//! What a scout says about its machine, and the machines as the board reads them: the reports.

use super::launch_files::LaunchFiles;
use super::machine_models::MachineModels;
use super::machine_rows::MachineRows;
use super::model_cache::ModelCacheFacts;
use super::remote_cells::RemoteCells;
use super::scout::ScoutAuth;
use super::scout_follow::ScoutFollow;
use super::scout_poll::Rerun;
use super::server_cells::{KeptCells, ServerCells};
use crate::app::App;
use crate::domain::client::FleetClient;
use crate::domain::driver_outlook::DriverOutlook;
use crate::domain::engine::EngineReport;
use crate::domain::host::HostRecord;
use crate::fleet::machine_settings::MachineSettings;
use crate::proxies::config::ProxiesConfig;
use crate::store::admin::AdminStore;
use crate::store::topology::Topology;
use plumbing::log::Log;
use rules::{AppError, CellId, Coerce};
use serde_json::{Map, Value, json};
use std::collections::{BTreeMap, BTreeSet};
use std::sync::Arc;
use std::time::Duration;

mod record;
pub use record::HostReport;
use record::ReportedModel;

mod proxy_meta;

/// The routers' outputs follow what a machine's cells do, with no board open (1.3.647).
pub struct CellsFollow;

impl CellsFollow {
    /// Each cell a report names: its name, the port its run holds ("" for none), whether it runs, its phase. A cell that starts again on
    /// another port changes the machine's outputs (`copyPorts`), so the port counts as well.
    fn phases(record: &Value) -> Vec<(String, String, bool, String)> {
        let single;
        let nodes: &[Value] = match record.get("llamaNodes").and_then(Value::as_array) {
            Some(nodes) => nodes,
            None => {
                single = [record.get("llamaNode").cloned().unwrap_or(Value::Null)];
                &single
            }
        };
        let mut said: Vec<(String, String, bool, String)> = nodes
            .iter()
            .filter(|node| node.is_object())
            .map(|node| {
                // absent-ok: a node that names no cell, by name or port, compares as one of none.
                let cell = ServerCells::node_cell(node).unwrap_or_default();
                let port = node
                    .get("port")
                    .filter(|port| Coerce::truthy(Some(*port)))
                    .map_or_else(String::new, |port| Coerce::str_of(Some(port)));
                (cell, port, Coerce::truthy(node.get("running")), Coerce::text(node.get("phase")))
            })
            .collect();
        said.sort();
        said
    }

    fn models(record: &Value) -> Option<Vec<ReportedModel>> {
        let models = record.get("entryModels")?.as_array()?;
        let mut said: Vec<ReportedModel> = models
            .iter()
            .filter(|model| model.is_object())
            .map(|model| {
                let copies = model.get("copies").and_then(Value::as_array).into_iter().flatten().filter(|copy| copy.is_object());
                let mut copies: Vec<(String, i64, String)> = copies
                    .map(|copy| {
                        // absent-ok: a copy that names no cell, or holds no port, compares as one of none.
                        let cell = ServerCells::node_cell(copy).unwrap_or_default();
                        (cell, Coerce::whole(copy.get("port")), Coerce::text(copy.get("state")))
                    })
                    .collect();
                copies.sort();
                (Coerce::text(model.get("id")), Coerce::text(model.get("state")), copies)
            })
            .collect();
        said.sort();
        Some(said)
    }

    /// A report replaced `previous`: whether what its cells do changed.
    pub fn changed(previous: &Value, report: &Value) -> bool {
        Self::phases(previous) != Self::phases(report) || Self::models(previous) != Self::models(report)
    }
}

/// What the board reads of the fleet.
pub struct FleetReads<'app> {
    app: &'app App,
}

impl<'app> FleetReads<'app> {
    /// The reads of `app`.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    /// How long a scout's report may wait for the file (`AdminStore::save_later`), seconds. It is live in memory at once, and the next
    /// heartbeat brings the same figures again within seconds: after a restart the board reads a report at most this old until then.
    pub const REPORT_SAVE_WITHIN: f64 = 300.0;

