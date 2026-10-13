#!/bin/bash
# GR00T cell launcher (CARAVAN command cell): NVIDIA's GR00T N1.7 robot policy behind HTTP.
#
# Usage: run_gr00t.sh <port> <checkpoint folder> --backbone <folder>
#                     [--embodiment TAG] [--denoising-steps N] [--name NAME]
#
#     bash run_gr00t.sh 22011 ~/models/GR00T-N1.7-3B/nvidia/BF16 \
#         --backbone ~/models/Cosmos-Reason2-2B/nvidia/BF16
#
# The runtime is installed on the machine once, into GR00T_HOME (default ~/Isaac-GR00T):
# NVIDIA's Isaac-GR00T at a pinned commit with its own locked environment
# (scripts/install-gr00t.sh). gr00t_server.py runs with that environment's Python, offline:
# both folders come from the caravan's library, brought by the scout, and the hub is never asked.
set -euo pipefail
GR00T_HOME="${GR00T_HOME:-$HOME/Isaac-GR00T}"
PY="$GR00T_HOME/.venv/bin/python"

SERVER=""
for cand in "$(dirname "$0")/gr00t_server.py" "$HOME/gr00t_server.py"; do
  [ -f "$cand" ] && SERVER="$cand" && break
done
if [ -z "$SERVER" ]; then
  echo "gr00t: gr00t_server.py not found beside the launcher or in \$HOME" >&2
  exit 1
fi
if [ ! -x "$PY" ]; then
  echo "gr00t: no Isaac-GR00T at $GR00T_HOME — its .venv/bin/python is missing; install it with the caravan's scripts/install-gr00t.sh" >&2
  exit 1
fi

export GR00T_HOME HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
exec "$PY" "$SERVER" "$@"
