#!/usr/bin/env python3
"""Ячейка контроллера — к скауту своей машины (шаг 6.8).

Машина контроллера получила своего скаута; её ячейки переезжают к нему по
одной, и контроллер перестаёт запускать ячейки сам. Ячейка сохраняет порт,
конфиг, модель, подпись, заметку, расписание и историю команд (запись
перекладывается под id скаута); маршруты и srv:<порт> канбана — по порту.
Что было только у ячейки контроллера, уходит: start.sh и cell.json — в
сторону, юнит systemd отключается (включённый юнит поднялся бы при загрузке
и подрался со скаутом за порт); юнит, стартовавший с машиной, становится
автозапуском у скаута — ячейка при этом стоит.

Пинится значениями: что переезжает и что уходит, что получает скаут, чего
не бывает при каждом отказе, и что при сбое на полпути запись возвращается
посимвольно. Хранилище, systemd и скаут подменены; папки — во временной.

Запуск: python3 scripts/test_cell_to_scout.py
"""
import copy
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from caravan.admin import cell_move  # noqa: E402
from caravan.common.errors import AppError  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


SLOT = {"id": "controller:22007", "hostId": "controller", "port": 22007, "model": "b/Q8_0/gemma-12B-Q8_0.gguf",
        "label": "gemma", "note": "for the kanban", "schedule": {"on": "09:00", "off": "18:00"},
        "schedState": {"last": "on"}, "commandHistory": [{"at": 1, "cmd": "x"}],
        "config": {"MODEL_FILE": "b/Q8_0/gemma-12B-Q8_0.gguf", "PORT": "22007"},
        "artifact": {"dir": "/var/cells/22007", "startScript": "/var/cells/22007/start.sh"}}
HOST = {"id": "box-pc", "hostname": "box-pc.lan", "agentUrl": "http://127.0.0.1:8092", "autostart": []}


class Rig:
    """The store, systemd and the scout, stood in for and put back."""

    def __init__(self, unit=None, host=None, autostart_ok=True, disable_ok=True, extra_slots=None, answer_ok=True):
        self.store = {"serverSlots": {"controller:22007": copy.deepcopy(SLOT), **(extra_slots or {})},
                      "hosts": {"box-pc": copy.deepcopy(host if host is not None else HOST)}}
        self.unit = unit or {"ActiveState": "inactive", "UnitFileState": "enabled"}
        self.autostart_ok, self.disable_ok, self.answer_ok = autostart_ok, disable_ok, answer_ok
        self.calls, self.saved = [], 0
        self.tmp = tempfile.TemporaryDirectory()
        self.cells = Path(self.tmp.name) / "var" / "server-cells"
        (self.cells / "22007").mkdir(parents=True)
        (self.cells / "22007" / "start.sh").write_text("#!/bin/bash\nexec llama-server\n")

    def __enter__(self):
        names = ("topology_store", "save_admin_state", "cell_service_status", "cell_service_action",
                 "client_llama_autostart", "scout_start_body", "server_cell_dir")
        self.keep = {n: getattr(cell_move, n) for n in names}
        cell_move.topology_store = lambda: self.store
        cell_move.save_admin_state = self.save
        cell_move.cell_service_status = lambda port: dict(self.unit)
        cell_move.cell_service_action = self.action
        cell_move.client_llama_autostart = self.autostart
        cell_move.scout_start_body = lambda host_id, port, slot, check=True: {
            "hostId": host_id, "port": port, "config": slot.get("config"), "modelPath": slot.get("model")}
        cell_move.server_cell_dir = lambda port: self.cells / str(int(port))
        return self

    def save(self):
        self.saved += 1

    def action(self, port, action):
        self.calls.append(("systemctl", action, port))
        if not self.disable_ok:
            raise AppError("Failed to disable unit: Access denied", 500)
        return {"ok": True}

    def autostart(self, body, enabled):
        self.calls.append(("autostart", enabled, body.get("port"), body.get("hostId")))
        if enabled and not self.autostart_ok:
            raise AppError("box-pc unreachable: Connection refused", 502)
        if enabled and not self.answer_ok:
            return {"ok": False, "result": {"error": "the start request is required to turn autostart on"}}
        return {"ok": True}

    def __exit__(self, *exc):
        for n, v in self.keep.items():
            setattr(cell_move, n, v)
        self.tmp.cleanup()

    def move(self, port=22007, host_id="box-pc", hostname="box-pc"):
        try:
            return cell_move.CellToScout(port, host_id, hostname=hostname).run()
        except AppError as exc:
            return ("refused", exc.status, str(exc))


