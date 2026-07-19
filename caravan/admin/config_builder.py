"""Launch-config contract: parse/build the # BEGIN/END LLAMA CONFIG block and
turn a config dict into llama-server CLI args (single source of truth).

CONFIG_FIELDS names and the marker lines are a contract with
scripts/start-server.sh — never rename them here alone.
"""
import json
import re
import shlex
from pathlib import Path

from caravan.admin.paths import DEFAULT_MODELS_DIR, LLAMA_HOME, START_SCRIPT
from caravan.common.errors import AppError
from caravan.admin.runners import runner_id
from caravan.common.fsio import read_text


CONFIG_BEGIN = "# BEGIN LLAMA CONFIG"

CONFIG_END = "# END LLAMA CONFIG"

CONFIG_FIELDS = [
    "HOST",
    "PORT",
    "LLAMA_MODELS_DIR",
    "MODEL_FILE",
    "MMPROJ_FILE",
    "SPEC_TYPE",
    "SPEC_DRAFT_MODEL_FILE",
    "SPEC_DRAFT_N_GPU_LAYERS",
    "SPEC_DRAFT_N_MAX",
    "SPEC_DRAFT_N_MIN",
    "SPEC_DRAFT_CACHE_TYPE_K",
    "SPEC_DRAFT_CACHE_TYPE_V",
    "CTX_SIZE",
    "THREADS",
    "THREADS_BATCH",
    "BATCH_SIZE",
    "UBATCH_SIZE",
    "PARALLEL",
    "N_GPU_LAYERS",
    "CACHE_TYPE_K",
    "CACHE_TYPE_V",
    "N_PREDICT",
    "KEEP",
    "CPU_RANGE",
    "CPU_STRICT",
    "POLL",
    "ROPE_SCALING",
    "ROPE_SCALE",
    "ROPE_FREQ_BASE",
    "ROPE_FREQ_SCALE",
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
    "ENABLE_JINJA",
    "ENABLE_THINKING",
    "ENABLE_FLASH_ATTN",
    "ENABLE_MLOCK",
    "ENABLE_METRICS",
    "ENABLE_CONT_BATCHING",
    "ENABLE_WEBUI",
    "MMPROJ_AUTO",
    "OFFLOAD_MMPROJ",
    "ENABLE_TOOLS",
    "ENABLE_AGENT",
    "ENABLE_MCP_PROXY",
    "ENABLE_EMBEDDINGS",
    "POOLING",
    "EMBD_NORMALIZE",
    "EXTRA_ARGS",
    # ── Generic command cell ────────────────────────────────────────────────
    # CELL_KIND="command" turns a cell into a managed arbitrary process (e.g. a
    # whisper-server) instead of llama-server. Empty CELL_KIND (the default for
    # every existing cell) stays a normal llama.cpp cell, so nothing else changes.
    # RUNNER supersedes it (see caravan/admin/runners.py): the GUI writes both
    # so old readers (scout included) keep working from CELL_KIND alone.
    "RUNNER",        # "" (legacy -> derive from CELL_KIND) | "llama-server" | "custom"
    "CELL_KIND",     # "" | "command"
    "COMMAND",       # single shell command line for a command cell; may use $PORT
    "HEALTH_PATH",   # optional HTTP path to health-probe (empty = TCP port probe)
    "ENV",           # command cell: newline/comma KEY=VALUE env exports
    "WORKDIR",       # command cell: working directory (cd before exec)
    # vLLM runner (RUNNER="vllm"): compiled into the command-cell machinery at
    # launch time — scout and start.sh treat it as a managed command.
    "VLLM_MODEL",              # HF repo id (nvidia/Qwen3.6-27B-NVFP4) or local path
    "MAX_MODEL_LEN",           # --max-model-len
    "GPU_MEMORY_UTILIZATION",  # --gpu-memory-utilization (0.90)
    "QUANTIZATION",            # --quantization (auto|modelopt|awq|gptq|fp8)
    "DTYPE",                   # --dtype (auto|bfloat16|float16)
    "TENSOR_PARALLEL",         # --tensor-parallel-size
    # whisper runner (RUNNER="whisper"): run_whisper.sh "$PORT" <size>
    "WHISPER_MODEL",           # faster-whisper size: tiny…large-v3(-turbo)
    # moonshine runner (RUNNER="moonshine"): run_moonshine.sh "$PORT" <lang>
    "MOONSHINE_MODEL",         # moonshine language: en es zh ja ko vi uk ar
]

