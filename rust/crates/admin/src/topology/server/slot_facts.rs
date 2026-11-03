//! What a slot says of itself: its model's size, its window, the notes on its card.

use super::*;

impl<'app> TopologyServer<'app> {
    pub(super) fn cell_meta(&self, health: Option<&Value>, config: &Config, is_command: bool) -> Map<String, Value> {
        let mut meta = health.and_then(|health| health.get("meta")).map_or_else(Map::new, Coerce::fields);
        let id = RunnerRegistry::runner_id(config);
        if is_command && health.and_then(|health| health.get("status")).and_then(Value::as_str) == Some("ok") {
            let state = CellAssets::of(self.app).source_state(
                &id,
                &Coerce::text(meta.get("source")),
                &Coerce::text(config.get("COMMAND")),
            );
            meta.insert("sourceState".to_string(), json!(state));
        }
        let mut target = Coerce::stripped(health.and_then(|health| health.get("targetLang")));
        if target.is_empty() {
            let key = match id.as_str() {
                "seamless" => Some("SEAMLESS_TGT_LANG"),
                "translate" => Some("TRANSLATE_TGT_LANG"),
                _ => None,
            };
            target = key.map_or_else(String::new, |key| Coerce::stripped(config.get(key)));
        }
        if !target.is_empty() {
            meta.insert("targetLang".to_string(), json!(target));
        }
        meta
    }

    pub(super) fn saved_command(&self, config: &Config) -> String {
        // absent-ok: a runner of no command has none to show.
        self.app.runners.for_config(config).command(config).unwrap_or_default()
    }

    /// `name-00001-of-00003.gguf`, cut at its number: what its other parts share.
    pub(super) fn split_part(path: &str) -> Option<(String, String)> {
        let stem = path.strip_suffix(".gguf")?;
        let (head, count) = stem.rsplit_once("-of-")?;
        let (start, number) = head.rsplit_once('-')?;
        let five = |word: &str| word.len() == 5 && word.chars().all(|digit| digit.is_ascii_digit());
        (five(number) && five(count)).then(|| (start.to_string(), count.to_string()))
    }

    pub(super) fn walk_for(folder: &Path, name: &str) -> Option<std::path::PathBuf> {
        let mut folders = vec![folder.to_path_buf()];
        while let Some(at) = folders.pop() {
            for entry in std::fs::read_dir(&at).into_iter().flatten().flatten() {
                let path = entry.path();
                if path.is_dir() {
                    folders.push(path);
                } else if entry.file_name().to_string_lossy() == name {
                    return Some(path);
                }
            }
        }
        None
    }

    pub(super) fn file_bytes(path: &Path) -> i64 {
        // absent-ok: a file that cannot be read has no size to say.
        std::fs::metadata(path).map_or(0, |found| i64::try_from(found.len()).unwrap_or(i64::MAX))
    }

    /// Weights on disk for a stopped cell's ≈VRAM badge, remembered five minutes.
    pub(super) fn slot_model_size(&self, model_path: &str, models_dir: &Path) -> i64 {
        if model_path.is_empty() {
            return 0;
        }
        let now = self.app.now();
        {
            let held = self.app.slot_sizes.held.lock().unwrap_or_else(PoisonError::into_inner);
            if let Some((size, _)) = held.get(model_path).filter(|(_, at)| now - *at < 300.0) {
                return *size;
            }
        }
        let mut path = Path::new(model_path).to_path_buf();
        if !path.is_file() {
            let name = path.file_name().map_or_else(String::new, |name| name.to_string_lossy().into_owned());
            if let Some(found) = Self::walk_for(models_dir, &name) {
                path = found;
            }
        }
        let mut size = 0;
        if path.is_file() {
            size = Self::file_bytes(&path);
            let shown = path.to_string_lossy().into_owned();
            if let (Some((start, count)), Some(folder)) = (Self::split_part(&shown), path.parent()) {
                let start_name =
                    Path::new(&start).file_name().map_or_else(String::new, |name| name.to_string_lossy().into_owned());
                let tail = format!("-of-{count}.gguf");
                size = std::fs::read_dir(folder)
                    .into_iter()
                    .flatten()
                    .flatten()
                    .filter(|entry| {
                        let name = entry.file_name().to_string_lossy().into_owned();
                        name.starts_with(&format!("{start_name}-")) && name.ends_with(&tail)
                    })
                    .map(|entry| Self::file_bytes(&entry.path()))
                    .sum();
            }
        }
        self.app.slot_sizes.held.lock().unwrap_or_else(PoisonError::into_inner).insert(model_path.to_string(), (size, now));
        size
    }

