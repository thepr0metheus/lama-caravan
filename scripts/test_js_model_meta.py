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
  repo: Object.fromEntries(JSON.parse(process.env.REPOS).map((n) => [n, m.repoOnlyWords(n)])),
  repoOdd: [m.repoOnlyWords(""), m.repoOnlyWords(null), m.repoOnlyWords(undefined), m.repoOnlyWords("Coder-Q4.gguf"), m.repoOnlyWords(42)],
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
  // The controller's own server's context window (read from its monitor) went
  // with its cells in step 6.9, together with the detail modal that showed it.
  ctxGone: "topologyCtxInfo" in m,
};
console.log(JSON.stringify(out));
"""

# Real fleet filenames. The values are what the board MUST read from them.
NAMES = {
    "Ternary-Bonsai-2-27B-PQ2_0.gguf":
        {"file": "Ternary-Bonsai-2-27B-PQ2_0", "label": "Ternary-Bonsai-2-27B", "quant": "PQ2_0", "size": "27B", "variant": ""},
    "Bonsai-PTQ1_0.gguf":
        {"file": "Bonsai-PTQ1_0", "label": "Bonsai", "quant": "PTQ1_0", "size": "", "variant": ""},
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

# The library's real paths: <repo>/<author>/<quant>/<file>. Which word the repository's name has and the file's has not.
REPOS = {
    # ISTA-DASLab's Coder package is named after the base model: the word "Coder" is in the folder only (the owner, 2026-10-18).
    "Qwen3.8-Flash-Next-GSQ-RCO-Coder-GGUF/ISTA-DASLab/IQ1_M/Qwen3.8-Flash-Next-GSQ-RCO-IQ1_M-00001-of-00002.gguf": ["Coder"],
    # negative: the base model's packages, the Swift fine-tune's and Unsloth's say nothing the file does not say
    "Qwen3.8-Flash-Next-GSQ-RCO-GGUF/ISTA-DASLab/IQ2_XS/Qwen3.8-Flash-Next-GSQ-RCO-IQ2_XS-00001-of-00002.gguf": [],
    "Swift-1.5-Qwen3.8-Flash-Next-GSQ-RCO-GGUF/ukisai/IQ3_XXS/Swift-Qwen3.8-Flash-Next-GSQ-RCO-IQ3_XXS-00001-of-00002.gguf": [],
    "Qwen3.8-Flash-Next-GGUF/unsloth/UD-IQ4_XS/Qwen3.8-Flash-Next-UD-IQ4_XS-00001-of-00003.gguf": [],
    # negative: the file says it too — no second chip for the same word
    "Qwen3-Coder-30B-A3B-Instruct-GGUF/unsloth/Q4_K_M/Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf": [],
    "Qwen3-Coder-Next-GGUF/unsloth/Q4_0/Qwen3-Coder-Next-Q4_0.gguf": [],
    "27B-TURBO-Fable-Cold-Fusion-735-882-Heretic-Uncensored-NEO-CODER-MAX-MTP-GGUF/DavidAU/Q5_K_S/Qwen3.8-27B-TurboFCFusion-735-882-Here-Uncen-NEO-CODER-MAX-Q5_K_S.gguf": [],
    # the word in lower case in the folder, and the file says "coding", which is not the word
    "gemma-4-12B-coder-fable5-composer2.5-v1-GGUF/yuxinlu1/Q8_0/gemma4-coding-Q8_0.gguf": ["Coder"],
    # a word counts whole: "Decoder" is not "Coder", and "Coderlike" is not either
    "Foo-Decoder-GGUF/a/Q4/foo-Q4.gguf": [],
    "Foo-Coderlike-GGUF/a/Q4/foo-Q4.gguf": [],
    "qwen-CODER-gguf/a/Q4/qwen-q4.gguf": ["Coder"],
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
           "NAMES": json.dumps(list(NAMES)), "REPOS": json.dumps(list(REPOS)), "PATH": "/usr/bin:/bin"}
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

print("repoOnlyWords на путях библиотеки:")
for path, want in REPOS.items():
    have = got["repo"].get(path)
    check(have == want, f"{path.split('/')[0][:48]}…/{path.split('/')[-1][:44]}: {have}")
check(got["repoOdd"] == [[], [], [], [], []],
      f"negative: пустой путь, null, undefined, имя файла без папки («Coder-Q4.gguf» — слово в имени файла, а не репозитория) и число → слов нет, не исключение (получено {got['repoOdd']})")

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

print("окно одиночного сервера контроллера:")
check(got["ctxGone"] is False, "negative: topologyCtxInfo больше нет — окно одиночного сервера контроллера ушло с его ячейками (шаг 6.9)")

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail: print("  - " + m)
    sys.exit(1)
print("js model-meta OK: настоящий модуль в node, значения на именах флота")
