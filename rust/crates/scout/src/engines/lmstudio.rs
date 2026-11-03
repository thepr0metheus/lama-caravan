//! LM Studio: the app or its windowless daemon (llmster), port 1234. Its native API (0.4+) lists every model with the instances loaded from it; 0.3's older `/api/v0` says only loaded or not. Neither says the memory a model holds: that is the process's. It may be set to want a token, and then says 401 to everything.

use crate::commands::Commands;
use crate::engines::kind::{EngineKind, EngineWords};
use crate::engines::lms::LmsCli;
use crate::engines::procs::EngineProcs;
use crate::engines::wire::{EnginePort, Seen};
use rules::Coerce;
use serde_json::{Map, Value, json};
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex, MutexGuard, PoisonError};
use wire::HttpDate;

/// The kind.
pub struct LmStudio {
    cli: LmsCli,
    /// Most of `lms` wakes LM Studio up when it is not running: a read that met a stop half-way started the daemon again. Every sequence of commands holds this lock, and one that must not wake it asks `lms server status` first.
    lock: Mutex<()>,
}

impl LmStudio {
    /// The LM Studio of this home.
    pub fn new(home: PathBuf, commands: Arc<dyn Commands>) -> Self {
        Self { cli: LmsCli::new(home, commands), lock: Mutex::new(()) }
    }

    fn code_word(code: Option<i32>) -> String {
        code.map_or_else(|| "None".to_string(), |code| code.to_string())
    }

    fn held(&self) -> MutexGuard<'_, ()> {
        self.lock.lock().unwrap_or_else(PoisonError::into_inner)
    }

    /// `{instance id: {ttlMs, lastUsedTime}}` of what is loaded, from `lms ps --json`: the REST list does not say an idle limit. Empty when the command line is not there or does not answer, or its server is not running: `lms ps` would wake LM Studio up: then nobody knows.
    fn idle_limits(&self) -> BTreeMap<String, Value> {
        let (code, text) = {
            let _held = self.held();
            // Whether its server runs now: the one question that does not wake LM Studio.
            let (code, text) = self.cli.run(&["server", "status"], LmsCli::QUICK);
            if code != Some(0) || !text.contains("is running") {
                return BTreeMap::new();
            }
            self.cli.run(&["ps", "--json"], LmsCli::QUICK)
        };
        let rows = serde_json::from_str::<Value>(&text).ok().filter(|_| code == Some(0));
        rows.as_ref()
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            .filter(|row| row.is_object() && Coerce::truthy(row.get("identifier")))
            .map(|row| (Coerce::text(row.get("identifier")), row.clone()))
            .collect()
    }

    fn native_row(model: &Value, limits: &BTreeMap<String, Value>) -> Value {
        let instances: Vec<&Value> = model
            .get("loaded_instances")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            .filter(|instance| instance.is_object())
            .collect();
        let first = instances.first().copied();
        let config = first.and_then(|first| first.get("config")).filter(|config| config.is_object());
        let quant = model.get("quantization");
        let quant = quant.filter(|quant| quant.is_object()).map_or(quant, |quant| quant.get("name"));
        // The first instance's idle limit, as the window is the first one's: when it is let go, or that it stays until unloaded. Neither when `lms ps` did not say.
        let limit = first.and_then(|first| limits.get(&Coerce::text(first.get("id"))));
        let ttl = limit.and_then(|limit| EngineWords::number(limit.get("ttlMs"))).filter(|ttl| *ttl != 0);
        let last = limit.and_then(|limit| EngineWords::number(limit.get("lastUsedTime"))).filter(|last| *last != 0);
        let expires = match (ttl, last) {
            (Some(ttl), Some(last)) => HttpDate::iso_utc((last + ttl) / 1000),
            _ => String::new(),
        };
        let said_max = model.get("max_context_length").filter(|said| Coerce::truthy(Some(*said)));
        let mut fields = Map::new();
        fields.insert("type".to_string(), json!(EngineWords::text(model.get("type"), 20)));
        fields.insert("format".to_string(), json!(EngineWords::text(model.get("format"), 20)));
        fields.insert("family".to_string(), json!(EngineWords::text(model.get("architecture"), 40)));
        fields.insert("params".to_string(), json!(EngineWords::text(model.get("params_string"), 20)));
        fields.insert("quant".to_string(), json!(EngineWords::text(quant, 20)));
        fields.insert("fileBytes".to_string(), json!(EngineWords::number(model.get("size_bytes"))));
        fields.insert("loaded".to_string(), json!(!instances.is_empty()));
        fields.insert(
            "contextLength".to_string(),
            json!(first.and_then(|_| EngineWords::number(config.and_then(|config| config.get("context_length"))))),
        );
        fields.insert(
            "maxContextLength".to_string(),
            json!(EngineWords::number(said_max.or_else(|| config.and_then(|config| config.get("max_context_length"))))),
        );
        fields.insert("instances".to_string(), json!(instances.len()));
        fields.insert("expiresAt".to_string(), json!(expires));
        fields.insert(
            "staysLoaded".to_string(),
            limit.map_or(Value::Null, |limit| json!(limit.get("ttlMs").is_none_or(Value::is_null))),
        );
        EngineWords::row(&EngineWords::text(model.get("key"), 200), fields)
    }

    fn old_row(model: &Value) -> Value {
        let loaded = model.get("state").and_then(Value::as_str) == Some("loaded");
        let mut fields = Map::new();
        fields.insert("type".to_string(), json!(EngineWords::text(model.get("type"), 20)));
        fields.insert("format".to_string(), json!(EngineWords::text(model.get("compatibility_type"), 20)));
        fields.insert("family".to_string(), json!(EngineWords::text(model.get("arch"), 40)));
        fields.insert("quant".to_string(), json!(EngineWords::text(model.get("quantization"), 20)));
        fields.insert("loaded".to_string(), json!(loaded));
        fields.insert(
            "contextLength".to_string(),
            json!(EngineWords::number(model.get("loaded_context_length")).filter(|_| loaded)),
        );
        fields.insert("maxContextLength".to_string(), json!(EngineWords::number(model.get("max_context_length"))));
        EngineWords::row(&EngineWords::text(model.get("id"), 200), fields)
    }
}

