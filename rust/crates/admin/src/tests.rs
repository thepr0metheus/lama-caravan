//! What this crate's tests stand on: a folder of a test's own, a controller over it, a clock in the test's hand, and an HTTP server that answers
//! what the test says. Nothing here reaches the network or the machine's real state.

#![allow(
    clippy::unwrap_used,
    clippy::panic,
    clippy::indexing_slicing,
    reason = "a helper of a test may stop where it found something wrong"
)]

use crate::app::{App, Outside};
use crate::paths::{AdminPaths, Environment};
use os::clock::{Clock, SystemClock};
use plumbing::SystemCommands;
use std::collections::BTreeMap;
use std::io::{Read, Write};
use std::net::TcpListener;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex};

/// A folder of a test's own, gone when the test ends, whichever way it ends.
pub struct TestFolder {
    /// Where it is.
    pub path: PathBuf,
}

impl TestFolder {
    /// The folder of the test named `name`: two tests of one name are one folder.
    pub fn new(name: &str) -> Self {
        let path = std::env::temp_dir().join(format!("caravan-admin-{name}-{}", std::process::id()));
        drop(std::fs::remove_dir_all(&path));
        std::fs::create_dir_all(&path).unwrap();
        Self { path: std::fs::canonicalize(&path).unwrap() }
    }
}

impl Drop for TestFolder {
    fn drop(&mut self) {
        drop(std::fs::remove_dir_all(&self.path));
    }
}

/// A controller over a folder, in a container's layout: its data folder is `<folder>/data`, its models `<folder>/models`.
pub struct TestApp;

impl TestApp {
    /// With the machine's clock; `vars` are laid over the environment it starts in.
    pub fn over(folder: &Path, vars: &[(&str, &str)]) -> Arc<App> {
        Self::with_clock(folder, vars, Arc::new(SystemClock::new()))
    }

    /// With a clock of the test's.
    pub fn with_clock(folder: &Path, vars: &[(&str, &str)], clock: Arc<dyn Clock>) -> Arc<App> {
        for inner in ["data", "models", "home"] {
            std::fs::create_dir_all(folder.join(inner)).unwrap();
        }
        let text = |path: PathBuf| path.to_string_lossy().into_owned();
        let mut all: BTreeMap<String, String> = BTreeMap::from([
            ("CARAVAN_DATA_DIR".to_string(), text(folder.join("data"))),
            ("LLAMA_MODELS_DIR".to_string(), text(folder.join("models"))),
            ("HOME".to_string(), text(folder.join("home"))),
        ]);
        all.extend(vars.iter().map(|(name, value)| ((*name).to_string(), (*value).to_string())));
        let env = Environment::of(all, folder.join("home"));
        let paths = AdminPaths::from_env(&env, folder.to_path_buf(), true).unwrap();
        App::new(paths, Outside { clock, commands: Arc::new(SystemCommands), env }).unwrap()
    }
}

/// A clock in the test's hand: it stands where it was put, and goes on by `step` at each look when one is set.
#[derive(Debug, Default)]
pub struct HandClock {
    millis: AtomicU64,
    step: AtomicU64,
}

impl HandClock {
    /// Standing at `seconds`.
    pub fn at(seconds: u64) -> Arc<Self> {
        let clock = Self::default();
        clock.millis.store(seconds * 1000, Ordering::SeqCst);
        Arc::new(clock)
    }

    /// Goes on by `seconds`.
    pub fn pass(&self, seconds: u64) {
        self.millis.fetch_add(seconds * 1000, Ordering::SeqCst);
    }

    /// Every look at it from now on takes `seconds`: a wait that counts on the clock ends without waiting.
    pub fn each_look_takes(&self, seconds: u64) {
        self.step.store(seconds * 1000, Ordering::SeqCst);
    }
}

impl Clock for HandClock {
    fn epoch(&self) -> f64 {
        self.millis.fetch_add(self.step.load(Ordering::SeqCst), Ordering::SeqCst) as f64 / 1000.0
    }

    fn monotonic(&self) -> f64 {
        self.epoch()
    }

    fn thread_cpu(&self) -> Option<f64> {
        None
    }
}

