//! A checkpoint's copy on disk against what the hub says of it.

use super::*;

/// Where the page lays a safetensors repository out under the models folder.
pub struct CheckpointLayout;

impl CheckpointLayout {
    /// `<model>/<author>`.
    pub fn repo_folder(repo_id: &str) -> String {
        let author = if repo_id.contains('/') { repo_id.split('/').next().unwrap_or_default() } else { "unknown" };
        format!("{}/{author}", repo_id.rsplit('/').next().unwrap_or(repo_id))
    }

    /// Where a file lies below the checkpoint's folder: its folders in the repository, without what leaves it.
    pub fn file_path(path: &str, name: &str) -> String {
        let mut parts: Vec<&str> = path.split('/').collect();
        parts.pop();
        parts.retain(|part| !part.is_empty() && !matches!(*part, "." | ".."));
        parts.push(name);
        parts.join("/")
    }
}

/// What one folder has of one file of the plan.
#[derive(Debug, Clone)]
pub struct CheckpointFile {
    pub(super) repo_path: String,
    pub(super) expected_size: i64,
    pub(super) hub_hash: HubHash,
    pub(super) local: Option<Value>,
}

impl CheckpointFile {
    pub(super) const STATES: [&'static str; 6] = ["same", "differs", "wrong-size", "missing", "size-only", "unreadable"];

    pub(super) fn row(&self, state: &str, more: &[(&str, Value)]) -> Value {
        let mut row = Map::new();
        row.insert("state".to_string(), json!(state));
        row.insert("hash".to_string(), json!(self.hub_hash.kind()));
        row.insert("expectedSize".to_string(), json!(self.expected_size));
        if let Some(size) = self.local.as_ref().and_then(|local| local.get("size")) {
            row.insert("size".to_string(), size.clone());
        }
        for (key, value) in more {
            row.insert((*key).to_string(), value.clone());
        }
        Value::Object(row)
    }

    /// The row when no byte needs reading; none when the hash has to be computed.
    pub(super) fn settled(&self) -> Option<Value> {
        let Some(local) = &self.local else {
            return Some(self.row("missing", &[]));
        };
        if let Some(error) = local.get("error") {
            return Some(self.row("unreadable", &[("error", error.clone())]));
        }
        if local.get("size").and_then(Value::as_i64) != Some(self.expected_size) {
            return Some(self.row("wrong-size", &[]));
        }
        self.hub_hash.value().is_none().then(|| self.row("size-only", &[]))
    }

    pub(super) fn judged(&self, actual: &str) -> Value {
        let key = if matches!(self.hub_hash, HubHash::Sha256(_)) { "sha256" } else { "gitSha1" };
        // absent-ok: a hub that names no hash leaves nothing to compare: `expected` is empty and said so.
        let expected = self.hub_hash.value().unwrap_or_default();
        self.row(if actual == expected { "same" } else { "differs" }, &[(key, json!(actual)), ("expected", json!(expected))])
    }

    /// A file the walk cannot read.
    pub(super) fn unreadable(&self, error: &str) -> Value {
        self.row("unreadable", &[("error", json!(error))])
    }
}

/// A folder on the models disk that holds part or all of the checkpoint's plan.
#[derive(Debug, Clone)]
pub struct CheckpointCopy {
    /// The folder, from the models folder.
    pub folder: String,
    pub(super) files: Vec<CheckpointFile>,
}

impl CheckpointCopy {
    /// Finds the copies of a repository's checkpoint: the folders under <model>/<author>/ holding any file of the plan.
    pub fn find(models_dir: &Path, repo_id: &str, checkpoint: Option<&Value>) -> Result<Vec<Self>, AppError> {
        let plan =
            checkpoint.and_then(|checkpoint| checkpoint.get("files")).and_then(Value::as_array).map_or(&[][..], Vec::as_slice);
        if plan.is_empty() {
            return Ok(Vec::new());
        }
        let base = CheckpointLayout::repo_folder(repo_id);
        let entries = match std::fs::read_dir(models_dir.join(&base)) {
            Ok(entries) => entries,
            Err(error) if matches!(error.kind(), std::io::ErrorKind::NotFound | std::io::ErrorKind::NotADirectory) => {
                return Ok(Vec::new());
            }
            Err(error) => return Err(AppError::with_status(format!("cannot read {base}: {error}"), 500)),
        };
        let mut labels: Vec<String> = entries
            .flatten()
            .filter(|entry| entry.path().is_dir())
            .map(|entry| entry.file_name().to_string_lossy().into_owned())
            .filter(|name| !ModelArtifacts::hidden(name))
            .collect();
        labels.sort();
        let mut found = Vec::new();
        for label in labels {
            let folder = models_dir.join(&base).join(&label);
            let files: Vec<CheckpointFile> = plan.iter().map(|entry| Self::file(&folder, entry)).collect();
            if files.iter().any(|file| file.local.is_some()) {
                found.push(Self { folder: format!("{base}/{label}"), files });
            }
        }
        Ok(found)
    }

    pub(super) fn file(folder: &Path, entry: &Value) -> CheckpointFile {
        let path = folder.join(CheckpointLayout::file_path(&Coerce::text(entry.get("path")), &Coerce::text(entry.get("name"))));
        let local = match std::fs::metadata(&path) {
            Ok(meta) if meta.is_file() => {
                Some(json!({"path": path.to_string_lossy(), "size": meta.size(), "mtime": meta.mtime()}))
            }
            Ok(_) => None,
            Err(error) if matches!(error.kind(), std::io::ErrorKind::NotFound | std::io::ErrorKind::NotADirectory) => None,
            Err(error) => Some(json!({"path": path.to_string_lossy(), "error": error.to_string()})),
        };
        // absent-ok: `int(expected_size or 0)`: a plan with no size is held against 0, and comes out "wrong-size": said, not guessed.
        CheckpointFile {
            repo_path: Coerce::text(entry.get("path")),
            expected_size: Coerce::whole(entry.get("size")),
            hub_hash: HubHash::from_entry(entry),
            local,
        }
    }
}
