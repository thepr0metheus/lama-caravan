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
from _node import find_node  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LANGS = sorted(p.stem for p in (ROOT / "static" / "js" / "i18n").glob("*.js"))
KEYS = ["modelCacheHead", "modelCacheKeepLabel", "modelCacheKeepHelp", "modelCacheHeld", "modelCacheFree", "modelCacheForeign",
        "modelCacheForeignHelp", "modelCacheDeleteBtn", "modelCacheDeleteTitle", "modelCacheDeleteConfirm", "modelCacheKept",
        "modelCacheFreed", "modelCacheNothingYet", "diskLowChip", "diskLowTitle"]

PROBE = r'''
import "./_js_globals.mjs";
import assert from "node:assert/strict";
const en = (await import("../static/js/i18n/en.js")).default;
const asked = [], toasts = [], refreshes = [];
let answer = true, confirmHook = null;
globalThis.__stubReturns = {
  "i18n.t": (key, vars = {}) => String(en[key] ?? `?${key}`).replace(/\{(\w+)\}/g, (_, name) => (vars[name] === undefined ? `{${name}}` : vars[name])),
  "dialogs.appConfirm": async (message, opts) => { asked.push({ message, opts }); if (confirmHook) confirmHook(); return answer; },
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
const reset = () => { asked.length = 0; toasts.length = 0; refreshes.length = 0; spoken.length = 0; answer = true; confirmHook = null; globalThis.__fetchCalls.length = 0; globalThis.__fetchReply = {}; };
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
  const asks = [];
  const root = { querySelectorAll(selector) { asks.push(selector); return selector === "[data-cache-keep]" ? boxes : selector === "[data-cache-delete-foreign]" ? buttons : []; } };
  ModelCacheLine.bind(root, refresh);
  pin(asks.join(",") === "[data-cache-keep],[data-cache-delete-foreign]" && boxes.every((b) => typeof b.handlers.change === "function")
      && buttons.every((b) => typeof b.handlers.click === "function"),
      "every box and every button under the card's container gets its handler, found by its data attribute");
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
                 diskLowChip: "pct", diskLowTitle: "limit" };
  const lacking = [], wrong = [], same = [];
  for (const lang of langs) {
    const m = (await import(`../static/js/i18n/${lang}.js`)).default;
    for (const key of keys) {
      if (!m[key]) { lacking.push(`${lang}.${key}`); continue; }
      if (lang !== "en" && m[key] === en[key] && !["modelCacheDeleteBtn", "modelCacheHead"].includes(key)) same.push(`${lang}.${key}`);
      if (key in want && holes(m[key]) !== want[key]) wrong.push(`${lang}.${key}: ${holes(m[key])}`);
    }
  }
  eq(lacking, [], "all 15 keys of the line and its sign exist in all 20 languages");
  eq(wrong, [], "every language fills the holes the code fills — host, number, size, free, total — and no other");
  eq(same, [], "no language is left with the English text");
  eq(Object.entries(want).filter(([key, h]) => holes(en[key]) !== h).map(([key]) => key), [], "and the English words have exactly those holes");
}

for (const why of pass) console.log("  ok  " + why);
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
        result = subprocess.run([node, "--import", f"data:text/javascript,import {{ register }} from 'node:module'; register('{harness.as_uri()}');", str(probe)], cwd=ROOT,
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
