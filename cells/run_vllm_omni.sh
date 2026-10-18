#!/bin/bash
# vLLM-Omni voice cell launcher (self-installing, for a CARAVAN command cell): models that ANSWER IN A VOICE through
# vLLM's OpenAI API. POST /v1/chat/completions with "modalities":["text","audio"] returns the answer's text in
# message.content and a base64 wav (24 kHz, mono) in message.audio.data. The llama.cpp and vLLM cells of the caravan
# answer in text only; these have a speech decoder behind the language model, and vLLM-Omni runs both as stages.
#
# Usage: run_vllm_omni.sh <port> <recipe> <model-dir> [--install-only]
#   recipe     step-audio2  stepfun-ai/Step-Audio-2-mini. A spoken question in, a spoken answer out. English and
#                           Chinese. About 25 GiB of the card.
#              qwen3-omni   Qwen3-Omni-30B-A3B-Instruct as the AWQ 4-bit checkpoint of cyankiwi (the speech stages
#                           stay bf16). Text, speech, images in; speech out in 10 languages, Russian among them.
#                           About 30 GiB: the WHOLE card, and no other cell may hold GPU memory while it runs.
#   model-dir  the checkpoint folder of the models library, as the /hf page lays it out
#   --install-only  makes the venv and the deploy file, then exits (a first start downloads about 9 GB: minutes)
#
# One venv per recipe ($OMNI_VENV, else $HOME/venvs/omni-<recipe>): the step-audio2 package puts modules with the generic
# names `utils` and `token2wav` into site-packages, which a second model's imports must not meet.
#
# Why the odd bits, each a defect that was paid for (2026-10-15):
#  * PATH carries the venv's bin: FlashInfer compiles its sampling kernels at the first start with `ninja`, which lives
#    there; without it the engine dies at its warm-up with FileNotFoundError: 'ninja'.
#  * The deploy file is written at EVERY start from this script: the file the engine reads can never be older than the
#    launcher. The default files of vLLM-Omni put the stages on two cards (2 x H100); here all stages share device 0 and
#    the budgets add up to what one RTX 5090 (32 GB) holds.
#  * The engine gives up on its own start after 600 s in total (--init-timeout) and 300 s per stage. A 26 GB checkpoint
#    read from a NAS at 20-50 MB/s needs 8-20 minutes: the first start of Qwen3-Omni died at 600 s with the weights still
#    arriving. The limits here are 40 and 30 minutes; the page cache makes the next start fast.
#  * Step-Audio's second stage (Token2Wav) loads its models at the FIRST request, not at start: /health answers 200
#    before that. The first spoken answer takes about a minute; the next ones take seconds.
#  * The checkpoint of Step-Audio 2 mini has a `token2wav/` folder (.pt and .onnx files) which the /hf page's plan leaves
#    out. Without it the engine starts and fails at the first request. The launcher links the library's files into a folder
#    of its own and fetches that one folder, at the commit this recipe was proven on.
set -euo pipefail

# The flag may stand anywhere: it is taken out first, and what is left is <port> <recipe> <model-dir>.
INSTALL_ONLY=""
ARGS=()
for arg in "$@"; do
  if [ "$arg" = "--install-only" ]; then INSTALL_ONLY=1; else ARGS+=("$arg"); fi
done
PORT="${ARGS[0]:-}"
RECIPE="${ARGS[1]:-}"
MODEL_DIR="${ARGS[2]:-}"

say() { echo "vllm-omni: $*"; }
die() { echo "vllm-omni: $*" >&2; exit "${2:-1}"; }

[ -n "$PORT" ] && [ -n "$RECIPE" ] && [ -n "$MODEL_DIR" ] || die "usage: run_vllm_omni.sh <port> <step-audio2|qwen3-omni> <model-dir> [--install-only]" 2

OMNI_HOME="${OMNI_HOME:-$HOME/omni}"
VENV="${OMNI_VENV:-$HOME/venvs/omni-$RECIPE}"
export PATH="$HOME/.local/bin:$PATH"

yaml_step_audio2() {
  cat <<'YAML'
async_chunk: true
trust_remote_code: true
enable_prefix_caching: false
stages:
  - stage_id: 0
    devices: "0"
    tensor_parallel_size: 1
    max_num_seqs: 1
    gpu_memory_utilization: 0.60
    enforce_eager: true
    async_scheduling: false
    max_num_batched_tokens: 1024
    default_sampling_params: {temperature: 0.7, top_p: 0.9, top_k: -1, max_tokens: 1024, seed: 42, repetition_penalty: 1.05}
  - stage_id: 1
    devices: "0"
    max_num_seqs: 1
    gpu_memory_utilization: 0.25
    enforce_eager: true
    async_scheduling: false
    max_num_batched_tokens: 2048
    hf_overrides: {architectures: ["StepAudio2Token2WavForConditionalGeneration"]}
    default_sampling_params: {temperature: 0.0, top_p: 1.0, top_k: -1, max_tokens: 1, seed: 42}
YAML
}

