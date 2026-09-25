#!/usr/bin/env python3
"""Снимок значениями: что монитор контроллера собирает каждую секунду.

До шага 6.9 каждая секунда монитора опрашивала ещё и одиночный сервер
контроллера: его слоты (/slots), журнал (тайминги и контекст запросов),
подключённых клиентов (ss) и счётчики токенов (/metrics всех его ячеек) — и
подмешивала их к записям прокси. Тайминги из журнала цеплялись к запросу по
времени, какой бы сервер его ни обслуживал; счётчики давали отдельную серию
скоростей (tokenGenSamples), а подписи клиентов — client-labels.json. Ячейки
контроллера переехали на скаут его машины в шаге 6.8, одиночный сервер не
запущен, и в 6.9 ушёл его опрос. Остаётся то, что монитор знает сам и от
прокси: CPU, память, диск, сеть, GPU и запросы в полёте по маршрутам.

Запуск: python3 scripts/test_monitor_sample.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from caravan.admin import llama_metrics, monitoring, proxy_stats, token_history  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


# A sample as the sampler builds it, plus what the controller's own single
# server used to put next to it (llamaActivity, tokens): its busy slot, a
# journal timing at the very second the recent request finished, its counters.
SAMPLE = {
    "time": 1700000000,
    "gpu": {"utilPct": 40, "memoryPct": 55, "memoryUsedMiB": 100, "memoryTotalMiB": 200,
            "temperatureC": 50, "powerW": 90},
    "agentProxies": {"agents": {
        "23001": {"label": "sol", "port": 23001, "upstreamType": "llama",
                  "active": [{"id": "r1", "phase": "running", "client": "10.0.0.7", "startedAt": 1699999990}],
                  "recent": [{"id": "r0", "status": 200, "client": "10.0.0.8", "startedAt": 1699999900,
                              "finishedAt": 1699999950, "time": "2023-11-14T22:12:30"}]},
        "23002": {"label": "sky", "port": 23002, "upstreamType": "cloud",
                  "active": [{"id": "r2", "phase": "running", "client": "10.0.0.9", "upstreamType": "cloud"}],
                  "recent": []},
    }},
    "llamaActivity": {"port": 8080, "activeSlots": [{"id": 0, "isProcessing": True}],
                      "timingEvents": [{"time": "2023-11-14T22:12:30", "promptTps": 300.0, "evalTps": 30.0}],
                      "contextEvents": [{"time": "2023-11-14T22:12:30", "tokens": 42}],
                      "context": {"tokens": 42}, "promptCache": {"prompts": 3},
                      "lastTiming": {"promptTps": 300.0, "evalTps": 30.0}},
    "tokens": {"requestsProcessing": 1, "requestsDeferred": 2,
               "promptTokensPerSecond": 500.0, "predictedTokensPerSecond": 50.0},
}

GPU_KEYS = ["activeClients", "activeRequestCount", "activeRoutes", "cloudActiveRoutes", "memoryPct",
            "memoryTotalMiB", "memoryUsedMiB", "powerW", "temperatureC", "utilPct"]


def pin_correlation():
    print("корреляция запросов:")
    res = monitoring.correlate_activity(SAMPLE)
    check(res["llamaServer"] == {"activeRequestCount": 1, "activeClients": ["10.0.0.7"], "activeRoutes": ["sol"]},
          f"локальные запросы в полёте по флоту — счётчик, клиенты, маршруты; negative: ни порта, ни слотов, "
          f"ни контекста, ни кэша, ни таймингов и скоростей одиночного сервера (got {res['llamaServer']})")
    gpu = res["gpu"]
    check(sorted(gpu) == GPU_KEYS,
          f"negative: у GPU-корреляции нет processingSlotCount — только запросы и показания карты (got {sorted(gpu)})")
    check([gpu["activeRequestCount"], gpu["activeRoutes"], gpu["cloudActiveRoutes"], gpu["utilPct"]]
          == [2, ["sol"], ["sky"], 40],
          f"GPU: два запроса в полёте, облачный маршрут отдельно, загрузка карты (got "
          f"{[gpu['activeRequestCount'], gpu['activeRoutes'], gpu['cloudActiveRoutes'], gpu['utilPct']]})")
    active = next(i for i in res["activeRequests"] if i["label"] == "sol")
    check([active["correlation"], "slots" in active, "slotIds" in active] == ["active-proxy", False, False],
          f"negative: запрос в полёте больше не получает слоты одиночного сервера (got "
          f"{[active['correlation'], 'slots' in active, 'slotIds' in active]})")
    recent = res["recentRequests"][0]
    check([recent["id"], recent["correlation"], "timing" in recent, "context" in recent]
          == ["r0", "proxy-only", False, False],
          f"negative: завершённый запрос — «proxy-only», хотя тайминг журнала в ту же секунду: к нему больше "
          f"ничего не цепляется по времени (got {[recent['id'], recent['correlation'], 'timing' in recent, 'context' in recent]})")
    return res


def pin_slim(res):
    print("история для графиков:")
    slim = monitoring._slim_sample({**SAMPLE, "cpu": {"totalPct": 5}, "correlatedActivity": res})
    check(sorted(slim) == ["correlatedActivity", "cpu", "gpu", "time"],
          f"negative: в историю не попадают tokens и llamaActivity, даже если они в сэмпле (got {sorted(slim)})")


def pin_collect():
    print("секунда монитора:")
    calls = []
    saved = {}
    fakes = {
        "read_cpu_times": lambda: None, "read_disk_counters": lambda: {}, "read_net_counters": lambda: {},
        "gpu_sample": lambda: {"utilPct": 1}, "agent_proxy_sample": lambda: {"agents": {}},
        "load_agent_proxy_config": lambda: {}, "memory_sample": lambda: {}, "top_processes": lambda: [],
        "record_token_history": lambda sample: None, "append_incidents_from_sample": lambda sample: None,
        "persist_monitor_history": lambda force=False: None, "trim_monitor_history": lambda: None,
        "run": lambda *a, **k: calls.append(("run", a)) or {"ok": False, "stdout": "", "stderr": ""},
        "fetch_json": lambda *a, **k: calls.append(("fetch_json", a)) or {},
        "fetch_text": lambda *a, **k: calls.append(("fetch_text", a)) or "",
    }
    for name, fake in fakes.items():
        saved[name] = getattr(monitoring, name)
        setattr(monitoring, name, fake)
    saved_rms = llama_metrics.runtime_metrics_sample
    llama_metrics.runtime_metrics_sample = lambda *a, **k: calls.append(("runtime_metrics_sample", a)) or {}
    history = list(monitoring.monitor_history)
    latest = monitoring.monitor_latest_full
    try:
        monitoring.collect_monitor_sample()
        sample = monitoring.monitor_latest_full
    finally:
        for name, fn in saved.items():
            setattr(monitoring, name, fn)
        llama_metrics.runtime_metrics_sample = saved_rms
        monitoring.monitor_history.clear()
        monitoring.monitor_history.extend(history)
        monitoring.monitor_latest_full = latest
    check(sorted(sample) == ["agentProxies", "agentProxyConfig", "correlatedActivity", "cpu", "cpuLoad", "disk",
                             "gpu", "memory", "net", "processes", "time"],
          f"negative: в сэмпле нет llamaClients, llamaActivity и tokens (got {sorted(sample)})")
    check(calls == [],
          f"negative: секунда монитора не зовёт ни journalctl/ss, ни HTTP одиночного сервера, ни его /metrics (got {calls})")


def pin_payload():
    print("ответ /api/system-monitor:")
    saved_log = monitoring.load_incident_log
    monitoring.load_incident_log = lambda limit=200: []
    history = list(monitoring.monitor_history)
    latest = monitoring.monitor_latest_full
    try:
        monitoring.monitor_history.clear()
        monitoring.monitor_history.append({"time": 2**40})
        monitoring.monitor_latest_full = {"time": 2**40}
        body = monitoring.system_monitor_state()
    finally:
        monitoring.load_incident_log = saved_log
        monitoring.monitor_history.clear()
        monitoring.monitor_history.extend(history)
        monitoring.monitor_latest_full = latest
    check([len(body["samples"]), body["latest"], body["incidents"]] == [1, {"time": 2**40}, []],
          f"сэмплы, последний сэмпл целиком и инциденты — на месте (got {[len(body['samples']), body['latest'], body['incidents']]})")
    check(["clientLabels" in body, "tokenGenSamples" in body] == [False, False],
          f"negative: ни подписей клиентов, ни серии скоростей одиночного сервера (got "
          f"{['clientLabels' in body, 'tokenGenSamples' in body]})")


def pin_gone():
    print("что ушло из модулей:")
    gone = [f"{mod.__name__.rsplit('.', 1)[-1]}.{name}" for mod, names in (
        (monitoring, ("llama_activity_sample", "llama_activity_cache", "llama_clients_sample", "load_client_labels",
                      "save_client_labels", "known_client_name", "KNOWN_LLAMA_CLIENTS", "parse_ss_client_line")),
        (token_history, ("controller_llama_ports", "controller_token_metrics", "record_controller_gen_tps",
                         "controller_gen_tps_samples", "CONTROLLER_GEN_TPS_MAX")),
        (proxy_stats, ("requests_by_client", "nearest_event", "proxy_item_timestamp", "iso_seconds")),
    ) for name in names if hasattr(mod, name)]
    check(gone == [], f"negative: опрос одиночного сервера, его счётчики и сверка по времени ушли (got {gone})")
    kept = [callable(token_history.record_token_history), callable(token_history.token_history_query),
            callable(proxy_stats.summarize_proxy_item)]
    check(kept == [True, True, True],
          "остаются история скоростей из записей прокси (точные тайминги llama.cpp) и сводка записи прокси")


def main():
    res = pin_correlation()
    pin_slim(res)
    pin_collect()
    pin_payload()
    pin_gone()
    if _fail:
        print(f"\nFAILED ({len(_fail)}):")
        for m in _fail:
            print("  - " + m)
        return 1
    print("\nmonitor sample OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
