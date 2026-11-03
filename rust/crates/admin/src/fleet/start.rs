//! A cell started on a scout's machine.

use super::launch::LaunchScript;
use super::model_cache::ModelCache;
use super::scout::ScoutCall;
use super::server_cells::ServerCells;
use crate::app::App;
use crate::config::builder::{CellCommand, FoundFiles};
use crate::config::text::ConfigText;
use crate::domain::runner::Config;
use crate::models::model_list::ModelList;
use crate::store::topology::Topology;
use rules::{AppError, Coerce};
use serde_json::{Map, Value, json};

/// A cell config as it leaves for a scout, and as this controller locates the cell's models: the folder is this controller's own word.
struct ScoutCellConfig {
    sent: Config,
    models_dir: String,
}

impl ScoutCellConfig {
    const KEY: &'static str = "LLAMA_MODELS_DIR";

    fn new(config: Option<&Value>, models_dir: &str) -> Self {
        let raw = config.map_or_else(Map::new, Coerce::fields);
        Self { sent: raw.into_iter().filter(|(key, _)| key != Self::KEY).collect(), models_dir: models_dir.to_string() }
    }

    fn located(&self, model_path: &str) -> Config {
        let mut config = self.sent.clone();
        config.insert(Self::KEY.to_string(), json!(self.models_dir));
        if !model_path.is_empty() {
            config.insert("MODEL_FILE".to_string(), json!(model_path));
        }
        config
    }
}

/// The version of a scout as numbers.
pub struct ScoutVersion;

impl ScoutVersion {
    /// `(2, 9, 0)` from "2.9.0" (a suffix such as ".dev1" ends it); `None` for no number at all.
    pub fn of(text: &str) -> Option<Vec<u32>> {
        let mut parts = Vec::new();
        for piece in Coerce::strip(text).split('.') {
            if piece.is_empty() || !piece.chars().all(|digit| digit.is_ascii_digit()) {
                break;
            }
            parts.push(piece.parse().ok()?);
        }
        (!parts.is_empty()).then_some(parts)
    }

    /// Whether `have` is known to be older than `need`: a version nothing said is given the benefit of the doubt.
    pub fn older(have: &str, need: &[u32]) -> bool {
        Self::of(have).is_some_and(|parts| parts.as_slice() < need)
    }
}

/// What a cell of one launch config keeps resident in its machine's memory, for the cell form's RAM scale.
pub struct CellRamPlan;

impl CellRamPlan {
    const HEADROOM_MIB: i64 = 2048;

    /// The runner, the promise, and the room left beside it.
    pub fn of(app: &App, config: &Value) -> Value {
        let config_fields = Coerce::fields(config);
        let runner = app.runners.for_config(&config_fields);
        let models_dir = app.models_dir().to_string_lossy().into_owned();
        let located = ScoutCellConfig::new(Some(config), &models_dir).located("");
        let found = CellCommand::of(app).model_paths(&located, Some(&ModelList::locations(app, false)));
        json!({"runner": runner.row().id, "ram": runner.ram_reservation(&config_fields, &found.sizes()), "headroomMiB": Self::HEADROOM_MIB})
    }
}

/// The starts of this controller.
pub struct ScoutStart<'app> {
    app: &'app App,
}

