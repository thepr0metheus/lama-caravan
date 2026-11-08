//! A llama cell's start follows the command the controller sent: a projector or a draft the command does not load is not asked of the cache keeper, not fetched,
//! not counted in the start's weight and not reported as the cell's. The rule by values first; then whole starts on a machine of the test's own (hand-made disks,
//! no tools, a controller that serves the files, and a server binary that is not there), so that each start ends where its process would begin, with all it asked,
//! fetched, counted and wrote down.

#![allow(clippy::unwrap_used, clippy::panic, clippy::indexing_slicing, reason = "a test may stop where it found something wrong")]

use super::Fetched;
use super::sent_args::SentArgs;
use crate::cells::{Cells, CellsParts};
use crate::commands::Commands;
use crate::config::ScoutConfig;
use crate::http_client::HttpClient;
use crate::machine::Machine;
use crate::models::files::SplitGguf;
use crate::paths::ScoutPaths;
use crate::process::LogPatterns;
use crate::state::ScoutState;
use crate::tests::{HandClock, HandDisks, NoTools, StandIn, TestFolder};
use os::clock::Clock;
use serde_json::{Map, Value, json};
use std::sync::Arc;
use std::time::Duration;

/// The cell the tests start, and the one port its range offers it: the lease has nothing else to choose.
const CELL: &str = "c22101";
const PORT: i64 = 22101;
const MODEL: &str = "m/q4/model-Q4.gguf";
const PROJECTOR: &str = "m/mmproj-model.gguf";
const DRAFT: &str = "m/mtp-model.gguf";
/// What each file weighs on the controller: no two sums of them are alike, so a start's weight says which files it counted.
const SIZES: [(&str, usize); 3] = [(MODEL, 1000), (PROJECTOR, 70), (DRAFT, 300)];

fn sent(args: &[&str]) -> SentArgs {
    SentArgs::of(json!({"args": args}).as_object().unwrap())
}

#[test]
fn a_file_is_wanted_exactly_where_the_command_has_its_placeholder() {
    let draft = || DRAFT.to_string();
    let loads = sent(&["--model", SentArgs::MODEL, "--model-draft", SentArgs::DRAFT]);
    assert_eq!(
        loads.wanted(SentArgs::DRAFT, draft()),
        DRAFT,
        "the draft's placeholder stands after --model-draft: the command reads the draft"
    );
    assert_eq!(
        loads.wanted(SentArgs::PROJECTOR, PROJECTOR.to_string()),
        "",
        "the projector's placeholder is not there: the command reads no projector"
    );
    let off = sent(&["--model", SentArgs::MODEL]);
    assert_eq!(
        off.wanted(SentArgs::DRAFT, draft()),
        "",
        "speculation switched off: the builder wrote no draft, so none is wanted"
    );
    let inside = sent(&["--model", SentArgs::MODEL, "--x", "{{SPEC_PATH}}.bak"]);
    assert_eq!(inside.wanted(SentArgs::DRAFT, draft()), "", "a placeholder inside a word is never replaced, so it loads nothing");
    let none = SentArgs::of(&Map::new());
    assert_eq!(none.wanted(SentArgs::DRAFT, draft()), "", "no args: nothing is loaded, and the launch refuses the start");
}

#[test]
fn the_paths_go_where_the_placeholders_stand() {
    let files = Fetched { model: "/c/m.gguf".to_string(), mmproj: "/c/p.gguf".to_string(), spec: "/c/d.gguf".to_string() };
    let args = sent(&["-m", SentArgs::MODEL, "--mmproj", SentArgs::PROJECTOR, "--model-draft", SentArgs::DRAFT, "--port", "1"]);
    assert_eq!(
        args.resolved(&files).unwrap(),
        ["-m", "/c/m.gguf", "--mmproj", "/c/p.gguf", "--model-draft", "/c/d.gguf", "--port", "1"],
        "each placeholder takes its own file's path here, and every other word stays as the controller wrote it"
    );
    let refused = SentArgs::of(&Map::new()).resolved(&files).unwrap_err().message;
    assert!(refused.contains("controller sent no args"), "a start with no args is refused, not built here: {refused}");
    assert!(sent(&[]).resolved(&files).is_err(), "nor is an empty list a command");
}

/// One machine of the test's own, with a controller that serves the three files.
struct StartRig {
    folder: TestFolder,
    controller: StandIn,
    cells: Arc<Cells>,
}

