//! Model engines on this machine that are not its cells: Ollama and LM Studio, found by their ports and process names and read through their own HTTP APIs. Looking is read only. Changing one is a separate, explicit act: the operator unloads a model, deletes one, starts or stops the engine's server, from the board. No model is loaded from here: a cell in the engine loads its model when it starts. None is downloaded either.

pub mod kind;
mod listening;
mod lms;
pub mod lmstudio;
pub mod ollama;
pub mod procs;
mod scan;
pub mod servers;
mod wire;

use crate::cells::Cells;
use crate::errors::{AppError, PyRepr};
use crate::log::Log;
use crate::machine::Machine;
use kind::EngineKind;
use listening::Listening;
use os::clock::Clock;
use rules::Coerce;
use serde_json::{Value, json};
use servers::EngineServers;
use std::collections::BTreeMap;
use std::sync::{Arc, Mutex, MutexGuard, PoisonError};
use std::time::Duration;
use wire::EnginePort;

/// (kind, port, model): what an action is about; a server's own has no model.
type ActionKey = (String, i64, String);

/// What the engines remember between scans.
#[derive(Debug, Default)]
pub(crate) struct EnginesMemory {
    pub(crate) views: Option<Vec<Value>>,
    /// An action under way.
    actions: BTreeMap<ActionKey, Value>,
    /// The last one that failed, until the next action on that model.
    failures: BTreeMap<ActionKey, Value>,
}

/// The engines on this machine that are not its cells, as the report says them, rescanned every 10 s by a thread of their own. Found where a kind listens by default, or where a process of its name listens. The ports of this scout's cells are never asked: `llama-server` answers some of the same paths, and a cell must not turn into a foreign engine. An answer proves the kind; a port that says nothing, or wants a token, is shown only when its process is the kind's own and, for silence, it is the kind's usual port. A scan never runs inside a report: a hung engine would hold `/api/state`. Before the first scan the report says `null`, "not looked yet", and after it a list, `[]` being "looked, none here".
pub struct ForeignEngines {
    pub(crate) machine: Arc<Machine>,
    pub(crate) cells: Arc<Cells>,
    pub(crate) servers: EngineServers,
    pub(crate) kinds: Vec<Arc<dyn EngineKind>>,
    clock: Arc<dyn Clock>,
    memory: Mutex<EnginesMemory>,
}

impl ForeignEngines {
    /// Seconds a started server has to answer.
    const START_WAIT: f64 = 60.0;
    /// Seconds a stopped one has to go quiet.
    const STOP_WAIT: f64 = 20.0;
    /// Seconds between scans.
    pub const PERIOD_SEC: u64 = 10;

    /// The engines of this machine.
    pub fn new(
        machine: Arc<Machine>,
        cells: Arc<Cells>,
        servers: EngineServers,
        kinds: Vec<Arc<dyn EngineKind>>,
        clock: Arc<dyn Clock>,
    ) -> Self {
        Self { machine, cells, servers, kinds, clock, memory: Mutex::new(EnginesMemory::default()) }
    }

