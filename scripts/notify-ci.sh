#!/usr/bin/env bash
# Tell an external test suite that a new version is live.
#
# WHY THIS EXISTS. The E2E suite lives in its own repository and runs against a
# DEPLOYMENT, not against a commit. Tests that sit beside an application run on
# its code before it ships; these cannot — so without a nudge from this side, the
# answer to "did that release break anything" arrives whenever the next schedule
# fires, up to a day later.
#
# WHY IT NAMES NOTHING. Every value comes from the environment: the URL, the
# token, nothing hardcoded. That keeps the credential out of the repository —
# which is the point — and it keeps this file portable, since any CI that starts
# a run from an authenticated POST works unchanged.
#
#   CARAVAN_CI_DISPATCH_URL   full endpoint that starts the run
#   CARAVAN_CI_TOKEN          credential for it; header form is CI-specific
#   CARAVAN_CI_AUTH_HEADER    optional, default "Authorization: token <TOKEN>"
#   CARAVAN_CI_REF            optional branch, default "main"
#
# Unset any of the first two and this exits 0 in silence: a deploy on a machine
# with no CI attached must not print errors about it, and this must never be the
# reason a release fails. The tests are a report on the deploy, not a gate on it.
#
#   bash scripts/notify-ci.sh [reason]
set -uo pipefail

REASON="${1:-deploy}"
URL="${CARAVAN_CI_DISPATCH_URL:-}"
TOKEN="${CARAVAN_CI_TOKEN:-}"
REF="${CARAVAN_CI_REF:-main}"

[ -n "$URL" ] && [ -n "$TOKEN" ] || exit 0

cd "$(dirname "$0")/.." || exit 0

# Read the version the same way the application does, so the number sent is the
# number /health will report — that comparison is the whole value of sending it.
VERSION=$(python3 -c 'import sys; sys.path.insert(0, "."); import caravan; print(caravan.__version__)' 2>/dev/null || echo "")
COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "")

AUTH="${CARAVAN_CI_AUTH_HEADER:-Authorization: token ${TOKEN}}"

BODY=$(python3 - "$REF" "$VERSION" "$COMMIT" "$REASON" <<'PY'
import json, sys
ref, version, commit, reason = sys.argv[1:5]
print(json.dumps({"ref": ref, "return_run_info": True,
                  "inputs": {"version": version, "commit": commit, "reason": reason}}))
PY
)

# --max-time so a CI host that is down cannot hold up a deploy, and the body is
# kept so a failure says WHY rather than just failing.
OUT=$(curl -sS --max-time 15 -w '\n%{http_code}' -X POST \
        -H "$AUTH" -H "Content-Type: application/json" \
        "$URL" -d "$BODY" 2>&1) || {
  echo "notify-ci: could not reach the CI host — deploy is unaffected" >&2
  exit 0
}

CODE=$(printf '%s' "$OUT" | tail -n1)
PAYLOAD=$(printf '%s' "$OUT" | sed '$d')

case "$CODE" in
  2*) echo "notify-ci: asked for a run of $VERSION ($COMMIT)"
      # The dispatch itself answers with an EMPTY body — 201 and 204 both carry
      # nothing, and the API's schema declares no response at all, so there is
      # no link to parse out of it. Ask for the run separately.
      #
      # Derived from the dispatch URL rather than configured again: the two
      # differ only in the tail, and a second variable is a second thing to get
      # out of step.
      RUNS_URL=$(printf '%s' "$URL" | sed 's#/actions/workflows/[^/]*/dispatches$#/actions/runs#')
      [ "$RUNS_URL" = "$URL" ] || RUN_COMMIT="$COMMIT" python3 - "$RUNS_URL" "$AUTH" <<'PY' 2>/dev/null
import json, os, sys, time, urllib.request

url, auth = sys.argv[1], sys.argv[2]
name, _, value = auth.partition(":")
want = os.environ.get("RUN_COMMIT", "")

# The run does not exist the instant the dispatch returns, so give it a moment.
# Three tries and out: this is a convenience line in a deploy log, and a deploy
# must not sit waiting on one.
for attempt in range(3):
    time.sleep(1.0 if attempt else 0.4)
    try:
        req = urllib.request.Request(url, headers={name.strip(): value.strip()})
        with urllib.request.urlopen(req, timeout=8) as resp:
            runs = json.loads(resp.read().decode("utf-8")).get("workflow_runs") or []
    except Exception:
        break
    # Oldest first, and neither `limit` nor `event` is honoured — so walk back
    # from the end and match on the commit we just sent, which is the only thing
    # that identifies OUR run among concurrent ones.
    for run in reversed(runs):
        if run.get("trigger_event") != "workflow_dispatch":
            continue
        try:
            inputs = json.loads(run.get("event_payload") or "{}").get("inputs") or {}
        except Exception:
            inputs = {}
        if want and inputs.get("commit") != want:
            continue
        if run.get("html_url"):
            print("           " + str(run["html_url"]))
        raise SystemExit
PY
      ;;
  404) echo "notify-ci: 404 — the workflow filename in the URL is wrong, or the token cannot write to that repo" >&2 ;;
  401|403) echo "notify-ci: $CODE — the token was rejected" >&2 ;;
  *)  echo "notify-ci: HTTP $CODE" >&2
      printf '%s\n' "$PAYLOAD" | head -c 300 >&2 ;;
esac
exit 0
