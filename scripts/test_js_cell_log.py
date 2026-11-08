#!/usr/bin/env python3
"""Value snapshot: a cell's log in its window (static/js/cell-log.js, 1.3.623).

The window's Log tab draws what the cell reported going wrong and, under it, the server's own log, read from its machine
through the controller (GET /api/cell-log?cell=<cellId> → the scout's GET /api/llama-node/log). What was read is kept by
cell id, outside the window, so a repaint of the lane keeps it; it is read when the tab opens and again on the poll's tick
while the cell runs and its present run is shown.

Pinned by value with a fake call, a fake clock and a fake page: the section in each state (never read, reading, read,
refused) and what it escapes, the words of a run, what a read asks and keeps (a refusal's own words, a throw, a second
read while one is under way), that no read names a machine or a port, the section drawn again where it stands with the
reader kept at the end, when the tick reads again and when it does not, and the clicks and the choice of a run. The words
come from static/js/i18n/en.js.

Run: python3 scripts/test_js_cell_log.py
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from _node import find_node, node_search_paths, probe_args  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def esc(text):
    """A word as the page writes it: escapeHtml of static/js/utils.js."""
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("'", "&#39;"))


PROBE = r"""
import "./_js_globals.mjs";
import { pathToFileURL } from "node:url";
const root = process.env.JS_ROOT;
const { CellLog } = await import(pathToFileURL(root + "/cell-log.js").href);
const en = (await import(pathToFileURL(root + "/i18n/en.js").href)).default;
const out = { en: Object.fromEntries(Object.entries(en).filter(([k]) => k.startsWith("cwLogTail"))) };

const RUNS = [{ name: "llama-server.c22001.log", bytes: 40, modifiedAt: 300 },
              { name: "llama-server.c22001.20261024-204735.log", bytes: 90, modifiedAt: 200 }];
const OK = { ok: true, hostId: "box", cellId: "c22001", run: "llama-server.c22001.log", lines: ["load <model>", "srv listening"], runs: RUNS };
let clock = 1000;
const asked = [];
const answers = [];
// Every address asked, kept whole: none may name a machine or a port (a cell holds a port only while it runs).
const everAsked = [];
const call = async (url) => { asked.push(url); everAsked.push(url); const a = answers.shift(); if (a instanceof Error) throw a; return a; };
const mk = () => new CellLog({ call, now: () => clock, when: (e) => `T${e}` });
const tags = (h, re) => [...h.matchAll(re)].map((m) => m[1]);

// The section in each state.
let log = mk();
out.idle = log.html("c22001");
out.idleLive = log.html("c22001", { live: true });
log.cells.set("c22001", { state: "loading" });
out.loading = log.html("c22001");
log.cells.set("c22001", { state: "error", error: "box: no log of cell c22001 <here>" });
out.error = log.html("c22001");
log.cells.set("c22001", { state: "ok", run: OK.run, runs: RUNS, lines: OK.lines, at: 1 });
out.ok = log.html("c22001", { live: true });
out.okStill = log.html("c22001", { live: false });
log.cells.set("c22001", { state: "ok", run: RUNS[1].name, runs: RUNS, lines: ["old"], at: 1 });
out.okEarlier = log.html("c22001", { live: true });
log.cells.set("c22001", { state: "ok", run: OK.run, runs: [RUNS[0]], lines: [], at: 1 });
out.okOneEmpty = log.html("c22001", { live: true });
log.cells.set("c22001", { state: "ok", run: OK.run, runs: RUNS, lines: OK.lines, at: 1, busy: true });
out.okBusy = log.html("c22001");
out.present = ["llama-server.c22001.log", "llama-server.c22001.20261024-204735.log", "command-cell.c3f9a02b1.20261024-204735-1.log", ""]
  .map((n) => CellLog.present(n));

// A read: what it asks, what it keeps.
log = mk();
answers.push(OK);
out.loaded = await log.load("c22001");
out.askedFirst = asked.splice(0);
answers.push({ ...OK, run: RUNS[1].name, lines: ["the crash"] });
await log.load("c22001", { run: RUNS[1].name });
out.askedRun = asked.splice(0);
answers.push({ ok: false, error: "box: its scout 2.35.4 is older than 2.36.0" });
out.refused = await log.load("c22001");
answers.push({ ok: false });
out.refusedBare = await log.load("c22001");
answers.push(new Error("Network down"));
out.thrown = await log.load("c22001");
asked.splice(0);
let release;
const slow = new CellLog({ call: (url) => { asked.push(url); return new Promise((r) => { release = r; }); }, now: () => clock, when: (e) => `T${e}` });
const first = slow.load("c22001");
out.during = slow.of("c22001");
out.second = await slow.load("c22001");
out.askedOnce = asked.splice(0).length;
release(OK);
await first;
out.afterSlow = slow.of("c22001").state;

