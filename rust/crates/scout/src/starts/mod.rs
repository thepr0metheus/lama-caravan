//! Starting a cell: the controller's request, accepted or refused, and the launch that follows it: a `llama-server` or whatever a command cell runs.
//!
//! The firewall is not opened here since 2.40: the owner decided on 2026-10-26 that the cells' ports answer the controller alone, by his own rule for their whole range.
//!
//! The request names the cell (`cellId`) and the range its port may be leased from (`ports`), never a port (Papyrus `caravan-scout-port-lease`, step 2): the
//! start leases the lowest free one, fills every place the controller left for it (`{{PORT}}`), and the cell holds it until it stops.

pub mod artifacts;
pub mod assets;
mod command;
mod llama;
mod room;

use crate::cells::Cells;
use crate::cells::lease::PortLease;
use crate::cells::table::{Cell, CellTable};
use crate::errors::AppError;
use crate::models::{CacheKeeper, ModelFetcher};
use crate::process::HostProcesses;
use rules::Coerce;
use serde_json::{Map, Value, json};
use std::path::Path;
use std::sync::Arc;

/// How a kind of cell takes its request.
type StartOfKind = fn(StartRequest) -> Result<Value, AppError>;

/// One start request, from the controller's payload to an answer: a cell on its way up, or a refusal that says why. Which kind it is, the payload says: `cellKind`, or `CELL_KIND` in its config.
pub struct StartRequest {
    pub(crate) cells: Arc<Cells>,
    pub(crate) payload: Map<String, Value>,
    pub(crate) config: Map<String, Value>,
}

