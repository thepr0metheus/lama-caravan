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
const m = await import(pathToFileURL(process.env.JS_ROOT + "/topology-render.js").href);
const reset = () => { st.setState({ config: {} });
  st.setTopology({ proxies: [], clients: [], routers: [], assignments: {} }); };
const CLIENT = (extra = {}) => ({ id: "c1", name: "C", state: "stale", gpus: [], ...extra });
const ROW = (routes) => ({ c1: { assignments: [{ agentId: "a1", routes }] } });
const out = {};
"""

PINS = [
    ("fingerprint_sees_a_new_agent",
     'st.setTopology({ ...st.topology, clients: [CLIENT({ agents: [] })] });'
     ' globalThis.__fp0 = m.topologyStructureFingerprint();'
     ' st.setTopology({ ...st.topology, clients: [CLIENT({ agents: [{ id: "a1" }] })] });',
     'm.topologyStructureFingerprint() !== globalThis.__fp0',
     'true',
     "defect-history: агент, заведённый руками, ложился в запись и не показывался до перезагрузки"),
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
    ("fingerprint_steady_when_nothing_changed",
     'st.setTopology({ ...st.topology, clients: [CLIENT({ agents: [{ id: "a1" }] })],'
     ' assignments: ROW([{ role: "primary", proxyId: "skynet:proxy:23001", endpoint: "e",'
     ' contextLength: 8192 }]) });'
     ' globalThis.__fp3 = m.topologyStructureFingerprint();',
     'm.topologyStructureFingerprint() === globalThis.__fp3',
     'true',
     "negative: ничего не менялось — отпечаток тот же, иначе доска перерисовывалась бы на каждом тике"),
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
    # the scout's version as one more.
    if len(PINS) < 16:
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
