#!/usr/bin/env python3
"""Snapshot of static/js/usage-stats.js — the cost and token figures the operator reads.

The usage modal assembles HTML from a stats object; the values in it — money
and tokens — are exactly what the operator goes there for. VALUES are
pinned: rounding money, keeping token figures exact, prompt+completion sums,
the mini-list's three-row cap, escaping model names, an unsaved rate edit
taking priority over the saved one.

The module is loaded into node FOR REAL (scripts/_js_harness.mjs); i18n is real too.

Run: python3 scripts/test_js_usage_stats.py
"""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _node import find_node, node_search_paths  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


PROBE = r"""
import "./_js_globals.mjs";
import { pathToFileURL } from "node:url";
const m = await import(pathToFileURL(process.env.JS_ROOT + "/usage-stats.js").href);
const st = await import(pathToFileURL(process.env.JS_ROOT + "/state.js").href);
const i18n = await import(pathToFileURL(process.env.JS_ROOT + "/i18n.js").href);
const S = {
  cloud: { total: 12.3456, requests: 7, promptTokens: 1000, completionTokens: 500,
           byModel: [{model: "gpt-x", cost: 12.3456}, {model: "<b>evil</b>", cost: 0.5},
                     {model: "third", cost: 0.25}, {model: "fourth", cost: 0.1}, {model: "fifth", cost: 0.05}] },
  local: { requests: 3, promptTokens: 20000, completionTokens: 5000, wouldCost: 0.0123,
           byModel: [{model: "gemma", promptTokens: 20000, completionTokens: 5000}] },
  rate: { inputPer1M: 2, outputPer1M: 8 },
};
const out = {
  money: [0, 0.5, 1, 12.345, null, NaN, -3, "abc"].map(m.usMoney),
  tok: [1234567, 0, null, "12"].map(m.usTok),
  overview: m.usageStatsOverview(S),
  overviewEmpty: m.usageStatsOverview({}),
  table_empty: m.usageStatsModelTable([], "cloud"),
  table_cloud: m.usageStatsModelTable(S.cloud.byModel.slice(0, 2), "cloud"),
  table_local: m.usageStatsModelTable(S.local.byModel, "local"),
  detail_saved: m.usageStatsLocalDetail(S),
};
st.ui.usageStatsRateEdit = { inputPer1M: 3.5, outputPer1M: "junk" };
out.detail_edit = m.usageStatsLocalDetail(S);
out.reset_bad = m.formatSubUsageReset("nonsense");
// "Today" is the given clock's day, local time — not the wall clock's.
const CLOCK = new Date(2031, 0, 10, 12, 0, 0);
out.reset_today = m.formatSubUsageReset(new Date(2031, 0, 10, 23, 30).toISOString(), CLOCK);
out.reset_far = m.formatSubUsageReset("2031-03-15T10:20:00Z", CLOCK);
out.reset_midnight = m.formatSubUsageReset(new Date(2031, 0, 11, 0, 0, 30).toISOString(), new Date(2031, 0, 10, 23, 59, 30));
// The banner above the bars.
const LIM = (weekly, extra = []) => [{ label: "5h limit", name: "", remainingPct: 99, resetsAt: "2031-03-15T10:20:00Z" }, { label: "Weekly limit", name: "", remainingPct: weekly, resetsAt: "2031-03-15T10:20:00Z" }, ...extra];
out.banner_blocked = m.subscriptionBannerHtml({ ok: true, limits: LIM(0), credits: null, limitReached: true, creditsInfo: { hasCredits: false }, upsell: { title: "You’re out", description: "Use your banked reset", ctas: ["Reset usage"] } });
out.banner_credits = m.subscriptionBannerHtml({ ok: true, limits: LIM(0), credits: 395, limitReached: true, creditsInfo: { hasCredits: true }, upsell: null });
out.banner_reserve = m.subscriptionBannerHtml({ ok: true, limits: LIM(0, [{ label: "gpt-reserve · Weekly limit", name: "gpt-reserve", remainingPct: 80, resetsAt: "" }]), credits: null, limitReached: true, creditsInfo: { hasCredits: false }, upsell: null });
out.banner_warn = m.subscriptionBannerHtml({ ok: true, limits: LIM(0), credits: null, limitReached: false, creditsInfo: { hasCredits: false }, upsell: null });
out.banner_none = m.subscriptionBannerHtml({ ok: true, limits: LIM(40), credits: null, limitReached: false, creditsInfo: {}, upsell: null });
out.banner_notok = m.subscriptionBannerHtml({ ok: false });
m.subscriptionUsageCache.set("acc", { data: { ok: true, limits: LIM(0), credits: null, limitReached: true, creditsInfo: { hasCredits: false }, upsell: null }, fetchedAt: 1 });
const panel = m.subscriptionUsageHtml("acc");
out.banner_order = [panel.indexOf("sub-usage-banner"), panel.indexOf("sub-usage-row")];
// The refresh button: in the panel's head by default; a card that keeps it elsewhere (a pool rung) asks for none
// here and takes it from subscriptionRefreshHtml.
const noBtn = m.subscriptionUsageHtml("acc", { refresh: false });
out.refresh_panel = [panel.includes('class="sub-usage-head"') && panel.includes('data-usage-refresh="acc"'), noBtn.includes("data-usage-refresh"), noBtn.includes("sub-usage-head"), noBtn.includes("sub-usage-row") && noBtn.includes("sub-usage-banner")];
m.subscriptionUsageCache.set("r-ok", { data: { ok: true, limits: LIM(50) }, fetchedAt: 1 });
m.subscriptionUsageCache.set("r-busy", { data: { ok: true, limits: LIM(50) }, fetchedAt: 1, loading: true });
m.subscriptionUsageCache.set("r-failed", { data: null, error: "boom", fetchedAt: 1 });
m.subscriptionUsageCache.set("r-empty", { data: { ok: false }, fetchedAt: 1 });
m.subscriptionUsageCache.set('r"q', { data: { ok: true, limits: LIM(50) }, fetchedAt: 1 });
const btnOf = (id) => m.subscriptionRefreshHtml(id);
out.refresh_button = {
  ok: [btnOf("r-ok").includes('data-usage-refresh="r-ok"'), btnOf("r-ok").includes("spinning"), btnOf("r-ok").includes("disabled"), btnOf("r-ok").startsWith("<button"), btnOf("r-ok").includes("<svg")],
  busy: [btnOf("r-busy").includes("spinning"), btnOf("r-busy").includes("disabled")],
  failed: btnOf("r-failed").includes('data-usage-refresh="r-failed"'),
  empty: btnOf("r-empty"), none: btnOf("never-read"), quoted: btnOf('r"q').includes('data-usage-refresh="r&quot;q"'),
  panelSame: m.subscriptionUsageHtml("r-busy").includes(btnOf("r-busy")),
};
// What the button says it does: it only reads. "Refresh" read as "renew" to the one who pressed it.
const said = i18n.t("usTitleRereadLimits");
out.refresh_words = [said !== "usTitleRereadLimits", said !== i18n.t("usTitleRefreshLimits"), btnOf("r-ok").includes(`title="${said}"`), btnOf("r-ok").includes(`aria-label="${said}"`), btnOf("r-ok").includes(i18n.t("usTitleRefreshLimits"))];

// ── «30 дней через караван»: одна строка; доли моделей — в их строках (cloud-models.js) ──
out.compact = [0, 999, 1000, 1500, 359627986, 1e9, 12345678901, null].map(m.compactCount);
globalThis.__fetchReply["/api/cloud-accounts/proxy-spend"] = { spend: { sub: { windowDays: 30, total: 698.73, requests: 5429,
  promptTokens: 359000000, completionTokens: 627986, byModel: [{ model: "GPT-5.6-TERRA", cost: 547.38 }] } } };
out.spend_unread = m.proxySpendHtml("x", { zero: true });
await m.fetchProxySpend();
out.spend = { api: m.proxySpendHtml("sub"), sub: m.proxySpendHtml("sub", { subscription: true }),
  asked: m.proxySpendHtml("sub", { open: true, subscription: true }), none: m.proxySpendHtml("other"),
  zero: m.proxySpendHtml("other", { zero: true }), zeroOwn: m.proxySpendHtml("sub", { zero: true }) === m.proxySpendHtml("sub"),
  of: m.proxySpendOf("sub")?.byModel?.[0]?.model || null, ofNone: m.proxySpendOf("other"),
  cost: [{ total: 698.73 }, { total: 0 }, { total: 1234567.4 }, { total: 0.4 }, null, {}, { total: "12.5" },
    { total: 0.004 }, { total: 0.005 }, { total: 12 }, { total: 99.999 }, { total: 100 }, { total: 0.07 }, { total: 1.22 }].map(m.spendCost) };

// ── возврат на вкладку перечитывает то, что устарело ──
const NOW = 1_000_000;
const MIN = m.RETURN_REFRESH_MIN_AGE_MS;
const C = (entries) => new Map(entries);
out.stale_old = m.staleReadings(C([["a", { data: {}, fetchedAt: NOW - MIN - 1 }]]), NOW);
out.stale_fresh = m.staleReadings(C([["a", { data: {}, fetchedAt: NOW - MIN + 1 }]]), NOW);
out.stale_boundary = m.staleReadings(C([["a", { data: {}, fetchedAt: NOW - MIN }]]), NOW);
out.stale_loading = m.staleReadings(C([["a", { loading: true, fetchedAt: 0 }]]), NOW);
out.stale_never = m.staleReadings(C([["a", {}]]), NOW);
out.stale_failed = m.staleReadings(C([["a", { data: null, error: "boom", fetchedAt: NOW - MIN - 1 }]]), NOW);
out.stale_mixed = m.staleReadings(C([
  ["old", { data: {}, fetchedAt: NOW - MIN - 1 }],
  ["fresh", { data: {}, fetchedAt: NOW }],
  ["busy", { loading: true, fetchedAt: 0 }],
]), NOW);
out.stale_empty = m.staleReadings(C([]), NOW);
out.min_age = MIN;
out.readings = Object.keys(m.USAGE_READINGS).sort();
// действие: спросить заново — то же, что делает кнопка ↻; прежнее чтение остаётся на карточке
m.subscriptionUsageCache.set("gone", { data: { ok: true, limits: LIM(70) }, fetchedAt: NOW });
const sentBefore = globalThis.__fetchCalls.length;
const didRefresh = m.refreshUsageReading("subscription", "gone");
const after = m.subscriptionUsageCache.get("gone");
out.refresh_keeps = [didRefresh, after?.data?.ok ?? null, !!after?.loading, globalThis.__fetchCalls.length - sentBefore];
out.refresh_drawn = [m.subscriptionUsageHtml("gone").startsWith('<div class="sub-usage-panel refreshing" aria-busy="true"'),
  m.subscriptionUsageHtml("gone").includes("sub-usage-row")];
// второй щелчок, пока первое чтение в полёте, второго запроса не шлёт
const sentMid = globalThis.__fetchCalls.length;
m.refreshUsageReading("subscription", "gone");
out.refresh_in_flight = globalThis.__fetchCalls.length - sentMid;
// первое чтение, когда показать ещё нечего: строка со спиннером, а не пустота
m.subscriptionUsageCache.set("first", { data: null, fetchedAt: 0, loading: true });
m.subscriptionUsageCache.set("first-failed", { data: null, error: "boom", fetchedAt: 1, loading: true });
out.first_read = [m.subscriptionUsageHtml("first"), m.subscriptionUsageHtml("first-failed").includes("sub-usage-spinner"),
  m.subscriptionUsageHtml("r-ok").includes("refreshing"), m.subscriptionUsageHtml("r-ok").includes("aria-busy")];
out.refresh_unknown_kind = m.refreshUsageReading("sorcery", "gone");
out.refresh_no_id = m.refreshUsageReading("subscription", "");
// ── два порога шага пула на полосках лимитов (2026-09-28, шаги — 2026-10-10, два порога — 2026-10-11) ──
const LIMR = { label: "5h limit", name: "", remainingPct: 15, resetsAt: "2031-03-15T10:20:00Z", windowSeconds: 18000 };
const STEPR = (switchAt, stopAt, extra = {}) => ({ poolId: "p<1>", stepId: "s<1>", switchAt, stopAt, switchMax: 90, ...extra });
out.row_two = m.subscriptionLimitRowHtml("acc<1>", LIMR, STEPR({ "18000": 40 }, { "18000": 10 }));
// Routing's model (1.3.486): the handles name the model by its account and model, not a pool's row.
out.row_model = m.subscriptionLimitRowHtml("acc<1>", LIMR, { accountId: "sub<1>", model: "gpt<1>", switchAt: { "18000": 40 }, stopAt: { "18000": 10 }, switchMax: 90 });
out.row_same = m.subscriptionLimitRowHtml("acc", LIMR, STEPR({ "18000": 20 }, { "18000": 20 }));
out.row_below = m.subscriptionLimitRowHtml("acc", LIMR, STEPR({ "18000": 5 }, { "18000": 30 }));
out.row_off = m.subscriptionLimitRowHtml("acc", LIMR, STEPR({}, {}));
out.row_nolen = m.subscriptionLimitRowHtml("acc", { ...LIMR, windowSeconds: null }, STEPR({ "18000": 20 }, { "18000": 20 }));
out.row_nomax = m.subscriptionLimitRowHtml("acc", LIMR, STEPR({ "18000": 20 }, { "18000": 20 }, { switchMax: undefined }));
out.row_nostep = m.subscriptionLimitRowHtml("acc", LIMR);
out.row_over = m.subscriptionLimitRowHtml("acc", LIMR, STEPR({ "18000": 95 }, { "18000": 95 }));
// живой показ, пока ручку тянут: стоп толкает переключение вверх, переключение не опускается ниже стопа
function fakeRow(stop, next) {
  const mk = (value) => { const cls = new Set(); return { value: String(value), max: "90", style: {}, hidden: false, textContent: "", cls, classList: { toggle: (c, on) => { if (on) cls.add(c); else cls.delete(c); } } }; };
  const els = { stop: mk(stop), next: mk(next), zoneStop: mk(0), zoneNext: mk(0), markNext: mk(0), markStop: mk(0) };
  const by = { ".sub-usage-switch.stop": els.stop, ".sub-usage-switch.switch": els.next, ".sub-usage-zone.stop": els.zoneStop,
    ".sub-usage-zone.switch": els.zoneNext, '[data-level-mark="switch"]': els.markNext, '[data-level-mark="stop"]': els.markStop };
  const row = { querySelector: (sel) => by[sel] || null };
  els.stop.closest = els.next.closest = () => row;
  return els;
}
const look = (e) => [e.stop.value, e.next.value, e.zoneStop.style.width, e.zoneNext.style.left, e.zoneNext.style.width,
  e.markNext.hidden ? null : e.markNext.textContent, e.markStop.hidden ? null : e.markStop.textContent, [...e.next.cls].join(), [...e.stop.cls].join(),
  [e.markNext.style.left, e.markNext.style.right], [e.markStop.style.left, e.markStop.style.right]];
let fr = fakeRow(10, 30); fr.next.value = "45"; m.previewSwitchLevel(fr.next); out.preview_switch = look(fr);
fr = fakeRow(10, 30); fr.stop.value = "50"; m.previewSwitchLevel(fr.stop); out.preview_stop_pushes = look(fr);
fr = fakeRow(20, 40); fr.next.value = "5"; m.previewSwitchLevel(fr.next); out.preview_switch_rests = look(fr);
fr = fakeRow(20, 40); fr.stop.value = "0"; m.previewSwitchLevel(fr.stop); out.preview_no_stop = look(fr);
fr = fakeRow(10, 30); fr.next.value = "72"; m.previewSwitchLevel(fr.next); out.preview_past_middle = look(fr);
out.row_past_middle = m.subscriptionLimitRowHtml("acc", LIMR, STEPR({ "18000": 72 }, { "18000": 51 }));
const KEPT = { windowSeconds: 18000, remainingPct: 15, reservePct: 20, resetAt: Math.floor(Date.parse("2031-03-15T10:20:00Z") / 1000) };
out.banner_kept = m.subscriptionBannerHtml({ ok: true, limits: [LIMR], credits: null, limitReached: false, creditsInfo: {} }, { switchReached: KEPT });
out.banner_stopped = m.subscriptionBannerHtml({ ok: true, limits: [LIMR], credits: null, limitReached: false, creditsInfo: {} }, { switchReached: KEPT, stopReached: KEPT });
// что значат ручки — одной строкой под полосками шага, и только там
m.subscriptionUsageCache.set("legend", { data: { ok: true, limits: [LIMR] }, fetchedAt: 1 });
out.legend = [m.subscriptionUsageHtml("legend", { step: STEPR({ "18000": 40 }, { "18000": 10 }) }).includes('data-t="pool-levels-legend"'),
  m.subscriptionUsageHtml("legend").includes("pool-levels-legend")];
out.signs = Object.fromEntries(Object.entries(m.LEVEL_HANDLES).map(([level, h]) => [level, h.sign]));
out.legend_html = m.subscriptionUsageHtml("legend", { step: STEPR({ "18000": 40 }, { "18000": 10 }) }).match(/<div class="sub-usage-legend"[^>]*>(.*?)<\/div>/)?.[1] ?? null;
out.banner_kept_blocked = m.subscriptionBannerHtml({ ok: true, limits: [LIMR], credits: null, limitReached: true, creditsInfo: { hasCredits: false }, upsell: null }, { switchReached: KEPT });
out.banner_kept_noreset = m.subscriptionBannerHtml({ ok: true, limits: [LIMR], credits: null, limitReached: false, creditsInfo: {} }, { switchReached: { ...KEPT, resetAt: 0 } });
out.banner_no_step = m.subscriptionBannerHtml({ ok: true, limits: [LIMR], credits: null, limitReached: false, creditsInfo: {}, reserveKept: KEPT });
globalThis.__fetchReply["/api/pools/level"] = { ok: true, switchAt: { "18000": 30 }, stopAt: { "18000": 30 }, topology: { pools: ["after"] } };
const applied = [];
const calls0 = globalThis.__fetchCalls.length;
await m.saveSwitchLevel({ value: "30", dataset: { poolSwitch: "work", stepId: "sub", windowSeconds: "18000", level: "stop" } }, (top) => applied.push(top));
const sent = globalThis.__fetchCalls.slice(calls0).find((c) => c.path === "/api/pools/level");
out.saved = [applied, sent ? JSON.parse(sent.body) : null, sent?.method || null];
const calls1 = globalThis.__fetchCalls.length;
await m.saveSwitchLevel({ value: "20", dataset: { levelAccount: "sub", levelModel: "gpt-6-sol", windowSeconds: "604800", level: "switch" } }, () => {});
const sentModel = globalThis.__fetchCalls.slice(calls1).find((c) => c.path === "/api/pools/level");
out.saved_model = sentModel ? JSON.parse(sentModel.body) : null;
globalThis.__fetchReply["/api/pools/level"] = { __status: 400, ok: false, error: "pct must be 0..90" };
const toastEl = { textContent: "", classList: { add() {}, remove() {} } };
const keepGet = document.getElementById;
document.getElementById = (id) => (id === "toast" ? toastEl : keepGet.call(document, id));
const appliedAfterFail = [];
try {
  await m.saveSwitchLevel({ value: "95", dataset: { poolSwitch: "work", stepId: "sub", windowSeconds: "18000", level: "switch" } }, (top) => appliedAfterFail.push(top));
} finally {
  document.getElementById = keepGet;
}
out.saved_failed = [appliedAfterFail, toastEl.textContent];
// перетаскивание: флаг снимается на ЛЮБОМ отпускании, отложенная перерисовка случается один раз
const listeners = {};
globalThis.window.addEventListener = (type, fn) => { (listeners[type] ||= []).push(fn); };
globalThis.window.removeEventListener = (type, fn) => { listeners[type] = (listeners[type] || []).filter((f) => f !== fn); };
let redraws = 0;
m.switchDrag.begin(() => { redraws += 1; });
const during = m.switchDrag.active;
m.switchDrag.deferred = true;
(listeners.pointerup || []).slice().forEach((fn) => fn());
out.drag = [during, m.switchDrag.active, redraws, (listeners.pointerup || []).length, (listeners.pointercancel || []).length];
m.switchDrag.begin(() => { redraws += 1; });
(listeners.pointercancel || []).slice().forEach((fn) => fn());
out.drag_cancel_no_defer = [m.switchDrag.active, redraws];
// ── the limits drawn small (1.3.541): a window one line, the stop levels as ticks on its bar ──
const LIMW = (label, pct, seconds) => ({ label, name: "", remainingPct: pct, windowSeconds: seconds, resetsAt: "2031-03-15T10:20:00Z" });
const READ = (id, data, extra = {}) => m.subscriptionUsageCache.set(id, { data, fetchedAt: 1, ...extra });
READ("mt", { ok: true, limits: [LIMW("5H", 49, 18000), LIMW("WEEKLY", 89, 604800)] });
READ("mt-one", { ok: true, limits: [LIMW("5H", 49, 18000)] });
READ("mt-nolen", { ok: true, limits: [LIMW("5H", 49, null)] });
READ("mt-unknown", { ok: true, limits: [LIMW("5H", null, 18000), LIMW("WEEKLY", undefined, 604800), LIMW("X", "", 3600), LIMW("Y", "abc", 3600)] });
READ("mt-tones", { ok: true, limits: [LIMW("A", 60, 1), LIMW("B", 30, 1), LIMW("C", 14, 1), LIMW("D", 51, 1), LIMW("E", 15, 1), LIMW("F", 150, 1), LIMW("G", -4, 1), LIMW("H", 50, 1)] });
READ("mt-credits", { ok: true, limits: [], credits: 12 });
READ("mt-blocked", { ok: true, limits: [LIMW("5H", 0, 18000)], limitReached: true, creditsInfo: { hasCredits: false }, upsell: null });
READ("mt-empty", { ok: true, limits: [] });
READ("mt-busy", { ok: true, limits: [LIMW("5H", 49, 18000)] }, { loading: true });
m.subscriptionUsageCache.set("mt-first", { data: null, fetchedAt: 0, loading: true });
m.subscriptionUsageCache.set("mt-failed", { data: null, error: "boom", fetchedAt: 1 });
m.subscriptionUsageCache.set("mt-notread", { data: { ok: false }, fetchedAt: 1 });
const MT = (id, stops) => m.subscriptionMetersHtml(id, stops === undefined ? undefined : { stops });
out.meters = {
  two: MT("mt", { "18000": [10, 20], "604800": [10] }), one: MT("mt-one"), nolen: MT("mt-nolen", { "0": [10], "18000": [10] }),
  unknown: MT("mt-unknown"), tones: MT("mt-tones"), credits: MT("mt-credits"), blocked: MT("mt-blocked"), empty: MT("mt-empty"), busy: MT("mt-busy"),
  never: MT("never-read"), notread: MT("mt-notread"),
  sameNotes: [MT("mt-first") === m.subscriptionUsageHtml("mt-first"), MT("mt-failed") === m.subscriptionUsageHtml("mt-failed"), MT("mt-notread") === m.subscriptionUsageHtml("mt-notread")],
  tall_unknown: m.subscriptionLimitRowHtml("acc", LIMW("5h limit", null, 18000)),
};
console.log(JSON.stringify(out));
"""

