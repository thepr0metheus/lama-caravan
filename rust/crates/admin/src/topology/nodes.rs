//! The machines as the board's cards draw them.

use crate::app::App;
use crate::domain::driver_outlook::DriverOutlook;
use crate::domain::engine::GpuOwners;
use crate::domain::host::HostRecord;
use crate::fleet::controller_machine::ControllerMachine;
use crate::fleet::engine_outputs::EngineOutputs;
use crate::fleet::host_power::HostPower;
use crate::fleet::remote_cells::RemoteCells;
use crate::store::topology::Topology;
use rules::Coerce;
use serde_json::{Map, Value, json};
use std::collections::{BTreeMap, BTreeSet};

/// Which process holds what on which card, as a machine's report says.
#[derive(Default)]
struct GpuHolders {
    indexes: BTreeMap<i64, BTreeSet<i64>>,
    memory: BTreeMap<(i64, i64), f64>,
    names: BTreeMap<i64, String>,
}

impl GpuHolders {
    fn read(gpus: &[Value], compute_apps: Option<&Value>) -> Self {
        let uuid_to_index: BTreeMap<String, Option<i64>> = gpus
            .iter()
            .filter(|gpu| Coerce::truthy(gpu.get("uuid")))
            .map(|gpu| (Coerce::str_of(gpu.get("uuid")), gpu.get("index").and_then(Value::as_i64)))
            .collect();
        let mut out = Self::default();
        for app in compute_apps.and_then(Value::as_array).into_iter().flatten() {
            let Some(index) = uuid_to_index.get(&Coerce::str_of(app.get("gpuUuid"))).copied().flatten() else {
                continue;
            };
            let Some(pid) = app.get("pid").and_then(Value::as_i64) else {
                continue;
            };
            out.indexes.entry(pid).or_default().insert(index);
            // absent-ok: `app.get("usedMiB", 0)`: what a process is not said to hold is nothing.
            out.memory.insert((pid, index), app.get("usedMiB").and_then(Value::as_f64).unwrap_or(0.0));
            out.names.insert(pid, Coerce::text(app.get("name")));
        }
        out
    }

    /// What these processes hold on each of these cards.
    fn memory_of(&self, pids: &BTreeSet<i64>, indexes: &BTreeSet<i64>) -> Map<String, Value> {
        indexes
            .iter()
            .map(|index| {
                // absent-ok: a process the card does not list holds none of it.
                let sum: f64 = pids.iter().map(|pid| self.memory.get(&(*pid, *index)).copied().unwrap_or(0.0)).sum();
                (index.to_string(), if sum.fract() == 0.0 { json!(sum as i64) } else { json!(sum) })
            })
            .collect()
    }

    /// `(the fleet's MiB on this card, the others', the others by process)`.
    fn split_on(&self, index: Option<i64>, fleet_pids: &BTreeSet<i64>) -> (f64, f64, Vec<(i64, f64, String)>) {
        let (mut fleet, mut others, mut foreign) = (0.0, 0.0, Vec::new());
        for ((pid, at), mib) in &self.memory {
            if Some(*at) != index {
                continue;
            }
            if fleet_pids.contains(pid) {
                fleet += mib;
            } else {
                others += mib;
                // absent-ok: a process that names itself nothing is listed by its number.
                foreign.push((*pid, *mib, self.names.get(pid).cloned().unwrap_or_default()));
            }
        }
        (fleet, others, foreign)
    }
}

/// The machines' cards.
pub struct TopologyNodes<'app> {
    app: &'app App,
}