// Drawn again where it stands, the reader kept at the end.
const page = () => {
  const lines = { scrollTop: 0, clientHeight: 100, scrollHeight: 400 };
  const view = { dataset: { cellLogLive: "1" }, outerHTML: "", querySelector: (s) => (s === ".cw-tail-lines" ? lines : null) };
  const fresh = { scrollTop: 0, scrollHeight: 900 };
  const doc = { asked: [], querySelector(s) { this.asked.push(s); return s.endsWith(" .cw-tail-lines") ? fresh : (s.startsWith("[data-cell-log-view=") ? view : null); } };
  return { doc, view, lines, fresh };
};
log = mk();
log.cells.set("c22001", { state: "ok", run: OK.run, runs: RUNS, lines: OK.lines, at: 1 });
let p = page();
p.lines.scrollTop = 300;
log.paint(p.doc, "c22001");
out.paintEnd = [p.view.outerHTML === log.html("c22001", { live: true }), p.fresh.scrollTop, p.doc.asked[0]];
p = page();
p.lines.scrollTop = 50;
log.paint(p.doc, "c22001");
out.paintUp = p.fresh.scrollTop;
out.paintNone = (() => { const doc = { querySelector: () => null }; log.paint(doc, "c22001"); return "quiet"; })();

// The tick.
const tickPage = (key, live) => {
  const view = { dataset: { cellLogView: key, cellLogLive: live ? "1" : "" } };
  return { querySelector: (s) => (s.includes('[data-cell-window-panel="log"]:not([hidden])') ? view : null) };
};
log = mk();
out.tickNoWindow = log.tick({ querySelector: () => null });
answers.push(OK);
await log.tick(tickPage("c22001", true));
out.tickIdle = asked.splice(0);
clock += 4999;
out.tickSoon = log.tick(tickPage("c22001", true));
clock += 1;
answers.push(OK);
await log.tick(tickPage("c22001", true));
out.tickDue = asked.splice(0);
clock += 10000;
out.tickStill = log.tick(tickPage("c22001", false));
log.cells.set("c22001", { ...log.of("c22001"), run: RUNS[1].name });
out.tickEarlier = log.tick(tickPage("c22001", true));
log.cells.set("c22001", { ...log.of("c22001"), state: "error", run: OK.run });
out.tickError = log.tick(tickPage("c22001", true));
log.cells.set("c22001", { ...log.of("c22001"), state: "ok", busy: true });
out.tickBusy = log.tick(tickPage("c22001", true));

