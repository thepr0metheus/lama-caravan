//! A llama cell's start: checked on the request, launched in the background. Downloading a multi-GB model can take minutes, far longer than the admin's HTTP client timeout, so the heavy work runs off the request thread; its progress
//! goes out as the cell's phase and bytes.

use crate::cells::Cells;
use crate::cells::records::NewRecord;
use crate::cells::table::Cell;
use crate::entry::names::ModelName;
use crate::errors::AppError;
use crate::log::Log;
use crate::models::fetcher::ModelFetcher;
use crate::paths::ScoutPaths;
use crate::starts::StartRequest;
use crate::starts::artifacts::{CellArtifacts, LaunchWords};
use rules::Coerce;
use sent_args::SentArgs;
use serde_json::{Map, Value, json};
use std::path::{Path, PathBuf};
use std::sync::Arc;

mod sent_args;
#[cfg(test)]
mod tests;

/// The start on the request.
pub(super) struct LlamaStart {
    start: StartRequest,
}

impl LlamaStart {
    /// Answers the request.
    pub(super) fn run(start: StartRequest) -> Result<Value, AppError> {
        Self { start }.answer()
    }

    fn runner_and_binary(&self) -> Result<(String, String), AppError> {
        let said = StartRequest::word_of(&self.start.config, "RUNNER");
        let runner = if said.is_empty() { "llama-server".to_string() } else { said.to_lowercase() };
        if !matches!(runner.as_str(), "llama-server" | "prism") {
            return Err(AppError::new(format!("unknown native runner: {runner}")));
        }
        let binary = Coerce::strip(&self.start.cells.config.text("llamaServerBin")).to_string();
        if binary.is_empty() && runner == "llama-server" {
            return Err(AppError::new("llamaServerBin not configured in config.json — run install.sh first"));
        }
        Ok((runner, binary))
    }

    /// The full admin form config (all llama.cpp flags), or a minimal one from the legacy individual fields for older callers.
    fn fill_legacy_config(&mut self, model: &str) {
        let start = &mut self.start;
        if start.config.is_empty() {
            start.config.insert("MODEL_FILE".to_string(), json!(model));
            for (key, field) in [("N_GPU_LAYERS", "gpuLayers"), ("CTX_SIZE", "ctxSize")] {
                start.config.insert(key.to_string(), start.payload.get(field).cloned().unwrap_or(Value::Null));
            }
        }
    }

    fn answer(mut self) -> Result<Value, AppError> {
        let (runner, binary) = self.runner_and_binary()?;
        let said = StartRequest::word_of(&self.start.payload, "modelPath");
        let model = if said.is_empty() { StartRequest::word_of(&self.start.config, "MODEL_FILE") } else { said };
        if model.is_empty() {
            return Err(AppError::new("modelPath is required"));
        }
        // A malformed environment is refused before a port is leased: a refusal leaves the cell holding nothing.
        self.start.process_env()?;
        self.fill_legacy_config(&model);
        let mut start = self.start;
        let id = start.cell_id()?;
        let cell = start.cells.table.at(&id);
        if let Some(refusal) = start.busy(&cell) {
            return Ok(refusal);
        }
        let port = start.lease_port(&cell)?;
        let environment = start.process_env()?;
        let config = start.config.clone();
        let name = ModelName::of(Some(&Value::Object(config.clone())), &model, &id);
        cell.facts().name.clone_from(&name);
        // The projector and the draft are this start's only when the command it was sent loads them: what follows, from the cache's word to the cell's report, reads these two.
        let args = SentArgs::of(&start.payload);
        let mmproj = args.wanted(SentArgs::PROJECTOR, StartRequest::word_of(&config, "MMPROJ_FILE"));
        let spec = args.wanted(SentArgs::DRAFT, StartRequest::word_of(&config, "SPEC_DRAFT_MODEL_FILE"));
        // The cache is told what this start asks of it before the first byte is copied: a trim that another start's end triggers must find these files wanted, whole or half copied. A llama cell's
        // models are the model cache's: no runner of one needs the folder for Strata's files.
        start.cells.asks(&cell, &[model.clone(), mmproj.clone(), spec.clone()], &start.cells.keeper);
        let cache_models = start.cache_models();
        cell.facts().cache_models = cache_models;
        let now = start.cells.clock.epoch() as i64;
        start.cells.table.say(&id, &json!({"phase": "resolving", "modelPath": model, "downloadedBytes": 0, "totalBytes": 0, "error": "", "startedAt": now}));
        let launch = LlamaLaunch {
            cells: Arc::clone(&start.cells),
            id: id.clone(),
            port,
            cell,
            binary,
            config,
            model,
            mmproj,
            spec,
            cache_models,
            args,
            hints: start.hints(),
            environment,
            name,
            runner,
        };
        start.in_background(&id, move || launch.run());
        Ok(json!({"ok": true, "status": "starting", "phase": "resolving", "cellId": id, "port": port}))
    }
}

