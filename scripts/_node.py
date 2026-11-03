"""Finding node — where it actually lives — and the one way a test starts it.

A bare `node` isn't enough. On the fleet's controller, node is installed
through nvm and only reaches PATH from an interactive zsh, so any scripted
session — including one running a deploy or a hook — sees nothing, and the
caller honestly prints SKIPPED. Measured once: v22.22.2 works there at
~/.nvm/versions/node/<version>/bin/node, while `command -v node` in bash
finds nothing, and neither does `bash -lc`, because nvm loads from ~/.zshrc.

A check that stands aside for the WRONG reason reads exactly like one that
passed. So this also looks where version managers install things, and if it
still finds nothing, it says where it looked.

Every node a test or a guard starts is started through `node_args` (or
`probe_args`, for a probe served by the stub loader): what every start needs
(`NODE_FLAGS`) is said here once, and check_node_start.py turns red on a
command line built anywhere else. The module stays functions, not a class: it
holds two rules without state — where node lives and the line it is started
with — and a class would only wrap them.
"""
import os
import shutil
from pathlib import Path

# Version managers that put node somewhere other than the system PATH.
_VERSION_MANAGER_GLOBS = (
    ".nvm/versions/node/*/bin/node",
    ".fnm/node-versions/*/installation/bin/node",
    ".local/share/fnm/node-versions/*/installation/bin/node",
    ".volta/tools/image/node/*/bin/node",
    ".asdf/installs/nodejs/*/bin/node",
)

#: What every node a test starts is given, before its own arguments.
#: --single-threaded: no V8 background threads. With them node could hang for
#: good inside process.exit, after the probe had printed its answer: the main
#: thread waits to join a V8 background thread, and that thread (a baseline
#: compile that needed memory) waits for a garbage collection only the main
#: thread makes. Measured on v24.1.0, 2026-10-21, with `sample` of the hung
#: process: the heaviest pin of test_js_river.py (startled trout in 36 streams)
#: hung in about one run of its pins in six. Turning off only that compiler
#: (--no-concurrent-sparkplug) made it rarer, not gone; with no background
#: threads, 40 runs of the 62 pins (2480 probes) went clean. A hang is a red
#: CI for nothing, and the runner's timeout says nothing about the cause.
NODE_FLAGS = ("--single-threaded",)


def node_search_paths():
    """Where we look, in order of preference. For the failure message."""
    places = ["PATH"]
    home = Path.home()
    places += [str(home / g) for g in _VERSION_MANAGER_GLOBS]
    return places


def find_node():
    """Path to a usable node, or None."""
    on_path = shutil.which("node")
    if on_path:
        return on_path
    home = Path.home()
    for pattern in _VERSION_MANAGER_GLOBS:
        # Newest version first: sorted by the version directory's name.
        found = sorted(home.glob(pattern), key=lambda p: p.parts, reverse=True)
        for candidate in found:
            if os.access(candidate, os.X_OK):
                return str(candidate)
    return None


def node_args(node, *args):
    """The command line of a test's node: its path, NODE_FLAGS, then `args`, each as a string."""
    return [node, *NODE_FLAGS, *(str(a) for a in args)]


def probe_args(node, harness, probe):
    """node on a probe whose imports go through the stub loader `harness` (scripts/_js_harness.mjs)."""
    hook = f"data:text/javascript,import {{ register }} from 'node:module'; register('{Path(harness).as_uri()}');"
    return node_args(node, "--import", hook, probe)
