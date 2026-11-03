//! The composite state of `/api/state`, the Controller card, and llama.cpp's own version and update.

use crate::app::App;
use crate::common::checkout::CheckoutCommit;
use crate::config::extra::ExtraFlags;
use crate::config::fields::ConfigFields;
use crate::fleet::cell_talk::TalkMode;
use crate::models::checkpoints::ModelCheckpoints;
use crate::models::model_list::ModelList;
use crate::monitoring::MachineState;
use crate::proxies::service::Services;
use crate::settings::SettingsBundle;
use os::{Disk, LocalTime};
use plumbing::commands::Ran;
use rules::{AppError, Coerce};
use serde_json::{Map, Value, json};
use std::collections::BTreeMap;
use std::io::{BufRead, BufReader};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::{Mutex, PoisonError};
use std::time::Duration;

mod llama_build;

/// The one background build or install job.
pub struct UpdateJobMemory {
    held: Mutex<Value>,
}

impl Default for UpdateJobMemory {
    fn default() -> Self {
        Self {
            held: Mutex::new(
                json!({"running": false, "startedAt": 0, "tag": "", "lines": [], "done": false, "rc": null, "error": ""}),
            ),
        }
    }
}

/// The state desk of this controller.
pub struct StatusDesk<'app> {
    app: &'app App,
}

impl<'app> StatusDesk<'app> {
    const GIB: f64 = 1_073_741_824.0;
    const LINES_KEPT: usize = 500;
    const LINES_SHOWN: usize = 200;

