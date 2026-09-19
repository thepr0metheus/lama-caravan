#!/usr/bin/env python3
"""Snapshot of static/js/model-moves.js — moves into a library, drawn in the /models tree.

The module is a class (MoveTracker) with one face, mountMoves. There is no panel
of jobs: what a move says is said on the rows. Pinned by value:

- a travelling file carries its bar on its own row — where to, the pass
  (copying, then checking the copy), and once two answers are in, the speed
  and the time left — with Stop beside it; a queued one says so; every row
  state has its word, and a code the page does not know is shown as it is;
- a pass the library holds up turns red and says why; the queued file behind
  it does not;
- a finished move leaves a note only on a file it left here, with the reason;
  a failed one gives its own reason; one stopped by hand says nothing; the
  newest job holding a file decides; a hidden note stays hidden after a reload
  (a storage that throws only forgets);
- a folded branch says how far its files are; one line by the move button
  counts everything on its way and opens the branches it is in;
- polling runs while something moves and stops after; bytes move in place,
  a file arriving or staying tells the page to redraw — so does the first
  answer when it holds anything to draw;
- the button below: named after the one library, disabled with nothing
  movable or no library, a choice when there are several; starting asks first
  and posts only files; ⇢ on a row or a branch does the same for its own files
  without folding the branch, straight to the one library or through a short
  list when there are more (the list closes on Escape or a click elsewhere);
- Stop asks first — and says so when the move carries more than this file.

Timers are caught, not run: a pin fires the poll it wants by hand. Time is a
clock the pin sets. Long English texts come from static/js/i18n/en.js.

Run: python3 scripts/test_js_model_moves.py
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _node import find_node, node_search_paths  # noqa: E402

# The same neighbours the models page stubs: the real i18n.js and utils.js pull
# the rest of the app in behind them.
STUBS = ("dialogs,dialog-llamas,polling,canvas,topology-dnd,topology-render,charts,cables,cloud,history,favorites,"
         "config-locator,system-panels,onboarding,onboarding-tours,usage-stats,system-page,memory,command-preview,"
         "llama-edit,remote-cells,topology-nodes,topology-modals,routers,topology-activity,topology-proxies,model-meta,form")


def _english():
    """Every one-string line of en.js; a line holding anything else is skipped."""
    out = {}
    for key, raw in re.findall(r'^  (\w+): (".*"),$', (ROOT / "static/js/i18n/en.js").read_text(encoding="utf-8"), re.M):
        try:
            out[key] = json.loads(raw)
        except ValueError:
            continue
    return out


EN = _english()


def en(key, **kw):
    text = EN[key]
    for k, v in kw.items():
        text = text.replace("{" + k + "}", str(v))
    return text


Q = "Qwen/unsloth/Q4/q.gguf"
#: The controller's own disk as the page names it — and as it reads once the
#: page has escaped it for an attribute or a text node.
LOCAL_ESC = EN["storeLocalName"].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#39;")
ROW_Q = ('<span class="mdl-dl mdl-move-bar" data-t="models-move-progress" data-t-id="%s" data-move-job="mv-1" data-move-path="%s"'
         ' title="2.50 GB / 10.0 GB"><span class="mdl-dl-bar" style="width:25%%"></span><span class="mdl-dl-text">⇢ NAS · copying 25%%</span></span>'
         '<button class="mdl-mini mdl-move-stop" type="button" data-move-stop="mv-1" data-t="models-move-stop" data-t-id="%s"'
         ' title="Stop" aria-label="Stop">✕</button>') % (Q, Q, Q)
STAYED_B = ('<span class="mdl-stayed" data-t="models-move-stayed" data-t-id="b/b.gguf">⚠ %s</span>'
            '<button class="mdl-mini" type="button" data-move-seen="mv-1" data-move-seen-path="b/b.gguf" data-t="models-move-dismiss"'
            ' data-t-id="b/b.gguf" title="%s" aria-label="%s">×</button>') % (
    en("movePhaseSkipped", why=EN["moveNoteInUse"]), EN["moveStayedHide"], EN["moveStayedHide"])


def branch(trail, text, stalled=False):
    return (f'<span class="mdl-move-branch{" stalled" if stalled else ""}" data-t="models-move-branch" data-t-id="{trail}"'
            f' data-move-branch="{trail}">{text}</span>')


def go(value, scope, size=None, title="Move to NAS", frm=None, kind=None):
    sized = f' data-size="{size}"' if size is not None else ""
    source = f' data-move-from="{frm}"' if frm else ""
    folder = f' data-kind="{kind}"' if kind else ""
    return (f'<button class="mdl-go" type="button" data-move-open="{value}" data-move-scope="{scope}"{source}{sized}{folder}'
            f' data-t="models-move-open" data-t-id="{value}" title="{title}" aria-label="{title}">⇢</button>')


PREAMBLE = r"""
import "./_js_globals.mjs";
import { pathToFileURL } from "node:url";
const m = await import(pathToFileURL(process.env.JS_ROOT + "/model-moves.js").href);
// Timers are caught, not run: a poll firing inside a later pin would add its
// requests to that pin's record. A pin fires the one it wants by hand.
globalThis.__timers = [];
globalThis.setTimeout = (fn, ms) => { globalThis.__timers.push({ fn, ms }); return globalThis.__timers.length; };
globalThis.clearTimeout = () => {};
const cls = () => { const s = new Set(); return { add: (...c) => c.forEach((x) => s.add(x)), remove: (...c) => c.forEach((x) => s.delete(x)), has: (c) => s.has(c), toggle: (c, on) => { if (on) s.add(c); else s.delete(c); } }; };
const mkEl = () => ({ textContent: "", innerHTML: "", value: "", title: "", hidden: false, disabled: false, classList: cls(), listeners: {}, addEventListener(t, fn) { (this.listeners[t] ||= []).push(fn); } });
// The tree hands out, per selector, the elements a pin planted: enough to see
// what update() paints in place and what reveal() opens.
const mkTree = () => { const r = mkEl(); r.querySelectorAll = (sel) => globalThis.__planted[sel] || []; r.querySelector = (sel) => (globalThis.__planted[sel] || [])[0] || null; return r; };
const plant = (dataset) => { const bar = { style: { width: "" } }; const text = { textContent: "" }; return { dataset, bar, text, textContent: "", title: "", classList: cls(), querySelector: (s) => (s === ".mdl-dl-bar" ? bar : s === ".mdl-dl-text" ? text : null) }; };
const mkStorage = () => ({ data: {}, getItem(k) { return k in this.data ? this.data[k] : null; }, setItem(k, v) { this.data[k] = String(v); } });
const GB = 2 ** 30;
const JOB = (over = {}) => ({ id: "mv-1", target: { id: "lib-a", name: "NAS" }, status: "running", reason: "", createdAt: 2, finishedAt: 0,
  totalBytes: 14 * GB, movedBytes: 0, workDone: 2.5 * GB, workTotal: 28 * GB, items: 2, itemsDone: 0,
  files: [{ path: "Qwen/unsloth/Q4/q.gguf", item: "pending", phase: "copying", done: 2.5 * GB, size: 10 * GB, note: "", detail: "" },
          { path: "gemma/g.gguf", item: "pending", phase: "", done: 0, size: 4 * GB, note: "", detail: "" }], ...over });
const LIBS = () => [{ id: "local", role: "local", state: "ok", name: "", builtin: true },
  { id: "lib-a", role: "library", state: "ok", name: "NAS", free: 900 * GB, total: 1000 * GB }, { id: "lib-b", role: "library", state: "not-mounted", name: "Old" }];
