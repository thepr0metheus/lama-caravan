#!/usr/bin/env python3
"""Снимок static/js/topology-proxies.js — чья версия назначений выигрывает.

У одного и того же агента есть ДВЕ версии его маршрутов: сохранённая на
контроллере (что оператор задал) и живая из отчёта скаута (куда агент реально
ходит). Доска их сливает, и сегодня ЖИВАЯ побеждает по роли. Это уже стоило
одной починки: у живого отчёта пустой proxyId выигрывал слияние, и кабель не
рисовался вовсе.

Для переноса управления на страницу это главный вопрос: настройка, положенная
в сохранённый маршрут, при таком слиянии исчезнет из виду — живой отчёт её не
несёт и никогда не понесёт. Пины закрепляют текущее правило по ролям и то,
какие поля уже добираются из сохранённой версии, а какие нет.

Модуль грузится НАСТОЯЩИЙ (scripts/_js_harness.mjs).

Запуск: python3 scripts/test_js_client_proxies.py
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _node import find_node, node_search_paths  # noqa: E402

STUBS = ("topology-render,topology-nodes,topology-modals,cables,routers,charts,remote-cells,cloud,history,dialogs,"
         "llama-edit,form,favorites,config-locator,system-panels,onboarding,topology-dnd,canvas,"
         "usage-stats,dialog-llamas,models-page,system-page,onboarding-tours,memory,command-preview,model-meta,polling")

PREAMBLE = r"""
import "./_js_globals.mjs";
import { pathToFileURL } from "node:url";
const st = await import(pathToFileURL(process.env.JS_ROOT + "/state.js").href);
st.setState({ config: {} });
st.setTopology({ proxies: [], clients: [], routers: [], assignments: {} });
Date.now = () => 1_700_000_100_000;
const m = await import(pathToFileURL(process.env.JS_ROOT + "/topology-proxies.js").href);
const reset = () => { st.setState({ config: {} });
  st.setTopology({ proxies: [], clients: [], routers: [], assignments: {} }); };
// Один агент, две версии его маршрутов.
const STORED = (extra = {}) => ({ c1: { agentUrl: "", assignments: [
  { agentId: "a1", routes: [{ role: "primary", proxyId: "skynet:proxy:23001",
                              endpoint: "http://h:23001/v1", ...extra }] } ] } });
const LIVE = (routes) => [{ id: "c1", name: "C", assignments: [{ agentId: "a1", routes }] }];
const PROXIES = [{ id: "skynet:proxy:23001", port: 23001, label: "p1", routerId: "r" },
                 { id: "skynet:proxy:23002", port: 23002, label: "p2", routerId: "r" }];
