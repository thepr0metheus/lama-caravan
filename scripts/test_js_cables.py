#!/usr/bin/env python3
"""Snapshot of static/js/cables.js — the board's cables: geometry, classes, and a report of the missing.

The centerpiece here is `drawTopologyCables` and its `cableDrops`: a cable
with no anchor or binding used to vanish silently into filter(Boolean), and
the board looked "normal minus one curve" — that's how a missing agent cable
stayed hidden for a month (v1.3.92, the "absence rendered as normality"
defect class). Now every drop names the cable and the reason, with warnings
deduplicated. What's pinned by value: which cables get drawn, with which
classes (primary/fallback, priority, unverified with a tooltip, idle/active),
and WHAT gets recorded about the ones that can't be drawn.

Alongside that: pure geometry (a Bezier curve with a 48 minimum arm), anchor
points relative to the board, state/proxy/route classes, a deterministic
accent by key, apply status with the priority "assignment > client > stored".

The DOM is the `globalThis.__q` selector dict (querySelector by exact string)
and `globalThis.__fields` for svg; CSS.escape is the identity function. The
module is real, as are routers/topology-activity/topology-proxies;
`topology-dnd.topologyPointerDrag` is set via __stubValues before import.

Run: python3 scripts/test_js_cables.py
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _node import find_node, node_search_paths  # noqa: E402

STUBS = ("topology-dnd,canvas,polling,topology-render,dialogs,charts,cloud,history,favorites,config-locator,"
         "system-panels,onboarding,onboarding-tours,usage-stats,dialog-llamas,models-page,system-page,memory,"
         "command-preview,llama-edit,remote-cells,topology-nodes,topology-modals")

PREAMBLE = r"""
import "./_js_globals.mjs";
import { pathToFileURL } from "node:url";
const st = await import(pathToFileURL(process.env.JS_ROOT + "/state.js").href);
st.setState({ config: {} });
st.setTopology({ proxies: [], clients: [], routers: [], assignments: {} });
const R = (left, top, width = 40, height = 20) => ({ getBoundingClientRect: () => ({ left, top, width, height, right: left + width, bottom: top + height }) });
const LIVE_SRC = R(100, 100);
globalThis.__stubValues = { "topology-dnd.topologyPointerDrag": { source: LIVE_SRC } };
globalThis.CSS = { escape: (s) => String(s) };
globalThis.__q = {};
document.querySelector = (s) => (Object.prototype.hasOwnProperty.call(globalThis.__q, s) ? globalThis.__q[s] : null);
globalThis.__warns = []; console.warn = (...a) => { globalThis.__warns.push(String(a[1] ?? "")); };
const m = await import(pathToFileURL(process.env.JS_ROOT + "/cables.js").href);
const svgEl = () => ({ attrs: {}, innerHTML: "", live: null, setAttribute(k, v) { this.attrs[k] = v; }, querySelector(sel) { return sel === ".topology-cable.live" ? this.live : null; }, insertAdjacentHTML(_p, h) { this.innerHTML += h; } });
const svg = () => globalThis.__fields.topologyCables;
const SEL = {
  board: ".topology-board",
  handle: (h, a, r) => `[data-topology-route-handle][data-host-id="${h}"][data-agent-id="${a}"][data-route-role="${r}"]`,
  rin: (id) => `[data-topology-router-input][data-router-id="${id}"]`,
  rout: (id) => `[data-topology-router-output][data-router-id="${id}"]`,
  llama: (port) => `[data-topology-llama-input][data-llama-port="${port}"]`,
  cloud: (acc) => `[data-topology-cloud-input][data-account-id="${acc}"]`,
};
const TOPO = (extra = {}) => ({
  clients: [{ id: "box-a", name: "Box A", agents: [{ id: "hermes" }] }],
  assignments: { "box-a": { assignments: [{ agentId: "hermes", routes: [
    { role: "primary", proxyId: "ctl:proxy:23001" }, { role: "fallback", proxyId: "ctl:proxy:23002" }, { role: "embeddings", proxyId: "ctl:proxy:23009" }] }] } },
  proxies: [
    { id: "ctl:proxy:23001", port: 23001, routerId: "router:default", lastRequestAt: 1, priority: 2 },
    { id: "ctl:proxy:23002", port: 23002, routerId: "router:default" },
    { id: "ctl:proxy:23009", port: 23009 },
  ],
  routers: [{ id: "router:default", outputs: [
    { id: "srv:22001", upstreamType: "llama", upstreamHost: "127.0.0.1", upstreamPort: 22001 },
    { id: "cb:terra", upstreamType: "cloud", accountId: "acct", providerId: "cb:terra" },
    { id: "srv:22077", upstreamType: "llama", upstreamHost: "127.0.0.1", upstreamPort: 22077 },
  ] }],
  ...extra,
});
const DOM = () => { globalThis.__q = {
  [SEL.board]: R(0, 0, 1000, 600),
  [SEL.handle("box-a", "hermes", "primary")]: R(100, 100), [SEL.handle("box-a", "hermes", "fallback")]: R(100, 140), [SEL.handle("box-a", "hermes", "embeddings")]: R(100, 180),
  [SEL.rin("router:default")]: R(400, 120), [SEL.rout("router:default")]: R(440, 120),
  [SEL.llama(22001)]: R(700, 100), [SEL.cloud("acct")]: R(700, 200),
}; };
const MON = (port) => ({ latest: { agentProxies: { agents: { [String(port)]: { port, active: [{ phase: "running", port }], recent: [] } } } } });
const reset = () => { st.setState({ config: {} }); st.setTopology(TOPO()); st.ui.latestSystemMonitor = null; DOM();
  globalThis.__fields = { topologyCables: svgEl() }; globalThis.__warns.length = 0; m.cableDrops.length = 0; };
