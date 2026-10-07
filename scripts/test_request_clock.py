#!/usr/bin/env python3
"""Snapshot of RequestClock and TimedResponse (caravan/proxy/request_clock.py)
by value: what each mark adds up to, and what stays None when it never happened.

Both clocks are driven by hand, so every figure here is exact: a millisecond
off is a failure, not noise.

Run: python3 scripts/test_request_clock.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from caravan.proxy.request_clock import RequestClock, TimedResponse  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


class Hands:
    """A wall clock and a processor clock that move only when told to."""

    def __init__(self):
        self.wall = 100.0
        self.cpu = 10.0

    def at(self, wall):
        self.wall = wall


class FakeAnswer:
    """An upstream answer read in pieces, like http.client's."""

    status = 200
    reason = "OK"

    def __init__(self, pieces):
        self.pieces = list(pieces)

    def read(self, amt=None):
        return self.pieces.pop(0) if self.pieces else b""

    def readline(self, limit=-1):
        return self.read()


def make():
    hands = Hands()
    return hands, RequestClock(clock=lambda: hands.wall, cpu_clock=lambda: hands.cpu)


def test_full_request():
    print("запрос целиком: очередь, подключение, заголовки, первые байты:")
    hands, clock = make()
    hands.at(100.002)
    clock.queue_entered()
    hands.at(101.002)          # a second in the queue: not the caravan's own time
    clock.admitted()
    hands.at(101.005)
    clock.leg_started()
    began = clock.now()
    hands.at(101.057)
    clock.connected(began, reused=False)
    hands.at(101.060)
    clock.sent()
    hands.at(101.260)
    answer = clock.answered(FakeAnswer([b"", b"data: 1\n", b"data: 2\n"]))
    hands.at(101.280)
    answer.read()               # an empty read is not the first bytes
    hands.at(101.300)
    answer.read()
    hands.at(101.900)
    answer.read()
    hands.cpu = 10.012
    got = clock.as_dict()
    check(got["prepMs"] == 5.0, f"своя работа = 2 мс до очереди + 3 мс после неё (получено {got['prepMs']})")
    check(got["connectMs"] == 52.0, f"подключение 52 мс (получено {got['connectMs']})")
    check(got["connReused"] is False, f"соединение новое (получено {got['connReused']!r})")
    check(got["headersMs"] == 200.0, f"заголовки через 200 мс после отправки (получено {got['headersMs']})")
    check(got["firstChunkMs"] == 240.0, f"первые байты через 240 мс, пустое чтение не в счёт (получено {got['firstChunkMs']})")
    check(got["cpuMs"] == 12.0, f"процессор 12 мс (получено {got['cpuMs']})")


def test_kept_connection():
    print("взятое из пула соединение:")
    hands, clock = make()
    clock.leg_started()
    clock.connected(None, reused=True)
    got = clock.as_dict()
    check(got["connectMs"] == 0.0, f"подключения не было: 0 мс (получено {got['connectMs']})")
    check(got["connReused"] is True, f"и это сказано (получено {got['connReused']!r})")


def test_cell_connection():
    print("соединение с ячейкой, где пула нет:")
    hands, clock = make()
    clock.leg_started()
    began = clock.now()
    hands.at(100.0004)
    clock.connected(began, reused=None)
    got = clock.as_dict()
    check(got["connReused"] is None, f"«не из пула» не утверждается: None (получено {got['connReused']!r})")
    check(got["connectMs"] == 0.4, f"а время подключения измерено (получено {got['connectMs']})")


def test_no_upstream():
    print("ответил сам караван — до провайдера не дошло:")
    hands, clock = make()
    clock.queue_entered()
    clock.admitted()
    hands.cpu = 10.003
    got = clock.as_dict()
    for key in ("prepMs", "connectMs", "connReused", "headersMs", "firstChunkMs"):
        check(got[key] is None, f"{key}: None, а не 0 — этого не было (получено {got[key]!r})")
    check(got["cpuMs"] == 3.0, f"процессор посчитан всё равно (получено {got['cpuMs']})")


def test_without_queue_marks():
    print("путь без очереди:")
    hands, clock = make()
    hands.at(100.004)
    clock.leg_started()
    check(clock.as_dict()["prepMs"] == 4.0, f"своя работа — от тела до первой попытки (получено {clock.as_dict()['prepMs']})")


def test_second_leg():
    print("второй выход после отказа первого:")
    hands, clock = make()
    hands.at(100.001)
    clock.leg_started()
    clock.connected(clock.now(), reused=None)
    clock.sent()
    hands.at(100.101)
    first = clock.answered(FakeAnswer([b"error"]))
    first.read()
    hands.at(100.500)
    clock.leg_started()         # the backup: prep stays the first leg's
    began = clock.now()
    hands.at(100.550)
    clock.connected(began, reused=False)
    clock.sent()
    hands.at(100.570)
    got = clock.as_dict()
    check(got["prepMs"] == 1.0, f"своя работа — до ПЕРВОЙ попытки (получено {got['prepMs']})")
    check(got["connectMs"] == 50.0, f"подключение — того выхода, что ответил (получено {got['connectMs']})")
    check(got["headersMs"] is None, f"заголовков второго выхода ещё нет — не первые (получено {got['headersMs']!r})")
    check(got["firstChunkMs"] is None, f"и первых байт тоже (получено {got['firstChunkMs']!r})")


def test_timed_response():
    print("обёртка ответа:")
    hands = Hands()
    answer = TimedResponse(FakeAnswer([b"a\n", b"b\n"]), lambda: hands.wall)
    check(answer.status == 200 and answer.reason == "OK", "статус и причина — у самого ответа")
    check(answer.first_bytes_at is None, "до чтения байт нет")
    hands.at(100.5)
    lines = list(answer)
    check(lines == [b"a\n", b"b\n"], f"перебор отдаёт строки ответа (получено {lines})")
    check(answer.first_bytes_at == 100.5, f"первые байты отмечены при первом чтении (получено {answer.first_bytes_at})")
    raw = FakeAnswer([])
    check(TimedResponse(raw, lambda: 0).raw is raw, "raw — сам обёрнутый ответ")


def test_negative_prep_clamped():
    print("часы назад не идут:")
    hands, clock = make()
    clock.queue_entered()
    hands.at(101.0)
    clock.admitted()
    hands.at(100.5)            # the wall clock stepped back half a second
    clock.leg_started()
    check(clock.as_dict()["prepMs"] == 0.0, f"отрицательное время не пишется (получено {clock.as_dict()['prepMs']})")


for fn in (test_full_request, test_kept_connection, test_cell_connection, test_no_upstream,
           test_without_queue_marks, test_second_leg, test_timed_response, test_negative_prep_clamped):
    fn()

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail:
        print("  - " + m)
    sys.exit(1)
print("all request-clock snapshots hold")
