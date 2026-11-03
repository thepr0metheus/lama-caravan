#!/usr/bin/env python3
"""Снимок static/js/placement.js — где живёт модель: сколько от каждой карты, что в RAM.

Владелец, 2026-10-24, после того как :22018 и :22020 умерли по четыре раза на
«failed to allocate CUDA buffer»: «забить 5090, всю или часть 3090 и что-то
держать в RAM». Карта памяти в форме ячейки повторяет то, что сделает
llama.cpp (common/fit.cpp, b1141), и пишет поля ячейки, когда двигают ручку.

Пинится ЗНАЧЕНИЯМИ, у каждого утверждения есть отрицательный двойник:
  - порядок подгонки llama.cpp: сначала деление всех слоёв по свободной памяти,
    а если карта его не держит — заполнение с ПОСЛЕДНЕЙ карты назад;
  - что останавливает подгонку (FIT выключен, -ngl, --tensor-split, эксперты
    вручную) — тогда ячейка грузится как записано;
  - какие поля пишет каждая раскладка и каких НЕ трогает;
  - неизвестное (число слоёв, RAM машины) названо, а не нарисовано нулём.

Модуль грузится в node по-настоящему (scripts/_js_harness.mjs), i18n тоже
настоящий: ожидаемые строки берутся из static/js/i18n/en.js программно.

Запуск: python3 scripts/test_js_placement.py
"""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _node import find_node, node_search_paths, probe_args  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


