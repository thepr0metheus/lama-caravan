//! What of a repository already lies here.

use super::*;

impl<'app> HubBrowser<'app> {
    /// `<model>/<author>` under the models folder: where this page lays a repository out.
    pub(super) fn scan_root(&self, repo_id: &str) -> (PathBuf, String, String) {
        let author =
            if repo_id.contains('/') { repo_id.split('/').next().unwrap_or_default().to_string() } else { String::new() };
        let model = Self::model_name(repo_id).to_string();
        let root = self.app.models_dir().join(&model);
        (if author.is_empty() { root } else { root.join(&author) }, model, author)
    }

    /// Deletes one downloaded GGUF of a repository.
    pub fn local_delete(&self, repo_id: &str, filename: &str) -> Value {
        let repo_id = Coerce::strip(repo_id).trim_matches('/');
        let filename = Coerce::strip(filename);
        if repo_id.is_empty() || filename.is_empty() {
            return json!({"ok": false, "error": "missing repo or filename"});
        }
        if filename.contains('/') || filename.contains('\\') || filename.starts_with('.') {
            return json!({"ok": false, "error": "invalid filename"});
        }
        let (root, _, _) = self.scan_root(repo_id);
        if !root.is_dir() {
            return json!({"ok": false, "error": "repo folder not found"});
        }
        let matches: Vec<PathBuf> = Walker::ending_in(&root, ".gguf")
            .into_iter()
            .filter(|path| path.file_name().is_some_and(|name| name == filename))
            .collect();
        if matches.is_empty() {
            return json!({"ok": false, "error": "file not found"});
        }
        let models_dir = self.app.models_dir();
        let base = std::fs::canonicalize(&models_dir).unwrap_or_else(|_| models_dir.clone());
        for path in matches {
            if !std::fs::canonicalize(&path).unwrap_or_else(|_| path.clone()).starts_with(&base) {
                return json!({"ok": false, "error": "path escape detected"});
            }
            if let Err(error) = std::fs::remove_file(&path) {
                return json!({"ok": false, "error": error.to_string()});
            }
            if let Some(parent) = path.parent() {
                Folders::prune_empty(parent, &models_dir);
            }
        }
        json!({"ok": true})
    }

    /// What we have locally from this repository, and in what shape.
    pub fn local_check(&self, repo_id: &str) -> Value {
        let repo_id = Coerce::strip(repo_id).trim_matches('/');
        if repo_id.is_empty() {
            return json!({"ok": false, "error": "missing repo"});
        }
        let (root, model, author) = self.scan_root(repo_id);
        let mut names = BTreeSet::new();
        let mut files = Map::new();
        let mut folders = Vec::new();
        if root.is_dir() {
            folders = Self::checkpoint_folders(&root);
            for path in Walker::ending_in(&root, ".gguf") {
                let name = path.file_name().map_or_else(String::new, |name| name.to_string_lossy().into_owned());
                names.insert(name.clone());
                let Ok(meta) = std::fs::metadata(&path) else {
                    files.entry(name).or_insert_with(|| json!({}));
                    continue;
                };
                // absent-ok: a row with no time is older than any file.
                let newer = files.get(&name).is_none_or(|row| meta.mtime() > Coerce::i64_or_zero(row.get("mtime")));
                if newer {
                    files.insert(name, json!({"size": meta.size(), "mtime": meta.mtime(), "path": path.to_string_lossy()}));
                }
            }
        }
        let prefix = if author.is_empty() { format!("{model}/") } else { format!("{model}/{author}/") };
        json!({"ok": true, "localNames": names, "localFiles": files, "libraryFiles": Self::library_files(&ModelList::locations(self.app, false), &prefix), "checkpointFolders": folders})
    }

    /// The folders directly under <model>/<author>/ that hold safetensors weights, by name.
    pub(super) fn checkpoint_folders(root: &std::path::Path) -> Vec<String> {
        let labels: BTreeSet<String> = Walker::ending_in(root, ".safetensors")
            .iter()
            .filter_map(|weights| {
                let rel = Walker::relative(weights, root)?;
                let (first, _) = rel.split_once('/')?;
                (!ModelArtifacts::hidden(first)).then(|| first.to_string())
            })
            .collect();
        labels.into_iter().collect()
    }

    /// The GGUF files under one repository's folder in every usable library, by name.
    pub(super) fn library_files(locations: &Locations, prefix: &str) -> Value {
        let mut found: BTreeMap<String, Vec<Value>> = BTreeMap::new();
        for (rel, store, file) in locations.library_copies().into_iter().map(|copy| (&copy.0, &copy.1, &copy.2)) {
            if rel.starts_with(prefix) && rel.to_lowercase().ends_with(".gguf") {
                // absent-ok: `int(f.get(...) or 0)`: what the look did not get is no figure.
                let figure = |key: &str| Coerce::whole(file.get(key));
                found.entry(RelPath::name(rel).to_string()).or_default().push(
                    json!({"store": {"id": store.id, "name": store.name}, "size": figure("size"), "mtime": figure("mtime")}),
                );
            }
        }
        json!(found)
    }
}
