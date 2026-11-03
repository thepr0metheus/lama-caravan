//! The services around the controller: systemd's units natively, and the proxy, its child: delivered as a program file, with no rebuild of the image.

use crate::app::App;
use os::{Detached, LocalTime};
use plumbing::{Log, NoAnswer, Ran};
use rules::{AppError, Coerce};
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};
use std::fs::OpenOptions;
use std::os::unix::fs::MetadataExt;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::{Mutex, PoisonError};
use std::time::Duration;

mod ports;
pub use ports::ListeningPorts;

mod units;

/// What `subprocess.run` left, as `procs.run` says it.
pub struct ToolAnswer;

impl ToolAnswer {
    /// `{ok, code, stdout, stderr}`; a tool that did not run is code -1.
    pub fn of(tool: &str, ran: Result<Ran, NoAnswer>) -> Value {
        match ran {
            Ok(ran) => json!({"ok": ran.ok(), "code": ran.code, "stdout": ran.stdout, "stderr": ran.stderr}),
            Err(no) => json!({"ok": false, "code": -1, "stdout": "", "stderr": no.words(tool)}),
        }
    }
}

/// One child the controller keeps alive.
struct KeptChild {
    child: Option<Child>,
    stamp: Option<(i64, u64)>,
    port: Option<String>,
    leaving: Vec<Child>,
    started_at: f64,
    respawns: i64,
    watching: bool,
    missing: bool,
}

impl KeptChild {
    const fn new() -> Self {
        Self {
            child: None,
            stamp: None,
            port: None,
            leaving: Vec::new(),
            started_at: 0.0,
            respawns: -1,
            watching: false,
            missing: false,
        }
    }

    fn alive(&mut self) -> bool {
        self.child.as_mut().is_some_and(|child| matches!(child.try_wait(), Ok(None)))
    }

    fn status(&mut self) -> Value {
        let alive = self.alive();
        // absent-ok: a process that is not alive has no id to show.
        let pid = self.child.as_ref().filter(|_| alive).map_or(0, Child::id);
        json!({"active": alive, "activeState": if alive { "active" } else { "failed" }, "subState": if alive { "running" } else { "dead" }, "pid": pid, "sinceEpoch": if alive { self.started_at.trunc() as i64 } else { 0 }, "respawns": self.respawns.max(0)})
    }
}

/// The children.
pub struct ServiceChildren {
    proxy: Mutex<KeptChild>,
    started_at: f64,
}

impl ServiceChildren {
    /// None yet; `now` is when this controller started.
    pub fn new(now: f64) -> Self {
        Self { proxy: Mutex::new(KeptChild::new()), started_at: now }
    }
}

/// The view.
pub struct Services<'app> {
    app: &'app App,
}

impl<'app> Services<'app> {
    const PROXY_WATCH: Duration = Duration::from_millis(500);
    const PROXY_PORT_VARIABLE: &'static str = "CARAVAN_RUST_ENTRY_PORT";
    /// Who keeps the proxy: it runs in a session of its own, and only this word makes it end with this process.
    const PROXY_KEEPER_VARIABLE: &'static str = "CARAVAN_PROXY_KEEPER";

