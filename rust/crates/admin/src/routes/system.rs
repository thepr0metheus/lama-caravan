//! The controller's machine, its state and its settings file.

use super::asked::Asked;
use crate::app::App;
use crate::benchmarks::Benchmarks;
use crate::benchmarks::quality::{OpenLeaderboard, QualityIndex};
use crate::fleet::gpu_driver::GpuDriver;
use crate::fleet::host_telemetry::HostTelemetry;
use crate::fleet::launch::LaunchScript;
use crate::metrics::MetricsText;
use crate::monitoring::{MachineState, MonitorSampler};
use crate::packages::InstalledPackages;
use crate::proxies::service::Services;
use crate::settings::SettingsBundle;
use crate::status::StatusDesk;
use crate::web::{Exchange, Routes};
use files::AtomicFile;
use rules::{AppError, Coerce};
use serde_json::{Value, json};
use std::os::unix::fs::PermissionsExt;
use std::time::UNIX_EPOCH;

/// The routes.
pub struct SystemRoutes;

impl SystemRoutes {
    const BACKUPS_SHOWN: usize = 20;
    const ASKED_MODELS_MOST: usize = 400;
    /// The API as OpenAPI 3.1, written out of the Python route tables and their docstrings while they stood; a test holds it to the table of routes.
    const OPENAPI: &'static str = include_str!("openapi.json");

    /// The table.
    pub const ROUTES: Routes = Routes {
        get: &[
            ("/api/system-monitor", Self::system_monitor),
            ("/api/state", Self::state),
            ("/api/project-git", Self::project_git),
            ("/api/controller-info", Self::controller_info),
            ("/metrics", Self::metrics),
            ("/api/llamacpp", Self::llamacpp),
            ("/api/llamacpp/update-status", Self::llamacpp_update_status),
            ("/api/llamacpp/builds", Self::llamacpp_builds),
            ("/api/gpu-driver", Self::gpu_driver),
            ("/api/gpu-driver/update-status", Self::gpu_driver_update_status),
            ("/openapi.json", Self::openapi),
            ("/api/packages", Self::packages),
            ("/api/settings/export", Self::settings_export),
            ("/api/settings/backups", Self::settings_backups),
            ("/api/hf/benchmarks", Self::benchmarks),
            ("/api/hf/benchmarks/status", Self::benchmarks_status),
            ("/api/hf/reference-models", Self::reference_models),
            ("/api/hf/bench-search", Self::bench_search),
        ],
        post: &[
            ("/api/system-monitor/settings", Self::monitor_settings),
            ("/api/config", Self::config),
            ("/api/repair/user-service", Self::repair),
            ("/api/llamacpp/update", Self::llamacpp_update),
            ("/api/llamacpp/restore", Self::llamacpp_restore),
            ("/api/gpu-driver/update", Self::gpu_driver_update),
            ("/api/gpu-driver/auto", Self::gpu_driver_auto),
            ("/api/settings/export", Self::settings_export_post),
            ("/api/settings/import", Self::settings_import),
            ("/api/aa-scores", Self::aa_scores),
        ],
        delete: &[],
    };

    /// `/api/monitor/<kind>`: a terminal-style snapshot of the controller's machine, read through its scout.
    pub fn monitor(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        let kind = h.parsed.path.rsplit('/').next().map_or_else(String::new, str::to_string);
        h.ok(&MachineState::of(app).snapshot(&kind)?);
        Ok(())
    }

    fn system_monitor(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        // absent-ok: `int(since or 0)`, and a word that is no number is 0: the whole series.
        let since = h.parsed.param_or("since", "0").parse::<i64>().unwrap_or(0);
        let mut payload = MonitorSampler::of(app).state(since);
        let held = h.parsed.param_or("hostsSince", "0");
        let hosts = app.shared().map_or_else(|| json!({}), |shared| HostTelemetry::watch(&shared, &held));
        Coerce::put(&mut payload, "hosts", hosts);
        h.ok(&payload);
        Ok(())
    }

