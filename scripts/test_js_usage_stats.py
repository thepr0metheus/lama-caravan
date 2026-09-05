#!/usr/bin/env python3
"""Снимок static/js/usage-stats.js — числа стоимости и токенов, которые читает оператор.

Модалка использования собирает HTML из объекта статистики; значения в нём —
деньги и токены — и есть то, за чем оператор туда ходит. Пинятся ЗНАЧЕНИЯ:
округление денег, сохранность цифр в токенах, суммы prompt+completion,
предел мини-списка в три строки, экранирование имён моделей, приоритет
несохранённой правки ставки над сохранённой.

Модуль грузится в node НАСТОЯЩИЙ (scripts/_js_harness.mjs); i18n настоящий.

Запуск: python3 scripts/test_js_usage_stats.py
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
out.reset_today = m.formatSubUsageReset(new Date(Date.now() + 60000).toISOString());
out.reset_far = m.formatSubUsageReset("2031-03-15T10:20:00Z");
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

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail: print("  - " + m)
    sys.exit(1)
print("js usage-stats OK: настоящий модуль в node, деньги и токены значениями")
