#!/usr/bin/env python3
"""Snapshot of the context-window rules in caravan/common/context_window.py.

Pins the VALUE of `effective_window` for every combination of its three
inputs — the operator's limit, the model's own window, the "model if larger"
switch — and of `block_window` and `route_window_inputs`. The proxy publishes
this figure in /v1/models and the board shows it on the route; the rule lives
once, and this is where it is spelled out row by row.

Run: python3 scripts/test_context_window.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from caravan.common.context_window import (  # noqa: E402
    block_window, effective_window, route_window_inputs, served_window, trained_window,
)

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


# (limit, model, prefer_model, expected, why)
EFFECTIVE = [
    (32768, 4096, False, 4096, "предел выше окна модели — меньшее, окно модели"),
    (2048, 4096, False, 2048, "предел ниже окна модели — меньшее, предел"),
    (4096, 4096, False, 4096, "равные — то же число"),
    (32768, None, False, 32768, "модель молчит — предел"),
    (None, 4096, False, 4096, "предела нет — окно модели"),
    (None, None, False, None, "ни того ни другого — ничего, а не ноль и не догадка"),
    (2048, 4096, True, 4096, "галка: модель больше предела — модель"),
    (32768, 4096, True, 4096, "галка: модель меньше предела — всё равно модель (меньшее и так оно)"),
    (32768, None, True, 32768, "галка при молчащей модели — предел остаётся в силе"),
    (None, None, True, None, "галка ничего не выдумывает"),
    (0, 4096, False, 4096, "ноль как предел — это отсутствие, а не окно в ноль"),
    ("8192", "4096", False, 4096, "строки читаются как числа"),
    ("8k", 4096, False, 4096, "мусор в пределе — отсутствие"),
    (True, 4096, False, 4096, "булево — не число, даже если int(True) == 1"),
    (8192, -1, False, 8192, "отрицательное окно модели — отсутствие"),
]

BLOCK = [
    (200000, 131072, False, 200000, "выключатель выкл: объявленное оператором, каталог не в счёт"),
    (200000, 131072, True, 131072, "выключатель вкл: число провайдера поверх объявленного"),
    (None, 131072, True, 131072, "вкл, объявленного нет — провайдер"),
    (None, 131072, False, None, "выкл, объявленного нет — ничего: каталог сам по себе не публикуется"),
    (200000, None, True, 200000, "вкл, провайдер молчит — объявленное"),
    (0, None, True, None, "ноль и молчание — ничего"),
]

INPUTS = [
    ({"contextLength": "8192", "contextAuto": 1}, (8192, True), "строка и единица читаются как число и галка"),
    ({"contextLength": 0, "contextAuto": False}, (None, False), "ноль — отсутствие предела"),
    ({}, (None, False), "пустой маршрут — ни предела, ни галки"),
    (None, (None, False), "не словарь — то же, что пустой"),
]


def main():
    print("effective_window(limit, model, prefer_model):")
    for limit, model, prefer, expected, why in EFFECTIVE:
        got = effective_window(limit, model, prefer)
        check(got == expected, f"({limit!r}, {model!r}, {prefer}) → {expected!r}: {why} (got {got!r})")
    print("block_window(declared, reported, prefer_reported):")
    for declared, reported, prefer, expected, why in BLOCK:
        got = block_window(declared, reported, prefer)
        check(got == expected, f"({declared!r}, {reported!r}, {prefer}) → {expected!r}: {why} (got {got!r})")
    print("route_window_inputs(route):")
    for route, expected, why in INPUTS:
        got = route_window_inputs(route)
        check(got == expected, f"{route!r} → {expected!r}: {why} (got {got!r})")
    print("served_window(entry) feeds the rule with the SERVED number only:")
    entry = {"meta": {"n_ctx": 60160, "n_ctx_train": 131072}}
    check(effective_window(None, served_window(entry)) == 60160,
          "llama.cpp: meta.n_ctx 60160 — а не обученные 131072")
    check(effective_window(None, served_window({"meta": {"n_ctx_train": 131072}})) is None,
          "только обученное число — окна нет: обученное окном не становится")
    print("trained_window(entry) — факт о весах, под своим именем:")
    check(trained_window(entry) == 131072, "llama.cpp: meta.n_ctx_train 131072 читается как обученное окно")
    check(trained_window({"meta": {"n_ctx": 60160}}) is None, "карточка без обученного числа — None, не n_ctx")
    check(trained_window({"meta": {"n_ctx_train": 0}}) is None and trained_window("x") is None,
          "ноль и не-словарь — отсутствие")
    check(effective_window(trained_window(entry), served_window(entry)) == 60160,
          "даже поданное как предел, обученное число не поднимает объявляемое окно выше обслуживаемого")
    if _fail:
        print(f"FAILED ({len(_fail)}):")
        for msg in _fail:
            print("  - " + msg)
        sys.exit(1)
    print(f"OK: {len(EFFECTIVE) + len(BLOCK) + len(INPUTS) + 6} пинов зелёные")


if __name__ == "__main__":
    main()
