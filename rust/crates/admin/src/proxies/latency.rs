//! The caravan's own time per client, read from the proxy's journal.

use super::client_ids::FormerPorts;
use super::config::ProxiesConfig;
use crate::app::App;
use crate::cloud::spend::JournalDays;
use os::LocalTime;
use rules::Coerce;
use serde_json::{Value, json};
use std::collections::BTreeMap;
use std::io::{Read, Seek, SeekFrom};
use std::sync::{Mutex, PoisonError};

const METRICS: [&str; 5] = ["prepMs", "connectMs", "headersMs", "firstChunkMs", "cpuMs"];

/// One finish the proxy measured.
#[derive(Clone)]
struct Sample {
    time: f64,
    reused: Option<bool>,
    measures: [Option<f64>; 5],
}

/// A day's samples, each under its client's id: a row written before 2026-11-07 under the id its number became.
#[derive(Default)]
struct DayRead {
    offset: u64,
    samples: Vec<(String, Sample)>,
}

/// The days read so far.
#[derive(Default)]
pub struct LatencyMemory {
    days: Mutex<BTreeMap<String, DayRead>>,
}

/// Medians and 90th percentiles of one client's request timings.
pub struct ProxyLatencyDigest<'app> {
    app: &'app App,
}

impl<'app> ProxyLatencyDigest<'app> {
    /// The digest of `app`.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    fn sample_of(line: &[u8], former: &FormerPorts) -> Option<(String, Sample)> {
        let text = std::str::from_utf8(line).ok()?;
        if !text.contains("\"event\":\"finished\"") || !text.contains("\"latency\":") {
            return None;
        }
        let row: Value = serde_json::from_str(text).ok()?;
        let item = row.get("item").filter(|item| item.is_object())?;
        let latency = item.get("latency").filter(|latency| latency.is_object())?;
        if row.get("event").and_then(Value::as_str) != Some("finished") {
            return None;
        }
        let client = former.client_of(item)?;
        let measure = |key: &str| latency.get(key).filter(|said| said.is_number()).and_then(Value::as_f64);
        let sample = Sample {
            // absent-ok: `row.get("time") or 0`: a row with no moment is the oldest there is.
            time: Coerce::float_or_zero(row.get("time")),
            reused: latency.get("connReused").and_then(Value::as_bool),
            measures: METRICS.map(measure),
        };
        Some((client, sample))
    }

    fn read_day(&self, held: &mut BTreeMap<String, DayRead>, day: &str, former: &FormerPorts) {
        let path = JournalDays::file(self.app, day);
        let Ok(found) = std::fs::metadata(&path) else {
            held.remove(day);
            return;
        };
        let size = found.len();
        let read = held.entry(day.to_string()).or_default();
        if read.offset > size {
            *read = DayRead::default();
        }
        if read.offset == size {
            return;
        }
        let mut chunk = Vec::new();
        let done = std::fs::File::open(&path).and_then(|mut file| {
            file.seek(SeekFrom::Start(read.offset))?;
            file.take(size - read.offset).read_to_end(&mut chunk)
        });
        if done.is_err() {
            return;
        }
        // absent-ok: no line end in this chunk: the whole of it waits for the next read.
        let whole = chunk.iter().rposition(|byte| *byte == b'\n').map_or(0, |at| at + 1);
        let lines = chunk.get(..whole).unwrap_or_default().split(|byte| *byte == b'\n');
        read.samples.extend(lines.filter_map(|line| Self::sample_of(line, former)));
        read.offset += whole as u64;
    }

    fn samples(&self, route_id: &str, since: i64) -> Vec<Sample> {
        let former = FormerPorts::of(&ProxiesConfig::of(self.app).read_payload());
        let every_day = crate::proxies::stats::ProxyStats::of(self.app).log_dates();
        let first = if since != 0 { LocalTime::of(since).map_or_else(String::new, |day| day.date()) } else { String::new() };
        let mut held = self.app.latency.days.lock().unwrap_or_else(PoisonError::into_inner);
        held.retain(|day, _| every_day.contains(day));
        let days: Vec<&String> = every_day.iter().filter(|day| **day >= first).collect();
        for day in &days {
            self.read_day(&mut held, day, &former);
        }
        days.iter()
            .filter_map(|day| held.get(*day))
            .flat_map(|read| read.samples.iter())
            .filter(|(said, sample)| said == route_id && sample.time >= since as f64)
            .map(|(_, sample)| sample.clone())
            .collect()
    }

    /// `{n, p50, p90}` by nearest rank; `None` when nothing was measured.
    fn spread(mut values: Vec<f64>) -> Value {
        if values.is_empty() {
            return Value::Null;
        }
        values.sort_by(f64::total_cmp);
        let rank = |share: f64| {
            let at = (share * values.len() as f64).ceil() as usize;
            // absent-ok: no values: the summary of nothing is none.
            values.get(at.saturating_sub(1)).copied().unwrap_or_default()
        };
        json!({"n": values.len(), "p50": rank(0.5), "p90": rank(0.9)})
    }

    /// What the caravan's own time was for the client `route_id` over `range` (1h, 12h, 24h, else all).
    pub fn summary(&self, route_id: &str, range: &str) -> Value {
        let span = match range {
            "1h" => Some(3600),
            "12h" => Some(12 * 3600),
            "24h" => Some(24 * 3600),
            _ => None,
        };
        // absent-ok: a range of no span reads from the start.
        let since = span.map_or(0, |span| self.app.now() as i64 - span);
        let samples = self.samples(route_id, since);
        let mut out =
            json!({"routeId": route_id, "range": if span.is_some() { range } else { "all" }, "requests": samples.len()});
        for (at, key) in METRICS.iter().enumerate() {
            let values = samples.iter().filter_map(|sample| sample.measures.get(at).copied().flatten()).collect();
            Coerce::put(&mut out, key, Self::spread(values));
        }
        let pooled: Vec<bool> = samples.iter().filter_map(|sample| sample.reused).collect();
        let reused = pooled.iter().filter(|said| **said).count();
        Coerce::put(
            &mut out,
            "connReused",
            if pooled.is_empty() { Value::Null } else { json!({"n": pooled.len(), "reused": reused}) },
        );
        out
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_finish_with_no_measure_is_no_sample() {
        let former = FormerPorts::of(&json!({"formerPorts": {"1": "client-old"}}));
        let line = br#"{"event":"finished","time":5,"item":{"routeId":"client-a","latency":{"prepMs":2,"connReused":true,"cpuMs":"x"}}}"#;
        let (client, sample) = ProxyLatencyDigest::sample_of(line, &former).unwrap();
        assert_eq!(client, "client-a");
        let old = br#"{"event":"finished","time":5,"item":{"port":1,"latency":{"prepMs":2}}}"#;
        assert_eq!(ProxyLatencyDigest::sample_of(old, &former).unwrap().0, "client-old");
        assert_eq!(sample.reused, Some(true));
        assert_eq!(sample.measures[0], Some(2.0));
        assert_eq!(sample.measures[4], None);
        assert!(ProxyLatencyDigest::sample_of(br#"{"event":"finished","item":{"port":1}}"#, &former).is_none());
    }

    #[test]
    fn a_spread_takes_the_nearest_rank() {
        assert_eq!(ProxyLatencyDigest::spread(vec![]), Value::Null);
        assert_eq!(ProxyLatencyDigest::spread(vec![3.0, 1.0, 2.0, 4.0]), json!({"n": 4, "p50": 2.0, "p90": 4.0}));
    }
}
