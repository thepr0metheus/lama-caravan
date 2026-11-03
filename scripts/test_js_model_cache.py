#!/usr/bin/env python3
"""Actual model-cache.js: a machine's model cache on its card — the setting, the figures, the foreign files (1.3.576).

The owner, 2026-10-18, when the disk of a machine was 94 % full of model copies and a start died with "No space left on device": keep in
the cache only the last models, from 1 to 5, 1 by default; show the setting somewhere noticeable; delete everything older by itself. The scout
does it (caravan-scout 2.34) and reports `modelCache`; ModelCacheLine is the card's line for it: a box for the setting, what the cache holds and
what the disk has left, and — when the folder holds files the scout did not download, which it never deletes by itself — a line with a button
that deletes them after a question that names the size.

The same figures give the sign on the machine's head — the main board's glance and the machine's own card (the owner, 2026-10-18, asked for it
after a disk filled up): "⚠ disk 94% full" when the cache folder's disk is used 90 % or more. Pinned: the share rounded down, the rule at its
boundary, a disk nobody measured drawing nothing, the tip carrying the rule and not the moving figures, what redraws the head and what is patched.

Pinned, by value: what is drawn and for whom (a scout that reports no cache gets no line — never a line with a made-up setting); the figures
as words, and a part the scout did not measure left out rather than zero; what makes the card be drawn again (the setting, the foreign files)
and what is patched in place (what the cache holds, what the disk has left); the two clicks — what is sent, what is said, what is refreshed,
and that a deletion carries the size the operator was shown at the click, whatever the board holds a moment later; the wiring into the card,
the redraw and the live patch; the words in all 20 languages.

The module is loaded FOR REAL, with utils.js and state.js; i18n (English words, filled in as the board fills them) and the dialog are
stand-ins; the network and the toast are the harness's.

Run: python3 scripts/test_js_model_cache.py
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _node import find_node, probe_args  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LANGS = sorted(p.stem for p in (ROOT / "static" / "js" / "i18n").glob("*.js"))
KEYS = ["modelCacheHead", "modelCacheKeepLabel", "modelCacheKeepHelp", "modelCacheHeld", "modelCacheFree", "modelCacheForeign",
        "modelCacheForeignHelp", "modelCacheDeleteBtn", "modelCacheDeleteTitle", "modelCacheDeleteConfirm", "modelCacheKept",
        "modelCacheFreed", "modelCacheNothingYet", "diskLowChip", "diskLowTitle",
        # 2.38: the budget in GB and the folder.
        "modelCacheBudgetLabel", "modelCacheGb", "modelCacheBudgetHelp", "modelCacheBudgetUnset", "modelCacheBudgetBad", "modelCacheBudgetSet",
        "modelCacheBudgetOff", "modelCacheDirLabel", "modelCacheDirChange", "modelCacheDirHelp", "modelCacheDirPrompt", "modelCacheDirNext",
        "modelCacheDirTitle", "modelCacheDirMove", "modelCacheMoved",
        # The owner, 2026-11-02: clear it, and turn it off.
        "modelCacheClear", "modelCacheClearHelp", "modelCacheClearTitle", "modelCacheClearConfirm", "modelCacheTurnOff", "modelCacheOffHelp", "modelCacheOffPrompt",
        "modelCacheOffTitle", "modelCacheOffConfirm", "modelCacheIsOff", "modelCacheIsOn", "modelCacheOffWord", "modelCacheLibraryLabel", "modelCacheTurnOn", "modelCacheOnHelp",
        "modelCacheOnTitle", "modelCacheOnConfirm",
        "modelCacheThroughWord", "modelCacheUseFolder", "modelCacheUseThrough", "modelCacheThroughHelp", "modelCacheOffConfirmThrough", "modelCacheIsOffThrough",
        "modelCacheLibraryNotSet", "modelCacheLibraryHelp", "modelCacheLibrarySave", "modelCacheLibraryIs"]

PROBE = r'''
import "./_js_globals.mjs";
import assert from "node:assert/strict";
const en = (await import("../static/js/i18n/en.js")).default;
const asked = [], toasts = [], refreshes = [], fieldsAsked = [];
let answer = true, confirmHook = null, typed = null, chosen = "move", filled = null;
const prompted = [], choiceAsked = [];
globalThis.__stubReturns = {
  "i18n.t": (key, vars = {}) => String(en[key] ?? `?${key}`).replace(/\{(\w+)\}/g, (_, name) => (vars[name] === undefined ? `{${name}}` : vars[name])),
  "dialogs.appConfirm": async (message, opts) => { asked.push({ message, opts }); if (confirmHook) confirmHook(); return answer; },
  "dialogs.appPrompt": async (message, opts) => { prompted.push({ message, opts }); return typed; },
  "dialogs.appConfirmChoice": async (message, opts) => { choiceAsked.push({ message, opts }); return chosen; },
  "dialogs.appConfirmFields": async (message, opts) => { fieldsAsked.push({ message, opts }); return filled; },
};
const toastEl = { textContent: "", classList: { add() {}, remove() {} } };
globalThis.__fields = { toast: toastEl };
const spoken = [];
Object.defineProperty(toastEl, "textContent", { get() { return spoken.at(-1) ?? ""; }, set(v) { spoken.push(v); } });
const st = await import("../static/js/state.js");
const { ModelCacheLine } = await import("../static/js/model-cache.js");
const { escapeHtml } = await import("../static/js/utils.js");
const pass = [];
const pin = (cond, why) => { assert.ok(cond, why); pass.push(why); };
const eq = (got, want, why) => { assert.deepEqual(got, want, why + ` (got ${JSON.stringify(got)})`); pass.push(why); };
const GB = 2 ** 30;
const FACTS = { keep: 1, managedBytes: 12 * GB, foreign: { files: 3, bytes: 67 * GB, folders: [{ folder: "hand-copied", files: 2, bytes: 61 * GB }, { folder: "speech", files: 1, bytes: 6 * GB }] },
                disk: { totalBytes: 900 * GB, freeBytes: 400 * GB } };
const node = (facts, id = "h1") => ({ id, name: "Box", modelCache: facts });
const reset = () => { asked.length = 0; toasts.length = 0; refreshes.length = 0; spoken.length = 0; answer = true; confirmHook = null; typed = null; prompted.length = 0; choiceAsked.length = 0; chosen = "move"; fieldsAsked.length = 0; filled = null; globalThis.__fetchCalls.length = 0; globalThis.__fetchReply = {}; };
const refresh = async () => { refreshes.push(1); };
const sent = () => globalThis.__fetchCalls.map((c) => ({ path: c.path, method: c.method, body: JSON.parse(c.body) }));

// ── for whom the line is drawn ──
{
  const line = ModelCacheLine.of(node(FACTS));
  pin(line.drawn === true && line.html().includes('data-t="node-cache"'), "a scout that reports its cache gets the line");
  const none = [undefined, null, {}, { keep: 0 }, { keep: -1 }, { keep: "1" }, { keep: 1.5 }, { keep: true }, "keeps 1", []];
  eq(none.map((facts) => [ModelCacheLine.of(node(facts)).drawn, ModelCacheLine.of(node(facts)).html(), ModelCacheLine.of(node(facts)).fingerprint()]),
     none.map(() => [false, "", "-"]),
     "negative: a scout that says nothing about its cache (older than 2.34) or says a setting that is no setting gets no line — never a line with a made-up '1'");
  eq([ModelCacheLine.of(undefined).drawn, ModelCacheLine.of(null).drawn, ModelCacheLine.of({}).drawn], [false, false, false], "negative: a card with no node, or one with no record, draws nothing and does not throw");
}

// ── the figures as words ──
{
  const line = ModelCacheLine.of(node(FACTS));
  eq(line.figures(), "holds 12.0 GB · 400 GB free of 900 GB", "what the cache holds and what the disk has left, in the units the pages print (fmtGb, fmtSpace)");
  const big = ModelCacheLine.of(node({ ...FACTS, disk: { totalBytes: 7 * 2 ** 40, freeBytes: 5.5 * 2 ** 40 } }));
  eq(big.figures(), "holds 12.0 GB · 5.5 TB free of 7.0 TB", "a disk of terabytes says terabytes");
  eq(ModelCacheLine.of(node({ ...FACTS, managedBytes: null })).figures(), "400 GB free of 900 GB", "negative: what the cache holds was not measured — left out, not '0'");
  eq(ModelCacheLine.of(node({ ...FACTS, disk: null })).figures(), "holds 12.0 GB", "negative: the disk could not be measured — left out");
  eq(ModelCacheLine.of(node({ keep: 2 })).figures(), "", "negative: nothing measured — no figures at all");
  eq(ModelCacheLine.of(node({ ...FACTS, managedBytes: 0 })).figures().startsWith("holds 0.00 GB"), true, "boundary: an empty cache holds 0 — that is a measure, and it is said");
  eq([ModelCacheLine.of(node({ ...FACTS, disk: { totalBytes: 0, freeBytes: 0 } })).disk, ModelCacheLine.of(node({ ...FACTS, disk: { totalBytes: 9 } })).disk,
      ModelCacheLine.of(node({ ...FACTS, disk: { totalBytes: "9", freeBytes: 1 } })).disk],
     [null, null, null], "negative: a disk of no size, with a figure missing or in text, is not a disk");
  eq(ModelCacheLine.of(node({ ...FACTS, disk: { totalBytes: 100 * GB, freeBytes: 400 * GB } })).figures(), "holds 12.0 GB",
     "negative: more free than the disk holds cannot be — the disk part is left out, not drawn as a figure that contradicts itself");
  eq([ModelCacheLine.of(node({ ...FACTS, managedBytes: "12" })).heldBytes, ModelCacheLine.of(node({ ...FACTS, managedBytes: NaN })).heldBytes], [null, null],
     "negative: a held figure that is text or not a number is not a figure");
}

// ── the setting's box ──
{
  eq(ModelCacheLine.of(node(FACTS)).choices, [1, 2, 3, 4, 5], "the box offers the scout's range, 1 to 5");
  eq(ModelCacheLine.of(node({ ...FACTS, keep: 7 })).choices, [1, 2, 3, 4, 5, 7], "a setting the scout reports outside the range is still shown — the box never shows a setting it does not hold");
  const html = ModelCacheLine.of(node({ ...FACTS, keep: 3 })).html();
  eq([...html.matchAll(/<option value="(\d)"( selected)?>/g)].map((m) => [m[1], !!m[2]]), [["1", false], ["2", false], ["3", true], ["4", false], ["5", false]],
     "the reported setting is the one chosen");
  pin(html.includes('data-t="node-cache-keep" data-t-id="h1" data-cache-keep="h1"'), "the box is found by its hook and carries its machine");
  pin(html.includes("Model cache") && html.includes("Keeps the last:") && html.includes(escapeHtml(en.modelCacheKeepHelp)), "the line says what it is and what the number means, and the help stands on it");
  const odd = ModelCacheLine.of({ id: 'a"><b>', name: "x", modelCache: FACTS }).html();
  pin(!odd.includes('"><b>') && odd.includes("&quot;&gt;&lt;b&gt;"), "negative: a machine id with markup in it is written out as text, not as markup");
}

// ── the foreign files ──
{
  const line = ModelCacheLine.of(node(FACTS));
  const html = line.html();
  pin(html.includes('data-t="node-cache-foreign" data-t-id="h1"') && html.includes("Files Caravan did not download: 3 · 67.0 GB")
      && html.includes('data-t="node-cache-delete" data-t-id="h1" data-cache-delete-foreign="h1"'),
      "files the scout did not download are said with their number and size, and the button that deletes them stands on that line");
  eq(line.folders(), "hand-copied · 61.0 GB\nspeech · 6.00 GB", "the folders they lie in, one to a line");
  pin(html.includes(escapeHtml(en.modelCacheForeignHelp)) && html.includes("hand-copied · 61.0 GB"), "the line's help says why the scout leaves them and where they lie");
  for (const [facts, why] of [[{ ...FACTS, foreign: { files: 0, bytes: 0, folders: [] } }, "none lie there"], [{ ...FACTS, foreign: null }, "the scout did not say"],
                              [{ ...FACTS, foreign: { files: 2, bytes: null, folders: [] } }, "their size is not a number"],
                              [{ ...FACTS, foreign: { files: "2", bytes: 5 } }, "their number is text"], [{ ...FACTS, foreign: "none" }, "it is not a block"]]) {
    const l = ModelCacheLine.of(node(facts));
    pin(l.foreign === null && !l.html().includes("node-cache-foreign") && !l.html().includes("data-cache-delete-foreign"),
        `negative: no foreign line and no delete button when ${why} — a button that deletes needs a size to ask about`);
  }
  eq(ModelCacheLine.of(node({ ...FACTS, foreign: { files: 1, bytes: 5 * GB } })).folders(), "", "a record with no folder names (an older block) lists none and does not throw");
}

// ── what redraws the card, and what is patched in place ──
{
  const fp = (facts) => ModelCacheLine.of(node(facts)).fingerprint();
  const base = fp(FACTS);
  pin(fp({ ...FACTS, keep: 2 }) !== base, "the setting moved (here or from another tab): the card is drawn again");
  pin(fp({ ...FACTS, foreign: { ...FACTS.foreign, files: 4 } }) !== base && fp({ ...FACTS, foreign: { ...FACTS.foreign, bytes: 70 * GB } }) !== base
      && fp({ ...FACTS, foreign: { files: 0, bytes: 0, folders: [] } }) !== base && fp({ ...FACTS, foreign: null }) !== base,
      "foreign files came, went or changed — or became unknown: the card is drawn again, the line comes and goes");
  pin(fp({ ...FACTS, managedBytes: 99 * GB }) === base && fp({ ...FACTS, disk: { totalBytes: 900 * GB, freeBytes: 300 * GB } }) === base,
      "negative: what the cache holds and what the disk has left move with every download — they never redraw the board; the live patch writes them");
  pin(fp({ ...FACTS, managedBytes: null }) !== base && fp({ ...FACTS, disk: null }) !== base,
      "but a part coming or going (measured / not) is a different line and redraws");
  pin(fp(undefined) === "-" && fp({ keep: 1 }) !== "-", "a record with nothing in it has a fingerprint of its own");
}

// ── the setting, changed ──
{
  const box = (value = "3", host = "h1") => ({ dataset: { cacheKeep: host }, value, disabled: false, blurred: 0, blur() { this.blurred++; } });
  st.setTopology({ nodes: [node(FACTS)] });
  reset();
  globalThis.__fetchReply["/api/topology/client-llama/cache-keep"] = { ok: true, hostId: "h1", result: { ok: true, keep: 3, removed: 2, freedBytes: 30 * GB, waiting: false } };
  const b = box("3");
  await ModelCacheLine.setKeep(b, refresh);
  eq(sent(), [{ path: "/api/topology/client-llama/cache-keep", method: "POST", body: { hostId: "h1", keep: 3 } }],
     "the box sends its machine and the number, as a number, to the controller — and nothing else");
  eq(spoken, ["The cache of Box keeps the last: 3 · Freed 30.0 GB · files deleted: 2"], "the operator is told what the scout did: the setting, and the files that went with it");
  pin(b.disabled === false && b.blurred === 1 && refreshes.length === 1,
      "the box is free again, lets go of the focus (a box that holds it holds the board's redraw back), and the board draws what the controller now holds");

  reset();
  globalThis.__fetchReply["/api/topology/client-llama/cache-keep"] = { ok: true, result: { ok: true, keep: 5, removed: 0, freedBytes: 0, waiting: false } };
  await ModelCacheLine.setKeep(box("5"), refresh);
  eq(spoken, ["The cache of Box keeps the last: 5"], "a setting that deletes nothing says only the setting");
  reset();
  globalThis.__fetchReply["/api/topology/client-llama/cache-keep"] = { ok: true, result: { ok: true, keep: 2, removed: 0, freedBytes: 0, waiting: true } };
  await ModelCacheLine.setKeep(box("2"), refresh);
  eq(spoken, ["The cache of Box keeps the last: 2. No model has run on Box since its scout began to keep a log, so nothing is deleted yet. The cache is trimmed after the next start."],
     "the scout knows no model that ran: the setting is kept, and the words say why nothing went — the first start after the update begins the log");
  reset();
  globalThis.__fetchReply["/api/topology/client-llama/cache-keep"] = { ok: true, result: { ok: true } };
  await ModelCacheLine.setKeep(box("4"), refresh);
  eq(spoken, ["The cache of Box keeps the last: 4"], "an answer that does not echo the setting is worded with the one that was sent");
  reset();
  globalThis.__fetchReply["/api/topology/client-llama/cache-keep"] = { __status: 502, error: "h1: keep must be 1 to 5" };
  const refused = box("9");
  await ModelCacheLine.setKeep(refused, refresh);
  pin(spoken.length === 1 && spoken[0].includes("keep must be 1 to 5") && refused.disabled === false && refresh.length === 0 && refreshes.length === 1,
      "negative: the scout refuses — its words are said, the box is free again, and the board is drawn from what the controller holds");
  eq(refused.value, "1", "and the box goes back to the setting the controller holds: its record did not change, so the redraw sees no structure moved and would leave the refused 9 in the box");
  reset();
  globalThis.__fetchReply["/api/topology/client-llama/cache-keep"] = { __status: 502, error: "ghost unreachable" };
  const lost = box("4", "ghost");
  await ModelCacheLine.setKeep(lost, refresh);
  eq(lost.value, "4", "negative: a machine the board does not hold has no setting to go back to — the box is left as it is, and nothing throws");
  reset();
  await ModelCacheLine.setKeep(box("3", "ghost"), refresh);
  pin(sent()[0].body.hostId === "ghost" && spoken[0].startsWith("The cache of ghost keeps"), "a machine the board does not hold is named by its id");
}

// ── the budget in GB and the folder (2.38: the owner, "in GB, not in models"; "an HDD, not the SSD") ──
{
  const B = { ...FACTS, budgetBytes: null, dir: "/home/u/llama-model-cache" };
  const unset = ModelCacheLine.of(node(B));
  const html = unset.html();
  pin(unset.budgets === true && unset.budgetGb === null
      && html.includes('<input type="number" class="cache-budget" min="1" step="1" inputmode="numeric" value="" placeholder="not set" data-t="node-cache-budget" data-t-id="h1" data-cache-budget="h1">')
      && html.includes("At most:") && html.includes(">GB</span>") && !html.includes("data-cache-keep"),
      "a scout of 2.38 gets the budget's box in GB in place of the count's: empty with \"not set\" while none is chosen — the last models rule then");
  pin(html.includes(escapeHtml(en.modelCacheBudgetHelp.replace("{n}", "1"))), "its help says what it keeps, and what an empty box means (the last 1 model)");
  const set = ModelCacheLine.of(node({ ...B, budgetBytes: 100 * GB }));
  pin(set.budgetGb === 100 && set.html().includes('value="100"'), "a chosen budget stands in the box, in GB (the board's GB: 2^30, as the figures beside it)");
  const old = ModelCacheLine.of(node(FACTS));
  pin(old.budgets === false && old.html().includes("data-cache-keep") && !old.html().includes("data-cache-budget"),
      "negative: a scout older than 2.38 says no budget — the count's box stays, never a box it cannot set");
  pin(html.includes('<div class="cache-dir" data-t="node-cache-dir" data-t-id="h1"><span class="cache-dir-label">Folder:</span>'
                    + '<code class="cache-dir-path" dir="ltr" title="/home/u/llama-model-cache">/home/u/llama-model-cache</code>')
      && html.includes('data-t="node-cache-dir-change" data-t-id="h1" data-cache-dir="h1"') && html.includes(">Change…</button>"),
      "the folder the cache is in stands on its line, with the button that moves it; the path reads left to right in every "
      + "language (in Arabic and Urdu its first slash went to the end)");
  pin(!old.html().includes("node-cache-dir") && !ModelCacheLine.of(node({ ...B, dir: "relative/x" })).html().includes("node-cache-dir"),
      "negative: a scout that names no folder (or no absolute one) offers no move");
  const fp = (facts) => ModelCacheLine.of(node(facts)).fingerprint();
  pin(fp(B) !== fp(FACTS) && fp(B) !== fp({ ...B, budgetBytes: 100 * GB }) && fp(B) !== fp({ ...B, dir: "/mnt/hdd/cache" }),
      "the budget and the folder redraw the card when they move — chosen or not, here or from another tab");
}

// ── the budget, changed ──
{
  const B = { ...FACTS, budgetBytes: 50 * GB, dir: "/home/u/llama-model-cache" };
  const box = (value, host = "h1") => ({ dataset: { cacheBudget: host }, value, disabled: false, blurred: 0, blur() { this.blurred++; } });
  st.setTopology({ nodes: [node(B)] });
  reset();
  globalThis.__fetchReply["/api/topology/client-llama/cache-budget"] = { ok: true, result: { ok: true, budgetBytes: 100 * GB, removed: 2, freedBytes: 30 * GB, waiting: false } };
  const b = box(" 100 ");
  await ModelCacheLine.setBudget(b, refresh);
  eq(sent(), [{ path: "/api/topology/client-llama/cache-budget", method: "POST", body: { hostId: "h1", budgetBytes: 100 * GB } }],
     "the box sends its machine and the budget in bytes (100 GB × 2^30)");
  eq(spoken, ["The cache of Box keeps at most 100 GB · Freed 30.0 GB · files deleted: 2"], "the operator is told the budget and what went with it");
  pin(b.disabled === false && b.blurred === 1 && refreshes.length === 1, "the box is free again, lets go of the focus, and the board is drawn again");
  reset();
  globalThis.__fetchReply["/api/topology/client-llama/cache-budget"] = { ok: true, result: { ok: true, budgetBytes: null, removed: 0, freedBytes: 0, waiting: false } };
  await ModelCacheLine.setBudget(box(""), refresh);
  eq([sent()[0].body.budgetBytes, spoken], [null, ["The cache of Box keeps the last models again"]],
     "an empty box takes the budget off — sent as null, and the words say the last models rule again");
  for (const bad of ["0", "2.5", "abc", "-3"]) {
    reset();
    const refused = box(bad);
    await ModelCacheLine.setBudget(refused, refresh);
    pin(sent().length === 0 && spoken[0] === "The cache limit is a whole number of GB, 1 or more" && refused.value === "50",
        `negative: ${JSON.stringify(bad)} is no budget — said, nothing sent, and the box goes back to the 50 the controller holds`);
  }
  reset();
  globalThis.__fetchReply["/api/topology/client-llama/cache-budget"] = { __status: 502, error: "h1: budgetBytes must be a whole number of bytes" };
  const fails = box("70");
  await ModelCacheLine.setBudget(fails, refresh);
  pin(spoken.length === 1 && spoken[0].includes("budgetBytes must be") && fails.value === "50" && refreshes.length === 1,
      "negative: the scout refuses — its words are said, the box goes back to what the controller holds, the board is drawn again");
}

// ── the folder, moved: its files carried or deleted, as the operator says (2026-11-03) ──
{
  const B = { ...FACTS, budgetBytes: null, managedBytes: 95 * GB, dir: "/home/u/llama-model-cache" };
  const DIR = "/api/topology/client-llama/cache-dir";
  st.setTopology({ nodes: [node(B)] });
  reset();
  typed = " /mnt/hdd/models ";
  globalThis.__fetchReply[DIR] = { ok: true, result: { ok: true, moving: true, dir: "/mnt/hdd/models", totalBytes: 95 * GB, files: 5 } };
  await ModelCacheLine.moveFolder("h1", refresh);
  eq([prompted[0].message, prompted[0].opts.value, prompted[0].opts.confirmLabel],
     ["New folder for the model cache of Box — the full path on that machine:", "/home/u/llama-model-cache", "Next"],
     "first the folder is asked, the present one in the box");
  const q = choiceAsked[0];
  eq([q.message, q.opts.title, q.opts.detail, q.opts.confirmLabel, q.opts.choice, q.opts.choices.map((c) => [c.value, c.label])],
     ["The old folder holds 95.0 GB of Caravan's files. Move them to the new folder, or delete them?", "Move the model cache?",
      "/home/u/llama-model-cache → /mnt/hdd/models", "Move", "move", [["move", "Move them"], ["delete", "Delete them"]]],
     "then whether the files go with it or are deleted, naming how much, where from and where to — moving them pressed first");
  eq(sent(), [{ path: DIR, method: "POST", body: { hostId: "h1", path: "/mnt/hdd/models", how: "move" } }],
     "the controller gets the machine, the folder trimmed, and the choice");
  eq(spoken, ["Moving 95.0 GB to /mnt/hdd/models: the page shows how far it is"], "a move under way is said as one, with its size");
  pin(refreshes.length === 1 && asked.length === 0, "the page is drawn again, and no other question was asked");
  reset();
  typed = "/mnt/hdd/models";
  chosen = "delete";
  globalThis.__fetchReply[DIR] = { ok: true, result: { ok: true, dir: "/mnt/hdd/models", removed: 5, freedBytes: 95 * GB } };
  await ModelCacheLine.moveFolder("h1", refresh);
  eq(sent()[0].body.how, "delete", "deleting them is the other choice, sent as it is");
  eq(spoken, ["The model cache of Box is in /mnt/hdd/models now · Freed 95.0 GB · files deleted: 5"], "the operator is told where the cache is and what went");
  for (const [answerTyped, why] of [[null, "the folder's question cancelled"], ["  ", "an empty folder"], ["/home/u/llama-model-cache", "the folder it is in"]]) {
    reset();
    typed = answerTyped;
    await ModelCacheLine.moveFolder("h1", refresh);
    pin(choiceAsked.length === 0 && sent().length === 0 && refreshes.length === 0, `negative: ${why} — no second question, nothing sent`);
  }
  reset();
  typed = "/mnt/hdd/models";
  chosen = null;
  await ModelCacheLine.moveFolder("h1", refresh);
  pin(choiceAsked.length === 1 && sent().length === 0 && spoken.length === 0, "negative: 'Cancel' on the choice moves nothing");
  reset();
  typed = "/mnt/hdd/models";
  globalThis.__fetchReply[DIR] = { __status: 502, error: "h1: the cache does not move while a cell is bringing its model: :22003 — try again when it runs" };
  await ModelCacheLine.moveFolder("h1", refresh);
  pin(spoken.length === 1 && spoken[0].includes("does not move while a cell is bringing its model: :22003") && refreshes.length === 1,
      "negative: the scout refuses while a cell loads — its words, the cell named, are said");
  reset();
  st.setTopology({ nodes: [node({ ...B, managedBytes: 0 })] });
  typed = "/mnt/hdd/models";
  globalThis.__fetchReply[DIR] = { ok: true, result: { ok: true, dir: "/mnt/hdd/models", removed: 0, freedBytes: 0 } };
  await ModelCacheLine.moveFolder("h1", refresh);
  pin(choiceAsked.length === 0 && sent()[0].body.how === "delete", "an empty cache has nothing to carry: no choice is asked, and nothing goes");
  reset();
  st.setTopology({ nodes: [node(FACTS)] });
  await ModelCacheLine.moveFolder("h1", refresh);
  pin(prompted.length === 0 && sent().length === 0, "negative: a machine whose scout names no folder is asked nothing");
}

// ── the files the scout did not download, deleted ──
{
  const FOREIGN = { files: 3, bytes: 71_000_000_001, folders: [{ folder: "hand-copied", files: 2, bytes: 61 * GB }, { folder: "speech", files: 1, bytes: 6 * GB }] };
  const open = (facts = { ...FACTS, foreign: FOREIGN }) => st.setTopology({ nodes: [node(facts)] });
  open();
  reset();
  globalThis.__fetchReply["/api/topology/client-llama/cache-delete-foreign"] = { ok: true, result: { ok: true, removed: 3, freedBytes: 71_000_000_001 } };
  await ModelCacheLine.deleteForeign("h1", refresh);
  eq(asked.map((a) => a.message), ["On Box, delete the files in the model cache that Caravan did not download. Files: 3, 66.1 GB. They cannot be restored."],
     "the question names the machine, how many files and how big");
  eq([asked[0].opts.title, asked[0].opts.detail, asked[0].opts.confirmLabel], ["Delete files from the model cache?", "hand-copied · 61.0 GB · speech · 6.00 GB", "Delete"],
     "and the folders they lie in, on a title of its own, with a button that says delete");
  eq(sent(), [{ path: "/api/topology/client-llama/cache-delete-foreign", method: "POST", body: { hostId: "h1", expectBytes: 71_000_000_001 } }],
     "yes: the controller gets the machine and the size to the byte — the scout deletes only if it is still that size");
  eq(spoken, ["Freed 66.1 GB · files deleted: 3"], "the operator is told what went");
  pin(refreshes.length === 1, "and the board draws what the controller holds now");

  reset();
  answer = false;
  await ModelCacheLine.deleteForeign("h1", refresh);
  pin(asked.length === 1 && sent().length === 0 && spoken.length === 0 && refreshes.length === 0, "negative: 'Cancel' deletes nothing, says nothing and redraws nothing");

  reset();
  open({ ...FACTS, foreign: { ...FOREIGN, files: 0, bytes: 0 } });
  await ModelCacheLine.deleteForeign("h1", refresh);
  pin(asked.length === 0 && sent().length === 0, "negative: no foreign files on the board now — no question, nothing sent (a stale button asks nothing it cannot name)");
  await ModelCacheLine.deleteForeign("ghost", refresh);
  pin(asked.length === 0 && sent().length === 0, "negative: a machine the board does not hold — the same");

  reset();
  open();
  confirmHook = () => open({ ...FACTS, foreign: { ...FOREIGN, bytes: 99 * GB } });
  globalThis.__fetchReply["/api/topology/client-llama/cache-delete-foreign"] = { ok: true, result: { ok: true, removed: 3, freedBytes: 1 } };
  await ModelCacheLine.deleteForeign("h1", refresh);
  eq(sent()[0].body.expectBytes, 71_000_000_001,
     "the size sent is the size the question named, taken before the dialog opened: the board redraws behind the dialog every few seconds, and without this the operator would approve one figure and the scout be asked about another");

  reset();
  open();
  globalThis.__fetchReply["/api/topology/client-llama/cache-delete-foreign"] = { __status: 502, error: "h1: the cache changed since it was shown: 70,000,000,000 bytes of files this scout did not download, not 71,000,000,001 — nothing was deleted" };
  await ModelCacheLine.deleteForeign("h1", refresh);
  pin(spoken.length === 1 && spoken[0].includes("the cache changed since it was shown") && spoken[0].includes("nothing was deleted") && refreshes.length === 1,
      "negative: the scout refuses because the files changed — its words are said and the board is drawn again, with the size it now has");
}

// ── the sign on the machine's head ──
{
  const disk = (total, free) => ({ ...FACTS, disk: { totalBytes: total, freeBytes: free } });
  const line = (total, free) => ModelCacheLine.of(node(disk(total, free)));
  eq([line(1000, 100).diskUsedPct, line(1000, 101).diskUsedPct, line(900 * GB, 400 * GB).diskUsedPct, line(1000, 0).diskUsedPct],
     [90, 89, 55, 100], "the share used, in whole percent, ROUNDED DOWN: 90 % shown means 90 % or more is used, never 89.9");
  pin(line(1000, 100).diskLow === true && line(1000, 101).diskLow === false,
      "boundary: a disk used exactly 90 % is almost full, one byte-in-a-thousand less is not — the rule is '90 or more', on the share as shown");
  pin(line(1000, 0).diskLow === true && line(1000, 50).diskLow === true && line(1000, 500).diskLow === false,
      "a full disk and a 95 % disk are almost full; a half-empty one is not");
  pin(ModelCacheLine.DISK_LOW_USED_PCT === 90, "the threshold is the class's own, one place for it");
  ModelCacheLine.DISK_LOW_USED_PCT = 80;
  try {
    pin(line(1000, 200).diskLow === true && line(1000, 201).diskLow === false && line(1000, 200).diskChipHtml().includes("is almost full: 80% or more is used."),
        "one place for the threshold: change it and the rule and the tip's words follow — the tip holds no number of its own");
  } finally { ModelCacheLine.DISK_LOW_USED_PCT = 90; }
  for (const [facts, why] of [[disk(0, 0), "of no size"], [{ ...FACTS, disk: null }, "nobody measured"], [{ ...FACTS, disk: { totalBytes: 1000 } }, "with its free figure missing"],
                              [disk(1000, 5000), "free more than its size"], [{ keep: 1 }, "no figures at all"], [undefined, "no record"]]) {
    const l = ModelCacheLine.of(node(facts));
    pin(l.diskLow === false && l.diskChipHtml() === "" && l.diskWords() === "",
        `negative: a disk ${why} draws no sign — the sign says only what the scout measured, and a disk that has not been measured is not called roomy either`);
  }
  const chip = line(1000, 60).diskChipHtml();
  pin(chip.includes('class="node-disk-low" data-t="node-disk-low" data-t-id="h1"') && chip.includes("⚠ ") && chip.includes("<span data-live-diskpct>disk 94% full</span>"),
      "the sign names its machine and says how full the disk is, with the live hook on the words");
  pin(chip.includes('title="The disk that holds this machine&#39;s model cache is almost full: 90% or more is used.') && chip.includes("out-of-space error"),
      "the tip says what the rule is (90 % or more) and why it matters — read from the class's threshold");
  eq(line(1000, 60).diskChipHtml().replace(/disk \d+% full/, "X"), line(1000, 20).diskChipHtml().replace(/disk \d+% full/, "X"),
     "the tip holds the rule, not the figures: two almost-full disks of different fullness differ in the words and nowhere else (a tip is written once, the figures move)");
  pin(!line(1000, 500).diskChipHtml().includes("node-disk-low"), "negative: a disk with room draws no sign");
  const odd = ModelCacheLine.of({ id: 'a"><b>', name: "x", modelCache: disk(1000, 10) }).diskChipHtml();
  pin(!odd.includes('"><b>') && odd.includes("&quot;&gt;&lt;b&gt;"), "negative: a machine id with markup in it is written out as text in the sign too");
  eq(ModelCacheLine.of(node(disk(1000, 60))).diskWords(), "disk 94% full", "the words alone — what the live patch writes");

  const fp = (facts) => ModelCacheLine.of(node(facts)).fingerprint();
  pin(fp(disk(1000, 500)) !== fp(disk(1000, 60)) && fp(disk(1000, 60)) === fp(disk(1000, 20)) && fp(disk(1000, 500)) === fp(disk(1000, 400)),
      "the sign coming or going redraws the head (the fingerprint moves); the disk filling inside the low band, or inside the roomy one, does not — the percent is patched in place");
  pin(fp(disk(1000, 101)) !== fp(disk(1000, 100)), "boundary: crossing 90 % either way is the one move that matters");
}

// ── the wiring ──
{
  const make = (dataset) => ({ dataset, handlers: {}, addEventListener(type, fn) { this.handlers[type] = fn; } });
  const boxes = [make({ cacheKeep: "h1" }), make({ cacheKeep: "h2" })], buttons = [make({ cacheDeleteForeign: "h1" }), make({})];
  const budgets = [make({ cacheBudget: "h1" })], folders = [make({ cacheDir: "h1" })], limits = [make({ cacheWorkBudget: "h1" })];
  const asks = [];
  const found = { "[data-cache-keep]": boxes, "[data-cache-budget]": budgets, "[data-cache-work-budget]": limits, "[data-cache-dir]": folders, "[data-cache-delete-foreign]": buttons };
  const root = { querySelectorAll(selector) { asks.push(selector); return found[selector] || []; } };
  ModelCacheLine.bind(root, refresh);
  pin(asks.join(",") === "[data-cache-keep],[data-cache-budget],[data-cache-work-budget],[data-cache-dir],[data-cache-clear],[data-cache-off],[data-cache-on],[data-cache-library],[data-cache-through],[data-cache-dir-remove],[data-cache-work],[data-cache-work-remove],[data-cache-delete-foreign]"
      && [...boxes, ...budgets, ...limits].every((b) => typeof b.handlers.change === "function")
      && [...buttons, ...folders].every((b) => typeof b.handlers.click === "function"),
      "every box and every button under the card's container gets its handler, found by its data attribute — the budget's box and the folder's button (2.38) too, and Strata's limit");
  st.setTopology({ nodes: [node({ ...FACTS, foreign: { files: 1, bytes: 5 * GB, folders: [] } })] });
  reset();
  let stopped = 0;
  await buttons[0].handlers.click({ stopPropagation: () => { stopped++; } });
  pin(stopped === 1 && asked.length === 1, "the click does not reach the card under the button, and asks");
  reset();
  await buttons[1].handlers.click({ stopPropagation: () => {} });
  pin(asked.length === 0 && sent().length === 0, "negative: a button with no machine in it asks nothing");
  pin(ModelCacheLine.bind(null, refresh) === undefined && ModelCacheLine.bind(undefined, refresh) === undefined, "negative: a board without its container binds nothing and does not throw");
}

// ── the words ──
{
  const langs = JSON.parse(process.env.LANGS), keys = JSON.parse(process.env.KEYS);
  const holes = (s) => [...String(s).matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort().join(",");
  const want = { modelCacheHeld: "size", modelCacheFree: "free,total", modelCacheForeign: "n,size", modelCacheDeleteConfirm: "host,n,size", modelCacheKept: "host,n",
                 modelCacheFreed: "n,size", modelCacheNothingYet: "host",
                 diskLowChip: "pct", diskLowTitle: "limit",
                 modelCacheBudgetHelp: "n", modelCacheBudgetSet: "host,size", modelCacheBudgetOff: "host", modelCacheDirPrompt: "host",
                 modelCacheMoved: "dir,host" };
  const lacking = [], wrong = [], same = [];
  for (const lang of langs) {
    const m = (await import(`../static/js/i18n/${lang}.js`)).default;
    for (const key of keys) {
      if (!m[key]) { lacking.push(`${lang}.${key}`); continue; }
      // The unit GB is written as English writes it in many languages: the same text there is the right one. Indonesian says
      // "folder", as its file does in every string that names one.
      const sameIsRight = ["modelCacheDeleteBtn", "modelCacheHead", "modelCacheGb"].includes(key) || `${lang}.${key}` === "id.modelCacheDirLabel";
      if (lang !== "en" && m[key] === en[key] && !sameIsRight) same.push(`${lang}.${key}`);
      if (key in want && holes(m[key]) !== want[key]) wrong.push(`${lang}.${key}: ${holes(m[key])}`);
    }
  }
  eq(lacking, [], `all ${keys.length} keys of the line and its sign (2.38: the budget and the folder too) exist in all ${langs.length} languages`);
  eq(wrong, [], "every language fills the holes the code fills — host, number, size, free, total — and no other");
  eq(same, [], "no language is left with the English text");
  eq(Object.entries(want).filter(([key, h]) => holes(en[key]) !== h).map(([key]) => key), [], "and the English words have exactly those holes");
}

for (const why of pass) console.log("  ok  " + why);
// ── clear it, and turn it off (the owner, 2026-11-02) ──
{
  const ON = { ...FACTS, foreign: null, budgetBytes: null, managedBytes: 95 * GB, dir: "/home/u/cache", off: false };
  const OFF = { ...ON, managedBytes: 0, off: true, library: "/mnt/lib" };
  const on = ModelCacheLine.of(node(ON)), off = ModelCacheLine.of(node(OFF)), old = ModelCacheLine.of(node({ ...ON, off: undefined })), empty = ModelCacheLine.of(node({ ...ON, managedBytes: 0 }));
  eq([on.html().includes('data-t="node-cache-clear"'), on.html().includes('data-t="node-cache-off"'), on.html().includes('data-t="node-cache-on"'), on.html().includes("cache-budget")],
     [true, true, false, true], "on: Clear and Turn off stand by the setting");
  eq([old.html().includes("node-cache-clear"), old.html().includes("node-cache-off"), old.switches], [false, false, false], "negative: a scout that does not say `off` is offered neither");
  eq([empty.html().includes("node-cache-clear"), empty.html().includes("node-cache-off")], [false, true], "negative: nothing held, nothing to clear; the switch stays");
  eq([off.html().includes('data-t-state="off"'), off.html().includes('data-t="node-cache-on"'), off.html().includes(">/mnt/lib<"), off.html().includes("cache-budget"), off.html().includes("node-cache-off"), off.html().includes("node-cache-clear"), off.html().includes("node-cache-dir")],
     [true, true, true, false, false, false, false], "off: it says so and from where, offers Turn on; negative: no limit, no folder, no second switch");
  pin(on.fingerprint() !== off.fingerprint() && off.fingerprint() !== ModelCacheLine.of(node({ ...OFF, library: "/mnt/other" })).fingerprint(), "turning it off, and another library, draw the card anew");
  pin(on.fingerprint() !== empty.fingerprint(), "the Clear button comes and goes with what the cache holds");
  pin(ModelCacheLine.of(node(OFF)).fingerprint() !== ModelCacheLine.of(node(ON)).fingerprint() && old.fingerprint() === ModelCacheLine.of(node({ ...ON, off: undefined, managedBytes: 1 * GB })).fingerprint(), "negative: for a scout without the switch, the size held moves no redraw, as before");
  st.setTopology({ nodes: [node(ON)] });
  reset();
  globalThis.__fetchReply["/api/topology/client-llama/cache-clear"] = { ok: true, result: { ok: true, removed: 5, freedBytes: 95 * GB } };
  await ModelCacheLine.clear("h1", refresh);
  eq([asked[0].message.includes("95.0 GB"), asked[0].message.includes("Box"), asked[0].opts.title, asked[0].opts.confirmLabel], [true, true, "Clear the model cache?", "Clear"], "Clear asks first, naming how much goes and where");
  eq(sent(), [{ path: "/api/topology/client-llama/cache-clear", method: "POST", body: { hostId: "h1" } }], "yes: the machine is named");
  eq([spoken, refreshes.length], [["Freed 95.0 GB · files deleted: 5"], 1], "what went is said, and the card drawn anew");
  reset();
  answer = false;
  await ModelCacheLine.clear("h1", refresh);
  eq([sent(), refreshes.length], [[], 0], "negative: Cancel deletes nothing");
  reset();
  globalThis.__fetchReply["/api/topology/client-llama/cache-clear"] = { __status: 502, error: "h1 unreachable" };
  await ModelCacheLine.clear("h1", refresh);
  eq([spoken, refreshes.length], [["h1 unreachable"], 1], "negative: a refusal is said in its words");
  reset();
  typed = " /mnt/lib ";
  globalThis.__fetchReply["/api/topology/client-llama/cache-off"] = { ok: true, result: { ok: true, off: true, library: "/mnt/lib", removed: 5, freedBytes: 95 * GB } };
  await ModelCacheLine.turnOff("h1", refresh);
  eq([prompted[0].message, asked[0].opts.title, asked[0].opts.detail, asked[0].opts.confirmLabel, asked[0].message.includes("95.0 GB"), asked[0].message.includes("6 minutes")],
     ["Where does the library lie on Box? The full path of the folder on that machine:", "Turn off the model cache?", "/mnt/lib", "Turn off…", true, true],
     "Turn off asks where the library lies, then names what a start will cost and what goes");
  eq(sent(), [{ path: "/api/topology/client-llama/cache-off", method: "POST", body: { hostId: "h1", off: true, library: "/mnt/lib" } }], "yes: the machine, the switch and the library, trimmed");
  eq(spoken, ["The model cache of Box is off: models are read from /mnt/lib · Freed 95.0 GB · files deleted: 5"], "it says from where it reads now and what went");
  for (const [word, why] of [[null, "the question cancelled"], ["  ", "an empty path"]]) {
    reset();
    typed = word;
    await ModelCacheLine.turnOff("h1", refresh);
    eq([asked.length, sent().length, refreshes.length], [0, 0, 0], `negative: ${why} — no second question, nothing sent`);
  }
  reset();
  typed = "/mnt/lib";
  answer = false;
  await ModelCacheLine.turnOff("h1", refresh);
  eq([asked.length, sent().length], [1, 0], "negative: Cancel on the second question turns nothing off");
  reset();
  typed = "/mnt/lib";
  globalThis.__fetchReply["/api/topology/client-llama/cache-off"] = { __status: 502, error: "h1: library must be a folder on this machine" };
  await ModelCacheLine.turnOff("h1", refresh);
  eq([spoken, refreshes.length], [["h1: library must be a folder on this machine"], 1], "negative: a folder that is not there is said in the scout's words");
  st.setTopology({ nodes: [node(OFF)] });
  reset();
  typed = "";
  await ModelCacheLine.turnOff("h1", refresh);
  eq([prompted.length, asked[0].opts.detail, sent()[0].body.library], [0, "/mnt/lib", "/mnt/lib"], "the scout found the library, or was told it: where it lies is not asked, and the question names it");
  // Turn on asks first, with the cache's folder and its limit in the same window (the owner, 2026-11-03: "it turns on at once — show such a window").
  const OFF_BUDGET = { ...OFF, budgetBytes: 50 * GB };
  st.setTopology({ nodes: [node(OFF_BUDGET)] });
  reset();
  filled = { dir: "/home/u/cache", budget: "50" };
  globalThis.__fetchReply["/api/topology/client-llama/cache-off"] = { ok: true, result: { ok: true, off: false, removed: 0, freedBytes: 0 } };
  await ModelCacheLine.turnOn("h1", refresh);
  eq([fieldsAsked[0].opts.title, fieldsAsked[0].opts.confirmLabel, fieldsAsked[0].opts.danger, fieldsAsked[0].opts.fields.map((f) => [f.key, f.value, f.kind || "text"])],
     ["Turn the model cache on?", "Turn on", false, [["dir", "/home/u/cache", "text"], ["budget", 50, "number"]]],
     "Turn on asks first, not in red, with the folder and the limit the cache has now in its boxes");
  pin(fieldsAsked[0].message.startsWith("On Box, a model will be copied into this folder") && fieldsAsked[0].message.includes("Strata's folder is apart"),
      "the question says what turning on does, and that Strata's folder is not touched");
  eq([sent(), spoken, refreshes.length], [[{ path: "/api/topology/client-llama/cache-off", method: "POST", body: { hostId: "h1", off: false } }], ["The model cache of Box is on"], 1],
     "nothing changed in the boxes: only the switch is sent");
  reset();
  filled = { dir: "/mnt/ssd/cache", budget: "300" };
  await ModelCacheLine.turnOn("h1", refresh);
  eq(sent().map((c) => [c.path, c.body]), [["/api/topology/client-llama/cache-dir", { hostId: "h1", path: "/mnt/ssd/cache", how: "delete" }],
                                            ["/api/topology/client-llama/cache-budget", { hostId: "h1", budgetBytes: 300 * GB }],
                                            ["/api/topology/client-llama/cache-off", { hostId: "h1", off: false }]],
     "a new folder and a new limit go first, in that order, and then the switch");
  pin(choiceAsked.length === 0, "the old folder holds nothing (turning off deleted the copies): what becomes of its files is not asked");
  // A running cell's files outlive the turning off: the old folder still holds them, and they are asked about as "Change…" asks.
  st.setTopology({ nodes: [node({ ...OFF_BUDGET, managedBytes: 9 * GB })] });
  reset();
  filled = { dir: "/mnt/ssd/cache", budget: "50" };
  globalThis.__fetchReply["/api/topology/client-llama/cache-dir"] = { ok: true, result: { dir: "/mnt/ssd/cache", moving: true, totalBytes: 9 * GB } };
  await ModelCacheLine.turnOn("h1", refresh);
  eq([choiceAsked.length, choiceAsked[0]?.opts.detail, sent().map((c) => [c.path.split("/").pop(), c.body.how]), spoken],
     [1, "/home/u/cache → /mnt/ssd/cache", [["cache-dir", "move"], ["cache-off", undefined]], ["Moving 9.00 GB to /mnt/ssd/cache: the page shows how far it is"]],
     "what the old folder still holds is asked about — move or delete — and the answer goes with the folder; a move under way is said");
  reset();
  filled = { dir: "/mnt/ssd/cache", budget: "50" };
  chosen = null;
  await ModelCacheLine.turnOn("h1", refresh);
  pin(choiceAsked.length === 1 && sent().length === 0 && refreshes.length === 0, "negative: stepped back at that question — nothing is sent, the cache stays off");
  st.setTopology({ nodes: [node(OFF_BUDGET)] });
  reset();
  filled = { dir: "/home/u/cache", budget: "" };
  await ModelCacheLine.turnOn("h1", refresh);
  eq(sent().map((c) => c.body.budgetBytes !== undefined ? ["budget", c.body.budgetBytes] : [c.path.split("/").pop()]), [["budget", null], ["cache-off"]], "an emptied limit takes it off");
  for (const bad of ["0", "2.5", "x"]) {
    reset();
    filled = { dir: "/home/u/cache", budget: bad };
    await ModelCacheLine.turnOn("h1", refresh);
    pin(sent().length === 0 && spoken[0] === "The cache limit is a whole number of GB, 1 or more", `negative: a limit of ${bad} is said, and nothing is sent — the cache stays off`);
  }
  reset();
  filled = null;
  await ModelCacheLine.turnOn("h1", refresh);
  pin(fieldsAsked.length === 1 && sent().length === 0 && refreshes.length === 0, "negative: stepped back — nothing is sent");
  reset();
  filled = { dir: "/root/nope", budget: "50" };
  globalThis.__fetchReply["/api/topology/client-llama/cache-dir"] = { __status: 502, error: "h1: the cache cannot be in /root/nope: permission denied" };
  await ModelCacheLine.turnOn("h1", refresh);
  eq([sent().map((c) => c.path.split("/").pop()), spoken], [["cache-dir"], ["h1: the cache cannot be in /root/nope: permission denied"]],
     "negative: a folder the scout refuses stops it there, in the scout's words, and the cache is not turned on");
  st.setTopology({ nodes: [node({ keep: 2, managedBytes: 0, off: true, dir: "/c" })] });
  reset();
  filled = { dir: "/c" };
  await ModelCacheLine.turnOn("h1", refresh);
  pin(fieldsAsked[0].opts.fields.length === 1 && sent().length === 1, "a scout that keeps no budget is asked its folder alone");
  // Where the library lies, named with the cache on: nothing goes, so only that is asked.
  st.setTopology({ nodes: [node(ON)] });
  eq([on.html().includes('data-t="node-cache-library"'), on.html().includes('data-t="node-cache-dir"'), old.html().includes("node-cache-library"), off.html().includes(">/mnt/lib<"), off.html().includes('data-t="node-cache-dir"')],
     [false, true, false, true, false], "the cache on: its folder, and no word of the library, for a model comes through the controller; the cache off: where it reads, and no folder of copies; negative: a scout that cannot is not asked");
  // The long way is the default (the owner, 2026-11-02): a machine that can is asked nothing but the yes, and no folder goes along.
  const CAN = { ...ON, canThrough: true };
  const THROUGH = { ...CAN, managedBytes: 0, off: true, through: true };
  st.setTopology({ nodes: [node(CAN)] });
  reset();
  typed = "/never/asked";
  globalThis.__fetchReply["/api/topology/client-llama/cache-off"] = { ok: true, result: { ok: true, off: true, removed: 2, freedBytes: 95 * GB } };
  await ModelCacheLine.turnOff("h1", refresh);
  eq([prompted.length, asked.length, "detail" in asked[0].opts, sent(), asked[0].message.includes("no folder has to be mounted")],
     [0, 1, false, [{ path: "/api/topology/client-llama/cache-off", method: "POST", body: { hostId: "h1", off: true, library: "" } }], true],
     "no folder is asked, none is named in the question, and the question says none has to be mounted");
  eq(spoken[0].startsWith("The model cache of Box is off: models come from this controller"), true, "and the answer says where they come from now");
  reset();
  answer = false;
  await ModelCacheLine.turnOff("h1", refresh);
  eq([asked.length, sent().length], [1, 0], "negative: Cancel turns nothing off");
  const through = ModelCacheLine.of(node(THROUGH));
  const fromFolder = ModelCacheLine.of(node({ ...CAN, managedBytes: 0, off: true, through: false, library: "/mnt/lib" }));
  eq([through.html().includes(">the controller<"), through.html().includes('data-t-state="through"'), through.html().includes("Use a mounted folder"), through.html().includes("data-cache-through")],
     [true, true, true, false], "off, through the controller: it says so, and a mounted folder is an option");
  eq([fromFolder.html().includes(">/mnt/lib<"), fromFolder.html().includes('data-t-state="folder"'), fromFolder.html().includes("data-cache-through"), off.html().includes("data-cache-through")],
     [true, true, true, false], "off, from a folder: it names the folder and offers the way back; negative: a scout that cannot read through the controller is not offered it");
  pin(through.fingerprint() !== fromFolder.fingerprint() && ModelCacheLine.of(node(CAN)).fingerprint() !== on.fingerprint(), "the block is drawn again when the way changes or the machine learns it can");
  st.setTopology({ nodes: [node({ ...CAN, managedBytes: 0, off: true, through: false, library: "/mnt/lib" })] });
  reset();
  globalThis.__fetchReply["/api/topology/client-llama/cache-off"] = { ok: true, result: { ok: true, off: true, removed: 0, freedBytes: 0 } };
  await ModelCacheLine.useThrough("h1", refresh);
  eq([asked.length, sent(), spoken, refreshes.length],
     [0, [{ path: "/api/topology/client-llama/cache-off", method: "POST", body: { hostId: "h1", off: true, library: "" } }], ["The model cache of Box is off: models come from this controller"], 1], "back to the controller: nothing goes, so nothing is asked");
  st.setTopology({ nodes: [node(ON)] });
  reset();
  typed = " /mnt/lib ";
  globalThis.__fetchReply["/api/topology/client-llama/cache-off"] = { ok: true, result: { ok: true, off: false, library: "/mnt/lib" } };
  await ModelCacheLine.nameLibrary("h1", refresh);
  eq([asked.length, prompted[0].opts.confirmLabel, sent(), spoken, refreshes.length],
     [0, "Save", [{ path: "/api/topology/client-llama/cache-off", method: "POST", body: { hostId: "h1", off: false, library: "/mnt/lib" } }], ["The library of Box is at /mnt/lib"], 1],
     "the library named: no second question, the cache stays as it is, and it is said");
  for (const [word, why] of [[null, "cancelled"], ["  ", "empty"]]) {
    reset();
    typed = word;
    await ModelCacheLine.nameLibrary("h1", refresh);
    eq([sent().length, refreshes.length], [0, 0], `negative: ${why} — nothing sent`);
  }
  st.setTopology({ nodes: [node(OFF)] });
  reset();
  typed = "/mnt/lib";
  await ModelCacheLine.nameLibrary("h1", refresh);
  eq(sent().length, 0, "negative: the same folder — nothing sent");
  reset();
  typed = "/mnt/other";
  globalThis.__fetchReply["/api/topology/client-llama/cache-off"] = { ok: true, result: { ok: true, off: true, library: "/mnt/other" } };
  await ModelCacheLine.nameLibrary("h1", refresh);
  eq(sent()[0].body, { hostId: "h1", off: true, library: "/mnt/other" }, "with the cache off, another library leaves it off");
  const clicks = {};
  const button = (hook, id) => ({ dataset: { [hook]: id }, addEventListener: (_, fn) => { clicks[hook] = fn; } });
  ModelCacheLine.bind({ querySelectorAll: (sel) => ({ "[data-cache-clear]": [button("cacheClear", "h1")], "[data-cache-off]": [button("cacheOff", "h1")], "[data-cache-on]": [button("cacheOn", "h1")], "[data-cache-through]": [button("cacheThrough", "h1")], "[data-cache-library]": [button("cacheLibrary", "h1")] }[sel] || []) }, refresh);
  eq(Object.keys(clicks).sort(), ["cacheClear", "cacheLibrary", "cacheOff", "cacheOn", "cacheThrough"], "the five buttons are wired");
}

console.log(`js model-cache OK: ${pass.length} pins — for whom the line is drawn, the figures, the box, the foreign files, the redraw and the live patch, the two clicks, the wiring, the words`);
'''


def wiring():
    """The card, the redraw and the live patch go through the class: the group draws the line from it, the render binds it, fingerprints it and patches its
    figures — no handler, no fingerprint and no figure words of the board's own."""
    render = (ROOT / "static" / "js" / "topology-render.js").read_text(encoding="utf-8")
    nodes = (ROOT / "static" / "js" / "topology-nodes.js").read_text(encoding="utf-8")
    problems = []
    group = nodes[nodes.index("export function nodeCaravanGroupHtml"):]
    group = group[:group.index("\n}\n")]
    if group.count("ModelCacheLine.of(n).html()") != 1 or not re.search(r"\$\{strip\}\$\{ModelCacheLine\.of\(n\)\.html\(\)\}\$\{add\}", group):
        problems.append("nodeCaravanGroupHtml must draw the cache line once, between the strip and '+ Add model', from ModelCacheLine.of(n).html()")
    if len(re.findall(r'ModelCacheLine\.bind\(\$\("topologyLlamaServers"\), refreshTopology\)', render)) != 1:
        problems.append("topology-render.js must bind the cache line of #topologyLlamaServers through ModelCacheLine.bind, once, with refreshTopology")
    if "ModelCacheLine.of(n).fingerprint()" not in render:
        problems.append("the structure fingerprint's hosts part must carry ModelCacheLine.of(n).fingerprint(): a setting changed elsewhere would not redraw the card")
    if '_liveSet(nodeEl, "[data-live-cachefigures]", ModelCacheLine.of(n).figures())' not in render:
        problems.append("syncTopologyLive must patch what the cache holds and what the disk has left from ModelCacheLine.of(n).figures()")
    if len(re.findall(r"\$\{scoutOldChipHtml\(n\)\}\s*\$\{ModelCacheLine\.of\(n\)\.diskChipHtml\(\)\}", nodes)) != 2:
        problems.append("both heads of a machine (the main board's glance and the machine's own card) must draw ModelCacheLine.of(n).diskChipHtml() right after the scout-old chip, once each")
    if '_liveSet(nodeEl, "[data-live-diskpct]", ModelCacheLine.of(n).diskWords())' not in render:
        problems.append("syncTopologyLive must patch how full the disk is from ModelCacheLine.of(n).diskWords()")
    for name, text in (("topology-render.js", render), ("topology-nodes.js", nodes)):
        if "client-llama/cache-" in text or "data-cache-keep" in text or "modelCacheHeld" in text or "modelCacheFree" in text or "diskLowChip" in text or "node-disk-low" in text:
            problems.append(f"{name} has the cache line's route, hook or words of its own again — they are model-cache.js's")
    return problems


def main():
    problems = wiring()
    if problems:
        print("js model-cache FAILED (wiring):")
        for line in problems:
            print("  - " + line)
        raise SystemExit(1)
    print("  ok  the group draws the line from the class, the render binds, fingerprints and patches it, and no copy of it is left in the board")
    node = find_node()
    if not node:
        raise SystemExit("node required")
    probe = ROOT / "scripts" / ".probe_model_cache.tmp.mjs"
    probe.write_text(PROBE)
    try:
        harness = ROOT / "scripts" / "_js_harness.mjs"
        result = subprocess.run(probe_args(node, harness, probe), cwd=ROOT,
                                env={**os.environ, "JS_ROOT": str(ROOT / "static/js"), "JS_STUBS": "i18n,dialogs", "LANGS": json.dumps(LANGS), "KEYS": json.dumps(KEYS),
                                     "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8", "TZ": "UTC"},
                                capture_output=True, text=True, timeout=90)
        print(result.stdout, end="")
        print(result.stderr, end="", file=sys.stderr)
    finally:
        probe.unlink(missing_ok=True)
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
