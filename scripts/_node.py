"""Finding node — where it actually lives.

A bare `node` isn't enough. On the fleet's controller, node is installed
through nvm and only reaches PATH from an interactive zsh, so any scripted
session — including one running a deploy or a hook — sees nothing, and the
caller honestly prints SKIPPED. Measured once: v22.22.2 works there at
~/.nvm/versions/node/<version>/bin/node, while `command -v node` in bash
finds nothing, and neither does `bash -lc`, because nvm loads from ~/.zshrc.

A check that stands aside for the WRONG reason reads exactly like one that
passed. So this also looks where version managers install things, and if it
still finds nothing, it says where it looked.
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
