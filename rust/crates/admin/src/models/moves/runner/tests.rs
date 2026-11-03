//! The queue of moves: what is written down when, what a restart makes of it, and when a cell is started.

#![allow(
    clippy::unwrap_used,
    clippy::panic,
    clippy::indexing_slicing,
    reason = "a helper of a test may stop where it found something wrong"
)]

use super::*;
use crate::models::moves::job::{MoveFile, MoveItem};
use crate::models::moves::tests::{LIBRARY, Rig, blob};
use crate::models::stores::StoreRegistry;
use crate::tests::StandIn;
use std::fs;
use std::time::Duration;

/// A job as a manifest on the disk, of one file that is not there.
fn saved_job(rig: &Rig, id: &str, created: i64, status: &str) {
    let mut job = Rig::blank(
        json!({"id": "local", "name": "", "root": "/m", "kind": "local"}),
        json!({"id": LIBRARY, "name": "NAS", "root": "/l", "kind": "library"}),
        vec![MoveItem::new("a", vec![MoveFile::new("a.gguf", 10, vec![10, 1])], "", 0)],
    );
    job.id = id.to_string();
    job.created_at = created;
    job.status = status.to_string();
    fs::create_dir_all(&rig.app.paths.store_moves_dir).unwrap();
    fs::write(manifest_of(rig, id), job.to_json().to_string()).unwrap();
}

fn manifest_of(rig: &Rig, id: &str) -> PathBuf {
    rig.app.paths.store_moves_dir.join(format!("{id}.json"))
}

fn on_disk(rig: &Rig, id: &str) -> Value {
    serde_json::from_slice(&fs::read(manifest_of(rig, id)).unwrap()).unwrap()
}

/// The runner with its worker's place taken: jobs stay where the test left them.
fn parked(rig: &Rig) -> MoveRunner<'_> {
    *rig.app.moves.worker.lock().unwrap() = true;
    MoveRunner::of(&rig.app)
}

fn statuses(runner: &MoveRunner<'_>) -> BTreeMap<String, String> {
    runner.summaries().iter().map(|row| (Coerce::text(row.get("id")), Coerce::text(row.get("status")))).collect()
}

fn rows(pairs: &[(&str, &str)]) -> BTreeMap<String, String> {
    pairs.iter().map(|(id, status)| ((*id).to_string(), (*status).to_string())).collect()
}

/// The rig with its library on the controller's list.
fn listed(name: &str) -> Rig {
    let rig = Rig::new(name);
    assert!(StoreRegistry::of(&rig.app).add(&rig.lib.to_string_lossy(), "", false).is_ok());
    rig
}

/// Waits for this job to end; a test that goes red ends.
fn ended(runner: &MoveRunner<'_>, id: &str) -> Value {
    for _ in 0..1500 {
        let row = runner.summaries().into_iter().find(|row| Coerce::text(row.get("id")) == id);
        if let Some(row) =
            row.filter(|row| matches!(row.get("status").and_then(Value::as_str), Some("done" | "failed" | "cancelled")))
        {
            return row;
        }
        std::thread::sleep(Duration::from_millis(10));
    }
    panic!("{id} did not end: {:?}", runner.summaries());
}

/// Waits for this job's first file to be proven: a clock that stands still holds it there.
fn proven(runner: &MoveRunner<'_>, id: &str) {
    for _ in 0..1500 {
        let summaries = runner.summaries();
        let row = summaries.iter().find(|row| Coerce::text(row.get("id")) == id).unwrap();
        if row["files"][0]["phase"] == "proven" {
            return;
        }
        std::thread::sleep(Duration::from_millis(5));
    }
    panic!("{id} was not proven: {:?}", runner.summaries());
}

#[test]
fn a_restart_puts_what_was_interrupted_back_in_line_and_skips_a_record_that_does_not_read() {
    let rig = Rig::new("runner-restart");
    saved_job(&rig, "mv-old", 5, "done");
    saved_job(&rig, "mv-run", 6, "running");
    saved_job(&rig, "mv-wait", 7, "waiting");
    fs::write(manifest_of(&rig, "mv-bad"), "not json").unwrap();
    let runner = parked(&rig);
    assert_eq!(runner.resume(), 2);
    assert_eq!(statuses(&runner), rows(&[("mv-old", "done"), ("mv-run", "queued"), ("mv-wait", "queued")]));
    assert!(manifest_of(&rig, "mv-bad").exists(), "what does not read is not deleted: it may say something to a person");
    assert_eq!(runner.resume(), 0, "what is in memory already is not taken twice");
}