    /// Which launch files only a library holds; null for none.
    pub(super) fn launch_in_library(
        &self,
        cell_config: &Config,
        model_path: &str,
        config: &Config,
        locations: &Locations,
    ) -> Value {
        let named = cell_config
            .get("LLAMA_MODELS_DIR")
            .filter(|said| Coerce::truthy(Some(*said)))
            .or_else(|| config.get("LLAMA_MODELS_DIR"));
        let mut asked = Map::new();
        if let Some(named) = named {
            asked.insert("LLAMA_MODELS_DIR".to_string(), named.clone());
        }
        let root = self.app.models_dir_of(&asked).to_string_lossy().into_owned();
        let (mut roles, mut stores) = (Vec::new(), Vec::new());
        for (role, reference) in LaunchFiles::new(cell_config, model_path).files() {
            let Some(hit) = locations.locate(&reference, &root).filter(|hit| hit.in_library()) else {
                continue;
            };
            roles.push(role);
            if let Some(store) = &hit.store {
                let row = json!({"id": store.id, "name": store.name});
                if !stores.contains(&row) {
                    stores.push(row);
                }
            }
        }
        if roles.is_empty() { Value::Null } else { json!({"stores": stores, "roles": roles}) }
    }

    pub(super) fn slot_ctx_max(&self, config: &Config, trained: Option<i64>) -> Value {
        let runner = self.app.runners.for_config(config);
        if !runner.row().token_context {
            return Value::Null;
        }
        let raw = config.get(runner.row().context_field);
        json!(AskedWindow::of(&Coerce::text(raw), trained))
    }

    pub(super) fn trained_of(&self, cells: &CellCommand<'_>, model_path: &str, models_dir: &Path) -> Option<i64> {
        cells.trained_window(model_path, Some(models_dir))
    }

    /// A scout's crash note as the card reads it.
    pub(super) fn crash_note(note: Option<&Value>) -> Option<Value> {
        let note = note.filter(|note| note.is_object())?;
        let count = Coerce::int_or_zero(note.get("count")).filter(|count| *count > 0)?;
        let reason: String = Coerce::text(note.get("reason")).chars().take(300).collect();
        let letters: Vec<char> = Coerce::text(note.get("tail")).chars().collect();
        let tail: String = letters.iter().skip(letters.len().saturating_sub(1500)).collect();
        let mut out =
            json!({"count": count, "at": Coerce::text(note.get("at")), "kind": CellWords::crash_kind(&reason), "reason": reason});
        if !tail.is_empty() {
            Coerce::put(&mut out, "tail", json!(tail));
        }
        if Coerce::truthy(note.get("gaveUp")) {
            Coerce::put(&mut out, "gaveUp", json!(true));
        }
        Some(out)
    }

    /// While a scout's watchdog brings a crashed cell back, what the attempt before died of.
    pub(super) fn retry_note(crash: Option<&Value>, phase: &str) -> Option<Value> {
        let crash = crash.filter(|crash| !Coerce::truthy(crash.get("gaveUp")))?;
        if !matches!(phase, "starting" | "warming") {
            return None;
        }
        let tail = Coerce::text(crash.get("tail"));
        let reason = Coerce::text(crash.get("reason"));
        let source = if tail.is_empty() { &reason } else { &tail };
        Some(json!({"kind": CellWords::failure_kind(source), "detail": reason, "tail": tail}))
    }

    pub(super) fn vllm_stats(node: &Value) -> Value {
        if node.get("requestsProcessing").is_none_or(Value::is_null) {
            return Value::Null;
        }
        // absent-ok: `int(ln.get(key) or 0)`: what is not said to wait is nobody.
        let count = |key: &str| Coerce::whole(node.get(key));
        json!({"ok": true, "requestsRunning": count("requestsProcessing"), "requestsWaiting": count("requestsWaiting"), "genTps": node.get("genTps"), "promptTps": node.get("promptTps")})
    }

    pub(super) fn gpu_name_of(client: &Value) -> String {
        Coerce::text(
            client.get("gpus").and_then(Value::as_array).and_then(|cards| cards.first()).and_then(|card| card.get("name")),
        )
    }

    pub(super) fn boot_fields(client: &Value, port: Option<&Value>) -> (bool, bool) {
        let list = client.get("autostart").and_then(Value::as_array);
        let number = port.filter(|port| !port.is_boolean()).and_then(Coerce::int);
        (list.into_iter().flatten().any(|said| said.as_i64() == number && number.is_some()), list.is_some())
    }

    pub(super) fn file_of(path: &str, models_dir: &Path, locations: &Locations, app: &App) -> i64 {
        let size = TopologyServer::of(app).slot_model_size(path, models_dir);
        if size != 0 { size } else { locations.library_size(path) }
    }
}
