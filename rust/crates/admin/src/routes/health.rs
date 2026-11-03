//! Liveness.

use crate::app::App;
use crate::web::{Exchange, Routes};
use rules::AppError;
use serde_json::json;

/// The routes.
pub struct HealthRoutes;

impl HealthRoutes {
    /// The table.
    pub const ROUTES: Routes = Routes {
        get: &[("/healthz", Self::healthz), ("/health", Self::health), ("/api/health", Self::health)],
        post: &[],
        delete: &[],
    };

    /// Liveness in the home network's shape.
    fn healthz(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        let commit = app.running_commit();
        h.ok(&json!({"status": "ok", "version": if commit.is_empty() { None } else { Some(commit) }}));
        Ok(())
    }

    fn health(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        h.ok(&json!({"ok": true, "service": "lama-caravan", "version": crate::VERSION, "commit": app.running_commit(), "authRequired": true, "setupRequired": !app.auth.enabled()?, "time": app.now_whole()}));
        Ok(())
    }
}
