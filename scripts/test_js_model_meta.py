#!/usr/bin/env python3
"""Snapshot of static/js/model-meta.js — the frontend's first snapshot.

Phase 7 starts here because `parseModelName` is what assembles a model's
chips on the board, and this exact family produced "absence drawn as
normal": an NLLB cell that looked like a gemma. VALUES are pinned against
REAL fleet filenames, not made-up ones.

The module is loaded into node FOR REAL (scripts/_js_harness.mjs): the four
neighbors that pull in the DOM and the whole app are replaced with stubs
carrying the same export names.

Run: python3 scripts/test_js_model_meta.py
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
const m = await import(pathToFileURL(process.env.JS_ROOT + "/model-meta.js").href);
const tx = (k) => "<" + k + ">";
const out = {
  parse: Object.fromEntries(JSON.parse(process.env.NAMES).map((n) => [n, m.parseModelName(n)])),
  parseEmpty: m.parseModelName(""),
  parseNull: m.parseModelName(null),
  price: Object.fromEntries([0, 0.4567, 0.05, 1.5, 2.10, 12.34, 150, 99.999].map((v) => [String(v), m.formatPricePer1M(v)])),
  priceNull: m.formatPricePer1M(null), priceUndef: m.formatPricePer1M(undefined), priceNaN: m.formatPricePer1M(NaN),
  mods: {
    va: m.modalitiesText({ modalities: { vision: true, audio: true } }),
    none: m.modalitiesText({ modalities: {} }),
    noneTx: m.modalitiesText({ modalities: {} }, tx),
    mmproj: m.modalitiesText({ mmproj: "x.gguf" }),
    bare: m.modalitiesText({}),
    bareTx: m.modalitiesText({}, tx),
    nullish: m.modalitiesText(null),
  },
  ctx: {
    given: m.topologyCtxInfo(),
  },
};
// topologyCtxInfo читает ui.latestSystemMonitor — подставляем через настоящий state.js
const st = await import(pathToFileURL(process.env.JS_ROOT + "/state.js").href);
st.ui.latestSystemMonitor = { latest: { llamaActivity: { context: { limit: 4096, tokens: 1024 } } } };
out.ctx.derived = m.topologyCtxInfo();
st.ui.latestSystemMonitor = { latest: { llamaActivity: { context: { limit: 4096, tokens: 1024, pct: 7 } } } };
out.ctx.explicit = m.topologyCtxInfo();
st.ui.latestSystemMonitor = { latest: { llamaActivity: { context: { tokens: 50 } } } };
out.ctx.noLimit = m.topologyCtxInfo();
console.log(JSON.stringify(out));
"""

# Real fleet filenames. The values are what the board MUST read from them.
NAMES = {
    "/x/models/gemma-4-12B-it-Q8_0.gguf":
        {"file": "gemma-4-12B-it-Q8_0", "label": "gemma-4-12B-it", "quant": "Q8_0", "size": "12B", "variant": "it"},
    "gemma-4-31B-it-Q4_K_S.gguf":
        {"file": "gemma-4-31B-it-Q4_K_S", "label": "gemma-4-31B-it", "quant": "Q4_K_S", "size": "31B", "variant": "it"},
    "Qwen3-Embedding-0.6B-f16.gguf":
        {"file": "Qwen3-Embedding-0.6B-f16", "label": "Qwen3-Embedding-0.6B", "quant": "f16", "size": "0.6B", "variant": ""},
    "gigaam-v3-e2e-rnnt-Q8_0.gguf":
        {"file": "gigaam-v3-e2e-rnnt-Q8_0", "label": "gigaam-v3-e2e-rnnt", "quant": "Q8_0", "size": "", "variant": ""},
    # Two names from golden with a tricky shape: the MoE suffix A3B and a dot in the version.
    "Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf":
        {"file": "Qwen3-Coder-30B-A3B-Instruct-Q4_K_M", "label": "Qwen3-Coder-30B-A3B-Instruct", "quant": "Q4_K_M", "size": "30B", "variant": "instruct"},
    "Qwen3.6-35B-A3B-UD-Q5_K_XL.gguf":
        {"file": "Qwen3.6-35B-A3B-UD-Q5_K_XL", "label": "Qwen3.6-35B-A3B-UD", "quant": "Q5_K_XL", "size": "35B", "variant": ""},
    # PINNED AS-IS: a trailing dot in the label — `-_ ` get trimmed, but not `.`.
    "Mixtral-8x7B-Instruct-v0.1.Q5_K_M.gguf":
        {"file": "Mixtral-8x7B-Instruct-v0.1.Q5_K_M", "label": "Mixtral-8x7B-Instruct-v0.1.", "quant": "Q5_K_M", "size": "8x7B", "variant": "instruct"},
}

