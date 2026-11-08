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
from _node import find_node, node_search_paths, probe_args  # noqa: E402
from _contract import Contract, RunnerCards  # noqa: E402

# Which card a Strata start lands on and what it needs free there: ONE table, run
# through the program's rule (contract/runner_cards.json) here and through the
# form's (placement.js FreeVramStart, re-exported by memory.js) in node — the two copies cannot drift apart
# without this going red.
CARD_GPUS = [{"index": 0, "memoryTotalMiB": 32607, "memoryFreeMiB": 13926},
             {"index": 1, "memoryTotalMiB": 24576, "memoryFreeMiB": 20000}]
CARD_CASES = [("", ""), ("CUDA_VISIBLE_DEVICES=1", ""), ("CUDA_VISIBLE_DEVICES=1\nCUDA_VISIBLE_DEVICES=0", ""),
              ('CUDA_VISIBLE_DEVICES="1"', ""), (" CUDA_VISIBLE_DEVICES = 1 ", ""), ("CUDA_VISIBLE_DEVICES=", ""),
              ("CUDA_VISIBLE_DEVICES=0,1", ""), ("X=CUDA_VISIBLE_DEVICES=1", ""), ("CUDA_VISIBLE_DEVICES=5", ""),
              ("CUDA_VISIBLE_DEVICES=GPU-3f2a", ""), ("CUDA_VISIBLE_DEVICES=00", ""), ("# CUDA_VISIBLE_DEVICES=1", ""),
              ("", "4096"), ("", " 512 "), ("", "2G")]


def gemma_meta():
    """The `ggufMeta` of Gemma 4 12B as the controller tells it to the page: a header with the facts of the real file (read 2026-10-19: 48 layers, five in six
    with a window of 1024 and 8 KV heads of 256, the sixth over the whole context with one head of 512). contract/gguf_meta.json holds the header and what the
    program reads of it: a name that drifted would leave the page counting every layer over the whole context."""
    return Contract.table("gguf_meta")["gemma"]["meta"]


def next_meta():
    """The `ggufMeta` of Qwen3-Coder-Next as the controller tells it to the page: its header as read 2026-10-24 (48 layers that attend in one of four, 2 KV
    heads of 256, 512 experts) and a tensor list of three: a dense tensor and two of experts, 5008 bytes of them."""
    return Contract.table("gguf_meta")["next"]["meta"]


