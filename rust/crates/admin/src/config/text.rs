//! The launch-config contract: the config block of a start script, as text.

use super::fields::ConfigFields;
use crate::domain::runner::{Config, RunnerRegistry};
use rules::{AppError, Coerce};
use serde_json::{Value, json};

/// The block.
pub struct ConfigText;

impl ConfigText {
    /// Where a block begins.
    pub const BEGIN: &'static str = "# BEGIN LLAMA CONFIG";
    /// Where it ends.
    pub const END: &'static str = "# END LLAMA CONFIG";

    const NUMERIC: [&'static str; 22] = [
        "CTX_SIZE",
        "THREADS",
        "THREADS_BATCH",
        "BATCH_SIZE",
        "UBATCH_SIZE",
        "PARALLEL",
        "N_PREDICT",
        "KEEP",
        "POLL",
        "MAIN_GPU",
        "FIT_CTX",
        "TIMEOUT",
        "THREADS_HTTP",
        "CACHE_REUSE",
        "CACHE_RAM",
        "SLEEP_IDLE_SECONDS",
        "IMAGE_MIN_TOKENS",
        "IMAGE_MAX_TOKENS",
        "REASONING_BUDGET",
        "SPEC_DRAFT_N_GPU_LAYERS",
        "SPEC_DRAFT_N_MAX",
        "SPEC_DRAFT_N_MIN",
    ];

