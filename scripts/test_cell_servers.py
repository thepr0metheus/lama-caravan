#!/usr/bin/env python3
"""Cell servers, at the one moment they are most likely to lie: when they could
not load.

Three bugs in a single day lived in cells/, and every one of them was a failure
that looked like a success. whisper answered 200 with an empty transcript when
transcription threw. NLLB reported `langs: 0` from an exception its own
try/except had swallowed. seamless silently dropped a language from its list.
All three were found by hand, because nothing here has ever been tested.

The invariant this pins is the one they broke, and it is the same for all six:

    A cell that could not load says so — on /health AND on its work endpoint —
    and never answers success.

That is testable without a GPU, without weights and without torch: point each
server at a model that cannot resolve, with the hub forced offline, and the load
must fail the same way everywhere. A machine that HAS torch fails on the missing
model instead of the missing import; the assertion is about what the server
does with a failure, not about which failure it got.

And the test must not lie about a cell either. Two of its waits read the clock
instead of the cell (found 2026-10-07: one run of the CI list in eight parallel
jobs said "30 passed, 1 failed"):

  * The port is picked by binding 0 and closing, and the cell binds it again
    itself. Under parallel jobs another process can take it in between: the cell
    died with "Address already in use", the test waited 25 s on a dead process,
    said only "no answer", and dropped that cell's other four checks from the
    count — 31 instead of 35. A lost race is now started again on another port;
    any other death is reported at once, in the cell's own words; a check that
    was not reached is counted as failed, not left out.
  * "Give the load a moment" stopped at the first answer that was not 200, and
    "loading" is one. On a slow machine the next check read "loading", which
    carries no reason. The wait is now for an answer that can be judged: ok, or
    a refusal that says why.

Both waits are pinned first, on a fake cell, before the real cells run.
"""
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CELLS = ROOT / "cells"

PASS, FAIL = [], []

# name → (argv after the port, path that does the work)
# The work path matters: /health is the one endpoint everybody remembers to get
# right. whisper and tts accept a POST on any path, so theirs is nominal.
SERVERS = {
    "whisper_server.py":    (["tiny"], "/v1/audio/transcriptions"),
    "moonshine_server.py":  (["en"], "/v1/audio/transcriptions"),
    "transcribe_server.py": (["/nonexistent/model.gguf"], "/v1/audio/transcriptions"),
    "seamless_server.py":   (["does-not/exist", "rus"], "/v1/audio/translations"),
    "translate_server.py":  (["does-not/exist", "eng_Latn", "rus_Cyrl"], "/v1/translate"),
    "tts_server.py":        (["does-not-exist"], "/v1/audio/speech"),
    # port 1 on loopback: no engine answers there, so the cell waits, and says what it waits on
    "engine_cell_server.py": (["ollama", "1", "does-not-exist"], "/v1/chat/completions"),
    # No checkpoint and no Isaac-GR00T here: it refuses on the folder before it imports anything.
    "gr00t_server.py":      (["does-not/exist", "--backbone", "does-not/exist"], "/v1/robot/predict"),
    # A model folder that is not there: it refuses on the folder, before it imports torch.
    "lfm_audio_server.py":  (["does-not/exist"], "/v1/audio/speech"),
}


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}{'' if cond else '  — ' + str(detail)[:160]}")


from _ports import free_port  # noqa: E402


def get(url, data=None, timeout=5):
    """(status, body) — an HTTP error is an ANSWER here, not an exception."""
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001
        return 0, f"{type(exc).__name__}: {exc}"


def has_reason(body):
    """A refusal has to say why. An empty body, or one whose only content is a
    status word, leaves the caller to guess — which is how a broken cell reads
    as a quiet one."""
    try:
        data = json.loads(body)
    except Exception:  # noqa: BLE001
        return bool(body.strip())
    if not isinstance(data, dict):
        return bool(body.strip())
    for key in ("error", "detail", "message", "reason"):
        if str(data.get(key) or "").strip():
            return True
    return False


def claims_ok(status, body):
    """Whether an answer claims a working cell: 200 with status ok."""
    if status != 200:
        return False
    try:
        return json.loads(body).get("status") == "ok"
    except Exception:  # noqa: BLE001
        return '"ok"' in body


def is_cell_health(body):
    """Whether a /health answer is a cell's: the fields every cell's carries
    (cells/cell_base.py), whatever its state. Anything else on the port is
    another process's answer."""
    try:
        data = json.loads(body)
    except Exception:  # noqa: BLE001
        return False
    return isinstance(data, dict) and all(k in data for k in ("engine", "source", "kinds"))


def tail(text, lines=3):
    return " | ".join(line.strip() for line in text.strip().splitlines()[-lines:]) or "(it printed nothing)"


