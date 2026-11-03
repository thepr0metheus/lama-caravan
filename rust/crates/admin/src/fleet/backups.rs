//! A node's saved launch configs, kept on the controller.

use super::launch::LaunchScript;
use crate::app::App;
use crate::config::fields::ConfigFields;
use files::AtomicFile;
use os::LocalTime;
use rules::{AppError, Coerce, PythonJson};
use serde_json::{Map, Value, json};
use std::path::{Component, Path};

/// The backups of this controller.
pub struct ConfigBackups<'app> {
    app: &'app App,
}

impl<'app> ConfigBackups<'app> {
    /// The backups of `app`.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    /// One path segment, a host id or a GPU's model, as a folder's name.
    fn safe_segment(value: &str, fallback: &str) -> String {
        let mut out = String::new();
        let mut in_run = false;
        for letter in Coerce::strip(value).chars() {
            if letter.is_ascii_alphanumeric() || matches!(letter, '.' | '_' | '-') {
                out.push(letter);
                in_run = false;
            } else if !in_run {
                out.push('-');
                in_run = true;
            }
        }
        let cut: String = out.trim_matches(['-', '.']).chars().take(80).collect();
        if cut.is_empty() { fallback.to_string() } else { cut }
    }

    /// The folder of a backup's compute target.
    fn target_segment(config: &Value, gpu_name: &str) -> String {
        if Coerce::stripped(config.get("N_GPU_LAYERS")) == "0" { "CPU".to_string() } else { Self::safe_segment(gpu_name, "GPU") }
    }

    fn meta(config: &Value) -> Map<String, Value> {
        let path = Coerce::text(config.get("MODEL_FILE"));
        let name = Path::new(&path).file_name().map_or_else(String::new, |name| name.to_string_lossy().into_owned());
        let mut out = Map::new();
        out.insert("modelName".to_string(), json!(name));
        out.insert("modelPath".to_string(), json!(path));
        out.insert("port".to_string(), json!(Coerce::text(config.get("PORT"))));
        out.insert("ctxSize".to_string(), json!(Coerce::text(config.get("CTX_SIZE"))));
        out.insert("gpuLayers".to_string(), json!(Coerce::text(config.get("N_GPU_LAYERS"))));
        out
    }

    /// A node's saved configs, the newest first.
    pub fn list(&self, host_id: &str) -> Result<Value, AppError> {
        let host_id = Coerce::strip(host_id);
        if host_id.is_empty() {
            return Err(AppError::new("hostId is required"));
        }
        let host_dir = self.app.paths.server_backups_dir.join(Self::safe_segment(host_id, "_"));
        let mut found: Vec<(String, std::path::PathBuf)> = Vec::new();
        for target in std::fs::read_dir(&host_dir).into_iter().flatten().flatten() {
            for file in std::fs::read_dir(target.path()).into_iter().flatten().flatten() {
                let path = file.path();
                if path.extension().is_some_and(|extension| extension == "json") {
                    found.push((path.to_string_lossy().into_owned(), path));
                }
            }
        }
        found.sort();
        found.reverse();
        let mut rows = Vec::new();
        for (_, path) in found {
            let Some(payload) = std::fs::read(&path).ok().and_then(|raw| serde_json::from_slice::<Value>(&raw).ok()) else {
                continue;
            };
            let config = payload.get("config").filter(|said| Coerce::truthy(Some(*said))).cloned().unwrap_or_else(|| json!({}));
            let target =
                path.parent().and_then(Path::file_name).map_or_else(String::new, |name| name.to_string_lossy().into_owned());
            let name = path.file_name().map_or_else(String::new, |name| name.to_string_lossy().into_owned());
            let mut row = json!({
                "filename": format!("{target}/{name}"), "target": target,
                "savedAt": Coerce::text(payload.get("savedAt")), "name": Coerce::text(payload.get("name")), "config": config,
            });
            for (key, said) in Self::meta(&config) {
                Coerce::put(&mut row, &key, said);
            }
            rows.push(row);
        }
        Ok(json!({"ok": true, "hostId": host_id, "configs": rows}))
    }

    /// The posted launch config saved as a named backup.
    pub fn save(&self, body: &Value) -> Result<Value, AppError> {
        let host_id = Coerce::stripped(body.get("hostId"));
        if host_id.is_empty() {
            return Err(AppError::new("hostId is required"));
        }
        let config =
            body.get("config").filter(|config| config.is_object() && !Coerce::stripped(config.get("MODEL_FILE")).is_empty());
        let config = config.ok_or_else(|| AppError::new("a config with MODEL_FILE is required"))?;
        let name = LaunchScript::sanitize_snapshot_name(&Coerce::text(body.get("name")));
        if name.is_empty() {
            return Err(AppError::new("Snapshot name is required"));
        }
        let target = Self::target_segment(config, &Coerce::text(body.get("gpuName")));
        let stamp = LocalTime::of(self.app.now_whole()).map_or_else(String::new, |at| at.compact());
        let folder =
            self.app.paths.server_backups_dir.join(Self::safe_segment(&host_id, "_")).join(Self::safe_segment(&target, "_"));
        std::fs::create_dir_all(&folder).map_err(|error| AppError::with_status(error.to_string(), 500))?;
        let merged: Map<String, Value> = ConfigFields::ALL
            .iter()
            .map(|key| {
                (
                    (*key).to_string(),
                    json!(
                        config.get(*key).map_or_else(String::new, |said| Coerce::strip(&Coerce::str_of(Some(said))).to_string())
                    ),
                )
            })
            .collect();
        let payload = json!({"hostId": host_id, "target": target, "name": name, "savedAt": stamp, "config": merged});
        let file = format!("{stamp}-{name}.json");
        let mut text = PythonJson::indented_letters(&payload);
        text.push('\n');
        AtomicFile::write(&folder.join(&file), text.as_bytes()).map_err(|error| AppError::with_status(error.to_string(), 500))?;
        Ok(json!({"ok": true, "hostId": host_id, "filename": format!("{target}/{file}"), "savedAt": stamp}))
    }

    /// A node's backup deleted from the controller's store.
    pub fn delete(&self, body: &Value) -> Result<Value, AppError> {
        let (host_id, filename) = (Coerce::stripped(body.get("hostId")), Coerce::stripped(body.get("filename")));
        if host_id.is_empty() {
            return Err(AppError::new("hostId is required"));
        }
        if filename.is_empty() {
            return Err(AppError::new("filename is required"));
        }
        let inside = Path::new(&filename).components().all(|part| matches!(part, Component::Normal(_)));
        let is_json = Path::new(&filename).extension().is_some_and(|extension| extension == "json");
        if !inside || !is_json {
            return Err(AppError::new("invalid backup path"));
        }
        let target = self.app.paths.server_backups_dir.join(Self::safe_segment(&host_id, "_")).join(&filename);
        if !target.exists() {
            return Err(AppError::with_status("Backup file was not found", 404));
        }
        std::fs::remove_file(&target).map_err(|error| AppError::with_status(error.to_string(), 500))?;
        Ok(json!({"ok": true, "hostId": host_id, "deleted": filename}))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_segment_is_a_plain_folder_name() {
        assert_eq!(ConfigBackups::safe_segment("RTX 5090 Ti/x", "_"), "RTX-5090-Ti-x");
        assert_eq!(ConfigBackups::safe_segment("..", "_"), "_");
        assert_eq!(ConfigBackups::target_segment(&json!({"N_GPU_LAYERS": "0"}), "RTX"), "CPU");
        assert_eq!(ConfigBackups::target_segment(&json!({}), ""), "GPU");
    }
}
