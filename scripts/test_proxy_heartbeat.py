#!/usr/bin/env python3
"""Value snapshot: the proxy rewrites its state file on a beat, and the admin reads it by one rule.

2026-10-08, the caravan on the NAS: the pool card said "Not measured yet" 30 s
after every request. The admin takes a state file older than 30 s for a proxy
that is gone; the proxy wrote the file on requests and after probing a cell's
slots — and a cloud-only controller has no cells to probe.

Pinned by value, positive and negative for every claim:
- the rule (caravan/common/proxy_heartbeat.py): when a file still speaks for the proxy;
- a beat (caravan/proxy/queue_admission.heartbeat_pass): it writes the file with
  nothing to probe, probes each llama upstream once, and a broken config or a
  failed write does not stop it;
- the file says where the ports listen (`listenHost`: the board's PortDoor);
- the pool card's runtime (PoolDesk.runtime) reads the file by the same rule.

Run: python3 scripts/test_proxy_heartbeat.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="caravan-heartbeat-"))
os.environ["CARAVAN_DATA_DIR"] = str(TMP)
os.environ["AGENT_PROXY_STATE_FILE"] = str(TMP / "agent-proxy-state.json")
os.environ["AGENT_PROXY_LOG_DIR"] = str(TMP / "logs")
sys.path.insert(0, str(ROOT))

from caravan.common.proxy_heartbeat import ProxyHeartbeat  # noqa: E402
from caravan.proxy.queue_admission import heartbeat_pass  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


NOW = 1_800_000_000


def test_the_rule():
    print("правило свежести:")
    check(ProxyHeartbeat.fresh(NOW, NOW) and ProxyHeartbeat.fresh(NOW - ProxyHeartbeat.STALE_SECONDS, NOW),
          "файл только что записан и ровно 30 с назад — ещё говорит за прокси")
    check(not ProxyHeartbeat.fresh(NOW - ProxyHeartbeat.STALE_SECONDS - 1, NOW),
          "negative: 31 с — три удара пропущены, прокси нет")
    check(not ProxyHeartbeat.fresh(None, NOW) and not ProxyHeartbeat.fresh(0, NOW) and not ProxyHeartbeat.fresh("x", NOW),
          "negative: файл без времени, с нулём или мусором — ничего не говорит")
    check(ProxyHeartbeat.BEAT_SECONDS * 3 == ProxyHeartbeat.STALE_SECONDS,
          "устаревший — это три пропущенных удара")


def test_a_beat():
    print("удар сердца прокси:")
    written, probed = [], []
    write = lambda: written.append(1)  # noqa: E731
    probe = lambda out, timeout: probed.append((out["upstreamHost"], out["upstreamPort"], timeout))  # noqa: E731
    cloud_only = {"routers": [{"outputs": [{"id": "cb:sol", "upstreamType": "cloud"},
                                           {"id": "eng:x", "upstreamType": "engine", "upstreamHost": "h", "upstreamPort": 11434}]}]}
    got = heartbeat_pass(cloud_only, probe, write)
    check(got == set() and probed == [] and written == [1],
          f"только облако: щупать нечего, а файл записан (раньше — нет) (got probed={probed}, written={written})")
    written.clear()
    cells = {"routers": [{"outputs": [{"id": "srv:1", "upstreamHost": "box", "upstreamPort": 22001},
                                      {"id": "srv:1b", "upstreamHost": "box", "upstreamPort": 22001},
                                      {"id": "srv:2", "upstreamType": "llama", "upstreamHost": "box", "upstreamPort": 22003},
                                      {"id": "srv:x", "upstreamHost": "", "upstreamPort": 22005}]},
                         {"outputs": [{"id": "srv:2", "upstreamHost": "box", "upstreamPort": 22003}]}]}
    probed.clear()
    got = heartbeat_pass(cells, probe, write)
    check(probed == [("box", 22001, 3.0), ("box", 22003, 3.0)] and got == {"box:22001", "box:22003"} and written == [1],
          f"ячейки: каждый апстрим щупается один раз, выход без адреса — нет; файл записан один раз; ответ — имена "
          f"очередей (got {probed} {got})")
    asked = []
    models = {"routers": [{"outputs": [
        {"id": "mm:a", "upstreamType": "machine", "upstreamHost": "box", "upstreamPort": 8092, "upstreamModel": "gemma"},
        {"id": "mm:b", "upstreamType": "machine", "upstreamHost": "box", "upstreamPort": 8092, "upstreamModel": "ear"},
        {"id": "mm:a2", "upstreamType": "machine", "upstreamHost": "box", "upstreamPort": 8092, "upstreamModel": "gemma"}]}]}
    got = heartbeat_pass(models, lambda out, timeout: asked.append(dict(out)), write)
    check(got == {"box:8092/gemma", "box:8092/ear"} and [a.get("upstreamModel") for a in asked] == ["gemma", "ear"]
          and all(a.get("upstreamType") == "machine" for a in asked),
          "модели входа машины (1.3.506): у каждой своя очередь — щупается каждая модель по имени, одна и та же — "
          "один раз; negative: адрес и порт входа один на все — по нему одному было бы одно щупанье")

    class Broken(dict):
        def get(self, *_):
            raise RuntimeError("config is broken")
    written.clear()
    check(heartbeat_pass(Broken(), probe, write) == set() and written == [1],
          "negative: сломанный конфиг не останавливает удар — файл всё равно записан")

    def failing():
        raise OSError("disk full")
    try:
        heartbeat_pass(cloud_only, probe, failing)
        check(True, "negative: запись не удалась — удар не падает, поток живёт")
    except Exception as err:  # noqa: BLE001
        check(False, f"negative: запись не удалась — удар не падает, поток живёт (got {err!r})")


def test_the_file_says_where_the_ports_listen():
    print("файл состояния говорит, где слушают порты:")
    from caravan.proxy import state as proxy_state
    from caravan.proxy.paths import HOST, STATE_FILE
    proxy_state.write_state()
    payload = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    check(payload.get("listenHost") == HOST and payload.get("time"),
          f"listenHost — адрес, на котором прокси открывает порты, со временем записи (got {payload.get('listenHost')!r})")


def test_the_pool_card_reads_by_the_rule():
    print("карточка пула читает файл тем же правилом:")
    from caravan.admin.pools import PoolDesk
    state = TMP / "agent-proxy-state.json"
    pools = {"pools": {"sol": {"selectedStepId": "sub", "decidedAt": NOW - 120}}, "events": []}

    def runtime(written_at):
        state.write_text(json.dumps({"time": written_at, "pools": pools}), encoding="utf-8")
        return PoolDesk(load=lambda: {"accounts": [], "pools": []}, save=lambda d: None,
                        state_file=state, clock=lambda: NOW).runtime()
    fresh = runtime(NOW - 29)
    check(fresh["available"] and fresh["pools"]["sol"]["selectedStepId"] == "sub",
          "файлу 29 с: выбор пула виден — карточка пишет, кто служит, а не «Not measured yet»")
    silent = {"available": False, "pools": {}, "events": []}
    check(runtime(NOW - 31) == silent,
          "negative: файлу 31 с — прокси молчит, выбора нет, а не старый выбор")
    state.write_text("not json", encoding="utf-8")
    check(PoolDesk(state_file=state, clock=lambda: NOW).runtime() == silent,
          "negative: битый файл — выбора нет")


for fn in (test_the_rule, test_a_beat, test_the_file_says_where_the_ports_listen, test_the_pool_card_reads_by_the_rule):
    fn()

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail:
        print("  - " + m)
    sys.exit(1)
print("proxy heartbeat OK: правило, удар и чтение карточкой пула — значениями")
