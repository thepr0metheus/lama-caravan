//! What went wrong, kept for a while: the incident log.

use crate::app::App;
use files::AtomicFile;
use rules::request_kind::RequestKind;
use rules::{Coerce, PythonJson};
use serde_json::{Value, json};
use std::collections::BTreeSet;
use std::io::Write;
use std::sync::{Mutex, PoisonError};

/// What was logged by this process.
#[derive(Default)]
pub struct IncidentMemory {
    file: Mutex<()>,
    logged: Mutex<BTreeSet<String>>,
}

/// The log of this controller.
pub struct IncidentLog<'app> {
    app: &'app App,
}

impl<'app> IncidentLog<'app> {
    /// The log of `app`.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    /// True for "the client asked for a path this server does not have": no failure of anything.
    fn is_discovery_probe(method: Option<&Value>, path: Option<&Value>, status: Option<&Value>) -> bool {
        const ABSENT_PATH_STATUSES: [i64; 4] = [404, 405, 415, 501];
        let path = Coerce::stripped(path);
        if path.is_empty() {
            return false;
        }
        let Some(code) = status.and_then(Coerce::int) else {
            return false;
        };
        ABSENT_PATH_STATUSES.contains(&code) && !RequestKind::is_inference(&Coerce::text(method), &path)
    }

