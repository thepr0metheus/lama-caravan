//! A cell's start and stop by the clock.

use super::cell_ops::CellOps;
use super::host_power::HostPower;
use super::server_cells::ServerCells;
use crate::app::App;
use crate::models::model_list::ModelList;
use crate::store::topology::Topology;
use os::LocalTime;
use plumbing::Ticking;
use plumbing::log::Log;
use rules::{AppError, Coerce};
use serde_json::{Value, json};
use std::collections::BTreeSet;
use std::sync::Arc;
use std::time::Duration;

/// The moment a schedule is read at.
#[derive(Clone, Copy)]
pub struct ClockReading {
    /// Monday is 0.
    pub weekday: i64,
    /// The minute of the day.
    pub minute: i64,
    /// The epoch of this minute.
    pub epoch: i64,
}

impl ClockReading {
    /// The local reading of an epoch; `None` when the system cannot place it.
    pub fn of(epoch: i64) -> Option<Self> {
        let here = LocalTime::of(epoch)?;
        Some(Self { weekday: i64::from(here.weekday), minute: i64::from(here.hour) * 60 + i64::from(here.minute), epoch })
    }
}

/// When a cell should be on.
pub struct CellSchedule;

impl CellSchedule {
    const PREFETCH_MIN: i64 = 30;

    fn hhmm(value: Option<&Value>, default: &str) -> Result<String, AppError> {
        let raw = value
            .filter(|said| !said.is_null() && **said != json!(""))
            .map_or_else(|| default.to_string(), |said| Coerce::strip(&Coerce::str_of(Some(said))).to_string());
        let parts = raw.split_once(':').filter(|(hour, minute)| {
            (1..=2).contains(&hour.len())
                && minute.len() == 2
                && hour.chars().chain(minute.chars()).all(|digit| digit.is_ascii_digit())
        });
        let Some((hour, minute)) = parts else {
            return Err(AppError::new(format!("time must look like HH:MM, got: {raw}")));
        };
        // absent-ok: both are digits: checked above.
        let (hour, minute): (i64, i64) = (hour.parse().unwrap_or(0), minute.parse().unwrap_or(0));
        if hour > 23 || minute > 59 {
            return Err(AppError::new(format!("time out of range: {raw}")));
        }
        Ok(format!("{hour:02}:{minute:02}"))
    }

    fn minutes(hhmm: &str) -> i64 {
        let (hour, minute) = hhmm.split_once(':').unwrap_or(("0", "0"));
        // absent-ok: a stored time is one `hhmm` wrote.
        hour.parse::<i64>().unwrap_or(0) * 60 + minute.parse::<i64>().unwrap_or(0)
    }

    /// A schedule as a slot keeps it.
    pub fn normalize(payload: &Value) -> Result<Value, AppError> {
        if !payload.is_object() {
            return Err(AppError::new("schedule must be an object"));
        }
        let mut days = BTreeSet::new();
        for day in payload.get("days").and_then(Value::as_array).into_iter().flatten() {
            let day = Coerce::int(day).ok_or_else(|| AppError::new("days must be integers 0..6 (Mon=0)"))?;
            if (0..=6).contains(&day) {
                days.insert(day);
            }
        }
        let (start, stop) = (Self::hhmm(payload.get("start"), "22:00")?, Self::hhmm(payload.get("stop"), "08:00")?);
        let enabled = Coerce::truthy(payload.get("enabled"));
        if enabled && start == stop {
            return Err(AppError::new("start and stop must differ"));
        }
        Ok(json!({"enabled": enabled, "start": start, "stop": stop, "days": days}))
    }

    fn days_of(schedule: &Value) -> Vec<i64> {
        let said: Vec<i64> =
            schedule.get("days").and_then(Value::as_array).into_iter().flatten().filter_map(Value::as_i64).collect();
        if said.is_empty() { (0..7).collect() } else { said }
    }

    fn word_or(schedule: &Value, key: &str, otherwise: &str) -> String {
        let said = Coerce::text(schedule.get(key));
        if said.is_empty() { otherwise.to_string() } else { said }
    }

