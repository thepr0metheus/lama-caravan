"""What the proxy last heard about each subscription account's limit windows.

The Codex backend states both of an account's windows on every answer, a
refusal included: `x-codex-<slot>-used-percent`, `-window-minutes` and
`-reset-at`, for the slots "primary" and "secondary" (checked against the live
backend on 2026-09-28). Nothing is asked for this: the reading rides on the
traffic the caravan sends anyway, and on the idle probe's one-token question
while the account's exit sees no traffic. The rule that reads it lives in
caravan/common/usage_reserve.py, shared with the board. The one exception is a
step that gets no traffic (UsagePage): its reading is refreshed from the
account's usage page instead.
"""
import http.client
import json
import threading
import time
from urllib.parse import urlsplit

from caravan.proxy.cloud_auth import load_provider_secret
from caravan.proxy.translate import _extract_chatgpt_account_id


class SubscriptionUsage:
    """Per account, the last reading of its windows and when it was heard."""

    SLOTS = ("primary", "secondary")

    def __init__(self):
        self._rows = {}
        self._lock = threading.Lock()

    @classmethod
    def windows_from_headers(cls, headers):
        """The windows an answer's headers state, as readings; [] when it states none."""
        items = headers.items() if isinstance(headers, dict) else (headers or [])
        low = {str(name).lower(): value for name, value in items}
        windows = []
        for slot in cls.SLOTS:
            try:
                minutes = int(low[f"x-codex-{slot}-window-minutes"])
                used = int(float(low[f"x-codex-{slot}-used-percent"]))
            except (KeyError, TypeError, ValueError):
                continue
            if minutes <= 0:
                continue
            try:
                reset_at = int(low.get(f"x-codex-{slot}-reset-at") or 0) or None
            except (TypeError, ValueError):
                reset_at = None
            windows.append({"seconds": minutes * 60, "usedPct": used, "resetAt": reset_at})
        return windows

    @staticmethod
    def windows_from_usage_page(payload):
        """The windows the account's usage page states, as readings; [] when it states none.

        Only `primary_window` and `secondary_window` — the two the headers carry.
        The page's additional windows (OpenAI's "gpt-reserve") are left out: no
        answer ever states them, and one of them shares the weekly length, so a
        reserve keyed by length would read it as the weekly window. A window
        without a used share is skipped, not read as unused.
        """
        rate = payload.get("rate_limit") if isinstance(payload, dict) else None
        if not isinstance(rate, dict):
            return []
        windows = []
        for slot in ("primary_window", "secondary_window"):
            window = rate.get(slot)
            if not isinstance(window, dict):
                continue
            try:
                seconds = int(window.get("limit_window_seconds") or 0)
                used = int(float(window.get("used_percent")))
            except (TypeError, ValueError):
                continue
            if seconds <= 0:
                continue
            try:
                reset_at = int(window.get("reset_at") or 0) or None
            except (TypeError, ValueError):
                reset_at = None
            windows.append({"seconds": seconds, "usedPct": used, "resetAt": reset_at})
        return windows

    def note(self, account_id, headers, now=None):
        """Keep what an answer from the account says about its windows. True when it said anything."""
        return self.keep(account_id, self.windows_from_headers(headers), now)

    def keep(self, account_id, windows, now=None):
        """Keep a reading of the account's windows. True when there was one: an
        empty reading leaves the last as it was — absence is not a reading."""
        key = str(account_id or "").strip()
        if not key or not windows:
            return False
        with self._lock:
            self._rows[key] = {"windows": [dict(w) for w in windows],
                               "readAt": float(now if now is not None else time.time())}
        return True

    def windows(self, account_id):
        with self._lock:
            row = self._rows.get(str(account_id or "").strip())
            return [dict(w) for w in row["windows"]] if row else []

    def read_at(self, account_id):
        """When the account's windows were last heard, or None — never a made-up moment."""
        with self._lock:
            row = self._rows.get(str(account_id or "").strip())
            return row["readAt"] if row else None

    def snapshot(self):
        """Every account's last reading — the state file carries it to the board."""
        with self._lock:
            return {key: {"windows": [dict(w) for w in row["windows"]], "readAt": row["readAt"]}
                    for key, row in self._rows.items()}

    def clear(self):
        with self._lock:
            self._rows.clear()


subscription_usage = SubscriptionUsage()


class UsagePage:
    """The account's usage page: what its limit windows are now, asked without
    spending a share of any of them. A pool asks it for a step whose reading is
    stale (caravan/proxy/pool_steps.py): a step held at its switch level gets
    no traffic, so no answer brings a new reading, and a reset that came early
    — a banked one, or one bought on chatgpt.com — would stay unseen until the
    old reset time: up to a week on the weekly window."""

    USAGE_PATH = "/backend-api/wham/usage"

    @classmethod
    def fetch(cls, provider, timeout=10):
        """GET the account's usage page with its own sign-in; the page's JSON, or None."""
        auth_pair = load_provider_secret(provider)
        base = urlsplit(str(provider.get("baseUrl") or ""))
        if not auth_pair or not base.hostname:
            return None
        use_tls = base.scheme != "http"
        conn = (http.client.HTTPSConnection if use_tls else http.client.HTTPConnection)(
            base.hostname, base.port or (443 if use_tls else 80), timeout=timeout)
        try:
            conn.request("GET", cls.USAGE_PATH, headers={
                "Host": base.netloc, "Connection": "close", "Accept": "application/json",
                "Authorization": auth_pair[1], "originator": "pi",
                "chatgpt-account-id": _extract_chatgpt_account_id(auth_pair[1][7:]) or ""})
            resp = conn.getresponse()
            raw = resp.read(1 << 20)
            return json.loads(raw.decode("utf-8")) if resp.status < 400 else None
        finally:
            conn.close()
