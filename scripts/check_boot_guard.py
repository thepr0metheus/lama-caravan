#!/usr/bin/env python3
"""Every served page carries the inline boot guard, and they all carry the same one.

The guard is the only script on the page that cannot fail to arrive, because it
is not fetched — it is in the document. That is the entire point of it: when
/js/main.js is lost, nothing else runs, and without this the page keeps saying
`data-t-state="loading"` forever, unable to reach `error` because the code that
would set `error` is the code that never came.

Being inline means it is copied per page, and copies drift. This check is the
thing that stops the drift: five identical blocks or CI fails. If you change the
guard, change it in all five — the diff will tell you which one you missed.
"""
import hashlib
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGES = ["static/index.html", "static/kanban.html", "static/models.html",
         "static/hf.html", "static/system.html"]
GUARD = re.compile(r"<script>\s*/\* Inline ON PURPOSE.*?</script>", re.S)


def main():
    problems, digests = [], {}
    for rel in PAGES:
        path = os.path.join(ROOT, rel)
        if not os.path.isfile(path):
            problems.append(f"{rel}: page is gone — drop it from PAGES or restore it")
            continue
        html = io.open(path, encoding="utf-8").read()
        if 'data-t-state="loading"' not in html:
            problems.append(f"{rel}: no data-t-state=\"loading\" on <body>")
        m = GUARD.search(html)
        if not m:
            problems.append(f"{rel}: inline boot guard missing "
                            f"(a lost /js/main.js would strand this page at 'loading')")
            continue
        digests[rel] = hashlib.sha256(m.group(0).encode()).hexdigest()[:12]

    if len(set(digests.values())) > 1:
        problems.append("the guard differs between pages — copies have drifted:")
        for rel, d in sorted(digests.items()):
            problems.append(f"    {d}  {rel}")

    for p in problems:
        print(f"boot guard: {p}", file=sys.stderr)
    if problems:
        return 1
    print(f"boot guard OK: {len(digests)} pages carry the same inline guard "
          f"({next(iter(set(digests.values())))})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
