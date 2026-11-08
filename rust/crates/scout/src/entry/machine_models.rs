//! The models of this machine, as `GET /v1/models` lists them: each cell the scout runs, starts or keeps a start request for, and each one the controller keeps for the machine, grouped by its model's name and its runner: two cells of one model on one
//! runner are its copies.
//!
//! A cell the table holds with nothing behind it, no process, no start, no record, no kept request, not one the controller keeps: a name only asked about, is no model, and is left out. A running copy also says its places: how many requests its server
//! takes at once and how many it works on now. A copy whose server does not say has `null`: a model's sum is known only when every running copy says its part.

use crate::cells::Cells;
use crate::cells::autostart::Autostart;
use crate::cells::table::Cell;
use crate::config::ScoutConfig;
use crate::entry::known::KnownCells;
use crate::entry::names::ModelName;
use rules::Coerce;
use serde_json::{Value, json};
use std::collections::BTreeMap;
use std::sync::Arc;

/// One copy of a model: one cell.
#[derive(Debug, Clone, PartialEq)]
pub struct Copy {
    /// Its cell's own name.
    pub id: String,
    /// The port its run holds; `None` while it holds none (Papyrus `caravan-scout-port-lease`): a stopped copy is still a copy.
    pub port: Option<i64>,
    /// Its model's name.
    pub name: String,
    /// Its runner.
    pub runner: String,
    /// `running`, `starting`, `failed` or `stopped`.
    pub state: &'static str,
    /// When its record says it started.
    pub since: Option<Value>,
    /// How many requests it takes at once, when it says.
    pub slots: Option<i64>,
    /// How many it works on now, when it says.
    pub busy: Option<i64>,
}

/// The copies of one name, by their runners.
type ByRunner = Vec<(String, Vec<Copy>)>;

/// A model's state, the best first.
const STATES: [&str; 4] = ["running", "starting", "failed", "stopped"];

/// The models.
pub struct MachineModels {
    cells: Arc<Cells>,
    autostart: Arc<Autostart>,
    config: Arc<ScoutConfig>,
    known: Arc<KnownCells>,
}

impl MachineModels {
    /// The runner of a cell whose settings name none: the controller's default too.
    const DEFAULT_RUNNER: &'static str = "llama-server";

    /// The models of these cells.
    pub fn new(cells: Arc<Cells>, autostart: Arc<Autostart>, config: Arc<ScoutConfig>, known: Arc<KnownCells>) -> Self {
        Self { cells, autostart, config, known }
    }

    fn runner(config: Option<&Value>) -> String {
        let said = config.and_then(|config| config.get("RUNNER")).filter(|said| Coerce::truthy(Some(*said)));
        let word = said.map_or_else(String::new, |said| Coerce::stripped(Some(said)).to_lowercase());
        if word.is_empty() { Self::DEFAULT_RUNNER.to_string() } else { word }
    }

