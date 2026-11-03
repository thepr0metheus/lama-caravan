//! What this crate's tests stand on: a folder of a test's own, a clock in the test's hand, and an HTTP server that answers what the test says. Nothing here
//! reaches the network or the machine's real state.

#![allow(
    clippy::unwrap_used,
    clippy::panic,
    clippy::indexing_slicing,
    reason = "a helper of a test may stop where it found something wrong"
)]

use os::clock::Clock;
use std::io::{Read, Write};
use std::net::TcpListener;
use std::path::PathBuf;
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
        let path = std::env::temp_dir().join(format!("caravan-scout-{name}-{}", std::process::id()));
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

/// A clock in the test's hand: it stands where it was put.
#[derive(Debug, Default)]
pub struct HandClock {
    millis: AtomicU64,
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
}

impl Clock for HandClock {
    fn epoch(&self) -> f64 {
        self.millis.load(Ordering::SeqCst) as f64 / 1000.0
    }

    fn monotonic(&self) -> f64 {
        self.epoch()
    }

    fn thread_cpu(&self) -> Option<f64> {
        None
    }
}

/// An HTTP server that answers what the test says: one request on a connection, the answer's bytes as they are, and then it closes. So an answer can be cut
/// anywhere. It stands in for the controller.
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
                kept.lock().unwrap().push(head.clone());
                let bytes = answer(&head);
                drop(stream.write_all(&bytes));
            }
        });
        Self { address, heads }
    }

    /// A whole answer's bytes.
    pub fn answer(status: &str, body: &[u8]) -> Vec<u8> {
        let mut out = format!("HTTP/1.1 {status}\r\nContent-Length: {}\r\nConnection: close\r\n\r\n", body.len()).into_bytes();
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
