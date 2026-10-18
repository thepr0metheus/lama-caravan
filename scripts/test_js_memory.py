#!/usr/bin/env python3
"""Snapshot of static/js/memory.js — "will the model fit", the number the operator trusts.

The memory estimator draws the OK / Near limit / Over VRAM pill on a cell's
card. A bug here is that exact class of defect, "absence drawn as normal": a
card already occupied by another model must not look free. VALUES are
pinned: comparison against FREE memory, not total; the margin boundaries at
exactly ±1 GB; summing two cards; "n/a" instead of zero; bytes per cache
element by quant type; the "CPU/GPU/auto" table per runner.

The module is loaded into node FOR REAL (scripts/_js_harness.mjs); i18n is real too.

Run: python3 scripts/test_js_memory.py
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT))
from _node import find_node, node_search_paths  # noqa: E402
from caravan.domain.runner import get as runner_get, registry_json  # noqa: E402

# Which card a Strata start lands on and what it needs free there: ONE table, run
# through the server's rule (runner.py vram_reservation) here and through the
# form's (memory.js FreeVramStart) in node — the two copies cannot drift apart
# without this going red.
CARD_GPUS = [{"index": 0, "memoryTotalMiB": 32607, "memoryFreeMiB": 13926},
             {"index": 1, "memoryTotalMiB": 24576, "memoryFreeMiB": 20000}]
CARD_CASES = [("", ""), ("CUDA_VISIBLE_DEVICES=1", ""), ("CUDA_VISIBLE_DEVICES=1\nCUDA_VISIBLE_DEVICES=0", ""),
              ('CUDA_VISIBLE_DEVICES="1"', ""), (" CUDA_VISIBLE_DEVICES = 1 ", ""), ("CUDA_VISIBLE_DEVICES=", ""),
              ("CUDA_VISIBLE_DEVICES=0,1", ""), ("X=CUDA_VISIBLE_DEVICES=1", ""), ("CUDA_VISIBLE_DEVICES=5", ""),
              ("CUDA_VISIBLE_DEVICES=GPU-3f2a", ""), ("CUDA_VISIBLE_DEVICES=00", ""), ("# CUDA_VISIBLE_DEVICES=1", ""),
              ("", "4096"), ("", " 512 "), ("", "2G")]


def server_card(env, reserve):
    r = runner_get("strata").vram_reservation({"ENV": env, "STRATA_VRAM_RESERVE_MIB": reserve}, CARD_GPUS)
    return None if r is None else [r["device"], r["reserveMiB"]]


def english(key, **kw):
    """A string of en.js, as the page shows it — read from the file, not copied."""
    import re
    raw = re.search(r'^  ' + key + r': (".*"),$', (ROOT / "static/js/i18n/en.js").read_text(encoding="utf-8"), re.M)
    text = json.loads(raw.group(1))
    for k, v in kw.items():
        text = text.replace("{" + k + "}", str(v))
    return text

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


PROBE = r"""
import "./_js_globals.mjs";
(globalThis.__stubReturns ||= {})["llama-edit.usesLlamaConfig"] = (id) => id === "llama-server" || id === "prism";
// The registry as the server sends it (runner.py registry_json) — the VRAM plan is read off it.
const REGISTRY = JSON.parse(process.env.RUNNERS_JSON);
globalThis.__stubReturns["llama-edit.runnerRegistry"] = () => REGISTRY;
// llama-edit is a stub here, so the helper that reads the fixed plan off the registry is restated; test_js_llama_edit.py
// pins the real one on its own table.
globalThis.__stubReturns["llama-edit.runnerFixedVramGb"] = (id) => { const mib = Number(REGISTRY.find((r) => r.id === id)?.vramPlan?.fixedMiB || 0); return mib > 0 ? mib / 1024 : 0; };
import { pathToFileURL } from "node:url";
// The machine the cell form targets: its cards and its RAM, as its scout
// reported them. Exported by remote-cells, which is a stub here — the values
// must exist before the import, and the object is mutated between runs.
const TR_CPU = { ram: { totalGb: 64, usedGb: 60 } };
const TR_GPUS = [{ index: 0, memoryTotalMiB: 8192, memoryFreeMiB: 8192, memoryUsedMiB: 0 }];
globalThis.__stubValues = { ...(globalThis.__stubValues || {}), "remote-cells._trClientCpu": TR_CPU,
  "remote-cells._trClientGpus": TR_GPUS };
