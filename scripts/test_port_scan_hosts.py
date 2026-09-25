#!/usr/bin/env python3
"""What each scout says about the ports it has, as the port scan reads it.

caravan/admin/port_exclusions.py, _client_scans: the scan asks every scout
what listens on its machine and offers to hold the numbers someone else took.
A host that could not be scanned must not read as a clean one. It did when
the scout answered but could not tell — its ss or lsof failed, and it said
{"ok": false}: the scan read that as "nothing listens here" (until
2026-09-25, when the scout started saying it for a failed ss too).

Pinned by value; the scouts' answers are stand-ins, nothing reaches a network.

Run: python3 scripts/test_port_scan_hosts.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import caravan.admin.fleet_clients as fleet_clients  # noqa: E402
import caravan.admin.port_exclusions as P  # noqa: E402
import caravan.common.fetch as fetch  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def same(actual, expected, msg):
    check(actual == expected, msg if actual == expected else f"{msg}\n        got:  {actual!r}\n        want: {expected!r}")


BASE = P.SERVER_CELL_BASE_PORT


def scans(answers, ours=frozenset()):
    """_client_scans over one scout per answer: an answer is the scout's JSON,
    or an exception its fetch raises."""
    hosts = {f"h{i}": {"agentUrl": f"http://10.0.0.{i}:8092"} for i in range(len(answers))}
    by_url = {f"http://10.0.0.{i}:8092/api/host/listeners": a for i, a in enumerate(answers)}

    def fake_fetch(url, timeout=None, headers=None):
        answer = by_url[url]
        if isinstance(answer, BaseException):
            raise answer
        return answer

    saved = (P.topology_store, fetch.fetch_json, fleet_clients._scout_headers)
    P.topology_store = lambda: {"hosts": hosts}
    fetch.fetch_json = fake_fetch
    fleet_clients._scout_headers = lambda: {}
    try:
        return P._client_scans(set(ours))
    finally:
        P.topology_store, fetch.fetch_json, fleet_clients._scout_headers = saved


def test_scans():
    print("что скаут сказал о своих портах:")
    listed = {"ok": True, "ports": [{"port": BASE + 5, "proc": "node", "pid": 7, "addrs": ["0.0.0.0"]},
                                    {"port": BASE + 6, "proc": "", "pid": 0},
                                    {"port": BASE - 1, "proc": "x", "pid": 1}, "junk"]}
    got = scans([listed], ours={BASE + 6})
    same(got, [{"hostId": "h0", "ok": True, "ports": [{"port": BASE + 5, "proc": "node", "pid": 7,
                                                      "addrs": ["0.0.0.0"]}]}],
         "ответил списком — чужие порты диапазона ячеек; свои, вне диапазона и мусор — нет")
    got = scans([{"ok": False, "error": "ss failed; lsof: lsof", "ports": []}])
    same(got, [{"hostId": "h0", "ok": False, "error": "ss failed; lsof: lsof", "ports": []}],
         "defect-history: скаут ответил, но сказать не смог (ok false) — хост не просканирован, а не чист")
    same(scans([{"ok": False}])[0]["error"], "the scout could not list its listeners",
         "negative: без текста ошибки — всё равно сказано, что не смог")
    same(scans([["not", "a", "dict"]])[0], {"hostId": "h0", "ok": False,
                                           "error": "the scout's answer is not a listener list", "ports": []},
         "negative: ответ не того вида — не «ничего не слушает»")
    same(scans([OSError("timed out")])[0], {"hostId": "h0", "ok": False, "error": "timed out", "ports": []},
         "скаут не ответил — ok false с причиной, как было")
    same(scans([{"ports": []}])[0], {"hostId": "h0", "ok": True, "ports": []},
         "boundary: старый скаут без поля ok и без портов — чистый хост, как он и сказал")


try:
    test_scans()
except Exception as exc:  # noqa: BLE001 — a crash is a red pin
    check(False, f"test_scans упал: {exc!r}")

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for f in _fail:
        print("  - " + f.splitlines()[0])
    sys.exit(1)
print("port scan hosts OK")
