//! The cells of this machine by their own names. A cell comes into being the first time anything starts or asks about it, and goes when it is stopped. Its identity is the cancellation token of a
//! start: a start that finds its cell replaced knows it was stopped while it worked. It is the part of the cells that asks nothing of the others, so that the cache can ask it what is in use. The port a
//! cell runs on is leased here, under the table's lock, so that two starts never take one (`PortLease`).

use crate::cells::lease::PortLease;
use crate::cells::watchdog::CrashNote;
use crate::errors::{AppError, PyRepr};
use crate::models::files::SplitGguf;
use crate::models::keeper::CellsInUse;
use crate::models::pace::CopyPace;
use crate::process::{CellProcess, ProcessParts};
use os::clock::Clock;
use rules::{CellId, Coerce};
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
    /// Whether THIS run's port has listened yet: `None` = not watched (the machine will not say what listens, or the cell holds no port), `Some(false)` = watched and silent so far, `Some(true)` = it
    /// listened, the run got ready.
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

/// One cell. A machine can hold several at once, a translator and a whisper cell, say; each keeps its own process, startup record, lock and flag.
pub struct Cell {
    /// Its own name: what the board, the controller and the mark of its processes know it by.
    pub id: String,
    /// Its process.
    pub process: CellProcess,
    facts: Mutex<CellFacts>,
    /// The port its run holds: leased by its start and given back when the cell stops or its start fails, set by nothing but the table.
    port: Mutex<Option<i64>>,
}

impl Cell {
    fn new(id: &str, parts: ProcessParts) -> Self {
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
        let process = CellProcess::new(parts, id);
        Self { id: id.to_string(), process, facts: Mutex::new(facts), port: Mutex::new(None) }
    }

