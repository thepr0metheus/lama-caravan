//! When a model is open and of `ModelSchedules`.
//!
//! A window is `{"days": [0..6], "from": "HH:MM", "to": "HH:MM"}`: Monday is 0, and no days means every day. A window whose `to` is not after
//! its `from` runs past midnight and belongs to the day it starts on; `from` equal to `to` is a whole day from that time. Times are the
//! caravan's wall clock, which this module asks of `WallClock`: it reads no zone itself.

use crate::coerce::Coerce;
use serde_json::Value;
use std::collections::BTreeMap;

/// The zone's clock, as a schedule needs it.
pub trait WallClock {
    /// The minutes since Monday 00:00 of the week `epoch` stands in, on the zone's clock.
    fn minute_of_week(&self, epoch: f64) -> i64;
    /// The epoch of `minute` minutes after Monday 00:00 of the week `epoch` stands in. Wall-clock arithmetic: a window from 22:00 to 08:00
    /// ends at 08:00 on the clock, whatever a night of a clock change makes of its length.
    fn epoch_of_week_minute(&self, epoch: f64, minute: i64) -> i64;
    /// `epoch` as a person in any zone reads it right: "2026-10-12 19:00 UTC+04:00".
    fn text(&self, epoch: i64) -> String;
}

/// One window, as minutes.
#[derive(Debug, Clone, PartialEq, Eq)]
struct Window {
    days: Vec<i64>,
    from: i64,
    to: i64,
}

/// The windows of one schedule, and what they say at a moment.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct WeekWindows {
    windows: Vec<Window>,
}

/// What a schedule says at a moment.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ScheduleState {
    /// Whether a window holds the moment.
    pub open: bool,
    /// The epoch the next window opens; `None` while open, or when none ever opens.
    pub opens_at: Option<i64>,
}

impl WeekWindows {
    const DAY: i64 = 1440;
    const WEEK: i64 = 7 * Self::DAY;
    /// More windows than a week has hours is no schedule a person made.
    const MAX: usize = 168;

    /// The windows as a reader takes them from the file: each one that reads, in order; one that does not is left out.
    pub fn clean(raw: Option<&Value>) -> Self {
        let mut windows = Vec::new();
        for item in raw.and_then(Value::as_array).into_iter().flatten() {
            if let Some(window) = Self::window(item).filter(|window| !windows.contains(window)) {
                windows.push(window);
            }
        }
        windows.truncate(Self::MAX);
        Self { windows }
    }

    fn window(raw: &Value) -> Option<Window> {
        raw.as_object()?;
        let (from, to) = (Self::minutes(raw.get("from"))?, Self::minutes(raw.get("to"))?);
        Some(Window { days: Self::days(raw.get("days"))?, from, to })
    }

    /// `HH:MM` as minutes: one or two digits of an hour up to 23, two of a minute up to 59; an empty field is none.
    fn minutes(raw: Option<&Value>) -> Option<i64> {
        let said = Coerce::stripped(raw);
        let (hour, minute) = said.split_once(':')?;
        let digits = |text: &str| !text.is_empty() && text.chars().all(|letter| letter.is_ascii_digit());
        if !digits(hour) || !digits(minute) || hour.len() > 2 || minute.len() != 2 {
            return None;
        }
        let (hour, minute) = (hour.parse::<i64>().ok()?, minute.parse::<i64>().ok()?);
        (hour <= 23 && minute <= 59).then_some(hour * 60 + minute)
    }

    /// The days, sorted; all seven are every day, said one way: none. A day that is no number of 0..6 makes the window unreadable.
    fn days(raw: Option<&Value>) -> Option<Vec<i64>> {
        let Some(raw) = raw.filter(|raw| !raw.is_null()) else {
            return Some(Vec::new());
        };
        let mut days = Vec::new();
        for day in raw.as_array()? {
            let day = day.as_i64().filter(|day| (0..=6).contains(day))?;
            if !days.contains(&day) {
                days.push(day);
            }
        }
        days.sort_unstable();
        if days.len() == 7 {
            days.clear();
        }
        Some(days)
    }

