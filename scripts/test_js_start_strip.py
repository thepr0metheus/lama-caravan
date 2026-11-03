#!/usr/bin/env python3
"""Actual start-strip.js: the start of a cell, said in its folded line (1.3.572).

The owner, 2026-10-18, after starting a cell whose model had to be copied: "when I start a cell, do not widen it by itself — only in the
same thin line say the same as the card says, without the name of the model, so it comes out shorter". The full card opened by itself
for a copy, a load and a warm-up; the line now keeps the cell, and under its name a strip carries the card's own status line. StartStrip
is the one place that says the copy's words for the strip, and leaves out the model's name, which the line already shows.

The module is loaded FOR REAL together with model-copy.js (the words of the copy), pace.js (its speed and time left, 1.3.661),
the real i18n (English) and utils.js (escaping). One module is a stub: form.js, which i18n.js asks only for the language list's
options and which would bring the whole board with it.

Run: python3 scripts/test_js_start_strip.py
"""
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _node import find_node, probe_args  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PROBE = r'''
import "./_js_globals.mjs";
import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
const { StartStrip } = await import(pathToFileURL(process.env.JS_ROOT + "/start-strip.js").href);
const { ModelCopy } = await import(pathToFileURL(process.env.JS_ROOT + "/model-copy.js").href);
const pass = [];
const pin = (cond, why) => { assert.ok(cond, why); pass.push(why); };
const GB = 2 ** 30;
const NAME = "Swift-Qwen3.8-Flash-Next-GSQ-RCO";
const FILE = "Swift-Qwen3.8-Flash-Next-GSQ-RCO-IQ3_S-00001-of-00002.gguf (1/2)";

// ── the file, without the model's name ──
{
  assert.equal(StartStrip.label(FILE, NAME), "IQ3_S-00001-of-00002.gguf (1/2)");
  pin(true, "the file's label loses the model's name and the hyphen after it: the part and the quant stay, they are what tells the files apart");
  pin(StartStrip.label("swift-qwen3.8-flash-next-gsq-rco-IQ3_S-00001-of-00002.gguf (1/2)", NAME) === "IQ3_S-00001-of-00002.gguf (1/2)",
    "the name is found whatever its case: the line's name and the file's are written by two different hands");
  pin(StartStrip.label("Model_Q4_K_M.gguf (1/1)", "Model") === "Q4_K_M.gguf (1/1)" && StartStrip.label("Model Q4.gguf", "Model") === "Q4.gguf",
    "an underscore and a space end a name as a hyphen does");
  pin(StartStrip.label("mmproj-BF16.gguf (2/2)", NAME) === "mmproj-BF16.gguf (2/2)"
      && StartStrip.label("mtp-q2_0.gguf (3/3)", NAME) === "mtp-q2_0.gguf (3/3)",
    "negative: a projector or a draft layer is not named after the model — it is said as it is");
  pin(StartStrip.label("Qwen3.8-27B-Q4_K_M.gguf (1/1)", "Qwen3") === "Qwen3.8-27B-Q4_K_M.gguf (1/1)",
    "negative: a dot is part of a version, not a break — \"Qwen3\" is not the name part of \"Qwen3.8-…\"");
  pin(StartStrip.label("Model.gguf (1/1)", "Model") === "Model.gguf (1/1)" && StartStrip.label("Model", "Model") === "Model",
    "boundary: a file that is nothing but the name (or the name and its extension) is said whole — an empty label says nothing");
  pin(StartStrip.label("Model-", "Model") === "Model-",
    "boundary: the name and a hyphen, nothing after — said whole");
  pin(StartStrip.label(FILE, "") === FILE && StartStrip.label(FILE, null) === FILE && StartStrip.label(FILE, undefined) === FILE,
    "negative: a line with no name (a reserved cell) leaves the file as it is");
  pin(StartStrip.label(null, NAME) === "" && StartStrip.label(undefined, NAME) === "" && StartStrip.label("", NAME) === "",
    "negative: no file, no label — never the word \"null\"");
  pin(StartStrip.label(FILE, "Other-Model") === FILE, "negative: the file of another model keeps its name");
}

// ── the words and the strip ──
{
  const copy = ModelCopy.said(9 * GB, 78 * GB);
  assert.equal(StartStrip.words(copy, FILE, NAME), "IQ3_S-00001-of-00002.gguf (1/2) · 9.0/78.0 GB · 12%");
  pin(true, "the words of the strip: the shortened file, the whole model's gigabytes (the pages' own, 2 ** 30) and the share — the card's line without the name");
  pin(ModelCopy.line(copy, FILE).endsWith(StartStrip.words(copy, FILE, NAME).slice(StartStrip.label(FILE, NAME).length)),
    "the figures are the card's own (ModelCopy.line), word for word: only the file's label is shorter");
  const html = StartStrip.download(copy, FILE, NAME);
  assert.equal(html, '<div class="fr-strip model-status-line" data-t="cell-row-strip"><span class="msl-bar"><span style="width:12%"></span></span>'
    + '<span class="msl-text" data-live-rowdl data-strip-name="Swift-Qwen3.8-Flash-Next-GSQ-RCO">IQ3_S-00001-of-00002.gguf (1/2) · 9.0/78.0 GB · 12%</span></div>');
  pin(true, "the strip: a thin line with the bar at the share and the words; the live patch finds the words by data-live-rowdl and the name to leave out by data-strip-name");
  const unknown = StartStrip.download(ModelCopy.said(1.5 * GB, 0), "downloading model", NAME);
  pin(unknown.includes('style="width:0%"') && unknown.includes(">downloading model · 1.5 GB<") && !unknown.includes("NaN") && !unknown.includes("%</span>"),
    "boundary: a copy that does not know its total has an empty bar and no share — never NaN%; the whole it does not know is not said (1.5 GB, not 1.5/0.0 GB)");
  const quoted = StartStrip.download(copy, 'a"><b>x.gguf', 'n"><i>');
  pin(!quoted.includes("<b>") && !quoted.includes("<i>") && quoted.includes("&quot;&gt;&lt;b&gt;x.gguf"),
    "the file and the name are escaped where they stand in the markup and in an attribute");
}

// ── how fast the copy goes (scout 2.42, 1.3.661; the owner, 2026-10-26: "show at what speed it downloads") ──
{
  const MIB = 2 ** 20;
  const fast = ModelCopy.said(9 * GB, 78 * GB, 112 * MIB);
  const words = ModelCopy.line(fast, "x.gguf");
  pin(words === "x.gguf · 9.0/78.0 GB · 12% · 112 MB/s · ~11 min left",
    "the copy's line says how fast the scout copies and how long the rest of the WHOLE model takes at that pace: 69 GB at 112 MB/s, ~11 min");
  pin(StartStrip.words(fast, FILE, NAME).endsWith(words.slice("x.gguf".length)), "the strip says the same pace, word for word");
  const none = [ModelCopy.said(9 * GB, 78 * GB), ModelCopy.said(9 * GB, 78 * GB, null), ModelCopy.said(9 * GB, 78 * GB, 0),
                ModelCopy.said(9 * GB, 78 * GB, -5), ModelCopy.said(9 * GB, 78 * GB, NaN)].map((c) => ModelCopy.line(c, "x.gguf"));
  pin(none.every((w) => w === "x.gguf · 9.0/78.0 GB · 12%") && none.every((w) => !w.includes("MB/s")),
    "negative: a pace the scout did not measure — none, 0, negative, NaN — says nothing: no «0 MB/s», no endless time left");
  pin([null, undefined, 0, -5, NaN, Infinity, "fast"].every((v) => ModelCopy.said(1, 2, v).rate === null) && ModelCopy.said(1, 2, 7).rate === 7,
    "a pace not measured is null on the copy, not a number: none, 0, negative, NaN, infinity, a word; a measured one is kept");
  const noTotal = ModelCopy.line(ModelCopy.said(1.5 * GB, 0, 50 * MIB), "x.gguf");
  pin(noTotal === "x.gguf · 1.5 GB · 50 MB/s", "a copy that does not know its total says what it has, its speed and no time left");
  const of = ModelCopy.of({ downloadedBytes: 2 * GB, totalBytes: 8 * GB, downloadingFile: "m.gguf", downloadBytesPerSec: 2 * GB }, []);
  pin(of.rate === 2 * GB && ModelCopy.line(of, "m.gguf").includes(" · 2.0 GB/s · "),
    "the scout's downloadBytesPerSec reaches the copy (ModelCopy.of), and a fast copy is said in GB/s");
}

// ── how far a loading cell has read its model (scout 2.43, 1.3.662; the owner, 2026-10-26: "at what speed it loads into memory") ──
{
  const { ModelLoad } = await import(pathToFileURL(process.env.JS_ROOT + "/model-copy.js").href);
  const MIB = 2 ** 20;
  const cell = (extra) => ({ slotConfig: {}, ...extra });
  const loading = cell({ readBytes: 12 * GB, modelBytes: 42 * GB, readBytesPerSec: 480 * MIB });
  pin(ModelLoad.words(loading, "warming") === "loading model into VRAM… · 12.0/42.0 GB · 29% · 480 MB/s · ~2 min left",
    "a cell loading its weights says how far (12 of 42 GB, the share), how fast, and how long the rest takes — the copy's own words");
  pin(ModelLoad.words(cell({ readBytes: 50e6, modelBytes: 42 * GB }), "warming") === "loading model into VRAM…",
    "negative: a few megabytes that do not move (a mapped model already in memory, its libraries read) say no figures — not a load stuck at 0 %");
  pin(ModelLoad.words(cell({ readBytes: 41 * GB, modelBytes: 42 * GB }), "warming") === "loading model into VRAM… · 41.0/42.0 GB · 98%",
    "a reading that stopped near the whole (the context is made after the weights) keeps its figures, without a speed");
  pin(ModelLoad.words(cell({ readBytes: 3 * GB, readBytesPerSec: GB }), "starting") === "starting · 3.0 GB · 1.0 GB/s",
    "a weight not measured (a cell adopted after a restart): what it read and how fast, no share and no time left");
  pin(ModelLoad.now(cell({ readBytes: 45 * GB, modelBytes: 42 * GB, readBytesPerSec: MIB })).done === 42 * GB
      && ModelLoad.now(cell({ readBytes: 45 * GB, modelBytes: 42 * GB, readBytesPerSec: MIB })).pct === 100,
    "the reading is capped at the whole: what its libraries took is not more of the model");
  pin([cell({}), cell({ readBytes: 0, readBytesPerSec: 5 }), cell({ readBytes: -5, readBytesPerSec: 5 }), cell({ readBytes: "x" })]
      .every((c) => ModelLoad.now(c) === null), "negative: nothing read, zero, negative, junk — no load, never a figure");
  pin(ModelLoad.label(cell({ slotConfig: { N_GPU_LAYERS: " 0 " } }), "warming") === "loading model into RAM…"
      && ModelLoad.label(cell({ slotConfig: { RUNNER: "Moonshine" } }), "warming") === "loading model into RAM…"
      && ModelLoad.label(cell({ slotConfig: { N_GPU_LAYERS: "1" } }), "warming") === "loading model into VRAM…",
    "a CPU cell loads into RAM — by its config, as the card always said; a cell with layers on a card into VRAM");
  pin(ModelLoad.label(cell({ status: { progressNote: "compiling 3/9" } }), "loading") === "loading model · compiling 3/9"
      && ModelLoad.label(cell({}), "starting") === "starting",
    "loading and starting say their words, a start's log note after them");
}

// ── a start with no bytes to count ──
{
  const inner = '<span class="topology-spinner" aria-hidden="true"></span><span class="msl-text">loading model into VRAM…</span>';
  pin(StartStrip.status(inner) === '<div class="fr-strip model-status-line" data-t="cell-row-strip">' + inner + "</div>",
    "a load or a warm-up says the card's own words, as the card says them, in the same strip");
  pin(StartStrip.status("") === "" && StartStrip.status(null) === "" && StartStrip.status(undefined) === "",
    "negative: nothing to say is no strip — an empty strip would be a line that grows for nothing");
}

for (const why of pass) console.log("  ok  " + why);
console.log(`js start-strip OK: ${pass.length} pins — the file without the model's name, the words of the copy, the strip`);
'''


def main():
    node = find_node()
    if not node:
        raise SystemExit("node required")
    probe = ROOT / "scripts" / ".probe_start_strip.tmp.mjs"
    probe.write_text(PROBE)
    try:
        result = subprocess.run(probe_args(node, ROOT / "scripts" / "_js_harness.mjs", probe), cwd=ROOT,
                                env={**os.environ, "JS_ROOT": str(ROOT / "static/js"), "JS_STUBS": "form",
                                     "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8", "TZ": "UTC"},
                                capture_output=True, text=True, timeout=60)
        print(result.stdout, end="")
        print(result.stderr, end="", file=sys.stderr)
    finally:
        probe.unlink(missing_ok=True)
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
