//! The model watcher: which files on the disk have diverged from Hugging Face. Three tiers, and each one turns on the one before it: check, download, keep the previous build. The day's pass starts at the first opening of the board.

use super::hf::HubBrowser;
use super::staging::ModelStaging;
use crate::app::App;
use crate::common::freshness::ModelFreshness;
use os::LocalTime;
use plumbing::Log;
use rules::Coerce;
use serde_json::{Map, Value, json};
use std::collections::BTreeMap;
use std::os::unix::fs::MetadataExt;
use std::sync::{Mutex, PoisonError};

#[cfg(test)]
mod tests;

/// A report worked out against the disk a moment ago, and whether a pass is under way.
#[derive(Default)]
pub struct WatchMemory {
    live: Mutex<Option<(f64, Value, Value)>>,
    running: Mutex<bool>,
}

/// The watcher.
pub struct ModelWatch<'app> {
    app: &'app App,
}

impl<'app> ModelWatch<'app> {
    const REPORT_KEYS: &'static str = "path";
    const LIVE_TTL: f64 = 1.0;

    /// The view.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    fn saved(&self) -> Map<String, Value> {
        // absent-ok: a document that has no watcher's section has said nothing yet: every tier is off.
        self.app.admin.read(|doc| doc.get("modelWatch").and_then(Value::as_object).cloned().unwrap_or_default())
    }

    fn put_saved(&self, saved: Map<String, Value>) {
        self.app.admin.saving(|doc| doc.insert("modelWatch".to_string(), Value::Object(saved)));
    }

    /// The watcher's settings and what its last pass said.
    pub fn settings(&self) -> Value {
        let saved = self.saved();
        let or_empty = |key: &str| saved.get(key).filter(|said| Coerce::truthy(Some(*said))).cloned();
        json!({
            "check": Coerce::truthy(saved.get("check")),
            "download": Coerce::truthy(saved.get("download")),
            "lastCheckDay": Coerce::text(saved.get("lastCheckDay")),
            "keepPrev": Coerce::truthy(saved.get("keepPrev")),
            // absent-ok: `int(saved.get(...) or 0)`: 0 says no pass yet.
            "lastCheckAt": Coerce::whole(saved.get("lastCheckAt")),
            "lastError": or_empty("lastError").unwrap_or_else(|| json!("")),
            "lastFetched": or_empty("lastFetched").unwrap_or_else(|| json!([])),
        })
    }

    /// Saves the three tiers.
    pub fn set_settings(&self, body: &Value) -> Value {
        let mut saved = self.saved();
        saved.insert("check".to_string(), json!(Coerce::truthy(body.get("check"))));
        saved.insert("download".to_string(), json!(Coerce::truthy(body.get("download"))));
        saved.insert("keepPrev".to_string(), json!(Coerce::truthy(body.get("keepPrev"))));
        saved.shift_remove("at");
        saved.shift_remove("replace");
        if Coerce::truthy(body.get("download")) {
            saved.insert("check".to_string(), json!(true));
        }
        self.put_saved(saved);
        self.settings()
    }

    /// The report: each row's state worked out against the file that is on the disk RIGHT NOW. Kept for a second: a page reads it many times over.
    pub fn report(&self) -> Value {
        let saved = self.app.admin.read(|doc| doc.get("modelFreshness").cloned());
        let Some(saved) =
            saved.filter(|saved| saved.is_object() && saved.get("keys").and_then(Value::as_str) == Some(Self::REPORT_KEYS))
        else {
            return json!({"checkedAt": 0, "repos": {}});
        };
        let now = self.app.now();
        let mut live = self.app.watch_memory.live.lock().unwrap_or_else(PoisonError::into_inner);
        if let Some((at, source, report)) = live.as_ref()
            && *source == saved
            && now - at < Self::LIVE_TTL
        {
            return report.clone();
        }
        let repos: Map<String, Value> = saved
            .get("repos")
            .and_then(Value::as_object)
            .into_iter()
            .flatten()
            .map(|(repo, row)| (repo.clone(), Self::relived(row)))
            .collect();
        // absent-ok: `int(saved.get(...) or 0)`: 0 says no pass yet.
        let report = json!({"checkedAt": Coerce::whole(saved.get("checkedAt")), "repos": repos});
        *live = Some((now, saved, report.clone()));
        report
    }

    fn relived(row: &Value) -> Value {
        let mut files = Map::new();
        for (key, file) in row.get("files").and_then(Value::as_object).into_iter().flatten() {
            let local = Coerce::truthy(file.get("localPath"))
                .then(|| std::fs::metadata(Coerce::text(file.get("localPath"))).ok())
                .flatten()
                .map(|meta| json!({"size": meta.size(), "mtime": meta.mtime()}));
            let (state, detail) = ModelFreshness::compare_file(
                local.as_ref(),
                Some(&json!({"size": file.get("remoteSize"), "date": file.get("remoteDate")})),
            );
            if state == "missing" {
                continue;
            }
            let mut out = Coerce::fields(file);
            out.extend(Coerce::fields(&detail));
            out.insert("state".to_string(), json!(state));
            files.insert(key.clone(), Value::Object(out));
        }
        let mut out = Coerce::fields(row);
        out.insert("files".to_string(), Value::Object(files));
        Value::Object(out)
    }

    /// `{path from the models folder: state}` of the report.
    pub fn freshness_by_path(&self) -> BTreeMap<String, String> {
        let report = self.report();
        let repos = report.get("repos").and_then(Value::as_object).into_iter().flatten();
        repos
            .flat_map(|(_, repo)| repo.get("files").and_then(Value::as_object).into_iter().flatten())
            .map(|(key, row)| (key.clone(), Coerce::text(row.get("state"))))
            .collect()
    }

    /// Repositories we have something from: `<model>/<author>/…` on the disk is `<author>/<model>` on the hub.
    fn local_repos(&self) -> BTreeMap<String, Map<String, Value>> {
        let root = self.app.models_dir();
        let mut out: BTreeMap<String, Map<String, Value>> = BTreeMap::new();
        for path in super::walk::Walker::ending_in(&root, ".gguf") {
            let Some(rel) = super::walk::Walker::relative(&path, &root) else {
                continue;
            };
            let parts: Vec<&str> = rel.split('/').collect();
            let (Some(model), Some(author), true) = (parts.first(), parts.get(1), parts.len() >= 3) else {
                continue;
            };
            let Ok(meta) = std::fs::metadata(&path) else {
                continue;
            };
            // absent-ok: an empty path has no last word.
            let name = parts.last().copied().unwrap_or_default();
            out.entry(format!("{author}/{model}")).or_default().insert(
                rel.clone(),
                json!({"size": meta.size(), "mtime": meta.mtime(), "path": path.to_string_lossy(), "name": name}),
            );
        }
        out
    }

    /// One pass: every repository we have something from, against the hub.
    pub fn check_pass(&self, force: bool) -> Value {
        let settings = self.settings();
        if settings.get("check") != Some(&json!(true)) && !force {
            return json!({"checked": false, "reason": "auto-check off"});
        }
        let stamp = self.app.now_whole();
        let mut repos = Map::new();
        let mut errors = 0;
        for (repo, local) in self.local_repos() {
            let listing = HubBrowser::of(self.app).list_files(&repo);
            if !Coerce::truthy(listing.get("ok")) {
                errors += 1;
                let words = if Coerce::truthy(listing.get("error")) {
                    Coerce::text(listing.get("error"))
                } else {
                    "unreachable".to_string()
                };
                repos.insert(repo, json!({"error": words, "files": {}, "summary": ModelFreshness::repo_summary([])}));
                continue;
            }
            repos.insert(repo.clone(), Self::repo_row(&repo, &local, &listing));
        }
        self.app.admin.saving(|doc| {
            doc.insert("modelFreshness".to_string(), json!({"checkedAt": stamp, "repos": repos, "keys": Self::REPORT_KEYS}))
        });
        *self.app.watch_memory.live.lock().unwrap_or_else(PoisonError::into_inner) = None;
        let download = settings.get("download") == Some(&json!(true));
        let fetched = if download { self.autofetch(&repos) } else { Vec::new() };
        let mut saved = self.saved();
        saved.insert("lastCheckAt".to_string(), json!(stamp));
        saved.insert(
            "lastError".to_string(),
            json!(if errors > 0 { format!("{errors} repo(s) unreachable") } else { String::new() }),
        );
        if download {
            saved.insert("lastFetched".to_string(), json!(fetched.iter().take(20).collect::<Vec<_>>()));
        }
        self.put_saved(saved);
        let differs: i64 = repos.values().filter_map(|row| row.get("summary")?.get("differs")?.as_i64()).sum();
        json!({"checked": true, "repos": repos.len(), "unreachable": errors, "differs": differs, "fetched": fetched})
    }

    fn repo_row(repo: &str, local: &Map<String, Value>, listing: &Value) -> Value {
        let remote: BTreeMap<String, &Value> = listing
            .get("files")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            .map(|file| (Coerce::text(file.get("name")), file))
            .collect();
        let mut files = Map::new();
        let mut states = Vec::new();
        for (key, meta) in local {
            let name = Coerce::text(meta.get("name"));
            let row = remote.get(&name).copied();
            let (state, detail) = ModelFreshness::compare_file(Some(meta), row);
            if state == "missing" {
                continue;
            }
            let mut out = Map::new();
            out.insert("state".to_string(), json!(state));
            out.extend(Coerce::fields(&detail));
            out.insert("name".to_string(), json!(name));
            out.insert("localPath".to_string(), json!(Coerce::text(meta.get("path"))));
            out.insert("remotePath".to_string(), json!(Coerce::text(row.and_then(|row| row.get("path")))));
            out.insert("repo".to_string(), json!(repo));
            files.insert(key.clone(), Value::Object(out));
            states.push(state);
        }
        json!({"error": "", "files": files, "summary": ModelFreshness::repo_summary(states)})
    }

    /// Replaces everything that has diverged with the new build.
    fn autofetch(&self, repos: &Map<String, Value>) -> Vec<Value> {
        let mut out = Vec::new();
        for row in repos.values() {
            for (key, file) in row.get("files").and_then(Value::as_object).into_iter().flatten() {
                if !matches!(file.get("state").and_then(Value::as_str), Some("size" | "date")) {
                    continue;
                }
                match ModelStaging::of(self.app).start_update(key) {
                    Ok(_) => out.push(json!({"path": key, "result": "fetching"})),
                    Err(error) => out.push(json!({"path": key, "result": error.message})),
                }
            }
        }
        out
    }

    /// The board was opened: the day's first opening starts the day's pass. Never in the way of a page.
    pub fn board_opened(&self) -> Value {
        let now = self.app.now_whole();
        let today = LocalTime::of(now).map_or_else(String::new, |local| local.date());
        let mut running = self.app.watch_memory.running.lock().unwrap_or_else(PoisonError::into_inner);
        let settings = self.settings();
        if settings.get("check") != Some(&json!(true)) {
            return json!({"started": false, "reason": "auto-check off"});
        }
        if settings.get("lastCheckDay").and_then(Value::as_str) == Some(&today) {
            return json!({"started": false, "reason": "already checked today"});
        }
        if *running {
            return json!({"started": false, "reason": "a pass is running"});
        }
        let Some(app) = self.app.shared() else {
            return json!({"started": false, "reason": "the program is ending"});
        };
        let mut saved = self.saved();
        saved.insert("lastCheckDay".to_string(), json!(today));
        self.put_saved(saved);
        *running = true;
        let started = std::thread::Builder::new().name("model-watch".to_string()).spawn(move || {
            let watch = ModelWatch::of(&app);
            let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| watch.check_pass(true)));
            if result.is_err() {
                let mut saved = watch.saved();
                saved.insert("lastError".to_string(), json!("check failed: the pass ended early"));
                watch.put_saved(saved);
                Log::line("[model-watch] a pass failed");
            }
            *app.watch_memory.running.lock().unwrap_or_else(PoisonError::into_inner) = false;
        });
        if started.is_err() {
            *running = false;
            return json!({"started": false, "reason": "no thread for the pass"});
        }
        json!({"started": true, "reason": ""})
    }
}
