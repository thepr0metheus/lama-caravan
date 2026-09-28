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

// ── «30 дней через караван»: одна строка; доли моделей — в их строках (cloud-models.js) ──
out.compact = [0, 999, 1000, 1500, 359627986, 1e9, 12345678901, null].map(m.compactCount);
globalThis.__fetchReply["/api/cloud-accounts/proxy-spend"] = { spend: { sub: { windowDays: 30, total: 698.73, requests: 5429,
  promptTokens: 359000000, completionTokens: 627986, byModel: [{ model: "GPT-5.6-TERRA", cost: 547.38 }] } } };
await m.fetchProxySpend();
out.spend = { api: m.proxySpendHtml("sub"), sub: m.proxySpendHtml("sub", { subscription: true }),
  asked: m.proxySpendHtml("sub", { open: true, subscription: true }), none: m.proxySpendHtml("other"),
  of: m.proxySpendOf("sub")?.byModel?.[0]?.model || null, ofNone: m.proxySpendOf("other") };

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
// действие: забыть и спросить заново — то же, что делает кнопка ↻
m.subscriptionUsageCache.set("gone", { data: { ok: true }, fetchedAt: NOW });
const didRefresh = m.refreshUsageReading("subscription", "gone");
const after = m.subscriptionUsageCache.get("gone");
out.refresh_forgets = [didRefresh, after?.data ?? null, !!after?.loading];
out.refresh_unknown_kind = m.refreshUsageReading("sorcery", "gone");
out.refresh_no_id = m.refreshUsageReading("subscription", "");
// ── запас оператора на полосках лимитов (2026-09-28) ──
const LIMR = { label: "5h limit", name: "", remainingPct: 15, resetsAt: "2031-03-15T10:20:00Z", windowSeconds: 18000 };
out.row_reserve = m.subscriptionLimitRowHtml("acc<1>", LIMR, { reserve: { "18000": 20 }, reserveMax: 90 });
out.row_off = m.subscriptionLimitRowHtml("acc", LIMR, { reserve: {}, reserveMax: 90 });
out.row_nolen = m.subscriptionLimitRowHtml("acc", { ...LIMR, windowSeconds: null }, { reserve: { "18000": 20 }, reserveMax: 90 });
out.row_nomax = m.subscriptionLimitRowHtml("acc", LIMR, { reserve: { "18000": 20 } });
out.row_over = m.subscriptionLimitRowHtml("acc", LIMR, { reserve: { "18000": 95 }, reserveMax: 90 });
const KEPT = { windowSeconds: 18000, remainingPct: 15, reservePct: 20, resetAt: Math.floor(Date.parse("2031-03-15T10:20:00Z") / 1000) };
out.banner_kept = m.subscriptionBannerHtml({ ok: true, limits: [LIMR], credits: null, limitReached: false, creditsInfo: {}, reserveKept: KEPT });
out.banner_kept_blocked = m.subscriptionBannerHtml({ ok: true, limits: [LIMR], credits: null, limitReached: true, creditsInfo: { hasCredits: false }, upsell: null, reserveKept: KEPT });
out.banner_kept_noreset = m.subscriptionBannerHtml({ ok: true, limits: [LIMR], credits: null, limitReached: false, creditsInfo: {}, reserveKept: { ...KEPT, resetAt: 0 } });
globalThis.__fetchReply["/api/cloud-accounts/usage-reserve"] = { ok: true, reserve: { "18000": 30 }, reserveKept: null, reserveReadAt: 5, reserveMax: 90 };
m.subscriptionUsageCache.set("accS", { data: { ok: true, limits: [LIMR], reserve: {} }, fetchedAt: 1 });
const calls0 = globalThis.__fetchCalls.length;
await m.saveUsageReserve({ value: "30", dataset: { usageReserve: "accS", windowSeconds: "18000" } });
const sent = globalThis.__fetchCalls.slice(calls0).find((c) => c.path === "/api/cloud-accounts/usage-reserve");
out.saved = [m.subscriptionUsageCache.get("accS").data.reserve, sent ? JSON.parse(sent.body) : null, sent?.method || null];
globalThis.__fetchReply["/api/cloud-accounts/usage-reserve"] = { __status: 400, ok: false, error: "pct must be 0..90" };
const toastEl = { textContent: "", classList: { add() {}, remove() {} } };
const keepGet = document.getElementById;
document.getElementById = (id) => (id === "toast" ? toastEl : keepGet.call(document, id));
try {
  await m.saveUsageReserve({ value: "95", dataset: { usageReserve: "accS", windowSeconds: "18000" } });
} finally {
  document.getElementById = keepGet;
}
out.saved_failed = [m.subscriptionUsageCache.get("accS").data.reserve, toastEl.textContent];
// перетаскивание: флаг снимается на ЛЮБОМ отпускании, отложенная перерисовка случается один раз
const listeners = {};
globalThis.window.addEventListener = (type, fn) => { (listeners[type] ||= []).push(fn); };
globalThis.window.removeEventListener = (type, fn) => { listeners[type] = (listeners[type] || []).filter((f) => f !== fn); };
let redraws = 0;
m.reserveDrag.begin(() => { redraws += 1; });
const during = m.reserveDrag.active;
m.reserveDrag.deferred = true;
(listeners.pointerup || []).slice().forEach((fn) => fn());
out.drag = [during, m.reserveDrag.active, redraws, (listeners.pointerup || []).length, (listeners.pointercancel || []).length];
m.reserveDrag.begin(() => { redraws += 1; });
(listeners.pointercancel || []).slice().forEach((fn) => fn());
out.drag_cancel_no_defer = [m.reserveDrag.active, redraws];
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
check(got["refresh_forgets"] == [True, None, True],
      f"обновление СНАЧАЛА забывает прежние данные и уходит в «идёт запрос»: _shouldFetch отказывает, пока лежат хорошие данные, "
      f"так что без удаления это был бы холостой вызов (got {got['refresh_forgets']})")
