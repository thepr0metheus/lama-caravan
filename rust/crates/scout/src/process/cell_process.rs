//! The process of one cell: a `llama-server`, or whatever a command cell runs. It knows nothing of ports or phases, only its process and the cell it carries the mark of. Started or adopted, then
//! running, then stopped or crashed. All state is behind its lock.

use crate::process::held::{Held, Inner};
use crate::process::launcher::{LaunchFiles, Launcher, Stopping};
use crate::process::log::{CellLog, LogPatterns};
use crate::process::scope::MemoryScope;
use os::Signals;
use os::clock::Clock;
use rules::Coerce;
use serde_json::{Map, Value, json};
use std::path::{Path, PathBuf};
use std::process::Child;
use std::sync::{Arc, Mutex, MutexGuard, PoisonError};

/// What a process needs from the scout.
#[derive(Clone)]
pub struct ProcessParts {
    /// The clocks.
    pub clock: Arc<dyn Clock>,
    /// The limits a cell runs under.
    pub scope: Arc<MemoryScope>,
    /// How a log is read.
    pub patterns: Arc<LogPatterns>,
    /// The machine's memory, in MiB, when it says: `MemoryLedger.meminfo`.
    pub total_memory_mib: Option<f64>,
    /// This scout's folder, in the environment of what it starts.
    pub home: String,
}

/// One cell's process.
pub struct CellProcess {
    parts: ProcessParts,
    /// The name of the cell whose mark it carries.
    cell: String,
    inner: Mutex<Inner>,
    /// One start or stop at a time. Apart from `inner`: a stop takes up to 15 seconds, every reading of a cell waits on `inner`, and `/api/state` reads them all.
    changes: Mutex<()>,
}

impl CellProcess {
    /// The launch files, each under its role on the board's card.
    const LAUNCH_FILES: [(&'static str, &'static str); 3] =
        [("modelPath", "model"), ("mmprojPath", "mmproj"), ("specPath", "draft")];

    /// A process of nothing yet, of the cell named `cell`.
    pub fn new(parts: ProcessParts, cell: &str) -> Self {
        Self { parts, cell: cell.to_string(), inner: Mutex::new(Inner::default()), changes: Mutex::new(()) }
    }