node = find_node()
if node is None:
    print("js usage-stats: SKIPPED — node не найден ни в PATH, ни у менеджеров версий: " + ", ".join(node_search_paths()))
    sys.exit(0)
probe = ROOT / "scripts" / ".probe_usage_stats.tmp.mjs"
probe.write_text(PROBE, encoding="utf-8")
try:
    hook = f"data:text/javascript,import {{ register }} from 'node:module'; register('file://{ROOT}/scripts/_js_harness.mjs');"
    env = {"JS_ROOT": str(ROOT / "static" / "js"), "JS_STUBS": "form,cloud,topology-render,polling", "PATH": "/usr/bin:/bin"}
    proc = subprocess.run([node, "--import", hook, str(probe)], capture_output=True, text=True, cwd=ROOT, env=env, timeout=60)
finally:
    probe.unlink(missing_ok=True)
if proc.returncode != 0:
    print("js usage-stats: FAILED — харнесс не отработал"); print(proc.stderr.strip()[:800]); sys.exit(1)
got = json.loads(proc.stdout.strip().splitlines()[-1])
digits = lambda s: "".join(ch for ch in str(s) if ch.isdigit())

print("usMoney:")
check(got["money"] == ["0.00", "0.500", "1.00", "12.35", "0.00", "0.00", "-3.00", "0.00"],
      f"три знака только ниже доллара, мусор → 0.00 (получено {got['money']})")
