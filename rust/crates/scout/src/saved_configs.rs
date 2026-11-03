//! Saved launch parameters of llama cells, kept by hand.

use crate::errors::AppError;
use files::AtomicFile;
use os::LocalTime;
use serde_json::{Value, json};
use std::fs;
use std::path::{Path, PathBuf};

/// Snapshots of a llama cell's launch parameters, saved on request only, never automatically on start, as `llama-node.bak.<stamp>.json` in a folder next to the scout's state.
pub struct SavedConfigs {
    folder: PathBuf,
}

/// What a snapshot says.
pub struct SavedLaunch<'a> {
    /// The model it runs.
    pub model_path: &'a str,
    /// The port.
    pub port: i64,
    /// `-ngl`.
    pub gpu_layers: i64,
    /// `--ctx-size`.
    pub ctx_size: i64,
}

impl SavedConfigs {
    const PREFIX: &'static str = "llama-node.bak.";
    const SHOWN: usize = 20;

    /// The snapshots in `folder`.
    pub fn new(folder: PathBuf) -> Self {
        Self { folder }
    }

    /// Saves a timestamped backup of the launch parameters.
    pub fn save(&self, launch: &SavedLaunch<'_>, now: i64) -> std::io::Result<()> {
        fs::create_dir_all(&self.folder)?;
        // absent-ok: a system that cannot place the moment still names the file by its seconds.
        let stamp = LocalTime::of(now).map_or_else(|| now.to_string(), |moment| moment.compact());
        let name = Path::new(launch.model_path).file_name().map_or_else(String::new, |name| name.to_string_lossy().into_owned());
        let data = json!({
            "savedAt": stamp,
            "savedAtTs": now,
            "modelPath": launch.model_path,
            "modelName": name,
            "port": launch.port,
            "gpuLayers": launch.gpu_layers,
            "ctxSize": launch.ctx_size,
        });
        let text = serde_json::to_string_pretty(&data).map_err(std::io::Error::other)?;
        AtomicFile::write(&self.folder.join(format!("{}{stamp}.json", Self::PREFIX)), text.as_bytes())
    }

    /// The saved configs, newest first, 20 at most. One that does not read is passed over.
    pub fn listing(&self) -> Vec<Value> {
        let Ok(entries) = fs::read_dir(&self.folder) else {
            return Vec::new();
        };
        let mut names: Vec<String> = entries
            .flatten()
            .map(|entry| entry.file_name().to_string_lossy().into_owned())
            .filter(|name| name.starts_with(Self::PREFIX) && name.ends_with(".json"))
            .collect();
        names.sort_unstable_by(|left, right| right.cmp(left));
        names.truncate(Self::SHOWN);
        names
            .into_iter()
            .filter_map(|name| {
                let raw = fs::read(self.folder.join(&name)).ok()?;
                let mut data = serde_json::from_slice::<Value>(&raw).ok()?;
                data.as_object_mut()?.insert("filename".to_string(), json!(name));
                Some(data)
            })
            .collect()
    }

    /// Deletes a saved config by its name: only its last part counts, so no path leaves the folder.
    pub fn delete(&self, filename: &str) -> Result<(), AppError> {
        let name = Path::new(filename).file_name().map_or_else(String::new, |name| name.to_string_lossy().into_owned());
        if !name.starts_with(Self::PREFIX) || !name.ends_with(".json") {
            return Err(AppError::new("invalid backup filename"));
        }
        let target = self.folder.join(&name);
        if !target.exists() {
            return Err(AppError::with_status(format!("backup not found: {name}"), 404));
        }
        fs::remove_file(target).map_err(|error| AppError::with_status(error.to_string(), 500))
    }
}
