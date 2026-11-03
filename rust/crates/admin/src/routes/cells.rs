//! The cells: their slots, their launch config, the window that talks to them.

use super::asked::Asked;
use crate::app::App;
use crate::config::builder::CellCommand;
use crate::config::extra::ExtraFlags;
use crate::config::fields::ConfigFields;
use crate::domain::runner::Config;
use crate::fleet::cell_assets::CellAssets;
use crate::fleet::cell_live::CellLive;
use crate::fleet::cell_ops::{CellAutostart, CellOps};
use crate::fleet::cell_schedule::CellSchedule;
use crate::fleet::cell_talk::CellTalk;
use crate::fleet::launch::LaunchScript;
use crate::fleet::server_cells::ServerCells;
use crate::fleet::start::CellRamPlan;
use crate::models::model_list::ModelList;
use crate::store::topology::Topology;
use crate::web::{Exchange, Routes};
use rules::{AppError, Coerce};
use serde_json::{Value, json};
use std::collections::BTreeSet;

/// The routes.
pub struct CellRoutes;

impl CellRoutes {
    /// The table.
    pub const ROUTES: Routes = Routes {
        get: &[
            ("/api/script-preview", Self::script_preview),
            ("/api/cell-talk/voices", Self::voices),
            ("/api/cell-live", Self::live),
            ("/api/cell-assets", Self::assets),
            ("/api/cell-assets/file", Self::asset_file),
        ],
        post: &[
            ("/api/topology/server-slot/add", Self::slot_add),
            ("/api/topology/server-slot/delete", Self::slot_delete),
            ("/api/topology/server-slot/note", Self::slot_note),
            ("/api/topology/server-cell/action", Self::action),
            ("/api/topology/server-cell/schedule", Self::schedule),
            ("/api/topology/server-cell/reassign-port", Self::reassign_port),
            ("/api/topology/server-cell/swap-port", Self::swap_port),
            ("/api/topology/server-cell/save-config", Self::save_config),
            ("/api/cell-talk", Self::talk),
            ("/api/cell-talk/voice", Self::store_voice),
            ("/api/llama-command-preview", Self::command_preview),
            ("/api/cell-ram-plan", Self::ram_plan),
            ("/api/parse-extra-args", Self::parse_extra_args),
            ("/api/config-favorites", Self::favorites),
        ],
        delete: &[],
    };

    fn script_preview(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        h.ok(&CellOps::of(app).script_preview(&h.parsed.param_or("path", ""))?);
        Ok(())
    }

    fn voices(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        let (host, port) = (h.parsed.param_or("hostId", ""), h.parsed.param_or("port", ""));
        h.ok(&Asked::ok_with(CellTalk::of(app).voices(&host, Some(&json!(port)))?));
        Ok(())
    }

    fn live(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        let (host, port) = (h.parsed.param_or("hostId", ""), h.parsed.param_or("port", ""));
        CellLive::of(app).serve(h, &host, Some(&json!(port)))
    }

    fn assets(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        h.ok(&CellAssets::of(app).manifest());
        Ok(())
    }

    fn asset_file(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        let data = CellAssets::of(app).bytes(&Asked::word(h, "name"))?;
        h.start(200, &[("Content-Type", "application/octet-stream".to_string()), ("Content-Length", data.len().to_string())]);
        h.write(&data);
        Ok(())
    }

    fn slot_add(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        h.ok(&CellOps::of(app).slot_add(&body)?);
        Ok(())
    }

    fn slot_delete(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        h.ok(&CellOps::of(app).slot_delete(&body)?);
        Ok(())
    }

    fn slot_note(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        let port = Asked::int_strict(&body, "port")?;
        let done = ServerCells::of(app).set_note(&Coerce::text(body.get("hostId")), port, body.get("note"))?;
        h.ok(&Asked::ok_with(done));
        Ok(())
    }

    fn action(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        h.ok(&CellOps::of(app).action(&body)?);
        Ok(())
    }

    fn schedule(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        h.ok(&CellSchedule::set(app, &body)?);
        Ok(())
    }