    /// Whether `now` falls in the schedule's window: a window that passes midnight belongs to the day it started.
    pub fn in_window(schedule: &Value, now: ClockReading) -> bool {
        let days = Self::days_of(schedule);
        let start = Self::minutes(&Self::word_or(schedule, "start", "22:00"));
        let stop = Self::minutes(&Self::word_or(schedule, "stop", "08:00"));
        if start == stop {
            return false;
        }
        if start < stop {
            return days.contains(&now.weekday) && start <= now.minute && now.minute < stop;
        }
        if days.contains(&now.weekday) && now.minute >= start {
            return true;
        }
        days.contains(&(now.weekday - 1).rem_euclid(7)) && now.minute < stop
    }

    /// Minutes until the next window opens; `None` when it never opens.
    pub fn minutes_to_window(schedule: &Value, now: ClockReading) -> Option<i64> {
        let days = Self::days_of(schedule);
        let start = Self::minutes(&Self::word_or(schedule, "start", "22:00"));
        if start == Self::minutes(&Self::word_or(schedule, "stop", "08:00")) {
            return None;
        }
        (0..8)
            .filter(|ahead| days.contains(&((now.weekday + ahead) % 7)))
            .map(|ahead| ahead * 1440 + start - now.minute)
            .find(|left| *left >= 0)
    }

    /// A cell's schedule from now on, of the cell `cellId` names.
    pub fn set(app: &App, body: &Value) -> Result<Value, AppError> {
        let id = ServerCells::asked_id(body)?;
        if !app.admin.change(|doc| Topology::of(doc).has_slot(&id)) {
            return Err(AppError::with_status(format!("no such cell: {id}"), 404));
        }
        let empty = json!({});
        let schedule = Self::normalize(body.get("schedule").filter(|said| Coerce::truthy(Some(*said))).unwrap_or(&empty))?;
        app.admin.saving(|doc| {
            if let Some(slot) = Topology::of(doc).find_slot(&id) {
                Coerce::put(slot, "schedule", schedule.clone());
                Coerce::take(slot, "schedState");
            }
        });
        Ok(json!({"ok": true, "cellId": id, "schedule": schedule}))
    }

    /// A model brought home before the window opens, so that a scheduled cell starts from this disk instead of reading over the network.
    fn prefetch(app: &App, slot: &mut Value, schedule: &Value, now: ClockReading) -> bool {
        let Some(left) = Self::minutes_to_window(schedule, now).filter(|left| *left <= Self::PREFETCH_MIN) else {
            return false;
        };
        let opening = LocalTime::of(now.epoch + left * 60);
        let opens = opening.map_or_else(String::new, |at| format!("{} {:02}:{:02}", at.date(), at.hour, at.minute));
        if Coerce::text(slot.get("schedFetch")) == opens {
            return false;
        }
        Coerce::put(slot, "schedFetch", json!(opens));
        let config = slot.get("config").cloned().unwrap_or_else(|| json!({}));
        let job = CellOps::of(app).bring_home(&config, &ModelList::locations(app, true));
        if job.is_some() {
            Log::line(&format!(
                "[cell-schedule] {} on {}: bringing the model home for {opens}",
                Coerce::text(slot.get("id")),
                Coerce::text(slot.get("hostId"))
            ));
        }
        true
    }

