//! The full llama-server argument list, everything AFTER the binary, from a cell's config.

use super::draft_file::DraftFileWord;
use super::shell::ShellSplit;
use rules::{AskedWindow, CellDoor, Coerce, CudaCards, Flag, PythonJson};
use serde_json::{Map, Value, json};

mod switches;

/// What a GGUF's header says, where this controller reads it: `contextLength` and `architecture`; empty for a file it does not read.
pub trait ModelHeaders {
    /// The header of a cell's model at `model_path`.
    fn model_header(&self, config: &Map<String, Value>, model_path: &str) -> Value;
}

/// The paths a command is built with.
#[derive(Debug, Clone, Default)]
pub struct ArgPaths<'paths> {
    /// The model's file, or its placeholder.
    pub model: &'paths str,
    /// The projector's.
    pub mmproj: &'paths str,
    /// The draft's.
    pub spec: &'paths str,
    /// Whether this host's own paths may appear.
    pub local_paths: bool,
    /// Whether the model is read over the network: no mapping then.
    pub over_network: bool,
    /// Where the header can be read, when `model` is a placeholder.
    pub header_path: &'paths str,
    /// The port, or its placeholder: a cell holds no port of its own, the scout leases one at the start and fills `{{PORT}}`
    /// (Papyrus `caravan-scout-port-lease`). Empty: the config's own `PORT` when it has one, else the placeholder.
    pub port: &'paths str,
}

/// The builder.
pub struct LlamaArgs<'config> {
    config: &'config Map<String, Value>,
    headers: &'config dyn ModelHeaders,
    args: Vec<String>,
}

