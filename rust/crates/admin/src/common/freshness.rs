//! One rule: what to say about the local copy of a file from Hugging Face. A file with this name existing said nothing: a 2026-09-07 fleet check found 11 files across 5 repositories that had diverged. `unknown` is its own state, not "probably same": turning not-knowing into a claim was the original defect.

use os::LocalTime;
use rules::Coerce;
use serde_json::{Value, json};

/// The rule.
pub struct ModelFreshness;

impl ModelFreshness {
    /// States where the copy is NOT equal to what's on HF.
    pub const DIFFERS: [&'static str; 2] = ["size", "date"];

    fn day_from_epoch(mtime: Option<&Value>) -> String {
        let seconds = mtime.and_then(Coerce::int).filter(|seconds| *seconds > 0);
        seconds.and_then(LocalTime::of).map_or_else(String::new, |local| local.date())
    }

    /// (state, details) for one file. `local` is `{size, mtime}`, or none if the file is absent; `remote` is `{size, date}` as HF reports it. Dates are compared by calendar day: the upload hour and the commit hour are in different time zones, and a same-day difference means nothing.
    pub fn compare_file(local: Option<&Value>, remote: Option<&Value>) -> (&'static str, Value) {
        let Some(local) = local.filter(|local| local.is_object()) else {
            return ("missing", json!({}));
        };
        // absent-ok: a size nobody said is 0, which the next branch reads as "unknown".
        let local_size = Coerce::whole(local.get("size"));
        let remote_field = |field: &str| remote.and_then(|remote| remote.get(field));
        // absent-ok: the same.
        let remote_size = Coerce::whole(remote_field("size"));
        let local_day = Self::day_from_epoch(local.get("mtime"));
        let said_date = if Coerce::truthy(remote_field("date")) { Coerce::text(remote_field("date")) } else { String::new() };
        let remote_day = Coerce::first_letters(&said_date, 10).to_string();
        let state = if local_size == 0 || remote_size == 0 {
            "unknown"
        } else if local_size != remote_size {
            "size"
        } else if !local_day.is_empty() && !remote_day.is_empty() && remote_day > local_day {
            "date"
        } else if local_day.is_empty() || remote_day.is_empty() {
            "unknown"
        } else {
            "same"
        };
        (state, json!({"localSize": local_size, "remoteSize": remote_size, "localDate": local_day, "remoteDate": remote_day}))
    }

    /// Repository rollup: how many files diverged, and how confidently. A zero in `differs` is the claim "checked, and matches": an unchecked file counts under `unknown`.
    pub fn repo_summary<'state>(states: impl IntoIterator<Item = &'state str>) -> Value {
        let (mut differs, mut by_size, mut by_date, mut unknown, mut same, mut missing) = (0, 0, 0, 0, 0, 0);
        for state in states {
            match state {
                "size" => {
                    differs += 1;
                    by_size += 1;
                }
                "date" => {
                    differs += 1;
                    by_date += 1;
                }
                "unknown" => unknown += 1,
                "same" => same += 1,
                "missing" => missing += 1,
                _ => {}
            }
        }
        json!({"differs": differs, "bySize": by_size, "byDate": by_date, "unknown": unknown, "same": same, "missing": missing})
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn not_knowing_is_a_state_of_its_own() {
        assert_eq!(ModelFreshness::compare_file(None, None).0, "missing");
        assert_eq!(
            ModelFreshness::compare_file(Some(&json!({"size": 1, "mtime": 100000})), Some(&json!({"size": 0}))).0,
            "unknown"
        );
        assert_eq!(ModelFreshness::compare_file(Some(&json!({"size": 1, "mtime": 100000})), Some(&json!({"size": 2}))).0, "size");
        assert_eq!(
            ModelFreshness::compare_file(
                Some(&json!({"size": 1, "mtime": 100000})),
                Some(&json!({"size": 1, "date": "2030-01-01T00"}))
            )
            .0,
            "date"
        );
        assert_eq!(
            ModelFreshness::compare_file(
                Some(&json!({"size": 1, "mtime": 100000})),
                Some(&json!({"size": 1, "date": "1960-01-01T00"}))
            )
            .0,
            "same"
        );
        assert_eq!(
            ModelFreshness::compare_file(Some(&json!({"size": 1})), Some(&json!({"size": 1, "date": "2030"}))).0,
            "unknown"
        );
    }

    #[test]
    fn a_rollup_counts_each_state() {
        assert_eq!(
            ModelFreshness::repo_summary(["size", "date", "same", "unknown", "missing", "other"]),
            json!({"differs": 2, "bySize": 1, "byDate": 1, "unknown": 1, "same": 1, "missing": 1})
        );
    }
}
