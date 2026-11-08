//! The cells of this machine: each one by its own name, on the port its run leased, the table of them, what they look like from outside, and what outlives a scout's restart.

pub mod autostart;
pub mod door;
pub mod lease;
pub mod ledger;
pub mod logs;
pub mod migration;
pub mod probe;
pub mod reconcile;
pub mod records;
pub mod saved_start;
mod stopping;
mod survivors;
pub mod suspect;
pub mod table;
mod view;
pub mod watchdog;

use crate::commands::Commands;
use crate::config::ScoutConfig;
use crate::errors::{AppError, PyRepr};
use crate::http_client::HttpClient;
use crate::machine::Machine;
use crate::models::files::SplitGguf;
use crate::models::keeper::CacheKeeper;
use crate::models::{FreeSpace, ModelFetcher, Shelf, ShelfParts};
use crate::paths::ScoutPaths;
use crate::process::{CellLog, HostProcesses, LogPatterns, MemoryScope, ProcessParts};
use crate::runtimes::prism::PrismRuntime;
use crate::starts::StartRequest;
use crate::state::ScoutState;
use ledger::MemoryFigures;
use logs::CellLogs;
use os::clock::Clock;
use probe::{HttpServerAsk, ServerProbe};
use records::CellRecords;
use rules::{CellId, Coerce};
use saved_start::SavedStarts;
use serde_json::{Map, Value, json};
use std::path::PathBuf;
use std::sync::Arc;
use table::{Cell, CellTable};

/// What the cells are made of.
pub struct CellsParts {
    /// The machine.
    pub machine: Arc<Machine>,
    /// The settings.
    pub config: Arc<ScoutConfig>,
    /// The memory.
    pub state: Arc<ScoutState>,
    /// How a command runs.
    pub commands: Arc<dyn Commands>,
    /// How the scout asks over HTTP.
    pub http: Arc<HttpClient>,
    /// The clocks.
    pub clock: Arc<dyn Clock>,
    /// Where things lie.
    pub paths: Arc<ScoutPaths>,
    /// How a log is read.
    pub patterns: Arc<LogPatterns>,
    /// The rule of split files.
    pub splits: Arc<SplitGguf>,
    /// What the disks have free, under the shelves the models are copied to: the machine's own, or a test's word.
    pub disks: Arc<dyn FreeSpace>,
}

/// The cells by their names, and how each looks from outside.
pub struct Cells {
    /// The table.
    pub table: Arc<CellTable>,
    /// The machine.
    pub machine: Arc<Machine>,
    /// The settings.
    pub config: Arc<ScoutConfig>,
    /// What servers say of themselves.
    pub probe: ServerProbe,
    /// What outlives a restart.
    pub records: CellRecords,
    /// What the host says of its processes.
    pub processes: HostProcesses,
    /// The PrismML runtime.
    pub prism: PrismRuntime,
    /// The model cache.
    pub models: Arc<ModelFetcher>,
    /// How much the cache keeps.
    pub keeper: Arc<CacheKeeper>,
    /// The folder for Strata's files: the copies of the cells that need a fast disk (shelf.rs).
    pub work_models: Arc<ModelFetcher>,
    /// How much it keeps.
    pub work_keeper: Arc<CacheKeeper>,
    /// How a command runs.
    pub commands: Arc<dyn Commands>,
    /// How the scout asks over HTTP.
    pub http: Arc<HttpClient>,
    /// The clocks.
    pub clock: Arc<dyn Clock>,
    /// Where things lie.
    pub paths: Arc<ScoutPaths>,
    /// Their logs.
    pub logs: CellLogs,
    /// What a cell that starts by itself starts with.
    pub saved: SavedStarts,
    patterns: Arc<LogPatterns>,
}

