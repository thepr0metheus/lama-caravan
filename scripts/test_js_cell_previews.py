#!/usr/bin/env python3
"""Snapshot of the cell form's previews: they follow what the operator does — a model pick, a typed edit.

A pick rewrites more than MODEL_FILE. The runner follows the artifact
(llama-edit.js), then the helper fields follow the model: ALIAS, the
projector, the draft (maybeAutofillModelHelpersPfx). The command a runner
shows is built from those fields. A preview drawn before the autofill names
what stood in the field before the pick, and it stays that way until some
other field is edited: on the live board (v1.3.515) GR00T's "New command"
showed `--name llama-3.3-70b-instruct-q4_k_m` over a form whose ALIAS read
`gr00t-n1.7-3b`. The saved command was right (readConfigForm reads the form
after the autofill); only the preview lied.

The pick runs the page's own handlers: the change listeners that
openLlamaRemoteEdit puts on the model field, in the order it puts them, started
by mcSelectItem, the call a click on a picker row makes. Every expected command
is the server's own (the runner classes of caravan/domain/runner.py) for the
fields the pick leaves in the form: the preview must be the command Apply will
save, not a command of its own.

A typed edit is the other way a preview goes stale. The page's own command line
was drawn after an edit only by a fixed list of fields (llama-edit.js), which had
no ALIAS (GR00T's --name, vLLM's --served-model-name), no draft file, no language
field and no port: typing there left "New command" on the old text. The form's own
listeners now draw every preview after every edit (remote-cells.js), and a typed
edit here is the listeners openLlamaRemoteEdit puts on the form, run as a browser's
bubbling would run them: the input event of a field typed into, the change event of a
select that was set.

The form is a dict of fake elements (globalThis.__fields). The ALIAS field and
the command preview log their writes, so a pin can say which came last. The
modules are loaded FOR REAL (_js_harness.mjs).

Run: python3 scripts/test_js_cell_previews.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT))
from _js_pins import run  # noqa: E402
from caravan.domain.runner import get as _runner, registry_json  # noqa: E402

LLAMA = "llama-3.3-70b-instruct-q4_k_m.gguf"
GEMMA = "gemma-3-27b-it-q4_k_m.gguf"
STRATA_1 = "Q/I/IQ2_XS/Qwen3.8-Flash-Next-GSQ-RCO-IQ2_XS-00001-of-00002.gguf"
STRATA_1_MTP = "Q/I/IQ2_XS/mtp-q2_0.gguf"
STRATA_2 = "Q/J/Q4_0/Qwen3.8-Flash-Next-Q4_0-00001-of-00002.gguf"
STRATA_2_MTP = "Q/J/Q4_0/mtp-q2_0.gguf"
ASR_1 = "stt/gigaam-v2.gguf"
ASR_2 = "stt/gigaam-v3.gguf"
GR00T_1 = "GR00T-N1.7-3B/nvidia/BF16"
GR00T_2 = "GR00T-N1.6-3B/nvidia/BF16"
SEAMLESS_1 = "seamless-m4t-v2-large/facebook/BF16"
SEAMLESS_2 = "seamless-m4t-medium/facebook/BF16"
QWEN = "Qwen3-8B/Qwen/BF16"
MISTRAL = "Mistral-7B/mistralai/BF16"
PORT = "22002"

MODELS = [
    {"path": LLAMA, "kind": "model", "ggufMeta": {"architecture": "llama"}},
    {"path": GEMMA, "kind": "model", "ggufMeta": {"architecture": "gemma3"}},
    {"path": STRATA_1, "kind": "model", "ggufMeta": {"architecture": "qwen4exp"}, "suggestedDraft": STRATA_1_MTP},
    {"path": STRATA_1_MTP, "kind": "draft"},
    {"path": STRATA_2, "kind": "model", "ggufMeta": {"architecture": "qwen4exp"}, "suggestedDraft": STRATA_2_MTP},
    {"path": STRATA_2_MTP, "kind": "draft"},
    {"path": ASR_1, "kind": "model", "ggufMeta": {"sttVariant": "gigaam"}},
    {"path": ASR_2, "kind": "model", "ggufMeta": {"sttVariant": "gigaam"}},
]
ARTIFACTS = [
    {"path": GR00T_1, "name": "GR00T-N1.7-3B", "arch": "Gr00tN1d7", "format": "bf16"},
    {"path": GR00T_2, "name": "GR00T-N1.6-3B", "arch": "Gr00tN1d7", "format": "bf16"},
    {"path": SEAMLESS_1, "name": "seamless-m4t-v2-large", "arch": "seamless_m4t_v2", "format": "bf16"},
    {"path": SEAMLESS_2, "name": "seamless-m4t-medium", "arch": "seamless_m4t_v2", "format": "bf16"},
    {"path": QWEN, "name": "Qwen3-8B", "arch": "qwen3", "format": "bf16"},
    {"path": MISTRAL, "name": "Mistral-7B", "arch": "mistral", "format": "bf16"},
]

PREAMBLE = r"""
import "./_js_globals.mjs";
import { pathToFileURL } from "node:url";
import { setTimeout as delay } from "node:timers/promises";
const st = await import(pathToFileURL(process.env.JS_ROOT + "/state.js").href);
const cp = await import(pathToFileURL(process.env.JS_ROOT + "/command-preview.js").href);
const le = await import(pathToFileURL(process.env.JS_ROOT + "/llama-edit.js").href);
const rc = await import(pathToFileURL(process.env.JS_ROOT + "/remote-cells.js").href);
const fm = await import(pathToFileURL(process.env.JS_ROOT + "/form.js").href);
const REG = __REG__, MODELS = __MODELS__, ARTIFACTS = __ARTIFACTS__;
const freshState = () => st.setState({ config: {}, runners: REG, artifacts: ARTIFACTS, models: MODELS, paths: {} });
const freshTopology = (nodes = []) => st.setTopology({ proxies: [], clients: [], routers: [], assignments: {}, nodes });
globalThis.__stubReturns = { "dialogs.appConfirm": async () => true };

