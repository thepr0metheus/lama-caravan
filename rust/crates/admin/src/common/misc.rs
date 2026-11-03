//! Small rules with no home of their own: the proxy's heartbeat, the shared queue policy, a key's cache by time, the keep of a cloud file, the journal of subscription resets, and the folder sweep.

use files::AtomicFile;
use os::{FileLock, LocalTime};
use rules::{Coerce, PythonJson};
use serde_json::{Map, Value, json};
use std::collections::{BTreeMap, HashMap};
use std::hash::Hash;
use std::path::{Path, PathBuf};
use std::sync::{Mutex, PoisonError};

/// The beat of the proxy's state file: the proxy rewrites it every 5 s whether anything happened or not, and three beats missed mean the proxy is gone, or stuck.
pub struct ProxyHeartbeat;

impl ProxyHeartbeat {
    const STALE_SECONDS: f64 = 30.0;

    /// True while a state file written at `written_at` still speaks for the proxy. A file with no time says nothing; a zero is the epoch, long stale.
    pub fn fresh(written_at: Option<&Value>, now: f64) -> bool {
        written_at.and_then(Coerce::float).is_some_and(|written| now - written <= Self::STALE_SECONDS)
    }
}

/// The three operator settings shared by every graph admission queue.
pub struct SharedQueuePolicy;

impl SharedQueuePolicy {
    /// Key, policy key, default, least, most.
    const FIELDS: [(&'static str, &'static str, i64, i64, i64); 3] = [
        ("spillPct", "cloudFallbackPct", 20, 0, 100),
        ("stickySlotSec", "stickySlotSec", 0, 0, 120),
        ("loadingModelWaitSec", "loadingModelWaitSec", 60, 0, 900),
    ];

    /// The values, each in its range: what is no number is its default.
    pub fn values(policy: Option<&Value>) -> Value {
        let mut out = Map::new();
        for (key, policy_key, default, least, most) in Self::FIELDS {
            let said = policy.and_then(|policy| policy.get(policy_key)).and_then(Coerce::int).unwrap_or(default);
            out.insert(key.to_string(), json!(said.clamp(least, most)));
        }
        Value::Object(out)
    }

    /// The same under the policy's own names.
    pub fn policy_values(policy: Option<&Value>) -> Value {
        let values = Self::values(policy);
        let mut out = Map::new();
        for (key, policy_key, ..) in Self::FIELDS {
            out.insert(policy_key.to_string(), values.get(key).cloned().unwrap_or(Value::Null));
        }
        Value::Object(out)
    }
}

/// A small (timestamp, value) cache with its own lock. Concurrent misses may both fetch, as every call site did before. A falsy value is cached like any other.
pub struct TtlCache<K, V> {
    ttl: f64,
    data: Mutex<HashMap<K, (f64, V)>>,
}

impl<K: Eq + Hash, V: Clone> TtlCache<K, V> {
    /// A cache of `ttl` seconds.
    pub fn new(ttl: f64) -> Self {
        Self { ttl, data: Mutex::new(HashMap::new()) }
    }

    /// What is held, while younger than `ttl` (the cache's own, when none is said).
    pub fn get(&self, key: &K, now: f64, ttl: Option<f64>) -> Option<V> {
        let limit = ttl.unwrap_or(self.ttl);
        let data = self.data.lock().unwrap_or_else(PoisonError::into_inner);
        data.get(key).filter(|(when, _)| now - when < limit).map(|(_, value)| value.clone())
    }

    /// Holds a value.
    pub fn put(&self, key: K, value: V, now: f64) {
        self.data.lock().unwrap_or_else(PoisonError::into_inner).insert(key, (now, value));
    }

    /// Forgets all of it.
    pub fn clear(&self) {
        self.data.lock().unwrap_or_else(PoisonError::into_inner).clear();
    }
}

/// What cloud-providers.json keeps beside its accounts and pools: one table for every reader and writer of the file. A key whose value is empty or of another shape is not written: an empty map and no map read the same.
pub struct CloudFileKeys;

