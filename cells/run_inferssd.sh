#!/bin/bash
# InferSSD cell launcher: wici-ai's fork of llama.cpp's server, which reads a MoE model's experts from an SSD
# (io_uring) and keeps the most used ones in RAM and on the card (Apache-2.0). Self-installing, for a CARAVAN cell.
#
# Usage: run_inferssd.sh [port] [--context N] [--install-only] <model-file>
#   model-file  the first GGUF part of the model, on the machine's fast disk: the runner keeps its models in the
#               folder for Strata's files, and the scout copies every part of the library's model there first.
#   --context   the context window in tokens (default 32768).
#   --install-only  builds the engine, then exits (the first build takes 2–12 minutes).
#
# What the first start does, once: the source of wici-ai/inferssd at ONE pinned commit (its tag v0.1.1), a venv
# with its framework, cmake and ninja, and the CUDA build of its server and probes. That is what its own
# install.sh does; here the commit is checked, and the install is marked done only when it is done (a first
# start that stopped halfway is built again by the next, not taken for an installed engine).
#
# Why the environment below, each a fact of its v0.1.1 launcher (framework/src/inferssd/launch/linux.py):
#  * It listens on 127.0.0.1 unless LLAMA_SERVER_HOST says otherwise, and 127.0.0.1 is where every cell listens: the scout
#    reaches it there (rules::CellDoor::LISTEN).
#  * It refuses to start while ANY card runs a compute process, unless VRAM_RESERVE_MIB is set. On a machine of two
#    cards the other card's cells are no business of this one, and the scout has already checked this cell's card.
#  * It sizes its card by the FIRST card nvidia-smi lists, whichever card CUDA_VISIBLE_DEVICES gives it.
#  * Its prompt cache goes to ~/.cache unless PROMPT_CACHE_DIR says otherwise; it belongs on the model's disk.
#  * It runs the server in a systemd user scope with a memory limit: the scout's user needs a user manager
#    (linger) and cgroup v2 with the memory controller delegated, which Ubuntu 24.04 gives by default.
set -euo pipefail

INSTALL_ONLY=""
CONTEXT=32768
ARGS=()
while [ "$#" -gt 0 ]; do
  case "$1" in
    --install-only) INSTALL_ONLY=1 ;;
    --context)
      [ "$#" -ge 2 ] || { echo "inferssd: --context needs a number of tokens" >&2; exit 2; }
      CONTEXT="$2"
      shift
      ;;
    *) ARGS+=("$1") ;;
  esac
  shift
done
PORT="${ARGS[0]:-8080}"
MODEL="${ARGS[1]:-}"

REF="v0.1.1"
PIN="d326616c257585fd8e9176de1fc36fcd823c09f7"
ENGINE_HOME="${INFERSSD_HOME:-$HOME/inferssd}"
RELEASE="$ENGINE_HOME/releases/$PIN"
SRC="$RELEASE/source"
VENV="$RELEASE/venv"
INSTALLED="$RELEASE/.caravan-installed"

say() { echo "inferssd: $*"; }
refuse() { echo "inferssd: $*" >&2; exit 1; }

[[ "$PORT" =~ ^[0-9]+$ ]] || refuse "the port must be a number, not '$PORT'"
[[ "$CONTEXT" =~ ^[1-9][0-9]*$ ]] || refuse "--context must be a positive number of tokens, not '$CONTEXT'"

