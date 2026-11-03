//! What clients of the entry asked, over the journal's days. A day's file is read on from where the last reading
//! stopped, at a whole line: the journal can be tens of megabytes, and the board asks every few seconds.

use crate::app::App;
use os::LocalTime;
use rules::Coerce;
use serde_json::{Map, Value, json};
use std::collections::{BTreeMap, BTreeSet};
use std::io::{Read, Seek, SeekFrom};
use std::sync::{Mutex, PoisonError};

/// What a key has counted so far.
#[derive(Clone, Default)]
struct TallyLine {
    count: i64,
    last: i64,
    note: String,
}

/// How far a day's file was read, and what it held.
#[derive(Clone)]
struct DayRead<K> {
    offset: u64,
    lines: BTreeMap<K, TallyLine>,
}

impl<K> Default for DayRead<K> {
    fn default() -> Self {
        Self { offset: 0, lines: BTreeMap::new() }
    }
}

/// The counting of one kind of row.
trait TallyRule {
    /// What a row is counted under.
    type Key: Ord + Clone;

    /// `(key, when, note)` of a journal row that counts; `None` for one that does not.
    fn tally_of(row: &Value) -> Option<(Self::Key, i64, String)>;

    /// The port of a key.
    fn port_of(key: &Self::Key) -> i64;
}

/// Rows of the journal counted by a key over the last days.
struct JournalTally<R: TallyRule> {
    read: Mutex<BTreeMap<String, DayRead<R::Key>>>,
    days: i64,
}

impl<R: TallyRule> JournalTally<R> {
    fn new(days: i64) -> Self {
        Self { read: Mutex::new(BTreeMap::new()), days }
    }

    fn day(held: &mut BTreeMap<String, DayRead<R::Key>>, app: &App, day: &str) -> Option<DayRead<R::Key>> {
        let path = app.paths.agent_proxy_log_dir.join(format!("{day}.jsonl"));
        let Ok(found) = std::fs::metadata(&path) else {
            held.remove(day);
            return None;
        };
        let size = found.len();
        // absent-ok: a day not read yet has no ports seen.
        let mut seen = held.get(day).cloned().unwrap_or_default();
        if seen.offset > size {
            seen = DayRead::default();
        }
        if seen.offset < size {
            let mut chunk = Vec::new();
            let opened = std::fs::File::open(&path).and_then(|mut file| {
                file.seek(SeekFrom::Start(seen.offset))?;
                file.take(size - seen.offset).read_to_end(&mut chunk)
            });
            if opened.is_ok() {
                // absent-ok: no line end in this chunk: the whole of it waits for the next read.
                let whole = chunk.iter().rposition(|byte| *byte == b'\n').map_or(0, |at| at + 1);
                for line in chunk.get(..whole).unwrap_or_default().split(|byte| *byte == b'\n') {
                    let Ok(row) = serde_json::from_slice::<Value>(line) else {
                        continue;
                    };
                    let Some((key, when, note)) = R::tally_of(&row) else {
                        continue;
                    };
                    let was = seen.lines.entry(key).or_default();
                    was.note = if when >= was.last { note } else { std::mem::take(&mut was.note) };
                    was.count += 1;
                    was.last = was.last.max(when);
                }
                seen.offset += whole as u64;
            }
        }
        held.insert(day.to_string(), seen.clone());
        Some(seen)
    }

    /// `{key: line}` over the days; `None` when there is no journal at all, which says nothing of the clients.
    fn totals(&self, app: &App, ports: &BTreeSet<i64>) -> Option<BTreeMap<R::Key, TallyLine>> {
        if !app.paths.agent_proxy_log_dir.is_dir() {
            return None;
        }
        let now = app.now() as i64;
        let days: Vec<String> =
            (0..self.days).filter_map(|back| LocalTime::of(now - back * 86400).map(|day| day.date())).collect();
        let mut held = self.read.lock().unwrap_or_else(PoisonError::into_inner);
        held.retain(|day, _| days.contains(day));
        let mut total: BTreeMap<R::Key, TallyLine> = BTreeMap::new();
        for day in &days {
            let Some(seen) = Self::day(&mut held, app, day) else {
                continue;
            };
            for (key, line) in seen.lines {
                if !ports.contains(&R::port_of(&key)) {
                    continue;
                }
                match total.get_mut(&key) {
                    Some(was) if line.last >= was.last => {
                        *was = TallyLine { count: line.count + was.count, last: line.last, note: line.note };
                    }
                    Some(was) => was.count += line.count,
                    None => {
                        total.insert(key, line);
                    }
                }
            }
        }
        Some(total)
    }
}

/// The item of a row a client of the entry made: Routing's test of a client is the test's.
struct ClientRow;

impl ClientRow {
    /// Routing's test of a client, and what the journal's rows from before 1.3.582 call it.
    const PROBE_CLIENTS: [&'static str; 2] = ["routing-probe", "kanban-probe"];

    fn item(row: &Value) -> Option<Value> {
        let item = row.get("item").filter(|item| item.is_object()).cloned().unwrap_or_else(|| json!({}));
        let probe = item.get("client").and_then(Value::as_str).is_some_and(|client| Self::PROBE_CLIENTS.contains(&client));
        (row.is_object() && !probe).then_some(item)
    }
}

/// The errors each client was answered with.
struct MissRule;

impl TallyRule for MissRule {
    type Key = (i64, String, String, i64);

