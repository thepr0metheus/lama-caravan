#!/usr/bin/env bash
# Puts caravan-scout on this machine: the sidecar that lends the machine's GPU or CPU to a LAMA CARAVAN controller.
# The controller named below wrote this text and hands out the program it names, so the two cannot differ.
#
#   curl -fsSL @@CONTROLLER@@/scout/install.sh | bash
#   curl -fsSL @@CONTROLLER@@/scout/install.sh | bash -s -- [--skip-llama] [--skip-whisper] [--llama-tag <tag>]
#
# It installs what the machine needs (llama.cpp built with CUDA where there is an NVIDIA card, the whisper speech
# server there too), starts the scout as a service, waits until it answers and prints the address to enter on the
# controller: ＋ Add scout. The controller pairs the scout itself and hands it its fleet token: there is nothing to
# edit here. Safe to run again. ~/caravan-scout/current/scripts/uninstall.sh takes the scout off.

set -euo pipefail

# All of it in one function: bash reads the whole of it before it runs a line. A download cut short then runs nothing, and a command that reads its
# input does not eat the rest of the script, which comes through that same input.
main() {
CONTROLLER="@@CONTROLLER@@"
COMMIT="@@COMMIT@@"
BUNDLE_SHA256="@@SHA256@@"
SCOUT_HOME="${CARAVAN_SCOUT_HOME:-${HOME}/caravan-scout}"
LLAMA_TAG="${LLAMA_TAG:-}"          # empty = the latest llama.cpp release
LLAMA_DIR="${HOME}/llama.cpp"
SKIP_LLAMA=0
SKIP_WHISPER=0

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BOLD='\033[1m'; NC='\033[0m'
info()  { echo -e "${GREEN}[install]${NC} $*"; }
warn()  { echo -e "${YELLOW}[warn]${NC}   $*"; }
err()   { echo -e "${RED}[error]${NC}  $*" >&2; }
have()  { command -v "$1" &>/dev/null; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-llama)   SKIP_LLAMA=1 ;;
    --skip-whisper) SKIP_WHISPER=1 ;;
    --llama-tag)    LLAMA_TAG="$2"; shift ;;
    *) err "unknown arg: $1"; exit 1 ;;
  esac
  shift
done

# ── 1. a machine this scout runs on ───────────────────────────────────────────────
SYSTEM="$(uname -s)-$(uname -m)"
if [[ "$SYSTEM" != "Linux-x86_64" ]]; then
  err "this controller hands out a scout for Linux on x86_64, and this machine is ${SYSTEM}"
  exit 1
fi
for tool in curl tar sha256sum systemctl; do
  have "$tool" || { err "${tool} is required here"; exit 1; }
done

# ── 2. the program, checked against the sum its controller named ──────────────────
RELEASE="${SCOUT_HOME}/releases/${COMMIT}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
info "Fetching the scout ${COMMIT} from ${CONTROLLER}..."
curl -fsSL "${CONTROLLER}/scout/bundle.tar.gz" -o "${WORK}/bundle.tar.gz"
if [[ "$(sha256sum "${WORK}/bundle.tar.gz" | cut -d' ' -f1)" != "${BUNDLE_SHA256}" ]]; then
  err "what arrived is not what the controller named: nothing was changed"
  exit 1
fi
mkdir -p "${WORK}/release"
tar -xzf "${WORK}/bundle.tar.gz" -C "${WORK}/release"
"${WORK}/release/caravan-scout" --version >/dev/null || { err "the program does not run on this machine: nothing was changed"; exit 1; }
mkdir -p "${SCOUT_HOME}/releases"
rm -rf "$RELEASE"
mv "${WORK}/release" "$RELEASE"
ln -sfn "releases/${COMMIT}" "${SCOUT_HOME}/current"

# A machine that ran the scout before keeps its pairing, its cells' records and its cache's settings.
OLD_HOME="${HOME}/projects/caravan-scout"
for name in config.json state.json; do
  if [[ -f "${OLD_HOME}/${name}" && ! -f "${SCOUT_HOME}/${name}" ]]; then
    cp -p "${OLD_HOME}/${name}" "${SCOUT_HOME}/${name}"
    info "Kept ${name} of the scout that ran here before"
  fi
done

# A new machine has no config yet: the scout makes one when it is paired, and until then it listens on its default.
PORT=""
if [[ -f "${SCOUT_HOME}/config.json" ]]; then
  PORT="$(sed -n 's/.*"listenPort": *\([0-9][0-9]*\).*/\1/p' "${SCOUT_HOME}/config.json" | head -1)"
fi
PORT="${PORT:-8092}"

# ── 3. python3: voice cells and the scripts below run on it ───────────────────────
if ! have python3; then
  info "Installing Python 3..."
  sudo apt-get update -qq && sudo apt-get install -y python3
fi

