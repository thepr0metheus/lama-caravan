#!/usr/bin/env python3
"""The live patch of what a cell holds: its RAM and GPU badges, its window's two tiles and its cards' figures, written again on every
poll tick (topology-render.js syncTopologyLive, cell-memory.js CellMemory.patch).

The defect (2026-11-07). A voice cell was started from the board and kept running. A tab open since before the start showed its line's badges
"RAM 3.7G | GPU 0.3G" for minutes, while /api/topology said gpuMem {"0": 2434} and ramBytes 5860118528; a tab opened later said
"RAM 5.5G | GPU 2.4G". 0.3G was what the process held in the first seconds of its start. The board draws a card again only when its structure
changes (topologyStructureFingerprint: a phase is structure, a figure is not), and between drawings the live patch wrote the speed and the
copy's progress — and not the memory, though the comment over the fingerprint said VRAM was among what it patched. A measured figure frozen
at the last drawing was shown as live.

The builder (topology-nodes.js nodeServerCardHtml) and the patch now read the cell's report through one class: CellMemory.measured reads it,
CellMemory draws the badges, the tiles and the cards' figures, and CellMemory.patch writes them again. So the pins draw a cell with the REAL
builder, read the drawing back into a small DOM, run the REAL syncTopologyLive over the next report, and compare what the patch left with
what the builder draws from that report — the badges as markup, the tiles and the cards' figures as words — and with the figures by value.

Pinned, each with its negative: a running cell's figures follow the report on its folded line, in its window (badges, tiles, cards) and on
its full card; a report that moved nothing writes nothing (not one write — a tick must not churn the page); a figure no longer told turns
into the dash, and one told at last turns into the figure; only a process that holds memory now is patched (running, warming, broken) — a
parked, failed or copying cell keeps the estimate it was drawn with; a cell in an engine keeps its engine's figures; a card the cell holds
nothing on any more says the dash.

topology-render.js and topology-nodes.js are loaded for real with cell-memory.js, cell-window.js, card-rows.js and i18n; the neighbours that
draw no cell are stubs. The words the pins expect are read out of static/js/i18n/en.js.

Run: python3 scripts/test_js_cell_memory_live.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _js_pins import run  # noqa: E402
from cell_speed_cases import en  # noqa: E402

STUBS = ("topology-modals,cables,routers,cloud,history,dialogs,favorites,config-locator,system-panels,"
         "onboarding,topology-dnd,canvas,usage-stats,dialog-llamas,models-page,system-page,onboarding-tours")

PREAMBLE = r"""
import "./_js_globals.mjs";
import { pathToFileURL } from "node:url";
globalThis.__stubValues = { ...(globalThis.__stubValues || {}),
  "topology-dnd.topologyPointerDrag": null, "canvas._cvDrag": null };
const st = await import(pathToFileURL(process.env.JS_ROOT + "/state.js").href);
const STATE = () => ({ config: {}, runners: [], artifacts: [], models: [], paths: {} });
const TOPO = () => ({ proxies: [], clients: [], routers: [], assignments: {}, llamas: [] });
st.setState(STATE());
st.setTopology(TOPO());
Date.now = () => 1_700_000_100_000;
globalThis.CSS = { escape: (x) => x };
const rc = await import(pathToFileURL(process.env.JS_ROOT + "/remote-cells.js").href);
const nodes = await import(pathToFileURL(process.env.JS_ROOT + "/topology-nodes.js").href);
const m = await import(pathToFileURL(process.env.JS_ROOT + "/topology-render.js").href);
const cf = await import(pathToFileURL(process.env.JS_ROOT + "/card-fold.js").href);
const reset = () => { st.setState(STATE()); st.setTopology(TOPO());
  cf.CARD_FOLD.pinned.clear(); cf.CARD_FOLD.densities = {}; cf.CARD_FOLD.peekKey = ""; cf.CARD_FOLD.openKey = ""; cf.CARD_FOLD.hideIdle.clear();
  cf.CARD_FOLD.launchers = {}; cf.CARD_FOLD.windowTabs.clear();
  for (const c of [rc._stoppingHosts, rc._stoppingCells, rc._deletingSlots, rc._newReservedCells, rc._pendingCellActions, rc._reservingCells]) c.clear(); };

