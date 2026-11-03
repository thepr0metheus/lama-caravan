//! A generic command cell (`CELL_KIND="command"`): checked on the request, launched in the background, as a llama cell is. Runs an arbitrary managed process in the same single-process cell. SECURITY: this executes a controller-supplied shell
//! command on this host; only the trusted admin can reach this endpoint. Until 2.31 all of it ran on the request, the download too: the controller waits 10 s for the answer, so a model of any size answered "timed out".

use crate::cells::Cells;
use crate::cells::records::NewRecord;
use crate::cells::table::Cell;
use crate::entry::names::ModelName;
use crate::errors::AppError;
use crate::log::Log;
use crate::models::{CacheKeeper, Fetch, ModelFetcher};
use crate::starts::StartRequest;
use crate::starts::assets::CellAssets;
use rules::Coerce;
use serde_json::{Map, Value, json};
use std::path::Path;
use std::sync::Arc;

/// The start on the request.
pub(super) struct CommandStart {
    start: StartRequest,
}

impl CommandStart {
    /// Answers the request.
    pub(super) fn run(start: StartRequest) -> Result<Value, AppError> {
        Self { start }.answer()
    }

    /// The command and its start line. The controller sends the whole start line: shell flags, exports, workdir, exec. This scout used to rebuild it, and the mirror had already lost `set -euo pipefail`: one config, two behaviours. Refusing beats guessing.
    fn lines(&self) -> Result<(String, String), AppError> {
        let said = StartRequest::word_of(&self.start.payload, "command");
        let said = if said.is_empty() { StartRequest::word_of(&self.start.config, "COMMAND") } else { said };
        let command = Self::without_exec(&said).to_string();
        if command.is_empty() {
            return Err(AppError::new("command is required for a command cell"));
        }
        let shell_line = StartRequest::word_of(&self.start.payload, "shellLine");
        if shell_line.is_empty() {
            return Err(AppError::new(
                "controller sent no shellLine for this command cell — it is older than this agent (needs lama-caravan v1.3.115+)",
            ));
        }
        Ok((command, shell_line))
    }

    fn answer(self) -> Result<Value, AppError> {
        let (command, shell_line) = self.lines()?;
        let files = self.model_files()?;
        let environment = self.start.process_env()?;
        let start = &self.start;
        let port = start.port()?;
        if let Some(refusal) = start.busy(port).or_else(|| start.short_of_vram(port)).or_else(|| start.short_of_ram(port)) {
            return Ok(refusal);
        }
        let (models, keeper) = start.shelf()?;
        let (models, keeper) = (Arc::clone(models), Arc::clone(keeper));
        let cell = start.cells.table.at(port);
        let ram_mib = self.ram_mib();
        let model_path = StartRequest::word_of(&start.payload, "modelPath");
        let name = ModelName::of(Some(&Value::Object(start.config.clone())), &model_path, port);
        // Its files stay or go as the controller asks, as a llama cell's do. Kept, a model is written to the disk once; not kept, every start writes it again.
        let cache_models = start.cache_models();
        {
            let mut facts = cell.facts();
            facts.ram_mib = ram_mib;
            facts.name.clone_from(&name);
            facts.cache_models = cache_models;
        }
        // What this start asks of its shelf, told before the first byte is copied.
        start.cells.asks(port, &files, &keeper);
        let shown = files.first().cloned().unwrap_or_else(|| Coerce::first_letters(&command, 80).to_string());
        let now = start.cells.clock.epoch() as i64;
        start.cells.table.say(port, &json!({"phase": "resolving", "modelPath": shown, "downloadedBytes": 0, "totalBytes": 0, "error": "", "startedAt": now}));
        let said = StartRequest::word_of(&start.payload, "healthPath");
        let health_path = if said.is_empty() { "/health".to_string() } else { Coerce::text(start.payload.get("healthPath")) };
        let launch = CommandLaunch {
            cells: Arc::clone(&start.cells),
            models,
            keeper,
            port,
            cell,
            command,
            shell_line,
            files,
            cache_models,
            hints: start.hints(),
            environment,
            name,
            health_path,
            ram_mib,
        };
        start.in_background(port, move || launch.run());
        Ok(json!({"ok": true, "status": "starting", "phase": "resolving", "port": port}))
    }

