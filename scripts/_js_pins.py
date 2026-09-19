"""Runs a JS snapshot: pins evaluated in node against the real module, twice.

A pin is (id, setup, expression, expected JSON, message). The probe runs every
pin once in order and once in reverse: a pin whose value depends on the pins
before it is a pin that tests the order, not the module, and fails as such.
The loader (_js_harness.mjs) serves the modules named in `stubs` as stubs.
"""
import json
import os
import subprocess
from pathlib import Path

from _node import find_node, node_search_paths

ROOT = Path(__file__).resolve().parent.parent


def run(label, tmp_name, preamble, pins, stubs=""):
    node = find_node()
    if not node:
        print(f"{label}: SKIPPED — node не найден: " + ", ".join(node_search_paths()))
        return 0

    def blocks(items, sink):
        return [f"try {{ reset(); {setup}\n  {sink}[{json.dumps(pid)}] = {expr}; }} "
                f"catch (e) {{ {sink}[{json.dumps(pid)}] = {{ __threw: String(e && e.stack || e) }}; }}"
                for pid, setup, expr, _exp, _msg in items]

    probe = (preamble + "\nconst out = {};\n" + "\n".join(blocks(pins, "out")) + "\nconst rev = {};\n"
             + "\n".join(blocks(list(reversed(pins)), "rev"))
             + "\nconsole.log(JSON.stringify({ out, rev })); process.exit(0);\n")
    harness = ROOT / "scripts" / "_js_harness.mjs"
    path = ROOT / "scripts" / tmp_name
    path.write_text(probe, encoding="utf-8")
    try:
        env = {**os.environ, "JS_ROOT": str(ROOT / "static" / "js"), "JS_STUBS": stubs,
               "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8", "TZ": "UTC"}
        done = subprocess.run(
            [node, "--import", f"data:text/javascript,import {{ register }} from 'node:module'; register('{harness.as_uri()}');",
             str(path)], capture_output=True, text=True, env=env, cwd=ROOT, timeout=180)
    finally:
        path.unlink(missing_ok=True)
    if done.returncode != 0:
        print(done.stdout)
        print(done.stderr)
        print(f"{label} FAILED: node вышел с кодом {done.returncode}")
        return 1
    both = json.loads(done.stdout.strip().splitlines()[-1])
    got, rev = both["out"], both["rev"]
    failed = []
    for pid, _s, _e, expected, msg in pins:
        want, have = json.loads(expected), got.get(pid, "\0missing")
        ok = have == want
        print(f"  {'ok  ' if ok else 'FAIL'} {msg}")
        if not ok:
            print(f"        ожидалось {json.dumps(want, ensure_ascii=False)[:400]}")
            print(f"        получено  {json.dumps(have, ensure_ascii=False)[:400]}")
            failed.append(msg)
        if have != rev.get(pid, "\0missing"):
            failed.append(f"пин {pid} зависит от порядка")
            print(f"  FAIL пин {pid} зависит от порядка: в обратном порядке {json.dumps(rev.get(pid), ensure_ascii=False)[:300]}")
    print()
    if failed:
        print(f"{label} FAILED ({len(failed)}):")
        for msg in failed:
            print("  - " + msg.splitlines()[0])
        return 1
    print(f"{label} OK: настоящий модуль в node, {len(pins)} пинов значениями")
    return 0
