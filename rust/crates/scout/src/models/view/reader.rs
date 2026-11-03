//! Bytes of the controller's files, read as a program asks for them: a window of a file on one connection, so that a program reading a file through asks the controller now and then and not at every read.

use crate::config::ScoutConfig;
use crate::http_client::HttpClient;
use crate::log::Log;
use rules::AppError;
use std::io::{self, Read};
use std::sync::{Arc, Mutex, PoisonError};
use std::time::Duration;
use wire::Percent;

/// Where the view's bytes come from: the controller here, a table in a test.
pub trait ViewBytes: Send + Sync {
    /// `size` bytes of `rel` from `offset`, fewer only where the file of `total` bytes ends. Several threads ask at once.
    fn read_at(&self, rel: &str, offset: u64, size: u32, total: u64) -> io::Result<Vec<u8>>;
}

/// The controller's files, as a scout may ask for them.
pub struct ControllerFiles {
    config: Arc<ScoutConfig>,
    http: Arc<HttpClient>,
}

impl ControllerFiles {
    /// How long one read may wait: for the connection, and for each read after it. A controller that restarts answers again within it.
    const TIMEOUT: Duration = Duration::from_secs(30);

    /// The files of this scout's controller.
    pub fn new(config: Arc<ScoutConfig>, http: Arc<HttpClient>) -> Self {
        Self { config, http }
    }

    fn url(&self, rel: &str) -> Option<String> {
        let controller = self.config.text("controllerUrl");
        let controller = controller.trim_end_matches('/');
        (!controller.is_empty()).then(|| format!("{controller}/api/models/download?path={}", Percent::encode_path(rel)))
    }

    fn fields(&self, range: String) -> Vec<(&'static str, String)> {
        let token = self.config.token();
        let mut fields = vec![("Range", range)];
        if !token.is_empty() {
            fields.push(("X-Caravan-Token", token));
        }
        fields
    }

    /// What `rel` weighs, as the controller says of its first byte.
    pub fn size_of(&self, rel: &str) -> Result<u64, AppError> {
        let url = self
            .url(rel)
            .ok_or_else(|| AppError::with_status(format!("model not found locally and controllerUrl not set: {rel}"), 404))?;
        let answer = self.http.answer("GET", &url, &self.fields("bytes=0-0".to_string()), &[], Self::TIMEOUT);
        let answer =
            answer.map_err(|error| AppError::with_status(format!("the controller does not answer for {rel}: {error}"), 502))?;
        let whole = answer
            .head
            .headers
            .get("Content-Range")
            .and_then(|said| said.rsplit('/').next().and_then(|total| total.trim().parse().ok()));
        match (whole, answer.head.status) {
            (Some(total), _) => Ok(total),
            (None, 404) => Err(AppError::with_status(format!("the controller has no {rel}"), 404)),
            (None, status) => {
                Err(AppError::with_status(format!("the controller does not give parts of {rel} (HTTP {status}): update it"), 502))
            }
        }
    }

    /// An open read of `rel` from `from` up to `to`, the last byte not included.
    fn window(&self, rel: &str, from: u64, to: u64) -> io::Result<Box<dyn Read + Send>> {
        let url = self.url(rel).ok_or_else(|| io::Error::new(io::ErrorKind::NotConnected, "no controller"))?;
        let answer = self
            .http
            .answer("GET", &url, &self.fields(format!("bytes={from}-{}", to.saturating_sub(1))), &[], Self::TIMEOUT)
            .map_err(|error| io::Error::other(error.to_string()))?;
        if answer.head.status != 206 {
            return Err(io::Error::other(format!("HTTP {} for a part of {rel}", answer.head.status)));
        }
        Ok(Box::new(answer.body))
    }
}

/// A read that goes on: where it stands and where it ends.
struct Window {
    rel: String,
    at: u64,
    end: u64,
    body: Box<dyn Read + Send>,
}

/// The session's reader of the controller.
pub struct ControllerReader {
    files: Arc<ControllerFiles>,
    /// The windows nobody reads from now, the longest unused first. One that is read from is out of the list, and the lock is not held over the network.
    open: Mutex<Vec<Window>>,
    rests: Vec<Duration>,
}

