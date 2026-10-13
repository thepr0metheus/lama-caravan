#!/bin/bash
# Strata cell launcher (CARAVAN command cell): Qwen3.8-Flash-Next on one card.
#
# Usage: run_strata.sh <port> <model's first GGUF part> [--mtp <mtp-q2_0.gguf>]
#                      [--context N] [--kv int8|q4_0|k8v4] [--draft-vocab cyrillic|cjk|en|fr]
#                      [--vram-reserve-mib N] [--name NAME]
#
#     bash run_strata.sh 22009 ~/models/Qwen3.8-Flash-Next-GSQ-RCO-IQ2_XS-00001-of-00002.gguf \
#         --mtp ~/models/mtp-q2_0.gguf --context 131072
#
# The engine is installed on the machine once, by Strata's own setup.sh, into
# STRATA_HOME (default ~/Strata). What Strata makes from the model at every
# start — its pack, the draft layer's runtime, its config — goes to
# CARAVAN_CELL_SCRATCH, the folder the scout empties at the cell's start and
# removes at its stop. strata_launch.py does that work with Strata's own Python.
set -euo pipefail
STRATA_HOME="${STRATA_HOME:-$HOME/Strata}"
PY="$STRATA_HOME/.venv/bin/python"

LAUNCH=""
for cand in "$(dirname "$0")/strata_launch.py" "$HOME/strata_launch.py"; do
  [ -f "$cand" ] && LAUNCH="$cand" && break
done
if [ -z "$LAUNCH" ]; then
  echo "strata: strata_launch.py not found beside the launcher or in \$HOME" >&2
  exit 1
fi
if [ ! -x "$PY" ]; then
  echo "strata: no Strata at $STRATA_HOME — its .venv/bin/python is missing; install it with Strata's setup.sh" >&2
  exit 1
fi

exec "$PY" "$LAUNCH" --strata-home "$STRATA_HOME" "$@"
