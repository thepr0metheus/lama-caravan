//! Server slot and cell bookkeeping. A slot is what the board keeps of a cell, whether it runs or not.

use super::cell_outputs::CellOutputs;
use super::engine_cells::EngineCellPlan;
use super::port_exclusions::PortExclusions;
use crate::app::App;
use crate::config::builder::CellCommand;
use crate::paths::HostIds;
use crate::proxies::config::ProxiesConfig;
use crate::store::topology::Topology;
use plumbing::log::Log;
use rules::{AppError, Coerce};
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

    /// The slots of `app`.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    /// The key of a slot.
    pub fn slot_key(host_id: &str, port: i64) -> String {
        format!("{}:{port}", HostIds::canonical(host_id))
    }

    fn number(raw: Option<&Value>) -> i64 {
        // absent-ok: `int(body.get(key) or 0)`: a port not said is none, and the caller refuses it.
        Coerce::whole(raw)
    }

    /// Every port the fleet holds, but a slot's own.
    pub fn used_ports(&self, exclude_key: Option<&str>) -> BTreeSet<i64> {
        let mut used: BTreeSet<i64> = BTreeSet::from([self.app.paths.port]);
        used.extend(PortExclusions::of(self.app).excluded());
        let slots = self.app.admin.change(|doc| Topology::of(doc).slots().clone());
        used.extend(
            slots
                .iter()
                .filter(|(key, _)| Some(key.as_str()) != exclude_key)
                .filter_map(|(_, slot)| Coerce::int_or_zero(slot.get("port"))),
        );
        let payload = ProxiesConfig::of(self.app).read_payload();
        let routes = payload.get("routes").and_then(Value::as_array).into_iter().flatten();
        used.extend(routes.filter(|route| route.is_object()).filter_map(|route| Coerce::int_or_zero(route.get("port"))));
        used.retain(|port| *port > 0);
        used
    }

    /// The first free cell port.
    pub fn next_port(&self) -> i64 {
        let used = self.used_ports(None);
        let mut port = self.app.paths.cell_ports.base;
        while used.contains(&port) {
            port += 1;
        }
        port
    }

    /// Refuses a port the fleet already holds.
    pub fn assert_port_available(&self, port: i64, exclude_key: Option<&str>) -> Result<(), AppError> {
        if !(1..=65535).contains(&port) {
            return Err(AppError::new("port must be between 1 and 65535"));
        }
        if self.used_ports(exclude_key).contains(&port) {
            return Err(AppError::with_status(format!("server cell port {port} is already reserved"), 409));
        }
        Ok(())
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

    /// A persistent server slot recorded or refreshed for host:port.
    pub fn upsert_slot(
        &self,
        host_id: &str,
        port: i64,
        config: Option<&Value>,
        model: Option<&Value>,
        label: Option<&Value>,
    ) -> Result<Value, AppError> {
        Self::refuse_controller_host(host_id)?;
        let key = Self::slot_key(host_id, port);
        let now = self.app.now_whole();
        let free_form = config.and_then(Value::as_object).is_some_and(|config| CellCommand::of(self.app).is_command_cell(config));
        Ok(self.app.admin.saving(|doc| {
            let mut topology = Topology::of(doc);
            let slots = topology.slots();
            let mut slot =
                slots.get(&key).filter(|slot| Coerce::truthy(Some(*slot))).cloned().unwrap_or_else(|| json!({"createdAt": now}));
            Coerce::put(&mut slot, "id", json!(key));
            Coerce::put(&mut slot, "hostId", json!(HostIds::canonical(host_id)));
            Coerce::put(&mut slot, "port", json!(port));
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
                let kept: Map<String, Value> =
                    config.iter().filter(|(_, said)| !said.is_null()).map(|(key, said)| (key.clone(), said.clone())).collect();
                Coerce::put(&mut slot, "config", Value::Object(kept));
            }
            slots.insert(key.clone(), slot.clone());
            slot
        }))
    }

    fn follow_port(slot: &mut Value, id: String, new_port: i64, now: i64) {
        Coerce::put(slot, "id", json!(id));
        Coerce::put(slot, "port", json!(new_port));
        Coerce::put(slot, "updatedAt", json!(now));
        if let Some(config) = slot.get_mut("config").filter(|config| config.is_object() && Coerce::truthy(Some(*config))) {
            Coerce::put(config, "PORT", json!(new_port.to_string()));
        }
    }

    /// A stopped cell's slot moved to another free port.
    pub fn reassign_port(&self, body: &Value) -> Result<Value, AppError> {
        let host_id = Coerce::stripped(body.get("hostId"));
        let (old_port, new_port) = (Self::number(body.get("port")), Self::number(body.get("newPort")));
        if host_id.is_empty() || old_port == 0 || new_port == 0 {
            return Err(AppError::new("hostId, port and newPort are required"));
        }
        if new_port == old_port {
            return Err(AppError::new("newPort equals the current port"));
        }
        let old_key = Self::slot_key(&host_id, old_port);
        if !self.app.admin.change(|doc| Topology::of(doc).slots().contains_key(&old_key)) {
            return Err(AppError::with_status(format!("no server slot {old_key}"), 404));
        }
        self.assert_port_available(new_port, Some(&old_key))?;
        let new_key = Self::slot_key(&host_id, new_port);
        let now = self.app.now_whole();
        self.app.admin.saving(|doc| {
            let mut topology = Topology::of(doc);
            let slots = topology.slots();
            if let Some(mut slot) = slots.shift_remove(&old_key) {
                Self::follow_port(&mut slot, new_key.clone(), new_port, now);
                slots.insert(new_key.clone(), slot);
            }
        });
        let followed = CellOutputs::of(self.app).moved(old_port, new_port);
        Ok(json!({"ok": true, "key": new_key, "port": new_port, "followed": followed}))
    }

    /// The ports of two stopped cells swapped, on any machines.
    pub fn swap_ports(&self, body: &Value) -> Result<Value, AppError> {
        let host_a = Coerce::stripped(body.get("hostId"));
        let (port_a, port_b) = (Self::number(body.get("port")), Self::number(body.get("targetPort")));
        if host_a.is_empty() || port_a == 0 || port_b == 0 {
            return Err(AppError::new("hostId, port and targetPort are required"));
        }
        if port_a == port_b {
            return Err(AppError::new("a cell cannot swap with itself"));
        }
        let key_a = Self::slot_key(&host_a, port_a);
        let now = self.app.now_whole();
        let host_b = self.app.admin.change(|doc| -> Result<String, AppError> {
            let mut topology = Topology::of(doc);
            let slots = topology.slots();
            if !slots.contains_key(&key_a) {
                return Err(AppError::with_status(format!("no server slot {key_a}"), 404));
            }
            let found = slots.iter().find(|(_, slot)| Self::number(slot.get("port")) == port_b).map(|(key, _)| key.clone());
            let Some(key_b) = found else {
                return Err(AppError::new(format!("port :{port_b} is not a cell — only two cells can swap")));
            };
            let (Some(mut slot_a), Some(mut slot_b)) = (slots.shift_remove(&key_a), slots.shift_remove(&key_b)) else {
                return Err(AppError::with_status(format!("no server slot {key_a}"), 404));
            };
            let host_b = {
                let said = Coerce::text(slot_b.get("hostId"));
                if said.is_empty() { key_b.rsplit_once(':').map_or_else(String::new, |(host, _)| host.to_string()) } else { said }
            };
            let (id_a, id_b) = (Self::slot_key(&host_a, port_b), Self::slot_key(&host_b, port_a));
            Self::follow_port(&mut slot_a, id_a.clone(), port_b, now);
            Self::follow_port(&mut slot_b, id_b.clone(), port_a, now);
            slots.insert(id_a, slot_a);
            slots.insert(id_b, slot_b);
            Ok(host_b)
        })?;
        self.app.save_admin();
        let followed = CellOutputs::of(self.app).swapped(port_a, port_b);
        Ok(
            json!({"ok": true, "a": {"host": host_a, "port": port_b}, "b": {"host": host_b, "port": port_a}, "followed": followed}),
        )
    }

    /// A person's note on a cell slot.
    pub fn set_note(&self, host_id: &str, port: i64, note: Option<&Value>) -> Result<Value, AppError> {
        let key = Topology::slot_key(host_id, port);
        let note: String = Coerce::stripped(note).chars().take(280).collect();
        let note = Coerce::strip(&note).to_string();
        let now = self.app.now_whole();
        let done = self.app.admin.saving(|doc| {
            let mut topology = Topology::of(doc);
            let Some(slot) = topology.find_slot(host_id, port) else {
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
            return Err(AppError::with_status(format!("no server slot {key}"), 404));
        }
        Ok(json!({"key": key, "note": note}))
    }

    fn mark_cell(&self, host_id: &str, port: i64, mut slot: Value) -> Value {
        Coerce::put(&mut slot, "kind", json!("serverCell"));
        self.app.admin.saving(|doc| {
            Topology::of(doc).put_slot(host_id, port, slot.clone());
        });
        slot
    }

    /// A cell reserved on a machine, at the port asked for or the next free one.
    pub fn reserve(&self, body: &Value) -> Result<Value, AppError> {
        let host_id = Coerce::stripped(body.get("hostId"));
        if host_id.is_empty() {
            return Err(AppError::new("hostId is required"));
        }
        Self::refuse_controller_host(&host_id)?;
        let host = self.app.admin.change(|doc| Topology::of(doc).hosts().get(&HostIds::canonical(&host_id)).cloned());
        let config = EngineCellPlan::from_body(self.app, host.as_ref(), body).map(|plan| plan.config()).transpose()?;
        let port = match body.get("port").filter(|said| !said.is_null() && **said != json!("")) {
            Some(said) => Coerce::int(said).ok_or_else(|| AppError::new("port must be a number"))?,
            None => self.next_port(),
        };
        let key = Self::slot_key(&host_id, port);
        let held = self.app.admin.change(|doc| Topology::of(doc).has_slot(&host_id, port));
        self.assert_port_available(port, held.then_some(key.as_str()))?;
        let slot = self.upsert_slot(&host_id, port, config.as_ref(), None, body.get("label"))?;
        let slot = self.mark_cell(&host_id, port, slot);
        Ok(json!({"ok": true, "cell": slot, "nextPort": self.next_port()}))
    }

    /// A cell started on another port than its slot's.
    pub fn move_cell(
        &self,
        host_id: &str,
        old_port: i64,
        new_port: i64,
        config: Option<&Value>,
        model: Option<&Value>,
    ) -> Result<Value, AppError> {
        let (old_key, new_key) = (Self::slot_key(host_id, old_port), Self::slot_key(host_id, new_port));
        self.assert_port_available(new_port, Some(&old_key))?;
        let old = self.app.admin.change(|doc| Topology::of(doc).slots().shift_remove(&old_key));
        let label = old.as_ref().and_then(|old| old.get("label"));
        let mut slot = self.upsert_slot(host_id, new_port, config, model, label)?;
        if let Some(created) = old.as_ref().and_then(|old| old.get("createdAt")) {
            Coerce::put(&mut slot, "createdAt", created.clone());
        }
        // What the operator wrote of the cell goes with it to its new port: a start that moved a cell lost its note (2026-11-03).
        if let Some(note) = old.as_ref().and_then(|old| old.get("note")).filter(|note| Coerce::truthy(Some(*note))) {
            Coerce::put(&mut slot, "note", note.clone());
        }
        Coerce::put(&mut slot, "kind", json!("serverCell"));
        self.app.admin.saving(|doc| {
            Topology::of(doc).slots().insert(new_key.clone(), slot.clone());
        });
        if old.is_some() && old_port != new_port {
            CellOutputs::of(self.app).moved(old_port, new_port);
        }
        Ok(slot)
    }

    /// Every cell configured on machine `from` goes to machine `to`.
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
        let ports = self.app.admin.change(|doc| -> Result<Vec<i64>, AppError> {
            let mut topology = Topology::of(doc);
            let slots = topology.slots();
            let mut moving: Vec<i64> = slots
                .values()
                .filter(|slot| slot.get("hostId").and_then(Value::as_str) == Some(source.as_str()))
                .map(|slot| Self::number(slot.get("port")))
                .collect();
            moving.sort_unstable();
            if moving.is_empty() {
                return Err(AppError::with_status(format!("no cells are configured on {source}"), 404));
            }
            let taken: Vec<String> = moving
                .iter()
                .filter(|port| slots.contains_key(&Self::slot_key(&target, **port)))
                .map(|port| format!(":{port}"))
                .collect();
            if !taken.is_empty() {
                return Err(AppError::with_status(format!("{target} already has cells on {}", taken.join(", ")), 409));
            }
            for port in &moving {
                if let Some(mut slot) = slots.shift_remove(&Self::slot_key(&source, *port)) {
                    let key = Self::slot_key(&target, *port);
                    Coerce::put(&mut slot, "id", json!(key));
                    Coerce::put(&mut slot, "hostId", json!(target));
                    Coerce::put(&mut slot, "updatedAt", json!(now));
                    slots.insert(key, slot);
                }
            }
            Ok(moving)
        })?;
        self.app.save_admin();
        Ok(json!({"ok": true, "from": source, "to": target, "ports": ports}))
    }

    /// A cell's slot forgotten; whether there was one.
    pub fn delete_slot(&self, host_id: &str, port: i64) -> bool {
        let key = Self::slot_key(host_id, port);
        let removed = self.app.admin.change(|doc| Topology::of(doc).slots().shift_remove(&key)).is_some();
        if removed {
            self.app.save_admin();
            CellOutputs::of(self.app).dropped(port, Some(host_id));
        }
        removed
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_kept_cell_s_key_is_a_port() {
        assert_eq!(KeptCells::port("8080"), 8080);
        assert_eq!(KeptCells::port("70000"), 0);
        assert_eq!(KeptCells::port("x"), 0);
        assert_eq!(KeptCells::port("-5"), 0);
    }

    #[test]
    fn a_cell_moved_to_another_port_keeps_its_note() {
        let folder = crate::tests::TestFolder::new("move-note");
        let app = crate::tests::TestApp::over(&folder.path, &[]);
        let cells = ServerCells::of(&app);
        cells.upsert_slot("box", 22020, Some(&json!({"MODEL_FILE": "m.gguf"})), None, None).unwrap();
        cells.set_note("box", 22020, Some(&json!("for the coder"))).unwrap();
        let moved = cells.move_cell("box", 22020, 22021, Some(&json!({"MODEL_FILE": "m.gguf"})), None).unwrap();
        assert_eq!(moved["note"], "for the coder");
        let kept = app.admin.change(|doc| Topology::of(doc).slot("box", 22021));
        assert_eq!(kept["note"], "for the coder", "kept so in the slot of the new port");
        assert!(!app.admin.change(|doc| Topology::of(doc).has_slot("box", 22020)), "and the old port's slot is gone");
        cells.upsert_slot("box", 22030, Some(&json!({"MODEL_FILE": "m.gguf"})), None, None).unwrap();
        assert_eq!(
            cells.move_cell("box", 22030, 22031, None, None).unwrap().get("note"),
            None,
            "negative: a cell with no note gets none"
        );
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
