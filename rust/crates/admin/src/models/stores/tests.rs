//! Where models live and whether each place is there: the rule, the registry and the memory of its looks, over folders of the test's own. A folder that
//! has to do what no folder can (hang, say another's mark) says it in `StoreProbe::SAYS`; the rest is looked at as a child would.

use super::super::hf::HubBrowser;
use super::super::locator::Locations;
use super::super::model_list::ModelList;
use super::super::store_probe::MARKER_NAME;
use super::*;
use crate::tests::{HandClock, TestApp, TestFolder};
use std::path::PathBuf;
use std::sync::Arc;
use std::time::{Duration, SystemTime};

const GB: i64 = 1 << 30;
const NOW: u64 = 8_640_000;
const DAY: u64 = 86_400;
const TTL: u64 = StoreRegistry::TTL as u64;

struct Stand {
    folder: TestFolder,
    clock: Arc<HandClock>,
    app: Arc<App>,
}

impl Stand {
    fn new(name: &str) -> Self {
        let folder = TestFolder::new(&format!("stores-{name}"));
        let clock = HandClock::at(NOW);
        let app = TestApp::with_clock(&folder.path, &[], clock.clone());
        Self { folder, clock, app }
    }

    fn registry(&self) -> StoreRegistry<'_> {
        StoreRegistry::of(&self.app)
    }

    /// A folder of the test's, there.
    fn dir(&self, name: &str) -> String {
        let path = self.folder.path.join(name);
        std::fs::create_dir_all(&path).unwrap();
        path.to_string_lossy().into_owned()
    }

    /// This folder's looks and claims come to `doc`.
    fn says(&self, root: &str, doc: &Value) {
        std::fs::write(PathBuf::from(root).join(StoreProbe::SAYS), doc.to_string()).unwrap();
    }

    fn local(&self) -> String {
        self.app.models_dir().to_string_lossy().into_owned()
    }

    fn added(&self, root: &str, name: &str, force: bool) -> Value {
        match self.registry().add(root, name, force) {
            Ok(row) => row,
            Err(refused) => panic!("{root} refused: {} {}", refused.code, refused.error.message),
        }
    }

    /// A library whose every look comes to `doc` with its own mark in it.
    fn library_saying(&self, name: &str, label: &str, doc: &Value) -> (String, String) {
        let root = self.dir(name);
        let marked = |id: &str, doc: &Value| {
            let mut doc = doc.clone();
            doc["marker"] = json!({"id": id, "name": label});
            doc
        };
        self.says(
            &root,
            &json!({"ok": true, "exists": true, "adopted": false, "marker": {"id": format!("lib-{name}"), "name": label}}),
        );
        let id = Coerce::text(self.added(&root, label, false).get("id"));
        self.says(&root, &marked(&id, doc));
        (id, root)
    }

    fn saved_stores(&self) -> Value {
        self.app.admin.read(|doc| doc.get("modelStores").cloned()).unwrap_or(Value::Null)
    }

    fn row(&self, rows: &[Value], id: &str) -> Value {
        rows.iter().find(|row| row["id"] == json!(id)).unwrap().clone()
    }

    fn refreshing(&self, held: bool) {
        *self.app.store_memory.refreshing.lock().unwrap() = held;
    }

    fn refresh_ended(&self) {
        for _ in 0..5000 {
            if !*self.app.store_memory.refreshing.lock().unwrap() {
                return;
            }
            std::thread::sleep(Duration::from_millis(2));
        }
        panic!("the look behind the answer did not end");
    }
}

fn refused(tried: Result<Value, StoreRefused>) -> (String, u16) {
    match tried {
        Ok(row) => panic!("not refused: {row}"),
        Err(refused) => (refused.code, refused.error.status),
    }
}

fn store(role: &'static str) -> ModelStore {
    ModelStore {
        id: if role == "local" { "local" } else { "lib-a" }.to_string(),
        name: "NAS".to_string(),
        path: "/mnt/lib".to_string(),
        role,
        builtin: role == "local",
    }
}

/// What a look at a healthy folder says, with `more` laid over it, as the rule reads it.
fn judged(role: &'static str, more: &Value) -> Map<String, Value> {
    let mut probe = json!({"ok": true, "exists": true, "writable": true, "free": 900 * GB, "total": 1000 * GB});
    Coerce::extend(&mut probe, more);
    StoreStatus::judge(&store(role), &probe, 100).to_json()
}

#[test]
fn a_library_in_its_place_with_room_is_ok_and_says_its_figures() {
    let folder = json!({"name": "m", "bytes": 7 * GB, "files": 3});
    let ok = judged("library", &json!({"marker": {"id": "lib-a"}, "files": 3, "bytes": 7 * GB, "folders": [folder], "more": 0}));
    assert_eq!(
        (&ok["state"], &ok["free"], &ok["files"], &ok["size"], &ok["folders"][0]["name"]),
        (&json!("ok"), &json!(900 * GB), &json!(3), &json!(7 * GB), &json!("m"))
    );
    assert_eq!(ok["checkedAt"], json!(100));
}

