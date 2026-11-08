#!/usr/bin/env python3
"""Value snapshot: a text chat with a cell from its window's Talk tab (static/js/cell-chat.js, 1.3.624).

A chat cell (its runner answers text-chat, its job is a chat) is asked in text from its window: the page asks the controller
(POST /api/cell-talk {cellId}, mode text-chat) and the controller the cell. The talk is kept by cell id, outside the window, so
a repaint of the lane keeps it — the typed draft too.

Pinned by value with a fake call and a fake page: who is offered a chat, what goes with a question (the last messages that were
said — a question whose answer failed goes with it), the words under an answer (only what was said), the section running,
busy and stopped, and that it names no port, a question sent (its body by the cell's id and with no machine or port, the
answer kept, a refusal's own words, a throw, an empty message, a second question while one is awaited), clearing, the section
drawn again at its newest message with the typing given back, and the keys: Enter sends, Shift+Enter and a word still composed
do not. The words come from static/js/i18n/en.js.

Run: python3 scripts/test_js_cell_chat.py
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from _node import find_node, node_search_paths, probe_args  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def esc(text):
    """A word as the page writes it: escapeHtml of static/js/utils.js."""
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("'", "&#39;"))


PROBE = r"""
import "./_js_globals.mjs";
import { pathToFileURL } from "node:url";
const root = process.env.JS_ROOT;
const { CellChat } = await import(pathToFileURL(root + "/cell-chat.js").href);
const en = (await import(pathToFileURL(root + "/i18n/en.js").href)).default;
const out = { en: Object.fromEntries(Object.entries(en).filter(([k]) => k.startsWith("cwChat"))) };
const asked = [];
const answers = [];
const call = async (url, opts) => { asked.push([url, JSON.parse(opts.body)]); const a = answers.shift(); if (a instanceof Error) throw a; return a; };
const fmt = (n) => n.toFixed(1);

out.offered = [
  CellChat.offered({ modes: ["heard-chat", "text-chat"] }, ["llm"]),
  CellChat.offered({ modes: ["heard-chat", "text-chat"] }, ["embed"]),
  CellChat.offered({ modes: ["transcription"] }, ["asr"]),
  CellChat.offered(null, ["llm"]),
  CellChat.offered({ modes: ["text-chat"] }, []),
];

// What goes with a question.
let chat = new CellChat({ call });
chat.cells.set("c3f9a02b1", { turns: [
  { role: "user", text: "q1" }, { role: "assistant", text: "a1" },
  { role: "user", text: "q2" }, { role: "assistant", error: "HTTP 500" },
  { role: "user", text: "q3" }, { role: "assistant", text: "a3" },
  { role: "user", text: "q4" }, { role: "assistant", text: "a4" } ] });
out.history = [chat.history("c3f9a02b1", 8), chat.history("c3f9a02b1", 3), chat.history("c3f9a02b1", 1), chat.history("c0d1e2f3a", 8),
               chat.history("c3f9a02b1", 4), chat.history("c3f9a02b1", 2)];

// The words under an answer.
out.meta = [
  CellChat.meta({ tokens: { written: 67 }, speed: { written: 6.12, read: 30.6 }, ms: { total: 11234 } }, fmt),
  CellChat.meta({ tokens: { read: 12 }, ms: { total: 800 } }, fmt),
  CellChat.meta({ ms: null }, fmt),
];

// The section.
chat = new CellChat({ call });
// A builder of before may still hand a port and a page: the section draws neither. A cell listens on its machine's loopback since
// 2026-11-08, and no browser reaches its own page.
out.empty = chat.html("c3f9a02b1", { running: true, port: 22020, carried: 8, page: "http://10.0.0.5:22020/", format: fmt });
out.emptyLead = (out.empty.match(/<p class="cw-lead">([^<]*)<\/p>/) || [])[1] ?? null;
chat.cells.set("c3f9a02b1", { turns: [{ role: "user", text: "Hi <b>" }, { role: "assistant", text: "Hello & bye", tokens: { written: 3 }, ms: { total: 1500 } },
                                       { role: "user", text: "and?" }, { role: "assistant", error: "cell c3f9a02b1 is not running: start it first" },
                                       { role: "user", text: "again" }, { role: "assistant", text: "" }], draft: "half <typed>" });
out.full = chat.html("c3f9a02b1", { running: true, carried: 8, format: fmt });
out.stopped = chat.html("c3f9a02b1", { running: false, carried: 8, format: fmt });
chat.cells.set("c22021", { turns: [{ role: "user", text: "q" }], busy: true, draft: "" });
out.busy = chat.html("c22021", { running: true, carried: 1, format: fmt });
out.stoppedEmpty = new CellChat({ call }).html("c5e01d7aa", { running: false });