# The model before the build: a start that cannot serve says so in a second, not after twelve minutes of compiling.
if [ -z "$INSTALL_ONLY" ]; then
  [ -n "$MODEL" ] || refuse "no model given: the first GGUF part of the model is the last argument"
  case "$MODEL" in *.gguf) ;; *) refuse "$MODEL is no GGUF file" ;; esac
  [ -f "$MODEL" ] || refuse "$MODEL is missing: download the model on the /hf page first"
  name="$(basename "$MODEL")"
  if [[ "$name" =~ ^(.*)-([0-9]{5})-of-([0-9]{5})\.gguf$ ]]; then
    stem="${BASH_REMATCH[1]}"
    count="${BASH_REMATCH[3]}"
    [ "${BASH_REMATCH[2]}" = "00001" ] || refuse "$name is not the first part of its model: pick the part ${stem}-00001-of-${count}.gguf"
    for ((part = 2; part <= 10#$count; part++)); do
      piece="$(dirname "$MODEL")/$(printf '%s-%05d-of-%s.gguf' "$stem" "$part" "$count")"
      [ -f "$piece" ] || refuse "$piece is missing: the model is $((10#$count)) files, and the server reads them all"
    done
  fi
fi

if [ ! -f "$INSTALLED" ]; then
  for tool in git python3 cc c++; do
    command -v "$tool" >/dev/null 2>&1 || refuse "$tool is missing on this machine: InferSSD is built from its source"
  done
  python3 -c 'import sys, venv; sys.exit(sys.version_info < (3, 9))' 2>/dev/null \
    || refuse "InferSSD's framework needs Python 3.9 or newer with venv"
  if [ -z "${CUDACXX:-}" ]; then
    if command -v nvcc >/dev/null 2>&1; then
      CUDACXX="$(command -v nvcc)"
    elif [ -x /usr/local/cuda/bin/nvcc ]; then
      CUDACXX=/usr/local/cuda/bin/nvcc
    else
      refuse "the CUDA toolkit is missing: nvcc is neither on PATH nor in /usr/local/cuda/bin"
    fi
  fi
  export CUDACXX
  printf '#include <liburing.h>\n' | cc -E - >/dev/null 2>&1 \
    || refuse "liburing's headers are missing: the machine's owner installs them once with: sudo apt install liburing-dev"

  say "building InferSSD $REF in $RELEASE (the first start on this machine: 2–12 minutes)"
  # A build that stopped halfway left nothing known: it is made again from the start.
  rm -rf -- "$RELEASE"
  mkdir -p "$RELEASE"
  git clone -q --depth 1 --branch "$REF" https://github.com/wici-ai/inferssd.git "$SRC"
  [ "$(git -C "$SRC" rev-parse HEAD)" = "$PIN" ] \
    || refuse "the tag $REF of wici-ai/inferssd no longer names $PIN: look at the release before building it"
  python3 -m venv "$VENV"
  "$VENV/bin/python" -m pip install -q --upgrade pip
  "$VENV/bin/python" -m pip install -q 'cmake>=3.24,<5' ninja "$SRC/framework[hf]"
  (
    cd "$SRC"
    export PATH="$VENV/bin:$PATH"
    cmake --preset linux-cuda
    cmake --build build-linux-cuda --parallel "${INFERSSD_JOBS:-4}" \
      --target inferssd-server inferssd-cpuprobe inferssd-ssdprobe inferssd-memprobe
    "$VENV/bin/python" scripts/engine-resources.py --build build-linux-cuda --output "$RELEASE/engine-resources.json"
  )
  INFERSSD_HOME="$ENGINE_HOME" INFERSSD_RESOURCES="$RELEASE/engine-resources.json" "$VENV/bin/inferssd" serve --help >/dev/null
  touch "$INSTALLED"
fi

if [ -n "$INSTALL_ONLY" ]; then
  say "ready (install-only): $RELEASE"
  exit 0
fi

export INFERSSD_HOME="$ENGINE_HOME"
export INFERSSD_RESOURCES="$RELEASE/engine-resources.json"
export LLAMA_SERVER_HOST=127.0.0.1
export LAUNCH_SCOPE="${LAUNCH_SCOPE:-caravan-cell-$PORT}"
# The cell's own folder beside its model, as Strata's cells have one: the scout points LLAMA_MODELS_DIR at the fast disk.
if [ -n "${LLAMA_MODELS_DIR:-}" ]; then
  mkdir -p "$LLAMA_MODELS_DIR/.cells/$PORT"
  export PROMPT_CACHE_DIR="${PROMPT_CACHE_DIR:-$LLAMA_MODELS_DIR/.cells/$PORT/prompt-cache}"
fi
if [ -n "${CUDA_VISIBLE_DEVICES:-}" ]; then
  export VRAM_RESERVE_MIB="${VRAM_RESERVE_MIB:-256}"
fi
say "serving $MODEL on port $PORT, context $CONTEXT, card ${CUDA_VISIBLE_DEVICES:-as the engine picks}"
exec "$VENV/bin/inferssd" serve -m "$MODEL" --port "$PORT" --context "$CONTEXT"
