#!/usr/bin/env python3
"""Snapshot of static/js/model-stores.js — the places panel on the /models page.

The module is a class (StoresPanel) with one face, mountStores. It draws two
things: the list of places in the side column and the summary over the model
list. Pinned by value.

The list: "All models" first, with every place's bytes together once this disk
is counted; each place with its state (a dot when healthy, a word otherwise),
what it holds (this disk's count comes from the page, never measured again
here), a bar of how full it is and its free space; a place that is not mounted
draws NO numbers even when some arrive, and says why in its chip's title; every
state has its word and tone, and an unknown state falls to "not answering",
never to "available"; a failed load says so instead of drawing nothing; before
the first answer the panel shows "…", not an empty list.

Choosing: a click on a place (or on a card's "Open") makes it the scope, tells
the page once, and moves the highlight and the summary; a place that is gone
hands the list back to every place.

The summary: under "All models" one bar with a segment per place that holds
something (none when nothing anywhere), a legend with each place's bytes and
files, and a card per place with its room and the way into it; one place's
summary carries its state, path, what may be done with the path (✎ for this
disk, "remove" for a library), what it holds with its model families (an empty
library says so), its folders (a list cut at the server's limit names what did
not fit) and its room.

Adding: "Add library" opens a box, Escape and Cancel close it; the path goes
out trimmed, an empty one sends nothing, a bare directory is refused once and
re-sent with force only after the operator confirms, any other refusal is a
toast and the typed path stays; Enter adds; what is typed survives a redraw.
Removing: asked first, then posted; a declined question sends nothing; a server
refusal is a toast and the button comes back. The pencil edits the models
directory in place and hands the trimmed path to the page. Every answer is told
to the page (the move button needs the libraries), a failed one with the last
list known; the same count handed over twice draws nothing again.

The DOM: the panel's root and summary are model elements whose querySelector
hands out the path fields and the buttons; toast() is the real one from
utils.js.

Run: python3 scripts/test_js_model_stores.py
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


def _english():
    """Every one-string line of en.js — expectations quote the page's own words
    instead of a copy of them that can drift."""
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


# The same neighbours the models page stubs: the real i18n.js and utils.js pull
# the rest of the app in behind them, and canvas.js alone needs a browser
# (MutationObserver at import time).
STUBS = ("dialogs,dialog-llamas,polling,canvas,topology-dnd,topology-render,charts,cables,cloud,history,favorites,"
         "config-locator,system-panels,onboarding,onboarding-tours,usage-stats,system-page,memory,command-preview,"
         "llama-edit,remote-cells,topology-nodes,topology-modals,routers,topology-activity,topology-proxies,model-meta,form")

PREAMBLE = r"""
import "./_js_globals.mjs";
import { pathToFileURL } from "node:url";
const m = await import(pathToFileURL(process.env.JS_ROOT + "/model-stores.js").href);
const cls = () => { const s = new Set(); return { add: (...c) => c.forEach((x) => s.add(x)), remove: (...c) => c.forEach((x) => s.delete(x)), has: (c) => s.has(c) } };
// innerHTML counts its writes: a redraw that changes nothing must not replace
// the markup under a pressed mouse button.
const mkEl = () => ({ textContent: "", _html: "", writes: 0, get innerHTML() { return this._html; }, set innerHTML(v) { this._html = v; this.writes += 1; },
  value: "", disabled: false, dataset: {}, classList: cls(), listeners: {}, addEventListener(t, fn) { (this.listeners[t] ||= []).push(fn); } });
const HANDS = { "[data-store-path]": "__input", "[data-store-add]": "__addBtn", "[data-store-dir]": "__dir", "[data-dir-save]": "__saveBtn",
  "[data-store-repath-box]": "__repathBox", "[data-repath-save]": "__repathBtn" };
const mkRoot = () => { const r = mkEl(); r.querySelector = (sel) => (HANDS[sel] ? globalThis[HANDS[sel]] || null : null); return r; };
const GB = 2 ** 30;
const STORES = () => [
  // The local store carries a file count ON PURPOSE: what this disk holds is
  // counted by the tree on the page and handed over with holds(), not measured
  // a second time here, and a pin that passes only because the number is
  // absent would not notice the rule breaking.
  { id: "local", name: "", path: "/home/x/llama.cpp/models", role: "local", builtin: true, state: "ok", detail: "", checkedAt: 1, free: 67 * GB, total: 915 * GB, files: 75, size: 490 * GB },
  { id: "lib-a", name: "lama-caravan-models", path: "/mnt/lama-caravan-models", role: "library", builtin: false, state: "ok", detail: "", checkedAt: 1,
    free: 5400 * GB, total: 7000 * GB, files: 3, size: 60 * GB, folders: [{ name: "Qwen3.8-27B-GGUF", bytes: 40 * GB, files: 2 }, { name: "gemma", bytes: 20 * GB, files: 1 }], more: 0 },
];
const HELD = () => ({ files: 58, size: 481 * GB, families: { all: 24, local: 20, "lib-a": 2 } });
const calls = () => globalThis.__fetchCalls.map((c) => ({ path: c.path, method: c.method, body: c.body === null ? null : JSON.parse(c.body) }));
const settle = async () => { for (let i = 0; i < 8; i++) await new Promise((r) => setImmediate(r)); };
const box = () => ({ value: "", focused: 0, selected: 0, disabled: false, classList: cls(), focus() { this.focused += 1; }, select() { this.selected += 1; } });
const reset = () => { globalThis.__fetchCalls.length = 0; globalThis.__fetchReply = {}; globalThis.__fields = { toast: mkEl() };
  globalThis.__input = box(); globalThis.__addBtn = { disabled: false }; globalThis.__dir = null; globalThis.__saveBtn = null;
  globalThis.__repathBox = box(); globalThis.__repathBtn = { disabled: false, classList: cls(), dataset: { repathSave: "lib-a" } };
  globalThis.__confirms = []; globalThis.__titles = []; globalThis.__confirmAnswer = true; globalThis.__scopes = [];
  globalThis.__stubReturns = { "dialogs.appConfirm": async (msg, opts) => { globalThis.__confirms.push(msg); globalThis.__titles.push(opts && opts.title); return globalThis.__confirmAnswer !== false; } }; };