    /// What it knows of itself, under its lock.
    pub fn facts(&self) -> MutexGuard<'_, CellFacts> {
        self.facts.lock().unwrap_or_else(PoisonError::into_inner)
    }

    /// The port it holds now; `None` when it holds none: no start of this scout leased it one, its start failed, or it was found again with no word of its port.
    pub fn port(&self) -> Option<i64> {
        *self.port.lock().unwrap_or_else(PoisonError::into_inner)
    }

    fn set_port(&self, port: Option<i64>) {
        *self.port.lock().unwrap_or_else(PoisonError::into_inner) = port;
    }

    /// How words to the operator name the cell of `id`: by its port while it holds one, as the board shows a cell that runs (`:22003`), by its name otherwise.
    pub fn words(id: &str, port: Option<i64>) -> String {
        port.map_or_else(|| id.to_string(), |port| format!(":{port}"))
    }

    /// The words for this cell.
    pub fn called(&self) -> String {
        Self::words(&self.id, self.port())
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
    by_id: Mutex<Vec<(String, Arc<Cell>)>>,
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
        Self { by_id: Mutex::new(Vec::new()), parts, splits, clock }
    }

    /// The cell a request names in `cellId`: its name, or the refusal of a request that names none, or names it in no cell's words.
    pub fn named(said: Option<&Value>) -> Result<String, AppError> {
        let said = said.filter(|said| !said.is_null()).ok_or_else(|| AppError::new("cellId is required"))?;
        CellId::read(said).ok_or_else(|| AppError::new(format!("cellId is not a cell's name: {}", PyRepr::of_value(said))))
    }

    fn rows(&self) -> MutexGuard<'_, Vec<(String, Arc<Cell>)>> {
        self.by_id.lock().unwrap_or_else(PoisonError::into_inner)
    }

    /// The cell `id`, made on first use.
    pub fn at(&self, id: &str) -> Arc<Cell> {
        let mut rows = self.rows();
        if let Some((_, cell)) = rows.iter().find(|(other, _)| other == id) {
            return Arc::clone(cell);
        }
        let cell = Arc::new(Cell::new(id, self.parts.clone()));
        rows.push((id.to_string(), Arc::clone(&cell)));
        cell
    }

    /// The cell `id` when there is one: asked this way, an empty cell is not made of a name nobody started.
    pub fn find(&self, id: &str) -> Option<Arc<Cell>> {
        self.rows().iter().find(|(other, _)| other == id).map(|(_, cell)| Arc::clone(cell))
    }

    /// (id, cell) pairs in the order the cells came: a copy.
    pub fn all(&self) -> Vec<(String, Arc<Cell>)> {
        self.rows().clone()
    }

    /// The cell leaves the table, and with it the port it held.
    pub fn drop_cell(&self, id: &str) {
        self.rows().retain(|(other, _)| other != id);
    }

    /// True while `cell` is still THE cell of this name. A stop replaces or removes the cell object, so identity is the cheapest cancellation token for a start's worker: no flags, no epochs.
    pub fn holds(&self, id: &str, cell: &Arc<Cell>) -> bool {
        self.find(id).is_some_and(|current| Arc::ptr_eq(&current, cell))
    }

    /// A port for `cell`'s run, from `lease`'s range: the lowest no other cell of the table holds, no other cell's record names (`recorded`) and nothing listens on. Chosen and taken under the
    /// table's lock, so that two starts at once never take one port; a port the cell held before is no other cell's, and may be its again. The refusal's words when every port is taken.
    pub fn lease(
        &self,
        cell: &Arc<Cell>,
        lease: &PortLease,
        recorded: &BTreeSet<i64>,
        listening: Option<&BTreeSet<i64>>,
    ) -> Result<i64, String> {
        let rows = self.rows();
        let held: BTreeSet<i64> = rows.iter().filter(|(id, _)| *id != cell.id).filter_map(|(_, other)| other.port()).collect();
        let port = lease.pick(&held, recorded, listening)?;
        cell.set_port(Some(port));
        Ok(port)
    }

    /// `cell` holds `port` without a lease: the port of a process found again, as its record or its own mark says it. Under the table's lock, as a lease is.
    pub fn hold(&self, cell: &Cell, port: Option<i64>) {
        let _rows = self.rows();
        cell.set_port(port);
    }

    /// `cell` gives its port back: its start failed, and no run of it holds the port.
    pub fn release(&self, cell: &Cell) {
        cell.set_port(None);
    }

    /// The ports the table's cells hold.
    pub fn ports(&self) -> BTreeSet<i64> {
        self.rows().iter().filter_map(|(_, cell)| cell.port()).collect()
    }

    /// A start says how it is going: fields merged into the record of the cell that is there. True when they were kept. A report never makes a cell: a start that was stopped goes on copying its model to the
    /// end of the file, and each report of that copy used to make the stopped cell again: a start under way for good with nothing behind it (2026-10-19). What reports is the start that holds the
    /// cell; the one that does not is late, and its words are dropped.
    pub fn report(&self, id: &str, fields: Map<String, Value>) -> bool {
        let Some(cell) = self.find(id) else {
            return false;
        };
        cell.facts().startup.extend(fields);
        true
    }

    /// A report given as a JSON object.
    pub fn say(&self, id: &str, fields: &Value) -> bool {
        // absent-ok: only this program's own literals come here, and they are objects.
        self.report(id, fields.as_object().cloned().unwrap_or_default())
    }

    /// A copy of the cell's startup record.
    pub fn startup(&self, id: &str) -> Map<String, Value> {
        self.at(id).facts().startup.clone()
    }

    /// Whether a cell of this scout of this name runs, or its start is under way: what it holds, as far as the scout knows.
    pub fn tracking(&self, id: &str) -> bool {
        let Some(cell) = self.find(id) else {
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

    fn live_cells(&self) -> BTreeSet<String> {
        self.all()
            .into_iter()
            .filter(|(_, cell)| Self::STARTING.contains(&cell.phase().as_str()) || cell.is_running())
            .map(|(id, _)| id)
            .collect()
    }

    fn loading_cells(&self) -> BTreeSet<String> {
        self.all().into_iter().filter(|(_, cell)| Self::LOADING.contains(&cell.phase().as_str())).map(|(id, _)| id).collect()
    }

    fn called(&self, cells: &BTreeSet<String>) -> Vec<String> {
        cells.iter().map(|id| Cell::words(id, self.find(id).and_then(|cell| cell.port()))).collect()
    }
}

#[cfg(test)]
mod tests {
    #![allow(clippy::unwrap_used, reason = "a test may stop where it found something wrong")]

    use super::*;
    use crate::process::{LogPatterns, MemoryScope};
    use crate::tests::NoTools;
    use os::clock::SystemClock;

    fn table() -> Arc<CellTable> {
        let clock: Arc<dyn Clock> = Arc::new(SystemClock::new());
        let parts = ProcessParts {
            clock: Arc::clone(&clock),
            scope: Arc::new(MemoryScope::new(Arc::new(NoTools), false)),
            patterns: Arc::new(LogPatterns::new().unwrap()),
            total_memory_mib: None,
            home: String::new(),
        };
        Arc::new(CellTable::new(parts, Arc::new(SplitGguf::new().unwrap()), clock))
    }

    fn range(base: i64, upper: i64) -> PortLease {
        PortLease::of(Some(&json!({"base": base, "upper": upper}))).unwrap()
    }

    #[test]
    fn a_port_a_cell_holds_is_no_other_cell_s_until_the_cell_goes() {
        let table = table();
        let (none, lease) = (BTreeSet::new(), range(22001, 22003));
        let first = table.at("c1");
        assert_eq!(table.lease(&first, &lease, &none, None), Ok(22001));
        let second = table.at("c2");
        assert_eq!(table.lease(&second, &lease, &none, None), Ok(22002), "the first cell holds 22001");
        assert_eq!(
            table.lease(&first, &lease, &none, None),
            Ok(22001),
            "a cell's own port is no other cell's: it may be its again"
        );
        assert_eq!(table.ports(), BTreeSet::from([22001, 22002]));
        table.drop_cell("c1");
        let third = table.at("c3");
        assert_eq!(
            table.lease(&third, &lease, &none, None),
            Ok(22001),
            "freed at the stop: the cell left the table, and its port with it"
        );
        table.release(&second);
        assert_eq!(second.port(), None, "a start that failed holds no port");
        assert_eq!(table.lease(&table.at("c4"), &lease, &none, None), Ok(22002), "and its port is free again");
        assert_eq!(table.lease(&table.at("c5"), &lease, &none, None), Ok(22003));
        assert_eq!(
            table.lease(&table.at("c6"), &lease, &none, None),
            Err("no free port for a cell in 22001–22003".to_string()),
            "every port held: refused, and nothing is taken"
        );
        assert_eq!(table.find("c6").and_then(|cell| cell.port()), None);
    }

    #[test]
    fn two_starts_at_once_never_take_one_port() {
        let table = table();
        let starts: Vec<_> = (0..24)
            .map(|at| {
                let table = Arc::clone(&table);
                std::thread::spawn(move || {
                    let cell = table.at(&format!("c{at}"));
                    table.lease(&cell, &range(22001, 22100), &BTreeSet::new(), None).unwrap()
                })
            })
            .collect();
        let ports: BTreeSet<i64> = starts.into_iter().map(|start| start.join().unwrap()).collect();
        assert_eq!(ports.len(), 24, "each start a port of its own: {ports:?}");
        assert_eq!(ports.last(), Some(&22024), "and the lowest ones");
    }

    #[test]
    fn a_cell_found_again_holds_the_port_it_was_found_on() {
        let table = table();
        let found = table.at("c22007");
        table.hold(&found, Some(22007));
        let lease = range(22007, 22008);
        assert_eq!(table.lease(&table.at("c9"), &lease, &BTreeSet::new(), None), Ok(22008));
        assert_eq!(Cell::words("c9", Some(22008)), ":22008", "a cell that holds a port is said by it");
        assert_eq!(Cell::words("c9", None), "c9", "and one that holds none by its name");
    }
}
