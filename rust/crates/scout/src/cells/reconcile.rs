//! A cell this scout started and no longer holds, found again: what `adopt_survivors` does once at a start, done again while the scout runs.
//!
//! A cell can leave this scout's hands without dying: the scout is killed while the cell loads (2026-10-14), a record is lost, a stop is half done. The process lives on, holding its port, its card and its
//! memory, and the board can neither stop it nor start another. A process that carries this scout's mark for a cell and that no cell of this scout holds is that cell, and it is held again; only once two
//! passes in a row have seen it: a start that has made its process and not yet put it in its cell would otherwise be taken from itself.

use crate::cells::Cells;
use crate::log::Log;
use std::collections::BTreeMap;
use std::sync::Arc;

/// The watch.
pub struct Reconcile {
    cells: Arc<Cells>,
    /// (cell, pid), the passes in a row that have seen it.
    seen: BTreeMap<(String, i64), u32>,
}

impl Reconcile {
    /// The passes in a row that must see the same process before it is taken.
    const SIGHTINGS: u32 = 2;
    /// Seconds between passes.
    pub const INTERVAL_SEC: u64 = 15;

    /// The watch over these cells.
    pub fn new(cells: Arc<Cells>) -> Self {
        Self { cells, seen: BTreeMap::new() }
    }

    /// One pass: the (cell, pid) pairs taken by it.
    pub fn tick(&mut self) -> Vec<(String, i64)> {
        let mut seen = BTreeMap::new();
        let mut taken = Vec::new();
        for (id, roots) in self.cells.processes.tagged_cells() {
            if self.cells.table.tracking(&id) {
                continue;
            }
            for pid in roots {
                // absent-ok: a process not seen before has been seen by no pass.
                let count = self.seen.get(&(id.clone(), pid)).copied().unwrap_or(0) + 1;
                if count >= Self::SIGHTINGS {
                    Log::line(&format!("[reconcile] {id} runs as pid {pid} outside this scout's cells — holding it again"));
                    self.cells.adopt_found(&id, pid);
                    taken.push((id.clone(), pid));
                } else {
                    seen.insert((id.clone(), pid), count);
                }
            }
        }
        self.seen = seen;
        taken
    }
}
