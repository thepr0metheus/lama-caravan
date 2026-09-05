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
"""
import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
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
}


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}{'' if cond else '  — ' + str(detail)[:160]}")


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


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


def wait_for_http(port, deadline=25):
    """The HTTP server starts before the model loads, so this should be quick.
    A server that only listens once its model is ready would hang the board on
    every start, which is why the timeout is short and its expiry is a failure."""
    end = time.time() + deadline
    while time.time() < end:
        status, _ = get(f"http://127.0.0.1:{port}/health", timeout=2)
        if status:
            return True
        time.sleep(0.3)
    return False


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


def exercise(script, extra_args, work_path):
    port = free_port()
    env = dict(os.environ)
    env["HF_HUB_OFFLINE"] = "1"          # the failure must not depend on the network
    env["TRANSFORMERS_OFFLINE"] = "1"
    env["HF_HUB_DISABLE_TELEMETRY"] = "1"
    proc = subprocess.Popen(
        [sys.executable, str(CELLS / script), str(port), *extra_args],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, start_new_session=True)
    try:
        if not wait_for_http(port):
            check(f"{script}: answers HTTP before the model is ready", False,
                  "no answer on /health within 25s")
            return
        check(f"{script}: answers HTTP before the model is ready", True)

        # Give the load thread a moment to reach its failure.
        deadline = time.time() + 20
        while time.time() < deadline:
            status, body = get(f"http://127.0.0.1:{port}/health")
            if status and status != 200:
                break
            if status == 200 and '"ok"' not in body:
                break
            time.sleep(0.5)

        status, body = get(f"http://127.0.0.1:{port}/health")
        check(f"{script}: /health does not claim ok after a failed load",
              not (status == 200 and '"status": "ok"' in body.replace('"status":"ok"', '"status": "ok"')),
              f"{status} {body[:120]}")
        check(f"{script}: /health carries a reason", has_reason(body), body[:160])

        # The work endpoint is where the lie used to be told.
        status, body = get(f"http://127.0.0.1:{port}{work_path}", data=b'{"malformed":true}')
        check(f"{script}: refuses work while broken", status != 0 and not (200 <= status < 300),
              f"{status} {body[:120]}")
        check(f"{script}: the refusal says why", has_reason(body), f"{status} {body[:160]}")
    finally:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except Exception:  # noqa: BLE001
            proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


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

    for script, (args, path) in SERVERS.items():
        print(f"— {script}")
        exercise(script, args, path)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
