//! `llama.cpp`'s own server and PrismML's fork of it.

use super::{Config, Runner, RunnerRow, TalkSpec};
use rules::{AppError, CudaCards, KvCache};

/// `llama.cpp`'s own server: the default, and the only one not on the command path: it has a launch renderer of its own.
pub struct LlamaServerRunner;

impl LlamaServerRunner {
    pub(super) const ROW: RunnerRow = RunnerRow {
        id: "llama-server",
        icon: "\u{1f999}",
        label_key: "runnerLlama",
        benefits_key: "runnerLlamaBenefits",
        minus_key: "runnerLlamaMinus",
        formats: &["gguf"],
        artifacts: &["llm-gguf"],
        needs_key: "runnerNeedsLlmGguf",
        health: "/health",
        api: "openai",
        model_field: Some("MODEL_FILE"),
        shared_picker: "source",
        token_context: true,
        command_path: false,
        llama_config: true,
        // A model that hears takes a recording in its chat and answers in words: which cells hear is the running server's to say. Any of its chat models is asked in text from the cell window's Talk tab.
        talk: TalkSpec { modes: &["heard-chat", "text-chat"], ..TalkSpec::NONE },
        ..RunnerRow::BASE
    };

    /// The cards the process may see. CPU mode hides them all: a CUDA build of `llama.cpp` still initializes the backend at `-ngl 0`, and ABORTS with "out of memory" when the card is full. A cell on the GPU hides the cards it did not pick, for the same reason.
    fn cards_env(config: &Config) -> Vec<(String, String)> {
        let mut env = vec![("CUDA_DEVICE_ORDER".to_string(), "PCI_BUS_ID".to_string())];
        if let Some(seen) = CudaCards::of(config).visible() {
            env.push(("CUDA_VISIBLE_DEVICES".to_string(), seen));
        }
        env
    }
}

impl Runner for LlamaServerRunner {
    fn row(&self) -> &RunnerRow {
        &Self::ROW
    }

    fn server_binary(&self, llama_home: &str) -> Option<String> {
        Some(format!("{}/build/bin/llama-server", llama_home.trim_end_matches('/')))
    }

    fn preflight_start(&self, config: &Config, model: &str) -> Result<(), AppError> {
        let said = if model.is_empty() { self.model_ref(config) } else { model.to_string() }.to_uppercase();
        if said.contains("PQ2_0") || said.contains("PTQ1_0") {
            return Err(AppError::new("This GGUF uses PrismML tensor types — select the PrismML runner"));
        }
        // A cell saved with a quantized V cache and flash attention off crashed four times and gave up, with the last line of the log on its card: the refusal names the cause instead.
        KvCache::check(config)
    }

    fn launch_env(&self, config: &Config) -> Vec<(String, String)> {
        Self::cards_env(config)
    }
}

/// PrismML's fork, with its own binary and matching ggml libraries.
pub struct PrismRunner {
    /// The controller's home: the path is a preview: the scout records the immutable installed release path.
    pub home: String,
}

impl PrismRunner {
    const ROW: RunnerRow = RunnerRow {
        id: "prism",
        icon: "🌱",
        label_key: "runnerPrism",
        benefits_key: "runnerPrismBenefits",
        minus_key: "runnerPrismMinus",
        ..LlamaServerRunner::ROW
    };

    fn folder(&self) -> String {
        format!("{}/.local/share/caravan/prismml/current", self.home.trim_end_matches('/'))
    }
}

impl Runner for PrismRunner {
    fn row(&self) -> &RunnerRow {
        &Self::ROW
    }

    /// Preview only: the scout records the immutable installed release path.
    fn server_binary(&self, _llama_home: &str) -> Option<String> {
        Some(format!("{}/llama-server", self.folder()))
    }

    fn preflight_start(&self, config: &Config, model: &str) -> Result<(), AppError> {
        if model.is_empty() && self.model_ref(config).is_empty() {
            return Err(AppError::new("PrismML cell has no model — configure it first"));
        }
        KvCache::check(config)
    }

    fn launch_env(&self, config: &Config) -> Vec<(String, String)> {
        let mut env = LlamaServerRunner::cards_env(config);
        let folder = self.folder();
        env.push(("LD_LIBRARY_PATH".to_string(), folder.clone()));
        env.push(("DYLD_LIBRARY_PATH".to_string(), folder));
        env
    }
}
