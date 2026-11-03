//! One file from the controller to this disk: its tries, its progress, the pages it leaves. The copying part of `ModelFetcher`.

use crate::errors::AppError;
use crate::http_client::{HttpAnswer, HttpError};
use crate::log::Log;
use crate::models::fetcher::{Fetch, ModelFetcher, RoomMaker};
use crate::models::pace::{CopyPace, RetryDelays, WrittenPages};
use os::Disk;
use serde_json::{Map, Value, json};
use std::fs;
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use wire::Percent;

impl ModelFetcher {
    const TRANSIENT: [&'static str; 7] = [
        "connection refused",
        "connection reset",
        "timed out",
        "temporarily unavailable",
        "incomplete download",
        "errno 111",
        "errno 104",
    ];
    const CHUNK: usize = 1 << 20;
    const PROGRESS_STEP: i64 = 32 << 20;
    const DOWNLOAD_TIMEOUT: std::time::Duration = std::time::Duration::from_secs(3600);

    /// What the machine still needs to write once a copy is in: its logs, a cell's own files. Bytes.
    pub(super) const LEFT_FREE: u64 = 2 << 30;
    const GIB: f64 = (1u64 << 30) as f64;

    /// Who makes room when a copy would not fit: told once, for the keeper stands after the fetcher it keeps.
    pub fn room_comes_from(&self, maker: RoomMaker) {
        // A second maker has nothing to add: the first stays.
        drop(self.room_maker.set(maker));
    }

    /// (what the copy here weighs, what the controller's file weighs) when the two differ: a file of another size is another file, as it is for reading in place (`in_place`). `None` for a copy
    /// that is not there, and for a hint that says no size: it says nothing to differ from.
    pub(super) fn copy_differs(&self, local: &Path, hint: Option<&Value>) -> Option<(u64, u64)> {
        let there = hint
            .filter(|hint| hint.is_object())
            .and_then(|hint| hint.get("size"))
            .and_then(Value::as_u64)
            .filter(|size| *size != 0)?;
        let here = fs::metadata(local).ok().filter(fs::Metadata::is_file)?.len();
        (here != there).then_some((here, there))
    }

    /// What the cache's disk has free, for a folder that may not be made yet; `None` when the system does not say.
    pub(super) fn disk_free(&self) -> Option<u64> {
        let cache = self.cache_dir();
        let probe = cache.ancestors().find(|folder| folder.exists()).unwrap_or(&cache);
        Disk::usage(probe).map(|(_, free)| free)
    }

    /// Whether a copy of `total` bytes fits, and why not. The keeper makes room when it is short — on the disk, and on a shelf of a size within its budget: a disk that fills up mid-copy kills the start
    /// after minutes of copying, and the machine's logs with it (2026-10-18). A length nobody said and a disk that does not say are not refused: nothing is known against them.
    fn room_for(&self, total: u64, label: &str) -> Result<(), String> {
        if total == 0 {
            return Ok(());
        }
        if let Some(make) = self.room_maker.get() {
            return make(total, label);
        }
        // No keeper stands yet: the disk alone answers.
        match self.disk_free().filter(|free| *free < total.saturating_add(Self::LEFT_FREE)) {
            Some(free) => Err(self.no_room_words(label, total, free)),
            None => Ok(()),
        }
    }

    /// The words of a copy the disk has no room for, with every copy no cell is using gone.
    pub(super) fn no_room_words(&self, label: &str, total: u64, free: u64) -> String {
        format!(
            "no room for {label}: it takes {:.1} GB and {} has {:.1} GB free, with every copy no cell is using gone. Nothing was copied. {}",
            total as f64 / Self::GIB,
            self.cache_dir().display(),
            free as f64 / Self::GIB,
            self.shelf.when_full
        )
    }

