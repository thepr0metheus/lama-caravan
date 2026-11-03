//! What may go from the models folder, and who holds a model while a move or a deletion asks.

#![allow(
    clippy::unwrap_used,
    clippy::panic,
    clippy::indexing_slicing,
    reason = "a helper of a test may stop where it found something wrong"
)]

use super::*;

#[test]
fn the_parts_of_a_file_are_one_group() {
    assert_eq!(ModelGc::part_group("a/b-00001-of-00003.gguf"), "a/b-*-of-00003.gguf");
    assert_eq!(ModelGc::part_group("b-00002-of-00003.gguf"), "b-*-of-00003.gguf");
    assert_eq!(ModelGc::part_group("a/b.gguf"), "a/b.gguf");
}

#[test]
fn one_owner_is_said_once() {
    let mut found = References::default();
    found.add(Some(&json!("/a/b.gguf")), "h:1");
    found.add(Some(&json!("a/b.gguf")), "h:1");
    found.add(Some(&json!("a/b.gguf")), "h:2");
    found.add(Some(&json!(" ")), "h:3");
    assert_eq!(found.owners.get("a/b.gguf").unwrap(), &["h:1", "h:2"]);
    assert_eq!(found.refs.len(), 1);
}

/// The topology of the tests below: cells by `(host, port, config)` and machines by what they reported.
fn topology(app: &App, cells: &[(&str, i64, Value)], hosts: Value) {
    let slots: Map<String, Value> = cells
        .iter()
        .map(|(host, port, config)| (format!("{host}:{port}"), json!({"hostId": host, "port": port, "config": config})))
        .collect();
    app.admin.saving(|doc| doc.insert("topology".to_string(), json!({"serverSlots": slots, "hosts": hosts})));
}

fn put(app: &App, rel: &str, bytes: &[u8]) -> PathBuf {
    let path = app.models_dir().join(rel);
    std::fs::create_dir_all(path.parent().unwrap()).unwrap();
    std::fs::write(&path, bytes).unwrap();
    path
}

fn controller(name: &str) -> (crate::tests::TestFolder, std::sync::Arc<App>) {
    let folder = crate::tests::TestFolder::new(&format!("gc-{name}"));
    let app = crate::tests::TestApp::over(&folder.path, &[]);
    (folder, app)
}

/// A clock that stands, so that "reported just now" stays so.
fn controller_at(name: &str, now: u64) -> (crate::tests::TestFolder, std::sync::Arc<App>) {
    let folder = crate::tests::TestFolder::new(&format!("gc-{name}"));
    let app = crate::tests::TestApp::with_clock(&folder.path, &[], crate::tests::HandClock::at(now));
    (folder, app)
}

fn refused(app: &App, files: Value) -> Option<(u16, String)> {
    ModelGc::of(app).delete(&json!({"files": files})).err().map(|error| (error.status, error.message))
}

#[test]
fn a_model_a_cell_names_is_not_deleted_nor_any_part_of_its_group() {
    let (_folder, app) = controller("named");
    let first = put(&app, "R/r-00001-of-00002.gguf", b"1");
    let second = put(&app, "R/r-00002-of-00002.gguf", b"2");
    let plain = put(&app, "C/c.gguf", b"3");
    topology(
        &app,
        &[("box", 1, json!({"MODEL_FILE": "R/r-00002-of-00002.gguf"})), ("box", 2, json!({"MMPROJ_FILE": "C/c.gguf"}))],
        json!({}),
    );
    for rel in ["R/r-00001-of-00002.gguf", "R/r-00002-of-00002.gguf", "C/c.gguf"] {
        let (status, words) = refused(&app, json!([rel])).unwrap();
        assert_eq!(status, 409, "{rel}");
        assert!(words.contains("referenced"), "{words}");
    }
    assert!(first.exists() && second.exists() && plain.exists());
}

#[test]
fn another_spelling_of_a_named_model_is_refused_as_it_is() {
    let (_folder, app) = controller("spelled");
    let model = put(&app, "R/r.gguf", b"1");
    let part = put(&app, "S/s-00001-of-00002.gguf", b"2");
    put(&app, "S/s-00002-of-00002.gguf", b"3");
    let cache = put(&app, "whisper/models--Systran--faster-whisper-large-v3/blobs/x", b"4");
    topology(
        &app,
        &[
            ("box", 1, json!({"MODEL_FILE": "R/r.gguf"})),
            ("box", 2, json!({"MODEL_FILE": "S/s-00002-of-00002.gguf"})),
            ("box", 3, json!({"RUNNER": "whisper"})),
        ],
        json!({}),
    );
    for rel in [
        "R/../R/r.gguf",
        "./R/r.gguf",
        "R//r.gguf",
        "/R/r.gguf",
        " R/r.gguf ",
        "none/../R/r.gguf",
        "S/../S/s-00001-of-00002.gguf",
        "./S/s-00001-of-00002.gguf",
        "whisper/models--Systran--faster-whisper-large-v3/",
    ] {
        assert_eq!(refused(&app, json!([rel])).map(|said| said.0), Some(409), "{rel}");
    }
    assert!(model.exists() && part.exists() && cache.exists());
}

