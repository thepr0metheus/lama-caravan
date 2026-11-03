//! One day of the journal, as the page asks for it.

use super::*;
use std::collections::VecDeque;

/// What a page asks of a day's rows.
struct LogFilter<'asked> {
    /// The oldest moment asked for.
    cutoff: Option<f64>,
    events: BTreeSet<&'asked str>,
    port: Option<i64>,
    route_part: String,
    client: &'asked str,
    errors: bool,
}

impl LogFilter<'_> {
    fn keeps(&self, row: &Value) -> bool {
        let item_of = |key: &str| row.get("item").and_then(|item| item.get(key));
        // absent-ok: `r.get("time") or 0`: a row that names no moment is older than any cutoff.
        self.cutoff.is_none_or(|cutoff| Coerce::float_or_zero(row.get("time")) >= cutoff)
            && (self.events.is_empty()
                || row.get("event").and_then(Value::as_str).is_some_and(|event| self.events.contains(event)))
            && self.port.is_none_or(|port| item_of("port") == Some(&json!(port)))
            && (self.route_part.is_empty() || Coerce::str_of(row.get("route")).to_lowercase().contains(&self.route_part))
            && (self.client.is_empty() || item_of("client").and_then(Value::as_str) == Some(self.client))
            && (!self.errors
                || Coerce::truthy(item_of("error"))
                || Coerce::truthy(item_of("errorKind"))
                || Coerce::truthy(row.get("error")))
    }

    /// A row without the board's picture of its moment, or what the provider was sent.
    fn slim(row: &mut Value) {
        for key in ["active", "queue", "policy", "cloudMeta", "cloudHeaders"] {
            Coerce::take(row, key);
        }
    }
}

impl<'app> ProxyStats<'app> {
    pub(super) fn is_day(name: &str) -> bool {
        let bytes = name.as_bytes();
        bytes.len() == 10
            && bytes.iter().enumerate().all(|(at, byte)| if at == 4 || at == 7 { *byte == b'-' } else { byte.is_ascii_digit() })
    }

    /// The days the journal has, the newest first.
    pub fn log_dates(&self) -> Vec<String> {
        let Ok(names) = std::fs::read_dir(&self.app.paths.agent_proxy_log_dir) else {
            return Vec::new();
        };
        let mut days: Vec<String> = names
            .flatten()
            .filter_map(|entry| {
                let name = entry.file_name().to_string_lossy().into_owned();
                name.strip_suffix(".jsonl").filter(|day| Self::is_day(day)).map(str::to_string)
            })
            .collect();
        days.sort();
        days.reverse();
        days
    }

    pub(super) fn today(&self) -> String {
        LocalTime::of(self.app.now_whole()).map_or_else(String::new, |day| day.date())
    }

    /// The rows of a day that `filter` keeps, at most the newest `most`. Read one by one: a busy day is 127 000 rows, 1.3 GB as values all at once (the NAS, 2026-11-02), for the 200 a page shows.
    /// A line that does not read fails the whole day, as it says so. With no `most`, a row keeps what a summary reads of it, not the board's picture of its moment.
    fn kept_rows(&self, date: &str, filter: &LogFilter<'_>, most: Option<usize>) -> Result<VecDeque<Value>, AppError> {
        let path = JournalDays::file(self.app, date);
        let mut kept = VecDeque::new();
        if !path.exists() {
            return Ok(kept);
        }
        let failed = |error: String| AppError::with_status(format!("failed to read proxy log: {error}"), 500);
        let text = String::from_utf8(std::fs::read(&path).map_err(|error| failed(error.to_string()))?)
            .map_err(|error| failed(error.to_string()))?;
        for line in text.lines().filter(|line| !line.trim().is_empty()) {
            let mut row = serde_json::from_str::<Value>(line).map_err(|error| failed(error.to_string()))?;
            if !filter.keeps(&row) {
                continue;
            }
            if most.is_none() {
                LogFilter::slim(&mut row);
            }
            kept.push_back(row);
            if most.is_some_and(|most| kept.len() > most) {
                kept.pop_front();
            }
        }
        Ok(kept)
    }

    fn asked_number(word: &str, refusal: &str) -> Result<Option<i64>, AppError> {
        let word = Coerce::strip(word);
        if word.is_empty() {
            return Ok(None);
        }
        word.parse().map(Some).map_err(|_| AppError::new(refusal))
    }

