#!/usr/bin/env python3
"""Snapshot of static/js/llama-edit.js — the cell editor: what it will launch.

18 fixes in this module's history, four of them in the DOM-free
_buildCommandExecPreview: the preview shows the command Apply will actually
write (2062ee8, ed5d4d3), knows about moonshine and seamless (395664a,
6858617), states what will actually launch (f28e409). VALUES are pinned:
eight runner branches of the preview with their defaults and path rules,
parsing ENV (commas and newlines, comments, invalid keys), effectiveRunnerId
by priority, building the vLLM command, artifactKind from a model's metadata,
the compute-capability table, a device read from ENV/COMMAND and written back
to it, the runner registry, backup labels.

The form is the globalThis.__fields dict (F({...})); fields carry the
"te-"/"tr-" prefix. Pins live as data in PINS; each runs in its own
try/catch after reset(). Time is frozen. The module is loaded FOR REAL
(_js_harness.mjs).

Run: python3 scripts/test_js_llama_edit.py
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _rust_leased_port():
    """The controller's own word for a start's port before its scout leases one (LlamaArgs::LEASED_PORT): the preview's twin."""
    text = (ROOT / "rust/crates/admin/src/config/args.rs").read_text(encoding="utf-8")
    return re.search(r'pub const LEASED_PORT: &\'static str = "([^"]+)";', text).group(1)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _node import find_node, node_search_paths, probe_args  # noqa: E402

STUBS = ("topology-render,topology-modals,cables,routers,cloud,history,dialogs,favorites,config-locator,system-panels,"
         "onboarding,topology-dnd,canvas,usage-stats,dialog-llamas,models-page,system-page,onboarding-tours")

PREAMBLE = r"""
import "./_js_globals.mjs";
import { pathToFileURL } from "node:url";
const st = await import(pathToFileURL(process.env.JS_ROOT + "/state.js").href);
st.setState({ config: {}, runners: [], artifacts: [], models: [], paths: {} });
st.setTopology({ proxies: [], clients: [], routers: [], assignments: {}, nodes: [] });
Date.now = () => 1_700_000_100_000;
globalThis.__stubReturns = { "dialogs.appConfirm": async () => true };
const le = await import(pathToFileURL(process.env.JS_ROOT + "/llama-edit.js").href);
const rc = await import(pathToFileURL(process.env.JS_ROOT + "/remote-cells.js").href);
const cst = await import(pathToFileURL(process.env.JS_ROOT + "/constants.js").href);
const ui = st.ui;
const norm = (s) => String(s).replace(/\s+/g, " ").trim();
const toastEl = () => ({ textContent: "", classList: { add() {}, remove() {} } });
const F = (fields) => { globalThis.__fields = { toast: toastEl(), ...fields }; };
const reset = () => { st.setState({ config: {}, runners: [], artifacts: [], models: [], paths: {} });
  st.setTopology({ proxies: [], clients: [], routers: [], assignments: {}, nodes: [] });
  F({}); globalThis.__fetchCalls.length = 0; globalThis.__fetchReply = {}; globalThis.__stubReturns = { "dialogs.appConfirm": async () => true };
  for (const c of [rc._stoppingHosts, rc._stoppingCells, rc._deletingSlots, rc._newReservedCells, rc._pendingCellActions, rc._reservingCells]) c.clear(); };
const calls = () => globalThis.__fetchCalls.map((c) => ({ path: c.path, method: c.method, body: c.body }));
const toastText = () => globalThis.__fields.toast.textContent;
const out = {};
"""

