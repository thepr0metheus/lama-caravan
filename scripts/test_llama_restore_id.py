#!/usr/bin/env python3
"""Restoring an archived llama.cpp build needs the id of one.

The controller restores its own machine's build with `install-llama.sh
--restore <id>`, and a client machine's through its scout's
`/api/llama-node/restore`. A scout (2.21) takes an empty id for an ordinary
update: a `git pull` and a rebuild, a different job from the one the operator
asked for, started on a machine where they wanted to go back.

The controller's own path refused an empty id from the start. The fleet path
forwarded whatever it was given, so a body with no `id` on
POST /api/fleet/llama-restore became an update. One fact, two copies, one of
them missing the check — so both are driven here against the same list of
blank ids, and must refuse in the same words.

The fleet path runs against a real HTTP server standing in for the scout, and
what the server received is what is counted: "refused" is only true if nothing
arrived.
"""
import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("CARAVAN_DATA_DIR", tempfile.mkdtemp(prefix="caravan-restore-id-"))
sys.path.insert(0, str(ROOT))

PASS, FAIL = [], []
RECEIVED = []          # (path, body) of every request the stand-in scout got


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    if not cond and detail:
        print(f"       {detail}")


class StandInScout(BaseHTTPRequestHandler):
    """Answers a restore the way a scout does: with the status of the job."""

    def log_message(self, *a):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        RECEIVED.append((self.path, json.loads(self.rfile.read(length) or b"{}")))
        body = json.dumps({"running": True, "tag": "restore"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def outcome(fn, *args, **kwargs):
    from caravan.common.errors import AppError
    try:
        return {"ok": fn(*args, **kwargs)}
    except AppError as exc:
        return {"refused": str(exc), "status": exc.status}


# What arrives when nobody named a build: nothing, a blank, a non-string.
BLANK_IDS = [("no id at all", None), ("an empty id", ""), ("a blank id", "   ")]


def main():
    from caravan.admin import fleet_clients as fc
    from caravan.admin import status
    from caravan.admin.state import topology as topo

    srv = HTTPServer(("127.0.0.1", 0), StandInScout)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    fc._scout_headers = lambda: {}
    topo.hosts()["h"] = {"id": "h", "agentUrl": f"http://127.0.0.1:{srv.server_port}"}

    started = []          # what the controller's own path asked its runner for
    status.start_llama_update = lambda tag="", restore_id="": started.append(restore_id) or {"running": True}

    # ── a build id that names nothing is refused, on both paths, in one voice ──
    for label, blank in BLANK_IDS:
        del RECEIVED[:], started[:]
        fleet = outcome(fc.client_llama_restore, {"hostId": "h", "id": blank})
        local = outcome(status.start_llama_restore, blank)
        check(f"fleet restore, {label}: refused as missing, with a 400",
              fleet.get("refused") == "build id is required" and fleet.get("status") == 400, str(fleet))
        check(f"fleet restore, {label}: the scout is not asked", RECEIVED == [], str(RECEIVED))
        check(f"controller restore, {label}: refused in the same words",
              (local.get("refused"), local.get("status")) == (fleet.get("refused"), fleet.get("status")),
              f"{local} vs {fleet}")
        check(f"controller restore, {label}: no job is started", started == [], str(started))
    del RECEIVED[:]
    left_out = outcome(fc.client_llama_restore, {"hostId": "h"})
    check("fleet restore: a body without the key is the same refusal, not an update",
          left_out.get("refused") == "build id is required" and RECEIVED == [], f"{left_out} {RECEIVED}")
    nobody = outcome(fc.client_llama_restore, None)
    check("fleet restore: no body at all is refused too", "refused" in nobody and RECEIVED == [], str(nobody))

    # ── and a build that is named goes through, as it did ───────────────────
    del RECEIVED[:], started[:]
    sent = outcome(fc.client_llama_restore, {"hostId": "h", "id": "b2"})
    check("fleet restore: the id goes to the scout's restore, and nowhere else",
          RECEIVED == [("/api/llama-node/restore", {"id": "b2"})], str(RECEIVED))
    check("fleet restore: the scout's answer is the answer",
          sent == {"ok": {"running": True, "tag": "restore"}}, str(sent))
    del RECEIVED[:]
    outcome(fc.client_llama_restore, {"hostId": "h", "id": "  b2  "})
    check("fleet restore: an id padded with spaces is sent trimmed (as it always was)",
          RECEIVED == [("/api/llama-node/restore", {"id": "b2"})], str(RECEIVED))
    outcome(status.start_llama_restore, " b1 ")
    check("controller restore: a named build starts the runner with that id, trimmed",
          started == ["b1"], str(started))

    # ── a missing machine is still its own refusal ──────────────────────────
    del RECEIVED[:]
    no_host = outcome(fc.client_llama_restore, {"id": "b2"})
    check("fleet restore: a build without a machine is the machine's refusal, and nothing is sent",
          no_host.get("refused") == "hostId is required" and no_host.get("status") == 400 and RECEIVED == [],
          f"{no_host} {RECEIVED}")
    unknown = outcome(fc.client_llama_restore, {"hostId": "nobody", "id": "b2"})
    check("fleet restore: a machine that never reported is a 404, as before",
          unknown.get("status") == 404 and RECEIVED == [], f"{unknown} {RECEIVED}")

    srv.shutdown()
    print(f"\n  {len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
