//! Ollama: `ollama serve`, its runner processes, port 11434. `/api/version` proves it is Ollama. `/api/ps` says what is loaded: the memory a model holds and how much of it is on the cards, the window it was loaded with, when `keep_alive` unloads it; `/api/tags` says what is installed. A tag with `remote_host` is a model Ollama runs on its own cloud, not on this machine.

use crate::engines::kind::{EngineKind, EngineWords};
use crate::engines::procs::EngineProcs;
use crate::engines::wire::{EnginePort, Seen};
use rules::Coerce;
use serde_json::{Map, Value, json};
use std::collections::BTreeMap;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::time::Duration;

/// The kind.
pub struct Ollama;

impl Ollama {
    /// What configures a server, by name: kept from the run it was learned from.
    const ENV_KEPT: [&'static str; 4] = ["OLLAMA_", "CUDA_VISIBLE_DEVICES", "HIP_VISIBLE_DEVICES", "ROCR_VISIBLE_DEVICES"];
    /// Where Ollama's own installers put it. The owner, 2026-10-24: Ollama belongs where it is installed as a rule, so that `command -v ollama` finds it.
    const SYSTEM_BINARIES: [&'static str; 2] = ["/usr/local/bin/ollama", "/usr/bin/ollama"];
    /// Where Ollama's own archive puts it in a home, and pip-style installs.
    const HOME_BINARIES: [&'static str; 3] = ["ollama/bin/ollama", ".local/bin/ollama", "bin/ollama"];
    /// How long a server told to stop gets before it is killed.
    const STOP_GRACE: Duration = Duration::from_secs(10);

    fn can_run(path: &Path) -> bool {
        std::fs::metadata(path).is_ok_and(|meta| meta.permissions().mode() & 0o111 != 0)
    }

    fn model(name: &str, tag: &Value, running: Option<&Value>, is_the_tag: bool, loaded_known: bool) -> Value {
        let details = tag.get("details").filter(|details| details.is_object());
        let said = |key: &str, limit: usize| EngineWords::text(details.and_then(|details| details.get(key)), limit);
        let mut fields = Map::new();
        fields.insert("format".to_string(), json!(said("format", 20)));
        fields.insert("family".to_string(), json!(said("family", 40)));
        fields.insert("params".to_string(), json!(said("parameter_size", 20)));
        fields.insert("quant".to_string(), json!(said("quantization_level", 20)));
        fields.insert("remote".to_string(), json!(Coerce::truthy(tag.get("remote_host"))));
        fields.insert("loaded".to_string(), if loaded_known { json!(running.is_some()) } else { Value::Null });
        if let Some(running) = running {
            fields.insert("memBytes".to_string(), json!(EngineWords::number(running.get("size"))));
            fields.insert("vramBytes".to_string(), json!(EngineWords::number(running.get("size_vram"))));
            fields.insert("contextLength".to_string(), json!(EngineWords::number(running.get("context_length"))));
            fields.insert("expiresAt".to_string(), json!(EngineWords::text(running.get("expires_at"), 40)));
        }
        if !is_the_tag {
            fields.insert("fileBytes".to_string(), json!(EngineWords::number(tag.get("size"))));
        }
        EngineWords::row(name, fields)
    }
}

impl EngineKind for Ollama {
    fn id(&self) -> &'static str {
        "ollama"
    }

    fn label(&self) -> &'static str {
        "Ollama"
    }

    fn default_port(&self) -> i64 {
        11434
    }

    fn process_prefixes(&self) -> &'static [&'static str] {
        &["ollama"]
    }

