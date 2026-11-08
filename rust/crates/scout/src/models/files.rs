//! What is this scout's in its cache, and what files a model is.

use regex::{Regex, RegexBuilder};
use serde_json::json;
use std::collections::BTreeSet;
use std::fs;
use std::path::{Component, Path, PathBuf};
use std::sync::{Arc, Mutex, PoisonError};

/// `Path.resolve()`: the real path of what exists, the rest as it is said.
pub struct Resolved;

impl Resolved {
    /// `path` with its links followed as far as it exists.
    pub fn of(path: &Path) -> PathBuf {
        let absolute = if path.is_absolute() {
            path.to_path_buf()
        } else {
            std::env::current_dir().map_or_else(|_| path.to_path_buf(), |here| here.join(path))
        };
        let mut existing = absolute.as_path();
        let mut rest: Vec<&std::ffi::OsStr> = Vec::new();
        loop {
            if let Ok(real) = fs::canonicalize(existing) {
                let mut out = real;
                for part in rest.iter().rev() {
                    out.push(part);
                }
                return Self::without_dots(&out);
            }
            match (existing.file_name(), existing.parent()) {
                (Some(name), Some(parent)) => {
                    rest.push(name);
                    existing = parent;
                }
                _ => return Self::without_dots(&absolute),
            }
        }
    }

    fn without_dots(path: &Path) -> PathBuf {
        let mut out = PathBuf::new();
        for part in path.components() {
            match part {
                Component::ParentDir => {
                    out.pop();
                }
                Component::CurDir => {}
                other => out.push(other),
            }
        }
        out
    }
}

/// A document as `json.dumps(value, indent=1)` writes it: what stands beside the models says what it said in Python, to the byte: a model's weight counts it.
pub struct OneSpaceJson;

impl OneSpaceJson {
    /// The text.
    pub fn text(value: &serde_json::Value) -> Result<String, serde_json::Error> {
        use serde_core::Serialize;
        let mut out = Vec::new();
        let mut writer = serde_json::Serializer::with_formatter(&mut out, serde_json::ser::PrettyFormatter::with_indent(b" "));
        value.serialize(&mut writer)?;
        Ok(String::from_utf8_lossy(&out).into_owned())
    }
}

/// A folder's contents, its links not followed.
pub struct Walk;

impl Walk {
    /// Every entry under `folder`.
    pub fn entries(folder: &Path) -> Vec<PathBuf> {
        let mut found = Vec::new();
        let mut todo = vec![folder.to_path_buf()];
        while let Some(current) = todo.pop() {
            let Ok(entries) = fs::read_dir(&current) else {
                continue;
            };
            for entry in entries.flatten() {
                let path = entry.path();
                if entry.file_type().is_ok_and(|kind| kind.is_dir()) {
                    todo.push(path.clone());
                }
                found.push(path);
            }
        }
        found.sort();
        found
    }
}

impl Walk {
    /// What `os.walk` calls the files under `folder`, each with its own size: a link to a folder is no file, and a link is measured as a link.
    pub fn files_with_sizes(folder: &Path) -> Vec<(PathBuf, u64)> {
        Self::entries(folder)
            .into_iter()
            .filter(|path| !path.is_dir())
            .filter_map(|path| path.symlink_metadata().ok().map(|meta| (path, meta.len())))
            .collect()
    }
}

/// The files this scout downloaded into its model cache: the only files it ever deletes there. The cache's folder is a setting, and a setting can name a folder the scout shares: deleting by
/// pattern there deletes the library. So a download is written down as it starts and when it lands, and what is not written down stays.
pub struct DownloadedFiles {
    cache_dir: Arc<dyn Fn() -> PathBuf + Send + Sync>,
    lock: Mutex<()>,
}

impl DownloadedFiles {
    const NAME: &'static str = ".caravan-downloads.json";

    /// The record of the folder `cache_dir` says, each time it is asked: the setting can change.
    pub fn new(cache_dir: Arc<dyn Fn() -> PathBuf + Send + Sync>) -> Self {
        Self { cache_dir, lock: Mutex::new(()) }
    }

    /// The record's own file, in the cache's folder.
    pub fn file(&self) -> PathBuf {
        (self.cache_dir)().join(Self::NAME)
    }

    fn read(&self) -> BTreeSet<String> {
        let said = fs::read(self.file()).ok().and_then(|raw| serde_json::from_slice::<serde_json::Value>(&raw).ok());
        said.and_then(|said| said.as_array().cloned())
            .into_iter()
            .flatten()
            .map(|name| rules::Coerce::text(Some(&name)))
            .collect()
    }

    /// Nothing downloaded: no bookkeeping file either. A record that cannot be written leaves the last one: what it does not name stays, which is the safe way to be wrong.
    fn write(&self, names: &BTreeSet<String>) {
        let target = self.file();
        if names.is_empty() {
            drop(fs::remove_file(&target));
            return;
        }
        if let Some(folder) = target.parent() {
            drop(fs::create_dir_all(folder));
        }
        let text = OneSpaceJson::text(&json!(names)).unwrap_or_else(|_| "[]".to_string());
        let temporary = target.with_file_name(format!("{}.new", Self::NAME));
        if fs::write(&temporary, text).is_ok() {
            drop(fs::rename(&temporary, &target));
        }
    }

    /// The path inside the cache; `None` outside it: nothing there is this scout's.
    fn key(&self, path: &Path) -> Option<String> {
        let inside = Resolved::of(path);
        let base = Resolved::of(&(self.cache_dir)());
        Some(inside.strip_prefix(base).ok()?.to_string_lossy().into_owned())
    }

