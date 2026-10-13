"""A step's levels on a subscription's limit windows — one rule for the proxy and the board.

A ChatGPT subscription serves the caravan from the same allowance the operator
uses by hand: once the caravan has spent the five-hour or the weekly window,
the operator's own chats and Codex stop too (2026-09-28: the five-hour window
ran out under the caravan's traffic). So a pool's step on a subscription has
two levels per window (the operator, 2026-10-11), each one a UsageReserve:

- the STOP level ("stop at N%"): when a window's remaining share is at or below
  it, the step does not serve at all, and when no step is left, the caravan
  answers 429 itself and sends nothing on until a window resets;
- the SWITCH level ("switch at N%"), never below the stop: from there on the
  pool sends requests to its next steps first, and the step still serves when
  none of them can (caravan/proxy/pool_steps.py).

The levels are the step's own (the operator, 2026-10-10): one subscription in
two pools may be left at 50% by one and spent down to 10% by the other. Until
1.3.462 they were the account's, as "the reserve the operator keeps for
themselves"; until 1.3.463 a step had one level, which stopped it.

A window is known by its length in seconds: 18000 for five hours, 604800 for a
week. The Codex backend states it in minutes on every answer, the usage page in
seconds, and a length does not depend on which slot ("primary", "secondary")
the provider happens to put the window in — OpenAI once dropped the five-hour
window, and the weekly one moved into the first slot.

A reading is `{"seconds", "usedPct", "resetAt"}`, `resetAt` in epoch seconds.
"""


class UsageReserve:
    """The levels per window of one step, and the verdict they give on a reading."""

    #: A level of a whole window would close the step for good; the slider
    #: stops short of that.
    MAX_PCT = 90

    #: Where a new subscription step stops — and switches, the same level — on
    #: its five hours and its week from the start (the operator, 2026-10-08, for
    #: a new subscription): with no level the caravan could spend a window to
    #: its end before anyone moved a slider.
    NEW_STEP = {"18000": 10, "604800": 10}

    def __init__(self, by_seconds=None):
        self.by_seconds = {int(k): v for k, v in self.normalize(by_seconds).items()}

    @classmethod
    def normalize(cls, raw):
        """The stored shape, `{"<seconds>": pct}`: whole percents from 1 to MAX_PCT.

        Zero is "no level" and is not stored — a stored zero would read as a
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

    def verdict(self, windows, now):
        """The window that keeps the step closed to the caravan now, or None.

        A window closes the step while its remaining share is at or below its
        level and its reset is still ahead. A reading past its reset says
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
