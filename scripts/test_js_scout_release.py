#!/usr/bin/env python3
"""Снимок static/js/scout-release.js — пункт «Обновить скаута» в меню машины.

Пинится значениями: какой из исходов следует из ответа контроллера (выпуска нет,
скаут не умеет заменять себя, уже этот выпуск, та же программа под другим коммитом,
новый), что сказано оператору в
каждом, что без согласия на провод ничего не уходит, что «взял» и «работает» —
разные слова: второе говорит только следующий отчёт машины, что скаут, который
ждёт запросы, идущие через него, так и назван и за ним следят столько, сколько
он может ждать, и что машина, не вернувшаяся за отведённое время, так и названа.

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
ONE_PROGRAM = {**OLD, "sameScout": True}
WAITING = {"ok": True, "commit": "new1", "restarting": False, "waiting": {"words": "box 1: not now: :22001 is loading", "retrySec": 120, "tries": 15}}
WAITS = {"ok": True, "commit": "new1", "restarting": True, "waitsFor": {"words": ["2 requests through the machine's entry"], "requests": 2, "mostSec": 600}}
TRIES = 30
#: The looks a watch adds for a scout that waits up to ten minutes for its requests: one every 2 s.
PATIENCE_TRIES = 300


def only_said(words, outcome):
    return json.dumps({"outcome": outcome, "calls": [["/api/fleet/scout-release?hostId=box%201"]], "said": [words], "asked": [], "pauses": 0}, ensure_ascii=False)


PINS = [
    ("offer_of_each_answer",
     "",
     "[" + ", ".join(f"sr.ScoutRelease.offer({json.dumps(x)})" for x in (OLD, SAME, NO_BUNDLE, NO_WORD, {}, None, ONE_PROGRAM,
                                                                         {**OLD, "sameScout": None}, {**OLD, "sameScout": False})) + "]",
     json.dumps([{"kind": "new", "commit": "new1", "running": "old1"}, {"kind": "current", "commit": "new1", "running": "new1"},
                 {"kind": "no-release"}, {"kind": "cannot", "commit": "new1"}, {"kind": "no-release"}, {"kind": "no-release"},
                 {"kind": "same", "commit": "new1", "running": "old1"},
                 {"kind": "new", "commit": "new1", "running": "old1"}, {"kind": "new", "commit": "new1", "running": "old1"}]),
     "пять исходов из значений; negative: пустой ответ и его отсутствие — «выпуска нет», а не «новый»; "
     "negative: контроллер не может сравнить (null) или программы разные — «новый», а не «та же»"),
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
    ("one_program_under_another_commit_is_not_taken",
     "",
     f"await pressed({{ answers: [{json.dumps(ONE_PROGRAM)}] }})",
     only_said(en("scoutUpdateSame", host="box 1", running="old1", commit="new1"), "same"),
     "negative: та же программа под другим коммитом — сказано, вопроса нет, ничего не перезапускается"),
    ("a_busy_scout_is_taken_over_by_the_cycle",
     "",
     f"await pressed({{ answers: [{json.dumps(OLD)}], update: {json.dumps(WAITING)} }})",
     json.dumps({"outcome": "waiting", "calls": [["/api/fleet/scout-release?hostId=box%201"], ["/api/fleet/scout-update", "POST", UPDATE_BODY]],
                 "said": [en("scoutUpdateWaiting", host="box 1", commit="new1", why="box 1: not now: :22001 is loading", minutes=2, total=30)],
                 "asked": [[en("scoutUpdateAsk", host="box 1", running="old1", commit="new1"), en("scoutUpdateOk")]], "pauses": 0}, ensure_ascii=False),
     "занятый скаут: контроллер спрашивает снова сам, сказано как часто и как долго; negative: «взял» не сказано, за отчётом не следим"),
    ("a_waiting_answer_without_figures_says_dashes",
     "",
     f"await (async () => {{ const seen = await pressed({{ answers: [{json.dumps(OLD)}], update: {{ ok: true, waiting: {{ words: 'not now' }} }} }}); return [seen.outcome, seen.said]; }})()",
     json.dumps(["waiting", [en("scoutUpdateWaiting", host="box 1", commit="new1", why="not now", minutes="—", total="—")]], ensure_ascii=False),
     "negative: ответ без чисел — прочерки, а не выдуманные минуты"),
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
    ("taken_and_restarts_once_its_requests_are_done",
     "",
     f"await pressed({{ answers: [{json.dumps(OLD)}, {json.dumps(OLD)}, {json.dumps(SAME)}], update: {json.dumps(WAITS)} }})",
     json.dumps({"outcome": "done",
                 "calls": [["/api/fleet/scout-release?hostId=box%201"], ["/api/fleet/scout-update", "POST", UPDATE_BODY],
                           ["/api/fleet/scout-release?hostId=box%201"], ["/api/fleet/scout-release?hostId=box%201"]],
                 "said": [en("scoutUpdateTakenWaits", host="box 1", commit="new1", why="2 requests through the machine's entry", minutes=10),
                          en("scoutUpdateDone", host="box 1", commit="new1")],
                 "asked": [[en("scoutUpdateAsk", host="box 1", running="old1", commit="new1"), en("scoutUpdateOk")]], "pauses": 2}, ensure_ascii=False),
     "скаут взял выпуск, но через него идут запросы: сказано, что он перезапустится, когда они закончатся, и самое долгое; "
     "«работает» — по-прежнему только по отчёту машины"),
    ("a_scout_that_waits_is_watched_as_long_as_it_may_wait",
     "",
     f"await (async () => {{ const seen = await pressed({{ answers: [{json.dumps(OLD)}], update: {json.dumps(WAITS)} }}); return [seen.outcome, seen.pauses, seen.said.slice(1)]; }})()",
     json.dumps(["silent", TRIES + PATIENCE_TRIES, [en("scoutUpdateSilent", host="box 1", commit="new1")]], ensure_ascii=False),
     "negative: за отчётом следят столько, сколько скаут может ждать свои запросы, и ещё обычную минуту — а не минуту, после "
     "которой ждущего скаута назвали бы молчащим"),
    ("a_wait_without_figures_says_dashes_and_adds_no_looks",
     "",
     f"await (async () => {{ const seen = await pressed({{ answers: [{json.dumps(OLD)}], update: {{ ok: true, restarting: true, waitsFor: {{ words: 'x', mostSec: null }} }} }}); return [seen.outcome, seen.pauses, seen.said[0]]; }})()",
     json.dumps(["silent", TRIES, en("scoutUpdateTakenWaits", host="box 1", commit="new1", why="—", minutes="—")], ensure_ascii=False),
     "negative: ответ без слов списком и без срока — прочерки, а не выдуманные минуты, и к обычной слежке ничего не прибавлено"),
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
