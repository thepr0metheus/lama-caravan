#!/bin/bash
# PersonaPlex-7B-v1 cell launcher: NVIDIA's speech-to-speech model (Moshi-based, full duplex).
# It listens and answers in SPEECH, in a browser page it serves itself: the microphone goes in,
# the voice comes out. Self-installing, for a CARAVAN command cell.
#
# Usage: run_personaplex.sh [port] [model-dir] [--install-only]
#   model-dir  the checkpoint folder of the models library, as the /hf page lays it out:
#              model.safetensors, tokenizer-*.safetensors, tokenizer_spm_32k_3.model, voices.tgz, dist.tgz.
#              Default: $LLAMA_MODELS_DIR/personaplex-7b-v1/nvidia/SAFETENSORS
#   --install-only  makes the venv and unpacks the assets, then exits (a first start takes minutes).
#
# What the first start does, once: a venv with torch for Blackwell (cu130) and the repository's own
# dependencies; the source of NVIDIA/personaplex at ONE pinned commit; the unpacked voices and web client.
# Nothing is fetched at start from the hub — the weights, the voices and the page are the library's files
# (the model is gated: its terms are accepted once, on its page, by the owner of the token that downloaded it).
#
# Why the odd install, each line a defect that was paid for (2026-10-15):
#  * The repository pins torch < 2.5, which has no kernels for an RTX 5090 (sm_120): torch is installed
#    FIRST, from the cu130 index, and the package itself with --no-deps (its other pins are stale too).
#  * The PyPI package `moshi` is Kyutai's, without the voice and text prompts: this one is NVIDIA's source.
#  * server.py and offline.py ask the hub for config.json at start, without a condition: that call fails
#    with HF_HUB_OFFLINE=1. The one line is replaced (the file is not used).
#  * `import moshi.server` runs the server's main(): never import it to test the install.
#  * One session at a time (the model is one stream). No TLS: a microphone needs a secure page, so open
#    http://localhost:<port> through an ssh tunnel (ssh -N -L <port>:localhost:<port> <machine>), or
#    put the port behind an https name.
set -euo pipefail

# The flag may stand anywhere: it is taken out first, and what is left is [port] [model-dir].
INSTALL_ONLY=""
ARGS=()
for arg in "$@"; do
  if [ "$arg" = "--install-only" ]; then INSTALL_ONLY=1; else ARGS+=("$arg"); fi
done
PORT="${ARGS[0]:-8030}"
MODEL_DIR="${ARGS[1]:-${LLAMA_MODELS_DIR:-/mnt/lama-caravan-models}/personaplex-7b-v1/nvidia/SAFETENSORS}"

PIN="3428dfd95309a7f3c84fd93259ded0f810d1ff91"
VENV="${PPLEX_VENV:-$HOME/personaplex-venv}"
SRC="${PPLEX_SRC:-$HOME/personaplex}"
ASSETS="${PPLEX_ASSETS:-$HOME/pplex-assets}"
export PATH="$HOME/.local/bin:$PATH"

say() { echo "personaplex: $*"; }

for f in model.safetensors tokenizer-e351c8d8-checkpoint125.safetensors tokenizer_spm_32k_3.model voices.tgz dist.tgz; do
  [ -f "$MODEL_DIR/$f" ] || { say "$MODEL_DIR/$f is missing: download nvidia/personaplex-7b-v1 on the /hf page first" >&2; exit 1; }
done

if [ ! -x "$VENV/bin/python" ]; then
  say "creating the venv $VENV (first start on this machine: several minutes)"
  if command -v uv >/dev/null 2>&1; then
    uv venv --python 3.12 "$VENV"
  else
    python3 -m venv "$VENV"
    "$VENV/bin/pip" -q install -U pip
  fi
fi
# The marker is written when the installs are DONE, not when the venv exists: a first start that stopped halfway
# (the network, a full disk) must not read as installed — the next start would skip the work and fail at its first import.
if [ ! -f "$VENV/.deps-installed" ]; then
  say "installing torch and the dependencies into $VENV"
  if command -v uv >/dev/null 2>&1; then
    uv pip install --python "$VENV/bin/python" "torch==2.13.0" --torch-backend=cu130
    uv pip install --python "$VENV/bin/python" --only-binary=:all: "numpy<2.2" "safetensors<0.5" "huggingface-hub<0.25" \
        "einops==0.7.0" "sentencepiece==0.2.0" "sphn==0.1.9" "aiohttp<3.11" tqdm
  else
    "$VENV/bin/pip" install "torch==2.13.0" --index-url https://download.pytorch.org/whl/cu130
    "$VENV/bin/pip" install --only-binary=:all: "numpy<2.2" "safetensors<0.5" "huggingface-hub<0.25" \
        "einops==0.7.0" "sentencepiece==0.2.0" "sphn==0.1.9" "aiohttp<3.11" tqdm
  fi
  touch "$VENV/.deps-installed"
fi

if [ ! -d "$SRC/.git" ]; then
  say "fetching the source"
  git clone -q https://github.com/NVIDIA/personaplex "$SRC"
fi
if [ "$(git -C "$SRC" rev-parse HEAD)" != "$PIN" ]; then
  git -C "$SRC" checkout -q --force "$PIN"
fi
# The one unconditional hub call of start (see above), as a line that does nothing.
for f in "$SRC/moshi/moshi/server.py" "$SRC/moshi/moshi/offline.py"; do
  # -i.orig, not -i: the one form GNU and BSD sed share.
  sed -E -i.orig 's/^([[:space:]]*)hf_hub_download\((args\.)?hf_repo, "config\.json"\)[[:space:]]*$/\1pass/' "$f" && rm -f "$f.orig"
done
if ! "$VENV/bin/python" -c "import importlib.util,sys; sys.exit(0 if importlib.util.find_spec('moshi') else 1)" 2>/dev/null; then
  if command -v uv >/dev/null 2>&1; then
    uv pip install --python "$VENV/bin/python" --no-deps -e "$SRC/moshi"
  else
    "$VENV/bin/pip" install --no-deps -e "$SRC/moshi"
  fi
fi

if [ ! -f "$ASSETS/dist/index.html" ] || [ ! -f "$ASSETS/voices/NATF0.pt" ]; then
  say "unpacking the voices and the page from $MODEL_DIR"
  mkdir -p "$ASSETS"
  tar -xzf "$MODEL_DIR/voices.tgz" -C "$ASSETS"
  tar -xzf "$MODEL_DIR/dist.tgz" -C "$ASSETS"
fi

if [ -n "$INSTALL_ONLY" ]; then
  say "ready (install-only): venv $VENV, source $SRC, assets $ASSETS"
  exit 0
fi

say "serving on port $PORT: weights from $MODEL_DIR"
cd "$SRC"
# NO_TORCH_COMPILE: any value turns the compile off, which needs no Python headers and no ptxas.
# LD_LIBRARY_PATH out: the machine's older CUDA libraries must not shadow the ones torch carries.
exec env -u LD_LIBRARY_PATH PYTHONUNBUFFERED=1 HF_HUB_OFFLINE=1 NO_TORCH_COMPILE=1 \
    "$VENV/bin/python" -m moshi.server --host 0.0.0.0 --port "$PORT" \
    --static "$ASSETS/dist" --voice-prompt-dir "$ASSETS/voices" \
    --moshi-weight "$MODEL_DIR/model.safetensors" \
    --mimi-weight "$MODEL_DIR/tokenizer-e351c8d8-checkpoint125.safetensors" \
    --tokenizer "$MODEL_DIR/tokenizer_spm_32k_3.model"
