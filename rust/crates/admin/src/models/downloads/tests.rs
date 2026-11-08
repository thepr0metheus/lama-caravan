//! A whole download job against a hub of the test's: what it asks for, what it leaves, and what it never writes over. The hub is `CARAVAN_HUB_URL`, so a job
//! runs from `Downloads::start` with no network.

#![allow(
    clippy::unwrap_used,
    clippy::panic,
    clippy::indexing_slicing,
    reason = "a helper of a test may stop where it found something wrong"
)]

use super::*;
use crate::routes::AllRoutes;
use crate::tests::{HandClock, StandIn, TestApp, TestFolder};
use crate::web::Exchange;
use std::io::BufReader;
use std::net::{TcpListener, TcpStream};
use std::os::unix::fs::MetadataExt;
use std::path::PathBuf;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::mpsc::{Sender, channel};
use std::sync::{Arc, Mutex};

const REPO: &str = "acme/model";
const SIZE: usize = 3000;

/// The file the hub has.
fn the_file() -> Vec<u8> {
    bytes(SIZE, 3)
}

fn bytes(size: usize, seed: usize) -> Vec<u8> {
    (0..size).map(|at| ((at * 31 + seed * 7) % 251) as u8).collect()
}

fn range_of(head: &str) -> Option<usize> {
    head.lines().find_map(|line| line.strip_prefix("Range: bytes=")?.strip_suffix('-')?.parse().ok())
}

fn ranges(hub: &StandIn) -> Vec<Option<usize>> {
    hub.asked().iter().map(|head| range_of(head)).collect()
}

/// A hub that hands the file over from where it is asked: on the n-th request `gives[n]` bytes of it, the last one for all after, and closes. The length it says
/// is the whole rest: fewer bytes are a connection cut short.
fn hub_giving(body: Vec<u8>, gives: Vec<usize>) -> StandIn {
    let turn = AtomicUsize::new(0);
    StandIn::serving(move |head| {
        let give = gives[turn.fetch_add(1, Ordering::SeqCst).min(gives.len() - 1)];
        let start = range_of(head).unwrap_or(0);
        let rest = &body[start..];
        let status = if start > 0 { "206 Partial Content" } else { "200 OK" };
        let mut out = format!("HTTP/1.1 {status}\r\nContent-Length: {}\r\nConnection: close\r\n\r\n", rest.len()).into_bytes();
        out.extend_from_slice(&rest[..give.min(rest.len())]);
        out
    })
}

/// A hub that says the same to all.
fn hub_saying(answer: Vec<u8>) -> StandIn {
    StandIn::serving(move |_| answer.clone())
}

/// A hub held by the test: for the n-th request it sends the first piece of `answers[n]`, waits for the test's word, sends the second, and closes.
struct HeldHub {
    address: String,
    asked: Arc<Mutex<Vec<String>>>,
    word: Sender<()>,
}

impl HeldHub {
    fn new(answers: Vec<(Vec<u8>, Vec<u8>)>) -> Self {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = format!("http://{}", listener.local_addr().unwrap());
        let asked = Arc::new(Mutex::new(Vec::new()));
        let (word, heard) = channel::<()>();
        let kept = Arc::clone(&asked);
        std::thread::spawn(move || {
            for (mut stream, (first, second)) in listener.incoming().flatten().zip(answers) {
                let mut head = vec![0u8; 16 * 1024];
                let read = stream.read(&mut head).unwrap();
                kept.lock().unwrap().push(String::from_utf8_lossy(&head[..read]).into_owned());
                stream.write_all(&first).unwrap();
                stream.flush().unwrap();
                heard.recv().unwrap();
                // The client may be gone: a job that stopped reads no more.
                drop(stream.write_all(&second));
            }
        });
        Self { address, asked, word }
    }

    fn targets(&self) -> Vec<String> {
        self.asked.lock().unwrap().iter().map(|head| head.split_whitespace().nth(1).unwrap().to_string()).collect()
    }
}

/// A controller over a folder of its own, the hub at `address`.
fn controller(name: &str, address: &str) -> (TestFolder, Arc<App>) {
    let folder = TestFolder::new(&format!("downloads-{name}"));
    let app = TestApp::over(&folder.path, &[("CARAVAN_HUB_URL", address)]);
    (folder, app)
}

fn file() -> DownloadFile {
    DownloadFile { path: "m.gguf".to_string(), name: "m.gguf".to_string(), dest_dir: "m".to_string(), size: SIZE as i64 }
}

fn models(app: &App) -> String {
    app.models_dir().to_string_lossy().into_owned()
}

/// Waits for a job to end; a test that goes red ends.
fn finished(app: &App, id: &str) -> Value {
    for _ in 0..3000 {
        let job = Downloads::of(app).job(id).unwrap();
        if job["done"] == json!(true) {
            return job;
        }
        std::thread::sleep(Duration::from_millis(5));
    }
    panic!("{id} did not end: {:?}", Downloads::of(app).job(id));
}

/// The files, as a job, to its end.
fn download(app: &App, files: Vec<DownloadFile>) -> Value {
    let id = Downloads::of(app).start(REPO, files, &models(app), "");
    finished(app, &id)
}

/// A partial with its manifest, of the size the manifest says.
fn partial(app: &App, bytes: &[u8], said_size: usize) -> PathBuf {
    let folder = app.models_dir().join("m");
    std::fs::create_dir_all(&folder).unwrap();
    let part = folder.join("m.gguf.part");
    std::fs::write(&part, bytes).unwrap();
    let manifest = json!({"repo": REPO, "path": "m.gguf", "name": "m.gguf", "destDir": "m", "size": said_size});
    std::fs::write(folder.join("m.gguf.part.json"), manifest.to_string()).unwrap();
    part
}

fn wait_for(what: &str, ready: impl Fn() -> bool) {
    for _ in 0..3000 {
        if ready() {
            return;
        }
        std::thread::sleep(Duration::from_millis(2));
    }
    panic!("no {what}");
}

fn size_of(path: &Path) -> u64 {
    std::fs::metadata(path).map_or(0, |meta| meta.len())
}

/// One POST of a route, past the door: its answer's JSON.
fn posted(app: &App, path: &str, body: Value) -> Value {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let mut client = TcpStream::connect(listener.local_addr().unwrap()).unwrap();
    let (server, _) = listener.accept().unwrap();
    let mut source = BufReader::new(server.try_clone().unwrap());
    let head = wire::RequestHead { method: "POST".to_string(), target: path.to_string(), headers: wire::Headers::new() };
    let mut exchange = Exchange::new(head, &mut source, &server, "127.0.0.1".to_string(), 0, "test");
    let route = AllRoutes::table().unwrap().post(path).unwrap();
    route(app, &mut exchange, body).unwrap();
    drop(exchange);
    drop(source);
    drop(server);
    let mut raw = String::new();
    client.read_to_string(&mut raw).unwrap();
    serde_json::from_str(raw.split_once("\r\n\r\n").unwrap().1).unwrap()
}

