#!/usr/bin/env python3
"""Снимок static/js/form.js — форма ячейки как её читает контроллер.

readConfigForm — единственное место, где 116 полей формы превращаются в
конфиг, который уходит на /api/config и дальше в командную строку сервера.
Ошибка здесь тихая: лишний пробел в порту, "0" вместо "" у необязательного
тумблера, модель прошлого раннера, уехавшая в слот vLLM. Пинятся ЗНАЧЕНИЯ:

- порт и числа обрезаются, чекбокс становится "1"/"0", отсутствующее поле — "";
- необязательный тумблер ТРЁХЗНАЧЕН: не трогали и в конфиге пусто → "" (даже
  при включённом чекбоксе), иначе — состояние чекбокса;
- RUNNER по умолчанию llama-server, для command-ячейки — custom, явный RUNNER
  побеждает; префикс формы ("tr-") читает свои поля, а не главные;
- vllm/whisper/moonshine/command сбрасывают MODEL_FILE/MMPROJ/DRAFT, а
  seamless/transcribe СОХРАНЯЮТ — как есть;
- LLAMA_MODELS_DIR: поле → state.paths.modelsDir, хвостовые слеши срезаны;
- badge НЕ экранирует текст, mbadge экранирует title и data-t, но не текст —
  как есть (все вызывающие подставляют свои строки, не пользовательские);
- mcFormatMtime зависит от локали Node — снимок гоняется под en_US/UTC.

DOM подменяется словарём полей (globalThis.__fields в _js_globals.mjs):
getElementById(id) отдаёт запись словаря или null, как браузер для
отсутствующего элемента. Модуль грузится НАСТОЯЩИЙ (_js_harness.mjs), вместе
с настоящими constants/i18n/utils/state/memory/command-preview.

Запуск: python3 scripts/test_js_form.py
"""
import json
import os
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
const st = await import(pathToFileURL(process.env.JS_ROOT + "/state.js").href);
const cst = await import(pathToFileURL(process.env.JS_ROOT + "/constants.js").href);
st.setState({ config: { KV_OFFLOAD: "0" }, paths: { modelsDir: "/srv/models/", llamaHome: "/opt/llama" }, chatTemplates: [], models: [] });
const m = await import(pathToFileURL(process.env.JS_ROOT + "/form.js").href);
const F = (o) => { globalThis.__fields = o; return m.readConfigForm(""); };
const base = { PORT: { value: " 22001 " }, MODEL_FILE: { value: "a.gguf" }, MMPROJ_FILE: { value: "mm.gguf" }, SPEC_DRAFT_MODEL_FILE: { value: "d.gguf" },
  ENABLE_FLASH_ATTN: { checked: true }, KV_OFFLOAD: { checked: true }, MMAP: { checked: true }, FIT: { checked: false } };
const pick = (c) => ({ PORT: c.PORT, MODEL_FILE: c.MODEL_FILE, MMPROJ_FILE: c.MMPROJ_FILE, DRAFT: c.SPEC_DRAFT_MODEL_FILE, RUNNER: c.RUNNER,
  KIND: c.CELL_KIND, DIR: c.LLAMA_MODELS_DIR, FA: c.ENABLE_FLASH_ATTN, KV: c.KV_OFFLOAD, MMAP: c.MMAP, FIT: c.FIT, THREADS: c.THREADS,
  COMMAND: c.COMMAND, VLLM: c.VLLM_MODEL, n: Object.keys(c).length });
