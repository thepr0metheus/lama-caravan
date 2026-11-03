//! Every llama-server flag this builder understands, and the field it belongs to: what splits a raw EXTRA_ARGS into form fields and leftovers.

use super::args::LlamaArgs;
use super::shell::ShellSplit;
use rules::ShellWord;
use serde_json::{Map, Value, json};
use std::collections::BTreeMap;

/// The tables.
pub struct ExtraFlags;

impl ExtraFlags {
    const VALUE_FLAGS: [(&'static str, &'static str); 79] = [
        ("--ctx-size", "CTX_SIZE"),
        ("-c", "CTX_SIZE"),
        ("--threads", "THREADS"),
        ("-t", "THREADS"),
        ("--threads-batch", "THREADS_BATCH"),
        ("-tb", "THREADS_BATCH"),
        ("--batch-size", "BATCH_SIZE"),
        ("-b", "BATCH_SIZE"),
        ("--ubatch-size", "UBATCH_SIZE"),
        ("-ub", "UBATCH_SIZE"),
        ("--parallel", "PARALLEL"),
        ("-np", "PARALLEL"),
        ("--n-gpu-layers", "N_GPU_LAYERS"),
        ("-ngl", "N_GPU_LAYERS"),
        ("--gpu-layers", "N_GPU_LAYERS"),
        ("--cache-type-k", "CACHE_TYPE_K"),
        ("-ctk", "CACHE_TYPE_K"),
        ("--cache-type-v", "CACHE_TYPE_V"),
        ("-ctv", "CACHE_TYPE_V"),
        ("--predict", "N_PREDICT"),
        ("-n", "N_PREDICT"),
        ("--n-predict", "N_PREDICT"),
        ("--keep", "KEEP"),
        ("--cpu-range", "CPU_RANGE"),
        ("--poll", "POLL"),
        ("--rope-scaling", "ROPE_SCALING"),
        ("--rope-scale", "ROPE_SCALE"),
        ("--rope-freq-base", "ROPE_FREQ_BASE"),
        ("--rope-freq-scale", "ROPE_FREQ_SCALE"),
        ("--numa", "NUMA"),
        ("--device", "DEVICE"),
        ("-dev", "DEVICE"),
        ("--split-mode", "SPLIT_MODE"),
        ("-sm", "SPLIT_MODE"),
        ("--tensor-split", "TENSOR_SPLIT"),
        ("-ts", "TENSOR_SPLIT"),
        ("--main-gpu", "MAIN_GPU"),
        ("-mg", "MAIN_GPU"),
        ("--fit-target", "FIT_TARGET"),
        ("--fit-ctx", "FIT_CTX"),
        ("--alias", "ALIAS"),
        ("-a", "ALIAS"),
        ("--api-prefix", "API_PREFIX"),
        ("--timeout", "TIMEOUT"),
        ("--threads-http", "THREADS_HTTP"),
        ("--cache-reuse", "CACHE_REUSE"),
        ("--cache-ram", "CACHE_RAM"),
        ("-cram", "CACHE_RAM"),
        ("--sleep-idle-seconds", "SLEEP_IDLE_SECONDS"),
        ("--api-key", "API_KEY"),
        ("--ssl-cert-file", "SSL_CERT_FILE"),
        ("--ssl-key-file", "SSL_KEY_FILE"),
        ("--image-min-tokens", "IMAGE_MIN_TOKENS"),
        ("--image-max-tokens", "IMAGE_MAX_TOKENS"),
        ("--reasoning", "REASONING"),
        ("--reasoning-format", "REASONING_FORMAT"),
        ("--reasoning-budget", "REASONING_BUDGET"),
        ("--chat-template", "CHAT_TEMPLATE"),
        ("--chat-template-kwargs", "CHAT_TEMPLATE_KWARGS"),
        ("--pooling", "POOLING"),
        ("--embd-normalize", "EMBD_NORMALIZE"),
        ("--host", "HOST"),
        ("--port", "PORT"),
        ("--checkpoint-min-step", "CHECKPOINT_MIN_STEP"),
        ("-cms", "CHECKPOINT_MIN_STEP"),
        ("--slot-prompt-similarity", "SLOT_PROMPT_SIMILARITY"),
        ("-sps", "SLOT_PROMPT_SIMILARITY"),
        ("--slot-save-path", "SLOT_SAVE_PATH"),
        ("--sse-ping-interval", "SSE_PING_INTERVAL"),
        ("--prio", "PRIO"),
        ("--yarn-orig-ctx", "YARN_ORIG_CTX"),
        ("--yarn-ext-factor", "YARN_EXT_FACTOR"),
        ("--yarn-attn-factor", "YARN_ATTN_FACTOR"),
        ("--yarn-beta-fast", "YARN_BETA_FAST"),
        ("--yarn-beta-slow", "YARN_BETA_SLOW"),
        ("--spec-draft-p-split", "SPEC_DRAFT_P_SPLIT"),
        ("--draft-p-split", "SPEC_DRAFT_P_SPLIT"),
        ("--cors-methods", "CORS_METHODS"),
        ("--cors-headers", "CORS_HEADERS"),
    ];
    /// Those of `VALUE_FLAGS` that came only from the builder's own pairs: they are no flags of a raw EXTRA_ARGS.
    const NOT_IN_EXTRA: [&'static str; 4] = ["--temp", "--top-k", "--top-p", "--min-p"];
    const ON_OFF_FLAGS: [(&'static str, &'static str); 4] =
        [("--flash-attn", "ENABLE_FLASH_ATTN"), ("-fa", "ENABLE_FLASH_ATTN"), ("--fit", "FIT"), ("--cpu-strict", "CPU_STRICT")];
    const PAIR_BOOL: [(&'static str, &'static str, &'static str); 31] = [
        ("--mmap", "MMAP", "1"),
        ("--no-mmap", "MMAP", "0"),
        ("--kv-offload", "KV_OFFLOAD", "1"),
        ("--no-kv-offload", "KV_OFFLOAD", "0"),
        ("--cache-prompt", "CACHE_PROMPT", "1"),
        ("--no-cache-prompt", "CACHE_PROMPT", "0"),
        ("--slots", "ENABLE_SLOTS", "1"),
        ("--no-slots", "ENABLE_SLOTS", "0"),
        ("--skip-chat-parsing", "SKIP_CHAT_PARSING", "1"),
        ("--no-skip-chat-parsing", "SKIP_CHAT_PARSING", "0"),
        ("--reasoning-preserve", "REASONING_PRESERVE", "1"),
        ("--no-reasoning-preserve", "REASONING_PRESERVE", "0"),
        ("--context-shift", "CONTEXT_SHIFT", "1"),
        ("--no-context-shift", "CONTEXT_SHIFT", "0"),
        ("--kv-unified", "KV_UNIFIED", "1"),
        ("--no-kv-unified", "KV_UNIFIED", "0"),
        ("--cache-idle-slots", "CACHE_IDLE_SLOTS", "1"),
        ("--no-cache-idle-slots", "CACHE_IDLE_SLOTS", "0"),
        ("--mmproj-auto", "MMPROJ_AUTO", "1"),
        ("--no-mmproj-auto", "MMPROJ_AUTO", "0"),
        ("--mmproj-offload", "OFFLOAD_MMPROJ", "1"),
        ("--no-mmproj-offload", "OFFLOAD_MMPROJ", "0"),
        ("--cont-batching", "ENABLE_CONT_BATCHING", "1"),
        ("-cb", "ENABLE_CONT_BATCHING", "1"),
        ("--no-cont-batching", "ENABLE_CONT_BATCHING", "0"),
        ("--webui", "ENABLE_WEBUI", "1"),
        ("--no-webui", "ENABLE_WEBUI", "0"),
        ("--no-jinja", "ENABLE_JINJA", "0"),
        ("--op-offload", "OP_OFFLOAD", "1"),
        ("--no-op-offload", "OP_OFFLOAD", "0"),
        ("--repack", "REPACK", "1"),
    ];
    const PAIR_BOOL_MORE: [(&'static str, &'static str, &'static str); 4] =
        [("--no-repack", "REPACK", "0"), ("-nr", "REPACK", "0"), ("--warmup", "WARMUP", "1"), ("--no-warmup", "WARMUP", "0")];
    const FLAG_ON: [(&'static str, &'static str); 13] = [
        ("--props", "ENABLE_PROPS"),
        ("--metrics", "ENABLE_METRICS"),
        ("--mlock", "ENABLE_MLOCK"),
        ("--embeddings", "ENABLE_EMBEDDINGS"),
        ("--embedding", "ENABLE_EMBEDDINGS"),
        ("--jinja", "ENABLE_JINJA"),
        ("--agent", "ENABLE_AGENT"),
        ("--ui-mcp-proxy", "ENABLE_MCP_PROXY"),
        ("--cpu-moe", "CPU_MOE"),
        ("-cmoe", "CPU_MOE"),
        ("--check-tensors", "CHECK_TENSORS"),
        ("--spec-draft-cpu-moe", "CPU_MOE_DRAFT"),
        ("--cpu-moe-draft", "CPU_MOE_DRAFT"),
    ];
    const ON_WORDS: [&'static str; 6] = ["on", "auto", "1", "true", "yes", "enabled"];
    const OFF_WORDS: [&'static str; 5] = ["off", "0", "false", "no", "disabled"];

    fn pair_bools() -> impl Iterator<Item = &'static (&'static str, &'static str, &'static str)> {
        Self::PAIR_BOOL.iter().chain(Self::PAIR_BOOL_MORE.iter())
    }

    /// Every flag this builder understands, with the field it belongs to.
    pub fn flag_to_field() -> BTreeMap<&'static str, &'static str> {
        let mut out: BTreeMap<&'static str, &'static str> = LlamaArgs::PAIRS.iter().copied().collect();
        out.extend(Self::VALUE_FLAGS.iter().copied());
        out.extend(Self::ON_OFF_FLAGS.iter().copied());
        out.extend(Self::pair_bools().map(|(flag, field, _)| (*flag, *field)));
        out.extend(Self::FLAG_ON.iter().copied());
        out.insert("-cmoed", "CPU_MOE_DRAFT");
        out
    }

    /// The same in the order the tables say them; a flag said again keeps its first place. The board shows the fields in this order.
    pub fn flags_in_order() -> Vec<(&'static str, &'static str)> {
        let table = Self::flag_to_field();
        let mut seen = std::collections::BTreeSet::new();
        let said = LlamaArgs::PAIRS
            .iter()
            .chain(Self::VALUE_FLAGS.iter())
            .chain(Self::ON_OFF_FLAGS.iter())
            .map(|(flag, _)| *flag)
            .chain(Self::pair_bools().map(|(flag, _, _)| *flag))
            .chain(Self::FLAG_ON.iter().map(|(flag, _)| *flag))
            .chain(std::iter::once("-cmoed"));
        said.filter(|flag| seen.insert(*flag)).filter_map(|flag| table.get(flag).map(|field| (flag, *field))).collect()
    }

    fn field_of(table: &[(&'static str, &'static str)], token: &str) -> Option<&'static str> {
        table.iter().find(|(flag, _)| *flag == token).map(|(_, field)| *field)
    }

    /// Splits a raw EXTRA_ARGS into recognized form fields and leftover flags.
    pub fn parse(text: &str) -> Value {
        let tokens = ShellSplit::words(text);
        let (mut recognized, mut remaining) = (Map::new(), Vec::new());
        let mut at = 0;
        while let Some(token) = tokens.get(at) {
            let next = tokens.get(at + 1);
            let token = token.as_str();
            if !Self::NOT_IN_EXTRA.contains(&token)
                && let Some(field) = Self::field_of(&Self::VALUE_FLAGS, token)
                && let Some(value) = next.filter(|value| !value.starts_with('-'))
            {
                recognized.insert(field.to_string(), json!(value));
                at += 2;
            } else if let Some(field) = Self::field_of(&Self::ON_OFF_FLAGS, token) {
                let word = next.map(|value| value.to_lowercase());
                let on = word.as_deref().is_some_and(|word| Self::ON_WORDS.contains(&word));
                let off = word.as_deref().is_some_and(|word| Self::OFF_WORDS.contains(&word));
                recognized.insert(field.to_string(), json!(if off { "0" } else { "1" }));
                at += if on || off { 2 } else { 1 };
            } else if let Some((_, field, value)) = Self::pair_bools().find(|(flag, _, _)| *flag == token) {
                recognized.insert((*field).to_string(), json!(value));
                at += 1;
            } else if let Some(field) =
                Self::field_of(&Self::FLAG_ON, token).or(if token == "-cmoed" { Some("CPU_MOE_DRAFT") } else { None })
            {
                recognized.insert(field.to_string(), json!("1"));
                at += 1;
            } else if token == "--tools" && next.is_some_and(|value| value == "all") {
                recognized.insert("ENABLE_TOOLS".to_string(), json!("1"));
                at += 2;
            } else {
                remaining.push(if token.contains([' ', '"', '\'']) { ShellWord::quote(token) } else { token.to_string() });
                at += 1;
            }
        }
        json!({"recognized": recognized, "remaining": remaining.join(" ")})
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_raw_line_comes_apart() {
        let said = ExtraFlags::parse("-c 4096 --fit off --no-mmap --metrics --tools all --other 'a b' -t -5 --flash-attn");
        assert_eq!(
            said.get("recognized").unwrap(),
            &json!({"CTX_SIZE": "4096", "FIT": "0", "MMAP": "0", "ENABLE_METRICS": "1", "ENABLE_TOOLS": "1", "ENABLE_FLASH_ATTN": "1"})
        );
        assert_eq!(said.get("remaining").unwrap(), &json!("--other 'a b' -t -5"));
    }

    #[test]
    fn every_flag_has_its_field() {
        let map = ExtraFlags::flag_to_field();
        assert_eq!(map.get("-ngl"), Some(&"N_GPU_LAYERS"));
        assert_eq!(map.get("--no-repack"), Some(&"REPACK"));
        assert_eq!(map.get("-cmoed"), Some(&"CPU_MOE_DRAFT"));
        assert_eq!(map.get("--ctx-size"), Some(&"CTX_SIZE"));
    }
}
