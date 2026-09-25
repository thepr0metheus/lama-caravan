#!/usr/bin/env python3
"""Резерв ячейки в движке: «где запускать» и модель — на шаге резерва.

Оператор резервирует ячейку и говорит, где она работает: сам караван, Ollama
или LM Studio этой машины (решение 2026-09-25). Для движка резерв сразу берёт
модель, и ячейка рождается настроенной. Пинится значениями:

  * настройки ячейки — ровно четыре поля; порт движка — из отчёта машины;
  * отказы словами: чужой движок, нет модели в запросе, машина без отчёта,
    скаут без движков, движка нет, движок не готов (каждое состояние — своими
    словами), движок не перечислил модели, такой модели нет — и ни один
    отказ не занимает порт;
  * резерв без движка — прежний: пустая ячейка каравана;
  * id контроллера отказан прежними словами, а не «нет отчёта»;
  * зарезервированная ячейка движка стартует строкой своего раннера и
    спрашивает здоровье на /health.

Запуск: python3 scripts/test_engine_cell_reserve.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from caravan.admin import cell_ops, fleet_clients as fc, server_cells as sc  # noqa: E402
from caravan.admin.engine_cells import EngineCellPlan  # noqa: E402
from caravan.admin.model_locator import Locations  # noqa: E402
from caravan.common.errors import AppError  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def refusal(fn):
    try:
        fn()
    except AppError as exc:
        return getattr(exc, "status", None), str(exc)
    return None


def engine(kind="ollama", label="Ollama", port=11434, state="ok", models=("qwen2.5:0.5b", "nomic-embed-text:latest")):
    return {"kind": kind, "label": label, "port": port, "state": state,
            "models": None if models is None else [{"name": m} for m in models]}


HOST = {"id": "box-a", "engines": [engine(), engine("lmstudio", "LM Studio", 1250, models=("google/gemma-4-e4b",))]}
OLLAMA_CFG = {"RUNNER": "ollama", "CELL_KIND": "command", "ENGINE_MODEL": "qwen2.5:0.5b", "ENGINE_PORT": "11434"}


def plan(host, kind, model):
    return EngineCellPlan(host, kind, model)


def section_plan():
    print("план ячейки движка:")
    check(EngineCellPlan.kinds() == ("ollama", "lmstudio"),
          "движки — раннеры ячеек движка из реестра, их id = слова скаута")
    check(plan(HOST, "ollama", "qwen2.5:0.5b").config() == OLLAMA_CFG,
          "Ollama: раннер, CELL_KIND для старых читателей, модель как её зовёт движок, порт движка")
    check(plan(HOST, " LMStudio ", " google/gemma-4-e4b ").config()
          == {"RUNNER": "lmstudio", "CELL_KIND": "command", "ENGINE_MODEL": "google/gemma-4-e4b", "ENGINE_PORT": "1250"},
          "LM Studio: порт из отчёта машины (1250), а не свой по умолчанию; регистр и пробелы не мешают")
    check(EngineCellPlan.from_body(HOST, {"hostId": "box-a"}) is None
          and EngineCellPlan.from_body(HOST, {"hostId": "box-a", "engine": " "}) is None,
          "без движка в запросе плана нет — обычный резерв ячейки каравана")
    got = EngineCellPlan.from_body(HOST, {"engine": "ollama", "model": "m"})
    check((got.kind, got.model, got.host is HOST) == ("ollama", "m", True), "с движком — план этой машины")

    print("отказы плана:")
    cases = [
        (plan(HOST, "vllm", "m"), (400, "a cell runs in ollama, lmstudio, not in 'vllm'"),
         "negative: чужой движок — отказ со списком тех, где ячейка работает"),
        (plan(HOST, "ollama", " "), (400, "a cell in an engine is reserved with its model"),
         "negative: без модели ячейку движка не резервируют"),
        (plan({"engines": [engine(state="stopped", models=())]}, "ollama", ""),
         (409, "Ollama is not running on this machine — start its server first"),
         "negative: движок спрошен раньше модели — доска, которой нечего было выбрать, слышит причину"),
        (plan({"engines": [engine(models=())]}, "ollama", ""),
         (409, "Ollama on this machine has no models — download one into it first"),
         "negative: у движка нет ни одной модели — сказано, что сделать"),
        (plan(None, "ollama", "m"), (404, "no scout has reported for this machine"),
         "negative: машина без отчёта скаута — отказ, а не пустая ячейка"),
        (plan({"id": "box-a", "engines": None}, "ollama", "m"),
         (409, "this machine's scout does not look for engines — it is older than 2.12"),
         "negative: скаут старше 2.12 движков не видит — «не умеет», а не «движка нет»"),
        (plan({"id": "box-a", "engines": []}, "ollama", "m"), (404, "this machine reports no ollama"),
         "negative: скаут смотрел и движка не нашёл"),
        (plan({"engines": [engine(state="stopped")]}, "ollama", "qwen2.5:0.5b"),
         (409, "Ollama is not running on this machine — start its server first"),
         "negative: движок остановлен — сказано, что сделать"),
        (plan({"engines": [engine("lmstudio", "LM Studio", 1234, "unreachable")]}, "lmstudio", "qwen2.5:0.5b"),
         (409, "LM Studio is not answering on this machine"),
         "negative: не отвечает — имя движка из отчёта (LM Studio), а не его id"),
        (plan({"engines": [engine("lmstudio", "LM Studio", 1234, "auth")]}, "lmstudio", "qwen2.5:0.5b"),
         (409, "LM Studio on this machine asks for a token, and a cell has none to give it"),
         "negative: движок просит токен — «не запущен» было бы неправдой"),
        (plan({"engines": [engine(models=None)]}, "ollama", "qwen2.5:0.5b"),
         (409, "Ollama did not list its models, so the cell's model cannot be checked"),
         "negative: движок не перечислил модели — модель не проверить, отказ, а не догадка"),
        (plan(HOST, "ollama", "llama3:8b"), (404, "Ollama has no model llama3:8b on this machine"),
         "negative: такой модели в движке нет"),
        (plan(HOST, "ollama", "google/gemma-4-e4b"), (404, "Ollama has no model google/gemma-4-e4b on this machine"),
         "negative: модель другого движка той же машины — не модель этого"),
    ]
    for p, want, why in cases:
        got = refusal(p.config)
        check(got == want, f"{why} (got {got})")
    check(plan({"engines": [{**engine(), "label": ""}]}, "ollama", "qwen2.5:0.5b").config() == OLLAMA_CFG
          and refusal(plan({"engines": [{**engine(state="stopped"), "label": ""}]}, "ollama", "m").config)
          == (409, "ollama is not running on this machine — start its server first"),
          "boundary: отчёт без подписи — движок назван своим id")


class Topo:
    def __init__(self, slots):
        self.slots = slots

    def put_slot(self, host_id, port, value):
        self.slots[(host_id, int(port))] = value

    def has_slot(self, host_id, port):
        return (host_id, int(port)) in self.slots


class Store:
    """The controller's store and what reserving reaches beyond it, stood in
    for and put back."""

    def __init__(self):
        # A cell of another machine holds 22044: ports are fleet-wide.
        self.data = {"serverSlots": {"box-b:22044": {"hostId": "box-b", "port": 22044}}, "hosts": {"box-a": HOST}}
        self.saved = 0

    def __enter__(self):
        self.keep = (sc.topology_store, sc.save_admin_state, sc.topo, sc.used_server_cell_ports)
        sc.topology_store = lambda: self.data
        sc.save_admin_state = self.save
        sc.topo = Topo({})
        sc.used_server_cell_ports = lambda exclude_key=None: {
            int(s["port"]) for k, s in self.data["serverSlots"].items() if k != exclude_key}
        return self

    def save(self):
        self.saved += 1

    def __exit__(self, *exc):
        sc.topology_store, sc.save_admin_state, sc.topo, sc.used_server_cell_ports = self.keep


def section_reserve():
    print("резерв:")
    with Store() as st:
        doc = sc.reserve_server_cell({"hostId": "box-a", "port": 22041, "engine": "ollama",
                                      "model": "qwen2.5:0.5b", "label": "chat"})
        slot = st.data["serverSlots"].get("box-a:22041") or {}
        check(doc.get("ok") is True and doc.get("cell") is slot, "ячейка движка зарезервирована")
        check(slot.get("config") == OLLAMA_CFG and slot.get("kind") == "serverCell" and slot.get("label") == "chat",
              "ячейка рождается настроенной: ровно четыре поля плана")
        check("model" not in slot,
              "negative: имя модели движка — не файл: поле model слота (его читают сборщик мусора и старт) пустое")
        before, saves = {k: dict(v) for k, v in st.data["serverSlots"].items()}, st.saved
        check(saves > 0, "записано на диск")
        for body, want, why in (
            ({"hostId": "box-a", "port": 22042, "engine": "lmstudio", "model": "llama3:8b"},
             (404, "LM Studio has no model llama3:8b on this machine"), "модели нет"),
            ({"hostId": "box-z", "port": 22042, "engine": "ollama", "model": "qwen2.5:0.5b"},
             (404, "no scout has reported for this machine"), "машина без отчёта"),
            ({"hostId": "box-a", "port": 22044, "engine": "vllm", "model": "m"},
             (400, "a cell runs in ollama, lmstudio, not in 'vllm'"), "чужой движок на порту, занятом другой машиной"),
        ):
            got = refusal(lambda: sc.reserve_server_cell(body))
            check(got == want, f"negative: {why} — отказ этими словами, план проверен раньше порта (got {got})")
        check(st.data["serverSlots"] == before and st.saved == saves,
              "negative: отказ не занял порт и ничего не записал — пустой ячейки не остаётся")

        for host in ("controller", "skynet"):
            got = refusal(lambda: sc.reserve_server_cell({"hostId": host, "engine": "ollama", "model": "qwen2.5:0.5b"}))
            check(got == (400, sc.CONTROLLER_RUNS_NO_CELLS),
                  f"id контроллера ({host}) с движком — прежний отказ, а не «нет отчёта» (got {got})")

        doc = cell_ops.client_server_slot_add({"hostId": "box-a", "port": 22045, "engine": "ollama",
                                               "model": "qwen2.5:0.5b"})
        via_port = st.data["serverSlots"].get("box-a:22045") or {}
        check(doc.get("ok") is True and via_port.get("config") == OLLAMA_CFG and "model" not in via_port,
              "добавление слота с портом и движком идёт через план: имя модели движка не становится файлом слота")

        doc = sc.reserve_server_cell({"hostId": "box-a", "port": 22043})
        plain = st.data["serverSlots"].get("box-a:22043") or {}
        check(doc.get("ok") is True and "config" not in plain and plain.get("kind") == "serverCell",
              "резерв без движка — прежняя пустая ячейка каравана, без настроек")


def section_start():
    print("старт зарезервированной ячейки:")
    slot = {"hostId": "box-a", "port": 22041, "config": dict(OLLAMA_CFG), "kind": "serverCell"}
    body = cell_ops.scout_start_body("box-a", 22041, slot)
    check(body["modelPath"] == "" and body["config"] == OLLAMA_CFG, "старт не выдумывает файл модели")
    keep = fc.current_locations, fc.topology_store
    fc.current_locations = lambda wait=False: Locations([])
    fc.topology_store = lambda: {"hosts": {"box-a": HOST}}
    try:
        payload = fc.scout_start_payload(body)
    finally:
        fc.current_locations, fc.topology_store = keep
    check(payload.get("cellKind") == "command"
          and payload.get("command") == 'bash $HOME/run_engine.sh "$PORT" ollama 11434 qwen2.5:0.5b',
          "скауту уходит строка раннера: сервер ячейки-движка, движок, его порт, модель")
    check(payload.get("healthPath") == "/health" and payload["command"] in payload.get("shellLine", ""),
          "здоровье — на /health ячейки; строка старта несёт ту же команду")
    check("vram" not in payload, "negative: ячейка движка карту не резервирует — память держит движок")
    got = refusal(lambda: cell_ops.scout_start_body("box-a", 22041, {"config": {**OLLAMA_CFG, "ENGINE_MODEL": ""}}))
    check(got == (400, "ollama cell has no model — reserve it with one"),
          f"negative: без модели старт отказан до скаута, с подсказкой, где её дают (got {got})")


def main():
    section_plan()
    section_reserve()
    section_start()
    if _fail:
        print(f"\nFAILED ({len(_fail)}):")
        for m in _fail:
            print("  - " + m)
        return 1
    print("\nengine cell reserve OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
