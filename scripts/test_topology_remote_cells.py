#!/usr/bin/env python3
"""Снимок topology_server: ячейки машин со скаутом в ответе доски.

Цикл по ячейкам, о которых отчитываются скауты, ни разу не гонялся тестом. Так
в нём два месяца прожила переменная, которую задавали только command-ячейки, а
читали все: работающая llama-ячейка на машине со скаутом роняла /api/topology
целиком (500 — пустая доска у всех), если перед ней в отчёте не было
работающей command-ячейки, а если была — носила её метаданные: версию сервера
и язык перевода соседки. Нашлось при первом запуске ячейки после переустановки
скаута на машине-доноре.

Пинится значениями: ответ собирается, у llama-ячейки нет чужих метаданных при
любом порядке отчёта, у command-ячейки — свои. Всё, что дошло бы до процесса,
диска или сети, подменено.

Запуск: python3 scripts/test_topology_remote_cells.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import caravan.admin.topology as T  # noqa: E402
from caravan.admin.model_locator import Locations  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


HOST = {"id": "box-a", "name": "Box A", "ip": "10.0.0.5", "gpus": [{"name": "G"}]}
# ctxMax and ctxTrained are reported, so nothing reads a slot store or a GGUF
# file for them.
LLAMA = {"port": 22021, "running": True, "phase": "running", "modelPath": "/m/model-a.gguf",
         "ctxMax": 8192, "ctxTrained": 131072}
WHISPER = {"port": 22024, "running": True, "phase": "running", "ctxMax": 1, "ctxTrained": 1}
SLOTS = {
    "box-a:22021": {"id": "box-a:22021", "hostId": "box-a", "port": 22021, "model": "/m/model-a.gguf",
                    "config": {"MODEL_FILE": "/m/model-a.gguf"}},
    "box-a:22024": {"id": "box-a:22024", "hostId": "box-a", "port": 22024,
                    "config": {"RUNNER": "whisper", "HEALTH_PATH": "/health"}},
    "box-a:22023": {"id": "box-a:22023", "hostId": "box-a", "port": 22023,
                    "config": {"RUNNER": "whisper", "HEALTH_PATH": "/health"}},
    "box-a:22012": {"id": "box-a:22012", "hostId": "box-a", "port": 22012,
                    "config": {"RUNNER": "vllm", "VLLM_MODEL": "org/model", "HEALTH_PATH": "/v1/models"}},
}
WHISPER_HEALTH = {"status": "ok", "meta": {"source": "d1g3st"}, "targetLang": "en"}


def served(nodes, parked=(), health="ok", **host_fields):
    """topology_server over one machine whose scout reports `nodes`. Only
    their slots are stored, and those of `parked` ports: a stored cell nobody
    reports is a parked card, which another loop draws. `health` is what a
    llama cell's /health says ("loading" while its model loads)."""
    host = dict(HOST, llamaNodes=[dict(n) for n in nodes], **host_fields)
    reported = {n["port"] for n in nodes} | set(parked)
    patch = {
        "service_status": lambda: {"ActiveState": "inactive"},
        "runtime_api": lambda _config: {},
        "runtime_phase": lambda *_a: {},
        "gpu_state": lambda: {"gpus": []},
        "runtime_metrics_sample": lambda: {"ok": False},
        "topology_store": lambda: {"hosts": {"box-a": host},
                                   "serverSlots": {k: dict(v) for k, v in SLOTS.items()
                                                   if v["port"] in reported}},
        "command_cell_health": lambda _ip, port, _path: dict(WHISPER_HEALTH) if port == 22024 else None,
        "remote_llama_health": lambda *_a: health,
        "remote_llama_modalities": lambda *_a: None,
        "probe_remote_port": lambda *_a: True,
        "current_locations": lambda: Locations([]),
        "_saved_command": lambda *_a: "",
    }
    saved = {k: getattr(T, k) for k in patch}
    try:
        for k, v in patch.items():
            setattr(T, k, v)
        return T.topology_server({"PORT": "8080"})
    finally:
        for k, v in saved.items():
            setattr(T, k, v)


def cells(nodes):
    """{port: (phase, cellMeta)} of the machine's cells — or the error."""
    try:
        answer = served(nodes)
    except Exception as exc:  # noqa: BLE001 — the defect IS an exception
        return f"{type(exc).__name__}: {exc}"
    return {s["port"]: (s["phase"], s["cellMeta"]) for s in answer["llamaServers"] if s.get("isRemote")}


def meta_of(cell_meta):
    """The cell's own words, without our verdict on its version (that one
    reads the shipped cell sources and is pinned elsewhere)."""
    return {k: v for k, v in cell_meta.items() if k != "sourceState"}


def test_llama_cell_alone():
    print("llama-ячейка на машине со скаутом, одна:")
    got = cells([LLAMA])
    check(got == {22021: ("running", {})},
          f"defect-history: ответ собирается, ячейка работает и без чужих метаданных (ответ: {got!r})")