// What the form's fields and the command preview were told, in order.
const LOG = [];
const el = (props = {}) => ({ value: "", dataset: {}, style: {}, textContent: "", innerHTML: "",
  classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
  addEventListener() {}, closest: () => null, querySelector: () => null, querySelectorAll: () => [], ...props });
const aliasField = (value = "", auto = true) => {
  const e = el({ dataset: auto && value ? { autoAlias: value } : {} });
  let cur = value;
  Object.defineProperty(e, "value", { get: () => cur, set: (v) => { LOG.push(["alias", v]); cur = v; }, enumerable: true });
  return e;
};
const previewBox = () => {
  const e = el();
  let cur = "";
  Object.defineProperty(e, "textContent", { get: () => cur, set: (v) => { LOG.push(["draw", String(v)]); cur = v; }, enumerable: true });
  return e;
};
// The model field. The page registers its change listeners on the first one it
// meets, once (openLlamaRemoteEdit); LISTENERS keeps them, in the order they came,
// and every later field runs them as a browser's dispatch would.
const LISTENERS = [];
let capturing = true;
// The form's own input and change listeners, kept the same way: what an edit of any field runs.
const FORM = { input: [], change: [] };
const formField = () => el({ addEventListener(ev, fn) { if (capturing && FORM[ev]) FORM[ev].push(fn); } });
const modelField = (value) => el({ value, closest: () => ({ style: {}, classList: { remove() {} } }),
  addEventListener(ev, fn) { if (capturing && ev === "change") LISTENERS.push(fn); },
  dispatchEvent(ev) { for (const fn of LISTENERS) fn(ev); return true; } });
