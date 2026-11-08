//! What was started on this machine, kept in `state.json` under "cells" so the next scout start can find it again: one record per cell, by its name, with the port its run holds.

use crate::cells::logs::CellLogs;
use crate::process::HostProcesses;
use crate::state::ScoutState;
use os::clock::Clock;
use rules::Coerce;
use serde_json::{Map, Value, json};
use std::collections::BTreeSet;
use std::sync::Arc;

/// What a start writes down.
#[derive(Debug, Default)]
pub struct NewRecord {
    /// "llama" or "command".
    pub kind: &'static str,
    /// The port its run holds: what a scout started after this one dials it at. `None` when nobody can say it.
    pub port: Option<i64>,
    /// The process.
    pub pid: i64,
    /// What its command line carries.
    pub marker: String,
    /// What it was started with.
    pub config: Map<String, Value>,
    /// Where it logs.
    pub log: String,
    /// Whether its models stay.
    pub cache_models: bool,
    /// Where it answers. Kept because re-adoption happens at the scout's start, long after the controller told where this cell answers: a vLLM cell replies on `/v1/models`, and probing `/health` would bury it.
    pub health_path: String,
    /// How it was launched, so that a crash after a scout's restart can be followed by the same launch.
    pub launch: Option<Value>,
    /// What its model is called at the machine's entry: kept, as a restart no longer has the request.
    pub name: String,
    /// The memory it promised to keep resident: kept, as a restart no longer has the request.
    pub ram_mib: i64,
}

/// The records, under the state's one lock, saved at once.
pub struct CellRecords {
    state: Arc<ScoutState>,
    clock: Arc<dyn Clock>,
}

impl CellRecords {
    const KEY: &'static str = "cells";
    const MARKER_LETTERS: usize = 200;

    /// The records of this state.
    pub fn new(state: Arc<ScoutState>, clock: Arc<dyn Clock>) -> Self {
        Self { state, clock }
    }

    /// Writes one down.
    pub fn add(&self, id: &str, new: NewRecord) {
        let mut record = Map::new();
        record.insert("id".to_string(), json!(id));
        record.insert("port".to_string(), json!(new.port));
        record.insert("kind".to_string(), json!(new.kind));
        record.insert("pid".to_string(), json!(new.pid));
        record.insert("marker".to_string(), json!(Coerce::first_letters(&new.marker, Self::MARKER_LETTERS)));
        let config: Map<String, Value> = new.config.into_iter().filter(|(key, _)| key != "cmd").collect();
        record.insert("cfg".to_string(), Value::Object(config));
        record.insert("log".to_string(), json!(new.log));
        record.insert("cacheModels".to_string(), json!(new.cache_models));
        record.insert(
            "healthPath".to_string(),
            json!(if new.health_path.is_empty() { "/health" } else { new.health_path.as_str() }),
        );
        record.insert("startedAt".to_string(), json!(self.clock.epoch() as i64));
        if let Some(launch) = new.launch.filter(|launch| Coerce::truthy(Some(launch))) {
            record.insert("launch".to_string(), launch);
        }
        if !new.name.is_empty() {
            record.insert("name".to_string(), json!(new.name));
        }
        if new.ram_mib != 0 {
            record.insert("ramMiB".to_string(), json!(new.ram_mib));
        }
        self.state.change(|doc| {
            let cells = doc.entry(Self::KEY.to_string()).or_insert_with(|| json!({}));
            if let Value::Object(cells) = cells {
                cells.insert(id.to_string(), Value::Object(record));
            }
        });
    }

    /// Lets one go.
    pub fn forget(&self, id: &str) {
        if !self.get(id).is_empty() {
            self.state.change(|doc| doc.get_mut(Self::KEY).and_then(Value::as_object_mut).and_then(|cells| cells.remove(id)));
        }
    }

    /// All of them: (key, record).
    pub fn items(&self) -> Vec<(String, Value)> {
        self.state.read(|doc| {
            doc.get(Self::KEY)
                .and_then(Value::as_object)
                .map_or_else(Vec::new, |cells| cells.iter().map(|(key, record)| (key.clone(), record.clone())).collect())
        })
    }

    /// The port a record says its run holds; `None` for a record that says none.
    pub fn port_of(record: &Map<String, Value>) -> Option<i64> {
        record.get("port").and_then(Value::as_i64).filter(|port| *port > 0)
    }

    /// The ports the records of every other cell than `id` say their runs hold: what a lease leaves alone, a cell that may still run.
    pub fn ports_besides(&self, id: &str) -> BTreeSet<i64> {
        let records = self.items();
        let others = records.iter().filter(|(key, _)| key != id);
        others.filter_map(|(_, record)| record.as_object().and_then(Self::port_of)).collect()
    }

    /// The record of the cell `id`; empty when there is none.
    pub fn get(&self, id: &str) -> Map<String, Value> {
        self.state.read(|doc| {
            doc.get(Self::KEY)
                .and_then(|cells| cells.get(id))
                .and_then(Value::as_object)
                .cloned()
                // absent-ok: the empty record is how the callers read "none".
                .unwrap_or_default()
        })
    }

    /// The record's process was found again under another pid.
    pub fn repoint(&self, id: &str, pid: i64) {
        self.state.change(|doc| {
            let record = doc.get_mut(Self::KEY).and_then(|cells| cells.get_mut(id)).and_then(Value::as_object_mut);
            if let Some(record) = record {
                record.insert("pid".to_string(), json!(pid));
            }
        });
    }

    /// The record of a cell this scout started and has none of: what the machine says of its process, its command line, the port its mark says, when it started, the log it was given by name, and
    /// nothing more: the controller sends the rest with the next start.
    pub fn found(&self, id: &str, pid: i64, llama_bin: &str, logs: &CellLogs, processes: &HostProcesses) -> Map<String, Value> {
        let line = processes.command_line(pid);
        let llama = !llama_bin.is_empty() && line.contains(llama_bin);
        let log = logs.named(if llama { "llama-server" } else { "command-cell" }, id);
        let port = processes.port_said(pid);
        let mut config = Map::new();
        config.insert("port".to_string(), json!(port));
        self.add(
            id,
            NewRecord {
                kind: if llama { "llama" } else { "command" },
                port,
                pid,
                marker: line,
                config,
                log: if log.exists() { log.display().to_string() } else { String::new() },
                ..NewRecord::default()
            },
        );
        let started = processes.started_at(pid);
        if started != 0 {
            self.state.change(|doc| {
                let record = doc.get_mut(Self::KEY).and_then(|cells| cells.get_mut(id)).and_then(Value::as_object_mut);
                if let Some(record) = record {
                    record.insert("startedAt".to_string(), json!(started));
                }
            });
        }
        self.get(id)
    }
}
