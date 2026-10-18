#!/usr/bin/env python3
"""Actual cell-speed.js: when a cell's line breathes, and which speed it shows (1.3.588).

The owner, 2026-10-18, shown a Strata cell on the machine page: the switch of the line breathed, both video cards stood at 0 %, and the line said
"211.3 t/s". The cell had answered once and held its last speed (the scout holds it while the cell is idle); the line took a speed above 0 for
work. The rule is a request running now: the scout says how many (`requestsProcessing`) and the line breathes on a number above 0. The held
speed stays on the line, quiet, with `last` before it and its hint on hover.

Pinned, by value, each with its negative:
  - the table of cases (scripts/cell_speed_cases.py) — the same one the card builder's and the live patch's snapshots read: which cases
    work, which hold a speed, which say nothing, and the hint each one carries;
  - a count is a whole number from 0 and nothing else: text, a float, a negative, a boolean, junk are "not told" (null), never 0 and never 1;
  - "not told" is its own state: with no count the line claims no work, and a speed above 0 is the last one;
  - the speed: a number above 0 on a running cell, a numeric string too (as the old rule read it); junk, a negative, infinity are no speed;
  - the words: the board's number formatter is handed over (the class does not import polling.js), `last` stands before a held figure only,
    nothing when there is no figure; the hint only for a held one;
  - a cell that does not run has no speed and no work whatever its report said, and a missing server is no crash.

The module is loaded for real, with the real i18n (English); the words the pins expect are read out of static/js/i18n/en.js.

Run: python3 scripts/test_js_cell_speed.py
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _js_pins import run  # noqa: E402
from cell_speed_cases import CASES, COUNTS, HELP, LAST  # noqa: E402

PREAMBLE = r"""
import "./_js_globals.mjs";
import { pathToFileURL } from "node:url";
const { CellSpeed } = await import(pathToFileURL(process.env.JS_ROOT + "/cell-speed.js").href);
const reset = () => {};
const fmt = (n) => `<${n}>`;
const face = (server, running) => { const c = new CellSpeed(server, running);
  return { working: c.working, held: c.held, words: c.words(fmt), hint: c.hint() }; };