// ── a small DOM, read back out of the builder's markup ──
// Elements keep their attributes in order, so a part the patch did not touch comes out as it went in. They answer what the patch asks
// of them: querySelector(All) by one compound of tag, classes and attributes (a selector with a combinator finds nothing here), classList,
// attributes, textContent, className, dataset, style. Every write is counted the way a browser would record it: setting text, a class name
// or an attribute writes even when the value is the same, a toggle or a removal that changes nothing does not. A bar's width (style) is not
// counted: no memory figure is a bar.
const VOID = new Set(["area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"]);
const unesc = (s) => s.replace(/&(amp|lt|gt|quot|#39);/g, (_, e) => ({ amp: "&", lt: "<", gt: ">", quot: '"', "#39": "'" }[e]));
const esc = (s) => String(s).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#39;");
globalThis.__writes = 0;
class Txt { constructor(text) { this.text = text; } html() { return esc(this.text); } get textContent() { return this.text; } }
class El {
  constructor(tag, attrs, parent) { this.tag = tag; this.attrs = attrs; this.children = []; this.parentElement = parent; this.selfClose = false; this.style = {}; }
  getAttribute(k) { const a = this.attrs.find((x) => x[0] === k); return a ? a[1] : null; }
  hasAttribute(k) { return this.attrs.some((x) => x[0] === k); }
  setAttribute(k, v) { const a = this.attrs.find((x) => x[0] === k); if (a) { a[1] = String(v); a[2] = false; } else this.attrs.push([k, String(v), false]); globalThis.__writes++; }
  removeAttribute(k) { const at = this.attrs.findIndex((x) => x[0] === k); if (at >= 0) { this.attrs.splice(at, 1); globalThis.__writes++; } }
  get className() { return this.getAttribute("class") || ""; }
  set className(v) { this.setAttribute("class", v); }
  get title() { return this.getAttribute("title") || ""; }
  set title(v) { this.setAttribute("title", v); }
  get classList() {
    const el = this, list = () => el.className.split(/\s+/).filter(Boolean);
    return { contains: (c) => list().includes(c),
      toggle: (c, force) => { const has = list().includes(c), on = force === undefined ? !has : !!force;
        if (on !== has) el.className = on ? [...list(), c].join(" ") : list().filter((x) => x !== c).join(" "); return on; },
      add: (c) => { if (!list().includes(c)) el.className = [...list(), c].join(" "); },
      remove: (...cs) => { if (cs.some((c) => list().includes(c))) el.className = list().filter((x) => !cs.includes(x)).join(" "); } };
  }
  get dataset() { const el = this, name = (k) => "data-" + String(k).replace(/[A-Z]/g, (c) => "-" + c.toLowerCase());
    return new Proxy({}, { get: (_, k) => el.getAttribute(name(k)) ?? undefined, set: (_, k, v) => { el.setAttribute(name(k), v); return true; } }); }
  get textContent() { return this.children.map((c) => c.textContent).join(""); }
  set textContent(v) { this.children = [new Txt(String(v))]; globalThis.__writes++; }
  *walk() { for (const c of this.children) if (c instanceof El) { yield c; yield* c.walk(); } }
  matches(sel) { const test = El.compound(sel); return !!test && test(this); }
  querySelector(sel) { const test = El.compound(sel); if (!test) return null; for (const el of this.walk()) if (test(el)) return el; return null; }
  querySelectorAll(sel) { const test = El.compound(sel); return test ? [...this.walk()].filter(test) : []; }
  static compound(sel) {
    const bare = String(sel).replace(/\[[^\]]*\]/g, "");
    if (/[\s>+~:,]/.test(bare)) return null;
    const tag = (bare.match(/^[a-zA-Z][\w-]*/) || [])[0] || "";
    const classes = [...bare.matchAll(/\.([\w-]+)/g)].map((x) => x[1]);
    const attrs = [...String(sel).matchAll(/\[([^\]=\s]+)(?:="([^"]*)")?\]/g)].map((x) => [x[1], x[2]]);
    return (el) => (!tag || el.tag === tag.toLowerCase()) && classes.every((c) => el.classList.contains(c))
      && attrs.every(([k, v]) => (v === undefined ? el.hasAttribute(k) : el.getAttribute(k) === v));
  }
  html() {
    const inner = this.children.map((c) => c.html()).join("");
    if (this.tag === "#root") return inner;
    const attrs = this.attrs.map(([k, v, bare]) => (bare ? ` ${k}` : ` ${k}="${esc(v)}"`)).join("");
    if (this.selfClose) return `<${this.tag}${attrs}/>`;
    return VOID.has(this.tag) ? `<${this.tag}${attrs}>` : `<${this.tag}${attrs}>${inner}</${this.tag}>`;
  }
}
const attrsOf = (s) => [...s.matchAll(/([^\s=>/]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+)))?/g)]
  .map((a) => [a[1], unesc(a[2] ?? a[3] ?? a[4] ?? ""), a[2] === undefined && a[3] === undefined && a[4] === undefined]);
