//! What the owner keeps on each model, whatever its quants. Keyed by the model's folder: the first folder of its path.

use crate::store::topology::Topology;
use rules::{AppError, Coerce};
use serde_json::{Map, Value, json};

/// The comments on the models, one reading of the section that holds them.
pub struct ModelNotes<'section> {
    section: &'section mut Map<String, Value>,
    limit: usize,
}

impl<'section> ModelNotes<'section> {
    const LIMIT: usize = 1000;
    const ROOT: &'static str = "(root)";
    const NAME_LIMIT: usize = 255;

    /// A reading of `section`.
    pub fn new(section: &'section mut Map<String, Value>, limit: usize) -> Self {
        Self { section, limit }
    }

    /// The model a path lies in, or "" when it names none.
    pub fn model_of(path: &str, models_root: &str) -> String {
        let path = Coerce::strip(path);
        let rest = if path.starts_with('/') {
            let root = models_root.trim_end_matches('/');
            let tail = path.strip_prefix(&format!("{root}/")).filter(|_| !root.is_empty());
            let Some(tail) = tail else {
                return String::new();
            };
            tail
        } else {
            path
        };
        let parts: Vec<&str> = rest.split('/').filter(|part| !part.is_empty()).collect();
        if parts.len() > 1 && !parts.contains(&"..") {
            parts.first().map_or_else(String::new, |first| (*first).to_string())
        } else {
            String::new()
        }
    }

    /// `model` as a folder of the list names it, or a refusal.
    pub fn named(model: &str) -> Result<String, AppError> {
        let model = Coerce::strip(model);
        let bad = model.is_empty()
            || model == Self::ROOT
            || model.chars().count() > Self::NAME_LIMIT
            || model.contains('/')
            || model.contains('\\')
            || model.chars().any(|letter| (letter as u32) < 32);
        if bad {
            return Err(AppError::new("model must be the name of a folder of the models list"));
        }
        Ok(model.to_string())
    }

    /// Every comment that has words, by model folder.
    pub fn all(&self) -> Map<String, Value> {
        self.section
            .iter()
            .filter_map(|(model, text)| text.as_str().map(|text| (model.clone(), Coerce::strip(text).to_string())))
            .filter(|(_, text)| !text.is_empty())
            .map(|(model, text)| (model, json!(text)))
            .collect()
    }

    /// Keeps `text` as the comment on `model`; no words take it away.
    pub fn set(&mut self, model: &str, text: &str) -> Result<String, AppError> {
        let model = Self::named(model)?;
        let normal = text.replace("\r\n", "\n").replace('\r', "\n");
        let text = Coerce::strip(&normal);
        let length = text.chars().count();
        if length > self.limit {
            return Err(AppError::new(format!("a comment is at most {} characters, this one has {length}", self.limit)));
        }
        if text.is_empty() {
            self.section.shift_remove(&model);
        } else {
            self.section.insert(model, json!(text));
        }
        Ok(text.to_string())
    }

    /// The comment of the model each cell runs, by the cell's key.
    pub fn for_cells(&self, refs: &[(String, String)], models_root: &str) -> Map<String, Value> {
        let notes = self.all();
        refs.iter()
            .filter_map(|(key, path)| notes.get(&Self::model_of(path, models_root)).map(|note| (key.clone(), note.clone())))
            .collect()
    }
}

/// The owner's texts on a model, one reading of its section each.
pub struct ModelFields;