// Clicks and the choice of a run.
log = mk();
const el = (data, closest = {}) => ({ dataset: data, value: data.value || "", closest: (s) => closest[s] ?? null });
const quiet = { querySelector: () => null };
answers.push(OK);
const show = el({ cellLogShow: "c22001" });
await log.onClick({ target: el({}, { "[data-cell-log-show], [data-cell-log-refresh]": show }) }, quiet);
out.clickShow = asked.splice(0);
answers.push(OK);
const refresh = el({ cellLogRefresh: "c22001" });
log.cells.set("c22001", { ...log.of("c22001"), run: RUNS[1].name });
await log.onClick({ target: el({}, { "[data-cell-log-show], [data-cell-log-refresh]": refresh }) }, quiet);
out.clickRefresh = asked.splice(0);
const win = { dataset: { tId: "c3f9a02b1" }, querySelector: (s) => (s === "[data-cell-log-view]" ? {} : null) };
const tab = el({}, { ".cell-window": win });
answers.push(OK);
await log.onClick({ target: el({}, { '[data-cell-window-tab="log"]': tab }) }, quiet);
out.clickTab = asked.splice(0);
out.clickTabAgain = log.onClick({ target: el({}, { '[data-cell-window-tab="log"]': tab }) }, quiet);
const bare = { dataset: { tId: "c5e01d7aa" }, querySelector: () => null };
out.clickTabNoView = log.onClick({ target: el({}, { '[data-cell-window-tab="log"]': el({}, { ".cell-window": bare }) }) }, quiet);
out.clickElse = log.onClick({ target: el({}) }, quiet);
answers.push(OK);
const pick = el({ cellLogRun: "c22001", value: RUNS[1].name });
await log.onChange({ target: el({}, { "[data-cell-log-run]": pick }) }, quiet);
out.changeRun = asked.splice(0);
out.changeElse = log.onChange({ target: el({}) }, quiet);
out.everAsked = everAsked;
console.log(JSON.stringify(out));
"""


def main():
    node = find_node()
    if node is None:
        print("js cell-log: SKIPPED — node не найден ни в PATH, ни у менеджеров версий: " + ", ".join(node_search_paths()))
        return 0
    probe = ROOT / "scripts" / ".probe_cell_log.tmp.mjs"
    probe.write_text(PROBE, encoding="utf-8")
    try:
        env = {"JS_ROOT": str(ROOT / "static" / "js"), "PATH": "/usr/bin:/bin", "JS_STUBS": "command-preview,favorites,llama-edit,form,remote-cells,cloud,topology-render,polling"}
        proc = subprocess.run(probe_args(node, ROOT / "scripts" / "_js_harness.mjs", probe), capture_output=True,
                              text=True, cwd=ROOT, env=env, timeout=60)
    finally:
        probe.unlink(missing_ok=True)
    if proc.returncode != 0:
        print("js cell-log: FAILED — харнесс не отработал")
        print(proc.stderr.strip()[:1500])
        return 1
    got = json.loads(proc.stdout.strip().splitlines()[-1])
    en = got["en"]

    print("секция в каждом состоянии:")
    idle = got["idle"]
    check('data-cell-log-view="c22001" data-cell-log-live=""' in idle and 'data-t="cell-log" data-t-id="c22001" data-t-state="idle"' in idle
          and esc(en["cwLogTailTitle"]) in idle and esc(en["cwLogTailLead"]) in idle
          and f'data-cell-log-show="c22001" data-t="cell-log-show" data-t-id="c22001">{en["cwLogTailShow"]}</button>' in idle,
          "не прочитан — заголовок, строка о чём это и кнопка «Show the log»; секция помнит ключ ячейки")
    check('data-cell-log-live="1"' in got["idleLive"] and 'data-cell-log-live=""' not in got["idleLive"],
          "работающая ячейка — секция помечена живой (по метке тик перечитывает)")
    check('data-t-state="loading"' in got["loading"] and en["cwLogTailLoading"] in got["loading"] and "cell-log-show" not in got["loading"],
          "читается — крутится и так и пишет; negative: кнопки нет, второго чтения не нажать")
    err = got["error"]
    check('data-t-state="error"' in err and "box: no log of cell c22001 &lt;here&gt;" in err and 'role="alert"' in err
          and f'>{en["cwLogTailRetry"]}</button>' in err,
          "отказ — его собственные слова, экранированы, и «Try again»")
    ok = got["ok"]
    check('data-t-state="ok"' in ok and '<pre class="cw-tail-lines" data-t="cell-log-lines" data-t-id="c22001">load &lt;model&gt;\nsrv listening</pre>' in ok,
          "прочитан — строки как есть, экранированы, одна под другой")
    check('<option value="llama-server.c22001.log" selected>' + en["cwLogTailNow"].replace("{time}", "T300") + "</option>" in ok
          and '<option value="llama-server.c22001.20261024-204735.log">' + en["cwLogTailBefore"].replace("{time}", "T200") + "</option>" in ok
          and 'data-cell-log-run="c22001" data-t="cell-log-run"' in ok,
          "выбор запуска — этот запуск и прежний, со временем последней строки; выбран читаемый")
    check(en["cwLogTailCount"].replace("{n}", "2") in ok and 'data-cell-log-refresh="c22001" data-t="cell-log-refresh"' in ok,
          "сколько строк и «Refresh»")
    check(en["cwLogTailLive"] in ok and en["cwLogTailLive"] not in got["okStill"] and en["cwLogTailLive"] not in got["okEarlier"],
          "«перечитывается» — только у работающей и только на этом запуске; negative: у стоящей и у прежнего запуска — нет")
    one = got["okOneEmpty"]
    check("<select" not in one and '<span class="cw-tail-run-one">' + en["cwLogTailNow"].replace("{time}", "T300") + "</span>" in one
          and en["cwLogTailEmpty"] in one and "cw-tail-lines" not in one,
          "один запуск — без выбора, просто подпись; пустой журнал — словами, а не пустая рамка")
    check(got["okBusy"].count(" disabled") == 2, "пока читается снова — выбор и «Refresh» закрыты")
    check(got["present"] == [True, False, False, False], "этот запуск — журнал без отметки времени; прежние — с отметкой rotate")

    print("чтение:")
    check(got["askedFirst"] == ["/api/cell-log?cell=c22001"] and got["loaded"]["state"] == "ok"
          and got["loaded"]["lines"] == ["load <model>", "srv listening"] and got["loaded"]["run"] == "llama-server.c22001.log"
          and got["loaded"]["at"] == 1000,
          "читает через контроллер по имени ячейки (cell=); держит строки, запуск, список и когда прочитано")
    check(got["askedRun"] == ["/api/cell-log?cell=c22001&run=llama-server.c22001.20261024-204735.log"],
          "прежний запуск — его имя уходит в запросе")
    ever = got["everAsked"]
    check(len(ever) >= 8 and all(u.startswith("/api/cell-log?cell=") and "hostId" not in u and "port" not in u for u in ever),
          "negative: ни один запрос журнала не называет ни машину, ни порт — только имя ячейки: порт у неё лишь пока она работает, "
          "и журналы идут за её именем, на каком бы порту она ни работала")
    check(got["refused"]["state"] == "error" and got["refused"]["error"] == "box: its scout 2.35.4 is older than 2.36.0"
          and got["refused"]["lines"] == ["the crash"],
          "отказ — его слова; negative: прочитанное раньше не стирается молча, состояние говорит «ошибка»")
    check(got["refusedBare"]["error"] == en["cwLogTailNone"], "отказ без слов — «The log could not be read», а не пусто")
    check(got["thrown"]["state"] == "error" and got["thrown"]["error"] == "Network down", "исключение — его текст, тоже ошибкой")
    check(got["during"]["state"] == "loading" and got["during"]["busy"] is True and got["second"]["busy"] is True
          and got["askedOnce"] == 1 and got["afterSlow"] == "ok",
          "negative: второе чтение, пока идёт первое, не уходит — один запрос; после ответа — прочитано")

    print("перерисовка на месте:")
    check(got["paintEnd"] == [True, 900, '[data-cell-log-view="c22001"]'],
          "секция заменена той же разметкой, метка «живая» сохранена; читатель был в конце — остаётся в конце")
    check(got["paintUp"] == 50, "читатель прокрутил вверх — остаётся на своей строке, конец его не дёргает")
    check(got["paintNone"] == "quiet", "negative: секции на странице нет — ничего, без ошибки")

    print("тик:")
    check(got["tickNoWindow"] is None, "negative: ни одно окно не показывает журнал — тик ничего не читает")
    check(got["tickIdle"] == ["/api/cell-log?cell=c22001"], "вкладка открыта, журнал не прочитан — читается")
    check(got["tickSoon"] is None and got["tickDue"] == ["/api/cell-log?cell=c22001&run=llama-server.c22001.log"],
          "работающая, этот запуск — раз в 5 с, не чаще; перечитывается тот же запуск")
    check(got["tickStill"] is None and got["tickEarlier"] is None and got["tickError"] is None and got["tickBusy"] is None,
          "negative: стоящая, прежний запуск, ошибка, чтение уже идёт — тик не читает")

    print("клики и выбор запуска:")
    check(got["clickShow"] == ["/api/cell-log?cell=c22001"], "«Show the log» — читает новейший запуск")
    check(got["clickRefresh"] == ["/api/cell-log?cell=c22001&run=llama-server.c22001.20261024-204735.log"],
          "«Refresh» — перечитывает тот запуск, что выбран")
    check(got["clickTab"] == ["/api/cell-log?cell=c3f9a02b1"] and got["clickTabAgain"] is None,
          "вкладка «Журнал» (или путь к ней с полосы) — читает сразу, а не к следующему тику; negative: уже прочитан — второй раз нет")
    check(got["clickTabNoView"] is None and got["clickElse"] is None,
          "negative: у окна нет секции журнала (ячейка движка) или клик мимо — ничего")
    check(got["changeRun"] == ["/api/cell-log?cell=c22001&run=llama-server.c22001.20261024-204735.log"]
          and got["changeElse"] is None,
          "выбор запуска — читает выбранный; negative: изменение другого поля — ничего")

    print()
    if _fail:
        print(f"js cell-log FAILED ({len(_fail)}):")
        for m in _fail:
            print("  - " + m.splitlines()[0])
        return 1
    print("js cell-log OK: секция, чтение, перерисовка, тик и клики журнала ячейки — значениями")
    return 0


if __name__ == "__main__":
    sys.exit(main())