# (id, setup, expression, expected JSON string, message). Filled from the pin
# workflow; see the OOP-rewrite journal (private), phase 7, snapshot 6.
PINS = [
    ('prism_native',
     'st.setState({runners:[{id:"prism",llamaConfig:true}]});',
     '[le.usesLlamaConfig("prism"), le.usesLlamaConfig("unknown")]',
     '[true,false]',
     'Prism использует параметры GGUF; неизвестный runner их не наследует'),
    ('prism_preview',
     'st.setState({runners:[{id:"prism",llamaConfig:true}]}); F({"tr-RUNNER":{value:"prism"}});',
     'le._buildCommandExecPreview("tr-")',
     '"export PORT={{PORT}}\\n# prism: the controller renders this command, not this preview"',
     'Prism идёт через общий построитель команды, не через custom'),

    # ── exec_preview ──
    ('er_explicit_trimmed',
     'F({ "te-RUNNER": { value: "  whisper  " } });',
     'le.effectiveRunnerId("te-")',
     '"whisper"',
     'positive: явный RUNNER берётся с обрезкой пробелов'),
    ('er_explicit_beats_kind',
     'F({ "te-RUNNER": { value: "vllm" }, "te-CELL_KIND": { value: "command" } });',
     'le.effectiveRunnerId("te-")',
     '"vllm"',
     'positive: явный RUNNER важнее CELL_KIND=command'),
    ('er_kind_command_custom',
     'F({ "te-CELL_KIND": { value: "command" } });',
     'le.effectiveRunnerId("te-")',
     '"custom"',
     'positive: без RUNNER: CELL_KIND=command → custom'),
    ('er_kind_command_runner_ws',
     'F({ "te-RUNNER": { value: "   " }, "te-CELL_KIND": { value: "command" } });',
     'le.effectiveRunnerId("te-")',
     '"custom"',
     'boundary: RUNNER из одних пробелов = пустой → решает CELL_KIND'),
    ('er_kind_other_llama',
     'F({ "te-CELL_KIND": { value: "llama" } });',
     'le.effectiveRunnerId("te-")',
     '"llama-server"',
     'negative: CELL_KIND≠command → llama-server'),
    ('er_no_fields_llama',
     'F({});',
     'le.effectiveRunnerId("te-")',
     '"llama-server"',
     'negative: полей нет вовсе → llama-server'),
    ('er_tr_prefix',
     'F({ "tr-RUNNER": { value: "moonshine" } });',
     'le.effectiveRunnerId("tr-")',
     '"moonshine"',
     'positive: префикс tr- читает поле tr-RUNNER'),
    ('er_prefix_isolation',
     'F({ "tr-RUNNER": { value: "moonshine" }, "tr-CELL_KIND": { value: "command" } });',
     'le.effectiveRunnerId("te-")',
     '"llama-server"',
     'negative: поля tr- не протекают в te-'),
    ('vllm_no_fields',
     'F({});',
     'le.buildVllmCommandPreview("te-")',
     '"$HOME/vllm-venv/bin/vllm serve … --host 0.0.0.0 --port \\"$PORT\\""',
     'negative: без модели: многоточие вместо модели, без served-model-name'),
    ('vllm_served_from_path',
     'F({ "te-VLLM_MODEL": { value: " Qwen/Qwen2.5-7B-Instruct " } });',
     'le.buildVllmCommandPreview("te-")',
     '"$HOME/vllm-venv/bin/vllm serve Qwen/Qwen2.5-7B-Instruct --host 0.0.0.0 --port \\"$PORT\\" --served-model-name qwen2.5-7b-instruct"',
     'positive: served-model-name = последний сегмент пути в нижнем регистре'),
    ('vllm_served_by_operators_name',
     'F({ "te-VLLM_MODEL": { value: "Qwen/Qwen2.5-7B-Instruct" }, "te-ALIAS": { value: "from-another-file" }, "te-MODEL_NAME": { value: "mine" } });',
     'le.buildVllmCommandPreview("te-")',
     '"$HOME/vllm-venv/bin/vllm serve Qwen/Qwen2.5-7B-Instruct --host 0.0.0.0 --port \\"$PORT\\" --served-model-name mine"',
     'positive: имя оператора важнее псевдонима: запрос по этому имени находит модель (проверка владельца, 2026-11-01)'),
    ('vllm_served_no_slash',
     'F({ "te-VLLM_MODEL": { value: "GPT-OSS" } });',
     'le.buildVllmCommandPreview("te-")',
     '"$HOME/vllm-venv/bin/vllm serve GPT-OSS --host 0.0.0.0 --port \\"$PORT\\" --served-model-name gpt-oss"',
     'boundary: модель без слэша: served-model-name = вся строка в нижнем регистре'),
    ('vllm_alias_wins',
     'F({ "te-VLLM_MODEL": { value: "Qwen/Qwen2.5-7B" }, "te-ALIAS": { value: " MyAlias " } });',
     'le.buildVllmCommandPreview("te-")',
     '"$HOME/vllm-venv/bin/vllm serve Qwen/Qwen2.5-7B --host 0.0.0.0 --port \\"$PORT\\" --served-model-name MyAlias"',
     'positive: ALIAS важнее сегмента пути и регистр не меняется'),
    ('vllm_alias_ws_ignored',
     'F({ "te-VLLM_MODEL": { value: "Qwen/Qwen2.5-7B" }, "te-ALIAS": { value: "   " } });',
     'le.buildVllmCommandPreview("te-")',
     '"$HOME/vllm-venv/bin/vllm serve Qwen/Qwen2.5-7B --host 0.0.0.0 --port \\"$PORT\\" --served-model-name qwen2.5-7b"',
     'negative: ALIAS из пробелов = пустой → имя из пути'),
    ('vllm_alias_without_model',
     'F({ "te-ALIAS": { value: "solo" } });',
     'le.buildVllmCommandPreview("te-")',
     '"$HOME/vllm-venv/bin/vllm serve … --host 0.0.0.0 --port \\"$PORT\\" --served-model-name solo"',
     'boundary: ALIAS без модели: многоточие + served-model-name'),
    ('vllm_maxlen_gpu_set',
     'F({ "te-VLLM_MODEL": { value: "m" }, "te-MAX_MODEL_LEN": { value: " 8192 " }, "te-GPU_MEMORY_UTILIZATION": { value: "0.9" } });',
     'le.buildVllmCommandPreview("te-")',
     '"$HOME/vllm-venv/bin/vllm serve m --host 0.0.0.0 --port \\"$PORT\\" --served-model-name m --max-model-len 8192 --gpu-memory-utilization 0.9"',
     'positive: MAX_MODEL_LEN и GPU_MEMORY_UTILIZATION попадают в команду обрезанными'),
    ('vllm_maxlen_gpu_ws_omitted',
     'F({ "te-VLLM_MODEL": { value: "m" }, "te-MAX_MODEL_LEN": { value: "  " }, "te-GPU_MEMORY_UTILIZATION": { value: "" } });',
     'le.buildVllmCommandPreview("te-")',
     '"$HOME/vllm-venv/bin/vllm serve m --host 0.0.0.0 --port \\"$PORT\\" --served-model-name m"',
     'negative: пустые/пробельные MAX_MODEL_LEN и GPU_MEMORY_UTILIZATION опускаются'),
    ('vllm_quant_set_lowercased',
     'F({ "te-VLLM_MODEL": { value: "m" }, "te-QUANTIZATION": { value: "Awq" } });',
     'le.buildVllmCommandPreview("te-")',
     '"$HOME/vllm-venv/bin/vllm serve m --host 0.0.0.0 --port \\"$PORT\\" --served-model-name m --quantization awq"',
     'positive: QUANTIZATION печатается в нижнем регистре'),
    ('vllm_quant_auto_omitted',
     'F({ "te-VLLM_MODEL": { value: "m" }, "te-QUANTIZATION": { value: "AUTO" } });',
     'le.buildVllmCommandPreview("te-")',
     '"$HOME/vllm-venv/bin/vllm serve m --host 0.0.0.0 --port \\"$PORT\\" --served-model-name m"',
     'negative: QUANTIZATION=AUTO (любой регистр) опускается'),
    ('vllm_dtype_set_lowercased',
     'F({ "te-VLLM_MODEL": { value: "m" }, "te-DTYPE": { value: "BF16" } });',
     'le.buildVllmCommandPreview("te-")',
     '"$HOME/vllm-venv/bin/vllm serve m --host 0.0.0.0 --port \\"$PORT\\" --served-model-name m --dtype bf16"',
     'positive: DTYPE печатается в нижнем регистре'),
    ('vllm_dtype_auto_omitted',
     'F({ "te-VLLM_MODEL": { value: "m" }, "te-DTYPE": { value: "Auto" } });',
     'le.buildVllmCommandPreview("te-")',
     '"$HOME/vllm-venv/bin/vllm serve m --host 0.0.0.0 --port \\"$PORT\\" --served-model-name m"',
     'negative: DTYPE=Auto (любой регистр) опускается'),
    ('vllm_tp_variants',
     'F({});',
     '["", "0", "1", "2", " 4 "].map((v) => { F({ "te-VLLM_MODEL": { value: "m" }, "te-TENSOR_PARALLEL": { value: v } }); return le.buildVllmCommandPreview("te-"); })',
     '["$HOME/vllm-venv/bin/vllm serve m --host 0.0.0.0 --port \\"$PORT\\" --served-model-name m","$HOME/vllm-venv/bin/vllm serve m --host 0.0.0.0 --port \\"$PORT\\" --served-model-name m","$HOME/vllm-venv/bin/vllm serve m --host 0.0.0.0 --port \\"$PORT\\" --served-model-name m","$HOME/vllm-venv/bin/vllm serve m --host 0.0.0.0 --port \\"$PORT\\" --served-model-name m --tensor-parallel-size 2","$HOME/vllm-venv/bin/vllm serve m --host 0.0.0.0 --port \\"$PORT\\" --served-model-name m --tensor-parallel-size 4"]',
     'boundary: TENSOR_PARALLEL: пусто/0/1 опускаются, 2 и 4 печатаются'),
    ('vllm_tr_prefix',
     'F({ "tr-VLLM_MODEL": { value: "org/Big-Model" }, "tr-DTYPE": { value: "half" } });',
     'le.buildVllmCommandPreview("tr-")',
     '"$HOME/vllm-venv/bin/vllm serve org/Big-Model --host 0.0.0.0 --port \\"$PORT\\" --served-model-name big-model --dtype half"',
     'positive: префикс tr- читает поля tr-VLLM_MODEL/tr-DTYPE'),
    ('vllm_prefix_isolation',
     'F({ "tr-VLLM_MODEL": { value: "org/Big-Model" } });',
     'le.buildVllmCommandPreview("te-")',
     '"$HOME/vllm-venv/bin/vllm serve … --host 0.0.0.0 --port \\"$PORT\\""',
     'negative: tr-VLLM_MODEL не виден превью te-'),
    ('exec_port_is_the_leased_placeholder',
     'F({ "te-RUNNER": { value: "vllm" } });',
     'le._buildCommandExecPreview("te-")',
     '"export PORT={{PORT}}\\n# first start on a host provisions ~/vllm-venv (several minutes)\\nexec $HOME/vllm-venv/bin/vllm serve … --host 0.0.0.0 --port \\"$PORT\\""',
     'порт старта в превью — заглушка {{PORT}}, которую скаут заполняет при старте (LlamaArgs::LEASED_PORT): порт у ячейки только у работающей; было буквальное «export PORT=PORT»'),
    ('exec_port_placeholder_is_the_servers',
     '',
     'le.LEASED_PORT',
     json.dumps(_rust_leased_port()),
     'двойник: заглушка порта в превью — та же, что у контроллера (LlamaArgs::LEASED_PORT в config/args.rs), которую скаут заполняет при старте; разойдутся — пин красный'),
    ('exec_port_field_on_the_page_is_not_read',
     'F({ "te-RUNNER": { value: "vllm" }, "te-PORT": { value: "22005" }, "tr-RUNNER": { value: "custom" }, "tr-PORT": { value: "22077" }, "tr-COMMAND": { value: "run.sh" } });',
     '[le._buildCommandExecPreview("te-").split("\\n")[0], le._buildCommandExecPreview("tr-").split("\\n")[0]]',
     '["export PORT={{PORT}}", "export PORT={{PORT}}"]',
     'negative: поле PORT, оставшееся на странице, не читается ни одной формой — превью говорит заглушку скаута, а не 22005 и не 22077'),
    ('exec_port_tr_placeholder',
     'F({ "tr-RUNNER": { value: "vllm" } });',
     'le._buildCommandExecPreview("tr-").split("\\n")[0]',
     '"export PORT={{PORT}}"',
     'tr- без порта: та же заглушка скаута'),
    ('exec_vllm_te',
     'F({ "te-RUNNER": { value: "vllm" }, "te-VLLM_MODEL": { value: "Qwen/Qwen2.5-7B" }, "te-MAX_MODEL_LEN": { value: "4096" } });',
     'le._buildCommandExecPreview("te-")',
     '"export PORT={{PORT}}\\n# first start on a host provisions ~/vllm-venv (several minutes)\\nexec $HOME/vllm-venv/bin/vllm serve Qwen/Qwen2.5-7B --host 0.0.0.0 --port \\"$PORT\\" --served-model-name qwen2.5-7b --max-model-len 4096"',
     'positive: ветка vllm: export, комментарий о venv, exec с командой vllm'),
    ('exec_vllm_tr',
     'F({ "tr-RUNNER": { value: "vllm" }, "tr-VLLM_MODEL": { value: "org/M" } });',
     'le._buildCommandExecPreview("tr-")',
     '"export PORT={{PORT}}\\n# first start on a host provisions ~/vllm-venv (several minutes)\\nexec $HOME/vllm-venv/bin/vllm serve org/M --host 0.0.0.0 --port \\"$PORT\\" --served-model-name m"',
     'positive: ветка vllm для префикса tr-'),
    ('exec_whisper_default_size',
     'F({ "te-RUNNER": { value: "whisper" } });',
     'le._buildCommandExecPreview("te-")',
     '"export PORT={{PORT}}\\n# model downloads on first start into <models root>/whisper\\nexec env HUGGINGFACE_HUB_CACHE=\\"${LLAMA_MODELS_DIR:-$HOME/llama-model-cache}/whisper\\" bash $HOME/run_whisper.sh \\"$PORT\\" large-v3"',
     'positive: whisper без размера: large-v3 и строка HUGGINGFACE_HUB_CACHE'),
    ('exec_whisper_size_trimmed',
     'F({ "te-RUNNER": { value: "whisper" }, "te-WHISPER_MODEL": { value: " small " } });',
     'le._buildCommandExecPreview("te-")',
     '"export PORT={{PORT}}\\n# model downloads on first start into <models root>/whisper\\nexec env HUGGINGFACE_HUB_CACHE=\\"${LLAMA_MODELS_DIR:-$HOME/llama-model-cache}/whisper\\" bash $HOME/run_whisper.sh \\"$PORT\\" small"',
     'positive: whisper: WHISPER_MODEL обрезается и подставляется'),
    ('exec_whisper_size_ws_default',
     'F({ "te-RUNNER": { value: "whisper" }, "te-WHISPER_MODEL": { value: "   " } });',
     'le._buildCommandExecPreview("te-").split("\\n")[2]',
     '"exec env HUGGINGFACE_HUB_CACHE=\\"${LLAMA_MODELS_DIR:-$HOME/llama-model-cache}/whisper\\" bash $HOME/run_whisper.sh \\"$PORT\\" large-v3"',
     'negative: whisper: пробельный WHISPER_MODEL → large-v3'),
    ('exec_whisper_tr',
     'F({ "tr-RUNNER": { value: "whisper" }, "tr-WHISPER_MODEL": { value: "medium" } });',
     'le._buildCommandExecPreview("tr-")',
     '"export PORT={{PORT}}\\n# model downloads on first start into <models root>/whisper\\nexec env HUGGINGFACE_HUB_CACHE=\\"${LLAMA_MODELS_DIR:-$HOME/llama-model-cache}/whisper\\" bash $HOME/run_whisper.sh \\"$PORT\\" medium"',
     'positive: ветка whisper для префикса tr-'),
    ('exec_transcribe_relative',
     'F({ "te-RUNNER": { value: "transcribe" }, "te-MODEL_FILE": { value: " stt/gigaam-v2.gguf " } });',
     'le._buildCommandExecPreview("te-")',
     '"export PORT={{PORT}}\\n# the engine and its venv come from scripts/install-transcribe.sh\\nexec bash $HOME/run_transcribe.sh \\"$PORT\\" \\"${LLAMA_MODELS_DIR:-$HOME/llama.cpp/models}\\"/stt/gigaam-v2.gguf"',
     'defect-history: f28e409: transcribe с относительным MODEL_FILE → "${LLAMA_MODELS_DIR:-$HOME/llama.cpp/models}"/<mf>'),
    ('exec_transcribe_absolute',
     'F({ "te-RUNNER": { value: "transcribe" }, "te-MODEL_FILE": { value: "/opt/models/x.gguf" } });',
     'le._buildCommandExecPreview("te-").split("\\n")[2]',
     '"exec bash $HOME/run_transcribe.sh \\"$PORT\\" \\"/opt/models/x.gguf\\""',
     'defect-history: f28e409: абсолютный MODEL_FILE цитируется как есть без корня моделей'),
    ('exec_transcribe_dollar',
     'F({ "te-RUNNER": { value: "transcribe" }, "te-MODEL_FILE": { value: "$HOME/models/x.gguf" } });',
     'le._buildCommandExecPreview("te-").split("\\n")[2]',
     '"exec bash $HOME/run_transcribe.sh \\"$PORT\\" \\"$HOME/models/x.gguf\\""',
     'defect-history: f28e409: MODEL_FILE с $ в начале цитируется как есть'),
    ('exec_transcribe_empty',
     'F({ "te-RUNNER": { value: "transcribe" }, "te-MODEL_FILE": { value: "  " } });',
     'le._buildCommandExecPreview("te-").split("\\n")[2]',
     '"exec bash $HOME/run_transcribe.sh \\"$PORT\\" \\"…\\""',
     'negative: transcribe без MODEL_FILE → многоточие в кавычках'),
    ('exec_transcribe_tr',
     'F({ "tr-RUNNER": { value: "transcribe" }, "tr-MODEL_FILE": { value: "a.gguf" } });',
     'le._buildCommandExecPreview("tr-")',
     '"export PORT={{PORT}}\\n# the engine and its venv come from scripts/install-transcribe.sh\\nexec bash $HOME/run_transcribe.sh \\"$PORT\\" \\"${LLAMA_MODELS_DIR:-$HOME/llama.cpp/models}\\"/a.gguf"',
     'positive: ветка transcribe для префикса tr-'),
    ('exec_moonshine_default_en',
     'F({ "te-RUNNER": { value: "moonshine" } });',
     'le._buildCommandExecPreview("te-")',
     '"export PORT={{PORT}}\\n# first start provisions ~/moonshine-venv and fetches the model\\nexec bash $HOME/run_moonshine.sh \\"$PORT\\" en"',
     'defect-history: 395664a: moonshine получил свою ветку (раньше показывал чужую llama-строку); без MOONSHINE_MODEL → en'),
    ('exec_moonshine_blank_en',
     'F({ "te-RUNNER": { value: "moonshine" }, "te-MOONSHINE_MODEL": { value: "   " } });',
     'le._buildCommandExecPreview("te-").split("\\n")[2]',
     '"exec bash $HOME/run_moonshine.sh \\"$PORT\\" en"',
     'defect-history: 395664a: пробельный MOONSHINE_MODEL → en'),
    ('exec_moonshine_lang_trimmed',
     'F({ "te-RUNNER": { value: "moonshine" }, "te-MOONSHINE_MODEL": { value: " ru " } });',
     'le._buildCommandExecPreview("te-").split("\\n")[2]',
     '"exec bash $HOME/run_moonshine.sh \\"$PORT\\" ru"',
     'positive: moonshine: язык из поля с обрезкой'),
    ('exec_moonshine_tr',
     'F({ "tr-RUNNER": { value: "moonshine" }, "tr-MOONSHINE_MODEL": { value: "es" } });',
     'le._buildCommandExecPreview("tr-")',
     '"export PORT={{PORT}}\\n# first start provisions ~/moonshine-venv and fetches the model\\nexec bash $HOME/run_moonshine.sh \\"$PORT\\" es"',
     'positive: ветка moonshine для префикса tr-'),
    ('exec_translate_defaults',
     'F({ "te-RUNNER": { value: "translate" } });',
     'le._buildCommandExecPreview("te-")',
     '"export PORT={{PORT}}\\n# model downloads on first start into <models root>/translate\\nexec env HUGGINGFACE_HUB_CACHE=\\"${LLAMA_MODELS_DIR:-$HOME/llama-model-cache}/translate\\" bash $HOME/run_translate.sh \\"$PORT\\" facebook/nllb-200-distilled-600M eng_Latn rus_Cyrl"',
     'positive: translate по умолчанию: nllb-200-distilled-600M, eng_Latn → rus_Cyrl'),
    ('exec_translate_all_set',
     'F({ "te-RUNNER": { value: "translate" }, "te-TRANSLATE_MODEL": { value: " facebook/nllb-200-1.3B " }, "te-TRANSLATE_SRC_LANG": { value: " deu_Latn " }, "te-TRANSLATE_TGT_LANG": { value: " fra_Latn " } });',
     'le._buildCommandExecPreview("te-").split("\\n")[2]',
     '"exec env HUGGINGFACE_HUB_CACHE=\\"${LLAMA_MODELS_DIR:-$HOME/llama-model-cache}/translate\\" bash $HOME/run_translate.sh \\"$PORT\\" facebook/nllb-200-1.3B deu_Latn fra_Latn"',
     'positive: translate: модель и оба языка из полей, обрезанные'),
    ('exec_translate_model_ws_default',
     'F({ "te-RUNNER": { value: "translate" }, "te-TRANSLATE_MODEL": { value: "   " } });',
     'le._buildCommandExecPreview("te-").split("\\n")[2]',
     '"exec env HUGGINGFACE_HUB_CACHE=\\"${LLAMA_MODELS_DIR:-$HOME/llama-model-cache}/translate\\" bash $HOME/run_translate.sh \\"$PORT\\" facebook/nllb-200-distilled-600M eng_Latn rus_Cyrl"',
     'negative: translate: пробельная модель → дефолт (trim до ||)'),
    ('exec_translate_langs_ws_empty',
     'F({ "te-RUNNER": { value: "translate" }, "te-TRANSLATE_SRC_LANG": { value: "  " }, "te-TRANSLATE_TGT_LANG": { value: "  " } });',
     'le._buildCommandExecPreview("te-").split("\\n")[2]',
     '"exec env HUGGINGFACE_HUB_CACHE=\\"${LLAMA_MODELS_DIR:-$HOME/llama-model-cache}/translate\\" bash $HOME/run_translate.sh \\"$PORT\\" facebook/nllb-200-distilled-600M eng_Latn rus_Cyrl"',
     'negative: пробельные языки падают в дефолт — trim ДО ||, как у модели и у всех прочих раннеров'),
    ('exec_translate_tr',
     'F({ "tr-RUNNER": { value: "translate" } });',
     'le._buildCommandExecPreview("tr-")',
     '"export PORT={{PORT}}\\n# model downloads on first start into <models root>/translate\\nexec env HUGGINGFACE_HUB_CACHE=\\"${LLAMA_MODELS_DIR:-$HOME/llama-model-cache}/translate\\" bash $HOME/run_translate.sh \\"$PORT\\" facebook/nllb-200-distilled-600M eng_Latn rus_Cyrl"',
     'positive: ветка translate для префикса tr-'),
    ('exec_seamless_relative_default_tgt',
     'F({ "te-RUNNER": { value: "seamless" }, "te-MODEL_FILE": { value: "seamless/m4t.pt" } });',
     'le._buildCommandExecPreview("te-")',
     '"export PORT={{PORT}}\\n# first start provisions ~/seamless-venv (torch + transformers)\\nexec bash $HOME/run_seamless.sh \\"$PORT\\" \\"${LLAMA_MODELS_DIR:-$HOME/llama.cpp/models}\\"/seamless/m4t.pt rus"',
     'defect-history: 6858617/395664a: ветка seamless есть; относительный MODEL_FILE под корнем моделей, SEAMLESS_TGT_LANG по умолчанию rus'),
    ('exec_seamless_absolute',
     'F({ "te-RUNNER": { value: "seamless" }, "te-MODEL_FILE": { value: "/opt/m4t" } });',
     'le._buildCommandExecPreview("te-").split("\\n")[2]',
     '"exec bash $HOME/run_seamless.sh \\"$PORT\\" \\"/opt/m4t\\" rus"',
     'defect-history: 395664a: seamless с абсолютным MODEL_FILE цитирует его как есть'),
    ('exec_seamless_dollar',
     'F({ "te-RUNNER": { value: "seamless" }, "te-MODEL_FILE": { value: "$MODELS/m4t" } });',
     'le._buildCommandExecPreview("te-").split("\\n")[2]',
     '"exec bash $HOME/run_seamless.sh \\"$PORT\\" \\"$MODELS/m4t\\" rus"',
     'defect-history: 395664a: seamless с $-путём цитирует его как есть'),
    ('exec_seamless_empty',
     'F({ "te-RUNNER": { value: "seamless" } });',
     'le._buildCommandExecPreview("te-").split("\\n")[2]',
     '"exec bash $HOME/run_seamless.sh \\"$PORT\\" \\"…\\" rus"',
     'negative: seamless без MODEL_FILE → многоточие в кавычках, язык rus'),
    ('exec_seamless_tgt_trimmed',
     'F({ "te-RUNNER": { value: "seamless" }, "te-MODEL_FILE": { value: "m" }, "te-SEAMLESS_TGT_LANG": { value: " eng " } });',
     'le._buildCommandExecPreview("te-").split("\\n")[2]',
     '"exec bash $HOME/run_seamless.sh \\"$PORT\\" \\"${LLAMA_MODELS_DIR:-$HOME/llama.cpp/models}\\"/m eng"',
     'defect-history: 395664a: seamless сохраняет свой язык — SEAMLESS_TGT_LANG обрезается и подставляется'),
    ('exec_seamless_tgt_ws_default',
     'F({ "te-RUNNER": { value: "seamless" }, "te-MODEL_FILE": { value: "m" }, "te-SEAMLESS_TGT_LANG": { value: "   " } });',
     'le._buildCommandExecPreview("te-").split("\\n")[2]',
     '"exec bash $HOME/run_seamless.sh \\"$PORT\\" \\"${LLAMA_MODELS_DIR:-$HOME/llama.cpp/models}\\"/m rus"',
     'negative: seamless: пробельный SEAMLESS_TGT_LANG → rus (в отличие от translate тут trim после ||)'),
    ('exec_seamless_tr',
     'F({ "tr-RUNNER": { value: "seamless" }, "tr-MODEL_FILE": { value: "m4t" }, "tr-SEAMLESS_TGT_LANG": { value: "deu" } });',
     'le._buildCommandExecPreview("tr-")',
     '"export PORT={{PORT}}\\n# first start provisions ~/seamless-venv (torch + transformers)\\nexec bash $HOME/run_seamless.sh \\"$PORT\\" \\"${LLAMA_MODELS_DIR:-$HOME/llama.cpp/models}\\"/m4t deu"',
     'positive: ветка seamless для префикса tr-'),
    ('exec_custom_full',
     'F({ "te-CELL_KIND": { value: "command" }, "te-COMMAND": { value: " python serve.py --port $PORT " }, "te-ENV": { value: "A=1\\nB=two" }, "te-WORKDIR": { value: " /srv/app " } });',
     'le._buildCommandExecPreview("te-")',
     '"export PORT={{PORT}}\\nexport A=\\"1\\"\\nexport B=\\"two\\"\\ncd /srv/app\\nexec python serve.py --port $PORT"',
     'defect-history: 2062ee8/ed5d4d3: custom показывает то, что запишет Apply — export PORT, export ENV, cd WORKDIR, exec COMMAND'),
    ('exec_custom_runner_explicit',
     'F({ "te-RUNNER": { value: "custom" }, "te-COMMAND": { value: "python x.py" } });',
     'le._buildCommandExecPreview("te-")',
     '"export PORT={{PORT}}\\nexec python x.py"',
     'positive: RUNNER=custom явно → та же custom-ветка'),
    ('exec_custom_exec_stripped_once',
     'F({ "te-CELL_KIND": { value: "command" }, "te-COMMAND": { value: "exec exec python x.py" } });',
     'le._buildCommandExecPreview("te-").split("\\n")[1]',
     '"exec exec python x.py"',
     'defect-history: ed5d4d3: ведущий «exec » снимается ровно один раз (двойной exec остаётся одним лишним)'),
    ('exec_custom_exec_leading_ws',
     'F({ "te-CELL_KIND": { value: "command" }, "te-COMMAND": { value: "   exec    python x.py" } });',
     'le._buildCommandExecPreview("te-").split("\\n")[1]',
     '"exec python x.py"',
     'positive: COMMAND обрезается, «exec» с любым числом пробелов после снимается'),
    ('exec_custom_exec_prefix_word_kept',
     'F({ "te-CELL_KIND": { value: "command" }, "te-COMMAND": { value: "executor x.py" } });',
     'le._buildCommandExecPreview("te-").split("\\n")[1]',
     '"exec executor x.py"',
     'negative: слово «executor» не считается за exec — остаётся целиком'),
    ('exec_custom_only_exec_word',
     'F({ "te-CELL_KIND": { value: "command" }, "te-COMMAND": { value: "exec" } });',
     'le._buildCommandExecPreview("te-").split("\\n")[1]',
     '"exec …"',
     'positive: COMMAND=«exec» — это не команда: срез берёт и голое слово, а не только «exec »'),
    ('exec_custom_empty_command',
     'F({ "te-CELL_KIND": { value: "command" }, "te-COMMAND": { value: "   " } });',
     'le._buildCommandExecPreview("te-")',
     '"export PORT={{PORT}}\\nexec …"',
     'defect-history: ed5d4d3: пустой COMMAND → «exec …»'),
    ('exec_custom_env_comma_split',
     'F({ "te-CELL_KIND": { value: "command" }, "te-ENV": { value: "A=1, B=2,C=3" } });',
     'le._buildCommandExecPreview("te-")',
     '"export PORT={{PORT}}\\nexport A=\\"1\\"\\nexport B=\\"2\\"\\nexport C=\\"3\\"\\nexec …"',
     'defect-history: ed5d4d3: ENV делится и по запятой, элементы обрезаются'),
    ('exec_custom_env_comment_skipped',
     'F({ "te-CELL_KIND": { value: "command" }, "te-ENV": { value: "# comment=1\\nA=1" } });',
     'le._buildCommandExecPreview("te-")',
     '"export PORT={{PORT}}\\nexport A=\\"1\\"\\nexec …"',
     'defect-history: ed5d4d3: строка-комментарий ENV (даже с «=») пропускается'),
    ('exec_custom_env_no_eq_skipped',
     'F({ "te-CELL_KIND": { value: "command" }, "te-ENV": { value: "FOO\\n\\n  \\nA=1" } });',
     'le._buildCommandExecPreview("te-")',
     '"export PORT={{PORT}}\\nexport A=\\"1\\"\\nexec …"',
     'defect-history: ed5d4d3: строки без «=» и пустые строки ENV пропускаются'),
    ('exec_custom_env_bad_keys_skipped',
     'F({ "te-CELL_KIND": { value: "command" }, "te-ENV": { value: "9X=1\\nB C=2\\nA-B=3\\n=4\\nA=1" } });',
     'le._buildCommandExecPreview("te-")',
     '"export PORT={{PORT}}\\nexport A=\\"1\\"\\nexec …"',
     'defect-history: ed5d4d3: невалидные ключи ENV (9X, «B C», A-B, пустой) пропускаются'),
    ('exec_custom_env_key_trailing_space_kept',
     'F({ "te-CELL_KIND": { value: "command" }, "te-ENV": { value: "B =2" } });',
     'le._buildCommandExecPreview("te-")',
     '"export PORT={{PORT}}\\nexport B=\\"2\\"\\nexec …"',
     'as-is: ключ «B » с пробелом перед «=» НЕ пропускается — обрезается до B (вопреки ожиданию из истории дефекта)'),
    ('exec_custom_env_value_trim_quote',
     'F({ "te-CELL_KIND": { value: "command" }, "te-ENV": { value: "A=  hello world  \\nB=x=y=z\\nC=\\"quoted\\"\\nD=" } });',
     'le._buildCommandExecPreview("te-")',
     '"export PORT={{PORT}}\\nexport A=\\"hello world\\"\\nexport B=\\"x=y=z\\"\\nexport C=\\"\\\\\\"quoted\\\\\\"\\"\\nexport D=\\"\\"\\nexec …"',
     'значения ENV обрезаются и берутся в кавычки; кавычка внутри экранируется РОВНО как в command_cell_env_exports (launch.py); split по первому «=»; пустое значение → ""'),
    ('exec_custom_workdir_absent',
     'F({ "te-CELL_KIND": { value: "command" }, "te-COMMAND": { value: "x" }, "te-WORKDIR": { value: "  " } });',
     'le._buildCommandExecPreview("te-")',
     '"export PORT={{PORT}}\\nexec x"',
     'negative: пробельный WORKDIR → строки cd нет'),
    ('exec_default_llama_server_falls_to_custom',
     'F({});',
     'le._buildCommandExecPreview("te-")',
     '"export PORT={{PORT}}\\n# llama-server: the controller renders this command, not this preview"',
     'positive: llama-server не выдаёт себя за custom — сказано, что команду рисует контроллер, а не «exec …»'),
    ('exec_unknown_runner_falls_to_custom',
     'F({ "te-RUNNER": { value: "sherpa" }, "te-COMMAND": { value: "run.sh" } });',
     'le._buildCommandExecPreview("te-")',
     '"export PORT={{PORT}}\\n# unknown runner \\"sherpa\\" — this caravan does not know how it starts"',
     'positive: неизвестный runner НАЗВАН неизвестным, а не молча отрисован как custom (как UnknownRunner на сервере)'),
    ('exec_custom_tr',
     'F({ "tr-CELL_KIND": { value: "command" }, "tr-COMMAND": { value: "exec bash go.sh" }, "tr-ENV": { value: "X=1" }, "tr-WORKDIR": { value: "/w" } });',
     'le._buildCommandExecPreview("tr-")',
     '"export PORT={{PORT}}\\nexport X=\\"1\\"\\ncd /w\\nexec bash go.sh"',
     'positive: custom-ветка для префикса tr-: exec снят и добавлен один раз'),
    ('exec_custom_prefix_isolation',
     'F({ "tr-CELL_KIND": { value: "command" }, "tr-COMMAND": { value: "bash go.sh" } });',
     'le._buildCommandExecPreview("te-")',
     '"export PORT={{PORT}}\\n# llama-server: the controller renders this command, not this preview"',
     'negative: поля tr-COMMAND/tr-PORT не видны превью te- — своя ветка te-, ни следа чужой команды'),
    ('exec_port_tr_not_from_the_cells_id',
     'try { rc.openLlamaRemoteEdit("h1", "gpu0", [], "c22031"); } catch (e) {} F({ "tr-RUNNER": { value: "vllm" } });',
     '(() => { const r = le._buildCommandExecPreview("tr-").split("\\n")[0]; try { rc.openLlamaRemoteEdit("h1", "gpu0", [], ""); } catch (e) {} return r; })()',
     '"export PORT={{PORT}}"',
     'negative: ячейка «c22031» (сделана до 2026-11-07) носит старый порт в имени, но превью не берёт порт ни из id, ни из открытой ячейки — его даст скаут при старте; выражение само закрывает ячейку после чтения'),
    ('er_kind_command_ws_llama',
     'F({ "te-CELL_KIND": { value: " command " } });',
     'le.effectiveRunnerId("te-")',
     '"custom"',
     'positive: CELL_KIND тримится — " command " даёт custom, как и на сервере'),
    ('er_kind_command_case_llama',
     'F({ "te-CELL_KIND": { value: "Command" } });',
     'le.effectiveRunnerId("te-")',
     '"custom"',
     'positive: CELL_KIND не зависит от регистра — «Command» даёт custom, как и на сервере'),
    ('er_kind_command_exact_custom',
     'F({ "te-CELL_KIND": { value: "command" } });',
     'le.effectiveRunnerId("te-")',
     '"custom"',
     'positive: точное "command" в CELL_KIND даёт custom (контроль к двум as-is выше)'),
    ('vllm_model_trailing_slash_no_served',
     'F({ "te-VLLM_MODEL": { value: "Qwen/" } });',
     'le.buildVllmCommandPreview("te-")',
     '"$HOME/vllm-venv/bin/vllm serve Qwen/ --host 0.0.0.0 --port \\"$PORT\\""',
     'as-is: как есть: модель со слэшем на конце теряет --served-model-name целиком (split(\'/\').pop() = "")'),
    ('vllm_model_trailing_slash_alias_rescues',
     'F({ "te-VLLM_MODEL": { value: "Qwen/" }, "te-ALIAS": { value: "q" } });',
     'le.buildVllmCommandPreview("te-")',
     '"$HOME/vllm-venv/bin/vllm serve Qwen/ --host 0.0.0.0 --port \\"$PORT\\" --served-model-name q"',
     'negative: ALIAS возвращает --served-model-name даже при модели со слэшем на конце'),
    ('vllm_tp_string_compare_01',
     'F({ "te-VLLM_MODEL": { value: "m" }, "te-TENSOR_PARALLEL": { value: "01" } });',
     'le.buildVllmCommandPreview("te-")',
     '"$HOME/vllm-venv/bin/vllm serve m --host 0.0.0.0 --port \\"$PORT\\" --served-model-name m --tensor-parallel-size 01"',
     'as-is: как есть: TENSOR_PARALLEL сравнивается как строка — "01" не равно "1" и печатается'),
    ('vllm_tp_ws_one_omitted',
     'F({ "te-VLLM_MODEL": { value: "m" }, "te-TENSOR_PARALLEL": { value: " 1 " } });',
     'le.buildVllmCommandPreview("te-")',
     '"$HOME/vllm-venv/bin/vllm serve m --host 0.0.0.0 --port \\"$PORT\\" --served-model-name m"',
     'boundary: граница: " 1 " тримится до "1" и --tensor-parallel-size опускается'),
    ('vllm_trust_remote_code_flag',
     'F({});',
     '[{ checked: true }, { checked: false }, undefined].map((box) => { F({ "te-VLLM_MODEL": { value: "m" }, ...(box ? { "te-TRUST_REMOTE_CODE": box } : {}) }); return le.buildVllmCommandPreview("te-"); })',
     '["$HOME/vllm-venv/bin/vllm serve m --host 0.0.0.0 --port \\"$PORT\\" --served-model-name m --trust-remote-code","$HOME/vllm-venv/bin/vllm serve m --host 0.0.0.0 --port \\"$PORT\\" --served-model-name m","$HOME/vllm-venv/bin/vllm serve m --host 0.0.0.0 --port \\"$PORT\\" --served-model-name m"]',
     'positive: отмеченный TRUST_REMOTE_CODE печатает --trust-remote-code в самом конце, как у сервера; negative: неотмеченный и отсутствующий — без флага'),
    # The three flags a model's recipe asks for (Nemotron 3 Nano Omni), in the order VllmRunner.command writes them: the
    # preview is the server's line, and contract/runner_lines.json holds the same strings for the program.
    ('vllm_recipe_flags_in_the_servers_order',
     'F({ "te-VLLM_MODEL": { value: "m" }, "te-MAX_NUM_SEQS": { value: " 8 " }, "te-KV_CACHE_DTYPE": { value: " FP8 " },'
     ' "te-REASONING_PARSER": { value: " nano_v3 " }, "te-TENSOR_PARALLEL": { value: "2" }, "te-TRUST_REMOTE_CODE": { checked: true } });',
     'le.buildVllmCommandPreview("te-")',
     '"$HOME/vllm-venv/bin/vllm serve m --host 0.0.0.0 --port \\"$PORT\\" --served-model-name m --tensor-parallel-size 2 --max-num-seqs 8 --kv-cache-dtype fp8'
     ' --reasoning-parser nano_v3 --trust-remote-code"',
     'positive: три флага рецепта — после --tensor-parallel-size и перед --trust-remote-code (он остаётся последним); значения обрезаны, тип KV — строчными, как у сервера'),
    ('vllm_offload_flag',
     'F({});',
     '[{ "te-CPU_OFFLOAD_GB": { value: " 12 " } }, { "te-CPU_OFFLOAD_GB": { value: "7.5" } }, { "te-CPU_OFFLOAD_GB": { value: "0" } }, { "te-CPU_OFFLOAD_GB": { value: "" } },'
     ' { "te-REASONING_PARSER": { value: "qwen3" }, "te-CPU_OFFLOAD_GB": { value: "12" }, "te-TRUST_REMOTE_CODE": { checked: true } }]'
     '.map((fields) => { F({ "te-VLLM_MODEL": { value: "m" }, ...fields }); return le.buildVllmCommandPreview("te-").split(" --served-model-name m")[1]; })',
     '[" --cpu-offload-gb 12"," --cpu-offload-gb 7.5","",""," --reasoning-parser qwen3 --cpu-offload-gb 12 --trust-remote-code"]',
     'positive: веса в RAM — флаг в том порядке, что пишет сервер (contract/runner_lines.json); negative: 0 и пусто — флага нет'),
    ('vllm_recipe_flags_alone_and_empty',
     'F({});',
     '[{ "te-MAX_NUM_SEQS": { value: "16" } }, { "te-KV_CACHE_DTYPE": { value: "fp8_e5m2" } }, { "te-REASONING_PARSER": { value: "deepseek_r1" } },'
     ' { "te-MAX_NUM_SEQS": { value: "  " } }, { "te-KV_CACHE_DTYPE": { value: "auto" } }, { "te-KV_CACHE_DTYPE": { value: " AUTO " } }, { "te-REASONING_PARSER": { value: "" } }]'
     '.map((fields) => { F({ "te-VLLM_MODEL": { value: "m" }, ...fields }); return le.buildVllmCommandPreview("te-").split(" --served-model-name m")[1]; })',
     '[" --max-num-seqs 16"," --kv-cache-dtype fp8_e5m2"," --reasoning-parser deepseek_r1","","","",""]',
     'positive: каждое поле само по себе даёт свой флаг и только его; negative: пустое (и из одних пробелов) поле, auto и AUTO у типа KV — флага нет, как у сервера'),
    ('vllm_tp_ws_two_kept',
     'F({ "te-VLLM_MODEL": { value: "m" }, "te-TENSOR_PARALLEL": { value: " 2 " } });',
     'le.buildVllmCommandPreview("te-")',
     '"$HOME/vllm-venv/bin/vllm serve m --host 0.0.0.0 --port \\"$PORT\\" --served-model-name m --tensor-parallel-size 2"',
     'positive: " 2 " тримится и печатается как --tensor-parallel-size 2'),
    ('vllm_maxlen_zero_kept',
     'F({ "te-VLLM_MODEL": { value: "m" }, "te-MAX_MODEL_LEN": { value: "0" } });',
     'le.buildVllmCommandPreview("te-")',
     '"$HOME/vllm-venv/bin/vllm serve m --host 0.0.0.0 --port \\"$PORT\\" --served-model-name m --max-model-len 0"',
     'boundary: граница: MAX_MODEL_LEN="0" — истинная строка, флаг печатается с нулём'),
    ('vllm_gpu_zero_kept',
     'F({ "te-VLLM_MODEL": { value: "m" }, "te-GPU_MEMORY_UTILIZATION": { value: "0" } });',
     'le.buildVllmCommandPreview("te-")',
     '"$HOME/vllm-venv/bin/vllm serve m --host 0.0.0.0 --port \\"$PORT\\" --served-model-name m --gpu-memory-utilization 0"',
     'boundary: граница: GPU_MEMORY_UTILIZATION="0" печатается как --gpu-memory-utilization 0'),
    ('vllm_maxlen_gpu_empty_omitted',
     'F({ "te-VLLM_MODEL": { value: "m" }, "te-MAX_MODEL_LEN": { value: "" }, "te-GPU_MEMORY_UTILIZATION": { value: "" } });',
     'le.buildVllmCommandPreview("te-")',
     '"$HOME/vllm-venv/bin/vllm serve m --host 0.0.0.0 --port \\"$PORT\\" --served-model-name m"',
     'negative: пустые MAX_MODEL_LEN и GPU_MEMORY_UTILIZATION — оба флага опущены (пара к нулевым границам)'),
    ('exec_whisper_tr_comment_line',
     'F({ "tr-RUNNER": { value: "whisper" } });',
     'le._buildCommandExecPreview("tr-").split("\\n")[1]',
     '"# model downloads on first start into <models root>/whisper"',
     'positive: tr- whisper: строка [1] — комментарий про загрузку модели в <models root>/whisper'),
    ('exec_whisper_tr_exec_line',
     'F({ "tr-RUNNER": { value: "whisper" } });',
     'le._buildCommandExecPreview("tr-").split("\\n")[2]',
     '"exec env HUGGINGFACE_HUB_CACHE=\\"${LLAMA_MODELS_DIR:-$HOME/llama-model-cache}/whisper\\" bash $HOME/run_whisper.sh \\"$PORT\\" large-v3"',
     'positive: tr- whisper: строка [2] — exec с HUGGINGFACE_HUB_CACHE и размером large-v3 по умолчанию'),
    ('exec_whisper_tr_port_placeholder',
     'F({ "tr-RUNNER": { value: "whisper" } });',
     'le._buildCommandExecPreview("tr-").split("\\n")[0]',
     '"export PORT={{PORT}}"',
     'tr- whisper без открытой ячейки — та же заглушка скаута'),
    ('exec_whisper_te_not_tr',
     'F({ "te-RUNNER": { value: "whisper" } });',
     'le._buildCommandExecPreview("tr-")',
     '"export PORT={{PORT}}\\n# llama-server: the controller renders this command, not this preview"',
     'negative: whisper-поля с префиксом te- не видны tr-превью — llama-ветка с литералом PORT'),
    ('exec_translate_tr_comment_line',
     'F({ "tr-RUNNER": { value: "translate" } });',
     'le._buildCommandExecPreview("tr-").split("\\n")[1]',
     '"# model downloads on first start into <models root>/translate"',
     'positive: tr- translate: строка [1] — комментарий про <models root>/translate'),
    ('exec_whisper_lines_count',
     'F({ "te-RUNNER": { value: "whisper" } });',
     'le._buildCommandExecPreview("te-").split("\\n").length',
     '3',
     'positive: whisper-превью — ровно три строки (export, комментарий, exec)'),
    ('exec_seamless_model_ws_ellipsis',
     'F({ "te-RUNNER": { value: "seamless" }, "te-MODEL_FILE": { value: "  " } });',
     'le._buildCommandExecPreview("te-")',
     '"export PORT={{PORT}}\\n# first start provisions ~/seamless-venv (torch + transformers)\\nexec bash $HOME/run_seamless.sh \\"$PORT\\" \\"…\\" rus"',
     'boundary: seamless: MODEL_FILE из одних пробелов тримится в пусто → "…" и tgt rus'),
    ('exec_transcribe_model_ws_ellipsis',
     'F({ "te-RUNNER": { value: "transcribe" }, "te-MODEL_FILE": { value: "  " } });',
     'le._buildCommandExecPreview("te-")',
     '"export PORT={{PORT}}\\n# the engine and its venv come from scripts/install-transcribe.sh\\nexec bash $HOME/run_transcribe.sh \\"$PORT\\" \\"…\\""',
     'boundary: transcribe: MODEL_FILE из одних пробелов → "…"'),
    ('exec_seamless_model_ws_trimmed',
     'F({ "te-RUNNER": { value: "seamless" }, "te-MODEL_FILE": { value: " m4t " } });',
     'le._buildCommandExecPreview("te-").split("\\n")[2]',
     '"exec bash $HOME/run_seamless.sh \\"$PORT\\" \\"${LLAMA_MODELS_DIR:-$HOME/llama.cpp/models}\\"/m4t rus"',
     'negative: seamless: пробелы вокруг непустого MODEL_FILE тримятся, относительный путь под models-dir'),
    ('exec_transcribe_tilde_relative',
     'F({ "te-RUNNER": { value: "transcribe" }, "te-MODEL_FILE": { value: "~/m/x.gguf" } });',
     'le._buildCommandExecPreview("te-").split("\\n")[2]',
     '"exec bash $HOME/run_transcribe.sh \\"$PORT\\" \\"${LLAMA_MODELS_DIR:-$HOME/llama.cpp/models}\\"/~/m/x.gguf"',
     'as-is: как есть: transcribe считает ~/… относительным путём (исключены только / и $) — получается models-dir/~/m/x.gguf'),
    ('exec_seamless_tilde_relative',
     'F({ "te-RUNNER": { value: "seamless" }, "te-MODEL_FILE": { value: "~/m4t" } });',
     'le._buildCommandExecPreview("te-").split("\\n")[2]',
     '"exec bash $HOME/run_seamless.sh \\"$PORT\\" \\"${LLAMA_MODELS_DIR:-$HOME/llama.cpp/models}\\"/~/m4t rus"',
     'as-is: как есть: seamless тот же тильда-дефект — models-dir/~/m4t'),
    ('exec_translate_src_ws_double_space',
     'F({ "te-RUNNER": { value: "translate" }, "te-TRANSLATE_SRC_LANG": { value: " " } });',
     'le._buildCommandExecPreview("te-").split("\\n")[2]',
     '"exec env HUGGINGFACE_HUB_CACHE=\\"${LLAMA_MODELS_DIR:-$HOME/llama-model-cache}/translate\\" bash $HOME/run_translate.sh \\"$PORT\\" facebook/nllb-200-distilled-600M eng_Latn rus_Cyrl"',
     'negative: пробельный SRC_LANG → дефолт eng_Latn, а не дыра посреди команды'),
    ('exec_translate_tgt_ws_trailing_space',
     'F({ "te-RUNNER": { value: "translate" }, "te-TRANSLATE_TGT_LANG": { value: " " } });',
     'le._buildCommandExecPreview("te-").split("\\n")[2]',
     '"exec env HUGGINGFACE_HUB_CACHE=\\"${LLAMA_MODELS_DIR:-$HOME/llama-model-cache}/translate\\" bash $HOME/run_translate.sh \\"$PORT\\" facebook/nllb-200-distilled-600M eng_Latn rus_Cyrl"',
     'negative: пробельный TGT_LANG → дефолт rus_Cyrl, а не висячий пробел в хвосте'),
    ('exec_translate_src_trimmed',
     'F({ "te-RUNNER": { value: "translate" }, "te-TRANSLATE_SRC_LANG": { value: " deu_Latn " } });',
     'le._buildCommandExecPreview("te-").split("\\n")[2]',
     '"exec env HUGGINGFACE_HUB_CACHE=\\"${LLAMA_MODELS_DIR:-$HOME/llama-model-cache}/translate\\" bash $HOME/run_translate.sh \\"$PORT\\" facebook/nllb-200-distilled-600M deu_Latn rus_Cyrl"',
     'negative: непустой SRC_LANG тримится и печатается одним пробелом (пара к as-is двойного пробела)'),
    ('exec_custom_env_comma_value_truncated',
     'F({ "te-CELL_KIND": { value: "command" }, "te-COMMAND": { value: "x" }, "te-ENV": { value: "LIST=a,b" } });',
     'le._buildCommandExecPreview("te-")',
     '"export PORT={{PORT}}\\nexport LIST=\\"a\\"\\nexec x"',
     'as-is: как есть: запятая в значении ENV режет его — LIST="a", хвост b без \'=\' молча выброшен (значение с запятой невыразимо)'),
    ('exec_custom_env_comma_value_both_eq',
     'F({ "te-CELL_KIND": { value: "command" }, "te-COMMAND": { value: "x" }, "te-ENV": { value: "LIST=a,B=b" } });',
     'le._buildCommandExecPreview("te-")',
     '"export PORT={{PORT}}\\nexport LIST=\\"a\\"\\nexport B=\\"b\\"\\nexec x"',
     'negative: запятая как разделитель двух пар — обе экспортируются (контроль к усечению)'),
    ('exec_custom_workdir_spaces_unquoted',
     'F({ "te-CELL_KIND": { value: "command" }, "te-COMMAND": { value: "x" }, "te-WORKDIR": { value: "/srv/my app" } });',
     'le._buildCommandExecPreview("te-")',
     '"export PORT={{PORT}}\\ncd /srv/my app\\nexec x"',
     'as-is: как есть: WORKDIR с пробелом печатается без кавычек — cd /srv/my app'),
    ('exec_custom_workdir_trimmed',
     'F({ "te-CELL_KIND": { value: "command" }, "te-COMMAND": { value: "x" }, "te-WORKDIR": { value: "  /srv/app  " } });',
     'le._buildCommandExecPreview("te-")',
     '"export PORT={{PORT}}\\ncd /srv/app\\nexec x"',
     'positive: WORKDIR тримится по краям перед cd'),
    ('exec_custom_exec_uppercase_kept',
     'F({ "te-CELL_KIND": { value: "command" }, "te-COMMAND": { value: "EXEC python x.py" } });',
     'le._buildCommandExecPreview("te-").split("\\n")[1]',
     '"exec EXEC python x.py"',
     'negative: срез ведущего exec регистрозависим — EXEC не срезается и дублируется'),
    ('exec_custom_exec_tab_stripped',
     'F({ "te-CELL_KIND": { value: "command" }, "te-COMMAND": { value: "exec\\tpython x.py" } });',
     'le._buildCommandExecPreview("te-").split("\\n")[1]',
     '"exec python x.py"',
     'positive: exec с табом после слова срезается (\\s+ покрывает таб)'),
    ('exec_custom_env_lower_underscore_keys',
     'F({ "te-CELL_KIND": { value: "command" }, "te-COMMAND": { value: "x" }, "te-ENV": { value: "_x1=a\\nab_C9=b" } });',
     'le._buildCommandExecPreview("te-")',
     '"export PORT={{PORT}}\\nexport _x1=\\"a\\"\\nexport ab_C9=\\"b\\"\\nexec x"',
     'positive: ключи с ведущим подчёркиванием и строчными буквами валидны и экспортируются'),
    ('exec_custom_env_key_dash_skipped',
     'F({ "te-CELL_KIND": { value: "command" }, "te-COMMAND": { value: "x" }, "te-ENV": { value: "a-b=1\\nA=1" } });',
     'le._buildCommandExecPreview("te-")',
     '"export PORT={{PORT}}\\nexport A=\\"1\\"\\nexec x"',
     'negative: ключ с дефисом отбрасывается, соседняя валидная пара остаётся'),
    ('exec_custom_env_comment_leading_ws_skipped',
     'F({ "te-CELL_KIND": { value: "command" }, "te-COMMAND": { value: "x" }, "te-ENV": { value: "   # x=1\\nA=1" } });',
     'le._buildCommandExecPreview("te-")',
     '"export PORT={{PORT}}\\nexport A=\\"1\\"\\nexec x"',
     "positive: комментарий с ведущими пробелами пропускается (trim до startsWith('#'))"),
    ('exec_custom_env_hash_inside_kept',
     'F({ "te-CELL_KIND": { value: "command" }, "te-COMMAND": { value: "x" }, "te-ENV": { value: "A=1 # note" } });',
     'le._buildCommandExecPreview("te-")',
     '"export PORT={{PORT}}\\nexport A=\\"1 # note\\"\\nexec x"',
     'negative: решётка не в начале строки — не комментарий, попадает в значение целиком'),
    ('exec_runner_case_sensitive_whisper',
     'F({ "te-RUNNER": { value: "Whisper" } });',
     'le._buildCommandExecPreview("te-")',
     '"export PORT={{PORT}}\\n# model downloads on first start into <models root>/whisper\\nexec env HUGGINGFACE_HUB_CACHE=\\"${LLAMA_MODELS_DIR:-$HOME/llama-model-cache}/whisper\\" bash $HOME/run_whisper.sh \\"$PORT\\" large-v3"',
     'positive: RUNNER не зависит от регистра — «Whisper» идёт в свою ветку, как и на сервере (runner_id приводит к нижнему)'),
    ('exec_runner_lowercase_whisper',
     'F({ "te-RUNNER": { value: "whisper" } });',
     'le._buildCommandExecPreview("te-")',
     '"export PORT={{PORT}}\\n# model downloads on first start into <models root>/whisper\\nexec env HUGGINGFACE_HUB_CACHE=\\"${LLAMA_MODELS_DIR:-$HOME/llama-model-cache}/whisper\\" bash $HOME/run_whisper.sh \\"$PORT\\" large-v3"',
     'negative: строчный "whisper" попадает в свою ветку (контроль к регистрозависимости)'),
    ('exec_runner_case_sensitive_vllm',
     'F({ "te-RUNNER": { value: "VLLM" } });',
     'le._buildCommandExecPreview("te-")',
     '"export PORT={{PORT}}\\n# first start on a host provisions ~/vllm-venv (several minutes)\\nexec $HOME/vllm-venv/bin/vllm serve … --host 0.0.0.0 --port \\"$PORT\\""',
     'positive: «VLLM» тоже узнаётся — тот же нижний регистр, что у сервера'),
    # ── artifacts_devices ──
    ('ak_moonshine',
     '',
     'le.artifactKind("moonshine/base-en")',
     '"moonshine-lang"',
     'positive: artifactKind: путь moonshine/… даёт moonshine-lang'),
    ('ak_whisper',
     '',
     'le.artifactKind("whisper/models--Systran--faster-whisper-large-v3")',
     '"whisper-size"',
     'positive: artifactKind: whisper/models--Systran--faster-whisper-… даёт whisper-size'),
    ('ak_whisper_other_repo',
     '',
     'le.artifactKind("whisper/models--openai--whisper-large")',
     '"safetensors"',
     'as-is: artifactKind: whisper-репо не от Systran проваливается в safetensors (префикс строгий, как есть)'),
    ('ak_nllb',
     '',
     'le.artifactKind("translate/models--facebook--nllb-200-distilled-600M")',
     '"nllb-repo"',
     'positive: artifactKind: translate/models--… даёт nllb-repo'),
    ('ak_seamless_found',
     'st.setState({ ...st.state, runners: [{ id: "seamless", artifacts: ["seamless-st"], stArchs: ["seamless_m4t", "seamless_m4t_v2"] }] });'
     ' st.state.artifacts = [{ path: "st/seamless-m4t-v2", arch: "seamless_m4t_v2" }];',
     'le.artifactKind("st/seamless-m4t-v2")',
     '"seamless-st"',
     'positive: artifactKind: не-gguf путь из state.artifacts с arch seamless_m4t* даёт seamless-st'),
    ('ak_st_found_other_arch',
     'st.state.artifacts = [{ path: "st/qwen", arch: "qwen2" }];',
     'le.artifactKind("st/qwen")',
     '"safetensors"',
     'negative: artifactKind: найденный не-gguf артефакт с другой arch даёт safetensors'),
    ('ak_st_not_found',
     '',
     'le.artifactKind("st/whatever-dir")',
     '"safetensors"',
     'positive: artifactKind: не-gguf путь, которого нет в state.artifacts, всё равно safetensors'),
    ('ak_st_artifacts_undefined',
     'st.state.artifacts = undefined;',
     'le.artifactKind("st/whatever-dir")',
     '"safetensors"',
     'boundary: artifactKind: state.artifacts=undefined не роняет, не-gguf → safetensors'),
    ('ak_gguf_asr',
     'st.state.models = [{ path: "m/gigaam.gguf", ggufMeta: { sttVariant: "gigaam" } }];',
     'le.artifactKind("m/gigaam.gguf")',
     '"asr-gguf"',
     'positive: artifactKind: .gguf из state.models с ggufMeta.sttVariant даёт asr-gguf'),
    ('ak_gguf_llm',
     'st.state.models = [{ path: "m/qwen.gguf", ggufMeta: {} }];',
     'le.artifactKind("m/qwen.gguf")',
     '"llm-gguf"',
     'negative: artifactKind: .gguf из state.models без sttVariant даёт llm-gguf'),
    ('ak_gguf_llm_no_meta',
     'st.state.models = [{ path: "m/qwen.gguf" }];',
     'le.artifactKind("m/qwen.gguf")',
     '"llm-gguf"',
     'boundary: artifactKind: .gguf без ggufMeta вовсе — тоже llm-gguf'),
    ('ak_gguf_unknown',
     '',
     'le.artifactKind("m/unknown.gguf")',
     '""',
     'as-is: artifactKind: .gguf, которого нет в state.models, даёт "" (неизвестное никогда не блокирует, как есть)'),
    ('ak_gguf_models_undefined',
     'st.state.models = undefined;',
     'le.artifactKind("m/unknown.gguf")',
     '""',
     'boundary: artifactKind: state.models=undefined не роняет, .gguf → ""'),
    ('ak_empty',
     '',
     'le.artifactKind("")',
     '""',
     'negative: artifactKind: пустая строка даёт ""'),
    ('ak_whitespace',
     '',
     'le.artifactKind("   ")',
     '""',
     'boundary: artifactKind: одни пробелы даёт "" (trim)'),
    ('ak_undefined',
     '',
     'le.artifactKind(undefined)',
     '""',
     'boundary: artifactKind: undefined даёт ""'),
    ('ak_upper_GGUF_found',
     'st.state.models = [{ path: "m/X.GGUF", ggufMeta: {} }];',
     'le.artifactKind("m/X.GGUF")',
     '"llm-gguf"',
     'boundary: artifactKind: суффикс .GGUF в верхнем регистре считается gguf, поиск по точному пути'),
    ('ak_trimmed_lookup',
     'st.state.models = [{ path: "m/qwen.gguf", ggufMeta: {} }];',
     'le.artifactKind("  m/qwen.gguf  ")',
     '"llm-gguf"',
     'boundary: artifactKind: пробелы вокруг пути срезаются до поиска в state.models'),
    ('ak_precedence_moonshine_gguf',
     '',
     'le.artifactKind("moonshine/x.gguf")',
     '"moonshine-lang"',
     'boundary: artifactKind: префикс moonshine/ побеждает суффикс .gguf'),
    ('cap_rtx5090',
     '',
     'le.gpuComputeCap("NVIDIA GeForce RTX 5090")',
     '12',
     'positive: gpuComputeCap: RTX 5090 → 12 (Blackwell consumer)'),
    ('cap_rtx50_substring_rtx5000',
     '',
     'le.gpuComputeCap("NVIDIA RTX 5000 Ada")',
     '12',
     'as-is: gpuComputeCap: RTX 5000 Ada попадает под /RTX 50/ и даёт 12 вместо 8.9 (как есть)'),
    ('cap_b200',
     '',
     'le.gpuComputeCap("NVIDIA B200")',
     '10',
     'positive: gpuComputeCap: B200 → 10 (Blackwell datacenter)'),
    ('cap_gb10',
     '',
     'le.gpuComputeCap("NVIDIA GB10")',
     '10',
     'positive: gpuComputeCap: GB10 → 10'),
    ('cap_gb100',
     '',
     'le.gpuComputeCap("NVIDIA GB100")',
     '10',
     'boundary: gpuComputeCap: GB100 → 10 (\\bGB[12]0 без правой границы ловит и GB100)'),
    ('cap_gb300',
     '',
     'le.gpuComputeCap("NVIDIA GB300")',
     'null',
     'as-is: gpuComputeCap: GB300 (Blackwell Ultra) не в карте → null (как есть)'),
    ('cap_h100',
     '',
     'le.gpuComputeCap("NVIDIA H100 80GB HBM3")',
     '9',
     'positive: gpuComputeCap: H100 → 9 (Hopper)'),
    ('cap_gh200',
     '',
     'le.gpuComputeCap("GH200")',
     '9',
     'positive: gpuComputeCap: GH200 → 9'),
    ('cap_rtx4090',
     '',
     'le.gpuComputeCap("NVIDIA GeForce RTX 4090")',
     '8.9',
     'positive: gpuComputeCap: RTX 4090 → 8.9 (Ada)'),
    ('cap_l4',
     '',
     'le.gpuComputeCap("NVIDIA L4")',
     '8.9',
     'positive: gpuComputeCap: L4 → 8.9'),
    ('cap_l40s',
     '',
     'le.gpuComputeCap("NVIDIA L40S")',
     '8.9',
     'boundary: gpuComputeCap: L40S → 8.9 (\\bL40 без правой границы)'),
    ('cap_rtx3050',
     '',
     'le.gpuComputeCap("NVIDIA GeForce RTX 3050")',
     '8.6',
     'positive: gpuComputeCap: RTX 3050 → 8.6 (Ampere)'),
    ('cap_a2000',
     '',
     'le.gpuComputeCap("NVIDIA RTX A2000")',
     'null',
     'as-is: gpuComputeCap: RTX A2000 (Ampere) не матчится ни \\bA2\\b, ни A[45]000 → null (как есть)'),
    ('cap_a2',
     '',
     'le.gpuComputeCap("NVIDIA A2")',
     '8.6',
     'boundary: gpuComputeCap: A2 → 8.6 (граница слова держит)'),
    ('cap_a16',
     '',
     'le.gpuComputeCap("NVIDIA A16")',
     '8.6',
     'positive: gpuComputeCap: A16 → 8.6'),
    ('cap_a1600',
     '',
     'le.gpuComputeCap("NVIDIA A1600")',
     'null',
     'negative: gpuComputeCap: A1600 не проходит границу \\bA16\\b → null'),
    ('cap_a5000',
     '',
     'le.gpuComputeCap("NVIDIA RTX A5000")',
     '8.6',
     'positive: gpuComputeCap: RTX A5000 → 8.6'),
    ('cap_a6000',
     '',
     'le.gpuComputeCap("NVIDIA RTX A6000")',
     '8.6',
     'positive: gpuComputeCap: RTX A6000 → 8.6'),
    ('cap_a100',
     '',
     'le.gpuComputeCap("NVIDIA A100-SXM4-80GB")',
     '8',
     'positive: gpuComputeCap: A100 → 8 (Ampere datacenter)'),
    ('cap_a30',
     '',
     'le.gpuComputeCap("NVIDIA A30")',
     '8',
     'positive: gpuComputeCap: A30 → 8'),
    ('cap_rtx2080',
     '',
     'le.gpuComputeCap("NVIDIA GeForce RTX 2080 Ti")',
     '7.5',
     'positive: gpuComputeCap: RTX 2080 Ti → 7.5 (Turing)'),
    ('cap_titan_rtx',
     '',
     'le.gpuComputeCap("TITAN RTX")',
     '7.5',
     'positive: gpuComputeCap: TITAN RTX → 7.5'),
    ('cap_t4',
     '',
     'le.gpuComputeCap("Tesla T4")',
     '7.5',
     'positive: gpuComputeCap: T4 → 7.5'),
    ('cap_t400',
     '',
     'le.gpuComputeCap("NVIDIA T400")',
     'null',
     'negative: gpuComputeCap: T400 не проходит \\bT4\\b → null'),
    ('cap_v100',
     '',
     'le.gpuComputeCap("Tesla V100-PCIE-16GB")',
     '7',
     'positive: gpuComputeCap: V100 → 7 (Volta)'),
    ('cap_gtx1080',
     '',
     'le.gpuComputeCap("NVIDIA GeForce GTX 1080")',
     'null',
     'negative: gpuComputeCap: GTX 1080 (Pascal) → null'),
    ('cap_lowercase',
     '',
     'le.gpuComputeCap("nvidia geforce rtx 3090")',
     '8.6',
     'boundary: gpuComputeCap: строчные буквы приводятся к верхнему регистру → 8.6'),
    ('cap_empty',
     '',
     'le.gpuComputeCap("")',
     'null',
     'negative: gpuComputeCap: пустая строка → null'),
    ('cap_undefined',
     '',
     'le.gpuComputeCap(undefined)',
     'null',
     'boundary: gpuComputeCap: undefined → null'),
    ('dev_cpu_wins',
     '',
     'le._envDeviceState("TTS_DEVICE=cuda\\nTTS_DEVICE=cpu", "")',
     '"cpu"',
     'positive: _envDeviceState: при cuda и cpu в ENV побеждает cpu'),
    ('dev_cpu_wins_cmd_gpu',
     '',
     'le._envDeviceState("TTS_DEVICE=cpu", "python x.py --device cuda")',
     '"cpu"',
     'positive: _envDeviceState: cpu в ENV побеждает --device cuda в команде'),
    ('dev_cvd_empty',
     '',
     'le._envDeviceState("CUDA_VISIBLE_DEVICES=", "")',
     '"cpu"',
     'positive: _envDeviceState: пустой CUDA_VISIBLE_DEVICES= → cpu'),
    ('dev_cvd_empty_dquotes',
     '',
     'le._envDeviceState(\'CUDA_VISIBLE_DEVICES=""\', "")',
     '"cpu"',
     'positive: _envDeviceState: CUDA_VISIBLE_DEVICES="" (двойные кавычки) → cpu'),
    ('dev_cvd_empty_squotes',
     '',
     'le._envDeviceState("CUDA_VISIBLE_DEVICES=\'\'", "")',
     '"cpu"',
     "positive: _envDeviceState: CUDA_VISIBLE_DEVICES='' (одинарные кавычки) → cpu"),
    ('dev_cvd_empty_mid',
     '',
     'le._envDeviceState("FOO=1\\nCUDA_VISIBLE_DEVICES=\\nBAR=2", "")',
     '"cpu"',
     'boundary: _envDeviceState: пустой CUDA_VISIBLE_DEVICES= в середине строк → cpu'),
    ('dev_cvd_zero',
     '',
     'le._envDeviceState("CUDA_VISIBLE_DEVICES=0", "")',
     '"auto"',
     'negative: _envDeviceState: CUDA_VISIBLE_DEVICES=0 не cpu → auto'),
    ('dev_cvd_in_cmd_ignored',
     '',
     'le._envDeviceState("", "CUDA_VISIBLE_DEVICES= python x.py")',
     '"auto"',
     'negative: _envDeviceState: пустой CUDA_VISIBLE_DEVICES в команде (не в ENV) не учитывается → auto'),
    ('dev_device_eq_gpu',
     '',
     'le._envDeviceState("", "python x.py --device=gpu")',
     '"gpu"',
     'positive: _envDeviceState: --device=gpu только в команде → gpu'),
    ('dev_device_space_cuda',
     '',
     'le._envDeviceState("", "python x.py --device cuda")',
     '"gpu"',
     'positive: _envDeviceState: --device cuda через пробел только в команде → gpu'),
    ('dev_device_space_cpu_cmd',
     '',
     'le._envDeviceState("", "python x.py --device cpu")',
     '"cpu"',
     'positive: _envDeviceState: --device cpu только в команде → cpu'),
    ('dev_DEVICE_cudart',
     '',
     'le._envDeviceState("DEVICE=cudart", "")',
     '"auto"',
     'negative: _envDeviceState: DEVICE=cudart не проходит границу слова → auto'),
    ('dev_MYDEVICE_cuda',
     '',
     'le._envDeviceState("MYDEVICE=cuda", "")',
     '"auto"',
     'negative: _envDeviceState: MYDEVICE=cuda не якорится на начало имени → auto'),
    ('dev_DEVICE_cuda',
     '',
     'le._envDeviceState("DEVICE=cuda", "")',
     '"gpu"',
     'positive: _envDeviceState: DEVICE=cuda в ENV → gpu'),
    ('dev_TTS_DEVICE_gpu_lower',
     '',
     'le._envDeviceState("tts_device=GPU", "")',
     '"gpu"',
     'boundary: _envDeviceState: регистр не важен, tts_device=GPU → gpu'),
    ('dev_cpu_semicolon_cmd',
     '',
     'le._envDeviceState("", "TTS_DEVICE=cpu;python x.py")',
     '"cpu"',
     'positive: _envDeviceState: TTS_DEVICE=cpu в начале команды перед ; → cpu'),
    ('dev_TTS_DEVICE_cpux',
     '',
     'le._envDeviceState("TTS_DEVICE=cpux", "")',
     '"auto"',
     'negative: _envDeviceState: TTS_DEVICE=cpux не проходит \\b после cpu → auto'),
    ('dev_auto_empty',
     '',
     'le._envDeviceState("", "")',
     '"auto"',
     'negative: _envDeviceState: пустые ENV и команда → auto'),
    ('app_cpu_strips',
     '',
     'le._applyDeviceToEnv("FOO=1\\ntts_device=cuda\\ncuda_visible_devices=0\\nBAR=2", "cpu")',
     '"FOO=1\\nBAR=2\\nTTS_DEVICE=cpu\\nCUDA_VISIBLE_DEVICES="',
     'positive: _applyDeviceToEnv cpu: старые TTS_DEVICE/CUDA_VISIBLE_DEVICES (любой регистр) выкинуты, остальное сохранено, дописаны две строки'),
    ('app_gpu_strips',
     '',
     'le._applyDeviceToEnv("FOO=1\\nTTS_DEVICE=cpu\\nCUDA_VISIBLE_DEVICES=\\nBAR=2", "gpu")',
     '"FOO=1\\nBAR=2\\nTTS_DEVICE=cuda"',
     'positive: _applyDeviceToEnv gpu: cpu-строки сняты, дописана одна TTS_DEVICE=cuda'),
    ('app_auto_strips',
     '',
     'le._applyDeviceToEnv("FOO=1\\nTTS_DEVICE=cpu\\nCUDA_VISIBLE_DEVICES=\\nBAR=2", "auto")',
     '"FOO=1\\nBAR=2"',
     'negative: _applyDeviceToEnv auto: device-строки сняты, ничего не дописано'),
    ('app_cpu_empty',
     '',
     'le._applyDeviceToEnv("", "cpu")',
     '"TTS_DEVICE=cpu\\nCUDA_VISIBLE_DEVICES="',
     'boundary: _applyDeviceToEnv: пустой ENV + cpu → ровно две строки'),
    ('app_gpu_empty',
     '',
     'le._applyDeviceToEnv("", "gpu")',
     '"TTS_DEVICE=cuda"',
     'boundary: _applyDeviceToEnv: пустой ENV + gpu → одна строка'),
    ('app_auto_empty',
     '',
     'le._applyDeviceToEnv("", "auto")',
     '""',
     'negative: _applyDeviceToEnv: пустой ENV + auto → пустая строка'),
    ('app_undefined_cpu',
     '',
     'le._applyDeviceToEnv(undefined, "cpu")',
     '"TTS_DEVICE=cpu\\nCUDA_VISIBLE_DEVICES="',
     'boundary: _applyDeviceToEnv: undefined ENV не роняет, cpu → две строки'),
    ('app_comma_split',
     '',
     'le._applyDeviceToEnv("A=1, B=2,C=3", "auto")',
     '"A=1\\nB=2\\nC=3"',
     'as-is: _applyDeviceToEnv: ввод через запятую переписывается через перевод строки (разделитель не сохраняется, как есть)'),
    ('app_blank_rows_dropped',
     '',
     'le._applyDeviceToEnv("A=1\\n\\n  \\nB=2", "auto")',
     '"A=1\\nB=2"',
     'boundary: _applyDeviceToEnv: пустые и пробельные строки выбрасываются'),
    ('app_unknown_mode',
     '',
     'le._applyDeviceToEnv("A=1", "banana")',
     '"A=1"',
     'negative: _applyDeviceToEnv: неизвестный режим ведёт себя как auto — ничего не дописывает'),
    ('app_MYTTS_DEVICE_kept',
     '',
     'le._applyDeviceToEnv("MYTTS_DEVICE=cpu", "auto")',
     '"MYTTS_DEVICE=cpu"',
     'negative: _applyDeviceToEnv: строка с префиксом перед TTS_DEVICE не снимается (якорь ^)'),
    ('rr_fallback_empty',
     '',
     'le.runnerRegistry()',
     '[{"id":"llama-server","icon":"🦙","labelKey":"runnerLlama","benefitsKey":"runnerLlamaBenefits","formats":["gguf"]},{"id":"custom","icon":"🛠️","labelKey":"runnerCustom","benefitsKey":"runnerCustomBenefits","formats":["*"]}]',
     'positive: runnerRegistry: state.runners=[] → встроенная пара llama-server/custom'),
    ('rr_fallback_undefined',
     'st.state.runners = undefined;',
     'le.runnerRegistry()',
     '[{"id":"llama-server","icon":"🦙","labelKey":"runnerLlama","benefitsKey":"runnerLlamaBenefits","formats":["gguf"]},{"id":"custom","icon":"🛠️","labelKey":"runnerCustom","benefitsKey":"runnerCustomBenefits","formats":["*"]}]',
     'boundary: runnerRegistry: state.runners=undefined → та же встроенная пара'),
    ('rr_fallback_nonarray',
     'st.state.runners = { id: "x" };',
     'le.runnerRegistry()',
     '[{"id":"llama-server","icon":"🦙","labelKey":"runnerLlama","benefitsKey":"runnerLlamaBenefits","formats":["gguf"]},{"id":"custom","icon":"🛠️","labelKey":"runnerCustom","benefitsKey":"runnerCustomBenefits","formats":["*"]}]',
     'boundary: runnerRegistry: state.runners не массив → встроенная пара'),
    ('rr_provided',
     'st.state.runners = [{ id: "moonshine", icon: "🌙", artifacts: ["moonshine-lang"] }];',
     'le.runnerRegistry()',
     '[{"id":"moonshine","icon":"🌙","artifacts":["moonshine-lang"]}]',
     'negative: runnerRegistry: непустой state.runners возвращается как есть, без встроенной пары'),
    # The VRAM a start takes whatever the model files weigh, read off the registry's fixed plan (runner.py vram_plan): the
    # form's estimate bar and the stopped cell's chip both ask here. GB, not MiB; 0 where the registry has no fixed figure.
    ('fixed_vram_gb',
     'st.setState({runners:[{id:"minicpm-omni",vramPlan:{fixedMiB:12800}},{id:"personaplex",vramPlan:{fixedMiB:20480}},'
     '{id:"strata",vramPlan:{takesFree:true,floorMiB:6144}},{id:"zero",vramPlan:{fixedMiB:0}},{id:"llama-server"}]});',
     '["minicpm-omni","personaplex","strata","zero","llama-server","unknown"].map((id) => le.runnerFixedVramGb(id))',
     '[12.5,20,0,0,0,0]',
     'positive: фиксированный план реестра — в ГБ (12800 МиБ → 12.5, 20480 → 20); negative: план «берёт свободное» (Strata), нулевая цифра, '
     'раннер без плана и неизвестный id дают 0, а не догадку'),
    ('fixed_vram_gb_fallback_registry',
     'st.state.runners = undefined;',
     'le.runnerFixedVramGb("llama-server")',
     '0',
     'boundary: реестр ещё не пришёл (встроенная пара) — плана нет, ноль, без ошибки'),
    ('cp_gone',
     '',
     '[typeof le.COMMAND_PRESETS, typeof le.populateCommandPresets]',
     '["undefined","undefined"]',
     'the command tab has no presets (1.3.611): whisper and the TTS engines are runners of their own; negative: no button '
     'that pastes a command stands in for a server — what the owner turned down on 2026-10-15 and 2026-10-21'),
    ('cap_h200',
     '',
     'le.gpuComputeCap("NVIDIA H200")',
     '9',
     'positive: gpuComputeCap: H200 → 9 (Hopper, альтернатива H200)'),
    ('cap_a40',
     '',
     'le.gpuComputeCap("NVIDIA A40")',
     '8.6',
     'positive: gpuComputeCap: A40 → 8.6 (альтернатива \\bA(40)\\b)'),
    ('cap_a10',
     '',
     'le.gpuComputeCap("NVIDIA A10")',
     '8.6',
     'positive: gpuComputeCap: A10 → 8.6 (альтернатива \\bA(10)\\b)'),
    ('cap_b100',
     '',
     'le.gpuComputeCap("NVIDIA B100")',
     '10',
     'positive: gpuComputeCap: B100 → 10 (альтернатива \\bB[12]00\\b, единица)'),
    ('cap_gb200',
     '',
     'le.gpuComputeCap("NVIDIA GB200")',
     '10',
     'positive: gpuComputeCap: GB200 → 10 (\\bGB[12]0 — префикс GB20)'),
    ('cap_gb20',
     '',
     'le.gpuComputeCap("NVIDIA GB20")',
     '10',
     'positive: gpuComputeCap: GB20 → 10 (\\bGB[12]0 без правой границы)'),
    ('cap_rtx_a4000',
     '',
     'le.gpuComputeCap("NVIDIA RTX A4000")',
     '8.6',
     'positive: gpuComputeCap: RTX A4000 → 8.6 (A[45]000, четвёрка)'),
    ('cap_l40',
     '',
     'le.gpuComputeCap("NVIDIA L40")',
     '8.9',
     'positive: gpuComputeCap: голый L40 → 8.9 (\\bL40 без суффикса S)'),
    ('cap_rtx4000_ada',
     '',
     'le.gpuComputeCap("NVIDIA RTX 4000 Ada Generation")',
     '8.9',
     'as-is: gpuComputeCap: RTX 4000 Ada → 8.9 — верно только по совпадению подстроки /RTX 40/, а не по распознаванию Ada-воркстейшн карты'),
    ('cap_rtx2000_ada',
     '',
     'le.gpuComputeCap("NVIDIA RTX 2000 Ada Generation")',
     '7.5',
     'as-is: gpuComputeCap: RTX 2000 Ada (Ada, реально 8.9) → 7.5 — /RTX 20/ читает воркстейшн-Ada как Turing; НЕВЕРНЫЙ не-null ответ'),
    ('cap_rtx500_ada',
     '',
     'le.gpuComputeCap("NVIDIA RTX 500 Ada Generation Laptop GPU")',
     '12',
     'as-is: gpuComputeCap: RTX 500 Ada (Ada, реально 8.9) → 12 — /RTX 50/ ловит префикс «RTX 500»; НЕВЕРНЫЙ Blackwell-ответ'),
    ('cap_rtx4500_ada',
     '',
     'le.gpuComputeCap("NVIDIA RTX 4500 Ada Generation")',
     'null',
     'as-is: gpuComputeCap: RTX 4500 Ada → null (ни одна семья не матчит «RTX 45», хотя это Ada 8.9)'),
    ('cap_a10g',
     '',
     'le.gpuComputeCap("NVIDIA A10G")',
     'null',
     'as-is: gpuComputeCap: A10G (имя в AWS) → null — \\bA10\\b не проходит перед буквой G'),
    ('cap_rtx_pro_6000',
     '',
     'le.gpuComputeCap("NVIDIA RTX PRO 6000 Blackwell")',
     'null',
     'as-is: gpuComputeCap: RTX PRO 6000 Blackwell → null (Blackwell-воркстейшн не в карте)'),
    ('cap_titan_v',
     '',
     'le.gpuComputeCap("TITAN V")',
     'null',
     'negative: gpuComputeCap: TITAN V → null (только TITAN RTX и \\bV100\\b в карте)'),
    ('cap_rtx5090_nospace',
     '',
     'le.gpuComputeCap("RTX5090")',
     'null',
     'negative: gpuComputeCap: «RTX5090» без пробела → null (шаблон требует «RTX 50»)'),
    ('cap_number',
     '',
     'le.gpuComputeCap(3090)',
     'null',
     'negative: gpuComputeCap(3090) → null (число стрингифицируется в «3090», без «RTX » не матчит)'),
    ('dev_comma_sep_cpu',
     '',
     'le._envDeviceState("FOO=1,TTS_DEVICE=cpu", "")',
     '"cpu"',
     'positive: _envDeviceState: запятая — допустимый разделитель перед TTS_DEVICE=cpu → cpu'),
    ('dev_cvd_empty_comma_term',
     '',
     'le._envDeviceState("CUDA_VISIBLE_DEVICES=,X=1", "")',
     '"cpu"',
     'positive: _envDeviceState: пустой CUDA_VISIBLE_DEVICES= с запятой-терминатором → cpu'),
    ('dev_cvd_lowercase_asis',
     '',
     'le._envDeviceState("cuda_visible_devices=", "")',
     '"auto"',
     'as-is: _envDeviceState: строчный cuda_visible_devices= → auto — регэксп без /i, тогда как _applyDeviceToEnv стирает эту строку без учёта регистра (асимметрия чтения и записи)'),
    ('dev_cvd_empty_beats_gpu',
     '',
     'le._envDeviceState("TTS_DEVICE=cuda\\nCUDA_VISIBLE_DEVICES=", "")',
     '"cpu"',
     'positive: _envDeviceState: пустой CUDA_VISIBLE_DEVICES= перевешивает явный TTS_DEVICE=cuda → cpu (оба в первом if)'),
    ('dev_device_eq_cpu',
     '',
     'le._envDeviceState("", "--device=cpu")',
     '"cpu"',
     'positive: _envDeviceState: --device=cpu в команде (форма с «=») → cpu'),
    ('dev_MYTTS_DEVICE_cpu',
     '',
     'le._envDeviceState("MYTTS_DEVICE=cpu", "")',
     '"auto"',
     'negative: _envDeviceState: MYTTS_DEVICE=cpu → auto (якорь начала/разделителя, cpu-сторона)'),
    ('dev_TTS_DEVICE_cuda_colon',
     '',
     'le._envDeviceState("TTS_DEVICE=cuda:0", "")',
     '"gpu"',
     'positive: _envDeviceState: TTS_DEVICE=cuda:0 → gpu (\\b перед двоеточием)'),
    ('dev_DEVICE_CPU_upper',
     '',
     'le._envDeviceState("DEVICE=CPU", "")',
     '"cpu"',
     'positive: _envDeviceState: DEVICE=CPU в верхнем регистре → cpu (флаг /i)'),
    ('dev_cvd_quoted_zero',
     '',
     'le._envDeviceState("CUDA_VISIBLE_DEVICES=\\"0\\"", "")',
     '"auto"',
     'negative: _envDeviceState: CUDA_VISIBLE_DEVICES="0" (кавычки с содержимым) → auto'),
    ('dev_cvd_empty_trailing_space',
     '',
     'le._envDeviceState("CUDA_VISIBLE_DEVICES= ", "")',
     '"cpu"',
     'positive: _envDeviceState: CUDA_VISIBLE_DEVICES= с хвостовым пробелом → cpu (пробел — терминатор)'),
    ('dev_MYCUDA_VISIBLE_DEVICES',
     '',
     'le._envDeviceState("MYCUDA_VISIBLE_DEVICES=", "")',
     '"auto"',
     'negative: _envDeviceState: MYCUDA_VISIBLE_DEVICES= → auto (якорь начала строки на CVD-проверке)'),
    ('dev_undefined_both',
     '',
     'le._envDeviceState(undefined, undefined)',
     '"auto"',
     'negative: _envDeviceState(undefined, undefined) → auto (шаблонная строка даёт «undefined», не бросает)'),
    ('app_semicolon_row_dropped_whole',
     '',
     'le._applyDeviceToEnv("TTS_DEVICE=cpu;B=2", "auto")',
     '""',
     'as-is: _applyDeviceToEnv: строка «TTS_DEVICE=cpu;B=2» выбрасывается ЦЕЛИКОМ вместе с B=2 — split только по \\n и запятой, тогда как _envDeviceState считает «;» разделителем'),
    ('app_leading_space_trimmed',
     '',
     'le._applyDeviceToEnv("  TTS_DEVICE=cpu\\nA=1", "auto")',
     '"A=1"',
     'positive: _applyDeviceToEnv: строка с ведущими пробелами тримится до проверки и стирается → «A=1»'),
    ('app_no_equals_kept',
     '',
     'le._applyDeviceToEnv("TTS_DEVICE\\nA=1", "auto")',
     '"TTS_DEVICE\\nA=1"',
     'negative: _applyDeviceToEnv: «TTS_DEVICE» без «=» не стирается (регэксп требует =)'),
    ('app_null_gpu',
     '',
     'le._applyDeviceToEnv(null, "gpu")',
     '"TTS_DEVICE=cuda"',
     'positive: _applyDeviceToEnv(null, gpu) → «TTS_DEVICE=cuda» (null коэрсится в пустую строку)'),
    ('app_mode_upper_CPU',
     '',
     'le._applyDeviceToEnv("TTS_DEVICE=cpu\\nA=1", "CPU")',
     '"A=1"',
     'as-is: _applyDeviceToEnv: режим «CPU» в верхнем регистре сравнивается чувствительно к регистру и ведёт себя как auto — стирает, ничего не добавляет'),
    ('app_cpu_idempotent',
     '',
     'le._applyDeviceToEnv(le._applyDeviceToEnv("A=1", "cpu"), "cpu")',
     '"A=1\\nTTS_DEVICE=cpu\\nCUDA_VISIBLE_DEVICES="',
     'positive: _applyDeviceToEnv: двойное применение cpu идемпотентно — ровно две device-строки, без дублей'),
    ('ak_translate_other',
     '',
     'le.artifactKind("translate/other")',
     '"safetensors"',
     'negative: artifactKind: «translate/other» без префикса models-- → safetensors, а не nllb-repo'),
    ('ak_seamless_exact_arch',
     'st.setState({ ...st.state, runners: [{ id: "seamless", artifacts: ["seamless-st"], stArchs: ["seamless_m4t", "seamless_m4t_v2"] }] });'
     ' st.state.artifacts = [{ path: "st/x", arch: "seamless_m4t" }];',
     'le.artifactKind("st/x")',
     '"seamless-st"',
     'boundary: artifactKind: arch ровно «seamless_m4t» (граница startsWith) → seamless-st'),
    ('ak_seamless_arch_case',
     'st.state.artifacts = [{ path: "st/x", arch: "Seamless_M4T" }];',
     'le.artifactKind("st/x")',
     '"safetensors"',
     'as-is: artifactKind: arch «Seamless_M4T» → safetensors — сравнение arch чувствительно к регистру'),
    ('ak_st_found_no_arch',
     'st.state.artifacts = [{ path: "st/x" }];',
     'le.artifactKind("st/x")',
     '"safetensors"',
     'negative: artifactKind: артефакт найден, но без поля arch → safetensors'),
    ('ak_gguf_sttVariant_empty',
     'st.state.models = [{ path: "m.gguf", ggufMeta: { sttVariant: "" } }];',
     'le.artifactKind("m.gguf")',
     '"llm-gguf"',
     'boundary: artifactKind: ggufMeta.sttVariant «» (falsy) → llm-gguf'),
    ('ak_gguf_sttVariant_empty_neg',
     'st.state.models = [{ path: "m.gguf", ggufMeta: { sttVariant: "gigaam" } }];',
     'le.artifactKind("m.gguf")',
     '"asr-gguf"',
     'positive: artifactKind: ggufMeta.sttVariant «gigaam» (truthy) → asr-gguf — пара к пустому sttVariant'),
    ('ak_moonshine_capital',
     '',
     'le.artifactKind("Moonshine/base")',
     '"safetensors"',
     'as-is: artifactKind: «Moonshine/base» → safetensors — префиксы чувствительны к регистру, тогда как суффикс .gguf — нет'),
    ('ak_number',
     '',
     'le.artifactKind(123)',
     '"safetensors"',
     'negative: artifactKind(123) → safetensors (число стрингифицируется, не .gguf, в артефактах нет)'),
    ('rr_fallback_fresh_each_call',
     '',
     'le.runnerRegistry() === le.runnerRegistry()',
     'false',
     'negative: runnerRegistry: фолбэк — новый массив на каждый вызов (=== false), пара к rr_provided_same_ref'),
]

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


