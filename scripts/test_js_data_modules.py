#!/usr/bin/env python3
"""Snapshot of three data modules: i18n-data.js, constants.js, state.js.

i18n-data: 6 languages, English first and static; `loadLanguage` — an
unknown/empty code and an import failure both fall back to "en" (the page
never ends up with no strings at all), a known one loads the table once and
returns the code, augmenters (tour strings) run for already-loaded tables
and for every later one. constants: every group from the tabs table exists
(the premise `check_field_homes` relies on), memory-estimate fields are
numeric, toggles on by default are a subset of the optional ones, value
picking only happens for known fields, `dirtyOptionalToggles` is a shared
Set. state: `state`/`topology` only change through their setters and are
visible to importers; `ui`'s default shape; writing `ui` properties with no
setters.

Run: python3 scripts/test_js_data_modules.py
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _node import find_node, node_search_paths, probe_args  # noqa: E402

STUBS = ""

PREAMBLE = r"""
import "./_js_globals.mjs";
import { pathToFileURL } from "node:url";
const D = await import(pathToFileURL(process.env.JS_ROOT + "/i18n-data.js").href);
const C = await import(pathToFileURL(process.env.JS_ROOT + "/constants.js").href);
const S = await import(pathToFileURL(process.env.JS_ROOT + "/state.js").href);
globalThis.__initialKeys = Object.keys(D.messages);
// Аугментеры и «поздняя» таблица пробуются ОДИН раз при старте процесса, пока ничего не загружено:
// в обратном прогоне allMessages уже загрузил всё, и поздний вызов не наблюдаем.
globalThis.__augProbe = await (async () => { const seen = []; D.onLanguageLoaded((code, table) => { seen.push(code); table.__probe = code; }); const atOnce = [...seen]; await D.loadLanguage("de"); return { atOnce, late: seen.slice(atOnce.length), deProbe: D.messages.de.__probe, enProbe: D.messages.en.__probe }; })();
globalThis.__warns = []; console.warn = (...a) => { globalThis.__warns.push(String(a[0])); };
const reset = () => { globalThis.__warns.length = 0; };
reset();
const out = {};
"""

PINS = [
    ("langs_six_unique_english_first", '', '[D.LANGS.length, D.LANGS[0].code, new Set(D.LANGS.map((l) => l.code)).size, D.LANGS.every((l) => l.code && l.emoji && l.label), globalThis.__initialKeys]', '[6,"en",6,true,["en"]]',
     "шесть языков без повторов, английский первым и единственный загруженный при импорте"),
    ("load_unknown_or_empty_falls_back", '', 'await (async () => [await D.loadLanguage("zz"), await D.loadLanguage(""), await D.loadLanguage(null), "zz" in D.messages])()', '["en","en","en",false]', "negative: неизвестный, пустой и null — «en», ничего не загружено"),
    ("load_known_once", '', 'await (async () => { const a = await D.loadLanguage("de"); const t1 = D.messages.de; const b = await D.loadLanguage("de"); return [a, b, t1 === D.messages.de, typeof D.messages.de.saved, D.messages.de.saved !== D.messages.en.saved]; })()', '["de","de",true,"string",true]',
     "известный код: таблица загружена один раз (повтор отдаёт тот же объект), строки свои, не английские"),
    ("augmenters_run_for_loaded_and_late", '', 'globalThis.__augProbe', '{"atOnce":["en"],"late":["de"],"deProbe":"de","enProbe":"en"}',
     "аугментер запускается для всех уже загруженных таблиц сразу и для каждой поздней"),
    ("all_messages_loads_six", '', 'await (async () => { const all = await D.allMessages(); return [Object.keys(all).length, D.LANGS.every((l) => typeof all[l.code]?.saved === "string")]; })()', '[6,true]', "allMessages — все шесть таблиц (для гвардов покрытия, не для страницы)"),
    ("tab_groups_all_exist", '', '(() => { const groups = new Set(C.advancedGroups.map((g) => g.titleKey)); const refs = C.advancedTabDefs.flatMap((t) => t.groups); return [refs.length > 0, refs.every((g) => groups.has(g)), C.advancedTabDefs.every((t) => t.key && t.groups.length), C.advancedGroups.every((g) => Array.isArray(g.fields) && g.fields.length)]; })()', '[true,true,true,true]',
     "каждая группа из таблицы вкладок существует и непуста — посылка гварда домов полей"),
    ("memory_fields_numeric_toggles_subset", '', '[C.memoryEstimateFields.every((f) => C.numericFields.includes(f)), C.defaultOnOptionalToggles.every((f) => C.optionalToggleFields.includes(f)), C.optionalToggleFields.every((f) => C.toggleFields.includes(f)), C.modelFields.includes("MODEL_FILE")]', '[true,true,true,true]',
     "поля оценки памяти — числовые; включённые по умолчанию — подмножество необязательных переключателей, те — подмножество переключателей"),
    ("field_choices_and_constants", '', '(() => { const all = new Set(C.advancedGroups.flatMap((g) => g.fields)); return [Object.keys(C.fieldChoices).every((f) => all.has(f)), ["CONTROLLER_HOST_ID", "gemma4DraftModel", "gemma4DefaultMmproj"].filter((k) => k in C), C.dirtyOptionalToggles instanceof Set, C.moonshineModelGb > 0, Object.values(C.whisperModelGb).every((v) => v > 0)]; })()', '[true,[],true,true,true]',
     "выбор значений только у полей с домом; negative: ни сентинела контроллера, ни моделей Gemma-режима классической формы — у контроллера нет своих ячеек и формы с шага 6.9; грязные переключатели — общий Set; размеры моделей положительные"),
    ("dirty_toggles_shared_mutable", '', '(() => { C.dirtyOptionalToggles.add("X"); const a = C.dirtyOptionalToggles.has("X"); C.dirtyOptionalToggles.clear(); return [a, C.dirtyOptionalToggles.size]; })()', '[true,0]', "Set грязных переключателей — один на всех и очищается"),
    ("state_setters_rebind_live", '', '(() => { S.setState({ a: 1 }); const a = S.state; S.setState({ b: 2 }); S.setTopology({ proxies: [] }); return [a.a, S.state.b, "a" in S.state, S.topology.proxies.length]; })()', '[1,2,false,0]', "setState/setTopology ЗАМЕНЯЮТ объект целиком (не сливают) — импортёры видят новый"),
    ("a_reading_older_than_the_page_holds_is_dropped", '', '(() => { const R = S.TOPOLOGY_READINGS; const first = R.setOut(), second = R.setOut(); return [R.land(second, { of: "second" }), R.land(first, { of: "first" }), S.topology.of]; })()', '[true,false,"second"]',
     "negative (1.3.691): чтение, вышедшее раньше, пришло позже — остаётся то, что вышло последним"),
    ("readings_landing_in_their_order_all_land", '', '(() => { const R = S.TOPOLOGY_READINGS; const first = R.setOut(), second = R.setOut(); return [R.land(first, { of: "first" }), S.topology.of, R.land(second, { of: "second" }), S.topology.of]; })()', '[true,"first",true,"second"]',
     "чтения, пришедшие по порядку, садятся оба: первое не отменяет второе, что вышло до его прихода, но после него"),
    ("a_write_answer_outdates_the_readings_on_their_way", '', '(() => { const R = S.TOPOLOGY_READINGS; const way = R.setOut(); S.setTopology({ of: "write" }); const late = R.land(way, { of: "late" }); const held = S.topology.of; const next = R.setOut(); return [late, held, R.land(next, { of: "next" }), S.topology.of]; })()', '[false,"write",true,"next"]',
     "ответ на запись новее чтений в пути (перенесённая строка не прыгает назад); negative: чтение, вышедшее после ответа, садится"),
    ("state_initial_null_and_ui_shape", '', '(() => { const keys = Object.keys(S.ui).sort(); return [S.ui.usageStatsScope, S.ui.usageStatsDays, "topologyProxyFormOpen" in S.ui, S.ui.pendingConfirm, S.ui.latestSystemMonitor, keys.length, keys.includes("topologyRouterDetailId"), keys.includes("_lastCloudProvidersKey"), keys.includes("topologyRouterInputSearch"), keys.includes("topologyRouterInputsExpanded")]; })()', '["overview",30,false,null,null,16,true,true,false,false]',
     "форма ui по умолчанию: область статистики overview, 30 дней, формы своего порта нет (ушла 2026-11-07 вместе с её полем и id), нет ожидающего подтверждения и монитора; 16 ключей "
     "(режим окна конфига агента ушёл вместе с окном; поиск по входам Маршрутизации и раскрытие входов — 2026-10-11, их поля и кнопок "
     "страница не рисовала)"),
    ("ui_property_writes_visible", '', '(() => { const was = S.ui.usageStatsDays; S.ui.usageStatsDays = 7; const a = S.ui.usageStatsDays; S.ui.usageStatsDays = was; return [a, S.ui.usageStatsDays]; })()', '[7,30]', "свойства ui пишутся напрямую и видны всем"),
    ("load_failure_stays_english", '', 'await (async () => { D.LANGS.push({ code: "xx", emoji: "?", label: "Probe" }); const r = await D.loadLanguage("xx"); D.LANGS.pop(); return [r, "xx" in D.messages, globalThis.__warns.length]; })()', '["en",false,0]',
     "negative: код добавлен в LANGS после импорта — KNOWN уже собран, значит «en» без попытки импорта (as-is: KNOWN — снимок LANGS на момент импорта)"),
]


_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def main():
    if len(PINS) < 12:
        print(f"js data-modules FAILED: всего {len(PINS)} пинов — снимок урезан")
        return 1
    node = find_node()
    if node is None:
        print("js data-modules: SKIPPED — node не найден: " + ", ".join(node_search_paths()))
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
    path = ROOT / "scripts" / ".probe_js_data_modules.tmp.mjs"
    path.write_text(probe)
    try:
        env = {**os.environ, "JS_ROOT": str(ROOT / "static" / "js"), "JS_STUBS": STUBS,
               "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8", "TZ": "UTC"}
        run = subprocess.run(
            probe_args(node, harness, path), capture_output=True, text=True, env=env, cwd=ROOT, timeout=120)
    finally:
        path.unlink(missing_ok=True)
    if run.returncode != 0:
        print(run.stdout); print(run.stderr)
        print(f"js data-modules FAILED: node вышел с кодом {run.returncode}")
        return 1
    both = json.loads(run.stdout.strip().splitlines()[-1])
    got, rev = both["out"], both["rev"]
    print("модули данных: языки, константы формы, состояние:")
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
    print(f"js data-modules OK: настоящий модуль в node, {len(PINS)} пинов данных значениями")
    return 0


if __name__ == "__main__":
    sys.exit(main())
