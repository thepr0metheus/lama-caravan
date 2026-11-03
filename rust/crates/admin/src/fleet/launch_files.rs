//! The files a cell's launch uses, and how they stand against Hugging Face.

use rules::Coerce;
use serde_json::{Map, Value, json};
use std::path::Path;

/// The files a llama.cpp cell takes at launch, each under its role on the card.
pub struct LaunchFiles<'config> {
    config: &'config Map<String, Value>,
    model_path: String,
}

impl<'config> LaunchFiles<'config> {
    const FIELDS: [(&'static str, &'static str); 3] =
        [("MODEL_FILE", "model"), ("MMPROJ_FILE", "mmproj"), ("SPEC_DRAFT_MODEL_FILE", "draft")];
    const SHOWN: [&'static str; 3] = ["size", "date", "unknown"];

    /// The files of `config`, with the model the slot names when the config names none.
    pub fn new(config: &'config Map<String, Value>, model_path: &str) -> Self {
        Self { config, model_path: model_path.to_string() }
    }

    /// `(role, path)` for every file of the launch, each once.
    pub fn files(&self) -> Vec<(&'static str, String)> {
        let mut out: Vec<(&'static str, String)> = Vec::new();
        for (field, role) in Self::FIELDS {
            let said = Coerce::stripped(self.config.get(field));
            let reference =
                if said.is_empty() && field == "MODEL_FILE" { Coerce::strip(&self.model_path).to_string() } else { said };
            if !reference.is_empty() && !out.iter().any(|(_, held)| *held == reference) {
                out.push((role, reference));
            }
        }
        out
    }

    /// `{role, file, state}` for the files the watcher's report says differ from Hugging Face or were not checked.
    pub fn fresh(&self, report: &Value, models_dir: &Path) -> Vec<Value> {
        let mut rows = Vec::new();
        for (role, reference) in self.files() {
            let state = Self::state_of(&reference, report, models_dir);
            if Self::SHOWN.contains(&state.as_str()) {
                let file = reference.rsplit('/').next().unwrap_or(&reference);
                rows.push(json!({"role": role, "file": file, "state": state}));
            }
        }
        rows
    }

    /// A file's state in the watcher's report, or empty.
    pub fn state_of(reference: &str, report: &Value, models_dir: &Path) -> String {
        let reference = Coerce::strip(reference);
        if reference.is_empty() {
            return String::new();
        }
        let path = Path::new(reference);
        let rel = if path.is_absolute() {
            match path.strip_prefix(models_dir) {
                Ok(rel) => rel.to_string_lossy().into_owned(),
                Err(_) => return String::new(),
            }
        } else {
            reference.to_string()
        };
        let repos = report.get("repos").and_then(Value::as_object).into_iter().flatten();
        for (_, repo) in repos {
            if let Some(row) = repo.get("files").and_then(|files| files.get(&rel)).filter(|row| Coerce::truthy(Some(*row))) {
                return Coerce::text(row.get("state"));
            }
        }
        String::new()
    }

    /// The roles a scout says changed on disk after its cell started, kept to the roles the card knows.
    pub fn disk_newer(reported: &[Value]) -> Vec<Value> {
        let roles = Self::FIELDS.map(|row| row.1);
        reported.iter().filter(|role| role.as_str().is_some_and(|role| roles.contains(&role))).cloned().collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_file_of_a_launch_is_named_once() {
        let config = json!({"MODEL_FILE": "a.gguf", "MMPROJ_FILE": "a.gguf", "SPEC_DRAFT_MODEL_FILE": " d.gguf "});
        let config = config.as_object().unwrap();
        assert_eq!(LaunchFiles::new(config, "").files(), [("model", "a.gguf".to_string()), ("draft", "d.gguf".to_string())]);
        let empty = Map::new();
        assert_eq!(LaunchFiles::new(&empty, "m.gguf").files(), [("model", "m.gguf".to_string())]);
    }

    #[test]
    fn a_file_stands_as_the_report_says() {
        let report = json!({"repos": {"r": {"files": {"a/b.gguf": {"state": "size"}, "c.gguf": {"state": "same"}}}}});
        let config = json!({"MODEL_FILE": "/models/a/b.gguf", "MMPROJ_FILE": "c.gguf"});
        let files = LaunchFiles::new(config.as_object().unwrap(), "");
        assert_eq!(files.fresh(&report, Path::new("/models")), [json!({"role": "model", "file": "b.gguf", "state": "size"})]);
        assert_eq!(LaunchFiles::state_of("/elsewhere/x", &report, Path::new("/models")), "");
    }

    #[test]
    fn only_roles_the_card_knows_stay() {
        assert_eq!(LaunchFiles::disk_newer(&[json!("model"), json!("other"), json!(5)]), [json!("model")]);
    }
}
