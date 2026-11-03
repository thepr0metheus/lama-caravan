//! What the headers of GGUF files said, kept from one start to the next: the first /api/state after every start used to read them all again, 51 s for 56 models. And what a header said of a file that lives in a library: reading it over NFS from this process is what `model_stores` forbids.

use files::AtomicFile;
use plumbing::Log;
use rules::{Coerce, PythonJson};
use serde_json::{Map, Value, json};
use std::path::{Path, PathBuf};
use std::sync::{Mutex, PoisonError};

struct Held {
    files: Map<String, Value>,
    dirty: bool,
    said_no: bool,
}

/// The remembered headers of the models folder, oldest first.
pub struct HeaderMemory {
    path: PathBuf,
    held: Mutex<Option<Held>>,
}

impl HeaderMemory {
    const FORMAT: i64 = 5;
    const CAP: usize = 4000;

    /// The memory kept at `path`.
    pub fn new(path: PathBuf) -> Self {
        Self { path, held: Mutex::new(None) }
    }

    fn loaded(path: &Path) -> Held {
        let doc: Option<Value> = std::fs::read(path).ok().and_then(|raw| serde_json::from_slice(&raw).ok());
        let files = doc
            .filter(|doc| doc.get("format").and_then(Value::as_i64) == Some(Self::FORMAT))
            .and_then(|doc| doc.get("files").and_then(Value::as_object).cloned());
        // absent-ok: a file of another format, or none, remembers nothing yet.
        let mut files = files.unwrap_or_default();
        files.retain(|_, entry| entry.get("meta").and_then(Value::as_object).is_some_and(|meta| !meta.is_empty()));
        Held { files, dirty: false, said_no: false }
    }

    /// What the header of this file said when the file was as it is now; none when it was not, or nothing is remembered.
    pub fn recall(&self, path: &str, mtime: i64, size: i64) -> Option<Map<String, Value>> {
        let mut held = self.held.lock().unwrap_or_else(PoisonError::into_inner);
        let held = held.get_or_insert_with(|| Self::loaded(&self.path));
        let entry = held.files.get(path)?;
        let same =
            entry.get("mtime").and_then(Value::as_i64) == Some(mtime) && entry.get("size").and_then(Value::as_i64) == Some(size);
        same.then(|| entry.get("meta").and_then(Value::as_object).cloned()).flatten()
    }

    /// Keeps what the header of this file said. An empty answer is kept for this run and not written.
    pub fn remember(&self, path: &str, mtime: i64, size: i64, meta: &Map<String, Value>) {
        let mut held = self.held.lock().unwrap_or_else(PoisonError::into_inner);
        let held = held.get_or_insert_with(|| Self::loaded(&self.path));
        let before = held.files.shift_remove(path);
        held.files.insert(path.to_string(), json!({"mtime": mtime, "size": size, "meta": meta}));
        let said_before = before.is_some_and(|entry| entry.get("meta").is_some_and(|meta| Coerce::truthy(Some(meta))));
        if !meta.is_empty() || said_before {
            held.dirty = true;
        }
    }

    /// Writes the file if something was remembered since it was written.
    pub fn flush(&self) -> bool {
        let mut held = self.held.lock().unwrap_or_else(PoisonError::into_inner);
        let held = held.get_or_insert_with(|| Self::loaded(&self.path));
        if !held.dirty {
            return false;
        }
        let kept: Vec<(&String, &Value)> =
            held.files.iter().filter(|(_, entry)| entry.get("meta").is_some_and(|meta| Coerce::truthy(Some(meta)))).collect();
        let from = kept.len().saturating_sub(Self::CAP);
        let files: Map<String, Value> = kept.into_iter().skip(from).map(|(name, entry)| (name.clone(), entry.clone())).collect();
        let doc = json!({"format": Self::FORMAT, "files": files});
        if let Err(error) = AtomicFile::write(&self.path, PythonJson::spaced_letters(&doc).as_bytes()) {
            if !held.said_no {
                held.said_no = true;
                Log::line(&format!("gguf headers: not kept on disk ({error}); the next start reads them again"));
            }
            return false;
        }
        held.dirty = false;
        true
    }
}

/// The remembered headers of files in a library, in one JSON file, read from the local copy before a move deleted it.
pub struct LibraryMeta {
    path: PathBuf,
    doc: Mutex<Option<Map<String, Value>>>,
}

impl LibraryMeta {
    /// The store kept at `path`.
    pub fn new(path: PathBuf) -> Self {
        Self { path, doc: Mutex::new(None) }
    }

    fn loaded(path: &Path) -> Map<String, Value> {
        match std::fs::read(path).ok().and_then(|raw| serde_json::from_slice::<Value>(&raw).ok()) {
            Some(Value::Object(doc)) => doc,
            _ => Map::new(),
        }
    }

