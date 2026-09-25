#!/usr/bin/env python3
"""Engines next to the cells — Ollama, LM Studio (scout 2.12+) — on the controller.

What a scout says about them is kept honestly (caravan/domain/engine.py,
EngineReport): typed and bounded, and whatever the scout did not say stays
None — an older scout's silence is not "no engines", an engine that did not
list its models has not "no models", a memory it did not say is not zero.
The part of a card's memory that is no cell's is named by who holds it
(GpuOwners): the engine that owns the process, else the process's name. And
the board's node carries the engines as the host record keeps them.

Pinned by value, positive and negative on each claim. Nothing reaches a
disk, a process or the network.

Run: python3 scripts/test_foreign_engines.py
"""
import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import caravan.admin.fleet_clients as fc  # noqa: E402
import caravan.admin.topology as T  # noqa: E402
from caravan.domain.engine import EngineReport, GpuOwners  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def same(actual, expected, msg):
    check(actual == expected, msg if actual == expected else f"{msg}\n        got:  {actual!r}\n        want: {expected!r}")


MODEL = {"name": "qwen3:8b", "type": "", "format": "gguf", "family": "qwen3", "params": "8.2B", "quant": "Q4_K_M",
         "fileBytes": 5_225_388_164, "remote": False, "loaded": True, "memBytes": 6_591_830_464,
         "vramBytes": 5_333_539_264, "contextLength": 4096, "maxContextLength": None,
         "expiresAt": "2026-09-22T17:00:00+00:00", "instances": None}
ENGINE = {"kind": "ollama", "label": "Ollama", "port": 11434, "listen": "network", "state": "ok", "version": "0.12.3",
          "models": [MODEL], "pids": [5100, 5151], "ramBytes": 1_283_457_024}


def test_engine_report():
    print("что контроллер хранит о движке:")
    kept = EngineReport.engines([copy.deepcopy(ENGINE)])
    same(kept, [{**ENGINE, "api": ""}], "движок как сказал скаут — все поля, api пустой, когда не сказан")
    same(EngineReport.engines(None), None, "negative: скаут не сказал (старый) — None, а не [] («смотрел — нет»)")
    same(EngineReport.engines([]), [], "смотрел, никого — []")
    same(EngineReport.engines("x"), None, "negative: не список — тоже «не сказал»")

    def one(**fields):
        return EngineReport.engine({**copy.deepcopy(ENGINE), **fields})

    for name, fields in (("вида нет", {"kind": ""}), ("состояние чужое", {"state": "broken"}),
                         ("порта нет", {"port": None}), ("порт 0", {"port": 0}), ("порт 70000", {"port": 70000}),
                         ("порт строкой-мусором", {"port": "x"})):
        same(one(**fields), None, f"negative: {name} — это не движок, который назвал скаут: не хранится")
    same(one(port="11434")["port"], 11434, "boundary: порт строкой — числом")
    same([one(state=s)["state"] for s in ("ok", "auth", "unreachable")], ["ok", "auth", "unreachable"],
         "три состояния движка хранятся как есть")
    same((one(listen="everywhere")["listen"], one(listen="loopback")["listen"], one(listen=None)["listen"]),
         ("", "loopback", ""), "negative: где слушает — только loopback|network; иначе «» (не знаю), а не выдуманное")
    same(one(models=None)["models"], None, "negative: моделей не назвал (токен, молчит) — None, а не []")
    same(one(models=[{"name": ""}, "x", {"name": "a"}])["models"][0]["name"], "a",
         "модель без имени и не словарь — пропущены")
    same(len(one(models=[{"name": f"m{i}"} for i in range(250)])["models"]), 200,
         "boundary: не больше 200 моделей на движок")
    same(len(EngineReport.engines([copy.deepcopy(ENGINE) for _ in range(12)])), 8, "boundary: не больше 8 движков")
    same(one(pids=[3, "7", 0, -1, "x", True, 3])["pids"], [3, 7],
         "процессы — числа >0 без повторов, по порядку; bool — не pid")
    same(one(pids="5100")["pids"], [], "negative: pids не список — пусто")
    same((one(ramBytes=None)["ramBytes"], one(ramBytes="x")["ramBytes"]), (None, None),
         "negative: память не сказана или мусор — None, а не 0")
    same(("installedKnown" in one(), one(installedKnown=False).get("installedKnown")), (False, False),
         "список установленных не ответил — пометка есть только тогда")
    same(one(label="")["label"], "ollama", "boundary: без названия — вид")

    m = EngineReport.model({"name": "a", "loaded": "yes", "memBytes": "12", "vramBytes": None, "remote": "true",
                            "contextLength": True})
    same((m["loaded"], m["memBytes"], m["vramBytes"], m["remote"], m["contextLength"]), (None, 12, None, False, None),
         "negative: «загружена» не булево — None (не знаю); память строкой — число; remote только True; "
         "окно-булево — None")
    same(EngineReport.model({"name": "a", "loaded": False})["loaded"], False, "не загружена — False, не None")
    same(len(EngineReport.model({"name": "x" * 500})["name"]), 200, "boundary: имя модели — до 200 знаков")