    /// The open minutes of the week as sorted, merged runs, Monday 00:00 being 0. A window that runs past Sunday midnight goes on at the
    /// week's start; two runs that touch are one.
    pub fn runs(&self) -> Vec<(i64, i64)> {
        let mut pieces = Vec::new();
        for window in &self.windows {
            let length = (window.to - window.from).rem_euclid(Self::DAY);
            let length = if length == 0 { Self::DAY } else { length };
            let every_day: Vec<i64> = (0..7).collect();
            for day in if window.days.is_empty() { &every_day } else { &window.days } {
                let begin = day * Self::DAY + window.from;
                let end = begin + length;
                if end <= Self::WEEK {
                    pieces.push((begin, end));
                } else {
                    pieces.push((begin, Self::WEEK));
                    pieces.push((0, end - Self::WEEK));
                }
            }
        }
        Self::merged(pieces)
    }

    fn merged(mut pieces: Vec<(i64, i64)>) -> Vec<(i64, i64)> {
        pieces.sort_unstable();
        let mut out: Vec<(i64, i64)> = Vec::new();
        for (begin, end) in pieces {
            match out.last_mut() {
                Some(last) if begin <= last.1 => last.1 = last.1.max(end),
                _ => out.push((begin, end)),
            }
        }
        out
    }

    /// The epoch the window open at `now` closes; `None` when none is open, or the week has no end to it.
    pub fn open_until(&self, now: f64, clock: &dyn WallClock) -> Option<i64> {
        let runs = self.runs();
        if runs.is_empty() || runs == [(0, Self::WEEK)] {
            return None;
        }
        let minute = clock.minute_of_week(now);
        let mut both = runs.clone();
        both.extend(runs.iter().map(|(begin, end)| (begin + Self::WEEK, end + Self::WEEK)));
        let found = Self::merged(both).into_iter().find(|(begin, end)| *begin <= minute && minute < *end);
        found.map(|(_, end)| clock.epoch_of_week_minute(now, end))
    }

    /// What they say at `now`.
    pub fn state(&self, now: f64, clock: &dyn WallClock) -> ScheduleState {
        let runs = self.runs();
        if runs.is_empty() {
            return ScheduleState { open: false, opens_at: None };
        }
        if runs == [(0, Self::WEEK)] {
            return ScheduleState { open: true, opens_at: None };
        }
        let minute = clock.minute_of_week(now);
        // This week and the next, merged across the joint: a stretch open over Sunday midnight ends when Monday's part does.
        let mut both = runs.clone();
        both.extend(runs.iter().map(|(begin, end)| (begin + Self::WEEK, end + Self::WEEK)));
        for (begin, end) in Self::merged(both) {
            if begin <= minute && minute < end {
                return ScheduleState { open: true, opens_at: None };
            }
            if begin > minute {
                return ScheduleState { open: false, opens_at: Some(clock.epoch_of_week_minute(now, begin)) };
            }
        }
        ScheduleState { open: false, opens_at: None }
    }
}

/// The schedules of the models of one reading of the file: `schedules`, by the key Routing draws its right column with.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct ModelSchedules {
    kept: BTreeMap<String, (bool, WeekWindows)>,
}

impl ModelSchedules {
    /// The file's map; a key that names no model and an entry that is no object are dropped.
    pub fn read(raw: Option<&Value>) -> Self {
        let mut read = Self::default();
        for (key, entry) in raw.and_then(Value::as_object).into_iter().flatten() {
            if Self::is_key(key) && entry.is_object() {
                let enabled = entry.get("enabled") == Some(&Value::Bool(true));
                read.kept.insert(key.clone(), (enabled, WeekWindows::clean(entry.get("windows"))));
            }
        }
        read
    }

    /// `ModelKey.parse`: `acc:<account>/<model>` or `out:<output>`, each of its clean parts.
    fn is_key(key: &str) -> bool {
        if let Some(rest) = key.strip_prefix("acc:") {
            let (account, model) = rest.split_once('/').unwrap_or((rest, ""));
            return !account.is_empty()
                && !model.is_empty()
                && Coerce::strip(account) == account
                && Coerce::strip(model) == model;
        }
        key.strip_prefix("out:").is_some_and(crate::cloud_pools::PoolRow::is_output_id)
    }

