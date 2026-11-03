//! Stopping cells: a stopped cell leaves the table and the registry, and the model cache loses what no running cell holds, unless the cell keeps its models cached. A stop that could not verify must not erase the
//! registry entry: that would turn a recoverable cell into a genuinely unowned process.

use crate::cells::Cells;
use crate::log::Log;
use crate::models::CellsInUse;
use crate::process::{CellScope, HostProcesses};
use os::Signals;
use serde_json::{Value, json};
use std::collections::BTreeSet;
use std::path::PathBuf;
use std::time::Duration;

impl Cells {
    /// Stops one cell (`port`) or every cell, and says how each went.
    pub fn stop(&self, port: Option<i64>) -> Value {
        let ports: Vec<i64> = match port.filter(|port| *port != 0) {
            Some(port) => vec![port],
            None => self.table.all().iter().map(|(port, _)| *port).collect(),
        };
        let mut results = Vec::with_capacity(ports.len());
        let mut own: BTreeSet<PathBuf> = BTreeSet::new();
        for port in ports {
            let cell = self.table.at(port);
            // Asked before the stop: with its process gone there is nothing to ask the way to its scope of.
            let scope = cell.process.status().get("pid").and_then(Value::as_i64).and_then(|pid| self.processes.scope_of(pid));
            let mut result = cell.process.stop();
            let not_running = result.get("detail").and_then(Value::as_str) == Some("not running");
            if not_running {
                result = self.reclaim(port, result);
            } else if result.get("ok") == Some(&Value::Bool(true)) {
                self.sweep(port, scope.as_ref());
            }
            let stopped_nothing = result.get("detail").and_then(Value::as_str) == Some("not running");
            let stopped = result.get("ok") == Some(&Value::Bool(true));
            results.push(result);
            if !stopped {
                continue;
            }
            self.table.say(port, &json!({"phase": "idle", "error": "", "downloadedBytes": 0, "totalBytes": 0}));
            // A cell that keeps no cache lets go of its own models when a stop stopped it, the files its present start asked for, and of nothing else: the rest of the cache is the keeper's. A stop of nothing lets
            // go of nothing: the board removes a stopped cell with one more stop, and the purge that followed deleted every cached model no running cell held: 116 GB at one "Remove cell"; a stop of an Ollama
            // cell, whose model lives in the engine, deleted 92 GB more, and 101.5 GB again once its port's past starts counted as its own (2026-10-26).
            let (keeps_cache, asked) = {
                let facts = cell.facts();
                (facts.cache_models, facts.asked.clone())
            };
            if !keeps_cache && !stopped_nothing {
                own.extend(self.keeper.files_of(&asked));
            }
            self.table.drop_cell(port);
            self.records.forget(port);
            // What it made from its model goes the way its models go: kept with a cache, removed without one.
            if !keeps_cache {
                self.models.clear_scratch(port);
            }
        }
        // Once, after the stopped cells are dropped, keeping what a running cell holds: a model still served by another cell is not evicted.
        if !own.is_empty() {
            let files: Vec<String> = own.iter().map(|path| path.display().to_string()).collect();
            self.models.release(&files, &self.table.held_files());
        }
        match results.len() {
            1 => results.pop().unwrap_or(Value::Null),
            _ => json!({"ok": true, "results": results}),
        }
    }

    /// "not running" from a process with no handles means it consulted NOTHING: the port may still be served by a process this scout lost track of (that is how a stop once reported success while 10.7 GB stayed
    /// occupied). Verifies the port; kills only what can be recognized as ours: first of all what carries this scout's mark for the port, then what the record's marker or the `llama` binary says it is.
    fn reclaim(&self, port: i64, result: Value) -> Value {
        let listener = self.processes.listener(port);
        // absent-ok: a port no process carries the mark of has none to stop.
        let marked = self.processes.tagged_cells().remove(&port).unwrap_or_default();
        if listener == 0 && marked.is_empty() {
            return result;
        }
        let mut targets = marked;
        if listener != 0 && !targets.contains(&listener) {
            if self.processes.port_of(listener) != port && !self.recognized(port, listener) {
                return json!({
                    "ok": false,
                    "listenerPid": listener,
                    "error": format!("port {port} is held by an unrecognized process (pid {listener}) — not killing it"),
                });
            }
            targets.push(listener);
        }
        self.terminate(&self.with_descendants(&targets));
        let pid = if listener != 0 { Some(listener) } else { targets.first().copied() };
        json!({"ok": true, "reclaimed": true, "pid": pid})
    }

    fn recognized(&self, port: i64, listener: i64) -> bool {
        let line = self.processes.command_line(listener);
        let record = self.records.get(port);
        let marker = rules::Coerce::text(record.get("marker"));
        let binary = self.config.text("llamaServerBin");
        let by_marker = rules::Coerce::truthy(record.get("marker")) && HostProcesses::marker_matches(&marker, &line);
        by_marker || (!binary.is_empty() && line.contains(&binary))
    }

    fn with_descendants(&self, roots: &[i64]) -> Vec<i64> {
        let mut all = Vec::new();
        for root in roots {
            all.push(*root);
            all.extend(self.processes.descendants(*root));
        }
        all
    }

    /// After a stop: whatever still carries this scout's mark for the port, or stands in the cell's scope, goes too. A server that hands the card to a child leaves the child holding 31 GB when the parent's SIGTERM does not reach it; a stop that
    /// ends with a cell's memory still in use is no stop.
    fn sweep(&self, port: i64, scope: Option<&CellScope>) {
        // absent-ok: a port no process carries the mark of is swept already.
        let mut left = self.processes.tagged_cells().remove(&port).unwrap_or_default();
        for pid in scope.map(CellScope::pids).into_iter().flatten() {
            if !left.contains(&pid) {
                left.push(pid);
            }
        }
        if !left.is_empty() {
            Log::line(&format!(
                "[llama-node] :{port} stopped, but {left:?} still carry its mark or stand in its scope — terminating them"
            ));
            self.terminate(&self.with_descendants(&left));
        }
    }

    /// SIGTERM, up to 10 s for them to go, then SIGKILL for the rest. Alive is asked of `ps`, as the stop of a cell it has no handle of always did: a signal-0 probe also says "alive" of a process that is a zombie
    /// until its parent reaps it.
    fn terminate(&self, pids: &[i64]) {
        const PATIENCE: f64 = 10.0;
        for pid in pids {
            // Gone already is what was asked.
            drop(Signals::terminate(*pid));
        }
        let deadline = self.clock.monotonic() + PATIENCE;
        while self.clock.monotonic() < deadline && pids.iter().any(|pid| !self.processes.command_line(*pid).is_empty()) {
            std::thread::sleep(Duration::from_millis(300));
        }
        for pid in pids.iter().filter(|pid| !self.processes.command_line(**pid).is_empty()) {
            drop(Signals::kill(*pid));
        }
    }
}