# ── 4. llama.cpp (NVIDIA or not), and the whisper speech server ───────────────────
if [[ $SKIP_LLAMA -eq 1 ]]; then
  warn "Skipping llama.cpp (--skip-llama)"
else
  # shellcheck source=/dev/null
  source "${RELEASE}/scripts/install-llama.sh"
  install_llama "$SCOUT_HOME" "$LLAMA_DIR" "$LLAMA_TAG" 0
fi
if [[ $SKIP_WHISPER -eq 1 ]]; then
  warn "Skipping whisper (--skip-whisper)"
else
  # Run, never source: this script exits early on a host with no NVIDIA card.
  VENV="${HOME}/wsr" bash "${RELEASE}/scripts/install-whisper.sh" || warn "whisper provisioning failed — see the output above"
fi

# ── 5. the service: installed, started, and kept after logout ─────────────────────
info "Installing the systemd user service..."
UNIT_DIR="${HOME}/.config/systemd/user"
mkdir -p "$UNIT_DIR"
rm -f "${UNIT_DIR}/caravan-scout.service.d/rust.conf"
cat > "${UNIT_DIR}/caravan-scout.service" <<UNIT
[Unit]
Description=Caravan Scout (lama-caravan client agent)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=${SCOUT_HOME}
Environment=CARAVAN_SCOUT_ROOT=${SCOUT_HOME}/current
Environment=LAMA_CARAVAN_SERVER_CELLS_DIR=${SCOUT_HOME}/var/server-cells
ExecStart=${SCOUT_HOME}/current/caravan-scout --config ${SCOUT_HOME}/config.json --state ${SCOUT_HOME}/state.json
Restart=always
RestartSec=3
# Cells must survive the scout's restart: the next one holds them again.
KillMode=process
TimeoutStopSec=15

[Install]
WantedBy=default.target
UNIT
systemctl --user daemon-reload
systemctl --user enable caravan-scout.service >/dev/null
systemctl --user restart caravan-scout.service
# Without lingering, a user service stops at logout and does not start at boot.
if [[ "$(loginctl show-user "$USER" -p Linger --value 2>/dev/null)" != "yes" ]]; then
  loginctl enable-linger "$USER" 2>/dev/null \
    || sudo loginctl enable-linger "$USER" \
    || warn "could not keep the scout running after logout — run: sudo loginctl enable-linger $USER"
fi

# ── 6. the firewall lets the controller in ────────────────────────────────────────
CELL_HINT="the cells need the controller's cell ports (22001–22999 unless changed there): sudo ufw allow from <controller-ip> to any port 22001:22999 proto tcp"
if have ufw && sudo -n true 2>/dev/null && sudo ufw status 2>/dev/null | grep "Status: active" >/dev/null; then
  if ! sudo ufw status 2>/dev/null | grep -E "^${PORT}(/tcp)?\b" >/dev/null; then
    info "Opening port ${PORT}/tcp in ufw for the controller..."
    sudo ufw allow "${PORT}/tcp" comment 'caravan-scout' >/dev/null || warn "could not open ${PORT}/tcp — run: sudo ufw allow ${PORT}/tcp"
  fi
  sudo ufw status 2>/dev/null | grep -E "^22001:" >/dev/null || warn "ufw is active here, and ${CELL_HINT}"
elif have ufw; then
  warn "If ufw is active here, the controller needs port ${PORT}: sudo ufw allow ${PORT}/tcp"
  warn "and ${CELL_HINT}"
fi

# ── 7. wait until the scout answers, then say where it is ─────────────────────────
info "Waiting for the scout to answer on :${PORT}..."
ANSWER=""
for _ in $(seq 1 30); do
  ANSWER="$(curl -fsS "http://127.0.0.1:${PORT}/api/pairing" 2>/dev/null || true)"
  [[ -n "$ANSWER" ]] && break
  sleep 1
done
if [[ -z "$ANSWER" ]]; then
  err "the scout did not answer on :${PORT} within 30 s"
  err "see: journalctl --user -u caravan-scout.service -n 50"
  exit 1
fi
ADDRESS="$(echo "$ANSWER" | sed -n 's/.*"ip": *"\([^"]*\)".*/\1/p' | head -1)"

echo ""
info "━━━ caravan-scout is running ━━━"
echo -e "  Address : ${BOLD}${ADDRESS:-?}${NC}"
echo -e "  Port    : ${BOLD}${PORT}${NC}"
echo ""
if echo "$ANSWER" | grep -q '"controllerUrl": *"[^"]'; then
  echo "  Already paired with a controller — it keeps reporting there."
else
  echo "  Now on the board: ＋ Add scout,"
  echo -e "  and enter ${BOLD}${ADDRESS:-?}${NC} with port ${BOLD}${PORT}${NC}. That is all."
fi
echo ""
}

main "$@"
