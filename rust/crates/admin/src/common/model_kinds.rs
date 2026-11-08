//! What a cell's router output says of the model behind it, as the file may keep it the proxy does not read.

use super::model_jobs::ModelJobs;
use rules::{Coerce, MediaParts};
use serde_json::{Map, Value, json};

/// The facts.
pub struct ModelFacts;

impl ModelFacts {
    /// The board's copy is the vocabulary itself, not a list of the same words: what the board accepts for a cell is what
    /// the entry decides a request against, and the second list is where a word gets added to one side only.
    const INPUTS: [&'static str; 3] = MediaParts::WORDS;

    fn whole_size(value: Option<&Value>) -> Option<&Value> {
        value.filter(|value| value.as_i64().is_some_and(|size| size > 0))
    }

    /// From the board's reading of the cell.
    pub fn cell_facts(server: &Value) -> Map<String, Value> {
        let config = server.get("slotConfig").filter(|config| config.is_object());
        let meta = server.get("cellMeta").filter(|meta| meta.is_object());
        let mut facts = Map::new();
        let jobs = ModelJobs::cell_jobs(&ModelJobs::cell_runner_id(config), meta, config);
        if !jobs.is_empty() {
            facts.insert("jobs".to_string(), json!(jobs));
        }
        if jobs == ["llm"] {
            let said = server.get("modalities").filter(|said| said.is_object());
            let yes = |key: &str| Coerce::truthy(said.and_then(|said| said.get(key)));
            let mut inputs = vec!["text"];
            if yes("vision") {
                inputs.push("image");
            }
            if yes("audio") {
                inputs.push("audio");
            }
            facts.insert("inputs".to_string(), json!(inputs));
        }
        if let Some(languages) =
            meta.and_then(|meta| meta.get("langs")).and_then(Value::as_array).filter(|languages| !languages.is_empty())
        {
            let words: Vec<String> =
                languages.iter().map(|word| Coerce::str_of(Some(word))).filter(|word| !Coerce::strip(word).is_empty()).collect();
            facts.insert("languages".to_string(), json!(words));
        }
        if let Some(size) = Self::whole_size(meta.and_then(|meta| meta.get("maxAudioMs"))) {
            facts.insert("maxAudioMs".to_string(), size.clone());
        }
        if let Some(size) = Self::whole_size(server.get("ctxServed")) {
            facts.insert("contextLength".to_string(), size.clone());
        }
        facts
    }

    /// A router output's facts as the file may keep them.
    pub fn clean_facts(raw: &Value) -> Map<String, Value> {
        let words = |key: &str| -> Vec<&str> {
            raw.get(key).and_then(Value::as_array).into_iter().flatten().filter_map(Value::as_str).collect()
        };
        let mut facts = Map::new();
        let said = words("jobs");
        let jobs: Vec<&str> = ModelJobs::JOBS.iter().copied().filter(|job| said.contains(job)).collect();
        if !jobs.is_empty() {
            facts.insert("jobs".to_string(), json!(jobs));
        }
        let said = words("inputs");
        let inputs: Vec<&str> = Self::INPUTS.iter().copied().filter(|input| said.contains(input)).collect();
        if !inputs.is_empty() {
            facts.insert("inputs".to_string(), json!(inputs));
        }
        let languages: Vec<&str> = words("languages")
            .into_iter()
            .map(Coerce::strip)
            .filter(|word| !word.is_empty())
            .map(|word| Coerce::first_letters(word, 32))
            .take(400)
            .collect();
        if !languages.is_empty() {
            facts.insert("languages".to_string(), json!(languages));
        }
        for key in ["maxAudioMs", "contextLength"] {
            if let Some(size) = Self::whole_size(raw.get(key)) {
                facts.insert(key.to_string(), size.clone());
            }
        }
        facts
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_cell_says_what_it_does() {
        let facts = ModelFacts::cell_facts(
            &json!({"slotConfig": {"RUNNER": "vllm"}, "modalities": {"vision": true}, "ctxServed": 100, "cellMeta": {"langs": ["en", " "], "maxAudioMs": 5}}),
        );
        assert_eq!(
            Value::Object(facts),
            json!({"jobs": ["llm"], "inputs": ["text", "image"], "languages": ["en"], "maxAudioMs": 5, "contextLength": 100})
        );
    }

    #[test]
    fn a_file_keeps_only_what_reads() {
        let facts = ModelFacts::clean_facts(
            &json!({"jobs": ["tts", "llm", "x", 1], "inputs": ["audio", "text"], "languages": [" en ", 5, ""], "maxAudioMs": "9", "contextLength": 5}),
        );
        assert_eq!(
            Value::Object(facts),
            json!({"jobs": ["llm", "tts"], "inputs": ["text", "audio"], "languages": ["en"], "contextLength": 5})
        );
    }
}
