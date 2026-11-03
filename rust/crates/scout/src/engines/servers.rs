//! The engines' servers the board can turn on and off, as this scout knows them in `state.json`: for each kind, how its server is started (learned from the run of this scout's user that it saw, or from where the kind installs itself), its port, and whether it starts when the machine boots. A known server that is not running is a view of its own, `state: "stopped"`, whose only control is "start". Another user's server, a system service, is named, and left to the operator.

use crate::engines::kind::EngineKind;
use crate::engines::procs::EngineProcs;
use crate::state::ScoutState;
use os::Account;
use rules::Coerce;
use serde_json::{Map, Value, json};
use std::collections::{BTreeMap, BTreeSet};
use std::path::PathBuf;
use std::sync::Arc;

/// The servers.
pub struct EngineServers {
    state: Arc<ScoutState>,
    procs: EngineProcs,
    home: PathBuf,
}

impl EngineServers {
    const KEY: &'static str = "engineServers";
    const BOOT_KEY: &'static str = "engineServersBoot";

    /// The servers of this state.
    pub fn new(state: Arc<ScoutState>, procs: EngineProcs, home: PathBuf) -> Self {
        Self { state, procs, home }
    }

    fn known(&self) -> Map<String, Value> {
        // absent-ok: no entries is no server known.
        self.state.get(Self::KEY).and_then(|rows| rows.as_object().cloned()).unwrap_or_default()
    }

    fn known_of(&self, kind: &str) -> Value {
        self.known().get(kind).filter(|entry| Coerce::truthy(Some(*entry))).cloned().unwrap_or_else(|| json!({}))
    }

    fn remember(&self, kind: &str, fields: Value) {
        let before = self.known_of(kind);
        // absent-ok: an entry of nothing yet gains these fields.
        let mut after = before.as_object().cloned().unwrap_or_default();
        if let Value::Object(new) = fields {
            after.extend(new);
        }
        if Value::Object(after.clone()) == before {
            return;
        }
        self.state.change(|doc| {
            let rows = doc.entry(Self::KEY.to_string()).or_insert_with(|| json!({}));
            if !rows.is_object() {
                *rows = json!({});
            }
            if let Value::Object(rows) = rows {
                rows.insert(kind.to_string(), Value::Object(after));
            }
        });
    }

    /// The scan's views with who runs each server and whether the board may stop it, learning, on the way, how to start it again, and the known servers that are not running, as stopped engines.
    pub fn annotate(&self, kinds: &[Arc<dyn EngineKind>], views: Vec<Value>, listeners: Option<&[Value]>) -> Vec<Value> {
        let by_port: BTreeMap<i64, &Value> = listeners
            .into_iter()
            .flatten()
            .filter_map(|row| row.get("port").and_then(Value::as_i64).map(|port| (port, row)))
            .collect();
        let me = i64::from(Account::uid());
        let mut out = Vec::with_capacity(views.len());
        let mut running = BTreeSet::new();
        for mut view in views {
            let kind_id = Coerce::text(view.get("kind"));
            running.insert(kind_id.clone());
            // absent-ok: `... or 0`: a port nothing listens on has no process to ask of.
            let port = view.get("port").and_then(Value::as_i64).unwrap_or(0);
            // absent-ok: as above.
            let pid = by_port.get(&port).and_then(|row| row.get("pid")).and_then(Value::as_i64).unwrap_or(0);
            let info = if pid > 0 { self.procs.info(pid) } else { None };
            let run_by = info
                .as_ref()
                .map_or("", |info| if info.get("uid").and_then(Value::as_i64) == Some(me) { "user" } else { "other" });
            let autostart = self.known_of(&kind_id).get("autostart") == Some(&Value::Bool(true));
            let answers = matches!(view.get("state").and_then(Value::as_str), Some("ok" | "auth"));
            if let Some(kind) = kinds.iter().find(|kind| kind.id() == kind_id).filter(|_| run_by == "user" && answers)
                && let Some(recipe) = kind.recipe(info.as_ref(), &view)
            {
                self.remember(kind.id(), json!({"recipe": recipe, "port": port}));
            }
            let can_stop = run_by == "user" && pid > 0 && Coerce::truthy(self.known_of(&kind_id).get("recipe"));
            if let Value::Object(fields) = &mut view {
                // absent-ok: a view of no controls offers none.
                let mut controls: Vec<Value> = fields.get("controls").and_then(Value::as_array).cloned().unwrap_or_default();
                if can_stop {
                    controls.push(json!("stop"));
                }
                fields.insert("controls".to_string(), Value::Array(controls));
                fields.insert("runBy".to_string(), json!(run_by));
                fields.insert("autostart".to_string(), json!(autostart));
            }
            out.push(view);
        }
        for kind in kinds.iter().filter(|kind| !running.contains(kind.id())) {
            let entry = self.known_of(kind.id());
            let Some(recipe) = self.recipe_for(kind.as_ref()) else {
                continue;
            };
            let said = [entry.get("port"), recipe.get("port")].into_iter().flatten().find(|port| Coerce::truthy(Some(*port)));
            let port = said.and_then(Coerce::int).unwrap_or_else(|| kind.default_port());
            out.push(json!({
                "kind": kind.id(), "label": kind.label(), "port": port, "listen": "", "state": "stopped",
                "version": "", "models": null, "pids": [], "controls": ["start"],
                "firewall": null, "ramBytes": null, "runBy": "", "autostart": entry.get("autostart") == Some(&Value::Bool(true)),
            }));
        }
        out
    }

