#!/usr/bin/env python3
"""The machine-level actions the board cannot take back ask the machine's NAME, typed.

The owner, 2026-10-14, on the Disconnect dialog: "just pressing the button is not enough — something must be typed in
the line, the machine's name for example". Letting a machine go (its scout forgets the controller), rebooting it
(every cell of it goes down, the controller's own board with it when it is the controller's) and powering it off (nothing
on the board switches it back on) are the three. Each opens `appConfirmTyped`: its confirm button stays off until the name
is typed, and the gate sits in the dialog's settle (test_js_dialogs.py).

The three places are named here, and none of them may open a dialog a click or a key answers: appConfirm, appPrompt (whose
suggestion Tab takes) or the browser's confirm. A fourth machine-level action adds its place below.

Negative self-test: scripts/test_guards_fail.py.

Run: python3 scripts/check_typed_machine_actions.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class Place:
    """One handler or function that asks, found in a file by what opens it and where it ends."""

    def __init__(self, what, path, start, end, phrase):
        self.what, self.path, self.start, self.end, self.phrase = what, path, start, end, phrase

    def asks_for_the_name(self, block):
        """appConfirmTyped( … , <the name>, { … : the name is its second argument, whatever the question is."""
        return re.search(r"appConfirmTyped\([\s\S]*?,\s*" + self.phrase + r"\s*,\s*\{", block) is not None

    def block(self):
        text = (ROOT / self.path).read_text(encoding="utf-8")
        at = text.find(self.start)
        if at < 0:
            return None
        stop = text.find(self.end, at + len(self.start))
        return text[at:stop if stop > 0 else len(text)]


PLACES = (
    Place("reboot", "static/js/topology-render.js", 'querySelectorAll("[data-reboot-host]")', "\n  });\n", "hostId"),
    Place("power off", "static/js/topology-render.js", 'querySelectorAll("[data-poweroff-host]")', "\n  });\n", "hostId"),
    Place("disconnect (and forget a silent scout)", "static/js/remote-cells.js", "export async function disconnectScout(",
          "\n}\n", "name"),
)
#: A dialog a click answers: appConfirm( and appPrompt( by name — appConfirmTyped( is neither — and the browser's own.
UNTYPED = re.compile(r"\bappConfirm\(|\bappPrompt\(|\bappConfirmChoice\(|\bappConfirmChecks\(|\bconfirm\(|\bprompt\(")


def problems():
    out = []
    for place in PLACES:
        block = place.block()
        if block is None:
            out.append(f"{place.what}: {place.path} no longer has `{place.start}` — the guard cannot find the place")
            continue
        if "appConfirmTyped(" not in block:
            out.append(f"{place.what}: {place.path} does not open appConfirmTyped — the name is not typed")
        elif not place.asks_for_the_name(block):
            out.append(f"{place.what}: {place.path} opens appConfirmTyped, but not with `{place.phrase}` — the machine's "
                       f"name — as the words to type")
        untyped = sorted(set(UNTYPED.findall(block)))
        if untyped:
            out.append(f"{place.what}: {place.path} also opens {', '.join(untyped)} — a click or a key answers it")
    return out


def main():
    found = problems()
    if found:
        print("typed machine actions: FAILED")
        for line in found:
            print("  - " + line)
        return 1
    print(f"typed machine actions OK: {len(PLACES)} places (reboot, power off, disconnect) ask the machine's name, typed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