    fn state(cell: &Cell) -> &'static str {
        let status = cell.process.status();
        let phase = {
            let facts = cell.facts();
            if Coerce::truthy(facts.startup.get("phase")) { Coerce::text(facts.startup.get("phase")) } else { String::new() }
        };
        if status.get("running") == Some(&Value::Bool(true)) {
            return "running";
        }
        match phase.as_str() {
            "resolving" | "downloading" | "loading" => "starting",
            "error" => "failed",
            _ if Coerce::truthy(status.get("crashed")) => "failed",
            _ => "stopped",
        }
    }

    /// Each cell, sorted by its name. The name from the freshest word first: the start under way or last made here, the record of a cell running since before this scout started, the kept start request, and, for a cell started before names were kept, its model's
    /// path in the record. A stopped cell the controller keeps is called what its settings call it now: they are what its next start runs. The runner: what the freshest settings say: the controller's, else the kept start request's, else the record's.
    pub fn cells_now(&self) -> Vec<Copy> {
        let kept = self.autostart.requests();
        // absent-ok: not knowing the cells lists what this scout knows, as before there was a list.
        let known = self.known.cells().unwrap_or_default();
        let mut found: BTreeMap<String, Copy> = BTreeMap::new();
        for (id, cell) in self.cells.table.all() {
            let record = self.cells.records.get(&id);
            let request = kept.get(&id).filter(|request| Coerce::truthy(Some(*request)));
            let state = Self::state(&cell);
            let told = known.get(&id);
            if state == "stopped" && record.is_empty() && request.is_none() && told.is_none() {
                continue;
            }
            let recorded_path =
                record.get("cfg").and_then(|config| config.get("modelPath")).filter(|path| Coerce::truthy(Some(*path)));
            let name = match told.filter(|_| state == "stopped") {
                Some(told) => told.name(&id),
                None => {
                    let own = cell.facts().name.clone();
                    if !own.is_empty() {
                        own
                    } else if Coerce::truthy(record.get("name")) {
                        Coerce::text(record.get("name"))
                    } else {
                        let requested =
                            request.and_then(|request| request.get("modelPath")).filter(|path| Coerce::truthy(Some(*path)));
                        let path = requested.or(recorded_path).map_or_else(String::new, |path| Coerce::text(Some(path)));
                        ModelName::of(request.and_then(|request| request.get("config")), &path, &id)
                    }
                }
            };
            let runner = match (told, request) {
                (Some(told), _) => Self::runner(Some(&told.config)),
                (None, Some(request)) => Self::runner(request.get("config")),
                (None, None) => Self::runner(Some(&json!({"RUNNER": record.get("cfg").and_then(|config| config.get("runner"))}))),
            };
            let port = cell.port();
            let (slots, busy) = self.places(port, state);
            found
                .insert(id.clone(), Copy { id, port, name, runner, state, since: record.get("startedAt").cloned(), slots, busy });
        }
        self.add_stopped(&mut found, &kept, &known);
        found.into_values().collect()
    }

    fn add_stopped(
        &self,
        found: &mut BTreeMap<String, Copy>,
        kept: &Value,
        known: &BTreeMap<String, crate::entry::known::KnownCell>,
    ) {
        let stopped = |id: &str, name: String, runner: String| Copy {
            id: id.to_string(),
            port: None,
            name,
            runner,
            state: "stopped",
            since: None,
            slots: None,
            busy: None,
        };
        for (id, request) in kept.as_object().into_iter().flatten() {
            if found.contains_key(id) {
                continue;
            }
            let told = known.get(id);
            let name = told.map_or_else(
                || ModelName::of(request.get("config"), &Coerce::text(request.get("modelPath")), id),
                |told| told.name(id),
            );
            let runner = told.map_or_else(|| Self::runner(request.get("config")), |told| Self::runner(Some(&told.config)));
            found.insert(id.clone(), stopped(id, name, runner));
        }
        for (id, told) in known {
            found.entry(id.clone()).or_insert_with(|| stopped(id, told.name(id), Self::runner(Some(&told.config))));
        }
    }

    /// A running copy's places; none asked of a copy that does not run.
    fn places(&self, port: Option<i64>, state: &str) -> (Option<i64>, Option<i64>) {
        let Some(port) = port.filter(|_| state == "running") else {
            return (None, None);
        };
        let busy = self.cells.probe.metrics(port).get("requestsProcessing").and_then(Value::as_i64).filter(|busy| *busy >= 0);
        (self.cells.probe.slots_total(port), busy)
    }

    /// The running copies' sum: 0 when none runs, `null` when one of them does not say.
    fn summed(copies: &[Copy], part: impl Fn(&Copy) -> Option<i64>) -> Option<i64> {
        copies.iter().filter(|copy| copy.state == "running").map(part).sum()
    }

    /// The models by the id the entry lists them under, each with its copies, in the order of their first cells. Cells of one name on two runners are two models, each called by the name and its runner (`name@runner`), as LM Studio tells a model's variants: a
    /// request for one of them must not land on a server of another kind, and which of the two the bare name meant nobody said.
    pub fn groups(&self) -> Vec<(String, Vec<Copy>)> {
        let mut by_name: Vec<(String, ByRunner)> = Vec::new();
        for copy in self.cells_now() {
            let at = by_name.iter().position(|(name, _)| *name == copy.name).unwrap_or_else(|| {
                by_name.push((copy.name.clone(), Vec::new()));
                by_name.len() - 1
            });
            let Some((_, runners)) = by_name.get_mut(at) else {
                continue;
            };
            match runners.iter_mut().find(|(runner, _)| *runner == copy.runner) {
                Some((_, copies)) => copies.push(copy),
                None => runners.push((copy.runner.clone(), vec![copy])),
            }
        }
        let mut out = Vec::new();
        for (name, runners) in by_name {
            let alone = runners.len() == 1;
            for (runner, copies) in runners {
                out.push((if alone { name.clone() } else { format!("{name}@{runner}") }, copies));
            }
        }
        out
    }

    /// The models in OpenAI's shape, each with `caravan`: its state, the best of its copies', its places, and each copy's cell, port (none while it holds none), state and places. `created` is when its first copy started; 0 for one never started.
    pub fn listing(&self) -> Vec<Value> {
        let owner = self.config.text("hostId");
        self.groups()
            .into_iter()
            .map(|(name, copies)| {
                // absent-ok: a group has a copy; a state outside the list is the last of it.
                let best = STATES.iter().find(|state| copies.iter().any(|copy| copy.state == **state)).copied().unwrap_or("stopped");
                let started = copies.iter().filter_map(|copy| copy.since.as_ref().and_then(Value::as_f64)).filter(|since| *since > 0.0).map(|since| since.trunc() as i64).min();
                let rows: Vec<Value> = copies.iter().map(|copy| json!({"id": copy.id, "port": copy.port, "state": copy.state, "slots": copy.slots, "busy": copy.busy})).collect();
                json!({
                    "id": name,
                    "object": "model",
                    // absent-ok: 0 is what OpenAI's shape says of a model never started.
                    "created": started.unwrap_or(0),
                    "owned_by": owner,
                    "caravan": {"state": best, "slots": Self::summed(&copies, |copy| copy.slots), "busy": Self::summed(&copies, |copy| copy.busy), "copies": rows},
                })
            })
            .collect()
    }

    /// The copies of the model the entry lists as `name`; none for a name it does not list.
    pub fn copies(&self, name: &str) -> Vec<Copy> {
        self.groups().into_iter().find(|(id, _)| id == name).map_or_else(Vec::new, |(_, copies)| copies)
    }
}