def test_gpu_owners():
    print("чья чужая память на карте:")
    owners = GpuOwners([ENGINE, {"kind": "lmstudio", "label": "LM Studio", "pids": [613, 5100]}])
    same(owners.owner(5151, "ollama"), ("Ollama", "ollama"), "процесс движка — его имя и вид")
    same(owners.owner(613, "LM Studio Helper"), ("LM Studio", "lmstudio"), "процесс LM Studio — LM Studio")
    same(owners.owner(5100, "x"), ("Ollama", "ollama"), "boundary: pid двух движков — первого по отчёту")
    same(owners.owner(900, "python3"), ("python3", ""), "negative: не движка — имя процесса, без вида")
    same(owners.owner(901, ""), ("", ""), "negative: безымянный — имя «» (доска скажет «outside»), не выдуманное")
    split = owners.split([(903, None, "x"), (901, 300, ""), (5151, 5000, "ollama"), (900, 700, "python3"),
                          (5100, 200, "ollama"), (902, 300, "python3")])
    same(split, [{"name": "Ollama", "engine": "ollama", "mib": 5200},
                 {"name": "python3", "engine": "", "mib": 1000},
                 {"name": "", "engine": "", "mib": 300},
                 {"name": "x", "engine": "", "mib": 0}],
         "по владельцу, сумма; от большего к меньшему; память без числа — 0 (as-is: так же читал и старый код)")
    same(GpuOwners(None).split([(1, 10, "a")]), [{"name": "a", "engine": "", "mib": 10}],
         "negative: скаут без движков — все по имени процесса")
    same(GpuOwners([]).split([]), [], "на карте чужих нет — пусто")


def test_report_to_record():
    print("отчёт скаута → запись машины:")
    payload = {"host": {"id": "box-a", "name": "Box A"},
               "computeApps": [{"gpuUuid": "u0", "pid": 11, "name": "ollama", "usedMiB": 900},
                               {"gpuUuid": "u0", "pid": 12, "usedMiB": 5}],
               "engines": [copy.deepcopy(ENGINE)]}
    rec = fc.host_from_report(copy.deepcopy(payload))
    same([a["name"] for a in rec["computeApps"]], ["ollama", ""],
         "имя процесса на карте хранится; скаут без него — «»")
    same(rec["engines"], [{**ENGINE, "api": ""}], "движки — в записи машины")
    older = fc.host_from_report({"host": {"id": "box-a"}})
    same(older["engines"], None, "negative: скаут до 2.12 — None, доска ничего не рисует")
    pulled = fc.scout_payload_from_state({"host": {"id": "box-a"}}, "http://10.0.0.5:8092")
    same(pulled["engines"], None, "negative: опрос /api/state старого скаута тоже None, не []")


def test_bind_outside():
    print("память карты: наши ячейки и чужие по именам:")
    gpus = [{"index": 0, "uuid": "u0"}, {"index": 1, "uuid": "u1"}]
    apps = [{"gpuUuid": "u0", "pid": 4242, "name": "llama-server", "usedMiB": 20000},
            {"gpuUuid": "u0", "pid": 5151, "name": "ollama", "usedMiB": 3500},
            {"gpuUuid": "u0", "pid": 900, "name": "python3", "usedMiB": 700},
            {"gpuUuid": "u1", "pid": 5151, "name": "ollama", "usedMiB": 1000},
            {"gpuUuid": "zz", "pid": 1, "name": "x", "usedMiB": 1}]
    servers = [{"port": 22001, "pid": 4242}]
    _servers, out = T._bind_servers_to_gpus([dict(g) for g in gpus], apps, servers, [ENGINE])
    same([(g["fleetUsedMiB"], g["nonFleetUsedMiB"]) for g in out], [(20000, 4200), (0, 1000)],
         "наше и чужое по картам — как было")
    same([g["outside"] for g in out],
         [[{"name": "Ollama", "engine": "ollama", "mib": 3500}, {"name": "python3", "engine": "", "mib": 700}],
          [{"name": "Ollama", "engine": "ollama", "mib": 1000}]],
         "чужое названо: процесс движка — движком, другой — именем; процесс чужой карты не считается")
    same([sum(r["mib"] for r in g["outside"]) == g["nonFleetUsedMiB"] for g in out], [True, True],
         "разбивка — та же память: сумма владельцев равна nonFleetUsedMiB")
    _s, plain = T._bind_servers_to_gpus([dict(g) for g in gpus], apps, [{"port": 22001, "pid": 4242}])
    same(plain[0]["outside"][0], {"name": "ollama", "engine": "", "mib": 3500},
         "negative: без отчёта о движках — по имени процесса, без вида движка")


def test_node_carries_engines():
    print("узел доски несёт движки машины:")
    host = {"id": "box-a", "name": "Box A", "ip": "10.0.0.5", "state": "online", "cpu": {},
            "gpus": [{"index": "0", "uuid": "u0", "name": "G", "memoryTotalMiB": "24576"}],
            "computeApps": [{"gpuUuid": "u0", "pid": 5151, "name": "ollama", "usedMiB": 3500}],
            "engines": [{**ENGINE, "api": ""}]}
    saved = T.topo.power_schedules
    T.topo.power_schedules = lambda: {}
    try:
        nodes = T.topology_nodes({}, {"llamaServers": []}, [host, {**host, "id": "box-b", "engines": None}])
    finally:
        T.topo.power_schedules = saved
    same([n["engines"] for n in nodes], [[{**ENGINE, "api": ""}], None],
         "движки — как в записи; у машины со старым скаутом — None (не [])")
    same([n["gpus"][0]["outside"] for n in nodes],
         [[{"name": "Ollama", "engine": "ollama", "mib": 3500}], [{"name": "ollama", "engine": "", "mib": 3500}]],
         "память карты названа движком машины — узел отдаёт его отчёт в разбивку; без отчёта — имя процесса")


for test in (test_engine_report, test_gpu_owners, test_report_to_record, test_bind_outside,
             test_node_carries_engines):
    try:
        test()
    except Exception as exc:  # noqa: BLE001 — a crash is a red pin; the rest still runs
        check(False, f"{test.__name__} упал: {exc!r}")

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for f in _fail:
        print("  - " + f.splitlines()[0])
    sys.exit(1)
print("foreign engines OK")
