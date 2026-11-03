//! Which models a cell names, and what may go.

use super::checkpoints::ModelCheckpoints;
use super::locator::SplitParts;
use super::walk::{Resolved, Walker};
use crate::app::App;
use crate::common::artifacts::ModelArtifacts;
use crate::domain::host::HostRecord;
use crate::domain::runner::TranslateRunner;
use rules::{AppError, Coerce};
use serde_json::{Map, Value, json};
use std::collections::{BTreeMap, BTreeSet};
use std::os::unix::fs::MetadataExt;
use std::path::{Path, PathBuf};

#[cfg(test)]
mod tests;

/// The view.
pub struct ModelGc<'app> {
    app: &'app App,
}

/// What cells name, and who names it.
#[derive(Debug, Default)]
pub struct References {
    /// The paths named.
    pub refs: BTreeSet<String>,
    /// Who names each, as "host:port", or "legacy" for the controller's own config.
    pub owners: BTreeMap<String, Vec<String>>,
}

impl References {
    fn add(&mut self, value: Option<&Value>, owner: &str) {
        let word = Coerce::stripped(value);
        let rel = word.trim_start_matches('/');
        if rel.is_empty() {
            return;
        }
        self.refs.insert(rel.to_string());
        let owners = self.owners.entry(rel.to_string()).or_default();
        if !owners.iter().any(|said| said == owner) {
            owners.push(owner.to_string());
        }
    }
}