def test_no_neighbour_meta():
    print("соседняя command-ячейка не делится своими словами:")
    for order, nodes in (("whisper, потом llama", [WHISPER, LLAMA]), ("llama, потом whisper", [LLAMA, WHISPER])):
        got = cells(nodes)
        ok = isinstance(got, dict) and set(got) == {22021, 22024}
        check(ok and got[22021] == ("running", {}),
              f"defect-history ({order}): у llama-ячейки нет версии и языка соседки (ответ: {got!r})")
        check(ok and got[22024][0] == "running"
              and meta_of(got[22024][1]) == {"source": "d1g3st", "targetLang": "en"},
              f"negative ({order}): у command-ячейки её собственные версия и язык остаются")


def test_silent_command_cell():
    print("command-ячейка, чей health молчит:")
    got = cells([dict(WHISPER, port=22023), LLAMA])
    check(isinstance(got, dict) and got.get(22021) == ("running", {}) and meta_of(got[22023][1]) == {},
          f"boundary: молчащий health — у обеих пусто, без исключения (ответ: {got!r})")


def test_autostart_on_the_card():
    print("↟ ячейки скаута:")

    def boot(**host_fields):
        answer = served([LLAMA], **host_fields)
        cell = next(s for s in answer["llamaServers"] if s.get("isRemote"))
        return cell["bootEnabled"], cell["bootSupported"]
    check(boot(autostart=[22021]) == (True, True),
          "скаут 2.4+ назвал порт в списке автозапуска — ↟ включён и доступен")
    check(boot(autostart=[]) == (False, True), "в списке нет — ↟ выключен, но доступен")
    check(boot() == (False, False) and boot(autostart=None) == (False, False),
          "negative: скаут списка не прислал (старше 2.4) — «не умеет», а не «выключено»")

    def parked(**host_fields):
        answer = served([], parked=[22021], **host_fields)
        cell = next((s for s in answer["llamaServers"] if s.get("port") == 22021), {})
        return cell.get("phase"), cell.get("bootEnabled"), cell.get("bootSupported")
    check(parked(autostart=[22021]) == ("stopped", True, True) and parked(autostart=[]) == ("stopped", False, True),
          "остановленная ячейка скаута тоже: ↟ по списку скаута — «Автозапуск есть, но стоит»")
    check(parked() == ("stopped", False, False),
          "negative: остановленная ячейка скаута без списка — «не умеет»")


def test_crash_on_the_card():
    print("💥 ячейки скаута:")

    def crash(note):
        answer = served([dict(LLAMA, crash=note)] if note is not ... else [LLAMA])
        return next(s for s in answer["llamaServers"] if s.get("isRemote"))["crash"]
    at = "2026-09-24T20:00:00+0400"
    check(crash({"count": 2, "at": at, "reason": "CUDA error: out of memory"})
          == {"count": 2, "at": at, "kind": "gpu-oom", "reason": "CUDA error: out of memory"},
          "сторож скаута (2.5+) говорит, сколько раз и почему — карточка показывает 💥 тем же видом, что у ячейки "
          "контроллера: вид определяет контроллер по тем же словам")
    check(crash({"count": 4, "at": at, "reason": "GGML_ASSERT failed", "gaveUp": True})
          == {"count": 4, "at": at, "kind": "assert", "reason": "GGML_ASSERT failed", "gaveUp": True},
          "сдался — так и сказано")
    check(crash(...) is None and crash({"count": 0}) is None and crash("oops") is None,
          "negative: скаут старше 2.5, ноль падений или мусор — нет 💥, а не «0 раз»")
    tail = "I load_model: loading\nE ggml_cuda: CUDA error: out of memory"
    got = crash({"count": 1, "at": at, "reason": "CUDA error: out of memory", "tail": tail})
    check(got.get("tail") == tail, "скаут 2.6+ прислал последние строки лога — они на карточке, под 💥")
    check(crash({"count": 1, "reason": "x", "tail": "a" * 1000 + "b" * 1000})["tail"] == "a" * 500 + "b" * 1000,
          "boundary: строк больше 1500 символов — остаются последние 1500, где причина")
    check("tail" not in crash({"count": 1, "at": at, "reason": "x", "tail": ""}),
          "negative: строк нет — поля нет, а не пустая строка")


def test_vllm_stats_on_the_card():
    print("очередь и скорость vLLM-ячейки скаута:")
    VLLM = {"port": 22012, "running": True, "phase": "running", "ctxMax": 1, "ctxTrained": 1}

    def stats(node, *also):
        answer = served([node, *also])
        return {s["port"]: s.get("vllmStats") for s in answer["llamaServers"] if s.get("isRemote")}
    got = stats(dict(VLLM, requestsProcessing=2, requestsWaiting=1, genTps=40.0, promptTps=150.0),
                dict(LLAMA, requestsProcessing=1, genTps=33.0))
    check(got == {22012: {"ok": True, "requestsRunning": 2, "requestsWaiting": 1, "genTps": 40.0, "promptTps": 150.0},
                  22021: None},
          f"скаут 2.7 сказал очередь и скорости — карточка получает те же vllmStats, что у vLLM-ячейки контроллера "
          f"(▶ идут ⏳ ждут, t/s); negative: у llama-ячейки их нет (got {got})")
    check(stats(dict(VLLM)) == {22012: None},
          "negative: скаут старше 2.7 очереди не говорит — чипов нет, а не «▶ 0»")
    check(stats(dict(VLLM, requestsProcessing=0, genTps=None)) == {22012: {
              "ok": True, "requestsRunning": 0, "requestsWaiting": 0, "genTps": None, "promptTps": None}},
          "boundary: первое чтение — очередь есть, скорости ещё нет: t/s не рисуется")


