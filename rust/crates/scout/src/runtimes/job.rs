//! A long job the scout runs in the background, a `llama.cpp` build, a vLLM install, and the one record of how it goes.

use crate::errors::AppError;
use os::clock::Clock;
use serde_json::{Value, json};
use std::collections::BTreeMap;
use std::io::{BufReader, Read};
use std::process::{Command, Stdio};
use std::sync::{Arc, Mutex, MutexGuard, PoisonError};

/// A job's record: the job's own thread writes it under the lock, and the board reads it.
#[derive(Debug, Default)]
struct JobRecord {
    running: bool,
    started_at: i64,
    tag: String,
    lines: Vec<String>,
    done: bool,
    rc: Option<i64>,
    error: String,
}

/// One job at a time, its output kept in a ring. A second start while one runs is refused with `busy`, and the running job is left as it was.
pub struct BackgroundJob {
    thread_name: &'static str,
    busy: &'static str,
    clock: Arc<dyn Clock>,
    record: Arc<Mutex<JobRecord>>,
}

impl BackgroundJob {
    /// The ring: past this many lines the oldest `DROP_LINES` go.
    const KEEP_LINES: usize = 500;
    const DROP_LINES: usize = 100;
    /// How many of the last lines a status carries.
    const STATUS_LINES: usize = 200;

    /// A job not started yet.
    pub fn new(thread_name: &'static str, busy: &'static str, clock: Arc<dyn Clock>) -> Self {
        Self { thread_name, busy, clock, record: Arc::new(Mutex::new(JobRecord::default())) }
    }

