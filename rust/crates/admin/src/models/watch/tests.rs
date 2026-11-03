//! Was anything we have re-issued: what the watcher measures, over a hub that stands in, a clock in the test's hand and a folder of the test's own.

use super::super::downloads::Downloads;
use super::super::hub::tests::{RouteCall, Row, TestHub};
use super::*;
use crate::routes::pages::PageRoutes;
use crate::tests::{HandClock, StandIn, TestApp, TestFolder};
use std::path::PathBuf;
use std::sync::Arc;
use std::time::{Duration, SystemTime};

/// A moment of 2026-08-15, before the 19th and after 2020 in any time zone.
const DAY: u64 = 1_786_795_200;
/// The clock's moment: 2026-09-08, noon or so.
const NOW: u64 = 1_788_868_800;
const NEWER: &str = "2026-08-19T00:00:00Z";
const OLDER: &str = "2020-01-01T00:00:00Z";

struct Stand {
    _folder: TestFolder,
    hub: StandIn,
    clock: Arc<HandClock>,
    app: Arc<App>,
}

impl Stand {
    fn new(name: &str, rows: Vec<Row>) -> Self {
        let folder = TestFolder::new(&format!("watch-{name}"));
        let hub = StandIn::table(rows);
        let clock = HandClock::at(NOW);
        let app = TestApp::with_clock(&folder.path, &[("CARAVAN_HUB_URL", hub.address())], clock.clone());
        Self { _folder: folder, hub, clock, app }
    }

    fn watch(&self) -> ModelWatch<'_> {
        ModelWatch::of(&self.app)
    }

    fn path(&self, rel: &str) -> PathBuf {
        self.app.models_dir().join(rel)
    }

    /// A file of `size` bytes last written at `when`, as the walk finds it.
    fn put(&self, rel: &str, size: usize, when: u64) {
        let path = self.path(rel);
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        std::fs::write(&path, vec![b'x'; size]).unwrap();
        let moment = SystemTime::UNIX_EPOCH + Duration::from_secs(when);
        std::fs::File::options().write(true).open(&path).unwrap().set_modified(moment).unwrap();
    }

    /// A new pass reaches the hub again.
    fn forget_the_hub(&self) {
        self.app.hub_memory.clear();
    }

    fn turned_on(&self, body: &Value) {
        self.watch().set_settings(body);
    }

    fn saved_watch(&self, doc: &Value) {
        self.app.admin.saving(|state| state.insert("modelWatch".to_string(), doc.clone()));
    }

    fn saved_report(&self, doc: &Value) {
        self.app.admin.saving(|state| state.insert("modelFreshness".to_string(), doc.clone()));
    }

    fn running(&self) -> bool {
        *self.app.watch_memory.running.lock().unwrap()
    }

    fn set_running(&self, running: bool) {
        *self.app.watch_memory.running.lock().unwrap() = running;
    }

    /// Waits for the pass a board started.
    fn pass_ended(&self) {
        for _ in 0..5000 {
            if !self.running() {
                return;
            }
            std::thread::sleep(Duration::from_millis(2));
        }
        panic!("the pass did not end");
    }

    fn downloads_ended(&self) {
        for _ in 0..5000 {
            if Downloads::of(&self.app).all().values().all(|job| job["done"] == json!(true)) {
                return;
            }
            std::thread::sleep(Duration::from_millis(2));
        }
        panic!("a download did not end");
    }

    /// The day the clock says, as the watcher writes it.
    fn today(&self) -> String {
        LocalTime::of(self.app.now_whole()).unwrap().date()
    }
}

/// A file of a repository's tree of this size and commit date.
fn remote(name: &str, size: i64, date: &str) -> Value {
    let mut entry = TestHub::lfs(name, size, &"b".repeat(64));
    entry["lastCommit"]["date"] = json!(date);
    entry
}

fn four_files() -> Vec<Row> {
    vec![TestHub::tree(
        "a/b",
        vec![remote("same.gguf", 100, OLDER), remote("smaller.gguf", 90, NEWER), remote("newer.gguf", 100, NEWER)],
    )]
}

/// The repository `a/b` of four files of a hundred bytes, written on `DAY`.
fn four_files_stand(name: &str) -> Stand {
    let stand = Stand::new(name, four_files());
    for file in ["same.gguf", "smaller.gguf", "newer.gguf", "only-ours.gguf"] {
        stand.put(&format!("b/a/Q4/{file}"), 100, DAY);
    }
    stand
}

