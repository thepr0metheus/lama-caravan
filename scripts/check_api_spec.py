#!/usr/bin/env python3
"""Every route says what it does, and docs/http-api.md says the same.

/openapi.json is the program's own file, rust/crates/admin/src/routes/openapi.json. An operation with no summary is a route the description cannot name: a test suite reading
/openapi.json sees a path with an empty summary and nothing to go on. This fails on that, on a summary too long to be one line, and on a draft left marked "UNSURE". That
every route is in the file and nothing else is: rust/crates/admin/tests/contract.rs.

docs/http-api.md carries the same list for people, between two markers. It was written by hand until 2026-09-29 and had fallen 16 paths behind the 164 it covered; now it is
rendered from the document, and this fails when the page and the document disagree. `--write` renders it again.

Run: python3 scripts/check_api_spec.py [--write]
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "http-api.md"
SPEC = ROOT / "rust" / "crates" / "admin" / "src" / "routes" / "openapi.json"
MAX_SUMMARY = 90


class ApiReference:
    """docs/http-api.md's endpoint list, rendered from the document between two markers. The page people read and /openapi.json say the same thing: the page used to be
    written by hand, and fell 16 paths behind."""

    START = ("<!-- api-reference:start — generated from rust/crates/admin/src/routes/openapi.json by "
             "`python3 scripts/check_api_spec.py --write`; edit that file, not this -->")
    END = "<!-- api-reference:end -->"

    def __init__(self, document):
        self.document = document

    def access_label(self, op):
        security = op.get("security")
        if security == []:
            return "open"
        names = [name for item in security or [] for name in item]
        if "session" in names and len(names) > 1:
            return "fleet token or session"
        if "fleetToken" in names:
            return "fleet token"
        roles = op.get("x-caravan-roles") or []
        return "any account" if "viewer" in roles else "admin"

    def inputs(self, op):
        parts = []
        query = [p["name"] for p in op.get("parameters", []) if p["in"] == "query"]
        path = [p["name"] for p in op.get("parameters", []) if p["in"] == "path"]
        if path:
            parts.append("path: " + ", ".join(f"`{n}`" for n in path))
        if query or op.get("x-caravan-query-complete") is False:
            listed = ", ".join(f"`{n}`" for n in query) or "—"
            parts.append("query: " + listed + (" …" if op.get("x-caravan-query-complete") is False else ""))
        body = (op.get("requestBody") or {}).get("content", {}).get("application/json", {}).get("schema")
        if body is not None:
            listed = ", ".join(f"`{n}`" for n in body.get("properties", {})) or "—"
            parts.append("body: " + listed + (" …" if body.get("x-caravan-fields-complete") is False else ""))
        return "; ".join(parts)

    @staticmethod
    def cell(text):
        return " ".join(str(text).split()).replace("|", "\\|")

    def table(self):
        lines = ["| Method & path | Access | Reads | What it does |", "|---|---|---|---|"]
        for path, ops in self.document["paths"].items():
            for method, op in ops.items():
                words = op["summary"] + (". " + op["description"] if op.get("description") else "")
                lines.append(f"| `{method.upper()} {path}` | {self.access_label(op)} | "
                             f"{self.cell(self.inputs(op))} | {self.cell(words)} |")
        return "\n".join(lines)

    def block(self):
        return f"{self.START}\n\n{self.table()}\n\n{self.END}"

    def splice(self, text):
        """`text` with the block between the markers replaced; ValueError when the markers are missing — a page without them is not ours to rewrite."""
        start = text.find("<!-- api-reference:start")
        end = text.find(self.END)
        if start < 0 or end < start:
            raise ValueError("docs/http-api.md has no api-reference markers")
        return text[:start] + self.block() + text[end + len(self.END):]


def problems_in(document):
    problems = []
    for path, ops in document["paths"].items():
        for method, op in ops.items():
            where = f"{method.upper()} {path}"
            summary = op.get("summary") or ""
            if not summary:
                problems.append(f"{where}: no summary — say what the route does")
            elif len(summary) > MAX_SUMMARY:
                problems.append(f"{where}: the summary is {len(summary)} characters, over {MAX_SUMMARY} — the first line is one line; the rest goes in its description")
            if "UNSURE" in (summary + " " + (op.get("description") or "")).upper():
                problems.append(f"{where}: a draft left marked UNSURE — find out, then say it")
    return problems


def main(argv):
    write = "--write" in argv
    document = json.loads(SPEC.read_text(encoding="utf-8"))
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
            problems.append(f"{DOC.relative_to(ROOT)} does not say what the document says — run: python3 scripts/check_api_spec.py --write")
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
