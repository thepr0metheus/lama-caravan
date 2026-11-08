//! The model cache of a machine, by value: only what this scout downloaded ever goes, never what a cell holds or what is being written, and a copy takes a
//! model's name only when it is whole.

#![allow(
    clippy::unwrap_used,
    clippy::panic,
    clippy::indexing_slicing,
    reason = "a helper of a test may stop where it found something wrong"
)]

use super::*;
use crate::config::ScoutConfig;
use crate::http_client::HttpClient;
use crate::state::ScoutState;
use crate::tests::{HandClock, HandDisks, StandIn, TestFolder};
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};

const A: &str = "org/a/q4/a-Q4.gguf";
const B: &str = "org/b/q4/b-Q4.gguf";
const C: &str = "org/c/q4/c-Q4.gguf";
const C_MM: &str = "org/c/mmproj-c.gguf";
const S1: &str = "org/s/q4/s-00001-of-00002.gguf";
const S2: &str = "org/s/q4/s-00002-of-00002.gguf";
const FOLDER: &str = "fold/x";
const FOREIGN: &str = "org/f/foreign.gguf";
const RECORD: &str = ".caravan-downloads.json";

/// The cells as the keeper asks them, in the test's hand.
#[derive(Default)]
struct Cells {
    held: Mutex<Vec<String>>,
    live: Mutex<BTreeSet<String>>,
    loading: Mutex<BTreeSet<String>>,
}

impl CellsInUse for Cells {
    fn held_files(&self) -> Vec<String> {
        self.held.lock().unwrap().clone()
    }

    fn live_cells(&self) -> BTreeSet<String> {
        self.live.lock().unwrap().clone()
    }

    fn loading_cells(&self) -> BTreeSet<String> {
        self.loading.lock().unwrap().clone()
    }

    /// The test's cells are called by their names: no port is leased here.
    fn called(&self, cells: &BTreeSet<String>) -> Vec<String> {
        cells.iter().cloned().collect()
    }
}

/// A scout's two shelves in a folder of their own: the cache, and the folder for Strata's files.
struct Rig {
    folder: TestFolder,
    cache: PathBuf,
    config: Arc<ScoutConfig>,
    state: Arc<ScoutState>,
    models: Arc<ModelFetcher>,
    keeper: CacheKeeper,
    work_models: Arc<ModelFetcher>,
    work: CacheKeeper,
    cells: Arc<Cells>,
    clock: Arc<HandClock>,
    disks: Arc<HandDisks>,
}

impl Rig {
    fn new(name: &str) -> Self {
        Self::with_view(name, || false)
    }

    /// The same, with this word on whether the machine can show a model through the controller.
    fn with_view(name: &str, can: fn() -> bool) -> Self {
        let folder = TestFolder::new(&format!("models-{name}"));
        let cache = folder.path.join("cache");
        fs::write(folder.path.join("config.json"), json!({"modelsBasePath": cache.to_string_lossy()}).to_string()).unwrap();
        let config = Arc::new(ScoutConfig::load(&folder.path.join("config.json")).unwrap());
        let state = Arc::new(ScoutState::load(&folder.path.join("state.json"), 0));
        let clock = HandClock::at(1000);
        let splits = Arc::new(SplitGguf::new().unwrap());
        let report: Progress = Arc::new(|_, _| {});
        let disks = Arc::new(HandDisks::default());
        let parts = ShelfParts::new(
            Arc::clone(&config),
            report,
            &state,
            Arc::<HandClock>::clone(&clock),
            Arc::new(HttpClient::new()),
            Arc::clone(&splits),
            Arc::<HandDisks>::clone(&disks),
        )
        .with_view_word(can);
        let (models, work_models) =
            (Arc::new(ModelFetcher::new(&parts, &Shelf::CACHE)), Arc::new(ModelFetcher::new(&parts, &Shelf::WORK)));
        let cells = Arc::new(Cells::default());
        let keeper_of = |models: &Arc<ModelFetcher>| {
            CacheKeeper::new(
                &state,
                Arc::clone(models),
                Arc::<Cells>::clone(&cells),
                Arc::clone(&splits),
                Arc::<HandClock>::clone(&clock),
            )
        };
        let (keeper, work) = (keeper_of(&models), keeper_of(&work_models));
        Self { folder, cache, config, state, models, keeper, work_models, work, cells, clock, disks }
    }

    /// A file in the cache this scout did not download.
    fn put(&self, rel: &str, bytes: &[u8]) -> PathBuf {
        let path = self.cache.join(rel);
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(&path, bytes).unwrap();
        path
    }

    /// A file in the cache this scout downloaded.
    fn ours(&self, rel: &str, bytes: &[u8]) -> PathBuf {
        let path = self.put(rel, bytes);
        self.models.downloaded.add(&path);
        path
    }

    /// A file of `size` bytes that takes no room: a budget is counted in gibibytes.
    fn ours_of(&self, rel: &str, size: u64) -> PathBuf {
        let path = self.cache.join(rel);
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::File::create(&path).unwrap().set_len(size).unwrap();
        self.models.downloaded.add(&path);
        path
    }

    /// A cache holding three models that ran or may have (A oldest, C with its projector), a split model, a folder model and a file this scout did not download.
    fn shelf(name: &str) -> Self {
        let rig = Self::new(name);
        for (rel, size) in [(A, 10), (B, 20), (C, 30), (C_MM, 5), (S1, 7), (S2, 8)] {
            rig.ours(rel, &vec![b'x'; size]);
        }
        rig.put(FOREIGN, &[b'x'; 9]);
        rig.put(&format!("{FOLDER}/FP32/weights.bin"), &[b'x'; 40]);
        rig.put(&format!("{FOLDER}/FP32/config.json"), &[b'x'; 2]);
        rig.models.downloaded.add(&rig.cache.join(FOLDER));
        rig
    }

    /// A start of these files that got as far as a running process.
    fn ran(&self, cell: &str, files: &[&str]) {
        self.begin(cell, files);
        self.keeper.uses.commit(cell);
    }

    fn begin(&self, cell: &str, files: &[&str]) {
        self.keeper.uses.begin(cell, &files.iter().map(|file| (*file).to_string()).collect::<Vec<_>>());
    }

    /// The files in the cache, its hidden ones not.
    fn left(&self) -> Vec<String> {
        let mut out: Vec<String> = Walk::entries(&self.cache)
            .into_iter()
            .filter(|path| path.is_file() && !path.file_name().unwrap().to_string_lossy().starts_with('.'))
            .map(|path| path.strip_prefix(&self.cache).unwrap().to_string_lossy().into_owned())
            .collect();
        out.sort();
        out
    }

    /// What the record names, inside the cache.
    fn written_down(&self) -> Vec<String> {
        self.models.downloaded.names().into_iter().collect()
    }

    fn with_controller(self, controller: &StandIn) -> Self {
        self.config.set("controllerUrl", json!(controller.address()));
        self
    }
}

fn sorted(mut names: Vec<&str>) -> Vec<&str> {
    names.sort_unstable();
    names
}

fn removed(result: &Value) -> (&Value, &Value) {
    (&result["removed"], &result["freedBytes"])
}

/// A controller with these files at `/api/models/download?path=…`.
fn controller_of(files: &[(&'static str, &'static [u8])]) -> StandIn {
    let files: BTreeMap<String, Vec<u8>> = files.iter().map(|(rel, bytes)| ((*rel).to_string(), bytes.to_vec())).collect();
    StandIn::serving(move |head| {
        let target = head.split_whitespace().nth(1).unwrap_or_default();
        let asked = target.split_once("path=").map_or("", |(_, path)| path);
        match files.get(asked) {
            Some(bytes) => StandIn::answer("200 OK", bytes),
            None => StandIn::answer("404 Not Found", b"nothing here"),
        }
    })
}

fn fetch() -> Fetch {
    Fetch { use_cache: true, ..Fetch::default() }
}

#[test]
fn a_purge_takes_what_this_scout_downloaded_and_only_that() {
    let rig = Rig::new("purge");
    let (kept, projector) = (rig.ours(A, &[b'x'; 10]), rig.ours(C_MM, &[b'x'; 5]));
    rig.ours("org/a/partial.tmp", &[b'x'; 3]);
    rig.ours("org/other/stale.gguf", &[b'x'; 7]);
    rig.put("notes.json", &[b'x'; 2]);
    let library = rig.put("lib/library.gguf", &[b'x'; 9]);
    let copying = rig.put("lib/copying.tmp", &[b'x'; 4]);
    let result = rig.models.purge(&[kept.to_string_lossy().into_owned()]);
    assert_eq!(removed(&result), (&json!(3), &json!(15)));
    assert!(kept.exists() && !projector.exists());
    assert!(
        library.exists() && copying.exists(),
        "a cache folder can be a library: deleting by pattern there deletes the library"
    );
    assert!(rig.cache.join("notes.json").exists());
    assert!(!rig.cache.join("org/other").exists() && !rig.cache.join("org/c").exists(), "the folders it emptied go");
    assert_eq!(rig.written_down(), [A], "what went is off the record");
    let result = rig.models.purge(&[]);
    assert_eq!(removed(&result), (&json!(1), &json!(10)));
    assert!(!rig.cache.join(RECORD).exists(), "nothing downloaded: no bookkeeping file either");
    assert!(rig.cache.is_dir() && library.exists());
}

#[test]
fn the_last_file_of_the_cache_goes_and_the_folder_stays_for_the_next_download() {
    let rig = Rig::new("purge-last");
    rig.ours("m.gguf", b"x");
    assert_eq!(removed(&rig.models.purge(&[])), (&json!(1), &json!(1)));
    assert!(rig.cache.is_dir());
    assert_eq!(fs::read_dir(&rig.cache).unwrap().count(), 0);
}

#[test]
fn a_purge_of_a_cache_that_is_not_there_finds_nothing() {
    let rig = Rig::new("purge-none");
    assert_eq!(removed(&rig.models.purge(&[])), (&json!(0), &json!(0)));
}

#[test]
fn a_purge_takes_a_folder_whole_and_leaves_one_that_holds_a_kept_path() {
    let rig = Rig::new("purge-folders");
    let (seam, whisper) = (rig.cache.join("seam/FP32"), rig.cache.join("whisper/x"));
    rig.put("seam/FP32/weights.bin", &[b'x'; 6]);
    rig.put("seam/FP32/.caravan-folder.json", &[b'x'; 2]);
    rig.put("whisper/x/blob", &[b'x'; 3]);
    rig.models.downloaded.add(&seam);
    rig.models.downloaded.add(&whisper);
    let result = rig.models.purge(&[whisper.join("blob").to_string_lossy().into_owned()]);
    assert_eq!(removed(&result), (&json!(1), &json!(8)), "the folder is one entry, its every file in the bytes");
    assert!(!rig.cache.join("seam").exists(), "and its emptied parent goes");
    assert!(whisper.join("blob").exists(), "a kept file inside a folder keeps the folder");
    assert_eq!(rig.written_down(), ["whisper/x"]);
    let result = rig.models.purge(&[whisper.to_string_lossy().into_owned()]);
    assert_eq!(removed(&result), (&json!(0), &json!(0)), "the folder kept by its own name");
    assert!(whisper.join("blob").exists());
}

#[test]
fn a_purge_leaves_what_is_being_written_until_it_is_over() {
    let rig = Rig::new("purge-flight");
    let live = rig.ours("org/a/live.tmp", &[b'x'; 4]);
    let part = rig.cache.join("seam/FP32.part");
    rig.put("seam/FP32.part/a.bin", b"1");
    rig.models.downloaded.add(&part);
    rig.models.flying(&live, true);
    rig.models.flying(&part, true);
    assert!(rig.models.is_flying(&live));
    assert_eq!(removed(&rig.models.purge(&[])), (&json!(0), &json!(0)));
    assert_eq!(removed(&rig.models.clear()), (&json!(0), &json!(0)), "a clearing either");
    assert!(live.exists() && part.join("a.bin").exists());
    assert_eq!(rig.written_down(), ["org/a/live.tmp", "seam/FP32.part"]);
    rig.models.flying(&live, false);
    rig.models.flying(&part, false);
    assert_eq!(removed(&rig.models.purge(&[])), (&json!(2), &json!(5)), "when it ends or fails it goes with the next purge");
    assert!(!live.exists() && !part.exists());
}

#[test]
fn a_purge_takes_models_and_their_temporary_files_and_a_clearing_takes_every_kind() {
    let rig = Rig::new("purge-kinds");
    rig.ours("w/ggml-base.bin", &[b'x'; 11]);
    rig.ours("m.gguf", &[b'x'; 2]);
    rig.ours("m.tmp", &[b'x'; 1]);
    rig.put("foreign.gguf", b"f");
    let result = rig.models.purge(&[]);
    assert_eq!(removed(&result), (&json!(2), &json!(3)));
    assert!(rig.cache.join("w/ggml-base.bin").exists(), "not of those kinds");
    let result = rig.models.clear();
    assert_eq!(removed(&result), (&json!(1), &json!(11)), "the cache is moving: everything of this scout's");
    assert!(rig.cache.join("foreign.gguf").exists(), "and nothing of anyone else's");
}

#[test]
fn a_link_out_of_the_cache_is_written_nowhere_and_what_it_points_at_stays() {
    let rig = Rig::new("purge-link");
    let target = rig.folder.path.join("elsewhere.gguf");
    fs::write(&target, b"library").unwrap();
    fs::create_dir_all(&rig.cache).unwrap();
    let link = rig.cache.join("m.gguf");
    std::os::unix::fs::symlink(&target, &link).unwrap();
    rig.models.downloaded.add(&link);
    assert_eq!(rig.written_down(), Vec::<String>::new(), "it comes to a path outside the cache: nothing there is this scout's");
    assert_eq!(removed(&rig.models.purge(&[])), (&json!(0), &json!(0)));
    assert!(link.is_symlink() && target.exists());
}

#[test]
fn a_dead_link_on_the_record_goes_as_a_link() {
    let rig = Rig::new("purge-dead-link");
    fs::create_dir_all(&rig.cache).unwrap();
    let link = rig.cache.join("m.gguf");
    std::os::unix::fs::symlink("nowhere.gguf", &link).unwrap();
    rig.models.downloaded.add(&link);
    assert_eq!(rig.written_down(), ["m.gguf"]);
    assert_eq!(rig.models.purge(&[])["removed"], json!(1));
    assert!(!link.is_symlink());
}

#[test]
fn a_link_to_a_folder_in_the_cache_is_not_walked_and_what_is_behind_it_stays() {
    let rig = Rig::new("foreign-link-folder");
    let library = rig.folder.path.join("library");
    fs::create_dir_all(&library).unwrap();
    fs::write(library.join("big.gguf"), b"a library's").unwrap();
    fs::create_dir_all(&rig.cache).unwrap();
    std::os::unix::fs::symlink(&library, rig.cache.join("shelf")).unwrap();
    assert_eq!(rig.keeper.foreign_files(), Vec::<(PathBuf, u64)>::new());
    assert_eq!(rig.keeper.delete_foreign(Some(&json!(0))).unwrap(), json!({"removed": 0, "freedBytes": 0}));
    rig.models.clear();
    assert!(rig.cache.join("shelf").is_symlink() && library.join("big.gguf").exists());
}

