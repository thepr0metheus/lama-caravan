//! What each path does: tables of what answers it, one per way a path is answered. A test holds them to the rows of the route table, both ways.

use crate::cells::Cells;
use crate::cells::table::CellTable;
use crate::engines::ForeignEngines;
use crate::errors::AppError;
use crate::scout::Scout;
use rules::Coerce;
use serde_json::{Map, Value, json};
use std::collections::BTreeMap;
use std::sync::Arc;
use std::time::Duration;

/// A POST's body, read only by a route that needs one: a body that does not parse fails only the routes that read it.
pub type BodyReader<'a> = &'a mut dyn FnMut() -> Result<Map<String, Value>, AppError>;
/// A GET's first values of its query.
pub type Query = BTreeMap<String, String>;

/// Answers a GET.
pub type GetHandler = fn(&Arc<Scout>) -> Result<Value, AppError>;
/// Answers a GET with a query.
pub type QueryHandler = fn(&Arc<Scout>, &Query) -> Result<Value, AppError>;
/// Answers a POST: the answer, and its status.
pub type PostHandler = fn(&Arc<Scout>, BodyReader<'_>) -> Result<(Value, u16), AppError>;

/// The tables.
pub struct Handlers;

impl Handlers {
    /// The open GETs and those behind the token: which is which, the route table says.
    pub const GETS: [(&'static str, GetHandler); 19] = [
        ("/api/pairing", |scout| Ok(scout.report.pairing())),
        ("/api/health", Self::health),
        ("/api/state", |scout| Ok(Value::Object(scout.report.public()))),
        ("/api/llama-node/status", |scout| Ok(json!({"ok": true, "nodes": scout.cells.views()}))),
        ("/api/monitor/nvidia-smi", |scout| Ok(scout.machine.nvidia_smi())),
        ("/api/monitor/btop", |scout| Ok(scout.machine.btop_snapshot())),
        ("/api/host/processes", |scout| Ok(scout.machine.top_processes())),
        ("/api/host/driver", |scout| Ok(scout.driver_packages.facts())),
        ("/api/host/driver/install-status", |scout| Ok(scout.driver_install.status())),
        ("/api/host/listeners", |scout| Ok(scout.machine.listeners())),
        ("/api/llama-node/configs", |scout| Ok(json!({"ok": true, "configs": scout.configs.listing()}))),
        ("/api/llama-node/update-status", |scout| Ok(scout.builds.status())),
        ("/api/llama-node/builds", |scout| Ok(scout.builds.archive())),
        ("/api/llama-node/list-cache", |scout| Ok(json!({"ok": true, "models": scout.cells.models.listing()}))),
        ("/api/llama-node/cache", |scout| Ok(Self::with_ok(scout.cells.cache_facts()))),
        ("/api/vllm", |scout| Ok(scout.vllm.info())),
        ("/api/vllm/update-status", |scout| Ok(scout.vllm.job_status())),
        ("/openapi.json", |_| Err(AppError::with_status("the server answers this itself", 500))),
        ("/", |_| Err(AppError::with_status("the server answers this itself", 500))),
    ];

    /// The GETs asked with a query.
    pub const QUERIES: [(&'static str, QueryHandler); 2] = [
        ("/api/llama-node/log", |scout, query| {
            Ok(scout.cells.log(
                query.get("cell").map(String::as_str),
                query.get("lines").map(String::as_str),
                query.get("run").map_or("", String::as_str),
            ))
        }),
        ("/api/telemetry", |scout, query| Ok(scout.telemetry.since(query.get("since").map(String::as_str)))),
    ];

    /// The POSTs behind the token.
    pub const POSTS: [(&'static str, PostHandler); 27] = [
        ("/api/heartbeat", |scout, _| Ok((scout.heartbeat.once()?, 200))),
        ("/api/unpair", |scout, _| Ok((scout.heartbeat.unpair()?, 200))),
        ("/api/scout/update", |scout, body| {
            let asked = body()?;
            // absent-ok: an empty word is what the update refuses, in words.
            let word = |key: &str| asked.get(key).and_then(Value::as_str).unwrap_or_default().to_string();
            Ok((scout.take_new_release(&word("commit"), &word("sha256"))?, 200))
        }),
        ("/api/llama-node/start", Self::start),
        ("/api/llama-node/autostart", Self::autostart),
        ("/api/host/reboot", |_, _| Ok(Power::issue("reboot"))),
        ("/api/host/driver/install", Self::driver_install),
        ("/api/host/poweroff", |_, _| Ok(Power::issue("poweroff"))),
        ("/api/llama-node/stop", Self::stop),
        ("/api/llama-node/update", |scout, body| Ok((scout.builds.start_update(&Value::Object(body()?))?, 200))),
        ("/api/vllm/update", |scout, body| Ok((scout.vllm.start_update(&Value::Object(body()?))?, 200))),
        ("/api/llama-node/restore", Self::restore),
        ("/api/llama-node/suspect-dismiss", |scout, _| Ok((scout.suspect.dismiss(), 200))),
        ("/api/llama-node/purge-cache", |scout, _| {
            scout.cells.models.relocation.refuse_while_moving()?;
            Ok((Self::ok_with(&scout.cells.purge_models_safely()), 200))
        }),
        ("/api/llama-node/cache/keep", |scout, body| {
            Ok((Self::ok_with(&scout.cells.keeper.set_keep(body()?.get("keep").unwrap_or(&Value::Null))?), 200))
        }),
        ("/api/llama-node/cache/budget", |scout, body| {
            Ok((Self::ok_with(&scout.cells.keeper.set_budget(body()?.get("budgetBytes").unwrap_or(&Value::Null))?), 200))
        }),
        ("/api/llama-node/cache/dir", |scout, body| {
            let asked = body()?;
            let said = |key: &str| asked.get(key).cloned().unwrap_or(Value::Null);
            Ok((Self::ok_with(&scout.cells.keeper.move_to(&said("path"), &said("how"))?), 200))
        }),
        ("/api/llama-node/cache/work", |scout, body| {
            let asked = body()?;
            let said = |key: &str| asked.get(key).cloned().unwrap_or(Value::Null);
            Ok((Self::ok_with(&scout.cells.work_keeper.set_work(&said("path"), &said("how"))?), 200))
        }),
        ("/api/llama-node/cache/work/budget", |scout, body| {
            Ok((Self::ok_with(&scout.cells.work_keeper.set_budget(body()?.get("budgetBytes").unwrap_or(&Value::Null))?), 200))
        }),
        ("/api/llama-node/cache/off", |scout, body| {
            let asked = body()?;
            let said = |key: &str| asked.get(key).cloned().unwrap_or(Value::Null);
            Ok((Self::ok_with(&scout.cells.keeper.set_off(&said("off"), &said("library"))?), 200))
        }),
        ("/api/llama-node/cache/delete-foreign", |scout, body| {
            Ok((Self::ok_with(&scout.cells.keeper.delete_foreign(body()?.get("expectBytes"))?), 200))
        }),
        ("/api/llama-node/configs/delete", Self::delete_config),
        ("/api/engines/unload", |scout, body| Self::engine(scout, "unload", body)),
        ("/api/engines/delete", |scout, body| Self::engine(scout, "delete", body)),
        ("/api/engines/start", |scout, body| Self::server(scout, "start", body)),
        ("/api/engines/stop", |scout, body| Self::server(scout, "stop", body)),
        ("/api/engines/keep-at-boot", |scout, body| Self::keep_at_boot(scout, body)),
    ];

    fn health(scout: &Arc<Scout>) -> Result<Value, AppError> {
        Ok(json!({
            "ok": true,
            "service": "caravan-scout",
            "version": crate::report::Report::VERSION,
            "tokenRequired": !scout.config.token().is_empty(),
            "time": scout.clock.epoch() as i64,
        }))
    }

    fn with_ok(fields: Map<String, Value>) -> Value {
        let mut out = Map::new();
        out.insert("ok".to_string(), json!(true));
        out.extend(fields);
        Value::Object(out)
    }

    fn ok_with(fields: &Value) -> Value {
        // absent-ok: what these parts answer is an object; anything else adds nothing to `ok`.
        Self::with_ok(fields.as_object().cloned().unwrap_or_default())
    }

    fn start(scout: &Arc<Scout>, body: BodyReader<'_>) -> Result<(Value, u16), AppError> {
        let payload = body()?;
        let result = Cells::start(&scout.cells, payload.clone())?;
        let ok = result.get("ok") == Some(&Value::Bool(true));
        if ok {
            scout.autostart.refresh(result.get("cellId"), &Value::Object(payload));
        }
        Ok((result, if ok { 200 } else { 400 }))
    }

    fn autostart(scout: &Arc<Scout>, body: BodyReader<'_>) -> Result<(Value, u16), AppError> {
        let fields = body()?;
        Ok((scout.autostart.set(fields.get("cellId"), Coerce::truthy(fields.get("enabled")), fields.get("payload"))?, 200))
    }

    fn driver_install(scout: &Arc<Scout>, body: BodyReader<'_>) -> Result<(Value, u16), AppError> {
        let fields = body()?;
        Ok((scout.driver_packages.install(&Coerce::text(fields.get("package")), &scout.driver_install)?, 200))
    }

    /// A stop of the cell `cellId` names; a request that names none stops every cell of this scout.
    fn stop(scout: &Arc<Scout>, body: BodyReader<'_>) -> Result<(Value, u16), AppError> {
        let fields = body()?;
        let id = match fields.get("cellId").filter(|said| !said.is_null()) {
            Some(said) => Some(CellTable::named(Some(said))?),
            None => None,
        };
        Ok((scout.cells.stop(id.as_deref()), 200))
    }

    fn restore(scout: &Arc<Scout>, body: BodyReader<'_>) -> Result<(Value, u16), AppError> {
        let fields = body()?;
        let id = fields.get("id").filter(|id| Coerce::truthy(Some(*id))).or_else(|| fields.get("restoreId"));
        Ok((scout.builds.restore(id)?, 200))
    }

    fn delete_config(scout: &Arc<Scout>, body: BodyReader<'_>) -> Result<(Value, u16), AppError> {
        let fields = body()?;
        scout.configs.delete(&Coerce::text(fields.get("filename")))?;
        Ok((json!({"ok": true}), 200))
    }

    fn engine(scout: &Arc<Scout>, op: &str, body: BodyReader<'_>) -> Result<(Value, u16), AppError> {
        let fields = body()?;
        Ok((
            ForeignEngines::act(
                &scout.engines,
                op,
                &Coerce::text(fields.get("kind")),
                fields.get("port"),
                &Coerce::text(fields.get("model")),
            )?,
            200,
        ))
    }

    fn keep_at_boot(scout: &Arc<Scout>, body: BodyReader<'_>) -> Result<(Value, u16), AppError> {
        let fields = body()?;
        Ok((scout.engines.keep_at_boot(&Coerce::text(fields.get("kind")))?, 200))
    }

    fn server(scout: &Arc<Scout>, op: &str, body: BodyReader<'_>) -> Result<(Value, u16), AppError> {
        let fields = body()?;
        Ok((ForeignEngines::serve(&scout.engines, op, &Coerce::text(fields.get("kind")), fields.get("port"))?, 200))
    }
}

/// Reboots or powers off this machine when the controller asks. Cells are not stopped first: systemd takes them down with the machine and autostart brings back what should come back. Poweroff is the one-way door: nothing on the board can switch this box on again, so it is separated from reboot by its own path rather than a flag in a body.
pub struct Power;

impl Power {
    fn issue(action: &str) -> (Value, u16) {
        crate::log::Log::line(&format!("[host] {action} requested by the controller"));
        let commands = crate::commands::SystemCommands;
        let ran = crate::commands::Commands::run(&commands, &["sudo", "-n", "systemctl", action], Duration::from_secs(10));
        match ran {
            Ok(ran) if ran.ok() => (json!({"ok": true, "detail": format!("{action} issued")}), 200),
            Ok(ran) => {
                let said = if ran.stderr.trim().is_empty() { ran.stdout.trim() } else { ran.stderr.trim() };
                let words = if said.is_empty() { format!("exit {}", ran.code_word()) } else { said.to_string() };
                let hint = if words.to_lowercase().contains("password") {
                    format!(" — passwordless sudo for `systemctl {action}` is required")
                } else {
                    String::new()
                };
                (json!({"ok": false, "error": format!("{action} refused: {words}{hint}")}), 500)
            }
            // The box is already going down: that is success.
            Err(crate::commands::NoAnswer::TimedOut) => (json!({"ok": true, "detail": format!("{action} issued")}), 200),
            Err(error) => (json!({"ok": false, "error": format!("{action} failed: {}", error.words("sudo"))}), 500),
        }
    }
}
