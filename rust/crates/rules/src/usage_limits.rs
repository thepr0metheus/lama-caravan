//! A subscription's limit windows and a model's two levels on them.
//!
//! A window is known by its length in seconds, 18000 for five hours and 604800 for a week: a length does not depend on which slot the
//! provider happens to put the window in. OpenAI once dropped the five-hour window, and the weekly one moved into the first slot.

use crate::coerce::Coerce;
use serde_json::{Value, json};
use std::collections::BTreeMap;

/// One reading of one window.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct UsageWindow {
    /// Its length.
    pub seconds: i64,
    /// How much of it is used.
    pub used_pct: i64,
    /// When it resets, epoch seconds; `None` when nothing said.
    pub reset_at: Option<i64>,
}

impl UsageWindow {
    const SLOTS: [&'static str; 2] = ["primary", "secondary"];

    /// `int(float(text))`.
    fn share(text: &str) -> Option<i64> {
        let value = Coerce::strip(text).parse::<f64>().ok().filter(|value| value.is_finite())?;
        Some(value.trunc() as i64)
    }

    /// The windows an answer's headers state; `field` says a header by its lower-case name. None stated: no windows.
    pub fn from_headers(field: impl Fn(&str) -> Option<String>) -> Vec<Self> {
        let mut windows = Vec::new();
        for slot in Self::SLOTS {
            let minutes = field(&format!("x-codex-{slot}-window-minutes")).and_then(|text| Coerce::int(&Value::String(text)));
            let used = field(&format!("x-codex-{slot}-used-percent")).and_then(|text| Self::share(&text));
            let (Some(minutes), Some(used_pct)) = (minutes, used) else {
                continue;
            };
            if minutes <= 0 {
                continue;
            }
            let reset_at = field(&format!("x-codex-{slot}-reset-at"))
                .and_then(|text| Coerce::int(&Value::String(text)))
                .filter(|at| *at != 0);
            windows.push(Self { seconds: minutes * 60, used_pct, reset_at });
        }
        windows
    }

    /// The windows the account's usage page states. Only the two the headers carry: the page's additional windows are stated by no answer,
    /// and one of them shares the weekly length. A window without a used share is skipped, not read as unused.
    pub fn from_usage_page(payload: &Value) -> Vec<Self> {
        let mut windows = Vec::new();
        let Some(rate) = payload.get("rate_limit").filter(|rate| rate.is_object()) else {
            return windows;
        };
        for slot in ["primary_window", "secondary_window"] {
            let Some(window) = rate.get(slot).filter(|window| window.is_object()) else {
                continue;
            };
            let seconds = Coerce::int_or_zero(window.get("limit_window_seconds"));
            let used = window.get("used_percent").and_then(Self::share_of_value);
            let (Some(seconds), Some(used_pct)) = (seconds.filter(|seconds| *seconds > 0), used) else {
                continue;
            };
            let reset_at = Coerce::int_or_zero(window.get("reset_at")).filter(|at| *at != 0);
            windows.push(Self { seconds, used_pct, reset_at });
        }
        windows
    }

    fn share_of_value(value: &Value) -> Option<i64> {
        match value {
            Value::String(text) => Self::share(text),
            Value::Bool(flag) => Some(i64::from(*flag)),
            other => other.as_f64().map(|share| share.trunc() as i64),
        }
    }

    /// The reading in the words of the state file and of a pool's row.
    pub fn as_json(&self) -> Value {
        json!({"seconds": self.seconds, "usedPct": self.used_pct, "resetAt": self.reset_at})
    }
}

/// The window that keeps a step closed, and by how much.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ReserveHit {
    /// The window's length.
    pub window_seconds: i64,
    /// What is left of it.
    pub remaining_pct: i64,
    /// The level.
    pub reserve_pct: i64,
    /// When it resets.
    pub reset_at: i64,
}

impl ReserveHit {
    /// The hit in the words of a pool's row.
    pub fn as_json(&self) -> Value {
        json!({"windowSeconds": self.window_seconds, "remainingPct": self.remaining_pct, "reservePct": self.reserve_pct, "resetAt": self.reset_at})
    }
}

/// The levels per window of one model, each a whole percent from 1 to `MAX_PCT`, and the verdict they give on a reading.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct UsageReserve {
    by_seconds: BTreeMap<i64, i64>,
}

impl UsageReserve {
    /// A level of a whole window would close the step for good.
    const MAX_PCT: i64 = 90;
    /// Where a model nobody set levels for stops and switches, on its five hours and its week: with no level the caravan could spend a
    /// window to its end before anyone moved a slider.
    const NEW_STEP: [(i64, i64); 2] = [(18_000, 10), (604_800, 10)];

