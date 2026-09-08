#!/usr/bin/env python3
"""A field that rides through several rebuilds must be NAMED in every one of them.

A client proxy cell's setting travels from the controller's document to the
proxy's response, and along the way it gets REBUILT four times: the record's
form class, the normalizer on writing a route, the normalizer on reading a
route, and the bridge that carries a copy from an assignment to a route. Each
rebuild constructs a dict from scratch, so a field it doesn't name
disappears — silently, with no error — and gets noticed a layer or two later,
when a client gets something other than what the operator set.

This happened FOUR times in a row during a single piece of work. The first
three were caught by a red pin, the fourth only because the first three had
taught the search. The field list and the boundary list live here, and the
guard requires every field to be named at every boundary.

This used to say "there won't be a fifth". There was a fifth — and this guard
missed it: the proxy reconcile built the assignment record AGAIN from a
client's live report, and the hand-written boundary list knew nothing about
it and printed green. A hand-written list goes stale silently — this was
already proven on the list of scripts in CI. So a rule was added below that
catches not a listed location but the SHAPE of the defect itself: building an
assignment from scratch where a saved record sits right next to it.

The guard fails TWO ways. On the defect itself: a field isn't named
everywhere. And when it stops finding anything to check: a boundary
disappeared, moved, or was renamed — then it doesn't stay silent, it says
there's nothing left to check.

Run: python3 scripts/check_carried_fields.py
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: Fields that must survive the whole path. Add such a field — write it in
#: here, and the guard will immediately say at which boundary you forgot to
#: name it.
CARRIED_FIELDS = ("contextLength", "contextAuto", "modelName", "modelNameAuto")

#: Rebuild boundaries: file → the function that constructs the record again.
#: The function isn't named for style — it's what the check verifies the
#: boundary against.
REBUILD_BOUNDARIES = {
    "caravan/domain/client_proxy.py": "to_dict",
    "caravan/admin/router_dsl.py": "normalize_agent_proxy_route",
    "caravan/proxy/config.py": "normalize_route",
    "caravan/admin/fleet_clients.py": "reconcile_proxy_metadata",
}

#: Below this many boundaries the check is meaningless: it means the list has
#: fallen behind the code.
MIN_BOUNDARIES = 4


def _emitted_keys(source, func_name):
    """Names the function PUTS into the record it's building, or None if it
    doesn't exist.

    Two spellings count, and only these: a dict literal's key
    (``{"field": ...}``) and the target of a keyed assignment
    (``out["field"] = ...``). Any other mention doesn't count as naming a
    field, and this isn't pedantry — both previous versions of this guard
    stayed green on a broken tree: the first was satisfied by the word
    appearing in a COMMENT, the second by READING the field from the input
    (``route.get("field")``), which stays in place even after the record has
    been renamed. What must be checked is what gets put in, not what's
    written nearby.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    target = next((n for n in ast.walk(tree)
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == func_name), None)
    if target is None:
        return None
    keys = set()
    for node in ast.walk(target):
        if isinstance(node, ast.Dict):
            keys |= {k.value for k in node.keys
                     if isinstance(k, ast.Constant) and isinstance(k.value, str)}
        elif isinstance(node, (ast.Assign, ast.AugAssign)):
            for tgt in (node.targets if isinstance(node, ast.Assign) else [node.target]):
                for sub in ast.walk(tgt):
                    if (isinstance(sub, ast.Subscript) and isinstance(sub.slice, ast.Constant)
                            and isinstance(sub.slice.value, str)):
                        keys.add(sub.slice.value)
    return keys


#: Where the record-form classes live: constructing a record from scratch
#: inside them is their job, outside them it's a defect.
DOMAIN_DIR = "caravan/domain/"

#: Constructors that CARRY OVER what's already saved. Everything else builds
#: an assignment from scratch and drops whatever wasn't named.
CARRYING_CONSTRUCTORS = ("from_raw", "rewired")


def _bare_assignment_builds():
    """Places outside the domain where `AgentAssignment(...)` is called directly.

    The fifth boundary looked exactly like this: `AgentAssignment(aid,
    [route])` right next to `existing[aid]`, from which nothing was taken.
    The class was handed only what the live report knows — and everything
    the operator had set was gone.
    """
    hits, call_sites = [], 0
    for path in sorted(ROOT.glob("caravan/**/*.py")):
        rel = path.relative_to(ROOT).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            # A file that fails to parse is NOT "nothing to see here". The
            # first version of this rule silently skipped such a file, and a
            # mutant that broke parsing left the guard green: exactly the
            # absence-drawn-as-normal case this whole guard exists to catch.
            hits.append(f"{rel}: не разбирается ({exc.msg}, строка {exc.lineno}) — "
                        f"проверить сборку назначения в нём нечем")
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) \
                    and func.value.id == "AgentAssignment":
                call_sites += 1
                if rel.startswith(DOMAIN_DIR) or func.attr in CARRYING_CONSTRUCTORS:
                    continue
                hits.append(f"{rel}:{node.lineno}: AgentAssignment.{func.attr}(…) — "
                            f"не переносящий конструктор")
            elif isinstance(func, ast.Name) and func.id == "AgentAssignment":
                call_sites += 1
                if rel.startswith(DOMAIN_DIR):
                    continue
                hits.append(f"{rel}:{node.lineno}: назначение собирается с нуля — "
                            f"возьми {' или '.join(CARRYING_CONSTRUCTORS)}, иначе всё, "
                            f"что задал оператор, исчезнет")
    return hits, call_sites


def main():
    problems = []
    checked = 0
    for rel, marker in sorted(REBUILD_BOUNDARIES.items()):
        path = ROOT / rel
        if not path.exists():
            problems.append(f"{rel}: граница исчезла — файла нет")
            continue
        emitted = _emitted_keys(path.read_text(encoding="utf-8"), marker)
        if emitted is None:
            problems.append(f"{rel}: не найдена функция «{marker}» — граница переехала или "
                            f"переименована, и гвард больше не знает, что проверять")
            continue
        checked += 1
        for field in CARRIED_FIELDS:
            if field not in emitted:
                problems.append(f"{rel}: «{marker}» не называет поле «{field}» — эта пересборка его уронит")
    bare, call_sites = _bare_assignment_builds()
    problems.extend(bare)
    if call_sites < 3:
        problems.append(f"вызовов AgentAssignment найдено {call_sites} — класс переехал или "
                        f"переименован, и правило о сборке с нуля больше ничего не проверяет")
    if checked < MIN_BOUNDARIES:
        problems.append(f"границ осмотрено {checked}, ожидалось не меньше {MIN_BOUNDARIES}: "
                        f"список в этом гварде отстал от кода")
    if problems:
        print("carried fields FAILED:")
        for p in problems:
            print("  - " + p)
        print("\nПоле, едущее через пересборки, должно быть названо в каждой: "
              "иначе оно исчезает молча (docs/why.md).")
        return 1
    print(f"carried fields OK: {len(CARRIED_FIELDS)} полей названы на всех {checked} границах "
          f"пересборки; {call_sites} сборок назначения — все переносящие")
    return 0


if __name__ == "__main__":
    sys.exit(main())
