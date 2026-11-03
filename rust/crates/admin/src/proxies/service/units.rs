//! The controller's systemd units and what they say of themselves.

use super::*;

impl<'app> Services<'app> {
    /// When this controller started, as `%a %Y-%m-%d %H:%M:%S`; "" for what never started.
    pub(super) fn stamp(epoch: i64) -> String {
        const DAYS: [&str; 7] = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
        if epoch == 0 {
            return String::new();
        }
        LocalTime::of(epoch).map_or_else(String::new, |local| {
            format!(
                "{} {} {:02}:{:02}:{:02}",
                // absent-ok: the weekday is 0..6: the table has them all.
                DAYS.get(local.weekday as usize).copied().unwrap_or_default(),
                local.date(),
                local.hour,
                local.minute,
                local.second
            )
        })
    }

    /// The proxy's chip: it is this controller's child, wherever it runs.
    pub fn proxy_brief(&self) -> Value {
        let proxy = self.proxy_status();
        let figure = |key: &str| Coerce::whole(proxy.get(key));
        json!({"unit": "agent-proxies (child)", "ok": true, "active": proxy.get("activeState"), "sub": proxy.get("subState"), "pid": figure("pid").to_string(), "since": Self::stamp(figure("sinceEpoch"))})
    }

    /// Container substitutes for the two service chips.
    pub fn container_briefs(&self) -> Vec<Value> {
        vec![
            json!({"unit": "lama-caravan (container)", "ok": true, "active": "active", "sub": "running", "pid": std::process::id().to_string(), "since": Self::stamp(self.app.services.started_at.trunc() as i64)}),
            self.proxy_brief(),
        ]
    }

    /// `show`'s lines as a map.
    pub(super) fn show_props(stdout: &str) -> BTreeMap<String, String> {
        stdout.lines().filter_map(|line| line.split_once('=')).map(|(key, value)| (key.to_string(), value.to_string())).collect()
    }

    /// One unit's chip.
    pub fn unit_brief(&self, unit: &str) -> Value {
        let show = self.systemctl(
            &["show", unit, "-p", "ActiveState", "-p", "SubState", "-p", "MainPID", "-p", "ExecMainStartTimestamp"],
            Duration::from_secs(5),
        );
        let props = Self::show_props(&Coerce::text(show.get("stdout")));
        let word = |key: &str, otherwise: &str| props.get(key).cloned().unwrap_or_else(|| otherwise.to_string());
        json!({"unit": unit, "ok": show.get("ok"), "active": word("ActiveState", ""), "sub": word("SubState", ""), "pid": word("MainPID", "0"), "since": word("ExecMainStartTimestamp", "")})
    }

    /// The legacy single server's unit.
    pub fn service_status(&self) -> Value {
        let show = self.systemctl(
            &[
                "show",
                &self.app.paths.service_name,
                "-p",
                "ActiveState",
                "-p",
                "SubState",
                "-p",
                "MainPID",
                "-p",
                "ExecMainStartTimestamp",
            ],
            Duration::from_secs(5),
        );
        let shown = Coerce::text(show.get("stdout"));
        let mut status: serde_json::Map<String, Value> =
            shown.lines().filter_map(|line| line.split_once('=')).map(|(key, value)| (key.to_string(), json!(value))).collect();
        let pid = status.get("MainPID").and_then(Value::as_str).unwrap_or("0").to_string();
        status.insert("ok".to_string(), show.get("ok").cloned().unwrap_or(Value::Null));
        status.insert("error".to_string(), show.get("stderr").cloned().unwrap_or(Value::Null));
        status.insert("cmdline".to_string(), json!(Self::read_cmdline(&pid)));
        Value::Object(status)
    }

    pub(super) fn read_cmdline(pid: &str) -> String {
        if pid.is_empty() || pid == "0" {
            return String::new();
        }
        std::fs::read(Path::new("/proc").join(pid).join("cmdline"))
            .map_or_else(|_| String::new(), |raw| Coerce::strip(&String::from_utf8_lossy(&raw).replace('\0', " ")).to_string())
    }

