#!/usr/bin/env python3
"""Value snapshot: what the controller reads off the proxy's journal for the board.

One reading of each day file (caravan/admin/proxy_stats.py, `_day_seen`) serves
two answers: when each port last served a request — the board's proof that a
route is used — and when a client last asked for /v1/embeddings: the kanban's
unset embeddings slot is red only then (2026-10-08, a cloud-only board stood
red for a call nobody made).

Also here: an image build has no branch — the controller says so (`baked`)
instead of a branch named "docker" (caravan/admin/status.py).

Run: python3 scripts/test_proxy_journal.py
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="caravan-journal-"))
os.environ["CARAVAN_DATA_DIR"] = str(TMP)
os.environ["AGENT_PROXY_LOG_DIR"] = str(TMP / "logs")
sys.path.insert(0, str(ROOT))

from caravan.admin import proxy_stats  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


LOGS = TMP / "logs"


def line(event, when, port=23001, status=None, path="/v1/chat/completions"):
    row = {"event": event, "time": when, "item": {"port": port, "path": path}}
    if status is not None:
        row["item"]["status"] = status
        row["status"] = status
    return json.dumps(row, separators=(",", ":")) + "\n"


def test_one_reading_two_answers():
    print("один проход по журналу — два ответа:")
    LOGS.mkdir(parents=True, exist_ok=True)
    now = int(time.time())
    today = LOGS / f"{time.strftime('%Y-%m-%d')}.jsonl"
    today.write_text(line("finished", now - 600, status=200)
                     + line("finished", now - 300, status=400, path="/v1/embeddings")
                     + line("received", now - 60, path="/v1/embeddings"), encoding="utf-8")
    proxy_stats._PORTS_SEEN_CACHE.clear()
    check(proxy_stats.proxy_ports_last_seen() == {23001: now - 600},
          "порт подтверждён только успешным запросом: отказ 400 на embeddings его не подтверждает")
    check(proxy_stats.embeddings_last_called() == now - 300,
          "вызов embeddings засчитан и с отказом — именно его слот на канбане и предупреждает")
    check(proxy_stats.embeddings_last_called() == now - 300,
          "negative: незавершённый запрос (received) — ещё не вызов: время не сдвинулось")
    with today.open("a", encoding="utf-8") as fh:
        fh.write(line("finished", now - 30, port=23003, status=200, path="/v1/embeddings/"))
    check(proxy_stats.embeddings_last_called() == now - 30 and proxy_stats.proxy_ports_last_seen() == {23001: now - 600, 23003: now - 30},
          "дописанный журнал читается с места, где остановился: новый вызов и новый порт видны")


def test_old_and_missing():
    print("старое и отсутствующее:")
    now = int(time.time())
    for p in LOGS.glob("*.jsonl"):
        p.unlink()
    old = LOGS / f"{time.strftime('%Y-%m-%d', time.localtime(now - 9 * 86400))}.jsonl"
    old.write_text(line("finished", now - 9 * 86400, status=400, path="/v1/embeddings"), encoding="utf-8")
    proxy_stats._PORTS_SEEN_CACHE.clear()
    check(proxy_stats.embeddings_last_called() == 0, "negative: вызов старше 7 дней — «не звали», слот не красный")
    old.unlink()
    LOGS.rmdir()
    proxy_stats._PORTS_SEEN_CACHE.clear()
    check(proxy_stats.embeddings_last_called() == 0 and proxy_stats.proxy_ports_last_seen() == {},
          "negative: журнала нет — ни вызовов, ни портов, без исключения")


def test_an_image_build_has_no_branch():
    print("сборка образа: ветки нет, есть коммит:")
    from caravan.admin import status

    class Baked:
        def __init__(self, root, short=False):
            self.baked, self.commit, self.from_git, self.error = True, "018d9695", False, ""
    keep = status.CheckoutCommit
    status.CheckoutCommit = Baked
    try:
        got = status.project_git_info()
    finally:
        status.CheckoutCommit = keep
    check(got == {"branch": "", "baked": True, "head": "018d9695", "dirtyCount": 0, "ok": True, "error": ""},
          f"нет git-копии — ветка пуста, `baked` так и говорит, коммит назван (раньше ветка «docker»: чип писал «git: docker») (got {got})")
    real = status.project_git_info()
    check("baked" not in real, "negative: копия git — как раньше, без `baked`")


def test_events_by_name():
    print("журнал по названиям событий (2026-10-11: вкладка «Запросы» не видела отказов):")
    LOGS.mkdir(parents=True, exist_ok=True)
    now = int(time.time())
    day = "2026-10-01"
    (LOGS / f"{day}.jsonl").write_text(line("received", now - 9) + line("finished", now - 8, status=200)
                                       + line("blocked", now - 7, status=401) + line("upstream_started", now - 6),
                                       encoding="utf-8")
    events = lambda wanted: [r["event"] for r in reversed(proxy_stats.load_agent_proxy_logs(day, 50, wanted)["rows"])]
    check(events("finished,blocked") == ["finished", "blocked"],
          "несколько событий через запятую: законченные и отказанные вместе, по порядку")
    check(events("blocked") == ["blocked"] and events(" blocked , ") == ["blocked"],
          "одно событие — как раньше; пробелы и пустые части не мешают")
    check(events("") == ["received", "finished", "blocked", "upstream_started"],
          "negative: без названия — все события дня")


for fn in (test_one_reading_two_answers, test_old_and_missing, test_an_image_build_has_no_branch, test_events_by_name):
    fn()

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail:
        print("  - " + m)
    sys.exit(1)
print("proxy journal OK: порты, embeddings и коммит образа — значениями")
