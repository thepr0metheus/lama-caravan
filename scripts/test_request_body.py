#!/usr/bin/env python3
"""Characterization snapshot: what the admin answers to a malformed request.

Pins the STATUS and the leaked text for every shape a POST body can arrive in —
an object, nothing, and the five JSON values that are not objects — and for a
DELETE whose handler raises AppError.

The server is real: a Handler bound to a free port on a throwaway data dir, so
the assertions run through the actual dispatcher rather than a re-implementation
of it. Written before read_body learned to insist on an object.

Run: python3 scripts/test_request_body.py
"""
import http.client
import json
import os
import socket
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="caravan-reqbody-"))
os.environ["CARAVAN_DATA_DIR"] = str(TMP)
for _d in ("state", "config", "secrets", "logs"):
    (TMP / _d).mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT))

from http.server import ThreadingHTTPServer  # noqa: E402

from caravan.admin import routes as routes_mod  # noqa: E402
from caravan.common.errors import AppError  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


class _Quiet(routes_mod.Handler):
    def log_message(self, *args):
        pass


_sock = socket.socket()
_sock.bind(("127.0.0.1", 0))
PORT = _sock.getsockname()[1]
_sock.close()
_srv = ThreadingHTTPServer(("127.0.0.1", PORT), _Quiet)
threading.Thread(target=_srv.serve_forever, daemon=True).start()


def request(method, path, raw=None):
    conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=15)
    conn.request(method, path, body=raw, headers={"Content-Type": "application/json"})
    resp = conn.getresponse()
    text = resp.read().decode("utf-8", "replace")
    conn.close()
    try:
        return resp.status, (json.loads(text).get("error") or "")
    except Exception:
        return resp.status, text[:120]


# Any POST route would do; this one validates its input, so a well-formed
# object still gets a 400 and the two cases stay distinguishable.
TARGET = "/api/cloud-blocks/save"
# Python type names in an error body are an internal detail reaching a client.
LEAKS = ("object has no attribute", "Expecting value", "Traceback")


# The route validates its own input and answers 400 to every body, so a status
# alone cannot tell "the route was reached" from "read_body refused it before
# any route saw it". Both cases are 400. The WORDS are what separate them, and
# a happy-path assertion that cannot separate them cannot fail: an adversarial
# review proved this file stayed fully green against a read_body mutated to
# reject every body, valid objects included.
ROUTE_SPOKE = "block.id must be 1-48 chars"
PARSER_SPOKE = "request body "


def test_bodies():
    print("POST body shapes:")
    status, err = request("POST", TARGET, b'{"block": {}}')
    check(status == 400, f"an object is validated, not crashed on (got {status})")
    check(err.startswith(ROUTE_SPOKE),
          f"and the ROUTE is what answered, not the body parser (got {err!r})")
    check(not err.startswith(PARSER_SPOKE), "a valid object is never refused by read_body")
    check(not any(x in err for x in LEAKS), "and its error is about the request, not about Python")

    status, err = request("POST", TARGET, b"")
    check(status == 400, f"an empty body reads as an empty object (got {status})")
    check(err.startswith(ROUTE_SPOKE), f"and reaches the route too (got {err!r})")

    # A body with keys the route does not know is still an object, so it must
    # reach the route and be judged there.
    status, err = request("POST", TARGET, b'{"nonsense": 1}')
    check(err.startswith(ROUTE_SPOKE), f"an object with unknown keys reaches the route (got {err!r})")

    for label, raw, named in (("null", b"null", "null"), ("a list", b"[1,2]", "array"),
                              ("a string", b'"x"', "string"), ("a number", b"5", "number"),
                              ("a boolean", b"true", "boolean")):
        status, err = request("POST", TARGET, raw)
        check(status == 400, f"{label}: answers {status}, a client error")
        check(not any(x in err for x in LEAKS), f"{label}: no Python detail escapes — {err[:60]!r}")
        check(err == f"request body must be a JSON object, not {named}",
              f"{label}: named in JSON's vocabulary (got {err!r})")

    status, err = request("POST", TARGET, b"<html>")
    check(status == 400, f"unparseable JSON: answers {status}")
    check(err == "request body is not valid JSON", f"unparseable JSON: says so plainly (got {err!r})")
    # A body that is not UTF-8 at all takes the same path, not a 500.
    status, err = request("POST", TARGET, b"\xff\xfe{")
    check(status == 400, f"undecodable bytes: answers {status}")


def test_delete_apperror():
    print("DELETE whose handler raises AppError:")
    original = routes_mod.hf_local_delete

    def _raise(*a, **k):
        raise AppError("no such file", 404)

    routes_mod.hf_local_delete = _raise
    try:
        status, err = request("DELETE", "/api/hf/local-file?repo=r&name=n.gguf")
        check(status == 404,
              f"the AppError's own status is honoured, as on GET and POST (got {status})")
        check(err == "no such file", f"the message survives (got {err!r})")
    finally:
        routes_mod.hf_local_delete = original


for fn in (test_bodies, test_delete_apperror):
    fn()

_srv.shutdown()
print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail:
        print("  - " + m)
    sys.exit(1)
print("all request-body snapshots hold")