const calls = () => globalThis.__fetchCalls.map((c) => ({ path: c.path, method: c.method, body: c.body === null ? null : JSON.parse(c.body) }));
const settle = async () => { for (let i = 0; i < 8; i++) await new Promise((r) => setImmediate(r)); };
const polls = () => globalThis.__timers.filter((x) => x.ms === 1200);
const tick = async () => { await polls().pop().fn(); await settle(); };
// The document's own listeners (the list's Escape and click-elsewhere) and the
// elements it makes (the list itself).
const docL = {};
document.addEventListener = (t, fn) => { (docL[t] ||= []).push(fn); };
document.removeEventListener = (t, fn) => { docL[t] = (docL[t] || []).filter((x) => x !== fn); };
const mkMenu = () => { const el = mkEl(); el.dataset = {}; el.style = {}; el.attrs = {}; el.removed = 0; el.setAttribute = (k, v) => { el.attrs[k] = v; }; el.remove = () => { el.removed += 1; }; el.contains = (x) => x === el; return el; };
const reset = () => { globalThis.__fetchCalls.length = 0; globalThis.__fetchReply = {}; globalThis.__fields = { toast: mkEl() }; globalThis.__timers.length = 0;
  globalThis.__planted = {}; globalThis.__confirms = []; globalThis.__confirmAnswer = true; globalThis.__changes = 0; globalThis.__now = 1000000;
  for (const k of Object.keys(docL)) delete docL[k];
  document.createElement = () => mkMenu(); document.body = { appended: [], appendChild(el) { this.appended.push(el); } };
  globalThis.__stubReturns = { "dialogs.appConfirm": async (msg, opts) => { globalThis.__confirms.push([msg, opts && opts.confirmLabel, opts && opts.title, opts && opts.scene]); return globalThis.__confirmAnswer !== false; } }; };
const mount = async (jobs = [JOB()], opts = {}) => { globalThis.__fetchReply["/api/model-stores/moves"] = { ok: true, jobs };
  const tree = mkTree(); const summary = mkEl(); const button = mkEl(); const select = mkEl();
  const p = m.MoveTracker.mount({ tree, summary, button, select, picked: opts.picked || (() => []), stores: opts.stores || (() => LIBS()),
    onChange: () => { globalThis.__changes += 1; }, onReveal: opts.onReveal, now: () => globalThis.__now, storage: "storage" in opts ? opts.storage : mkStorage() });
  await settle(); const first = globalThis.__changes; globalThis.__changes = 0; globalThis.__fetchCalls.length = 0;
  return { p, tree, summary, button, select, first }; };
