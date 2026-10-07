#!/usr/bin/env python3
"""Snapshot of ProxyLatencyDigest (caravan/admin/proxy_latency.py) by value:
what the route window says about a port's own time, read from the journal.

The journal here is written by hand, day files and all, and the clock is a
parameter: every median is computed in the head and checked to the decimal.

Run: python3 scripts/test_proxy_latency.py
"""
import json
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from caravan.admin.proxy_latency import ProxyLatencyDigest  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


NOW = time.mktime((2026, 10, 7, 12, 0, 0, 0, 0, -1))
TODAY = datetime.fromtimestamp(NOW).strftime("%Y-%m-%d")
YESTERDAY = datetime.fromtimestamp(NOW - 86400).strftime("%Y-%m-%d")


def finished(t, port, prep=None, connect=None, reused=None, cpu=None, headers=None, first=None, latency=True):
    item = {"id": f"r{t}", "port": port, "status": 200}
    if latency:
        item["latency"] = {"prepMs": prep, "connectMs": connect, "connReused": reused,
                           "headersMs": headers, "firstChunkMs": first, "cpuMs": cpu}
    return json.dumps({"time": int(t), "event": "finished", "item": item,
                       "active": [], "queue": []}, separators=(",", ":")) + "\n"


def other(t, port, event="received"):
    return json.dumps({"time": int(t), "event": event,
                       "item": {"port": port, "latency": {"prepMs": 999.0}}}, separators=(",", ":")) + "\n"


def setup():
    folder = Path(tempfile.mkdtemp(prefix="caravan-latency-"))
    (folder / f"{YESTERDAY}.jsonl").write_text(
        finished(NOW - 20 * 3600, 23001, prep=9.0, connect=50.0, reused=False, cpu=30.0, headers=900.0, first=950.0),
        encoding="utf-8")
    (folder / f"{TODAY}.jsonl").write_text(
        finished(NOW - 7200, 23001, prep=1.0, connect=0.0, reused=True, cpu=10.0, headers=500.0, first=520.0)
        + other(NOW - 7000, 23001)
        + finished(NOW - 1800, 23001, prep=2.0, connect=48.0, reused=False, cpu=12.0, headers=700.0, first=710.0)
        + finished(NOW - 600, 23001, prep=3.0, connect=0.0, reused=True, cpu=14.0, headers=None, first=None)
        + finished(NOW - 500, 23001, latency=False)
        + finished(NOW - 400, 23002, prep=100.0, connect=0.4, reused=None, cpu=50.0)
        + other(NOW - 300, 23001, event="upstream_started"),
        encoding="utf-8")
    (folder / "notes.jsonl").write_text(finished(NOW, 23001, prep=500.0), encoding="utf-8")
    return folder, ProxyLatencyDigest(log_dir=folder, clock=lambda: NOW)


def test_everything_kept():
    print("весь журнал, порт 23001:")
    _, digest = setup()
    got = digest.summary(23001, "all")
    check(got["requests"] == 4, f"4 измеренных запроса: без latency и чужие события не в счёт (получено {got['requests']})")
    check(got["range"] == "all", f"диапазон назван (получено {got['range']!r})")
    check(got["prepMs"] == {"n": 4, "p50": 2.0, "p90": 9.0},
          f"своя работа: медиана 2, p90 9 из [1, 2, 3, 9] (получено {got['prepMs']})")
    check(got["connectMs"] == {"n": 4, "p50": 0.0, "p90": 50.0}, f"подключение (получено {got['connectMs']})")
    check(got["cpuMs"] == {"n": 4, "p50": 12.0, "p90": 30.0}, f"процессор (получено {got['cpuMs']})")
    check(got["headersMs"] == {"n": 3, "p50": 700.0, "p90": 900.0},
          f"заголовки — только где измерены: 3 из 4 (получено {got['headersMs']})")
    check(got["connReused"] == {"n": 4, "reused": 2}, f"из пула 2 из 4 (получено {got['connReused']})")


def test_ranges():
    print("диапазоны:")
    _, digest = setup()
    hour = digest.summary(23001, "1h")
    check(hour["requests"] == 2 and hour["range"] == "1h", f"за час — 2 запроса (получено {hour['requests']})")
    check(hour["prepMs"] == {"n": 2, "p50": 2.0, "p90": 3.0}, f"медиана из [2, 3] (получено {hour['prepMs']})")
    check(digest.summary(23001, "12h")["requests"] == 3, "за 12 часов — 3")
    check(digest.summary(23001, "24h")["requests"] == 4, "за сутки — 4, вчерашний файл прочитан")
    check(digest.summary(23001, "week")["range"] == "all", "незнакомый диапазон — весь журнал")


def test_cell_port_and_absence():
    print("ячейка и порт без измерений:")
    _, digest = setup()
    cell = digest.summary(23002, "all")
    check(cell["connReused"] is None, f"у ячейки пула нет — доля не считается (получено {cell['connReused']})")
    check(cell["headersMs"] is None, f"не измерено — None, а не 0 (получено {cell['headersMs']})")
    empty = digest.summary(23009, "all")
    check(empty["requests"] == 0 and empty["prepMs"] is None and empty["connReused"] is None,
          f"порт без измерений — ноль запросов и None везде (получено {empty})")


def test_growing_day():
    print("сегодняшний файл растёт:")
    folder, digest = setup()
    check(digest.summary(23001, "1h")["requests"] == 2, "до дописи — 2")
    path = folder / f"{TODAY}.jsonl"
    line = finished(NOW - 60, 23001, prep=4.0, connect=0.0, reused=True, cpu=15.0)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line[:40])
    check(digest.summary(23001, "1h")["requests"] == 2, "недописанная строка не читается")
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line[40:])
    got = digest.summary(23001, "1h")
    check(got["requests"] == 3, f"дописанная — прочитана один раз (получено {got['requests']})")
    check(got["prepMs"]["p90"] == 4.0, f"и попала в счёт (получено {got['prepMs']})")


def test_day_rewritten_or_removed():
    print("файл переписан или удалён:")
    folder, digest = setup()
    digest.summary(23001, "all")
    (folder / f"{TODAY}.jsonl").write_text(
        finished(NOW - 60, 23001, prep=7.0, connect=0.0, reused=True, cpu=1.0), encoding="utf-8")
    got = digest.summary(23001, "1h")
    check(got["requests"] == 1 and got["prepMs"]["p50"] == 7.0,
          f"файл стал короче — прочитан заново (получено {got['requests']}, {got['prepMs']})")
    (folder / f"{YESTERDAY}.jsonl").unlink()
    check(digest.summary(23001, "all")["requests"] == 1, "удалённый день не в счёте")
    check(digest.cached_days() == [TODAY], f"и не в памяти (получено {digest.cached_days()})")


for fn in (test_everything_kept, test_ranges, test_cell_port_and_absence, test_growing_day,
           test_day_rewritten_or_removed):
    fn()

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail:
        print("  - " + m)
    sys.exit(1)
print("all proxy-latency snapshots hold")