#[test]
fn a_link_to_a_named_model_is_refused_and_a_link_out_of_the_models_folder_too() {
    let (folder, app) = controller("links");
    let model = put(&app, "R/r.gguf", b"1");
    std::os::unix::fs::symlink("R/r.gguf", app.models_dir().join("alias.gguf")).unwrap();
    topology(&app, &[("box", 1, json!({"MODEL_FILE": "R/r.gguf"}))], json!({}));
    assert_eq!(refused(&app, json!(["alias.gguf"])).map(|said| said.0), Some(409), "it comes to the named model");
    assert!(model.exists());
    let secret = folder.path.join("secret.gguf");
    std::fs::write(&secret, b"s").unwrap();
    std::os::unix::fs::symlink(&secret, app.models_dir().join("out.gguf")).unwrap();
    assert!(refused(&app, json!(["out.gguf"])).unwrap().1.contains("escapes"));
    assert!(secret.exists());
    assert!(refused(&app, json!(["../secret.gguf"])).unwrap().1.contains("escapes"));
    assert!(secret.exists());
}

#[test]
fn only_a_model_can_be_deleted_and_only_when_it_was_asked_for_by_name() {
    let (_folder, app) = controller("kinds");
    let note = put(&app, "A/notes.txt", b"n");
    let folder_of_models = put(&app, "A/a.gguf", b"a");
    for files in [json!(null), json!([]), json!("A/a.gguf")] {
        assert!(refused(&app, files.clone()).unwrap().1.contains("non-empty list"), "{files}");
    }
    assert!(refused(&app, json!(["A/notes.txt"])).unwrap().1.contains("not a gguf"));
    assert!(refused(&app, json!(["A"])).unwrap().1.contains("not a gguf"), "a folder of GGUFs is no model of its own");
    assert!(note.exists() && folder_of_models.exists());
}

#[test]
fn what_nobody_names_goes_and_the_answer_says_what_went() {
    let (_folder, app) = controller("goes");
    let gguf = put(&app, "A/a.gguf", &vec![b'a'; 1 << 20]);
    let cache = put(&app, "whisper/models--x/blobs/one", &vec![b'b'; 1 << 20]);
    put(&app, "Keep/k.gguf", b"k");
    let said = ModelGc::of(&app).delete(&json!({"files": ["A/a.gguf", "gone.gguf", "whisper/models--x"]})).unwrap();
    assert_eq!(
        said,
        json!({"ok": true, "deleted": ["A/a.gguf", "whisper/models--x"], "freedGb": 0.0}),
        "gone already is not said to be deleted"
    );
    assert!(!gguf.exists() && !cache.parent().unwrap().parent().unwrap().exists());
    assert!(app.models_dir().join("Keep/k.gguf").exists());
}

#[test]
fn a_cell_is_taken_to_be_reading_unless_its_machine_says_otherwise() {
    let (_folder, app) = controller_at("running", 100_000);
    let now = 100_000;
    topology(
        &app,
        &[],
        json!({
            "box": {"lastSeen": now, "llamaNodes": [
                {"port": 22031, "running": true},
                {"port": 22032, "running": false, "phase": "loading"},
                {"port": 22033, "running": false, "phase": "error"},
                {"port": 22037, "running": false, "phase": "downloading"},
            ]},
            "gone": {"lastSeen": now - 90_000, "llamaNodes": [{"port": 22035, "running": false}]},
            "never": {"llamaNodes": []},
        }),
    );
    let asked: BTreeSet<String> = [
        "box:22031",
        "box:22032",
        "box:22033",
        "box:22034",
        "box:22037",
        "gone:22035",
        "never:22038",
        "nobody:22036",
        "controller:22001",
    ]
    .iter()
    .map(|who| (*who).to_string())
    .collect();
    let busy: Vec<String> = ModelGc::of(&app).running_owners(asked).into_iter().collect();
    assert_eq!(
        busy,
        ["box:22031", "box:22032", "box:22037", "controller:22001", "gone:22035", "never:22038", "nobody:22036"],
        "running or about to; a report too old or none at all: not known, and taken for yes; failed or not in its report: free"
    );
}

