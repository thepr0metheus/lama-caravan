//! What this machine's memory has left for a cell that keeps its weights in it.
//!
//! Some cells keep their whole model in RAM: Strata holds every expert there and streams the hot ones to the card. The card has its own check; the RAM had none, and a second such cell loaded its
//! model next to the first while the first was still loading: the machine swapped, the OOM killer took the scout, and the board hung (2026-10-14). What the kernel says is available must cover it,
//! with HEADROOM left for the system; and what the cells that run promised, and it itself, loaded yet or not, must fit in BUDGET of the machine's memory: that second rule is the one that sees a
//! cell still loading.

use crate::cells::table::CellTable;
use rules::Coerce;
use serde_json::{Value, json};
use std::fs;
use std::path::Path;

/// What the machine's memory can still promise.
pub struct MemoryLedger<'a> {
    table: &'a CellTable,
    meminfo: &'a Path,
}

/// `/proc/meminfo` in MiB.
#[derive(Debug, Clone, Copy, Default, PartialEq)]
pub struct MemoryFigures {
    /// `MemTotal`.
    pub total: Option<f64>,
    /// `MemAvailable`.
    pub available: Option<f64>,
}

impl MemoryFigures {
    /// What the file at `path` says; nothing at all where it does not read.
    pub fn read(path: &Path) -> Self {
        let Ok(text) = fs::read_to_string(path) else {
            return Self::default();
        };
        let mut out = Self::default();
        for line in text.lines() {
            let Some((key, rest)) = line.split_once(':') else {
                continue;
            };
            let number =
                || rest.split_whitespace().next().and_then(|word| word.parse::<i64>().ok()).map(|kib| kib as f64 / 1024.0);
            match key {
                "MemTotal" => match number() {
                    Some(mib) => out.total = Some(mib),
                    None => return Self::default(),
                },
                "MemAvailable" => match number() {
                    Some(mib) => out.available = Some(mib),
                    None => return Self::default(),
                },
                _ => {}
            }
        }
        out
    }
}

impl<'a> MemoryLedger<'a> {
    /// Left for the system and the other cells' own growth: never promised.
    const HEADROOM_MIB: f64 = 2048.0;
    /// The part of the machine's memory all the promises together may be.
    const BUDGET: f64 = 0.90;

    /// The ledger of these cells, on the figures of this file.
    pub fn new(table: &'a CellTable, meminfo: &'a Path) -> Self {
        Self { table, meminfo }
    }

    /// (how the operator knows it, MiB) of every other cell of this scout than `id` that is up or on its way up and has promised memory: a cell by
    /// the name its model has at the machine's entry, or its id when it has none — never a port, which the board does not show.
    fn promised(&self, id: &str) -> Vec<(String, f64)> {
        let mut found = Vec::new();
        for (other, cell) in self.table.all() {
            // Read apart: `tracking` asks for the same cell's lock.
            let (ram_mib, name) = {
                let facts = cell.facts();
                (facts.ram_mib, facts.name.clone())
            };
            if other != id && ram_mib != 0 && self.table.tracking(&other) {
                found.push((if name.is_empty() { other } else { name }, ram_mib as f64));
            }
        }
        found
    }