    /// Stores what a scout says about its machine; `None` for a machine this controller does not hold when `only_known`. A machine first
    /// heard of, or a change of its settings, goes to the file at once; the rest of a report waits for it (`REPORT_SAVE_WITHIN`).
    pub fn record(&self, payload: &Value, only_known: bool) -> Result<Option<Value>, AppError> {
        let now = self.app.now_whole();
        let mut report = HostReport::of(payload, now)?;
        let id = Coerce::text(report.get("id"));
        let held = self.app.admin.change(|doc| {
            let mut topology = Topology::of(doc);
            let hosts = topology.hosts();
            if only_known && !hosts.contains_key(&id) {
                return None;
            }
            let known = hosts.contains_key(&id);
            let previous = hosts.get(&id).cloned().unwrap_or_else(|| json!({}));
            if let Some(first) = previous.get("firstSeen").filter(|first| Coerce::truthy(Some(*first))) {
                Coerce::put(&mut report, "firstSeen", first.clone());
            }
            hosts.insert(id.clone(), report.clone());
            let settings = MachineSettings::remember(&mut topology, &id, &report);
            Some((previous, !known || settings))
        });
        let Some((previous, at_once)) = held else {
            return Ok(None);
        };
        let admin = &self.app.admin;
        if at_once {
            if let Err(error) = admin.save() {
                Log::line(&format!("admin state not saved: {error}"));
            }
        } else {
            admin.save_later(self.app.now());
            admin.save_if_waited(self.app.now(), Self::REPORT_SAVE_WITHIN);
        }
        if CellsFollow::changed(&previous, &report)
            && let Some(app) = self.app.shared()
        {
            let pick: fn(&App) -> &Rerun = |app| &app.cells_follow;
            app.cells_follow.kick(&app, pick, crate::topology::RouterOutputs::follow);
        }
        if let Err(error) = MachineRows::of(self.app).heard(&previous, &report, &self.hosts()) {
            Log::line(&format!("[machine-rows] {id}: the pools' rows were not moved to its models: {}", error.message));
        }
        if let Err(error) = KeptCells::of(self.app).adopt(&id, payload.get("autostartRequests")) {
            Log::line(&format!("[cells] {id}: the cells its scout keeps were not read: {}", error.message));
        }
        ScoutFollow::heard(self.app, &id, &report);
        Ok(Some(report))
    }

    /// Fresh state pulled from each machine's scout between its heartbeats.
    pub fn refresh_from_scouts(app: &App) {
        let reads = FleetReads::of(app);
        let hosts: Vec<Value> = app.admin.change(|doc| Topology::of(doc).hosts().values().cloned().collect());
        for host in hosts {
            let agent_url = Coerce::stripped(host.get("agentUrl")).trim_end_matches('/').to_string();
            if agent_url.is_empty() {
                continue;
            }
            let fields = ScoutAuth::fields(app);
            let Ok(state) = app.http.json("GET", &format!("{agent_url}/api/state"), &fields, &[], Duration::from_secs(2)) else {
                continue;
            };
            if !state.is_object() || Coerce::stripped(state.get("controllerUrl")).is_empty() {
                continue;
            }
            // A scout that sends something unreadable waits for its next beat.
            drop(reads.record(&HostReport::of_state(&state, &agent_url, app.now_whole()), true));
        }
    }

    /// A pull started off the board's request path.
    pub fn kick_poll(app: &Arc<App>) -> bool {
        app.scout_poller.kick(app, |app| &app.scout_poller, Self::refresh_from_scouts)
    }

    fn aliased(mut row: Value, aliases: &Map<String, Value>) -> Value {
        let reported = {
            let name = row.get("name").filter(|said| Coerce::truthy(Some(*said)));
            name.or_else(|| row.get("id").filter(|said| Coerce::truthy(Some(*said)))).cloned().unwrap_or_else(|| json!(""))
        };
        let alias = Coerce::stripped(row.get("id").and_then(|id| aliases.get(&Coerce::str_of(Some(id)))));
        Coerce::put(&mut row, "reportedName", reported);
        Coerce::put(&mut row, "alias", json!(alias));
        if !alias.is_empty() {
            Coerce::put(&mut row, "name", json!(alias));
        }
        row
    }

