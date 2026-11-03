//! A model of an engine next to the cells unloaded or deleted from the board, and the engine's server started or stopped.

use super::reports::FleetReads;
use super::scout::ScoutCall;
use crate::app::App;
use crate::domain::engine::EngineReport;
use crate::store::topology::Topology;
use rules::{AppError, Coerce, PyRepr};
use serde_json::{Value, json};

/// The acts of this controller on the machines' engines.
pub struct EngineActions<'app> {
    app: &'app App,
}

impl<'app> EngineActions<'app> {
    const TIMEOUT: u64 = 15;

    /// The acts of `app`.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    fn engine(&self, host_id: &str, kind: &str) -> Result<Value, AppError> {
        let hosts = FleetReads::of(self.app).hosts();
        let host = hosts.iter().find(|host| Coerce::text(host.get("id")) == host_id);
        let host = host.ok_or_else(|| AppError::with_status(format!("no scout has reported for host {host_id}"), 404))?;
        let engines = host.get("engines").and_then(Value::as_array).into_iter().flatten();
        let mut engines = engines;
        let engine = engines.find(|engine| engine.get("kind").and_then(Value::as_str) == Some(kind));
        engine.cloned().ok_or_else(|| AppError::with_status(format!("{host_id} reports no {kind}"), 404))
    }

    /// Unload a model of an engine on a machine with a scout, or delete it.
    pub fn act(&self, host_id: Option<&Value>, op: &str, kind: Option<&Value>, model: Option<&Value>) -> Result<Value, AppError> {
        let (host_id, kind, model) = (Coerce::stripped(host_id), Coerce::stripped(kind), Coerce::stripped(model));
        if !EngineReport::ACTIONS.contains(&op) {
            return Err(AppError::new(format!("unknown engine action {}", PyRepr::of(op))));
        }
        if host_id.is_empty() || kind.is_empty() || model.is_empty() {
            return Err(AppError::new("hostId, kind and model are required"));
        }
        let engine = self.engine(&host_id, &kind)?;
        let asked = json!({"kind": kind, "port": engine.get("port"), "model": model});
        let answer = ScoutCall::of_host(self.app, &host_id)?.post(&format!("/api/engines/{op}"), &asked, Self::TIMEOUT)?;
        self.keep(&host_id, &answer);
        Ok(json!({"ok": true, "hostId": host_id, "kind": kind, "model": model, "op": op}))
    }

    /// The engine's server started, or stopped (scout 2.16+).
    pub fn serve(&self, host_id: Option<&Value>, op: &str, kind: Option<&Value>) -> Result<Value, AppError> {
        let (host_id, kind) = (Coerce::stripped(host_id), Coerce::stripped(kind));
        if !EngineReport::SERVER_ACTIONS.contains(&op) {
            return Err(AppError::new(format!("unknown engine action {}", PyRepr::of(op))));
        }
        if host_id.is_empty() || kind.is_empty() {
            return Err(AppError::new("hostId and kind are required"));
        }
        let engine = self.engine(&host_id, &kind)?;
        let asked = json!({"kind": kind, "port": engine.get("port")});
        let answer = ScoutCall::of_host(self.app, &host_id)?.post(&format!("/api/engines/{op}"), &asked, Self::TIMEOUT)?;
        self.keep(&host_id, &answer);
        Ok(json!({"ok": true, "hostId": host_id, "kind": kind, "op": op}))
    }

    /// An engine that runs now starts with the machine from now on. A start would refuse it: it runs.
    pub fn keep_at_boot(&self, host_id: &str, kind: &str) -> Result<Value, AppError> {
        ScoutCall::of_host(self.app, host_id)?.post("/api/engines/keep-at-boot", &json!({"kind": kind}), Self::TIMEOUT)
    }

    /// The engines the scout answered with, into the machine's record at once: the board shows the act under way on its next read.
    fn keep(&self, host_id: &str, answer: &Value) {
        let engines = EngineReport::engines(answer.get("engines"));
        if engines.is_null() {
            return;
        }
        self.app.admin.saving(|doc| {
            if let Some(record) = Topology::of(doc).hosts().get_mut(host_id).filter(|record| record.is_object()) {
                Coerce::put(record, "engines", engines);
            }
        });
    }
}
