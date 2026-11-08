//! What this scout says about its machine, in three shapes: `public()`, everything, for `/api/state`; `heartbeat()`, the body of a heartbeat: the same facts under the same names; `pairing()`, what the scout's page shows and the controller reads first when it adds the scout: open even behind a token. One set of names for all of them: the controller keeps whichever report arrived last, and a field only one of them carried was erased by the other every minute.

use crate::cells::Cells;
use crate::cells::autostart::Autostart;
use crate::cells::suspect::CrashSuspect;
use crate::config::ScoutConfig;
use crate::driver::DriverFacts;
use crate::engines::ForeignEngines;
use crate::entry::machine_models::MachineModels;
use crate::identity::HostIdentity;
use crate::machine::Machine;
use crate::own_release::OwnRelease;
use crate::runtimes::builds::LlamaBuilds;
use crate::state::ScoutState;
use crate::telemetry::Telemetry;
use os::Host;
use os::clock::Clock;
use rules::Coerce;
use serde_json::{Map, Value, json};
use std::sync::Arc;

/// What the report asks of the other parts.
pub struct Report {
    /// The settings.
    pub config: Arc<ScoutConfig>,
    /// The memory.
    pub state: Arc<ScoutState>,
    /// The machine.
    pub machine: Arc<Machine>,
    /// The cells.
    pub cells: Arc<Cells>,
    /// The builds.
    pub builds: Arc<LlamaBuilds>,
    /// The autostart.
    pub autostart: Arc<Autostart>,
    /// The suspect.
    pub suspect: Arc<CrashSuspect>,
    /// The telemetry.
    pub telemetry: Arc<Telemetry>,
    /// The name the board shows follows the machine's hostname.
    pub identity: Arc<HostIdentity>,
    /// Ollama, LM Studio on this machine: their last scan.
    pub engines: Arc<ForeignEngines>,
    /// The NVIDIA driver as the next boot will meet it.
    pub driver: Arc<DriverFacts>,
    /// The machine's models as its entry lists them.
    pub entry_models: Arc<MachineModels>,
    /// The clocks.
    pub clock: Arc<dyn Clock>,
}

impl Report {
    /// The version this scout reports: the floor a controller checks what it can ask against. It stands still, a release is named by its commit.
    pub const VERSION: &'static str = "2.48.0";
    const DEFAULT_PORT: i64 = 8092;

