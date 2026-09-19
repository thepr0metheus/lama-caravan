#!/usr/bin/env python3
"""Snapshot of static/js/hf-bench.js — benchmarks on /hf and the frontier they
are read against.

Pinned by value. Loading: one request per repository however many callers
ask, the answer cached (a failure too, as "nothing"), a forced refresh asks
again with force=1. The queue: one repository after another, skipping what is
cached, counting as it goes, and a newer queue stops an older one. The frontier
list: only scored models, best first, with its source; forced with force=1.

Reading a score against it: the neighbours below and above, the top and the
bottom of the list; up to four ticks spread over the ranking; a scale that
widens for a score above 65. The list row: a placeholder while loading, "no
data" when there is none, the bar with ticks, other headline scores as chips.
The repository line: loading, "no data" with refresh, the mark between its
neighbours with where the data comes from and whether it is cached, the toggle
of the full panel. The full panel: group labels and descriptions in the page's
language by key — the server's Russian only for what the page has no word for
— with bars, values and links. The frontier panel: the list with the
repository placed in it, the snapshot note only for the built-in list.

Run: python3 scripts/test_js_hf_bench.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _js_pins import run  # noqa: E402

PREAMBLE = r"""
import "./_js_globals.mjs";
import { pathToFileURL } from "node:url";
const B = await import(pathToFileURL(process.env.JS_ROOT + "/hf-bench.js").href);
let asked, answers, bench;
// Out of order on purpose: the list is ranked by the page, not by the server.
const FRONTIER = () => ({ ok: true, source: "default", models: [
  { org: "Google", name: "Gemini 2.5 Flash", aa: 20.6 }, { org: "Meta", name: "Llama 4 Scout", aa: 13.5 }, { org: "Anthropic", name: "Claude Fable 5", aa: 64.9 },
  { org: "X", name: "Unscored", aa: null }, { org: "Mistral", name: "Mistral Large 2", aa: 15.1 }, { org: "OpenAI", name: "GPT-5.4", aa: 56.8 },
  { org: "Meta", name: "Llama 4 Maverick", aa: 18.4 }] });
const reset = () => { asked = []; answers = {};
  bench = new B.HfBench({ getJson: async (url) => { asked.push(url); const a = answers[url]; if (a instanceof Error) throw a; return a === undefined ? { ok: false } : a; }, wait: async () => {} }); };
const settle = async () => { for (let i = 0; i < 12; i++) await new Promise((r) => setImmediate(r)); };
const GROUPS = [{ id: "summary", label: "Сводные рейтинги", keys: ["aa_intelligence", "arena_elo"] }, { id: "math", label: "Математика и рассуждение", keys: ["mt_bench"] },
  { id: "future", label: "Будущая группа", keys: ["new_bench"] }, { id: "code", label: "Код", keys: [] }];
const META = { aa_intelligence: ["AA Intelligence", "Индекс качества", "0–65", "summary", "https://artificialanalysis.ai/leaderboards/models"],
  arena_elo: ["Arena Elo", "Живой рейтинг", "~800–1400", "summary", ""], mt_bench: ["MT-Bench", "Качество диалога", "1–10", "math", ""],
  new_bench: ["NewBench", "Новый бенчмарк без перевода", "0–100 %", "future", ""] };
const DATA = (over = {}) => ({ ok: true, scores: { aa_intelligence: 14.2, arena_elo: 1234, mt_bench: 8.25, new_bench: 55 }, inline: ["arena_elo", "aa_intelligence", "mt_bench"],
  groups: GROUPS, meta: META, data_from: "google/gemma-4-12B-it", from_cache: true, ...over });
