//! Server slot and cell bookkeeping. A slot is what the board keeps of a cell, whether it runs or not: under the cell's own id
//! (`rules::CellId`), with its machine as a field and no port — the scout leases one when the cell starts and takes it back when the
//! cell stops (Papyrus `caravan-scout-port-lease`, step 2). So nothing here picks, checks or swaps a port.

use super::cell_outputs::CellOutputs;
use crate::app::App;
use crate::config::builder::CellCommand;
use crate::paths::HostIds;
use crate::store::topology::Topology;
use net::Randomness;
use plumbing::log::Log;
use rules::{AppError, CellId, Coerce};
use serde_json::{Map, Value, json};
use std::collections::BTreeSet;

mod kept;
pub use kept::KeptCells;

/// The slots of this controller.
pub struct ServerCells<'app> {
    app: &'app App,
}

impl<'app> ServerCells<'app> {
    const RUNS_NO_CELLS: &'static str =
        "the controller runs no cells — its machine's cells run through its scout, on that machine's node";
    /// How many times a new id is drawn before the draw is given up: four random bytes meet a taken name about never.
    const DRAWS: usize = 8;

    /// The slots of `app`.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    /// The cell a scout's report names: its `id`, or — from a scout of before the cells had names — its port, as that cell's name.
    /// `None` for a report that names neither.
    pub fn node_cell(node: &Value) -> Option<String> {
        node.get("id").and_then(CellId::read).or_else(|| node.get("port").and_then(CellId::read))
    }

    /// The id a cell in a request names: `cellId`; a request that names none names no cell, and the caller refuses it.
    pub fn asked_id(body: &Value) -> Result<String, AppError> {
        body.get("cellId").and_then(CellId::read).ok_or_else(|| AppError::new("cellId is required"))
    }

    /// A new cell's id: four bytes of the system's randomness, drawn again for a name already taken. A system that gives no
    /// randomness makes no cell: nothing here guesses its way around it.
    pub fn fresh_id(&self) -> Result<String, AppError> {
        for _ in 0..Self::DRAWS {
            let drawn = Randomness::bytes(4).and_then(|bytes| CellId::fresh(&bytes));
            let Some(id) = drawn else {
                return Err(AppError::with_status("the system gave no randomness for a new cell's id", 500));
            };
            if !self.app.admin.change(|doc| Topology::of(doc).has_slot(&id)) {
                return Ok(id);
            }
        }
        Err(AppError::with_status("no free id for a new cell", 500))
    }

    /// The ports the fleet's cells hold now, as the machines' reports say them: a cell holds one only while it runs or starts.
    pub fn held_ports(&self) -> BTreeSet<i64> {
        let hosts = self.app.admin.change(|doc| Topology::of(doc).hosts().clone());
        hosts
            .values()
            .flat_map(|host| host.get("llamaNodes").and_then(Value::as_array).into_iter().flatten())
            .filter_map(|node| node.get("port").and_then(Value::as_i64).filter(|port| *port > 0))
            .collect()
    }

    /// The machine of cell `id`: the one its slot names, else the one whose report names it — a cell this controller does not keep is
    /// a row of the board all the same, and its log is read as any other's. "" for a cell neither names.
    pub fn host_of(&self, id: &str) -> String {
        let kept = self.app.admin.change(|doc| Coerce::stripped(Topology::of(doc).slot(id).get("hostId")));
        if !kept.is_empty() {
            return kept;
        }
        let hosts = self.app.admin.change(|doc| Topology::of(doc).hosts().clone());
        let names = |host: &Value| {
            let nodes = host.get("llamaNodes").and_then(Value::as_array).into_iter().flatten();
            nodes.filter_map(Self::node_cell).any(|cell| cell == id)
        };
        // absent-ok: "" is how this says that no machine names the cell.
        hosts.iter().find(|(_, host)| names(host)).map(|(host_id, _)| host_id.clone()).unwrap_or_default()
    }

    /// Refuses a cell of the controller's own host id, saying why: not a slot nobody would ever start.
    pub fn refuse_controller_host(host_id: &str) -> Result<(), AppError> {
        if HostIds::is_controller(host_id) { Err(AppError::new(Self::RUNS_NO_CELLS)) } else { Ok(()) }
    }

    fn remember_old_command(slot: &mut Value, config: &Map<String, Value>, now: i64) {
        let old = slot.get("config").cloned().unwrap_or(Value::Null);
        let (old_command, new_command) = (Coerce::stripped(old.get("COMMAND")), Coerce::stripped(config.get("COMMAND")));
        if old_command.is_empty() || old_command == new_command {
            return;
        }
        let mut history: Vec<Value> = slot
            .get("commandHistory")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            .filter(|row| row.is_object() && row.get("command").and_then(Value::as_str) != Some(old_command.as_str()))
            .cloned()
            .collect();
        history.insert(
            0,
            json!({
                "command": old_command, "env": Coerce::text(old.get("ENV")), "workdir": Coerce::text(old.get("WORKDIR")),
                "healthPath": Coerce::text(old.get("HEALTH_PATH")), "ts": now,
            }),
        );
        history.truncate(10);
        Coerce::put(slot, "commandHistory", Value::Array(history));
    }

