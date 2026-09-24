#!/usr/bin/env python3
"""Сколько видеопамяти ячейка забирает при старте — одно правило для машины
контроллера и для машин со скаутом.

vLLM при старте резервирует GPU_MEMORY_UTILIZATION × карту (0.9 по
умолчанию); если столько не свободно, он минуту падает по кругу. Контроллер
отказывал такому старту на своей машине заранее (`_vllm_vram_gate`), а у
ячеек скаута проверки не было. Правило переехало в раннер
(`Runner.vram_reservation`): контроллер проверяет им свою машину, а скауту
отдаёт резерв в запросе старта (`vram`) — свободную память скаут знает
сам, в момент запуска.

Пинится значениями: что резервирует vLLM и на какой карте, когда не
резервирует ничего, как контроллер отказывает и как ENV разбирается одним
парсером. Хранилище, nvidia-smi и systemd подменены.

Запуск: python3 scripts/test_vram_reservation.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from caravan.admin import cell_ops, fleet_clients as fc  # noqa: E402
from caravan.admin.model_locator import Locations  # noqa: E402
from caravan.common.errors import AppError  # noqa: E402
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


class Topo:
    def __init__(self, slots):
        self._slots = slots

    def slots(self):
        return self._slots


def gate(cfg, gpus, active=()):
    keep = cell_ops.gpu_state, cell_ops.topo, cell_ops.cell_service_status, cell_ops.is_controller_host
    cell_ops.gpu_state = lambda: {"ok": gpus is not None, "gpus": gpus or []}
    cell_ops.topo = Topo({f"c:{p}": {"hostId": "controller", "port": p} for p in (22001, 22012, *active)})
    cell_ops.cell_service_status = lambda p: {"ActiveState": "active" if p in active else "inactive"}
    cell_ops.is_controller_host = lambda h: h == "controller"
    try:
        cell_ops._vram_gate(22012, cfg)
        return None
    except AppError as exc:
        return exc.status, str(exc)
    finally:
        cell_ops.gpu_state, cell_ops.topo, cell_ops.cell_service_status, cell_ops.is_controller_host = keep


def section_the_controllers_gate():
    print("проверка на машине контроллера:")
    tight = [{"index": "0", "memoryTotalMiB": "32768", "memoryFreeMiB": "4000"}]
    check(gate(VLLM, tight, active=(22010,)) == (409, "vLLM wants 28.8 GiB reserved (utilization 0.90 × 32.0 GiB) but "
                                                       "only 3.9 GiB VRAM is free on GPU 0 — stop :22010 or lower "
                                                       "GPU_MEMORY_UTILIZATION"),
          "не помещается — 409 до старта, с картой и с тем, кто её держит; те же слова, что у скаута")
    check(gate(VLLM, tight) == (409, "vLLM wants 28.8 GiB reserved (utilization 0.90 × 32.0 GiB) but only 3.9 GiB VRAM "
                                     "is free on GPU 0 — lower GPU_MEMORY_UTILIZATION"),
          "никто из своих не держит — совет один: убавить долю")
    pinned = [{"index": "0", "memoryTotalMiB": "32768", "memoryFreeMiB": "32000"},
              {"index": "1", "memoryTotalMiB": "24576", "memoryFreeMiB": "1000"}]
    check((gate({**VLLM, "ENV": "CUDA_VISIBLE_DEVICES=1"}, pinned) or (0, ""))[1].endswith(
              "only 1.0 GiB VRAM is free on GPU 1 — lower GPU_MEMORY_UTILIZATION"),
          "ячейка закреплена за второй картой — проверяется она, а не первая (раньше — всегда первая)")
    check(gate(VLLM, CARDS) is None, "negative: помещается — старт идёт")
    check(gate({"RUNNER": "llama-server"}, tight) is None, "negative: llama.cpp не проверяется")
    check(gate(VLLM, None) is None, "negative: nvidia-smi нет — не мешаем, как и было")


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
    section_the_controllers_gate()
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
