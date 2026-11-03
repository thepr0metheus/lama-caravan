//! What the cloud file and the catalogue say of the accounts' models.

use crate::coerce::Coerce;
use crate::model_kind::ModelKind;
use serde_json::Value;
use std::collections::{BTreeMap, BTreeSet};

/// The models the operator added to Routing's right column, by account: `addedModels`.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct AddedModels {
    kept: BTreeMap<String, Vec<String>>,
}

impl AddedModels {
    /// The file's map. A model named twice under an account is one; a blank account or model is none.
    pub fn read(raw: Option<&Value>) -> Self {
        let mut read = Self::default();
        for (account, models) in raw.and_then(Value::as_object).into_iter().flatten() {
            let account = Coerce::strip(account);
            for model in models.as_array().into_iter().flatten() {
                let model = Coerce::stripped(Some(model));
                let kept = read.kept.entry(account.to_string()).or_default();
                if !account.is_empty() && !model.is_empty() && !kept.contains(&model) {
                    kept.push(model);
                }
            }
        }
        read
    }

    /// The account's models, in the order they were added.
    pub fn of(&self, account: &str) -> &[String] {
        self.kept.get(account).map_or(&[], Vec::as_slice)
    }
}

/// What the operator said a key's model does: `modelJobs`.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct AccountModelJobs {
    kept: BTreeMap<(String, String), Vec<&'static str>>,
}

impl AccountModelJobs {
    /// The file's map. What is no offered job is no word.
    pub fn read(raw: Option<&Value>) -> Self {
        let mut read = Self::default();
        for (account, models) in raw.and_then(Value::as_object).into_iter().flatten() {
            for (model, jobs) in models.as_object().into_iter().flatten() {
                let said: Vec<&str> = jobs.as_array().into_iter().flatten().filter_map(Value::as_str).collect();
                let jobs = ModelKind::offered_jobs(&said);
                let key = (Coerce::strip(account).to_string(), Coerce::strip(model).to_string());
                if jobs.is_empty() {
                    read.kept.remove(&key);
                } else if !key.0.is_empty() && !key.1.is_empty() {
                    read.kept.insert(key, jobs);
                }
            }
        }
        read
    }

    /// The jobs said of one model, or `None` when nobody said.
    pub fn of(&self, account: &str, model: &str) -> Option<&[&'static str]> {
        self.kept.get(&(account.to_string(), model.to_string())).map(Vec::as_slice)
    }
}

/// What the accounts' providers last named as their models' windows: a cache the controller writes when a list is refreshed. The
/// alternative is a network call on a question this proxy answers locally, and absence stays absence.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct ModelCatalogue {
    windows: BTreeMap<(String, String), Option<i64>>,
    /// The accounts with a list at all: a model a list does not name is one its provider no longer has.
    listed: BTreeSet<String>,
}

impl ModelCatalogue {
    /// The catalogue's document; one that does not read knows nothing.
    pub fn read(raw: Option<&Value>) -> Self {
        let mut read = Self::default();
        let accounts = raw.and_then(|document| document.get("accounts")).and_then(Value::as_object);
        for (account, entry) in accounts.into_iter().flatten() {
            if entry.get("models").is_some_and(Value::is_array) {
                read.listed.insert(account.clone());
            }
            for model in entry.get("models").and_then(Value::as_array).into_iter().flatten() {
                if let Some(id) = model.get("id").and_then(Value::as_str) {
                    let window = model.get("contextLength").and_then(Value::as_i64).filter(|window| *window > 0);
                    read.windows.entry((account.clone(), id.to_string())).or_insert(window);
                }
            }
        }
        read
    }

    /// Whether `account`'s provider lists `model`; `None` when it has no list.
    pub fn lists(&self, account: &str, model: &str) -> Option<bool> {
        (self.listed.contains(account) && !model.is_empty())
            .then(|| self.windows.contains_key(&(account.to_string(), model.to_string())))
    }

    /// The window `account`'s provider named for `model`.
    pub fn window(&self, account: &str, model: &str) -> Option<i64> {
        self.windows.get(&(account.to_string(), model.to_string())).copied().flatten()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn added_models_keep_their_order_and_drop_what_is_blank_or_said_twice() {
        let added = AddedModels::read(Some(&json!({" a ": ["z", " y ", "z", "", 5], "b": "not a list", "": ["q"]})));
        assert_eq!(added.of("a"), ["z", "y", "5"]);
        assert!(added.of("b").is_empty());
        assert!(added.of("").is_empty());
        assert!(added.of("nobody").is_empty());
    }

    #[test]
    fn jobs_are_only_the_offered_ones_and_none_is_no_word() {
        let jobs = AccountModelJobs::read(Some(
            &json!({"a": {"both": ["tts", "llm"], "other": ["robot-policy"], "none": [], "odd": "llm"}}),
        ));
        assert_eq!(jobs.of("a", "both"), Some(&["llm", "tts"][..]));
        assert_eq!(jobs.of("a", "other"), None);
        assert_eq!(jobs.of("a", "none"), None);
        assert_eq!(jobs.of("a", "odd"), None);
        assert_eq!(jobs.of("b", "both"), None);
    }

    #[test]
    fn a_blank_account_or_model_is_no_key_of_a_word() {
        let jobs = AccountModelJobs::read(Some(&json!({"": {"m": ["llm"]}, "a": {" ": ["llm"], "m": ["llm"]}})));
        assert_eq!(jobs.of("", "m"), None);
        assert_eq!(jobs.of("a", ""), None);
        assert_eq!(jobs.of("a", "m"), Some(&["llm"][..]));
    }

    #[test]
    fn the_catalogue_s_first_row_of_a_model_answers_and_a_figure_that_is_no_size_is_none() {
        let catalogue = ModelCatalogue::read(Some(&json!({"accounts": {"a": {"models": [
            {"id": "m", "contextLength": 100}, {"id": "m", "contextLength": 200},
            {"id": "zero", "contextLength": 0}, {"id": "flag", "contextLength": true}, {"id": "text", "contextLength": "9"},
            {"id": "shown", "contextLength": 5.0}, {"id": "gone", "contextLength": 9}, {"id": "gone", "contextLength": 0}, "row",
            {"id": 7, "contextLength": 7},
        ]}}})));
        assert_eq!(catalogue.window("a", "m"), Some(100));
        assert_eq!(catalogue.window("a", "gone"), Some(9));
        for model in ["zero", "flag", "text", "shown", "nobody", "7"] {
            assert_eq!(catalogue.window("a", model), None, "{model}");
        }
        assert_eq!(catalogue.window("b", "m"), None);
    }

    #[test]
    fn a_first_row_with_no_size_still_answers_for_its_model() {
        let catalogue = ModelCatalogue::read(Some(&json!({"accounts": {"a": {"models": [
            {"id": "m", "contextLength": 0}, {"id": "m", "contextLength": 200},
        ]}}})));
        assert_eq!(catalogue.window("a", "m"), None);
    }
}
