//! A scout's report in the shape the record keeps.

use super::*;

/// `(id, state, [(port, state)])` of a machine's model, as far as a change of it matters.
/// A model of a machine's entry as a report says it: its name, its state, and each copy by its cell, the port its run holds and its state.
pub(super) type ReportedModel = (String, String, Vec<(String, i64, String)>);

/// A scout's report in the shape the record keeps.
pub struct HostReport;

impl HostReport {
    pub(super) const GPU_FIELDS: [&'static str; 13] = [
        "index",
        "uuid",
        "name",
        "vendor",
        "driverStatus",
        "memoryTotalMiB",
        "memoryUsedMiB",
        "memoryFreeMiB",
        "utilizationGpuPct",
        "temperatureC",
        "powerDrawW",
        // The card's bus, since scout 2.45.0: what weights left in RAM come to it over (the board's estimate of the speed).
        "pcieGen",
        "pcieWidth",
    ];

    pub(super) fn cut(raw: Option<&Value>, most: usize) -> String {
        let text: String = Coerce::stripped(raw).chars().take(most).collect();
        Coerce::strip(&text).to_string()
    }

    pub(super) fn cut_raw(raw: Option<&Value>, most: usize) -> String {
        Coerce::text(raw).chars().take(most).collect()
    }

    /// The GPU inventory a scout reports in its heartbeat.
    pub fn gpus(raw: Option<&Value>) -> Vec<Value> {
        let mut gpus = Vec::new();
        for item in raw.and_then(Value::as_array).into_iter().flatten().take(8).filter(|item| item.is_object()) {
            let mut row = Map::new();
            for key in Self::GPU_FIELDS {
                if let Some(said) = item.get(key).filter(|said| !said.is_null()) {
                    let shown = Coerce::str_of(Some(said));
                    let shown = Coerce::strip(&shown);
                    if !shown.is_empty() {
                        row.insert(key.to_string(), json!(shown.chars().take(80).collect::<String>()));
                    }
                }
            }
            if Coerce::truthy(row.get("name")) {
                gpus.push(Value::Object(row));
            }
        }
        gpus
    }

    /// A scout's word on its fresh llama.cpp build as the record keeps it.
    pub(super) fn suspect(raw: Option<&Value>) -> Value {
        let Some(raw) = raw.filter(|raw| raw.is_object()) else {
            return Value::Null;
        };
        if raw.get("suspect") != Some(&json!(true)) {
            return json!({"suspect": false});
        }
        // absent-ok: `int(raw.get(key) or 0)`, with 0 for what is no number: a count not said is none.
        let number = |key: &str| Coerce::whole(raw.get(key));
        let candidate =
            raw.get("restoreCandidate").filter(|candidate| candidate.is_object() && Coerce::truthy(candidate.get("id")));
        let restore = candidate.map_or(Value::Null, |candidate| {
            let kept: Map<String, Value> = ["id", "commit", "version", "builtAt", "sizeMb"]
                .iter()
                .filter_map(|key| candidate.get(*key).map(|said| ((*key).to_string(), said.clone())))
                .collect();
            Value::Object(kept)
        });
        json!({
            "suspect": true, "crashes15m": number("crashes15m"), "builtAt": number("builtAt"),
            "currentCommit": Self::cut_raw(raw.get("currentCommit"), 40),
            "firstSeenAt": number("firstSeenAt"), "lastSeenAt": number("lastSeenAt"), "restoreCandidate": restore,
        })
    }

    pub(super) fn compute_apps(raw: Option<&Value>) -> Vec<Value> {
        let apps = raw.and_then(Value::as_array).into_iter().flatten().take(64).filter(|app| app.is_object());
        apps.filter_map(|app| {
            let (pid, used) = (Coerce::int_or_zero(app.get("pid"))?, Coerce::int_or_zero(app.get("usedMiB"))?);
            Some(json!({"gpuUuid": Self::cut_raw(app.get("gpuUuid"), 80), "pid": pid, "name": Self::cut(app.get("name"), 60), "usedMiB": used}))
        })
        .collect()
    }

    pub(super) fn cpu(raw: Option<&Value>) -> Value {
        let mut cpu = Map::new();
        let Some(raw) = raw.filter(|raw| raw.is_object() && Coerce::truthy(Some(*raw))) else {
            return Value::Object(cpu);
        };
        for key in ["loadPct", "ncpu", "logicalCores", "physicalCores", "availableCores"] {
            if let Some(said) = raw.get(key).filter(|said| !said.is_null()) {
                cpu.insert(key.to_string(), said.clone());
            }
        }
        if let Some(ram) = raw.get("ram").filter(|ram| ram.is_object()) {
            cpu.insert("ram".to_string(), json!({"usedGb": ram.get("usedGb"), "totalGb": ram.get("totalGb")}));
        }
        Value::Object(cpu)
    }