node = find_node()
if node is None:
    print("js model-meta: SKIPPED — node не найден ни в PATH, ни у менеджеров версий: " + ", ".join(node_search_paths()))
    sys.exit(0)

probe = ROOT / "scripts" / ".probe_model_meta.tmp.mjs"
probe.write_text(PROBE, encoding="utf-8")
try:
    hook = f"data:text/javascript,import {{ register }} from 'node:module'; register('file://{ROOT}/scripts/_js_harness.mjs');"
    env = {"JS_ROOT": str(ROOT / "static" / "js"), "JS_STUBS": "form,cloud,topology-render,polling",
           "NAMES": json.dumps(list(NAMES)), "PATH": "/usr/bin:/bin"}
    proc = subprocess.run([node, "--import", hook, str(probe)], capture_output=True, text=True, cwd=ROOT, env=env, timeout=60)
finally:
    probe.unlink(missing_ok=True)
if proc.returncode != 0:
    print("js model-meta: FAILED — харнесс не отработал"); print(proc.stderr.strip()[:800]); sys.exit(1)
got = json.loads(proc.stdout.strip().splitlines()[-1])

print("parseModelName на именах флота:")
for name, want in NAMES.items():
    have = got["parse"].get(name)
    check(have == want, f"{name.split('/')[-1]}: {json.dumps(have, ensure_ascii=False)}")
check(got["parseEmpty"] is None and got["parseNull"] is None, "пустой и null путь → null, не пустая карточка")

print("formatPricePer1M:")
want_price = {"0": "$0", "0.4567": "$0.457", "0.05": "$0.05", "1.5": "$1.5", "2.1": "$2.1",
              "12.34": "$12.3", "150": "$150", "99.999": "$100"}
for k, v in want_price.items():
    check(got["price"].get(k) == v, f"{k} → {got['price'].get(k)!r} (ожидалось {v!r})")
check(got["priceNull"] == "" and got["priceUndef"] == "" and got["priceNaN"] == "",
      f"null/undefined/NaN → пустая строка, не «$NaN» (получено {got['priceNull']!r},{got['priceUndef']!r},{got['priceNaN']!r})")

print("modalitiesText:")
mods = got["mods"]
check(mods["va"] == "👁 vision · 🎙 audio", f"vision+audio → {mods['va']!r}")
check(mods["none"] == "text only", f"пустой словарь → {mods['none']!r}")
check(mods["noneTx"] == "<topologyTextOnly>", f"…и через переводчик → {mods['noneTx']!r}")
check(mods["mmproj"] == "on", f"без словаря, но с mmproj → {mods['mmproj']!r} (эвристика)")
check(mods["bare"] == "off", f"без словаря и без mmproj → {mods['bare']!r}")
check(mods["bareTx"] == "<topologyOff>", f"…и через переводчик → {mods['bareTx']!r}")
check(mods["nullish"] == "off", f"null-ячейка → {mods['nullish']!r}, не исключение")

print("topologyCtxInfo:")
ctx = got["ctx"]
check(ctx["given"] == {"tokens": 0, "limit": 0, "pct": None}, f"нет монитора → {ctx['given']}")
check(ctx["derived"] == {"tokens": 1024, "limit": 4096, "pct": 25}, f"pct вычислен из tokens/limit → {ctx['derived']}")
check(ctx["explicit"] == {"tokens": 1024, "limit": 4096, "pct": 7}, f"явный pct побеждает вычисленный → {ctx['explicit']}")
check(ctx["noLimit"] == {"tokens": 50, "limit": 0, "pct": None}, f"без лимита pct ОТСУТСТВУЕТ, не 0 и не ∞ → {ctx['noLimit']}")

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail: print("  - " + m)
    sys.exit(1)
print("js model-meta OK: настоящий модуль в node, значения на именах флота")
