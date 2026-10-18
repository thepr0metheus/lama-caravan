"""One table of "time left" cases for the rule that words a wait (static/js/pace-rule.js).

Two screens word a wait with it: the models page (`Pace.eta`, the shared dictionary: scripts/test_js_model_moves.py) and /hf
(`HfFormat.eta`, the page's own table: scripts/test_js_hf_catalog.py). Both are run against THIS table, so a case added here is
read the same on both, and a rule that drifts on one of them turns that one red.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: (the seconds as a JS literal, the key of the phrase it takes — None when nothing is said — and the phrase's variables)
ETA_CASES = [
    ("0", None, {}), ("-1", None, {}), ("NaN", None, {}), ("Infinity", None, {}),
    ("0.2", "moveEtaSeconds", {"n": 5}), ("3", "moveEtaSeconds", {"n": 5}), ("40", "moveEtaSeconds", {"n": 40}),
    ("55", "moveEtaSeconds", {"n": 55}),
    # 58 s rounds up to 60 in fives, and a minute is a minute: "~60 s left" is never said
    ("58", "moveEtaMinutes", {"n": 1}), ("60", "moveEtaMinutes", {"n": 1}), ("61", "moveEtaMinutes", {"n": 2}),
    ("185", "moveEtaMinutes", {"n": 4}), ("3540", "moveEtaMinutes", {"n": 59}),
    ("3599", "moveEtaHours", {"h": 1, "m": 0}), ("3601", "moveEtaHours", {"h": 1, "m": 1}),
    ("3900", "moveEtaHours", {"h": 1, "m": 5}), ("4200", "moveEtaHours", {"h": 1, "m": 10}),
    ("7260", "moveEtaHours", {"h": 2, "m": 1}),
    # no days: a wait past a day is hours still
    ("90000", "moveEtaHours", {"h": 25, "m": 0}),
]


def inputs_js():
    """The seconds of every case, as a JS array literal."""
    return "[" + ", ".join(seconds for seconds, _, _ in ETA_CASES) + "]"


def expected(say):
    """What each case reads as, given `say(key, **vars)` that words a phrase in one language."""
    return [say(key, **variables) if key else "" for _, key, variables in ETA_CASES]


def words(lang="en"):
    """Every one-string line of the shared dictionary of a language (static/js/i18n/<lang>.js); a line holding anything else is skipped."""
    out = {}
    text = (ROOT / "static" / "js" / "i18n" / f"{lang}.js").read_text(encoding="utf-8")
    for key, raw in re.findall(r'^  (\w+): (".*"),$', text, re.M):
        try:
            out[key] = json.loads(raw)
        except ValueError:
            continue
    return out


def say_in(lang="en"):
    """A `say(key, **vars)` for `expected`, wording from the shared dictionary of a language."""
    table = words(lang)

    def say(key, **variables):
        text = table[key]
        for name, value in variables.items():
            text = text.replace("{" + name + "}", str(value))
        return text

    return say
