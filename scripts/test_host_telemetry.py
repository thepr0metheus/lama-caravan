#!/usr/bin/env python3
"""Машины со скаутом — посекундно, для графиков доски (скаут 2.8+).

Контроллер рисует свою машину по своему замеру раз в секунду, а машину со
скаутом рисовал по её отчётам: показания карты скаут держал 10 с, отчёт
приходил в лучшем случае раз в несколько секунд. Скаут 2.8 хранит 10 минут
своих посекундных замеров и говорит об этом в отчёте (`telemetry`);
HostTelemetry дотягивает новое у каждой такой машины — не чаще раза в
секунду и не на пути запроса: чтение монитора доской только пинает
дотягивание и отдаёт то, что уже здесь.

Пинится значениями с подменёнными часами, скаутом и запуском потока: у кого
спрашивается и как часто, что копится, что отдаётся доске, что держит запись
машины и что несёт ответ монитора.

Запуск: python3 scripts/test_host_telemetry.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from caravan.admin import fleet_clients as fc  # noqa: E402
from caravan.admin.host_telemetry import HostTelemetry  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


SAMPLED = {"watchedSeconds": 1.0, "idleSeconds": 10.0, "retentionSeconds": 600}


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


class FakeScout:
    def __init__(self, answers):
        self.answers = answers
        self.asked = []

    def read(self, path, timeout=10):
        self.asked.append(path)
        answer = self.answers.pop(0) if self.answers else {"ok": True, "samples": []}
        if isinstance(answer, Exception):
            raise answer
        return answer


def rows(*ts):
    return [{"t": t, "gpus": [{"index": 0, "utilPct": float(t % 100)}], "cpuPct": 1.0} for t in ts]


def rig(hosts, answers=None):
    scouts = {h["id"]: FakeScout(list((answers or {}).get(h["id"], []))) for h in hosts}
    clock = Clock()
    tel = HostTelemetry(lambda: [dict(h) for h in hosts], lambda host_id: scouts[host_id], clock=clock,
                        start=lambda target: target())
    return tel, scouts, clock


def section_who_is_asked():
    print("у кого спрашивается и как часто:")
    hosts = [{"id": "box-a", "state": "online", "telemetry": SAMPLED},
             {"id": "box-b", "state": "stale", "telemetry": SAMPLED},
             {"id": "box-c", "state": "online", "telemetry": None},
             {"id": "box-d", "state": "online"}]
    tel, scouts, clock = rig(hosts)
    check(tel.kick() == ["box-a"],
          "спрашивается машина на связи, чей скаут сказал, что снимает; negative: молчащая, скаут старше 2.8 — нет")
    clock.now += 0.5
    check(tel.kick() == [] and scouts["box-a"].asked == ["/api/telemetry?since=0"],
          "не чаще раза в секунду: вторая доска в ту же секунду нового запроса не вызывает")
    clock.now += 0.6
    check(tel.kick() == ["box-a"], "через секунду — снова")
    busy = HostTelemetry(lambda: [dict(hosts[0])], lambda h: scouts["box-a"], clock=clock, start=lambda target: None)
    busy.kick()
    clock.now += 5
    check(busy.kick() == [], "negative: прошлое дотягивание ещё не кончилось — второе не начинается")


def section_what_is_kept():
    print("что копится:")
    host = {"id": "box-a", "state": "online", "telemetry": SAMPLED}
    tel, scouts, clock = rig([host], {"box-a": [
        {"ok": True, "samples": rows(1000, 1001, 1002)},
        {"ok": True, "samples": rows(1002, 1003)},
        {"ok": False, "error": "box-a unreachable"},
        RuntimeError("socket died"),
        {"ok": True, "samples": rows(*range(1004, 1700))}]})
    for _ in range(2):
        tel.kick()
        clock.now += 1.1
    check([r["t"] for r in tel.since(None)["box-a"]] == [1000, 1001, 1002, 1003],
          "строка с тем же t, что уже есть, не дублируется")
    for _ in range(3):
        tel.kick()
        clock.now += 1.1
    asked = scouts["box-a"].asked
    check(asked[:3] == ["/api/telemetry?since=0", "/api/telemetry?since=1002", "/api/telemetry?since=1003"],
          f"первый раз — всё, дальше — новее последнего, что есть (got {asked[:3]})")
    got = tel.since(0)["box-a"]
    check(got[0]["t"] == 1099 and got[-1]["t"] == 1699 and len(got) == 601,
          "держится 10 минут по часам самой машины")
    tel2, scouts2, clock2 = rig([host], {"box-a": [{"ok": True, "samples": rows(5, 6)}, {"ok": False, "error": "x"}]})
    tel2.kick()
    clock2.now += 2
    tel2.kick()
    check([r["t"] for r in tel2.since(0)["box-a"]] == [5, 6], "negative: машина не ответила — то, что было, остаётся")
    check(tel2.since({"box-a": 5}) == {"box-a": [rows(6)[0]]} and tel2.since({"box-a": 6}) == {},
          "доске — только новее того, что у неё есть по этой машине; пусто — машины в ответе нет")
    check(tel2.since({"box-z": 99}) == {"box-a": rows(5, 6)} and tel2.since(None) == {"box-a": rows(5, 6)},
          "машину, которой у доски нет (пришла позже), доска получает всю — история не теряется")
    check(HostTelemetry.held("box-a:1002, box-b:5,bad,:7,box-c:x,box-d:12.9") == {"box-a": 1002, "box-b": 5, "box-d": 12},
          "hostsSince «id:t,id:t»; мусор пропускается, а не роняет чтение")


def section_the_record():
    print("запись машины:")
    base = {"host": {"id": "box-a", "name": "A"}}
    check(fc.host_from_report({**base, "telemetry": {**SAMPLED, "junk": 1}})["telemetry"] == SAMPLED,
          "скаут 2.8 сказал, как снимает, — запись держит это (без лишнего)")
    check(fc.host_from_report(base)["telemetry"] is None, "negative: старший молчит — None, у него не спрашивают")
    check(fc.scout_payload_from_state({"host": {"id": "box-a"}, "telemetry": SAMPLED}, "u")["telemetry"] == SAMPLED,
          "опрос /api/state несёт то же поле — пульс и опрос не стирают его друг у друга")


def section_the_monitor_read():
    print("ответ монитора доске:")
    import caravan.admin.routes as routes
    sent = []

    class H:
        def send_json(self, payload, status=200):
            sent.append(payload)

    class Parsed:
        query = "since=5&hostsSince=box-a:1001"
    keep = routes.system_monitor_state, routes.HOST_TELEMETRY
    calls = []
    routes.system_monitor_state = lambda since: {"ok": True, "samples": [], "since": since}
    routes.HOST_TELEMETRY = type("T", (), {"watch": lambda self, since: calls.append(since) or {"box-a": rows(1002)}})()
    try:
        routes._get_api_system_monitor(H(), Parsed())
    finally:
        routes.system_monitor_state, routes.HOST_TELEMETRY = keep
    check(sent == [{"ok": True, "samples": [], "since": "5", "hosts": {"box-a": rows(1002)}}] and calls == ["box-a:1001"],
          "GET /api/system-monitor несёт машины со скаутом (hosts) — новее hostsSince; чтение пинает дотягивание")


def main():
    section_who_is_asked()
    section_what_is_kept()
    section_the_record()
    section_the_monitor_read()
    if _fail:
        print(f"\nFAILED ({len(_fail)}):")
        for m in _fail:
            print("  - " + m)
        return 1
    print("\nhost telemetry OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
