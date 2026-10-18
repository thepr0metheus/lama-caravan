#!/usr/bin/env python3
"""Actual cell-memory.js: the two badges of the memory a cell holds, RAM and GPU, on its line and on its card (1.3.583).

The owner, 2026-10-18, looking at the thin rows of a machine's cells, where only the video memory a cell holds was written: "for each model show
two badges, how much it holds in RAM and how much on the GPU, as separate badges, even if one of them is not occupied".

Four things a badge can say, and they look different — what the cell HOLDS now, what it is EXPECTED to hold when it runs, that it holds NOTHING,
and that the caravan is NOT TOLD. Pinned, by value, each with its negative: the figure's words (one place of gigabytes, "0" for nothing, "<0.1G"
for a sliver); a running cell's two measured badges; a figure the scout (RAM, from 2.35) or the machine's cards (GPU) did not tell, drawn as a dash
and never as a zero; a zero that was measured, drawn plain; a cell that is not running — its estimate where the card knows one (the runner's own
measured figure, else the model file's size; on the CPU the file is RAM, and the GPU holds none), a dash where it does not; a port with no model yet
saying nothing; an engine cell's own tip; garbage in (booleans, text, negatives) treated as not told; the classes and hooks; the words in all 20 languages;
and the wiring: the card builds both badges once, from the class, and keeps no copy of the old single chip.

The module is loaded FOR REAL with utils.js; i18n (English words) is a stand-in.

Run: python3 scripts/test_js_cell_memory.py
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _css_rules import CssRules  # noqa: E402
from _node import find_node  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LANGS = sorted(p.stem for p in (ROOT / "static" / "js" / "i18n").glob("*.js"))
KEYS = ["cellRamTitle", "cellMemUnknownTitle", "cellRamEstChipTitle", "cellMemIdleTitle"]

PROBE = r'''
import "./_js_globals.mjs";
import assert from "node:assert/strict";
const en = (await import("../static/js/i18n/en.js")).default;
globalThis.__stubReturns = { "i18n.t": (key, vars = {}) => String(en[key] ?? `?${key}`).replace(/\{(\w+)\}/g, (_, n) => (vars[n] === undefined ? `{${n}}` : vars[n])) };
const { CellMemory } = await import("../static/js/cell-memory.js");
const pass = [];
const eq = (got, want, why) => { assert.deepEqual(got, want, why + ` (got ${JSON.stringify(got)})`); pass.push(why); };
const GB = 2 ** 30;
const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
// [which, class, state, text] of each badge
const badges = (html) => [...html.matchAll(/<span class="mbadge mbadge-([\w-]+)" data-t="cell-(ram|gpu)" data-t-state="(\w+)" title="([^"]*)">([^<]*)<\/span>/g)].map((x) => [x[2], x[1], x[3], x[5]]);
const titles = (html) => [...html.matchAll(/ title="([^"]*)"/g)].map((x) => x[1]);
const of = (f) => CellMemory.of(f).html();

// ── the figure ──
eq([0, 0.5 * GB, 0.04 * GB, 0.05 * GB, 31 * GB, 63.4 * GB, 1536 * GB].map((b) => CellMemory.gb(b)), ["0", "0.5G", "<0.1G", "0.1G", "31.0G", "63.4G", "1536.0G"],
   "a size says gigabytes with one place, \"0\" for nothing and \"<0.1G\" for what one place would round to nothing — the unit the board prints (GiB)");
eq([-1, NaN, "x", null, undefined, Infinity].map((b) => CellMemory.gb(b)), ["", "", "", "", "", ""], "negative: a size that is negative, not a number, or missing says nothing — never \"0\" or \"NaN\"");

// ── a cell that runs: two measured badges ──
eq(badges(of({ live: true, gpuKnown: true, ramBytes: 4.2 * GB, vramBytes: 31 * GB })),
   [["ram", "ram", "held", "RAM 4.2G"], ["gpu", "vram", "held", "GPU 31.0G"]],
   "a running cell: what its processes hold in RAM, then what they hold on the cards — two separate badges, RAM first, solid (held)");
eq(titles(of({ live: true, gpuKnown: true, ramBytes: 4.2 * GB, vramBytes: 31 * GB, split: "GPU1: 31.0 GiB" })).map((t) => t.replace(/&#39;/g, "'")),
   [en.cellRamTitle, `${en.vramChipTitle} — GPU1: 31.0 GiB`], "the tips: the RAM badge says it is the resident size and what it counts; the GPU badge keeps its old words and the split by card");
eq(badges(of({ live: true, gpuKnown: true, ramBytes: 13 * GB, vramBytes: 0 })),
   [["ram", "ram", "held", "RAM 13.0G"], ["gpu", "mem-zero", "none", "GPU 0"]],
   "a running cell on the CPU on a machine whose cards were read: the GPU badge is there, and it says 0 — plain, not green (nothing held there)");
eq(badges(of({ live: true, gpuKnown: true, ramBytes: 0.3 * GB, vramBytes: 12 * GB })).map((b) => b[3]), ["RAM 0.3G", "GPU 12.0G"],
   "a cell that sits on the card holds little RAM — and the RAM badge still says it (0.3G), not nothing");

// ── not told is not zero ──
eq(badges(of({ live: true, gpuKnown: true, ramBytes: null, vramBytes: 31 * GB })),
   [["ram", "mem-unknown", "unknown", "RAM —"], ["gpu", "vram", "held", "GPU 31.0G"]],
   "negative: a scout older than 2.35 does not say the RAM of a cell — a dash (muted, dashed), never a 0 that would say the cell holds none; the GPU badge is unaffected");
eq(badges(of({ live: true, gpuKnown: false, ramBytes: 2 * GB, vramBytes: 0 })),
   [["ram", "ram", "held", "RAM 2.0G"], ["gpu", "mem-unknown", "unknown", "GPU —"]],
   "negative: a machine whose cards were not read (no NVIDIA driver, macOS) has no GPU figure to sum — a dash, not 0 (a 0 would say the card holds none of it)");
eq(titles(of({ live: true, gpuKnown: false, ramBytes: null })).map((t) => t.replace(/&#39;/g, "'")), [en.cellMemUnknownTitle, en.cellMemUnknownTitle],
   "the dash's tip says why there is no figure and that a dash is not a zero");
eq(badges(of({ live: true, gpuKnown: true, ramBytes: 0, vramBytes: 1 * GB })).map((b) => b.slice(1)), [["mem-zero", "none", "RAM 0"], ["vram", "held", "GPU 1.0G"]],
   "boundary: a RAM of exactly 0 that was measured is a plain 0 — a measure, and said");

// ── garbage in is not told ──
eq(badges(of({ live: true, gpuKnown: true, ramBytes: true, vramBytes: "12" })).map((b) => [b[0], b[2]]).concat(badges(of({ live: true, gpuKnown: true, ramBytes: "x", vramBytes: -5 })).map((b) => [b[0], b[2]])),
   [["ram", "unknown"], ["gpu", "held"], ["ram", "unknown"], ["gpu", "unknown"]],
   "negative: a boolean, a negative, or a word where a size should be is not told (a number given as text is read, as the topology's other figures are)");
eq(badges(of({ live: true, gpuKnown: true, ramBytes: undefined, vramBytes: undefined })).map((b) => b[2]), ["unknown", "unknown"], "negative: no figure at all — both not told");

// ── a cell that does not run ──
eq(badges(of({ cpu: true, fileBytes: 13 * GB })), [["ram", "ram-est", "expected", "RAM ≈13.0G"], ["gpu", "mem-zero", "none", "GPU 0"]],
   "a parked CPU cell: its weights will be in RAM (the file's size, an estimate: dashed, ≈) and it will hold none on the cards (0, known from the config)");
eq(titles(of({ cpu: true, fileBytes: 13 * GB })).map((t) => t.replace(/&#39;/g, "'")), [en.cellRamEstChipTitle, en.topologyCpuCellsHint], "its tips: the RAM estimate's words, and the CPU hint for the 0");
eq(badges(of({ cpu: true })).map((b) => b.slice(1)), [["mem-unknown", "idle", "RAM —"], ["mem-zero", "none", "GPU 0"]],
   "negative: a parked CPU cell with no file size — RAM is a dash (nothing says how much), GPU is still 0: that is known");
eq(badges(of({ fileBytes: 7.5 * GB })).map((b) => b.slice(1)), [["mem-unknown", "idle", "RAM —"], ["vram-est", "expected", "GPU ≈7.5G"]],
   "a parked cell that will be on a card: the file's size is the GPU estimate (the old chip, now named); RAM has nothing to expect — a dash");
eq(badges(of({ fileBytes: 4.7 * GB, plannedGb: 12.5 })).map((b) => b[3]), ["RAM —", "GPU ≈12.5G"],
   "the runner's own measured figure wins over the file's size (llama.cpp-omni's GGUF is 4.7 GB, its cell takes 12.5)");
eq(titles(of({ fileBytes: 4.7 * GB, plannedGb: 12.5 })).map((t) => t.replace(/&#39;/g, "'")), [en.cellMemIdleTitle, en.vramPlanChipTitle], "…and its tip says it is a measure of the engine, not the file");
eq(titles(of({ fileBytes: 7.5 * GB })).map((t) => t.replace(/&#39;/g, "'")), [en.cellMemIdleTitle, en.vramEstChipTitle], "…and the estimate's tip says it is from the file's size");
eq(badges(of({})).map((b) => b.slice(1)), [["mem-unknown", "idle", "RAM —"], ["mem-unknown", "idle", "GPU —"]],
   "negative: a parked cell of which nothing is known — both dashes, \"not running, nothing says how much\": no estimate made up");
eq(badges(of({ live: false, gpuKnown: true, ramBytes: 5 * GB, vramBytes: 9 * GB })).map((b) => b[3]), ["RAM —", "GPU —"],
   "negative: a cell that does not run holds nothing now — the figures of a process that is not there are not shown as held");

// ── a port with no model yet, and an engine's own tip ──
eq([of({ reserved: true }), of({ reserved: true, live: true, ramBytes: 1, vramBytes: 1, gpuKnown: true })], ["", ""], "negative: a reserved port has no model — nothing to say, no badges");
eq(titles(of({ live: true, gpuKnown: true, ramBytes: GB, vramBytes: GB, heldTitle: "Memory Ollama holds" })), ["Memory Ollama holds", "Memory Ollama holds"],
   "an engine's cell: both held badges say that the engine reports it (its own words)");
eq(titles(of({ live: true, gpuKnown: false, ramBytes: null, heldTitle: "Memory Ollama holds" })).map((t) => t.replace(/&#39;/g, "'")), [en.cellMemUnknownTitle, en.cellMemUnknownTitle],
   "negative: the engine's words go on what is held only — a dash keeps its own tip");

// ── the markup ──
{
  const html = of({ live: true, gpuKnown: true, ramBytes: GB, vramBytes: GB });
  eq([html.includes('data-t="cell-ram"'), html.includes('data-t="cell-gpu"'), (html.match(/data-t-state="held"/g) || []).length], [true, true, 2],
     "each badge has its hook and says its state (held, expected, none, unknown, idle) — a test finds it by that, not by its colour");
  const tip = of({ live: true, gpuKnown: true, ramBytes: GB, vramBytes: GB, heldTitle: `a "quoted" <b>engine</b> & 'more'` });
  eq(tip.includes("&quot;quoted&quot; &lt;b&gt;engine&lt;/b&gt; &amp; &#39;more&#39;") && !tip.includes("<b>"), true, "negative: a tip is escaped — a model's or an engine's name cannot break the markup");
}

// ── the words ──
{
  const langs = JSON.parse(process.env.LANGS), keys = JSON.parse(process.env.KEYS);
  const lacking = [], same = [];
  for (const lang of langs) {
    const m = (await import(`../static/js/i18n/${lang}.js`)).default;
    for (const key of keys) {
      if (!m[key]) { lacking.push(`${lang}.${key}`); continue; }
      if (lang !== "en" && m[key] === en[key]) same.push(`${lang}.${key}`);
    }
  }
  eq(lacking, [], "all 4 keys of the badges' tips exist in all 20 languages");
  eq(same, [], "no language is left with the English text");
}

for (const why of pass) console.log("  ok  " + why);
console.log(`js cell-memory OK: ${pass.length} pins — the figure, a running cell, not told is not zero, garbage in, a cell that does not run, a port with no model, the markup, the words`);
'''


def wiring():
    """The card builds the two badges once, from the class, and keeps no copy of the old single chip: one fact in one place."""
    nodes = (ROOT / "static" / "js" / "topology-nodes.js").read_text(encoding="utf-8")
    problems = []
    if len(re.findall(r"CellMemory\.of\(", nodes)) != 2 or "const memBadge = memory.html();" not in nodes:
        problems.append("topology-nodes.js must build the memory badges from CellMemory.of(...) — once for an engine's cell and once for the others — and take memBadge from memory.html()")
    if re.search(r'const memBadge = engineRunner\s*\?', nodes) or 'mbadge("vram", `${escapeHtml((_vramMib' in nodes:
        problems.append("topology-nodes.js has the old single memory chip again — the two badges are cell-memory.js's")
    if "const row = new CellRow({" in nodes and "chip: memBadge || deviceChip" not in nodes:
        problems.append("the line (CellRow) must carry the same badges as the card: chip: memBadge || deviceChip")
    css = (ROOT / "static" / "css" / "modals.css").read_text(encoding="utf-8")
    fold = (ROOT / "static" / "css" / "fold.css").read_text(encoding="utf-8")

    def rule(sheet, selector):
        merged = {}
        for sel, decl in CssRules.rules(sheet):
            if sel == selector:
                merged.update(decl)
        return merged
    for cls in ("mbadge-ram", "mbadge-ram-est", "mbadge-mem-zero", "mbadge-mem-unknown"):
        if not rule(css, f".{cls}"):
            problems.append(f"modals.css has no rule for .{cls}")
    held, expected, zero, unknown = (rule(css, f".{c}") for c in ("mbadge-ram", "mbadge-ram-est", "mbadge-mem-zero", "mbadge-mem-unknown"))
    if "dashed" in held.get("border", "") or "#4593ff" not in held.get("border-color", ""):
        problems.append(".mbadge-ram must be solid, in the CPU's blue (#4593ff): a held figure")
    if "dashed" not in expected.get("border", ""):
        problems.append(".mbadge-ram-est must be dashed: an estimate reads as a forecast, as the GPU's does")
    if "dashed" not in unknown.get("border", "") or unknown.get("background") != "transparent":
        problems.append(".mbadge-mem-unknown (a dash: not told) must be dashed and have no fill — it must not look like a figure")
    if "solid" not in zero.get("border", "") or "dashed" in zero.get("border", ""):
        problems.append(".mbadge-mem-zero (a measured 0) must be plain: a zero and a dash are not the same fact and must not look alike")
    if rule(fold, ".cell-row.parked .mbadge-ram-est") != rule(fold, ".cell-row.parked .mbadge-vram-est") or not rule(fold, ".cell-row.parked .mbadge-ram-est"):
        problems.append("a parked line's RAM estimate must go grey with its GPU estimate (fold.css: one rule for both)")
    return problems


def main():
    problems = wiring()
    if problems:
        print("js cell-memory FAILED (wiring):")
        for line in problems:
            print("  - " + line)
        raise SystemExit(1)
    print("  ok  the card builds both badges once from the class; the line carries them; no copy of the old chip; every class has a rule")
    node = find_node()
    if not node:
        raise SystemExit("node required")
    probe = ROOT / "scripts" / ".probe_cell_memory.tmp.mjs"
    probe.write_text(PROBE)
    try:
        harness = ROOT / "scripts" / "_js_harness.mjs"
        result = subprocess.run([node, "--import", f"data:text/javascript,import {{ register }} from 'node:module'; register('{harness.as_uri()}');", str(probe)], cwd=ROOT,
                                env={**os.environ, "JS_ROOT": str(ROOT / "static/js"), "JS_STUBS": "i18n", "LANGS": json.dumps(LANGS), "KEYS": json.dumps(KEYS),
                                     "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8", "TZ": "UTC"},
                                capture_output=True, text=True, timeout=90)
        print(result.stdout, end="")
        print(result.stderr, end="", file=sys.stderr)
    finally:
        probe.unlink(missing_ok=True)
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
