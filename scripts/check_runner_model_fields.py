#!/usr/bin/env python3
"""Every runner must say which config key names the model it serves.

The board labels a cell, and draws chips describing it, from one string. That
string used to be MODEL_FILE for every runner — but only llama keeps its model
there. An NLLB cell therefore rendered as "google gemma-4-31B-it" with a quant,
a parameter count and a 100k context window: the model picker's leftover value,
drawn as fact. Nothing was broken, nothing was empty, and the card was wrong.

A runner added later inherits that by omission, which is why this is a build
step and not a convention. `modelField: None` is a legitimate answer (a custom
cell has only a command) — it just has to be said out loud.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from caravan.admin.runners import RUNNERS, cell_model_ref  # noqa: E402
from caravan.admin.config_builder import CONFIG_FIELDS     # noqa: E402


def main():
    errors = []
    for row in RUNNERS:
        rid = row["id"]
        if "modelField" not in row:
            errors.append(
                f"runner {rid} does not declare modelField — the board would label its\n"
                f"        cells with MODEL_FILE, which belongs to a different runner.\n"
                f"        Name the config key it keeps its model in, or None if it has none.")
            continue
        picker = row.get("sharedPicker")
        if picker not in ("source", "carrier", "aim", "ignored"):
            errors.append(
                f"runner {rid} declares sharedPicker={picker!r}. Say how it relates to the\n"
                f"        editor's shared model picker: source (it launches what the picker\n"
                f"        names), carrier (the picker is the UI for its own field), aim\n"
                f"        (picking an artifact writes its own field), ignored (it reads\n"
                f"        nothing from it — the picker is then hidden for this runner).")
        field = row["modelField"]
        if field is None:
            continue
        if field not in CONFIG_FIELDS:
            errors.append(f"runner {rid} names modelField {field}, which is not a CONFIG_FIELDS entry")
            continue
        # And the lookup must actually reach it: a runner id the dispatcher does
        # not recognise falls back to MODEL_FILE, silently.
        probe = {"RUNNER": rid, "MODEL_FILE": "WRONG"}
        probe[field] = "SENTINEL"      # set last: for llama, field IS MODEL_FILE
        got = cell_model_ref(probe)
        if got != "SENTINEL":
            errors.append(f"runner {rid}: cell_model_ref returned {got!r}, not its own {field}")

    if errors:
        print("runner model fields: FAILED", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1
    named = sum(1 for r in RUNNERS if r.get("modelField"))
    hidden = sum(1 for r in RUNNERS if r.get("sharedPicker") == "ignored")
    print(f"runner model fields OK: {named}/{len(RUNNERS)} runners name a model field, "
          f"{hidden} hide the shared picker")
    return 0


if __name__ == "__main__":
    sys.exit(main())
