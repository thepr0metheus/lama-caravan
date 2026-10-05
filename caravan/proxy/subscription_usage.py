"""What the proxy last heard about each subscription account's limit windows,
and the answer it gives itself when the operator's reserve is reached.

The Codex backend states both of an account's windows on every answer, a
refusal included: `x-codex-<slot>-used-percent`, `-window-minutes` and
`-reset-at`, for the slots "primary" and "secondary" (checked against the live
backend on 2026-09-28). Nothing is asked for this: the reading rides on the
traffic the caravan sends anyway, and on the idle probe's one-token question
while the account's exit sees no traffic. The rule that reads it lives in
caravan/common/usage_reserve.py, shared with the board. The one exception is a
shut door (ReserveGate): then nothing is sent, and the reading is refreshed
from the account's usage page instead.
"""
import http.client
import json
import threading
import time
from urllib.parse import urlsplit

from caravan.common.usage_reserve import UsageReserve
from caravan.common.subscription_resets import SubscriptionResetJournal
from caravan.proxy.paths import SUBSCRIPTION_RESETS_FILE
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


class ReserveGate:
    """Whether an account's door is shut now: the one question the handler and
    the probe both ask before sending anything to a subscription.

    While the door is shut nothing is sent, so no answer brings a new reading.
    A reset that came early — a banked one, or one bought on chatgpt.com — would
    stay unseen until the old reset time: up to a week on the weekly window.
    So while shut, a reading older than REFRESH_SEC is refreshed from the
    account's usage page, which spends no share of any window. An open door
    never asks: its reading rides on the answers.
    """

    REFRESH_SEC = 300
    USAGE_PATH = "/backend-api/wham/usage"

    def __init__(self, usage, fetch=None, clock=time.time, resets=None):
        self.usage = usage
        self.fetch = fetch or self.fetch_usage_page
        self.clock = clock
        self.resets = resets or SubscriptionResetJournal(SUBSCRIPTION_RESETS_FILE)
        self._tried = {}
        self._lock = threading.Lock()

    def verdict(self, provider):
        """The window holding the account shut ({windowSeconds, remainingPct,
        reservePct, resetAt}), or None when the door is open."""
        account = str((provider or {}).get("usageAccountId") or (provider or {}).get("accountId") or "").strip()
        reserve = UsageReserve.of(provider)
        now = self.clock()
        hit = reserve.verdict(self.usage.windows(account), now)
        if hit and self._claim(account, now):
            try:
                payload = self.fetch(provider)
            except Exception:
                payload = None   # the page did not answer: the door stays as the last reading says
            if self.usage.keep(account, SubscriptionUsage.windows_from_usage_page(payload), now):
                hit = reserve.verdict(self.usage.windows(account), now)
        return hit

    def _claim(self, account, now):
        """One refresh per account per REFRESH_SEC, counted from the reading and
        from the last try: a page that does not answer is not asked on every request."""
        read_at = self.usage.read_at(account) or 0
        reset_at = self.resets.reset_at(account)
        with self._lock:
            if max(read_at, self._tried.get(account, 0)) >= reset_at and now - max(read_at, self._tried.get(account, 0)) < self.REFRESH_SEC:
                return False
            self._tried[account] = now
            return True

    @classmethod
    def fetch_usage_page(cls, provider, timeout=10):
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

    def clear(self):
        with self._lock:
            self._tried.clear()


reserve_gate = ReserveGate(subscription_usage)


class ReserveRefusal:
    """The proxy's own answer while the operator's reserve is reached: an HTTP
    response a handler reads exactly as it reads the provider's.

    It is the provider's refusal in shape — 429, `usage_limit_reached`, when the
    window resets — so a client and a backup node treat it as they treat the
    real one. Its words name the caravan, and `caravan_reserve` carries the
    numbers: a refusal the provider never gave must not be read as the
    provider's.
    """

    status = 429
    reason = "Too Many Requests"
    #: What the journal and the board call this refusal (proxy errorKind).
    KIND = "usage_reserve"

    def __init__(self, verdict, now=None):
        now = float(now if now is not None else time.time())
        self.verdict = dict(verdict)
        reset_at = int(self.verdict["resetAt"])
        self.retry_after = max(1, int(reset_at - now))
        self.message = (f"The caravan keeps your reserve: the {self.window_name(self.verdict['windowSeconds'])} "
                        f"window has {self.verdict['remainingPct']}% left and you keep "
                        f"{self.verdict['reservePct']}% for yourself. Nothing is sent to this account "
                        f"until the window resets at {time.strftime('%Y-%m-%d %H:%M', time.localtime(reset_at))}.")
        self.body = json.dumps({"error": {
            "type": "usage_limit_reached",
            "message": self.message,
            "resets_at": reset_at,
            "resets_in_seconds": self.retry_after,
            "caravan_reserve": {"window_seconds": self.verdict["windowSeconds"],
                                "remaining_pct": self.verdict["remainingPct"],
                                "reserve_pct": self.verdict["reservePct"]},
        }}).encode("utf-8")
        self._headers = [("Content-Type", "application/json"), ("Retry-After", str(self.retry_after)),
                         ("Content-Length", str(len(self.body)))]
        self._offset = 0

    @staticmethod
    def window_name(seconds):
        seconds = int(seconds)
        if seconds == 604800:
            return "weekly"
        if seconds % 3600 == 0:
            return f"{seconds // 3600}-hour"
        return f"{seconds}-second"

    def getheaders(self):
        return list(self._headers)

    def getheader(self, name, default=None):
        return next((value for key, value in self._headers if key.lower() == str(name).lower()), default)

    def read(self, amount=None):
        end = len(self.body) if amount is None or amount < 0 else self._offset + amount
        chunk = self.body[self._offset:end]
        self._offset += len(chunk)
        return chunk

    def readline(self, limit=-1):
        rest = self.body[self._offset:]
        cut = rest.find(b"\n") + 1 or len(rest)
        if limit is not None and limit >= 0:
            cut = min(cut, limit)
        chunk = rest[:cut]
        self._offset += len(chunk)
        return chunk