#[test]
fn a_foreign_link_to_a_file_is_measured_as_a_link_and_goes_as_a_link() {
    let rig = Rig::new("foreign-link-file");
    let target = rig.folder.path.join("elsewhere.gguf");
    fs::write(&target, [b'x'; 7]).unwrap();
    fs::create_dir_all(&rig.cache).unwrap();
    let link = rig.cache.join("m.gguf");
    std::os::unix::fs::symlink(&target, &link).unwrap();
    let figure = fs::symlink_metadata(&link).unwrap().len();
    assert_eq!(rig.keeper.foreign_files(), [(link.clone(), figure)]);
    assert_eq!(rig.keeper.delete_foreign(Some(&json!(figure))).unwrap(), json!({"removed": 1, "freedBytes": figure}));
    assert!(!link.is_symlink());
    assert!(target.exists(), "the file behind it is no file of this cache");
}

#[test]
fn a_record_that_does_not_read_names_nothing_and_nothing_goes() {
    let rig = Rig::new("record-broken");
    let file = rig.ours(A, b"x");
    fs::write(rig.cache.join(RECORD), "not json").unwrap();
    assert_eq!(removed(&rig.models.purge(&[])), (&json!(0), &json!(0)), "what it does not name stays, the safe way to be wrong");
    assert!(file.exists());
}

#[test]
fn an_entry_of_the_record_whose_file_is_gone_is_forgotten() {
    let rig = Rig::new("record-gone");
    let file = rig.ours(A, b"x");
    fs::remove_file(&file).unwrap();
    assert_eq!(removed(&rig.models.purge(&[])), (&json!(0), &json!(0)));
    assert_eq!(rig.written_down(), Vec::<String>::new());
}

#[test]
fn a_release_takes_the_named_files_and_nothing_else() {
    let rig = Rig::new("release");
    let (model, projector, draft) = (rig.ours(A, &[b'x'; 10]), rig.ours(C_MM, &[b'x'; 5]), rig.ours(B, &[b'x'; 4]));
    let stale = rig.ours("org/other/stale.gguf", &[b'x'; 7]);
    let library = rig.put("lib/library.gguf", &[b'x'; 9]);
    let text = |path: &Path| path.to_string_lossy().into_owned();
    assert_eq!(
        removed(&rig.models.release(&[], &[])),
        (&json!(0), &json!(0)),
        "a cell of an engine has nothing to let go of: one such stop erased 92 GB"
    );
    assert!(model.exists() && stale.exists());
    let result = rig.models.release(&[text(&library)], &[]);
    assert_eq!(removed(&result), (&json!(0), &json!(0)), "named, and not this scout's");
    assert!(library.exists());
    let result = rig.models.release(&[text(&model)], &[text(&model)]);
    assert_eq!(removed(&result), (&json!(0), &json!(0)), "named, and a running cell holds it");
    assert!(model.exists());
    let result = rig.models.release(&[text(&model), text(&projector)], &[]);
    assert_eq!(removed(&result), (&json!(2), &json!(15)));
    assert!(!model.exists() && !projector.exists());
    assert!(draft.exists() && stale.exists() && library.exists(), "the other models of the cache are not this stop's");
}

#[test]
fn the_record_holds_what_is_inside_the_cache_and_a_folder_holds_its_files() {
    let rig = Rig::new("record");
    let record = &rig.models.downloaded;
    let inside = rig.ours("a/b.gguf", b"x");
    assert!(record.has(&inside));
    let outside = rig.folder.path.join("outside.gguf");
    fs::write(&outside, b"x").unwrap();
    record.add(&outside);
    assert!(!record.has(&outside));
    assert_eq!(rig.written_down(), ["a/b.gguf"]);
    let names: BTreeSet<String> = ["seam/FP3".to_string(), "x.gguf".to_string()].into();
    for (rel, covered) in [
        ("x.gguf", true),
        ("seam/FP3/a.bin", true),
        ("seam/FP3", true),
        ("seam/FP32/a.bin", false),
        ("seam/FP32", false),
        ("y.gguf", false),
    ] {
        assert_eq!(DownloadedFiles::covers(&names, rel), covered, "{rel}: under a folder means under it");
    }
    record.add(&rig.cache.join("a"));
    record.forget_under(&rig.cache.join("a"));
    assert_eq!(rig.written_down(), ["a"], "the folder now holds its files itself");
    record.forget(&rig.cache.join("a"));
    assert!(!rig.cache.join(RECORD).exists());
}

#[test]
fn the_files_under_a_folder_nobody_wrote_down_are_foreign_hidden_ones_too() {
    let rig = Rig::new("foreign-in");
    let record = &rig.models.downloaded;
    let folder = rig.cache.join("seam/FP32");
    rig.ours("seam/FP32/config.json", b"x");
    assert_eq!(record.foreign_in(&folder), Vec::<PathBuf>::new());
    rig.put("seam/FP32/.note", b"x");
    assert_eq!(record.foreign_in(&folder), [folder.join(".note")]);
    record.add(&folder);
    assert_eq!(record.foreign_in(&folder), Vec::<PathBuf>::new(), "a folder written down holds all that lies in it");
}

#[test]
fn a_file_from_the_controller_lands_whole_under_its_name_and_on_the_record() {
    let controller = controller_of(&[(A, b"GGUF model")]);
    let rig = Rig::new("copy").with_controller(&controller);
    rig.config.set("controllerToken", json!("tok-1"));
    let local = rig.cache.join(A);
    let got = rig.models.ensure(A, &fetch()).unwrap();
    assert_eq!(got, local);
    assert_eq!(fs::read(&local).unwrap(), b"GGUF model");
    assert_eq!(controller.targets(), [format!("/api/models/download?path={A}")]);
    assert!(controller.asked()[0].contains("X-Caravan-Token: tok-1\r\n"));
    assert!(!local.with_extension("tmp").exists());
    assert_eq!(rig.written_down(), [A], "only what is written down ever goes");
}

#[test]
fn a_copy_cut_short_is_tried_again_and_no_half_file_stays_or_takes_the_name() {
    let mut cut = StandIn::answer("200 OK", &[b'x'; 100]);
    cut.truncate(cut.len() - 40);
    let controller = StandIn::serving(move |_| cut.clone());
    let rig = Rig::new("copy-cut").with_controller(&controller);
    let refused = rig.models.ensure(A, &fetch()).err().unwrap();
    assert_eq!(refused.status, 500);
    assert_eq!(
        refused.message,
        "model download failed: incomplete download: received 60 of 100 bytes (60.0%) — connection closed prematurely"
    );
    assert_eq!(controller.targets().len(), 4, "a cut is transient: a controller restarting during a deploy");
    assert_eq!(rig.left(), Vec::<String>::new(), "no model and no temporary file");
    assert_eq!(rig.written_down(), Vec::<String>::new());
}

#[test]
fn a_copy_that_comes_through_after_a_cut_lands_whole() {
    let turn = std::sync::atomic::AtomicUsize::new(0);
    let controller = StandIn::serving(move |_| {
        if turn.fetch_add(1, std::sync::atomic::Ordering::SeqCst) == 0 {
            b"HTTP/1.1 200 OK\r\nContent-Length: 4\r\nConnection: close\r\n\r\nGG".to_vec()
        } else {
            StandIn::answer("200 OK", b"GGUF")
        }
    });
    let rig = Rig::new("copy-retry").with_controller(&controller);
    rig.models.ensure(A, &fetch()).unwrap();
    assert_eq!(fs::read(rig.cache.join(A)).unwrap(), b"GGUF");
    assert_eq!(controller.targets().len(), 2);
    assert_eq!(rig.written_down(), [A]);
}

#[test]
fn a_copy_cut_short_goes_on_from_what_it_has_and_asks_only_for_the_rest() {
    let bytes: Vec<u8> = (0..100u8).collect();
    let served = bytes.clone();
    let turn = std::sync::atomic::AtomicUsize::new(0);
    let controller = StandIn::serving(move |head| {
        if turn.fetch_add(1, std::sync::atomic::Ordering::SeqCst) == 0 {
            let mut cut = b"HTTP/1.1 200 OK\r\nContent-Length: 100\r\nConnection: close\r\n\r\n".to_vec();
            cut.extend_from_slice(&served[..60]);
            return cut;
        }
        let from: usize =
            head.lines().find_map(|line| line.strip_prefix("Range: bytes=")).unwrap().trim_end_matches('-').parse().unwrap();
        let mut rest = format!("HTTP/1.1 206 Partial Content\r\nContent-Length: {}\r\nContent-Range: bytes {from}-99/100\r\nConnection: close\r\n\r\n", 100 - from).into_bytes();
        rest.extend_from_slice(&served[from..]);
        rest
    });
    let rig = Rig::new("copy-goes-on").with_controller(&controller);
    rig.models.ensure(A, &fetch()).unwrap();
    assert_eq!(fs::read(rig.cache.join(A)).unwrap(), bytes, "the two halves are the file");
    let asked = controller.asked();
    assert!(!asked[0].contains("Range:"), "the first try asks for all of it");
    assert!(asked[1].contains("Range: bytes=60-"), "the next for what is missing");
    assert_eq!(rig.written_down(), [A]);
}

#[test]
fn a_file_that_changed_during_its_copy_is_brought_again_from_the_start() {
    let turn = std::sync::atomic::AtomicUsize::new(0);
    let controller = StandIn::serving(move |_| match turn.fetch_add(1, std::sync::atomic::Ordering::SeqCst) {
        0 => b"HTTP/1.1 200 OK\r\nContent-Length: 10\r\nConnection: close\r\n\r\nold".to_vec(),
        // Another length now: these bytes do not go on from the three that came.
        1 => b"HTTP/1.1 206 Partial Content\r\nContent-Length: 4\r\nContent-Range: bytes 3-6/7\r\nConnection: close\r\n\r\nWXYZ"
            .to_vec(),
        _ => StandIn::answer("200 OK", b"NEWFILE"),
    });
    let rig = Rig::new("copy-changed").with_controller(&controller);
    rig.models.ensure(A, &fetch()).unwrap();
    assert_eq!(fs::read(rig.cache.join(A)).unwrap(), b"NEWFILE");
    let asked = controller.asked();
    assert!(asked[1].contains("Range: bytes=3-"));
    assert!(!asked[2].contains("Range:"), "it starts over: {:?}", asked[2]);
}

#[test]
fn a_temporary_file_found_from_before_is_not_gone_on_from() {
    let controller = StandIn::serving(|_| StandIn::answer("200 OK", b"GGUF"));
    let rig = Rig::new("copy-left-before").with_controller(&controller);
    rig.put("org/a/q4/a-Q4.tmp", b"somebody else's half");
    rig.models.ensure(A, &fetch()).unwrap();
    assert_eq!(fs::read(rig.cache.join(A)).unwrap(), b"GGUF");
    assert!(!controller.asked()[0].contains("Range:"), "it may be of another file under the same name");
}

#[test]
fn an_answer_of_no_said_length_is_taken_as_it_came() {
    let controller = StandIn::serving(|_| b"HTTP/1.1 200 OK\r\nConnection: close\r\n\r\nGGUF".to_vec());
    let rig = Rig::new("copy-no-length").with_controller(&controller);
    rig.models.ensure(A, &fetch()).unwrap();
    assert_eq!(fs::read(rig.cache.join(A)).unwrap(), b"GGUF", "a copy of no said length has nothing to be short of");
}

