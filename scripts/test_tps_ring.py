#!/usr/bin/env python3
"""Value snapshot: the history of the machine's token speed records what a cell does NOW, not the rates it holds (1.3.590).

The owner, 2026-10-18, after the lines and the panel of the machine window learned to say `last` for a speed a cell only holds: "yes, clean the
sum and the graph too". A scout keeps the last request's rates while its cell is idle; the ring the graph is drawn from (`_tps_history`,
caravan/admin/telemetry.py) took them for the cell's own and drew a plateau at the last speed through every idle minute.

Pinned, by value, each with its negative:
  - `TokenRates.count`: a request count is a whole number from 0 and nothing else — the table COUNTS (scripts/cell_speed_cases.py), the very table
    `CellSpeed.count` in the browser is run against, so the two cannot drift apart;
  - `TokenRates.now`: a cell that says it answers no request records zeros (a measurement: it generates nothing, not a gap); a cell that answers
    one, or says nothing (an older scout, text, a boolean), is recorded as it reports — nothing tells idle from held;
  - the ring over time: idle, a request, idle again — zeros, the rates, zeros — with the same-second rule and junk rates as before;
  - the whole way: a cell's entry on the topology carries its history, and the entry's count reaches the recorder.

Run: python3 scripts/test_tps_ring.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import caravan.admin.telemetry as TM  # noqa: E402
import caravan.admin.topology as T  # noqa: E402
from cell_speed_cases import COUNTS  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


class Clock:
    """A clock the test winds: the ring stamps its rows with whole seconds."""

    def __init__(self, now):
        self.now = now

    def time(self):
        return self.now


def ring(key, steps):
    """The rows the ring holds after these (second, prompt, gen, requests) steps, on a clock of the test's own."""
    clock = Clock(0)
    real = TM.time
    TM.time = clock
    TM._tps_history.pop(key, None)
    try:
        rows = []
        for second, prompt, gen, *requests in steps:
            clock.now = second
            rows = TM._record_tps_history(key, prompt, gen, *requests)
        return rows
    finally:
        TM.time = real
        TM._tps_history.pop(key, None)


def test_the_count():
    print("a request count, in Python as in the browser (the table COUNTS):")
    got = [(js, TM.TokenRates.count(py)) for js, py, _count in COUNTS]
    want = [(js, count) for js, _py, count in COUNTS]
    check(all(g == w for g, w in zip(got, want)) and all(type(g[1]) is type(w[1]) for g, w in zip(got, want)),
          f"the same cases as CellSpeed.count: a whole number from 0 is a count (2.0 is 2), nothing else is (got {got})")
    check([c for _js, c in got if c is not None] == [c for _js, _py, c in COUNTS if c is not None],
          "positive: 2, a measured 0, a hundred and 2.0 are counts")
    check(all(c is None for (_js, c), (_j, _p, w) in zip(got, COUNTS) if w is None),
          "negative: a float, a negative, text, a boolean, None, NaN, infinity, a list, a dict are not told — never a 0 and never a 1")


def test_what_a_cell_does_now():
    print("the rates a cell has now:")
    now = TM.TokenRates.now
    check(now(2671.4, 211.3, 0) == (0, 0), "a cell that answers no request generates nothing: zeros, though it holds 2671.4 and 211.3")
    check(now(2671.4, 211.3, 1) == (2671.4, 211.3) and now(2671.4, 211.3, 3) == (2671.4, 211.3),
          "a cell that answers a request is recorded as it reports")
    check(now(2671.4, 211.3, None) == (2671.4, 211.3),
          "negative: a scout that says no count — nothing tells idle from held, so the rates are recorded as they come")
    check([now(5, 6, v) for v in ("0", False, -1, 0.5, float("nan"))] == [(5, 6)] * 5,
          "negative: text, a boolean, a negative, a float and NaN are not a count of 0 — the rates are kept, not zeroed")
    check(now(5, 6, 0.0) == (0, 0), "boundary: 0.0 is 0 (the same whole number as in the browser)")
    check(now(None, None, 0) == (0, 0), "a measured idle with no rate to hold is zeros too: it generates nothing, and that is a measurement")
    check(now(None, None, 1) == (None, None), "negative: a request is running and no rate is known yet — a gap, not a zero")