impl Cells {
    /// The cells of this machine.
    pub fn new(parts: CellsParts) -> Self {
        let CellsParts { machine, config, state, commands, http, clock, paths, patterns, splits, disks } = parts;
        let scope = Arc::new(MemoryScope::new(Arc::clone(&commands), cfg!(target_os = "linux")));
        let total_memory_mib = MemoryFigures::read(&paths.meminfo).total;
        let home = state.folder().to_path_buf();
        let process_parts = ProcessParts {
            clock: Arc::clone(&clock),
            scope,
            patterns: Arc::clone(&patterns),
            total_memory_mib,
            home: home.display().to_string(),
        };
        let table = Arc::new(CellTable::new(process_parts, Arc::clone(&splits), Arc::clone(&clock)));
        // The model files are the cells': downloads report into a cell's startup record, and a purge keeps what a running cell holds.
        let reporting = Arc::clone(&table);
        let report: crate::models::Progress = Arc::new(move |cell, fields| {
            reporting.report(cell, fields);
        });
        let parts = ShelfParts::new(
            Arc::clone(&config),
            report,
            &state,
            Arc::clone(&clock),
            Arc::clone(&http),
            Arc::clone(&splits),
            disks,
        );
        let shelf = |row: &'static Shelf| {
            let models = Arc::new(ModelFetcher::new(&parts, row));
            let cells = Arc::clone(&table) as Arc<dyn crate::models::CellsInUse>;
            let keeper = Arc::new(CacheKeeper::new(&state, Arc::clone(&models), cells, Arc::clone(&splits), Arc::clone(&clock)));
            let room = Arc::downgrade(&keeper);
            models.room_comes_from(Arc::new(move |bytes, label, free| {
                room.upgrade().map_or(Ok(()), |keeper| keeper.make_room(bytes, label, free))
            }));
            (models, keeper)
        };
        let (models, keeper) = shelf(&Shelf::CACHE);
        let (work_models, work_keeper) = shelf(&Shelf::WORK);
        Self {
            logs: CellLogs::of_state(&state, Arc::clone(&clock)),
            saved: SavedStarts::new(Arc::clone(&config), Arc::clone(&http)),
            probe: ServerProbe::new(Arc::new(HttpServerAsk { http: Arc::clone(&http) }), Arc::clone(&clock)),
            records: CellRecords::new(state, Arc::clone(&clock)),
            processes: HostProcesses::new(paths.proc_root.clone(), Arc::clone(&commands)).of_scout(&home),
            prism: PrismRuntime::new(Arc::clone(&config), Arc::clone(&commands), Arc::clone(&http)),
            table,
            machine,
            config,
            models,
            keeper,
            work_models,
            work_keeper,
            commands,
            http,
            clock,
            paths,
            patterns,
        }
    }

    /// The logs' pass: what is too old goes, and what lies in the cache's folder comes over; a running cell's own log stays where it is written.
    pub fn tidy_logs(&self) {
        use crate::models::CellsInUse;
        self.logs.pass(&self.models.cache_dir(), &self.table.live_cells());
    }

    /// A log of this path.
    pub fn log_of(&self, path: Option<PathBuf>) -> CellLog {
        CellLog::new(path, Arc::clone(&self.patterns))
    }

    /// Where the cell `id` writes: its process's log while this scout holds the process, the log its record names after a restart, else a log of its name in the logs' folder or the model cache. A log
    /// of nothing when none of them is there. Asked without making an empty cell of a name nobody started.
    pub fn log_file(&self, id: &str) -> CellLog {
        if let Some(log) = self.table.find(id).map(|cell| cell.process.log()).filter(|log| log.path().is_some()) {
            return log;
        }
        let record = self.records.get(id);
        let recorded = Coerce::truthy(record.get("log")).then(|| PathBuf::from(Coerce::text(record.get("log"))));
        // A log the record names may have come to the logs' folder since.
        let found = recorded.filter(|path| path.is_file()).or_else(|| self.logs.find(id, &self.models.cache_dir()));
        self.log_of(found)
    }

    /// What the cell `cell` wrote, the board's window: the last lines of a run, the newest when `run` names none, and the runs there are to read, newest first. `{ok: false, error}` for a word that is
    /// no cell's name or a cell with no log here, and for a name that is not one of its runs.
    pub fn log(&self, cell: Option<&str>, lines: Option<&str>, run: &str) -> Value {
        let Some(id) = cell.and_then(|said| CellId::read(&json!(Coerce::strip(said)))) else {
            return json!({"ok": false, "error": "cell must be a cell's name"});
        };
        let log = self.log_file(&id);
        let runs = log.runs();
        let Some(newest) = runs.first() else {
            return json!({"ok": false, "error": format!("no log of the cell {id} here")});
        };
        let name = if run.is_empty() { Coerce::text(newest.get("name")) } else { run.to_string() };
        let Some(chosen) = log.run(&name) else {
            return json!({"ok": false, "error": format!("{} is not a log of the cell {id}", PyRepr::of(&name))});
        };
        json!({"ok": true, "cellId": id, "run": name, "lines": chosen.lines(lines), "runs": runs})
    }

    /// Starts a cell as the controller asks: a llama cell or a command cell, whichever the payload names. A start by hand clears the cell's crash count: it counts since the operator last touched it.
    pub fn start(cells: &Arc<Self>, payload: Map<String, Value>) -> Result<Value, AppError> {
        // A move of the cache or of the work folder copies what a start would read or write.
        cells.models.relocation.refuse_while_moving()?;
        let start = StartRequest::of(Arc::clone(cells), payload.clone());
        let id = start.cell_id().ok();
        // A refusal leaves no slot: only a cell that exists is touched.
        if let Some(cell) = id.as_deref().and_then(|id| cells.table.find(id)) {
            cell.facts().crash = None;
        }
        let result = start.run();
        let started = result.as_ref().is_ok_and(|said| said.get("ok") == Some(&Value::Bool(true)));
        if let Some(cell) = id.as_deref().filter(|_| started).and_then(|id| cells.table.find(id)) {
            cell.facts().request = Some(payload);
        }
        result
    }

    /// On-demand cache purge. Keeps the running cells' files, so that a live server isn't broken: which files those are is the cells' to say, the fetcher only deletes.
    pub fn purge_models_safely(&self) -> Value {
        self.keeper.clear_unheld()
    }

    /// A start of `cell` asks a shelf for `files`: the keeper's log hears of it before the first byte is copied (a trim that another start's end triggers must find them wanted, whole or half copied),
    /// and the cell keeps the list, what its stop lets go of.
    pub fn asks(&self, cell: &Cell, files: &[String], keeper: &CacheKeeper) {
        let names: Vec<String> =
            files.iter().map(|file| Coerce::strip(file).to_string()).filter(|name| !name.is_empty()).collect();
        cell.facts().asked.clone_from(&names);
        keeper.uses.begin(&cell.id, &names);
    }

    /// The shelf a start keeps its models on: the folder for Strata's files when the start asks for it, the model cache otherwise.
    pub fn shelf(&self, work: bool) -> (&Arc<ModelFetcher>, &Arc<CacheKeeper>) {
        if work { (&self.work_models, &self.work_keeper) } else { (&self.models, &self.keeper) }
    }

    /// What the board reads of the machine's copies: the model cache's setting and figures, and the folder for Strata's files as `work`.
    pub fn cache_facts(&self) -> Map<String, Value> {
        let mut out = self.keeper.facts();
        out.insert("work".to_string(), self.work_keeper.work_facts());
        out
    }
}
