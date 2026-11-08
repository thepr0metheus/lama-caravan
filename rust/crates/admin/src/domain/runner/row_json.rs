//! A runner's row as the browser reads it.

use super::{PageSpec, RunnerRow};
use serde_json::{Map, Value, json};

/// The registry row as the frontend has always received it.
pub(super) struct RowJson;

impl RowJson {
    pub(super) fn of(row: &RunnerRow, plan: Value, keeps_ram: bool) -> Value {
        let mut out = Map::new();
        out.insert("id".to_string(), json!(row.id));
        out.insert("sharedPicker".to_string(), json!(row.shared_picker));
        out.insert("modelField".to_string(), json!(row.model_field));
        out.insert("icon".to_string(), json!(row.icon));
        out.insert("labelKey".to_string(), json!(row.label_key));
        out.insert("benefitsKey".to_string(), json!(row.benefits_key));
        out.insert("formats".to_string(), json!(row.formats));
        out.insert("artifacts".to_string(), json!(row.artifacts));
        out.insert("health".to_string(), json!(row.health));
        out.insert("api".to_string(), json!(row.api));
        out.insert("minCompute".to_string(), Value::Null);
        out.insert("tokenContext".to_string(), json!(row.token_context));
        out.insert("commandPath".to_string(), json!(row.command_path));
        out.insert("llamaConfig".to_string(), json!(row.llama_config));
        out.insert("editorTab".to_string(), json!(row.editor_tab));
        out.insert("engineCell".to_string(), json!(row.engine_cell));
        out.insert("ggufArchs".to_string(), json!(row.gguf_archs));
        out.insert("stArchs".to_string(), json!(row.st_archs));
        out.insert("contextField".to_string(), json!(row.context_field));
        out.insert("vramPlan".to_string(), plan);
        out.insert("keepsRam".to_string(), json!(keeps_ram));
        Self::add_said_ones(row, &mut out);
        Value::Object(out)
    }

    /// Said only when there is something to say: a row without them reads as before.
    fn add_said_ones(row: &RunnerRow, out: &mut Map<String, Value>) {
        if !row.minus_key.is_empty() {
            out.insert("minusKey".to_string(), json!(row.minus_key));
        }
        if !row.needs_key.is_empty() {
            out.insert("needsKey".to_string(), json!(row.needs_key));
        }
        for (said, key) in [
            (row.gpu_only, "gpuOnly"),
            (row.one_card, "oneCard"),
            (row.auto_device, "autoDevice"),
            (row.work_folder, "workFolder"),
        ] {
            if said {
                out.insert(key.to_string(), json!(true));
            }
        }
        if !row.own_companions.is_empty() {
            out.insert("ownCompanions".to_string(), json!(row.own_companions));
        }
        if !row.format_requirements.is_empty() {
            let gates: Map<String, Value> =
                row.format_requirements.iter().map(|(quant, compute)| ((*quant).to_string(), json!(compute))).collect();
            out.insert("formatRequirements".to_string(), Value::Object(gates));
        }
        if !row.talk.modes.is_empty() {
            out.insert("talk".to_string(), row.talk.as_json());
        }
        if !row.live.path.is_empty() {
            out.insert("live".to_string(), json!({"protocol": row.live.protocol}));
        }
        if !row.page.field.is_empty() {
            out.insert("page".to_string(), json!({"field": row.page.field, "pattern": PageSpec::PATTERN}));
        }
        if let Some(launcher) = &row.launcher {
            out.insert("launcher".to_string(), json!(launcher.launcher));
            out.insert("launcherArgs".to_string(), json!(launcher.args));
            out.insert("folderRule".to_string(), json!(launcher.folder_rule));
        }
    }
}