# The controller's machine runs its cells through its scout since step 6.8, and
# they are edited in the scout's form (tr-). For that machine the controller's
# models tree is its own, so the choices only that tree backs are offered there
# too — and still held back from any other machine (formOnControllerMachine).
_ON = ('const onMachine = (flag) => { try { rc.openLlamaRemoteEdit("box-c", "gpu0", [], 22031); } catch (e) {}'
       ' st.setTopology({ ...st.topology, nodes: [{ id: "box-c", role: "host", ...(flag ? { controllerMachine: true } : {}) },'
       ' { id: "box-d", role: "host", controllerMachine: !flag }] }); };'
       ' const off = () => { try { rc.openLlamaRemoteEdit("", "", [], ""); } catch (e) {} };')
PINS += [
    ('frcm_the_fact',
     _ON,
     '(() => { onMachine(true); const own = rc.formOnControllerMachine("tr-"); const noForm = rc.formOnControllerMachine("");'
     ' onMachine(false); const other = rc.formOnControllerMachine("tr-"); off(); return [own, noForm, other]; })()',
     '[true,false,false]',
     'форма ячейки на машине контроллера (controllerMachine её узла) — её файлы это файлы контроллера; negative: префикс, за которым нет формы ячейки, — нет (своей формы у контроллера нет с шага 6.9); другая машина — нет, даже если флаг у соседнего узла'),
    ('form_keeps_a_model_its_list_does_not_offer',
     _ON,
     '(() => { const added = []; const sel = { tagName: "SELECT", options: [{ value: "a.gguf" }], value: "", dataset: {}, appendChild(o) { added.push(o.value); this.options.push(o); } };'
     ' const made = document.createElement; document.createElement = () => ({ value: "", textContent: "" }); F({ "tr-MODEL_FILE": sel });'
     ' try { le.applyConfigToForm({ MODEL_FILE: "not/offered/here" }, "tr-"); } catch (e) {} const first = [sel.value, [...added]];'
     ' added.length = 0; try { le.applyConfigToForm({ MODEL_FILE: "a.gguf" }, "tr-"); } catch (e) {} const offered = [sel.value, [...added]];'
     ' added.length = 0; try { le.applyConfigToForm({ MODEL_FILE: "" }, "tr-"); } catch (e) {} document.createElement = made; return [first, offered, [sel.value, added]]; })()',
     '[["not/offered/here",["not/offered/here"]],["a.gguf",[]],["",[]]]',
     'значение, которого нет в списке, остаётся значением поля: select принял бы его за пустоту; negative: то, что в списке, не дублируется, и пустое ничего не добавляет'),
    ('frcm_seamless_panel',
     _ON + ' const panel = (flag) => { onMachine(flag); F({ llamaRemoteEditOverlay: { hidden: false, dataset: {}, querySelector: () => null, querySelectorAll: () => [] },'
     ' "tr-CELL_KIND": { value: "" }, "tr-RUNNER": { value: "seamless" }, "tr-seamlessFields": { style: {} } });'
     ' try { le.applyCellKindUI("tr-"); } catch (e) {} const d = globalThis.__fields["tr-seamlessFields"].style.display; off(); return d; };',
     '[panel(true), panel(false)]',
     '["",""]',
     'defect-history: язык перевода seamless виден в форме любой машины — до 1.3.512 только на машине контроллера, '
     'а с контроллером на NAS такой формы нет вовсе; папку модели скаут приносит сам (2.30)'),
    ('env_block_belongs_to_custom_and_vllm',
     _ON + ' const shown = (runner) => { onMachine(true); F({ llamaRemoteEditOverlay: { hidden: false, dataset: {}, querySelector: () => null, querySelectorAll: () => [] },'
     ' "tr-CELL_KIND": { value: "" }, "tr-RUNNER": { value: runner }, "tr-envFields": { style: {} }, "tr-vllmFields": { style: {} }, "tr-commandFields": { style: {} } });'
     ' try { le.applyCellKindUI("tr-"); } catch (e) {} const f = globalThis.__fields; const r = [f["tr-envFields"].style.display, f["tr-vllmFields"].style.display, f["tr-commandFields"].style.display]; off(); return r; };',
     '["vllm", "custom", "llama-server", "whisper", "strata"].map(shown)',
     '[["","","none"],["","none",""],["none","none","none"],["none","none","none"],["none","none","none"]]',
     'ENV (переменные запуска) виден у vLLM и у custom — vLLM без него не обойти сломанный FlashInfer и не задать HF_HOME; панель vLLM не показывает панель custom и наоборот; '
     'negative: у llama.cpp, whisper и Strata блока ENV нет'),
    ('frcm_seamless_tab',
     _ON + ' const tabs = (flag) => { onMachine(flag); st.setState({ ...st.state, runners: ['
     '{ id: "llama-server", labelKey: "runnerLlama", artifacts: ["llm-gguf"] }, { id: "seamless", labelKey: "runnerSeamless", artifacts: ["seamless-st"] }] });'
     ' const wrap = { innerHTML: "" }; F({ llamaRemoteEditOverlay: { hidden: false, dataset: {}, querySelector: (q) => (q === ".runner-tabs" ? wrap : null), querySelectorAll: () => [] },'
     ' "tr-RUNNER": { value: "llama-server" }, "tr-MODEL_FILE": { value: "" } });'
     ' try { le.renderRunnerTabs("tr-"); } catch (e) {} off(); const b = norm(wrap.innerHTML).match(/<button[^>]*data-runner="seamless"[^>]*>/)[0];'
     ' return [b.includes(" disabled"), b.includes("Controller only")]; };',
     '[tabs(true), tabs(false)]',
     '[[false,false],[false,false]]',
     'defect-history: вкладка seamless открыта в форме любой машины — до 1.3.512 серой была везде, кроме машины '
     'контроллера, хотя скаут 2.30 приносит папку модели сам'),
    ('optional_toggles_stated_by_the_config_that_fills_the_form',
     '',
     'await (async () => { const fm = await import(pathToFileURL(process.env.JS_ROOT + "/form.js").href);'
     ' const boxes = () => Object.fromEntries(cst.toggleFields.map((k) => ["tr-" + k, { type: "checkbox", checked: false }]));'
     ' cst.dirtyOptionalToggles.clear(); cst.dirtyOptionalToggles.add("WARMUP");'
     ' F(boxes()); try { le.applyConfigToForm({ KV_OFFLOAD: "0", MMAP: "1", FIT: " " }, "tr-"); } catch (e) {}'
     ' const marks = [...cst.dirtyOptionalToggles].sort(); const read = fm.readConfigForm("tr-");'
     ' const r = [marks, [read.KV_OFFLOAD, read.MMAP, read.FIT, read.WARMUP], globalThis.__fields["tr-WARMUP"].checked]; cst.dirtyOptionalToggles.clear(); return r; })()',
     '[["KV_OFFLOAD","MMAP"],["0","1","",""],true]',
     'defect-history (1.3.625): необязательный переключатель читается заданным, только пока помечен, а метки жили от того, что '
     'страница трогала последним: ячейка с KV_OFFLOAD "0" теряла его на следующем «Применить» со свежей страницы, а тронутый для '
     'одной ячейки переключатель приходил заданным в следующую; теперь метки ставит конфиг, которым заполнена форма; negative: '
     'не заданный конфигом (WARMUP, пробелы у FIT) — не задан, хотя коробка нарисована умолчанием сервера'),
    ('model_name_loads_the_cells_own',
     '',
     '(() => { const load = (config) => { F({ "tr-MODEL_NAME": { value: "left over" } }); try { le.applyConfigToForm(config, "tr-"); } catch (e) {}'
     ' return globalThis.__fields["tr-MODEL_NAME"].value; }; return [load({ MODEL_NAME: "gemma-chat", RUNNER: "whisper" }), load({ ALIAS: "g4" })]; })()',
     '["gemma-chat",""]',
     'MODEL_NAME (1.3.507) — имя ячейки на входе машины, у любого раннера; negative: у ячейки его нет — поле пустое, а не имя, '
     'оставшееся от другой ячейки, и не алиас'),
    # The speculation switch says whether the start speculates, by the builder's rule (cell-plan.js CellDraft, 2026-11-07).
    ('spec_switch_opens_as_the_start_speculates',
     '',
     '(() => { const open = (config) => { const sw = { type: "checkbox", checked: null, closest: () => null };'
     ' F({ "tr-SPEC_ENABLED": sw }); try { le.applyConfigToForm(config, "tr-"); } catch (e) {} return sw.checked; };'
     ' const file = "m/mtp-q.gguf";'
     ' return [open({ SPEC_TYPE: "draft-mtp", SPEC_DRAFT_MODEL_FILE: file }), open({ SPEC_TYPE: "", SPEC_DRAFT_MODEL_FILE: file }),'
     ' open({ SPEC_TYPE: "draft-mtp" }), open({ SPEC_TYPE: "ngram-mod" }),'
     ' open({ SPEC_TYPE: "none", SPEC_DRAFT_MODEL_FILE: file }), open({ SPEC_TYPE: "draft-eagle3" }),'
     ' open({ SPEC_TYPE: "draft-mtp", SPEC_DRAFT_MODEL_FILE: file, ENABLE_EMBEDDINGS: "1" }), open({})]; })()',
     '[true,true,true,true,false,false,false,false]',
     'переключатель спекуляции открывается так, как старт её сделает: файл с типом, файл без типа (сборщик грузит его по типу '
     'самого файла — раньше такая ячейка открывалась выключенной), своя голова MTP, ngram — включён; negative: none с файлом '
     '(так пишет выключенный), тип черновика без файла, ячейка эмбеддингов, пусто — выключен'),
    ('vllm_recipe_fields_load_the_cells_own',
     '',
     '(() => { const load = (config) => { F({ "tr-MAX_NUM_SEQS": { value: "left" }, "tr-KV_CACHE_DTYPE": { value: "left" }, "tr-REASONING_PARSER": { value: "left" } });'
     ' try { le.applyConfigToForm(config, "tr-"); } catch (e) {} const f = globalThis.__fields; return [f["tr-MAX_NUM_SEQS"].value, f["tr-KV_CACHE_DTYPE"].value, f["tr-REASONING_PARSER"].value]; };'
     ' return [load({ RUNNER: "vllm", MAX_NUM_SEQS: "8", KV_CACHE_DTYPE: "fp8", REASONING_PARSER: "nano_v3" }), load({ RUNNER: "vllm" })]; })()',
     '[["8","fp8","nano_v3"],["","",""]]',
     'три поля рецепта vLLM открываются как сохранены; negative: у ячейки их нет — поля пусты, а не значения, оставшиеся от другой ячейки'),
    ('vllm_recipe_fields_have_a_tip',
     '',
     '(() => { const made = []; const real = document.createElement; const names = ["MAX_NUM_SEQS", "KV_CACHE_DTYPE", "REASONING_PARSER", "NOT_A_FIELD"];'
     ' document.createElement = () => { const b = { className: "", type: "", innerHTML: "", attrs: {}, setAttribute(k, v) { this.attrs[k] = v; }, querySelector: () => b.tip, tip: { textContent: "" } }; made.push(b); return b; };'
     ' const labels = {}; names.forEach((f) => { labels[f] = { parentElement: { querySelector: () => null }, after(btn) { this.btn = btn; } }; });'
     ' F({ llamaRemoteEditOverlay: { hidden: false, dataset: {}, querySelectorAll: () => [],'
     ' querySelector: (q) => { const m = q.match(/^label\\[for="tr-([A-Z_]+)"\\]$/); return q === ".runner-tabs" ? { innerHTML: "" } : (m ? (labels[m[1]] || null) : null); } } });'
     ' try { le.renderRunnerTabs("tr-"); } catch (e) {} document.createElement = real;'
     ' return names.map((f) => [f, labels[f].btn ? labels[f].btn.tip.textContent.slice(0, 24) : null]); })()',
     '[["MAX_NUM_SEQS","How many requests vLLM w"],["KV_CACHE_DTYPE","Data type of the KV cach"],["REASONING_PARSER","Splits a reasoning model"],["NOT_A_FIELD",null]]',
     'три поля рецепта vLLM получают (?) с подсказкой из словаря (_STATIC_TIP_FIELDS); negative: имя без подсказки в словаре метки не получает'),
    ('trust_remote_code_loads_the_cells_own',
     '',
     '(() => { const load = (config) => { const box = { id: "tr-TRUST_REMOTE_CODE", tagName: "INPUT", type: "checkbox", checked: true, defaultChecked: false };'
     ' F({ "tr-vllmFields": { style: {}, querySelectorAll: () => [box] }, "tr-TRUST_REMOTE_CODE": box }); try { le.applyConfigToForm(config, "tr-"); } catch (e) {}'
     ' return box.checked; };'
     ' return [load({ RUNNER: "vllm", TRUST_REMOTE_CODE: "1" }), load({ RUNNER: "vllm", TRUST_REMOTE_CODE: "true" }), load({ RUNNER: "vllm", TRUST_REMOTE_CODE: "" }), load({ RUNNER: "vllm" }), load({ RUNNER: "vllm", TRUST_REMOTE_CODE: "0" })]; })()',
     '[true,true,false,false,false]',
     'TRUST_REMOTE_CODE ячейки открывается как сохранён: «1» и «true» — отмечено; negative: пусто, нет поля и «0» — не отмечено, а не флажок, оставшийся отмеченным от другой ячейки (код авторов модели без слова оператора не запускается). Флажок — в своей панели, как на странице: без неё цикл панелей до него не доходил, и пин был зелёным по везению'),
    ('runner_tab_not_for_engines',
     ' const tabsOf = (runners) => { st.setState({ ...st.state, runners }); const wrap = { innerHTML: "" };'
     ' F({ llamaRemoteEditOverlay: { hidden: false, dataset: {}, querySelector: (q) => (q === ".runner-tabs" ? wrap : null), querySelectorAll: () => [] },'
     ' "tr-RUNNER": { value: "llama-server" }, "tr-MODEL_FILE": { value: "" } });'
     ' try { le.renderRunnerTabs("tr-"); } catch (e) {} return (norm(wrap.innerHTML).match(/data-runner="[^"]+"/g) || []).map((x) => x.slice(13, -1)); };',
     'tabsOf([{ id: "llama-server", labelKey: "runnerLlama", artifacts: ["llm-gguf"] }, { id: "ollama", labelKey: "runnerOllama", artifacts: ["engine-model"], editorTab: false }, { id: "custom", labelKey: "runnerCustom", artifacts: ["*"], editorTab: true }, { id: "lmstudio", labelKey: "runnerLmStudio", artifacts: ["engine-model"], editorTab: false }, { id: "whisper", labelKey: "runnerWhisper", artifacts: ["whisper-size"] }])',
     '["llama-server","custom","whisper"]',
     'negative: у раннеров движков (editorTab: false) вкладки в редакторе нет — ячейку движка делают на шаге резерва; у прочих есть, и у старого реестра без поля тоже'),
    ('frcm_vllm_field_hidden_when_derived',
     _ON + ' const field = (flag) => { onMachine(flag); st.setState({ ...st.state, runners: [{ id: "vllm", labelKey: "runnerVllm", artifacts: ["*"] }] });'
     ' const wrap = { innerHTML: "" }; F({ llamaRemoteEditOverlay: { hidden: false, dataset: {}, querySelector: (q) => (q === ".runner-tabs" ? wrap : null), querySelectorAll: () => [] },'
     ' "tr-RUNNER": { value: "vllm" }, "tr-MODEL_FILE": { value: "org/Qwen-ST" }, "tr-VLLM_MODEL": { style: {}, previousElementSibling: null } });'
     ' try { le.renderRunnerTabs("tr-"); } catch (e) {} off(); return globalThis.__fields["tr-VLLM_MODEL"].style.display; };',
     '[field(true), field(false)]',
     '["none","none"]',
     'поле пути vLLM прячется, когда модель выбрана в списке, на любой машине: путь выводится из выбора (негативный случай — пустой выбор, HF-репозиторий — следующий пин)'),
    ('frcm_vllm_field_shown_with_nothing_picked',
     _ON + ' const field = (flag) => { onMachine(flag); st.setState({ ...st.state, runners: [{ id: "vllm", labelKey: "runnerVllm", artifacts: ["*"] }] });'
     ' const wrap = { innerHTML: "" }; F({ llamaRemoteEditOverlay: { hidden: false, dataset: {}, querySelector: (q) => (q === ".runner-tabs" ? wrap : null), querySelectorAll: () => [] },'
     ' "tr-RUNNER": { value: "vllm" }, "tr-MODEL_FILE": { value: "" }, "tr-VLLM_MODEL": { style: {}, previousElementSibling: null } });'
     ' try { le.renderRunnerTabs("tr-"); } catch (e) {} off(); return globalThis.__fields["tr-VLLM_MODEL"].style.display; };',
     '[field(true), field(false)]',
     '["",""]',
     'negative: ничего не выбрано — поле видно: туда вписывают HF-репозиторий или путь на машине'),
    ('frcm_vllm_path_from_folder',
     _ON + ' const pick = (flag) => { onMachine(flag); st.setState({ ...st.state, config: {}, paths: { modelsDir: "/m" },'
     ' artifacts: [{ path: "org/Qwen-ST", name: "Qwen-ST", format: "safetensors", arch: "qwen2" }], runners: [{ id: "vllm", labelKey: "runnerVllm", artifacts: ["*"] }] });'
     ' let onChange = null; F({ llamaRemoteEditOverlay: { hidden: false, dataset: {}, querySelector: () => null, querySelectorAll: () => [] },'
     ' "tr-MODEL_FILE": { value: "org/Qwen-ST", addEventListener: (ev, fn) => { if (ev === "change") onChange = fn; } },'
     ' "tr-VLLM_MODEL": { value: "" }, "tr-RUNNER": { value: "vllm" } });'
     ' try { le.wireCellKindToggle("tr-"); } catch (e) {} try { onChange && onChange(); } catch (e) {}'
     ' const v = globalThis.__fields["tr-VLLM_MODEL"].value; off(); return v; };',
     '[pick(true), pick(false)]',
     '["/m/org/Qwen-ST","org/Qwen-ST"]',
     'выбрана папка safetensors — на машине контроллера это путь его дерева моделей; на другой машине — место среди моделей контроллера: скаут принесёт модель или покажет её, и строка возьмёт её оттуда. Пути на чужой машине форма не выдумывает'),
    ('vllm_preview_says_where_a_placed_model_is_read',
     'st.setState({ ...st.state, artifacts: [{ path: "org/Qwen-ST", name: "Qwen-ST" }] });'
     ' const line = (said) => { F({ "tr-VLLM_MODEL": { value: said } }); return le.buildVllmCommandPreview("tr-").split(" ").slice(2, 3)[0]; };',
     '[line("org/Qwen-ST"), line("org/Qwen-ST/"), line("Qwen/Qwen2.5-7B"), line("/mnt/x")]',
     '["\\"${LLAMA_MODELS_DIR:-$HOME/llama.cpp/models}\\"/org/Qwen-ST","\\"${LLAMA_MODELS_DIR:-$HOME/llama.cpp/models}\\"/org/Qwen-ST/","Qwen/Qwen2.5-7B","/mnt/x"]',
     'предпросмотр говорит то же, что настоящая строка: место среди моделей контроллера читается оттуда, куда их принёс скаут; negative: HF-репозиторий и путь на машине остаются как написаны'),
    ('vllm_cell_opens_on_its_place_or_its_path_in_the_picker',
     'st.setState({ ...st.state, paths: { modelsDir: "/m" }, artifacts: [{ path: "org/Qwen-ST", name: "Qwen-ST" }], runners: [{ id: "vllm", labelKey: "runnerVllm", artifacts: ["*"] }] });'
     ' const opened = (said) => { const sel = { tagName: "SELECT", options: [{ value: "org/Qwen-ST" }], value: "", dataset: {}, appendChild() {} }; F({ "tr-MODEL_FILE": sel });'
     ' try { le.applyConfigToForm({ RUNNER: "vllm", VLLM_MODEL: said }, "tr-"); } catch (e) {} return sel.value; };',
     '[opened("org/Qwen-ST"), opened("/m/org/Qwen-ST"), opened("Qwen/Qwen2.5-7B")]',
     '["org/Qwen-ST","org/Qwen-ST",""]',
     'открытая ячейка vLLM показывает в списке свою модель, названную местом или путём; negative: HF-репозиторий не модель библиотеки — список пуст'),
]