"""

PINS = [
    ("one_request_cached_and_forced", "",
     r"""await (async () => { const url = "/api/hf/benchmarks?repo=a%2Fb"; answers[url] = { ok: true, scores: { aa_intelligence: 20 } };
        const [x, y] = await Promise.all([bench.load("a/b"), bench.load("a/b")]); await bench.load("a/b");
        answers["/api/hf/benchmarks?repo=a%2Fb&force=1"] = { ok: true, scores: { aa_intelligence: 21 } }; await bench.load("a/b", true);
        answers["/api/hf/benchmarks?repo=c%2Fd"] = new Error("down"); const failed = await bench.load("c/d"); await bench.load("c/d");
        return [asked, x === y, bench.aa("a/b"), failed, bench.data("c/d"), bench.data("e/f")]; })()""",
     '[["/api/hf/benchmarks?repo=a%2Fb","/api/hf/benchmarks?repo=a%2Fb&force=1","/api/hf/benchmarks?repo=c%2Fd"],true,21,null,null,null]',
     "бенчмарки: один запрос на двоих, дальше из кэша; force=1 спрашивает снова; отказ кэшируется как «нет данных»; не загружали — undefined (null в JSON)"),

    ("queue_skips_cached_counts_and_yields", "",
     r"""await (async () => { bench.cache.set("a/1", null); const steps = [];
        const first = bench.loadAll(["a/1", "a/2", "a/3"], (id) => steps.push([id, bench.done, bench.total]));
        const second = bench.loadAll(["a/4"], (id) => steps.push([id, bench.done, bench.total]));
        await Promise.all([first, second]);
        return [steps, asked, bench.running]; })()""",
     '[[[null,0,2],[null,0,1],["a/4",1,1]],["/api/hf/benchmarks?repo=a%2F2","/api/hf/benchmarks?repo=a%2F4"],false]',
     "очередь: пропускает загруженное, считает шаги; новая очередь останавливает старую — та не досчитывает до a/3"),

    ("frontier_list_scored_best_first", "",
     r"""await (async () => { answers["/api/hf/reference-models"] = FRONTIER(); await bench.loadFrontier();
        answers["/api/hf/reference-models?force=1"] = { ok: true, source: "aa", models: [{ org: "A", name: "M", aa: 1 }] }; const before = bench.frontierModels().map((m) => m.name);
        await bench.loadFrontier(true);
        return [before, bench.frontier.source, asked]; })()""",
     '[["Claude Fable 5","GPT-5.4","Gemini 2.5 Flash","Llama 4 Maverick","Mistral Large 2","Llama 4 Scout"],"aa",["/api/hf/reference-models","/api/hf/reference-models?force=1"]]',
     "фронтир: только с баллом, лучшие первыми; обновление — с force=1 и новым источником"),

    ("neighbours_ticks_and_scale", "",
     r"""await (async () => { answers["/api/hf/reference-models"] = FRONTIER(); await bench.loadFrontier();
        const n = (aa) => { const { lo, hi } = bench.neighbours(aa); return [lo && lo.name, hi && hi.name]; };
        return [n(14.2), n(13.5), n(70), n(10), bench.ticks().map((m) => m.name), bench.ticks(10).length, bench.scale(20), bench.scale(80)]; })()""",
     '[["Llama 4 Scout","Mistral Large 2"],["Llama 4 Scout","Mistral Large 2"],["Claude Fable 5",null],[null,"Llama 4 Scout"],["Claude Fable 5","Gemini 2.5 Flash","Llama 4 Maverick","Llama 4 Scout"],6,65,80]',
     "соседи снизу и сверху (равный балл — сосед снизу), выше всех и ниже всех; четыре засечки по рангу; меньше моделей — все; шкала 0–65, шире — для балла выше"),

    ("row_score_states", "",
     r"""await (async () => { answers["/api/hf/reference-models"] = FRONTIER(); await bench.loadFrontier();
        const pending = bench.rowHtml("x/pending"); bench.cache.set("x/none", null); bench.cache.set("x/empty", { ok: true, scores: {}, inline: [] });
        bench.cache.set("x/aa", DATA()); bench.cache.set("x/elo", { ok: true, scores: { arena_elo: 1300 }, inline: ["arena_elo"], meta: META });
        const aa = bench.rowHtml("x/aa"); const elo = bench.rowHtml("x/elo");
        return [pending.includes("is-pending"), bench.rowHtml("x/none").includes(">no data<"), bench.rowHtml("x/empty").includes(">no data<"),
                aa.includes('class="hfp-aa-fill" style="width:21.8%"'), (aa.match(/hfp-tick/g) || []).length, aa.includes("<b>14.2</b>"),
                aa.includes("hfp-bchip is-elo") && aa.includes("Arena Elo <b>1234</b>"), aa.includes("MT-Bench <b>8.3</b>"),
                elo.includes("hfp-aa-fill"), elo.includes("Arena Elo <b>1300</b>")]; })()""",
     '[true,true,true,true,4,true,true,true,false,true]',
     "строка списка: пока грузится — заглушка; нет данных — «no data»; AA — полоса на шкале с 4 засечками и значением; прочие главные баллы — чипы (Elo золотой, MT-Bench с одним знаком); без AA — только чипы"),

    ("repository_line", "",
     r"""await (async () => { answers["/api/hf/reference-models"] = FRONTIER(); await bench.loadFrontier();
        const loading = bench.stripHtml("x/pending", false); bench.cache.set("x/none", null); const none = bench.stripHtml("x/none", false);
        bench.cache.set("x/aa", DATA()); const closed = bench.stripHtml("x/aa", false); const open = bench.stripHtml("x/aa", true);
        bench.cache.set("x/own", DATA({ data_from: "x/own", from_cache: false })); const own = bench.stripHtml("x/own", false);
        return [loading.includes("Loading benchmarks…"), none.includes("AA — No benchmark data") && none.includes('data-t="hf-bench-refresh"') && !none.includes("hf-bench-toggle"),
                closed.includes('class="hfp-scale-me" style="left:21.8%"'), closed.includes("between Llama 4 Scout 13.5 and Mistral Large 2 15.1"),
                closed.includes("data for google/gemma-4-12B-it"), closed.includes(">cached<"), closed.includes('aria-expanded="false">all benchmarks ▾'),
                open.includes('aria-expanded="true">hide benchmarks ▴'), own.includes("data for"), own.includes(">fresh<"), closed.includes('data-t="hf-frontier-open"')]; })()""",
     '[true,true,true,true,true,true,true,true,false,true,true]',
     "строка репозитория: загрузка; нет данных — с обновлением, без раскрытия; метка на шкале, соседи, чьи данные и кэш, «все бенчмарки»/«скрыть»; данные своего репозитория не подписываются, свежие — «fresh»; вход во фронтир"),

    ("full_panel_in_the_page_language", "",
     r"""(() => { bench.cache.set("x/aa", DATA()); const h = bench.panelHtml("x/aa");
        localStorage.setItem("llamacppAdminLang", "ru"); const ru = bench.panelHtml("x/aa"); localStorage.clear();
        bench.cache.set("x/none", null);
        return [h.includes(">Summary ratings<"), h.includes("Сводные рейтинги"), h.includes(">Math and reasoning<"), h.includes(">Будущая группа<"), h.includes(">Code<"),
                h.includes("Artificial Analysis quality index: independent runs on 10+ benchmarks"), h.includes("Индекс качества"), h.includes("Новый бенчмарк без перевода"),
                h.includes(">8.3/10<"), h.includes(">55 %<"), h.includes('<a href="https://artificialanalysis.ai/leaderboards/models" target="_blank" rel="noopener">AA Intelligence</a>'),
                h.includes("hfp-bench-row is-elo"), ru.includes(">Сводные рейтинги<"), bench.panelHtml("x/none"), h.startsWith('<div class="hfp-bench-panel" data-t="hf-bench-panel">')]; })()""",
     '[true,false,true,true,false,true,false,true,true,true,true,true,true,"<div class=\\"hfp-bench-panel\\" data-t=\\"hf-bench-panel\\"><div class=\\"hfp-muted\\">No benchmark data</div></div>",true]',
     "полная панель: группы и описания на языке страницы по ключу (серверный русский не показан), незнакомые — текстом сервера; пустая группа не рисуется; MT-Bench /10, проценты, ссылка, Elo золотой; по-русски — русские подписи; нет данных — «нет данных»; хук панели в обоих случаях"),

    ("frontier_panel_places_the_repository", "",
     r"""await (async () => { const empty = bench.frontierHtml(null); answers["/api/hf/reference-models"] = FRONTIER(); await bench.loadFrontier();
        bench.cache.set("x/model-GGUF", DATA()); const h = bench.frontierHtml("x/model-GGUF"); const plain = bench.frontierHtml(null);
        const names = [...h.matchAll(/hfp-front-name">([^<]*)</g)].map((m) => m[1]);
        bench.frontier.source = "aa";
        return [empty.includes("Loading data from Artificial Analysis…"), names, h.includes("hfp-front-row is-own"), plain.includes("is-own"),
                h.includes("built-in snapshot, ~June 2026"), bench.frontierHtml(null).includes("built-in snapshot"), h.includes('data-t="hf-frontier-refresh"')]; })()""",
     '[true,["Claude Fable 5","GPT-5.4","Gemini 2.5 Flash","Llama 4 Maverick","Mistral Large 2","model-GGUF","Llama 4 Scout"],true,false,true,false,true]',
     "панель фронтира: пока грузится — «загружаю»; модель репозитория встаёт на своё место в рейтинге; без репозитория — только фронтир; пометка «встроенный снимок» — только для встроенного списка; обновление"),
]


if __name__ == "__main__":
    sys.exit(run("js hf-bench", ".probe_js_hf_bench.tmp.mjs", PREAMBLE, PINS))
