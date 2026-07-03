#!/usr/bin/env python3
"""Thin launcher for the lama-caravan proxy daemon. Real code: caravan/proxy/.

This file must keep this name and path: systemd ExecStart runs it directly,
and scripts/test_queue_node.py loads it by path via spec_from_file_location.
"""
import sys
from pathlib import Path

# Repo root must be importable both under `python agent-proxies.py` and when
# this file is loaded by path (spec_from_file_location does not extend sys.path).
_REPO_ROOT = str(Path(__file__).resolve().parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from caravan.proxy.main import main  # noqa: E402
from caravan.proxy.graph import (  # noqa: E402,F401 — scripts/test_queue_node.py
    _queue_spec_from_node,
    apply_router,
    apply_router_spill,
    resolve_graph,
)

if __name__ == "__main__":
    main()
