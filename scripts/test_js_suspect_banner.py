#!/usr/bin/env python3
"""Снимок static/js/suspect-banner.js — баннер «свежая сборка llama.cpp роняет ячейки».

Баннер был один, про машину контроллера, и жил строками в topology-render.js
без единого теста. Скаут 2.6 судит так же о своей машине, и баннер стал
строкой на машину: своя у контроллера (topology.llamaSuspect) и по строке на
машину со скаутом (topology.hostSuspects). Пинится значениями: какие строки,
что в каждой написано, что уходит на провод при «скрыть» и что открывается
при «откатить», что строка, с которой оператор уже что-то сделал, уходит
сразу, и что одинаковый баннер не перерисовывается.

Подписи берутся из static/js/i18n/en.js программно, а не по памяти.

Запуск: python3 scripts/test_js_suspect_banner.py
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
const sb = await import(pathToFileURL(process.env.JS_ROOT + "/suspect-banner.js").href);
// The banner's element: innerHTML becomes buttons with their data-* value,
// so the module can bind them and a pin can click them.
const mkBanner = () => {
  const el = { hidden: true, _html: "", buttons: [],
    querySelectorAll(sel) { const m = sel.match(/^\[data-([a-z-]+)\]$/); return this.buttons.filter((b) => b.attr === m[1]); } };
  Object.defineProperty(el, "innerHTML", { get() { return this._html; }, set(v) { this._html = v;
    this.buttons = [...v.matchAll(/data-(suspect-restore|suspect-dismiss)="([^"]*)"/g)].map((mm) => { const h = [];
      return { attr: mm[1], getAttribute: (k) => (k === "data-" + mm[1] ? mm[2] : null),
               addEventListener: (ev, fn) => h.push(fn), click: () => h.forEach((fn) => fn()) }; }); } });
  return el;
};
const CAND = { id: "20260920-090000-def5678", commit: "def5678", version: "version: 9900 (def5678)", builtAt: 1789600000, sizeMb: 87 };
const OWN = { suspect: true, crashes15m: 4, builtAt: 1789990000, currentCommit: "abc1234", firstSeenAt: 1789999000, lastSeenAt: 1789999800, restoreCandidate: CAND };
const HOST = { suspect: true, crashes15m: 3, builtAt: 1789996400, currentCommit: "0a0a0a0", firstSeenAt: 1789999100, lastSeenAt: 1789999880,
               restoreCandidate: CAND, hostId: "box-a", name: "Box A", llamaBinaryVersion: "version: 9947 (0a0a0a0)" };
let banner, el;
const reset = () => { banner = new sb.LlamaSuspectBanner(); el = mkBanner();
  globalThis.__fetchCalls.length = 0; globalThis.__fetchReply = {}; globalThis.__opened = [];
  globalThis.__stubReturns = { "system-panels.openRestoreBuildModal": (...a) => { globalThis.__opened.push(a); } }; };
const keys = (rows) => rows.map((r) => [r.hostId, r.key]);
const rowsOn = () => [...el.innerHTML.matchAll(/data-t-id="([^"]*)"/g)].map((m) => m[1]);
const settle = async () => { for (let i = 0; i < 3; i++) await new Promise((r) => setImmediate(r)); };
const wire = () => globalThis.__fetchCalls.map((c) => [c.path, c.method, c.body]);
"""

HOST_ROW = ('<div class="llama-suspect-row" data-t="board-llama-suspect-row" data-t-id="box-a">'
            '<span class="llama-suspect-msg">⚠ ' + en("llamaSuspectMsgHost", host="Box A", n=3) + ' · 2:11:20 PM</span>'
            '<button type="button" class="llama-suspect-restore" data-suspect-restore="box-a|0a0a0a0:1789996400:'
            '20260920-090000-def5678:29833331">' + en("llamaSuspectRestore") + ' b9900 (def5678)</button>'
            '<button type="button" class="llama-suspect-dismiss" data-suspect-dismiss="box-a|0a0a0a0:1789996400:'
            '20260920-090000-def5678:29833331">' + en("llamaSuspectDismiss") + '</button></div>')

