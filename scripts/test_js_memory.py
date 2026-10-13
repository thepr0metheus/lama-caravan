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
  caps: Object.fromEntries(["vllm","whisper","moonshine","strata","gr00t","transcribe","seamless","translate","custom","llama-server","nonsense"].map((r) => [r, m.runnerDeviceCaps(r)])),
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
check(got["mode"] == {"vllm": "gpu", "whisper": "gpu", "moonshine": "cpu", "strata": "gpu", "gr00t": "gpu", "transcribe": "cpu"},
      "раннер с одним устройством называет его, что бы ни писал ENV; transcribe (оба) читает ENV — negative "
      f"(получено {got['mode']})")
check(got["cpuTileOff"] == {"strata": True, "gr00t": True, "vllm": True, "transcribe": False},
      f"плитка CPU у Strata, GR00T и vLLM не нажимается, у transcribe — нажимается (получено {got['cpuTileOff']})")

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

check(aside["gr00t"] == [["tr-", 7.5, True]] and got["fitGb"]["gr00t"] == 7.5,
      "GR00T — по своему плану: 7.5 ГБ, замер политики на RTX 5090 с запасом, а не сумма llama, которую ей передали "
      f"(получено {aside['gr00t']}, {got['fitGb']})")
check(got["fitGb"]["seamless"] != 7.5,
      f"negative: раннер без цифры в плане её не получает (получено {got['fitGb']['seamless']})")

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

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail: print("  - " + m)
    sys.exit(1)
print("js memory OK: настоящий модуль в node, оценка памяти значениями")
