#!/usr/bin/env python3
"""Снимок static/js/model-list.js — список моделей страницы идёт за диском.

Доска получала список моделей один раз, с /api/state, а её опрос читает только
топологию: полка каравана на карточке машины (и редактор ячейки) не видели
модель, скачанную после открытия страницы (2026-09-26). Теперь топология несёт
отпечаток списка (ModelList в caravan/admin/models.py), и ModelListFollower
дочитывает строки, когда отпечаток страницы от него отстал.

Пинится значениями: когда он НЕ ходит за строками (нет состояния страницы, нет
отпечатка, отпечаток тот же), когда ходит — один раз на сколько угодно опросов
разом, — что кладёт на страницу, и что провал запроса оставляет список как был
и не мешает следующему опросу спросить снова. Страница и запрос подставные;
одиночка MODEL_LIST — с настоящими state.js и api() (fetch записывающий).

Запуск: python3 scripts/test_js_model_list.py
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
const { ModelListFollower, MODEL_LIST } = await import(pathToFileURL(process.env.JS_ROOT + "/model-list.js").href);
const st = await import(pathToFileURL(process.env.JS_ROOT + "/state.js").href);

const OLD = [{ path: "old.gguf", kind: "model" }];
const NEW = [{ path: "old.gguf", kind: "model" }, { path: "new.gguf", kind: "model" }];
// A follower over a page it owns and a fetch that counts and answers `reply`
// (a function: called per fetch, may throw or reject).
const mk = (page, reply) => {
  const f = { page, calls: 0 };
  f.it = new ModelListFollower({
    page: () => f.page,
    fetchRows: () => { f.calls += 1; return typeof reply === "function" ? reply(f.calls) : Promise.resolve(reply); },
  });
  return f;
};
const view = (f) => ({ models: Array.isArray(f.page?.models) ? f.page.models.map((r) => r.path) : f.page?.models ?? null,
  stamp: f.page?.modelsStamp ?? null, calls: f.calls });

const out = {};

// Where it does not fetch.
{
  const f = mk(null, { models: NEW, stamp: "b" });
  out.noPage = [await f.it.follow("b"), f.calls];
}
{
  const f = mk({ models: OLD, modelsStamp: "a" }, { models: NEW, stamp: "b" });
  out.noStamp = [await f.it.follow(""), await f.it.follow(undefined), await f.it.follow(null), view(f)];
}
{
  const f = mk({ models: OLD, modelsStamp: "a" }, { models: NEW, stamp: "b" });
  out.sameStamp = [await f.it.follow("a"), view(f)];
}

// Where it does.
{
  const f = mk({ models: OLD, modelsStamp: "a" }, { models: NEW, stamp: "b" });
  out.moved = [await f.it.follow("b"), view(f)];
  out.movedThenSame = [await f.it.follow("b"), view(f)];
}
{
  let release;
  const gate = new Promise((r) => { release = r; });
  const f = mk({ models: OLD, modelsStamp: "a" }, () => gate.then(() => ({ models: NEW, stamp: "b" })));
  const both = [f.it.follow("b"), f.it.follow("b"), f.it.follow("b")];
  const inflightWhileWaiting = f.it.inflight !== null;
  release();
  out.together = [await Promise.all(both), f.calls, inflightWhileWaiting, f.it.inflight];
}
{
  const f = mk({ models: OLD, modelsStamp: "a" }, (n) => Promise.resolve({ models: n === 1 ? NEW : OLD, stamp: n === 1 ? "b" : "c" }));
  await f.it.follow("b");
  out.laterMove = [await f.it.follow("c"), view(f)];
}
{
  const f = mk({ models: OLD, modelsStamp: "a" }, { models: NEW });
  out.replyWithoutStamp = [await f.it.follow("b"), view(f)];
}
{
  // The list moved again between the beat's topology and the rows' fetch.
  const f = mk({ models: OLD, modelsStamp: "a" }, { models: NEW, stamp: "c" });
  out.replyNewerThanBeat = [await f.it.follow("b"), view(f), await f.it.follow("c"), f.calls];
}

// Where the fetch fails: the list stays, the next beat asks again.
{
  const f = mk({ models: OLD, modelsStamp: "a" }, (n) => (n === 1 ? Promise.reject(new Error("502")) : Promise.resolve({ models: NEW, stamp: "b" })));
  out.failed = [await f.it.follow("b"), view(f), f.it.inflight];
  out.failedThenAgain = [await f.it.follow("b"), view(f)];
}
{
  const f = mk({ models: OLD, modelsStamp: "a" }, () => { throw new Error("sync"); });
  out.throwsAtOnce = [await f.it.follow("b"), view(f)];
}
{
  const f = mk({ models: OLD, modelsStamp: "a" }, { ok: true, models: "nope", stamp: "b" });
  out.notAList = [await f.it.follow("b"), view(f)];
}

// The one the board uses: the page is state.js's state, the rows come from
// /api/models/rows.
globalThis.__fetchCalls = [];
globalThis.__fetchReply["/api/models/rows"] = { ok: true, models: NEW, stamp: "b" };
st.setState({ models: OLD, modelsStamp: "a" });
out.singleton = [MODEL_LIST.behind("a"), MODEL_LIST.behind("b"), await MODEL_LIST.follow("b"),
  globalThis.__fetchCalls.map((c) => `${c.method} ${c.path}`), st.state.models.map((r) => r.path), st.state.modelsStamp];
st.setState(null);
globalThis.__fetchCalls = [];
out.singletonBeforeState = [MODEL_LIST.behind("z"), await MODEL_LIST.follow("z"), globalThis.__fetchCalls.length];

console.log(JSON.stringify(out));
process.exit(0);
"""