    pub(super) fn node(raw: &Value) -> Value {
        if !raw.is_object() {
            return json!({});
        }
        let pids = raw.get("pids").and_then(Value::as_array).into_iter().flatten();
        let pids: Vec<&Value> = pids.filter(|pid| pid.as_i64().is_some_and(|pid| pid > 1)).take(64).collect();
        let ctx_max = raw.get("ctxMax").filter(|said| Coerce::truthy(Some(*said))).or_else(|| raw.get("nCtx"));
        let tail: Vec<char> = Coerce::text(raw.get("startingTail")).chars().collect();
        let tail: String = tail.iter().skip(tail.len().saturating_sub(1500)).collect();
        // absent-ok: `int(raw.get(key) or 0)`: what is not said to be read is none so far.
        let count = |key: &str| Coerce::whole(raw.get(key));
        let object = |key: &str| raw.get(key).filter(|said| said.is_object());
        json!({
            // The cell by its name since scout 2.46; a scout of before names none, and its port names the cell `c<port>` (ServerCells::node_cell).
            "id": raw.get("id").filter(|said| said.is_string()).and_then(CellId::read),
            "running": Coerce::truthy(raw.get("running")),
            // The port this run of the cell leased; none while it holds none.
            "port": raw.get("port"),
            "modelPath": Self::cut_raw(raw.get("modelPath"), 300),
            "mmprojPath": Self::cut_raw(raw.get("mmprojPath"), 300),
            "specPath": Self::cut_raw(raw.get("specPath"), 300),
            "specType": Self::cut_raw(raw.get("specType"), 40),
            "uptimeSec": raw.get("uptimeSec"),
            "pid": raw.get("pid"),
            "pids": pids,
            "ramBytes": EngineReport::size(raw.get("ramBytes")),
            // A refusal says what to do after why: Strata's "no room" ran to 270 characters and lost its advice at 200 (2026-11-03).
            "lastError": Self::cut_raw(raw.get("lastError"), 500),
            "phase": Self::cut_raw(raw.get("phase"), 20),
            "downloadedBytes": count("downloadedBytes"),
            "totalBytes": count("totalBytes"),
            "downloadingFile": Self::cut_raw(raw.get("downloadingFile"), 200),
            "downloadBytesPerSec": EngineReport::size(raw.get("downloadBytesPerSec")),
            "readBytes": EngineReport::size(raw.get("readBytes")),
            "readBytesPerSec": EngineReport::size(raw.get("readBytesPerSec")),
            "modelBytes": EngineReport::size(raw.get("modelBytes")),
            "promptTps": raw.get("promptTps"),
            "genTps": raw.get("genTps"),
            "requestsProcessing": raw.get("requestsProcessing"),
            "noMetrics": raw.get("noMetrics") == Some(&json!(true)),
            "requestsWaiting": raw.get("requestsWaiting"),
            "ctxMax": ctx_max,
            "ctxUsed": raw.get("ctxUsed"),
            "modalities": RemoteCells::normalize_modalities(raw.get("modalities")),
            "firewall": object("firewall"),
            "crash": object("crash"),
            "listening": raw.get("listening").filter(|said| said.is_boolean()),
            "startingTail": tail,
            "launchDiskNewer": raw.get("launchDiskNewer").and_then(Value::as_array).map(|said| LaunchFiles::disk_newer(said)),
        })
    }

