#!/usr/bin/env python3
"""Value snapshot: the board's toast stands over every layer and takes no clicks (form.css #toast, 1.3.625).

A toast had no layer of its own: it was drawn under an open dialog (z 30 and 70, blurred) and under a cell's window, whose
lane is a layer of its own (topology-board.css), and the word of a refusal — why Apply did nothing — was read dimmed or not
read. Lifted over them, a toast that faded out keeps its box and its last words over the buttons of the corner it covers, so
it takes no clicks at all, shown or not (the models page's own toast, #hfToast, already did). Read from the stylesheets' text,
as a browser is not in CI (scripts/_css_rules.py).

Run: python3 scripts/test_toast_css.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _css_rules import CssRules  # noqa: E402

# The layers of the board's page that a toast is shown over: its dialogs, the request detail, the talk window, and the lanes
# — a cell's window and its shade are drawn inside the lanes' layer.
OVERLAYS = [".modal-overlay", ".topology-llama-edit-overlay", ".history-detail-overlay", ".talk-overlay",
            'html:not([data-board-view="machine"]) .topology-lanes > section',
            'html:not([data-board-view="machine"]) .topology-lanes > section:has(.topology-policy-overlay)']

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def main():
    rules = []
    for css in sorted((ROOT / "static" / "css").glob("*.css")):
        rules += CssRules.rules(css.read_text(encoding="utf-8"))

    def declared(selector):
        merged = {}
        for sel, decl in rules:
            if sel == selector:
                merged.update(decl)
        return merged

    toast = declared("#toast")
    shown = declared("#toast.show")
    layers = {sel: declared(sel).get("z-index") for sel in OVERLAYS}
    check(all(v is not None for v in layers.values()),
          f"every layer named here is in the stylesheets with its z-index (got {layers}) — a renamed one would leave the pin blind")
    z = int(toast.get("z-index", "0") or 0)
    check(toast.get("position") == "fixed" and all(z > int(v) for v in layers.values() if v is not None),
          f"the toast stands over every layer it is shown over: z-index {z} over {sorted(int(v) for v in layers.values() if v)}")
    check(toast.get("pointer-events") == "none" and "pointer-events" not in shown,
          "it takes no clicks, shown or faded; negative: being shown does not give them back")
    check(shown.get("opacity") == "1" and toast.get("opacity") == "0", "negative: faded out it is unseen, shown it is seen — as before")
    print()
    if _fail:
        print(f"toast css FAILED ({len(_fail)}):")
        for msg in _fail:
            print("  - " + msg)
        return 1
    print("toast css OK: over every layer of the board, and never in the way of a click")
    return 0


if __name__ == "__main__":
    sys.exit(main())