PROBE = r"""
import "./_js_globals.mjs";
import { pathToFileURL } from "node:url";
const root = process.env.JS_ROOT;
const { PlacementPlan, PlacementPanel } = await import(pathToFileURL(root + "/placement.js").href);
const en = (await import(pathToFileURL(root + "/i18n/en.js").href)).default;
const fill = (s, args) => s.replace(/\{(\w+)\}/g, (m, k) => (k in args ? String(args[k]) : m));
// An element's text as the page shows it: what escapeHtml wrote, read back.
const shown = (s) => (s === null || s === undefined ? null
  : s.replaceAll("&quot;", '"').replaceAll("&#39;", "'").replaceAll("&lt;", "<").replaceAll("&gt;", ">").replaceAll("&amp;", "&"));
const r2 = (x) => Math.round(x * 100) / 100;

// The machine of the owner's case: a 3090 and a 5090, as the cell sees them.
const cards = [{ index: 0, name: "RTX 3090", freeGb: 23.6, totalGb: 24.0 }, { index: 1, name: "RTX 5090", freeGb: 31.3, totalGb: 31.8 }];
// Hermes-4-70B Q4_K_M with a 131k context: 39.6 GB of files, 21.3 GB of KV, 3.19 GB of buffers, 80 layers.
const hermes = { weightsGb: 39.6, kvGb: 21.3, batchGb: 3.19, layers: 80, experts: 0 };
const limitsOf = (o = {}) => PlacementPlan.limitsFrom({ cards, ...o });
const plan = (o = {}) => new PlacementPlan({ model: hermes, cards, limits: limitsOf(), ramFreeGb: 51, cores: 16, ...o });
const brief = (p) => {
  const placed = p.placed();
  return { layers: placed.cards.map((c) => c.layers), buffers: placed.cards.map((c) => r2(c.buffersGb)),
           totals: placed.cards.map((c) => r2(c.totalGb)), over: placed.cards.map((c) => c.over),
           ram: { layers: placed.ram.layers, weightsGb: r2(placed.ram.weightsGb), kvGb: r2(placed.ram.kvGb), short: placed.ram.short },
           onCards: placed.layersOnCards, verdict: placed.verdict };
};
const out = {};

out.known = {
  whole: plan().known, noLayers: plan({ model: { ...hermes, layers: 0 } }).known,
  noWeights: plan({ model: { ...hermes, weightsGb: 0 } }).known, noCards: plan({ cards: [] }).known,
  countedFitted: plan().counted, countedMoe: plan({ held: "moe" }).counted,
};

out.heldBy = Object.fromEntries([
  ["nothing", {}], ["fitOn", { fit: "1" }], ["fitOff", { fit: "0" }],
  ["ngl60", { nGpuLayers: "60" }], ["nglAll", { nGpuLayers: "all" }], ["nglAuto", { nGpuLayers: "auto" }],
  ["nglMinusOne", { nGpuLayers: "-1" }], ["nglEmpty", { nGpuLayers: "" }],
  ["split", { tensorSplit: "23.4,31.1" }], ["splitZeros", { tensorSplit: "0,0" }],
  ["moeN", { nCpuMoe: "20" }], ["moeZero", { nCpuMoe: "0" }], ["moeAll", { cpuMoe: "1" }], ["moeAllOff", { cpuMoe: "0" }],
  ["offBeforeLayers", { fit: "0", nGpuLayers: "60" }], ["layersBeforeSplit", { nGpuLayers: "60", tensorSplit: "1,3" }],
  ["splitBeforeMoe", { tensorSplit: "1,3", nCpuMoe: "4" }],
].map(([k, f]) => [k, PlacementPlan.heldBy(f)]));

out.held = {
  layers: [plan({ held: "layers", fixedLayers: 60 }).held, plan({ held: "layers", fixedLayers: 60 }).fixedLayers],
  layersClamped: plan({ held: "layers", fixedLayers: 999 }).fixedLayers,
  layersWithoutCount: plan({ held: "layers", fixedLayers: null }).held,
  split: [plan({ held: "split" }).held, plan({ held: "split" }).fixedLayers],
  off: plan({ held: "off" }).fixedLayers,
  inTensor: plan({ held: "split", mode: "tensor" }).held,
  stranger: plan({ held: "maybe" }).held,
  fitted: [plan().held, plan().fixedLayers, plan().fitted],
};

// Fitted, step 1: every layer dealt by the free memory leaves each card within its limit — llama.cpp keeps that split.
const small = { weightsGb: 20, kvGb: 2, batchGb: 1, layers: 40, experts: 0 };
out.stepOne = brief(plan({ model: small }));
// Fitted, step 3: the 3090 may take only 15.6 GB (an 8 GiB margin), so the split by free memory overflows it; llama.cpp
// fills the cards from the last one back. One GB per layer (36 + 4 over 40), 2 GB of buffers.
const unit = { weightsGb: 36, kvGb: 4, batchGb: 2, layers: 40, experts: 0 };
out.backToFront = brief(plan({ model: unit, limits: limitsOf({ fitTarget: "8192,1024" }) }));
// The owner's case: Hermes with llama.cpp's default margins.
out.hermes = brief(plan());
// The 3090 left out by its handle: it computes nothing and keeps no buffer, so the 5090 holds them all.
out.noneOnFirst = brief(plan({ limits: [0, limitsOf()[1]] }));

out.ram = {
  notReported: brief(plan({ ramFreeGb: null })),
  short: brief(plan({ ramFreeGb: 5 })),
  enough: brief(plan({ ramFreeGb: 51 })),
};
out.kv = {
  inRam: brief(plan({ model: small, kvOnCards: false })),
  onCards: brief(plan({ model: small, kvOnCards: true })),
};
out.tensor = {
  equal: brief(plan({ mode: "tensor", limits: limitsOf({ mode: "tensor" }) })),
  bySize: brief(plan({ mode: "tensor", parts: [24, 32], limits: limitsOf({ mode: "tensor", tensorSplit: "24,32" }) })),
  smallBySize: brief(plan({ model: small, mode: "tensor", parts: [24, 32], limits: limitsOf({ mode: "tensor", tensorSplit: "24,32" }) })),
};
out.heldPlaced = {
  layers60: brief(plan({ held: "layers", fixedLayers: 60 })),
  splitAll: brief(plan({ held: "split", parts: [1, 3] })),
  offAll: brief(plan({ held: "off" })),
  moe: brief(plan({ held: "moe" })),
};

out.fields = {
  fitted: plan().fields(),
  fittedFits: plan({ model: small }).fields(),
  fittedOneCard: new PlacementPlan({ model: small, cards: [cards[0]], limits: [22.6], ramFreeGb: 51, cores: 16 }).fields(),
  tensor: plan({ mode: "tensor", limits: limitsOf({ mode: "tensor", tensorSplit: "24,32" }), parts: [24, 32] }).fields(),
  tensorTiny: plan({ mode: "tensor", limits: [0.2, 30], parts: [0.2, 30] }).fields(),
  heldLayers: plan({ held: "layers", fixedLayers: 60 }).fields(),
  heldSplit: plan({ held: "split", parts: [1, 3] }).fields(),
  heldOff: plan({ held: "off", kvOnCards: false }).fields(),
  heldMoe: plan({ held: "moe" }).fields(),
};

out.margins = {
  default: plan().margins(),
  dragged: plan({ limits: [13.5, limitsOf()[1]] }).margins(),
  none: plan({ limits: [0, limitsOf()[1]] }).margins(),
  ceiling: plan({ limits: cards.map((c) => PlacementPlan.ceiling(c)) }).margins(),
};
out.limitsFrom = {
  empty: limitsOf().map(r2), one: limitsOf({ fitTarget: "512" }).map(r2), two: limitsOf({ fitTarget: "2048,512" }).map(r2),
  short: limitsOf({ fitTarget: "2048" }).map(r2), fewer: PlacementPlan.limitsFrom({ cards: [...cards, { index: 2, freeGb: 10 }], fitTarget: "2048,512" }).map(r2),
  belowFloor: limitsOf({ fitTarget: "0" }).map(r2), junk: limitsOf({ fitTarget: "x,-5" }).map(r2),
  reversed: PlacementPlan.limitsFrom({ cards: [...cards].reverse(), fitTarget: "2048,512" }).map(r2),
  tensorParts: limitsOf({ mode: "tensor", tensorSplit: "24,32" }).map(r2), tensorSmall: limitsOf({ mode: "tensor", tensorSplit: "10,12" }).map(r2),
  tensorNone: limitsOf({ mode: "tensor" }).map(r2), tensorMiscount: limitsOf({ mode: "tensor", tensorSplit: "1,2,3" }).map(r2),
};
out.fixedFrom = Object.fromEntries(["all", "MAX", "60", "999", "0", "auto", "", "-1", "x", " 12 "].map((v) => [`[${v}]`, PlacementPlan.fixedFrom(v, 80)]));

// The panel: a fake form that records what is written, and the facts the form would give.
const form = (fields) => {
  const writes = [];
  let changed = 0;
  return { writes, changed: () => changed, api: { get: (k) => fields[k] ?? "", set: (k, v) => { fields[k] = v; writes.push(k); }, changed: () => { changed += 1; } } };
};
const facts = (o = {}) => ({ model: hermes, cards, ramFreeGb: 51, ramTotalGb: 60.5, cores: 16, mode: "layer", ...o });
const panelOf = (fields, f = facts()) => { const fm = form(fields); return { fm, fields, panel: new PlacementPanel({ form: fm.api, facts: f }) }; };
const html = (fields, f) => panelOf(fields, f).panel.html();
const attrs = (h, name) => [...h.matchAll(new RegExp(`data-t="${name}"[^>]*?data-t-(?:state|id)="([^"]*)"`, "g"))].map((m) => m[1]);
const hooks = (h) => [...h.matchAll(/data-t="([a-z-]+)"/g)].map((m) => m[1]);
const text = (h, cls) => shown((h.match(new RegExp(`class="${cls}"[^>]*>([^<]*)<`)) || [null, null])[1]);
const base = { FIT_TARGET: "", TENSOR_SPLIT: "", N_GPU_LAYERS: "auto", KV_OFFLOAD: "1", FIT: "1", N_CPU_MOE: "", CPU_MOE: "0" };

const H = PlacementPanel.HOOKS;
out.html = {
  noModel: html({ ...base }, facts({ model: { ...hermes, weightsGb: 0 } })),
  noCards: html({ ...base }, facts({ cards: [] })),
  unknown: (() => { const h = html({ ...base }, facts({ model: { ...hermes, layers: 0 } }));
    return { state: attrs(h, H.panel), pill: shown((h.match(/class="place-pill unknown"[^>]*>([^<]*)</) || [])[1] ?? null), lanes: hooks(h).filter((x) => x === H.card).length }; })(),
  fitted: (() => { const h = html({ ...base });
    return { state: attrs(h, H.panel), cards: attrs(h, H.card), limits: attrs(h, H.limit), kv: attrs(h, H.kv), verdict: attrs(h, H.verdict),
             kvOn: (h.match(/class="place-kv-btn on" data-place-kv="([a-z]+)"/) || [])[1] ?? null, held: hooks(h).includes(H.held),
             ram: hooks(h).includes(H.ram), none: attrs(h, H.none), flags: (h.match(/data-place-flags>([^<]*)</) || [])[1] ?? null }; })(),
  tensor: (() => { const h = html({ ...base, SPLIT_MODE: "tensor", TENSOR_SPLIT: "24,32" }, facts({ mode: "tensor" }));
    return { state: attrs(h, H.panel), none: attrs(h, H.none), verdict: attrs(h, H.verdict),
             pill: shown((h.match(/data-t-state="over">([^<]*)</) || [])[1] ?? null),
             ram: shown(((h.match(/data-place-text>([^<]*)</g) || []).pop() ?? "").replace(/^data-place-text>|<$/g, "")) }; })(),
  heldSplit: (() => { const h = html({ ...base, TENSOR_SPLIT: "23.4,31.1" });
    return { state: attrs(h, H.panel), held: attrs(h, H.held), note: shown(((h.match(/class="place-held-text">([\s\S]*?)<\/p>/) || [])[1] ?? "").replace(/<\/?code>/g, "")), fit: hooks(h).includes(H.fit),
             code: h.includes("<code>TENSOR_SPLIT</code>"),
             verdict: attrs(h, H.verdict), pill: shown((h.match(/data-t-state="over">([^<]*)</) || [])[1] ?? null),
             flags: (h.match(/data-place-flags>([^<]*)</) || [])[1] ?? null }; })(),
  heldMoe: (() => { const h = html({ ...base, N_CPU_MOE: "20" });
    return { state: attrs(h, H.panel), held: attrs(h, H.held), lanes: hooks(h).filter((x) => x === H.card).length,
             verdict: hooks(h).includes(H.verdict), legend: h.includes("place-legend") }; })(),
  ramNotReported: (() => { const h = html({ ...base }, facts({ ramFreeGb: null }));
    const ramLane = h.slice(h.indexOf(`data-t="${H.ram}"`));
    return { size: (ramLane.match(/class="place-lane-size">([^<]*)</) || [])[1] ?? null, track: ramLane.split("place-lane-foot")[0].includes("place-track"),
             verdict: attrs(h, H.verdict) }; })(),
  escaped: (() => { const h = html({ ...base }, facts({ cards: [{ ...cards[0], name: '<b>x</b>' }, cards[1]] }));
    return { raw: h.includes("<b>x</b>"), escaped: h.includes("&lt;b&gt;x&lt;/b&gt;") }; })(),
  // Each part of a lane carries its words — what it is, then how much — and so does each part of the model's bar (1.3.657).
  words: (() => { const h = html({ ...base });
    const parts = (cls) => [...h.matchAll(new RegExp(`class="${cls} ([a-z0-9]+)" style="width:[\\d.]+%" title="[^"]*">((?:<span class="place-word">[^<]*</span>)*)</span>`, "g"))]
      .map((m) => [m[1], [...m[2].matchAll(/<span class="place-word">([^<]*)<\/span>/g)].map((w) => w[1])]);
    return { lanes: parts("place-seg"), sum: parts("place-sum-seg"),
             tiny: PlacementPanel.segHtml("kv", 0.005, "KV", 10), named: PlacementPanel.segHtml("weights", 2, "a <b>", 8) }; })(),
};

// What the panel writes, and what it leaves alone.
const act = (fields, f, run) => { const p = panelOf(fields, f); run(p.panel); return { fields: p.fields, writes: [...new Set(p.fm.writes)].sort(), changed: p.fm.changed() }; };
out.write = {
  drag: act({ ...base }, facts(), (p) => p.setLimit(0, 13.5)),
  all: act({ ...base, FIT_TARGET: "4096,4096" }, facts(), (p) => p.setLimit(1, PlacementPlan.ceiling(cards[1]))),
  kvHeld: act({ ...base, N_GPU_LAYERS: "60", FIT_TARGET: "2048,2048" }, facts(), (p) => p.setKv(false)),
  kvFitted: act({ ...base }, facts(), (p) => p.setKv(false)),
  fitHeld: act({ ...base, TENSOR_SPLIT: "23.4,31.1", N_CPU_MOE: "", FIT: "1" }, facts(), (p) => p.fitByLimits()),
  fitMoe: act({ ...base, N_CPU_MOE: "20", CPU_MOE: "1" }, facts(), (p) => p.fitByLimits()),
  dragHeld: act({ ...base, N_GPU_LAYERS: "60" }, facts(), (p) => p.setLimit(1, 20)),
  dragTensor: act({ ...base, SPLIT_MODE: "tensor", TENSOR_SPLIT: "24,32" }, facts({ mode: "tensor" }), (p) => p.setLimit(0, 12)),
};

// A card asked for more than it has: its lane is drawn as long as the ask, the excess hatched from the card's end.
out.over = (() => {
  const past = (h) => [...h.matchAll(/class="place-past" style="left:([\d.]+)%"/g)].map((m) => Number(m[1]));
  const keep = (h) => [...h.matchAll(/data-place-keep style="width:([\d.]+)%"/g)].map((m) => Number(m[1]));
  const tensor = html({ ...base, SPLIT_MODE: "tensor", TENSOR_SPLIT: "" }, facts({ mode: "tensor" }));
  const fitted = html({ ...base });
  const held = html({ ...base, N_GPU_LAYERS: "60", FIT_TARGET: "4096,4096" });
  const segsSum = (h) => h.split('data-t="' + H.card + '"').slice(1).map((lane) => [...lane.split("place-lane-foot")[0]
    .matchAll(/class="place-seg [a-z]+" style="width:([\d.]+)%"/g)].reduce((a, m) => a + Number(m[1]), 0));
  return { tensorPast: past(tensor), tensorSums: segsSum(tensor), fittedPast: past(fitted), fittedKeep: keep(fitted), heldKeep: keep(held),
           heldFlags999: PlacementPanel.flags(plan({ held: "layers", fixedLayers: 80 }), "999"), heldFlagsNone: PlacementPanel.flags(plan({ held: "layers", fixedLayers: 60 })) };
})();

// The threads the RAM lane says are the cell's own (THREADS), not the machine's cores.
out.threads = (() => {
  const ramText = (h) => { const lane = h.slice(h.indexOf(`data-t="${H.ram}"`)); return shown((lane.match(/data-place-text>([^<]*)</) || [])[1] ?? null); };
  const draw = (THREADS, f = facts()) => { const h = html({ ...base, THREADS }, f); return { text: ramText(h), button: h.includes(`data-t="${H.threads}"`) }; };
  return { one: draw("1"), all: draw("16"), none: draw(""), fits: draw("1", facts({ model: small })) };
})();
out.threadsWrite = act({ ...base, THREADS: "1", THREADS_BATCH: "1" }, facts(), (p) => p.setThreads(16));

out.flags = {
  fitted: PlacementPanel.flags(plan()), fittedKvRam: PlacementPanel.flags(plan({ kvOnCards: false })),
  oneCard: PlacementPanel.flags(new PlacementPlan({ model: small, cards: [cards[0]], limits: [22.6] })),
  tensor: PlacementPanel.flags(plan({ mode: "tensor", limits: limitsOf({ mode: "tensor", tensorSplit: "24,32" }), parts: [24, 32] })),
  layers: PlacementPanel.flags(plan({ held: "layers", fixedLayers: 60 })),
  split: PlacementPanel.flags(plan({ held: "split", parts: [23.4, 31.1] })),
  off: PlacementPanel.flags(plan({ held: "off" })),
};

// An MoE model (1.3.620): Qwen3-Coder-Next UD-Q4_K_XL as its header and its tensor list say — 46.2 GB of files, 43.69 of
// them its experts; the cache of its 12 attention layers at 262144 tokens of q8_0, 3.19 GB; 2 GB of buffers; 48 layers.
const next = { weightsGb: 46.2, expertsGb: 43.69, kvGb: 3.19, batchGb: 2.0, layers: 48, experts: 512 };
const briefMoe = (p) => {
  const placed = p.placed();
  return { ...brief(p), expertLayers: placed.ram.expertLayers, cardsKv: r2(placed.cards.reduce((a, c) => a + c.kvGb, 0)),
           weights: placed.cards.map((c) => r2(c.weightsGb)) };
};
const narrow = [limitsOf()[0], 20];
out.moe = {
  fits: briefMoe(plan({ model: next })),
  spill: briefMoe(plan({ model: next, limits: narrow })),
  deficit: briefMoe(plan({ model: next, limits: [3, 4] })),
  unknown: briefMoe(plan({ model: { ...next, expertsGb: 0 }, limits: narrow })),
  kvRam: briefMoe(plan({ model: next, limits: [10, 12], kvOnCards: false })),
  held: briefMoe(plan({ model: next, held: "layers", fixedLayers: 40 })),
  tensor: briefMoe(plan({ model: next, mode: "tensor", limits: limitsOf({ mode: "tensor" }) })),
  known: [plan({ model: next }).expertsKnown, plan({ model: { ...next, expertsGb: 0 } }).expertsKnown,
          plan({ model: { ...next, experts: 0 } }).expertsKnown, plan({ model: { ...next, expertsGb: 46.2 } }).expertsKnown],
};
// What the map says of it: the RAM lane and the verdict, drawn by the panel for the plan.
const moeText = (p) => {
  const panel = panelOf({ ...base }, facts({ model: p.model })).panel;
  const placed = p.placed();
  return { verdict: shown((panel.verdictHtml(p, placed).match(/data-t-state="[a-zA-Z]+">([^<]*)</) || [])[1] ?? null),
           ram: shown((panel.ramInnerHtml(p, placed, 16).match(/data-place-text>([^<]*)</) || [])[1] ?? null),
           gb: PlacementPanel.gb(placed.ram.weightsGb), total: PlacementPanel.gb(placed.ram.totalGb) };
};
out.moeText = {
  spill: moeText(plan({ model: next, limits: narrow })),
  deficit: moeText(plan({ model: next, limits: [3, 4] })),
  unknown: moeText(plan({ model: { ...next, expertsGb: 0 }, limits: narrow })),
  fits: moeText(plan({ model: next })),
};
out.enMoe = { experts: en.placeRamExperts, layersExperts: en.placeRamLayersExperts, layers: en.placeRamLayers, none: en.placeRamNone,
  spillExperts: en.placeSpillExperts, spillDense: en.placeSpillDense, spillLayers: en.placeSpillLayers, fits: en.placeFits };

out.en = {
  placeOver: fill(en.placeOver, { layer: en.splitLayer }), placeOverHeld: fill(en.placeOverHeld, { fit: en.placeFitByLimits }),
  placeUnknown: en.placeUnknown, placeHeldSplit: fill(en.placeHeldSplit, { split: "23.4,31.1" }), placeRamNotReported: en.placeRamNotReported,
  placeRamTensor: en.placeRamTensor,
  cpuFew: fill(en.placeCpuFew, { n: 1, cores: 16 }), cpuAll: fill(en.placeCpuThreads, { n: 16 }), ramNone: en.placeRamNone,
  placeLegendOthers: en.placeLegendOthers, placeLegendWeights: en.placeLegendWeights, placeLegendBuffers: en.placeLegendBuffers,
};
console.log(JSON.stringify(out));
"""

