//! The switches of a command: on and off, the projector, the draft, what comes last.

use super::*;

impl<'config> LlamaArgs<'config> {
    /// How the model is loaded: `LOAD_MODE`, else what the two old switches say. llama.cpp took `--mmap`, `--no-mmap` and `--mlock` away for `--load-mode`, and a cell with one of them does not start
    /// ("invalid argument", 2026-11-03). Empty leaves it to the server; a model read over the network is never mapped, and says so even when nothing else was asked.
    fn load_mode(&self, over_network: bool) -> String {
        let said = self.word("LOAD_MODE");
        let locked = self.yes("ENABLE_MLOCK");
        let mapped = self.has("MMAP").then(|| self.yes("MMAP"));
        let mode = match (said.is_empty(), mapped, locked) {
            (false, _, _) => said,
            (_, Some(true) | None, true) => "mmap+mlock".to_string(),
            (_, Some(false), true) => "mlock".to_string(),
            (_, Some(true), false) => "mmap".to_string(),
            (_, Some(false), false) => "none".to_string(),
            (_, None, false) => String::new(),
        };
        if !over_network {
            return mode;
        }
        if mode.is_empty() { "none".to_string() } else { Self::no_mmap_mode(&mode) }
    }

    pub(super) fn on_off_flags(&mut self, over_network: bool) {
        if self.yes("CPU_STRICT") {
            self.push(&["--cpu-strict", "1"]);
        }
        let load_mode = self.load_mode(over_network);
        if !load_mode.is_empty() {
            self.push(&["--load-mode", &load_mode]);
        }
        self.add_bool("KV_OFFLOAD", "--kv-offload", "--no-kv-offload");
        for (key, on, off) in [
            ("CACHE_PROMPT", "--cache-prompt", "--no-cache-prompt"),
            ("ENABLE_SLOTS", "--slots", "--no-slots"),
            ("SKIP_CHAT_PARSING", "--skip-chat-parsing", "--no-skip-chat-parsing"),
            ("REASONING_PRESERVE", "--reasoning-preserve", "--no-reasoning-preserve"),
            ("CONTEXT_SHIFT", "--context-shift", "--no-context-shift"),
            ("KV_UNIFIED", "--kv-unified", "--no-kv-unified"),
            ("CACHE_IDLE_SLOTS", "--cache-idle-slots", "--no-cache-idle-slots"),
            ("MMPROJ_AUTO", "--mmproj-auto", "--no-mmproj-auto"),
            ("OP_OFFLOAD", "--op-offload", "--no-op-offload"),
            ("REPACK", "--repack", "--no-repack"),
            ("WARMUP", "--warmup", "--no-warmup"),
        ] {
            self.add_bool(key, on, off);
        }
        if self.yes("CPU_MOE") {
            self.push(&["--cpu-moe"]);
        }
        if self.yes("CHECK_TENSORS") {
            self.push(&["--check-tensors"]);
        }
        if self.has("FIT") {
            let word = if self.yes("FIT") { "on" } else { "off" };
            self.push(&["--fit", word]);
        }
        if self.yes("ENABLE_PROPS") {
            self.push(&["--props"]);
        }
        if self.yes("ENABLE_CONT_BATCHING") {
            self.push(&["--cont-batching"]);
        }
        if Self::metrics_on(self.config) {
            self.push(&["--metrics"]);
        }
    }

    pub(super) fn projector_and_embeddings(&mut self, paths: &ArgPaths<'_>) {
        let is_embedding = self.yes("ENABLE_EMBEDDINGS");
        if is_embedding {
            self.push(&["--embeddings"]);
        }
        if self.has("MMPROJ_FILE") {
            let offload = if self.yes("OFFLOAD_MMPROJ") { "--mmproj-offload" } else { "--no-mmproj-offload" };
            self.push(&["--mmproj", paths.mmproj, offload]);
        }
        self.speculation(paths, is_embedding);
        if is_embedding || !self.yes("ENABLE_JINJA") {
            self.push(&["--no-jinja"]);
        } else {
            self.push(&["--jinja"]);
        }
    }

