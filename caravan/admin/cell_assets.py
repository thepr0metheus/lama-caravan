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
import re

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
    "cell_base.py",
    "moonshine_server.py",
    "run_moonshine.sh",
    "tts_server.py",
    "run_tts.sh",
    "whisper_server.py",
    "run_whisper.sh",
    "transcribe_server.py",
    "run_transcribe.sh",
    "seamless_server.py",
    "run_seamless.sh",
    "translate_server.py",
    "run_translate.sh",
    "engine_cell_server.py",
    "run_engine.sh",
    "strata_launch.py",
    "run_strata.sh",
    "gr00t_server.py",
    "run_gr00t.sh",
    "lfm_audio_server.py",
    "run_lfm_audio.sh",
    "run_personaplex.sh",
    "run_vllm_omni.sh",
    "run_minicpm_omni.sh",
)

# Which assets a runner needs in $HOME before its command can run. The command
# names the launcher; the launcher expects its server next to it.
# cell_base.py rides with every python server: the subclass imports it, so a
# client that received only the subclass has a cell that cannot start. The scout
# fetches exactly what this table names, so naming it here is what puts it on
# the client — an older scout included, since it reads the list from us.
RUNNER_ASSETS = {
    "moonshine": ("run_moonshine.sh", "cell_base.py", "moonshine_server.py"),
    "whisper": ("run_whisper.sh", "cell_base.py", "whisper_server.py"),
    "custom": ("run_tts.sh", "cell_base.py", "tts_server.py"),
    "transcribe": ("run_transcribe.sh", "cell_base.py", "transcribe_server.py"),
    "seamless": ("run_seamless.sh", "cell_base.py", "seamless_server.py"),
    "translate": ("run_translate.sh", "cell_base.py", "translate_server.py"),
    # Strata serves itself (its own server.py, in the engine's install); the
    # caravan brings only what makes its files and starts it.
    "strata": ("run_strata.sh", "strata_launch.py"),
    # GR00T's runtime is NVIDIA's (scripts/install-gr00t.sh); the cell that serves it over HTTP
    # is ours, and runs with the runtime's Python.
    "gr00t": ("run_gr00t.sh", "cell_base.py", "gr00t_server.py"),
    # A cell whose model runs inside an engine next to it. Its server needs
    # only the standard library; the launcher is there because a scout brings
    # a cell's files by the run_<name>.sh its command names — the two engines
    # share it, and a scout that finds it under ollama fetches the same files.
    "ollama": ("run_engine.sh", "cell_base.py", "engine_cell_server.py"),
    "lmstudio": ("run_engine.sh", "cell_base.py", "engine_cell_server.py"),
    # The servers that answer in a voice (1.3.553: runners of their own — LauncherCellMixin in runner.py; in 1.3.551 they
    # were custom commands with presets, whose files were a GROUP named after the launcher, and the groups kept their names).
    # The scout asks the manifest which group a cell's runner id names and fetches it — no scout release for a new one.
    # The board's stale-source check follows the same group (cell_source_state): LFM's server is not the TTS server
    # that "custom" stands for.
    "lfm-audio": ("run_lfm_audio.sh", "cell_base.py", "lfm_audio_server.py"),
    # PersonaPlex serves itself (NVIDIA's moshi.server and its page): the launcher is all that is ours.
    "personaplex": ("run_personaplex.sh",),
    # vLLM-Omni serves itself (`vllm serve --omni`): the launcher installs it and writes the deploy file, and that is all.
    # One engine, one runner per model family (each its own recipe and footprint): the same launcher under both ids.
    "step-audio2": ("run_vllm_omni.sh",),
    "qwen3-omni": ("run_vllm_omni.sh",),
    # llama.cpp-omni builds and serves itself: the launcher builds the server and links the model folder.
    "minicpm-omni": ("run_minicpm_omni.sh",),
}

#: The launcher a command line names: run_<stem>.sh. The scout reads the same pattern (cell_assets.py there).
LAUNCHER_RE = re.compile(r"\brun_([a-z0-9_]+)\.sh\b")


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


def group_for_command(command: str) -> str:
    """The asset group whose launcher a command names, "" when it names none of ours.

    A custom command hosts any of several servers, and the runner id "custom" stands for only one of them
    (the TTS server): the version a cell should be running is the version of the files of ITS launcher. A cell of
    the launcher runners names its launcher too, and gets its own runner's group: where two runners share a
    launcher (the vLLM-Omni families) the files are the same under either.
    """
    found = LAUNCHER_RE.search(str(command or ""))
    if not found:
        return ""
    launcher = f"run_{found.group(1)}.sh"
    return next((group for group, names in RUNNER_ASSETS.items() if launcher in names), "")


def server_stamp(runner: str) -> str:
    """The stamp a cell of this runner reports in /health when it is running the
    version we currently ship — the first 12 hex of the server's sha256.

    Kept in step with `_source_stamp()` in cells/cell_base.py: the cell hashes
    the code it is RUNNING, we hash the same files here. Both sides cover the
    base AND the subclass — the behaviour lives in two files now, and a fix to
    the base with an untouched subclass is still a cell running yesterday's
    code. Same files, same order (sorted by absolute path), same concatenation:
    if the two ever disagree, every cell reports "stale" forever and nobody can
    tell which ones really are.

    "" when the runner has no python server (vLLM, llama-server) or a file is
    missing.
    """
    paths = sorted(os.path.abspath(os.path.join(CELLS_DIR, name))
                   for name in assets_for_runner(runner) if name.endswith(".py"))
    if not paths:
        return ""
    parts = []
    for path in paths:
        try:
            with open(path, "rb") as fh:
                parts.append(fh.read())
        except OSError:
            return ""
    return hashlib.sha256(b"\n".join(parts)).hexdigest()[:12]


def cell_source_state(runner: str, reported: str, command: str = "") -> str:
    """Compare what a running cell says it loaded against what we ship.

      "current" — the running process holds the version in cells/
      "stale"   — it holds an older one; a restart picks the new one up
      "unknown" — the cell does not report a stamp at all

    `command` is the cell's launch command: when it names a launcher of ours, that launcher's group of
    files is what the cell should be running, not the runner id's.

    "unknown" is a real answer and deliberately not folded into "stale". A cell
    server predating this mechanism cannot report, so a stamp we cannot read
    means "nobody can tell" — which is the honest thing to show, and which
    stopped being true for everything shipped after 1.3.147.
    """
    want = server_stamp(group_for_command(command) or runner)
    got = str(reported or "").strip()
    if not want or not got:
        return "unknown"
    return "current" if got == want else "stale"