    /// A filtered view over one day of the proxy's events.
    pub fn logs(&self, asked: &LogQuery) -> Result<Value, AppError> {
        let dates = self.log_dates();
        let date = {
            let said = Coerce::strip(&asked.date).to_string();
            if !said.is_empty() { said } else { dates.first().cloned().unwrap_or_else(|| self.today()) }
        };
        if !Self::is_day(&date) {
            return Err(AppError::new("invalid log date"));
        }
        // A limit that does not read asks for the default; a limit of 0 too, as `int(limit or 200)` does.
        let limit = Coerce::strip(&asked.limit).parse::<i64>().ok().filter(|limit| *limit != 0).unwrap_or(200).clamp(1, 2000);
        let port = Self::asked_number(&asked.port, "invalid port")?;
        // absent-ok: no `since` asks for the whole day.
        let since = Self::asked_number(&asked.since, "invalid since")?.unwrap_or(0).max(0);
        let filter = LogFilter {
            cutoff: (since != 0).then(|| self.app.now() - (since * 60) as f64),
            events: asked.event.split(',').map(Coerce::strip).filter(|word| !word.is_empty()).collect(),
            port,
            route_part: Coerce::strip(&asked.route).to_lowercase(),
            client: Coerce::strip(&asked.client),
            errors: asked.errors,
        };
        if asked.summary {
            let rows: Vec<Value> = self.kept_rows(&date, &filter, None)?.into();
            return Ok(json!({"date": date, "dates": dates, "summary": Self::logs_summary(&rows)}));
        }
        let mut rows: Vec<Value> = self.kept_rows(&date, &filter, Some(limit as usize))?.into();
        rows.reverse();
        if asked.slim {
            rows.iter_mut().for_each(LogFilter::slim);
        }
        Ok(json!({"date": date, "dates": dates, "rows": rows, "limit": limit}))
    }

    pub(super) fn logs_summary(rows: &[Value]) -> Value {
        let mut totals = Map::new();
        for row in rows {
            if !matches!(row.get("event").and_then(Value::as_str), Some("finished" | "blocked" | "client_disconnected_queued")) {
                continue;
            }
            let empty = json!({});
            let item = row.get("item").filter(|item| Coerce::truthy(Some(*item))).unwrap_or(&empty);
            let Some(port) = item.get("port").filter(|port| Coerce::truthy(Some(*port))) else {
                continue;
            };
            let entry = totals.entry(Coerce::str_of(Some(port))).or_insert_with(|| {
                json!({"port": port, "route": Coerce::str_of(row.get("route")).replace("None", ""), "total": 0, "errors": 0, "byKind": {}, "clients": {}})
            });
            Self::bump(entry, "total", 1);
            let caller = Coerce::stripped(item.get("client"));
            if !caller.is_empty()
                && let Some(clients) = entry.get_mut("clients")
            {
                Self::bump(clients, &caller, 1);
            }
            let kind = {
                let said = Coerce::stripped(item.get("errorKind"));
                if said.is_empty() { Coerce::stripped(item.get("reason")) } else { said }
            };
            if !kind.is_empty() || Coerce::truthy(item.get("error")) {
                Self::bump(entry, "errors", 1);
                if let Some(kinds) = entry.get_mut("byKind") {
                    Self::bump(kinds, if kind.is_empty() { "error" } else { &kind }, 1);
                }
            }
        }
        for entry in totals.values_mut() {
            let mut ranked: Vec<(String, i64)> = entry
                .get("clients")
                .and_then(Value::as_object)
                .into_iter()
                .flatten()
                // absent-ok: a count that is no number adds nothing.
                .map(|(name, count)| (name.clone(), count.as_i64().unwrap_or_default()))
                .collect();
            ranked.sort_by(|left, right| right.1.cmp(&left.1).then_with(|| left.0.cmp(&right.0)));
            Coerce::put(entry, "topClient", json!(ranked.first().map_or("", |row| row.0.as_str())));
            Coerce::put(entry, "clientCount", json!(ranked.len()));
        }
        Value::Object(totals)
    }

    pub(super) fn bump(row: &mut Value, key: &str, by: i64) {
        let held = Coerce::i64_or_zero(row.get(key));
        Coerce::put(row, key, json!(held + by));
    }

    /// Per-route request counts for a day (today, unless named).
    pub fn daily_stats(&self, date: &str) -> Value {
        let date = if date.is_empty() { self.today() } else { date.to_string() };
        let mut routes = Map::new();
        if let Ok(text) = std::fs::read_to_string(JournalDays::file(self.app, &date)) {
            for line in text.lines().filter(|line| !line.trim().is_empty()) {
                let Ok(row) = serde_json::from_str::<Value>(line) else {
                    continue;
                };
                let route =
                    row.get("route").filter(|route| Coerce::truthy(Some(*route))).map(|route| Coerce::str_of(Some(route)));
                let Some(route) = route else {
                    continue;
                };
                let counted = match row.get("event").and_then(Value::as_str) {
                    Some("received") => Some("total"),
                    Some("blocked") => {
                        let kind = Coerce::text(row.get("item").and_then(|item| item.get("errorKind")));
                        Some(if kind == "blocked" { "paused" } else { "failed" })
                    }
                    Some("finished") => {
                        let status = JournalDays::whole(Some(&row), "status");
                        let kind = Coerce::text(row.get("errorKind"));
                        (status >= 500 || matches!(kind.as_str(), "stopped" | "upstream_timeout" | "failed")).then_some("failed")
                    }
                    _ => None,
                };
                if let Some(counted) = counted {
                    let entry = routes.entry(route).or_insert_with(|| json!({"total": 0, "failed": 0, "paused": 0}));
                    Self::bump(entry, counted, 1);
                }
            }
        }
        json!({"date": date, "routes": routes})
    }
}
