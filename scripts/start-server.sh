#!/usr/bin/env bash
set -euo pipefail

LLAMA_HOME="$HOME/llama.cpp"
export LD_LIBRARY_PATH="$LLAMA_HOME/build/bin:$LLAMA_HOME/build/lib:${LD_LIBRARY_PATH:-}"
export PATH="$LLAMA_HOME/build/bin:$PATH"

# BEGIN LLAMA CONFIG
HOST="0.0.0.0"
PORT="8080"

LLAMA_MODELS_DIR="$HOME/llama.cpp/models"
MODEL_FILE="gemma-4-31b-it/bartowski/q4-k-m/google_gemma-4-31B-it-Q4_K_M.gguf"
MMPROJ_FILE="gemma-4-31b-it/bartowski/mmproj-BF16.gguf"

SPEC_TYPE="draft-mtp"
SPEC_DRAFT_MODEL_FILE="gemma-4-31b-it/mtp/gemma-4-31B-it-MTP-Q8_0.gguf"
SPEC_DRAFT_N_GPU_LAYERS="999"
SPEC_DRAFT_N_MAX="16"
SPEC_DRAFT_N_MIN="0"
SPEC_DRAFT_CACHE_TYPE_K="q8_0"
SPEC_DRAFT_CACHE_TYPE_V="q8_0"

CTX_SIZE="100000"
THREADS="8"
THREADS_BATCH="8"
BATCH_SIZE="1024"
UBATCH_SIZE="1024"
PARALLEL="1"
N_GPU_LAYERS="999"
CACHE_TYPE_K="q8_0"
CACHE_TYPE_V="q8_0"

N_PREDICT=""
KEEP=""
CPU_RANGE=""
CPU_STRICT=""
POLL=""
ROPE_SCALING=""
ROPE_SCALE=""
ROPE_FREQ_BASE=""
ROPE_FREQ_SCALE=""

KV_OFFLOAD=""
MMAP=""
NUMA=""
DEVICE=""
SPLIT_MODE=""
TENSOR_SPLIT=""
MAIN_GPU=""
FIT=""
FIT_TARGET=""
FIT_CTX=""

ALIAS=""
API_PREFIX=""
TIMEOUT=""
THREADS_HTTP=""
CACHE_PROMPT=""
CACHE_REUSE=""
ENABLE_PROPS=""
ENABLE_SLOTS=""

IMAGE_MIN_TOKENS=""
IMAGE_MAX_TOKENS=""
REASONING=""
REASONING_FORMAT=""
REASONING_BUDGET=""
CHAT_TEMPLATE=""
CHAT_TEMPLATE_FILE=""
CHAT_TEMPLATE_KWARGS=""
SKIP_CHAT_PARSING=""

ENABLE_JINJA="1"
ENABLE_FLASH_ATTN="1"
ENABLE_MLOCK="1"
ENABLE_METRICS="1"
ENABLE_CONT_BATCHING="1"
ENABLE_WEBUI="1"
OFFLOAD_MMPROJ="1"

ENABLE_TOOLS=""
ENABLE_AGENT=""
ENABLE_MCP_PROXY=""
EXTRA_ARGS=""
# END LLAMA CONFIG

# BEGIN LLAMA COMMAND — generated from the config above by the admin UI; edit via the UI, not by hand
[ -f $HOME/llama.cpp/models/gemma-4-31b-it/bartowski/q4-k-m/google_gemma-4-31B-it-Q4_K_M.gguf ] || { echo "Model not found: $HOME/llama.cpp/models/gemma-4-31b-it/bartowski/q4-k-m/google_gemma-4-31B-it-Q4_K_M.gguf" >&2; exit 1; }
[ -f $HOME/llama.cpp/models/gemma-4-31b-it/bartowski/mmproj-BF16.gguf ] || { echo "MMProj not found: $HOME/llama.cpp/models/gemma-4-31b-it/bartowski/mmproj-BF16.gguf" >&2; exit 1; }
[ -f $HOME/llama.cpp/models/gemma-4-31b-it/mtp/gemma-4-31B-it-MTP-Q8_0.gguf ] || { echo "Spec draft not found: $HOME/llama.cpp/models/gemma-4-31b-it/mtp/gemma-4-31B-it-MTP-Q8_0.gguf" >&2; exit 1; }
exec "$LLAMA_HOME/build/bin/llama-server" --host 0.0.0.0 --port 8080 --model $HOME/llama.cpp/models/gemma-4-31b-it/bartowski/q4-k-m/google_gemma-4-31B-it-Q4_K_M.gguf --ctx-size 100000 --threads 8 --threads-batch 8 --batch-size 1024 --ubatch-size 1024 --parallel 1 --n-gpu-layers 999 --cache-type-k q8_0 --cache-type-v q8_0 --cont-batching --metrics --mlock --mmproj $HOME/llama.cpp/models/gemma-4-31b-it/bartowski/mmproj-BF16.gguf --mmproj-offload --spec-type draft-mtp --model-draft $HOME/llama.cpp/models/gemma-4-31b-it/mtp/gemma-4-31B-it-MTP-Q8_0.gguf --gpu-layers-draft 999 --spec-draft-n-max 16 --spec-draft-n-min 0 --jinja --flash-attn on "$@"
# END LLAMA COMMAND
