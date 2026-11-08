//! The cells this machine starts by itself when it boots.
//!
//! An entry keeps the start request the controller last sent for its cell, by the cell's own name, so that the scout starts the cell with no controller at hand. At boot, not at every scout start: the scout also
//! restarts on an update, and starting its autostart cells then would bring back a cell the operator had stopped. The machine's boot id tells the two apart. A machine that will not say which boot it is gets no
//! autostart, and the log says why: a surprise start is worse than a missing one. A start leases the cell's port as any start does: an entry keeps none.

use crate::cells::Cells;
use crate::cells::saved_start::SavedStart;
use crate::cells::table::CellTable;
use crate::errors::AppError;
use crate::log::Log;
use crate::state::ScoutState;
use os::clock::Clock;
use rules::{CellId, Coerce};
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

    fn entries(&self) -> Map<String, Value> {
        // absent-ok: no entries is no autostart.
        self.state.get(Self::KEY).and_then(|entries| entries.as_object().cloned()).unwrap_or_default()
    }

    /// The cells that have it, by name, in order. A key that is no cell's name is no entry.
    pub fn cells(&self) -> Vec<String> {
        let mut ids: Vec<String> = self.entries().keys().filter(|key| CellId::is_name(key)).cloned().collect();
        ids.sort_unstable();
        ids
    }

    /// The kept start requests by cell, as a controller keeps a cell: its settings (`config`, whole: an empty value is a flag taken off), the model it names and whether its models stay cached. The scout drops
    /// a stopped cell from its report, and a controller that did not start the cell has no record of it; from these it keeps one. An entry without settings is no request, and is left out.
    pub fn requests(&self) -> Value {
        let mut out = Map::new();
        for (key, entry) in self.entries().into_iter().filter(|(key, _)| CellId::is_name(key)) {
            let payload = entry.get("payload").filter(|payload| payload.is_object());
            let config = payload.and_then(|payload| payload.get("config")).filter(|config| config.is_object());
            let (Some(payload), Some(config)) = (payload, config) else {
                continue;
            };
            let model =
                if Coerce::truthy(payload.get("modelPath")) { Coerce::text(payload.get("modelPath")) } else { String::new() };
            out.insert(
                key,
                json!({"config": config, "modelPath": model, "cacheModels": Coerce::truthy(payload.get("cacheModels"))}),
            );
        }
        Value::Object(out)
    }

    /// The entry kept for a request of cell `id`: the request names its cell, and no port — a start leases one.
    fn entry_of(&self, payload: &Map<String, Value>, id: &str) -> Value {
        let mut request = payload.clone();
        request.insert("cellId".to_string(), json!(id));
        request.remove("port");
        if let Some(Value::Object(config)) = request.get_mut("config") {
            config.remove("PORT");
        }
        json!({"payload": request, "savedAt": self.clock.epoch() as i64})
    }

    /// Turns a cell's autostart on (with the request that starts it) or off.
    pub fn set(&self, cell: Option<&Value>, enabled: bool, payload: Option<&Value>) -> Result<Value, AppError> {
        let id = CellTable::named(cell)?;
        let request = payload.and_then(Value::as_object).filter(|payload| !payload.is_empty());
        if enabled && request.is_none() {
            return Err(AppError::new("the start request is required to turn autostart on"));
        }
        let mut entries = self.entries();
        match request.filter(|_| enabled) {
            Some(request) => {
                entries.insert(id.clone(), self.entry_of(request, &id));
            }
            None => {
                entries.remove(&id);
            }
        }
        self.state.change(|doc| doc.insert(Self::KEY.to_string(), Value::Object(entries)));
        Ok(json!({"ok": true, "cellId": id, "autostart": self.cells()}))
    }

    /// A cell with autostart on was started: keeps the request it was started with, so that the next boot starts what runs now, not what ran then.
    pub fn refresh(&self, cell: Option<&Value>, payload: &Value) {
        let (Some(id), Some(request)) = (cell.and_then(CellId::read), payload.as_object()) else {
            return;
        };
        let mut entries = self.entries();
        if entries.contains_key(&id) {
            entries.insert(id.clone(), self.entry_of(request, &id));
            self.state.change(|doc| doc.insert(Self::KEY.to_string(), Value::Object(entries)));
        }
    }

    /// Starts the autostart cells, on the first scout start of a boot only. The cells it started.
    pub fn start_all(&self) -> Vec<String> {
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
        for id in self.cells() {
            if self.cells.table.find(&id).is_some_and(|cell| cell.process.status().get("running") == Some(&Value::Bool(true))) {
                Log::line(&format!("[autostart] {id} is running already"));
                continue;
            }
            // The settings are the controller's: what was saved while this machine was off counts. A controller that does not answer yet leaves the request kept here.
            let request = match self.cells.saved.of(&id) {
                SavedStart::Request(request) => request,
                SavedStart::NoCell => {
                    Log::line(&format!("[autostart] {id} is no cell of the controller any more — not started, and not kept"));
                    let forgotten = self.set(Some(&json!(id)), false, None);
                    drop(forgotten);
                    continue;
                }
                SavedStart::NotKnown => entries
                    .get(&id)
                    .and_then(|entry| entry.get("payload"))
                    .and_then(Value::as_object)
                    .cloned()
                    // absent-ok: an entry of no request starts what `start` refuses, and that is said below.
                    .unwrap_or_default(),
            };
            match Cells::start(&self.cells, request) {
                Ok(result) if result.get("ok") == Some(&Value::Bool(true)) => {
                    started.push(id.clone());
                    Log::line(&format!("[autostart] {id} started"));
                }
                Ok(result) => Log::line(&format!("[autostart] {id} did not start: {}", Coerce::text(result.get("error")))),
                Err(error) => Log::line(&format!("[autostart] {id} did not start: {error}")),
            }
        }
        started
    }
}
