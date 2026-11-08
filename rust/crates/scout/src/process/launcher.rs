//! How a process is launched and how it ends: what `CellProcess` does outside its own state.

use crate::process::cell_process::ProcessParts;
use crate::process::host::HostProcesses;
use crate::process::log::{CellLog, FileTimes};
use os::Signals;
use rules::Coerce;
use serde_json::{Map, Value, json};
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Arc;
use std::time::Duration;

/// A launch.
pub(super) struct Launcher<'a> {
    parts: &'a ProcessParts,
}

impl<'a> Launcher<'a> {
    pub(super) fn new(parts: &'a ProcessParts) -> Self {
        Self { parts }
    }

    /// The child of `argv`, in its scope, writing to `log_path`, with the scout's environment, what the start adds over it, and the marks: the name of its cell and the port its run holds (`mark`),
    /// whose it is. Nothing a start carries can take a mark away.
    pub(super) fn spawned(
        &self,
        argv: &[String],
        mark: (&str, Option<&Value>),
        extra: &Map<String, Value>,
        log_path: Option<&Path>,
        ram_mib: f64,
    ) -> Result<Child, String> {
        let wrapped = self.parts.scope.wrap(argv, ram_mib, self.parts.total_memory_mib);
        let (program, rest) = wrapped.split_first().ok_or_else(|| "nothing to run".to_string())?;
        let log = CellLog::new(log_path.map(Path::to_path_buf), Arc::clone(&self.parts.patterns))
            .open_new(self.parts.clock.epoch() as i64)
            .map_err(|error| error.to_string())?;
        let (cell, port) = mark;
        let mut command = Command::new(program);
        command.args(rest).stdin(Stdio::null()).env(HostProcesses::CELL_ENV, cell).env(HostProcesses::HOME_ENV, &self.parts.home);
        if let Some(port) = port.filter(|port| !port.is_null()) {
            command.env(HostProcesses::PORT_ENV, Coerce::text(Some(port)));
        }
        for (name, value) in extra.iter().filter(|(name, _)| !HostProcesses::MARKS.contains(&name.as_str())) {
            command.env(name, Coerce::text(Some(value)));
        }
        match log {
            Some(file) => {
                let errors = file.try_clone().map_err(|error| error.to_string())?;
                command.stdout(file).stderr(errors);
            }
            None => {
                command.stdout(Stdio::null()).stderr(Stdio::null());
            }
        }
        command.spawn().map_err(|error| error.to_string())
    }

    pub(super) fn spec_of(argv: &[String], extra: &Map<String, Value>, log_path: Option<&Path>, ram_mib: f64) -> Value {
        let mut spec =
            json!({"argv": argv, "extraEnv": extra, "log": log_path.map_or_else(String::new, |path| path.display().to_string())});
        if ram_mib != 0.0
            && let Some(fields) = spec.as_object_mut()
        {
            fields.insert("ramMiB".to_string(), json!(ram_mib.trunc() as i64));
        }
        spec
    }

    pub(super) fn expanded(path: &str) -> PathBuf {
        match (path.strip_prefix("~/"), std::env::var_os("HOME")) {
            (Some(rest), Some(home)) => PathBuf::from(home).join(rest),
            _ => PathBuf::from(path),
        }
    }
}

/// The end of a process.
pub(super) struct Stopping;

impl Stopping {
    const PATIENCE: Duration = Duration::from_secs(10);
    const TURN: Duration = Duration::from_millis(300);
    const KILL_PATIENCE: Duration = Duration::from_secs(5);

    pub(super) fn adopted(pid: i64) -> Value {
        if Signals::alive(pid) {
            if let Err(error) = Signals::terminate(pid) {
                return json!({"ok": false, "error": error.to_string()});
            }
            let mut spent = Duration::ZERO;
            while spent < Self::PATIENCE && Signals::alive(pid) {
                std::thread::sleep(Self::TURN);
                spent += Self::TURN;
            }
            if Signals::alive(pid)
                && let Err(error) = Signals::kill(pid)
            {
                return json!({"ok": false, "error": error.to_string()});
            }
        }
        json!({"ok": true, "adopted": true})
    }

    pub(super) fn child(child: &mut Child) -> Value {
        if let Err(error) = Signals::terminate(i64::from(child.id())) {
            return json!({"ok": false, "error": error.to_string()});
        }
        if !Self::waited(child, Self::PATIENCE) {
            if let Err(error) = child.kill() {
                return json!({"ok": false, "error": error.to_string()});
            }
            if !Self::waited(child, Self::KILL_PATIENCE) {
                return json!({"ok": false, "error": "the process did not end after SIGKILL"});
            }
        }
        json!({"ok": true})
    }

    fn waited(child: &mut Child, patience: Duration) -> bool {
        const TURN: Duration = Duration::from_millis(50);
        let mut spent = Duration::ZERO;
        while spent < patience {
            if !matches!(child.try_wait(), Ok(None)) {
                return true;
            }
            std::thread::sleep(TURN);
            spent += TURN;
        }
        false
    }
}

/// The times of the files a launch holds.
pub(super) struct LaunchFiles;

impl LaunchFiles {
    /// The file's time; for a folder, its newest file's, or its own when it is empty. 0 when it cannot be read.
    pub(super) fn newest_mtime(path: &str) -> i64 {
        let target = Launcher::expanded(path);
        let Ok(meta) = fs::metadata(&target) else {
            return 0;
        };
        if !meta.is_dir() {
            return FileTimes::modified(&meta);
        }
        let Ok(entries) = fs::read_dir(&target) else {
            return 0;
        };
        let newest = entries
            .flatten()
            .filter_map(|entry| entry.metadata().ok().filter(fs::Metadata::is_file))
            .map(|file| FileTimes::modified(&file))
            .max();
        // absent-ok: an empty folder is as old as itself.
        newest.unwrap_or_else(|| FileTimes::modified(&meta))
    }
}
