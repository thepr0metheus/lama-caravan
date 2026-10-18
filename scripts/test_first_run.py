#!/usr/bin/env python3
"""Value snapshot: the first run — /setup makes the first account and goes
straight to the board; the fleet token waits in System → Security.

Until 2026-10-07 the page showed the fleet token after the account, "copy it now
and add to every caravan-scout". That step was from before scouts were added
from the board, which hands them the token itself, and a first user with no
scouts did not know what to make of it. The page also said "Sign in" where
nobody was signing in, and called the controller "open" when, since 1.3.453,
nothing but this page answers.

caravan/admin/auth.py renders the page and its language table; the setup and
fleet-token routes answer through a real server on a throwaway data folder.

Run: python3 scripts/test_first_run.py
"""
import http.client
import json
import os
import re
import secrets
import socket
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="caravan-first-run-"))
os.environ["CARAVAN_DATA_DIR"] = str(TMP)
for _d in ("state", "config", "secrets", "logs"):
    (TMP / _d).mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT))

from _ports import free_port  # noqa: E402

from http.server import ThreadingHTTPServer  # noqa: E402

from caravan.admin import auth  # noqa: E402
from caravan.admin import routes as routes_mod  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


print("the page:")
setup, login = auth.setup_page(), auth.login_page()
check('<p class="sub" data-i18n="subSetup">Create the first account</p>' in setup
      and '<p class="sub" data-i18n="sub">' not in setup,
      "/setup says what it is: the first account, not a sign-in (the shared language table keeps both titles)")
check("this controller answers nothing but this page" in setup.split("var M = {")[0]
      and "open page" not in setup.split("var M = {")[0],
      "negative: the note's default text, before any language applies, no longer calls the controller open")
check('data-i18n="sub">Sign in to the fleet controller<' in login,
      "negative: /login keeps its own words")
check('if (res.ok && res.j.ok) { window.location = "/board"; }' in setup and 'id="tokenBox"' not in setup
      and 'data-t="setup-token' not in setup and 'data-t="setup-go-board"' not in setup,
      "after the account, straight to the board — no fleet token box, no second button")

print("the language table:")
table = re.search(r"var M = \{\n(.*?)\n  \};", setup, re.S).group(1)
rows = dict(re.findall(r"^    ([a-z]{2}):\{(.*)\},?$", table, re.M))
check(len(rows) == 20, f"twenty languages ({len(rows)})")
missing = sorted(lang for lang, row in rows.items() if 'subSetup:"' not in row or 'setupNote:"' not in row)
check(not missing, f"every language has the setup page's title and note (missing: {missing})")
stale = sorted(lang for lang, row in rows.items() if "tokenIntro:" in row or "goBoard:" in row)
check(not stale, f"negative: the token box's strings are gone from every language (left: {stale})")
check("this controller answers nothing but this page" in rows.get("en", "") and "open page" not in rows.get("en", ""),
      "negative: the note no longer calls the controller open")


class _Quiet(routes_mod.Handler):
    def log_message(self, *args):
        pass


PORT = free_port()
_srv = ThreadingHTTPServer(("127.0.0.1", PORT), _Quiet)
threading.Thread(target=_srv.serve_forever, daemon=True).start()


def call(method, path, body=None, cookie=""):
    conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=15)
    headers = {"Content-Type": "application/json"}
    if cookie:
        headers["Cookie"] = cookie
    conn.request(method, path, body=None if body is None else json.dumps(body), headers=headers)
    resp = conn.getresponse()
    text = resp.read().decode("utf-8", "replace")
    conn.close()
    try:
        data = json.loads(text)
    except ValueError:
        data = None
    return resp.status, resp.getheader("Location"), resp.getheader("Set-Cookie") or "", data


print("the first account, through the real routes:")
check(call("GET", "/board")[:2] == (302, "/setup"), "before it: the board leads to /setup")
status, _loc, cookie, answer = call("POST", "/api/auth/setup",
                                    {"username": "first-run", "password": secrets.token_urlsafe(18)})
session = cookie.split(";", 1)[0]
made = str(auth.fleet_token_get() or "")
check(status == 200 and set(answer or {}) == {"ok", "user"} and answer.get("user") == "first-run",
      f"the answer is the account, without the fleet token ({sorted(answer or {})})")
check(session.startswith("caravan_session=") and call("GET", "/board", cookie=session)[0] == 200,
      "its session opens the board at once")
check(made.startswith("caravan-"),
      "the fleet token is made with the account, before anyone asks to see it: adding a scout hands it over")
check(call("GET", "/setup")[:2] == (302, "/login") and call("GET", "/board")[:2] == (302, "/login"),
      "negative: after it, /setup and the board without a session lead to sign-in")
status, _loc, _c, token = call("POST", "/api/auth/fleet-token", {}, cookie=session)
check(status == 200 and str((token or {}).get("fleetToken") or "").startswith("caravan-"),
      "the fleet token waits in System → Security: the admin's session shows it")
check(call("POST", "/api/auth/fleet-token", {})[0] == 401, "negative: without a session it is not shown")

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail:
        print("  - " + m)
    sys.exit(1)
print("first run snapshot holds")
