#!/usr/bin/env python3
"""Snapshot of static/js/topology-render.js — what makes the board redraw.

The board decides to redraw based on a structural FINGERPRINT: as long as it
hasn't changed, a cheap in-place edit runs instead. That means anything
missing from the fingerprint doesn't appear on the board until the page
reloads — and looks exactly like "didn't save".

That's exactly what happened: an agent created by hand landed in the record
and didn't show up until the page was reloaded. The fingerprint counted a
client's ASSIGNMENTS and didn't count its agents. The context-window chip
failed to update for the same reason.

This module had never been loaded by a single snapshot until now — it's
stubbed out in every harness. That's also how syntax that `node --check`
doesn't catch shipped to production inside it. Now it's loaded for real.

Run: python3 scripts/test_js_topology_render.py
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _node import find_node, node_search_paths  # noqa: E402

STUBS = ("topology-modals,cables,routers,charts,cloud,history,dialogs,"
         "llama-edit,form,favorites,config-locator,system-panels,onboarding,topology-dnd,canvas,"
         "usage-stats,dialog-llamas,models-page,system-page,onboarding-tours,memory,command-preview,model-meta,"
         "polling,charts,hf,models,settings,auth,onboarding-strings")

PREAMBLE = r"""
import "./_js_globals.mjs";
import { pathToFileURL } from "node:url";
const st = await import(pathToFileURL(process.env.JS_ROOT + "/state.js").href);
st.setState({ config: {} });
st.setTopology({ proxies: [], clients: [], routers: [], assignments: {} });
Date.now = () => 1_700_000_100_000;
// No drag is under way: a stubbed non-function export is a (truthy) stub, and
// topologyInteractionActive() read every board as mid-drag.
globalThis.__stubValues = { ...(globalThis.__stubValues || {}),
  "topology-dnd.topologyPointerDrag": null, "canvas._cvDrag": null };
const m = await import(pathToFileURL(process.env.JS_ROOT + "/topology-render.js").href);
const reset = () => { st.setState({ config: {} });
  st.setTopology({ proxies: [], clients: [], routers: [], assignments: {} }); };