/// An HTTP server that answers what the test says: one request on a connection, the answer's bytes as they are, and then it closes. So an answer can
/// be cut anywhere, or be no HTTP at all. Pointed at by `CARAVAN_HUB_URL`, it is the hub.
pub struct StandIn {
    address: String,
    heads: Arc<Mutex<Vec<String>>>,
}

impl StandIn {
    /// Serving: `answer` takes the head of a request, as it came, and gives the bytes that go back.
    pub fn serving(answer: impl Fn(&str) -> Vec<u8> + Send + 'static) -> Self {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = format!("http://{}", listener.local_addr().unwrap());
        let heads = Arc::new(Mutex::new(Vec::new()));
        let kept = Arc::clone(&heads);
        std::thread::spawn(move || {
            for mut stream in listener.incoming().flatten() {
                let mut head = vec![0u8; 16 * 1024];
                let read = stream.read(&mut head).unwrap_or(0);
                let head = String::from_utf8_lossy(&head[..read]).into_owned();
                let bytes = answer(&head);
                kept.lock().unwrap().push(head);
                drop(stream.write_all(&bytes));
            }
        });
        Self { address, heads }
    }

    /// Serving a table: the first row whose path the target starts with answers with `(status line, fields, body)`, and any other target with a 404.
    pub fn table(rows: Vec<(String, String, String, Vec<u8>)>) -> Self {
        Self::serving(move |head| {
            let target = head.split_whitespace().nth(1).unwrap_or_default();
            match rows.iter().find(|row| target.starts_with(row.0.as_str())) {
                Some((_, status, fields, body)) => Self::answer(status, fields, body),
                None => Self::answer("404 Not Found", "", b"nothing here"),
            }
        })
    }

    /// A whole answer's bytes. `fields` are whole lines, each with its CRLF.
    pub fn answer(status: &str, fields: &str, body: &[u8]) -> Vec<u8> {
        let mut out =
            format!("HTTP/1.1 {status}\r\n{fields}Content-Length: {}\r\nConnection: close\r\n\r\n", body.len()).into_bytes();
        out.extend_from_slice(body);
        out
    }

    /// The address it listens at, with no slash at its end.
    pub fn address(&self) -> &str {
        &self.address
    }

    /// The head of each request so far, in their order.
    pub fn asked(&self) -> Vec<String> {
        self.heads.lock().unwrap().clone()
    }

    /// The target of each request so far.
    pub fn targets(&self) -> Vec<String> {
        self.asked().iter().map(|head| head.split_whitespace().nth(1).unwrap_or_default().to_string()).collect()
    }
}

#[test]
fn a_stand_in_answers_by_its_table_and_remembers() {
    let stand_in = StandIn::table(vec![("/a".to_string(), "200 OK".to_string(), String::new(), b"yes".to_vec())]);
    let client = plumbing::HttpClient::new();
    let timeout = std::time::Duration::from_secs(5);
    let said = client.ask("GET", &format!("{}/a/b", stand_in.address()), &[], b"", timeout).unwrap().text(100).unwrap();
    assert_eq!(said, b"yes");
    assert!(client.ask("GET", &format!("{}/z", stand_in.address()), &[], b"", timeout).is_err());
    assert_eq!(stand_in.targets(), ["/a/b", "/z"]);
}

#[test]
fn a_hand_clock_stands_until_it_is_moved() {
    let clock = HandClock::at(100);
    assert_eq!(clock.epoch(), 100.0);
    clock.pass(5);
    assert_eq!(clock.epoch(), 105.0);
    clock.each_look_takes(1);
    assert_eq!((clock.epoch(), clock.epoch()), (105.0, 106.0));
}

#[test]
fn an_app_lives_in_its_folder_and_is_told_the_hub() {
    let folder = TestFolder::new("rig");
    let real = TestApp::over(&folder.path, &[]);
    assert_eq!(real.hub(), "https://huggingface.co");
    assert!(real.models_dir().starts_with(&folder.path));
    let told = TestApp::over(&folder.path, &[("CARAVAN_HUB_URL", "http://127.0.0.1:9/")]);
    assert_eq!(told.hub(), "http://127.0.0.1:9");
}
