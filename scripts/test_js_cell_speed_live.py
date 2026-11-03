#!/usr/bin/env python3
"""The live patch of a cell's line: what topology-render.js writes into the line on every poll tick (1.3.588).

The line is drawn twice. The card builder writes it whole (test_js_topology_nodes.py reads the table of cases for that), the live patch rewrites
the speed, the breathing and the hint in place, and a fact told in two places drifts. This snapshot reads the SAME table
(scripts/cell_speed_cases.py) for the patch: the switch's `busy`, the speed's `held`, its words and its title must come out as the builder's do.

Beyond the table, what only the patch can get wrong: a hint set on a held speed must be taken off when the cell starts to work (a title left
behind would explain a plain figure as a held one, and an empty title would hide the row's own title from the pointer), and the speed of a
cell that stops must go with it.

A folded cell's window (cell-window.js, 1.3.621) says the same speed twice more — on its Overview's tile and on its band, where the band
also says whether the cell answers — and the patch finds the window where it found the full card. Its pins read the builder's own words:
`CellWindow.speedWords` is the one rule for the band, the tile shows a dash where the line shows nothing.

topology-render.js is loaded for real with the real polling.js (so the number is written by the board's own formatTps, not by a copy of it);
the rest of the board is stubbed as in test_js_topology_render.py, and the words the pins expect are read out of static/js/i18n/en.js.

Run: python3 scripts/test_js_cell_speed_live.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _js_pins import run  # noqa: E402
from cell_speed_cases import CASES, HELP, LAST, en  # noqa: E402

STUBS = ("topology-modals,cables,routers,charts,cloud,history,dialogs,"
         "llama-edit,form,favorites,config-locator,system-panels,onboarding,topology-dnd,canvas,"
         "usage-stats,dialog-llamas,models-page,system-page,onboarding-tours,memory,command-preview,model-meta,"
         "hf,models,settings,auth,onboarding-strings")

PREAMBLE = r"""
import "./_js_globals.mjs";
import { pathToFileURL } from "node:url";
globalThis.__stubValues = { ...(globalThis.__stubValues || {}),
  "topology-dnd.topologyPointerDrag": null, "canvas._cvDrag": null };
const st = await import(pathToFileURL(process.env.JS_ROOT + "/state.js").href);
st.setState({ config: {} });
st.setTopology({ proxies: [], clients: [], routers: [], assignments: {} });
const m = await import(pathToFileURL(process.env.JS_ROOT + "/topology-render.js").href);
const reset = () => { st.setState({ config: {} }); st.setTopology({ proxies: [], clients: [], routers: [], assignments: {} }); };
globalThis.CSS = { escape: (x) => x };
// A line and its speed as the browser holds them, recording what the patch writes: the classes it toggles, the title it sets or takes off.
const SPAN = () => { const el = { textContent: "", attrs: {}, classes: {}, style: {}, dataset: {} };
  el.classList = { toggle: (name, on) => { el.classes[name] = !!on; } };
  el.setAttribute = (k, v) => { el.attrs[k] = String(v); };
  el.removeAttribute = (k) => { delete el.attrs[k]; };
  return el; };
const LINE = () => { const span = SPAN(); const el = { classes: {}, span };
  el.querySelector = (sel) => (sel === "[data-live-rowtps]" ? span : null);
  el.classList = { toggle: (name, on) => { el.classes[name] = !!on; } };
  return el; };
// One tick of the patch over one cell, on the line that was there (or a new one): the line afterwards.
const tick = (server, running, kept) => {
  const line = kept || LINE();
  const card = { querySelector: () => null, querySelectorAll: () => [] };
  const nodeEl = { querySelector: (sel) => (sel.startsWith(".node-server[") ? card : sel.startsWith(".cell-row[") ? line : null) };
  const keep = document.querySelector;
  document.querySelector = (sel) => (sel.includes('data-node-id="h1"') ? nodeEl : null);
  st.setTopology({ ...st.topology, nodes: [{ id: "h1", role: "host", online: true, gpus: [],
    servers: [{ port: 22001, isSlot: true, phase: running ? "running" : "stopped", ...server }] }] });
  try { m.syncTopologyLive(); } finally { document.querySelector = keep; }
  return line;
};
const said = (l) => ({ busy: !!l.classes.busy, held: !!l.span.classes.held, text: l.span.textContent, title: l.span.attrs.title || "" });
// A folded cell's window as the browser holds it (cell-window.js): the live part carries data-cell-live and the port, the tile's figure and
// the band's words are the two spans the patch writes. The full card is not there — the window stands where it stood.
const WIN = () => { const tile = SPAN(), band = SPAN(), sub = SPAN();
  tile.textContent = "drawn"; band.textContent = "drawn"; sub.textContent = "drawn";
  return { tile, band, sub, querySelectorAll: () => [],
    querySelector: (sel) => ({ "[data-live-cwtps]": tile, "[data-live-cwband]": band, "[data-live-cwtpssub]": sub }[sel] || null) }; };
