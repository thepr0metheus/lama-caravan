//! The launch builder's saved parameter sets and the per-model runner marks (domain/runner_presets.rs): read by every page,
//! written by an administrator. A write is kept in memory and saved as the other doors of the admin state save (`saving`).

use crate::app::App;
use crate::domain::runner_presets::RunnerPresets;
use crate::web::{Exchange, Routes};
use rules::{AppError, Coerce};
use serde_json::{Value, json};

/// The operator's shared choices.
pub struct RunnerPresetRoutes;

impl RunnerPresetRoutes {
    /// Routes use the normal session and administrator write access.
    pub const ROUTES: Routes = Routes {
        get: &[("/api/runner-presets", Self::list), ("/api/runner-presets/fields", Self::fields)],
        post: &[
            ("/api/runner-presets/put", Self::put),
            ("/api/runner-presets/remove", Self::remove),
            ("/api/model-runner-warning", Self::mark),
        ],
        delete: &[],
    };

    fn word<'a>(body: &'a Value, key: &str) -> Result<&'a str, AppError> {
        body.get(key).and_then(Value::as_str).ok_or_else(|| AppError::new(format!("{key} must be a string")))
    }

    fn list(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        let mut data = app.admin.read(|doc| RunnerPresets::list(doc, &app.runners));
        Coerce::put(&mut data, "ok", json!(true));
        h.ok(&data);
        Ok(())
    }

    fn fields(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        let runner = h.parsed.param_or("runner", "");
        h.ok(&json!({"ok": true, "runner": runner, "fields": RunnerPresets::fields(&app.runners, &runner)?}));
        Ok(())
    }

    fn put(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        let runner = Self::word(&body, "runner")?;
        let name = Self::word(&body, "name")?;
        let params = body.get("params").ok_or_else(|| AppError::new("params required"))?;
        app.admin.saving(|doc| RunnerPresets::put(doc, &app.runners, runner, name, params))?;
        h.ok(&json!({"ok": true}));
        Ok(())
    }

    fn remove(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        app.admin.saving(|doc| RunnerPresets::remove(doc, Self::word(&body, "runner")?, Self::word(&body, "name")?))?;
        h.ok(&json!({"ok": true}));
        Ok(())
    }

    fn mark(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        let unwanted =
            body.get("unwanted").and_then(Value::as_bool).ok_or_else(|| AppError::new("unwanted must be a boolean"))?;
        app.admin.saving(|doc| {
            RunnerPresets::mark(doc, &app.runners, Self::word(&body, "model")?, Self::word(&body, "runner")?, unwanted)
        })?;
        h.ok(&json!({"ok": true}));
        Ok(())
    }
}