// A click on the tree: the target answers closest() for one selector only.
const on = (sel, el) => ({ closest: (s) => (s === sel ? el : null) });
const click = (tree, target) => { let prevented = 0; const r = tree.listeners.click[0]({ target, preventDefault: () => { prevented += 1; } }); return { r, prevented: () => prevented }; };
const text = (h) => (h.match(/mdl-dl-text">([^<]*)</) || [])[1] ?? null;
const note = (h) => (h.match(/data-t="models-move-stayed"[^>]*>([^<]*)</) || [])[1] ?? null;
reset();
const out = {};
"""

PINS = [
    ("nothing_before_or_without_moves", '',
     r"""await (async () => { const a = await mount([]); const bare = new m.MoveTracker({ summary: mkEl(), storage: mkStorage() });
       return [a.summary.hidden, a.summary.textContent, a.p.rowHtml("x"), a.p.branchHtml("x"), a.p.shape(), polls().length, bare.rowHtml("x"), bare.summaryText(), a.first]; })()""",
     '[true,"","","","",0,"","",0]',
     'переносов нет — ни полос, ни строки у кнопки, опрос не запущен; до первого ответа тоже пусто, и странице не о чем сообщать'),
    ("a_travelling_file_carries_its_bar_on_its_row", '',
     r"""await (async () => { const { p } = await mount(); return [p.rowHtml("Qwen/unsloth/Q4/q.gguf"), text(p.rowHtml("gemma/g.gguf")), p.rowHtml("llama/l.gguf"), polls().length]; })()""",
     json.dumps([ROW_Q, "⇢ NAS · in line", "", 1], ensure_ascii=False),
     'файл в пути несёт полосу НА СВОЕЙ строке: куда, какой проход и сколько, байты — в подсказке, «Остановить» рядом; ждущий очереди так и назван; файлу не в пути — пусто; опрос запущен'),
    ("every_row_has_its_word", '',
     r"""(() => { const j = { id: "x", status: "running" }; const done = { id: "x", status: "done" }; const wait = { id: "x", status: "waiting", reason: "OSError" }; const waitBare = { id: "x", status: "waiting", reason: "" };
       const rows = [
         [j, { item: "pending", phase: "" }], [j, { item: "pending", phase: "copying", done: GB, size: 4 * GB }], [j, { item: "pending", phase: "checking", done: 3 * GB, size: 4 * GB }],
         [j, { item: "pending", phase: "proven" }], [j, { item: "removing", phase: "removed" }], [done, { item: "done", phase: "removed" }],
         [done, { item: "skipped", phase: "", note: "in-use" }], [done, { item: "skipped", note: "mismatch" }], [done, { item: "skipped", note: "brand-new-code" }],
         [done, { item: "cancelled", phase: "copying", done: GB, size: 4 * GB }], [{ id: "x", status: "failed" }, { item: "pending", phase: "copying", done: GB, size: 4 * GB }],
         [wait, { item: "pending", phase: "copying", done: GB, size: 4 * GB }], [wait, { item: "pending", phase: "" }], [waitBare, { item: "pending", phase: "checking", done: 2 * GB, size: 4 * GB }]];
       return rows.map(([jj, r]) => { const v = m.MoveTracker.view(jj, r); return [v.kind, v.label, v.width, v.stalled]; }); })()""",
     json.dumps([["queued", "in line", 0, False], ["copying", "copying 25%", 25, False], ["checking", "checking the copy 75%", 75, False],
                 ["checked", "copy checked", 100, False], ["moved", "", 100, False], ["moved", "", 100, False],
                 ["skipped", en("movePhaseSkipped", why=EN["moveNoteInUse"]), 0, True], ["skipped", en("movePhaseSkipped", why=EN["moveNoteMismatch"]), 0, True],
                 ["skipped", en("movePhaseSkipped", why="brand-new-code"), 0, True], ["stopped", "", 0, True], ["stopped", "", 0, True],
                 ["waiting", en("moveRowWaiting", why="OSError"), 25, True], ["queued", "in line", 0, False], ["waiting", "waiting for the library", 50, True]]),
     'у каждой судьбы строки своё слово: очередь, копия и сверка с процентом прохода, сверено, перенесён; не перенесён — с причиной, незнакомая причина как есть; остановленный — красный; проход, который держит библиотека, — красный, с причиной или без неё; ждущий очереди за ним — нет'),
    ("speed_and_time_left_come_from_answers", '',
     r"""await (async () => { const { p, summary } = await mount(); const bar = plant({ moveJob: "mv-1", movePath: "Qwen/unsloth/Q4/q.gguf" }); globalThis.__planted = { "[data-move-path]": [bar] };
       const first = text(p.rowHtml("Qwen/unsloth/Q4/q.gguf"));
       const step = async (done) => { const j = JOB({ workDone: done * GB }); j.files[0].done = done * GB; globalThis.__fetchReply["/api/model-stores/moves"] = { ok: true, jobs: [j] }; globalThis.__now += 10000; await tick(); return bar.text.textContent; };
       const second = await step(3.5); const third = await step(5.5);
       return [first, second, third, summary.textContent, globalThis.__changes]; })()""",
     json.dumps(["⇢ NAS · copying 25%",
                 "⇢ NAS · copying 35% · 102 MB/s · " + en("moveEtaMinutes", n=3),
                 "⇢ NAS · copying 55% · 133 MB/s · " + en("moveEtaMinutes", n=2),
                 en("movesInFlight", n=2, pct=20) + " · " + en("moveEtaMinutes", n=3), 0], ensure_ascii=False),
     'скорость и остаток — из двух ответов, не из одного: первый — только проход; 1 ГБ за 10 с — 102 МБ/с и ~3 мин на оставшиеся копию и сверку; следующее чтение сглажено (133, не 205); строка у кнопки считает всё в пути'),
    ("a_checked_copy_counts_down_to_its_removal", '',
     r"""await (async () => { const proven = (removeIn) => { const j = JOB({ workDone: 20 * GB, workTotal: 20 * GB, totalBytes: 10 * GB }); j.files = [{ ...j.files[0], phase: "proven", done: 10 * GB, removeIn }]; return j; };
       const a = await mount([proven(95)]); const b = await mount([proven(0)]);
       return [text(a.p.rowHtml("Qwen/unsloth/Q4/q.gguf")), a.summary.textContent, text(b.p.rowHtml("Qwen/unsloth/Q4/q.gguf")), b.summary.textContent]; })()""",
     json.dumps(["⇢ NAS · copy checked · " + en("moveEtaMinutes", n=2), en("movesInFlight", n=1, pct=100) + " · " + en("moveEtaMinutes", n=2),
                 "⇢ NAS · copy checked", en("movesInFlight", n=1, pct=100)], ensure_ascii=False),
     'сверенная копия ждёт, пока библиотека точно сохранит запись, — строка и строка у кнопки считают это ожидание вниз, а не стоят на «сверено» и «100%» две минуты молча; ждать нечего — ничего и не сказано'),
    ("a_pause_keeps_the_last_speed", '',
     r"""await (async () => { const { summary } = await mount(); const bar = plant({ moveJob: "mv-1", movePath: "Qwen/unsloth/Q4/q.gguf" }); globalThis.__planted = { "[data-move-path]": [bar] };
       const step = async (done) => { const j = JOB({ workDone: done * GB }); j.files[0].done = done * GB; globalThis.__fetchReply["/api/model-stores/moves"] = { ok: true, jobs: [j] }; globalThis.__now += 10000; await tick(); return bar.text.textContent; };
       await step(3.5); const paused = await step(3.5); return [paused, summary.textContent]; })()""",
     json.dumps(["⇢ NAS · copying 35% · 102 MB/s · " + en("moveEtaMinutes", n=3), en("movesInFlight", n=2, pct=13) + " · " + en("moveEtaMinutes", n=5)], ensure_ascii=False),
     'пауза в байтах (ожидание после сверки, библиотека держит) — не медленная сеть: скорость держит последнее значение, иначе остаток очереди рос бы без предела (живьём было «~299 ч»)'),
    ("the_wait_and_the_bytes_add_up", '',
     r"""await (async () => { const j = JOB({ workDone: 20 * GB }); j.files[0] = { ...j.files[0], phase: "proven", done: 10 * GB, removeIn: 55 };
       const { p, summary } = await mount([j]); p.pace.set("mv-1", { t: globalThis.__now, work: 20 * GB, rate: 100 * 2 ** 20 }); p.drawSummary(); return summary.textContent; })()""",
     json.dumps(en("movesInFlight", n=2, pct=71) + " · " + en("moveEtaMinutes", n=3), ensure_ascii=False),
     'остаток у кнопки — ожидание перед удалением сверенной копии ПЛЮС байты очереди по последней скорости (55 с + 82 с), а не большее из двух: работник берёт их по очереди'),
    ("no_speed_yet_no_time_left", '',
     r"""await (async () => { const proven = JOB({ workDone: 20 * GB }); proven.files[0] = { ...proven.files[0], phase: "proven", done: 10 * GB, removeIn: 19 };
       const queued = JOB({ id: "mv-2", status: "queued" }); queued.files = [{ ...queued.files[0], path: "B/b.gguf", phase: "", done: 0, size: 160 * GB }];
       const { p, summary } = await mount([proven, queued]); const unknown = summary.textContent;
       p.pace.set("mv-1", { t: globalThis.__now, work: 20 * GB, rate: 200 * 2 ** 20 }); p.drawSummary(); const known = summary.textContent;
       return [unknown, known]; })()""",
     json.dumps([en("movesInFlight", n=3, pct=6), en("movesInFlight", n=3, pct=6) + " · " + en("moveEtaMinutes", n=29)], ensure_ascii=False),
     'negative: байты ещё в очереди, а скорость не измерена (страницу только что открыли, работник стоит у сверенной копии) — остатка НЕТ, а не «~20 с»: '
     'живьём так читалось 17 файлов и 324 ГБ работы; как только скорость есть — остаток честный: 19 с ожидания + 328 ГБ работы по 200 МБ/с ≈ 29 мин'),
    ("time_left_and_speed_in_words", '',
     r"""(() => [[0, -1, NaN, 3, 40, 58, 60, 185, 3599, 3900, 7260].map((s) => m.MoveTracker.eta(s)), [0, 5e5, 107374182.4, 2 ** 31].map((b) => m.MoveTracker.speed(b))])()""",
     json.dumps([["", "", "", en("moveEtaSeconds", n=5), en("moveEtaSeconds", n=40), en("moveEtaMinutes", n=1), en("moveEtaMinutes", n=1),
                  en("moveEtaMinutes", n=4), en("moveEtaHours", h=1, m=0), en("moveEtaHours", h=1, m=5), en("moveEtaHours", h=2, m=1)],
                 ["", "1 MB/s", "102 MB/s", "2.0 GB/s"]], ensure_ascii=False),
     'остаток словами: неизвестно — ничего; секунды — шагом 5, от минуты — минуты вверх, от часа — часы и минуты; скорость — МБ/с, от 1 ГБ/с — ГБ/с'),
    ("waiting_says_why_and_turns_red", '',
     r"""await (async () => { const { p } = await mount([JOB({ status: "waiting", reason: "OSError: [Errno 5] Input/output error" })]);
       const q = p.rowHtml("Qwen/unsloth/Q4/q.gguf"); const g = p.rowHtml("gemma/g.gguf");
       return [q.startsWith('<span class="mdl-dl mdl-move-bar stalled"'), text(q), g.startsWith('<span class="mdl-dl mdl-move-bar stalled"'), p.branchHtml("Qwen"), p.branchHtml("gemma")]; })()""",
     json.dumps([True, "⇢ NAS · " + en("moveRowWaiting", why="OSError: [Errno 5] Input/output error"), False,
                 branch("Qwen", "⇢ 1 · 13%", True), branch("gemma", "⇢ 1 · 0%")], ensure_ascii=False),
     'библиотека держит проход — полоса красная и говорит причину, ветка с ним красная; файл, ждущий очереди за ним, и его ветка — нет: он и не начинался'),
    ("a_finished_move_leaves_notes_only_where_it_left_files", '',
     r"""await (async () => { const files = [{ path: "a/a.gguf", item: "done", phase: "removed", done: GB, size: GB, note: "", detail: "" },
       { path: "b/b.gguf", item: "skipped", phase: "proven", done: GB, size: GB, note: "in-use", detail: "" },
       { path: "c/c.gguf", item: "skipped", phase: "", done: 0, size: GB, note: "unlink-failed", detail: "PermissionError: denied" }];
       const { p, summary } = await mount([JOB({ status: "done", files })]);
       return [p.rowHtml("b/b.gguf"), p.stayedHtml("a/a.gguf"), p.stayedHtml("b/b.gguf"), p.stayedHtml("c/c.gguf").includes('data-t-id="c/c.gguf" title="PermissionError: denied">'), note(p.stayedHtml("c/c.gguf")), summary.hidden, polls().length]; })()""",
     json.dumps(["", "", STAYED_B, True, "⚠ " + en("movePhaseSkipped", why=EN["moveNoteUnlinkFailed"]), True, 0], ensure_ascii=False),
     'законченный перенос: пометка — только у файла, который остался здесь, с причиной (подробность — в подсказке) и кнопкой «скрыть»; перенесённый уже в библиотеке; строка у кнопки спрятана, опрос не идёт'),
    ("a_failed_move_gives_its_reason_a_stop_by_hand_says_nothing", '',
     r"""await (async () => { const f = (path, item, phase) => ({ path, item, phase, done: 0, size: GB, note: item === "skipped" ? "in-use" : "", detail: "" });
       const { p } = await mount([JOB({ id: "mv-3", status: "failed", reason: "the library vanished", files: [f("f/f.gguf", "pending", "copying")] }),
                                 JOB({ id: "mv-2", status: "cancelled", files: [f("s/s.gguf", "cancelled", "copying"), f("k/k.gguf", "skipped", "")] })]);
       return [note(p.stayedHtml("f/f.gguf")), p.stayedHtml("s/s.gguf"), note(p.stayedHtml("k/k.gguf"))]; })()""",
     json.dumps(["⚠ " + en("movePhaseSkipped", why="the library vanished"), "", "⚠ " + en("movePhaseSkipped", why=EN["moveNoteInUse"])], ensure_ascii=False),
     'упавший перенос называет свою причину на каждом оставленном файле; остановленный руками молчит (оператор знает), но файл, пропущенный ещё до остановки, свою причину сохраняет'),
    ("a_folder_left_behind_says_what_stopped_it", '',
     r"""await (async () => { const f = (path, note) => ({ path, item: "skipped", phase: "", done: 0, size: GB, note, detail: "" });
       const { p } = await mount([JOB({ id: "mv-4", status: "done", files: [f("w/link-out", "link-out"), f("w/odd", "folder-odd"), f("w/changed", "folder-changed")] })]);
       return ["w/link-out", "w/odd", "w/changed"].map((x) => note(p.stayedHtml(x))); })()""",
     json.dumps(["⚠ " + en("movePhaseSkipped", why=EN["moveNoteLinkOut"]),
                 "⚠ " + en("movePhaseSkipped", why=EN["moveNoteFolderOdd"]),
                 "⚠ " + en("movePhaseSkipped", why=EN["moveNoteFolderChanged"])], ensure_ascii=False),
     'папка, которую перенос не взял, называет причину словами, а не кодом: ссылка наружу, не-файл внутри, изменилась по дороге — все три на языке страницы'),
    ("the_newest_job_decides", '',
     r"""await (async () => { const b = (over) => ({ path: "b/b.gguf", item: "pending", phase: "copying", done: GB, size: 4 * GB, note: "", detail: "", ...over });
       const a = await mount([JOB({ id: "mv-2", files: [b({})] }), JOB({ id: "mv-1", status: "done", files: [b({ item: "skipped", phase: "", note: "in-use" })] })]);
       const r1 = [a.p.rowHtml("b/b.gguf") !== "", a.p.stayedHtml("b/b.gguf")];
       const c = await mount([JOB({ id: "mv-3", status: "done", files: [b({ item: "done", phase: "removed" })] }), JOB({ id: "mv-1", status: "done", files: [b({ item: "skipped", phase: "", note: "in-use" })] })]);
       return [...r1, c.p.stayedHtml("b/b.gguf"), c.p.rowHtml("b/b.gguf")]; })()""",
     '[true,"","",""]',
     'о файле говорит самый новый перенос: снова в пути — полоса без старой пометки; перенесён позже — старая пометка не всплывает'),
    ("hiding_a_note_is_remembered", '',
     r"""await (async () => { const files = [{ path: "b/b.gguf", item: "skipped", phase: "", done: 0, size: GB, note: "in-use", detail: "" }]; const store = mkStorage();
       const { p, tree } = await mount([JOB({ status: "done", files })], { storage: store });
       let removed = 0; const noteEl = { dataset: { t: "models-move-stayed" }, remove: () => { removed += 1; } };
       const btn = { dataset: { moveSeen: "mv-1", moveSeenPath: "b/b.gguf" }, previousElementSibling: noteEl, remove: () => { removed += 1; } };
       click(tree, on("[data-move-seen]", btn)); await settle(); const changes = globalThis.__changes;
       const again = await mount([JOB({ status: "done", files })], { storage: store }); const fresh = await mount([JOB({ status: "done", files })]);
       return [removed, store.data["mdl.moveSeen"], p.stayedHtml("b/b.gguf"), again.p.stayedHtml("b/b.gguf"), fresh.p.stayedHtml("b/b.gguf") !== "", changes]; })()""",
     '[2,"[\\"mv-1|b/b.gguf\\"]","","",true,0]',
     'скрытая пометка уходит НА МЕСТЕ (перерисовка свернула бы ветку) и помнится браузером: после перезагрузки её нет; в другом браузере — есть'),
    ("a_broken_storage_only_forgets", '',
     r"""(() => { const bad = { getItem() { throw new Error("denied"); }, setItem() { throw new Error("denied"); } }; const p = new m.MoveTracker({ storage: bad });
       p.dismiss({ dataset: { moveSeen: "mv-1", moveSeenPath: "b/b.gguf" }, previousElementSibling: null, remove() {} }); return [...p.seen]; })()""",
     '["mv-1|b/b.gguf"]',
     'negative: хранилище браузера бросает — пометка скрыта на этот визит, ошибки нет'),
    ("a_folded_branch_says_how_far", '',
     r"""await (async () => { const { p } = await mount(); return ["Qwen", "Qwen/unsloth", "Qwen/unsloth/Q4", "gemma", "llama", "Qwe"].map((b) => p.branchHtml(b)); })()""",
     json.dumps([branch("Qwen", "⇢ 1 · 13%"), branch("Qwen/unsloth", "⇢ 1 · 13%"), branch("Qwen/unsloth/Q4", "⇢ 1 · 13%"),
                 branch("gemma", "⇢ 1 · 0%"), "", ""], ensure_ascii=False),
     'свёрнутая ветка говорит, сколько её файлов в пути и как далеко (копия и сверка — два прохода) — на каждом уровне; ветка без переносов молчит, и начало имени — не ветка'),
    ("the_line_by_the_button", '',
     r"""await (async () => { const { summary } = await mount(); const a = [summary.hidden, summary.textContent, summary.title];
       globalThis.__fetchReply["/api/model-stores/moves"] = { ok: true, jobs: [JOB({ status: "done", files: [] })] }; await tick();
       return [...a, summary.hidden, summary.textContent]; })()""",
     json.dumps([False, en("movesInFlight", n=2, pct=9), EN["movesInFlightTip"], True, ""], ensure_ascii=False),
     'строка у кнопки: сколько файлов в пути и общий процент, подсказка — что по клику; всё закончилось — строка прячется'),
    ("polling_stops_when_nothing_moves", '',
     r"""await (async () => { await mount(); const a = polls().length; globalThis.__fetchReply["/api/model-stores/moves"] = { ok: true, jobs: [JOB({ status: "done" })] }; await tick(); return [a, polls().length, calls().map((c) => c.path)]; })()""",
     '[1,1,["/api/model-stores/moves"]]',
     'опрос идёт, пока что-то едет, и сам останавливается, когда всё закончилось'),
    ("bytes_move_in_place_without_a_redraw", '',
     r"""await (async () => { const { summary } = await mount(); const bar = plant({ moveJob: "mv-1", movePath: "Qwen/unsloth/Q4/q.gguf" }); const br = plant({ moveBranch: "Qwen" });
       bar.classList.add("stalled"); globalThis.__planted = { "[data-move-path]": [bar], "[data-move-branch]": [br] };
       const j = JOB({ workDone: 5 * GB }); j.files[0].done = 5 * GB; globalThis.__fetchReply["/api/model-stores/moves"] = { ok: true, jobs: [j] }; await tick();
       return [bar.bar.style.width, bar.text.textContent, bar.title, bar.classList.has("stalled"), br.textContent, summary.textContent, polls().length, globalThis.__changes]; })()""",
     json.dumps(["50%", "⇢ NAS · copying 50%", "5.00 GB / 10.0 GB", False, "⇢ 1 · 25%", en("movesInFlight", n=2, pct=18), 2, 0], ensure_ascii=False),
     'сдвинулись только байты — дерево НЕ перерисовывается (свернуло бы ветки и съело клик по «Остановить»): полоса, слово, подсказка, цвет, чип ветки и строка у кнопки меняются на месте; страница не тревожится'),
    ("a_file_arriving_or_staying_tells_the_page", '',
     r"""await (async () => { await mount(); const j = JOB(); j.files[0] = { ...j.files[0], item: "done", phase: "removed", done: 10 * GB }; globalThis.__fetchReply["/api/model-stores/moves"] = { ok: true, jobs: [j] }; await tick(); const arrived = globalThis.__changes;
       await mount(); const k = JOB({ status: "done" }); k.files[0] = { ...k.files[0], item: "done", phase: "removed" }; k.files[1] = { ...k.files[1], item: "skipped", note: "in-use" };
       globalThis.__fetchReply["/api/model-stores/moves"] = { ok: true, jobs: [k] }; await tick(); return [arrived, globalThis.__changes]; })()""",
     '[1,1]',
     'файл приехал или остался с причиной — странице сказано: дерево и хранилища изменились'),
    ("the_first_answer_tells_the_page", '',
     r"""await (async () => { const a = await mount(); const b = await mount([]); const c = await mount([JOB({ status: "done", files: [] })]);
       const d = await mount([JOB({ status: "done", files: [{ path: "k/k.gguf", item: "skipped", phase: "", note: "in-use", size: GB, done: 0 }] })]); return [a.first, b.first, c.first, d.first]; })()""",
     '[1,0,0,1]',
     'первый ответ уже с файлами в пути или с пометкой (перенос из другой вкладки или до перезагрузки) — странице сказано сразу: дерево, нарисованное раньше, их не знает; нечего сказать — не тревожим'),
    ("on_its_way_means_still_here_and_still_travelling", '',
     r"""await (async () => { const files = [{ path: "a.gguf", item: "pending", phase: "copying" }, { path: "b.gguf", item: "removing", phase: "removed" }, { path: "c.gguf", item: "skipped", phase: "" }, { path: "d.gguf", item: "pending", phase: "proven" }];
       const { p } = await mount([JOB({ files }), JOB({ id: "mv-0", status: "done", files: [{ path: "e.gguf", item: "cancelled", phase: "" }] })]);
       return ["a.gguf", "b.gguf", "c.gguf", "d.gguf", "e.gguf"].map((x) => !!p.onWay(x)); })()""",
     '[true,false,false,true,false]',
     'в пути — то, что ещё здесь и ещё едет (сверенная копия ждёт удаления оригинала — тоже); уже удалённое здесь, пропущенное и файлы законченных задач — нет'),
    ("the_button_names_its_library", '',
     r"""await (async () => { const pick = () => [{ path: "a.gguf", size: GB, folder: false }];
       const one = await mount([], { picked: pick }); const none = await mount([], { picked: pick, stores: () => LIBS().filter((s) => s.id !== "lib-a") });
       const nothing = await mount([], { picked: () => [] }); const folderOnly = await mount([], { picked: () => [{ path: "whisper/x", size: GB, kind: "whisper" }] });
       const two = await mount([], { picked: pick, stores: () => [...LIBS(), { id: "lib-c", role: "library", state: "low-space", name: "Spare" }] });
       const loading = await mount([], { picked: pick, stores: () => null });
       const b = (x) => [x.button.textContent, x.button.disabled, x.button.title, x.select.hidden];
       return [b(one), b(none), b(nothing), b(folderOnly), b(two), two.select.innerHTML, b(loading)]; })()""",
     json.dumps([["Move to NAS", False, "", True], ["Move to library", True, EN["moveNoLibrary"], True],
                 ["Move to NAS", True, "", True], ["Move to NAS", False, "", True], ["Move to library", False, "", False],
                 '<option value="lib-a">NAS</option><option value="lib-c">Spare</option>', ["Move to library", True, "", True]]),
     'кнопка внизу: одна библиотека — её имя; нет доступной — выключена и говорит, чего не хватает (но не пока хранилища ещё не ответили); нечего выбрано — выключена, а одна папка — уже есть что переносить; две библиотеки — выбор, «мало места» не мешает'),
    ("start_asks_then_posts_files_and_target", '',
     r"""await (async () => { const picked = () => [{ path: "a/a.gguf", size: 4 * GB }, { path: "b/b.gguf", size: 6 * GB }, { path: "whisper/models--x", size: GB, kind: "whisper" }];
       const { button } = await mount([], { picked }); globalThis.__fetchReply["/api/model-stores/move"] = { ok: true, job: { id: "mv-9" } }; globalThis.__fetchReply["/api/model-stores/moves"] = { ok: true, jobs: [JOB({ id: "mv-9" })] };
       await button.listeners.click[0](); await settle(); return [globalThis.__confirms[0][0], globalThis.__confirms[0][1], globalThis.__confirms[0][2], calls(), globalThis.__changes, button.disabled]; })()""",
     json.dumps([en("moveConfirm", count=3, size="11.0 GB", name="NAS") + "\n\n" + en("moveConfirmFolders", n=1), "Move", EN["movesTitle"],
                 [{"path": "/api/model-stores/move", "method": "POST",
                   "body": {"files": ["a/a.gguf", "b/b.gguf", "whisper/models--x"], "to": "lib-a", "from": "local"}},
                  {"path": "/api/model-stores/moves", "method": "GET", "body": None}], 1, False]),
     'старт кнопкой: вопрос с числом предметов, их объёмом и библиотекой, с обещанием сверки до удаления и с тем, сколько из них папки (одна строка — тысячи файлов на проводе), под заголовком переносов; после «да» — пути всех предметов и id библиотеки; потом список переносов и сигнал странице'),
    ("the_move_dialogs_show_the_pack_llama", '',
     r"""await (async () => { const { button } = await mount([], { picked: () => [{ path: "a.gguf", size: GB }] });
       globalThis.__confirmAnswer = false; await button.listeners.click[0](); await settle();
       return globalThis.__confirms.map((c) => c[3]); })()""",
     '["move"]',
     'вопрос перед переносом показывает вьючную ламу с тюком, а не ламу, топчущую ящик: та сцена значит «удалить», '
     'и перенос выглядел как удаление'),
    ("a_declined_start_sends_nothing", '',
     r"""await (async () => { const { button } = await mount([], { picked: () => [{ path: "a.gguf", size: GB }] }); globalThis.__confirmAnswer = false; await button.listeners.click[0](); await settle(); return [calls().length, globalThis.__changes, button.disabled]; })()""",
     '[0,0,false]',
     'negative: «нет» на вопросе — ни одного запроса, кнопка на месте'),
    ("a_refused_start_is_a_toast", '',
     r"""await (async () => { const { button } = await mount([], { picked: () => [{ path: "a.gguf", size: GB }] }); globalThis.__fetchReply["/api/model-stores/move"] = { ok: false, code: "no-room", error: "the library has no room" };
       await button.listeners.click[0](); await settle(); return [globalThis.__fields.toast.textContent, calls().length, globalThis.__changes, button.disabled]; })()""",
     '["the library has no room",1,0,false]',
     'negative: сервер отказал — причина тостом, дерево не трогаем, кнопка снова доступна'),
    ("two_libraries_the_select_decides", '',
     r"""await (async () => { const stores = () => [...LIBS(), { id: "lib-c", role: "library", state: "ok", name: "Spare" }]; const picked = () => [{ path: "a.gguf", size: GB }];
       const a = await mount([], { picked, stores }); a.select.value = "lib-c"; globalThis.__fetchReply["/api/model-stores/move"] = { ok: true, job: { id: "mv-2" } };
       await a.button.listeners.click[0](); await settle(); const got = [globalThis.__confirms[0][0].includes("to Spare?"), calls()[0].body.to];
       reset(); const b = await mount([], { picked, stores }); b.select.value = "lib-gone"; await b.button.listeners.click[0](); await settle();
       return [...got, globalThis.__confirms.length, calls().length]; })()""",
     '[true,"lib-c",0,0]',
     'библиотек две — едет в выбранную, и вопрос называет её; выбранной больше нет — ни вопроса, ни запроса'),
    ("the_arrow_offers_itself_only_where_there_is_somewhere_to_go", '',
     r"""await (async () => { const one = await mount([]); const none = await mount([], { stores: () => LIBS().filter((s) => s.id !== "lib-a") });
       const two = await mount([], { stores: () => [...LIBS(), { id: "lib-c", role: "library", state: "ok", name: "Spare" }] });
       return [one.p.openHtml("file", "a/a.gguf", { size: GB }), one.p.openHtml("branch", "Qwen/unsloth"), none.p.openHtml("file", "a/a.gguf", { size: GB }),
               (two.p.openHtml("branch", "x").match(/title="([^"]*)"/) || [])[1], one.p.storesKey(), two.p.storesKey(), none.p.storesKey()]; })()""",
     json.dumps([go("a/a.gguf", "file", 1073741824), go("Qwen/unsloth", "branch"), "", "Move to library",
                 "local:|lib-a:NAS", "local:|lib-a:NAS|lib-c:Spare", "local:"], ensure_ascii=False),
     '⇢ у файла несёт его путь и размер, у ветки — её путь; подсказка называет единственное место назначения; идти некуда — нет и ⇢ (кнопка внизу говорит, чего не хватает); ключ хранилищ меняется с их составом'),
    ("the_arrow_of_a_library_row_sends_the_file_back", '',
     r"""await (async () => { const { p } = await mount([]); const html = p.openHtml("file", "L/l.gguf", { size: GB, from: "lib-a" });
       const folder = p.openHtml("file", "whisper/models--x", { size: GB, from: "lib-a", kind: "whisper" });
       return [html, (html.match(/title="([^"]*)"/) || [])[1], p.openHtml("file", "x", { size: GB, from: "lib-gone" }) === "", folder,
               p.openHtml("branch", "x", { kind: "whisper" }).includes("data-kind"), p.nameOf({ id: "local" }), p.nameOf({ id: "lib-a" }), p.nameOf({ id: "lib-gone", name: "Old" })]; })()""",
     json.dumps([go("L/l.gguf", "file", 1073741824, title="Move to " + LOCAL_ESC, frm="lib-a"),
                 "Move to " + LOCAL_ESC, False,
                 go("whisper/models--x", "file", 1073741824, title="Move to " + LOCAL_ESC, frm="lib-a", kind="whisper"),
                 False, EN["storeLocalName"], "NAS", "Old"], ensure_ascii=False),
     'у строки библиотеки ⇢ несёт «откуда»: единственное место назначения для неё — этот диск, и он назван теми же словами, что в панели хранилищ; хранилище, которого нет, названо как есть; ⇢ папки несёт и её вид, а ⇢ ветки — нет: ветка везёт то, что отмечено в ней'),
    ("every_arrow_asks_and_a_no_sends_nothing", '',
     r"""await (async () => { const stores = () => [...LIBS(), { id: "lib-c", role: "library", state: "ok", name: "Spare", free: 10 * GB, total: 20 * GB }];
       const one = await mount([]); globalThis.__confirmAnswer = false;
       const file = { dataset: { moveOpen: "a/a.gguf", moveScope: "file", size: String(GB) } };
       const rows = [{ dataset: { moveOpen: "Qwen/a.gguf", size: String(GB) } }];
       const branch = { dataset: { moveOpen: "Qwen", moveScope: "branch" }, closest: (s) => (s === "details" ? { querySelectorAll: () => rows } : null) };
       const back = { dataset: { moveOpen: "L/l.gguf", moveScope: "file", moveFrom: "lib-a", size: String(GB) } };
       for (const btn of [file, branch, back]) { const c = click(one.tree, on("[data-move-open]", btn)); await c.r; await settle(); }
       const firstPosts = calls().filter((x) => x.method === "POST").length;
       const two = await mount([], { stores }); globalThis.__confirmAnswer = false;
       const c = click(two.tree, on("[data-move-open]", { ...file, getBoundingClientRect: () => ({ left: 0, bottom: 0 }) })); await c.r; await settle();
       const menu = document.body.appended[document.body.appended.length - 1];
       menu.listeners.click[0]({ target: on("[data-move-dest]", { dataset: { moveDest: "lib-c" } }) }); await settle();
       return [globalThis.__confirms.length, firstPosts, calls().filter((x) => x.method === "POST").length]; })()""",
     '[4,0,0]',
     'negative: каждая ⇢ — у файла, у ветки, у строки библиотеки и выбор из списка библиотек — сначала спрашивает, и «нет» не отправляет ни одного переноса'),
    ("the_arrow_on_a_file_asks_and_moves_that_file", '',
     r"""await (async () => { const { tree } = await mount([]); globalThis.__fetchReply["/api/model-stores/move"] = { ok: true, job: { id: "mv-9" } }; globalThis.__fetchReply["/api/model-stores/moves"] = { ok: true, jobs: [JOB({ id: "mv-9" })] };
       const btn = { dataset: { moveOpen: "a/a.gguf", moveScope: "file", size: String(4 * GB) } }; const c = click(tree, on("[data-move-open]", btn)); await c.r; await settle();
       return [c.prevented(), globalThis.__confirms[0][0], calls().map((x) => [x.path, x.body]), globalThis.__changes]; })()""",
     json.dumps([1, en("moveConfirm", count=1, size="4.00 GB", name="NAS"),
                 [["/api/model-stores/move", {"files": ["a/a.gguf"], "to": "lib-a", "from": "local"}],
                  ["/api/model-stores/moves", None]], 1]),
     '⇢ у файла: тот же вопрос, что у кнопки, про этот один файл, и перенос в единственную библиотеку — без выбора галочками; клик не сворачивает ветку'),
    ("the_arrow_on_a_branch_moves_what_can_move", '',
     r"""await (async () => { const { tree } = await mount([]); globalThis.__fetchReply["/api/model-stores/move"] = { ok: true, job: { id: "mv-9" } };
       const rows = [{ dataset: { moveOpen: "Qwen/a.gguf", size: String(4 * GB) } }, { dataset: { moveOpen: "Qwen/b.gguf", size: String(6 * GB) } },
                     { dataset: { moveOpen: "Qwen/whisper-x", size: "5", kind: "whisper" } },
                     { dataset: { moveOpen: "Qwen/in-lib.gguf", size: String(GB), moveFrom: "lib-a" } }];
       const details = { querySelectorAll: (s) => (s === '[data-move-scope="file"]' ? rows : []) };
       const btn = { dataset: { moveOpen: "Qwen", moveScope: "branch" }, closest: (s) => (s === "details" ? details : null) };
       const c = click(tree, on("[data-move-open]", btn)); await c.r; await settle();
       return [globalThis.__confirms[0][0], calls()[0].body]; })()""",
     json.dumps([en("moveConfirm", count=3, size="10.0 GB", name="NAS") + "\n\n" + en("moveConfirmFolders", n=1),
                 {"files": ["Qwen/a.gguf", "Qwen/b.gguf", "Qwen/whisper-x"], "to": "lib-a", "from": "local"}]),
     '⇢ у ветки: везёт всё, у чего в ней есть своя ⇢ (здесь, не читается ячейкой, не в пути), — папки в том числе; строка из библиотеки не едет: ветка отправляет с ЭТОГО диска, и файла, которого тут нет, она не найдёт; вопрос называет, сколько из этого папки'),
    ("a_move_back_asks_and_posts_its_source", '',
     r"""await (async () => { const { tree } = await mount([]); globalThis.__fetchReply["/api/model-stores/move"] = { ok: true, job: { id: "mv-9" } };
       const btn = { dataset: { moveOpen: "L/l.gguf", moveScope: "file", moveFrom: "lib-a", size: String(2 * GB) } };
       const c = click(tree, on("[data-move-open]", btn)); await c.r; await settle();
       return [globalThis.__confirms[0][0], calls().map((x) => [x.path, x.body])]; })()""",
     json.dumps([en("moveConfirm", count=1, size="2.00 GB", name=EN["storeLocalName"]),
                 [["/api/model-stores/move", {"files": ["L/l.gguf"], "to": "local", "from": "lib-a"}],
                  ["/api/model-stores/moves", None]]], ensure_ascii=False),
     'перенос обратно: ⇢ у строки библиотеки везёт файл на этот диск — вопрос называет его теми же словами, а запрос несёт и «куда», и «откуда»'),
    ("a_row_on_its_way_home_says_where_it_goes", '',
     r"""await (async () => { const j = JOB({ target: { id: "local", name: "" } }); const { p } = await mount([j]);
       return [text(p.rowHtml("Qwen/unsloth/Q4/q.gguf")), p.summaryText()]; })()""",
     json.dumps(["⇢ " + LOCAL_ESC + " · copying 25%", en("movesInFlight", n=2, pct=9)], ensure_ascii=False),
     'полоса возврата называет этот диск словами панели хранилищ, а не пустым именем, которое хранилище отдаёт серверу'),
    ("two_libraries_the_arrow_offers_a_list", '',
     r"""await (async () => { const stores = () => [...LIBS(), { id: "lib-c", role: "library", state: "ok", name: "Spare", free: 10 * GB, total: 20 * GB }];
       const { tree } = await mount([], { stores }); globalThis.__fetchReply["/api/model-stores/move"] = { ok: true, job: { id: "mv-9" } };
       const btn = { dataset: { moveOpen: "a/a.gguf", moveScope: "file", size: String(GB) }, getBoundingClientRect: () => ({ left: 100, bottom: 40 }) };
       const c = click(tree, on("[data-move-open]", btn)); await c.r; await settle();
       const menu = document.body.appended[0]; const shown = [menu.className, menu.dataset.t, menu.attrs.role, menu.attrs["aria-label"], menu.style.left, menu.style.top,
         menu.innerHTML.includes('data-move-dest="lib-a"'), menu.innerHTML.includes('data-move-dest="lib-c"'), menu.innerHTML.includes("lib-b"), menu.innerHTML.includes("free of"), (docL.click || []).length, globalThis.__confirms.length];
       menu.listeners.click[0]({ target: on("[data-move-dest]", { dataset: { moveDest: "lib-c" } }) }); await settle();
       return [shown, menu.removed, (docL.click || []).length, (docL.keydown || []).length, globalThis.__confirms[0][0].includes("to Spare?"), calls()[0].body]; })()""",
     json.dumps([["mdl-move-menu", "models-move-menu", "menu", EN["a11yMoveMenu"], "100px", "44px", True, True, False, True, 1, 0],
                 1, 0, 0, True, {"files": ["a/a.gguf"], "to": "lib-c", "from": "local"}]),
     'библиотек две — у ⇢ короткий список (только доступные, со свободным местом) прямо под кнопкой; выбор закрывает список, спрашивает про выбранную и везёт туда'),
    ("the_list_closes_on_escape_or_a_click_elsewhere", '',
     r"""await (async () => { const stores = () => [...LIBS(), { id: "lib-c", role: "library", state: "ok", name: "Spare" }]; const { tree } = await mount([], { stores });
       const btn = { dataset: { moveOpen: "a/a.gguf", moveScope: "file", size: String(GB) } };
       click(tree, on("[data-move-open]", btn)); await settle(); const m1 = document.body.appended[0];
       docL.keydown[0]({ type: "keydown", key: "Tab" }); const tabKept = m1.removed; docL.keydown[0]({ type: "keydown", key: "Escape" });
       // Read at once: opening the next list closes this one anyway.
       const escaped = [m1.removed, (docL.keydown || []).length];
       click(tree, on("[data-move-open]", btn)); await settle(); const m2 = document.body.appended[1];
       docL.click[0]({ type: "click", target: m2 }); const insideKept = m2.removed; docL.click[0]({ type: "click", target: {} });
       return [tabKept, escaped, insideKept, m2.removed, globalThis.__confirms.length, calls().length, (docL.click || []).length]; })()""",
     '[0,[1,0],0,1,0,0,0]',
     'negative: список закрывается по Escape и по клику мимо — ни вопроса, ни запроса; другая клавиша и клик внутри его не закрывают; слушатели документа сняты'),
    ("stop_asks_then_cancels", '',
     r"""await (async () => { const { tree } = await mount(); globalThis.__fetchReply["/api/model-stores/moves/cancel"] = { ok: true, job: {} }; const btn = { dataset: { moveStop: "mv-1" }, disabled: false };
       const c = click(tree, on("[data-move-stop]", btn)); await c.r; await settle(); return [globalThis.__confirms[0], calls().map((x) => [x.path, x.body])]; })()""",
     json.dumps([[EN["moveStopConfirm"] + "\n\n" + en("moveStopConfirmJob", count=2), "Stop", EN["movesTitle"], "move"],
                 [["/api/model-stores/moves/cancel", {"id": "mv-1"}], ["/api/model-stores/moves", None]]]),
     '«Остановить» на строке: сначала вопрос — и он говорит, что остановится весь перенос, раз в нём ещё два файла; под той же вьючной ламой, что и начало переноса; потом запрос по id и перечитывание'),
    ("stop_of_a_single_file_move_says_just_that", '',
     r"""await (async () => { const j = JOB(); j.files = [j.files[0]]; const { tree } = await mount([j]); globalThis.__confirmAnswer = false;
       const c = click(tree, on("[data-move-stop]", { dataset: { moveStop: "mv-1" } })); await c.r; await settle(); return [globalThis.__confirms[0][0], calls().length]; })()""",
     json.dumps([EN["moveStopConfirm"], 0]),
     'в переносе один файл — вопрос без лишнего абзаца; «нет» — ни запроса'),
    ("a_refused_stop_is_a_toast", '',
     r"""await (async () => { const { tree } = await mount(); globalThis.__fetchReply["/api/model-stores/moves/cancel"] = { ok: false, code: "unknown-job", error: "no such move: mv-1" }; const btn = { dataset: { moveStop: "mv-1" }, disabled: false };
       const c = click(tree, on("[data-move-stop]", btn)); await c.r; await settle(); return [globalThis.__fields.toast.textContent, btn.disabled]; })()""",
     '["no such move: mv-1",false]',
     'negative: сервер отказал — причина тостом и кнопка снова доступна'),
    ("a_missed_poll_keeps_the_picture", '',
     r"""await (async () => { const { p, summary } = await mount(); const before = [p.rowHtml("Qwen/unsloth/Q4/q.gguf"), summary.textContent];
       globalThis.__fetchReply["/api/model-stores/moves"] = { __status: 502, error: "bad gateway" }; await tick();
       return [p.rowHtml("Qwen/unsloth/Q4/q.gguf") === before[0], summary.textContent === before[1], summary.hidden, polls().length, globalThis.__changes]; })()""",
     '[true,true,false,2,0]',
     'negative: опрос не дошёл — картинка прежняя, не пустая, и следующий опрос назначен'),
    ("the_line_opens_the_branches_its_files_are_in", '',
     r"""await (async () => { const { summary } = await mount(); const det = (b) => ({ dataset: { branch: b }, open: false });
       const ds = ["Qwen", "Qwen/unsloth", "Qwen/unsloth/Q4", "gemma", "llama", "Qwen/other"].map(det); const scrolled = [];
       globalThis.__planted = { "details[data-branch]": ds, "[data-move-path]": [{ scrollIntoView: (o) => scrolled.push(o) }] };
       summary.listeners.click[0]({}); const opened = ds.filter((d) => d.open).map((d) => d.dataset.branch);
       ds.forEach((d) => { d.open = false; }); let prevented = 0; summary.listeners.keydown[0]({ key: "Enter", preventDefault: () => { prevented += 1; } });
       summary.listeners.keydown[0]({ key: "a", preventDefault: () => { prevented += 1; } });
       return [opened, ds.filter((d) => d.open).length, scrolled, prevented]; })()""",
     '[["Qwen","Qwen/unsloth","Qwen/unsloth/Q4","gemma"],4,[{"block":"center"},{"block":"center"}],1]',
     'строка у кнопки раскрывает ровно те ветки, где едут файлы, и подводит к первой полосе — мышью и с клавиатуры (Enter), другая клавиша — ничего'),
    ("the_page_is_asked_first_what_to_show", '',
     r"""await (async () => { const order = []; const { summary } = await mount([JOB()], { onReveal: () => order.push("page") });
       const det = { dataset: { branch: "Qwen" }, get open() { return false; }, set open(v) { order.push("open:" + v); } };
       globalThis.__planted = { "details[data-branch]": [det], "[data-move-path]": [{ scrollIntoView: () => order.push("scroll") }] };
       summary.listeners.click[0]({}); const clicked = [...order]; order.length = 0;
       summary.listeners.keydown[0]({ key: "Enter", preventDefault() {} }); const keyed = [...order]; order.length = 0;
       summary.listeners.keydown[0]({ key: "x", preventDefault() {} });
       return [clicked, keyed, order]; })()""",
     '[["page","open:true","scroll"],["page","open:true","scroll"],[]]',
     'строка «в пути» сначала спрашивает страницу, что показать (все места, фильтр «В пути»), и только потом раскрывает ветки и подводит к '
     'первой полосе: в отфильтрованном или чужом месте полос могло не быть в разметке вовсе; negative: другая клавиша страницу не трогает'),
    ("render_speaks_the_new_language", '',
     r"""await (async () => { const { p, summary, button } = await mount(); summary.textContent = "stale"; button.textContent = "stale"; p.render(); return [summary.textContent, button.textContent]; })()""",
     json.dumps([en("movesInFlight", n=2, pct=9), "Move to NAS"], ensure_ascii=False),
     'смена языка перерисовывает строку у кнопки и саму кнопку; дерево страница перерисует сама'),
]


_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def main():
    if len(PINS) < 25:
        print(f"js model-moves FAILED: всего {len(PINS)} пинов — снимок урезан")
        return 1
    node = find_node()
    if node is None:
        print("js model-moves: SKIPPED — node не найден: " + ", ".join(node_search_paths()))
        return 0
    ids = [p[0] for p in PINS]
    dup = {i for i in ids if ids.count(i) > 1}
    if dup:
        print(f"js model-moves FAILED: повторяющиеся id пинов: {sorted(dup)}")
        return 1
    body = [f"try {{ reset(); {setup}\n  out[{json.dumps(pid)}] = {expr}; }} catch (e) {{ out[{json.dumps(pid)}] = {{ __threw: String(e && e.message || e) }}; }}"
            for pid, setup, expr, _exp, _msg in PINS]
    probe = PREAMBLE + "\n".join(body) + "\nconsole.log(JSON.stringify(out)); process.exit(0);\n"
    harness = ROOT / "scripts" / "_js_harness.mjs"
    path = ROOT / "scripts" / ".probe_js_model_moves.tmp.mjs"
    path.write_text(probe)
    try:
        env = {**os.environ, "JS_ROOT": str(ROOT / "static" / "js"), "JS_STUBS": STUBS,
               "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8", "TZ": "UTC"}
        run = subprocess.run(
            [node, "--import", f"data:text/javascript,import {{ register }} from 'node:module'; register('{harness.as_uri()}');",
             str(path)], capture_output=True, text=True, env=env, cwd=ROOT, timeout=120)
    finally:
        path.unlink(missing_ok=True)
    if run.returncode != 0:
        print(run.stdout); print(run.stderr)
        print(f"js model-moves FAILED: node вышел с кодом {run.returncode}")
        return 1
    got = json.loads(run.stdout.strip().splitlines()[-1])
    print("переносы в дереве /models:")
    for pid, _setup, _expr, expected, msg in PINS:
        want, have = json.loads(expected), got.get(pid, {"__missing": True})
        check(have == want, msg if have == want else
              f"{msg}\n        ожидалось {json.dumps(want, ensure_ascii=False)[:400]}\n        получено  {json.dumps(have, ensure_ascii=False)[:400]}")
    print()
    if _fail:
        print(f"FAILED ({len(_fail)}):")
        for f in _fail:
            print("  - " + f.splitlines()[0])
        return 1
    print(f"js model-moves OK: настоящий модуль в node, {len(PINS)} пинов переносов в дереве значениями")
    return 0


if __name__ == "__main__":
    sys.exit(main())