const tickWin = (server, running, kept) => {
  const win = kept || WIN();
  const nodeEl = { querySelector: (sel) => (sel.startsWith(".node-server[") ? null
    : sel.startsWith("[data-cell-window-live][") && sel.includes('data-llama-port="22001"') ? win : sel.startsWith(".cell-row[") ? LINE() : null) };
  const keep = document.querySelector;
  document.querySelector = (sel) => (sel.includes('data-node-id="h1"') ? nodeEl : null);
  st.setTopology({ ...st.topology, nodes: [{ id: "h1", role: "host", online: true, gpus: [],
    servers: [{ port: 22001, isSlot: true, phase: running ? "running" : "stopped", ...server }] }] });
  try { m.syncTopologyLive(); } finally { document.querySelector = keep; }
  return win;
};
const saidWin = (w) => ({ tile: w.tile.textContent, band: w.band.textContent, sub: w.sub.textContent });
// A load line as the browser holds it (1.3.662): its words, and the bar beside them with its fill.
const LOADEL = () => { const fill = { style: {} };
  const bar = { classes: {}, fill, classList: { toggle: (n, on) => { bar.classes[n] = !!on; } }, querySelector: (sel) => (sel === "span" ? fill : null) };
  const text = { textContent: "drawn", parentElement: { querySelector: (sel) => (sel === ".msl-bar" ? bar : null) } };
  return { text, bar, querySelectorAll: () => [], querySelector: (sel) => (sel === "[data-live-load]" ? text : null) }; };
