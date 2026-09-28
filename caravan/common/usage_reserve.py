"""The operator's reserve on a subscription's limits — one rule for the proxy and the board.

A ChatGPT subscription serves the caravan from the same pool the operator uses
by hand: once the caravan has spent the five-hour or the weekly window, the
operator's own chats and Codex stop too (2026-09-28: the five-hour window ran
out under the caravan's traffic). The reserve is the share of each window the
operator keeps for themselves. When a window's remaining share is at or below
it, the caravan answers requests to that account itself — the same 429 OpenAI
gives when a window is spent — and sends nothing on until that window resets.

A window is known by its length in seconds: 18000 for five hours, 604800 for a
week. The Codex backend states it in minutes on every answer, the usage page in
seconds, and a length does not depend on which slot ("primary", "secondary")
the provider happens to put the window in — OpenAI once dropped the five-hour
window, and the weekly one moved into the first slot.

A reading is `{"seconds", "usedPct", "resetAt"}`, `resetAt` in epoch seconds.
"""


class UsageReserve:
    """The reserve per window of one account, and the verdict it gives on a reading."""

    #: A reserve of a whole window would close the account for good; the
    #: slider stops short of that.
    MAX_PCT = 90

    def __init__(self, by_seconds=None):
        self.by_seconds = {int(k): v for k, v in self.normalize(by_seconds).items()}

    @classmethod
    def normalize(cls, raw):
        """The stored shape, `{"<seconds>": pct}`: whole percents from 1 to MAX_PCT.

        Zero is "no reserve" and is not stored — a stored zero would read as a
        choice nobody made. Rubbish drops out rather than becoming a number.
        """
        out = {}
        if not isinstance(raw, dict):
            return out
        for key, value in raw.items():
            if isinstance(value, bool):
                continue
            try:
                seconds, pct = int(key), int(value)
            except (TypeError, ValueError):
                continue
            if seconds > 0 and pct > 0:
                out[str(seconds)] = min(pct, cls.MAX_PCT)
        return out

    @classmethod
    def of(cls, account):
        """The reserve an account (or a provider resolved from it) carries."""
        return cls((account or {}).get("usageReserve"))

    def verdict(self, windows, now):
        """The window that keeps the account closed to the caravan now, or None.

        A window closes the account while its remaining share is at or below
        its reserve and its reset is still ahead. A reading past its reset says
        nothing any more — the window has emptied since — and a reading with no
        reset time cannot say how long it holds, so neither closes anything:
        not knowing is not a reason to refuse. Of several closing windows, the
        one that resets last is named: it is the one that keeps the door shut.
        """
        hits = []
        for window in windows or []:
            if not isinstance(window, dict):
                continue
            try:
                seconds = int(window.get("seconds"))
                used = int(window.get("usedPct"))
                reset_at = int(window.get("resetAt") or 0)
            except (TypeError, ValueError):
                continue
            reserve = self.by_seconds.get(seconds)
            if not reserve or reset_at <= now:
                continue
            remaining = max(0, 100 - used)
            if remaining <= reserve:
                hits.append({"windowSeconds": seconds, "remainingPct": remaining,
                             "reservePct": reserve, "resetAt": reset_at})
        return max(hits, key=lambda hit: hit["resetAt"]) if hits else None
