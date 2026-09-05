#!/usr/bin/env python3
"""Run the old implementation and the new one side by side, and show where they part.

During the rewrite both live at once: the class is written, the function it
replaces is still there, and the question is always the same — does the new one
answer exactly what the old one answered? Reading both and deciding they look
equivalent is how equivalence gets assumed. This runs them.

The inputs are the golden fixtures — 33 real and synthetic cell configs covering
every runner and all 116 config fields — so a comparison is against what the
fleet actually holds rather than against an example someone invented while
holding the new design in their head.

    scripts/diff_behaviour.py --old caravan.admin.runners:effective_command \\
                              --new caravan.domain.runner:command_for

Both sides are called with one config dict. `module:name` or `module:Class.method`
(the method is called unbound, with the config as its only argument).

Exit code is non-zero when anything differs, so it can gate a swap: while this
is red, the old code stays.
"""
import argparse
import difflib
import importlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests/golden/cells"

# Same pinning as the snapshot: two implementations compared under different
# path assumptions differ on every line for a reason that is not about them.
HOME = "/home/caravan"
for _k, _v in (("LLAMA_HOME", f"{HOME}/llama.cpp"),
               ("LLAMA_MODELS_DIR", f"{HOME}/llama.cpp/models"),
               ("HOME", HOME)):
    os.environ.setdefault(_k, _v)

sys.path.insert(0, str(ROOT))


def resolve(spec):
    """`module:name` or `module:Class.method` → something callable."""
    if ":" not in spec:
        raise SystemExit(f"нужно module:name, получено {spec!r}")
    module_name, attr = spec.split(":", 1)
    obj = importlib.import_module(module_name)
    for part in attr.split("."):
        obj = getattr(obj, part)
    if not callable(obj):
        raise SystemExit(f"{spec} не вызывается")
    return obj


def call(fn, config):
    """Whatever it answers — including the exception, which is also an answer.

    An implementation that raises where the other returns has changed behaviour
    just as surely as one that returns something else, and a harness that let
    the exception through would report the run as broken instead of reporting
    the difference.
    """
    try:
        return "ok", fn(config)
    except Exception as exc:  # noqa: BLE001
        return "raised", f"{type(exc).__name__}: {exc}"


def render(value):
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:  # noqa: BLE001
        return repr(value)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--old", required=True, help="module:name старой реализации")
    ap.add_argument("--new", required=True, help="module:name новой реализации")
    ap.add_argument("--only", default="", help="подстрока в имени фикстуры")
    ap.add_argument("--full", action="store_true", help="полный дифф, не первые строки")
    args = ap.parse_args()

    old_fn, new_fn = resolve(args.old), resolve(args.new)
    fixtures = sorted(FIXTURES.glob("*.json"))
    if args.only:
        fixtures = [f for f in fixtures if args.only in f.stem]
    if not fixtures:
        print("нет фикстур — снимите: python3 scripts/capture_golden.py", file=sys.stderr)
        return 1

    differ = []
    for fixture in fixtures:
        config = json.loads(fixture.read_text(encoding="utf-8"))
        old_kind, old_val = call(old_fn, config)
        new_kind, new_val = call(new_fn, config)
        same = old_kind == new_kind and render(old_val) == render(new_val)
        print(f"  {'ok  ' if same else 'РАЗНО'} {fixture.stem}"
              f"{'' if same else f'   ({old_kind} → {new_kind})'}")
        if not same:
            differ.append(fixture.stem)
            diff = list(difflib.unified_diff(
                render(old_val).splitlines(), render(new_val).splitlines(),
                fromfile="старое", tofile="новое", lineterm=""))
            for line in (diff if args.full else diff[:14]):
                print(f"       {line[:170]}")
            if not args.full and len(diff) > 14:
                print(f"       … ещё {len(diff) - 14} строк (--full)")

    print(f"\n  {len(fixtures) - len(differ)} совпало, {len(differ)} разошлось")
    if differ:
        print(f"  расходятся: {', '.join(differ[:8])}"
              f"{' …' if len(differ) > 8 else ''}", file=sys.stderr)
    return 1 if differ else 0


if __name__ == "__main__":
    sys.exit(main())
