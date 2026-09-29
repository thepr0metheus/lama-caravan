#!/usr/bin/env python3
"""Every route says what it does, and docs/http-api.md says the same.

/openapi.json is built from the route tables and the handlers' docstrings
(caravan/admin/api_spec.py). A route whose handler has no docstring is a
route the description cannot name: a test suite reading /openapi.json sees a
path with an empty summary and nothing to go on. This fails on that, on a
summary too long to be one line, and on a draft left marked "UNSURE".

docs/http-api.md carries the same list for people, between two markers. It
was written by hand until 2026-09-29 and had fallen 16 paths behind the 164
it covered; now it is rendered from the document, and this fails when the
page and the code disagree. `--write` renders it again.

Run: python3 scripts/check_api_spec.py [--write]
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "http-api.md"
MAX_SUMMARY = 90

os.environ.setdefault("CARAVAN_DATA_DIR", tempfile.mkdtemp(prefix="caravan-api-spec-"))
sys.path.insert(0, str(ROOT))

from caravan.admin import routes  # noqa: E402
from caravan.admin.api_spec import ApiReference  # noqa: E402


def problems_in(document):
    problems = []
    for path, ops in document["paths"].items():
        for method, op in ops.items():
            where = f"{method.upper()} {path} ({op['x-caravan-handler']})"
            summary = op.get("summary") or ""
            if not summary:
                problems.append(f"{where}: the handler has no docstring — say what the route does")
            elif len(summary) > MAX_SUMMARY:
                problems.append(f"{where}: the summary is {len(summary)} characters, over {MAX_SUMMARY} "
                                f"— the first line is one line; the rest goes after a blank line")
            if "UNSURE" in (summary + " " + (op.get("description") or "")).upper():
                problems.append(f"{where}: a draft left marked UNSURE — find out, then say it")
    return problems


def main(argv):
    write = "--write" in argv
    document = routes.API_SPEC.build()
    problems = problems_in(document)
    text = DOC.read_text(encoding="utf-8")
    try:
        rendered = ApiReference(document).splice(text)
    except ValueError as exc:
        problems.append(str(exc))
        rendered = text
    if rendered != text:
        if write:
            DOC.write_text(rendered, encoding="utf-8")
            print(f"check_api_spec: {DOC.relative_to(ROOT)} rendered again")
        else:
            problems.append(f"{DOC.relative_to(ROOT)} does not say what the handlers say — "
                            f"run: python3 scripts/check_api_spec.py --write")
    operations = sum(len(ops) for ops in document["paths"].values())
    if problems:
        print(f"check_api_spec: FAILED — {len(problems)} of {operations} operations or pages:")
        for line in problems:
            print("  - " + line)
        return 1
    print(f"check_api_spec OK: {operations} operations, each says what it does; {DOC.name} matches")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