const m = await import(pathToFileURL(process.env.JS_ROOT + "/memory.js").href);
// form.js is a stub: its model lookups answer as the real ones do with no model
// listed and none chosen, until a block below says otherwise.
Object.assign((globalThis.__stubReturns ||= {}), {
  "form.modelsByPath": () => new Map(),
  "form.modelChoiceOf": () => ({ model: "", mmproj: "", draft: "" }),
});
const g = (total, free, used) => ({ memoryTotalMiB: total, memoryFreeMiB: free, memoryUsedMiB: used });
const gx = (index) => ({ index, memoryTotalMiB: 24576, memoryFreeMiB: 24576, memoryUsedMiB: 0 });
const out = {
  size: Object.fromEntries([0, -1, NaN, "abc", 1.5, 12.34, 9.999, 10].map((v) => [String(v), m.formatSizeGb(v)])),
  cache: Object.fromEntries(["q8_0","Q8_0","q6_k","q5_1","q4_0","iq4_nl","f32","bf16","f16",null,"weird"].map((v) => [String(v), m.cacheBytesPerElement(v)])),
  free: [m.gpuFreeMiB(g(24576, 20000, 0)), m.gpuFreeMiB(g(24576, 0, 4096)), m.gpuFreeMiB(g(1000, 0, 5000)), m.gpuFreeMiB({})],
  fit: {
    noGpu: m._vramFitFrom([], 10),
    zeroRuntime: m._vramFitFrom([g(24576, 24576, 0)], 0),
    good: m._vramFitFrom([g(24576, 24576, 0)], 10),
    warn: m._vramFitFrom([g(24576, 24576, 0)], 23.5),
    bad: m._vramFitFrom([g(24576, 24576, 0)], 30),
    edgeMinus1: m._vramFitFrom([g(10240, 10240, 0)], 11),
    edgePlus1: m._vramFitFrom([g(10240, 10240, 0)], 9),
    freeNotTotal: m._vramFitFrom([g(24576, 4096, 20480)], 10),
    twoCards: m._vramFitFrom([g(12288, 12288, 0), g(12288, 12288, 0)], 20),
  },
  caps: Object.fromEntries(["vllm","whisper","moonshine","strata","gr00t","personaplex","lfm-audio","step-audio2","qwen3-omni","minicpm-omni","transcribe","seamless","translate","custom","llama-server","nonsense"].map((r) => [r, m.runnerDeviceCaps(r)])),
  // The device a one-device runner reports, whatever its ENV pins (llama-edit's
  // ENV reader is a stub here, made to read "cpu").
  mode: (() => {
    globalThis.__stubReturns["llama-edit._envDeviceState"] = () => "cpu";
    const got = Object.fromEntries(["vllm","whisper","moonshine","strata","gr00t","transcribe"].map((r) => {
      globalThis.__fields = { "tr-RUNNER": { value: r }, "tr-ENV": { value: "TTS_DEVICE=cpu\nCUDA_VISIBLE_DEVICES=" } };
      return [r, m.currentComputeMode("tr-")];
    }));
    delete globalThis.__stubReturns["llama-edit._envDeviceState"];
    return got;
  })(),
  // What the GPU tile WRITES. The split mode is decided in split-mode.js and
  // pinned there by value; what this pins is the wiring — that picking cards
  // is what applies it, and that one card leaves the flag unsaid.
  applied: await (async () => {
    const st = await import(pathToFileURL(process.env.JS_ROOT + "/state.js").href);
    st.setState({ gpu: { gpus: [gx(0), gx(1)] }, memory: { availableMiB: 65536 }, cpu: { physicalCores: 8, availableCores: 8 }, config: {} });
    st.setTopology(null);
    const run = (sel, before) => {
      globalThis.__fields = Object.fromEntries(
        ["N_GPU_LAYERS", "DEVICE", "MAIN_GPU", "SPLIT_MODE", "TENSOR_SPLIT", "THREADS", "THREADS_BATCH"]
          .map((k) => [k, { value: k === "SPLIT_MODE" ? before : "" }]));
      m.applyComputeTarget("", sel);
      return Object.fromEntries(["DEVICE", "MAIN_GPU", "SPLIT_MODE"].map((k) => [k, globalThis.__fields[k].value]));
    };
    return {
      bothBlank: run({ mode: "gpu", gpuIdx: [0, 1] }, ""),
      bothChosen: run({ mode: "gpu", gpuIdx: [0, 1] }, "layer"),
      oneCard: run({ mode: "gpu", gpuIdx: [1] }, "row"),
      cpu: run({ mode: "cpu" }, "row"),
    };
  })(),
  // WHERE the control is offered. The tile renders into an element, so the
  // element is faked and its innerHTML read back — the claim "only once two
  // cards are actually picked" is otherwise nobody's to check.
  tile: await (async () => {
    const st = await import(pathToFileURL(process.env.JS_ROOT + "/state.js").href);
    const shown = (gpus, device, ngl) => {
      st.setState({ gpu: { gpus }, memory: { availableMiB: 65536 }, cpu: { physicalCores: 8, availableCores: 8 }, config: {} });
      const box = { innerHTML: "", querySelectorAll: () => [], querySelector: () => null };
      globalThis.__fields = { computeTarget: box, DEVICE: { value: device },
                              N_GPU_LAYERS: { value: ngl }, SPLIT_MODE: { value: "row" } };
      m.refreshComputeTarget("");
      return box.innerHTML.includes("compute-split-seg");
    };
    const two = [gx(0), gx(1)];
    return {
      twoPicked: shown(two, "", "auto"),
      twoHostOnePicked: shown(two, "CUDA0", "auto"),
      oneCardHost: shown([gx(0)], "", "auto"),
      cpuMode: shown(two, "", "0"),
    };
  })(),
};
// The offload plan's RAM check: the weights that land in RAM against the RAM of
// the MACHINE the cell runs on — its scout's report — not the controller's.
{
  const st = await import(pathToFileURL(process.env.JS_ROOT + "/state.js").href);
  st.setState({ gpu: { gpus: [] }, memory: { availableMiB: 65536 }, cpu: {}, config: {} });
  (globalThis.__stubReturns ||= {})["form.modelsByPath"] = () => new Map([["m.gguf", { path: "m.gguf", sizeGb: 20, ggufMeta: { blockCount: 40 } }]]);
  // The form's word on the chosen model (form.js is a stub here): the field's value.
  globalThis.__stubReturns["form.modelChoiceOf"] = (pfx) => ({ model: globalThis.__fields[pfx + "MODEL_FILE"]?.value || "", mmproj: "", draft: "" });
  const plan = (usedGb) => {
    TR_CPU.ram.usedGb = usedGb;
    const box = { innerHTML: "", querySelectorAll: () => [], querySelector: () => null };
    globalThis.__fields = { "tr-offloadPlan": box, "tr-MODEL_FILE": { value: "m.gguf" }, "tr-N_GPU_LAYERS": { value: "10" } };
    try { m.refreshOffloadPlan("tr-"); } catch (e) { return "threw: " + e.message; }
    const readout = (box.innerHTML.match(/<div class="plan-readout( bad)?">/) || [])[1];
    return [box.innerHTML.includes("plan-readout"), readout === " bad"];
  };
  out.ramShort = { machineFull: plan(60), machineRoomy: plan(4) };
}
// Which model the estimate is of: the one the form names as chosen, and none
// while "+ Add model" awaits a pick — not the field with the config behind it.
// The aside's bar per runner, and a llama cell with no model chosen.
{
  const st = await import(pathToFileURL(process.env.JS_ROOT + "/state.js").href);
  const cst = await import(pathToFileURL(process.env.JS_ROOT + "/constants.js").href);
  st.setState({ gpu: { gpus: [] }, memory: { availableMiB: 65536 }, cpu: {}, config: { MODEL_FILE: "m.gguf" } });
  const choose = (model) => { globalThis.__stubReturns["form.modelChoiceOf"] = () => ({ model, mmproj: "", draft: "" }); };
  globalThis.__fields = { "tr-MODEL_FILE": { value: "" } };
  choose(""); out.rows = { awaited: m.selectedModelRows("tr-").selected?.path ?? null };
  choose("m.gguf"); out.rows.chosen = m.selectedModelRows("tr-").selected?.path ?? null;
  const calls = [];
  globalThis.__stubReturns["form.renderAsideVramBar"] = (...a) => { calls.push(a); };
  const aside = (runner, model) => {
    calls.length = 0;
    choose(model);
    globalThis.__fields = { "tr-RUNNER": { value: runner } };
    m.refreshAsidePanels("tr-");
    return calls.map((c) => c.slice());
  };
  out.aside = { llamaNone: aside("llama-server", ""), llamaModel: aside("llama-server", "m.gguf"),
                moonshine: aside("moonshine", ""), moonshineGb: cst.moonshineModelGb };
  // llama's own figure, handed in by renderModelInsight; Strata's from its plan,
  // on the 8 GB card of the machine; a pin to a card the machine has not.
  const drawn = (fields, llamaGb) => {
    calls.length = 0;
    choose("m.gguf");
    globalThis.__fields = fields;
    m.refreshAsidePanels("tr-", llamaGb);
    return calls.map((c) => c.slice());
  };
  out.aside.llamaFigure = drawn({ "tr-RUNNER": { value: "llama-server" } }, 37.2);
  out.aside.strata = drawn({ "tr-RUNNER": { value: "strata" }, "tr-ENV": { value: "" } }, 37.2);
  out.aside.strataNoCard = drawn({ "tr-RUNNER": { value: "strata" }, "tr-ENV": { value: "CUDA_VISIBLE_DEVICES=3" } }, 37.2);
  // GR00T's plan is the figure its policy was measured at, whatever llama's sum is.
  out.aside.gr00t = drawn({ "tr-RUNNER": { value: "gr00t" }, "tr-ENV": { value: "" } }, 37.2);
  out.fitGb = Object.fromEntries(["gr00t", "seamless"].map((r) => {
    globalThis.__fields = { "tr-RUNNER": { value: r } };
    return [r, m.computeFitRuntimeGb("tr-")];
  }));
}
// A start that takes its card's free VRAM: which card and how much it needs, for
// the cases the server's own rule is run on (runner.py vram_reservation) …
{
  const plan = REGISTRY.find((r) => r.id === "strata").vramPlan;
  const { gpus, cases } = JSON.parse(process.env.CARD_CASES);
  out.cards = cases.map(([env, reserve]) => {
    const s = m.FreeVramStart.of(plan, { env, reserve, gpus });
    return s ? [Number(s.card.index), s.needMiB] : null;
  });
  // … and where the scout lets it start (starts.py: free >= reserved), to the MiB.
  const at = (freeMiB, reserve) => {
    const s = m.FreeVramStart.of(plan, { env: "", reserve, gpus: [{ index: 0, memoryTotalMiB: 32607, memoryFreeMiB: freeMiB }] });
    return [s.fits, Math.round(s.addGb * 100) / 100];
  };
  out.freeStart = { roomy: at(13926, ""), roomyReserve: at(13926, "4096"), exact: at(6144, ""), short: at(6143, ""),
                    shortReserve: at(9000, "4096") };
  out.freeStartBar = m.FreeVramStart.of(plan, { env: "CUDA_VISIBLE_DEVICES=1", reserve: "4096",
    gpus: [{ index: 0, memoryFreeMiB: 1 }, { index: 1, memoryFreeMiB: 20000 }] }).bar();
}
// The CPU tile of a GPU-only runner is drawn and cannot be pressed.
out.cpuTileOff = Object.fromEntries(["strata", "gr00t", "vllm", "transcribe"].map((r) => {
  const box = { innerHTML: "", querySelectorAll: () => [], querySelector: () => null };
  globalThis.__fields = { "tr-computeTarget": box, "tr-RUNNER": { value: r }, "tr-ENV": { value: "" } };
  m.refreshComputeTarget("tr-");
  const cpu = (box.innerHTML.match(/<button[^>]*data-compute="cpu"[^>]*>/) || [""])[0];
  return [r, cpu ? /\sdisabled[\s"]/.test(cpu) : null];
}));
out.prismPlacement = ["0", "10"].map((layers) => {
  globalThis.__fields = {"tr-RUNNER": {value: "prism"}, "tr-N_GPU_LAYERS": {value: layers}};
  return m.currentComputeMode("tr-");
});

// A runner that runs on ONE card (the registry's oneCard) on a machine with two: the chips write the card's pin
// into its ENV, the tile and the estimate bar follow it, and a runner that is not one-card gets no chips.
{
  const st = await import(pathToFileURL(process.env.JS_ROOT + "/state.js").href);
  st.setState({ gpu: { gpus: [] }, memory: { availableMiB: 65536 }, cpu: {}, config: {} });
  const two = [{ index: 0, name: "NVIDIA GeForce RTX 3090", memoryTotalMiB: 24576, memoryFreeMiB: 24000, memoryUsedMiB: 576 },
               { index: 1, name: "NVIDIA GeForce RTX 5090", memoryTotalMiB: 32607, memoryFreeMiB: 27700, memoryUsedMiB: 4907 }];
  const setCards = (list) => { TR_GPUS.length = 0; TR_GPUS.push(...list.map((x) => ({ ...x }))); };
  const tile = (runner, env, cards = two) => {
    setCards(cards);
    const box = { innerHTML: "", querySelectorAll: () => [], querySelector: () => null };
    globalThis.__fields = { "tr-computeTarget": box, "tr-RUNNER": { value: runner }, "tr-ENV": { value: env } };
    m.refreshComputeTarget("tr-");
    const html = box.innerHTML;
    return { chips: [...html.matchAll(/<button type="button" class="compute-gpu-chip( on)?" data-pin-card="(\d+)"/g)].map((x) => [Number(x[2]), !!x[1]]),
             tile: (html.match(/data-compute="gpu"[^>]*>[\s\S]*?compute-card-main">([^<]*)</) || [])[1] ?? null,
             hook: /data-t="cell-remote-card" data-t-id="1"/.test(html) };
  };
  out.chips = {
    qwenNoPin: tile("qwen3-omni", ""), qwenPinned: tile("qwen3-omni", "CUDA_VISIBLE_DEVICES=1"),
    personaplexPinned: tile("personaplex", "FOO=1\nCUDA_VISIBLE_DEVICES=1"), strata: tile("strata", "CUDA_VISIBLE_DEVICES=1"), gr00t: tile("gr00t", ""),
    missingCard: tile("qwen3-omni", "CUDA_VISIBLE_DEVICES=7"), aList: tile("qwen3-omni", "CUDA_VISIBLE_DEVICES=0,1"),
    oneCardMachine: tile("qwen3-omni", "", [two[1]]), llama: tile("llama-server", ""), vllm: tile("vllm", "CUDA_VISIBLE_DEVICES=1"),
    custom: tile("custom", ""), transcribe: tile("transcribe", ""),
  };
  // The mode is read off the ENV for a runner that is not llama.cpp. A runner that CAN run on the CPU and is set to,
  // has no card to pick; none is registered like that today (every oneCard runner is gpuOnly), the rule is the form's
  // own and holds for the one that comes.
  REGISTRY.push({ id: "x-one-card", oneCard: true });
  globalThis.__stubReturns["llama-edit._envDeviceState"] = () => "gpu";
  out.chips.gpuMode = tile("x-one-card", "");
  globalThis.__stubReturns["llama-edit._envDeviceState"] = () => "cpu";
  out.chips.cpuMode = tile("x-one-card", "");
  delete globalThis.__stubReturns["llama-edit._envDeviceState"];
  REGISTRY.pop();
  // A click on a chip writes the pin, and the chips, the tile and the command preview follow it.
  {
    setCards(two);
    const previews = [];
    globalThis.__stubReturns["command-preview.renderCommandPreview"] = (...a) => { previews.push(a[0]); };
    const box = { innerHTML: "", querySelector: () => null, listeners: [] };
    box.querySelectorAll = (sel) => (sel === "[data-pin-card]"
      ? [0, 1].map((i) => ({ dataset: { pinCard: String(i) }, addEventListener: (ev, fn) => { if (ev === "click") box.listeners[i] = fn; } })) : []);
    globalThis.__fields = { "tr-computeTarget": box, "tr-RUNNER": { value: "qwen3-omni" }, "tr-ENV": { value: "FOO=1\nCUDA_VISIBLE_DEVICES=0" } };
    m.refreshComputeTarget("tr-");
    const before = globalThis.__fields["tr-ENV"].value;
    const tileOf = () => (box.innerHTML.match(/data-compute="gpu"[^>]*>[\s\S]*?compute-card-main">([^<]*)</) || [])[1] ?? null;
    const litOf = () => [...box.innerHTML.matchAll(/<button type="button" class="compute-gpu-chip( on)?" data-pin-card="(\d+)"/g)].filter((x) => x[1]).map((x) => Number(x[2]));
    previews.length = 0;
    box.listeners[1]({ preventDefault() {} });
    const after = globalThis.__fields["tr-ENV"].value, tileAfter = tileOf(), litAfter = litOf(), previewsAfter = previews.slice();
    box.listeners[0]({ preventDefault() {} });
    out.chipClick = { before, after, back: globalThis.__fields["tr-ENV"].value, tileAfter, litAfter, previews: previewsAfter, tileBack: tileOf(), litBack: litOf() };
    delete globalThis.__stubReturns["command-preview.renderCommandPreview"];
  }
  // The estimate bar of a fixed plan lands on the card the pin names, and says so exactly; a pin to a card the
  // machine has not draws it as before.
  const calls = [];
  globalThis.__stubReturns["form.renderAsideVramBar"] = (...a) => { calls.push(a); };
  const bar = (runner, env, cards = two) => {
    setCards(cards);
    calls.length = 0;
    globalThis.__fields = { "tr-RUNNER": { value: runner }, "tr-ENV": { value: env } };
    m.refreshAsidePanels("tr-");
    return calls.map((c) => c.slice(1));
  };
  out.cardBar = { noPin: bar("qwen3-omni", ""), pinned: bar("qwen3-omni", "CUDA_VISIBLE_DEVICES=1"), missing: bar("qwen3-omni", "CUDA_VISIBLE_DEVICES=7"),
                  aList: bar("qwen3-omni", "CUDA_VISIBLE_DEVICES=0,1"), vllm: bar("vllm", "CUDA_VISIBLE_DEVICES=1").map((c) => c.length) };
  // A runner that keeps its weights in the machine's memory (the registry's `keepsRam`: Strata) has a RAM plan too: the controller's answer for
  // the config the form holds, asked once (ram-plan.js). Here the asking holds the answer already; what is pinned is the wiring — the bar is told
  // the plan, one that promises nothing is told nothing, and only a runner that keeps RAM asks (1.3.574).
  {
    const rp = await import(pathToFileURL(process.env.JS_ROOT + "/ram-plan.js").href);
    const cfg = { RUNNER: "strata", MODEL_FILE: "x/IQ3_S/p-00001-of-00002.gguf" };
    globalThis.__stubReturns["form.readConfigForm"] = () => cfg;
    rp.RamPlanAsk.forms.clear();
    const ask = rp.RamPlanAsk.of("tr-");
    const asked = [];
    ask.timers = { setTimeout(fn) { asked.push(fn); return asked.length; }, clearTimeout() {} };    // nothing is really asked here
    ask.key = JSON.stringify(cfg);
    ask.plan = new rp.RamPlan(52531, 2048, "Strata");
    const told = (runner, env) => bar(runner, env).map(([gb, allow, opts]) => (opts && opts.ramPlan ? [opts.ramPlan.reserveMiB, opts.ramPlan.headroomMiB, Object.keys(opts).sort()] : null));
    out.ramWire = { strata: told("strata", "CUDA_VISIBLE_DEVICES=1"), omni: told("qwen3-omni", "CUDA_VISIBLE_DEVICES=1"), asking: [...rp.RamPlanAsk.forms.keys()] };
    ask.key = ""; ask.plan = null; asked.length = 0;
    out.ramUnknown = { strata: told("strata", "CUDA_VISIBLE_DEVICES=1"), asked: asked.length };
    delete globalThis.__stubReturns["form.readConfigForm"];
    rp.RamPlanAsk.forms.clear();
  }
  // The server's rule and the form's, one table: which card an ENV names.
  const { gpus, cases } = JSON.parse(process.env.CARD_CASES);
  out.pin = { card: cases.map(([env]) => { const d = m.CardPin.card(env); return d !== "" && gpus.some((x) => String(x.index) === d) ? Number(d) : null; }),
    write: ["", "FOO=1", "CUDA_VISIBLE_DEVICES=0", "A=1\nCUDA_VISIBLE_DEVICES=0\nB=2", "CUDA_VISIBLE_DEVICES=0,1", "# CUDA_VISIBLE_DEVICES=0", " CUDA_VISIBLE_DEVICES = 3 ", "A=1, CUDA_VISIBLE_DEVICES=0, B=2",
            "# the big card\nFOO=1"]
      .map((env) => m.CardPin.write(env, 1)) };
  out.label = [[], null, [{ name: "NVIDIA GeForce RTX 3090" }], [{ name: "NVIDIA GeForce RTX 3090" }, { name: "NVIDIA GeForce RTX 3090" }],
               [{ name: "NVIDIA GeForce RTX 3090" }, { name: "NVIDIA GeForce RTX 5090" }], [{}, { name: "NVIDIA GeForce RTX 5090" }],
               [{ name: "NVIDIA GeForce RTX 3090" }, { name: "NVIDIA GeForce RTX 5090" }, { name: "NVIDIA GeForce RTX 3090" }]].map((l) => m.machineGpuLabel(l));
}
// Two cards, one model (2026-10-17, the 70B of :22027 on a 3090 and a 5090): the KV cache, the room a running cell gives back, where
// "auto" lands, how the cards share the weights, and what the compute target writes for the split.
{
  const st = await import(pathToFileURL(process.env.JS_ROOT + "/state.js").href);
  st.setState({ gpu: { gpus: [] }, memory: { availableMiB: 65536 }, cpu: { physicalCores: 8, availableCores: 8 }, config: {} });
  const META = { blockCount: 80, headCount: 64, headCountKv: 8, embeddingLength: 8192 };
  const llama = { path: "m70.gguf", sizeGb: 39.6, ggufMeta: { ...META, keyLength: 128, valueLength: 128 } };
  const noKeyLength = { ...llama, ggufMeta: META };
  const round = (v, d = 3) => Math.round(v * 10 ** d) / 10 ** d;
  const kv = (row, ctx = "4096", kType = "q8_0", vType = kType) => {
    globalThis.__fields = { "tr-CTX_SIZE": { value: ctx }, "tr-CACHE_TYPE_K": { value: kType }, "tr-CACHE_TYPE_V": { value: vType } };
    return round(m.estimateKvCacheGb(row, "tr-"));
  };
  const mqa = (withLength) => ({ path: "q.gguf", ggufMeta: { blockCount: 32, headCount: 32, headCountKv: 1, embeddingLength: 4096, ...(withLength ? { keyLength: 128 } : {}) } });
  out.kv = {
    q8: kv(llama), f16: kv(llama, "4096", "f16"), mixed: kv(llama, "4096", "f16", "q8_0"), long: kv(llama, "131072"),
    withoutKeyLength: kv(noKeyLength), withoutKeyLengthF16: kv(noKeyLength, "4096", "f16"),
    mqaWith: kv(mqa(true)), mqaWithout: kv(mqa(false)),
    valueLengthAlone: kv({ path: "v.gguf", ggufMeta: { ...META, valueLength: 128 } }),
    noHeads: kv({ path: "x.gguf", ggufMeta: { blockCount: 32, embeddingLength: 4096, keyLength: 128 } }),
    noContext: kv(llama, "0"), noLayers: kv({ path: "y.gguf", ggufMeta: { headCount: 64, headCountKv: 8, keyLength: 128 } }),
    noMeta: kv({ path: "z.gguf" }),
  };

  // The machine as it reports itself WHILE the cell runs: 18.3 + 24.4 GB of 24.0 + 31.8 are the cell's own.
  const cards = () => [{ index: 0, name: "NVIDIA GeForce RTX 3090", memoryTotalMiB: 24576, memoryFreeMiB: 6208, memoryUsedMiB: 18368 },
                       { index: 1, name: "NVIDIA GeForce RTX 5090", memoryTotalMiB: 32607, memoryFreeMiB: 8243, memoryUsedMiB: 24364 }];
  const setCards = (list) => { TR_GPUS.length = 0; TR_GPUS.push(...list); };
  const slot = (phase, gpuMem) => ({ isSlot: true, port: 22027, phase, gpuMem });
  const cellIs = (s) => { globalThis.__stubReturns["llama-edit._commandCellSlot"] = () => s; };
  globalThis.__stubReturns["form.modelsByPath"] = () => new Map([["m70.gguf", llama]]);
  globalThis.__stubReturns["form.modelChoiceOf"] = () => ({ model: "m70.gguf", mmproj: "", draft: "" });
  const form = (extra = {}) => { globalThis.__fields = { "tr-MODEL_FILE": { value: "m70.gguf" }, "tr-N_GPU_LAYERS": { value: "auto" }, "tr-CTX_SIZE": { value: "4096" },
    "tr-CACHE_TYPE_K": { value: "q8_0" }, "tr-CACHE_TYPE_V": { value: "q8_0" }, "tr-BATCH_SIZE": { value: "1024" }, "tr-UBATCH_SIZE": { value: "1024" },
    "tr-SPLIT_MODE": { value: "layer" }, "tr-TENSOR_SPLIT": { value: "" }, "tr-DEVICE": { value: "" }, ...extra }; };
  const runtime = () => round(m.estimateRuntimeMemoryGb("tr-").runtimeSize, 2);
  setCards(cards());
  const running = slot("running", { 0: 18350, 1: 24364 });
  const holds = (s) => { cellIs(s); const h = m.cellHolds("tr-"); return { live: h.live, byCard: h.byCard, totalGb: round(h.totalGb, 2) }; };
  out.holds = { running: holds(running), warming: holds(slot("warming", { 0: 5 })), starting: holds(slot("starting", { 0: 5 })), stopped: holds(slot("stopped", { 0: 5 })),
                none: holds(null), noMem: holds(slot("running", undefined)), junk: holds(slot("running", { 0: "x", 1: 100 })) };
  cellIs(running);
  out.room = { running: setCards(cards()) ?? cards().map((g) => m.cellFreeMiB("tr-", g)) };
  cellIs(slot("stopped", {}));
  out.room.stopped = cards().map((g) => m.cellFreeMiB("tr-", g));
  out.room.otherPort = (() => { cellIs(null); return cards().map((g) => m.cellFreeMiB("tr-", g)); })();

  form();
  out.runtimeGb = runtime();
  const fit = (s) => { cellIs(s); form(); const f = m.vramFitForPfx(m.estimateRuntimeMemoryGb("tr-").runtimeSize, "tr-"); return [f.kind, (f.html.match(/\/ ([0-9.]+ GB) free/) || [])[1]]; };
  out.ownFit = { running: fit(running), stopped: fit(slot("stopped", {})), noCell: fit(null),
                 plainStillTwoArgs: m._vramFitFrom(cards(), 43.45).kind };
  const split = (s, extra = {}) => { cellIs(s); form(extra); const o = m.offloadSplit("tr-"); return { auto: o.autoLayers, onGpu: o.layersGpu, partial: o.partial,
    cards: o.perGpu.map((g) => [g.index, g.layers, round(g.gb, 1)]) }; };
  out.auto = { running: split(running), stopped: split(slot("stopped", {})), tensorStopped: split(slot("stopped", {}), { "tr-SPLIT_MODE": { value: "tensor" } }),
               tensorRunning: split(running, { "tr-SPLIT_MODE": { value: "tensor" } }) };
  out.cardsShare = {
    layer: split(running, { "tr-N_GPU_LAYERS": { value: "999" } }),
    tensorEven: split(running, { "tr-N_GPU_LAYERS": { value: "999" }, "tr-SPLIT_MODE": { value: "tensor" } }),
    tensorBySize: split(running, { "tr-N_GPU_LAYERS": { value: "999" }, "tr-SPLIT_MODE": { value: "tensor" }, "tr-TENSOR_SPLIT": { value: "24,32" } }),
    layerManual: split(running, { "tr-N_GPU_LAYERS": { value: "999" }, "tr-TENSOR_SPLIT": { value: "1,3" } }),
    rowFollowsRoom: split(running, { "tr-N_GPU_LAYERS": { value: "999" }, "tr-SPLIT_MODE": { value: "row" } }),
  };
  // A cell that sits mostly on ONE card: the cards report 6.1 and 27.3 GB free, the cell holds 18.0 and 4.5 of what they lack, so
  // each card has the room it reported plus its own share back — 24.0 and 31.8 GB — and the weights follow THAT.
  {
    setCards([{ index: 0, name: "NVIDIA GeForce RTX 3090", memoryTotalMiB: 24576, memoryFreeMiB: 6208, memoryUsedMiB: 18368 },
              { index: 1, name: "NVIDIA GeForce RTX 5090", memoryTotalMiB: 32607, memoryFreeMiB: 28000, memoryUsedMiB: 4607 }]);
    out.cardsShare.asymmetric = split(slot("running", { 0: 18350, 1: 4607 }), { "tr-N_GPU_LAYERS": { value: "999" } });
    out.cardsShare.asymmetricStopped = split(slot("stopped", {}), { "tr-N_GPU_LAYERS": { value: "999" } });
    setCards(cards());
  }

  // The plan panel: which tile is lit for what N_GPU_LAYERS says, and that "auto" reads the number offloadSplit worked out.
  const plan = (ngl, s = running) => {
    cellIs(s); form({ "tr-N_GPU_LAYERS": { value: ngl } });
    const box = { innerHTML: "", querySelectorAll: () => [], querySelector: () => null };
    globalThis.__fields["tr-offloadPlan"] = box;
    m.refreshOffloadPlan("tr-");
    const lit = (box.innerHTML.match(/class="compute-card active[^"]*" data-plan="([a-z]+)"/) || [])[1] ?? null;
    const autoMain = (box.innerHTML.match(/data-plan="auto"[^>]*>[\s\S]*?compute-card-main">([^<]*)</) || [])[1] ?? null;
    return { lit, autoMain, slider: box.innerHTML.includes("plan-slider") };
  };
  out.plan = { n999: plan("999"), n80: plan("80"), n79: plan("79"), all: plan("all"), manual40: plan("40"), runningAuto: plan("40", running).autoMain,
               stoppedAuto: plan("40", slot("stopped", {})).autoMain };

  // What the compute target writes: the split follows the mode, and the cards' sizes follow the split.
  const apply = (before, gpuIdx, cardList, ts = "") => {
    setCards(cardList); cellIs(null);
    globalThis.__fields = Object.fromEntries(["N_GPU_LAYERS", "DEVICE", "MAIN_GPU", "SPLIT_MODE", "TENSOR_SPLIT", "THREADS", "THREADS_BATCH"]
      .map((k) => ["tr-" + k, { value: k === "SPLIT_MODE" ? before : k === "TENSOR_SPLIT" ? ts : "" }]));
    m.applyComputeTarget("tr-", { mode: "gpu", gpuIdx });
    return ["SPLIT_MODE", "TENSOR_SPLIT"].map((k) => globalThis.__fields["tr-" + k].value);
  };
  const equal = [{ ...cards()[0], memoryTotalMiB: 24576 }, { ...cards()[1], index: 1, memoryTotalMiB: 24576 }];
  const three = [...cards(), { index: 2, name: "NVIDIA RTX A6000", memoryTotalMiB: 49152, memoryFreeMiB: 49000, memoryUsedMiB: 152 }];
  out.apply = {
    blank: apply("", [0, 1], cards()), layer: apply("layer", [0, 1], cards()), row: apply("row", [0, 1], cards()),
    tensor: apply("tensor", [0, 1], cards()), tensorEqualCards: apply("tensor", [0, 1], equal), tensorOneCard: apply("tensor", [1], cards()),
    tensorMachineListedBackwards: apply("tensor", [0, 1], [cards()[1], cards()[0]]),
    tensorKeepsNothingOfAnOldSplit: apply("tensor", [0, 1], cards(), "1,3"), tensorTwoOfThree: apply("tensor", [2, 0], three),
  };

  // The tile: a click on a mode moves the split that was written for the mode and leaves the one the operator typed.
  const click = (start, mode, cardList = cards()) => {
    setCards(cardList); cellIs(null);
    const listeners = {};
    const box = { innerHTML: "", querySelector: () => null };
    box.querySelectorAll = (sel) => (sel === "[data-split]" ? ["layer", "row", "tensor"].map((v) => ({ dataset: { split: v },
      addEventListener: (ev, fn) => { if (ev === "click") listeners[v] = fn; } })) : []);
    globalThis.__fields = { "tr-computeTarget": box, "tr-RUNNER": { value: "llama-server" }, "tr-N_GPU_LAYERS": { value: "auto" }, "tr-DEVICE": { value: "" },
      "tr-SPLIT_MODE": { value: start.mode }, "tr-TENSOR_SPLIT": { value: start.split } };
    m.refreshComputeTarget("tr-");
    listeners[mode]({ preventDefault() {} });
    return [globalThis.__fields["tr-SPLIT_MODE"].value, globalThis.__fields["tr-TENSOR_SPLIT"].value];
  };
  out.click = {
    blankToTensor: click({ mode: "", split: "" }, "tensor"), tensorToLayer: click({ mode: "tensor", split: "24,32" }, "layer"),
    tensorToRow: click({ mode: "tensor", split: "24,32" }, "row"), layerToTensor: click({ mode: "layer", split: "" }, "tensor"),
    ownSplitKeptOnTensor: click({ mode: "layer", split: "3,1" }, "tensor"), ownSplitKeptOnLayer: click({ mode: "tensor", split: "3,1" }, "layer"),
    equalCards: click({ mode: "layer", split: "" }, "tensor", equal),
    machineListedBackwards: click({ mode: "layer", split: "" }, "tensor", [cards()[1], cards()[0]]),
  };
}
// vLLM on a machine with two cards (2026-10-17, the Qwen3-Omni AWQ of 25.7 GB on a 3090 and a 5090): which cards it takes, what it
// asks of each, whether the weights fit, and what the tile and the bar say.
{
  const st = await import(pathToFileURL(process.env.JS_ROOT + "/state.js").href);
  st.setState({ gpu: { gpus: [] }, memory: { availableMiB: 65536 }, cpu: { physicalCores: 8, availableCores: 8 }, config: {} });
  const cards = () => [{ index: 0, name: "NVIDIA GeForce RTX 3090", memoryTotalMiB: 24576, memoryFreeMiB: 24000, memoryUsedMiB: 576 },
                       { index: 1, name: "NVIDIA GeForce RTX 5090", memoryTotalMiB: 32607, memoryFreeMiB: 32000, memoryUsedMiB: 607 }];
  const setCards = (list) => { TR_GPUS.length = 0; TR_GPUS.push(...list); };
  const round = (v, d = 2) => Math.round(v * 10 ** d) / 10 ** d;
  const awq = { path: "omni-awq", sizeGb: 25.66, ggufMeta: {} };
  globalThis.__stubReturns["form.modelsByPath"] = () => new Map([["omni-awq", awq], ["m205", { path: "m205", sizeGb: 20.5, ggufMeta: {} }], ["m207", { path: "m207", sizeGb: 20.7, ggufMeta: {} }]]);
  const field = (tp, util, env, model) => { globalThis.__stubReturns["form.modelChoiceOf"] = () => ({ model, mmproj: "", draft: "" });
    globalThis.__fields = { "tr-RUNNER": { value: "vllm" }, "tr-TENSOR_PARALLEL": { value: tp }, "tr-GPU_MEMORY_UTILIZATION": { value: util }, "tr-ENV": { value: env },
      "tr-MODEL_FILE": { value: model } }; };
  const place = (tp, util = "", env = "", model = "omni-awq", list = cards()) => { setCards(list); field(tp, util, env, model);
    const p = m.VllmPlacement.of("tr-");
    return { tp: p.tp, cards: p.indexes, each: p.perCardGb.map((g) => round(g)), total: round(p.totalGb), over: p.weightsOver, noted: p.note() !== "" }; };
  out.vllm = {
    default: place(""), one: place("1"), two: place("2"), twoLowUtil: place("2", "0.7"), three: place("3"), zero: place("0"), junk: place("x"), negative: place("-2"),
    fractional: place("1.5"), padded: place(" 2 "),
    pinned5090: place("1", "", "CUDA_VISIBLE_DEVICES=1"), pinnedMissing: place("1", "", "CUDA_VISIBLE_DEVICES=7"), pinnedList: place("1", "", "CUDA_VISIBLE_DEVICES=0,1"),
    pinIgnoredByTp: place("2", "", "CUDA_VISIBLE_DEVICES=1"),
    noModel: place("1", "", "", ""), unknownModel: place("1", "", "", "typed-repo-id"),
    oneCardMachine: place("1", "", "", "omni-awq", [cards()[1]]), tpOverMachine: place("4", "", "", "omni-awq", [cards()[0]]), noCards: place("2", "", "", "omni-awq", []),
    backwards: place("2", "", "", "omni-awq", [cards()[1], cards()[0]]),
    threeCardsTwoAsked: place("2", "", "", "omni-awq", [...cards(), { index: 2, name: "NVIDIA RTX A6000", memoryTotalMiB: 49152, memoryFreeMiB: 49000, memoryUsedMiB: 152 }]),
    badUtil: place("1", "abc"), zeroUtil: place("1", "0"),
    // the margin: 21.6 GB asked of the card, 1 GB of it kept for activations and graphs — 20.5 fits, 20.7 does not
    fitsByTheMargin: place("1", "", "", "m205"), overByTheMargin: place("1", "", "", "m207"),
  };
  // what the fit figure, the bar and the tile say for it
  const aside = (tp, env = "", util = "", model = "omni-awq") => { setCards(cards()); field(tp, util, env, model);
    const calls = []; globalThis.__stubReturns["form.renderAsideVramBar"] = (...a) => { calls.push(a); };
    m.refreshAsidePanels("tr-");
    delete globalThis.__stubReturns["form.renderAsideVramBar"];
    return calls.map((c) => [c[0], round(c[1]), c[2], { hard: c[3].hard, cards: c[3].cards, note: c[3].vramNote !== "" }]); };
  out.vllmBar = { one: aside("1"), two: aside("2"), pinned: aside("1", "CUDA_VISIBLE_DEVICES=1"), noModel: aside("1", "", "", ""), missing: aside("1", "CUDA_VISIBLE_DEVICES=7") };
  out.vllmFit = Object.fromEntries(["", "1", "2", "3"].map((tp) => { setCards(cards()); field(tp, "", "", "omni-awq"); return ["tp" + tp, round(m.computeFitRuntimeGb("tr-"))]; }));
  const tileOf = (tp, env = "", list = cards()) => { setCards(list); field(tp, "", env, "omni-awq");
    const box = { innerHTML: "", querySelectorAll: () => [], querySelector: () => null };
    globalThis.__fields["tr-computeTarget"] = box;
    m.refreshComputeTarget("tr-");
    const html = box.innerHTML;
    const main = (html.match(/data-compute="gpu"[^>]*>[\s\S]*?compute-card-main">([^<]*)</) || [])[1] ?? null;
    const sub = (html.match(/data-compute="gpu"[^>]*>[\s\S]*?compute-card-sub">([^<]*)</) || [])[1] ?? null;
    return { main, sub, chips: (html.match(/compute-gpu-chip/g) || []).length }; };
  out.vllmTile = { default: tileOf(""), one: tileOf("1"), two: tileOf("2"), pinned: tileOf("1", "CUDA_VISIBLE_DEVICES=1"), missing: tileOf("1", "CUDA_VISIBLE_DEVICES=7"),
                   oneCardMachine: tileOf("2", "", [cards()[1]]) };
  // the words under the bar are the string's own, with the figures in
  setCards(cards()); field("1", "", "", "omni-awq");
  out.vllmNote = new m.VllmPlacement(1, 0.9, [cards()[0]], 2, 25.66).note();
}
console.log(JSON.stringify(out));
"""

node = find_node()
if node is None:
    print("js memory: SKIPPED — node не найден ни в PATH, ни у менеджеров версий: " + ", ".join(node_search_paths()))
    sys.exit(0)
probe = ROOT / "scripts" / ".probe_memory.tmp.mjs"
probe.write_text(PROBE, encoding="utf-8")
try:
    hook = f"data:text/javascript,import {{ register }} from 'node:module'; register('file://{ROOT}/scripts/_js_harness.mjs');"
    env = {"JS_ROOT": str(ROOT / "static" / "js"), "PATH": "/usr/bin:/bin",
           "JS_STUBS": "command-preview,favorites,llama-edit,form,remote-cells,cloud,topology-render,polling",
           "RUNNERS_JSON": json.dumps(registry_json()),
           "CARD_CASES": json.dumps({"gpus": CARD_GPUS, "cases": CARD_CASES})}
    proc = subprocess.run([node, "--import", hook, str(probe)], capture_output=True, text=True, cwd=ROOT, env=env, timeout=60)
finally:
    probe.unlink(missing_ok=True)
if proc.returncode != 0:
    print("js memory: FAILED — харнесс не отработал"); print(proc.stderr.strip()[:800]); sys.exit(1)
got = json.loads(proc.stdout.strip().splitlines()[-1])

print("formatSizeGb:")
check(got["size"] == {"0": "n/a", "-1": "n/a", "NaN": "n/a", "abc": "n/a", "1.5": "1.50 GB",
                      "12.34": "12.3 GB", "9.999": "10.00 GB", "10": "10.0 GB"},
      f"n/a для нуля/мусора, два знака до 10 ГБ и один после (получено {got['size']})")
print("cacheBytesPerElement:")
check(got["cache"] == {"q8_0": 1.0625, "Q8_0": 1.0625, "q6_k": 0.8125, "q5_1": 0.7, "q4_0": 0.5625,
                       "iq4_nl": 0.5625, "f32": 4, "bf16": 2, "f16": 2, "null": 2, "weird": 2},
      f"байты на элемент по типу кванта, регистр не важен, неизвестное = f16 (получено {got['cache']})")
print("gpuFreeMiB:")
check(got["free"] == [20000, 20480, 0, 0],
      f"свободная берётся напрямую, иначе total−used, никогда не ниже нуля (получено {got['free']})")

print("_vramFitFrom:")
fit = got["fit"]
check(fit["noGpu"] == {"kind": "", "html": "<b>n/a</b>"}, "без карт — n/a, не «OK»")
check(fit["zeroRuntime"] == {"kind": "", "html": "<b>n/a</b>"}, "без размера — n/a, не «OK»")
check(fit["good"]["kind"] == "good" and "<b>10.0 GB</b> / 24.0 GB free" in fit["good"]["html"], "10 из 24 свободных — OK")
check(fit["warn"]["kind"] == "warn", "запас меньше 1 ГБ — Near limit")
check(fit["bad"]["kind"] == "bad" and "Over VRAM" in fit["bad"]["html"], "не влезает — Over VRAM")
check(fit["edgeMinus1"]["kind"] == "warn", "ровно −1 ГБ запаса — ещё Near limit, не Over")
check(fit["edgePlus1"]["kind"] == "good", "ровно +1 ГБ запаса — уже OK")
check(fit["freeNotTotal"]["kind"] == "bad" and "/ 4.00 GB free" in fit["freeNotTotal"]["html"],
      "карта с 24 ГБ, из которых свободно 4, — Over VRAM: сравнение со СВОБОДНОЙ, не с общей")
check(fit["twoCards"]["kind"] == "good" and "/ 24.0 GB free" in fit["twoCards"]["html"], "две карты по 12 суммируются в 24")

check(got["prismPlacement"] == ["cpu", "gpu"], "Prism читает размещение из N_GPU_LAYERS, а не ENV команды")
print("runnerDeviceCaps:")
caps = got["caps"]
check(caps["vllm"] == {"cpu": False, "gpu": True, "auto": False} and caps["whisper"] == caps["vllm"], "vllm и whisper — только GPU")
check(caps["moonshine"] == {"cpu": True, "gpu": False, "auto": False}, "moonshine — только CPU")
check(all(caps[r] == {"cpu": True, "gpu": True, "auto": False} for r in ("transcribe", "seamless", "translate")),
      "transcribe/seamless/translate — оба, без auto")
check(caps["custom"] == {"cpu": True, "gpu": True, "auto": True}, "custom — единственный с auto")
check(caps["llama-server"] == caps["nonsense"] == {"cpu": True, "gpu": True, "auto": False},
      "llama-server и неизвестный раннер — умолчание: оба, без auto")
check(caps["strata"] == {"cpu": False, "gpu": True, "auto": False},
      "defect-history: Strata — только GPU; раньше ей доставалось умолчание llama, и плитка CPU писала в ENV "
      "CUDA_VISIBLE_DEVICES=, а лаунчер такую ячейку отклоняет (1.3.512)")
check(caps["gr00t"] == {"cpu": False, "gpu": True, "auto": False},
      "GR00T — только GPU: Isaac-GR00T держит политику на CUDA")
check(all(caps[r] == {"cpu": False, "gpu": True, "auto": False} for r in ("personaplex", "lfm-audio", "step-audio2", "qwen3-omni", "minicpm-omni")),
      "the five voice servers — только GPU, по слову реестра (gpuOnly), без списка id в браузере; negative: transcribe, seamless и "
      "translate (gpuOnly нет) остаются с обоими устройствами")
check(got["mode"] == {"vllm": "gpu", "whisper": "gpu", "moonshine": "cpu", "strata": "gpu", "gr00t": "gpu", "transcribe": "cpu"},
      "раннер с одним устройством называет его, что бы ни писал ENV; transcribe (оба) читает ENV — negative "
      f"(получено {got['mode']})")
check(got["cpuTileOff"] == {"strata": True, "gr00t": True, "vllm": True, "transcribe": False},
      f"плитка CPU у Strata, GR00T и vLLM не нажимается, у transcribe — нажимается (получено {got['cpuTileOff']})")

print("applyComputeTarget — что плитка пишет в поля:")
ap = got["applied"]
check(ap["bothBlank"] == {"DEVICE": "", "MAIN_GPU": "", "SPLIT_MODE": "layer"},
      f"обе карты и пустой режим: DEVICE пуст (= все карты), деление конвейером — row на b1141 не стартует (получено {ap['bothBlank']})")
check(ap["bothChosen"]["SPLIT_MODE"] == "layer",
      "уже выбранный конвейер переживает повторный выбор карт — плитка не переписывает решение оператора")
check(ap["oneCard"] == {"DEVICE": "CUDA1", "MAIN_GPU": "1", "SPLIT_MODE": ""},
      f"одна карта: флаг деления снимается, делить нечего (получено {ap['oneCard']})")
check(ap["cpu"]["SPLIT_MODE"] == "" and ap["cpu"]["DEVICE"] == "",
      "CPU: деления между картами нет вовсе")

print("где плитка показывает деление:")
tl = got["tile"]
check(tl["twoPicked"], "две карты выбраны — переключатель деления на виду, в плитке «где запускать»")
check(tl["twoHostOnePicked"] is False,
      "в машине две карты, выбрана одна — переключателя нет: делить нечего, а показанный он читался бы как настройка, которая не сработала")
check(tl["oneCardHost"] is False, "одна карта в машине — переключателя нет")
check(tl["cpuMode"] is False, "режим CPU — переключателя нет")

print("план выгрузки: RAM машины, а не контроллера:")
rs = got["ramShort"]
check(rs["machineFull"] == [True, True],
      f"в RAM машины свободно 4 ГБ, туда уходит ~15 ГБ весов — план красный, хотя у контроллера свободно 64 ГБ "
      f"(было: сравнивалось с RAM контроллера, и нехватка на другой машине не показывалась) (got {rs['machineFull']})")
check(rs["machineRoomy"] == [True, False],
      f"negative: у машины свободно 60 ГБ — план не красный (got {rs['machineRoomy']})")

print("какую модель оценивает форма и что говорит полоса памяти:")
check(got["rows"] == {"awaited": None, "chosen": "m.gguf"},
      "defect-history: оценка — о модели, которую форма называет выбранной (modelChoiceOf); пока «＋ Add model» ждёт "
      "выбора, модели нет — раньше пустое поле читалось вместе с конфигом, и редактор показывал 29.8 ГБ «не влезет» "
      f"и подсказку про проектор модели по умолчанию (живая проверка 1.3.390) (got {got['rows']})")
aside = got["aside"]
check(aside["llamaNone"] == [["tr-", 0]],
      f"llama без модели — полоса говорит «выберите модель», а не держит цифры прошлой модели (got {aside['llamaNone']})")
check(aside["llamaModel"] == [],
      "negative: llama с моделью — полосу рисует renderModelInsight (разбивка по файлам), здесь её не трогают")
check(aside["moonshine"] == [["tr-", aside["moonshineGb"], True]] and aside["moonshineGb"] > 0,
      "другие раннеры — полоса отсюда, с картиной машины и без модели (allowEmpty)")
check(aside["llamaFigure"] == [["tr-", 37.2]],
      f"llama с моделью — цифра, которую передал renderModelInsight (получено {aside['llamaFigure']})")
note6 = english("vramTakesFree", gb="6.00 GB")
check(aside["strata"] == [["tr-", 8, True, {"hard": True, "cards": [0], "vramNote": note6}]],
      "defect-history: Strata — по своему плану, а не по сумме llama, которую ей передали: свободное на её карте "
      "(8 ГБ), точное сравнение, одна карта, строка «как она берёт память»; было «37.2 GB, won't fit» "
      f"(живая проверка 2026-10-13) (получено {aside['strata']})")
check(aside["strataNoCard"] == [["tr-", 0, True]],
      "negative: ENV называет карту, которой у машины нет, — сервер ничего не резервирует, и полоса не выдумывает "
      f"цифру: только картина машины (получено {aside['strataNoCard']})")

check(aside["gr00t"] == [["tr-", 7.5, True, {"hard": True, "cards": [0]}]] and got["fitGb"]["gr00t"] == 7.5,
      "GR00T — по своему плану: 7.5 ГБ, замер политики на RTX 5090 с запасом, а не сумма llama, которую ей передали; рисуется на одной карте и "
      "точно (скаут отказывает с первого МиБ нехватки) "
      f"(получено {aside['gr00t']}, {got['fitGb']})")
check(got["fitGb"]["seamless"] != 7.5,
      f"negative: раннер без цифры в плане её не получает (получено {got['fitGb']['seamless']})")


print("одна карта у раннера на машине с двумя (чипы карты):")
chips = got["chips"]
check(chips["qwenNoPin"] == {"chips": [[0, True], [1, False]], "tile": "RTX 3090", "hook": True},
      f"Qwen3-Omni без пина: две карты, выбрана нулевая — та, на которую сервер считает резерв; плитка называет её (получено {chips['qwenNoPin']})")
check(chips["qwenPinned"] == {"chips": [[0, False], [1, True]], "tile": "RTX 5090", "hook": True},
      f"пин на карту 1: выбрана она, плитка называет RTX 5090 (получено {chips['qwenPinned']})")
check(chips["personaplexPinned"]["chips"] == [[0, False], [1, True]] and chips["strata"]["chips"] == [[0, False], [1, True]]
      and chips["gr00t"]["chips"] == [[0, True], [1, False]],
      "чипы есть у всех раннеров на одной карте: PersonaPlex (пин среди чужих строк ENV), Strata, GR00T")
check(chips["missingCard"] == {"chips": [[0, False], [1, False]], "tile": "RTX 3090", "hook": True}
      and chips["aList"]["chips"] == [[0, True], [1, False]],
      f"boundary: пин на карту, которой нет, — не выбрана ни одна (сервер резерва не считает), плитка — первая карта; список «0,1» ENV читает по запятой: пин «0» (получено {chips['missingCard']}, {chips['aList']})")
check(chips["oneCardMachine"]["chips"] == [] and chips["oneCardMachine"]["tile"] == "RTX 5090",
      "negative: у машины одна карта — чипов нет, выбирать не из чего")
check(all(chips[r]["chips"] == [] for r in ("llama", "vllm", "custom", "transcribe")),
      f"negative: у llama.cpp (свой выбор набора карт), vLLM (свой ENV и тензорный параллелизм), custom и transcribe чипов одной карты нет (получено {[chips[r]['chips'] for r in ('llama', 'vllm', 'custom', 'transcribe')]})")
click = got["chipClick"]
check(chips["gpuMode"]["chips"] == [[0, True], [1, False]] and chips["cpuMode"]["chips"] == [],
      f"раннер, который МОЖЕТ работать на CPU: в режиме GPU карты на выбор есть, в режиме CPU — нет (получено {chips['gpuMode']['chips']}, {chips['cpuMode']['chips']})")
check(click["before"] == "FOO=1\nCUDA_VISIBLE_DEVICES=0" and click["after"] == "FOO=1\nCUDA_VISIBLE_DEVICES=1" and click["back"] == "FOO=1\nCUDA_VISIBLE_DEVICES=0",
      f"щелчок по чипу пишет пин в ENV, остальные строки ENV целы, и обратно (получено {click})")
check(click["litAfter"] == [1] and click["tileAfter"] == "RTX 5090" and click["litBack"] == [0] and click["tileBack"] == "RTX 3090",
      f"после щелчка перерисованы и чипы (горит нажатый), и плитка (называет его карту), и обратно (получено {click})")
check(click["previews"] == ["tr-"],
      f"после щелчка перерисован предпросмотр команды формы, ровно один раз: в команде стоит тот же пин, что в ENV (получено {click['previews']})")
bar = got["cardBar"]
check(bar["noPin"] == [[31, True, {"hard": True, "cards": [0]}]] and bar["pinned"] == [[31, True, {"hard": True, "cards": [1]}]],
      f"полоса оценки: 31 ГБ плана на карте, которую называет пин, и точно (получено {bar['noPin']}, {bar['pinned']})")
check(bar["missing"] == [[31, True]] and bar["aList"] == [[31, True, {"hard": True, "cards": [0]}]] and bar["vllm"] == [3],
      f"negative: пин на карту, которой нет, — полоса как была, без карты; список «0,1» — пин «0», как читает сервер; у vLLM с пином — своя карта и точно, три аргумента (получено {bar['missing']}, {bar['aList']}, {bar['vllm']})")
check(got["ramWire"] == {"strata": [[52531, 2048, ["cards", "hard", "ramPlan", "vramNote"]]], "omni": [None], "asking": ["tr-"]},
      "1.3.574: Strata (реестр говорит keepsRam) получает в полосу обещание памяти, которое у формы уже есть: 52531 МиБ и запас 2048; ячейка, что ничего не держит в ОЗУ "
      f"(qwen3-omni), — полосу как прежде, без обещания, и спрашивать ей не у кого (получено {got['ramWire']})")
check(got["ramUnknown"] == {"strata": [None], "asked": 1},
      "negative: пока контроллер не ответил, обещания в полосе нет — не чужое, не нулевое; а спросить он просит ровно один раз "
      f"(получено {got['ramUnknown']})")
server_pins = [runner_get("strata").pinned_card({"ENV": env}, CARD_GPUS) for env, _ in CARD_CASES]
check(got["pin"]["card"] == server_pins,
      f"какую карту называет ENV — одна таблица, форма и сервер (Runner.pinned_card) дают одно (форма {got['pin']['card']}, сервер {server_pins})")
check(got["pin"]["write"] == ["CUDA_VISIBLE_DEVICES=1", "FOO=1\nCUDA_VISIBLE_DEVICES=1", "CUDA_VISIBLE_DEVICES=1", "A=1\nB=2\nCUDA_VISIBLE_DEVICES=1",
                              "CUDA_VISIBLE_DEVICES=1", "# CUDA_VISIBLE_DEVICES=0\nCUDA_VISIBLE_DEVICES=1", "CUDA_VISIBLE_DEVICES=1",
                              "A=1\nB=2\nCUDA_VISIBLE_DEVICES=1", "# the big card\nFOO=1\nCUDA_VISIBLE_DEVICES=1"],
      f"запись пина: прежний пин снят (в любой записи; список «0,1» — это пин «0» и строка «1» без «=», которую сервер пропускает, и запись её не оставляет), "
      f"чужие строки целы, комментарий не считается пином и остаётся — и тот, что без «=» (получено {got['pin']['write']})")
check(got["label"] == ["", "", "NVIDIA GeForce RTX 3090", "2 × RTX 3090", "RTX 3090 + RTX 5090", "NVIDIA GeForce RTX 5090",
                       "2 × RTX 3090 + RTX 5090"],
      f"имя машины в заголовке формы — все её карты: одна называется как была, две одинаковые — «2 × …», разные — через «+»; карта без имени не считается (получено {got['label']})")

print("старт, который берёт свободную VRAM карты (Strata):")
srv = [server_card(e, r) for e, r in CARD_CASES]
check(srv.count(None) >= 4 and [1, 6144] in srv and [0, 10240] in srv and [0, 6656] in srv,
      f"таблица случаев задевает обе стороны: карта 0 и 1, резерв, отказы (сервер: {srv})")
check(got["cards"] == srv,
      "форма выбирает ту же карту и ту же нужную память, что сервер (vram_reservation): последний "
      "CUDA_VISIBLE_DEVICES в ENV, иначе карта 0; кавычки и пробелы срезаны; пустой, чужой, «00» и «GPU-…» — "
      f"нет карты; резерв не числом — нет резерва (форма: {got['cards']})")
check(got["freeStart"] == {"roomy": [True, 13.6], "roomyReserve": [True, 9.6], "exact": [True, 6.0],
                           "short": [False, 6.0], "shortReserve": [False, 10.0]},
      "свободно 13.6 ГБ — берёт всё, с резервом 4 ГБ — 9.6; ровно 6 ГБ — стартует, на 1 МиБ меньше — нет "
      "(правило скаута starts.py: свободно >= нужно); не стартует — полоса рисует нужное "
      f"(получено {got['freeStart']})")
check(got["freeStartBar"] == {"hard": True, "cards": [1], "vramNote": english("vramTakesFree", gb="10.0 GB")},
      f"полоса — на её карте (1), без запаса в 1 ГБ, с нужным: 6 ГБ + резерв 4 (получено {got['freeStartBar']})")

print("две карты, одна модель — кэш KV (70B на 3090 + 5090, 2026-10-17):")
kvs = got["kv"]
check(kvs["q8"] == 0.664 and kvs["f16"] == 1.25 and kvs["mixed"] == 0.957,
      f"Llama 3.3 70B, 4096 токенов, 80 слоёв, 8 KV-голов по 128: q8_0 — 0.664 ГБ, f16 — 1.25, K f16 + V q8_0 — 0.957 (получено {kvs['q8']}, {kvs['f16']}, {kvs['mixed']}); "
      "key_length — длина ОДНОЙ головы, раньше не умножалась на число KV-голов: форма писала «KV≈0.08 ГБ», в 8 раз меньше")
check(kvs["long"] == 21.25, f"131072 токена — 21.25 ГБ: рост кэша с контекстом по-прежнему линеен (получено {kvs['long']})")
check(kvs["withoutKeyLength"] == kvs["q8"] and kvs["withoutKeyLengthF16"] == kvs["f16"] and kvs["mqaWith"] == kvs["mqaWithout"] == 0.033,
      "один и тот же ответ, есть в заголовке key_length или нет: его нет — берётся embedding / head_count × KV-голов, и обе дороги сходятся "
      f"(MQA с одной KV-головой — 0.033 ГБ обеими; получено {kvs['mqaWith']} и {kvs['mqaWithout']})")
check(kvs["valueLengthAlone"] == kvs["q8"], "одна value_length без key_length — ключ из запасной дороги, значение умножено на головы: те же 0.664")
check(all(kvs[k] == 0 for k in ("noHeads", "noContext", "noLayers", "noMeta")),
      "negative: нет числа голов при key_length, нет контекста, нет слоёв, нет описания — «нет оценки» (0 = n/a), а не выдуманное число")

print("две карты, одна модель — что ячейка держит и что ей свободно:")
hd = got["holds"]
check(hd["running"] == {"live": True, "byCard": {"0": 18350, "1": 24364}, "totalGb": 41.71},
      f"работающая ячейка держит по картам своё: 18350 + 24364 МиБ = 41.7 ГБ (получено {hd['running']})")
check(hd["warming"]["live"] is True and hd["running"]["live"] is True,
      "работающая и прогревающаяся — держат (так же считает полоса справа в форме)")
check(not any(hd[k]["live"] for k in ("starting", "stopped", "none")) and all(hd[k]["byCard"] == {} for k in ("starting", "stopped", "none")),
      "negative: остановленная, ещё не начавшая и «ячейки нет» — не держат ничего: их память уже свободна, прибавлять нечего")
check(hd["noMem"] == {"live": True, "byCard": {}, "totalGb": 0} and hd["junk"]["byCard"] == {"0": 0, "1": 100},
      "negative: работает, а память не измерена, или число не число — 0, а не NaN в сумме")
check(got["room"]["running"] == [24558, 32607] and got["room"]["stopped"] == [6208, 8243] and got["room"]["otherPort"] == [6208, 8243],
      "комната карты для ЭТОЙ ячейки: что карта сообщает свободным + что держит сама ячейка (6208 + 18350, 8243 + 24364 — по общему объёму карты); "
      f"остановленной или чужой ничего не прибавляется (получено {got['room']})")

print("две карты, одна модель — «влезает ли» у работающей ячейки:")
check(got["runtimeGb"] == 43.45, f"оценка рантайма 70B: 39.6 + KV 0.66 + буферы 3.19 = 43.45 ГБ (получено {got['runtimeGb']})")
check(got["ownFit"]["running"] == ["good", "55.8 GB"],
      "форма работающей ячейки: 43.45 ГБ влезает в 55.8 ГБ — свои 41.7 ГБ возвращаются при перезапуске; было «Over VRAM 42.9 GB / 13.3 GB free» "
      f"у ячейки, которая с этим самым объёмом работает (получено {got['ownFit']['running']})")
check(got["ownFit"]["stopped"] == ["bad", "14.1 GB"] and got["ownFit"]["noCell"] == ["bad", "14.1 GB"] and got["ownFit"]["plainStillTwoArgs"] == "bad",
      "negative: остановленной и новой ячейке (и вызову с двумя аргументами) свободные 14.1 ГБ прибавлять нечем — Over VRAM остаётся")

print("две карты, одна модель — где ляжет «auto» и как карты делят веса:")
au = got["auto"]
check(au["running"]["auto"] == 80 and au["running"]["partial"] is False and au["stopped"]["auto"] == 19 and au["stopped"]["partial"] is True,
      f"auto у работающей ячейки — все 80 слоёв (своя память возвращается), у остановленной при тех же 14.1 ГБ свободных — 19 (получено {au['running']['auto']} и {au['stopped']['auto']}); "
      "в окне работающей ячейки это было «19/80 … 30 ГБ в ОЗУ» для весов, которые она держала целиком в видеопамяти")
check(au["tensorStopped"]["auto"] == 80 and au["tensorRunning"]["auto"] == 80 and au["tensorStopped"]["partial"] is False,
      "tensor: auto — все слои на картах, как есть на деле (llama.cpp: «llama_params_fit is not implemented for SPLIT_MODE_TENSOR»; замер 70B: 42.5 ГБ на двух картах), а не частичное деление, которого он не делает")
cs = got["cardsShare"]
check(cs["layer"]["cards"] == [[0, 34, 18.5], [1, 46, 25.0]] and cs["rowFollowsRoom"]["cards"] == cs["layer"]["cards"],
      f"layer и row делят по комнате карт (24.6 : 32.6 → 34 и 46 слоёв; замер: 18.3 + 24.4 ГБ), получено {cs['layer']['cards']}")
check(cs["tensorEven"]["cards"] == [[0, 40, 21.7], [1, 40, 21.7]],
      f"tensor без своих долей режет ровно пополам, какие бы карты ни были (замер: 21.1 + 21.4 ГБ), получено {cs['tensorEven']['cards']}")
check(cs["asymmetric"]["cards"][0][1] == 34 and cs["asymmetricStopped"]["cards"][0][1] == 15,
      "комната карты для весов — то, что она сообщает, плюс своё: 6.1 + 18.0 и 27.3 + 4.5 ГБ → 34 и 46 слоёв (карта, на которой ячейка сидела, не обделяется); "
      f"у остановленной — по сообщённому, 15 и 65 (получено {cs['asymmetric']['cards']} и {cs['asymmetricStopped']['cards']})")
check(cs["tensorBySize"]["cards"] == [[0, 34, 18.5], [1, 46, 25.0]] and cs["layerManual"]["cards"] == [[0, 20, 10.9], [1, 60, 32.6]],
      "свои доли оператора (24,32 или 1,3) решают в любом режиме — в том числе перебивают «ровно» у tensor")

print("две карты, одна модель — панель размещения весов:")
pl = got["plan"]
check(pl["n999"] == {"lit": "all", "autoMain": "80/80", "slider": False} and pl["n80"]["lit"] == "all" and pl["all"]["lit"] == "all",
      f"число, которое достаёт до всех слоёв (999 у новой ячейки, 80 из 80), — «all on GPU», не «manual» с ползунком в конце (получено {pl['n999']})")
check(pl["n79"] == {"lit": "manual", "autoMain": "80/80", "slider": True} and pl["manual40"]["lit"] == "manual" and pl["manual40"]["slider"] is True,
      "negative: 79 из 80 и 40 — по-прежнему «manual», с ползунком (граница — ровно все слои)")
check(pl["runningAuto"] == "80/80" and pl["stoppedAuto"] == "19/80",
      "плитка «auto» читает число из offloadSplit (одно место), и у работающей ячейки оно с возвращённой памятью")

print("две карты, одна модель — что пишет выбор карт и плитка деления:")
ap2 = got["apply"]
check(ap2["blank"] == ["layer", ""] and ap2["layer"] == ["layer", ""] and ap2["row"] == ["row", ""],
      f"выбор карт: пустое — конвейер, выбранный нарочно режим остаётся, долей нет там, где режим делит по комнате сам (получено {ap2['blank']}, {ap2['layer']}, {ap2['row']})")
check(ap2["tensor"] == ["tensor", "24,32"] and ap2["tensorTwoOfThree"] == ["tensor", "24,48"] and ap2["tensorKeepsNothingOfAnOldSplit"] == ["tensor", "24,32"],
      "tensor приносит доли по размерам карт (3090 и 5090 — 24,32; две из трёх — по номерам, 24,48); прежние доли при смене набора карт заменяются, как и раньше сбрасывались")
check(ap2["tensorMachineListedBackwards"] == ["tensor", "24,32"],
      "доли — в порядке номеров карт, как их видит llama.cpp, а не в порядке списка машины (5090 впереди 3090 в отчёте — всё равно 24,32)")
check(ap2["tensorEqualCards"] == ["tensor", ""] and ap2["tensorOneCard"] == ["", ""],
      "negative: равные карты — долей нет; одна карта — ни режима, ни долей: делить нечего")
ck = got["click"]
check(ck["blankToTensor"] == ["tensor", "24,32"] and ck["layerToTensor"] == ["tensor", "24,32"],
      f"плитка Tensor + KV приносит доли по размерам карт (получено {ck['blankToTensor']})")
check(ck["tensorToLayer"] == ["layer", ""] and ck["tensorToRow"] == ["row", ""],
      "режим после него забирает доли обратно: они были записаны для tensor, и в конвейере переопределяли бы его деление по свободной памяти")
check(ck["ownSplitKeptOnTensor"] == ["tensor", "3,1"] and ck["ownSplitKeptOnLayer"] == ["layer", "3,1"],
      "negative: доли, которые оператор вписал сам, — его: плитка их не трогает ни в одну сторону")
check(ck["equalCards"] == ["tensor", ""], "negative: равные карты — плитка долей не пишет")
check(ck["machineListedBackwards"] == ["tensor", "24,32"], "и у плитки доли — в порядке номеров карт, не списка машины")

print("vLLM на машине с двумя картами — какие карты он берёт и что просит у каждой:")
vl = got["vllm"]
check(vl["default"] == {"tp": 1, "cards": [0], "each": [21.6], "total": 21.6, "over": True, "noted": True} and vl["one"] == vl["default"],
      f"TENSOR_PARALLEL пуст или 1 — одна карта, нулевая (3090), и просит у неё 0.9 × 24 = 21.6 ГБ; раньше форма рисовала 0.9 × ВСЕ карты машины, 50.3 ГБ (получено {vl['default']})")
check(vl["two"] == {"tp": 2, "cards": [0, 1], "each": [21.6, 21.6], "total": 43.2, "over": False, "noted": False},
      "TENSOR_PARALLEL 2 — обе карты, и каждая просит одно и то же: рабочие vLLM делают ОДИН кэш KV по самой маленькой, замер 22.8 и 23.2 ГБ на 24.6 и 32.6 ГБ при 0.9, "
      f"а не 22.1 и 29.3 (получено {vl['two']})")
check(vl["twoLowUtil"]["each"] == [16.8, 16.8] and vl["twoLowUtil"]["total"] == 33.6, "доля занятого задаётся GPU_MEMORY_UTILIZATION: 0.7 × 24 = 16.8 на каждую")
check(vl["three"]["cards"] == [0, 1] and vl["three"]["total"] == 43.2,
      "as-is: TENSOR_PARALLEL больше числа карт машины (3 из 2) берёт все карты; vLLM откажет сам, форма не предупреждает")
check(all(vl[k]["tp"] == 1 for k in ("zero", "junk", "negative", "fractional")) and vl["padded"]["tp"] == 2,
      "negative: 0, не число, минус два и 1.5 — это один (без параллелизма); пробелы вокруг «2» не мешают")
check(vl["pinned5090"] == {"tp": 1, "cards": [1], "each": [28.66], "total": 28.66, "over": False, "noted": False},
      f"одна карта, закреплённая в ENV (CUDA_VISIBLE_DEVICES=1), — 5090, 0.9 × 31.8 = 28.66; веса 25.7 в неё помещаются (получено {vl['pinned5090']})")
check(vl["pinnedMissing"]["cards"] == [] and vl["pinnedMissing"]["total"] == 0 and vl["pinnedList"]["cards"] == [0],
      "negative: пин на карту, которой нет, — карт нет и просить нечего (сервер не резервирует тоже); список «0,1» — пин «0», как читает сервер")
check(vl["pinIgnoredByTp"]["cards"] == [0, 1],
      "as-is: при TENSOR_PARALLEL 2 пин в ENV не читается — берутся первые две карты (с пином на одну карту vLLM не стартует, форма об этом молчит)")
check(vl["backwards"]["cards"] == [0, 1], "порядок карт — по номерам, а не по списку машины")
check(vl["threeCardsTwoAsked"]["cards"] == [0, 1] and vl["threeCardsTwoAsked"]["total"] == 43.2,
      "три карты, TENSOR_PARALLEL 2 — первые две, а не все три (третья остаётся свободной)")
check(vl["badUtil"]["each"] == [21.6] and vl["zeroUtil"]["each"] == [21.6], "negative: доля не числом или нулевая — 0.9, как у vLLM по умолчанию")
print("vLLM — влезают ли веса:")
check(vl["default"]["over"] and vl["one"]["over"] and not vl["two"]["over"] and not vl["pinned5090"]["over"] and not vl["twoLowUtil"]["over"],
      "веса 25.66 ГБ не помещаются в 21.6 ГБ одной карты (минус 1 ГБ на активации), а на двух по 12.8 ГБ или на 5090 (28.66) — помещаются; "
      "раньше форма на TENSOR_PARALLEL 1 показывала «50.3 из 55.8 ГБ» для старта, который не мог разместить свои веса")
check(not vl["fitsByTheMargin"]["over"] and vl["overByTheMargin"]["over"],
      "boundary: 1 ГБ из 21.6 ГБ остаётся на активации и графы — 20.5 ГБ весов помещаются, 20.7 нет")
check(not vl["noModel"]["over"] and not vl["unknownModel"]["over"] and not vl["pinnedMissing"]["over"] and not vl["noCards"]["over"],
      "negative: модель не выбрана, или выбрана вписанная руками (размера нет), или карт нет — «не помещаются» не говорится: размера нет — нет и утверждения")
check(got["vllmNote"] == english("vllmWeightsOver", weights="25.7 GB", budget="21.6 GB"),
      f"строка под полосой — слова из ключа vllmWeightsOver с числами (получено {got['vllmNote']})")
print("vLLM — что рисуют полоса, число и плитка:")
vb = got["vllmBar"]
check(vb["one"] == [["tr-", 21.6, True, {"hard": True, "cards": [0], "note": True}]] and vb["two"] == [["tr-", 43.2, True, {"hard": True, "cards": [0, 1], "note": False}]],
      f"полоса: только карты, которые он берёт, и точно (старт vLLM отказывает, когда свободно меньше), с замечанием о весах, когда они не помещаются (получено {vb['one']}, {vb['two']})")
check(vb["pinned"] == [["tr-", 28.66, True, {"hard": True, "cards": [1], "note": False}]] and vb["noModel"][0][3]["note"] is False
      and vb["missing"] == [["tr-", 0, True, {"hard": True, "cards": [], "note": False}]],
      "карта, закреплённая в ENV, — своя полоса; без модели замечания нет; пин на несуществующую карту — нуль и без карт")
check(got["vllmFit"] == {"tp": 21.6, "tp1": 21.6, "tp2": 43.2, "tp3": 43.2}, f"число для сравнения — то же, что у полосы (получено {got['vllmFit']})")
vt = got["vllmTile"]
check(vt["default"] == {"main": "1/2 · 24.0 GB", "sub": "GPU0", "chips": 0} and vt["two"] == {"main": "2/2 · 55.8 GB", "sub": "All", "chips": 0}
      and vt["pinned"] == {"main": "1/2 · 31.8 GB", "sub": "GPU1", "chips": 0},
      f"плитка GPU у vLLM называет карты, которые он берёт: «1/2 · 24.0 GB — GPU0» при одной, «2/2 · 55.8 GB — All» при двух; раньше всегда «RTX 3090» (получено {vt})")
check(vt["missing"] == {"main": "RTX 3090", "sub": "24.0 GB VRAM", "chips": 0} and vt["oneCardMachine"]["main"] == "RTX 5090",
      "negative: карт, которые он берёт, нет, и машина с одной картой — плитка как была, имя карты и её объём; чипов у vLLM нет — число карт задаёт TENSOR_PARALLEL")

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail: print("  - " + m)
    sys.exit(1)
print("js memory OK: настоящий модуль в node, оценка памяти значениями")
