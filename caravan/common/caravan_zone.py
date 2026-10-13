"""The caravan's time zone: the one its schedules are written in.

A model's schedule says "Mon–Fri 09:00–19:00" in the caravan's own time — the zone the
controller and the proxy run in: TZ in a container, which ContainerPreflight requires, and the
machine's own zone natively. Both processes read it here, and the board is told its name, so a
browser in another zone draws the same hours the proxy keeps to.
"""
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path


class CaravanZone:
    """The zone schedules are read in, with the two conversions they need: an epoch to the zone's
    wall clock, and a wall-clock time back to an epoch. Wall-clock arithmetic is the schedules':
    a window from 22:00 to 08:00 ends at 08:00 on the clock, whatever a night of a clock change
    makes of its length."""

    LOCALTIME = Path("/etc/localtime")

    def __init__(self, name="UTC", tzinfo=None, known=True):
        self.name = str(name or "UTC")
        self.tzinfo = tzinfo or timezone.utc
        self.known = bool(known)

    @classmethod
    def named(cls, name):
        from zoneinfo import ZoneInfo
        return cls(name, ZoneInfo(name), True)

    @classmethod
    def current(cls, env=None, localtime=None):
        """The zone this process keeps time in: TZ when it names a zone; else the machine's own
        (/etc/localtime, named by the zone file it leads to); else UTC — said as not known, not
        passed off as the caravan's choice."""
        env = os.environ if env is None else env
        name = str(env.get("TZ", "")).strip().lstrip(":")
        if name:
            try:
                return cls.named(name)
            except Exception:  # noqa: BLE001 — a TZ zoneinfo cannot read is the same as none
                pass
        path = Path(localtime or cls.LOCALTIME)
        try:
            target = str(path.resolve())
            if "zoneinfo/" in target:
                return cls.named(target.split("zoneinfo/", 1)[1])
        except Exception:  # noqa: BLE001 — no zone file, or one zoneinfo does not know
            pass
        return cls("UTC", timezone.utc, False)

    def wall(self, epoch):
        """The zone's wall clock at `epoch`, as a naive datetime."""
        return datetime.fromtimestamp(float(epoch), self.tzinfo).replace(tzinfo=None)

    def epoch(self, wall):
        """The epoch of a wall-clock time of this zone. A time a clock change skips is read with
        the offset from before the change, as zoneinfo reads it."""
        return int(wall.replace(tzinfo=self.tzinfo).timestamp())

    def offset_minutes(self, epoch):
        return int(datetime.fromtimestamp(float(epoch), self.tzinfo).utcoffset() // timedelta(minutes=1))

    def text(self, epoch):
        """`epoch` as a person in any zone reads it right: "2026-10-12 19:00 UTC+04:00"."""
        minutes = self.offset_minutes(epoch)
        sign = "+" if minutes >= 0 else "-"
        hours, rest = divmod(abs(minutes), 60)
        return f"{self.wall(epoch):%Y-%m-%d %H:%M} UTC{sign}{hours:02d}:{rest:02d}"

    def state(self, now):
        """What the board is told: the zone's name, whether it is known, and its offset now."""
        return {"name": self.name, "known": self.known, "offsetMinutes": self.offset_minutes(now)}