#[test]
fn a_library_with_no_mark_is_not_mounted_and_has_no_figure_for_they_would_be_the_local_disks() {
    let bare = judged("library", &json!({"marker": null, "files": 3, "bytes": 5}));
    assert_eq!(bare["state"], json!("not-mounted"));
    for key in ["free", "total", "files", "size", "folders"] {
        assert!(!bare.contains_key(key), "{key}: {bare:?}");
    }
    assert_eq!(judged("library", &json!({"marker": {}}))["state"], json!("not-mounted"), "an empty mark is no mark");
    assert_eq!(judged("library", &json!({"marker": "lib-a"}))["state"], json!("not-mounted"), "nor is a word");
}

#[test]
fn another_librarys_mark_is_foreign_with_its_name_and_no_figure() {
    let foreign = judged("library", &json!({"marker": {"id": "lib-b", "name": "other"}}));
    assert_eq!(foreign["state"], json!("foreign"));
    assert!(foreign["detail"].as_str().unwrap().contains("other"), "{foreign:?}");
    assert!(!foreign.contains_key("free"));
    let unnamed = judged("library", &json!({"marker": {"id": "lib-b"}}));
    assert!(unnamed["detail"].as_str().unwrap().contains("lib-b"), "{unnamed:?}");
}

#[test]
fn the_controllers_own_folder_needs_no_mark() {
    let local = judged("local", &json!({"marker": null}));
    assert_eq!((&local["state"], &local["free"]), (&json!("ok"), &json!(900 * GB)));
}

#[test]
fn a_folder_that_cannot_be_written_is_read_only_with_its_figures() {
    let read_only = judged("library", &json!({"marker": {"id": "lib-a"}, "writable": false}));
    assert_eq!((&read_only["state"], &read_only["free"]), (&json!("read-only"), &json!(900 * GB)));
}

#[test]
fn low_space_is_strictly_below_the_line_and_the_line_itself_is_ok() {
    let line = 50 * GB;
    let word = |free: i64| judged("library", &json!({"marker": {"id": "lib-a"}, "free": free}))["state"].clone();
    assert_eq!(word(line - 1), json!("low-space"));
    assert_eq!(word(line), json!("ok"));
    assert_eq!(word(line + 1), json!("ok"));
    let said = judged("library", &json!({"marker": {"id": "lib-a"}, "free": 5 * GB}));
    assert_eq!(said["detail"], json!("5.0 GB free"));
}

#[test]
fn no_folder_is_said_with_its_path_and_a_probe_that_did_not_answer_is_unknown() {
    let missing = StoreStatus::judge(&store("library"), &json!({"ok": true, "exists": false}), 100).to_json();
    assert_eq!((&missing["state"], &missing["detail"]), (&json!("missing"), &json!("no directory at /mnt/lib")));
    let dead =
        StoreStatus::judge(&store("library"), &json!({"ok": false, "timeout": true, "error": "no answer in 8 s"}), 100).to_json();
    assert_eq!(
        (&dead["state"], &dead["detail"], &dead["checkedAt"]),
        (&json!("unknown"), &json!("no answer in 8 s"), &json!(100))
    );
    let nothing = StoreStatus::judge(&store("library"), &Value::Null, 5).to_json();
    assert_eq!(nothing["state"], json!("unknown"), "no answer at all is not ok");
}

#[test]
fn no_mark_goes_before_read_only_and_low_space_for_those_figures_are_of_the_wrong_folder() {
    let order = judged("library", &json!({"marker": null, "writable": false, "free": 1}));
    assert_eq!(order["state"], json!("not-mounted"));
    let foreign_first = judged("library", &json!({"marker": {"id": "lib-b"}, "writable": false, "free": 1}));
    assert_eq!(foreign_first["state"], json!("foreign"));
    let read_only_first = judged("library", &json!({"marker": {"id": "lib-a"}, "writable": false, "free": 1}));
    assert_eq!(read_only_first["state"], json!("read-only"));
}

#[test]
fn a_path_refused_on_its_face_is_refused_before_any_look_and_saves_nothing() {
    let stand = Stand::new("refused-early");
    let local = stand.local();
    let parent = stand.folder.path.to_string_lossy().into_owned();
    for (bad, want) in [
        ("".to_string(), ("no-path", 400)),
        ("   ".to_string(), ("no-path", 400)),
        ("mnt/lib".to_string(), ("not-absolute", 400)),
        (local.clone(), ("duplicate", 409)),
        (format!("{local}/"), ("duplicate", 409)),
        (format!("{local}/nas"), ("nested", 409)),
        (parent, ("nested", 409)),
    ] {
        assert_eq!(refused(stand.registry().add(&bad, "x", true)), (want.0.to_string(), want.1), "{bad:?}");
    }
    assert_eq!(stand.saved_stores(), Value::Null, "not one write of the state");
    assert!(!stand.app.models_dir().join("nas").exists());
    assert!(!stand.folder.path.join(MARKER_NAME).exists(), "and no mark on the folder above the models");
}

