//! What outlives a scout's restart: cells re-attached by their mark, their marker or their port, and the strays reaped.

use crate::cells::Cells;
use crate::cells::records::CellRecords;
use crate::log::Log;
use crate::process::HostProcesses;
use os::Signals;
use rules::{CellDoor, CellId, Coerce};
use serde_json::{Map, Value, json};
use std::collections::BTreeSet;
use std::path::PathBuf;
use std::time::Duration;

impl Cells {
    /// Re-attaches the cells that survived the scout's restart, then reaps only the truly orphaned `llama-server` processes. For each record, in this order: the pid is alive and carries this scout's mark for the
    /// cell, or its command line still contains the marker: adopted, same pid, same uptime. When neither holds, whoever serves the port the record says is the cell. When nothing serves it yet, the process that
    /// carries the mark of it: a cell loading its model does not listen for a minute and more, and a scout restarted in that minute used to forget it (2026-10-14). Only a cell with no process at all is forgotten.
    pub fn adopt_survivors(&self) {
        let mut adopted = BTreeSet::new();
        for (key, record) in self.records.items() {
            let id = record.get("id").and_then(CellId::read).or_else(|| CellId::read(&Value::String(key.clone())));
            let recorded = record.get("pid").map_or(Some(0), |pid| Coerce::int_or_zero(Some(pid)));
            let (Some(id), Some(recorded)) = (id, recorded) else {
                continue;
            };
            // absent-ok: an object stands here by the way the records are written; an odd one holds no settings.
            let fields = record.as_object().cloned().unwrap_or_default();
            let Some(pid) = self.survivor_of(&id, CellRecords::port_of(&fields), recorded, &record) else {
                continue;
            };
            self.take_over(&id, pid, &fields);
            adopted.insert(pid);
        }
        self.reap_strays(&adopted);
    }

    /// The process of a record, or `None` when the record is let go of.
    fn survivor_of(&self, id: &str, port: Option<i64>, recorded: i64, record: &Value) -> Option<i64> {
        let marker = if Coerce::truthy(record.get("marker")) { Coerce::text(record.get("marker")) } else { String::new() };
        let line = if recorded > 1 { self.processes.command_line(recorded) } else { String::new() };
        if recorded > 1
            && (self.processes.cell_of(recorded).as_deref() == Some(id) || HostProcesses::marker_matches(&marker, &line))
        {
            return Some(recorded);
        }
        // The mark and the marker are both gone (an exec-chained wrapper rewrote argv) or the recorded pid was clobbered by a failed restart: whoever serves the cell's port right now IS the cell.
        let serving = port.map(|port| (port, self.processes.listener(port))).filter(|(_, listener)| *listener != 0);
        let pid = match serving {
            None => {
                let carrier = self.processes.carrier(id, recorded);
                if carrier == 0 {
                    self.records.forget(id);
                    Log::line(&format!("[llama-node] {id} is gone: no process serves it or carries its mark — forgetting it"));
                    return None;
                }
                Log::line(&format!(
                    "[llama-node] {id} does not listen yet, but pid {carrier} still runs it (it carries this scout's mark for the cell) — adopting it while it loads"
                ));
                carrier
            }
            Some((port, listener)) => {
                if self.processes.owned(listener) == Some(false) {
                    // Someone else serves the port now, a hand-run server. Ours is gone; theirs stays theirs.
                    Log::line(&format!(
                        "[llama-node] {id}: :{port} is served by pid {listener}, which no scout started — not adopting it"
                    ));
                    self.records.forget(id);
                    return None;
                }
                let path = if Coerce::truthy(record.get("healthPath")) {
                    Coerce::text(record.get("healthPath"))
                } else {
                    "/health".to_string()
                };
                if !self.healthy(port, Duration::from_secs(4), 3, &path) {
                    // Something owns the port but stayed quiet. On a loaded host that is a timeout, not a death: forgetting here stranded a live cell as "stopped" for good.
                    Log::line(&format!(
                        "[llama-node] {id}: :{port} holds the port but {path} stayed quiet — adopting anyway rather than forgetting it"
                    ));
                }
                listener
            }
        };
        if pid != recorded {
            self.records.repoint(id, pid);
        }
        Some(pid)
    }

    /// True if the server on `port` answers its health endpoint with 2xx. The path is not always `/health`: the controller computes it per cell. Retries because this runs at the scout's start, exactly when the
    /// host is busiest.
    fn healthy(&self, port: i64, timeout: Duration, attempts: u32, health_path: &str) -> bool {
        let path = Coerce::strip(health_path);
        let path = if path.is_empty() {
            "/health".to_string()
        } else if path.starts_with('/') {
            path.to_string()
        } else {
            format!("/{path}")
        };
        for attempt in 0..attempts {
            if let Ok(answer) = self.http.ask("GET", &format!("http://{}:{port}{path}", CellDoor::LISTEN), &[], &[], timeout) {
                return (200..300).contains(&answer.head.status);
            }
            if attempt + 1 < attempts {
                std::thread::sleep(Duration::from_secs(1));
            }
        }
        false
    }