    /// The operator's client records as the board reads them.
    pub fn clients(&self) -> Vec<Value> {
        let (clients, aliases, agent_aliases) = self.app.admin.change(|doc| {
            let store = AdminStore::topology(doc);
            let named = |store: &mut Map<String, Value>, key: &str| {
                // absent-ok: a section that is not a table holds nothing yet.
                store.entry(key.to_string()).or_insert_with(|| json!({})).as_object().cloned().unwrap_or_default()
            };
            let aliases = named(store, "clientAliases");
            let agents = named(store, "agentAliases");
            // absent-ok: a section that is not a table holds nothing yet.
            (store.get("clients").and_then(Value::as_object).cloned().unwrap_or_default(), aliases, agents)
        });
        let mut rows: Vec<Value> = Vec::new();
        for client in clients.values() {
            let mut row = client.clone();
            if Coerce::truthy(row.get("agents")) {
                let id = Coerce::str_of(row.get("id"));
                let agents: Vec<Value> = row
                    .get("agents")
                    .and_then(Value::as_array)
                    .into_iter()
                    .flatten()
                    .filter(|agent| agent.is_object())
                    .map(|agent| {
                        let mut shown = agent.clone();
                        let alias = agent_aliases
                            .get(&format!("{id}::{}", Coerce::str_of(agent.get("id"))))
                            .filter(|alias| Coerce::truthy(Some(*alias)));
                        if let Some(alias) = alias {
                            Coerce::put(&mut shown, "reportedName", agent.get("name").cloned().unwrap_or(Value::Null));
                            Coerce::put(&mut shown, "name", alias.clone());
                        }
                        shown
                    })
                    .collect();
                Coerce::put(&mut row, "agents", Value::Array(agents));
            }
            rows.push(Self::aliased(row, &aliases));
        }
        rows.sort_by_key(|row| {
            let name = Coerce::text(row.get("name"));
            if name.is_empty() { Coerce::text(row.get("id")) } else { name }
        });
        rows
    }

    /// Machines with a scout as the board reads them.
    pub fn hosts(&self) -> Vec<Value> {
        let now = self.app.now_whole();
        let (hosts, aliases) = self.app.admin.change(|doc| {
            let mut topology = Topology::of(doc);
            let aliases = topology.aliases().clone();
            (topology.hosts().clone(), aliases)
        });
        let mut rows: Vec<Value> = hosts
            .values()
            .map(|host| {
                let mut row = Self::aliased(host.clone(), &aliases);
                let (state, age) = HostRecord::liveness(&row, now, self.app.paths.host_report_ttl);
                Coerce::put(&mut row, "state", json!(state));
                Coerce::put(&mut row, "ageSeconds", json!(age));
                row
            })
            .collect();
        rows.sort_by_key(HostRecord::board_order);
        rows
    }