const out = {};
"""

PINS = [
    ("kanban_clients_come_from_the_board",
     'st.setTopology({ ...st.topology, clients: [{ id: "c1", manual: true, agents: [{ id: "a1" }] }],'
     ' assignments: { c1: { assignments: [{ agentId: "a1", routes: [{ role: "primary",'
     ' proxyId: "skynet:proxy:23001", endpoint: "e" }] }] } } });',
     '(r => [r.rows.map((x) => x.key), r.unclaimed.map((p) => p.port)])'
     '(m.canvasBoardClients([{ id: "skynet:proxy:23001", port: 23001, label: "p1" }]))',
     '[["c1::a1"],[]]',
     "клиенты канбана берутся с главной: раньше он перечислял ПОРТЫ и показывал строки, которых на главной нет"),
    ("kanban_shows_a_contested_port_once",
     'st.setTopology({ ...st.topology, clients: [{ id: "c1", manual: true, agents: [{ id: "a1" }] },'
     ' { id: "c2", manual: true, agents: [{ id: "a2" }] }],'
     ' assignments: { c1: { assignments: [{ agentId: "a1", routes: [{ role: "primary",'
     ' proxyId: "skynet:proxy:23001", endpoint: "e" }] }] },'
     ' c2: { assignments: [{ agentId: "a2", routes: [{ role: "primary",'
     ' proxyId: "skynet:proxy:23001", endpoint: "e" }] }] } } });',
     '(r => [r.rows.map((x) => x.key), r.rows.map((x) => x.proxies.length)])'
     '(m.canvasBoardClients([{ id: "skynet:proxy:23001", port: 23001 }]))',
     '[["c1::a1"],[1]]',
     "boundary: один порт назвали два назначения — на канбане он ОДИН раз, у первого; иначе одна очередь рисуется как две"),
    ("kanban_names_a_port_no_client_owns",
     'st.setTopology({ ...st.topology, clients: [], assignments: {} });',
     '(r => [r.rows.length, r.unclaimed.map((p) => p.port)])'
     '(m.canvasBoardClients([{ id: "skynet:proxy:8022", port: 8022, label: "promie" }]))',
     '[0,[8022]]',
     "порт без владельца НЕ прячется: молча выкинуть заведённый в маршрутизацию вход — отсутствие, нарисованное нормой"),
    ("kanban_pairs_primary_and_fallback_in_one_row",
     'st.setTopology({ ...st.topology, clients: [{ id: "c1", manual: true, agents: [{ id: "a1" }] }],'
     ' assignments: { c1: { assignments: [{ agentId: "a1", routes: [{ role: "primary",'
     ' proxyId: "skynet:proxy:23001", endpoint: "e" }, { role: "fallback",'
     ' proxyId: "skynet:proxy:23002", endpoint: "e2" }] }] } } });',
     '(r => [r.rows.length, r.rows[0].proxies.map((p) => p.port), r.unclaimed.length])'
     '(m.canvasBoardClients([{ id: "skynet:proxy:23001", port: 23001 }, { id: "skynet:proxy:23002", port: 23002 }]))',
     '[1,[23001,23002],0]',
     "пара ролей одного агента — одна строка, как и было"),
    ("kanban_rows_alphabetical_by_client_then_agent",
     'st.setTopology({ ...st.topology, clients: [{ id: "zeta", manual: true, agents: [{ id: "z1" }] },'
     ' { id: "mid", name: "Alpha", manual: true, agents: [{ id: "beta" }, { id: "alpha" }] }],'
     ' assignments: { zeta: { assignments: [{ agentId: "z1", routes: [{ role: "primary", proxyId: "skynet:proxy:23001", endpoint: "e" }] }] },'
     ' mid: { assignments: [{ agentId: "beta", routes: [{ role: "primary", proxyId: "skynet:proxy:23003", endpoint: "e" }] },'
     ' { agentId: "alpha", routes: [{ role: "primary", proxyId: "skynet:proxy:23005", endpoint: "e" }] }] } } });',
     '(r => r.rows.map((x) => x.key))'
     '(m.canvasBoardClients([{ id: "skynet:proxy:23001", port: 23001 }, { id: "skynet:proxy:23003", port: 23003 }, { id: "skynet:proxy:23005", port: 23005 }]))',
     '["mid::alpha","mid::beta","zeta::z1"]',
     "строки канбана — в порядке главной: клиенты по алфавиту ПОКАЗАННЫХ имён (Alpha раньше zeta, хоть id «mid»), внутри клиента агенты по алфавиту — а не в порядке хранения"),
    ("kanban_ignores_a_client_whose_ports_are_not_wired",
     'st.setTopology({ ...st.topology, clients: [{ id: "c1", manual: true, agents: [{ id: "a1" }] }],'
     ' assignments: { c1: { assignments: [{ agentId: "a1", routes: [{ role: "primary",'
     ' proxyId: "skynet:proxy:29999", endpoint: "e" }] }] } } });',
     '(r => [r.rows.length, r.unclaimed.length])'
     '(m.canvasBoardClients([{ id: "skynet:proxy:23001", port: 23001 }]))',
     '[0,1]',
     "negative: клиент есть, но его порт в этот роутер не заведён — строки нет, а чужой порт назван непринадлежащим"),
    ("scout_presence_by_agent_url",
     '',
     '[m.clientHasScout({ agentUrl: "http://h:8092" }), m.clientHasScout({ lastSeen: 111 }), m.clientHasScout({ manual: true }), m.clientHasScout(null)]',
     '[true,true,false,false]',
     'карточка хоста существует ради того, что рассказал скаут: признак — адрес агента или хоть один полученный ответ'),
    ("silenced_scout_client_keeps_its_card",
     '',
     'm.clientHasScout({ lastSeen: 111, ageSeconds: 600000 })',
     'true',
     'boundary: скаут был и замолчал — карточка остаётся, чтобы показать, КОГДА он отвечал в последний раз'),
    ("idle_hours_from_the_freshest_route",
     'st.setTopology({ ...st.topology, proxies: [{ id: "skynet:proxy:23001", port: 23001, lastRequestAt: 1700000100 - 3600 * 20 },'
     ' { id: "skynet:proxy:23002", port: 23002, lastRequestAt: 1700000100 - 3600 * 2 }] });',
     'm.agentIdleHours([{ proxyId: "skynet:proxy:23001" }, { proxyId: "skynet:proxy:23002" }])',
     '2',
     "простой считается по САМОМУ СВЕЖЕМУ запросу среди всех ролей агента: фолбэк ходил два часа назад — агент не простаивает"),
    ("idle_when_older_than_the_threshold",
     'st.setTopology({ ...st.topology, proxies: [{ id: "skynet:proxy:23001", port: 23001, lastRequestAt: 1700000100 - 3600 * 13 }] });',
     '[m.agentIsIdle([{ proxyId: "skynet:proxy:23001" }]), m.AGENT_IDLE_HOURS]',
     '[true,12]',
     "13 часов без трафика — простаивает; порог 12 задан одним числом, а не размазан по коду"),
    ("not_idle_just_under_the_threshold",
     'st.setTopology({ ...st.topology, proxies: [{ id: "skynet:proxy:23001", port: 23001, lastRequestAt: 1700000100 - 3600 * 11.9 }] });',
     'm.agentIsIdle([{ proxyId: "skynet:proxy:23001" }])',
     'false',
     "boundary: 11.9 часа — ещё не простой; рамка не появляется раньше порога"),
    ("never_seen_is_infinity_not_zero",
     'st.setTopology({ ...st.topology, proxies: [{ id: "skynet:proxy:23001", port: 23001, lastRequestAt: 0 }] });',
     '[m.agentIdleHours([{ proxyId: "skynet:proxy:23001" }]) === Infinity, m.agentIsIdle([{ proxyId: "skynet:proxy:23001" }])]',
     '[true,true]',
     "defect-class: «ни одного запроса за окно» — Infinity, а не ноль; ноль часов означал бы «только что», то есть отсутствие, нарисованное нормой"),
    ("no_routes_is_idle",
     'st.setTopology({ ...st.topology, proxies: [] });',
     '[m.agentIsIdle([]), m.agentIsIdle(null)]',
     '[true,true]',
     "negative: агент без маршрутов трафика не возит — простаивает, и без исключения"),
    ("client_is_live_when_one_agent_has_fresh_traffic",
     'st.setTopology({ ...st.topology, proxies: [{ id: "skynet:proxy:23001", port: 23001, lastRequestAt: 1700000100 - 3600 * 13 }, { id: "skynet:proxy:23002", port: 23002, lastRequestAt: 1700000100 - 60 }],'
     ' clients: [{ id: "c1", manual: true, agents: [{ id: "a1" }, { id: "a2" }] }],'
     ' assignments: { c1: { assignments: [{ agentId: "a1", routes: [{ role: "primary", proxyId: "skynet:proxy:23001" }] }, { agentId: "a2", routes: [{ role: "primary", proxyId: "skynet:proxy:23002" }] }] } } });',
     'm.clientIsLive(st.topology.clients[0])',
     'true',
     "клиент живой, если ХОТЬ ОДИН его агент возил трафик за 12 часов — второй агент молчит 13 часов, а первый ходил минуту назад"),
    ("client_is_quiet_when_all_agents_idle_or_absent",
     'st.setTopology({ ...st.topology, proxies: [{ id: "skynet:proxy:23001", port: 23001, lastRequestAt: 1700000100 - 3600 * 13 }],'
     ' clients: [{ id: "c1", manual: true, agents: [{ id: "a1" }] }, { id: "c2", manual: true, agents: [] }, { id: "c3", manual: true, agents: [{ id: "a3" }] }],'
     ' assignments: { c1: { assignments: [{ agentId: "a1", routes: [{ role: "primary", proxyId: "skynet:proxy:23001" }] }] } } });',
     'st.topology.clients.map((c) => m.clientIsLive(c))',
     '[false,false,false]',
     "negative: все агенты простаивают, агентов нет, назначений нет — клиент тихий; тот же порог 12 ч, что у жёлтой рамки"),
    ("kanban_rows_put_live_agents_first",
     'st.setTopology({ ...st.topology, proxies: [{ id: "skynet:proxy:23001", port: 23001, lastRequestAt: 1700000100 - 3600 * 13 }, { id: "skynet:proxy:23003", port: 23003, lastRequestAt: 1700000100 - 60 }, { id: "skynet:proxy:23005", port: 23005, lastRequestAt: 1700000100 - 120 }],'
     ' clients: [{ id: "alpha", manual: true, agents: [{ id: "a1" }] }, { id: "host", manual: true, agents: [{ id: "argus" }, { id: "orion" }] }],'
     ' assignments: { alpha: { assignments: [{ agentId: "a1", routes: [{ role: "primary", proxyId: "skynet:proxy:23003" }] }] }, host: { assignments: [{ agentId: "argus", routes: [{ role: "primary", proxyId: "skynet:proxy:23001" }] }, { agentId: "orion", routes: [{ role: "primary", proxyId: "skynet:proxy:23005" }] }] } } });',
     '(r => [r.rows.map((x) => x.key), r.rows.map((x) => x.live)])(m.canvasBoardClients([{ id: "skynet:proxy:23001", port: 23001 }, { id: "skynet:proxy:23003", port: 23003 }, { id: "skynet:proxy:23005", port: 23005 }]))',
     '[["alpha::a1","host::orion","host::argus"],[true,true,false]]',
     "строки канбана — как карточки главной: живые агенты (a1, orion) раньше тихого argus, даже когда он из того же клиента и первый по алфавиту; внутри групп по имени"),
    ("agent_card_carries_its_name",
     'st.setTopology({ ...st.topology, proxies: [], clients: [{ id: "c1", manual: true, agents: [{ id: "a1", name: "Alice" }, { id: "a2" }] }] });',
     'm.clientLaneAgentCards(st.topology.clients[0], []).map((c) => c.name)',
     '["a2","Alice"]',
     "карточка агента несёт имя для сортировки лейна: имя агента, иначе id"),
    ("agent_card_carries_the_idle_flag",
     'st.setTopology({ ...st.topology, proxies: [{ id: "skynet:proxy:23001", port: 23001, lastRequestAt: 1700000100 - 60 }],'
     ' clients: [{ id: "c1", manual: true, agents: [{ id: "a1" }, { id: "a2" }] }] });',
     '(cards => cards.map((c) => [c.agentId, c.idle]))'
     '(m.clientLaneAgentCards(st.topology.clients[0], [{ agentId: "a1", routes: [{ role: "primary", proxyId: "skynet:proxy:23001", endpoint: "e" }] }, { agentId: "a2", routes: [] }]))',
     '[["a1",false],["a2",true]]',
     "positive: у карточки есть флаг простоя — тот, чей порт ходил минуту назад, живой; тот, у кого нет маршрутов, простаивает"),
    ("host_card_only_where_the_scout_is",
     'st.setTopology({ ...st.topology, proxies: PROXIES, clients: [] });',
     '[m.clientCardIsRedundant({ id: "c1", manual: true }, 1), m.clientCardIsRedundant({ id: "c1", agentUrl: "http://h:8092" }, 1),'
     ' m.clientCardIsRedundant({ id: "c1", lastSeen: 111 }, 0)]',
     '[true,false,false]',
     'карточка хоста нужна там, где есть скаут; без него она рамка вокруг пустоты рядом с карточкой агента'),
    ("caption_when_the_agent_card_cannot_hold_the_controls",
     'st.setTopology({ ...st.topology, proxies: PROXIES, clients: [] });',
     '[m.clientNeedsCaption({ manual: true }, 0), m.clientNeedsCaption({ manual: true }, 1), m.clientNeedsCaption({ manual: true }, 2),'
     ' m.clientNeedsCaption({ agentUrl: "http://h" }, 0)]',
     '[true,false,true,false]',
     'boundary: один агент — управление уходит в его карточку; ноль или несколько — строка-заголовок, иначе «удалить клиента» повторится на каждом агенте'),
    ("single_agent_card_takes_the_client_controls",
     'st.setTopology({ ...st.topology, proxies: PROXIES,'
     ' clients: [{ id: "c1", manual: true, agents: [{ id: "a1" }] }] });',
     '(cards => [cards.length, cards[0].html.includes("data-client-delete"), cards[0].html.includes("data-client-agent-add")])'
     '(m.clientLaneAgentCards(st.topology.clients[0], []))',
     '[1,true,true]',
     'positive: единственный агент забирает ＋ и ✕ клиента — карточки хоста рядом не будет'),
    ("several_agent_cards_do_not_repeat_the_client_controls",
     'st.setTopology({ ...st.topology, proxies: PROXIES,'
     ' clients: [{ id: "c1", manual: true, agents: [{ id: "a1" }, { id: "a2" }] }] });',
     'm.clientLaneAgentCards(st.topology.clients[0], []).filter((c) => c.html.includes("data-client-delete")).length',
     '0',
     'negative: агентов несколько — «удалить клиента» не повторяется на каждом, оно уходит в строку-заголовок'),
    ("manual_client_gets_a_card_per_agent",
     'st.setTopology({ ...st.topology, proxies: PROXIES,'
     ' clients: [{ id: "c1", manual: true, agents: [{ id: "a1" }, { id: "a2" }, { id: "a3" }] }] });',
     'm.clientLaneAgentCards(st.topology.clients[0], []).length',
     '3',
     "каждый агент — свой блок: слепленные в одну карточку читаются как одна сущность, хотя это разные потребители с разными портами"),
    ("scout_client_gets_no_separate_cards",
     'st.setTopology({ ...st.topology, proxies: PROXIES,'
     ' clients: [{ id: "c1", agents: [{ id: "a1" }, { id: "a2" }] }] });',
     'm.clientLaneAgentCards(st.topology.clients[0], []).length',
     '0',
     "negative: у клиента от скаута раскладка своя — по тому, где агент живёт на машине"),
    ("manual_client_without_agents_gets_no_cards",
     'st.setTopology({ ...st.topology, proxies: PROXIES,'
     ' clients: [{ id: "c1", manual: true, agents: [] }] });',
     'm.clientLaneAgentCards(st.topology.clients[0], []).length',
     '0',
     "negative: агентов нет — и блоков нет, пустых рамок не появляется"),
    ("agent_cards_carry_their_own_routes",
     'st.setTopology({ ...st.topology, proxies: PROXIES,'
     ' clients: [{ id: "c1", manual: true, agents: [{ id: "a1" }, { id: "a2" }] }] });',
     '(cards => [cards[0].html.includes("a1"), cards[0].html.includes("a2"), cards[1].html.includes("a2")])'
     '(m.clientLaneAgentCards(st.topology.clients[0], [{ agentId: "a1", routes: [{ role: "primary",'
     ' proxyId: "skynet:proxy:23001", endpoint: "e" }] }, { agentId: "a2", routes: [] }]))',
     '[true,false,true]',
     "boundary: блок агента несёт СВОИ маршруты, а не соседские"),
    ("manual_client_has_no_scope_sections",
     'st.setTopology({ ...st.topology, proxies: PROXIES,'
     ' clients: [{ id: "c1", manual: true, agents: [{ id: "a1" }] }] });',
     '(h => [h.split("<h3>").length - 1, h.split("topology-agent-group").length - 1])'
     '(m.topologyGroupedAgents(st.topology.clients[0], []))',
     '[0,1]',
     "ручной клиент показывает агентов списком: деление на HOST/VMS/DOCKER пересказывает отчёт скаута, которого у него нет"),
    ("scout_client_keeps_its_scope_sections",
     'st.setTopology({ ...st.topology, proxies: PROXIES,'
     ' clients: [{ id: "c1", agents: [{ id: "a1", scope: "host" }] }] });',
     '(h => [h.split("<h3>").length - 1, h.split("topology-agent-group").length - 1])'
     '(m.topologyGroupedAgents(st.topology.clients[0], []))',
     '[4,4]',
     "negative: у клиента от скаута четыре раздела остаются — там это настоящие сведения"),
    ("manual_client_without_agents_says_so",
     'st.setTopology({ ...st.topology, proxies: PROXIES,'
     ' clients: [{ id: "c1", manual: true, agents: [] }] });',
     'm.topologyGroupedAgents(st.topology.clients[0], []).includes("topology-empty-group")',
     'true',
     "boundary: ручной клиент без агентов показывает прочерк, а не пустоту без объяснения"),
    ("scout_owned_counts_both",
     'st.setTopology({ ...st.topology, proxies: PROXIES, clients: [{ id: "c1" }, { id: "c2" }],'
     ' assignments: { c1: { assignments: [{ agentId: "a1", routes: [] }, { agentId: "a2", routes: [] }] },'
     '                c2: { assignments: [{ agentId: "b1", manual: true, routes: [] }] } } });',
     'm.scoutOwnedCounts()',
     '{"clients":2,"agents":2}',
     "positive: считаются и клиенты, и их непомеченные строки; клиент с ручной строкой всё ещё скаутовский, потому что сам не помечен"),
    ("scout_owned_counts_nothing_left",
     'st.setTopology({ ...st.topology, proxies: PROXIES, clients: [{ id: "c1", manual: true }],'
     ' assignments: { c1: { assignments: [{ agentId: "a1", manual: true, routes: [] }] } } });',
     'm.scoutOwnedCounts()',
     '{"clients":0,"agents":0}',
     "negative: всё уже ручное — переносить нечего, кнопке появляться не на чем"),
    ("scout_owned_skips_controller",
     'st.setTopology({ ...st.topology, proxies: PROXIES, clients: [{ id: "controller" }],'
     ' assignments: { controller: { assignments: [{ agentId: "x", routes: [] }] } } });',
     'm.scoutOwnedCounts()',
     '{"clients":0,"agents":0}',
     "negative: сентинел контроллера не клиент скаута — в счёт не идёт"),
    ("scout_owned_manual_client_with_scout_row",
     'st.setTopology({ ...st.topology, proxies: PROXIES, clients: [{ id: "c1", manual: true }],'
     ' assignments: { c1: { assignments: [{ agentId: "a1", routes: [] }] } } });',
     'm.scoutOwnedCounts()',
     '{"clients":1,"agents":1}',
     "boundary: клиент уже ручной, а строка ещё нет — переносить есть что"),
    ("merge_marks_setting_that_lives_elsewhere",
     'st.setTopology({ ...st.topology, assignments: STORED({ contextLength: 8192 }), proxies: PROXIES,'
     ' clients: LIVE([{ role: "primary", proxyId: "skynet:proxy:23002", endpoint: "http://h:23002/v1" }]) });',
     'm.topologyBoardAssignmentsForHost("c1")[0].routes.map((r) => [r.proxyId, r.contextLength, r.settingsProxyId])',
     '[["skynet:proxy:23002",8192,"skynet:proxy:23001"]]',
     "defect-history: агент ушёл на другой порт — настройка едет на доску, но помечена ЧУЖИМ портом, иначе доска показывает то, чего нет в силе"),
    ("merge_no_mark_when_ports_agree",
     'st.setTopology({ ...st.topology, assignments: STORED({ contextLength: 8192 }), proxies: PROXIES,'
     ' clients: LIVE([{ role: "primary", proxyId: "skynet:proxy:23001", endpoint: "http://h:23001/v1" }]) });',
     'm.topologyBoardAssignmentsForHost("c1")[0].routes.map((r) => "settingsProxyId" in r)',
     '[false]',
     "negative: порты сошлись — метки нет, обычная строка без предупреждения"),
    ("merge_no_mark_without_live",
     'st.setTopology({ ...st.topology, assignments: STORED({ contextLength: 8192 }), proxies: PROXIES });',
     'm.topologyBoardAssignmentsForHost("c1")[0].routes.map((r) => "settingsProxyId" in r)',
     '[false]',
     "negative: живого отчёта нет — сравнивать не с чем, метки нет"),
    ("routes_rebuild_keeps_window",
     'st.setTopology({ ...st.topology, proxies: [{ id: "skynet:proxy:23001", port: 23001,'
     ' label: "p1", routerId: "r", contextLength: 8192, contextAuto: false }] });',
     'm.topologyProxyRoutes().map((r) => [r.port, r.contextLength, r.contextAuto])',
     '[[23001,8192,false]]',
     "defect-history: сохранение списка прокси ПЕРЕСОБИРАЕТ каждый маршрут — окно оператора обязано уцелеть"),
    ("routes_rebuild_keeps_auto_on",
     'st.setTopology({ ...st.topology, proxies: [{ id: "skynet:proxy:23001", port: 23001,'
     ' label: "p1", routerId: "r", contextAuto: true }] });',
     'm.topologyProxyRoutes().map((r) => ["contextLength" in r, r.contextAuto])',
     '[[false,true]]',
     "boundary: включённая галка переживает пересборку, а незаданного числа не появляется"),
    ("routes_rebuild_invents_nothing",
     'st.setTopology({ ...st.topology, proxies: [{ id: "skynet:proxy:23001", port: 23001,'
     ' label: "p1", routerId: "r" }] });',
     'm.topologyProxyRoutes().map((r) => ["contextLength" in r, "contextAuto" in r])',
     '[[false,false]]',
     "negative: чего оператор не задавал, пересборка не выдумывает — ноль читался бы как настоящий предел"),
    ("stored_only",
     'st.setTopology({ ...st.topology, assignments: STORED(), proxies: PROXIES });',
     'm.topologyBoardAssignmentsForHost("c1")[0].routes.map((r) => [r.role, r.proxyId])',
     '[["primary","skynet:proxy:23001"]]',
     "positive: без живого отчёта берётся сохранённая версия"),
    ("live_wins_role",
     'st.setTopology({ ...st.topology, assignments: STORED(), proxies: PROXIES,'
     ' clients: LIVE([{ role: "primary", proxyId: "skynet:proxy:23002", endpoint: "http://h:23002/v1" }]) });',
     'm.topologyBoardAssignmentsForHost("c1")[0].routes.map((r) => [r.role, r.proxyId])',
     '[["primary","skynet:proxy:23002"]]',
     "as-is: ЖИВОЙ отчёт побеждает по роли — сохранённый порт на доску не попадает"),
    ("live_empty_id_refilled",
     'st.setTopology({ ...st.topology, assignments: STORED(), proxies: PROXIES,'
     ' clients: LIVE([{ role: "primary", proxyId: "", endpoint: "http://h:23001/v1" }]) });',
     'm.topologyBoardAssignmentsForHost("c1")[0].routes.map((r) => [r.role, r.proxyId])',
     '[["primary","skynet:proxy:23001"]]',
     "defect-history: пустой proxyId живого отчёта ДОБИРАЕТСЯ из сохранённого — иначе кабель не рисуется"),
    ("empty_live_id_refilled_when_port_unknown",
     'st.setTopology({ ...st.topology, assignments: STORED(), proxies: PROXIES,'
     ' clients: LIVE([{ role: "primary", proxyId: "", endpoint: "http://h:29999/v1" }]) });',
     'm.topologyBoardAssignmentsForHost("c1")[0].routes.map((r) => r.proxyId)',
     '["skynet:proxy:23001"]',
     "defect-history: порт живого отчёта неизвестен каравану — id берётся из сохранённого, а не остаётся пустым"),
    ("live_endpoint_wins",
     'st.setTopology({ ...st.topology, assignments: STORED(), proxies: PROXIES,'
     ' clients: LIVE([{ role: "primary", proxyId: "skynet:proxy:23002", endpoint: "http://h:23002/v1" }]) });',
     'm.topologyBoardAssignmentsForHost("c1")[0].routes.map((r) => r.endpoint)',
     '["http://h:23002/v1"]',
     "positive: endpoint — поле ЖИВОСТИ, живой отчёт его диктует"),
    ("empty_live_endpoint_keeps_stored",
     'st.setTopology({ ...st.topology, assignments: STORED(), proxies: PROXIES,'
     ' clients: LIVE([{ role: "primary", proxyId: "skynet:proxy:23002", endpoint: "" }]) });',
     'm.topologyBoardAssignmentsForHost("c1")[0].routes.map((r) => r.endpoint)',
     '["http://h:23001/v1"]',
     "negative: пустой endpoint живого отчёта НЕ стирает сохранённый — пустота не сведение"),
    ("stored_setting_survives_merge",
     'st.setTopology({ ...st.topology, assignments: STORED({ contextLength: 131072 }), proxies: PROXIES,'
     ' clients: LIVE([{ role: "primary", proxyId: "skynet:proxy:23001", endpoint: "http://h:23001/v1" }]) });',
     'm.topologyBoardAssignmentsForHost("c1")[0].routes.map((r) => r.contextLength ?? null)',
     '[131072]',
     "positive: настройка из СОХРАНЁННОГО маршрута переживает слияние — её живой отчёт не диктует"),
    ("live_cannot_dictate_a_setting",
     'st.setTopology({ ...st.topology, assignments: STORED({ contextLength: 131072 }), proxies: PROXIES,'
     ' clients: LIVE([{ role: "primary", proxyId: "skynet:proxy:23001", endpoint: "http://h:23001/v1",'
     '                  contextLength: 8192 }]) });',
     'm.topologyBoardAssignmentsForHost("c1")[0].routes.map((r) => r.contextLength)',
     '[131072]',
     "negative: даже если бы живой отчёт нёс настройку, она НЕ побеждает сохранённую"),
    ("live_only_role_keeps_its_own",
     'st.setTopology({ ...st.topology, proxies: PROXIES, assignments: { c1: { agentUrl: "", assignments: [] } },'
     ' clients: LIVE([{ role: "primary", proxyId: "skynet:proxy:23002", endpoint: "http://h:23002/v1" }]) });',
     'm.topologyBoardAssignmentsForHost("c1")[0].routes.map((r) => [r.role, r.proxyId])',
     '[["primary","skynet:proxy:23002"]]',
     "boundary: роль, которой нет в сохранённом, берётся из живого целиком"),
    ("stored_setting_survives_without_live",
     'st.setTopology({ ...st.topology, assignments: STORED({ contextLength: 131072 }), proxies: PROXIES });',
     'm.topologyBoardAssignmentsForHost("c1")[0].routes.map((r) => r.contextLength ?? null)',
     '[131072]',
     "positive: та же настройка доходит и когда живого отчёта нет вовсе"),
    ("stored_fills_missing_role",
     'st.setTopology({ ...st.topology, proxies: PROXIES,'
     ' assignments: { c1: { agentUrl: "", assignments: [{ agentId: "a1", routes: ['
     '   { role: "primary", proxyId: "skynet:proxy:23001", endpoint: "http://h:23001/v1" },'
     '   { role: "fallback", proxyId: "skynet:proxy:23002", endpoint: "http://h:23002/v1" }] }] } },'
     ' clients: LIVE([{ role: "primary", proxyId: "skynet:proxy:23001", endpoint: "http://h:23001/v1" }]) });',
     'm.topologyBoardAssignmentsForHost("c1")[0].routes.map((r) => r.role).sort()',
     '["fallback","primary"]',
     "positive: роль, которой нет в живом отчёте, добирается из сохранённой версии"),
    ("plain_reader_prefers_live",
     'st.setTopology({ ...st.topology, assignments: STORED(), proxies: PROXIES,'
     ' clients: LIVE([{ role: "primary", proxyId: "skynet:proxy:23002", endpoint: "http://h:23002/v1" }]) });',
     'm.topologyAssignmentsForHost("c1")[0].routes.map((r) => r.proxyId)',
     '["skynet:proxy:23002"]',
     "as-is: простой читатель тоже предпочитает живой отчёт, без всякого слияния"),
    ("plain_reader_falls_back",
     'st.setTopology({ ...st.topology, assignments: STORED(), proxies: PROXIES, clients: [{ id: "c1", name: "C" }] });',
     'm.topologyAssignmentsForHost("c1")[0].routes.map((r) => r.proxyId)',
     '["skynet:proxy:23001"]',
     "negative: клиент без поля assignments — читается сохранённая версия"),
    ("unknown_host_empty",
     '',
     'm.topologyAssignmentsForHost("nope").length + m.topologyBoardAssignmentsForHost("nope").length',
     '0',
     "negative: незнакомый хост — пусто с обеих сторон, без исключения"),
]

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def main():
    if len(PINS) < 14:
        print(f"js client-proxies FAILED: всего {len(PINS)} пинов — снимок урезан")
        return 1
    node = find_node()
    if node is None:
        print("js client-proxies: SKIPPED — node не найден: " + ", ".join(node_search_paths()))
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
        print(f"js client-proxies FAILED: node вышел с кодом {run.returncode}")
        return 1
    both = json.loads(run.stdout.strip().splitlines()[-1])
    got, rev = both["out"], both["rev"]
    print("слияние сохранённого и живого:")
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
    print(f"js client-proxies OK: настоящий модуль в node, {len(PINS)} пинов слияния значениями")
    return 0


if __name__ == "__main__":
    sys.exit(main())