    /// The model and its other files, with progress for all of them: (the model, the projector, the draft), "" for one not asked.
    pub fn download_all(
        &self,
        model: &str,
        projector: &str,
        draft: &str,
        use_cache: bool,
        port: i64,
        hints: Option<&Value>,
    ) -> Result<(String, String, String), AppError> {
        let files: Vec<&str> = [model, projector, draft].into_iter().filter(|raw| !raw.is_empty()).collect();
        let count = files.len();
        let mut results = Vec::with_capacity(count);
        for (at, raw) in files.iter().enumerate() {
            let short = Path::new(raw).file_name().map_or_else(String::new, |name| name.to_string_lossy().into_owned());
            let label = if count > 1 { format!("{short} ({}/{count})", at + 1) } else { short };
            let hint = hints.filter(|hints| hints.is_object()).and_then(|hints| hints.get(*raw)).cloned();
            results.push(self.ensure(raw, &Fetch { report: true, label, use_cache, port, hint })?.display().to_string());
        }
        let mut rest = results.into_iter();
        let first = rest.next().ok_or_else(|| AppError::new("no model to fetch"))?;
        // absent-ok: a file not asked for is "", as the caller reads it.
        let second = if projector.is_empty() { String::new() } else { rest.next().unwrap_or_default() };
        // absent-ok: as above.
        let third = if draft.is_empty() { String::new() } else { rest.next().unwrap_or_default() };
        Ok((first, second, third))
    }

    /// One file from the controller into `local`, through `temporary`. `record`: written down as this scout's download: a folder's files are not, the folder is.
    pub(super) fn download(
        &self,
        raw: &str,
        local: &Path,
        temporary: &Path,
        label: &str,
        fetch: &Fetch,
        record: bool,
    ) -> Result<PathBuf, AppError> {
        let url = format!("{}/api/models/download?path={}", self.controller(raw)?, Percent::encode_path(raw));
        self.flying(temporary, true);
        let done = self.fetched(&url, local, temporary, label, fetch, record);
        self.flying(temporary, false);
        done
    }

    /// Transient errors, a controller restarting during a deploy, are tried again with a rest between.
    fn fetched(
        &self,
        url: &str,
        local: &Path,
        temporary: &Path,
        label: &str,
        fetch: &Fetch,
        record: bool,
    ) -> Result<PathBuf, AppError> {
        let tries = RetryDelays::ALL.len() + 1;
        let mut last = String::from("no attempts made");
        // What the file weighs, from the first answer: only this start's tries go on from what they left. A temporary file found from before may be of another file under the same name.
        let mut whole = 0;
        for attempt in 0..tries {
            if record {
                self.downloaded.add(temporary);
            }
            match self.copied(url, temporary, label, fetch, &mut whole) {
                Ok(done) => {
                    Log::line(&format!("[llama-node] download complete: {label} — {done} bytes"));
                    fs::rename(temporary, local)
                        .map_err(|error| AppError::with_status(format!("model download failed: {error}"), 500))?;
                    if record {
                        self.downloaded.add(local);
                        self.downloaded.forget(temporary);
                    }
                    return Ok(local.to_path_buf());
                }
                Err(words) => {
                    Log::line(&format!("[llama-node] download error (attempt {}/{tries}): {label} — {words}", attempt + 1));
                    let low = words.to_lowercase();
                    let transient = Self::TRANSIENT.iter().any(|word| low.contains(word));
                    let rest = RetryDelays::ALL.get(attempt).filter(|_| transient);
                    last = words;
                    let Some(rest) = rest else {
                        // What cannot be removed was never written.
                        drop(fs::remove_file(temporary));
                        if record {
                            self.downloaded.forget(temporary);
                        }
                        // The folders the start made for it, when nothing else lies in them: a copy refused before its first byte left three empty ones (2026-11-03).
                        Self::parents_left_empty(temporary, &self.cache_dir());
                        break;
                    };
                    self.say_the_next_try(label, attempt, &last, rest.as_secs(), fetch);
                    std::thread::sleep(*rest);
                }
            }
        }
        Err(AppError::with_status(format!("model download failed: {last}"), 500))
    }

    fn say_the_next_try(&self, label: &str, attempt: usize, why: &str, rest: u64, fetch: &Fetch) {
        Log::line(&format!("[llama-node] download transient error (attempt {}): {why} — retrying in {rest}s…", attempt + 1));
        if fetch.report {
            let mut said = Map::new();
            said.insert("downloadingFile".to_string(), json!(format!("{label} (retry {} in {rest}s…)", attempt + 1)));
            (self.report)(fetch.port, said);
        }
    }

    fn progress(&self, fetch: &Fetch, fields: Value) {
        if let (true, Value::Object(said)) = (fetch.report, fields) {
            (self.report)(fetch.port, said);
        }
    }

