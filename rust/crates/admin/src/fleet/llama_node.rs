//! What the board asks of a machine's llama.cpp and vLLM through its scout.

use super::controller_machine::ControllerMachine;
use super::reports::FleetReads;
use super::scout::ScoutCall;
use super::server_cells::ServerCells;
use super::start::{ScoutStart, ScoutVersion};
use crate::app::App;
use crate::domain::runner::VllmRunner;
use crate::store::topology::Topology;
use rules::{AppError, CellId, Coerce};
use serde_json::{Value, json};
use wire::Percent;

/// The machine's servers.
pub struct LlamaNode<'app> {
    app: &'app App,
}

impl<'app> LlamaNode<'app> {
    const VLLM_SCOUT: [u32; 3] = [2, 9, 0];

    /// The servers of `app`.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    fn scout(&self, host_id: &str) -> Result<ScoutCall<'app>, AppError> {
        ScoutCall::of_host(self.app, host_id)
    }

    /// A monitor snapshot of a machine.
    pub fn monitor(&self, host_id: &str, kind: &str) -> Result<Value, AppError> {
        let host_id = Coerce::strip(host_id);
        if host_id.is_empty() {
            return Err(AppError::new("hostId is required"));
        }
        if kind != "nvidia-smi" {
            return Err(AppError::new(format!("unsupported monitor kind: {kind}")));
        }
        Ok(self.scout(host_id)?.read(&format!("/api/monitor/{kind}"), 5))
    }

    /// A llama.cpp update job started on a machine.
    pub fn update(&self, body: &Value) -> Result<Value, AppError> {
        let scout = self.scout(&Coerce::text(body.get("hostId")))?;
        scout.post("/api/llama-node/update", &json!({"tag": Coerce::stripped(body.get("tag"))}), 15)
    }

    /// How a machine's update goes.
    pub fn update_status(&self, host_id: &str) -> Result<Value, AppError> {
        Ok(self.scout(host_id)?.read("/api/llama-node/update-status", 10))
    }

    /// A machine's archived builds.
    pub fn builds(&self, host_id: &str) -> Result<Value, AppError> {
        Ok(self.scout(host_id)?.read("/api/llama-node/builds", 10))
    }

    /// An archived build restored on a machine.
    pub fn restore(&self, body: &Value) -> Result<Value, AppError> {
        let build_id = Coerce::stripped(body.get("id"));
        if build_id.is_empty() {
            return Err(AppError::new("build id is required"));
        }
        self.scout(&Coerce::text(body.get("hostId")))?.post("/api/llama-node/restore", &json!({"id": build_id}), 15)
    }

    /// vLLM on the machines with a scout, for the System panel.
    pub fn vllm(&self, host_id: &str) -> Result<Value, AppError> {
        let rows = FleetReads::of(self.app).hosts();
        let here = ControllerMachine::of(self.app);
        let machines: Vec<Value> = rows
            .iter()
            .map(|host| {
                let id = Coerce::text(host.get("id"));
                let name = Coerce::text(host.get("name"));
                json!({
                    "id": id, "name": if name.is_empty() { id.clone() } else { name },
                    "online": host.get("state").and_then(Value::as_str) == Some("online"),
                    "scoutVersion": Coerce::text(host.get("scoutVersion")),
                    "controllerMachine": here.is_host(host),
                })
            })
            .collect();
        let mut host_id = Coerce::strip(host_id).to_string();
        if host_id.is_empty() {
            host_id = here.host_id(rows.iter());
        }
        if host_id.is_empty() {
            host_id = machines.first().map_or_else(String::new, |machine| Coerce::text(machine.get("id")));
        }
        let doc = json!({"machines": machines, "hostId": host_id, "pinnedDefault": VllmRunner::DEFAULT_VERSION});
        let with = |extra: Value| {
            let mut out = doc.clone();
            Coerce::extend(&mut out, &extra);
            out
        };
        if host_id.is_empty() {
            return Ok(with(json!({"ok": false, "error": "no machine with a scout has reported yet"})));
        }
        let Some(machine) = machines.iter().find(|machine| Coerce::text(machine.get("id")) == host_id) else {
            return Ok(with(json!({"ok": false, "error": format!("no scout has reported for host {host_id}")})));
        };
        let version = Coerce::text(machine.get("scoutVersion"));
        if ScoutVersion::older(&version, &Self::VLLM_SCOUT) {
            let error = format!(
                "{host_id}: its scout {version} is older than 2.9.0, the first to answer for vLLM on its machine — update the scout"
            );
            return Ok(with(json!({"ok": false, "error": error})));
        }
        Ok(with(self.scout(&host_id)?.read("/api/vllm", 10)))
    }

    /// What a cell's server wrote, for the cell window's Log tab.
    pub fn cell_log(&self, cell: &str, lines: &str, run: &str) -> Result<Value, AppError> {
        let id = CellId::read(&json!(Coerce::strip(cell))).ok_or_else(|| AppError::new("cell is required"))?;
        let host_id = ServerCells::of(self.app).host_of(&id);
        if host_id.is_empty() {
            return Err(AppError::with_status(format!("no cell {id}"), 404));
        }
        let scout = self.scout(&host_id)?;
        let have = self
            .app
            .admin
            .change(|doc| Coerce::text(Topology::of(doc).hosts().get(&host_id).and_then(|host| host.get("scoutVersion"))));
        if ScoutVersion::older(&have, &ScoutStart::LEASES_PORTS) {
            let [major, minor, patch] = ScoutStart::LEASES_PORTS;
            let error = format!(
                "{host_id}: its scout {have} keeps the logs of cells by port — update the scout to {major}.{minor}.{patch}"
            );
            return Ok(json!({"ok": false, "hostId": host_id, "cellId": id, "error": error}));
        }
        let mut query = vec![format!("cell={id}")];
        if !Coerce::strip(lines).is_empty() {
            query.push(format!("lines={}", Percent::encode(Coerce::strip(lines))));
        }
        if !Coerce::strip(run).is_empty() {
            query.push(format!("run={}", Percent::encode(Coerce::strip(run))));
        }
        let mut result = scout.read(&format!("/api/llama-node/log?{}", query.join("&")), 10);
        Coerce::put(&mut result, "hostId", json!(host_id));
        Coerce::put(&mut result, "cellId", json!(id));
        Ok(result)
    }

    /// Another vLLM installed on a scout's machine.
    pub fn vllm_update(&self, body: &Value) -> Result<Value, AppError> {
        self.scout(&Coerce::text(body.get("hostId")))?.post(
            "/api/vllm/update",
            &json!({"version": Coerce::stripped(body.get("version"))}),
            15,
        )
    }

    /// How that install goes.
    pub fn vllm_update_status(&self, host_id: &str) -> Result<Value, AppError> {
        Ok(self.scout(host_id)?.read("/api/vllm/update-status", 10))
    }

    /// A machine's "fresh build, crashing cells" banner hidden, for that build.
    pub fn suspect_dismiss(&self, body: &Value) -> Result<Value, AppError> {
        let host_id = Coerce::text(body.get("hostId"));
        let result = self.scout(&host_id)?.post("/api/llama-node/suspect-dismiss", &json!({}), 10)?;
        if Coerce::truthy(result.get("ok")) {
            self.app.admin.saving(|doc| {
                if let Some(host) = Topology::of(doc).hosts().get_mut(&host_id).filter(|host| host.is_object()) {
                    Coerce::put(host, "llamaSuspect", json!({"suspect": false}));
                }
            });
        }
        Ok(result)
    }

    /// The cached model files on a machine's disk.
    pub fn list_cache(&self, host_id: &str) -> Result<Value, AppError> {
        let result = self.scout(host_id)?.read("/api/llama-node/list-cache", 5);
        if result.get("ok").is_some_and(|said| !Coerce::truthy(Some(said))) {
            return Ok(json!({"ok": false, "hostId": host_id, "error": Coerce::text(result.get("error")), "models": []}));
        }
        Ok(json!({"ok": true, "hostId": host_id, "models": result.get("models").cloned().unwrap_or_else(|| json!([]))}))
    }

    /// A machine asked to delete its downloaded model cache, a running model kept.
    pub fn purge_cache(&self, body: &Value) -> Result<Value, AppError> {
        let host_id = Coerce::stripped(body.get("hostId"));
        let result = self.scout(&host_id)?.post("/api/llama-node/purge-cache", &json!({}), 30)?;
        Ok(json!({"ok": Coerce::truthy(result.get("ok")), "hostId": host_id, "result": result}))
    }
}