#[test]
fn a_dropped_connection_is_retried_from_the_bytes_on_disk_and_counted_once() {
    let hub = hub_giving(the_file(), vec![1000, usize::MAX]);
    let (_folder, app) = controller("drop", hub.address());
    let job = download(&app, vec![file()]);
    assert_eq!(job["status"], json!("done"), "{job}");
    assert_eq!(ranges(&hub), [None, Some(1000)], "the retry asks for the bytes it does not have");
    assert_eq!(job["total_bytes_done"], json!(SIZE), "the second attempt does not add the first one's bytes again");
    assert_eq!(std::fs::read(app.models_dir().join("m/m.gguf")).unwrap(), the_file());
    assert!(!app.models_dir().join("m/m.gguf.part").exists(), "no partial is left");
    assert!(!app.models_dir().join("m/m.gguf.part.json").exists(), "and no manifest");
}

#[test]
fn each_retry_starts_later_than_the_last() {
    let hub = hub_giving(the_file(), vec![500, 500, usize::MAX]);
    let (_folder, app) = controller("drops", hub.address());
    let job = download(&app, vec![file()]);
    assert_eq!(job["status"], json!("done"), "{job}");
    assert_eq!(ranges(&hub), [None, Some(500), Some(1000)]);
}

#[test]
fn a_stream_cut_short_every_time_never_takes_the_model_s_name_and_keeps_its_resume_point() {
    let hub = hub_giving(the_file(), vec![100]);
    let (_folder, app) = controller("cut", hub.address());
    let dest = app.models_dir().join("m/m.gguf");
    std::fs::create_dir_all(dest.parent().unwrap()).unwrap();
    std::fs::write(&dest, b"THE WORKING BUILD").unwrap();
    let job = download(&app, vec![file()]);
    assert_eq!(job["status"], json!("error"), "{job}");
    assert_eq!(ranges(&hub), [None, Some(100), Some(200), Some(300)], "four attempts, each of which moved something");
    assert_eq!(std::fs::read(&dest).unwrap(), b"THE WORKING BUILD", "the working file stands until a whole one lands");
    assert_eq!(size_of(&app.models_dir().join("m/m.gguf.part")), 400);
    assert!(app.models_dir().join("m/m.gguf.part.json").exists(), "the next attempt, or a person, goes on from here");
}

#[test]
fn an_answer_that_says_its_end_too_soon_is_no_file_either() {
    // A clean close and no length from the hub: only the size the page was told can tell it is short.
    let hub = hub_saying(b"HTTP/1.1 200 OK\r\nConnection: close\r\n\r\nshort".to_vec());
    let (_folder, app) = controller("short", hub.address());
    let job = download(&app, vec![file()]);
    assert_eq!(job["status"], json!("error"), "{job}");
    assert!(Coerce::text(job.get("error")).contains("incomplete download"), "{job}");
    assert!(!app.models_dir().join("m/m.gguf").exists());
}

#[test]
fn attempts_that_move_nothing_give_up_after_the_second() {
    let hub = hub_giving(the_file(), vec![0]);
    let (_folder, app) = controller("still", hub.address());
    let job = download(&app, vec![file()]);
    assert_eq!(job["status"], json!("error"), "{job}");
    assert_eq!(ranges(&hub), [None, None]);
    assert_eq!(job["attempt"], json!(2));
}

#[test]
fn a_request_that_never_connects_gives_up_after_two_tries_and_says_what_happened() {
    let free = TcpListener::bind("127.0.0.1:0").unwrap().local_addr().unwrap();
    let (_folder, app) = controller("no-hub", &format!("http://{free}"));
    let job = download(&app, vec![file()]);
    assert_eq!((&job["status"], &job["attempt"]), (&json!("error"), &json!(2)), "{job}");
    assert!(!Coerce::text(job.get("error")).is_empty());
    assert!(!app.models_dir().join("m/m.gguf").exists());
}

/// A hub that refuses a file with this status and says this of the repository.
fn walled(status: &'static str, record: &'static str) -> StandIn {
    StandIn::serving(move |head| {
        let target = head.split_whitespace().nth(1).unwrap_or_default();
        if target.starts_with("/api/models/") {
            StandIn::answer("200 OK", "", record.as_bytes())
        } else {
            StandIn::answer(status, "", b"no")
        }
    })
}

