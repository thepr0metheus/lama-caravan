#!/usr/bin/env python3
"""Value snapshot: a machine's card on the main board opens its page as a whole, and its name does not light up on its own (1.3.650).

The owner, 2026-10-26, with a screenshot of the board: "I don't like that the machine's name stands out — a tap on the block leads
to the same page anyway". The card is the way into the machine's page (main.js); its name is a link only for the keyboard and a click with
a modifier (a new tab). Under the pointer the name was underlined by itself, and read as a second way somewhere else.

A browser is not in CI, so what the stylesheet says is read from its text (scripts/_css_rules.py). Pinned:
  - the card answers the pointer — it says it opens (cursor) and its border lights up on hover;
  - the name under the pointer is the card's text: no underline, its colour the card's; negative: no rule underlines it on hover;
  - the keyboard still sees where it is: the name is underlined on focus-visible.

Run: python3 scripts/test_css_machine_glance.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _css_rules import CssRules  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CSS = (ROOT / "static" / "css" / "topology-board.css").read_text(encoding="utf-8")
_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def declared(selector):
    """The declarations of every rule that names this selector, alone or among others — the later over the earlier."""
    merged = {}
    for sel, decl in CssRules.rules(CSS):
        if selector in [s.strip() for s in sel.split(",")]:
            merged.update(decl)
    return merged


CARD, CARD_HOVER = declared(".machine-glance"), declared(".machine-glance:hover")
NAME, NAME_HOVER = declared(".machine-glance .machine-name"), declared(".machine-glance .machine-name:hover")
NAME_FOCUS = declared(".machine-glance .machine-name:focus-visible")

print("a machine's card on the main board:")
check(CARD.get("cursor") == "pointer" and "border-color" in CARD_HOVER,
      "the card answers the pointer: it says it opens, and its border lights up on hover")
check(NAME.get("text-decoration") == "none" and NAME.get("color") == "inherit",
      "the name is the card's text: no underline, the card's colour")
check("text-decoration" not in NAME_HOVER and "color" not in NAME_HOVER,
      "defect-history (the owner, 2026-10-26): the name does not light up under the pointer — the whole card opens the same page, "
      "and an underlined name read as a second way somewhere else")
check(NAME_FOCUS.get("text-decoration") == "underline",
      "the keyboard still sees where it is: the name is underlined on focus-visible")

if _fail:
    print(f"\ncss machine glance FAILED: {len(_fail)}")
    sys.exit(1)
print("\ncss machine glance OK")
