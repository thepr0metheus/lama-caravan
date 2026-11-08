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
    /// What a config sent to a scout never says: its port is the one the scout leases at the start.
    const LEASED: &'static str = "PORT";

    fn new(config: Option<&Value>, models_dir: &str) -> Self {
        let raw = config.map_or_else(Map::new, Coerce::fields);
        Self {
            sent: raw.into_iter().filter(|(key, _)| key != Self::KEY && key != Self::LEASED).collect(),
            models_dir: models_dir.to_string(),
        }
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
        Coerce::put(payload, "shellLine", json!(LaunchScript::of(self.app).command_cell_shell_line(&run)?));
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

    /// The scout that leases a cell's port at its start: one older does not know the names of cells, and would run a command
    /// with the port's placeholder in it.
    pub const LEASES_PORTS: [u32; 3] = [2, 46, 0];
    /// The scout with a door to its cells (`rules::CellDoor`): a cell listens on its machine's loopback since 2026-11-08, and one
    /// started by an older scout would answer nobody — not its health, not the Talk tab — while its scout had no way in.
    pub const OPENS_ITS_CELLS: [u32; 3] = [2, 48, 0];

    /// The request that starts a cell on a scout's machine: sent by a start, and kept by the scout for a cell that starts with the machine.
    /// It names the cell, and the range its port is leased from; no port: the scout leases one (Papyrus `caravan-scout-port-lease`).
    pub fn payload(&self, body: &Value) -> Result<Value, AppError> {
        let models_dir = self.app.models_dir().to_string_lossy().into_owned();
        let cell = ScoutCellConfig::new(body.get("config"), &models_dir);
        let model_path = Coerce::stripped(body.get("modelPath"));
        let id = ServerCells::asked_id(body)?;
        self.needs_scout(body, Self::LEASES_PORTS, "holds a port for every cell; a cell now gets one when it starts")?;
        self.needs_scout(body, Self::OPENS_ITS_CELLS, "has no door to its cells, which listen on its loopback now")?;
        let range = &self.app.paths.cell_ports;
        let mut payload = json!({
            "cellId": id,
            "ports": {"base": range.base, "upper": range.upper},
            "modelPath": model_path,
            "gpuLayers": ConfigText::gpu_layers_int(body.get("gpuLayers"), 999),
            "ctxSize": Self::number_or(body.get("ctxSize"), 4096)?,
            "cacheModels": Coerce::truthy(body.get("cacheModels")),
            "config": cell.sent,
        });
        let runner = self.app.runners.for_config(&cell.sent);
        let row = runner.row();
        if let Some((major, minor, patch)) = row.min_scout {
            self.needs_scout(body, [major, minor, patch], &format!("cannot start a {} cell", row.id))?;
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
        Coerce::put(&mut payload, "inPlace", Value::Object(Self::with_parts(runner, &cell.sent, hints)));
        Ok(payload)
    }

    /// Refuses a start on a scout older than `need`, in words that say what it cannot do (`cannot`) and which scout it needs.
    fn needs_scout(&self, body: &Value, need: [u32; 3], cannot: &str) -> Result<(), AppError> {
        let have = Coerce::str_of(self.host_record(body).get("scoutVersion"));
        if !ScoutVersion::older(&have, &need) {
            return Ok(());
        }
        let [major, minor, patch] = need;
        Err(AppError::new(format!(
            "this scout ({have}) {cannot} — it needs caravan-scout {major}.{minor}.{patch}: update the scout"
        )))
    }

    /// The hints of a start's files, with how many first parts the scout brings of a split the runner does not bring whole: an IST-DAS set's sixth part is the Engram, named apart, and
    /// Unsloth's metadata part is read alone (2026-11-03). A file the library gave no hint gets one that says only that.
    fn with_parts(
        runner: &dyn crate::domain::runner::Runner,
        config: &Map<String, Value>,
        mut hints: Map<String, Value>,
    ) -> Map<String, Value> {
        for (field, value) in runner.model_file_values(config) {
            if let Some(count) = runner.parts_brought(&field, &value)
                && let Value::Object(hint) = hints.entry(value).or_insert_with(|| json!({}))
            {
                hint.insert("parts".to_string(), json!(count));
            }
        }
        hints
    }

    /// A start forwarded to the machine's scout. The scout answers with the port it leased; the slot keeps none.
    pub fn start(&self, body: &Value) -> Result<Value, AppError> {
        let host_id = Coerce::stripped(body.get("hostId"));
        if host_id.is_empty() {
            return Err(AppError::new("hostId is required"));
        }
        let scout = ScoutCall::of_host(self.app, &host_id)?;
        let payload = self.payload(body)?;
        let id = Coerce::text(payload.get("cellId"));
        let (config, model) = (body.get("config"), payload.get("modelPath"));
        let result = scout.post("/api/llama-node/start", &payload, 10)?;
        if Coerce::truthy(result.get("ok")) {
            // The cell runs: a record that was not kept is the next report's to make.
            drop(ServerCells::of(self.app).upsert_slot(&host_id, &id, config, model, None));
        }
        Ok(
            json!({"ok": Coerce::truthy(result.get("ok")), "hostId": host_id, "cellId": id, "port": result.get("port"), "result": result}),
        )
    }

    /// A scout cell's autostart turned on or off.
    pub fn autostart(&self, body: &Value, enabled: bool) -> Result<Value, AppError> {
        let host_id = Coerce::stripped(body.get("hostId"));
        if host_id.is_empty() {
            return Err(AppError::new("hostId is required"));
        }
        let scout = ScoutCall::of_host(self.app, &host_id)?;
        let id = ServerCells::asked_id(body)?;
        let payload = if enabled { self.payload(body)? } else { Value::Null };
        let result =
            scout.post("/api/llama-node/autostart", &json!({"cellId": id, "enabled": enabled, "payload": payload}), 10)?;
        if let Some(kept) = result.get("autostart").filter(|kept| kept.is_array()) {
            self.app.admin.saving(|doc| {
                if let Some(host) = Topology::of(doc).hosts().get_mut(&host_id).filter(|host| host.is_object()) {
                    Coerce::put(host, "autostart", kept.clone());
                }
            });
        }
        Ok(json!({"ok": Coerce::truthy(result.get("ok")), "hostId": host_id, "cellId": id, "result": result}))
    }

    /// A stop forwarded to the machine's scout.
    pub fn stop(&self, body: &Value) -> Result<Value, AppError> {
        let host_id = Coerce::stripped(body.get("hostId"));
        if host_id.is_empty() {
            return Err(AppError::new("hostId is required"));
        }
        let mut stop_body = json!({});
        if let Some(id) = body.get("cellId").and_then(rules::CellId::read) {
            Coerce::put(&mut stop_body, "cellId", json!(id));
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
    fn a_split_the_runner_does_not_bring_whole_is_said_in_its_file_s_hint() {
        let folder = TestFolder::new("start-parts");
        let app = TestApp::with_clock(&folder.path, &[], HandClock::at(1000));
        let set = "D/ISTA-DASLab/IQ1_M/DeepSeek-V4.1-Flash-1017-GSQ-RCO-IQ1_M-00001-of-00006.gguf";
        let meta = "U/unsloth/Q8_K_XL/DeepSeek-V4.1-Flash-1017-UD-Q8_K_XL-00001-of-00009.gguf";
        let config: Map<String, Value> = Coerce::fields(
            &json!({"RUNNER": "strata-ds", "MODEL_FILE": set, "STRATA_META_FILE": meta, "STRATA_ENGRAM_FILE": "D/e.gguf"}),
        );
        let library = json!({"path": "/lib/x", "library": "main", "size": 5});
        let hints = Coerce::fields(&json!({set: library.clone(), "D/e.gguf": library.clone()}));
        let said = ScoutStart::with_parts(app.runners.get("strata-ds"), &config, hints);
        assert_eq!(
            said[set],
            json!({"path": "/lib/x", "library": "main", "size": 5, "parts": 5}),
            "five of six: the sixth is the Engram"
        );
        assert_eq!(said[meta], json!({"parts": 1}), "a file of no hint gets one that says only that");
        assert_eq!(said["D/e.gguf"], library, "a file brought whole is not touched");
        let plain = Coerce::fields(&json!({"RUNNER": "strata", "MODEL_FILE": "Q/x-00001-of-00002.gguf"}));
        assert_eq!(
            ScoutStart::with_parts(app.runners.get("strata"), &plain, Map::new()),
            Map::new(),
            "another runner brings every part"
        );
    }

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
            start.payload(&json!({"hostId": "h", "cellId": "c22100", "config": {"RUNNER": "vllm", "VLLM_MODEL": model}})).unwrap()
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
        let body = json!({"hostId": "h", "cellId": "c22009", "config": {"RUNNER": "strata", "MODEL_FILE": "q/q-IQ2_XS.gguf", "SPEC_DRAFT_MODEL_FILE": "mtp-q2_0.gguf"}});
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
            .payload(&json!({"hostId": "nowhere", "cellId": "c22100", "config": {"RUNNER": "vllm", "VLLM_MODEL": "a/b"}}));
        assert!(vllm.is_ok(), "a runner that writes nothing of its own at a start needs no folder");
        assert_eq!(vllm.unwrap().get("workFolder"), None, "and its models stay the cache's");
    }

    /// The speculation switch of the cell form and of the new-cell wizard writes "none" when it is off (static/js/cell-plan.js
    /// CellDraft.OFF), and keeps the draft file: the start the controller sends a scout carries no draft then. It wrote an empty type
    /// until 2026-11-07, and an empty type with a file named launches the file by the file's own type.
    #[test]
    fn a_start_whose_speculation_is_switched_off_sends_no_draft() {
        let folder = TestFolder::new("start-draft-off");
        let app = TestApp::with_clock(&folder.path, &[], HandClock::at(1000));
        let start = ScoutStart::of(&app);
        let args = |spec_type: &str| -> Vec<String> {
            let config = json!({"MODEL_FILE": "m/q.gguf", "SPEC_TYPE": spec_type, "SPEC_DRAFT_MODEL_FILE": "m/mtp-q.gguf"});
            let payload =
                start.payload(&json!({"hostId": "h", "cellId": "c22100", "modelPath": "m/q.gguf", "config": config})).unwrap();
            Coerce::list(payload.get("args")).iter().map(|word| Coerce::text(Some(word))).collect()
        };
        let off = args("none");
        assert!(!off.iter().any(|word| word == "--model-draft" || word == "--spec-type"), "switched off: {off:?}");
        let empty = args("");
        assert!(empty.windows(2).any(|pair| pair == ["--spec-type", "draft-mtp"]), "{empty:?}");
        assert!(empty.iter().any(|word| word == "--model-draft"), "an empty type with a file named loads it: {empty:?}");
    }

    #[test]
    fn a_start_names_its_cell_and_the_range_and_no_port() {
        let folder = TestFolder::new("start-lease");
        let app = TestApp::with_clock(&folder.path, &[], HandClock::at(1000));
        let start = ScoutStart::of(&app);
        let body = json!({"hostId": "h", "cellId": "c3f9a02b1", "modelPath": "m/q.gguf", "config": {"MODEL_FILE": "m/q.gguf", "PORT": "22007"}});
        let payload = start.payload(&body).unwrap();
        assert_eq!(payload["cellId"], "c3f9a02b1");
        assert_eq!(payload["ports"], json!({"base": app.paths.cell_ports.base, "upper": app.paths.cell_ports.upper}));
        assert_eq!(payload.get("port"), None, "negative: no port is sent — the scout leases one");
        assert_eq!(payload["config"].get("PORT"), None, "nor in the config");
        let args: Vec<String> = Coerce::list(payload.get("args")).iter().map(|word| Coerce::text(Some(word))).collect();
        assert!(args.windows(2).any(|pair| pair == ["--port", "{{PORT}}"]), "{args:?}");
        assert!(
            start.payload(&json!({"hostId": "h", "port": 22007, "config": {}})).is_err(),
            "negative: a start by port names no cell"
        );
        app.admin.saving(|doc| {
            Topology::of(doc).hosts().insert("h".to_string(), json!({"scoutVersion": "2.45.0"}));
        });
        let old = start.payload(&body).map_or_else(|error| error.message, |_| String::new());
        assert!(old.contains("update the scout"), "a scout that holds a port for every cell is told to update: {old}");
        app.admin.saving(|doc| {
            Topology::of(doc).hosts().insert("h".to_string(), json!({"scoutVersion": "2.47.1"}));
        });
        let old = start.payload(&body).map_or_else(|error| error.message, |_| String::new());
        assert!(
            old.contains("has no door to its cells") && old.contains("2.48.0"),
            "negative: a scout with no door would start a cell nobody reaches: {old}"
        );
        app.admin.saving(|doc| {
            Topology::of(doc).hosts().insert("h".to_string(), json!({"scoutVersion": "2.48.0"}));
        });
        assert!(start.payload(&body).is_ok(), "the scout that leases and opens its cells starts it");
        let args: Vec<String> =
            Coerce::list(start.payload(&body).unwrap().get("args")).iter().map(|word| Coerce::text(Some(word))).collect();
        assert!(args.windows(2).any(|pair| pair == ["--host", "127.0.0.1"]), "on its machine's loopback: {args:?}");
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
