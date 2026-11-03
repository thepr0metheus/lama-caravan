//! The machines and their scouts.

use super::asked::Asked;
use crate::app::App;
use crate::fleet::backups::ConfigBackups;
use crate::fleet::cell_ops::CellOps;
use crate::fleet::clients::ClientDesk;
use crate::fleet::engine_actions::EngineActions;
use crate::fleet::engine_outputs::EngineOutputs;
use crate::fleet::host_power::HostPower;
use crate::fleet::llama_node::LlamaNode;
use crate::fleet::machine_cells::MachineCells;
use crate::fleet::model_cache::ModelCache;
use crate::fleet::port_exclusions::PortExclusions;
use crate::fleet::reports::FleetReads;
use crate::fleet::scout_bundle::ScoutBundle;
use crate::fleet::scout_pairing::ScoutPairing;
use crate::fleet::scout_scan::ScoutScan;
use crate::fleet::server_cells::ServerCells;
use crate::fleet::start::ScoutStart;
use crate::store::topology::Topology;
use crate::web::{Exchange, Routes};
use plumbing::Log;
use rules::{AppError, Coerce};
use serde_json::{Value, json};

/// The routes.
pub struct FleetRoutes;

impl FleetRoutes {
    /// The table.
    pub const ROUTES: Routes = Routes {
        get: &[
            ("/api/machines", Self::machines),
            ("/api/topology/client-monitor", Self::client_monitor),
            ("/api/fleet/llama-update-status", Self::llama_update_status),
            ("/api/fleet/vllm", Self::vllm),
            ("/api/fleet/vllm/update-status", Self::vllm_update_status),
            ("/api/fleet/llama-builds", Self::llama_builds),
            ("/api/topology/client-llama/configs", Self::configs),
            ("/api/topology/client-llama/list-cache", Self::list_cache),
            ("/api/cell-log", Self::cell_log),
            ("/api/fleet/cell-start", Self::cell_start),
            ("/api/port-exclusions", Self::exclusions),
            ("/scout/install.sh", Self::scout_installer),
            ("/scout/bundle.tar.gz", Self::scout_bundle_file),
            ("/api/fleet/scout-release", Self::scout_release),
        ],
        post: &[
            ("/api/port-exclusions", Self::set_exclusions),
            ("/api/topology/client-heartbeat", Self::heartbeat),
            ("/api/fleet/llama-update", Self::llama_update),
            ("/api/fleet/llama-restore", Self::llama_restore),
            ("/api/fleet/vllm/update", Self::vllm_update),
            ("/api/fleet/llama-suspect-dismiss", Self::suspect_dismiss),
            ("/api/host/reboot", Self::reboot),
            ("/api/host/poweroff", Self::poweroff),
            ("/api/host/power-schedule", Self::power_schedule),
            ("/api/topology/client-llama/start", Self::start),
            ("/api/topology/client-llama/stop", Self::stop),
            ("/api/topology/client-llama/purge-cache", Self::purge_cache),
            ("/api/topology/client-llama/cache-keep", Self::cache_keep),
            ("/api/topology/client-llama/cache-off", Self::cache_off),
            ("/api/topology/client-llama/cache-clear", Self::cache_clear),
            ("/api/topology/client-llama/cache-budget", Self::cache_budget),
            ("/api/topology/client-llama/cache-dir", Self::cache_dir),
            ("/api/topology/client-llama/cache-work", Self::cache_work),
            ("/api/topology/client-llama/cache-work-budget", Self::cache_work_budget),
            ("/api/topology/client-llama/cache-delete-foreign", Self::cache_delete_foreign),
            ("/api/topology/client-llama/configs/save", Self::configs_save),
            ("/api/topology/client-llama/configs/delete", Self::configs_delete),
            ("/api/fleet/scout-update", Self::scout_update),
            ("/api/topology/scout/connect", Self::scout_connect),
            ("/api/topology/scout/scan", Self::scout_scan),
            ("/api/topology/scout/disconnect", Self::scout_disconnect),
            ("/api/topology/host/move-cells", Self::move_cells),
            ("/api/topology/client/create", Self::client_create),
            ("/api/topology/client/delete", Self::client_delete),
            ("/api/topology/client/agent/delete", Self::agent_delete),
            ("/api/topology/client/agent-alias", Self::agent_alias),
            ("/api/engine-outputs/expose", Self::engine_expose),
            ("/api/engines/unload", Self::engines_act),
            ("/api/engines/delete", Self::engines_act),
            ("/api/engines/start", Self::engines_serve),
            ("/api/engines/stop", Self::engines_serve),
        ],
        delete: &[],
    };

