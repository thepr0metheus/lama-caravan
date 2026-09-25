#!/usr/bin/env python3
"""Снимок значениями: плановое выключение машины (host_power_schedule).

Выключение — дверь в одну сторону: доска машину не включит. Поэтому снимок
держит, КОГДА тик стреляет (окно в три минуты от `at`, раз в дату), что
делает разовое и ежедневное, и КОГО он выключает.

Последнее — из-за шага 6.9. Узел контроллера ушёл с доски, а расписание,
записанное на id контроллера, осталось заряженным и не рисовалось нигде:
отсутствие, похожее на «расписания нет», которое ночью выключает машину.
Теперь оно переезжает на узел машины контроллера — узел её скаута, — где
его видно и можно выключить.

Хранилище, часы, выключение и имя машины подменены.

Запуск: python3 scripts/test_host_power_schedule.py
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from caravan.admin import host_power, host_power_schedule as hps  # noqa: E402
from caravan.admin.controller_machine import ControllerMachine  # noqa: E402
from caravan.admin.paths import LEGACY_CONTROLLER_HOST_IDS  # noqa: E402

#: The controller's id from before the sentinel, read from the code rather
#: than spelled here: it is a machine's name.
OLD_ID = LEGACY_CONTROLLER_HOST_IDS[0]

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def clock(hh, mm, day=25):
    return time.strptime(f"2026-09-{day:02d} {hh:02d}:{mm:02d}", "%Y-%m-%d %H:%M")


HOSTS = {"box-a": {"id": "box-a", "hostname": "box-a"},
         "box-c": {"id": "box-c", "hostname": "box-c.lan"}}


def tick(schedules, at, hosts=HOSTS, here="box-c"):
    """One tick over a store holding these schedules; what it powered off,
    whether it saved, and the schedules after."""
    store = {"hostPowerSchedules": schedules, "hosts": hosts}
    fired, saved = [], []
    keep = (hps.topology_store, hps.save_admin_state, hps.ControllerMachine, host_power.host_power)
    hps.topology_store = lambda: store
    hps.save_admin_state = lambda: saved.append(1)
    hps.ControllerMachine = lambda: ControllerMachine(here)
    host_power.host_power = lambda body, action="reboot": fired.append((body["hostId"], action)) or {"ok": True}
    try:
        hps.power_schedule_tick(now=at)
    finally:
        hps.topology_store, hps.save_admin_state, hps.ControllerMachine, host_power.host_power = keep
    return fired, bool(saved), store["hostPowerSchedules"]


def daily(at="03:20", **kw):
    return {"enabled": True, "at": at, "daily": True, **kw}


def section_when():
    print("когда тик стреляет:")
    fired, saved, after = tick({"box-a": daily()}, clock(3, 20))
    check(fired == [("box-a", "poweroff")] and saved and after["box-a"]["lastFired"] == "2026-09-25"
          and after["box-a"]["enabled"] is True,
          "в минуту `at` — выключение этой машины, дата записана, ежедневное остаётся включённым")
    check(tick({"box-a": daily()}, clock(3, 22))[0] == [("box-a", "poweroff")],
          "тик опоздал на две минуты — всё равно стреляет: окно три минуты")
    check(tick({"box-a": daily()}, clock(3, 23))[0] == [] and tick({"box-a": daily()}, clock(3, 19))[0] == [],
          "negative: минутой раньше и на четвёртой минуте — нет")
    fired, saved, _ = tick({"box-a": daily(lastFired="2026-09-25")}, clock(3, 21))
    check(fired == [] and not saved, "negative: в эту дату уже стреляло — второго раза нет, и ничего не записано")
    check(tick({"box-a": daily(lastFired="2026-09-24")}, clock(3, 21, day=25))[0] == [("box-a", "poweroff")],
          "на следующий день — снова")
    fired, _, after = tick({"box-a": daily(daily=False)}, clock(3, 20))
    check(fired == [("box-a", "poweroff")] and after["box-a"]["enabled"] is False,
          "разовое: выстрелило и выключилось — завтра не повторится")
    check(tick({"box-a": {**daily(), "enabled": False}}, clock(3, 20))[0] == [],
          "negative: выключенное расписание не стреляет")
    check(tick({"box-a": daily(at="23:59")}, clock(0, 0, day=26))[0] == [],
          "negative: окно не переходит через полночь")


def section_the_controllers_own():
    print("расписание на id контроллера — на узел его машины (шаг 6.9):")
    fired, saved, after = tick({"controller": daily(lastFired="2026-09-24")}, clock(3, 20))
    check("controller" not in after and after.get("box-c") == daily(lastFired="2026-09-25"),
          "переехало под id машины контроллера (её узел на доске) со своим временем и режимом")
    check(fired == [("box-c", "poweroff")] and saved,
          "и стреляет уже через неё — через скаута той же машины; переезд записан")
    fired, saved, after = tick({OLD_ID: daily(at="04:00")}, clock(3, 20))
    check(after == {"box-c": daily(at="04:00")} and fired == [] and saved,
          "старый id контроллера — так же; не его минута — только переезд, без выключения")
    fired, _, after = tick({"controller": daily(at="03:20"), "box-c": daily(at="05:00")}, clock(3, 20))
    check(after == {"box-c": daily(at="05:00")} and fired == [],
          "у узла машины уже есть своё — остаётся оно, то, что видно; старое снято и не стреляет")
    fired, saved, after = tick({"controller": daily()}, clock(3, 20), here="elsewhere")
    check(after.get("controller", {}).get("lastFired") == "2026-09-25" and fired == [("controller", "poweroff")]
          and saved,
          "negative: скаут машины контроллера не отчитался — ничего не переезжает, старый ключ стреляет как прежде")
    fired, saved, after = tick({"old-name": daily(at="04:00")}, clock(3, 20))
    check(after == {"old-name": daily(at="04:00")} and fired == [] and not saved,
          "as-is: расписание машины, которой нет на доске (старое имя), не трогается — оно тоже нигде не "
          "нарисовано; это шаг 7 (устойчивый id машины)")


def section_setting():
    print("включение расписания:")
    store = {}
    keep = hps.topology_store, hps.save_admin_state, hps.time.localtime
    hps.topology_store = lambda: store
    hps.save_admin_state = lambda: None
    try:
        hps.time.localtime = lambda *a: clock(3, 30)
        past = hps.set_host_power_schedule({"hostId": "box-a", "schedule": {"enabled": True, "at": "03:20"}})
        ahead = hps.set_host_power_schedule({"hostId": "box-b", "schedule": {"enabled": True, "at": "03:40"}})
        off = hps.set_host_power_schedule({"hostId": "box-d", "schedule": {"at": "03:20"}})
    finally:
        hps.topology_store, hps.save_admin_state, hps.time.localtime = keep
    check(past["schedule"] == {"enabled": True, "at": "03:20", "daily": True, "lastFired": "2026-09-25"},
          "время сегодня уже прошло — помечено «сегодня стреляло»: включение задним числом не выключает")
    check(ahead["schedule"] == {"enabled": True, "at": "03:40", "daily": True},
          "время сегодня впереди — выстрелит сегодня")
    check(off["schedule"] == {"enabled": False, "at": "03:20", "daily": True} and sorted(store["hostPowerSchedules"])
          == ["box-a", "box-b", "box-d"],
          "negative: выключенное — без пометки; все три записаны под своими id")


def main():
    section_when()
    section_the_controllers_own()
    section_setting()
    if _fail:
        print(f"\nFAILED ({len(_fail)}):")
        for m in _fail:
            print("  - " + m)
        return 1
    print("\nhost power schedule OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
