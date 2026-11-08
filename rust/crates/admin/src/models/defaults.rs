//! What a model's maker states as its own numbers, held as a table the guard can read.
//!
//! `modelParams` is prose for a person: 28 of the 59 cards name a value twice — once for the mode with
//! reasoning, once without — so a value read out of prose is a choice, not a fact. This table keeps only what a
//! card states once, and `contract/model_defaults.json` keeps the sentence each value came from: the guard
//! `scripts/check_model_defaults.py` reads every number back out of its own sentence and refuses a sentence that
//! names a mode or a use — "для текста" states its numbers for text, so it is not a fact for the cell. So the values
//! here and the rows there are one fact in two halves, held to each other.
//!
//! Only fields a cell can actually say are in the table. The caravan writes no flag for a penalty, so a penalty
//! cannot be a row; and the port, the key, a path and a runner are the cell's facts, not the model's, so they are
//! not here either.

use serde_json::{Map, Value, json};

/// The numbers each maker states once, by the model's folder.
pub struct ModelDefaults;

impl ModelDefaults {
    /// Model folder, and its values as the cell's config keeps them, in the order `contract/model_defaults.json` lists them.
    const TABLE: [(&'static str, &[(&'static str, &'static str)]); 12] = [
        ("DeepSeek-V4.1-Flash-1017-GSQ-RCO-GGUF", &[("TEMPERATURE", "1.0"), ("TOP_P", "1.0")]),
        ("Hermes-4-70B-GGUF", &[("TEMPERATURE", "0.6"), ("TOP_P", "0.95"), ("TOP_K", "20")]),
        ("Hermes-4-70B-heretic-i1-GGUF", &[("TEMPERATURE", "0.6"), ("TOP_P", "0.95"), ("TOP_K", "20")]),
        ("North-Mini-Code-1.0-GGUF", &[("TEMPERATURE", "1.0"), ("TOP_P", "0.95")]),
        ("PhoneLLM-alpha-1-Q4_K_M", &[("TEMPERATURE", "0")]),
        ("Muse-Glimmer-30B-GGUF", &[("TEMPERATURE", "1.0"), ("TOP_P", "0.95"), ("TOP_K", "64")]),
        ("Qwen3-Coder-Next-GGUF", &[("TEMPERATURE", "1.0"), ("TOP_P", "0.95"), ("TOP_K", "40"), ("MIN_P", "0.01")]),
        (
            "Swift-1.5-Qwen3.8-Flash-Next-GSQ-RCO-GGUF",
            &[("TEMPERATURE", "1.0"), ("TOP_P", "0.95"), ("TOP_K", "20"), ("MIN_P", "0.0")],
        ),
        ("gemma-4-12B-it-GGUF", &[("TEMPERATURE", "1.0"), ("TOP_P", "0.95"), ("TOP_K", "64")]),
        ("gemma-4-31B-it-GGUF", &[("TEMPERATURE", "1.0"), ("TOP_P", "0.95"), ("TOP_K", "64")]),
        ("gemma-4-E4B-it-GGUF", &[("TEMPERATURE", "1.0"), ("TOP_P", "0.95"), ("TOP_K", "64")]),
        ("google_gemma-4-31B-it-GGUF", &[("TEMPERATURE", "1.0"), ("TOP_P", "0.95"), ("TOP_K", "64")]),
    ];

    /// The fields this table has the right to hold: sampling and the window. `scripts/check_field_homes.py` holds
    /// every field to one group, and `scripts/check_llama_flags.py` to a flag the checked build knows.
    pub const FIELDS: [&'static str; 6] = ["TEMPERATURE", "TOP_P", "TOP_K", "MIN_P", "CTX_SIZE", "N_PREDICT"];

    /// The values of `model`, as a cell's config keeps them; nothing for a folder the table does not name. What the retirement of
    /// the default cells holds a slot to: a slot that holds no more than this was what the preset gives back.
    pub fn values(model: &str) -> Map<String, Value> {
        Self::TABLE
            .iter()
            .filter(|(folder, _)| *folder == model)
            .flat_map(|(_, fields)| fields.iter())
            .map(|(field, value)| (field.to_string(), json!(value)))
            .collect()
    }

    /// The whole table, as the page reads it: by folder, the values the maker stated once. The machine's page says them on the model
    /// picked (`defaults` of the model texts), and the launch builder offers them as the model's own set (`makers` of its sets).
    pub fn answer() -> Value {
        let mut out = Map::new();
        for (folder, fields) in Self::TABLE {
            let row = out.entry(folder.to_string()).or_insert_with(|| Value::Object(Map::new()));
            for (field, value) in fields {
                if let Some(fields) = row.as_object_mut() {
                    fields.insert(field.to_string(), json!(value));
                }
            }
        }
        Value::Object(out)
    }

    /// The rows, flat: folder, field, value. What the guard and `rust/crates/admin/tests/contract.rs` hold to
    /// `contract/model_defaults.json`.
    pub fn rows() -> Vec<(String, String, String)> {
        let mut out = Vec::new();
        for (folder, fields) in Self::TABLE {
            for (field, value) in fields {
                out.push((folder.to_string(), field.to_string(), value.to_string()));
            }
        }
        out
    }
}
