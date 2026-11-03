//! The Hugging Face page's routes.

use crate::app::App;
use crate::models::downloads::{DownloadFile, Downloads};
use crate::models::hf::HubBrowser;
use crate::models::verify::{CheckpointCopy, ModelVerify};
use crate::web::{Exchange, Routes};
use rules::{AppError, Coerce, Flag};
use serde_json::{Map, Value, json};

/// The routes.
pub struct HfRoutes;

impl HfRoutes {
    /// A job that ended is listed for this long.
    const FINISHED_KEPT: f64 = 300.0;

    /// The table.
    pub const ROUTES: Routes = Routes {
        get: &[
            ("/api/hf/token", Self::token),
            ("/api/hf/download/status", Self::download_status),
            ("/api/hf/download/jobs", Self::download_jobs),
            ("/api/hf/favorites", Self::favorites),
            ("/api/hf/search", Self::search),
            ("/api/hf/files", Self::files),
            ("/api/hf/model-tree", Self::model_tree),
            ("/api/hf/local-check", Self::local_check),
            ("/api/hf/verify", Self::verify_status),
        ],
        post: &[
            ("/api/hf/download", Self::download),
            ("/api/hf/verify", Self::verify),
            ("/api/hf/download/cancel", Self::cancel),
            ("/api/hf/download/discard", Self::discard),
            ("/api/hf/download/resume", Self::resume),
            ("/api/hf/token", Self::set_token),
            ("/api/hf/favorites", Self::set_favorites),
        ],
        delete: &[("/api/hf/local-file", Self::delete_local)],
    };

    fn masked(token: &str) -> Value {
        let count = token.chars().count();
        let tail: String = token.chars().skip(count.saturating_sub(4)).collect();
        let masked = if count >= 8 {
            format!("●●●●{tail}")
        } else if count > 0 {
            "set".to_string()
        } else {
            String::new()
        };
        json!({"ok": true, "set": count > 0, "masked": masked})
    }

    fn token(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        h.ok(&Self::masked(&app.hf_token()));
        Ok(())
    }

    fn set_token(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        let token = Coerce::stripped(body.get("token"));
        app.admin.saving(|doc| doc.insert("hfToken".to_string(), json!(token)));
        app.hub_memory.clear();
        h.ok(&Self::masked(&token));
        Ok(())
    }

    fn download_status(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        let job = Downloads::of(app).job(Coerce::strip(&h.parsed.param_or("job", "")));
        match job.and_then(|job| job.as_object().cloned()).filter(|job| !job.is_empty()) {
            Some(job) => {
                let mut out = Map::new();
                out.insert("ok".to_string(), json!(true));
                out.extend(job);
                h.ok(&Value::Object(out));
            }
            None => h.ok(&json!({"ok": false, "error": "job not found"})),
        }
        Ok(())
    }

    fn download_jobs(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        let downloads = Downloads::of(app);
        downloads.forget_finished(app.now(), Self::FINISHED_KEPT);
        let mut jobs: Vec<Value> = Vec::new();
        for (id, job) in downloads.all() {
            if !matches!(job.get("status").and_then(Value::as_str), Some("done" | "cancelled")) {
                let mut row = Map::new();
                row.insert("jobId".to_string(), json!(id));
                row.extend(Coerce::fields(&job));
                jobs.push(Value::Object(row));
            }
        }
        jobs.extend(downloads.scan_interrupted(&app.models_dir().to_string_lossy()));
        h.ok(&json!({"ok": true, "jobs": jobs}));
        Ok(())
    }

    fn favorites(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        let favorites = app.admin.read(|doc| doc.get("hfFavorites").cloned()).unwrap_or_else(|| json!([]));
        h.ok(&json!({"ok": true, "favorites": favorites}));
        Ok(())
    }

    fn set_favorites(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        if let Some(favorites) = body.get("favorites").filter(|favorites| favorites.is_array()) {
            app.admin.saving(|doc| doc.insert("hfFavorites".to_string(), favorites.clone()));
        }
        h.ok(&json!({"ok": true}));
        Ok(())
    }

    fn search(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        let query = h.parsed.param_or("q", "");
        let word = h.parsed.param_or("limit", "20");
        let limit: i64 = Coerce::strip(&word).parse().map_err(|_| {
            AppError::with_status(format!("invalid literal for int() with base 10: {}", rules::PyRepr::of(&word)), 500)
        })?;
        h.ok(&HubBrowser::of(app).search(&query, limit));
        Ok(())
    }

    fn repo_param(h: &Exchange<'_>) -> String {
        Coerce::strip(&h.parsed.param_or("repo", "")).to_string()
    }

    fn files(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        let repo = Self::repo_param(h);
        let answer =
            if repo.is_empty() { json!({"ok": false, "error": "missing repo"}) } else { HubBrowser::of(app).list_files(&repo) };
        h.ok(&answer);
        Ok(())
    }

