#!/usr/bin/env python3
"""Snapshot: what api() puts on the wire as a request body.

`fetch` coerces a body it doesn't recognize through `String()`, so a plain
object goes out as the fifteen bytes `[object Object]`. Three calls on the
system page did exactly this, and settings restore had not worked since the
day it was written — silently, because the page showed a generic error toast.

Exercises the REAL `static/js/utils.js` in node with stubs for `document` and
`fetch`: the module has no imports, so it can be called as-is.

Run: python3 scripts/test_api_body.py
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _node import find_node, node_search_paths  # noqa: E402

HARNESS = r"""
globalThis.document = { getElementById: () => null };
globalThis.window = globalThis;
globalThis.location = { pathname: "/x" };
let seen = null;
globalThis.fetch = async (path, opts) => {
  seen = opts && "body" in opts ? opts.body : null;
  return { ok: true, status: 200, json: async () => ({}) };
};
const m = await import(process.argv[1]);
const out = {};
await m.api("/x", { method: "POST", body: { secrets: false, passphrase: "p" } });
out.object = typeof seen === "string" ? seen : String(seen);
await m.api("/x", { method: "POST", body: JSON.stringify({ a: 1 }) });
out.string = seen;
await m.api("/x", { method: "POST", body: new URLSearchParams({ a: "1" }) });
out.searchParams = seen && seen.constructor ? seen.constructor.name : String(seen);
await m.api("/x", { method: "POST", body: "" });
out.emptyString = seen;
await m.api("/x", { method: "GET" });
out.noBody = seen === null ? "absent" : String(seen);
await m.api("/x", { method: "POST", body: [1, 2] });
out.array = seen;
console.log(JSON.stringify(out));
"""

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


NODE = find_node()
if NODE is None:
    # The failure reason has to be TRUE: the fleet's controller keeps node
    # under nvm, and "no node on this host" was wrong there — see scripts/_node.py.
    print("api body: SKIPPED — node не найден ни в PATH, ни у менеджеров версий: "
          + ", ".join(node_search_paths()))
    sys.exit(0)

proc = subprocess.run(
    [NODE, "--input-type=module", "-e", HARNESS, str(ROOT / "static" / "js" / "utils.js")],
    capture_output=True, text=True, timeout=60)
if proc.returncode != 0:
    print("api body: FAILED — харнесс не отработал")
    print(proc.stderr.strip()[:600])
    sys.exit(1)

got = json.loads(proc.stdout.strip().splitlines()[-1])
print("api(): что уходит на провод:")
check(got["object"] == '{"secrets":false,"passphrase":"p"}',
      f"обычный объект сериализуется (получено {got['object']!r})")
check(got["object"] != "[object Object]",
      "и НЕ превращается в пятнадцать байт [object Object]")
check(got["string"] == '{"a":1}', f"готовая строка не трогается (получено {got['string']!r})")
check(got["searchParams"] == "URLSearchParams",
      f"URLSearchParams уходит как есть, не в JSON (получено {got['searchParams']!r})")
check(got["emptyString"] == "", "пустая строка остаётся пустой строкой")
check(got["noBody"] == "absent", f"без тела ничего не добавляется (получено {got['noBody']!r})")
check(got["array"] == "[1,2]", f"список тоже сериализуется (получено {got['array']!r})")

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail:
        print("  - " + m)
    sys.exit(1)
print("api body OK: тело запроса уходит на провод сериализованным")