    /// The facts for this file; none, too, when the size no longer matches: a file replaced under the same name is another file.
    pub fn lookup(&self, store_id: &str, rel: &str, size: i64) -> Option<Map<String, Value>> {
        let mut doc = self.doc.lock().unwrap_or_else(PoisonError::into_inner);
        let doc = doc.get_or_insert_with(|| Self::loaded(&self.path));
        let hit = doc.get(&format!("{store_id}/{rel}"))?;
        (hit.get("size").and_then(Coerce::int) == Some(size))
            // absent-ok: a cached header with no fields says none.
            .then(|| hit.get("meta").and_then(Value::as_object).cloned().unwrap_or_default())
    }

    fn write(&self, doc: &Map<String, Value>) -> std::io::Result<()> {
        AtomicFile::write(&self.path, PythonJson::spaced_letters(&Value::Object(doc.clone())).as_bytes())
    }

    /// Keeps the facts of a file.
    pub fn remember(&self, store_id: &str, rel: &str, size: i64, meta: &Map<String, Value>) -> std::io::Result<()> {
        let mut doc = self.doc.lock().unwrap_or_else(PoisonError::into_inner);
        let doc = doc.get_or_insert_with(|| Self::loaded(&self.path));
        doc.insert(format!("{store_id}/{rel}"), json!({"size": size, "meta": meta}));
        self.write(doc)
    }