#[test]
fn a_chunked_answer_cut_short_is_no_copy() {
    let controller =
        StandIn::serving(|_| b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n4\r\nGGUF\r\n".to_vec());
    let rig = Rig::new("copy-chunked").with_controller(&controller);
    assert_eq!(rig.models.ensure(A, &fetch()).err().map(|refused| refused.status), Some(500));
    assert_eq!(rig.left(), Vec::<String>::new());
}

#[test]
fn a_copy_under_way_is_on_the_record_and_marked_as_being_written() {
    let holder = Arc::new(Mutex::new(None::<(Arc<ModelFetcher>, PathBuf)>));
    let seen = Arc::new(Mutex::new(None));
    let (rig_of, noted) = (Arc::clone(&holder), Arc::clone(&seen));
    let controller = StandIn::serving(move |_| {
        let (models, temporary) = rig_of.lock().unwrap().clone().unwrap();
        *noted.lock().unwrap() = Some((models.downloaded.has(&temporary), models.is_flying(&temporary)));
        StandIn::answer("200 OK", b"GGUF")
    });
    let rig = Rig::new("copy-flight").with_controller(&controller);
    let temporary = rig.cache.join("org/a/q4/a-Q4.tmp");
    *holder.lock().unwrap() = Some((Arc::clone(&rig.models), temporary.clone()));
    rig.models.ensure(A, &fetch()).unwrap();
    assert_eq!(*seen.lock().unwrap(), Some((true, true)), "a scout that dies here leaves a file it can still purge");
    assert!(!rig.models.is_flying(&temporary));
    assert_eq!(rig.written_down(), [A]);
}

#[test]
fn a_missing_absolute_path_is_fetched_to_that_very_path_as_it_always_was() {
    let rig = Rig::new("absolute-missing");
    let elsewhere = rig.folder.path.join("elsewhere/m.gguf");
    let controller = StandIn::serving(|_| StandIn::answer("200 OK", b"GGUF"));
    let rig = rig.with_controller(&controller);
    assert_eq!(rig.models.ensure(&elsewhere.to_string_lossy(), &Fetch::default()).unwrap(), elsewhere);
    assert_eq!(fs::read(&elsewhere).unwrap(), b"GGUF");
    assert_eq!(rig.written_down(), Vec::<String>::new(), "outside the cache: not this scout's, so never purged");
}

#[test]
fn a_length_the_answer_does_not_keep_is_no_copy_and_the_old_copy_stands() {
    let controller = StandIn::serving(|_| b"HTTP/1.1 200 OK\r\nContent-Length: 100\r\nConnection: close\r\n\r\nshort".to_vec());
    let rig = Rig::new("copy-old").with_controller(&controller);
    let old = rig.ours(A, b"GGUF old copy");
    let refused = rig.models.ensure(A, &Fetch::default()).err().unwrap();
    assert_eq!(refused.status, 500);
    assert_eq!(fs::read(&old).unwrap(), b"GGUF old copy", "a failed copy does not spoil the one that was there");
    assert_eq!(rig.left(), [A]);
}

#[test]
fn a_new_copy_replaces_the_old_only_when_it_is_whole() {
    let cache_old = Arc::new(Mutex::new(Vec::new()));
    let (seen, path) = (Arc::clone(&cache_old), Arc::new(Mutex::new(PathBuf::new())));
    let at = Arc::clone(&path);
    let controller = StandIn::serving(move |_| {
        seen.lock().unwrap().push(fs::read(&*at.lock().unwrap()).unwrap());
        StandIn::answer("200 OK", b"GGUF new copy")
    });
    let rig = Rig::new("copy-swap").with_controller(&controller);
    let old = rig.ours(A, b"GGUF old copy");
    *path.lock().unwrap() = old.clone();
    rig.models.ensure(A, &Fetch::default()).unwrap();
    assert_eq!(cache_old.lock().unwrap().as_slice(), [b"GGUF old copy".to_vec()], "while it comes the old copy is whole");
    assert_eq!(fs::read(&old).unwrap(), b"GGUF new copy");
}

#[test]
fn a_refusal_of_the_controller_is_not_tried_again() {
    let controller = controller_of(&[]);
    let rig = Rig::new("copy-404").with_controller(&controller);
    let refused = rig.models.ensure(A, &fetch()).err().unwrap();
    assert_eq!(refused.status, 500);
    assert_eq!(controller.targets().len(), 1);
    assert_eq!(rig.written_down(), Vec::<String>::new());
    assert_eq!(rig.left(), Vec::<String>::new());
}

#[test]
fn a_copy_here_is_taken_only_when_asked_for_and_no_controller_is_a_refusal_that_names_the_file() {
    let controller = controller_of(&[(A, b"new")]);
    let rig = Rig::new("copy-cache").with_controller(&controller);
    let local = rig.ours(A, b"cached");
    assert_eq!(rig.models.ensure(A, &fetch()).unwrap(), local);
    assert_eq!(controller.targets().len(), 0, "use_cache and a copy here: nothing is asked");
    assert_eq!(fs::read(&local).unwrap(), b"cached");
    rig.models.ensure(A, &Fetch::default()).unwrap();
    assert_eq!(fs::read(&local).unwrap(), b"new", "without it the model is fetched again");
    let bare = Rig::new("copy-no-controller");
    let refused = bare.models.ensure(A, &fetch()).err().unwrap();
    assert_eq!(
        (refused.status, refused.message.as_str()),
        (404, format!("model not found locally and controllerUrl not set: {A}").as_str())
    );
}

#[test]
fn a_fresh_copy_never_takes_the_place_of_a_file_this_scout_did_not_download() {
    let controller = controller_of(&[(A, b"new")]);
    let rig = Rig::new("copy-foreign").with_controller(&controller);
    let local = rig.put(A, b"somebody's");
    let refused = rig.models.ensure(A, &Fetch::default()).err().unwrap();
    assert_eq!(
        (refused.status, refused.message),
        (409, format!("{} is there and was not downloaded by this scout: not replaced", local.display()))
    );
    assert_eq!(controller.targets().len(), 0, "asked before a byte is fetched");
    assert_eq!(rig.written_down(), Vec::<String>::new(), "and it is not on the record");
    assert_eq!(rig.models.ensure(A, &fetch()).unwrap(), local, "a start that keeps a cache reads it as it is");
    rig.models.purge(&[]);
    assert_eq!(fs::read(&local).unwrap(), b"somebody's", "and a clean-up leaves it");
}

#[test]
fn a_fresh_copy_does_not_go_through_a_link_nor_over_one_that_leads_nowhere() {
    let controller = controller_of(&[(A, b"new")]);
    let rig = Rig::new("copy-link").with_controller(&controller);
    let target = rig.folder.path.join("library.gguf");
    fs::write(&target, b"somebody's").unwrap();
    let link = rig.cache.join(A);
    fs::create_dir_all(link.parent().unwrap()).unwrap();
    std::os::unix::fs::symlink(&target, &link).unwrap();
    assert_eq!(rig.models.ensure(A, &Fetch::default()).err().unwrap().status, 409);
    assert!(link.is_symlink() && fs::read(&target).unwrap() == b"somebody's");
    fs::remove_file(&link).unwrap();
    std::os::unix::fs::symlink("nowhere.gguf", &link).unwrap();
    assert_eq!(rig.models.ensure(A, &Fetch::default()).err().unwrap().status, 409);
    assert!(link.is_symlink());
    assert_eq!(controller.targets().len(), 0);
}

/// Two starts of one file, the second while the first is copying it: how many copies the controller was asked for.
fn two_starts(name: &str, asked: &Fetch) -> usize {
    let (first_came, heard) = std::sync::mpsc::channel();
    let controller = StandIn::serving(move |_| {
        // A second copy finds nobody listening for this.
        let _heard_or_gone = first_came.send(0_u8);
        std::thread::sleep(std::time::Duration::from_millis(50));
        StandIn::answer("200 OK", b"GGUF")
    });
    let rig = Rig::new(name).with_controller(&controller);
    std::thread::scope(|scope| {
        let first = scope.spawn(|| rig.models.ensure(A, asked).unwrap());
        heard.recv().unwrap();
        drop(heard);
        assert_eq!(rig.models.ensure(A, asked).unwrap(), rig.cache.join(A));
        first.join().unwrap();
    });
    assert_eq!(fs::read(rig.cache.join(A)).unwrap(), b"GGUF");
    controller.targets().len()
}

#[test]
fn a_second_start_of_a_file_waits_for_its_copy_and_finds_it_whole() {
    assert_eq!(two_starts("copy-one", &fetch()), 1, "one copy, and both starts have the path");
    assert_eq!(
        two_starts("copy-again", &Fetch::default()),
        2,
        "a start that keeps no cache copies it again, after the first: one at a time, not one for all"
    );
}

#[test]
fn a_file_read_in_place_is_not_written_down_and_so_never_deleted() {
    let controller = controller_of(&[(A, b"from the controller")]);
    let rig = Rig::new("in-place").with_controller(&controller);
    let model = rig.folder.path.join("library/m.gguf");
    fs::create_dir_all(model.parent().unwrap()).unwrap();
    fs::write(&model, b"GGUF").unwrap();
    let hinted = |size: i64| Fetch { hint: Some(json!({"path": model.to_string_lossy(), "size": size})), ..Fetch::default() };
    assert_eq!(rig.models.ensure(A, &hinted(4)).unwrap(), model);
    assert_eq!(controller.targets().len(), 0);
    assert_eq!(rig.written_down(), Vec::<String>::new());
    assert_eq!(removed(&rig.models.purge(&[])), (&json!(0), &json!(0)));
    assert!(model.exists());
    // Another file at that path: not read, and not touched.
    assert_eq!(rig.models.ensure(A, &hinted(999)).unwrap(), rig.cache.join(A));
    assert_eq!(fs::read(&model).unwrap(), b"GGUF");
    assert_eq!(rig.written_down(), [A]);
}

#[test]
fn an_absolute_path_that_is_there_is_read_as_it_is_and_never_written_down() {
    let controller = controller_of(&[]);
    let rig = Rig::new("absolute").with_controller(&controller);
    let own = rig.folder.path.join("store/m.gguf");
    fs::create_dir_all(own.parent().unwrap()).unwrap();
    fs::write(&own, b"GGUF").unwrap();
    assert_eq!(rig.models.ensure(&own.to_string_lossy(), &Fetch::default()).unwrap(), own);
    assert_eq!(controller.targets().len(), 0);
    assert_eq!(rig.written_down(), Vec::<String>::new());
}

#[test]
fn a_model_in_a_library_this_machine_lacks_comes_through_the_controller() {
    let controller = controller_of(&[(A, b"from a library")]);
    let rig = Rig::new("library").with_controller(&controller);
    let fetch = Fetch {
        hint: Some(json!({"path": "/nowhere/m.gguf", "library": "NAS", "size": 14})),
        use_cache: true,
        ..Fetch::default()
    };
    let brought = rig.models.ensure(A, &fetch).unwrap();
    assert_eq!(fs::read(brought).unwrap(), b"from a library", "the machine needs no mount of its own");
}

#[test]
fn a_split_model_brings_its_parts_and_one_read_in_place_needs_them_beside_it() {
    let controller = controller_of(&[(S1, b"one"), (S2, b"two")]);
    let rig = Rig::new("split").with_controller(&controller);
    rig.models.ensure(S1, &fetch()).unwrap();
    assert_eq!(fs::read(rig.cache.join(S2)).unwrap(), b"two");
    assert_eq!(rig.written_down(), [S1, S2], "both are this scout's: a purge takes both");
    assert_eq!(
        controller.targets(),
        [format!("/api/models/download?path={S1}"), format!("/api/models/download?path={S2}")],
        "in their order"
    );
    // Read in place: the other part is looked for beside it, and its lack is said.
    let place = rig.folder.path.join("library");
    fs::create_dir_all(&place).unwrap();
    let first = place.join("s-00001-of-00002.gguf");
    fs::write(&first, b"one").unwrap();
    let hinted = Fetch { hint: Some(json!({"path": first.to_string_lossy(), "size": 3})), ..Fetch::default() };
    let refused = rig.models.ensure(S1, &hinted).err().unwrap();
    assert_eq!(refused.status, 409);
    assert!(refused.message.contains("s-00002-of-00002.gguf is not there"), "{}", refused.message);
    fs::write(place.join("s-00002-of-00002.gguf"), b"two").unwrap();
    assert_eq!(rig.models.ensure(S1, &hinted).unwrap(), first);
}

#[test]
fn the_parts_of_a_split_model_are_named_from_its_first() {
    let splits = SplitGguf::new().unwrap();
    assert_eq!(
        splits.parts("org/big-00001-of-00003.gguf"),
        ["org/big-00001-of-00003.gguf", "org/big-00002-of-00003.gguf", "org/big-00003-of-00003.gguf"]
    );
    assert_eq!(splits.parts("big-00001-OF-00002.GGUF"), ["big-00001-OF-00002.GGUF", "big-00002-OF-00002.GGUF"]);
    for alone in ["org/big-00002-of-00003.gguf", "org/big-00001-of-00001.gguf", "org/big.gguf"] {
        assert_eq!(splits.parts(alone), [alone], "a later part named by itself is a file like any other");
    }
}

#[test]
fn a_start_may_bring_fewer_parts_of_a_split_than_its_name_says() {
    let splits = SplitGguf::new().unwrap();
    let six = "ds/iq1m/set-00001-of-00006.gguf";
    let five: Vec<String> = (1..=5).map(|at| format!("ds/iq1m/set-{at:05}-of-00006.gguf")).collect();
    assert_eq!(
        splits.brought(six, Some(&json!({"parts": 5}))).unwrap(),
        five,
        "an IST-DAS set: its sixth part is the Engram, named apart"
    );
    assert_eq!(splits.brought(six, Some(&json!({"parts": 1}))).unwrap(), [six], "a part read for its metadata comes alone");
    assert_eq!(splits.brought(six, None).unwrap().len(), 6, "no word: every part, as the name says");
    assert_eq!(
        splits.brought(six, Some(&json!({"path": "/lib/x", "size": 3}))).unwrap().len(),
        6,
        "a hint silent on parts: every part"
    );
    assert_eq!(splits.brought(six, Some(&json!({"parts": null}))).unwrap().len(), 6, "null is no word");
    for wrong in [json!(0), json!(7), json!(-1), json!("5"), json!(2.5)] {
        let refused = splits.brought(six, Some(&json!({"parts": wrong}))).err().unwrap();
        assert!(refused.message.contains("which has 6"), "{wrong}: {}", refused.message);
    }
    assert_eq!(splits.brought("org/big.gguf", Some(&json!({"parts": 1}))).unwrap(), ["org/big.gguf"], "one file is one part");
    assert!(splits.brought("org/big.gguf", Some(&json!({"parts": 2}))).is_err(), "and no more");
}

#[test]
fn a_split_brings_only_the_parts_its_start_asks_for() {
    // The controller holds parts 1 and 2 of three, as the library holds an IST-DAS set: the last is named apart.
    const T1: &str = "org/t/q/t-00001-of-00003.gguf";
    const T2: &str = "org/t/q/t-00002-of-00003.gguf";
    let controller = controller_of(&[(T1, b"one"), (T2, b"two")]);
    let rig = Rig::new("brought").with_controller(&controller);
    rig.models.ensure(T1, &Fetch { hint: Some(json!({"parts": 2})), ..fetch() }).unwrap();
    assert_eq!(fs::read(rig.cache.join(T2)).unwrap(), b"two");
    let asked = [format!("/api/models/download?path={T1}"), format!("/api/models/download?path={T2}")];
    assert_eq!(controller.targets(), asked, "the third is not asked for");
    // Without the word the third is asked for, and its lack refuses the start.
    let rig = Rig::new("brought-all").with_controller(&controller);
    assert!(rig.models.ensure(T1, &fetch()).is_err(), "every part, as the name says");
    // A number past the split refuses before a byte is fetched.
    let rig = Rig::new("brought-wrong").with_controller(&controller);
    let before = controller.targets().len();
    assert!(rig.models.ensure(T1, &Fetch { hint: Some(json!({"parts": 4})), ..fetch() }).is_err());
    assert_eq!(controller.targets().len(), before, "nothing fetched");
}

#[test]
fn only_a_cell_s_own_scratch_is_cleared() {
    let rig = Rig::new("scratch");
    rig.put(".cells/22001/made.bin", b"x");
    let other = rig.put(".cells/22002/made.bin", b"x");
    assert!(rig.models.clear_scratch("c22001"));
    assert!(!rig.cache.join(".cells/c22001").exists() && other.exists());
    assert!(!rig.models.clear_scratch("c22001"), "there was none");
}

#[test]
fn the_words_of_a_broken_file_are_told_apart_from_other_failures() {
    for text in
        ["tensor 'blk.0' data is not within the file bounds", "model is CORRUPTED OR INCOMPLETE", "gguf: Unexpected End Of File"]
    {
        assert!(ModelFetcher::is_corruption_error(text), "{text}");
    }
    for text in ["out of memory", "file bounds ok", ""] {
        assert!(!ModelFetcher::is_corruption_error(text), "{text}");
    }
}

const WHOLE: &str = "seam/facebook/FP32";

/// The controller of a folder model: its listing, then each file.
fn folder_controller(listing: Value, files: &[(&'static str, &'static [u8])]) -> StandIn {
    let files: BTreeMap<String, Vec<u8>> = files.iter().map(|(rel, bytes)| (format!("{WHOLE}/{rel}"), bytes.to_vec())).collect();
    let listing = listing.to_string().into_bytes();
    StandIn::serving(move |head| {
        let target = head.split_whitespace().nth(1).unwrap_or_default();
        if target.starts_with("/api/models/folder?") {
            return StandIn::answer("200 OK", &listing);
        }
        let asked = target.split_once("path=").map_or("", |(_, path)| path);
        match files.get(asked) {
            Some(bytes) => StandIn::answer("200 OK", bytes),
            None => StandIn::answer("404 Not Found", b"nothing here"),
        }
    })
}

fn listing() -> Value {
    json!({"path": WHOLE, "size": 26,
        "files": [{"path": "config.json", "size": 8}, {"path": "model-00001.safetensors", "size": 9}, {"path": "sub/conf.yaml", "size": 5}, {"path": "blobs/abc", "size": 4}],
        "links": [{"path": "snap/h1/model.bin", "target": "../../blobs/abc"}, {"path": "snap/h2", "target": "h1"}]})
}

const FILES: [(&str, &[u8]); 4] = [
    ("config.json", b"{\"a\": 1}"),
    ("model-00001.safetensors", b"WEIGHTS-1"),
    ("sub/conf.yaml", b"k: v\n"),
    ("blobs/abc", b"BLOB"),
];

fn folder_fetch() -> Fetch {
    Fetch { use_cache: true, hint: Some(json!({"path": format!("/data/models/{WHOLE}"), "dir": true})), ..Fetch::default() }
}

fn fetched_files(controller: &StandIn) -> Vec<String> {
    controller
        .targets()
        .iter()
        .filter_map(|target| target.strip_prefix(&format!("/api/models/download?path={WHOLE}/")).map(str::to_string))
        .collect()
}

#[test]
fn a_folder_is_built_under_another_name_and_takes_its_own_when_it_is_whole() {
    let controller = folder_controller(listing(), &FILES);
    let rig = Rig::new("folder").with_controller(&controller);
    let local = rig.cache.join(WHOLE);
    assert_eq!(rig.models.ensure(WHOLE, &folder_fetch()).unwrap(), local);
    assert_eq!(controller.targets()[0], format!("/api/models/folder?path={WHOLE}"));
    assert_eq!(fetched_files(&controller), ["config.json", "model-00001.safetensors", "sub/conf.yaml", "blobs/abc"]);
    for (rel, bytes) in FILES {
        assert_eq!(fs::read(local.join(rel)).unwrap(), bytes, "{rel}");
    }
    assert_eq!(fs::read_link(local.join("snap/h1/model.bin")).unwrap().to_string_lossy(), "../../blobs/abc");
    assert_eq!(fs::read_link(local.join("snap/h2")).unwrap().to_string_lossy(), "h1");
    let mark: Value = serde_json::from_slice(&fs::read(local.join(".caravan-folder.json")).unwrap()).unwrap();
    assert_eq!(mark, listing(), "the mark of a whole folder lies last, and it is the listing");
    assert!(!rig.cache.join("seam/facebook/FP32.part").exists());
    assert_eq!(rig.written_down(), [WHOLE], "one folder on the record, not each file in it");
    let fetched = fetched_files(&controller).len();
    assert_eq!(rig.models.ensure(WHOLE, &folder_fetch()).unwrap(), local);
    assert_eq!(
        fetched_files(&controller).len(),
        fetched,
        "a second start takes the whole folder as it is: it asks for the listing, and for no file"
    );
    assert_eq!(controller.targets().last().unwrap(), &format!("/api/models/folder?path={WHOLE}"));
}

#[test]
fn a_folder_whose_links_changed_is_brought_again() {
    let controller = folder_controller(listing(), &FILES);
    let rig = Rig::new("folder-links").with_controller(&controller);
    let local = rig.cache.join(WHOLE);
    rig.models.ensure(WHOLE, &folder_fetch()).unwrap();
    let mut changed = listing();
    changed["links"][1] = json!({"path": "snap/h3", "target": "h1"});
    let newer = folder_controller(changed, &FILES);
    let rig = rig.with_controller(&newer);
    rig.models.ensure(WHOLE, &folder_fetch()).unwrap();
    assert!(local.join("snap/h3").symlink_metadata().is_ok(), "the link the controller lists now");
    assert!(local.join("snap/h2").symlink_metadata().is_err(), "and not the one it listed before");
}

#[test]
fn a_folder_the_controller_lists_otherwise_is_brought_again_and_one_nobody_can_ask_about_stays() {
    let controller = folder_controller(listing(), &FILES);
    let rig = Rig::new("folder-stale").with_controller(&controller);
    let local = rig.cache.join(WHOLE);
    rig.models.ensure(WHOLE, &folder_fetch()).unwrap();
    let changed = {
        let mut changed = listing();
        changed["files"][0] = json!({"path": "config.json", "size": 9});
        changed
    };
    let newer = folder_controller(changed.clone(), &[("config.json", b"{\"a\": 22}"), FILES[1], FILES[2], FILES[3]]);
    let rig = rig.with_controller(&newer);
    assert_eq!(rig.models.ensure(WHOLE, &folder_fetch()).unwrap(), local);
    assert_eq!(
        fs::read(local.join("config.json")).unwrap(),
        b"{\"a\": 22}",
        "the checkpoint changed in the library: the old folder is not run"
    );
    let mark: Value = serde_json::from_slice(&fs::read(local.join(".caravan-folder.json")).unwrap()).unwrap();
    assert_eq!(mark["files"], changed["files"]);
    let gone = rig.with_controller(&StandIn::serving(|_| StandIn::answer("502 Bad Gateway", b"down")));
    assert_eq!(
        gone.models.ensure(WHOLE, &folder_fetch()).unwrap(),
        local,
        "a machine that comes up before its controller starts what it has"
    );
}

#[test]
fn a_fetch_cut_short_keeps_what_arrived_and_never_takes_the_name() {
    let broken = folder_controller(listing(), &FILES[..2]);
    let rig = Rig::new("folder-cut").with_controller(&broken);
    let refused = rig.models.ensure(WHOLE, &folder_fetch()).err().unwrap();
    assert_eq!(refused.status, 500);
    let local = rig.cache.join(WHOLE);
    assert!(!local.exists(), "no half a folder under the model's name");
    let part = rig.cache.join("seam/facebook/FP32.part");
    assert_eq!(fs::read(part.join("config.json")).unwrap(), FILES[0].1);
    assert_eq!(rig.written_down(), ["seam/facebook/FP32.part"], "and it is this scout's to finish or to purge");
    let whole = folder_controller(listing(), &FILES);
    rig.config.set("controllerUrl", json!(whole.address()));
    rig.models.ensure(WHOLE, &folder_fetch()).unwrap();
    assert_eq!(fetched_files(&whole), ["sub/conf.yaml", "blobs/abc"], "a file of its own size stays");
    assert_eq!(fs::read(local.join("blobs/abc")).unwrap(), b"BLOB");
    assert!(!part.exists());
    assert_eq!(rig.written_down(), [WHOLE]);
}

#[test]
fn a_file_of_the_wrong_size_in_the_part_is_fetched_again() {
    let controller = folder_controller(listing(), &FILES);
    let rig = Rig::new("folder-short").with_controller(&controller);
    let part = rig.cache.join("seam/facebook/FP32.part");
    rig.put("seam/facebook/FP32.part/config.json", FILES[0].1);
    rig.put("seam/facebook/FP32.part/model-00001.safetensors", b"WEIGHTS");
    rig.models.downloaded.add(&part);
    rig.models.ensure(WHOLE, &folder_fetch()).unwrap();
    assert_eq!(fetched_files(&controller), ["model-00001.safetensors", "sub/conf.yaml", "blobs/abc"]);
    assert_eq!(fs::read(rig.cache.join(WHOLE).join("model-00001.safetensors")).unwrap(), b"WEIGHTS-1");
}

#[test]
fn a_folder_this_scout_did_not_download_is_not_replaced_and_nothing_is_asked() {
    let controller = folder_controller(listing(), &FILES);
    let rig = Rig::new("folder-foreign").with_controller(&controller);
    let foreign = rig.put(&format!("{WHOLE}/config.json"), b"by hand");
    let refused = rig.models.ensure(WHOLE, &folder_fetch()).err().unwrap();
    assert_eq!(refused.status, 409);
    assert_eq!(
        refused.message,
        format!("{} is there and was not downloaded by this scout: not replaced", rig.cache.join(WHOLE).display())
    );
    assert_eq!(fs::read(&foreign).unwrap(), b"by hand");
    assert_eq!(controller.targets().len(), 0);
    assert!(!rig.cache.join("seam/facebook/FP32.part").exists());
}

#[test]
fn a_link_where_the_folder_should_be_is_not_replaced() {
    let controller = folder_controller(listing(), &FILES);
    let rig = Rig::new("folder-link").with_controller(&controller);
    let real = rig.folder.path.join("real");
    fs::create_dir_all(real.join("sub")).unwrap();
    let parent = rig.cache.join("seam/facebook");
    fs::create_dir_all(&parent).unwrap();
    std::os::unix::fs::symlink(&real, parent.join("FP32")).unwrap();
    assert_eq!(rig.models.ensure(WHOLE, &folder_fetch()).err().unwrap().status, 409);
    assert!(parent.join("FP32").is_symlink() && real.join("sub").is_dir());
    fs::remove_dir_all(&real).unwrap();
    assert_eq!(
        rig.models.ensure(WHOLE, &folder_fetch()).err().unwrap().status,
        409,
        "a link that leads nowhere is in the way too"
    );
    assert_eq!(controller.targets().len(), 0);
}

#[test]
fn a_folder_of_this_scout_s_own_files_is_completed_where_it_is_and_one_foreign_file_makes_it_foreign() {
    let controller = folder_controller(listing(), &FILES);
    let rig = Rig::new("folder-own").with_controller(&controller);
    let local = rig.cache.join(WHOLE);
    rig.ours(&format!("{WHOLE}/config.json"), FILES[0].1);
    rig.ours(&format!("{WHOLE}/model-00001.safetensors"), FILES[1].1);
    rig.models.ensure(WHOLE, &folder_fetch()).unwrap();
    assert_eq!(fetched_files(&controller), ["sub/conf.yaml", "blobs/abc"]);
    assert!(local.join(".caravan-folder.json").is_file() && !rig.cache.join("seam/facebook/FP32.part").exists());
    assert_eq!(rig.written_down(), [WHOLE], "the folder is written down, its files one by one forgotten");

    for (name, stranger) in [("folder-note", "notes.txt"), ("folder-hidden", ".hidden-note")] {
        let controller = folder_controller(listing(), &FILES);
        let rig = Rig::new(name).with_controller(&controller);
        rig.ours(&format!("{WHOLE}/config.json"), FILES[0].1);
        let foreign = rig.put(&format!("{WHOLE}/{stranger}"), b"by hand");
        assert_eq!(rig.models.ensure(WHOLE, &folder_fetch()).err().unwrap().status, 409, "{stranger}");
        assert_eq!(controller.targets().len(), 0, "{stranger}");
        assert_eq!(fs::read(&foreign).unwrap(), b"by hand", "{stranger}");
        assert_eq!(rig.written_down(), [format!("{WHOLE}/config.json")], "{stranger}");
    }

    let controller = folder_controller(listing(), &FILES);
    let rig = Rig::new("folder-neighbour").with_controller(&controller);
    rig.ours("seam/facebook/FP3", b"a file of this scout");
    let foreign = rig.put(&format!("{WHOLE}/config.json"), b"by hand");
    assert_eq!(
        rig.models.ensure(WHOLE, &folder_fetch()).err().unwrap().status,
        409,
        "FP3 on the record does not make FP32 this scout's"
    );
    assert_eq!(fs::read(&foreign).unwrap(), b"by hand");
}

#[test]
fn a_folder_on_the_record_is_replaced_whole_when_a_new_one_is_ready() {
    let controller = folder_controller(listing(), &FILES);
    let rig = Rig::new("folder-replace").with_controller(&controller);
    let local = rig.cache.join(WHOLE);
    let stale = rig.put(&format!("{WHOLE}/stale.bin"), b"old");
    rig.models.downloaded.add(&local);
    rig.models.ensure(WHOLE, &folder_fetch()).unwrap();
    assert!(!stale.exists(), "the old folder went");
    assert_eq!(fs::read(local.join("config.json")).unwrap(), FILES[0].1);
    assert_eq!(rig.written_down(), [WHOLE]);
}

#[test]
fn the_record_is_asked_again_at_the_moment_of_the_swap() {
    let rig = Arc::new(Mutex::new(None::<Arc<ModelFetcher>>));
    let local = Arc::new(Mutex::new(PathBuf::new()));
    let (holder, place) = (Arc::clone(&rig), Arc::clone(&local));
    let files: BTreeMap<String, Vec<u8>> = FILES.iter().map(|(rel, bytes)| (format!("{WHOLE}/{rel}"), bytes.to_vec())).collect();
    let said = listing().to_string().into_bytes();
    let controller = StandIn::serving(move |head| {
        let target = head.split_whitespace().nth(1).unwrap_or_default();
        if target.starts_with("/api/models/folder?") {
            return StandIn::answer("200 OK", &said);
        }
        // While the files come, the folder there stops being this scout's.
        let models = holder.lock().unwrap().clone().unwrap();
        models.downloaded.forget(&place.lock().unwrap());
        StandIn::answer("200 OK", &files[target.split_once("path=").unwrap().1])
    });
    let scout = Rig::new("folder-swap").with_controller(&controller);
    *rig.lock().unwrap() = Some(Arc::clone(&scout.models));
    let there = scout.cache.join(WHOLE);
    *local.lock().unwrap() = there.clone();
    let kept = scout.put(&format!("{WHOLE}/mine.bin"), b"keep");
    scout.models.downloaded.add(&there);
    assert_eq!(scout.models.ensure(WHOLE, &folder_fetch()).err().unwrap().status, 409);
    assert_eq!(fs::read(&kept).unwrap(), b"keep");
    assert!(scout.cache.join("seam/facebook/FP32.part/config.json").exists(), "what came stays for the next try");
}

#[test]
fn a_listing_that_leads_out_of_the_folder_writes_nothing_and_a_listing_that_is_none_is_refused() {
    let cases = [
        ("out-file", json!({"files": [{"path": "../../evil", "size": 1}], "links": []})),
        ("abs-file", json!({"files": [{"path": "/etc/evil", "size": 1}], "links": []})),
        ("out-link", json!({"files": [], "links": [{"path": "x", "target": "../../../evil"}]})),
        ("abs-link", json!({"files": [], "links": [{"path": "x", "target": "/etc/passwd"}]})),
        ("out-at", json!({"files": [], "links": [{"path": "../../x", "target": "y"}]})),
        ("empty", json!({"files": [{"path": "", "size": 1}], "links": []})),
        ("none", json!([1, 2])),
        ("no-links", json!({"files": []})),
    ];
    for (name, said) in cases {
        let controller = folder_controller(said, &[("../../evil", b"E")]);
        let rig = Rig::new(&format!("folder-{name}")).with_controller(&controller);
        let refused = rig.models.ensure(WHOLE, &folder_fetch()).err().unwrap();
        assert_eq!(refused.status, 502, "{name}: {}", refused.message);
        assert!(!rig.cache.join(WHOLE).exists(), "{name}");
        assert!(!rig.cache.join("seam/evil").exists() && !rig.cache.join("seam/facebook/evil").exists(), "{name}");
        assert_eq!(fetched_files(&controller), Vec::<String>::new(), "{name}");
    }
}

#[test]
fn an_absolute_path_in_a_listing_is_refused_even_when_it_comes_to_the_folder_itself() {
    let rig = Rig::new("folder-abs-inside");
    let inside = rig.cache.join("seam/facebook/FP32.part/x");
    let said = json!({"files": [{"path": inside.to_string_lossy(), "size": 1}], "links": []});
    let controller = StandIn::serving(move |head| {
        if head.split_whitespace().nth(1).unwrap_or_default().starts_with("/api/models/folder?") {
            StandIn::answer("200 OK", said.to_string().as_bytes())
        } else {
            StandIn::answer("200 OK", b"x")
        }
    });
    let rig = rig.with_controller(&controller);
    let refused = rig.models.ensure(WHOLE, &folder_fetch()).err().unwrap();
    assert_eq!(refused.status, 502, "{}", refused.message);
    assert!(!inside.exists());
}

#[test]
fn a_link_to_an_absolute_path_is_said_to_be_one() {
    let controller = folder_controller(json!({"files": [], "links": [{"path": "x", "target": "/etc/passwd"}]}), &[]);
    let rig = Rig::new("folder-abs-link").with_controller(&controller);
    let refused = rig.models.ensure(WHOLE, &folder_fetch()).err().unwrap();
    assert_eq!(refused.message, format!("the controller listed a link out of the folder {WHOLE}: x -> /etc/passwd"));
}

#[test]
fn a_folder_with_no_controller_is_refused() {
    let bare = Rig::new("folder-no-controller");
    let refused = bare.models.ensure(WHOLE, &folder_fetch()).err().unwrap();
    assert_eq!(
        (refused.status, refused.message.as_str()),
        (404, format!("model not found locally and controllerUrl not set: {WHOLE}").as_str())
    );
}

#[test]
fn the_keep_is_one_to_five_and_anything_else_is_refused_not_rounded() {
    let rig = Rig::new("keep");
    let keep = &rig.keeper.keep;
    assert_eq!(keep.value(), 1, "until set");
    assert_eq!((keep.set(&json!(3)).unwrap(), keep.value()), (3, 3));
    assert_eq!(rig.state.get("cacheKeep"), Some(json!(3)), "in the scout's own memory");
    for bad in [
        json!(0),
        json!(6),
        json!(-1),
        json!(100),
        json!("3"),
        json!(2.5),
        json!(true),
        json!(false),
        Value::Null,
        json!([]),
        json!({}),
    ] {
        let refused = keep.set(&bad).err().unwrap();
        assert_eq!((refused.status, refused.message.as_str()), (400, "keep must be a whole number from 1 to 5"), "{bad}");
        assert_eq!(keep.value(), 3, "{bad}");
    }
    assert_eq!((keep.set(&json!(1)).unwrap(), keep.set(&json!(5)).unwrap()), (1, 5));
    for stored in [json!(9), json!(0), json!("2"), json!(true), json!(2.0), Value::Null, json!([1])] {
        rig.state.change(|doc| doc.insert("cacheKeep".to_string(), stored.clone()));
        assert_eq!(keep.value(), 1, "{stored}: a hand-edited file does not break the trim");
    }
}

#[test]
fn the_budget_is_a_whole_number_of_bytes_and_null_takes_it_off() {
    let rig = Rig::new("budget");
    let budget = &rig.keeper.budget;
    let five = 5_i64 << 30;
    assert_eq!(budget.value(), None, "a size nobody chose is not made up");
    assert_eq!((budget.set(&json!(five)).unwrap(), budget.value()), (Some(five), Some(five)));
    for bad in
        [json!(0), json!((1_i64 << 30) - 1), json!((1_i64 << 50) + 1), json!("5"), json!(2.5), json!(true), json!([]), json!({})]
    {
        assert_eq!(budget.set(&bad).err().map(|refused| refused.status), Some(400), "{bad}");
        assert_eq!(budget.value(), Some(five), "{bad}");
    }
    assert_eq!(budget.set(&json!(1_i64 << 30)).unwrap(), Some(1 << 30));
    assert_eq!((budget.set(&Value::Null).unwrap(), budget.value()), (None, None));
    assert_eq!(rig.state.get("cacheBudgetBytes"), None);
    for stored in [json!("5"), json!(true), json!(12), json!(-1), json!(2.0)] {
        rig.state.change(|doc| doc.insert("cacheBudgetBytes".to_string(), stored.clone()));
        assert_eq!(budget.value(), None, "{stored}: a hand-edited file does not trim the cache");
    }
}

#[test]
fn the_log_of_starts_is_newest_first_and_a_model_that_ran_keeps_its_word() {
    let rig = Rig::new("uses");
    let uses = &rig.keeper.uses;
    rig.begin("c22001", &[A, "", "  ", C_MM]);
    let first = &uses.entries()[0];
    assert_eq!((&first["files"], &first["cell"], &first["ok"]), (&json!([A, C_MM]), &json!("c22001"), &json!(false)));
    rig.begin("c22002", &[B]);
    uses.commit("c22001");
    let row = |entry: &Value| {
        (
            entry["files"][0].as_str().unwrap().to_string(),
            entry["cell"].as_str().unwrap().to_string(),
            entry["ok"].as_bool().unwrap(),
        )
    };
    let entry = |file: &str, cell: &str, ok: bool| (file.to_string(), cell.to_string(), ok);
    assert_eq!(uses.entries().iter().map(row).collect::<Vec<_>>(), [entry(B, "c22002", false), entry(A, "c22001", true)]);
    rig.begin("c22003", &[A]);
    assert_eq!(
        uses.entries().iter().map(row).collect::<Vec<_>>(),
        [entry(A, "c22003", true), entry(B, "c22002", false)],
        "a model that ran is not unmade by a start that may fail"
    );
    uses.commit("c99999");
    assert_eq!(uses.entries().len(), 2);
    rig.begin("c22009", &["", "  "]);
    assert_eq!(uses.entries().len(), 2, "a start that names no file is no entry");
    for at in 0..30 {
        rig.begin(&format!("c{}", 23000 + at), &[&format!("m{at}.gguf")]);
    }
    assert_eq!(uses.entries().len(), 20);
    assert_eq!(uses.entries()[0]["files"], json!(["m29.gguf"]));
    rig.state.change(|doc| {
        doc.insert(
            "modelUse".to_string(),
            json!([1, "x", {"files": []}, {"files": [3]}, {"files": ["a.gguf"], "cell": "c1", "ok": true}, {"nofiles": 1}]),
        )
    });
    assert_eq!(uses.entries().len(), 1, "junk is skipped, a sound entry is read");
    assert_eq!(uses.newest(1), [json!({"files": ["a.gguf"], "cell": "c1", "ok": true})]);
    assert_eq!(uses.newest(0), Vec::<Value>::new());
}

#[test]
fn nothing_is_trimmed_while_no_model_is_known_to_have_run() {
    let rig = Rig::shelf("trim-waiting");
    let before = rig.left();
    assert_eq!(rig.keeper.trim(), json!({"removed": 0, "freedBytes": 0, "waiting": true}), "unknown is not nothing");
    rig.begin("c22005", &[A]);
    assert_eq!(rig.keeper.trim()["waiting"], json!(true), "a start that reached no running process is no model that ran");
    assert_eq!(rig.left(), before);
    assert_eq!(rig.keeper.set_keep(&json!(1)).unwrap()["waiting"], json!(true));
    assert_eq!(rig.left(), before);
}

#[test]
fn a_trim_keeps_the_last_model_with_its_files_and_takes_what_is_older_and_never_a_foreign_file() {
    let rig = Rig::shelf("trim");
    rig.ran("c22001", &[A]);
    rig.ran("c22002", &[B]);
    rig.ran("c22003", &[C, C_MM]);
    let result = rig.keeper.trim();
    assert_eq!(rig.left(), sorted(vec![C, C_MM, FOREIGN]));
    assert_eq!(result, json!({"removed": 5, "freedBytes": 87, "waiting": false}), "A, B, both parts and the folder as one entry");
    assert!(!rig.cache.join("org/a").exists() && !rig.cache.join("fold").exists() && rig.cache.join("org/c/q4").is_dir());
    assert_eq!(rig.keeper.trim(), json!({"removed": 0, "freedBytes": 0, "waiting": false}), "a second trim finds nothing to do");
}

#[test]
fn a_trim_keeps_as_many_models_as_the_setting_says() {
    let rig = Rig::shelf("trim-two");
    rig.keeper.keep.set(&json!(2)).unwrap();
    rig.ran("c22001", &[A]);
    rig.ran("c22002", &[B]);
    rig.ran("c22003", &[C, C_MM]);
    rig.keeper.trim();
    assert_eq!(rig.left(), sorted(vec![B, C, C_MM, FOREIGN]));

    let rig = Rig::shelf("trim-five");
    rig.keeper.keep.set(&json!(5)).unwrap();
    rig.ran("c22001", &[A]);
    rig.ran("c22002", &[B]);
    rig.ran("c22003", &[C, C_MM]);
    rig.keeper.trim();
    assert_eq!(rig.left(), sorted(vec![A, B, C, C_MM, FOREIGN]), "and what never ran in this log is not one of them");
}

#[test]
fn a_kept_model_keeps_every_part_and_a_folder_stays_or_goes_whole() {
    let rig = Rig::shelf("trim-parts");
    rig.ran("c22001", &[S1]);
    rig.ran("c22002", &[C]);
    rig.keeper.set_keep(&json!(2)).unwrap();
    assert!(rig.cache.join(S1).exists() && rig.cache.join(S2).exists(), "the engine opens the other parts by name");

    let rig = Rig::shelf("trim-folder-goes");
    rig.ran("c22001", &[FOLDER]);
    rig.ran("c22002", &[C]);
    rig.keeper.trim();
    assert!(!rig.cache.join(FOLDER).exists());

    let rig = Rig::shelf("trim-folder-stays");
    rig.ran("c22001", &[C]);
    rig.ran("c22002", &[FOLDER]);
    rig.keeper.trim();
    assert!(rig.cache.join(FOLDER).join("FP32/weights.bin").is_file() && !rig.cache.join(C).exists());
}

#[test]
fn a_running_process_or_a_live_cell_keeps_its_model_whatever_its_age() {
    let rig = Rig::shelf("trim-held");
    rig.ran("c22001", &[A]);
    rig.ran("c22002", &[C]);
    rig.cells.held.lock().unwrap().push(rig.cache.join(A).to_string_lossy().into_owned());
    rig.keeper.trim();
    assert!(rig.cache.join(A).exists() && rig.cache.join(C).exists() && !rig.cache.join(B).exists());

    let rig = Rig::shelf("trim-starting");
    rig.ran("c22001", &[A]);
    rig.begin("c22002", &[B]);
    rig.ran("c22003", &[C, C_MM]);
    rig.cells.live.lock().unwrap().insert("c22002".to_string());
    rig.keeper.trim();
    assert!(rig.cache.join(B).exists(), "a cell still starting has asked for its files from its first moment");
    assert!(!rig.cache.join(A).exists());
    rig.cells.live.lock().unwrap().clear();
    rig.keeper.trim();
    assert!(!rig.cache.join(B).exists(), "the same start that failed is no model that ran");

    let rig = Rig::shelf("trim-live");
    rig.ran("c22001", &[A]);
    rig.ran("c22002", &[B]);
    rig.ran("c22003", &[C, C_MM]);
    rig.cells.live.lock().unwrap().insert("c22001".to_string());
    rig.keeper.trim();
    assert!(
        rig.cache.join(A).exists() && !rig.cache.join(B).exists(),
        "it ran, and its cell is alive: it stays beyond the setting"
    );
}

#[test]
fn a_start_that_never_ran_takes_no_place_from_the_model_that_did() {
    let rig = Rig::shelf("trim-not-ran");
    rig.ran("c22001", &[A]);
    rig.begin("c22002", &[B]);
    rig.keeper.trim();
    assert!(rig.cache.join(A).exists(), "the last model that ran");
    assert!(!rig.cache.join(B).exists(), "the newest asked for, its start not over and its cell not alive");
}

#[test]
fn a_trim_leaves_a_file_being_written_until_its_download_is_over() {
    let rig = Rig::shelf("trim-flight");
    rig.ran("c22001", &[A]);
    rig.ran("c22002", &[C, C_MM]);
    let tmp = rig.ours("org/b/q4/b-Q4.gguf.tmp", &[b'x'; 3]);
    rig.models.flying(&tmp, true);
    rig.keeper.trim();
    assert!(tmp.is_file(), "a trim on one port does not break a download on another");
    rig.models.flying(&tmp, false);
    rig.keeper.trim();
    assert!(!tmp.exists());
}

#[test]
fn lowering_the_setting_trims_at_once_and_raising_it_or_a_refused_number_takes_nothing() {
    let rig = Rig::shelf("trim-set");
    rig.keeper.keep.set(&json!(3)).unwrap();
    rig.ran("c22001", &[A]);
    rig.ran("c22002", &[B]);
    rig.ran("c22003", &[C, C_MM]);
    let result = rig.keeper.set_keep(&json!(1)).unwrap();
    assert_eq!((&result["keep"], &result["waiting"]), (&json!(1), &json!(false)));
    assert!(!rig.cache.join(A).exists() && !rig.cache.join(B).exists() && rig.cache.join(C).exists());
    let before = rig.left();
    assert_eq!(rig.keeper.set_keep(&json!(5)).unwrap()["removed"], json!(0));
    assert_eq!(rig.left(), before);
    assert_eq!(rig.keeper.set_keep(&json!(0)).err().map(|refused| refused.status), Some(400));
    assert_eq!(rig.keeper.keep.value(), 5);
    assert_eq!(rig.left(), before);
}

/// A cache of models that weigh gibibytes and take no room: A 10, B 20, C and its projector 35, the rest 57, all of them this scout's, and one foreign file.
fn weighed(name: &str, budget: i64, live: &[&str]) -> Rig {
    const GIB: u64 = 1 << 30;
    let rig = Rig::new(name);
    for (rel, size) in [(A, 10), (B, 20), (C, 30), (C_MM, 5), (S1, 7), (S2, 8), ("fold/x.gguf", 42)] {
        rig.ours_of(rel, size * GIB);
    }
    rig.put(FOREIGN, b"f");
    rig.ran("c22001", &[A]);
    rig.ran("c22002", &[B]);
    rig.ran("c22003", &[C, C_MM]);
    rig.cells.live.lock().unwrap().extend(live.iter().map(|cell| cell.to_string()));
    rig.keeper.set_budget(&json!(budget << 30)).unwrap();
    rig
}

#[test]
fn a_budget_keeps_the_newest_that_fit_and_lets_an_older_one_take_the_room_of_one_that_does_not() {
    for (budget, live, want) in [
        (60, &[][..], vec![B, C, C_MM]),
        (55, &[][..], vec![B, C, C_MM]),
        (50, &[][..], vec![A, C, C_MM]),
        (30, &[][..], vec![A, B]),
        (40, &["c22002"][..], vec![A, B]),
        (5, &["c22003"][..], vec![C, C_MM]),
    ] {
        let rig = weighed(&format!("budget-{budget}"), budget, live);
        let mut want = want;
        want.push(FOREIGN);
        assert_eq!(rig.left(), sorted(want), "{budget} GiB, live {live:?}");
    }
}

#[test]
fn a_budget_taken_off_gives_the_count_its_word_again() {
    let rig = weighed("budget-off", 100, &[]);
    assert_eq!(rig.left(), sorted(vec![A, B, C, C_MM, FOREIGN]));
    let result = rig.keeper.set_budget(&Value::Null).unwrap();
    assert_eq!(result["budgetBytes"], Value::Null);
    assert_eq!(rig.left(), sorted(vec![C, C_MM, FOREIGN]));
}

#[test]
fn a_size_that_is_no_size_takes_nothing() {
    let rig = weighed("budget-bad", 100, &[]);
    let before = rig.left();
    assert_eq!(rig.keeper.set_budget(&json!("2")).err().map(|refused| refused.status), Some(400));
    assert_eq!(rig.left(), before);
    assert_eq!(rig.keeper.budget.value(), Some(100 << 30));
}

#[test]
fn foreign_files_are_counted_without_the_hidden_scratch_and_what_is_no_model() {
    let rig = Rig::shelf("foreign");
    for (rel, size) in [
        (".cells/22001/scratch.bin", 50),
        ("llama-server.22001.log", 4),
        ("stray.tmp", 1),
        ("half.part", 1),
        ("org/f/readme.txt", 6),
        ("other/zz.gguf", 12),
        (".hidden/x.gguf", 99),
    ] {
        rig.put(rel, &vec![b'x'; size]);
    }
    let mut found: Vec<(String, u64)> = rig
        .keeper
        .foreign_files()
        .into_iter()
        .map(|(path, size)| (path.strip_prefix(&rig.cache).unwrap().to_string_lossy().into_owned(), size))
        .collect();
    found.sort();
    assert_eq!(found, [(FOREIGN.to_string(), 9), ("org/f/readme.txt".to_string(), 6), ("other/zz.gguf".to_string(), 12)]);
    assert_eq!(
        rig.keeper.facts()["foreign"],
        json!({"files": 3, "bytes": 27, "folders": [{"folder": "org", "files": 2, "bytes": 15}, {"folder": "other", "files": 1, "bytes": 12}]})
    );
    assert_eq!(Rig::new("foreign-none").keeper.foreign_files(), Vec::<(PathBuf, u64)>::new());
}

#[test]
fn foreign_files_go_only_with_the_figure_the_operator_was_shown() {
    let rig = Rig::shelf("foreign-delete");
    let foreign = rig.cache.join(FOREIGN);
    for bad in [None, Some(json!("many")), Some(Value::Null), Some(json!([9]))] {
        let refused = rig.keeper.delete_foreign(bad.as_ref()).err().unwrap();
        assert_eq!(
            (refused.status, refused.message.as_str()),
            (400, "expectBytes is required: the size the operator was shown"),
            "{bad:?}"
        );
    }
    for wrong in [json!(10), json!(8), json!(0), json!(-9)] {
        let refused = rig.keeper.delete_foreign(Some(&wrong)).err().unwrap();
        assert_eq!(refused.status, 409, "{wrong}");
        assert!(refused.message.contains("nothing was deleted"), "{}", refused.message);
        assert!(foreign.is_file(), "{wrong}");
    }
    rig.cells.held.lock().unwrap().push(foreign.to_string_lossy().into_owned());
    assert_eq!(
        rig.keeper.delete_foreign(Some(&json!(9))).unwrap(),
        json!({"removed": 0, "freedBytes": 0}),
        "a running cell holds it"
    );
    assert!(foreign.is_file());
    rig.cells.held.lock().unwrap().clear();
    rig.models.flying(&foreign, true);
    assert_eq!(
        rig.keeper.delete_foreign(Some(&json!(9))).unwrap(),
        json!({"removed": 0, "freedBytes": 0}),
        "it is being written"
    );
    rig.models.flying(&foreign, false);
    assert_eq!(rig.keeper.delete_foreign(Some(&json!(9))).unwrap(), json!({"removed": 1, "freedBytes": 9}));
    assert!(!foreign.exists() && !rig.cache.join("org/f").exists());
    assert!(
        rig.cache.join(A).is_file() && rig.cache.join(FOLDER).join("FP32/weights.bin").is_file(),
        "what the record holds is not touched"
    );
    assert!(rig.cache.is_dir());
}

#[test]
fn a_deletion_of_foreign_files_prunes_empty_folders_but_not_the_hidden_ones() {
    let rig = Rig::new("foreign-prune");
    let scratch = rig.put(".cells/22001/x", b"1");
    fs::create_dir_all(rig.cache.join(".cells/c22002")).unwrap();
    rig.put("org/zz/lonely.gguf", &[b'x'; 4]);
    assert_eq!(rig.keeper.delete_foreign(Some(&json!(4))).unwrap()["removed"], json!(1));
    assert!(scratch.is_file() && rig.cache.join(".cells/c22002").is_dir(), "a cell's scratch not yet filled");
    assert!(!rig.cache.join("org").exists());
}

#[test]
fn the_figures_are_reused_for_some_seconds_and_measured_again_after_a_deletion() {
    let rig = Rig::shelf("facts");
    rig.keeper.keep.set(&json!(2)).unwrap();
    let facts = rig.keeper.facts();
    assert_eq!((&facts["keep"], &facts["budgetBytes"]), (&json!(2), &Value::Null));
    assert_eq!(facts["dir"], json!(rig.cache.to_string_lossy()));
    assert_eq!(facts["managedBytes"], json!(122), "what the record names and the disk holds, a folder whole");
    rig.put("org/f/new.gguf", &[b'x'; 100]);
    assert_eq!(rig.keeper.facts()["foreign"]["bytes"], json!(9), "the heartbeat and the controller's polls both ask");
    rig.keeper.keep.set(&json!(4)).unwrap();
    assert_eq!(rig.keeper.facts()["keep"], json!(4), "the setting is never reused");
    rig.clock.pass(21);
    assert_eq!(rig.keeper.facts()["foreign"]["bytes"], json!(109));
    rig.ran("c22001", &[C]);
    rig.keeper.keep.set(&json!(1)).unwrap();
    rig.keeper.trim();
    assert_eq!(rig.keeper.facts()["managedBytes"], json!(30), "a trim makes the next report measure again");
}

#[test]
fn the_cache_moves_with_only_what_this_scout_downloaded_going() {
    let rig = Rig::shelf("move");
    rig.ours("w/ggml-base.bin", &[b'x'; 11]);
    let hdd = rig.folder.path.join("hdd/models");
    rig.cells.held.lock().unwrap().push(rig.cache.join(C).to_string_lossy().into_owned());
    let result = rig.keeper.move_to(&json!(hdd.to_string_lossy()), &Value::Null).unwrap();
    assert_eq!(
        result,
        json!({"dir": hdd.to_string_lossy(), "removed": 8, "freedBytes": 133}),
        "every kind, and the folder model whole"
    );
    assert_eq!(rig.left(), [FOREIGN], "the file this scout did not download stays in the old folder");
    assert!(!rig.cache.join(RECORD).exists());
    assert_eq!(rig.models.cache_dir(), hdd);
    assert_eq!(fs::read_dir(&hdd).unwrap().count(), 0, "made, and no probe left");
    assert_eq!(rig.state.get("cacheDir"), Some(json!(hdd.to_string_lossy())));
    assert_eq!(rig.keeper.facts()["managedBytes"], json!(0));
}

#[test]
fn a_move_that_is_refused_deletes_nothing_and_the_cache_stays() {
    let rig = Rig::shelf("move-refused");
    let before = rig.left();
    let blocker = rig.folder.path.join("a-file");
    fs::write(&blocker, b"x").unwrap();
    let text = |path: &Path| json!(path.to_string_lossy());
    for (path, words) in [
        (json!(""), "lies in its own folder already"),
        (Value::Null, "lies in its own folder already"),
        (json!("relative/dir"), "must be an absolute path"),
        (text(&rig.cache), "is in"),
        (text(&rig.cache.join("inside")), "may not lie inside the old one or hold it"),
        (text(&rig.folder.path), "may not lie inside the old one or hold it"),
        (text(&blocker.join("sub")), "the cache cannot be in"),
    ] {
        let refused = rig.keeper.move_to(&path, &Value::Null).err().unwrap();
        assert_eq!(refused.status, 400, "{path}");
        assert!(refused.message.contains(words), "{path}: {}", refused.message);
        assert_eq!(rig.models.cache_dir(), rig.cache, "{path}");
        assert_eq!(rig.left(), before, "{path}");
    }
    rig.cells.loading.lock().unwrap().extend(["c22005", "c22003"].map(String::from));
    let hdd = rig.folder.path.join("hdd");
    let refused = rig.keeper.move_to(&text(&hdd), &Value::Null).err().unwrap();
    assert_eq!(
        (refused.status, refused.message.as_str()),
        (409, "the cache does not move while a cell is bringing its model: c22003, c22005 — try again when it runs")
    );
    assert!(!hdd.exists(), "a refused move makes no folder on the disk it named");
    assert_eq!(rig.models.cache_dir(), rig.cache);
    assert_eq!(rig.left(), before);
}

#[test]
fn a_chosen_folder_is_read_back_and_one_that_is_no_absolute_path_is_no_setting() {
    let rig = Rig::new("move-state");
    rig.state.change(|doc| doc.insert("cacheDir".to_string(), json!("relative/path")));
    assert_eq!(rig.models.cache_dir(), rig.cache);
    rig.state.change(|doc| doc.insert("cacheDir".to_string(), json!("/mnt/hdd")));
    assert_eq!(rig.models.cache_dir(), Path::new("/mnt/hdd"));
}

#[test]
fn the_cache_turned_off_takes_what_is_this_scout_s_but_for_what_a_cell_holds() {
    let rig = Rig::shelf("off");
    let library = rig.folder.path.join("library");
    fs::create_dir_all(&library).unwrap();
    rig.cells.held.lock().unwrap().push(rig.cache.join(C).to_string_lossy().into_owned());
    let result = rig.keeper.set_off(&json!(true), &json!(library.to_string_lossy())).unwrap();
    assert_eq!((&result["off"], &result["removed"]), (&json!(true), &json!(6)));
    assert_eq!(rig.left(), sorted(vec![C, FOREIGN]));
    assert!(rig.models.off.is_off());
    let result = rig.keeper.set_off(&json!(false), &Value::Null).unwrap();
    assert_eq!((&result["off"], &result["removed"]), (&json!(false), &json!(0)));
    assert_eq!(rig.left(), sorted(vec![C, FOREIGN]), "turned on, it takes nothing");
}

#[test]
fn the_cache_is_not_turned_off_with_no_way_to_read_or_while_a_start_brings_its_files() {
    let rig = Rig::shelf("off-refused");
    let before = rig.left();
    let library = rig.folder.path.join("library");
    for (off, said) in [
        (json!("yes"), json!(library.to_string_lossy())),
        (json!(true), json!(library.to_string_lossy())),
        (json!(true), json!("relative")),
    ] {
        let refused = rig.keeper.set_off(&off, &said).err().unwrap();
        assert_eq!(refused.status, 400, "{off} {said}");
        assert_eq!(rig.left(), before, "{off} {said}");
        assert!(!rig.models.off.is_off(), "{off} {said}");
    }
    let refused = rig.keeper.set_off(&json!(true), &Value::Null).err().unwrap();
    assert_eq!(refused.status, 409, "no folder named, and this machine cannot read through the controller");
    assert!(refused.message.contains("install fuse3"), "{refused:?}");
    assert_eq!(rig.left(), before);
    assert!(!rig.models.off.is_off());
    fs::create_dir_all(&library).unwrap();
    rig.cells.loading.lock().unwrap().insert("c22003".to_string());
    assert_eq!(
        rig.keeper.set_off(&json!(true), &json!(library.to_string_lossy())).err().map(|refused| refused.status),
        Some(409)
    );
    assert_eq!(rig.left(), before);
    assert!(!rig.models.off.is_off());
}

#[test]
fn a_cache_that_is_off_brings_nothing_to_this_disk() {
    let controller = controller_of(&[(A, b"from the controller")]);
    let rig = Rig::new("off-read").with_controller(&controller);
    let library = rig.folder.path.join("library");
    fs::create_dir_all(library.join("org/a/q4")).unwrap();
    fs::write(library.join(A), b"GGUF").unwrap();
    rig.keeper.set_off(&json!(true), &json!(library.to_string_lossy())).unwrap();
    assert_eq!(rig.models.ensure(A, &Fetch::default()).unwrap(), library.join(A));
    assert_eq!(
        rig.models.ensure(B, &Fetch::default()).err().map(|refused| refused.status),
        Some(409),
        "not there: it is said, and not fetched after all"
    );
    assert_eq!(controller.targets().len(), 0);
    assert_eq!(rig.written_down(), Vec::<String>::new());
    assert_eq!(rig.left(), Vec::<String>::new());
}

/// A cell's scratch folder on the cache with a file of this many bytes in it.
fn made(rig: &Rig, cell: &str, bytes: usize) -> PathBuf {
    made_on(&rig.models, cell, bytes)
}

/// The same on the shelf `models`.
fn made_on(models: &ModelFetcher, cell: &str, bytes: usize) -> PathBuf {
    let folder = models.scratch(cell);
    fs::create_dir_all(&folder).unwrap();
    fs::write(folder.join("pack.bin"), vec![b'p'; bytes]).unwrap();
    folder
}

#[test]
fn a_copy_of_another_size_is_brought_again_and_one_of_the_same_size_stays() {
    let rig = Rig::new("stale");
    let path = rig.ours(A, b"old");
    let controller = controller_of(&[(A, b"newer")]);
    let rig = rig.with_controller(&controller);
    let asked = |size: u64| Fetch { use_cache: true, hint: Some(json!({"path": "/not/here", "size": size})), ..Fetch::default() };
    assert_eq!(rig.models.ensure(A, &asked(3)).unwrap(), path);
    assert_eq!(fs::read(&path).unwrap(), b"old", "the size the controller says is the size here: no copy");
    assert_eq!(rig.models.ensure(A, &Fetch { use_cache: true, ..Fetch::default() }).unwrap(), path);
    assert_eq!(fs::read(&path).unwrap(), b"old", "no hint says nothing to differ from");
    assert_eq!(rig.models.ensure(A, &asked(5)).unwrap(), path);
    assert_eq!(fs::read(&path).unwrap(), b"newer", "the library's file changed under the same name: the old copy is not run");
    assert!(rig.models.downloaded.has(&path), "the new copy is this scout's");
}

#[test]
fn a_file_of_another_size_this_scout_did_not_bring_is_refused_not_run() {
    let rig = Rig::new("stale-foreign");
    let path = rig.put(A, b"by hand");
    let controller = controller_of(&[(A, b"the library's")]);
    let rig = rig.with_controller(&controller);
    let fetch = Fetch { use_cache: true, hint: Some(json!({"path": "/not/here", "size": 13})), ..Fetch::default() };
    let refused = rig.models.ensure(A, &fetch).unwrap_err();
    assert_eq!(refused.status, 409, "{refused:?}");
    assert_eq!(fs::read(&path).unwrap(), b"by hand", "what is not this scout's is not replaced");
}

#[test]
fn a_split_model_of_another_size_brings_all_its_parts_again() {
    let rig = Rig::new("stale-split");
    let (first, second) = (rig.ours(S1, b"old1"), rig.ours(S2, b"old2"));
    let controller = controller_of(&[(S1, b"newer1"), (S2, b"newer2")]);
    let rig = rig.with_controller(&controller);
    rig.models
        .ensure(S1, &Fetch { use_cache: true, hint: Some(json!({"path": "/not/here", "size": 4})), ..Fetch::default() })
        .unwrap();
    assert_eq!(
        (fs::read(&first).unwrap(), fs::read(&second).unwrap()),
        (b"old1".to_vec(), b"old2".to_vec()),
        "the same size: nothing is copied"
    );
    rig.models
        .ensure(S1, &Fetch { use_cache: true, hint: Some(json!({"path": "/not/here", "size": 6})), ..Fetch::default() })
        .unwrap();
    assert_eq!(fs::read(&first).unwrap(), b"newer1");
    assert_eq!(fs::read(&second).unwrap(), b"newer2", "a new first part is not joined to the old second");
}

#[test]
fn what_the_cells_made_is_counted_and_goes_with_clear_and_with_the_cache_going_off() {
    let rig = Rig::new("scratch");
    rig.ours(A, &[b'x'; 10]);
    let (idle, running) = (made(&rig, "c22001", 100), made(&rig, "c22002", 200));
    assert_eq!(rig.keeper.facts()["managedBytes"], 310, "what the board says the cache holds is what lies in it");
    rig.cells.live.lock().unwrap().insert("c22002".to_string());
    let cleared = rig.keeper.clear_unheld();
    assert!(!idle.exists(), "made from a model that went");
    assert!(running.exists(), "a running cell writes there");
    assert_eq!(cleared["freedBytes"], 110);
    assert_eq!(cleared["removed"], 2, "the copy and the one file made");
    rig.keeper.forget_figures();
    assert_eq!(rig.keeper.facts()["managedBytes"], 200);
    rig.cells.live.lock().unwrap().clear();
    let library = rig.folder.path.join("library");
    fs::create_dir_all(&library).unwrap();
    let off = rig.keeper.set_off(&json!(true), &json!(library.to_string_lossy())).unwrap();
    assert!(!running.exists(), "the cache going off takes it too");
    assert_eq!(off["freedBytes"], 200);
}

#[test]
fn a_folder_in_the_scratch_with_no_port_s_name_is_not_taken() {
    let rig = Rig::new("scratch-other");
    let other = rig.cache.join(".cells/not-a-port");
    fs::create_dir_all(&other).unwrap();
    made(&rig, "c22001", 1);
    rig.keeper.clear_unheld();
    assert!(other.exists());
    assert!(!rig.models.scratch("c22001").exists());
}

#[test]
fn what_a_cell_made_goes_when_the_trim_takes_its_model_and_stays_while_the_model_stays() {
    let rig = Rig::new("scratch-trim");
    rig.ours(A, &[b'x'; 10]);
    rig.ours(B, &[b'x'; 10]);
    let (a, b, unknown) = (made(&rig, "c1", 1), made(&rig, "c2", 1), made(&rig, "c3", 1));
    rig.keeper.uses.begin("c1", &[A.to_string()]);
    rig.keeper.commit("c1");
    assert!(a.exists(), "the model that ran stays, and what was made from it");
    assert!(!b.exists() && !unknown.exists(), "no model of the log stands behind these");
    rig.keeper.uses.begin("c2", &[B.to_string()]);
    made(&rig, "c2", 1);
    rig.keeper.commit("c2");
    assert!(!a.exists(), "A left the cache: keep is one model");
    assert!(rig.models.scratch("c2").exists());
    assert!(!rig.cache.join(A).exists());
}

#[test]
fn the_trim_takes_no_scratch_while_the_log_knows_no_model_that_ran() {
    let rig = Rig::new("scratch-waiting");
    let kept = made(&rig, "c1", 1);
    assert_eq!(rig.keeper.trim()["waiting"], true);
    assert!(kept.exists(), "unknown is not nothing");
}

#[test]
fn room_is_made_from_what_was_not_used_for_longest_and_only_until_there_is_enough() {
    let rig = Rig::new("room");
    let (a, b, c, foreign) =
        (rig.ours(A, &[b'x'; 10]), rig.ours(B, &[b'x'; 10]), rig.ours(C, &[b'x'; 10]), rig.put(FOREIGN, b"mine"));
    let never_logged = rig.ours("org/n/never.gguf", &[b'x'; 10]);
    let scratch_of_a = made(&rig, "c1", 1);
    for (cell, file) in [("c1", A), ("c2", B), ("c3", C)] {
        rig.keeper.uses.begin(cell, &[file.to_string()]);
    }
    rig.cells.live.lock().unwrap().insert("c3".to_string());
    // The disk has the room of the copies that are gone.
    let free = || Some([&a, &b, &c, &never_logged].iter().filter(|path| !path.exists()).count() as u64);
    assert_eq!(rig.keeper.room_until(1, 1, &free), Ok(()));
    assert!(!never_logged.exists(), "a copy the log does not name goes first");
    assert!(!a.exists(), "then the oldest");
    assert!(!scratch_of_a.exists(), "with what was made from it");
    assert!(b.exists(), "there is room: the rest stays");
    assert_eq!(rig.keeper.room_until(8, 1, &free), Err(room::Short::Disk { free: 3 }), "nothing more can go: said so");
    assert!(c.exists(), "the file of a cell that is starting stays whatever is short");
    assert!(foreign.exists(), "what is not this scout's stays");
    assert_eq!(rig.keeper.room_until(1 << 40, 1, &|| None), Ok(()), "a disk that does not say is not refused");
    assert_eq!(
        rig.keeper.room_until(1 << 40, 1, &|| Some(1 << 41)),
        Ok(()),
        "the cache's budget is what a trim keeps, not a bound on a copy"
    );
}

#[test]
fn a_copy_that_would_not_fit_is_refused_before_a_byte_is_written() {
    let rig = Rig::new("no-room");
    // 1 GB, and the 2 GB the machine keeps beside a copy, on a disk with 2 GB free: the answer is refused by its head, and its body never read.
    let head = b"HTTP/1.1 200 OK\r\nContent-Length: 1073741824\r\nConnection: close\r\n\r\nx".to_vec();
    let controller = StandIn::serving(move |_| head.clone());
    let rig = rig.with_controller(&controller);
    rig.disks.has(&rig.cache, Some(2 << 30));
    let refused = rig.models.ensure(A, &Fetch::default()).unwrap_err();
    let words = format!(
        "no room for a-Q4.gguf: it takes 1.0 GB and {} has 2.0 GB free, with every copy no cell is using gone. Nothing was copied. {}",
        rig.cache.display(),
        Shelf::CACHE.when_full
    );
    assert!(refused.message.contains(&words), "no keeper stands: the disk says it, {refused:?}");
    let asked = Arc::new(Mutex::new(Vec::new()));
    let heard = Arc::clone(&asked);
    rig.models.room_comes_from(Arc::new(move |bytes, label, free| {
        heard.lock().unwrap().push((bytes, label.to_string(), free()));
        Err(format!("the keeper's words for {label}"))
    }));
    let refused = rig.models.ensure(A, &Fetch::default()).unwrap_err();
    assert!(refused.message.contains("the keeper's words for a-Q4.gguf"), "{refused:?}");
    assert_eq!(
        *asked.lock().unwrap(),
        [(1 << 30, "a-Q4.gguf".to_string(), Some(2 << 30))],
        "the keeper was asked first, for the file, and handed what the cache's disk has free"
    );
    assert!(!rig.cache.join(A).exists());
    assert!(!rig.cache.join(A).with_extension("tmp").exists(), "not a byte");
    assert!(!rig.cache.join("org").exists(), "and no folder made for it is left");
    assert!(rig.cache.exists(), "the cache's own folder stays");
}

#[test]
fn the_cache_off_by_the_default_way_names_no_folder_and_a_folder_is_a_word_of_the_operator() {
    let rig = Rig::shelf("off-way");
    let can = Rig::with_view("off-way-can", || true);
    let through = &can.keeper;
    let answer = through.set_off(&json!(true), &Value::Null).unwrap();
    assert_eq!((&answer["off"], &answer["library"]), (&json!(true), &Value::Null));
    assert_eq!(through.facts()["through"], true, "off, and nobody named a folder: the long way");
    assert_eq!(through.facts()["canThrough"], true);
    let library = can.folder.path.join("library");
    fs::create_dir_all(&library).unwrap();
    let answer = through.set_off(&json!(true), &json!(library.to_string_lossy())).unwrap();
    assert_eq!(answer["library"], json!(library.to_string_lossy()));
    assert_eq!(through.facts()["through"], false, "a folder named: read from there");
    through.models.off.set(true, Some(&library));
    let _found = through.set_off(&json!(true), &json!("")).unwrap();
    assert_eq!(through.facts()["through"], true, "back to the controller: the folder stays known, and is not read");
    assert_eq!(through.facts()["library"], json!(library.to_string_lossy()));
    assert_eq!(rig.keeper.facts()["canThrough"], false, "a machine that cannot says so");
}

#[test]
fn a_library_found_by_itself_does_not_change_the_way() {
    let rig = Rig::new("off-found");
    let library = rig.folder.path.join("library");
    fs::create_dir_all(library.join("org/a/q4")).unwrap();
    fs::write(library.join(A), b"GGUF").unwrap();
    rig.models.off.set(true, Some(&library));
    assert!(!rig.models.off.from_folder(), "a mount the scout found is no word of the operator's");
    let refused = rig.models.ensure(A, &Fetch::default()).unwrap_err();
    assert!(refused.message.contains("through the controller") || refused.message.contains("controllerUrl"), "{refused:?}");
    rig.models.off.choose(true);
    assert_eq!(rig.models.ensure(A, &Fetch::default()).unwrap(), library.join(A), "on the operator's word it is read from there");
}

/// The folder for Strata's files chosen in the rig's own folder.
fn work_of(rig: &Rig, name: &str) -> PathBuf {
    let work = rig.folder.path.join(name);
    let said = rig.work.set_work(&json!(work.to_string_lossy()), &Value::Null).unwrap();
    assert_eq!(said["chosen"], true);
    work
}

/// A copy on the shelf `models` of `size` bytes that takes no room, as this scout downloaded it.
fn copy_on(models: &ModelFetcher, rel: &str, size: u64) -> PathBuf {
    let path = models.cache_dir().join(rel);
    fs::create_dir_all(path.parent().unwrap()).unwrap();
    fs::File::create(&path).unwrap().set_len(size).unwrap();
    models.downloaded.add(&path);
    path
}

#[test]
fn each_shelf_keeps_what_its_cells_make_in_its_own_folder() {
    let rig = Rig::new("work-chosen");
    assert_eq!(
        rig.models.scratch("c22001"),
        rig.cache.join(".cells/c22001"),
        "the cache's cells: in the cache's folder, as always"
    );
    assert_eq!(
        rig.work_models.scratch("c22009"),
        rig.cache.join(".strata/.cells/c22009"),
        "none chosen: a folder of its own, where nothing is written, for no start that needs it begins"
    );
    assert!(!rig.work_models.folder_chosen());
    let work = work_of(&rig, "ssd");
    assert!(rig.work_models.folder_chosen());
    assert_eq!(rig.work_models.scratch("c22009"), work.join(".cells/c22009"));
    assert_eq!(rig.models.scratch("c22001"), rig.cache.join(".cells/c22001"), "the cache's cells stay where they were");
    let new = made_on(&rig.work_models, "c22009", 10);
    let copy = copy_on(&rig.work_models, B, 20);
    fs::write(work.join("operator.txt"), b"his").unwrap();
    let back = rig.work.set_work(&json!(""), &Value::Null).unwrap();
    assert_eq!((&back["chosen"], &back["removed"], &back["freedBytes"]), (&json!(false), &json!(2), &json!(30)));
    assert!(!new.exists() && !work.join(".cells").exists(), "the scout's own folder goes when it is empty");
    assert!(
        !copy.exists() && !work.join("org").exists() && !work.join(RECORD).exists(),
        "the copies go with the folder, and their record"
    );
    assert!(work.join("operator.txt").exists(), "what the operator keeps in the folder he named stays");
    assert!(rig.work.set_work(&json!(""), &Value::Null).is_err(), "no folder to forget");
}

#[test]
fn the_board_hears_what_each_shelf_keeps_and_each_counts_only_its_own() {
    let rig = Rig::new("work-facts");
    rig.ours(A, &[b'x'; 30]);
    made(&rig, "c22001", 100);
    assert_eq!(rig.keeper.facts()["managedBytes"], 130, "what the cache's cells made takes its disk like a copy");
    let quiet = json!({"dir": rig.cache.join(".strata").to_string_lossy(), "chosen": false, "budgetBytes": 300i64 << 30, "budgetChosen": false});
    assert_eq!(rig.work.work_facts(), quiet, "no folder: nothing to measure, and the limit is the owner's 300 GB");
    let work = work_of(&rig, "ssd");
    copy_on(&rig.work_models, B, 20);
    copy_on(&rig.work_models, C, 25);
    made_on(&rig.work_models, "c22009", 70);
    rig.work.forget_figures();
    let facts = rig.work.work_facts();
    assert_eq!(facts["dir"], json!(work.to_string_lossy()));
    assert_eq!((&facts["bytes"], &facts["modelsBytes"], &facts["madeBytes"]), (&json!(115), &json!(45), &json!(70)));
    assert_eq!(facts["models"], json!([{"name": C, "bytes": 25}, {"name": B, "bytes": 20}]), "biggest first");
    assert!(facts["disk"]["totalBytes"].as_u64().is_some_and(|total| total > 0), "{facts}");
    rig.keeper.forget_figures();
    assert_eq!(rig.keeper.facts()["managedBytes"], 130, "Strata's files are not the cache's");
}

#[test]
fn the_folder_for_strata_s_files_does_not_move_while_a_cell_keeps_files_there_or_brings_its_model() {
    let rig = Rig::new("work-busy");
    let first = work_of(&rig, "ssd");
    let writing = made_on(&rig.work_models, "c22009", 5);
    rig.cells.live.lock().unwrap().insert("c22009".to_string());
    let hdd = json!(rig.folder.path.join("hdd").to_string_lossy());
    let refused = rig.work.set_work(&hdd, &Value::Null).unwrap_err();
    assert_eq!(refused.status, 409);
    assert!(refused.message.contains("c22009"), "{}", refused.message);
    assert!(writing.exists() && rig.work_models.cache_dir() == first, "nothing moved");
    assert!(!rig.folder.path.join("hdd").exists(), "and a refused move made no folder on the disk it named");
    rig.cells.live.lock().unwrap().clear();
    rig.cells.held.lock().unwrap().push(first.join(A).display().to_string());
    let refused = rig.work.set_work(&hdd, &Value::Null).unwrap_err();
    assert!(refused.message.contains("a cell that reads its model there"), "{}", refused.message);
    rig.cells.held.lock().unwrap().clear();
    rig.cells.loading.lock().unwrap().insert("c22011".to_string());
    let refused = rig.work.set_work(&hdd, &Value::Null).unwrap_err();
    assert_eq!(refused.status, 409);
    assert!(refused.message.contains("c22011"), "{}", refused.message);
    rig.cells.loading.lock().unwrap().clear();
    rig.cells.live.lock().unwrap().insert("c22010".to_string());
    assert!(rig.work.set_work(&hdd, &Value::Null).is_ok(), "a running cell with no files here keeps running where it is");
    assert!(!writing.exists(), "the stopped cell's files went");
}

#[test]
fn the_folder_for_strata_s_files_may_not_lie_in_the_cache_s_and_the_cache_may_not_hold_it() {
    let rig = Rig::new("work-nest");
    let refused = rig.work.set_work(&json!(rig.cache.join("strata").to_string_lossy()), &Value::Null).unwrap_err();
    assert!(refused.message.contains("may not lie in the cache's folder"), "{}", refused.message);
    assert!(rig.work.set_work(&json!(rig.cache.to_string_lossy()), &Value::Null).is_err(), "nor be it");
    assert!(rig.work.set_work(&json!("relative/path"), &Value::Null).is_err());
    let work = work_of(&rig, "hdd/strata");
    let refused = rig.keeper.move_to(&json!(rig.folder.path.join("hdd").to_string_lossy()), &Value::Null).unwrap_err();
    assert!(refused.message.contains("may not hold the folder for Strata's files"), "{}", refused.message);
    assert!(rig.keeper.move_to(&json!(work.to_string_lossy()), &Value::Null).is_err(), "nor be it");
    assert!(rig.keeper.move_to(&json!(rig.folder.path.join("ssd").to_string_lossy()), &Value::Null).is_ok());
}

#[test]
fn the_cache_cleared_or_turned_off_leaves_strata_s_shelf_alone() {
    let rig = Rig::new("work-apart");
    let work = work_of(&rig, "ssd");
    let (stopped, copy) = (made_on(&rig.work_models, "c1", 10), copy_on(&rig.work_models, B, 20));
    rig.ours(A, &[b'x'; 5]);
    let cleared = rig.keeper.clear_unheld();
    assert_eq!(cleared["freedBytes"], 5, "only the cache's copy");
    assert!(stopped.exists() && copy.exists(), "Clear is the cache's: Strata's models and what its cells made stay");
    let library = rig.folder.path.join("library");
    fs::create_dir_all(&library).unwrap();
    rig.keeper.set_off(&json!(true), &json!(library.to_string_lossy())).unwrap();
    assert!(stopped.exists() && copy.exists(), "the cache going off is the cache's too");
    assert!(work.exists());
}

#[test]
fn strata_s_limit_is_300_gb_until_the_operator_says_and_null_gives_it_back() {
    let rig = Rig::new("work-limit");
    assert_eq!((rig.work.budget.value(), rig.work.budget.chosen()), (Some(300 << 30), None));
    assert_eq!(rig.keeper.budget.value(), None, "the cache's is nobody's choice until he makes it");
    assert_eq!(rig.work.set_budget(&json!(500i64 << 30)).unwrap()["budgetBytes"], 500i64 << 30);
    assert_eq!(rig.work.budget.value(), Some(500 << 30));
    assert_eq!(rig.keeper.budget.value(), None, "each shelf keeps its own");
    assert!(rig.work.set_budget(&json!(1)).is_err(), "less than a gibibyte keeps no model");
    assert_eq!(rig.work.set_budget(&Value::Null).unwrap()["budgetBytes"], 300i64 << 30, "back to the owner's 300 GB");
    assert_eq!(rig.work.budget.chosen(), None);
    assert_eq!(rig.state.get("workBudgetBytes"), None);
}

#[test]
fn strata_s_models_stay_after_their_start_and_only_its_limit_takes_the_oldest() {
    let rig = Rig::new("work-keeps");
    work_of(&rig, "ssd");
    rig.work.set_budget(&json!(2i64 << 30)).unwrap();
    let gib = 1u64 << 30;
    // A start names its files before they come, as a start does (Cells::asks), and the trim at its end sees them.
    rig.work.uses.begin("c22009", &[A.to_string()]);
    let (a, made_a) = (copy_on(&rig.work_models, A, gib), made_on(&rig.work_models, "c22009", 3));
    rig.work.commit("c22009");
    rig.work.uses.begin("c22010", &[B.to_string()]);
    let b = copy_on(&rig.work_models, B, gib / 2);
    rig.work.commit("c22010");
    assert!(a.exists() && b.exists() && made_a.exists(), "1.5 GiB in a 2 GiB shelf: both stay after their cells stopped");
    rig.work.uses.begin("c22011", &[C.to_string()]);
    let c = copy_on(&rig.work_models, C, gib);
    rig.work.commit("c22011");
    assert!(!a.exists() && !made_a.exists(), "the oldest went, and what was made from it");
    assert!(b.exists() && c.exists());
    assert_eq!(rig.models.downloaded.paths(), Vec::<PathBuf>::new(), "the cache's record never heard of them");
}

#[test]
fn each_shelf_keeps_its_own_log_and_a_strata_start_takes_no_place_from_the_cache_s_last_model() {
    let rig = Rig::new("work-log");
    work_of(&rig, "ssd");
    rig.keeper.uses.begin("c22001", &[A.to_string()]);
    let a = rig.ours(A, &[b'a'; 10]);
    rig.keeper.commit("c22001");
    rig.work.uses.begin("c22009", &[B.to_string()]);
    let b = copy_on(&rig.work_models, B, 20);
    rig.work.commit("c22009");
    rig.keeper.trim();
    assert!(a.exists(), "the cache keeps its last model: Strata's start is not one of its starts");
    assert!(b.exists());
    assert_eq!(rig.keeper.uses.newest(1)[0]["files"], json!([A]), "each shelf hears of its own starts only");
    assert_eq!(rig.work.uses.newest(1)[0]["files"], json!([B]));
}

#[test]
fn a_copy_that_would_pass_strata_s_limit_makes_room_from_the_oldest_and_one_bigger_than_the_limit_is_refused() {
    let rig = Rig::new("work-room");
    let work = work_of(&rig, "ssd");
    rig.work.set_budget(&json!(2i64 << 30)).unwrap();
    let gib = 1u64 << 30;
    let (a, b) = (copy_on(&rig.work_models, A, gib), copy_on(&rig.work_models, B, gib / 2));
    for (cell, file) in [("c1", A), ("c2", B)] {
        rig.work.uses.begin(cell, &[file.to_string()]);
    }
    // The disk is the test's: a roomy one leaves the limit alone to refuse, whatever disk the test runs on.
    let roomy = || Some(1u64 << 50);
    assert_eq!(rig.work.room_until(gib / 2, 0, &roomy), Ok(()), "2 GiB with it: it fits as they are");
    assert!(a.exists() && b.exists());
    assert_eq!(rig.work.room_until(gib, 0, &roomy), Ok(()));
    assert!(!a.exists() && b.exists(), "the oldest went, and only as much as the new one needs");
    rig.cells.live.lock().unwrap().insert("c2".to_string());
    let short = rig.work.room_until(gib * 2, 0, &roomy).unwrap_err();
    assert_eq!(short, room::Short::Budget { budget: 2 * gib, held: gib / 2 }, "the copy a running cell reads stays");
    let words = rig.work.make_room(gib * 3, "big.gguf", &roomy).unwrap_err();
    assert!(
        words.contains("no room for big.gguf: it takes 3.0 GB, more than the 2.0 GB the folder for Strata's files may keep"),
        "{words}"
    );
    assert!(words.contains("Nothing was copied. Raise its limit"), "{words}");
    let words = rig.work.make_room(gib * 2, "m.gguf", &roomy).unwrap_err();
    assert!(words.contains("may keep 2.0 GB, 0.5 GB of which are models a running cell uses"), "{words}");
    // Within the limit, and short on the disk: 0.5 GB and the 2 GB the machine keeps beside a copy do not go into 1 GB.
    assert_eq!(
        rig.work.make_room(gib / 2, "s.gguf", &|| Some(gib)),
        Err(format!(
            "no room for s.gguf: it takes 0.5 GB and {} has 1.0 GB free, with every copy no cell is using gone. Nothing was copied. {}",
            work.display(),
            Shelf::WORK.when_full
        )),
        "the disk refuses in its own words"
    );
    assert!(b.exists());
}

#[test]
fn strata_s_shelf_copies_its_model_with_the_cache_off_and_never_reads_it_where_the_controller_has_it() {
    let rig = Rig::new("work-copies");
    let library = rig.folder.path.join("library");
    fs::create_dir_all(library.join("org/a/q4")).unwrap();
    fs::write(library.join(A), b"GGUF").unwrap();
    rig.models.off.set(true, Some(&library));
    rig.models.off.choose(true);
    let work = work_of(&rig, "ssd");
    let controller = controller_of(&[(A, b"GGUF")]);
    let rig = rig.with_controller(&controller);
    let hint = Some(json!({"path": library.join(A).to_string_lossy(), "size": 4}));
    assert_eq!(
        rig.models.ensure(A, &Fetch { hint: hint.clone(), ..fetch() }).unwrap(),
        library.join(A),
        "the cache is off: read there"
    );
    let copy = rig.work_models.ensure(A, &Fetch { hint, ..fetch() }).unwrap();
    assert_eq!(copy, work.join(A), "Strata's shelf brings it to its fast disk");
    assert_eq!(fs::read(&copy).unwrap(), b"GGUF");
    assert!(rig.work_models.downloaded.has(&copy) && !rig.models.downloaded.has(&copy));
}

/// Waits for the move under way to end, as the board would.
fn moved(rig: &Rig) {
    for _ in 0..1000 {
        if !rig.models.relocation.is_moving() {
            return;
        }
        std::thread::sleep(std::time::Duration::from_millis(10));
    }
    panic!("the move did not end");
}

#[test]
fn a_cache_that_moves_takes_the_scout_s_files_and_leaves_the_others() {
    let rig = Rig::new("move-carry");
    rig.ours(A, &[b'a'; 30]);
    rig.put(FOREIGN, b"theirs");
    made(&rig, "c22001", 5);
    let hdd = rig.folder.path.join("hdd/models");
    let said = rig.keeper.move_to(&json!(hdd.to_string_lossy()), &json!("move")).unwrap();
    assert_eq!(said["moving"], true);
    moved(&rig);
    assert_eq!(rig.models.cache_dir(), hdd);
    assert_eq!(fs::read(hdd.join(A)).unwrap(), vec![b'a'; 30]);
    assert!(hdd.join(".cells/c22001/pack.bin").exists(), "what a stopped cell made goes with the cache it lies in");
    assert!(rig.models.downloaded.has(&hdd.join(A)), "the record went too, and names the file where it is now");
    assert!(!rig.cache.join(A).exists() && !rig.cache.join(RECORD).exists() && !rig.cache.join(".cells").exists());
    assert!(rig.cache.join(FOREIGN).exists(), "a file this scout did not download stays where it was");
    assert_eq!(rig.keeper.facts().get("moving"), None);
}

#[test]
fn a_cache_removed_goes_back_to_its_own_folder_and_its_files_go() {
    let rig = Rig::new("move-back");
    let hdd = rig.folder.path.join("hdd");
    rig.keeper.move_to(&json!(hdd.to_string_lossy()), &json!("delete")).unwrap();
    let file = hdd.join(A);
    fs::create_dir_all(file.parent().unwrap()).unwrap();
    fs::write(&file, [b'a'; 10]).unwrap();
    rig.models.downloaded.add(&file);
    let back = rig.keeper.move_to(&json!(""), &json!("delete")).unwrap();
    assert_eq!(back["freedBytes"], 10);
    assert_eq!(rig.models.cache_dir(), rig.cache, "the folder the config names, as before anything was chosen");
    assert!(!hdd.join(A).exists());
    assert_eq!(rig.keeper.facts()["dirChosen"], false);
}

#[test]
fn a_move_onto_a_file_of_the_same_name_or_by_a_word_it_does_not_know_is_refused_before_anything_is_written() {
    let rig = Rig::new("move-taken");
    rig.ours(A, &[b'a'; 10]);
    let hdd = rig.folder.path.join("hdd");
    fs::create_dir_all(hdd.join("org/a/q4")).unwrap();
    fs::write(hdd.join(A), b"the operator's").unwrap();
    let refused = rig.keeper.move_to(&json!(hdd.to_string_lossy()), &json!("move")).unwrap_err();
    assert_eq!(refused.status, 409);
    assert!(refused.message.contains("already holds"), "{}", refused.message);
    assert_eq!(fs::read(hdd.join(A)).unwrap(), b"the operator's");
    assert_eq!(rig.models.cache_dir(), rig.cache);
    assert!(!rig.models.relocation.is_moving());
    let unknown = rig.keeper.move_to(&json!(hdd.to_string_lossy()), &json!("moov")).unwrap_err();
    assert!(unknown.message.contains("how must be"), "{}", unknown.message);
}

#[test]
fn a_move_the_new_folder_s_disk_cannot_take_is_refused_before_anything_is_written() {
    let rig = Rig::new("move-no-room");
    let copy = rig.ours_of(A, 1 << 29);
    let hdd = rig.folder.path.join("hdd");
    // 0.5 GB fits in 2 GB, the 2 GB the machine keeps beside it does not; the cache's own disk has as much as ever: the move asks the disk it goes to.
    rig.disks.has(&hdd, Some(2 << 30));
    let answer = rig.keeper.move_to(&json!(hdd.to_string_lossy()), &json!("move"));
    assert_eq!(
        answer.map_err(|refused| (refused.status, refused.message)),
        Err((409, format!("{} has 2.0 GB free, and the move needs 0.5 GB with 2.0 GB to spare", hdd.display()))),
        "the disk it goes to refuses it, in its words"
    );
    assert!(copy.exists() && !hdd.join(A).exists(), "nothing was written");
    assert_eq!(rig.models.cache_dir(), rig.cache, "the setting stays");
    assert!(!rig.models.relocation.is_moving());
}

#[test]
fn a_move_that_fails_on_the_way_takes_its_copies_back_and_says_why() {
    let rig = Rig::new("move-fails");
    let (from, to) = (rig.folder.path.join("from"), rig.folder.path.join("to"));
    fs::create_dir_all(from.join("x")).unwrap();
    fs::write(from.join("x/one.bin"), b"1").unwrap();
    let files =
        relocate::FileMove { from: from.clone(), to: to.clone(), names: vec!["x/one.bin".to_string(), "x/two.bin".to_string()] };
    let switched = Arc::new(Mutex::new(false));
    let flag = Arc::clone(&switched);
    files
        .start(&Shelf::CACHE, &rig.models.relocation, 0, rig.disks.as_ref(), Box::new(move || *flag.lock().unwrap() = true))
        .unwrap();
    moved(&rig);
    assert!(!*switched.lock().unwrap(), "the setting stays");
    assert!(from.join("x/one.bin").exists(), "the old file stays");
    assert!(!to.join("x").exists(), "the copies went, and the folder they made");
    let error = rig.keeper.facts()["moveError"].as_str().unwrap().to_string();
    assert!(error.contains("x/two.bin"), "{error}");
}

#[test]
fn the_folder_for_strata_s_files_moves_with_its_models_and_what_its_cells_made() {
    let rig = Rig::new("work-carry");
    let first = work_of(&rig, "hdd1");
    made_on(&rig.work_models, "c22009", 50);
    copy_on(&rig.work_models, A, 30);
    let second = rig.folder.path.join("hdd2");
    let said = rig.work.set_work(&json!(second.to_string_lossy()), &json!("move")).unwrap();
    assert_eq!(
        (&said["moving"], &said["totalBytes"]),
        (&json!(true), &json!(80 + fs::metadata(first.join(RECORD)).unwrap().len()))
    );
    moved(&rig);
    assert_eq!(fs::read(second.join(".cells/c22009/pack.bin")).unwrap().len(), 50);
    assert_eq!(fs::metadata(second.join(A)).unwrap().len(), 30, "the copy went with it");
    assert!(rig.work_models.downloaded.has(&second.join(A)), "and its record, naming it where it is now");
    assert!(!first.join(".cells").exists() && !first.join(A).exists(), "the old folder keeps nothing of the scout's");
    assert!(first.exists(), "the folder the operator named stays");
    assert_eq!(rig.work_models.cache_dir(), second);
    assert_eq!(rig.keeper.facts().get("moving"), None);
}
