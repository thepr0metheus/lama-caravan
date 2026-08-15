// The controller's host id in API bodies and slot keys — a role name the
// backend also accepts under its legacy spellings; keep in sync with
// caravan/admin/paths.py CONTROLLER_HOST_ID.
export const CONTROLLER_HOST_ID = "controller";

// Launch-form field definitions (shared by the config form and edit modals).
export const numericFields = [
  "HOST", "PORT", "CTX_SIZE", "THREADS", "THREADS_BATCH", "BATCH_SIZE",
  "UBATCH_SIZE", "PARALLEL", "N_GPU_LAYERS", "CACHE_TYPE_K", "CACHE_TYPE_V",
  "N_PREDICT", "KEEP", "CPU_RANGE", "POLL", "ROPE_SCALING", "ROPE_SCALE",
  "ROPE_FREQ_BASE", "ROPE_FREQ_SCALE", "NUMA", "DEVICE", "SPLIT_MODE",
  "TENSOR_SPLIT", "MAIN_GPU", "FIT_TARGET", "FIT_CTX", "ALIAS", "API_PREFIX",
  "TIMEOUT", "THREADS_HTTP", "CACHE_REUSE", "CACHE_RAM", "SLEEP_IDLE_SECONDS",
  "API_KEY", "SSL_CERT_FILE", "SSL_KEY_FILE",
  "IMAGE_MIN_TOKENS",
  "IMAGE_MAX_TOKENS", "REASONING", "REASONING_FORMAT", "REASONING_BUDGET",
  "CHAT_TEMPLATE", "CHAT_TEMPLATE_FILE", "CHAT_TEMPLATE_KWARGS",
  "SPEC_TYPE", "SPEC_DRAFT_MODEL_FILE",
  "SPEC_DRAFT_N_GPU_LAYERS", "SPEC_DRAFT_N_MAX", "SPEC_DRAFT_N_MIN",
  "SPEC_DRAFT_CACHE_TYPE_K", "SPEC_DRAFT_CACHE_TYPE_V", "SPEC_DRAFT_P_MIN",
  "POOLING", "EMBD_NORMALIZE",
  "LOAD_MODE", "N_CPU_MOE", "MTMD_BATCH_MAX_TOKENS", "CTX_CHECKPOINTS",
  "LOG_VERBOSITY", "CORS_ORIGINS", "TOOLS_RUNTIME", "API_KEY_FILE",
  "EXTRA_ARGS"
];
export const toggleFields = [
  "ENABLE_JINJA", "ENABLE_THINKING", "ENABLE_FLASH_ATTN", "ENABLE_MLOCK", "ENABLE_METRICS",
  "ENABLE_CONT_BATCHING", "ENABLE_WEBUI", "OFFLOAD_MMPROJ", "CPU_STRICT",
  "KV_OFFLOAD", "MMAP", "FIT", "CACHE_PROMPT", "ENABLE_PROPS", "ENABLE_SLOTS",
  "SKIP_CHAT_PARSING", "ENABLE_TOOLS", "ENABLE_AGENT", "ENABLE_MCP_PROXY",
  "ENABLE_EMBEDDINGS",
  "CONTEXT_SHIFT", "KV_UNIFIED", "REASONING_PRESERVE", "CACHE_IDLE_SLOTS", "MMPROJ_AUTO",
  "SWA_FULL", "ENABLE_RERANK", "CORS_CREDENTIALS"
];
export const basicFields = [
  "HOST", "PORT", "CTX_SIZE", "THREADS", "THREADS_BATCH", "BATCH_SIZE",
  "UBATCH_SIZE", "PARALLEL", "N_GPU_LAYERS", "CACHE_TYPE_K", "CACHE_TYPE_V",
  "ENABLE_JINJA", "ENABLE_FLASH_ATTN", "ENABLE_MLOCK", "ENABLE_METRICS",
  "ENABLE_CONT_BATCHING", "ENABLE_WEBUI"
];
export const advancedGroups = [
  { titleKey: "advancedGeneration", fields: ["N_PREDICT", "KEEP", "ENABLE_THINKING", "CONTEXT_SHIFT"] },
  { titleKey: "advancedSpeculative", fields: ["SPEC_TYPE", "SPEC_DRAFT_N_GPU_LAYERS", "SPEC_DRAFT_N_MAX", "SPEC_DRAFT_N_MIN", "SPEC_DRAFT_P_MIN", "SPEC_DRAFT_CACHE_TYPE_K", "SPEC_DRAFT_CACHE_TYPE_V"] },
  { titleKey: "advancedCpu", fields: ["CPU_RANGE", "CPU_STRICT", "POLL"] },
  { titleKey: "advancedRope", fields: ["ROPE_SCALING", "ROPE_SCALE", "ROPE_FREQ_BASE", "ROPE_FREQ_SCALE"] },
  { titleKey: "advancedGpu", fields: ["KV_OFFLOAD", "NUMA", "DEVICE", "SPLIT_MODE", "TENSOR_SPLIT", "MAIN_GPU", "N_CPU_MOE", "FIT", "FIT_TARGET", "FIT_CTX", "KV_UNIFIED"] },
  { titleKey: "advancedServer", fields: ["ALIAS", "API_PREFIX", "TIMEOUT", "THREADS_HTTP", "ENABLE_PROPS", "ENABLE_SLOTS", "SLEEP_IDLE_SECONDS", "LOG_VERBOSITY"] },
  { titleKey: "advancedCache", fields: ["CACHE_PROMPT", "CACHE_REUSE", "CACHE_RAM", "CACHE_IDLE_SLOTS", "CTX_CHECKPOINTS", "SWA_FULL"] },
  { titleKey: "advancedNetwork", fields: ["API_KEY", "API_KEY_FILE", "SSL_CERT_FILE", "SSL_KEY_FILE"] },
  { titleKey: "advancedCors", fields: ["CORS_ORIGINS", "CORS_CREDENTIALS"] },
  { titleKey: "advancedLoading", fields: ["LOAD_MODE", "MMAP"] },
  { titleKey: "advancedVision", fields: ["IMAGE_MIN_TOKENS", "IMAGE_MAX_TOKENS", "MTMD_BATCH_MAX_TOKENS", "MMPROJ_AUTO"] },
  { titleKey: "advancedReasoning", fields: ["REASONING", "REASONING_FORMAT", "REASONING_BUDGET", "REASONING_PRESERVE", "CHAT_TEMPLATE", "CHAT_TEMPLATE_KWARGS", "SKIP_CHAT_PARSING"] },
  { titleKey: "advancedTools", fields: ["ENABLE_TOOLS", "ENABLE_AGENT", "ENABLE_MCP_PROXY", "TOOLS_RUNTIME"] },
  { titleKey: "advancedEmbeddings", fields: ["ENABLE_EMBEDDINGS", "ENABLE_RERANK", "POOLING", "EMBD_NORMALIZE"] },
];