    /// Holds a process this scout started and had lost track of as the cell `id`, on the port its record says, or its mark when the record says none: the start-up adoption, the reconcile pass and
    /// a start that finds its cell already running all end here.
    pub fn take_over(&self, id: &str, pid: i64, record: &Map<String, Value>) {
        let cell = self.table.at(id);
        self.table.hold(&cell, CellRecords::port_of(record).or_else(|| self.processes.port_said(pid)));
        let log = Coerce::truthy(record.get("log")).then(|| PathBuf::from(Coerce::text(record.get("log"))));
        // absent-ok: a record of no promise promised nothing.
        let ram = Coerce::int_or_zero(record.get("ramMiB")).unwrap_or(0);
        let mut launch = record.get("launch").filter(|launch| Coerce::truthy(Some(*launch))).cloned();
        // A record written before 2.38.2 keeps the promise beside its launch, not in it: the relaunch reads it there.
        if let Some(Value::Object(fields)) = launch.as_mut().filter(|_| ram != 0) {
            fields.entry("ramMiB".to_string()).or_insert_with(|| json!(ram));
        }
        // absent-ok: a record of no settings has none to show.
        let config = record.get("cfg").and_then(Value::as_object).cloned().unwrap_or_default();
        // absent-ok: `int(... or 0)`: a record of no start time is said started now by `adopt`.
        let started = Coerce::int_or_zero(record.get("startedAt")).unwrap_or(0);
        cell.process.adopt(pid, config, log, started, launch);
        {
            let mut facts = cell.facts();
            facts.cache_models = Coerce::truthy(record.get("cacheModels"));
            facts.ram_mib = ram;
        }
        self.table.say(id, &json!({"phase": "running", "error": ""}));
        Log::line(&format!("[llama-node] adopted running cell {id} on {} (pid {pid})", cell.called()));
    }

    /// The process a scout started for the cell `id` that no cell of this scout holds: found by its mark, listening or still loading. 0 when there is none, or when this scout's own cell of that name is held.
    pub fn survivor(&self, id: &str) -> i64 {
        if self.table.tracking(id) {
            return 0;
        }
        // absent-ok: a cell of no record has no pid to prefer.
        let recorded = Coerce::int_or_zero(self.records.get(id).get("pid")).unwrap_or(0);
        self.processes.carrier(id, recorded)
    }

    /// Holds the process `survivor` found. A record of the cell, if one is left, keeps what the start knew; without one the cell is written down from what the machine can say of the process.
    pub fn adopt_found(&self, id: &str, pid: i64) {
        let mut record = self.records.get(id);
        if record.is_empty() {
            record = self.records.found(id, pid, &self.config.text("llamaServerBin"), &self.logs, &self.processes);
        } else if Coerce::int_or_zero(record.get("pid")) != Some(pid) {
            self.records.repoint(id, pid);
            record.insert("pid".to_string(), json!(pid));
        }
        self.take_over(id, pid, &record);
    }

    /// Kills any `llama-server` left from a previous run. Whatever a scout started and nobody adopted is a genuine orphan holding the card and the port. Only a process a scout started: it used to be any process
    /// running the same binary, and on a machine the scout shares with the controller that is the controller's own cells.
    fn reap_strays(&self, keep: &BTreeSet<i64>) {
        let binary = Coerce::strip(&self.config.text("llamaServerBin")).to_string();
        if binary.is_empty() {
            return;
        }
        let Ok(found) = self.commands.run(&["pgrep", "-f", &binary], Duration::from_secs(5)) else {
            return;
        };
        let own = i64::from(std::process::id());
        let pids: Vec<i64> = found
            .stdout
            .split_whitespace()
            .filter_map(|word| word.parse::<i64>().ok())
            .filter(|pid| *pid != own && !keep.contains(pid) && self.processes.owned(*pid) == Some(true))
            .collect();
        if pids.is_empty() {
            return;
        }
        Log::line(&format!("[llama-node] reaping {} stray llama-server(s): {pids:?}", pids.len()));
        for pid in &pids {
            // Gone already is what was asked.
            drop(Signals::terminate(*pid));
        }
        std::thread::sleep(Duration::from_secs(2));
        for pid in pids.iter().filter(|pid| Signals::alive(**pid)) {
            drop(Signals::kill(*pid));
        }
        if keep.is_empty() {
            self.models.purge(&[]);
        }
    }
}
