"""One table of what a cell's line says of speed and of work (1.3.588).

The line is drawn twice: the card builder (topology-nodes.js) writes it, the live patch (topology-render.js) rewrites it on every poll tick.
Both ask `CellSpeed` (cell-speed.js), and the snapshots of the class, of the builder and of the patch read THIS table, so the three cannot
agree on something the table does not say.

The owner, 2026-10-18, shown a Strata cell on the machine page: the switch of the line breathed, both video cards stood at 0 %, and the line
said "211.3 t/s". The cell had answered once and held its last speed; the line took a speed above 0 for work. The rule is a request running
now (`requestsProcessing` above 0), and the speed above 0 is only the last one — quiet, with `last` before it.

A case is (name, the server's fields, is the cell running, what the line shows, why). What the line shows:
  busy   — the switch breathes (the row's class `busy`)
  held   — the speed is the held one (the span's class `held`)
  text   — the words on the line
  title  — what hovering the speed says ("" for no title at all, not an empty one)
The words come out of static/js/i18n/en.js, not out of memory.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def en(key):
    """A string the pins expect, read out of static/js/i18n/en.js."""
    text = (ROOT / "static" / "js" / "i18n" / "en.js").read_text(encoding="utf-8")
    m = re.search(r"^\s*" + re.escape(key) + r':\s*(".*"),\s*$', text, re.M)
    return json.loads(m.group(1))


LAST = en("tpsLastLabel")
HELP = en("tpsLastHelp")
NOTHING = {"busy": False, "held": False, "text": "", "title": ""}

CASES = [
    ("working", {"genTps": 41.7, "requestsProcessing": 1}, True,
     {"busy": True, "held": False, "text": "41.70 t/s", "title": ""},
     "a request runs and the cell says its speed: the switch breathes, the figure is plain, nothing to explain on hover"),
    ("working_no_speed_yet", {"genTps": None, "requestsProcessing": 1}, True,
     {"busy": True, "held": False, "text": "", "title": ""},
     "a request runs and there is no speed yet (it reads its prompt): the switch breathes — it is the request that makes work, not the figure"),
    ("working_two_requests", {"genTps": 211.27, "requestsProcessing": 2}, True,
     {"busy": True, "held": False, "text": "211.3 t/s", "title": ""},
     "two requests run: the same, the figure written by the board's formatTps"),
    ("idle_holds_the_last_speed", {"genTps": 211.27, "requestsProcessing": 0}, True,
     {"busy": False, "held": True, "text": f"{LAST} 211.3 t/s", "title": HELP},
     "defect-history (the owner, 2026-10-18): the cell answered once and holds 211.3 t/s while no request runs — the switch must not breathe, "
     "and the figure says it is the last one (`last`, with its hint on hover)"),
    ("not_told_holds_the_last_speed", {"genTps": 41.7}, True,
     {"busy": False, "held": True, "text": f"{LAST} 41.70 t/s", "title": HELP},
     "a scout that does not say how many requests run: the line cannot tell work from a held speed, so it claims no work (not told is not 1)"),
    ("a_count_that_is_text_is_not_told", {"genTps": 41.7, "requestsProcessing": "2"}, True,
     {"busy": False, "held": True, "text": f"{LAST} 41.70 t/s", "title": HELP},
     "negative: a count that comes as text is not a count — nothing is coerced into work"),
    ("idle_no_speed", {"genTps": 0, "requestsProcessing": 0}, True, NOTHING,
     "idle with no speed to hold: no breathing, no figure, no title — the span stays, empty, for the live patch to write into"),
    ("not_running_says_nothing", {"genTps": 41.7, "requestsProcessing": 2}, False, NOTHING,
     "negative: a cell that does not run shows neither a speed nor breathing, whatever its last report said"),
]

#: A request count as a scout says it, and what it is: (JS source, the same value in Python, the count — None for "not told").
#: One table for `CellSpeed.count` (static/js/cell-speed.js) and `TokenRates.count` (caravan/admin/telemetry.py): the same rule in two languages,
#: so both are run against this and cannot drift apart. A whole number from 0 is a count (2.0 is 2); nothing else is, and nothing else is a 0 or a 1.
COUNTS = [
    ("2", 2, 2), ("0", 0, 0), ("100", 100, 100), ("2.0", 2.0, 2), ("0.0", 0.0, 0),
    ("1.5", 1.5, None), ("-1", -1, None), ("-0.5", -0.5, None), ('"2"', "2", None), ('""', "", None),
    ("true", True, None), ("false", False, None), ("null", None, None), ("undefined", None, None),
    ("NaN", float("nan"), None), ("Infinity", float("inf"), None), ("-Infinity", float("-inf"), None),
    ("[]", [], None), ("[2]", [2], None), ("({})", {}, None),
]
