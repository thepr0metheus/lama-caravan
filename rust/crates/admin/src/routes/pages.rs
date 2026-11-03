//! The board's pages and files.

use crate::app::App;
use crate::web::{Exchange, Routes};
use rules::AppError;
use serde_json::json;

/// The routes.
pub struct PageRoutes;

impl PageRoutes {
    const HTML: &'static str = "text/html; charset=utf-8";

    /// The table.
    pub const ROUTES: Routes = Routes {
        get: &[
            ("/board", Self::board),
            ("/machine", Self::machine),
            ("/", Self::root),
            ("/index.html", Self::root),
            ("/hf", Self::hf),
            ("/router", Self::router),
            ("/routing", Self::routing),
            ("/system", Self::system),
            ("/models", Self::models),
            ("/favicon.svg", Self::favicon),
            ("/favicon.ico", Self::favicon),
        ],
        post: &[],
        delete: &[],
    };

    /// Serves a JavaScript module or a stylesheet of the web UI: a name made of letters, digits, `.`, `_` and `-` that ends in `.js` or `.css`, or a `/js/i18n/` one.
    pub fn static_subdir(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        let path = h.parsed.path.clone();
        let Some((folder, rest)) =
            path.strip_prefix('/').and_then(|tail| tail.split_once('/')).filter(|(folder, _)| matches!(*folder, "js" | "css"))
        else {
            h.send_json(&json!({"error": "Not found"}), 404);
            return Ok(());
        };
        let name = rest.strip_prefix("i18n/").unwrap_or(rest);
        let fits =
            !name.is_empty() && name.chars().all(|letter| letter.is_ascii_alphanumeric() || matches!(letter, '.' | '_' | '-'));
        let kind = if rest.ends_with(".js") {
            Some("application/javascript; charset=utf-8")
        } else if rest.ends_with(".css") {
            Some("text/css; charset=utf-8")
        } else {
            None
        };
        match kind.filter(|_| fits && !rest.contains("..")) {
            Some(kind) => h.send_file(&app.paths.static_dir.join(folder).join(rest), kind),
            None => h.send_json(&json!({"error": "Not found"}), 404),
        }
        Ok(())
    }

    fn file(app: &App, h: &mut Exchange<'_>, name: &str) -> Result<(), AppError> {
        h.send_file(&app.paths.static_dir.join(name), Self::HTML);
        Ok(())
    }

    fn board(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        app.board_opened();
        Self::file(app, h, "index.html")
    }

    fn machine(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        Self::file(app, h, "index.html")
    }

    fn root(_app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        h.redirect("/board");
        Ok(())
    }

    fn hf(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        Self::file(app, h, "hf.html")
    }

    fn router(_app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        let query = h.parsed.query.clone();
        let place = if query.is_empty() { "/routing".to_string() } else { format!("/routing?{query}") };
        h.redirect(&place);
        Ok(())
    }

    fn routing(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        Self::file(app, h, "routing.html")
    }

    fn system(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        Self::file(app, h, "system.html")
    }

    fn models(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        Self::file(app, h, "models.html")
    }

    fn favicon(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        h.send_file(&app.paths.static_dir.join("favicon.svg"), "image/svg+xml");
        Ok(())
    }
}