#[test]
fn who_holds_a_file_is_asked_by_its_group_and_named() {
    let (_folder, app) = controller_at("holders", 100_000);
    topology(
        &app,
        &[
            ("box", 22001, json!({"MODEL_FILE": "C/c.gguf"})),
            ("box", 22002, json!({"MODEL_FILE": "D/d-00001-of-00002.gguf"})),
            ("hotel", 22021, json!({"MODEL_FILE": "D/d-00001-of-00002.gguf"})),
            ("box", 22003, json!({"MODEL_FILE": "E/e.gguf"})),
        ],
        json!({"box": {"lastSeen": 100_000, "llamaNodes": [{"port": 22001, "running": true}, {"port": 22003, "running": false, "phase": "error"}]}}),
    );
    let gc = ModelGc::of(&app);
    let ask = |rel: &str| gc.holders(&[rel.to_string()]);
    assert_eq!(ask("C/c.gguf"), ["box:22001"]);
    assert_eq!(ask("E/e.gguf"), Vec::<String>::new(), "its cell fell: the model may travel");
    assert_eq!(
        ask("D/d-00002-of-00002.gguf"),
        ["hotel:22021"],
        "the other part; a machine with no report; a stopped cell does not hold it"
    );
    assert_eq!(ask("A/a.gguf"), Vec::<String>::new());
    assert_eq!(gc.holders(&[]), Vec::<String>::new());
}

#[test]
fn what_a_cell_names_counts_whichever_way_it_names_it() {
    let (_folder, app) = controller("names");
    let root = app.models_dir().to_string_lossy().into_owned();
    topology(
        &app,
        &[
            ("h", 1, json!({"MODEL_FILE": "/a/m.gguf", "MMPROJ_FILE": "a/p.gguf", "SPEC_DRAFT_MODEL_FILE": "a/d.gguf"})),
            ("h", 2, json!({"RUNNER": "vllm", "VLLM_MODEL": format!("{root}/ck/pt/")})),
            ("h", 3, json!({"RUNNER": "vllm", "VLLM_MODEL": "/elsewhere/ckpt"})),
            ("h", 4, json!({"RUNNER": "whisper"})),
            ("h", 5, json!({"RUNNER": "Whisper", "WHISPER_MODEL": "tiny"})),
            ("h", 6, json!({"RUNNER": "translate"})),
        ],
        json!({}),
    );
    let found = ModelGc::of(&app).references();
    let refs: Vec<&str> = found.refs.iter().map(String::as_str).collect();
    assert_eq!(
        refs,
        [
            "a/d.gguf",
            "a/m.gguf",
            "a/p.gguf",
            "ck/pt",
            "translate/models--facebook--nllb-200-distilled-600M",
            "whisper/models--Systran--faster-whisper-large-v3",
            "whisper/models--Systran--faster-whisper-tiny",
        ]
    );
    assert_eq!(found.owners["a/m.gguf"], ["h:1"]);
}

#[test]
fn the_list_says_of_each_model_who_names_it_and_who_reads_it() {
    let (_folder, app) = controller_at("list", 100_000);
    put(&app, "A/a.gguf", b"aa");
    put(&app, "B/b-00001-of-00002.gguf", b"b");
    put(&app, "B/b-00002-of-00002.gguf", b"bb");
    put(&app, "whisper/models--x/blobs/one", b"xxx");
    topology(
        &app,
        &[("box", 1, json!({"MODEL_FILE": "B/b-00002-of-00002.gguf"})), ("box", 2, json!({"MODEL_FILE": "whisper/models--x"}))],
        json!({"box": {"lastSeen": 100_000, "llamaNodes": [{"port": 1, "running": true}]}}),
    );
    let listing = ModelGc::of(&app).list_unused();
    let rows = listing["files"].as_array().unwrap();
    let row = |path: &str| rows.iter().find(|row| row["path"] == path).unwrap();
    assert_eq!(
        (&row("A/a.gguf")["referenced"], &row("A/a.gguf")["sizeBytes"], &row("A/a.gguf")["group"]),
        (&json!(false), &json!(2), &json!("A/a.gguf"))
    );
    let part = row("B/b-00001-of-00002.gguf");
    assert_eq!(
        (&part["referenced"], &part["referencedBy"], &part["readBy"]),
        (&json!(true), &json!(["box:1"]), &json!(["box:1"])),
        "by its sister"
    );
    assert_eq!(part["group"], json!("B/b-*-of-00002.gguf"));
    let cache = row("whisper/models--x");
    assert_eq!(
        (&cache["kind"], &cache["sizeBytes"], &cache["referencedBy"], &cache["readBy"]),
        (&json!("whisper"), &json!(3), &json!(["box:2"]), &json!([])),
        "named, and stopped"
    );
    assert_eq!(listing["unusedCount"], json!(1));
    std::fs::remove_dir_all(app.models_dir()).unwrap();
    let none = ModelGc::of(&app).list_unused();
    assert_eq!(
        (&none["ok"], &none["error"], &none["files"]),
        (&json!(false), &json!("models dir not found"), &json!([])),
        "not an empty folder"
    );
}