    fn state(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        h.ok(&StatusDesk::of(app).state());
        Ok(())
    }

    fn project_git(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        h.ok(&StatusDesk::of(app).project_git_info());
        Ok(())
    }

    fn controller_info(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        h.ok(&StatusDesk::of(app).controller_info()?);
        Ok(())
    }

    fn metrics(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        let data = MetricsText::of(app).build().into_bytes();
        h.start(
            200,
            &[
                ("Content-Type", "text/plain; version=0.0.4; charset=utf-8".to_string()),
                ("Content-Length", data.len().to_string()),
            ],
        );
        h.write(&data);
        Ok(())
    }

    fn llamacpp(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        h.ok(&StatusDesk::of(app).llama_cpp_info(true));
        Ok(())
    }

    fn llamacpp_update_status(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        h.ok(&StatusDesk::of(app).update_status());
        Ok(())
    }

    fn llamacpp_builds(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        h.ok(&StatusDesk::of(app).builds_list());
        Ok(())
    }

    fn gpu_driver(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        h.ok(&GpuDriver::of(app).status(GpuDriver::STATUS_TTL)?);
        Ok(())
    }

    fn gpu_driver_update_status(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        h.ok(&GpuDriver::of(app).update_status());
        Ok(())
    }

    fn openapi(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        let mut document: Value =
            serde_json::from_str(Self::OPENAPI).map_err(|error| AppError::with_status(error.to_string(), 500))?;
        if let Some(info) = document.get_mut("info") {
            let commit = app.running_commit();
            Coerce::put(info, "version", json!(if commit.is_empty() { crate::VERSION.to_string() } else { commit }));
            Coerce::put(info, "x-release", json!(crate::VERSION));
        }
        h.ok(&document);
        Ok(())
    }

    fn packages(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        let commit = app.running_commit();
        let mut out = json!({"version": if commit.is_empty() { None } else { Some(commit) }});
        Coerce::extend(&mut out, &InstalledPackages::of(app).listing());
        h.ok(&out);
        Ok(())
    }

    fn settings_export(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        let bundle = SettingsBundle::of(app).export(h.parsed.flag("secrets", false))?;
        h.ok(&json!({"ok": true, "bundle": bundle}));
        Ok(())
    }

    fn settings_backups(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        let mut rows = Vec::new();
        if let Ok(folder) = std::fs::read_dir(&app.paths.settings_backup_dir) {
            let mut files: Vec<_> = folder
                .flatten()
                .map(|entry| entry.path())
                .filter(|path| path.extension().is_some_and(|word| word == "json"))
                .collect();
            files.sort();
            for path in files.iter().rev().take(Self::BACKUPS_SHOWN) {
                let Ok(meta) = std::fs::metadata(path) else {
                    break;
                };
                let name = path.file_name().map_or_else(String::new, |name| name.to_string_lossy().into_owned());
                let mtime = meta.modified().ok().and_then(|when| when.duration_since(UNIX_EPOCH).ok()).map(|when| when.as_secs());
                rows.push(json!({"name": name, "bytes": meta.len(), "mtime": mtime}));
            }
        }
        h.ok(&json!({"ok": true, "backups": rows}));
        Ok(())
    }

    fn benchmarks(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        let repo = Asked::word(h, "repo");
        let answer = if repo.is_empty() {
            json!({"ok": false, "error": "missing repo"})
        } else {
            Benchmarks::of(app).get(&repo, h.parsed.flag("force", false))
        };
        h.ok(&answer);
        Ok(())
    }

    fn benchmarks_status(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        let board = OpenLeaderboard::of(app);
        board.ensure();
        h.ok(&Asked::ok_with(board.status()));
        Ok(())
    }

    fn reference_models(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        h.ok(&QualityIndex::of(app).reference_models(h.parsed.flag("force", false)));
        Ok(())
    }