PINS = [
    ("rows_own_then_hosts",
     "",
     "keys(banner.rows({ llamaSuspect: OWN, hostSuspects: [HOST, { ...HOST, hostId: 'box-b', name: 'Box B' }, { suspect: false, hostId: 'box-c' }] }))",
     json.dumps([["", "|abc1234:1789990000:20260920-090000-def5678:29833330"],
                 ["box-a", "box-a|0a0a0a0:1789996400:20260920-090000-def5678:29833331"],
                 ["box-b", "box-b|0a0a0a0:1789996400:20260920-090000-def5678:29833331"]]),
     "строка контроллера первой, потом по строке на машину со скаутом; ключ — машина, сборка, кандидат, минута последнего падения; negative: машина без подозрения — строки нет"),
    ("rows_none",
     "",
     "[banner.rows({ llamaSuspect: { suspect: false } }), banner.rows({}), banner.rows(null)]",
     json.dumps([[], [], []]),
     "negative: никто не подозревает, поля нет, доски ещё нет — строк нет"),
    ("message_names_the_machine",
     "",
     "[banner.message(HOST), banner.message({ ...HOST, name: '' }), banner.message({ ...OWN, hostId: '' })]",
     json.dumps([en("llamaSuspectMsgHost", host="Box A", n=3), en("llamaSuspectMsgHost", host="box-a", n=3),
                 en("llamaSuspectMsg", n=4)], ensure_ascii=False),
     "строка машины называет машину (имени нет — её id); строка контроллера — прежними словами"),
    ("row_html_host",
     "",
     "banner.rowHtml(banner.rows({ hostSuspects: [HOST] })[0])",
     json.dumps(HOST_ROW, ensure_ascii=False),
     "строка машины: data-t=board-llama-suspect-row с id машины, сообщение со временем последнего падения, «Откатить» с версией кандидата, «Скрыть»"),
    ("row_html_without_a_candidate",
     "",
     "banner.rowHtml(banner.rows({ hostSuspects: [{ ...HOST, restoreCandidate: null }] })[0]).includes('data-suspect-restore')",
     "false",
     "negative: откатывать не на что (в архиве только текущая) — кнопки отката нет, «Скрыть» есть"),
    ("render_nothing",
     "",
     "(banner.render(el, { llamaSuspect: { suspect: false }, hostSuspects: [] }), [el.hidden, el.innerHTML])",
     json.dumps([True, ""]),
     "negative: подозрений нет — баннер скрыт и пуст"),
    ("render_rows",
     "",
     "(banner.render(el, { llamaSuspect: OWN, hostSuspects: [HOST] }), [el.hidden, rowsOn(), el.buttons.map((b) => b.attr)])",
     json.dumps([False, ["controller", "box-a"], ["suspect-restore", "suspect-dismiss", "suspect-restore", "suspect-dismiss"]]),
     "две строки — контроллер и машина, у каждой свои кнопки"),
    ("render_same_is_left_alone",
     "",
     "(() => { const topo = { hostSuspects: [HOST] }; banner.render(el, topo); el._html = 'untouched'; banner.render(el, topo); return el.innerHTML; })()",
     json.dumps("untouched"),
     "тот же баннер на следующем опросе не перерисовывается — кнопка под курсором не пропадает"),
    ("restore_on_a_machine",
     "",
     "(() => { const topo = { llamaSuspect: OWN, hostSuspects: [HOST] }; banner.render(el, topo); el.buttons[2].click(); return [globalThis.__opened, rowsOn(), wire()]; })()",
     json.dumps([[["20260920-090000-def5678", {"id": "20260920-090000-def5678", "commit": "def5678",
                                              "version": "version: 9900 (def5678)", "builtAt": 1789600000, "sizeMb": 87},
                   {"hostId": "box-a", "name": "Box A", "version": "version: 9947 (0a0a0a0)"}]], ["controller"], []]),
     "«Откатить» у машины — то же окно подтверждения, что в Системе, с машиной и её текущей сборкой; строка уходит сразу; на провод ничего — откат только после подтверждения"),
    ("restore_on_the_controller",
     "",
     "(() => { banner.render(el, { llamaSuspect: OWN }); el.buttons[0].click(); return [globalThis.__opened.map((a) => [a[0], a[2]]), el.hidden, el.innerHTML]; })()",
     json.dumps([[["20260920-090000-def5678", None]], True, ""]),
     "у контроллера — окно без машины (восстанавливает сам контроллер); последняя строка ушла — баннер скрыт и пуст "
     "(живая проверка 2026-09-24: скрытый баннер держал строку, и поиск по data-t находил невидимое)"),
    ("dismiss_a_machine",
     "",
     "await (async () => { banner.render(el, { llamaSuspect: OWN, hostSuspects: [HOST] }); el.buttons[3].click(); await settle(); return [wire(), rowsOn()]; })()",
     json.dumps([[["/api/fleet/llama-suspect-dismiss", "POST", "{\"hostId\":\"box-a\"}"]], ["controller"]]),
     "«Скрыть» у машины — её скауту через контроллер, для этой сборки; строка уходит сразу, строка контроллера остаётся"),
    ("dismiss_the_controller",
     "",
     "await (async () => { banner.render(el, { llamaSuspect: OWN, hostSuspects: [HOST] }); el.buttons[1].click(); await settle(); return [wire(), rowsOn()]; })()",
     json.dumps([[["/api/llamacpp/suspect-dismiss", "POST", "{}"]], ["box-a"]]),
     "«Скрыть» у контроллера — прежний путь; строка машины остаётся"),
    ("a_new_crash_shows_again",
     "",
     "(() => { banner.render(el, { hostSuspects: [HOST] }); el.buttons[1].click(); const gone = el.hidden; banner.render(el, { hostSuspects: [HOST] }); const still = el.hidden; banner.render(el, { hostSuspects: [{ ...HOST, lastSeenAt: HOST.lastSeenAt + 60 }] }); return [gone, still, el.hidden, rowsOn()]; })()",
     json.dumps([True, True, False, ["box-a"]]),
     "скрытая строка не возвращается со следующим опросом того же инцидента; новое падение (другая минута) — это новое, строка снова видна"),
    ("one_banner",
     "",
     "sb.SUSPECT_BANNER instanceof sb.LlamaSuspectBanner",
     "true",
     "доска держит один баннер (SUSPECT_BANNER)"),
]

if __name__ == "__main__":
    sys.exit(run("js suspect-banner", ".probe_js_suspect_banner.tmp.mjs", PREAMBLE, PINS,
                 stubs="system-panels,topology-render,canvas,topology-dnd,topology-modals,cables,routers,cloud,dialogs"))
