#!/usr/bin/env python3
"""Actual model-disk.js and the folder actions of model-cache.js: the model disk on a machine's own page (2026-11-03).

The owner, 2026-11-03, looking at the old line on the machine's page: "make it prettier"; and: a folder for Strata's files of its own, always there and
red until one is chosen — no Strata start until then, with a hint where to choose it — and every folder either moved with its files, moved with them
deleted, or removed (its files deleted, the cache back in its own folder, Strata's row red again).

Later that day: Strata's models stay in its folder up to a limit he changes there (300 GB unless he says); the row says to choose a fast disk and what Strata
writes to it, warns when the disk spins and when it has less room than the limit leaves.

Pinned, by value: for whom the block is drawn; the head (on or off, Clear only while the cache holds something, the switch); the disk as a bar, and no bar
for a disk nobody measured; each folder's row — its path whole, Change…, ✕ only where the operator chose the folder; Strata's row red with its words
while none is chosen, and absent for a scout that keeps no such folder; its limit's box, its models with their names, its hints and warnings, each only
when the scout said what it rests on; a move under way and the words of one that failed; the live patch of the bar, of a move's progress and of what
Strata's folder holds; the clicks — what is asked, what is sent, what is said; the words in all six languages.

The modules are loaded FOR REAL, with utils.js, state.js and ui-parts.js; i18n (English words, filled as the board fills them) and the dialogs are
stand-ins; the network and the toast are the harness's.

Run: python3 scripts/test_js_model_disk.py
"""
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _node import find_node, probe_args  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LANGS = sorted(p.stem for p in (ROOT / "static" / "js" / "i18n").glob("*.js"))
KEYS = ["modelDiskOnWord", "modelDiskDisk", "modelDiskOthers", "modelDiskCacheShare", "modelDiskWorkLabel", "modelDiskWorkHelp", "modelDiskWorkUnset",
        "modelDiskWorkChoose", "modelDiskWorkPrompt", "modelDiskWorkTitle", "modelDiskWorkSet", "modelDiskWorkRemoveHelp", "modelDiskWorkRemoveTitle",
        "modelDiskWorkRemoveConfirm", "modelDiskWorkRemoved", "modelDiskCacheRemoveHelp", "modelDiskCacheRemoveTitle", "modelDiskCacheRemoveConfirm",
        "modelDiskRemove", "modelDiskCarryQuestion", "modelDiskCarryWhat", "modelDiskCarryMove", "modelDiskCarryDelete", "modelDiskMoveStarted",
        "modelDiskMoving", "modelDiskWhatCache", "modelDiskWhatWork", "modelDiskMoveFailed", "modelDiskWorkFast", "modelDiskWorkHdd", "modelDiskWorkWear",
        "modelDiskWorkShort", "modelDiskWorkModels", "modelDiskWorkNoModels", "modelDiskWorkLimit", "modelDiskWorkLimitHelp", "modelDiskWorkLimitBad",
        "modelDiskWorkLimitSet", "modelDiskWorkApart"]

