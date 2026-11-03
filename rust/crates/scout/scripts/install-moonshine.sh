#!/usr/bin/env bash
# install-moonshine.sh — provision a Moonshine v2 speech server on this host so
# it can run a moonshine "command" cell. One cell, two roles: it recognizes
# speech AND synthesizes it.
#
#     COMMAND:     bash ~/run_moonshine.sh $PORT en
#     HEALTH_PATH: /health
#
# CPU-ONLY on purpose: Moonshine's medium-streaming EN model beats Whisper
# large-v3 WER at 250M params and runs sub-second on a laptop core — so this
# installs on any box, GPU or not, and the GPUs stay free for LLMs.
# Languages — recognition: en es zh ja ko vi uk ar (no Russian, whisper stays
# the RU recognizer); synthesis: 20 locales, Russian included, each voice
# downloading on its first request.
# Licensing: the EN model is MIT; the others are Moonshine Community License
# (free below $1M/yr revenue, registration + attribution required).
#
#     scripts/install-moonshine.sh                # venv + $HOME files
#     scripts/install-moonshine.sh --prewarm "en" # + download models now
#
# Idempotent. Standalone on purpose — NOT invoked from install-llama.sh.

set -euo pipefail

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info() { echo -e "${GREEN}[install-moonshine]${NC} $*"; }
warn() { echo -e "${YELLOW}[warn]${NC}   $*"; }
err()  { echo -e "${RED}[error]${NC}  $*" >&2; }
have() { command -v "$1" &>/dev/null; }

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PREWARM=""
if [[ "${1:-}" == "--prewarm" ]]; then PREWARM="${2:-en}"; fi


have python3 || { err "python3 required"; exit 1; }
if ! python3 -c "import venv" 2>/dev/null; then
  info "Installing python3-venv..."
  sudo apt-get update -qq && sudo apt-get install -y python3-venv \
    || warn "could not install python3-venv — install it manually"
fi

"${REPO_DIR}/scripts/fetch-cell-assets.sh" run_moonshine.sh moonshine_server.py
info "installed ~/moonshine_server.py + ~/run_moonshine.sh"

# The launcher self-installs its venv on first start; --install-only does it
# now (plus the model download with --prewarm) so a cell's first start is fast.
if [[ -n "$PREWARM" ]]; then
  for lang in $PREWARM; do
    info "prewarming '${lang}' (venv + model download)…"
    bash "${HOME}/run_moonshine.sh" 8099 "$lang" --install-only \
      || warn "prewarm for '${lang}' failed — the cell will retry on first start"
  done
else
  bash "${HOME}/run_moonshine.sh" 8099 en --install-only \
    || warn "venv provisioning failed — the cell will retry on first start"
fi
info "done — add a moonshine cell in the caravan (Runner: moonshine, e.g. port 8025)"
