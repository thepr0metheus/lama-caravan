#!/usr/bin/env python3
"""Snapshot of static/js/kv-cache.js — the browser's copy of "a quantized V cache needs flash attention".

The rule is Python's (caravan/common/kv_cache.py) and the browser says it at Apply, before the cell crashes
four times and gives up (2026-10-14). The two copies run ONE table of cases, scripts/fixtures/kv-cache-cases.json:
which pair is refused, in which spellings, and what is not (flash attention unstated, a K cache, the draft's
cache types, the types of plain numbers). A case the copies would answer differently turns this red or
scripts/test_kv_cache.py red.

Run: python3 scripts/test_js_kv_cache.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _js_pins import run  # noqa: E402

CASES = json.loads((Path(__file__).resolve().parent / "fixtures" / "kv-cache-cases.json").read_text(encoding="utf-8"))["cases"]

PREAMBLE = r"""
import "./_js_globals.mjs";
import { pathToFileURL } from "node:url";
const K = await import(pathToFileURL(process.env.JS_ROOT + "/kv-cache.js").href);
const CASES = """ + json.dumps(CASES) + r""";
const reset = () => {};
"""

PINS = [
    ("the_table_of_cases", "",
     r"""CASES.filter((c) => K.KvCache.refusedType(c.config) !== c.refused).map((c) => c.say)""",
     "[]",
     "таблица случаев — та же, что у Python: каждый ответ совпал (названы только расхождения)"),

    ("the_table_says_both_answers", "",
     r"""[CASES.filter((c) => c.refused).length > 3, CASES.filter((c) => !c.refused).length > 6, CASES.length]""",
     "[true,true," + str(len(CASES)) + "]",
     "в таблице есть и «нельзя», и «можно»: таблица, которая всегда говорит «можно», ничего не держит"),

    ("what_plain_numbers_are", "",
     r"""[K.KvCache.PLAIN, K.KvCache.refusedType({ ENABLE_FLASH_ATTN: "0", CACHE_TYPE_V: "f32" }), K.KvCache.refusedType({ ENABLE_FLASH_ATTN: "0", CACHE_TYPE_V: "q4_1" })]""",
     '[["","f32","f16","bf16"],"","q4_1"]',
     "типы из чисел без сжатия — f32, f16, bf16 и пустой (умолчание llama.cpp); q4_1 при выключенном flash attention — отказ"),

    ("no_config_is_no_refusal", "",
     r"""[K.KvCache.refusedType(), K.KvCache.refusedType(null), K.KvCache.refusedType({}), K.KvCache.refusedType({ ENABLE_FLASH_ATTN: 0, CACHE_TYPE_V: "q8_0" })]""",
     '["","","","q8_0"]',
     "нет настроек — нет отказа; число 0 вместо строки — тоже «выключено»"),
]


if __name__ == "__main__":
    sys.exit(run("js kv-cache", ".probe_js_kv_cache.tmp.mjs", PREAMBLE, PINS))