impl ModelFields {
    /// Field, section, its limit, the answer's key.
    const TABLE: [(&'static str, &'static str, usize, &'static str); 3] = [
        ("note", "modelNotes", ModelNotes::LIMIT, "notes"),
        ("params", "modelParams", 4000, "params"),
        ("comment", "modelComments", ModelNotes::LIMIT, "comments"),
    ];

    /// A field's reading, or a refusal.
    pub fn of<'doc>(topology: &'doc mut Topology<'_>, field: &str) -> Result<ModelNotes<'doc>, AppError> {
        let Some((_, section, limit, _)) = Self::TABLE.iter().find(|(name, ..)| *name == field) else {
            return Err(AppError::new("field must be one of note, params, comment"));
        };
        Ok(ModelNotes::new(topology.named(section), *limit))
    }

    /// What the page reads.
    pub fn answer(topology: &mut Topology<'_>) -> Value {
        let mut out = Map::new();
        for (_, section, limit, key) in Self::TABLE {
            out.insert(key.to_string(), Value::Object(ModelNotes::new(topology.named(section), limit).all()));
        }
        let limits: Map<String, Value> =
            Self::TABLE.iter().map(|(field, _, limit, _)| ((*field).to_string(), json!(limit))).collect();
        out.insert("limits".to_string(), Value::Object(limits));
        Value::Object(out)
    }
}

/// The owner's like or dislike of each model, one for all its quants.
pub struct ModelRatings<'section> {
    section: &'section mut Map<String, Value>,
}

impl<'section> ModelRatings<'section> {
    const VALUES: [&'static str; 2] = ["like", "dislike"];

    /// A reading of `section`.
    pub fn new(section: &'section mut Map<String, Value>) -> Self {
        Self { section }
    }

    /// Every mark, by model folder.
    pub fn all(&self) -> Map<String, Value> {
        self.section
            .iter()
            .filter(|(_, rating)| rating.as_str().is_some_and(|word| Self::VALUES.contains(&word)))
            .map(|(model, rating)| (model.clone(), rating.clone()))
            .collect()
    }

    /// Keeps `rating` on `model`; empty takes it away.
    pub fn set(&mut self, model: &str, rating: Option<&Value>) -> Result<Value, AppError> {
        let model = ModelNotes::named(model)?;
        let rating = rating.cloned().unwrap_or(Value::Null);
        let rating = if rating.is_null() { json!("") } else { rating };
        if !Coerce::truthy(Some(&rating)) {
            self.section.shift_remove(&model);
            return Ok(rating);
        }
        if !rating.as_str().is_some_and(|word| Self::VALUES.contains(&word)) {
            return Err(AppError::new("rating must be one of like, dislike, or empty"));
        }
        self.section.insert(model, rating.clone());
        Ok(rating)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_path_names_its_model() {
        assert_eq!(ModelNotes::model_of("Qwen/a/b.gguf", ""), "Qwen");
        assert_eq!(ModelNotes::model_of("b.gguf", ""), "");
        assert_eq!(ModelNotes::model_of("../a/b.gguf", ""), "");
        assert_eq!(ModelNotes::model_of("/m/Qwen/b.gguf", "/m/"), "Qwen");
        assert_eq!(ModelNotes::model_of("/x/Qwen/b.gguf", "/m"), "");
    }

    #[test]
    fn a_comment_is_kept_and_taken_away() {
        let mut section = Map::new();
        let mut notes = ModelNotes::new(&mut section, 5);
        assert_eq!(notes.set("m", " a\r\nb ").unwrap(), "a\nb");
        assert_eq!(notes.all().get("m"), Some(&json!("a\nb")));
        assert!(notes.set("m", "123456").unwrap_err().message.contains("this one has 6"));
        assert_eq!(notes.set("m", " ").unwrap(), "");
        assert!(notes.all().is_empty());
        assert!(notes.set("a/b", "x").is_err());
        assert!(notes.set("(root)", "x").is_err());
    }

    #[test]
    fn a_mark_is_one_of_two() {
        let mut section = Map::new();
        let mut ratings = ModelRatings::new(&mut section);
        assert_eq!(ratings.set("m", Some(&json!("like"))).unwrap(), json!("like"));
        assert!(ratings.set("m", Some(&json!("love"))).is_err());
        assert_eq!(ratings.set("m", None).unwrap(), json!(""));
        assert!(ratings.all().is_empty());
    }
}
