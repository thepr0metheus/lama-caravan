//! What else is on the models disk: safetensors checkpoints, whisper and translate caches, chat templates.

use super::walk::{RelPath, Walker};
use crate::app::App;
use crate::domain::runner::Config;
use rules::Coerce;
use serde_json::{Map, Value, json};
use std::collections::{BTreeMap, HashMap};
use std::os::unix::fs::MetadataExt;
use std::path::{Path, PathBuf};
use std::sync::{Mutex, PoisonError};

/// What each checkpoint's config.json said, by its file's (mtime, size).
#[derive(Default)]
pub struct CheckpointConfigs {
    held: Mutex<HashMap<String, (i64, i64, CheckpointConfig)>>,
}

/// What a checkpoint's config.json says of it.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct CheckpointConfig {
    /// Its `model_type`, else the first of its architectures.
    pub kind: String,
    /// The window its weights were trained with, or 0.
    pub window: i64,
    /// What a token of KV cache weighs, in bytes, when the file states what that takes.
    pub kv_per_token: Option<i64>,
}

/// The view.
pub struct ModelCheckpoints<'app> {
    pub(super) app: &'app App,
}

impl<'app> ModelCheckpoints<'app> {
    /// The words a quantization's folder is told by.
    pub const FORMAT_HINTS: [&'static str; 12] =
        ["NVFP4", "MXFP4", "AWQ", "GPTQ", "AUTOROUND", "FP8", "INT4", "W4A16", "BNB", "BF16", "FP16", "FP32"];
    const CONFIG_MOST_BYTES: i64 = 16 * 1024 * 1024;

    /// The view.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    /// The trained window a parsed config.json states, or 0.
    fn window_of(doc: &Value) -> i64 {
        const PATHS: [&[&str]; 5] = [
            &["max_position_embeddings"],
            &["text_config", "max_position_embeddings"],
            &["thinker_config", "text_config", "max_position_embeddings"],
            &["llm_config", "max_position_embeddings"],
            &["language_config", "max_position_embeddings"],
        ];
        for keys in PATHS {
            let said = keys.iter().try_fold(doc, |value, key| value.get(*key));
            if let Some(window) = said.and_then(Value::as_i64).filter(|window| *window > 0) {
                return window;
            }
        }
        0
    }

    /// The bytes of KV cache one token takes, as vLLM counts them: a key and a value on each layer, each `kv_heads × head_dim` numbers. It refuses to start when one request of
    /// the longest length does not fit what the weights leave (the owner's check, 2026-11-01: 0.88 GiB at a length of 8192 on a card the form called enough). Any figure the
    /// file does not state leaves this unknown.
    fn kv_per_token(doc: &Value) -> Option<i64> {
        const TEXT: [&[&str]; 4] = [&["text_config"], &["thinker_config", "text_config"], &["llm_config"], &["language_config"]];
        let text = TEXT.iter().find_map(|keys| keys.iter().try_fold(doc, |value, key| value.get(*key))).unwrap_or(doc);
        let whole = |key: &str| text.get(key).and_then(Value::as_i64).filter(|said| *said > 0);
        let layers = whole("num_hidden_layers")?;
        let heads = whole("num_attention_heads")?;
        let head = whole("head_dim").or_else(|| Some(whole("hidden_size")? / heads)).filter(|said| *said > 0)?;
        let kv_heads = whole("num_key_value_heads").unwrap_or(heads);
        let word =
            ["dtype", "torch_dtype"].iter().find_map(|key| text.get(*key).or_else(|| doc.get(*key)).and_then(Value::as_str));
        let bytes = match word {
            Some("float32" | "float") => 4,
            Some("float64" | "double") => 8,
            _ => 2,
        };
        Some(2 * layers * kv_heads * head * bytes)
    }

    /// What a checkpoint's config.json says of it, kept by (path, mtime, size).
    pub fn config_of(&self, directory: &Path) -> CheckpointConfig {
        let file = directory.join("config.json");
        let Ok(meta) = std::fs::metadata(&file) else {
            return CheckpointConfig::default();
        };
        let (key, mtime, size) = (file.to_string_lossy().into_owned(), meta.mtime(), meta.size() as i64);
        let mut held = self.app.checkpoint_configs.held.lock().unwrap_or_else(PoisonError::into_inner);
        if let Some((_, _, config)) = held.get(&key).filter(|(at, weight, _)| *at == mtime && *weight == size) {
            return config.clone();
        }
        let hit = Self::read_config(&file, size);
        held.insert(key, (mtime, size, hit.clone()));
        hit
    }

    fn read_config(file: &Path, size: i64) -> CheckpointConfig {
        if size > Self::CONFIG_MOST_BYTES {
            return CheckpointConfig::default();
        }
        let Some(doc) =
            std::fs::read(file).ok().and_then(|raw| serde_json::from_str::<Value>(&String::from_utf8_lossy(&raw)).ok())
        else {
            return CheckpointConfig::default();
        };
        let first_arch = doc.get("architectures").and_then(Value::as_array).and_then(|list| list.first());
        let kind =
            if Coerce::truthy(doc.get("model_type")) { Coerce::text(doc.get("model_type")) } else { Coerce::text(first_arch) };
        CheckpointConfig { kind, window: Self::window_of(&doc), kv_per_token: Self::kv_per_token(&doc) }
    }

    /// The snapshot an HF cache's `refs/main` names, or none.
    fn snapshot_of(directory: &Path) -> Option<PathBuf> {
        let reference = std::fs::read_to_string(directory.join("refs/main")).ok()?;
        let reference = Coerce::strip(&reference);
        if reference.is_empty() || reference.contains('/') || matches!(reference, "." | "..") {
            return None;
        }
        let snapshot = directory.join("snapshots").join(reference);
        snapshot.is_dir().then_some(snapshot)
    }

    /// What a model folder's config.json says, for the rows that list it.
    pub fn facts(&self, directory: &Path) -> Map<String, Value> {
        let config = match Self::snapshot_of(directory) {
            Some(snapshot) => self.config_of(&snapshot),
            None => self.config_of(directory),
        };
        let mut out = Map::new();
        if !config.kind.is_empty() {
            out.insert("arch".to_string(), json!(config.kind));
        }
        if config.window != 0 {
            out.insert("contextLength".to_string(), json!(config.window));
        }
        if let Some(bytes) = config.kv_per_token {
            out.insert("kvPerToken".to_string(), json!(bytes));
        }
        out
    }

    /// A label for a cell's model, from the path the config stores.
    pub fn display_name(model_path: &str) -> String {
        let raw = Coerce::strip(model_path);
        let path = raw.trim_matches('/');
        if path.is_empty() {
            return String::new();
        }
        let parts: Vec<&str> = path.split('/').filter(|part| !part.is_empty()).collect();
        // absent-ok: an empty path has no last word.
        let last = parts.last().copied().unwrap_or_default();
        if path.to_lowercase().ends_with(".gguf") {
            // absent-ok: an empty path has no last word.
            return path.rsplit('/').next().unwrap_or_default().to_string();
        }
        if raw.starts_with('/') || raw.starts_with('~') {
            if let Some(third) = parts
                .len()
                .checked_sub(3)
                .and_then(|at| parts.get(at))
                .filter(|_| Self::FORMAT_HINTS.contains(&last.to_uppercase().as_str()))
            {
                return (*third).to_string();
            }
            return last.to_string();
        }
        if parts.len() == 2 {
            return last.to_string();
        }
        // absent-ok: an empty path has no first word.
        parts.first().copied().unwrap_or_default().to_string()
    }

    /// Safetensors checkpoints in the models tree.
    pub fn st_artifacts(&self, config: &Config) -> Vec<Value> {
        let models_dir = self.app.models_dir_of(config);
        if !models_dir.exists() {
            return Vec::new();
        }
        let mut by_dir: BTreeMap<PathBuf, (i64, i64, i64)> = BTreeMap::new();
        for path in Walker::ending_in(&models_dir, ".safetensors") {
            let Ok(meta) = std::fs::metadata(&path) else {
                continue;
            };
            let (Some(parent), true) = (path.parent(), meta.is_file()) else {
                continue;
            };
            let entry = by_dir.entry(parent.to_path_buf()).or_default();
            entry.0 += meta.size() as i64;
            entry.1 += 1;
            entry.2 = entry.2.max(meta.mtime());
        }
        let mut rows = Vec::new();
        for (folder, (size, files, mtime)) in by_dir {
            // absent-ok: what lies outside the folder has no path from it, and is left out by the name.
            let rel = Walker::relative(&folder, &models_dir).unwrap_or_default();
            let parts: Vec<&str> = rel.split('/').filter(|part| !part.is_empty()).collect();
            let format = Self::format_of(&rel, &parts);
            let config = self.config_of(&folder);
            let mut row = Map::new();
            row.insert("path".to_string(), json!(if rel.is_empty() { "." } else { rel.as_str() }));
            row.insert("name".to_string(), json!(parts.first().copied().unwrap_or(rel.as_str())));
            row.insert("kind".to_string(), json!("safetensors"));
            row.insert("arch".to_string(), json!(config.kind));
            if config.window != 0 {
                row.insert("contextLength".to_string(), json!(config.window));
            }
            if let Some(bytes) = config.kv_per_token {
                row.insert("kvPerToken".to_string(), json!(bytes));
            }
            row.insert("format".to_string(), json!(format));
            row.insert("files".to_string(), json!(files));
            row.insert("size".to_string(), json!(size));
            row.insert("sizeGb".to_string(), json!(Coerce::rounded(size as f64 / 1_073_741_824.0, 2)));
            row.insert("mtime".to_string(), json!(mtime));
            rows.push(Value::Object(row));
        }
        rows
    }

    fn format_of(rel: &str, parts: &[&str]) -> String {
        if let Some(segment) = parts.iter().rev().find(|segment| Self::FORMAT_HINTS.contains(&segment.to_uppercase().as_str())) {
            return segment.to_uppercase();
        }
        let upper = rel.to_uppercase();
        Self::FORMAT_HINTS.iter().find(|hint| upper.contains(**hint)).map_or_else(|| "ST".to_string(), |hint| (*hint).to_string())
    }

    fn dirs_starting(folder: &Path, start: &str) -> Vec<String> {
        let mut names: Vec<String> = std::fs::read_dir(folder)
            .into_iter()
            .flatten()
            .flatten()
            .filter(|entry| entry.path().is_dir())
            .map(|entry| entry.file_name().to_string_lossy().into_owned())
            .filter(|name| name.starts_with(start))
            .collect();
        names.sort();
        names
    }

    /// Which faster-whisper sizes are already on disk: dir names only, no file reads.
    pub fn whisper_sizes(&self, config: &Config) -> Vec<String> {
        let root = self.app.models_dir_of(config).join("whisper");
        Self::dirs_starting(&root, "models--")
            .into_iter()
            .filter(|name| name.contains("faster-whisper-"))
            .filter_map(|name| name.rsplit_once("faster-whisper-").map(|(_, size)| size.to_string()))
            .collect()
    }

    /// NLLB checkpoints already downloaded, as repo ids.
    pub fn translate_models(&self, config: &Config) -> Vec<String> {
        let root = self.app.models_dir_of(config).join("translate");
        let mut out = Vec::new();
        for name in Self::dirs_starting(&root, "models--") {
            let parts: Vec<&str> = name.split("--").collect();
            if let (Some(author), Some(rest)) = (parts.get(1), parts.get(2..).filter(|rest| !rest.is_empty())) {
                out.push(format!("{author}/{}", rest.join("--")));
            }
        }
        out
    }

    /// The chat templates of `llama.cpp`'s folder and of the models folder.
    pub fn chat_templates(&self, config: &Config) -> Vec<Value> {
        let roots = [self.app.paths.llama_home.join("templates"), self.app.models_dir_of(config).join("templates")];
        let mut rows: Vec<Value> = Vec::new();
        for root in roots {
            for suffix in [".jinja", ".jinja2"] {
                let mut names: Vec<PathBuf> = std::fs::read_dir(&root)
                    .into_iter()
                    .flatten()
                    .flatten()
                    .map(|entry| entry.path())
                    .filter(|path| path.is_file() && path.to_string_lossy().ends_with(suffix))
                    .collect();
                names.sort();
                for path in names {
                    let value = path.to_string_lossy().into_owned();
                    if !rows.iter().any(|row| row.get("path").and_then(Value::as_str) == Some(&value)) {
                        rows.push(json!({"path": value, "name": RelPath::name(&value)}));
                    }
                }
            }
        }
        rows
    }

    /// GGUF model files of the configured models folder.
    pub fn gguf_models(&self) -> Value {
        let models_dir = self.app.models_dir();
        if !models_dir.is_dir() {
            return json!({"ok": false, "error": format!("models dir not found: {}", models_dir.display()), "models": []});
        }
        let mut files = Vec::new();
        for path in Walker::ending_in(&models_dir, ".gguf") {
            let name = RelPath::name(&path.to_string_lossy()).to_string();
            let lower = name.to_lowercase();
            if ["mmproj", "vocab", "projector"].iter().any(|word| lower.contains(word)) {
                continue;
            }
            let Ok(meta) = std::fs::metadata(&path) else {
                continue;
            };
            if meta.size() < 1024 {
                continue;
            }
            // absent-ok: what lies outside the folder has no path from it, and is left out by the name.
            let rel = Walker::relative(&path, &models_dir).unwrap_or_default();
            files.push(json!({"path": rel, "name": name, "sizeMiB": (meta.size() as f64 / 1_048_576.0).round_ties_even() as i64, "dir": RelPath::parent(&rel)}));
        }
        json!({"ok": true, "models": files, "modelsDir": models_dir.to_string_lossy()})
    }
}

#[cfg(test)]
mod tests;