    /// A persistent slot of cell `id` on `host_id`, recorded or refreshed. A config keeps no port: the scout leases one at the start.
    pub fn upsert_slot(
        &self,
        host_id: &str,
        id: &str,
        config: Option<&Value>,
        model: Option<&Value>,
        label: Option<&Value>,
    ) -> Result<Value, AppError> {
        Self::refuse_controller_host(host_id)?;
        let now = self.app.now_whole();
        let free_form = config.and_then(Value::as_object).is_some_and(|config| CellCommand::of(self.app).is_command_cell(config));
        Ok(self.app.admin.saving(|doc| {
            let mut topology = Topology::of(doc);
            let slots = topology.slots();
            let mut slot =
                slots.get(id).filter(|slot| Coerce::truthy(Some(*slot))).cloned().unwrap_or_else(|| json!({"createdAt": now}));
            Coerce::put(&mut slot, "id", json!(id));
            Coerce::put(&mut slot, "hostId", json!(HostIds::canonical(host_id)));
            Coerce::take(&mut slot, "port");
            Coerce::put(&mut slot, "updatedAt", json!(now));
            if let Some(model) = model.filter(|model| !model.is_null()) {
                Coerce::put(&mut slot, "model", json!(Coerce::str_of(Some(model)).chars().take(300).collect::<String>()));
            }
            if let Some(label) = label.filter(|label| !label.is_null()) {
                Coerce::put(&mut slot, "label", json!(Coerce::str_of(Some(label)).chars().take(120).collect::<String>()));
            }
            if let Some(config) = config.and_then(Value::as_object) {
                if free_form {
                    Self::remember_old_command(&mut slot, config, now);
                }
                let kept: Map<String, Value> = config
                    .iter()
                    .filter(|(key, said)| !said.is_null() && key.as_str() != "PORT")
                    .map(|(key, said)| (key.clone(), said.clone()))
                    .collect();
                Coerce::put(&mut slot, "config", Value::Object(kept));
            }
            slots.insert(id.to_string(), slot.clone());
            slot
        }))
    }

    /// A person's note on a cell.
    pub fn set_note(&self, id: &str, note: Option<&Value>) -> Result<Value, AppError> {
        let note: String = Coerce::stripped(note).chars().take(280).collect();
        let note = Coerce::strip(&note).to_string();
        let now = self.app.now_whole();
        let done = self.app.admin.saving(|doc| {
            let mut topology = Topology::of(doc);
            let Some(slot) = topology.find_slot(id) else {
                return false;
            };
            if note.is_empty() {
                Coerce::take(slot, "note");
            } else {
                Coerce::put(slot, "note", json!(note));
            }
            Coerce::put(slot, "updatedAt", json!(now));
            true
        });
        if !done {
            return Err(AppError::with_status(format!("no cell {id}"), 404));
        }
        Ok(json!({"cellId": id, "note": note}))
    }

    /// The slot marked as a cell the operator made, and kept.
    pub fn mark_cell(&self, id: &str, mut slot: Value) -> Value {
        Coerce::put(&mut slot, "kind", json!("serverCell"));
        self.app.admin.saving(|doc| {
            Topology::of(doc).put_slot(id, slot.clone());
        });
        slot
    }

    /// A new cell reserved on a machine: a slot of its own id, with no port and, for an engine's cell, the engine's config.
    pub fn reserve(&self, body: &Value) -> Result<Value, AppError> {
        let host_id = Coerce::stripped(body.get("hostId"));
        if host_id.is_empty() {
            return Err(AppError::new("hostId is required"));
        }
        Self::refuse_controller_host(&host_id)?;
        let host = self.app.admin.change(|doc| Topology::of(doc).hosts().get(&HostIds::canonical(&host_id)).cloned());
        let config = super::engine_cells::EngineCellPlan::from_body(self.app, host.as_ref(), body)
            .map(|plan| plan.config())
            .transpose()?;
        let id = self.fresh_id()?;
        let slot = self.upsert_slot(&host_id, &id, config.as_ref(), None, body.get("label"))?;
        let slot = self.mark_cell(&id, slot);
        Ok(json!({"ok": true, "cell": slot}))
    }

