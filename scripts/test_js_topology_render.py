#!/usr/bin/env python3
"""Снимок static/js/topology-render.js — от чего доска перерисовывается.

Доска решает перерисоваться по ОТПЕЧАТКУ структуры: пока он не изменился,
идёт дешёвая правка на месте. Значит всё, чего в отпечатке нет, на доске не
появляется до перезагрузки страницы — и выглядит это как «не сохранилось».

Так и вышло: агент, заведённый руками, ложился в запись и не показывался,
пока страницу не перезагрузишь. Отпечаток считал НАЗНАЧЕНИЯ клиента и не
считал агентов. По той же причине не обновлялся чип окна контекста.

Этот модуль до сих пор не грузил НИ ОДИН снимок — он заглушён во всех
харнессах. Поэтому же в нём проехал в прод синтаксис, который node --check не
ловит. Теперь он загружается по-настоящему.

Запуск: python3 scripts/test_js_topology_render.py
"""
import json
import os
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
    ("fingerprint_steady_when_nothing_changed",
     'st.setTopology({ ...st.topology, clients: [CLIENT({ agents: [{ id: "a1" }] })],'
     ' assignments: ROW([{ role: "primary", proxyId: "skynet:proxy:23001", endpoint: "e",'
     ' contextLength: 8192 }]) });'
     ' globalThis.__fp3 = m.topologyStructureFingerprint();',
     'm.topologyStructureFingerprint() === globalThis.__fp3',
     'true',
     "negative: ничего не менялось — отпечаток тот же, иначе доска перерисовывалась бы на каждом тике"),
    ("fingerprint_ignores_liveness_age",
     'st.setTopology({ ...st.topology, clients: [CLIENT({ agents: [{ id: "a1" }], ageSeconds: 5 })] });'
     ' globalThis.__fp4 = m.topologyStructureFingerprint();'
     ' st.setTopology({ ...st.topology, clients: [CLIENT({ agents: [{ id: "a1" }], ageSeconds: 900 })] });',
     'm.topologyStructureFingerprint() === globalThis.__fp4',
     'true',
     "negative: возраст ответа — не структура, его чинит живой патчер; иначе полный ререндер каждые пару секунд"),
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
    ("silent_manual_client_says_it_once",
     '',
     'm.clientHasNothingToReport({ manual: true })',
     'true',
     'ручной и ни разу не отвечавший: «ip n/a», плашка, «never answered» и заметка — четыре способа сказать одно и то же'),
    ("client_that_answered_reports_normally",
     '',
     '[m.clientHasNothingToReport({ manual: true, ageSeconds: 0 }), m.clientHasNothingToReport({ manual: true, ageSeconds: 300 })]',
     '[false,false]',
     'boundary: отозвался — есть что сказать, и ноль секунд это ответ прямо сейчас, а не отсутствие'),
    ("client_with_an_address_reports_it",
     '',
     'm.clientHasNothingToReport({ manual: true, ip: "10.0.0.5" })',
     'false',
     'negative: адрес известен — молчать не о чем'),
    ("scout_client_always_reports",
     '',
     '[m.clientHasNothingToReport({ lastSeen: 111 }), m.clientHasNothingToReport({ agentUrl: "http://h:8092" })]',
     '[false,false]',
     'negative: у клиента СО СКАУТОМ ничего не скрывается — правило про то, есть ли кому рассказывать, а не про пометку «руками»'),
    ("quiet_manual_client_gets_no_alarm",
     'st.setTopology({ ...st.topology, clients: [CLIENT({ manual: true, state: "stale", agents: [] })] });',
     '(h => [h.includes("client-stale-banner"), h.includes("client-delete-btn"), h.includes("client-quiet-note")])'
     '(m.clientStaleBannerHtml({ id: "c1", manual: true }, true))',
     '[false,false,true]',
     'defect-history: молчащему ручному клиенту доска кричала красным «агент не отвечает» и ставила рядом Delete — на этом жесте потеряли запись'),
    ("quiet_scout_client_still_alarms",
     'st.setTopology({ ...st.topology, clients: [CLIENT({ state: "stale", agents: [] })] });',
     '(h => [h.includes("client-stale-banner"), h.includes("client-delete-btn")])'
     '(m.clientStaleBannerHtml({ id: "c1", lastSeen: 111 }, true))',
     '[true,true]',
     'negative: скаут был и замолчал — это настоящая поломка, тревога остаётся; усыновление пометило manual весь флот, и по нему судить больше нельзя'),
    ("quiet_note_absent_while_the_client_answers",
     '',
     '[m.clientStaleBannerHtml({ id: "c1", manual: true }, false), m.clientStaleBannerHtml({ id: "c1" }, false)]',
     '["",""]',
     'negative: клиент отвечает — ни тревоги, ни заметки: сказать нечего'),
    ("discovery_hidden_on_a_manual_client",
     '',
     'm.clientDiscoveryBannerHtml({ id: "c1", manual: true }, [{ machine: "m1", suggestedId: "s1" }])',
     '""',
     "запись ведёт доска: агенты заводятся ＋ в карточке, и второй, чужой способ рядом — вопрос «какой правильный»"),
    ("discovery_shown_on_a_scout_client",
     '',
     'm.clientDiscoveryBannerHtml({ id: "c1" }, [{ machine: "m1", suggestedId: "s1" }]).includes("data-discover-add")',
     'true',
     "negative: у клиента, которого ведёт скаут, предложение остаётся — там это его работа"),
    ("discovery_empty_when_nothing_found",
     '',
     'm.clientDiscoveryBannerHtml({ id: "c1" }, [])',
     '""',
     "negative: находок нет — пустая рамка не рисуется"),
    ("discovery_survives_missing_candidates",
     '',
     'm.clientDiscoveryBannerHtml({ id: "c1" }, null)',
     '""',
     "boundary: список не пришёл вовсе — это не находки, а их отсутствие"),
    ("fingerprint_sees_a_new_client",
     'st.setTopology({ ...st.topology, clients: [CLIENT()] });'
     ' globalThis.__fp5 = m.topologyStructureFingerprint();'
     ' st.setTopology({ ...st.topology, clients: [CLIENT(), { id: "c2", name: "D", state: "stale", gpus: [] }] });',
     'm.topologyStructureFingerprint() !== globalThis.__fp5',
     'true',
     "positive: новый клиент — структура, как и было"),
    ("fingerprint_sees_state_change",
     'st.setTopology({ ...st.topology, clients: [CLIENT({ state: "stale" })] });'
     ' globalThis.__fp6 = m.topologyStructureFingerprint();'
     ' st.setTopology({ ...st.topology, clients: [CLIENT({ state: "online" })] });',
     'm.topologyStructureFingerprint() !== globalThis.__fp6',
     'true',
     "positive: замолчал или отозвался — структура, как и было"),
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


_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def main():
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

    # Пины не опираются друг на друга: тот же набор в обратном порядке обязан
    # дать те же значения.
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
