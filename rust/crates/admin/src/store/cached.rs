//! Two documents with opposite jobs: what the cloud accounts ARE, and their keys. Both are cached on the file's own (inode, mtime, size): reading them was treated as free, and 502 blocks meant ~500 re-parses of a 99 KB file for ONE request. The key is the file's identity, not a timer: an operator who rotates a key is served the new one on the very next call.

use super::base::Unreadable;
use files::AtomicFile;
use rules::PythonJson;
use serde_json::Value;
use std::os::unix::fs::MetadataExt;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex, PoisonError};

/// A file's generation.
type FileKey = (u64, i128, u64);

/// A JSON document re-read only when the file itself changes.
pub struct CachedJsonStore {
    path: PathBuf,
    /// One generation only.
    cache: Mutex<Option<(FileKey, Arc<Value>)>>,
}

impl CachedJsonStore {
    /// The store of the file at `path`.
    pub fn new(path: PathBuf) -> Self {
        Self { path, cache: Mutex::new(None) }
    }

    /// Where it lives.
    pub fn path(&self) -> &Path {
        &self.path
    }

    fn key(&self) -> Option<FileKey> {
        let found = std::fs::metadata(&self.path).ok()?;
        Some((found.ino(), i128::from(found.mtime()) * 1_000_000_000 + i128::from(found.mtime_nsec()), found.size()))
    }

    /// The parsed document, or none when there is nothing usable: the caller says what absence means for its own document. A file we cannot parse is not a reason to fail the page that asked. It IS a reason not to cache, and a reason to keep a copy: unreadable, these read as "no accounts, no keys", and the next edit writes that emptiness over the file.
    pub fn read(&self, stamp: &str) -> Option<Arc<Value>> {
        if !self.path.exists() {
            return None;
        }
        let key = self.key();
        if let Some(key) = key {
            let cache = self.cache.lock().unwrap_or_else(PoisonError::into_inner);
            if let Some((_, value)) = cache.as_ref().filter(|(held, _)| *held == key) {
                return Some(Arc::clone(value));
            }
        }
        let parsed = std::fs::read(&self.path).ok().and_then(|raw| serde_json::from_slice::<Value>(&raw).ok());
        let Some(parsed) = parsed else {
            Unreadable::keep(&self.path, stamp);
            return None;
        };
        let value = Arc::new(parsed);
        if let Some(key) = key {
            *self.cache.lock().unwrap_or_else(PoisonError::into_inner) = Some((key, Arc::clone(&value)));
        }
        Some(value)
    }

    /// The file, indented, UTF-8 as itself, with a trailing newline.
    pub fn write(&self, payload: &Value) -> std::io::Result<()> {
        AtomicFile::write(&self.path, Self::text(payload).as_bytes())
    }

    /// The same at mode 0600, its folder made first: what the keys are written with.
    pub fn write_private(&self, payload: &Value) -> std::io::Result<()> {
        if let Some(parent) = self.path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        AtomicFile::write_private(&self.path, Self::text(payload).as_bytes())
    }

    fn text(payload: &Value) -> String {
        let mut text = PythonJson::indented_letters(payload);
        text.push('\n');
        text
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn a_new_generation_is_read_at_once_and_a_broken_file_is_kept() {
        let folder = std::env::temp_dir().join(format!("cached-{}", std::process::id()));
        std::fs::create_dir_all(&folder).unwrap();
        let path = folder.join("doc.json");
        let store = CachedJsonStore::new(path.clone());
        assert!(store.read("s").is_none());
        store.write(&json!({"a": 1})).unwrap();
        assert_eq!(*store.read("s").unwrap(), json!({"a": 1}));
        store.write(&json!({"a": 2})).unwrap();
        assert_eq!(*store.read("s").unwrap(), json!({"a": 2}));
        std::fs::write(&path, "{").unwrap();
        assert!(store.read("s").is_none());
        assert!(folder.join("doc.json.unreadable-s").exists());
        std::fs::remove_dir_all(&folder).unwrap();
    }
}