impl StartRig {
    fn new(name: &str) -> Self {
        let folder = TestFolder::new(&format!("llama-start-{name}"));
        let controller = StandIn::serving(|head| {
            let target = head.split_whitespace().nth(1).unwrap_or_default();
            let asked = target.split_once("path=").map_or("", |(_, path)| path);
            match SIZES.iter().find(|(file, _)| *file == asked) {
                Some((_, size)) => StandIn::answer("200 OK", &vec![b'x'; *size]),
                None => StandIn::answer("404 Not Found", b"nothing here"),
            }
        });
        let at = |rel: &str| folder.path.join(rel).to_string_lossy().into_owned();
        // The server binary is not there: the start ends where its process would begin.
        let said = json!({"modelsBasePath": at("cache"), "controllerUrl": controller.address(), "llamaServerBin": at("bin/llama-server")});
        std::fs::write(folder.path.join("config.json"), said.to_string()).unwrap();
        let config = Arc::new(ScoutConfig::load(&folder.path.join("config.json")).unwrap());
        let (commands, clock): (Arc<dyn Commands>, Arc<dyn Clock>) = (Arc::new(NoTools), HandClock::at(1000));
        let paths = ScoutPaths {
            root: folder.path.clone(),
            server_cells: folder.path.join("server-cells"),
            proc_root: folder.path.join("proc"),
            meminfo: folder.path.join("meminfo"),
            home: folder.path.clone(),
        };
        let cells = Cells::new(CellsParts {
            machine: Arc::new(Machine::new(Arc::clone(&config), Arc::clone(&commands), Arc::clone(&clock))),
            config,
            state: Arc::new(ScoutState::load(&folder.path.join("state.json"), 0)),
            commands,
            http: Arc::new(HttpClient::new()),
            clock,
            paths: Arc::new(paths),
            patterns: Arc::new(LogPatterns::new().unwrap()),
            splits: Arc::new(SplitGguf::new().unwrap()),
            disks: Arc::new(HandDisks::default()),
        });
        Self { folder, controller, cells: Arc::new(cells) }
    }

    /// Starts the cell with these args and this config, as the controller sends them, and waits for the start to end: at the binary that is not there, after all it does before. What the start said
    /// of itself on the way.
    fn start(&self, args: &[&str], config: Value) -> Value {
        let payload = json!({"cellId": CELL, "ports": {"base": PORT, "upper": PORT}, "modelPath": MODEL, "args": args, "config": config, "cacheModels": false});
        let taken = Cells::start(&self.cells, payload.as_object().unwrap().clone()).unwrap();
        assert_eq!(taken["ok"], true, "the start is taken: {taken}");
        for _ in 0..1000 {
            let said = Value::Object(self.cells.table.startup(CELL));
            if !matches!(said["phase"].as_str(), Some("resolving" | "downloading" | "loading")) {
                let error = said["error"].as_str().unwrap_or_default();
                assert!(
                    error.contains("binary not found"),
                    "the start went all the way to its server, so what it did on the way is all it does: {said}"
                );
                return said;
            }
            std::thread::sleep(Duration::from_millis(10));
        }
        panic!("the start did not end in 10 s: {:?}", self.cells.table.startup(CELL));
    }

    /// The files the start told the cache keeper it asks for, as the keeper's log has them.
    fn asked(&self) -> Vec<String> {
        let entries = self.cells.keeper.uses.entries();
        let entry = entries.iter().find(|entry| entry["cell"] == CELL).unwrap();
        entry["files"].as_array().unwrap().iter().map(|file| file.as_str().unwrap().to_string()).collect()
    }

    /// The files the controller was asked to send, in their order.
    fn fetched(&self) -> Vec<String> {
        self.controller.targets().iter().filter_map(|target| Some(target.split_once("path=")?.1.to_string())).collect()
    }

    /// What the cell wrote down beside itself: what it was started with (`runtime`) and its command (`cmd`).
    fn written(&self) -> Value {
        let path = self.folder.path.join("server-cells").join(CELL).join("cell.json");
        serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap()
    }

    /// Where the copy of `rel` lies here.
    fn copy_of(&self, rel: &str) -> String {
        self.folder.path.join("cache").join(rel).to_string_lossy().into_owned()
    }

    /// The word the command has after `flag`.
    fn after(written: &Value, flag: &str) -> Value {
        let words = written["cmd"].as_array().unwrap();
        let at = words.iter().position(|word| word == flag).unwrap();
        words[at + 1].clone()
    }
}

#[test]
fn a_draft_the_command_loads_is_asked_fetched_counted_and_reported() {
    let rig = StartRig::new("draft-loaded");
    let args = ["--model", SentArgs::MODEL, "--spec-type", "draft-mtp", "--model-draft", SentArgs::DRAFT];
    let ended = rig.start(&args, json!({"SPEC_TYPE": "draft-mtp", "SPEC_DRAFT_MODEL_FILE": DRAFT}));
    assert_eq!(
        rig.asked(),
        [MODEL, DRAFT],
        "the command loads the draft: the cache keeper must hold it for this start from its first byte, or another start's trim takes it half copied"
    );
    assert_eq!(
        rig.fetched(),
        [MODEL, DRAFT],
        "the command reads the draft from this machine's disk, so it is copied from the controller"
    );
    assert_eq!(
        ended["modelBytes"], 1300,
        "the server reads the model and the draft as it loads: the board counts its reading against both"
    );
    let written = rig.written();
    assert_eq!(
        written["runtime"]["specPath"],
        rig.copy_of(DRAFT),
        "the cell names the draft it reads: the purge spares it while the cell runs, and the board says the cell drafts"
    );
    assert_eq!(
        StartRig::after(&written, "--model-draft"),
        rig.copy_of(DRAFT),
        "the copy made is the file the command reads, not just a file on the disk"
    );
}