print("usTok:")
check(digits(got["tok"][0]) == "1234567" and len(got["tok"][0]) > 7,
      f"цифры сохранены и есть разделители (получено {got['tok'][0]!r})")
check(got["tok"][1:] == ["0", "0", "12"], f"0/null/строка → {got['tok'][1:]}")

print("usageStatsOverview:")
ov = got["overview"]
check('<div class="us-bignum">$12.35</div>' in ov, "облачный итог округлён до цента")
check("7 req · 1,500 tok" in ov or "7 req · 1500 tok" in ov, "облачные токены = prompt+completion, запросы как есть")
check('25,000 <span class="us-bignum-unit">tok</span>' in ov or '25000 <span' in ov, "локальные токены просуммированы")
check("≈ $0.012 " in ov, "«стоило бы в облаке» — три знака ниже доллара")
check(ov.count('<div class="us-mini-row"><span>') == 3 + 1,
      f"мини-список облака обрезан до ТРЁХ моделей, локальный — одна (строк {ov.count('<div class=\"us-mini-row\"><span>')})")
check("&lt;b&gt;evil&lt;/b&gt;" in ov and "<b>evil</b>" not in ov, "имя модели экранировано — HTML не исполнится")
emp = got["overviewEmpty"]
check("$0.00" in emp and "0 req · 0 tok" in emp, "пустая статистика — нули, а не NaN и не исключение")
check(emp.count("no data in this window") == 2, "…и «нет данных» в обоих мини-списках")