const page = (over = {}) => {
  globalThis.__fields = {
    toast: el(),
    llamaRemoteEditOverlay: el({ hidden: false, hasAttribute: () => true, focus() {} }),
    "tr-MODEL_FILE": modelField(over.model ?? "__LLAMA__"),
    "tr-ALIAS": over.alias ?? aliasField("llama-3.3-70b-instruct-q4_k_m"),
    "tr-MODEL_NAME": el({ value: over.modelName ?? "" }),
    "tr-RUNNER": el({ value: over.runner ?? "llama-server" }),
    "tr-CELL_KIND": el(),
    "tr-SPEC_DRAFT_MODEL_FILE": el({ value: over.draft ?? "" }),
    "tr-PORT": el({ value: "__PORT__" }),
    llamaRemoteEditForm: formField(),
    "tr-SEAMLESS_TGT_LANG": el(), "tr-TRANSLATE_MODEL": el(), "tr-TRANSLATE_SRC_LANG": el(), "tr-TRANSLATE_TGT_LANG": el(),
    "tr-MOONSHINE_MODEL": el(), "tr-COMMAND": el(), "tr-ENV": el(), "tr-QUANTIZATION": el(),
    "tr-cmdPreview": previewBox(),
    "tr-strataDraft": el(),
    "tr-previewCmdline": el(),
    "tr-currentCmdline": el(),
  };
  return globalThis.__fields;
};
const F = () => globalThis.__fields;
const reset = () => {
  freshState(); freshTopology(); LOG.length = 0; page();
  globalThis.__fetchCalls.length = 0; globalThis.__fetchReply = {};
  for (const k of Object.keys(cp._cmdPreviewTimers)) clearTimeout(cp._cmdPreviewTimers[k]);
};
freshState(); freshTopology();
// The first opening of the form wires it, and the listeners are kept.
page();
rc.openLlamaRemoteEdit("h1", "gpu0", [], "");
capturing = false;
if (!LISTENERS.length) throw new Error("opening the form put no change listener on the model field");
if (!FORM.input.length || !FORM.change.length) throw new Error("opening the form put no input or change listener on the form");

// The operator types into a field (the input event bubbles to the form), or sets a select (the change event does).
const typeInto = (id, value) => { F()["tr-" + id].value = value; FORM.input.forEach((fn) => fn({ target: { id: "tr-" + id } })); };
const chooseIn = (id, value) => { F()["tr-" + id].value = value; FORM.change.forEach((fn) => fn({ target: { id: "tr-" + id } })); };

