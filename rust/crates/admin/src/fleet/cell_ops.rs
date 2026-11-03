//! Server-cell lifecycle actions, each run through the scout of its machine.

use super::engine_cells::EngineCellFit;
use super::server_cells::ServerCells;
use super::start::ScoutStart;
use crate::app::App;
use crate::config::builder::CellCommand;
use crate::config::text::ConfigText;
use crate::models::locator::Locations;
use crate::models::moves::runner::MoveRunner;
use crate::models::stores::StoreRegistry;
use crate::paths::HostIds;
use crate::status::StatusDesk;
use crate::store::topology::Topology;
use rules::{AppError, Coerce};
use serde_json::{Map, Value, json};
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

/// A cell's autostart follows its record (1.3.504).
pub struct CellAutostart<'app> {
    app: &'app App,
}

impl<'app> CellAutostart<'app> {
    /// The autostarts of `app`.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    fn kept(&self, host_id: &str, port: i64) -> bool {
        let id = HostIds::canonical(host_id);
        self.app.admin.change(|doc| {
            let mut topology = Topology::of(doc);
            let ports = topology.hosts().get(&id).and_then(|host| host.get("autostart")).and_then(Value::as_array).cloned();
            ports.into_iter().flatten().any(|said| said.as_i64() == Some(port))
        })
    }

    /// A cell's autostart on or off, on its machine: what happened, in words the caller shows.
    pub fn set(&self, host_id: &str, port: i64, enabled: bool) -> Value {
        let result = (|| {
            let body = if enabled {
                let slot = self.app.admin.change(|doc| Topology::of(doc).slot(host_id, port));
                CellOps::of(self.app).scout_start_body(host_id, port, &slot, false)?
            } else {
                json!({"hostId": host_id, "port": port})
            };
            ScoutStart::of(self.app).autostart(&body, enabled)
        })();
        match result {
            Ok(said) => json!({"port": port, "enabled": enabled, "ok": Coerce::truthy(said.get("ok"))}),
            Err(error) => json!({"port": port, "enabled": enabled, "ok": false, "error": error.message}),
        }
    }

    /// The deleted cell's request goes; `None` when it kept none.
    pub fn forget(&self, host_id: &str, port: i64) -> Option<Value> {
        self.kept(host_id, port).then(|| self.set(host_id, port, false))
    }

    /// `change`, the records' move, run with each kept request off its old port before and on its new one after.
    pub fn moved<R>(
        &self,
        moves: &[(String, i64, i64)],
        change: impl FnOnce() -> Result<R, AppError>,
    ) -> Result<(R, Vec<Value>), AppError> {
        let kept: Vec<&(String, i64, i64)> = moves.iter().filter(|(host_id, old, _)| self.kept(host_id, *old)).collect();
        let mut said: Vec<Value> = kept.iter().map(|(host_id, old, _)| self.set(host_id, *old, false)).collect();
        let result = match change() {
            Ok(result) => result,
            Err(error) => {
                for (host_id, old, _) in &kept {
                    self.set(host_id, *old, true);
                }
                return Err(error);
            }
        };
        said.extend(kept.iter().map(|(host_id, _, new)| self.set(host_id, *new, true)));
        Ok((result, said))
    }
}

/// The lifecycle of this controller's cells.
pub struct CellOps<'app> {
    app: &'app App,
}

impl<'app> CellOps<'app> {
    const SCRIPT_MOST: usize = 64 * 1024;