    /// How to start the kind's server: the recipe learned from its run, or where the kind is installed. A learned recipe whose binary is gone (the engine moved, as Ollama did from the home to `/usr/local`, 2026-10-24) keeps its arguments and environment and takes the binary from where the kind is installed now.
    pub fn recipe_for(&self, kind: &dyn EngineKind) -> Option<Value> {
        let Some(mut learned) = self.known_of(kind.id()).get("recipe").filter(|recipe| Coerce::truthy(Some(*recipe))).cloned()
        else {
            return kind.installed(&self.home);
        };
        let exe = Coerce::text(learned.get("exe"));
        if !exe.is_empty()
            && !Self::can_run(&exe)
            && let Some(found) =
                kind.installed(&self.home).and_then(|found| found.get("exe").filter(|exe| Coerce::truthy(Some(*exe))).cloned())
            && let Value::Object(fields) = &mut learned
        {
            fields.insert("exe".to_string(), found);
        }
        Some(learned)
    }

    fn can_run(path: &str) -> bool {
        use std::os::unix::fs::PermissionsExt;
        std::fs::metadata(path).is_ok_and(|meta| meta.permissions().mode() & 0o111 != 0)
    }

    /// Starts the server as the recipe says; it starts with the machine from now on. "" or why not: whether it answers is the caller's.
    pub fn start(&self, kind: &dyn EngineKind, port: i64) -> String {
        let Some(recipe) = self.recipe_for(kind) else {
            return format!("how to start {} here is not known", kind.label());
        };
        let reason = kind.start_server(&recipe, &self.procs);
        if reason.is_empty() {
            self.remember(kind.id(), json!({"recipe": recipe, "port": port, "autostart": true}));
        }
        reason
    }

    /// A server that runs now starts with the machine from now on: what a controller gives back to a new scout. It is not started, and a kind this scout does not know is said.
    pub fn keep_at_boot(&self, kinds: &[Arc<dyn EngineKind>], kind_id: &str) -> Result<(), String> {
        if !kinds.iter().any(|kind| kind.id() == kind_id) {
            return Err(format!("no engine {kind_id} here"));
        }
        self.remember(kind_id, json!({"autostart": true}));
        Ok(())
    }

    /// Stops the server; it no longer starts with the machine.
    pub fn stop(&self, kind: &dyn EngineKind, pid: Option<i64>) -> String {
        let reason = kind.stop_server(pid, &self.procs);
        if reason.is_empty() {
            self.remember(kind.id(), json!({"autostart": false}));
        }
        reason
    }

    /// The kinds to start because the machine booted: those started from here and not stopped since, on the first scout start of a boot only (a scout restarted by an update must not bring back what the operator stopped by hand), and never where the machine will not say which boot it is.
    pub fn due_at_boot(&self, boot: &str) -> Vec<String> {
        if boot.is_empty() || self.state.get(Self::BOOT_KEY).as_ref().and_then(Value::as_str) == Some(boot) {
            return Vec::new();
        }
        self.state.change(|doc| doc.insert(Self::BOOT_KEY.to_string(), json!(boot)));
        self.known()
            .iter()
            .filter(|(_, entry)| entry.get("autostart") == Some(&Value::Bool(true)) && Coerce::truthy(entry.get("recipe")))
            .map(|(kind, _)| kind.clone())
            .collect()
    }
}