    /// The machines as the bar of every page lists them, in the board's order.
    pub fn machines(&self) -> Vec<Value> {
        self.hosts().iter().map(HostRecord::brief).collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// When the file says the machine was last heard of: what a restart starts from.
    fn seen_on_disk(app: &App) -> Value {
        let doc: Value = serde_json::from_slice(&std::fs::read(app.admin.store().path()).unwrap()).unwrap();
        doc["topology"]["hosts"]["box"]["lastSeen"].clone()
    }

    #[test]
    fn a_machine_first_heard_of_goes_to_the_file_at_once_though_its_report_says_no_settings() {
        let folder = crate::tests::TestFolder::new("reports-first-heard");
        let clock = crate::tests::HandClock::at(1_000);
        let app = crate::tests::TestApp::with_clock(&folder.path, &[], clock.clone());
        let reads = FleetReads::of(&app);
        reads.record(&json!({"host": {"id": "box", "name": "Box"}}), false).unwrap();
        assert_eq!((seen_on_disk(&app), app.admin.waiting()), (json!(1_000), false));
        clock.pass(10);
        reads.record(&json!({"host": {"id": "box", "name": "Box"}}), false).unwrap();
        assert_eq!((seen_on_disk(&app), app.admin.waiting()), (json!(1_000), true), "negative: its next report waits");
    }

    #[test]
    fn a_report_waits_for_the_file_and_a_new_machine_or_a_change_of_its_settings_does_not() {
        let folder = crate::tests::TestFolder::new("reports-save-later");
        let clock = crate::tests::HandClock::at(1_000);
        let app = crate::tests::TestApp::with_clock(&folder.path, &[], clock.clone());
        let reads = FleetReads::of(&app);
        let report =
            |dir: &str| json!({"host": {"id": "box", "name": "Box"}, "modelCache": {"keep": 1, "dir": dir, "dirChosen": true}});
        reads.record(&report("/a"), false).unwrap();
        assert_eq!(seen_on_disk(&app), json!(1_000), "a machine first heard of goes to the file at once");
        clock.pass(10);
        reads.record(&report("/a"), false).unwrap();
        assert_eq!(seen_on_disk(&app), json!(1_000), "the figures of a heartbeat wait for the file");
        let live = app.admin.read(|doc| Value::Object(doc.clone())["topology"]["hosts"]["box"]["lastSeen"].clone());
        assert_eq!((live, app.admin.waiting()), (json!(1_010), true), "and are live in memory at once");
        clock.pass(FleetReads::REPORT_SAVE_WITHIN as u64 - 10);
        reads.record(&report("/a"), false).unwrap();
        assert_eq!(seen_on_disk(&app), json!(1_000), "negative: not before the first of them waited its time");
        clock.pass(10);
        reads.record(&report("/a"), false).unwrap();
        assert_eq!(
            (seen_on_disk(&app), app.admin.waiting()),
            (json!(1_310), false),
            "a heartbeat after it takes them all to the file"
        );
        clock.pass(10);
        reads.record(&report("/b"), false).unwrap();
        assert_eq!(seen_on_disk(&app), json!(1_320), "a change of the machine's settings goes to the file at once");
        clock.pass(10);
        reads.record(&report("/b"), false).unwrap();
        app.admin.saving(|doc| doc.insert("note".to_string(), json!("x")));
        assert_eq!(
            (seen_on_disk(&app), app.admin.waiting()),
            (json!(1_330), false),
            "a save of anything takes what waited with it"
        );
        clock.pass(10);
        reads.record(&report("/b"), false).unwrap();
        clock.pass(FleetReads::REPORT_SAVE_WITHIN as u64);
        assert!(
            app.admin.save_if_waited(app.now(), FleetReads::REPORT_SAVE_WITHIN),
            "a machine gone quiet: the minute's tick saves it"
        );
        assert_eq!(seen_on_disk(&app), json!(1_340));
        assert!(
            !app.admin.save_if_waited(app.now(), FleetReads::REPORT_SAVE_WITHIN),
            "negative: nothing waits, nothing is written"
        );
    }

    #[test]
    fn a_report_is_cleaned_for_its_record() {
        let record = HostReport::of(
            &json!({
                "host": {"id": "box", "name": "Box", "ip": " 10.0.0.1 "},
                "gpus": [{"name": "RTX", "index": 0, "uuid": null}, {"index": 1}],
                "llamaNode": {"running": 1, "port": 5, "pids": [1, 2, "x"], "ctxMax": 0, "nCtx": 9},
                "autostart": [5, "6", "x", 5],
                "agentUrl": "http://a:1",
            }),
            100,
        )
        .unwrap();
        assert_eq!(record["id"], "box");
        assert_eq!(record["ip"], "10.0.0.1");
        assert_eq!(record["gpus"], json!([{"index": "0", "name": "RTX"}]));
        assert_eq!(record["llamaNode"]["pids"], json!([2]));
        assert_eq!(record["llamaNode"]["ctxMax"], 9);
        assert_eq!(record["llamaNodes"][0]["port"], 5);
        assert_eq!(record["autostart"], json!(["c5", "c6"]), "a scout of before said ports: they name the cells c<port>");
        assert_eq!(record["llamaNodes"][0]["id"], Value::Null, "and named no cell: its port does (ServerCells::node_cell)");
        assert_eq!(record["firstSeen"], 100);
        assert_eq!(record["entryModels"], Value::Null);
        // A scout of 2.46 names its cells, and a cell that does not run holds no port.
        let named = HostReport::of(
            &json!({
                "host": {"id": "box"},
                "llamaNodes": [{"id": "c3f9a02b1", "running": true, "port": 22004}, {"id": "c22011", "port": null}, {"id": "C-1", "port": 7}],
                "autostart": ["c3f9a02b1", "c22011", "nobody's"],
            }),
            100,
        )
        .unwrap();
        let ids: Vec<&Value> = named["llamaNodes"].as_array().unwrap().iter().map(|node| &node["id"]).collect();
        assert_eq!(
            ids,
            [&json!("c3f9a02b1"), &json!("c22011"), &Value::Null],
            "negative: a word that is no cell's name is not kept as one"
        );
        assert_eq!(named["llamaNodes"][1]["port"], Value::Null);
        assert_eq!(named["autostart"], json!(["c22011", "c3f9a02b1"]));
    }

    #[test]
    fn a_cell_s_refusal_keeps_its_advice_and_a_runaway_one_is_still_bounded() {
        let words = format!(
            "model download failed: no room for {}.gguf (1/2): it takes 36.5 GB, more than the 10.0 GB the folder for Strata's files may keep. Nothing was copied. Raise its limit on the machine's page (Model disk → Strata files), or stop a Strata cell.",
            "q".repeat(60)
        );
        let kept = HostReport::node(&json!({"port": 5, "lastError": words}));
        assert_eq!(kept["lastError"], json!(words), "what to do comes after why, and stays");
        let long = HostReport::node(&json!({"port": 5, "lastError": "x".repeat(2000)}));
        assert_eq!(long["lastError"].as_str().map(|said| said.chars().count()), Some(500), "a log's tail is no refusal: bounded");
    }

    #[test]
    fn a_suspect_build_is_said_only_when_it_is_one() {
        assert_eq!(HostReport::suspect(None), Value::Null);
        assert_eq!(HostReport::suspect(Some(&json!({"suspect": false}))), json!({"suspect": false}));
        let said = HostReport::suspect(Some(&json!({"suspect": true, "crashes15m": 3, "restoreCandidate": {"id": "a", "x": 1}})));
        assert_eq!(said["crashes15m"], 3);
        assert_eq!(said["restoreCandidate"], json!({"id": "a"}));
    }

    #[test]
    fn what_a_machine_s_cells_do_is_compared_without_order() {
        let a = json!({"llamaNodes": [{"port": 1, "running": true, "phase": "x"}, {"port": 2}], "entryModels": [{"id": "m", "state": "s", "copies": [{"port": 2, "state": "r"}]}]});
        let b = json!({"llamaNodes": [{"port": 2}, {"port": 1, "running": true, "phase": "x"}], "entryModels": [{"id": "m", "state": "s", "copies": [{"port": 2, "state": "r"}]}]});
        assert!(!CellsFollow::changed(&a, &b));
        let c = json!({"llamaNodes": [{"port": 2}, {"port": 1, "running": false, "phase": "x"}], "entryModels": [{"id": "m", "state": "s", "copies": [{"port": 2, "state": "r"}]}]});
        assert!(CellsFollow::changed(&a, &c));
        // A cell by its name: the same cell started again on another port changes what the machine's model reaches.
        let ran = |port: i64| json!({"llamaNodes": [{"id": "c3f9a02b1", "port": port, "running": true, "phase": "running"}], "entryModels": [{"id": "m", "state": "running", "copies": [{"id": "c3f9a02b1", "port": port, "state": "running"}]}]});
        assert!(!CellsFollow::changed(&ran(22001), &ran(22001)));
        assert!(CellsFollow::changed(&ran(22001), &ran(22002)), "negative: a new port of the same cell is a change");
    }

    #[test]
    fn a_port_said_twice_is_contested() {
        let assignments = json!({"h": {"assignments": [
            {"agentId": "a", "routes": [{"proxyId": "skynet:proxy:5", "role": "primary"}, {"proxyId": "skynet:proxy:6", "modelName": " m "}]},
            {"agentId": "b", "routes": [{"proxyId": "skynet:proxy:5"}, {"proxyId": "other:1"}]},
        ]}});
        let clients = json!({"h": {"name": "Host", "agents": [{"id": "a", "name": "A"}]}});
        let (meta, contested) = FleetReads::port_meta(assignments.as_object().unwrap(), clients.as_object().unwrap());
        assert_eq!(contested, [5].into());
        assert_eq!(meta[&6]["modelName"], "m");
        assert_eq!(meta[&6]["name"], "Host");
    }
}
