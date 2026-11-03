//! Reboot or power off a fleet host from the board, and when it goes off by itself.

use super::controller_machine::ControllerMachine;
use super::machine_scout::MachineScout;
use super::scout::ScoutCall;
use crate::app::App;
use crate::common::daytime::Daytime;
use crate::paths::HostIds;
use crate::store::topology::Topology;
use os::LocalTime;
use plumbing::log::Log;
use rules::{AppError, Coerce};
use serde_json::{Map, Value, json};

/// The power of the machines with a scout.
pub struct HostPower<'app> {
    app: &'app App,
}

impl<'app> HostPower<'app> {
    const ACTIONS: [&'static str; 2] = ["reboot", "poweroff"];

    /// The power of `app`.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    /// The named host rebooted or powered off through its scout: the controller's own machine through the scout on it.
    pub fn act(&self, body: &Value, action: &str) -> Result<Value, AppError> {
        if !Self::ACTIONS.contains(&action) {
            return Err(AppError::new(format!("unknown action: {action}")));
        }
        let mut host_id = Coerce::stripped(body.get("hostId"));
        if host_id.is_empty() {
            return Err(AppError::new("hostId is required"));
        }
        if HostIds::is_controller(&host_id) {
            host_id = MachineScout::of(self.app).host_id();
            if host_id.is_empty() {
                return Err(AppError::with_status(MachineScout::NO_SCOUT, 409));
            }
        }
        let result = ScoutCall::of_host(self.app, &host_id)?.post(&format!("/api/host/{action}"), &json!({}), 8)?;
        let ok = result.get("ok").is_none_or(|said| Coerce::truthy(Some(said)));
        Ok(json!({"ok": ok, "hostId": host_id, "action": action, "result": result, "at": self.app.now_whole()}))
    }

    /// A schedule as the record keeps it.
    fn normalized(payload: &Value) -> Result<Value, AppError> {
        if !payload.is_object() {
            return Err(AppError::new("schedule must be an object"));
        }
        Ok(json!({
            "enabled": Coerce::truthy(payload.get("enabled")),
            "at": Daytime::hhmm(payload.get("at"), "03:00")?,
            "daily": payload.get("daily").is_none_or(|said| Coerce::truthy(Some(said))),
        }))
    }

    fn minutes(at: &str) -> i64 {
        let (hour, minute) = at.split_once(':').unwrap_or(("3", "0"));
        // absent-ok: a stored time is one `Daytime::hhmm` wrote.
        hour.parse::<i64>().unwrap_or(0) * 60 + minute.parse::<i64>().unwrap_or(0)
    }

    /// A machine's schedule from now on. A time already past today waits for tomorrow.
    pub fn set_schedule(&self, body: &Value) -> Result<Value, AppError> {
        let host_id = Coerce::stripped(body.get("hostId"));
        if host_id.is_empty() {
            return Err(AppError::new("hostId is required"));
        }
        let mut schedule =
            Self::normalized(body.get("schedule").filter(|said| Coerce::truthy(Some(*said))).unwrap_or(&json!({})))?;
        if Coerce::truthy(schedule.get("enabled"))
            && let Some(now) = LocalTime::of(self.app.now_whole())
            && Self::minutes(&Coerce::text(schedule.get("at"))) <= i64::from(now.hour) * 60 + i64::from(now.minute)
        {
            Coerce::put(&mut schedule, "lastFired", json!(now.date()));
        }
        self.app.admin.saving(|doc| {
            Topology::of(doc).power_schedules().insert(host_id.clone(), schedule.clone());
        });
        Ok(json!({"ok": true, "hostId": host_id, "schedule": schedule}))
    }

    /// `{host id: schedule}`.
    pub fn schedules(&self) -> Map<String, Value> {
        self.app.admin.change(|doc| Topology::of(doc).power_schedules().clone())
    }

    /// A schedule keyed to the controller's own id moved onto its machine's node.
    fn adopt_controller_schedule(&self, schedules: &mut Map<String, Value>) -> bool {
        let keys: Vec<String> = schedules.keys().filter(|key| HostIds::is_controller(key)).cloned().collect();
        if keys.is_empty() {
            return false;
        }
        let here = ControllerMachine::of(self.app);
        let target = self.app.admin.change(|doc| here.host_id(Topology::of(doc).hosts().values()));
        if target.is_empty() {
            return false;
        }
        for key in keys {
            let Some(schedule) = schedules.shift_remove(&key) else {
                continue;
            };
            if schedules.contains_key(&target) {
                Log::line(&format!("[host-power-schedule] {key}: dropped — {target} has its own schedule"));
            } else {
                schedules.insert(target.clone(), schedule);
                Log::line(&format!("[host-power-schedule] {key}: moved to {target}, the controller's machine"));
            }
        }
        true
    }

    /// Fires any host poweroff whose minute has arrived.
    pub fn tick(&self) {
        let mut schedules = self.schedules();
        if schedules.is_empty() {
            return;
        }
        let Some(now) = LocalTime::of(self.app.now_whole()) else {
            return;
        };
        let mut changed = self.adopt_controller_schedule(&mut schedules);
        let today = now.date();
        let current = i64::from(now.hour) * 60 + i64::from(now.minute);
        let mut firing = Vec::new();
        for (host_id, schedule) in &mut schedules {
            if !schedule.is_object()
                || !Coerce::truthy(schedule.get("enabled"))
                || Coerce::text(schedule.get("lastFired")) == today
            {
                continue;
            }
            let at = {
                let said = Coerce::text(schedule.get("at"));
                if said.is_empty() { "03:00".to_string() } else { said }
            };
            let minute = Self::minutes(&at);
            if !(minute <= current && current < (minute + 3).min(24 * 60)) {
                continue;
            }
            Coerce::put(schedule, "lastFired", json!(today));
            if !Coerce::truthy(schedule.get("daily")) {
                Coerce::put(schedule, "enabled", json!(false));
            }
            changed = true;
            firing.push((host_id.clone(), at));
        }
        if changed {
            self.app.admin.saving(|doc| {
                *Topology::of(doc).power_schedules() = schedules;
            });
        }
        for (host_id, at) in firing {
            Log::line(&format!("[host-power-schedule] {host_id}: poweroff at {at}"));
            if let Err(error) = self.act(&json!({"hostId": host_id}), "poweroff") {
                Log::line(&format!("[host-power-schedule] {host_id}: poweroff failed: {}", error.message));
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_schedule_reads_with_its_defaults() {
        let schedule = HostPower::normalized(&json!({"enabled": 1})).unwrap();
        assert_eq!(schedule, json!({"enabled": true, "at": "03:00", "daily": true}));
        assert!(HostPower::normalized(&json!(5)).is_err());
        assert_eq!(HostPower::minutes("03:10"), 190);
    }
}
