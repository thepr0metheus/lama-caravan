#!/usr/bin/env python3
"""Value snapshot: /healthz, the home network's liveness shape — `{status, version}`
with the commit as `version`, open without signing in, and null rather than a guess.

The NAS's deploy check compares this commit with the one it shipped (visumap
nas-apps.md); /health stays as it is for everything that already reads it.

Run: python3 scripts/test_healthz.py
"""
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from caravan.admin import routes  # noqa: E402
from caravan.admin.route_access import ROUTE_ACCESS, RouteAccess  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


class Handler:
    def __init__(self):
        self.sent = []

    def send_json(self, body, status=200):
        self.sent.append((status, body))


def answer(git_info):
    keep = routes.project_git_info
    routes.project_git_info = git_info
    try:
        h = Handler()
        routes.GET_ROUTES["/healthz"](h, urlparse("/healthz"))
        return h.sent
    finally:
        routes.project_git_info = keep


def boom():
    raise RuntimeError("git is gone")


print("/healthz:")
check(answer(lambda: {"head": "1a2b3c4", "branch": "docker"}) == [(200, {"status": "ok", "version": "1a2b3c4"})],
      "the commit as version, nothing else")
check(answer(lambda: {"head": "", "ok": False}) == [(200, {"status": "ok", "version": None})],
      "negative: no commit known — null, not an empty string or a guess")
check(answer(boom) == [(200, {"status": "ok", "version": None})],
      "a failing commit reading does not fail the liveness answer")
check(ROUTE_ACCESS.kind("GET", "/healthz") == RouteAccess.PUBLIC, "open without signing in, as /health")
check(routes.GET_ROUTES.get("/health") is not routes.GET_ROUTES.get("/healthz"),
      "negative: /health keeps its own answer for its readers")


def health(accounts):
    keep = (routes.project_git_info, routes.auth_mod.auth_enabled)
    routes.project_git_info = lambda: {"head": "1a2b3c4"}
    routes.auth_mod.auth_enabled = lambda: accounts
    try:
        h = Handler()
        routes.GET_ROUTES["/health"](h, urlparse("/health"))
        status, body = h.sent[0]
        return status, {k: body.get(k) for k in ("ok", "authRequired", "setupRequired")}
    finally:
        routes.project_git_info, routes.auth_mod.auth_enabled = keep


print("/health and the first account:")
check(health(False) == (200, {"ok": True, "authRequired": True, "setupRequired": True}),
      "a fresh install: sign-in is required, and the first account is still to be made at /setup")
check(health(True) == (200, {"ok": True, "authRequired": True, "setupRequired": False}),
      "negative: an account exists — nothing left to set up")

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail:
        print("  - " + m)
    sys.exit(1)
print("healthz snapshot holds")