impl<'app> TopologyNodes<'app> {
    /// The cards of `app`.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    fn pids_of(server: &Value) -> BTreeSet<i64> {
        let own = server.get("pid").and_then(Value::as_i64).filter(|pid| *pid != 0);
        let more =
            server.get("pids").and_then(Value::as_array).into_iter().flatten().filter_map(Value::as_i64).filter(|pid| *pid != 0);
        own.into_iter().chain(more).collect()
    }

    /// Which server stands on which card, many to many.
    fn bind_servers(gpus: &mut [Value], compute_apps: Option<&Value>, servers: &mut [Value], engines: Option<&Value>) {
        let holders = GpuHolders::read(gpus, compute_apps);
        let mut gpu_ports: BTreeMap<i64, BTreeSet<i64>> = BTreeMap::new();
        let mut fleet_pids = BTreeSet::new();
        for server in servers.iter_mut() {
            let pids = Self::pids_of(server);
            fleet_pids.extend(pids.iter().copied());
            let mut indexes: BTreeSet<i64> =
                pids.iter().flat_map(|pid| holders.indexes.get(pid).into_iter().flatten().copied()).collect();
            if indexes.is_empty() {
                indexes =
                    server.get("gpuIndexes").and_then(Value::as_array).into_iter().flatten().filter_map(Value::as_i64).collect();
            }
            let mem = if pids.is_empty() { Map::new() } else { holders.memory_of(&pids, &indexes) };
            Coerce::put(server, "gpuIndexes", json!(indexes));
            Coerce::put(server, "gpuMem", Value::Object(mem));
            if let Some(port) = server.get("port").and_then(Value::as_i64) {
                for index in &indexes {
                    gpu_ports.entry(*index).or_default().insert(port);
                }
            }
        }
        let engine_rows = engines.and_then(Value::as_array).map_or(&[][..], Vec::as_slice);
        let owners = GpuOwners::new(engine_rows);
        for gpu in gpus.iter_mut() {
            let index = gpu.get("index").and_then(Value::as_i64);
            let ports: Vec<i64> = index.and_then(|index| gpu_ports.get(&index)).into_iter().flatten().copied().collect();
            Coerce::put(gpu, "serverPorts", json!(ports));
            let (fleet, others, foreign) = holders.split_on(index, &fleet_pids);
            Coerce::put(gpu, "fleetUsedMiB", json!(fleet.round() as i64));
            Coerce::put(gpu, "nonFleetUsedMiB", json!(others.round() as i64));
            Coerce::put(gpu, "outside", json!(owners.split(&foreign)));
        }
    }

    /// The host-centric view.
    pub fn rows(&self, server_obj: &Value, hosts: &[Value]) -> Vec<Value> {
        let mut remote_by_host: BTreeMap<String, Vec<Value>> = BTreeMap::new();
        for server in server_obj.get("llamaServers").and_then(Value::as_array).into_iter().flatten() {
            if Coerce::truthy(server.get("isRemote")) && Coerce::truthy(server.get("clientId")) {
                remote_by_host.entry(Coerce::str_of(server.get("clientId"))).or_default().push(server.clone());
            }
        }
        let schedules = HostPower::of(self.app).schedules();
        hosts
            .iter()
            .map(|host| {
                // absent-ok: a machine with no cells has none.
                let servers = remote_by_host.remove(&Coerce::text(host.get("id"))).unwrap_or_default();
                self.row_of(host, servers, &schedules)
            })
            .collect()
    }

    fn row_of(&self, host: &Value, mut servers: Vec<Value>, schedules: &Map<String, Value>) -> Value {
        let id = Coerce::text(host.get("id"));
        let remote = RemoteCells::of(self.app);
        let rows = host.get("gpus").and_then(Value::as_array).into_iter().flatten();
        let mut gpus: Vec<Value> = rows.filter(|gpu| Coerce::truthy(gpu.get("name"))).cloned().collect();
        for gpu in &mut gpus {
            let index = gpu.get("index").filter(|index| !index.is_null()).and_then(Coerce::int);
            Coerce::put(gpu, "index", json!(index));
        }
        // A machine's cells stand in the order they were made, which a run's port does not change; a cell the board keeps no record of
        // comes after them, by its name.
        let made: Vec<String> = self.app.admin.change(|doc| Topology::of(doc).slots().keys().cloned().collect());
        servers.sort_by_key(|server| {
            let cell = Coerce::text(server.get("cellId"));
            (made.iter().position(|id| *id == cell).unwrap_or(made.len()), cell) // absent-ok: a cell of no record sorts after the kept ones
        });
        Self::bind_servers(&mut gpus, host.get("computeApps"), &mut servers, host.get("engines"));
        remote.record_gpu_history(&id, &mut gpus);
        for server in &mut servers {
            let key = format!("{id}:{}", Coerce::text(server.get("cellId")));
            let history =
                remote.record_tps_history(&key, server.get("promptTps"), server.get("genTps"), server.get("requestsProcessing"));
            Coerce::put(server, "tpsHistory", Value::Array(history));
        }
        let mut cpu = host.get("cpu").filter(|said| Coerce::truthy(Some(*said))).cloned().unwrap_or_else(|| json!({}));
        let history = remote.record_cpu_history(&id, &cpu);
        Coerce::put(&mut cpu, "history", Value::Array(history));
        let word =
            |key: &str, otherwise: Value| host.get(key).filter(|said| Coerce::truthy(Some(*said))).cloned().unwrap_or(otherwise);
        let mut node = Coerce::fields(&HostRecord::brief(host));
        for (key, said) in Coerce::fields(&json!({
            "ip": host.get("ip"),
            "role": "host",
            "ageSeconds": host.get("ageSeconds"),
            "platform": word("platform", json!("")),
            "cpu": cpu,
            "gpus": gpus,
            "servers": servers,
            "llamaBinaryVersion": word("llamaBinaryVersion", json!("")),
            "prismRuntime": word("prismRuntime", json!({})),
            "llamaBinaryMtime": word("llamaBinaryMtime", json!("")),
            "llamaUpdate": word("llamaUpdate", json!({})),
            "scoutVersion": word("scoutVersion", json!("")),
            "scoutCommit": word("scoutCommit", json!("")),
            "powerSchedule": schedules.get(&id).filter(|said| Coerce::truthy(Some(*said))).cloned().unwrap_or_else(|| json!({})),
            "engines": EngineOutputs::of(self.app).annotate(host),
            "entryModels": host.get("entryModels").filter(|said| said.is_array()),
            "modelCache": host.get("modelCache").filter(|said| said.is_object()),
            "controllerMachine": ControllerMachine::of(self.app).is_host(host),
            "gpuError": Coerce::text(host.get("gpuError")),
            "driverWarnings": DriverOutlook::new(host.get("driver").unwrap_or(&Value::Null)).warnings(),
        })) {
            node.insert(key, said);
        }
        Value::Object(node)
    }

    /// Machines whose scout says a fresh llama.cpp build crashes their cells.
    pub fn host_suspects(hosts: &[Value]) -> Vec<Value> {
        hosts
            .iter()
            .filter_map(|host| {
                let verdict = host.get("llamaSuspect").filter(|said| said.get("suspect") == Some(&json!(true)))?;
                let mut row = Coerce::fields(verdict);
                let id = Coerce::text(host.get("id"));
                let name = Coerce::text(host.get("name"));
                row.insert("hostId".to_string(), json!(id));
                row.insert("name".to_string(), json!(if name.is_empty() { id } else { name }));
                row.insert("llamaBinaryVersion".to_string(), json!(Coerce::text(host.get("llamaBinaryVersion"))));
                Some(Value::Object(row))
            })
            .collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_server_stands_on_the_cards_its_processes_use() {
        let mut gpus = [json!({"index": 0, "uuid": "a"}), json!({"index": 1, "uuid": "b"})];
        let apps = json!([{"gpuUuid": "a", "pid": 5, "usedMiB": 100, "name": "s"}, {"gpuUuid": "b", "pid": 6, "usedMiB": 50, "name": "other"}]);
        let mut servers = [json!({"port": 9, "pid": 5, "pids": []})];
        TopologyNodes::bind_servers(&mut gpus, Some(&apps), &mut servers, None);
        assert_eq!(servers[0]["gpuIndexes"], json!([0]));
        assert_eq!(servers[0]["gpuMem"], json!({"0": 100}));
        assert_eq!(gpus[0]["serverPorts"], json!([9]));
        assert_eq!(gpus[0]["fleetUsedMiB"], 100);
        assert_eq!(gpus[1]["nonFleetUsedMiB"], 50);
    }

    #[test]
    fn a_suspect_is_only_one_that_says_so() {
        let hosts = [
            json!({"id": "a", "llamaSuspect": {"suspect": true, "crashes15m": 2}}),
            json!({"id": "b", "llamaSuspect": {"suspect": false}}),
        ];
        let rows = TopologyNodes::host_suspects(&hosts);
        assert_eq!(rows.len(), 1);
        assert_eq!(rows[0]["hostId"], "a");
        assert_eq!(rows[0]["name"], "a");
    }
}
