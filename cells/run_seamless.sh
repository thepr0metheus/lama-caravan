#!/bin/bash
# SeamlessM4T v2 cell launcher (self-installing, CARAVAN command-cell ready).
# Speech in one language -> TEXT in another, in one model: EN audio in, RU text
# out, with no English transcript in between.
#
# Usage: run_seamless.sh <port> <model_dir> [target_lang] [--install-only]
#        model_dir:   the downloaded HF folder (config.json + safetensors)
#        target_lang: ISO 639-3, e.g. rus eng deu fra spa — default rus
#
#     bash run_seamless.sh 22030 ~/llama.cpp/models/seamless-m4t-v2-large/facebook/FP32 rus
#
# LICENCE: the weights are CC-BY-NC-4.0 — non-commercial use only. That is
# unlike whisper (MIT) and GigaAM, and it is a property of the model, not of
# this script.
set -e
PORT="${1:-22030}"
MODEL_DIR="${2:-}"
TGT="${3:-rus}"
VENV="${VENV:-$HOME/seamless-venv}"

# Its own venv, deliberately. The box's vllm-venv already holds a working torch,
# and adding this model's dependencies to it would put a running production cell
# one pip resolution away from breaking.
if [ ! -x "$VENV/bin/python" ]; then
  echo "seamless: creating venv $VENV …"
  python3 -m venv "$VENV"
  "$VENV/bin/pip" -q install -U pip
  # cu128 wheels cover Blackwell (sm_120); on a CPU-only host pip falls back to
  # the CPU build of the same version.
  "$VENV/bin/pip" install torch --index-url https://download.pytorch.org/whl/cu128 \
    || "$VENV/bin/pip" install torch
  "$VENV/bin/pip" install "transformers>=4.36" sentencepiece protobuf numpy
fi

SERVER=""
for cand in "$(dirname "$0")/seamless_server.py" "$HOME/seamless_server.py"; do
  [ -f "$cand" ] && SERVER="$cand" && break
done
if [ -z "$SERVER" ]; then
  echo "seamless: seamless_server.py not found beside the launcher or in \$HOME" >&2
  exit 1
fi

if [ "${4:-}" = "--install-only" ] || [ "${3:-}" = "--install-only" ]; then
  echo "seamless: venv ready at $VENV"
  exit 0
fi

if [ -z "$MODEL_DIR" ]; then
  echo "seamless: a model directory is required (download it from the HF browser)" >&2
  exit 1
fi

exec "$VENV/bin/python" "$SERVER" "$PORT" "$MODEL_DIR" "$TGT"
