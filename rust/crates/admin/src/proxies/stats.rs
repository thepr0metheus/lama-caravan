//! Readers over the proxy's artifacts: its state file and its journal.

use crate::app::App;
use crate::cloud::spend::JournalDays;
use crate::common::entry::EntryDoor;
use os::LocalTime;
use regex::Regex;
use rules::{AppError, Coerce};
use serde_json::{Map, Value, json};
use std::collections::{BTreeMap, BTreeSet};
use std::io::{BufRead, BufReader, Seek, SeekFrom};
use std::sync::{Mutex, PoisonError};

mod logs;

/// One day of the journal, read once: today's file only for the bytes added since.
#[derive(Clone, Default)]
struct DaySeen {
    size: u64,
    ports: BTreeMap<i64, i64>,
    embeddings: i64,
}

/// What the journal's days said.
pub struct StatsMemory {
    seen: Mutex<BTreeMap<String, DaySeen>>,
    port: Regex,
    time: Regex,
    status: Regex,
    embed: Regex,
}

impl StatsMemory {
    /// The empty memory.
    pub fn new() -> Result<Self, regex::Error> {
        Ok(Self {
            seen: Mutex::new(BTreeMap::new()),
            port: Regex::new(r#""port":(\d+)"#)?,
            time: Regex::new(r#""time":(\d+)"#)?,
            status: Regex::new(r#""status":(\d{3})"#)?,
            embed: Regex::new(r#""path":"[^"]*/embeddings/?""#)?,
        })
    }

    fn first_number(pattern: &Regex, line: &str) -> Option<i64> {
        pattern.captures(line)?.get(1)?.as_str().parse().ok()
    }

    fn read_line(&self, line: &str, day: &mut DaySeen) {
        if !line.contains("\"event\":\"finished\"") {
            return;
        }
        let Some(when) = Self::first_number(&self.time, line) else {
            return;
        };
        if self.embed.is_match(line) && when > day.embeddings {
            day.embeddings = when;
        }
        let good = self.status.captures(line).and_then(|found| found.get(1)).is_some_and(|code| code.as_str().starts_with('2'));
        if !good {
            return;
        }
        if let Some(port) = Self::first_number(&self.port, line) {
            let seen = day.ports.entry(port).or_insert(0);
            *seen = (*seen).max(when);
        }
    }
}

/// The readers of this controller.
pub struct ProxyStats<'app> {
    app: &'app App,
}

impl<'app> ProxyStats<'app> {
    /// The readers of `app`.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    fn usage_tokens(item: &Value) -> i64 {
        let usage_of = |key: &str| {
            item.get(key).and_then(|part| part.get("usage")).filter(|usage| usage.is_object() && Coerce::truthy(Some(*usage)))
        };
        let usage = usage_of("response").or_else(|| usage_of("stream"));
        let at = |key: &str| usage.and_then(|usage| usage.get(key)).filter(|said| Coerce::truthy(Some(*said)));
        // absent-ok: `int(... or 0)`: a request that says no tokens counted none.
        at("total_tokens").or_else(|| at("totalTokens")).and_then(Coerce::int).unwrap_or(0)
    }

    fn item_exit(
        kind: Option<&Value>,
        provider: Option<&Value>,
        host: Option<&Value>,
        port: Option<&Value>,
        upstream: &str,
    ) -> String {
        let kind = kind.and_then(Value::as_str);
        if kind == Some("cloud") {
            let block = Coerce::stripped(provider);
            return if block.is_empty() { String::new() } else { format!("☁ {block}") };
        }
        if matches!(kind, Some("llama" | "engine")) && Coerce::truthy(host) && Coerce::truthy(port) {
            return format!("{}:{}", Coerce::str_of(host), Coerce::str_of(port));
        }
        if kind == Some("machine") && upstream.contains('/') {
            return upstream.to_string();
        }
        String::new()
    }

    /// The host and the port an item says, or what its upstream's address says for the ones it does not.
    fn upstream_place(host: Option<&Value>, port: Option<&Value>, upstream: &str) -> (Option<Value>, Option<Value>) {
        let (mut host, mut port) = (host.cloned(), port.cloned());
        if !upstream.is_empty() && (host.is_none() || port.is_none()) {
            let bare = upstream.strip_prefix("http://").or_else(|| upstream.strip_prefix("https://")).unwrap_or(upstream);
            let host_port = bare.split('/').next().unwrap_or(bare);
            if let Some((name, number)) = host_port.rsplit_once(':') {
                host = Some(json!(name));
                if let Ok(number) = number.parse::<i64>() {
                    port = Some(json!(number));
                }
            }
        }
        (host, port)
    }

    /// One request of the proxy's state, as the board's monitor shows it.
    pub fn summarize_item(label: &str, row: &Value, item: &Value, state: &str) -> Value {
        let said = |key: &str| item.get(key).filter(|value| Coerce::truthy(Some(*value)));
        let either = |key: &str| said(key).or_else(|| row.get(key).filter(|value| Coerce::truthy(Some(*value))));
        let port = either("port");
        let upstream = either("upstream").cloned().unwrap_or_else(|| json!(""));
        let upstream_text = Coerce::str_of(Some(&upstream));
        let (host, upstream_port) = Self::upstream_place(said("upstreamHost"), said("upstreamPort"), &upstream_text);
        let duration = said("durationMs").or_else(|| said("elapsedMs"));
        let elapsed = said("elapsedMs").or_else(|| said("durationMs"));
        let object = |key: &str| item.get(key).filter(|value| value.is_object()).cloned().unwrap_or_else(|| json!({}));
        let word = |key: &str, otherwise: Value| said(key).cloned().unwrap_or(otherwise);
        let id = said("id").cloned().unwrap_or_else(|| {
            let moment = said("startedAt").or_else(|| said("finishedAt")).map_or_else(String::new, |at| Coerce::str_of(Some(at)));
            json!(format!("{label}:{}:{moment}", port.map_or_else(|| "None".to_string(), |port| Coerce::str_of(Some(port)))))
        });
        let kind = {
            let named = either("upstreamType").map_or_else(String::new, |said| Coerce::str_of(Some(said)));
            if named.is_empty() { "llama".to_string() } else { named }
        };
        json!({
            "id": id,
            "state": state,
            "label": label,
            "port": port,
            "upstream": upstream,
            "upstreamHost": host.filter(|said| Coerce::truthy(Some(said))).unwrap_or_else(|| json!("127.0.0.1")),
            "upstreamPort": upstream_port.filter(|said| Coerce::truthy(Some(said))).unwrap_or_else(|| json!(8080)),
            "upstreamType": kind,
            "providerId": either("providerId").map_or_else(String::new, |said| Coerce::str_of(Some(said))),
            "exit": Self::item_exit(item.get("upstreamType"), item.get("providerId"), said("upstreamHost"), said("upstreamPort"), &upstream_text),
            "client": word("client", json!("")),
            "method": word("method", json!("POST")),
            "path": word("path", json!("")),
            "status": item.get("status"),
            "phase": word("phase", json!(state)),
            "startedAt": item.get("startedAt"),
            "finishedAt": item.get("finishedAt"),
            "durationMs": duration,
            "elapsedMs": elapsed,
            "bytes": word("bytes", json!(0)),
            "chunks": word("chunks", json!(0)),
            "firstByteMs": item.get("firstByteMs"),
            "request": object("request"),
            "response": object("response"),
            "stream": object("stream"),
            "error": word("error", json!("")),
            "usageTokens": Self::usage_tokens(item),
        })
    }

    /// The proxy's state as the admin hands it on: its routes without their keys.
    pub fn sample(&self) -> Value {
        let path = &self.app.paths.agent_proxy_state_file;
        if !path.exists() {
            return json!({"ok": false, "error": "agent proxy state missing", "agents": {}});
        }
        let read = std::fs::read(path)
            .map_err(|error| error.to_string())
            .and_then(|raw| serde_json::from_slice::<Value>(&raw).map_err(|error| error.to_string()));
        let mut payload = match read {
            Ok(payload) if payload.is_object() => payload,
            Ok(_) => return json!({"ok": false, "error": "'list' object does not support item assignment", "agents": {}}),
            Err(error) => return json!({"ok": false, "error": error, "agents": {}}),
        };
        Coerce::put(&mut payload, "ok", json!(true));
        if let Some(routes) = payload.get("routes").and_then(Value::as_array) {
            let public: Vec<Value> = routes.iter().filter(|route| route.is_object()).map(EntryDoor::public_route).collect();
            Coerce::put(&mut payload, "routes", Value::Array(public));
        }
        payload
    }

    fn day_seen(&self, day: &str) -> Option<DaySeen> {
        let path = JournalDays::file(self.app, day);
        let size = std::fs::metadata(&path).ok()?.len();
        let memory = &self.app.stats;
        let cached = memory.seen.lock().unwrap_or_else(PoisonError::into_inner).get(day).cloned();
        if let Some(cached) = cached.as_ref().filter(|cached| cached.size == size) {
            return Some(cached.clone());
        }
        // absent-ok: nothing kept for this day: it is read from its start.
        let mut seen = cached.unwrap_or_default();
        let start = if seen.size <= size { seen.size } else { 0 };
        if start == 0 {
            seen = DaySeen::default();
        }
        let mut file = std::fs::File::open(&path).ok()?;
        file.seek(SeekFrom::Start(start)).ok()?;
        for line in BufReader::new(file).split(b'\n') {
            memory.read_line(&String::from_utf8_lossy(&line.ok()?), &mut seen);
        }
        seen.size = size;
        memory.seen.lock().unwrap_or_else(PoisonError::into_inner).insert(day.to_string(), seen.clone());
        Some(seen)
    }

    /// When a client last asked for embeddings over recent days; 0 for not at all.
    pub fn embeddings_last_called(&self, days: i64) -> i64 {
        let days = days.max(1);
        let cutoff = self.app.now() - (days * 86400) as f64;
        let last = self
            .log_dates()
            .iter()
            .take(days as usize)
            .filter_map(|day| self.day_seen(day))
            .map(|day| day.embeddings)
            .max()
            // absent-ok: no days read is no call heard.
            .unwrap_or(0);
        if last as f64 >= cutoff { last } else { 0 }
    }

    /// `{proxy port: when it last answered well}`, over recent days.
    pub fn ports_last_seen(&self, days: i64) -> BTreeMap<i64, i64> {
        let days = days.max(1);
        let cutoff = self.app.now() - (days * 86400) as f64;
        let mut out: BTreeMap<i64, i64> = BTreeMap::new();
        for day in self.log_dates().iter().take(days as usize) {
            // absent-ok: a day with no journal saw no port.
            for (port, when) in self.day_seen(day).map(|seen| seen.ports).unwrap_or_default() {
                let seen = out.entry(port).or_insert(0);
                *seen = (*seen).max(when);
            }
        }
        out.retain(|_, when| *when as f64 >= cutoff);
        out
    }
}

/// What the journal's page asks for.
#[derive(Default)]
pub struct LogQuery {
    /// The day; the newest, when empty.
    pub date: String,
    /// How many rows, from the end.
    pub limit: String,
    /// Comma-separated events.
    pub event: String,
    /// One port.
    pub port: String,
    /// A part of a route's name.
    pub route: String,
    /// One client's address.
    pub client: String,
    /// Only the failures.
    pub errors: bool,
    /// Without what the state said beside each row.
    pub slim: bool,
    /// Counts per port in place of rows.
    pub summary: bool,
    /// The last minutes only.
    pub since: String,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn an_exit_is_named_by_what_it_reached() {
        let exit = |kind: &str, host: Option<Value>, port: Option<Value>, upstream: &str| {
            ProxyStats::item_exit(Some(&json!(kind)), Some(&json!(" pool ")), host.as_ref(), port.as_ref(), upstream)
        };
        assert_eq!(exit("cloud", None, None, ""), "☁ pool");
        assert_eq!(exit("llama", Some(json!("h")), Some(json!(1)), ""), "h:1");
        assert_eq!(exit("machine", None, None, "h/m"), "h/m");
        assert_eq!(exit("llama", None, None, ""), "");
    }

    #[test]
    fn a_request_has_one_shape_on_the_monitor() {
        let row = json!({"port": 9, "upstream": "http://h:7/v1", "upstreamType": "engine", "providerId": "p"});
        let shown =
            ProxyStats::summarize_item("l", &row, &json!({"id": "x", "response": {"usage": {"total_tokens": 5}}}), "active");
        assert_eq!(shown["upstreamHost"], "h");
        assert_eq!(shown["upstreamPort"], 7);
        assert_eq!(shown["upstreamType"], "engine");
        assert_eq!(shown["usageTokens"], 5);
        assert_eq!(shown["phase"], "active");
        let shown = ProxyStats::summarize_item("l", &json!({}), &json!({"startedAt": 3}), "done");
        assert_eq!(shown["id"], "l:None:3");
        assert_eq!(shown["upstreamHost"], "127.0.0.1");
        assert_eq!(shown["upstreamPort"], 8080);
    }

    #[test]
    fn a_journal_file_is_named_by_its_day() {
        assert!(ProxyStats::is_day("2026-11-01"));
        assert!(!ProxyStats::is_day("2026-1-01"));
        assert!(!ProxyStats::is_day("2026_11_01"));
    }
}