    pub(super) fn speculation(&mut self, paths: &ArgPaths<'_>, is_embedding: bool) {
        let mut spec_type = self.word("SPEC_TYPE").to_lowercase();
        if spec_type == "mtp" {
            spec_type = "draft-mtp".to_string();
        }
        if is_embedding {
            spec_type.clear();
        }
        if spec_type.starts_with("ngram-") {
            self.push(&["--spec-type", &spec_type]);
        } else if self.has("SPEC_DRAFT_MODEL_FILE") && !is_embedding {
            let kind = if spec_type.is_empty() {
                DraftFileWord::launch_type(Coerce::strip(&self.value("SPEC_DRAFT_MODEL_FILE"))).to_string()
            } else {
                spec_type
            };
            if kind != "none" {
                self.push(&["--spec-type", &kind, "--model-draft", paths.spec]);
                let layers = self.word("SPEC_DRAFT_N_GPU_LAYERS");
                let layers = if layers.is_empty() { "999".to_string() } else { layers };
                self.push(&["--gpu-layers-draft", &layers]);
                self.draft_counts("");
            }
        } else if spec_type == "draft-mtp" {
            self.push(&["--spec-type", "draft-mtp"]);
            self.draft_counts("2");
        }
    }

    pub(super) fn draft_counts(&mut self, most_by_default: &str) {
        let most = self.word("SPEC_DRAFT_N_MAX");
        let most = if most.is_empty() { most_by_default.to_string() } else { most };
        if !most.is_empty() {
            self.push(&["--spec-draft-n-max", &most]);
        }
        let least = self.word("SPEC_DRAFT_N_MIN");
        if !least.is_empty() {
            self.push(&["--spec-draft-n-min", &least]);
        }
    }

    pub(super) fn last_switches(&mut self) {
        if self.has("ENABLE_FLASH_ATTN") {
            let word = if self.yes("ENABLE_FLASH_ATTN") { "on" } else { "off" };
            self.push(&["--flash-attn", word]);
        }
        if !self.yes("ENABLE_WEBUI") {
            self.push(&["--no-webui"]);
        }
        self.add_bool("CORS_CREDENTIALS", "--cors-credentials", "--no-cors-credentials");
        if self.yes("SWA_FULL") {
            self.push(&["--swa-full"]);
        }
        if self.yes("ENABLE_RERANK") {
            self.push(&["--rerank"]);
        }
        if self.yes("CPU_MOE_DRAFT") && !self.yes("ENABLE_EMBEDDINGS") {
            self.push(&["--spec-draft-cpu-moe"]);
        }
        if self.yes("ENABLE_TOOLS") {
            self.push(&["--tools", "all"]);
        }
        if self.yes("ENABLE_AGENT") {
            self.push(&["--agent"]);
        }
        if self.yes("ENABLE_MCP_PROXY") {
            self.push(&["--ui-mcp-proxy"]);
        }
    }

    pub(super) fn extra_args(&mut self) {
        if self.has("EXTRA_ARGS") {
            let extra = ShellSplit::words(&self.value("EXTRA_ARGS"));
            self.args.extend(extra);
        }
    }

    /// The YaRN flags implied by CTX_SIZE exceeding the model's native window.
    pub(super) fn auto_yarn_args(&self, header_at: &str) -> Vec<String> {
        let said = self.word("CTX_SIZE");
        // absent-ok: a window that is no number asks for none: the server chooses.
        let context: i64 = if said.is_empty() { 0 } else { said.parse().unwrap_or(0) };
        if context <= 0 {
            return Vec::new();
        }
        let meta = self.headers.model_header(self.config, header_at);
        // absent-ok: a header that names no window has nothing to exceed, as the next line says.
        let native = Coerce::i64_or_zero(meta.get("contextLength"));
        let arch = Coerce::text(meta.get("architecture"));
        if native == 0 || arch.is_empty() || context <= native {
            return Vec::new();
        }
        let extra_raw = Coerce::text(self.config.get("EXTRA_ARGS"));
        let present = |flag: &str| self.args.iter().any(|arg| arg == flag);
        let mut out = Vec::new();
        if !present("--rope-scaling") {
            out.extend(["--rope-scaling".to_string(), "yarn".to_string()]);
        }
        if !present("--rope-scale") {
            let scale = (context as f64 / native as f64 * 100.0).ceil() / 100.0;
            out.extend(["--rope-scale".to_string(), PythonGeneral::of(scale)]);
        }
        if !present("--yarn-orig-ctx") && !extra_raw.contains("--yarn-orig-ctx") {
            out.extend(["--yarn-orig-ctx".to_string(), native.to_string()]);
        }
        if !present("--override-kv") && !extra_raw.contains("--override-kv") {
            out.extend(["--override-kv".to_string(), format!("{arch}.context_length=int:{context}")]);
        }
        out
    }
}