const out = {
  exports: Object.keys(m).length,
  rc: {
    llama: pick(F(base)),
    dirField: pick(F({ ...base, LLAMA_MODELS_DIR: { value: "/x/y//" } })),
    seamless: pick(F({ ...base, RUNNER: { value: " seamless " } })),
    transcribe: pick(F({ ...base, RUNNER: { value: "transcribe" } })),
    vllm: pick(F({ ...base, RUNNER: { value: "vllm" }, VLLM_MODEL: { value: " org/m " } })),
    whisper: pick(F({ ...base, RUNNER: { value: "whisper" } })),
    moonshine: pick(F({ ...base, RUNNER: { value: "moonshine" } })),
    command: pick(F({ ...base, CELL_KIND: { value: "command" }, COMMAND: { value: " run.sh --x " } })),
    commandRunner: pick(F({ ...base, CELL_KIND: { value: "command" }, RUNNER: { value: "custom-x" } })),
    empty: pick(F({})),
  },
  tc: { undef: m.toggleChecked("KV_OFFLOAD", {}), blank: m.toggleChecked("KV_OFFLOAD", { KV_OFFLOAD: " " }),
        off: m.toggleChecked("KV_OFFLOAD", { KV_OFFLOAD: "0" }), yes: m.toggleChecked("MMAP", { MMAP: "YES" }),
        nonDefault: m.toggleChecked("ENABLE_MLOCK", {}), stateDefault: m.toggleChecked("KV_OFFLOAD") },
  paths: { qwen: [m.isQwenModelPath("Qwen3-8B.gguf"), m.isQwenModelPath("gemma"), m.isQwenModelPath(null)],
           g4: [m.isGemma4ModelPath("gemma-4-31b"), m.isGemma4ModelPath("gemma-3"), m.isGemma4ModelPath(undefined)] },
  oc: { noTpl: m.openClawQwenTemplatePath(), exists0: m.openClawQwenTemplateExists() },
  fmt: { badge: m.badge("<b>", "warn"), badgeNoKind: m.badge("x"),
         mbadge: m.mbadge("fault", "T", 'a"<b', "id<1"), mbadgePlain: m.mbadge("ok", "T"),
         label: m.modelOptionLabel({ path: "p.gguf", sizeGb: "4.1", capability: "vision_likely", suggestedMmproj: "mm" }),
         labelText: m.modelOptionLabel({ path: "p", sizeGb: 1 }),
         rec: [m.familyRecChipHtml("ENABLE_FLASH_ATTN", "1"), m.familyRecChipHtml("ENABLE_FLASH_ATTN", "0"),
               m.familyRecChipHtml("CTX_SIZE", " "), m.familyRecChipHtml("CTX_SIZE", "8<1")],
         mtime: [m.mcFormatMtime(0), m.mcFormatMtime(-5), m.mcFormatMtime("x"), m.mcFormatMtime(1700000000), m.mcFormatMtime("1700000000")] },
  gemma: { none: m.selectedGemma4Mmproj() },
};
globalThis.__fields = { "tr-PORT": { value: "9" }, PORT: { value: "1" } };
out.prefixed = m.readConfigForm("tr-").PORT;
const items = [{ dataset: { search: "Qwen3 8B" }, hidden: false }, { dataset: { search: "gemma" }, hidden: false }, { dataset: {}, hidden: false }];
m.mcFilterList({ children: items }, "QWEN"); out.filter = { q: items.map((i) => i.hidden) };
m.mcFilterList({ children: items }, ""); out.filter.blank = items.map((i) => i.hidden);
cst.dirtyOptionalToggles.add("FIT"); out.dirtyFit = pick(F(base)).FIT; cst.dirtyOptionalToggles.delete("FIT");
st.setState({ ...st.state, chatTemplates: [{ name: "OpenClaw Qwen", path: "/t/oq.jinja" }],
  models: [{ path: "a.gguf", suggestedMmproj: "mm-a.gguf" }], config: { ...st.state.config, MODEL_FILE: "a.gguf" } });
