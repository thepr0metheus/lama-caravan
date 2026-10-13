#!/usr/bin/env python3
"""Value snapshot: when a model is open — the windows of a schedule (1.3.498).

The rule lives twice — caravan/common/week_windows.py, which the proxy and the
controller read, and static/js/week-windows.js, which the board paints and edits
with — and both copies run here against ONE table of windows, each read as the
same open minutes of the week. Pinned: Monday is 0 and no days is every day; a
window is open from `from` and closed at `to`; a window whose `to` is not after its
`from` runs past midnight and belongs to its start day; `from` equal to `to` is a
whole day; a window past Sunday midnight goes on at the week's start; windows that
touch are one stretch; a window that does not read opens nothing in either copy.
The board's own reading back of a painted week (`fromMask`): one way for one week,
and the same minutes again. What a schedule says at a moment, in the caravan's
zone: open until when, or closed until when — across midnight, the weekend, the
week's end, and the night a clock goes back. The caravan's zone: TZ, the machine's
own zone, or UTC said as not known. The door's reading: what is wrong, said.

Run: python3 scripts/test_week_windows.py
"""
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _node import find_node  # noqa: E402
from caravan.common.caravan_zone import CaravanZone  # noqa: E402
from caravan.common.errors import AppError  # noqa: E402
from caravan.common.week_windows import WeekWindows  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


D = 1440


def w(days, start, end):
    return {"days": days, "from": start, "to": end}


# (windows, open runs of the week, what the pin is for)
CASES = [
    ([w([0, 1, 2, 3, 4], "09:00", "19:00")],
     [[d * D + 540, d * D + 1140] for d in range(5)], "positive: будни 09:00–19:00 — пять отрезков"),
    ([w([], "19:00", "09:00")],
     [[0, 540]] + [[d * D + 1140, d * D + D + 540] for d in range(6)] + [[6 * D + 1140, 7 * D]],
     "positive: каждый день через полночь; ночь воскресенья идёт в начало недели"),
    ([w([4], "22:00", "08:00")], [[4 * D + 1320, 5 * D + 480]], "boundary: окно через полночь — дню начала: с вечера пятницы до утра субботы"),
    ([w([5], "06:00", "06:00")], [[5 * D + 360, 6 * D + 360]], "boundary: «с» равно «до» — целые сутки от этого времени"),
    ([w([], "00:00", "00:00")], [[0, 7 * D]], "boundary: каждый день целые сутки — вся неделя"),
    ([w([6], "22:00", "02:00")], [[0, 120], [6 * D + 1320, 7 * D]], "boundary: ночь с воскресенья на понедельник — в начале недели"),
    ([w([0], "09:00", "12:00"), w([0], "12:00", "15:00")], [[540, 900]], "positive: соседние окна — один отрезок"),
    ([w([0, 1, 2, 3, 4, 5, 6], "10:00", "11:00")], [[d * D + 600, d * D + 660] for d in range(7)], "positive: все семь дней списком — каждый день"),
    ([w([0], "9:05", "9:35")], [[545, 575]], "positive: час одной цифрой читается"),
    ([w([0], "25:00", "26:00"), {"days": [0], "from": "08:00"}, w([1, 9], "08:00", "09:00"), w([True], "08:00", "09:00"),
      w("mon", "08:00", "09:00"), "08:00-09:00", w([2], "", "09:00")],
     [], "negative: окно, которое не читается (час 25, нет «до», день 9, True, строка вместо списка, не объект, пусто), ничего не открывает — в обоих двойниках целиком"),
    ([], [], "absence: окон нет — модель закрыта всегда, а не открыта"),
]


def section_python():
    print("правило на сервере:")
    for windows, runs, why in CASES:
        got = [list(r) for r in WeekWindows(windows).runs()]
        check(got == runs, f"py: {why} (got {got[:4]}…)" if len(got) > 4 else f"py: {why} (got {got})")


def section_parse():
    print("дверь читает окна строго и говорит, что не так:")
    check(WeekWindows.parse([w([3, 1, 1], "9:00", "18:30"), w([3, 1], "09:00", "18:30")]) == [w([1, 3], "09:00", "18:30")],
          "дни по порядку, без повторов; время ЧЧ:ММ; одинаковое окно — одно")
    check(WeekWindows.parse([w([0, 1, 2, 3, 4, 5, 6], "08:00", "09:00")]) == [w([], "08:00", "09:00")],
          "все семь дней — каждый день, одним видом: без дней")
    check(WeekWindows.parse(None) == [], "нет окон — пустой список, а не отказ")
    for raw, said, why in (("x", "windows must be a list", "не список"),
                           ([w([7], "08:00", "09:00")], "window 1: days must be numbers 0..6", "день 7"),
                           ([w([0], "08:00", "09:00"), w([True], "08:00", "09:00")], "window 2: days must be numbers 0..6", "True вместо дня — у второго окна"),
                           ([{"days": [0], "from": "08:00"}], "window 1: `to` is required", "нет «до»"),
                           ([w([0], "24:00", "09:00")], "window 1: time out of range: 24:00", "24:00"),
                           ([w([0], "8h", "09:00")], "window 1: time must look like HH:MM", "не ЧЧ:ММ"),
                           (["08:00"], "window 1 must be an object", "не объект"),
                           ([w([0], "08:00", "09:00")] * 200, "a schedule holds at most 168 windows", "слишком много окон")):
        try:
            WeekWindows.parse(raw)
            got = None
        except AppError as exc:
            got = (exc.status, str(exc))
        check(got is not None and got[0] == 400 and got[1].startswith(said),
              f"negative: {why} — 400 и сказано, что не так (got {got})")