// The click on a picker row, and the reading of the form after it.
const pickModel = (value) => fm.mcSelectItem(F()["tr-MODEL_FILE"], value);
const shown = () => F()["tr-cmdPreview"].textContent;
const execLine = () => String(shown()).split("\n").filter((l) => l.startsWith("exec ")).pop() ?? null;
const flagIn = (flag) => (new RegExp(flag + " (\\S+)").exec(shown()) || [])[1] ?? null;
// A form of that runner, holding that model, as it stands when the operator has not touched it since.
const form = (runner, model, alias, extra = {}) => {
  page({ runner, model, alias: aliasField(alias), ...extra });
  le.renderCommandCellPreview("tr-");
  LOG.length = 0;
};
// A saved cell on port __PORT__, opened as the board opens it. Opening a saved cell asks the controller for its
// command (setEditCurrentCommand), writes the answer into "Current command" and draws once more: wait for that here,
// in this pin. A late draw would land in whichever pin runs next, and could answer a question that pin never put.
const openSaved = async (config) => {
  freshTopology([{ id: "h1", role: "host", servers: [{ isSlot: true, clientId: "h1", port: __PORT__, slotConfig: config }] }]);
  page({ alias: aliasField("") });
  globalThis.__fetchReply["/api/llama-command-preview"] = { tokens: ["bash", "run.sh"] };
  rc.openLlamaRemoteEdit("h1", "gpu0", [], "__PORT__");
  for (let i = 0; i < 100 && !F()["tr-currentCmdline"].textContent; i++) await delay(10);
};
// The machine's list of saved configs holds one backup; the returned function loads it as a click on its row does.
const backup = (config) => {
  let click = null;
  const row = { dataset: { remoteBackup: "b1.json" }, addEventListener(ev, fn) { if (ev === "click") click = fn; } };
  F()["tr-backupInfo"] = el();
  F()["tr-backups"] = el({ querySelectorAll: (sel) => (sel === "[data-remote-backup]" ? [row] : []) });
  globalThis.__fetchReply["/api/topology/client-llama/configs?hostId=h1"] = { configs: [{ filename: "b1.json", savedAt: "2026-10-13", config }] };
  return async () => { await rc.fetchAndRenderRemoteBackups("h1"); click(); };
};
const asked = () => globalThis.__fetchCalls.filter((c) => c.path === "/api/llama-command-preview").map((c) => JSON.parse(c.body).config);
// The controller's line is asked for 160 ms after the last draw (a debounce): wait for the question, not for the clock.
const untilAsked = async () => { for (let i = 0; i < 100 && !asked().length; i++) await delay(30); };
"""


def _exec(runner, cfg):
    """The line the server builds for a cell of that runner: what Apply saves."""
    return "exec " + _runner(runner).command(cfg)


def _pin(pid, setup, expr, expected, msg):
    return (pid, setup, expr, json.dumps(expected, ensure_ascii=False), msg)


GR00T_FORM = f'form("gr00t", "{GR00T_1}", "gr00t-n1.7-3b");'
CELL = '({ runner: F()["tr-RUNNER"].value, alias: F()["tr-ALIAS"].value, line: execLine() })'

PINS = [
    # ── the live defect: a pick that switches the runner ──
    _pin("add_model_then_pick_gr00t_names_the_new_alias",
         f'st.setState({{ config: {{ MODEL_FILE: "{LLAMA}" }}, runners: REG, artifacts: ARTIFACTS, models: MODELS, paths: {{}} }});',
         f'(() => {{ page({{ alias: aliasField("") }}); rc.openLlamaRemoteEdit("h1", "gpu0", [], "", {{ pickModel: true }}); '
         f'const awaited = [F()["tr-MODEL_FILE"].value, F()["tr-MODEL_FILE"].dataset.pickPending]; pickModel("{GR00T_1}"); '
         f'return {{ awaited, ...{CELL}, pending: F()["tr-MODEL_FILE"].dataset.pickPending ?? null }}; }})()',
         {"awaited": ["", "1"], "runner": "gr00t", "alias": "gr00t-n1.7-3b", "pending": None,
          "line": _exec("gr00t", {"MODEL_FILE": GR00T_1, "ALIAS": "gr00t-n1.7-3b"})},
         "defect-history: the live path — «＋ Add model» opens the form with the model field empty and awaited, the "
         "alias of the model the form opened with still in ALIAS; the GR00T folder picked from the list: the preview "
         "is the command Apply saves, named after the folder (v1.3.515 showed the first model's alias)"),
    _pin("gr00t_pick_from_llama_names_the_new_alias",
         "",
         f'(() => {{ pickModel("{GR00T_1}"); return {CELL}; }})()',
         {"runner": "gr00t", "alias": "gr00t-n1.7-3b",
          "line": _exec("gr00t", {"MODEL_FILE": GR00T_1, "ALIAS": "gr00t-n1.7-3b"})},
         "defect-history: picking the GR00T folder over the first model of the list — the form switches to GR00T and "
         "ALIAS follows the folder; the preview is the command Apply saves, named after the folder (it kept the first "
         "model's alias until another field was edited, v1.3.515)"),
    _pin("strata_pick_from_llama_names_the_new_alias_and_the_draft",
         "",
         f'(() => {{ pickModel("{STRATA_1}"); return {{ ...{CELL}, draft: F()["tr-SPEC_DRAFT_MODEL_FILE"].value }}; }})()',
         {"runner": "strata", "alias": "qwen3.8-flash-next-gsq-rco-iq2_xs", "draft": STRATA_1_MTP,
          "line": _exec("strata", {"MODEL_FILE": STRATA_1, "SPEC_DRAFT_MODEL_FILE": STRATA_1_MTP,
                                   "ALIAS": "qwen3.8-flash-next-gsq-rco-iq2_xs"})},
         "positive: picking the Strata model — its preview carries the new alias and the draft layer the pick filled "
         "in (--mtp), both written after the first draw"),
    _pin("strata_pick_from_llama_redraws_the_draft_note",
         "",
         f'(() => {{ pickModel("{STRATA_1}"); const n = F()["tr-strataDraft"]; '
         f'return [n.dataset.state, n.textContent.includes("{STRATA_1_MTP.split("/")[-1]}")]; }})()',
         ["on", True],
         "positive: the Strata panel's draft line names the draft the pick filled in (it said none was found: it was "
         "drawn before the draft was written)"),
    _pin("vllm_pick_from_llama_names_the_new_alias",
         "",
         f'(() => {{ pickModel("{QWEN}"); return [F()["tr-RUNNER"].value, F()["tr-ALIAS"].value, flagIn("--served-model-name")]; }})()',
         ["vllm", "qwen3-8b", "qwen3-8b"],
         "positive: a checkpoint folder over a llama.cpp model — the form switches to vLLM, whose --served-model-name "
         "is the alias the pick wrote"),
    # ── a pick that keeps the runner: it used to draw nothing (GR00T, seamless) or draw before the alias ──
    _pin("gr00t_pick_within_gr00t_names_the_new_folder",
         GR00T_FORM,
         f'(() => {{ pickModel("{GR00T_2}"); return {CELL}; }})()',
         {"runner": "gr00t", "alias": "gr00t-n1.6-3b",
          "line": _exec("gr00t", {"MODEL_FILE": GR00T_2, "ALIAS": "gr00t-n1.6-3b"})},
         "positive: another GR00T folder while the GR00T runner stays — the preview names the new folder and its alias "
         "(it was not drawn at all)"),
    _pin("seamless_pick_within_seamless_names_the_new_folder",
         f'form("seamless", "{SEAMLESS_1}", "seamless-m4t-v2-large");',
         f'(() => {{ pickModel("{SEAMLESS_2}"); return {CELL}; }})()',
         {"runner": "seamless", "alias": "seamless-m4t-medium", "line": _exec("seamless", {"MODEL_FILE": SEAMLESS_2})},
         "positive: another SeamlessM4T folder while the Seamless runner stays — the preview names the new folder (it "
         "was not drawn at all)"),
    _pin("strata_pick_within_strata_names_the_new_alias_and_draft",
         f'form("strata", "{STRATA_1}", "qwen3.8-flash-next-gsq-rco-iq2_xs", {{ draft: "{STRATA_1_MTP}" }});',
         f'(() => {{ pickModel("{STRATA_2}"); return {{ ...{CELL}, draft: F()["tr-SPEC_DRAFT_MODEL_FILE"].value }}; }})()',
         {"runner": "strata", "alias": "qwen3.8-flash-next-q4_0", "draft": STRATA_2_MTP,
          "line": _exec("strata", {"MODEL_FILE": STRATA_2, "SPEC_DRAFT_MODEL_FILE": STRATA_2_MTP,
                                   "ALIAS": "qwen3.8-flash-next-q4_0"})},
         "positive: another Strata model while the Strata runner stays — new model, alias and draft in the preview"),
    _pin("vllm_pick_within_vllm_names_the_new_alias",
         f'form("vllm", "{QWEN}", "qwen3-8b");',
         f'(() => {{ pickModel("{MISTRAL}"); return [F()["tr-RUNNER"].value, F()["tr-ALIAS"].value, flagIn("--served-model-name")]; }})()',
         ["vllm", "mistral-7b", "mistral-7b"],
         "positive: another checkpoint folder while the vLLM runner stays — --served-model-name is the new alias"),
    _pin("transcribe_pick_within_transcribe_names_the_new_file",
         f'form("transcribe", "{ASR_1}", "gigaam-v2");',
         f'(() => {{ pickModel("{ASR_2}"); return {CELL}; }})()',
         {"runner": "transcribe", "alias": "gigaam-v3", "line": _exec("transcribe", {"MODEL_FILE": ASR_2})},
         "positive: the runner that was drawn after a pick before — it still is"),
    # ── llama.cpp: the controller draws its line; the request must carry the pick's fields ──
    _pin("llama_pick_asks_the_controller_with_the_new_alias",
         "",
         f'await (async () => {{ pickModel("{GEMMA}"); await untilAsked(); '
         'const last = asked().at(-1) || {}; return [asked().length > 0, last.MODEL_FILE, last.ALIAS]; })()',
         [True, GEMMA, "gemma-3-27b-it-q4_k_m"],
         "positive: a llama.cpp pick — the line the controller is asked for carries the new model and its alias"),
    # ── the operator's MODEL_NAME is not the pick's to touch ──
    _pin("gr00t_pick_keeps_the_typed_model_name",
         'page({ modelName: "my-robot" });',
         f'(() => {{ pickModel("{GR00T_1}"); return {{ ...{CELL}, name: F()["tr-MODEL_NAME"].value }}; }})()',
         {"runner": "gr00t", "alias": "gr00t-n1.7-3b", "name": "my-robot",
          "line": _exec("gr00t", {"MODEL_FILE": GR00T_1, "ALIAS": "gr00t-n1.7-3b", "MODEL_NAME": "my-robot"})},
         "negative: a name the operator typed (MODEL_NAME) is not overwritten by the alias the pick writes, and the "
         "preview names the cell by it, not by the alias"),
    _pin("strata_pick_keeps_the_typed_model_name",
         'page({ modelName: "my-strata" });',
         f'(() => {{ pickModel("{STRATA_1}"); return {{ ...{CELL}, name: F()["tr-MODEL_NAME"].value }}; }})()',
         {"runner": "strata", "alias": "qwen3.8-flash-next-gsq-rco-iq2_xs", "name": "my-strata",
          "line": _exec("strata", {"MODEL_FILE": STRATA_1, "SPEC_DRAFT_MODEL_FILE": STRATA_1_MTP,
                                   "ALIAS": "qwen3.8-flash-next-gsq-rco-iq2_xs", "MODEL_NAME": "my-strata"})},
         "negative: the same for Strata"),
    # ── ALIAS follows an explicit pick even over a value the operator typed ──
    _pin("pick_over_a_typed_alias_follows_the_model",
         'page({ alias: aliasField("my-own-alias", false) });',
         f'(() => {{ pickModel("{GR00T_1}"); return {CELL}; }})()',
         {"runner": "gr00t", "alias": "gr00t-n1.7-3b",
          "line": _exec("gr00t", {"MODEL_FILE": GR00T_1, "ALIAS": "gr00t-n1.7-3b"})},
         "positive: an alias typed by hand is replaced on an explicit pick (aliasFollow), and the preview shows the "
         "replacement"),
    # ── the order: the last draw follows the last write of ALIAS ──
    _pin("preview_is_drawn_after_the_alias_is_written",
         "",
         f'(() => {{ pickModel("{GR00T_1}"); '
         'const at = (kind) => LOG.map((e, i) => (e[0] === kind ? i : -1)).filter((i) => i >= 0).at(-1) ?? -1; '
         'return [at("alias") >= 0, at("draw") > at("alias"), LOG[at("draw")]?.[1].includes("--name gr00t-n1.7-3b") ?? false]; })()',
         [True, True, True],
         "order: ALIAS is written, and after the last write the preview is drawn again from the new value — the "
         "last draw is the last thing the pick does to the form"),
    # ── opening the form: the autofill rules of the open, and the preview after them ──
    _pin("open_keeps_a_saved_alias",
         "",
         f'await (async () => {{ await openSaved({{ RUNNER: "gr00t", MODEL_FILE: "{GR00T_1}", ALIAS: "robot-saved" }}); return {CELL}; }})()',
         {"runner": "gr00t", "alias": "robot-saved",
          "line": _exec("gr00t", {"MODEL_FILE": GR00T_1, "ALIAS": "robot-saved"})},
         "negative: a cell saved with its own alias opens with it — the open does not derive one from the model; "
         "the preview names it"),
    _pin("open_keeps_a_saved_model_name",
         "",
         f'await (async () => {{ await openSaved({{ RUNNER: "gr00t", MODEL_FILE: "{GR00T_1}", MODEL_NAME: "gr00t-n1.7-droid" }}); '
         f'return {{ ...{CELL}, name: F()["tr-MODEL_NAME"].value }}; }})()',
         {"runner": "gr00t", "alias": "gr00t-n1.7-3b", "name": "gr00t-n1.7-droid",
          "line": _exec("gr00t", {"MODEL_FILE": GR00T_1, "ALIAS": "gr00t-n1.7-3b", "MODEL_NAME": "gr00t-n1.7-droid"})},
         "negative: a cell saved with a model name opens with it; the empty ALIAS is filled in, and the preview "
         "still names the cell by its MODEL_NAME"),
    # ── loading a backup: the same two calls as an opening ──
    _pin("backup_without_names_fills_the_alias_and_shows_it",
         "",
         f'await (async () => {{ await backup({{ RUNNER: "gr00t", MODEL_FILE: "{GR00T_1}" }})(); return {CELL}; }})()',
         {"runner": "gr00t", "alias": "gr00t-n1.7-3b",
          "line": _exec("gr00t", {"MODEL_FILE": GR00T_1, "ALIAS": "gr00t-n1.7-3b"})},
         "positive: a backup saved with neither name, loaded over a llama.cpp form — the alias is derived from its "
         "model and the preview carries it"),
    _pin("backup_keeps_a_saved_alias",
         "",
         f'await (async () => {{ await backup({{ RUNNER: "gr00t", MODEL_FILE: "{GR00T_1}", ALIAS: "robot-saved" }})(); return {CELL}; }})()',
         {"runner": "gr00t", "alias": "robot-saved",
          "line": _exec("gr00t", {"MODEL_FILE": GR00T_1, "ALIAS": "robot-saved"})},
         "negative: a backup saved with its own alias keeps it, over the alias of the model the form held"),
    _pin("open_without_names_fills_the_alias_and_shows_it",
         "",
         f'await (async () => {{ await openSaved({{ RUNNER: "gr00t", MODEL_FILE: "{GR00T_1}" }}); return {CELL}; }})()',
         {"runner": "gr00t", "alias": "gr00t-n1.7-3b",
          "line": _exec("gr00t", {"MODEL_FILE": GR00T_1, "ALIAS": "gr00t-n1.7-3b"})},
         "positive: a cell saved with neither name opens with the alias derived from its model, and the preview "
         "carries it (the open drew the preview first and wrote the alias after)"),

    # ── a typed edit: the form's own listeners draw every preview ──
    _pin("typed_alias_in_gr00t_names_the_typed_alias",
         GR00T_FORM,
         f'(() => {{ typeInto("ALIAS", "my-robot"); return {CELL}; }})()',
         {"runner": "gr00t", "alias": "my-robot",
          "line": _exec("gr00t", {"MODEL_FILE": GR00T_1, "ALIAS": "my-robot"})},
         "defect-history: an alias typed into a GR00T form — «New command» names it (the fixed list of fields that drew "
         "after an edit had no ALIAS, so the line kept the alias of the pick)"),
    _pin("typed_alias_in_vllm_names_the_served_model",
         f'form("vllm", "{QWEN}", "qwen3-8b");',
         '(() => { typeInto("ALIAS", "my-qwen"); return [F()["tr-RUNNER"].value, flagIn("--served-model-name")]; })()',
         ["vllm", "my-qwen"],
         "positive: an alias typed into a vLLM form — --served-model-name follows it"),
    _pin("typed_alias_in_strata_names_the_cell",
         f'form("strata", "{STRATA_1}", "qwen3.8-flash-next-gsq-rco-iq2_xs", {{ draft: "{STRATA_1_MTP}" }});',
         f'(() => {{ typeInto("ALIAS", "my-strata"); return {CELL}; }})()',
         {"runner": "strata", "alias": "my-strata",
          "line": _exec("strata", {"MODEL_FILE": STRATA_1, "SPEC_DRAFT_MODEL_FILE": STRATA_1_MTP, "ALIAS": "my-strata"})},
         "positive: an alias typed into a Strata form — --name follows it, the draft layer stays"),
    _pin("typed_draft_in_strata_redraws_mtp_and_its_note",
         f'form("strata", "{STRATA_1}", "qwen3.8-flash-next-gsq-rco-iq2_xs", {{ draft: "{STRATA_1_MTP}" }});',
         f'(() => {{ typeInto("SPEC_DRAFT_MODEL_FILE", "{STRATA_2_MTP}"); const n = F()["tr-strataDraft"]; '
         f'return {{ ...{CELL}, state: n.dataset.state, names: n.textContent.includes("{STRATA_2_MTP.split("/")[-1]}") }}; }})()',
         {"runner": "strata", "alias": "qwen3.8-flash-next-gsq-rco-iq2_xs", "state": "on", "names": True,
          "line": _exec("strata", {"MODEL_FILE": STRATA_1, "SPEC_DRAFT_MODEL_FILE": STRATA_2_MTP,
                                   "ALIAS": "qwen3.8-flash-next-gsq-rco-iq2_xs"})},
         "positive: a draft file typed into a Strata form — --mtp names it, and so does the panel's draft line"),
    _pin("typed_model_name_beats_the_alias",
         GR00T_FORM,
         f'(() => {{ typeInto("MODEL_NAME", "my-named"); return {CELL}; }})()',
         {"runner": "gr00t", "alias": "gr00t-n1.7-3b",
          "line": _exec("gr00t", {"MODEL_FILE": GR00T_1, "ALIAS": "gr00t-n1.7-3b", "MODEL_NAME": "my-named"})},
         "positive: a model name typed into a GR00T form — the line names the cell by it, not by the alias (a field the old list "
         "had: the form-wide listener keeps what the list did)"),
    _pin("typed_alias_twice_draws_the_last_value",
         GR00T_FORM,
         '(() => { typeInto("ALIAS", "a"); typeInto("ALIAS", "ab"); return flagIn("--name"); })()',
         "ab",
         "boundary: two edits in a row — the preview is the last one's, nothing of the first is left"),
    _pin("chosen_seamless_language_redraws_the_command",
         f'form("seamless", "{SEAMLESS_1}", "seamless-m4t-v2-large");',
         '(() => { chooseIn("SEAMLESS_TGT_LANG", "eng"); return execLine(); })()',
         _exec("seamless", {"MODEL_FILE": SEAMLESS_1, "SEAMLESS_TGT_LANG": "eng"}),
         "positive: a target language set on the Seamless select (a change event) — the command ends with it"),
    _pin("typed_nllb_fields_redraw_the_command",
         'form("translate", "", "");',
         '(() => { typeInto("TRANSLATE_MODEL", "facebook/nllb-200-distilled-1.3B"); typeInto("TRANSLATE_SRC_LANG", "fra_Latn"); '
         'typeInto("TRANSLATE_TGT_LANG", "deu_Latn"); return execLine(); })()',
         _exec("translate", {"TRANSLATE_MODEL": "facebook/nllb-200-distilled-1.3B", "TRANSLATE_SRC_LANG": "fra_Latn",
                             "TRANSLATE_TGT_LANG": "deu_Latn"}),
         "positive: the NLLB model and both languages typed — the command carries all three, in the server's order"),
    _pin("typed_moonshine_language_redraws_the_command",
         'form("moonshine", "", "");',
         '(() => { typeInto("MOONSHINE_MODEL", "es"); return execLine(); })()',
         _exec("moonshine", {"MOONSHINE_MODEL": "es"}),
         "positive: a language typed into a Moonshine form — the command names it"),
    _pin("typed_port_redraws_the_exported_port",
         GR00T_FORM,
         '(() => { typeInto("PORT", "22044"); return String(shown()).split("\\n")[0]; })()',
         "export PORT=22044",
         "positive: a port typed into a command cell's form — the first line of the preview exports it"),
    _pin("typed_custom_command_and_env_redraw",
         'form("custom", "", "");',
         '(() => { typeInto("COMMAND", "python serve.py --x"); typeInto("ENV", "A=1"); '
         'return [execLine(), String(shown()).includes("export A=")]; })()',
         ["exec python serve.py --x", True],
         "positive: the custom runner's command and env typed — the preview shows the command and the exported variable "
         "(what the old per-field list drew: the form-wide listener keeps it)"),
    _pin("chosen_vllm_quantization_redraws_the_command",
         f'form("vllm", "{QWEN}", "qwen3-8b");',
         '(() => { chooseIn("QUANTIZATION", "awq"); return flagIn("--quantization"); })()',
         "awq",
         "positive: a vLLM select set (a change event) — its flag is in the command (a field the old list had)"),
    _pin("typed_alias_in_llama_form_asks_the_controller_not_the_page",
         f'form("llama-server", "{LLAMA}", "llama-3.3-70b-instruct-q4_k_m");',
         'await (async () => { typeInto("ALIAS", "my-llama"); await untilAsked(); '
         'return [LOG.filter((e) => e[0] === "draw").length, asked().at(-1).ALIAS]; })()',
         [0, "my-llama"],
         "negative: an alias typed into a llama.cpp form — the controller is asked for its line with it, and the page draws "
         "no line of its own (its panel is hidden: the controller's command is the one that runs)"),
]

if __name__ == "__main__":
    pre = (PREAMBLE.replace("__REG__", json.dumps(registry_json()))
           .replace("__MODELS__", json.dumps(MODELS)).replace("__ARTIFACTS__", json.dumps(ARTIFACTS))
           .replace("__LLAMA__", LLAMA).replace("__PORT__", PORT))
    sys.exit(run("js cell-previews", ".probe_js_cell_previews.tmp.mjs", pre, PINS,
                 stubs="topology-render,topology-modals,cables,routers,cloud,history,dialogs,favorites,config-locator,"
                       "system-panels,onboarding,topology-dnd,canvas,usage-stats,dialog-llamas,models-page,system-page,"
                       "onboarding-tours"))
