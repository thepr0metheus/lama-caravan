#!/usr/bin/env python3
"""Boot smoke: the controller starts from this tree and answers what a fresh one answers.

A fresh controller is closed (be41edff, 2026-10-07): before the first account only the
public routes answer — pages lead to /setup and every other route is 401. The CI step
this replaces still asked a fresh controller for /api/state with `curl -f`, took the 401
for a broken boot, and was red from that day on an intact tree. It also started
`python3 app.py &` and never stopped it: on a local run the server held the step's output
open, and with the state it shared with every earlier run (/tmp/ci) a second run met an
account the first had left.

So this asks what the guard says it answers (routes.py `_auth_guard`, route_access.py),
makes the first account as the setup page does, and asks again as that account. It
starts its own controller: its own data folder and home (CARAVAN_DATA_DIR, HOME — nothing
of the machine's real state is read or written), a free port on 127.0.0.1, and a stop on
every way out.

Exit codes: 0 every answer as expected, 1 an answer was not, 2 the server did not start.

Run: python3 scripts/check_boot_smoke.py
"""
from __future__ import annotations

import http.client
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class Answer:
    """One HTTP answer: its status, headers and body, read whole."""

    def __init__(self, status: int, headers: dict, body: bytes):
        self.status = status
        self.headers = headers
        self.body = body

    def json(self):
        try:
            return json.loads(self.body.decode("utf-8"))
        except ValueError:
            return None

    def header(self, name: str) -> str:
        return self.headers.get(name.lower(), "")


