#!/usr/bin/env python3
"""Сколько видеопамяти ячейка забирает при старте — одно правило для машины
контроллера и для машин со скаутом.

vLLM при старте резервирует GPU_MEMORY_UTILIZATION × карту (0.9 по
умолчанию); если столько не свободно, он минуту падает по кругу. Контроллер
отказывал такому старту на своей машине заранее (`_vllm_vram_gate`), а у
ячеек скаута проверки не было. Правило переехало в раннер
(`Runner.vram_reservation`): контроллер проверяет им свою машину, а скауту
отдаёт резерв в запросе старта (`vram`) — свободную память скаут знает
сам, в момент запуска. С шага 6.9 своих ячеек у контроллера нет, и своей
проверки тоже: все ячейки проверяет скаут их машины.

Пинится значениями: что резервирует vLLM и на какой карте, когда не
резервирует ничего, что уходит скауту и как ENV разбирается одним
парсером. Хранилище, nvidia-smi и systemd подменены.

Запуск: python3 scripts/test_vram_reservation.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from caravan.admin import fleet_clients as fc  # noqa: E402
from caravan.admin.model_locator import Locations  # noqa: E402
from caravan.domain.runner import Runner, VllmRunner, for_config  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


CARDS = [{"index": "0", "memoryTotalMiB": "32768", "memoryFreeMiB": "31000"},
         {"index": "1", "memoryTotalMiB": "24576", "memoryFreeMiB": "2000"}]
VLLM = {"RUNNER": "vllm", "VLLM_MODEL": "org/model", "PORT": "22012"}


def section_the_rule():
    print("что резервирует vLLM:")
    got = VllmRunner().vram_reservation(VLLM, CARDS)
    check(got == {"device": 0, "reserveMiB": 29491, "who": "vLLM", "why": "utilization 0.90 × 32.0 GiB",
                  "lower": "GPU_MEMORY_UTILIZATION"},
          f"по умолчанию 0.9 × первой карты — карта, сколько, чьё правило и что убавить (got {got})")
    got = VllmRunner().vram_reservation({**VLLM, "GPU_MEMORY_UTILIZATION": "0.5", "ENV": "HF_HOME=/x\nCUDA_VISIBLE_DEVICES=1"}, CARDS)
    check(got["device"] == 1 and got["reserveMiB"] == 12288 and got["why"] == "utilization 0.50 × 24.0 GiB",
          "своя доля, а карта — та, что закреплена в ENV (CUDA_VISIBLE_DEVICES=1)")
    for why, cfg, cards in (("tensor parallel на 2 карты — vLLM раскладывает сам", {**VLLM, "TENSOR_PARALLEL": "2"}, CARDS),
                            ("закреплена не одна карта по номеру", {**VLLM, "ENV": "CUDA_VISIBLE_DEVICES=GPU-3fa1"}, CARDS),
                            ("закреплённой карты у машины нет", {**VLLM, "ENV": "CUDA_VISIBLE_DEVICES=5"}, CARDS),
                            ("о картах машины ничего не известно", VLLM, None)):
        check(VllmRunner().vram_reservation(cfg, cards) is None, f"negative: {why} — резерва нет, проверки нет")
    check(VllmRunner().vram_reservation({**VLLM, "GPU_MEMORY_UTILIZATION": "много"}, CARDS)["reserveMiB"] == 29491,
          "boundary: доля не числом — 0.9, как у контроллера было")
    for runner in ("llama-server", "whisper", "custom"):
        check(for_config({"RUNNER": runner}).vram_reservation({"RUNNER": runner}, CARDS) is None,
              f"negative: {runner} ничего не резервирует заранее (llama.cpp и так падает быстро и понятно)")


def section_env():
    print("ENV — один разбор:")
    got = Runner.env_pairs("A=1, B = two\n# C=3\n9X=4\nnot a pair\nD=a=b")
    check(got == [("A", "1"), ("B", "two"), ("D", "a=b")],
          f"строки и запятые, комментарии и кривые имена пропущены, значение после первого «=» (got {got})")


def payload(cfg, host):
    keep = fc.topology_store, fc.current_locations
    fc.topology_store = lambda: {"hosts": {"box-a": host} if host is not None else {}}
    fc.current_locations = lambda wait=False: Locations([])
    try:
        return fc.scout_start_payload({"hostId": "box-a", "port": 22012, "config": dict(cfg), "modelPath": ""})
    finally:
        fc.topology_store, fc.current_locations = keep


def section_the_scouts_start():
    print("запрос старта ячейки скаута:")
    got = payload(VLLM, {"id": "box-a", "gpus": [{"index": "0", "memoryTotalMiB": "24576"}]})
    check(got.get("vram") == {"device": 0, "reserveMiB": 22118, "who": "vLLM", "why": "utilization 0.90 × 24.0 GiB",
                              "lower": "GPU_MEMORY_UTILIZATION"},
          "vLLM на машине со скаутом — в запросе резерв по карте из её отчёта: свободное скаут проверит сам при запуске")
    check("vram" not in payload(VLLM, {"id": "box-a"}),
          "negative: машина не назвала своих карт — резерва нет (не выдумываем размер карты)")
    check("vram" not in payload({"RUNNER": "whisper", "PORT": "22024"}, {"id": "box-a", "gpus": CARDS}),
          "negative: whisper ничего не резервирует заранее")


def main():
    section_the_rule()
    section_env()
    section_the_scouts_start()
    if _fail:
        print(f"\nFAILED ({len(_fail)}):")
        for m in _fail:
            print("  - " + m)
        return 1
    print("\nvram reservation OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