    /// The refusal when the memory cannot hold what `want` reserves (`{reserveMiB, who, why}`); `None` when it can, or when this machine does not say what it has: no refusal then, as with no card.
    pub fn short(&self, id: &str, want: &Value) -> Option<Value> {
        let said = want.get("reserveMiB").filter(|value| Coerce::truthy(Some(*value)));
        let need = match said {
            Some(value) => Coerce::float(value)?,
            None => 0.0,
        };
        let figures = MemoryFigures::read(self.meminfo);
        let total = figures.total.filter(|total| *total != 0.0)?;
        let available = figures.available?;
        if need <= 0.0 {
            return None;
        }
        let who = Some(Coerce::text(want.get("who")))
            .filter(|who| !who.is_empty() && Coerce::truthy(want.get("who")))
            .unwrap_or_else(|| "the cell".to_string());
        let why = if Coerce::truthy(want.get("why")) { Coerce::text(want.get("why")) } else { String::new() };
        let held = self.promised(id);
        let holders: Vec<String> = held.iter().map(|(other, _)| other.clone()).collect();
        let hint = if holders.is_empty() { String::new() } else { format!(" — stop {} first", holders.join(", ")) };
        let reason = if why.is_empty() { String::new() } else { format!(" ({why})") };
        let wants = format!("{who} wants {:.1} GiB of memory{reason}", need / 1024.0);
        if need > available - Self::HEADROOM_MIB {
            let error = format!(
                "{wants} but only {:.1} GiB is available (and {:.0} GiB stays for the system){hint}",
                available / 1024.0,
                Self::HEADROOM_MIB / 1024.0
            );
            return Some(json!({"ok": false, "error": error}));
        }
        let promised: f64 = held.iter().map(|(_, mib)| *mib).sum::<f64>() + need;
        if promised > total * Self::BUDGET {
            let error = format!(
                "{wants}, and with what the cells running here promised ({:.1} GiB) that is more than {:.0}% of the machine's {:.1} GiB{hint}",
                (promised - need) / 1024.0,
                Self::BUDGET * 100.0,
                total / 1024.0
            );
            return Some(json!({"ok": false, "error": error}));
        }
        None
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::commands::SystemCommands;
    use crate::models::files::SplitGguf;
    use crate::process::{LogPatterns, MemoryScope, ProcessParts};
    use os::clock::SystemClock;
    use std::sync::Arc;

    fn table() -> CellTable {
        let clock: Arc<dyn os::clock::Clock> = Arc::new(SystemClock::new());
        let parts = ProcessParts {
            clock: Arc::clone(&clock),
            scope: Arc::new(MemoryScope::new(Arc::new(SystemCommands), false)),
            patterns: Arc::new(LogPatterns::new().unwrap()),
            total_memory_mib: None,
            home: String::new(),
        };
        CellTable::new(parts, Arc::new(SplitGguf::new().unwrap()), clock)
    }

    fn figures(name: &str, total_mib: u64, available_mib: u64) -> std::path::PathBuf {
        let path = std::env::temp_dir().join(format!("scout-ledger-{}-{name}", std::process::id()));
        fs::write(&path, format!("MemTotal: {} kB\nMemAvailable: {} kB\nOther: 1 kB\n", total_mib * 1024, available_mib * 1024))
            .unwrap();
        path
    }

    #[test]
    fn what_the_machine_has_not_got_is_refused_by_the_words_that_name_it() {
        let table = table();
        let file = figures("short", 60_000, 10_000);
        let ledger = MemoryLedger::new(&table, &file);
        assert_eq!(ledger.short("c1", &json!({"reserveMiB": 1000})), None);
        let refusal = ledger.short("c1", &json!({"reserveMiB": 9000, "who": "Strata", "why": "experts"})).unwrap();
        assert_eq!(
            refusal.get("error").and_then(Value::as_str),
            Some("Strata wants 8.8 GiB of memory (experts) but only 9.8 GiB is available (and 2 GiB stays for the system)")
        );
        assert_eq!(ledger.short("c1", &json!({"reserveMiB": "x"})), None);
        assert_eq!(ledger.short("c1", &json!({})), None);
        drop(fs::remove_file(&file));
    }

    #[test]
    fn a_cell_still_loading_has_promised_its_memory() {
        let table = table();
        let file = figures("promised", 60_000, 50_000);
        let other = table.at("c3f9a02b1");
        other.facts().ram_mib = 40_000;
        other.facts().name = "strata-experts".to_string();
        let ledger = MemoryLedger::new(&table, &file);
        // Not up and not on its way up: its promise holds nothing.
        assert_eq!(ledger.short("c22002", &json!({"reserveMiB": 30_000})), None);
        table.say("c3f9a02b1", &json!({"phase": "loading"}));
        let refusal = ledger.short("c22002", &json!({"reserveMiB": 30_000})).unwrap();
        let words = refusal.get("error").and_then(Value::as_str).unwrap();
        assert!(
            words.ends_with("that is more than 90% of the machine's 58.6 GiB — stop strata-experts first"),
            "named by its model, not a port: {words}"
        );
        // The cell's own promise is not in its own way.
        assert_eq!(ledger.short("c3f9a02b1", &json!({"reserveMiB": 30_000})), None);
        drop(fs::remove_file(&file));
    }

    #[test]
    fn a_machine_that_does_not_say_is_no_refusal() {
        let table = table();
        let missing = std::path::Path::new("/no/such/meminfo");
        assert_eq!(MemoryLedger::new(&table, missing).short("c1", &json!({"reserveMiB": 1_000_000})), None);
        assert_eq!(MemoryFigures::read(missing), MemoryFigures::default());
    }
}