    fn controls(&self, seen: &Value) -> Vec<&'static str> {
        if seen.get("state").and_then(Value::as_str) == Some("ok") { vec!["unload", "delete"] } else { Vec::new() }
    }

    fn delete(&self, port: &EnginePort<'_>, name: &str) -> String {
        let (status, words) = port.call("DELETE", "/api/delete", &json!({"model": name}));
        EngineWords::refused(status, &words)
    }

    fn unload(&self, port: &EnginePort<'_>, model: &str) -> String {
        let (status, words) = port.call("POST", "/api/generate", &json!({"model": model, "keep_alive": 0}));
        EngineWords::refused(status, &words)
    }

    /// `ollama serve` as it runs: its binary, and the `OLLAMA_*` and device variables it was started with: what makes it "the one set up".
    fn recipe(&self, info: Option<&Value>, _view: &Value) -> Option<Value> {
        let info = info?;
        let exe = Coerce::text(info.get("exe"));
        let args = info.get("args").and_then(Value::as_array);
        let serves = args.and_then(|args| args.get(1)).and_then(Value::as_str) == Some("serve");
        if Path::new(&exe).file_name().is_none_or(|name| name != "ollama") || !serves {
            return None;
        }
        let kept: Map<String, Value> = info
            .get("env")
            .and_then(Value::as_object)
            .into_iter()
            .flatten()
            .filter(|(name, _)| Self::ENV_KEPT.iter().any(|prefix| name.starts_with(prefix)))
            .map(|(name, value)| (name.clone(), json!(Coerce::text(Some(value)))))
            .collect();
        Some(json!({"exe": exe, "args": ["serve"], "env": kept}))
    }

    /// How to start the Ollama installed here: the system's places first, then the home's.
    fn installed(&self, home: &Path) -> Option<Value> {
        let system = Self::SYSTEM_BINARIES.iter().map(|path| Path::new(path).to_path_buf());
        let own = Self::HOME_BINARIES.iter().map(|relative| home.join(relative));
        let found = system.chain(own).find(|path| Self::can_run(path))?;
        Some(json!({"exe": found.display().to_string(), "args": ["serve"], "env": {}}))
    }

    /// `ollama serve`, detached from the scout (a scout's restart leaves it running, as it leaves its cells), its output in a log of its own.
    fn start_server(&self, recipe: &Value, procs: &EngineProcs) -> String {
        let exe = Coerce::text(recipe.get("exe"));
        if !Self::can_run(Path::new(&exe)) {
            return format!("{} is not there to run", if exe.is_empty() { "ollama" } else { &exe });
        }
        let mut argv = vec![exe];
        match recipe.get("args").and_then(Value::as_array).filter(|args| !args.is_empty()) {
            Some(args) => argv.extend(args.iter().map(|word| Coerce::text(Some(word)))),
            None => argv.push("serve".to_string()),
        }
        let empty = Map::new();
        procs.spawn(&argv, recipe.get("env").and_then(Value::as_object).unwrap_or(&empty), self.id())
    }

    /// SIGTERM: Ollama unloads its models and stops its runners; one that does not go in time is killed, runners and all.
    fn stop_server(&self, pid: Option<i64>, procs: &EngineProcs) -> String {
        match pid.filter(|pid| *pid != 0) {
            Some(pid) => procs.terminate(pid, Self::STOP_GRACE),
            None => "nothing listens on its port".to_string(),
        }
    }

    fn read(&self, ask: &dyn Fn(&str) -> Seen) -> Option<Value> {
        let (status, version) = ask("/api/version");
        let Some(status) = status else {
            return Some(json!({"state": "unreachable"}));
        };
        if matches!(status, 401 | 403) {
            return Some(json!({"state": "auth"}));
        }
        let version = version
            .as_ref()
            .and_then(|version| version.get("version"))
            .filter(|said| said.is_string())
            .filter(|_| status == 200)?;
        let list_of = |(status, payload): Seen| {
            payload.filter(|_| status == Some(200)).and_then(|payload| payload.get("models").and_then(Value::as_array).cloned())
        };
        let loaded_list = list_of(ask("/api/ps"));
        let tags = list_of(ask("/api/tags"));
        let (loaded_known, installed_known) = (loaded_list.is_some(), tags.is_some());
        let mut loaded: BTreeMap<String, Value> = BTreeMap::new();
        let mut order: Vec<String> = Vec::new();
        for model in loaded_list.into_iter().flatten() {
            let name = EngineWords::text(model.get("name"), 120);
            if model.is_object() && !name.is_empty() {
                if !loaded.contains_key(&name) {
                    order.push(name.clone());
                }
                loaded.insert(name, model);
            }
        }
        let mut models = Vec::new();
        for tag in tags.into_iter().flatten().filter(Value::is_object) {
            let name = EngineWords::text(tag.get("name"), 120);
            if !name.is_empty() {
                let running = loaded.remove(&name);
                models.push(Self::model(&name, &tag, running.as_ref(), false, loaded_known));
            }
        }
        // Loaded but not installed: a tag list that did not answer, or a model removed while it ran. Still on the card, so still said.
        for name in order {
            if let Some(model) = loaded.remove(&name) {
                models.push(Self::model(&name, &model, Some(&model), true, true));
            }
        }
        let mut out = json!({"state": "ok", "version": EngineWords::text(Some(version), 40), "models": models});
        if let (false, Value::Object(fields)) = (installed_known, &mut out) {
            fields.insert("installedKnown".to_string(), json!(false));
        }
        Some(out)
    }
}
