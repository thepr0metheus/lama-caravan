#!/usr/bin/env python3
"""Value snapshot: the one name for the cloud providers on Routing (static/js/client-name-settings.js; 1.3.692).

The owner, 2026-10-31: "let us present ourselves as one". The rule of what can be a name is the server's alone
(rust/crates/rules/src/client_name.rs); here, with the real module in node and the words from en.js:
  * the button says which: each client's own name, or the one that is set;
  * the field opens under it, holds what the controller keeps, says what filling it means, and is closed unless asked for;
  * a value let go is saved as the proxy's policy as it was typed; a refusal says the controller's words and the field goes back;
  * a name reaches the page escaped, and a second save waits for the first.

Run: python3 scripts/test_js_client_name.py
"""
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _node import find_node, node_search_paths, probe_args  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


PROBE = r'''
import "./_js_globals.mjs";
const { ClientNameSettings } = await import("../static/js/client-name-settings.js");
const NAME = "pi (linux; x64)", ODD = 'a"><b>';
const calls = [], notes = [];
let answer = async (path, o) => { calls.push([path, JSON.parse(o.body)]); return { ok: true, config: { policy: { clientName: NAME } } }; };
const settings = new ClientNameSettings({ call: (...a) => answer(...a), notify: (x) => notes.push(x) });
const shutButton = settings.buttonHtml({}), shutPanel = settings.panelHtml({ clientName: NAME });
settings.open = true;
const openButton = settings.buttonHtml({ clientName: NAME }), panel = settings.panelHtml({ clientName: NAME }), emptyPanel = settings.panelHtml({}), odd = [settings.buttonHtml({ clientName: ODD }), settings.panelHtml({ clientName: ODD })];
const field = { value: "  typed  " };
const reply = await settings.save(field, { clientName: NAME });
const refused = { value: "bad" };
answer = async () => { throw new Error("the controller's words"); };
const none = await settings.save(refused, { clientName: NAME });
const emptied = { value: "bad" };
await settings.save(emptied, {});
const held = [];
let free;
answer = (path, o) => { held.push(JSON.parse(o.body)); return new Promise((resolve) => { free = () => resolve({ ok: true }); }); };
const first = settings.save({ value: "one" }, {});
const whileSaving = settings.panelHtml({}).includes(" disabled");
const second = await settings.save({ value: "two" }, {});
free();
await first;
console.log(JSON.stringify({
  pills: [ClientNameSettings.pill({}), ClientNameSettings.pill(null), ClientNameSettings.pill({ clientName: NAME })],
  shut: [shutButton.includes('aria-expanded="false" data-t="pb-client-name-open"'), shutButton.includes(">Seen as: own names</button>"), shutButton.includes(" open\""), shutPanel],
  open: [openButton.includes('aria-expanded="true"'), openButton.includes("pb-name-pill open"), openButton.includes(">Seen as: " + NAME + "</button>")],
  panel: [panel.includes('data-t="pb-client-name-panel"'), panel.includes('value="' + NAME + '"'), panel.includes("Kimi does"), panel.includes(" disabled"),
    emptyPanel.includes('value=""'), emptyPanel.includes('placeholder="each client&#39;s own name"') || emptyPanel.includes("placeholder=\"each client's own name\"")],
  odd: odd.map((h) => h.includes(ODD)),
  saved: [calls, reply?.config?.policy, notes[0], field.value],
  refused: [none, refused.value, notes[1], emptied.value],
  guard: [held, second, whileSaving, settings.saving],
}));
'''


def main():
    node = find_node()
    if node is None:
        print("js client name: SKIPPED — node не найден ни в PATH, ни у менеджеров версий: " + ", ".join(node_search_paths()))
        return 0
    probe = ROOT / "scripts" / ".probe_client_name.tmp.mjs"
    probe.write_text(PROBE, encoding="utf-8")
    try:
        env = {**os.environ, "JS_ROOT": str(ROOT / "static" / "js"), "JS_STUBS": "form", "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8", "TZ": "UTC"}
        proc = subprocess.run(probe_args(node, ROOT / "scripts" / "_js_harness.mjs", probe), capture_output=True, text=True, cwd=ROOT, env=env, timeout=90)
    finally:
        probe.unlink(missing_ok=True)
    if proc.returncode != 0:
        print("js client name: FAILED — харнесс не отработал")
        print(proc.stderr[-2000:])
        return 1
    got = json.loads(proc.stdout.strip().splitlines()[-1])

    print("имя для облачных провайдеров на Маршрутизации:")
    name = "pi (linux; x64)"
    check(got["pills"] == ["Seen as: own names", "Seen as: own names", f"Seen as: {name}"], "кнопка говорит, какое имя видят провайдеры; negative: политики нет — свои имена, а не пусто")
    check(got["shut"] == [True, True, False, ""], "negative: закрытая кнопка — поля нет")
    check(got["open"] == [True, True, True], "открытая кнопка так и сказано, и на ней заданное имя")
    check(got["panel"] == [True, True, True, False, True, True], "поле: то, что хранит контроллер, подсказка говорит о нарушении и блокировке; пустое — подсказка «своё имя у каждого»")
    check(got["odd"] == [False, False], "negative: имя с разметкой не становится разметкой ни на кнопке, ни в поле")
    calls, policy, note, typed = got["saved"]
    check(calls == [["/api/agent-proxies/policy", {"policy": {"clientName": "  typed  "}}]] and policy == {"clientName": name} and note == "Saved: the name providers see" and typed == "  typed  ",
          "отпущенное поле уходит в политику прокси как напечатано: правило имени у сервера, копии правила здесь нет")
    none, refused, words, emptied = got["refused"]
    check(none is None and refused == name and words == "the controller's words" and emptied == "",
          "negative: отказ сервера сказан его словами, поле вернулось к тому, что он хранит (к пустому, если имени нет)")
    held, second, while_saving, saving = got["guard"]
    check(held == [{"policy": {"clientName": "one"}}] and second is None and while_saving is True and saving is False,
          "negative: пока идёт сохранение, второе не уходит и поле закрыто; после него снято")
    print()
    if _fail:
        print(f"js client name FAILED ({len(_fail)}):")
        for msg in _fail:
            print("  - " + msg)
        return 1
    print("js client name OK: the button, the field, its saving and refusal")
    return 0


if __name__ == "__main__":
    sys.exit(main())