impl ControllerReader {
    /// How much one request asks for. A long read through a proxy holds its buffers and its temporary file, and one that pauses while a card takes what it read gets cut: a window ends soon by itself.
    /// A program that reads many places at once leaves most of each window unread, and the proxy has read it all the same.
    const WINDOW: u64 = 16 << 20;
    /// How far ahead a read is taken from the window it is in, the bytes between read and dropped: a new request costs more than this.
    const SKIP_MOST: u64 = 4 << 20;
    /// Reads kept open at once: a model's parts, its projector, and each thread of a program that copies one file by many threads: seamless at 26, whose reads through 4 windows opened a connection
    /// nearly each and went at 9 MB/s (2026-11-03).
    const MOST_OPEN: usize = 32;
    /// The rests between tries: a controller restarting during a deploy is back within them, and a program's read waits for it.
    const RESTS: [Duration; 5] = [
        Duration::from_secs(1),
        Duration::from_secs(2),
        Duration::from_secs(5),
        Duration::from_secs(10),
        Duration::from_secs(20),
    ];

    /// A reader of these files.
    pub fn new(files: Arc<ControllerFiles>) -> Self {
        Self::resting(files, Self::RESTS.to_vec())
    }

    /// The same with these rests between tries.
    pub fn resting(files: Arc<ControllerFiles>, rests: Vec<Duration>) -> Self {
        Self { files, open: Mutex::new(Vec::new()), rests }
    }

    /// The window standing nearest before `at`, taken out of the list.
    fn nearest(&self, rel: &str, at: u64) -> Option<Window> {
        let mut open = self.open.lock().unwrap_or_else(PoisonError::into_inner);
        let near = |window: &Window| window.rel == rel && window.at <= at && at - window.at <= Self::SKIP_MOST && at < window.end;
        let place = (0..open.len()).filter(|place| open.get(*place).is_some_and(near)).min_by_key(|place| {
            // absent-ok: the filter above has seen this place.
            at - open.get(*place).map_or(0, |window| window.at)
        })?;
        Some(open.remove(place))
    }

    /// The window standing at `at`: one near it read up to there, or a new one when none is near.
    fn window_at(&self, rel: &str, at: u64, total: u64) -> io::Result<Window> {
        if let Some(mut window) = self.nearest(rel, at) {
            let skip = at - window.at;
            let dropped = io::copy(&mut (&mut window.body).take(skip), &mut io::sink())?;
            if dropped != skip {
                return Err(io::Error::new(io::ErrorKind::UnexpectedEof, "a window ended before its length"));
            }
            window.at = at;
            return Ok(window);
        }
        let end = at.saturating_add(Self::WINDOW).min(total);
        Ok(Window { rel: rel.to_string(), at, end, body: self.files.window(rel, at, end)? })
    }

    /// A window that goes on, back on the list for the next read.
    fn put_back(&self, window: Window) {
        let mut open = self.open.lock().unwrap_or_else(PoisonError::into_inner);
        open.push(window);
        if open.len() > Self::MOST_OPEN {
            open.remove(0);
        }
    }

    /// One try at the bytes. What stands open and whole goes back on the list.
    fn tried(&self, rel: &str, offset: u64, want: u64, total: u64) -> io::Result<Vec<u8>> {
        let mut out = Vec::new();
        while (out.len() as u64) < want {
            let at = offset + out.len() as u64;
            let mut window = self.window_at(rel, at, total)?;
            let here = (want - out.len() as u64).min(window.end - window.at);
            let read = (&mut window.body).take(here).read_to_end(&mut out)? as u64;
            if read != here {
                return Err(io::Error::new(io::ErrorKind::UnexpectedEof, "a window ended before its length"));
            }
            window.at += read;
            if window.at < window.end {
                self.put_back(window);
            }
        }
        Ok(out)
    }
}

impl ViewBytes for ControllerReader {
    fn read_at(&self, rel: &str, offset: u64, size: u32, total: u64) -> io::Result<Vec<u8>> {
        let want = u64::from(size).min(total.saturating_sub(offset));
        let mut rests = self.rests.clone().into_iter();
        loop {
            match self.tried(rel, offset, want, total) {
                Ok(bytes) => return Ok(bytes),
                Err(error) => {
                    self.open.lock().unwrap_or_else(PoisonError::into_inner).retain(|window| window.rel != rel);
                    let Some(rest) = rests.next() else {
                        Log::line(&format!("[llama-node] {rel}: no bytes from {offset} through the controller: {error}"));
                        return Err(error);
                    };
                    Log::line(&format!(
                        "[llama-node] {rel}: a read from {offset} failed ({error}) — asking again in {} s",
                        rest.as_secs()
                    ));
                    std::thread::sleep(rest);
                }
            }
        }
    }
}
