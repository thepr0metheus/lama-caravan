#!/usr/bin/env python3
"""Value snapshot: the model cache's line on a machine's card is a compact line, not a form (1.3.576).

A browser is not in CI, so what the stylesheet says about the line's boxes is read from its text (scripts/_css_rules.py). The line sits under the
caravan's strip on every machine's card (static/css/nodes.css, model-cache.js). The board's global rules make any new control the biggest thing on
the card — `select` is 42px high and as wide as its container, `button` has a 34px minimum (cards.css; the trap is in the owner's memory since
2026-10-04, when the subscription pool card came out heavier than its neighbours) — so each claim below is one that bends without a word:

  - the setting's box (`.cache-keep`) is sized in full: automatic width, no minimum height, 22px high — and the global rules are still what
    makes the trap, so this pin goes red if they change and the override is no longer the thing it overrides;
  - the delete button (`.cache-foreign-delete`) likewise: no minimum height, 22px high, takes no space it does not need (`flex: 0 0 auto`);
  - the line (`.cache-line`) wraps and may shrink (`flex-wrap: wrap`, `min-width: 0`): on a narrow window the figures go under the setting and the
    foreign files' line under both — a nowrap line would push the card wider than the window;
  - the foreign files stand on a line of their own (`flex: 1 0 100%`) in the warning colour, with the text allowed to shrink and wrap;
  - the figures draw nothing while they have no words (`:empty`), so a scout that measured nothing leaves no gap in the line;
  - every colour of these rules comes from the board's tokens (`var(--…, fallback)`): a literal colour would stay as it is in the other theme;
  - the sign on a machine's head that the disk is almost full (`.node-disk-low`, 1.3.577) is a chip in the warning colour that does not wrap: it
    stands beside the machine's name on the main board's glance, where a chip that broke in two would push the name down.

Each claim has a positive and a negative pin.

Run: python3 scripts/test_css_model_cache.py
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _css_rules import CssRules  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def declared(css, selector):
    """Every declaration of every rule whose selector is exactly this one, the later one over the earlier."""
    merged = {}
    for sel, decl in CssRules.rules(css):
        if sel == selector:
            merged.update(decl)
    return merged


NODES = (ROOT / "static" / "css" / "nodes.css").read_text(encoding="utf-8")
CARDS = (ROOT / "static" / "css" / "cards.css").read_text(encoding="utf-8")
KEEP, DELETE, LINE = declared(NODES, ".cache-keep"), declared(NODES, ".cache-foreign-delete"), declared(NODES, ".cache-line")
FOREIGN, TEXT, FIGURES = declared(NODES, ".cache-foreign"), declared(NODES, ".cache-foreign-text"), declared(NODES, ".cache-figures")
DISK = declared(NODES, ".node-disk-low")

print("the board's global rules — the trap:")
check(any(CssRules.px(decl.get("height")) == 42 and sel == "select" for sel, decl in CssRules.rules(CARDS)),
      "cards.css still gives a select 42px of height — which is why the setting's box is sized in full")
check(any(CssRules.px(decl.get("min-height")) == 34 and sel == "button" for sel, decl in CssRules.rules(CARDS)),
      "and a button a 34px minimum — which is why the delete button is sized in full")

print("the setting's box and the delete button:")
check(KEEP.get("width") == "auto" and CssRules.px(KEEP.get("min-height")) == 0 and CssRules.px(KEEP.get("height")) == 22,
      "the box is automatic in width, has no minimum height and is 22px high")
check(CssRules.px(DELETE.get("min-height")) == 0 and CssRules.px(DELETE.get("height")) == 22 and DELETE.get("flex") == "0 0 auto",
      "the delete button has no minimum height, is 22px high and takes only the room it needs")
check(not (CssRules.px(KEEP.get("height")) or 0) >= 34 and not (CssRules.px(DELETE.get("height")) or 0) >= 34,
      "negative: neither is as tall as the board's own controls")

print("the line wraps:")
check(LINE.get("display") == "flex" and LINE.get("flex-wrap") == "wrap" and CssRules.px(LINE.get("min-width")) == 0,
      "a flex line that wraps and may shrink: on a narrow window the figures go under the setting")
check(LINE.get("flex-wrap") != "nowrap" and "white-space" not in LINE, "negative: it never says nowrap, and cuts nothing off")
check(FOREIGN.get("flex") == "1 0 100%" and "flex-wrap" in FOREIGN and CssRules.px(FOREIGN.get("min-width")) == 0
      and TEXT.get("min-width") == "0" and TEXT.get("overflow-wrap") == "anywhere" and TEXT.get("flex") == "1",
      "the foreign files take a line of their own, and their words shrink and wrap")
check(FIGURES.get("overflow-wrap") == "anywhere" and CssRules.px(FIGURES.get("min-width")) == 0,
      "the figures wrap too — a long figure never widens the card")
check(declared(NODES, ".cache-figures:empty").get("display") == "none", "the figures draw nothing while they have no words")

print("the sign on a machine's head:")
check(DISK.get("white-space") == "nowrap" and DISK.get("color", "").startswith("var(--warn") and DISK.get("cursor") == "help",
      "a chip in the warning colour that does not break in two and says it has a tip (the cursor)")
check("border" in DISK and "var(--warn" in DISK["border"] and CssRules.px(DISK.get("font-size")) == 11,
      "its border is the warning colour's and its size is the scout-old chip's 11px — the two chips stand side by side in a head")
check("display" not in DISK and "flex" not in DISK and "width" not in DISK,
      "negative: it asks for no box of its own — inline, as wide as its words")

print("the colours are the board's:")
rules = [(sel, decl) for sel, decl in CssRules.rules(NODES) if sel.startswith(".cache-") or sel == ".node-disk-low"]
check(len(rules) >= 10, f"the stylesheet carries the line's and the sign's rules ({len(rules)} found)")
literal = []
for sel, decl in rules:
    for prop, value in decl.items():
        if prop in ("color", "background", "border", "border-top"):
            bare = re.sub(r"var\([^()]*\)", "", value)
            if re.search(r"#[0-9a-f]{3,8}\b|rgba?\(|hsla?\(", bare):
                literal.append(f"{sel} {prop}: {value}")
check(literal == [], f"negative: no literal colour outside a var(--token, fallback) ({literal})")
check(FOREIGN.get("color", "").startswith("var(--warn"), "the foreign files are in the warning colour, from its token")

if _fail:
    print(f"\nFAILED ({len(_fail)}):")
    for m in _fail:
        print("  - " + m)
    sys.exit(1)
print("\ncss model-cache OK")
