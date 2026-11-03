//! One move, as its manifest keeps it: rewritten after every step, so a restart continues a move instead of forgetting it.

use rules::Coerce;
use serde_json::{Value, json};

/// The states an item ends in.
pub const FINAL_ITEM_STATES: [&str; 3] = ["done", "skipped", "cancelled"];
/// The states a job ends in.
pub const FINAL_JOB_STATES: [&str; 3] = ["done", "failed", "cancelled"];
/// How long a proven copy on a library waits before the source goes, seconds: whatever the share's cache holds has reached its disk by then.
pub const SETTLE_S: f64 = 120.0;

/// One file of an item.
#[derive(Debug, Clone, PartialEq)]
pub struct MoveFile {
    /// Its path from a store's root.
    pub rel: String,
    /// Its size.
    pub size: i64,
    /// Its size and its time when the plan was made: `[size, mtime_ns]`, or none yet for a file in a library.
    pub stamp: Vec<i64>,
    /// "pending" or "proven".
    pub state: String,
    /// "", "copying", "checking", "proven" or "removed".
    pub phase: String,
    /// How far this phase is.
    pub done: i64,
    /// How far the copy is on the disk for certain.
    pub synced: i64,
    /// Copies that came out wrong.
    pub attempts: i64,
    /// When the copy ended.
    pub copied_at: i64,
    /// Its digest once proven.
    pub sha256: String,
    /// Whether the proof read past this host's page cache.
    pub bypassed: bool,
}

impl MoveFile {
    /// A file not begun.
    pub fn new(rel: &str, size: i64, stamp: Vec<i64>) -> Self {
        Self {
            rel: rel.to_string(),
            size,
            stamp,
            state: "pending".to_string(),
            phase: String::new(),
            done: 0,
            synced: 0,
            attempts: 0,
            copied_at: 0,
            sha256: String::new(),
            bypassed: false,
        }
    }

    fn of_json(raw: &Value) -> Option<Self> {
        let number = |key: &str| Coerce::whole(raw.get(key));
        let word = |key: &str, otherwise: &str| raw.get(key).and_then(Value::as_str).unwrap_or(otherwise).to_string();
        Some(Self {
            rel: raw.get("rel")?.as_str()?.to_string(),
            size: raw.get("size")?.as_i64()?,
            stamp: raw.get("stamp").and_then(Value::as_array).into_iter().flatten().filter_map(Value::as_i64).collect(),
            state: word("state", "pending"),
            phase: word("phase", ""),
            done: number("done"),
            synced: number("synced"),
            attempts: number("attempts"),
            copied_at: number("copiedAt"),
            sha256: word("sha256", ""),
            bypassed: raw.get("bypassed") == Some(&json!(true)),
        })
    }

    fn to_json(&self) -> Value {
        json!({"rel": self.rel, "size": self.size, "stamp": self.stamp, "state": self.state, "phase": self.phase, "done": self.done, "synced": self.synced, "attempts": self.attempts, "copiedAt": self.copied_at, "sha256": self.sha256, "bypassed": self.bypassed})
    }

    fn is_past_copy(&self) -> bool {
        matches!(self.phase.as_str(), "proven" | "removed")
    }
}

/// One thing moved: a file with its parts, or a folder.
#[derive(Debug, Clone, PartialEq)]
pub struct MoveItem {
    /// What it is called.
    pub key: String,
    /// "pending", "removing", or one of the final ones.
    pub state: String,
    /// Why it ended as it did.
    pub note: String,
    /// The system's words for that.
    pub detail: String,
    /// Failures so far.
    pub errors: i64,
    /// Its files.
    pub files: Vec<MoveFile>,
    /// The folder, for a folder.
    pub folder: String,
    /// What it weighs.
    pub size: i64,
    /// The links of a folder: path, target.
    pub links: Vec<(String, String)>,
    /// The folders of a folder.
    pub dirs: Vec<String>,
    /// Whether the folder was read.
    pub scanned: bool,
}

