//! The cells this machine starts by itself when it boots.
//!
//! An entry keeps the start request the controller last sent for its port, so that the scout starts the cell with no controller at hand. At boot, not at every scout start: the scout also restarts on an update,
//! and starting its autostart cells then would bring back a cell the operator had stopped. The machine's boot id tells the two apart. A machine that will not say which boot it is gets no autostart, and the
//! log says why: a surprise start is worse than a missing one.

use crate::cells::Cells;
use crate::cells::saved_start::SavedStart;
use crate::errors::AppError;
use crate::log::Log;
use crate::state::ScoutState;
use os::clock::Clock;
use rules::Coerce;
use serde_json::{Map, Value, json};
use std::sync::Arc;

/// The autostart's records.
pub struct Autostart {
    state: Arc<ScoutState>,
    cells: Arc<Cells>,
    clock: Arc<dyn Clock>,
}

impl Autostart {
    const KEY: &'static str = "autostart";
    const BOOT: &'static str = "autostartBoot";

    /// The autostart of these cells.
    pub fn new(state: Arc<ScoutState>, cells: Arc<Cells>, clock: Arc<dyn Clock>) -> Self {
        Self { state, cells, clock }
    }

    fn port(value: Option<&Value>) -> Result<i64, AppError> {
        value
            .and_then(Coerce::int)
            .filter(|port| (1..=65535).contains(port))
            .ok_or_else(|| AppError::new("port must be a number from 1 to 65535"))
    }

    fn entries(&self) -> Map<String, Value> {
        // absent-ok: no entries is no autostart.
        self.state.get(Self::KEY).and_then(|entries| entries.as_object().cloned()).unwrap_or_default()
    }

    fn is_port_key(key: &str) -> bool {
        !key.is_empty() && key.chars().all(char::is_numeric)
    }

    /// The ports that have it, in order.
    pub fn ports(&self) -> Vec<i64> {
        let mut ports: Vec<i64> =
            self.entries().keys().filter(|key| Self::is_port_key(key)).filter_map(|key| key.parse().ok()).collect();
        ports.sort_unstable();
        ports
    }

    /// The kept start requests by port, as a controller keeps a cell: its settings (`config`, whole: an empty value is a flag taken off), the model it names and whether its models stay cached. The scout drops
    /// a stopped cell from its report, and a controller that did not start the cell has no record of it; from these it keeps one. An entry without settings is no request, and is left out.
    pub fn requests(&self) -> Value {
        let mut out = Map::new();
        for (key, entry) in self.entries() {
            let payload = entry.get("payload").filter(|payload| payload.is_object());
            let config = payload.and_then(|payload| payload.get("config")).filter(|config| config.is_object());
            let (Some(payload), Some(config), Some(port)) =
                (payload, config, Some(&key).filter(|key| Self::is_port_key(key)).and_then(|key| key.parse::<i64>().ok()))
            else {
                continue;
            };
            let model =
                if Coerce::truthy(payload.get("modelPath")) { Coerce::text(payload.get("modelPath")) } else { String::new() };
            out.insert(
                port.to_string(),
                json!({"config": config, "modelPath": model, "cacheModels": Coerce::truthy(payload.get("cacheModels"))}),
            );
        }
        Value::Object(out)
    }

    fn entry_of(&self, payload: &Map<String, Value>, port: i64) -> Value {
        let mut request = payload.clone();
        request.insert("port".to_string(), json!(port));
        json!({"payload": request, "savedAt": self.clock.epoch() as i64})
    }

    /// Turns a cell's autostart on (with the request that starts it) or off.
    pub fn set(&self, port: Option<&Value>, enabled: bool, payload: Option<&Value>) -> Result<Value, AppError> {
        let port = Self::port(port)?;
        let request = payload.and_then(Value::as_object).filter(|payload| !payload.is_empty());
        if enabled && request.is_none() {
            return Err(AppError::new("the start request is required to turn autostart on"));
        }
        let mut entries = self.entries();
        match request.filter(|_| enabled) {
            Some(request) => {
                entries.insert(port.to_string(), self.entry_of(request, port));
            }
            None => {
                entries.remove(&port.to_string());
            }
        }
        self.state.change(|doc| doc.insert(Self::KEY.to_string(), Value::Object(entries)));
        Ok(json!({"ok": true, "port": port, "autostart": self.ports()}))
    }

    /// A cell with autostart on was started: keeps the request it was started with, so that the next boot starts what runs now, not what ran then.
    pub fn refresh(&self, port: Option<&Value>, payload: &Value) {
        let (Ok(port), Some(request)) = (Self::port(port), payload.as_object()) else {
            return;
        };
        let mut entries = self.entries();
        if entries.contains_key(&port.to_string()) {
            entries.insert(port.to_string(), self.entry_of(request, port));
            self.state.change(|doc| doc.insert(Self::KEY.to_string(), Value::Object(entries)));
        }
    }

    /// Starts the autostart cells, on the first scout start of a boot only. The ports it started.
    pub fn start_all(&self) -> Vec<i64> {
        let boot = self.cells.machine.boot_id();
        if boot.is_empty() {
            Log::line("[autostart] this machine does not say which boot it is — not starting anything");
            return Vec::new();
        }
        if self.state.get(Self::BOOT).as_ref().and_then(Value::as_str) == Some(boot.as_str()) {
            return Vec::new();
        }
        self.state.change(|doc| doc.insert(Self::BOOT.to_string(), json!(boot)));
        let entries = self.entries();
        let mut started = Vec::new();
        for port in self.ports() {
            if self.cells.table.at(port).process.status().get("running") == Some(&Value::Bool(true)) {
                Log::line(&format!("[autostart] :{port} is running already"));
                continue;
            }
            // The settings are the controller's: what was saved while this machine was off counts. A controller that does not answer yet leaves the request kept here.
            let request = match self.cells.saved.of(port) {
                SavedStart::Request(request) => request,
                SavedStart::NoCell => {
                    Log::line(&format!("[autostart] :{port} is no cell of the controller any more — not started, and not kept"));
                    let forgotten = self.set(Some(&json!(port)), false, None);
                    drop(forgotten);
                    continue;
                }
                SavedStart::NotKnown => entries
                    .get(&port.to_string())
                    .and_then(|entry| entry.get("payload"))
                    .and_then(Value::as_object)
                    .cloned()
                    // absent-ok: an entry of no request starts what `start` refuses, and that is said below.
                    .unwrap_or_default(),
            };
            match Cells::start(&self.cells, request) {
                Ok(result) if result.get("ok") == Some(&Value::Bool(true)) => {
                    started.push(port);
                    Log::line(&format!("[autostart] :{port} started"));
                }
                Ok(result) => Log::line(&format!("[autostart] :{port} did not start: {}", Coerce::text(result.get("error")))),
                Err(error) => Log::line(&format!("[autostart] :{port} did not start: {error}")),
            }
        }
        started
    }
}
