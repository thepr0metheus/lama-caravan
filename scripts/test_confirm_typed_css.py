#!/usr/bin/env python3
"""Value snapshot: the look of the confirm button that waits for typed words (form.css, dialogs.js appConfirmTyped).

A confirm that cannot be answered by a click (1.3.545: a machine let go of, rebooted, powered off asks for its name) keeps
its button OFF until the name is typed. Off, it looked pressable — red, bright under the pointer, "pointer" cursor — and did
nothing (seen on the stand, 2026-10-14). Read from the stylesheet's text, as a browser is not in CI (scripts/_css_rules.py).

Each claim has a positive and a negative pin.

Run: python3 scripts/test_confirm_typed_css.py
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

    off = declared("#confirmDelete:disabled")
    off_hover = declared("#confirmDelete:disabled:hover")
    on = declared("#confirmDelete")
    check(float(off.get("opacity", "1")) <= 0.5, "the off button is dimmed: opacity at most one half, so it is plain that it is off")
    check(off.get("cursor") == "not-allowed", "the pointer over it says \"not here\" (cursor: not-allowed), not \"pointer\"")
    check(off.get("box-shadow") == "none" and "saturate" in off.get("filter", ""),
          "it is flat and drained of colour: no glow of the danger tone, which belongs to a button that works")
    check(off_hover.get("filter") == off.get("filter") and float(off_hover.get("opacity", "1")) <= 0.5,
          "negative: the pointer over the off button does not brighten it back (the plain button's :hover brightens)")
    check("opacity" not in on and "cursor" not in on and declared("#confirmDelete:hover").get("filter") == "brightness(1.08)",
          "negative: the button that works keeps its look — full colour, the glow, brighter under the pointer")
    check(declared("#confirmOverlay .modal-actions button:disabled:active").get("transform") == "none",
          "an off button is not pressed down by a click (the plain one moves 1 px)")
    check(declared("#confirmOverlay .modal-actions button:active").get("transform") == "translatey(1px)",
          "negative: the button that works still moves 1 px under a press")
    print()
    if _fail:
        print(f"confirm typed css FAILED ({len(_fail)}):")
        for msg in _fail:
            print("  - " + msg)
        return 1
    print("confirm typed css OK: the off confirm button looks off, the working one is as it was")
    return 0


if __name__ == "__main__":
    sys.exit(main())