/// The files a launch reads, where they are on this machine.
#[derive(Debug, Clone)]
struct Fetched {
    model: String,
    mmproj: String,
    spec: String,
}

/// The slow half of a llama cell's start, off the request thread: fetches the model files, writes the cell's artifacts, starts `llama-server` and registers it, or gives up cleanly when the cell was stopped meanwhile.
struct LlamaLaunch {
    cells: Arc<Cells>,
    /// The cell's own name.
    id: String,
    /// The port its run was leased.
    port: i64,
    /// The cell the request made: a stop drops it, so a later lookup no longer returns it: the cancel token.
    cell: Arc<Cell>,
    binary: String,
    config: Map<String, Value>,
    model: String,
    mmproj: String,
    spec: String,
    cache_models: bool,
    args: SentArgs,
    hints: Option<Value>,
    environment: Map<String, Value>,
    name: String,
    runner: String,
}

impl LlamaLaunch {
    fn holds(&self) -> bool {
        self.cells.table.holds(&self.id, &self.cell)
    }

    /// A start that failed says why, and gives its port back: no run of it holds the port.
    fn fail(&self, words: &str) {
        self.cells.table.say(&self.id, &json!({"phase": "error", "error": words}));
        self.cells.table.release(&self.cell);
    }

    fn cancelled(&self) {
        Log::line(&format!("[llama-node] {} start cancelled — the cell was stopped mid-download", self.id));
    }

    fn fetch(&self, use_cache: bool) -> Result<Fetched, AppError> {
        let (model, mmproj, spec) =
            self.cells.models.download_all(&self.model, &self.mmproj, &self.spec, use_cache, &self.id, self.hints.as_ref())?;
        Ok(Fetched { model, mmproj, spec })
    }

    /// The Prism runtime, when this is a Prism cell: the server's path. Its download reports as the model's would.
    fn ensure_runtime(&mut self) -> Result<(), AppError> {
        if self.runner != "prism" {
            return Ok(());
        }
        let (table, id, cell) = (Arc::clone(&self.cells.table), self.id.clone(), Arc::clone(&self.cell));
        let progress = move |downloaded: u64, total: u64, file: &str| {
            if table.holds(&id, &cell) {
                table.say(
                    &id,
                    &json!({"phase": "downloading", "downloadedBytes": downloaded, "totalBytes": total, "downloadingFile": file}),
                );
            }
        };
        self.binary = self.cells.prism.ensure(&progress)?;
        self.environment.extend(crate::runtimes::prism::PrismRuntime::environment(&self.binary));
        self.cells.prism.validate_args(&self.binary, self.args.as_sent())
    }