    fn reassign_port(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        let host = Coerce::stripped(body.get("hostId"));
        let moves = [(host, Asked::int_or_zero(&body, "port")?, Asked::int_or_zero(&body, "newPort")?)];
        let (mut done, autostart) = CellAutostart::of(app).moved(&moves, || ServerCells::of(app).reassign_port(&body))?;
        Coerce::put(&mut done, "autostart", json!(autostart));
        Asked::send_with_board(app, h, done)
    }

    fn swap_port(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        let host = Coerce::stripped(body.get("hostId"));
        let (port_a, port_b) = (Asked::int_or_zero(&body, "port")?, Asked::int_or_zero(&body, "targetPort")?);
        let other = app.admin.change(|doc| {
            let slots = Topology::of(doc).slots().clone();
            slots.values().find(|slot| Coerce::int_or_zero(slot.get("port")) == Some(port_b)).cloned()
        });
        let mut moves = vec![(host, port_a, port_b)];
        if let Some(other) = other {
            moves.push((Coerce::text(other.get("hostId")), port_b, port_a));
        }
        let (mut done, autostart) = CellAutostart::of(app).moved(&moves, || ServerCells::of(app).swap_ports(&body))?;
        Coerce::put(&mut done, "autostart", json!(autostart));
        Asked::send_with_board(app, h, done)
    }

    fn save_config(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        h.ok(&CellOps::of(app).save_config(&body)?);
        Ok(())
    }

    fn talk(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        h.ok(&Asked::ok_with(CellTalk::of(app).talk(&body)?));
        Ok(())
    }

    fn store_voice(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        h.ok(&Asked::ok_with(CellTalk::of(app).store_voice(&body)?));
        Ok(())
    }

    /// The command with the words the runner's environment puts before it, as the operator reads it.
    fn command_preview(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        // absent-ok: what is no object is an empty config, previewed as such.
        let config: Config = body.get("config").filter(|config| config.is_object()).map(Coerce::fields).unwrap_or_default();
        let where_they_are = ModelList::locations(app, false);
        let build = |config: &Config| -> Result<Vec<String>, AppError> {
            let command = CellCommand::of(app).local_command(config, Some(&where_they_are))?;
            let environment = app.runners.for_config(config).launch_env(config);
            Ok(LaunchScript::env_words(&environment).into_iter().chain(command).collect())
        };
        let tokens = match build(&config) {
            Ok(tokens) => tokens,
            Err(error) => {
                h.ok(&json!({"ok": false, "error": error.message, "tokens": []}));
                return Ok(());
            }
        };
        let owners = CellCommand::token_owners(&config, build);
        let command = tokens.join(" ");
        h.ok(&json!({"ok": true, "tokens": tokens, "command": command, "owners": owners}));
        Ok(())
    }

    fn ram_plan(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        let config = body.get("config").filter(|config| config.is_object()).cloned().unwrap_or_else(|| json!({}));
        h.ok(&Asked::ok_with(CellRamPlan::of(app, &config)));
        Ok(())
    }

    fn parse_extra_args(_app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        let said = body.get("extraArgs").filter(|said| Coerce::truthy(Some(*said))).or_else(|| body.get("text"));
        h.ok(&Asked::ok_with(ExtraFlags::parse(&Coerce::text(said))));
        Ok(())
    }

    fn favorites(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        let Some(favorites) = body.get("favorites").and_then(Value::as_array) else {
            h.ok(&json!({"ok": false, "error": "favorites must be a list"}));
            return Ok(());
        };
        let mut seen = BTreeSet::new();
        let mut clean = Vec::new();
        for said in favorites {
            let field = Coerce::str_of(Some(said));
            if ConfigFields::holds(&field) && seen.insert(field.clone()) {
                clean.push(field);
            }
        }
        app.admin.saving(|doc| doc.insert("favFields".to_string(), json!(clean)));
        h.ok(&json!({"ok": true, "favFields": clean}));
        Ok(())
    }
}