# ── Strata (1.3.512): a runner button, its panel, its preview ─────────────────
# The preview mirrors StrataRunner.command on the server; the expected text is
# that method's own answer, so the two cannot drift apart unnoticed.
sys.path.insert(0, str(ROOT))
from _contract import Contract, RunnerLines  # noqa: E402

_S_FIRST = "Q/I/IQ2_XS/Qwen3.8-Flash-Next-GSQ-RCO-IQ2_XS-00001-of-00002.gguf"
_S_FULL = {"MODEL_FILE": _S_FIRST, "SPEC_DRAFT_MODEL_FILE": "Q/I/IQ2_XS/mtp-q2_0.gguf", "STRATA_CONTEXT": "65536",
           "STRATA_KV": "k8v4", "STRATA_DRAFT_VOCAB": "en", "STRATA_VRAM_RESERVE_MIB": "2048",
           "MODEL_NAME": "qwen3.8-flash-next"}
_S_BARE = {"MODEL_FILE": _S_FIRST}
_S_NOTE = "# the scout brings both parts and the draft layer; Strata's pack is made from them at the start"
# DeepSeek-V4.1-Flash on Strata (2026-11-03): the rows of contract/runner_lines.json the program wrote for it.
_SD_BARE = {"MODEL_FILE": "D/I/IQ1_M/DeepSeek-V4.1-Flash-1017-GSQ-RCO-IQ1_M-00001-of-00006.gguf"}
_SD_FULL = {**_SD_BARE, "STRATA_ENGRAM_FILE": "D/I/IQ4_NL/DeepSeek-V4.1-Flash-Engram-IQ4_NL.gguf",
            "STRATA_META_FILE": "U/u/Q8_K_XL/DeepSeek-V4.1-Flash-1017-UD-Q8_K_XL-00001-of-00009.gguf",
            "SPEC_DRAFT_MODEL_FILE": "U/u/Q8_0/dspark-DeepSeek-V4.1-Flash-1017-Q8_0.gguf",
            "MMPROJ_FILE": "D/I/default/mmproj-DeepSeek-V4.1-Flash-1017-BF16.gguf", "STRATA_CONTEXT": "131072",
            "MODEL_NAME": "deepseek-v4.1-flash"}