#[test]
fn the_hub_s_wall_is_asked_once_a_missing_file_twice_and_only_a_gated_repository_names_a_door() {
    let resolve = format!("/{REPO}/resolve/main/m.gguf");
    let record = format!("/api/models/{REPO}");
    for (name, status, said, targets, door) in [
        ("gated", "403 Forbidden", r#"{"gated": "manual"}"#, vec![resolve.clone(), record.clone()], true),
        ("login", "401 Unauthorized", r#"{"gated": "auto"}"#, vec![resolve.clone(), record.clone()], true),
        ("open", "403 Forbidden", r#"{"gated": false}"#, vec![resolve.clone(), record.clone()], false),
        ("missing", "404 Not Found", r#"{"gated": "manual"}"#, vec![resolve.clone(), resolve.clone()], false),
        ("broken", "500 Oops", r#"{"gated": "manual"}"#, vec![resolve.clone(), resolve.clone()], false),
    ] {
        let hub = walled(status, said);
        let (_folder, app) = controller(&format!("wall-{name}"), hub.address());
        let job = download(&app, vec![file()]);
        assert_eq!(job["status"], json!("error"), "{name}: {job}");
        assert_eq!(hub.targets(), targets, "{name}");
        assert_eq!(job.get("access").is_some(), door, "{name}: {job}");
        if door {
            assert_eq!(job["access"]["url"], json!(format!("{}/{REPO}", hub.address())), "{name}");
            assert_eq!(job["access"]["repo"], json!(REPO), "{name}");
        }
    }
}

#[test]
fn every_request_of_a_job_says_who_asks_and_carries_the_token() {
    let hub = hub_giving(the_file(), vec![usize::MAX]);
    let (_folder, app) = controller("token", hub.address());
    let id = Downloads::of(&app).start(REPO, vec![file()], &models(&app), "secret-word");
    finished(&app, &id);
    let head = &hub.asked()[0];
    assert!(head.contains("Authorization: Bearer secret-word\r\n"), "{head}");
    assert!(head.contains("User-Agent: lama-caravan/1.0\r\n"), "{head}");
}

#[test]
fn a_partial_of_another_build_is_thrown_away_and_not_glued_to_the_new_one() {
    let hub = hub_giving(the_file(), vec![usize::MAX]);
    let (_folder, app) = controller("other-build", hub.address());
    partial(&app, &b"OLD".repeat(100), SIZE + 12345);
    download(&app, vec![file()]);
    assert_eq!(ranges(&hub), [None]);
    assert_eq!(std::fs::read(app.models_dir().join("m/m.gguf")).unwrap(), the_file());
}

#[test]
fn a_partial_of_another_file_or_repository_is_thrown_away_too() {
    for (name, repo, path) in [("other-repo", "acme/else", "m.gguf"), ("other-path", REPO, "else.gguf")] {
        let hub = hub_giving(the_file(), vec![usize::MAX]);
        let (_folder, app) = controller(name, hub.address());
        partial(&app, &[b'?'; 700], SIZE);
        let manifest = json!({"repo": repo, "path": path, "size": SIZE});
        std::fs::write(app.models_dir().join("m/m.gguf.part.json"), manifest.to_string()).unwrap();
        download(&app, vec![file()]);
        assert_eq!(ranges(&hub), [None], "{name}");
        assert_eq!(std::fs::read(app.models_dir().join("m/m.gguf")).unwrap(), the_file(), "{name}");
    }
}

#[test]
fn a_partial_with_no_manifest_or_no_size_is_nobody_s_and_starts_again() {
    for (name, manifest) in
        [("no-manifest", None), ("no-size", Some(json!({"repo": REPO, "path": "m.gguf"}))), ("broken", Some(json!("text")))]
    {
        let hub = hub_giving(the_file(), vec![usize::MAX]);
        let (_folder, app) = controller(name, hub.address());
        partial(&app, &[b'?'; 700], 0);
        let at = app.models_dir().join("m/m.gguf.part.json");
        match manifest {
            Some(said) => std::fs::write(&at, said.to_string()).unwrap(),
            None => std::fs::remove_file(&at).unwrap(),
        }
        download(&app, vec![file()]);
        assert_eq!(ranges(&hub), [None], "{name}");
        assert_eq!(std::fs::read(app.models_dir().join("m/m.gguf")).unwrap(), the_file(), "{name}");
    }
}

#[test]
fn a_partial_whose_build_nobody_can_tell_starts_again_when_neither_side_says_a_size() {
    let hub = hub_giving(the_file(), vec![usize::MAX]);
    let (_folder, app) = controller("no-sizes", hub.address());
    partial(&app, &[b'?'; 700], 0);
    download(&app, vec![DownloadFile { size: 0, ..file() }]);
    assert_eq!(ranges(&hub), [None], "two zeros are no promise of one build");
    assert_eq!(std::fs::read(app.models_dir().join("m/m.gguf")).unwrap(), the_file());
}

#[test]
fn a_partial_of_the_same_build_is_resumed() {
    let hub = hub_giving(the_file(), vec![usize::MAX]);
    let (_folder, app) = controller("same-build", hub.address());
    partial(&app, &the_file()[..400], SIZE);
    let job = download(&app, vec![file()]);
    assert_eq!(ranges(&hub), [Some(400)]);
    assert_eq!(job["total_bytes_done"], json!(SIZE));
    assert_eq!(std::fs::read(app.models_dir().join("m/m.gguf")).unwrap(), the_file());
}

#[test]
fn a_partial_of_the_older_naming_is_taken_up_and_only_its_own_strays_go() {
    let hub = hub_giving(the_file(), vec![usize::MAX]);
    let (_folder, app) = controller("legacy", hub.address());
    let folder = app.models_dir().join("m");
    partial(&app, &the_file()[..400], SIZE);
    std::fs::rename(folder.join("m.gguf.part"), folder.join("m.gguf.part-2")).unwrap();
    std::fs::write(folder.join("m.gguf.part-1"), b"older").unwrap();
    std::fs::write(folder.join("m.gguf.parted"), b"not a partial").unwrap();
    std::fs::write(folder.join("n.gguf.part-1"), b"another file's").unwrap();
    download(&app, vec![file()]);
    assert_eq!(ranges(&hub), [Some(400)], "the newest goes on");
    let mut left: Vec<String> =
        std::fs::read_dir(&folder).unwrap().flatten().map(|entry| entry.file_name().to_string_lossy().into_owned()).collect();
    left.sort();
    assert_eq!(left, ["m.gguf", "m.gguf.parted", "n.gguf.part-1"]);
}

#[test]
fn a_new_build_lands_by_a_new_name_and_a_running_cell_keeps_what_it_opened() {
    let hub = hub_giving(the_file(), vec![usize::MAX]);
    let (_folder, app) = controller("swap", hub.address());
    let dest = app.models_dir().join("m/m.gguf");
    std::fs::create_dir_all(dest.parent().unwrap()).unwrap();
    std::fs::write(&dest, b"OLD BUILD").unwrap();
    let (mut held, old) = (std::fs::File::open(&dest).unwrap(), std::fs::metadata(&dest).unwrap().ino());
    let job = download(&app, vec![file()]);
    assert_eq!(job["status"], json!("done"), "{job}");
    assert_ne!(std::fs::metadata(&dest).unwrap().ino(), old, "a rename and not a write into the file a cell has open");
    assert_eq!(std::fs::read(&dest).unwrap(), the_file());
    let mut seen = Vec::new();
    held.read_to_end(&mut seen).unwrap();
    assert_eq!(seen, b"OLD BUILD");
}

#[test]
fn a_redirect_with_nowhere_to_go_writes_nothing_over_the_working_build() {
    let hub = hub_saying(StandIn::answer("302 Found", "", b"moved"));
    let (_folder, app) = controller("no-location", hub.address());
    let dest = app.models_dir().join("m/m.gguf");
    std::fs::create_dir_all(dest.parent().unwrap()).unwrap();
    std::fs::write(&dest, b"THE WORKING BUILD").unwrap();
    let job = download(&app, vec![file()]);
    assert_eq!(job["status"], json!("error"), "{job}");
    assert_eq!(std::fs::read(&dest).unwrap(), b"THE WORKING BUILD");
}

#[test]
fn a_small_file_the_hub_sends_elsewhere_by_a_relative_address_lands() {
    let body = the_file();
    let hub = StandIn::serving(move |head| {
        if head.split_whitespace().nth(1).unwrap_or_default().starts_with("/api/resolve-cache/") {
            StandIn::answer("200 OK", "", &body)
        } else {
            StandIn::answer("307 Temporary Redirect", "Location: /api/resolve-cache/models/acme/m.gguf?x=1\r\n", b"")
        }
    });
    let (_folder, app) = controller("relative", hub.address());
    let job = download(&app, vec![file()]);
    assert_eq!(job["status"], json!("done"), "{job}");
    assert_eq!(std::fs::read(app.models_dir().join("m/m.gguf")).unwrap(), the_file());
}

fn length_head(length: usize) -> Vec<u8> {
    format!("HTTP/1.1 200 OK\r\nContent-Length: {length}\r\nConnection: close\r\n\r\n").into_bytes()
}

#[test]
fn a_cancel_in_the_middle_of_a_file_keeps_the_bytes_and_the_manifest_and_lists_them_at_once() {
    let (total, first) = (3 * (1 << 20), 1000);
    let body = bytes(total, 1);
    let mut start = length_head(total);
    start.extend_from_slice(&body[..first]);
    let hub = HeldHub::new(vec![(start, body[first..].to_vec())]);
    let folder = TestFolder::new("downloads-cancel");
    // The clock stands: the list of what is interrupted would be read from its memory for good, if the cancel did not clear it.
    let app = TestApp::with_clock(&folder.path, &[("CARAVAN_HUB_URL", &hub.address)], HandClock::at(1000));
    let downloads = Downloads::of(&app);
    assert_eq!(downloads.scan_interrupted(&models(&app)), Vec::<Value>::new());
    let id = downloads.start(REPO, vec![DownloadFile { size: total as i64, ..file() }], &models(&app), "");
    let part = app.models_dir().join("m/m.gguf.part");
    wait_for("first bytes", || size_of(&part) == first as u64);
    assert!(downloads.cancel(&id).is_some());
    hub.word.send(()).unwrap();
    let job = finished(&app, &id);
    assert_eq!((&job["status"], &job["done"], &job["error"]), (&json!("cancelled"), &json!(true), &Value::Null), "{job}");
    let kept = size_of(&part);
    assert!(kept >= first as u64 && kept < total as u64, "the bytes stay, and it stopped where it was: {kept}");
    assert!(app.models_dir().join("m/m.gguf.part.json").exists());
    assert!(!app.models_dir().join("m/m.gguf").exists(), "the final name is never written");
    assert_eq!(hub.targets().len(), 1, "a cancel is not retried like a dropped connection");
    let rows = downloads.scan_interrupted(&models(&app));
    assert_eq!(rows.len(), 1, "{rows:?}");
    assert_eq!(
        (&rows[0]["status"], &rows[0]["resumable"], &rows[0]["total_bytes_done"]),
        (&json!("interrupted"), &json!(true), &json!(kept))
    );
}

#[test]
fn a_cancel_while_one_file_finishes_keeps_it_whole_and_the_next_is_never_asked_for() {
    let body = bytes(2000, 1);
    let mut whole = b"HTTP/1.1 200 OK\r\nConnection: close\r\n\r\n".to_vec();
    whole.extend_from_slice(&body);
    let hub = HeldHub::new(vec![(whole, Vec::new())]);
    let (_folder, app) = controller("cancel-next", &hub.address);
    let downloads = Downloads::of(&app);
    let (first, next) = (
        DownloadFile { path: "a.gguf".to_string(), name: "a.gguf".to_string(), dest_dir: "m".to_string(), size: 2000 },
        DownloadFile { path: "b.gguf".to_string(), name: "b.gguf".to_string(), dest_dir: "m".to_string(), size: 2000 },
    );
    let id = downloads.start(REPO, vec![first, next], &models(&app), "");
    let part = app.models_dir().join("m/a.gguf.part");
    wait_for("all its bytes", || size_of(&part) == 2000);
    assert!(downloads.cancel(&id).is_some());
    hub.word.send(()).unwrap();
    let job = finished(&app, &id);
    assert_eq!(job["status"], json!("cancelled"), "{job}");
    assert_eq!(hub.targets(), [format!("/{REPO}/resolve/main/a.gguf")], "the next one is never asked for");
    let mut left: Vec<String> = std::fs::read_dir(app.models_dir().join("m"))
        .unwrap()
        .flatten()
        .map(|entry| entry.file_name().to_string_lossy().into_owned())
        .collect();
    left.sort();
    // The press comes while the job waits for the end of the answer. By a hair it can come before the job's last look at it, and then the file stays a whole
    // partial: never half of it under its name, and nothing of the next either way.
    if left == ["a.gguf"] {
        assert_eq!(std::fs::read(app.models_dir().join("m/a.gguf")).unwrap(), body);
    } else {
        assert_eq!(left, ["a.gguf.part", "a.gguf.part.json"]);
        assert_eq!(std::fs::read(&part).unwrap(), body);
    }
}

#[test]
fn a_cancel_before_a_single_byte_leaves_no_trace() {
    let mut whole = length_head(SIZE);
    whole.extend_from_slice(&the_file());
    let hub = HeldHub::new(vec![(Vec::new(), whole)]);
    let (_folder, app) = controller("cancel-early", &hub.address);
    let downloads = Downloads::of(&app);
    let id = downloads.start(REPO, vec![file()], &models(&app), "");
    wait_for("the request", || !hub.targets().is_empty());
    assert!(downloads.cancel(&id).is_some());
    hub.word.send(()).unwrap();
    let job = finished(&app, &id);
    assert_eq!(job["status"], json!("cancelled"), "{job}");
    assert!(!app.models_dir().join("m/m.gguf.part").exists() && !app.models_dir().join("m/m.gguf.part.json").exists());
}

#[test]
fn a_cancel_before_the_job_starts_sends_no_request() {
    let hub = hub_giving(the_file(), vec![usize::MAX]);
    let (_folder, app) = controller("cancel-first", hub.address());
    let downloads = Downloads::of(&app);
    downloads.jobs().insert(
        "job".to_string(),
        json!({"status": "running", "done": false, "repo": REPO, "filePaths": ["m/m.gguf"], "total_bytes_done": 0}),
    );
    assert!(downloads.cancel("job").is_some());
    downloads.run("job", REPO, &[file()], &models(&app), "");
    assert_eq!(downloads.job("job").unwrap()["status"], json!("cancelled"));
    assert_eq!(hub.asked(), Vec::<String>::new());
}

#[test]
fn only_a_running_job_can_be_cancelled() {
    let hub = hub_giving(the_file(), vec![usize::MAX]);
    let (_folder, app) = controller("cancel-who", hub.address());
    let downloads = Downloads::of(&app);
    assert_eq!(downloads.cancel("nope"), None);
    downloads.jobs().insert("over".to_string(), json!({"status": "done", "done": true}));
    assert_eq!(downloads.cancel("over"), None);
    assert_eq!(downloads.job("over").unwrap().get("cancel"), None);
}

#[test]
fn a_running_job_s_partial_is_not_called_interrupted_and_another_folder_s_is() {
    let hub = hub_giving(the_file(), vec![usize::MAX]);
    let (_folder, app) = controller("whose", hub.address());
    let downloads = Downloads::of(&app);
    downloads.jobs().insert("live".to_string(), json!({"done": false, "repo": REPO, "filePaths": ["b/m.gguf"]}));
    for sub in ["a", "b"] {
        let at = app.models_dir().join(sub);
        std::fs::create_dir_all(&at).unwrap();
        std::fs::write(at.join("m.gguf.part"), b"?").unwrap();
    }
    let rows = downloads.scan_interrupted(&models(&app));
    let seen: Vec<&Value> = rows.iter().map(|row| &row["filePaths"][0]).collect();
    assert_eq!(seen, [&json!("a/m.gguf")]);
    assert_eq!(rows[0]["resumable"], json!(false), "with no manifest it can only be named");
}

/// What is left of a stopped download: a partial and its manifest.
fn leftover(app: &App, folder: &str, name: &str, size: usize) -> PathBuf {
    let target = app.models_dir().join(folder).join(format!("{name}.part"));
    std::fs::create_dir_all(target.parent().unwrap()).unwrap();
    std::fs::write(&target, vec![b'x'; size]).unwrap();
    std::fs::write(
        target.with_file_name(format!("{name}.part.json")),
        json!({"repo": REPO, "path": name, "size": 5000}).to_string(),
    )
    .unwrap();
    target
}

#[test]
fn a_discard_says_what_it_freed_and_takes_the_partial_its_manifest_and_the_folders_it_empties() {
    let hub = hub_giving(the_file(), vec![usize::MAX]);
    let (_folder, app) = controller("discard", hub.address());
    let (downloads, root) = (Downloads::of(&app), models(&app));
    let gone = leftover(&app, "d/acme/Q4", "x.gguf", 1000);
    assert_eq!(downloads.scan_interrupted(&root).len(), 1);
    assert_eq!(downloads.discard_interrupted(&root, "d/acme/Q4", "x.gguf"), Ok(1000));
    assert!(!gone.exists() && !gone.with_file_name("x.gguf.part.json").exists());
    assert!(
        !app.models_dir().join("d").exists() && app.models_dir().is_dir(),
        "the folders go, up to the models folder and not it"
    );
    assert_eq!(
        downloads.scan_interrupted(&root),
        Vec::<Value>::new(),
        "the row goes at once, not when the list's seconds are up"
    );
    // A whole file beside it stays with its folder; a folder with something in it stays.
    let first = leftover(&app, "e/acme/Q4", "one.gguf", 10);
    let second = leftover(&app, "e/acme/Q8", "two.gguf", 10);
    let whole = app.models_dir().join("e/acme/Q4/whole.gguf");
    std::fs::write(&whole, b"w").unwrap();
    downloads.discard_interrupted(&root, "e/acme/Q4", "one.gguf").unwrap();
    assert!(!first.exists() && whole.exists());
    downloads.discard_interrupted(&root, "e/acme/Q8", "two.gguf").unwrap();
    assert!(!second.parent().unwrap().exists() && app.models_dir().join("e/acme").is_dir());
    // At the root of the models folder.
    let at_root = leftover(&app, ".", "root.gguf", 7);
    assert_eq!(downloads.discard_interrupted(&root, ".", "root.gguf"), Ok(7));
    assert!(!at_root.exists() && app.models_dir().is_dir());
}

#[test]
fn a_discard_never_leaves_the_models_folder() {
    let hub = hub_giving(the_file(), vec![usize::MAX]);
    let (folder, app) = controller("discard-out", hub.address());
    let (downloads, root) = (Downloads::of(&app), models(&app));
    let outside = folder.path.join("outside.gguf.part");
    let above = folder.path.to_string_lossy().into_owned();
    for (dest, name) in [
        ("..", "outside.gguf"),
        ("a/../..", "outside.gguf"),
        (above.as_str(), "outside.gguf"),
        (".", "../outside.gguf"),
        (".", ".."),
        (".", "."),
        (".", ""),
    ] {
        std::fs::write(&outside, b"o").unwrap();
        assert_eq!(
            downloads.discard_interrupted(&root, dest, name),
            Err("invalid destDir or name".to_string()),
            "{dest:?} {name:?}"
        );
        assert!(outside.exists(), "{dest:?} {name:?}");
    }
}

#[test]
fn a_discard_refuses_a_partial_a_running_job_writes_however_its_folder_is_spelled() {
    let hub = hub_giving(the_file(), vec![usize::MAX]);
    let (_folder, app) = controller("discard-live", hub.address());
    let (downloads, root) = (Downloads::of(&app), models(&app));
    let live = leftover(&app, "f/acme/Q4", "busy.gguf", 1000);
    downloads
        .jobs()
        .insert("writing".to_string(), json!({"status": "running", "done": false, "filePaths": ["f/acme/Q4/busy.gguf"]}));
    for dest in ["f/acme/Q4", "./f/acme/Q4", "f/acme//Q4", "f/./acme/Q4", "f/acme/Q4/"] {
        assert_eq!(
            downloads.discard_interrupted(&root, dest, "busy.gguf"),
            Err("a running download is writing this file: stop it first".to_string()),
            "{dest}"
        );
        assert!(live.exists() && live.with_file_name("busy.gguf.part.json").exists(), "{dest}");
    }
    downloads.jobs().get_mut("writing").unwrap()["done"] = json!(true);
    assert_eq!(downloads.discard_interrupted(&root, "f/acme/Q4", "busy.gguf"), Ok(1000), "once it has ended the partial goes");
    assert_eq!(
        downloads.discard_interrupted(&root, "f/acme/Q4", "busy.gguf"),
        Err("this partial is gone".to_string()),
        "gone is said, not done"
    );
}

#[test]
fn a_resume_reads_what_it_resumes_from_the_manifest_and_stays_inside_the_models_folder() {
    let hub = hub_giving(the_file(), vec![usize::MAX]);
    let (folder, app) = controller("resume", hub.address());
    let (downloads, root) = (Downloads::of(&app), models(&app));
    partial(&app, &the_file()[..400], SIZE);
    let id = downloads.resume_interrupted(&root, "", "m", "m.gguf").unwrap();
    let job = finished(&app, &id);
    assert_eq!(job["status"], json!("done"), "{job}");
    assert_eq!(job["total_files"], json!(1), "a manifest of an older controller names no other files: its job is its one file");
    assert_eq!(ranges(&hub), [Some(400)]);
    assert_eq!(std::fs::read(app.models_dir().join("m/m.gguf")).unwrap(), the_file());
    // A manifest waits outside the models folder: a resume that went there would start a download that lands there.
    let said = json!({"repo": REPO, "path": "m.gguf", "size": SIZE}).to_string();
    std::fs::write(folder.path.join("outside.gguf.part.json"), &said).unwrap();
    let above = folder.path.to_string_lossy().into_owned();
    for (dest, name, words) in [
        ("..", "outside.gguf", "invalid destDir"),
        ("m/..", "outside.gguf", "invalid destDir"),
        (above.as_str(), "outside.gguf", "invalid destDir"),
        (".", "../outside.gguf", "invalid name"),
        ("m", "..", "invalid name"),
        ("m", "", "invalid name"),
    ] {
        let refused = downloads.resume_interrupted(&root, "", dest, name).err().unwrap();
        assert_eq!(refused.message, words, "{dest:?} {name:?}");
    }
    let refused = downloads.resume_interrupted(&root, "", "m", "gone.gguf").err().unwrap();
    assert!(refused.message.contains("no manifest"), "{}", refused.message);
    std::fs::write(app.models_dir().join("m/half.gguf.part.json"), json!({"repo": REPO}).to_string()).unwrap();
    let refused = downloads.resume_interrupted(&root, "", "m", "half.gguf").err().unwrap();
    assert!(refused.message.contains("missing the repo or file path"), "{}", refused.message);
    assert_eq!(hub.asked().len(), 1, "a refusal starts nothing");
}

/// A hub with several files, each answered from where it is asked; the file `cut` names gives no byte past its `limit`, though its length says the whole.
fn hub_with(files: Vec<(&'static str, Vec<u8>)>, cut: Option<(&'static str, usize)>) -> StandIn {
    StandIn::serving(move |head| {
        let target = head.split_whitespace().nth(1).unwrap_or_default().to_string();
        let Some((name, body)) = files.iter().find(|(name, _)| target.ends_with(&format!("/{name}"))) else {
            return b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n".to_vec();
        };
        let start = range_of(head).unwrap_or(0).min(body.len());
        let rest = &body[start..];
        let give = match cut {
            Some((short, limit)) if short == *name => limit.saturating_sub(start).min(rest.len()),
            _ => rest.len(),
        };
        let status = if start > 0 { "206 Partial Content" } else { "200 OK" };
        let mut out = format!("HTTP/1.1 {status}\r\nContent-Length: {}\r\nConnection: close\r\n\r\n", rest.len()).into_bytes();
        out.extend_from_slice(&rest[..give]);
        out
    })
}

/// A file of the job in the folder `m`, named as the hub has it.
fn in_m(name: &str, size: usize) -> DownloadFile {
    DownloadFile { path: name.to_string(), name: name.to_string(), dest_dir: "m".to_string(), size: size as i64 }
}

fn fetched(hub: &StandIn) -> Vec<String> {
    hub.targets().iter().map(|target| target.rsplit('/').next().unwrap().to_string()).collect()
}

#[test]
fn a_job_cut_off_in_its_middle_keeps_the_files_after_it_and_its_resume_after_a_restart_brings_them_all() {
    let (a, b, c) = (bytes(1500, 1), bytes(SIZE, 2), bytes(2500, 3));
    let files = || vec![("a.gguf", a.clone()), ("b.gguf", b.clone()), ("c.gguf", c.clone())];
    let broken = hub_with(files(), Some(("b.gguf", 1000)));
    let (folder, app) = controller("whole-job", broken.address());
    let job = download(&app, vec![in_m("a.gguf", 1500), in_m("b.gguf", SIZE), in_m("c.gguf", 2500)]);
    assert_eq!(job["status"], json!("error"), "{job}");
    assert_eq!(fetched(&broken), ["a.gguf", "b.gguf", "b.gguf"], "the file after the broken one is never asked for");
    let manifest: Value = serde_json::from_slice(&std::fs::read(app.models_dir().join("m/b.gguf.part.json")).unwrap()).unwrap();
    assert_eq!(
        manifest["rest"],
        json!([in_m("c.gguf", 2500).said()]),
        "the partial's manifest names the file of the job after it"
    );
    // The restart: a controller with no memory of the job, over the same folder.
    let whole = hub_with(files(), None);
    let again = TestApp::over(&folder.path, &[("CARAVAN_HUB_URL", whole.address())]);
    let downloads = Downloads::of(&again);
    let rows = downloads.scan_interrupted(&models(&again));
    assert_eq!(rows.len(), 1, "{rows:?}");
    let row = &rows[0];
    assert_eq!(
        (&row["total_files"], &row["fileNames"], &row["filePaths"], &row["current_file"]),
        (&json!(2), &json!(["b.gguf", "c.gguf"]), &json!(["m/b.gguf", "m/c.gguf"]), &json!("b.gguf")),
        "the row is the job still to fetch: the partial's file and the one after it"
    );
    assert_eq!(
        (&row["total_bytes"], &row["total_bytes_done"], &row["file_bytes_total"], &row["resumable"]),
        (&json!(SIZE + 2500), &json!(1000), &json!(SIZE), &json!(true))
    );
    let id = downloads.resume_interrupted(&models(&again), "", "m", "b.gguf").unwrap();
    let resumed = finished(&again, &id);
    assert_eq!((&resumed["status"], &resumed["total_files"]), (&json!("done"), &json!(2)), "{resumed}");
    assert_eq!(fetched(&whole), ["b.gguf", "c.gguf"], "what is on the disk is not asked for again");
    assert_eq!(ranges(&whole), [Some(1000), None], "the partial goes on from its bytes, the next file from its start");
    for (name, body) in [("a.gguf", &a), ("b.gguf", &b), ("c.gguf", &c)] {
        assert_eq!(&std::fs::read(again.models_dir().join("m").join(name)).unwrap(), body, "{name}");
    }
}

#[test]
fn a_resume_leaves_out_the_files_of_its_job_on_the_disk_or_written_by_a_running_job() {
    let (b, e) = (bytes(SIZE, 2), bytes(800, 5));
    let hub =
        hub_with(vec![("b.gguf", b.clone()), ("c.gguf", bytes(10, 3)), ("d.gguf", bytes(10, 4)), ("e.gguf", e.clone())], None);
    let (_folder, app) = controller("whole-left", hub.address());
    let (downloads, root) = (Downloads::of(&app), models(&app));
    let folder = app.models_dir().join("m");
    std::fs::create_dir_all(&folder).unwrap();
    std::fs::write(folder.join("b.gguf.part"), &b[..1000]).unwrap();
    let rest = json!([in_m("c.gguf", 10).said(), in_m("d.gguf", 10).said(), in_m("e.gguf", 800).said()]);
    let said = json!({"repo": REPO, "path": "b.gguf", "name": "b.gguf", "destDir": "m", "size": SIZE, "rest": rest});
    std::fs::write(folder.join("b.gguf.part.json"), said.to_string()).unwrap();
    std::fs::write(folder.join("c.gguf"), bytes(10, 3)).unwrap();
    downloads
        .jobs()
        .insert("writing".to_string(), json!({"status": "running", "done": false, "repo": REPO, "filePaths": ["m/d.gguf"]}));
    let rows = downloads.scan_interrupted(&root);
    assert_eq!(
        (&rows[0]["total_files"], &rows[0]["fileNames"], &rows[0]["total_bytes"]),
        (&json!(2), &json!(["b.gguf", "e.gguf"]), &json!(SIZE + 800)),
        "{rows:?}"
    );
    let id = downloads.resume_interrupted(&root, "", "m", "b.gguf").unwrap();
    assert_eq!(finished(&app, &id)["status"], json!("done"));
    assert_eq!(fetched(&hub), ["b.gguf", "e.gguf"], "a file on the disk is done, and a running job's file is that job's");
    assert_eq!(std::fs::read(folder.join("e.gguf")).unwrap(), e);
    assert!(!folder.join("d.gguf").exists(), "nothing of the running job's file is written by the resume");
}

#[test]
fn a_size_one_file_of_the_job_does_not_say_leaves_the_whole_unknown() {
    let (_folder, app) = controller("whole-size", "http://127.0.0.1:9");
    let folder = app.models_dir().join("m");
    std::fs::create_dir_all(&folder).unwrap();
    std::fs::write(folder.join("b.gguf.part"), b"0123").unwrap();
    let said = json!({"repo": REPO, "path": "b.gguf", "size": SIZE, "rest": [in_m("c.gguf", 0).said()]});
    std::fs::write(folder.join("b.gguf.part.json"), said.to_string()).unwrap();
    let rows = Downloads::of(&app).scan_interrupted(&models(&app));
    assert_eq!(
        (&rows[0]["total_files"], &rows[0]["total_bytes"], &rows[0]["file_bytes_total"]),
        (&json!(2), &json!(0), &json!(SIZE)),
        "a sum without the unsaid size would be drawn as the whole"
    );
}

#[test]
fn a_manifest_whose_other_files_cannot_be_read_is_refused_and_not_guessed() {
    let hub = hub_giving(the_file(), vec![usize::MAX]);
    let (_folder, app) = controller("whole-unread", hub.address());
    let (downloads, root) = (Downloads::of(&app), models(&app));
    let file = |name: &str, dest: &str| json!([{"path": "c.gguf", "name": name, "destDir": dest, "size": 1}]);
    for (rest, words) in [
        (json!("c.gguf"), "is not a list"),
        (json!({"c.gguf": 1}), "is not a list"),
        (file("../c.gguf", "m"), "cannot fetch into the models folder"),
        (file("c.gguf", "/etc"), "cannot fetch into the models folder"),
        (file("c.gguf", "m/../.."), "cannot fetch into the models folder"),
        (json!([{"name": "c.gguf", "destDir": "m", "size": 1}]), "cannot fetch into the models folder"),
        (json!([7]), "cannot fetch into the models folder"),
    ] {
        let part = partial(&app, &the_file()[..400], SIZE);
        let said = json!({"repo": REPO, "path": "m.gguf", "name": "m.gguf", "destDir": "m", "size": SIZE, "rest": rest});
        std::fs::write(part.with_file_name("m.gguf.part.json"), said.to_string()).unwrap();
        *app.downloads.scan.lock().unwrap() = None;
        let rows = downloads.scan_interrupted(&root);
        assert_eq!((&rows[0]["resumable"], &rows[0]["total_files"]), (&json!(false), &json!(1)), "{rest}");
        let refused = downloads.resume_interrupted(&root, "", "m", "m.gguf").err().unwrap();
        assert!(refused.message.contains(words), "{rest}: {}", refused.message);
    }
    assert_eq!(hub.asked(), Vec::<String>::new(), "a refusal starts nothing");
}

#[test]
fn the_same_file_twice_is_one_job_and_the_same_name_in_another_folder_is_another() {
    let free = TcpListener::bind("127.0.0.1:0").unwrap().local_addr().unwrap();
    let (_folder, app) = controller("twice", &format!("http://{free}"));
    let downloads = Downloads::of(&app);
    downloads
        .jobs()
        .insert("already".to_string(), json!({"status": "running", "done": false, "repo": REPO, "filePaths": ["a/m.gguf"]}));
    let in_folder = |dest: &str| DownloadFile { dest_dir: dest.to_string(), ..file() };
    assert_eq!(downloads.start(REPO, vec![in_folder("a")], &models(&app), ""), "already", "one partial, one writer");
    let other = downloads.start(REPO, vec![in_folder("b")], &models(&app), "");
    assert_ne!(other, "already");
    assert_eq!(finished(&app, &other)["filePaths"], json!(["b/m.gguf"]), "a job names where it writes");
}

#[test]
fn what_a_download_would_write_over_is_a_file_and_nothing_else() {
    let hub = hub_giving(the_file(), vec![usize::MAX]);
    let (_folder, app) = controller("over", hub.address());
    let root = app.models_dir();
    for (rel, body) in [("Qwen/unsloth/Q4_K_M/q4.gguf", &b"weights"[..]), ("Qwen/unsloth/Q8_0/q8.gguf.part", &b"half"[..])] {
        std::fs::create_dir_all(root.join(rel).parent().unwrap()).unwrap();
        std::fs::write(root.join(rel), body).unwrap();
    }
    std::fs::create_dir_all(root.join("Qwen/unsloth/folder.gguf")).unwrap();
    let wanted = |dest: &str, name: &str| DownloadFile {
        path: name.to_string(),
        name: name.to_string(),
        dest_dir: dest.to_string(),
        size: 7,
    };
    let taken = Downloads::replaces_on_disk(
        &[
            wanted("Qwen/unsloth/Q4_K_M", "q4.gguf"),
            wanted("Qwen/unsloth/Q8_0", "q8.gguf"),
            wanted("Qwen/unsloth/Q2_K", "q2.gguf"),
            wanted("Qwen/unsloth", "folder.gguf"),
            wanted("", "root.gguf"),
        ],
        &models(&app),
    );
    assert_eq!(taken, ["Qwen/unsloth/Q4_K_M/q4.gguf"], "a missing file, a leftover .part and a folder of that name are not");
}

#[test]
fn the_route_starts_over_a_file_on_disk_only_when_it_was_told_to() {
    let hub = hub_giving(the_file(), vec![usize::MAX]);
    let (_folder, app) = controller("route", hub.address());
    let dest = app.models_dir().join("m/m.gguf");
    std::fs::create_dir_all(dest.parent().unwrap()).unwrap();
    std::fs::write(&dest, b"weights").unwrap();
    let wanted = json!([{"path": "m.gguf", "name": "m.gguf", "destDir": "m", "size": SIZE}]);
    for replace in [None, Some(json!(false)), Some(json!("false")), Some(json!(0)), Some(json!(""))] {
        let mut body = json!({"repo": REPO, "files": wanted});
        if let Some(replace) = &replace {
            body["replace"] = replace.clone();
        }
        let answer = posted(&app, "/api/hf/download", body);
        assert_eq!(
            answer,
            json!({"ok": false, "code": "exists", "files": ["m/m.gguf"], "error": "already on disk: m/m.gguf"}),
            "replace {replace:?}"
        );
        assert_eq!(Downloads::of(&app).all().len(), 0, "replace {replace:?}: refused means nothing started");
        assert_eq!(hub.asked(), Vec::<String>::new());
    }
    assert_eq!(std::fs::read(&dest).unwrap(), b"weights");
    let answer = posted(&app, "/api/hf/download", json!({"repo": REPO, "files": wanted, "replace": true}));
    let id = Coerce::text(answer.get("jobId"));
    assert_eq!(answer, json!({"ok": true, "jobId": id}));
    assert_eq!(finished(&app, &id)["status"], json!("done"));
    assert_eq!(std::fs::read(&dest).unwrap(), the_file());
}

#[test]
fn the_route_starts_new_files_without_a_question_and_a_partial_is_no_file() {
    let hub = hub_giving(the_file(), vec![usize::MAX]);
    let (_folder, app) = controller("route-new", hub.address());
    partial(&app, &the_file()[..400], SIZE);
    let answer = posted(
        &app,
        "/api/hf/download",
        json!({"repo": REPO, "files": [{"path": "m.gguf", "name": "m.gguf", "destDir": "m", "size": SIZE}]}),
    );
    let id = Coerce::text(answer.get("jobId"));
    assert_eq!(finished(&app, &id)["status"], json!("done"), "{answer}");
    assert_eq!(ranges(&hub), [Some(400)]);
}

#[test]
fn the_route_lets_no_file_land_outside_the_models_folder() {
    let hub = hub_giving(the_file(), vec![usize::MAX]);
    let (folder, app) = controller("route-out", hub.address());
    for (dest, name, words) in [
        ("../..", "x.gguf", "invalid destDir"),
        ("/etc", "x.gguf", "invalid destDir"),
        ("m", "../../../outside.gguf", "invalid name"),
        ("m", "a/b.gguf", "invalid name"),
        ("m", "..", "invalid name"),
        ("m", "", "invalid name"),
    ] {
        let answer = posted(
            &app,
            "/api/hf/download",
            json!({"repo": REPO, "replace": true, "files": [{"path": "x", "name": name, "destDir": dest, "size": 1}]}),
        );
        assert_eq!(answer, json!({"ok": false, "error": words}), "{dest:?} {name:?}");
    }
    assert_eq!(hub.asked(), Vec::<String>::new());
    assert!(!folder.path.join("outside.gguf").exists());
    assert_eq!(Downloads::of(&app).all().len(), 0);
}

/// One attempt over a partial of five bytes: `(what came of it, the offset after it, the partial's bytes, what the hub was asked)`.
fn attempt_over_a_partial(name: &str, answer: &'static str) -> (Result<(), Stop>, i64, Vec<u8>, String) {
    let folder = TestFolder::new(&format!("downloads-{name}"));
    let app = TestApp::over(&folder.path, &[]);
    let partial = folder.path.join("x.gguf.part");
    std::fs::write(&partial, b"12345").unwrap();
    let hub = StandIn::serving(move |_| answer.as_bytes().to_vec());
    let file = DownloadFile::of(&json!({"path": "x.gguf", "name": "x.gguf", "size": 10}));
    let mut offset = 5;
    let tried = Downloads::of(&app).one_attempt("job", &format!("{}/file", hub.address()), &file, &partial, &mut offset, 0, "");
    let bytes = std::fs::read(&partial).unwrap();
    (tried, offset, bytes, hub.asked().join(""))
}

#[test]
fn a_hub_that_ignores_the_range_starts_the_file_and_the_count_again() {
    let (tried, offset, bytes, asked) =
        attempt_over_a_partial("ignored", "HTTP/1.1 200 OK\r\nContent-Length: 10\r\nConnection: close\r\n\r\nabc");
    assert!(asked.contains("Range: bytes=5-\r\n"), "{asked}");
    assert!(matches!(tried, Err(Stop::Failed(_))), "three bytes of ten are no file");
    assert_eq!(bytes, b"abc", "the old five are gone: they were the start of the file sent again");
    assert_eq!(offset, 0, "three bytes after a restart moved something, and the next attempt must count them so");
}

#[test]
fn a_redirect_with_nowhere_to_go_lands_nowhere() {
    let (tried, _, bytes, _) =
        attempt_over_a_partial("nowhere", "HTTP/1.1 302 Found\r\nContent-Length: 5\r\nConnection: close\r\n\r\nmoved");
    assert!(matches!(tried, Err(Stop::Failed(_))));
    assert_eq!(bytes, b"12345", "the partial is as it was, and its body is not the file");
}

#[test]
fn a_hub_that_takes_the_range_adds_to_the_partial() {
    let (tried, offset, bytes, _) =
        attempt_over_a_partial("resumed", "HTTP/1.1 206 Partial Content\r\nContent-Length: 5\r\nConnection: close\r\n\r\n67890");
    assert!(tried.is_ok());
    assert_eq!(bytes, b"1234567890");
    assert_eq!(offset, 5);
}