node = find_node()
if node is None:
    print("js placement: SKIPPED — node не найден ни в PATH, ни у менеджеров версий: "
          + ", ".join(node_search_paths()))
    sys.exit(0)
probe = ROOT / "scripts" / ".probe_placement.tmp.mjs"
probe.write_text(PROBE, encoding="utf-8")
try:
    env = {"JS_ROOT": str(ROOT / "static" / "js"), "PATH": "/usr/bin:/bin",
           "JS_STUBS": "command-preview,favorites,llama-edit,form,remote-cells,cloud,topology-render,polling"}
    proc = subprocess.run(probe_args(node, ROOT / "scripts" / "_js_harness.mjs", probe), capture_output=True,
                          text=True, cwd=ROOT, env=env, timeout=60)
finally:
    probe.unlink(missing_ok=True)
if proc.returncode != 0:
    print("js placement: FAILED — харнесс не отработал")
    print(proc.stderr.strip()[:1200])
    sys.exit(1)
got = json.loads(proc.stdout.strip().splitlines()[-1])
en = got["en"]

print("MoE: в RAM — эксперты, а не целые слои (1.3.620):")
mo, mt, em = got["moe"], got["moeText"], got["enMoe"]


def fill_py(text, **kw):
    return re.sub(r"\{(\w+)\}", lambda m_: str(kw.get(m_.group(1), m_.group(0))), text)


