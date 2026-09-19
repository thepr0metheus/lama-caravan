#!/usr/bin/env python3
"""Snapshot of static/js/hf-catalog.js and static/js/hf-text.js — what the /hf
page knows about repositories and which of them a tab shows, and the words and
numbers it prints.

Pinned by value. A repository's size is read off its name as a whole token and
anything outside 0.1–10000 is "unknown"; the size buckets run up to the next
one's start (9.5B is "≤9B"). Capabilities: instruct and uncensored by name,
vision by the record's modality or an mmproj file, audio by modality, mmproj
and mtp only from the file list — and until that list is in, "has no mmproj"
is not an answer yet. The format comes from tags, the checkpoint, then the
name. A record merged in never erases a known date with an empty one.

A tab's view: the name filter ignores case; a size filter hides what has no
size in its name and says how many it hid; a capability filter matches any
chosen one, hides known absence silently and counts what it cannot check yet.
The chip counts are faceted — each under the other filters. Sorting by every
key, both ways, unknown values last in "descending", ties in the server's
order. Favorites: a new one goes first, the payload keeps the date and the
modality when known. HfText: variables, the English fallback, "ago" words;
HfFormat: counts and sizes.

Run: python3 scripts/test_js_hf_catalog.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _js_pins import run  # noqa: E402

PREAMBLE = r"""
import "./_js_globals.mjs";
import { pathToFileURL } from "node:url";
const C = await import(pathToFileURL(process.env.JS_ROOT + "/hf-catalog.js").href);
const T = await import(pathToFileURL(process.env.JS_ROOT + "/hf-text.js").href);
const GB = 2 ** 30;
const bench = { data: {}, scores(id) { return (this.data[id] || {}); } };
const facts = (id, record = {}) => new C.HfRepoFacts(id).merge(record);
const withFiles = (f, kinds) => { f.setFiles({ files: kinds.map((k, i) => ({ kind: k, quant: k === "model" ? "Q4_K_M" : "", name: `${k}${i}.gguf`, path: `${k}${i}.gguf`, size: 1 })) }); return f; };
const reset = () => { localStorage.clear(); bench.data = {}; };
const catalog = () => {
  const c = new C.HfCatalog(bench);
  c.setResults([
    { id: "unsloth/Qwen3.6-27B-GGUF", downloads: 900, likes: 5, createdAt: "2026-04-01T00:00:00Z", pipelineTag: "image-text-to-text", tags: ["gguf"] },
    { id: "acme/tiny-9.5B-it-GGUF", downloads: 100, likes: 50, createdAt: "2026-08-01T00:00:00Z", tags: ["gguf"] },
    { id: "acme/nameless-GGUF", downloads: 500, likes: 9, createdAt: "2026-02-01T00:00:00Z" },
    { id: "bob/Big-120B-heretic-GGUF", downloads: 500, likes: 1, createdAt: "2026-05-01T00:00:00Z" },
  ]);
  return c;
};
"""

PINS = [
    ("size_is_read_off_the_name_as_a_whole_token", "",
     r"""["unsloth/Qwen3.6-27B-MTP-GGUF", "Qwen/Qwen3-Embedding-0.6B-GGUF", "unsloth/Qwen3.6-35B-A3B-GGUF", "unsloth/gemma-4-12b-it-GGUF",
        "acme/Qwen3.6-GGUF", "acme/model-20000B-GGUF", "acme/Qwen2.5B-GGUF", "acme/model-4bit-GGUF"].map((id) => [facts(id).params, facts(id).paramsLabel])""",
     '[[27,"27B"],[0.6,"0.6B"],[35,"35B"],[12,"12B"],[null,""],[null,""],[null,""],[null,""]]',
     "размер из имени: 27B, 0.6B, первое «NB» (35B, не A3B), строчная b; нет токена, 20000B, «Qwen2.5B» без разделителя и «4bit» (за b идут буквы) — неизвестно"),

    ("size_buckets_run_up_to_the_next_start", "",
     r"""["a/x-9B", "a/x-9.5B", "a/x-10B", "a/x-19.9B", "a/x-29B", "a/x-39B", "a/x-74.5B", "a/x-75B", "a/x-405B", "a/x-GGUF"].map((id) => facts(id).bucket)""",
     '["0-9","0-9","10-19","10-19","20-29","30-39","40-74","75+","75+",null]',
     "корзины размера сплошные: 9.5B — «≤9B», 19.9B — «10–19B», 74.5B — «40–74B»; без размера — ни в одной"),

    ("capabilities_by_name_and_by_modality", "",
     r"""(() => { const ids = [["unsloth/gemma-4-12b-it-GGUF", {}], ["acme/x_it/y", {}], ["acme/britain-GGUF", {}], ["acme/heretic-GGUF", {}], ["acme/abliterated-GGUF", {}],
        ["acme/v-GGUF", { pipelineTag: "image-text-to-text" }], ["acme/a-GGUF", { tags: ["audio"] }], ["acme/b-GGUF", { pipelineTag: "any-to-any" }], ["acme/plain-GGUF", { tags: ["gguf"] }]];
        return ids.map(([id, r]) => facts(id, r).capabilities()); })()""",
     '[["it"],["it"],[],["uncensored"],["uncensored"],["vision"],["audio"],["vision","audio"],[]]',
     "возможности по имени (it, uncensored) и по модальности записи (vision, audio, any-to-any — обе); «britain» — не it"),

    ("file_kinds_are_known_only_once_the_list_is_in", "",
     r"""(() => { const f = facts("acme/plain-GGUF");
        const before = [f.has("mmproj"), f.knows("mmproj"), f.knows("mtp"), f.knows("vision"), f.knows("it"), f.kinds];
        withFiles(f, ["model", "mmproj", "mtp"]);
        return [before, [f.has("mmproj"), f.has("mtp"), f.has("vision"), f.knows("mmproj"), f.capabilities()]]; })()""",
     '[[false,false,false,false,true,null],[true,true,true,true,["vision","mmproj","mtp"]]]',
     "до списка файлов «нет mmproj» — не ответ (knows=false; vision тоже ждёт); после — mmproj даёт vision"),

    ("format_from_tags_checkpoint_then_name", "",
     r"""(() => { const st = facts("google/gemma-4-31B-it"); st.setFiles({ files: [], safetensors: { format: "BF16", files: [{ name: "a.safetensors" }], totalSize: 1 } });
        return [facts("a/b", { tags: ["gguf"] }).format, st.format, facts("a/b", { tags: ["mlx"] }).format, facts("a/Model-GGUF").format,
                facts("a/Model-NVFP4").format, facts("a/b", { tags: ["safetensors"] }).format, facts("a/b").format]; })()""",
     '["GGUF","BF16","MLX","GGUF","NVFP4","ST",""]',
     "формат: тег gguf, формат чекпоинта, тег mlx, «-GGUF» в имени, подсказка NVFP4, тег safetensors; ничего — пусто"),

    ("date_and_merge_keep_what_is_known", "",
     r"""(() => { const f = facts("a/b", { createdAt: "2026-01-01T00:00:00Z", downloads: 7 });
        f.merge({ createdAt: "", downloads: 9 });
        const noCreated = facts("a/c"); noCreated.setFiles({ files: [], lastModified: "2026-03-01T00:00:00Z" });
        return [f.date, f.downloads, noCreated.date, facts("a/d").date]; })()""",
     '["2026-01-01T00:00:00Z",9,"2026-03-01T00:00:00Z",""]',
     "дата: создания; пустая дата при слиянии не стирает известную; без неё — дата последнего файла; ничего — пусто"),

    ("name_filter_ignores_case", "",
     r"""(() => { const c = catalog(); c.mask = "QWEN"; const hit = c.view().items.map((f) => f.id); c.mask = "zzz"; const miss = c.view(); return [hit, miss.items.length, miss.total]; })()""",
     '[["unsloth/Qwen3.6-27B-GGUF"],0,4]',
     "фильтр по имени без учёта регистра; не совпало ничего — пусто, но всего по-прежнему 4"),

    ("size_filter_hides_unknown_and_counts_it", "",
     r"""(() => { const c = catalog(); c.size = "20-29"; const v = c.view(); c.size = "all"; const all = c.view();
        return [v.items.map((f) => f.id), v.hiddenNoSize, all.hiddenNoSize, all.items.length]; })()""",
     '[["unsloth/Qwen3.6-27B-GGUF"],1,0,4]',
     "фильтр размера прячет репозиторий без размера в имени и называет, сколько спрятал; без фильтра — никого и ноль"),

    ("capability_filter_any_known_absence_and_unchecked", "",
     r"""(() => { const c = catalog(); c.caps = new Set(["mmproj"]);
        const pending = c.view();
        for (const id of c.resultIds) withFiles(c.repo(id), id.includes("Qwen") ? ["model", "mmproj"] : ["model"]);
        const known = c.view();
        c.caps = new Set(["mmproj", "uncensored"]);
        const any = c.view().items.map((f) => f.id);
        return [pending.items.length, pending.unchecked, known.items.map((f) => f.id), known.unchecked, any]; })()""",
     '[0,4,["unsloth/Qwen3.6-27B-GGUF"],0,["unsloth/Qwen3.6-27B-GGUF","bob/Big-120B-heretic-GGUF"]]',
     "фильтр возможностей: пока файлы не пришли — не показывает и считает «не проверено»; известное отсутствие скрыто молча; несколько — любой из"),

    ("chip_counts_are_faceted", "",
     r"""(() => { const c = catalog(); for (const id of c.resultIds) withFiles(c.repo(id), ["model"]);
        c.mask = "gguf"; c.size = "75+";
        const sizes = c.sizeCounts(); const caps = c.capCounts().map((x) => [x.id, x.count]);
        c.caps = new Set(["audio"]); const chosen = c.capCounts().map((x) => [x.id, x.count]);
        return [sizes, caps, chosen, c.sizeCounts()]; })()""",
     '[{"all":4,"0-9":1,"10-19":0,"20-29":1,"30-39":0,"40-74":0,"75+":1},[["uncensored",1]],[["audio",0],["uncensored",1]],{"all":0,"0-9":0,"10-19":0,"20-29":0,"30-39":0,"40-74":0,"75+":0}]',
     "счёт чипов: размер — под остальными фильтрами без учёта размера (выбранная возможность, которой нет ни у кого, обнуляет все); возможности — только ненулевые, выбранная остаётся и с нулём"),

    ("sorting_every_key_both_ways", "",
     r"""(() => { const c = catalog(); const ids = () => c.view().items.map((f) => f.id.split("/")[1].split("-")[0]);
        bench.data = { "unsloth/Qwen3.6-27B-GGUF": { aa_intelligence: 21.9 }, "bob/Big-120B-heretic-GGUF": { aa_intelligence: 30, open_llm_avg: 40 } };
        const out = [];
        for (const [key, dir] of [["downloads", "desc"], ["downloads", "asc"], ["likes", "desc"], ["params", "desc"], ["params", "asc"], ["date", "desc"], ["aa", "desc"], ["olb", "desc"]]) {
          c.sortKey = key; c.sortDir = dir; out.push(ids()); }
        return out; })()""",
     '[["Qwen3.6","nameless","Big","tiny"],["tiny","nameless","Big","Qwen3.6"],["tiny","nameless","Qwen3.6","Big"],["Big","Qwen3.6","tiny","nameless"],["nameless","tiny","Qwen3.6","Big"],["tiny","Big","Qwen3.6","nameless"],["Big","Qwen3.6","tiny","nameless"],["Big","Qwen3.6","tiny","nameless"]]',
     "сортировка: загрузки ↓↑ (равные — в порядке сервера), лайки, размер ↓↑ (неизвестный последним), дата, AA и Open LLM (без балла — последними)"),

    ("favorites_go_first_and_keep_what_is_known", "",
     r"""(() => { const c = catalog(); c.setFavorites([{ id: "old/fav", downloads: 3, likes: 1 }]);
        const payload = c.toggleFavorite("unsloth/Qwen3.6-27B-GGUF");
        const after = [c.isFavorite("unsloth/Qwen3.6-27B-GGUF"), c.favoriteIds];
        const removed = c.toggleFavorite("unsloth/Qwen3.6-27B-GGUF");
        return [payload, after, removed, c.isFavorite("unsloth/Qwen3.6-27B-GGUF")]; })()""",
     '[[{"id":"unsloth/Qwen3.6-27B-GGUF","downloads":900,"likes":5,"createdAt":"2026-04-01T00:00:00Z","pipelineTag":"image-text-to-text","tags":["gguf"]},{"id":"old/fav","downloads":3,"likes":1}],[true,["unsloth/Qwen3.6-27B-GGUF","old/fav"]],[{"id":"old/fav","downloads":3,"likes":1}],false]',
     "избранное: новое — первым, в записи дата и модальность, если известны (у старой записи без них — нет); повторное нажатие убирает"),

    ("unknown_counts_stay_unknown", "",
     r"""(() => { const c = catalog(); c.setFavorites([{ id: "bartowski/gemma-4-12B-it-GGUF", downloads: 61351, likes: 17 }, { id: "never/counted-GGUF" }]);
        const f = c.repo("bartowski/gemma-4-12B-it-GGUF"); const n = c.repo("never/counted-GGUF");
        const before = [f.countLabel("downloads"), f.countLabel("likes"), n.countLabel("downloads"), n.countLabel("likes")];
        c.setResults([{ id: "bartowski/gemma-4-12B-it-GGUF" }]); const afterExact = [f.countLabel("downloads"), f.countLabel("likes"), f.downloads];
        const payload = c.toggleFavorite("unsloth/Qwen3.6-27B-GGUF").filter((x) => x.id !== "unsloth/Qwen3.6-27B-GGUF");
        const zero = facts("x/zero", { downloads: 0, likes: 0 });
        return [before, afterExact, payload, [zero.countLabel("downloads"), zero.countLabel("likes")], n.downloads]; })()""",
     '[["61.4k","17","—","—"],["61.4k","17",61351],[{"id":"bartowski/gemma-4-12B-it-GGUF","downloads":61351,"likes":17},{"id":"never/counted-GGUF"}],["0","0"],0]',
     "неизвестные числа: ответ без чисел (точный author/repo, когда HF не ответил) не затирает известные у избранного; чего не знали — «—», а в сохранении избранного его нет; настоящий ноль — «0»; для сортировки неизвестное — 0"),

    ("library_copies_by_name", "",
     r"""(() => { const f = new C.HfRepoFacts("unsloth/gemma-4-31B-it-GGUF"); const before = [f.libraryCount, f.libraryNames, f.inLibrary("x.gguf")];
        f.setLocal({ localNames: ["mtp.gguf"], localFiles: {}, libraryFiles: { "q5.gguf": [{ store: { id: "a", name: "lama-caravan-models" }, size: 1, mtime: 2 }],
          "q8.gguf": [{ store: { id: "a", name: "lama-caravan-models" }, size: 3, mtime: 4 }, { store: { id: "b", name: "second-shelf" }, size: 3, mtime: 5 }] } });
        const after = [f.libraryCount, f.libraryNames, f.inLibrary("q8.gguf").map((copy) => copy.store.name), f.inLibrary("mtp.gguf"), f.localCount];
        f.setLocal({ localNames: [] });
        return [before, after, [f.libraryCount, f.libraryNames]]; })()""",
     '[[0,[],[]],[2,["lama-caravan-models","second-shelf"],["lama-caravan-models","second-shelf"],[],1],[0,[]]]',
     "копии в библиотеках: по имени файла, счёт — файлов, библиотеки — каждая один раз; файл только на этом диске в библиотеке не числится; новый ответ без библиотек их стирает"),

    ("tabs_and_everything_to_load", "",
     r"""(() => { const c = catalog(); c.setFavorites([{ id: "bob/Big-120B-heretic-GGUF" }, { id: "old/fav" }]);
        const before = new C.HfCatalog(bench).searched;
        return [before, c.searched, c.view("favorites").total, c.view("results").total, c.allIds()]; })()""",
     '[false,true,2,4,["bob/Big-120B-heretic-GGUF","old/fav","unsloth/Qwen3.6-27B-GGUF","acme/tiny-9.5B-it-GGUF","acme/nameless-GGUF"]]',
     "вкладки: избранное и результаты; «искали» только после поиска; загрузить — избранное и результаты, каждый один раз"),

    ("text_variables_fallbacks_and_language", "",
     r"""(() => { const a = [T.hfT("listShown", { shown: 3, total: 20 }), T.hfT("noSuchKey")];
        localStorage.setItem(T.LANG_KEY, "ru"); const ru = T.hfT("listShown", { shown: 3, total: 20 });
        localStorage.setItem(T.LANG_KEY, "xx"); const unknown = T.hfT("tabResults");
        return [...a, ru, unknown, T.hfText.lang]; })()""",
     '["3 of 20","noSuchKey","3 из 20","Results","en"]',
     "слова: подстановка переменных, неизвестный ключ — сам ключ, русский по ключу языка, неизвестный язык — английский"),

    ("ago_words", "",
     r"""(() => { const now = Date.parse("2026-09-16T12:00:00Z");
        return ["2026-09-16T01:00:00Z", "2026-09-15T00:00:00Z", "2026-09-06T00:00:00Z", "2026-05-01T00:00:00Z", "2024-09-01T00:00:00Z", "2026-10-01T00:00:00Z", "nope", ""]
          .map((iso) => T.hfText.ago(iso, now)); })()""",
     '["today","yesterday","10d ago","4mo ago","2y ago","today","",""]',
     "«назад»: сегодня, вчера, дни, месяцы, годы; дата в будущем — сегодня, а не «-15d»; негодная и пустая — пусто"),

    ("numbers_and_sizes", "",
     r"""[T.HfFormat.count(999), T.HfFormat.count(61351), T.HfFormat.count(1268083), T.HfFormat.count(undefined),
        T.HfFormat.bytes(12669647328), T.HfFormat.bytes(175115712), T.HfFormat.bytes(1000), T.HfFormat.bytes(0), T.HfFormat.gib(50 * GB, 1)]""",
     '["999","61.4k","1.3M","0","11.8 GB","167 MB","1 MB","—","50.0"]',
     "числа: счёт 999/61.4k/1.3M; размеры в двоичных GB и MB, крошечный — 1 MB, ноль — «—»"),
]


if __name__ == "__main__":
    sys.exit(run("js hf-catalog", ".probe_js_hf_catalog.tmp.mjs", PREAMBLE, PINS))