    fn scout_installer(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        let script = ScoutBundle::of(app).installer(&h.field_or_empty("Host"))?;
        h.send_text(200, "text/x-shellscript; charset=utf-8", &script, "no-store");
        Ok(())
    }

    fn scout_bundle_file(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        let bundle = ScoutBundle::of(app);
        bundle.facts().ok_or_else(ScoutBundle::none)?;
        h.send_file(&bundle.file(), "application/gzip");
        Ok(())
    }

    fn scout_release(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        let said = ScoutBundle::of(app).status(&Asked::word(h, "hostId"), &h.field_or_empty("Host"))?;
        h.ok(&said);
        Ok(())
    }

    fn scout_update(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        h.ok(&ScoutBundle::of(app).update(&Asked::said(&body, "hostId"))?);
        Ok(())
    }

    fn machines(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        h.ok(&json!({"machines": FleetReads::of(app).machines()}));
        Ok(())
    }

    fn client_monitor(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        let kind = Coerce::strip(&h.parsed.param_or("kind", "nvidia-smi")).to_string();
        h.ok(&LlamaNode::of(app).monitor(&Asked::word(h, "hostId"), &kind)?);
        Ok(())
    }

    fn llama_update_status(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        h.ok(&LlamaNode::of(app).update_status(&Asked::word(h, "hostId"))?);
        Ok(())
    }

    fn vllm(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        h.ok(&LlamaNode::of(app).vllm(&Asked::word(h, "hostId"))?);
        Ok(())
    }

    fn vllm_update_status(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        h.ok(&LlamaNode::of(app).vllm_update_status(&Asked::word(h, "hostId"))?);
        Ok(())
    }

    fn llama_builds(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        h.ok(&LlamaNode::of(app).builds(&Asked::word(h, "hostId"))?);
        Ok(())
    }

    fn configs(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        h.ok(&ConfigBackups::of(app).list(&Asked::word(h, "hostId"))?);
        Ok(())
    }

    fn list_cache(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        h.ok(&LlamaNode::of(app).list_cache(&Asked::word(h, "hostId"))?);
        Ok(())
    }

    /// The start of a cell as its settings are saved now, for its machine: what its watchdog and its boot start. `request` is null when there is no such cell here.
    fn cell_start(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        let host = h.parsed.param_or("hostId", "");
        // absent-ok: a port that is no number is a cell of none, and there is none.
        let port = h.parsed.param_or("port", "").trim().parse().unwrap_or(0);
        h.ok(&CellOps::of(app).start_request(&host, port));
        Ok(())
    }

    fn cell_log(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        let said = LlamaNode::of(app).cell_log(
            &Asked::word(h, "hostId"),
            &Asked::word(h, "port"),
            &Asked::word(h, "lines"),
            &Asked::word(h, "run"),
        )?;
        h.ok(&said);
        Ok(())
    }

    fn exclusions(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        let desk = PortExclusions::of(app);
        let mut out = json!({"ok": true, "exclusions": desk.list()});
        if h.parsed.query.contains("scan=1") {
            Coerce::put(&mut out, "scan", desk.scan_foreign());
        }
        h.ok(&out);
        Ok(())
    }

    fn set_exclusions(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        h.ok(&PortExclusions::of(app).set(&body)?);
        Ok(())
    }

    fn heartbeat(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        let host = FleetReads::of(app).record(&body, false)?.unwrap_or(Value::Null);
        let slots = app.admin.change(|doc| Topology::of(doc).slots().clone());
        let cells = MachineCells::of(app, &slots, &Coerce::text(host.get("id")));
        h.ok(&json!({"ok": true, "host": host, "cells": cells}));
        Ok(())
    }

    fn llama_update(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        h.ok(&LlamaNode::of(app).update(&body)?);
        Ok(())
    }

    fn llama_restore(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        h.ok(&LlamaNode::of(app).restore(&body)?);
        Ok(())
    }

    fn vllm_update(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        h.ok(&LlamaNode::of(app).vllm_update(&body)?);
        Ok(())
    }

    fn suspect_dismiss(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        h.ok(&LlamaNode::of(app).suspect_dismiss(&body)?);
        Ok(())
    }

    fn host_named(body: &Value) -> String {
        let said = Coerce::text(body.get("hostId"));
        if said.is_empty() { "?".to_string() } else { said }
    }

    fn reboot(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        Log::line(&format!("[host] reboot requested for {}", Self::host_named(&body)));
        h.ok(&HostPower::of(app).act(&body, "reboot")?);
        Ok(())
    }