impl MoveItem {
    /// An item not begun.
    pub fn new(key: &str, files: Vec<MoveFile>, folder: &str, size: i64) -> Self {
        Self {
            key: key.to_string(),
            state: "pending".to_string(),
            note: String::new(),
            detail: String::new(),
            errors: 0,
            files,
            folder: folder.to_string(),
            size,
            links: Vec::new(),
            dirs: Vec::new(),
            scanned: false,
        }
    }

    fn of_json(raw: &Value) -> Option<Self> {
        let word = |key: &str, otherwise: &str| raw.get(key).and_then(Value::as_str).unwrap_or(otherwise).to_string();
        let files = raw
            .get("files")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            .map(MoveFile::of_json)
            .collect::<Option<Vec<_>>>()?;
        let links = raw
            .get("links")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            .filter_map(|link| Some((link.get(0)?.as_str()?.to_string(), link.get(1)?.as_str()?.to_string())))
            .collect();
        Some(Self {
            key: raw.get("key")?.as_str()?.to_string(),
            state: word("state", "pending"),
            note: word("note", ""),
            detail: word("detail", ""),
            errors: Coerce::whole(raw.get("errors")),
            files,
            folder: word("folder", ""),
            size: Coerce::whole(raw.get("size")),
            links,
            dirs: raw
                .get("dirs")
                .and_then(Value::as_array)
                .into_iter()
                .flatten()
                .filter_map(Value::as_str)
                .map(str::to_string)
                .collect(),
            scanned: raw.get("scanned") == Some(&json!(true)),
        })
    }

    fn to_json(&self) -> Value {
        let links: Vec<Value> = self.links.iter().map(|(path, target)| json!([path, target])).collect();
        json!({"key": self.key, "state": self.state, "note": self.note, "detail": self.detail, "errors": self.errors, "files": self.files.iter().map(MoveFile::to_json).collect::<Vec<_>>(), "folder": self.folder, "size": self.size, "links": links, "dirs": self.dirs, "scanned": self.scanned})
    }

    /// Whether it has ended.
    pub fn is_final(&self) -> bool {
        FINAL_ITEM_STATES.contains(&self.state.as_str())
    }
}

/// One move.
#[derive(Debug, Clone, PartialEq)]
pub struct MoveJob {
    /// Its id.
    pub id: String,
    /// Where from: id, name, root, kind.
    pub source: Value,
    /// Where to.
    pub target: Value,
    /// What is moved.
    pub items: Vec<MoveItem>,
    /// When it was asked for.
    pub created_at: i64,
    /// "queued", "running", "waiting" or one of the final ones.
    pub status: String,
    /// What it waits for.
    pub reason: String,
    /// When it ended.
    pub finished_at: i64,
    /// Whether the operator stopped it.
    pub cancel: bool,
    /// What waits for it: a cell to start.
    pub then: Value,
}

impl MoveJob {
    /// A job from its manifest, an older one's two roots included; none when it does not read.
    pub fn of_json(doc: &Value) -> Option<Self> {
        let items = doc
            .get("items")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            .map(MoveItem::of_json)
            .collect::<Option<Vec<_>>>()?;
        let (source, mut target) = (
            doc.get("source").filter(|source| Coerce::truthy(Some(*source))).cloned(),
            doc.get("target").filter(|target| Coerce::truthy(Some(*target))).cloned().unwrap_or_else(|| json!({})),
        );
        let source = source.unwrap_or_else(|| {
            if let Value::Object(fields) = &mut target {
                fields.insert("root".to_string(), json!(Coerce::text(doc.get("libraryRoot"))));
                fields.insert("kind".to_string(), json!("library"));
            }
            json!({"id": "local", "name": "", "root": Coerce::text(doc.get("localRoot")), "kind": "local"})
        });
        let status = Coerce::text(doc.get("status"));
        Some(Self {
            id: doc.get("id")?.as_str()?.to_string(),
            source,
            target,
            items,
            created_at: Coerce::whole(doc.get("createdAt")),
            status: if status.is_empty() { "queued".to_string() } else { status },
            reason: Coerce::text(doc.get("reason")),
            finished_at: Coerce::whole(doc.get("finishedAt")),
            cancel: Coerce::truthy(doc.get("cancel")),
            then: doc.get("then").filter(|then| Coerce::truthy(Some(*then))).cloned().unwrap_or_else(|| json!({})),
        })
    }

