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
      # Print the run's URL when the CI returns one, so whoever deployed can
      # follow it instead of going to look for it.
      printf '%s' "$PAYLOAD" | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit()
for k in ("url", "html_url"):
    run = d.get("run") if isinstance(d.get("run"), dict) else d
    if isinstance(run, dict) and run.get(k):
        print("           " + str(run[k])); break' 2>/dev/null ;;
  404) echo "notify-ci: 404 — the workflow filename in the URL is wrong, or the token cannot write to that repo" >&2 ;;
  401|403) echo "notify-ci: $CODE — the token was rejected" >&2 ;;
  *)  echo "notify-ci: HTTP $CODE" >&2
      printf '%s\n' "$PAYLOAD" | head -c 300 >&2 ;;
esac
exit 0