impl<'config> LlamaArgs<'config> {
    /// What a start's port is called before the scout leases one: the scout fills it, as it fills `{{MODEL_PATH}}`.
    pub const LEASED_PORT: &'static str = "{{PORT}}";
    /// The flags the caravan writes itself, which an operator's EXTRA_ARGS does not say again: where a cell listens.
    const CARAVANS_OWN: [&'static str; 2] = ["--host", "--port"];

    /// Flags with a value, each of a field.
    pub const PAIRS: [(&'static str, &'static str); 65] = [
        ("--ctx-size", "CTX_SIZE"),
        ("--threads", "THREADS"),
        ("--threads-batch", "THREADS_BATCH"),
        ("--batch-size", "BATCH_SIZE"),
        ("--ubatch-size", "UBATCH_SIZE"),
        ("--parallel", "PARALLEL"),
        ("--n-gpu-layers", "N_GPU_LAYERS"),
        ("--cache-type-k", "CACHE_TYPE_K"),
        ("--cache-type-v", "CACHE_TYPE_V"),
        ("--predict", "N_PREDICT"),
        ("--keep", "KEEP"),
        ("--cpu-range", "CPU_RANGE"),
        ("--poll", "POLL"),
        ("--rope-scaling", "ROPE_SCALING"),
        ("--rope-scale", "ROPE_SCALE"),
        ("--rope-freq-base", "ROPE_FREQ_BASE"),
        ("--rope-freq-scale", "ROPE_FREQ_SCALE"),
        ("--numa", "NUMA"),
        ("--device", "DEVICE"),
        ("--split-mode", "SPLIT_MODE"),
        ("--tensor-split", "TENSOR_SPLIT"),
        ("--main-gpu", "MAIN_GPU"),
        ("--fit-target", "FIT_TARGET"),
        ("--fit-ctx", "FIT_CTX"),
        ("--alias", "ALIAS"),
        ("--api-prefix", "API_PREFIX"),
        ("--timeout", "TIMEOUT"),
        ("--threads-http", "THREADS_HTTP"),
        ("--cache-reuse", "CACHE_REUSE"),
        ("--cache-ram", "CACHE_RAM"),
        ("--sleep-idle-seconds", "SLEEP_IDLE_SECONDS"),
        ("--api-key", "API_KEY"),
        ("--image-min-tokens", "IMAGE_MIN_TOKENS"),
        ("--image-max-tokens", "IMAGE_MAX_TOKENS"),
        ("--temp", "TEMPERATURE"),
        ("--top-k", "TOP_K"),
        ("--top-p", "TOP_P"),
        ("--min-p", "MIN_P"),
        ("--reasoning", "REASONING"),
        ("--reasoning-format", "REASONING_FORMAT"),
        ("--reasoning-budget", "REASONING_BUDGET"),
        ("--chat-template", "CHAT_TEMPLATE"),
        ("--pooling", "POOLING"),
        ("--embd-normalize", "EMBD_NORMALIZE"),
        ("--n-cpu-moe", "N_CPU_MOE"),
        ("--spec-draft-p-min", "SPEC_DRAFT_P_MIN"),
        ("--mtmd-batch-max-tokens", "MTMD_BATCH_MAX_TOKENS"),
        ("--ctx-checkpoints", "CTX_CHECKPOINTS"),
        ("--log-verbosity", "LOG_VERBOSITY"),
        ("--cors-origins", "CORS_ORIGINS"),
        ("--tools-runtime", "TOOLS_RUNTIME"),
        ("--api-key-file", "API_KEY_FILE"),
        ("--checkpoint-min-step", "CHECKPOINT_MIN_STEP"),
        ("--slot-prompt-similarity", "SLOT_PROMPT_SIMILARITY"),
        ("--slot-save-path", "SLOT_SAVE_PATH"),
        ("--sse-ping-interval", "SSE_PING_INTERVAL"),
        ("--prio", "PRIO"),
        ("--yarn-orig-ctx", "YARN_ORIG_CTX"),
        ("--yarn-ext-factor", "YARN_EXT_FACTOR"),
        ("--yarn-attn-factor", "YARN_ATTN_FACTOR"),
        ("--yarn-beta-fast", "YARN_BETA_FAST"),
        ("--yarn-beta-slow", "YARN_BETA_SLOW"),
        ("--spec-draft-p-split", "SPEC_DRAFT_P_SPLIT"),
        ("--cors-methods", "CORS_METHODS"),
        ("--cors-headers", "CORS_HEADERS"),
    ];

    fn value(&self, key: &str) -> String {
        Coerce::str_of(self.config.get(key))
    }

    fn has(&self, key: &str) -> bool {
        self.config.get(key).is_some_and(|value| !value.is_null()) && !Coerce::strip(&self.value(key)).is_empty()
    }

    fn word(&self, key: &str) -> String {
        Coerce::stripped(self.config.get(key))
    }

    fn yes(&self, key: &str) -> bool {
        Flag::yes(self.config.get(key))
    }

    fn push(&mut self, words: &[&str]) {
        self.args.extend(words.iter().map(|word| (*word).to_string()));
    }

    fn add_bool(&mut self, key: &str, on: &str, off: &str) {
        if self.has(key) {
            let flag = if self.yes(key) { on } else { off };
            self.push(&[flag]);
        }
    }

    /// Whether a llama.cpp cell starts with its metrics: an unsaid box starts it with them.
    pub fn metrics_on(config: &Map<String, Value>) -> bool {
        let value = config.get("ENABLE_METRICS");
        value.is_none_or(|said| said.is_null() || Coerce::strip(&Coerce::str_of(Some(said))).is_empty()) || Flag::yes(value)
    }

    /// The same loading mode with the mapping taken out: what a model read over the network is loaded with.
    pub fn no_mmap_mode(load_mode: &str) -> String {
        match Coerce::strip(load_mode) {
            "mmap+mlock" => "mlock".to_string(),
            "mmap" => "none".to_string(),
            other => other.to_string(),
        }
    }

    /// The list.
    pub fn build(config: &'config Map<String, Value>, paths: &ArgPaths<'_>, headers: &'config dyn ModelHeaders) -> Vec<String> {
        let mut this = Self { config, headers, args: Vec::new() };
        // The address is the caravan's, not the cell's: on its machine's loopback, behind the scout (`rules::CellDoor`).
        let host = CellDoor::LISTEN;
        let port = if !paths.port.is_empty() {
            paths.port.to_string()
        } else if Coerce::truthy(config.get("PORT")) {
            Coerce::text(config.get("PORT"))
        } else {
            Self::LEASED_PORT.to_string()
        };
        this.push(&["--host", host, "--port", &port, "--model", paths.model]);
        let header_at = if paths.header_path.is_empty() { paths.model } else { paths.header_path };
        this.value_flags(header_at);
        this.chat_kwargs();
        this.local_files(paths);
        this.on_off_flags(paths.over_network);
        this.projector_and_embeddings(paths);
        this.last_switches();
        this.extra_args();
        let yarn = this.auto_yarn_args(header_at);
        this.args.extend(yarn);
        this.args
    }

    fn value_flags(&mut self, header_at: &str) {
        let cards = CudaCards::of(self.config);
        for (flag, key) in &Self::PAIRS {
            if *key == "CTX_SIZE" {
                let window = self.ctx_size_args(header_at);
                self.args.extend(window);
            } else if self.has(key) {
                let said = cards.flag_value(key, Coerce::strip(&self.value(key)));
                self.push(&[flag, &said]);
            }
        }
    }

    /// `--ctx-size`: the number the field says, and for a field left empty the window the model was trained for.
    fn ctx_size_args(&self, header_at: &str) -> Vec<String> {
        let raw = self.config.get("CTX_SIZE");
        let text = if raw.is_none_or(Value::is_null) { String::new() } else { Coerce::strip(&Coerce::str_of(raw)).to_string() };
        let trained = if AskedWindow::empty(&text) {
            self.headers.model_header(self.config, header_at).get("contextLength").and_then(Value::as_i64)
        } else {
            None
        };
        if let Some(window) = AskedWindow::of(&text, trained) {
            return vec!["--ctx-size".to_string(), window.to_string()];
        }
        if text.is_empty() { Vec::new() } else { vec!["--ctx-size".to_string(), text] }
    }

    fn chat_kwargs(&mut self) {
        let raw = self.word("CHAT_TEMPLATE_KWARGS");
        let think = self.word("ENABLE_THINKING").to_lowercase();
        let mut kwargs: Option<Map<String, Value>> = if raw.is_empty() {
            None
        } else {
            serde_json::from_str::<Value>(&raw).ok().and_then(|parsed| parsed.as_object().cloned())
        };
        if matches!(think.as_str(), "0" | "false" | "off" | "no" | "-1") {
            kwargs.get_or_insert_with(Map::new).insert("enable_thinking".to_string(), json!(false));
        } else if matches!(think.as_str(), "1" | "true" | "on" | "yes") {
            kwargs.get_or_insert_with(Map::new).insert("enable_thinking".to_string(), json!(true));
        }
        match kwargs {
            Some(kwargs) => {
                let written = PythonJson::compact_letters(&Value::Object(kwargs));
                self.push(&["--chat-template-kwargs", &written]);
            }
            None if !raw.is_empty() => self.push(&["--chat-template-kwargs", &raw]),
            None => {}
        }
    }

    fn local_files(&mut self, paths: &ArgPaths<'_>) {
        if !paths.local_paths {
            return;
        }
        for (key, flag) in [
            ("CHAT_TEMPLATE_FILE", "--chat-template-file"),
            ("SSL_CERT_FILE", "--ssl-cert-file"),
            ("SSL_KEY_FILE", "--ssl-key-file"),
        ] {
            if self.has(key) {
                let said = self.word(key);
                self.push(&[flag, &said]);
            }
        }
    }
}

/// `f"{value:g}"`.
pub struct PythonGeneral;

impl PythonGeneral {
    /// Six significant digits, no trailing zeros, an exponent below 1e-4 and from 1e6.
    pub fn of(value: f64) -> String {
        if value == 0.0 {
            return "0".to_string();
        }
        let scientific = format!("{value:.5e}");
        let Some((digits, exponent)) = scientific.split_once('e') else {
            return scientific;
        };
        // absent-ok: Rust's exponent form always has a whole exponent.
        let exponent: i32 = exponent.parse().unwrap_or(0);
        if (-4..6).contains(&exponent) {
            let places = (5 - exponent).max(0) as usize;
            let plain = format!("{value:.places$}");
            let trimmed = if plain.contains('.') { plain.trim_end_matches('0').trim_end_matches('.') } else { plain.as_str() };
            return trimmed.to_string();
        }
        let digits = digits.trim_end_matches('0').trim_end_matches('.');
        let sign = if exponent < 0 { '-' } else { '+' };
        format!("{digits}e{sign}{:02}", exponent.abs())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    struct NoHeaders;

    impl ModelHeaders for NoHeaders {
        fn model_header(&self, _config: &Map<String, Value>, _model_path: &str) -> Value {
            json!({})
        }
    }

    struct Window(i64);

    impl ModelHeaders for Window {
        fn model_header(&self, _config: &Map<String, Value>, _model_path: &str) -> Value {
            json!({"contextLength": self.0, "architecture": "qwen3"})
        }
    }

    fn args(config: Value, headers: &dyn ModelHeaders, over_network: bool) -> Vec<String> {
        let config = config.as_object().unwrap().clone();
        let paths = ArgPaths {
            model: "/m.gguf",
            mmproj: "/p.gguf",
            spec: "/d.gguf",
            local_paths: true,
            over_network,
            header_path: "",
            port: "",
        };
        LlamaArgs::build(&config, &paths, headers)
    }

    #[test]
    fn an_empty_config_says_what_it_must() {
        assert_eq!(
            args(json!({}), &NoHeaders, false),
            ["--host", "127.0.0.1", "--port", "{{PORT}}", "--model", "/m.gguf", "--metrics", "--no-jinja", "--no-webui"]
        );
    }

    #[test]
    fn an_empty_window_is_the_trained_one_and_a_larger_one_is_yarn() {
        let line = args(json!({}), &Window(1000), false).join(" ");
        assert!(line.contains("--ctx-size 1000"), "{line}");
        let line = args(json!({"CTX_SIZE": "1500"}), &Window(1000), false).join(" ");
        assert!(
            line.ends_with(
                "--rope-scaling yarn --rope-scale 1.5 --yarn-orig-ctx 1000 --override-kv qwen3.context_length=int:1500"
            ),
            "{line}"
        );
    }

    #[test]
    fn a_model_over_the_network_is_not_mapped() {
        let line = |config: Value, over_network: bool| args(config, &NoHeaders, over_network).join(" ");
        assert!(line(json!({"MMAP": "1"}), true).contains("--load-mode none"));
        assert!(line(json!({}), true).contains("--load-mode none"), "asked for nothing, and still not mapped");
        assert!(line(json!({"ENABLE_MLOCK": "1"}), true).contains("--load-mode mlock"));
        assert!(line(json!({"LOAD_MODE": "mmap+mlock", "ENABLE_MLOCK": "1"}), true).contains("--load-mode mlock"));
        assert!(line(json!({"LOAD_MODE": "dio"}), true).contains("--load-mode dio"), "no mapping there to take out");
    }

    /// llama.cpp took the three old flags away: a cell that says one of them does not start. The switches still in a saved cell's settings mean what they meant.
    #[test]
    fn the_old_switches_are_read_into_the_one_flag_there_is() {
        let mode = |config: Value| {
            let words = args(config, &NoHeaders, false);
            words.iter().position(|word| word == "--load-mode").and_then(|at| words.get(at + 1)).cloned()
        };
        assert_eq!(mode(json!({})), None, "nothing asked: the server's own choice");
        assert_eq!(mode(json!({"MMAP": "1"})).as_deref(), Some("mmap"));
        assert_eq!(mode(json!({"MMAP": "0"})).as_deref(), Some("none"));
        assert_eq!(
            mode(json!({"ENABLE_MLOCK": "1"})).as_deref(),
            Some("mmap+mlock"),
            "locked, and mapped as the server maps by default"
        );
        assert_eq!(mode(json!({"ENABLE_MLOCK": "0"})), None);
        assert_eq!(mode(json!({"MMAP": "1", "ENABLE_MLOCK": "1"})).as_deref(), Some("mmap+mlock"));
        assert_eq!(mode(json!({"MMAP": "0", "ENABLE_MLOCK": "1"})).as_deref(), Some("mlock"));
        assert_eq!(
            mode(json!({"LOAD_MODE": "dio", "MMAP": "1", "ENABLE_MLOCK": "1"})).as_deref(),
            Some("dio"),
            "the field that says it outright wins"
        );
        for gone in ["--mmap", "--no-mmap", "--mlock"] {
            for config in [json!({"MMAP": "1"}), json!({"MMAP": "0"}), json!({"ENABLE_MLOCK": "1"})] {
                assert!(!args(config.clone(), &NoHeaders, false).iter().any(|word| word == gone), "{gone} for {config}");
                assert!(!args(config.clone(), &NoHeaders, true).iter().any(|word| word == gone), "{gone} for {config}");
            }
        }
    }

    #[test]
    fn a_draft_is_launched_by_its_kind() {
        let line = args(json!({"SPEC_DRAFT_MODEL_FILE": "m/mtp-q.gguf", "SPEC_DRAFT_N_MAX": "4"}), &NoHeaders, false).join(" ");
        assert!(
            line.contains("--spec-type draft-mtp --model-draft /d.gguf --gpu-layers-draft 999 --spec-draft-n-max 4"),
            "{line}"
        );
        let line = args(json!({"SPEC_TYPE": "mtp"}), &NoHeaders, false).join(" ");
        assert!(line.contains("--spec-type draft-mtp --spec-draft-n-max 2"), "{line}");
        let line = args(json!({"SPEC_TYPE": "mtp", "ENABLE_EMBEDDINGS": "1"}), &NoHeaders, false).join(" ");
        assert!(!line.contains("--spec-type") && line.contains("--embeddings"), "{line}");
    }

    #[test]
    fn thinking_goes_into_the_templates_words() {
        let line = args(json!({"ENABLE_THINKING": "0", "CHAT_TEMPLATE_KWARGS": "{\"a\": 1}"}), &NoHeaders, false).join(" ");
        assert!(line.contains("--chat-template-kwargs {\"a\":1,\"enable_thinking\":false}"), "{line}");
        let line = args(json!({"CHAT_TEMPLATE_KWARGS": "not json"}), &NoHeaders, false).join(" ");
        assert!(line.contains("--chat-template-kwargs not json"), "{line}");
    }

    #[test]
    fn a_number_is_said_as_python_says_it() {
        for (value, want) in [
            (1.5, "1.5"),
            (2.0, "2"),
            (1.33, "1.33"),
            (100000.0, "100000"),
            (1000000.0, "1e+06"),
            (0.0001, "0.0001"),
            (0.00001, "1e-05"),
            (1.234567, "1.23457"),
        ] {
            assert_eq!(PythonGeneral::of(value), want);
        }
    }
}
