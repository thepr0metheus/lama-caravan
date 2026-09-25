#!/usr/bin/env python3
"""vLLM на машинах со скаутом — System, раздел vLLM (шаг 6.9).

Раздел обновлял и откатывал vLLM в venv машины контроллера, и только её. С
6.8 ячейки этой машины идут через её скаута, как у любой другой, и vLLM у
каждой машины — в её ~/vllm-venv. Теперь раздел выбирает машину, а за её
vLLM отвечает её скаут (2.9.0+): версия, история, задание установки.
Контроллер свой venv больше не держит.

Пинится значениями: какая машина — «машина контроллера» (ControllerMachine,
по имени хоста из отчёта скаута), список машин и машина по умолчанию, отказ
для старого скаута, для неизвестной машины и когда машин нет, ответ скаута
как есть, и куда уходят установка и её статус. Хранилище и скаут подменены.

Запуск: python3 scripts/test_vllm_machines.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from caravan.admin import fleet_clients as fc  # noqa: E402
from caravan.admin.controller_machine import ControllerMachine  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


HOSTS = [
    {"id": "box-b", "name": "Box B", "state": "online", "hostname": "box-b", "scoutVersion": "2.9.0"},
    {"id": "box-a", "name": "Box A", "state": "online", "hostname": "Box-A.lan", "scoutVersion": "2.9.1"},
    {"id": "old-c", "name": "Old C", "state": "stale", "hostname": "old-c", "scoutVersion": "2.8.2"},
]


class Scout:
    """A scout that answers what it was asked, writing the asks down."""
    asked = []

    def __init__(self, host_id):
        self.host_id = host_id

    def read(self, path, timeout=0):
        Scout.asked.append(("GET", self.host_id, path))
        if path == "/api/vllm":
            return {"ok": True, "installed": True, "version": "0.24.0", "venv": "/home/x/vllm-venv",
                    "history": [{"version": "0.24.0", "seenAt": 1}], "job": {"running": False}}
        return {"running": True, "lines": ["pip…"]}

    def post(self, path, payload=None, timeout=0):
        Scout.asked.append(("POST", self.host_id, path, payload))
        return {"running": True, "tag": "vllm:0.23.1"}


def ask(host_id, hosts=HOSTS, here="box-a"):
    keep = fc.topology_hosts, fc._scout, fc.ControllerMachine
    fc.topology_hosts = lambda: [dict(h) for h in hosts]
    fc._scout = lambda hid: Scout(hid)
    fc.ControllerMachine = lambda: ControllerMachine(here)
    Scout.asked = []
    try:
        return fc.client_vllm(host_id)
    finally:
        fc.topology_hosts, fc._scout, fc.ControllerMachine = keep


def section_controller_machine():
    print("машина контроллера среди машин со скаутом:")
    here = ControllerMachine("box-a")
    check(here.is_host({"hostname": "Box-A.lan"}) and here.is_host({"hostname": "box-a"}),
          "по имени хоста из отчёта скаута: без домена и без учёта регистра")
    check(not here.is_host({"hostname": "box-b"}) and not here.is_host({}) and not here.is_host(None),
          "negative: другое имя, имени нет, записи нет — не она")
    blank = ControllerMachine(".")
    check(blank.hostname == "" and not blank.is_host({"hostname": ""}) and not blank.is_host({"hostname": "."}),
          "negative: имя, от которого ничего не осталось, не совпадает с пустым")
    check(here.host_id(HOSTS) == "box-a" and here.host_id({h["id"]: h for h in HOSTS}) == "box-a",
          "id машины — из списка записей и из словаря по id одинаково")
    check(ControllerMachine("elsewhere").host_id(HOSTS) == "", "negative: скаута на машине контроллера нет — пусто")


def section_machines():
    print("список машин и машина по умолчанию:")
    got = ask("")
    check(got["hostId"] == "box-a", "машина не названа — машина контроллера (скаут на ней же)")
    check(got["machines"] == [
        {"id": "box-b", "name": "Box B", "online": True, "scoutVersion": "2.9.0", "controllerMachine": False},
        {"id": "box-a", "name": "Box A", "online": True, "scoutVersion": "2.9.1", "controllerMachine": True},
        {"id": "old-c", "name": "Old C", "online": False, "scoutVersion": "2.8.2", "controllerMachine": False}],
        "машины — в порядке хостов доски: имя, на связи ли, версия скаута, машина ли контроллера")
    check(got["pinnedDefault"] == "0.24.0", "версия первого провижининга — правило раннера")
    check(got["version"] == "0.24.0" and got["history"] == [{"version": "0.24.0", "seenAt": 1}] and got["ok"] is True,
          "ответ скаута машины — как есть")
    check(Scout.asked == [("GET", "box-a", "/api/vllm")], "спрошен скаут выбранной машины, один раз")
    got = ask("box-b")
    check(got["hostId"] == "box-b" and Scout.asked == [("GET", "box-b", "/api/vllm")],
          "названа машина — её скаут")
    got = ask("", here="elsewhere")
    check(got["hostId"] == "box-b", "boundary: машины контроллера среди них нет — первая машина")


def section_refusals():
    print("отказы — словами, без вызова скаута:")
    got = ask("old-c")
    check(got["ok"] is False and got["error"] == "old-c: its scout 2.8.2 is older than 2.9.0, the first to answer "
                                                  "for vLLM on its machine — update the scout" and Scout.asked == [],
          "скаут старше 2.9.0 — «обновите скаут», а не голый 404")
    check(ask("box-b", hosts=[{**HOSTS[0], "scoutVersion": "2.9.0.dev1"}])["ok"] is True,
          "boundary: dev-сборка 2.9.0 — уже умеет")
    check(ask("box-b", hosts=[{**HOSTS[0], "scoutVersion": "2.8.2.dev1"}])["ok"] is False,
          "negative: dev-сборка старого скаута — всё равно старый: суффикс не прячет версию")
    check(ask("box-b", hosts=[{**HOSTS[0], "scoutVersion": ""}])["ok"] is True,
          "negative: версия не сообщена — спрашиваем скаута, а не отказываем вслепую")
    got = ask("ghost")
    check(got["ok"] is False and got["error"] == "no scout has reported for host ghost" and Scout.asked == [],
          "negative: такой машины нет — отказ")
    got = ask("", hosts=[])
    check(got["ok"] is False and got["error"] == "no machine with a scout has reported yet"
          and got["machines"] == [] and got["hostId"] == "",
          "negative: машин нет вовсе — сказано, что нет")


def section_update():
    print("установка и её ход — у скаута машины:")
    keep = fc._scout
    fc._scout = lambda hid: Scout(hid)
    Scout.asked = []
    try:
        started = fc.client_vllm_update({"hostId": "box-b", "version": " 0.23.1 "})
        status = fc.client_vllm_update_status("box-b")
        fc.client_vllm_update({"hostId": "box-b"})
    finally:
        fc._scout = keep
    check(Scout.asked[0] == ("POST", "box-b", "/api/vllm/update", {"version": "0.23.1"}) and started["tag"] == "vllm:0.23.1",
          "откат: версия без пробелов — скауту машины, его ответ — как есть")
    check(Scout.asked[1] == ("GET", "box-b", "/api/vllm/update-status") and status["lines"] == ["pip…"],
          "ход установки — у того же скаута")
    check(Scout.asked[2] == ("POST", "box-b", "/api/vllm/update", {"version": ""}),
          "без версии — пустая: последний релиз выбирает скаут")


def main():
    section_controller_machine()
    section_machines()
    section_refusals()
    section_update()
    if _fail:
        print(f"\nFAILED ({len(_fail)}):")
        for m in _fail:
            print("  - " + m)
        return 1
    print("\nvllm machines OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