const CLIENT = (extra = {}) => ({ id: "c1", name: "C", state: "stale", gpus: [], ...extra });
const ROW = (routes) => ({ c1: { assignments: [{ agentId: "a1", routes }] } });
const out = {};
"""

PINS = [
    ("phase_default_is_stopped_for_any_cell",
     '',
     '[m.topologyServerPhase({}), m.topologyServerPhase({ isController: true }), m.topologyServerPhase({ status: { phase: "loading" } }), m.topologyServerPhase({ phase: "running", status: { phase: "loading" } })]',
     '["stopped","stopped","loading","running"]',
     "фаза ячейки без поля — «stopped», и для флага isController тоже (раньше ячейка контроллера без фазы считалась работающей; её нет с шага 6.9); status.phase — запасной, собственная фаза важнее"),
    ("fingerprint_sees_a_new_agent",
     'st.setTopology({ ...st.topology, clients: [CLIENT({ agents: [] })] });'
     ' globalThis.__fp0 = m.topologyStructureFingerprint();'
     ' st.setTopology({ ...st.topology, clients: [CLIENT({ agents: [{ id: "a1" }] })] });',
     'm.topologyStructureFingerprint() !== globalThis.__fp0',
     'true',
     "defect-history: агент, заведённый руками, ложился в запись и не показывался до перезагрузки"),
    ("fingerprint_sees_a_driver_warning",
     'const W = (w) => ({ id: "h1", online: true, scoutVersion: "2.19.0", driverWarnings: w });'
     ' st.setTopology({ ...st.topology, nodes: [W([])] }); globalThis.__fpd0 = m.topologyStructureFingerprint();'
     ' st.setTopology({ ...st.topology, nodes: [W([{ kind: "nextBootNoDriver", reason: "missing", kernel: "7.0.0-35-generic" }])] });'
     ' globalThis.__fpd1 = m.topologyStructureFingerprint();'
     ' st.setTopology({ ...st.topology, nodes: [W([{ kind: "nextBootNoDriver", reason: "missing", kernel: "7.0.0-35-generic" }])] });'
     ' globalThis.__fpd2 = m.topologyStructureFingerprint();'
     ' st.setTopology({ ...st.topology, nodes: [W([{ kind: "rebootForDriver", installed: "2.0", loaded: "1.0" }])] });',
     '[globalThis.__fpd1 !== globalThis.__fpd0, globalThis.__fpd2 === globalThis.__fpd1, m.topologyStructureFingerprint() !== globalThis.__fpd1]',
     '[true, true, true]',
     "предупреждение о драйвере появилось или сменилось — карточка перерисовывается; negative: то же самое на следующем "
     "опросе — не перерисовывается"),
    ("fingerprint_sees_a_changed_window",
     'st.setTopology({ ...st.topology, clients: [CLIENT({ agents: [{ id: "a1" }] })],'
     ' assignments: ROW([{ role: "primary", proxyId: "skynet:proxy:23001", endpoint: "e" }]) });'
     ' globalThis.__fp1 = m.topologyStructureFingerprint();'
     ' st.setTopology({ ...st.topology, assignments: ROW([{ role: "primary", proxyId: "skynet:proxy:23001",'
     ' endpoint: "e", contextLength: 8192 }]) });',
     'm.topologyStructureFingerprint() !== globalThis.__fp1',
     'true',
     "defect-history: чип окна контекста не перерисовывался — настройки в отпечатке не было"),
    ("fingerprint_sees_the_switch",
     'st.setTopology({ ...st.topology, clients: [CLIENT({ agents: [{ id: "a1" }] })],'
     ' assignments: ROW([{ role: "primary", proxyId: "skynet:proxy:23001", endpoint: "e" }]) });'
     ' globalThis.__fp2 = m.topologyStructureFingerprint();'
     ' st.setTopology({ ...st.topology, assignments: ROW([{ role: "primary", proxyId: "skynet:proxy:23001",'
     ' endpoint: "e", contextAuto: true }]) });',
     'm.topologyStructureFingerprint() !== globalThis.__fp2',
     'true',
     "boundary: галка «от модели» — тоже изменение, которое обязано доехать до глаз"),
    ("fingerprint_sees_a_changed_name",
     'st.setTopology({ ...st.topology, clients: [CLIENT({ agents: [{ id: "a1" }] })],'
     ' assignments: ROW([{ role: "primary", proxyId: "skynet:proxy:23001", endpoint: "e" }]) });'
     ' globalThis.__fpN = m.topologyStructureFingerprint();'
     ' st.setTopology({ ...st.topology, assignments: ROW([{ role: "primary", proxyId: "skynet:proxy:23001",'
     ' endpoint: "e", modelName: "main-model" }]) });',
     'm.topologyStructureFingerprint() !== globalThis.__fpN',
     'true',
     "defect-history: имя, под которым порт объявляет модель, в отпечатке не стояло — сохранённое имя доска показывала только после перезагрузки"),
    ("fingerprint_sees_the_lock",
     'st.setTopology({ ...st.topology, clients: [CLIENT({ agents: [{ id: "a1" }] })],'
     ' assignments: ROW([{ role: "primary", proxyId: "skynet:proxy:23001", endpoint: "e",'
     ' modelName: "main-model" }]) });'
     ' globalThis.__fpL = m.topologyStructureFingerprint();'
     ' st.setTopology({ ...st.topology, assignments: ROW([{ role: "primary", proxyId: "skynet:proxy:23001",'
     ' endpoint: "e", modelName: "main-model", modelNameAuto: true }]) });',
     'm.topologyStructureFingerprint() !== globalThis.__fpL',
     'true',
     "boundary: замок у имени — то же самое изменение записи, и оно обязано доехать до глаз без перезагрузки"),
    ("fingerprint_sees_a_port_join_a_kanban",
     'st.setTopology({ ...st.topology, proxies: [{ id: "skynet:proxy:23010", port: 23010, label: "alpha", routerId: "" }] });'
     ' globalThis.__fpR0 = m.topologyStructureFingerprint();'
     ' st.setTopology({ ...st.topology, proxies: [{ id: "skynet:proxy:23010", port: 23010, label: "alpha", routerId: "" }] });'
     ' globalThis.__fpR1 = m.topologyStructureFingerprint();'
     ' st.setTopology({ ...st.topology, proxies: [{ id: "skynet:proxy:23010", port: 23010, label: "alpha", routerId: "router:default" }] });',
     '[globalThis.__fpR1 === globalThis.__fpR0, m.topologyStructureFingerprint() !== globalThis.__fpR1]',
     '[true,true]',
     "defect-history (2026-10-04): порт, привязанный из списка «unassigned», менял только routerId — канбан оставался "
     "со старыми клиентами и старым значком; negative: тот же канбан на следующем опросе — отпечаток тот же"),
    ("fingerprint_steady_when_nothing_changed",
     'st.setTopology({ ...st.topology, clients: [CLIENT({ agents: [{ id: "a1" }] })],'
     ' assignments: ROW([{ role: "primary", proxyId: "skynet:proxy:23001", endpoint: "e",'
     ' contextLength: 8192 }]) });'
     ' globalThis.__fp3 = m.topologyStructureFingerprint();',
     'm.topologyStructureFingerprint() === globalThis.__fp3',
     'true',
     "negative: ничего не менялось — отпечаток тот же, иначе доска перерисовывалась бы на каждом тике"),
    ("fingerprint_sees_an_engine_model_loading",
     'const E = (models, extra = {}) => ({ kind: "ollama", label: "Ollama", port: 11434, listen: "network", state: "ok", version: "0.12.3", models, pids: [5100], ramBytes: 100, ...extra });'
     ' st.setTopology({ ...st.topology, nodes: [{ id: "h1", role: "host", online: true, engines: [E([{ name: "qwen3:8b", loaded: false }])] }] });'
     ' globalThis.__fpE1 = m.topologyStructureFingerprint();'
     ' st.setTopology({ ...st.topology, nodes: [{ id: "h1", role: "host", online: true, engines: [E([{ name: "qwen3:8b", loaded: true, contextLength: 4096 }])] }] });',
     'm.topologyStructureFingerprint() !== globalThis.__fpE1',
     'true',
     "positive: модель движка рядом с ячейками загрузилась — структура: его карточка перестраивается (scout 2.12+)"),
    ("fingerprint_sees_an_engine_state",
     'const E = (models, extra = {}) => ({ kind: "ollama", label: "Ollama", port: 11434, listen: "network", state: "ok", version: "0.12.3", models, pids: [5100], ramBytes: 100, ...extra });'
     ' st.setTopology({ ...st.topology, nodes: [{ id: "h1", role: "host", online: true, engines: [E([])] }] });'
     ' globalThis.__fpE2 = m.topologyStructureFingerprint();'
     ' st.setTopology({ ...st.topology, nodes: [{ id: "h1", role: "host", online: true, engines: [E(null, { state: "auth" })] }] });',
     'm.topologyStructureFingerprint() !== globalThis.__fpE2',
     'true',
     "positive: движок стал просить токен — структура"),
    ("fingerprint_sees_a_model_made_an_output",
     'const E = (models, extra = {}) => ({ kind: "ollama", label: "Ollama", port: 11434, listen: "network", state: "ok", version: "0.12.3", models, pids: [5100], ramBytes: 100, ...extra });'
     ' st.setTopology({ ...st.topology, nodes: [{ id: "h1", role: "host", online: true, engines: [E([{ name: "a", exposed: false }])] }] });'
     ' globalThis.__fpE4 = m.topologyStructureFingerprint();'
     ' st.setTopology({ ...st.topology, nodes: [{ id: "h1", role: "host", online: true, engines: [E([{ name: "a", exposed: true }])] }] });',
     'm.topologyStructureFingerprint() !== globalThis.__fpE4',
     'true',
     "positive: модель стала выходом роутера — структура: у строки появляется якорь кабеля и нажатый переключатель"),
    ("fingerprint_sees_a_firewall_close",
     'const E = (models, extra = {}) => ({ kind: "ollama", label: "Ollama", port: 11434, listen: "network", state: "ok", version: "0.12.3", models, pids: [5100], ramBytes: 100, ...extra });'
     ' st.setTopology({ ...st.topology, nodes: [{ id: "h1", role: "host", online: true, engines: [E([], { firewall: { state: "open", allowedFrom: [] }, blockedBy: "", reachable: true })] }] });'
     ' globalThis.__fpE5 = m.topologyStructureFingerprint();'
     ' st.setTopology({ ...st.topology, nodes: [{ id: "h1", role: "host", online: true, engines: [E([], { firewall: { state: "restricted", allowedFrom: ["10.0.0.0/24"] }, blockedBy: "", reachable: true })] }] });',
     'm.topologyStructureFingerprint() !== globalThis.__fpE5',
     'true',
     "positive: файрвол порта движка сменился (открыт → только сеть контроллера) при той же достижимости — структура: бейдж перерисовывается (скаут 2.13)"),
    ("fingerprint_sees_an_act_start_and_fail",
     'const E = (models, extra = {}) => ({ kind: "ollama", label: "Ollama", port: 11434, listen: "network", state: "ok", version: "0.12.3", models, pids: [5100], ramBytes: 100, ...extra });'
     ' st.setTopology({ ...st.topology, nodes: [{ id: "h1", role: "host", online: true, engines: [E([{ name: "a", loaded: false }], { controls: ["load", "unload"] })] }] });'
     ' const f0 = m.topologyStructureFingerprint();'
     ' st.setTopology({ ...st.topology, nodes: [{ id: "h1", role: "host", online: true, engines: [E([{ name: "a", loaded: false, action: { op: "load", since: 1 } }], { controls: ["load", "unload"] })] }] });'
     ' const f1 = m.topologyStructureFingerprint();'
     ' st.setTopology({ ...st.topology, nodes: [{ id: "h1", role: "host", online: true, engines: [E([{ name: "a", loaded: false, actionError: { op: "load", error: "e", at: 2 } }], { controls: ["load", "unload"] })] }] });'
     ' const f2 = m.topologyStructureFingerprint();'
     ' st.setTopology({ ...st.topology, nodes: [{ id: "h1", role: "host", online: true, engines: [E([{ name: "a", loaded: false }], { controls: [] })] }] });'
     ' globalThis.__fpA = [f0, f1, f2, m.topologyStructureFingerprint()];',
     'new Set(globalThis.__fpA).size',
     '4',
     "positive: действие началось, упало, движок перестал его предлагать — каждое перестраивает карточку (кнопка, «loading…», ошибка)"),
    ("fingerprint_sees_the_server",
     'const E = (extra = {}) => ({ kind: "ollama", label: "Ollama", port: 11434, listen: "loopback", state: "ok", version: "0.34.4", models: [], pids: [7], ramBytes: 100, controls: ["load", "unload", "stop"], ...extra });'
     ' const fp = (e) => { st.setTopology({ ...st.topology, nodes: [{ id: "h1", role: "host", online: true, engines: [e] }] }); return m.topologyStructureFingerprint(); };'
     ' globalThis.__fpC = [fp(E()), fp(E({ runBy: "user" })), fp(E({ runBy: "other" })), fp(E({ autostart: true })),'
     ' fp(E({ serverAction: { op: "stop", since: 1 } })), fp(E({ serverError: { op: "start", error: "x", at: 2 } })),'
     ' fp(E({ state: "stopped", models: null, controls: ["start"] }))];',
     'new Set(globalThis.__fpC).size',
     '7',
     "positive: кто запускает сервер, «с машиной», пуск/остановка идёт или упали, «остановлен» (скаут 2.16) — каждое перестраивает карточку"),
    ("fingerprint_sees_a_download_not_its_bytes",
     'const E = (extra = {}) => ({ kind: "ollama", label: "Ollama", port: 11434, listen: "loopback", state: "ok", version: "0.34.4", models: [], pids: [7], ramBytes: 100, controls: ["load", "unload", "delete", "pull"], ...extra });'
     ' const fp = (e) => { st.setTopology({ ...st.topology, nodes: [{ id: "h1", role: "host", online: true, engines: [e] }] }); return m.topologyStructureFingerprint(); };'
     ' globalThis.__fpD = [fp(E()), fp(E({ downloading: { model: "qwen3:4b", since: 1, doneBytes: 1, totalBytes: 10 } })),'
     ' fp(E({ downloading: { model: "qwen3:4b", since: 1, doneBytes: 9, totalBytes: 10 } })), fp(E({ downloadError: { model: "q", error: "x", at: 3 } }))];',
     '[new Set(globalThis.__fpD).size, globalThis.__fpD[1] === globalThis.__fpD[2]]',
     '[3, true]',
     "скачивание началось, кончилось отказом — перестраивают карточку; negative: пришли ещё байты — нет (строку обновляет живой патч)"),
    ("fingerprint_sees_hold_and_stays",
     'const E = (models, extra = {}) => ({ kind: "lmstudio", label: "LM Studio", port: 1234, listen: "loopback", state: "ok", version: "", models, pids: [7], ramBytes: 100, controls: ["load", "unload"], ...extra });'
     ' const fp = (e) => { st.setTopology({ ...st.topology, nodes: [{ id: "h1", role: "host", online: true, engines: [e] }] }); return m.topologyStructureFingerprint(); };'
     ' globalThis.__fpB = [fp(E([{ name: "a", loaded: true }])), fp(E([{ name: "a", loaded: true, staysLoaded: true }])),'
     ' fp(E([{ name: "a", loaded: true }], { holds: true })), fp(E([{ name: "a", loaded: true, staysLoaded: false }]))];',
     '[new Set(globalThis.__fpB).size, globalThis.__fpB[0] === globalThis.__fpB[3]]',
     '[3, true]',
     "positive: «держит, пока не выгрузят» и «можно сказать срок» (скаут 2.15) перестраивают карточку; negative: staysLoaded false — как не сказано: текст строки тот же"),
    ("fingerprint_ignores_engine_memory",
     'const E = (models, extra = {}) => ({ kind: "ollama", label: "Ollama", port: 11434, listen: "network", state: "ok", version: "0.12.3", models, pids: [5100], ramBytes: 100, ...extra });'
     ' st.setTopology({ ...st.topology, nodes: [{ id: "h1", role: "host", online: true, engines: [E([{ name: "a", loaded: true }])] }] });'
     ' globalThis.__fpE3 = m.topologyStructureFingerprint();'
     ' st.setTopology({ ...st.topology, nodes: [{ id: "h1", role: "host", online: true, engines: [E([{ name: "a", loaded: true }], { ramBytes: 999999 })] }] });',
     'm.topologyStructureFingerprint() === globalThis.__fpE3',
     'true',
     "negative: память процессов движка — не структура, её пишет живой патчер; иначе перестройка на каждом отчёте"),
    ("fingerprint_ignores_liveness_age",
     'st.setTopology({ ...st.topology, nodes: [{ id: "h1", role: "host", online: false, ageSeconds: 5 }] });'
     ' globalThis.__fp4 = m.topologyStructureFingerprint();'
     ' st.setTopology({ ...st.topology, nodes: [{ id: "h1", role: "host", online: false, ageSeconds: 900 }] });',
     'm.topologyStructureFingerprint() === globalThis.__fp4',
     'true',
     "negative: возраст отчёта скаута — не структура, его двигает живой патчер; иначе полный ререндер каждые пару секунд"),
    ("fingerprint_sees_stored_change_under_a_live_report",
     'st.setTopology({ ...st.topology, clients: [CLIENT({ agents: [{ id: "a1" }],'
     ' assignments: [{ agentId: "a1", routes: [{ role: "primary", proxyId: "skynet:proxy:23001",'
     ' endpoint: "e" }] }] })],'
     ' assignments: ROW([{ role: "primary", proxyId: "skynet:proxy:23001", endpoint: "e" }]) });'
     ' globalThis.__fp9 = m.topologyStructureFingerprint();'
     ' st.setTopology({ ...st.topology, assignments: { c1: { assignments: [{ agentId: "a1",'
     ' manual: true, routes: [{ role: "primary", proxyId: "skynet:proxy:23001", endpoint: "e",'
     ' contextLength: 8192 }] }] } } });',
     'm.topologyStructureFingerprint() !== globalThis.__fp9',
     'true',
     "defect-history: у клиента, о котором есть ЖИВОЙ отчёт, отпечаток читал только его — и правка сохранённой записи (окно, флаг «руками») на доску не доезжала до перезагрузки"),
    ("fingerprint_sees_a_new_client",
     'st.setTopology({ ...st.topology, clients: [CLIENT()] });'
     ' globalThis.__fp5 = m.topologyStructureFingerprint();'
     ' st.setTopology({ ...st.topology, clients: [CLIENT(), { id: "c2", name: "D", state: "stale", gpus: [] }] });',
     'm.topologyStructureFingerprint() !== globalThis.__fp5',
     'true',
     "positive: новый клиент — структура, как и было"),
    ("fingerprint_sees_state_change",
     'st.setTopology({ ...st.topology, nodes: [{ id: "h1", role: "host", online: true }] });'
     ' globalThis.__fp6 = m.topologyStructureFingerprint();'
     ' st.setTopology({ ...st.topology, nodes: [{ id: "h1", role: "host", online: false }] });',
     'm.topologyStructureFingerprint() !== globalThis.__fp6',
     'true',
     "positive: скаут замолчал или отозвался — структура: у узла появляется или уходит баннер с ✕"),
    ("fingerprint_sees_a_new_host",
     'st.setTopology({ ...st.topology, nodes: [] });'
     ' globalThis.__fpH = m.topologyStructureFingerprint();'
     ' st.setTopology({ ...st.topology, nodes: [{ id: "h1", role: "host", online: true, gpus: [], servers: [] }] });',
     'm.topologyStructureFingerprint() !== globalThis.__fpH',
     'true',
     "positive: появилась машина без видеокарт и ячеек — структура: её id несут строка хостов и строка сборок llama.cpp"),
    ("fingerprint_sees_a_scout_name_its_version",
     'st.setTopology({ ...st.topology, nodes: [{ id: "h1", role: "host", online: true }] });'
     ' globalThis.__fpV = m.topologyStructureFingerprint();'
     ' st.setTopology({ ...st.topology, nodes: [{ id: "h1", role: "host", online: true, scoutVersion: "2.0.0" }] });',
     'm.topologyStructureFingerprint() !== globalThis.__fpV',
     'true',
     "positive: скаут обновился и назвал версию — плашка «обновите» уходит без перезагрузки"),
    ("fingerprint_ignores_a_client_rows_liveness",
     'st.setTopology({ ...st.topology, clients: [CLIENT({ state: "stale", gpus: [] })] });'
     ' globalThis.__fpC = m.topologyStructureFingerprint();'
     ' st.setTopology({ ...st.topology, clients: [CLIENT({ state: "online", gpus: [{ name: "RTX" }] })] });',
     'm.topologyStructureFingerprint() === globalThis.__fpC',
     'true',
     "negative: у клиента нет своей живости и железа — это поля машины; в строке клиента они больше не структура"),
    ("fingerprint_sees_a_new_assignment",
     'st.setTopology({ ...st.topology, clients: [CLIENT()], assignments: {} });'
     ' globalThis.__fp7 = m.topologyStructureFingerprint();'
     ' st.setTopology({ ...st.topology, assignments: ROW([]) });',
     'm.topologyStructureFingerprint() !== globalThis.__fp7',
     'true',
     "as-is: назначение считалось и раньше — эту половину не сломали"),
    ("fingerprint_sees_a_new_proxy",
     'st.setTopology({ ...st.topology, clients: [CLIENT()], proxies: [] });'
     ' globalThis.__fp8 = m.topologyStructureFingerprint();'
     ' st.setTopology({ ...st.topology, proxies: [{ port: 23001, label: "p", upstreamHost: "h",'
     ' upstreamPort: 8080, upstreamType: "llama" }] });',
     'm.topologyStructureFingerprint() !== globalThis.__fp8',
     'true',
     "as-is: новый порт — структура"),
]




def _en(key):
    """A string the pins expect, read out of static/js/i18n/en.js."""
    text = (ROOT / "static" / "js" / "i18n" / "en.js").read_text(encoding="utf-8")
    m = re.search(r'^\s*' + re.escape(key) + r':\s*(".*"),\s*$', text, re.M)
    return json.loads(m.group(1))


PINS += [
    ("fingerprint_sees_autostart",
     'st.setTopology({ ...st.topology, server: { llamaServers: [{ id: "s", port: 22021, model: "m", phase: "stopped",'
     ' bootSupported: true, bootEnabled: false }] } }); globalThis.__fpA = m.topologyStructureFingerprint();'
     ' st.setTopology({ ...st.topology, server: { llamaServers: [{ id: "s", port: 22021, model: "m", phase: "stopped",'
     ' bootSupported: true, bootEnabled: true }] } });',
     'm.topologyStructureFingerprint() !== globalThis.__fpA',
     'true',
     "defect-history: ↟ нажат, сервер включил автозапуск — отпечаток видит это, доска перерисовывается; без этого "
     "кнопка крутилась, пока не изменится что-то ещё"),
    ("fingerprint_sees_autostart_support",
     'st.setTopology({ ...st.topology, nodes: [{ id: "h1", role: "host", servers: [{ port: 22021, model: "m",'
     ' phase: "stopped" }] }] }); globalThis.__fpB = m.topologyStructureFingerprint();'
     ' st.setTopology({ ...st.topology, nodes: [{ id: "h1", role: "host", servers: [{ port: 22021, model: "m",'
     ' phase: "stopped", bootSupported: true }] }] });',
     'm.topologyStructureFingerprint() !== globalThis.__fpB',
     'true',
     "скаут обновился до 2.4 — ↟ на его ячейках становится доступным без перезагрузки страницы"),
]

PINS += [
    ("live_patch_moves_a_silent_hosts_age",
     'globalThis.CSS = { escape: (x) => x };'
     ' const age = { textContent: "" };'
     ' const nodeEl = { querySelector: (sel) => sel === "[data-live-hostage]" ? age : null };'
     ' globalThis.__age = age;'
     ' globalThis.__qs = document.querySelector;'
     ' document.querySelector = (sel) => sel.includes(\'data-node-id="h1"\') ? nodeEl : null;'
     ' st.setTopology({ ...st.topology, nodes: [{ id: "h1", role: "host", online: false, ageSeconds: 900, gpus: [], servers: [] }] });',
     '(() => { try { m.syncTopologyLive(); return globalThis.__age.textContent; }'
     ' finally { document.querySelector = globalThis.__qs; } })()',
     json.dumps(_en("nodeScoutLastReport").replace("{ago}", "15m")),
     "positive: живой патчер двигает возраст молчащего скаута тем же текстом, что и узел (hostAgeText), — "
     "иначе починка текста держалась бы один тик опроса"),
    # 2026-10-11: the pools' cards say which step serves and why the others wait — the proxy's word
    # changes between structural renders, so every live tick asks the lane, which draws itself only
    # when its own key moved (cloud.js).
    ("live_tick_asks_the_pools_lane",
     'globalThis.__lane = 0; globalThis.__stubReturns = { ...(globalThis.__stubReturns || {}),'
     ' "cloud.renderTopologyCloudProviders": () => { globalThis.__lane += 1; } };',
     '(() => { try { m.syncTopologyLive(); m.syncTopologyLive(); const ticks = globalThis.__lane;'
     ' st.setTopology(null); m.syncTopologyLive(); return [ticks, globalThis.__lane]; }'
     ' finally { delete globalThis.__stubReturns["cloud.renderTopologyCloudProviders"];'
     ' st.setTopology({ proxies: [], clients: [], routers: [], assignments: {} }); } })()',
     '[2, 2]',
     "живой тик доски просит полосу пулов перерисоваться (она сама решает по своему ключу) — иначе «Serving now» и причины шагов "
     "ждали бы структурной перерисовки; negative: топологии нет — не просит"),
    ("a_field_that_survives_render_does_not_hold_the_board",
     'globalThis.__ae = document.activeElement;'
     ' document.activeElement = { matches: () => true,'
     ' closest: (sel) => (sel === "[data-survives-render]" ? {} : null) };',
     '(() => { try { return m.topologyInteractionActive(); } finally { document.activeElement = globalThis.__ae; } })()',
     'false',
     "defect-history: фокус в поле «＋ Add scout» держал перерисовку доски — скаут, добавленный по Enter, "
     "не появлялся на доске, пока фокус не ушёл"),
    ("a_field_inside_the_board_holds_it",
     'globalThis.__ae = document.activeElement;'
     ' document.activeElement = { matches: () => true, closest: () => null };',
     '(() => { try { return m.topologyInteractionActive(); } finally { document.activeElement = globalThis.__ae; } })()',
     'true',
     "negative: поле внутри перестраиваемой доски (заметка ячейки, селект роутера) по-прежнему откладывает "
     "перерисовку — иначе она вырвала бы каретку из-под пальцев"),
]

# The caravan's shelf lists the models the page holds; /api/state brought them
# once and the beat read only the topology (2026-09-26). The topology carries
# the list's stamp, the beat brings the rows in when it moved (model-list.js),
# and the fingerprint sees the new list. To look at the order without a DOM,
# the render is held back by a focused field whose getter writes down the
# stamp the page holds at the moment the update is decided (twice: the render's
# check, then the "new model" window's). The first
# refresh marks the page ready on document.body, so the body has a dataset.
_REFRESH_SETUP = (
    'document.body = { dataset: {}, setAttribute: () => undefined };'
    ' globalThis.__fetchCalls = [];'
    ' globalThis.__fetchReply["/api/topology"] = { proxies: [], clients: [], routers: [], assignments: {}, modelsStamp: "s2" };'
    ' globalThis.__fetchReply["/api/models/rows"] = { ok: true, models: [{ path: "new.gguf", kind: "model" }], stamp: "s2" };'
    ' globalThis.__seen = [];'
    ' Object.defineProperty(document, "activeElement", { configurable: true, get: () => {'
    ' globalThis.__seen.push(st.state?.modelsStamp); return { matches: () => true, closest: () => null }; } });')
_REFRESH_RUN = (
    'await (async () => { try { await m.refreshTopology();'
    ' return [globalThis.__fetchCalls.map((c) => c.path), (st.state.models || []).map((r) => r.path),'
    ' st.state.modelsStamp, globalThis.__seen]; }'
    ' finally { Object.defineProperty(document, "activeElement", { configurable: true, writable: true, value: undefined });'
    ' delete globalThis.__fetchReply["/api/topology"]; delete globalThis.__fetchReply["/api/models/rows"]; } })()')
PINS += [
    ("fingerprint_sees_a_new_model_list",
     'st.setState({ config: {}, modelsStamp: "a" }); globalThis.__fpm0 = m.topologyStructureFingerprint();'
     ' st.setState({ config: {}, modelsStamp: "a" }); globalThis.__fpm1 = m.topologyStructureFingerprint();'
     ' st.setState({ config: {}, modelsStamp: "b" });',
     '[globalThis.__fpm1 === globalThis.__fpm0, m.topologyStructureFingerprint() !== globalThis.__fpm1]',
     '[true, true]',
     "defect-history: модель скачана при открытой доске — список страницы сменился, карточки перестраиваются, "
     "полка каравана её показывает; negative: тот же список на следующем опросе — не перестраиваются"),
    ("refresh_brings_the_models_before_the_render",
     'st.setState({ config: {}, models: [{ path: "old.gguf", kind: "model" }], modelsStamp: "s1" }); ' + _REFRESH_SETUP,
     _REFRESH_RUN,
     '[["/api/topology", "/api/models/rows"], ["new.gguf"], "s2", ["s2"]]',
     "defect-history: отпечаток списка в топологии сдвинулся — опрос дочитывает строки, и решение о перерисовке "
     "принимается уже над новым списком (иначе полка рисовала бы старый до следующего опроса)"),
    ("refresh_leaves_a_current_list_alone",
     'st.setState({ config: {}, models: [{ path: "old.gguf", kind: "model" }], modelsStamp: "s2" }); ' + _REFRESH_SETUP,
     _REFRESH_RUN,
     '[["/api/topology"], ["old.gguf"], "s2", ["s2"]]',
     "negative: отпечаток тот же — опрос не ходит за строками, список страницы как был"),
]

PINS += [
    # 2026-10-12: the kanban is the pools' board — what it draws is structure, moved from any page.
    ("fingerprint_follows_the_pools_board",
     'st.setTopology({ ...st.topology, proxies: [{ port: 23001, kind: "consumer", set: "chat", models: ["S"] }],'
     ' sets: [{ id: "chat", name: "Chat", pools: ["std"] }],'
     ' pools: [{ id: "std", name: "S", steps: [{ id: "r1", kind: "output", output: "srv:22008" }] }],'
     ' modelLevels: { set: {} }, poolsRuntime: { available: true, pools: { std: { selectedStepId: "r1", decidedAt: 1, steps: [] } } } });',
     '(() => { const fp = () => m.topologyStructureFingerprint(); const moved = (change) => { const before = fp(); change(); return fp() !== before; };'
     ' const top = st.topology; globalThis.ROUTER_STANDALONE = true;'
     ' try { return [moved(() => { top.proxies[0].set = "cheap"; }), moved(() => { top.proxies[0].models = ["S", "E"]; }),'
     ' moved(() => { top.sets[0].pools = ["std", "eco"]; }), moved(() => { top.sets[0].name = "Chat 2"; }),'
     ' moved(() => { top.pools[0].steps[0].output = "srv:22009"; }),'
     ' moved(() => { top.modelLevels = { set: { sub: { m: { stopAt: { "18000": 20 } } } } }; }), moved(() => { top.addedModels = { sub: ["m"] }; }),'
     ' moved(() => { top.poolsRuntime.pools.std.selectedStepId = ""; }), moved(() => { top.poolsRuntime.pools.std.decidedAt = 99; }),'
     ' (() => { globalThis.ROUTER_STANDALONE = false; return moved(() => { top.poolsRuntime.pools.std.selectedStepId = "r1"; }); })()]; }'
     ' finally { delete globalThis.ROUTER_STANDALONE; } })()',
     '[true,true,true,true,true,true,true,true,false,false]',
     "канбан перерисовывается, когда клиент перенёс канат на другой набор, у клиента сменились модели, у набора сменились пулы "
     "или имя (1.3.497), строка сменила выход, задан уровень модели, у аккаунта добавлена "
     "или убрана модель (2026-10-12), прокси выбрал другую строку; "
     "negative: время решения прокси меняется с каждым запросом — не структура; на главной доске решение прокси не перестраивает страницу"),
    # 1.3.498: a model opening or closing by its schedule changes its ⏱ and its rows' pills.
    ("fingerprint_follows_model_schedules",
     'st.setTopology({ ...st.topology, modelSchedules: { zone: { name: "UTC", known: true, offsetMinutes: 0 }, now: 1,'
     ' models: { "acc:a/m": { enabled: true, windows: [], open: true, until: 100, opensAt: null } } } });',
     '(() => { const fp = () => m.topologyStructureFingerprint(); const moved = (change) => { const before = fp(); change(); return fp() !== before; };'
     ' const ms = st.topology.modelSchedules; return [moved(() => { ms.models["acc:a/m"] = { ...ms.models["acc:a/m"], open: false, until: null, opensAt: 200 }; }),'
     ' moved(() => { ms.zone = { ...ms.zone, name: "Asia/Tbilisi" }; }), moved(() => { ms.now = 2; })]; })()',
     '[true,true,false]',
     "доска перерисовывается, когда модель закрылась или открылась и когда сменилась зона каравана; "
     "negative: миг «сейчас» меняется с каждым опросом — не структура"),
    ("fingerprint_follows_a_clients_errors",
     'st.setTopology({ ...st.topology, proxies: [{ port: 23001, kind: "consumer", set: "chat" }] });',
     '(() => { const fp = () => m.topologyStructureFingerprint(); const moved = (change) => { const before = fp(); change(); return fp() !== before; };'
     ' const c = st.topology.proxies[0]; return [moved(() => { c.misses = { items: [], more: 0 }; }),'
     ' moved(() => { c.misses = { items: [{ method: "POST", path: "/api/show", status: 404, count: 1, last: 1 }], more: 0 }; }),'
     ' moved(() => { c.misses.items[0].count = 2; }), moved(() => { c.misses = { ...c.misses, more: 3 }; }),'
     ' moved(() => { c.misses = { items: [{ ...c.misses.items[0] }], more: 3 }; }), moved(() => { delete c.misses; })]; })()',
     '[true,true,true,true,false,true]',
     "канбан перерисовывает карточку клиента, когда у него новая ошибка, выросло число или пришли ещё (2026-10-12); "
     "нет чтения журнала — это не «ошибок нет»; negative: те же ошибки новым объектом — не новая структура"),
    ("fingerprint_follows_a_pools_window",
     'st.setTopology({ ...st.topology, pools: [{ id: "std", name: "S", steps: [] }] });',
     '(() => { const fp = () => m.topologyStructureFingerprint(); const moved = (change) => { const before = fp(); change(); return fp() !== before; };'
     ' const pool = st.topology.pools[0]; return [moved(() => { pool.window = null; }), moved(() => { pool.window = 272000; }),'
     ' moved(() => { pool.contextLength = "300000"; }), moved(() => { pool.contextAuto = true; }), moved(() => { pool.window = 272000; }),'
     ' moved(() => { delete pool.window; })]; })()',
     '[true,true,true,true,false,true]',
     "канбан перерисовывается, когда у пула сменилось окно в «Pool settings», переключатель или то, что пул называет клиентам "
     "(2026-10-12) — с этой страницы или с другой; ответа контроллера нет — это не «окна нет»; negative: то же значение — не новая структура"),
    ("fingerprint_follows_the_providers_on_the_board",
     'st.setTopology({ ...st.topology, cloudAccounts: [{ id: "sub", name: "Sub", hasCredential: true }],'
     ' boardProviders: [{ kind: "openai-subscription", accounts: ["sub"] }] });',
     '(() => { const part = () => m.topologyStructureParts().providers; const moved = (change) => { const before = part(); change(); return part() !== before; };'
     ' const top = st.topology; return [moved(() => { top.boardProviders = [...top.boardProviders, { kind: "anthropic", accounts: [] }]; }),'
     ' moved(() => { top.boardProviders = top.boardProviders.slice(0, 1); }), moved(() => { top.boardProviders[0].accounts = ["sub", "sub-2"]; }),'
     ' moved(() => { top.boardProviders = top.boardProviders.map((p) => ({ ...p })); })]; })()',
     '[true,true,true,false]',
     "главная доска перерисовывает облачных провайдеров, когда провайдера поставили на доску или убрали, когда в блок добавили аккаунт "
     "(2026-10-12) — с этой страницы или с другой; negative: тот же список новым объектом — не новая структура"),
    ("fingerprint_parts_are_named_in_one_place",
     'st.setTopology({ ...st.topology, nodes: [{ id: "h1", online: true }] });',
     '[Object.keys(m.topologyStructureParts()),'
     ' Object.values(m.topologyStructureParts()).join("||") === m.topologyStructureFingerprint(),'
     ' (() => { const saved = st.topology; st.setTopology(null);'
     ' try { return [m.topologyStructureParts(), m.topologyStructureFingerprint()]; } finally { st.setTopology(saved); } })()]',
     '[["clients", "hosts", "classicSrv", "nodeSrv", "gpus", "engines", "prox", "sets", "cloud", "levels", "providers", "decided", "llamaVer", "models",'
     ' "view", "pendingCells", "modals", "order"], true, [{}, ""]]',
     "defect-history: window.__fpDebug называл части своим списком, без hosts и engines, — каждая часть после "
     "clients печаталась под именем соседки; теперь имена и порядок — сами части, и отпечаток — их склейка; "
     "boundary: топологии нет — частей нет, отпечаток пустой"),
]

# Model servers is one list of machines and cloud providers in the operator's order
# (server-order.js, 2026-10-04). The kanban's Servers panel is built in that order, so
# the order is structure; the board must not be rebuilt under a card in the air. The
# order is module state that outlives a pin: each pin starts it empty and leaves it so.
_SO_FRESH = ('globalThis.__so = (await import(pathToFileURL(process.env.JS_ROOT + "/server-order.js").href)).SERVER_ORDER;'
             ' Object.assign(globalThis.__so, { held: { order: [], rev: -1 }, shown: null, dragging: null, target: null });')
_SO_DONE = 'Object.assign(globalThis.__so, { held: { order: [], rev: -1 }, shown: null, dragging: null, target: null });'
PINS += [
    ("lane_switch_counts_by_board",
     '',
     '[m.laneSwitchCounts({ clients: [{ agents: [1, 2] }, { agents: [3] }], hosts: [{}, {}] }, { isMachine: false }),'
     ' m.laneSwitchCounts({ hosts: [{}, {}] }, { isMachine: true }), m.laneSwitchCounts(null, { isMachine: false })]',
     '[{"clients":3,"cells":0},{"clients":0,"cells":2},{"clients":0,"cells":0}]',
     "⊟ ячеек — только там, где ячейки нарисованы: в окне машины; negative: главная доска ячеек не рисует — счёт 0, "
     "и переключатель прячется (раньше считал машины и стоял без дела, 2026-10-11); нет сведений — ноль, а не падение"),
    ("server_order_is_structure",
     _SO_FRESH,
     '(() => { const so = globalThis.__so; try {'
     ' st.setTopology({ ...st.topology, layout: { serverOrder: ["cloud:p", "node:a"], serverOrderRev: 2 } }); so.read(st.topology);'
     ' const a = m.topologyStructureParts().order, fa = m.topologyStructureFingerprint();'
     ' st.setTopology({ ...st.topology, layout: { serverOrder: ["cloud:p", "node:a"], serverOrderRev: 2 } }); so.read(st.topology);'
     ' const same = m.topologyStructureFingerprint() === fa;'
     ' st.setTopology({ ...st.topology, layout: { serverOrder: ["node:a", "cloud:p"], serverOrderRev: 3 } }); so.read(st.topology);'
     ' return [a, same, m.topologyStructureParts().order, m.topologyStructureFingerprint() !== fa]; } finally { ' + _SO_DONE + ' } })()',
     '["cloud:p,node:a", true, "node:a,cloud:p", true]',
     "порядок карточек Model servers — часть структуры: новый порядок (с этой страницы или с другой) перестраивает "
     "панель «Серверы» канбана, которая собрана в этом порядке; negative: тот же порядок на следующем опросе — нет"),
    ("server_order_is_read_before_the_update_decides",
     _SO_FRESH + ' globalThis.__ae = document.activeElement; document.activeElement = { matches: () => true, closest: () => null };',
     '(() => { const so = globalThis.__so; try {'
     ' st.setTopology({ ...st.topology, layout: { serverOrder: ["cloud:p", "node:a"], serverOrderRev: 1 } });'
     ' m.applyTopologyUpdate(); return so.current(); }'
     ' finally { document.activeElement = globalThis.__ae; ' + _SO_DONE + ' } })()',
     '["cloud:p", "node:a"]',
     "опрос берёт порядок из топологии до решения о перерисовке — иначе отпечаток считался бы по старому порядку "
     "и канбан ждал бы следующего изменения; взят и тогда, когда перерисовка отложена (фокус в поле)"),
]

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def main():
    # The floor catches a list cut short by accident, so it follows the list: 16
    # since the host card's seven pins went with the card (2026-09-24), the
    # host's liveness came to the fingerprint and the live patch as three, and
    # the scout's version as one more; 18 since a field that survives the
    # render stopped holding it back; 20 since autostart came to the print.
    if len(PINS) < 20:
        print(f"js topology-render FAILED: всего {len(PINS)} пинов — снимок урезан")
        return 1
    node = find_node()
    if node is None:
        print("js topology-render: SKIPPED — node не найден: " + ", ".join(node_search_paths()))
        return 0

    def blocks(pins, sink):
        return [f"try {{ reset(); {setup}\n  {sink}[{json.dumps(pid)}] = {expr}; }} "
                f"catch (e) {{ {sink}[{json.dumps(pid)}] = {{ __threw: String(e && e.message || e) }}; }}"
                for pid, setup, expr, _exp, _msg in pins]

    # Pins don't depend on each other: the same set run in reverse order
    # must give the same values.
    probe = (PREAMBLE + "\n".join(blocks(PINS, "out")) + "\nconst rev = {};\n"
             + "\n".join(blocks(list(reversed(PINS)), "rev"))
             + "\nconsole.log(JSON.stringify({ out, rev })); process.exit(0);\n")
    harness = ROOT / "scripts" / "_js_harness.mjs"
    path = ROOT / "scripts" / ".probe_js_client_proxies.tmp.mjs"
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
        print(f"js topology-render FAILED: node вышел с кодом {run.returncode}")
        return 1
    both = json.loads(run.stdout.strip().splitlines()[-1])
    got, rev = both["out"], both["rev"]
    print("перерисовка доски:")
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
    print(f"js topology-render OK: настоящий модуль в node, {len(PINS)} пинов отпечатка значениями")
    return 0


if __name__ == "__main__":
    sys.exit(main())