    /// The report as a record.
    pub fn of(payload: &Value, now: i64) -> Result<Value, AppError> {
        let host = payload.get("host").filter(|host| host.is_object());
        let at = |key: &str| host.and_then(|host| host.get(key));
        let named = at("id").filter(|said| Coerce::truthy(Some(*said))).or_else(|| at("name"));
        let host_id = FleetClient::validate_id(named)?;
        let raw_nodes = payload.get("llamaNodes").and_then(Value::as_array);
        let mut nodes: Vec<Value> = raw_nodes.into_iter().flatten().filter(|node| node.is_object()).map(Self::node).collect();
        let one = payload.get("llamaNode").map_or_else(|| json!({}), Self::node);
        let node = if Coerce::truthy(Some(&one)) { one } else { nodes.first().cloned().unwrap_or_else(|| json!({})) };
        if nodes.is_empty() && Coerce::truthy(Some(&node)) {
            nodes.push(node.clone());
        }
        let object = |key: &str| payload.get(key).filter(|said| said.is_object()).cloned().unwrap_or_else(|| json!({}));
        // The cells the scout starts with its machine, by their names; a scout of before said their ports, which name the cells `c<port>`.
        let autostart = payload.get("autostart").and_then(Value::as_array).map(|said| {
            let unique: BTreeSet<String> = said.iter().filter_map(CellId::read).collect();
            unique
        });
        let telemetry = payload.get("telemetry").filter(|said| said.is_object()).map(|said| {
            let kept: Map<String, Value> = ["watchedSeconds", "idleSeconds", "retentionSeconds"]
                .iter()
                .filter_map(|key| said.get(*key).map(|value| ((*key).to_string(), value.clone())))
                .collect();
            Value::Object(kept)
        });
        let name = Self::cut(at("name"), 120);
        let record = json!({
            "id": host_id,
            "name": if at("name").is_some_and(|said| Coerce::truthy(Some(said))) { name } else { host_id.clone() },
            "hostname": Self::cut(at("hostname"), 160),
            "ip": Self::cut(at("ip"), 80),
            "agentUrl": Self::cut(payload.get("agentUrl"), 240),
            "gpus": Self::gpus(payload.get("gpus")),
            "gpuError": Self::cut(payload.get("gpuError"), 200),
            "computeApps": Self::compute_apps(payload.get("computeApps")),
            "engines": EngineReport::engines(payload.get("engines")),
            "cpu": Self::cpu(payload.get("cpu")),
            "platform": Self::cut(payload.get("platform"), 40),
            "driver": DriverOutlook::clean(payload.get("driver").unwrap_or(&Value::Null)),
            "llamaNode": node,
            "llamaNodes": nodes,
            "llamaBinaryVersion": Self::cut(payload.get("llamaBinaryVersion"), 120),
            "prismRuntime": object("prismRuntime"),
            "llamaBinaryMtime": Self::cut(payload.get("llamaBinaryMtime"), 30),
            "llamaUpdate": object("llamaUpdate"),
            "scoutVersion": Self::cut(payload.get("scoutVersion"), 40),
            "autostart": autostart,
            "llamaSuspect": Self::suspect(payload.get("llamaSuspect")),
            "telemetry": telemetry,
            "entryModels": MachineModels::clean(payload.get("entryModels")),
            "modelCache": ModelCacheFacts::clean(payload.get("modelCache")),
            "firstSeen": now,
            "lastSeen": now,
        });
        Ok(Self::with_release(record, payload))
    }

    /// The release the scout says it runs. Said only by a scout installed as one, and no word at all from the others, not an empty one: nothing here stands for a release without a name.
    fn with_release(mut record: Value, payload: &Value) -> Value {
        let commit = Self::cut(payload.get("scoutCommit"), 40);
        if !commit.is_empty()
            && let Some(fields) = record.as_object_mut()
        {
            fields.insert("scoutCommit".to_string(), json!(commit));
        }
        record
    }

    /// A scout's `/api/state` in the shape of its heartbeat, so that a pull and a beat are stored alike.
    pub fn of_state(state: &Value, agent_url: &str, now: i64) -> Value {
        let or_empty =
            |key: &str, otherwise: Value| state.get(key).filter(|said| Coerce::truthy(Some(*said))).cloned().unwrap_or(otherwise);
        let object = |key: &str| state.get(key).filter(|said| said.is_object()).cloned();
        let list = |key: &str| state.get(key).filter(|said| said.is_array()).cloned();
        json!({
            "host": or_empty("host", json!({})),
            "gpus": or_empty("gpus", json!([])),
            "computeApps": or_empty("computeApps", json!([])),
            "engines": state.get("engines"),
            "cpu": or_empty("cpu", json!({})),
            "platform": or_empty("platform", json!("")),
            "driver": state.get("driver"),
            "llamaNode": or_empty("llamaNode", json!({})),
            "llamaNodes": or_empty("llamaNodes", json!([])),
            "llamaBinaryVersion": or_empty("llamaBinaryVersion", json!("")),
            "prismRuntime": object("prismRuntime").unwrap_or_else(|| json!({})),
            "llamaBinaryMtime": or_empty("llamaBinaryMtime", json!("")),
            "llamaUpdate": object("llamaUpdate").unwrap_or_else(|| json!({})),
            "scoutVersion": or_empty("scoutVersion", json!("")),
            "scoutCommit": state.get("scoutCommit"),
            "autostart": list("autostart"),
            "autostartRequests": object("autostartRequests"),
            "llamaSuspect": object("llamaSuspect"),
            "telemetry": object("telemetry"),
            "entryModels": list("entryModels"),
            "modelCache": object("modelCache"),
            "agentUrl": agent_url,
            "time": or_empty("time", json!(now)),
        })
    }
}
