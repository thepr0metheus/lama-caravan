//! The default cells of 2026-11-05, retired: a model's numbers are a preset now, not a cell.
//!
//! From 2026-11-05 every folder of the library got a cell on every machine at each start of the controller: an ordinary slot
//! with a reserved port and one more fact, `defaultFor`, the folder it was the default for. On 2026-11-07 that was 51 of the 85
//! ports of the big machine, none of them ever started, and one of them took an `mmproj` file for its model, so the machine's entry
//! named a projector as a model. The owner's choice of that day (Papyrus `caravan-scout-port-lease`, step 1): a cell holds a
//! port only while it runs, and a model's default cell becomes a preset — the maker's numbers, which the launch builder offers
//! as a set of its own (`RunnerPresets::list`, `makers`), with no slot and no port until the operator starts a launch.
//!
//! So each such slot is looked at once, at the start. One the preset gives back whole goes: its config is the maker's numbers
//! with at most a file — the builder offers the model's files itself — and nothing of the operator's is on it. What it was is
//! kept under `defaultCellsRetired` in the board's state, so nothing is lost. One that holds more — a value the operator
//! changed, a note, a schedule, a name of its own — is the operator's cell now: it stays, and only the mark goes. Run at every
//! start, it finds nothing to do after the first: no code makes the mark any more.

use super::cell_outputs::CellOutputs;
use crate::app::App;
use crate::models::defaults::ModelDefaults;
use crate::store::admin::AdminStore;
use crate::store::topology::Topology;
use rules::{AppError, Coerce};
use serde_json::{Map, Value, json};

/// The retirement of the default cells.
pub struct DefaultCellsRetired<'app> {
    app: &'app App,
}

/// A slot that carried the mark, as the retirement found it: under its cell's id since the slots were keyed so (`store/cell_ids.rs`,
/// done when the document opens, before this step).
struct Marked {
    key: String,
    host: String,
    slot: Value,
}

