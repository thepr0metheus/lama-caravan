#!/usr/bin/env python3
"""CI guard: every cell server says what it DOES in one vocabulary.

`kinds` is the only thing a LAN consumer can choose a cell by, and the cells
grew their own spellings before there was a vocabulary: whisper said
"stt.whisper", transcribe said "asr", and those are the same job written two
ways. A consumer matching on the job then found one of them and missed the
other — while nothing looked wrong from either side.

The rule: at least one BARE job word from caravan/common/model_jobs.JOBS,
optionally with a dotted refinement naming the engine ("stt.whisper" beside
"asr"). The bare word is what a consumer choosing by job matches on; the dotted
one is for a consumer that already knows the engine.

Unknown words are refused rather than ignored: a kind nobody can read is
indistinguishable from a cell that said nothing, which is how "seamless is a
recognizer" survived — it claimed "asr" while its own docstring said it never
produces a transcript.

Output is Russian on purpose: it is read by the operator running the guards.
"""
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from caravan.common.model_jobs import JOBS  # noqa: E402

CELLS = ROOT / "cells"

#: Dotted refinements are engine names under a job prefix. The prefix must be a
#: job word or its alias, so "stt.whisper" is legal and "magic.whisper" is not.
PREFIX_ALIASES = {"stt": "asr"}


def _as_text(node):
    """One list element as text. An f-string keeps its literal head and marks
    the hole: `f"tts.{self.engine}"` reads as "tts.*", which is all this guard
    needs — the job is the part before the dot, and the engine is the cell's
    business."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        out = ""
        for part in node.values:
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                out += part.value
            else:
                out += "*"
        return out
    return None


def declared_kinds(path):
    """What a cell server declares as `kinds`, read from the source.

    BOTH shapes, because both are live: a plain class attribute (whisper,
    moonshine…) and a `@property` returning a list (the TTS cell, whose kind
    carries the engine it was started with). Reading only the first shape is
    how this guard's first run declared the TTS cell silent when it was not.

    Parsed rather than imported: importing a cell server drags in torch and the
    engine it wraps, which is not something a guard on the controller can do.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            if "kinds" not in [t.id for t in node.targets if isinstance(t, ast.Name)]:
                continue
        elif isinstance(node, ast.FunctionDef) and node.name == "kinds":
            returns = [n for n in ast.walk(node) if isinstance(n, ast.Return)]
            node = type("_V", (), {"value": returns[-1].value})() if returns else None
            if node is None:
                return None
        else:
            continue
        value = getattr(node, "value", None)
        if not isinstance(value, (ast.List, ast.Tuple)):
            return None            # computed some other way — reported by the caller
        items = [_as_text(el) for el in value.elts]
        if any(i is None for i in items):
            return None
        return items
    return []


def main() -> int:
    problems = []
    checked = 0
    for path in sorted(CELLS.glob("*_server.py")):
        kinds = declared_kinds(path)
        rel = path.relative_to(ROOT)
        if kinds is None:
            problems.append(f"{rel}: kinds собирается на ходу — гвард не может его прочитать")
            continue
        if not kinds:
            problems.append(f"{rel}: не объявлен kinds — ячейку не найти по работе, "
                            f"только по движку")
            continue
        checked += 1
        bare = [k for k in kinds if "." not in k]
        for k in kinds:
            head = k.split(".")[0]
            job = PREFIX_ALIASES.get(head, head)
            if job not in JOBS:
                problems.append(f"{rel}: «{k}» не из словаря работ "
                                f"({', '.join(JOBS)}) — такое слово читатель пропустит")
            if "." in k and not re.fullmatch(r"[a-z0-9-]+\.[a-z0-9._*-]+", k):
                problems.append(f"{rel}: «{k}» — не «работа.движок»")
        if not any(PREFIX_ALIASES.get(k, k) in JOBS for k in bare):
            problems.append(f"{rel}: нет ни одного ГОЛОГО слова работы "
                            f"(есть только {kinds}) — по работе ячейку не выбрать")

    for p in problems:
        print(f"  - {p}", file=sys.stderr)
    if problems:
        print(f"\nсловарь работ живёт в caravan/common/model_jobs.py (JOBS); "
              f"голое слово — то, по чему ячейку выбирают, точечное — уточнение движка",
              file=sys.stderr)
        return 1
    print(f"cell kinds OK: {checked} ячеек называют работу словами из одного словаря")
    return 0


if __name__ == "__main__":
    sys.exit(main())