impl CloudFileKeys {
    const KEPT: [(&'static str, bool); 5] =
        [("levels", false), ("addedModels", false), ("boardProviders", true), ("schedules", false), ("modelJobs", false)];

    /// The kept keys a parsed file holds, each only when it has the right shape and is not empty.
    pub fn read(parsed: Option<&Value>) -> Map<String, Value> {
        let mut out = Map::new();
        for (key, is_list) in Self::KEPT {
            let said =
                parsed.and_then(|parsed| parsed.get(key)).filter(|said| if is_list { said.is_array() } else { said.is_object() });
            if let Some(said) = said.filter(|said| Coerce::truthy(Some(*said))) {
                out.insert(key.to_string(), said.clone());
            }
        }
        out
    }
}

/// Durable reset attempts and confirmed quota invalidations, shared by both daemons.
pub struct SubscriptionResetJournal {
    path: PathBuf,
}

impl SubscriptionResetJournal {
    /// The journal at `path`.
    pub fn new(path: PathBuf) -> Self {
        Self { path }
    }

    /// The journal as it stands; none of it yet reads as no attempts and no resets.
    pub fn read(&self) -> Result<Value, String> {
        match std::fs::read(&self.path) {
            Ok(raw) => serde_json::from_slice(&raw).map_err(|error| error.to_string()),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(json!({"attempts": {}, "resets": {}})),
            Err(error) => Err(error.to_string()),
        }
    }

    /// When the account's quota was last reset; 0 for never, or for a journal that does not read.
    pub fn reset_at(&self, account_id: &str) -> f64 {
        let journal = self.read();
        let said = journal.as_ref().ok().and_then(|journal| journal.get("resets")).and_then(|resets| resets.get(account_id));
        // absent-ok: a reset nobody wrote down is 0: every window counts from before it.
        said.and_then(Coerce::float).unwrap_or(0.0)
    }

    /// A reading held under the lock both daemons take.
    pub fn locked<R>(&self, work: impl FnOnce(Value) -> Result<R, String>) -> Result<R, String> {
        if let Some(parent) = self.path.parent() {
            std::fs::create_dir_all(parent).map_err(|error| error.to_string())?;
        }
        let _held = FileLock::exclusive(&self.path.with_extension("lock")).map_err(|error| error.to_string())?;
        work(self.read()?)
    }

    /// Writes it back, keeping unresolved attempts, even when trimming the completed journal.
    pub fn write(&self, data: &mut Value) -> Result<(), String> {
        const KEPT_COMPLETED: usize = 100;
        if let Some(rows) = data.get_mut("attempts").and_then(Value::as_object_mut) {
            let mut completed: Vec<(f64, String)> = rows
                .iter()
                .filter(|(_, row)| Coerce::truthy(row.get("outcome")))
                // absent-ok: a completed attempt with no time is the oldest there is, and goes first
                .map(|(key, row)| (row.get("at").and_then(Coerce::float).unwrap_or_default(), key.clone()))
                .collect();
            completed.sort_by(|left, right| left.0.total_cmp(&right.0));
            let doomed = completed.len().saturating_sub(KEPT_COMPLETED);
            for (_, key) in completed.iter().take(doomed) {
                rows.shift_remove(key);
            }
        }
        AtomicFile::write_private(&self.path, PythonJson::spaced(data).as_bytes()).map_err(|error| error.to_string())
    }
}

/// Rows by name in the order their names first came: what Python's dict gives a tally for free, and what a board's column shows.
pub struct Ordered<T> {
    order: Vec<String>,
    rows: BTreeMap<String, T>,
}

impl<T> Default for Ordered<T> {
    fn default() -> Self {
        Self { order: Vec::new(), rows: BTreeMap::new() }
    }
}

impl<T: Default> Ordered<T> {
    /// The row of `name`, a new one last.
    pub fn entry(&mut self, name: &str) -> &mut T {
        if !self.rows.contains_key(name) {
            self.order.push(name.to_string());
        }
        self.rows.entry(name.to_string()).or_default()
    }
}

impl<T> Ordered<T> {
    /// The row of `name`.
    pub fn get(&self, name: &str) -> Option<&T> {
        self.rows.get(name)
    }

    /// Every row in its order.
    pub fn iter(&self) -> impl Iterator<Item = (&String, &T)> {
        self.order.iter().filter_map(|name| self.rows.get(name).map(|row| (name, row)))
    }

    /// Whether it holds nothing.
    pub fn is_empty(&self) -> bool {
        self.order.is_empty()
    }
}

/// A moment written as `datetime.fromisoformat` reads it.
pub struct IsoMoment;

impl IsoMoment {
    /// Unix seconds of `2026-11-01T15:04:05[.123][Z|+04:00]`, or of the date alone. A moment with no zone is the machine's local time; `None` for
    /// what is no moment.
    pub fn epoch(text: &str) -> Option<f64> {
        let text = text.trim();
        let (date, rest) = match text.char_indices().find(|(_, letter)| *letter == 'T' || *letter == ' ') {
            Some((at, _)) => (text.get(..at)?, text.get(at + 1..)?),
            None => (text, "00:00:00"),
        };
        let mut parts = date.split('-');
        let (year, month, day): (i64, i64, i64) =
            (parts.next()?.parse().ok()?, parts.next()?.parse().ok()?, parts.next()?.parse().ok()?);
        if parts.next().is_some() || !(1..=12).contains(&month) || !(1..=31).contains(&day) {
            return None;
        }
        let (clock, zone) = Self::split_zone(rest)?;
        let mut pieces = clock.split(':');
        let hour: i64 = pieces.next()?.parse().ok()?;
        let minute: i64 = pieces.next().map_or(Some(0), |said| said.parse().ok())?;
        let seconds: f64 = pieces.next().map_or(Some(0.0), |said| said.parse().ok())?;
        if pieces.next().is_some() {
            return None;
        }
        let wall = (Self::days_from_civil(year, month, day) * 86400 + hour * 3600 + minute * 60) as f64 + seconds;
        Some(match zone {
            Some(offset) => wall - (offset * 60) as f64,
            // absent-ok: a moment the system cannot place reads as UTC.
            None => wall - LocalTime::of(wall as i64).map_or(0, |here| here.offset_minutes) as f64 * 60.0,
        })
    }

    /// The days since the epoch of a calendar date.
    fn days_from_civil(year: i64, month: i64, day: i64) -> i64 {
        let year = if month <= 2 { year - 1 } else { year };
        let era = year.div_euclid(400);
        let year_of_era = year.rem_euclid(400);
        let shifted_month = (month + 9) % 12;
        let day_of_year = (153 * shifted_month + 2) / 5 + day - 1;
        let day_of_era = year_of_era * 365 + year_of_era / 4 - year_of_era / 100 + day_of_year;
        era * 146_097 + day_of_era - 719_468
    }

    /// The clock and its zone in minutes east, `None` for a clock with no zone.
    fn split_zone(rest: &str) -> Option<(&str, Option<i64>)> {
        if let Some(clock) = rest.strip_suffix('Z') {
            return Some((clock, Some(0)));
        }
        let at = rest.char_indices().find(|(_, letter)| *letter == '+' || *letter == '-').map(|(at, _)| at);
        let Some(at) = at else {
            return Some((rest, None));
        };
        let sign = if rest.get(at..at + 1)? == "-" { -1 } else { 1 };
        let zone = rest.get(at + 1..)?;
        let (hours, minutes) = zone.split_once(':').unwrap_or((zone, "0"));
        let (hours, minutes): (i64, i64) = (hours.parse().ok()?, minutes.parse().ok()?);
        Some((rest.get(..at)?, Some(sign * (hours * 60 + minutes))))
    }
}

/// Filesystem helpers.
pub struct Folders;

impl Folders {
    /// `folder` and the parents above it while each is empty, up to and never including `root`: what is left of a model's author/quant skeleton once its last file is gone. A folder outside `root`, or one that cannot go, stops it.
    pub fn prune_empty(folder: &Path, root: &Path) {
        let mut at = folder.to_path_buf();
        while at != root && at.starts_with(root) {
            let empty = std::fs::read_dir(&at).is_ok_and(|mut names| names.next().is_none());
            if !empty || std::fs::remove_dir(&at).is_err() {
                return;
            }
            let Some(parent) = at.parent() else {
                return;
            };
            at = parent.to_path_buf();
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_state_file_speaks_for_thirty_seconds() {
        assert!(ProxyHeartbeat::fresh(Some(&json!(100)), 130.0));
        assert!(!ProxyHeartbeat::fresh(Some(&json!(100)), 131.0));
        assert!(!ProxyHeartbeat::fresh(None, 0.0));
        assert!(!ProxyHeartbeat::fresh(Some(&json!("x")), 0.0));
    }

    #[test]
    fn a_policy_is_cut_to_its_range() {
        assert_eq!(
            SharedQueuePolicy::values(Some(&json!({"cloudFallbackPct": 500, "stickySlotSec": "x"}))),
            json!({"spillPct": 100, "stickySlotSec": 0, "loadingModelWaitSec": 60})
        );
        assert_eq!(
            SharedQueuePolicy::policy_values(None),
            json!({"cloudFallbackPct": 20, "stickySlotSec": 0, "loadingModelWaitSec": 60})
        );
    }

    #[test]
    fn a_cloud_file_keeps_only_what_has_its_shape() {
        let kept = CloudFileKeys::read(Some(
            &json!({"levels": {"a": 1}, "addedModels": {}, "boardProviders": {"x": 1}, "schedules": [1], "other": 1}),
        ));
        assert_eq!(Value::Object(kept), json!({"levels": {"a": 1}}));
    }

    #[test]
    fn a_ttl_cache_forgets_by_the_clock() {
        let cache = TtlCache::new(5.0);
        cache.put("a", 0, 100.0);
        assert_eq!(cache.get(&"a", 104.0, None), Some(0));
        assert_eq!(cache.get(&"a", 105.0, None), None);
        assert_eq!(cache.get(&"a", 110.0, Some(20.0)), Some(0));
    }

    #[test]
    fn a_moment_reads_as_python_reads_it() {
        let at = |text: &str| IsoMoment::epoch(text);
        assert_eq!(at("1970-01-01T00:16:40Z"), Some(1000.0));
        assert_eq!(at("1970-01-01T00:16:40+00:00"), Some(1000.0));
        assert_eq!(at("1970-01-01T04:16:40+04:00"), Some(1000.0));
        assert_eq!(at("1970-01-01T00:16:40.5Z"), Some(1000.5));
        assert_eq!(at("soon"), None);
        assert_eq!(at("2026-13-01T00:00:00Z"), None);
    }

    #[test]
    fn ordered_rows_keep_the_order_their_names_came() {
        let mut rows: Ordered<i64> = Ordered::default();
        *rows.entry("b") += 1;
        *rows.entry("a") += 1;
        *rows.entry("b") += 1;
        let seen: Vec<(&String, &i64)> = rows.iter().collect();
        assert_eq!(seen.len(), 2);
        assert_eq!(seen[0].0, "b");
        assert_eq!(*seen[0].1, 2);
    }
}
