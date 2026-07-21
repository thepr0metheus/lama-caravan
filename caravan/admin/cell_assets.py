"""The cell servers themselves — the launchers and HTTP servers that a command
cell actually runs (moonshine, whisper, tts).

WHY THE CONTROLLER OWNS THEM. The controller already decides WHAT a command
cell runs: runners.py builds `bash $HOME/run_moonshine.sh "$PORT" en` and hands
it to whoever will execute it. Until now it did not supply the script it names,
so each host had to obtain it on its own — clients through their caravan-scout
clone, the controller through somebody copying a file in by hand. The copies
drifted silently, because nothing ever compared them.

Now the file ships from here. `cells/` in this repo is the only home; the
controller materializes it into its own $HOME before starting a local cell, and
a scout fetches it over the fleet channel it already uses for everything else.
A client that has not pulled anything in months still runs the current cell.

The assets are small (a few KB each) and there are six, so the manifest carries
a hash per file and callers skip what they already match — no versioning
protocol beyond that.
"""
import hashlib
import os

from caravan.common.errors import AppError

# Repo-relative home of the cell servers. Flat on purpose: they are published
# as one set, and a scout asks for them by bare filename.
CELLS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "cells")

# Only these ever leave the controller. An allowlist rather than a directory
# listing: this endpoint hands files to every agent in the fleet, so a stray
# file dropped into cells/ must not become fleet-readable by accident.
CELL_ASSETS = (
    "moonshine_server.py",
    "run_moonshine.sh",
    "tts_server.py",
    "run_tts.sh",
    "whisper_server.py",
    "run_whisper.sh",
)

# Which assets a runner needs in $HOME before its command can run. The command
# names the launcher; the launcher expects its server next to it.
RUNNER_ASSETS = {
    "moonshine": ("run_moonshine.sh", "moonshine_server.py"),
    "whisper": ("run_whisper.sh", "whisper_server.py"),
    "custom": ("run_tts.sh", "tts_server.py"),
}


def _asset_path(name: str) -> str:
    if name not in CELL_ASSETS:
        raise AppError(f"unknown cell asset: {name}", 404)
    path = os.path.join(CELLS_DIR, name)
    if not os.path.isfile(path):
        raise AppError(f"cell asset missing on controller: {name}", 500)
    return path


def asset_digest(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def cell_assets_manifest() -> dict:
    """{name: {sha256, size, mode}} for everything the fleet may fetch."""
    out = {}
    for name in CELL_ASSETS:
        path = os.path.join(CELLS_DIR, name)
        if not os.path.isfile(path):
            continue          # reported as missing only when actually asked for
        out[name] = {
            "sha256": asset_digest(path),
            "size": os.path.getsize(path),
            # launchers must land executable; servers are run via the venv python
            "executable": name.endswith(".sh"),
        }
    return {"assets": out, "runners": {k: list(v) for k, v in RUNNER_ASSETS.items()}}


def cell_asset_bytes(name: str) -> bytes:
    with open(_asset_path(name), "rb") as fh:
        return fh.read()


def materialize_local_assets(names=None, home=None) -> dict:
    """Copy assets into the controller's own $HOME, where the cell command
    looks for them. Same destination a scout writes to on a client, so one
    command string works on every host.

    Returns {name: "written"|"current"} and never raises for a single bad file:
    a cell whose asset cannot be refreshed should still start with whatever is
    already on disk rather than be blocked by a bookkeeping error.
    """
    home = home or os.path.expanduser("~")
    result = {}
    for name in (names or CELL_ASSETS):
        try:
            src = _asset_path(name)
            dst = os.path.join(home, name)
            payload = open(src, "rb").read()
            if os.path.isfile(dst) and open(dst, "rb").read() == payload:
                result[name] = "current"
                continue
            tmp = dst + ".new"
            with open(tmp, "wb") as fh:
                fh.write(payload)
            if name.endswith(".sh"):
                os.chmod(tmp, 0o755)
            os.replace(tmp, dst)          # atomic: never a half-written launcher
            result[name] = "written"
        except Exception as exc:  # noqa: BLE001
            result[name] = f"failed: {exc}"
    return result


def assets_for_runner(runner: str):
    return RUNNER_ASSETS.get(str(runner or "").strip().lower(), ())
