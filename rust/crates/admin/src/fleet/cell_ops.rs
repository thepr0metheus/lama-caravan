//! Server-cell lifecycle actions, each run through the scout of its machine.

use super::engine_cells::EngineCellFit;
use super::server_cells::ServerCells;
use super::start::ScoutStart;
use crate::app::App;
use crate::config::builder::CellCommand;
use crate::config::text::ConfigText;
use crate::domain::runner::RunnerDefaults;
use crate::models::locator::Locations;
use crate::models::moves::runner::MoveRunner;
use crate::models::stores::StoreRegistry;
use crate::paths::HostIds;
use crate::status::StatusDesk;
use crate::store::topology::Topology;
use rules::{AppError, CellId, Coerce};
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

    /// Whether the scout of `host_id` keeps cell `id` on autostart, as its report said: by ids, or by the ports of a scout of before.
    fn kept(&self, host_id: &str, id: &str) -> bool {
        let host = HostIds::canonical(host_id);
        self.app.admin.change(|doc| {
            let mut topology = Topology::of(doc);
            let kept = topology.hosts().get(&host).and_then(|host| host.get("autostart")).and_then(Value::as_array).cloned();
            kept.into_iter().flatten().any(|said| CellId::read(&said).as_deref() == Some(id))
        })
    }

    /// A cell's autostart on or off, on its machine: what happened, in words the caller shows.
    pub fn set(&self, id: &str, enabled: bool) -> Value {
        let result = (|| {
            let slot = self.app.admin.change(|doc| Topology::of(doc).slot(id));
            let host_id = Coerce::stripped(slot.get("hostId"));
            if host_id.is_empty() {
                return Err(AppError::with_status(format!("no cell {id}"), 404));
            }
            let body = if enabled {
                CellOps::of(self.app).scout_start_body(&host_id, id, &slot, false)?
            } else {
                json!({"hostId": host_id, "cellId": id})
            };
            ScoutStart::of(self.app).autostart(&body, enabled)
        })();
        match result {
            Ok(said) => json!({"cellId": id, "enabled": enabled, "ok": Coerce::truthy(said.get("ok"))}),
            Err(error) => json!({"cellId": id, "enabled": enabled, "ok": false, "error": error.message}),
        }
    }

    /// The deleted cell's request goes; `None` when it kept none.
    pub fn forget(&self, host_id: &str, id: &str) -> Option<Value> {
        self.kept(host_id, id).then(|| self.set(id, false))
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

    /// The slot of the cell a request names, with its machine: refused when the request names none, or one this controller does
    /// not keep.
    fn asked_slot(&self, body: &Value) -> Result<(String, String, Value), AppError> {
        let id = ServerCells::asked_id(body)?;
        let slot = self.app.admin.change(|doc| Topology::of(doc).find_slot(&id).cloned());
        let Some(slot) = slot else {
            return Err(AppError::with_status(format!("no cell {id}"), 404));
        };
        let host_id = Coerce::stripped(slot.get("hostId"));
        if host_id.is_empty() {
            return Err(AppError::with_status(format!("cell {id} has no machine"), 500));
        }
        Ok((id, host_id, slot))
    }

    /// A persistent cell declared by hand, so that a cable can attach to it before the server runs: a new id on the machine named.
    pub fn slot_add(&self, body: &Value) -> Result<Value, AppError> {
        let cells = ServerCells::of(self.app);
        if Coerce::truthy(body.get("engine")) || !body.get("config").is_some_and(Value::is_object) {
            let result = cells.reserve(body)?;
            return Ok(json!({"ok": true, "slot": result.get("cell"), "cell": result.get("cell")}));
        }
        let host_id = Coerce::stripped(body.get("hostId"));
        if host_id.is_empty() {
            return Err(AppError::new("hostId is required"));
        }
        ServerCells::refuse_controller_host(&host_id)?;
        let id = cells.fresh_id()?;
        let slot = cells.upsert_slot(&host_id, &id, body.get("config"), body.get("model"), body.get("label"))?;
        let slot = cells.mark_cell(&id, slot);
        Ok(json!({"ok": true, "slot": slot, "cell": slot}))
    }

    /// A slot deleted: its autostart first, then its record, then its server if one runs.
    pub fn slot_delete(&self, body: &Value) -> Result<Value, AppError> {
        let (id, host_id, _) = self.asked_slot(body)?;
        let autostart = CellAutostart::of(self.app).forget(&host_id, &id);
        let removed = ServerCells::of(self.app).delete_slot(&id);
        // A machine that does not answer has no server of this cell to worry about until it does, and then its record is gone.
        drop(ScoutStart::of(self.app).stop(&json!({"hostId": host_id, "cellId": id})));
        let mut out = json!({"ok": true, "removed": removed});
        if let Some(autostart) = autostart {
            Coerce::put(&mut out, "autostart", autostart);
        }
        Ok(out)
    }

    /// A cell's config saved without starting the server: of the cell a request names, or — with no `cellId` — of a new cell on the
    /// machine named, which the answer names.
    pub fn save_config(&self, body: &Value) -> Result<Value, AppError> {
        let cells = ServerCells::of(self.app);
        let (id, host_id) = if body.get("cellId").is_some_and(|said| !said.is_null()) {
            let (id, host_id, _) = self.asked_slot(body)?;
            (id, host_id)
        } else {
            let host_id = Coerce::stripped(body.get("hostId"));
            if host_id.is_empty() {
                return Err(AppError::new("hostId or cellId is required"));
            }
            ServerCells::refuse_controller_host(&host_id)?;
            (cells.fresh_id()?, host_id)
        };
        let mut config = body.get("config").filter(|config| config.is_object()).map_or_else(Map::new, Coerce::fields);
        let model = Coerce::stripped(config.get("MODEL_FILE"));
        let runner = self.app.runners.for_config(&config);
        let page = runner.row().page;
        if !page.field.is_empty() {
            let checked = page.checked(config.get(page.field))?;
            config.insert(page.field.to_string(), json!(checked));
        }
        // What the runner finds for the cell (a DeepSeek set's Engram, drafter, metadata part): saved with it, and seen in its settings.
        let defaults = RunnerDefaults {
            models_dir: self.app.paths.default_models_dir.to_string_lossy().into_owned(),
            home: self.app.env.home().to_string_lossy().into_owned(),
        };
        runner.complete(&mut config, &defaults);
        let model = (!model.is_empty()).then(|| json!(model));
        let mut slot = cells.upsert_slot(&host_id, &id, Some(&Value::Object(config)), model.as_ref(), None)?;
        Coerce::put(&mut slot, "cacheModels", json!(Coerce::truthy(body.get("cacheModels"))));
        let slot = cells.mark_cell(&id, slot);
        let autostart = CellAutostart::of(self.app).kept(&host_id, &id).then(|| {
            self.scout_start_body(&host_id, &id, &slot, true).and_then(|body| ScoutStart::of(self.app).autostart(&body, true))
        });
        let mut doc = json!({"ok": true, "hostId": host_id, "cellId": id, "state": StatusDesk::of(self.app).state()});
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

    /// What the board's buttons ask: start, stop, restart, enable, disable — of the cell `cellId` names.
    pub fn action(&self, body: &Value) -> Result<Value, AppError> {
        let action = Coerce::stripped(body.get("action")).to_lowercase();
        if !matches!(action.as_str(), "start" | "stop" | "restart" | "enable" | "disable") {
            return Err(AppError::new("action must be start, stop, restart, enable, or disable"));
        }
        let (id, host_id, slot) = self.asked_slot(body)?;
        ServerCells::refuse_controller_host(&host_id)?;
        let start = ScoutStart::of(self.app);
        let answered = |result: Value| json!({"ok": Coerce::truthy(result.get("ok")), "hostId": host_id, "cellId": id, "action": action, "result": result});
        let stop_body = json!({"hostId": host_id, "cellId": id});
        if action == "stop" {
            return Ok(answered(start.stop(&stop_body)?));
        }
        if matches!(action.as_str(), "start" | "restart") && body.get("force") != Some(&json!(true)) {
            let host = self.app.admin.change(|doc| Topology::of(doc).hosts().get(&HostIds::canonical(&host_id)).cloned());
            if let Some(short) = EngineCellFit::short(self.app, host.as_ref(), slot.get("config")) {
                return Ok(json!({"ok": false, "hostId": host_id, "cellId": id, "action": action, "short": short}));
            }
        }
        let start_body = self.scout_start_body(&host_id, &id, &slot, action != "disable")?;
        if matches!(action.as_str(), "enable" | "disable") {
            return Ok(answered(start.autostart(&start_body, action == "enable")?));
        }
        if action == "restart" {
            let stopped = start.stop(&stop_body)?;
            if !Coerce::truthy(stopped.get("ok")) {
                let words = stopped.get("error").filter(|said| Coerce::truthy(Some(*said))).unwrap_or(&stopped);
                let error = format!("the stop before the start failed: {}", Coerce::str_of(Some(words)));
                return Ok(
                    json!({"ok": false, "hostId": host_id, "cellId": id, "action": action, "result": {"ok": false, "error": error, "stop": stopped}}),
                );
            }
        }
        Ok(answered(start.start(&start_body)?))
    }

    /// What a machine asks before it starts a cell by itself, its watchdog or its boot: the request of the cell's settings as they are saved now, for the settings are this controller's (the owner, 2026-11-02).
    /// `request` null: no such cell here. Not ok: the cell cannot be started as it stands, and the machine goes by what it has.
    pub fn start_request(&self, host_id: &str, id: &str) -> Value {
        let slot = self.app.admin.change(|doc| Topology::of(doc).find_slot(id).cloned());
        let Some(slot) = slot.filter(|slot| HostIds::canonical(&Coerce::text(slot.get("hostId"))) == HostIds::canonical(host_id))
        else {
            return json!({"ok": true, "request": null});
        };
        match self.scout_start_body(host_id, id, &slot, true).and_then(|body| ScoutStart::of(self.app).payload(&body)) {
            Ok(request) => json!({"ok": true, "request": request}),
            Err(error) => json!({"ok": false, "error": error.message}),
        }
    }

    /// What starts a scout's cell, from its saved slot: for a start and for its autostart alike. It names the cell and no port: the
    /// scout leases one in the range given here (`ports`).
    pub fn scout_start_body(&self, host_id: &str, id: &str, slot: &Value, check: bool) -> Result<Value, AppError> {
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
            "hostId": host_id, "cellId": id, "modelPath": model,
            "gpuLayers": ConfigText::gpu_layers_int(config.get("N_GPU_LAYERS"), 999), "ctxSize": ctx,
            "cacheModels": Coerce::truthy(slot.get("cacheModels")), "config": config,
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
        assert_eq!(ops.start_request("box", "c5"), json!({"ok": true, "request": null}), "no such cell");
        let made = ops
            .save_config(&json!({"hostId": "box", "config": {"MODEL_FILE": "a/b.gguf", "PARALLEL": "2", "PORT": "5"}, "cacheModels": true}))
            .unwrap();
        let id = made["cellId"].as_str().unwrap().to_string();
        assert!(CellId::is_name(&id), "a save with no cell makes one, and the answer names it: {made}");
        let first = ops.start_request("box", &id);
        assert_eq!(first["ok"], true);
        assert_eq!(first["request"]["cellId"], json!(id));
        assert_eq!(first["request"].get("port"), None, "negative: a request holds no port — the scout leases one");
        assert_eq!(first["request"]["config"].get("PORT"), None, "nor does the config it carries");
        assert_eq!(first["request"]["modelPath"], "a/b.gguf");
        assert_eq!(first["request"]["config"]["PARALLEL"], "2");
        let args = first["request"]["args"].as_array().cloned().unwrap_or_default();
        assert!(args.contains(&json!("--parallel")), "the same request a start from the board sends: {first}");
        assert!(
            args.windows(2).any(|pair| pair[0] == json!("--port") && pair[1] == json!("{{PORT}}")),
            "the port is the scout's to fill: {args:?}"
        );
        ops.save_config(&json!({"cellId": id, "config": {"MODEL_FILE": "a/b.gguf", "PARALLEL": "7"}, "cacheModels": true}))
            .unwrap();
        assert_eq!(ops.start_request("box", &id)["request"]["config"]["PARALLEL"], "7", "what was saved a moment ago");
        assert_eq!(ops.start_request("box", "c6")["request"], Value::Null, "another id is another cell");
        assert_eq!(ops.start_request("other", &id)["request"], Value::Null, "and another machine");
        assert_eq!(
            ops.save_config(&json!({"cellId": "c6", "config": {}})).unwrap_err().status,
            404,
            "negative: no saving into a cell that is not kept"
        );
    }

    #[test]
    fn a_save_writes_what_the_runner_finds_in_the_library_into_the_cell() {
        let folder = TestFolder::new("cell-save-finds");
        let app = TestApp::over(&folder.path, &[]);
        let set = "D/I/IQ1_M/DeepSeek-V4.1-Flash-1017-GSQ-RCO-IQ1_M-00001-of-00006.gguf";
        for file in
            [set, "D/I/IQ4_NL/DeepSeek-V4.1-Flash-Engram-IQ4_NL.gguf", "U/u/Q8_0/dspark-DeepSeek-V4.1-Flash-1017-Q8_0.gguf"]
        {
            let path = app.models_dir().join(file);
            std::fs::create_dir_all(path.parent().unwrap()).unwrap();
            std::fs::write(path, b"x").unwrap();
        }
        let ops = CellOps::of(&app);
        let save = |config: Value| {
            let made = ops.save_config(&json!({"hostId": "box", "config": config})).unwrap();
            made["cellId"].as_str().unwrap().to_string()
        };
        let saved = |id: &str| app.admin.change(|doc| Topology::of(doc).slot(id)).get("config").cloned().unwrap_or(Value::Null);
        let strata = save(json!({"RUNNER": "strata-ds", "MODEL_FILE": set, "SPEC_DRAFT_MODEL_FILE": "mine/d.gguf"}));
        assert_eq!(
            saved(&strata)["STRATA_ENGRAM_FILE"],
            "D/I/IQ4_NL/DeepSeek-V4.1-Flash-Engram-IQ4_NL.gguf",
            "found in the library and saved"
        );
        assert_eq!(saved(&strata)["SPEC_DRAFT_MODEL_FILE"], "mine/d.gguf", "what the operator named stays");
        assert_eq!(saved(&strata).get("STRATA_META_FILE"), None, "a file the library lacks is not made up");
        let plain = save(json!({"MODEL_FILE": set}));
        assert_ne!(plain, strata, "a second save with no cell makes a second cell");
        assert_eq!(saved(&plain).get("STRATA_ENGRAM_FILE"), None, "another runner finds nothing");
    }

    #[test]
    fn a_cell_that_cannot_start_as_it_stands_is_said_so_and_the_machine_goes_by_what_it_has() {
        let folder = TestFolder::new("cell-start-no");
        let app = TestApp::over(&folder.path, &[]);
        let ops = CellOps::of(&app);
        let made = ops.save_config(&json!({"hostId": "box", "config": {}, "cacheModels": true})).unwrap();
        let said = ops.start_request("box", made["cellId"].as_str().unwrap());
        assert_eq!(said["ok"], false, "{said}");
        assert!(said["error"].as_str().is_some_and(|words| words.contains("no saved model")), "{said}");
    }
}