def test_starting_on_its_machine():
    print("ячейка скаута, чей порт ещё не слушает:")
    VLLM = {"port": 22012, "running": True, "phase": "running", "ctxMax": 1, "ctxTrained": 1}

    def shown(node):
        answer = served([node])
        s = next(x for x in answer["llamaServers"] if x.get("isRemote"))
        return s["phase"], s["status"]
    tail = "[caravan] provisioning vLLM venv at $HOME/vllm-venv (first start on this host, several minutes)…\nCollecting vllm"
    check(shown(dict(VLLM, listening=False, startingTail=tail)) == ("starting", {"phase": "starting",
                                                                                "progressNote": "provisioning venv"}),
          "процесс жив, порт не слушает (скаут 2.7) — «starting», а не «running»; где старт — теми же словами, что "
          "журнал ячейки контроллера (provisioning venv)")
    check(shown(dict(VLLM, listening=False, startingTail="Loading safetensors checkpoint shards: 40%")) == (
              "starting", {"phase": "starting", "progressNote": "loading weights"}),
          "веса грузятся — «loading weights»")
    check(shown(dict(VLLM, listening=False)) == ("starting", {"phase": "starting"}),
          "boundary: строк нет — «starting» без заметки, а не выдуманная стадия")
    check(shown(dict(VLLM, listening=True))[0] == "running",
          "negative: слушает у себя — «running»; если отсюда порт не виден, это файрвол, и карточка говорит о нём")
    check(shown(dict(VLLM))[0] == "running",
          "negative: скаут старше 2.7 не говорит — как было")


def test_retry_on_the_card():
    print("⚠ «прошлая попытка» у ячейки скаута, которую поднимает сторож:")
    tail = "I load_model: loading\nE alloc: cudaMalloc failed: out of memory"
    note = {"count": 1, "at": "2026-09-24T20:00:00+0400", "reason": "CUDA error: out of memory", "tail": tail}

    def status(node, health="loading"):
        answer = served([node], health=health)
        return next(s for s in answer["llamaServers"] if s.get("isRemote"))["status"]
    check(status(dict(LLAMA, crash=note)) == {"phase": "warming", "lastError": {
              "kind": "oom", "detail": "CUDA error: out of memory", "tail": tail}},
          "сторож поднял ячейку, она грузится — карточка говорит, от чего умерла прошлая попытка, теми же словами, "
          "что у ячейки контроллера (вид — по тому же правилу, что её журнал), и её строки")
    check(status(dict(LLAMA, crash=dict(note, tail=""))) == {"phase": "warming", "lastError": {
              "kind": "oom", "detail": "CUDA error: out of memory", "tail": ""}},
          "boundary: строк нет (скаут 2.5) — вид по одной причине, тем же правилом")
    check(status(dict(LLAMA, crash=dict(note, tail="", reason="GGML_ASSERT(n > 0) failed"))) == {
              "phase": "warming", "lastError": {"kind": "crash", "detail": "GGML_ASSERT(n > 0) failed", "tail": ""}},
          "negative: слов из правила нет — «крэш», а не выдуманная причина")
    check(status(dict(LLAMA, crash=dict(note, reason="exited (code 1)",
                                         tail="E srv: bind: address already in use"))) == {
              "phase": "warming", "lastError": {"kind": "port", "detail": "exited (code 1)",
                                                "tail": "E srv: bind: address already in use"}},
          "вид — по строкам лога, когда они есть: в них больше слов, чем в одной причине")
    check(status(dict(LLAMA, crash=note), health="ok") == {"phase": "running"},
          "negative: поднялась и работает — «прошлой попытки» нет, остаётся 💥")
    check(status(dict(LLAMA, crash=dict(note, gaveUp=True)), health="loading") == {"phase": "warming"},
          "negative: сторож сдался — он её не поднимает, и «прошлой попытки» нет")
    check(status(LLAMA) == {"phase": "warming"}, "negative: не падала — ничего")


if __name__ == "__main__":
    for fn in (test_llama_cell_alone, test_no_neighbour_meta, test_silent_command_cell, test_autostart_on_the_card,
               test_crash_on_the_card, test_retry_on_the_card, test_vllm_stats_on_the_card,
               test_starting_on_its_machine):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            check(False, f"{fn.__name__} упал: {exc!r}")
    if _fail:
        print(f"\nFAILED ({len(_fail)}):")
        for m in _fail:
            print("  - " + m)
        sys.exit(1)
    print("\ntopology remote cells OK")