check(mo["known"] == [True, False, False, False],
      "эксперты отделимы, только когда известен их вес; negative: вес не сказан, модель плотная, или вес — весь файл")
f_ = mo["fits"]
check(f_["verdict"] == "fits" and f_["layers"] == [20, 28] and f_["expertLayers"] == 0 and f_["ram"]["weightsGb"] == 0,
      f"Qwen3-Coder-Next на 3090 + 5090: всё на картах — 20 + 28 слоёв, как и вышло на живом запуске 24.10 (got {f_})")
sp = mo["spill"]
check(sp["verdict"] == "spill" and sp["expertLayers"] == 11 and sp["ram"]["layers"] == 0 and sp["layers"] == [20, 28]
      and sp["ram"]["weightsGb"] == 10.01,
      f"5090 до 20 ГБ: в RAM эксперты 11 слоёв (10.01 ГБ), а сами слои — на картах, все 48 (got {sp})")
check(sp["ram"]["kvGb"] == 0 and sp["cardsKv"] == 3.19,
      "negative: кэш KV остаётся с вниманием на картах — весь, 3.19 ГБ; раньше карта уносила в RAM и кэш этих слоёв")
de = mo["deficit"]
check(de["ram"]["layers"] == 7 and de["expertLayers"] == 41 and de["layers"] == [16, 25] and de["ram"]["weightsGb"] == 44.06,
      f"карты в 3 и 4 ГБ: не влезает даже остальное каждого слоя — 7 слоёв в RAM целиком и эксперты остальных 41 (got {de})")
un = mo["unknown"]
check(un["expertLayers"] == 0 and un["ram"]["layers"] == 10 and un["layers"] == [20, 18],
      f"negative: вес экспертов не сказан — модель рисуется плотной, 10 целых слоёв в RAM, без слов об экспертах (got {un})")
kr = mo["kvRam"]
check(kr["expertLayers"] == 30 and kr["ram"]["kvGb"] == 3.19 and kr["cardsKv"] == 0 and kr["ram"]["layers"] == 0,
      f"кэш в RAM по выбору: весь кэш там, и эксперты 30 слоёв (got {kr})")
check(mo["held"]["expertLayers"] == 0 and mo["held"]["ram"]["layers"] == 8 and mo["tensor"]["expertLayers"] == 0
      and mo["tensor"]["ram"]["layers"] == 0,
      "negative: -ngl числом и тензорный режим не подгоняются — эксперты не отделяются, слои ложатся целиком, как пишет ячейка")
