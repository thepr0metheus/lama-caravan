//! A running cell's card: what it says of itself, and what the board makes of it.

use super::*;

/// One live cell's facts as they are read.
pub(super) struct LiveRow<'row> {
    pub(super) client: &'row Value,
    pub(super) node: &'row Value,
    pub(super) slot: Option<&'row Value>,
    pub(super) config: Config,
    /// The cell's own id: what joins the report to its slot.
    pub(super) cell: String,
    /// The port leased for this run; null while it holds none.
    pub(super) port: Value,
    pub(super) ip: String,
    pub(super) phase: String,
    pub(super) running: bool,
}

/// What a cell's health page and the board make of it.
pub(super) struct LiveHealth {
    pub(super) body: Option<Value>,
    pub(super) phase: String,
    pub(super) word: Option<String>,
}

/// What a live cell's card is drawn from, once it has been asked.
pub(super) struct LiveFacts {
    pub(super) is_command: bool,
    pub(super) slot_model: String,
    pub(super) model_path: String,
    pub(super) health: LiveHealth,
    pub(super) effective: String,
    pub(super) note: &'static str,
    pub(super) modalities: Option<Value>,
    pub(super) crash: Option<Value>,
    pub(super) model_name: String,
    pub(super) meta: Map<String, Value>,
    pub(super) trained: Option<i64>,
}

impl<'app> TopologyServer<'app> {
    /// One running, starting or failed cell, as its machine reports it.
    pub(super) fn live_row(&self, row: &LiveRow<'_>, reading: &ServerReading<'_>) -> Value {
        let facts = self.live_facts(row, reading);
        let mut out = self.live_card(row, &facts, reading);
        Coerce::extend(&mut out, &self.live_progress(row, &facts));
        out
    }

    /// What a cell's own health page says, for a cell whose command the operator wrote; the board's word on the rest. Both are
    /// asked through the machine's scout (`way`); a machine with no way to its cells says nothing, and nothing is guessed.
    pub(super) fn live_health(&self, row: &LiveRow<'_>, is_command: bool, way: Option<&CellDoorway>) -> LiveHealth {
        let remote = RemoteCells::of(self.app);
        let listening = row.node.get("listening").and_then(Value::as_bool);
        let body = way.filter(|_| is_command && row.running).map(|way| {
            remote.command_cell_health(way, &self.app.runners.for_config(&row.config).health_path(&row.config), listening)
        });
        let phase = Coerce::text(body.as_ref().and_then(|health| health.get("status")));
        let word = if is_command {
            match phase.as_str() {
                "ok" => Some("ok".to_string()),
                "downloading" | "loading" => Some("loading".to_string()),
                "broken" => Some("broken".to_string()),
                "down" => Some("down".to_string()),
                _ => None,
            }
        } else if row.running {
            way.map(|way| remote.llama_health(way))
        } else {
            None
        };
        LiveHealth { body, phase, word }
    }

    /// `(the phase the card says, a note on what a starting cell is doing)`.
    pub(super) fn live_phase(row: &LiveRow<'_>, health: &LiveHealth, is_command: bool) -> (String, &'static str) {
        let warming = row.running && health.word.as_deref() == Some("loading");
        let mut effective = if warming {
            "warming".to_string()
        } else if row.running {
            "running".to_string()
        } else {
            row.phase.clone()
        };
        if is_command && matches!(health.phase.as_str(), "downloading" | "loading") {
            effective.clone_from(&health.phase);
        }
        if row.running && is_command && health.phase == "broken" {
            effective = "broken".to_string();
        }
        let mut note = "";
        if row.running && row.node.get("listening") == Some(&json!(false)) {
            effective = "starting".to_string();
            note = CellWords::progress_note(&Coerce::text(row.node.get("startingTail")));
        }
        (effective, note)
    }

    pub(super) fn live_status(row: &LiveRow<'_>, facts: &LiveFacts) -> Value {
        if facts.effective == "broken" {
            return json!({"phase": "broken", "error": Coerce::text(facts.health.body.as_ref().and_then(|health| health.get("error")))});
        }
        let shown_phase = if row.running {
            facts.effective.clone()
        } else if row.phase.is_empty() {
            "starting".to_string()
        } else {
            row.phase.clone()
        };
        let mut out = json!({"phase": shown_phase});
        if !facts.note.is_empty() {
            Coerce::put(&mut out, "progressNote", json!(facts.note));
        }
        if let Some(note) = Self::retry_note(facts.crash.as_ref(), &shown_phase) {
            Coerce::put(&mut out, "lastError", note);
        }
        out
    }

    pub(super) fn live_facts(&self, row: &LiveRow<'_>, reading: &ServerReading<'_>) -> LiveFacts {
        let (node, config) = (row.node, &row.config);
        let is_command = self.app.runners.for_config(config).row().command_path;
        let remote = RemoteCells::of(self.app);
        let way = CellDoorway::of(self.app, row.client, &row.cell);
        let slot_model = Coerce::text(row.slot.and_then(|slot| slot.get("model")));
        let model_path = {
            let said = Coerce::text(node.get("modelPath"));
            if said.is_empty() { slot_model.clone() } else { said }
        };
        let health = self.live_health(row, is_command, way.as_ref());
        let (effective, note) = Self::live_phase(row, &health, is_command);
        let mut modalities = if health.word.as_deref() == Some("ok") && !is_command {
            way.as_ref().and_then(|way| remote.llama_modalities(way))
        } else {
            None
        };
        if modalities.is_none() {
            modalities = Some(RemoteCells::normalize_modalities(node.get("modalities")));
        }
        let about =
            way.as_ref().filter(|_| row.running && config.is_empty()).map_or_else(|| json!({}), |way| remote.cell_about(way));
        let mut model_name = ModelCheckpoints::display_name(if slot_model.is_empty() { &model_path } else { &slot_model });
        if model_name.is_empty() {
            model_name = Coerce::text(about.get("model"));
        }
        let mut meta = self.cell_meta(health.body.as_ref(), config, is_command);
        for said in ["engine", "kinds", "langs", "maxAudioMs", "targetLang"] {
            if let Some(value) = about.get(said).filter(|_| !meta.contains_key(said)) {
                meta.insert(said.to_string(), value.clone());
            }
        }
        let cells = CellCommand::of(self.app);
        let trained = Self::positive_int(node.get("ctxTrained"))
            .or_else(|| self.trained_of(&cells, &model_path, reading.models_dir))
            .or_else(|| self.trained_of(&cells, &slot_model, reading.models_dir));
        let crash = Self::crash_note(node.get("crash"));
        LiveFacts { is_command, slot_model, model_path, health, effective, note, modalities, crash, model_name, meta, trained }
    }