def server_card(env, reserve):
    r = RunnerCards.said("vram", {"ENV": env, "STRATA_VRAM_RESERVE_MIB": reserve})
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
  caps: Object.fromEntries(["vllm","whisper","moonshine","strata","gr00t","personaplex","lfm-audio","step-audio2","qwen3-omni","minicpm-omni","transcribe","seamless","translate","custom","voice-clone","llama-server","nonsense"].map((r) => [r, m.runnerDeviceCaps(r)])),
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
  const plan = (usedGb, totalGb = 64, extra = {}) => {
    TR_CPU.ram.usedGb = usedGb;
    TR_CPU.ram.totalGb = totalGb;
    const box = { innerHTML: "", querySelectorAll: () => [], querySelector: () => null };
    globalThis.__fields = { "tr-placementMap": box, "tr-MODEL_FILE": { value: "m.gguf" }, "tr-N_GPU_LAYERS": { value: "10" }, ...extra };
    try { m.refreshPlacementMap("tr-"); } catch (e) { return "threw: " + e.message; }
    // The placement map's verdict pill says what it found: ramShort, or a part in RAM that fits.
    const verdict = (box.innerHTML.match(/data-t="cell-remote-placement-verdict" data-t-state="([a-zA-Z]+)"/) || [])[1] ?? null;
    return [verdict !== null, verdict === "ramShort"];
  };
  // A machine whose scout has not reported its RAM: 0 total, 0 used.
  out.ramShort = { machineFull: plan(60), machineRoomy: plan(4), machineSilent: plan(0, 0) };
  // Experts moved by hand: the plan cannot count them, so the line above the tabs claims no split either.
  const split = (extra) => { globalThis.__fields = { "tr-MODEL_FILE": { value: "m.gguf" }, "tr-N_GPU_LAYERS": { value: "auto" }, ...extra };
    const s = m.offloadSplit("tr-"); return { known: s.known, partial: s.partial, onCards: s.layersGpu }; };
  out.moeSplit = { byHand: split({ "tr-N_CPU_MOE": { value: "20" } }), fitted: split({}) };
  TR_CPU.ram.totalGb = 64;
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
  const oldGpus = TR_GPUS.slice();
  TR_GPUS.splice(0, TR_GPUS.length, { index: 0, memoryFreeMiB: 20480 }, { index: 1 });
  out.aside.strataDsUntold = drawn({ "tr-RUNNER": { value: "strata-ds" } }, 37.2);
  TR_GPUS.splice(0, TR_GPUS.length, ...oldGpus);
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
  // Strata's DeepSeek engine takes the free memory of every card (the registry's `everyCard`): the form's bar is on them all.
  const every = REGISTRY.find((r) => r.id === "strata-ds").vramPlan;
  const both = [{ index: 0, memoryFreeMiB: 20480 }, { index: 1, memoryFreeMiB: 30720 }];
  const s = m.FreeVramStart.of(every, { env: "CUDA_VISIBLE_DEVICES=1", reserve: "", gpus: both });
  out.freeEvery = { plan: every, bar: s.bar(), gb: s.addGb, known: s.known, places: s.places,
                    untold: m.FreeVramStart.of(every, { env: "", reserve: "", gpus: [both[0], { index: 1 }] }).known,
                    none: m.FreeVramStart.of(every, { env: "", reserve: "", gpus: [] }),
                    zero: m.FreeVramStart.of(every, { gpus: [{ index: 0, memoryFreeMiB: 0 }] }).known };
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
    // 2026-10-27: whisper and seamless open one card, "cuda" — the pin, else card 0 — and the form now asks which.
    whisperNoPin: tile("whisper", ""), whisperPinned: tile("whisper", "CUDA_VISIBLE_DEVICES=1"), seamlessGpu: tile("seamless", ""),
  };
  globalThis.__stubReturns["llama-edit._envDeviceState"] = () => "cpu";
  out.chips.seamlessCpu = tile("seamless", "TTS_DEVICE=cpu\nCUDA_VISIBLE_DEVICES=");
  delete globalThis.__stubReturns["llama-edit._envDeviceState"];
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
  const bar = (runner, env, cards = two, extra = {}) => {
    setCards(cards);
    calls.length = 0;
    globalThis.__fields = { "tr-RUNNER": { value: runner }, "tr-ENV": { value: env }, ...extra };
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
    const rideBar = (offload) => bar("vllm", "CUDA_VISIBLE_DEVICES=1", two, offload ? { "tr-CPU_OFFLOAD_GB": { value: offload } } : {}).map(([gb, allow, opts]) => (opts.ramPlan ? opts.ramPlan.reserveMiB : null));
    out.ramWireVllm = { rides: rideBar("12.5"), none: rideBar(""), zero: rideBar("0") };
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

  // A model whose layers differ (2026-10-19, cell :22007, the form said 277 GB for a 12 GB model): Gemma 4 12B as its header says. 48 layers,
  // five in six attend through a window of 1024 with 8 KV heads of 256, the sixth over the whole context with ONE head of 512.
  const SIX = (a, b) => Array.from({ length: 8 }, () => [a, a, a, a, a, b]).flat();
  // As the controller tells it (rust/crates/admin/tests/contract.rs reads a header of the real file with the real reader), not written by hand here.
  const GEMMA = JSON.parse(process.env.GEMMA_META);
  // Qwen3-Coder-Next, a hybrid: it attends in 12 of its 48 layers (full_attention_interval 4), the rest keep a recurrent state.
  const NEXT = JSON.parse(process.env.NEXT_META);
  const cell = { ctx: "180000", k: "f16", v: "f16" };
  const gem = (extra = {}, meta = GEMMA, fields = cell) => {
    globalThis.__fields = { "tr-CTX_SIZE": { value: fields.ctx }, "tr-CACHE_TYPE_K": { value: fields.k }, "tr-CACHE_TYPE_V": { value: fields.v }, ...extra };
    return m.estimateKvCacheGb({ path: "g.gguf", ggufMeta: meta }, "tr-");
  };
  const THREE = { "tr-PARALLEL": { value: "3" } };
  // The cell as the owner has it (read from the controller 2026-10-19): 3 slots, a batch of 2048 and a physical batch of 2048.
  const OWNER = { ...THREE, "tr-BATCH_SIZE": { value: "2048" }, "tr-UBATCH_SIZE": { value: "2048" } };
  out.layers = {
    layout: m.kvLayout(GEMMA),
    owner: gem(OWNER),
    threeSlots: gem(THREE),
    auto: gem(),
    unified: gem({ ...THREE, "tr-KV_UNIFIED": { checked: true } }),
    unifiedOff: gem({ ...THREE, "tr-KV_UNIFIED": { checked: false } }),
    swaFull: gem({ ...THREE, "tr-SWA_FULL": { checked: true } }),
    q8: gem(THREE, GEMMA, { ctx: "180000", k: "q8_0", v: "q8_0" }),
    mixed: gem(THREE, GEMMA, { ctx: "180000", k: "f16", v: "q8_0" }),
    smallCtx: gem(THREE, GEMMA, { ctx: "512", k: "f16", v: "f16" }),
    ubatch: gem({ ...THREE, "tr-UBATCH_SIZE": { value: "2048" } }),
    ubatchUnderBatch: gem({ ...THREE, "tr-UBATCH_SIZE": { value: "2048" }, "tr-BATCH_SIZE": { value: "1024" } }),
    noFlags: gem(THREE, { ...GEMMA, slidingWindowLayers: [] }),
    layout_noFlags: m.kvLayout({ ...GEMMA, slidingWindowLayers: [] }),
    shortFlags: m.kvLayout({ ...GEMMA, slidingWindowLayers: SIX(1, 0).slice(1) }),
    noWindow: m.kvLayout({ ...GEMMA, slidingWindow: 0 }),
    shortHeads: m.kvLayout({ ...GEMMA, headCountKvLayers: SIX(8, 1).slice(1) }),
    shared: m.kvLayout({ ...GEMMA, sharedKvLayers: 16 }),
    sharedAll: m.kvLayout({ ...GEMMA, sharedKvLayers: 48 }),
    sharedTooMany: m.kvLayout({ ...GEMMA, sharedKvLayers: 99 }),
    sharedNegative: m.kvLayout({ ...GEMMA, sharedKvLayers: -5 }),
    keyless: m.kvLayout({ blockCount: 4, headCount: 8, headCountKv: 8, valueLength: 128 }),
    noHeadWidthSwa: m.kvLayout({ ...GEMMA, keyLengthSwa: 0, valueLengthSwa: 0 }),
    hybrid: m.kvLayout({ blockCount: 4, headCount: 8, headCountKv: 8, keyLength: 128, valueLength: 128, headCountKvLayers: [0, 0, 8, 0] }),
    plain: m.kvLayout(META),
    plainWith: m.kvLayout({ ...META, keyLength: 128, valueLength: 128 }),
    noLayers: m.kvLayout({ ...GEMMA, blockCount: 0 }),
    noHeads: m.kvLayout({ blockCount: 4, keyLength: 128 }),
    zeroHeads: m.kvLayout({ ...GEMMA, headCountKvLayers: Array(48).fill(0) }),
    nothing: m.kvLayout(null),
    noMetaEstimate: gem(THREE, null),
    next: m.kvLayout(NEXT),
    nextArchDefault: m.kvLayout({ ...NEXT, fullAttentionInterval: 0 }),
    nextOtherArch: m.kvLayout({ ...NEXT, fullAttentionInterval: 0, architecture: "llama" }),
    nextEveryOther: m.kvLayout({ ...NEXT, fullAttentionInterval: 2 }),
    nextFlags: m.kvLayout({ ...NEXT, recurrentLayers: Array.from({ length: 48 }, (_, il) => (il % 6 === 5 ? 0 : 1)) }),
    nextShortFlags: m.kvLayout({ ...NEXT, recurrentLayers: [1, 1, 1, 0] }),
    nextAllRecurrent: m.kvLayout({ ...NEXT, recurrentLayers: Array(48).fill(1) }),
    nextKv: gem({ "tr-PARALLEL": { value: "1" } }, NEXT, { ctx: "262144", k: "q8_0", v: "q8_0" }),
    cells: [m.kvCells(180000, 1024, { slots: 3, unified: false, ubatch: 512, swaFull: false }),
            m.kvCells(180000, 1024, { slots: 4, unified: true, ubatch: 512, swaFull: false }),
            m.kvCells(180000, 0, { slots: 3, unified: false, ubatch: 512, swaFull: false }),
            m.kvCells(180000, 1024, { slots: 0, unified: false, ubatch: 512, swaFull: false }),
            m.kvCells(1000, 1024, { slots: 1, unified: false, ubatch: 512, swaFull: false })],
    autoSlots: m.AUTO_SLOTS,
  };

  // One rule for the form and for a stored config (cell-plan.js, 1.3.635): the cell the owner has, read off the form and off its
  // config, gives one cache and one figure of buffers — the machine page's bench and the cell window cannot say two sizes.
  {
    const P = await import(pathToFileURL(process.env.JS_ROOT + "/cell-plan.js").href);
    const CFG = { CTX_SIZE: "180000", CACHE_TYPE_K: "f16", CACHE_TYPE_V: "q8_0", PARALLEL: "3", KV_UNIFIED: "0", SWA_FULL: "1",
                  BATCH_SIZE: "2048", UBATCH_SIZE: "1024" };
    const BOXES = new Set(["KV_UNIFIED", "SWA_FULL"]);
    const formOf = (cfg) => Object.fromEntries(Object.entries(cfg).map(([k, v]) => [`tr-${k}`, BOXES.has(k) ? { type: "checkbox", checked: v === "1" } : { value: v }]));
    const both = (cfg, meta) => {
      globalThis.__fields = formOf(cfg);
      const form = [m.estimateKvCacheGb({ ggufMeta: meta }, "tr-"), m.estimateBatchBuffersGb({ ggufMeta: meta }, "tr-")];
      const fields = P.CellFields.ofConfig(cfg, {});
      return { form, config: [P.KvCache.gb(meta, fields), P.BatchBuffers.gb(meta, fields)] };
    };
    out.oneRule = { gemma: both(CFG, GEMMA), unified: both({ ...CFG, KV_UNIFIED: "1", SWA_FULL: "0" }, GEMMA),
                    next: both({ ...CFG, CTX_SIZE: "262144", CACHE_TYPE_V: "q8_0", PARALLEL: "1" }, NEXT) };
    // An empty field of the form reads the controller's default behind it, as it always did (`field || state.config`).
    const st = await import(pathToFileURL(process.env.JS_ROOT + "/state.js").href);
    const was = st.state;
    st.setState({ ...(was || {}), config: { ...(was?.config || {}), CTX_SIZE: "4096", CACHE_TYPE_K: "f16", CACHE_TYPE_V: "f16" } });
    globalThis.__fields = { "tr-CTX_SIZE": { value: "" } };
    const byDefault = m.estimateKvCacheGb(llama, "tr-");
    globalThis.__fields = { "tr-CTX_SIZE": { value: "4096" }, "tr-CACHE_TYPE_K": { value: "f16" }, "tr-CACHE_TYPE_V": { value: "f16" } };
    const said = m.estimateKvCacheGb(llama, "tr-");
    st.setState(was);
    out.formDefault = [round(byDefault, 4), round(said, 4)];
  }

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

  // The placement map: what plan N_GPU_LAYERS makes, its verdict, and that it says the split offloadSplit says — one plan.
  const plan = (ngl, s = running, extra = {}) => {
    cellIs(s); form({ "tr-N_GPU_LAYERS": { value: ngl }, ...extra });
    const box = { innerHTML: "", querySelectorAll: () => [], querySelector: () => null };
    globalThis.__fields["tr-placementMap"] = box;
    m.refreshPlacementMap("tr-");
    const h = box.innerHTML;
    const state = (name) => (h.match(new RegExp(`data-t="${name}" data-t-state="([a-zA-Z]+)"`)) || [])[1] ?? null;
    const ramText = (h.slice(h.indexOf('data-t="cell-remote-placement-ram"')).match(/data-place-text>([^<]*)</) || [])[1] ?? null;
    return { state: state("cell-remote-placement"), held: state("cell-remote-placement-held"), verdict: state("cell-remote-placement-verdict"),
             ramText, onCards: m.offloadSplit("tr-").layersGpu };
  };
  out.plan = { n999: plan("999"), autoRunning: plan("auto"), autoStopped: plan("auto", slot("stopped", {})), n40: plan("40"),
               row: plan("auto", running, { "tr-SPLIT_MODE": { value: "row" } }), cpu: plan("0") };
  // The same map drawn into another box — the cell window's Memory tab (cell-settings.js) — by the one rule of who has one.
  {
    const mount = (ngl, extra = {}) => {
      cellIs(running); form({ "tr-N_GPU_LAYERS": { value: ngl }, ...extra });
      const dialog = { innerHTML: "", querySelectorAll: () => [], querySelector: () => null };
      const win = { innerHTML: "was here", querySelectorAll: () => [], querySelector: () => null };
      globalThis.__fields["tr-placementMap"] = dialog;
      m.refreshPlacementMap("tr-");
      const drawn = m.mountPlacementMap("tr-", win);
      return [drawn, win.innerHTML === dialog.innerHTML, win.innerHTML.length > 0];
    };
    out.mountMap = { cards: mount("auto"), row: mount("auto", { "tr-SPLIT_MODE": { value: "row" } }), noBox: m.mountPlacementMap("tr-", null) };
  }
  // An MoE model: the map is told what its experts weigh, as GB, and the cache of its attention layers only.
  {
    globalThis.__stubReturns["form.modelsByPath"] = () => new Map([["next.gguf", { path: "next.gguf", sizeGb: 46.2, ggufMeta: NEXT }]]);
    globalThis.__stubReturns["form.modelChoiceOf"] = () => ({ model: "next.gguf", mmproj: "", draft: "" });
    cellIs(slot("stopped", {}));
    form({ "tr-MODEL_FILE": { value: "next.gguf" }, "tr-CTX_SIZE": { value: "262144" }, "tr-PARALLEL": { value: "1" } });
    const f = m.placementFacts("tr-");
    out.moeFacts = { experts: f.model.experts, expertBytes: Math.round(f.model.expertsGb * 1024 ** 3), kvGb: round(f.model.kvGb, 2),
                     weightsGb: f.model.weightsGb, layers: f.model.layers };
    globalThis.__stubReturns["form.modelsByPath"] = () => new Map([["next.gguf", { path: "next.gguf", sizeGb: 46.2, ggufMeta: { ...NEXT, expertBytes: 0 } }]]);
    out.moeFacts.unknownBytes = m.placementFacts("tr-").model.expertsGb;
    globalThis.__stubReturns["form.modelsByPath"] = () => new Map([["m70.gguf", llama]]);
    globalThis.__stubReturns["form.modelChoiceOf"] = () => ({ model: "m70.gguf", mmproj: "", draft: "" });
    out.moeFacts.dense = m.placementFacts("tr-").model.expertsGb;
  }

  // A speculative draft (2026-11-07): the estimate counts its file when the start loads it, and the map and the line above the tabs
  // place it — one figure (cellModelOf). The draft as the form names it (modelChoiceOf), its type and layers off the form's fields.
  {
    const DRAFT = { path: "mtp-m70.gguf", kind: "draft", sizeGb: 1.28, ggufMeta: { blockCount: 80 } };
    const rows = (list) => { globalThis.__stubReturns["form.modelsByPath"] = () => new Map(list.map((r) => [r.path, r])); };
    const named = (draft) => { globalThis.__stubReturns["form.modelChoiceOf"] = () => ({ model: "m70.gguf", mmproj: "", draft }); };
    // Two empty cards of 48 GB: the 70B and its draft fit whole.
    setCards([{ index: 0, name: "Card", memoryTotalMiB: 49152, memoryFreeMiB: 49152, memoryUsedMiB: 0 },
              { index: 1, name: "Card", memoryTotalMiB: 49152, memoryFreeMiB: 49152, memoryUsedMiB: 0 }]);
    cellIs(slot("stopped", {}));
    rows([llama, DRAFT]);
    const at = (extra = {}, draft = DRAFT.path) => {
      named(draft);
      form({ "tr-SPEC_TYPE": { value: "draft-mtp" }, ...extra });
      const e = m.estimateRuntimeMemoryGb("tr-");
      const s = m.offloadSplit("tr-");
      const f = m.placementFacts("tr-").model;
      return { runtime: round(e.runtimeSize, 2), files: round(e.fileTotalSize, 2), draftSize: e.draftSize, state: e.draft?.state ?? null,
               vram: round(s.vramGb, 2), ram: round(s.ramGb, 2), cards: round(f.draftCardsGb ?? 0, 2), inRam: round(f.draftRamGb ?? 0, 2) };
    };
    out.draftEst = {
      plain: at({ "tr-SPEC_TYPE": { value: "" } }, ""), mtp: at(), sidecarType: at({ "tr-SPEC_TYPE": { value: "" } }),
      none: at({ "tr-SPEC_TYPE": { value: "none" } }), ngram: at({ "tr-SPEC_TYPE": { value: "ngram-simple" } }),
      embed: at({ "tr-ENABLE_EMBEDDINGS": { type: "checkbox", checked: true } }), builtin: at({}, ""),
      ram: at({ "tr-SPEC_DRAFT_N_GPU_LAYERS": { value: "0" } }),
      unsized: (rows([llama]), at()),
    };
    rows([llama]);
    named("");
    setCards(cards());
  }

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
  {
    // What the cell serves is weighed, not what stands in MODEL_FILE: the owner's check said 36.6 GB of a 2 GB checkpoint, the first file of the list.
    const st = await import(pathToFileURL(process.env.JS_ROOT + "/state.js").href);
    const weighs = (said, files = []) => { field("1", "", "", "m205"); globalThis.__fields["tr-VLLM_MODEL"] = { value: said }; st.state.artifacts = files; const gb = m.VllmPlacement.of("tr-").weightsGb; st.state.artifacts = []; return gb; };
    {
      // The owner's Cosmos on a 3090: vLLM asked 0.88 GiB at a length of 8192 and refused where 0.5 GiB was left.
      const cosmos = { kvPerToken: 114688, contextLength: 262144 };
      const at = (config, weights = 2, model = cosmos) => { const p = m.VllmPlacement.from({ ENV: `CUDA_VISIBLE_DEVICES=${cards()[0].index}`, ...config }, cards(), weights, model); return [round(p.kvGb), p.kvOver]; };
      out.vllmKv = { asked: at({ MAX_MODEL_LEN: "8192" }), trained: at({}), tight: at({ MAX_MODEL_LEN: "8192", GPU_MEMORY_UTILIZATION: "0.2" }, 3), fp8: at({ MAX_MODEL_LEN: "8192", KV_CACHE_DTYPE: "fp8", GPU_MEMORY_UTILIZATION: "0.2" }, 3),
                     unknown: at({ MAX_MODEL_LEN: "8192", GPU_MEMORY_UTILIZATION: "0.2" }, 3, {}), noCard: (() => { const p = m.VllmPlacement.from({ MAX_MODEL_LEN: "8192" }, [], 2, cosmos); return [round(p.kvGb), p.kvOver]; })(),
                     spread: (() => { const p = m.VllmPlacement.from({ TENSOR_PARALLEL: "2", MAX_MODEL_LEN: "8192" }, cards(), 2, cosmos); return round(p.kvGb); })() };
      const tight = m.VllmPlacement.from({ ENV: `CUDA_VISIBLE_DEVICES=${cards()[0].index}`, MAX_MODEL_LEN: "8192", GPU_MEMORY_UTILIZATION: "0.2" }, cards(), 3, cosmos);
      out.vllmKvNote = tight.note();
    }
    out.vllmWeighs = {
      byItsField: weighs("/mnt/library/omni-awq"), itself: weighs("omni-awq"), trailingSlash: weighs("/mnt/library/omni-awq/"),
      checkpoint: weighs("/mnt/library/Cosmos/nvidia/BF16", [{ path: "Cosmos/nvidia/BF16", sizeGb: 2.1 }]),
      notInLibrary: weighs("Qwen/hub-only"), noField: weighs(""),
      lookalike: weighs("/mnt/library/not-omni-awq"),
    };
  }
  out.vllmNote = new m.VllmPlacement(1, 0.9, [cards()[0]], 2, 25.66).note();
  // CPU_OFFLOAD_GB: the weights that stay in RAM and come to the card for every pass.
  {
    const one = [cards()[0]];
    const facts = (p) => ({ onCard: round(p.weightsOnCardGb), rides: round(p.ridesGb), need: p.offloadNeededGb, over: p.weightsOver, note: p.note() });
    const from = (config, weights = 40) => m.VllmPlacement.from({ ENV: `CUDA_VISIBLE_DEVICES=${one[0].index}`, ...config }, cards(), weights);
    out.vllmOffload = {
      none: facts(from({})),
      enough: facts(from({ CPU_OFFLOAD_GB: "20" })),
      short: facts(from({ CPU_OFFLOAD_GB: "5" })),
      overdone: facts(from({ CPU_OFFLOAD_GB: "90" })),
      unsized: facts(from({ CPU_OFFLOAD_GB: "9" }, 0)),
      zero: facts(from({ CPU_OFFLOAD_GB: "0" }, 10)),
      words: facts(from({ CPU_OFFLOAD_GB: "abc" }, 10)),
      negative: facts(from({ CPU_OFFLOAD_GB: "-3" }, 10)),
      parallel: facts(m.VllmPlacement.from({ TENSOR_PARALLEL: "2", CPU_OFFLOAD_GB: "5" }, cards(), 60)),
      form: (() => { field("1", "", "", "omni-awq"); globalThis.__fields["tr-CPU_OFFLOAD_GB"] = { value: "7.5" }; return m.VllmPlacement.of("tr-").offloadGb; })(),
    };
    delete globalThis.__fields["tr-CPU_OFFLOAD_GB"];
  }
  // What the trips cost (DecodeSpeed): the owner's Cosmos-Reason2-2B BF16 (4.54 GiB) on the GPU machine's RTX 3090, PCIe 4.0 x8, 3 GiB left in RAM —
  // measured 2026-11-02 at 5.2–5.3 tokens/s, 182–184 with all of it on the card.
  {
    const c3090 = { index: "0", name: "NVIDIA GeForce RTX 3090", memoryTotalMiB: 24576, pcieGen: "4", pcieWidth: "8" };
    const at = (card, model, offload = "3", util = "0.2") => m.VllmPlacement.from({ ENV: "CUDA_VISIBLE_DEVICES=0", GPU_MEMORY_UTILIZATION: util, CPU_OFFLOAD_GB: offload }, [card], 4.54, model);
    const speedOf = (p) => (p.speed ? [Math.round(p.speed.now * 10) / 10, Math.round(p.speed.full), Math.round(p.speed.slower)] : null);
    const busless = { ...c3090, pcieGen: undefined, pcieWidth: undefined };
    out.vllmSpeed = {
      cosmos: [speedOf(at(c3090, { expertCount: 0 })), at(c3090, { expertCount: 0 }).note()],
      // As measured without the offload: util 0.45, all of it on the card (at 0.2 it does not fit, and the line says that).
      allOnCard: [speedOf(at(c3090, { expertCount: 0 }, "", "0.45")), at(c3090, { expertCount: 0 }, "", "0.45").note()],
      noBus: [speedOf(at(busless, { expertCount: 0 })), at(busless, { expertCount: 0 }).note()],
      experts: [speedOf(at(c3090, { expertCount: 128 })), at(c3090, { expertCount: 128 }).note()],
      unsaid: [speedOf(at(c3090, {})), speedOf(at(c3090, { expertCount: "0" }))],
    };
  }
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
    env = {"JS_ROOT": str(ROOT / "static" / "js"), "PATH": "/usr/bin:/bin",
           "JS_STUBS": "command-preview,favorites,llama-edit,form,remote-cells,cloud,topology-render,polling",
           "RUNNERS_JSON": json.dumps(Contract.table("controller")["runners"]),
           "CARD_CASES": json.dumps({"gpus": CARD_GPUS, "cases": CARD_CASES}), "GEMMA_META": json.dumps(gemma_meta()), "NEXT_META": json.dumps(next_meta())}
    proc = subprocess.run(probe_args(node, ROOT / "scripts" / "_js_harness.mjs", probe), capture_output=True, text=True, cwd=ROOT, env=env, timeout=60)
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
check(caps["custom"] == caps["voice-clone"] == {"cpu": True, "gpu": True, "auto": True},
      "custom и клон голоса (1.3.611) — с auto, по слову реестра (autoDevice), а не по ветке на id в браузере: ячейка сама берёт "
      "карту, когда на ней есть место, иначе CPU")
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
of = got["vllmOffload"]
check(of["none"] == {"onCard": 40, "rides": 0, "need": of["none"]["need"], "over": True, "note": of["none"]["note"]} and of["none"]["need"] > 0 and "do not fit" in of["none"]["note"],
      f"поля нет: веса на карте целиком, не влезает — сколько нужно оставить в RAM (получено {of['none']})")
check(of["enough"]["onCard"] == 20 and of["enough"]["rides"] == 20 and of["enough"]["over"] is False and "20.0 GB of the weights stay in RAM" in of["enough"]["note"],
      f"CPU_OFFLOAD_GB=20: на карте остальное, влезает, строка говорит о цене (получено {of['enough']})")
check(of["short"]["onCard"] == 35 and of["short"]["over"] is True and "do not fit" in of["short"]["note"], "мало оставили: по-прежнему не влезает, и строка о весах на карте")
check(of["overdone"]["onCard"] == 0 and of["overdone"]["rides"] == 40, "negative: больше, чем весов: на карте ноль, в RAM только то, что есть")
check(of["unsized"]["rides"] == 9 and of["unsized"]["need"] == 0 and of["unsized"]["over"] is False, "вес не известен: в RAM сказанное; нужно — 0, а не догадка")
check(of["zero"]["rides"] == 0 and of["words"]["rides"] == 0 and of["negative"]["rides"] == 0 and of["zero"]["note"] == "", "negative: 0, слово и минус: ничего в RAM, строки нет")
check(of["parallel"]["rides"] == 10 and of["parallel"]["onCard"] == 25, "tensor-parallel: на каждую карту: 2 × 5 ГБ в RAM, на карте по 30 − 5")
check(of["form"] == 7.5, "форма читает своё поле тем же правилом")
vs = got["vllmSpeed"]
check(vs["cosmos"][0] == [4.8, 192, 40] and "≈ 4.8 tokens/s, 40× slower than with all of them on the card (≈ 192)" in vs["cosmos"][1]
      and "not a measurement" in vs["cosmos"][1],
      f"Cosmos на 3090 PCIe 4.0 x8, 3 ГиБ в RAM: строка говорит ≈ 4,8 т/с и «в 40 раз», замер владельца 5,2–5,3 и 182–184 (получено {vs['cosmos']})")
check(vs["allOnCard"][0] == [192, 192, 1] and vs["allOnCard"][1] == "", "все веса на карте: оценка без перевозки, строки о цене нет")
check(vs["noBus"][0] is None and vs["noBus"][1].endswith("each pass takes longer for the trips."),
      "negative: шина карты не сказана (скаут до 2.45.0): прежние слова без числа, а не догадка")
check(vs["experts"][0] is None and "≈" not in vs["experts"][1], "negative: модель с экспертами читает часть весов на токен — правило о ней молчит")
check(vs["unsaid"] == [None, None], "negative: строка модели не сказала число экспертов (или сказала словом) — оценки нет")
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

print("карта памяти: RAM машины, а не контроллера:")
rs = got["ramShort"]
check(rs["machineFull"] == [True, True],
      f"в RAM машины свободно 4 ГБ, туда уходит ~15 ГБ весов — карта памяти говорит «не хватает RAM», хотя у контроллера свободно 64 ГБ "
      f"(было: сравнивалось с RAM контроллера, и нехватка на другой машине не показывалась) (got {rs['machineFull']})")
check(rs["machineRoomy"] == [True, False],
      f"negative: у машины свободно 60 ГБ — нехватки нет (got {rs['machineRoomy']})")
check(rs["machineSilent"] == [True, False],
      f"машина не сообщила RAM — нехватка не утверждается: неизвестное не рисуется отказом (got {rs['machineSilent']})")
ms = got["moeSplit"]
check(ms["byHand"] == {"known": False, "partial": False, "onCards": 40},
      f"эксперты вручную (N_CPU_MOE): строка над вкладками не называет деления, которого не знает — а не «0 слоёв на картах» (got {ms['byHand']})")
check(ms["fitted"]["known"] is True, "negative: без экспертов вручную деление известно")

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
check(chips["whisperNoPin"] == {"chips": [[0, True], [1, False]], "tile": "RTX 3090", "hook": True}
      and chips["whisperPinned"]["chips"] == [[0, False], [1, True]] and chips["whisperPinned"]["tile"] == "RTX 5090",
      f"whisper (2026-10-27): без пина выбрана карта 0 — туда он и пойдёт, плитка её называет; пин на 1 — RTX 5090 (получено {chips['whisperNoPin']}, {chips['whisperPinned']})")
check(chips["seamlessGpu"]["chips"] == [[0, True], [1, False]] and chips["seamlessCpu"]["chips"] == [],
      f"seamless на карте — выбор карты есть; на CPU — нет (получено {chips['seamlessGpu']['chips']}, {chips['seamlessCpu']['chips']})")
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
check(got["ramWireVllm"] == {"rides": [52531], "none": [None], "zero": [None]},
      f"vLLM с весами в RAM получает обещание на шкалу формы; negative: без них не спрашивает и не рисует (получено {got['ramWireVllm']})")
check(got["ramWire"] == {"strata": [[52531, 2048, ["cards", "hard", "ramPlan", "vramNote"]]], "omni": [None], "asking": ["tr-"]},
      "1.3.574: Strata (реестр говорит keepsRam) получает в полосу обещание памяти, которое у формы уже есть: 52531 МиБ и запас 2048; ячейка, что ничего не держит в ОЗУ "
      f"(qwen3-omni), — полосу как прежде, без обещания, и спрашивать ей не у кого (получено {got['ramWire']})")
check(got["ramUnknown"] == {"strata": [None], "asked": 1},
      "negative: пока контроллер не ответил, обещания в полосе нет — не чужое, не нулевое; а спросить он просит ровно один раз "
      f"(получено {got['ramUnknown']})")
server_pins = [RunnerCards.said("pinned", {"ENV": env}) for env, _ in CARD_CASES]
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
fe = got["freeEvery"]
check(fe["plan"] == {"takesFree": True, "everyCard": True} and fe["bar"] == {"hard": True, "cards": [0, 1], "vramNote": english("vramTakesFreeEvery")}
      and fe["gb"] == 50 and fe["known"] is True and fe["places"] == [{"index": "0", "gb": 20}, {"index": "1", "gb": 30}],
      f"Strata · DeepSeek (everyCard из реестра): полоса формы — на обеих картах, 20 + 30 ГБ, закрепление карты 1 её не меняет (получено {fe})")
check(fe["untold"] is False and fe["none"] is None and fe["zero"] is True,
      "negative: карта не сказала свободное — старт не известен; карт нет — старта нет; сказанный ноль известен")
check(got["aside"]["strataDsUntold"] and got["aside"]["strataDsUntold"][0][1] == 0,
      f"форма не рисует частичную оценку при неизвестной памяти карты: {got['aside']['strataDsUntold']}")
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

print("кэш KV модели со слоями разного рода (Gemma 4 12B, ячейка :22007, 2026-10-19):")
L = got["layers"]
GIB = 1024 ** 3
pad = lambda cells: -(-cells // 256) * 256  # noqa: E731 — llama.cpp rounds the cells of a cache up to 256
# What the engine takes, by hand: 8 layers over the whole context, one head of 512 (K and V, 2 bytes each in f16): 8 * 1 * 512 elements for each of K and V.
# 40 layers over a window, 8 heads of 256: 40 * 8 * 256. A cell of the owner's: 180000 tokens, 3 slots, no unified cache, physical batch 512.
FULL_K = 8 * 1 * 512
SWA_K = 40 * 8 * 256
f16 = lambda cells_full, cells_swa: (cells_full * (FULL_K + FULL_K) * 2 + cells_swa * (SWA_K + SWA_K) * 2) / GIB  # noqa: E731
three_slots = pad(-(-180000 // 3)) * 3            # 60160 each, as /slots said: 180480
swa_three = pad(min(pad(-(-180000 // 3)), 1024 + 512)) * 3
check(L["layout"] == {"full": {"k": FULL_K, "v": FULL_K}, "swa": {"k": SWA_K, "v": SWA_K}, "window": 1024},
      f"48 layers of the header: 8 keep the whole context (8 x 1 head x 512 = {FULL_K}), 40 a window of 1024 (40 x 8 heads x 256 = {SWA_K}) (got {L['layout']})")
check(three_slots == 180480 and swa_three == 4608, "the cells of the owner's cell: 3 x 60160 for the whole context, 3 x 1536 for the windows")
swa_owner = 3 * pad(min(pad(-(-180000 // 3)), 1024 + 2048))   # the owner's physical batch is 2048: 3 windows of 3072
check(abs(L["owner"] - f16(three_slots, swa_owner)) < 1e-9 and 5.5 < L["owner"] < 5.6,
      f"cell :22007 as the owner has it (180000 tokens, 3 slots, batch 2048, f16): {f16(three_slots, swa_owner):.3f} GB, not the 264 GB the form said (got {L['owner']})")
check(abs(L["threeSlots"] - f16(three_slots, swa_three)) < 1e-9 and 4.1 < L["threeSlots"] < 4.2 and L["threeSlots"] < L["owner"],
      f"the same with the engine's own physical batch (512, the field left empty): {f16(three_slots, swa_three):.3f} GB (got {L['threeSlots']})")
check(abs(L["auto"] - f16(pad(180000), pad(min(pad(180000), 1024 * 4 + 512)))) < 1e-9,
      "PARALLEL empty: llama-server takes 4 slots with ONE cache for them (server.cpp), so a window for each slot and the batch once")
check(abs(L["unified"] - f16(pad(180000), pad(1024 * 3 + 512))) < 1e-9,
      "a unified cache of 3 slots: the whole context once, 3 windows and the batch once")
check(L["unifiedOff"] == L["threeSlots"], "negative: KV_UNIFIED unchecked is the engine's default for a stated PARALLEL: slots of their own")
check(abs(L["swaFull"] - f16(three_slots, three_slots)) < 1e-9,
      "SWA_FULL: the windowed layers keep the whole context as well (--swa-full)")
check(abs(L["q8"] - L["threeSlots"] * 34 / 32 / 2) < 1e-9, "q8_0 is 34/32 bytes an element, not 2: the same cells, 17/32 of the f16 cache")
check(abs(L["mixed"] - (L["threeSlots"] + L["q8"]) / 2) < 1e-9, "K f16 and V q8_0: half of each")
check(abs(L["smallCtx"] - f16(3 * 256, 3 * 256)) < 1e-9,
      "a context that is less than a window: the windowed cache cannot be larger than the context (3 slots x 256 cells each, padded)")
check(abs(L["ubatch"] - f16(three_slots, swa_owner)) < 1e-9 and L["ubatch"] == L["owner"],
      "a physical batch of 2048 widens each window by 2048 (the batch field left empty does not hold it back)")
check(abs(L["ubatchUnderBatch"] - f16(three_slots, 3 * pad(1024 + 1024))) < 1e-9 and L["ubatchUnderBatch"] < L["ubatch"],
      "negative: a batch of 1024 holds the physical batch to 1024 (llama.cpp does): each window grows by 1024, not 2048")
check(abs(L["noFlags"] - (three_slots * (8 * 41 * 512 * 2) * 2) / GIB) < 1e-9 and L["layout_noFlags"]["window"] == 0
      and L["layout_noFlags"]["swa"] == {"k": 0, "v": 0},
      "a header that gives no flags for the windowed layers (an engine keeps them in its code): every layer over the whole context, "
      "the KV heads still one by one (8 x 41 heads x 512) — more than the engine takes, never less")
check(L["shortFlags"]["window"] == 0 and L["shortFlags"]["full"] == L["layout_noFlags"]["full"],
      "negative: 47 flags for 48 layers are no flags — none are used")
check(L["noWindow"]["window"] == 0 and L["noWindow"]["swa"] == {"k": 0, "v": 0} and L["noWindow"]["full"] == L["layout_noFlags"]["full"],
      "negative: flags and a window of 0: nothing is windowed")
check(L["shortHeads"] == {"full": {"k": 8 * 8 * 512, "v": 8 * 8 * 512}, "swa": {"k": SWA_K, "v": SWA_K}, "window": 1024},
      "negative: 47 numbers for 48 layers are no heads for each layer — the one count of the file (8) stands for every layer")
check(L["shared"] == {"full": {"k": 5 * 512, "v": 5 * 512}, "swa": {"k": 27 * 8 * 256, "v": 27 * 8 * 256}, "window": 1024},
      "the last 16 layers keep no cache of their own (shared_kv_layers): of the first 32, 5 keep the whole context and 27 a window")
check(L["sharedAll"] is None and L["sharedTooMany"] is None,
      "negative: every layer shared, or more of them than there are layers — no cache of its own at all: no estimate")
check(L["sharedNegative"] == L["layout"], "negative: a negative number of shared layers is none")
check(L["keyless"] is None,
      "negative: heads and a value width but no key width and nothing to take it from (no key_length, no embedding length): no layout, "
      "not a key cache of 0 beside a value cache")
check(L["noHeadWidthSwa"]["swa"] == {"k": 40 * 8 * 512, "v": 40 * 8 * 512},
      "negative: a file that gives no head width for the windowed layers: the full width")
check(L["hybrid"] == {"full": {"k": 8 * 128, "v": 8 * 128}, "swa": {"k": 0, "v": 0}, "window": 0},
      "layers with no KV heads (0) keep nothing: one layer of four, 8 heads of 128")
check(L["plain"] == L["plainWith"] == {"full": {"k": 80 * 8 * 128, "v": 80 * 8 * 128}, "swa": {"k": 0, "v": 0}, "window": 0},
      "a model with no window and one count of heads: every layer, 8 heads of 128, with and without key_length (embedding / heads)")
check(L["noLayers"] is None and L["noHeads"] is None and L["zeroHeads"] is None and L["nothing"] is None and L["noMetaEstimate"] == 0,
      "negative: no layer count, no heads, heads 0 in every layer, no header — no layout and no estimate (0 = n/a), not a number made up")
check(L["cells"] == [{"full": 180480, "swa": 4608}, {"full": 180224, "swa": 4608}, {"full": 180480, "swa": 0},
                     {"full": 180224, "swa": 1536}, {"full": 1024, "swa": 1024}],
      f"the cells: 3 slots 60160 + 1536 each; 4 slots in one cache 180224 + 4608; no window 180480 + 0; 0 slots are 1; a context under the window (got {L['cells']})")
check(L["autoSlots"] == 4, "a PARALLEL left empty is 4 slots (server.cpp: n_parallel is set to auto, using n_parallel = 4)")
attend = lambda n: {"full": {"k": n * 2 * 256, "v": n * 2 * 256}, "swa": {"k": 0, "v": 0}, "window": 0}  # noqa: E731
check(L["next"] == attend(12),
      f"Qwen3-Coder-Next attends in 12 of its 48 layers (full_attention_interval 4): the cache of 12, 2 heads of 256 (got {L['next']})")
check(L["nextArchDefault"] == attend(12),
      "a qwen3next header that names no interval: llama.cpp's own 4 for that family (src/models/qwen3next.cpp)")
check(L["nextOtherArch"] == attend(48),
      "negative: another architecture with no interval and no flags has no recurrent layer this can see — every layer keeps a cache")
check(L["nextEveryOther"] == attend(24), "an interval of 2: every second layer attends, 24 of 48")
check(L["nextFlags"] == attend(8), "flags for each layer (attention.recurrent_layers) win over the interval: 8 layers flagged 0")
check(L["nextShortFlags"] == attend(12), "negative: flags of another length than the layers are no flags — the interval says it")
check(L["nextAllRecurrent"] is None, "negative: every layer recurrent — no cache at all, so no layout and no estimate")
check(got["formDefault"] == [1.25, 1.25],
      "пустое поле формы читает значение контроллера за ним: контекст и типы кэша из state.config дают ту же цифру, что сказанные в поле "
      "(1.25 ГБ у плотной 70B на 4096 токенах f16)")
one = got["oneRule"]
check(all(v["form"] == v["config"] and v["form"][0] > 0 and v["form"][1] > 0 for v in one.values())
      and one["gemma"]["form"][0] != one["unified"]["form"][0],
      "одно правило (cell-plan.js): та же ячейка из формы и из сохранённого конфига — тот же кэш и те же буферы, у Gemma со слотами и "
      "окном, с общим кэшем и у гибрида; negative: общий кэш и полное окно меняют цифру — правило их правда читает")
check(abs(L["nextKv"] - 3.19) < 0.01,
      f"its 262144 tokens of q8_0 cache: 3.19 GB as llama.cpp keeps it, not the 12.75 of all 48 layers (got {L['nextKv']:.2f})")
mf = got["moeFacts"]
check(mf["experts"] == 512 and mf["expertBytes"] == 5008 and mf["layers"] == 48 and mf["kvGb"] == 3.19,
      f"the map is told the experts, what they weigh (5008 bytes, as GB) and the cache of 12 layers (got {mf})")
check(mf["unknownBytes"] == 0 and mf["dense"] == 0,
      "negative: experts whose bytes the header did not give weigh 0 — not known; a dense model's experts weigh nothing")
print()
print("черновик спекуляции в оценке формы, на карте памяти и в строке над вкладками (2026-11-07):")
de = got["draftEst"]
pl = de["plain"]
check(pl["draftSize"] == 0 and pl["state"] is None and pl["cards"] == 0 and pl["inRam"] == 0 and pl["ram"] == 0,
      f"без черновика — ничего о нём (got {pl})")
mtp = de["mtp"]
check(mtp["draftSize"] == 1.28 and mtp["state"] == "cards" and round(mtp["runtime"] - pl["runtime"], 2) == 1.28
      and round(mtp["files"] - pl["files"], 2) == 1.28 and round(mtp["vram"] - pl["vram"], 2) == 1.28 and mtp["cards"] == 1.28
      and mtp["inRam"] == 0,
      f"positive (дефект 2026-10-27): draft-mtp с файлом в библиотеке — +1.28 ГБ к файлам, к целому и к картам (got {mtp} против {pl})")
check(de["sidecarType"] == mtp, "тип не сказан, файл — голова MTP: грузится так же, и считается так же")
for name in ("none", "ngram", "embed", "builtin"):
    check({k: de[name][k] for k in ("runtime", "files", "vram", "ram", "draftSize", "state")}
          == {k: pl[k] for k in ("runtime", "files", "vram", "ram", "draftSize", "state")},
          f"negative ({name}): SPEC_TYPE none / ngram-* / ячейка эмбеддингов / draft-mtp без файла — черновик ничего не добавляет")
rm = de["ram"]
check(rm["state"] == "ram" and round(rm["runtime"] - pl["runtime"], 2) == 1.28 and rm["vram"] == pl["vram"] and rm["ram"] == 1.28
      and rm["cards"] == 0 and rm["inRam"] == 1.28,
      f"SPEC_DRAFT_N_GPU_LAYERS 0 — черновик в целом, но в RAM: карты те же, RAM +1.28 (got {rm})")
un = de["unsized"]
check(un["draftSize"] is None and un["state"] == "unsized" and un["runtime"] == pl["runtime"] and un["files"] == pl["files"],
      f"черновика нет в библиотеке — размер не известен (null, не 0), назван, а не прибавлен нулём (got {un})")
print()
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
check(au["running"]["auto"] == 80 and au["running"]["partial"] is False and au["stopped"]["auto"] == 16 and au["stopped"]["partial"] is True,
      f"auto у работающей ячейки — все 80 слоёв (своя память возвращается), у остановленной при тех же 14.1 ГБ свободных — 16 (получено {au['running']['auto']} и {au['stopped']['auto']}); "
      "в окне работающей ячейки это было «19/80 … 30 ГБ в ОЗУ» для весов, которые она держала целиком в видеопамяти")
check(au["stopped"]["cards"] == [[0, 6, 4.6], [1, 10, 6.6]],
      "16, как подгоняет llama.cpp (common/fit.cpp): на каждой карте — свой запас 1024 МиБ, буферы делятся между картами, и заполняются они "
      f"С ПОСЛЕДНЕЙ — 10 слоёв на 5090, 6 на 3090 (получено {au['stopped']['cards']}); прежняя оценка, 19, считала один запас 0.6 ГБ на обе")
check(au["tensorStopped"]["auto"] == 80 and au["tensorRunning"]["auto"] == 80 and au["tensorStopped"]["partial"] is False,
      "tensor: auto — все слои на картах, как есть на деле (llama.cpp: «llama_params_fit is not implemented for SPLIT_MODE_TENSOR»; замер 70B: 42.5 ГБ на двух картах), а не частичное деление, которого он не делает")
cs = got["cardsShare"]
check(cs["layer"]["cards"] == [[0, 34, 18.7], [1, 46, 24.7]] and cs["rowFollowsRoom"]["cards"] == cs["layer"]["cards"],
      "layer и row делят по комнате карт (24.0 : 31.8 → 34 и 46 слоёв), буферы — поровну на обе считающие карты "
      f"(замер работающей: 18350 + 24364 МиБ, по 1.0–1.1 ГБ сверх весов на каждой), получено {cs['layer']['cards']}")
check(cs["tensorEven"]["cards"] == [[0, 80, 21.7], [1, 80, 21.7]],
      "tensor без своих долей режет ровно пополам, какие бы карты ни были (замер: 21.1 + 21.4 ГБ), и каждая карта держит часть "
      f"КАЖДОГО из 80 слоёв, получено {cs['tensorEven']['cards']}")
check(cs["asymmetric"]["cards"][0][1] == 34 and cs["asymmetricStopped"]["cards"][0][1] == 15,
      "комната карты для весов — то, что она сообщает, плюс своё: 6.1 + 18.0 и 27.3 + 4.5 ГБ → 34 и 46 слоёв (карта, на которой ячейка сидела, не обделяется); "
      f"у остановленной — по сообщённому, 15 и 65 (получено {cs['asymmetric']['cards']} и {cs['asymmetricStopped']['cards']})")
check(cs["tensorBySize"]["cards"] == [[0, 80, 18.8], [1, 80, 24.6]] and cs["layerManual"]["cards"] == [[0, 20, 11.7], [1, 60, 31.8]],
      "свои доли оператора (24,32 или 1,3) решают в любом режиме — в том числе перебивают «ровно» у tensor "
      f"(получено {cs['tensorBySize']['cards']} и {cs['layerManual']['cards']})")

print("две карты, одна модель — карта памяти (где живёт модель):")
pl = got["plan"]
check(pl["autoRunning"]["state"] == "fitted" and pl["autoRunning"]["held"] is None and pl["autoRunning"]["verdict"] == "fits",
      "-ngl auto у работающей ячейки: llama.cpp подгоняет сам, и все слои помещаются — своя память ячейки возвращается")
check(pl["autoStopped"]["verdict"] == "spill" and pl["autoStopped"]["onCards"] == 16
      and pl["autoStopped"]["ramText"].startswith("≈ 64 layers"),
      "у остановленной та же подгонка выносит 64 слоя в RAM — и карта, и строка над вкладками (offloadSplit) говорят одно: "
      f"16 на картах, 64 в RAM — один план, а не две оценки (получено {pl['autoStopped']['onCards']}, {pl['autoStopped']['ramText']!r})")
check(pl["n999"]["state"] == "held" and pl["n999"]["held"] == "layers" and pl["n999"]["verdict"] == "fits" and pl["n999"]["onCards"] == 80,
      "999 у новой ячейки — -ngl задан: llama.cpp не подгоняет, и карта говорит это заметкой «удержано» (layers); все 80 слоёв влезают")
check(pl["n40"]["held"] == "layers" and pl["n40"]["verdict"] == "spill" and pl["n40"]["onCards"] == 40
      and pl["n40"]["ramText"].startswith("≈ 40 layers"),
      "40 вручную — ровно 40 на картах, 40 в RAM")
check(pl["row"]["state"] is None and pl["cpu"]["state"] is None,
      "negative: row (на этой сборке не стартует — плитка деления так и говорит) и CPU — карты памяти нет")
mm = got["mountMap"]
check(mm == {"cards": [True, True, True], "row": [False, True, False], "noBox": False},
      "та же карта рисуется в любую коробку — окна ячейки (cell-settings.js) — тем же правилом, что в диалоге; negative: у row "
      "карты нет — false, коробка опустошена, а не оставлена с прежним; коробки нет — false")

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
print("vLLM — что он весит: то, что в его поле, а не то, что в MODEL_FILE:")
vw = got["vllmWeighs"]
check((vw["byItsField"], vw["itself"], vw["trailingSlash"]) == (25.66, 25.66, 25.66), f"модель поля VLLM_MODEL, по полному пути на машине и по своему (получено {vw})")
check(vw["checkpoint"] == 2.1, f"папка-чекпойнт библиотеки: 2,1 ГБ, а не 20,5 ГБ файла из MODEL_FILE (получено {vw['checkpoint']})")
check((vw["notInLibrary"], vw["lookalike"]) == (0, 0), f"negative: модели нет в библиотеке — размера нет, а не чужой; имя, которое лишь кончается так же, — не она (получено {vw})")
check(vw["noField"] == 20.5, f"поле ещё пусто: остаётся выбранная модель, как было (получено {vw['noField']})")
print("vLLM — кэш KV одного запроса наибольшей длины:")
vk = got["vllmKv"]
check(vk["asked"] == [0.88, False], f"длина 8192 у Cosmos — те самые 0,88 ГиБ, которые назвал vLLM; на свободной карте влезает (получено {vk['asked']})")
check(vk["trained"][0] == 28.0 and vk["trained"][1] is True, f"длина не указана: vLLM берёт обученную, 262144, а это 28 ГиБ: не влезет, и это видно заранее (получено {vk['trained']})")
check(vk["tight"] == [0.88, True] and vk["fp8"] == [0.44, False], f"мало места: откажется; fp8 вдвое меньше, и теперь влезает (получено {vk['tight']}, {vk['fp8']})")
check(vk["unknown"] == [0, False] and vk["noCard"] == [0.88, False], f"negative: файл не сказал вес токена или карта не названа — не утверждается (получено {vk})")
check(vk["spread"] == 0.44, f"на двух картах — поровну (получено {vk['spread']})")
check("vLLM will refuse to start" in got["vllmKvNote"], f"строка под полосой говорит это словами (получено {got['vllmKvNote']})")
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