CELL_ENV = dict(os.environ, HF_HUB_OFFLINE="1",          # the failure must not depend on the network
                TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1")
RACE_RETRIES = 3          # fresh ports after a lost race; more than that is not a race
START_DEADLINE = 25       # seconds for a live cell to answer /health at all
SETTLE_DEADLINE = 20      # seconds for a failing load to say why


class CellRun:
    """One cell process on a port it really holds, and what it said.

    The port comes from binding 0 and closing; the cell binds it again itself,
    and another process may take it in between. That race is not the cell's
    fault, so it is run again on a fresh port. Every other way of not starting
    is the cell's, and is reported in its own words.
    """

    def __init__(self, script, args, *, cells=CELLS, pick=free_port):
        self.script, self.args, self.cells, self.pick = script, list(args), Path(cells), pick
        self.proc = None
        self.port = 0
        self.races = 0
        self.first = (0, "")     # the first /health answer the start saw
        self.why = ""            # why it did not start

    def url(self, path):
        return f"http://127.0.0.1:{self.port}{path}"

    def start(self):
        """True once a cell answers /health on its port as a cell."""
        foreign = 0
        for _ in range(RACE_RETRIES + 1):
            self.port = self.pick()
            self.proc = subprocess.Popen(
                [sys.executable, str(self.cells / self.script), str(self.port), *self.args],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=CELL_ENV, start_new_session=True)
            seen = self._first_answer()
            if seen == "cell":
                return True
            printed = self.stop()
            if seen == "dead" and "Address already in use" in printed:
                self.races += 1
                continue
            if seen == "foreign":
                # macOS lets a wildcard bind share a port with a loopback one: the
                # cell came up, and /health on 127.0.0.1 reached the other process.
                self.races += 1
                foreign += 1
                continue
            self.why = (f"the cell exited: {tail(printed)}" if seen == "dead"
                        else f"no answer on /health within {START_DEADLINE}s")
            return False
        self.why = (f"{self.races} starts in a row: the port was another process's"
                    + (f" ({foreign} times an answer that is no cell's /health — another process, or this"
                       " cell's /health lost engine/source/kinds)" if foreign else ""))
        return False

    def _first_answer(self):
        end = time.monotonic() + START_DEADLINE
        while time.monotonic() < end:
            if self.proc.poll() is not None:
                return "dead"
            status, body = get(self.url("/health"), timeout=2)
            if status:
                self.first = (status, body)
                return "cell" if is_cell_health(body) else "foreign"
            time.sleep(0.1)
        return "silent"

    def settled_health(self):
        """/health once the cell has something to say: ok, or a refusal with its
        reason. "starting" and "loading" are neither, and a slow machine shows
        them first. Past the deadline, the last answer is what there is."""
        end = time.monotonic() + SETTLE_DEADLINE
        while True:
            status, body = get(self.url("/health"))
            if claims_ok(status, body) or (status and has_reason(body)):
                return status, body
            if time.monotonic() >= end:
                return status, body
            time.sleep(0.2)

    def stop(self):
        """Stop the cell; answer what it printed."""
        if self.proc is None:
            return ""
        if self.proc.poll() is None:
            try:
                os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
            except Exception:  # noqa: BLE001
                self.proc.terminate()
        try:
            out, _ = self.proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            out, _ = self.proc.communicate()
        self.proc = None
        return (out or b"").decode("utf-8", "replace")


CHECKS = ("answers HTTP before the model is ready", "/health does not claim ok after a failed load",
          "/health carries a reason", "refuses work while broken", "the refusal says why")


def exercise(script, extra_args, work_path, *, cells=CELLS, record=check):
    cell = CellRun(script, extra_args, cells=cells)
    try:
        started = cell.start()
        record(f"{script}: {CHECKS[0]}", started, cell.why)
        if not started:
            # Not reached is not passed: left out, these four made a run with a
            # dead cell count 31 checks instead of 35.
            for name in CHECKS[1:]:
                record(f"{script}: {name}", False, "not reached: the cell did not start")
            return
        status, body = cell.settled_health()
        record(f"{script}: {CHECKS[1]}", not claims_ok(status, body), f"{status} {body[:120]}")
        record(f"{script}: {CHECKS[2]}", has_reason(body), body[:160])

        # The work endpoint is where the lie used to be told.
        status, body = get(cell.url(work_path), data=b'{"malformed":true}')
        record(f"{script}: {CHECKS[3]}", status != 0 and not (200 <= status < 300), f"{status} {body[:120]}")
        record(f"{script}: {CHECKS[4]}", has_reason(body), f"{status} {body[:160]}")
    finally:
        cell.stop()


# A cell that does nothing, built on the same base: "crash" dies before it
# binds; otherwise its load waits for a file to appear and then fails.
FAKE_CELL = """
import os, sys, time
sys.path.insert(0, {cells!r})
from cell_base import CellServer


class Fake(CellServer):
    engine = "fake"
    model_name = "nothing"
    kinds = ["asr"]

    def load(self):
        gate = self.args[1] if len(self.args) > 1 else ""
        while gate and not os.path.exists(gate):
            time.sleep(0.05)
        raise RuntimeError("no model here, on purpose")

    def handle(self, body, headers, path):
        return 500, b'{{"error": "never loaded"}}', "application/json"


if __name__ == "__main__":
    if sys.argv[2:3] == ["crash"]:
        raise SystemExit("this cell breaks before it binds, on purpose")
    Fake().serve()
"""


class _NotACell(BaseHTTPRequestHandler):
    """Another process's server: it answers, but not as a cell."""

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *args):
        pass


