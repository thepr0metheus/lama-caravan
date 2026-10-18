#!/usr/bin/env python3
"""The live patch of a cell's line: what topology-render.js writes into the line on every poll tick (1.3.588).

The line is drawn twice. The card builder writes it whole (test_js_topology_nodes.py reads the table of cases for that), the live patch rewrites
the speed, the breathing and the hint in place, and a fact told in two places drifts. This snapshot reads the SAME table
(scripts/cell_speed_cases.py) for the patch: the switch's `busy`, the speed's `held`, its words and its title must come out as the builder's do.

Beyond the table, what only the patch can get wrong: a hint set on a held speed must be taken off when the cell starts to work (a title left
behind would explain a plain figure as a held one, and an empty title would hide the row's own title from the pointer), and the speed of a
cell that stops must go with it.

topology-render.js is loaded for real with the real polling.js (so the number is written by the board's own formatTps, not by a copy of it);
the rest of the board is stubbed as in test_js_topology_render.py, and the words the pins expect are read out of static/js/i18n/en.js.

Run: python3 scripts/test_js_cell_speed_live.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _js_pins import run  # noqa: E402
from cell_speed_cases import CASES, HELP, LAST  # noqa: E402

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

if __name__ == "__main__":
    sys.exit(run("js cell-speed live", ".probe_cell_speed_live.tmp.mjs", PREAMBLE, PINS, STUBS))