fn state<'report>(report: &'report Value, key: &str) -> &'report Value {
    &report["repos"]["a/b"]["files"][key]["state"]
}

#[test]
fn a_pass_with_the_check_off_reaches_no_network_and_a_pressed_button_does() {
    let stand = Stand::new("off", vec![TestHub::tree("u/Q", Vec::new())]);
    stand.put("Q/u/Q4/a.gguf", 1, DAY);
    assert_eq!(stand.watch().check_pass(false), json!({"checked": false, "reason": "auto-check off"}));
    assert_eq!(stand.hub.targets(), Vec::<String>::new(), "the checkbox is off, and nothing knocks outward");
    assert_eq!(stand.watch().report(), json!({"checkedAt": 0, "repos": {}}), "and nothing was measured");
    let pressed = stand.watch().check_pass(true);
    assert_eq!(pressed["checked"], json!(true));
    assert_eq!(stand.hub.targets().len(), 1, "a pressed button is a direct request");
    assert_eq!(stand.watch().report()["checkedAt"], json!(NOW), "the report keeps WHEN it was measured");
    assert_eq!(stand.watch().settings()["lastCheckAt"], json!(NOW));
}

#[test]
fn a_pass_with_the_check_on_goes_by_itself() {
    let stand = Stand::new("on", vec![TestHub::tree("u/Q", Vec::new())]);
    stand.put("Q/u/Q4/a.gguf", 1, DAY);
    stand.turned_on(&json!({"check": true}));
    assert_eq!(stand.watch().check_pass(false)["checked"], json!(true));
    assert_eq!(stand.hub.targets().len(), 1);
}

#[test]
fn each_tier_turns_on_the_one_before_it_and_none_after_it() {
    let stand = Stand::new("tiers", Vec::new());
    let watch = stand.watch();
    let tiers = |settings: &Value| (settings["check"].clone(), settings["download"].clone(), settings["keepPrev"].clone());
    let (yes, no) = (json!(true), json!(false));
    assert_eq!(tiers(&watch.settings()), (no.clone(), no.clone(), no.clone()), "nothing said: every tier is off");
    assert_eq!(
        tiers(&watch.set_settings(&json!({"download": true}))),
        (yes.clone(), yes.clone(), no.clone()),
        "downloading turns checking on: or nobody would be there to do it"
    );
    assert_eq!(
        tiers(&watch.set_settings(&json!({"check": true}))),
        (yes.clone(), no.clone(), no.clone()),
        "and a check downloads nothing by itself"
    );
    assert_eq!(
        tiers(&watch.set_settings(&json!({"check": true, "keepPrev": true}))),
        (yes, no.clone(), json!(true)),
        "keeping the previous build is about room, not about the automatic"
    );
    assert_eq!(tiers(&watch.set_settings(&json!({}))), (no.clone(), no.clone(), no), "a box not sent is a box cleared");
}

#[test]
fn the_old_hour_of_the_schedule_is_no_setting_and_saving_keeps_the_day() {
    let stand = Stand::new("old-hour", Vec::new());
    stand.saved_watch(&json!({"check": true, "at": "03:00", "replace": true, "lastCheckDay": "2026-09-08"}));
    assert!(stand.watch().settings().get("at").is_none());
    let saved = stand.watch().set_settings(&json!({"check": true, "at": "25:00"}));
    assert!(saved.get("at").is_none());
    let kept = stand.app.admin.read(|doc| doc.get("modelWatch").cloned()).unwrap();
    assert!(kept.get("at").is_none() && kept.get("replace").is_none(), "wiped from the state, and no refusal: {kept}");
    assert_eq!(saved["lastCheckDay"], json!("2026-09-08"), "saving neither marks a day nor wipes it");
}

#[test]
fn a_file_is_same_size_date_or_unknown_and_each_is_counted() {
    let stand = four_files_stand("states");
    stand.watch().check_pass(true);
    let report = stand.watch().report();
    assert_eq!(state(&report, "b/a/Q4/same.gguf"), &json!("same"));
    assert_eq!(state(&report, "b/a/Q4/smaller.gguf"), &json!("size"));
    assert_eq!(state(&report, "b/a/Q4/newer.gguf"), &json!("date"));
    assert_eq!(
        state(&report, "b/a/Q4/only-ours.gguf"),
        &json!("unknown"),
        "the repository no longer lists it: not matches, and not silence"
    );
    assert_eq!(
        report["repos"]["a/b"]["summary"],
        json!({"differs": 2, "bySize": 1, "byDate": 1, "unknown": 1, "same": 1, "missing": 0})
    );
}