const saidLoad = (r) => ({ text: r.text.textContent, looping: !!r.bar.classes.indeterminate, width: r.bar.fill.style.width ?? "" });
const tickLoad = (server) => {
  const card = LOADEL();
  // The folded line holds its strip's load words too, beside its own speed span.
  const line = LINE(); const strip = LOADEL(); const ownQuery = line.querySelector;
  line.querySelector = (sel) => (sel === "[data-live-load]" ? strip.text : ownQuery(sel));
  const nodeEl = { querySelector: (sel) => (sel.startsWith(".node-server[") ? card : sel.startsWith(".cell-row[") ? line : null) };
  const keep = document.querySelector;
  document.querySelector = (sel) => (sel.includes('data-node-id="h1"') ? nodeEl : null);
  st.setTopology({ ...st.topology, nodes: [{ id: "h1", role: "host", online: true, gpus: [],
    servers: [{ port: 22001, isSlot: true, slotConfig: {}, ...server }] }] });
  try { m.syncTopologyLive(); } finally { document.querySelector = keep; }
  return { card: saidLoad(card), line: saidLoad(strip) };
};
const GIB = 2 ** 30, MIB = 2 ** 20;
"""

PINS = [
    (f"table_{name}",
     "",
     f"said(tick({json.dumps(server)}, {json.dumps(running)}))",
     json.dumps(want),
     f"the line from the live patch — {name}: {why}")
    for name, server, running, want, why in CASES
]

PINS += [
    ("a_hint_goes_when_the_work_starts",
     "",
     'said(tick({ genTps: 211.27, requestsProcessing: 1 }, true, tick({ genTps: 211.27, requestsProcessing: 0 }, true)))',
     json.dumps({"busy": True, "held": False, "text": "211.3 t/s", "title": ""}),
     "defect-history (a title would outlive the state): the cell held its speed, then a request came — the same line is plain again, the `held` "
     "class and the hint are gone, and no empty title is left behind to hide the row's own"),
    ("the_hint_comes_when_the_work_ends",
     "",
     'said(tick({ genTps: 211.27, requestsProcessing: 0 }, true, tick({ genTps: 211.27, requestsProcessing: 1 }, true)))',
     json.dumps({"busy": False, "held": True, "text": f"{LAST} 211.3 t/s", "title": HELP}),
     "the request ended: the same line stops breathing at once, the speed turns into the last one and takes its hint"),
    ("a_stopped_cell_loses_its_speed",
     "",
     'said(tick({ genTps: 211.27, requestsProcessing: 0 }, false, tick({ genTps: 211.27, requestsProcessing: 0 }, true)))',
     json.dumps({"busy": False, "held": False, "text": "", "title": ""}),
     "the cell stopped: the line says no speed, no `held`, no hint — a quiet figure of a cell that is not there would be a lie"),
    ("a_title_is_removed_not_emptied",
     "",
     '(() => { const l = tick({ genTps: 5, requestsProcessing: 0 }, true); tick({ genTps: 5, requestsProcessing: 1 }, true, l); return Object.keys(l.span.attrs); })()',
     "[]",
     "negative: the hint is taken off with removeAttribute — an empty `title=\"\"` would hide the row's own title from the pointer"),
]

ANSWERING, WAITING, PROMPT, NONE = en("cwAnswering"), en("cwWaiting"), en("cwPromptSpeed"), en("cwSpeedNone")
NO_METRICS, NO_METRICS_NEXT = en("cwSpeedNoMetrics"), en("cwSpeedNoMetricsNext")
PINS += [
    ("window_working",
     "",
     'saidWin(tickWin({ genTps: 41.7, promptTps: 912.4, requestsProcessing: 1 }, true))',
     json.dumps({"tile": "41.70 t/s", "band": f"{ANSWERING} · 41.70 t/s", "sub": PROMPT.replace("{tps}", "912.4")}),
     "positive: the window of a cell answering a request — the tile says the speed and the prompt's, the band says it answers and how fast"),
    ("window_waiting_holds_the_last",
     "",
     'saidWin(tickWin({ genTps: 41.7, requestsProcessing: 0 }, true))',
     json.dumps({"tile": f"{LAST} 41.70 t/s", "band": f"{WAITING} · {LAST} 41.70 t/s", "sub": ""}),
     "the request ended: the tile turns to the last speed, the band says the cell waits — the same words as the line's"),
    ("window_waiting_no_speed",
     "",
     'saidWin(tickWin({ genTps: 0, requestsProcessing: 0 }, true))',
     json.dumps({"tile": "—", "band": WAITING, "sub": NONE}),
     "negative: no request measured yet — the tile is a dash, not «0 t/s», and the band says only that the cell waits"),
    ("window_not_told",
     "",
     'saidWin(tickWin({ genTps: 5 }, true))',
     json.dumps({"tile": f"{LAST} 5 t/s", "band": f"{LAST} 5 t/s", "sub": ""}),
     "negative: the server does not say how many requests run — the band claims neither «answering» nor «waiting», only the speed, "
     "held as the line holds it"),
    ("window_moves_with_the_cell",
     "",
     'saidWin(tickWin({ genTps: 41.7, requestsProcessing: 1 }, true, tickWin({ genTps: 0, requestsProcessing: 0 }, true)))',
     json.dumps({"tile": "41.70 t/s", "band": f"{ANSWERING} · 41.70 t/s", "sub": ""}),
     "defect-history (1.3.621, до выкладки): the same window, a tick later — a request came: the figure, its line and the band are "
     "rewritten in place; negative: «no request measured yet» does not stay under a measured speed"),
    ("window_no_metrics_next",
     "",
     'saidWin(tickWin({ noMetrics: true, metricsNext: true }, true))',
     json.dumps({"tile": "—", "band": "", "sub": NO_METRICS_NEXT}),
     "defect-history (Hermes, the owner 2026-10-26: «модель отвечала — почему не видно, сколько токенов в секунду?»): its server keeps no "
     "metrics (started without --metrics) — the line says the speed is not measured and that a restart brings it, not «no request "
     "measured yet»; the band claims neither answering nor waiting"),
    ("window_no_metrics",
     "",
     'saidWin(tickWin({ noMetrics: true, metricsNext: false }, true))',
     json.dumps({"tile": "—", "band": "", "sub": NO_METRICS}),
     "negative: a server that keeps none and whose next start does not bring them (a box said off, another server) — only «not measured»"),
    ("window_no_metrics_as_text_is_not_told",
     "",
     'saidWin(tickWin({ noMetrics: "true", genTps: 0, requestsProcessing: 0 }, true))',
     json.dumps({"tile": "—", "band": WAITING, "sub": NONE}),
     "negative: the word as text is not the fact — read as not told, the line is the old one"),
    ("window_stopped_untouched",
     "",
     'saidWin(tickWin({ genTps: 41.7, requestsProcessing: 0 }, false))',
     json.dumps({"tile": "drawn", "band": "drawn", "sub": "drawn"}),
     "negative: a cell that is not running is repainted with the lane, not patched — the patch leaves the window's words as drawn"),
]

PINS += [
    ("load_line_moves",
     "",
     '(() => { const r = LOADEL(); m._liveLoad(r, { readBytes: 12 * GIB, modelBytes: 42 * GIB, readBytesPerSec: 480 * MIB, slotConfig: {} }, "warming"); return saidLoad(r); })()',
     json.dumps({"text": "loading model into VRAM… · 12.0/42.0 GB · 29% · 480 MB/s · ~2 min left", "looping": False, "width": "29%"}),
     "1.3.662: the load line of a cell on its way is patched in place — its words with how far, how fast and how long, and its bar "
     "stops looping and stands at the share"),
    ("load_line_unmeasured_loops",
     "",
     '(() => { const r = LOADEL(); m._liveLoad(r, { slotConfig: {} }, "warming"); return saidLoad(r); })()',
     json.dumps({"text": "loading model into VRAM…", "looping": True, "width": ""}),
     "negative: a load its scout does not measure keeps its words alone, and its bar loops — no 0 % drawn"),
    ("load_line_in_the_tick",
     "",
     'tickLoad({ phase: "warming", readBytes: 3 * GIB, modelBytes: 6 * GIB, readBytesPerSec: GIB })',
     json.dumps({"card": {"text": "loading model into VRAM… · 3.0/6.0 GB · 50% · 1.0 GB/s · ~5 s left", "looping": False, "width": "50%"},
                 "line": {"text": "loading model into VRAM… · 3.0/6.0 GB · 50% · 1.0 GB/s · ~5 s left", "looping": False, "width": "50%"}}),
     "the tick of the board patches a warming cell's card and its folded line's strip with its load (syncTopologyLive)"),
    ("load_line_not_while_running",
     "",
     'tickLoad({ phase: "running", readBytes: 3 * GIB, modelBytes: 6 * GIB, readBytesPerSec: GIB })',
     json.dumps({"card": {"text": "drawn", "looping": False, "width": ""}, "line": {"text": "drawn", "looping": False, "width": ""}}),
     "negative: a running cell keeps reading (a mapped model pages in) — neither its card nor its line says a load"),
]

# A machine's page (machine-head.js, 1.3.630): the same tick keeps its head current — the map's lanes and the band's words.
HEAD = ("(page => { const map = { innerHTML: '' }; const title = { textContent: 'drawn' }; const sub = { innerHTML: '' };"
        " const band = { dataset: { tState: 'good' }, querySelector: (s) => ({ '.ui-band-title': title, '.ui-band-sub': sub }[s] || null) };"
        " const nodeEl = { matches: (s) => page && s === '.machine-page',"
        " querySelector: (sel) => ({ '[data-machine-map]': map, '[data-machine-band]': band }[sel] || null) };"
        " const keep = document.querySelector; document.querySelector = (sel) => (sel.includes('data-node-id=\"h1\"') ? nodeEl : null);"
        " st.setTopology({ ...st.topology, nodes: [{ id: 'h1', role: 'host', online: true, gpus: [], cpu: { ram: { totalGb: 16, usedGb: 4 } },"
        " servers: [{ port: 22001, isSlot: true, phase: 'running', ramBytes: 2 ** 31 }] }] });"
        " try { m.syncTopologyLive(); } finally { document.querySelector = keep; }"
        " return [map.innerHTML.includes('data-t=\"machine-map-lane\" data-t-id=\"ram\"'), title.textContent]; })")
PINS += [
    ("machine_head_live",
     "",
     f"{HEAD}(true)",
     json.dumps([True, en("machineBandRunning").replace("{n}", "1").replace("{m}", "1")]),
     "a machine's page: the tick writes its map's lanes (the RAM's among them) and its band's words in place (machine-head.js)"),
    ("machine_head_not_on_the_glance",
     "",
     f"{HEAD}(false)",
     json.dumps([False, "drawn"]),
     "negative: a node that is no machine page (the main board's glance) — its head is not patched: it has none"),
]

if __name__ == "__main__":
    sys.exit(run("js cell-speed live", ".probe_cell_speed_live.tmp.mjs", PREAMBLE, PINS, STUBS))