class BootSmoke:
    """A controller of this tree, started for the checks and stopped after them."""

    #: How long the server may take to answer its first /health.
    START_SECONDS = 45
    USER = "ci-smoke"

    def __init__(self, root: Path = ROOT):
        self.root = root
        self.tmp = Path(tempfile.mkdtemp(prefix="caravan-boot-smoke-"))
        self.port = self.free_port()
        self.proc: subprocess.Popen | None = None
        self.log = self.tmp / "server.log"
        self.failures: list[str] = []
        self.checks = 0

    @staticmethod
    def free_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]

    def env(self) -> dict:
        """The environment the server starts with: this machine's PATH and language, and
        nothing of its state — every path below one fresh folder."""
        home = self.tmp / "home"
        home.mkdir(parents=True, exist_ok=True)
        keep = {k: v for k, v in os.environ.items() if k in ("PATH", "LANG", "LC_ALL", "TZ", "SYSTEMROOT")}
        return {**keep, "HOME": str(home), "CARAVAN_DATA_DIR": str(self.tmp / "data"),
                "LLAMACPP_ADMIN_HOST": "127.0.0.1", "LLAMACPP_ADMIN_PORT": str(self.port),
                "PYTHONDONTWRITEBYTECODE": "1"}

    def start(self) -> bool:
        """Start the server and wait for its first /health; False when it never answers."""
        with open(self.log, "wb") as out:
            self.proc = subprocess.Popen([sys.executable, "app.py"], cwd=self.root, env=self.env(),
                                         stdout=out, stderr=subprocess.STDOUT)
        deadline = time.time() + self.START_SECONDS
        while time.time() < deadline:
            if self.proc.poll() is not None:
                return False
            try:
                if self.get("/health").status == 200:
                    return True
            except OSError:
                pass
            time.sleep(0.5)
        return False

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=5)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def request(self, method: str, path: str, body: dict | None = None, cookie: str = "") -> Answer:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        headers = {"Cookie": cookie} if cookie else {}
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        try:
            conn.request(method, path, body=data, headers=headers)
            resp = conn.getresponse()
            return Answer(resp.status, {k.lower(): v for k, v in resp.getheaders()}, resp.read())
        finally:
            conn.close()

    def get(self, path: str, cookie: str = "") -> Answer:
        return self.request("GET", path, cookie=cookie)

    def check(self, cond: bool, msg: str) -> None:
        self.checks += 1
        print(("  ok  " if cond else " FAIL ") + msg)
        if not cond:
            self.failures.append(msg)

    def fresh(self) -> None:
        """Before the first account: the public routes answer, pages lead to /setup,
        everything else is 401 with the reason."""
        print("before the first account:")
        health = self.get("/health").json() or {}
        self.check(health.get("ok") is True and health.get("service") == "lama-caravan"
                   and health.get("setupRequired") is True and health.get("authRequired") is True,
                   f"/health answers and says the first account is still to be made (got {health})")
        me = self.get("/api/auth/me").json() or {}
        self.check(me.get("enabled") is False and me.get("authenticated") is False,
                   f"/api/auth/me: sign-in not on yet, nobody signed in (got {me})")
        for page in ("/", "/login"):
            ans = self.get(page)
            self.check(ans.status == 302 and ans.header("Location") == "/setup",
                       f"{page} leads to /setup (got {ans.status} {ans.header('Location')!r})")
        setup = self.get("/setup")
        self.check(setup.status == 200 and b'data-t="setup-form"' in setup.body,
                   f"/setup shows the first account's form (got {setup.status})")
        state = self.get("/api/state")
        self.check(state.status == 401 and (state.json() or {}).get("error")
                   == "no account yet: create the first one at /setup",
                   f"/api/state is closed and says why: no open door before the first account "
                   f"(got {state.status} {state.body[:80]!r})")
        spec = self.get("/openapi.json")
        self.check(spec.status == 200 and (spec.json() or {}).get("openapi") == "3.1.0",
                   f"/openapi.json is open, as the home rule asks (got {spec.status})")

    def first_account(self) -> str:
        """Make the first account as the setup page does; the session cookie it set."""
        print("the first account:")
        password = secrets.token_urlsafe(18)      # this run's only; never printed
        made = self.request("POST", "/api/auth/setup", {"username": self.USER, "password": password})
        cookie = made.header("Set-Cookie").split(";", 1)[0]
        self.check(made.status == 200 and (made.json() or {}).get("ok") is True
                   and cookie.startswith("caravan_session="),
                   f"POST /api/auth/setup makes it and signs it in (got {made.status}, cookie set: "
                   f"{cookie.startswith('caravan_session=')})")
        again = self.request("POST", "/api/auth/setup", {"username": "other", "password": password})
        self.check(again.status == 409, f"a second first account is refused, 409 (got {again.status})")
        return cookie

    def signed_in(self, cookie: str) -> None:
        print("with the account:")
        health = self.get("/health").json() or {}
        self.check(health.get("setupRequired") is False, f"/health: setup done (got {health.get('setupRequired')})")
        me = self.get("/api/auth/me", cookie).json() or {}
        self.check(me.get("authenticated") is True and me.get("role") == "admin" and me.get("user") == self.USER,
                   f"/api/auth/me knows the account, an admin (got {me})")
        state = self.get("/api/state", cookie)
        self.check(state.status == 200 and isinstance(state.json(), dict),
                   f"/api/state answers the account (got {state.status})")
        root = self.get("/", cookie)
        self.check(root.status == 302 and root.header("Location") == "/board",
                   f"/ leads the account to the board (got {root.status} {root.header('Location')!r})")
        board = self.get("/board", cookie)
        self.check(board.status == 200 and "text/html" in board.header("Content-Type"),
                   f"the board's page answers the account (got {board.status})")
        print("without it:")
        state = self.get("/api/state")
        self.check(state.status == 401 and (state.json() or {}).get("error") == "authentication required",
                   f"/api/state wants a session (got {state.status} {state.body[:60]!r})")
        for page in ("/", "/board", "/setup"):
            ans = self.get(page)
            self.check(ans.status == 302 and ans.header("Location") == "/login",
                       f"{page} leads to /login now (got {ans.status} {ans.header('Location')!r})")

    def run(self) -> int:
        try:
            if not self.start():
                tail = self.log.read_text(errors="replace")[-1500:] if self.log.exists() else ""
                print(f"boot smoke: FAILED — the server did not answer /health on 127.0.0.1:{self.port} "
                      f"within {self.START_SECONDS} s (exit {self.proc.poll() if self.proc else None})\n{tail}")
                return 2
            self.fresh()
            self.signed_in(self.first_account())
        finally:
            self.stop()
        if self.failures:
            print(f"\nboot smoke: FAILED ({len(self.failures)} of {self.checks}):")
            for msg in self.failures:
                print("  - " + msg)
            return 1
        print(f"\nboot smoke OK: {self.checks} answers as a fresh controller and its first account give them")
        return 0


if __name__ == "__main__":
    sys.exit(BootSmoke().run())