#[test]
fn a_rows_key_is_the_path_and_it_says_both_sizes_and_where_the_new_build_goes() {
    let stand = four_files_stand("row");
    let pass = stand.watch().check_pass(true);
    assert_eq!((&pass["repos"], &pass["unreachable"], &pass["differs"]), (&json!(1), &json!(0), &json!(2)));
    let report = stand.watch().report();
    let row = &report["repos"]["a/b"]["files"]["b/a/Q4/smaller.gguf"];
    assert_eq!((&row["localSize"], &row["remoteSize"]), (&json!(100), &json!(90)), "no second trip to the hub for it");
    assert_eq!(
        (&row["localPath"], &row["remotePath"]),
        (&json!(stand.path("b/a/Q4/smaller.gguf").to_string_lossy()), &json!("smaller.gguf"))
    );
    assert_eq!((&row["repo"], &row["name"]), (&json!("a/b"), &json!("smaller.gguf")));
    assert_eq!(row["remoteDate"], json!("2026-08-19"), "by the calendar day");
    assert_eq!(stand.watch().freshness_by_path()["b/a/Q4/smaller.gguf"], "size", "and the list of models reads the same report");
}

#[test]
fn a_repository_the_hub_refuses_is_an_error_with_no_states_and_a_zero_that_claims_nothing() {
    let stand = Stand::new("refused", vec![TestHub::refused("/api/models/a/b/tree/main", "404 Not Found")]);
    stand.put("b/a/Q4/m.gguf", 100, DAY);
    let pass = stand.watch().check_pass(true);
    let report = stand.watch().report();
    let row = &report["repos"]["a/b"];
    assert_eq!(row["error"], json!("HTTP Error 404: Not Found"));
    assert_eq!(row["files"], json!({}), "no file gets a state: this is NOT matches");
    assert_eq!(row["summary"], json!({"differs": 0, "bySize": 0, "byDate": 0, "unknown": 0, "same": 0, "missing": 0}));
    assert_eq!((&pass["unreachable"], &pass["differs"]), (&json!(1), &json!(0)));
    assert_eq!(stand.watch().settings()["lastError"], json!("1 repo(s) unreachable"), "and it is said that not everything read");
}

#[test]
fn a_later_pass_that_reads_everything_clears_the_error() {
    let stand = Stand::new("error-clears", vec![TestHub::tree("a/b", vec![remote("m.gguf", 100, OLDER)])]);
    stand.put("b/a/Q4/m.gguf", 100, DAY);
    let mut saved = stand.watch().saved();
    saved.insert("lastError".to_string(), json!("1 repo(s) unreachable"));
    stand.watch().put_saved(saved);
    stand.watch().check_pass(true);
    assert_eq!(stand.watch().settings()["lastError"], json!(""));
}

#[test]
fn one_name_in_two_quants_is_two_rows_each_measured_on_its_own() {
    let stand = Stand::new("duplicates", vec![TestHub::tree("A/M", vec![remote("dup.gguf", 90, NEWER)])]);
    stand.put("M/A/Q5_K_M/dup.gguf", 100, 200);
    stand.put("M/A/default/dup.gguf", 100, 100);
    let local = stand.watch().local_repos();
    let copies = &local["A/M"];
    assert_eq!(copies.keys().collect::<Vec<_>>(), ["M/A/Q5_K_M/dup.gguf", "M/A/default/dup.gguf"], "each under its own path");
    assert_eq!(
        (&copies["M/A/default/dup.gguf"]["mtime"], &copies["M/A/Q5_K_M/dup.gguf"]["mtime"]),
        (&json!(100), &json!(200)),
        "and its own time"
    );
    stand.watch().check_pass(true);
    let report = stand.watch().report();
    let row = &report["repos"]["A/M"];
    assert_eq!(
        row["files"].as_object().unwrap().keys().collect::<Vec<_>>(),
        ["M/A/Q5_K_M/dup.gguf", "M/A/default/dup.gguf"],
        "one on the hub, two here: both are checked"
    );
    assert_eq!(row["files"]["M/A/default/dup.gguf"]["name"], json!("dup.gguf"));
    assert_eq!(
        row["files"]["M/A/default/dup.gguf"]["localPath"],
        json!(stand.path("M/A/default/dup.gguf").to_string_lossy()),
        "a row leads to its own file"
    );
    assert_eq!(row["summary"]["differs"], json!(2));
}

