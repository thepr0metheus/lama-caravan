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
from _node import find_node, node_search_paths  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


PROBE = r"""
import "./_js_globals.mjs";
import { pathToFileURL } from "node:url";
// The machine the cell form targets: its cards and its RAM, as its scout
// reported them. Exported by remote-cells, which is a stub here — the values
// must exist before the import, and the object is mutated between runs.
const TR_CPU = { ram: { totalGb: 64, usedGb: 60 } };
globalThis.__stubValues = { ...(globalThis.__stubValues || {}), "remote-cells._trClientCpu": TR_CPU,
  "remote-cells._trClientGpus": [{ index: 0, memoryTotalMiB: 8192, memoryFreeMiB: 8192, memoryUsedMiB: 0 }] };
const m = await import(pathToFileURL(process.env.JS_ROOT + "/memory.js").href);
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
  caps: Object.fromEntries(["vllm","whisper","moonshine","transcribe","seamless","translate","custom","llama-server","nonsense"].map((r) => [r, m.runnerDeviceCaps(r)])),
  // What the GPU tile WRITES. The split mode is decided in split-mode.js and
  // pinned there by value; what this pins is the wiring — that picking cards
  // is what applies it, and that one card leaves the flag unsaid.
  applied: await (async () => {
    const st = await import(pathToFileURL(process.env.JS_ROOT + "/state.js").href);
    st.setState({ gpu: { gpus: [gx(0), gx(1)] }, memory: { availableMiB: 65536 }, cpu: { physicalCores: 8, availableCores: 8 } });
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
      st.setState({ gpu: { gpus }, memory: { availableMiB: 65536 }, cpu: { physicalCores: 8, availableCores: 8 } });
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
           "JS_STUBS": "command-preview,favorites,llama-edit,form,remote-cells,cloud,topology-render,polling"}
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

print("runnerDeviceCaps:")
caps = got["caps"]
check(caps["vllm"] == {"cpu": False, "gpu": True, "auto": False} and caps["whisper"] == caps["vllm"], "vllm и whisper — только GPU")
check(caps["moonshine"] == {"cpu": True, "gpu": False, "auto": False}, "moonshine — только CPU")
check(all(caps[r] == {"cpu": True, "gpu": True, "auto": False} for r in ("transcribe", "seamless", "translate")),
      "transcribe/seamless/translate — оба, без auto")
check(caps["custom"] == {"cpu": True, "gpu": True, "auto": True}, "custom — единственный с auto")
check(caps["llama-server"] == caps["nonsense"] == {"cpu": True, "gpu": True, "auto": False},
      "llama-server и неизвестный раннер — умолчание: оба, без auto")

print("applyComputeTarget — что плитка пишет в поля:")
ap = got["applied"]
check(ap["bothBlank"] == {"DEVICE": "", "MAIN_GPU": "", "SPLIT_MODE": "row"},
      f"обе карты и пустой режим: DEVICE пуст (= все карты), деление тензорное (получено {ap['bothBlank']})")
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

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail: print("  - " + m)
    sys.exit(1)
print("js memory OK: настоящий модуль в node, оценка памяти значениями")
