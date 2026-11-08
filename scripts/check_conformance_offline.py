#!/usr/bin/env python3
"""A snapshot may not hold a value the controller reads from the internet: the test writes that value itself, fresh for its day.

`tests/frozen/admin.jsonl` is what the controller promised to answer. Some of those answers the controller can only get from the internet, and a promise
written from the internet is a promise of the day it was written: the program reads its copy again when the copy is older than the TTL, so the answer moves
with the internet. This happened twice on code that changed nothing — LiteLLM published a new table and four answers went red under every merge request on
2026-11-03; npm published 0.167.0 and 75 answers went red on 2026-11-06 (pipeline 616). The test now writes its own copy for each of them, so the answers
are the copies and never the internet.

Three halves, each able to go red:
 - a value the pins can only get from the internet has no copy the test writes: the answer is whatever the internet says today;
 - a copy is written with the fixture's own date instead of fresh for its day: the program reads the internet again, and the copy is decoration;
 - the copy and the pins that hold its values are not the same values: a copy the pins no longer answer is a copy written to please this guard.

The third half is already red in the conformance test itself, because the conformance compares an answer with its pin and the answer IS the copy. It is
checked here too so that the copies are named in one place and the guard can say which of them watches nothing.

Run: python3 scripts/check_conformance_offline.py
"""
import json
import re
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_rust_admin_conformance import Fixture  # noqa: E402


class ConformanceOffline:
    #: What the controller reads from the internet, and the copy the test writes instead. The TTL is read from where the program reads it, so this is
    #: the code and not a promise; the file, the values and the date are the shape of the copy as the fixture writes it.
    COPIES = [
        {"what": "npm's latest for @openai/codex", "file": "state/model-catalog.json",
         "values": ("codexNpm", "version"), "date": ("codexNpm", "checkedAt"),
         "ttl": ("rust/crates/admin/src/cloud/catalog.rs", "NPM_TTL_SEC"),
         #: The word the program names when the value came from the internet (codex_client_version): "env", "floor", or this.
         "source": "npm", "fields": ("value",)},
        {"what": "LiteLLM's price table on GitHub", "file": "logs/model-pricing-cache.json",
         "values": ("pricing",), "date": ("fetchedAt",),
         "ttl": ("rust/crates/admin/src/cloud/pricing.rs", "TTL"),
         #: The table has no source word in the pins: what the pins hold of it are its numbers.
         "source": None,
         "fields": ("inputPer1M", "outputPer1M", "cacheReadPer1M", "cacheWritePer1M")},
    ]

    def check(self):
        pins = [json.loads(line) for line in (ROOT / "tests" / "frozen" / "admin.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        copies = self.written()
        if not copies:
            return ["the test writes no copy of anything: this guard is looking at nothing"]
        problems = []
        for copy in self.COPIES:
            held = copies.get(copy["file"])
            if held is None:
                problems.append(f"the pins hold a value from {copy['what']}, and the test writes no copy for it: the answer is whatever the internet says today")
                continue
            date = self.at(held, copy["date"])
            if date is None:
                problems.append(f"{copy['file']}: the copy has no date field, so nothing says when it was written — the program reads {copy['what']} again")
                continue
            age = time.time() - float(date)
            ttl = self.ttl(copy["ttl"])
            if age > ttl:
                problems.append(f"{copy['file']}: the copy is {int(age / 3600)} h old, over the {int(ttl / 3600)} h the program allows before it reads "
                                f"{copy['what']} again — a copy written with the fixture's date is never read")
            if not self.pins_answer(pins, copy, held):
                problems.append(f"{copy['file']}: no pin answers this copy, so the copy and the pins are not the same fact")
        return problems

    def written(self):
        """What the fixture writes, by running it: the copies as the code writes them, not as its docstring says them."""
        with tempfile.TemporaryDirectory(prefix="caravan-offline-") as tmp:
            Fixture(Path(tmp)).write()
            out = {}
            for copy in self.COPIES:
                path = Path(tmp) / copy["file"]
                if path.is_file():
                    out[copy["file"]] = json.loads(path.read_text(encoding="utf-8"))
            return out

    def ttl(self, where):
        """The seconds the program lets its copy be old, read from the file where the program reads them."""
        source = (ROOT / where[0]).read_text(encoding="utf-8")
        found = re.search(rf"const {where[1]}: f64 = ([0-9.]+(?:\s*\*\s*[0-9.]+)*);", source)
        if not found:
            raise SystemExit(f"guard: no TTL {where[1]} in {where[0]} — the guard is holding a promise, not the code")
        value = 1.0
        for part in found.group(1).split("*"):
            value *= float(part.strip())
        return value

    def pins_answer(self, pins, copy, held):
        """Whether the pins answer the copy: a pin that no longer holds the copy's values is a copy nobody reads."""
        if copy["source"]:
            named = [row for row in pins if any(k == "source" and v == copy["source"] for k, v in self.walk(row))]
            version = self.at(held, copy["values"])
            return bool(named) and all(any(k in copy["fields"] and v == version for k, v in self.walk(row)) for row in named)
        numbers = self.numbers(self.at(held, copy["values"]))
        pinned = {v for row in pins for k, v in self.walk(row) if k in copy["fields"] and isinstance(v, (int, float))}
        return bool(numbers) and bool(numbers & pinned)

    def numbers(self, table):
        return {value for entry in (table or {}).values() if isinstance(entry, dict)
                for value in entry.values() if isinstance(value, (int, float))}

    def at(self, value, path):
        for key in path:
            if not isinstance(value, dict):
                return None
            value = value.get(key)
        return value

    def walk(self, row):
        """One pin row and every part of it, with the field each part stands under."""
        said = row.get("said", row)
        if isinstance(said, dict):
            for key, value in said.items():
                yield key, value
                yield from self.walk({"said": value})
        elif isinstance(said, list):
            for item in said:
                yield from self.walk({"said": item})


if __name__ == "__main__":
    errors = ConformanceOffline().check()
    print("conformance offline: " + ("FAILED: " + "; ".join(errors) if errors else "OK"))
    sys.exit(bool(errors))