#[test]
fn a_file_shallower_than_three_levels_belongs_to_no_repository() {
    let stand = Stand::new("layout", Vec::new());
    stand.put("Qwen3.8-27B-GGUF/unsloth/Q4_K_XL/m.gguf", 1, DAY);
    stand.put("loose.gguf", 1, DAY);
    stand.put("vendor/x.gguf", 1, DAY);
    stand.put("Qwen3.8-27B-GGUF/unsloth/Q4_K_XL/notes.txt", 1, DAY);
    let repos = stand.watch().local_repos();
    assert_eq!(
        repos.keys().collect::<Vec<_>>(),
        ["unsloth/Qwen3.8-27B-GGUF"],
        "<model>/<author>/<quant> is <author>/<model>, and no author is made up"
    );
    let one = &repos["unsloth/Qwen3.8-27B-GGUF"];
    assert_eq!(one.keys().collect::<Vec<_>>(), ["Qwen3.8-27B-GGUF/unsloth/Q4_K_XL/m.gguf"]);
    assert_eq!(one["Qwen3.8-27B-GGUF/unsloth/Q4_K_XL/m.gguf"]["name"], json!("m.gguf"), "the hub is asked by the name");
}

#[test]
fn a_file_replaced_reads_as_it_is_now_with_no_new_trip_and_the_time_of_the_check_stays() {
    let stand = four_files_stand("relive");
    stand.watch().check_pass(true);
    let before = stand.watch().report();
    assert_eq!(state(&before, "b/a/Q4/smaller.gguf"), &json!("size"));
    let asked = stand.hub.targets().len();
    stand.put("b/a/Q4/smaller.gguf", 90, NOW);
    stand.clock.pass(2);
    let after = stand.watch().report();
    assert_eq!(state(&after, "b/a/Q4/smaller.gguf"), &json!("same"), "the file is what the hub has now: the button goes at once");
    assert_eq!(after["repos"]["a/b"]["files"]["b/a/Q4/smaller.gguf"]["localSize"], json!(90));
    assert_eq!(stand.hub.targets().len(), asked, "no trip to the hub");
    assert_eq!(after["checkedAt"], before["checkedAt"], "the time of the check is about the trip");
    assert_eq!(state(&after, "b/a/Q4/newer.gguf"), &json!("date"), "and the file beside it keeps its verdict");
}

#[test]
fn a_file_gone_from_the_disk_leaves_the_report() {
    let stand = four_files_stand("gone");
    stand.watch().check_pass(true);
    std::fs::remove_file(stand.path("b/a/Q4/only-ours.gguf")).unwrap();
    stand.clock.pass(2);
    let report = stand.watch().report();
    assert!(report["repos"]["a/b"]["files"].get("b/a/Q4/only-ours.gguf").is_none());
    assert_eq!(state(&report, "b/a/Q4/same.gguf"), &json!("same"));
}

#[test]
fn a_report_is_kept_for_a_second_unless_it_was_written_again() {
    let stand = four_files_stand("kept");
    stand.watch().check_pass(true);
    stand.watch().report();
    std::fs::remove_file(stand.path("b/a/Q4/only-ours.gguf")).unwrap();
    assert_eq!(
        state(&stand.watch().report(), "b/a/Q4/only-ours.gguf"),
        &json!("unknown"),
        "within the second: fifty readers, one look at the disk"
    );
    stand.watch().check_pass(true);
    assert!(
        stand.watch().report()["repos"]["a/b"]["files"].get("b/a/Q4/only-ours.gguf").is_none(),
        "a new report is read anew, in the same second too"
    );
}

#[test]
fn no_report_reads_as_not_checked_and_an_old_keyed_report_too() {
    let stand = Stand::new("old-report", Vec::new());
    let unchecked = json!({"checkedAt": 0, "repos": {}});
    assert_eq!(stand.watch().report(), unchecked, "not checked: time zero");
    let old = json!({"checkedAt": 9, "repos": {"a/b": {"files": {"smaller.gguf": {"state": "size", "localPath": "/m/a/b/smaller.gguf"}}}}});
    stand.saved_report(&old);
    assert_eq!(
        stand.watch().report(),
        unchecked,
        "a report keyed by name measured the wrong file: its verdicts are not carried forward"
    );
    assert_eq!(stand.watch().freshness_by_path(), BTreeMap::new());
    stand.saved_report(&json!({"checkedAt": 9, "keys": "path", "repos": {"a/b": {"files": {}}}}));
    assert_eq!(stand.watch().report()["checkedAt"], json!(9), "one marked by the path reads as its own");
}

