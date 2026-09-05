#!/usr/bin/env python3
"""An installer that ships a cell server must ship what that server imports.

The six cell servers used to be standalone files: copy one into $HOME and it
ran. They are not any more — each imports cell_base.py from its own directory —
and an installer that copies only the server produces a cell that starts, fails
on ImportError, and looks to the board like a cell that "did not come up",
with the reason on the client's journal where nobody is reading.

Nothing else catches this. The controller pushes RUNNER_ASSETS in full when it
starts a cell, so the fleet keeps working while the manual installers are
broken; the break shows up the day someone provisions a new host.

So: for every runner, if an installer copies its <runner>_server.py into $HOME,
that script must name every other .py in that runner's assets too.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from caravan.admin.cell_assets import RUNNER_ASSETS  # noqa: E402


def ships(text, name):
    """Whether this script COPIES the file into $HOME.

    Not "mentions": the first version of this asked whether the name appeared
    anywhere in the file, and passed on a script whose only remaining reference
    was the comment explaining why the copy mattered. A guard that cannot fail
    is worse than no guard — it reports the thing it stopped checking as safe.
    """
    return bool(re.search(rf'(install|cp)\b[^\n]*{re.escape(name)}[^\n]*\$\{{?HOME', text))


def main():
    errors = []
    checked = 0
    for script in sorted(ROOT.glob("scripts/install-*.sh")):
        text = script.read_text(encoding="utf-8")
        for runner, assets in RUNNER_ASSETS.items():
            # The server's name, not the runner's: the tts cell is the "custom"
            # runner, and deriving the filename from the key skipped it — the
            # one installer this check most needed to cover.
            servers = [a for a in assets if a.endswith("_server.py")]
            if not servers:
                continue
            server = servers[0]
            if not ships(text, server):
                continue
            checked += 1
            for asset in assets:
                if not asset.endswith(".py") or asset == server:
                    continue
                if not ships(text, asset):
                    errors.append(f"{script.name}: ставит {server}, но не {asset} — "
                                  f"ячейка упадёт на ImportError")
    if not checked:
        errors.append("ни один install-*.sh не кладёт сервер ячейки в $HOME — "
                      "проверка перестала что-либо проверять")
    if errors:
        print("installer assets: FAILED", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1
    print(f"installer assets OK: {checked} установщиков везут всё, что импортирует сервер")
    return 0


if __name__ == "__main__":
    sys.exit(main())