#[test]
fn a_bare_folder_is_refused_with_no_mark_written_and_a_confirmed_one_is_marked() {
    let stand = Stand::new("bare");
    let root = stand.dir("nas");
    assert_eq!(refused(stand.registry().add(&root, "NAS", false)), ("not-a-mount".to_string(), 409));
    assert!(
        !PathBuf::from(&root).join(MARKER_NAME).exists(),
        "if the share did not mount, a mark would make the local disk pose as the library"
    );
    assert_eq!(stand.saved_stores(), Value::Null);
    let added = stand.added(&format!("{root}/"), "NAS library", true);
    let id = Coerce::text(added.get("id"));
    assert!(id.starts_with("lib-") && id.len() == 12, "{id}");
    assert_eq!(
        (&added["path"], &added["role"], &added["adopted"], &added["builtin"]),
        (&json!(root), &json!("library"), &json!(false), &json!(false)),
        "the path made normal"
    );
    let mark: Value = serde_json::from_slice(&std::fs::read(PathBuf::from(&root).join(MARKER_NAME)).unwrap()).unwrap();
    assert_eq!((&mark["id"], &mark["name"], &mark["role"]), (&json!(id), &json!("NAS library"), &json!("library")));
    assert_eq!(stand.saved_stores(), json!([{"id": id, "name": "NAS library", "path": root}]));
}

#[test]
fn a_library_with_no_name_takes_its_folders() {
    let stand = Stand::new("no-name");
    let root = stand.dir("shelf");
    assert_eq!(stand.added(&root, "  ", true)["name"], json!("shelf"));
}

#[test]
fn the_same_path_or_a_folder_inside_a_library_is_refused() {
    let stand = Stand::new("same-path");
    let root = stand.dir("nas");
    stand.added(&root, "NAS", true);
    assert_eq!(refused(stand.registry().add(&root, "again", true)), ("duplicate".to_string(), 409));
    assert_eq!(refused(stand.registry().add(&format!("{root}/inner"), "in", true)), ("nested".to_string(), 409));
    assert_eq!(stand.saved_stores().as_array().unwrap().len(), 1);
    let ids: Vec<&'static str> = stand.registry().stores().iter().map(|one| one.role).collect();
    assert_eq!(ids, ["local", "library"], "its own folder first, and never saved");
}

#[test]
fn a_mark_already_there_is_adopted_and_not_written_over() {
    let stand = Stand::new("adopted");
    let root = stand.dir("nas");
    let first = stand.added(&root, "Known", true);
    let id = Coerce::text(first.get("id"));
    let before = std::fs::read(PathBuf::from(&root).join(MARKER_NAME)).unwrap();
    stand.registry().remove(&id).ok().unwrap();
    let again = stand.added(&root, "typed name", false);
    assert_eq!(
        (&again["id"], &again["name"], &again["adopted"]),
        (&json!(id), &json!("Known"), &json!(true)),
        "the same library from another host stays itself"
    );
    assert_eq!(std::fs::read(PathBuf::from(&root).join(MARKER_NAME)).unwrap(), before);
}

#[test]
fn the_same_mark_by_a_second_path_is_refused() {
    let stand = Stand::new("second-path");
    let (first, second) = (stand.dir("first"), stand.dir("second"));
    let id = Coerce::text(stand.added(&first, "NAS", true).get("id"));
    std::fs::copy(PathBuf::from(&first).join(MARKER_NAME), PathBuf::from(&second).join(MARKER_NAME)).unwrap();
    let said = stand.registry().add(&second, "x", false);
    assert_eq!(refused(said), ("duplicate".to_string(), 409), "one library is never on the list twice");
    assert_eq!(stand.saved_stores().as_array().unwrap().len(), 1);
    assert_eq!(stand.saved_stores()[0]["id"], json!(id));
}

#[test]
fn a_probe_that_refuses_refuses_the_adding_and_nothing_is_saved() {
    let stand = Stand::new("claim-refused");
    let root = stand.dir("nas");
    for (answer, code, status) in [
        (json!({"ok": true, "exists": true, "refused": "not-a-mount"}), "not-a-mount", 409),
        (json!({"ok": true, "exists": false}), "missing", 404),
        (json!({"ok": false, "timeout": true, "error": "no answer in 8 s"}), "unreachable", 504),
        (json!({"ok": true, "exists": true, "refused": "not-writable", "error": "EROFS"}), "not-writable", 409),
        (Value::Null, "unreachable", 504),
    ] {
        stand.says(&root, &answer);
        assert_eq!(refused(stand.registry().add(&root, "x", false)), (code.to_string(), status), "{answer}");
        assert_eq!(stand.saved_stores(), Value::Null, "{answer}");
    }
}

