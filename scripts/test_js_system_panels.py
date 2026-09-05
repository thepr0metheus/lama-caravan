#!/usr/bin/env python3
"""Снимок static/js/system-panels.js — панели страницы System.

Что пинится значением. Сводки из state: сервис (фаза, PID, командная строка
через formatCmdline, «нет запущенной команды»), рантайм (модель с запасными
путями, контекст, vision, спекулятивный режим, RAM-строка или её ошибка,
tok/s «сейчас / prev» через tokenSpeedState), CPU/GPU (данные или текст
ошибки). Контроллер: чипы сервисов good/warn, ячейки, git с warn при грязных
файлах, python, диск с warn ниже 50 GB или с ошибкой, модели; в контейнере
кнопка починки user-сервиса убирается. llama.cpp: «upstream новее» решается по
КОММИТУ, когда обе стороны известны, и по номеру сборки — только как запасной
путь; «not checked». Список архивных сборок и панель vLLM (текущая версия
отдельно, история без неё). Безопасность: auth выключен → форма первого
аккаунта; включён → пользователи с ролями, сессии (не больше пяти, +N),
токен флота. Известные проблемы: легаси-проверки сворачиваются в details,
подсказка-как-чинить только когда есть red/amber. Модалы через общий confirm:
поля from/to и путь, `ui.pendingConfirm` делает POST; опрос обновления
llama.cpp — running → через 2 с, done rc=0 → тост и перечитывание, rc≠0 → тост
ошибки. Сборщик мусора моделей: список неиспользуемых по размеру вниз,
«ничего лишнего», удаление только выбранных и только после подтверждения.

DOM — словарь `globalThis.__fields` (элементы с innerHTML/textContent/hidden/
classList/слушателями и разбором innerHTML в кнопки с data-атрибутами).

Запуск: python3 scripts/test_js_system_panels.py
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _node import find_node, node_search_paths  # noqa: E402

STUBS = ("polling,dialogs,topology-nodes,canvas,topology-dnd,topology-render,charts,cables,cloud,history,favorites,"
         "config-locator,onboarding,onboarding-tours,usage-stats,dialog-llamas,models-page,system-page,llama-edit,"
         "remote-cells,topology-modals,routers,topology-activity,topology-proxies,form")

PREAMBLE = r"""
import "./_js_globals.mjs";
import { pathToFileURL } from "node:url";
const st = await import(pathToFileURL(process.env.JS_ROOT + "/state.js").href);
st.setState({ config: {}, paths: { service: "llamacpp-current.service" } });
globalThis.__stubValues = { "polling.tokenSpeedState": { lastTime: null, current: null, previous: null } };
globalThis.__timers = []; globalThis.setTimeout = (fn, ms) => { globalThis.__timers.push(Number(ms) || 0); return 0; }; globalThis.clearTimeout = () => {};
const m = await import(pathToFileURL(process.env.JS_ROOT + "/system-panels.js").href);
const P = await import(pathToFileURL(process.env.JS_ROOT + "/polling.js").href);
const TSS = globalThis.__stubValues["polling.tokenSpeedState"];
const cls = () => { const s = new Set(); return { add: (...c) => c.forEach((x) => s.add(x)), remove: (...c) => c.forEach((x) => s.delete(x)), toggle: (c, on) => (on ? s.add(c) : s.delete(c)), has: (c) => s.has(c), contains: (c) => s.has(c), list: () => [...s].sort() } };
// Элемент словарного DOM: innerHTML разбирается в кнопки с data-атрибутом (restore-build / vllm-update / auth-*), чтобы модуль мог навесить слушатели.
const mkEl = (tag = "div") => { const e = { tag, textContent: "", hidden: false, disabled: false, title: "", classList: cls(), dataset: {}, listeners: {}, events: [], children: [], scrollTop: 0, scrollHeight: 0, value: "",
  addEventListener(t, fn) { (this.listeners[t] ||= []).push(fn); }, dispatchEvent(ev) { this.events.push(ev.type); return true; }, remove() { this.removed = true; }, closest() { return this; },
  querySelectorAll(sel) { const mm = sel.match(/^\[data-([a-z-]+)\]$/); if (!mm) throw new Error("selector not modelled: " + sel); const key = mm[1]; return this.children.filter((c) => key in c.attrs); }, querySelector() { return null; } };
  Object.defineProperty(e, "innerHTML", { get() { return this._html || ""; }, set(v) { this._html = v; this.children = []; for (const idm of v.matchAll(/ id="([A-Za-z0-9_-]+)"/g)) { if (!globalThis.__fields[idm[1]]) globalThis.__fields[idm[1]] = mkEl(); } for (const h of v.matchAll(/data-([a-z-]+)="([^"]*)"/g)) { const b = mkEl("button"); b.attrs = { [h[1]]: h[2] }; b.getAttribute = (k) => (k === "data-" + h[1] ? h[2] : null); b.dataset = { [h[1].replace(/-([a-z])/g, (_, c) => c.toUpperCase())]: h[2] }; this.children.push(b); } } });
  e.attrs = {}; return e; };
const IDS = ["serviceSummary", "cmdline", "runtimeSummary", "cpuSummary", "gpuSummary", "openclawLinksSummary", "controllerInfo", "repairUserServiceBtn", "llamaCppSummary", "llamaUpdateLog", "llamaBuildsList", "vllmSummary", "projectGitBranch", "knownProblems", "securityInfo", "authLogoutBtn", "confirmTitle", "confirmText", "confirmMeta", "confirmPath", "confirmDelete", "confirmOverlay", "modelGcOverlay", "modelGcList", "modelGcSummary", "modelGcSelected", "modelGcDelete", "toast"];
globalThis.__checked = []; document.querySelectorAll = (sel) => (sel === "[data-gc-file]:checked" ? globalThis.__checked : []);
const F = () => globalThis.__fields;
const html = (id) => F()[id].innerHTML;
const toastText = () => F().toast.textContent;
const calls = () => globalThis.__fetchCalls.map((c) => ({ path: c.path, method: c.method, body: c.body === null ? null : JSON.parse(c.body) }));
const polls = () => globalThis.__timers.filter((ms) => ms === 2000);
const settle = async () => { for (let i = 0; i < 3; i++) await new Promise((r) => setImmediate(r)); };
const reset = () => { st.setState({ config: {}, paths: { service: "llamacpp-current.service" }, time: 0 }); st.ui.pendingConfirm = null; TSS.lastTime = null; TSS.current = null; TSS.previous = null;
  globalThis.__fields = Object.fromEntries(IDS.map((id) => [id, mkEl()])); globalThis.__checked = []; globalThis.__timers.length = 0;
  globalThis.__fetchCalls.length = 0; globalThis.__fetchReply = {};
  globalThis.__stubReturns = { "polling.formatTps": P.formatTps, "polling.metricNumber": P.metricNumber, "dialogs.appConfirm": async () => true, "dialogs.settleAppConfirm": () => true, "form.modelsByPath": () => new Map(), "topology-nodes.parseLlamaBuildVersion": (v) => { const n = Number(String(v || "").replace(/\D/g, "")); return n ? { build: n } : null; } }; };
reset();
const out = {};
"""

PINS = [
    # ── сводки ──
    ("service_summary", 'st.setState({ ...st.state, service: { ActiveState: "active", SubState: "running", MainPID: 4242, ExecMainStartTimestamp: "Fri 10:00", cmdline: "llama-server --port 22001 --ctx-size 8192" }, runtime: { status: { phase: "ready", kind: "good", detail: "slots 4" } } });',
     '(() => { m.renderService(); return [html("serviceSummary").includes("<b>4242</b>"), html("serviceSummary").includes("running"), html("serviceSummary").includes("slots 4"), html("serviceSummary").includes("llamacpp-current.service"), F().cmdline.textContent.includes("--port 22001")]; })()',
     '[true,true,true,true,true]', "сервис: PID, подсостояние, деталь фазы, имя юнита, командная строка"),
    ("service_no_command", 'st.setState({ ...st.state, service: {} });', '(() => { m.renderService(); return [F().cmdline.textContent, html("serviceSummary").includes("<b>0</b>")]; })()', '["No running command line.",true]', "negative: без cmdline — подсказка, PID 0"),
    ("service_without_element", 'delete globalThis.__fields.serviceSummary;', '(() => { m.renderService(); return F().cmdline.textContent; })()', '""', "negative: панели нет — ничего не рисуется"),
    ("runtime_summary_fields", 'st.setState({ ...st.state, config: { SPEC_DRAFT_MODEL_FILE: "draft.gguf", SPEC_TYPE: "mtp" }, runtime: { models: { data: [{ id: "qwen3" }] }, props: { default_generation_settings: { n_ctx: 8192 }, modalities: { vision: true } }, status: { phase: "ready", kind: "good" }, metrics: { "llamacpp:prompt_tokens_seconds": "120.5", "llamacpp:predicted_tokens_seconds": "33.333" } }, memory: { error: "no /proc" } });',
     '(() => { m.renderRuntime(); const h = html("runtimeSummary"); return [h.includes("<b>qwen3</b>"), h.includes("<b>8192</b>"), h.includes("Vision: <span class=\\"pill good\\">on</span>") || /Vision:.*good.*on/.test(h), h.includes("draft-mtp"), h.includes("draft.gguf"), h.includes("no /proc"), h.includes("<b>120.5</b>"), h.includes("<b>33.33</b>"), h.includes("prev n/a")]; })()',
     '[true,true,true,true,true,true,true,true,true]', "рантайм: модель, контекст, vision, спекулятивный mtp с файлом, ошибка RAM, tok/s и prev n/a при первом замере"),
    ("runtime_prev_tps_on_next_sample", 'st.setState({ ...st.state, time: 1, runtime: { metrics: { "llamacpp:prompt_tokens_seconds": 10, "llamacpp:predicted_tokens_seconds": 20 } } });',
     '(() => { m.renderRuntime(); st.setState({ ...st.state, time: 2, runtime: { metrics: { "llamacpp:prompt_tokens_seconds": 30, "llamacpp:predicted_tokens_seconds": 40 } } }); m.renderRuntime(); const h = html("runtimeSummary"); m.renderRuntime(); return [h.includes("<b>30.00</b> <span>prev 10.00</span>"), h.includes("<b>40.00</b> <span>prev 20.00</span>"), html("runtimeSummary").includes("prev 10.00")]; })()',
     '[true,true,true]', "второй замер по времени сдвигает prev; повторный рендер того же времени не сдвигает"),
    ("runtime_fallbacks", 'st.setState({ ...st.state, runtime: { models: { models: [{ name: "ollama-name" }] } }, memory: { ok: true, usedMiB: 1024, availableMiB: 2048, totalMiB: 4096 } });',
     '(() => { m.renderRuntime(); const h = html("runtimeSummary"); return [h.includes("<b>ollama-name</b>"), h.includes("<b>n/a</b>"), h.includes("Speculative: <span class=\\"pill\\">off</span>") || /Speculative:.*off/.test(h), h.includes("RAM:")]; })()',
     '[true,true,true,true]', "запасные пути: имя модели из ollama-формы, контекст n/a, спекулятивный off, RAM-строка при ok"),
    ("cpu_ok_and_error", '', '(() => { st.setState({ ...st.state, cpu: { ok: true, model: "Ryzen", usagePct: 12, load1: 1, load5: 2, load15: 3, physicalCores: 8, logicalCores: 16 } }); m.renderCpu(); const a = html("cpuSummary"); st.setState({ ...st.state, cpu: { ok: false } }); m.renderCpu(); return [a.includes("<b>Ryzen</b>"), a.includes("<b>12%</b>"), a.includes("<b>1</b> / 2 / 3"), a.includes("<b>8</b> physical, <b>16</b> logical"), html("cpuSummary")]; })()',
     '[true,true,true,true,"<div>No CPU data</div>"]', "CPU: модель, загрузка, load, ядра; без данных — подсказка"),
    ("gpu_rows_and_error", '', '(() => { st.setState({ ...st.state, gpu: { ok: true, gpus: [{ name: "RTX", memoryUsedMiB: 1024, memoryFreeMiB: 2048, utilizationGpuPct: 55, temperatureC: 60, powerDrawW: 200, pcieGenCurrent: 4, pcieWidthCurrent: 16, pcieGenMax: 5, pcieWidthMax: 16 }, { name: "B" }] } }); m.renderGpu(); const a = html("gpuSummary"); st.setState({ ...st.state, gpu: { ok: true, gpus: [] } }); m.renderGpu(); return [(a.match(/<div><b>/g) || []).length, a.includes("<b>55%</b>"), a.includes("<b>Gen4 x16</b> / Gen5 x16"), a.includes("<b>n/a GB/s</b>"), html("gpuSummary")]; })()',
     '[2,true,true,true,"<div>No GPU data</div>"]', "GPU: блок на карту, util, PCIe; неизвестная пропускная — n/a; пустой список — подсказка"),
    ("openclaw_links", 'st.setState({ ...st.state, openclawConfigManagers: { targets: [{ name: "a", url: "http://a" }, { name: "b", url: "http://b" }, { name: "c", url: "http://c" }], lastNotify: { modelHint: "gpt", results: [{ name: "a", ok: true, response: { status: "200" } }, { name: "b", ok: false, error: "refused" }] } } });',
     '(() => { m.renderOpenClawLinks(); const h = html("openclawLinksSummary"); return [h.includes(">connected<") && h.includes("<b>a</b>"), h.includes(">error<") && h.includes("refused"), h.includes(">configured<") && h.includes("<b>c</b>"), h.includes("Last model: gpt")]; })()',
     '[true,true,true,true]', "менеджеры openclaw: connected/error по результату, configured без него, подсказка модели"),
    ("openclaw_links_none", '', '(() => { m.renderOpenClawLinks(); return html("openclawLinksSummary").includes("not configured"); })()', 'true', "negative: без целей — «not configured»"),
    # ── контроллер ──
    ("controller_info_chips", '', '(() => { m.renderControllerInfo({ services: [{ unit: "caravan.service", ok: true, active: "active", sub: "running", pid: "77" }, { unit: "proxies.service", ok: false }], cells: { running: 3, total: 5 }, projectGit: { branch: "main", head: "abc1234", dirtyCount: 2 }, python: "3.12", disk: { path: "/models", totalGb: 900, freeGb: 20 }, models: { count: 12, totalGb: 340 } }); const h = html("controllerInfo"); return [h.includes("llama-chip good\\"><span>caravan.service</span><strong>active / running · PID 77"), h.includes("llama-chip warn\\"><span>proxies.service</span><strong>n/a"), h.includes("<strong>3 / 5</strong>"), h.includes("llama-chip warn\\"><span>app git</span><strong>main @ abc1234"), h.includes("<strong>3.12</strong>"), h.includes("llama-chip warn\\"><span>models disk</span><strong>20 GB free / 900 GB"), h.includes("<strong>12 · 340 GB</strong>"), F().repairUserServiceBtn.removed]; })()',
     '[true,true,true,true,true,true,true,null]', "чипы контроллера: сервис good с PID и warn без данных, ячейки, git warn при грязных файлах, python, диск warn ниже 50 GB, модели; кнопка починки на месте"),
    ("controller_info_container_and_disk_error", '', '(() => { m.renderControllerInfo({ container: true, projectGit: {}, disk: { path: "/models", error: "not mounted" } }); const h = html("controllerInfo"); return [F().repairUserServiceBtn.removed, h.includes("llama-chip warn\\"><span>models disk</span><strong>/models: not mounted"), h.includes("llama-chip good\\"><span>app git</span><strong>n/a</strong>"), h.includes("server cells")]; })()',
     '[true,true,true,false]', "контейнер: кнопка починки user-сервиса убрана; диск с ошибкой — warn; без ячеек чипа нет"),
    ("controller_info_missing", '', '(() => { m.renderControllerInfo(null); return html("controllerInfo"); })()', '""', "negative: без данных — ничего"),
    # ── llama.cpp ──
    ("llamacpp_upstream_newer_by_commit", 'st.setState({ ...st.state, llamaCpp: { binary: "/opt/llama-server", version: "version: 9947 (abc)", git: { head: "abc1234", branch: "master", upstreamChecked: true, upstreamHead: "def5678", upstreamBuild: 9900, upstreamBuildCommit: "def5678", dirtyCount: 0, trackedDirtyCount: 0 }, supportsChatTemplateFile: true } });',
     '(() => { m.renderLlamaCpp(); const h = html("llamaCppSummary"); return [h.includes("llama-chip warn\\"><span>upstream build</span><strong>b9900"), h.includes("<strong>abc1234</strong>"), h.includes("<strong>def5678</strong>"), h.includes("llama-chip good\\"><span>Tracked dirty</span><strong>0"), F().llamaUpdateLog.textContent, calls().map((c) => c.path)]; })()',
     '[true,true,true,true,"version: 9947 (abc)",["/api/llamacpp/builds","/api/vllm"]]',
     "upstream новее решается по КОММИТУ: локальный номер сборки больше, но коммит другой — warn; лог обновления показывает версию; тянутся сборки и vLLM"),
    ("llamacpp_same_commit_is_good", 'st.setState({ ...st.state, llamaCpp: { version: "version: 9947 (abc)", git: { head: "abc1234", upstreamChecked: true, upstreamBuild: 9947, upstreamBuildCommit: "abc12", trackedDirtyCount: 1 } } });',
     '(() => { m.renderLlamaCpp(); const h = html("llamaCppSummary"); return [h.includes("llama-chip good\\"><span>upstream build</span><strong>b9947"), h.includes("llama-chip warn\\"><span>Tracked dirty</span><strong>1")]; })()',
     '[true,true]', "тот же коммит (по префиксу) — good; грязные отслеживаемые файлы — warn"),
    ("llamacpp_number_fallback_and_not_checked", '', '(() => { st.setState({ ...st.state, llamaCpp: { version: "version: 9900", git: { upstreamChecked: true, upstreamBuild: 9947 } } }); m.renderLlamaCpp(); const a = html("llamaCppSummary").includes("llama-chip warn\\"><span>upstream build</span><strong>b9947"); st.setState({ ...st.state, llamaCpp: { git: {} } }); m.renderLlamaCpp(); const h = html("llamaCppSummary"); return [a, h.includes("<strong>not checked</strong>"), h.includes("llama-chip \\"><span>upstream build</span><strong>not checked")]; })()',
     '[true,true,true]', "без коммитов — сравнение номеров сборок; без проверки — «not checked» без окраски"),
    ("llama_builds_list", 'globalThis.__fetchReply["/api/llamacpp/builds"] = { builds: [{ id: "b1", version: "version: 9947 (abc)", builtAt: 1700000000, sizeMb: 120 }, { id: "b2", commit: "def" }] };',
     'await (async () => { await m.loadLlamaBuilds(); const h = html("llamaBuildsList"); return [(h.match(/llama-build-row/g) || []).length, h.includes("llama-build-ver\\">b9947 (abc)"), h.includes("120 MB"), h.includes(\'data-restore-build="b2"\'), F().llamaBuildsList.children.length, !!F().llamaBuildsList.children[0].listeners.click]; })()',
     '[2,true,true,true,2,true]', "архив сборок: строка на сборку с версией и размером, кнопка Restore привязана"),
    ("llama_builds_empty_and_error", '', 'await (async () => { globalThis.__fetchReply["/api/llamacpp/builds"] = { builds: [] }; await m.loadLlamaBuilds(); const a = html("llamaBuildsList").includes("No archived builds yet"); globalThis.__fetchReply["/api/llamacpp/builds"] = { __status: 500, error: "boom" }; await m.loadLlamaBuilds(); return [a, F().llamaBuildsList.textContent]; })()',
     '[true,"boom"]', "negative: пустой архив — подсказка; отказ — текст ошибки"),
    ("vllm_panel_installed", 'globalThis.__fetchReply["/api/vllm"] = { installed: true, version: "0.24.0", venv: "/opt/vllm", history: [{ version: "0.24.0" }, { version: "0.23.1", seenAt: 1700000000 }] };',
     'await (async () => { await m.loadVllmPanel(); const h = html("vllmSummary"); return [(h.match(/llama-build-row/g) || []).length, h.includes("vllm 0.24.0"), h.includes("/opt/vllm"), h.includes(">Update to latest<"), h.includes(\'data-vllm-update="0.23.1"\'), h.includes(\'data-vllm-update="0.24.0"\')]; })()',
     '[2,true,true,true,true,false]', "vLLM: текущая версия отдельной строкой с «Update to latest», история без текущей, у прошлых — Restore"),
    ("vllm_panel_not_installed", 'globalThis.__fetchReply["/api/vllm"] = { installed: false, pinnedDefault: "0.24.0", history: [] };', 'await (async () => { await m.loadVllmPanel(); return html("vllmSummary").includes("pinned to 0.24.0"); })()', 'true', "negative: не установлен — подсказка с пином провижининга"),
    ("vllm_update_modal_and_post", 'globalThis.__fetchReply["/api/vllm"] = { installed: true, version: "0.24.0", history: [{ version: "0.23.1" }] }; globalThis.__fetchReply["/api/llamacpp/update-status"] = { running: true, lines: ["pip…"] };',
     'await (async () => { await m.loadVllmPanel(); F().vllmSummary.children[1].listeners.click[0](); const a = [F().confirmPath.textContent, F().confirmDelete.textContent, F().confirmMeta.innerHTML.includes("<strong>vllm 0.24.0</strong>"), F().confirmMeta.innerHTML.includes("<strong>vllm 0.23.1</strong>"), F().confirmOverlay.hidden]; await st.ui.pendingConfirm(); await settle(); return [...a, calls().slice(1).map((c) => [c.path, c.body]), F().llamaUpdateLog.textContent, polls()]; })()',
     '["pip install vllm==0.23.1","Restore",true,true,false,[["/api/vllm/update",{"version":"0.23.1"}],["/api/llamacpp/update-status",null]],"pip…",[2000]]',
     "откат vLLM: модал с командой pip и from/to; подтверждение — POST версии и опрос статуса, running → следующий опрос через 2 с"),
    # ── модалы llama.cpp ──
    ("restore_build_modal", 'st.setState({ ...st.state, llamaCpp: { version: "version: 9947 (abc)\\nextra" } }); globalThis.__fetchReply["/api/llamacpp/update-status"] = { done: true, rc: 1, error: "build failed" };',
     'await (async () => { m.openRestoreBuildModal("b2", { version: "version: 9900 (def)" }); const a = [F().confirmTitle.textContent, F().confirmMeta.innerHTML.includes("<strong>b9947 (abc)</strong>"), F().confirmMeta.innerHTML.includes("<strong>b9900 (def)</strong>"), F().confirmPath.textContent, F().confirmOverlay.hidden]; await st.ui.pendingConfirm(); await settle(); return [...a, calls().map((c) => [c.path, c.body]), toastText(), polls()]; })()',
     '["Restore an archived build?",true,true,"b2",false,[["/api/llamacpp/restore",{"id":"b2"}],["/api/llamacpp/update-status",null]],"build failed",[]]',
     "восстановление сборки: from/to из версий, POST id; статус done с rc≠0 — тост ошибки, опроса дальше нет"),
    ("update_modal_success_path", 'st.setState({ ...st.state, llamaCpp: { binary: "/opt/llama-server", git: { branch: "master", head: "abc", trackedDirtyCount: 0 } } }); globalThis.__fetchReply["/api/llamacpp/update-status"] = { done: true, rc: 0, lines: ["ok"] }; globalThis.__fetchReply["/api/llamacpp"] = { version: "version: 9950" }; globalThis.__fetchReply["/api/llamacpp/builds"] = { builds: [] }; globalThis.__fetchReply["/api/vllm"] = { installed: false, history: [] };',
     'await (async () => { m.openUpdateLlamaModal(); const a = [F().confirmTitle.textContent, F().confirmMeta.innerHTML.includes("<strong>master</strong>"), F().confirmPath.textContent]; await st.ui.pendingConfirm(); await settle(); const paths = calls().map((c) => c.path); return [...a, paths.slice(0, 3), paths.filter((x) => x === "/api/llamacpp/builds").length, paths.filter((x) => x === "/api/vllm").length, paths.length, st.state.llamaCpp.version, F().llamaUpdateLog.textContent]; })()',
     '["Update llama.cpp build?",true,"/opt/llama-server",["/api/llamacpp/update","/api/llamacpp/update-status","/api/llamacpp"],2,2,7,"version: 9950","version: 9950"]',
     "обновление: POST, статус done rc=0 → перечитаны llama.cpp, архив и vLLM (as-is: архив и vLLM перечитываются дважды — из renderLlamaCpp и из опроса); лог после перечитывания показывает новую версию (строки джобы перекрыты — as-is)"),
    ("update_post_failure", 'globalThis.__fetchReply["/api/llamacpp/update"] = { __status: 409, error: "job running" };', 'await (async () => { m.openUpdateLlamaModal(); await st.ui.pendingConfirm(); await settle(); return [calls().map((c) => c.path), F().llamaUpdateLog.textContent, toastText()]; })()',
     '[["/api/llamacpp/update"],"job running","job running"]', "negative: отказ старта обновления — ошибка в логе и в тосте, опроса нет"),
    ("repair_user_service_modal", 'st.setState({ ...st.state, service: { MainPID: 0 } }); globalThis.__fetchReply["/api/repair/user-service"] = { state: { config: {}, paths: { service: "x.service" }, service: { MainPID: 9 } } };',
     'await (async () => { m.openRepairUserServiceModal(); const a = [F().confirmTitle.textContent, F().confirmMeta.innerHTML.includes("<strong>llamacpp-current.service</strong>"), F().confirmPath.textContent]; await st.ui.pendingConfirm(); await settle(); return [...a, calls()[0].path, st.state.service.MainPID, toastText()]; })()',
     '["Repair user service?",true,"llamacpp-current.service","/api/repair/user-service",9,"User service repaired."]', "починка user-сервиса: модал с юнитом, POST, новое состояние применено, тост"),
    ("revert_latest_confirm_gate", 'globalThis.__fetchReply["/api/revert"] = { state: { config: {}, paths: { service: "s" }, appVersion: "9" } };',
     'await (async () => { globalThis.__stubReturns["dialogs.appConfirm"] = async () => false; await m.revertLatest(); const a = calls().length; globalThis.__stubReturns["dialogs.appConfirm"] = async () => true; await m.revertLatest(); return [a, calls()[0].path, calls()[0].body, st.state.appVersion, toastText()]; })()',
     '[0,"/api/revert",{"restart":true},"9","Reverted latest backup and restarted."]', "откат бэкапа: без подтверждения — ничего; с ним — POST restart, состояние, тост"),
    ("check_llamacpp", 'globalThis.__fetchReply["/api/llamacpp"] = { version: "version: 1" };', 'await (async () => { await m.checkLlamaCpp(); return [st.state.llamaCpp.version, toastText(), F().llamaUpdateLog.textContent]; })()', '["version: 1","Reloaded.","version: 1"]', "проверка версии: GET, состояние, панель перерисована, тост"),
    # ── git-бейдж и известные проблемы ──
    ("project_git_branch", '', '(() => { st.setState({ ...st.state, appVersion: "1.3.200", projectGit: { branch: "main", head: "abc", dirtyCount: 2 } }); m.renderProjectGitBranch(); const a = [F().projectGitBranch.textContent, F().projectGitBranch.title, F().projectGitBranch.classList.has("dirty")]; st.setState({ ...st.state, appVersion: "", projectGit: { ok: false, error: "no git" } }); m.renderProjectGitBranch(); return [...a, F().projectGitBranch.textContent, F().projectGitBranch.title, F().projectGitBranch.classList.has("dirty")]; })()',
     '["v1.3.200 · git: main +2","Project branch main @ abc, 2 dirty files",true,"git: n/a","Project git branch unavailable: no git",false]', "бейдж git: версия, ветка, счётчик грязных с классом; недоступен — причина в подсказке"),
    ("known_problems_healthy_collapses_legacy", 'st.setState({ ...st.state, diagnostics: { summary: "S", fix: "F", checks: [{ kind: "good", title: "proxy", detail: "ok" }, { kind: "bad", title: "Legacy unit", detail: "inactive" }] } });',
     '(() => { m.renderKnownProblems(); const h = html("knownProblems"); return [h.includes("diagnostic-row good"), h.includes("<details class=\\"legacy-details\\">"), h.includes("diagnostic-row bad"), h.includes("<p>S</p>")]; })()',
     '[true,true,true,false]', "всё зелёное: легаси-проверки свёрнуты в details, подсказки-как-чинить нет"),
    ("known_problems_unhealthy_shows_advice", 'st.setState({ ...st.state, diagnostics: { legacyActive: true, summary: "S", fix: "F", checks: [{ kind: "warn", title: "proxy", detail: "slow" }] } });',
     '(() => { m.renderKnownProblems(); const h = html("knownProblems"); return [h.includes("<p>S</p><p>F</p>"), h.includes("<details"), h.includes("problem-item")]; })()',
     '[true,false,true]', "есть amber: подсказка показана; легаси активен — статья без сворачивания"),
    # ── безопасность ──
    ("security_auth_off_setup_form", '', '(() => { m.renderSecurity({ enabled: false }); const h = html("securityInfo"); return [F().authLogoutBtn.hidden, h.includes("Accounts are off"), h.includes(\'id="authSetupForm"\'), h.includes(\'autocomplete="new-password"\')]; })()',
     '[true,true,true,true]', "auth выключен: форма первого аккаунта, кнопка выхода спрятана, пароль без автозаполнения менеджером"),
    ("security_auth_on_users_and_sessions", '', '(() => { m.renderSecurity({ enabled: true, user: "admin", users: [{ username: "admin", role: "admin" }, { username: "bob", role: "viewer" }], sessions: Array.from({ length: 7 }, (_, i) => ({ id: "s" + i, username: "admin", ip: "10.0.0." + i, lastSeen: 1700000000 })) }); const h = html("securityInfo"); return [F().authLogoutBtn.hidden, h.includes("sign-in required · admin"), h.includes(\'data-auth-role="admin:viewer"\'), h.includes(\'data-auth-role="bob:admin"\'), (h.match(/data-auth-revoke=/g) || []).length, h.includes("<p class=\\"muted\\">+2</p>"), h.includes(\'data-auth-del="bob"\')]; })()',
     '[false,true,true,true,5,true,true]', "auth включён: статус с именем, переключение роли в противоположную, сессии не больше пяти и +N, удаление пользователя"),
    ("security_null", '', '(() => { m.renderSecurity(null); return html("securityInfo"); })()', '""', "negative: без данных — ничего"),
    # ── сборщик мусора моделей ──
    ("gc_modal_lists_unused_by_size", 'globalThis.__fetchReply["/api/models/unused"] = { path: "/models", unusedCount: 2, unusedGb: 3.5, files: [{ path: "/models/a.gguf", sizeBytes: 100, sizeGb: 0.1, ageDays: 3, referenced: false }, { path: "/models/big.gguf", sizeBytes: 900, sizeGb: 0.9, ageDays: 30, referenced: false }, { path: "/models/used.gguf", sizeBytes: 999, referenced: true }] };',
     'await (async () => { await m.openModelGcModal(); const h = html("modelGcList"); return [F().modelGcOverlay.hidden, F().modelGcSummary.textContent, h.indexOf("big.gguf") < h.indexOf("a.gguf"), h.includes("used.gguf"), (h.match(/data-gc-file=/g) || []).length]; })()',
     '[false,"/models — 2 unused files, 3.5 GB reclaimable",true,false,2]', "сборщик: только неиспользуемые, крупные первыми, сводка по пути"),
    ("gc_modal_nothing_and_error", '', 'await (async () => { globalThis.__fetchReply["/api/models/unused"] = { path: "/m", unusedCount: 0, unusedGb: 0, files: [] }; await m.openModelGcModal(); const a = html("modelGcList").includes("Nothing unused"); globalThis.__fetchReply["/api/models/unused"] = { __status: 500, error: "scan failed" }; await m.openModelGcModal(); return [a, html("modelGcList").includes("scan failed")]; })()',
     '[true,true]', "negative: ничего лишнего — подсказка; отказ — текст ошибки"),
    ("gc_delete_only_selected_after_confirm", 'globalThis.__fetchReply["/api/models/gc"] = { freedGb: 1.2 }; globalThis.__fetchReply["/api/models/unused"] = { path: "/m", unusedCount: 0, unusedGb: 0, files: [] };',
     'await (async () => { m.bindModelGc(); const del = F().modelGcDelete.listeners.click[0]; await del(); const none = calls().length; globalThis.__checked = [{ dataset: { gcFile: "/models/big.gguf", gcSize: "900" } }]; globalThis.__stubReturns["dialogs.appConfirm"] = async () => false; await del(); const refused = calls().length; globalThis.__stubReturns["dialogs.appConfirm"] = async () => true; await del(); await settle(); return [none, refused, calls()[0].path, calls()[0].body, toastText(), F().modelGcDelete.disabled]; })()',
     '[0,0,"/api/models/gc",{"files":["/models/big.gguf"]},"1.2 GB freed",false]', "удаление: ничего не выбрано — ничего; отказ подтверждения — ничего; иначе POST выбранных, тост, кнопка разблокирована"),
]


_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def main():
    if len(PINS) < 30:
        print(f"js system-panels FAILED: всего {len(PINS)} пинов — снимок урезан")
        return 1
    node = find_node()
    if node is None:
        print("js system-panels: SKIPPED — node не найден: " + ", ".join(node_search_paths()))
        return 0

    def blocks(pins, sink):
        return [f"try {{ reset(); {setup}\n  {sink}[{json.dumps(pid)}] = {expr}; }} "
                f"catch (e) {{ {sink}[{json.dumps(pid)}] = {{ __threw: String(e && e.message || e) }}; }}"
                for pid, setup, expr, _exp, _msg in pins]

    # Пины не опираются друг на друга: тот же набор в обратном порядке обязан
    # дать те же значения.
    probe = (PREAMBLE + "\n".join(blocks(PINS, "out")) + "\nconst rev = {};\n"
             + "\n".join(blocks(list(reversed(PINS)), "rev"))
             + "\nconsole.log(JSON.stringify({ out, rev })); process.exit(0);\n")
    harness = ROOT / "scripts" / "_js_harness.mjs"
    path = ROOT / "scripts" / ".probe_js_system_panels.tmp.mjs"
    path.write_text(probe)
    try:
        env = {**os.environ, "JS_ROOT": str(ROOT / "static" / "js"), "JS_STUBS": STUBS,
               "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8", "TZ": "UTC"}
        run = subprocess.run(
            [node, "--import",
             f"data:text/javascript,import {{ register }} from 'node:module'; register('{harness.as_uri()}');",
             str(path)], capture_output=True, text=True, env=env, cwd=ROOT, timeout=120)
    finally:
        path.unlink(missing_ok=True)
    if run.returncode != 0:
        print(run.stdout); print(run.stderr)
        print(f"js system-panels FAILED: node вышел с кодом {run.returncode}")
        return 1
    both = json.loads(run.stdout.strip().splitlines()[-1])
    got, rev = both["out"], both["rev"]
    print("панели System: сводки, безопасность, сборки, модалы починки:")
    for pid, _s, _e, expected, msg in PINS:
        want, have = json.loads(expected), got.get(pid, "\0missing")
        check(have == want, msg if have == want else
              f"{msg}\n        ожидалось {json.dumps(want, ensure_ascii=False)[:200]}"
              f"\n        получено  {json.dumps(have, ensure_ascii=False)[:200]}")
        if have != rev.get(pid, "\0missing"):
            _fail.append(f"пин {pid} зависит от порядка")
    print(f"порядок: {len(PINS)} пинов дают те же значения в обратном порядке" if not _fail else "")
    print()
    if _fail:
        print(f"FAILED ({len(_fail)}):")
        for m in _fail:
            print("  - " + m.splitlines()[0])
        return 1
    print(f"js system-panels OK: настоящий модуль в node, {len(PINS)} пинов панелей значениями")
    return 0


if __name__ == "__main__":
    sys.exit(main())