#[test]
fn a_restart_with_nothing_to_do_starts_no_worker_and_says_so() {
    let rig = Rig::new("runner-nothing");
    assert_eq!(MoveRunner::of(&rig.app).resume(), 0);
    saved_job(&rig, "mv-old", 5, "done");
    assert_eq!(MoveRunner::of(&rig.app).resume(), 0);
    assert!(!*rig.app.moves.worker.lock().unwrap());
}

#[test]
fn a_stop_of_a_job_in_line_ends_it_at_once_and_is_on_the_disk() {
    let rig = Rig::new("runner-stop-line");
    saved_job(&rig, "mv-next", 2, "queued");
    let runner = parked(&rig);
    runner.resume();
    let row = runner.cancel("mv-next").map_err(|refused| refused.code).unwrap();
    assert_eq!((&row["status"], &row["files"][0]["item"]), (&json!("cancelled"), &json!("cancelled")));
    assert!(row["finishedAt"].as_i64().unwrap() > 0);
    let disk = on_disk(&rig, "mv-next");
    assert_eq!((&disk["cancel"], &disk["status"]), (&json!(true), &json!("cancelled")));
    let restarted = crate::tests::TestApp::over(&rig.folder.path, &[]);
    let again = MoveRunner::of(&restarted);
    assert_eq!(again.resume(), 0, "a restart does not forget it, and does not put it back in line");
    assert_eq!(statuses(&again), rows(&[("mv-next", "cancelled")]));
}

#[test]
fn a_job_the_worker_holds_is_only_told_to_stop_and_it_stops_itself_between_blocks() {
    let rig = Rig::new("runner-stop-held");
    saved_job(&rig, "mv-held", 1, "queued");
    saved_job(&rig, "mv-next", 2, "queued");
    let runner = parked(&rig);
    runner.resume();
    rig.app.moves.current.lock().unwrap().push_str("mv-held");
    runner.cancel("mv-held").map_err(|refused| refused.code).unwrap();
    runner.cancel("mv-next").map_err(|refused| refused.code).unwrap();
    assert_eq!(statuses(&runner), rows(&[("mv-held", "queued"), ("mv-next", "cancelled")]));
    assert_eq!(on_disk(&rig, "mv-held")["cancel"], json!(true), "the flag is on the disk at once");
}

#[test]
fn a_finished_job_is_not_touched_by_a_stop_and_an_unknown_one_is_refused() {
    let rig = Rig::new("runner-stop-done");
    saved_job(&rig, "mv-old", 1, "done");
    let runner = parked(&rig);
    runner.resume();
    let row = runner.cancel("mv-old").map_err(|refused| refused.code).unwrap();
    assert_eq!(row["status"], json!("done"));
    assert_eq!(on_disk(&rig, "mv-old")["cancel"], json!(false));
    let refused = runner.cancel("mv-none").err().unwrap();
    assert_eq!((refused.code.as_str(), refused.error.status), ("unknown-job", 404));
}

#[test]
fn twenty_finished_jobs_are_remembered_the_oldest_go_from_memory_and_disk_and_an_open_one_stays() {
    let rig = Rig::new("runner-prune");
    saved_job(&rig, "mv-open", 0, "queued");
    for at in 0..22 {
        saved_job(&rig, &format!("mv-{at:02}"), i64::from(at) + 1, "done");
    }
    let runner = parked(&rig);
    runner.resume();
    let kept = statuses(&runner);
    assert_eq!(kept.len(), 21);
    assert!(kept.contains_key("mv-open"), "not finished: not pruned");
    for gone in ["mv-00", "mv-01"] {
        assert!(!kept.contains_key(gone), "{gone}");
        assert!(!manifest_of(&rig, gone).exists(), "{gone}");
    }
    assert!(kept.contains_key("mv-02") && manifest_of(&rig, "mv-02").exists());
    let order: Vec<String> = runner.summaries().iter().map(|row| Coerce::text(row.get("id"))).collect();
    assert_eq!(order[0], "mv-21", "newest first");
    assert_eq!(order[20], "mv-open");
}

