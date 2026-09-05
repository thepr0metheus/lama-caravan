#!/usr/bin/env python3
"""Снимок static/js/memory.js — «влезет ли модель», число, которому оператор верит.

Оценщик памяти рисует на карточке ячейки пилюлю OK / Near limit / Over VRAM.
Ошибка здесь — тот самый класс «отсутствие, нарисованное как норма»: карта,
уже занятая другой моделью, не должна выглядеть свободной. Пинятся ЗНАЧЕНИЯ:
сравнение со СВОБОДНОЙ памятью, а не с общей; границы запаса ровно ±1 ГБ;
суммирование двух карт; «n/a» вместо нуля; байты на элемент кеша по типу
кванта; таблица «CPU/GPU/auto» по раннеру.

Модуль грузится в node НАСТОЯЩИЙ (scripts/_js_harness.mjs); i18n настоящий.

Запуск: python3 scripts/test_js_memory.py
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
const m = await import(pathToFileURL(process.env.JS_ROOT + "/memory.js").href);
const g = (total, free, used) => ({ memoryTotalMiB: total, memoryFreeMiB: free, memoryUsedMiB: used });
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
};
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

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail: print("  - " + m)
    sys.exit(1)
print("js memory OK: настоящий модуль в node, оценка памяти значениями")