    fn bench_search(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        h.ok(&Benchmarks::of(app).search(&Asked::word(h, "q")));
        Ok(())
    }

    fn monitor_settings(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        MonitorSampler::of(app).set_retention(body.get("retentionSeconds"))?;
        Asked::send_with_monitor(app, h, json!({"ok": true}));
        Ok(())
    }

    /// The controller's own launch file, regenerated whole: its config block and its command cannot drift apart.
    fn config(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        // absent-ok: no config said: the launch file is rendered from the defaults.
        let config = body.get("config").map(Coerce::fields).unwrap_or_default();
        let script = LaunchScript::of(app).render(&config, None)?;
        let path = &app.paths.start_script;
        let written = AtomicFile::write(path, script.as_bytes())
            .and_then(|()| std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o755)));
        written.map_err(|error| AppError::with_status(format!("{}: {error}", path.display()), 500))?;
        h.ok(&json!({"ok": true, "backup": null, "state": StatusDesk::of(app).state()}));
        Ok(())
    }

    fn repair(app: &App, h: &mut Exchange<'_>, _body: Value) -> Result<(), AppError> {
        let result = Services::of(app).repair_user_service()?;
        h.ok(&json!({"ok": true, "result": result, "state": StatusDesk::of(app).state()}));
        Ok(())
    }

    fn llamacpp_update(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        let job = StatusDesk::of(app).start_update(&Coerce::text(body.get("tag")), "")?;
        h.ok(&json!({"ok": true, "job": job}));
        Ok(())
    }

    fn llamacpp_restore(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        let job = StatusDesk::of(app).start_restore(body.get("id"))?;
        h.ok(&json!({"ok": true, "job": job}));
        Ok(())
    }

    fn gpu_driver_update(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        h.ok(&GpuDriver::of(app).update(&Coerce::text(body.get("package")))?);
        Ok(())
    }

    fn gpu_driver_auto(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        h.ok(&GpuDriver::of(app).set_auto_settings(&body));
        Ok(())
    }

    fn settings_export_post(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        let mut bundle = SettingsBundle::of(app).export(Coerce::truthy(body.get("secrets")))?;
        let passphrase = Coerce::text(body.get("passphrase"));
        if !passphrase.is_empty() {
            bundle = SettingsBundle::encrypt_credentials(bundle, &passphrase)?;
        }
        h.ok(&json!({"ok": true, "bundle": bundle}));
        Ok(())
    }

    /// A refusal here is an answer of 200, as the panel reads it.
    fn settings_import(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        let Some(bundle) = body.get("bundle").filter(|bundle| bundle.is_object()) else {
            h.ok(&json!({"ok": false, "error": "no settings bundle in the request"}));
            return Ok(());
        };
        let desk = SettingsBundle::of(app);
        let done = if Coerce::truthy(body.get("dryRun")) {
            desk.preview_import(bundle).map(|preview| {
                let mut out = json!({"ok": true, "dryRun": true});
                Coerce::extend(&mut out, &preview);
                out
            })
        } else {
            desk.apply(bundle, &Coerce::text(body.get("passphrase"))).map(Asked::ok_with)
        };
        match done {
            Ok(answer) => h.ok(&answer),
            Err(error) => h.ok(&json!({"ok": false, "error": error.message})),
        }
        Ok(())
    }

    fn aa_scores(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        let Some(models) = body.get("models").and_then(Value::as_array) else {
            h.ok(&json!({"ok": false, "error": "models must be a list"}));
            return Ok(());
        };
        let ids: Vec<String> = models.iter().take(Self::ASKED_MODELS_MOST).map(|model| Coerce::str_of(Some(model))).collect();
        let fetch = body.get("fetch").and_then(Value::as_bool) != Some(false);
        h.ok(&QualityIndex::of(app).scores(&ids, fetch));
        Ok(())
    }
}