PROBE = r'''
import "./_js_globals.mjs";
import assert from "node:assert/strict";
const en = (await import("../static/js/i18n/en.js")).default;
const asked = [], prompted = [], choiceAsked = [], refreshes = [];
let answer = true, typed = null, chosen = "move";
globalThis.__stubReturns = {
  "i18n.t": (key, vars = {}) => String(en[key] ?? `?${key}`).replace(/\{(\w+)\}/g, (_, name) => (vars[name] === undefined ? `{${name}}` : vars[name])),
  "dialogs.appConfirm": async (message, opts) => { asked.push({ message, opts }); return answer; },
  "dialogs.appPrompt": async (message, opts) => { prompted.push({ message, opts }); return typed; },
  "dialogs.appConfirmChoice": async (message, opts) => { choiceAsked.push({ message, opts }); return chosen; },
};
const toastEl = { textContent: "", classList: { add() {}, remove() {} } };
globalThis.__fields = { toast: toastEl };
const spoken = [];
Object.defineProperty(toastEl, "textContent", { get() { return spoken.at(-1) ?? ""; }, set(v) { spoken.push(v); } });
const st = await import("../static/js/state.js");
const { ModelCacheLine } = await import("../static/js/model-cache.js");
const { ModelDisk } = await import("../static/js/model-disk.js");
const pass = [];
const pin = (cond, why) => { assert.ok(cond, why); pass.push(why); };
const eq = (got, want, why) => { assert.deepEqual(got, want, why + ` (got ${JSON.stringify(got)})`); pass.push(why); };
const GB = 2 ** 30;
const FACTS = { keep: 1, budgetBytes: 2 * GB, managedBytes: 100 * GB, dir: "/home/u/llama-model-cache", dirChosen: false, dirOwn: "/home/u/llama-model-cache",
                off: false, through: false, canThrough: true, disk: { totalBytes: 1000 * GB, freeBytes: 400 * GB },
                work: { dir: "/home/u/llama-model-cache", chosen: false, bytes: 0 } };
const node = (facts, id = "h1") => ({ id, name: "Box", modelCache: facts });
const draw = (facts) => ModelDisk.of(node(facts)).html();
const reset = () => { asked.length = 0; prompted.length = 0; choiceAsked.length = 0; refreshes.length = 0; spoken.length = 0; answer = true; typed = null; chosen = "move";
                      globalThis.__fetchCalls.length = 0; globalThis.__fetchReply = {}; };
const refresh = async () => { refreshes.push(1); };
const sent = () => globalThis.__fetchCalls.map((c) => ({ path: c.path, body: JSON.parse(c.body) }));
const row = (html, name) => { const m = html.match(new RegExp(`<div class="mdisk-row[^"]*" data-t="${name}"[^>]*>`)); return m ? m[0] : ""; };

// ── for whom it is drawn ──
{
  pin(draw(FACTS).includes('data-t="node-cache" data-t-id="h1" data-t-state="on"'), "a scout that reports its cache gets the block, on");
  eq([undefined, null, {}, { keep: 0 }].map((facts) => draw(facts)), ["", "", "", ""], "negative: a scout that says nothing of its cache gets no block — never one with a made-up setting");
}

// ── the head ──
{
  const html = draw(FACTS);
  pin(html.includes(">Model cache</span>") && html.includes('class="ui-badge ui-badge--good">On</span>'), "the head says the cache and that it is on");
  pin(html.includes('data-cache-clear="h1"') && html.includes('data-cache-off="h1"') && !html.includes('data-cache-on="h1"'), "on, holding something: Clear and Turn off");
  pin(!draw({ ...FACTS, managedBytes: 0 }).includes("data-cache-clear"), "negative: nothing held, nothing to clear: no Clear");
  const off = draw({ ...FACTS, off: true, through: true });
  pin(off.includes('data-t-state="off"') && off.includes('class="ui-badge">Off</span>') && off.includes('data-cache-on="h1"') && !off.includes("data-cache-off="),
      "off: the badge says so, and the one button is Turn on");
  pin(!draw({ ...FACTS, off: undefined }).includes("ui-badge"), "negative: a scout that cannot switch its cache gets no state and no switch");
}

// ── the disk as a bar ──
{
  const disk = ModelDisk.of(node(FACTS));
  eq(disk.meterParts(), { total: 1000 * GB, parts: [{ value: 500 * GB, kind: "other", title: "other files on this disk" }, { value: 100 * GB, series: 1, title: "the model cache" }] },
     "the bar: the disk's other files hatched, the cache in its colour, of the disk's size");
  pin(draw(FACTS).includes('data-live-diskbar') && draw(FACTS).includes('style="width: 50%"') && draw(FACTS).includes('style="width: 10%"'), "the bar is drawn in its shares");
  eq(ModelDisk.of(node({ ...FACTS, managedBytes: null })).meterParts().parts.map((p) => p.value), [600 * GB], "negative: the cache not measured — all the used space is other files, no share made up");
  pin(!draw({ ...FACTS, disk: null }).includes("data-live-diskbar"), "negative: a disk nobody measured has no bar — an empty one would read as a free disk");
  pin(draw(FACTS).includes('data-live-cachefigures>holds 100 GB · 400 GB free of 1000 GB</div>'), "the figures stand under the bar, patched in place");
}

// ── the cache's folder ──
{
  const html = draw(FACTS);
  pin(row(html, "node-cache-dir") && html.includes('<code class="mdisk-path" dir="ltr">/home/u/llama-model-cache</code>'), "the folder's path is written whole, left to right");
  pin(html.includes('data-t="node-cache-dir-change" data-t-id="h1" data-cache-dir="h1"'), "Change… is found by the hook the card's line has");
  pin(!html.includes("data-cache-dir-remove"), "negative: a folder nobody chose cannot be removed — there is nothing to go back to");
  const chosen = draw({ ...FACTS, dir: "/mnt/hdd/cache", dirChosen: true });
  pin(chosen.includes('data-t="node-cache-dir-remove" data-t-id="h1" data-cache-dir-remove="h1"') && chosen.includes('title="Back to /home/u/llama-model-cache: what Caravan downloaded into this folder is deleted"'),
      "a chosen folder has its ✕, and its tip names where the cache goes back to and what goes");
  pin(draw({ ...FACTS, budgetBytes: 2 * GB }).includes('data-cache-budget="h1"') && draw({ keep: 3, managedBytes: 0 }).includes('data-cache-keep="h1"'),
      "the rule: the budget's box where the scout keeps one, the box of the last N where it does not");
  const off = draw({ ...FACTS, off: true, through: true });
  pin(!off.includes("data-cache-budget") && !row(off, "node-cache-dir") && off.includes('data-t="node-cache-library" data-t-id="h1" data-t-state="through"'),
      "off: no rule and no folder for copies, and where the models are read from");
  pin(draw({ ...FACTS, off: true, through: false, library: "/mnt/lib" }).includes('<code class="mdisk-path" dir="ltr">/mnt/lib</code>'), "off, from a mounted folder: its path");
}

// ── Strata's folder ──
{
  const unset = draw(FACTS);
  pin(row(unset, "node-cache-work").includes("mdisk-row--bad") && row(unset, "node-cache-work").includes('data-t-state="unset"')
      && unset.includes("Not chosen: Strata does not start until a folder is chosen") && unset.includes('data-cache-work="h1"') && unset.includes(">Choose…</button>"),
      "none chosen: the row is red, says Strata does not start, and offers Choose…");
  pin(!unset.includes("data-cache-work-remove"), "negative: nothing chosen, nothing to remove");
  pin(unset.includes('data-t="node-cache-work-fast" data-t-id="h1">Choose a folder on an SSD: while it answers, Strata reads its model here at random, and on an HDD it stalls.</span>'),
      "none chosen: the moment of choosing says what to choose — a fast disk");
  const set = draw({ ...FACTS, work: { dir: "/mnt/hdd/strata", chosen: true, bytes: 2.3 * GB } });
  pin(!row(set, "node-cache-work").includes("mdisk-row--bad") && row(set, "node-cache-work").includes('data-t-state="chosen"')
      && set.includes("Strata files · <span data-live-workbytes>2.30 GB</span>") && set.includes('<code class="mdisk-path" dir="ltr">/mnt/hdd/strata</code>')
      && set.includes('data-cache-work-remove="h1"'), "chosen: its path whole, what lies there, Change… and ✕");
  pin(!draw({ ...FACTS, work: { dir: "/mnt/hdd/strata", chosen: true, bytes: 0 } }).includes("Strata files · "), "negative: nothing made there yet: no size after the name");
  pin(set.includes('data-t="node-cache-work-wear" data-t-id="h1">Writes to this disk: a model once, when a Strata cell first starts with it;'),
      "chosen: what Strata writes to the disk is said under it");
  pin(set.includes('data-t="node-cache-work-apart" data-t-id="h1">Apart from the model cache: its Turn off and Clear do not touch this folder.</span>'),
      "chosen: the card says in words that the cache's switch and Clear do not reach it");
  pin(!unset.includes("node-cache-work-apart"), "negative: none chosen, nothing there to be touched or not");
  pin(!set.includes("data-cache-work-budget") && !set.includes("node-cache-work-hdd") && set.includes("node-cache-work-fast"),
      "negative: a scout that keeps no limit gets no box; one that does not say the disk's kind gets the hint, not a warning");
  const full = { dir: "/ssd/strata", chosen: true, bytes: 72 * GB, modelsBytes: 70 * GB, madeBytes: 2 * GB, budgetBytes: 300 * GB, budgetChosen: false,
                 disk: { totalBytes: 1000 * GB, freeBytes: 500 * GB }, rotational: false,
                 models: [{ name: "q/q-00001-of-00002.gguf", bytes: 60 * GB }, { name: "mtp-q2_0.gguf", bytes: 10 * GB }] };
  const ssd = draw({ ...FACTS, work: full });
  pin(ssd.includes('<input type="number" class="cache-budget" min="1" step="1" inputmode="numeric" value="300"') && ssd.includes('data-cache-work-budget="h1"'),
      "the limit's box holds the folder's 300 GB");
  pin(ssd.includes('title="q/q-00001-of-00002.gguf · 60.0 GB\nmtp-q2_0.gguf · 10.0 GB" data-live-workmodels>Models 70.0 GB</span>'),
      "what its models take, with their names in the tip");
  pin(!ssd.includes("node-cache-work-fast") && !ssd.includes("node-cache-work-hdd") && !ssd.includes("node-cache-work-short"),
      "negative: an SSD with room: no hint of a disk, no warning");
  const hdd = draw({ ...FACTS, work: { ...full, rotational: true } });
  pin(hdd.includes('data-t="node-cache-work-hdd" data-t-id="h1">⚠ This folder is on an HDD: Strata stalls here. Move it to a folder on an SSD.</span>') && !hdd.includes("node-cache-work-fast"),
      "a disk that spins is said in red, and why");
  const tight = draw({ ...FACTS, work: { ...full, disk: { totalBytes: 1000 * GB, freeBytes: 100 * GB } } });
  pin(tight.includes("⚠ The disk has 100 GB free — less than the 230 GB the limit still leaves for models: a bigger model will not fit."),
      "a disk with less room than the limit leaves is said before a start meets it");
  pin(!draw({ ...FACTS, work: { ...full, disk: null } }).includes("node-cache-work-short") && !draw({ ...FACTS, work: { ...full, modelsBytes: undefined } }).includes("node-cache-work-short"),
      "negative: a disk or models nobody measured warn of nothing");
  pin(draw({ ...FACTS, work: { ...full, models: [] } }).includes('title="No models yet: they come with the first Strata start"'), "no models yet: the tip says when they come");
  const fp = (work) => ModelCacheLine.of(node({ ...FACTS, work })).fingerprint();
  pin(fp(full) === fp({ ...full, bytes: 80 * GB, modelsBytes: 78 * GB, disk: { totalBytes: 1000 * GB, freeBytes: 420 * GB } }),
      "what the folder holds moves with a copy, and never redraws the page");
  pin(fp(full) !== fp({ ...full, budgetBytes: 200 * GB }) && fp(full) !== fp({ ...full, rotational: true }) && fp(full) !== fp({ ...full, models: [] })
      && fp(full) !== fp({ ...full, disk: { totalBytes: 1000 * GB, freeBytes: 100 * GB } }),
      "its limit, its disk's kind, its models' names and a disk too short for the limit redraw it");
  for (const [work, why] of [[undefined, "the scout keeps no such folder"], [{ dir: "relative", chosen: true }, "a path that is no path"], [{ dir: "/x" }, "chosen or not, unsaid"]]) {
    pin(!draw({ ...FACTS, work }).includes("node-cache-work"), `negative: no row when ${why}`);
  }
  pin(draw({ ...FACTS, off: true, through: true }).includes('data-t="node-cache-work"'), "the row stands with the cache off too: Strata writes its files either way");
  // A card of its own, not a row under the cache's switch (the owner, 2026-11-03: the cache's Turn off must not touch Strata).
  const apart = draw({ ...FACTS, work: { dir: "/ssd/strata", chosen: true, bytes: 0 } });
  const cacheCard = apart.slice(apart.indexOf('data-t="node-cache" '), apart.indexOf('data-t="node-strata"'));
  pin(apart.indexOf('data-t="node-strata"') > apart.indexOf('data-t="node-cache" ') && !cacheCard.includes("node-cache-work")
      && apart.slice(apart.indexOf('data-t="node-strata"')).includes('data-t="node-cache-work"') && apart.startsWith('<div class="mdisk-stack">'),
      "Strata's folder is a card of its own after the cache's: no row of it under the cache's switch");
  pin(unset.includes('class="mdisk mdisk--work mdisk--bad" data-t="node-strata"') && !apart.includes("mdisk--bad"), "none chosen, the card is red; chosen, it is not");
  const movingWork = draw({ ...FACTS, work: { dir: "/ssd/strata", chosen: true, bytes: 0 }, moving: { what: "work", to: "/ssd/b", doneBytes: 1, totalBytes: 2 } });
  const movingCache = draw({ ...FACTS, work: { dir: "/ssd/strata", chosen: true, bytes: 0 }, moving: { what: "cache", to: "/hdd/c", doneBytes: 1, totalBytes: 2 } });
  pin(movingWork.slice(movingWork.indexOf('data-t="node-strata"')).includes("node-cache-moving")
      && !movingCache.slice(movingCache.indexOf('data-t="node-strata"')).includes("node-cache-moving"),
      "a move stands in the card of the folder that moves");
}

// ── a move under way, and one that failed ──
{
  const moving = { what: "cache", to: "/mnt/hdd/cache", doneBytes: 3 * GB, totalBytes: 12 * GB };
  const html = draw({ ...FACTS, moving });
  pin(html.includes('data-t="node-cache-moving" data-t-id="h1" data-t-state="cache"') && html.includes("Moving the model cache to /mnt/hdd/cache: 3.00 GB of 12.0 GB")
      && html.includes('data-live-moveshare style="width: 25%"'), "a move says what moves where and how far, with its bar");
  pin(!draw(FACTS).includes("node-cache-moving") && !draw({ ...FACTS, moving: { what: "else", to: "/x", doneBytes: 1, totalBytes: 2 } }).includes("node-cache-moving"),
      "negative: no move, or one the board cannot read, draws nothing");
  pin(draw({ ...FACTS, moveError: "x/two.bin: no space" }).includes("The last move did not happen: x/two.bin: no space. The old folder stays as it was."), "the words of a move that failed stay until the next");
  pin(!draw({ ...FACTS, moveError: "" }).includes("node-cache-move-error"), "negative: no words, no line");
  const fp = (facts) => ModelCacheLine.of(node(facts)).fingerprint();
  pin(fp({ ...FACTS, moving }) === fp({ ...FACTS, moving: { ...moving, doneBytes: 9 * GB } }) && fp({ ...FACTS, moving }) !== fp(FACTS),
      "how far a move is never redraws the page; a move starting or ending does");
}

// ── the live patch ──
{
  const seg = () => ({ style: { width: "" } });
  const disk = [seg(), seg()], share = seg(), words = { textContent: "" };
  const bar = { querySelectorAll: () => disk };
  const el = { querySelector: (sel) => ({ "[data-live-diskbar]": bar, "[data-live-movewords]": words, "[data-live-moveshare]": share })[sel] || null };
  ModelDisk.patch(el, node({ ...FACTS, managedBytes: 200 * GB, moving: { what: "work", to: "/mnt/x", doneBytes: 1 * GB, totalBytes: 4 * GB } }));
  eq([disk[0].style.width, disk[1].style.width, share.style.width, words.textContent], ["40%", "20%", "25%", "Moving Strata's files to /mnt/x: 1.00 GB of 4.00 GB"],
     "the bar's shares, a move's share and its words are written in place");
  const one = [seg()];
  ModelDisk.patch({ querySelector: (sel) => (sel === "[data-live-diskbar]" ? { querySelectorAll: () => one } : null) }, node(FACTS));
  eq(one[0].style.width, "", "negative: a bar whose parts came or went is not patched — the fingerprint draws it again");
  ModelDisk.patch(null, node(FACTS));
  pass.push("negative: no element, no patch, no throw");
  const held = { textContent: "2.00 GB" }, models = { textContent: "Models 1.00 GB" };
  const work = { querySelector: (sel) => ({ "[data-live-workbytes]": held, "[data-live-workmodels]": models })[sel] || null };
  ModelDisk.patch(work, node({ ...FACTS, work: { dir: "/ssd/strata", chosen: true, bytes: 40 * GB, modelsBytes: 38 * GB } }));
  eq([held.textContent, models.textContent], ["40.0 GB", "Models 38.0 GB"], "what Strata's folder holds is written in place as a copy grows");
  ModelDisk.patch(work, node({ ...FACTS, work: { dir: "/ssd/strata", chosen: true } }));
  eq([held.textContent, models.textContent], ["40.0 GB", "Models 38.0 GB"], "negative: figures not said leave the last ones, never an empty or a zero");
}

// ── the clicks ──
{
  const DIR = "/api/topology/client-llama/cache-dir", WORK = "/api/topology/client-llama/cache-work";
  const chosenCache = { ...FACTS, dir: "/mnt/hdd/cache", dirChosen: true, managedBytes: 30 * GB };
  st.setTopology({ nodes: [node(chosenCache)] });
  reset();
  globalThis.__fetchReply[DIR] = { ok: true, result: { ok: true, dir: "/home/u/llama-model-cache", removed: 4, freedBytes: 30 * GB } };
  await ModelCacheLine.removeFolder("h1", refresh);
  eq([asked[0].message, asked[0].opts.title, asked[0].opts.confirmLabel],
     ["On Box, the model cache goes back to /home/u/llama-model-cache, and what Caravan downloaded into /mnt/hdd/cache (30.0 GB) is deleted. The library keeps the models: a cell brings its model again when it starts.",
      "Remove this folder of the model cache?", "Remove"], "✕ asks first, naming where the cache goes back to and what goes");
  eq(sent(), [{ path: DIR, body: { hostId: "h1", path: "", how: "delete" } }], "yes: the folder is removed, its files deleted");
  eq(spoken, ["The model cache of Box is in /home/u/llama-model-cache now · Freed 30.0 GB · files deleted: 4"], "and the operator is told");
  reset();
  answer = false;
  await ModelCacheLine.removeFolder("h1", refresh);
  pin(asked.length === 1 && sent().length === 0, "negative: no — nothing goes");
  reset();
  st.setTopology({ nodes: [node(FACTS)] });
  await ModelCacheLine.removeFolder("h1", refresh);
  pin(asked.length === 0 && sent().length === 0, "negative: a folder nobody chose is not removed, and nothing is asked");

  reset();
  typed = " /mnt/hdd/strata ";
  globalThis.__fetchReply[WORK] = { ok: true, result: { ok: true, dir: "/mnt/hdd/strata", chosen: true, removed: 0, freedBytes: 0 } };
  await ModelCacheLine.chooseWork("h1", refresh);
  eq([prompted[0].message, prompted[0].opts.value, prompted[0].opts.placeholder],
     ["Folder for Strata's files on Box — the full path on that machine. Choose a fast disk (SSD): Strata stalls on an HDD.", "", "/mnt/hdd/caravan/strata"],
     "Choose… asks the folder, empty while none is chosen, and says what disk to choose");
  pin(choiceAsked.length === 0, "nothing made yet: nothing to carry, and no choice asked");
  eq(sent(), [{ path: WORK, body: { hostId: "h1", path: "/mnt/hdd/strata", how: "delete" } }], "the folder goes to the controller, trimmed");
  eq(spoken, ["Strata's files on Box go to /mnt/hdd/strata"], "and the operator is told where they go — and nothing of a deletion that did not happen");

  const setWork = { ...FACTS, work: { dir: "/mnt/hdd/strata", chosen: true, bytes: 2 * GB } };
  st.setTopology({ nodes: [node(setWork)] });
  reset();
  typed = "/mnt/wd/strata";
  globalThis.__fetchReply[WORK] = { ok: true, result: { ok: true, moving: true, dir: "/mnt/wd/strata", totalBytes: 2 * GB, files: 3 } };
  await ModelCacheLine.chooseWork("h1", refresh);
  eq([prompted[0].opts.value, choiceAsked[0].message, choiceAsked[0].opts.title, choiceAsked[0].opts.detail],
     ["/mnt/hdd/strata", "The old folder holds 2.00 GB of Caravan's files. Move them to the new folder, or delete them?", "Move Strata's files?", "/mnt/hdd/strata → /mnt/wd/strata"],
     "Change…: the present folder in the box, then whether the files go with it");
  eq(sent()[0].body, { hostId: "h1", path: "/mnt/wd/strata", how: "move" }, "moving them is sent");
  eq(spoken, ["Moving 2.00 GB to /mnt/wd/strata: the page shows how far it is"], "a move under way is said as one");
  reset();
  typed = "/mnt/hdd/strata";
  await ModelCacheLine.chooseWork("h1", refresh);
  pin(sent().length === 0 && choiceAsked.length === 0, "negative: the folder it is in — nothing asked, nothing sent");

  reset();
  globalThis.__fetchReply[WORK] = { ok: true, result: { ok: true, dir: "/home/u/llama-model-cache", chosen: false, removed: 3, freedBytes: 2 * GB } };
  await ModelCacheLine.removeWork("h1", refresh);
  eq(asked[0].message, "On Box, Strata's models and what the cells made in /mnt/hdd/strata (2.00 GB) are deleted, and Strata does not start until a folder is chosen again. The folder itself and anything else in it stay.",
     "✕ by Strata's folder asks first, naming what goes — its models too — and that Strata stops starting");
  eq(sent(), [{ path: WORK, body: { hostId: "h1", path: "", how: "delete" } }], "yes: the folder is removed");
  eq(spoken, ["Box has no folder for Strata's files: Strata does not start until one is chosen · Freed 2.00 GB · files deleted: 3"], "and the operator is told Strata waits");
  reset();
  st.setTopology({ nodes: [node(FACTS)] });
  await ModelCacheLine.removeWork("h1", refresh);
  pin(asked.length === 0 && sent().length === 0, "negative: nothing chosen, nothing to remove");
  reset();
  typed = "/mnt/hdd/strata";
  globalThis.__fetchReply[WORK] = { __status: 502, error: "h1: the work folder does not move while a cell keeps its files there: :22009 — stop it first" };
  await ModelCacheLine.chooseWork("h1", refresh);
  pin(spoken.length === 1 && spoken[0].includes(":22009 — stop it first") && refreshes.length === 1, "negative: the scout refuses — its words, the cell named, are said");

  const LIMIT = "/api/topology/client-llama/cache-work-budget";
  st.setTopology({ nodes: [node({ ...FACTS, work: { dir: "/ssd/strata", chosen: true, bytes: 0, budgetBytes: 300 * GB } })] });
  const box = (value) => ({ value, disabled: false, dataset: { cacheWorkBudget: "h1" }, blur() {} });
  reset();
  globalThis.__fetchReply[LIMIT] = { ok: true, result: { ok: true, budgetBytes: 500 * GB, removed: 0, freedBytes: 0, waiting: false } };
  await ModelCacheLine.setWorkBudget(box(" 500 "), refresh);
  eq(sent(), [{ path: LIMIT, body: { hostId: "h1", budgetBytes: 500 * GB } }], "the limit in GB goes to the controller in bytes");
  eq(spoken, ["Strata's models on Box may take up to 500 GB"], "and the operator is told");
  reset();
  globalThis.__fetchReply[LIMIT] = { ok: true, result: { ok: true, budgetBytes: 300 * GB, removed: 2, freedBytes: 70 * GB, waiting: false } };
  await ModelCacheLine.setWorkBudget(box(""), refresh);
  eq(sent()[0].body, { hostId: "h1", budgetBytes: null }, "an empty box gives the folder its own limit back");
  eq(spoken, ["Strata's models on Box may take up to 300 GB · Freed 70.0 GB · files deleted: 2"], "what a lower limit deleted is said");
  for (const bad of ["0", "2.5", "x"]) {
    reset();
    const b = box(bad);
    await ModelCacheLine.setWorkBudget(b, refresh);
    pin(sent().length === 0 && spoken[0] === "Strata's limit is a whole number of GB, 1 or more" && b.value === "300", `negative: ${bad} is no limit — said, nothing sent, the box back to 300`);
  }
  reset();
  globalThis.__fetchReply[LIMIT] = { __status: 502, error: "h1: budgetBytes must be a whole number of bytes" };
  const refused = box("9");
  await ModelCacheLine.setWorkBudget(refused, refresh);
  pin(spoken[0].includes("budgetBytes must be") && refused.value === "300" && refreshes.length === 1, "negative: the scout refuses — its words, the box back");
}

// ── the wiring ──
{
  const fs = await import("node:fs");
  const nodes = fs.readFileSync(new URL("../static/js/topology-nodes.js", import.meta.url), "utf8");
  const render = fs.readFileSync(new URL("../static/js/topology-render.js", import.meta.url), "utf8");
  pin(/disk: ModelDisk\.of\(n\)\.html\(\)/.test(nodes) && !/disk: ModelCacheLine\.of\(n\)\.html\(\)/.test(nodes), "the machine's page draws the block; the board's card keeps its line");
  pin(/ModelDisk\.patch\(nodeEl, n\)/.test(render), "the render's live patch writes the bar and a move's progress");
}

// ── the words ──
{
  const langs = JSON.parse(process.env.LANGS), keys = JSON.parse(process.env.KEYS);
  const holes = (s) => [...String(s).matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort().join(",");
  const want = { modelDiskWorkPrompt: "host", modelDiskWorkSet: "dir,host", modelDiskWorkRemoveConfirm: "folder,host,size", modelDiskWorkRemoved: "host",
                 modelDiskWorkShort: "free,room", modelDiskWorkModels: "size", modelDiskWorkLimitSet: "host,size", modelDiskWorkFast: "", modelDiskWorkHdd: "", modelDiskWorkWear: "",
                 modelDiskCacheRemoveHelp: "dir", modelDiskCacheRemoveConfirm: "dir,folder,host,size", modelDiskCarryQuestion: "size", modelDiskMoveStarted: "dir,size",
                 modelDiskMoving: "done,to,total,what", modelDiskMoveFailed: "words" };
  const lacking = [], wrong = [], same = [];
  for (const lang of langs) {
    const m = (await import(`../static/js/i18n/${lang}.js`)).default;
    for (const key of keys) {
      if (!m[key]) { lacking.push(`${lang}.${key}`); continue; }
      if (lang !== "en" && m[key] === en[key]) same.push(`${lang}.${key}`);
      if (key in want && holes(m[key]) !== want[key]) wrong.push(`${lang}.${key}: ${holes(m[key])}`);
    }
  }
  eq(lacking, [], `all ${keys.length} words exist in all ${langs.length} languages`);
  eq(wrong, [], "every language fills the holes the code fills, and no other");
  eq(same, [], "no language is left with the English text");
  eq(Object.entries(want).filter(([key, h]) => holes(en[key]) !== h).map(([key]) => key), [], "and the English words have exactly those holes");
}

for (const why of pass) console.log("  ok  " + why);
console.log(`js model-disk OK: ${pass.length} pins`);
'''


def main() -> int:
    node = find_node()
    if not node:
        raise SystemExit("node required")
    probe = ROOT / "scripts" / ".probe_model_disk.tmp.mjs"
    probe.write_text(PROBE, encoding="utf-8")
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
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