    /// `None` while the model may serve: no schedule, one switched off, or a window open now. Else when it opens next.
    pub fn closed(&self, key: &str, now: f64, clock: &dyn WallClock) -> Option<Option<i64>> {
        let (enabled, windows) = self.kept.get(key)?;
        if !enabled {
            return None;
        }
        let state = windows.state(now, clock);
        (!state.open).then_some(state.opens_at)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    /// A clock where the week begins at epoch 0 and a minute is sixty seconds, whatever the zone.
    struct PlainClock;

    impl WallClock for PlainClock {
        fn minute_of_week(&self, epoch: f64) -> i64 {
            (epoch as i64 / 60).rem_euclid(WeekWindows::WEEK)
        }

        fn epoch_of_week_minute(&self, epoch: f64, minute: i64) -> i64 {
            (epoch as i64 / 60).div_euclid(WeekWindows::WEEK) * WeekWindows::WEEK * 60 + minute * 60
        }

        fn text(&self, epoch: i64) -> String {
            epoch.to_string()
        }
    }

    fn at(day: i64, hour: i64, minute: i64) -> f64 {
        ((day * 1440 + hour * 60 + minute) * 60) as f64
    }

    fn state(windows: Value, now: f64) -> ScheduleState {
        WeekWindows::clean(Some(&windows)).state(now, &PlainClock)
    }

    fn until(windows: &Value, now: f64) -> Option<i64> {
        WeekWindows::clean(Some(windows)).open_until(now, &PlainClock)
    }

    #[test]
    fn an_open_window_says_when_it_closes() {
        let friday = json!([{"days": [4], "from": "09:00", "to": "19:00"}]);
        assert_eq!(until(&friday, at(4, 9, 0)), Some(at(4, 19, 0) as i64));
        assert_eq!(until(&friday, at(4, 18, 59)), Some(at(4, 19, 0) as i64));
        assert_eq!(until(&friday, at(4, 19, 0)), None, "closed at its end");
        assert_eq!(until(&friday, at(4, 8, 59)), None, "not open yet");
    }

    #[test]
    fn a_week_with_no_end_or_no_window_closes_at_nothing() {
        assert_eq!(until(&json!([{"from": "00:00", "to": "00:00"}]), at(2, 3, 0)), None);
        assert_eq!(until(&json!([]), at(2, 3, 0)), None);
    }

    #[test]
    fn a_stretch_over_sunday_midnight_closes_when_monday_s_part_does() {
        let night = json!([{"days": [6], "from": "22:00", "to": "08:00"}]);
        assert_eq!(until(&night, at(6, 23, 0)), Some(at(7, 8, 0) as i64));
        assert_eq!(until(&night, at(0, 7, 0)), Some(at(0, 8, 0) as i64));
    }

    #[test]
    fn windows_that_touch_are_one() {
        let two = json!([{"days": [1], "from": "10:00", "to": "12:00"}, {"days": [1], "from": "12:00", "to": "14:00"}]);
        assert_eq!(until(&two, at(1, 11, 0)), Some(at(1, 14, 0) as i64));
    }

    #[test]
    fn a_time_python_s_pattern_would_not_take_makes_the_window_unreadable() {
        for (from, to) in [
            ("+1:30", "12:00"),
            ("01:+5", "12:00"),
            ("24:00", "12:00"),
            ("12:60", "12:00"),
            ("123:00", "12:00"),
            ("1:5", "12:00"),
            ("a:00", "12:00"),
            ("01:00", "1:ab"),
        ] {
            let windows = json!([{"from": from, "to": to}]);
            assert!(!state(windows, at(0, 13, 0)).open, "{from} {to}");
        }
        assert!(state(json!([{"from": "1:30", "to": "23:59"}]), at(0, 13, 0)).open, "one digit of an hour is an hour");
    }

    #[test]
    fn a_window_of_the_day_holds_from_its_from_up_to_its_to() {
        let friday = json!([{"days": [4], "from": "09:00", "to": "19:00"}]);
        assert!(!state(friday.clone(), at(4, 8, 59)).open);
        assert!(state(friday.clone(), at(4, 9, 0)).open);
        assert!(state(friday.clone(), at(4, 18, 59)).open);
        let shut = state(friday.clone(), at(4, 19, 0));
        assert!(!shut.open);
        assert_eq!(shut.opens_at, Some(at(11, 9, 0) as i64), "next Friday");
        assert_eq!(state(friday, at(3, 12, 0)).opens_at, Some(at(4, 9, 0) as i64));
    }

    #[test]
    fn a_window_past_midnight_belongs_to_the_day_it_starts_on() {
        let night = json!([{"days": [4], "from": "22:00", "to": "08:00"}]);
        assert!(state(night.clone(), at(4, 23, 0)).open);
        assert!(state(night.clone(), at(5, 7, 59)).open);
        assert!(!state(night.clone(), at(5, 8, 0)).open);
        assert!(!state(night, at(4, 7, 0)).open);
        let sunday_night = json!([{"days": [6], "from": "22:00", "to": "08:00"}]);
        assert!(state(sunday_night.clone(), at(0, 7, 0)).open, "over the week's joint");
        assert!(state(sunday_night, at(6, 23, 0)).open);
    }

    #[test]
    fn from_equal_to_to_is_a_whole_day_and_no_days_is_every_day() {
        let whole = json!([{"days": [1], "from": "10:00", "to": "10:00"}]);
        assert!(state(whole.clone(), at(2, 9, 59)).open);
        assert!(!state(whole, at(2, 10, 0)).open);
        let always = json!([{"from": "00:00", "to": "00:00"}]);
        assert_eq!(state(always, at(3, 3, 0)), ScheduleState { open: true, opens_at: None });
        let seven = json!([{"days": [0, 1, 2, 3, 4, 5, 6, 6], "from": "09:00", "to": "10:00"}]);
        assert!(state(seven, at(5, 9, 30)).open);
    }

    #[test]
    fn no_window_never_opens() {
        assert_eq!(state(json!([]), at(0, 0, 0)), ScheduleState { open: false, opens_at: None });
    }

    #[test]
    fn a_window_that_does_not_read_is_left_out() {
        for broken in [
            json!({"from": "09:00"}),
            json!({"to": "09:00"}),
            json!({"from": "24:00", "to": "10:00"}),
            json!({"from": "09:60", "to": "10:00"}),
            json!({"from": "9:5", "to": "10:00"}),
            json!({"from": "009:00", "to": "10:00"}),
            json!({"from": "09:00", "to": "10:00", "days": [7]}),
            json!({"from": "09:00", "to": "10:00", "days": [true]}),
            json!({"from": "09:00", "to": "10:00", "days": "monday"}),
            json!("09:00"),
        ] {
            assert_eq!(WeekWindows::clean(Some(&json!([broken.clone()]))).windows, vec![], "{broken}");
        }
        let two = json!([{"from": "9:00", "to": "10:00"}, {"from": "09:00", "to": "10:00"}]);
        assert_eq!(WeekWindows::clean(Some(&two)).windows.len(), 1, "one window said twice is one");
    }

    #[test]
    fn a_schedule_switched_off_or_open_lets_its_model_serve() {
        let schedules = ModelSchedules::read(Some(&json!({
            "out:mm:a": {"enabled": true, "windows": [{"days": [4], "from": "09:00", "to": "19:00"}]},
            "out:mm:off": {"enabled": false, "windows": []},
            "out:mm:yes": {"enabled": 1, "windows": []},
            "acc:key/m": {"enabled": true, "windows": []},
            "acc:key": {"enabled": true, "windows": []},
            "other": {"enabled": true, "windows": []},
            "out:mm:odd": "not an entry",
        })));
        assert_eq!(schedules.closed("out:mm:a", at(4, 10, 0), &PlainClock), None);
        assert_eq!(schedules.closed("out:mm:a", at(3, 10, 0), &PlainClock), Some(Some(at(4, 9, 0) as i64)));
        assert_eq!(schedules.closed("out:mm:off", at(3, 10, 0), &PlainClock), None);
        assert_eq!(schedules.closed("out:mm:yes", at(3, 10, 0), &PlainClock), None, "only true switches it on");
        assert_eq!(schedules.closed("acc:key/m", at(3, 10, 0), &PlainClock), Some(None), "no window ever opens");
        for key in ["acc:key", "other", "out:mm:odd", "nobody"] {
            assert_eq!(schedules.closed(key, at(3, 10, 0), &PlainClock), None, "{key}");
        }
    }
}