    /// The lifecycle of `app`.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    fn number(raw: Option<&Value>) -> i64 {
        // absent-ok: `int(body.get("port") or 0)`: a port not said is none, and the caller refuses it.
        Coerce::whole(raw)
    }

    fn mark_cell(&self, host_id: &str, port: i64, mut slot: Value) -> Value {
        Coerce::put(&mut slot, "kind", json!("serverCell"));
        self.app.admin.saving(|doc| {
            Topology::of(doc).put_slot(host_id, port, slot.clone());
        });
        slot
    }

    /// A persistent server slot declared by hand, so that a cable can attach to it before the server runs.
    pub fn slot_add(&self, body: &Value) -> Result<Value, AppError> {
        let cells = ServerCells::of(self.app);
        if !Coerce::truthy(body.get("port")) || Coerce::truthy(body.get("engine")) {
            let result = cells.reserve(body)?;
            return Ok(
                json!({"ok": true, "slot": result.get("cell"), "cell": result.get("cell"), "nextPort": result.get("nextPort")}),
            );
        }
        let host_id = Coerce::stripped(body.get("hostId"));
        if host_id.is_empty() {
            return Err(AppError::new("hostId is required"));
        }
        let port = Self::number(body.get("port"));
        if port == 0 {
            return Err(AppError::new("port is required"));
        }
        let key = ServerCells::slot_key(&host_id, port);
        let held = self.app.admin.change(|doc| Topology::of(doc).has_slot(&host_id, port));
        cells.assert_port_available(port, held.then_some(key.as_str()))?;
        let config = body.get("config").filter(|config| config.is_object());
        let slot = cells.upsert_slot(&host_id, port, config, body.get("model"), body.get("label"))?;
        let slot = self.mark_cell(&host_id, port, slot);
        Ok(json!({"ok": true, "slot": slot, "cell": slot}))
    }

    /// A slot deleted: its autostart first, then its record, then its server if one runs.
    pub fn slot_delete(&self, body: &Value) -> Result<Value, AppError> {
        let host_id = Coerce::stripped(body.get("hostId"));
        let port = Self::number(body.get("port"));
        if host_id.is_empty() || port == 0 {
            return Err(AppError::new("hostId and port are required"));
        }
        let autostart = CellAutostart::of(self.app).forget(&host_id, port);
        let removed = ServerCells::of(self.app).delete_slot(&host_id, port);
        // A machine that does not answer has no server of this cell to worry about until it does, and then its record is gone.
        drop(ScoutStart::of(self.app).stop(&json!({"hostId": host_id, "port": port})));
        let mut out = json!({"ok": true, "removed": removed});
        if let Some(autostart) = autostart {
            Coerce::put(&mut out, "autostart", autostart);
        }
        Ok(out)
    }

    /// A cell's config saved without starting the server.
    pub fn save_config(&self, body: &Value) -> Result<Value, AppError> {
        let host_id = Coerce::stripped(body.get("hostId"));
        let port = Self::number(body.get("port"));
        let mut config = body.get("config").filter(|config| config.is_object()).map_or_else(Map::new, Coerce::fields);
        let model = Coerce::stripped(config.get("MODEL_FILE"));
        if host_id.is_empty() || port == 0 {
            return Err(AppError::new("hostId and port are required"));
        }
        let page = self.app.runners.for_config(&config).row().page;
        if !page.field.is_empty() {
            let checked = page.checked(config.get(page.field))?;
            config.insert(page.field.to_string(), json!(checked));
        }
        let cells = ServerCells::of(self.app);
        if !self.app.admin.change(|doc| Topology::of(doc).has_slot(&host_id, port)) {
            cells.assert_port_available(port, None)?;
        }
        let model = (!model.is_empty()).then(|| json!(model));
        let mut slot = cells.upsert_slot(&host_id, port, Some(&Value::Object(config)), model.as_ref(), None)?;
        Coerce::put(&mut slot, "cacheModels", json!(Coerce::truthy(body.get("cacheModels"))));
        self.app.admin.saving(|doc| {
            Topology::of(doc).put_slot(&host_id, port, slot.clone());
        });
        let kept = self.app.admin.change(|doc| {
            let mut topology = Topology::of(doc);
            let ports = topology.hosts().get(&host_id).and_then(|host| host.get("autostart")).and_then(Value::as_array).cloned();
            ports.into_iter().flatten().any(|said| said.as_i64() == Some(port))
        });
        let autostart = kept.then(|| {
            self.scout_start_body(&host_id, port, &slot, true).and_then(|body| ScoutStart::of(self.app).autostart(&body, true))
        });
        let mut doc = json!({"ok": true, "hostId": host_id, "port": port, "state": StatusDesk::of(self.app).state()});
        match autostart {
            Some(Ok(said)) => {
                let mut shown = json!({"ok": Coerce::truthy(said.get("ok"))});
                if let Some(error) = said.get("error").filter(|error| Coerce::truthy(Some(*error))) {
                    Coerce::put(&mut shown, "error", error.clone());
                }
                Coerce::put(&mut doc, "autostart", shown);
            }
            Some(Err(error)) => Coerce::put(&mut doc, "autostart", json!({"ok": false, "error": error.message})),
            None => {}
        }
        Ok(doc)
    }

    /// A scheduled cell's model brought home from the library it sits in, before its window opens, when there is room for it; the move's word.
    pub fn bring_home(&self, config: &Value, locations: &Locations) -> Option<Value> {
        let found = CellCommand::of(self.app).model_paths(&Coerce::fields(config), Some(locations));
        let mut by_store: BTreeMap<String, Vec<String>> = BTreeMap::new();
        for (_, at) in found.iter().filter(|(_, at)| at.in_library()) {
            if let Some(store) = &at.store {
                by_store.entry(store.id.clone()).or_default().push(at.rel.clone());
            }
        }
        let mut started = None;
        for (store_id, mut rels) in by_store {
            rels.sort();
            let paths: Vec<Value> = rels.iter().map(|rel| json!(rel)).collect();
            match MoveRunner::of(self.app).start(&paths, StoreRegistry::LOCAL_ID, Some(&store_id), Some(&json!({}))) {
                Ok(job) => started = Some(job),
                Err(_) => return None,
            }
        }
        started
    }

    /// What the board's buttons ask: start, stop, restart, enable, disable.
    pub fn action(&self, body: &Value) -> Result<Value, AppError> {
        let host_id = Coerce::stripped(body.get("hostId"));
        let port = Self::number(body.get("port"));
        let action = Coerce::stripped(body.get("action")).to_lowercase();
        if host_id.is_empty() || port == 0 {
            return Err(AppError::new("hostId and port are required"));
        }
        if !matches!(action.as_str(), "start" | "stop" | "restart" | "enable" | "disable") {
            return Err(AppError::new("action must be start, stop, restart, enable, or disable"));
        }
        ServerCells::refuse_controller_host(&host_id)?;
        let start = ScoutStart::of(self.app);
        let answered = |result: Value| json!({"ok": Coerce::truthy(result.get("ok")), "hostId": host_id, "port": port, "action": action, "result": result});
        if action == "stop" {
            return Ok(answered(start.stop(&json!({"hostId": host_id, "port": port}))?));
        }
        let slot = self.app.admin.change(|doc| Topology::of(doc).slot(&host_id, port));
        if matches!(action.as_str(), "start" | "restart") && body.get("force") != Some(&json!(true)) {
            let id = HostIds::canonical(&host_id);
            let host = self.app.admin.change(|doc| Topology::of(doc).hosts().get(&id).cloned());
            if let Some(short) = EngineCellFit::short(self.app, host.as_ref(), slot.get("config")) {
                return Ok(json!({"ok": false, "hostId": host_id, "port": port, "action": action, "short": short}));
            }
        }
        let start_body = self.scout_start_body(&host_id, port, &slot, action != "disable")?;
        if matches!(action.as_str(), "enable" | "disable") {
            return Ok(answered(start.autostart(&start_body, action == "enable")?));
        }
        if action == "restart" {
            let stopped = start.stop(&json!({"hostId": host_id, "port": port}))?;
            if !Coerce::truthy(stopped.get("ok")) {
                let words = stopped.get("error").filter(|said| Coerce::truthy(Some(*said))).unwrap_or(&stopped);
                let error = format!("the stop before the start failed: {}", Coerce::str_of(Some(words)));
                return Ok(
                    json!({"ok": false, "hostId": host_id, "port": port, "action": action, "result": {"ok": false, "error": error, "stop": stopped}}),
                );
            }
        }
        Ok(answered(start.start(&start_body)?))
    }

    /// What a machine asks before it starts a cell by itself, its watchdog or its boot: the request of the cell's settings as they are saved now, for the settings are this controller's (the owner, 2026-11-02).
    /// `request` null: no such cell here. Not ok: the cell cannot be started as it stands, and the machine goes by what it has.
    pub fn start_request(&self, host_id: &str, port: i64) -> Value {
        let slot = self.app.admin.change(|doc| {
            let mut topology = Topology::of(doc);
            topology.has_slot(host_id, port).then(|| topology.slot(host_id, port))
        });
        let Some(slot) = slot else {
            return json!({"ok": true, "request": null});
        };
        match self.scout_start_body(host_id, port, &slot, true).and_then(|body| ScoutStart::of(self.app).payload(&body)) {
            Ok(request) => json!({"ok": true, "request": request}),
            Err(error) => json!({"ok": false, "error": error.message}),
        }
    }

    /// What starts a scout's cell, from its saved slot: for a start and for its autostart alike.
    pub fn scout_start_body(&self, host_id: &str, port: i64, slot: &Value, check: bool) -> Result<Value, AppError> {
        let config = slot.get("config").filter(|config| config.is_object()).cloned().unwrap_or_else(|| json!({}));
        let fields = Coerce::fields(&config);
        let model = {
            let said = Coerce::stripped(slot.get("model"));
            if said.is_empty() { Coerce::stripped(config.get("MODEL_FILE")) } else { said }
        };
        if check {
            let runner = self.app.runners.for_config(&fields);
            if runner.row().command_path {
                runner.preflight_start(&fields, &model)?;
            } else if model.is_empty() {
                return Err(AppError::new("cell has no saved model — configure it first"));
            }
        }
        let ctx = match config.get("CTX_SIZE").filter(|said| Coerce::truthy(Some(*said))) {
            Some(said) => Coerce::int(said)
                .ok_or_else(|| AppError::with_status(format!("CTX_SIZE is no number: {}", Coerce::str_of(Some(said))), 500))?,
            None => 4096,
        };
        Ok(json!({
            "hostId": host_id, "modelPath": model, "port": port,
            "gpuLayers": ConfigText::gpu_layers_int(config.get("N_GPU_LAYERS"), 999), "ctxSize": ctx,
            "cacheModels": Coerce::truthy(slot.get("cacheModels")), "config": config, "cellPort": port,
        }))
    }

    /// `os.path.realpath`: a path that is not there resolves as far as it goes.
    fn real_path(path: &Path) -> PathBuf {
        if let Ok(real) = path.canonicalize() {
            return real;
        }
        match (path.parent(), path.file_name()) {
            (Some(parent), Some(name)) => Self::real_path(parent).join(name),
            _ => path.to_path_buf(),
        }
    }

    /// A read-only peek at a script a command cell's line names.
    pub fn script_preview(&self, raw_path: &str) -> Result<Value, AppError> {
        let said = Coerce::strip(raw_path).trim_matches(['"', '\'']);
        if said.is_empty() {
            return Err(AppError::new("path required"));
        }
        let home = self.app.env.home();
        let expanded = self.app.env.expand(said);
        let expanded = if expanded.is_absolute() { expanded } else { home.join(expanded) };
        let real = Self::real_path(&expanded);
        let real_home = Self::real_path(home);
        if !real.starts_with(&real_home) {
            return Err(AppError::new("only scripts under the home directory are readable"));
        }
        let extension = real.extension().map_or_else(String::new, |word| word.to_string_lossy().to_lowercase());
        if !matches!(extension.as_str(), "sh" | "bash" | "py") {
            return Err(AppError::new("only .sh / .bash / .py scripts are readable"));
        }
        if !Path::new(&real).is_file() {
            return Err(AppError::with_status("script not found", 404));
        }
        let raw = std::fs::read(&real).map_err(|error| AppError::with_status(error.to_string(), 500))?;
        let text = String::from_utf8_lossy(&raw);
        let meta = std::fs::metadata(&real).map_err(|error| AppError::with_status(error.to_string(), 500))?;
        let modified =
            // absent-ok: a file with no time reads as old.
            meta.modified().ok().and_then(|at| at.duration_since(std::time::UNIX_EPOCH).ok()).map_or(0, |since| since.as_secs());
        let content: String = text.chars().take(Self::SCRIPT_MOST).collect();
        let truncated = text.chars().count() > Self::SCRIPT_MOST;
        Ok(
            json!({"path": real.to_string_lossy(), "size": meta.len(), "mtime": modified, "content": content, "truncated": truncated}),
        )
    }
}