def section_state():
    print("что говорит расписание в миг, по зоне каравана:")
    tbilisi = CaravanZone.named("Asia/Tbilisi")

    def at(zone, text):
        return zone.epoch(datetime.fromisoformat(text))

    def said(windows, zone, text):
        st = WeekWindows(windows).state(at(zone, text), zone)
        return (st["open"], st["until"] and zone.text(st["until"]), st["opensAt"] and zone.text(st["opensAt"]))

    weekdays = [w([0, 1, 2, 3, 4], "09:00", "19:00")]
    for text, want, why in (
            ("2026-10-12 08:59", (False, None, "2026-10-12 09:00 UTC+04:00"), "понедельник до окна — откроется в 09:00"),
            ("2026-10-12 09:00", (True, "2026-10-12 19:00 UTC+04:00", None), "boundary: в 09:00 уже открыта, до 19:00"),
            ("2026-10-12 18:59", (True, "2026-10-12 19:00 UTC+04:00", None), "в 18:59 ещё открыта"),
            ("2026-10-12 19:00", (False, None, "2026-10-13 09:00 UTC+04:00"), "boundary: в 19:00 уже закрыта — до утра вторника"),
            ("2026-10-16 19:30", (False, None, "2026-10-19 09:00 UTC+04:00"), "вечер пятницы — до утра понедельника, выходные пропущены")):
        check(said(weekdays, tbilisi, text) == want, f"будни: {why} (got {said(weekdays, tbilisi, text)})")
    chain = [w([6], "22:00", "08:00"), w([0], "08:00", "10:00")]
    check(said(chain, tbilisi, "2026-10-18 23:00") == (True, "2026-10-19 10:00 UTC+04:00", None),
          "ночь воскресенья и утро понедельника — один отрезок через конец недели: открыта до 10:00 понедельника")
    check(said([w([], "00:00", "00:00")], tbilisi, "2026-10-12 12:00") == (True, None, None),
          "открыта всегда — «до» нет")
    check(said([], tbilisi, "2026-10-12 12:00") == (False, None, None),
          "negative: окон нет — закрыта, и «откроется» нет: не выдумано")
    berlin = CaravanZone.named("Europe/Berlin")
    night = [w([], "01:00", "05:00")]
    now = at(berlin, "2026-10-25 01:30")
    st = WeekWindows(night).state(now, berlin)
    check(st["open"] and st["until"] - now == 4 * 3600 + 30 * 60 and berlin.text(st["until"]) == "2026-10-25 05:00 UTC+01:00",
          f"boundary: ночь перевода часов назад — окно кончается в 05:00 по часам стены, на час позже по времени (got {st})")
    utc = CaravanZone.named("UTC")
    check(said(weekdays, utc, "2026-10-12 08:00") == (False, None, "2026-10-12 09:00 UTC+00:00"),
          "в UTC — те же часы по UTC")


def section_zone():
    print("зона каравана:")
    tbilisi = CaravanZone.current(env={"TZ": "Asia/Tbilisi"})
    check((tbilisi.name, tbilisi.known) == ("Asia/Tbilisi", True), "TZ называет зону — она и есть зона каравана")
    check(CaravanZone.current(env={"TZ": ":Europe/Berlin"}).name == "Europe/Berlin", "TZ с двоеточием впереди — та же зона")
    with tempfile.TemporaryDirectory() as tmp:
        zone_file = Path(tmp) / "zoneinfo" / "America" / "New_York"
        zone_file.parent.mkdir(parents=True)
        zone_file.write_bytes(b"")
        link = Path(tmp) / "localtime"
        link.symlink_to(zone_file)
        own = CaravanZone.current(env={}, localtime=link)
        check((own.name, own.known) == ("America/New_York", True), f"без TZ — зона машины по файлу /etc/localtime (got {own.name})")
        bad = CaravanZone.current(env={"TZ": "Nowhere/Bad"}, localtime=Path(tmp) / "missing")
        check((bad.name, bad.known) == ("UTC", False),
              f"negative: зона не известна — UTC, и сказано, что не известна, а не выдано за выбор (got {bad.name}, {bad.known})")
    epoch = CaravanZone.named("Asia/Tbilisi").epoch(datetime(2026, 10, 12, 19, 0))
    check(CaravanZone.named("Asia/Tbilisi").text(epoch) == "2026-10-12 19:00 UTC+04:00"
          and CaravanZone.named("America/New_York").text(epoch) == "2026-10-12 11:00 UTC-04:00",
          "время словами — с поясом: читается верно в любой зоне")
    check(CaravanZone.named("Asia/Tbilisi").state(epoch) == {"name": "Asia/Tbilisi", "known": True, "offsetMinutes": 240},
          "доске — имя зоны, известна ли она и сдвиг сейчас")