    /// `re.sub(r"^\s*exec\s+", "", line).strip()`.
    fn without_exec(line: &str) -> &str {
        let stripped = Coerce::strip(line);
        match stripped.strip_prefix("exec") {
            Some(rest) if rest.starts_with(char::is_whitespace) => Coerce::strip(rest),
            _ => stripped,
        }
    }

    /// The memory this start promises to keep resident, as it said it: 0 for none.
    fn ram_mib(&self) -> i64 {
        let said = self
            .start
            .payload
            .get("ram")
            .filter(|want| want.is_object())
            .and_then(|want| want.get("reserveMiB"))
            .filter(|said| Coerce::truthy(Some(*said)));
        // absent-ok: no promise, or one that does not read, is none: the check on the request has its own say.
        said.and_then(Coerce::float).map_or(0, |mib| (mib.trunc() as i64).max(0))
    }

    /// The model files the command reads, as the controller names them: `modelFiles`. An older controller sends none, and `MODEL_FILE` is then the one file.
    fn model_files(&self) -> Result<Vec<String>, AppError> {
        let Some(sent) = self.start.payload.get("modelFiles").filter(|sent| !sent.is_null()) else {
            let one = StartRequest::word_of(&self.start.config, "MODEL_FILE");
            return Ok(if one.is_empty() { Vec::new() } else { vec![one] });
        };
        let names = sent.as_array().map(|names| {
            names
                .iter()
                .map(|name| name.as_str().map(Coerce::strip).filter(|name| !name.is_empty()).map(str::to_string))
                .collect::<Option<Vec<String>>>()
        });
        names.flatten().ok_or_else(|| AppError::new("modelFiles must be a list of model paths"))
    }
}

/// The slow half of a command cell's start, off the request thread: the model files, the launcher's files from the controller, the cell's scratch folder, the process and its record, or nothing, when the cell was stopped meanwhile.
struct CommandLaunch {
    cells: Arc<Cells>,
    /// The shelf its models are kept on, and its keeper.
    models: Arc<ModelFetcher>,
    keeper: Arc<CacheKeeper>,
    port: i64,
    /// The cell the request made: the cancel token. Taken on the request: a stop in between would otherwise be met by a fresh cell and missed.
    cell: Arc<Cell>,
    command: String,
    shell_line: String,
    files: Vec<String>,
    cache_models: bool,
    hints: Option<Value>,
    environment: Map<String, Value>,
    name: String,
    health_path: String,
    ram_mib: i64,
}

impl CommandLaunch {
    fn holds(&self) -> bool {
        self.cells.table.holds(self.port, &self.cell)
    }

    fn say_failed(&self, words: &str) {
        self.cells.table.say(self.port, &json!({"phase": "error", "error": words}));
    }

    /// Each model file where this machine reads it: in place, in the cache, or downloaded now. Without the download the failure was quiet: the cell came up on its port and said "model file not found" only in its own log.
    fn fetch(&self) -> Result<Vec<String>, AppError> {
        let count = self.files.len();
        let mut held = Vec::with_capacity(count);
        for (at, raw) in self.files.iter().enumerate() {
            let short = Path::new(raw).file_name().map_or_else(String::new, |name| name.to_string_lossy().into_owned());
            let label = if count > 1 { format!("{short} ({}/{count})", at + 1) } else { String::new() };
            let hint = self.hints.as_ref().and_then(|hints| hints.get(raw)).cloned();
            let fetch = Fetch { report: true, label, use_cache: self.cache_models, port: self.port, hint };
            held.push(self.models.ensure(raw, &fetch)?.display().to_string());
        }
        Ok(held)
    }

    /// The controller owns the cell servers: its current copy is picked up before the launcher this command names runs. Never fatal.
    fn sync_assets(&self) {
        let assets = CellAssets {
            controller: self.cells.config.text("controllerUrl"),
            fields: self.models.token_fields(),
            home: self.cells.paths.home.clone(),
            http: &self.cells.http,
        };
        let synced = assets.sync(&self.command);
        if !synced.is_empty() {
            let words: Vec<String> = synced.iter().map(|(name, word)| format!("{name}={}", Coerce::text(Some(word)))).collect();
            Log::line(&format!("[llama-node] cell-assets :{} — {}", self.port, words.join(", ")));
        }
    }

    /// What the cell makes from its model: on its models' shelf and kept with them, so that a start of the same model uses what the last one made; emptied at the start when they are not kept.
    fn scratch(&self) -> std::io::Result<String> {
        if !self.cache_models {
            self.models.clear_scratch(self.port);
        }
        let scratch = self.models.scratch(self.port);
        std::fs::create_dir_all(&scratch)?;
        Ok(scratch.display().to_string())
    }