#[test]
fn a_move_that_cannot_be_written_down_is_not_accepted() {
    let rig = listed("runner-unwritten");
    rig.put_local("A/a.gguf", &blob(10, 1));
    // A file where its folder should be: refused to any user.
    fs::write(&rig.app.paths.store_moves_dir, b"in the way").unwrap();
    let refused = MoveRunner::of(&rig.app).start(&[json!("A/a.gguf")], LIBRARY, None, None).err().unwrap();
    assert_eq!((refused.code.as_str(), refused.error.status), ("not-written", 500));
    assert_eq!(MoveRunner::of(&rig.app).summaries(), Vec::<Value>::new(), "nothing is in line");
    assert!(!*rig.app.moves.worker.lock().unwrap(), "and nothing was started");
    assert_eq!(rig.local_files(), ["A/a.gguf"]);
    assert!(rig.library_files().is_empty());
}

#[test]
fn a_move_is_on_the_disk_when_it_is_accepted_and_a_file_moving_is_refused_to_a_second_one() {
    let rig = listed("runner-busy");
    rig.clock.each_look_takes(0);
    rig.put_local("A/a.gguf", &blob(10, 1));
    rig.put_local("B/b.gguf", &blob(20, 2));
    let runner = MoveRunner::of(&rig.app);
    let first = runner.start(&[json!("A/a.gguf")], LIBRARY, None, None).map_err(|refused| refused.code).unwrap();
    let id = Coerce::text(first.get("id"));
    assert_eq!(first["status"], json!("queued"));
    assert_eq!(on_disk(&rig, &id)["id"], json!(id));
    // A clock that stands still holds the job in its settle: it is running, and it does not end.
    proven(&runner, &id);
    let refused = runner.start(&[json!("A/a.gguf")], LIBRARY, None, None).err().unwrap();
    assert_eq!(refused.code, "busy");
    let second = runner.start(&[json!("B/b.gguf")], LIBRARY, None, None).map_err(|refused| refused.code).unwrap();
    let next = Coerce::text(second.get("id"));
    assert_eq!(
        runner.cancel(&next).map_err(|refused| refused.code).unwrap()["status"],
        json!("cancelled"),
        "in line: it ends at once"
    );
    assert_eq!(runner.cancel(&id).map_err(|refused| refused.code).unwrap()["status"], json!("running"), "held: it ends itself");
    assert_eq!(ended(&runner, &id)["status"], json!("cancelled"));
    assert_eq!(rig.local_files(), ["A/a.gguf", "B/b.gguf"], "a stopped move takes nothing away");
}

#[test]
fn a_move_runs_to_its_end_behind_the_answer() {
    let rig = listed("runner-whole");
    let data = blob(5000, 1);
    rig.put_local("A/a.gguf", &data);
    let runner = MoveRunner::of(&rig.app);
    let started = runner.start(&[json!("A/a.gguf")], LIBRARY, None, None).map_err(|refused| refused.code).unwrap();
    let id = Coerce::text(started.get("id"));
    assert_eq!(ended(&runner, &id)["status"], json!("done"));
    assert_eq!(fs::read(rig.lib.join("A/a.gguf")).unwrap(), data);
    assert!(rig.local_files().is_empty());
    assert_eq!(on_disk(&rig, &id)["status"], json!("done"), "the manifest says how it ended");
    // Over, it holds nothing: the file may go back.
    let home = runner.start(&[json!("A/a.gguf")], "local", Some(LIBRARY), None).map_err(|refused| refused.code).unwrap();
    assert_eq!(ended(&runner, &Coerce::text(home.get("id")))["status"], json!("done"));
    assert_eq!(fs::read(rig.local.join("A/a.gguf")).unwrap(), data);
}

