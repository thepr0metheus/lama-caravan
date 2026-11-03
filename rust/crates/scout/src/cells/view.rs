//! A cell from outside: its process's status merged with its start's phase and progress, so that the admin sees downloading or loading before the server is up.

use crate::cells::Cells;
use crate::cells::table::Cell;
use crate::cells::watchdog::{ProcessEnd, Watchdog};
use crate::process::HostProcesses;
use rules::Coerce;
use serde_json::{Map, Value, json};
use std::collections::BTreeMap;

/// One look at the machine's process table for every cell, and none when no cell runs.
#[derive(Default)]
struct OneLook {
    table: Option<Option<BTreeMap<i64, Value>>>,
}

impl OneLook {
    fn table(&mut self, cells: &Cells) -> Option<&BTreeMap<i64, Value>> {
        self.table.get_or_insert_with(|| cells.machine.processes()).as_ref()
    }
}

impl Cells {
    /// The views of all the cells.
    pub fn views(&self) -> Vec<Value> {
        let mut look = OneLook::default();
        self.table.all().iter().map(|(_, cell)| Value::Object(self.view_with(cell, &mut look))).collect()
    }

    /// The single-cell view older controllers read: the first cell's.
    pub fn first_view(&self) -> Value {
        self.views().into_iter().next().unwrap_or_else(|| json!({"running": false, "phase": "idle"}))
    }

    /// The view of one cell.
    pub fn view(&self, cell: &Cell) -> Map<String, Value> {
        self.view_with(cell, &mut OneLook::default())
    }

    fn view_with(&self, cell: &Cell, look: &mut OneLook) -> Map<String, Value> {
        let port = cell.port;
        let mut status = cell.process.status();
        let (startup, crash) = {
            let facts = cell.facts();
            (facts.startup.clone(), facts.crash.as_ref().and_then(|note| note.public()))
        };
        if let Some(crash) = &crash {
            status.insert("crash".to_string(), crash.clone());
        }
        if status.get("running") == Some(&Value::Bool(true)) {
            return self.running_view(cell, status, &startup, look);
        }
        let said_port = || startup.get("port").filter(|said| Coerce::truthy(Some(*said))).cloned().unwrap_or_else(|| json!(port));
        // Crashed shortly after start (non-zero exit): an error, even if the startup worker already marked it "running".
        if Coerce::truthy(status.get("crashed")) {
            let reason = Self::crash_reason(&status, crash.as_ref());
            status.insert("phase".to_string(), json!("error"));
            status.insert("port".to_string(), said_port());
            status.insert("modelPath".to_string(), startup.get("modelPath").cloned().unwrap_or_else(|| json!("")));
            status.insert("lastError".to_string(), json!(reason));
            return status;
        }
        let phase = startup.get("phase").and_then(Value::as_str);
        match phase {
            Some("resolving" | "downloading" | "loading") => {
                status.insert("running".to_string(), json!(false));
                status.insert("phase".to_string(), json!(phase));
                status.insert("modelPath".to_string(), startup.get("modelPath").cloned().unwrap_or_else(|| json!("")));
                status.insert("port".to_string(), said_port());
                status.insert("downloadedBytes".to_string(), startup.get("downloadedBytes").cloned().unwrap_or_else(|| json!(0)));
                status.insert("totalBytes".to_string(), startup.get("totalBytes").cloned().unwrap_or_else(|| json!(0)));
                status
                    .insert("downloadingFile".to_string(), startup.get("downloadingFile").cloned().unwrap_or_else(|| json!("")));
                // How fast the copy goes, bytes a second over its last seconds; `null` while not measured.
                status.insert(
                    "downloadBytesPerSec".to_string(),
                    startup.get("downloadBytesPerSec").cloned().unwrap_or(Value::Null),
                );
                status.insert("startedAt".to_string(), startup.get("startedAt").cloned().unwrap_or(Value::Null));
            }
            Some("error") => {
                let error = if Coerce::truthy(startup.get("error")) {
                    startup.get("error").cloned()
                } else {
                    status.get("lastError").cloned()
                };
                status.insert("port".to_string(), json!(port));
                status.insert("phase".to_string(), json!("error"));
                status.insert("lastError".to_string(), error.unwrap_or_else(|| json!("")));
            }
            _ => {
                status.insert("port".to_string(), json!(port));
            }
        }
        status
    }