check(got["refresh_unknown_kind"] is False and got["refresh_no_id"] is False,
      "negative: неизвестный вид чтения или пустой id — ничего не делаем и говорим об этом false")
check(0 <= got["banner_order"][0] < got["banner_order"][1], f"в панели баннер стоит ВЫШЕ шкал (получено {got['banner_order']})")

print("запас оператора на полосках:")
row = got["row_reserve"]
check('type="range" min="0" max="90" step="1" value="20"' in row and 'data-window-seconds="18000"' in row
      and 'data-usage-reserve="acc&lt;1&gt;"' in row and 'data-t="usage-reserve"' in row,
      "ползунок лежит на полоске: от 0 до потолка сервера, стоит на запасе, знает окно и аккаунт (экранированный)")
check('class="sub-usage-reserve-zone" style="width:20%"' in row and ">keep 20%<" in row and "is-off" not in row,
      "запас заштрихован от левого края и подписан у названия окна")
check('value="20" style="width:90%"' in row and 'style="width:90%"' in got["row_off"],
      "ползунок занимает долю полоски, равную потолку: ручка на 20 стоит там, где кончается штриховка 20%")
check('aria-label="Keep for yourself:' in row, "у ползунка есть имя для экранного диктора и подсказка")
off = got["row_off"]
check('value="0"' in off and "is-off" in off and 'style="width:0%"' in off and " hidden>" in off,
      "запаса нет — ручка бледная в начале полоски, подпись скрыта, штриховки нет")
check("sub-usage-reserve" not in got["row_nolen"] and "sub-usage-reserve" not in got["row_nomax"],
      "negative: окно без длины или без потолка сервера — ползунка нет вовсе (настройка, которая ничего не делает, не рисуется)")
check('value="90"' in got["row_over"] and "width:90%" in got["row_over"],
      "запас выше потолка рисуется на потолке, а не за полоской")
kept = got["banner_kept"]
check(kept.startswith('<div class="sub-usage-banner reserve" data-t="sub-usage-banner">🛡 Kept for you — 5h limit: 15% left, you keep 20%. The caravan answers requests to this account with 429 until Mar 15'),
      f"караван держит запас — своя плашка, названы окно, остаток, запас и срок (получено {kept[:140]!r})")
check(got["banner_kept_blocked"].startswith('<div class="sub-usage-banner blocked"'),
      "OpenAI уже отказывает — главная плашка его, не наша")
check(got["banner_kept_noreset"] == "", "negative: у вердикта нет срока — плашки нет (не знаем до когда — не пишем)")
saved, sent_body, method = got["saved"]
check(saved == {"18000": 30} and sent_body == {"id": "accS", "windowSeconds": 18000, "pct": 30} and method == "POST",
      f"отпустили — ушёл POST с окном и процентом, в карточке то, что сохранил сервер (получено {got['saved']})")
check(got["saved_failed"][0] == {"18000": 30} and got["saved_failed"][1].startswith("The share kept for you was not saved: "),
      f"negative: сохранение не удалось — сказано, и в карточке остаётся сохранённое, а не то, куда уехала ручка (получено {got['saved_failed']})")
check(got["drag"] == [True, False, 1, 0, 0],
      f"флаг перетаскивания снимается на отпускании, отложенная перерисовка — один раз, слушатели убраны (получено {got['drag']})")
check(got["drag_cancel_no_defer"] == [False, 1],
      "отмена жеста тоже снимает флаг; перерисовки не просили — её и нет")

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

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail: print("  - " + m)
    sys.exit(1)
print("js usage-stats OK: настоящий модуль в node, деньги и токены значениями")