    /// The groups a block is written in, a blank line between them.
    const GROUPS: [&'static [&'static str]; 11] = [
        &["HOST", "PORT"],
        &["LLAMA_MODELS_DIR", "MODEL_FILE", "MMPROJ_FILE"],
        &[
            "SPEC_TYPE",
            "SPEC_DRAFT_MODEL_FILE",
            "SPEC_DRAFT_N_GPU_LAYERS",
            "SPEC_DRAFT_N_MAX",
            "SPEC_DRAFT_N_MIN",
            "SPEC_DRAFT_CACHE_TYPE_K",
            "SPEC_DRAFT_CACHE_TYPE_V",
        ],
        &[
            "CTX_SIZE",
            "THREADS",
            "THREADS_BATCH",
            "BATCH_SIZE",
            "UBATCH_SIZE",
            "PARALLEL",
            "N_GPU_LAYERS",
            "CACHE_TYPE_K",
            "CACHE_TYPE_V",
        ],
        &[
            "N_PREDICT",
            "KEEP",
            "CPU_RANGE",
            "CPU_STRICT",
            "POLL",
            "ROPE_SCALING",
            "ROPE_SCALE",
            "ROPE_FREQ_BASE",
            "ROPE_FREQ_SCALE",
        ],
        &[
            "KV_OFFLOAD",
            "MMAP",
            "CONTEXT_SHIFT",
            "KV_UNIFIED",
            "NUMA",
            "DEVICE",
            "SPLIT_MODE",
            "TENSOR_SPLIT",
            "MAIN_GPU",
            "FIT",
            "FIT_TARGET",
            "FIT_CTX",
        ],
        &[
            "ALIAS",
            "API_PREFIX",
            "TIMEOUT",
            "THREADS_HTTP",
            "CACHE_PROMPT",
            "CACHE_REUSE",
            "CACHE_RAM",
            "CACHE_IDLE_SLOTS",
            "SLEEP_IDLE_SECONDS",
            "API_KEY",
            "SSL_CERT_FILE",
            "SSL_KEY_FILE",
            "ENABLE_PROPS",
            "ENABLE_SLOTS",
        ],
        &[
            "IMAGE_MIN_TOKENS",
            "IMAGE_MAX_TOKENS",
            "REASONING",
            "REASONING_FORMAT",
            "REASONING_BUDGET",
            "REASONING_PRESERVE",
            "CHAT_TEMPLATE",
            "CHAT_TEMPLATE_FILE",
            "CHAT_TEMPLATE_KWARGS",
            "SKIP_CHAT_PARSING",
        ],
        &[
            "ENABLE_JINJA",
            "ENABLE_THINKING",
            "ENABLE_FLASH_ATTN",
            "ENABLE_MLOCK",
            "ENABLE_METRICS",
            "ENABLE_CONT_BATCHING",
            "ENABLE_WEBUI",
            "OFFLOAD_MMPROJ",
        ],
        &["ENABLE_EMBEDDINGS", "POOLING", "EMBD_NORMALIZE"],
        &["ENABLE_TOOLS", "ENABLE_AGENT", "ENABLE_MCP_PROXY", "EXTRA_ARGS"],
    ];

    /// N_GPU_LAYERS as a NUMBER, for the places that need one.
    pub fn gpu_layers_int(value: Option<&Value>, default: i64) -> i64 {
        let text =
            if value.is_none_or(Value::is_null) { String::new() } else { Coerce::strip(&Coerce::str_of(value)).to_lowercase() };
        if text.is_empty() || matches!(text.as_str(), "auto" | "all" | "max") {
            return default;
        }
        text.parse().unwrap_or(default)
    }

    /// (before, the block, after).
    pub fn split<'text>(text: &'text str, source: &str) -> Result<(&'text str, &'text str, &'text str), AppError> {
        let missing = || AppError::with_status(format!("Config markers not found in {source}"), 500);
        let begin = text.find(Self::BEGIN).ok_or_else(missing)?;
        let end = text.find(Self::END).filter(|end| *end > begin).ok_or_else(missing)?;
        let line_end = text.get(end..).and_then(|tail| tail.find('\n')).map_or(text.len(), |at| end + at + 1);
        match (text.get(..begin), text.get(begin..line_end), text.get(line_end..)) {
            (Some(before), Some(block), Some(after)) => Ok((before, block, after)),
            _ => Err(missing()),
        }
    }

    /// A value of a block's line, its quotes gone.
    pub fn parse_value(raw: &str) -> String {
        let raw = Coerce::strip(raw);
        let quoted =
            raw.len() >= 2 && ((raw.starts_with('"') && raw.ends_with('"')) || (raw.starts_with('\'') && raw.ends_with('\'')));
        // Python takes `raw[1:-1]` of a lone quote too: nothing.
        if raw.len() == 1 && (raw == "\"" || raw == "'") {
            return String::new();
        }
        // absent-ok: the quotes were just seen on both sides.
        if quoted { raw.get(1..raw.len() - 1).unwrap_or_default().to_string() } else { raw.to_string() }
    }

    /// The config of a text: every field there, those not said empty, the models folder at least the default.
    pub fn parse(text: &str, source: &str, default_models_dir: &str) -> Result<Config, AppError> {
        let (_, block, _) =
            Self::split(text, source).map_err(|_| AppError::new(format!("Config markers not found in {source}")))?;
        let mut config = Config::new();
        for line in block.lines() {
            let line = Coerce::strip(line);
            if line.is_empty() || line.starts_with('#') {
                continue;
            }
            let Some((key, value)) = line.split_once('=') else {
                continue;
            };
            let key = Coerce::strip(key);
            if ConfigFields::holds(key) {
                config.insert(key.to_string(), json!(Self::parse_value(value)));
            }
        }
        for key in ConfigFields::ALL {
            config.entry(key.to_string()).or_insert_with(|| json!(""));
        }
        if !Coerce::truthy(config.get("LLAMA_MODELS_DIR")) {
            config.insert("LLAMA_MODELS_DIR".to_string(), json!(default_models_dir));
        }
        Ok(config)
    }

    /// A value in the double quotes of a block's line.
    pub fn quote_shell_value(value: &str) -> String {
        format!("\"{}\"", value.replace('\\', "\\\\").replace('"', "\\\"").replace('$', "\\$"))
    }

    /// `{key: str(config.get(key, "")).strip()}`: every field, as text.
    pub fn merged(config: &Config) -> Config {
        ConfigFields::ALL
            .iter()
            .map(|key| ((*key).to_string(), json!(Coerce::strip(&Coerce::str_of(config.get(*key))))))
            .collect()
    }

    fn is_int(text: &str) -> bool {
        let digits = text.strip_prefix('-').unwrap_or(text);
        !digits.is_empty() && digits.chars().all(|letter| letter.is_ascii_digit())
    }

    /// The block of a config: its fields checked, in their groups.
    pub fn build_block(config: &Config, runners: &RunnerRegistry) -> Result<String, AppError> {
        let merged = Self::merged(config);
        // absent-ok: a field the merged config does not hold is empty.
        let word = |key: &str| merged.get(key).and_then(Value::as_str).unwrap_or_default();
        if word("MODEL_FILE").is_empty() {
            return Err(AppError::new("MODEL_FILE is required"));
        }
        if word("PORT").is_empty() || !word("PORT").chars().all(|letter| letter.is_ascii_digit()) {
            return Err(AppError::new("PORT must be a number"));
        }
        for key in Self::NUMERIC {
            if !word(key).is_empty() && !Self::is_int(word(key)) {
                return Err(AppError::new(format!("{key} must be a number")));
            }
        }
        let target = word("FIT_TARGET");
        if !target.is_empty()
            && !target.split(',').all(|part| !part.is_empty() && part.chars().all(|letter| letter.is_ascii_digit()))
        {
            return Err(AppError::new("FIT_TARGET must be a number or comma-separated numbers"));
        }
        let mut lines = vec![Self::BEGIN.to_string()];
        let runner = runners.for_config(&merged);
        if !word("RUNNER").is_empty() && runner.row().llama_config && runner.row().id != "llama-server" {
            lines.push(format!("RUNNER={}", Self::quote_shell_value(word("RUNNER"))));
        }
        let listed: Vec<&str> = Self::GROUPS.iter().flat_map(|group| group.iter().copied()).collect();
        let rest: Vec<&str> = ConfigFields::llama().iter().copied().filter(|key| !listed.contains(key)).collect();
        for (index, group) in Self::GROUPS.iter().copied().chain((!rest.is_empty()).then_some(rest.as_slice())).enumerate() {
            if index > 0 {
                lines.push(String::new());
            }
            lines.extend(group.iter().map(|key| format!("{key}={}", Self::quote_shell_value(word(key)))));
        }
        lines.push(Self::END.to_string());
        Ok(lines.join("\n") + "\n")
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_block_reads_back() {
        let text = "#!/bin/bash\n# BEGIN LLAMA CONFIG\nPORT=\"8080\"\nMODEL_FILE='a b.gguf'\n# comment\nNOPE=\"x\"\n# END LLAMA CONFIG\nrest\n";
        let (before, block, after) = ConfigText::split(text, "x").unwrap();
        assert_eq!(before, "#!/bin/bash\n");
        assert!(block.ends_with("# END LLAMA CONFIG\n"));
        assert_eq!(after, "rest\n");
        let config = ConfigText::parse(text, "x", "/models").unwrap();
        assert_eq!(config.get("PORT"), Some(&json!("8080")));
        assert_eq!(config.get("MODEL_FILE"), Some(&json!("a b.gguf")));
        assert_eq!(config.get("LLAMA_MODELS_DIR"), Some(&json!("/models")));
        assert_eq!(config.get("CTX_SIZE"), Some(&json!("")));
        assert!(config.get("NOPE").is_none());
        assert_eq!(ConfigText::parse("x", "the file", "/m").unwrap_err().message, "Config markers not found in the file");
    }

    #[test]
    fn what_a_shell_would_read_otherwise_is_escaped() {
        assert_eq!(ConfigText::quote_shell_value("a\"b$c\\"), "\"a\\\"b\\$c\\\\\"");
        assert_eq!(ConfigText::gpu_layers_int(Some(&json!("auto")), 999), 999);
        assert_eq!(ConfigText::gpu_layers_int(Some(&json!(" 12 ")), 999), 12);
        assert_eq!(ConfigText::gpu_layers_int(Some(&json!("x")), 7), 7);
        assert_eq!(ConfigText::gpu_layers_int(None, 7), 7);
    }
}