check(mt["spill"]["ram"].startswith(fill_py(em["experts"], n=11, gb=mt["spill"]["gb"]))
      and mt["spill"]["verdict"] == fill_py(em["spillExperts"], n=11, total=48, gb=mt["spill"]["total"]),
      f"слова: «эксперты 11 слоёв» в полосе RAM и в вердикте (got {mt['spill']['ram']!r} / {mt['spill']['verdict']!r})")
check(mt["deficit"]["ram"].startswith(fill_py(em["layersExperts"], n=7, m=41, gb=mt["deficit"]["gb"]))
      and mt["deficit"]["verdict"] == fill_py(em["spillDense"], n=7, total=48, gb=mt["deficit"]["total"]),
      f"слова: 7 слоёв целиком и эксперты ещё 41 (got {mt['deficit']['ram']!r})")
check(mt["unknown"]["ram"].startswith(fill_py(em["layers"], n=10, gb=mt["unknown"]["gb"]))
      and mt["unknown"]["verdict"] == fill_py(em["spillLayers"], n=10, total=48, gb=mt["unknown"]["total"]),
      "negative: без веса экспертов слова о целых слоях, как и числа — не «эксперты» поверх целых слоёв")
check(mt["fits"]["ram"].startswith(em["none"]) and mt["fits"]["verdict"] == fill_py(em["fits"], total=48),
      "всё на картах: «ничего от модели» в RAM и вердикт «помещается»")

print("есть ли что раскладывать:")
kn = got["known"]
check(kn["whole"] and kn["countedFitted"], "модель с числом слоёв и карта — план есть, и его можно сосчитать")
check(not kn["noLayers"] and not kn["noWeights"] and not kn["noCards"],
      "negative: без числа слоёв, без файлов модели или без карты — плана нет (а не план из нулей)")
check(kn["countedMoe"] is False, "negative: эксперты, вынесенные вручную, план не считает — и говорит это, а не рисует догадку")

print("что останавливает подгонку llama.cpp (common/fit.cpp: «… already set by user, abort»):")
hb = got["heldBy"]
check(hb["nothing"] is None and hb["fitOn"] is None, "ничего не задано, FIT включён — llama.cpp подгоняет сам")
check(hb["fitOff"] == "off", "FIT выключен — подгонки нет вовсе")
check(hb["ngl60"] == "layers" and hb["nglAll"] == "layers", "-ngl числом или all — подгонка прерывается (n_gpu_layers already set by user)")
check(hb["nglAuto"] is None and hb["nglMinusOne"] is None and hb["nglEmpty"] is None,
      "negative: auto, -1 и пусто — это выбор самого llama.cpp, он подгоняет")
check(hb["split"] == "split", "--tensor-split в конвейере — подгонка прерывается (tensor_split already set by user)")
check(hb["splitZeros"] is None, "negative: доли из нулей — это «долей нет» (tensor_split[id] != 0.0f)")
check(hb["moeN"] == "moe" and hb["moeAll"] == "moe", "--n-cpu-moe и --cpu-moe — переопределения тензоров, подгонка прерывается")
check(hb["moeZero"] is None and hb["moeAllOff"] is None, "negative: --n-cpu-moe 0 и выключенный --cpu-moe ничего не переносят")
check(hb["offBeforeLayers"] == "off" and hb["layersBeforeSplit"] == "layers" and hb["splitBeforeMoe"] == "split",
      "несколько причин сразу — называется первая в том порядке, в каком их встречает llama.cpp: FIT, -ngl, доли, эксперты")
hd = got["held"]
check(hd["layers"] == ["layers", 60] and hd["layersClamped"] == 80, "-ngl 60 — 60 слоёв на картах; 999 — все 80, не больше, чем есть")
check(hd["split"] == ["split", 80] and hd["off"] == 80,
      "доли или выключенный FIT — -ngl auto без подгонки, а это у llama.cpp ВСЕ слои (n_gpu_layers() = n_layer + 1 при -1)")
check(hd["layersWithoutCount"] is None and hd["inTensor"] is None and hd["stranger"] is None,
      "negative: «-ngl» без числа, причина в тензорном режиме (там подгонки нет никогда) и незнакомое слово — не «удержано»")
check(hd["fitted"] == [None, None, True], "ничего не удерживает — план подгоняемый, число слоёв не задано")

print("подгонка — как llama.cpp (common/fit.cpp):")
s1 = got["stepOne"]
check(s1["layers"] == [17, 23] and s1["verdict"] == "fits",
      f"шаг 1: все 40 слоёв по свободной памяти (23.6 : 31.3 → 17 и 23) влезают в пределы карт — llama.cpp так и оставляет (получено {s1['layers']})")
bf = got["backToFront"]
check(bf["layers"] == [11, 29] and bf["ram"]["layers"] == 0 and bf["verdict"] == "fits",
      "шаг 3: деление по памяти переполняет 3090 (предел 15.6 ГБ), и карты заполняются С ПОСЛЕДНЕЙ: 5090 берёт 29 слоёв "
      f"(30.3 − 1 ГБ буферов), 3090 — оставшиеся 11 (получено {bf['layers']})")
check(bf["layers"] != [14, 26],
      "negative: не с первой карты — тогда было бы 14 на 3090 и 26 на 5090, а llama.cpp кладёт иначе («filling dense layers back-to-front»)")
he = got["hermes"]
check(he["layers"] == [27, 37] and he["ram"]["layers"] == 16 and he["verdict"] == "spill",
      "Hermes 70B со 131k контекста (0.76 ГБ на слой с его KV): 5090 — 37 слоёв, 3090 — 27, в RAM 16 — "
      f"llama.cpp сам выносит остаток, и ячейка стартует (получено {he['layers']} + {he['ram']['layers']})")
check(he["buffers"] == [1.6, 1.6] and not any(he["over"]),
      "буферы — поровну на каждую считающую карту (замер 70B: 1.1 и 1.0 ГБ сверх весов), и ни одна карта не перебрана")
nf = got["noneOnFirst"]
check(nf["layers"][0] == 0 and nf["buffers"] == [0, 3.19] and nf["layers"][1] == 35 and not any(nf["over"]),
      "3090 «Не брать»: она ничего не считает и буферов не держит, все 3.19 ГБ — на 5090, и слоёв там 35, а не 37: "
      f"карта не перебрана (получено {nf['layers']}, буферы {nf['buffers']})")

print("RAM машины:")
rm = got["ram"]
check(rm["short"]["verdict"] == "ramShort" and rm["short"]["ram"]["short"] is True,
      "в RAM уходит 12.2 ГБ, а свободно 5 — «не хватает RAM»")