    fn run(&self) {
        let port = self.port;
        if !self.holds() {
            Log::line(&format!("[llama-node] :{port} start cancelled — the cell was stopped before it began"));
            return;
        }
        let held = match self.fetch() {
            Ok(held) => held,
            Err(error) => {
                if self.holds() {
                    self.say_failed(&error.message);
                }
                return;
            }
        };
        if !self.holds() {
            Log::line(&format!("[llama-node] :{port} start cancelled — the cell was stopped mid-download"));
            return;
        }
        // `modelPath` is filled in for a second reason: the safe purge keeps the files of RUNNING cells by reading it (and `files`, the rest of them); left empty, a purge deletes the weights out from under a running cell.
        // absent-ok: a command of no model files reads none.
        let model_abs = held.first().cloned().unwrap_or_default();
        let mut runtime = Map::new();
        runtime.insert("modelPath".to_string(), json!(model_abs));
        runtime.insert("port".to_string(), json!(port));
        runtime.insert("cellKind".to_string(), json!("command"));
        runtime.insert("command".to_string(), json!(self.command));
        if let Some((_, rest)) = held.split_first().filter(|(_, rest)| !rest.is_empty()) {
            runtime.insert("files".to_string(), json!(rest));
        }
        let weight = self.cells.table.splits().bytes_of(&held);
        let now = self.cells.clock.epoch() as i64;
        let shown = Coerce::first_letters(&self.command, 80);
        self.cells.table.say(port, &json!({"phase": "loading", "modelPath": shown, "downloadedBytes": 0, "totalBytes": 0, "error": "", "startedAt": now, "modelBytes": weight}));
        let log_path = self.cells.logs.path("command-cell", port);
        self.sync_assets();
        let scratch = match self.scratch() {
            Ok(scratch) => scratch,
            Err(error) => {
                self.say_failed(&error.to_string());
                return;
            }
        };
        let mut environment = self.environment.clone();
        let model_raw = self.files.first().map_or("", String::as_str);
        if let Some(root) = StartRequest::models_root(model_raw, &model_abs) {
            environment.insert("LLAMA_MODELS_DIR".to_string(), json!(root));
        }
        environment.insert(StartRequest::SCRATCH_ENV.to_string(), json!(scratch));
        let result = self.cell.process.start_command(
            &self.shell_line,
            runtime.clone(),
            Some(log_path.clone()),
            &environment,
            self.ram_mib as f64,
        );
        self.settle(runtime, &result, &log_path);
    }

    fn settle(&self, runtime: Map<String, Value>, result: &Value, log_path: &Path) {
        let port = self.port;
        let ok = result.get("ok") == Some(&Value::Bool(true));
        if ok && !self.holds() {
            Log::line(&format!("[llama-node] :{port} stopped during startup — terminating the fresh process"));
            self.cell.process.stop();
            return;
        }
        if !ok {
            let said =
                if Coerce::truthy(result.get("error")) { Coerce::text(result.get("error")) } else { "start failed".to_string() };
            self.say_failed(&said);
            return;
        }
        self.cells.table.say(port, &json!({"phase": "running", "error": ""}));
        // A marker for re-adoption: the exec'd command line with $PORT expanded (the shell resolves it before exec, so ps shows the resolved form).
        let line = self.command.replace("$PORT", &port.to_string()).replace("~/", "");
        let record = NewRecord {
            kind: "command",
            // absent-ok: `result.get("pid") or 0`: a start that says no pid is found by its marker.
            pid: result.get("pid").and_then(Value::as_i64).unwrap_or(0),
            marker: Coerce::first_letters(&line, 120).to_string(),
            config: runtime,
            log: log_path.display().to_string(),
            cache_models: self.cache_models,
            health_path: self.health_path.clone(),
            launch: self.cell.process.launch_spec(),
            name: self.name.clone(),
            ram_mib: self.ram_mib,
        };
        self.cells.records.add(port, record);
        if self.cache_models {
            self.keeper.commit(port);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn exec_goes_only_when_it_is_the_first_word() {
        assert_eq!(CommandStart::without_exec("  exec  python3 x.py "), "python3 x.py");
        assert_eq!(CommandStart::without_exec("execute y"), "execute y");
        assert_eq!(CommandStart::without_exec("exec"), "exec");
    }
}
