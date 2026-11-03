//! One kind of engine: the port it takes when nobody changes it, what its processes are called, and how its API is read. The kinds are a table; a new engine is a new kind, and nothing outside a kind asks which one it is.

use crate::engines::procs::EngineProcs;
use crate::engines::wire::{EnginePort, Seen};
use rules::Coerce;
use serde_json::{Map, Value, json};
use std::path::Path;

/// The questions and the acts of a kind.
pub trait EngineKind: Send + Sync {
    /// Its id.
    fn id(&self) -> &'static str;
    /// Its name on the board.
    fn label(&self) -> &'static str;
    /// The port it takes when nobody changes it.
    fn default_port(&self) -> i64;
    /// Its processes by the start of their name, lower case: the server, its runners, its helpers.
    fn process_prefixes(&self) -> &'static [&'static str];
    /// What the engine behind `ask` says: `{"state": "ok", "version", "models", …}`; `{"state": "auth"}` when it wants a token; `{"state": "unreachable"}` when nothing answered. `None` when what answers is not this kind.
    fn read(&self, ask: &dyn Fn(&str) -> Seen) -> Option<Value>;
    /// What the operator can do to this engine from the board, as it answered: nothing to an engine that did not answer or wants a token.
    fn controls(&self, seen: &Value) -> Vec<&'static str>;
    /// Removes the model `name` from the engine's disk: "" or its words. A kind that cannot says so, and does not offer it.
    fn delete(&self, port: &EnginePort<'_>, name: &str) -> String {
        let _not_asked = (port, name);
        format!("{} cannot delete a model from here", self.label())
    }
    /// Unloads `model`: "" when it did, else the engine's own words.
    fn unload(&self, port: &EnginePort<'_>, model: &str) -> String;
    /// How to start this kind's server again, learned from the one running now: its process as the machine says it, and its view. `None` when it cannot be told.
    fn recipe(&self, info: Option<&Value>, view: &Value) -> Option<Value>;
    /// A recipe for a server never seen running here, from where this kind puts itself; `None` when it is not there.
    fn installed(&self, home: &Path) -> Option<Value>;
    /// Starts the server the recipe says: "" when it was started, else why not. Whether it answers is the caller's to wait for.
    fn start_server(&self, recipe: &Value, procs: &EngineProcs) -> String;
    /// Stops the server running as `pid`: "" when it was told to stop, else why not.
    fn stop_server(&self, pid: Option<i64>, procs: &EngineProcs) -> String;

    /// Whether a process of this name is the kind's own.
    fn is_its_process(&self, name: Option<&Value>) -> bool {
        let low = if Coerce::truthy(name) { Coerce::stripped(name).to_lowercase() } else { String::new() };
        !low.is_empty() && self.process_prefixes().iter().any(|prefix| low.starts_with(prefix))
    }
}

/// What an engine says, as every kind reads it.
pub struct EngineWords;

impl EngineWords {
    /// A count or a size as the engine said it; `None` when it did not.
    pub fn number(value: Option<&Value>) -> Option<i64> {
        let value = value.filter(|value| !value.is_null() && !value.is_boolean())?;
        if value.as_str().is_some_and(|said| Coerce::strip(said).is_empty()) {
            return None;
        }
        Coerce::int(value)
    }

    /// `str(value or "").strip()[:limit]`.
    pub fn text(value: Option<&Value>, limit: usize) -> String {
        if !Coerce::truthy(value) {
            return String::new();
        }
        Coerce::first_letters(&Coerce::stripped(value), limit).to_string()
    }

    /// "" for a 2xx; the reason for anything else, never empty.
    pub fn refused(status: Option<u16>, words: &str) -> String {
        match status {
            Some(status) if (200..300).contains(&status) => String::new(),
            _ if !words.is_empty() => words.to_string(),
            Some(status) => format!("http {status}"),
            None => "no answer".to_string(),
        }
    }

    /// One model in the shape every kind reports. A field the engine does not say is `null`, never a zero.
    pub fn row(name: &str, fields: Map<String, Value>) -> Value {
        let mut row = json!({
            "name": name, "type": "", "format": "", "family": "", "params": "", "quant": "",
            "fileBytes": null, "remote": false, "loaded": null, "memBytes": null, "vramBytes": null,
            "contextLength": null, "maxContextLength": null, "expiresAt": "", "staysLoaded": null, "instances": null,
        });
        if let Value::Object(out) = &mut row {
            out.extend(fields);
        }
        row
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_number_is_what_the_engine_said_and_nothing_else() {
        assert_eq!(EngineWords::number(Some(&json!(5))), Some(5));
        assert_eq!(EngineWords::number(Some(&json!("7"))), Some(7));
        assert_eq!(EngineWords::number(Some(&json!(0))), Some(0));
        assert_eq!(EngineWords::number(Some(&json!(true))), None);
        assert_eq!(EngineWords::number(Some(&json!(" "))), None);
        assert_eq!(EngineWords::number(Some(&json!("x"))), None);
        assert_eq!(EngineWords::number(None), None);
    }

    #[test]
    fn a_refusal_is_never_empty() {
        assert_eq!(EngineWords::refused(Some(200), "x"), "");
        assert_eq!(EngineWords::refused(Some(404), "gone"), "gone");
        assert_eq!(EngineWords::refused(Some(500), ""), "http 500");
        assert_eq!(EngineWords::refused(None, ""), "no answer");
    }
}