_SD_NOTE = "# the scout brings the set's five parts, the Engram, the drafter and the metadata part; Strata's pack is made from them at the start"


def _strata_fields(cfg):
    pairs = {**cfg, "RUNNER": "strata"}
    return "F({" + ", ".join(f'"tr-{k}": {{ value: {json.dumps(v)} }}' for k, v in pairs.items()) + "});"


def _strata_ds_fields(cfg):
    pairs = {**cfg, "RUNNER": "strata-ds"}
    return "F({" + ", ".join(f'"tr-{k}": {{ value: {json.dumps(v)} }}' for k, v in pairs.items()) + "});"


_S_REG = ('st.setState({ ...st.state, runners: [{ id: "llama-server", labelKey: "runnerLlama", artifacts: ["llm-gguf"] },'
          ' { id: "strata", labelKey: "runnerStrata", artifacts: ["strata-gguf"], ggufArchs: ["qwen4exp"] }] });')

PINS += [
    ('strata_preview_mirrors_server',
     _strata_fields(_S_FULL),
     'le._buildCommandExecPreview("tr-")',
     json.dumps("export PORT={{PORT}}\n" + _S_NOTE + "\nexec " + RunnerLines.of("strata", _S_FULL)),
     'превью Strata — та же строка, что строит сервер (StrataRunner.command): обе части пути, черновик, окно, KV, '
     'словарь, запас VRAM, имя'),
    ('strata_preview_defaults',
     _strata_fields(_S_BARE),
     'le._buildCommandExecPreview("tr-")',
     json.dumps("export PORT={{PORT}}\n" + _S_NOTE + "\nexec " + RunnerLines.of("strata", _S_BARE)),
     'пустые поля — те же значения по умолчанию, что у сервера: int8, cyrillic; без черновика, запаса и имени; окна модель '
     'не назвала (её нет в библиотеке) — и --context нет: лаунчер возьмёт окно своей модели'),
    ('strata_preview_trained_window',
     'st.setState({ ...st.state, models: [{ path: ' + json.dumps(_S_FIRST) + ', ggufMeta: { contextLength: 262144 } }] }); '
     + _strata_fields(_S_BARE),
     'le._buildCommandExecPreview("tr-")',
     json.dumps("export PORT={{PORT}}\n" + _S_NOTE + "\nexec " + RunnerLines.of("strata", _S_BARE, trained=262144)),
     'пустое поле окна, модель в библиотеке обучена на 262144 — --context 262144, как у сервера (StrataRunner.command с '
     'окном обучения); было 131072 — половина окна модели (владелец, 2026-10-26)'),
    ('window_placeholder_is_the_models_most',
     'st.setState({ ...st.state, runners: [{ id: "llama-server", labelKey: "runnerLlama", artifacts: ["llm-gguf"], modelField: "MODEL_FILE" },'
     ' { id: "strata", labelKey: "runnerStrata", contextField: "STRATA_CONTEXT", modelField: "MODEL_FILE" },'
     ' { id: "vllm", labelKey: "runnerVllm", contextField: "MAX_MODEL_LEN", modelField: "VLLM_MODEL" }],'
     ' models: [{ path: ' + json.dumps(_S_FIRST) + ', ggufMeta: { contextLength: 262144 } }, { path: "Qwen/Qwen3-8B/BF16", contextLength: 40960 }] }); '
     'F({ "tr-RUNNER": { value: "strata" }, "tr-MODEL_FILE": { value: ' + json.dumps(_S_FIRST) + ' }, "tr-STRATA_CONTEXT": { value: "65536", placeholder: "131072" },'
     ' "tr-VLLM_MODEL": { value: "Qwen/Qwen3-8B/BF16" }, "tr-MAX_MODEL_LEN": { value: "", placeholder: "32768 — empty = model default" },'
     ' "tr-CTX_SIZE": { value: "", placeholder: "4096" } });',
     '(() => { const f = globalThis.__fields; const out = []; le.syncWindowPlaceholder("tr-"); out.push(f["tr-STRATA_CONTEXT"].placeholder);'
     ' f["tr-MODEL_FILE"].value = "elsewhere/x-00001-of-00002.gguf"; le.syncWindowPlaceholder("tr-"); out.push(f["tr-STRATA_CONTEXT"].placeholder);'
     ' f["tr-RUNNER"].value = "vllm"; le.syncWindowPlaceholder("tr-"); out.push(f["tr-MAX_MODEL_LEN"].placeholder);'
     ' f["tr-RUNNER"].value = "llama-server"; le.syncWindowPlaceholder("tr-"); out.push(f["tr-CTX_SIZE"].placeholder);'
     ' return out; })()',
     '["262144","","40960","4096"]',
     'подсказка поля окна — всегда максимум модели (владелец, 2026-10-26), даже когда в поле стоит число: Strata — окно из '
     'заголовка GGUF (было «131072» в разметке), vLLM — из конфига чекпойнта (было «32768», ничьё число); negative: модель '
     'библиотеке не известна — подсказки нет, а не выдуманное число; у CTX_SIZE своя синхронизация — её не трогают'),
    ('strata_gguf_kind',
     _S_REG,
     '[le.ggufKind({ sttVariant: "gigaam" }), le.ggufKind({ architecture: "qwen4exp" }),'
     ' le.ggufKind({ architecture: "llama" }), le.ggufKind(null)]',
     '["asr-gguf","strata-gguf","llm-gguf","llm-gguf"]',
     'вид GGUF по его заголовку: речь — asr; архитектура, которую берёт раннер (qwen4exp — Strata), — его вид; '
     'остальное — llm; без заголовка — llm'),
    ('strata_gguf_kind_old_server',
     'st.setState({ ...st.state, runners: [{ id: "llama-server", artifacts: ["llm-gguf"] }] });',
     'le.ggufKind({ architecture: "qwen4exp" })',
     '"llm-gguf"',
     'negative: реестр сервера не знает Strata (старый сервер) — файл остаётся llm, а не выдуманным видом'),
    ('strata_artifact_kind',
     _S_REG + ' st.setState({ ...st.state, models: [{ path: "' + _S_FIRST + '", ggufMeta: { architecture: "qwen4exp" } }] });',
     'le.artifactKind("' + _S_FIRST + '")',
     '"strata-gguf"',
     'файл модели Strata из списка моделей — вид strata-gguf: по нему выбор модели переключает раннер на Strata'),
    ('strata_tabs',
     _S_REG + ' st.setState({ ...st.state, models: [{ path: "' + _S_FIRST + '", ggufMeta: { architecture: "qwen4exp" } }] });'
     ' const wrap = { innerHTML: "" }; F({ llamaRemoteEditOverlay: { hidden: false, dataset: {},'
     ' querySelector: (q) => (q === ".runner-tabs" ? wrap : null), querySelectorAll: () => [] },'
     ' "tr-RUNNER": { value: "strata" }, "tr-MODEL_FILE": { value: "' + _S_FIRST + '" } });'
     ' try { le.renderRunnerTabs("tr-"); } catch (e) {} globalThis.__wrap = wrap;',
     '(() => { const h = norm(globalThis.__wrap.innerHTML);'
     ' const b = (id) => h.match(new RegExp(`<button[^>]*data-runner="${id}"[^>]*>`))[0];'
     ' return [b("strata").includes(" disabled"), b("strata").includes("is-active"), b("llama-server").includes(" disabled")]; })()',
     '[false,true,true]',
     'модель Strata выбрана: вкладка Strata открыта и активна; negative: llama.cpp серая — он не знает qwen4exp'),
    ('strata_panel',
     _S_REG + ' F({ llamaRemoteEditOverlay: { hidden: false, dataset: {}, querySelector: () => null, querySelectorAll: () => [] },'
     ' "tr-CELL_KIND": { value: "" }, "tr-RUNNER": { value: "strata" }, "tr-strataFields": { style: {} },'
     ' "tr-llamaFields": { style: {} }, "tr-llamaAside": { style: {} }, "tr-commandAside": { style: {} },'
     ' "tr-strataDraft": { textContent: "", dataset: {}, style: {} },'
     ' "tr-SPEC_DRAFT_MODEL_FILE": { value: "Q/I/IQ2_XS/mtp-q2_0.gguf" } });'
     ' try { le.applyCellKindUI("tr-"); } catch (e) {}',
     '(() => { const f = globalThis.__fields; return [f["tr-strataFields"].style.display, f["tr-llamaFields"].style.display,'
     ' f["tr-commandAside"].style.display, f["tr-strataDraft"].dataset.state,'
     ' f["tr-strataDraft"].textContent.includes("mtp-q2_0.gguf")]; })()',
     '["","none","",\"on\",true]',
     'раннер Strata: её панель видна, флаги llama.cpp скрыты, справа — превью команды; панель называет слой черновика'),
    ('strata_ds_preview_mirrors_server',
     _strata_ds_fields(_SD_FULL),
     'le._buildCommandExecPreview("tr-")',
     json.dumps("export PORT={{PORT}}\n" + _SD_NOTE + "\nexec " + RunnerLines.of("strata-ds", _SD_FULL)),
     'превью DeepSeek на Strata — та же строка, что строит сервер (StrataDeepSeekRunner.command): набор, Engram, '
     'часть метаданных, драфтер, читатель картинок, окно, имя'),
    ('strata_ds_preview_bare',
     _strata_ds_fields(_SD_BARE),
     'le._buildCommandExecPreview("tr-")',
     json.dumps("export PORT={{PORT}}\n" + _SD_NOTE + "\nexec " + RunnerLines.of("strata-ds", _SD_BARE)),
     'negative: файлы рядом с набором ещё не найдены (их находит сохранение) — флагов для них нет, как у сервера'),
    ('strata_ds_panel_shows_its_files_not_qwen_settings',
     ' globalThis.__panel = (runner) => { F({ llamaRemoteEditOverlay: { hidden: false, dataset: {}, querySelector: () => null, querySelectorAll: () => [] },'
     ' "tr-CELL_KIND": { value: "" }, "tr-RUNNER": { value: runner }, "tr-strataFields": { style: {} }, "tr-strataQwenOnly": { style: {} },'
     ' "tr-strataDsFiles": { style: {} }, "tr-strataDraft": { style: {}, textContent: "", dataset: {} } });'
     ' try { le.applyCellKindUI("tr-"); } catch (e) {} const f = globalThis.__fields;'
     ' return ["strataFields", "strataQwenOnly", "strataDsFiles", "strataDraft"].map((id) => f["tr-" + id].style.display); };',
     '[__panel("strata-ds"), __panel("strata"), __panel("llama-server")]',
     '[["","none","","none"],["","","none",""],["none","","none",""]]',
     'DeepSeek: панель Strata с окном и файлами набора, без настроек движка Qwen и без строки о слое черновика; '
     'negative: у Qwen — его настройки и строка черновика, файлов DeepSeek нет; у llama.cpp панели нет'),
    ('strata_keeps_its_models_by_its_folder',
     _S_REG.replace('ggufArchs: ["qwen4exp"] }', 'ggufArchs: ["qwen4exp"], workFolder: true }')
     + ' globalThis.__panel = (runner) => { F({ llamaRemoteEditOverlay: { hidden: false, dataset: {}, querySelector: () => null, querySelectorAll: () => [] },'
     ' "tr-CELL_KIND": { value: "" }, "tr-RUNNER": { value: runner }, "tr-cacheRow": { style: {} }, "tr-cacheByFolder": { style: {} } });'
     ' try { le.applyCellKindUI("tr-"); } catch (e) {} const f = globalThis.__fields; return [f["tr-cacheRow"].style.display, f["tr-cacheByFolder"].style.display]; };',
     '[__panel("strata"), __panel("llama-server")]',
     '[["none",""],["","none"]]',
     'раннер, что держит модели в своей папке (workFolder, Strata): переключателя «хранить модель» нет, вместо него слова, где она лежит '
     '(владелец, 2026-11-03); negative: у llama.cpp переключатель на месте, слов нет'),
    ('cache_switch_opens_on_cell',
     'globalThis.__open = (slot) => { st.setTopology({ ...st.topology, nodes: [{ id: "h1", role: "host", servers: slot ? [slot] : [] }] });'
     ' F({ "tr-cacheModels": { checked: false, type: "checkbox" } });'
     ' try { rc.openLlamaRemoteEdit("h1", "gpu0", [], slot ? "c22031" : ""); } catch (e) {}'
     ' const v = globalThis.__fields["tr-cacheModels"].checked; try { rc.openLlamaRemoteEdit("h1", "gpu0", [], ""); } catch (e) {} return v; };',
     '[__open({ isSlot: true, clientId: "h1", cellId: "c22031", port: null, slotConfig: { MODEL_FILE: "m.gguf" }, cacheModels: false }),'
     ' __open({ isSlot: true, clientId: "h1", cellId: "c22031", port: null, slotConfig: { MODEL_FILE: "m.gguf" }, cacheModels: true }), __open(null)]',
     '[false,true,true]',
     'defect-history: галочка кэша открывается со значением ячейки — раньше всегда включённой, и Apply включал кэш '
     'ячейке, где его выключили; новая ячейка — с кэшем: модель пишется на диск один раз (владелец, 2026-10-13)'),
    ('strata_panel_no_draft',
     _S_REG + ' F({ "tr-strataDraft": { textContent: "", dataset: {} }, "tr-SPEC_DRAFT_MODEL_FILE": { value: "" } });',
     '(() => { le.syncStrataDraftNote("tr-"); const n = globalThis.__fields["tr-strataDraft"];'
     ' return [n.dataset.state, n.textContent.includes("Q2_0"), n.textContent.includes("an IQ pack does not start")]; })()',
     '["off",true,true]',
     'negative: слоя черновика в библиотеке нет — панель говорит это вслух, а не молчит, и говорит обе правды: пакет Q2_0 идёт без него вдвое '
     'медленнее, пакет IQ не стартует (defect-history 2026-10-17: строка уверяла, что Strata работает без него, а IQ1_M после копирования '
     '54 GiB падал с «native (IQ) pack needs --spec»)'),
]


