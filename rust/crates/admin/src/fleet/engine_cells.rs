//! A cell reserved to run inside an engine next to it: what it is made of.

use crate::app::App;
use rules::{AppError, Coerce, PyRepr};
use serde_json::{Value, json};

/// The config of a cell in one engine of one machine, or the refusal that says why there is none.
pub struct EngineCellPlan<'app> {
    app: &'app App,
    host: Option<&'app Value>,
    kind: String,
    model: String,
}

impl<'app> EngineCellPlan<'app> {
    /// The engines a cell can run in.
    pub fn kinds(app: &App) -> Vec<&'static str> {
        app.runners.all().filter(|runner| runner.row().engine_cell).map(|runner| runner.row().id).collect()
    }

    /// The plan a reserve request asks for; `None` when it names no engine: an ordinary reserve, a cell the caravan runs itself.
    pub fn from_body(app: &'app App, host: Option<&'app Value>, body: &Value) -> Option<Self> {
        let engine = Coerce::stripped(body.get("engine"));
        if engine.is_empty() {
            return None;
        }
        Some(Self {
            app,
            host: host.filter(|host| host.is_object()),
            kind: engine.to_lowercase(),
            model: Coerce::stripped(body.get("model")),
        })
    }

    /// The machine's reported engine of this kind, running and listing the model.
    fn engine(&self) -> Result<&Value, AppError> {
        let kinds = Self::kinds(self.app);
        if !kinds.contains(&self.kind.as_str()) {
            return Err(AppError::new(format!("a cell runs in {}, not in {}", kinds.join(", "), PyRepr::of(&self.kind))));
        }
        let host = self.host.ok_or_else(|| AppError::with_status("no scout has reported for this machine", 404))?;
        let reported = host.get("engines").filter(|said| !said.is_null());
        let reported = reported.ok_or_else(|| {
            AppError::with_status("this machine's scout does not look for engines — it is older than 2.12", 409)
        })?;
        let found = reported
            .as_array()
            .into_iter()
            .flatten()
            .find(|row| row.get("kind").and_then(Value::as_str) == Some(self.kind.as_str()));
        let found = found.ok_or_else(|| AppError::with_status(format!("this machine reports no {}", self.kind), 404))?;
        let name = {
            let label = Coerce::text(found.get("label"));
            if label.is_empty() { self.kind.clone() } else { label }
        };
        let state = found.get("state");
        if state.and_then(Value::as_str) != Some("ok") {
            let words = match state.and_then(Value::as_str) {
                Some("stopped") => format!("{name} is not running on this machine — start its server first"),
                Some("unreachable") => format!("{name} is not answering on this machine"),
                Some("auth") => format!("{name} on this machine asks for a token, and a cell has none to give it"),
                _ => format!("{name} on this machine answers {}", PyRepr::of_value(state.unwrap_or(&Value::Null))),
            };
            return Err(AppError::with_status(words, 409));
        }
        let models = found.get("models").filter(|said| !said.is_null());
        let models = models.ok_or_else(|| {
            AppError::with_status(format!("{name} did not list its models, so the cell's model cannot be checked"), 409)
        })?;
        if !Coerce::truthy(Some(models)) {
            return Err(AppError::with_status(format!("{name} on this machine has no models — download one into it first"), 409));
        }
        if self.model.is_empty() {
            return Err(AppError::new("a cell in an engine is reserved with its model"));
        }
        let listed = models
            .as_array()
            .into_iter()
            .flatten()
            .any(|row| row.get("name").and_then(Value::as_str) == Some(self.model.as_str()));
        if !listed {
            return Err(AppError::with_status(format!("{name} has no model {} on this machine", self.model), 404));
        }
        Ok(found)
    }

    /// What the cell's config holds.
    pub fn config(&self) -> Result<Value, AppError> {
        let found = self.engine()?;
        let port = Coerce::str_of(found.get("port"));
        Ok(json!({"RUNNER": self.kind, "CELL_KIND": "command", "ENGINE_MODEL": self.model, "ENGINE_PORT": port}))
    }
}

/// Whether the model of a cell in an engine fits into its machine's cards, asked before the cell starts it (2026-09-26).
pub struct EngineCellFit;

impl EngineCellFit {
    fn model_row<'host>(app: &App, host: &'host Value, config: &Value) -> Option<&'host Value> {
        let kind = Coerce::stripped(config.get("RUNNER")).to_lowercase();
        let model = Coerce::stripped(config.get("ENGINE_MODEL"));
        if model.is_empty() || !EngineCellPlan::kinds(app).contains(&kind.as_str()) {
            return None;
        }
        let engines = host.get("engines").and_then(Value::as_array).into_iter().flatten();
        let engine = engines.into_iter().find(|engine| engine.get("kind").and_then(Value::as_str) == Some(kind.as_str()))?;
        let models = engine.get("models").and_then(Value::as_array).into_iter().flatten();
        models.into_iter().find(|row| row.get("name").and_then(Value::as_str) == Some(model.as_str()))
    }

    /// Bytes free on all the machine's cards together; `None` when there is no card, or one does not say.
    fn free_bytes(host: &Value) -> Option<i64> {
        let cards = host.get("gpus").and_then(Value::as_array).filter(|cards| !cards.is_empty())?;
        let mut free = 0.0;
        for card in cards {
            free += card.get("memoryFreeMiB").and_then(Coerce::float)?;
        }
        Some((free * 1024.0 * 1024.0) as i64)
    }

    /// `{model, needBytes, freeBytes, basis}` when the model would not fit; `None` when it would, or nothing says.
    pub fn short(app: &App, host: Option<&Value>, config: Option<&Value>) -> Option<Value> {
        let (host, config) = (host.filter(|host| host.is_object())?, config.filter(|config| config.is_object())?);
        let row = Self::model_row(app, host, config)?;
        if row.get("loaded") == Some(&json!(true)) || row.get("remote") == Some(&json!(true)) {
            return None;
        }
        let need = row.get("fileBytes").and_then(Value::as_i64).filter(|need| *need > 0)?;
        let free = Self::free_bytes(host).filter(|free| need > *free)?;
        Some(
            json!({"model": Coerce::stripped(config.get("ENGINE_MODEL")), "needBytes": need, "freeBytes": free, "basis": "weights"}),
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn free_memory_is_unknown_when_a_card_does_not_say() {
        assert_eq!(
            EngineCellFit::free_bytes(&json!({"gpus": [{"memoryFreeMiB": "1"}, {"memoryFreeMiB": 1}]})),
            Some(2 * 1024 * 1024)
        );
        assert_eq!(EngineCellFit::free_bytes(&json!({"gpus": [{"memoryFreeMiB": "[N/A]"}]})), None);
        assert_eq!(EngineCellFit::free_bytes(&json!({"gpus": []})), None);
    }
}
