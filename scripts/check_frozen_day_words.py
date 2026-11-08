#!/usr/bin/env python3
"""A promise file may not hold a word of the run where the program quoted a date.

`tests/frozen/*.jsonl` is what a program promised to answer. A `description` there is the
program's own words: text the program writes in its table (rust/crates/scout/src/routes.json), not something a run works out,
so the day inside it is a word of the answer and the answer is the same on every day. A relative word (`<today>`, `<yesterday>`, the
words `OwnWords` gives the days of a run) inside a description means the file was written on the
day that happened to be today: the promise then says "the day the comparison is run", and it goes
red the next day. Pipeline #581 (2026-11-04) went red for four descriptions written on 2026-11-03,
on code that changed nothing — the snapshot was green only on the day it was written.

A word of the run is right wherever the program COMPUTED the day: the journal's `date`, a schedule's `lastFired`, the key a
scenario asked with today. This names descriptions because that is where the program's own words lie, and a run cannot compute
anything there. `OwnWords.clean` keeps a day in them as it is written, so this guard is what says the files agree with that rule
(pipeline #582, 2026-11-04, showed the rule needs both halves).

The same rule has a second half, about WHEN the program computes the day. A day the program writes only for a time
already past today is a promise of the hour it was written at: `lastFired` is kept by the promise file, but the program
stamps it only when the clock has passed the schedule's time, so a run before that time answers without the key. Pipelines
#596, #603 and #604 went red on code that changed nothing, on hours before 03:30. So a power schedule a scenario sends
must name a time that is already past at every hour of a run — `00:00` — and this guard says so.

Run: python3 scripts/check_frozen_day_words.py
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FOLDER = ROOT / "tests" / "frozen"
CONFORMANCE = ROOT / "scripts" / "test_rust_admin_conformance.py"


class FrozenDayWords:
    #: The words OwnWords gives the days of a run. A day the program quoted is not one of these.
    RELATIVE = ("<today>", "<yesterday>")
    #: A day as the program writes it.
    DAY = re.compile(r"(?<![0-9])20[0-9]{2}-[0-9]{2}-[0-9]{2}(?![0-9])")
    #: A power schedule time a scenario sends while the schedule is enabled. The program stamps `lastFired`
    #: only for a time the clock has already passed, so a promise holding that day is kept only on runs at or
    #: after the time. A time that is past at every hour of a run is `00:00`; every other is ahead of some runs.
    SENT_AT = re.compile(r'power-schedule", \{"schedule": \{"enabled": True, "at": "([0-9]{2}:[0-9]{2})"')
    ALWAYS_PAST = "00:00"

    def __init__(self):
        self.problems = []
        #: Whether any description names a day at all: without one this guard watches nothing.
        self.witness = False
        #: Promise rows that hold a day the program writes only for a time already past.
        self.hour_days = []

    def check(self):
        for path in sorted(FOLDER.glob("*.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                self.walk(json.loads(line), path)
        if not self.witness:
            self.problems.append("no promise file names a day inside a description: this guard is looking at nothing")
        if not self.hour_days:
            self.problems.append("no promise file holds a day the program writes only for a time already past: this half is looking at nothing")
        for sent in self.SENT_AT.findall(CONFORMANCE.read_text(encoding="utf-8")):
            if sent != self.ALWAYS_PAST:
                self.problems.append(
                    f"a promise holds `lastFired` ({self.hour_days[0]}), while the scenario sends {sent}: the program "
                    f"stamps that day only for a time it has already passed, so the promise is kept only on runs after "
                    f"{sent} — it is a promise of the hour it was written at, not of an answer")
        return self.problems

    def walk(self, row, path, key="", where=""):
        """One promise row, then its parts, with the field each part is under."""
        said = row["said"]
        if key == "description" and isinstance(said, str):
            if any(word in said for word in self.RELATIVE):
                self.problems.append(
                    f"{path.name} · {row['key']}{where}: a description holds a word of the run ({said[:80]}); "
                    "the program's own words name a day as they write it")
            elif self.DAY.search(said):
                self.witness = True
        elif key == "lastFired" and isinstance(said, str) and said in self.RELATIVE:
            self.hour_days.append(f"{path.name} · {row['key']}{where}")
        elif isinstance(said, dict):
            for name, item in said.items():
                self.walk({"key": row["key"], "said": item}, path, name, f"{where}/{name}")
        elif isinstance(said, list):
            for item in said:
                self.walk({"key": row["key"], "said": item}, path, key, where)


if __name__ == "__main__":
    errors = FrozenDayWords().check()
    print("frozen day words: " + ("FAILED: " + "; ".join(errors) if errors else "OK"))
    sys.exit(bool(errors))
