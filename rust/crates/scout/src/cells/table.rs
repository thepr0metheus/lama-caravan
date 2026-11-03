//! The cells of this machine by port. A cell comes into being the first time anything starts or asks about its port, and goes when it is stopped. Its identity is the cancellation token of a start: a
//! start that finds its cell replaced knows it was stopped while it worked. It is the part of the cells that asks nothing of the others, so that the cache can ask it what is in use.

use crate::cells::watchdog::CrashNote;
use crate::models::files::SplitGguf;
use crate::models::keeper::CellsInUse;
use crate::models::pace::CopyPace;
use crate::process::{CellProcess, ProcessParts};
use os::clock::Clock;
use rules::Coerce;
use serde_json::{Map, Value, json};
use std::collections::BTreeSet;
use std::sync::{Arc, Mutex, MutexGuard, PoisonError};

/// How fast a cell's run reads: the window of its bytes read, kept for one process. A new run of the cell starts the window again, and a count that went back (a child that left) does too.
#[derive(Debug, Default)]
pub struct RunPace {
    pid: i64,
    pace: CopyPace,
}

impl RunPace {
    /// The run's bytes read now; its pace over the last seconds, or `None` while not measured.
    pub fn read(&mut self, pid: i64, done: Option<i64>, now: f64) -> Option<i64> {
        let done = done?;
        if pid != self.pid {
            self.pid = pid;
            self.pace = CopyPace::default();
        }
        self.pace.add(done, now);
        self.pace.rate()
    }
}

/// What a cell knows of itself, behind its one lock.
#[derive(Debug)]
pub struct CellFacts {
    /// How its start is going.
    pub startup: Map<String, Value>,
    /// Whether its model files stay cached when it stops.
    pub cache_models: bool,
    /// The memory its start promised to keep resident, in MiB; 0 = none promised.
    pub ram_mib: i64,
    /// Crashes since it was last started by hand.
    pub crash: Option<CrashNote>,
    /// Whether THIS run's port has listened yet: `None` = not watched (the machine will not say what listens), `Some(false)` = watched and silent so far, `Some(true)` = it listened, the run got ready.
    pub listened: Option<bool>,
    /// What its model is called at the machine's entry, from the start that made it; "" for a cell no start of this scout made (its record keeps the name).
    pub name: String,
    /// The files its present start asked the cache for, as the controller named them: what its stop lets go of when it keeps no cache. Empty for a start that asked for none (a cell in an engine) and for
    /// a cell no start of this scout made: its stop lets go of nothing, and the keeper trims the cache in its time.
    pub asked: Vec<String>,
    /// How fast its run reads its model while it loads.
    pub reading: RunPace,
    /// The request its present start came with: what the settings saved since are held against.
    pub request: Option<Map<String, Value>>,
}

/// One cell on one port. A machine can hold several at once, a translator and a whisper cell, say; each keeps its own process, startup record, lock and flag.
pub struct Cell {
    /// Its port.
    pub port: i64,
    /// Its process.
    pub process: CellProcess,
    facts: Mutex<CellFacts>,
}

impl Cell {
    fn new(port: i64, parts: ProcessParts) -> Self {
        let mut startup = Map::new();
        startup.insert("phase".to_string(), json!("idle"));
        let facts = CellFacts {
            startup,
            cache_models: false,
            ram_mib: 0,
            crash: None,
            listened: None,
            name: String::new(),
            asked: Vec::new(),
            reading: RunPace::default(),
            request: None,
        };
        Self { port, process: CellProcess::new(parts), facts: Mutex::new(facts) }
    }

    /// What it knows of itself, under its lock.
    pub fn facts(&self) -> MutexGuard<'_, CellFacts> {
        self.facts.lock().unwrap_or_else(PoisonError::into_inner)
    }

    fn phase(&self) -> String {
        let facts = self.facts();
        if Coerce::truthy(facts.startup.get("phase")) { Coerce::text(facts.startup.get("phase")) } else { String::new() }
    }

    fn is_running(&self) -> bool {
        self.process.status().get("running") == Some(&Value::Bool(true))
    }
}

/// The table.
pub struct CellTable {
    by_port: Mutex<Vec<(i64, Arc<Cell>)>>,
    parts: ProcessParts,
    splits: Arc<SplitGguf>,
    clock: Arc<dyn Clock>,
}