def main():
    node = find_node()
    if node is None:
        print("js model-list: SKIPPED — node не найден: " + ", ".join(node_search_paths()))
        return 0
    path = ROOT / "scripts" / ".probe_js_model_list.tmp.mjs"
    path.write_text(PROBE)
    try:
        run = subprocess.run([node, str(path)], capture_output=True, text=True, cwd=ROOT, timeout=60,
                             env={"PATH": str(Path(node).parent), "JS_ROOT": str(ROOT / "static" / "js")})
    finally:
        path.unlink(missing_ok=True)
    if run.returncode != 0:
        print(run.stdout)
        print(run.stderr)
        print(f"js model-list FAILED: node вышел с кодом {run.returncode}")
        return 1
    got = json.loads(run.stdout.strip().splitlines()[-1])
    old, new = ["old.gguf"], ["old.gguf", "new.gguf"]

    print("когда за строками не ходит:")
    check(got["noPage"] == [False, 0],
          "у страницы ещё нет состояния (/api/state в пути и принесёт свой список) — не ходит")
    check(got["noStamp"] == [False, False, False, {"models": old, "stamp": "a", "calls": 0}],
          "топология без отпечатка (контроллер старше него) — не ходит, список как был")
    check(got["sameStamp"] == [False, {"models": old, "stamp": "a", "calls": 0}],
          "negative: отпечаток тот же — список страницы и есть нынешний, запроса нет")

    print("когда ходит:")
    check(got["moved"] == [True, {"models": new, "stamp": "b", "calls": 1}],
          "отпечаток сдвинулся — строки дочитаны, на странице новый список и отпечаток ответа")
    check(got["movedThenSame"] == [False, {"models": new, "stamp": "b", "calls": 1}],
          "negative: следующий опрос с тем же отпечатком — второго запроса нет")
    check(got["together"] == [[True, True, True], 1, True, None],
          "три опроса разом, пока строки в пути, — один запрос на всех; после ответа путь свободен")
    check(got["laterMove"] == [True, {"models": old, "stamp": "c", "calls": 2}],
          "отпечаток сдвинулся ещё раз (модель удалили) — новый запрос, список снова идёт за диском")
    check(got["replyNewerThanBeat"] == [True, {"models": new, "stamp": "c", "calls": 1}, False, 1],
          "список сменился ещё раз между опросом и запросом строк — страница держит отпечаток ОТВЕТА (он называет "
          "строки, что пришли), и следующий опрос с этим отпечатком за ними не ходит")
    check(got["replyWithoutStamp"] == [True, {"models": new, "stamp": "b", "calls": 1}],
          "boundary: ответ без своего отпечатка прочитан после отпечатка топологии — страница держит его, "
          "а не ходит за строками на каждом опросе")

    print("когда запрос не удался:")
    check(got["failed"] == [False, {"models": old, "stamp": "a", "calls": 1}, None],
          "запрос упал — список и отпечаток страницы как были (не пустой список вместо моделей), путь свободен")
    check(got["failedThenAgain"] == [True, {"models": new, "stamp": "b", "calls": 2}],
          "следующий опрос спрашивает снова и получает строки")
    check(got["throwsAtOnce"] == [False, {"models": old, "stamp": "a", "calls": 1}],
          "boundary: запрос бросил сразу, не дойдя до обещания, — то же «не удалось», опрос не падает")
    check(got["notAList"] == [False, {"models": old, "stamp": "a", "calls": 1}],
          "negative: в ответе вместо списка что-то другое — страница его не берёт")

    print("одиночка доски:")
    check(got["singleton"] == [False, True, True, ["GET /api/models/rows"], new, "b"],
          "MODEL_LIST держит state.js-состояние страницы и берёт строки с GET /api/models/rows")
    check(got["singletonBeforeState"] == [False, False, 0],
          "страница без состояния (отдельная страница роутера не грузит /api/state) — ни запроса, ни падения")
    print()
    if _fail:
        print(f"FAILED ({len(_fail)}):")
        for msg in _fail:
            print("  - " + msg)
        return 1
    print("js model-list OK: список страницы идёт за отпечатком, один запрос, провал оставляет список")
    return 0


if __name__ == "__main__":
    sys.exit(main())