print("usageStatsModelTable:")
check("no data in this window" in got["table_empty"], "пустая таблица говорит «нет данных»")
check("gpt-x" in got["table_cloud"] and "$12.35" in got["table_cloud"], "облачная таблица: модель и деньги")
check("gemma" in got["table_local"] and ("25,000" in got["table_local"] or "25000" in got["table_local"]),
      "локальная таблица: модель и токены")

print("usageStatsLocalDetail — ставка:")
check('value="2" data-usage-stats-rate="inputPer1M"' in got["detail_saved"]
      and 'value="8" data-usage-stats-rate="outputPer1M"' in got["detail_saved"], "сохранённая ставка попадает в поля")
check('value="3.5" data-usage-stats-rate="inputPer1M"' in got["detail_edit"], "несохранённая правка ПОБЕЖДАЕТ сохранённую")
check('value="0" data-usage-stats-rate="outputPer1M"' in got["detail_edit"], "мусор в правке → 0, не «junk» в поле")
check("$0.012</b>" in got["detail_saved"], "«стоило бы» в деталях с тем же округлением")

print("formatSubUsageReset:")
check(got["reset_bad"] == "nonsense", f"нечитаемая дата возвращается как есть ({got['reset_bad']!r})")
check(got["reset_today"].startswith("resets ") and not any(mo in got["reset_today"] for mo in ("Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec")),
      f"сегодня — только время, без даты ({got['reset_today']!r})")
