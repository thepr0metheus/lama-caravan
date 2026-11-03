//! What the tests of a move stand on: a models folder and a library beside it, on real folders; a clock in the test's hand; and every state a job was
//! written down in. There is nothing to break a file operation with on purpose, so a test breaks the real file at the moment a save tells it to.

#![allow(
    clippy::unwrap_used,
    clippy::panic,
    clippy::indexing_slicing,
    reason = "a helper of a test may stop where it found something wrong"
)]

use super::job::{MoveFile, MoveItem, MoveJob};
use super::mover::{Mover, SharedJob};
use crate::app::App;
use crate::tests::{HandClock, TestApp, TestFolder};
use serde_json::{Value, json};
use std::os::unix::fs::MetadataExt;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

/// The id in the mark of the test's library.
pub const LIBRARY: &str = "lib-a";

/// Bytes of a test, each file's its own.
pub fn blob(size: usize, seed: usize) -> Vec<u8> {
    (0..size).map(|at| ((at * 31 + seed * 7) % 251) as u8).collect()
}

/// A move's two ends and what happened on the way.
pub struct Rig {
    /// Where it all stands; gone with the rig.
    pub folder: TestFolder,
    /// The controller over it.
    pub app: Arc<App>,
    /// Its clock: every look takes half a minute until a test says otherwise, so a wait that counts on it ends.
    pub clock: Arc<HandClock>,
    /// The models folder.
    pub local: PathBuf,
    /// The library.
    pub lib: PathBuf,
    /// Every state a job was saved in, in order.
    pub saves: Mutex<Vec<MoveJob>>,
}

impl Rig {
    /// A rig whose library carries its own mark.
    pub fn new(name: &str) -> Self {
        let rig = Self::unmarked(name);
        rig.set_mark(LIBRARY);
        rig
    }

    /// A rig whose library carries no mark: a share that did not mount.
    pub fn unmarked(name: &str) -> Self {
        let folder = TestFolder::new(&format!("moves-{name}"));
        let clock = HandClock::at(1000);
        clock.each_look_takes(30);
        let app = TestApp::with_clock(&folder.path, &[], Arc::<HandClock>::clone(&clock));
        let (local, lib) = (folder.path.join("models"), folder.path.join("lib"));
        std::fs::create_dir_all(&lib).unwrap();
        Self { folder, app, clock, local, lib, saves: Mutex::new(Vec::new()) }
    }

    /// The library carries the mark of `id`.
    pub fn set_mark(&self, id: &str) {
        std::fs::write(self.mark(), json!({"id": id, "name": "NAS"}).to_string()).unwrap();
    }

    /// Where its mark is.
    pub fn mark(&self) -> PathBuf {
        self.lib.join(".caravan-store.json")
    }

    /// A file in `root`, with its folders.
    pub fn put(root: &Path, rel: &str, bytes: &[u8]) -> PathBuf {
        let path = root.join(rel);
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        std::fs::write(&path, bytes).unwrap();
        path
    }

    /// A file on the models disk.
    pub fn put_local(&self, rel: &str, bytes: &[u8]) -> PathBuf {
        Self::put(&self.local, rel, bytes)
    }

    /// A file in the library.
    pub fn put_library(&self, rel: &str, bytes: &[u8]) -> PathBuf {
        Self::put(&self.lib, rel, bytes)
    }

    /// `[size, mtime_ns]`, as a plan takes it and a manifest keeps it.
    pub fn stamp(path: &Path) -> Vec<i64> {
        let meta = std::fs::metadata(path).unwrap();
        vec![meta.size() as i64, meta.mtime() * 1_000_000_000 + meta.mtime_nsec()]
    }

    /// A file of this size that takes no room: a copy or a proof of it has not ended by the time a test is over, so a stop finds it under way for certain.
    pub fn endless(path: &Path) {
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        std::fs::File::create(path).unwrap().set_len(1 << 40).unwrap();
    }

    /// A second on the file's time: not the file that was planned.
    pub fn touch(path: &Path) {
        let moved = std::fs::metadata(path).unwrap().modified().unwrap() + Duration::from_secs(1);
        std::fs::File::options().write(true).open(path).unwrap().set_modified(moved).unwrap();
    }

    fn here(&self) -> Value {
        json!({"id": "local", "name": "", "root": self.local.to_string_lossy(), "kind": "local"})
    }

    fn there(&self) -> Value {
        json!({"id": LIBRARY, "name": "NAS", "root": self.lib.to_string_lossy(), "kind": "library"})
    }

    /// A job not begun, from one end to the other.
    pub fn blank(source: Value, target: Value, items: Vec<MoveItem>) -> MoveJob {
        MoveJob {
            id: "mv-test".to_string(),
            source,
            target,
            items,
            created_at: 1,
            status: "queued".to_string(),
            reason: String::new(),
            finished_at: 0,
            cancel: false,
            then: json!({}),
        }
    }

    /// A job of these groups into the library, as a plan leaves it: each file stamped.
    pub fn job(&self, groups: &[&[&str]]) -> MoveJob {
        let items = groups
            .iter()
            .map(|rels| {
                let files = rels
                    .iter()
                    .map(|rel| {
                        let path = self.local.join(rel);
                        MoveFile::new(rel, std::fs::metadata(&path).unwrap().size() as i64, Self::stamp(&path))
                    })
                    .collect();
                MoveItem::new(rels[0], files, "", 0)
            })
            .collect();
        Self::blank(self.here(), self.there(), items)
    }

