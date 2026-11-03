#!/usr/bin/env python3
"""Value snapshot: a local model's queue on Routing (static/js/model-queue.js, static/js/model-queue-settings.js; 1.3.663).

The owner, 2026-10-26: "several pools may go to one local model, so the queue is to be made on the model, not in the pool";
"let us first make one for all"; "let it be seconds and minutes"; of the mockups — "I like the new mockups, do it". The board
reads the monitor's requests and what the proxy says on each one in a model's queue (since when it waits, when it leaves and
where to — rust/crates/rules/src/model_queue.rs, QueueLeave) and works none of that out.

Pinned by value, each claim with its negative, with the real modules in node and the words from en.js:
  * the requests of one model from two pools gather in ONE queue — served and waiting, the waiting in the proxy's order; one
    still being routed, or on another model, or gone on to a subscription's row, is in none;
  * the model's line: "1 of 1 · 2 waiting"; nothing while it serves none and none waits; a slot count nobody said is "?";
  * a waiting request on its scale: waited, left, the bar's share, the ticks and labels of round steps, the mark of its end —
    the pool's next row by its number, or 503; one with no leave said: "no limit", no bar, no end;
  * a pool's row whose request waits: how long until it leaves;
  * the settings, one for all models: their twin of the proxy's table (names, defaults, bounds), the button's words, the two
    in words, the fields in their units (the limit in minutes), a value saved in seconds, a wrong one refused before it is sent.

Run: python3 scripts/test_js_model_queue.py
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _node import find_node, node_search_paths, probe_args  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
from _contract import Contract  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


PROBE = r'''
import "./_js_globals.mjs";
const { ModelQueue, QueueScale, QueueTime } = await import("../static/js/model-queue.js");
const { ModelQueueSettings } = await import("../static/js/model-queue-settings.js");
const NOW = 1800000000000;
const s = NOW / 1000;
const herm = { routedOutputId: "mm:herm", upstream: "box/herm" };
const agents = {
  "23001": { port: 23001, active: [
    { id: "c", route: "hermes", phase: "queued", cloudPoolId: "gpt", poolStepId: "r3", ...herm,
      queue: { since: s - 65, leaveAt: s - 65 + 90, leaveTo: "next", position: 1 } },
    { id: "x", route: "hermes", phase: "queued", queue: { queuedMs: 0, position: null } },
    { id: "y", route: "hermes", phase: "streaming", cloudPoolId: "gpt", poolStepId: "sub", routedOutputId: "mm:herm" } ] },
  "23005": { port: 23005, active: [
    { id: "a", route: "openwebui", phase: "streaming", cloudPoolId: "p4", poolStepId: "r1", ...herm, slotAt: s - 130, startedAt: s - 140 },
    { id: "b", route: "openwebui", phase: "queued", cloudPoolId: "p4", poolStepId: "r1", ...herm,
      queue: { since: s - 100, leaveAt: s - 100 + 1500, leaveTo: "refuse", position: 0 } },
    { id: "q", route: "openwebui", phase: "queued", cloudPoolId: "p4", poolStepId: "r9", routedOutputId: "mm:qwen", upstream: "box/qwen",
      slotAt: s - 5, queue: { since: s - 6 } } ] },
};
const ROWS = { "gpt/r3": "out:mm:herm", "p4/r1": "out:mm:herm", "gpt/sub": "acc:sub/sol", "p4/r9": "out:mm:qwen" };
// The board's rule (PoolBoard.queueKey, pinned in test_js_pool_board.py): a pool's row names the model, a subscription's row no queue.
const keyOf = (item) => { const key = ROWS[`${item.cloudPoolId}/${item.poolStepId}`] ?? (item.routedOutputId ? "out:" + item.routedOutputId : "");
  return key.startsWith("out:") ? key : ""; };
const slots = (group) => ({ "box/herm": 1 })[group];
const queues = ModelQueue.of(agents, keyOf, slots, NOW);
const hq = queues.get("out:mm:herm");
const html = hq.html((w) => (w.pool === "gpt" ? 2 : null));
const waits = html.split('<div class="pb-queue-wait"').slice(1);

// A request that says no leave, a model whose slots nobody said, and an empty queue.
const loose = ModelQueue.of({ "1": { active: [
  { id: "a", route: "agent", phase: "upstream", routedOutputId: "srv:9", upstream: "h:9", slotAt: s - 3 },
  { id: "b", route: "agent", phase: "queued", routedOutputId: "srv:9", upstream: "h:9", queue: { since: s - 40, leaveAt: null, leaveTo: null, position: 0 } },
  { id: "c", route: "agent", phase: "queued", routedOutputId: "srv:9", upstream: "h:9", queue: { since: s - 10, leaveAt: s + 5, leaveTo: "elsewhere", position: 1 } } ] } },
  (item) => "out:" + item.routedOutputId, () => undefined, NOW).get("out:srv:9");
const looseHtml = loose.html();
const empty = new ModelQueue("out:srv:1", NOW);
// A slot whose client's deadline the proxy said (received 140 s ago, everyone waits an hour), and one past it.
const timed = (deadline) => ModelQueue.of({ "1": { active: [{ id: "t", route: "agent", phase: "streaming", routedOutputId: "srv:9", upstream: "h:9",
  startedAt: s - 140, slotAt: s - 130, clientDeadline: deadline }] } }, (item) => "out:" + item.routedOutputId, () => undefined, NOW).get("out:srv:9").html();

// A served request on its client's scale (1.3.670): received 140 s ago and on its slot for 130 s, its client waiting an hour; one
// whose client gave up 20 s ago; one with no deadline said; one served the moment it came (no slotAt).
const runOf = (deadline, slotAt = s - 130) => { const q = ModelQueue.of({ "1": { active: [{ id: "t", route: "agent", phase: "streaming",
  routedOutputId: "srv:9", upstream: "h:9", startedAt: s - 140, slotAt, clientDeadline: deadline }] } }, (item) => "out:" + item.routedOutputId,
  () => undefined, NOW).get("out:srv:9"); return { span: q.runSpan(q.running[0]), slot: q.html().split('<div class="pb-queue-slot"')[1] || "" }; };
const runs = [runOf(s - 140 + 3600), runOf(s - 20), runOf(undefined), runOf(s - 140 + 3600, null)];

// The settings: a stand-in controller and toasts.
const calls = [], notes = [];
const settings = new ModelQueueSettings({ call: async (path, o) => { calls.push([path, JSON.parse(o.body)]); return { ok: true, config: { policy: { queueLimitSec: 1500 } } }; },
  notify: (x) => notes.push(x) });
const field = (key, value) => ({ dataset: { pbQueueField: key }, value });
const POLICY = { queueYieldSec: 90, queueLimitSec: 1500 };
const saved = await settings.save(field("queueLimitSec", "25"), POLICY);
const wrong = [field("queueLimitSec", "61"), field("queueYieldSec", "abc"), field("queueYieldSec", "1.25"), field("queueYieldSec", "26"), field("clientTimeoutSec", "0")];
for (const f of wrong) await settings.save(f, POLICY);
const halves = [];
const halfSaver = new ModelQueueSettings({ call: async (path, o) => { halves.push(JSON.parse(o.body).policy); return { ok: true }; }, notify: () => {} });
await halfSaver.save(field("queueYieldSec", "1.5"), POLICY);
await halfSaver.save(field("queueYieldSec", "25"), POLICY);
await halfSaver.save(field("queueYieldSec", "45"), { queueYieldSec: 90 });
const CAPS = [[90, 1500], [1800, 600], [1800, 0], [3600, 3600], [99999, 60], [0, 60]];
settings.open = true;
const panel = settings.panelHtml(POLICY);

console.log(JSON.stringify({
  keys: [...queues.keys()].sort(),
  running: hq.running.map((r) => [r.client, r.pool, r.since === s - 130]),
  waiting: hq.waiting.map((w) => [w.id, w.client, w.pool, w.row, w.leaveTo]),
  chip: hq.chip(), slotted: queues.get("out:mm:qwen").running.map((r) => r.id), qwenChip: queues.get("out:mm:qwen").chip().text,
  spans: hq.waiting.map((w) => { const x = hq.span(w); return [Math.round(x.waited), Math.round(x.total), Math.round(x.left), Number(x.fill.toFixed(1))]; }),
  rows: [hq.rowWait("gpt", "r3"), hq.rowWait("p4", "r1"), hq.rowWait("p4", "r9"), hq.rowWait("nope", "r3")],
  head: hq.waitingHead(),
  html: { state: html.includes('data-t-state="waiting"'), running: html.includes("running 2:10 · end unknown"), waits: waits.length,
    next: [waits[0].includes("next for the slot"), waits[1].includes("next for the slot")],
    fates: waits.map((w) => (w.match(/class="pb-queue-fate (\w+)"[^>]*>([^<]*)</) || []).slice(1)),
    fills: waits.map((w) => (w.match(/<i style="width: ([\d.]+)%"><\/i>/) || [])[1]),
    ticks: waits.map((w) => (w.match(/<s style="left: ([\d.]+%)"><\/s>/g) || []).map((x) => x.match(/left: ([\d.]+%)/)[1])),
    labels: waits.map((w) => (w.match(/<span class="(?:start|end|)" style="left: [\d.]+%">[^<]*<\/span>/g) || []).map((x) => x.replace(/<[^>]+>/g, ""))),
    times: waits.map((w) => (w.match(/<span class="pb-queue-time">(.*?)<\/span>/) || [])[1].replace(/<[^>]+>/g, "")),
    who: (() => { const named = hq.html(() => null, (id) => ({ gpt: "Standart", p4: "Pool-4" })[id] || id);
      const slot = named.split('<div class="pb-queue-slot"')[1] || "";
      return [html.includes("<b>hermes</b> · gpt<"), named.includes("<b>hermes</b> · Standart<"), slot.includes("<b>openwebui</b> · Pool-4<"),
        named.includes("· gpt<") || named.includes("· p4<")]; })() },
  loose: { slots: loose.slotsText, chip: loose.chip().text, rows: loose.rowWait("", ""), leaveTo: loose.waiting.map((w) => w.leaveTo),
    noBar: looseHtml.includes("pb-queue-scale none"), noFate: !looseHtml.includes("pb-queue-fate"), noLimit: looseHtml.includes("no limit"),
    head: loose.waitingHead() },
  empty: { chip: empty.chip(), html: empty.html().includes("Nobody is waiting") && empty.html().includes("Busy: 0 of ?") && empty.html().includes('data-t-state="idle"') },
  scales: [QueueScale.of(1500), QueueScale.of(90), QueueScale.of(10), QueueScale.of(270), QueueScale.of(0)].map((x) => [x.ticks, x.labels.map((l) => l.text)]),
  times: [QueueTime.clock(65), QueueTime.clock(3723), QueueTime.clock(-5), QueueTime.left(24.2), QueueTime.left(0), QueueTime.left(1400)],
  fields: ModelQueueSettings.FIELDS.map((f) => [f.key, f.fallback, f.min, f.max, f.per]),
  values: [ModelQueueSettings.values({}), ModelQueueSettings.values(POLICY), ModelQueueSettings.values({ queueYieldSec: -1, queueLimitSec: "x" }),
    ModelQueueSettings.values({ queueLimitSec: 99999, clientTimeoutSec: 30 }), ModelQueueSettings.values({ clientTimeoutSec: null })],
  timedRunning: [timed(s - 140 + 3600), timed(s - 200), timed(undefined)].map((h) => (h.match(/<span class="pb-queue-time run">([^<]*)<\/span>/) || [])[1]),
  runScale: runs.map(({ span, slot }) => [span && [Math.round(span.total), Number(span.queued.toFixed(1)), Number(span.ran.toFixed(1))],
    (slot.match(/<span class="pb-queue-bar (\w+)"/) || [])[1] ?? null, (slot.match(/<i style="width: ([\d.]+)%"><\/i>/) || [])[1] ?? null,
    (slot.match(/<i class="ran" style="left: ([\d.]+)%; width: ([\d.]+)%"><\/i>/) || []).slice(1),
    (slot.match(/<span class="(?:start|end|)" style="left: [\d.]+%">[^<]*<\/span>/g) || []).map((x) => x.replace(/<[^>]+>/g, "")),
    slot.includes('class="pb-queue-run"'), slot.includes('title="The scale is the client'), (slot.match(/aria-label="([^"]*)"/) || [])[1] ?? null]),
  caps: CAPS.map(([queueYieldSec, queueLimitSec]) => ModelQueueSettings.values({ queueYieldSec, queueLimitSec })),
  halves,
  pills: [ModelQueueSettings.pill({}), ModelQueueSettings.pill(POLICY), ModelQueueSettings.pill({ queueLimitSec: 90 }), ModelQueueSettings.pill({ queueYieldSec: 100 })],
  said: [ModelQueueSettings.said(POLICY), ModelQueueSettings.said({})],
  saved: [calls, saved && saved.ok, notes, wrong.map((f) => f.value)],
  panel: [panel.includes('min="0" max="25" step="0.5" inputmode="decimal" value="1.5" data-pb-queue-field="queueYieldSec"'), panel.includes('max="60" step="0.5"') === false, panel.includes('value="25" data-pb-queue-field="queueLimitSec"'),
    panel.includes('max="60"'), panel.includes('min="1" max="1440" step="1" inputmode="numeric" value="60" data-pb-queue-field="clientTimeoutSec"'),
    new ModelQueueSettings({}).panelHtml(POLICY),
    (() => { const o = new ModelQueueSettings({}); o.open = true; return o.panelHtml({ queueYieldSec: 90 }).includes('min="0" max="60" step="0.5"'); })()],
  button: [settings.buttonHtml(POLICY).includes(">Queue: 1.5 min · 25 min</button>"), settings.buttonHtml(POLICY).includes('aria-expanded="true"')],
}));
'''


def main():
    node = find_node()
    if node is None:
        print("js model queue: SKIPPED — node не найден ни в PATH, ни у менеджеров версий: " + ", ".join(node_search_paths()))
        return 0
    probe = ROOT / "scripts" / ".probe_model_queue.tmp.mjs"
    probe.write_text(PROBE, encoding="utf-8")
    try:
        env = {**os.environ, "JS_ROOT": str(ROOT / "static" / "js"), "JS_STUBS": "form", "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8", "TZ": "UTC"}
        proc = subprocess.run(probe_args(node, ROOT / "scripts" / "_js_harness.mjs", probe), capture_output=True, text=True, cwd=ROOT,
                              env=env, timeout=90)
    finally:
        probe.unlink(missing_ok=True)
    if proc.returncode != 0:
        print("js model queue: FAILED — харнесс не отработал")
        print(proc.stderr.strip()[:3000])
        return 1
    got = json.loads(proc.stdout.strip().splitlines()[-1])

    print("очередь модели на доске:")
    check(got["keys"] == ["out:mm:herm", "out:mm:qwen"],
          "запросы одной модели из двух пулов — одна очередь; negative: запрос, которого ещё маршрутизируют, и ушедший на строку подписки — ни в одной")
    check(got["running"] == [["openwebui", "p4", True]], "в слоте — запрос openwebui из Pool-4, с того мига, как получил слот (slotAt)")
    check(got["waiting"] == [["b", "openwebui", "p4", "r1", "refuse"], ["c", "hermes", "gpt", "r3", "next"]],
          "ждущие — в порядке прокси (position), а не в порядке портов; negative: у каждого своё «куда»")
    check(got["chip"] == {"text": "1 of 1 · 2 waiting", "title": "The model's queue: 1 of 1 slots busy, 2 waiting", "waiting": True},
          "строка модели: «1 из 1 · ждут 2», янтарная")
    check(got["slotted"] == ["q"] and got["qwenChip"] == "1 of ?",
          "запрос со slotAt — уже в слоте, хоть фаза ещё «queued»; negative: слотов никто не сказал — «?», а не 1")
    check(got["spans"] == [[100, 1500, 1400, 6.7], [65, 90, 25, 72.2]],
          "шкала ждущего: ждёт 100 из 1500 с (6,7%), ждёт 65 из 90 с (72,2%), сколько осталось")
    check(got["rows"] == ["waiting in the queue · 25 s left", "waiting in the queue · 23:20 left", None, None],
          "строка пула, чей запрос ждёт: «ждёт в очереди · ещё 25 с»; negative: строка без ждущих и чужой пул — ничего")
    check(got["head"] == "Waiting: 2 · longest — 1:40 · next leaves in 25 s", "над списком: сколько ждут, дольше всех, ближайший уход")
    h = got["html"]
    check(h["state"] and h["running"] and h["waits"] == 2, "полоса: состояние «ждут», слот «идёт 2:10 · конец неизвестен», два ждущих")
    check(h["next"] == [True, False], "первый в очереди помечен «следующий в слот»; negative: второй — нет")
    check(h["fates"] == [["refuse", "→ 503"], ["next", "→ row 2"]],
          "конец шкалы: уйти некуда — «→ 503»; есть готовая строка — «→ строка 2», по её номеру")
    check(h["fills"] == ["6.7", "72.2"], "закрашено столько, сколько ждёт")
    check(h["ticks"] == [["20%", "40%", "60%", "80%"], ["33.33%", "66.67%"]] and h["labels"] == [["0", "5", "10", "15", "20", "25 min"], ["0", "0:30", "1:00", "1:30"]],
          "деления: 25 мин — по 5 мин, подписи в минутах, у конца — единица; 90 с — по 30 с, подписи часами")
    check(h["times"] == ["waited 1:40 · 23:20 left", "waited 1:05 · 25 s left"], "слова у шкалы: сколько ждёт и сколько осталось")
    check(h["who"] == [True, True, True, False],
          "чей запрос: клиент и имя пула, каким его называет доска, — и у ждущего, и в слоте (владелец, 2026-10-26: id `gpt-6-1-sol` у чужой модели "
          "читался как модель запроса); negative: без имён — id, как сказал прокси; с именами id в полосе не остаётся")
    lo = got["loose"]
    check(lo["slots"] == "?" and lo["chip"] == "1 of ? · 2 waiting", "negative: слотов никто не сказал — «?»")
    check(lo["leaveTo"] == [None, None] and lo["noBar"] and lo["noFate"] and lo["noLimit"],
          "negative: запрос без ухода — «без предела», без шкалы и без конца; «куда», которого прокси не говорит, — не принято")
    check(lo["rows"] is None, "negative: запросы, пришедшие к модели напрямую, — ничьей строки пула")
    check(lo["head"] == "Waiting: 2 · longest — 0:40 · next leaves in 5 s",
          "ближайший уход — у того, кто его сказал; без предела в него не считается")
    check(got["empty"] == {"chip": None, "html": True}, "negative: пустая очередь — на строке ничего, в полосе «никто не ждёт», «занято 0 из ?»")
    check(got["scales"] == [[["20%", "40%", "60%", "80%"], ["0", "5", "10", "15", "20", "25 min"]],
                            [["33.33%", "66.67%"], ["0", "0:30", "1:00", "1:30"]],
                            [["50%"], ["0", "5", "10 s"]],
                            [["22.22%", "44.44%", "66.67%", "88.89%"], ["0", "1:00", "2:00", "3:00", "4:30"]],
                            [[], []]],
          "шкалы: минуты, часы, секунды; не целые минуты — часами, подпись у самого конца не ставится; negative: нет длины — нет шкалы")
    check(got["times"] == ["1:05", "1:02:03", "0:00", "25 s", "0 s", "23:20"],
          "время: часы с минутами, осталось — с округлением вверх (не «0» пока ждёт)")
    print()
    print("настройки очереди — одни на все модели:")
    tables = Contract.table("controller")
    twin = tables["modelQueueFields"]
    check([f[:4] for f in got["fields"]] == twin,
          "поля браузера — двойник правила прокси (contract/controller.json): имена, умолчания, границы")
    check([f[4] for f in got["fields"]] == [60, 60, 60],
          "1.3.681 (владелец, 2026-10-29: «не в секундах, а минутах»): все три поля вписываются в минутах; negative: терпение больше не в секундах")
    pairs = [(90, 1500), (1800, 600), (1800, 0), (3600, 3600), (99999, 60), (0, 60)]
    check(got["caps"] == [row["said"] for row in tables["modelQueueCaps"]]
          and [c["queueYieldSec"] for c in got["caps"]] == [90, 600, 1800, 3600, 60, 0],
          "терпение не дольше предела (владелец: «и не больше значения в „wait up to“») — браузер и прокси по одной таблице случаев; "
          "negative: предел 0 («без предела») не ограничивает терпение, только его собственная граница")
    unsaid = {"queueYieldSec": 0, "queueLimitSec": 0, "clientTimeoutSec": 3600}
    check(got["values"] == [unsaid, {**unsaid, "queueYieldSec": 90, "queueLimitSec": 1500}, unsaid,
                            {**unsaid, "queueLimitSec": 3600, "clientTimeoutSec": 60}, unsaid],
          "значения: несказанное и сломанное — умолчание (поведение без настройки; клиенты ждут час), лишнее — до границы, "
          "меньше минуты ожидания клиентов — минута, как у прокси; negative: null — не 0, а умолчание")
    check(got["timedRunning"] == ["running 2:10 · the client waits 57:40 more", "running 2:10 · the client waits 0 s more", "running 2:10 · end unknown"],
          "в слоте — сколько идёт и сколько ещё ждёт его клиент (срок сказал прокси: clientDeadline; владелец, 2026-10-26: «почему не известен?»); "
          "срок прошёл — «0 с», а не минус; negative: срока нет — «конец неизвестен», как прежде")
    rs = got["runScale"]
    check(rs[0] == [[3600, 0.3, 3.6], "run", "0.3", ["0.3", "3.6"], ["0", "15", "30", "45", "60 min"], False, True,
                    "running 2:10 · the client waits 57:40 more"],
          "в слоте — шкала клиента от прихода запроса до его тайм-аута (владелец, 2026-10-27: «почему конец неизвестен? мы знаем, когда "
          "начался запрос, и порог отключения»): янтарное — 10 с в очереди, полосы — 130 с работы, остальное — сколько клиент ещё ждёт; "
          "деления по 15 мин; negative: полосы без конца нет")
    check(rs[1][:5] == [[120, 8.3, 91.7], "run", "8.3", ["8.3", "91.7"], ["0", "0:30", "1:00", "1:30", "2:00"]],
          "клиент уже ушёл — шкала полная и не длиннее себя")
    check(rs[2] == [None, None, None, [], [], True, False, None],
          "negative: срока клиента прокси не сказал — ни шкалы, ни долей: полосы без конца, как прежде")
    check(rs[3][:4] == [[3600, 0.0, 3.9], "run", None, ["0", "3.9"]],
          "negative: запрос не ждал в очереди — янтарной доли нет, работа с нуля")
    # 1.3.670: the list is written anew on every reading of the monitor (PoolBoard.paintQueue fills `data-pb-queue-live`), so it
    # cannot be the scroller — its scroll went back to the top each time; and it is not held to 112px over an empty foot.
    css = (ROOT / "static" / "css" / "pool-board.css").read_text(encoding="utf-8")
    rule = lambda sel: (re.search(r"(?m)^" + re.escape(sel) + r" \{([^}]*)\}", css) or [None, ""])[1]
    check("overflow" not in rule(".pb-queue") and "max-height" not in rule(".pb-queue")
          and "overflow-y: auto" in rule(".pb-queue-live") and "minmax(0, 1fr)" in rule(".pb-queue-main"),
          "список очереди прокручивается в держателе, который остаётся (`.pb-queue-live`), и держатель берёт высоту полосы; "
          "negative: у самого списка, который переписывается каждую секунду, ни прокрутки, ни предела в 112 px (владелец, 2026-10-27: "
          "«вижу баг визуальный внизу» — второй ждущий был разрезан пополам)")
    check(got["pills"] == ["Queue: at once · no limit", "Queue: 1.5 min · 25 min", "Queue: at once · 1:30", "Queue: 1.67 min · no limit"],
          "кнопка в шапке «Модели»: «Очередь: 1,5 мин · 25 мин»; нули — «сразу» и «без предела»; сохранённое не кратным полминуте (100 с) — "
          "минуты с двумя знаками, а не длинная дробь")
    check(got["said"] == [["A busy model is waited for up to 1.5 min, then the pool's next ready row.",
                           "With nowhere to go — wait up to 25 min, then the client gets 503.",
                           "Clients wait up to 60 min — give your agents this timeout."],
                          ["A busy model gives way at once when the pool has somewhere to go.",
                           "With nowhere to go — wait until the client drops the request itself.",
                           "Clients wait up to 60 min — give your agents this timeout."]],
          "настройки словами и сколько ждут клиенты — тайм-аут, какой ставить агентам (владелец, 2026-10-26: «писать „установите такое вашему "
          "агенту, чтобы билось“», «я планирую всем агентам такой период ожидания поставить»); negative: нули сказаны как есть — "
          "«уступает сразу», «пока клиент не оборвёт»; ожидание клиентов несказанное — час")
    calls, ok, notes, wrong = got["saved"]
    check(calls == [["/api/agent-proxies/policy", {"policy": {"queueLimitSec": 1500}}]] and ok,
          "предел, вписанный в минутах (25), уходит в политику прокси секундами (1500)")
    yield_words = "From 0 to 25 min in half-minute steps, and no longer than the wait with nowhere to go"
    check(notes == ["Saved: the models' queue", "A whole number from 0 to 60", yield_words, yield_words, yield_words, "A whole number from 1 to 1440"]
          and wrong == ["25", "1.5", "1.5", "1.5", "60"],
          "negative: 61 мин, «abc», 1.25 (не шаг в полминуты), 26 мин при пределе 25, 0 мин ожидания клиентов — не отправлены, сказано, в каких "
          "границах, и поле вернулось к тому, что хранит контроллер")
    check(got["halves"] == [{"queueYieldSec": 90}, {"queueYieldSec": 1500}, {"queueYieldSec": 2700}],
          "терпение, вписанное в минутах: 1,5 → 90 с (нынешнее значение прода показывается и сохраняется как есть); ровно предел — можно; "
          "без предела — выше прежних 10 минут (45 мин), граница своя")
    check(got["panel"] == [True, True, True, True, True, "", True],
          "поля: терпение в минутах с шагом 0,5 и потолком — пределом (25), предел в минутах до 60, ожидание клиентов в минутах от 1 до 1440 "
          "(60 несказанное); без предела потолок терпения — его граница, 60 мин; negative: закрытая кнопка — полей нет")
    check(got["button"] == [True, True], "кнопка говорит обе настройки и что открыта")
    print()
    if _fail:
        print(f"js model queue FAILED ({len(_fail)}):")
        for msg in _fail:
            print("  - " + msg)
        return 1
    print("js model queue OK: one queue per model from every pool, its scales, and one setting for all models")
    return 0


if __name__ == "__main__":
    sys.exit(main())