// A question sent.
const page = () => {
  const turns = { scrollTop: 0, scrollHeight: 640 };
  const draft = { focused: 0, focus() { this.focused += 1; } };
  const view = { dataset: { tState: "idle", cellChatCarried: "8" }, outerHTML: "", querySelector: (s) => (s === ".cw-chat-page" ? { getAttribute: () => "http://10.0.0.5:22020/" } : null) };
  const doc = { querySelector: (s) => (s.endsWith(" .cw-chat-turns") ? turns : s.endsWith(" .cw-chat-draft") ? draft : s.startsWith("[data-cell-chat-view=") ? view : null) };
  return { doc, view, turns, draft };
};
chat = new CellChat({ call });
let p = page();
chat.draft("c3f9a02b1", "  What is 2+2?  ");
answers.push({ mode: "text-chat", status: 200, text: "4", ms: { first: 900, total: 1200 }, tokens: { read: 20, written: 1 }, speed: { read: 33.3, written: 9.1 } });
out.sent = await chat.send("c3f9a02b1", { carried: 8, doc: p.doc, format: fmt });
out.sentBody = asked.splice(0);
out.sentPaint = [p.view.outerHTML.includes('data-cell-chat-view="c3f9a02b1"'), p.view.outerHTML.includes("http://10.0.0.5:22020/"), p.turns.scrollTop, p.draft.focused];
chat.draft("c3f9a02b1", "and 3+3?");
answers.push({ mode: "text-chat", status: 503, error: "Loading model", ms: { first: 5, total: 6 } });
await chat.send("c3f9a02b1", { carried: 8, doc: page().doc });
out.secondBody = asked.splice(0);
out.refused = chat.of("c3f9a02b1").turns.slice(-1)[0];
chat.draft("c3f9a02b1", "once more");
answers.push(new Error("cell c3f9a02b1 is not running: start it first"));
await chat.send("c3f9a02b1", { carried: 8, doc: page().doc });
asked.splice(0);
out.thrown = chat.of("c3f9a02b1").turns.slice(-1)[0];
out.emptySend = (await chat.send("c3f9a02b1", { doc: page().doc })).turns.length;
out.emptyAsked = asked.length;
let release;
const slow = new CellChat({ call: (url, opts) => { asked.push([url, JSON.parse(opts.body)]); return new Promise((r) => { release = r; }); } });
slow.draft("c3f9a02b1", "first");
const first = slow.send("c3f9a02b1", { doc: page().doc });
out.during = [slow.of("c3f9a02b1").busy, slow.of("c3f9a02b1").turns.length, slow.of("c3f9a02b1").draft];
slow.draft("c3f9a02b1", "second");
out.second = (await slow.send("c3f9a02b1", { doc: page().doc })).turns.length;
out.clearBusy = slow.clear("c3f9a02b1", page().doc).turns.length;
out.slowAsked = asked.splice(0).length;
release({ text: "done" });
await first;
out.afterSlow = [slow.of("c3f9a02b1").busy, slow.of("c3f9a02b1").turns.map((t) => t.text), slow.of("c3f9a02b1").draft];
out.cleared = chat.clear("c3f9a02b1", page().doc).turns.length;

