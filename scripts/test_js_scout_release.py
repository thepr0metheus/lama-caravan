#!/usr/bin/env python3
"""Снимок static/js/scout-release.js — пункт «Обновить скаута» в меню машины.

Пинится значениями: какой из исходов следует из ответа контроллера (выпуска нет,
скаут не умеет заменять себя, уже этот выпуск, новый), что сказано оператору в
каждом, что без согласия на провод ничего не уходит, что «взял» и «работает» —
разные слова: второе говорит только следующий отчёт машины, и что машина, не
вернувшаяся за отведённое время, так и названа.

Подписи берутся из static/js/i18n/en.js программно, а не по памяти.

Запуск: python3 scripts/test_js_scout_release.py
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
const sr = await import(pathToFileURL(process.env.JS_ROOT + "/scout-release.js").href);
const STATUS = "/api/fleet/scout-release?hostId=box%201";
// A press with everything outside it given: the answers the controller gives in turn, the operator's answer, what is said.
const pressed = async ({ answers = [], yes = true, update = { ok: true } }) => {
  const calls = [], said = [], asked = [], pauses = [];
  const call = async (path, options) => {
    calls.push(options ? [path, options.method, options.body] : [path]);
    if (options) {
      if (update.error) throw new Error(update.error);
      return update;
    }
    const next = answers.length > 1 ? answers.shift() : answers[0];
    if (next.error) throw new Error(next.error);
    return next;
  };
  const release = new sr.ScoutRelease("box 1", { call, confirm: async (words, opts) => { asked.push([words, opts.confirmLabel]); return yes; },
                                                 notify: (words) => said.push(words), pause: async (ms) => { pauses.push(ms); } });
  const outcome = await release.press();
  return { outcome, calls, said, asked, pauses: pauses.length };
};
const item = (hostId) => {
  const handlers = {};
  return { getAttribute: (name) => (name === "data-scout-update" ? hostId : null), addEventListener: (ev, fn) => { handlers[ev] = fn; }, fire: (ev, arg) => handlers[ev](arg) };
};
const reset = () => {};
"""

UPDATE_BODY = {"hostId": "box 1"}
OLD = {"release": {"commit": "new1", "sha256": "ff", "bytes": 9}, "running": "old1"}
SAME = {"release": {"commit": "new1", "sha256": "ff", "bytes": 9}, "running": "new1"}
NO_BUNDLE = {"release": None, "running": "old1"}
NO_WORD = {"release": {"commit": "new1", "sha256": "ff", "bytes": 9}, "running": None}
TRIES = 30


def only_said(words, outcome):
    return json.dumps({"outcome": outcome, "calls": [["/api/fleet/scout-release?hostId=box%201"]], "said": [words], "asked": [], "pauses": 0}, ensure_ascii=False)