yaml_qwen3_omni() {
  cat <<'YAML'
# Three stages on ONE card: the thinker (the language model, MoE on Marlin), the talker (speech codes), code2wav (the
# vocoder). Budgets are shares of the card and add up to 0.92. The first audio frame leaves after 1 codec frame, not 4.
async_chunk: true
connectors:
  connector_of_shared_memory:
    name: SharedMemoryConnector
    extra:
      initial_codec_chunk_frames: 1
      codec_chunk_frames: 25
      codec_left_context_frames: 25
stages:
  - stage_id: 0
    max_num_batched_tokens: 4096
    max_model_len: 4096
    max_num_seqs: 2
    gpu_memory_utilization: 0.655
    moe_backend: marlin
    trust_remote_code: true
    enable_prefix_caching: false
    devices: "0"
    default_sampling_params: {temperature: 0.0, max_tokens: 2048}
  - stage_id: 1
    max_num_batched_tokens: 8192
    max_model_len: 8192
    max_num_seqs: 2
    gpu_memory_utilization: 0.225
    moe_backend: triton
    trust_remote_code: true
    enable_prefix_caching: false
    devices: "0"
    input_connectors:
      from_stage_0: connector_of_shared_memory
    default_sampling_params: {seed: 42, temperature: 0.9, top_k: 50, max_tokens: 4096, repetition_penalty: 1.05}
  - stage_id: 2
    max_num_batched_tokens: 8192
    max_model_len: 8192
    max_num_seqs: 1
    gpu_memory_utilization: 0.04
    enforce_eager: true
    trust_remote_code: true
    enable_prefix_caching: false
    enable_chunked_prefill: false
    async_scheduling: false
    devices: "0"
    input_connectors:
      from_stage_1: connector_of_shared_memory
    default_sampling_params: {temperature: 0.0, top_p: 1.0, top_k: -1, max_tokens: 65536, repetition_penalty: 1.1}
# CUDA graphs for a short prompt's prefill (with 2 sequences the default captures up to 4 tokens only).
platforms:
  cuda:
    stages:
      - stage_id: 0
        compilation_config:
          custom_ops: ["+rotary_embedding"]
          cudagraph_capture_sizes: [1, 2, 4, 8, 16, 32, 48, 64]
      - stage_id: 1
        compilation_config:
          cudagraph_capture_sizes: [1, 2, 4, 8, 16, 32, 48, 64]
YAML
}

case "$RECIPE" in
  step-audio2)
    NAME="stepfun-ai/Step-Audio-2-mini"
    PACKAGES="vllm==0.30.0 vllm-omni==0.30.0 step-audio2==1.0.0"
    SERVE_FLAGS="--enforce-eager"
    TOKEN2WAV_COMMIT="e36fdd5d71e0ea22f09dd94bbab9bfc544ca1e36"
    ;;
  qwen3-omni)
    NAME="qwen3-omni"
    PACKAGES="vllm==0.30.0 vllm-omni==0.30.0"
    SERVE_FLAGS=""
    export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
    ;;
  *) die "unknown recipe '$RECIPE': step-audio2 or qwen3-omni" 2 ;;
esac

[ -f "$MODEL_DIR/config.json" ] || die "$MODEL_DIR/config.json is missing: download the model on the /hf page first"
compgen -G "$MODEL_DIR/*.safetensors" >/dev/null || die "$MODEL_DIR holds no .safetensors weights: download the model on the /hf page first"

# The marker is written when the install is DONE, not when the venv exists: a first start that stopped halfway (the
# network, a full disk) must not read as installed — the next start would skip the work and fail at its first import.
# One marker per recipe: two recipes that share a venv through $OMNI_VENV do not share what each of them needs.
if [ ! -f "$VENV/.installed-$RECIPE" ]; then
  command -v uv >/dev/null 2>&1 || die "uv is not installed: vLLM's wheels are installed with it (https://docs.astral.sh/uv/)"
  say "installing $PACKAGES into $VENV (first start on this machine: several minutes)"
  [ -x "$VENV/bin/python" ] || uv venv --python 3.12 --seed "$VENV"
  # shellcheck disable=SC2086
  uv pip install --python "$VENV/bin/python" $PACKAGES
  touch "$VENV/.installed-$RECIPE"
fi

mkdir -p "$OMNI_HOME"
YAML="$OMNI_HOME/$RECIPE.yaml"
"yaml_${RECIPE//-/_}" > "$YAML"

SERVE_DIR="$MODEL_DIR"
if [ "$RECIPE" = "step-audio2" ] && [ ! -d "$MODEL_DIR/token2wav" ]; then
  SERVE_DIR="$OMNI_HOME/step-audio2-model"
  mkdir -p "$SERVE_DIR"
  for f in "$MODEL_DIR"/*; do ln -sfn "$f" "$SERVE_DIR/${f##*/}"; done
  if [ ! -d "$SERVE_DIR/token2wav" ]; then
    say "token2wav/ is not in the library's folder: fetching it (1.2 GB) into $SERVE_DIR"
    "$VENV/bin/python" - "$SERVE_DIR" "$TOKEN2WAV_COMMIT" <<'PY'
import sys
from huggingface_hub import snapshot_download
snapshot_download("stepfun-ai/Step-Audio-2-mini", revision=sys.argv[2], allow_patterns=["token2wav/*"], local_dir=sys.argv[1])
PY
  fi
fi

if [ -n "$INSTALL_ONLY" ]; then
  say "ready (install-only): venv $VENV, deploy file $YAML, model $SERVE_DIR"
  exit 0
fi

say "serving $NAME on port $PORT: weights from $SERVE_DIR"
export PATH="$VENV/bin:$PATH" VLLM_WORKER_MULTIPROC_METHOD=spawn MAX_JOBS="${MAX_JOBS:-4}"
cd "$OMNI_HOME"
# shellcheck disable=SC2086
exec vllm serve "$SERVE_DIR" --omni --served-model-name "$NAME" --host 0.0.0.0 --port "$PORT" \
    --stage-init-timeout 1800 --init-timeout 2400 --trust-remote-code $SERVE_FLAGS --deploy-config "$YAML"