def section_the_move():
    print("переезд ячейки с автозапуском:")
    with Rig() as rig:
        got = rig.move()
        slot = rig.store["serverSlots"].get("box-pc:22007")
        kept = Path(got.get("kept") or "/nowhere")
        check(got["ok"] is True and got["to"] == "box-pc" and got["autostart"] is True
              and "controller:22007" not in rig.store["serverSlots"],
              "запись ячейки контроллера ушла, ячейка теперь у скаута машины")
        check({k: slot.get(k) for k in ("port", "model", "label", "note", "schedule", "schedState", "commandHistory",
                                        "config")} == {k: SLOT[k] for k in ("port", "model", "label", "note", "schedule",
                                                                             "schedState", "commandHistory", "config")}
              and slot["id"] == "box-pc:22007" and slot["hostId"] == "box-pc",
              "порт, модель, подпись, заметка, расписание, история команд и конфиг — те же, под id скаута")
        check("artifact" not in slot, "negative: start.sh контроллера у ячейки скаута не значится — у неё его нет")
        check(rig.calls == [("autostart", True, 22007, "box-pc"), ("systemctl", "disable", 22007)],
              f"юнит стартовал с машиной — скаут получает автозапуск (с тем же запросом старта), потом юнит "
              f"отключается; ничего не запускается (got {rig.calls})")
        check(kept.parent.name == "server-cells-moved" and kept.name.startswith("22007-")
              and (kept / "start.sh").read_text().startswith("#!/bin/bash") and not (rig.cells / "22007").exists(),
              "start.sh и cell.json — отложены рядом (var/server-cells-moved/<порт>-<время>), а не удалены")
    with Rig(unit={"ActiveState": "inactive", "UnitFileState": "disabled"}) as rig:
        got = rig.move()
    check(got.get("autostart") is False and rig.calls == [],
          "negative: юнит не стартовал с машиной — скаут автозапуска не получает, systemctl не трогается")
    with Rig() as rig:
        import shutil
        shutil.rmtree(rig.cells / "22007")
        got = rig.move()
    check(got.get("ok") is True and got.get("kept") == "", "boundary: папки ячейки нет — переезд всё равно, откладывать нечего")


def section_refusals():
    print("отказы — и ничего не меняется:")
    cases = (
        ("работает", {"unit": {"ActiveState": "active", "UnitFileState": "enabled"}}, {}, (409, ":22007 is running — stop it first")),
        ("нет такой ячейки у контроллера", {}, {"port": 22099}, (404, "the controller has no cell on :22099")),
        ("скаута нет", {}, {"host_id": "ghost"}, (404, "no scout has reported for ghost")),
        ("скаут без адреса", {"host": {**HOST, "agentUrl": ""}}, {}, (400, "box-pc reported no scout address")),
        ("скаут другой машины", {}, {"hostname": "the-controller"},
         (400, "box-pc is another machine — a cell of this controller moves only to the scout of the machine it runs on")),
        ("у скаута уже есть этот порт", {"extra_slots": {"box-pc:22007": {"id": "box-pc:22007", "port": 22007}}}, {},
         (409, "box-pc already has a cell on :22007")),
    )
    for what, rig_kw, move_kw, want in cases:
        with Rig(**rig_kw) as rig:
            before = json.dumps(rig.store, sort_keys=True)
            got = rig.move(**move_kw)
            same = json.dumps(rig.store, sort_keys=True) == before
        check(got == ("refused", *want) and same and rig.calls == [] and rig.saved == 0,
              f"negative: {what} — {want[0]}, хранилище посимвольно то же, скаут и systemd не тронуты (got {got})")
    with Rig() as rig:
        got = rig.move(port="x")
    check(got == ("refused", 400, "port must be a number"), "negative: порт не числом — 400")


def section_half_way():
    print("сбой на полпути — запись возвращается:")
    with Rig(autostart_ok=False) as rig:
        before = json.dumps(rig.store, sort_keys=True)
        got = rig.move()
        after = json.dumps(rig.store, sort_keys=True)
        files_stay = (rig.cells / "22007" / "start.sh").exists()
    check(got == ("refused", 502, "box-pc unreachable: Connection refused") and after == before
          and rig.calls == [("autostart", True, 22007, "box-pc")] and files_stay,
          "скаут не принял автозапуск — запись посимвольно прежняя, юнит не отключён, start.sh на месте")
    with Rig(answer_ok=False) as rig:
        before = json.dumps(rig.store, sort_keys=True)
        got = rig.move()
        after = json.dumps(rig.store, sort_keys=True)
    check(got[0] == "refused" and got[1] == 502 and "the scout did not take the autostart" in got[2]
          and after == before and ("systemctl", "disable", 22007) not in rig.calls,
          "скаут ответил, но отказал (ok: false) — это тоже отказ: запись прежняя, юнит не тронут")
    with Rig(disable_ok=False) as rig:
        before = json.dumps(rig.store, sort_keys=True)
        got = rig.move()
        after = json.dumps(rig.store, sort_keys=True)
    check(got[0] == "refused" and got[1] == 500 and "lama-cell@22007.service is still enabled" in got[2]
          and after == before and rig.calls[-1] == ("autostart", False, 22007, "box-pc"),
          "юнит не отключился — автозапуск у скаута снят обратно, запись прежняя: при загрузке не стартуют двое")


def main():
    section_the_move()
    section_refusals()
    section_half_way()
    if _fail:
        print(f"\nFAILED ({len(_fail)}):")
        for m in _fail:
            print("  - " + m)
        return 1
    print("\ncell to scout OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
