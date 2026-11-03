//! The scout's heartbeat to its controller: one beat is the report POSTed to `<controllerUrl>/api/topology/client-heartbeat`; the loop beats forever; pairing, which the CONTROLLER does, from its board, points the scout at it and beats once to show whether that works; unpairing lets go. Every outcome is written to `state.json`. The controller's answer names the cells it keeps for this machine: they are kept for the entry's list of models, and forgotten with the controller.

use crate::cells::Cells;
use crate::config::ScoutConfig;
use crate::entry::known::KnownCells;
use crate::errors::AppError;
use crate::http_client::HttpClient;
use crate::log::Log;
use crate::report::Report;
use crate::state::ScoutState;
use os::clock::Clock;
use rules::{Coerce, PythonJson};
use serde_json::{Value, json};
use std::sync::Arc;
use std::time::Duration;

/// The heartbeat.
pub struct Heartbeat {
    config: Arc<ScoutConfig>,
    state: Arc<ScoutState>,
    report: Arc<Report>,
    cells: Arc<Cells>,
    known: Arc<KnownCells>,
    http: Arc<HttpClient>,
    clock: Arc<dyn Clock>,
}

impl Heartbeat {
    const PATH: &'static str = "/api/topology/client-heartbeat";
    const TIMEOUT: Duration = Duration::from_secs(5);
    /// The phases of a cell on its way up: a beat comes sooner, and a restart of the scout would cut a copy in progress.
    pub const STARTING_PHASES: [&'static str; 4] = ["resolving", "downloading", "loading", "warming"];

    /// The heartbeat of this scout.
    pub fn new(
        config: Arc<ScoutConfig>,
        state: Arc<ScoutState>,
        report: Arc<Report>,
        cells: Arc<Cells>,
        known: Arc<KnownCells>,
        http: Arc<HttpClient>,
        clock: Arc<dyn Clock>,
    ) -> Self {
        Self { config, state, report, cells, known, http, clock }
    }

    fn record(&self, status: &Value) {
        self.state.change(|doc| doc.insert("heartbeat".to_string(), status.clone()));
    }

    fn post(&self, url: &str, payload: &Value, token: &str) -> Result<Value, String> {
        let mut fields = vec![("Content-Type", "application/json".to_string())];
        if !token.is_empty() {
            fields.push(("X-Caravan-Token", token.to_string()));
        }
        let answer = self
            .http
            .ask("POST", url, &fields, PythonJson::spaced(payload).as_bytes(), Self::TIMEOUT)
            .map_err(|error| error.to_string())?;
        let raw = answer.text(64 << 20).map_err(|error| error.to_string())?;
        if raw.is_empty() {
            return Ok(json!({"ok": true}));
        }
        serde_json::from_slice(&raw).map_err(|error| error.to_string())
    }

    /// One beat: the report POSTed to the controller; its answer.
    pub fn once(&self) -> Result<Value, AppError> {
        let controller = self.config.text("controllerUrl");
        let controller = controller.trim_end_matches('/');
        if controller.is_empty() {
            return Err(AppError::new("controllerUrl is required"));
        }
        let url = format!("{controller}{}", Self::PATH);
        let answer =
            self.post(&url, &self.report.heartbeat(), &self.config.token()).map_err(|words| AppError::with_status(words, 500))?;
        self.known.take(&answer);
        Ok(answer)
    }

    fn outcome(&self) -> Value {
        let started = self.clock.epoch() as i64;
        match self.once() {
            Ok(result) => json!({"state": "ok", "lastAt": started, "result": result}),
            Err(error) => json!({"state": "error", "lastAt": started, "error": error.message}),
        }
    }

    /// One turn of the loop: beats, writes the outcome down, and says how long to rest. A scout nobody has paired yet has nobody to beat to: it records that it waits, rather than an error every minute. A short rest during a start, so that the admin UI receives download and loading progress in near-real-time.
    pub fn turn(&self) -> Duration {
        const DURING_A_START: u64 = 5;
        const USUAL: i64 = 60;
        let status =
            if Coerce::truthy(self.config.get("controllerUrl").as_ref()) { self.outcome() } else { json!({"state": "unpaired"}) };
        self.record(&status);
        let starting =
            self.cells.views().iter().any(|view| {
                view.get("phase").and_then(Value::as_str).is_some_and(|phase| Self::STARTING_PHASES.contains(&phase))
            });
        if starting {
            return Duration::from_secs(DURING_A_START);
        }
        let said = self
            .config
            .get("heartbeatIntervalSeconds")
            .filter(|said| Coerce::truthy(Some(said)))
            .and_then(|said| Coerce::int(&said))
            .unwrap_or(USUAL);
        Duration::from_secs(u64::try_from(said).unwrap_or(USUAL as u64))
    }

    /// Whether a pairing may bring a fleet token this scout does not hold. When the controller's token is rotated, a paired scout still holds the old one, and a pairing bringing the new one was checked against the old one and refused. A new token is taken only for the SAME controller, and only after that controller accepts a heartbeat carrying it: whoever brings it knows the controller's current token, which is what the gate asks for.
    pub fn takes_new_token(&self, raw_url: &str, raw_token: &str) -> bool {
        let token = Coerce::strip(raw_token);
        let current = self.config.text("controllerUrl");
        if token.is_empty() || current.is_empty() {
            return false;
        }
        let (Ok(said), Ok(address)) = (ScoutConfig::controller_address(raw_url), ScoutConfig::controller_address(&current))
        else {
            return false;
        };
        if said != address || self.post(&format!("{address}{}", Self::PATH), &self.report.heartbeat(), token).is_err() {
            return false;
        }
        Log::line("[pairing] the controller accepted a fleet token this scout did not hold — taking it");
        true
    }

    /// The controller lets go of this machine: the scout forgets its address and token and stops beating. Its cells keep running: stopping them is a separate request, made before this one when wanted.
    pub fn unpair(&self) -> Result<Value, AppError> {
        self.config.unpair()?;
        self.known.forget();
        self.record(&json!({"state": "unpaired"}));
        Log::line("[pairing] unpaired: the controller let go of this machine");
        Ok(json!({"ok": true}))
    }

    /// Points the scout at a controller, which calls this when it adds the scout: stores its address (and token) in `config.json` and tries one heartbeat right away, so that the controller learns at once whether the scout can reach it back.
    pub fn pair(&self, raw_url: &str, raw_token: &str) -> Result<Value, AppError> {
        let url = self.config.pair(raw_url, raw_token)?;
        let status = self.outcome();
        self.record(&status);
        Ok(json!({"ok": true, "controllerUrl": url, "heartbeat": status}))
    }
}