impl EngineKind for LmStudio {
    fn id(&self) -> &'static str {
        "lmstudio"
    }

    fn label(&self) -> &'static str {
        "LM Studio"
    }

    fn default_port(&self) -> i64 {
        1234
    }

    fn process_prefixes(&self) -> &'static [&'static str] {
        &["lm studio", "lm-studio", "lmstudio", "llmster"]
    }

    /// Only its native API (0.4+) unloads; 0.3's `/api/v0` has no such verb, and is read, not driven. A model is not deleted from here: LM Studio has no verb for it, and which files are a model's it does not say: a guess would delete the wrong ones.
    fn controls(&self, seen: &Value) -> Vec<&'static str> {
        let native =
            seen.get("state").and_then(Value::as_str) == Some("ok") && seen.get("api").and_then(Value::as_str) == Some("v1");
        if native { vec!["unload"] } else { Vec::new() }
    }

    /// Every loaded instance of the model, by the ids the engine gives now: asked afresh, not taken from the last scan.
    fn unload(&self, port: &EnginePort<'_>, model: &str) -> String {
        let (status, body) = port.ask("/api/v1/models");
        let Some(body) = body.filter(|body| status == Some(200) && body.is_object()) else {
            return EngineWords::refused(
                status.filter(|status| !(200..300).contains(status)).or(Some(500)),
                "the model list did not answer",
            );
        };
        let ids: Vec<String> = body
            .get("models")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            .filter(|row| row.get("key").and_then(Value::as_str) == Some(model))
            .flat_map(|row| row.get("loaded_instances").and_then(Value::as_array).into_iter().flatten())
            .filter(|instance| Coerce::truthy(instance.get("id")))
            .map(|instance| Coerce::text(instance.get("id")))
            .collect();
        if ids.is_empty() {
            return format!("{model} is not loaded");
        }
        for instance in ids {
            let (status, words) = port.call("POST", "/api/v1/models/unload", &json!({"instance_id": instance}));
            let reason = EngineWords::refused(status, &words);
            if !reason.is_empty() {
                return reason;
            }
        }
        String::new()
    }

    /// Its own command line starts and stops it; what is learned is where it listens: the port, and whether only this machine may call.
    fn recipe(&self, _info: Option<&Value>, view: &Value) -> Option<Value> {
        if !self.cli.available() {
            return None;
        }
        let port =
            view.get("port").filter(|port| Coerce::truthy(Some(*port))).and_then(Coerce::int).unwrap_or(self.default_port());
        let loopback = view.get("listen").and_then(Value::as_str) == Some("loopback");
        Some(json!({"port": port, "bind": if loopback { "127.0.0.1" } else { "0.0.0.0" }}))
    }

    /// Installed where its command line is, the app and its windowless daemon alike; its server on its usual port, this machine only (LM Studio's own default).
    fn installed(&self, home: &Path) -> Option<Value> {
        LmsCli::available_in(home).then(|| json!({"port": self.default_port(), "bind": "127.0.0.1"}))
    }

    /// `lms daemon up`, then `lms server start` on the learned port and address. The command line returns when the server has started.
    fn start_server(&self, recipe: &Value, _procs: &EngineProcs) -> String {
        let _held = self.held();
        let (code, text) = self.cli.run(&["daemon", "up"], LmsCli::SLOW);
        if code != Some(0) {
            let said = LmsCli::said(&text);
            return if said.is_empty() { format!("lms daemon up exited with {}", Self::code_word(code)) } else { said };
        }
        let port = recipe
            .get("port")
            .filter(|port| Coerce::truthy(Some(*port)))
            .and_then(Coerce::int)
            .unwrap_or(self.default_port())
            .to_string();
        let bind = if Coerce::truthy(recipe.get("bind")) { Coerce::text(recipe.get("bind")) } else { "127.0.0.1".to_string() };
        let (code, text) = self.cli.run(&["server", "start", "-p", &port, "--bind", &bind], LmsCli::SLOW);
        if code == Some(0) {
            return String::new();
        }
        let said = LmsCli::said(&text);
        if said.is_empty() { format!("lms server start exited with {}", Self::code_word(code)) } else { said }
    }

    /// `lms daemon down`: the daemon holds the loaded models, and only its going frees their memory; where there is no daemon (the app runs the server), `lms server stop`.
    fn stop_server(&self, _pid: Option<i64>, _procs: &EngineProcs) -> String {
        let _held = self.held();
        let (code, _) = self.cli.run(&["daemon", "down"], LmsCli::SLOW);
        if code == Some(0) {
            return String::new();
        }
        let (code, text) = self.cli.run(&["server", "stop"], LmsCli::SLOW);
        if code == Some(0) {
            return String::new();
        }
        let said = LmsCli::said(&text);
        if said.is_empty() { format!("lms server stop exited with {}", Self::code_word(code)) } else { said }
    }

    fn read(&self, ask: &dyn Fn(&str) -> Seen) -> Option<Value> {
        let (status, body) = ask("/api/v1/models");
        let Some(status) = status else {
            return Some(json!({"state": "unreachable"}));
        };
        if matches!(status, 401 | 403) {
            return Some(json!({"state": "auth"}));
        }
        let listed = body.as_ref().filter(|_| status == 200).and_then(|body| body.get("models")).and_then(Value::as_array);
        if let Some(listed) = listed {
            let rows: Vec<&Value> =
                listed.iter().filter(|model| model.is_object() && !EngineWords::text(model.get("key"), 120).is_empty()).collect();
            let limits = if rows.iter().any(|model| Coerce::truthy(model.get("loaded_instances"))) {
                self.idle_limits()
            } else {
                BTreeMap::new()
            };
            let models: Vec<Value> = rows.iter().map(|model| Self::native_row(model, &limits)).collect();
            return Some(json!({"state": "ok", "version": "", "api": "v1", "models": models}));
        }
        let (status, body) = ask("/api/v0/models");
        let rows = body.as_ref().filter(|_| status == Some(200)).and_then(|body| body.get("data")).and_then(Value::as_array)?;
        // Its own mark: every entry says whether it is loaded. A plain OpenAI-style list of models has no `state`.
        if rows.is_empty() || !rows.iter().all(|model| model.is_object() && model.get("state").is_some()) {
            return None;
        }
        let models: Vec<Value> =
            rows.iter().filter(|model| !EngineWords::text(model.get("id"), 120).is_empty()).map(Self::old_row).collect();
        Some(json!({"state": "ok", "version": "", "api": "v0", "models": models}))
    }
}