    /// Drops what was remembered for this file; whether there was anything.
    pub fn forget(&self, store_id: &str, rel: &str) -> std::io::Result<bool> {
        let mut doc = self.doc.lock().unwrap_or_else(PoisonError::into_inner);
        let doc = doc.get_or_insert_with(|| Self::loaded(&self.path));
        if doc.shift_remove(&format!("{store_id}/{rel}")).is_none() {
            return Ok(false);
        }
        self.write(doc)?;
        Ok(true)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::tests::TestFolder;

    #[test]
    fn a_header_is_recalled_only_for_the_same_file() {
        let folder = std::env::temp_dir().join(format!("header-memory-{}", std::process::id()));
        let path = folder.join("h.json");
        let memory = HeaderMemory::new(path.clone());
        let meta: Map<String, Value> = json!({"a": 1}).as_object().unwrap().clone();
        assert!(memory.recall("/m", 1, 2).is_none());
        memory.remember("/m", 1, 2, &meta);
        memory.remember("/empty", 1, 2, &Map::new());
        assert_eq!(memory.recall("/m", 1, 2), Some(meta.clone()));
        assert!(memory.recall("/m", 1, 3).is_none());
        assert_eq!(memory.recall("/empty", 1, 2), Some(Map::new()));
        assert!(memory.flush());
        assert!(!memory.flush());
        let again = HeaderMemory::new(path);
        assert_eq!(again.recall("/m", 1, 2), Some(meta));
        assert!(again.recall("/empty", 1, 2).is_none());
        std::fs::remove_dir_all(&folder).unwrap();
    }

    fn facts(text: &str) -> Map<String, Value> {
        serde_json::from_str(text).unwrap()
    }

    fn a_header() -> Map<String, Value> {
        json!({"general.architecture": "qwen", "x.flag": true, "x.ratio": 0.5, "general.languages": ["en", "ru"], "x.nothing": null}).as_object().unwrap().clone()
    }

    fn written(path: &Path) -> Value {
        serde_json::from_slice(&std::fs::read(path).unwrap()).unwrap()
    }

    #[test]
    fn another_second_another_size_or_another_path_is_another_file() {
        let folder = TestFolder::new("memory-same-file");
        let memory = HeaderMemory::new(folder.path.join("h.json"));
        let meta = a_header();
        assert_eq!(memory.recall("/m/a.gguf", 100, 5), None, "a file never seen");
        memory.remember("/m/a.gguf", 100, 5, &meta);
        assert_eq!(memory.recall("/m/a.gguf", 100, 5), Some(meta));
        assert_eq!(memory.recall("/m/a.gguf", 101, 5), None);
        assert_eq!(memory.recall("/m/a.gguf", 100, 6), None);
        assert_eq!(memory.recall("/m/b.gguf", 100, 5), None);
    }

    #[test]
    fn a_file_rewritten_has_the_new_header_and_the_old_one_is_gone() {
        let folder = TestFolder::new("memory-rewritten");
        let memory = HeaderMemory::new(folder.path.join("h.json"));
        memory.remember("/m/a.gguf", 100, 5, &a_header());
        let new = facts(r#"{"general.architecture": "new"}"#);
        memory.remember("/m/a.gguf", 200, 7, &new);
        assert_eq!(memory.recall("/m/a.gguf", 100, 5), None);
        assert_eq!(memory.recall("/m/a.gguf", 200, 7), Some(new));
    }

    #[test]
    fn nothing_remembered_writes_nothing_and_what_was_written_is_not_written_again() {
        let folder = TestFolder::new("memory-writes");
        let path = folder.path.join("fresh.json");
        let memory = HeaderMemory::new(path.clone());
        assert!(!memory.flush());
        assert!(!path.exists(), "no file is made");
        memory.remember("/m/a.gguf", 100, 5, &a_header());
        assert!(memory.flush());
        assert!(path.exists());
        std::fs::remove_file(&path).unwrap();
        assert!(!memory.flush(), "written already");
        assert!(!path.exists());
    }

    #[test]
    fn the_file_holds_a_header_that_said_something_with_its_second_and_its_size() {
        let folder = TestFolder::new("memory-file");
        let path = folder.path.join("fresh.json");
        let memory = HeaderMemory::new(path.clone());
        let meta = a_header();
        memory.remember("/m/a.gguf", 100, 5, &meta);
        memory.remember("/m/e.gguf", 100, 5, &Map::new());
        assert!(memory.flush());
        assert_eq!(written(&path), json!({"format": 5, "files": {"/m/a.gguf": {"mtime": 100, "size": 5, "meta": meta}}}));
    }

    #[test]
    fn a_header_that_said_nothing_is_kept_for_this_run_and_no_file_is_made_of_it() {
        let folder = TestFolder::new("memory-nothing");
        let path = folder.path.join("only-nothing.json");
        let memory = HeaderMemory::new(path.clone());
        memory.remember("/m/e.gguf", 1, 1, &Map::new());
        assert_eq!(memory.recall("/m/e.gguf", 1, 1), Some(Map::new()), "read once per walk, not twice");
        assert!(!memory.flush());
        assert!(!path.exists());
    }

    #[test]
    fn a_start_that_follows_recalls_every_fact_as_its_own_type_and_reads_again_what_said_nothing() {
        let folder = TestFolder::new("memory-restart");
        let path = folder.path.join("fresh.json");
        let memory = HeaderMemory::new(path.clone());
        let meta = a_header();
        memory.remember("/m/a.gguf", 100, 5, &meta);
        memory.remember("/m/e.gguf", 100, 5, &Map::new());
        memory.flush();
        let restarted = HeaderMemory::new(path);
        assert_eq!(restarted.recall("/m/a.gguf", 100, 5), Some(meta));
        assert_eq!(restarted.recall("/m/e.gguf", 100, 5), None);
        assert_eq!(restarted.recall("/m/a.gguf", 100, 6), None, "the file grew since");
    }

    #[test]
    fn a_file_that_has_stopped_saying_anything_leaves_the_disk_at_the_next_write() {
        let folder = TestFolder::new("memory-stopped");
        let path = folder.path.join("fresh.json");
        let memory = HeaderMemory::new(path.clone());
        memory.remember("/m/a.gguf", 100, 5, &a_header());
        memory.flush();
        let restarted = HeaderMemory::new(path.clone());
        restarted.remember("/m/a.gguf", 100, 5, &Map::new());
        assert!(restarted.flush());
        assert_eq!(written(&path)["files"], json!({}));
    }

    #[test]
    fn a_file_the_code_did_not_write_or_wrote_in_another_format_is_read_as_no_file() {
        let folder = TestFolder::new("memory-formats");
        let path = folder.path.join("bad.json");
        let entry = json!({"/m/a.gguf": {"mtime": 100, "size": 5, "meta": a_header()}});
        let in_format = |format: Value| json!({"format": format, "files": entry}).to_string();
        for (why, text) in [
            ("garbage", "{not json".to_string()),
            ("empty", String::new()),
            ("a list", "[1, 2]".to_string()),
            ("before the layers", in_format(json!(1))),
            ("before the experts", in_format(json!(2))),
            ("before the experts' bytes", in_format(json!(3))),
            ("before the key count", in_format(json!(4))),
            ("from the future", in_format(json!(6))),
            ("a word for a format", in_format(json!("5"))),
            ("no format", json!({"files": entry}).to_string()),
            ("files is a list", json!({"format": 5, "files": []}).to_string()),
        ] {
            std::fs::write(&path, text).unwrap();
            assert_eq!(HeaderMemory::new(path.clone()).recall("/m/a.gguf", 100, 5), None, "{why}");
        }
        std::fs::write(&path, in_format(json!(5))).unwrap();
        assert_eq!(HeaderMemory::new(path).recall("/m/a.gguf", 100, 5), Some(a_header()), "and its own format reads");
    }

    #[test]
    fn one_good_entry_among_wrong_ones_is_kept_and_the_wrong_ones_are_not() {
        let folder = TestFolder::new("memory-mixed");
        let path = folder.path.join("bad.json");
        let meta = a_header();
        let doc = json!({"format": 5, "files": {
            "/m/ok.gguf": {"mtime": 1, "size": 2, "meta": meta},
            "/m/str-mtime.gguf": {"mtime": "1", "size": 2, "meta": meta},
            "/m/no-size.gguf": {"mtime": 1, "meta": meta},
            "/m/meta-list.gguf": {"mtime": 1, "size": 2, "meta": [1]},
            "/m/meta-empty.gguf": {"mtime": 1, "size": 2, "meta": {}},
            "/m/not-a-dict.gguf": 7
        }});
        std::fs::write(&path, doc.to_string()).unwrap();
        let mixed = HeaderMemory::new(path);
        assert_eq!(mixed.recall("/m/ok.gguf", 1, 2), Some(meta));
        for name in ["str-mtime", "no-size", "meta-list", "meta-empty", "not-a-dict"] {
            assert_eq!(mixed.recall(&format!("/m/{name}.gguf"), 1, 2), None, "{name}");
        }
    }

    #[test]
    fn past_the_cap_those_remembered_longest_ago_go_and_a_file_seen_again_counts_as_new() {
        let folder = TestFolder::new("memory-cap");
        let path = folder.path.join("capped.json");
        let memory = HeaderMemory::new(path.clone());
        let meta = facts(r#"{"n": 1}"#);
        let name = |index: usize| format!("/m/f{index}.gguf");
        for index in 0..HeaderMemory::CAP + 2 {
            memory.remember(&name(index), 1, 1, &meta);
        }
        memory.remember(&name(0), 1, 1, &meta);
        memory.flush();
        let doc = written(&path);
        let kept: Vec<&String> = doc["files"].as_object().unwrap().keys().collect();
        assert_eq!(kept.len(), HeaderMemory::CAP);
        assert_eq!(kept[0], &name(3), "f1 and f2 went, and f0 came back as the newest");
        assert_eq!(kept[HeaderMemory::CAP - 1], &name(0));
        assert_eq!(memory.recall(&name(1), 1, 1), Some(meta), "the process still knows what the disk dropped");
    }

    #[test]
    fn a_disk_that_cannot_be_written_does_not_stop_the_walk_and_is_said_once() {
        let folder = TestFolder::new("memory-blocked");
        std::fs::write(folder.path.join("blocker"), b"a file where a folder should be").unwrap();
        let memory = HeaderMemory::new(folder.path.join("blocker/inside/x.json"));
        let meta = a_header();
        memory.remember("/m/a.gguf", 1, 1, &meta);
        let said_no = |memory: &HeaderMemory| memory.held.lock().unwrap().as_ref().unwrap().said_no;
        assert!(!said_no(&memory));
        assert!(!memory.flush());
        assert!(said_no(&memory), "said");
        assert!(!memory.flush(), "and it is still not written");
        assert_eq!(memory.recall("/m/a.gguf", 1, 1), Some(meta), "the process remembers it all the same");
    }

    #[test]
    fn many_threads_remembering_and_writing_together_lose_nothing() {
        let folder = TestFolder::new("memory-threads");
        let path = folder.path.join("busy.json");
        let memory = std::sync::Arc::new(HeaderMemory::new(path.clone()));
        let meta = facts(r#"{"w": 1}"#);
        let workers: Vec<_> = (0..8)
            .map(|worker| {
                let (memory, meta) = (std::sync::Arc::clone(&memory), meta.clone());
                std::thread::spawn(move || {
                    for index in 0..50 {
                        let name = format!("/m/w{worker}-{index}.gguf");
                        memory.remember(&name, index, index, &meta);
                        assert_eq!(memory.recall(&name, index, index).as_ref(), Some(&meta));
                        if index % 10 == 0 {
                            memory.flush();
                        }
                    }
                })
            })
            .collect();
        for worker in workers {
            worker.join().unwrap();
        }
        memory.flush();
        assert_eq!(written(&path)["files"].as_object().unwrap().len(), 8 * 50);
        let names: Vec<_> = std::fs::read_dir(&folder.path).unwrap().flatten().map(|entry| entry.file_name()).collect();
        assert_eq!(names, ["busy.json"], "no temporary file is left");
    }

    #[test]
    fn a_library_file_of_another_size_is_another_file() {
        let folder = std::env::temp_dir().join(format!("library-meta-{}", std::process::id()));
        let path = folder.join("m.json");
        let store = LibraryMeta::new(path.clone());
        let meta: Map<String, Value> = json!({"a": 1}).as_object().unwrap().clone();
        store.remember("s", "r", 5, &meta).unwrap();
        assert_eq!(store.lookup("s", "r", 5), Some(meta));
        assert!(store.lookup("s", "r", 6).is_none());
        assert!(store.forget("s", "r").unwrap());
        assert!(!store.forget("s", "r").unwrap());
        assert!(LibraryMeta::new(path).lookup("s", "r", 5).is_none());
        std::fs::remove_dir_all(&folder).unwrap();
    }
}
