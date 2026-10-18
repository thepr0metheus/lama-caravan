#!/bin/bash
# LFM2.5-Audio cell launcher (self-installing, CARAVAN command-cell ready): Liquid AI's 1.5B audio model, and it
# SPEAKS — text to speech, a spoken answer to a spoken question, speech to text. English only.
# Usage: run_lfm_audio.sh [port] [model-dir] [--install-only]
#   model-dir  the checkpoint folder of the models library, as the /hf page lays it out
#              (model.safetensors and audio_detokenizer/): LiquidAI/LFM2.5-Audio-1.5B.
#              Default: $LFM_MODEL_DIR, else $LLAMA_MODELS_DIR/LFM2.5-Audio-1.5B/LiquidAI/SAFETENSORS
#   --install-only  makes the venv, then exits (a first start downloads the package's locked torch: minutes).
#
# Why a venv of its own, from Liquid's own lock (uv sync --frozen): the package pins torch and torchaudio 2.8.0
# (CUDA 12.8 wheels, which carry the kernels of an RTX 5090) and transformers 4.56.1. torchaudio ends at 2.11, is
# imported by the package and pins no torch: a venv with another torch (vLLM's 2.13) breaks it. The `[demo]` extra
# is left out: its locked `av` builds from source and needs ffmpeg and opus headers. The cell server needs
# only the standard library besides the package (cells/lfm_audio_server.py).
set -euo pipefail

# The flag may stand anywhere: it is taken out first, and what is left is [port] [model-dir].
INSTALL_ONLY=""
ARGS=()
for arg in "$@"; do
  if [ "$arg" = "--install-only" ]; then INSTALL_ONLY=1; else ARGS+=("$arg"); fi
done
PORT="${ARGS[0]:-8031}"
MODEL_DIR="${ARGS[1]:-${LFM_MODEL_DIR:-${LLAMA_MODELS_DIR:-/mnt/lama-caravan-models}/LFM2.5-Audio-1.5B/LiquidAI/SAFETENSORS}}"

TAG="v1.3.0"
ROOT="${LFM_HOME:-$HOME/lfm25}"
SRC="$ROOT/liquid-audio"
VENV="$SRC/.venv"
export PATH="$HOME/.local/bin:$PATH"

say() { echo "lfm-audio: $*"; }

# The marker is written when the sync is DONE, not when the venv exists: a first start that stopped halfway (the
# network, a full disk) leaves a venv with a python in it and half the packages — the next start must finish the job.
if [ ! -f "$VENV/.synced" ]; then
  command -v uv >/dev/null 2>&1 || { say "uv is not installed: the package's lock is installed with it (https://docs.astral.sh/uv/)" >&2; exit 1; }
  say "creating the venv $VENV (first start on this machine: several minutes)"
  mkdir -p "$ROOT"
  [ -d "$SRC/.git" ] || git clone -q --depth 1 --branch "$TAG" https://github.com/Liquid4All/liquid-audio.git "$SRC"
  (cd "$SRC" && uv sync --frozen --no-dev)
  touch "$VENV/.synced"
fi

if [ -n "$INSTALL_ONLY" ]; then
  say "ready (install-only): venv $VENV"
  exit 0
fi

HERE="$(cd "$(dirname "$0")" && pwd)"
SERVER="$HERE/lfm_audio_server.py"
[ -f "$SERVER" ] || SERVER="$HOME/lfm_audio_server.py"
[ -f "$SERVER" ] || { say "lfm_audio_server.py is not next to this launcher" >&2; exit 1; }
say "serving on port $PORT: weights from $MODEL_DIR"
exec "$VENV/bin/python" "$SERVER" "$PORT" "$MODEL_DIR"