    /// The stored shape. Zero is "no level" and is not stored; rubbish drops out rather than becoming a number.
    pub fn normalize(raw: Option<&Value>) -> Self {
        let mut by_seconds = BTreeMap::new();
        for (key, value) in raw.and_then(Value::as_object).into_iter().flatten() {
            if value.is_boolean() {
                continue;
            }
            let seconds = Coerce::int(&Value::String(key.clone()));
            if let (Some(seconds), Some(pct)) =
                (seconds.filter(|seconds| *seconds > 0), Coerce::int(value).filter(|pct| *pct > 0))
            {
                by_seconds.insert(seconds, pct.min(Self::MAX_PCT));
            }
        }
        Self { by_seconds }
    }

    fn new_step() -> Self {
        Self { by_seconds: Self::NEW_STEP.into_iter().collect() }
    }

    /// Whether it holds a level on a window of this length.
    pub fn names(&self, seconds: i64) -> bool {
        self.by_seconds.contains_key(&seconds)
    }

    /// The window that keeps the step closed now, or `None`. A window closes it while its remaining share is at or below its level and
    /// its reset is still ahead: a reading past its reset says nothing any more, and one with no reset cannot say how long it holds. Not
    /// knowing is not a reason to refuse. Of several, the one that resets last: it is the one that keeps the door shut.
    pub fn verdict(&self, windows: &[UsageWindow], now: f64) -> Option<ReserveHit> {
        let mut found: Option<ReserveHit> = None;
        for window in windows {
            let Some(level) = self.by_seconds.get(&window.seconds).copied() else {
                continue;
            };
            // absent-ok: `int(window.get("resetAt") or 0)`: no reset is one already past, which closes nothing.
            let reset_at = window.reset_at.unwrap_or(0);
            let remaining_pct = (100 - window.used_pct).max(0);
            if reset_at as f64 > now && remaining_pct <= level && found.is_none_or(|hit| reset_at > hit.reset_at) {
                found = Some(ReserveHit { window_seconds: window.seconds, remaining_pct, reserve_pct: level, reset_at });
            }
        }
        found
    }
}

/// The stop and switch levels of the subscription models of one reading of the file: `levels`.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct ModelLevels {
    kept: BTreeMap<(String, String), (UsageReserve, UsageReserve)>,
}

impl ModelLevels {
    /// The file's map, each pair cleaned: the switch never below the stop. A pair of the time when one level did both has `switchAt` alone.
    pub fn read(raw: Option<&Value>) -> Self {
        let mut read = Self::default();
        for (account, models) in raw.and_then(Value::as_object).into_iter().flatten() {
            for (model, entry) in models.as_object().into_iter().flatten() {
                let (account, model) = (Coerce::strip(account), Coerce::strip(model));
                if entry.is_object() && !account.is_empty() && !model.is_empty() {
                    read.kept.insert((account.to_string(), model.to_string()), Self::clean(entry));
                }
            }
        }
        read
    }

    fn clean(entry: &Value) -> (UsageReserve, UsageReserve) {
        let stop = UsageReserve::normalize(entry.get("stopAt").or_else(|| entry.get("switchAt")));
        let mut switch = UsageReserve::normalize(entry.get("switchAt"));
        for (seconds, level) in &stop.by_seconds {
            let held = switch.by_seconds.entry(*seconds).or_insert(*level);
            *held = (*held).max(*level);
        }
        (stop, switch)
    }

    /// The (stop, switch) of one model: its own, or `NEW_STEP`'s when unset. Lifted levels are kept as empty maps: "no level" is a choice.
    pub fn of(&self, account: &str, model: &str) -> (UsageReserve, UsageReserve) {
        match self.kept.get(&(account.to_string(), model.to_string())) {
            Some(pair) => pair.clone(),
            None => (UsageReserve::new_step(), UsageReserve::new_step()),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn of_several_closing_windows_the_first_of_the_latest_reset_is_named() {
        let reserve = UsageReserve::normalize(Some(&json!({"100": 50, "200": 50, "300": 50})));
        let window = |seconds, reset_at| UsageWindow { seconds, used_pct: 90, reset_at: Some(reset_at) };
        let hit = reserve.verdict(&[window(100, 500), window(200, 900), window(300, 900)], 10.0).unwrap();
        assert_eq!(hit.window_seconds, 200);
    }

    #[test]
    fn a_window_exactly_at_its_level_closes_and_one_past_its_reset_does_not() {
        let reserve = UsageReserve::normalize(Some(&json!({"100": 10})));
        let at = |used_pct, reset_at| UsageWindow { seconds: 100, used_pct, reset_at };
        assert!(reserve.verdict(&[at(90, Some(50))], 10.0).is_some());
        assert!(reserve.verdict(&[at(89, Some(50))], 10.0).is_none());
        assert!(reserve.verdict(&[at(90, Some(10))], 10.0).is_none(), "a reset that is now is past");
        assert!(reserve.verdict(&[at(90, None)], 10.0).is_none());
        assert_eq!(reserve.verdict(&[at(150, Some(50))], 10.0).unwrap().remaining_pct, 0);
    }
}
