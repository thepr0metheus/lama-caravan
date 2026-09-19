#!/usr/bin/env python3
"""Snapshot of the confirm dialog's knitted llama scenes (dialog-llamas.js).

The scenes are pixel art on a 22×14 grid, so what can be pinned is their story
frame by frame and the rules that keep it legible, not their pixels one by one.

The "move" scene — a pack llama carrying a parcel to the library cabinet — is
pinned closely, because it was drawn twice: the first cut tossed the parcel
straight through the llama's head and parked its nose inside the shelf.

* The story: loaded → walks up → lifts the pack → over the head → to the hatch
  → in, and checked (a spark in the accent colour) → the hatch shuts as it
  steps back → open again, and the next pack comes down.
* The pack rides the llama's OWN layer, so it walks with it, and is gone from
  its back from the moment it is lifted until the next one comes down.
* The arc never passes through the llama: no prop cell lands on a llama cell
  in any frame, and the only row above the grid it uses is the one the stage
  still shows.
* The loop is seamless: the hatch is open and empty at the start and at the
  end, so no parcel blinks out of existence between two rounds.
* The pack reads on every llama: its colours are none of the bodies' (three of
  the bodies are the crates' browns, and a wooden pack on a brown llama was
  simply gone).
* The library is scenery: it sits on the static sky layer; a scene without
  scenery has none.
* The other scenes kept their shape through the refactor that made frames
  pure data: same frame counts, same first poses.

Run: python3 scripts/test_js_dialog_llamas.py
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _node import find_node, node_search_paths  # noqa: E402

STUBS = ""

PREAMBLE = r"""
import "./_js_globals.mjs";
import { pathToFileURL } from "node:url";
const L = await import(pathToFileURL(process.env.JS_ROOT + "/dialog-llamas.js").href);
const BODIES = ["#d9c29a", "#e8e2d4", "#a97e4f", "#b9b3a7", "#8a6f52", "#cbb188"];
const KRAFT = new Set(["#e3c48a", "#b8894f", "#6e5137"]);
const ACCENT = "#123456";
const move = (body = BODIES[0]) => L.sceneFrames("move", { body, blanket: "#9a7bd0", accent: ACCENT });
const key = ([x, y]) => `${x},${y}`;
// Cells of the llama layer where they actually stand: the layer is shifted.
const placed = (f) => new Set(f.llama.map(([x, y]) => key([x + f.shift, y])));
const packOn = (f) => f.llama.filter(([, , c]) => c === "#e3c48a" || c === "#b8894f");
const reset = () => {};
reset();
const out = {};
"""

PINS = [
    ("move_story_frame_by_frame", '',
     'move().map((f) => [f.pose, f.shift, f.slide])',
     json.dumps([["standA", 0, False], ["standB", 1, False], ["bow", 1, False], ["bow", 1, False], ["bow", 1, False],
                 ["standA", 1, False], ["standB", 0, False], ["standA", 0, False], ["standA", 0, False]]),
     "перенос по кадрам: нагружена → подходит к шкафу → снимает тюк → над головой → к дверце → внутри и проверено "
     "→ дверца закрывается, лама отступает → снова открыта, и спускается следующий тюк"),
    ("the_pack_rides_the_llama", '',
     'move().map((f) => { const p = packOn(f); return p.length ? [Math.min(...p.map((c) => c[1])), Math.max(...p.map((c) => c[1]))] : null; })',
     json.dumps([[4, 5], [4, 5], None, None, None, None, None, None, [2, 3]]),
     "тюк — на СЛОЕ ЛАМЫ, поэтому идёт вместе с ней: на спине в первых двух кадрах, снят с момента подъёма "
     "и до следующего, а новый спускается сверху (строки 2–3) прежде чем лечь"),
    ("the_arc_never_passes_through_the_llama", '',
     'move().map((f) => { const at = placed(f); return f.prop.filter((c) => at.has(key(c))).length; })',
     json.dumps([0] * 9),
     "дуга ни в одном кадре не проходит сквозь ламу: ни одна клетка тюка не ложится на клетку ламы "
     "(первая версия бросала тюк ей в голову)"),
    ("the_arc_stays_on_stage", '',
     '(() => { const rows = move().flatMap((f) => f.prop.map((c) => c[1])); const cols = move().flatMap((f) => [...f.prop, ...f.llama.map(([x, y, c]) => [x + f.shift, y, c])].map((c) => c[0])); '
     'return [Math.min(...rows), Math.max(...rows), Math.min(...cols), Math.max(...cols), move().filter((f) => f.prop.some((c) => c[1] < 0)).length]; })()',
     '[-1,7,1,20,1]',
     "всё на сцене: всё подвижное — в колонках 1..20 (21-я — стенка шкафа на слое декораций), над сеткой — "
     "только одна строка (её сцена ещё показывает), и только в верхней точке дуги"),
    ("the_loop_is_seamless", '',
     '(() => { const f = move(); const hatchShut = (fr) => fr.prop.some(([x, y, c]) => x === 20 && y === 6 && c === "#c8a06c"); '
     'const inHatch = (fr) => fr.prop.some(([x, y]) => x >= 18 && x <= 20 && y >= 6 && y <= 7); '
     'return [f[0].prop.length, f[f.length - 1].prop.length, inHatch(f[5]), hatchShut(f[6]), hatchShut(f[7]), f.map(hatchShut).filter(Boolean).length]; })()',
     '[0,0,true,true,true,2]',
     "петля бесшовная: дверца пуста в начале и в конце круга, тюк внутри — в кадре «проверено», "
     "дверца закрыта ровно два кадра; иначе между кругами тюк исчезал бы на глазах"),
    ("the_spark_says_checked_once", '',
     'move().map((f) => f.prop.filter((c) => c[2] === ACCENT).length)',
     json.dumps([0, 0, 0, 0, 0, 4, 0, 0, 0]),
     "искра цвета акцента — ровно в кадре, где тюк внутри: копия сверена; в остальных кадрах её нет"),
    ("the_pack_reads_on_every_llama", '',
     'BODIES.map((body) => { const f = move(body)[0]; return packOn(f).length === 4 && f.llama.filter((c) => KRAFT.has(c[2])).every((c) => c[2] !== body); })',
     json.dumps([True] * 6),
     "тюк виден на ламе любого цвета: цвета крафта не совпадают ни с одним телом — три тела тех же коричневых, "
     "что ящики, и деревянный тюк на коричневой ламе пропадал"),
    ("the_library_is_scenery", '',
     '[L.sceneSky("move").length > 0, L.sceneSky("move").some((c) => c[2] === "#4f8fd0"), L.sceneSky("start").length > 0, L.sceneSky("delete").length, L.sceneSky("stop").length]',
     '[true,true,true,0,0]',
     "шкаф-библиотека с корешками книг — неподвижная декорация (слой неба); у ракеты своя (луна и площадка); "
     "negative: у сцен без декораций слой пуст"),
    ("the_other_scenes_kept_their_shape", '',
     '["create", "delete", "stop", "start", "change"].map((k) => { const f = L.sceneFrames(k, {}); return [k, f.length, f[0].pose, f.some((x) => x.slide)]; })',
     json.dumps([["create", 6, "standA", True], ["delete", 6, "standA", True], ["stop", 6, "standA", False],
                 ["start", 10, "standA", True], ["change", 4, "standA", False]]),
     "negative: остальные сцены пережили перевод кадров в чистые данные — те же числа кадров, "
     "те же первые позы, тот же «въезд» нового реквизита"),
    ("an_unknown_scene_is_the_toggle", '',
     'L.sceneFrames("no-such-scene", {}).length',
     '4',
     "negative: незнакомая сцена падает в «переключатель» (4 кадра), а не в пустоту"),
]


_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def main():
    if len(PINS) < 10:
        print(f"js dialog-llamas FAILED: всего {len(PINS)} пинов — снимок урезан")
        return 1
    node = find_node()
    if node is None:
        print("js dialog-llamas: SKIPPED — node не найден: " + ", ".join(node_search_paths()))
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
    path = ROOT / "scripts" / ".probe_js_dialog_llamas.tmp.mjs"
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
        print(f"js dialog-llamas FAILED: node вышел с кодом {run.returncode}")
        return 1
    both = json.loads(run.stdout.strip().splitlines()[-1])
    got, rev = both["out"], both["rev"]
    print("сцены ламы в окне подтверждения:")
    for pid, _s, _e, expected, msg in PINS:
        want, have = json.loads(expected), got.get(pid, "\0missing")
        check(have == want, msg if have == want else
              f"{msg}\n        ожидалось {json.dumps(want, ensure_ascii=False)[:240]}"
              f"\n        получено  {json.dumps(have, ensure_ascii=False)[:240]}")
        if have != rev.get(pid, "\0missing"):
            _fail.append(f"пин {pid} зависит от порядка")
    print(f"порядок: {len(PINS)} пинов дают те же значения в обратном порядке" if not _fail else "")
    print()
    if _fail:
        print(f"FAILED ({len(_fail)}):")
        for m in _fail:
            print("  - " + m.splitlines()[0])
        return 1
    print(f"js dialog-llamas OK: настоящий модуль в node, {len(PINS)} пинов сцен значениями")
    return 0


if __name__ == "__main__":
    sys.exit(main())
