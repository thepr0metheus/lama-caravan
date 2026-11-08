//! The launch builder's saved parameter sets (static/js/machine-build.js, the owner's choice of 2026-11-06): named, kept per
//! runner and shared by every machine, each holding only fields reviewed as portable from one cell to another — what a client
//! gets back (sampling) and two switches of the server's own behaviour, never a model, a port or a placement. And the owner's
//! per-model mark that a runner is not for that model: a warning shown in the builder, never a refusal.
//!
//! Beside them, read and never written here: what each model's maker stated once (`ModelDefaults`), the preset a model's
//! default cell became on 2026-11-07 (`fleet/default_cells_retired.rs`) — a set the builder offers for that model alone.
//!
//! A stored row that does not read is left out of what is listed and counted (`unread`), so one bad row never hides the others
//! and is never drawn as a set.

use crate::domain::runner::RunnerRegistry;
use crate::models::defaults::ModelDefaults;
use crate::models::notes::ModelNotes;
use crate::store::base::{Document, Store};
use rules::AppError;
use serde_json::{Map, Value, json};

#[derive(Clone, Copy)]
enum PortableValue {
    Number(f64, f64),
    Integer(u64),
    Boolean,
}

/// Shared operator choices. They never change or start a cell.
pub struct RunnerPresets;