// The keys and what is typed.
chat = new CellChat({ call });
const box = { dataset: { cellChatDraft: "c3f9a02b1" }, value: "typed", closest: (s) => (s === "[data-cell-chat-draft]" ? box : s === "[data-cell-chat-view]" ? { dataset: { cellChatCarried: "4" } } : null) };
let prevented = 0;
const key = (k, extra = {}) => ({ key: k, target: box, preventDefault: () => { prevented += 1; }, ...extra });
out.shift = chat.onKey(key("Enter", { shiftKey: true }), page().doc);
out.composing = chat.onKey(key("Enter", { isComposing: true }), page().doc);
out.otherKey = chat.onKey(key("a"), page().doc);
answers.push({ text: "ok" });
await chat.onKey(key("Enter"), page().doc);
out.enter = [prevented, asked.splice(0)];
const typing = { dataset: { cellChatDraft: "c3f9a02b1" }, value: "kept while the lane repaints", closest: (s) => (s === "[data-cell-chat-draft]" ? typing : null) };
chat.onInput({ target: typing });
out.typed = chat.of("c3f9a02b1").draft;
out.inputElse = chat.onInput({ target: { closest: () => null } });
const send = { dataset: { cellChatSend: "c3f9a02b1" }, closest: (s) => (s === "[data-cell-chat-send]" ? send : s === "[data-cell-chat-view]" ? { dataset: { cellChatCarried: "2" } } : null) };
answers.push({ text: "ok2" });
await chat.onClick({ target: send }, page().doc);
out.clickSend = asked.splice(0);
const clearBtn = { dataset: { cellChatClear: "c3f9a02b1" }, closest: (s) => (s === "[data-cell-chat-clear]" ? clearBtn : null) };
out.clickClear = chat.onClick({ target: clearBtn }, page().doc).turns.length;
out.clickElse = chat.onClick({ target: { closest: () => null } }, page().doc);
// A talk is held with the model it was had with: the cell given another model starts with no talk. A cell made anew has an id of
// its own — the talk of the deleted cell it may replace is not its own, whatever port either ran on.
const held = new CellChat({ call });
held.cells.set("c22030", { turns: [{ role: "user", text: "17*23?" }, { role: "assistant", text: "391" }], draft: "", busy: false });
held.html("c22030", { running: true, model: "gemma/gemma-4-12B.gguf" });
const keptSame = held.of("c22030").turns.length;
held.html("c22030", { running: true });
const keptUnsaid = held.of("c22030").turns.length;
held.html("c22030", { running: true, model: "hermes/Hermes-4-70B.gguf" });
const afterOther = [held.of("c22030").turns.length, held.of("c22030").model];
held.cells.set("c9a8b7c6d", { turns: [{ role: "user", text: "q" }], draft: "", busy: true, model: "a.gguf" });
held.html("c9a8b7c6d", { running: true, model: "b.gguf" });
const fresh = held.html("c4b5c6d7e", { running: true, model: "gemma/gemma-4-12B.gguf" });
out.heldWith = { keptSame, keptUnsaid, afterOther, busyKept: held.of("c9a8b7c6d").turns.length,
                 newCell: [held.of("c4b5c6d7e").turns.length, fresh.includes("cw-chat-turns"), held.of("c22030").model],
                 section: !held.html("c22030", { running: true, model: "hermes/Hermes-4-70B.gguf" }).includes("cw-chat-turns") };
