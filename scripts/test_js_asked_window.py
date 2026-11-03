#!/usr/bin/env python3
"""Snapshot of static/js/asked-window.js — the browser's copy of "an empty context field asks for the trained window".

The rule is the program's (rust/crates/rules/src/cell_config.rs AskedWindow) and the browser counts by it: the form's memory
estimate, the cell window's plan and the add-model wizard size the KV cache of the window the start will ask for. The
two copies run ONE table of cases, contract/asked_window.json; a case they would answer differently turns
this red or rust/crates/admin/tests/contract.rs red.

Run: python3 scripts/test_js_asked_window.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _js_pins import run  # noqa: E402

CASES = json.loads((Path(__file__).resolve().parent.parent / "contract" / "asked_window.json").read_text(encoding="utf-8"))["cases"]

PREAMBLE = r"""
import "./_js_globals.mjs";
import { pathToFileURL } from "node:url";
const W = await import(pathToFileURL(process.env.JS_ROOT + "/asked-window.js").href);
const CASES = """ + json.dumps(CASES) + r""";
const reset = () => {};
"""

PINS = [
    ("the_table_of_cases", "",
     r"""CASES.filter((c) => W.AskedWindow.of(c.field, c.trained) !== c.asked).map((c) => c.say)""",
     "[]",
     "таблица случаев — та же, что у программы: каждый ответ совпал (названы только расхождения)"),

    ("the_table_says_every_answer", "",
     r"""[CASES.filter((c) => c.asked === null).length >= 5, CASES.filter((c) => c.asked !== null).length >= 9, CASES.length]""",
     "[true,true," + str(len(CASES)) + "]",
     "в таблице есть и число, и окно обучения, и «не знаю»: таблица с одним ответом ничего не держит"),

    ("booleans_are_no_window", "",
     r"""[W.AskedWindow.of("", true), W.AskedWindow.of(true, 4096), W.AskedWindow.positive(false)]""",
     "[null,null,null]",
     "булево — не размер: ни как окно обучения, ни как поле"),
]


if __name__ == "__main__":
    sys.exit(run("js asked-window", ".probe_js_asked_window.tmp.mjs", PREAMBLE, PINS))
