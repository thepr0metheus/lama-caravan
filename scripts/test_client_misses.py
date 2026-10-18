#!/usr/bin/env python3
"""Snapshot of caravan/admin/client_misses.py: a client's errors of the last 30 days.

The owner, 2026-10-12: "keep for 30 days the endpoints a client called and got an error — to see,
say, that it asked /api/show". Pinned by value against journal files in a scratch folder: which
rows are a client's errors (an entry's refusal, a request finished with 4xx/5xx, under a port) and
which are not; one line per method, path and status, counted, newest first, the rest counted; the
days of the window and none older; today's file read on only for the whole lines added since; no
folder — not known, not "no errors"; and the board handed the lines on each client of the entry.

Run: python3 scripts/test_client_misses.py
"""
import json
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from caravan.admin.client_misses import ClientMisses  # noqa: E402
from caravan.admin.topology import annotate_consumer_misses  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


NOW = datetime(2026, 10, 12, 12, 0, 0).timestamp()
TODAY = datetime.fromtimestamp(NOW).date()


def day(back):
    return (TODAY - timedelta(days=back)).isoformat()


def blocked(when, port, path, status, method="POST", reason="entry:invalid-url"):
    item = {"port": port, "path": path, "status": status, "reason": reason}
    if method is not None:
        item["method"] = method
    return {"time": int(when), "event": "blocked", "route": "Hermes", "item": item}


def finished(when, port, path, status, kind=""):
    return {"time": int(when), "event": "finished", "route": "Hermes", "status": status, "errorKind": kind,
            "item": {"port": port, "method": "POST", "path": path}}


def write(folder, back, rows, tail=""):
    text = "".join(json.dumps(row) + "\n" for row in rows) + tail
    (folder / f"{day(back)}.jsonl").write_text(text, encoding="utf-8")


def test_rows():
    print("which rows of the journal are a client's errors:")
    got = [ClientMisses.miss_of(row) for row in (
        blocked(NOW, 23001, "/api/show", 404),
        blocked(NOW, 23001, "/api/show", 404, method=None),
        finished(NOW, 23001, "/v1/chat/completions", 502, kind="upstream_error"),
        finished(NOW, 23001, "/v1/chat/completions", 200),
        blocked(NOW, "entry", "/v1/models", 401),
        {"time": NOW, "event": "received", "item": {"port": 23001, "path": "/x", "status": 500}},
        {"event": "finished", "status": "bad", "item": {"port": 23001}},
        {"time": NOW, "event": "blocked", "item": {"port": 23001, "path": "/v1/audio/transcriptions", "status": 400, "client": "routing-probe"}},
        {"time": NOW, "event": "blocked", "item": {"port": 23001, "path": "/v1/audio/transcriptions", "status": 400, "client": "kanban-probe"}},
        None)]
    check(got[:3] == [(23001, "POST", "/api/show", 404, "entry:invalid-url", int(NOW)),
                      (23001, "", "/api/show", 404, "entry:invalid-url", int(NOW)),
                      (23001, "POST", "/v1/chat/completions", 502, "upstream_error", int(NOW))],
          f"a refusal of the entry and a request finished with an error, under the client's port; a record from "
          f"before 1.3.495 has no method — said as none (got {got[:3]})")
    check(got[3:] == [None] * 7,
          "negative: a request finished 200, a refusal of no client (the entry's own, an unknown key), a mid-flight "
          "event, a status that is no number, Routing's test of the client under the name it has now and under the one "
          "the journal's rows from before 1.3.582 carry (kept 30 days), no row — none of them an error of a client")


