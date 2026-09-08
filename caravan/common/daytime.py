"""Time of day "HH:MM" — one parsing rule for every schedule.

The caravan already has three schedules: cell power on/off, host power off,
and — since 1.3.339 — the daily model check. Parsing "HH:MM" separately in
each one means eventually accepting "24:00" in one place and rejecting it in
another.
"""
import re

from caravan.common.errors import AppError

_PATTERN = re.compile(r"^(\d{1,2}):(\d{2})$")


def hhmm(value, default="03:00"):
    """Normalized "HH:MM". An empty value is `default`; garbage is refused.

    Refused, not silently defaulted: a schedule that quietly drifted to a
    different time would only be noticed by its consequences.
    """
    raw = str(value if value not in (None, "") else default).strip()
    match = _PATTERN.match(raw)
    if not match:
        raise AppError(f"time must look like HH:MM, got: {raw}")
    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > 23 or minute > 59:
        raise AppError(f"time out of range: {raw}")
    return f"{hour:02d}:{minute:02d}"


def minutes_of_day(value):
    """"HH:MM" → minutes since midnight. For comparing against the current time."""
    hour, minute = hhmm(value).split(":")
    return int(hour) * 60 + int(minute)
