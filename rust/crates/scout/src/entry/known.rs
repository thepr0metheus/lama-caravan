//! The cells the controller keeps for this machine, as its answer to a heartbeat says them, by their own names. A cell this scout has not started since its own start is then a model of its machine too,
//! stopped: on 2026-10-25 the entry named 8 of the 17 ports the controller's pools led to. `None` until a controller has said them: not knowing the cells is not "no cells". What the network says is checked:
//! a cell named in no cell's words, a field that is no text is left out. A cell is said with no port: it holds one only while it runs (Papyrus `caravan-scout-port-lease`).

use crate::entry::names::ModelName;
use crate::state::ScoutState;
use rules::{CellId, Coerce};
use serde_json::{Map, Value, json};
use std::collections::BTreeMap;
use std::sync::Arc;

/// One cell as the controller said it.
#[derive(Debug, Clone, PartialEq)]
pub struct KnownCell {
    /// The settings its model's name is made of.
    pub config: Value,
    /// Where its model lies.
    pub model_path: String,
}

impl KnownCell {
    /// What its settings call it now; `id` names it when nothing else does.
    pub fn name(&self, id: &str) -> String {
        ModelName::of(Some(&self.config), &self.model_path, id)
    }
}

/// The list.
pub struct KnownCells {
    state: Arc<ScoutState>,
}

impl KnownCells {
    const KEY: &'static str = "knownCells";
    const MAX: usize = 500;
    const FIELDS: [&'static str; 6] = ["MODEL_NAME", "ALIAS", "RUNNER", "WHISPER_MODEL", "MOONSHINE_MODEL", "MODEL_FILE"];
    const FIELD_LETTERS: usize = 400;
    const PATH_LETTERS: usize = 1000;

    /// The list of this state.
    pub fn new(state: Arc<ScoutState>) -> Self {
        Self { state }
    }

    /// What a controller said, or `None` when it said no list. A cell is named by its `id`; a list of before named ports, and is
    /// read as no list: its cells come again with the controller's next answer, by their names.
    pub fn clean(raw: Option<&Value>) -> Option<BTreeMap<String, KnownCell>> {
        let list = raw?.as_array()?;
        if list.iter().any(|item| item.get("id").is_none() && item.get("port").is_some()) {
            return None;
        }
        let mut out = BTreeMap::new();
        for item in list.iter().take(Self::MAX) {
            let Some(id) = item.get("id").filter(|id| id.is_string()).and_then(CellId::read) else {
                continue;
            };
            let mut named = Map::new();
            for (key, value) in item.get("config").and_then(Value::as_object).into_iter().flatten() {
                let readable = value.is_string() || value.as_i64().is_some();
                if readable && Self::FIELDS.contains(&key.as_str()) {
                    named.insert(key.clone(), json!(Coerce::first_letters(&Coerce::text(Some(value)), Self::FIELD_LETTERS)));
                }
            }
            let path = item
                .get("modelPath")
                .and_then(Value::as_str)
                .map_or("", |path| Coerce::first_letters(path, Self::PATH_LETTERS))
                .to_string();
            out.insert(id, KnownCell { config: Value::Object(named), model_path: path });
        }
        Some(out)
    }

    /// Keeps the cells a controller's answer to a heartbeat says; an answer that says none changes nothing.
    pub fn take(&self, answer: &Value) {
        let Some(cells) = Self::clean(answer.get("cells")) else {
            return;
        };
        let rows: Vec<Value> =
            cells.iter().map(|(id, cell)| json!({"id": id, "config": cell.config, "modelPath": cell.model_path})).collect();
        self.state.change(|doc| doc.insert(Self::KEY.to_string(), Value::Array(rows)));
    }

    /// Unpairing forgets them with the controller.
    pub fn forget(&self) {
        if self.state.get(Self::KEY).is_some() {
            self.state.change(|doc| doc.remove(Self::KEY));
        }
    }

    /// The cells by name, when a controller has said them.
    pub fn cells(&self) -> Option<BTreeMap<String, KnownCell>> {
        Self::clean(self.state.get(Self::KEY).as_ref())
    }

    /// What the controller's settings call the cell's model now, "" when it does not keep the cell.
    pub fn name(&self, id: &str) -> String {
        // absent-ok: "" says the controller does not keep the cell.
        self.cells().and_then(|cells| cells.get(id).map(|cell| cell.name(id))).unwrap_or_default()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn what_the_network_says_is_checked() {
        let said = json!([
            {"id": "c22001", "config": {"MODEL_NAME": "m", "SECRET": "x", "ALIAS": true, "RUNNER": 3}, "modelPath": "a/b.gguf"},
            {"id": 22002},
            {"id": "x"},
            {"id": true},
            "text",
            {"id": "c3f9a02b1", "config": [1], "modelPath": 5},
        ]);
        let cells = KnownCells::clean(Some(&said)).unwrap();
        assert_eq!(cells.keys().cloned().collect::<Vec<_>>(), ["c22001", "c3f9a02b1"]);
        assert_eq!(cells.get("c22001").unwrap().config, json!({"MODEL_NAME": "m", "RUNNER": "3"}));
        assert_eq!(cells.get("c3f9a02b1").unwrap().model_path, "");
        assert_eq!(KnownCells::clean(Some(&json!({"no": "list"}))), None);
        assert_eq!(KnownCells::clean(None), None);
        // Negative: a list of before, by port, is no list — not a list of cells named by numbers.
        assert_eq!(KnownCells::clean(Some(&json!([{"port": 22001, "config": {}}]))), None);
    }
}
