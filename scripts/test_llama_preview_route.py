#!/usr/bin/env python3
"""Value snapshot: POST /api/llama-command-preview for a cell of every runner.

The editor asks this route for a saved cell's current command whatever the cell
runs on (llama-edit.js setEditCurrentCommand), and for the llama preview while
the form changes. Only llama.cpp's runners have a llama-server line; for every
other one the builder reached for a server_binary the runner does not have, and
the route answered 500 with Python's own message — for every vLLM, Strata,
whisper or custom cell the editor opened (stand check, 2026-10-13). The route's
own contract is an answer of ok: false, still 200, for a config it cannot build.

Run: python3 scripts/test_llama_preview_route.py
"""
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from caravan.admin import model_locator, routes  # noqa: E402
from caravan.admin.model_locator import Locations  # noqa: E402
from caravan.domain.runner import REGISTRY, runner_id  # noqa: E402

ROUTE = "/api/llama-command-preview"
_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


class Handler:
    def __init__(self):
        self.sent = []

    def send_json(self, body, status=200):
        self.sent.append((status, body))


def preview(config):
    """(status, body) as the page gets it; an exception is what the server sends as a 500."""
    h = Handler()
    keep = model_locator.current_locations
    model_locator.current_locations = lambda wait=False: Locations([])
    try:
        routes.POST_ROUTES[ROUTE](h, urlparse(ROUTE), {"config": config})
    except Exception as exc:  # noqa: BLE001 — the dispatcher's 500, named
        return 500, {"error": f"{type(exc).__name__}: {exc}"}
    finally:
        model_locator.current_locations = keep
    return h.sent[-1] if h.sent else (None, None)


def main():
    cell = {"MODEL_FILE": "org/m.gguf", "PORT": "22009", "VLLM_MODEL": "org/m", "COMMAND": "echo hi"}
    print("ячейки llama.cpp — строка llama-server:")
    for rid in ("llama-server", "prism"):
        status, body = preview({**cell, "RUNNER": rid})
        tokens = (body or {}).get("tokens") or []
        check(status == 200 and body.get("ok") is True and tokens and tokens[0].endswith("llama-server")
              and "--model" in tokens,
              f"{rid}: 200, ok, первая лексема — llama-server (получено {status}, {str(body)[:120]})")

    print("ячейки других раннеров — отказ по имени, а не 500:")
    others = [r.id for r in REGISTRY if not r.llama_config]
    check(len(others) >= 10, f"в реестре есть раннеры не llama.cpp: {others}")
    for rid in others:
        status, body = preview({**cell, "RUNNER": rid})
        want = {"ok": False, "error": f"the {rid} runner builds its own command, not a llama-server line",
                "tokens": []}
        check(status == 200 and body == want,
              f"defect-history: {rid} — 200 и ok: false с причиной; было 500 «no attribute 'server_binary'» "
              f"на каждое открытие сохранённой ячейки (получено {status}, {str(body)[:140]})")
    status, body = preview({**cell, "RUNNER": "nonsense"})
    check(status == 200 and (body or {}).get("ok") is False
          and body.get("error") == f"the {runner_id({'RUNNER': 'nonsense'}) or 'unknown'} runner builds its own "
                                   f"command, not a llama-server line",
          f"negative: раннер, которого нет в реестре, — тоже отказ по имени, не 500 (получено {status}, {body})")

    print()
    if _fail:
        print(f"FAILED ({len(_fail)}):")
        for m in _fail:
            print("  - " + m)
        return 1
    print(f"llama preview route OK: {len(others) + 3} раннеров, ни одного 500")
    return 0


if __name__ == "__main__":
    sys.exit(main())