    /// The view.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    fn log_file(&self, name: &str) -> PathBuf {
        let dir = &self.app.paths.agent_proxy_log_dir;
        dir.parent().unwrap_or(dir).join(name)
    }

    /// `systemctl --user …`.
    pub fn systemctl(&self, args: &[&str], timeout: Duration) -> Value {
        let mut argv = vec!["systemctl", "--user"];
        argv.extend_from_slice(args);
        ToolAnswer::of("systemctl", self.app.commands.run(&argv, timeout))
    }

    fn spawn_with(&self, program: &str, env: &[(&str, &str)], log_name: &str) -> std::io::Result<Child> {
        let mut command = Command::new(program);
        for (name, value) in env {
            command.env(name, value);
        }
        self.spawned(&mut command, log_name)
    }

    fn spawned(&self, command: &mut Command, log_name: &str) -> std::io::Result<Child> {
        let log = self.log_file(log_name);
        if let Some(parent) = log.parent() {
            std::fs::create_dir_all(parent)?;
        }
        let out = OpenOptions::new().create(true).append(true).open(&log)?;
        let err = out.try_clone()?;
        command.stdin(Stdio::null()).stdout(out).stderr(err).current_dir(&self.app.paths.project_root);
        Detached::in_own_session(command);
        command.spawn()
    }

    /// The port the proxy is to listen on: the entry's, for as long as it is open.
    fn proxy_port(&self) -> Option<String> {
        let payload = super::config::ProxiesConfig::of(self.app).read_payload();
        let port = Coerce::whole(payload.get("entry").and_then(|entry| entry.get("port")));
        (port != 0).then(|| port.to_string())
    }

    fn proxy_program(&self) -> PathBuf {
        self.app.paths.project_root.join("bin/caravan-proxy")
    }

    fn proxy_stamp(&self) -> Option<(i64, u64)> {
        let meta = std::fs::metadata(self.proxy_program()).ok()?;
        Some((meta.mtime() * 1_000_000_000 + meta.mtime_nsec(), meta.size()))
    }

    /// One look of the proxy's watchdog: it is respawned when it died, and replaced when its file changed; the old one finishes what it is doing.
    fn proxy_tick(&self) {
        let mut held = self.app.services.proxy.lock().unwrap_or_else(PoisonError::into_inner);
        held.leaving.retain_mut(|old| matches!(old.try_wait(), Ok(None)));
        // The proxy refuses to start with no data folder: said once, and not started twice a second.
        let stamp = self.proxy_stamp().filter(|_| self.app.paths.data_dir.is_some());
        let Some(stamp) = stamp else {
            if !held.missing {
                held.missing = true;
                let why = if self.app.paths.data_dir.is_some() {
                    format!("{} is not there", self.proxy_program().display())
                } else {
                    "it takes CARAVAN_DATA_DIR, and none is set".to_string()
                };
                Log::line(&format!("caravan-proxy: {why}"));
            }
            return;
        };
        held.missing = false;
        let port = self.proxy_port();
        if held.port != port
            && let Some(mut old) = held.child.take()
        {
            // The entry moved or closed: the port the old one holds is to be free now, not when its last request ends.
            drop(old.kill());
            drop(old.wait());
        }
        let Some(listen_on) = port.clone() else {
            held.port = None;
            return;
        };
        let dead = !held.alive();
        if !dead && Some(stamp) == held.stamp {
            return;
        }
        if !dead && let Some(old) = held.child.take() {
            held.leaving.push(old);
        }
        let keeper = std::process::id().to_string();
        match self.spawn_with(
            &self.proxy_program().to_string_lossy(),
            &[(Self::PROXY_PORT_VARIABLE, listen_on.as_str()), (Self::PROXY_KEEPER_VARIABLE, keeper.as_str())],
            "rust-proxy.log",
        ) {
            Ok(child) => {
                held.child = Some(child);
                held.stamp = Some(stamp);
                held.port = port;
                held.started_at = self.app.now();
                held.respawns += 1;
            }
            Err(error) => Log::line(&format!("caravan-proxy: did not start: {error}")),
        }
    }

    /// Starts the proxy and its watchdog.
    pub fn start_proxy(&self) {
        self.proxy_tick();
        let mut held = self.app.services.proxy.lock().unwrap_or_else(PoisonError::into_inner);
        if !held.watching {
            held.watching = true;
            if let Some(app) = self.app.shared() {
                plumbing::Ticking::in_background("proxy-watchdog", Self::PROXY_WATCH, move || Services::of(&app).proxy_tick());
            }
        }
    }

    /// Whether a proxy that was replaced is still answering what it holds.
    pub fn proxy_finishing(&self) -> bool {
        let mut held = self.app.services.proxy.lock().unwrap_or_else(PoisonError::into_inner);
        held.leaving.retain_mut(|old| matches!(old.try_wait(), Ok(None)));
        !held.leaving.is_empty()
    }

    /// The System modal's word on the proxy child.
    pub fn proxy_status(&self) -> Value {
        let mut held = self.app.services.proxy.lock().unwrap_or_else(PoisonError::into_inner);
        let mut status = held.status();
        if let Value::Object(fields) = &mut status {
            fields.insert("programMissing".to_string(), json!(held.missing));
            fields.insert("leaving".to_string(), json!(held.leaving.len()));
        }
        status
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_kernels_table_says_who_listens() {
        let root = std::env::temp_dir().join(format!("listening-{}", std::process::id()));
        std::fs::create_dir_all(root.join("net")).unwrap();
        std::fs::write(root.join("net/tcp"), "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n   0: 00000000:1F90 00000000:0000 0A 00000000:00000000 00:00000000 00000000  1000        0 111 1 0\n   1: 0100007F:0050 0100007F:0051 01 00000000:00000000 00:00000000 00000000  1000        0 222 1 0\n").unwrap();
        let ports = ListeningPorts::of(&root);
        assert!(ports.known);
        assert!(ports.busy(8080));
        assert!(!ports.busy(80));
        assert_eq!(ports.ports(), [8080]);
        assert_eq!(ports.owner(80), (0, String::new()));
        assert_eq!(ports.owner(8080), (0, "?".to_string()));
        std::fs::remove_dir_all(&root).unwrap();
        assert!(!ListeningPorts::of(&root).known);
    }

    #[test]
    fn a_tool_that_did_not_run_says_why() {
        let said = ToolAnswer::of("systemctl", Err(NoAnswer::NotFound));
        assert_eq!(
            said,
            json!({"ok": false, "code": -1, "stdout": "", "stderr": "[Errno 2] No such file or directory: 'systemctl'"})
        );
    }
}