check(got["reset_far"].startswith("resets ") and "Mar" in got["reset_far"] and "15" in got["reset_far"],
      f"другой день — с датой ({got['reset_far']!r})")
check(got["reset_midnight"].startswith("resets Jan 11"),
      f"negative: сброс через минуту, но уже за полночью — с датой ({got['reset_midnight']!r})")

print("баннер над шкалами:")
b = got["banner_blocked"]
check(b.startswith('<div class="sub-usage-banner blocked" data-t="sub-usage-banner">⛔ Plan limit reached — OpenAI refuses requests (429) until Mar 15'),
      f"план заблокирован: красный баннер с моментом сброса (получено {b[:110]!r})")
check("No credits and no reserve — only a backup exit can answer until then" in b, "ни кредитов, ни резерва — сказано прямо")
check("You’re out — Use your banked reset" in b and "Reset usage" not in b,
      "слова OpenAI процитированы (заголовок и описание), кнопки — нет")
check("Requests continue on credits: $395" in got["banner_credits"], "кредиты есть — сказано, на что идут запросы")
check("Requests continue on gpt-reserve · Weekly limit: 80% left" in got["banner_reserve"],
      "резерв есть — назван вместе с остатком")
check(got["banner_warn"].startswith('<div class="sub-usage-banner warn" data-t="sub-usage-banner">⚠ Weekly limit: 0% left by OpenAI'),
      f"счётчик 0%, но не заблокировано — янтарное предупреждение (получено {got['banner_warn'][:90]!r})")
check(got["banner_none"] == "" and got["banner_notok"] == "", "всё в порядке или чтение не удалось — баннера нет")

print("возврат на вкладку:")
check(got["stale_old"] == ["a"], "цифра старше минуты — перечитываем: пока вкладка была в фоне, токены и тратились")
check(got["stale_fresh"] == [], "negative: моложе минуты — НЕ ходим; чтение подписки стоит вызова по тому самому лимиту, который показывает панель")
check(got["stale_boundary"] == ["a"], "boundary: РОВНО минута считается устаревшей")
check(got["stale_loading"] == [], "negative: запрос уже в полёте — второй не шлём")
check(got["stale_never"] == ["a"], "ни разу не читали — читаем: карточка после неудачного первого чтения чинится сама при возврате")
check(got["stale_failed"] == ["a"], "прошлое чтение упало — пробуем снова, а не держим панель мёртвой до перезагрузки")
check(got["stale_mixed"] == ["old"], f"из трёх аккаунтов берётся ровно устаревший (got {got['stale_mixed']})")
check(got["stale_empty"] == [], "negative: пустой кэш — пустой ответ, а не падение")
check(got["min_age"] == 60000, f"порог — минута (got {got['min_age']})")
check(got["readings"] == ["apiCosts", "openrouter", "subscription"], 
      f"все три вида чтений в одной таблице — кнопка и возврат зовут одно действие (got {got['readings']})")
check(got["refresh_keeps"] == [True, True, True, 1],
      f"обновление идёт мимо отказа _shouldFetch (хорошие данные лежат), одним запросом, и НЕ стирает прежнее чтение: "
      f"до 1.3.463 шкалы пропадали с карточки до ответа (got {got['refresh_keeps']})")
check(got["refresh_drawn"] == [True, True],
      f"пока идёт чтение — те же шкалы, помеченные «читается» (refreshing, aria-busy) (got {got['refresh_drawn']})")
check(got["refresh_in_flight"] == 0, "negative: щелчок, пока чтение в полёте, второго запроса не шлёт")
fr = got["first_read"]
check(fr[0].startswith('<div class="sub-usage-panel sub-usage-loading" aria-busy="true" data-t="sub-usage-loading">')
      and "sub-usage-spinner" in fr[0] and "loading limits…" in fr[0],
      f"первое чтение без данных — строка со спиннером «loading limits…», а не пустота (got {fr[0][:120]!r})")
check(fr[1] is True, "повтор после неудачи, пока он идёт, — тоже строка со спиннером")
check(fr[2:] == [False, False], "negative: прочитанное и не читающееся — без пометки")
check(got["refresh_unknown_kind"] is False and got["refresh_no_id"] is False,
      "negative: неизвестный вид чтения или пустой id — ничего не делаем и говорим об этом false")
check(0 <= got["banner_order"][0] < got["banner_order"][1], f"в панели баннер стоит ВЫШЕ шкал (получено {got['banner_order']})")
check(got["refresh_panel"] == [True, False, False, True],
      f"кнопка ↻ по умолчанию в голове панели; panel(refresh=false) — без кнопки и без головы, шкалы и баннер на месте (получено {got['refresh_panel']})")
rb = got["refresh_button"]
check(rb["ok"] == [True, False, False, True, True],
      f"subscriptionRefreshHtml: кнопка со значком, знает аккаунт, не крутится и не заблокирована (получено {rb['ok']})")
check(rb["busy"] == [True, True], "пока читается — крутится и заблокирована (повторный щелчок не плодит запросов)")
check(rb["failed"] is True, "после неудачного чтения кнопка есть: повторить можно (в панели сбоя её нет, на ступени пула — есть)")
check(rb["empty"] == "" and rb["none"] == "", "negative: нечего перечитывать — ни ответа, ни ошибки, ни записи — кнопки нет")
check(rb["quoted"] is True, "идентификатор в атрибуте экранирован")
check(rb["panelSame"] is True, "одна кнопка на оба места: панель вставляет ту же разметку, что и ступень пула")
check(got["refresh_words"] == [True, True, True, True, False],
      f"подсказка кнопки ↻ говорит, что она только читает («Re-read … changes nothing»), а не «Refresh»: слово переведено, не равно старому, стоит и в title, и в aria-label (получено {got['refresh_words']})")

print("два порога шага на полосках (2026-10-11):")
row = got["row_two"]
check('class="sub-usage-switch switch" type="range" min="0" max="90" step="1" value="40" style="width:90%"' in row
      and 'class="sub-usage-switch stop" type="range" min="0" max="90" step="1" value="10" style="width:90%"' in row
      and row.count('data-pool-switch="p&lt;1&gt;" data-step-id="s&lt;1&gt;" data-window-seconds="18000"') == 2
      and 'data-level="switch" data-t="pool-switch"' in row and 'data-level="stop" data-t="pool-stop"' in row,
      "две ручки на полоске: ▼ переключение на 40 и ▲ стоп на 10, от 0 до потолка сервера, каждая знает окно, пул и шаг (экранированные)")
