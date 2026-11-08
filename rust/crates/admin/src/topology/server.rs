//! The fleet's cells as the board draws them.

use crate::app::App;
use crate::common::window::Windows;
use crate::config::args::LlamaArgs;
use crate::config::builder::CellCommand;
use crate::domain::runner::{Config, RunnerRegistry};
use crate::fleet::cell_assets::CellAssets;
use crate::fleet::cell_doorway::CellDoorway;
use crate::fleet::cell_words::CellWords;
use crate::fleet::controller_machine::ControllerMachine;
use crate::fleet::launch_files::LaunchFiles;
use crate::fleet::machine_cells::SlotModel;
use crate::fleet::remote_cells::RemoteCells;
use crate::fleet::server_cells::ServerCells;
use crate::models::checkpoints::ModelCheckpoints;
use crate::models::locator::Locations;
use crate::models::model_list::ModelList;
use crate::models::watch::ModelWatch;
use crate::monitoring::MachineState;
use crate::paths::CONTROLLER_HOST_ID;
use crate::store::topology::Topology;
use os::Host;
use rules::{AskedWindow, Coerce};
use serde_json::{Map, Value, json};
use std::collections::BTreeMap;
use std::path::Path;
use std::sync::{Mutex, PoisonError};

mod slot_facts;

mod live;
use live::LiveRow;

/// What a parked cell's weights weigh on disk, for a while.
#[derive(Default)]
pub struct SlotSizeMemory {
    held: Mutex<BTreeMap<String, (i64, f64)>>,
}

/// The cells of this controller's fleet.
pub struct TopologyServer<'app> {
    app: &'app App,
}

