#!/usr/bin/env python3
"""Снимок: что api() кладёт на провод в качестве тела запроса.

`fetch` приводит незнакомое ему тело через `String()`, поэтому обычный объект
уходит пятнадцатью байтами `[object Object]`. Три вызова на странице системы
делали именно это, и восстановление настроек не работало со дня написания —
молча, потому что страница показывала общий тост об ошибке.

Проверяется НАСТОЯЩИЙ `static/js/utils.js` в node с заглушками `document` и
`fetch`: модуль не имеет импортов, поэтому его можно вызвать как есть.

Запуск: python3 scripts/test_api_body.py
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
    # Причина отказа должна быть ПРАВДОЙ: контроллер флота держит node у nvm,
    # и «на этом хосте нет node» там было неверно — см. scripts/_node.py.
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