"""

PINS = []

# ── the table: the same cases the builder's and the patch's snapshots read ──
for name, server, running, want, why in CASES:
    expected = {"working": want["busy"], "held": want["held"], "hint": want["title"],
                "shape": ("none" if not want["text"] else "held" if want["held"] else "plain")}
    PINS.append((
        f"table_{name}",
        "",
        f"(f => ({{ working: f.working, held: f.held, hint: f.hint, "
        f"shape: f.words === '' ? 'none' : f.words.startsWith({json.dumps(LAST + ' ')}) ? 'held' : 'plain' }}))"
        f"(face({json.dumps(server)}, {json.dumps(running)}))",
        json.dumps(expected),
        f"the table — {name}: {why}",
    ))

PINS += [
    ("count_is_a_whole_number",
     "",
     "[" + ", ".join(js for js, _py, count in COUNTS if count is not None) + "].map((v) => String(CellSpeed.count(v)))",
     json.dumps([str(count) for _js, _py, count in COUNTS if count is not None]),
     "positive (the table COUNTS, shared with the Python rule in telemetry.py): a count is a whole number from 0 — 2, a measured 0, a hundred; 2.0 is 2"),
    ("count_is_not_anything_else",
     "",
     "[" + ", ".join(js for js, _py, count in COUNTS if count is None) + "].map((v) => String(CellSpeed.count(v)))",
     json.dumps(["null"] * sum(1 for _js, _py, count in COUNTS if count is None)),
     "negative: a float, a negative, text, a boolean, null, NaN, infinity, a list, an object are NOT told (null) — never a 0 (that would say "
     "'idle') and never a 1 (that would say 'working'); read as text, because JSON prints infinity as null and would not tell it from null"),
    ("not_told_is_not_idle_and_not_work",
     "",
     '[new CellSpeed({ genTps: 5 }, true), new CellSpeed({ genTps: 5, requestsProcessing: 0 }, true)].map((c) => [c.requests, c.working, c.held])',
     json.dumps([[None, False, True], [0, False, True]]),
     "a scout that says no count leaves requests null, and a measured 0 is 0: neither claims work, both hold the speed as the last one"),
    ("speed_above_zero_on_a_running_cell",
     "",
     '[41.7, "41.7", 0.001].map((v) => new CellSpeed({ genTps: v, requestsProcessing: 1 }, true).speed)',
     "[41.7, 41.7, 0.001]",
     "positive: a number above 0 is the speed, and so is a numeric string — the old rule read it as a number too"),
    ("speed_junk_is_no_speed",
     "",
     '["x", -3, Infinity, NaN, null, undefined, 0, "", {}].map((v) => new CellSpeed({ genTps: v, requestsProcessing: 1 }, true).speed)',
     json.dumps([0] * 9),
     "negative: junk, a negative, infinity, null, zero are no speed — 0, never NaN; a cell with a request running and no speed still works"),
    ("working_without_speed_still_works",
     "",
     '[new CellSpeed({ genTps: "x", requestsProcessing: 1 }, true), new CellSpeed({ requestsProcessing: 3 }, true)].map((c) => [c.working, c.held, c.words(fmt)])',
     json.dumps([[True, False, ""], [True, False, ""]]),
     "work is the request, not the figure: it breathes with no figure, and there is nothing to say on the line"),
    ("words_use_the_number_handed_over",
     "",
     '[new CellSpeed({ genTps: 41.7, requestsProcessing: 1 }, true).words((n) => "N"), new CellSpeed({ genTps: 41.7, requestsProcessing: 0 }, true).words((n) => "N")]',
     json.dumps(["N t/s", f"{LAST} N t/s"]),
     "the board's formatter writes the number (the class does not import polling.js): a plain figure while working, `last` before it when held"),
    ("hint_only_for_a_held_speed",
     "",
     '[new CellSpeed({ genTps: 41.7, requestsProcessing: 1 }, true).hint(), new CellSpeed({ genTps: 41.7, requestsProcessing: 0 }, true).hint(), new CellSpeed({}, true).hint()]',
     json.dumps(["", HELP, ""]),
     "the hint explains only a held speed; a plain figure and no figure have nothing to explain (and no title at all, not an empty one)"),
    ("a_cell_that_does_not_run_has_nothing",
     "",
     '[false, 0, null, undefined, ""].map((r) => face({ genTps: 41.7, requestsProcessing: 2 }, r))',
     json.dumps([{"working": False, "held": False, "words": "", "hint": ""}] * 5),
     "negative: a cell that does not run has no speed and no work, whatever its last report said"),
    ("a_missing_server_is_no_crash",
     "",
     '[face(null, true), face(undefined, true), face({}, true)]',
     json.dumps([{"working": False, "held": False, "words": "", "hint": ""}] * 3),
     "no server record, or an empty one: nothing to say, and no crash"),
    ("held_and_working_never_together",
     "",
     '[0, 1, 2, null, undefined, "1"].map((n) => { const c = new CellSpeed({ genTps: 9, requestsProcessing: n }, true); return c.held && c.working; })',
     json.dumps([False] * 6),
     "a line breathes or holds a speed, never both: the ring and the word `last` would contradict each other"),
]

# i18n.js reaches the board's modules, which want a browser; the modules a card-rows snapshot stubs are stubbed here too.
STUBS = "command-preview,favorites,llama-edit,form,remote-cells,cloud,topology-render,polling"

ROOT = Path(__file__).resolve().parent.parent
#: The cases the table must keep: thin it and the three snapshots that read it go on passing without saying what they were written for.
KEPT = {"working", "working_no_speed_yet", "idle_holds_the_last_speed", "not_told_holds_the_last_speed", "a_count_that_is_text_is_not_told",
        "idle_no_speed", "not_running_says_nothing"}


def words_and_table():
    """What the pins above cannot see: the hint's words in every language, and that the table still holds its cases."""
    bad = []
    missing = KEPT - {c[0] for c in CASES}
    if missing:
        bad.append(f"the table of cases lost {sorted(missing)} — the snapshots would pass without them")
    hints = {}
    for path in sorted((ROOT / "static" / "js" / "i18n").glob("*.js")):
        m = re.search(r'^  tpsLastHelp: "((?:[^"\\]|\\.)*)",$', path.read_text(encoding="utf-8"), re.M)
        hints[path.stem] = m.group(1) if m else ""
    if len(hints) != 20 or [lang for lang, text in hints.items() if not text]:
        bad.append(f"the hint tpsLastHelp is missing or empty in {[lang for lang, text in hints.items() if not text] or 'a language file'}")
    named = sorted(lang for lang, text in hints.items() if "llama" in text.lower())
    if named:
        bad.append(f"the hint names llama.cpp in {named}: a held speed is shown for every server (Strata, vLLM), not only for llama.cpp")
    return bad


def main():
    code = run("js cell-speed", ".probe_cell_speed.tmp.mjs", PREAMBLE, PINS, STUBS)
    problems = words_and_table()
    print("the hint's words and the table:")
    for line in problems or ["  ok  the hint is in 20 languages and names no single server; the table keeps its cases"]:
        print(("  FAIL " + line) if problems else line)
    return 1 if (code or problems) else 0


if __name__ == "__main__":
    sys.exit(main())