const parse = (html) => {
  const root = new El("#root", [], null);
  let cur = root;
  for (const x of String(html).matchAll(/<!--[\s\S]*?-->|<\/([a-zA-Z][\w:-]*)\s*>|<([a-zA-Z][\w:-]*)((?:\s+[^\s=>/]+(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+))?)*)\s*(\/?)>|([^<]+)/g)) {
    if (x[1]) { let el = cur; while (el && el.tag !== x[1].toLowerCase()) el = el.parentElement; if (el && el.parentElement) cur = el.parentElement; }
    else if (x[2]) { const el = new El(x[2].toLowerCase(), attrsOf(x[3] || ""), cur); cur.children.push(el);
      if (x[4] === "/") el.selfClose = true; else if (!VOID.has(el.tag)) cur = el; }
    else if (x[5] !== undefined) cur.children.push(new Txt(unesc(x[5])));
  }
  return root;
};

// ── a machine with one card, one cell on it, drawn and then ticked ──
const GIB = 2 ** 30;
const NODE = { id: "h1", name: "Host", ip: "10.0.0.5", role: "host", online: true, gpus: [{ index: 0, name: "RTX", memoryTotalMiB: 24576 }] };
// A cell is known by its id (cellId): the builder draws it as the cell's address (data-cell-id), and the tick finds the line, the window
// and the card by it — a row with no id has nothing to patch.
const CELL = (extra) => ({ cellId: "c22001", port: 22001, isSlot: true, model: "a.gguf", slotConfig: { RUNNER: "llama-server", MODEL_FILE: "a.gguf" }, ...extra });
// What the live board saw (2026-11-07): the first seconds of the start, and a minute later.
const EARLY = { gpuIndexes: [0], gpuMem: { "0": 307 }, ramBytes: 3_970_000_000 };
const LATER = { gpuIndexes: [0], gpuMem: { "0": 2434 }, ramBytes: 5_860_118_528 };
const draw = (server, fold = true, node = NODE) => nodes.nodeServerCardHtml(node, server, { fold });
// One tick of the board over a page drawn earlier: the machine's next report, the number of writes it made.
const tick = (page, server, node = NODE) => {
  const keep = document.querySelector;
  document.querySelector = (sel) => (sel.includes('data-node-id="h1"') ? page : null);
  st.setTopology({ ...st.topology, nodes: [{ ...node, servers: [server] }] });
  globalThis.__writes = 0;
  try { m.syncTopologyLive(); } finally { document.querySelector = keep; }
  return globalThis.__writes;
};
// What a drawing says of the memory: the badges as markup (line first, then the window's or the card's), the window's two tiles as
// [which, figure, words], the figure of each card in its Memory tab.
const MEMORY = (html) => {
  const h = String(html);
  return {
    badges: [...h.matchAll(/<span class="mbadge [^"]*" data-t="cell-(?:ram|gpu)"[^>]*>[^<]*<\/span>/g)].map((x) => x[0]),
    tiles: [...h.matchAll(/data-t-id="[^"]*:(gpu|ram)"><span class="cw-tile-label">[^<]*<\/span><span class="cw-tile-value"[^>]*>([^<]*)<\/span><span class="cw-tile-sub"[^>]*>([^<]*)<\/span>/g)]
      .map((x) => [x[1], unesc(x[2]), unesc(x[3])]),
    cards: [...h.matchAll(/<span class="cw-mem-figure"[^>]*>([^<]*)<\/span>/g)].map((x) => unesc(x[1])),
  };
};
const words = (badge) => unesc((badge.match(/>([^<]*)<\/span>$/) || [])[1] || "");
const stateOf = (badge) => (badge.match(/data-t-state="(\w+)"/) || [])[1] || "";
const titleOf = (badge) => unesc((badge.match(/ title="([^"]*)"/) || [])[1] || "");
const classOf = (badge) => (badge.match(/^<span class="mbadge ([^"]*)"/) || [])[1] || "";
// The page drawn from `first`, ticked with `next`: what it says now, whether that is what the builder draws from `next`, and the writes.
const follow = (first, next, fold = true, node = NODE) => {
  const page = parse(draw(first, fold, node));
  const writes = tick(page, next, node);
  const now = MEMORY(page.html());
  return { now, same: JSON.stringify(now) === JSON.stringify(MEMORY(draw(next, fold, node))), kept: JSON.stringify(now) === JSON.stringify(MEMORY(draw(first, fold, node))), writes };
};
"""

GPU_TIP = en("vramChipTitle")
HELD, UNKNOWN, NONE = en("cwMemHeld"), en("cwMemUnknown"), en("cwMemNone")
RAM_TIP, UNKNOWN_TIP = en("cellRamTitle"), en("cellMemUnknownTitle")

PINS = [
    ("line_follows_the_report",
     "",
     '(() => { const r = follow(CELL({ phase: "running", ...EARLY }), CELL({ phase: "running", ...LATER }));'
     ' return { same: r.same, line: r.now.badges.slice(0, 2).map(words), states: r.now.badges.slice(0, 2).map(stateOf),'
     ' tip: titleOf(r.now.badges[1]) }; })()',
     json.dumps({"same": True, "line": ["RAM 5.5G", "GPU 2.4G"], "states": ["held", "held"], "tip": f"{GPU_TIP} — GPU0: 2.4 GiB"},
                ensure_ascii=False),
     "defect-history (2026-11-07): a running cell drawn at the start of its process (RAM 3.7G, GPU 0.3G) and ticked with the report of a "
     "minute later says what it holds now on its folded line — RAM 5.5G, GPU 2.4G, the tip split by card — exactly what the builder "
     "draws from that report; it used to keep 0.3G until something else redrew the card"),
    ("window_follows_the_report",
     "",
     '(() => { const r = follow(CELL({ phase: "running", ...EARLY }), CELL({ phase: "running", ...LATER }));'
     ' return { same: r.same, badges: r.now.badges.slice(2).map(words), tiles: r.now.tiles, cards: r.now.cards }; })()',
     json.dumps({"same": True, "badges": ["RAM 5.5G", "GPU 2.4G"], "tiles": [["gpu", "2.4G", HELD], ["ram", "5.5G", HELD]],
                 "cards": ["2.4 GB"]}, ensure_ascii=False),
     "positive: the folded cell's window says the same figures — its Memory tab's badges and its card's figure (GPU0: 2.4 GB), its "
     "Overview's two tiles — not the ones of the drawing: a window that said 0.3G under a line that says 2.4G would tell two stories"),
    ("full_card_follows_the_report",
     "",
     '(() => { const r = follow(CELL({ phase: "running", ...EARLY }), CELL({ phase: "running", ...LATER }), false);'
     ' return { same: r.same, badges: r.now.badges.map(words), classes: r.now.badges.map(classOf) }; })()',
     json.dumps({"same": True, "badges": ["RAM 5.5G", "GPU 2.4G"], "classes": ["mbadge-ram", "mbadge-vram"]}),
     "positive: an unfolded card's chips row follows the report as the line does"),
    ("a_tick_that_moves_nothing_writes_nothing",
     "",
     '[follow(CELL({ phase: "running", ...LATER }), CELL({ phase: "running", ...LATER })),'
     ' follow(CELL({ phase: "running", ...LATER }), CELL({ phase: "running", ...LATER }), false)].map((r) => [r.same, r.writes])',
     json.dumps([[True, 0], [True, 0]]),
     "negative: the same report a tick later writes nothing at all — on the line, in the window or on the card (no DOM churn: the "
     "board's tick runs every 1.5 s)"),
    ("a_figure_no_longer_told_is_a_dash",
     "",
     '(() => { const r = follow(CELL({ phase: "running", ...LATER }), CELL({ phase: "running", gpuIndexes: [0], gpuMem: { "0": 2434 } }));'
     ' return { same: r.same, ram: [words(r.now.badges[0]), stateOf(r.now.badges[0]), classOf(r.now.badges[0]), titleOf(r.now.badges[0])],'
     ' tile: r.now.tiles.find((x) => x[0] === "ram") }; })()',
     json.dumps({"same": True, "ram": ["RAM —", "unknown", "mbadge-mem-unknown", UNKNOWN_TIP], "tile": ["ram", "—", UNKNOWN]},
                ensure_ascii=False),
     "negative: the scout stops telling the RAM — the badge turns into the dash with its own tip, and the tile says it is not reported; "
     "the last figure does not stay drawn as if it were still held"),
    ("a_figure_told_at_last_is_held",
     "",
     '(() => { const r = follow(CELL({ phase: "running", gpuIndexes: [0], gpuMem: { "0": 2434 } }), CELL({ phase: "running", ...LATER }));'
     ' return { same: r.same, ram: [words(r.now.badges[0]), stateOf(r.now.badges[0]), classOf(r.now.badges[0]), titleOf(r.now.badges[0])] }; })()',
     json.dumps({"same": True, "ram": ["RAM 5.5G", "held", "mbadge-ram", RAM_TIP]}),
     "positive: a dash drawn while the RAM was not told becomes the figure when the report brings it — the class, the state and the tip "
     "with it"),
    ("a_card_it_holds_nothing_on_says_a_dash",
     "",
     '(() => { const r = follow(CELL({ phase: "running", ...LATER }), CELL({ phase: "running", gpuIndexes: [0], gpuMem: {}, ramBytes: 5_860_118_528 }));'
     ' return { same: r.same, gpu: [words(r.now.badges[1]), stateOf(r.now.badges[1])], tile: r.now.tiles.find((x) => x[0] === "gpu"), cards: r.now.cards }; })()',
     json.dumps({"same": True, "gpu": ["GPU 0", "none"], "tile": ["gpu", "0", NONE], "cards": ["—"]}, ensure_ascii=False),
     "negative: the card's reading lists the cell on GPU0 with nothing held there — the badge says the measured 0, the card's figure "
     "the dash, as the builder draws them; not the 2.4 GB of the tick before"),
    ("only_a_process_that_holds_memory_is_patched",
     "",
     '["running", "warming", "broken", "stopped", "error", "downloading"].map((phase) => {'
     ' const r = follow(CELL({ phase, modelSizeBytes: 7.5 * GIB, ...EARLY }), CELL({ phase, modelSizeBytes: 7.5 * GIB, ...LATER }));'
     ' return [phase, r.same, r.kept, words(r.now.badges[1])]; })',
     json.dumps([["running", True, False, "GPU 2.4G"], ["warming", True, False, "GPU 2.4G"], ["broken", True, False, "GPU 2.4G"],
                 ["stopped", True, True, "GPU ≈7.5G"], ["error", True, True, "GPU ≈7.5G"], ["downloading", True, True, "GPU ≈7.5G"]],
                ensure_ascii=False),
     "positive: a running, warming or broken cell's process holds memory now — its badges follow the report; negative: a parked, failed "
     "or copying cell keeps the estimate it was drawn with (≈ the file's size), whatever figures its report still carries"),
    ("a_parked_cell_is_not_written",
     "",
     '[follow(CELL({ phase: "stopped", modelSizeBytes: 7.5 * GIB, ...EARLY }), CELL({ phase: "stopped", modelSizeBytes: 7.5 * GIB, ...LATER })).writes]',
     "[0]",
     "negative: a parked cell's line and window are not written at all — its estimate is redrawn with the lane, when its phase changes"),
    ("an_engine_cell_keeps_its_engines_figures",
     'st.setState({ ...st.state, runners: [{ id: "llama-server", tokenContext: true }, { id: "ollama", engineCell: true, labelKey: "engineOllama" }] });'
     ' globalThis.__eng = { ...NODE, engines: [{ kind: "ollama", label: "Ollama", port: 11434, listen: "network", state: "ok", version: "0.12.3", api: "",'
     ' pids: [5100], ramBytes: 1288490189, models: [{ name: "qwen3:8b", loaded: true, memBytes: 5 * GIB, vramBytes: 4 * GIB, params: "8.2B", quant: "Q4_K_M" }] }] };'
     ' globalThis.__engCell = (extra) => CELL({ phase: "running", model: "", modelPath: "", slotConfig: { RUNNER: "ollama", ENGINE_MODEL: "qwen3:8b", ENGINE_PORT: "11434" }, ...extra });',
     '(() => { const r = follow(globalThis.__engCell({}), globalThis.__engCell(LATER), true, globalThis.__eng);'
     ' return [r.kept, r.writes, r.now.badges.slice(0, 2).map(words)]; })()',
     json.dumps([True, 0, ["RAM 1.0G", "GPU 4.0G"]]),
     "negative: a cell in an engine says what its engine reports for the model (Ollama's size and size_vram, told when it loads it) — "
     "the figures of the cell's own process in its report do not overwrite them"),
]

if __name__ == "__main__":
    sys.exit(run("js cell-memory live", ".probe_cell_memory_live.tmp.mjs", PREAMBLE, PINS, STUBS))