FIELD_HELP = {
    "HOST": "Bind address. 0.0.0.0 exposes the server on the LAN.",
    "RUNNER": "Launch flavour of this cell: llama-server or a custom managed command. Legacy configs derive it from CELL_KIND.",
    "CELL_KIND": "Legacy launch-kind flag; superseded by RUNNER but still written for old readers.",
    "COMMAND": "Full shell command for a custom cell. $PORT expands to the cell port.",
    "ENV": "Extra environment for the command: newline- or comma-separated KEY=VALUE pairs.",
    "WORKDIR": "Working directory the command starts in (cd before exec).",
    "HEALTH_PATH": "HTTP path probed to decide the cell is up; empty falls back to a TCP port probe.",
    "VLLM_MODEL": "HF repo id (e.g. nvidia/Qwen3.6-27B-NVFP4) or a local path; vLLM downloads HF repos into its own cache on first start.",
    "MAX_MODEL_LEN": "vLLM context window (--max-model-len). Empty lets vLLM use the model default — large defaults can exhaust VRAM.",
    "GPU_MEMORY_UTILIZATION": "Fraction of VRAM vLLM may claim (--gpu-memory-utilization), e.g. 0.90.",
    "QUANTIZATION": "vLLM quantization backend (--quantization): auto detects; modelopt for NVFP4 checkpoints, awq/gptq for INT4.",
    "DTYPE": "Activation dtype (--dtype): auto, bfloat16 or float16.",
    "TENSOR_PARALLEL": "GPUs to shard across (--tensor-parallel-size). 1 on single-GPU hosts.",
    "WHISPER_MODEL": "faster-whisper model size (tiny…large-v3). Downloaded automatically on first start; language is chosen per request.",
    "MOONSHINE_MODEL": "Moonshine v2 language (en es zh ja ko vi uk ar) — CPU-only STT, the model downloads itself on first start. en is MIT-licensed; the rest need the free Moonshine Community License (registration + attribution). No Russian — use whisper for RU.",
    "PORT": "llama.cpp HTTP port. OpenAI-compatible API is /v1 on this port.",
    "LLAMA_MODELS_DIR": "Directory where local GGUF models and mmproj files are stored.",
    "MODEL_FILE": "GGUF model path relative to the models directory.",
    "MMPROJ_FILE": "Multimodal projector path. Empty means text-only mode.",
    "SPEC_TYPE": "Speculative decoding type (--spec-type). Official llama.cpp values: draft-mtp (Gemma 4 MTP text boost), draft-simple, draft-eagle3, ngram-*. Empty/none disables it.",
    "SPEC_DRAFT_MODEL_FILE": "Draft / MTP-head GGUF path (--model-draft), relative to the models directory. Required to enable speculative decoding.",
    "SPEC_DRAFT_N_GPU_LAYERS": "GPU layers for the draft model (--gpu-layers-draft). 999/all keeps the small drafter on GPU.",
    "SPEC_DRAFT_N_MAX": "Maximum draft tokens proposed per speculative decoding step (--draft-max).",
    "SPEC_DRAFT_N_MIN": "Minimum draft tokens before speculative decoding is used (--draft-min).",
    "SPEC_DRAFT_CACHE_TYPE_K": "KV cache data type for draft model K cache (--cache-type-k-draft).",
    "SPEC_DRAFT_CACHE_TYPE_V": "KV cache data type for draft model V cache (--cache-type-v-draft).",
    "CTX_SIZE": "Requested context size. Larger values consume more KV cache memory.",
    "THREADS": "CPU threads used for generation-side CPU work.",
    "THREADS_BATCH": "CPU threads used during prompt/batch processing.",
    "BATCH_SIZE": "Logical prompt batch size. Higher can improve prompt throughput.",
    "UBATCH_SIZE": "Physical batch chunk size. Higher can use more VRAM.",
    "PARALLEL": "Number of parallel slots. Higher shares context memory across users.",
    "N_GPU_LAYERS": "How many model layers to offload to GPU. 999 means all possible.",
    "CACHE_TYPE_K": "KV cache quantization for K. q8_0 saves memory with good quality.",
    "CACHE_TYPE_V": "KV cache quantization for V. q8_0 saves memory with good quality.",
    "N_PREDICT": "Maximum generated tokens. -1 means unlimited.",
    "KEEP": "Tokens to keep from the initial prompt when context shifts. -1 keeps all.",
    "CPU_RANGE": "CPU affinity range, for example 0-7. Empty lets the OS schedule freely.",
    "CPU_STRICT": "Use strict CPU placement with CPU_RANGE.",
    "POLL": "Polling level while waiting for work, 0-100.",
    "ROPE_SCALING": "RoPE scaling method: none, linear, or yarn. Empty uses model/default.",
    "ROPE_SCALE": "RoPE context scaling factor. Empty uses model/default.",
    "ROPE_FREQ_BASE": "RoPE base frequency override. Empty uses model/default.",
    "ROPE_FREQ_SCALE": "RoPE frequency scale override. Empty uses model/default.",
    "KV_OFFLOAD": "Offload KV cache to GPU when possible.",
    "CONTEXT_SHIFT": "Slide the context window on endless generation instead of stopping at the ctx limit (--context-shift). Empty = llama.cpp default (off); 1 = on, 0 = explicitly off.",
    "KV_UNIFIED": "Use a single unified KV-cache buffer across slots (--kv-unified) instead of per-slot buffers. Empty = llama.cpp default; can change VRAM use with --parallel.",
    "MMPROJ_AUTO": "Auto-load the multimodal projector companion when present (--mmproj-auto). Empty = llama.cpp default (on); 0 forces off even if an mmproj file is set.",
    "MMAP": "Memory-map model files. Usually faster startup and lower RAM pressure.",
    "NUMA": "NUMA mode: distribute, isolate, or numactl. Empty disables.",
    "DEVICE": "Comma-separated devices for offload. Empty lets llama.cpp choose.",
    "SPLIT_MODE": "Multi-GPU split mode: none, layer, or row.",
    "TENSOR_SPLIT": "Comma-separated proportions for splitting tensors across GPUs.",
    "MAIN_GPU": "Main GPU index for split-mode none/row.",
    "FIT": "Let llama.cpp adjust unset options to fit device memory.",
    "FIT_TARGET": "MiB margin per GPU for --fit.",
    "FIT_CTX": "Minimum context size allowed by --fit.",
    "ALIAS": "Model alias exposed by API.",
    "API_PREFIX": "URL prefix for the server, without trailing slash.",
    "TIMEOUT": "HTTP read/write timeout in seconds.",
    "THREADS_HTTP": "HTTP worker threads. -1 means auto.",
    "CACHE_PROMPT": "Enable prompt cache reuse.",
    "CACHE_REUSE": "Minimum chunk size for KV cache reuse.",
    "CACHE_RAM": "Prompt-cache RAM cap in MiB (--cache-ram). llama.cpp default 8192; -1 = unlimited, 0 = disable. Lower it on RAM-tight hosts.",
    "CACHE_IDLE_SLOTS": "Keep the prompt cache for idle slots (--cache-idle-slots) so a returning client skips re-processing its prompt. Empty = llama.cpp default; 0 disables to reclaim RAM.",
    "SLEEP_IDLE_SECONDS": "Put the server to sleep after N idle seconds (--sleep-idle-seconds), freeing VRAM until the next request wakes it. Empty/0 = never sleep. Trades first-token latency after idle for VRAM.",
    "API_KEY": "Require this key on every request (--api-key). Usually left empty here — the caravan proxy handles auth; set only for a cell exposed directly.",
    "SSL_CERT_FILE": "Path to a TLS certificate (--ssl-cert-file) to serve HTTPS directly. Host-local path; usually unset (the proxy terminates TLS).",
    "SSL_KEY_FILE": "Path to the TLS private key (--ssl-key-file), paired with the certificate. Host-local path.",
    "ENABLE_PROPS": "Enable POST /props for changing global server properties.",
    "ENABLE_SLOTS": "Expose slot monitoring endpoint.",
    "IMAGE_MIN_TOKENS": "Minimum image tokens for dynamic-resolution vision models.",
    "IMAGE_MAX_TOKENS": "Maximum image tokens for dynamic-resolution vision models.",
    "REASONING": "Reasoning mode: on, off, or auto.",
    "REASONING_FORMAT": "Reasoning output format: none, deepseek, deepseek-legacy, or auto.",
    "REASONING_BUDGET": "Thinking token budget. -1 unrestricted, 0 disables thinking budget.",
    "REASONING_PRESERVE": "Keep the reasoning trace across the whole chat history, not only the last turn (--reasoning-preserve). Empty = template default; needs a template with supports_preserve_reasoning (Qwen3.6 suggests enabling).",
    "CHAT_TEMPLATE": "Built-in chat template name override. Empty uses model metadata.",
    "CHAT_TEMPLATE_FILE": "Path to a custom Jinja chat template file. Overrides model metadata/template behavior when set.",
    "CHAT_TEMPLATE_KWARGS": "JSON object passed into the Jinja chat template parser, for model-specific tool/template knobs.",
    "ENABLE_THINKING": "🧠 Model reasoning/thinking. On = model default. Turn OFF to force a direct answer (sets chat-template enable_thinking=false) — fixes reasoning models (gemma-4, Qwen3) that otherwise return empty content, e.g. for translation.",
    "SKIP_CHAT_PARSING": "Force llama.cpp to return raw assistant content instead of parsing reasoning/tool calls.",
    "ENABLE_JINJA": "Enable model chat templates and tool-capable formatting.",
    "ENABLE_FLASH_ATTN": "Enable flash attention for speed and lower memory pressure.",
    "ENABLE_MLOCK": "Ask the OS to keep model memory resident.",
    "ENABLE_METRICS": "Expose Prometheus metrics at /metrics.",
    "ENABLE_CONT_BATCHING": "Allow continuous batching for queued requests.",
    "ENABLE_WEBUI": "Enable llama.cpp built-in Web UI. Usually off here.",
    "OFFLOAD_MMPROJ": "Try to offload vision projector to GPU. Needs extra VRAM.",
    "ENABLE_TOOLS": "Enable ALL built-in WebUI tools (--tools all): read_file, write_file, exec_shell_command, grep_search, file_glob_search, edit_file, apply_diff, get_datetime. For a specific subset instead, leave this off and use EXTRA_ARGS '--tools name1,name2'. Security risk: tools run as the server process with no path restriction.",
    "ENABLE_AGENT": "Agent mode (--agent): enable CORS proxy and ALL built-in tools at once. Convenience switch; supersedes TOOLS. Do not enable in untrusted environments.",
    "ENABLE_MCP_PROXY": "Enable the MCP CORS proxy (--ui-mcp-proxy) so the WebUI can reach MCP servers/tools. Experimental; do not enable in untrusted environments.",
    "ENABLE_EMBEDDINGS": "Run this server in embedding mode (--embeddings): exposes /v1/embeddings and returns vectors instead of chat. A chat model cannot also serve embeddings on the same instance — use a dedicated embedding model.",
    "POOLING": "How token states are pooled into one vector (--pooling): none | mean | cls | last | rank. Must match the model: Qwen3-Embedding = last, BERT/bge = cls, e5/gte/nomic = mean. Wrong pooling = garbage vectors.",
    "EMBD_NORMALIZE": "Embedding normalization (--embd-normalize): -1 none, 0 max-abs-int16, 1 taxicab, 2 euclidean/L2 (default), >2 p-norm. Leave blank for the llama.cpp default (L2).",
    "EXTRA_ARGS": "Raw extra llama-server flags appended verbatim to the command, space-separated (e.g. --some-new-flag value). Escape hatch for options without a dedicated field.",
}

