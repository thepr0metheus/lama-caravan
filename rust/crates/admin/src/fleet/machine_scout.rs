//! The scout of the machine this controller runs on, its hands there.

use super::controller_machine::ControllerMachine;
use super::scout::ScoutCall;
use crate::app::App;
use crate::store::topology::Topology;
use rules::{AppError, Coerce};
use serde_json::{Value, json};
use std::collections::BTreeMap;
use std::sync::{Mutex, PoisonError};

/// What failed a moment ago: a scout that does not answer is not asked again at once, or a page that reads it every second would wait each time.
#[derive(Default)]
pub struct MachineScoutMemory {
    failed: Mutex<BTreeMap<String, (f64, Value)>>,
}

/// The scout on the controller's own machine, which does what the controller once did there.
pub struct MachineScout<'app> {
    app: &'app App,
}

impl<'app> MachineScout<'app> {
    /// What is said while no scout runs on this machine.
    pub const NO_SCOUT: &'static str = "there is no scout on the controller's machine — add one (Machines → Add scout) to read and act on this machine from the board";
    const FAIL_PAUSE: f64 = 10.0;

    /// The scout of `app`.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    /// The id of the scout on this controller's machine; empty for none.
    pub fn host_id(&self) -> String {
        let here = ControllerMachine::of(self.app);
        self.app.admin.change(|doc| here.host_id(Topology::of(doc).hosts().values()))
    }

    /// The host record of this controller's machine: what its scout last reported.
    pub fn host(&self) -> Value {
        let id = self.host_id();
        if id.is_empty() {
            return json!({});
        }
        self.app.admin.change(|doc| Topology::of(doc).hosts().get(&id).cloned()).unwrap_or_else(|| json!({}))
    }

    /// The machine's scout, ready to be called.
    pub fn scout(&self) -> Result<ScoutCall<'app>, AppError> {
        let id = self.host_id();
        if id.is_empty() {
            return Err(AppError::with_status(Self::NO_SCOUT, 409));
        }
        ScoutCall::of_host(self.app, &id)
    }

    /// The scout's answer, or `{ok: false, error}`, remembered a moment when it failed.
    pub fn read(&self, path: &str, timeout: u64) -> Value {
        let key = path.split('?').next().unwrap_or(path).to_string();
        let now = self.app.clock.monotonic();
        let memory = &self.app.machine_scout;
        {
            let failed = memory.failed.lock().unwrap_or_else(PoisonError::into_inner);
            if let Some((_, said)) = failed.get(&key).filter(|(at, _)| now - *at < Self::FAIL_PAUSE) {
                return said.clone();
            }
        }
        let answer = match self.scout() {
            Ok(scout) => scout.read(path, timeout),
            Err(error) => json!({"ok": false, "error": error.message}),
        };
        let unusable = !answer.is_object() || (answer.get("ok") == Some(&json!(false)) && answer.get("error").is_some());
        let mut failed = memory.failed.lock().unwrap_or_else(PoisonError::into_inner);
        if unusable {
            let said =
                if answer.is_object() { answer.clone() } else { json!({"ok": false, "error": Coerce::str_of(Some(&answer))}) };
            failed.insert(key, (now, said));
        } else {
            failed.remove(&key);
        }
        answer
    }

    /// Asks the scout to act.
    pub fn post(&self, path: &str, payload: &Value, timeout: u64) -> Result<Value, AppError> {
        self.scout()?.post(path, payload, timeout)
    }
}
