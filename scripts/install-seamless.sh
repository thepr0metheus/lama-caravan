#!/usr/bin/env bash
# install-seamless.sh — provision SeamlessM4T v2 on this host so it can run a
# "seamless" cell: speech in one language, TEXT in another, in one model.
#
#     COMMAND:     bash ~/run_seamless.sh $PORT <model dir> rus
#     HEALTH_PATH: /health
#
# WHY RUN THIS RATHER THAN JUST STARTING A CELL. The launcher self-installs, but
# its venv is a torch + CUDA stack — several minutes and ~7 GB. Doing that on a
# cell's first start means the board shows a cell failing its health check for
# the whole install, which reads as broken rather than busy.
#
# THE MODEL IS NOT DOWNLOADED HERE. Fetch it from the HF browser
# (facebook/seamless-m4t-v2-large, the FP32 safetensors artifact ~9.3 GB) and
# point the cell at that folder. The fairseq2 .pt checkpoints in the same repo
# are for a different runtime and are not needed.
#
# LICENCE: weights are CC-BY-NC-4.0 — non-commercial, unlike whisper's MIT.
#
#     scripts/install-seamless.sh                 # venv + $HOME files
#     SEAMLESS_TORCH_INDEX=… scripts/install-seamless.sh   # pick a CUDA build
#
# Idempotent. Standalone on purpose — NOT invoked from install-llama.sh.

set -euo pipefail

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info() { echo -e "${GREEN}[install-seamless]${NC} $*"; }
warn() { echo -e "${YELLOW}[warn]${NC}   $*"; }
err()  { echo -e "${RED}[error]${NC}  $*" >&2; }

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SRC="${REPO_DIR}/cells"

if [[ ! -f "${SRC}/seamless_server.py" || ! -f "${SRC}/run_seamless.sh" ]]; then
  err "cell servers missing under ${SRC} — is this a full checkout?"
  exit 1
fi

command -v python3 &>/dev/null || { err "python3 required"; exit 1; }
if ! python3 -c "import venv" 2>/dev/null; then
  info "Installing python3-venv..."
  sudo apt-get update -qq && sudo apt-get install -y python3-venv \
    || warn "could not install python3-venv — install it manually"
fi
command -v ffmpeg &>/dev/null \
  || warn "ffmpeg not found — the cell decodes WAV natively but needs ffmpeg for anything else"

install -m 0644 "${SRC}/seamless_server.py" "${HOME}/seamless_server.py"
install -m 0755 "${SRC}/run_seamless.sh"    "${HOME}/run_seamless.sh"
info "installed ~/seamless_server.py + ~/run_seamless.sh"

info "building the venv (torch + transformers, several minutes)…"
bash "${HOME}/run_seamless.sh" --install-only \
  || { err "venv build failed — the cell would retry this on its first start"; exit 1; }

info "done. Download facebook/seamless-m4t-v2-large from the HF browser,"
info "then configure a cell: runner 'seamless', model = that folder."