    fn model_tree(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        let repo = Self::repo_param(h);
        let answer =
            if repo.is_empty() { json!({"ok": false, "error": "missing repo"}) } else { HubBrowser::of(app).model_tree(&repo) };
        h.ok(&answer);
        Ok(())
    }

    fn local_check(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        let repo = Self::repo_param(h);
        h.ok(&HubBrowser::of(app).local_check(&repo));
        Ok(())
    }

    fn verify_status(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        let job = h.parsed.param_or("job", "");
        let repo = h.parsed.param_or("repo", "");
        h.ok(&ModelVerify::of(app).status(Coerce::strip(&job), Coerce::strip(&repo)));
        Ok(())
    }

    fn download(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        let repo = Coerce::stripped(body.get("repo"));
        let raw = body.get("files").filter(|files| Coerce::truthy(Some(*files))).and_then(Value::as_array);
        let Some(raw) = raw.filter(|_| !repo.is_empty()) else {
            h.ok(&json!({"ok": false, "error": "missing repo or files"}));
            return Ok(());
        };
        let files: Vec<DownloadFile> = raw.iter().map(DownloadFile::of).collect();
        if files.iter().any(|file| file.dest_dir.contains("..") || file.dest_dir.starts_with('/')) {
            h.ok(&json!({"ok": false, "error": "invalid destDir"}));
            return Ok(());
        }
        // A name lands inside its folder: `../x` would write past the check above.
        if files.iter().any(|file| !DownloadFile::is_plain_name(&file.name)) {
            h.ok(&json!({"ok": false, "error": "invalid name"}));
            return Ok(());
        }
        let models_dir = app.models_dir().to_string_lossy().into_owned();
        if !Flag::yes(body.get("replace")) {
            let taken = Downloads::replaces_on_disk(&files, &models_dir);
            if !taken.is_empty() {
                h.ok(&json!({"ok": false, "code": "exists", "files": taken, "error": format!("already on disk: {}", taken.join(", "))}));
                return Ok(());
            }
        }
        let job = Downloads::of(app).start(&repo, files, &models_dir, &app.hf_token());
        h.ok(&json!({"ok": true, "jobId": job}));
        Ok(())
    }

    fn verify(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        let repo = Coerce::stripped(body.get("repo"));
        let browser = HubBrowser::of(app);
        let listing = browser.list_files(&repo);
        if !Coerce::truthy(listing.get("ok")) {
            h.ok(&listing);
            return Ok(());
        }
        let local = browser.local_check(&repo);
        let started = CheckpointCopy::find(&app.models_dir(), &repo, listing.get("safetensors")).and_then(|copies| {
            let files = listing.get("files").and_then(Value::as_array).map_or(&[][..], Vec::as_slice);
            let empty = json!({});
            ModelVerify::of(app).start(&repo, files, local.get("localFiles").unwrap_or(&empty), copies)
        });
        match started {
            Ok(job) => h.ok(&json!({"ok": true, "jobId": job})),
            Err(error) => h.ok(&json!({"ok": false, "error": error.message})),
        }
        Ok(())
    }

    fn cancel(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        let job = Coerce::stripped(body.get("jobId"));
        if job.is_empty() {
            h.ok(&json!({"ok": false, "error": "missing jobId"}));
        } else if Downloads::of(app).cancel(&job).is_none() {
            h.ok(&json!({"ok": false, "error": "job not found or already finished"}));
        } else {
            h.ok(&json!({"ok": true, "jobId": job}));
        }
        Ok(())
    }

    fn discard(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        let (dest, name) = (Coerce::stripped(body.get("destDir")), Coerce::stripped(body.get("name")));
        if dest.is_empty() || name.is_empty() {
            h.ok(&json!({"ok": false, "error": "missing destDir or name"}));
            return Ok(());
        }
        match Downloads::of(app).discard_interrupted(&app.models_dir().to_string_lossy(), &dest, &name) {
            Ok(freed) => h.ok(&json!({"ok": true, "freed": freed})),
            Err(words) => h.ok(&json!({"ok": false, "error": words})),
        }
        Ok(())
    }

    fn resume(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        let (dest, name) = (Coerce::stripped(body.get("destDir")), Coerce::stripped(body.get("name")));
        if dest.is_empty() || name.is_empty() {
            h.ok(&json!({"ok": false, "error": "missing destDir or name"}));
            return Ok(());
        }
        match Downloads::of(app).resume_interrupted(&app.models_dir().to_string_lossy(), &app.hf_token(), &dest, &name) {
            Ok(job) => h.ok(&json!({"ok": true, "jobId": job})),
            Err(error) => h.ok(&json!({"ok": false, "error": error.message})),
        }
        Ok(())
    }

    fn delete_local(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        let (repo, name) = (Self::repo_param(h), h.parsed.param_or("name", ""));
        h.ok(&HubBrowser::of(app).local_delete(&repo, Coerce::strip(&name)));
        Ok(())
    }
}