export const advancedTabDefs = [
  { key: "tabInference", groups: ["advancedGeneration", "advancedSpeculative"] },
  { key: "tabHardware",  groups: ["advancedCpu", "advancedRope", "advancedGpu", "advancedLoading"] },
  { key: "tabServer",    groups: ["advancedEmbeddings", "advancedServer", "advancedCache", "advancedNetwork", "advancedCors", "advancedVision", "advancedReasoning", "advancedTools"] },
];
// EXTRA_ARGS (manual raw-flags escape hatch) is rendered separately on the
// default Params tab for visibility — see renderFields().
export const optionalToggleFields = ["CPU_STRICT", "KV_OFFLOAD", "MMAP", "FIT", "CACHE_PROMPT", "ENABLE_PROPS", "ENABLE_SLOTS", "SKIP_CHAT_PARSING", "ENABLE_THINKING"];
export const defaultOnOptionalToggles = ["KV_OFFLOAD", "MMAP", "FIT", "CACHE_PROMPT", "ENABLE_SLOTS", "ENABLE_THINKING"];
// Closed value sets rendered as a <datalist> beside the plain input: they stay
// free text (an unknown future value must remain typeable) while every legal
// value is discoverable. SPEC_TYPE is the field the whole speculative-decoding
// story hangs on, and six of its eleven values were unnameable from the UI.
export const fieldChoices = {
  SPEC_TYPE: ["none", "draft-simple", "draft-eagle3", "draft-mtp", "draft-dflash",
    "draft-dspark", "ngram-simple", "ngram-map-k", "ngram-map-k4v", "ngram-mod", "ngram-cache"],
  LOAD_MODE: ["none", "mmap", "mlock", "mmap+mlock", "dio"],
};

export const modelFields = ["LLAMA_MODELS_DIR", "MODEL_FILE", "MMPROJ_FILE", "CHAT_TEMPLATE_FILE"];
export const memoryEstimateFields = ["CTX_SIZE", "CACHE_TYPE_K", "CACHE_TYPE_V", "BATCH_SIZE", "UBATCH_SIZE"];
// Numeric weights (GB) for the command-runner fit panel. The model pickers in
// form.js show the matching human labels ("3 GB", "75 MB") — keep the two in sync.
export const whisperModelGb = {
  tiny: 0.075, base: 0.145, small: 0.48, medium: 1.5,
  "large-v3": 3, "large-v3-turbo": 1.6, "distil-large-v3": 1.5,
};
// Every Moonshine v2 model is ~250M params, whatever the language.
export const moonshineModelGb = 0.25;
export const gemma4DraftModel = "gemma-4-31b-it/assistant/gemma-4-31B-it-assistant.Q4_K_M.gguf";
export const gemma4DefaultMmproj = "gemma-4-31b-it/q4-k-m/mmproj-gemma-4-31B-it-f32.gguf";
export const dirtyOptionalToggles = new Set();
