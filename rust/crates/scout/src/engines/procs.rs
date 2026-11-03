//! The machine's side of an engine's server: what a process is (Linux `/proc`), starting one detached from the scout, stopping one. Where `/proc` does not say, nothing is known of a process, and nothing is offered.

use crate::commands::Commands;
use crate::process::HostProcesses;
use os::clock::Clock;
use os::{Detached, Signals};
use rules::Coerce;
use serde_json::{Map, Value, json};
use std::fs;
use std::os::unix::fs::MetadataExt;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::Arc;
use std::time::Duration;

/// A server's process.
pub struct EngineProcs {
    logs: PathBuf,
    proc_root: PathBuf,
    home: PathBuf,
    tree: HostProcesses,
    clock: Arc<dyn Clock>,
}

impl EngineProcs {
    /// The environment mark of a server this scout started. Not a cell's mark: the stray-cell reaper must never take a server for a lost cell.
    const ENGINE_ENV: &'static str = "CARAVAN_SCOUT_ENGINE";

    /// The processes of this machine; the servers' output in `logs`.
    pub fn new(logs: PathBuf, proc_root: PathBuf, home: PathBuf, commands: Arc<dyn Commands>, clock: Arc<dyn Clock>) -> Self {
        let tree = HostProcesses::new(proc_root.clone(), commands);
        Self { logs, proc_root, home, tree, clock }
    }

    /// `{uid, exe, args, env, marked}` of a process; `None` when `/proc` does not say. The binary and environment only for the scout's own user: the machine keeps another user's to itself.
    pub fn info(&self, pid: i64) -> Option<Value> {
        let base = self.proc_root.join(pid.to_string());
        let uid = fs::metadata(&base).ok()?.uid();
        let args: Vec<String> = fs::read(base.join("cmdline")).map_or_else(
            |_| Vec::new(),
            |raw| {
                raw.split(|byte| *byte == 0)
                    .filter(|word| !word.is_empty())
                    .map(|word| String::from_utf8_lossy(word).into_owned())
                    .collect()
            },
        );
        let exe = fs::read_link(base.join("exe")).map_or_else(|_| String::new(), |path| path.display().to_string());
        let mut environment = Map::new();
        if let Ok(raw) = fs::read(base.join("environ")) {
            for item in raw.split(|byte| *byte == 0) {
                let item = String::from_utf8_lossy(item);
                if let Some((name, value)) = item.split_once('=') {
                    environment.insert(name.to_string(), json!(value));
                }
            }
        }
        let marked = environment.contains_key(Self::ENGINE_ENV);
        Some(json!({"uid": uid, "exe": exe, "args": args, "env": environment, "marked": marked}))
    }

    /// Starts a server in a session of its own, its output appended to `<logs>/<kind>.log`, with the scout's environment and the recipe's on top, and this scout's mark. "" when it started, else why not.
    pub fn spawn(&self, argv: &[String], environment: &Map<String, Value>, kind: &str) -> String {
        let Some((program, rest)) = argv.split_first() else {
            return "nothing to start".to_string();
        };
        let name = Path::new(program).file_name().map_or_else(String::new, |name| name.to_string_lossy().into_owned());
        let started = fs::create_dir_all(&self.logs).and_then(|()| {
            let log = fs::OpenOptions::new().create(true).append(true).open(self.logs.join(format!("{kind}.log")))?;
            let errors = log.try_clone()?;
            let mut command = Command::new(program);
            command
                .args(rest)
                .stdin(Stdio::null())
                .stdout(log)
                .stderr(errors)
                .current_dir(&self.home)
                .env_remove(HostProcesses::CELL_ENV);
            for (key, value) in environment {
                command.env(key, Coerce::text(Some(value)));
            }
            command.env(Self::ENGINE_ENV, kind);
            Detached::in_own_session(&mut command);
            command.spawn().map(drop)
        });
        match started {
            Ok(()) => String::new(),
            Err(error) => format!("{name} did not start: {error}"),
        }
    }

    /// SIGTERM; one that outlives `grace` is killed with all its children, or they would keep the cards' memory. "" when it is gone, else why not.
    pub fn terminate(&self, pid: i64, grace: Duration) -> String {
        const TURN: Duration = Duration::from_millis(250);
        if let Err(error) = Signals::terminate(pid) {
            return if error.kind() == std::io::ErrorKind::PermissionDenied {
                format!("not allowed to stop process {pid}")
            } else {
                String::new()
            };
        }
        let deadline = self.clock.monotonic() + grace.as_secs_f64();
        while self.clock.monotonic() < deadline {
            if !self.alive(pid) {
                return String::new();
            }
            std::thread::sleep(TURN);
        }
        let mut victims = vec![pid];
        victims.extend(self.tree.descendants(pid));
        for victim in victims {
            // Gone already is what was asked.
            drop(Signals::kill(victim));
        }
        std::thread::sleep(Duration::from_millis(500));
        if self.alive(pid) { format!("process {pid} would not stop") } else { String::new() }
    }

    /// Whether `pid` runs. A server this scout started is its child: one that exited is reaped here.
    fn alive(&self, pid: i64) -> bool {
        !Detached::exited(pid) && Signals::alive(pid)
    }
}
