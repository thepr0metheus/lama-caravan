//! The `llama.cpp` build on this machine: the binary the cells run, the job that builds or restores another, and the archive of earlier builds. Running cells keep the OLD binary (they hold
//! its inode) until restarted: deliberately never automatic. The slim status rides every heartbeat. One job per scout.

use crate::commands::Commands;
use crate::config::ScoutConfig;
use crate::errors::AppError;
use crate::paths::ScoutPaths;
use crate::process::FileTimes;
use crate::runtimes::job::BackgroundJob;
use os::LocalTime;
use os::clock::Clock;
use rules::Coerce;
use serde_json::{Value, json};
use std::collections::BTreeMap;
use std::fs;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

/// The builds.
pub struct LlamaBuilds {
    config: Arc<ScoutConfig>,
    commands: Arc<dyn Commands>,
    paths: Arc<ScoutPaths>,
    job: BackgroundJob,
}

impl LlamaBuilds {
    /// The builds of this machine.
    pub fn new(config: Arc<ScoutConfig>, commands: Arc<dyn Commands>, paths: Arc<ScoutPaths>, clock: Arc<dyn Clock>) -> Self {
        Self { config, commands, paths, job: BackgroundJob::new("llama-update", "a llama.cpp update is already running", clock) }
    }

    fn binary(&self) -> Option<String> {
        let binary = Coerce::strip(&self.config.text("llamaServerBin")).to_string();
        (!binary.is_empty() && fs::metadata(&binary).is_ok_and(|meta| meta.is_file())).then_some(binary)
    }

    /// The `llama-server` version line, e.g. 'version: 362 (3ac3c20)'.
    pub fn binary_version(&self) -> String {
        let Some(binary) = self.binary() else {
            return String::new();
        };
        let Some(ran) = self.commands.run(&[&binary, "--version"], Duration::from_secs(5)).ok().filter(crate::commands::Ran::ok)
        else {
            return String::new();
        };
        let said = if ran.stdout.is_empty() { &ran.stderr } else { &ran.stdout };
        Coerce::strip(said).lines().next().map_or_else(String::new, str::to_string)
    }

    /// When the binary was built or replaced (epoch s), 0 when there is none.
    pub fn binary_built_at(&self) -> i64 {
        // absent-ok: 0 says "no binary", as the callers read it.
        self.binary().and_then(|binary| fs::metadata(binary).ok()).map_or(0, |meta| FileTimes::modified(&meta))
    }

    /// When the binary was built, in ISO-8601.
    pub fn binary_mtime(&self) -> String {
        let built = self.binary_built_at();
        if built == 0 {
            return String::new();
        }
        // absent-ok: a system that cannot place the moment has no date to say.
        LocalTime::of(built).map_or_else(String::new, |moment| moment.iso())
    }

    /// The job's whole status.
    pub fn status(&self) -> Value {
        self.job.status()
    }

    /// The job's status for a heartbeat.
    pub fn status_slim(&self) -> Value {
        self.job.status_slim()
    }

    fn archive_root(&self) -> PathBuf {
        std::env::var_os("LLAMA_BUILDS_DIR")
            .filter(|said| !said.is_empty())
            .map_or_else(|| self.paths.home.join(".local/share/lama-caravan/llama-builds"), PathBuf::from)
    }

    /// Archived build snapshots on THIS host, newest first: the update script writes one per successful build and prunes.
    pub fn archive(&self) -> Value {
        let mut entries: Vec<PathBuf> = fs::read_dir(self.archive_root())
            .map_or_else(|_| Vec::new(), |entries| entries.flatten().map(|entry| entry.path()).collect());
        entries.sort_unstable_by(|left, right| right.cmp(left));
        let rows: Vec<Value> = entries
            .iter()
            .filter_map(|entry| {
                let raw = fs::read(entry.join("meta.json")).ok()?;
                let mut row = serde_json::from_slice::<Value>(&raw).ok()?;
                let name = entry.file_name()?.to_string_lossy().into_owned();
                row.as_object_mut()?.insert("id".to_string(), json!(name));
                Some(row)
            })
            .collect();
        json!({"ok": true, "builds": rows})
    }

    /// The update job told to put an archived build back. A restore that names no build is refused: the job reads an empty `restoreId` as "no restore" and builds the latest release instead, a pull and a rebuild on a
    /// machine whose operator asked to go back.
    pub fn restore(&self, build_id: Option<&Value>) -> Result<Value, AppError> {
        let id = if build_id.is_some_and(|id| Coerce::truthy(Some(id))) { Coerce::stripped(build_id) } else { String::new() };
        if id.is_empty() {
            return Err(AppError::new("build id is required"));
        }
        self.start_update(&json!({"restoreId": id}))
    }

    /// `{tag?}`: an empty tag is the latest release; a commit works too, which is how the controller converges a client onto its own build. With `{restoreId}` the same job restores an archived build instead of building.
    pub fn start_update(&self, body: &Value) -> Result<Value, AppError> {
        let script = self.paths.root.join("scripts/update-llama.sh");
        if !script.exists() {
            return Err(AppError::with_status(format!("update script not found: {}", script.display()), 500));
        }
        let word = |key: &str| if Coerce::truthy(body.get(key)) { Coerce::stripped(body.get(key)) } else { String::new() };
        let (mut tag, restore) = (word("tag"), word("restoreId"));
        let mut argv = vec!["bash".to_string(), script.display().to_string()];
        if restore.is_empty() {
            argv.extend(["--force".to_string(), "--no-restart".to_string()]);
            if !tag.is_empty() {
                argv.extend(["--llama-tag".to_string(), tag.clone()]);
            }
        } else {
            argv.extend(["--restore".to_string(), restore.clone()]);
            tag = format!("restore:{restore}");
        }
        let mut environment: BTreeMap<String, String> = std::env::vars().collect();
        let path = environment.get("PATH").map_or("/usr/bin:/bin", String::as_str);
        let path = format!("/usr/local/cuda/bin:{path}");
        environment.insert("PATH".to_string(), path);
        // Clients keep a SHORT archive (default 2: current and one-step undo): client snapshots are big and a client rollback is never urgent.
        let keep = self
            .config
            .get("llamaBuildsKeep")
            .filter(|keep| Coerce::truthy(Some(keep)))
            .and_then(|keep| Coerce::int(&keep))
            .unwrap_or(2);
        environment.entry("LLAMA_BUILDS_KEEP".to_string()).or_insert_with(|| keep.to_string());
        self.job.start(argv, &tag, environment)
    }
}
