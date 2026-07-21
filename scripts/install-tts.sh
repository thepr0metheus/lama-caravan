#!/usr/bin/env bash
# install-tts.sh — provision voice-clone TTS "command" cells on this GPU host
# (three engines share one server file; the engine is picked per cell):
#
#     COMMAND:     bash ~/run_tts.sh $PORT xtts        (or: f5 | cosyvoice)
#     HEALTH_PATH: /health
#
# Drops ~/tts_server.py + ~/run_tts.sh in $HOME and installs system ffmpeg
# (torchcodec — torch>=2.9 audio IO — dlopens libav*; synthesis 500s without
# it). Engine venvs (~/tts-<engine>, tens of GB with models) self-install on
# a cell's FIRST start, which takes 10–20 min; pre-warm them instead with:
#
#     scripts/install-tts.sh --prewarm "xtts f5 cosyvoice"
#
# Idempotent. Standalone on purpose — NOT invoked from install-llama.sh:
# the engines are heavyweight and only voice-clone users need them.

set -euo pipefail

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info() { echo -e "${GREEN}[install-tts]${NC} $*"; }
warn() { echo -e "${YELLOW}[warn]${NC}   $*"; }
err()  { echo -e "${RED}[error]${NC}  $*" >&2; }
have() { command -v "$1" &>/dev/null; }

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SRC="${REPO_DIR}/cells"
PREWARM=""
if [[ "${1:-}" == "--prewarm" ]]; then PREWARM="${2:-xtts}"; fi

if [[ "$(uname -s)" == "Darwin" ]]; then
  warn "macOS: the TTS GPU server is Linux/NVIDIA only — skipping."
  exit 0
fi
if ! nvidia-smi -L >/dev/null 2>&1 \
   && ! (lspci 2>/dev/null | grep -i nvidia >/dev/null); then
  warn "No NVIDIA GPU detected — skipping TTS provisioning."
  exit 0
fi
if [[ ! -f "${SRC}/tts_server.py" || ! -f "${SRC}/run_tts.sh" ]]; then
  err "cell servers missing under ${SRC} — is this a full checkout?"
  exit 1
fi

info "NVIDIA GPU detected — provisioning voice-clone TTS cells"
have python3 || { err "python3 required"; exit 1; }

install -m 0644 "${SRC}/tts_server.py" "${HOME}/tts_server.py"
install -m 0755 "${SRC}/run_tts.sh"    "${HOME}/run_tts.sh"
info "  installed ~/tts_server.py + ~/run_tts.sh"

# torchcodec (torch>=2.9 audio IO) needs the system ffmpeg shared libraries.
if ldconfig -p 2>/dev/null | grep -q libavutil; then
  info "  ffmpeg libraries present"
elif sudo -n true 2>/dev/null; then
  info "Installing ffmpeg (torchcodec runtime)..."
  sudo apt-get update -qq && sudo apt-get install -y -qq ffmpeg \
    || warn "ffmpeg install failed — xtts synthesis will 500 until it exists"
else
  warn "no ffmpeg libs and no passwordless sudo — run: sudo apt-get install -y ffmpeg"
fi

if [[ -n "$PREWARM" ]]; then
  for eng in $PREWARM; do
    info "Pre-warming '${eng}' venv (this downloads gigabytes)..."
    bash "${HOME}/run_tts.sh" 8099 "$eng" --install-only \
      || warn "prewarm of ${eng} failed — its first cell start will retry"
  done
fi

info "TTS ready. CARAVAN command cell → COMMAND: bash ~/run_tts.sh \$PORT xtts|f5|cosyvoice   HEALTH_PATH: /health"
info "  (engine venv + model self-install on first start unless pre-warmed)"