impl<'app> DefaultCellsRetired<'app> {
    /// The fact that made a slot a model's default cell: the folder it was the default for.
    const MARK: &'static str = "defaultFor";
    /// Where the slots that went are kept, as they were, in the topology section.
    const RECORD: &'static str = "defaultCellsRetired";
    /// What on a slot is the operator's own: a default cell that carries any of it is not given back by a preset.
    const OPERATORS: [&'static str; 3] = ["note", "schedule", "commandHistory"];

    /// The retirement over `app`.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    /// The folder a slot was the default cell of; "" for any other slot.
    fn folder(slot: &Value) -> String {
        Coerce::stripped(slot.get(Self::MARK))
    }

    /// Whether the preset of its folder gives back all the slot holds: the maker's numbers, a file at most, the names the pass gave
    /// it, and nothing the operator put on it. `cacheModels` is not the operator's here: it is a start's choice, asked again at the
    /// next start, and the record keeps it.
    fn given_back(slot: &Value) -> bool {
        let folder = Self::folder(slot);
        let mut config: Map<String, Value> = match slot.get("config") {
            Some(Value::Object(config)) => config.clone(),
            // A slot with no config held no numbers: the preset gives back what it did not hold.
            _ => Map::new(),
        };
        config.shift_remove("MODEL_FILE");
        let own = Self::OPERATORS.iter().any(|key| Coerce::truthy(slot.get(*key)));
        let named_by_pass = |key: &str| {
            let said = Coerce::stripped(slot.get(key));
            said.is_empty() || said == folder
        };
        config == ModelDefaults::values(&folder) && !own && named_by_pass("label") && named_by_pass("model")
    }

    /// The slots that carry the mark, in the order the document keeps them.
    fn marked(&self) -> Vec<Marked> {
        self.app.admin.change(|doc| {
            Topology::of(doc)
                .slots()
                .iter()
                .filter(|(_, slot)| !Self::folder(slot).is_empty())
                .map(|(key, slot)| Marked { key: key.clone(), host: Coerce::stripped(slot.get("hostId")), slot: slot.clone() })
                .collect()
        })
    }

    /// The retirement, once a start: `None` when no slot carries the mark; else the keys of the slots that went and of those kept as
    /// the operator's cells, and the pools whose rows lost a cable with them.
    pub fn migrate(app: &'app App) -> Result<Option<Value>, AppError> {
        Self::of(app).run()
    }

    fn run(&self) -> Result<Option<Value>, AppError> {
        let marked = self.marked();
        if marked.is_empty() {
            return Ok(None);
        }
        let (gone, kept): (Vec<Marked>, Vec<Marked>) = marked.into_iter().partition(|cell| Self::given_back(&cell.slot));
        let at = self.app.now_whole();
        // One write for all of it: the record of what goes, then the slots that go, and the mark off the ones that stay. The record is
        // written before anything goes, in the same change, so a slot is never gone without its copy.
        self.app.admin.saving(|doc| {
            let topology = AdminStore::topology(doc);
            let record = topology.entry(Self::RECORD).or_insert_with(|| json!({"slots": {}}));
            Coerce::put(record, "at", json!(at));
            if !record.get("slots").is_some_and(Value::is_object) {
                Coerce::put(record, "slots", json!({}));
            }
            if let Some(slots) = record.get_mut("slots").and_then(Value::as_object_mut) {
                for cell in &gone {
                    slots.insert(cell.key.clone(), cell.slot.clone());
                }
            }
            let mut view = Topology::of(doc);
            let slots = view.slots();
            for cell in &gone {
                slots.shift_remove(&cell.key);
            }
            for cell in &kept {
                if let Some(slot) = slots.get_mut(&cell.key) {
                    Coerce::take(slot, Self::MARK);
                }
            }
        });
        // A cell that goes takes its cables with it, as a deletion does (`ServerCells::delete_slot`).
        let mut pools: Vec<Value> = Vec::new();
        for cell in &gone {
            let followed = CellOutputs::of(self.app).dropped(&cell.key, Some(&cell.host));
            for pool in followed.get("pools").and_then(Value::as_array).into_iter().flatten() {
                if !pools.contains(pool) {
                    pools.push(pool.clone());
                }
            }
        }
        let keys = |cells: &[Marked]| cells.iter().map(|cell| json!(cell.key)).collect::<Vec<Value>>();
        Ok(Some(json!({"gone": keys(&gone), "kept": keys(&kept), "pools": pools})))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::fleet::server_cells::ServerCells;

    #[test]
    fn a_slot_is_given_back_only_when_the_preset_holds_all_of_it() {
        // The maker's numbers of a folder the table names, with the file the pass found, and the names the pass gave it.
        let stated = json!({"defaultFor": "gemma-4-12B-it-GGUF", "label": "gemma-4-12B-it-GGUF", "model": "gemma-4-12B-it-GGUF",
            "config": {"TEMPERATURE": "1.0", "TOP_P": "0.95", "TOP_K": "64", "MODEL_FILE": "gemma-4-12B-it-GGUF/a/Q4/g.gguf"}});
        assert!(DefaultCellsRetired::given_back(&stated));
        // A folder the table does not name, with nothing in its config — 29 of the 51 on 2026-11-07 — and one that took a projector.
        assert!(DefaultCellsRetired::given_back(&json!({"defaultFor": "Kimi-K2.7-Code-GGUF", "config": {}})));
        assert!(DefaultCellsRetired::given_back(
            &json!({"defaultFor": "X-GGUF", "config": {"MODEL_FILE": "X-GGUF/mmproj-F16.gguf"}})
        ));
        assert!(DefaultCellsRetired::given_back(&json!({"defaultFor": "Kimi-K2.7-Code-GGUF", "cacheModels": true})));

        // Negative: a value the operator changed, a field more, a note, a schedule, a name of their own — the operator's cell now.
        let changed =
            json!({"defaultFor": "gemma-4-12B-it-GGUF", "config": {"TEMPERATURE": "0.7", "TOP_P": "0.95", "TOP_K": "64"}});
        let more = json!({"defaultFor": "gemma-4-12B-it-GGUF", "config": {"TEMPERATURE": "1.0", "TOP_P": "0.95", "TOP_K": "64", "CTX_SIZE": "8192"}});
        let noted = json!({"defaultFor": "Kimi-K2.7-Code-GGUF", "note": "for the coder"});
        let scheduled = json!({"defaultFor": "Kimi-K2.7-Code-GGUF", "schedule": {"enabled": true}});
        let renamed = json!({"defaultFor": "Kimi-K2.7-Code-GGUF", "label": "my coder"});
        for slot in [changed, more, noted, scheduled, renamed] {
            assert!(!DefaultCellsRetired::given_back(&slot), "kept: {slot}");
        }
    }

    #[test]
    fn the_retirement_keeps_what_goes_and_leaves_the_operator_s_cells() {
        let folder = crate::tests::TestFolder::new("default-cells-retired");
        let app = crate::tests::TestApp::over(&folder.path, &[]);
        let cells = ServerCells::of(&app);
        let mark = |id: &str, slot_folder: &str| {
            app.admin.saving(|doc| {
                if let Some(slot) = Topology::of(doc).find_slot(id) {
                    Coerce::put(slot, "defaultFor", json!(slot_folder));
                }
            });
        };
        cells
            .upsert_slot("alpha", "c22040", Some(&json!({"TEMPERATURE": "0.6", "TOP_P": "0.95", "TOP_K": "20"})), None, None)
            .unwrap();
        mark("c22040", "Hermes-4-70B-GGUF");
        cells.upsert_slot("alpha", "c22041", Some(&json!({"TEMPERATURE": "0.2"})), None, None).unwrap();
        mark("c22041", "Hermes-4-70B-GGUF");
        cells.upsert_slot("alpha", "c22020", Some(&json!({"MODEL_FILE": "m.gguf"})), None, None).unwrap();

        let done = DefaultCellsRetired::migrate(&app).unwrap().unwrap();
        assert_eq!(done["gone"], json!(["c22040"]));
        assert_eq!(done["kept"], json!(["c22041"]));
        let (slots, record) = app.admin.change(|doc| {
            let mut topology = Topology::of(doc);
            let slots: Vec<String> = topology.slots().keys().cloned().collect();
            (slots, topology.raw().get("defaultCellsRetired").cloned().unwrap_or(Value::Null))
        });
        assert_eq!(slots, ["c22041", "c22020"], "the given-back slot went; the operator's and the ordinary one stayed");
        assert_eq!(record["slots"]["c22040"]["config"]["TOP_K"], "20", "what went is kept as it was");
        let kept = app.admin.change(|doc| Topology::of(doc).slot("c22041"));
        assert_eq!(kept.get("defaultFor"), None, "the kept cell lost its mark");
        assert_eq!(kept["config"]["TEMPERATURE"], "0.2");

        // Negative: run again, it finds no mark and does nothing — nothing goes twice, the record is not rewritten.
        assert_eq!(DefaultCellsRetired::migrate(&app).unwrap(), None);
    }
}