console.log(JSON.stringify(out));
"""


def main():
    node = find_node()
    if node is None:
        print("js cell-chat: SKIPPED — node не найден ни в PATH, ни у менеджеров версий: " + ", ".join(node_search_paths()))
        return 0
    probe = ROOT / "scripts" / ".probe_cell_chat.tmp.mjs"
    probe.write_text(PROBE, encoding="utf-8")
    try:
        env = {"JS_ROOT": str(ROOT / "static" / "js"), "PATH": "/usr/bin:/bin",
               "JS_STUBS": "command-preview,favorites,llama-edit,form,remote-cells,cloud,topology-render,polling"}
        proc = subprocess.run(probe_args(node, ROOT / "scripts" / "_js_harness.mjs", probe), capture_output=True,
                              text=True, cwd=ROOT, env=env, timeout=60)
    finally:
        probe.unlink(missing_ok=True)
    if proc.returncode != 0:
        print("js cell-chat: FAILED — харнесс не отработал")
        print(proc.stderr.strip()[:1500])
        return 1
    got = json.loads(proc.stdout.strip().splitlines()[-1])
    en = got["en"]

    print("кому чат:")
    check(got["offered"] == [True, False, False, False, False],
          "чат — у раннера, что отвечает текстом, и у ячейки-чата; negative: сервер эмбеддингов того же раннера, распознаватель, "
          "раннер без разговора и ячейка, чья работа не названа, — без чата")

    print("что уходит с вопросом:")
    h8, h3, h1, none, h4, h2 = got["history"]
    check(h8 == [{"role": "user", "text": "q1"}, {"role": "assistant", "text": "a1"}, {"role": "user", "text": "q3"},
                 {"role": "assistant", "text": "a3"}, {"role": "user", "text": "q4"}, {"role": "assistant", "text": "a4"}],
          "сказанное парами — вопрос и ответ; negative: вопрос с проваленным ответом не уходит (два вопроса подряд иные модели не берут)")
    check(h3 == [{"role": "user", "text": "q4"}, {"role": "assistant", "text": "a4"}] and h1 == [] and none == [],
          "раннер несёт три сообщения — уходят два последних, новое третье; одно — только новое; у ячейки без разговора — ничего")
    check(h4 == [{"role": "user", "text": "q4"}, {"role": "assistant", "text": "a4"}] and h2 == [],
          "defect-history (1.3.624, до выкладки): мест нечётно — уходят только целые пары; negative: ответ без своего вопроса не уходит")

    print("слова под ответом:")
    m_full, m_part, m_none = got["meta"]
    check(m_full == " · ".join([en["cwChatTokens"].replace("{n}", "67"), en["cwChatWriting"].replace("{tps}", "6.1"),
                                en["cwChatReading"].replace("{tps}", "30.6"), en["cwChatSeconds"].replace("{s}", "11.2")]),
          "токены, скорость генерации и чтения — как их пишет доска, — и сколько шло")
    check(m_part == en["cwChatSeconds"].replace("{s}", "0.8") and m_none == "",
          "negative: не сказанное не пишется — ни «0 токенов», ни пустые части")

    print("секция:")
    e = got["empty"]
    check('data-cell-chat-view="c3f9a02b1" data-cell-chat-carried="8" data-t="cell-chat" data-t-id="c3f9a02b1" data-t-state="idle"' in e
          and got["emptyLead"] == esc(en["cwChatLead"]) and "cw-chat-turns" not in e and "cell-chat-clear" not in e,
          "пустой разговор — строка «прямо в ячейку», поле и «Send»; negative: ни пустой ленты, ни «Clear»")
    check("{" not in en["cwChatLead"] and "22020" not in got["emptyLead"] and ":" not in got["emptyLead"],
          "negative: строка о чате не называет порт — даже если доска по-старому его дала: порт у ячейки только пока она работает")
    check('<textarea class="cw-chat-draft" rows="3" data-cell-chat-draft="c3f9a02b1" data-t="cell-chat-draft" data-t-id="c3f9a02b1"' in e
          and f'aria-label="{esc(en["cwChatDraftLabel"])}"' in e and esc(en["cwChatMemory"].replace("{n}", "8")) in e
          and f'data-cell-chat-send="c3f9a02b1" data-t="cell-chat-send" data-t-id="c3f9a02b1">{en["cwChatSend"]}</button>' in e,
          "поле с подписью, сколько сообщений видит модель, и «Send»")
    check("cw-chat-page" not in e and "10.0.0.5" not in e and "cwChatPage" not in en,
          "negative: своей страницы llama.cpp нет — ячейка слушает петлю своей машины, браузер до неё не дойдёт, даже если доска "
          "по-старому дала адрес; и слова для ссылки ушли")
    f = got["full"]
    check('<div class="cw-turn me" data-t="cell-chat-turn" data-t-id="c3f9a02b1" data-t-state="user">Hi &lt;b&gt;</div>' in f
          and '<div class="cw-turn-text">Hello &amp; bye</div><div class="cw-turn-meta">'
              + esc(en["cwChatTokens"].replace("{n}", "3") + " · " + en["cwChatSeconds"].replace("{s}", "1.5")) + "</div>" in f,
          "вопрос справа, ответ слева со словами под ним — всё экранировано")
    check('data-t-state="error" role="alert"><div class="cw-turn-text">cell c3f9a02b1 is not running: start it first</div>' in f
          and f'<div class="cw-turn-text"><em>{esc(en["cwChatNoWords"])}</em></div>' in f,
          "отказ — его словами и красным; ответ без слов — так и сказано, а не пустой пузырь")
    check(">half &lt;typed&gt;</textarea>" in f and 'data-cell-chat-clear="c3f9a02b1" data-t="cell-chat-clear"' in f and "page" not in f.split("cw-chat-foot")[1].split("cw-chat-gap")[0],
          "набранное, но не отправленное, — в поле после перерисовки; есть «Clear»; negative: страницы нет — нет и ссылки")
    st = got["stopped"]
    check('data-t-state="off"' in st and esc(en["cwChatOff"]) in st and "textarea" not in st and "cell-chat-send" not in st
          and "Hello &amp; bye" in st and "cell-chat-clear" in st,
          "ячейка стоит — разговор виден, поле и «Send» убраны, сказано, что запустить её надо кнопкой на полосе; «Clear» есть")
    b = got["busy"]
    check('data-t-state="busy"' in b and esc(en["cwChatWaiting"]) in b and b.count(" disabled") == 3 and "cell-chat-clear" in b
          and esc(en["cwChatMemory"].replace("{n}", "1")) in b,
          "ответ ждут — «модель отвечает…», поле и «Send» закрыты; «Clear» тоже закрыт")
    check("cw-chat-turns" not in got["stoppedEmpty"] and "cell-chat-clear" not in got["stoppedEmpty"],
          "negative: стоит и разговора не было — ни ленты, ни «Clear»")

    print("вопрос:")
    check(got["sentBody"] == [["/api/cell-talk", {"cellId": "c3f9a02b1", "mode": "text-chat", "text": "What is 2+2?", "history": []}]],
          "вопрос уходит контроллеру: имя ячейки (cellId), режим text-chat, текст без пробелов по краям, история")
    check(all("hostId" not in body and "port" not in body for _, body in got["sentBody"] + got["secondBody"] + got["enter"][1] + got["clickSend"]),
          "negative: ни в одном вопросе нет ни машины, ни порта — контроллер знает порт, который взял запуск ячейки")
    s = got["sent"]
    check(s["busy"] is False and s["draft"] == "" and s["turns"] == [{"role": "user", "text": "What is 2+2?"},
          {"role": "assistant", "text": "4", "ms": {"first": 900, "total": 1200}, "tokens": {"read": 20, "written": 1}, "speed": {"read": 33.3, "written": 9.1}}],
          "ответ держится с его числами; поле очищено")
    check(got["sentPaint"] == [True, False, 640, 1],
          "перерисован на месте, лента у новейшего, курсор снова в поле; negative: ссылка на свою страницу, если была в старой "
          "разметке, не переносится — страницы у ячейки на петле нет")
    check(got["secondBody"][0][1]["history"] == [{"role": "user", "text": "What is 2+2?"}, {"role": "assistant", "text": "4"}],
          "следующий вопрос несёт предыдущий разговор")
    check(got["refused"] == {"role": "assistant", "error": "Loading model", "ms": {"first": 5, "total": 6}},
          "отказ ячейки — её собственные слова и время")
    check(got["thrown"] == {"role": "assistant", "error": "cell c3f9a02b1 is not running: start it first"},
          "отказ контроллера (исключение) — его текст")
    check(got["emptySend"] == 6 and got["emptyAsked"] == 0, "negative: пустое сообщение не уходит")
    check(got["during"] == [True, 1, ""] and got["second"] == 1 and got["clearBusy"] == 1 and got["slowAsked"] == 1
          and got["afterSlow"] == [False, ["first", "done"], "second"],
          "negative: пока ждут ответ, второй вопрос не уходит, а очистка не стирает разговор; набранное остаётся в поле")
    check(got["cleared"] == 0, "«Clear» — разговор забыт")

    print("клавиши и набранное:")
    check(got["shift"] is None and got["composing"] is None and got["otherKey"] is None,
          "negative: Shift+Enter — новая строка, слово, которое ещё собирает метод ввода, — не отправка; другая клавиша — ничего")
    check(got["enter"] == [1, [["/api/cell-talk", {"cellId": "c3f9a02b1", "mode": "text-chat", "text": "typed", "history": []}]]],
          "Enter — отправляет то, что в поле, и не вставляет перевод строки")
    check(got["typed"] == "kept while the lane repaints" and got["inputElse"] is None, "набранное запоминается на каждый ввод — перерисовка его вернёт")
    check(got["clickSend"][0][1]["text"] == "kept while the lane repaints" and got["clickSend"][0][1]["history"] == []
          and got["clickClear"] == 0 and got["clickElse"] is None,
          "«Send» — отправляет набранное; ячейка несёт два сообщения — целая пара в одно место не влезает, история пуста; "
          "«Clear» очищает; клик мимо — ничего")
    h = got["heldWith"]
    check(h["afterOther"] == [0, "hermes/Hermes-4-70B.gguf"] and h["section"],
          "defect-history (2026-10-26): ячейке дали другую модель — разговор начинается заново: окно Hermes показывало вопросы "
          "и ответы gemma с её скоростями как свои")
    check(h["newCell"] == [0, False, "hermes/Hermes-4-70B.gguf"],
          "новая ячейка — со своим именем (cellId) и своим, пустым разговором; negative: разговор прежней ячейки к ней не переходит")
    check(h["keptSame"] == 2 and h["keptUnsaid"] == 2 and h["busyKept"] == 1,
          "negative: та же модель, модель не сказана, ответ ещё ждут — разговор остаётся")

    print()
    if _fail:
        print(f"js cell-chat FAILED ({len(_fail)}):")
        for m in _fail:
            print("  - " + m.splitlines()[0])
        return 1
    print("js cell-chat OK: кому чат, история, слова под ответом, секция, вопрос, клавиши — значениями")
    return 0


if __name__ == "__main__":
    sys.exit(main())
