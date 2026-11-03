//! Turns "move these files there" into a job, or into a refusal that says why.

use super::job::{MoveFile, MoveItem, MoveJob};
use crate::app::App;
use crate::models::gc::ModelGc;
use crate::models::stores::{StoreRefused, StoreRegistry};
use net::Randomness;
use rules::Coerce;
use serde_json::{Value, json};
use std::collections::BTreeSet;
use std::os::unix::fs::MetadataExt;
use std::path::Path;

#[cfg(test)]
mod tests;

/// A move that is not started: `StoreRefused`'s shape, a word the page can act on.
pub type MoveRefused = StoreRefused;

/// One end of a move.
struct End {
    id: String,
    name: String,
    path: String,
    kind: &'static str,
    state: String,
    free: Option<f64>,
    detail: String,
}

impl End {
    fn of(rows: &[Value], store_id: &str, side: &str) -> Result<Self, MoveRefused> {
        let Some(row) = rows.iter().find(|row| row.get("id").and_then(Value::as_str) == Some(store_id)) else {
            return Err(StoreRefused::refused(format!("no such store: {store_id}"), &format!("no-{side}"), 404));
        };
        let state = Coerce::text(row.get("state"));
        Ok(Self {
            id: Coerce::text(row.get("id")),
            name: Coerce::text(row.get("name")),
            path: Coerce::text(row.get("path")),
            kind: if row.get("role").and_then(Value::as_str) == Some("local") { "local" } else { "library" },
            state: if state.is_empty() { "unknown".to_string() } else { state },
            free: row.get("free").and_then(Value::as_f64),
            detail: Coerce::text(row.get("detail")),
        })
    }

    fn state_words(&self, who: &str) -> String {
        let detail = if self.detail.is_empty() { String::new() } else { format!(": {}", self.detail) };
        format!("{who} is {}{detail}", self.state)
    }

    fn usable(&self) -> bool {
        matches!(self.state.as_str(), "ok" | "low-space")
    }
}

/// The planner.
pub struct MovePlanner<'app> {
    app: &'app App,
}

impl<'app> MovePlanner<'app> {
    const SPACE_MARGIN: i64 = 2 << 30;

    /// The view.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    /// What the source holds, as the plan needs it, and its root.
    fn source_files(&self, source: &End) -> Result<(Vec<Value>, String), MoveRefused> {
        if source.kind == "local" {
            let listing = ModelGc::of(self.app).list_unused();
            if !Coerce::truthy(listing.get("ok")) {
                let words = if Coerce::truthy(listing.get("error")) {
                    Coerce::text(listing.get("error"))
                } else {
                    "the models directory is not readable".to_string()
                };
                return Err(StoreRefused::refused(words, "no-source", 409));
            }
            return Ok((Coerce::list(listing.get("files")), Coerce::text(listing.get("path"))));
        }
        let rows = StoreRegistry::of(self.app).library_files(false, true);
        let Some(row) = rows.iter().find(|row| row.get("id").and_then(Value::as_str) == Some(&source.id)) else {
            return Err(StoreRefused::refused(format!("no such library: {}", source.id), "no-source", 404));
        };
        let refs = ModelGc::of(self.app).references().refs;
        let groups: BTreeSet<String> = refs.iter().map(|rel| ModelGc::part_group(rel)).collect();
        let files = row.get("files").and_then(Value::as_array).into_iter().flatten().map(|file| {
            let rel = Coerce::text(file.get("path"));
            let group = ModelGc::part_group(&rel);
            let referenced = refs.contains(&rel) || groups.contains(&group);
            // absent-ok: `int(f.get("size") or 0)`: what the look did not size weighs nothing in the plan.
            let mut out = json!({"path": rel, "sizeBytes": Coerce::whole(file.get("size")), "group": group});
            if let (Some(kind), Value::Object(fields)) = (file.get("kind").filter(|kind| Coerce::truthy(Some(*kind))), &mut out) {
                fields.insert("kind".to_string(), kind.clone());
            }
            if let Value::Object(fields) = &mut out {
                fields.insert("referenced".to_string(), json!(referenced));
            }
            out
        });
        let files = files.collect();
        let root = if Coerce::truthy(row.get("path")) { Coerce::text(row.get("path")) } else { source.path.clone() };
        Ok((files, root))
    }

    fn stamp(path: &Path) -> Result<Vec<i64>, MoveRefused> {
        let meta = std::fs::metadata(path).map_err(|error| StoreRefused::refused(error.to_string(), "no-source", 409))?;
        Ok(vec![meta.size() as i64, meta.mtime() * 1_000_000_000 + meta.mtime_nsec()])
    }