    /// The manifest.
    pub fn to_json(&self) -> Value {
        json!({"id": self.id, "source": self.source, "target": self.target, "items": self.items.iter().map(MoveItem::to_json).collect::<Vec<_>>(), "createdAt": self.created_at, "status": self.status, "reason": self.reason, "finishedAt": self.finished_at, "cancel": self.cancel, "then": self.then})
    }

    /// Where the files are.
    pub fn source_root(&self) -> String {
        Coerce::text(self.source.get("root"))
    }

    /// Where they go.
    pub fn target_root(&self) -> String {
        Coerce::text(self.target.get("root"))
    }

    /// Whether it has ended.
    pub fn finished(&self) -> bool {
        FINAL_JOB_STATES.contains(&self.status.as_str())
    }

    /// Every path this job holds: a folder by its own path, so a second move cannot take it while this one carries it.
    pub fn paths(&self) -> Vec<String> {
        let files = self.items.iter().flat_map(|item| item.files.iter().map(|file| file.rel.clone()));
        files.chain(self.items.iter().filter(|item| !item.folder.is_empty()).map(|item| item.folder.clone())).collect()
    }

    /// How far one file is, out of 2 × its size.
    fn work(item: &MoveItem, file: &MoveFile) -> i64 {
        if item.is_final() || file.is_past_copy() {
            return 2 * file.size;
        }
        match file.phase.as_str() {
            "copying" => file.size.min(file.done),
            "checking" => file.size + file.size.min(file.done),
            _ => 0,
        }
    }

    /// Seconds until the item's copies here may be deleted.
    fn settle_left(item: &MoveItem, now: f64) -> i64 {
        if item.is_final() || item.files.is_empty() || item.files.iter().any(|file| file.phase != "proven") {
            return 0;
        }
        // absent-ok: an item with no files copied has no last moment.
        let last = item.files.iter().map(|file| file.copied_at).max().unwrap_or_default();
        ((last as f64 + SETTLE_S - now).ceil() as i64).max(0)
    }

    fn folder_row(item: &MoveItem, settle: i64) -> Value {
        let files = &item.files;
        let done: i64 = files
            .iter()
            .filter(|file| matches!(file.phase.as_str(), "copying" | "checking" | "proven" | "removed"))
            .map(|file| if file.is_past_copy() { file.size } else { file.done })
            .sum();
        let mut phase = files
            .iter()
            .find(|file| matches!(file.phase.as_str(), "copying" | "checking"))
            .map_or("", |file| file.phase.as_str());
        if phase.is_empty() && !files.is_empty() {
            if files.iter().all(|file| file.phase == "removed") {
                phase = "removed";
            } else if files.iter().all(MoveFile::is_past_copy) {
                phase = "proven";
            }
        }
        let size = if item.size != 0 { item.size } else { files.iter().map(|file| file.size).sum() };
        json!({"path": item.folder, "item": item.state, "phase": phase, "done": done, "size": size, "note": item.note, "detail": item.detail, "removeIn": if phase == "proven" { settle } else { 0 }})
    }