PINS = [
    ("offer_of_each_answer",
     "",
     "[" + ", ".join(f"sr.ScoutRelease.offer({json.dumps(x)})" for x in (OLD, SAME, NO_BUNDLE, NO_WORD, {}, None)) + "]",
     json.dumps([{"kind": "new", "commit": "new1", "running": "old1"}, {"kind": "current", "commit": "new1", "running": "new1"},
                 {"kind": "no-release"}, {"kind": "cannot", "commit": "new1"}, {"kind": "no-release"}, {"kind": "no-release"}]),
     "четыре исхода из значений; negative: пустой ответ и его отсутствие — «выпуска нет», а не «новый»"),
    ("no_release_says_so_and_sends_nothing",
     "",
     f"await pressed({{ answers: [{json.dumps(NO_BUNDLE)}] }})",
     only_said(en("scoutUpdateNoRelease"), "no-release"),
     "negative: у контроллера нет скаута — сказано, вопроса нет, на провод ничего"),
    ("a_scout_without_a_release_cannot",
     "",
     f"await pressed({{ answers: [{json.dumps(NO_WORD)}] }})",
     only_said(en("scoutUpdateCannot", host="box 1"), "cannot"),
     "negative: скаут не говорит свой выпуск — он не умеет заменять себя, сказано что делать, на провод ничего"),
    ("the_same_release_is_not_taken_again",
     "",
     f"await pressed({{ answers: [{json.dumps(SAME)}] }})",
     only_said(en("scoutUpdateCurrent", host="box 1", commit="new1"), "current"),
     "negative: уже этот выпуск — сказано, ничего не перезапускается"),
    ("declined_sends_nothing",
     "",
     f"await pressed({{ answers: [{json.dumps(OLD)}], yes: false }})",
     json.dumps({"outcome": "declined", "calls": [["/api/fleet/scout-release?hostId=box%201"]], "said": [],
                 "asked": [[en("scoutUpdateAsk", host="box 1", running="old1", commit="new1"), en("scoutUpdateOk")]], "pauses": 0}, ensure_ascii=False),
     "вопрос называет машину и оба выпуска; negative: оператор отказался — на провод ничего"),
    ("taken_and_come_back",
     "",
     f"await pressed({{ answers: [{json.dumps(OLD)}, {json.dumps(OLD)}, {{ error: 'a moment' }}, {json.dumps(SAME)}] }})",
     json.dumps({"outcome": "done",
                 "calls": [["/api/fleet/scout-release?hostId=box%201"], ["/api/fleet/scout-update", "POST", UPDATE_BODY],
                           ["/api/fleet/scout-release?hostId=box%201"], ["/api/fleet/scout-release?hostId=box%201"], ["/api/fleet/scout-release?hostId=box%201"]],
                 "said": [en("scoutUpdateTaking", host="box 1", commit="new1"), en("scoutUpdateDone", host="box 1", commit="new1")],
                 "asked": [[en("scoutUpdateAsk", host="box 1", running="old1", commit="new1"), en("scoutUpdateOk")]], "pauses": 3}, ensure_ascii=False),
     "согласие → запрос с машиной; «взял» сказано сразу, «работает» — только когда отчёт машины назвал новый выпуск; "
     "negative: миг без ответа контроллера — ещё не ответ, следим дальше"),
    ("taken_and_silent",
     "",
     f"await (async () => {{ const seen = await pressed({{ answers: [{json.dumps(OLD)}] }}); return [seen.outcome, seen.pauses, seen.said]; }})()",
     json.dumps(["silent", TRIES, [en("scoutUpdateTaking", host="box 1", commit="new1"), en("scoutUpdateSilent", host="box 1", commit="new1")]], ensure_ascii=False),
     "negative: машина не сообщила новый выпуск за отведённое время — так и сказано, а не «работает»"),
    ("a_refusal_of_the_scout_is_said",
     "",
     f"await (async () => {{ const seen = await pressed({{ answers: [{json.dumps(OLD)}], update: {{ error: 'box 1: not now: :22013 is loading' }} }}); return [seen.outcome, seen.said, seen.pauses]; }})()",
     json.dumps(["failed", ["box 1: not now: :22013 is loading"], 0]),
     "negative: скаут отказал (ячейка стартует) — его слова, и следить не за чем"),
    ("a_controller_that_does_not_answer_is_said",
     "",
     "await (async () => { const seen = await pressed({ answers: [{ error: 'unreachable' }] }); return [seen.outcome, seen.said, seen.asked]; })()",
     json.dumps(["failed", ["unreachable"], []]),
     "negative: контроллер не ответил на первый вопрос — сказано, вопроса оператору нет"),
    ("bind_presses_for_the_item_host",
     "",
     "await (async () => { const seen = []; const it = item('box 2'); const calls = []; const originalApi = sr.ScoutRelease.prototype.press;"
     " sr.ScoutRelease.prototype.press = function () { calls.push(this.hostId); return Promise.resolve(); };"
     " sr.ScoutRelease.bind({ querySelectorAll: (sel) => { seen.push(sel); return [it]; } });"
     " let stopped = 0; it.fire('click', { stopPropagation: () => { stopped += 1; } }); sr.ScoutRelease.prototype.press = originalApi;"
     " sr.ScoutRelease.bind(null); return [seen, calls, stopped]; })()",
     json.dumps([["[data-scout-update]"], ["box 2"], 1]),
     "щелчок по пункту — нажатие для его машины, дальше не всплывает; negative: нет полосы — и привязывать нечего, не падение"),
]

if __name__ == "__main__":
    sys.exit(run("js scout-release", ".probe_js_scout_release.tmp.mjs", PREAMBLE, PINS,
                 stubs="topology-render,canvas,topology-dnd,topology-modals,cables,routers,cloud,dialogs"))