    /// The System page's Diagnostics. `probe` asks the legacy port, only when its unit runs.
    pub fn diagnostics(&self, service: &Value, probe: &dyn Fn() -> Value) -> Value {
        if self.app.paths.is_container {
            return self.container_diagnostics();
        }
        let uid = os::Account::uid();
        let runtime = self.app.env.get("XDG_RUNTIME_DIR").map_or_else(|| format!("/run/user/{uid}"), str::to_string);
        let bus = Path::new(&runtime).join("bus");
        let mut checks = vec![
            json!({"kind": if bus.exists() { "good" } else { "bad" }, "title": "systemd user bus", "detail": format!("{} {}", bus.display(), if bus.exists() { "exists" } else { "is missing" })}),
        ];
        let ok = Coerce::truthy(service.get("ok"));
        let legacy_active = ok && service.get("ActiveState").and_then(Value::as_str) == Some("active");
        let word = |key: &str, otherwise: &str| service.get(key).and_then(Value::as_str).unwrap_or(otherwise).to_string();
        if ok {
            let tail = if legacy_active { "" } else { " — off is normal when serving via cells" };
            checks.push(json!({"kind": if legacy_active { "good" } else { "muted" }, "title": "llamacpp-current.service (legacy)", "detail": format!("{} / {}, PID {}{tail}", word("ActiveState", "unknown"), word("SubState", "unknown"), word("MainPID", "0"))}));
        } else {
            let said = word("error", "");
            let words = if said.is_empty() { "systemctl --user failed".to_string() } else { Coerce::strip(&said).to_string() };
            checks.push(json!({"kind": "bad", "title": "llamacpp-current.service (legacy)", "detail": words}));
        }
        if legacy_active {
            let props = probe();
            let ready = props.is_object() && props.get("ok") != Some(&json!(false)) && props.get("error").is_none();
            let detail = if ready {
                "ready on configured port".to_string()
            } else if Coerce::truthy(props.get("error")) {
                Coerce::text(props.get("error"))
            } else {
                "not ready yet".to_string()
            };
            checks.push(
                json!({"kind": if ready { "good" } else { "warn" }, "title": "llama.cpp HTTP (legacy port)", "detail": detail}),
            );
        } else {
            checks.push(json!({"kind": "muted", "title": "llama.cpp HTTP (legacy port)", "detail": "legacy single-server not running — check skipped"}));
        }
        json!({"summary": "Admin uses systemctl --user, so the system service must talk to the service user's bus.", "fix": "Use Repair user service, or restart lama-caravan after ensuring /run/user/<uid>/bus exists.", "checks": checks, "legacyActive": legacy_active})
    }

    pub(super) fn container_diagnostics(&self) -> Value {
        let data = self.app.paths.data_dir.as_deref();
        let writable = data.is_some_and(os::Disk::writable);
        let data_word = data.map_or_else(|| "not set".to_string(), |dir| dir.display().to_string());
        let proxy = self.proxy_status();
        let active = |row: &Value| Coerce::truthy(row.get("active"));
        let figure = |row: &Value, key: &str| Coerce::whole(row.get(key));
        let checks = vec![
            json!({"kind": "good", "title": "container mode", "detail": format!("data dir {data_word}")}),
            json!({"kind": if writable { "good" } else { "bad" }, "title": "data dir writable", "detail": if writable { "ok" } else { "mount a writable volume at the data dir" }}),
            json!({"kind": if active(&proxy) { "good" } else { "bad" }, "title": "proxy child", "detail": if active(&proxy) { format!("pid {}, respawns {}", figure(&proxy, "pid"), figure(&proxy, "respawns")) } else { "dead — watchdog respawns it within seconds".to_string() }}),
        ];
        json!({"summary": "Controller runs in a Docker container; cells are served by caravan-scout hosts.", "fix": "If something is stuck, restart the container: docker restart <name>.", "checks": checks, "legacyActive": false})
    }

    /// `daemon-reload` and a restart of the legacy unit.
    pub fn repair_user_service(&self) -> Result<Value, AppError> {
        if self.app.paths.is_container {
            return Err(AppError::new("no systemd inside the container — restart the container itself (docker restart <name>)"));
        }
        let mut steps = Vec::new();
        let service = self.app.paths.service_name.clone();
        for args in [vec!["daemon-reload"], vec!["restart", service.as_str()]] {
            let result = self.systemctl(&args, Duration::from_secs(30));
            let mut step = serde_json::Map::new();
            step.insert("cmd".to_string(), json!(format!("systemctl --user {}", args.join(" "))));
            step.extend(Coerce::fields(&result));
            steps.push(Value::Object(step));
            if !Coerce::truthy(result.get("ok")) {
                let words = Coerce::text(result.get("stderr"));
                return Err(AppError::with_status(
                    if words.is_empty() { format!("systemctl --user {} failed", args.join(" ")) } else { words },
                    500,
                ));
            }
        }
        Ok(json!({"steps": steps}))
    }
}