impl CellTable {
    /// The phases of a start whose files are still coming, found, copied, read: the cache's folder does not move under them.
    const LOADING: [&'static str; 3] = ["resolving", "downloading", "loading"];
    /// The phases of a start that has asked the cache for its files and not let go of them.
    const STARTING: [&'static str; 4] = ["resolving", "downloading", "loading", "running"];

    /// An empty table.
    pub fn new(parts: ProcessParts, splits: Arc<SplitGguf>, clock: Arc<dyn Clock>) -> Self {
        Self { by_port: Mutex::new(Vec::new()), parts, splits, clock }
    }

    fn rows(&self) -> MutexGuard<'_, Vec<(i64, Arc<Cell>)>> {
        self.by_port.lock().unwrap_or_else(PoisonError::into_inner)
    }

    /// The cell on `port`, made on first use.
    pub fn at(&self, port: i64) -> Arc<Cell> {
        let mut rows = self.rows();
        if let Some((_, cell)) = rows.iter().find(|(other, _)| *other == port) {
            return Arc::clone(cell);
        }
        let cell = Arc::new(Cell::new(port, self.parts.clone()));
        rows.push((port, Arc::clone(&cell)));
        cell
    }

    /// The cell on `port` when there is one: asked this way, an empty cell is not made of a port nobody started.
    pub fn find(&self, port: i64) -> Option<Arc<Cell>> {
        self.rows().iter().find(|(other, _)| *other == port).map(|(_, cell)| Arc::clone(cell))
    }

    /// (port, cell) pairs in the order the cells came: a copy.
    pub fn all(&self) -> Vec<(i64, Arc<Cell>)> {
        self.rows().clone()
    }

    /// The cell leaves the table.
    pub fn drop_cell(&self, port: i64) {
        self.rows().retain(|(other, _)| *other != port);
    }

    /// True while `cell` is still THE cell of this port. A stop replaces or removes the cell object, so identity is the cheapest cancellation token for a start's worker: no flags, no epochs.
    pub fn holds(&self, port: i64, cell: &Arc<Cell>) -> bool {
        self.find(port).is_some_and(|current| Arc::ptr_eq(&current, cell))
    }

    /// A start says how it is going: fields merged into the record of the cell that is there. True when they were kept. A report never makes a cell: a start that was stopped goes on copying its model to the
    /// end of the file, and each report of that copy used to make the stopped port's cell again: a start under way for good with nothing behind it (2026-10-19). What reports is the start that holds the
    /// cell; the one that does not is late, and its words are dropped.
    pub fn report(&self, port: i64, fields: Map<String, Value>) -> bool {
        let Some(cell) = self.find(port) else {
            return false;
        };
        cell.facts().startup.extend(fields);
        true
    }

    /// A report given as a JSON object.
    pub fn say(&self, port: i64, fields: &Value) -> bool {
        // absent-ok: only this program's own literals come here, and they are objects.
        self.report(port, fields.as_object().cloned().unwrap_or_default())
    }

    /// A copy of the cell's startup record.
    pub fn startup(&self, port: i64) -> Map<String, Value> {
        self.at(port).facts().startup.clone()
    }

    /// Whether a cell of this scout runs on `port`, or its start is under way there: what it holds, as far as the scout knows.
    pub fn tracking(&self, port: i64) -> bool {
        let Some(cell) = self.find(port) else {
            return false;
        };
        cell.is_running() || Self::LOADING.contains(&cell.phase().as_str())
    }

    /// The clock its cells read.
    pub fn now(&self) -> f64 {
        self.clock.epoch()
    }

    /// A monotonic reading, for the paces.
    pub fn monotonic(&self) -> f64 {
        self.clock.monotonic()
    }

    /// The rule of split files.
    pub fn splits(&self) -> &SplitGguf {
        &self.splits
    }
}

impl CellsInUse for CellTable {
    fn held_files(&self) -> Vec<String> {
        let mut keep = Vec::new();
        for (_, cell) in self.all() {
            for path in cell.process.named_files() {
                keep.extend(self.splits.parts(&path));
            }
        }
        keep
    }

    fn live_ports(&self) -> BTreeSet<i64> {
        self.all()
            .iter()
            .filter(|(_, cell)| Self::STARTING.contains(&cell.phase().as_str()) || cell.is_running())
            .map(|(port, _)| *port)
            .collect()
    }

    fn loading_ports(&self) -> BTreeSet<i64> {
        self.all().iter().filter(|(_, cell)| Self::LOADING.contains(&cell.phase().as_str())).map(|(port, _)| *port).collect()
    }
}
