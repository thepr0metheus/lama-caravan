#!/usr/bin/env python3
"""Queue-wait thresholds, by value: the arithmetic over each port's wait budget.

The thresholds moved out of admin/openclaw.py when the OpenClaw config
managers went (2026-09-24): the budget is the operator's number on the port
now, and what is left is the share of it after which a waiting request
overflows to the cloud, preempts, or is aborted. The cache and its lock were
module globals; they are one object's fields, read through latest().

Run: python3 scripts/test_queue_thresholds.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import caravan.admin.queue_thresholds as qt  # noqa: E402

FAILURES = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        FAILURES.append(msg)


def harness(routes, policy=None):
    """The module's collaborators pointed at in-memory values; returns the
    list the mirror is written into."""
    written = []
    qt.load_agent_proxy_config = lambda: {"routes": routes, "policy": policy or {}}
    qt.normalize_agent_proxy_policy = lambda _p: {}
    qt.read_agent_proxy_payload = lambda: {"routes": routes}
    qt.write_agent_proxy_payload = lambda payload: written.append(payload)
    return written


def test_shares_of_the_budget():
    print("пороги — доли бюджета ожидания порта:")
    written = harness([
        {"id": "p1", "port": 23001, "label": "one", "clientTimeoutSeconds": 1800,
         "cloudFallbackProviderId": "cloud-a"},
        {"id": "p2", "port": 23003, "label": "two", "clientTimeoutSeconds": 600, "queueAbortPct": 50},
        {"id": "p3", "port": 23005, "label": "cloud", "upstreamType": "cloud", "clientTimeoutSeconds": 900},
        {"id": "p4", "port": 23007, "label": "no budget"},
        "not a route",
    ])
    q = qt.QueueThresholds()
    out = q.compute()
    rows = {r["port"]: r for r in out["proxies"]}
    check(sorted(rows) == [23001, 23003],
          f"считаются только порты с бюджетом и не облачные (got {sorted(rows)})")
    one = rows[23001]
    check((one["queueAbortSec"], one["priorityPreemptSec"], one["cloudFallbackSec"]) == (1530, 900, 360),
          f"по умолчанию 85 / 50 / 20 процентов от 1800 с (got {one['queueAbortSec']}, "
          f"{one['priorityPreemptSec']}, {one.get('cloudFallbackSec')})")
    two = rows[23003]
    check(two["queueAbortSec"] == 300 and two["hasAbortOverride"] is True,
          "своя доля порта побеждает политику, и это отмечено")
    check("cloudFallbackSec" not in two,
          "negative: без облачного запасного выхода нет и порога ухода в облако — не ноль, а отсутствие")
    check(q.latest() is out, "latest() отдаёт последний расчёт")
    check(len(written) == 1 and written[0]["computedThresholds"] is out,
          "расчёт зеркалится в agent-proxies.json один раз")


def test_before_and_after_a_failure():
    print("до первого расчёта и после неудачного:")
    harness([])
    q = qt.QueueThresholds()
    check(q.latest() is None, "до первого расчёта — None, а не пустые пороги")
    check(q.compute() is None and q.latest() is None,
          "as-is: портов с бюджетом нет — расчёт падает внутри (доли политики берутся "
          "из переменных цикла, которых не было) и возвращает None; прежнее значение не тронуто")
    qt.load_agent_proxy_config = lambda: (_ for _ in ()).throw(OSError("disk"))
    check(q.compute() is None, "negative: конфиг не читается — None, без исключения наружу")


def test_refresh_keeps_going():
    print("фоновое обновление:")
    harness([{"id": "p1", "port": 23001, "clientTimeoutSeconds": 100}])
    q = qt.QueueThresholds()
    calls = []

    def sleep(seconds):
        calls.append(seconds)
        if len(calls) == 1:
            q.compute = lambda: (_ for _ in ()).throw(RuntimeError("once"))
        elif len(calls) == 2:
            del q.compute
        else:
            raise StopIteration

    try:
        q.refresh_forever(sleep=sleep)
    except StopIteration:
        pass
    check(calls == [qt.QueueThresholds.REFRESH_SECONDS] * 3,
          "спит 6 часов между проходами, и упавший проход не останавливает цикл")
    check(q.latest() is not None and q.latest()["proxies"][0]["port"] == 23001,
          "проход после упавшего считает заново")


def test_face_for_the_callers():
    print("имя для вызывающих:")
    harness([{"id": "p1", "port": 23001, "clientTimeoutSeconds": 100}])
    out = qt.compute_queue_thresholds()
    check(out is qt.QUEUE_THRESHOLDS.latest(), "compute_queue_thresholds считает в общий объект")


for fn in (test_shares_of_the_budget, test_before_and_after_a_failure, test_refresh_keeps_going,
           test_face_for_the_callers):
    fn()

if FAILURES:
    print(f"\nFAILED ({len(FAILURES)}):")
    for f in FAILURES:
        print("  - " + f)
    sys.exit(1)
print("\nqueue thresholds OK")