#[cfg(test)]
mod tests {
    #![allow(
        clippy::unwrap_used,
        clippy::indexing_slicing,
        reason = "a helper of a test may stop where it found something wrong"
    )]

    use super::*;
    use crate::tests::{TestApp, TestFolder};

    #[test]
    fn a_machine_is_told_the_start_of_a_cell_as_it_is_saved_now() {
        let folder = TestFolder::new("cell-start");
        let app = TestApp::over(&folder.path, &[]);
        let ops = CellOps::of(&app);
        assert_eq!(ops.start_request("box", 5), json!({"ok": true, "request": null}), "no such cell");
        let config = json!({"MODEL_FILE": "a/b.gguf", "PARALLEL": "2", "PORT": "5"});
        let save = |config: &Value| {
            ops.save_config(&json!({"hostId": "box", "port": 5, "config": config, "cacheModels": true})).unwrap()
        };
        save(&config);
        let first = ops.start_request("box", 5);
        assert_eq!(first["ok"], true);
        assert_eq!(first["request"]["port"], 5);
        assert_eq!(first["request"]["modelPath"], "a/b.gguf");
        assert_eq!(first["request"]["config"]["PARALLEL"], "2");
        assert!(
            first["request"]["args"].as_array().is_some_and(|args| args.contains(&json!("--parallel"))),
            "the same request a start from the board sends: {first}"
        );
        save(&json!({"MODEL_FILE": "a/b.gguf", "PARALLEL": "7", "PORT": "5"}));
        assert_eq!(ops.start_request("box", 5)["request"]["config"]["PARALLEL"], "7", "what was saved a moment ago");
        assert_eq!(ops.start_request("box", 6)["request"], Value::Null, "another port is another cell");
        assert_eq!(ops.start_request("other", 5)["request"], Value::Null, "and another machine");
    }

    #[test]
    fn a_cell_that_cannot_start_as_it_stands_is_said_so_and_the_machine_goes_by_what_it_has() {
        let folder = TestFolder::new("cell-start-no");
        let app = TestApp::over(&folder.path, &[]);
        let ops = CellOps::of(&app);
        ops.save_config(&json!({"hostId": "box", "port": 5, "config": {"PORT": "5"}, "cacheModels": true})).unwrap();
        let said = ops.start_request("box", 5);
        assert_eq!(said["ok"], false, "{said}");
        assert!(said["error"].as_str().is_some_and(|words| words.contains("no saved model")), "{said}");
    }
}