check(rm["enough"]["verdict"] == "spill" and rm["enough"]["ram"]["short"] is False, "negative: свободно 51 ГБ — хватает, вердикт «запустится»")
check(rm["notReported"]["verdict"] == "spill" and rm["notReported"]["ram"]["short"] is False,
      "машина не сообщила RAM — нехватка не утверждается: неизвестное не рисуется отказом (было: 0 свободно → «не хватает»)")

print("кэш KV:")
kv = got["kv"]
check(kv["inRam"]["verdict"] == "kvRam" and kv["inRam"]["ram"]["kvGb"] == 2 and kv["inRam"]["ram"]["layers"] == 0,
      "весь кэш в RAM (--no-kv-offload): слои на картах, но это не «помещается» — свой жёлтый вердикт, внимание считает процессор")
check(kv["onCards"]["verdict"] == "fits" and kv["onCards"]["ram"]["kvGb"] == 0, "negative: кэш на картах — «помещается», в RAM ничего")

print("тензорный режим (подгонки нет, RAM нет):")
tn = got["tensor"]
check(tn["equal"]["totals"] == [32.05, 32.05] and tn["equal"]["over"] == [True, True] and tn["equal"]["verdict"] == "over",
      "без долей — ровно пополам (как режет llama.cpp): по 32 ГБ на карту, обе переполнены — «не поместится»")
check(tn["bySize"]["layers"] == [80, 80] and tn["bySize"]["ram"]["layers"] == 0,
      "каждая карта держит часть КАЖДОГО слоя, в RAM ничего (llama_params_fit is not implemented for SPLIT_MODE_TENSOR)")
check(tn["smallBySize"]["verdict"] == "fits"
      and abs(tn["smallBySize"]["totals"][0] / tn["smallBySize"]["totals"][1] - 23.35 / 31.05) < 0.02,
      f"с долями 24,32 части следуют долям (до потолка карты), маленькая модель помещается (получено {tn['smallBySize']['totals']})")

print("удержанный план — как записано:")
hp = got["heldPlaced"]
check(hp["layers60"]["layers"] == [26, 34] and hp["layers60"]["ram"]["layers"] == 20 and hp["layers60"]["verdict"] == "spill",
      f"-ngl 60: ровно 60 слоёв на карты, по свободной памяти (26 и 34), 20 в RAM (получено {hp['layers60']['layers']})")
check(hp["splitAll"]["layers"] == [20, 60] and hp["splitAll"]["verdict"] == "over" and hp["splitAll"]["ram"]["layers"] == 0,
      "доли 1,3 без подгонки: все 80 слоёв на карты по долям — 5090 переполнена, и в RAM llama.cpp ничего не вынесет")
check(hp["offAll"]["onCards"] == 80 and hp["offAll"]["verdict"] == "over",
      "FIT выключен: -ngl auto кладёт все слои на карты — у 70B со 131k это «не поместится», как и падали :22018/:22020")
check(hp["moe"]["verdict"] == "unknown" and hp["moe"]["layers"] == [] and hp["moe"]["onCards"] == 0,
      "эксперты вручную — «не знаю», без чисел (а не «0 слоёв на картах»)")

print("какие поля пишет раскладка — и каких не трогает:")
fd = got["fields"]
check(fd["fitted"] == {"KV_OFFLOAD": "1", "THREADS": "16", "THREADS_BATCH": "16", "N_CPU_MOE": "", "CPU_MOE": "0", "FIT": "1",
                       "SPLIT_MODE": "layer", "TENSOR_SPLIT": "", "N_GPU_LAYERS": "auto", "FIT_TARGET": "1024,1024"},
      f"подгонка: число слоёв и доли — пустые (llama.cpp подгоняет только незаданное), запасы карт в --fit-target, потоки — все ядра, раз в RAM есть слои (получено {fd['fitted']})")
check(fd["fittedFits"]["THREADS"] == "1" and fd["fittedFits"]["THREADS_BATCH"] == "1",
      "negative: всё на картах — один поток, как у плитки GPU")
check(fd["fittedOneCard"]["SPLIT_MODE"] == "" and fd["fittedOneCard"]["FIT_TARGET"] == "1024",
      "одна карта — режим деления не пишется, один запас")
check(fd["tensor"]["SPLIT_MODE"] == "tensor" and fd["tensor"]["TENSOR_SPLIT"] == "23.4,31.1" and fd["tensor"]["FIT_TARGET"] == ""
      and fd["tensor"]["N_GPU_LAYERS"] == "auto",
      f"тензор: доли — ГБ каждой карты, с десятыми, не больше её потолка (24,32 → 23.4,31.1), запасов нет (получено {fd['tensor']['TENSOR_SPLIT']})")
check(fd["tensorTiny"]["TENSOR_SPLIT"].startswith("1,"), "доля меньше 1 ГБ поднимается до 1: ноль llama.cpp не режет, а карту убирают фишками карт")
check(sorted(fd["heldLayers"]) == ["KV_OFFLOAD", "N_GPU_LAYERS", "THREADS", "THREADS_BATCH"] and fd["heldLayers"]["N_GPU_LAYERS"] == "60",
      "-ngl вручную: пишутся только кэш, потоки и то же -ngl 60")
check(not {"FIT_TARGET", "TENSOR_SPLIT", "N_CPU_MOE", "SPLIT_MODE"} & set(fd["heldLayers"]),
      "negative: удержанный план не трогает ни запасы, ни доли, ни экспертов — переключатель кэша не снимает ручной -ngl (был дефект)")
check(sorted(fd["heldSplit"]) == ["KV_OFFLOAD", "THREADS", "THREADS_BATCH"] and sorted(fd["heldOff"]) == ["KV_OFFLOAD", "THREADS", "THREADS_BATCH"]
      and fd["heldOff"]["KV_OFFLOAD"] == "0",
      "доли или выключенный FIT: только кэш и потоки, причину снимает лишь «Подогнать по ручкам» или сдвинутая ручка")
check(fd["heldMoe"] == {"KV_OFFLOAD": "1"},
      "negative: эксперты вручную — только кэш: потоки шли бы за частью в RAM, которую план не знает")

print("запасы (--fit-target) и пределы:")
mg = got["margins"]
check(mg["default"] == [1024, 1024], "пределы по умолчанию — запас llama.cpp, 1024 МиБ")
check(mg["dragged"] == [10342, 1024], "3090 «брать до 13.5 ГБ» из 23.6 свободных — запас 10342 МиБ")
check(mg["none"][0] == round(23.6 * 1024), "«Не брать» — запас во всю свободную память: llama.cpp не кладёт туда ни слоя")
check(mg["ceiling"] == [256, 256], "negative: «Всю» — не ноль запаса, а 256 МиБ: контекст CUDA и зазоры между буферами")
lf = got["limitsFrom"]
check(lf["empty"] == [22.6, 30.3] and lf["one"] == [23.1, 30.8], "без --fit-target — 1024 МиБ на карту; одно число — запас КАЖДОЙ карты, как читает llama.cpp")
check(lf["two"] == [21.6, 30.8] and lf["short"] == [21.6, 29.3], "два числа — по картам; одно число на две — у обеих")
check(lf["fewer"] == [21.6, 30.8, 9.0], "чисел меньше, чем карт, — недостающим запас llama.cpp по умолчанию")
check(lf["belowFloor"] == [23.35, 31.05], "negative: запас 0 не даёт карту целиком — пол 256 МиБ")
check(lf["junk"] == [22.6, 30.3], "negative: мусор в поле — как пусто, а не NaN в пределах")
check(lf["reversed"] == lf["two"], "карты в обратном порядке отчёта — пределы всё равно по номерам карт, как их видит llama.cpp")
check(lf["tensorParts"] == [23.35, 31.05] and lf["tensorSmall"] == [10.0, 12.0],
      "тензор: доли поля, но не больше потолка карты")