impl<'app> TopologyServer<'app> {
    const STARTUP_PHASES: [&'static str; 3] = ["resolving", "downloading", "loading"];

    /// The reading of `app`.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    /// A size, or none.
    pub fn positive_int(value: Option<&Value>) -> Option<i64> {
        value.filter(|said| !said.is_boolean() && !said.is_null()).and_then(Coerce::int).filter(|number| *number > 0)
    }

    /// A cell that does not run: no port — the scout leases one when it starts (Papyrus `caravan-scout-port-lease`).
    fn parked_row(&self, cell: &str, slot: &Value, client: &Value, reading: &ServerReading<'_>) -> Value {
        let host_id = Coerce::text(slot.get("hostId"));
        let config = slot.get("config").map_or_else(Map::new, Coerce::fields);
        let model_path = SlotModel::path(self.app, slot);
        let runner = self.app.runners.for_config(&config);
        let is_command = runner.row().command_path;
        let phase = if SlotModel::configured(self.app, slot) { "stopped" } else { "reserved" };
        let cells = CellCommand::of(self.app);
        let trained = self.trained_of(&cells, &model_path, reading.models_dir);
        let (boot_enabled, boot_supported) = Self::boot_fields(client, cell);
        let name = {
            let said = Coerce::text(client.get("name"));
            if said.is_empty() { host_id.clone() } else { said }
        };
        let ip = Coerce::stripped(client.get("ip"));
        json!({
            "id": format!("slot:{cell}"), "cellId": cell,
            "name": name, "port": null, "host": ip,
            "model": ModelCheckpoints::display_name(&model_path),
            "cellLabel": runner.artifact_label(&config, reading.quant_words),
            "cellMeta": self.cell_meta(None, &config, is_command),
            "modelPath": model_path,
            "modelStore": self.launch_in_library(&config, &model_path, reading.config, reading.locations),
            "launchFresh": LaunchFiles::new(&config, &model_path).fresh(reading.fresh_report, reading.models_dir),
            "mmproj": Coerce::text(config.get("MMPROJ_FILE")),
            "specDraft": Coerce::text(config.get("SPEC_DRAFT_MODEL_FILE")),
            "specType": Coerce::text(config.get("SPEC_TYPE")),
            "status": {"phase": phase}, "service": "", "gpuIndexes": [], "isRemote": true, "isController": false, "isSlot": true,
            "clientId": host_id, "clientIp": ip, "gpuName": Self::gpu_name_of(client), "modalities": null, "phase": phase,
            "downloadedBytes": 0, "totalBytes": 0, "downloadingFile": "",
            "ctxMax": self.slot_ctx_max(&config, trained), "ctxServed": null, "ctxTrained": trained,
            "modelSizeBytes": Self::file_of(&model_path, reading.models_dir, reading.locations, self.app),
            "promptTps": null, "genTps": null, "requestsProcessing": null, "vllmStats": null,
            "schedule": slot.get("schedule").filter(|said| Coerce::truthy(Some(*said))),
            "slotConfig": config,
            "cacheModels": Coerce::truthy(slot.get("cacheModels")),
            "commandHistory": slot.get("commandHistory").filter(|said| Coerce::truthy(Some(*said))).cloned().unwrap_or_else(|| json!([])),
            "savedCommand": if is_command { self.saved_command(&config) } else { String::new() },
            "bootEnabled": boot_enabled, "bootSupported": boot_supported,
            "pid": null, "lastError": "", "crash": null,
        })
    }

    /// The whole answer: the machine of the controller, and every cell.
    pub fn state(&self) -> Value {
        // absent-ok: an unreadable config reads as the defaults here: what it would break is said on the page that shows it.
        let config = self.app.parse_config().unwrap_or_default();
        let gpu_read = MachineState::of(self.app).gpu_state();
        let raw_gpus = Coerce::list(gpu_read.get("gpus"));
        let gpu_error: String =
            if raw_gpus.is_empty() { Coerce::text(gpu_read.get("error")).chars().take(200).collect() } else { String::new() };
        let gpus: Vec<Value> = raw_gpus
            .iter()
            .enumerate()
            .map(|(at, gpu)| {
                let mut row = gpu.clone();
                if row.get("index").is_none() {
                    Coerce::put(&mut row, "index", json!(at));
                }
                row
            })
            .collect();
        json!({
            "id": CONTROLLER_HOST_ID,
            "hostname": ControllerMachine::name(&Host::name()),
            "ip": self.app.paths.topology_server_ip,
            "gpus": gpus,
            "gpuError": gpu_error,
            "llamaServers": self.fleet_servers(&config),
        })
    }

    /// What a machine's cell says of itself as a row to draw; `None` for a cell with nothing to say yet, or a report that names no cell.
    fn live_row_of<'row>(client: &'row Value, node: &'row Value, slots: &'row Map<String, Value>) -> Option<LiveRow<'row>> {
        let mut phase = Coerce::text(node.get("phase"));
        let running = Coerce::truthy(node.get("running"));
        if phase.is_empty() && !Coerce::stripped(node.get("lastError")).is_empty() {
            phase = "error".to_string();
        }
        if !running && !Self::STARTUP_PHASES.contains(&phase.as_str()) && phase != "error" {
            return None;
        }
        let ip = Coerce::stripped(client.get("ip"));
        if ip.is_empty() {
            return None;
        }
        let cell = ServerCells::node_cell(node)?;
        // The port the scout leased this run, while it holds one; none is said as none.
        let port = node.get("port").filter(|port| Coerce::truthy(Some(*port))).cloned().unwrap_or(Value::Null);
        let slot = slots.get(&cell);
        let config = slot.and_then(|slot| slot.get("config")).map_or_else(Map::new, Coerce::fields);
        Some(LiveRow { client, node, slot, config, cell, port, ip, phase, running })
    }

    /// The cells the machines report, then the ones only the board keeps.
    fn fleet_servers(&self, config: &Config) -> Vec<Value> {
        let (hosts, slots) = self.app.admin.change(|doc| {
            let mut topology = Topology::of(doc);
            (topology.hosts().clone(), topology.slots().clone())
        });
        let models_dir = self.app.models_dir_of(config);
        let locations = ModelList::locations(self.app, false);
        let fresh_report = ModelWatch::of(self.app).report();
        let reading = ServerReading {
            config,
            models_dir: &models_dir,
            locations: &locations,
            fresh_report: &fresh_report,
            quant_words: &ModelCheckpoints::FORMAT_HINTS,
        };
        let mut servers = Vec::new();
        let mut live_cells: Vec<String> = Vec::new();
        for client in hosts.values() {
            let nodes: Vec<Value> = match client.get("llamaNodes").and_then(Value::as_array).filter(|nodes| !nodes.is_empty()) {
                Some(nodes) => nodes.clone(),
                None => {
                    vec![client.get("llamaNode").filter(|node| Coerce::truthy(Some(*node))).cloned().unwrap_or_else(|| json!({}))]
                }
            };
            for node in &nodes {
                if let Some(row) = Self::live_row_of(client, node, &slots) {
                    live_cells.push(row.cell.clone());
                    servers.push(self.live_row(&row, &reading));
                }
            }
        }
        let empty = json!({});
        for (cell, slot) in &slots {
            if live_cells.contains(cell) {
                continue;
            }
            let host_id = Coerce::text(slot.get("hostId"));
            servers.push(self.parked_row(cell, slot, hosts.get(&host_id).unwrap_or(&empty), &reading));
        }
        servers
    }

    /// `(host, port)` → the window each running cell serves, keyed as a router output names it.
    pub fn served_windows(server_obj: &Value) -> BTreeMap<(String, i64), i64> {
        let mut found = BTreeMap::new();
        for row in server_obj.get("llamaServers").and_then(Value::as_array).into_iter().flatten().filter(|row| row.is_object()) {
            let (Some(port), Some(window)) = (Self::positive_int(row.get("port")), Self::positive_int(row.get("ctxServed")))
            else {
                continue;
            };
            let ip = Coerce::stripped(row.get("clientIp"));
            if !ip.is_empty() {
                found.insert((ip, port), window);
            }
        }
        found
    }

    /// A window a served cell's props state: one fact, in `Windows`.
    pub fn declared(entry: &Value) -> Option<i64> {
        Windows::declared(entry)
    }
}