#[test]
fn a_folder_not_there_and_a_mark_that_cannot_be_written_are_refusals_of_their_own() {
    let stand = Stand::new("claim-real");
    let gone = stand.folder.path.join("gone").to_string_lossy().into_owned();
    assert_eq!(refused(stand.registry().add(&gone, "x", true)), ("missing".to_string(), 404));
    let root = stand.dir("nas");
    // A folder where the mark's temporary file goes: a write that fails whoever runs the test, root too.
    std::fs::create_dir(PathBuf::from(&root).join(format!("{MARKER_NAME}.tmp"))).unwrap();
    assert_eq!(refused(stand.registry().add(&root, "x", true)), ("not-writable".to_string(), 409));
    assert_eq!(stand.saved_stores(), Value::Null);
}

#[test]
fn the_controllers_folder_cannot_be_removed_and_an_unknown_id_is_refused() {
    let stand = Stand::new("remove-refused");
    assert_eq!(refused(stand.registry().remove("local")), ("builtin".to_string(), 409));
    assert_eq!(refused(stand.registry().remove("lib-none")), ("unknown-id".to_string(), 404));
    let root = stand.dir("nas");
    stand.added(&root, "NAS", true);
    assert_eq!(refused(stand.registry().remove("lib-none")), ("unknown-id".to_string(), 404), "with a library on the list too");
    assert_eq!(stand.saved_stores().as_array().unwrap().len(), 1);
}

#[test]
fn taking_a_library_off_the_list_leaves_its_files_and_its_mark_and_it_is_found_again() {
    let stand = Stand::new("remove");
    let root = stand.dir("nas");
    std::fs::write(PathBuf::from(&root).join("m.gguf"), b"x").unwrap();
    let id = Coerce::text(stand.added(&root, "Other", true).get("id"));
    assert_eq!(stand.registry().remove(&id).ok(), Some(json!({"removed": id})));
    assert_eq!(stand.saved_stores(), json!([]));
    assert_eq!(stand.registry().stores().len(), 1, "off the list");
    assert!(PathBuf::from(&root).join(MARKER_NAME).exists() && PathBuf::from(&root).join("m.gguf").exists(), "not wiped");
    assert_eq!(stand.added(&root, "x", false)["id"], json!(id), "the same folder is found by its mark again");
}

#[test]
fn a_library_moves_to_a_folder_with_its_own_mark_in_one_write() {
    let stand = Stand::new("repath");
    let (old, new) = (stand.dir("old"), stand.dir("new"));
    let id = Coerce::text(stand.added(&old, "NAS", true).get("id"));
    std::fs::copy(PathBuf::from(&old).join(MARKER_NAME), PathBuf::from(&new).join(MARKER_NAME)).unwrap();
    let Ok(moved) = stand.registry().repath(&id, &format!("{new}/")) else { panic!("refused") };
    assert_eq!(moved["store"], json!({"id": id, "name": "NAS", "path": new}), "the path made normal");
    assert_eq!(stand.saved_stores(), json!([{"id": id, "name": "NAS", "path": new}]));
    std::fs::remove_file(PathBuf::from(&new).join(MARKER_NAME)).unwrap();
    let Ok(same) = stand.registry().repath(&id, &new) else { panic!("the same path looks at nothing, and so cannot be refused") };
    assert_eq!(same["store"]["path"], json!(new));
}

#[test]
fn a_move_to_anything_but_the_same_library_is_refused_and_the_path_stays() {
    let stand = Stand::new("repath-refused");
    let current = stand.dir("current");
    let id = Coerce::text(stand.added(&current, "NAS", true).get("id"));
    let other = stand.dir("other");
    stand.says(&other, &json!({"ok": true, "exists": true, "writable": true, "marker": {"id": "lib-zzz", "name": "Other"}}));
    let bare = stand.dir("bare");
    let dead = stand.dir("dead");
    stand.says(&dead, &json!({"ok": false, "timeout": true, "error": "no answer in 8 s"}));
    let gone = stand.folder.path.join("gone").to_string_lossy().into_owned();
    let local = stand.local();
    for (bad, code, status) in [
        (other, "other-library", 409),
        (bare, "not-a-mount", 409),
        (gone, "not-a-mount", 409),
        (dead, "unreachable", 504),
        ("mnt/rel".to_string(), "not-absolute", 400),
        (String::new(), "no-path", 400),
        (local.clone(), "duplicate", 409),
        (format!("{local}/inner"), "nested", 409),
    ] {
        assert_eq!(refused(stand.registry().repath(&id, &bad)), (code.to_string(), status), "{bad:?}");
    }
    assert_eq!(
        refused(stand.registry().repath("local", "/tmp/x")),
        ("builtin".to_string(), 409),
        "its own folder is changed on the page"
    );
    assert_eq!(refused(stand.registry().repath("lib-nope", &current)), ("unknown-id".to_string(), 404));
    assert_eq!(stand.saved_stores()[0]["path"], json!(current), "after all the refusals the path is what it was");
}

