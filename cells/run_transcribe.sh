#!/bin/bash
# transcribe.cpp cell launcher (CARAVAN command-cell ready).
# Usage: run_transcribe.sh [port] [model.gguf]
#
# One engine, many model families — GigaAM, Parakeet, Canary, Whisper, Qwen3-ASR
# and more, picked by which .gguf you pass. That is why the caravan drives this
# runner with its ordinary MODEL_FILE picker: an ASR GGUF downloads through the
# same HF browser as a llama one.
#
# The heavy part (building libtranscribe with CUDA/Metal and installing the
# Python binding) lives in scripts/install-transcribe.sh, exactly as the llama
# and moonshine cells split install from launch. This script only runs.
set -e
PORT="${1:-8030}"
MODEL="${2:-}"
VENV="${VENV:-$HOME/transcribe-venv}"
LIB="${TRANSCRIBE_LIBRARY:-$HOME/transcribe.cpp/build/src/libtranscribe.so}"

if [ -z "$MODEL" ]; then
  echo "transcribe: no model given — usage: run_transcribe.sh <port> <model.gguf>" >&2
  exit 2
fi
if [ ! -x "$VENV/bin/python" ]; then
  echo "transcribe: venv missing at $VENV — run scripts/install-transcribe.sh first" >&2
  exit 3
fi
# macOS builds a .dylib; fall back before failing so the Mac client works too.
if [ ! -f "$LIB" ] && [ -f "${LIB%.so}.dylib" ]; then
  LIB="${LIB%.so}.dylib"
fi
if [ ! -f "$LIB" ]; then
  echo "transcribe: libtranscribe not found at $LIB — run scripts/install-transcribe.sh" >&2
  exit 4
fi

HERE="$(cd "$(dirname "$0")" && pwd)"
SERVER="$HERE/transcribe_server.py"
[ -f "$SERVER" ] || SERVER="$HOME/transcribe_server.py"

export TRANSCRIBE_LIBRARY="$LIB"
exec "$VENV/bin/python" "$SERVER" "$PORT" "$MODEL"