def test_window():
    print("a client's lines over the window:")
    folder = Path(tempfile.mkdtemp(prefix="caravan-misses-"))
    write(folder, 0, [blocked(NOW - 60, 23001, "/api/show", 404), blocked(NOW - 30, 23001, "/api/show", 404),
                      finished(NOW - 10, 23001, "/v1/chat/completions", 429, kind="limit"),
                      finished(NOW - 5, 23002, "/v1/chat/completions", 200)])
    write(folder, 1, [blocked(NOW - 86400, 23001, "/api/show", 404, method=None),
                      blocked(NOW - 86400 - 7, 23001, "/api/show", 404)])
    write(folder, 29, [blocked(NOW - 29 * 86400, 23001, "/v1/audio/transcriptions", 400, reason="entry:not-json")])
    write(folder, 30, [blocked(NOW - 30 * 86400, 23001, "/too/old", 404)])
    reader = ClientMisses(log_dir=folder, clock=lambda: NOW)
    got = reader.of([23001, 23002])
    lines = [(m["method"], m["path"], m["status"], m["count"], m["last"]) for m in got[23001]["items"]]
    check(lines == [("POST", "/v1/chat/completions", 429, 1, int(NOW - 10)), ("POST", "/api/show", 404, 3, int(NOW - 30)),
                    ("", "/api/show", 404, 1, int(NOW - 86400)),
                    ("POST", "/v1/audio/transcriptions", 400, 1, int(NOW - 29 * 86400))],
          f"one line per method, path and status, counted over the days, newest first; the 30th day back is in, "
          f"the 31st is not (got {lines})")
    check(got[23001]["items"][1]["reason"] == "entry:invalid-url" and got[23001]["more"] == 0,
          "each line says why, as the journal named it")
    check(got[23002] == {"items": [], "more": 0}, "negative: a client with only answers that went well has no lines")

    print("today's file, read on:")
    with (folder / f"{day(0)}.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(blocked(NOW - 1, 23001, "/api/show", 404)) + "\n")
        fh.write('{"time": 1, "event": "blocked", "item": {"port": 23001, "path": "/half')
    got = reader.of([23001])
    show = next(m for m in got[23001]["items"] if m["method"] == "POST" and m["path"] == "/api/show")
    check(show["count"] == 4 and show["last"] == int(NOW - 1),
          f"a line added since is counted once, the lines read before are not counted again (got {show})")
    check(not any(m["path"].startswith("/half") for m in got[23001]["items"]),
          "negative: a line still being written is not read — it is read when it is whole")
    with (folder / f"{day(0)}.jsonl").open("a", encoding="utf-8") as fh:
        fh.write('", "status": 404}, "time": ' + str(int(NOW)) + "}\n")
    got = reader.of([23001])
    check(any(m["path"] == "/half" for m in got[23001]["items"]), "the line made whole is read then")

    print("many lines:")
    write(folder, 2, [blocked(NOW - 2 * 86400 - i, 23001, f"/p{i}", 404) for i in range(10)])
    got = ClientMisses(log_dir=folder, clock=lambda: NOW).of([23001])
    check(len(got[23001]["items"]) == ClientMisses.SHOWN and got[23001]["more"] == 15 - ClientMisses.SHOWN,
          f"a card shows the newest {ClientMisses.SHOWN}; the rest are counted (got {len(got[23001]['items'])} + {got[23001]['more']})")
    check(ClientMisses(log_dir=folder / "nowhere", clock=lambda: NOW).of([23001]) is None,
          "negative: no journal folder — not known, not \"no errors\"")


def test_board():
    print("what the board is handed:")

    class Reader:
        def __init__(self, answer):
            self.answer, self.asked = answer, []

        def of(self, ports):
            self.asked.append(sorted(ports))
            return self.answer

    proxies = [{"port": 23001, "kind": "consumer"}, {"port": 23002, "kind": "consumer"}, {"port": 23050}, "junk"]
    reader = Reader({23001: {"items": [{"path": "/api/show"}], "more": 0}})
    annotate_consumer_misses(proxies, reader)
    check(reader.asked == [[23001, 23002]] and proxies[0]["misses"] == {"items": [{"path": "/api/show"}], "more": 0}
          and proxies[1]["misses"] == {"items": [], "more": 0} and "misses" not in proxies[2],
          "each client of the entry gets its lines — none when it had no error; negative: an agent of the old kind is not asked about")
    proxies = [{"port": 23001, "kind": "consumer"}]
    annotate_consumer_misses(proxies, Reader(None))
    check("misses" not in proxies[0], "negative: a journal that cannot be read leaves the key out — not known, not none")


def main():
    for fn in (test_rows, test_window, test_board):
        fn()
    print()
    if _fail:
        print(f"FAILED ({len(_fail)}):")
        for m in _fail:
            print("  - " + m)
        return 1
    print("client misses OK: ошибки клиента за 30 дней — из журнала прокси, по порту клиента")
    return 0


if __name__ == "__main__":
    sys.exit(main())
