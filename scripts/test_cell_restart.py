#!/usr/bin/env python3
"""Value snapshot: a restart of a scout's cell stops it first (POST /api/topology/server-cell/action).

A restart was a start: the scout refused it, "a server is already running on port 22001", and
the cell kept running its old command (2026-10-12, moving the controller machine's cells onto
the NAS library). Now a restart stops the cell, starts it when the stop succeeded, and says so
when it did not. A start and a stop are what they were.

Run: python3 scripts/test_cell_restart.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from caravan.admin import cell_ops  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


SLOT = {"config": {"MODEL_FILE": "q/Qwen/Q8/q.gguf", "PORT": "22031"}, "model": "q/Qwen/Q8/q.gguf"}


class Topo:
    def slot(self, host, port):
        return SLOT


class Scout:
    """The scout as the controller calls it: each call written down, each answer chosen."""

    def __init__(self, stop=None, start=None):
        self.calls = []
        self.stop_answer = stop or {"ok": True}
        self.start_answer = start or {"ok": True, "status": "starting"}

    def stop(self, body):
        self.calls.append(("stop", body.get("hostId"), body.get("port")))
        return self.stop_answer

    def start(self, body):
        self.calls.append(("start", body.get("hostId"), body.get("port")))
        return self.start_answer


def act(action, scout):
    saved = {k: getattr(cell_ops, k) for k in ("topo", "client_llama_stop", "client_llama_start")}
    cell_ops.topo = Topo()
    cell_ops.client_llama_stop = scout.stop
    cell_ops.client_llama_start = scout.start
    try:
        return cell_ops.server_cell_action({"hostId": "forge", "port": 22031, "action": action})
    finally:
        for k, v in saved.items():
            setattr(cell_ops, k, v)


def test_restart():
    print("restart ячейки скаута:")
    scout = Scout()
    got = act("restart", scout)
    check(scout.calls == [("stop", "forge", 22031), ("start", "forge", 22031)],
          f"defect-history: сначала стоп, потом старт — раньше restart был стартом, и скаут отказывал "
          f"«a server is already running» (got {scout.calls})")
    check(got.get("ok") is True and got.get("action") == "restart" and got.get("result", {}).get("status") == "starting",
          "ответ — ответ старта, действие названо restart")

    scout = Scout(stop={"ok": False, "error": "skynet unreachable: timed out"})
    got = act("restart", scout)
    check(scout.calls == [("stop", "forge", 22031)],
          f"negative: стоп не удался — старта нет, ячейку не запускают поверх живой (got {scout.calls})")
    check(got.get("ok") is False and "the stop before the start failed: skynet unreachable: timed out"
          in str(got.get("result", {}).get("error")),
          "отказ называет причину: стоп перед стартом не удался, и почему")


def test_start_and_stop_unchanged():
    print("start и stop — как были:")
    scout = Scout()
    act("start", scout)
    check(scout.calls == [("start", "forge", 22031)], f"start — только старт (got {scout.calls})")
    scout = Scout()
    act("stop", scout)
    check(scout.calls == [("stop", "forge", 22031)], f"stop — только стоп (got {scout.calls})")


for fn in (test_restart, test_start_and_stop_unchanged):
    fn()

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail:
        print("  - " + m)
    sys.exit(1)
print("cell restart snapshot holds")