#[test]
fn a_restart_finishes_what_it_finds_and_never_forgets_the_stop() {
    let rig = Rig::new("runner-finishes");
    let data = blob(5000, 1);
    rig.put_local("A/a.gguf", &data);
    let mut job = rig.job(&[&["A/a.gguf"]]);
    job.status = "running".to_string();
    job.id = "mv-found".to_string();
    fs::create_dir_all(&rig.app.paths.store_moves_dir).unwrap();
    fs::write(manifest_of(&rig, "mv-found"), job.to_json().to_string()).unwrap();
    let runner = MoveRunner::of(&rig.app);
    assert_eq!(runner.resume(), 1);
    assert_eq!(ended(&runner, "mv-found")["status"], json!("done"));
    assert_eq!(fs::read(rig.lib.join("A/a.gguf")).unwrap(), data);

    let rig = Rig::new("runner-finishes-stop");
    rig.put_local("A/a.gguf", &data);
    let mut job = rig.job(&[&["A/a.gguf"]]);
    job.cancel = true;
    job.id = "mv-stopped".to_string();
    fs::create_dir_all(&rig.app.paths.store_moves_dir).unwrap();
    fs::write(manifest_of(&rig, "mv-stopped"), job.to_json().to_string()).unwrap();
    let runner = MoveRunner::of(&rig.app);
    assert_eq!(runner.resume(), 1);
    assert_eq!(ended(&runner, "mv-stopped")["status"], json!("cancelled"));
    assert_eq!(rig.local_files(), ["A/a.gguf"], "the stop came before the restart, and it holds after it");
    assert!(rig.library_files().is_empty());
}

/// A job for the promise, in the state it ended in; what `keep_promise` made of it.
fn after_promise(rig: &Rig, status: &str, items: &[&str], then: Value) -> String {
    let mut job = rig.job(&[]);
    job.status = status.to_string();
    job.then = then;
    job.items = items
        .iter()
        .map(|state| {
            let mut item = MoveItem::new("a", Vec::new(), "", 0);
            item.state = (*state).to_string();
            item
        })
        .collect();
    let shared = Arc::new(Mutex::new(job));
    MoveRunner::of(&rig.app).keep_promise(&shared);
    let job = shared.lock().unwrap();
    job.reason.clone()
}

#[test]
fn a_cell_is_started_only_when_every_item_came_home() {
    let rig = Rig::new("runner-promise");
    let then = json!({"start": {"hostId": "box", "port": 22001}});
    let tried = "the cell did not start: cell has no saved model — configure it first";
    assert_eq!(after_promise(&rig, "done", &["done", "done"], then.clone()), tried, "it was asked to start");
    for (status, items) in
        [("done", &["done", "skipped"][..]), ("done", &["skipped"][..]), ("failed", &["done"][..]), ("cancelled", &["done"][..])]
    {
        assert_eq!(
            after_promise(&rig, status, items, then.clone()),
            "",
            "{status} {items:?}: a cell would read a file that is not there"
        );
    }
    assert_eq!(after_promise(&rig, "done", &["done"], json!({})), "", "no promise, no start");
}

#[test]
fn a_promise_survives_on_the_disk_and_starts_the_cell_when_the_model_is_home() {
    let rig = listed("runner-promise-whole");
    let scout = StandIn::table(vec![(
        "/api/llama-node/start".to_string(),
        "200 OK".to_string(),
        String::new(),
        b"{\"ok\": true}".to_vec(),
    )]);
    rig.clock.each_look_takes(0);
    let now = rig.app.now_whole();
    let address = scout.address().to_string();
    rig.app.admin.saving(|doc| {
        doc.insert(
            "topology".to_string(),
            json!({
                "serverSlots": {"box:22001": {"hostId": "box", "port": 22001, "model": "other/o.gguf", "config": {"MODEL_FILE": "other/o.gguf"}}},
                "hosts": {"box": {"id": "box", "lastSeen": now, "agentUrl": address, "llamaNodes": []}},
            }),
        );
    });
    rig.put_library("K/k.gguf", &blob(10, 1));
    let runner = MoveRunner::of(&rig.app);
    let then = json!({"start": {"hostId": "box", "port": 22001}});
    let started =
        runner.start(&[json!("K/k.gguf")], "local", Some(LIBRARY), Some(&then)).map_err(|refused| refused.code).unwrap();
    let id = Coerce::text(started.get("id"));
    assert_eq!(on_disk(&rig, &id)["then"], then, "a restart in the middle does not lose it");
    let row = ended(&runner, &id);
    assert_eq!(row["status"], json!("done"));
    for _ in 0..500 {
        if !scout.targets().is_empty() {
            break;
        }
        std::thread::sleep(Duration::from_millis(5));
    }
    assert_eq!(scout.targets().first().map(String::as_str), Some("/api/llama-node/start"), "{:?}", runner.summaries());
    assert!(rig.local.join("K/k.gguf").exists(), "the model was home first");
}
