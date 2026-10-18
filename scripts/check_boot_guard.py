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

The guard also says where a page that did not boot stood still (1.3.542): the step the boot
last reported, `window.__bootWaiting`. Two files must agree on that name — the guard reads it,
static/js/boot-step.js writes it — and the writer must run FIRST: main.js imports it before
any other module, so a module graph that never finishes loading still leaves its first word
behind; and main.js must name its steps (the guard's words for where the boot stands are these).
How the guard behaves is test_boot_guard.py's.
"""
import hashlib
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGES = ["static/index.html", "static/routing.html", "static/models.html",
         "static/hf.html", "static/system.html"]
GUARD = re.compile(r"<script>\s*/\* Inline ON PURPOSE.*?</script>", re.S)
MAIN = "static/js/main.js"
BOOT_STEP = "static/js/boot-step.js"
#: What the boot says it is waiting for, in main.js, and how many times: each is a sentence of the banner a person reads. The
#: topology is waited for twice — by Routing's page and by the board's.
STEPS = {"the language files": 1, "the page's own setup": 1, "/api/state": 1, "/api/topology": 2}


def step_problems():
    """The guard and the boot agree on the name of the step, and the boot says its steps first and in full."""
    bad = []
    step_path, main_path, page = (os.path.join(ROOT, rel) for rel in (BOOT_STEP, MAIN, PAGES[0]))
    if not (os.path.isfile(step_path) and os.path.isfile(main_path)):
        return [f"{BOOT_STEP} or {MAIN} is gone — the banner cannot say where the boot stood"]
    step = io.open(step_path, encoding="utf-8").read()
    main = io.open(main_path, encoding="utf-8").read()
    guard = GUARD.search(io.open(page, encoding="utf-8").read())
    wrote = set(re.findall(r"window\.(__\w+)\s*=", step))
    read = set(re.findall(r"window\.(__\w+)", guard.group(0))) if guard else set()
    if not wrote or wrote != read:
        bad.append(f"{BOOT_STEP} writes {sorted(wrote) or 'nothing'} and the guard reads {sorted(read) or 'nothing'}: one name, or the banner is silent")
    if 'BootStep.waitsFor("the other scripts to load");' not in step:
        bad.append(f"{BOOT_STEP}: it does not say its own word at once — a graph that never finishes loading would leave none")
    first = re.search(r"^import .*$", main, re.M)
    if not first or "./boot-step.js" not in first.group(0):
        bad.append(f"{MAIN}: its first import is not ./boot-step.js — a module graph that never loads would leave no word behind")
    for name, times in STEPS.items():
        said = len(re.findall(r"BootStep\.waitsFor\(\"" + re.escape(name) + r"\"\)", main))
        if said < times:
            bad.append(f"{MAIN}: the boot says it waits for \"{name}\" {said} time(s), not {times}")
    return bad


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

    problems += step_problems()

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