#[test]
fn with_the_download_tier_off_a_pass_fetches_nothing() {
    let stand = four_files_stand("no-fetch");
    stand.turned_on(&json!({"check": true}));
    let pass = stand.watch().check_pass(false);
    assert_eq!(pass["fetched"], json!([]));
    assert!(
        stand.hub.targets().iter().all(|target| !target.contains("/resolve/main/") || target.contains("config.json")),
        "{:?}",
        stand.hub.targets()
    );
    assert_eq!(Downloads::of(&stand.app).all().len(), 0);
}

#[test]
fn with_the_download_tier_on_a_pass_takes_up_what_diverged_by_its_path_and_leaves_the_rest() {
    let mut rows = four_files();
    // The hub's wall: a job that started ends at its first request, and this test leaves nothing running behind it.
    rows.push(TestHub::refused("/a/b/resolve/main/", "403 Forbidden"));
    let stand = Stand::new("fetch", rows);
    for file in ["same.gguf", "smaller.gguf", "newer.gguf", "only-ours.gguf"] {
        stand.put(&format!("b/a/Q4/{file}"), 100, DAY);
    }
    stand.turned_on(&json!({"download": true}));
    let pass = stand.watch().check_pass(false);
    stand.downloads_ended();
    let fetched = pass["fetched"].as_array().unwrap();
    let paths: Vec<&Value> = fetched.iter().map(|row| &row["path"]).collect();
    assert_eq!(paths, [&json!("b/a/Q4/newer.gguf"), &json!("b/a/Q4/smaller.gguf")], "exactly what diverged; the walk's order");
    assert!(
        fetched
            .iter()
            .all(|row| row["result"] == json!("fetching") || Coerce::text(row.get("result")).contains("not enough room")),
        "{fetched:?}"
    );
    assert_eq!(stand.watch().settings()["lastFetched"], pass["fetched"], "and the models page reads what it took up");
}

#[test]
fn a_file_that_cannot_be_fetched_keeps_its_reason_and_does_not_stop_the_rest() {
    let huge = 1_i64 << 60;
    let stand =
        Stand::new("no-room", vec![TestHub::tree("a/b", vec![remote("one.gguf", huge, NEWER), remote("two.gguf", huge, NEWER)])]);
    stand.put("b/a/Q4/one.gguf", 100, DAY);
    stand.put("b/a/Q4/two.gguf", 100, DAY);
    stand.turned_on(&json!({"download": true}));
    let pass = stand.watch().check_pass(false);
    let fetched = pass["fetched"].as_array().unwrap();
    assert_eq!(fetched.len(), 2, "no room for one is said, and the other is still tried: {fetched:?}");
    assert!(fetched.iter().all(|row| Coerce::text(row.get("result")).contains("not enough room")), "{fetched:?}");
}

#[test]
fn a_board_with_the_check_off_starts_nothing_and_reaches_nothing() {
    let stand = Stand::new("board-off", vec![TestHub::tree("a/b", Vec::new())]);
    stand.put("b/a/Q4/x.gguf", 1, DAY);
    stand.saved_watch(&json!({"check": false}));
    assert_eq!(stand.watch().board_opened(), json!({"started": false, "reason": "auto-check off"}));
    assert_eq!(stand.hub.targets(), Vec::<String>::new());
    assert_eq!(stand.watch().settings()["lastCheckDay"], json!(""), "and no day is marked");
}

#[test]
fn the_first_board_of_a_day_starts_the_days_pass_with_the_day_marked_before_it() {
    let stand = Stand::new("board-first", vec![TestHub::tree("a/b", Vec::new())]);
    stand.put("b/a/Q4/x.gguf", 1, DAY);
    stand.saved_watch(&json!({"check": true, "lastCheckDay": "2026-09-07"}));
    assert_eq!(stand.watch().board_opened(), json!({"started": true, "reason": ""}));
    assert_eq!(
        stand.watch().settings()["lastCheckDay"],
        json!(stand.today()),
        "marked already, whatever the pass has done by now"
    );
    stand.pass_ended();
    assert_eq!(stand.hub.targets().len(), 1, "the pass that started is the check: it went to the hub for the repository");
    assert_eq!(stand.watch().report()["checkedAt"], json!(NOW));
}