const mount = async (stores = STORES(), opts = {}) => { globalThis.__fetchReply["/api/model-stores"] = { ok: true, stores }; const root = mkRoot(); const summary = mkRoot();
  const p = m.StoresPanel.mount(root, { summary, onScope: (s) => globalThis.__scopes.push(s), ...opts }); await settle(); globalThis.__fetchCalls.length = 0;
  return { p, root, summary, html: () => root.innerHTML, sum: () => summary.innerHTML }; };
const target = (sel, el) => ({ closest: (s) => (s === sel ? el : null) });
const click = (el, sel, hit) => el.listeners.click[0]({ target: target(sel, hit) });
const clickAdd = (root) => click(root, "[data-store-add]", globalThis.__addBtn);
const clickRemove = (root, rm) => click(root, "[data-store-remove]", rm);
const clickPlace = (el, scope) => click(el, "[data-scope]", { dataset: { scope } });
// One place's entry in the list: from its id to the end of its button.
const entryOf = (h, id) => { const at = h.indexOf(id === "all" ? 'data-t="models-place-all"' : `data-t-id="${id}"`); return at < 0 ? "" : h.slice(at, h.indexOf("</button>", at)); };
const cardOf = (h, id) => { const at = h.indexOf(`data-t="models-place-card" data-t-id="${id}"`); return at < 0 ? "" : h.slice(at, h.indexOf('<div class="mdl-card"', at + 1) < 0 ? undefined : h.indexOf('<div class="mdl-card"', at + 1)); };
reset();
const out = {};
"""

PINS = [
    ("why_it_does_not_answer_and_what_to_run", '',
     r"""(() => { const H = (f, path) => { const h = new m.MountHint(f, path); return [h.text(), h.command()]; };
       return [H({ inFstab: true, source: "", type: "", host: "", answers: null }, "/mnt/x"),
               H({ inFstab: false, source: "", type: "", host: "", answers: null }, "/mnt/x"),
               H({ inFstab: true, source: "nas.lan:/v/lib", type: "nfs4", host: "nas.lan", answers: false }, "/mnt/x"),
               H({ inFstab: true, source: "nas.lan:/v/lib", type: "nfs4", host: "nas.lan", answers: true }, "/mnt/x"),
               H({ inFstab: true, source: "/dev/sdb1", type: "ext4", host: "", answers: null }, "/mnt/x"),
               H(null, "/mnt/x")]; })()""",
     json.dumps([[en("storeWhyNotMounted"), "sudo mount /mnt/x"],
                 [en("storeWhyNoFstab"), ""],
                 [en("storeWhyFrom", source="nas.lan:/v/lib") + " · " + en("storeWhySilent", host="nas.lan"),
                  "sudo umount -l /mnt/x && sudo mount /mnt/x"],
                 [en("storeWhyFrom", source="nas.lan:/v/lib") + " · " + en("storeWhyAnswers", host="nas.lan"), ""],
                 [en("storeWhyFrom", source="/dev/sdb1"), ""],
                 ["", ""]], ensure_ascii=False),
     "почему не отвечает: ничего не смонтировано — команда смонтировать; записи в fstab нет — команды нет, монтировать нечего; "
     "машина молчит — перемонтировать; машина отвечает и устройство без машины — только факт, без команды (она увела бы не туда); "
     "фактов нет — ни строки, ни команды"),

    ("why_line_only_where_something_is_wrong", '',
     r"""await (async () => { const s = STORES();
       s[1] = { ...s[1], state: "unknown", detail: "no answer in 8 s", mount: { inFstab: true, source: "nas.lan:/v/lib", type: "nfs4", host: "nas.lan", answers: false } };
       const { p, sum } = await mount(s); p.choose("lib-a"); const bad = sum();
       p.choose("local"); const good = sum();
       return [bad.includes('data-t="models-store-why" data-t-id="lib-a"'), bad.includes("nas.lan"),
               bad.includes('data-t="models-store-why-command"'), bad.includes("sudo umount -l /mnt/lama-caravan-models"),
               good.includes('data-t="models-store-why"')]; })()""",
     '[true,true,true,true,false]',
     "строка «почему» рисуется там, где сервер прислал факты о монтировании (а он шлёт их только неотвечающему месту), с готовой командой; у здорового места фактов нет — и строки нет"),

    ("repath_edits_in_place_and_posts_it", '',
     r"""await (async () => { const { p, summary, sum } = await mount(); p.choose("lib-a");
       const before = sum().includes('data-t="models-store-repath"');
       click(summary, "[data-store-repath]", { dataset: { storeRepath: "lib-a" } }); await settle();
       const editing = sum(); globalThis.__repathBox.value = "  /mnt/new-place  ";
       globalThis.__fetchReply["/api/model-stores/repath"] = { ok: true, store: { id: "lib-a", name: "lama-caravan-models", path: "/mnt/new-place" } };
       click(summary, "[data-repath-save]", globalThis.__repathBtn); await settle();
       return [before, editing.includes('data-t="models-store-repath-input"'), editing.includes('value="/mnt/lama-caravan-models"'),
               globalThis.__repathBox.focused, calls().filter((c) => c.path.includes("repath")), p.repathing]; })()""",
     '[true,true,true,1,[{"path":"/api/model-stores/repath","method":"POST","body":{"id":"lib-a","path":"/mnt/new-place"}}],""]',
     "✎ у библиотеки открывает поле с её нынешним путём и ставит в него курсор; сохранение шлёт id и путь без пробелов и закрывает поле"),

    ("repath_refusal_stays_open_and_says_why", '',
     r"""await (async () => { const { p, summary } = await mount(); p.choose("lib-a");
       click(summary, "[data-store-repath]", { dataset: { storeRepath: "lib-a" } }); await settle();
       globalThis.__repathBox.value = "/mnt/other";
       globalThis.__fetchReply["/api/model-stores/repath"] = { ok: false, error: "/mnt/other holds another library: Other", code: "other-library" };
       click(summary, "[data-repath-save]", globalThis.__repathBtn); await settle();
       return [globalThis.__fields.toast.textContent, p.repathing, globalThis.__repathBtn.disabled]; })()""",
     '["/mnt/other holds another library: Other","lib-a",false]',
     "negative: отказ сервера показан как есть, поле остаётся открытым, кнопка снова доступна — вторая, молчаливая попытка «добавить» не делается"),

    ("a_place_in_the_list_says_what_it_holds_and_its_room", '',
     r"""await (async () => { const { p, html } = await mount(); p.holds(HELD()); const h = html();
       const loc = entryOf(h, "local"), lib = entryOf(h, "lib-a");
       return [(h.match(/data-t="models-store"/g) || []).length, loc.includes("This controller&#39;s disk"),
               loc.includes("data-store-remove"), loc.includes("data-dir-edit"), loc.includes('data-t="models-store-meta">481 GB<'),
               loc.includes('<i style="width:93%">'), loc.includes(">67.0 GB free of 915 GB<"),
               loc.includes('mdl-store-state good" data-t="models-store-state">available<'),
               lib.includes('data-t="models-store-meta">60.0 GB<'), lib.includes(">5.3 TB free of 6.8 TB<"), h.includes("490 GB")]; })()""",
     '[2,true,false,false,true,true,true,true,true,true,false]',
     'место в списке: имя и состояние, что держит, полоса занятости и свободное место; счёт своего диска — со страницы '
     '(481, а не 490 из ответа сервера: второй замер завёл бы второе число); ни ✎, ни «убрать» в списке нет — они в сводке места'),
    ("not_mounted_draws_no_numbers", '',
     r"""await (async () => { const s = STORES(); s[1] = { ...s[1], state: "not-mounted", detail: "the folder carries no library mark", files: 0 };
       const { p, html, sum } = await mount(s); p.holds(HELD()); const row = entryOf(html(), "lib-a"); const card = cardOf(sum(), "lib-a");
       const all = entryOf(html(), "all"); p.choose("lib-a"); const own = sum();
       return [row.includes('mdl-store-state bad" data-t="models-store-state" title="the folder carries no library mark">not mounted<'),
               row.includes("free of"), row.includes('data-t="models-store-meta"></span>'), row.includes("mdl-store-bar"),
               card.includes(">not mounted<"), card.includes("mdl-free"), all.includes(">481 GB<"),
               own.includes("models-summary-facts"), own.includes("models-store-files"), own.includes("mdl-sum-space"), own.includes('data-store-remove="lib-a"')]; })()""",
     '[true,false,true,false,true,false,true,false,false,false,true]',
     'negative: не смонтировано — красное слово и причина в подсказке, и НИ ОДНОЙ цифры ни в списке, ни на карточке, ни в сводке, даже если '
     'они пришли: это были бы цифры локального диска под пустой точкой монтирования; в «Все модели» такая библиотека не входит; убрать её можно'),
    ("every_state_has_its_word", '',
     r"""await (async () => { const states = ["ok", "low-space", "read-only", "foreign", "not-mounted", "missing", "unknown", "weird"];
       const s = states.map((st, i) => ({ id: "lib-" + i, name: "n" + i, path: "/p" + i, role: "library", builtin: false, state: st, detail: "" })); const { html } = await mount(s); const h = html();
       return states.map((st, i) => { const x = entryOf(h, "lib-" + i).match(/mdl-store-state (\w+)" data-t="models-store-state">([^<]*)</); return x ? x[1] + ":" + x[2] : null; }); })()""",
     '["good:available","warn:low on space","warn:read-only","bad:another library here","bad:not mounted","bad:folder not found","bad:not answering","bad:not answering"]',
     'у каждого состояния своё слово и тон; незнакомое состояние падает в «не отвечает», а не в «доступно»'),
    ("an_empty_library_says_so", '',
     r"""await (async () => { const s = STORES(); s[1] = { ...s[1], files: 0, size: 0, folders: [], more: 0 }; const { p, html, sum } = await mount(s);
       const before = [entryOf(html(), "local").includes('data-t="models-store-meta"></span>'), (p.choose("local"), sum().includes("models-summary-facts"))];
       p.choose("lib-a"); const lib = sum();
       return [...before, lib.includes(`data-t="models-summary-facts">${EMPTY}<`),
               lib.includes(">5.3 TB<"), lib.includes("models-store-files"), entryOf(html(), "lib-a").includes('data-t="models-store-meta"></span>')]; })()""",
     '[true,false,true,true,false,true]',
     'пустая библиотека — «моделей пока нет» словами, место при этом показано, пустого списка папок нет; negative: свой диск молчит, '
     'пока страница не сказала, сколько у неё файлов — «0 моделей» и «ещё не считали» разные вещи'),
    ("what_did_not_fit_is_named", '',
     r"""await (async () => { const s = STORES(); s[1] = { ...s[1], more: 3 }; const a = await mount(s); a.p.choose("lib-a");
       const b = await mount(); b.p.choose("lib-a"); return [a.sum().includes("…and 3 more"), b.sum().includes("…and")]; })()""",
     '[true,false]',
     'список папок обрезан лимитом — остаток назван числом; нечего называть — ничего и не пишем'),
    ("a_failed_load_says_so", '',
     r"""await (async () => { globalThis.__fetchReply["/api/model-stores"] = { __status: 500, error: "boom" }; const root = mkRoot(); const summary = mkRoot();
       m.StoresPanel.mount(root, { summary }); await settle(); const h = root.innerHTML;
       return [h.includes('data-t="models-stores-error">boom<'), h.includes('data-t="models-store"'), h.includes('data-t="models-store-add-open"'), summary.innerHTML.includes('class="mdl-card"')]; })()""",
     '[true,false,true,false]',
     'negative: сервер не ответил — список говорит это словами, а не рисует пустоту; добавить библиотеку по-прежнему можно, карточек мест нет'),
    ("before_the_first_answer_dots_not_an_empty_list", '',
     r"""(() => { const root = mkRoot(); const summary = mkRoot(); const p = new m.StoresPanel(root, { summary }); p.render();
       return [root.innerHTML.includes('<p class="muted">…</p>'), root.innerHTML.includes('data-t="models-store"'), summary.innerHTML, p.stores]; })()""",
     '[true,false,"<p class=\\"muted\\">…</p>",null]',
     'до первого ответа — «…» и в списке, и в сводке, а не пустота: «ещё не знаем» и «ничего нет» — разные вещи'),
    ("the_first_load_reuses_the_servers_memory", '',
     'await (async () => { globalThis.__fetchReply["/api/model-stores"] = { ok: true, stores: STORES() }; const root = mkRoot(); m.StoresPanel.mount(root); await settle(); return calls().map((c) => c.path); })()',
     '["/api/model-stores"]',
     'первая загрузка не заставляет сервер мерить заново — force только после действий'),
    ("add_sends_the_trimmed_path_and_measures_again", '',
     'await (async () => { const { root } = await mount(); globalThis.__input.value = "  /mnt/x  "; globalThis.__fetchReply["/api/model-stores/add"] = { ok: true, store: { id: "lib-x" } }; '
     'globalThis.__fetchReply["/api/model-stores?force=1"] = { ok: true, stores: STORES() }; await clickAdd(root); await settle(); return [calls(), globalThis.__addBtn.disabled, globalThis.__input.value]; })()',
     '[[{"path":"/api/model-stores/add","method":"POST","body":{"path":"/mnt/x","force":false}},{"path":"/api/model-stores?force=1","method":"GET","body":null}],false,""]',
     'добавить: путь без пробелов по краям, без force; потом перечитываем с force — новый замер, а не память; кнопка снова доступна, поле пустое'),
    ("add_with_an_empty_path_sends_nothing", '',
     'await (async () => { const { root } = await mount(); globalThis.__input.value = "   "; await clickAdd(root); await settle(); return calls().length; })()',
     '0',
     'negative: пустой путь — ни одного запроса'),
    ("a_bare_directory_is_asked_about_once", '',
     'await (async () => { const { root } = await mount(); globalThis.__input.value = "/mnt/lama-caravan-models"; '
     'globalThis.__fetchReply["/api/model-stores/add"] = { ok: false, code: "not-a-mount", error: "not a mount point" }; globalThis.__fetchReply["/api/model-stores?force=1"] = { ok: true, stores: STORES() }; '
     'globalThis.__stubReturns["dialogs.appConfirm"] = async (msg) => { globalThis.__confirms.push(msg); globalThis.__fetchReply["/api/model-stores/add"] = { ok: true, store: { id: "lib-x" } }; return true; }; '
     'await clickAdd(root); await settle(); return [calls().map((c) => [c.path, c.body && c.body.force]), globalThis.__confirms.length, globalThis.__confirms[0].includes("/mnt/lama-caravan-models"), globalThis.__fields.toast.textContent]; })()',
     '[[["/api/model-stores/add",false],["/api/model-stores/add",true],["/api/model-stores?force=1",null]],1,true,""]',
     'голая папка — сервер отказал, страница СПРАШИВАЕТ один раз, с путём в вопросе, и только после «да» шлёт тот же путь с force'),
    ("a_declined_bare_directory_stays_unmarked", '',
     'await (async () => { const { root } = await mount(); globalThis.__input.value = "/mnt/x"; globalThis.__fetchReply["/api/model-stores/add"] = { ok: false, code: "not-a-mount", error: "not a mount point" }; '
     'globalThis.__confirmAnswer = false; await clickAdd(root); await settle(); return [calls().length, globalThis.__confirms.length, globalThis.__fields.toast.textContent, globalThis.__addBtn.disabled]; })()',
     '[1,1,"",false]',
     'negative: оператор ответил «нет» — второго запроса нет, пометки нет, ругаться тостом не за что'),
    ("other_refusals_are_a_toast_not_a_question", '',
     'await (async () => { const { root } = await mount(); globalThis.__input.value = "/home/x/llama.cpp/models/nas"; globalThis.__fetchReply["/api/model-stores/add"] = { ok: false, code: "nested", error: "the two are nested" }; '
     'await clickAdd(root); await settle(); return [calls().length, globalThis.__confirms.length, globalThis.__fields.toast.textContent, globalThis.__input.value]; })()',
     '[1,0,"the two are nested","/home/x/llama.cpp/models/nas"]',
     'negative: любой другой отказ — тост с причиной и без вопроса: переспрашивать можно только там, где решает оператор; набранный путь остаётся для правки'),
    ("remove_asks_then_posts", '',
     'await (async () => { const { root } = await mount(); globalThis.__fetchReply["/api/model-stores/remove"] = { ok: true, removed: "lib-a" }; globalThis.__fetchReply["/api/model-stores?force=1"] = { ok: true, stores: STORES().slice(0, 1) }; '
     'const rm = { dataset: { storeRemove: "lib-a" }, disabled: false }; await clickRemove(root, rm); await settle(); return [globalThis.__confirms[0], calls(), (root.innerHTML.match(/data-t="models-store"/g) || []).length]; })()',
     '["Remove lama-caravan-models from the list? Its files and its mark stay where they are.",[{"path":"/api/model-stores/remove","method":"POST","body":{"id":"lib-a"}},{"path":"/api/model-stores?force=1","method":"GET","body":null}],1]',
     'убрать: вопрос с именем и обещанием, что файлы и метка останутся; потом запрос по id и новый замер — место ушло из списка'),
    ("a_declined_remove_sends_nothing", '',
     'await (async () => { const { root } = await mount(); globalThis.__confirmAnswer = false; const rm = { dataset: { storeRemove: "lib-a" }, disabled: false }; await clickRemove(root, rm); await settle(); return [calls().length, rm.disabled]; })()',
     '[0,false]',
     'negative: «нет» на вопросе — ни одного запроса'),
    ("a_refused_remove_is_a_toast_and_the_button_returns", '',
     'await (async () => { const { root } = await mount(); globalThis.__fetchReply["/api/model-stores/remove"] = { ok: false, code: "builtin", error: "changed with ✎, not removed" }; '
     'const rm = { dataset: { storeRemove: "lib-a" }, disabled: false }; await clickRemove(root, rm); await settle(); return [globalThis.__fields.toast.textContent, rm.disabled, calls().length]; })()',
     '["changed with ✎, not removed",false,1]',
     'negative: сервер отказал — причина тостом, кнопка снова доступна, перечитывать нечего'),
    ("enter_in_the_path_field_adds", '',
     'await (async () => { const { root } = await mount(); globalThis.__input.value = "/mnt/y"; globalThis.__fetchReply["/api/model-stores/add"] = { ok: true, store: { id: "lib-y" } }; '
     'globalThis.__fetchReply["/api/model-stores?force=1"] = { ok: true, stores: STORES() }; let prevented = 0; '
     'root.listeners.keydown[0]({ key: "Enter", preventDefault: () => { prevented += 1; }, target: target("[data-store-path]", globalThis.__input) }); await settle(); '
     'root.listeners.keydown[0]({ key: "a", preventDefault: () => { prevented += 1; }, target: target("[data-store-path]", globalThis.__input) }); await settle(); '
     'return [prevented, calls().filter((c) => c.method === "POST").map((c) => c.body.path)]; })()',
     '[1,["/mnt/y"]]',
     'Enter в поле пути добавляет (и гасится); другие клавиши — просто ввод'),
    ("every_answer_is_told_to_the_page", '',
     'await (async () => { const seen = []; globalThis.__fetchReply["/api/model-stores"] = { ok: true, stores: STORES() }; const root = mkRoot(); const p = m.StoresPanel.mount(root, { onChange: (s) => seen.push(s ? s.map((x) => x.id) : s) }); await settle(); '
     'globalThis.__fetchReply["/api/model-stores"] = { __status: 500, error: "boom" }; await p.refresh(); return seen; })()',
     '[["local","lib-a"],["local","lib-a"]]',
     'после каждого ответа панель говорит странице, что знает: кнопке переноса нужны библиотеки; неудачный замер оставляет прежний список, а не пустоту'),
    ("questions_carry_the_panels_title", '',
     'await (async () => { const { root } = await mount(); globalThis.__fetchReply["/api/model-stores/remove"] = { ok: true, removed: "lib-a" }; globalThis.__fetchReply["/api/model-stores?force=1"] = { ok: true, stores: STORES() }; '
     'await clickRemove(root, { dataset: { storeRemove: "lib-a" }, disabled: false }); await settle(); '
     'globalThis.__input.value = "/mnt/x"; globalThis.__fetchReply["/api/model-stores/add"] = { ok: false, code: "not-a-mount", error: "x" }; globalThis.__confirmAnswer = false; '
     'await clickAdd(root); await settle(); return globalThis.__titles; })()',
     '["Model stores","Model stores"]',
     'оба вопроса панели — «убрать» и «голая папка» — под её заголовком, а не общим «Confirm service action?», который к хранилищам не относится'),
    ("choosing_a_place_tells_the_page_once", '',
     r"""await (async () => { const { p, root, summary, html } = await mount(); clickPlace(root, "lib-a");
       const now = [p.scope, [...globalThis.__scopes], entryOf(html(), "lib-a").includes('aria-current="true"'), entryOf(html(), "all").includes("aria-current"), summary.dataset.tId];
       clickPlace(root, "lib-a"); const again = [...globalThis.__scopes]; clickPlace(summary, "local"); const card = [p.scope, summary.dataset.tId];
       p.choose("lib-gone"); return [...now, again, card, p.scope, globalThis.__scopes]; })()""",
     '["lib-a",["lib-a"],true,false,"lib-a",["lib-a"],["local","local"],"all",["lib-a","local","all"]]',
     'клик по месту делает его областью списка: страница слышит это ОДИН раз, подсветка и сводка переезжают; повторный клик по тому же месту — '
     'ничего; «Открыть» на карточке в сводке работает так же; negative: неизвестное место — это «Все модели», а не пустая сводка'),
    ("a_place_that_is_gone_hands_the_list_back", '',
     r"""await (async () => { const { p, summary } = await mount(); p.choose("lib-a"); globalThis.__scopes.length = 0;
       await p.refresh(); const kept = [p.scope, [...globalThis.__scopes]];
       globalThis.__fetchReply["/api/model-stores"] = { ok: true, stores: STORES().slice(0, 1) }; await p.refresh();
       return [kept, p.scope, globalThis.__scopes, summary.dataset.tId]; })()""",
     '[["lib-a",[]],"all",["all"],"all"]',
     'выбранное место исчезло (убрали здесь или в другой вкладке) — список возвращается ко всем местам и страница об этом слышит; negative: '
     'пока место на месте, новый замер область не трогает'),
    ("every_place_on_one_bar", '',
     r"""await (async () => { const { p, sum } = await mount(); p.holds(HELD()); const h = sum();
       const empty = STORES(); empty[1] = { ...empty[1], files: 0, size: 0, folders: [] }; const e = await mount(empty); e.p.holds(HELD()); const eh = e.sum();
       const none = await mount(empty); none.p.holds({ files: 0, size: 0 });
       return [h.includes('<i class="here" style="width:88.91%"></i><i class="lib0" style="width:11.09%"></i>'),
               h.includes(`🏠 This controller&#39;s disk <b>481 GB</b> · ${FILES58}`), h.includes(`📚 lama-caravan-models <b>60.0 GB</b> · ${FILES3}`),
               h.includes(`data-t="models-summary-facts">${FACTS}<`),
               eh.includes('<i class="here" style="width:100.00%"></i></div>'), eh.includes('class="lib0"'), eh.includes('data-t="models-place-card" data-t-id="lib-a"'),
               none.sum().includes("models-summary-bar")]; })()""",
     json.dumps([True, True, True, True, True, False, True, False]),
     '«Все модели»: одна полоса, у каждого места отрезок длиной в то, что оно держит, под ней — байты и файлы каждого места, в заголовке — '
     'семейства, файлы и объём разом; negative: пустое место отрезка не получает (карточка остаётся), а когда нигде ничего нет — полосы нет вовсе'),
    ("a_card_says_its_room_and_opens_its_place", '',
     r"""await (async () => { const s = STORES(); s[1] = { ...s[1], state: "low-space", detail: "12.0 GB free" }; const { p, sum } = await mount(s); p.holds(HELD());
       const loc = cardOf(sum(), "local"), lib = cardOf(sum(), "lib-a");
       return [loc.includes("<b>67.0 GB</b><span>free of 915 GB</span>"), loc.includes('<div class="mdl-full">93% full</div>'),
               loc.includes('data-scope="local" data-t="models-place-open" data-t-id="local">Open ›</button>'), loc.includes("mdl-store-state"), loc.includes("files:"),
               lib.includes('<span class="mdl-store-state warn" title="12.0 GB free">low on space</span>'), lib.includes('mdl-store-bar low')]; })()""",
     '[true,true,true,false,false,true,true]',
     'карточка места в сводке «Все модели» — его запас: свободно крупно, «из» сколько, полоса и «занято N%», и путь внутрь; что место держит, '
     'сказано в легенде полосы рядом, и карточка этого не повторяет; negative: здоровому месту слово состояния не нужно, а места мало — сказано словом, полоса жёлтая'),
    ("a_place_summary_carries_path_state_facts_and_room", '',
     r"""await (async () => { const { p, sum } = await mount(); p.holds(HELD()); p.choose("local"); const loc = sum(); p.choose("lib-a"); const lib = sum();
       return [loc.includes('This controller&#39;s disk <span class="mdl-store-state good">available</span>'), loc.includes('data-t="models-path-value" title="/home/x/llama.cpp/models"'),
               loc.includes('data-t="models-path-edit">✎</button>'), loc.includes(`data-t="models-summary-facts">${LOCAL_FACTS}<`), loc.includes("93% full"),
               loc.includes("data-store-remove"), loc.includes("models-store-files"),
               lib.includes('data-store-remove="lib-a" data-t="models-store-remove">remove</button>'), lib.includes(`data-t="models-summary-facts">${LIB_FACTS}<`),
               lib.includes('<code title="Qwen3.8-27B-GGUF">Qwen3.8-27B-GGUF</code><span class="meta">40.0 GB · 2</span>'), lib.includes("data-dir-edit")]; })()""",
     '[true,true,true,true,true,false,false,true,true,true,false]',
     'сводка одного места: имя и состояние, путь и что с ним можно (у своего диска ✎, у библиотеки «убрать»), файлы · объём · семейства, '
     'запас; у библиотеки ещё «Что внутри»; negative: у своего диска нет «убрать» и списка папок, у библиотеки нет ✎'),
    ("the_total_waits_for_this_disk", '',
     r"""await (async () => { const { p, html, sum } = await mount(); const before = [entryOf(html(), "all").includes('<span class="c"></span>'), sum().includes("models-summary-facts")];
       p.holds({ files: 58, size: 481 * GB }); const bare = sum().includes("families:");
       p.holds(HELD()); return [...before, bare, entryOf(html(), "all").includes('<span class="c">541 GB</span>'), sum().includes("families: 24")]; })()""",
     '[true,false,false,true,true]',
     'итог «Все модели» ждёт счёта своего диска: сумма без самой большой части читалась бы как целое; семейства — только те, что посчитала '
     'страница; negative: до счёта ни итога, ни фактов в сводке'),
    ("the_same_count_draws_nothing_again", '',
     r"""await (async () => { const { p, root, summary } = await mount(); p.holds(HELD()); const a = [root.writes, summary.writes];
       p.holds(HELD()); p.render(); const b = [root.writes, summary.writes];
       p.holds({ ...HELD(), size: 482 * GB }); return [b[0] - a[0], b[1] - a[1], root.writes - b[0], summary.writes - b[1]]; })()""",
     '[0,0,1,1]',
     'тот же счёт второй раз ничего не перерисовывает: разметка, заменённая под зажатой кнопкой мыши, съедает клик (так терялись клики по '
     'местам, пока страница перерисовывалась); negative: новый счёт перерисовывает и список, и сводку'),
    ("adding_opens_a_box_and_closes_it", '',
     r"""await (async () => { const { root, html } = await mount(); const closed = [html().includes('data-t="models-store-add-open"'), html().includes("models-store-add-row")];
       click(root, "[data-store-add-open]", {}); const open = [html().includes('data-t="models-store-add-row"'), html().includes("models-store-add-open"), globalThis.__input.focused];
       root.listeners.keydown[0]({ key: "Escape", preventDefault() {}, target: target("[data-store-path]", globalThis.__input) }); const esc = html().includes("models-store-add-row");
       click(root, "[data-store-add-open]", {}); click(root, "[data-store-add-cancel]", {});
       return [...closed, ...open, esc, html().includes("models-store-add-row"), html().includes("models-store-add-open")]; })()""",
     '[true,false,true,false,1,false,false,true]',
     '«Добавить библиотеку» открывает поле пути на месте кнопки и ставит в него курсор; Escape и «Отмена» закрывают; negative: закрытое поле в списке не висит'),
    ("what_is_typed_survives_a_redraw", '',
     r"""await (async () => { const { p, root } = await mount(); click(root, "[data-store-add-open]", {});
       const typed = globalThis.__input; typed.value = "/mnt/half"; const fresh = box();
       root.querySelector = (sel) => (sel === "[data-store-path]" ? (root.innerHTML.includes("…swapped") ? fresh : typed) : null);
       const real = Object.getOwnPropertyDescriptor(root, "innerHTML"); Object.defineProperty(root, "innerHTML", { get: real.get, set(v) { real.set.call(this, v + "<!--…swapped-->"); }, configurable: true });
       p.holds(HELD()); return [fresh.value, root.innerHTML.includes("…swapped")]; })()""",
     '["/mnt/half",true]',
     'набранное переживает перерисовку: перенос перерисовывает страницу на каждом приехавшем файле, и полпути в поле добавления стиралось бы'),
    ("the_pencil_edits_the_models_directory_in_place", '',
     r"""await (async () => { const saved = []; const { p, summary, sum } = await mount(STORES(), { onSavePath: async (x) => { saved.push(x); } }); p.choose("local");
       click(summary, "[data-dir-edit]", {}); const editing = [sum().includes('data-t="models-path-input"'), sum().includes('value="/home/x/llama.cpp/models"'), sum().includes("data-dir-edit")];
       globalThis.__dir = box(); globalThis.__saveBtn = box(); globalThis.__dir.value = "   ";
       await click(summary, "[data-dir-save]", globalThis.__saveBtn); const blank = [saved.length, p.editing];
       globalThis.__dir.value = "  /srv/models  "; await click(summary, "[data-dir-save]", globalThis.__saveBtn); await settle();
       return [...editing, ...blank, saved, p.editing, sum().includes("models-path-input")]; })()""",
     '[true,true,false,0,true,["/srv/models"],false,false]',
     '✎ в сводке своего диска открывает поле с текущим путём на месте пути; сохранить — путь без пробелов уходит странице (что значит '
     'сохранить, решает она), поле закрывается; negative: пустой путь не сохраняется, поле остаётся открытым'),
    ("a_refused_directory_stays_open_to_fix", '',
     r"""await (async () => { const { p, summary, sum } = await mount(STORES(), { onSavePath: async () => { throw new Error("config refused"); } }); p.choose("local");
       click(summary, "[data-dir-edit]", {}); globalThis.__dir = box(); globalThis.__dir.value = "/srv/x"; globalThis.__saveBtn = box();
       await click(summary, "[data-dir-save]", globalThis.__saveBtn); await settle();
       const failed = [globalThis.__fields.toast.textContent, p.editing, globalThis.__saveBtn.disabled];
       summary.listeners.keydown[0]({ key: "Escape", preventDefault() {}, target: target("[data-store-dir]", globalThis.__dir) });
       return [...failed, p.editing, sum().includes("models-path-input")]; })()""",
     '["config refused",true,false,false,false]',
     'negative: сохранение не прошло — причина тостом, поле остаётся открытым с кнопкой, чтобы поправить; Escape закрывает правку без сохранения'),
]


_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def main():
    if len(PINS) < 14:
        print(f"js model-stores FAILED: всего {len(PINS)} пинов — снимок урезан")
        return 1
    node = find_node()
    if node is None:
        print("js model-stores: SKIPPED — node не найден: " + ", ".join(node_search_paths()))
        return 0

    # Words the pins compare against, taken from en.js rather than retyped.
    words = (f"const EMPTY = {json.dumps(EN['storeEmpty'])};\n"
             f"const FILES58 = {json.dumps(en('mdlFiles', n=58))};\n"
             f"const FILES3 = {json.dumps(en('mdlFiles', n=3))};\n"
             f"const FACTS = {json.dumps(' · '.join([en('mdlFamilies', n=24), en('mdlFiles', n=61), '541 GB']))};\n"
             f"const LOCAL_FACTS = {json.dumps(' · '.join([en('mdlFiles', n=58), '481 GB', en('mdlFamilies', n=20)]))};\n"
             f"const LIB_FACTS = {json.dumps(' · '.join([en('mdlFiles', n=3), '60.0 GB', en('mdlFamilies', n=2)]))};\n")

    def blocks(pins, sink):
        return [f"try {{ reset(); {setup}\n  {sink}[{json.dumps(pid)}] = {expr}; }} "
                f"catch (e) {{ {sink}[{json.dumps(pid)}] = {{ __threw: String(e && e.message || e) }}; }}"
                for pid, setup, expr, _exp, _msg in pins]

    # Pins don't depend on each other: the same set run in reverse order must
    # give the same values.
    probe = (PREAMBLE + words + "\n".join(blocks(PINS, "out")) + "\nconst rev = {};\n"
             + "\n".join(blocks(list(reversed(PINS)), "rev"))
             + "\nconsole.log(JSON.stringify({ out, rev })); process.exit(0);\n")
    harness = ROOT / "scripts" / "_js_harness.mjs"
    path = ROOT / "scripts" / ".probe_js_model_stores.tmp.mjs"
    path.write_text(probe)
    try:
        env = {**os.environ, "JS_ROOT": str(ROOT / "static" / "js"), "JS_STUBS": STUBS,
               "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8", "TZ": "UTC"}
        run = subprocess.run(
            [node, "--import",
             f"data:text/javascript,import {{ register }} from 'node:module'; register('{harness.as_uri()}');",
             str(path)], capture_output=True, text=True, env=env, cwd=ROOT, timeout=120)
    finally:
        path.unlink(missing_ok=True)
    if run.returncode != 0:
        print(run.stdout)
        print(run.stderr)
        print(f"js model-stores FAILED: node вышел с кодом {run.returncode}")
        return 1
    both = json.loads(run.stdout.strip().splitlines()[-1])
    got, rev = both["out"], both["rev"]
    print("панель мест на странице /models:")
    for pid, _s, _e, expected, msg in PINS:
        want, have = json.loads(expected), got.get(pid, "\0missing")
        check(have == want, msg if have == want else
              f"{msg}\n        ожидалось {json.dumps(want, ensure_ascii=False)[:240]}"
              f"\n        получено  {json.dumps(have, ensure_ascii=False)[:240]}")
        if have != rev.get(pid, "\0missing"):
            _fail.append(f"пин {pid} зависит от порядка")
    print()
    if _fail:
        print(f"FAILED ({len(_fail)}):")
        for msg in _fail:
            print("  - " + msg.splitlines()[0])
        return 1
    print(f"js model-stores OK: настоящий модуль в node, {len(PINS)} пинов панели мест значениями")
    return 0


if __name__ == "__main__":
    sys.exit(main())
