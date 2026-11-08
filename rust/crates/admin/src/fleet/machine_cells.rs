//! The cells the controller keeps for a machine, as the machine's scout is told them.

use crate::app::App;
use crate::domain::runner::RunnerRegistry;
use crate::paths::HostIds;
use rules::Coerce;
use serde_json::{Map, Value, json};

/// What a cell the controller keeps has to serve.
pub struct SlotModel;

impl SlotModel {
    fn config_of(slot: &Value) -> Map<String, Value> {
        slot.get("config").map_or_else(Map::new, Coerce::fields)
    }

    /// The model it names.
    pub fn path(app: &App, slot: &Value) -> String {
        let config = Self::config_of(slot);
        let named = app.runners.for_config(&config).model_ref(&config);
        if named.is_empty() { Coerce::text(slot.get("model")) } else { named }
    }

    /// The launch line of a command cell; empty when it renders none.
    pub fn command(app: &App, slot: &Value) -> String {
        let config = Self::config_of(slot);
        let runner = app.runners.for_config(&config);
        if !runner.row().command_path {
            return String::new();
        }
        runner.command(&config).map_or_else(|_| String::new(), |line| Coerce::strip(&line).to_string())
    }

    /// Whether it has anything to serve.
    pub fn configured(app: &App, slot: &Value) -> bool {
        !Self::path(app, slot).is_empty() || !Self::command(app, slot).is_empty()
    }
}

/// The configured cells of one machine, in the shape its scout reads.
pub struct MachineCells;

impl MachineCells {
    const NAME_FIELDS: [&'static str; 6] = ["MODEL_NAME", "ALIAS", "RUNNER", "WHISPER_MODEL", "MOONSHINE_MODEL", "MODEL_FILE"];

    /// The cells of `host_id` among `slots`, by id: what each serves, and no port — the scout leases one at a start.
    pub fn of(app: &App, slots: &Map<String, Value>, host_id: &str) -> Vec<Value> {
        let host = HostIds::canonical(host_id);
        if host.is_empty() {
            return Vec::new();
        }
        let mut cells = Vec::new();
        for (id, slot) in slots.iter().filter(|(_, slot)| slot.is_object()) {
            if HostIds::canonical(&Coerce::text(slot.get("hostId"))) != host || !SlotModel::configured(app, slot) {
                continue;
            }
            let config = SlotModel::config_of(slot);
            let mut named = Map::new();
            for key in Self::NAME_FIELDS {
                if !Coerce::stripped(config.get(key)).is_empty() {
                    named.insert(key.to_string(), json!(Coerce::str_of(config.get(key))));
                }
            }
            named.insert("RUNNER".to_string(), json!(RunnerRegistry::runner_id(&config)));
            cells.push((id.clone(), json!({"id": id, "modelPath": SlotModel::path(app, slot), "config": named})));
        }
        cells.sort_by(|a, b| a.0.cmp(&b.0));
        cells.into_iter().map(|row| row.1).collect()
    }
}
