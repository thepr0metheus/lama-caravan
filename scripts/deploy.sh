#!/usr/bin/env bash
# The deploy, as one command: push, pull on the controller, restart what needs
# restarting, smoke it, and tell the test suite a release happened.
#
# WHY IT EXISTS. Every step here was already written down in docs/operations.md
# and performed by hand, which works right up until the day one step is skipped.
# The last one is skipped most easily, because nothing breaks when it is: the
# tests simply do not run and the silence looks like success. The step before it
# is the second easiest — a docs-only change needs no restart, so the pull gets
# postponed, and then the controller's checkout is behind while /health still
# reports a healthy service.
#
# Configuration, all from the environment — nothing here names a host:
#   CARAVAN_DEPLOY_HOST   ssh target of the controller        (required)
#   CARAVAN_DEPLOY_PATH   its checkout, default ~/projects/lama-caravan
#   CARAVAN_CI_*          see scripts/notify-ci.sh            (optional)
#
#   bash scripts/deploy.sh [--no-restart]
set -uo pipefail

cd "$(dirname "$0")/.." || exit 1

HOST="${CARAVAN_DEPLOY_HOST:-}"
REMOTE_PATH="${CARAVAN_DEPLOY_PATH:-~/projects/lama-caravan}"
SKIP_RESTART=0
[ "${1:-}" = "--no-restart" ] && SKIP_RESTART=1

if [ -z "$HOST" ]; then
  echo "deploy: set CARAVAN_DEPLOY_HOST to the controller's ssh target" >&2
  exit 1
fi

# A dirty tree means the thing about to be deployed is not the thing on this
# screen. Refuse rather than ship a surprise.
if [ -n "$(git status --porcelain)" ]; then
  echo "deploy: working tree is dirty — commit or stash first" >&2
  git status --short >&2
  exit 1
fi

BRANCH=$(git rev-parse --abbrev-ref HEAD)
[ "$BRANCH" = "main" ] || { echo "deploy: on '$BRANCH', not main" >&2; exit 1; }

VERSION=$(python3 -c 'import sys; sys.path.insert(0, "."); import caravan; print(caravan.__version__)')
COMMIT=$(git rev-parse --short HEAD)
echo "deploy: $VERSION ($COMMIT) → $HOST"

git push -q origin main || { echo "deploy: push failed" >&2; exit 1; }

# Compile before restarting, on the machine that will run it: a syntax error
# found here costs nothing, and found by systemd costs the service.
ssh "$HOST" "cd $REMOTE_PATH && git pull --ff-only -q && \
  .venv/bin/python -m py_compile app.py agent-proxies.py \$(find caravan -name '*.py')" \
  || { echo "deploy: pull or compile failed on the controller — nothing restarted" >&2; exit 1; }

if [ "$SKIP_RESTART" = "1" ]; then
  echo "deploy: --no-restart, leaving the services alone"
else
  ssh "$HOST" "systemctl --user restart lama-caravan.service lama-caravan-proxies.service" \
    || { echo "deploy: restart failed" >&2; exit 1; }
fi

# Ask the deployed service what it is, and compare. This is the check the whole
# version-passing exists for, made locally and immediately: a deploy that
# reports success while the previous process keeps serving has no other symptom.
# Poll, don't peek once: a restart takes a second or three to bind the port, and
# a single early check reports the old version (or none) and cries MISMATCH on a
# deploy that is merely mid-restart. Six tries over ~15s covers the startup.
LIVE_V=""; LIVE_C=""
for _try in 1 2 3 4 5 6; do
  sleep 3
  LIVE=$(ssh "$HOST" "curl -s --max-time 5 localhost:7990/health") || LIVE=""
  LIVE_V=$(printf '%s' "$LIVE" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("version",""))' 2>/dev/null || echo "")
  LIVE_C=$(printf '%s' "$LIVE" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("commit",""))' 2>/dev/null || echo "")
  [ "$LIVE_V" = "$VERSION" ] && [ "$LIVE_C" = "$COMMIT" ] && break
done

if [ "$LIVE_V" != "$VERSION" ] || [ "$LIVE_C" != "$COMMIT" ]; then
  echo "deploy: MISMATCH — shipped $VERSION ($COMMIT), serving ${LIVE_V:-?} (${LIVE_C:-?})" >&2
  echo "        the old process is probably still alive" >&2
  exit 1
fi
echo "deploy: serving $LIVE_V ($LIVE_C)"

bash scripts/notify-ci.sh deploy