#: The server's registry, as the page receives it: the folder kinds come from its stArchs.
_REG = "st.setState({ ...st.state, runners: " + json.dumps(Contract.table("controller")["runners"]) + " });"
_G_FULL = {"MODEL_FILE": "GR00T-N1.7-3B/nvidia/BF16/", "GR00T_BACKBONE": "/srv/models/Cosmos-Reason2-2B/nvidia/BF16",
           "GR00T_EMBODIMENT": "XDOF", "GR00T_DENOISING_STEPS": "8", "MODEL_NAME": "gr00t-n1.7"}
_G_BARE = {"MODEL_FILE": "GR00T-N1.7-3B/nvidia/BF16"}
_G_NOTE = "# the scout brings the checkpoint and its backbone; the cell serves POST /v1/robot/predict"


def _gr00t_fields(cfg):
    pairs = {**cfg, "RUNNER": "gr00t"}
    return "F({" + ", ".join(f'"tr-{k}": {{ value: {json.dumps(v)} }}' for k, v in pairs.items()) + "});"


PINS += [
    ('gr00t_preview_mirrors_server',
     _gr00t_fields(_G_FULL),
     'le._buildCommandExecPreview("tr-")',
     json.dumps("export PORT={{PORT}}\n" + _G_NOTE + "\nexec " + RunnerLines.of("gr00t", _G_FULL)),
     'превью GR00T — та же строка, что строит сервер (Gr00tRunner.command): папка чекпойнта без хвостового «/», '
     'своя основа, робот, шаги, имя'),
    ('gr00t_preview_defaults',
     _gr00t_fields(_G_BARE),
     'le._buildCommandExecPreview("tr-")',
     json.dumps("export PORT={{PORT}}\n" + _G_NOTE + "\nexec " + RunnerLines.of("gr00t", _G_BARE)),
     'пустые поля — основа Cosmos из библиотеки и робот DROID, как у сервера'),
    ('st_kind_from_the_registry',
     _REG,
     '[le.stKind("Gr00tN1d7"), le.stKind("seamless_m4t_v2"), le.stKind("seamless_m4t"), le.stKind("qwen3_vl"), '
     'le.stKind(""), (le.stOwner("Gr00tN1d7") || {}).id, le.stOwner("qwen3_vl")]',
     json.dumps(["gr00t-st", "seamless-st", "seamless-st", "safetensors", "safetensors", "gr00t", None]),
     'вид папки safetensors — по stArchs раннеров сервера: GR00T и seamless свои, основа Cosmos (qwen3_vl) — общий; '
     'negative: пустая архитектура — общий вид, владельца нет'),
    ('ak_gr00t_found',
     _REG + ' st.state.artifacts = [{ path: "GR00T-N1.7-3B/nvidia/BF16", arch: "Gr00tN1d7" }];',
     'le.artifactKind("GR00T-N1.7-3B/nvidia/BF16")',
     '"gr00t-st"',
     'positive: папка GR00T в выборе модели — своего вида, кнопка GR00T берёт её, а vLLM — нет'),
]

