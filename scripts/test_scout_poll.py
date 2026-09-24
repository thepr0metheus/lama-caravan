#!/usr/bin/env python3
"""The scouts' state is pulled in the background, never inside a board read.

GET /api/topology used to call every scout's /api/state one after another, two
seconds of timeout each: one machine switched off added two seconds to every
board poll. The read now only kicks a pull (caravan/admin/scout_poll.py): at
most one at a time, at most one per MIN_INTERVAL, and the read never waits.

Run: python3 scripts/test_scout_poll.py
"""
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from caravan.admin.scout_poll import ScoutPoller  # noqa: E402

FAILURES = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        FAILURES.append(msg)


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_one_pull_at_a_time():
    print("не больше одного опроса за раз и не чаще интервала:")
    clock, started, pulls = Clock(), [], []
    poller = ScoutPoller(lambda: pulls.append(clock.now), clock=clock, start=started.append)
    check(poller.kick() is True and len(started) == 1, "первый пинок запускает опрос")
    check(poller.kick() is False and len(started) == 1,
          "negative: пока опрос идёт, второй не запускается — доска опрашивает часто, скауты не должны")
    clock.now += ScoutPoller.MIN_INTERVAL * 3
    check(poller.kick() is False and len(started) == 1,
          "negative: опрос висит дольше интервала (скаут молчит до таймаута) — второй рядом с ним не встаёт")
    clock.now -= ScoutPoller.MIN_INTERVAL * 3
    started[0]()
    check(pulls == [1000.0], "запущенный опрос выполняет pull")
    clock.now += ScoutPoller.MIN_INTERVAL - 0.1
    check(poller.kick() is False, "negative: опрос кончился, но интервал не вышел — нового нет")
    clock.now += 0.1
    check(poller.kick() is True and len(started) == 2, "boundary: ровно через интервал — новый опрос")


def test_a_failure_does_not_wedge_the_gate():
    print("упавший опрос не запирает ворота:")
    clock, started = Clock(), []

    def pull():
        raise OSError("scout unreachable")
    poller = ScoutPoller(pull, clock=clock, start=started.append)
    poller.kick()
    started[0]()
    clock.now += ScoutPoller.MIN_INTERVAL
    check(poller.kick() is True, "исключение внутри pull не наружу, и следующий опрос запускается")

    def no_thread(_target):
        raise RuntimeError("can't start new thread")
    poller = ScoutPoller(lambda: None, clock=clock, start=no_thread)
    try:
        poller.kick()
        raised = False
    except RuntimeError:
        raised = True
    check(raised, "negative: поток не стартовал — это видно вызывающему, а не проглочено")
    poller._start = started.append
    clock.now += ScoutPoller.MIN_INTERVAL
    check(poller.kick() is True, "и ворота не остались запертыми: через интервал опрос снова запускается")


def test_the_read_never_waits():
    print("чтение доски не ждёт опроса:")
    release, done = threading.Event(), threading.Event()

    def slow_pull():
        release.wait(5)
        done.set()
    poller = ScoutPoller(slow_pull)
    began = time.monotonic()
    started = poller.kick()
    spent = time.monotonic() - began
    check(started is True and spent < 0.5,
          f"пинок возвращается сразу, пока опрос ещё идёт (заняло {spent:.3f} с)")
    check(not done.is_set(), "negative: к возврату опрос не закончен — он в своём потоке")
    release.set()
    check(done.wait(5), "опрос доходит до конца в фоне")


for fn in (test_one_pull_at_a_time, test_a_failure_does_not_wedge_the_gate, test_the_read_never_waits):
    fn()

if FAILURES:
    print(f"\nFAILED ({len(FAILURES)}):")
    for f in FAILURES:
        print("  - " + f)
    sys.exit(1)
print("\nscout poll OK")
