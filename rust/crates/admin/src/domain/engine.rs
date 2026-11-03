//! Model engines on a machine that are not its cells, as the controller keeps and reads them. The scout decides what an engine is and which processes are its own; here the report is only kept honestly and joined with the cards' memory.

use rules::Coerce;
use serde_json::{Map, Value, json};
use std::collections::{BTreeMap, BTreeSet};

/// The `engines` of a scout's report as the host record keeps them: each field typed and bounded, anything the scout did not say kept as `null`. `null` for the whole list is an older scout; `[]` is a scout that looked and found none. A model's memory, window or loaded state the engine did not say stays `null`, never a zero.
pub struct EngineReport;

impl EngineReport {
    const MAX_ENGINES: usize = 8;
    const MAX_MODELS: usize = 200;
    const MAX_PIDS: usize = 256;
    const STATES: [&'static str; 4] = ["ok", "auth", "unreachable", "stopped"];
    const LISTEN: [&'static str; 2] = ["loopback", "network"];
    const FIREWALL: [&'static str; 5] = ["open", "all", "restricted", "blocked", "unknown"];
    /// What may be done to an engine's model.
    pub const ACTIONS: [&'static str; 2] = ["unload", "delete"];
    /// What may be done to an engine's server.
    pub const SERVER_ACTIONS: [&'static str; 2] = ["start", "stop"];
    const CONTROLS: [&'static str; 5] = ["unload", "delete", "pull", "start", "stop"];
    const RUN_BY: [&'static str; 2] = ["user", "other"];

    fn text(value: Option<&Value>, limit: usize) -> String {
        if !Coerce::truthy(value) {
            return String::new();
        }
        Coerce::first_letters(&Coerce::stripped(value), limit).to_string()
    }

    /// A size in bytes as the scout said it; null when it did not, or said none that can be.
    pub fn size(value: Option<&Value>) -> Value {
        let number = Self::number(value);
        if number.as_i64().is_some_and(|number| number >= 0) { number } else { Value::Null }
    }

    fn number(value: Option<&Value>) -> Value {
        value.filter(|value| !value.is_boolean()).and_then(Coerce::int).map_or(Value::Null, |number| json!(number))
    }

    fn flag(value: Option<&Value>) -> Value {
        value.filter(|value| value.is_boolean()).cloned().unwrap_or(Value::Null)
    }

    /// The list a report says.
    pub fn engines(raw: Option<&Value>) -> Value {
        let Some(list) = raw.and_then(Value::as_array) else {
            return Value::Null;
        };
        Value::Array(list.iter().take(Self::MAX_ENGINES).filter_map(Self::engine).collect())
    }

    fn engine(raw: &Value) -> Option<Value> {
        raw.as_object()?;
        let kind = Self::text(raw.get("kind"), 40);
        let state = Self::text(raw.get("state"), 20);
        let port =
            raw.get("port").filter(|value| !value.is_boolean()).and_then(Coerce::int).filter(|port| (1..65536).contains(port))?;
        if kind.is_empty() || !Self::STATES.contains(&state.as_str()) {
            return None;
        }
        let label = Self::text(raw.get("label"), 60);
        let listen = Self::text(raw.get("listen"), 20);
        let models = raw
            .get("models")
            .and_then(Value::as_array)
            .map(|models| models.iter().take(Self::MAX_MODELS).filter_map(Self::model).collect::<Vec<_>>());
        let pids: BTreeSet<i64> = raw
            .get("pids")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            .take(Self::MAX_PIDS)
            .filter(|pid| !pid.is_boolean())
            .filter_map(Coerce::int)
            .filter(|pid| *pid > 0)
            .collect();
        let controls: Vec<&str> = raw.get("controls").and_then(Value::as_array).map_or_else(Vec::new, |said| {
            Self::CONTROLS.iter().copied().filter(|control| said.iter().any(|word| word.as_str() == Some(control))).collect()
        });
        let run_by = raw.get("runBy").and_then(Value::as_str).filter(|word| Self::RUN_BY.contains(word));
        let mut row = json!({
            "kind": kind,
            "label": if label.is_empty() { kind.clone() } else { label },
            "port": port,
            "listen": if Self::LISTEN.contains(&listen.as_str()) { listen } else { String::new() },
            "state": state,
            "version": Self::text(raw.get("version"), 40),
            "api": Self::text(raw.get("api"), 10),
            "models": models,
            "pids": pids,
            "ramBytes": Self::number(raw.get("ramBytes")),
            "firewall": Self::firewall(raw.get("firewall")),
            "controls": controls,
            "runBy": run_by.map_or_else(String::new, |word| Coerce::first_letters(word, 10).to_string()),
            "autostart": raw.get("autostart") == Some(&Value::Bool(true)),
            "serverAction": Self::act_mark(raw.get("serverAction"), "since", false, &Self::SERVER_ACTIONS),
            "serverError": Self::act_mark(raw.get("serverError"), "at", true, &Self::SERVER_ACTIONS),
            "downloading": Self::download(raw.get("downloading"), false),
            "downloadError": Self::download(raw.get("downloadError"), true),
        });
        // Only when the list of installed models did not answer: the models shown are the loaded ones, and "that is all it has" would be a guess.
        if let (true, Value::Object(fields)) = (raw.get("installedKnown") == Some(&Value::Bool(false)), &mut row) {
            fields.insert("installedKnown".to_string(), json!(false));
        }
        Some(row)
    }

    /// `{state, allowedFrom}` as the scout's ufw reading says it, or `null`.
    fn firewall(raw: Option<&Value>) -> Value {
        let Some(raw) = raw.filter(|raw| raw.is_object()) else {
            return Value::Null;
        };
        let Some(state) = raw.get("state").and_then(Value::as_str).filter(|state| Self::FIREWALL.contains(state)) else {
            return Value::Null;
        };
        let allowed: Vec<String> = raw
            .get("allowedFrom")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            .take(8)
            .map(|address| Self::text(Some(address), 60))
            .filter(|address| !address.is_empty())
            .collect();
        json!({"state": state, "allowedFrom": allowed})
    }

    fn model(raw: &Value) -> Option<Value> {
        raw.as_object()?;
        let name = Self::text(raw.get("name"), 200);
        if name.is_empty() {
            return None;
        }
        Some(json!({
            "name": name,
            "type": Self::text(raw.get("type"), 20),
            "format": Self::text(raw.get("format"), 20),
            "family": Self::text(raw.get("family"), 40),
            "params": Self::text(raw.get("params"), 20),
            "quant": Self::text(raw.get("quant"), 20),
            "fileBytes": Self::number(raw.get("fileBytes")),
            "remote": raw.get("remote") == Some(&Value::Bool(true)),
            "loaded": Self::flag(raw.get("loaded")),
            "memBytes": Self::number(raw.get("memBytes")),
            "vramBytes": Self::number(raw.get("vramBytes")),
            "contextLength": Self::number(raw.get("contextLength")),
            "maxContextLength": Self::number(raw.get("maxContextLength")),
            "expiresAt": Self::text(raw.get("expiresAt"), 40),
            "staysLoaded": Self::flag(raw.get("staysLoaded")),
            "instances": Self::number(raw.get("instances")),
            "action": Self::act_mark(raw.get("action"), "since", false, &Self::ACTIONS),
            "actionError": Self::act_mark(raw.get("actionError"), "at", true, &Self::ACTIONS),
        }))
    }

    fn download(raw: Option<&Value>, failed: bool) -> Value {
        let Some(raw) = raw.filter(|raw| raw.is_object()) else {
            return Value::Null;
        };
        let model = Self::text(raw.get("model"), 300);
        if model.is_empty() {
            return Value::Null;
        }
        if failed {
            return json!({"model": model, "error": Self::text(raw.get("error"), 300), "at": Self::number(raw.get("at"))});
        }
        json!({"model": model, "since": Self::number(raw.get("since")), "doneBytes": Self::number(raw.get("doneBytes")), "totalBytes": Self::number(raw.get("totalBytes"))})
    }

    fn act_mark(raw: Option<&Value>, when: &str, with_error: bool, ops: &[&str]) -> Value {
        let Some(raw) = raw.filter(|raw| raw.is_object()) else {
            return Value::Null;
        };
        let Some(op) = raw.get("op").and_then(Value::as_str).filter(|op| ops.contains(op)) else {
            return Value::Null;
        };
        let mut mark = Map::new();
        mark.insert("op".to_string(), json!(op));
        mark.insert(when.to_string(), Self::number(raw.get(when)));
        if with_error {
            mark.insert("error".to_string(), json!(Self::text(raw.get("error"), 300)));
        }
        Value::Object(mark)
    }
}

/// Who holds the part of a card's memory that is not the fleet's. An engine the scout found owns its processes; any other process is named by its executable, as `nvidia-smi` says it. The board shows "Ollama 6.1 GB" where it showed "outside 6.1 GB".
pub struct GpuOwners<'a> {
    by_pid: BTreeMap<i64, &'a Value>,
}

impl<'a> GpuOwners<'a> {
    /// The owners among these engines.
    pub fn new(engines: &'a [Value]) -> Self {
        let mut by_pid = BTreeMap::new();
        for engine in engines {
            for pid in engine.get("pids").and_then(Value::as_array).into_iter().flatten().filter_map(Value::as_i64) {
                by_pid.entry(pid).or_insert(engine);
            }
        }
        Self { by_pid }
    }

    fn owner(&self, pid: i64, name: &str) -> (String, String) {
        let Some(engine) = self.by_pid.get(&pid) else {
            return (name.to_string(), String::new());
        };
        let said = if Coerce::truthy(engine.get("label")) { engine.get("label") } else { engine.get("kind") };
        (Coerce::text(said), Coerce::text(engine.get("kind")))
    }

    /// `[(pid, MiB, process name)]` on one card, none of them the fleet's: `[{name, engine, mib}]` by owner, largest first; names break ties.
    pub fn split(&self, apps: &[(i64, f64, String)]) -> Vec<Value> {
        let mut held: BTreeMap<(String, String), f64> = BTreeMap::new();
        for (pid, mib, name) in apps {
            *held.entry(self.owner(*pid, name)).or_default() += mib;
        }
        let mut rows: Vec<(String, String, i64)> =
            held.into_iter().map(|((name, engine), mib)| (name, engine, mib.round_ties_even() as i64)).collect();
        rows.sort_by(|left, right| right.2.cmp(&left.2).then_with(|| left.0.cmp(&right.0)).then_with(|| left.1.cmp(&right.1)));
        rows.into_iter().map(|(name, engine, mib)| json!({"name": name, "engine": engine, "mib": mib})).collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn what_a_scout_did_not_say_stays_none() {
        assert_eq!(EngineReport::engines(None), Value::Null);
        assert_eq!(EngineReport::engines(Some(&json!([]))), json!([]));
        let kept = EngineReport::engines(Some(
            &json!([{"kind": "ollama", "state": "ok", "port": 11434, "models": [{"name": "m", "loaded": "yes", "memBytes": true}], "pids": [5, 3, 3, -1, true], "controls": ["unload", "load"], "serverAction": {"op": "start", "since": 5}, "installedKnown": false}, {"kind": "x", "state": "nonsense", "port": 1}, {"state": "ok", "port": 1}, {"kind": "y", "state": "ok", "port": 70000}]),
        ));
        let list = kept.as_array().unwrap();
        assert_eq!(list.len(), 1);
        let engine = list.first().unwrap();
        assert_eq!(engine.get("pids"), Some(&json!([3, 5])));
        assert_eq!(engine.get("controls"), Some(&json!(["unload"])));
        assert_eq!(engine.get("serverAction"), Some(&json!({"op": "start", "since": 5})));
        assert_eq!(engine.get("installedKnown"), Some(&json!(false)));
        let model = engine.get("models").and_then(|models| models.get(0)).unwrap();
        assert_eq!(model.get("loaded"), Some(&Value::Null));
        assert_eq!(model.get("memBytes"), Some(&Value::Null));
    }

    #[test]
    fn an_engine_owns_its_processes_and_the_rest_go_by_name() {
        let engines = [json!({"kind": "ollama", "label": "Ollama", "pids": [7]})];
        let owners = GpuOwners::new(&engines);
        let rows =
            owners.split(&[(7, 100.0, "runner".to_string()), (9, 300.0, "python3".to_string()), (11, 100.0, String::new())]);
        assert_eq!(
            rows,
            [
                json!({"name": "python3", "engine": "", "mib": 300}),
                json!({"name": "", "engine": "", "mib": 100}),
                json!({"name": "Ollama", "engine": "ollama", "mib": 100})
            ]
        );
    }
}