    /// One pass over the slots.
    pub fn tick(app: &App, now: ClockReading) {
        let slots = app.admin.change(|doc| Topology::of(doc).slots().clone());
        let mut changed = false;
        let mut updated = slots.clone();
        for (key, slot) in &mut updated {
            let schedule = slot.get("schedule").cloned().unwrap_or_else(|| json!({}));
            if !Coerce::truthy(schedule.get("enabled")) {
                changed = Coerce::take(slot, "schedState").is_some() || changed;
                continue;
            }
            let want = if Self::in_window(&schedule, now) { "on" } else { "off" };
            if want == "off" && Self::prefetch(app, slot, &schedule, now) {
                changed = true;
            }
            let last = slot.get("schedState").and_then(Value::as_str).map(str::to_string);
            if last.as_deref() == Some(want) {
                continue;
            }
            Coerce::put(slot, "schedState", json!(want));
            changed = true;
            if last.is_none() && want == "off" {
                continue;
            }
            let action = if want == "on" { "start" } else { "stop" };
            Log::line(&format!("[cell-schedule] {key}: window -> {action}"));
            let asked = json!({"cellId": key, "action": action});
            if let Err(error) = CellOps::of(app).action(&asked) {
                Log::line(&format!("[cell-schedule] {key}: {action} failed: {}", error.message));
            }
        }
        if changed {
            app.admin.saving(|doc| {
                let mut topology = Topology::of(doc);
                let current = topology.slots();
                for (key, slot) in updated {
                    // A slot deleted during the pass stays deleted.
                    if current.contains_key(&key) {
                        current.insert(key, slot);
                    }
                }
            });
        }
    }

    /// The thread of the cells' and the machines' schedules.
    pub fn start_thread(app: &Arc<App>) -> std::io::Result<()> {
        let app = Arc::clone(app);
        std::thread::Builder::new().name("cell-schedule".to_string()).spawn(move || {
            // Let the board settle after a start. One timer for each kind of schedule: a failure in one never stops the other.
            std::thread::sleep(Duration::from_secs(20));
            let cells = Arc::clone(&app);
            Ticking::in_background("cell-schedule-tick", Duration::from_secs(60), move || {
                if let Some(now) = ClockReading::of(cells.now_whole()) {
                    Self::tick(&cells, now);
                }
            });
            Ticking::in_background("host-power-schedule", Duration::from_secs(60), move || HostPower::of(&app).tick());
        })?;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn at(weekday: i64, minute: i64) -> ClockReading {
        ClockReading { weekday, minute, epoch: 0 }
    }

    #[test]
    fn a_schedule_is_cleaned_and_checked() {
        let schedule =
            CellSchedule::normalize(&json!({"enabled": true, "start": "9:05", "stop": "10:00", "days": [6, 0, 9, 0]})).unwrap();
        assert_eq!(schedule, json!({"enabled": true, "start": "09:05", "stop": "10:00", "days": [0, 6]}));
        assert!(CellSchedule::normalize(&json!({"enabled": true, "start": "10:00", "stop": "10:00"})).is_err());
        assert!(CellSchedule::normalize(&json!({"start": "25:00"})).is_err());
        assert!(CellSchedule::normalize(&json!({"start": "soon"})).is_err());
        assert!(CellSchedule::normalize(&json!({"days": ["x"]})).is_err());
    }

    #[test]
    fn a_window_across_midnight_belongs_to_the_day_it_started() {
        let night = json!({"start": "22:00", "stop": "08:00", "days": [0]});
        assert!(CellSchedule::in_window(&night, at(0, 23 * 60)));
        assert!(CellSchedule::in_window(&night, at(1, 7 * 60)));
        assert!(!CellSchedule::in_window(&night, at(1, 23 * 60)));
        assert!(!CellSchedule::in_window(&night, at(0, 7 * 60)));
        let day = json!({"start": "09:00", "stop": "17:00"});
        assert!(CellSchedule::in_window(&day, at(3, 10 * 60)));
        assert!(!CellSchedule::in_window(&day, at(3, 8 * 60)));
        assert!(!CellSchedule::in_window(&json!({"start": "09:00", "stop": "09:00"}), at(3, 9 * 60)));
    }

    #[test]
    fn the_next_window_is_counted_in_minutes() {
        let schedule = json!({"start": "22:00", "stop": "08:00", "days": [1]});
        assert_eq!(CellSchedule::minutes_to_window(&schedule, at(1, 21 * 60)), Some(60));
        assert_eq!(CellSchedule::minutes_to_window(&schedule, at(0, 22 * 60)), Some(1440));
        assert_eq!(CellSchedule::minutes_to_window(&schedule, at(1, 23 * 60)), Some(7 * 1440 - 60));
        assert_eq!(CellSchedule::minutes_to_window(&json!({"start": "01:00", "stop": "01:00"}), at(0, 0)), None);
    }
}