    fn cause(item: &Value, kind: &str) -> &'static str {
        match kind {
            "client_disconnected" => "Client closed the connection while proxy was still streaming the response.",
            "upstream_timeout" => "Proxy waited too long for llama.cpp upstream response.",
            "slow_first_byte" | "slow_request" => {
                // absent-ok: `int(item.get("chunks") or 0)`: no chunks said is none seen.
                let chunks = Coerce::whole(item.get("chunks"));
                let first_byte = Coerce::float_or_zero(item.get("firstByteMs"));
                if chunks <= 1 && first_byte >= 30000.0 {
                    "Likely queued or busy in llama.cpp prompt processing before first token."
                } else {
                    "Likely long prompt/context processing or overloaded shared llama.cpp server."
                }
            }
            _ => "Proxy or upstream returned an error.",
        }
    }

    /// The incident of one request; `None` for a request with nothing wrong.
    fn incident_for(item: &Value) -> Option<Value> {
        if !item.is_object() || Self::is_discovery_probe(item.get("method"), item.get("path"), item.get("status")) {
            return None;
        }
        let status = item
            .get("status")
            .filter(|said| Coerce::truthy(Some(*said)))
            .map_or_else(String::new, |said| Coerce::str_of(Some(said)));
        let label = {
            let said = Coerce::text(item.get("label"));
            if said.is_empty() { Coerce::text(item.get("route")) } else { said }
        };
        let title = if label.is_empty() { "route".to_string() } else { label };
        let first_byte = Coerce::float_or_zero(item.get("firstByteMs"));
        let duration = item
            .get("durationMs")
            .filter(|said| Coerce::truthy(Some(*said)))
            .or_else(|| item.get("elapsedMs"))
            .and_then(Coerce::float)
            // absent-ok: a figure not said is none.
            .unwrap_or(0.0);
        let chunks = item.get("chunks").filter(|said| Coerce::truthy(Some(*said))).cloned().unwrap_or_else(|| json!(0));
        let chunk_word = Coerce::str_of(Some(&chunks));
        let error = Coerce::text(item.get("error"));
        if !error.is_empty() || (!status.is_empty() && !status.starts_with('2') && status != "?") {
            let low = error.to_lowercase();
            let mut kind = Coerce::text(item.get("errorKind"));
            if kind.is_empty() && ["client disconnected", "broken pipe", "connection reset"].iter().any(|word| low.contains(word))
            {
                kind = "client_disconnected".to_string();
            }
            if kind.is_empty() && error.contains("timed out") {
                kind = "upstream_timeout".to_string();
            }
            let chain = Coerce::stripped(item.get("chain"));
            let said = if error.is_empty() { format!("status {status}") } else { error };
            let summary = if chain.is_empty() { said } else { format!("{said} — after {chain}") };
            let word = if kind == "client_disconnected" { "client disconnected" } else { "failed" };
            let named = if kind.is_empty() { "failed".to_string() } else { kind };
            return Some(
                json!({"kind": named, "title": format!("{title} {word}"), "summary": summary, "cause": Self::cause(item, &named)}),
            );
        }
        if first_byte >= 30000.0 {
            let seconds = (first_byte / 1000.0).round() as i64;
            return Some(
                json!({"kind": "slow_first_byte", "title": format!("{title} slow first byte"), "summary": format!("fb {seconds}s - {chunk_word} chunks"), "cause": Self::cause(item, "slow_first_byte")}),
            );
        }
        if duration >= 120_000.0 {
            let seconds = (duration / 1000.0).round() as i64;
            return Some(
                json!({"kind": "slow_request", "title": format!("{title} slow request"), "summary": format!("{seconds}s - {chunk_word} chunks"), "cause": Self::cause(item, "slow_request")}),
            );
        }
        None
    }

    fn key_of(item: &Value, incident: &Value) -> String {
        let word = |raw: Option<&Value>| {
            raw.filter(|said| Coerce::truthy(Some(*said))).map_or_else(String::new, |said| Coerce::str_of(Some(said)))
        };
        let request = item
            .get("id")
            .filter(|said| Coerce::truthy(Some(*said)))
            .or_else(|| item.get("requestId"))
            .filter(|said| Coerce::truthy(Some(*said)));
        match request {
            Some(id) => [word(Some(id)), word(incident.get("kind")), word(item.get("label"))].join(":"),
            None => [word(incident.get("kind")), word(item.get("label")), word(item.get("startedAt"))].join(":"),
        }
    }

    fn record(&self, item: &Value, incident: &Value) -> Value {
        let model = item.get("request").filter(|request| request.is_object()).and_then(|request| request.get("model"));
        json!({
            "time": self.app.now_whole(), "key": Self::key_of(item, incident), "kind": incident.get("kind"), "title": incident.get("title"),
            "summary": incident.get("summary"), "label": item.get("label"), "port": item.get("port"), "upstreamHost": item.get("upstreamHost"),
            "upstreamPort": item.get("upstreamPort"), "exit": item.get("exit").filter(|said| Coerce::truthy(Some(*said))).cloned().unwrap_or_else(|| json!("")),
            "client": item.get("client"), "method": item.get("method"), "path": item.get("path"), "status": item.get("status"), "error": item.get("error"),
            "errorKind": item.get("errorKind"), "chain": item.get("chain"), "cause": incident.get("cause"), "startedAt": item.get("startedAt"),
            "finishedAt": item.get("finishedAt"), "durationMs": item.get("durationMs"), "elapsedMs": item.get("elapsedMs"), "firstByteMs": item.get("firstByteMs"),
            "chunks": item.get("chunks"), "bytes": item.get("bytes"), "requestId": item.get("id"), "correlation": item.get("correlation"), "model": model,
        })
    }

    fn moment(row: &Value) -> f64 {
        let said =
            ["time", "finishedAt", "startedAt"].iter().filter_map(|key| row.get(*key)).find(|said| Coerce::truthy(Some(*said)));
        // absent-ok: a figure not said is none.
        said.and_then(Coerce::float).unwrap_or(0.0)
    }

    /// The incidents kept, the newest first.
    pub fn load(&self, limit: usize) -> Vec<Value> {
        let path = &self.app.paths.incident_log_file;
        let Ok(text) = std::fs::read_to_string(path) else {
            return Vec::new();
        };
        let cutoff = self.app.now() - self.app.paths.incident_retention_seconds as f64;
        let mut rows = Vec::new();
        for line in text.lines().filter(|line| !line.trim().is_empty()) {
            let Ok(row) = serde_json::from_str::<Value>(line) else {
                return Vec::new();
            };
            if row.get("kind").and_then(Value::as_str) == Some("fallback_active")
                || Self::is_discovery_probe(row.get("method"), row.get("path"), row.get("status"))
            {
                continue;
            }
            if Coerce::float_or_zero(row.get("time")) >= cutoff {
                rows.push(row);
            }
        }
        rows.sort_by(|left, right| Self::moment(right).total_cmp(&Self::moment(left)));
        rows.truncate(limit);
        rows
    }

    fn trim(&self) {
        let cutoff = self.app.now() - self.app.paths.incident_retention_seconds as f64;
        let mut rows: Vec<Value> =
            self.load(10000).into_iter().filter(|row| Coerce::float_or_zero(row.get("time")) >= cutoff).collect();
        rows.sort_by(|left, right| Self::moment(left).total_cmp(&Self::moment(right)));
        let text: String = rows.iter().map(|row| format!("{}\n", PythonJson::compact(row))).collect();
        // A log that was not trimmed is trimmed on the next incident.
        drop(AtomicFile::write(&self.app.paths.incident_log_file, text.as_bytes()));
    }

    /// The incidents of a sample's requests appended, each once.
    pub fn append_from(&self, sample: &Value) {
        let correlated = sample.get("correlatedActivity");
        let list = |key: &str| correlated.and_then(|said| said.get(key)).and_then(Value::as_array).into_iter().flatten();
        let mut records = Vec::new();
        {
            let mut logged = self.app.incidents.logged.lock().unwrap_or_else(PoisonError::into_inner);
            for item in list("activeRequests").chain(list("recentRequests")) {
                let Some(incident) = Self::incident_for(item) else {
                    continue;
                };
                if logged.insert(Self::key_of(item, &incident)) {
                    records.push(self.record(item, &incident));
                }
            }
        }
        if records.is_empty() {
            return;
        }
        let _held = self.app.incidents.file.lock().unwrap_or_else(PoisonError::into_inner);
        let existing: BTreeSet<String> = self.load(10000).iter().map(|row| Coerce::text(row.get("key"))).collect();
        records.retain(|row| !existing.contains(&Coerce::text(row.get("key"))));
        if records.is_empty() {
            return;
        }
        let path = &self.app.paths.incident_log_file;
        if let Some(parent) = path.parent() {
            drop(std::fs::create_dir_all(parent));
        }
        let text: String = records.iter().map(|row| format!("{}\n", PythonJson::compact(row))).collect();
        let written =
            std::fs::OpenOptions::new().create(true).append(true).open(path).and_then(|mut file| file.write_all(text.as_bytes()));
        if written.is_ok() {
            self.trim();
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn an_absent_path_is_no_incident() {
        assert!(IncidentLog::incident_for(&json!({"method": "GET", "path": "/props", "status": 404})).is_none());
        let failed =
            IncidentLog::incident_for(&json!({"method": "POST", "path": "/v1/chat/completions", "status": 404, "label": "L"}))
                .unwrap();
        assert_eq!(failed["kind"], "failed");
        assert_eq!(failed["title"], "L failed");
        assert_eq!(failed["summary"], "status 404");
    }

    #[test]
    fn a_failure_says_what_it_was() {
        let gone = IncidentLog::incident_for(&json!({"error": "Broken pipe", "chain": "a"})).unwrap();
        assert_eq!(gone["kind"], "client_disconnected");
        assert_eq!(gone["title"], "route client disconnected");
        assert_eq!(gone["summary"], "Broken pipe — after a");
        let timeout = IncidentLog::incident_for(&json!({"error": "timed out"})).unwrap();
        assert_eq!(timeout["kind"], "upstream_timeout");
        assert!(IncidentLog::incident_for(&json!({"status": 200})).is_none());
    }

    #[test]
    fn slowness_is_an_incident() {
        let slow = IncidentLog::incident_for(&json!({"status": 200, "firstByteMs": 31000, "chunks": 1})).unwrap();
        assert_eq!(slow["kind"], "slow_first_byte");
        assert_eq!(slow["summary"], "fb 31s - 1 chunks");
        assert!(slow["cause"].as_str().unwrap().starts_with("Likely queued"));
        let long = IncidentLog::incident_for(&json!({"status": 200, "durationMs": 120000})).unwrap();
        assert_eq!(long["kind"], "slow_request");
    }

    #[test]
    fn a_key_is_the_request_s_or_its_moment_s() {
        let incident = json!({"kind": "failed"});
        assert_eq!(IncidentLog::key_of(&json!({"id": "a", "label": "L"}), &incident), "a:failed:L");
        assert_eq!(IncidentLog::key_of(&json!({"label": "L", "startedAt": 5}), &incident), "failed:L:5");
    }
}