def section_js():
    print("двойник в браузере — та же таблица, и как доска пишет окна из закрашенной недели:")
    node = find_node()
    if not node:
        check(False, "node не найден — двойник не проверен")
        return
    canon = [
        ("будни", [w([0, 1, 2, 3, 4], "09:00", "19:00")], [w([0, 1, 2, 3, 4], "09:00", "19:00")]),
        ("ночи", [w([], "19:00", "09:00")], [w([], "19:00", "09:00")]),
        ("сутки субботы", [w([5], "06:00", "06:00")], [w([5], "06:00", "06:00")]),
        ("неделя", [w([], "00:00", "00:00")], [w([], "00:00", "00:00")]),
        ("36 часов", [w([0], "20:00", "00:00"), w([1], "00:00", "00:00"), w([2], "00:00", "08:00")],
         [w([0], "20:00", "00:00"), w([1], "00:00", "00:00"), w([2], "00:00", "08:00")]),
        ("пусто", [], []),
    ]
    probe = (
        'import { pathToFileURL } from "node:url";\n'
        'const { WeekWindows } = await import(pathToFileURL(process.env.JS_FILE).href);\n'
        f"const cases = {json.dumps([c[0] for c in CASES])};\n"
        f"const canon = {json.dumps([c[1] for c in canon])};\n"
        "const runsOf = (mask) => WeekWindows.runs(WeekWindows.fromMask(mask));\n"
        "const week = WeekWindows.mask([{ days: [0, 1, 2, 3, 4], from: '09:00', to: '19:00' }]);\n"
        "WeekWindows.paint(week, 2, 12, false);\n"
        "const half = WeekWindows.mask([{ days: [0], from: '09:30', to: '10:00' }]);\n"
        "const out = {\n"
        "  runs: cases.map((c) => WeekWindows.runs(c)),\n"
        "  canon: canon.map((c) => WeekWindows.fromMask(WeekWindows.mask(c))),\n"
        "  round: cases.map((c) => JSON.stringify(runsOf(WeekWindows.mask(c))) === JSON.stringify(WeekWindows.runs(c))),\n"
        "  painted: WeekWindows.fromMask(week),\n"
        "  shares: [WeekWindows.share(half, 0, 9), WeekWindows.share(half, 0, 10), WeekWindows.share(week, 1, 12), WeekWindows.share(week, 2, 12)],\n"
        "  words: [WeekWindows.minutes('9:05'), WeekWindows.minutes('24:00'), WeekWindows.minutes(''), WeekWindows.hhmm(1439), WeekWindows.hhmm(1440)],\n"
        "};\n"
        "console.log(JSON.stringify(out));\n"
    )
    env = {**os.environ, "JS_FILE": str(ROOT / "static" / "js" / "week-windows.js")}
    run = subprocess.run([node, "--input-type=module", "-e", probe], capture_output=True, text=True, env=env, timeout=60)
    if run.returncode != 0:
        check(False, f"node вышел с кодом {run.returncode}: {run.stderr.strip()[-300:]}")
        return
    js = json.loads(run.stdout.strip().splitlines()[-1])
    for (windows, runs, why), got in zip(CASES, js["runs"]):
        check(got == runs, f"js: {why}")
    check(len(js["runs"]) == len(CASES), "двойник ответил на каждый случай таблицы")
    for (name, _windows, want), got in zip(canon, js["canon"]):
        check(got == want, f"js fromMask: {name} — неделя пишется одним видом (got {got})")
    check(all(js["round"]), f"js: окна из закрашенной недели открывают те же минуты — для каждого случая таблицы (got {js['round']})")
    check(js["painted"] == [w([0, 1, 3, 4], "09:00", "19:00"), w([2], "09:00", "12:00"), w([2], "13:00", "19:00")],
          f"js: закрыт полдень среды — среда двумя окнами, остальные будни одним (got {js['painted']})")
    check(js["shares"] == [30, 0, 60, 0], f"js: час закрашен целиком, наполовину или пуст — по минутам (got {js['shares']})")
    check(js["words"] == [545, None, None, "23:59", "00:00"], f"js: ЧЧ:ММ читается так же, как на сервере (got {js['words']})")


def main():
    section_python()
    section_parse()
    section_state()
    section_zone()
    section_js()
    if _fail:
        print(f"\nweek windows FAILED: {len(_fail)}")
        for m in _fail:
            print("  - " + m)
        return 1
    print(f"\nweek windows OK: {len(CASES)} случаев одной таблицей в обоих двойниках, миг по зоне каравана, дверь говорит, что не так")
    return 0


if __name__ == "__main__":
    sys.exit(main())