impl<'app> ScoutStart<'app> {
    /// The starts of `app`.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    fn host_record(&self, body: &Value) -> Value {
        let id = Coerce::text(body.get("hostId"));
        self.app.admin.change(|doc| Topology::of(doc).hosts().get(&id).cloned()).unwrap_or_else(|| json!({}))
    }

    fn number_or(raw: Option<&Value>, otherwise: i64) -> Result<i64, AppError> {
        match raw.filter(|said| Coerce::truthy(Some(*said))) {
            None => Ok(otherwise),
            Some(said) => Coerce::int(said)
                .ok_or_else(|| AppError::with_status(format!("not a number: {}", Coerce::str_of(Some(said))), 500)),
        }
    }

    /// The command half of a start.
    fn command_part(&self, payload: &mut Value, body: &Value, found: &FoundFiles) -> Result<(), AppError> {
        let config = payload.get("config").map_or_else(Map::new, Coerce::fields);
        let runner = self.app.runners.for_config(&config);
        Coerce::put(payload, "cellKind", json!("command"));
        let cells = CellCommand::of(self.app);
        let mut files: Vec<String> = runner.model_file_values(&config).into_iter().map(|(_, value)| value).collect();
        files.extend(cells.placed_model(&config, found));
        Coerce::put(payload, "modelFiles", json!(files));
        let run = cells.run_config(&config, found);
        let command = self.app.runners.for_config(&run).command(&run)?;
        Coerce::put(payload, "command", json!(command));
        Coerce::put(payload, "healthPath", json!(runner.health_path(&config)));
        let port = payload.get("port").and_then(Value::as_i64);
        Coerce::put(payload, "shellLine", json!(LaunchScript::of(self.app).command_cell_shell_line(&run, port)?));
        if command.is_empty() {
            return Err(AppError::new("command is required for a command cell"));
        }
        let host = self.host_record(body);
        let gpus = Coerce::list(host.get("gpus"));
        if let Some(reservation) = runner.vram_reservation(&config, &gpus).filter(|said| Coerce::truthy(Some(said))) {
            Coerce::put(payload, "vram", reservation);
        }
        if let Some(ram) = runner.ram_reservation(&config, &found.sizes()).filter(|said| Coerce::truthy(Some(said))) {
            Coerce::put(payload, "ram", ram);
        }
        Ok(())
    }

    /// The request that starts a cell on a scout's machine: sent by a start, and kept by the scout for a cell that starts with the machine.
    pub fn payload(&self, body: &Value) -> Result<Value, AppError> {
        let models_dir = self.app.models_dir().to_string_lossy().into_owned();
        let cell = ScoutCellConfig::new(body.get("config"), &models_dir);
        let model_path = Coerce::stripped(body.get("modelPath"));
        let mut payload = json!({
            "modelPath": model_path,
            "port": Self::number_or(body.get("port"), 8180)?,
            "gpuLayers": ConfigText::gpu_layers_int(body.get("gpuLayers"), 999),
            "ctxSize": Self::number_or(body.get("ctxSize"), 4096)?,
            "cacheModels": Coerce::truthy(body.get("cacheModels")),
            "config": cell.sent,
        });
        let runner = self.app.runners.for_config(&cell.sent);
        let row = runner.row();
        if let Some((major, minor, patch)) = row.min_scout {
            let host = self.host_record(body);
            let have = Coerce::str_of(host.get("scoutVersion"));
            if ScoutVersion::older(&have, &[major, minor, patch]) {
                return Err(AppError::new(format!(
                    "this scout ({have}) cannot start a {} cell — it needs caravan-scout {major}.{minor}.{patch}: update the scout",
                    row.id
                )));
            }
        }
        if row.work_folder {
            ModelCache::refuse_without_work(&self.host_record(body), row.id)?;
            // Its models are kept in that folder too, copied there whether the cache is on or off, and kept after the stop by the folder's own limit (the owner, 2026-11-03).
            Coerce::put(&mut payload, "workFolder", json!(true));
        }
        if row.llama_config {
            runner.preflight_start(&cell.sent, &model_path)?;
        }
        if row.id == "prism" {
            let host = self.host_record(body);
            if !Coerce::truthy(host.get("prismRuntime").and_then(|runtime| runtime.get("supported"))) {
                return Err(AppError::new("This scout does not support PrismML yet — update caravan-scout and refresh the host"));
            }
        }
        let located = cell.located(if row.command_path { "" } else { &model_path });
        let cells = CellCommand::of(self.app);
        let found = cells.model_paths(&located, Some(&ModelList::locations(self.app, true)));
        if row.command_path {
            self.command_part(&mut payload, body, &found)?;
        } else {
            let header = found.get("MODEL_FILE").map_or_else(String::new, |at| at.path.clone());
            // A machine whose cache is off reads its model from the library, whatever the controller's own place for it.
            let over_network = found.over_network() || ModelCache::reads_over_network(&self.host_record(body));
            Coerce::put(&mut payload, "args", json!(cells.remote_args(&cell.sent, over_network, &header)));
            let env: Map<String, Value> =
                runner.launch_env(&cell.sent).into_iter().map(|(key, value)| (key, json!(value))).collect();
            Coerce::put(&mut payload, "env", Value::Object(env));
            if model_path.is_empty() {
                return Err(AppError::new("modelPath is required"));
            }
        }
        let hints: Map<String, Value> = found.iter().filter_map(|(_, at)| at.hint().map(|hint| (at.rel.clone(), hint))).collect();
        Coerce::put(&mut payload, "inPlace", Value::Object(hints));
        Ok(payload)
    }

    /// A start forwarded to the machine's scout.
    pub fn start(&self, body: &Value) -> Result<Value, AppError> {
        let host_id = Coerce::stripped(body.get("hostId"));
        if host_id.is_empty() {
            return Err(AppError::new("hostId is required"));
        }
        let scout = ScoutCall::of_host(self.app, &host_id)?;
        let payload = self.payload(body)?;
        // absent-ok: `payload` wrote its port above.
        let port = Coerce::i64_or_zero(payload.get("port"));
        let cells = ServerCells::of(self.app);
        let (config, model) = (payload.get("config"), payload.get("modelPath"));
        let key = ServerCells::slot_key(&host_id, port);
        match body.get("cellPort").filter(|said| !said.is_null() && **said != json!("")).and_then(Coerce::int) {
            Some(old) if old != port => {
                cells.move_cell(&host_id, old, port, config, model)?;
            }
            Some(_) => cells.assert_port_available(port, Some(&key))?,
            None => {
                let held = self.app.admin.change(|doc| Topology::of(doc).has_slot(&host_id, port));
                cells.assert_port_available(port, held.then_some(key.as_str()))?;
            }
        }
        let result = scout.post("/api/llama-node/start", &payload, 10)?;
        if Coerce::truthy(result.get("ok")) {
            // The cell runs: a record that was not kept is the next report's to make.
            drop(cells.upsert_slot(&host_id, port, config, model, None));
        }
        Ok(json!({"ok": Coerce::truthy(result.get("ok")), "hostId": host_id, "result": result}))
    }

    /// A scout cell's autostart turned on or off.
    pub fn autostart(&self, body: &Value, enabled: bool) -> Result<Value, AppError> {
        let host_id = Coerce::stripped(body.get("hostId"));
        if host_id.is_empty() {
            return Err(AppError::new("hostId is required"));
        }
        let scout = ScoutCall::of_host(self.app, &host_id)?;
        // absent-ok: `int(body.get("port") or 0)`: the scout refuses a port of none in its own words.
        let port = Coerce::whole(body.get("port"));
        let payload = if enabled { self.payload(body)? } else { Value::Null };
        let result =
            scout.post("/api/llama-node/autostart", &json!({"port": port, "enabled": enabled, "payload": payload}), 10)?;
        if let Some(ports) = result.get("autostart").filter(|ports| ports.is_array()) {
            self.app.admin.saving(|doc| {
                if let Some(host) = Topology::of(doc).hosts().get_mut(&host_id).filter(|host| host.is_object()) {
                    Coerce::put(host, "autostart", ports.clone());
                }
            });
        }
        Ok(json!({"ok": Coerce::truthy(result.get("ok")), "hostId": host_id, "port": port, "result": result}))
    }

    /// A stop forwarded to the machine's scout.
    pub fn stop(&self, body: &Value) -> Result<Value, AppError> {
        let host_id = Coerce::stripped(body.get("hostId"));
        if host_id.is_empty() {
            return Err(AppError::new("hostId is required"));
        }
        let mut stop_body = json!({});
        if let Some(port) = body.get("port").filter(|port| Coerce::truthy(Some(*port))).and_then(Coerce::int) {
            Coerce::put(&mut stop_body, "port", json!(port));
        }
        // A process has 15 s to end and what it left 10 more: a shorter wait said "unreachable" of a stop that went on.
        let result = ScoutCall::of_host(self.app, &host_id)?.post("/api/llama-node/stop", &stop_body, 40)?;
        Ok(json!({"ok": Coerce::truthy(result.get("ok")), "hostId": host_id, "result": result}))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::tests::{HandClock, TestApp, TestFolder};

    #[test]
    fn a_version_reads_up_to_its_suffix() {
        assert_eq!(ScoutVersion::of("2.9.0"), Some(vec![2, 9, 0]));
        assert_eq!(ScoutVersion::of("2.9.dev1"), Some(vec![2, 9]));
        assert_eq!(ScoutVersion::of("dev"), None);
        assert!(ScoutVersion::older("2.8.9", &[2, 9, 0]));
        assert!(!ScoutVersion::older("2.9.0", &[2, 9, 0]));
        assert!(!ScoutVersion::older("", &[2, 9, 0]));
    }

    #[test]
    fn a_checkpoint_named_by_its_place_comes_as_a_model_does_and_what_else_vllm_can_read_stays_as_written() {
        let folder = TestFolder::new("start-vllm");
        let app = TestApp::with_clock(&folder.path, &[], HandClock::at(1000));
        std::fs::create_dir_all(app.models_dir().join("Qwen/nvidia/NVFP4")).unwrap();
        let start = ScoutStart::of(&app);
        let payload = |model: &str| {
            start.payload(&json!({"hostId": "h", "port": 22100, "config": {"RUNNER": "vllm", "VLLM_MODEL": model}})).unwrap()
        };
        let serves = |payload: &Value, word: &str| {
            let command = Coerce::text(payload.get("command"));
            let line = Coerce::text(payload.get("shellLine"));
            assert!(command.contains(&format!("serve {word} --host")), "{command}");
            assert!(line.contains(&format!("serve {word} --host")), "{line}");
        };

        let placed = payload("Qwen/nvidia/NVFP4/");
        assert_eq!(placed["modelFiles"], json!(["Qwen/nvidia/NVFP4"]), "the scout brings it, or shows it");
        serves(&placed, "\"${LLAMA_MODELS_DIR:-$HOME/llama.cpp/models}\"/Qwen/nvidia/NVFP4");
        assert_eq!(placed["config"]["VLLM_MODEL"], "Qwen/nvidia/NVFP4/", "what is kept is what the operator picked");
        assert_eq!(placed["inPlace"]["Qwen/nvidia/NVFP4"]["dir"], true, "the scout hears it is a folder");

        let repo = payload("nvidia/Qwen3.6-27B-NVFP4");
        assert_eq!(repo["modelFiles"], json!([]), "no such place: an HF repo id, and vLLM fetches that itself");
        serves(&repo, "nvidia/Qwen3.6-27B-NVFP4");

        let path = payload("/mnt/elsewhere/ckpt");
        assert_eq!(path["modelFiles"], json!([]), "a path on the machine is the operator's");
        serves(&path, "/mnt/elsewhere/ckpt");

        let home = app.models_dir().to_string_lossy().into_owned();
        let own = payload(&format!("{home}/Qwen/nvidia/NVFP4"));
        assert_eq!(own["modelFiles"], json!([]), "a path written out stays one, as a cell made before says it");
        serves(&own, &format!("{home}/Qwen/nvidia/NVFP4"));
    }

    #[test]
    fn a_strata_cell_does_not_start_where_no_folder_is_chosen_for_its_files() {
        let folder = TestFolder::new("start-work");
        let app = TestApp::with_clock(&folder.path, &[], HandClock::at(1000));
        let body = json!({"hostId": "h", "port": 22009, "config": {"RUNNER": "strata", "MODEL_FILE": "q/q-IQ2_XS.gguf", "SPEC_DRAFT_MODEL_FILE": "mtp-q2_0.gguf"}});
        let with = |work: Value| {
            app.admin.saving(|doc| {
                Topology::of(doc)
                    .hosts()
                    .insert("h".to_string(), json!({"name": "box", "modelCache": {"keep": 1, "work": work}}));
            });
            ScoutStart::of(&app).payload(&body).map_or_else(|error| error.message, |_| String::new())
        };
        let refused = with(json!({"dir": "/c", "chosen": false}));
        assert!(refused.contains("no folder is chosen for them on box"), "{refused}");
        let chosen = with(json!({"dir": "/mnt/hdd", "chosen": true}));
        assert!(
            !chosen.contains("no folder is chosen") && !chosen.contains("does not say where"),
            "chosen, the start goes on: {chosen}"
        );
        let payload = ScoutStart::of(&app).payload(&body).unwrap();
        assert_eq!(payload["workFolder"], true, "the scout keeps its models in that folder");
        let vllm = ScoutStart::of(&app)
            .payload(&json!({"hostId": "nowhere", "port": 22100, "config": {"RUNNER": "vllm", "VLLM_MODEL": "a/b"}}));
        assert!(vllm.is_ok(), "a runner that writes nothing of its own at a start needs no folder");
        assert_eq!(vllm.unwrap().get("workFolder"), None, "and its models stay the cache's");
    }

    #[test]
    fn the_models_folder_stays_this_controller_s_own_word() {
        let cell = ScoutCellConfig::new(Some(&json!({"A": 1, "LLAMA_MODELS_DIR": "/there"})), "/here");
        assert!(!cell.sent.contains_key("LLAMA_MODELS_DIR"));
        let located = cell.located("m.gguf");
        assert_eq!(located["LLAMA_MODELS_DIR"], "/here");
        assert_eq!(located["MODEL_FILE"], "m.gguf");
    }
}