#[test]
fn the_memory_of_a_look_holds_for_its_time_and_a_new_look_comes_on_force_or_after_it() {
    let stand = Stand::new("memory");
    let look = |files: i64| json!({"ok": true, "exists": true, "writable": true, "free": 900 * GB, "total": 1000 * GB, "files": files, "bytes": GB, "folders": [], "more": 0});
    let (id, root) = stand.library_saying("nas", "NAS", &look(1));
    let files = |rows: Vec<Value>| stand.row(&rows, &id)["files"].clone();
    assert_eq!(files(stand.registry().statuses(false)), json!(1));
    let mut seen = look(2);
    seen["marker"] = json!({"id": id});
    stand.says(&root, &seen);
    assert_eq!(files(stand.registry().statuses(false)), json!(1), "within the memory no folder is gone to");
    stand.clock.pass(TTL - 1);
    assert_eq!(files(stand.registry().statuses(false)), json!(1));
    assert_eq!(files(stand.registry().statuses(true)), json!(2), "force measures anew");
    seen["files"] = json!(3);
    stand.says(&root, &seen);
    stand.clock.pass(TTL);
    assert_eq!(files(stand.registry().statuses(false)), json!(3), "the memory ended");
}

#[test]
fn a_row_of_status_is_the_store_and_its_look_and_its_own_folder_is_never_listed() {
    let stand = Stand::new("status-row");
    let local = stand.local();
    stand.says(&local, &json!({"ok": true, "exists": true, "writable": true, "free": 900 * GB, "total": 1000 * GB}));
    let (id, root) = stand.library_saying("nas", "NAS", &json!({"ok": true, "exists": true, "writable": true, "free": 900 * GB, "total": 1000 * GB, "files": 1, "bytes": GB, "folders": [], "more": 0}));
    let rows = stand.registry().statuses(false);
    assert_eq!(
        (&rows[0]["id"], &rows[0]["builtin"], &rows[0]["state"]),
        (&json!("local"), &json!(true), &json!("ok")),
        "{rows:?}"
    );
    assert_eq!(rows[0].get("files"), None);
    let library = stand.row(&rows, &id);
    assert_eq!(
        (&library["files"], &library["state"], &library["path"], &library["size"]),
        (&json!(1), &json!("ok"), &json!(root), &json!(GB))
    );
    assert!(
        rows.iter().all(|row| ["entries", "entriesMore", "dirs", "dirsMore"].iter().all(|key| row.get(*key).is_none())),
        "the list goes to the tree, and the panel is drawn after every action"
    );
}

#[test]
fn only_a_library_is_asked_what_it_holds() {
    let stand = Stand::new("listing-asked");
    let root = stand.dir("nas");
    std::fs::write(PathBuf::from(&root).join("m.gguf"), b"xx").unwrap();
    std::fs::write(stand.app.models_dir().join("local.gguf"), b"xxx").unwrap();
    let id = Coerce::text(stand.added(&root, "NAS", true).get("id"));
    let rows = stand.registry().statuses(false);
    assert_eq!(rows[0].get("files"), None, "its own disk: the state alone, and no walk: {:?}", rows[0]);
    assert_eq!(stand.row(&rows, &id)["files"], json!(1));
}

#[test]
fn a_path_that_moved_is_measured_anew_and_the_old_look_is_not_handed_out_for_it() {
    let stand = Stand::new("moved");
    let root = stand.dir("nas");
    std::fs::write(PathBuf::from(&root).join("m.gguf"), b"xx").unwrap();
    let id = Coerce::text(stand.added(&root, "NAS", true).get("id"));
    stand.registry().statuses(false);
    let gone = stand.folder.path.join("gone").to_string_lossy().into_owned();
    stand.app.admin.saving(|doc| doc.insert("modelStores".to_string(), json!([{"id": id, "name": "NAS", "path": gone}])));
    stand.refreshing(true);
    let unmeasured = stand.registry().library_files(false, false);
    assert_eq!(
        (&unmeasured[0]["state"], &unmeasured[0]["files"]),
        (&json!("unknown"), &json!([])),
        "the new path has no look yet"
    );
    let rows = stand.registry().statuses(false);
    assert_eq!((&stand.row(&rows, &id)["state"], &stand.row(&rows, &id)["path"]), (&json!("missing"), &json!(gone)));
}

/// A library's memory as a look at it left it.
fn looked(stand: &Stand, id: &str, root: &str, probe: &Value) {
    let status = StoreStatus::judge(
        &ModelStore { id: id.to_string(), name: "x".to_string(), path: root.to_string(), role: "library", builtin: false },
        probe,
        NOW as i64,
    );
    let at = stand.app.now();
    stand.registry().cache().insert(id.to_string(), (root.to_string(), status, at));
}