    fn tally_of(row: &Value) -> Option<(Self::Key, i64, String)> {
        let item = ClientRow::item(row)?;
        let status = match row.get("event").and_then(Value::as_str) {
            Some("blocked") => item.get("status"),
            Some("finished") => row.get("status").or_else(|| item.get("status")),
            _ => return None,
        };
        let (status, port) = (status.and_then(Coerce::int)?, item.get("port").and_then(Coerce::int)?);
        if status < 400 || port <= 0 {
            return None;
        }
        let reason = {
            let said = Coerce::text(item.get("reason"));
            if said.is_empty() { Coerce::text(row.get("errorKind")) } else { said }
        };
        // absent-ok: `int(row.get("time") or 0)`: a row that names no moment is the oldest there is.
        let when = Coerce::whole(row.get("time"));
        Some(((port, Coerce::text(item.get("method")), Coerce::text(item.get("path")), status), when, reason))
    }

    fn port_of(key: &Self::Key) -> i64 {
        key.0
    }
}

/// What each client called over the last three days.
struct CallRule;

impl TallyRule for CallRule {
    type Key = (i64, String);

    fn tally_of(row: &Value) -> Option<(Self::Key, i64, String)> {
        let item = ClientRow::item(row)?;
        if row.get("event").and_then(Value::as_str) != Some("finished") {
            return None;
        }
        let pool = Coerce::text(item.get("cloudPoolId"));
        let port = item.get("port").and_then(Coerce::int)?;
        if port <= 0 || pool.is_empty() {
            return None;
        }
        // absent-ok: `int(row.get("time") or 0)`: a row that names no moment is the oldest there is.
        let when = Coerce::whole(row.get("time"));
        Some(((port, pool), when, String::new()))
    }

    fn port_of(key: &Self::Key) -> i64 {
        key.0
    }
}

/// The two tallies of this controller.
pub struct ClientTallies {
    misses: JournalTally<MissRule>,
    calls: JournalTally<CallRule>,
}

impl Default for ClientTallies {
    fn default() -> Self {
        Self { misses: JournalTally::new(30), calls: JournalTally::new(3) }
    }
}

impl ClientTallies {
    const SHOWN: usize = 8;

    /// `{port: {items, more}}`: the errors each client was answered with; `None` with no journal.
    pub fn misses(&self, app: &App, ports: &[i64]) -> Option<BTreeMap<i64, Value>> {
        let wanted: BTreeSet<i64> = ports.iter().copied().collect();
        let total = self.misses.totals(app, &wanted)?;
        let mut out: BTreeMap<i64, Vec<(i64, String, Value)>> = wanted.iter().map(|port| (*port, Vec::new())).collect();
        for ((port, method, path, status), line) in total {
            let row = json!({"method": method, "path": path, "status": status, "count": line.count, "last": line.last, "reason": line.note});
            out.entry(port).or_default().push((line.last, path, row));
        }
        Some(
            out.into_iter()
                .map(|(port, mut lines)| {
                    lines.sort_by(|left, right| right.0.cmp(&left.0).then_with(|| left.1.cmp(&right.1)));
                    let more = lines.len().saturating_sub(Self::SHOWN);
                    let items: Vec<Value> = lines.into_iter().take(Self::SHOWN).map(|row| row.2).collect();
                    (port, json!({"items": items, "more": more}))
                })
                .collect(),
        )
    }

    /// `{port: rows}`: what each client called; `None` with no journal.
    pub fn calls(&self, app: &App, ports: &[i64]) -> Option<BTreeMap<i64, Value>> {
        let wanted: BTreeSet<i64> = ports.iter().copied().collect();
        let total = self.calls.totals(app, &wanted)?;
        let mut out: BTreeMap<i64, Vec<(i64, i64, String)>> = wanted.iter().map(|port| (*port, Vec::new())).collect();
        for ((port, pool), line) in total {
            out.entry(port).or_default().push((line.count, line.last, pool));
        }
        let shown = |(port, mut lines): (i64, Vec<(i64, i64, String)>)| {
            lines.sort_by(|left, right| {
                right.0.cmp(&left.0).then_with(|| right.1.cmp(&left.1)).then_with(|| left.2.cmp(&right.2))
            });
            let rows: Vec<Value> =
                lines.iter().map(|(count, last, pool)| json!({"pool": pool, "count": count, "last": last})).collect();
            (port, Value::Array(rows))
        };
        Some(out.into_iter().map(shown).collect())
    }

    /// A tally as the board's document keeps it.
    pub fn as_json(rows: &BTreeMap<i64, Value>) -> Value {
        let map: Map<String, Value> = rows.iter().map(|(port, row)| (port.to_string(), row.clone())).collect();
        Value::Object(map)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn an_error_a_client_was_told_is_a_miss() {
        let row = json!({"event": "finished", "time": 5, "status": 404, "item": {"port": 1, "method": "GET", "path": "/x", "reason": "r"}});
        let ((port, method, path, status), when, note) = MissRule::tally_of(&row).unwrap();
        assert_eq!((port, method.as_str(), path.as_str(), status, when, note.as_str()), (1, "GET", "/x", 404, 5, "r"));
        assert!(MissRule::tally_of(&json!({"event": "finished", "status": 200, "item": {"port": 1}})).is_none());
        assert!(MissRule::tally_of(&json!({"event": "received", "status": 500, "item": {"port": 1}})).is_none());
        assert!(
            MissRule::tally_of(&json!({"event": "finished", "status": 500, "item": {"port": 1, "client": "routing-probe"}}))
                .is_none()
        );
    }

    #[test]
    fn a_call_names_a_pool() {
        let row = json!({"event": "finished", "time": 5, "item": {"port": 1, "cloudPoolId": "p"}});
        assert_eq!(CallRule::tally_of(&row).unwrap().0, (1, "p".to_string()));
        assert!(CallRule::tally_of(&json!({"event": "finished", "item": {"port": 1}})).is_none());
    }
}