reset();
const paths = () => (svg().innerHTML.match(/<path class="([^"]*)"/g) || []).map((x) => x.slice(13, -1).replace(/\s+/g, " ").trim());
const out = {};
"""

PINS = [
    # ── geometry ──
    ("cable_path_bezier", '', 'm.topologyCablePath({ x: 0, y: 0 }, { x: 200, y: 100 })', '"M 0 0 C 96 0, 104 100, 200 100"', "кривая: плечо 48% расстояния по x"),
    ("cable_path_min_arm", '', 'm.topologyCablePath({ x: 0, y: 0 }, { x: 20, y: 50 })', '"M 0 0 C 48 0, -28 50, 20 50"', "boundary: близкие точки — плечо не короче 48"),
    ("svg_path_and_title", '', '[m.topologySvgPath({ x: 1, y: 2 }, { x: 3, y: 4 }, "c x", "a<b"), m.topologySvgPath(null, { x: 1, y: 1 }, "c"), m.topologySvgPath({ x: 1, y: 1 }, undefined, "c")]',
     '["<path class=\\"c x\\" d=\\"M 1 2 C 49 2, -45 4, 3 4\\"><title>a&lt;b</title></path>","",""]', "путь с экранированной подсказкой; без любой из точек — пусто"),
    ("svg_text", '', '[m.topologySvgText({ x: 5, y: 6 }, "<hi>"), m.topologySvgText({ x: 5, y: 6 }, ""), m.topologySvgText(null, "x")]',
     '["<text class=\\"topology-cable-label\\" x=\\"5\\" y=\\"6\\">&lt;hi&gt;</text>","",""]', "подпись экранирована; без текста или точки — пусто"),
    ("point_for_sides", '', '[m.topologyPointFor(R(100, 100, 40, 20), "left"), m.topologyPointFor(R(100, 100, 40, 20), "right"), m.topologyPointFor(R(100, 100, 40, 20))]',
     '[{"x":100,"y":110},{"x":140,"y":110},{"x":120,"y":110}]', "точка якоря относительно доски: левый край, правый край, центр; y — середина"),
    ("point_for_board_offset_and_missing", '', '(() => { globalThis.__q[SEL.board] = R(10, 20, 500, 500); const a = m.topologyPointFor(R(100, 100, 40, 20), "left"); delete globalThis.__q[SEL.board]; return [a, m.topologyPointFor(R(1, 1), "left"), m.topologyPointFor(null)]; })()',
     '[{"x":90,"y":90},null,null]', "смещение доски вычитается; без доски или элемента — null"),
    # ── classes ──
    ("status_class", '', '["error", "failed", "stale", "pending", "applied", "", undefined].map(m.topologyCableStatusClass)', '["status-error","status-error","status-warn","status-warn","status-ok","status-ok","status-ok"]',
     "статус кабеля: ошибка / предупреждение / ок по умолчанию"),
    ("proxy_and_route_class", '', '[m.topologyProxyClass("ctl:proxy:23001"), m.topologyProxyClass(""), m.topologyRouteClass("box a", "hermes", undefined)]', '["proxy-ctl-proxy-23001","proxy-","route-box-a-hermes-"]',
     "классы: всё, кроме [A-Za-z0-9_-], — в дефис"),
    ("accent_deterministic", '', '[m.topologyAccentStyle("hermes") === m.topologyAccentStyle("hermes"), m.topologyAccentStyle("hermes") !== m.topologyAccentStyle("scout"), m.topologyAccentColor("hermes", 0.5).endsWith("/ 0.5)"), m.topologyAccentStyle("") === m.topologyAccentStyle("item"), /^--topology-accent: hsl\\(\\d+ 70% 62%\\); --topology-accent-soft: hsl\\(\\d+ 70% 62% \\/ 0\\.13\\);$/.test(m.topologyAccentStyle("x"))]',
     '[true,true,true,true,true]', "акцент по ключу: детерминирован, разный для разных ключей, пустой ключ = item, формат стиля"),
    ("apply_state_precedence", 'st.setTopology(TOPO({ assignments: { "box-a": { assignments: [], applyStatus: { state: "pending" } } }, clients: [{ id: "box-a", applyStatus: { state: "error" } }, { id: "box-b", applyStatus: { state: "error" } }, { id: "box-c" }] }));',
     '[m.topologyApplyStateForHost("box-a"), m.topologyApplyStateForHost("box-b"), m.topologyApplyStateForHost("box-c"), m.topologyApplyStateForHost("ghost")]',
     '["pending","error","stored","stored"]', "статус применения: назначение > клиент > stored"),
    # ── drawTopologyCables ──
    ("draw_paths_and_viewbox", '', '(() => { m.drawTopologyCables(); return [svg().attrs.viewBox, paths().length]; })()',
     '["0 0 1000 600",4]', "viewBox из доски; нарисованы 2 кабеля клиента + 2 выхода роутера, 2 пропущены"),
    ("draw_segment1_classes", '', '(() => { m.drawTopologyCables(); return paths().slice(0, 2); })()',
     '["topology-cable primary idle priority proxy-ctl-proxy-23001 route-box-a-hermes-primary","topology-cable fallback unverified idle proxy-ctl-proxy-23002 route-box-a-hermes-fallback"]',
     "primary с приоритетом и трафиком — priority, idle без активности; fallback без единого запроса — unverified; классы прокси и маршрута для подсветки"),
    ("draw_unverified_has_title", '', '(() => { m.drawTopologyCables(); return (svg().innerHTML.match(/<title>/g) || []).length; })()', '1', "подсказка «не подтверждён» стоит ровно на непроверенном кабеле"),
    ("draw_segment3_classes", '', '(() => { m.drawTopologyCables(); return paths().slice(2); })()',
     '["topology-cable router idle","topology-cable router cloud idle"]', "выходы роутера: локальный и облачный, оба idle без активности"),
    ("draw_active_cable_lights", 'st.ui.latestSystemMonitor = MON(23001);', '(() => { m.drawTopologyCables(); return paths()[0]; })()',
     '"topology-cable primary priority activity-active health-ok proxy-ctl-proxy-23001 route-box-a-hermes-primary"', "активный запрос на порту — кабель без idle, с классами активности и здоровья (анимируется)"),
    ("draw_drops_named_with_reasons", '', '(() => { m.drawTopologyCables(); return m.cableDrops.map((d) => ({ ...d })); })()',
     '[{"what":"box-a/hermes embeddings -> router","routeHandleFound":true,"proxyId":"ctl:proxy:23009","proxyResolved":true,"routerId":"(unresolved)","routerInputFound":false},{"what":"router router:default -> srv:22077","routerOutputFound":true,"upstream":":22077","upstreamInputFound":false}]',
     "defect-class: невырисованный кабель НАЗВАН — и почему: прокси без роутера, выход без ячейки на доске"),
    ("draw_drop_warned_once", 'st.topology.assignments["box-a"].assignments[0].routes[2].proxyId = "ctl:proxy:" + Math.random().toString(36).slice(2);',
     '(() => { m.drawTopologyCables(); m.drawTopologyCables(); return [globalThis.__warns.filter((w) => w === "box-a/hermes embeddings -> router").length, m.cableDrops[0].proxyResolved]; })()',
     '[1,false]', "предупреждение в консоль — один раз на новую сигнатуру пропуска (дедуп переживает перерисовки), повторная отрисовка не дублирует"),
    ("draw_drops_rebuilt_each_draw", '', '(() => { m.drawTopologyCables(); globalThis.__q[SEL.rin("router:default")] = null; st.topology.proxies[2].routerId = "router:default"; m.drawTopologyCables(); return [m.cableDrops.length, m.cableDrops.map((d) => d.what)]; })()',
     '[4,["box-a/hermes primary -> router","box-a/hermes fallback -> router","box-a/hermes embeddings -> router","router router:default -> srv:22077"]]',
     "список пропусков пересобирается на каждой отрисовке: пропал вход роутера — пропали все три кабеля клиента"),
    ("draw_muted_when_live_report_says_unused", 'st.setTopology(TOPO({ clients: [{ id: "box-a", agents: [{ id: "hermes" }], assignments: [{ agentId: "hermes", routes: [{ role: "primary", proxyId: "ctl:proxy:23001" }] }] }] }));',
     '(() => { m.drawTopologyCables(); return paths().slice(0, 2); })()',
     '["topology-cable primary idle priority proxy-ctl-proxy-23001 route-box-a-hermes-primary","topology-cable fallback muted proxy-ctl-proxy-23002 route-box-a-hermes-fallback"]', "живой отчёт агента: роль вне отчёта — muted (и не idle), подтверждённая — без unverified"),
    ("draw_without_svg_or_board", '', '(() => { delete globalThis.__fields.topologyCables; m.drawTopologyCables(); globalThis.__fields = { topologyCables: svgEl() }; delete globalThis.__q[SEL.board]; m.drawTopologyCables(); return [svg().innerHTML, m.cableDrops.length]; })()',
     '["",0]', "negative: без svg или без доски — ничего не рисуется и не отмечается"),
    ("live_cable_replaces_previous", '', '(() => { const prev = { removed: 0, remove() { this.removed += 1; } }; svg().live = prev; m.drawLiveTopologyCable(300, 250); return [prev.removed, paths(), svg().innerHTML.includes("M 140 110 C")]; })()',
     '[1,["topology-cable live"],true]', "живой кабель при перетаскивании: прежний удалён, новый от правого края источника к курсору"),
    ("live_cable_without_board", 'delete globalThis.__q[SEL.board];', '(() => { m.drawLiveTopologyCable(300, 250); return svg().innerHTML; })()', '""', "negative: без доски живой кабель не рисуется"),
]


_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def main():
    if len(PINS) < 22:
        print(f"js cables FAILED: всего {len(PINS)} пинов — снимок урезан")
        return 1
    node = find_node()
    if node is None:
        print("js cables: SKIPPED — node не найден: " + ", ".join(node_search_paths()))
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
    path = ROOT / "scripts" / ".probe_js_cables.tmp.mjs"
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
        print(f"js cables FAILED: node вышел с кодом {run.returncode}")
        return 1
    both = json.loads(run.stdout.strip().splitlines()[-1])
    got, rev = both["out"], both["rev"]
    print("кабели доски: геометрия, классы, отчёт о невырисованных:")
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
    print(f"js cables OK: настоящий модуль в node, {len(PINS)} пинов кабелей значениями")
    return 0


if __name__ == "__main__":
    sys.exit(main())