/// What every row of the answer reads.
struct ServerReading<'read> {
    config: &'read Config,
    models_dir: &'read Path,
    locations: &'read Locations,
    fresh_report: &'read Value,
    quant_words: &'read [&'read str],
}

#[cfg(test)]
mod tests {
    use super::live::{LiveFacts, LiveHealth};
    use super::*;
    use crate::tests::{HandClock, TestApp, TestFolder};

    #[test]
    fn a_running_cell_s_row_says_nothing_of_an_address_of_its_own() {
        let folder = TestFolder::new("row-port");
        let clock = HandClock::at(1000);
        let app = TestApp::with_clock(&folder.path, &[], clock.clone());
        // A machine that said no scout address: nothing reaches its cells, and the row does not guess.
        let client = json!({"id": "box", "ip": "127.0.0.1"});
        let node = json!({"port": 1, "phase": "running", "running": true, "firewall": {"state": "restricted"}});
        let slots = Map::new();
        let row = TopologyServer::live_row_of(&client, &node, &slots).unwrap();
        let facts = LiveFacts {
            is_command: false,
            slot_model: String::new(),
            model_path: String::new(),
            health: LiveHealth { body: None, phase: String::new(), word: None },
            effective: "running".to_string(),
            note: "",
            modalities: None,
            crash: None,
            model_name: String::new(),
            meta: Map::new(),
            trained: None,
        };
        let cells = TopologyServer::of(&app);
        let progress = cells.live_progress(&row, &facts);
        for gone in ["reachable", "firewall"] {
            assert!(
                progress.get(gone).is_none(),
                "negative: a cell listens on its machine's loopback, whom its port lets in is no word of the board's: {gone}"
            );
        }
        clock.pass(20);
        let health = cells.live_health(&row, false, None);
        assert_eq!(health.word, None, "no way to the cell: its health is not known, and not drawn as down");
    }

    #[test]
    fn a_split_file_says_what_its_parts_share() {
        assert_eq!(TopologyServer::split_part("/a/m-00001-of-00003.gguf"), Some(("/a/m".to_string(), "00003".to_string())));
        assert_eq!(TopologyServer::split_part("/a/m.gguf"), None);
    }

    #[test]
    fn a_crash_note_is_read_for_its_card() {
        assert!(TopologyServer::crash_note(Some(&json!({"count": 0}))).is_none());
        let note = TopologyServer::crash_note(Some(&json!({"count": 2, "reason": "Out of memory", "gaveUp": true}))).unwrap();
        assert_eq!(note["kind"], "gpu-oom");
        assert_eq!(note["gaveUp"], true);
        assert!(TopologyServer::retry_note(Some(&note), "starting").is_none());
        let live = TopologyServer::crash_note(Some(&json!({"count": 1, "reason": "address already in use"}))).unwrap();
        assert_eq!(TopologyServer::retry_note(Some(&live), "warming").unwrap()["kind"], "port");
        assert!(TopologyServer::retry_note(Some(&live), "running").is_none());
    }

    #[test]
    fn vllm_stats_are_said_only_by_a_scout_that_says_them() {
        assert_eq!(TopologyServer::vllm_stats(&json!({})), Value::Null);
        assert_eq!(TopologyServer::vllm_stats(&json!({"requestsProcessing": 2}))["requestsRunning"], 2);
    }

    #[test]
    fn a_running_cell_s_window_is_keyed_by_where_it_stands() {
        let server = json!({"llamaServers": [{"port": 5, "ctxServed": 100, "clientIp": "a"}, {"port": 6, "clientIp": "b"}, 5]});
        assert_eq!(TopologyServer::served_windows(&server), [(("a".to_string(), 5), 100)].into());
    }
}