    /// The desk of `app`.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    fn run_in(&self, argv: &[&str], folder: &Path, timeout: u64) -> Value {
        let cwd = folder.to_string_lossy();
        let mut asked = vec!["git", "-C", cwd.as_ref()];
        asked.extend(argv.iter().skip(1).copied());
        let ran = self.app.commands.run(&asked, Duration::from_secs(timeout));
        Self::shown(ran.ok())
    }

    fn shown(ran: Option<Ran>) -> Value {
        match ran {
            Some(ran) => json!({"ok": ran.ok(), "stdout": ran.stdout, "stderr": ran.stderr}),
            None => json!({"ok": false, "stdout": "", "stderr": "the command did not answer"}),
        }
    }

    /// The checkout this controller runs from.
    pub fn project_git_info(&self) -> Value {
        let root = &self.app.paths.project_root;
        let source = CheckoutCommit::of(root, true, self.app.env.get(CheckoutCommit::BAKED_ENV), self.app.commands.as_ref());
        if source.baked {
            return json!({"branch": "", "baked": true, "head": source.commit, "dirtyCount": 0, "ok": true, "error": ""});
        }
        let branch = self.run_in(&["git", "branch", "--show-current"], root, 3);
        let dirty = self.run_in(&["git", "status", "--porcelain"], root, 3);
        let name = {
            let said = Coerce::stripped(branch.get("stdout"));
            if said.is_empty() { "detached".to_string() } else { said }
        };
        let branch_ok = Coerce::truthy(branch.get("ok"));
        let dirty_count = if Coerce::truthy(dirty.get("ok")) {
            Coerce::text(dirty.get("stdout")).lines().filter(|line| !line.trim().is_empty()).count()
        } else {
            0
        };
        let ok = source.from_git && branch_ok;
        let error = if ok {
            String::new()
        } else if source.error.is_empty() {
            Coerce::text(branch.get("stderr"))
        } else {
            source.error.clone()
        };
        json!({"branch": if branch_ok { name } else { String::new() }, "head": source.commit, "dirtyCount": dirty_count, "ok": ok, "error": error})
    }

    /// Disk headroom for the models folder: cheap, for the page's badge and the check before a download.
    pub fn models_disk(&self) -> Result<Value, AppError> {
        let folder = self.app.models_dir_of(&self.app.parse_config()?);
        Ok(match Disk::usage(&folder) {
            Some((total, free)) => json!({
                "ok": true, "path": folder.to_string_lossy(),
                "totalGb": Coerce::rounded(total as f64 / Self::GIB, 1), "freeGb": Coerce::rounded(free as f64 / Self::GIB, 1),
            }),
            None => json!({"ok": false, "path": folder.to_string_lossy(), "error": "the disk of this folder cannot be read"}),
        })
    }

    fn gguf_sizes(folder: &Path) -> Option<Vec<u64>> {
        let (mut sizes, mut folders) = (Vec::new(), vec![folder.to_path_buf()]);
        while let Some(at) = folders.pop() {
            for entry in std::fs::read_dir(&at).ok()?.flatten() {
                let path = entry.path();
                if path.is_dir() {
                    folders.push(path);
                } else if path.extension().is_some_and(|extension| extension == "gguf") {
                    // absent-ok: a file that cannot be read adds nothing to the sum.
                    sizes.push(entry.metadata().map_or(0, |found| found.len()));
                }
            }
        }
        Some(sizes)
    }

    /// The Controller card in the System modal.
    pub fn controller_info(&self) -> Result<Value, AppError> {
        let folder = self.app.models_dir_of(&self.app.parse_config()?);
        let services = Services::of(self.app);
        let briefs = if self.app.paths.is_container {
            services.container_briefs()
        } else {
            vec![services.unit_brief(&self.app.paths.admin_service_name), services.proxy_brief()]
        };
        let disk = match Disk::usage(&folder) {
            Some((total, free)) => json!({
                "path": folder.to_string_lossy(), "totalGb": Coerce::rounded(total as f64 / Self::GIB, 1),
                "freeGb": Coerce::rounded(free as f64 / Self::GIB, 1), "usedGb": Coerce::rounded(total.saturating_sub(free) as f64 / Self::GIB, 1),
            }),
            None => json!({"path": folder.to_string_lossy(), "error": "the disk of this folder cannot be read"}),
        };
        let models = Self::gguf_sizes(&folder).map_or_else(
            || json!({}),
            |sizes| json!({"count": sizes.len(), "totalGb": Coerce::rounded(sizes.iter().sum::<u64>() as f64 / Self::GIB, 1)}),
        );
        Ok(json!({
            "ok": true, "appVersion": crate::VERSION, "container": self.app.paths.is_container,
            "projectGit": self.project_git_info(), "services": briefs, "disk": disk, "models": models, "time": self.app.now_whole(),
        }))
    }

    /// Each config field with its flags, sorted.
    fn field_flags() -> Value {
        let mut order: Vec<&str> = Vec::new();
        let mut out: BTreeMap<&str, Vec<&str>> = BTreeMap::new();
        for (flag, field) in ExtraFlags::flags_in_order() {
            if field.is_empty() {
                continue;
            }
            let flags = out.entry(field).or_insert_with(|| {
                order.push(field);
                Vec::new()
            });
            flags.push(flag);
        }
        let mut shown = Map::new();
        for field in order {
            if let Some(flags) = out.get_mut(field) {
                flags.sort_unstable();
                shown.insert(field.to_string(), json!(flags));
            }
        }
        Value::Object(shown)
    }

    /// The legacy single server's `/props`, on its configured port.
    fn legacy_port_props(&self, config: &Map<String, Value>) -> Value {
        let port = {
            let said = Coerce::text(config.get("PORT"));
            if said.is_empty() { "8080".to_string() } else { said }
        };
        let url = format!("http://127.0.0.1:{port}/props");
        self.app
            .http
            .json("GET", &url, &[], &[], Duration::from_secs(2))
            .unwrap_or_else(|error| json!({"ok": false, "error": error.to_string()}))
    }

    /// `/api/state`.
    pub fn state(&self) -> Value {
        // absent-ok: an unreadable config reads as the defaults here: what it breaks is said where it is used.
        let config = self.app.parse_config().unwrap_or_default();
        let services = Services::of(self.app);
        let service = services.service_status();
        let (models, stamp) = ModelList::of(self.app).current();
        let favorites = self.app.admin.read(|doc| doc.get("favFields").cloned());
        let favorites: Vec<Value> = favorites
            .as_ref()
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            .filter(|field| field.as_str().is_some_and(ConfigFields::holds))
            .cloned()
            .collect();
        let help: Value = serde_json::from_str(ConfigFields::HELP).unwrap_or_else(|_| json!({}));
        let checkpoints = ModelCheckpoints::of(self.app);
        let machine = MachineState::of(self.app);
        let props = || self.legacy_port_props(&config);
        json!({
            "appVersion": crate::VERSION,
            "container": self.app.paths.is_container,
            "runners": self.app.runners.registry_json(),
            "talkModes": TalkMode::all_json(),
            "config": config,
            "fields": ConfigFields::ALL.as_slice(),
            "help": help,
            "fieldFlags": Self::field_flags(),
            "favFields": favorites,
            "paths": {
                "llamaHome": self.app.paths.llama_home.to_string_lossy(),
                "startScript": self.app.paths.start_script.to_string_lossy(),
                "modelsDir": self.app.models_dir_of(&config).to_string_lossy(),
                "service": self.app.paths.service_name,
            },
            "models": *models,
            "modelsStamp": stamp,
            "artifacts": checkpoints.st_artifacts(&config),
            "whisperOnDisk": checkpoints.whisper_sizes(&config),
            "translateOnDisk": checkpoints.translate_models(&config),
            "settingsPassphrase": SettingsBundle::passphrase_available(),
            "chatTemplates": checkpoints.chat_templates(&config),
            "service": service,
            "diagnostics": services.diagnostics(&service, &props),
            "cpu": machine.cpu_state(),
            "gpu": machine.gpu_state(),
            "memory": machine.memory_state(),
            "llamaCpp": self.llama_cpp_info(false),
            "projectGit": self.project_git_info(),
            "time": self.app.now_whole(),
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn colours_are_taken_out_of_a_line() {
        assert_eq!(StatusDesk::without_colors("\x1b[31mred\x1b[0m plain"), "red plain");
        assert_eq!(StatusDesk::without_colors("\x1b[2Jkept"), "\x1b[2Jkept");
    }

    #[test]
    fn the_newest_build_is_read_off_the_tags() {
        let listing = "aaaaaaaa11\trefs/tags/b5\nbbbbbbbb22\trefs/tags/b7\ncccccccc33\trefs/tags/b7^{}\nnot a line\n";
        assert_eq!(StatusDesk::newest_build_tag(listing), (7, "cccccccc33".to_string()));
        assert_eq!(StatusDesk::newest_build_tag(""), (0, String::new()));
    }
}