    fn record_of(record: &Mutex<JobRecord>) -> MutexGuard<'_, JobRecord> {
        record.lock().unwrap_or_else(PoisonError::into_inner)
    }

    /// The whole status.
    pub fn status(&self) -> Value {
        let job = Self::record_of(&self.record);
        let (_, last) = job.lines.split_at(job.lines.len().saturating_sub(Self::STATUS_LINES));
        json!({"running": job.running, "startedAt": job.started_at, "tag": job.tag, "done": job.done, "rc": job.rc, "error": job.error, "lines": last})
    }

    /// What rides every heartbeat.
    pub fn status_slim(&self) -> Value {
        let job = Self::record_of(&self.record);
        json!({"running": job.running, "done": job.done, "rc": job.rc, "startedAt": job.started_at, "tag": job.tag, "lastLine": job.lines.last().map_or("", String::as_str)})
    }

    /// Runs `argv` in the background under `tag`, with exactly this environment; the status right away.
    pub fn start(&self, argv: Vec<String>, tag: &str, environment: BTreeMap<String, String>) -> Result<Value, AppError> {
        {
            let mut job = Self::record_of(&self.record);
            if job.running {
                return Err(AppError::with_status(self.busy, 409));
            }
            *job =
                JobRecord { running: true, started_at: self.clock.epoch() as i64, tag: tag.to_string(), ..JobRecord::default() };
        }
        let record = Arc::clone(&self.record);
        let started =
            std::thread::Builder::new().name(self.thread_name.to_string()).spawn(move || Self::run(&record, &argv, &environment));
        if let Err(error) = started {
            let mut job = Self::record_of(&self.record);
            *job = JobRecord { done: true, rc: Some(-1), error: error.to_string(), ..JobRecord::default() };
        }
        Ok(self.status())
    }

    fn run(record: &Mutex<JobRecord>, argv: &[String], environment: &BTreeMap<String, String>) {
        let (rc, error) = match Self::ran(record, argv, environment) {
            Ok(rc) => (rc, String::new()),
            Err(error) => (-1, error.to_string()),
        };
        let mut job = Self::record_of(record);
        job.running = false;
        job.done = true;
        job.rc = Some(rc);
        job.error = error;
    }

    fn ran(record: &Mutex<JobRecord>, argv: &[String], environment: &BTreeMap<String, String>) -> std::io::Result<i64> {
        let (program, args) = argv.split_first().ok_or_else(|| std::io::Error::other("no command"))?;
        let mut child = Command::new(program)
            .args(args)
            .env_clear()
            .envs(environment)
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()?;
        // Both streams in one record, as they come, as `stderr=STDOUT` has it.
        let error_side = child.stderr.take();
        let output_side = child.stdout.take();
        std::thread::scope(|scope| {
            if let Some(stream) = error_side {
                scope.spawn(move || Self::keep_lines(record, stream));
            }
            if let Some(stream) = output_side {
                Self::keep_lines(record, stream);
            }
        });
        let status = child.wait()?;
        use std::os::unix::process::ExitStatusExt;
        Ok(status.code().or_else(|| status.signal().map(|signal| -signal)).map_or(-1, i64::from))
    }

    /// Every line of a stream, its colours taken off. A progress bar's `\r` ends a line too, as Python's text mode has it.
    fn keep_lines(record: &Mutex<JobRecord>, stream: impl Read) {
        let mut reader = BufReader::new(stream);
        let mut line = Vec::new();
        let mut chunk = [0u8; 4096];
        while let Ok(count) = reader.read(&mut chunk) {
            if count == 0 {
                break;
            }
            for byte in chunk.iter().take(count) {
                if matches!(*byte, b'\n' | b'\r') {
                    Self::keep_line(record, &line);
                    line.clear();
                } else {
                    line.push(*byte);
                }
            }
        }
        if !line.is_empty() {
            Self::keep_line(record, &line);
        }
    }

    fn keep_line(record: &Mutex<JobRecord>, raw: &[u8]) {
        let text = String::from_utf8_lossy(raw);
        let clean = Self::without_colours(text.trim_end());
        let mut job = Self::record_of(record);
        job.lines.push(clean);
        if job.lines.len() > Self::KEEP_LINES {
            job.lines.drain(..Self::DROP_LINES);
        }
    }

    /// Colour codes only: an erase-line sequence stays as it came.
    fn without_colours(text: &str) -> String {
        let mut out = String::with_capacity(text.len());
        let mut rest = text;
        while let Some(at) = rest.find("\u{1b}[") {
            let (head, tail) = rest.split_at(at);
            out.push_str(head);
            let codes = tail.strip_prefix("\u{1b}[").unwrap_or(tail);
            let length = codes.find(|letter: char| !(letter.is_ascii_digit() || letter == ';')).unwrap_or(codes.len());
            let (_, after) = codes.split_at(length);
            if let Some(past) = after.strip_prefix('m') {
                rest = past;
            } else {
                out.push_str("\u{1b}[");
                rest = codes;
            }
        }
        out.push_str(rest);
        out
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use os::clock::SystemClock;

    #[test]
    fn colours_go_and_an_erase_line_stays() {
        assert_eq!(BackgroundJob::without_colours("\u{1b}[31mred\u{1b}[0m and \u{1b}[2Kerased"), "red and \u{1b}[2Kerased");
        assert_eq!(BackgroundJob::without_colours("plain"), "plain");
        assert_eq!(BackgroundJob::without_colours("\u{1b}["), "\u{1b}[");
    }

    #[test]
    fn a_job_says_what_it_printed_and_how_it_ended_and_refuses_a_second() {
        let job = BackgroundJob::new("test-job", "busy", Arc::new(SystemClock::new()));
        let argv = ["sh", "-c", "echo one; sleep 0.3; echo two >&2; exit 3"].map(str::to_string).to_vec();
        let environment: BTreeMap<String, String> = std::env::vars().collect();
        let started = job.start(argv.clone(), "tag", environment.clone()).unwrap();
        assert_eq!(started.get("running"), Some(&json!(true)));
        assert_eq!(job.start(argv, "tag", environment).err().map(|error| error.status), Some(409));
        for _ in 0..100 {
            if job.status().get("done") == Some(&json!(true)) {
                break;
            }
            std::thread::sleep(std::time::Duration::from_millis(50));
        }
        let status = job.status();
        assert_eq!(status.get("rc"), Some(&json!(3)));
        assert_eq!(status.get("lines"), Some(&json!(["one", "two"])));
        assert_eq!(job.status_slim().get("lastLine"), Some(&json!("two")));
    }

    #[test]
    fn a_command_that_cannot_start_says_so() {
        let job = BackgroundJob::new("test-job", "busy", Arc::new(SystemClock::new()));
        job.start(vec!["/no/such/program".to_string()], "t", BTreeMap::new()).unwrap();
        for _ in 0..100 {
            if job.status().get("done") == Some(&json!(true)) {
                break;
            }
            std::thread::sleep(std::time::Duration::from_millis(20));
        }
        let status = job.status();
        assert_eq!(status.get("rc"), Some(&json!(-1)));
        assert!(status.get("error").and_then(Value::as_str).is_some_and(|words| !words.is_empty()));
    }
}
