#!/usr/bin/env bash
# install-whisper.sh — provision a faster-whisper ASR server on this host (the
# lama-caravan controller / a GPU box) so it can run a whisper "command" cell:
#
#     COMMAND:     bash ~/run_whisper.sh $PORT large-v3
#     HEALTH_PATH: /health
#
# Creates a dedicated venv (~/wsr) with faster-whisper + the bundled cuDNN/cuBLAS
# wheels, and drops ~/whisper_server.py + ~/run_whisper.sh in $HOME (run_whisper.sh
# puts those CUDA libs on LD_LIBRARY_PATH — CTranslate2 segfaults without them).
# The whisper model auto-downloads from HuggingFace on first start.
#
# Idempotent. Run standalone, or it's invoked at the end of install-llama.sh.

set -euo pipefail

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info() { echo -e "${GREEN}[install-whisper]${NC} $*"; }
warn() { echo -e "${YELLOW}[warn]${NC}   $*"; }
err()  { echo -e "${RED}[error]${NC}  $*" >&2; }
have() { command -v "$1" &>/dev/null; }

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SRC="${REPO_DIR}/whisper"
VENV="${VENV:-${HOME}/wsr}"

if [[ "$(uname -s)" == "Darwin" ]]; then
  warn "macOS: the faster-whisper GPU server is Linux/NVIDIA only — skipping."
  exit 0
fi
if ! lspci 2>/dev/null | grep -qi nvidia; then
  warn "No NVIDIA GPU detected (lspci) — skipping whisper provisioning."
  exit 0
fi
if [[ ! -f "${SRC}/whisper_server.py" || ! -f "${SRC}/run_whisper.sh" ]]; then
  err "bundled whisper files missing under ${SRC} — cannot provision."
  exit 1
fi

info "NVIDIA GPU detected — provisioning faster-whisper ASR server (venv: ${VENV})"

have python3 || { err "python3 required"; exit 1; }
if ! python3 -c "import venv" 2>/dev/null; then
  info "Installing python3-venv..."
  sudo apt-get update -qq && sudo apt-get install -y python3-venv \
    || warn "could not install python3-venv — install it manually"
fi

[[ -x "${VENV}/bin/python" ]] || { info "Creating venv at ${VENV}..."; python3 -m venv "$VENV"; }
"${VENV}/bin/python" -m pip install -q --upgrade pip
info "Installing faster-whisper + CUDA libs (cuDNN/cuBLAS) — a few hundred MB..."
"${VENV}/bin/python" -m pip install --upgrade \
    faster-whisper nvidia-cudnn-cu12 nvidia-cublas-cu12
if ! "${VENV}/bin/python" -c "import faster_whisper" 2>/dev/null; then
  err "faster-whisper failed to import in ${VENV} — check pip output above."
  exit 1
fi

install -m 0644 "${SRC}/whisper_server.py" "${HOME}/whisper_server.py"
install -m 0755 "${SRC}/run_whisper.sh"    "${HOME}/run_whisper.sh"
info "  installed ~/whisper_server.py + ~/run_whisper.sh"

# No ufw rule here on purpose: the 8001–8099 inference range is already open, and
# firewall changes are managed separately.

info "whisper ready. CARAVAN command cell → COMMAND: bash ~/run_whisper.sh \$PORT large-v3   HEALTH_PATH: /health"
info "  (the model ~large-v3 auto-downloads from HuggingFace on first start)"
