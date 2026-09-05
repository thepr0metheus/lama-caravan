#!/usr/bin/env python3
"""Снимок истории скорости токенов — что попадает в график, а что нет.

История писалась ТОЛЬКО из блока `timings`, который отдаёт llama.cpp. Облачный
апстрим такого блока не отдаёт вовсе, поэтому у порта, который целыми днями
возит трафик, график был пуст — и выглядело это как «запросов не было». Запросов
было сколько угодно; не было ИЗМЕРЕНИЯ. Ровно тот класс дефектов, что в
docs/why.md: отсутствие, нарисованное как норма.

Теперь у завершённого облачного запроса выводится скорость генерации: сколько
токенов пришло и за сколько времени ПОСЛЕ первого байта. Скорость промпта не
выводится и здесь пинится её отсутствие: время до первого байта у облака — это
сеть и очередь провайдера, и выдать его за обработку промпта значило бы объявить
измерением то, чего мы не измеряли. Каждая запись помечена источником.

Запуск: python3 scripts/test_token_history.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from caravan.admin import token_history as th  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def test_derived_sample():
    print("скорость, выведенная из итогов запроса:")
    item = {"durationMs": 5000, "firstByteMs": 1000,
            "response": {"usage": {"completion_tokens": 120, "prompt_tokens": 800}}}
    s = th._usage_sample(item)
    check(s and s["evalTokens"] == 120, f"токены генерации взяты из usage (got {s})")
    check(s and s["genMs"] == 4000, "время считается ПОСЛЕ первого байта, а не за весь запрос")
    check(s and s["evalTps"] == 30.0, f"скорость = токены / это время (got {s and s['evalTps']})")
    check(s and "promptTps" not in s,
          "скорость промпта НЕ выводится: время до первого байта — сеть и очередь провайдера")
    s2 = th._usage_sample({"durationMs": 3000, "firstByteMs": 1000,
                           "stream": {"usage": {"completion_tokens": 40}}})
    check(s2 and s2["evalTps"] == 20.0, f"usage из потокового ответа считается так же (got {s2})")

    # ОТРИЦАТЕЛЬНЫЕ: где выводить нечего — там None, а не выдуманное число.
    check(th._usage_sample({"timings": {"predicted_n": 5},
                            "response": {"usage": {"completion_tokens": 9}}}) is None,
          "у запроса со своими таймингами есть измерение — выводить не надо")
    check(th._usage_sample({"durationMs": 5000, "firstByteMs": 1000, "response": {}}) is None,
          "без usage выводить нечего")
    check(th._usage_sample({"durationMs": 5000, "firstByteMs": 1000,
                            "response": {"usage": {"completion_tokens": 0}}}) is None,
          "ноль токенов — пустой ответ, а не запись в историю")
    check(th._usage_sample({"durationMs": 1000, "firstByteMs": 1000,
                            "response": {"usage": {"completion_tokens": 5}}}) is None,
          "первый байт в самом конце — делить не на что")
    check(th._usage_sample({"durationMs": 900, "firstByteMs": 1000,
                            "response": {"usage": {"completion_tokens": 5}}}) is None,
          "отрицательное время — отказ, а не отрицательная скорость")
    check(th._usage_sample(None) is None and th._usage_sample({}) is None,
          "мусор на входе — None, без исключения")


def test_records_both_kinds():
    print("что попадает в историю:")
    saved = []
    th._token_history = []
    th.save_token_history = lambda: saved.append(list(th._token_history))

    sample = {"agentProxies": {"agents": {
        "23001": {"recent": [
            {"id": "cloud-1", "port": 23001, "finishedAt": 1700000000, "client": "10.0.0.7",
             "durationMs": 5000, "firstByteMs": 1000,
             "response": {"usage": {"completion_tokens": 120, "prompt_tokens": 800},
                          "finishReasons": ["stop"]}},
        ]},
        "23103": {"recent": [
            {"id": "llama-1", "port": 23103, "finishedAt": 1700000001,
             "timings": {"predicted_n": 50, "predicted_per_second": 25.0,
                         "prompt_n": 300, "prompt_per_second": 900.0,
                         "prompt_ms": 333, "predicted_ms": 2000, "cache_n": 10}},
        ]},
    }}}
    th.record_token_history(sample)
    hist = {h["sig"]: h for h in th._token_history}
    check(set(hist) == {"cloud-1", "llama-1"},
          f"обе записи попали в историю (got {sorted(hist)})")
    cloud, llama = hist["cloud-1"], hist["llama-1"]
    check(cloud["source"] == "usage" and llama["source"] == "timings",
          "каждая помечена источником: измерено сервером или выведено из итогов")
    check(cloud["evalTps"] == 30.0 and cloud["port"] == 23001,
          f"облачная запись несёт свою скорость и свой порт (got {cloud})")
    check(cloud["promptTps"] == 0 and cloud["promptMs"] == 0,
          f"а скорости промпта у неё нет — и это не ноль-как-значение, а отсутствие (got {cloud})")
    check(cloud["finish"] == "stop", "причина завершения читается и у облачной записи")
    check(llama["evalTps"] == 25.0 and llama["promptTps"] == 900.0,
          f"запись llama.cpp по-прежнему берёт ОБЕ скорости из своих таймингов (got {llama})")
    check(llama["cacheTokens"] == 10, "и кэш, который знает только сервер")

    # ОТРИЦАТЕЛЬНЫЙ: повтор того же запроса не удваивает историю.
    th.record_token_history(sample)
    check(len(th._token_history) == 2, f"повторный опрос не дублирует записи (got {len(th._token_history)})")
    # ОТРИЦАТЕЛЬНЫЙ: незавершённый облачный запрос в историю не идёт.
    th.record_token_history({"agentProxies": {"agents": {"23001": {"recent": [
        {"id": "cloud-2", "port": 23001, "durationMs": 0, "firstByteMs": 0,
         "response": {"usage": {"completion_tokens": 7}}}]}}}})
    check("cloud-2" not in {h["sig"] for h in th._token_history},
          "запрос без измеримой длительности в историю не попадает")


for fn in (test_derived_sample, test_records_both_kinds):
    fn()

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail:
        print("  - " + m)
    sys.exit(1)
print("all token-history snapshots hold")
