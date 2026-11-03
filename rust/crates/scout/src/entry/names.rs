//! What a cell's model is called at the machine's entry.

use rules::Coerce;
use serde_json::{Map, Value};

/// The name its operator gave it (`MODEL_NAME`), else the cell's alias (`ALIAS`: what `llama-server` answers with), else one made of its model: a GGUF file's name without `.gguf` (and without the part a split file adds),
/// a folder's own name; Whisper and Moonshine by their size or language. Nothing to go by: `cell-<port>`, a name that says it was not given one. Made of the cell's settings alone, so a model keeps its name while it is stopped.
pub struct ModelName;

impl ModelName {
    /// What the settings' own name is made of.
    pub const KEYS: [&'static str; 2] = ["MODEL_NAME", "ALIAS"];
    const SIZES: [(&'static str, &'static str); 2] = [("whisper", "WHISPER_MODEL"), ("moonshine", "MOONSHINE_MODEL")];

    fn said(config: &Map<String, Value>, key: &str) -> String {
        let value = config.get(key).filter(|value| Coerce::truthy(Some(*value)));
        if value.is_some() { Coerce::stripped(value) } else { String::new() }
    }

    /// The name. Settings that are no object say nothing.
    pub fn of(config: Option<&Value>, model_path: &str, port: i64) -> String {
        let empty = Map::new();
        let config = config.and_then(Value::as_object).unwrap_or(&empty);
        for key in Self::KEYS {
            let said = Self::said(config, key);
            if !said.is_empty() {
                return said;
            }
        }
        let runner = Self::said(config, "RUNNER").to_lowercase();
        for (kind, key) in Self::SIZES {
            let size = Self::said(config, key);
            if runner == kind && !size.is_empty() {
                return format!("{kind}-{size}");
            }
        }
        let file = Self::said(config, "MODEL_FILE");
        let path = if file.is_empty() { Coerce::strip(model_path) } else { file.as_str() };
        let made = Self::from_path(path);
        if !made.is_empty() {
            return made;
        }
        if port != 0 { format!("cell-{port}") } else { String::new() }
    }

    /// What a split GGUF adds to each file's name: `model-00001-of-00003` is the model `model`.
    fn without_split(name: &str) -> &str {
        const TAIL: usize = "-00001-of-00003".len();
        let Some(head) = name.len().checked_sub(TAIL).and_then(|at| name.get(..at)) else {
            return name;
        };
        // absent-ok: a tail cut through a letter is no split tail.
        let tail = name.get(head.len()..).unwrap_or_default();
        let is_split = tail.chars().enumerate().all(|(at, letter)| match at {
            0 | 6 | 9 => letter == '-',
            7 => letter == 'o',
            8 => letter == 'f',
            _ => letter.is_ascii_digit(),
        });
        if is_split { head } else { name }
    }

    /// `models--<owner>--<repository>` is how HF lays its files out, not the model's name.
    fn of_hf_cache(part: &str) -> Option<&str> {
        let rest = part.strip_prefix("models--")?;
        let (_, tail) = rest.char_indices().skip(1).find_map(|(at, _)| {
            let (head, tail) = rest.split_at(at);
            tail.strip_prefix("--").filter(|tail| !tail.is_empty() && !head.contains('/')).map(|tail| (head, tail))
        })?;
        Some(tail)
    }

    /// A model's name from where it lies: a GGUF file, its name without `.gguf`; a folder of HF's cache, its repository's name; a folder named under the models' root, its first part; an absolute folder, the part after `models`, else its last part.
    pub fn from_path(path: &str) -> String {
        let path = Coerce::strip(path).trim_end_matches('/');
        if path.is_empty() {
            return String::new();
        }
        let parts: Vec<&str> = path.split('/').filter(|part| !part.is_empty() && *part != ".").collect();
        // absent-ok: a path of slashes and dots alone names nothing.
        let last = parts.last().copied().unwrap_or_default();
        if path.to_lowercase().ends_with(".gguf") {
            let stem = last.char_indices().rev().nth(4).map_or("", |(at, _)| last.get(..at).unwrap_or_default());
            return Self::without_split(stem).to_string();
        }
        if let Some(repository) = parts.iter().find_map(|part| Self::of_hf_cache(part)) {
            return repository.to_string();
        }
        if !path.starts_with('/') {
            // absent-ok: as above.
            return parts.first().copied().unwrap_or_default().to_string();
        }
        let (_, before_last) = (last, parts.split_last().map_or(&[][..], |(_, head)| head));
        match before_last.iter().position(|part| *part == "models") {
            // absent-ok: `models` stands before the last part, so one follows it.
            Some(at) => parts.get(at + 1).copied().unwrap_or_default().to_string(),
            None => last.to_string(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn a_name_comes_from_the_settings_first() {
        assert_eq!(ModelName::of(Some(&json!({"MODEL_NAME": " mine ", "ALIAS": "other"})), "x.gguf", 1), "mine");
        assert_eq!(ModelName::of(Some(&json!({"ALIAS": "other"})), "x.gguf", 1), "other");
        assert_eq!(ModelName::of(Some(&json!({"RUNNER": "Whisper", "WHISPER_MODEL": "large-v3"})), "", 1), "whisper-large-v3");
        assert_eq!(
            ModelName::of(Some(&json!({"RUNNER": "llama", "WHISPER_MODEL": "large-v3", "MODEL_FILE": "a/b.gguf"})), "", 1),
            "b"
        );
        assert_eq!(ModelName::of(None, "", 22001), "cell-22001");
        assert_eq!(ModelName::of(Some(&json!([1])), "", 0), "");
    }

    #[test]
    fn a_name_from_where_it_lies() {
        assert_eq!(ModelName::from_path("dir/model-00001-of-00003.gguf"), "model");
        assert_eq!(ModelName::from_path("/x/Model.GGUF"), "Model");
        assert_eq!(
            ModelName::from_path("whisper/models--Systran--faster-whisper-large-v3-turbo"),
            "faster-whisper-large-v3-turbo"
        );
        assert_eq!(ModelName::from_path("seamless-m4t-v2-large/facebook/FP32"), "seamless-m4t-v2-large");
        assert_eq!(ModelName::from_path("/data/models/qwen/snapshots/"), "qwen");
        assert_eq!(ModelName::from_path("/data/other/qwen"), "qwen");
        assert_eq!(ModelName::from_path("/models"), "models");
        assert_eq!(ModelName::from_path("   "), "");
    }
}