    /// The first half of a live cell's card: what it is and where it stands.
    pub(super) fn live_card(&self, row: &LiveRow<'_>, facts: &LiveFacts, reading: &ServerReading<'_>) -> Value {
        let LiveRow { client, node, config, cell, port, ip, .. } = row;
        let id = Coerce::str_of(client.get("id"));
        let name = {
            let said = Coerce::stripped(client.get("name"));
            if said.is_empty() { Coerce::stripped(client.get("id")) } else { said }
        };
        let disk_newer =
            node.get("launchDiskNewer").and_then(Value::as_array).map_or_else(Vec::new, |said| LaunchFiles::disk_newer(said));
        json!({
            "id": format!("remote:{cell}"), "cellId": cell,
            "name": name, "port": port, "host": ip, "model": facts.model_name,
            "cellLabel": self.app.runners.for_config(config).artifact_label(config, reading.quant_words),
            "cellMeta": facts.meta, "modelPath": facts.model_path,
            "modelStore": self.launch_in_library(config, &facts.slot_model, reading.config, reading.locations),
            "launchFresh": LaunchFiles::new(config, &facts.slot_model).fresh(reading.fresh_report, reading.models_dir),
            "launchDiskNewer": disk_newer,
            "mmproj": Coerce::text(node.get("mmprojPath")),
            "specDraft": Coerce::text(node.get("specPath")),
            "specType": Coerce::text(node.get("specType")),
            "status": Self::live_status(row, facts), "service": "", "gpuIndexes": [], "isRemote": true,
            "clientId": id, "clientIp": ip, "gpuName": Self::gpu_name_of(client),
            "uptimeSec": node.get("uptimeSec"), "pid": node.get("pid"),
            "pids": node.get("pids").filter(|said| Coerce::truthy(Some(*said))).cloned().unwrap_or_else(|| json!([])),
            "ramBytes": node.get("ramBytes"), "phase": facts.effective,
        })
    }

    /// The second half: how far it is, what it served, what its slot keeps.
    pub(super) fn live_progress(&self, row: &LiveRow<'_>, facts: &LiveFacts) -> Value {
        let LiveRow { client, node, slot, config, cell, phase, running, .. } = row;
        let running = *running;
        let count = |key: &str| {
            let said = facts.health.body.as_ref().and_then(|own| own.get(key)).and_then(Value::as_i64).filter(|said| *said != 0);
            said.unwrap_or_else(|| Coerce::whole(node.get(key)))
        };
        let (boot_enabled, boot_supported) = Self::boot_fields(client, cell);
        let runner = self.app.runners.for_config(config);
        let ctx_max = node
            .get("ctxMax")
            .filter(|said| Coerce::truthy(Some(*said)))
            .cloned()
            .unwrap_or_else(|| self.slot_ctx_max(config, facts.trained));
        let last_error: String =
            if phase == "error" { Coerce::text(node.get("lastError")).chars().take(500).collect() } else { String::new() };
        let kept_list = |key: &str| slot.and_then(|slot| slot.get(key)).filter(|said| Coerce::truthy(Some(*said))).cloned();
        json!({
            "modelReady": running.then(|| facts.health.word.as_deref() == Some("ok")),
            "downloadedBytes": count("downloadedBytes"),
            "totalBytes": count("totalBytes"),
            "downloadingFile": Coerce::text(node.get("downloadingFile")),
            "downloadBytesPerSec": node.get("downloadBytesPerSec"),
            "readBytes": node.get("readBytes"), "readBytesPerSec": node.get("readBytesPerSec"),
            "modelBytes": node.get("modelBytes"), "promptTps": node.get("promptTps"), "genTps": node.get("genTps"),
            "requestsProcessing": node.get("requestsProcessing"),
            "noMetrics": node.get("noMetrics") == Some(&json!(true)),
            "metricsNext": slot.is_some() && runner.row().llama_config && LlamaArgs::metrics_on(config),
            "schedule": kept_list("schedule"),
            "ctxMax": ctx_max,
            "ctxServed": Self::positive_int(node.get("ctxMax")),
            "ctxTrained": facts.trained,
            "ctxUsed": node.get("ctxUsed"), "modalities": facts.modalities,
            "lastError": last_error,
            "isSlot": slot.is_some(), "isController": false, "slotConfig": config,
            "cacheModels": Coerce::truthy(slot.and_then(|slot| slot.get("cacheModels"))),
            "commandHistory": kept_list("commandHistory").unwrap_or_else(|| json!([])),
            "savedCommand": if facts.is_command { self.saved_command(config) } else { String::new() },
            "crash": facts.crash,
            "vllmStats": if running && RunnerRegistry::runner_id(config) == "vllm" { Self::vllm_stats(node) } else { Value::Null },
            "bootEnabled": boot_enabled, "bootSupported": boot_supported,
        })
    }
}
