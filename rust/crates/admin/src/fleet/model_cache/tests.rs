//! A machine's model cache as the controller asks its scout, by value: what goes to the scout, what is refused first, what is kept of its answer.

#![allow(
    clippy::unwrap_used,
    clippy::panic,
    clippy::indexing_slicing,
    reason = "a helper of a test may stop where it found something wrong"
)]

use super::*;

#[test]
fn a_cache_with_no_keep_is_no_cache() {
    assert_eq!(ModelCacheFacts::clean(Some(&json!({"keep": 0}))), None);
    assert_eq!(ModelCacheFacts::clean(Some(&json!({}))), None);
    assert_eq!(ModelCacheFacts::clean(None), None);
}

#[test]
fn a_cache_keeps_what_it_says_in_its_shape() {
    let cleaned = ModelCacheFacts::clean(Some(&json!({
        "keep": 3, "managedBytes": 5, "budgetBytes": 0, "dir": " /a ",
        "foreign": {"files": 1, "bytes": 2, "folders": [{"folder": "x", "files": 1, "bytes": 2}, {"folder": "", "files": 1, "bytes": 2}]},
        "disk": {"totalBytes": 10, "freeBytes": 0},
    })))
    .unwrap();
    assert_eq!(cleaned["budgetBytes"], Value::Null);
    assert_eq!(cleaned["dir"], "/a");
    assert_eq!(cleaned["foreign"]["folders"], json!([{"folder": "x", "files": 1, "bytes": 2}]));
    assert_eq!(cleaned["disk"], json!({"totalBytes": 10, "freeBytes": 0}));
}

/// A machine's scout that answers by path and remembers, whole, what it was asked: (method, path, body).
struct StandInScout {
    address: String,
    asked: std::sync::Arc<std::sync::Mutex<Vec<(String, String, String)>>>,
}