def split_config(text):
    begin = text.find(CONFIG_BEGIN)
    end = text.find(CONFIG_END)
    if begin < 0 or end < 0 or end <= begin:
        raise AppError(f"Config markers not found in {START_SCRIPT}", 500)
    line_end = text.find("\n", end)
    if line_end < 0:
        line_end = len(text)
    else:
        line_end += 1
    return text[:begin], text[begin:line_end], text[line_end:]

def parse_value(raw):
    raw = raw.strip()
    if (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'")):
        return raw[1:-1]
    return raw

def parse_config():
    # Fresh installs have no legacy single-server layout (~/llama.cpp/
    # start-server.sh) — the board must still come up: server cells don't
    # need it. Missing script => empty config instead of a 500 on /api/state.
    if not START_SCRIPT.exists():
        return {}
    return parse_config_from_text(read_text(START_SCRIPT))

def parse_config_from_text(text, source="text"):
    try:
        _, block, _ = split_config(text)
    except AppError:
        raise AppError(f"Config markers not found in {source}")
    config = {}
    for line in block.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if key in CONFIG_FIELDS:
            config[key] = parse_value(value)
    for key in CONFIG_FIELDS:
        config.setdefault(key, "")
    config["LLAMA_MODELS_DIR"] = config.get("LLAMA_MODELS_DIR") or str(DEFAULT_MODELS_DIR)
    return config

def quote_shell_value(value):
    text = str(value)
    escaped = text.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$")
    return f'"{escaped}"'

def build_config_block(config):
    merged = {key: str(config.get(key, "")).strip() for key in CONFIG_FIELDS}
    if not merged["MODEL_FILE"]:
        raise AppError("MODEL_FILE is required")
    if not merged["PORT"].isdigit():
        raise AppError("PORT must be a number")
    for key in [
        "CTX_SIZE", "THREADS", "THREADS_BATCH", "BATCH_SIZE", "UBATCH_SIZE", "PARALLEL",
        "N_PREDICT", "KEEP", "POLL", "MAIN_GPU", "FIT_CTX", "TIMEOUT",
        "THREADS_HTTP", "CACHE_REUSE", "CACHE_RAM", "SLEEP_IDLE_SECONDS", "IMAGE_MIN_TOKENS", "IMAGE_MAX_TOKENS", "REASONING_BUDGET",
        "SPEC_DRAFT_N_GPU_LAYERS", "SPEC_DRAFT_N_MAX", "SPEC_DRAFT_N_MIN",
    ]:
        if merged[key] and not re.fullmatch(r"-?\d+", merged[key]):
            raise AppError(f"{key} must be a number")
    if merged["FIT_TARGET"] and not re.fullmatch(r"\d+(,\d+)*", merged["FIT_TARGET"]):
        raise AppError("FIT_TARGET must be a number or comma-separated numbers")

    lines = [CONFIG_BEGIN]
    groups = [
        ["HOST", "PORT"],
        ["LLAMA_MODELS_DIR", "MODEL_FILE", "MMPROJ_FILE"],
        ["SPEC_TYPE", "SPEC_DRAFT_MODEL_FILE", "SPEC_DRAFT_N_GPU_LAYERS", "SPEC_DRAFT_N_MAX", "SPEC_DRAFT_N_MIN", "SPEC_DRAFT_CACHE_TYPE_K", "SPEC_DRAFT_CACHE_TYPE_V"],
        ["CTX_SIZE", "THREADS", "THREADS_BATCH", "BATCH_SIZE", "UBATCH_SIZE", "PARALLEL", "N_GPU_LAYERS", "CACHE_TYPE_K", "CACHE_TYPE_V"],
        ["N_PREDICT", "KEEP", "CPU_RANGE", "CPU_STRICT", "POLL", "ROPE_SCALING", "ROPE_SCALE", "ROPE_FREQ_BASE", "ROPE_FREQ_SCALE"],
        ["KV_OFFLOAD", "MMAP", "CONTEXT_SHIFT", "KV_UNIFIED", "NUMA", "DEVICE", "SPLIT_MODE", "TENSOR_SPLIT", "MAIN_GPU", "FIT", "FIT_TARGET", "FIT_CTX"],
        ["ALIAS", "API_PREFIX", "TIMEOUT", "THREADS_HTTP", "CACHE_PROMPT", "CACHE_REUSE", "CACHE_RAM", "CACHE_IDLE_SLOTS", "SLEEP_IDLE_SECONDS", "API_KEY", "SSL_CERT_FILE", "SSL_KEY_FILE", "ENABLE_PROPS", "ENABLE_SLOTS"],
        ["IMAGE_MIN_TOKENS", "IMAGE_MAX_TOKENS", "REASONING", "REASONING_FORMAT", "REASONING_BUDGET", "REASONING_PRESERVE", "CHAT_TEMPLATE", "CHAT_TEMPLATE_FILE", "CHAT_TEMPLATE_KWARGS", "SKIP_CHAT_PARSING"],
        ["ENABLE_JINJA", "ENABLE_THINKING", "ENABLE_FLASH_ATTN", "ENABLE_MLOCK", "ENABLE_METRICS", "ENABLE_CONT_BATCHING", "ENABLE_WEBUI", "OFFLOAD_MMPROJ"],
        ["ENABLE_EMBEDDINGS", "POOLING", "EMBD_NORMALIZE"],
        ["ENABLE_TOOLS", "ENABLE_AGENT", "ENABLE_MCP_PROXY", "EXTRA_ARGS"],
    ]
    for index, group in enumerate(groups):
        if index:
            lines.append("")
        for key in group:
            lines.append(f"{key}={quote_shell_value(merged[key])}")
    lines.append(CONFIG_END)
    return "\n".join(lines) + "\n"

# Host-specific paths the controller cannot resolve for a remote client are sent
# as placeholders; the route-agent swaps them for the real downloaded paths.
LLAMA_PATH_PLACEHOLDER_MODEL = "{{MODEL_PATH}}"

LLAMA_PATH_PLACEHOLDER_MMPROJ = "{{MMPROJ_PATH}}"

LLAMA_PATH_PLACEHOLDER_SPEC = "{{SPEC_PATH}}"

# ── Single source of truth: config dict -> llama-server argument list ────────
# Variant 2 architecture: this is the ONE place that turns the admin form config
# into llama-server flags. Every consumer funnels through it:
#   • local server   -> render_launch_script() generates start-server.sh
#   • server cells    -> render_server_cell_script() (same generator)
#   • remote clients  -> sent over the wire as payload["args"] (with path
#                        placeholders the route-agent substitutes after download)
#   • GUI preview     -> POST /api/llama-command-preview
# Adding a new flag means editing build_llama_args() and nothing else.
def _flag_truthy(value):
    return str(value).strip().lower() in ("1", "true", "yes", "on")

def build_llama_args(config, *, model_path, mmproj_path="", spec_path="",
                     include_local_paths=True):
    """Return the full llama-server argument list (everything AFTER the binary).

    `model_path` / `mmproj_path` / `spec_path` are the values emitted for the
    corresponding flags — real absolute paths for local builds, or placeholders
    for remote builds. Whether a flag is emitted at all is decided from `config`
    (e.g. --mmproj only when MMPROJ_FILE is set), not from the path argument.

    `include_local_paths` controls host-local-only flags (e.g.
    --chat-template-file) that make no sense to ship to a different host.
    """
    c = config if isinstance(config, dict) else {}

    def has(key):
        v = c.get(key)
        return v is not None and str(v).strip() != ""

    truthy = _flag_truthy
    args = [
        "--host", str(c.get("HOST") or "0.0.0.0"),
        "--port", str(c.get("PORT") or 8080),
        "--model", model_path,
    ]
    pairs = [
        ("--ctx-size", "CTX_SIZE"), ("--threads", "THREADS"),
        ("--threads-batch", "THREADS_BATCH"), ("--batch-size", "BATCH_SIZE"),
        ("--ubatch-size", "UBATCH_SIZE"), ("--parallel", "PARALLEL"),
        ("--n-gpu-layers", "N_GPU_LAYERS"),
        ("--cache-type-k", "CACHE_TYPE_K"), ("--cache-type-v", "CACHE_TYPE_V"),
        ("--predict", "N_PREDICT"), ("--keep", "KEEP"),
        ("--cpu-range", "CPU_RANGE"), ("--poll", "POLL"),
        ("--rope-scaling", "ROPE_SCALING"), ("--rope-scale", "ROPE_SCALE"),
        ("--rope-freq-base", "ROPE_FREQ_BASE"), ("--rope-freq-scale", "ROPE_FREQ_SCALE"),
        ("--numa", "NUMA"), ("--device", "DEVICE"),
        ("--split-mode", "SPLIT_MODE"), ("--tensor-split", "TENSOR_SPLIT"),
        ("--main-gpu", "MAIN_GPU"), ("--fit-target", "FIT_TARGET"),
        ("--fit-ctx", "FIT_CTX"), ("--alias", "ALIAS"),
        ("--api-prefix", "API_PREFIX"), ("--timeout", "TIMEOUT"),
        ("--threads-http", "THREADS_HTTP"), ("--cache-reuse", "CACHE_REUSE"),
        ("--cache-ram", "CACHE_RAM"), ("--sleep-idle-seconds", "SLEEP_IDLE_SECONDS"),
        ("--api-key", "API_KEY"),
        ("--image-min-tokens", "IMAGE_MIN_TOKENS"),
        ("--image-max-tokens", "IMAGE_MAX_TOKENS"),
        ("--reasoning", "REASONING"), ("--reasoning-format", "REASONING_FORMAT"),
        ("--reasoning-budget", "REASONING_BUDGET"),
        ("--chat-template", "CHAT_TEMPLATE"),
        ("--pooling", "POOLING"),
        ("--embd-normalize", "EMBD_NORMALIZE"),
    ]
    for flag, key in pairs:
        if has(key):
            args += [flag, str(c[key]).strip()]

    # Chat-template kwargs: merge the raw CHAT_TEMPLATE_KWARGS JSON with the
    # ENABLE_THINKING toggle (off → enable_thinking:false) so reasoning models
    # (gemma-4, Qwen3, …) put the answer in `content`, not `reasoning_content`.
    ctk_raw = str(c.get("CHAT_TEMPLATE_KWARGS") or "").strip()
    think = str(c.get("ENABLE_THINKING") or "").strip().lower()
    ctk = None
    if ctk_raw:
        try:
            _parsed = json.loads(ctk_raw)
            ctk = _parsed if isinstance(_parsed, dict) else None
        except Exception:
            ctk = None
    if think in ("0", "false", "off", "no", "-1"):
        ctk = dict(ctk or {}); ctk["enable_thinking"] = False
    elif think in ("1", "true", "on", "yes"):
        ctk = dict(ctk or {}); ctk["enable_thinking"] = True
    if ctk is not None:
        args += ["--chat-template-kwargs",
                 json.dumps(ctk, ensure_ascii=False, separators=(",", ":"))]
    elif ctk_raw:
        args += ["--chat-template-kwargs", ctk_raw]  # unparseable JSON — pass through

    # Host-local file path — only meaningful on the host that owns the file.
    if include_local_paths and has("CHAT_TEMPLATE_FILE"):
        args += ["--chat-template-file", str(c["CHAT_TEMPLATE_FILE"]).strip()]
    if include_local_paths and has("SSL_CERT_FILE"):
        args += ["--ssl-cert-file", str(c["SSL_CERT_FILE"]).strip()]
    if include_local_paths and has("SSL_KEY_FILE"):
        args += ["--ssl-key-file", str(c["SSL_KEY_FILE"]).strip()]

    if truthy(c.get("CPU_STRICT")):
        args += ["--cpu-strict", "1"]

    def add_bool(key, on, off):
        if has(key):
            args.append(on if truthy(c[key]) else off)

    add_bool("KV_OFFLOAD", "--kv-offload", "--no-kv-offload")
    add_bool("MMAP", "--mmap", "--no-mmap")
    add_bool("CACHE_PROMPT", "--cache-prompt", "--no-cache-prompt")
    add_bool("ENABLE_SLOTS", "--slots", "--no-slots")
    add_bool("SKIP_CHAT_PARSING", "--skip-chat-parsing", "--no-skip-chat-parsing")
    add_bool("REASONING_PRESERVE", "--reasoning-preserve", "--no-reasoning-preserve")
    add_bool("CONTEXT_SHIFT", "--context-shift", "--no-context-shift")
    add_bool("KV_UNIFIED", "--kv-unified", "--no-kv-unified")
    add_bool("CACHE_IDLE_SLOTS", "--cache-idle-slots", "--no-cache-idle-slots")
    add_bool("MMPROJ_AUTO", "--mmproj-auto", "--no-mmproj-auto")

    if has("FIT"):
        args += ["--fit", "on" if truthy(c["FIT"]) else "off"]
    if truthy(c.get("ENABLE_PROPS")):
        args.append("--props")
    if truthy(c.get("ENABLE_CONT_BATCHING")):
        args.append("--cont-batching")
    if truthy(c.get("ENABLE_METRICS")):
        args.append("--metrics")
    if truthy(c.get("ENABLE_MLOCK")):
        args.append("--mlock")
    is_embedding = truthy(c.get("ENABLE_EMBEDDINGS"))
    if is_embedding:
        args.append("--embeddings")

    if has("MMPROJ_FILE"):
        args += ["--mmproj", mmproj_path]
        args.append("--mmproj-offload" if truthy(c.get("OFFLOAD_MMPROJ")) else "--no-mmproj-offload")

    spec_type_raw = str(c.get("SPEC_TYPE") or "").strip().lower()
    if spec_type_raw == "mtp":
        spec_type_raw = "draft-mtp"
    # Speculative decoding (draft / built-in MTP) and chat templates are meaningless
    # for an embeddings server. A SPEC_TYPE=draft-mtp leaked from a chat config makes
    # llama-server abort on a non-MTP model, so drop spec (and --jinja below) when
    # embeddings is on — a safety net independent of what leaked into the config.
    if is_embedding:
        spec_type_raw = ""
    if has("SPEC_DRAFT_MODEL_FILE") and not is_embedding:
        spec_type = spec_type_raw or "draft-mtp"
        if spec_type and spec_type != "none":
            args += ["--spec-type", spec_type, "--model-draft", spec_path]
            draft_gpu = str(c.get("SPEC_DRAFT_N_GPU_LAYERS") or "999").strip()
            draft_max = str(c.get("SPEC_DRAFT_N_MAX") or "").strip()
            draft_min = str(c.get("SPEC_DRAFT_N_MIN") or "").strip()
            if draft_gpu:
                args += ["--gpu-layers-draft", draft_gpu]
            if draft_max:
                args += ["--spec-draft-n-max", draft_max]
            if draft_min:
                args += ["--spec-draft-n-min", draft_min]
    elif spec_type_raw == "draft-mtp":
        draft_max = str(c.get("SPEC_DRAFT_N_MAX") or "2").strip()
        draft_min = str(c.get("SPEC_DRAFT_N_MIN") or "").strip()
        args += ["--spec-type", "draft-mtp"]
        if draft_max:
            args += ["--spec-draft-n-max", draft_max]
        if draft_min:
            args += ["--spec-draft-n-min", draft_min]

    if truthy(c.get("ENABLE_JINJA")) and not is_embedding:
        args.append("--jinja")
    if truthy(c.get("ENABLE_FLASH_ATTN")):
        args += ["--flash-attn", "on"]
    if not truthy(c.get("ENABLE_WEBUI")):
        args.append("--no-webui")

    # Built-in WebUI tools / MCP proxy (recent llama-server features).
    if truthy(c.get("ENABLE_TOOLS")):
        args += ["--tools", "all"]
    if truthy(c.get("ENABLE_AGENT")):
        args.append("--agent")
    if truthy(c.get("ENABLE_MCP_PROXY")):
        args.append("--ui-mcp-proxy")

    # Fallback: raw extra flags typed in the admin UI, appended verbatim.
    if has("EXTRA_ARGS"):
        try:
            args += shlex.split(str(c["EXTRA_ARGS"]))
        except ValueError:
            args += str(c["EXTRA_ARGS"]).split()
    return args

# ── EXTRA_ARGS -> form fields (inverse of build_llama_args) ───────────────────
# When a user pastes raw llama-server flags into EXTRA_ARGS, recognize the ones
# that have a dedicated form field and hoist them into that field, leaving only
# truly-extra flags behind. Keep this table in sync with build_llama_args.
# Value flags (consume the next token). Short aliases included.
_EXTRA_VALUE_FLAGS = {
    "--ctx-size": "CTX_SIZE", "-c": "CTX_SIZE",
    "--threads": "THREADS", "-t": "THREADS",
    "--threads-batch": "THREADS_BATCH", "-tb": "THREADS_BATCH",
    "--batch-size": "BATCH_SIZE", "-b": "BATCH_SIZE",
    "--ubatch-size": "UBATCH_SIZE", "-ub": "UBATCH_SIZE",
    "--parallel": "PARALLEL", "-np": "PARALLEL",
    "--n-gpu-layers": "N_GPU_LAYERS", "-ngl": "N_GPU_LAYERS", "--gpu-layers": "N_GPU_LAYERS",
    "--cache-type-k": "CACHE_TYPE_K", "-ctk": "CACHE_TYPE_K",
    "--cache-type-v": "CACHE_TYPE_V", "-ctv": "CACHE_TYPE_V",
    "--predict": "N_PREDICT", "-n": "N_PREDICT", "--n-predict": "N_PREDICT",
    "--keep": "KEEP", "--cpu-range": "CPU_RANGE", "--poll": "POLL",
    "--rope-scaling": "ROPE_SCALING", "--rope-scale": "ROPE_SCALE",
    "--rope-freq-base": "ROPE_FREQ_BASE", "--rope-freq-scale": "ROPE_FREQ_SCALE",
    "--numa": "NUMA", "--device": "DEVICE", "-dev": "DEVICE",
    "--split-mode": "SPLIT_MODE", "-sm": "SPLIT_MODE",
    "--tensor-split": "TENSOR_SPLIT", "-ts": "TENSOR_SPLIT",
    "--main-gpu": "MAIN_GPU", "-mg": "MAIN_GPU",
    "--fit-target": "FIT_TARGET", "--fit-ctx": "FIT_CTX",
    "--alias": "ALIAS", "-a": "ALIAS", "--api-prefix": "API_PREFIX",
    "--timeout": "TIMEOUT", "--threads-http": "THREADS_HTTP", "--cache-reuse": "CACHE_REUSE", "--cache-ram": "CACHE_RAM", "-cram": "CACHE_RAM",
    "--sleep-idle-seconds": "SLEEP_IDLE_SECONDS", "--api-key": "API_KEY",
    "--ssl-cert-file": "SSL_CERT_FILE", "--ssl-key-file": "SSL_KEY_FILE",
    "--image-min-tokens": "IMAGE_MIN_TOKENS", "--image-max-tokens": "IMAGE_MAX_TOKENS",
    "--reasoning": "REASONING", "--reasoning-format": "REASONING_FORMAT",
    "--reasoning-budget": "REASONING_BUDGET",
    "--chat-template": "CHAT_TEMPLATE", "--chat-template-kwargs": "CHAT_TEMPLATE_KWARGS",
    "--pooling": "POOLING", "--embd-normalize": "EMBD_NORMALIZE",
    "--host": "HOST", "--port": "PORT",
}

# Flags taking an optional on/off/auto value; bare flag => on ("1").
_EXTRA_ONOFF_FLAGS = {
    "--flash-attn": "ENABLE_FLASH_ATTN", "-fa": "ENABLE_FLASH_ATTN",
    "--fit": "FIT", "--cpu-strict": "CPU_STRICT",
}

# --x => "1", --no-x => "0".
_EXTRA_PAIR_BOOL = {
    "--mmap": ("MMAP", "1"), "--no-mmap": ("MMAP", "0"),
    "--kv-offload": ("KV_OFFLOAD", "1"), "--no-kv-offload": ("KV_OFFLOAD", "0"),
    "--cache-prompt": ("CACHE_PROMPT", "1"), "--no-cache-prompt": ("CACHE_PROMPT", "0"),
    "--slots": ("ENABLE_SLOTS", "1"), "--no-slots": ("ENABLE_SLOTS", "0"),
    "--skip-chat-parsing": ("SKIP_CHAT_PARSING", "1"), "--no-skip-chat-parsing": ("SKIP_CHAT_PARSING", "0"),
    "--reasoning-preserve": ("REASONING_PRESERVE", "1"), "--no-reasoning-preserve": ("REASONING_PRESERVE", "0"),
    "--context-shift": ("CONTEXT_SHIFT", "1"), "--no-context-shift": ("CONTEXT_SHIFT", "0"),
    "--kv-unified": ("KV_UNIFIED", "1"), "--no-kv-unified": ("KV_UNIFIED", "0"),
    "--cache-idle-slots": ("CACHE_IDLE_SLOTS", "1"), "--no-cache-idle-slots": ("CACHE_IDLE_SLOTS", "0"),
    "--mmproj-auto": ("MMPROJ_AUTO", "1"), "--no-mmproj-auto": ("MMPROJ_AUTO", "0"),
    "--mmproj-offload": ("OFFLOAD_MMPROJ", "1"), "--no-mmproj-offload": ("OFFLOAD_MMPROJ", "0"),
    "--cont-batching": ("ENABLE_CONT_BATCHING", "1"), "-cb": ("ENABLE_CONT_BATCHING", "1"),
    "--no-cont-batching": ("ENABLE_CONT_BATCHING", "0"),
    "--webui": ("ENABLE_WEBUI", "1"), "--no-webui": ("ENABLE_WEBUI", "0"),
}

# Presence => "1".
_EXTRA_FLAG_ON = {
    "--props": "ENABLE_PROPS", "--metrics": "ENABLE_METRICS", "--mlock": "ENABLE_MLOCK",
    "--embeddings": "ENABLE_EMBEDDINGS", "--embedding": "ENABLE_EMBEDDINGS",
    "--jinja": "ENABLE_JINJA", "--agent": "ENABLE_AGENT", "--ui-mcp-proxy": "ENABLE_MCP_PROXY",
}

_EXTRA_ONOFF_TRUE = {"on", "auto", "1", "true", "yes", "enabled"}

def parse_extra_args(text):
    """Split a raw EXTRA_ARGS string into recognized form fields + leftover flags.

    Returns {"recognized": {FIELD: value}, "remaining": "<unrecognized flags>"}.
    Model / projector / draft / chat-template-file path flags are intentionally
    NOT hoisted (they map to selects + companion toggles) and stay in remaining.
    """
    try:
        tokens = shlex.split(str(text or ""))
    except ValueError:
        tokens = str(text or "").split()
    recognized = {}
    remaining = []
    i = 0
    n = len(tokens)
    while i < n:
        tok = tokens[i]
        nxt = tokens[i + 1] if i + 1 < n else None
        if tok in _EXTRA_VALUE_FLAGS and nxt is not None and not nxt.startswith("-"):
            recognized[_EXTRA_VALUE_FLAGS[tok]] = nxt
            i += 2
            continue
        if tok in _EXTRA_ONOFF_FLAGS:
            field = _EXTRA_ONOFF_FLAGS[tok]
            if nxt is not None and nxt.lower() in (_EXTRA_ONOFF_TRUE | {"off", "0", "false", "no", "disabled"}):
                recognized[field] = "1" if nxt.lower() in _EXTRA_ONOFF_TRUE else "0"
                i += 2
            else:
                recognized[field] = "1"
                i += 1
            continue
        if tok in _EXTRA_PAIR_BOOL:
            field, val = _EXTRA_PAIR_BOOL[tok]
            recognized[field] = val
            i += 1
            continue
        if tok in _EXTRA_FLAG_ON:
            recognized[_EXTRA_FLAG_ON[tok]] = "1"
            i += 1
            continue
        if tok == "--tools" and nxt == "all":
            recognized["ENABLE_TOOLS"] = "1"
            i += 2
            continue
        remaining.append(tok)
        i += 1
    remaining_str = " ".join(
        shlex.quote(t) if (" " in t or '"' in t or "'" in t) else t for t in remaining
    )
    return {"recognized": recognized, "remaining": remaining_str}

def build_remote_llama_args(config):
    """Argument list for a remote client: host-local paths become placeholders
    the route-agent substitutes after it downloads the files locally."""
    return build_llama_args(
        config,
        model_path=LLAMA_PATH_PLACEHOLDER_MODEL,
        mmproj_path=LLAMA_PATH_PLACEHOLDER_MMPROJ,
        spec_path=LLAMA_PATH_PLACEHOLDER_SPEC,
        include_local_paths=False,
    )

def _join_models_path(models_dir, rel):
    rel = str(rel or "").strip()
    if not rel:
        return ""
    return f"{str(models_dir).rstrip('/')}/{rel}"

def build_local_llama_command(config, *, llama_home=None):
    """[binary, *args] for a server running on THIS controller host, with all
    paths resolved to real absolute locations."""
    merged = {key: str(config.get(key, "")).strip() for key in CONFIG_FIELDS}
    models_dir = merged.get("LLAMA_MODELS_DIR") or str(DEFAULT_MODELS_DIR)
    home = str(llama_home or LLAMA_HOME)
    model_abs = _join_models_path(models_dir, merged.get("MODEL_FILE"))
    mmproj_abs = _join_models_path(models_dir, merged.get("MMPROJ_FILE"))
    spec_abs = _join_models_path(models_dir, merged.get("SPEC_DRAFT_MODEL_FILE"))
    args = build_llama_args(merged, model_path=model_abs, mmproj_path=mmproj_abs,
                            spec_path=spec_abs, include_local_paths=True)
    return [f"{home.rstrip('/')}/build/bin/llama-server", *args]

def is_command_cell(config):
    """True when a cell runs a generic managed command instead of llama-server."""
    return runner_id(config) == "custom"

def models_dir_from_config(config):
    return Path(config.get("LLAMA_MODELS_DIR") or str(DEFAULT_MODELS_DIR)).expanduser()
