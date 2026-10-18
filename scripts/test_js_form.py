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
sys.path.insert(0, str(ROOT))
from _node import find_node, node_search_paths  # noqa: E402
from caravan.domain.runner import registry_json  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


PROBE = r"""
import "./_js_globals.mjs";
(globalThis.__stubReturns ||= {})["llama-edit.usesLlamaConfig"] = (id) => id === "llama-server" || id === "prism";
import { pathToFileURL } from "node:url";
const st = await import(pathToFileURL(process.env.JS_ROOT + "/state.js").href);
const cst = await import(pathToFileURL(process.env.JS_ROOT + "/constants.js").href);
st.setState({ config: { KV_OFFLOAD: "0" }, paths: { modelsDir: "/srv/models/", llamaHome: "/opt/llama" }, chatTemplates: [], models: [] });
// remote-cells is a stub here; its values are given before the import: the cached-models
// set, and the machine the cell form targets — no cards, no RAM reported until a pin adds them.
const TR_GPUS = [];
globalThis.__stubValues = { ...(globalThis.__stubValues || {}), "remote-cells._trCachedModels": new Set(),
  "remote-cells._trClientGpus": TR_GPUS, "remote-cells._trClientCpu": {} };
// llama-edit is a stub here: its folder-kind rule answers from the server's registry, as the real one does.
{
  const reg = JSON.parse(process.env.RUNNERS_JSON);
  const owner = (arch) => reg.find((r) => (r.stArchs || []).includes(String(arch || ""))) || null;
  (globalThis.__stubReturns ||= {})["llama-edit.stOwner"] = owner;
  globalThis.__stubReturns["llama-edit.stKind"] = (arch) => ((owner(arch) || {}).artifacts || ["safetensors"])[0];
}
const m = await import(pathToFileURL(process.env.JS_ROOT + "/form.js").href);
const F = (o) => { globalThis.__fields = o; return m.readConfigForm(""); };
const base = { PORT: { value: " 22001 " }, MODEL_FILE: { value: "a.gguf" }, MMPROJ_FILE: { value: "mm.gguf" }, SPEC_DRAFT_MODEL_FILE: { value: "d.gguf" },
  ENABLE_FLASH_ATTN: { checked: true }, KV_OFFLOAD: { checked: true }, MMAP: { checked: true }, FIT: { checked: false } };
const pick = (c) => ({ PORT: c.PORT, MODEL_FILE: c.MODEL_FILE, MMPROJ_FILE: c.MMPROJ_FILE, DRAFT: c.SPEC_DRAFT_MODEL_FILE, RUNNER: c.RUNNER,
  KIND: c.CELL_KIND, DIR: c.LLAMA_MODELS_DIR, FA: c.ENABLE_FLASH_ATTN, KV: c.KV_OFFLOAD, MMAP: c.MMAP, FIT: c.FIT, THREADS: c.THREADS,
  COMMAND: c.COMMAND, VLLM: c.VLLM_MODEL, NAME: c.MODEL_NAME, TRUST: c.TRUST_REMOTE_CODE, SEQS: c.MAX_NUM_SEQS, KVDT: c.KV_CACHE_DTYPE,
  PARSER: c.REASONING_PARSER, n: Object.keys(c).length });
const out = {
  exports: Object.keys(m).length,
  rc: {
    llama: pick(F(base)),
    dirField: pick(F({ ...base, LLAMA_MODELS_DIR: { value: "/x/y//" } })),
    seamless: pick(F({ ...base, RUNNER: { value: " seamless " } })),
    transcribe: pick(F({ ...base, RUNNER: { value: "transcribe" } })),
    vllm: pick(F({ ...base, RUNNER: { value: "vllm" }, VLLM_MODEL: { value: " org/m " } })),
    vllmTrusted: pick(F({ ...base, RUNNER: { value: "vllm" }, VLLM_MODEL: { value: "org/m" }, TRUST_REMOTE_CODE: { checked: true, value: "on" } })),
    vllmRecipe: pick(F({ ...base, RUNNER: { value: "vllm" }, VLLM_MODEL: { value: "org/m" }, MAX_NUM_SEQS: { value: " 8 " },
      KV_CACHE_DTYPE: { value: " fp8 " }, REASONING_PARSER: { value: " nano_v3 " } })),
    whisper: pick(F({ ...base, RUNNER: { value: "whisper" } })),
    moonshine: pick(F({ ...base, RUNNER: { value: "moonshine" } })),
    command: pick(F({ ...base, CELL_KIND: { value: "command" }, COMMAND: { value: " run.sh --x " } })),
    commandRunner: pick(F({ ...base, CELL_KIND: { value: "command" }, RUNNER: { value: "custom-x" } })),
    named: pick(F({ ...base, MODEL_NAME: { value: " gemma " } })),
    namedWhisper: pick(F({ ...base, RUNNER: { value: "whisper" }, MODEL_NAME: { value: "ear" } })),
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
// The HF link of the model picker's field: a plain link to the caravan's HF page, in this tab (2026-10-17: "HF ↗" in a window of its own
// took the unsaved form away or left a tab behind; no target, no arrow). Drawn for the MODEL_FILE field of a repository path only.
{
  const keep = document.createElement, keepCss = globalThis.CSS;
  globalThis.CSS = { escape: (x) => String(x) };
  document.createElement = (tag) => ({ tag, style: {}, dataset: {}, children: [], appendChild(c) { this.children.push(c); }, addEventListener(ev, fn) { (this.listeners ||= {})[ev] = fn; } });
  const trigger = { innerHTML: "", children: [], appendChild(c) { this.children.push(c); } };
  const wrap = { classList: { contains: (c) => c === "mc-wrap" }, querySelector: (sel) => (sel === ".mc-trigger" ? trigger : null) };
  const draw = (id, value) => { trigger.children.length = 0; m.mcUpdateTrigger({ id, value, previousElementSibling: wrap }); return trigger.children.find((c) => c.tag === "a") || null; };
  const link = draw("tr-MODEL_FILE", "Qwen3-GGUF/Qwen/Q4_K_M/x.gguf");
  let stopped = 0; link.listeners.click({ stopPropagation() { stopped += 1; } });
  out.hfLink = { href: link.href, text: link.textContent, target: link.target ?? null, rel: link.rel ?? null, cls: link.className, title: link.title, stopped,
                 other: draw("tr-MMPROJ_FILE", "Qwen3-GGUF/Qwen/Q4_K_M/x.gguf") !== null, flat: draw("tr-MODEL_FILE", "plain.gguf") !== null, empty: draw("tr-MODEL_FILE", "") !== null };
  document.createElement = keep; globalThis.CSS = keepCss;
}
// A model combobox's list, opened as a click on the field opens it ("+ Add model").
const combo = (hidden) => { const w = { clicks: 0 }; const trigger = { click: () => { w.clicks += 1; } };
  w.select = { previousElementSibling: { classList: { contains: (c) => c === "mc-wrap" },
    querySelector: (sel) => (sel === ".mc-panel" ? { hidden } : sel === ".mc-trigger" ? trigger : null) } }; return w; };
const shut = combo(true), open = combo(false);
// What the model fields keep when the selects are drawn again, and a pick awaited ("+ Add model").
{
  const saved = st.state;
  st.setState({ ...st.state, config: { MODEL_FILE: "cfg.gguf", MMPROJ_FILE: "cfg-mm.gguf", SPEC_DRAFT_MODEL_FILE: "cfg-d.gguf" } });
  const keep = globalThis.__fields;
  globalThis.__fields = { "tr-MODEL_FILE": { value: "", dataset: {} }, "tr-MMPROJ_FILE": { value: "" }, "tr-SPEC_DRAFT_MODEL_FILE": { value: "x-d.gguf" } };
  out.choice = { normal: m.modelChoiceOf("tr-") };
  globalThis.__fields["tr-MODEL_FILE"].value = "own.gguf";
  out.choice.own = m.modelChoiceOf("tr-").model;
  globalThis.__fields["tr-MODEL_FILE"].dataset.pickPending = "1";
  out.choice.pending = m.modelChoiceOf("tr-");
  globalThis.__fields = keep;
  st.setState(saved);
  const ev = []; const sel = { value: "a.gguf", dataset: {}, dispatchEvent: (e) => { ev.push(e.type); return true; } };
  out.awaitPick = [m.mcAwaitPick(sel), sel.value, sel.dataset.pickPending, ev.slice()];
  m.mcSelectItem(sel, ""); out.awaitPick.push(sel.dataset.pickPending);
  m.mcSelectItem(sel, "b.gguf"); out.awaitPick.push(sel.dataset.pickPending ?? null, sel.value, m.mcAwaitPick(null));
}
out.mcOpen = [m.mcOpen(shut.select), shut.clicks, m.mcOpen(open.select), open.clicks, m.mcOpen(null),
  m.mcOpen({ previousElementSibling: { classList: { contains: () => false } } })];
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
// A package named after the base model whose repository says Coder: its row wears the word (the owner, 2026-10-18: "I do not see the Coder
// model for Strata" — it stood in the grey folder line only).
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
    { value: "Qwen3.8-Flash-Next-GSQ-RCO-Coder-GGUF/ISTA-DASLab/IQ1_M/Qwen3.8-Flash-Next-GSQ-RCO-IQ1_M-00001-of-00002.gguf", kind: "model", sizeGb: 54.4 },
    { value: "Qwen3.8-Flash-Next-GSQ-RCO-GGUF/ISTA-DASLab/IQ2_XS/Qwen3.8-Flash-Next-GSQ-RCO-IQ2_XS-00001-of-00002.gguf", kind: "model", sizeGb: 63.3 },
    { value: "Qwen3-Coder-30B-A3B-Instruct-GGUF/unsloth/Q4_K_M/Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf", kind: "model", sizeGb: 17.3 },
    { value: "Foo-Coder-GGUF/a/Q4/foo-Q4.gguf", kind: "model", missing: true },
    { value: "Foo-Coder-GGUF/a/Q4/asr-Q4.gguf", kind: "model", sttVariant: "ctc", sizeGb: 1 }], "");
  document.createElement = made;
  const repo = (h) => (h.match(/<span class="mbadge mbadge-repo"[^>]*>[^<]*<\/span>/) || [null])[0];
  out.repoRows = kids.map((el) => repo(el.innerHTML));
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
      { path: "org/Qwen-ST", name: "Qwen-ST", sizeGb: 16, format: "safetensors", arch: "qwen2" },
      { path: "seam/FP32", name: "seamless-m4t-v2-large", sizeGb: 9, format: "FP32", arch: "seamless_m4t_v2" }] });
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
    return [kids.some((el) => el.dataset.value === "org/Qwen-ST"), kids.some((el) => el.dataset.value === "seam/FP32")];
  };
  out.stRows = [pickFor(true), pickFor(false)];
}
// A split GGUF is one choice — its first part; Strata's second part sat in the
// picker as a llama.cpp model of its own (1.3.512).
{
  const kids = [];
  const list = { innerHTML: "", appendChild: (el) => kids.push(el) };
  const trigger = { innerHTML: "", appendChild() {} };
  const wrap = { classList: { contains: (c) => c === "mc-wrap", toggle() {}, add() {} },
                 querySelector: (q) => (q === ".mc-list" ? list : q === ".mc-trigger" ? trigger : null) };
  const other = () => {
    const l = { innerHTML: "", appendChild() {} }, tr = { innerHTML: "", appendChild() {} };
    return { value: "", dataset: {}, innerHTML: "", appendChild() {},
             previousElementSibling: { classList: { contains: (c) => c === "mc-wrap", toggle() {}, add() {} },
                                       querySelector: (q) => (q === ".mc-list" ? l : q === ".mc-trigger" ? tr : null) } };
  };
  const saved = st.state;
  st.setState({ ...st.state, config: {}, artifacts: [], models: [
    { path: "S/a/IQ2/S-IQ2-00001-of-00002.gguf", kind: "model", sizeGb: 68, parts: 2, partsFound: 2, ggufMeta: { architecture: "qwen4exp" } },
    { path: "S/a/IQ2/S-IQ2-00002-of-00002.gguf", kind: "model", sizeGb: 29, ggufMeta: {} },
    { path: "O/a/Q8/one-00001-of-00001.gguf", kind: "model", sizeGb: 1, parts: 1, partsFound: 1, ggufMeta: { architecture: "llama" } },
    { path: "W/a/Q4/whole-Q4.gguf", kind: "model", sizeGb: 4, ggufMeta: { architecture: "llama" } },
    { path: "H/a/Q8/half-00001-of-00003.gguf", kind: "model", sizeGb: 5, parts: 3, partsFound: 1, ggufMeta: { architecture: "llama" } }] });
  globalThis.__fields = { "tr-MODEL_FILE": { value: "", dataset: {}, innerHTML: "", appendChild() {}, previousElementSibling: wrap },
                          "tr-MMPROJ_FILE": other(), "tr-SPEC_DRAFT_MODEL_FILE": other(),
                          "tr-RUNNER": { value: "llama-server" } };
  (globalThis.__stubReturns ||= {})["llama-edit.runnerRegistry"] = () => [
    { id: "llama-server", artifacts: ["llm-gguf"] }, { id: "strata", artifacts: ["strata-gguf"], ggufArchs: ["qwen4exp"] }];
  globalThis.__stubReturns["llama-edit.ggufKind"] = (meta) => (meta && meta.architecture === "qwen4exp" ? "strata-gguf" : "llm-gguf");
  const made = document.createElement;
  document.createElement = () => { const cls = new Set();
    return { className: "", dataset: {}, style: {}, cls, classList: { add: (c) => cls.add(c), toggle() {} }, setAttribute() {},
             addEventListener() {}, appendChild() {}, innerHTML: "", textContent: "" }; };
  try { m.renderModelSelects("tr-"); } catch (e) { out.splitError = String((e && e.message) || e); }
  document.createElement = made;
  delete globalThis.__stubReturns["llama-edit.ggufKind"];
  st.setState(saved);
  out.splitRows = kids.map((el) => [el.dataset.value, !!(el.cls && el.cls.has("mc-dim"))])
    .filter(([v]) => /^(S|W|O|H)\//.test(v));
  out.splitSizes = kids.filter((el) => /^(S|W|O|H)\//.test(el.dataset.value))
    .map((el) => [el.dataset.value, (/class="mc-item-size">([^<]*)</.exec(el.innerHTML || "") || [])[1] ?? null]);
}
// The redraw of a form awaiting a pick: the config's model (here gone from the
// disk, so the list would carry it as a "missing" row) does not come back.
{
  const drawTr = (pending) => {
    const kids = [];
    const list = { innerHTML: "", appendChild: (el) => kids.push(el) };
    const trigger = { innerHTML: "", appendChild() {} };
    const wrap = { classList: { contains: (c) => c === "mc-wrap", toggle() {}, add() {} },
                   querySelector: (q) => (q === ".mc-list" ? list : q === ".mc-trigger" ? trigger : null) };
    const other = () => {
      const l = { innerHTML: "", appendChild() {} }, tr = { innerHTML: "", appendChild() {} };
      return { value: "", dataset: {}, innerHTML: "", appendChild() {},
               previousElementSibling: { classList: { contains: (c) => c === "mc-wrap", toggle() {}, add() {} },
                                         querySelector: (q) => (q === ".mc-list" ? l : q === ".mc-trigger" ? tr : null) } };
    };
    const saved = st.state;
    st.setState({ ...st.state, config: { MODEL_FILE: "gone/q/absent.gguf" }, artifacts: [],
                  models: [{ path: "x/q/x.gguf", kind: "model", sizeGb: 4 }] });
    const opts = [];
    globalThis.__fields = { "tr-MODEL_FILE": { value: "", dataset: pending ? { pickPending: "1" } : {}, innerHTML: "",
                                               appendChild: (o) => opts.push([o.value, o.selected]), previousElementSibling: wrap },
                            "tr-MMPROJ_FILE": other(), "tr-SPEC_DRAFT_MODEL_FILE": other() };
    (globalThis.__stubReturns ||= {})["llama-edit.runnerRegistry"] = () => [];
    globalThis.__stubReturns["remote-cells.formOnControllerMachine"] = () => true;
    const made = document.createElement;
    document.createElement = () => ({ className: "", dataset: {}, style: {}, classList: { add() {}, toggle() {} }, setAttribute() {},
                                      addEventListener() {}, appendChild() {}, innerHTML: "", textContent: "" });
    try { m.renderModelSelects("tr-"); } catch (e) { out.redrawError = String((e && e.message) || e); }
    document.createElement = made;
    delete globalThis.__stubReturns["remote-cells.formOnControllerMachine"];
    st.setState(saved);
    return [kids.some((el) => el.dataset.value === "gone/q/absent.gguf"), opts[0] || null];
  };
  out.redraw = [drawTr(false), drawTr(true)];
}
// The estimate while "+ Add model" awaits a pick: of no model — not of the
// config's, which the field fell back to (form and memory both real here).
{
  const saved = st.state;
  st.setState({ ...st.state, config: { MODEL_FILE: "big.gguf" },
    models: [{ path: "big.gguf", sizeGb: 29.8, capability: "vision_likely", ggufMeta: { blockCount: 60 } }] });
  const keep = globalThis.__fields;
  TR_GPUS.push({ index: 0, name: "Card", memoryTotalMiB: 32768, memoryFreeMiB: 32768, memoryUsedMiB: 0 });
  const box = { innerHTML: "", querySelector: () => null, querySelectorAll: () => [] }, aside = { innerHTML: "" };
  globalThis.__fields = { "tr-modelInsight": box, "tr-asideVramBar": aside,
    "tr-MODEL_FILE": { value: "", dataset: { pickPending: "1" } }, "tr-MMPROJ_FILE": { value: "" } };
  const draw = () => {
    box.innerHTML = "stale"; aside.innerHTML = "stale";
    try { m.renderModelInsight("tr-"); } catch (e) { return "threw: " + String((e && e.message) || e); }
    return [box.innerHTML.includes("29.8 GB"), box.innerHTML.includes("chooseProjectorHint") || box.innerHTML.includes("multimodal"),
            box.innerHTML === "", aside.innerHTML.includes("aside-vram-empty"), aside.innerHTML === "stale"];
  };
  out.awaitEstimate = { pending: draw() };
  delete globalThis.__fields["tr-MODEL_FILE"].dataset.pickPending;
  out.awaitEstimate.normal = draw();
  TR_GPUS.length = 0;
  globalThis.__fields = keep;
  st.setState(saved);
}
// The estimate bar of a runner that is not llama's, with a model chosen — the
// live defect: renderModelInsight drew llama's sum for every runner, and a Strata
// cell read "37.2 GB, won't fit" on the card it runs on. The registry is the
// server's (its VRAM plan); form and memory are real.
{
  const saved = st.state, keep = globalThis.__fields;
  globalThis.__stubReturns["llama-edit.runnerRegistry"] = () => JSON.parse(process.env.RUNNERS_JSON);
  const first = "Q/I/IQ2_XS/q-00001-of-00002.gguf";
  st.setState({ ...st.state, config: {}, models: [{ path: first, sizeGb: 36.53,
    ggufMeta: { blockCount: 48, embeddingLength: 2048, headCount: 16, headCountKv: 2 } }] });
  const card = { index: 0, name: "Card", memoryTotalMiB: 32607, memoryFreeMiB: 13926, memoryUsedMiB: 18681 };
  TR_GPUS.push(card);
  const box = { innerHTML: "", querySelector: () => null, querySelectorAll: () => [] }, aside = { innerHTML: "" };
  const draw = (runner) => {
    globalThis.__fields = { "tr-modelInsight": box, "tr-asideVramBar": aside, "tr-RUNNER": { value: runner },
      "tr-MODEL_FILE": { value: first, dataset: {} }, "tr-MMPROJ_FILE": { value: "" }, "tr-CTX_SIZE": { value: "131072" },
      "tr-ENV": { value: "" } };
    aside.innerHTML = "stale";
    try { m.renderModelInsight("tr-"); } catch (e) { return "threw: " + String((e && e.message) || e); }
    const h = aside.innerHTML;
    return { wontFit: h.includes("won't fit"), plan: h.includes('class="aside-vram-plan"'),
             add: (h.match(/≈ <strong>([^<]+)<\/strong>/) || [])[1] || null };
  };
  out.planBar = { strata: draw("strata"), vllm: draw("vllm"), llama: draw("llama-server") };
  // The same runner with a checkpoint that fits the card's reservation (10 GB of 28.7): no line about the weights.
  st.setState({ ...st.state, models: [{ ...st.state.models[0], sizeGb: 10 }] });
  out.planBar.vllmFits = draw("vllm");
  st.setState({ ...st.state, models: [{ ...st.state.models[0], sizeGb: 36.53 }] });
  card.memoryFreeMiB = 5632;
  out.planBar.strataShort = draw("strata");
  TR_GPUS.length = 0;
  // The bar's own options: an exact rule overflows at once, an estimate gets 1 GB
  // of grace; the start's cards alone; its note escaped.
  TR_GPUS.push({ index: 0, memoryTotalMiB: 32768, memoryFreeMiB: 5632 }, { index: 1, memoryTotalMiB: 16384, memoryFreeMiB: 16384 });
  const bar = (opts) => {
    globalThis.__fields = { "tr-asideVramBar": aside };
    m.renderAsideVramBar("tr-", 6, true, opts);
    const h = aside.innerHTML;
    return { wontFit: h.includes("won't fit"), total: (h.match(/free \/ ([^<]+)<\/span>/) || [])[1] || null,
             note: (h.match(/<div class="aside-vram-plan">([^<]*)<\/div>/) || [])[1] ?? null };
  };
  out.barOptions = { hard: bar({ hard: true, cards: [0], vramNote: "<b>x</b>" }), grace: bar({ cards: [0] }), all: bar(undefined) };
  // A cell that RUNS holds its memory already: it is drawn as "this cell", carved out of what is in use (cellHolds, memory.js — the
  // one place that reads it), and nothing is added on top — the same 6 GB on 5.5 free (by the exact rule) would not fit a cell that is not there yet.
  const running = (slot) => {
    globalThis.__stubReturns["llama-edit._commandCellSlot"] = () => slot;
    globalThis.__fields = { "tr-asideVramBar": aside };
    m.renderAsideVramBar("tr-", 6, true, { cards: [0], hard: true });
    const h = aside.innerHTML;
    delete globalThis.__stubReturns["llama-edit._commandCellSlot"];
    return { wontFit: h.includes("won't fit"), mine: (h.match(/class="aside-pool-mine">this cell <strong>([^<]+)<\/strong>/) || [])[1] ?? null };
  };
  out.barRunning = { running: running({ phase: "running", gpuMem: { 0: 5632 } }), stopped: running({ phase: "stopped", gpuMem: { 0: 5632 } }), noCell: running(null) };
  TR_GPUS.length = 0;
  delete globalThis.__stubReturns["llama-edit.runnerRegistry"];
  globalThis.__fields = keep;
  st.setState(saved);
}
// The RAM scale of a runner that keeps its weights in the machine's memory (Strata, 1.3.574; the owner, 2026-10-18: "I do not see the planned amount
// of RAM on the scale on the right"): its promise is drawn on the RAM pool as the VRAM's is on the VRAM pool, by the scout's own rule — no more than
// what is free, less the room the scout leaves the system. A cell that runs holds its memory already, in the used figure.
{
  const keep = globalThis.__fields, cpu = globalThis.__stubValues["remote-cells._trClientCpu"], aside = { innerHTML: "" };
  globalThis.__stubReturns["llama-edit.runnerRegistry"] = () => JSON.parse(process.env.RUNNERS_JSON);
  TR_GPUS.push({ index: 0, name: "Card", memoryTotalMiB: 32768, memoryFreeMiB: 32768, memoryUsedMiB: 0 });
  const plan = (mib, headMiB = 2048) => ({ addGb: mib / 1024, headroomGb: headMiB / 1024 });
  const pools = (ramPlan, { slot, extra } = {}) => {
    cpu.ram = { totalGb: 64, usedGb: 12 };         // 52 GB free
    if (slot !== undefined) globalThis.__stubReturns["llama-edit._commandCellSlot"] = () => slot;
    globalThis.__fields = { "tr-asideVramBar": aside, "tr-RUNNER": { value: "strata" }, "tr-ENV": { value: "" } };
    m.renderAsideVramBar("tr-", 6, true, { cards: [0], hard: true, ramPlan, ...(extra || {}) });
    delete globalThis.__stubReturns["llama-edit._commandCellSlot"];
    const ram = aside.innerHTML.split('<div class="aside-pool">')[1] || "", vram = aside.innerHTML.split('<div class="aside-pool">')[2] || "";
    return { add: (ram.match(/≈ <strong>([^<]+)<\/strong>/) || [])[1] ?? null, wontFit: ram.includes("won't fit"),
             fill: (ram.match(/aside-vram-fill (bad|warn|good)/) || [])[1] ?? null, note: (ram.match(/<div class="aside-vram-plan">([^<]*)<\/div>/) || [])[1] ?? null,
             mine: ram.includes("aside-pool-mine"), vramNote: (vram.match(/<div class="aside-vram-plan">([^<]*)<\/div>/) || [])[1] ?? null };
  };
  out.ramPlan = { short: pools(plan(51201)), exact: pools(plan(51200)), roomy: pools(plan(40 * 1024)), near: pools(plan(49 * 1024 + 512)),
                  none: pools(null), noRoom: pools(plan(52 * 1024, 0)), noRoomOver: pools(plan(52 * 1024 + 1, 0)),
                  running: pools(plan(51201), { slot: { phase: "running", gpuMem: { 0: 5632 } } }), stopped: pools(plan(51201), { slot: { phase: "stopped" } }) };
  cpu.ram = {};
  TR_GPUS.length = 0;
  delete globalThis.__stubReturns["llama-edit.runnerRegistry"];
  globalThis.__fields = keep;
}
// Picking a model writes its draft and the type that draft is for, by the one
// rule (draft-file.js): a head in the model's mtp/ folder was named draft-simple.
{
  const saved = st.state, keep = globalThis.__fields;
  const pick = (row) => {
    st.setState({ ...st.state, models: [row], artifacts: [] });
    globalThis.__fields = { "tr-MODEL_FILE": { value: row.path, dataset: {} }, "tr-SPEC_DRAFT_MODEL_FILE": { value: "old.gguf", dataset: {} },
                            "tr-SPEC_TYPE": { value: "stale" }, "tr-SPEC_ENABLED": { checked: false, closest: () => null } };
    // Everything after the draft wants a real page; the draft and its type are written by then.
    try { m.maybeAutofillModelHelpersPfx("tr-"); } catch (e) { /* the insight panels */ }
    const f = globalThis.__fields;
    return [f["tr-SPEC_DRAFT_MODEL_FILE"].value, f["tr-SPEC_TYPE"].value, f["tr-SPEC_ENABLED"].checked];
  };
  out.specPick = [
    pick({ path: "gemma-4-31b-it/q4/m.gguf", suggestedDraft: "gemma-4-31b-it/mtp/gemma-4-31B-it-MTP-Q8_0.gguf", familyDefaults: { SPEC_TYPE: "draft-mtp" } }),
    pick({ path: "x/q4/m.gguf", suggestedDraft: "x/default/dflash-x.gguf", familyDefaults: { SPEC_TYPE: "draft-mtp" } }),
    pick({ path: "q/q4/m.gguf", hasMtpBuiltin: true, familyDefaults: { SPEC_TYPE: "draft-eagle3" } }),
    pick({ path: "p/q4/m.gguf" }),
  ];
  globalThis.__fields = keep;
  st.setState(saved);
}
// A pick ends by drawing the previews, after every write: what the draw sees is what the pick
// filled in. Drawn before the alias is written (the runner switch's draw on a pick,
// applyConfigToForm's on an opening) a preview names the model it replaced — on the live board
// (v1.3.515) GR00T's `--name` kept the alias of the first model of the list. llama-edit is a stub
// here, so the stub IS the draw: it records what the form held at the moment it was called.
{
  const saved = st.state, keep = globalThis.__fields, seen = [];
  globalThis.__stubReturns["llama-edit.renderCellPreviews"] = (pfx) => {
    const f = globalThis.__fields;
    seen.push([pfx, f["tr-ALIAS"].value, f["tr-SPEC_DRAFT_MODEL_FILE"].value, f["tr-MODEL_NAME"].value]);
  };
  const fill = (opts, alias, auto) => {
    seen.length = 0;
    st.setState({ ...st.state, models: [{ path: "x/q4/m.gguf", suggestedDraft: "x/mtp/d.gguf" }], artifacts: [] });
    globalThis.__fields = { "tr-MODEL_FILE": { value: "x/q4/m.gguf", dataset: {} },
      "tr-ALIAS": { value: alias, dataset: auto ? { autoAlias: alias } : {} },
      "tr-SPEC_DRAFT_MODEL_FILE": { value: "old.gguf", dataset: {} }, "tr-MODEL_NAME": { value: "typed" } };
    try { m.maybeAutofillModelHelpersPfx("tr-", opts); } catch (e) { return "threw: " + String((e && e.message) || e); }
    return seen.map((s) => s.slice());
  };
  out.previewsLast = {
    pick: fill({ aliasFollow: true }, "old-model", true),
    pickOverTyped: fill({ aliasFollow: true }, "typed-by-hand", false),
    openKeepsSaved: fill({}, "saved-alias", false),
    openFillsEmpty: fill({}, "", false),
  };
  delete globalThis.__stubReturns["llama-edit.renderCellPreviews"];
  globalThis.__fields = keep;
  st.setState(saved);
}
// The projector and draft pickers offer a model's companions as the SERVER lists them — its own folder, default/ and the
// repository's other quant folders — not only the files of the model's own folder (2026-10-17: gemma-4-12B Q5_K_M had its
// draft in Q8_0/, the suggested draft had no option, the field stayed empty and the speculative type stayed "draft-mtp").
{
  const saved = st.state, keep = globalThis.__fields;
  const en = (await import(pathToFileURL(process.env.JS_ROOT + "/i18n/en.js").href)).default;
  const picker = () => {
    const kids = [], opts = [];
    const list = { innerHTML: "", appendChild: (el) => kids.push(el) };
    const trigger = { innerHTML: "", appendChild() {} };
    const wrap = { classList: { contains: (c) => c === "mc-wrap", toggle() {}, add() {} },
                   querySelector: (q) => (q === ".mc-list" ? list : q === ".mc-trigger" ? trigger : null) };
    return { kids, opts, sel: { value: "", dataset: {}, innerHTML: "", appendChild: (o) => opts.push([o.value, o.textContent]), previousElementSibling: wrap } };
  };
  const ROWS = [
    { path: "G/b/Q5/g-Q5.gguf", kind: "model", sizeGb: 8, compatibleMmprojs: ["G/b/Q8/mmproj-g.gguf"], suggestedMmproj: "G/b/Q8/mmproj-g.gguf",
      compatibleDrafts: ["G/b/Q8/mtp-g.gguf", "G/b/default/mtp-d.gguf"], suggestedDraft: "G/b/Q8/mtp-g.gguf" },
    { path: "G/b/Q8/g-Q8.gguf", kind: "model", sizeGb: 12 },
    { path: "G/b/Q8/mmproj-g.gguf", kind: "mmproj", sizeGb: 1 }, { path: "G/b/Q8/mtp-g.gguf", kind: "draft", sizeGb: 1 },
    { path: "G/b/default/mtp-d.gguf", kind: "draft", sizeGb: 1 },
    { path: "H/c/Q4/mmproj-h.gguf", kind: "mmproj", sizeGb: 1 }, { path: "H/c/Q4/mtp-h.gguf", kind: "draft", sizeGb: 1 },
    { path: "Z/q/mmproj-z.gguf", kind: "mmproj", sizeGb: 1 }, { path: "Z/other/mmproj-z2.gguf", kind: "mmproj", sizeGb: 1 },
    { path: "Z/q/mtp-z.gguf", kind: "draft", sizeGb: 1 }, { path: "Z/other/mtp-z2.gguf", kind: "draft", sizeGb: 1 }];
  const draw = (model, mmproj = "", draft = "", rows = ROWS) => {
    const [pm, pp, pd] = [picker(), picker(), picker()];
    pp.sel.value = mmproj; pd.sel.value = draft; pm.sel.value = model;
    st.setState({ ...st.state, config: {}, artifacts: [], models: rows });
    globalThis.__fields = { MODEL_FILE: pm.sel, MMPROJ_FILE: pp.sel, SPEC_DRAFT_MODEL_FILE: pd.sel };
    (globalThis.__stubReturns ||= {})["llama-edit.runnerRegistry"] = () => [];
    const made = document.createElement, keepCss = globalThis.CSS;
    globalThis.CSS = { escape: (x) => String(x) };
    document.createElement = () => ({ className: "", dataset: {}, style: {}, classList: { add() {}, toggle() {} }, setAttribute() {},
                                      addEventListener() {}, appendChild() {}, innerHTML: "", textContent: "" });
    let error = null;
    try { m.renderModelSelects(""); } catch (e) { error = String((e && e.message) || e); }
    document.createElement = made; globalThis.CSS = keepCss;
    const rowsOf = (pk) => pk.kids.map((el) => el.dataset.value).filter((v) => v);
    return { mmproj: rowsOf(pp), draft: rowsOf(pd), heldMmproj: pp.sel.value, heldDraft: pd.sel.value,
             emptyMmproj: (pp.opts.find(([v]) => v === "") || [])[1], emptyDraft: (pd.opts.find(([v]) => v === "") || [])[1], error };
  };
  const q5 = "G/b/Q5/g-Q5.gguf";
  const a = draw(q5);
  out.companions = {
    siblings: [a.mmproj, a.draft],
    labels: [a.emptyMmproj === en.textOnlyOption, a.emptyDraft === en.noDraftOption, a.emptyDraft === en.textOnlyOption, en.noDraftOption !== en.textOnlyOption],
    // A companion of another repository: replaced by the model's own suggestion; one of a sibling quant folder: kept.
    stale: [draw(q5, "H/c/Q4/mmproj-h.gguf", "H/c/Q4/mtp-h.gguf"), draw(q5, "G/b/Q8/mmproj-g.gguf", "G/b/default/mtp-d.gguf")].map((d) => [d.heldMmproj, d.heldDraft]),
    unknownModel: (({ mmproj, draft }) => [mmproj, draft])(draw("Z/q/z.gguf")),
    noRow: (({ mmproj, draft }) => [mmproj, draft])(draw(q5, "", "", ROWS.map(({ compatibleMmprojs, compatibleDrafts, ...r }) => r))),
    errors: [a.error],
  };
  // What the draft field HOLDS decides the speculative type: a <select> drops a value it has no option for.
  const picky = (allowed) => ({ dataset: {}, allowed, _v: "old.gguf", get value() { return this._v; }, set value(x) { this._v = this.allowed.includes(x) ? x : ""; } });
  const fill = (allowed) => {
    st.setState({ ...st.state, models: [{ path: "x/q4/m.gguf", suggestedDraft: "x/mtp/d.gguf", familyDefaults: { SPEC_TYPE: "draft-mtp" } }], artifacts: [] });
    globalThis.__fields = { "tr-MODEL_FILE": { value: "x/q4/m.gguf", dataset: {} }, "tr-SPEC_DRAFT_MODEL_FILE": picky(allowed),
                            "tr-SPEC_TYPE": { value: "stale" }, "tr-SPEC_ENABLED": { checked: true, closest: () => null } };
    try { m.maybeAutofillModelHelpersPfx("tr-"); } catch (e) { /* the insight panels */ }
    const f = globalThis.__fields;
    return [f["tr-SPEC_DRAFT_MODEL_FILE"].value, f["tr-SPEC_TYPE"].value, f["tr-SPEC_ENABLED"].checked];
  };
  // Strata's one draft layer lies in the ORIGINAL's folder, and the server lists it for the Coder's pack by architecture
  // (DraftPairing, 2026-10-17): another repository's file, offered and kept — while a model whose row does not list it still loses it.
  const SROWS = [
    { path: "C/c/IQ1_M/c-IQ1_M-00001-of-00002.gguf", kind: "model", sizeGb: 54,
      compatibleDrafts: ["O/o/IQ2_XS/mtp-q2_0.gguf"], suggestedDraft: "O/o/IQ2_XS/mtp-q2_0.gguf" },
    { path: "G/b/Q5/g-Q5.gguf", kind: "model", sizeGb: 8, compatibleDrafts: [], suggestedDraft: "" },
    { path: "O/o/IQ2_XS/mtp-q2_0.gguf", kind: "draft", sizeGb: 1 }];
  const coder = "C/c/IQ1_M/c-IQ1_M-00001-of-00002.gguf", layer = "O/o/IQ2_XS/mtp-q2_0.gguf";
  out.pairedDraft = [draw(coder, "", layer, SROWS), draw(coder, "", "", SROWS), draw("G/b/Q5/g-Q5.gguf", "", layer, SROWS)]
    .map((d) => [d.draft, d.heldDraft]);
  out.heldDraft = [fill(["x/mtp/d.gguf"]), fill([])];
  // A pick writes the companions into pickers whose options are THOSE OF THE NEW MODEL: the options are drawn first. Pickers that
  // keep only the options drawn since their last redraw (a <select> drops any other value) show the difference.
  const keepCss = globalThis.CSS, made = document.createElement;
  globalThis.CSS = { escape: (x) => String(x) };
  document.createElement = () => ({ className: "", dataset: {}, style: {}, classList: { add() {}, toggle() {} }, setAttribute() {},
                                    addEventListener() {}, appendChild() {}, innerHTML: "", textContent: "" });
  const select = (initial = "") => {
    const list = { innerHTML: "", appendChild() {} }, trigger = { innerHTML: "", appendChild() {} };
    const wrap = { classList: { contains: (c) => c === "mc-wrap", toggle() {}, add() {} },
                   querySelector: (q) => (q === ".mc-list" ? list : q === ".mc-trigger" ? trigger : null) };
    return { dataset: {}, allowed: [], _v: initial, previousElementSibling: wrap,
             get value() { return this._v; }, set value(x) { this._v = (x === "" || this.allowed.includes(x)) ? x : ""; },
             set innerHTML(h) { this.allowed = []; this._v = ""; }, get innerHTML() { return ""; },
             appendChild(o) { this.allowed.push(o.value); if (o.selected) this._v = o.value; } };
  };
  st.setState({ ...st.state, config: {}, artifacts: [], models: ROWS });
  globalThis.__fields = { "tr-MODEL_FILE": select("G/b/Q5/g-Q5.gguf"),
                          "tr-MMPROJ_FILE": select(), "tr-SPEC_DRAFT_MODEL_FILE": select(),
                          "tr-SPEC_TYPE": { value: "stale" }, "tr-SPEC_ENABLED": { checked: false, closest: () => null } };
  (globalThis.__stubReturns ||= {})["llama-edit.runnerRegistry"] = () => [];
  try { m.maybeAutofillModelHelpersPfx("tr-"); } catch (e) { out.pickThenWriteError = String((e && e.stack) || e).split("\n").slice(0, 4).join(" | "); }
  const f = globalThis.__fields;
  out.pickThenWrite = [f["tr-MMPROJ_FILE"].value, f["tr-SPEC_DRAFT_MODEL_FILE"].value, f["tr-SPEC_TYPE"].value, f["tr-SPEC_ENABLED"].checked];
  document.createElement = made; globalThis.CSS = keepCss;
  globalThis.__fields = keep;
  st.setState(saved);
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
           "RUNNERS_JSON": json.dumps(registry_json()),
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
check(got["exports"] == 43, "form.js экспортирует 43 функции (пересчитай при изменении охвата; +ModelCompanions, 2026-10-17; +mcOpen, раунд 10; "
      "+modelChoiceOf, +mcAwaitPick)")
check(got["classicGone"] == [],
      f"negative: помощников классической формы одиночного сервера больше нет — Gemma-режимы, автошаблон, "
      f"сырой вывод; она ушла с ячейками контроллера в шаге 6.9 (got {got['classicGone']})")

print("readConfigForm — поля:")
rc = got["rc"]
check(rc["llama"]["n"] == 147 and rc["empty"]["n"] == 147,
      "конфиг всегда из 147 ключей, даже с пустой формы (1.3.512: +4 поля Strata; 1.3.515: +3 поля GR00T; 1.3.550: +TRUST_REMOTE_CODE; "
      "1.3.555: +MAX_NUM_SEQS, KV_CACHE_DTYPE, REASONING_PARSER)")
check(rc["named"]["NAME"] == "gemma" and rc["namedWhisper"]["NAME"] == "ear" and rc["llama"]["NAME"] == "",
      "MODEL_NAME (1.3.507) — имя модели на входе машины, у любого раннера, без пробелов; поля нет — пусто")
check(rc["llama"]["PORT"] == "22001", "порт обрезан от пробелов")
check(rc["llama"]["FA"] == "1" and rc["empty"]["FA"] == "0", "чекбокс → \"1\"; отсутствующий чекбокс → \"0\"")
check(rc["llama"]["THREADS"] == "", "отсутствующее числовое поле → \"\", не undefined")
check(rc["llama"]["KV"] == "1", "необязательный тумблер со значением в конфиге читает чекбокс")
check(rc["llama"]["MMAP"] == "" and rc["llama"]["FIT"] == "",
      "необязательный тумблер без значения и не тронутый → \"\" — даже при включённом чекбоксе")
check(got["dirtyFit"] == "0", "тронутый (dirty) необязательный тумблер читает чекбокс: \"0\"")
check(got["prefixed"] == "9", "префикс формы \"tr-\" читает tr-PORT, а не PORT")
check(got["hfLink"] == {"href": "/hf?q=Qwen%2FQwen3-GGUF", "text": "HF", "target": None, "rel": None, "cls": "mc-hf-link",
                        "title": "Open Qwen/Qwen3-GGUF in HF Browser", "stopped": 1, "other": False, "flat": False, "empty": False},
      "ссылка «HF» у поля модели — обычная ссылка на страницу HF каравана с репозиторием в запросе, в ЭТОЙ ЖЕ вкладке (2026-10-17): без target и без стрелки ↗; щелчок по ней не открывает список "
      "(stopPropagation); negative: у поля mmproj, у файла без папки репозитория и у пустого поля ссылки нет "
      f"(получено {got['hfLink']})")

check(rc["vllmTrusted"]["TRUST"] == "1" and rc["vllm"]["TRUST"] == "" and rc["empty"]["TRUST"] == "",
      "TRUST_REMOTE_CODE (--trust-remote-code у vLLM): отмеченный флажок → \"1\" (не \"on\" — значение флажка), неотмеченный и отсутствующий → \"\", а не \"0\"")

check(rc["vllmRecipe"]["SEQS"] == "8" and rc["vllmRecipe"]["KVDT"] == "fp8" and rc["vllmRecipe"]["PARSER"] == "nano_v3",
      "рецепт модели (--max-num-seqs, --kv-cache-dtype, --reasoning-parser): три поля читаются обрезанными от пробелов, как остальные текстовые поля vLLM")
check(rc["vllm"]["SEQS"] == "" and rc["vllm"]["KVDT"] == "" and rc["vllm"]["PARSER"] == "" and rc["empty"]["SEQS"] == ""
      and rc["empty"]["KVDT"] == "" and rc["empty"]["PARSER"] == "",
      "negative: поля не заполнены (или их нет на форме) — пустая строка, а не «0», «auto» и не undefined: пусто значит «флага нет»")

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

print("modelChoiceOf / mcAwaitPick:")
check(got["choice"]["normal"] == {"model": "cfg.gguf", "mmproj": "cfg-mm.gguf", "draft": "x-d.gguf"}
      and got["choice"]["own"] == "own.gguf",
      "перерисовка держит значения формы, пустое поле — из конфига (как было); своё значение важнее конфига")
check(got["choice"]["pending"] == {"model": "", "mmproj": "", "draft": ""},
      "defect-history: форма «＋ Add model» ждёт выбора — все три поля пустые при перерисовке; раньше модель конфига "
      "возвращалась в поле, когда приходил список с машины, и Apply создавал ячейку с ней")
check(got.get("redraw") == [[True, ["gone/q/absent.gguf", True]], [False, ["", True]]] and "redrawError" not in got,
      "перерисовка списков: обычная форма с пустым полем берёт модель конфига (её нет на диске — строка «пропала», "
      "она и выбрана); negative: форма, ждущая выбора, модель конфига не возвращает, а первой в скрытом поле стоит "
      "пустая выбранная опция — без неё браузер сам выбирал первую модель списка (живая проверка 1.3.388) "
      f"(got {got.get('redraw')}, {got.get('redrawError', '')})")
check(got["awaitPick"] == [True, "", "1", ["change"], "1", None, "b.gguf", False],
      "mcAwaitPick: поле пустое, выбор ждёт, поле узнаёт о смене; выбор «пусто» ожидания не снимает, выбор модели — "
      "снимает; negative: поля нет — false")

pb = got.get("planBar") or {}
check(pb.get("strata") == {"wontFit": False, "plan": True, "add": "13.6 GB"},
      "defect-history: форма Strata с выбранной моделью рисует её план — всё свободное на карте (13.6 ГБ) и строку "
      "«как она берёт память»; было «≈ 37.2 GB ✗ won't fit» по сумме llama на карте, где она работает "
      f"(живая проверка 2026-10-13) (got {pb.get('strata')})")
check(pb.get("strataShort") == {"wontFit": True, "plan": True, "add": "6.00 GB"},
      "на карте свободно 5.5 ГБ из нужных 6 — «won't fit» сразу, без запаса в 1 ГБ: скаут откажет ровно здесь "
      f"(got {pb.get('strataShort')})")
check(pb.get("vllm") == {"wontFit": True, "plan": True, "add": "28.7 GB"},
      "vLLM с моделью — его резерв (0.9 × 31.8 ГБ карты), а не сумма llama по файлу; при 13.6 ГБ свободных — "
      "не влезет; и строка под полосой: веса 36.5 ГБ не помещаются в резерв одной карты (VllmPlacement) "
      f"(got {pb.get('vllm')})")
check(pb.get("vllmFits") == {"wontFit": True, "plan": False, "add": "28.7 GB"},
      "negative: та же карта и тот же резерв, но веса 10 ГБ в него помещаются — строки о весах нет (резерв по-прежнему не влезает в 13.6 свободных) "
      f"(got {pb.get('vllmFits')})")
check((pb.get("llama") or {}).get("plan") is False and (pb.get("llama") or {}).get("add") not in (None, "13.6 GB"),
      "negative: llama.cpp с той же моделью — по-прежнему своя цифра (доля VRAM при выгрузке слоёв), "
      f"без строки плана (got {pb.get('llama')})")
bo = got.get("barOptions") or {}
check(bo.get("hard") == {"wontFit": True, "total": "32.0 GB", "note": "&lt;b&gt;x&lt;/b&gt;"},
      f"точное правило: 6 ГБ на 5.5 свободных — «won't fit»; только её карта (32 ГБ); строка экранирована (got {bo.get('hard')})")
check(bo.get("grace") == {"wontFit": False, "total": "32.0 GB", "note": None},
      f"оценка без hard — запас 1 ГБ, как было: 6 на 5.5 ещё «впритык», строки плана нет (got {bo.get('grace')})")
check(bo.get("all") == {"wontFit": False, "total": "48.0 GB", "note": None},
      f"без cards — все карты машины, как было (got {bo.get('all')})")
br = got.get("barRunning") or {}
check(br.get("running") == {"wontFit": False, "mine": "5.50 GB"},
      f"работающая ячейка уже держит свою память: полоса рисует её «this cell 5.50 GB» внутри занятого и ничего не добавляет (got {br.get('running')})")
check(br.get("stopped") == {"wontFit": True, "mine": None} and br.get("noCell") == {"wontFit": True, "mine": None},
      f"negative: остановленная ячейка и «ячейки нет» ничего не держат — те же 6 ГБ на 5.5 свободных «won't fit», без «this cell» (got {br.get('stopped')}, {br.get('noCell')})")
check(got.get("awaitEstimate") == {"pending": [False, False, True, True, False], "normal": [True, True, False, False, False]},
      "defect-history: пока «＋ Add model» ждёт выбора, оценка пуста, а полоса памяти говорит «выберите модель» — "
      "раньше редактор показывал размер, «не влезет» и подсказку про проектор модели конфига (живая проверка "
      "1.3.390); negative: обычная форма с пустым полем — модель конфига, как было: размер и подсказка на месте, "
      f"полоса рисуется (у машины карта на 32 ГБ) (got {got.get('awaitEstimate')})")

rp = got.get("ramPlan") or {}
note = "keeps its weights in memory · needs 50.0 GB free, plus 2.00 GB left for the system"
check(rp.get("short") == {"add": "50.0 GB", "wontFit": True, "fill": "bad", "note": note, "mine": False, "vramNote": None},
      f"шкала RAM показывает обещание Strata: 51201 МиБ при 52 ГБ свободных и 2 ГБ, что скаут оставляет системе, — «≈ 50.0 GB ✗ won't fit», красный отрезок и строка под полосой (got {rp.get('short')})")
check(rp.get("exact", {}).get("wontFit") is False and rp.get("exact", {}).get("add") == "50.0 GB" and rp.get("exact", {}).get("fill") == "warn",
      f"boundary: ровно 50 ГБ (51200 МиБ) — влезает до МиБ, как режет скаут (MemoryLedger.short); запас меньше 1 ГБ — жёлтый (got {rp.get('exact')})")
check(rp.get("roomy", {}).get("wontFit") is False and rp.get("roomy", {}).get("fill") == "good" and rp.get("roomy", {}).get("add") == "40.0 GB",
      f"обещание 40 ГБ при 52 свободных — влезает, зелёный отрезок (got {rp.get('roomy')})")
check(rp.get("near", {}).get("fill") == "warn" and rp.get("near", {}).get("wontFit") is False and rp.get("near", {}).get("add") == "49.5 GB",
      f"49.5 ГБ при 52 − 2 = 50 «свободных» после запаса: влезает, но меньше ГБ в запасе — жёлтый, не красный (got {rp.get('near')})")
check(rp.get("none") == {"add": None, "wontFit": False, "fill": None, "note": None, "mine": False, "vramNote": None},
      f"negative: без плана (llama.cpp, ничего не обещает) на шкале RAM ничего, кроме занятого, — как было до 1.3.574 (got {rp.get('none')})")
check(rp.get("noRoom", {}).get("wontFit") is False and rp.get("noRoomOver", {}).get("wontFit") is True,
      f"запаса системе нет (ответ без него) — обещание сравнивается со свободным как есть: 52 ГБ влезает, МиБ сверху — нет (got {rp.get('noRoom')}, {rp.get('noRoomOver')})")
check(rp.get("running", {}).get("add") is None and rp.get("running", {}).get("note") is None and rp.get("running", {}).get("wontFit") is False,
      f"negative: работающая ячейка уже держит память внутри «занято» — обещание поверх не рисуется, дважды не считается (got {rp.get('running')})")
check(rp.get("stopped", {}).get("wontFit") is True and rp.get("stopped", {}).get("add") == "50.0 GB",
      f"остановленная ячейка ничего не держит — обещание рисуется, как у новой (got {rp.get('stopped')})")

print("mcOpen:")
check(got["mcOpen"] == [True, 1, False, 0, False, False],
      "список модели открывается одним щелчком по полю, как руками («＋ Add model», раунд 10); negative: уже открыт — "
      "не щёлкает (щелчок бы закрыл); поля нет или это не комбобокс — false")

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

print("💻 слово из имени репозитория:")
repo_rows = got["repoRows"]
check(repo_rows == ['<span class="mbadge mbadge-repo" title="Qwen3.8-Flash-Next-GSQ-RCO-Coder-GGUF">\U0001f4bb Coder</span>', None, None, None, None],
      f"пакет Coder назван по базовой модели (…GSQ-RCO-IQ1_M-…), и слово «Coder» стояло только в серой строке папки: на строке имени теперь чип 💻 Coder, подсказка — репозиторий; "
      f"negative: у базовой модели чипа нет, у Qwen3-Coder нет (слово уже в имени файла), у файла, которого нет на диске, и у распознавателя речи — тоже (got {repo_rows})")

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
check(got.get("splitRows") == [["S/a/IQ2/S-IQ2-00001-of-00002.gguf", True],
                               ["O/a/Q8/one-00001-of-00001.gguf", False],
                               ["W/a/Q4/whole-Q4.gguf", False],
                               ["H/a/Q8/half-00001-of-00003.gguf", False]] and got.get("splitError") is None,
      f"разбитый GGUF — один выбор, его первая часть (вторая часть Strata стояла в пикере моделью llama.cpp); "
      f"модель Strata под llama.cpp приглушена — её вид по архитектуре qwen4exp; boundary: «часть 1 из 1» — "
      f"обычная модель (got {got.get('splitRows')}, {got.get('splitError')})")
check(got.get("splitSizes") == [["S/a/IQ2/S-IQ2-00001-of-00002.gguf", "68 GB \u00d72"], ["O/a/Q8/one-00001-of-00001.gguf", "1 GB"],
                               ["W/a/Q4/whole-Q4.gguf", "4 GB"], ["H/a/Q8/half-00001-of-00003.gguf", "5 GB \u00d71/3"]],
      f"модель из частей в пикере — размер ВСЕЙ модели и число частей («68 GB ×2»); недостающая часть названа («×1/3»: её нельзя запустить, а выглядела бы целой); "
      f"negative: целый файл и «часть 1 из 1» — без «×» (got {got.get('splitSizes')})")
check(got["stRows"] == [[True, True], [False, True]] and got.get("stPickError") is None,
      f"папка safetensors — в пикере формы, чья машина читает дерево моделей контроллера (машина контроллера); "
      f"negative: у другой машины скаута папки vLLM нет; defect-history: папку SeamlessM4T другая машина видит — "
      f"скаут 2.30 приносит её сам (got {got['stRows']}, {got.get('stPickError')})")
check(got["specPick"] == [["gemma-4-31b-it/mtp/gemma-4-31B-it-MTP-Q8_0.gguf", "draft-mtp", True],
                          ["x/default/dflash-x.gguf", "draft-dflash", True],
                          ["", "draft-eagle3", True],
                          ["", "", False]],
      f"выбор модели пишет черновик и его тип по одному правилу: голова из папки mtp/ — draft-mtp (было draft-simple); "
      f"negative: DFlash не получает тип семейства; без файла с MTP внутри — тип семейства; без черновика и без MTP — "
      f"пусто и выключено (got {got['specPick']})")
comp = got["companions"]
check(comp["errors"] == [None], f"пикеры рисуются без ошибок (got {comp['errors']})")
check(comp["siblings"] == [["G/b/Q8/mmproj-g.gguf"], ["G/b/Q8/mtp-g.gguf", "G/b/default/mtp-d.gguf"]],
      f"пикеры предлагают компаньонов так, как их назвал сервер: проектор и черновик из соседней папки кванта Q8_0 и из default/, "
      f"а не только из своей папки; negative: файлы чужого репозитория (H/c) не предложены (got {comp['siblings']})")
check(comp["labels"] == [True, True, False, True],
      f"пустой пункт проектора — «только текст», пустой пункт черновика — «без черновика», а не слова про mmproj (got {comp['labels']})")
check(comp["stale"] == [["G/b/Q8/mmproj-g.gguf", "G/b/Q8/mtp-g.gguf"], ["G/b/Q8/mmproj-g.gguf", "G/b/default/mtp-d.gguf"]],
      "положительный и отрицательный: сохранённые компаньоны чужого репозитория заменены предложением модели; компаньоны из соседней папки "
      f"кванта и из default/ — это компаньоны модели, они остаются (got {comp['stale']})")
check(got["pairedDraft"] == [[["O/o/IQ2_XS/mtp-q2_0.gguf"], "O/o/IQ2_XS/mtp-q2_0.gguf"], [["O/o/IQ2_XS/mtp-q2_0.gguf"], ""], [[], ""]],
      "defect-history (2026-10-17): the Coder's pack has no draft in its own repository; the server lists the original's draft layer for it "
      "(by architecture), and the picker OFFERS that other repository's file and KEEPS it when the cell holds it; negative: with nothing "
      "chosen nothing is written by the redraw, and a model whose row does not list the file is offered none and loses it "
      f"(got {got['pairedDraft']})")
check(comp["unknownModel"] == [["Z/q/mmproj-z.gguf"], ["Z/q/mtp-z.gguf"]],
      f"модель, которой сервер не знает (путь набран руками): остаётся одно правило — своя папка (got {comp['unknownModel']})")
check(comp["noRow"] == [[], []],
      f"ответ без списков (сервер старой версии): то же единственное правило — своя папка; в папке Q5 компаньонов нет (got {comp['noRow']})")
check(got["pickThenWrite"] == ["G/b/Q8/mmproj-g.gguf", "G/b/Q8/mtp-g.gguf", "draft-mtp", True],
      "выбор модели пишет проектор и черновик в пикеры, у которых уже варианты ЭТОЙ модели (соседняя папка кванта): значения остались, "
      f"тип — draft-mtp, ускорение включено; пикеры с вариантами прежней модели значения сбросили бы (got {got['pickThenWrite']}, {got.get('pickThenWriteError')})")
check(got["heldDraft"] == [["x/mtp/d.gguf", "draft-mtp", True], ["", "", False]],
      "тип ускорения следует за тем, что поле УДЕРЖАЛО: поле приняло черновик — draft-mtp включён; поле значения не приняло "
      f"(нет такого пункта) — тип пуст и ускорение выключено, а не draft-mtp без файла (got {got['heldDraft']})")
pl = got["previewsLast"]
check(pl["pick"] == [["tr-", "m", "x/mtp/d.gguf", "typed"]],
      f"выбор модели рисует превью ОДИН раз и ПОСЛЕ записей: рисунок видит новый алиас и новый черновик (было: старые — "
      f"превью называло прежнюю модель); negative: имя модели, набранное оператором, алиас не трогает (got {pl['pick']})")
check(pl["pickOverTyped"] == [["tr-", "m", "x/mtp/d.gguf", "typed"]],
      f"явный выбор заменяет и алиас, набранный руками, — и превью рисуется уже с новым (got {pl['pickOverTyped']})")
check(pl["openKeepsSaved"] == [["tr-", "saved-alias", "x/mtp/d.gguf", "typed"]],
      f"negative: открытие формы не затирает сохранённый алиас, а превью всё равно рисуется после автозаполнения "
      f"(got {pl['openKeepsSaved']})")
check(pl["openFillsEmpty"] == [["tr-", "m", "x/mtp/d.gguf", "typed"]],
      f"positive: открытие формы дописывает пустой алиас — и превью рисуется после этого (got {pl['openFillsEmpty']})")

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail: print("  - " + m)
    sys.exit(1)
print("js form OK: настоящий модуль в node, форма ячейки значениями")