impl RunnerPresets {
    const PRESETS: &'static str = "runnerPresets";
    const WARNINGS: &'static str = "modelRunnerWarnings";
    // Sampling defaults and two behavioural switches, used by the common llama argument builder.
    const LLAMA_FIELDS: [(&'static str, PortableValue); 6] = [
        ("TEMPERATURE", PortableValue::Number(0.0, 2.0)),
        ("TOP_K", PortableValue::Integer(100000)),
        ("TOP_P", PortableValue::Number(0.0, 1.0)),
        ("MIN_P", PortableValue::Number(0.0, 1.0)),
        ("CACHE_PROMPT", PortableValue::Boolean),
        ("CONTEXT_SHIFT", PortableValue::Boolean),
    ];

    fn runner(registry: &RunnerRegistry, id: &str) -> Result<(), AppError> {
        if registry.all().any(|runner| runner.row().id == id) { Ok(()) } else { Err(AppError::new("unknown runner")) }
    }

    fn name(name: &str) -> Result<(), AppError> {
        if name.trim() != name || name.is_empty() || name.chars().count() > 80 || name.chars().any(char::is_control) {
            return Err(AppError::new("name must be 1–80 characters, without surrounding whitespace or control characters"));
        }
        Ok(())
    }

    /// The permitted fields are deliberately per runner, not inferred from the config registry.
    pub fn fields(registry: &RunnerRegistry, runner: &str) -> Result<Value, AppError> {
        Self::runner(registry, runner)?;
        Ok(Value::Object(
            Self::allowed(registry, runner)
                .iter()
                .map(|(name, kind)| {
                    let spec = match kind {
                        PortableValue::Number(min, max) => json!({"type": "number", "min": min, "max": max}),
                        PortableValue::Integer(max) => json!({"type": "integer", "min": 0, "max": max}),
                        PortableValue::Boolean => json!({"type": "boolean"}),
                    };
                    ((*name).to_string(), spec)
                })
                .collect(),
        ))
    }

    /// The fields a set of `runner` may hold: the llama.cpp family's, by its registry row (`llama_config`), so a runner of the family
    /// added later gets them without a second list; none for any other runner yet — nobody has reviewed theirs.
    fn allowed(registry: &RunnerRegistry, runner: &str) -> &'static [(&'static str, PortableValue)] {
        let llama = registry.all().any(|row| row.row().id == runner && row.row().llama_config);
        if llama { &Self::LLAMA_FIELDS } else { &[] }
    }

    fn validate(registry: &RunnerRegistry, runner: &str, params: &Value) -> Result<Map<String, Value>, AppError> {
        Self::runner(registry, runner)?;
        let params = params.as_object().ok_or_else(|| AppError::new("params must be an object"))?;
        if params.is_empty() {
            return Err(AppError::new("params must not be empty"));
        }
        for (key, value) in params {
            let Some((_, kind)) = Self::allowed(registry, runner).iter().find(|(name, _)| *name == key) else {
                return Err(AppError::new(format!("field not portable for this runner: {key}")));
            };
            let valid = match kind {
                PortableValue::Number(min, max) => value.as_f64().is_some_and(|n| n >= *min && n <= *max),
                PortableValue::Integer(max) => value.as_u64().is_some_and(|n| n <= *max),
                PortableValue::Boolean => value.is_boolean(),
            };
            if !valid {
                return Err(AppError::new(format!("invalid value for {key}")));
            }
        }
        Ok(params.clone())
    }

    /// What is kept: the sets that read, the marks that read, and how many stored rows did not (`unread`) — absent sections are
    /// empty, not an invented set or mark, and a row that does not read is left out and counted rather than failing the whole list.
    /// And the maker's numbers by model (`makers`): the program's own table, so it is never a stored row that could fail to read.
    pub fn list(doc: &Document, registry: &RunnerRegistry) -> Value {
        let mut unread = 0;
        let mut presets = Map::new();
        for (runner, sets) in doc.get(Self::PRESETS).and_then(Value::as_object).into_iter().flatten() {
            let Some(sets) = sets.as_object().filter(|_| Self::runner(registry, runner).is_ok()) else {
                unread += 1;
                continue;
            };
            let mut kept = Map::new();
            for (name, params) in sets {
                match Self::name(name).and_then(|()| Self::validate(registry, runner, params)) {
                    Ok(params) => {
                        kept.insert(name.clone(), Value::Object(params));
                    }
                    Err(_) => unread += 1,
                }
            }
            if !kept.is_empty() {
                presets.insert(runner.clone(), Value::Object(kept));
            }
        }
        let mut warnings = Map::new();
        for (model, marks) in doc.get(Self::WARNINGS).and_then(Value::as_object).into_iter().flatten() {
            let named = ModelNotes::named(model).is_ok_and(|named| named == *model);
            let Some(marks) = marks.as_object().filter(|_| named) else {
                unread += 1;
                continue;
            };
            let mut kept = Map::new();
            for (runner, mark) in marks {
                if mark == &json!(true) && Self::runner(registry, runner).is_ok() {
                    kept.insert(runner.clone(), json!(true));
                } else {
                    unread += 1;
                }
            }
            if !kept.is_empty() {
                warnings.insert(model.clone(), Value::Object(kept));
            }
        }
        json!({"presets": presets, "warnings": warnings, "makers": ModelDefaults::answer(), "unread": unread})
    }

    /// Insert or replace one named set.
    pub fn put(doc: &mut Document, registry: &RunnerRegistry, runner: &str, name: &str, params: &Value) -> Result<(), AppError> {
        Self::name(name)?;
        let params = Self::validate(registry, runner, params)?;
        let section = Store::section(doc, Self::PRESETS, &[]);
        let sets = section.entry(runner.to_string()).or_insert_with(|| json!({}));
        let sets = sets.as_object_mut().ok_or_else(|| AppError::new("invalid stored presets"))?;
        sets.insert(name.to_string(), Value::Object(params));
        Ok(())
    }

    /// Remove one set; removing an absent set is harmless. Asked of any runner the file holds — a set of a runner the caravan no
    /// longer has is still the operator's to take away — and a runner left with no set leaves no empty section behind.
    pub fn remove(doc: &mut Document, runner: &str, name: &str) -> Result<(), AppError> {
        Self::name(name)?;
        let Some(section) = doc.get_mut(Self::PRESETS).and_then(Value::as_object_mut) else {
            return Ok(());
        };
        if let Some(sets) = section.get_mut(runner).and_then(Value::as_object_mut) {
            sets.shift_remove(name);
            if sets.is_empty() {
                section.shift_remove(runner);
            }
        }
        Ok(())
    }

    /// A mark is shared with the model's other notes, by model folder, not inferred compatibility.
    pub fn mark(
        doc: &mut Document,
        registry: &RunnerRegistry,
        model: &str,
        runner: &str,
        unwanted: bool,
    ) -> Result<(), AppError> {
        let model = ModelNotes::named(model)?;
        Self::runner(registry, runner)?;
        if unwanted {
            let section = Store::section(doc, Self::WARNINGS, &[]);
            let marks = section.entry(model).or_insert_with(|| json!({}));
            marks
                .as_object_mut()
                .ok_or_else(|| AppError::new("invalid stored warnings"))?
                .insert(runner.to_string(), json!(true));
            return Ok(());
        }
        // Taking a mark off writes nothing where there was nothing: no empty section for a model nobody marked.
        let Some(section) = doc.get_mut(Self::WARNINGS).and_then(Value::as_object_mut) else {
            return Ok(());
        };
        if let Some(marks) = section.get_mut(&model).and_then(Value::as_object_mut) {
            marks.shift_remove(runner);
            if marks.is_empty() {
                section.shift_remove(&model);
            }
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::domain::runner::RunnerDefaults;

    fn registry() -> RunnerRegistry {
        RunnerRegistry::new(&RunnerDefaults { models_dir: "/m".into(), home: "/h".into() }).unwrap()
    }

    #[test]
    fn only_reviewed_values_are_stored_and_false_is_not_absent() {
        let r = registry();
        let mut doc = Document::new();
        RunnerPresets::put(&mut doc, &r, "llama-server", "quiet", &json!({"CACHE_PROMPT": false, "TOP_P": 0.5})).unwrap();
        assert_eq!(RunnerPresets::list(&doc, &r)["presets"]["llama-server"]["quiet"]["CACHE_PROMPT"], false);
        for params in [
            json!({"MODEL_FILE":"/x"}),
            json!({"TOP_P":"0.5;evil"}),
            json!({"TOP_P":2}),
            json!({"CACHE_PROMPT":null}),
            json!({"TOP_K":1.5}),
            json!({}),
        ] {
            assert!(RunnerPresets::put(&mut doc, &r, "llama-server", "bad", &params).is_err());
        }
        assert!(RunnerPresets::put(&mut doc, &r, "vllm", "bad", &json!({"TOP_P":0.5})).is_err());
        assert!(RunnerPresets::put(&mut doc, &r, "unknown", "bad", &json!({"TOP_P":0.5})).is_err());
        RunnerPresets::remove(&mut doc, "llama-server", "quiet").unwrap();
        let listed = RunnerPresets::list(&doc, &r);
        assert!(listed["presets"].get("llama-server").is_none(), "a runner with no set left leaves no section: {listed}");
        RunnerPresets::mark(&mut doc, &r, "model", "vllm", true).unwrap();
        assert_eq!(RunnerPresets::list(&doc, &r)["warnings"]["model"]["vllm"], true);
        RunnerPresets::mark(&mut doc, &r, "model", "vllm", false).unwrap();
        assert!(RunnerPresets::list(&doc, &r)["warnings"].get("model").is_none());
        assert!(RunnerPresets::mark(&mut doc, &r, "../bad", "vllm", true).is_err());
    }

    #[test]
    fn a_stored_row_that_does_not_read_is_left_out_and_counted() {
        let r = registry();
        let mut doc = Document::new();
        RunnerPresets::put(&mut doc, &r, "llama-server", "good", &json!({"TOP_P": 0.9})).unwrap();
        doc.insert(
            "runnerPresets".into(),
            json!({
                "llama-server": {"good": {"TOP_P": 0.9}, "bad": {"TOP_P": "x"}},
                "gone-runner": {"old": {"TOP_P": 0.5}},
            }),
        );
        let listed = RunnerPresets::list(&doc, &r);
        assert_eq!(listed["presets"], json!({"llama-server": {"good": {"TOP_P": 0.9}}}));
        assert_eq!(listed["unread"], 2, "the bad set and the runner the caravan no longer has: {listed}");
        // A set of a runner the caravan no longer has is still the operator's to take away.
        RunnerPresets::remove(&mut doc, "gone-runner", "old").unwrap();
        assert_eq!(RunnerPresets::list(&doc, &r)["unread"], 1);
    }

    #[test]
    fn taking_a_mark_off_writes_nothing_where_there_was_nothing() {
        let r = registry();
        let mut doc = Document::new();
        RunnerPresets::mark(&mut doc, &r, "model", "vllm", false).unwrap();
        assert!(doc.get("modelRunnerWarnings").is_none(), "no empty section for a model nobody marked");
    }
}
