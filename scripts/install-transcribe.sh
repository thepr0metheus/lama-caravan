#!/usr/bin/env bash
# install-transcribe.sh — provision the transcribe.cpp speech engine on this
# host so it can run a `transcribe` cell:
#
#     COMMAND:     bash ~/run_transcribe.sh $PORT <model.gguf>
#     HEALTH_PATH: /health
#
# transcribe.cpp is a ggml speech-recognition library — the llama.cpp of ASR.
# One build runs 16 model families (GigaAM, Parakeet, Canary, Whisper, Moonshine,
# Qwen3-ASR, Granite Speech, Voxtral…) from GGUF weights, so adding a model later
# means downloading a file, not provisioning another engine.
#
# The reason it earns its place next to whisper: for RUSSIAN, GigaAM-v3 sits near
# 8% WER where whisper large-v3 sits at 21-25% across Sber's ten Russian sets,
# and it returns cased, punctuated text. Measured on an RTX 5090 here: 0.1 s to
# load, ~78x realtime to transcribe, from a 260 MB quantised file.
#
#     scripts/install-transcribe.sh              # build + venv
#     scripts/install-transcribe.sh --cpu        # skip CUDA even if nvcc exists
#
# Idempotent. Standalone on purpose — NOT invoked from install-llama.sh.
# Licensing: transcribe.cpp is MIT. The MODELS are not all MIT — GigaAM-v3 is,
# but some ASR weights are CC-BY-NC; check the card before commercial use.

set -euo pipefail

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info() { echo -e "${GREEN}[install-transcribe]${NC} $*"; }
warn() { echo -e "${YELLOW}[warn]${NC}   $*"; }
err()  { echo -e "${RED}[error]${NC}  $*" >&2; }
have() { command -v "$1" &>/dev/null; }

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SRC="${REPO_DIR}/cells"
CLONE="${TRANSCRIBE_DIR:-$HOME/transcribe.cpp}"
VENV="${VENV:-$HOME/transcribe-venv}"
WANT_CUDA=1
[ "${1:-}" = "--cpu" ] && WANT_CUDA=0

# The cell server files have ONE home: the controller's cells/. On the
# controller this script is sitting next to it; on a client there is no cells/
# and the scout fetches the same files over /api/cell-assets. Same script, both
# hosts — which is the point, because a second copy is how the old drift began.
# (On scout hosts the scout itself fetches these files over /api/cell-assets —
# this script only ever needs the local cells/ of a full checkout.)
if [[ ! -f "${SRC}/transcribe_server.py" ]]; then
  err "no cells/transcribe_server.py here — run from a full lama-caravan checkout"
  exit 1
fi
have cmake || { err "cmake is required"; exit 1; }
have git   || { err "git is required"; exit 1; }

# ── source ───────────────────────────────────────────────────────────────────
if [ -d "$CLONE/.git" ]; then
  info "updating $CLONE"
  git -C "$CLONE" pull --ff-only -q || warn "pull failed — building what is on disk"
else
  info "cloning transcribe.cpp into $CLONE"
  git clone -q --depth 1 https://github.com/handy-computer/transcribe.cpp "$CLONE"
fi

# ── build ────────────────────────────────────────────────────────────────────
# TRANSCRIBE_BUILD_SHARED is what produces libtranscribe.so — the Python binding
# is a pure-Python ctypes layer and needs the shared object, not the .a that a
# default build leaves behind.
# -B must be ABSOLUTE. A bare `-B build` is resolved against the caller's
# working directory, not against -S, so running this from the caravan checkout
# wrote the build tree into the caravan repo and then failed looking for it
# under the clone.
CMAKE_ARGS=(-B "$CLONE/build" -DCMAKE_BUILD_TYPE=Release -DTRANSCRIBE_BUILD_SHARED=ON)
if [ "$WANT_CUDA" = "1" ] && { have nvcc || [ -x /usr/local/cuda/bin/nvcc ]; }; then
  export PATH="/usr/local/cuda/bin:$PATH"
  info "CUDA toolkit found — building the CUDA backend"
  CMAKE_ARGS+=(-DTRANSCRIBE_CUDA=ON)
elif [[ "$(uname -s)" == "Darwin" ]]; then
  info "Apple Silicon — Metal is enabled automatically"
else
  warn "no CUDA toolkit — CPU build (still fine for the small ASR models)"
fi
# Optional but worth saying out loud: without BLAS the host-side decoder runs a
# scalar fallback the project measures as 10-15x slower.
if ! ldconfig -p 2>/dev/null | grep -qi openblas; then
  warn "libopenblas not found — decoder falls back to scalar (10-15x slower)"
  warn "  install it with: sudo apt install libopenblas-dev, then re-run"
fi

info "configuring…"
cmake "${CMAKE_ARGS[@]}" -S "$CLONE" > /tmp/transcribe-build.log 2>&1 || {
  err "cmake configure failed — see /tmp/transcribe-build.log"; exit 1; }
info "building (this takes a few minutes with CUDA)…"
cmake --build "$CLONE/build" -j "$(nproc 2>/dev/null || sysctl -n hw.ncpu)" \
  >> /tmp/transcribe-build.log 2>&1 || {
  err "build failed — see /tmp/transcribe-build.log"; exit 1; }

LIB="$(find "$CLONE/build" -name 'libtranscribe.so' -o -name 'libtranscribe.dylib' | head -1)"
[ -n "$LIB" ] || { err "build produced no shared library"; exit 1; }
info "built $LIB"

# ── python binding ───────────────────────────────────────────────────────────
if [ ! -x "$VENV/bin/python" ]; then
  info "creating venv $VENV"
  python3 -m venv "$VENV"
  "$VENV/bin/pip" -q install -U pip
fi
# --no-deps on purpose: the binding declares transcribe-cpp-native==<same
# version>, a wheel of PREBUILT libraries that PyPI lags behind the repo on
# (repo 0.2.0, PyPI 0.1.3 as of this writing) — and we do not want it anyway,
# having just built the library ourselves with this machine's accelerator.
# TRANSCRIBE_LIBRARY (set by run_transcribe.sh) points the pure-Python ctypes
# layer at that build.
info "installing the transcribe-cpp binding (no deps — we built the library)"
"$VENV/bin/pip" -q install --no-deps "$CLONE/bindings/python"

if [ -f "${SRC}/transcribe_server.py" ]; then
  # `install` is not portable enough to rely on across the fleet (BSD install on
  # macOS takes different flags), and cp -p is all this needs.
  cp -f "${SRC}/transcribe_server.py" "${HOME}/transcribe_server.py"
  cp -f "${SRC}/run_transcribe.sh"    "${HOME}/run_transcribe.sh"
  chmod 0644 "${HOME}/transcribe_server.py"; chmod 0755 "${HOME}/run_transcribe.sh"
else
  "$FETCH" run_transcribe.sh transcribe_server.py
fi
info "installed ~/transcribe_server.py + ~/run_transcribe.sh"

cat <<EOF

  Done. Point a cell at a GGUF ASR model:

    COMMAND      bash ~/run_transcribe.sh \$PORT ~/llama.cpp/models/gigaam-v3-e2e-rnnt-Q8_0.gguf
    HEALTH_PATH  /health

  Russian model (MIT, cased + punctuated):
    huggingface.co/handy-computer/gigaam-v3-e2e-rnnt-gguf

EOF