    pub(crate) fn memory(&self) -> MutexGuard<'_, EnginesMemory> {
        self.memory.lock().unwrap_or_else(PoisonError::into_inner)
    }

    fn now(&self) -> i64 {
        self.clock.epoch() as i64
    }

    pub(crate) fn port_of(&self, port: i64, host: &'_ str) -> EnginePortOwned {
        EnginePortOwned { http: Arc::clone(&self.cells.http), port, host: host.to_string() }
    }

    /// The last scan, with what is being done to each model and what failed last: a list, or `null` before the first scan.
    pub fn views(&self) -> Value {
        let memory = self.memory();
        memory
            .views
            .as_ref()
            .map_or(Value::Null, |views| Value::Array(views.iter().map(|view| Self::with_actions(&memory, view)).collect()))
    }

    /// A copy of one engine's view, each model carrying `action` while an action on it runs and `actionError` when the last one failed; the engine itself `serverAction` and `serverError`.
    fn with_actions(memory: &EnginesMemory, view: &Value) -> Value {
        let kind = Coerce::text(view.get("kind"));
        // absent-ok: every view has its port; none is keyed by none.
        let port = view.get("port").and_then(Value::as_i64).unwrap_or(0);
        let mut out = view.clone();
        let server = (kind.clone(), port, String::new());
        let Value::Object(fields) = &mut out else {
            return out;
        };
        if let Some(action) = memory.actions.get(&server) {
            fields.insert("serverAction".to_string(), action.clone());
        }
        if let Some(failure) = memory.failures.get(&server) {
            fields.insert("serverError".to_string(), failure.clone());
        }
        if let Some(Value::Array(models)) = fields.get_mut("models") {
            for model in models {
                let key = (kind.clone(), port, Coerce::text(model.get("name")));
                if let Value::Object(row) = model {
                    if let Some(action) = memory.actions.get(&key) {
                        row.insert("action".to_string(), action.clone());
                    }
                    if let Some(failure) = memory.failures.get(&key) {
                        row.insert("actionError".to_string(), failure.clone());
                    }
                }
            }
        }
        out
    }

    fn port_number(port: Option<&Value>) -> Result<i64, AppError> {
        port.and_then(Coerce::int).ok_or_else(|| AppError::new("port must be a number"))
    }

    fn view_of(views: Option<&Vec<Value>>, kind: &str, port: i64) -> Option<Value> {
        views?
            .iter()
            .find(|view| {
                view.get("kind").and_then(Value::as_str) == Some(kind) && view.get("port").and_then(Value::as_i64) == Some(port)
            })
            .cloned()
    }

    fn offers(view: &Value, op: &str) -> bool {
        view.get("controls")
            .and_then(Value::as_array)
            .is_some_and(|controls| controls.iter().any(|control| control.as_str() == Some(op)))
    }

    /// Unloads a model the engine holds, or deletes one from its disk, on a thread of its own; answered at once, with the engines as they are now. Only an engine the last scan found, only an act it offers, only a model it listed (the scout is no proxy to an arbitrary port) and one act per model at a time.
    pub fn act(engines: &Arc<Self>, op: &str, kind_id: &str, port: Option<&Value>, model: &str) -> Result<Value, AppError> {
        if !matches!(op, "unload" | "delete") {
            return Err(AppError::new(format!("unknown engine action {}", PyRepr::of(op))));
        }
        let port = Self::port_number(port)?;
        let kind = engines.kinds.iter().find(|kind| kind.id() == kind_id).cloned();
        let key = (kind_id.to_string(), port, model.to_string());
        {
            let mut memory = engines.memory();
            Self::check_target(&memory, op, kind.is_some(), &key)?;
            memory.actions.insert(key.clone(), json!({"op": op, "since": engines.now()}));
            memory.failures.remove(&key);
        }
        let host = Listening::ask_host(engines.listener_of(port).as_ref());
        let (worker, op_word) = (Arc::clone(engines), op.to_string());
        Self::in_background(engines, &key, move |key| {
            let target = worker.port_of(port, &host);
            let reason = match kind {
                Some(kind) if op_word == "delete" => kind.delete(&target.borrowed(), &key.2),
                Some(kind) => kind.unload(&target.borrowed(), &key.2),
                None => String::new(),
            };
            worker.finished(&op_word, key, &reason);
        });
        Ok(json!({"ok": true, "engines": engines.views()}))
    }

    fn in_background(engines: &Arc<Self>, key: &ActionKey, work: impl FnOnce(&ActionKey) + Send + 'static) {
        let key = key.clone();
        let (failed_key, failed) = (key.clone(), Arc::clone(engines));
        let started = std::thread::Builder::new().name("engine-act".to_string()).spawn(move || work(&key));
        if let Err(error) = started {
            failed.finished("start", &failed_key, &error.to_string());
        }
    }

    /// The refusal that says why there is nothing to act on. Called with the lock held.
    fn check_target(memory: &EnginesMemory, op: &str, kind_known: bool, key: &ActionKey) -> Result<(), AppError> {
        let (kind_id, port, model) = key;
        let view = Self::view_of(memory.views.as_ref(), kind_id, *port).filter(|_| kind_known);
        let Some(view) = view else {
            return Err(AppError::with_status(
                format!("no {} on port {port} here", if kind_id.is_empty() { "engine" } else { kind_id }),
                404,
            ));
        };
        let label = Coerce::text(view.get("label"));
        if !Self::offers(&view, op) {
            return Err(AppError::with_status(format!("{label} on port {port} cannot {op} from here"), 409));
        }
        let row = view
            .get("models")
            .and_then(Value::as_array)
            .and_then(|models| models.iter().find(|row| row.get("name").and_then(Value::as_str) == Some(model)));
        let Some(row) = row else {
            return Err(AppError::with_status(format!("{label} lists no model {}", PyRepr::of(model)), 404));
        };
        let loaded = row.get("loaded") == Some(&Value::Bool(true));
        if op == "unload" && !loaded {
            return Err(AppError::with_status(format!("{model} is not loaded"), 409));
        }
        if op == "delete" && loaded {
            return Err(AppError::with_status(format!("{model} is loaded — unload it first"), 409));
        }
        if let Some(action) = memory.actions.get(key) {
            let doing = if action.get("op").and_then(Value::as_str) == Some("unload") { "unloaded" } else { "deleted" };
            return Err(AppError::with_status(format!("{model} is being {doing} already"), 409));
        }
        Ok(())
    }

    /// An engine that runs now starts with the machine from now on.
    pub fn keep_at_boot(&self, kind_id: &str) -> Result<Value, AppError> {
        self.servers.keep_at_boot(&self.kinds, kind_id).map_err(|words| AppError::with_status(words, 404))?;
        Ok(json!({"ok": true, "kind": kind_id}))
    }

    /// Starts an engine's server, or stops it, on a thread of its own: a start waits for the server to answer, a stop for it to go quiet. Answered at once with the engines as they are now. Only what its view offers: a stop for a server this scout's user runs, a start for a known one that is not running.
    pub fn serve(engines: &Arc<Self>, op: &str, kind_id: &str, port: Option<&Value>) -> Result<Value, AppError> {
        if !matches!(op, "start" | "stop") {
            return Err(AppError::new(format!("unknown server action {}", PyRepr::of(op))));
        }
        let port = Self::port_number(port)?;
        let kind = engines.kinds.iter().find(|kind| kind.id() == kind_id).cloned();
        let key = (kind_id.to_string(), port, String::new());
        {
            let mut memory = engines.memory();
            let view = Self::view_of(memory.views.as_ref(), kind_id, port).filter(|_| kind.is_some());
            let Some(view) = view else {
                return Err(AppError::with_status(
                    format!("no {} on port {port} here", if kind_id.is_empty() { "engine" } else { kind_id }),
                    404,
                ));
            };
            let label = Coerce::text(view.get("label"));
            if !Self::offers(&view, op) {
                return Err(AppError::with_status(format!("{label} on port {port} cannot {op} from here"), 409));
            }
            if let Some(action) = memory.actions.get(&key) {
                let doing = if action.get("op").and_then(Value::as_str) == Some("start") { "started" } else { "stopped" };
                return Err(AppError::with_status(format!("{label} is being {doing} already"), 409));
            }
            memory.actions.insert(key.clone(), json!({"op": op, "since": engines.now()}));
            memory.failures.remove(&key);
        }
        let listener = engines.listener_of(port);
        let pid = listener.as_ref().and_then(|row| row.get("pid")).and_then(Value::as_i64).filter(|pid| *pid != 0);
        let host = Listening::ask_host(listener.as_ref());
        let (worker, op_word) = (Arc::clone(engines), op.to_string());
        Self::in_background(engines, &key, move |key| {
            let Some(kind) = kind else {
                return;
            };
            let mut reason = if op_word == "start" {
                worker.servers.start(kind.as_ref(), port)
            } else {
                worker.servers.stop(kind.as_ref(), pid)
            };
            if reason.is_empty() {
                reason = worker.wait_for(kind.as_ref(), port, &host, op_word == "start");
            }
            worker.finished(&op_word, key, &reason);
        });
        Ok(json!({"ok": true, "engines": engines.views()}))
    }

    fn finished(&self, op: &str, key: &ActionKey, reason: &str) {
        let at = self.now();
        {
            let mut memory = self.memory();
            memory.actions.remove(key);
            if !reason.is_empty() {
                memory.failures.insert(key.clone(), json!({"op": op, "error": reason, "at": at}));
            }
        }
        let (kind, port, model) = key;
        let what = if model.is_empty() { format!("{op} {kind}:{port}") } else { format!("{op} {model} on {kind}:{port}") };
        Log::line(&format!("[engines] {what}: {}", if reason.is_empty() { "done" } else { reason }));
        // The loaded state now, not in ten seconds.
        self.refresh();
    }

    /// Waits until the engine answers on its port (a start) or stops answering (a stop): "" when it did, else what did not happen.
    fn wait_for(&self, kind: &dyn EngineKind, port: i64, host: &str, answering: bool) -> String {
        let wait = if answering { Self::START_WAIT } else { Self::STOP_WAIT };
        let deadline = self.clock.monotonic() + wait;
        let target = self.port_of(port, host);
        loop {
            let seen = kind.read(&|path| target.borrowed().ask(path));
            let up = seen.as_ref().is_some_and(|seen| matches!(seen.get("state").and_then(Value::as_str), Some("ok" | "auth")));
            if up == answering {
                return String::new();
            }
            if self.clock.monotonic() >= deadline {
                return if answering {
                    format!("it did not answer on port {port} in {wait} s")
                } else {
                    format!("it still answers on port {port} after {wait} s")
                };
            }
            std::thread::sleep(Duration::from_secs(1));
        }
    }

    /// The servers started from here and not stopped since, started when the machine has booted. The kinds asked to start.
    pub fn start_at_boot(engines: &Arc<Self>) -> Vec<String> {
        let mut started = Vec::new();
        for kind_id in engines.servers.due_at_boot(&engines.machine.boot_id()) {
            let views = engines.views();
            let view = views
                .as_array()
                .and_then(|views| views.iter().find(|view| view.get("kind").and_then(Value::as_str) == Some(kind_id.as_str())))
                .filter(|view| Self::offers(view, "start"));
            let Some(view) = view else {
                Log::line(&format!("[engines] {kind_id} is running already or cannot start here — not started at boot"));
                continue;
            };
            match Self::serve(engines, "start", &kind_id, view.get("port")) {
                Ok(_) => started.push(kind_id),
                Err(error) => Log::line(&format!("[engines] {kind_id} did not start at boot: {error}")),
            }
        }
        started
    }
}

/// An engine's port, for a thread that outlives its asker.
pub(crate) struct EnginePortOwned {
    http: Arc<crate::http_client::HttpClient>,
    port: i64,
    host: String,
}

impl EnginePortOwned {
    pub(crate) fn borrowed(&self) -> EnginePort<'_> {
        EnginePort { http: &self.http, port: self.port, host: &self.host }
    }
}