out.oc.withTpl = m.openClawQwenTemplatePath(); out.oc.exists1 = m.openClawQwenTemplateExists();
globalThis.__fields = { MODEL_FILE: { value: "a.gguf" } }; out.gemma.sel = m.selectedGemma4Mmproj();
out.byPath = [...m.modelsByPath().keys()];
console.log(JSON.stringify(out));
"""

node = find_node()
if node is None:
    print("js form: SKIPPED — node не найден ни в PATH, ни у менеджеров версий: " + ", ".join(node_search_paths()))
    sys.exit(0)

harness = ROOT / "scripts" / "_js_harness.mjs"
probe_path = ROOT / "scripts" / ".probe_js_form.tmp.mjs"
probe_path.write_text(PROBE)
try:
    env = {**os.environ, "JS_ROOT": str(ROOT / "static" / "js"),
           "JS_STUBS": "favorites,config-locator,llama-edit,polling,remote-cells,system-panels,cloud,topology-render,charts,dialogs",
           # mcFormatMtime — toLocaleDateString: значение зависит от локали и зоны Node.
           "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8", "TZ": "UTC"}
    run = subprocess.run(
        [node, "--import", f"data:text/javascript,import {{ register }} from 'node:module'; register('{harness.as_uri()}');",
         str(probe_path)], capture_output=True, text=True, env=env, cwd=ROOT, timeout=60)
finally:
    probe_path.unlink(missing_ok=True)
if run.returncode != 0:
    print(run.stdout); print(run.stderr)
    print("js form FAILED: node вышел с кодом %d" % run.returncode)
    sys.exit(1)
got = json.loads(run.stdout.strip().splitlines()[-1])

print("модуль:")
check(got["exports"] == 44, "form.js экспортирует 44 функции (пересчитай при изменении охвата)")

print("readConfigForm — поля:")
rc = got["rc"]
check(rc["llama"]["n"] == 116 and rc["empty"]["n"] == 116, "конфиг всегда из 116 ключей, даже с пустой формы")
check(rc["llama"]["PORT"] == "22001", "порт обрезан от пробелов")
check(rc["llama"]["FA"] == "1" and rc["empty"]["FA"] == "0", "чекбокс → \"1\"; отсутствующий чекбокс → \"0\"")
check(rc["llama"]["THREADS"] == "", "отсутствующее числовое поле → \"\", не undefined")
check(rc["llama"]["KV"] == "1", "необязательный тумблер со значением в конфиге читает чекбокс")
check(rc["llama"]["MMAP"] == "" and rc["llama"]["FIT"] == "",
      "необязательный тумблер без значения и не тронутый → \"\" — даже при включённом чекбоксе")
check(got["dirtyFit"] == "0", "тронутый (dirty) необязательный тумблер читает чекбокс: \"0\"")
check(got["prefixed"] == "9", "префикс формы \"tr-\" читает tr-PORT, а не PORT")

print("readConfigForm — раннер:")
check(rc["llama"]["RUNNER"] == "llama-server" and rc["llama"]["KIND"] == "", "RUNNER по умолчанию llama-server")
check(rc["command"]["RUNNER"] == "custom" and rc["command"]["KIND"] == "command" and rc["command"]["COMMAND"] == "run.sh --x",
      "command-ячейка: RUNNER custom, COMMAND обрезан")
check(rc["commandRunner"]["RUNNER"] == "custom-x", "явный RUNNER побеждает умолчание command-ячейки")
check(rc["seamless"]["RUNNER"] == "seamless", "RUNNER обрезан от пробелов")
check(all(rc[r]["MODEL_FILE"] == "" and rc[r]["MMPROJ_FILE"] == "" and rc[r]["DRAFT"] == "" for r in ("vllm", "whisper", "moonshine", "command")),
      "vllm/whisper/moonshine/command сбрасывают MODEL_FILE, MMPROJ_FILE, SPEC_DRAFT_MODEL_FILE")
check(rc["vllm"]["VLLM"] == "org/m", "VLLM_MODEL обрезан")
check(all(rc[r]["MODEL_FILE"] == "a.gguf" and rc[r]["MMPROJ_FILE"] == "mm.gguf" and rc[r]["DRAFT"] == "d.gguf" for r in ("seamless", "transcribe")),
      "seamless/transcribe СОХРАНЯЮТ модель — как есть, не в списке сброса")

print("readConfigForm — каталог моделей:")
check(rc["llama"]["DIR"] == "/srv/models", "без поля — state.paths.modelsDir, хвостовой слеш срезан")
check(rc["dirField"]["DIR"] == "/x/y", "поле побеждает state, двойной хвостовой слеш срезан")

print("toggleChecked:")
tc = got["tc"]
check(tc["undef"] is True and tc["blank"] is True, "KV_OFFLOAD без значения/пробел → включён по умолчанию")
check(tc["off"] is False and tc["yes"] is True, "\"0\" → выкл, \"YES\" → вкл (formatBool)")
check(tc["nonDefault"] is False, "ENABLE_MLOCK без значения → выкл (не в списке default-on)")
check(tc["stateDefault"] is False, "без второго аргумента читает state.config (KV_OFFLOAD=\"0\")")

print("пути и шаблоны:")
check(got["paths"]["qwen"] == [True, False, False] and got["paths"]["g4"] == [True, False, False],
      "isQwenModelPath/isGemma4ModelPath: регистронезависимо, null/undefined → false")
oc = got["oc"]
check(oc["noTpl"] == "/opt/llama/models/templates/openclaw-qwen.jinja" and oc["exists0"] is False,
      "без шаблонов — путь из state.paths.llamaHome, exists=false")
check(oc["withTpl"] == "/t/oq.jinja" and oc["exists1"] is True, "шаблон с openclaw+qwen в имени найден по регэкспу, exists=true")
check(got["gemma"]["none"] == "gemma-4-31b-it/q4-k-m/mmproj-gemma-4-31B-it-f32.gguf", "Gemma-4 mmproj без выбора — константа по умолчанию")
check(got["gemma"]["sel"] == "mm-a.gguf", "выбранная модель с suggestedMmproj побеждает умолчание")
check(got["byPath"] == ["a.gguf"], "modelsByPath — Map по path из state.models")

print("форматтеры:")
fmt = got["fmt"]
check(fmt["badge"] == '<span class="badge warn"><b></span>', "badge НЕ экранирует текст — как есть")
check(fmt["badgeNoKind"] == '<span class="badge ">x</span>', "badge без kind — пустой класс с пробелом, как есть")
check(fmt["mbadge"] == '<span class="mbadge mbadge-fault" title="a&quot;&lt;b" data-t="id&lt;1">T</span>',
      "mbadge экранирует title и data-t")
check(fmt["mbadgePlain"] == '<span class="mbadge mbadge-ok">T</span>', "mbadge без title/testId — без атрибутов")
check(fmt["label"] == "p.gguf (4.1 GB) - 👁 Vision likely / 📷 Proj ✓", "modelOptionLabel: vision + projector")
check(fmt["labelText"] == "p (1 GB) - Text", "modelOptionLabel: текстовая модель без проектора")
check(fmt["rec"][0].endswith('<span class="insight-family-val">on</span></span>') and ' set"' in fmt["rec"][0],
      "familyRecChipHtml: тумблер \"1\" → on/set")
check(' off"' in fmt["rec"][1] and 'val">off<' in fmt["rec"][1], "familyRecChipHtml: тумблер \"0\" → off/off")
check(' off"' in fmt["rec"][2] and 'val">remove<' in fmt["rec"][2], "familyRecChipHtml: пустое значение → remove/off")
check(' set"' in fmt["rec"][3] and 'val">8&lt;1<' in fmt["rec"][3], "familyRecChipHtml: значение экранировано")
check(fmt["mtime"][:3] == ["", "", ""], "mcFormatMtime: 0, отрицательное, мусор → \"\"")
check(fmt["mtime"][3] == "Nov 14, 2023" and fmt["mtime"][4] == "Nov 14, 2023", "mcFormatMtime: секунды (число и строка) → короткая дата en_US")

print("mcFilterList:")
check(got["filter"]["q"] == [False, True, True], "фильтр регистронезависим; элемент без data-search прячется")
check(got["filter"]["blank"] == [False, False, False], "пустой запрос показывает всё")

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail: print("  - " + m)
    sys.exit(1)
print("js form OK: настоящий модуль в node, форма ячейки значениями")