    /// Every cell configured on machine `from` goes to machine `to`, under the ids it has.
    pub fn move_host_cells(&self, body: &Value) -> Result<Value, AppError> {
        let source = HostIds::canonical(&Coerce::stripped(body.get("from")));
        let target = HostIds::canonical(&Coerce::stripped(body.get("to")));
        if source.is_empty() || target.is_empty() {
            return Err(AppError::new("both machines are required: from and to"));
        }
        if source == target {
            return Err(AppError::new("from and to are the same machine"));
        }
        Self::refuse_controller_host(&source)?;
        Self::refuse_controller_host(&target)?;
        let now = self.app.now_whole();
        let moved = self.app.admin.change(|doc| {
            let mut topology = Topology::of(doc);
            let mut moved = Vec::new();
            for (id, slot) in topology.slots().iter_mut() {
                if slot.get("hostId").and_then(Value::as_str) != Some(source.as_str()) {
                    continue;
                }
                Coerce::put(slot, "hostId", json!(target));
                Coerce::put(slot, "updatedAt", json!(now));
                moved.push(id.clone());
            }
            moved
        });
        if moved.is_empty() {
            return Err(AppError::with_status(format!("no cells are configured on {source}"), 404));
        }
        self.app.save_admin();
        Ok(json!({"ok": true, "from": source, "to": target, "cells": moved}))
    }

    /// A cell's slot forgotten, with the cable of its model when it was that model's only copy; whether there was one.
    pub fn delete_slot(&self, id: &str) -> bool {
        let removed = self.app.admin.change(|doc| Topology::of(doc).drop_slot(id));
        let Some(slot) = removed else {
            return false;
        };
        self.app.save_admin();
        let host_id = Coerce::stripped(slot.get("hostId"));
        let followed = CellOutputs::of(self.app).dropped(id, Some(&host_id));
        if let Some(pools) = followed.get("pools").and_then(Value::as_array).filter(|pools| !pools.is_empty()) {
            Log::line(&format!("[cells] {id} deleted: the rows of its model's only copy left the pools {pools:?}"));
        }
        true
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_cell_is_kept_under_its_id_with_no_port() {
        let folder = crate::tests::TestFolder::new("slot-by-id");
        let app = crate::tests::TestApp::over(&folder.path, &[]);
        let cells = ServerCells::of(&app);
        let id = cells.fresh_id().unwrap();
        assert!(CellId::is_name(&id) && id.len() == 9, "c and eight hex digits: {id}");
        let slot = cells.upsert_slot("box", &id, Some(&json!({"MODEL_FILE": "m.gguf", "PORT": "22020"})), None, None).unwrap();
        assert_eq!(slot["id"], json!(id));
        assert_eq!(slot["hostId"], "box");
        assert_eq!(slot.get("port"), None, "negative: a slot holds no port");
        assert_eq!(slot["config"], json!({"MODEL_FILE": "m.gguf"}), "negative: nor does its config");
        cells.set_note(&id, Some(&json!("for the coder"))).unwrap();
        assert_eq!(app.admin.change(|doc| Topology::of(doc).slot(&id))["note"], "for the coder");
        assert_eq!(cells.host_of(&id), "box");
        app.admin.saving(|doc| {
            Topology::of(doc)
                .hosts()
                .insert("far".to_string(), json!({"llamaNodes": [{"id": "c3f9a02b1", "port": 22007}, {"port": 22008}]}));
        });
        assert_eq!(cells.host_of("c3f9a02b1"), "far", "a cell the controller does not keep: the machine whose report names it");
        assert_eq!(cells.host_of("c22008"), "far", "and a scout of before names it by its port");
        assert_eq!(cells.host_of("c0badcafe"), "", "negative: a cell nobody names has no machine");
        assert!(cells.delete_slot(&id));
        assert!(!cells.delete_slot(&id), "negative: a cell deleted is not there to delete again");
        assert_eq!(cells.set_note(&id, Some(&json!("x"))).unwrap_err().status, 404);
    }

    #[test]
    fn a_report_names_its_cell_by_id_or_by_the_port_of_before() {
        assert_eq!(ServerCells::node_cell(&json!({"id": "c3f9a02b1", "port": 22001})), Some("c3f9a02b1".to_string()));
        assert_eq!(ServerCells::node_cell(&json!({"port": 22001})), Some("c22001".to_string()), "a scout of before names a port");
        assert_eq!(ServerCells::node_cell(&json!({"port": null})), None, "negative: a report that names neither names no cell");
        assert_eq!(ServerCells::asked_id(&json!({"cellId": "c22001"})).unwrap(), "c22001");
        assert!(ServerCells::asked_id(&json!({"port": 22001})).is_err(), "negative: a request by port names no cell");
    }

    #[test]
    fn an_old_command_goes_to_the_history() {
        let mut slot =
            json!({"config": {"COMMAND": "old", "ENV": "A=1"}, "commandHistory": [{"command": "old"}, {"command": "older"}, 5]});
        let config = json!({"COMMAND": "new"});
        ServerCells::remember_old_command(&mut slot, config.as_object().unwrap(), 9);
        assert_eq!(slot["commandHistory"][0]["command"], "old");
        assert_eq!(slot["commandHistory"][0]["env"], "A=1");
        assert_eq!(slot["commandHistory"][1], json!({"command": "older"}));
        assert_eq!(slot["commandHistory"].as_array().unwrap().len(), 2);
    }
}