    /// The items of `keys`.
    fn items(
        source: &End,
        root: &str,
        files: &[Value],
        keys: &[String],
        busy: &BTreeSet<String>,
    ) -> Result<(Vec<MoveItem>, i64), MoveRefused> {
        let (mut items, mut total) = (Vec::new(), 0);
        for key in keys {
            let picked = files.iter().find(|file| file.get("path").and_then(Value::as_str) == Some(key));
            // absent-ok: every row was made with its size.
            let size_of = |file: &Value| Coerce::i64_or_zero(file.get("sizeBytes"));
            if let Some(picked) = picked.filter(|picked| Coerce::truthy(picked.get("kind"))) {
                if busy.contains(key) {
                    return Err(StoreRefused::refused(format!("already moving: {key}"), "busy", 409));
                }
                items.push(MoveItem::new(key, Vec::new(), key, size_of(picked)));
                total += size_of(picked);
                continue;
            }
            let group_of = |file: &Value| {
                if Coerce::truthy(file.get("group")) { Coerce::text(file.get("group")) } else { Coerce::text(file.get("path")) }
            };
            let mut members: Vec<&Value> =
                files.iter().filter(|file| group_of(file) == *key && !Coerce::truthy(file.get("kind"))).collect();
            members.sort_by_key(|file| Coerce::text(file.get("path")));
            let mut planned = Vec::new();
            for member in members {
                let rel = Coerce::text(member.get("path"));
                if busy.contains(&rel) {
                    return Err(StoreRefused::refused(format!("already moving: {rel}"), "busy", 409));
                }
                let full = Path::new(root).join(&rel);
                if source.kind == "local" && full.is_symlink() {
                    return Err(StoreRefused::refused(format!("a link, not a file: {rel}"), "link", 409));
                }
                let stamp = if source.kind == "local" { Self::stamp(&full)? } else { Vec::new() };
                total += size_of(member);
                planned.push(MoveFile::new(&rel, size_of(member), stamp));
            }
            items.push(MoveItem::new(key, planned, "", 0));
        }
        Ok((items, total))
    }

    /// What the asked paths come to, a split model's parts as its group; a path the store does not hold is refused.
    fn keys_of(wanted: &[String], files: &[Value], source: &End) -> Result<Vec<String>, MoveRefused> {
        let mut keys: Vec<String> = Vec::new();
        for rel in wanted {
            let Some(entry) = files.iter().find(|file| file.get("path").and_then(Value::as_str) == Some(rel)) else {
                let place = if source.kind == "local" {
                    "the models disk"
                } else if source.name.is_empty() {
                    source.id.as_str()
                } else {
                    source.name.as_str()
                };
                return Err(StoreRefused::refused(format!("not in {place}: {rel}"), "unknown-file", 404));
            };
            let key = if Coerce::truthy(entry.get("group")) { Coerce::text(entry.get("group")) } else { rel.clone() };
            if !keys.contains(&key) {
                keys.push(key);
            }
        }
        Ok(keys)
    }

    fn check_room(target: &End, total: i64) -> Result<(), MoveRefused> {
        let store_word = if target.name.is_empty() { "the store" } else { target.name.as_str() };
        if !target.usable() {
            return Err(StoreRefused::refused(target.state_words(store_word), &format!("target-{}", target.state), 409));
        }
        if target.free.is_none_or(|free| free < (total + Self::SPACE_MARGIN) as f64) {
            return Err(StoreRefused::refused(
                format!(
                    "{store_word} has no room: the move needs {:.1} GB and {:.0} GB to spare",
                    total as f64 / 1_073_741_824.0,
                    Self::SPACE_MARGIN as f64 / 1_073_741_824.0
                ),
                "no-room",
                409,
            ));
        }
        Ok(())
    }

    /// The plan, or a refusal. `busy`: the paths other moves hold.
    pub fn plan(
        &self,
        paths: &[Value],
        target_id: &str,
        busy: &BTreeSet<String>,
        source_id: Option<&str>,
    ) -> Result<MoveJob, MoveRefused> {
        let wanted: Vec<String> = paths
            .iter()
            .map(|path| Coerce::stripped(Some(path)).trim_start_matches('/').to_string())
            .filter(|path| !path.is_empty())
            .collect();
        if wanted.is_empty() {
            return Err(StoreRefused::refused("nothing to move", "empty", 400));
        }
        let rows = StoreRegistry::of(self.app).statuses(true);
        let source = End::of(&rows, source_id.filter(|id| !id.is_empty()).unwrap_or("local"), "source")?;
        let target = End::of(&rows, target_id, "target")?;
        if source.id == target.id {
            return Err(StoreRefused::refused("that is where they already are", "same-store", 400));
        }
        if !source.usable() {
            return Err(StoreRefused::refused(
                source.state_words("the store they sit in"),
                &format!("source-{}", source.state),
                409,
            ));
        }
        let (files, root) = self.source_files(&source)?;
        let keys = Self::keys_of(&wanted, &files, &source)?;
        let (items, total) = Self::items(&source, &root, &files, &keys, busy)?;
        let held: Vec<String> = items
            .iter()
            .flat_map(|item| item.files.iter().map(|file| file.rel.clone()))
            .chain(items.iter().filter(|item| !item.folder.is_empty()).map(|item| item.folder.clone()))
            .collect();
        let reading = ModelGc::of(self.app).holders(&held);
        if !reading.is_empty() {
            return Err(StoreRefused::refused(format!("a running cell reads it: {}", reading.join(", ")), "in-use", 409));
        }
        Self::check_room(&target, total)?;
        let bytes =
            Randomness::bytes(4).ok_or_else(|| StoreRefused::refused("the system gives no random bytes", "no-random", 500))?;
        let id = format!("mv-{}", bytes.iter().map(|byte| format!("{byte:02x}")).collect::<String>());
        Ok(MoveJob {
            id,
            source: json!({"id": source.id, "name": source.name, "root": root, "kind": source.kind}),
            target: json!({"id": target.id, "name": target.name, "root": target.path, "kind": target.kind}),
            items,
            created_at: self.app.now_whole(),
            status: "queued".to_string(),
            reason: String::new(),
            finished_at: 0,
            cancel: false,
            then: json!({}),
        })
    }
}