impl StartRequest {
    /// The folder a command cell may fill with what it makes from its model: kept with the cell's models, emptied at its start and removed at its stop when they are not kept.
    pub(crate) const SCRATCH_ENV: &'static str = "CARAVAN_CELL_SCRATCH";
    /// The kinds that are not a llama cell.
    const KINDS: [(&'static str, StartOfKind); 1] = [("command", command::CommandStart::run)];
    /// What the controller writes where the port goes, in a llama cell's arguments and a command cell's line (the controller's
    /// `LlamaArgs::LEASED_PORT`): the start fills it with the port it leased.
    const PORT_MARK: &'static str = "{{PORT}}";

    /// The request of this payload.
    pub fn of(cells: Arc<Cells>, payload: Map<String, Value>) -> Self {
        // absent-ok: a payload of no settings has the legacy fields of a llama cell, or is refused for what it lacks.
        let config = payload.get("config").and_then(Value::as_object).cloned().unwrap_or_default();
        Self { cells, payload, config }
    }

    pub(crate) fn word_of(fields: &Map<String, Value>, key: &str) -> String {
        if Coerce::truthy(fields.get(key)) { Coerce::stripped(fields.get(key)) } else { String::new() }
    }

    /// Answers it.
    pub fn run(self) -> Result<Value, AppError> {
        let said = Self::word_of(&self.payload, "cellKind");
        let kind = if said.is_empty() { Self::word_of(&self.config, "CELL_KIND") } else { said }.to_lowercase();
        match Self::KINDS.iter().find(|(name, _)| *name == kind) {
            Some((_, run)) => run(self),
            None => llama::LlamaStart::run(self),
        }
    }

    /// Whether its files stay when it stops: as the controller asks, else as this machine's settings say. A start that keeps them in the folder for Strata's files always keeps them: that folder
    /// keeps copies by its own size (shelf.rs), so that a start does not write the model again.
    pub(crate) fn cache_models(&self) -> bool {
        if self.work_folder() {
            return true;
        }
        match self.payload.get("cacheModels") {
            Some(said) => Coerce::truthy(Some(said)),
            None => Coerce::truthy(self.cells.config.get("cacheModels").as_ref()),
        }
    }

    /// Whether the controller asks for this start's models in the folder for Strata's files: its runner needs a fast disk of the operator's choosing (`workFolder`).
    pub(crate) fn work_folder(&self) -> bool {
        Coerce::truthy(self.payload.get("workFolder"))
    }

    /// The shelf this start keeps its models on, or the refusal of a start that needs the folder for Strata's files where none is chosen: the controller says so before it asks, and an older one
    /// that does not is answered the same here.
    pub(crate) fn shelf(&self) -> Result<(&Arc<ModelFetcher>, &Arc<CacheKeeper>), AppError> {
        let work = self.work_folder();
        if work && !self.cells.work_models.folder_chosen() {
            return Err(AppError::with_status(
                "this cell keeps its models in the folder for Strata's files, and none is chosen on this machine: open the machine's page, Model disk → Strata files → Choose…",
                409,
            ));
        }
        Ok(self.cells.shelf(work))
    }

    /// The environment the cell starts with over this scout's own: the one the controller's `start.sh` exports. Refused when malformed: a cell started with a guess at its environment is the wrong cell. The marker this scout
    /// finds its cells by is its own to set, not the controller's.
    pub(crate) fn process_env(&self) -> Result<Map<String, Value>, AppError> {
        let Some(said) = self.payload.get("env").filter(|env| !env.is_null()) else {
            return Ok(Map::new());
        };
        let is_name = |name: &str| {
            name.chars().next().is_some_and(|first| first.is_ascii_alphabetic() || first == '_')
                && name.chars().all(|letter| letter.is_ascii_alphanumeric() || letter == '_')
        };
        let sound = said.as_object().filter(|env| env.iter().all(|(name, value)| is_name(name) && value.is_string()));
        let env = sound.ok_or_else(|| AppError::new("env must map variable names to strings"))?;
        for mark in [HostProcesses::CELL_ENV, HostProcesses::HOME_ENV] {
            if env.contains_key(mark) {
                return Err(AppError::new(format!("env may not set {mark} — the scout sets it")));
            }
        }
        Ok(env.clone())
    }

    /// Where the controller reads each model file, keyed by the path this scout is sent.
    pub(crate) fn hints(&self) -> Option<Value> {
        self.payload.get("inPlace").filter(|hints| hints.is_object()).cloned()
    }

    /// `LLAMA_MODELS_DIR` for a command that names its model as `${LLAMA_MODELS_DIR:-…}/<path>`: the folder the model really sits under here. The command used to fall back to `~/llama.cpp/models` while the download went to the
    /// cache, and the two never met. A value the operator set is exported by the start line itself and wins.
    pub(crate) fn models_root(model_raw: &str, model_abs: &str) -> Option<String> {
        let raw = Coerce::strip(model_raw).trim_matches('/');
        if raw.is_empty() || model_abs.is_empty() || Path::new(model_raw).is_absolute() {
            return None;
        }
        let path = model_abs.trim_end_matches('/');
        let root = path.strip_suffix(raw)?.strip_suffix('/')?;
        Some(if root.is_empty() { "/".to_string() } else { root.to_string() })
    }

    /// The cell it starts: the name the controller gives it (`cellId`). A request that names none is refused: a cell is not its port any more.
    pub fn cell_id(&self) -> Result<String, AppError> {
        CellTable::named(self.payload.get("cellId"))
    }

    /// The port `cell`'s run is leased, from the range the request names (`ports`, the cells' own when it names none), and every place the
    /// request leaves for it filled with it: the config's `PORT`, a llama cell's arguments, a command cell's line, command and environment. The
    /// refusal of a range with no free port, in words.
    pub(crate) fn lease_port(&mut self, cell: &Arc<Cell>) -> Result<i64, AppError> {
        let range = PortLease::of(self.payload.get("ports"))?;
        let recorded = self.cells.records.ports_besides(&cell.id);
        let listening = self.cells.machine.listening_ports_now();
        let port = match self.cells.table.lease(cell, &range, &recorded, listening.as_ref()) {
            Ok(port) => port,
            Err(words) => {
                // The cell says why it did not start, as a start that failed on its way does: a refusal that left it with nothing to say
                // stood on the board as a cell of no phase.
                self.cells.table.say(&cell.id, &json!({"phase": "error", "error": words}));
                return Err(AppError::with_status(words, 409));
            }
        };
        self.fill_port(port);
        Ok(port)
    }

    /// `port` written where the request left its place.
    fn fill_port(&mut self, port: i64) {
        let word = port.to_string();
        let filled = |text: &str| text.replace(Self::PORT_MARK, &word);
        self.config.insert("PORT".to_string(), json!(word));
        if let Some(Value::Object(config)) = self.payload.get_mut("config") {
            config.insert("PORT".to_string(), json!(word));
        }
        for key in ["shellLine", "command"] {
            if let Some(Value::String(text)) = self.payload.get_mut(key) {
                *text = filled(text);
            }
        }
        for list in ["args"] {
            for item in self.payload.get_mut(list).and_then(Value::as_array_mut).into_iter().flatten() {
                if let Value::String(text) = item {
                    *text = filled(text);
                }
            }
        }
        for value in self.payload.get_mut("env").and_then(Value::as_object_mut).into_iter().flat_map(|env| env.values_mut()) {
            if let Value::String(text) = value {
                *text = filled(text);
            }
        }
    }

    /// The refusal when `cell` already runs or its start is under way; `None` when it may start.
    pub(crate) fn busy(&self, cell: &Arc<Cell>) -> Option<Value> {
        let id = &cell.id;
        if cell.process.status().get("running") == Some(&Value::Bool(true)) {
            return Some(json!({"ok": false, "error": format!("the cell {id} is already running")}));
        }
        let startup = cell.facts().startup.clone();
        let phase = startup.get("phase").and_then(Value::as_str);
        if let Some(phase) = phase.filter(|phase| matches!(*phase, "resolving" | "downloading" | "loading")) {
            return Some(
                json!({"ok": false, "error": format!("startup already in progress for the cell {id} ({phase})"), "phase": phase}),
            );
        }
        // A process of this cell that this scout started and lost track of still runs, a start that was loading when the scout was killed (2026-10-14). A second copy beside it loads its
        // model again and fights it for the card: it is held again instead, and the board shows it.
        let lost = self.cells.survivor(id);
        if lost != 0 {
            self.cells.adopt_found(id, lost);
            let error = format!(
                "the cell {id} is already running (pid {lost}, started by this scout and lost track of) — it is held again; stop it from the board to start it anew"
            );
            return Some(json!({"ok": false, "adopted": true, "pid": lost, "error": error}));
        }
        None
    }

    /// A launch thread. A system that gives no thread says it on the cell's card.
    pub(crate) fn in_background(&self, id: &str, launch: impl FnOnce() + Send + 'static) {
        let started = std::thread::Builder::new().name(format!("start-{id}")).spawn(launch);
        if let Err(error) = started {
            self.cells.table.say(id, &json!({"phase": "error", "error": error.to_string()}));
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_models_root_is_the_folder_the_model_sits_under() {
        assert_eq!(StartRequest::models_root("a/b.gguf", "/cache/a/b.gguf").as_deref(), Some("/cache"));
        assert_eq!(StartRequest::models_root("a/b.gguf", "/a/b.gguf").as_deref(), Some("/"));
        assert_eq!(StartRequest::models_root("/abs/b.gguf", "/abs/b.gguf"), None);
        assert_eq!(StartRequest::models_root("a/b.gguf", "/elsewhere/c.gguf"), None);
        assert_eq!(StartRequest::models_root("", "/x"), None);
    }
}
