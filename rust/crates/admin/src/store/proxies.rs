//! `agent-proxies.json`: the document the board is drawn from. Its write is the graph's only protection: the file is backed up whenever the copy on disk still has graph nodes, and a payload with NO graph does not overwrite a file that HAS one. The read upgrades the pre-rename schema in place.

use super::base::Unreadable;
use files::AtomicFile;
use rules::{Coerce, PythonJson};
use serde_json::{Value, json};
use std::path::{Path, PathBuf};

/// The proxy document. It is read per call, not held: it is written by the panel AND read by a separate proxy process that watches the file's mtime.
pub struct ProxyStore {
    path: PathBuf,
}

impl ProxyStore {
    const LEGACY_ROUTER_ID: &'static str = "sb:default";
    /// What a route's router is by default.
    pub const DEFAULT_ROUTER_ID: &'static str = "router:default";
    /// What a timestamped copy is called.
    const BACKUP_SUFFIX: &'static str = "bak-graph";
    /// How many of those to keep: a copy per save, never removed, left 13 678 of them beside the file (2026-09-20).
    const BACKUPS_KEPT: usize = 20;

    /// The store of the file at `path`.
    pub fn new(path: PathBuf) -> Self {
        Self { path }
    }

    /// Where it lives.
    pub fn path(&self) -> &Path {
        &self.path
    }

    /// The document as stored, schema-upgraded. `default` when unreadable: a file we cannot parse, or one of the wrong shape, is kept once under `.unreadable-<stamp>`, as the next write would replace it.
    pub fn payload(&self, default: Value, stamp: &str) -> Value {
        let Ok(raw) = std::fs::read(&self.path) else {
            return default;
        };
        match serde_json::from_slice::<Value>(&raw) {
            Ok(document) if document.is_object() => Self::upgrade(document),
            _ => {
                Unreadable::keep(&self.path, stamp);
                default
            }
        }
    }

    /// Pre-rename `switchboard` schema to `router`, idempotent: a file already in the new shape has nothing left to match.
    pub fn upgrade(mut payload: Value) -> Value {
        let Some(fields) = payload.as_object_mut() else {
            return payload;
        };
        if !fields.contains_key("routers")
            && fields.get("switchboards").is_some_and(Value::is_array)
            && let Some(routers) = fields.shift_remove("switchboards")
        {
            fields.insert("routers".to_string(), routers);
        }
        for router in fields.get_mut("routers").and_then(Value::as_array_mut).into_iter().flatten() {
            if router.get("id").and_then(Value::as_str) == Some(Self::LEGACY_ROUTER_ID) {
                router["id"] = json!(Self::DEFAULT_ROUTER_ID);
            }
        }
        for route in fields.get_mut("routes").and_then(Value::as_array_mut).into_iter().flatten() {
            let Some(row) = route.as_object_mut() else {
                continue;
            };
            if !row.contains_key("routerId")
                && let Some(said) = row.shift_remove("switchboardId")
            {
                row.insert("routerId".to_string(), said);
            }
            if row.get("routerId").and_then(Value::as_str) == Some(Self::LEGACY_ROUTER_ID) {
                row.insert("routerId".to_string(), json!(Self::DEFAULT_ROUTER_ID));
            }
        }
        payload
    }

    /// Every graph node in a payload, across all its routers.
    pub fn graph_nodes(payload: &Value) -> Vec<&Value> {
        let routers = payload.get("routers").and_then(Value::as_array).into_iter().flatten();
        routers.filter_map(|router| router.get("graph")?.get("nodes")?.as_array()).flatten().collect()
    }

    /// Backs the file up, and puts its graph back if the payload lost it. Failures are kept quiet on purpose: this is a safety net around the write, and a net that can refuse the write is worse than no net.
    pub fn protect_graph(&self, mut payload: Value, stamp: &str) -> Value {
        let Ok(text) = std::fs::read(&self.path) else {
            return payload;
        };
        let Ok(old) = serde_json::from_slice::<Value>(&text) else {
            return payload;
        };
        if Self::graph_nodes(&old).is_empty() {
            return payload;
        }
        let stem = self.stem();
        // In silence, as above.
        drop(std::fs::write(self.path.with_file_name(format!("{stem}.json.{}-{stamp}", Self::BACKUP_SUFFIX)), &text));
        self.prune_backups();
        if !Self::graph_nodes(&payload).is_empty() {
            return payload;
        }
        // absent-ok: an old file with no routers has no graph to give back; the nodes above came from somewhere, this is only for the type.
        let old_routers = Coerce::list(old.get("routers"));
        for router in payload.get_mut("routers").and_then(Value::as_array_mut).into_iter().flatten() {
            let keeps_nodes =
                router.get("graph").and_then(|graph| graph.get("nodes")).is_some_and(|nodes| Coerce::truthy(Some(nodes)));
            let id = router.get("id").cloned();
            let found =
                old_routers.iter().find(|row| id.is_some() && Coerce::truthy(row.get("id")) && row.get("id") == id.as_ref());
            if let (false, Some(found)) = (keeps_nodes, found) {
                let graph = found
                    .get("graph")
                    .filter(|graph| Coerce::truthy(Some(*graph)))
                    .or_else(|| router.get("graph").filter(|graph| Coerce::truthy(Some(*graph))));
                let graph = graph.cloned().unwrap_or_else(|| json!({}));
                router["graph"] = graph;
            }
        }
        payload
    }

    fn stem(&self) -> String {
        self.path.file_stem().map_or_else(String::new, |stem| stem.to_string_lossy().into_owned())
    }

    /// Leaves the newest copies and removes the rest. By the stamp in the name, not by mtime: the stamp says which save a copy belongs to. A copy that will not go is left where it is.
    fn prune_backups(&self) {
        let Some(parent) = self.path.parent() else {
            return;
        };
        let start = format!("{}.json.{}-", self.stem(), Self::BACKUP_SUFFIX);
        let Ok(names) = std::fs::read_dir(parent) else {
            return;
        };
        let mut copies: Vec<PathBuf> = names
            .flatten()
            .filter(|name| name.file_name().to_string_lossy().starts_with(&start))
            .map(|name| name.path())
            .collect();
        copies.sort();
        let doomed = copies.len().saturating_sub(Self::BACKUPS_KEPT);
        for old in copies.iter().take(doomed) {
            // Left where it is, as above.
            drop(std::fs::remove_file(old));
        }
    }

    /// The file, indented, UTF-8 as itself, with a trailing newline: this document is read by a person during an incident and by `git diff` afterwards.
    pub fn write(&self, payload: &Value) -> std::io::Result<()> {
        let mut text = PythonJson::indented_letters(payload);
        text.push('\n');
        AtomicFile::write(&self.path, text.as_bytes())
    }
}
