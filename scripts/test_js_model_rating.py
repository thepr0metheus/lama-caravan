#!/usr/bin/env python3
"""Actual model-rating.js: the owner's like or dislike of a model, as every page draws it, by value.

One mark for all a model's quants, kept by its folder (rust/crates/admin/src/models/notes.rs, ModelRatings). What is pinned, on the real module:
which words of a map are a mark, how a path of the library finds its model's mark, what a press leaves, the mark as a list shows it
and the two buttons that set it. A model with no mark draws nothing: no mark is no opinion, and it must not read as a neutral one.

Run: python3 scripts/test_js_model_rating.py
"""
import os
from pathlib import Path
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _node import find_node, probe_args
ROOT = Path(__file__).resolve().parent.parent
PROBE = r'''
globalThis.__stubReturns = { "utils.escapeHtml": (x) => String(x ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll('"', "&quot;") };
const { ModelRating } = await import("../static/js/model-rating.js");
const failed = [];
let pins = 0;
const pin = (what, got, want) => {
  pins++;
  const a = JSON.stringify(got), b = JSON.stringify(want);
  console.log(a === b ? `  ok  ${what}` : ` FAIL ${what}\n       got  ${a}\n       want ${b}`);
  if (a !== b) failed.push(what);
};
const words = (key) => `<${key}>`;
const R = { good: "like", bad: "dislike", odd: "great", num: 1, toString: "like" };
pin("из карты читаются только настоящие оценки", ["good", "bad", "odd", "num", "none", ""].map((m) => ModelRating.of(R, m)), ["like", "dislike", "", "", "", ""]);
pin("negative: карты нет — оценки нет; унаследованное от Object оценкой не считается", [ModelRating.of(null, "good"), ModelRating.of(undefined, "good"), ModelRating.of({}, "constructor")], ["", "", ""]);
pin("путь библиотеки находит оценку своей модели", ModelRating.ofPath(R, "good/author/Q4/m.gguf"), "like");
pin("negative: файл прямо в библиотеке, чужой диск и путь наверх модели не называют",
  [ModelRating.ofPath({ "m.gguf": "like" }, "m.gguf"), ModelRating.ofPath(R, "/home/u/good/a/Q4/m.gguf"), ModelRating.ofPath({ "..": "like" }, "../up/m.gguf")], ["", "", ""]);
pin("нажатие: та же оценка снимается, другая сменяет, на пустом ставится",
  [ModelRating.pressed("like", "like"), ModelRating.pressed("like", "dislike"), ModelRating.pressed("", "dislike")], ["", "dislike", "dislike"]);
const mark = ModelRating.markHtml("like", words);
pin("значок: знак, хук и слова, с экранированием", mark, '<span class="model-rating" data-t="model-rating" data-t-state="like" title="&lt;ratingLike>" aria-label="&lt;ratingLike>">👍</span>');
pin("дизлайк — своим знаком и словами", ModelRating.markHtml("dislike", words).includes('data-t-state="dislike" title="&lt;ratingDislike>"') && ModelRating.markHtml("dislike", words).includes(">👎<"), true);
pin("negative: без оценки значка нет; чужое слово значком не рисуется", ["", null, undefined, "great", "constructor"].map((r) => ModelRating.markHtml(r, words)), ["", "", "", "", ""]);
const buttons = ModelRating.buttonsHtml('a"b', "dislike", words, { cls: "box", hook: 'data-t="here"' });
const each = [...buttons.matchAll(/<button type="button" class="model-rate-btn( is-on)?" aria-pressed="(true|false)" data-model-rate="(like|dislike)" data-model-rate-for="([^"]*)" data-t="here" data-t-id="([^"]*)" title="([^"]*)" aria-label="[^"]*">(👍|👎)<\/button>/g)].map((m) => m.slice(1));
pin("две кнопки в своей коробке: нажата та, что стоит; имя модели экранировано", [buttons.startsWith('<span class="box">'), each],
  [true, [[null, "false", "like", "a&quot;b", "a&quot;b:like", "&lt;ratingLike>", "👍"], [" is-on", "true", "dislike", "a&quot;b", "a&quot;b:dislike", "&lt;ratingDislike>", "👎"]]]);
pin("negative: без оценки ни одна не нажата", (ModelRating.buttonsHtml("m", "", words, { cls: "b", hook: 'data-t="h"' }).match(/aria-pressed="true"/g) || []).length, 0);
const button = (kind) => { const e = { dataset: { modelRate: kind }, attrs: {}, on: null }; e.classList = { toggle: (_, v) => { e.on = v; } }; e.setAttribute = (k, v) => { e.attrs[k] = v; }; return e; };
const like = button("like"), dislike = button("dislike");
ModelRating.mark(like, "like"); ModelRating.mark(dislike, "like");
pin("кнопка в странице следует оценке модели", [like.on, like.attrs["aria-pressed"], dislike.on, dislike.attrs["aria-pressed"]], [true, "true", false, "false"]);
ModelRating.mark(like, "");
pin("negative: оценку сняли — кнопка отжата", [like.on, like.attrs["aria-pressed"]], [false, "false"]);
if (failed.length) { console.log(`\nFAILED (${failed.length}):`); process.exit(1); }
console.log(`js model rating OK: настоящий модуль в node, ${pins} пинов значениями`);
'''
node = find_node()
if not node:
    raise SystemExit('node required')
probe = ROOT / 'scripts' / '.probe_model_rating.tmp.mjs'
probe.write_text(PROBE)
try:
    harness = ROOT / 'scripts' / '_js_harness.mjs'
    result = subprocess.run(probe_args(node, harness, probe), cwd=ROOT,
                            env={**os.environ, 'JS_ROOT': str(ROOT / 'static/js'), 'JS_STUBS': 'utils'}, capture_output=True, text=True, timeout=120)
    print(result.stdout, end='')
    print(result.stderr, end='', file=sys.stderr)
finally:
    probe.unlink(missing_ok=True)
raise SystemExit(result.returncode)