# The five voice servers (1.3.553): the launcher runners. The preview is held to the server's line over the table the
# program is held to (contract/runner_lines.json), and the tabs to the kinds the registry names.
_LINES = [row for row in Contract.table("runner_lines")["lines"] if "name" in row]

_L_NOTE = "# the launcher installs its engine at the first start (minutes); the scout brings the model's folder"


def _launcher_fields(runner, cfg):
    pairs = {**cfg, "RUNNER": runner}
    return "F({" + ", ".join(f'"tr-{k}": {{ value: {json.dumps(v)} }}' for k, v in pairs.items()) + "});"


for _i, (_name, _rid, _cfg, _line) in enumerate((r["name"], r["runner"], r["config"], r["line"]) for r in _LINES if r["runner"] != "voice-clone"):
    PINS.append((f'launcher_preview_{_i}_{_rid.replace("-", "_")}', _REG + _launcher_fields(_rid, _cfg),
                 'le._buildCommandExecPreview("tr-")',
                 json.dumps("export PORT={{PORT}}\n" + _L_NOTE + "\nexec " + _line),
                 f"the preview is the line the server builds (LauncherCellMixin.command): {_name}"))

_MINI_SHALLOW = "MiniCPM-o-4_5-gguf/model.gguf"
_VOICE_ROWS = [{"path": "personaplex-7b-v1/nvidia/SAFETENSORS", "arch": "personaplex"},
               {"path": "Step-Audio-2-mini/stepfun-ai/SAFETENSORS", "arch": "step_audio_2"},
               {"path": "Qwen3-Omni-30B-A3B-Instruct-AWQ-4bit/cyankiwi/AWQ", "arch": "qwen3_omni_moe"},
               {"path": "LFM2.5-Audio-1.5B/LiquidAI/SAFETENSORS", "arch": "Lfm2AudioForConditionalGeneration"},
               {"path": "Qwen3-8B/Qwen/BF16", "arch": "qwen3"}]


_VOICE_MODELS = [{"path": "MiniCPM-o-4_5-gguf/openbmb/Q4_K_M/MiniCPM-o-4_5-Q4_K_M.gguf", "ggufMeta": {"architecture": "qwen3"}}]


def _tabs_expr(runner, model):
    return ('(() => { const h = norm(globalThis.__wrap.innerHTML);'
            ' const b = (id) => h.match(new RegExp(`<button[^>]*data-runner="${id}"[^>]*>`))[0];'
            ' return Object.fromEntries(["personaplex", "lfm-audio", "step-audio2", "qwen3-omni", "minicpm-omni", "vllm", "llama-server"]'
            '.map((id) => [id, b(id).includes(" disabled")])); })()')