check('<b class="sub-usage-zone stop" style="width:10%"></b><b class="sub-usage-zone switch" style="left:10%;width:30%"></b>' in row,
      "под стопом — своя штриховка от левого края, между стопом и переключением — своя")
check('data-level-mark="switch" style="left:calc(40% + var(--level-thumb) * 0.556 + 3px)">switch at 40%<' in row
      and 'data-level-mark="stop" style="left:calc(10% + var(--level-thumb) * 0.889 + 3px)">stop at 10%<' in row and "is-off" not in row,
      "каждый порог подписан справа от своей ручки: ручка идёт по 90% полоски без своей ширины — подпись стоит у её правого края; "
      "знак — сама ручка, в словах его нет (2026-10-11: подписи стояли отдельной строкой у названия окна)")
track_at, meta_at = row.index('class="sub-usage-track'), row.index('class="sub-usage-meta"')
check(row.index('data-level-mark="switch"') > track_at and row.index('data-level-mark="stop"') > track_at
      and "sub-usage-levels" not in row and row.index('class="sub-usage-pct"') < track_at and meta_at < track_at,
      "negative: подписей порогов нет у названия окна — они внутри полоски, рядом с ручками")
check('aria-label="Switch level:' in row and 'aria-label="Stop level:' in row, "у каждой ручки — имя для экранного диктора и подсказка")
same = got["row_same"]
check('data-level-mark="switch" style="left:calc(20% + var(--level-thumb) * 0.778 + 3px)" hidden>' in same
      and 'data-level-mark="stop" style="left:calc(20% + var(--level-thumb) * 0.778 + 3px)">stop at 20%<' in same
      and 'class="sub-usage-switch switch is-off"' in same and 'style="left:20%;width:0%"' in same,
      "переключение на стопе ничего не меняет: его подпись скрыта, ручка бледная — но стоит на месте, её можно тянуть")
check('class="sub-usage-switch switch is-off" type="range" min="0" max="90" step="1" value="30"' in got["row_below"],
      "переключение ниже стопа рисуется на стопе")
off = got["row_off"]
check(off.count('value="0"') == 2 and off.count("is-off") == 2 and 'style="width:0%"' in off and off.count(" hidden>") == 2,
      "порогов нет — обе ручки бледные в начале полоски, подписи скрыты, штриховки нет")
check(all("sub-usage-switch" not in got[k] for k in ("row_nolen", "row_nomax", "row_nostep")),
      "negative: окно без длины, без потолка сервера или полоска не шага — ручек нет вовсе (настройка, которая ничего не делает, не рисуется)")
check(got["row_over"].count('value="90"') == 2, "порог выше потолка рисуется на потолке, а не за полоской")
check(got["preview_switch"] == ["10", "45", "10%", "10%", "35%", "switch at 45%", "stop at 10%", "", "",
                                ["calc(45% + var(--level-thumb) * 0.5 + 3px)", ""], ["calc(10% + var(--level-thumb) * 0.889 + 3px)", ""]],
      f"тянут переключение — сдвигается его штриховка и подпись, подпись едет за ручкой (получено {got['preview_switch']})")
check(got["preview_stop_pushes"] == ["50", "50", "50%", "50%", "0%", None, "stop at 50%", "is-off", "",
                                     ["calc(50% + var(--level-thumb) * 0.444 + 3px)", ""], ["calc(50% + var(--level-thumb) * 0.444 + 3px)", ""]],
      f"стоп выше переключения толкает его вверх; подпись переключения прячется (получено {got['preview_stop_pushes']})")
check(got["preview_switch_rests"] == ["20", "20", "20%", "20%", "0%", None, "stop at 20%", "is-off", "",
                                      ["calc(20% + var(--level-thumb) * 0.778 + 3px)", ""], ["calc(20% + var(--level-thumb) * 0.778 + 3px)", ""]],
      f"переключение ниже стопа встаёт на стоп (получено {got['preview_switch_rests']})")
check(got["preview_no_stop"] == ["0", "40", "0%", "0%", "40%", "switch at 40%", None, "", "is-off",
                                 ["calc(40% + var(--level-thumb) * 0.556 + 3px)", ""], ["calc(0% + var(--level-thumb) * 1 + 3px)", ""]],
      f"стоп на нуле — стопа нет: ручка бледная, подпись скрыта (получено {got['preview_no_stop']})")
check(got["preview_past_middle"][9] == ["", "calc(28% + var(--level-thumb) * 0.8 + 3px)"]
      and got["preview_past_middle"][10] == ["calc(10% + var(--level-thumb) * 0.889 + 3px)", ""],
      f"ручку утянули за середину — подпись переходит налево от неё, а не уезжает за конец полоски на время сброса (получено {got['preview_past_middle'][9:]})")
past = got["row_past_middle"]
check('data-level-mark="switch" style="right:calc(28% + var(--level-thumb) * 0.8 + 3px)">switch at 72%<' in past
      and 'data-level-mark="stop" style="right:calc(49% + var(--level-thumb) * 0.567 + 3px)">stop at 51%<' in past,
      "за серединой полоски подпись стоит слева от ручки — так рисуется и сразу; negative: на 50% и ниже — справа (пины выше)")
check(got["legend"] == [True, False], "под полосками шага — строка, что значат ▼ и ▲; у полосок не шага её нет")
signs = got["signs"]
check(signs == {"switch": "▼", "stop": "▲"},
      f"знаки порогов — треугольники: ▼ переключение, ▲ стоп (владелец, 2026-10-12, вместо эмодзи) (получено {signs})")
check(got["legend_html"] == ('<span class="sub-usage-sign switch" aria-hidden="true">▼</span> switch: from this much left, requests go to '
                             'the next steps first · <span class="sub-usage-sign stop" aria-hidden="true">▲</span> stop: from this much left, '
                             'the step does not serve'),
      f"в строке-пояснении знаки — в цветах своих ручек, слова — языка (получено {got['legend_html']!r})")
import glob, re, urllib.parse
legends = {path.split("/")[-1]: re.search(r'^  poolLevelsLegend: "(.*)",$', open(path, encoding="utf-8").read(), re.M).group(1)
           for path in sorted(glob.glob(str(ROOT / "static/js/i18n/*.js")))}
check(all(v.startswith(signs["switch"] + " ") and (" " + signs["stop"] + " ") in v for v in legends.values()),
      "строка-пояснение на всех 20 языках называет пороги теми же знаками, что подписи у шкалы")
css = urllib.parse.unquote((ROOT / "static/css/modals.css").read_text(encoding="utf-8"))
thumbs = {level: re.search(r"\.sub-usage-switch\." + level + r"::-webkit-slider-thumb \{[^}]*url\(\"([^\"]+)\"\)", css) for level in signs}
tokens = dict(re.findall(r"--level-(stop|switch): (#[0-9a-f]{6});", css))
shapes = {}
for level, found in thumbs.items():
    poly = re.search(r"<polygon points='([^']+)' fill='(#[0-9a-f]{6})'", found.group(1)) if found else None
    pts = [tuple(float(v) for v in xy.split(",")) for xy in poly.group(1).split()] if poly else []
    apex = min(pts, key=lambda xy: abs(xy[0] - 8)) if pts else None
    base = [xy[1] for xy in pts if xy != apex]
    shapes[level] = (poly.group(2) if poly else None,
                     ("down" if apex[1] > max(base) else "up" if apex[1] < min(base) else "?") if apex and base else None)
