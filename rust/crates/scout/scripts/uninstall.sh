#!/usr/bin/env bash
# uninstall.sh — take caravan-scout off this machine.
#
#   ~/caravan-scout/current/scripts/uninstall.sh
#
# Stops every cell the scout runs (so no llama-server is left holding a GPU
# with nobody to stop it), then the service, and removes it together with the
# scout's own files here: the program, config.json, state.json, the service and cell logs, var/.
#
# What stays, because it is expensive to make and the scout did not own it
# alone: the llama.cpp build (~/llama.cpp), the model cache
# (~/llama-model-cache), the whisper venv (~/wsr).
# The end of the output names each, with the command that removes it.
#
# On the controller the machine's node says its scout went silent; remove it
# there with its ✕ (or remove it there FIRST: the controller then lets go of
# the scout itself).

set -euo pipefail

INSTALL_DIR="${CARAVAN_SCOUT_HOME:-${HOME}/caravan-scout}"
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info() { echo -e "${GREEN}[uninstall]${NC} $*"; }
warn() { echo -e "${YELLOW}[warn]${NC}   $*"; }
on_linux() { [[ "$(uname -s)" == "Linux" ]]; }
on_macos() { [[ "$(uname -s)" == "Darwin" ]]; }

PORT="$(python3 -c "import json,sys
try: print(int(json.load(open(sys.argv[1])).get('listenPort') or 8092))
except Exception: print(8092)" "$INSTALL_DIR/config.json" 2>/dev/null || echo 8092)"

# ── 1. stop the cells, through the scout itself ──────────────────────────────
# With a fleet token configured the scout asks for it; it is read from the
# config file here and sent as a header, never printed.
if curl -fsS -o /dev/null "http://127.0.0.1:${PORT}/api/health" 2>/dev/null; then
  info "Stopping the scout's cells..."
  python3 - "$INSTALL_DIR/config.json" "$PORT" <<'PYEOF' || warn "could not stop the cells — see above"
import json, sys, urllib.request
path, port = sys.argv[1], sys.argv[2]
try:
    token = str(json.load(open(path)).get("controllerToken") or "")
except Exception:
    token = ""
headers = {"Content-Type": "application/json"}
if token:
    headers["X-Caravan-Token"] = token
req = urllib.request.Request(f"http://127.0.0.1:{port}/api/llama-node/stop", data=b"{}",
                             headers=headers, method="POST")
with urllib.request.urlopen(req, timeout=60) as resp:
    body = json.loads(resp.read().decode("utf-8") or "{}")
results = body.get("results", [body])
print(f"  stopped: {sum(1 for r in results if r.get('ok'))} of {len(results)}")
PYEOF
else
  warn "the scout does not answer on :${PORT} — its cells, if any, are left as they are"
fi

# ── 2. the service ────────────────────────────────────────────────────────────
if on_linux; then
  UNIT="${HOME}/.config/systemd/user/caravan-scout.service"
  systemctl --user disable --now caravan-scout.service 2>/dev/null || true
  rm -f "$UNIT"
  systemctl --user daemon-reload 2>/dev/null || true
  info "systemd user service removed"
elif on_macos; then
  PLIST="${HOME}/Library/LaunchAgents/com.caravan-scout.plist"
  launchctl unload "$PLIST" 2>/dev/null || true
  rm -f "$PLIST"
  info "launchd agent removed"
fi

# What the scout showed of the library goes with it: a little shell does this when the scout ends, and if that was killed too, it goes here.
fusermount3 -u -z "$INSTALL_DIR/library-view" 2>/dev/null || true

# ── 3. the scout's own files ─────────────────────────────────────────────────
rm -rf "$INSTALL_DIR/config.json" "$INSTALL_DIR/config.tmp" "$INSTALL_DIR/state.json" \
       "$INSTALL_DIR/state.tmp" "$INSTALL_DIR/var" "$INSTALL_DIR/llama-node-configs" \
       "$INSTALL_DIR/caravan-scout.log" "$INSTALL_DIR/caravan-scout.err.log" "$INSTALL_DIR/engine-logs" \
       "$INSTALL_DIR/library-view" "$INSTALL_DIR/cell-logs"
info "config, state, cell artifacts and logs removed"

echo ""
info "━━━ caravan-scout is off this machine ━━━"
echo "  Left in place — remove what you no longer need:"
[[ -d "${HOME}/llama.cpp" ]] && echo "    llama.cpp build : rm -rf ~/llama.cpp"
[[ -d "${HOME}/llama-model-cache" ]] && echo "    model cache     : rm -rf ~/llama-model-cache"
[[ -d "${HOME}/wsr" ]] && echo "    whisper venv    : rm -rf ~/wsr ~/whisper_server.py ~/run_whisper.sh"
echo ""
# Last, for this script stands inside it.
rm -rf "$INSTALL_DIR/releases" "$INSTALL_DIR/current"
rmdir "$INSTALL_DIR" 2>/dev/null || true