#[test]
fn a_second_board_of_the_day_starts_no_second_pass() {
    let stand = Stand::new("board-second", vec![TestHub::tree("a/b", Vec::new())]);
    stand.put("b/a/Q4/x.gguf", 1, DAY);
    stand.saved_watch(&json!({"check": true, "lastCheckDay": stand.today()}));
    assert_eq!(stand.watch().board_opened(), json!({"started": false, "reason": "already checked today"}));
    assert_eq!(stand.hub.targets(), Vec::<String>::new());
}

#[test]
fn a_pass_that_still_runs_keeps_the_next_days_board_from_starting_another_beside_it() {
    let stand = Stand::new("board-running", vec![TestHub::tree("a/b", Vec::new())]);
    stand.put("b/a/Q4/x.gguf", 1, DAY);
    stand.saved_watch(&json!({"check": true, "lastCheckDay": "2026-09-07"}));
    stand.set_running(true);
    assert_eq!(stand.watch().board_opened(), json!({"started": false, "reason": "a pass is running"}));
    assert_eq!(stand.watch().settings()["lastCheckDay"], json!("2026-09-07"), "no day is marked for a pass that did not start");
    stand.set_running(false);
    assert_eq!(
        stand.watch().board_opened()["started"],
        json!(true),
        "ended: the flag is down, and the next board starts its own"
    );
    stand.pass_ended();
}

#[test]
fn a_pass_that_ended_leaves_the_flag_down_for_the_next_day() {
    let stand = Stand::new("board-next-day", vec![TestHub::tree("a/b", Vec::new())]);
    stand.put("b/a/Q4/x.gguf", 1, DAY);
    stand.saved_watch(&json!({"check": true, "lastCheckDay": "2026-09-07"}));
    assert_eq!(stand.watch().board_opened()["started"], json!(true));
    stand.pass_ended();
    assert_eq!(stand.watch().board_opened(), json!({"started": false, "reason": "already checked today"}));
    stand.clock.pass(86_400);
    stand.forget_the_hub();
    assert_eq!(stand.watch().board_opened()["started"], json!(true), "the next day's first board");
    stand.pass_ended();
    assert_eq!(stand.hub.targets().len(), 2);
}

#[test]
fn a_board_says_why_in_this_order_off_then_today_then_running() {
    let stand = Stand::new("board-order", Vec::new());
    let today = stand.today();
    stand.set_running(true);
    stand.saved_watch(&json!({"check": false, "lastCheckDay": today}));
    assert_eq!(stand.watch().board_opened()["reason"], json!("auto-check off"));
    stand.saved_watch(&json!({"check": true, "lastCheckDay": today}));
    assert_eq!(stand.watch().board_opened()["reason"], json!("already checked today"));
    stand.saved_watch(&json!({"check": true, "lastCheckDay": "2026-09-07"}));
    assert_eq!(stand.watch().board_opened()["reason"], json!("a pass is running"));
}

#[test]
fn the_board_page_starts_the_days_pass_and_the_machines_page_does_not() {
    let stand = Stand::new("board-page", vec![TestHub::tree("a/b", Vec::new())]);
    stand.put("b/a/Q4/x.gguf", 1, DAY);
    stand.saved_watch(&json!({"check": true, "lastCheckDay": "2026-09-07"}));
    let page = stand.app.paths.static_dir.join("index.html");
    std::fs::create_dir_all(page.parent().unwrap()).unwrap();
    std::fs::write(&page, b"the page").unwrap();
    assert_eq!(RouteCall::page(&stand.app, &PageRoutes::ROUTES, "/machine"), (200, "the page".to_string()));
    assert_eq!(stand.watch().settings()["lastCheckDay"], json!("2026-09-07"), "a machine's page starts nothing");
    assert_eq!(
        RouteCall::page(&stand.app, &PageRoutes::ROUTES, "/board"),
        (200, "the page".to_string()),
        "and the page does not wait for the pass"
    );
    assert_eq!(stand.watch().settings()["lastCheckDay"], json!(stand.today()));
    stand.pass_ended();
    assert_eq!(stand.hub.targets().len(), 1);
}
