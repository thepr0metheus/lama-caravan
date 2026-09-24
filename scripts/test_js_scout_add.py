#!/usr/bin/env python3
"""Снимок static/js/scout-add.js — поле «＋ Добавить скаута» под Серверами моделей.

Машина только ставит скаут; сопрягает его контроллер. Пинится значениями:
что уходит на провод (адрес и порт как введены), что сказано оператору в
каждом исходе и в каком состоянии блок (data-t-state), что поле адреса
очищается только при успехе, что пустой адрес не уходит никуда, что Enter
в поле — то же нажатие, и что блок связывается один раз.

Подписи берутся из static/js/i18n/en.js программно, а не по памяти.

Запуск: python3 scripts/test_js_scout_add.py
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _js_pins import run  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
EN = (ROOT / "static" / "js" / "i18n" / "en.js").read_text(encoding="utf-8")


def en(key, **kw):
    m = re.search(r'^\s*' + re.escape(key) + r':\s*("(?:[^"\\]|\\.)*"),\s*$', EN, re.M)
    text = json.loads(m.group(1))
    for k, v in kw.items():
        text = text.replace("{" + k + "}", str(v))
    return text


PREAMBLE = r"""
import "./_js_globals.mjs";
import { pathToFileURL } from "node:url";
const sa = await import(pathToFileURL(process.env.JS_ROOT + "/scout-add.js").href);
const part = (value = "") => {
  const handlers = {};
  return { value, disabled: false, textContent: "", focused: false,
           addEventListener(ev, fn) { (handlers[ev] ||= []).push(fn); },
           focus() { this.focused = true; },
           fire(ev, arg) { return Promise.all((handlers[ev] || []).map((fn) => fn(arg))); } };
};
let root, doc;
const reset = () => {
  const parts = { "[data-scout-add-address]": part(), "[data-scout-add-port]": part("8092"),
                  "[data-scout-add-connect]": part(), "[data-scout-add-status]": part() };
  root = { dataset: { tState: "idle" }, parts, querySelector: (sel) => parts[sel] || null };
  doc = { getElementById: (id) => (id === "scoutAdd" ? root : null) };
  globalThis.__fetchCalls.length = 0; globalThis.__fetchReply = {};
};
const P = (sel) => root.parts[sel];
const view = () => ({ state: root.dataset.tState, status: P("[data-scout-add-status]").textContent,
                      address: P("[data-scout-add-address]").value, disabled: P("[data-scout-add-connect]").disabled,
                      calls: globalThis.__fetchCalls.map((c) => ({ path: c.path, method: c.method, body: c.body })) });
"""

DONE = {"ok": True, "hostId": "box-a", "name": "Box A", "scoutVersion": "2.1.0",
        "scoutUrl": "http://10.0.0.5:8092", "controllerUrl": "http://10.0.0.1:7990"}
REFUSED = "no scout answers at http://10.0.0.5:8092: Connection refused — is ./install.sh done there, and is the port open?"

PINS = [
    ("mount_binds_once",
     "",
     "[!!sa.ScoutAddForm.mount(doc), sa.ScoutAddForm.mount(doc), root.dataset.bound, "
     "sa.ScoutAddForm.mount({ getElementById: () => null })]",
     json.dumps([True, None, "1", None]),
     "блок связывается один раз: второй вызов — null; negative: блока на странице нет — null, не падение"),
    ("connect_ok",
     f"globalThis.__fetchReply['/api/topology/scout/connect'] = {json.dumps(DONE)};"
     " sa.ScoutAddForm.mount(doc); P('[data-scout-add-address]').value = ' 10.0.0.5 ';",
     "await (async () => { await root.parts['[data-scout-add-connect]'].fire('click'); return view(); })()",
     json.dumps({"state": "ok", "status": en("scoutAddDone", name="Box A", version="2.1.0"), "address": "",
                 "disabled": False,
                 "calls": [{"path": "/api/topology/scout/connect", "method": "POST",
                            "body": "{\"address\":\"10.0.0.5\",\"port\":\"8092\"}"}]}, ensure_ascii=False),
     "подключено: на провод адрес без пробелов и порт как введён; блок «ok» с именем машины и версией скаута; поле адреса очищено"),
    ("connect_refused",
     f"globalThis.__fetchReply['/api/topology/scout/connect'] = {{ __status: 502, error: {json.dumps(REFUSED)} }};"
     " sa.ScoutAddForm.mount(doc); P('[data-scout-add-address]').value = '10.0.0.5';",
     "await (async () => { await root.parts['[data-scout-add-connect]'].fire('click'); return view(); })()",
     json.dumps({"state": "error", "status": REFUSED, "address": "10.0.0.5", "disabled": False,
                 "calls": [{"path": "/api/topology/scout/connect", "method": "POST",
                            "body": "{\"address\":\"10.0.0.5\",\"port\":\"8092\"}"}]}, ensure_ascii=False),
     "negative: сервер отказал — его слова в строке, блок «error», адрес остаётся для исправления, кнопка снова доступна"),
    ("connect_empty_address",
     "sa.ScoutAddForm.mount(doc);",
     "await (async () => { await root.parts['[data-scout-add-connect]'].fire('click'); "
     "return { ...view(), focused: P('[data-scout-add-address]').focused }; })()",
     json.dumps({"state": "error", "status": en("scoutAddEmpty"), "address": "", "disabled": False, "calls": [],
                 "focused": True}, ensure_ascii=False),
     "negative: адрес пуст — никуда не уходит, сказано «введите адрес», фокус в поле"),
    ("enter_key_connects",
     f"globalThis.__fetchReply['/api/topology/scout/connect'] = {json.dumps(DONE)};"
     " sa.ScoutAddForm.mount(doc); P('[data-scout-add-address]').value = 'gpu-box.lan'; P('[data-scout-add-port]').value = '9000';",
     "await (async () => { await P('[data-scout-add-port]').fire('keydown', { key: 'Enter' }); "
     "await P('[data-scout-add-address]').fire('keydown', { key: 'a' }); return view().calls; })()",
     json.dumps([{"path": "/api/topology/scout/connect", "method": "POST",
                  "body": "{\"address\":\"gpu-box.lan\",\"port\":\"9000\"}"}]),
     "Enter в поле порта — то же нажатие, с его портом; negative: другая клавиша ничего не шлёт"),
]

if __name__ == "__main__":
    sys.exit(run("js scout-add", ".probe_js_scout_add.tmp.mjs", PREAMBLE, PINS,
                 stubs="topology-render,canvas,topology-dnd,topology-modals,cables,routers,cloud,dialogs"))