def test_the_ring_over_time():
    print("the ring over time:")
    rows = ring("t:idle-working-idle", [(1000, 2671.4, 211.3, 0), (1001, 2000.0, 284.2, 1), (1002, 2500.5, 311.1, 0)])
    check(rows == [[1000, 0.0, 0.0], [1001, 2000.0, 284.2], [1002, 0.0, 0.0]],
          f"idle, a request, idle again: zeros, the rates, zeros — no plateau at the held speed (got {rows})")
    rows = ring("t:not-told", [(2000, 2671.4, 211.3), (2001, 2671.4, 211.3, None)])
    check(rows == [[2000, 2671.4, 211.3], [2001, 2671.4, 211.3]],
          f"negative: a cell that says no count keeps the rates it reports, as before (got {rows})")
    rows = ring("t:same-second", [(3000, 100.0, 50.0, 1), (3000, 120.0, 60.0, 0)])
    check(rows == [[3000, 0.0, 0.0]], f"two reports in one second still leave one row, the later one (got {rows})")
    rows = ring("t:junk", [(4000, "x", float("inf"), 1), (4001, "x", float("inf"), 0)])
    check(rows == [[4000, None, None], [4001, 0.0, 0.0]],
          f"junk rates stay a gap while a request runs, and a measured idle is zeros even then (got {rows})")


def test_the_whole_way():
    print("from a cell's entry to its history on the board:")
    saved = {k: getattr(T, k) for k in ("topo", "_record_cpu_history", "_record_gpu_history", "ControllerMachine")}
    clock = Clock(5000)
    real = TM.time
    try:
        from caravan.admin.controller_machine import ControllerMachine
        T.ControllerMachine = lambda: ControllerMachine("m-box")
        T.topo = type("Topo", (), {"power_schedules": staticmethod(lambda: {})})()
        T._record_cpu_history = T._record_gpu_history = lambda *a, **kw: []
        TM.time = clock
        out = {}
        for second, requests in ((5000, 0), (5001, 1), (5002, 0), (5003, "absent")):
            clock.now = second
            cell = {"isRemote": True, "clientId": "m", "port": 22028, "phase": "running", "promptTps": 2671.4, "genTps": 211.3}
            if requests != "absent":
                cell["requestsProcessing"] = requests
            nodes = T.topology_nodes({}, {"id": "controller", "name": "Ctl", "llamaServers": [cell]},
                                     [{"id": "m", "name": "M", "ip": "10.0.0.9", "state": "online", "ageSeconds": 0, "gpus": []}])
            out[second] = nodes[0]["servers"][0]["tpsHistory"][-1]
    finally:
        TM.time = real
        TM._tps_history.pop("m:22028", None)
        for k, v in saved.items():
            setattr(T, k, v)
    check(out == {5000: [5000, 0.0, 0.0], 5001: [5001, 2671.4, 211.3], 5002: [5002, 0.0, 0.0], 5003: [5003, 2671.4, 211.3]},
          f"the entry's request count reaches the ring: idle is zeros, a request is the rates, idle is zeros again, and no count keeps the rates (got {out})")


for fn in (test_the_count, test_what_a_cell_does_now, test_the_ring_over_time, test_the_whole_way):
    try:
        fn()
    except Exception as exc:  # noqa: BLE001 — a failing probe is a failed pin, said out loud
        check(False, f"{fn.__name__} raised {exc!r}")

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail:
        print("  - " + m.splitlines()[0])
    sys.exit(1)
print("tps ring snapshot holds")