#[test]
fn a_library_says_its_files_and_model_folders_with_their_age_and_what_is_left_out() {
    let stand = Stand::new("library-files");
    let (id, root) = ("lib-a".to_string(), "/mnt/lib".to_string());
    stand.app.admin.saving(|doc| doc.insert("modelStores".to_string(), json!([{"id": id, "name": "NAS", "path": root}])));
    let now = NOW as i64;
    looked(
        &stand,
        &id,
        &root,
        &json!({
            "ok": true, "exists": true, "writable": true, "free": 900 * GB, "total": 1000 * GB, "marker": {"id": id},
            "entries": [["A/a/Q4/a.gguf", 10, now - 3 * DAY as i64], ["b.gguf", 20, now + 50]], "entriesMore": 4,
            "dirs": [["whisper/models--openai--whisper", "whisper", 70, now - DAY as i64]], "dirsMore": 2
        }),
    );
    stand.refreshing(true);
    let rows = stand.registry().library_files(false, false);
    assert_eq!(rows.len(), 1, "libraries alone: its own disk the tree draws anyway");
    assert_eq!(
        rows[0]["files"],
        json!([
            {"path": "A/a/Q4/a.gguf", "size": 10, "ageDays": 3, "mtime": now - 3 * DAY as i64},
            {"path": "b.gguf", "size": 20, "ageDays": 0, "mtime": now + 50},
            {"path": "whisper/models--openai--whisper", "kind": "whisper", "size": 70, "ageDays": 1, "mtime": now - DAY as i64}
        ]),
        "a time from the future is age zero, and no minus"
    );
    assert_eq!(
        (&rows[0]["more"], &rows[0]["state"], &rows[0]["name"], &rows[0]["path"]),
        (&json!(6), &json!("ok"), &json!("NAS"), &json!(root)),
        "what is left out, files and folders together, and the root this host reads"
    );
}

#[test]
fn a_library_not_mounted_names_no_file_whatever_lies_under_its_mount_point() {
    let stand = Stand::new("not-mounted-files");
    let root = stand.dir("nas");
    std::fs::write(PathBuf::from(&root).join("local-disk.gguf"), b"x").unwrap();
    let id = Coerce::text(stand.added(&root, "Old", true).get("id"));
    std::fs::remove_file(PathBuf::from(&root).join(MARKER_NAME)).unwrap();
    let rows = stand.registry().library_files(true, true);
    assert_eq!(
        (&rows[0]["id"], &rows[0]["state"], &rows[0]["files"]),
        (&json!(id), &json!("not-mounted"), &json!([])),
        "that would be the local disk"
    );
    let foreign = json!({"id": "lib-other", "name": "Other"});
    std::fs::write(PathBuf::from(&root).join(MARKER_NAME), foreign.to_string()).unwrap();
    let rows = stand.registry().library_files(true, true);
    assert_eq!((&rows[0]["state"], &rows[0]["files"]), (&json!("foreign"), &json!([])));
    assert_eq!(Locations::new(&rows, "/h").library_copies().len(), 0);
}

#[test]
fn a_library_in_its_place_is_walked_and_its_files_reach_the_locator() {
    let stand = Stand::new("walked");
    let root = stand.dir("nas");
    std::fs::create_dir_all(PathBuf::from(&root).join("M/a/Q4")).unwrap();
    let file = PathBuf::from(&root).join("M/a/Q4/m.gguf");
    std::fs::write(&file, b"xxx").unwrap();
    let id = Coerce::text(stand.added(&root, "NAS", true).get("id"));
    let moment = SystemTime::UNIX_EPOCH + Duration::from_secs(NOW - 2 * DAY);
    std::fs::File::options().write(true).open(&file).unwrap().set_modified(moment).unwrap();
    let rows = stand.registry().library_files(false, true);
    assert_eq!(rows[0]["files"], json!([{"path": "M/a/Q4/m.gguf", "size": 3, "ageDays": 2, "mtime": NOW - 2 * DAY}]));
    let locations = Locations::new(&rows, "/h");
    assert_eq!(locations.library_copies().len(), 1);
    let at = locations.locate("M/a/Q4/m.gguf", "/nowhere").unwrap();
    assert!(at.in_library(), "{at:?}");
    assert_eq!(at.store.unwrap().id, id);
}

#[test]
fn without_waiting_the_last_look_is_read_as_it_is_and_a_stale_one_is_measured_behind_the_answer() {
    let stand = Stand::new("behind");
    let root = stand.dir("nas");
    let first = PathBuf::from(&root).join("first.gguf");
    std::fs::write(&first, b"x").unwrap();
    stand.added(&root, "NAS", true);
    stand.registry().statuses(false);
    std::fs::remove_file(&first).unwrap();
    std::fs::write(PathBuf::from(&root).join("second.gguf"), b"x").unwrap();
    stand.clock.pass(TTL + 1);
    // Held: the look behind the answer does not start, so what this read gives is the last look, by no race.
    stand.refreshing(true);
    let stale = stand.registry().library_files(false, false);
    assert_eq!(stale[0]["files"][0]["path"], json!("first.gguf"), "as it is");
    stand.refreshing(false);
    stand.registry().library_files(false, false);
    stand.refresh_ended();
    let fresh = stand.registry().library_files(false, false);
    assert_eq!(fresh[0]["files"][0]["path"], json!("second.gguf"), "the next question sees the new look");
}