impl StandInScout {
    fn answering(table: Vec<(&'static str, String)>) -> Self {
        use std::io::{BufRead, Read, Write};
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let address = format!("http://{}", listener.local_addr().unwrap());
        let asked = std::sync::Arc::new(std::sync::Mutex::new(Vec::new()));
        let kept = std::sync::Arc::clone(&asked);
        std::thread::spawn(move || {
            for stream in listener.incoming().flatten() {
                let mut reader = std::io::BufReader::new(stream.try_clone().unwrap());
                let (mut first, mut length) = (String::new(), 0_usize);
                reader.read_line(&mut first).unwrap();
                loop {
                    let mut line = String::new();
                    reader.read_line(&mut line).unwrap();
                    if line == "\r\n" || line.is_empty() {
                        break;
                    }
                    if let Some(said) = line.to_ascii_lowercase().strip_prefix("content-length:") {
                        length = said.trim().parse().unwrap();
                    }
                }
                let mut body = vec![0_u8; length];
                reader.read_exact(&mut body).unwrap();
                let mut words = first.split_whitespace();
                let (method, path) = (words.next().unwrap().to_string(), words.next().unwrap().to_string());
                let answer = table
                    .iter()
                    .find(|row| row.0 == path)
                    .map_or_else(|| "HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n".to_string(), |row| row.1.clone());
                kept.lock().unwrap().push((method, path, String::from_utf8_lossy(&body).into_owned()));
                let mut stream = stream;
                stream.write_all(answer.as_bytes()).unwrap();
            }
        });
        Self { address, asked }
    }

    fn calls(&self) -> Vec<(String, String, Value)> {
        let read = |body: &str| serde_json::from_str(body).unwrap_or(Value::Null);
        self.asked.lock().unwrap().iter().map(|(method, path, body)| (method.clone(), path.clone(), read(body))).collect()
    }
}

fn ok_with(body: &Value) -> String {
    let text = body.to_string();
    format!("HTTP/1.1 200 OK\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{text}", text.len())
}

fn refused_with(status: &str, words: &str) -> String {
    let text = json!({"error": words}).to_string();
    format!("HTTP/1.1 {status}\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{text}", text.len())
}

const KEEP: &str = "/api/llama-node/cache/keep";
const DELETE: &str = "/api/llama-node/cache/delete-foreign";
const BUDGET: &str = "/api/llama-node/cache/budget";
const MOVE: &str = "/api/llama-node/cache/dir";
const CLEAR: &str = "/api/llama-node/purge-cache";
const FIGURES: &str = "/api/llama-node/cache";

fn figures(keep: i64) -> Value {
    json!({"ok": true, "keep": keep, "managedBytes": 7, "foreign": {"files": 0, "bytes": 0, "folders": []}, "disk": {"totalBytes": 10, "freeBytes": 5}})
}

/// A controller with the machine `box`, its scout answering by this table, and the record it left.
fn machine(name: &str, table: Vec<(&'static str, String)>) -> (crate::tests::TestFolder, std::sync::Arc<App>, StandInScout) {
    let scout = StandInScout::answering(table);
    let folder = crate::tests::TestFolder::new(&format!("cache-{name}"));
    let app = crate::tests::TestApp::over(&folder.path, &[]);
    let address = scout.address.clone();
    app.admin.saving(|doc| {
        doc.insert(
            "topology".to_string(),
            json!({"hosts": {"box": {"id": "box", "agentUrl": address, "modelCache": {"keep": 1, "managedBytes": 5, "foreign": null, "disk": null}}}}),
        );
    });
    (folder, app, scout)
}

fn record_of(app: &App) -> Value {
    app.admin.change(|doc| Topology::of(doc).hosts().get("box").and_then(|host| host.get("modelCache")).cloned()).unwrap()
}

#[test]
fn what_cannot_be_a_setting_is_refused_before_the_scout_is_asked() {
    let (_folder, app, scout) = machine("bad", Vec::new());
    let cache = ModelCache::of(&app);
    let bad =
        |said: Result<Value, AppError>, what: &str| assert_eq!(said.err().map(|refused| refused.status), Some(400), "{what}");
    for value in [json!("3"), json!(true), Value::Null, json!(2.5), json!([3]), json!({})] {
        bad(cache.keep("box", Some(&value)), &format!("keep {value}"));
    }
    for value in [json!("100"), json!(true), Value::Null, json!(1.5), json!([1])] {
        bad(cache.delete_foreign("box", Some(&value)), &format!("delete {value}"));
    }
    bad(cache.delete_foreign("box", None), "delete with no size");
    for value in [json!("50"), json!(2.5), json!(true), json!([]), json!({})] {
        bad(cache.budget("box", Some(&value)), &format!("budget {value}"));
    }
    for how in [json!("moov"), json!(1), json!(true)] {
        bad(cache.move_to("box", Some(&json!("/mnt/hdd")), Some(&how)), &format!("move how {how}"));
        bad(cache.work("box", Some(&json!("/mnt/hdd")), Some(&how)), &format!("work how {how}"));
    }
    for value in [json!("true"), json!(1), Value::Null] {
        bad(cache.off("box", Some(&value), None), &format!("off {value}"));
    }
    assert_eq!(scout.calls(), [], "the scout is not asked to delete without the size it was shown");
}

#[test]
fn a_machine_nobody_reported_is_refused_and_nothing_is_sent() {
    let (_folder, app, scout) = machine("ghost", Vec::new());
    let cache = ModelCache::of(&app);
    assert_eq!(cache.keep("ghost", Some(&json!(3))).err().map(|refused| refused.status), Some(404));
    assert_eq!(cache.delete_foreign("ghost", Some(&json!(3))).err().map(|refused| refused.status), Some(404));
    assert!(cache.keep("", Some(&json!(3))).is_err(), "no machine named is no machine");
    assert_eq!(scout.calls(), []);
}

#[test]
fn the_setting_goes_to_the_scout_and_the_figures_are_asked_after_it_and_stored() {
    let trimmed = json!({"ok": true, "keep": 3, "removed": 2, "freedBytes": 30, "waiting": false});
    let (_folder, app, scout) = machine("keep", vec![(KEEP, ok_with(&trimmed)), (FIGURES, ok_with(&figures(3)))]);
    let got = ModelCache::of(&app).keep(" box ", Some(&json!(3))).unwrap();
    assert_eq!(
        scout.calls(),
        [("POST".to_string(), KEEP.to_string(), json!({"keep": 3})), ("GET".to_string(), FIGURES.to_string(), Value::Null)]
    );
    let cleaned = ModelCacheFacts::clean(Some(&figures(3))).unwrap();
    assert_eq!(got, json!({"ok": true, "hostId": "box", "result": trimmed, "modelCache": cleaned}));
    assert_eq!(record_of(&app), cleaned, "a board read a moment later shows them");
}

#[test]
fn a_scout_that_did_not_do_it_is_not_said_to_have_done_it() {
    let (_folder, app, _scout) =
        machine("no", vec![(KEEP, ok_with(&json!({"ok": false, "error": "refused"}))), (FIGURES, ok_with(&figures(1)))]);
    assert_eq!(ModelCache::of(&app).keep("box", Some(&json!(2))).unwrap()["ok"], json!(false));
}

#[test]
fn figures_that_cannot_be_asked_or_read_leave_the_record_as_the_last_report_left_it() {
    for (name, answer) in
        [("quiet", refused_with("500 Oops", "box unreachable")), ("garbage", ok_with(&json!({"ok": true, "keep": 0})))]
    {
        let (_folder, app, _scout) = machine(name, vec![(KEEP, ok_with(&json!({"ok": true}))), (FIGURES, answer)]);
        let before = record_of(&app);
        let got = ModelCache::of(&app).keep("box", Some(&json!(3))).unwrap();
        assert_eq!((&got["ok"], &got["modelCache"]), (&json!(true), &Value::Null), "{name}: set, and no figures known");
        assert_eq!(record_of(&app), before, "{name}");
    }
}

#[test]
fn a_deletion_goes_with_the_size_the_operator_was_shown_and_nothing_else() {
    let (_folder, app, scout) = machine(
        "delete",
        vec![(DELETE, ok_with(&json!({"ok": true, "removed": 3, "freedBytes": 67}))), (FIGURES, ok_with(&figures(1)))],
    );
    let got = ModelCache::of(&app).delete_foreign("box", Some(&json!(67))).unwrap();
    assert_eq!(scout.calls()[0], ("POST".to_string(), DELETE.to_string(), json!({"expectBytes": 67})));
    assert_eq!(got["result"]["removed"], json!(3));
    let (_folder, app, scout) =
        machine("delete-zero", vec![(DELETE, ok_with(&json!({"ok": true, "removed": 0}))), (FIGURES, ok_with(&figures(1)))]);
    ModelCache::of(&app).delete_foreign("box", Some(&json!(0))).unwrap();
    assert_eq!(
        scout.calls()[0].2,
        json!({"expectBytes": 0}),
        "0 is a size: nothing was shown to lie there, and the scout decides"
    );
}

#[test]
fn a_deletion_the_scout_refuses_comes_back_in_its_words_and_nothing_is_asked_or_stored_after_it() {
    let words = "the cache changed since it was shown: nothing was deleted";
    let (_folder, app, scout) =
        machine("delete-refused", vec![(DELETE, refused_with("409 Conflict", words)), (FIGURES, ok_with(&figures(1)))]);
    let before = record_of(&app);
    let refused = ModelCache::of(&app).delete_foreign("box", Some(&json!(67))).err().unwrap();
    assert_eq!(refused.status, 502);
    assert_eq!(refused.message, format!("box: {words}"));
    assert_eq!(scout.calls().len(), 1);
    assert_eq!(record_of(&app), before);
}

#[test]
fn the_budget_goes_in_bytes_and_null_takes_it_off() {
    let (_folder, app, scout) = machine("budget", vec![(BUDGET, ok_with(&json!({"ok": true}))), (FIGURES, ok_with(&figures(1)))]);
    let cache = ModelCache::of(&app);
    cache.budget("box", Some(&json!(50_i64 << 30))).unwrap();
    cache.budget("box", Some(&Value::Null)).unwrap();
    cache.budget("box", None).unwrap();
    let sent: Vec<Value> = scout.calls().into_iter().filter(|call| call.1 == BUDGET).map(|call| call.2).collect();
    assert_eq!(sent, [json!({"budgetBytes": 50_i64 << 30}), json!({"budgetBytes": null}), json!({"budgetBytes": null})]);
}

#[test]
fn a_move_and_a_clearing_go_as_they_were_said() {
    let (_folder, app, scout) = machine(
        "move",
        vec![
            (MOVE, ok_with(&json!({"ok": true, "removed": 5}))),
            (CLEAR, ok_with(&json!({"ok": true}))),
            (FIGURES, ok_with(&figures(1))),
        ],
    );
    let cache = ModelCache::of(&app);
    cache.move_to(" box ", Some(&json!(" /mnt/hdd/models ")), None).unwrap();
    cache.clear("box").unwrap();
    let sent: Vec<(String, Value)> =
        scout.calls().into_iter().filter(|call| call.1 != FIGURES).map(|call| (call.1, call.2)).collect();
    assert_eq!(
        sent,
        [(MOVE.to_string(), json!({"path": "/mnt/hdd/models", "how": "delete"})), (CLEAR.to_string(), json!({}))],
        "a board from before the choice moves as every move did then"
    );
}

#[test]
fn a_cache_block_is_kept_only_for_what_can_be_read() {
    let base = json!({"keep": 1, "managedBytes": 5, "foreign": {"files": 1, "bytes": 2, "folders": []}, "disk": {"totalBytes": 10, "freeBytes": 1}});
    let with = |key: &str, value: Value| {
        let mut doc = base.clone();
        doc[key] = value;
        doc
    };
    let clean = |doc: &Value| ModelCacheFacts::clean(Some(doc));
    for value in [json!(0), json!(-1), json!(true), json!("3"), json!(2.5), Value::Null, json!([])] {
        assert_eq!(clean(&with("keep", value.clone())), None, "keep {value}: there is no cache that keeps no model");
    }
    assert_eq!(clean(&with("keep", json!(5))).unwrap()["keep"], json!(5), "the range is the scout's to refuse");
    for not_a_block in [Value::Null, json!([]), json!("keep 1"), json!(7), json!(true)] {
        assert_eq!(clean(&not_a_block), None, "{not_a_block}: never a block of zeros");
    }
    for value in [json!(-1), json!(true), json!("12"), json!(1.5), Value::Null] {
        assert_eq!(
            clean(&with("managedBytes", value.clone())).unwrap()["managedBytes"],
            Value::Null,
            "managed {value}: unknown, not a number"
        );
    }
    for value in [json!("5"), json!(true), json!(0), json!(-1), json!(2.5)] {
        assert_eq!(clean(&with("budgetBytes", value.clone())).unwrap()["budgetBytes"], Value::Null, "budget {value}");
    }
    assert_eq!(
        clean(&base).unwrap().get("budgetBytes"),
        None,
        "a scout that says none: this scout cannot, which is not none chosen"
    );
    for value in [json!("relative/models"), json!(""), Value::Null, json!(7), json!(["/x"])] {
        assert_eq!(clean(&with("dir", value.clone())).unwrap().get("dir"), None, "dir {value}");
    }
    for value in [
        json!({"totalBytes": 0, "freeBytes": 0}),
        json!({"totalBytes": 100}),
        json!({"freeBytes": 100}),
        json!({"totalBytes": "9", "freeBytes": 1}),
        json!({"totalBytes": 100, "freeBytes": -1}),
        json!({"totalBytes": true, "freeBytes": 1}),
        json!([100, 1]),
    ] {
        assert_eq!(clean(&with("disk", value.clone())).unwrap()["disk"], Value::Null, "disk {value}");
    }
    assert_eq!(
        clean(&with("disk", json!({"totalBytes": 100, "freeBytes": 0}))).unwrap()["disk"]["freeBytes"],
        json!(0),
        "a full disk is a fact"
    );
    for key in ["files", "bytes"] {
        for value in [json!(-1), json!(true), json!("3"), Value::Null] {
            let mut foreign = base["foreign"].clone();
            foreign[key] = value.clone();
            assert_eq!(
                clean(&with("foreign", foreign)).unwrap()["foreign"],
                Value::Null,
                "foreign {key} {value}: not a clean folder"
            );
        }
    }
    assert_eq!(clean(&with("foreign", json!("none"))).unwrap()["foreign"], Value::Null);
    let rows: Vec<Value> = (0..12).map(|at| json!({"folder": format!("f{at}"), "files": 1, "bytes": 10 + at})).collect();
    let kept = clean(&with("foreign", json!({"files": 12, "bytes": 999, "folders": rows.clone()}))).unwrap();
    assert_eq!(kept["foreign"]["folders"], json!(rows[..8]), "the first 8, in the scout's order");
    let messy = json!([{"folder": "ok", "files": 1, "bytes": 5}, {"folder": "", "files": 1, "bytes": 5}, {"files": 1, "bytes": 5}, {"folder": "no-size", "files": 1}, {"folder": "negative", "files": 1, "bytes": -5}, "text", null, 7, {"folder": "x".repeat(300), "files": 2, "bytes": 8}]);
    let got = clean(&with("foreign", json!({"files": 4, "bytes": 13, "folders": messy}))).unwrap();
    assert_eq!(
        got["foreign"]["folders"],
        json!([{"folder": "ok", "files": 1, "bytes": 5}, {"folder": "x".repeat(200), "files": 2, "bytes": 8}])
    );
    assert_eq!(
        clean(&with("foreign", json!({"files": 0, "bytes": 0, "folders": "none"}))).unwrap()["foreign"]["folders"],
        json!([])
    );
}

#[test]
fn the_way_a_machine_reads_with_its_cache_off_reaches_the_board_only_as_it_is_said() {
    let base = json!({"keep": 1, "managedBytes": 5, "foreign": {"files": 1, "bytes": 2, "folders": []}, "disk": {"totalBytes": 9, "freeBytes": 3}});
    let with = |key: &str, value: Value| {
        let mut raw = base.clone();
        raw[key] = value;
        ModelCacheFacts::clean(Some(&raw)).unwrap()
    };
    assert_eq!(with("through", json!(true))["through"], true);
    assert_eq!(with("canThrough", json!(false))["canThrough"], false);
    assert!(with("through", json!("yes")).get("through").is_none(), "what is no yes or no says nothing");
    assert!(
        ModelCacheFacts::clean(Some(&base)).unwrap().get("canThrough").is_none(),
        "an older scout says nothing of it: the board offers it no way it may refuse"
    );
}

#[test]
fn the_cells_work_folder_is_kept_only_as_a_scout_says_it_whole() {
    let said = |work: Value| ModelCacheFacts::clean(Some(&json!({"keep": 1, "work": work}))).unwrap().get("work").cloned();
    assert_eq!(
        said(json!({"dir": " /mnt/hdd/strata ", "chosen": true, "bytes": 7})),
        Some(json!({"dir": "/mnt/hdd/strata", "chosen": true, "bytes": 7}))
    );
    assert_eq!(
        said(json!({"dir": "/c", "chosen": false})),
        Some(json!({"dir": "/c", "chosen": false, "bytes": null})),
        "bytes not measured are not 0"
    );
    assert_eq!(said(json!({"dir": "relative", "chosen": true})), None, "no folder of a machine");
    assert_eq!(said(json!({"dir": "/c"})), None, "chosen or not, unsaid, is no fact");
    assert_eq!(said(json!(null)), None);
}

#[test]
fn strata_s_shelf_reaches_the_board_with_its_limit_its_copies_and_its_disk_and_nothing_made_up() {
    let said = |work: Value| ModelCacheFacts::clean(Some(&json!({"keep": 1, "work": work}))).unwrap()["work"].clone();
    let full = said(json!({
        "dir": "/ssd/strata", "chosen": true, "bytes": 90, "modelsBytes": 70, "madeBytes": 20, "budgetBytes": 300, "budgetChosen": false,
        "disk": {"totalBytes": 1000, "freeBytes": 400}, "rotational": false,
        "models": [{"name": "q/q-00001-of-00002.gguf", "bytes": 60}, {"name": "", "bytes": 1}, {"name": "mtp.gguf", "bytes": -1}, {"name": "mtp-q2_0.gguf", "bytes": 10}],
    }));
    assert_eq!(
        full,
        json!({"dir": "/ssd/strata", "chosen": true, "bytes": 90, "modelsBytes": 70, "madeBytes": 20, "budgetBytes": 300, "budgetChosen": false,
               "disk": {"totalBytes": 1000, "freeBytes": 400}, "rotational": false,
               "models": [{"name": "q/q-00001-of-00002.gguf", "bytes": 60}, {"name": "mtp-q2_0.gguf", "bytes": 10}]}),
        "a row of no name or no size is no copy"
    );
    let quiet = said(json!({"dir": "/c/.strata", "chosen": false, "budgetBytes": 300, "budgetChosen": false}));
    assert_eq!(
        quiet,
        json!({"dir": "/c/.strata", "chosen": false, "bytes": null, "budgetBytes": 300, "budgetChosen": false}),
        "not measured: not said"
    );
    let odd = said(json!({"dir": "/s", "chosen": true, "rotational": "yes", "disk": {"freeBytes": 1}, "budgetBytes": -5}));
    assert_eq!(
        odd,
        json!({"dir": "/s", "chosen": true, "bytes": null, "disk": null}),
        "what is no fact is left out, a disk half said is null"
    );
}

#[test]
fn a_cell_that_writes_its_files_at_a_start_waits_for_a_folder_and_says_where_to_choose_it() {
    let host = |work: Value| json!({"name": "gpu-box", "modelCache": {"keep": 1, "work": work}});
    assert!(ModelCache::refuse_without_work(&host(json!({"dir": "/mnt/hdd", "chosen": true})), "strata").is_ok());
    let refused = ModelCache::refuse_without_work(&host(json!({"dir": "/home/u/cache", "chosen": false})), "strata").unwrap_err();
    assert_eq!(refused.status, 409);
    assert!(
        refused.message.contains("no folder is chosen for them on gpu-box")
            && refused.message.contains("Model disk → Strata files → Choose…"),
        "{}",
        refused.message
    );
    let older = ModelCache::refuse_without_work(&json!({"name": "gpu-box", "modelCache": {"keep": 1}}), "strata").unwrap_err();
    assert!(older.message.contains("update the scout"), "a scout that does not say is no folder: {}", older.message);
    let unknown = ModelCache::refuse_without_work(&json!({}), "strata").unwrap_err();
    assert!(unknown.message.contains("this machine"), "{}", unknown.message);
}

#[test]
fn a_move_under_way_and_one_that_failed_reach_the_board_as_the_scout_says_them() {
    let said = |extra: Value| {
        let mut raw = json!({"keep": 1});
        raw.as_object_mut().unwrap().extend(extra.as_object().unwrap().clone());
        ModelCacheFacts::clean(Some(&raw)).unwrap()
    };
    let moving = said(json!({"moving": {"what": "cache", "to": "/mnt/hdd", "doneBytes": 5, "totalBytes": 9}}));
    assert_eq!(moving["moving"], json!({"what": "cache", "to": "/mnt/hdd", "doneBytes": 5, "totalBytes": 9}));
    for bad in [
        json!({"what": "else", "to": "/a", "doneBytes": 1, "totalBytes": 2}),
        json!({"what": "work", "to": "a", "doneBytes": 1, "totalBytes": 2}),
        json!({"what": "work", "to": "/a", "totalBytes": 2}),
    ] {
        assert_eq!(said(json!({"moving": bad})).get("moving"), None, "{bad}");
    }
    assert_eq!(said(json!({"moveError": " x: no space "}))["moveError"], "x: no space");
    assert_eq!(said(json!({"moveError": ""})).get("moveError"), None);
}