    /// The card's words for a crash: the watchdog stopped trying, and why.
    fn crash_reason(status: &Map<String, Value>, crash: Option<&Value>) -> String {
        let reason =
            if Coerce::truthy(status.get("lastError")) { Coerce::text(status.get("lastError")) } else { ProcessEnd::how(status) };
        let Some(crash) = crash.filter(|crash| Coerce::truthy(crash.get("gaveUp"))) else {
            return reason;
        };
        let count = Coerce::text(crash.get("count"));
        let why = if Coerce::truthy(crash.get("reason")) { Coerce::text(crash.get("reason")) } else { reason };
        if Coerce::truthy(crash.get("neverReady")) {
            format!("never ready in {count} starts — not restarting it: {why}")
        } else {
            format!("crashed {count} times in {} minutes — not restarting it: {why}", Watchdog::WINDOW_SEC / 60)
        }
    }

    fn running_view(
        &self,
        cell: &Cell,
        status: Map<String, Value>,
        startup: &Map<String, Value>,
        look: &mut OneLook,
    ) -> Map<String, Value> {
        let port = status.get("port").and_then(Value::as_i64).filter(|port| *port != 0).unwrap_or(cell.port);
        // absent-ok: a running process has a pid; none reads as no process under it.
        let pid = status.get("pid").and_then(Value::as_i64).unwrap_or(0);
        let started_at = status.get("startedAt").and_then(Value::as_i64);
        let metrics = self.probe.metrics(port);
        let pids = self.processes.descendants(pid);
        // What its processes have read, how fast, and of how much: a loading cell's progress. Said for every running cell; the board shows it while the cell loads.
        let mut tree = vec![pid];
        tree.extend(&pids);
        let read = self.processes.bytes_read(&tree);
        // A model read through the view by a map passes by the process's own counters: what the view gave it is the larger word.
        let asked = cell.facts().asked.clone();
        let given = self.models.view.given_of(&asked).and_then(|given| i64::try_from(given).ok());
        let read = read.max(given);
        let pace = cell.facts().reading.read(pid, read, self.table.monotonic());
        let mut view = status;
        view.insert("port".to_string(), json!(port));
        view.insert("phase".to_string(), json!("running"));
        view.extend(metrics);
        // The processes it started: the card's memory may be a child's, Strata's engine under its server.
        view.insert("pids".to_string(), json!(pids));
        view.insert("readBytes".to_string(), json!(read));
        view.insert("readBytesPerSec".to_string(), json!(pace));
        view.insert("modelBytes".to_string(), startup.get("modelBytes").cloned().unwrap_or(Value::Null));
        // The memory its processes hold in RAM, their RSS in bytes. `null` when ps did not answer: "not told", never a zero.
        view.insert("ramBytes".to_string(), json!(HostProcesses::resident(pid, look.table(self))));
        view.insert("firewall".to_string(), self.machine.firewall(&json!(port)));
        // Which of the files it holds changed on disk after it started: ⟳ on the card, restart to pick them up.
        // absent-ok: `changed_since(None)`: a start of no known time has changed nothing.
        view.insert("launchDiskNewer".to_string(), json!(cell.process.changed_since(started_at.unwrap_or(0))));
        // Whether its port answers here yet: vLLM installs and loads for minutes before it listens, and from the controller a silent port looks the same as a firewall. Not listening, the cell says its last
        // log lines: where the start is.
        if let Some(listening) = self.machine.listening_ports() {
            let is_listening = listening.contains(&port);
            view.insert("listening".to_string(), json!(is_listening));
            if !is_listening {
                view.insert("startingTail".to_string(), json!(cell.process.log().tail()));
            }
        }
        view
    }
}