    fn locked(&self) -> std::sync::MutexGuard<'_, ()> {
        self.lock.lock().unwrap_or_else(PoisonError::into_inner)
    }

    /// Writes `path` down.
    pub fn add(&self, path: &Path) {
        if let Some(key) = self.key(path) {
            let _held = self.locked();
            let mut names = self.read();
            if names.insert(key) {
                self.write(&names);
            }
        }
    }

    /// Takes `path` off the record.
    pub fn forget(&self, path: &Path) {
        if let Some(key) = self.key(path) {
            let _held = self.locked();
            let mut names = self.read();
            if names.remove(&key) {
                self.write(&names);
            }
        }
    }

    /// Whether `path` is written down.
    pub fn has(&self, path: &Path) -> bool {
        self.key(path).is_some_and(|key| self.read().contains(&key))
    }

    /// Whether the file at `rel` is this scout's: written down itself, or under a folder that is. The one rule of ownership.
    pub fn covers(names: &BTreeSet<String>, rel: &str) -> bool {
        names.contains(rel) || names.iter().any(|entry| rel.starts_with(&format!("{entry}/")))
    }

    /// The files under `folder` this scout did not download: every file, hidden ones too, for a folder of them is written into.
    pub fn foreign_in(&self, folder: &Path) -> Vec<PathBuf> {
        let base = (self.cache_dir)();
        let names = self.read();
        Walk::entries(folder)
            .into_iter()
            .filter(|path| !path.symlink_metadata().is_ok_and(|meta| meta.is_dir()) && !path.is_dir())
            .filter(|path| match path.strip_prefix(&base) {
                Ok(rel) => !Self::covers(&names, &rel.to_string_lossy()),
                Err(_) => true,
            })
            .collect()
    }

    /// Forgets what is written down inside `folder`: the files a folder, now written down as a whole, holds.
    pub fn forget_under(&self, folder: &Path) {
        if let Some(key) = self.key(folder) {
            let _held = self.locked();
            let names = self.read();
            let kept: BTreeSet<String> = names.iter().filter(|name| !name.starts_with(&format!("{key}/"))).cloned().collect();
            if kept != names {
                self.write(&kept);
            }
        }
    }

    /// Everything written down, as paths.
    pub fn paths(&self) -> Vec<PathBuf> {
        let base = (self.cache_dir)();
        self.read().iter().map(|name| base.join(name)).collect()
    }

    /// What is written down, as paths inside the cache folder.
    pub fn names(&self) -> BTreeSet<String> {
        self.read()
    }
}

/// A GGUF in parts: `<stem>-00001-of-00002.gguf` and the rest beside it. An engine loads the first part and opens the others next to it by name, so a cell names only the first.
pub struct SplitGguf {
    part: Regex,
}

impl SplitGguf {
    /// The rule. Its pattern is this program's own text.
    pub fn new() -> Result<Self, regex::Error> {
        Ok(Self { part: RegexBuilder::new(r"^(.+)-(\d{5})(-of-)(\d{5})(\.gguf)$").case_insensitive(true).build()? })
    }

    /// Every part, the first first, when `path` names the first of several; `path` alone otherwise: a later part named by itself is a file like any other.
    pub fn parts(&self, path: &str) -> Vec<String> {
        let (head, name) = path.rsplit_once('/').map_or(("", path), |(head, name)| (head, name));
        let separator = if path.contains('/') { "/" } else { "" };
        let Some(found) = self.part.captures(name) else {
            return vec![path.to_string()];
        };
        let word = |at: usize| found.get(at).map_or("", |word| word.as_str());
        let (index, count) = (word(2).parse::<u32>(), word(4).parse::<u32>());
        match (index, count) {
            (Ok(1), Ok(count)) if count >= 2 => {
                (1..=count).map(|at| format!("{head}{separator}{}-{at:05}{}{}{}", word(1), word(3), word(4), word(5))).collect()
            }
            _ => vec![path.to_string()],
        }
    }

    /// The parts a start brings when it names `path`: every part, unless the controller's hint says how many of the first it brings (`parts`). Two files are not whole sets (2026-11-03): an
    /// IST-DAS DeepSeek set's sixth part is the shared Engram table, published apart under its own name, so the set brings the five named like it; and Unsloth's 5.8 MB first part of a 508 GB set is
    /// read only for its metadata, so it comes alone. The runner that names such a file says so; a number that is not 1 to the split's count is refused, not taken for another.
    pub fn brought(&self, path: &str, hint: Option<&serde_json::Value>) -> Result<Vec<String>, crate::errors::AppError> {
        let parts = self.parts(path);
        let Some(said) = hint.and_then(|hint| hint.get("parts")).filter(|said| !said.is_null()) else {
            return Ok(parts);
        };
        match said.as_u64().and_then(|count| usize::try_from(count).ok()) {
            Some(count) if (1..=parts.len()).contains(&count) => Ok(parts.into_iter().take(count).collect()),
            _ => Err(crate::errors::AppError::new(format!(
                "the start asks for {said} part(s) of {path}, which has {} — a number from 1 to {}",
                parts.len(),
                parts.len()
            ))),
        }
    }

    /// How many bytes a start's model files take on this machine: what the board counts a loading cell's reading against. `None` when no file could be measured: an unknown whole is no denominator.
    pub fn bytes_of(&self, paths: &[String]) -> Option<u64> {
        let mut total = 0;
        for path in paths.iter().filter(|path| !path.is_empty()) {
            let target = Path::new(path);
            if target.is_dir() {
                total += Walk::entries(target)
                    .iter()
                    .filter_map(|file| file.metadata().ok().filter(fs::Metadata::is_file))
                    .map(|meta| meta.len())
                    .sum::<u64>();
            } else {
                total += self.parts(path).iter().filter_map(|part| fs::metadata(part).ok()).map(|meta| meta.len()).sum::<u64>();
            }
        }
        (total > 0).then_some(total)
    }
}