    /// What the process's status shows. Bookkeeping only: the real `-ngl` comes from the args the controller sends. A string field: an exact count, or "auto" or "all".
    fn runtime_of(&self, files: &Fetched) -> Result<Map<String, Value>, AppError> {
        let layers_said = StartRequest::word_of(&self.config, "N_GPU_LAYERS").to_lowercase();
        // absent-ok: 999 is what a layer count of no number says: all of them, as the args have it.
        let gpu_layers = if layers_said.is_empty() || matches!(layers_said.as_str(), "auto" | "all" | "max") {
            999
        } else {
            layers_said.parse().unwrap_or(999)
        };
        let ctx_said = self.config.get("CTX_SIZE").filter(|said| Coerce::truthy(Some(*said)));
        let ctx_size = match ctx_said {
            Some(said) => Coerce::int(said)
                .ok_or_else(|| AppError::new(format!("CTX_SIZE is not a number: {}", Coerce::text(Some(said)))))?,
            None => 4096,
        };
        // The operator's word, whether a draft file is loaded or not: that is the path's to say, empty unless the command loads one (SentArgs). Exposed in the heartbeat so that the UI can show the MTP badge
        // for built-in MTP, where the path is empty; and speculation switched off says "none", true of the start, which the board's chip (cell-plan.js CellDraft) reads, with no path, as no draft.
        let spec_type = StartRequest::word_of(&self.config, "SPEC_TYPE").to_lowercase();
        let spec_type = if spec_type == "mtp" { "draft-mtp".to_string() } else { spec_type };
        let mut runtime = Map::new();
        runtime.insert("modelPath".to_string(), json!(files.model));
        runtime.insert("mmprojPath".to_string(), json!(files.mmproj));
        runtime.insert("specPath".to_string(), json!(files.spec));
        runtime.insert("specType".to_string(), json!(spec_type));
        runtime.insert("port".to_string(), json!(self.port));
        runtime.insert("gpuLayers".to_string(), json!(gpu_layers));
        runtime.insert("ctxSize".to_string(), json!(ctx_size));
        if self.runner == "prism" {
            runtime.insert("runner".to_string(), json!(self.runner));
        }
        Ok(runtime)
    }

