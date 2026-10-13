"""When a model is open: windows of weekdays and times of day — one rule for the proxy, the
controller and the board.

The owner, 2026-10-12 (visumap scheme caravan-model-schedule): a model has a schedule of the
days and hours it is open, and the caravan keeps to it. A window is
`{"days": [0..6], "from": "HH:MM", "to": "HH:MM"}` — Monday is 0, and no days means every day.
It is open from `from` and closed again at `to`. A window whose `to` is not after its `from`
runs past midnight and belongs to the day it starts on: Friday 22:00–08:00 is open from Friday
evening to Saturday morning. `from` equal to `to` is a whole day from that time. The cells'
schedule has kept the same rule since 2026-07 (caravan/admin/cell_schedule.py).

Times are the caravan's wall clock (caravan/common/caravan_zone.py). The board paints and edits
windows in static/js/week-windows.js: both read a window as the same minutes of the week, and
scripts/test_week_windows.py holds the two to one table of cases.
"""
from datetime import timedelta

from caravan.common.daytime import hhmm, minutes_of_day
from caravan.common.errors import AppError


class WeekWindows:
    """The windows of one schedule, and what they say at a moment."""

    DAY = 1440
    WEEK = 7 * DAY
    #: More windows than a week has hours is no schedule a person made.
    MAX = 168

    def __init__(self, windows=None):
        self.windows = self.clean(windows)

    # ── reading what was sent ─────────────────────────────────────────────

    @classmethod
    def _days(cls, raw, where):
        if raw is None:
            return []
        if not isinstance(raw, list):
            raise AppError(f"{where}: days must be a list of 0..6 (Monday is 0)")
        days = set()
        for day in raw:
            if isinstance(day, bool) or not isinstance(day, int) or not 0 <= day <= 6:
                raise AppError(f"{where}: days must be numbers 0..6 (Monday is 0), got {day!r}")
            days.add(day)
        # All seven are every day, said one way: no days.
        return [] if len(days) == 7 else sorted(days)

    @classmethod
    def _window(cls, raw, where):
        if not isinstance(raw, dict):
            raise AppError(f"{where} must be an object: {{days, from, to}}")
        times = {}
        for name in ("from", "to"):
            value = str(raw.get(name) or "").strip()
            if not value:
                raise AppError(f"{where}: `{name}` is required, as HH:MM")
            try:
                times[name] = hhmm(value)
            except AppError as exc:
                raise AppError(f"{where}: {exc}")
        return {"days": cls._days(raw.get("days"), where), "from": times["from"], "to": times["to"]}

    @classmethod
    def parse(cls, raw):
        """The windows the operator sent, or a refusal that says what is wrong with which one:
        a schedule that quietly dropped a window would be noticed only by its consequences."""
        if raw is None:
            return []
        if not isinstance(raw, list):
            raise AppError("windows must be a list")
        if len(raw) > cls.MAX:
            raise AppError(f"a schedule holds at most {cls.MAX} windows")
        out = []
        for index, item in enumerate(raw, 1):
            window = cls._window(item, f"window {index}")
            if window not in out:
                out.append(window)
        return out

    @classmethod
    def clean(cls, raw):
        """The windows as a reader takes them from the file: each one that reads, in order; one
        that does not is left out — the door refused it, so a hand's edit put it there."""
        out = []
        for index, item in enumerate(raw if isinstance(raw, list) else [], 1):
            try:
                window = cls._window(item, f"window {index}")
            except AppError:
                continue
            if window not in out:
                out.append(window)
        return out[:cls.MAX]

    # ── what they say ─────────────────────────────────────────────────────

    def runs(self):
        """The open minutes of the week as sorted, merged `(start, end)` runs, Monday 00:00 being
        0. A window that runs past Sunday midnight goes on at the week's start, so a run never
        ends after the week does; two runs that touch are one."""
        pieces = []
        for window in self.windows:
            start = minutes_of_day(window["from"])
            length = (minutes_of_day(window["to"]) - start) % self.DAY or self.DAY
            for day in window["days"] or range(7):
                begin = day * self.DAY + start
                end = begin + length
                if end <= self.WEEK:
                    pieces.append((begin, end))
                else:
                    pieces += [(begin, self.WEEK), (0, end - self.WEEK)]
        return self._merged(pieces)

    @staticmethod
    def _merged(pieces):
        out = []
        for begin, end in sorted(pieces):
            if out and begin <= out[-1][1]:
                out[-1] = (out[-1][0], max(out[-1][1], end))
            else:
                out.append((begin, end))
        return out

    def state(self, now, zone):
        """At the epoch `now`, in the caravan's zone: `open` — whether a window holds it;
        `until` — the epoch its open stretch ends, None when it never does; `opensAt` — the epoch
        the next window opens, None while open or when none ever opens."""
        runs = self.runs()
        if not runs:
            return {"open": False, "until": None, "opensAt": None}
        if runs == [(0, self.WEEK)]:
            return {"open": True, "until": None, "opensAt": None}
        wall = zone.wall(now).replace(second=0, microsecond=0)
        minute = wall.weekday() * self.DAY + wall.hour * 60 + wall.minute
        monday = wall - timedelta(minutes=minute)
        # This week and the next, merged across the joint: a stretch open over Sunday midnight
        # ends when Monday's part does.
        ahead = self._merged(runs + [(begin + self.WEEK, end + self.WEEK) for begin, end in runs])
        for begin, end in ahead:
            if begin <= minute < end:
                return {"open": True, "until": zone.epoch(monday + timedelta(minutes=end)), "opensAt": None}
            if begin > minute:
                return {"open": False, "until": None, "opensAt": zone.epoch(monday + timedelta(minutes=begin))}
        return {"open": False, "until": None, "opensAt": None}