check(lf["tensorNone"] == [23.35, 23.35] and lf["tensorMiscount"] == [23.35, 23.35],
      "тензор без долей или с долями на другое число карт — поровну, по меньшей карте")
ff = got["fixedFrom"]
check(ff["[all]"] == 80 and ff["[MAX]"] == 80 and ff["[60]"] == 60 and ff["[999]"] == 80 and ff["[0]"] == 0 and ff["[ 12 ]"] == 12,
      "-ngl: all/max — все слои, число — оно (не больше числа слоёв), 0 — ни одного")
check(all(ff[k] is None for k in ("[auto]", "[]", "[-1]", "[x]")), "negative: auto, пусто, -1 и мусор — не число слоёв, а подгонка")

print("панель — что рисуется:")
ht = got["html"]
check(ht["noModel"] == "" and ht["noCards"] == "", "без модели или без карты — ничего: раскладывать нечего")
check(ht["unknown"]["state"] == ["unknown"] and ht["unknown"]["pill"] == en["placeUnknown"] and ht["unknown"]["lanes"] == 0,
      "модель есть, а число слоёв неизвестно — панель говорит это серой плашкой (placeUnknown), а не исчезает молча")
fh = ht["fitted"]
check(fh["state"] == ["fitted"] and fh["cards"] == ["0", "1"] and fh["limits"] == ["0", "1"] and fh["none"] == ["0", "1"]
      and fh["ram"] and fh["verdict"] == ["spill"],
      "подгонка: дорожка и ручка у каждой карты (data-t-id — номер карты), «Не брать», дорожка RAM, вердикт «запустится»")
check(fh["kv"] == ["cards", "ram"] and fh["kvOn"] == "cards" and fh["held"] is False,
      "кэш KV — две кнопки, горит «на картах»; заметки «удержано» нет")
check(fh["flags"] == "--split-mode layer --fit on --fit-target 1024,1024", "в команду — подгонка с запасами карт")
th = ht["tensor"]
check(th["state"] == ["tensor"] and th["none"] == [] and th["verdict"] == ["over"] and th["pill"] == en["placeOver"]
      and "{" not in th["pill"] and th["ram"] == en["placeRamTensor"],
      "тензор: без «Не брать» (ноль долей llama.cpp не режет), «не поместится» с советом выбрать конвейер ПО ЕГО ИМЕНИ на экране, RAM — «ничего»")
hs = ht["heldSplit"]
check(hs["state"] == ["held"] and hs["held"] == ["split"] and hs["note"] == en["placeHeldSplit"] and hs["fit"] and hs["code"],
      "конвейер с оставшимися от тензора долями: заметка называет доли и что llama.cpp тогда не подгоняет, с кнопкой «Подогнать по ручкам»")
check(hs["verdict"] == ["over"] and hs["pill"] == en["placeOverHeld"] and hs["pill"] != en["placeOver"],
      "negative: и вердикт ведёт к кнопке «Подогнать по ручкам», а не к «выберите конвейер» — он уже выбран")
check(hs["flags"] == "--split-mode layer --tensor-split 23.4,31.1", "в команду — то, что удерживает план")
hm = ht["heldMoe"]
check(hm["state"] == ["held"] and hm["held"] == ["moe"] and hm["lanes"] == 0 and hm["verdict"] is False and hm["legend"] is False,
      "эксперты вручную: только заметка и кнопка — ни дорожек, ни вердикта, ни легенды: план этого не считает")
rn = ht["ramNotReported"]
check(rn["size"] == en["placeRamNotReported"] and rn["track"] is False and rn["verdict"] == ["spill"],
      "RAM не сообщена: так и написано, шкалы без масштаба нет, вердикт не «не хватает»")
check(ht["escaped"]["raw"] is False and ht["escaped"]["escaped"] is True, "имя карты экранируется — разметкой из отчёта машины панель не подменишь")
wd = ht["words"]
check([kind for kind, _ in wd["lanes"]].count("weights") >= 2 and all(len(words) == 2 and words[1].endswith("GB") for _, words in wd["lanes"])
      and {kind: words[0] for kind, words in wd["lanes"]} == {"others": en["placeLegendOthers"], "weights": en["placeLegendWeights"],
                                                               "kv": "KV", "buffers": en["placeLegendBuffers"]},
      f"1.3.657 (слово владельца 2026-10-26: «если вмещается — подписывать, что это, модель или кв кэш»): в каждой части полосы — что "
      f"это и сколько, по два слова: веса, KV, буферы, другие процессы; цвет полосы — её карты, и только слова говорят, что это "
      f"(got {wd['lanes'][:4]})")
check([words[0] for _, words in wd["sum"]][:2] == ["GPU0", "GPU1"] and all(len(words) == 2 for _, words in wd["sum"]),
      "полоса модели — те же слова: устройство и сколько; negative: порога в 14% больше нет — что влезает, решает браузер")
check(wd["tiny"] == "" and "a &lt;b&gt;" in wd["named"] and "<b>" not in wd["named"],
      "negative: часть меньше 0,01 ГБ не рисуется; слова экранируются")

print("панель — что пишет:")
wr = got["write"]
dr = wr["drag"]
check(dr["fields"]["FIT_TARGET"] == "10342,1024" and dr["fields"]["N_GPU_LAYERS"] == "auto" and dr["fields"]["TENSOR_SPLIT"] == ""
      and dr["changed"] == 1,
      "ручка 3090 на 13.5 ГБ — запас 10342 МиБ, подгонку решает llama.cpp; форма перерисована один раз")
check(wr["all"]["fields"]["FIT_TARGET"] == "4096,256", "«Всю» на 5090 — её запас 256 МиБ, у 3090 остаётся записанный 4096")
kh = wr["kvHeld"]
check(kh["fields"]["N_GPU_LAYERS"] == "60" and kh["fields"]["KV_OFFLOAD"] == "0" and kh["fields"]["FIT_TARGET"] == "2048,2048",
      "кэш в RAM при -ngl 60 вручную: -ngl остаётся 60, запасы — как были")
check("FIT_TARGET" not in kh["writes"] and "TENSOR_SPLIT" not in kh["writes"],
      "negative: переключатель кэша не переписывает ни запасы, ни доли удержанного плана")