    fn artifacts(&self) -> CellArtifacts<'_> {
        let paths: &ScoutPaths = &self.cells.paths;
        CellArtifacts { paths, host_id: self.cells.config.text("hostId"), now: self.cells.clock.epoch() as i64 }
    }

    /// Writes what stands next to the cell, and starts the process.
    fn launched(&self, files: &Fetched, log_path: &Path) -> Result<(Map<String, Value>, Value), AppError> {
        let args = self.args.resolved(files)?;
        let mut runtime = self.runtime_of(files)?;
        let written = self.artifacts().write(
            &self.id,
            self.port,
            &LaunchWords {
                binary: &self.binary,
                args: &args,
                config: &self.config,
                runtime: &runtime,
                environment: &self.environment,
            },
        );
        let written = written.map_err(|error| AppError::with_status(error.to_string(), 500))?;
        runtime.insert("artifact".to_string(), written);
        // A Stop that arrived while the files came has already dropped the cell and unregistered it. Starting now would resurrect a process nobody owns: exactly how a llama-server once survived with 10.7 GB of VRAM while the board showed
        // its port as stopped.
        if !self.holds() {
            self.cancelled();
            return Err(AppError::new(""));
        }
        let ram = self.cell.facts().ram_mib as f64;
        let result =
            self.cell.process.start(&self.binary, &args, runtime.clone(), Some(log_path.to_path_buf()), &self.environment, ram);
        Ok((runtime, result))
    }

    fn run(mut self) {
        let fetched = self.ensure_runtime().and_then(|()| self.fetch(self.cache_models));
        let files = match fetched {
            Ok(files) => files,
            Err(error) => {
                if self.holds() {
                    self.fail(&error.message);
                }
                return;
            }
        };
        // Stopped while the files came: nothing more is said or written for a start that no longer holds the port.
        if !self.holds() {
            self.cancelled();
            return;
        }
        // What its files weigh here: what the board counts its reading against while it loads.
        let weight = self.cells.table.splits().bytes_of(&[files.model.clone(), files.mmproj.clone(), files.spec.clone()]);
        self.cells.table.say(&self.id, &json!({"phase": "loading", "modelBytes": weight}));
        // Per CELL, not one file for the whole host: every llama cell used to write to one log and each new start renamed it away, so a crashed cell's card quoted whichever cell had spawned last.
        // By its name, not its port: a cell's logs follow it whatever port each run held.
        let log_path = self.cells.logs.path("llama-server", &self.id);
        let (mut runtime, mut result) = match self.launched(&files, &log_path) {
            Ok(done) => done,
            Err(error) => {
                if self.holds() {
                    self.fail(&error.message);
                }
                return;
            }
        };
        if let Some(again) = self.after_corruption(&files, &result, &log_path) {
            match again {
                Some((new_runtime, new_result)) => (runtime, result) = (new_runtime, new_result),
                None => return,
            }
        }
        self.settle(&runtime, &result, &log_path);
    }

    /// If this start failed on a truncated or corrupted cached file: deletes the bad files and downloads once more before giving up. Only this attempt's own error: a failed start never ran, so the log on the port is the PREVIOUS run's, and
    /// reading it deleted a good model when the binary was missing and an old run had said "corrupted". `None`: nothing to do. `Some(None)`: it ended here.
    #[allow(clippy::type_complexity, reason = "three answers, each said in its doc: not worth a type of its own")]
    fn after_corruption(&self, files: &Fetched, result: &Value, log_path: &Path) -> Option<Option<(Map<String, Value>, Value)>> {
        let ok = result.get("ok") == Some(&Value::Bool(true));
        let error = Coerce::text(result.get("error"));
        if ok || !self.cache_models || !ModelFetcher::is_corruption_error(&error) {
            return None;
        }
        Log::line("[llama-node] corruption detected in cached file(s), deleting and retrying…");
        let models = &self.cells.models;
        let all: Vec<PathBuf> =
            [&files.model, &files.mmproj, &files.spec].into_iter().filter(|path| !path.is_empty()).map(PathBuf::from).collect();
        let (mine, others): (Vec<PathBuf>, Vec<PathBuf>) = all.into_iter().partition(|path| models.downloaded.has(path));
        if let Some(other) = others.first() {
            // Not downloaded by this scout: read in place from a library, or in the cache from before the scout kept a record. Not its to delete: a library's file is nobody's cache.
            self.fail(&format!("the model file looks damaged: {} — this scout did not download it, so it left it alone; replace or delete it on this machine", other.display()));
            return Some(None);
        }
        for path in &mine {
            match std::fs::remove_file(path) {
                Ok(()) => {
                    models.downloaded.forget(path);
                    Log::line(&format!("[llama-node]   deleted: {}", path.display()));
                }
                Err(error) if error.kind() == std::io::ErrorKind::NotFound => models.downloaded.forget(path),
                Err(error) => Log::line(&format!("[llama-node]   delete failed for {}: {error}", path.display())),
            }
        }
        self.cells.table.say(
            &self.id,
            &json!({"phase": "downloading", "downloadedBytes": 0, "totalBytes": 0, "downloadingFile": "re-downloading…"}),
        );
        let done = self.fetch(false).and_then(|fresh| {
            self.cells.table.say(&self.id, &json!({"phase": "loading"}));
            self.launched(&fresh, log_path)
        });
        match done {
            Ok(done) => Some(Some(done)),
            Err(error) => {
                if self.holds() {
                    self.fail(&error.message);
                }
                Some(None)
            }
        }
    }

    fn settle(&self, runtime: &Map<String, Value>, result: &Value, log_path: &Path) {
        if result.get("ok") != Some(&Value::Bool(true)) {
            let said =
                if Coerce::truthy(result.get("error")) { Coerce::text(result.get("error")) } else { "start failed".to_string() };
            self.fail(&said);
            return;
        }
        if !self.holds() {
            // Stopped between the start and here (the corruption retry keeps this window open for a re-download). Registering would re-add the cell the stop just deleted; letting the process live would orphan it.
            Log::line(&format!("[llama-node] {} stopped during startup — terminating the fresh process", self.id));
            self.cell.process.stop();
            return;
        }
        self.cells.table.say(&self.id, &json!({"phase": "running", "error": ""}));
        let record = NewRecord {
            kind: "llama",
            port: Some(self.port),
            // absent-ok: `result.get("pid") or 0`: a start that says no pid is found by its marker.
            pid: result.get("pid").and_then(Value::as_i64).unwrap_or(0),
            marker: self.binary.clone(),
            config: runtime.clone(),
            log: log_path.display().to_string(),
            cache_models: self.cache_models,
            health_path: String::new(),
            launch: self.cell.process.launch_spec(),
            name: self.name.clone(),
            ram_mib: 0,
        };
        self.cells.records.add(&self.id, record);
        // Caching on: the cache keeps the last models the operator set, this one among them, and deletes the older ones; what the neighbours run stays whatever its age. Caching off: files get purged on stop anyway.
        if self.cache_models {
            self.cells.keeper.commit(&self.id);
        }
    }
}