    /// A job of these files out of the library, as a plan leaves it: no stamp, for a plan takes no look over the network.
    pub fn job_back(&self, rels: &[&str]) -> MoveJob {
        let files = rels
            .iter()
            .map(|rel| MoveFile::new(rel, std::fs::metadata(self.lib.join(rel)).unwrap().size() as i64, Vec::new()))
            .collect();
        Self::blank(self.there(), self.here(), vec![MoveItem::new(rels[0], files, "", 0)])
    }

    /// A job of one folder into the library, as a plan leaves it: its path and its weight, not read yet.
    pub fn folder_job(&self, folder: &str, size: i64) -> MoveJob {
        Self::blank(self.here(), self.there(), vec![MoveItem::new(folder, Vec::new(), folder, size)])
    }

    /// Runs the job to its end. `hook` sees each save, with the job held. A wait that would never end is stopped after 15 s, and the test's own asserts
    /// say what went wrong: a test that goes red ends.
    pub fn run_watching(&self, job: MoveJob, hook: impl Fn(&MoveJob) + Sync) -> MoveJob {
        let shared: SharedJob = Arc::new(Mutex::new(job));
        self.run_shared(&shared, hook);
        shared.lock().unwrap().clone()
    }

    /// The same with nothing to see.
    pub fn run(&self, job: MoveJob) -> MoveJob {
        self.run_watching(job, |_| {})
    }

    /// Runs the job and stops it the first time `when` says so, while it goes on: as a person presses Stop, between its blocks.
    pub fn run_stopping(&self, job: MoveJob, when: impl Fn(&MoveJob) -> bool + Sync) -> MoveJob {
        let shared: SharedJob = Arc::new(Mutex::new(job));
        let (pressed, button) = (AtomicBool::new(false), Arc::clone(&shared));
        self.run_shared(&shared, |job| {
            if !pressed.load(Ordering::SeqCst) && when(job) {
                pressed.store(true, Ordering::SeqCst);
                // The job is held while a save is made: the press comes as soon as the save ends, and this waits until it is on its way.
                let (button, (told, heard)) = (Arc::clone(&button), std::sync::mpsc::channel());
                std::thread::spawn(move || {
                    told.send(()).unwrap();
                    button.lock().unwrap().cancel = true;
                });
                heard.recv().unwrap();
            }
        });
        shared.lock().unwrap().clone()
    }

    fn run_shared(&self, shared: &SharedJob, hook: impl Fn(&MoveJob) + Sync) {
        const LIMIT: Duration = Duration::from_secs(15);
        const TURN: Duration = Duration::from_millis(5);
        let save = |job: &MoveJob| {
            self.saves.lock().unwrap().push(job.clone());
            hook(job);
        };
        let ended = AtomicBool::new(false);
        std::thread::scope(|scope| {
            scope.spawn(|| {
                let mut spent = Duration::ZERO;
                while !ended.load(Ordering::SeqCst) {
                    if spent >= LIMIT {
                        shared.lock().unwrap().cancel = true;
                        return;
                    }
                    std::thread::sleep(TURN);
                    spent += TURN;
                }
            });
            Mover::new(&self.app, Arc::clone(shared), &save).run();
            ended.store(true, Ordering::SeqCst);
        });
    }

    fn files_under(root: &Path, at: &Path, out: &mut Vec<String>) {
        for entry in std::fs::read_dir(at).into_iter().flatten().flatten() {
            let kind = entry.file_type().unwrap();
            if kind.is_dir() {
                Self::files_under(root, &entry.path(), out);
            } else if kind.is_file() && entry.file_name() != ".caravan-store.json" {
                out.push(entry.path().strip_prefix(root).unwrap().to_string_lossy().into_owned());
            }
        }
    }

    fn listed(root: &Path) -> Vec<String> {
        let mut out = Vec::new();
        Self::files_under(root, root, &mut out);
        out.sort();
        out
    }

    /// The files in the library, a part or a temporary one among them, its mark not.
    pub fn library_files(&self) -> Vec<String> {
        Self::listed(&self.lib)
    }

    /// The files on the models disk.
    pub fn local_files(&self) -> Vec<String> {
        Self::listed(&self.local)
    }

    /// (phase, done) of the first file at every save.
    pub fn phases(&self) -> Vec<(String, i64)> {
        self.saves
            .lock()
            .unwrap()
            .iter()
            .map(|save| (save.items[0].files[0].phase.clone(), save.items[0].files[0].done))
            .collect()
    }

    /// Each phase of the first file once, in the order they came.
    pub fn phase_order(&self) -> Vec<String> {
        let mut order: Vec<String> = Vec::new();
        for (phase, _) in self.phases() {
            if order.last() != Some(&phase) {
                order.push(phase);
            }
        }
        order
    }

    /// How far the copy of the first file stood at each save of its copying.
    pub fn copying(&self) -> Vec<i64> {
        self.phases().into_iter().filter(|(phase, _)| phase == "copying").map(|(_, done)| done).collect()
    }

    /// The status of the job at each save.
    pub fn statuses(&self) -> Vec<String> {
        self.saves.lock().unwrap().iter().map(|save| save.status.clone()).collect()
    }

    /// A cell on a machine with no report names this model: it may be reading it.
    pub fn a_cell_names(&self, rel: &str) {
        self.app.admin.saving(|doc| {
            doc.insert(
                "topology".to_string(),
                json!({"serverSlots": {"box:22001": {"hostId": "box", "port": 22001, "config": {"MODEL_FILE": rel}}}, "hosts": {}}),
            );
        });
    }
}