    fn inner(&self) -> MutexGuard<'_, Inner> {
        self.inner.lock().unwrap_or_else(PoisonError::into_inner)
    }

    fn one_change(&self) -> MutexGuard<'_, ()> {
        self.changes.lock().unwrap_or_else(PoisonError::into_inner)
    }

    fn now(&self) -> i64 {
        self.parts.clock.epoch() as i64
    }

    fn log_of(&self, path: Option<PathBuf>) -> CellLog {
        CellLog::new(path, Arc::clone(&self.parts.patterns))
    }

    /// Re-attaches to a server that survived a scout's restart: managed by pid, liveness by a signal of nothing, stop by SIGTERM and SIGKILL.
    pub fn adopt(
        &self,
        pid: i64,
        config: Map<String, Value>,
        log_path: Option<PathBuf>,
        started_at: i64,
        launch: Option<Value>,
    ) -> Value {
        let now = self.now();
        let _one_change = self.one_change();
        let mut inner = self.inner();
        inner.held = Held::Adopted(pid);
        inner.config = config;
        inner.started_at = if started_at != 0 { started_at } else { now };
        inner.last_error = String::new();
        inner.log_path = log_path;
        inner.exit_info = None;
        inner.launch = launch.filter(|launch| Coerce::truthy(launch.get("argv")));
        json!({"ok": true, "pid": pid, "adopted": true})
    }

    fn launched(
        &self,
        inner: &mut Inner,
        child: Child,
        config: Map<String, Value>,
        spec: Value,
        log_path: Option<PathBuf>,
    ) -> Value {
        let pid = child.id();
        let port = config.get("port").cloned();
        inner.held = Held::Child(child);
        inner.config = config;
        inner.started_at = self.now();
        inner.last_error = String::new();
        inner.log_path = log_path;
        inner.exit_info = None;
        inner.launch = Some(spec);
        json!({"ok": true, "pid": pid, "port": port})
    }

    /// Launches `llama-server`. `args` is the full list after the binary; `config` is what `status` shows; `extra` is set over the scout's own environment and kept with the launch, so that a restart
    /// after a crash starts it the same way.
    pub fn start(
        &self,
        binary: &str,
        args: &[String],
        config: Map<String, Value>,
        log_path: Option<PathBuf>,
        extra: &Map<String, Value>,
        ram_mib: f64,
    ) -> Value {
        let _one_change = self.one_change();
        let mut inner = self.inner();
        if inner.is_running() {
            return json!({"ok": false, "error": "llama-server is already running", "port": inner.config.get("port")});
        }
        inner.held = Held::Nothing;
        let binary = Launcher::expanded(binary);
        if !binary.exists() {
            return json!({"ok": false, "error": format!("llama-server binary not found: {}", binary.display())});
        }
        let model = Coerce::text(config.get("modelPath"));
        if !model.is_empty() && !Path::new(&model).exists() {
            return json!({"ok": false, "error": format!("model file not found: {model}")});
        }
        let mut argv = vec![binary.display().to_string()];
        argv.extend(args.iter().cloned());
        self.launch_locked(&mut inner, argv, config, log_path, extra, ram_mib)
    }

    /// Launches a command cell through bash: `line` is a whole shell line that sets `$PORT` and `exec`s the real process, so that the tracked pid is the server itself.
    pub fn start_command(
        &self,
        line: &str,
        config: Map<String, Value>,
        log_path: Option<PathBuf>,
        extra: &Map<String, Value>,
        ram_mib: f64,
    ) -> Value {
        let _one_change = self.one_change();
        let mut inner = self.inner();
        if inner.is_running() {
            return json!({"ok": false, "error": "a process is already running", "port": inner.config.get("port")});
        }
        inner.held = Held::Nothing;
        let argv = vec!["bash".to_string(), "-lc".to_string(), line.to_string()];
        self.launch_locked(&mut inner, argv, config, log_path, extra, ram_mib)
    }

    fn launch_locked(
        &self,
        inner: &mut Inner,
        argv: Vec<String>,
        mut config: Map<String, Value>,
        log_path: Option<PathBuf>,
        extra: &Map<String, Value>,
        ram_mib: f64,
    ) -> Value {
        match Launcher::new(&self.parts).spawned(&argv, (&self.cell, config.get("port")), extra, log_path.as_deref(), ram_mib) {
            Ok(child) => {
                let spec = Launcher::spec_of(&argv, extra, log_path.as_deref(), ram_mib);
                config.insert("cmd".to_string(), json!(argv));
                self.launched(inner, child, config, spec, log_path)
            }
            Err(words) => {
                inner.last_error.clone_from(&words);
                inner.held = Held::Nothing;
                json!({"ok": false, "error": words})
            }
        }
    }

    /// How this cell was last launched; `None` when it never was here.
    pub fn launch_spec(&self) -> Option<Value> {
        self.inner().launch.clone()
    }

    /// The same launch again, after a crash: same argv, environment and log; the crashed run's log is kept aside, as on every start.
    pub fn relaunch(&self) -> Value {
        let _one_change = self.one_change();
        let mut inner = self.inner();
        if inner.is_running() {
            return json!({"ok": false, "error": "the cell is running"});
        }
        let spec = inner.launch.clone().unwrap_or(Value::Null);
        let argv: Vec<String> =
            spec.get("argv").and_then(Value::as_array).into_iter().flatten().map(|word| Coerce::text(Some(word))).collect();
        if argv.is_empty() {
            return json!({"ok": false, "error": "no launch to repeat — it was started before this scout kept one"});
        }
        let log_path = Some(Coerce::text(spec.get("log"))).filter(|path| !path.is_empty()).map(PathBuf::from);
        // absent-ok: a launch of no extra environment has the scout's own.
        let extra = spec.get("extraEnv").and_then(Value::as_object).cloned().unwrap_or_default();
        // absent-ok: a launch that promised no memory has no raised scope to size.
        let ram_mib = spec.get("ramMiB").and_then(Value::as_f64).unwrap_or(0.0);
        let port = inner.config.get("port").cloned();
        match Launcher::new(&self.parts).spawned(&argv, (&self.cell, port.as_ref()), &extra, log_path.as_deref(), ram_mib) {
            Ok(child) => {
                let pid = child.id();
                inner.held = Held::Child(child);
                inner.started_at = self.now();
                inner.last_error = String::new();
                inner.log_path = log_path;
                inner.exit_info = None;
                json!({"ok": true, "pid": pid})
            }
            Err(words) => {
                inner.last_error.clone_from(&words);
                inner.held = Held::Nothing;
                json!({"ok": false, "error": words})
            }
        }
    }

    /// Stops the process. Any prior crash goes too, so that a failed cell can be dismissed without a restart of the scout.
    pub fn stop(&self) -> Value {
        let _one_change = self.one_change();
        let held = {
            let mut inner = self.inner();
            let held = std::mem::take(&mut inner.held);
            match &held {
                Held::Child(child) => inner.held = Held::Stopping(i64::from(child.id())),
                Held::Adopted(pid) | Held::Stopping(pid) => inner.held = Held::Stopping(*pid),
                Held::Nothing => {}
            }
            held
        };
        let not_running = || json!({"ok": true, "detail": "not running"});
        let result = match held {
            Held::Adopted(pid) => Stopping::adopted(pid),
            Held::Child(mut child) => {
                if matches!(child.try_wait(), Ok(None)) {
                    Stopping::child(&mut child)
                } else {
                    not_running()
                }
            }
            Held::Nothing | Held::Stopping(_) => not_running(),
        };
        let mut inner = self.inner();
        inner.held = Held::Nothing;
        inner.last_error = String::new();
        inner.exit_info = Some(Map::new());
        inner.config = Map::new();
        inner.started_at = 0;
        result
    }

    /// The log this process writes: a log of nothing before its first start.
    pub fn log(&self) -> CellLog {
        let path = self.inner().log_path.clone();
        self.log_of(path)
    }

    /// The model files this process holds while it runs, what a cache purge must leave alone: the launch files, the rest a command cell was sent. A process that does not run holds none.
    pub fn named_files(&self) -> Vec<String> {
        if self.status().get("running") != Some(&Value::Bool(true)) {
            return Vec::new();
        }
        let inner = self.inner();
        let mut named: Vec<String> = Self::LAUNCH_FILES
            .iter()
            .map(|(key, _)| Coerce::text(inner.config.get(*key)))
            .filter(|path| !path.is_empty())
            .collect();
        let files = inner.config.get("files").and_then(Value::as_array).into_iter().flatten();
        named.extend(files.filter(|file| Coerce::truthy(Some(*file))).map(|file| Coerce::text(Some(file))));
        named
    }

    /// The roles of the launch files that changed on disk after the process started: a running process holds the files it opened, not their names, so a file replaced under it reaches the cell only
    /// on a restart, and the board says so. A file that cannot be read has not "changed"; a folder changed when a file in it did.
    pub fn changed_since(&self, started_at: i64) -> Vec<&'static str> {
        if started_at == 0 {
            return Vec::new();
        }
        // The times are read with the lock let go: a folder takes as long as its listing, and every reading of this cell waits on the lock. Through the view it is a question to the controller's side.
        let named: Vec<(String, &'static str)> = {
            let inner = self.inner();
            Self::LAUNCH_FILES.iter().map(|(key, role)| (Coerce::text(inner.config.get(*key)), *role)).collect()
        };
        named
            .into_iter()
            .filter(|(path, _)| !path.is_empty() && LaunchFiles::newest_mtime(path) > started_at)
            .map(|(_, role)| role)
            .collect()
    }

    /// What it is doing now. A process found dead here is read for its reason, once: what stays is the exit's record.
    pub fn status(&self) -> Map<String, Value> {
        let now = self.now();
        let mut inner = self.inner();
        match std::mem::take(&mut inner.held) {
            Held::Adopted(pid) => {
                if Signals::alive(pid) {
                    inner.held = Held::Adopted(pid);
                    let mut out = inner.running_row(pid, now);
                    out.insert("adopted".to_string(), json!(true));
                    return out;
                }
                // Died while adopted: no exit code is observable, for it was not this scout's child.
                self.exited(&mut inner, Value::Null, true)
            }
            Held::Stopping(pid) => {
                inner.held = Held::Stopping(pid);
                inner.running_row(pid, now)
            }
            Held::Nothing => {
                let mut out = Map::new();
                out.insert("running".to_string(), json!(false));
                if let Some(info) = &inner.exit_info {
                    out.extend(info.clone());
                }
                if !inner.last_error.is_empty() && !Coerce::truthy(out.get("lastError")) {
                    out.insert("lastError".to_string(), json!(inner.last_error));
                }
                out
            }
            Held::Child(mut child) => match child.try_wait() {
                Ok(None) => {
                    let pid = i64::from(child.id());
                    inner.held = Held::Child(child);
                    inner.running_row(pid, now)
                }
                Ok(Some(status)) => {
                    use std::os::unix::process::ExitStatusExt;
                    // A signal ended it: `poll()` says that as the signal's number below zero.
                    let code = status.code().or_else(|| status.signal().map(|signal| -signal));
                    self.exited(&mut inner, json!(code), code != Some(0))
                }
                Err(_) => self.exited(&mut inner, Value::Null, true),
            },
        }
    }

    fn exited(&self, inner: &mut Inner, code: Value, crashed: bool) -> Map<String, Value> {
        let said = if inner.last_error.is_empty() {
            self.log_of(inner.log_path.clone()).crash_reason()
        } else {
            inner.last_error.clone()
        };
        let mut info = Map::new();
        info.insert("exitCode".to_string(), code);
        info.insert("lastError".to_string(), json!(said));
        info.insert("crashed".to_string(), json!(crashed));
        if inner.config.get("runner").and_then(Value::as_str) == Some("prism") {
            info.insert("runner".to_string(), json!("prism"));
        }
        inner.exit_info = Some(info.clone());
        let mut out = Map::new();
        out.insert("running".to_string(), json!(false));
        out.extend(info);
        out
    }

    /// The configuration it was started with.
    pub fn config(&self) -> Map<String, Value> {
        self.inner().config.clone()
    }
}