    /// The answer to one try, and how much of the file is here already: a try goes on from what the last one left, so that a controller restarted at 90 GB of a model does not send them again (2026-11-03).
    /// A controller that gives no parts, or a file that changed meanwhile, starts over.
    fn asked_from(&self, url: &str, temporary: &Path, whole: &mut u64) -> Result<(HttpAnswer, u64), String> {
        // absent-ok: what is not there has nothing to go on from.
        let have = if *whole == 0 { 0 } else { fs::metadata(temporary).map_or(0, |meta| meta.len()) };
        let mut fields = self.token_fields();
        if have != 0 {
            fields.push(("Range", format!("bytes={have}-")));
        }
        let answer = match self.http.ask("GET", url, &fields, &[], Self::DOWNLOAD_TIMEOUT) {
            Ok(answer) => answer,
            // Less there than here: another file now, and all of it is asked for again.
            Err(HttpError::Status(416, _)) if have != 0 => {
                *whole = 0;
                return Err("incomplete download: the file at the controller changed during its copy".to_string());
            }
            Err(error) => return Err(error.to_string()),
        };
        if answer.head.status != 206 {
            return Ok((answer, 0));
        }
        // absent-ok: a part that does not say which it is is taken for no part of this file.
        let said = answer.head.headers.get("Content-Range").unwrap_or_default();
        if have == 0 || !said.starts_with(&format!("bytes {have}-")) || !said.ends_with(&format!("/{whole}")) {
            *whole = 0;
            return Err("incomplete download: the file at the controller changed during its copy".to_string());
        }
        Ok((answer, have))
    }

    /// One try: the bytes read, or why not. A connection closed before all its bytes came is no copy: that is how a network's blip or a restart looks.
    fn copied(&self, url: &str, temporary: &Path, label: &str, fetch: &Fetch, whole: &mut u64) -> Result<u64, String> {
        let (answer, have) = self.asked_from(url, temporary, whole)?;
        // absent-ok: `int(Content-Length or 0)`: a copy of no said length has nothing to be short of.
        let coming: u64 = answer.head.headers.get("Content-Length").and_then(|said| said.trim().parse().ok()).unwrap_or(0);
        let total = if have == 0 { coming } else { *whole };
        *whole = total;
        self.room_for(coming, label)?;
        let opened = if have == 0 { fs::File::create(temporary) } else { fs::OpenOptions::new().append(true).open(temporary) };
        let mut file = opened.map_err(|error| error.to_string())?;
        let mut body = answer.body;
        let mut pace = CopyPace::default();
        let mut pages = WrittenPages::new(label);
        self.progress(fetch, json!({"phase": "downloading", "downloadedBytes": have, "totalBytes": total, "downloadingFile": label, "downloadBytesPerSec": null}));
        pace.add(have as i64, self.clock.monotonic());
        let (mut done, mut last_report) = (have, have);
        let mut chunk = vec![0u8; Self::CHUNK];
        loop {
            let count = match body.read(&mut chunk) {
                Ok(count) => count,
                // An answer that ends before the length it said is told from a whole one by the count below: its words are what a retry goes by.
                Err(error) if total != 0 && error.kind() == std::io::ErrorKind::UnexpectedEof => 0,
                Err(error) => return Err(error.to_string()),
            };
            if count == 0 {
                pages.drop_to(&file, done);
                break;
            }
            file.write_all(chunk.get(..count).unwrap_or_default()).map_err(|error| error.to_string())?;
            done += count as u64;
            pages.wrote(&file, done);
            pace.add(done as i64, self.clock.monotonic());
            if done - last_report >= Self::PROGRESS_STEP as u64 {
                last_report = done;
                self.progress(fetch, json!({"downloadedBytes": done, "downloadBytesPerSec": pace.rate()}));
            }
        }
        self.progress(fetch, json!({"downloadedBytes": done, "downloadBytesPerSec": pace.rate()}));
        if total != 0 && done != total {
            return Err(format!(
                "incomplete download: received {done} of {total} bytes ({:.1}%) — connection closed prematurely",
                done as f64 / total as f64 * 100.0
            ));
        }
        Ok(done)
    }
}