check(wr["kvFitted"]["fields"]["KV_OFFLOAD"] == "0" and wr["kvFitted"]["fields"]["FIT_TARGET"] == "1024,1024",
      "кэш в RAM при подгонке: подгонка остаётся, с теми же запасами")
fh2 = wr["fitHeld"]
check(fh2["fields"]["TENSOR_SPLIT"] == "" and fh2["fields"]["N_GPU_LAYERS"] == "auto" and fh2["fields"]["FIT"] == "1"
      and fh2["fields"]["FIT_TARGET"] == "1024,1024",
      "«Подогнать по ручкам» при оставшихся долях: доли сняты, -ngl auto, FIT включён — llama.cpp снова подгоняет")
fm = wr["fitMoe"]
check(fm["fields"]["N_CPU_MOE"] == "" and fm["fields"]["CPU_MOE"] == "0" and fm["fields"]["FIT"] == "1",
      "«Подогнать по ручкам» при экспертах вручную — эксперты отдаются подгонке llama.cpp")
check(wr["dragHeld"]["fields"]["N_GPU_LAYERS"] == "auto",
      "сдвинутая ручка при -ngl вручную — это просьба подогнать по ручкам: -ngl снимается")
dt = wr["dragTensor"]
check(dt["fields"]["TENSOR_SPLIT"] == "12,31.1" and dt["fields"]["SPLIT_MODE"] == "tensor" and dt["fields"]["FIT_TARGET"] == "",
      f"тензор: ручка 3090 на 12 ГБ — доли 12,31.1, режим остаётся тензорным (получено {dt['fields']['TENSOR_SPLIT']})")

print("карта, которой дали больше, чем у неё есть:")
ov = got["over"]
check([round(x, 1) for x in ov["tensorPast"]] == [74.0, 97.7] and all(abs(s - 100) < 0.1 for s in ov["tensorSums"]),
      "тензор пополам: 3090 просят 32 ГБ при 24 — дорожка длиннее карты, лишнее заштриховано красным от её конца (74 % дорожки), "
      f"5090 — с 97,7 %; сегменты укладываются в дорожку, а не обрезаются её краем (получено {ov['tensorPast']}, суммы {ov['tensorSums']})")
check(ov["fittedPast"] == [], "negative: подогнанная модель ни одной карты не переполняет — красной штриховки нет")
check(all(k > 0 for k in ov["fittedKeep"]) and ov["heldKeep"] == [0.0, 0.0],
      "«остаётся свободным» — только при подгонке: ручка удержанного плана llama.cpp ничего не оставляет (там зона была бы неправдой)")
check(ov["heldFlags999"] == "--n-gpu-layers 999" and ov["heldFlagsNone"] == "--n-gpu-layers 60",
      "строка команды — -ngl как в поле: 999, а не 48 слоёв, в которые он превращается; поле не дали — число слоёв")

print("потоки, которыми считается часть в RAM:")
th = got["threads"]
check(th["one"]["text"].endswith(en["cpuFew"]) and th["one"]["button"] is True,
      "THREADS 1 (так пишет плитка GPU), а 16 слоёв в RAM: строка говорит «только 1 из 16 потоков» и предлагает кнопку «Взять 16» — "
      "на живой доске она писала «8 потоков», пока ячейка считала RAM одним (2026-10-24)")
check(th["all"]["text"].endswith(en["cpuAll"]) and th["all"]["button"] is False,
      "negative: THREADS 16 из 16 — обычная строка, кнопки нет")
check(th["none"]["text"].endswith(en["cpuAll"]) and th["none"]["button"] is False,
      "THREADS не задан — llama.cpp берёт ядра машины, так и сказано, кнопки нет")
check(th["fits"]["text"] == en["ramNone"] and th["fits"]["button"] is False,
      "negative: в RAM ничего — о процессоре ни слова, и THREADS 1 не беда")
tw = got["threadsWrite"]
check(tw["writes"] == ["THREADS", "THREADS_BATCH"] and tw["fields"]["THREADS"] == "16" and tw["fields"]["THREADS_BATCH"] == "16" and tw["changed"] == 1,
      "кнопка пишет ровно THREADS и THREADS_BATCH = ядрам машины, остальное не трогает")

print("команда:")
fl = got["flags"]
check(fl["fitted"] == "--split-mode layer --fit on --fit-target 1024,1024" and fl["fittedKvRam"].endswith(" --no-kv-offload"),
      "подгонка; кэш в RAM добавляет --no-kv-offload")
check(fl["oneCard"] == "--fit on --fit-target 1024", "negative: одна карта — без --split-mode")
check(fl["tensor"] == "--split-mode tensor --tensor-split 23.4,31.1", "тензор — с долями")
check(fl["layers"] == "--n-gpu-layers 60" and fl["split"] == "--split-mode layer --tensor-split 23.4,31.1" and fl["off"] == "--fit off",
      "удержанный план показывает то, что его удерживает")

print("ручка поверх дорожки — прозрачная и в окне ячейки (стили static/css):")
from _css_rules import CssRules  # noqa: E402
css_rules = [rule for path in sorted((ROOT / "static" / "css").glob("*.css")) for rule in CssRules.rules(path.read_text(encoding="utf-8"))]
handle = [(sel, decl) for sel, decl in css_rules if CssRules.subject(sel).endswith('input.place-handle[type="range"]')]
check(len(handle) == 1 and handle[0][1].get("background") == "transparent" and handle[0][1].get("border") == "0"
      and handle[0][1].get("box-shadow") == "none" and handle[0][1].get("min-height") == "0",
      "у ручки своё правило: фон прозрачный, ни рамки, ни тени, без наименьшей высоты поля — сквозь неё видно, что держит карта")
# The rules that can reach the handle: on an input of the window or any input, not those of a checkbox or another type.
window_inputs = [(sel, decl) for sel, decl in css_rules
                 if CssRules.subject(sel).startswith("input") and ("topo-edit-form" in sel or sel == "input")
                 and not re.search(r'input\[type="(?!range)', sel) and {"background", "border", "height", "box-shadow"} & set(decl)]
heavier = [sel for sel, _ in window_inputs if handle and CssRules.specificity(sel) >= CssRules.specificity(handle[0][0])]
check(bool(window_inputs) and handle and heavier == [],
      f"и оно весомее всех правил, что красят поля окна ячейки ({len(window_inputs)}: `input, select`, `.topo-edit-form input:not(...)` и их :focus)"
      + (f" — сильнее: {heavier}" if heavier else ""))
check(any(CssRules.specificity(".place-handle") < CssRules.specificity(sel) for sel, _ in window_inputs),
      "negative: один класс `.place-handle` им проигрывал — на живой доске ручка закрывала дорожку непрозрачным полем (2026-10-24)")

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail:
        print("  - " + m)
    sys.exit(1)
print("js placement OK: подгонка llama.cpp, удержанные планы, тензор, поля и панель")