#[test]
fn while_one_look_goes_behind_the_answers_no_second_starts_for_a_dead_share_must_not_pile_threads() {
    let stand = Stand::new("one-at-a-time");
    let root = stand.dir("nas");
    std::fs::write(PathBuf::from(&root).join("first.gguf"), b"x").unwrap();
    stand.added(&root, "NAS", true);
    stand.refreshing(true);
    assert_eq!(stand.registry().library_files(false, false)[0]["files"], json!([]), "never measured: nothing, and no wait");
    assert_eq!(stand.registry().library_files(false, false)[0]["state"], json!("unknown"));
    // A look started in spite of the flag would have ended by now, and left its mark.
    std::thread::sleep(Duration::from_millis(50));
    assert!(*stand.app.store_memory.refreshing.lock().unwrap(), "still the one that was going");
    assert!(stand.registry().cache().is_empty(), "and nothing was measured");
    stand.refreshing(false);
    assert!(stand.registry().library_files(false, true)[0]["files"][0].get("path").is_some(), "waiting measures now");
}

#[test]
fn a_look_that_is_fresh_starts_nothing_behind_the_answer() {
    let stand = Stand::new("fresh-no-look");
    let root = stand.dir("nas");
    stand.added(&root, "NAS", true);
    stand.registry().statuses(false);
    stand.registry().library_files(false, false);
    assert!(!*stand.app.store_memory.refreshing.lock().unwrap(), "nothing stale, nothing started");
}

#[test]
fn a_store_that_does_not_answer_says_so_and_what_it_is_mounted_from_and_a_healthy_one_does_not() {
    let stand = Stand::new("dead");
    let local = stand.local();
    stand.says(&local, &json!({"ok": true, "exists": true, "writable": true, "free": 900 * GB, "total": 1000 * GB}));
    let (id, root) = stand.library_saying("nas", "NAS", &json!({"ok": false, "timeout": true, "error": "no answer in 8 s"}));
    stand.says(&root, &json!({"ok": false, "timeout": true, "error": "no answer in 8 s"}));
    let rows = stand.registry().statuses(true);
    let library = stand.row(&rows, &id);
    assert_eq!((&library["state"], &library["detail"]), (&json!("unknown"), &json!("no answer in 8 s")));
    assert_eq!(library["mount"]["source"], json!(""), "a section of what it is mounted from: {library}");
    assert!(rows[0].get("mount").is_none(), "nothing to explain for a healthy one: {:?}", rows[0]);
    let files = stand.registry().library_files(false, true);
    assert_eq!((&files[0]["state"], &files[0]["files"]), (&json!("unknown"), &json!([])), "and it names no file");
}

#[test]
fn what_hf_says_of_the_libraries_is_the_last_look_and_it_never_waits_for_a_share() {
    let stand = Stand::new("local-check-no-wait");
    let root = PathBuf::from(stand.dir("nas"));
    for rel in ["M/a/Q4/m.gguf", "M/a-extra/Q4/other-author.gguf", "M-extra/a/Q4/other-model.gguf", "M/a/Q4/notes.txt"] {
        let path = root.join(rel);
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        std::fs::write(path, b"xx").unwrap();
    }
    stand.added(&root.to_string_lossy(), "NAS", true);
    // Held: were the read to wait, it would measure here and now, and the file would show.
    stand.refreshing(true);
    let browser = HubBrowser::of(&stand.app);
    assert_eq!(
        browser.local_check("a/M")["libraryFiles"],
        json!({}),
        "a dead NAS must not hold this request: no look yet, so nothing yet"
    );
    assert!(stand.registry().cache().is_empty(), "and it went to no folder");
    stand.refreshing(false);
    stand.registry().statuses(false);
    let got = browser.local_check("a/M");
    assert_eq!(
        got["libraryFiles"].as_object().unwrap().keys().collect::<Vec<_>>(),
        ["m.gguf"],
        "this author's folder of this model, its GGUFs alone: {got}"
    );
    assert_eq!(got["libraryFiles"]["m.gguf"][0]["size"], json!(2));
    assert_eq!(got["libraryFiles"]["m.gguf"][0]["store"]["name"], json!("NAS"));
}

#[test]
fn what_the_board_and_the_picker_read_never_waits_and_a_start_does() {
    let stand = Stand::new("locations");
    let root = stand.dir("nas");
    std::fs::write(PathBuf::from(&root).join("m.gguf"), b"x").unwrap();
    stand.added(&root, "NAS", true);
    stand.refreshing(true);
    assert_eq!(ModelList::locations(&stand.app, false).library_copies().len(), 0);
    assert_eq!(ModelList::locations(&stand.app, true).library_copies().len(), 1);
}

