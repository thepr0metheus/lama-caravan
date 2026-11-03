//! What a scout says about its machine, and the machines as the board reads them: the reports.

use super::launch_files::LaunchFiles;
use super::machine_models::MachineModels;
use super::machine_rows::MachineRows;
use super::model_cache::ModelCacheFacts;
use super::remote_cells::RemoteCells;
use super::scout::ScoutAuth;
use super::scout_poll::Rerun;
use super::server_cells::KeptCells;
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
use rules::{AppError, Coerce};
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
    fn phases(record: &Value) -> Vec<(String, bool, String)> {
        let single;
        let nodes: &[Value] = match record.get("llamaNodes").and_then(Value::as_array) {
            Some(nodes) => nodes,
            None => {
                single = [record.get("llamaNode").cloned().unwrap_or(Value::Null)];
                &single
            }
        };
        let mut said: Vec<(String, bool, String)> = nodes
            .iter()
            .filter(|node| node.is_object())
            .map(|node| {
                let port = node
                    .get("port")
                    .filter(|port| Coerce::truthy(Some(*port)))
                    .map_or_else(String::new, |port| Coerce::str_of(Some(port)));
                (port, Coerce::truthy(node.get("running")), Coerce::text(node.get("phase")))
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
                // absent-ok: `int(c.get("port") or 0)`: a copy with no port compares as one.
                let mut ports: Vec<(i64, String)> =
                    copies.map(|copy| (Coerce::whole(copy.get("port")), Coerce::text(copy.get("state")))).collect();
                ports.sort();
                (Coerce::text(model.get("id")), Coerce::text(model.get("state")), ports)
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

    /// Stores what a scout says about its machine; `None` for a machine this controller does not hold when `only_known`.
    pub fn record(&self, payload: &Value, only_known: bool) -> Result<Option<Value>, AppError> {
        let now = self.app.now_whole();
        let mut report = HostReport::of(payload, now)?;
        let id = Coerce::text(report.get("id"));
        let previous = self.app.admin.saving(|doc| {
            let mut topology = Topology::of(doc);
            let hosts = topology.hosts();
            if only_known && !hosts.contains_key(&id) {
                return None;
            }
            let previous = hosts.get(&id).cloned().unwrap_or_else(|| json!({}));
            if let Some(first) = previous.get("firstSeen").filter(|first| Coerce::truthy(Some(*first))) {
                Coerce::put(&mut report, "firstSeen", first.clone());
            }
            hosts.insert(id.clone(), report.clone());
            MachineSettings::remember(&mut topology, &id, &report);
            Some(previous)
        });
        let Some(previous) = previous else {
            return Ok(None);
        };
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
        assert_eq!(record["autostart"], json!([5, 6]));
        assert_eq!(record["firstSeen"], 100);
        assert_eq!(record["entryModels"], Value::Null);
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
