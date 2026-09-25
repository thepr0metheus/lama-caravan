#!/usr/bin/env python3
"""Snapshot of static/js/form.js — the cell form the way the controller reads it.

readConfigForm is the single place where 135 form fields turn into the
config that goes out to /api/config and, from there, into the server's
command line. A bug here is silent: a stray space in the port, "0" instead
of "" on an optional toggle, a previous runner's model stranded in the vLLM
slot. VALUES are pinned:

- port and numbers are trimmed, a checkbox becomes "1"/"0", a missing field
  becomes "";
- an optional toggle is THREE-VALUED: untouched with an empty config →
  "" (even with the checkbox on), otherwise the checkbox's own state;
- RUNNER defaults to llama-server, to custom for a command cell, an explicit
  RUNNER wins; a form prefix ("tr-") reads its own fields, not the main ones;
- vllm/whisper/moonshine/command clear MODEL_FILE/MMPROJ/DRAFT, while
  seamless/transcribe KEEP them — as-is;
- LLAMA_MODELS_DIR: field → state.paths.modelsDir, trailing slashes trimmed;
- badge does NOT escape its text, mbadge escapes title and data-t but not the
  text — as-is (every caller passes its own strings, never user input);
- mcFormatMtime depends on Node's locale — the snapshot runs under en_US/UTC;
- a file only a library holds is a picker row like any other, with a 📚 chip
  naming the library (escaped: the name is the operator's).

The DOM is replaced by a field dict (globalThis.__fields in _js_globals.mjs):
getElementById(id) returns the dict's entry or null, the same as a browser
would for a missing element. The module is loaded FOR REAL (_js_harness.mjs),
together with the real constants/i18n/utils/state/memory/command-preview.

Run: python3 scripts/test_js_form.py
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
  paths: { qwen: [m.isQwenModelPath("Qwen3-8B.gguf"), m.isQwenModelPath("gemma"), m.isQwenModelPath(null)] },
  classicGone: ["isGemma4ModelPath", "selectedGemma4Mmproj", "setGemma4Mode", "ensureGemma4MtpFields", "setInputValue",
                "maybeAutofillModelHelpers", "maybeAutofillChatTemplate", "renderStaticConfigFields", "renderRaw"]
    .filter((n) => n in m),
  oc: { noTpl: m.openClawQwenTemplatePath(), exists0: m.openClawQwenTemplateExists() },
  fmt: { badge: m.badge("<b>", "warn"), badgeNoKind: m.badge("x"),
         mbadge: m.mbadge("fault", "T", 'a"<b', "id<1"), mbadgePlain: m.mbadge("ok", "T"),
         label: m.modelOptionLabel({ path: "p.gguf", sizeGb: "4.1", capability: "vision_likely", suggestedMmproj: "mm" }),
         labelText: m.modelOptionLabel({ path: "p", sizeGb: 1 }),
         rec: [m.familyRecChipHtml("ENABLE_FLASH_ATTN", "1"), m.familyRecChipHtml("ENABLE_FLASH_ATTN", "0"),
               m.familyRecChipHtml("CTX_SIZE", " "), m.familyRecChipHtml("CTX_SIZE", "8<1")],
         mtime: [m.mcFormatMtime(0), m.mcFormatMtime(-5), m.mcFormatMtime("x"), m.mcFormatMtime(1700000000), m.mcFormatMtime("1700000000")],
         jobs: { llm: m.jobChips(["llm"]), two: m.jobChips(["asr", "tts"]),
                 none: m.jobChips([]), unknown: m.jobChips(["sorcery"]),
                 compound: m.jobChips(["speech-translate"]) } },
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
out.byPath = [...m.modelsByPath().keys()];
// 🎓 beside CTX_SIZE — the trained window in one press.
st.setState({ ...st.state, models: [{ path: "a.gguf", ggufMeta: { contextLength: 262144 } }] });
globalThis.__fields = { "te-MODEL_FILE": { value: "a.gguf" }, "te-CTX_SIZE": { value: "", placeholder: "", dataset: {} } };
out.ctxNative = { gguf: m.ctxNativeFor("te-") };
globalThis.__fields = { "te-MODEL_FILE": { value: "a.gguf" }, "te-CTX_SIZE": { value: "", placeholder: "4096", dataset: { trained: "131072" } } };
out.ctxNative.ggufWins = m.ctxNativeFor("te-");
globalThis.__fields = { "te-MODEL_FILE": { value: "elsewhere.gguf" }, "te-CTX_SIZE": { value: "", placeholder: "4096", dataset: { trained: "131072" } } };
out.ctxNative.running = m.ctxNativeFor("te-");
globalThis.__fields = { "te-MODEL_FILE": { value: "" }, "te-CTX_SIZE": { value: "", placeholder: "4096", dataset: {} } };
out.ctxNative.placeholder = m.ctxNativeFor("te-");
globalThis.__fields = { "te-CTX_SIZE": { value: "", placeholder: "", dataset: {} } };
out.ctxNative.unknown = m.ctxNativeFor("te-");
out.ctxNative.state = [m.ctxNativeButtonState(262144, ""), m.ctxNativeButtonState(262144, "262144"),
                       m.ctxNativeButtonState(0, "5"), m.ctxNativeButtonState(32768, "32768").label];
globalThis.__fields = { "te-MODEL_FILE": { value: "a.gguf" }, "te-CTX_SIZE": { value: "100000", placeholder: "", dataset: {} } };
out.ctxNative.apply = [m.applyCtxNative("te-"), globalThis.__fields["te-CTX_SIZE"].value];
globalThis.__fields = { "te-CTX_SIZE": { value: "100000", placeholder: "", dataset: {} } };
out.ctxNative.applyNothing = [m.applyCtxNative("te-"), globalThis.__fields["te-CTX_SIZE"].value];
// The picker row of a file only a library holds — a fake list, the real renderer.
{
  const kids = [];
  const list = { innerHTML: "", appendChild: (el) => kids.push(el) };
  const trigger = { innerHTML: "", appendChild() {} };
  const wrap = { classList: { contains: (c) => c === "mc-wrap" },
                 querySelector: (q) => (q === ".mc-list" ? list : q === ".mc-trigger" ? trigger : null) };
  const made = document.createElement;
  document.createElement = () => ({ className: "", dataset: {}, style: {}, classList: { add() {} }, setAttribute() {},
                                    addEventListener() {}, appendChild() {}, innerHTML: "", textContent: "" });
  m.updateModelComboboxItems({ previousElementSibling: wrap, value: "" }, [
    { value: "M/a/Q4/m-Q4.gguf", kind: "model", sizeGb: 4, libraryOnly: true, store: { id: "lib-a", name: "N<AS" } },
    { value: "M/a/Q8/m-Q8.gguf", kind: "model", sizeGb: 8 }], "");
  document.createElement = made;
  const lib = (h) => (h.match(/<span class="mbadge mbadge-lib"[^>]*>[^<]*<\/span>/) || [null])[0];
  out.libRows = kids.map((el) => ({ lib: lib(el.innerHTML), llama: el.innerHTML.includes("🦙") }));
}
// The picker as a whole: renderModelSelects carries a library row's place onto
// the model, projector and draft pickers alike.
{
  const fakeSelect = () => {
    const kids = [];
    const list = { innerHTML: "", appendChild: (el) => kids.push(el) };
    const trigger = { innerHTML: "", appendChild() {} };
    const wrap = { classList: { contains: (c) => c === "mc-wrap", toggle() {}, add() {} },
                   querySelector: (q) => (q === ".mc-list" ? list : q === ".mc-trigger" ? trigger : null) };
    return { kids, sel: { value: "", dataset: {}, innerHTML: "", appendChild() {}, previousElementSibling: wrap } };
  };
  const [pm, pp, pd] = [fakeSelect(), fakeSelect(), fakeSelect()];
  const lib = { id: "lib-a", name: "NAS" };
  st.setState({ ...st.state, config: {}, models: [
    { path: "L/a/Q4/lib-Q4.gguf", kind: "model", sizeGb: 4, libraryOnly: true, store: lib },
    { path: "L/a/Q4/loc-Q4.gguf", kind: "model", sizeGb: 4 },
    { path: "L/a/Q4/mmproj-lib.gguf", kind: "mmproj", sizeGb: 1, libraryOnly: true, store: lib },
    { path: "L/a/Q4/mtp-lib.gguf", kind: "draft", sizeGb: 1, libraryOnly: true, store: lib }] });
  globalThis.__fields = { MODEL_FILE: pm.sel, MMPROJ_FILE: pp.sel, SPEC_DRAFT_MODEL_FILE: pd.sel };
  (globalThis.__stubReturns ||= {})["llama-edit.runnerRegistry"] = () => [];
  const made = document.createElement;
  document.createElement = () => ({ className: "", dataset: {}, style: {}, classList: { add() {}, toggle() {} }, setAttribute() {},
                                    addEventListener() {}, appendChild() {}, innerHTML: "", textContent: "" });
  // The insight panels after the pickers want a real page; the pickers are drawn by then.
  try { m.renderModelSelects(""); } catch (e) { out.pickerMapError = String((e && e.message) || e); }
  document.createElement = made;
  const rows = (p) => p.kids.filter((el) => String(el.dataset.value || "").startsWith("L/"))
    .map((el) => [el.dataset.value, el.innerHTML.includes('data-t="model-in-library"')]);
  out.pickerMap = { model: rows(pm), mmproj: rows(pp), draft: rows(pd) };
}
// A safetensors folder is offered where the form's machine reads the
// controller's models tree — asked of remote-cells, the one place that knows.
{
  const pickFor = (reads) => {
    const kids = [];
    const list = { innerHTML: "", appendChild: (el) => kids.push(el) };
    const trigger = { innerHTML: "", appendChild() {} };
    const wrap = { classList: { contains: (c) => c === "mc-wrap", toggle() {}, add() {} },
                   querySelector: (q) => (q === ".mc-list" ? list : q === ".mc-trigger" ? trigger : null) };
    st.setState({ ...st.state, config: {}, models: [], artifacts: [
      { path: "org/Qwen-ST", name: "Qwen-ST", sizeGb: 16, format: "safetensors", arch: "qwen2" }] });
    const other = () => {
      const l = { innerHTML: "", appendChild() {} }, tr = { innerHTML: "", appendChild() {} };
      return { value: "", dataset: {}, innerHTML: "", appendChild() {},
               previousElementSibling: { classList: { contains: (c) => c === "mc-wrap", toggle() {}, add() {} },
                                         querySelector: (q) => (q === ".mc-list" ? l : q === ".mc-trigger" ? tr : null) } };
    };
    globalThis.__fields = { "tr-MODEL_FILE": { value: "", dataset: {}, innerHTML: "", appendChild() {}, previousElementSibling: wrap },
                            "tr-MMPROJ_FILE": other(), "tr-SPEC_DRAFT_MODEL_FILE": other() };
    (globalThis.__stubReturns ||= {})["llama-edit.runnerRegistry"] = () => [];
    globalThis.__stubReturns["remote-cells.formOnControllerMachine"] = (pfx) => (pfx === "tr-" ? reads : true);
    const made = document.createElement;
    document.createElement = () => ({ className: "", dataset: {}, style: {}, classList: { add() {}, toggle() {} }, setAttribute() {},
                                      addEventListener() {}, appendChild() {}, innerHTML: "", textContent: "" });
    try { m.renderModelSelects("tr-"); } catch (e) { out.stPickError = String((e && e.message) || e); }
    document.createElement = made;
    delete globalThis.__stubReturns["remote-cells.formOnControllerMachine"];
    return kids.some((el) => el.dataset.value === "org/Qwen-ST");
  };
  out.stRows = [pickFor(true), pickFor(false)];
}
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
           # mcFormatMtime — toLocaleDateString: the value depends on Node's locale and timezone.
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
check(got["exports"] == 39, "form.js экспортирует 39 функций (пересчитай при изменении охвата)")
check(got["classicGone"] == [],
      f"negative: помощников классической формы одиночного сервера больше нет — Gemma-режимы, автошаблон, "
      f"сырой вывод; она ушла с ячейками контроллера в шаге 6.9 (got {got['classicGone']})")

print("readConfigForm — поля:")
rc = got["rc"]
check(rc["llama"]["n"] == 135 and rc["empty"]["n"] == 135, "конфиг всегда из 135 ключей, даже с пустой формы")
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
check(got["paths"]["qwen"] == [True, False, False],
      "isQwenModelPath: регистронезависимо, null/undefined → false")
oc = got["oc"]
check(oc["noTpl"] == "/opt/llama/models/templates/openclaw-qwen.jinja" and oc["exists0"] is False,
      "без шаблонов — путь из state.paths.llamaHome, exists=false")
check(oc["withTpl"] == "/t/oq.jinja" and oc["exists1"] is True, "шаблон с openclaw+qwen в имени найден по регэкспу, exists=true")
check(got["byPath"] == ["a.gguf"], "modelsByPath — Map по path из state.models")

print("форматтеры:")
fmt = got["fmt"]
check(fmt["badge"] == '<span class="badge warn"><b></span>', "badge НЕ экранирует текст — как есть")
check(fmt["badgeNoKind"] == '<span class="badge ">x</span>', "badge без kind — пустой класс с пробелом, как есть")
check(fmt["mbadge"] == '<span class="mbadge mbadge-fault" title="a&quot;&lt;b" data-t="id&lt;1">T</span>',
      "mbadge экранирует title и data-t")
check(fmt["mbadgePlain"] == '<span class="mbadge mbadge-ok">T</span>', "mbadge без title/testId — без атрибутов")
jobs = fmt["jobs"]
check(jobs["llm"] == '<span class="mbadge mbadge-job" data-t="model-job-llm">\U0001f4ac LLM</span>',
      "positive: у обычной модели работа СКАЗАНА словом — раньше «LLM» выражалось тем, что про строку молчат")
check(jobs["two"] == ('<span class="mbadge mbadge-job" data-t="model-job-asr">\U0001f3a7 speech \u2192 text</span>'
                      '<span class="mbadge mbadge-job" data-t="model-job-tts">\U0001f50a text \u2192 speech</span>'),
      f"две работы — два чипа, в порядке словаря (got {jobs['two']})")
check(jobs["compound"] == '<span class="mbadge mbadge-job" data-t="model-job-speech-translate">\U0001f3a7\U0001f310 speech \u2192 translation</span>',
      "составная работа несёт ОБА значка: 🌐 в одиночку читался бы как обычный перевод текста")
check(jobs["none"] == "" and jobs["unknown"] == "",
      "negative: работы нет или она неизвестна — чипа НЕТ, а не выдуманный «LLM»")
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

print("🎓 у CTX_SIZE — обученное окно одним нажатием:")
cn = got["ctxNative"]
check(cn["gguf"] == 262144, "заголовок GGUF выбранного файла — обученное окно (модель ещё не загружена)")
check(cn["ggufWins"] == 262144, "заголовок файла главнее стэша с карточки и плейсхолдера")
check(cn["running"] == 131072, "файла нет в каталоге — число с карточки запущенной ячейки, спрятанное редактором на поле")
check(cn["placeholder"] == 4096, "as-is: плейсхолдер прошлого прохода — последний источник")
check(cn["unknown"] == 0, "никто не знает — ноль, кнопки не будет")
title = ("Set CTX_SIZE to the trained window — 262144 tokens, what the weights were trained with. "
         "Going above it needs YaRN; going below saves KV memory.")
check(cn["state"][0] == {"hidden": False, "label": "🎓 262k", "title": title, "active": False},
      "подпись кнопки — само число, подсказка называет его обученным")
check(cn["state"][1]["active"] is True, "active, когда поле уже держит ровно это число")
check(cn["state"][2] == {"hidden": True, "label": "", "title": "", "active": False}, "без числа кнопка спрятана")
check(cn["state"][3] == "🎓 32.8k", "формат тот же, что у 🪟 на карточке")
check(cn["apply"] == [262144, "262144"], "нажатие пишет обученное окно в поле и возвращает его")
check(cn["applyNothing"] == [0, "100000"], "без числа поле не трогается")

print("📚 строка пикера из библиотеки:")
lib_rows = got["libRows"]
check(lib_rows[0] == {"lib": '<span class="mbadge mbadge-lib" title="In the library N&lt;AS, not on this disk" '
                             'data-t="model-in-library">\U0001f4da N&lt;AS</span>', "llama": True},
      f"файл только из библиотеки — в пикере как любой другой (🦙: ячейка стартует и оттуда), с чипом 📚 и именем "
      f"библиотеки; имя экранировано и в тексте, и в подсказке (got {lib_rows[0]})")
check(lib_rows[1] == {"lib": None, "llama": True}, f"negative: файл с этого диска — без чипа 📚 (got {lib_rows[1]})")
pmap = got["pickerMap"]
check(pmap == {"model": [["L/a/Q4/lib-Q4.gguf", True], ["L/a/Q4/loc-Q4.gguf", False]],
               "mmproj": [["L/a/Q4/mmproj-lib.gguf", True]], "draft": [["L/a/Q4/mtp-lib.gguf", True]]},
      f"пикер целиком: место файла доходит до всех трёх выборов — модели, проектора и черновика; строка с этого диска "
      f"без 📚 (got {pmap}, {got.get('pickerMapError')})")
check(got["stRows"] == [True, False] and got.get("stPickError") is None,
      f"папка safetensors — в пикере формы, чья машина читает дерево моделей контроллера (машина контроллера); "
      f"negative: у другой машины скаута её нет (got {got['stRows']}, {got.get('stPickError')})")

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail: print("  - " + m)
    sys.exit(1)
print("js form OK: настоящий модуль в node, форма ячейки значениями")
