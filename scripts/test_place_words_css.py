#!/usr/bin/env python3
"""Value snapshot: a part of the memory map says what it is only where its words fit (form.css, 1.3.657).

The owner, 2026-10-26, on the map of a cell's memory: "what do all these colours mean? why do the left parts differ on the two
cards? if it fits, label it — the model, the KV cache or whatever it is". A lane's colour is its device's, the colour of the
device's share in the model's bar above, so the weights on GPU0 and on GPU1 are two colours; only words say what a part is.
A part writes them (PlacementPanel.wordsHtml: what it is, then how much), and the stylesheet decides which ones are seen: the
part is one line of flex items — the zero-wide ::before is that line, the part's whole height — and a word that does not fit
wraps below it, out of sight. A narrow part says only what it is, a narrower one nothing; the browser measures each word in
its own language, so no width is guessed. Until 1.3.657 the model's bar wrote its words past 14% of its width, and the lanes
none at all.

Pinned here, read from the stylesheet's text (a browser is not in CI, scripts/_css_rules.py): the parts of the lanes and of
the model's bar wrap their words, hide what wraps, start on the first line and keep a zero-wide line of their whole height
first; a word does not shrink.

Run: python3 scripts/test_place_words_css.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _css_rules import CssRules  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def main():
    rules = CssRules.rules((ROOT / "static" / "css" / "form.css").read_text(encoding="utf-8"))

    def declared(selector):
        merged = {}
        for sel, decl in rules:
            if sel == selector:
                merged.update(decl)
        return merged

    print("a part of the map says what it is only where its words fit:")
    for part in (".place-seg", ".place-sum-seg"):
        box, line = declared(part), declared(f"{part}::before")
        check(box.get("display") == "flex" and box.get("flex-wrap") == "wrap" and box.get("overflow") == "hidden"
              and box.get("align-content") == "flex-start" and box.get("white-space") == "nowrap",
              f"{part}: its words stand in one flex line, a word that does not fit wraps below and is hidden (got {box})")
        check(line.get("content") in ('""', "''") and line.get("width") == "0" and line.get("height") == "100%",
              f"{part}::before: a zero-wide item of the part's whole height — the first line is the part's own height, and a "
              f"word that wraps falls below it; negative: without it a word wider than the part would stand clipped on the "
              f"first line (got {line})")
    word = declared(".place-word")
    check(word.get("flex") == "none", f"a word does not shrink to fit: it fits whole, or wraps out of sight (got {word})")
    print()
    if _fail:
        print(f"place words css FAILED ({len(_fail)}):")
        for msg in _fail:
            print("  - " + msg)
        return 1
    print("place words css OK: a part of the map says what it is where its words fit, and nothing where they do not")
    return 0


if __name__ == "__main__":
    sys.exit(main())