impl<'app> ModelGc<'app> {
    const FILE_FIELDS: [&'static str; 3] = ["MODEL_FILE", "MMPROJ_FILE", "SPEC_DRAFT_MODEL_FILE"];
    const BUSY_PHASES: [&'static str; 5] = ["resolving", "downloading", "loading", "starting", "running"];

    /// The view.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    /// The group a multi-part GGUF belongs to: its own path when it is whole.
    pub fn part_group(rel: &str) -> String {
        let Some(part) = SplitParts::of(rel) else {
            return rel.to_string();
        };
        let (folder, stem, total) = part.group;
        if folder.is_empty() { format!("{stem}-*-of-{total}.gguf") } else { format!("{folder}/{stem}-*-of-{total}.gguf") }
    }

    /// Every model path a cell refers to right now, as relative paths, with who names it.
    pub fn references(&self) -> References {
        let mut found = References::default();
        // absent-ok: a launch config that does not read names no model: the listing still shows the folder.
        let config = self.app.parse_config().unwrap_or_default();
        let models_root = self.app.models_dir_of(&config).to_string_lossy().trim_end_matches('/').to_string();
        for key in Self::FILE_FIELDS {
            found.add(config.get(key), "legacy");
        }
        let slots = self
            .app
            .admin
            .read(|doc| doc.get("topology").and_then(|topology| topology.get("serverSlots")).cloned())
            .unwrap_or_else(|| json!({}));
        for slot in slots.as_object().into_iter().flat_map(|slots| slots.values()) {
            Self::add_slot(slot, &models_root, &mut found);
        }
        found
    }

    fn add_slot(slot: &Value, models_root: &str, found: &mut References) {
        let empty = json!({});
        let config = slot.get("config").filter(|config| Coerce::truthy(Some(*config))).unwrap_or(&empty);
        let word = |key: &str, otherwise: &str| {
            if Coerce::truthy(slot.get(key)) { Coerce::text(slot.get(key)) } else { otherwise.to_string() }
        };
        let owner = format!("{}:{}", word("hostId", "?"), word("port", "?"));
        found.add(slot.get("model"), &owner);
        for key in Self::FILE_FIELDS {
            found.add(config.get(key), &owner);
        }
        let vllm = Coerce::stripped(config.get("VLLM_MODEL"));
        let vllm = vllm.trim_end_matches('/');
        // A path of the models folder, or a place in it as the form says it: a repo id of that shape names nothing there, and keeps nothing.
        let place = vllm.strip_prefix(&format!("{models_root}/")).or_else(|| (!vllm.starts_with('/')).then_some(vllm));
        if let Some(rel) = place.filter(|rel| !rel.is_empty()) {
            found.add(Some(&json!(rel)), &owner);
        }
        let runner = Coerce::stripped(config.get("RUNNER")).to_lowercase();
        if runner == "whisper" {
            let said = Coerce::stripped(config.get("WHISPER_MODEL"));
            let size = if said.is_empty() { "large-v3" } else { said.as_str() };
            found.add(Some(&json!(format!("whisper/models--Systran--faster-whisper-{size}"))), &owner);
        }
        if let ("translate", Some(fields)) = (runner.as_str(), config.as_object()) {
            found.add(Some(&json!(TranslateRunner::cache_folder(fields))), &owner);
        }
    }

    fn group_owners(owners: &BTreeMap<String, Vec<String>>) -> BTreeMap<String, Vec<String>> {
        let mut groups: BTreeMap<String, Vec<String>> = BTreeMap::new();
        for (rel, who) in owners {
            let group = groups.entry(Self::part_group(rel)).or_default();
            for owner in who {
                if !group.contains(owner) {
                    group.push(owner.clone());
                }
            }
        }
        groups
    }

    /// A folder model's row: a checkpoint or a translation, weighed as one.
    fn folder_row(&self, models_dir: &Path, rel: &str, kind: &str, found: &References, running: &BTreeSet<String>) -> Value {
        let (size, mtime) = ModelArtifacts::folder_weight(&models_dir.join(rel));
        // absent-ok: a folder no cell names has no owners.
        let by = found.owners.get(rel).cloned().unwrap_or_default();
        let read_by: Vec<&String> = by.iter().filter(|who| running.contains(*who)).collect();
        let mut row = Map::new();
        row.insert("path".to_string(), json!(rel));
        row.insert("kind".to_string(), json!(kind));
        if matches!(kind, "safetensors" | "translate") {
            row.extend(ModelCheckpoints::of(self.app).facts(&models_dir.join(rel)));
        }
        row.insert("sizeBytes".to_string(), json!(size));
        row.insert("sizeGb".to_string(), json!(Coerce::rounded(size as f64 / 1_073_741_824.0, 2)));
        let now = self.app.now();
        row.insert("ageDays".to_string(), json!(if mtime != 0 { ((now - mtime as f64) / 86400.0).floor() as i64 } else { 0 }));
        row.insert("referenced".to_string(), json!(found.refs.contains(rel)));
        row.insert("referencedBy".to_string(), json!(by));
        row.insert("readBy".to_string(), json!(read_by));
        row.insert("group".to_string(), json!(rel));
        Value::Object(row)
    }

    /// Every GGUF and model folder under the models folder, flagged referenced or unused.
    pub fn list_unused(&self) -> Value {
        let models_dir = self.app.models_dir();
        if !models_dir.is_dir() {
            return json!({"ok": false, "path": models_dir.to_string_lossy(), "error": "models dir not found", "files": []});
        }
        let found = self.references();
        let ref_groups: BTreeSet<String> = found.refs.iter().map(|rel| Self::part_group(rel)).collect();
        let group_owners = Self::group_owners(&found.owners);
        let running = self.running_owners(found.owners.values().flatten().cloned().collect());
        let now = self.app.now();
        let gib = |size: i64| Coerce::rounded(size as f64 / 1_073_741_824.0, 2);
        let mut files = Vec::new();
        for path in Walker::ending_in(&models_dir, ".gguf") {
            let Ok(meta) = std::fs::metadata(&path) else {
                continue;
            };
            // absent-ok: what lies outside the folder has no path from it.
            let rel = Walker::relative(&path, &models_dir).unwrap_or_default();
            let group = Self::part_group(&rel);
            let referenced = found.refs.contains(&rel) || ref_groups.contains(&group);
            let by = found
                .owners
                .get(&rel)
                .filter(|who| !who.is_empty())
                .or_else(|| group_owners.get(&group))
                .cloned()
                // absent-ok: a file with no time reads as old.
                .unwrap_or_default();
            let read_by: Vec<&String> = by.iter().filter(|who| running.contains(*who)).collect();
            let age = ((now - meta.mtime() as f64) / 86400.0).floor() as i64;
            files.push(json!({"path": rel, "sizeBytes": meta.size(), "sizeGb": gib(meta.size() as i64), "ageDays": age, "referenced": referenced, "referencedBy": by, "readBy": read_by, "group": group}));
        }
        for (rel, kind) in ModelArtifacts::dirs(&models_dir) {
            files.push(self.folder_row(&models_dir, &rel, kind, &found, &running));
        }
        let unused: Vec<i64> = files
            .iter()
            .filter(|row| row.get("referenced") != Some(&json!(true)))
            // absent-ok: each row was made with its size above.
            .map(|row| Coerce::i64_or_zero(row.get("sizeBytes")))
            .collect();
        let unused_bytes: i64 = unused.iter().sum();
        json!({"ok": true, "path": models_dir.to_string_lossy(), "files": files, "unusedCount": unused.len(), "unusedGb": Coerce::rounded(unused_bytes as f64 / 1_073_741_824.0, 1)})
    }

    /// Deletes the given relative paths, refusing anything referenced or outside the models folder.
    pub fn delete(&self, body: &Value) -> Result<Value, AppError> {
        let Some(paths) = body.get("files").and_then(Value::as_array).filter(|paths| !paths.is_empty()) else {
            return Err(AppError::new("files must be a non-empty list"));
        };
        let models_dir = self.app.models_dir();
        let root = std::fs::canonicalize(&models_dir).unwrap_or(models_dir);
        let found = self.references();
        let groups: BTreeSet<String> = found.refs.iter().map(|rel| Self::part_group(rel)).collect();
        let folders: BTreeSet<String> = ModelArtifacts::dirs(&root).into_iter().map(|(rel, _)| rel).collect();
        let (mut deleted, mut freed) = (Vec::new(), 0);
        for said in paths {
            let word = Coerce::stripped(Some(said));
            let rel = word.trim_start_matches('/');
            let is_folder = folders.contains(rel.trim_end_matches('/'));
            if !rel.ends_with(".gguf") && !is_folder {
                return Err(AppError::new(format!("not a gguf or a known artifact folder: {rel}")));
            }
            let target: PathBuf = Resolved::under(&root, rel);
            if !target.starts_with(&root) {
                return Err(AppError::new(format!("path escapes the models dir: {rel}")));
            }
            // By the path it comes to as well: `a/../x.gguf` and `x/` are spellings of what a cell may name.
            let clean = target.strip_prefix(&root).map_or_else(|_| rel.to_string(), |inner| inner.to_string_lossy().into_owned());
            let named = |path: &str| found.refs.contains(path) || groups.contains(&Self::part_group(path));
            if named(rel) || named(&clean) {
                return Err(AppError::with_status(format!("refusing to delete a referenced model: {rel}"), 409));
            }
            let gone = if is_folder {
                let size = ModelArtifacts::folder_weight(&target).0;
                std::fs::remove_dir_all(&target).map(|()| size)
            } else {
                std::fs::metadata(&target).and_then(|meta| std::fs::remove_file(&target).map(|()| meta.size() as i64))
            };
            match gone {
                Ok(size) => {
                    deleted.push(rel.to_string());
                    freed += size;
                }
                Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
                Err(error) => return Err(AppError::with_status(format!("delete failed for {rel}: {error}"), 500)),
            }
        }
        Ok(json!({"ok": true, "deleted": deleted, "freedGb": Coerce::rounded(freed as f64 / 1_073_741_824.0, 2)}))
    }

    /// Which of these cells are RUNNING: reading their files, or about to, as "host:port". A machine that does not answer may well be reading: what is not known is taken for yes.
    pub fn running_owners(&self, owners: BTreeSet<String>) -> BTreeSet<String> {
        let hosts = self
            .app
            .admin
            .read(|doc| doc.get("topology").and_then(|topology| topology.get("hosts")).cloned())
            .unwrap_or_else(|| json!({}));
        let (now, ttl) = (self.app.now_whole(), self.app.paths.host_report_ttl);
        let mut out = BTreeSet::new();
        for who in owners {
            let (host, port) = who.rsplit_once(':').unwrap_or(("", who.as_str()));
            let record = hosts.get(host).filter(|record| record.is_object());
            let online = record.is_some_and(|record| HostRecord::liveness(record, now, ttl).0 == "online");
            if !online {
                out.insert(who);
                continue;
            }
            let nodes = record.and_then(|record| record.get("llamaNodes")).and_then(Value::as_array).into_iter().flatten();
            let node = nodes.filter(|node| node.is_object()).find(|node| Coerce::str_of(node.get("port")) == port);
            let busy = node.is_some_and(|node| {
                Coerce::truthy(node.get("running"))
                    || node.get("phase").and_then(Value::as_str).is_some_and(|phase| Self::BUSY_PHASES.contains(&phase))
            });
            if busy {
                out.insert(who);
            }
        }
        out
    }

    /// The cells READING these files right now, as "host:port".
    pub fn holders(&self, rels: &[String]) -> Vec<String> {
        let found = self.references();
        let groups = Self::group_owners(&found.owners);
        let mut wanted = BTreeSet::new();
        for rel in rels {
            wanted.extend(found.owners.get(rel).into_iter().flatten().cloned());
            wanted.extend(groups.get(&Self::part_group(rel)).into_iter().flatten().cloned());
        }
        self.running_owners(wanted).into_iter().collect()
    }
}