    /// What the page draws.
    pub fn summary(&self, now: f64) -> Value {
        let (mut rows, mut work) = (Vec::new(), 0);
        for item in &self.items {
            let settle = Self::settle_left(item, now);
            work += item.files.iter().map(|file| Self::work(item, file)).sum::<i64>();
            if !item.folder.is_empty() {
                rows.push(Self::folder_row(item, settle));
                continue;
            }
            for file in &item.files {
                rows.push(json!({"path": file.rel, "item": item.state, "phase": file.phase, "done": file.done, "size": file.size, "note": item.note, "detail": item.detail, "removeIn": if file.phase == "proven" { settle } else { 0 }}));
            }
        }
        // absent-ok: every row was made with its size above.
        let size_of = |row: &Value| Coerce::i64_or_zero(row.get("size"));
        let total: i64 = rows.iter().map(size_of).sum();
        let moved: i64 = rows.iter().filter(|row| row.get("item").and_then(Value::as_str) == Some("done")).map(size_of).sum();
        let end = |row: &Value| json!({"id": row.get("id"), "name": Coerce::text(row.get("name"))});
        json!({"id": self.id, "source": end(&self.source), "target": end(&self.target), "status": self.status, "reason": self.reason, "createdAt": self.created_at, "finishedAt": self.finished_at, "totalBytes": total, "movedBytes": moved, "workDone": work, "workTotal": 2 * total, "items": self.items.len(), "itemsDone": self.items.iter().filter(|item| item.state == "done").count(), "files": rows})
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn job() -> MoveJob {
        let mut proven = MoveFile::new("a/b.gguf", 10, vec![10, 5]);
        proven.phase = "proven".to_string();
        proven.copied_at = 100;
        let mut copying = MoveFile::new("c.gguf", 20, vec![]);
        copying.phase = "copying".to_string();
        copying.done = 5;
        MoveJob {
            id: "mv-1".to_string(),
            source: json!({"id": "local", "name": "", "root": "/m", "kind": "local"}),
            target: json!({"id": "lib", "name": "L", "root": "/l", "kind": "library"}),
            items: vec![MoveItem::new("a/b.gguf", vec![proven], "", 0), MoveItem::new("c.gguf", vec![copying], "", 0)],
            created_at: 1,
            status: "running".to_string(),
            reason: String::new(),
            finished_at: 0,
            cancel: false,
            then: json!({}),
        }
    }

    #[test]
    fn a_manifest_reads_back_whole() {
        let job = job();
        assert_eq!(MoveJob::of_json(&job.to_json()).unwrap(), job);
        assert_eq!(MoveJob::of_json(&json!({"items": []})), None);
        let old =
            MoveJob::of_json(&json!({"id": "x", "items": [], "localRoot": "/m", "libraryRoot": "/l", "target": {"id": "lib"}}))
                .unwrap();
        assert_eq!((old.source_root().as_str(), old.target_root().as_str()), ("/m", "/l"));
    }

    fn blank(items: Vec<MoveItem>) -> MoveJob {
        MoveJob { items, ..job() }
    }

    fn one(key: &str, rel: &str, size: i64) -> MoveItem {
        MoveItem::new(key, vec![MoveFile::new(rel, size, vec![size, 1])], "", 0)
    }

    #[test]
    fn work_is_two_passes_a_file_and_what_was_skipped_is_passed_but_not_moved() {
        let mut job = blank(vec![one("a", "a.gguf", 100), one("b", "b.gguf", 300), one("c", "c.gguf", 50)]);
        job.items[0].state = "done".to_string();
        job.items[0].files[0].phase = "removed".to_string();
        job.items[1].files[0].phase = "checking".to_string();
        job.items[1].files[0].done = 150;
        job.items[2].state = "skipped".to_string();
        job.items[2].note = "in-use".to_string();
        let said = job.summary(5000.0);
        let figures: Vec<&Value> =
            ["totalBytes", "movedBytes", "workDone", "workTotal", "items", "itemsDone"].iter().map(|key| &said[key]).collect();
        assert_eq!(figures, [&json!(450), &json!(100), &json!(750), &json!(900), &json!(3), &json!(1)]);
        let rows: Vec<(&Value, &Value, &Value, &Value)> = said["files"]
            .as_array()
            .unwrap()
            .iter()
            .map(|row| (&row["path"], &row["item"], &row["phase"], &row["note"]))
            .collect();
        assert_eq!(rows[0], (&json!("a.gguf"), &json!("done"), &json!("removed"), &json!("")));
        assert_eq!(rows[1], (&json!("b.gguf"), &json!("pending"), &json!("checking"), &json!("")));
        assert_eq!(rows[2], (&json!("c.gguf"), &json!("skipped"), &json!(""), &json!("in-use")));
        assert!(
            said["files"].as_array().unwrap().iter().all(|row| row["removeIn"] == json!(0)),
            "moved, checking or skipped: nothing to count down"
        );
    }

    #[test]
    fn a_folder_in_line_is_one_row_with_its_weight_and_nothing_done() {
        let said = blank(vec![MoveItem::new("whisper/models--x", Vec::new(), "whisper/models--x", 700)]).summary(5000.0);
        let row = &said["files"][0];
        assert_eq!(said["files"].as_array().unwrap().len(), 1);
        assert_eq!((&row["path"], &row["item"], &row["phase"]), (&json!("whisper/models--x"), &json!("pending"), &json!("")));
        assert_eq!((&row["done"], &row["size"], &row["removeIn"]), (&json!(0), &json!(700), &json!(0)));
        assert_eq!((&said["workDone"], &said["workTotal"]), (&json!(0), &json!(1400)));
    }

    #[test]
    fn a_proven_copy_counts_down_to_the_removal_only_when_a_removal_is_coming() {
        let two =
            MoveItem::new("e", vec![MoveFile::new("e1.gguf", 10, vec![10, 1]), MoveFile::new("e2.gguf", 10, vec![10, 1])], "", 0);
        let mut job = blank(vec![one("d", "d.gguf", 10), two, one("f", "f.gguf", 10)]);
        for (item, file) in [(0, 0), (1, 0), (2, 0)] {
            let row = &mut job.items[item].files[file];
            row.state = "proven".to_string();
            row.phase = "proven".to_string();
            row.done = 10;
            row.copied_at = 1000;
        }
        job.items[1].files[1].phase = "checking".to_string();
        job.items[1].files[1].copied_at = 1010;
        job.items[2].state = "skipped".to_string();
        job.items[2].note = "local-changed".to_string();
        let left = |now: f64| -> Vec<Value> {
            job.summary(now)["files"].as_array().unwrap().iter().map(|row| row["removeIn"].clone()).collect()
        };
        assert_eq!(
            left(1030.5),
            [json!(90), json!(0), json!(0), json!(0)],
            "up to a whole second; a part while another is checking; proven and kept here"
        );
        assert_eq!(left(1200.0)[0], json!(0), "the time is over");
    }

    #[test]
    fn a_job_holds_its_files_and_its_folders_by_their_paths() {
        let job = blank(vec![one("a", "a.gguf", 1), MoveItem::new("f", Vec::new(), "whisper/f", 1)]);
        assert_eq!(job.paths(), ["a.gguf", "whisper/f"]);
    }

    #[test]
    fn a_manifest_without_the_newer_fields_reads_with_zeros_and_one_without_its_own_does_not_read() {
        let mut old = job().to_json();
        old["items"][1]["files"][0].as_object_mut().unwrap().remove("synced");
        old["items"][1].as_object_mut().unwrap().remove("errors");
        let back = MoveJob::of_json(&old).unwrap();
        assert_eq!((back.items[1].files[0].synced, back.items[1].errors), (0, 0));
        let mut broken = job().to_json();
        broken["items"][0]["files"][0].as_object_mut().unwrap().remove("rel");
        assert_eq!(MoveJob::of_json(&broken), None, "a file with no path is not guessed at");
    }

    #[test]
    fn a_job_that_ended_is_finished_and_one_on_its_way_is_not() {
        for (status, finished) in
            [("done", true), ("failed", true), ("cancelled", true), ("queued", false), ("running", false), ("waiting", false)]
        {
            assert_eq!(MoveJob { status: status.to_string(), ..job() }.finished(), finished, "{status}");
        }
    }

    #[test]
    fn a_page_is_told_how_far_it_is() {
        let said = job().summary(150.0);
        assert_eq!(said.get("totalBytes"), Some(&json!(30)));
        assert_eq!(said.get("workDone"), Some(&json!(25)));
        assert_eq!(said.get("workTotal"), Some(&json!(60)));
        assert_eq!(said.get("files").unwrap().get(0).unwrap().get("removeIn"), Some(&json!(70)));
        assert_eq!(said.get("source"), Some(&json!({"id": "local", "name": ""})));
    }
}
