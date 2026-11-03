#!/usr/bin/env bash
# fetch-cell-assets.sh — put a cell's server files in $HOME, from the controller.
#
#     scripts/fetch-cell-assets.sh run_moonshine.sh moonshine_server.py
#
# The controller owns these files (its cells/ directory) and hands them to the
# fleet over /api/cell-assets. This repo used to keep its own copies and the
# installers laid those down; the two sides then drifted for months with nothing
# to notice it. Now there is one copy, upstream, and everything else fetches it.
#
# The scout also does this by itself before every command-cell start, so an
# installer that cannot reach the controller is not fatal — the files will
# arrive when the cell first runs. This exists so a freshly provisioned host has
# them right away, and so --install-only paths (venv prewarming) find them.
#
# Controller URL and fleet token come from the scout's own config.json.
set -euo pipefail

CFG="${CARAVAN_SCOUT_CONFIG:-$HOME/caravan-scout/config.json}"
# A scout that came before ~/caravan-scout keeps its config in its old folder. A new machine has none yet, and is told so under its own folder's name.
[[ -f "$CFG" || ! -f "$HOME/projects/caravan-scout/config.json" ]] || CFG="$HOME/projects/caravan-scout/config.json"
[ $# -gt 0 ] || { echo "usage: $(basename "$0") <asset> [asset …]" >&2; exit 2; }

if [ ! -f "$CFG" ]; then
  echo "[cell-assets] no scout config at $CFG — skipping fetch;" >&2
  echo "              the files will arrive when the cell first starts." >&2
  exit 0
fi

read -r BASE TOKEN <<EOF
$(python3 - "$CFG" <<'PY'
import json, sys
cfg = json.load(open(sys.argv[1]))
print((cfg.get("controllerUrl") or "").rstrip("/"), cfg.get("controllerToken") or "")
PY
)
EOF

if [ -z "${BASE:-}" ]; then
  echo "[cell-assets] no controllerUrl in $CFG — skipping fetch." >&2
  exit 0
fi

for name in "$@"; do
  tmp="$HOME/$name.new"
  if curl -fsS -m 20 -H "X-Caravan-Token: ${TOKEN}" \
       "${BASE}/api/cell-assets/file?name=${name}" -o "$tmp"; then
    case "$name" in *.sh) chmod 0755 "$tmp";; *) chmod 0644 "$tmp";; esac
    mv -f "$tmp" "$HOME/$name"          # atomic — never a half-written launcher
    echo "[cell-assets] $name <- ${BASE}"
  else
    rm -f "$tmp"
    # Not fatal on purpose: a host that already has the file keeps running, and
    # a fresh one gets it at first cell start.
    echo "[cell-assets] could not fetch $name from ${BASE} — leaving what is there" >&2
  fi
done