check(tokens == {"stop": "#ef4444", "switch": "#eab308"} and shapes == {"switch": (tokens.get("switch"), "down"), "stop": (tokens.get("stop"), "up")},
      f"ручка на шкале — треугольник цвета своего порога: ▼ жёлтый над полоской, ▲ красный под ней; его заливка — тот же цвет, "
      f"что у штриховки, подписи и знака в строке-пояснении (--level-*) (получено {tokens}, {shapes})")
moz = {level: re.search(r"\.sub-usage-switch\." + level + r"::-moz-range-thumb \{[^}]*url\(\"([^\"]+)\"\)", css) for level in signs}
check(all(moz[level] and thumbs[level] and moz[level].group(1) == thumbs[level].group(1) for level in signs),
      "в Firefox ручки — те же картинки")
thumb_rule = re.search(r"\.sub-usage-switch::-webkit-slider-thumb \{([^}]*)\}", css).group(1)
check(re.search(r"\.sub-usage-track \{[^}]*--level-thumb: 16px;", css) is not None and "width: var(--level-thumb);" in thumb_rule
      and "height: var(--level-thumb);" in thumb_rule,
      "ширина ручки сказана один раз (--level-thumb) — по ней и ручка, и место подписи; negative: числа 16px в правиле ручки нет")
areas = {name: re.search(r"^\.pool-step \.sub-usage-" + name + r" \{ grid-area: ([^;]+);", css, re.M) for name in ("label", "track", "resets", "pct")}
check({k: v.group(1) if v else None for k, v in areas.items()} == {"label": "1 / 1", "track": "1 / 2", "resets": "1 / 3", "pct": "1 / 4"},
      f"полоска шага — одна строка: название слева, полоска, справа сброс и остаток (2026-10-11, компактнее) (получено {areas})")
panel = re.search(r"^\.pool-step > \.sub-usage-panel \{([^}]*)\}", css, re.M)
row = re.search(r"^\.pool-step \.sub-usage-row \{([^}]*)\}", css, re.M)
check(panel is not None and "grid-template-columns: max-content minmax(0, 1fr) max-content max-content;" in panel.group(1)
      and row is not None and "grid-template-columns: subgrid;" in row.group(1)
      and re.search(r"^\.pool-step \.sub-usage-resets \{[^}]*justify-self: end;", css, re.M) is not None,
      "полоски шага — на одной сетке панели: названия в одном столбце, каждая полоска начинается и кончается в одном месте, "
      "время сброса — у одного края (2026-10-11, аккуратнее); negative: у строки своей сетки нет — иначе длина полоски "
      "зависела бы от длины названия и времени сброса")
kept = got["banner_kept"]
check(kept.startswith('<div class="sub-usage-banner reserve" data-t="sub-usage-banner">↓ 5h limit: 15% left, the switch level is 20%. Until Mar 15'),
      f"шаг ниже переключения — своя плашка: окно, остаток, порог и до какого срока пул шлёт сначала в следующие шаги (получено {kept[:140]!r})")
stopped = got["banner_stopped"]
check(stopped.startswith('<div class="sub-usage-banner stop" data-t="sub-usage-banner">■ 5h limit: 15% left, the stop level is 20%. The step does not serve until Mar 15'),
      f"шаг на стопе — плашка стопа, она важнее плашки переключения (получено {stopped[:140]!r})")
check(got["banner_kept_blocked"].startswith('<div class="sub-usage-banner blocked"'),
      "OpenAI уже отказывает — главная плашка его, не наша")
check(got["banner_kept_noreset"] == "", "negative: у вердикта нет срока — плашки нет (не знаем до когда — не пишем)")
check(got["banner_no_step"] == "", "negative: старое поле учётки (reserveKept) больше ничего не рисует — уровень у шага, а не у учётки")
check(got["saved_model"] == {"accountId": "sub", "model": "gpt-6-sol", "level": "switch", "windowSeconds": 604800, "pct": 20},
      f"ручка модели (Маршрутизация, 1.3.486) сохраняет уровень модели — аккаунт и модель, без пула и строки (получено {got['saved_model']})")
rm = got["row_model"]
check(rm.count('data-level-account="sub&lt;1&gt;" data-level-model="gpt&lt;1&gt;" data-window-seconds="18000"') == 2
      and "data-pool-switch" not in rm and "data-step-id" not in rm,
      "две ручки модели называют аккаунт и модель (экранированные); negative: ни пула, ни строки у них нет")
applied, sent_body, method = got["saved"]
check(applied == [{"pools": ["after"]}] and sent_body == {"poolId": "work", "stepId": "sub", "level": "stop", "windowSeconds": 18000, "pct": 30}
      and method == "POST",
      f"отпустили — ушёл POST с пулом, шагом, порогом ручки, окном и процентом, доска нарисована из ответа сервера (получено {got['saved']})")
check(got["saved_failed"][0] == [] and got["saved_failed"][1].startswith("The level was not saved: "),
      f"negative: сохранение не удалось — сказано, ответа нет и доска не подменена (получено {got['saved_failed']})")
check(got["drag"] == [True, False, 1, 0, 0],
      f"флаг перетаскивания снимается на отпускании, отложенная перерисовка — один раз, слушатели убраны (получено {got['drag']})")
check(got["drag_cancel_no_defer"] == [False, 1],
      "отмена жеста тоже снимает флаг; перерисовки не просили — её и нет")

print("the limits drawn small (1.3.541; Routing's account card):")
mt = got["meters"]
two = mt["two"]
check(two.count('<div class="sub-meter" ') == 2 and two.count('class="sub-meters"') == 1 and 'data-t="sub-meters"' in two and "sub-usage-row" not in two,
      "два окна — две строки-шкалы в одной сетке, высоких строк нет")
check('<span class="sub-meter-label">5H</span><span class="sub-meter-bar"><i class="sub-meter-fill" style="width:49%;background:#f59e0b"></i>'
      '<i class="sub-meter-stop" data-t="sub-meter-stop" style="left:10%" title="stop at 10%"></i><i class="sub-meter-stop" data-t="sub-meter-stop" style="left:20%" title="stop at 20%"></i>'
      '</span><span class="sub-meter-pct">49%</span>' in two,
      "5H: подпись, полоска с заливкой по остатку (49% — янтарная) и по красной риске на каждом уровне остановки моделей карточки, проценты")
