#!/usr/bin/env python3
"""Value snapshot: a quantized V cache needs flash attention (caravan/common/kv_cache.py, runner.py).

The incident (2026-10-14): the form of a new cell offered V cache q8_0 with flash attention off. llama.cpp
stops at once with "quantized V cache requires flash_attn to be enabled"; the cell crashed four times in ten
minutes and gave up, and its card showed the last line of the log, not the cause.

Pinned, each claim with the answer that would pass it wrongly:
  * the table of cases scripts/fixtures/kv-cache-cases.json — the same table static/js/kv-cache.js is held to
    (scripts/test_js_kv_cache.py): which pair is refused, in which spellings, and what is NOT refused (flash
    attention unstated, a K cache, the draft's cache types, plain-number types);
  * the refusal names the type, the cause and BOTH ways out;
  * a start is refused before it is made, for a llama.cpp cell and a PrismML cell, and a good pair starts.

Run: python3 scripts/test_kv_cache.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from caravan.common.errors import AppError  # noqa: E402
from caravan.common.kv_cache import KvCache  # noqa: E402
from caravan.domain.runner import for_config  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def refusal(runner_config, model="m.gguf"):
    try:
        for_config(runner_config).preflight_start(runner_config, model)
    except AppError as exc:
        return str(exc), exc.status if hasattr(exc, "status") else None
    return None


def main():
    cases = json.loads((ROOT / "scripts" / "fixtures" / "kv-cache-cases.json").read_text(encoding="utf-8"))["cases"]

    print("the table of cases (the browser's copy runs the same):")
    for case in cases:
        got = KvCache.refused_type(case["config"])
        check(got == case["refused"], f"{case['say']} -> {case['refused']!r} (got {got!r})")
    check(len(cases) >= 12 and any(c["refused"] for c in cases) and any(not c["refused"] for c in cases),
          "the table holds both answers: a table that only ever says no pins nothing")

    print("the words of the refusal:")
    try:
        KvCache.check({"ENABLE_FLASH_ATTN": "0", "CACHE_TYPE_V": "q8_0"})
        said = ""
    except AppError as exc:
        said = str(exc)
    check("q8_0" in said and "flash_attn" in said, f"it names the type and the cause llama.cpp gives (got {said!r})")
    check("ENABLE_FLASH_ATTN on" in said and "CACHE_TYPE_V to f16" in said, "it names both ways out: flash attention on, or an f16 V cache")
    KvCache.check({"ENABLE_FLASH_ATTN": "1", "CACHE_TYPE_V": "q8_0"})
    check(True, "negative: a good pair raises nothing")

    print("a start is refused before it is made:")
    bad = {"RUNNER": "llama-server", "MODEL_FILE": "m.gguf", "ENABLE_FLASH_ATTN": "0", "CACHE_TYPE_V": "q8_0"}
    good = {**bad, "ENABLE_FLASH_ATTN": "1"}
    for name in ("llama-server", "prism"):
        got = refusal({**bad, "RUNNER": name})
        check(got and "needs flash attention" in got[0], f"a {name} cell saved with the bad pair is refused with the cause (got {got})")
        check(refusal({**good, "RUNNER": name}) is None, f"negative: a {name} cell with flash attention on starts")
    check(refusal({**bad, "ENABLE_FLASH_ATTN": ""}) is None, "negative: flash attention unstated is not refused: llama.cpp decides")
    check(refusal({**bad, "CACHE_TYPE_V": "f16"}) is None, "negative: flash attention off with an f16 V cache starts")
    others = refusal({"RUNNER": "vllm", "VLLM_MODEL": "x/y", "ENABLE_FLASH_ATTN": "0", "CACHE_TYPE_V": "q8_0"}, "")
    check(others is None, "negative: another runner keeps the fields of the llama form unread, whatever they hold")

    if _fail:
        print(f"FAILED ({len(_fail)}):")
        for msg in _fail:
            print("  - " + msg)
        sys.exit(1)
    print("kv cache snapshots hold")


if __name__ == "__main__":
    main()
