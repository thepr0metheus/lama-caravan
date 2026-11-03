#!/usr/bin/env python3
"""Снимок static/js/scout-add.js — ящик «＋ Добавить скаута» под заголовком «Машины».

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
  return { value, disabled: false, textContent: "", focused: false, hidden: false, dataset: {}, innerHTML: "", attrs: {},
           addEventListener(ev, fn) { (handlers[ev] ||= []).push(fn); },
           setAttribute(k, v) { this.attrs[k] = v; },
           focus() { this.focused = true; },
           fire(ev, arg) { return Promise.all((handlers[ev] || []).map((fn) => fn(arg))); } };
};
// A read the box started by itself has run its course: the page's timers are the harness's and do not fire here.
const settled = async () => { for (let step = 0; step < 50; step += 1) await Promise.resolve(); };
// The command for a new machine, where the page has it (ScoutInstallLine), and what it shows.
const withInstall = () => {
  const line = part();
  line.parts = { "[data-scout-install-command]": part(), "[data-scout-install-copy]": part(), "[data-scout-install-note]": part() };
  line.querySelector = (sel) => line.parts[sel] || null;
  root.parts["[data-scout-install]"] = line;
  return line;
};
const lineView = (line) => ({ state: line.dataset.tState, command: line.parts["[data-scout-install-command]"].textContent,
                              shown: !line.parts["[data-scout-install-command]"].hidden, copy: !line.parts["[data-scout-install-copy]"].hidden,
                              note: line.parts["[data-scout-install-note]"].textContent });
// The 🔍 panel, where the page has it (ScoutFinder): added to the block on demand, closed.
const withFinder = () => {
  for (const sel of ["[data-scout-find]", "[data-scout-add-find]", "[data-scout-find-networks]", "[data-scout-find-run]", "[data-scout-find-list]"]) root.parts[sel] = part();
  root.parts["[data-scout-find]"].hidden = true;
};
const memory = (start = null) => { const box = { value: start, getItem: () => box.value, setItem: (_k, v) => { box.value = v; } }; return box; };
// A form whose finder remembers into `mem` instead of the browser's storage.
const finderForm = (mem) => { withFinder(); const form = new sa.ScoutAddForm(root); form.finder = new sa.ScoutFinder(form, root, { memory: mem }); form.bind(); return form; };
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

FOUND = {"networks": ["10.0.30.0/24"], "port": 8092, "scanned": 254, "found": [
    {"address": "10.0.30.20", "port": 8092, "hostId": "sierra-pc", "name": "sierra-pc", "version": "2.25.1", "state": "free"},
    {"address": "10.0.30.23", "port": 8092, "hostId": "alpha", "name": "foxtrot-pc", "version": "2.25.1", "state": "here"},
    {"address": "10.0.30.24", "port": 8092, "hostId": "bravo", "name": "<b>bravo</b>", "version": "", "state": "taken"}]}
NONE = {"networks": ["10.0.20.0/24"], "port": 8092, "scanned": 254, "found": []}
NOT_PRIVATE = "8.8.8.0/24 is not a private network: the scan looks only in the home network"

DONE = {"ok": True, "hostId": "box-a", "name": "Box A", "scoutVersion": "2.1.0",
        "scoutUrl": "http://10.0.0.5:8092", "controllerUrl": "http://10.0.0.1:7990"}
REFUSED = "no scout answers at http://10.0.0.5:8092: Connection refused — is ./install.sh done there, and is the port open?"

# A form on the board's page, with its opener: what it asked to run later waits in `waiting`, and runs when a pin says.
CLOSING = (
    f"globalThis.__fetchReply['/api/topology/scout/connect'] = {json.dumps(DONE)};"
    " const waiting = []; const opener = part();"
    " const form = new sa.ScoutAddForm(root, { opener, later: (run, ms) => waiting.push({ run, ms }) }); form.bind();"
    " const connected = async () => { P('[data-scout-add-address]').value = '10.0.0.5'; await P('[data-scout-add-connect]').fire('click'); };"
    " const closing = () => ({ hidden: !!root.hidden, expanded: opener.attrs['aria-expanded'], state: root.dataset.tState, status: P('[data-scout-add-status]').textContent });"
)

PINS = [
    ("closes_a_moment_after_connecting",
     CLOSING + " form.open(true);",
     "await (async () => { await connected(); const before = closing(); const asked = waiting.map((w) => w.ms); waiting.forEach((w) => w.run()); return { before, asked, after: closing() }; })()",
     json.dumps({"before": {"hidden": False, "expanded": "true", "state": "ok", "status": en("scoutAddDone", name="Box A", version="2.1.0")},
                 "asked": [2500],
                 "after": {"hidden": True, "expanded": "false", "state": "idle", "status": ""}}, ensure_ascii=False),
     "машина на доске: слово держится 2,5 секунды, потом ящик закрывается сам и при новом открытии не говорит о прошлой машине"),
    ("stays_when_the_next_address_is_typed",
     CLOSING + " form.open(true);",
     "await (async () => { await connected(); P('[data-scout-add-address]').value = 'next-box'; waiting.forEach((w) => w.run()); return closing(); })()",
     json.dumps({"hidden": False, "expanded": "true", "state": "ok", "status": en("scoutAddDone", name="Box A", version="2.1.0")}, ensure_ascii=False),
     "negative: оператор уже вводит следующий адрес — ящик остаётся"),
    ("stays_while_the_scan_lists_machines",
     CLOSING.replace("const form = new", "withFinder(); const form = new") + " form.open(true); P('[data-scout-find]').hidden = false;",
     "await (async () => { await connected(); waiting.forEach((w) => w.run()); return closing().hidden; })()",
     "false",
     "negative: открыт поиск по сети, в списке могут быть ещё машины — ящик остаётся"),
    ("stays_after_a_refusal",
     CLOSING + f" globalThis.__fetchReply['/api/topology/scout/connect'] = {{ __status: 502, error: {json.dumps(REFUSED)} }}; form.open(true);",
     "await (async () => { await connected(); return { asked: waiting.length, hidden: closing().hidden }; })()",
     json.dumps({"asked": 0, "hidden": False}),
     "negative: отказ — закрывать нечего, адрес остаётся для исправления"),
    ("a_page_without_the_opener_keeps_its_box",
     f"globalThis.__fetchReply['/api/topology/scout/connect'] = {json.dumps(DONE)};"
     " const waiting = []; const form = new sa.ScoutAddForm(root, { later: (run, ms) => waiting.push({ run, ms }) }); form.bind();",
     "await (async () => { P('[data-scout-add-address]').value = '10.0.0.5'; await P('[data-scout-add-connect]').fire('click'); return waiting.length; })()",
     "0",
     "negative: страница без кнопки открытия — ящик стоит всегда, закрывать нечем"),
    ("settings_that_came_back_are_said",
     CLOSING.replace(json.dumps(DONE), json.dumps({**DONE, "settingsBack": ["cacheLimit", "cell:22013"]})) + " form.open(true);",
     "await (async () => { await connected(); return { status: closing().status, asked: waiting.length }; })()",
     json.dumps({"status": en("scoutAddDone", name="Box A", version="2.1.0") + " " + en("scoutAddSettingsBack"), "asked": 1}, ensure_ascii=False),
     "настройки машины вернулись: сказано одной фразой, ящик закрывается как обычно"),
    ("settings_that_did_not_come_back_keep_the_box",
     CLOSING.replace(json.dumps(DONE), json.dumps({**DONE, "settingsBack": ["cacheLimit"], "settingsNotBack": ["cacheFolder: the cache cannot be in /mnt/gone"]})) + " form.open(true);",
     "await (async () => { await connected(); return { status: closing().status, asked: waiting.length }; })()",
     json.dumps({"status": en("scoutAddDone", name="Box A", version="2.1.0") + " " + en("scoutAddSettingsBack") + " " + en("scoutAddSettingsNotBack", what="cacheFolder: the cache cannot be in /mnt/gone"), "asked": 0}, ensure_ascii=False),
     "negative: что-то не вернулось: названо словами скаута, и ящик остаётся, чтобы это прочитали"),
    ("connect_names_the_scouts_release",
     f"globalThis.__fetchReply['/api/topology/scout/connect'] = {json.dumps({**DONE, 'scoutCommit': '86f58740'})}; sa.ScoutAddForm.mount(doc); P('[data-scout-add-address]').value = '10.0.0.5';",
     "await (async () => { await P('[data-scout-add-connect]').fire('click'); return P('[data-scout-add-status]').textContent; })()",
     json.dumps(en("scoutAddDone", name="Box A", version="86f58740"), ensure_ascii=False),
     "скаут, назвавший свой выпуск: в словах номер выпуска, как в шапке страницы машины"),
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

FINDER_PINS = [
    ("finder_absent_on_an_old_page",
     "",
     "(() => { const form = new sa.ScoutAddForm(root); form.bind(); return form.finder; })()",
     json.dumps(None),
     "negative: страница без панели 🔍 — формы хватает, поиска нет и ничего не падает"),
    ("finder_opens_with_what_was_typed_last",
     "",
     "(() => { const mem = memory('10.0.30.0/24'); finderForm(mem); const panel = P('[data-scout-find]');"
     " P('[data-scout-add-find]').fire('click'); const opened = [panel.hidden, P('[data-scout-find-networks]').value,"
     " P('[data-scout-add-find]').attrs['aria-expanded'], P('[data-scout-find-networks]').focused];"
     " P('[data-scout-add-find]').fire('click'); const closed = [panel.hidden, P('[data-scout-add-find]').attrs['aria-expanded']];"
     " P('[data-scout-find-networks]').value = '10.1.1.0/24'; P('[data-scout-add-find]').fire('click');"
     " return [opened, closed, P('[data-scout-find-networks]').value]; })()",
     json.dumps([[False, "10.0.30.0/24", "true", True], [True, "false"], "10.1.1.0/24"]),
     "🔍 открывает панель с сетями прошлого поиска и ставит в поле фокус, второе нажатие закрывает; "
     "negative: уже введённое память не затирает"),
    ("scan_found",
     f"globalThis.__fetchReply['/api/topology/scout/scan'] = {json.dumps(FOUND)};",
     "await (async () => { const mem = memory(); finderForm(mem); P('[data-scout-find-networks]').value = ' 10.0.30.0/24 ';"
     " P('[data-scout-add-port]').value = '8092'; await P('[data-scout-find-run]').fire('click');"
     " const html = P('[data-scout-find-list]').innerHTML; const rows = [...html.matchAll(/data-t-id=\"([^\"]+)\" data-t-state=\"([^\"]+)\"/g)].map((m) => [m[1], m[2]]);"
     " return { state: P('[data-scout-find]').dataset.tState, rows, connects: [...html.matchAll(/data-scout-find-connect=\"([^\"]+)\"/g)].map((m) => m[1]),"
     " note: html.includes(" + json.dumps(en("scoutFindFound", networks="10.0.30.0/24", count="3")) + "),"
     " chips: [" + ", ".join(json.dumps(en(k)) for k in ("scoutFindFree", "scoutFindHere", "scoutFindTaken")) + "].map((c) => html.includes('>' + c + '<')),"
     " escaped: html.includes('&lt;b&gt;bravo&lt;/b&gt;') && !html.includes('<b>bravo</b>'), remembered: mem.value, disabled: P('[data-scout-find-run]').disabled,"
     " calls: globalThis.__fetchCalls.map((c) => ({ path: c.path, body: c.body })) }; })()",
     json.dumps({"state": "found", "rows": [["10.0.30.20:8092", "free"], ["10.0.30.23:8092", "here"], ["10.0.30.24:8092", "taken"]],
                 "connects": ["10.0.30.20"], "note": True, "chips": [True, True, True], "escaped": True,
                 "remembered": "10.0.30.0/24", "disabled": False,
                 "calls": [{"path": "/api/topology/scout/scan", "body": "{\"networks\":\"10.0.30.0/24\",\"port\":\"8092\"}"}]}),
     "найдены: строка на скаут по порядку, состояние каждого; «Подключить» только у свободного; имя экранировано; "
     "сети запомнены; на провод — сети без пробелов и порт из формы"),
    ("scan_none_and_refused",
     f"globalThis.__fetchReply['/api/topology/scout/scan'] = {json.dumps(NONE)};",
     "await (async () => { finderForm(memory()); await P('[data-scout-find-run]').fire('click');"
     " const none = [P('[data-scout-find]').dataset.tState, P('[data-scout-find-list]').innerHTML.includes(" + json.dumps(en("scoutFindNone", networks="10.0.20.0/24", port="8092").replace("'", "&#39;")) + ")];"
     f" globalThis.__fetchReply['/api/topology/scout/scan'] = {{ __status: 400, error: {json.dumps(NOT_PRIVATE)} }};"
     " P('[data-scout-find-networks]').value = '8.8.8.0/24'; await P('[data-scout-find-networks]').fire('keydown', { key: 'Enter' });"
     " return [none, P('[data-scout-find]').dataset.tState, P('[data-scout-find-list]').innerHTML.includes(" + json.dumps(NOT_PRIVATE) + "),"
     " P('[data-scout-find-run]').disabled, globalThis.__fetchCalls.map((c) => c.body)]; })()",
     json.dumps([["none", True], "error", True, False,
                 ['{"networks":"","port":"8092"}', '{"networks":"8.8.8.0/24","port":"8092"}']]),
     "никто не ответил — сказано, где искали и на каком порту, и что проверить; пусто — своя сеть контроллера; "
     "negative: отказ контроллера — его слова, кнопка снова доступна; Enter в поле сетей — тот же поиск"),
    ("found_scout_connects_as_if_typed",
     f"globalThis.__fetchReply['/api/topology/scout/connect'] = {json.dumps(DONE)};",
     "await (async () => { finderForm(memory()); P('[data-scout-add-port]').value = '9999';"
     " await P('[data-scout-find-list]').fire('click', { target: { closest: () => ({ dataset: { scoutFindConnect: '10.0.30.20', scoutFindPort: '8092' } }) } });"
     " await P('[data-scout-find-list]').fire('click', { target: { closest: () => null } });"
     " return view(); })()",
     json.dumps({"state": "ok", "status": en("scoutAddDone", name="Box A", version="2.1.0"), "address": "", "disabled": False,
                 "calls": [{"path": "/api/topology/scout/connect", "method": "POST",
                            "body": '{"address":"10.0.30.20","port":"8092"}'}]}, ensure_ascii=False),
     "«Подключить» у найденного — адрес и порт в форму, и форма сопрягает его, как введённого руками; "
     "negative: щелчок мимо кнопки ничего не шлёт"),
]
PINS += FINDER_PINS
# The box opens by two buttons in the Machines head, where "+ New pool" stands for the pools
# (the owner, 2026-10-11): ＋ Add scout and 🔍 Find. The head is the page's, outside the box.
HEAD = ("const head = { '[data-scout-add-open]': part(), '[data-scout-add-find]': part() };"
        " doc.querySelector = (sel) => head[sel] || null; withFinder(); delete root.parts['[data-scout-add-find]']; root.hidden = true;")
HEAD_PINS = [
    ("head_button_opens_and_closes_the_box",
     HEAD,
     "(() => { sa.ScoutAddForm.mount(doc); const o = head['[data-scout-add-open]']; const shut = root.hidden;"
     " o.fire('click'); const opened = [root.hidden, o.attrs['aria-expanded'], P('[data-scout-add-address]').focused, P('[data-scout-find]').hidden];"
     " o.fire('click'); return [shut, opened, [root.hidden, o.attrs['aria-expanded']]]; })()",
     json.dumps([True, [False, "true", True, True], [True, "false"]]),
     "ящик закрыт, пока его не открыли; «＋ Добавить скаута» в заголовке открывает его и ставит курсор в адрес (поиск закрыт), "
     "второе нажатие закрывает"),
    ("head_find_opens_the_box_and_the_scan",
     HEAD,
     "(() => { sa.ScoutAddForm.mount(doc); const f = head['[data-scout-add-find]'], o = head['[data-scout-add-open]'];"
     " f.fire('click'); const opened = [root.hidden, P('[data-scout-find]').hidden, f.attrs['aria-expanded'], o.attrs['aria-expanded'], P('[data-scout-find-networks]').focused];"
     " o.fire('click'); return [opened, [root.hidden, P('[data-scout-find]').hidden, f.attrs['aria-expanded']]]; })()",
     json.dumps([[False, False, "true", "true", True], [True, True, "false"]]),
     "«🔍 Найти» в заголовке открывает ящик и поиск в нём, курсор — в поле сетей; "
     "negative: ящик закрыли кнопкой «＋ Добавить скаута» — поиск закрыт вместе с ним, а не висит открытым внутри закрытого"),
    ("old_page_keeps_the_box_open",
     "",
     "(() => { sa.ScoutAddForm.mount(doc); return [!!root.hidden, P('[data-scout-add-address]').focused]; })()",
     json.dumps([False, False]),
     "negative: страница без кнопок в заголовке — ящик открыт, как был всегда, и курсор сам никуда не прыгает"),
]
PINS += HEAD_PINS

COMMAND = "curl -fsSL https://caravan.example/scout/install.sh | bash"
PLAIN_COMMAND = "curl -fsSL http://10.0.0.1:7990/scout/install.sh | bash"


def line_shows(reply, state, command, note):
    """A pin of what the line shows after reading the controller's `reply`, and that it asked only the one address."""
    return ("await (async () => { const line = withInstall(); const form = new sa.ScoutInstallLine(line); await form.load();"
            " return { ...lineView(line), calls: globalThis.__fetchCalls.map((c) => [c.method, c.path]) }; })()",
            json.dumps({"state": state, "command": command, "shown": bool(command), "copy": bool(command), "note": note,
                        "calls": [["GET", "/api/fleet/scout-release"]]}, ensure_ascii=False))