    fn poweroff(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        Log::line(&format!("[host] POWEROFF requested for {} — not reversible from here", Self::host_named(&body)));
        h.ok(&HostPower::of(app).act(&body, "poweroff")?);
        Ok(())
    }

    fn power_schedule(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        let enabled = Coerce::truthy(body.get("schedule").and_then(|schedule| schedule.get("enabled")));
        Log::line(&format!("[host] power-schedule {} for {}", if enabled { "ENABLED" } else { "set" }, Self::host_named(&body)));
        h.ok(&HostPower::of(app).set_schedule(&body)?);
        Ok(())
    }

    fn start(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        h.ok(&ScoutStart::of(app).start(&body)?);
        Ok(())
    }

    fn stop(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        h.ok(&ScoutStart::of(app).stop(&body)?);
        Ok(())
    }

    fn purge_cache(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        h.ok(&LlamaNode::of(app).purge_cache(&body)?);
        Ok(())
    }

    fn cache_keep(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        h.ok(&ModelCache::of(app).keep(&Coerce::text(body.get("hostId")), body.get("keep"))?);
        Ok(())
    }

    fn cache_off(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        h.ok(&ModelCache::of(app).off(&Coerce::text(body.get("hostId")), body.get("off"), body.get("library"))?);
        Ok(())
    }

    fn cache_clear(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        h.ok(&ModelCache::of(app).clear(&Coerce::text(body.get("hostId")))?);
        Ok(())
    }

    fn cache_budget(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        h.ok(&ModelCache::of(app).budget(&Coerce::text(body.get("hostId")), body.get("budgetBytes"))?);
        Ok(())
    }

    fn cache_dir(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        h.ok(&ModelCache::of(app).move_to(&Coerce::text(body.get("hostId")), body.get("path"), body.get("how"))?);
        Ok(())
    }

    fn cache_work(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        h.ok(&ModelCache::of(app).work(&Coerce::text(body.get("hostId")), body.get("path"), body.get("how"))?);
        Ok(())
    }

    fn cache_work_budget(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        h.ok(&ModelCache::of(app).work_budget(&Coerce::text(body.get("hostId")), body.get("budgetBytes"))?);
        Ok(())
    }

    fn cache_delete_foreign(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        h.ok(&ModelCache::of(app).delete_foreign(&Coerce::text(body.get("hostId")), body.get("expectBytes"))?);
        Ok(())
    }

    fn configs_save(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        h.ok(&ConfigBackups::of(app).save(&body)?);
        Ok(())
    }

    fn configs_delete(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        h.ok(&ConfigBackups::of(app).delete(&body)?);
        Ok(())
    }

    fn scout_connect(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        h.ok(&ScoutPairing::of(app).connect(body.get("address"), body.get("port"))?);
        Ok(())
    }

    fn scout_scan(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        h.ok(&ScoutScan::of(app).scan(body.get("networks"), body.get("port"))?);
        Ok(())
    }

    fn scout_disconnect(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        h.ok(&ScoutPairing::of(app).disconnect(&Coerce::text(body.get("hostId")))?);
        Ok(())
    }

    fn move_cells(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        h.ok(&ServerCells::of(app).move_host_cells(&body)?);
        Ok(())
    }

    fn client_create(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        h.ok(&ClientDesk::of(app).create(&body)?);
        Ok(())
    }

    fn client_delete(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        h.ok(&ClientDesk::of(app).delete(&body)?);
        Ok(())
    }

    fn agent_delete(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        h.ok(&ClientDesk::of(app).delete_agent(&body)?);
        Ok(())
    }

    fn agent_alias(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        h.ok(&ClientDesk::of(app).set_agent_alias(body.get("hostId"), body.get("agentId"), body.get("name"))?);
        Ok(())
    }

    fn engine_expose(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        let hosts = FleetReads::of(app).hosts();
        let on = Coerce::truthy(body.get("exposed"));
        let done = EngineOutputs::of(app).set(&hosts, body.get("hostId"), body.get("kind"), body.get("model"), on)?;
        Asked::send_with_board(app, h, Asked::ok_with(done))
    }

    fn last_word(h: &Exchange<'_>) -> String {
        h.parsed.path.rsplit('/').next().map_or_else(String::new, str::to_string)
    }

    fn engines_act(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        let done = EngineActions::of(app).act(body.get("hostId"), &Self::last_word(h), body.get("kind"), body.get("model"))?;
        Asked::send_with_board(app, h, done)
    }

    fn engines_serve(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        let done = EngineActions::of(app).serve(body.get("hostId"), &Self::last_word(h), body.get("kind"))?;
        Asked::send_with_board(app, h, done)
    }
}