PINS += [
    ('launcher_preview_no_model', _REG + _launcher_fields("personaplex", {}),
     'le._buildCommandExecPreview("tr-")',
     json.dumps("export PORT={{PORT}}\n" + _L_NOTE + "\nexec bash $HOME/run_personaplex.sh \"$PORT\" …"),
     'a runner with no model yet says so with «…», as the others do'),
    ('launcher_preview_shallow_path', _REG + _launcher_fields("minicpm-omni", {"MODEL_FILE": _MINI_SHALLOW}),
     'le._buildCommandExecPreview("tr-")',
     json.dumps("export PORT={{PORT}}\n" + _L_NOTE + "\n# MODEL_FILE must be a file of a library model laid out as <model>/<author>/<variant>/<file>"),
     'negative: llama.cpp-omni with a file that has no model folder above it: the preview says the start refuses it, and prints no exec line'),
    ('launcher_preview_not_for_other_runners', _REG + _launcher_fields("gr00t", {"MODEL_FILE": "GR00T-N1.7-3B/nvidia/BF16"}),
     '!le._buildCommandExecPreview("tr-").includes("run_personaplex") && le._buildCommandExecPreview("tr-").includes("run_gr00t.sh")',
     'true', 'negative: the launcher preview does not touch runners that have a builder of their own'),
    ('launcher_panel_personaplex', _REG + ' F({ llamaRemoteEditOverlay: { hidden: false, dataset: {}, querySelector: () => null, querySelectorAll: () => [] },'
     ' "tr-CELL_KIND": { value: "" }, "tr-RUNNER": { value: "personaplex" }, "tr-llamaFields": { style: {} }, "tr-llamaAside": { style: {} },'
     ' "tr-commandAside": { style: {} }, "tr-commandFields": { style: {} }, "tr-vllmFields": { style: {} } });'
     ' try { le.applyCellKindUI("tr-"); } catch (e) {}',
     '(() => { const f = globalThis.__fields; return [f["tr-llamaFields"].style.display, f["tr-llamaAside"].style.display,'
     ' f["tr-commandAside"].style.display, f["tr-commandFields"].style.display, f["tr-vllmFields"].style.display]; })()',
     json.dumps(["none", "none", "", "none", "none"]),
     'a voice runner: llama.cpp\'s flags and estimate are hidden, the command preview is shown, and the custom-command and vLLM panels stay shut — '
     'the registry says it has no llama flags (llamaConfig), no chain of ids was extended for it'),
    ('launcher_panel_llama_keeps_its_flags', _REG + ' F({ llamaRemoteEditOverlay: { hidden: false, dataset: {}, querySelector: () => null, querySelectorAll: () => [] },'
     ' "tr-CELL_KIND": { value: "" }, "tr-RUNNER": { value: "llama-server" }, "tr-llamaFields": { style: {} }, "tr-llamaAside": { style: {} },'
     ' "tr-commandAside": { style: {} } });'
     ' try { le.applyCellKindUI("tr-"); } catch (e) {}',
     '(() => { const f = globalThis.__fields; return [f["tr-llamaFields"].style.display, f["tr-llamaAside"].style.display, f["tr-commandAside"].style.display]; })()',
     json.dumps(["", "", "none"]),
     'negative: llama.cpp keeps its flags and its estimate, and has no command preview'),
    ('launcher_model_folder_rules', _REG,
     '[le.launcherModelFolder({ folderRule: "picked" }, "a/b/c/"), le.launcherModelFolder({ folderRule: "entry" }, "m/o/v/f.gguf"),'
     ' le.launcherModelFolder({ folderRule: "entry" }, "m/f.gguf"), le.launcherModelFolder({ folderRule: "entry" }, "/f.gguf"),'
     ' le.launcherModelFolder({ folderRule: "entry" }, ""), le.launcherModelFolder(null, " x/y ")]',
     json.dumps(["a/b/c", "m/o", "", "", "", "x/y"]),
     'the folder rules: picked is the path itself (no trailing slash), entry is two steps up, and a path with nothing above it has no folder'),
    ('launcher_artifact_kinds', _REG + " st.state.artifacts = " + json.dumps(_VOICE_ROWS) + ";",
     '[' + ", ".join(f'le.artifactKind("{row["path"]}")' for row in _VOICE_ROWS) + ']',
     json.dumps(["personaplex-st", "step-audio2-st", "qwen3-omni-st", "lfm-audio-st", "safetensors"]),
     'a folder of a voice model has the kind of its runner, by the architecture the registry names (stArchs); an ordinary Qwen3 folder stays a safetensors checkpoint'),
] + [
    (f'launcher_tabs_{rid.replace("-", "_")}',
     _REG + ' st.state.artifacts = ' + json.dumps(_VOICE_ROWS) + '; st.state.models = ' + json.dumps(_VOICE_MODELS) + ';'
     ' const wrap = { innerHTML: "" }; F({ llamaRemoteEditOverlay: { hidden: false, dataset: {},'
     ' querySelector: (q) => (q === ".runner-tabs" ? wrap : null), querySelectorAll: () => [] },'
     ' "tr-RUNNER": { value: "' + rid + '" }, "tr-MODEL_FILE": { value: ' + json.dumps(path) + ' } });'
     ' try { le.renderRunnerTabs("tr-"); } catch (e) {} globalThis.__wrap = wrap;',
     _tabs_expr(rid, path), json.dumps(want), note)
    for rid, path, want, note in (
        ("personaplex", "personaplex-7b-v1/nvidia/SAFETENSORS",
         {"personaplex": False, "lfm-audio": True, "step-audio2": True, "qwen3-omni": True, "minicpm-omni": True, "vllm": False, "llama-server": True},
         "PersonaPlex's folder picked: its tab is open; the other voice engines, llama.cpp-omni and llama.cpp are grey (they cannot read a checkpoint folder); vLLM accepts anything"),
        ("qwen3-omni", "Qwen3-Omni-30B-A3B-Instruct-AWQ-4bit/cyankiwi/AWQ",
         {"personaplex": True, "lfm-audio": True, "step-audio2": True, "qwen3-omni": False, "minicpm-omni": True, "vllm": False, "llama-server": True},
         "Qwen3-Omni's folder picked: its tab is open and Step-Audio 2's is grey — one launcher, two recipes, and each folder has ONE"),
        ("lfm-audio", "LFM2.5-Audio-1.5B/LiquidAI/SAFETENSORS",
         {"personaplex": True, "lfm-audio": False, "step-audio2": True, "qwen3-omni": True, "minicpm-omni": True, "vllm": False, "llama-server": True},
         "LFM2.5-Audio's folder (its config.json has no model_type: its architecture is the family): its tab is open, the others grey"),
        ("vllm", "Qwen3-8B/Qwen/BF16",
         {"personaplex": True, "lfm-audio": True, "step-audio2": True, "qwen3-omni": True, "minicpm-omni": True, "vllm": False, "llama-server": True},
         "negative: an ordinary Qwen3 folder opens vLLM and no voice engine, llama.cpp-omni included (it reads a GGUF)"),
        ("llama-server", "MiniCPM-o-4_5-gguf/openbmb/Q4_K_M/MiniCPM-o-4_5-Q4_K_M.gguf",
         {"personaplex": True, "lfm-audio": True, "step-audio2": True, "qwen3-omni": True, "minicpm-omni": False, "vllm": False, "llama-server": False},
         "MiniCPM-o's GGUF picked: llama.cpp and llama.cpp-omni are both open (its main file is a plain qwen3 GGUF, no file claims it), the checkpoint-folder engines are grey"),
    )
] + [
    ('launcher_why_grey', _REG + ' st.state.artifacts = ' + json.dumps(_VOICE_ROWS) + ';'
     ' const { t: tr } = await import(pathToFileURL(process.env.JS_ROOT + "/i18n.js").href);'
     ' const unesc = (x) => x.replace(/&quot;/g, \'"\').replace(/&#39;/g, "\'").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&");'
     ' const wrap = { innerHTML: "" }; F({ llamaRemoteEditOverlay: { hidden: false, dataset: {},'
     ' querySelector: (q) => (q === ".runner-tabs" ? wrap : null), querySelectorAll: () => [] },'
     ' "tr-RUNNER": { value: "personaplex" }, "tr-MODEL_FILE": { value: "personaplex-7b-v1/nvidia/SAFETENSORS" } });'
     ' try { le.renderRunnerTabs("tr-"); } catch (e) {} globalThis.__wrap = wrap; globalThis.__tr = tr; globalThis.__unesc = unesc;',
     '(() => { const h = globalThis.__unesc(globalThis.__wrap.innerHTML); const tr = globalThis.__tr;'
     ' const b = (id) => h.match(new RegExp(`<button[^>]*data-runner="${id}"[^>]*>`))[0];'
     ' return [b("step-audio2").includes(tr("runnerNeedsStepAudio2St")), b("llama-server").includes(tr("runnerNeedsLlmGguf")),'
     ' b("personaplex").includes(tr("runnerNeedsPersonaplexSt")), b("step-audio2").includes(tr("runnerNeedsLlmGguf"))]; })()',
     json.dumps([True, True, False, False]),
     'a grey tab says WHY in its own words (the registry\'s needsKey, no table in the browser): Step-Audio 2 needs its folder, '
     'llama.cpp a GGUF; negative: the open tab says nothing of the kind, and a grey tab does not say another runner\'s reason'),
    ('tip_has_the_registrys_costs', _REG + ' const { t: tr } = await import(pathToFileURL(process.env.JS_ROOT + "/i18n.js").href);'
     ' const unesc = (x) => x.replace(/&quot;/g, \'"\').replace(/&#39;/g, "\'").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&");'
     ' const wrap = { innerHTML: "" }; F({ llamaRemoteEditOverlay: { hidden: false, dataset: {},'
     ' querySelector: (q) => (q === ".runner-tabs" ? wrap : null), querySelectorAll: () => [] }, "tr-RUNNER": { value: "gr00t" } });'
     ' try { le.renderRunnerTabs("tr-"); } catch (e) {} globalThis.__wrap = wrap; globalThis.__tr = tr; globalThis.__unesc = unesc;',
     '(() => { const h = globalThis.__unesc(globalThis.__wrap.innerHTML); const tr = globalThis.__tr;'
     ' const b = (id) => h.match(new RegExp(`<button[^>]*data-runner="${id}"[^>]*>`))[0];'
     ' return [b("gr00t").includes(tr("runnerGr00tMinus")), b("qwen3-omni").includes(tr("runnerQwen3OmniMinus")),'
     ' b("custom").includes(tr("runnerCustomMinus")), b("gr00t").includes(tr("runnerQwen3OmniMinus"))]; })()',
     json.dumps([True, True, True, False]),
     'every tab carries ITS costs in the tip, from the registry: an older runner (whose table moved out of the browser), a new one and custom; '
     'negative: not another runner\'s'),
]

# The voice-clone runner (1.3.611): its preview is held to the line the server builds over the table the program is held to
# (contract/runner_lines.json), and its panel is shown for it alone.

_VC_NOTE = "# the first start makes ~/tts-<engine> and fetches the engine's weights (10–20 minutes)"
for _i, (_name, _cfg, _line) in enumerate((r["name"], r["config"], r["line"]) for r in _LINES if r["runner"] == "voice-clone"):
    PINS.append((f'voice_clone_preview_{_i}', _REG + _launcher_fields("voice-clone", _cfg),
                 'le._buildCommandExecPreview("tr-")',
                 json.dumps("export PORT={{PORT}}\n" + _VC_NOTE + "\nexec " + _line),
                 f"the preview is the line the server builds (VoiceCloneRunner.command): {_name}"))

PINS.append(('voice_clone_engine_loads', '',
             '(() => { const load = (config) => { F({ "tr-TTS_ENGINE": { value: "cosyvoice" } }); try { le.applyConfigToForm(config, "tr-"); } catch (e) {}'
             ' return globalThis.__fields["tr-TTS_ENGINE"].value; };'
             ' return [load({ RUNNER: "voice-clone", TTS_ENGINE: "F5" }), load({ RUNNER: "voice-clone", TTS_ENGINE: "" }), load({ RUNNER: "voice-clone" })]; })()',
             '["f5","xtts","xtts"]',
             "the engine opens as saved, in the select's own case; negative: a config that names none opens on the launcher's "
             "default, not blank and not the engine of the cell opened before"))
_VC_PANELS = ' "tr-CELL_KIND": { value: "" }, "tr-llamaFields": { style: {} }, "tr-voiceCloneFields": { style: {} }, "tr-seamlessFields": { style: {} } });'
PINS += [
    ('voice_clone_panel', _REG + ' F({ llamaRemoteEditOverlay: { hidden: false, dataset: {}, querySelector: () => null, querySelectorAll: () => [] },'
     ' "tr-RUNNER": { value: "voice-clone" },' + _VC_PANELS + ' try { le.applyCellKindUI("tr-"); } catch (e) {}',
     '(() => { const f = globalThis.__fields; return [f["tr-voiceCloneFields"].style.display, f["tr-seamlessFields"].style.display,'
     ' f["tr-llamaFields"].style.display]; })()',
     json.dumps(["", "none", "none"]),
     'the voice-clone tab shows its engine and no other runner\'s panel, and no llama.cpp flags'),
    ('voice_clone_panel_not_for_others', _REG + ' F({ llamaRemoteEditOverlay: { hidden: false, dataset: {}, querySelector: () => null, querySelectorAll: () => [] },'
     ' "tr-RUNNER": { value: "seamless" },' + _VC_PANELS + ' try { le.applyCellKindUI("tr-"); } catch (e) {}',
     '(() => { const f = globalThis.__fields; return [f["tr-voiceCloneFields"].style.display, f["tr-seamlessFields"].style.display]; })()',
     json.dumps(["none", ""]),
     'negative: another runner\'s tab keeps the engine shut'),
]

# The page a cell serves itself (1.3.613): its address is shown for a runner whose registry row says it serves one, and
# opens as the cell saved it — or empty, never as the cell opened before.
PINS.append(('page_url_loads', '',
             '(() => { const load = (config) => { F({ "tr-PAGE_URL": { value: "https://other.example.org" } }); try { le.applyConfigToForm(config, "tr-"); } catch (e) {}'
             ' return globalThis.__fields["tr-PAGE_URL"].value; };'
             ' return [load({ RUNNER: "personaplex", PAGE_URL: " https://personaplex.example.org " }), load({ RUNNER: "personaplex", PAGE_URL: "" }),'
             ' load({ RUNNER: "personaplex" })]; })()',
             '["https://personaplex.example.org","",""]',
             "the page's address opens as the cell saved it, trimmed; negative: a config that names none opens empty — not "
             "the address of the cell opened before, which the next Apply would have kept"))
_PAGE_PANELS = ' "tr-CELL_KIND": { value: "" }, "tr-llamaFields": { style: {} }, "tr-pageFields": { style: {} }, "tr-voiceCloneFields": { style: {} } });'
PINS += [
    ('page_panel', _REG + ' F({ llamaRemoteEditOverlay: { hidden: false, dataset: {}, querySelector: () => null, querySelectorAll: () => [] },'
     ' "tr-RUNNER": { value: "personaplex" },' + _PAGE_PANELS + ' try { le.applyCellKindUI("tr-"); } catch (e) {}',
     '(() => { const f = globalThis.__fields; return [f["tr-pageFields"].style.display, f["tr-voiceCloneFields"].style.display,'
     ' f["tr-llamaFields"].style.display]; })()',
     json.dumps(["", "none", "none"]),
     "PersonaPlex's tab shows where its page is reached — its registry row says it serves one — and no llama.cpp flags"),
    ('page_panel_not_for_others', _REG + ' F({ llamaRemoteEditOverlay: { hidden: false, dataset: {}, querySelector: () => null, querySelectorAll: () => [] },'
     ' "tr-RUNNER": { value: "minicpm-omni" },' + _PAGE_PANELS + ' try { le.applyCellKindUI("tr-"); } catch (e) {}',
     '(() => { const f = globalThis.__fields; return [f["tr-pageFields"].style.display, f["tr-voiceCloneFields"].style.display]; })()',
     json.dumps(["none", "none"]),
     "negative: a runner that serves no page keeps the address shut (MiniCPM-o is talked to in the board's own window)"),
]

# The runner panels as the page has them: each field inside its panel, as index.html draws it — an input with no value
# of its own (its placeholder shows the launcher's default), a list with one option marked selected, a box unticked. The
# fields are made once and live across opens, as the page's own do: a form opened on one cell and then on another.
_PANEL_DOM = (
    'const input = (id) => ({ id, tagName: "INPUT", type: "text", value: "", defaultValue: "" });'
    ' const box = (id) => ({ id, tagName: "INPUT", type: "checkbox", checked: false, defaultChecked: false });'
    ' const select = (id, values, d) => { const el = { id, tagName: "SELECT", type: "select-one",'
    ' options: values.map((v) => ({ value: v, defaultSelected: v === d })), _v: d };'
    ' Object.defineProperty(el, "value", { get() { return this._v; }, set(v) { this._v = this.options.some((o) => o.value === String(v)) ? String(v) : ""; } });'
    ' return el; };'
    ' const panel = (...els) => ({ style: {}, querySelectorAll: () => els });'
    ' const G = { backbone: input("tr-GR00T_BACKBONE"), steps: input("tr-GR00T_DENOISING_STEPS"),'
    ' kv: select("tr-STRATA_KV", ["int8", "q4_0", "k8v4"], "int8"), lang: select("tr-SEAMLESS_TGT_LANG", ["rus", "eng", "deu"], "rus"),'
    ' trust: box("tr-TRUST_REMOTE_CODE") };'
    ' F({ "tr-gr00tFields": panel(G.backbone, G.steps), "tr-strataFields": panel(G.kv), "tr-seamlessFields": panel(G.lang),'
    ' "tr-vllmFields": panel(G.trust), "tr-GR00T_BACKBONE": G.backbone, "tr-GR00T_DENOISING_STEPS": G.steps, "tr-STRATA_KV": G.kv,'
    ' "tr-SEAMLESS_TGT_LANG": G.lang, "tr-TRUST_REMOTE_CODE": G.trust });'
    ' const open = (config) => { try { le.applyConfigToForm(config, "tr-"); } catch (e) {}'
    ' return [G.backbone.value, G.steps.value, G.kv.value, G.lang.value, G.trust.checked]; };'
)
_SAVED = '{ RUNNER: "gr00t", GR00T_BACKBONE: "Cosmos-Reason2-2B/nvidia/BF16", GR00T_DENOISING_STEPS: "8", STRATA_KV: "q4_0", SEAMLESS_TGT_LANG: "eng", TRUST_REMOTE_CODE: "1" }'
PINS += [
    ('panel_fields_open_as_saved', _PANEL_DOM,
     'open(' + _SAVED + ')',
     json.dumps(["Cosmos-Reason2-2B/nvidia/BF16", "8", "q4_0", "eng", True]),
     'positive: a cell opens on its own panel fields, as saved — text, number, a list, a box'),
    ('panel_fields_not_left_from_the_cell_before', _PANEL_DOM,
     '[open(' + _SAVED + '), open({ RUNNER: "gr00t" }), open({ RUNNER: "strata", STRATA_KV: "k8v4" })]',
     json.dumps([["Cosmos-Reason2-2B/nvidia/BF16", "8", "q4_0", "eng", True], ["", "", "int8", "rus", False], ["", "", "k8v4", "rus", False]]),
     "negative: a cell whose config does not name a panel field opens on the field's own default — an input empty (its "
     "placeholder shows the launcher's), a list on its option marked selected, a box unticked — not on what the cell "
     "opened before left in it, which the next Apply saved as its own (a new cell names none of them)"),
    ('panel_box_reads_words', _PANEL_DOM,
     '["1", "true", " Yes ", "ON", "0", "", "no", "false"].map((v) => open({ RUNNER: "vllm", TRUST_REMOTE_CODE: v })[4])',
     json.dumps([True, True, True, True, False, False, False, False]),
     'a box reads "1", "true", "yes", "on" (any case, any spaces) as ticked; negative: "0", "", "no", "false" are not — '
     'a box saved as "0" opened ticked, and the next Apply ran the model\'s own code unasked'),
    ('panel_field_restores_the_markup', '',
     '(() => { const sel = (opts) => { const el = { tagName: "SELECT", type: "select-one", options: opts, _v: "zz" };'
     ' Object.defineProperty(el, "value", { get() { return this._v; }, set(v) { this._v = String(v); } }); return el; };'
     ' const a = sel([{ value: "x", defaultSelected: false }, { value: "y", defaultSelected: true }]);'
     ' const b = sel([{ value: "x", defaultSelected: false }, { value: "y", defaultSelected: false }]);'
     ' const c = sel([]);'
     ' const t = { tagName: "INPUT", type: "text", value: "left", defaultValue: "drawn" };'
     ' const u = { tagName: "TEXTAREA", type: "textarea", value: "left", defaultValue: "" };'
     ' const k = { tagName: "INPUT", type: "checkbox", checked: false, defaultChecked: true };'
     ' for (const el of [a, b, c, t, u, k]) new le.PanelField(el).restore();'
     ' return [a.value, b.value, c.value, t.value, u.value, k.checked]; })()',
     json.dumps(["y", "x", "", "drawn", "", True]),
     "the markup's own default: the option marked selected, else the first, none for a list with none; an input's value "
     "attribute, a textarea's text; a box as drawn"),
]


def main():
    if len(PINS) < 40:
        print(f"js llama-edit FAILED: всего {len(PINS)} пинов — снимок пуст или урезан")
        return 1
    node = find_node()
    if node is None:
        print("js llama-edit: SKIPPED — node не найден ни в PATH, ни у менеджеров версий: " + ", ".join(node_search_paths()))
        return 0
    ids = [p[0] for p in PINS]
    dup = {i for i in ids if ids.count(i) > 1}
    if dup:
        print(f"js llama-edit FAILED: повторяющиеся id пинов: {sorted(dup)}")
        return 1
    def blocks(pins, sink):
        return [f"try {{ reset(); {setup}\n  {sink}[{json.dumps(pid)}] = {expr}; }} catch (e) {{ {sink}[{json.dumps(pid)}] = {{ __threw: String(e && e.message || e) }}; }}"
                for pid, setup, expr, _exp, _msg in pins]
    # Every pin must be independent of its neighbors: that's exactly why
    # reset() sits in front of it. This is proven right here — the whole set
    # is run a SECOND time in reverse order, and the values must match.
    # Without this check a pin can pass because of state left behind by the
    # previous one (this actually happened: two "port not set" pins stayed
    # green only because they ran before the cell was opened).
    probe = (PREAMBLE + "\n".join(blocks(PINS, "out")) + "\nconst rev = {};\n"
             + "\n".join(blocks(list(reversed(PINS)), "rev")).replace("out[", "rev[")
             + "\nconsole.log(JSON.stringify({ out, rev })); process.exit(0);\n")
    harness = ROOT / "scripts" / "_js_harness.mjs"
    probe_path = ROOT / "scripts" / ".probe_js_llama_edit.tmp.mjs"
    probe_path.write_text(probe)
    try:
        env = {**os.environ, "JS_ROOT": str(ROOT / "static" / "js"), "JS_STUBS": STUBS,
               "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8", "TZ": "UTC"}
        run = subprocess.run(
            probe_args(node, harness, probe_path), capture_output=True, text=True, env=env, cwd=ROOT, timeout=120)
    finally:
        probe_path.unlink(missing_ok=True)
    if run.returncode != 0:
        print(run.stdout); print(run.stderr)
        print("js llama-edit FAILED: node вышел с кодом %d" % run.returncode)
        return 1
    both = json.loads(run.stdout.strip().splitlines()[-1])
    got, rev = both["out"], both["rev"]
    for pid, _s, _e, _x, _m in PINS:
        if got.get(pid, "\0missing") != rev.get(pid, "\0missing"):
            _fail.append(f"пин {pid} зависит от порядка: прямой прогон {json.dumps(got.get(pid), ensure_ascii=False)[:120]}, "
                         f"обратный {json.dumps(rev.get(pid), ensure_ascii=False)[:120]}")
    section = ""
    for pid, _setup, _expr, expected, msg in PINS:
        head = pid.split("_", 1)[0]
        if head != section:
            section = head
            print(f"{section}:")
        want = json.loads(expected)
        have = got.get(pid, {"__missing": True})
        ok = have == want
        check(ok, msg if ok else f"{msg}\n        ожидалось {json.dumps(want, ensure_ascii=False)[:300]}\n        получено  {json.dumps(have, ensure_ascii=False)[:300]}")
    print(f"порядок: {len(PINS)} пинов дают те же значения в обратном порядке" if not _fail else "")
    print()
    if _fail:
        print(f"FAILED ({len(_fail)}):")
        for f in _fail:
            print("  - " + f.splitlines()[0])
        return 1
    print(f"js llama-edit OK: настоящий модуль в node, {len(PINS)} пинов редактора ячейки значениями")
    return 0


if __name__ == "__main__":
    sys.exit(main())