INSTALL_PINS = [
    ("install_line_over_https_warns_of_the_certificate",
     f"globalThis.__fetchReply['/api/fleet/scout-release'] = {json.dumps({'ok': True, 'release': {'commit': 'abc1'}, 'running': None, 'installCommand': COMMAND})};",
     *line_shows(None, "ready", COMMAND, en("scoutInstallTrust")),
     "команда контроллера показана как есть, с кнопкой копирования; по https сказано, что машина должна доверять сертификату"),
    ("install_line_over_http_says_nothing_of_a_certificate",
     f"globalThis.__fetchReply['/api/fleet/scout-release'] = {json.dumps({'ok': True, 'release': {'commit': 'abc1'}, 'running': None, 'installCommand': PLAIN_COMMAND})};",
     *line_shows(None, "ready", PLAIN_COMMAND, ""),
     "negative: по http сертификата нет, и о нём ни слова"),
    ("install_line_without_a_bundle_shows_no_command",
     "globalThis.__fetchReply['/api/fleet/scout-release'] = {'ok': true, 'release': null, 'running': null, 'installCommand': null};",
     *line_shows(None, "none", "", en("scoutInstallNone")),
     "negative: у контроллера нет скаута — команды, которая упала бы, нет, и сказано почему"),
    ("install_line_when_the_controller_refuses",
     "globalThis.__fetchReply['/api/fleet/scout-release'] = { __status: 500, error: 'the disk is gone' };",
     *line_shows(None, "error", "", "the disk is gone"),
     "negative: отказ контроллера — его слова, состояние error, команды нет"),
    ("install_copy_says_what_happened",
     "",
     "await (async () => { const line = withInstall(); const copied = []; let lands = true;"
     " const form = new sa.ScoutInstallLine(line, { call: async () => ({ installCommand: 'the command' }), copy: async (text) => { copied.push(text); return lands; } });"
     " form.bind(); await form.load(); await line.parts['[data-scout-install-copy]'].fire('click'); const landed = lineView(line);"
     " lands = false; await line.parts['[data-scout-install-copy]'].fire('click'); const failed = lineView(line);"
     " return [copied, landed.state, landed.note, failed.state, failed.note]; })()",
     json.dumps([["the command", "the command"], "copied", en("scoutInstallCopied"), "ready", en("scoutInstallCopyFailed")], ensure_ascii=False),
     "кнопка копирует саму команду и говорит «скопировано»; negative: не легло в буфер — сказано, что не скопировалось, а не «готово»"),
    ("install_is_read_when_the_box_opens",
     HEAD + " globalThis.__fetchReply['/api/fleet/scout-release'] = {'ok': true, 'installCommand': 'c'};",
     "await (async () => { const line = withInstall(); sa.ScoutAddForm.mount(doc); const before = globalThis.__fetchCalls.length;"
     " const o = head['[data-scout-add-open]']; await o.fire('click'); await settled(); const opened = globalThis.__fetchCalls.length;"
     " await o.fire('click'); await settled(); return [before, opened, globalThis.__fetchCalls.length, line.dataset.tState]; })()",
     json.dumps([0, 1, 1, "ready"]),
     "закрытый ящик ничего не спрашивает, открытый читает команду; negative: закрытие не читает"),
    ("install_absent_on_a_page_without_it",
     "",
     "(() => { const form = new sa.ScoutAddForm(root); form.bind(); form.open(true); return [form.install, globalThis.__fetchCalls.length]; })()",
     json.dumps([None, 0]),
     "negative: на странице без строки команды форма работает и ничего не спрашивает"),
    ("install_read_at_once_on_a_page_with_the_box_always_open",
     "globalThis.__fetchReply['/api/fleet/scout-release'] = {'ok': true, 'installCommand': 'c'};",
     "await (async () => { withInstall(); sa.ScoutAddForm.mount(doc); await settled(); return globalThis.__fetchCalls.map((c) => c.path); })()",
     json.dumps(["/api/fleet/scout-release"]),
     "страница без кнопок в заголовке держит ящик открытым — команда читается сразу"),
]
PINS += INSTALL_PINS

if __name__ == "__main__":
    sys.exit(run("js scout-add", ".probe_js_scout_add.tmp.mjs", PREAMBLE, PINS,
                 stubs="topology-render,canvas,topology-dnd,topology-modals,cables,routers,cloud,dialogs"))