#[test]
fn a_mount_table_says_who_stands_last_at_a_path_and_what_cannot_be_knocked_on_is_unknown() {
    let table = "25 30 0:22 / /proc rw,nosuid - proc proc rw\n\
                 31 25 0:26 / /mnt/lib rw,relatime - nfs4 192.0.2.30:/volume1/lib rw,vers=4.1\n\
                 32 25 0:27 / /mnt/lib rw,relatime - nfs4 nas.lan:/volume1/lib rw,vers=4.1\n\
                 33 25 0:28 / /mnt/smb rw,relatime - cifs //nas.lan/share rw\n\
                 34 25 0:29 / /mnt/disk rw,relatime - ext4 /dev/sdb1 rw\n\
                 35 25 0:30 / /mnt/odd rw,relatime - fuse.odd odd-fs rw\n";
    let mounted = |path: &str| MountFacts::mounted(path, table);
    assert_eq!(
        mounted("/mnt/lib"),
        Some(("nas.lan:/volume1/lib".to_string(), "nfs4".to_string())),
        "mounts stack, and a reader gets the last"
    );
    assert_eq!(mounted("/mnt/nothing"), None);
    assert_eq!(MountFacts::host("nas.lan:/volume1/lib"), "nas.lan");
    assert_eq!(MountFacts::host("//nas.lan/share"), "nas.lan");
    assert_eq!(MountFacts::host("/dev/sdb1"), "", "a device names no machine");
    assert_eq!(MountFacts::host("odd-fs"), "");
    assert_eq!(
        (MountFacts::port("nfs4"), MountFacts::port("nfs"), MountFacts::port("cifs"), MountFacts::port("smb3")),
        (Some(2049), Some(2049), Some(445), Some(445))
    );
    assert_eq!(MountFacts::port("fuse.odd"), None, "no port for that kind: not knocked on, and not called silent");
    let fstab = "# comment\nnas.lan:/volume1/lib /mnt/lib nfs4 defaults 0 0\n/dev/sdb1 /mnt/disk ext4 defaults 0 0\n";
    assert!(MountFacts::in_fstab("/mnt/lib", fstab) && !MountFacts::in_fstab("/mnt/nothing", fstab));
    assert!(!MountFacts::in_fstab("comment", fstab), "a comment names nothing");
}

fn library() -> ModelStore {
    ModelStore { id: "lib".to_string(), name: "L".to_string(), path: "/l".to_string(), role: "library", builtin: false }
}

#[test]
fn a_look_comes_to_one_word() {
    let word = |probe: Value| StoreStatus::judge(&library(), &probe, 1).state;
    assert_eq!(word(json!({"ok": false, "error": "x"})), "unknown");
    assert_eq!(word(json!({"ok": true, "exists": false})), "missing");
    assert_eq!(word(json!({"ok": true, "exists": true})), "not-mounted");
    assert_eq!(word(json!({"ok": true, "exists": true, "marker": {"id": "other"}})), "foreign");
    assert_eq!(word(json!({"ok": true, "exists": true, "marker": {"id": "lib"}, "free": 1})), "read-only");
    assert_eq!(word(json!({"ok": true, "exists": true, "marker": {"id": "lib"}, "writable": true, "free": 1})), "low-space");
    assert_eq!(word(json!({"ok": true, "exists": true, "marker": {"id": "lib"}, "writable": true, "free": 1u64 << 40})), "ok");
}

#[test]
fn a_mount_table_says_who_stands_at_a_path() {
    let table = "36 35 98:0 /a /mnt/x rw - nfs4 nas:/a rw\n36 35 98:0 /b /mnt/x rw - cifs //nas2/b rw\n1 2 3:4 / /mnt/my\\040share rw - ext4 /dev/sda1 rw";
    assert_eq!(MountFacts::mounted("/mnt/x/", table), Some(("//nas2/b".to_string(), "cifs".to_string())));
    assert_eq!(MountFacts::mounted("/mnt/my share", table), Some(("/dev/sda1".to_string(), "ext4".to_string())));
    assert_eq!(MountFacts::mounted("/none", table), None);
    assert!(MountFacts::in_fstab("/mnt/x", "nas:/a /mnt/x nfs defaults 0 0\n# nas:/b /mnt/y nfs"));
    assert!(!MountFacts::in_fstab("/mnt/y", "nas:/a /mnt/x nfs defaults 0 0\n# nas:/b /mnt/y nfs"));
    assert_eq!(MountFacts::host("nas:/a"), "nas");
    assert_eq!(MountFacts::host("//nas2/b"), "nas2");
    assert_eq!(MountFacts::host("/dev/sda1"), "");
}

#[test]
fn a_path_is_normal() {
    assert_eq!(PathWord::normal("/a//b/./c/../d/"), "/a/b/d");
    assert_eq!(PathWord::normal("/"), "/");
}
