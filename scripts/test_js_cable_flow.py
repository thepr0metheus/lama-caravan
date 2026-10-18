#!/usr/bin/env python3
"""Snapshot of static/js/cable-flow.js and static/js/pool-flow.js — the drops on the cables that carry a request now (1.3.549).

The owner, 2026-10-14: "the connections on the main board — make them like Routing's, keep how an active one is shown, dashes or
a drop, and carry that to Routing too". Two small modules stand behind it, both loaded FOR REAL (no neighbour stubbed: they have none):

  cable-flow.js — `CableFlow`: the twin of a cable, the markup the drops run along. What is pinned: the markup (a pair of paths of
    their own, one for each way, the cable's own line, the classes a hover finds them by, a lap and a delay of their own), where in
    its lap a twin made at a time stands — every twin reads the one clock, so a cable drawn anew goes on from where its drops were —
    and that a clock that says no time puts the drops at the start of their lap, not NaN in a style. Since 1.3.579 (the owner,
    2026-10-18: "make the drops come up and go down smoothly, not abruptly, and run both ways at once, not only left to right"): the
    way back runs half a lap behind the way there; the drops come up and go down along the cable (one gradient to a twin, opaque
    between the ends' 16 %); a cable that begins to carry a request brings its drops up over 600 ms, from nothing, and one that stops
    lets them go over 900 ms (a ghost the next drawing draws in its place), by the cable's key, whatever the number of drawings in
    between; and what is not a story — a cable that carries again before its drops are gone, one seen again after 3 s, one that
    stopped long ago, one with no key — is told as it is;
  pool-flow.js — `PoolFlow`: which of Routing's cables a request runs through, read from the monitor's rows. A request names its
    own way down the chain — the port it came in by (a client's), the pool and the row that serve it (`cloudPoolId`, `poolStepId`) —
    and the board's cables are named by those: client:<port>, set:<set>/<pool>, row:<pool>/<row>. What is pinned: the way of a
    request; that a queued one is not served yet, and a finished one lights its way for 8 s and no longer (the main board's reading
    of the same rows, topologyItemsActivity); that a client with no set has no cable of its own to light; that a pool the board does
    not draw lights nothing of itself; that a cable that is lit is not also "recent"; and the signature the board decides a drawing by.

Run: python3 scripts/test_js_cable_flow.py
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _node import find_node, node_search_paths  # noqa: E402

PREAMBLE = r"""
import "./_js_globals.mjs";
import { pathToFileURL } from "node:url";
const { CableFlow } = await import(pathToFileURL(process.env.JS_ROOT + "/cable-flow.js").href);
const { PoolFlow } = await import(pathToFileURL(process.env.JS_ROOT + "/pool-flow.js").href);
const NOW = 1000000;   // ms: 1000 s on the clock
const CLIENTS = [{ port: 23001, set: "S" }, { port: 23002, set: "" }, { port: 23003, set: "T" }];
const POOLS = [{ id: "P" }, { id: "Q" }];
const BOARD = { clients: CLIENTS, pools: POOLS };
const run = (item, port = 23001) => ({ [String(port)]: { port, active: [{ phase: "streaming", port, ...item }], recent: [] } });
const saw = (item, port = 23001) => ({ [String(port)]: { port, active: [], recent: [{ port, ...item }] } });
const list = (set) => [...set].sort();
const read = (agents, board = BOARD) => { const f = PoolFlow.of(board, agents, NOW); return { active: list(f.active), recent: list(f.recent), signature: f.signature }; };
const out = {};
"""

PINS = [
    # ── CableFlow ──
    ("lap_at", '', '[CableFlow.lapAt(0), CableFlow.lapAt(380), CableFlow.lapAt(NOW), CableFlow.lapAt(NOW + 379), CableFlow.lapAt("x"), CableFlow.lapAt(undefined), CableFlow.lapAt(Infinity)]',
     '[0,0,220,219,0,0,0]',
     "где в круге (380 мс) стоят капли в час now: остаток от деления на круг; negative: часы, что не говорят времени (не число, ничего, бесконечность), — начало круга, "
     "а не NaN в style"),
    ("lap_is_380", '', 'CableFlow.LAP_MS', '380', "круг — 380 мс: капли проходят один период узора (26px) за круг, 68px в секунду (cables.css, --flow-period)"),
    ("twin_markup", 'CableFlow.reset();', 'CableFlow.twin("M 0 0 C 1 1, 2 2, 3 3", "proxy-x route-a-b-primary", NOW)',
     json.dumps('<path class="cable-flow fwd proxy-x route-a-b-primary" d="M 0 0 C 1 1, 2 2, 3 3" style="animation-duration:380ms;animation-delay:-220ms"></path>'
                '<path class="cable-flow back proxy-x route-a-b-primary" d="M 0 0 C 1 1, 2 2, 3 3" style="animation-duration:380ms;animation-delay:-30ms"></path>'),
     "двойник каната — пара: два path на той же d, один бежит от начала к концу (fwd), другой от конца к началу (back), оба с классами каната, по которым их находят; "
     "круг и задержка — свои, из общих часов; без ключа и без точек — ни градиента, ни нарастания: капли просто есть"),
    ("twin_classes_are_taken_whole", 'CableFlow.reset();', '[CableFlow.twin("M 0 0", "", NOW), CableFlow.twin("M 0 0", "  proxy-x   route-y ", NOW), CableFlow.twin("M 0 0", undefined, NOW), CableFlow.twin("M 0 0", null, NOW)]'
     '.map((x) => x.match(/class="([^"]*)"/)[1])',
     '["cable-flow fwd","cable-flow fwd proxy-x route-y","cable-flow fwd","cable-flow fwd"]',
     "классы каната — по словам, лишние пробелы не в счёт; negative: у каната их нет, или не сказано вовсе — двойник с cable-flow и своей стороной, без пустых слов"),
    ("a_twin_is_a_pair_one_each_way", 'CableFlow.reset();', '(() => { const h = CableFlow.twin("M 5 5", "proxy-x", NOW); return [[...h.matchAll(/class="cable-flow (fwd|back)/g)].map((m) => m[1]), (h.match(/ d="M 5 5"/g) || []).length]; })()',
     '[["fwd","back"],2]', "пара: по пути на каждую сторону, оба на одной линии; negative: ни третьего пути, ни пути на одну сторону"),
    ("the_way_back_runs_half_a_lap_behind", 'CableFlow.reset();',
     '[0, 190, 379, 380, 570].map((t) => [...CableFlow.twin("M", "", t).matchAll(/animation-delay:-(\\d+)ms/g)].map((m) => Number(m[1])))',
     '[[0,190],[190,0],[379,189],[0,190],[190,0]]',
     "обратные капли идут на полкруга позади прямых: там, где прямые в начале круга, обратные на 190 мс дальше — две стороны не стоят друг на друге; "
     "negative: на границе круга (379, 380) фаза не сходит с ума"),
    ("twins_made_at_one_time_stand_alike", 'CableFlow.reset();', '[CableFlow.twin("M 0", "", NOW) === CableFlow.twin("M 0", "", NOW), CableFlow.twin("M 0", "", NOW) === CableFlow.twin("M 0", "", NOW + 380),'
     ' CableFlow.twin("M 0", "", NOW) === CableFlow.twin("M 0", "", NOW + 1)]', '[true,true,false]',
     "двойник, сделанный в одно время, — тот же; через круг — снова тот же (капли возвращаются на то же место); negative: через 1 мс — другая задержка, капли сдвинулись"),
    ("the_drops_come_up_and_go_down_along_the_cable", 'CableFlow.reset();',
     '(() => { const h = CableFlow.twin("M 1 2", "", NOW, { from: { x: 1, y: 2 }, to: { x: 3, y: 4 } });'
     ' return [h.match(/<linearGradient[^>]*>/)[0], [...h.matchAll(/offset="([^"]+)" stop-opacity="([^"]+)"/g)].map((m) => [Number(m[1]), Number(m[2])]),'
     ' (h.match(/stroke:url\\(#cf1\\) var\\(--accent-strong, var\\(--accent\\)\\);/g) || []).length, (h.match(/class="cable-flow-stop"/g) || []).length]; })()',
     json.dumps(['<linearGradient id="cf1" gradientUnits="userSpaceOnUse" x1="1" y1="2" x2="3" y2="4">', [[0, 0], [0.16, 1], [0.84, 1], [1, 0]], 2, 4]),
     "капли поднимаются и опускаются вдоль каната: градиент от начала к концу (в точках каната), прозрачный на концах и непрозрачный между 16 % и 84 % длины; "
     "им покрашены оба пути; цвет — у таблицы стилей (cable-flow-stop), в разметке его нет"),
    ("no_gradient_without_both_points", 'CableFlow.reset();',
     '[CableFlow.twin("M", "", NOW), CableFlow.twin("M", "", NOW, { from: { x: 0, y: 0 } }), CableFlow.twin("M", "", NOW, { to: { x: 1, y: 1 } }), CableFlow.twin("M", "", NOW, { key: "k" })]'
     '.map((h) => h.includes("linearGradient") || h.includes("stroke:url"))',
     '[false,false,false,false]', "negative: нет обеих точек, между которыми канат, — нет и градиента: капли стоят полным цветом, а не вдоль несуществующей линии"),
    ("one_gradient_to_a_twin", 'CableFlow.reset();',
     '[CableFlow.twin("M", "", NOW, { from: { x: 0, y: 0 }, to: { x: 1, y: 1 } }), CableFlow.twin("M", "", NOW, { from: { x: 0, y: 0 }, to: { x: 1, y: 1 } })].map((h) => h.match(/<linearGradient id="([^"]*)"/)[1])',
     '["cf1","cf2"]', "у каждого двойника свой градиент, свой номер: два каната на странице не красятся одним"),
    ("a_cable_that_begins_to_carry_comes_up", 'CableFlow.reset();',
     '[0, 300, 599, 600, 601].map((t) => { const h = CableFlow.twin("M", "", NOW + t, { key: "k" }); return [/ rising"/.test(h), (h.match(/animation-duration:([^;"]*)/) || [])[1], (h.match(/animation-delay:-[^,"]*,-(\\d+)ms/) || [])[1]]; })',
     json.dumps([[True, "380ms,600ms", "0"], [True, "380ms,600ms", "300"], [True, "380ms,600ms", "599"], [False, "380ms", None], [False, "380ms", None]]),
     "кабель, что начал нести запрос, поднимает капли за 600 мс: класс rising, второй круг — на нарастание, со сдвигом на сколько уже прошло, и перерисовки по пути его не сбрасывают; "
     "negative: на 600-й мс и позже — обычные капли, без нарастания, один круг"),
    ("a_cable_that_stops_lets_the_drops_go", 'CableFlow.reset(); CableFlow.twin("M 0", "", NOW, { key: "k" });',
     '[0, 100, 400, 899, 900, 2000].map((t) => { CableFlow.round(); const h = CableFlow.ghosts(NOW + 600 + t); return [(h.match(/ fading"/g) || []).length, (h.match(/animation-delay:-[^,"]*,-(\\d+)ms/) || [])[1] ?? null, CableFlow.seen.size]; })',
     json.dumps([[2, "0", 1], [2, "100", 1], [2, "400", 1], [2, "899", 1], [0, None, 0], [0, None, 0]]),
     "кабель, что перестал нести, отпускает капли за 900 мс: призрак — пара с классом fading, сдвиг на сколько уже прошло от первой перерисовки, где кабеля нет; "
     "negative: на 900-й мс призрака нет и в памяти его нет (seen пуст): он не копится"),
    ("a_ghost_keeps_its_cables_line_kin_and_points", 'CableFlow.reset(); CableFlow.twin("M 0 0", "proxy-x route-y", NOW, { key: "k", from: { x: 1, y: 2 }, to: { x: 3, y: 4 } }); CableFlow.round();',
     '(() => { const h = CableFlow.ghosts(NOW + 700); return [[...h.matchAll(/class="([^"]*)"/g)].map((m) => m[1]).filter((c) => c.startsWith("cable-flow ")),'
     ' (h.match(/<linearGradient[^>]*>/g) || []).map((x) => x.replace(/id="cf\\d+"/, \'id="cfN"\')), (h.match(/stroke:url\\(#cf\\d+\\)/g) || []).length, (h.match(/ d="M 0 0"/g) || []).length]; })()',
     json.dumps([["cable-flow fwd fading proxy-x route-y", "cable-flow back fading proxy-x route-y"], ['<linearGradient id="cfN" gradientUnits="userSpaceOnUse" x1="1" y1="2" x2="3" y2="4">'], 2, 2]),
     "призрак — тот же канат, каким его видели в последний раз: та же линия, те же классы, по которым его находят (наведение на точку), и тот же градиент между теми же точками, "
     "а не безликие капли на всю длину, у которых на концах не гаснет"),
    ("a_clock_that_is_no_number_is_the_clock_of_now", 'CableFlow.reset();',
     '(() => { const real = Date.now; Date.now = () => 5000000; try { CableFlow.twin("M", "", "x", { key: "a" }); CableFlow.twin("M", "", NaN, { key: "b" }); CableFlow.twin("M", "", undefined, { key: "c" });'
     ' return ["a", "b", "c"].map((k) => { const e = CableFlow.seen.get(k); return [e.since, e.last]; }); } finally { Date.now = real; } })()',
     '[[5000000,5000000],[5000000,5000000],[5000000,5000000]]',
     "negative: часы, что не говорят времени (не число, NaN, ничего), читаются как «сейчас»: у истории кабеля настоящие времена, а не NaN, из-за которого он не старел бы и не уходил"),
    ("a_clock_that_goes_back_is_no_negative_delay", 'CableFlow.reset();',
     '(() => { CableFlow.twin("M", "", NOW + 100, { key: "k" }); CableFlow.round(); const h = CableFlow.twin("M", "", NOW, { key: "k" });'
     ' return [/ rising"/.test(h), [...h.matchAll(/animation-delay:-(\\d+)ms,-(-?\\d+)ms/g)].map((m) => m[2])]; })()',
     '[true,["0","0"]]',
     "negative: часы, что пошли назад (поправили время), не дают отрицательной задержки: нарастание не раньше своего начала — «--100ms» в style значило бы мусор"),
    ("a_cable_that_carries_again_comes_up_from_where_its_drops_had_got_to", 'CableFlow.reset();',
     '[0, 450, 899, 900, 2300].map((g) => { CableFlow.reset(); CableFlow.twin("M 0", "", NOW, { key: "k" }); CableFlow.round(); CableFlow.ghosts(NOW + 700); CableFlow.round();'
     ' const delay = (h) => (h.match(/animation-delay:-[^,"]*,-(\\d+)ms/) || [])[1] ?? null;'
     ' const h = CableFlow.twin("M 0", "", NOW + 700 + g, { key: "k" }); CableFlow.round(); const next = CableFlow.twin("M 0", "", NOW + 700 + g + 100, { key: "k" });'
     ' return [/ rising"/.test(h), delay(h), / fading"/.test(h), CableFlow.ghosts(NOW + 700 + g), CableFlow.seen.get("k").ended, delay(next)]; })',
     json.dumps([[False, None, False, "", None, None], [True, "300", False, "", None, "400"], [True, "1", False, "", None, "101"], [True, "0", False, "", None, "100"], [True, "0", False, "", None, "100"]]),
     "кабель несёт снова, пока его капли ещё уходят, — они поднимаются с того места, до какого успели уйти, а не с нуля и не скачком к полной силе: "
     "ушли на долю g/900 — подъём начинается на 600·(1 − g/900) мс своих 600 (ease-in вниз и ease-out вверх — зеркала, так что это та же прозрачность); "
     "сразу же (g = 0) — капли на полной силе, без подъёма; на 450-й мс — подъём с 300-й; почти ушли (899) — с 1-й; ушли (900 и дольше, хоть призрака ещё не снимали) — с нуля; "
     "призрака больше нет, память о конце сброшена, а следующая перерисовка (через 100 мс) продолжает подъём с того же места: ушли дольше круга падения — "
     "подъём не уходит в будущее и не стоит нулём, пока часы его не догонят"),
    ("a_cable_seen_long_ago_begins_anew", '',
     '[2999, 3000, 3001, 60000].map((t) => { CableFlow.reset(); CableFlow.twin("M 0", "", NOW, { key: "k" }); CableFlow.round(); return / rising"/.test(CableFlow.twin("M 0", "", NOW + t, { key: "k" })); })',
     '[false,false,true,true]',
     "кабель, виденный несущим давно (больше 3 с назад), начинает заново — с нуля; negative: в пределах 3 с — продолжает, нарастание не заводится вновь"),
    ("a_cable_that_stopped_long_ago_has_no_ghost", 'CableFlow.reset(); CableFlow.twin("M 0", "", NOW, { key: "k" }); CableFlow.round();',
     '[CableFlow.ghosts(NOW + 4000), CableFlow.seen.size]', '["",0]',
     "negative: кабель, что перестал нести давно (первая перерисовка без него — через 4 с), призрака не получает: он уже отпустил бы капли, и его забывают"),
    ("a_drawn_cable_is_no_ghost", 'CableFlow.reset(); CableFlow.round(); CableFlow.twin("M 0", "", NOW, { key: "k" });',
     '[CableFlow.ghosts(NOW + 10), CableFlow.drawn.has("k")]', '["",true]',
     "negative: кабель, что нарисован в этой перерисовке, не призрак — призраки только у тех, кого в ней нет"),
    ("round_forgets_what_was_drawn", 'CableFlow.reset(); CableFlow.twin("M 0", "", NOW, { key: "k" });',
     '[CableFlow.drawn.size, (CableFlow.round(), CableFlow.drawn.size), CableFlow.seen.size]', '[1,0,1]',
     "новая перерисовка забывает, что нарисовала прежняя, но не историю каналов: кого в ней не будет, тот и остановился"),
    ("a_twin_with_no_key_has_no_story", 'CableFlow.reset();',
     '(() => { CableFlow.twin("M 0", "", NOW); CableFlow.round(); return [CableFlow.seen.size, CableFlow.ghosts(NOW + 100)]; })()', '[0,""]',
     "negative: двойник без ключа ни в чём не запоминается: нет ни нарастания, ни призрака — капли просто есть, пока их рисуют"),
    ("reset_forgets_everything", 'CableFlow.reset(); CableFlow.twin("M", "", NOW, { key: "k", from: { x: 0, y: 0 }, to: { x: 1, y: 1 } });',
     '(() => { CableFlow.reset(); return [CableFlow.seen.size, CableFlow.drawn.size, CableFlow.serial]; })()', '[0,0,0]', "reset: памяти нет, номеров нет — страница начинается заново"),
    # ── PoolFlow: the way of a request ──
    ("a_request_lights_its_way", '', 'read(run({ cloudPoolId: "P", poolStepId: "sub-1" }))',
     json.dumps({"active": ["client:23001", "row:P/sub-1", "set:S/P"], "recent": [], "signature": "client:23001|row:P/sub-1|set:S/P~"}),
     "запрос клиента 23001 (набор S), что служит пул P строкой sub-1, зажигает три каната: клиента, набора к пулу и строки к модели; подпись — активные, потом «~», потом недавние"),
    ("a_free_client_lights_only_the_row", '', 'read(run({ cloudPoolId: "P", poolStepId: "sub-1" }, 23002))',
     json.dumps({"active": ["row:P/sub-1"], "recent": [], "signature": "row:P/sub-1~"}),
     "negative: клиент без набора (2-й в списке) не имеет каната, который зажечь, и набор от него к пулу не идёт: горит одна строка пула"),
    ("a_port_that_is_no_client_lights_only_the_row", '', 'read(run({ cloudPoolId: "P", poolStepId: "sub-1" }, 23999))',
     json.dumps({"active": ["row:P/sub-1"], "recent": [], "signature": "row:P/sub-1~"}),
     "negative: запрос на порт пула (его не клиент набора) — горит строка пула и больше ничего"),
    ("a_request_with_no_pool_yet_lights_the_client", '', '[read(run({})), read(run({ cloudPoolId: "", poolStepId: "sub-1" })), read(run({ cloudPoolId: "P" }))]',
     json.dumps([{"active": ["client:23001"], "recent": [], "signature": "client:23001~"}, {"active": ["client:23001"], "recent": [], "signature": "client:23001~"},
                 {"active": ["client:23001", "set:S/P"], "recent": [], "signature": "client:23001|set:S/P~"}]),
     "запрос ещё не назвал пул (его выбирают) — горит канат клиента; пул назван, а строка ещё нет — горит и набор к пулу; "
     "negative: строка без пула ничего не зажигает: пул не назван"),
    ("a_pool_the_board_does_not_draw_lights_nothing_of_itself", '', 'read(run({ cloudPoolId: "ghost", poolStepId: "x" }))',
     json.dumps({"active": ["client:23001"], "recent": [], "signature": "client:23001~"}),
     "negative: пула, которого на доске нет, нет и в каналах: горит канат клиента, пока запрос идёт, и всё"),
    ("the_row_may_be_named_by_a_number", '', 'read(run({ cloudPoolId: "P", poolStepId: 0 }, 23002)).active',
     '["row:P/0"]', "id строки — строка, но 0 не пропадает за «ничего»: ноль — это тоже имя"),
    ("the_port_of_the_item_or_of_its_row", '', '[read({ "23001": { port: 23001, active: [{ phase: "streaming", cloudPoolId: "P", poolStepId: "a" }], recent: [] } }).active,'
     ' read({ "x": { port: 23003, active: [{ phase: "streaming", cloudPoolId: "Q", poolStepId: "b" }], recent: [] } }).active,'
     ' read({ "x": { port: 23003, active: [{ phase: "streaming", port: 23001, cloudPoolId: "Q", poolStepId: "b" }], recent: [] } }).active]',
     json.dumps([["client:23001", "row:P/a", "set:S/P"], ["client:23003", "row:Q/b", "set:T/Q"], ["client:23001", "row:Q/b", "set:S/Q"]]),
     "порт запроса — его собственный, а нет — порт строки монитора (строки лежат по портам); negative: собственный порт запроса сильнее порта строки"),
    # ── PoolFlow: when ──
    ("a_queued_request_is_not_served_yet", '', 'read(run({ phase: "queued", cloudPoolId: "P", poolStepId: "a" }))',
     json.dumps({"active": [], "recent": [], "signature": "~"}), "negative: запрос в очереди ещё не идёт — ничего не горит"),
    ("a_finished_request_lights_its_way_for_8_s", '',
     '[7999, 8000, 2000, 0].map((age) => read(saw({ cloudPoolId: "P", poolStepId: "a", finishedAt: (NOW - age) / 1000 })).recent)',
     json.dumps([["client:23001", "row:P/a", "set:S/P"], [], ["client:23001", "row:P/a", "set:S/P"], ["client:23001", "row:P/a", "set:S/P"]]),
     "закончившийся запрос зажигает свой путь на 8 с (то же окно, что у главной доски); negative: ровно 8 с назад и дальше — уже нет"),
    ("a_finished_request_with_no_time_lights_nothing", '', '[read(saw({ cloudPoolId: "P", poolStepId: "a" })), read(saw({ cloudPoolId: "P", poolStepId: "a", finishedAt: 0 })), read(saw({ cloudPoolId: "P", poolStepId: "a", finishedAt: "x" }))]',
     json.dumps([{"active": [], "recent": [], "signature": "~"}] * 3),
     "negative: у закончившегося запроса нет времени конца (или оно не число) — возраста не измерить, и путь не зажигается: «недавно» без срока — не новость"),
    ("a_lit_cable_is_not_also_recent", '',
     'read({ "23001": { port: 23001, active: [{ phase: "streaming", port: 23001, cloudPoolId: "P", poolStepId: "a" }], recent: [{ port: 23001, finishedAt: (NOW - 1000) / 1000, cloudPoolId: "P", poolStepId: "b" }] } })',
     json.dumps({"active": ["client:23001", "row:P/a", "set:S/P"], "recent": ["row:P/b"],
                 "signature": "client:23001|row:P/a|set:S/P~row:P/b"}),
     "канат, по которому идёт запрос, не назван ещё и недавним: горят оба запроса — путь активного целиком, у недавнего — своя строка (b)"),
    # ── PoolFlow: no reading ──
    ("nothing_to_read", '', '[read(undefined), read(null), read({}), read({ "23001": null }), read({ "23001": { port: 23001 } }), read({ "23001": { port: 23001, active: null, recent: "x" } }),'
     ' PoolFlow.of({}, run({ cloudPoolId: "P" }), NOW).signature, PoolFlow.of(undefined, undefined, NOW).signature]',
     json.dumps([{"active": [], "recent": [], "signature": "~"}] * 6 + ["~", "~"]),
     "negative: монитора нет, строки пусты или кривые, а у доски нет ни клиентов, ни пулов — пусто и «~», и не падает: «не знаю» — не «горит»"),
    ("the_signature_is_the_picture", '',
     '[read(run({ cloudPoolId: "P", poolStepId: "a" })).signature === read(run({ cloudPoolId: "P", poolStepId: "a" })).signature,'
     ' read(run({ cloudPoolId: "P", poolStepId: "a" })).signature === read(run({ cloudPoolId: "P", poolStepId: "b" })).signature,'
     ' read(run({ cloudPoolId: "P", poolStepId: "a" })).signature === read(saw({ cloudPoolId: "P", poolStepId: "a", finishedAt: (NOW - 1000) / 1000 })).signature]',
     '[true,false,false]',
     "подпись — картина: та же картина, та же подпись; negative: другая строка — другая; то же самое, но не идёт, а закончилось, — тоже другая (доска перерисует канаты лишь на смену)"),
]


_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def main():
    if len(PINS) < 30:
        print(f"js cable-flow FAILED: всего {len(PINS)} пинов — снимок урезан")
        return 1
    node = find_node()
    if node is None:
        print("js cable-flow: SKIPPED — node не найден: " + ", ".join(node_search_paths()))
        return 0

    def blocks(pins, sink):
        return [f"try {{ {setup}\n  {sink}[{json.dumps(pid)}] = {expr}; }} "
                f"catch (e) {{ {sink}[{json.dumps(pid)}] = {{ __threw: String(e && e.message || e) }}; }}"
                for pid, setup, expr, _exp, _msg in pins]

    # Pins don't depend on each other: the same set run in reverse order must give the same values.
    probe = (PREAMBLE + "\n".join(blocks(PINS, "out")) + "\nconst rev = {};\n"
             + "\n".join(blocks(list(reversed(PINS)), "rev"))
             + "\nconsole.log(JSON.stringify({ out, rev })); process.exit(0);\n")
    harness = ROOT / "scripts" / "_js_harness.mjs"
    path = ROOT / "scripts" / ".probe_js_cable_flow.tmp.mjs"
    path.write_text(probe)
    try:
        env = {**os.environ, "JS_ROOT": str(ROOT / "static" / "js"), "JS_STUBS": "",
               "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8", "TZ": "UTC"}
        run = subprocess.run(
            [node, "--import",
             f"data:text/javascript,import {{ register }} from 'node:module'; register('{harness.as_uri()}');",
             str(path)], capture_output=True, text=True, env=env, cwd=ROOT, timeout=120)
    finally:
        path.unlink(missing_ok=True)
    if run.returncode != 0:
        print(run.stdout)
        print(run.stderr)
        print(f"js cable-flow FAILED: node вышел с кодом {run.returncode}")
        return 1
    both = json.loads(run.stdout.strip().splitlines()[-1])
    got, rev = both["out"], both["rev"]
    print("капли на канатах: круг, двойник каната, путь запроса по Маршрутизации:")
    for pid, _s, _e, expected, msg in PINS:
        want, have = json.loads(expected), got.get(pid, "\0missing")
        check(have == want, msg if have == want else
              f"{msg}\n        ожидалось {json.dumps(want, ensure_ascii=False)[:300]}"
              f"\n        получено  {json.dumps(have, ensure_ascii=False)[:300]}")
        if have != rev.get(pid, "\0missing"):
            _fail.append(f"пин {pid} зависит от порядка")
    print()
    if _fail:
        print(f"FAILED ({len(_fail)}):")
        for m in _fail:
            print("  - " + m.splitlines()[0])
        return 1
    print(f"js cable-flow OK: настоящие модули в node, {len(PINS)} пинов значениями")
    return 0


if __name__ == "__main__":
    sys.exit(main())
