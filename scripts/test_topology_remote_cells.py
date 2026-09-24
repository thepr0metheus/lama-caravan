#!/usr/bin/env python3
"""Снимок topology_server: ячейки машин со скаутом в ответе доски.

Цикл по ячейкам, о которых отчитываются скауты, ни разу не гонялся тестом. Так
в нём два месяца прожила переменная, которую задавали только command-ячейки, а
читали все: работающая llama-ячейка на машине со скаутом роняла /api/topology
целиком (500 — пустая доска у всех), если перед ней в отчёте не было
работающей command-ячейки, а если была — носила её метаданные: версию сервера
и язык перевода соседки. Нашлось при первом запуске ячейки после переустановки
скаута на машине-доноре.

Пинится значениями: ответ собирается, у llama-ячейки нет чужих метаданных при
любом порядке отчёта, у command-ячейки — свои. Всё, что дошло бы до процесса,
диска или сети, подменено.

Запуск: python3 scripts/test_topology_remote_cells.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import caravan.admin.topology as T  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


HOST = {"id": "box-a", "name": "Box A", "ip": "10.0.0.5", "gpus": [{"name": "G"}]}
# ctxMax and ctxTrained are reported, so nothing reads a slot store or a GGUF
# file for them.
LLAMA = {"port": 22021, "running": True, "phase": "running", "modelPath": "/m/model-a.gguf",
         "ctxMax": 8192, "ctxTrained": 131072}
WHISPER = {"port": 22024, "running": True, "phase": "running", "ctxMax": 1, "ctxTrained": 1}
SLOTS = {
    "box-a:22021": {"id": "box-a:22021", "hostId": "box-a", "port": 22021, "model": "/m/model-a.gguf",
                    "config": {"MODEL_FILE": "/m/model-a.gguf"}},
    "box-a:22024": {"id": "box-a:22024", "hostId": "box-a", "port": 22024,
                    "config": {"RUNNER": "whisper", "HEALTH_PATH": "/health"}},
    "box-a:22023": {"id": "box-a:22023", "hostId": "box-a", "port": 22023,
                    "config": {"RUNNER": "whisper", "HEALTH_PATH": "/health"}},
}
WHISPER_HEALTH = {"status": "ok", "meta": {"source": "d1g3st"}, "targetLang": "en"}


def served(nodes):
    """topology_server over one machine whose scout reports `nodes`. Only
    their slots are stored: a stored cell nobody reports is a parked card,
    which another loop draws."""
    host = dict(HOST, llamaNodes=[dict(n) for n in nodes])
    reported = {n["port"] for n in nodes}
    patch = {
        "service_status": lambda: {"ActiveState": "inactive"},
        "runtime_api": lambda _config: {},
        "runtime_phase": lambda *_a: {},
        "gpu_state": lambda: {"gpus": []},
        "runtime_metrics_sample": lambda: {"ok": False},
        "topology_store": lambda: {"hosts": {"box-a": host},
                                   "serverSlots": {k: dict(v) for k, v in SLOTS.items()
                                                   if v["port"] in reported}},
        "command_cell_health": lambda _ip, port, _path: dict(WHISPER_HEALTH) if port == 22024 else None,
        "remote_llama_health": lambda *_a: "ok",
        "remote_llama_modalities": lambda *_a: None,
        "probe_remote_port": lambda *_a: True,
        "current_locations": lambda: {},
        "_saved_command": lambda *_a: "",
    }
    saved = {k: getattr(T, k) for k in patch}
    try:
        for k, v in patch.items():
            setattr(T, k, v)
        return T.topology_server({"PORT": "8080"})
    finally:
        for k, v in saved.items():
            setattr(T, k, v)


def cells(nodes):
    """{port: (phase, cellMeta)} of the machine's cells — or the error."""
    try:
        answer = served(nodes)
    except Exception as exc:  # noqa: BLE001 — the defect IS an exception
        return f"{type(exc).__name__}: {exc}"
    return {s["port"]: (s["phase"], s["cellMeta"]) for s in answer["llamaServers"] if s.get("isRemote")}


def meta_of(cell_meta):
    """The cell's own words, without our verdict on its version (that one
    reads the shipped cell sources and is pinned elsewhere)."""
    return {k: v for k, v in cell_meta.items() if k != "sourceState"}


def test_llama_cell_alone():
    print("llama-ячейка на машине со скаутом, одна:")
    got = cells([LLAMA])
    check(got == {22021: ("running", {})},
          f"defect-history: ответ собирается, ячейка работает и без чужих метаданных (ответ: {got!r})")


def test_no_neighbour_meta():
    print("соседняя command-ячейка не делится своими словами:")
    for order, nodes in (("whisper, потом llama", [WHISPER, LLAMA]), ("llama, потом whisper", [LLAMA, WHISPER])):
        got = cells(nodes)
        ok = isinstance(got, dict) and set(got) == {22021, 22024}
        check(ok and got[22021] == ("running", {}),
              f"defect-history ({order}): у llama-ячейки нет версии и языка соседки (ответ: {got!r})")
        check(ok and got[22024][0] == "running"
              and meta_of(got[22024][1]) == {"source": "d1g3st", "targetLang": "en"},
              f"negative ({order}): у command-ячейки её собственные версия и язык остаются")


def test_silent_command_cell():
    print("command-ячейка, чей health молчит:")
    got = cells([dict(WHISPER, port=22023), LLAMA])
    check(isinstance(got, dict) and got.get(22021) == ("running", {}) and meta_of(got[22023][1]) == {},
          f"boundary: молчащий health — у обеих пусто, без исключения (ответ: {got!r})")


if __name__ == "__main__":
    for fn in (test_llama_cell_alone, test_no_neighbour_meta, test_silent_command_cell):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            check(False, f"{fn.__name__} упал: {exc!r}")
    if _fail:
        print(f"\nFAILED ({len(_fail)}):")
        for m in _fail:
            print("  - " + m)
        sys.exit(1)
    print("\ntopology remote cells OK")