    /// The words Python's `sys.platform` says.
    fn platform() -> &'static str {
        match std::env::consts::OS {
            "macos" => "darwin",
            other => other,
        }
    }

    /// Everything this scout reports, for `/api/state`.
    pub fn public(&self) -> Map<String, Value> {
        let version = self.builds.binary_version();
        let mut out = Map::new();
        out.insert("service".to_string(), json!("caravan-scout"));
        out.insert("scoutVersion".to_string(), json!(Self::VERSION));
        if let Some(release) = OwnRelease::running() {
            out.insert("scoutCommit".to_string(), json!(release.commit()));
        }
        out.insert("llamaBinaryVersion".to_string(), json!(version));
        out.insert("prismRuntime".to_string(), self.cells.prism.facts());
        out.insert("llamaBinaryMtime".to_string(), json!(self.builds.binary_mtime()));
        out.insert("llamaUpdate".to_string(), self.builds.status_slim());
        // Cells crashing soon after a fresh `llama.cpp` build: the board's banner offers a rollback.
        out.insert("llamaSuspect".to_string(), self.suspect.verdict(Some(&version)));
        // That this machine is sampled second by second, and how: the controller asks `/api/telemetry` only of a scout that says so.
        out.insert("telemetry".to_string(), self.telemetry.describe());
        out.insert(
            "host".to_string(),
            json!({"id": self.config.get("hostId"), "name": self.identity.name(), "hostname": Host::name(), "ip": self.machine.address()}),
        );
        out.insert("controllerUrl".to_string(), self.config.get("controllerUrl").unwrap_or(Value::Null));
        out.insert("gpus".to_string(), json!(self.machine.gpus()));
        // Why `nvidia-smi` named no card, in its words: "" when it named them or is not installed.
        out.insert("gpuError".to_string(), json!(self.machine.gpu_error()));
        out.insert("computeApps".to_string(), json!(self.machine.compute_apps()));
        // Model engines on this machine that are not its cells: `null` before the first scan, `[]` when none were found.
        out.insert("engines".to_string(), self.engines.views());
        out.insert("cpu".to_string(), self.machine.cpu_ram());
        out.insert("platform".to_string(), json!(Self::platform()));
        // The NVIDIA driver as the next boot will meet it: `null` where there is no NVIDIA driver, or not Linux.
        out.insert("driver".to_string(), self.driver.facts());
        out.insert("heartbeat".to_string(), self.state.get("heartbeat").unwrap_or_else(|| json!({})));
        out.insert("llamaNode".to_string(), self.cells.first_view());
        out.insert("llamaNodes".to_string(), Value::Array(self.cells.views()));
        // The ports that start with the machine, stopped ones too: the board shows ↟ on a parked cell as well.
        out.insert("autostart".to_string(), json!(self.autostart.cells()));
        // The start request kept for each of them: a controller that did not start a cell keeps its record from it, so that the cell stays on its board when it stops.
        out.insert("autostartRequests".to_string(), self.autostart.requests());
        // The machine's models as `GET /v1/models` lists them: a controller names a model of this machine by its name, as a client of the entry does.
        out.insert("entryModels".to_string(), json!(self.entry_models.listing()));
        // The model cache: how many of the last models it keeps, what it holds, what of that this scout did not download, what the disk has left.
        out.insert("modelCache".to_string(), Value::Object(self.cells.cache_facts()));
        out.insert("time".to_string(), json!(self.clock.epoch() as i64));
        out
    }

    /// What the scout's page shows, and nothing more: open even when a fleet token closes the rest. The controller reads this first when it adds the scout: that a scout answers at the address, which version, whether it holds a token. No controller reply here, and nothing a caller could act on.
    pub fn pairing(&self) -> Value {
        let gpus: Vec<String> = self
            .machine
            .gpus()
            .iter()
            .map(|gpu| {
                let name = [gpu.get("name"), gpu.get("model")].into_iter().flatten().find(|word| Coerce::truthy(Some(*word)));
                name.map_or_else(|| "GPU".to_string(), |name| Coerce::text(Some(name)))
            })
            .collect();
        let nodes = self.cells.views();
        let running = nodes.iter().filter(|node| Coerce::truthy(node.get("running"))).count();
        let beat = self.state.get("heartbeat").filter(|beat| beat.is_object()).unwrap_or_else(|| json!({}));
        let shown: Map<String, Value> = ["state", "lastAt", "error"]
            .iter()
            .filter_map(|key| beat.get(*key).map(|value| ((*key).to_string(), value.clone())))
            .collect();
        let port = self
            .config
            .get("listenPort")
            .filter(|port| Coerce::truthy(Some(port)))
            .and_then(|port| Coerce::int(&port))
            .unwrap_or(Self::DEFAULT_PORT);
        json!({
            "service": "caravan-scout",
            "version": Self::VERSION,
            "hostId": self.config.get("hostId"),
            "hostname": Host::name(),
            "ip": self.machine.address(),
            // What the operator types on the controller: address and this port.
            "port": port,
            "platform": Self::platform(),
            "gpus": gpus,
            "cells": {"running": running, "total": nodes.len()},
            "controllerUrl": self.config.text("controllerUrl"),
            "tokenRequired": !self.config.token().is_empty(),
            "heartbeat": shown,
        })
    }

    /// The heartbeat's body: the same facts as `public()`, under the same names, minus what only the scout's own API needs.
    pub fn heartbeat(&self) -> Value {
        const KEPT: [&str; 19] = [
            "host",
            "gpus",
            "gpuError",
            "computeApps",
            "engines",
            "cpu",
            "platform",
            "driver",
            "llamaNode",
            "llamaNodes",
            "llamaBinaryVersion",
            "llamaBinaryMtime",
            "llamaUpdate",
            "llamaSuspect",
            "telemetry",
            "scoutVersion",
            "scoutCommit",
            "prismRuntime",
            "autostart",
        ];
        const LAST: [&str; 3] = ["autostartRequests", "entryModels", "modelCache"];
        let state = self.public();
        let mut out = Map::new();
        for key in KEPT.iter().chain(LAST.iter()) {
            if let Some(value) = state.get(*key) {
                out.insert((*key).to_string(), value.clone());
            }
        }
        let ip = state.get("host").and_then(|host| host.get("ip")).map_or_else(String::new, |ip| Coerce::text(Some(ip)));
        out.insert("agentUrl".to_string(), json!(format!("http://{ip}:{}", self.config.text("listenPort"))));
        out.insert("time".to_string(), state.get("time").cloned().unwrap_or(Value::Null));
        Value::Object(out)
    }
}