#[test]
fn a_draft_switched_off_is_neither_asked_nor_fetched_nor_counted_nor_reported() {
    let rig = StartRig::new("draft-off");
    // What the controller sends for a cell whose speculation is switched off: SPEC_TYPE "none" with the draft still named, and no --model-draft
    // (rust/crates/admin/src/fleet/start.rs, a_start_whose_speculation_is_switched_off_sends_no_draft).
    let ended = rig.start(&["--model", SentArgs::MODEL], json!({"SPEC_TYPE": "none", "SPEC_DRAFT_MODEL_FILE": DRAFT}));
    assert_eq!(
        rig.asked(),
        [MODEL],
        "a draft the command does not load is no file of this start: the cache keeper is not told to keep it"
    );
    assert_eq!(
        rig.fetched(),
        [MODEL],
        "nor is it copied: a big draft is gigabytes of disk and minutes of start for a file the cell never reads"
    );
    assert_eq!(
        ended["modelBytes"], 1000,
        "nor counted: the board would measure the cell's loading against a file it never reads, and the bar would stop short"
    );
    let runtime = &rig.written()["runtime"];
    assert_eq!(
        runtime["specPath"], "",
        "nor reported: the cell runs no draft, and a path here would spare a copy from the purge and say on the board that it drafts"
    );
    assert_eq!(
        runtime["specType"], "none",
        "the type stays the operator's word: speculation is off, and the board reads none with no path as no draft"
    );
}

#[test]
fn a_projector_the_command_loads_is_asked_fetched_counted_and_reported() {
    let rig = StartRig::new("projector-loaded");
    let ended = rig.start(&["--model", SentArgs::MODEL, "--mmproj", SentArgs::PROJECTOR], json!({"MMPROJ_FILE": PROJECTOR}));
    assert_eq!(
        rig.asked(),
        [MODEL, PROJECTOR],
        "the command loads the projector: the cache keeper must hold it for this start, as it holds the model"
    );
    assert_eq!(rig.fetched(), [MODEL, PROJECTOR], "the command reads the projector from this machine's disk, so it is copied");
    assert_eq!(ended["modelBytes"], 1070, "the server reads the model and the projector as it loads: the board counts both");
    let written = rig.written();
    assert_eq!(
        written["runtime"]["mmprojPath"],
        rig.copy_of(PROJECTOR),
        "the cell names the projector it reads: the purge spares it while the cell runs"
    );
    assert_eq!(
        StartRig::after(&written, "--mmproj"),
        rig.copy_of(PROJECTOR),
        "the copy made is the file the command reads, not just a file on the disk"
    );
}

#[test]
fn a_projector_the_command_does_not_load_is_left_alone() {
    let rig = StartRig::new("projector-unloaded");
    // No controller sends this today (its builder writes --mmproj whenever the config names a projector), and the rule is the draft's: the command decides.
    let ended = rig.start(&["--model", SentArgs::MODEL], json!({"MMPROJ_FILE": PROJECTOR}));
    assert_eq!(
        rig.asked(),
        [MODEL],
        "the command reads no projector: the config naming one makes it no file of this start, and the cache keeper is not told to keep it"
    );
    assert_eq!(rig.fetched(), [MODEL], "nor is it copied: bytes on the disk that the cell never reads");
    assert_eq!(ended["modelBytes"], 1000, "nor counted: the server reads the model alone as it loads");
    assert_eq!(
        rig.written()["runtime"]["mmprojPath"],
        "",
        "nor reported: a path here would spare the copy from the purge and say the cell sees pictures"
    );
}

#[test]
fn a_start_with_no_free_port_is_refused_and_its_cell_says_why() {
    let rig = StartRig::new("no-port");
    let other = rig.cells.table.at("c0a1b2c3e");
    rig.cells.table.hold(&other, Some(PORT));
    let payload = json!({"cellId": CELL, "ports": {"base": PORT, "upper": PORT}, "modelPath": MODEL, "args": ["--port", "{{PORT}}", "-m", SentArgs::MODEL], "config": {}, "cacheModels": false});
    let refused = Cells::start(&rig.cells, payload.as_object().unwrap().clone()).unwrap_err();
    assert_eq!(refused.status, 409, "{}", refused.message);
    assert!(refused.message.contains("no free port"), "{}", refused.message);
    let said = rig.cells.table.startup(CELL);
    assert_eq!(said["phase"], "error", "the cell says it did not start: {said:?}");
    assert!(said["error"].as_str().unwrap().contains("no free port"), "and why: {said:?}");
    assert_eq!(rig.cells.table.find(CELL).and_then(|cell| cell.port()), None, "negative: a refused start holds no port");
    assert_eq!(other.port(), Some(PORT), "negative: nor takes the other cell's");
}