def harness_checks():
    """The waits, on a fake cell: a port lost to another listener, a port where
    another server answers, a load still under way when the cell first answers,
    a cell that dies on its own, and the checks a dead cell costs."""
    with tempfile.TemporaryDirectory(prefix="caravan-cell-harness-") as tmp:
        tmp = Path(tmp)
        (tmp / "fake_server.py").write_text(FAKE_CELL.format(cells=str(CELLS)), encoding="utf-8")
        gate = tmp / "load-may-fail"

        holder = socket.socket()                      # another process's listener, on every address
        holder.bind(("0.0.0.0", 0))
        holder.listen(1)
        taken = holder.getsockname()[1]
        picks = [taken]
        cell = CellRun("fake_server.py", ["gate", str(gate)], cells=tmp,
                       pick=lambda: picks.pop(0) if picks else free_port())
        try:
            started = cell.start()
            check("harness: a cell that lost its port to another listener starts again on another one",
                  started and cell.races == 1 and cell.port != taken, f"{started} {cell.races} {cell.why}")
        finally:
            cell.stop()
            holder.close()

        other = ThreadingHTTPServer(("127.0.0.1", 0), _NotACell)
        threading.Thread(target=other.serve_forever, daemon=True).start()
        taken = other.server_address[1]
        picks = [taken]
        cell = CellRun("fake_server.py", ["gate", str(gate)], cells=tmp,
                       pick=lambda: picks.pop(0) if picks else free_port())
        try:
            started = cell.start()
            # Linux refuses the cell's bind; macOS lets it share the port, and
            # then /health on 127.0.0.1 reaches the other server. Either way the
            # cell must end up on a port of its own.
            check("harness: an answer that is no cell's /health is another process's — the cell starts elsewhere",
                  started and cell.races == 1 and cell.port != taken, f"{started} {cell.races} {cell.why}")
        finally:
            cell.stop()
            other.shutdown()
            other.server_close()

        cell = CellRun("fake_server.py", ["gate", str(gate)], cells=tmp)
        try:
            started = cell.start()
            check("harness: while the load is under way, the first answer gives no reason yet",
                  started and not has_reason(cell.first[1]), str(cell.first)[:160])
            status, body = 0, ""
            if started:
                threading.Timer(0.3, gate.touch).start()
                status, body = cell.settled_health()
            check("harness: the wait goes on until the failed load says why",
                  status == 500 and has_reason(body), f"{status} {body[:160]}")
        finally:
            cell.stop()

        crashed = CellRun("fake_server.py", ["crash"], cells=tmp)
        try:
            started = crashed.start()
            check("harness: a cell that dies on its own is reported in its words, not started again",
                  not started and crashed.races == 0 and "on purpose" in crashed.why, crashed.why)
        finally:
            crashed.stop()

        seen = []
        exercise("fake_server.py", ["crash"], "/v1/x", cells=tmp, record=lambda n, ok, d="": seen.append(ok))
        check("harness: a cell that does not start costs all five checks, not one", seen == [False] * 5, str(seen))


def main():
    missing = [n for n in SERVERS if not (CELLS / n).is_file()]
    if missing:
        print(f"cell servers: FAILED — not found: {missing}", file=sys.stderr)
        return 1
    # Every *_server.py must be listed, or a cell added later goes untested in
    # the exact way these six were until now.
    on_disk = {p.name for p in CELLS.glob("*_server.py")}
    unlisted = sorted(on_disk - set(SERVERS))
    if unlisted:
        print(f"cell servers: FAILED — not covered by this test: {unlisted}\n"
              f"  add it to SERVERS with its work endpoint.", file=sys.stderr)
        return 1

    print("— the harness itself, on a fake cell")
    harness_checks()
    for script, (args, path) in SERVERS.items():
        print(f"— {script}")
        exercise(script, args, path)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