check('<span class="sub-meter-label">WEEKLY</span><span class="sub-meter-bar"><i class="sub-meter-fill" style="width:89%;background:#22c55e"></i>'
      '<i class="sub-meter-stop" data-t="sub-meter-stop" style="left:10%" title="stop at 10%"></i></span><span class="sub-meter-pct">89%</span>' in two,
      "WEEKLY: свои уровни, у каждого окна — только его (окно распознаётся по длине в секундах)")
check('role="meter" aria-label="5H 49% · resets ' in two and 'aria-valuemin="0" aria-valuemax="100" aria-valuenow="49"' in two and 'aria-valuenow="89"' in two,
      "для чтеца с экрана окно — «meter» с остатком, как в подсказке: одной строкой «5H 49% · resets …»")
check(re.search(r'title="5H 49% · resets [^"]*Mar[^"]*15[^"]*"', two) is not None and 'class="sub-usage-panel sub-meters-panel"' in two,
      "когда сбрасывается окно — в подсказке шкалы, одной строкой с остатком; панель — та же, что у высоких полосок (читаются её правила)")
check('class="sub-meters single"' in mt["one"] and mt["one"].count('<div class="sub-meter" ') == 1 and "sub-meter-stop" not in mt["one"],
      "одно окно — на всю ширину («single»); negative: уровней не дали — рисок нет")
check("sub-meter-stop" not in mt["nolen"],
      "negative: окно без длины в секундах рисок не получает, что бы ни дали: уровень на безымянном окне — настройка, которая ничего не делает")
unk = mt["unknown"]
check(unk.count('role="img" aria-label="') == 4 and "aria-valuenow" not in unk and 'aria-label="5H: unknown"' in unk,
      "negative: без числа — не «meter» с нулём (экранный чтец прочёл бы «0»), а картинка «5H: unknown»")
check(unk.count('<span class="sub-meter-pct">—</span>') == 4 and "sub-meter-fill" not in unk and unk.count('data-t-state="unknown"') == 4 and unk.count('data-t-state="known"') == 0,
      "negative: чтение не назвало остаток (null, undefined, пусто, не число) — прочерк и пустая полоска, а не красный «0%», который читается как «ничего не осталось»")
tones = {label: (width, color) for label, width, color in re.findall(r'data-t-id="(\w)"[^>]*>.*?style="width:(\d+%);background:(#\w+)"', mt["tones"])}
check(tones == {"A": ("60%", "#22c55e"), "B": ("30%", "#f59e0b"), "C": ("14%", "#ef4444"), "D": ("51%", "#22c55e"), "E": ("15%", "#ef4444"), "F": ("100%", "#22c55e"), "G": ("0%", "#ef4444"), "H": ("50%", "#f59e0b")},
      f"тон полоски — правило высоких: строго больше 50% зелёная (на 50 — янтарная), строго больше 15% янтарная (на 15 — красная), иначе красная; остаток сжат до 0–100 (получено {tones})")
check('<div class="sub-usage-credits"><span>' in mt["credits"] and "<strong>12</strong>" in mt["credits"] and "sub-meters" not in mt["credits"].replace("sub-meters-panel", ""),
      "кредиты без окон — строка кредитов, сетки шкал нет")
bl = mt["blocked"]
check('data-t="sub-usage-banner"' in bl and bl.index("sub-usage-banner") < bl.index('class="sub-meters'),
      "слово провайдера «лимит исчерпан» — над шкалами, как над высокими (его видно первым)")
check(mt["empty"] == "" and mt["never"] == "" and mt["notread"] == "",
      "negative: ни окон, ни кредитов; не читали; чтение пришло «не ok» — карточке нечего рисовать")
check('class="sub-usage-panel sub-meters-panel refreshing" aria-busy="true"' in mt["busy"] and "sub-meter-fill" in mt["busy"],
      "перечитывается — шкалы остаются как были и помечены (бежит огонёк), а не пропадают")
check(mt["sameNotes"] == [True, True, True],
      "первое чтение и сбой читаются теми же строками, что на высокой панели (одна разметка в одном месте), а не своими")
check('<span class="sub-usage-pct">—</span>' in mt["tall_unknown"] and "<i style=" not in mt["tall_unknown"] and "0%" not in mt["tall_unknown"],
      "высокая строка того же чтения — тоже прочерк (карточка и полоса не расходятся: одно правило остатка)")

print("30 дней через караван:")
check(got["compact"] == ["0", "999", "1K", "1.5K", "360M", "1B", "12.3B", "0"],
      f"числа коротко и одинаково на любом языке; граница 1000 → 1K; пусто — 0 (got {got['compact']})")
sp = got["spend"]
check("5.4K" in sp["api"] and "360M" in sp["api"] and "≈ $699 at API prices" in sp["api"] and "GPT-5.6-TERRA" not in sp["api"]
      and '<div class="spend-line"' in sp["api"],
      "одна строка — запросы, токены и «≈ $699 по ценам API»; модели в ней не перечисляются")
check(all("data-spend-toggle" not in v and "aria-expanded" not in v and "GPT-5.6-TERRA" not in v for v in (sp["api"], sp["sub"], sp["asked"])),
      "defect-history (оператор, 2026-09-27: «зачем строки дублировать»): разбивки по щелчку нет — доля каждой модели "
      "стоит в её строке в списке моделей; negative: и по-старому (open) она не раскрывается")
check("The subscription covers this" in sp["sub"] and "The subscription covers this" not in sp["api"],
      "у подписки подсказка строки говорит, чья это цена (подписка это покрывает); negative: у ключа API — нет")
check(sp["of"] == "GPT-5.6-TERRA" and sp["ofNone"] is None,
      "строки моделей читают запись аккаунта; negative: трафика не было — null, а не пустая запись")
check(sp["none"] == "", "negative: трафика не было — строки нет")
check("0 req · 0 tok" in sp["zero"] and "30 days via the caravan" in sp["zero"] and sp["zeroOwn"] is True,
      "где строка — всё, что есть (складка аккаунта в Маршрутизации), месяц без трафика сказан нулём, когда расход прочитан; "
      "negative: у аккаунта с трафиком строка та же")
check(got["spend_unread"] == "", "negative: расход ещё не прочитан — нуля нет: не знаем, а не «ничего»")
check(sp["cost"] == ["$699", "$0", "$1,234,567", "$0.40", "$0", "$0", "$12.50", "<$0.01", "$0.01", "$12", "$100", "$100", "$0.07", "$1.22"],
      f"сумма пишется одним способом (1.3.585) — от ста долларов целые, тысячи через запятую; меньше ста — с центами, без «.00»; "
      f"нет записи — $0, не NaN; больше нуля, но меньше половины цента — «<$0.01», не $0 (got {sp['cost']}). Оператор сверял строку с Console, "
      "где центы: «≈ $0» при расходе $0.07 читалось как «ничего не потрачено»")
check("≈ $699 at API prices" in sp["api"], "строка расхода берёт сумму у того же правила")

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail: print("  - " + m)
    sys.exit(1)
print("js usage-stats OK: настоящий модуль в node, деньги и токены значениями")
