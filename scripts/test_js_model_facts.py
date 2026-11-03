#!/usr/bin/env python3
"""Value snapshot: what a model on /models does and how long a context it takes (static/js/model-facts.js, 1.3.637).

The owner, 2026-10-25: "on /models I want to see at once what context a model supports and what it is for". The page reads both,
never guesses them: a GGUF's job and trained window from its own header through the cell editor's rows, a checkpoint folder's
from its config.json through the page's listing, the job by the picker's rule (model-jobs.js). Each claim with its negative:
  * the facts of a GGUF: chat, embedding and speech models told apart; the window its header states, none when it states none;
    a projector or a draft is no model; the editor's rows missing — nothing known, not "no job";
  * the facts of a folder: its job by its architecture, its window by its config; a whisper cache recognizes speech and has
    no window in tokens; a folder the rows already know is not read twice;
  * a branch: the jobs of its models in the vocabulary's order, one window or a range, "not known" only for a model that
    takes a window in tokens and states none, a dash for a job with no such window, nothing for a row with no model;
  * the side column: a job or a window chosen keeps only the models that pass; a group with nothing to keep is not offered
    unless it is the one chosen.

Run: python3 scripts/test_js_model_facts.py
"""
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _node import find_node, node_search_paths, probe_args  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


PROBE = r'''
import "./_js_globals.mjs";
const { ModelFacts } = await import("../static/js/model-facts.js");
const out = {};
const ROWS = { ok: true, models: [
  { path: "Hermes/a/Q4/hermes.gguf", kind: "model", detectedFamily: "hermes4", ggufMeta: { contextLength: 131072, architecture: "llama" } },
  { path: "Emb/a/Q8/emb.gguf", kind: "model", detectedFamily: "embedding", ggufMeta: { contextLength: 32768 } },
  { path: "Giga/a/Q8/giga.gguf", kind: "model", detectedFamily: "asr", ggufMeta: { sttVariant: "gigaam-v3" } },
  { path: "Coder/a/Q4/coder-00001-of-00002.gguf", kind: "model", detectedFamily: "qwen3", ggufMeta: { contextLength: 262144 } },
  { path: "Coder/a/Q4/coder-00002-of-00002.gguf", kind: "model", detectedFamily: "qwen3", ggufMeta: {} },
  { path: "Coder/a/Q5/coder-q5.gguf", kind: "model", detectedFamily: "qwen3", ggufMeta: { contextLength: 1048576 } },
  { path: "Lone/a/Q4/lone-00002-of-00003.gguf", kind: "model", detectedFamily: "llama", ggufMeta: { contextLength: 0, architecture: "" } },
  { path: "Hermes/a/Q4/mmproj-hermes.gguf", kind: "mmproj" },
  { path: "Hermes/a/Q4/mtp-hermes.gguf", kind: "draft", ggufMeta: { contextLength: 4096 } },
  { path: "Odd/a/Q4/odd.gguf", kind: "model", detectedFamily: "llama", ggufMeta: { contextLength: "nope" } },
  { path: "Zero/a/Q4/zero.gguf", kind: "model", detectedFamily: "llama", ggufMeta: { contextLength: 0 } },
] };
const FILES = [
  { path: "Qwen3-TTS-12Hz-1.7B-Base", kind: "safetensors", arch: "qwen3_tts" },
  { path: "seamless-m4t-v2-large", kind: "safetensors", arch: "seamless_m4t_v2" },
  { path: "Qwen3-0.6B", kind: "safetensors", arch: "qwen3", contextLength: 40960 },
  { path: "Mystery-ST", kind: "safetensors" },
  { path: "whisper/models--Systran--faster-whisper-large-v3", kind: "whisper" },
  { path: "translate/models--facebook--nllb-200-distilled-600M", kind: "translate", arch: "m2m_100", contextLength: 1024 },
  { path: "translate/models--facebook--nllb-200-3.3B", kind: "translate" },
  { path: "Hermes/a/Q4/hermes.gguf", kind: "safetensors", arch: "qwen3_tts", contextLength: 5 },
  { path: "loose.bin" },
];
const facts = ModelFacts.of(ROWS, FILES);
const f = (p) => facts.of(p);
out.gguf = ["Hermes/a/Q4/hermes.gguf", "Emb/a/Q8/emb.gguf", "Giga/a/Q8/giga.gguf", "Coder/a/Q4/coder-00002-of-00002.gguf", "Odd/a/Q4/odd.gguf", "Zero/a/Q4/zero.gguf"].map(f);
out.notModels = ["Hermes/a/Q4/mmproj-hermes.gguf", "Hermes/a/Q4/mtp-hermes.gguf", "loose.bin", "nowhere.gguf", "Lone/a/Q4/lone-00002-of-00003.gguf"].map(f);
out.partIsFirst = f("Coder/a/Q4/coder-00002-of-00002.gguf") === f("Coder/a/Q4/coder-00001-of-00002.gguf");
out.folders = ["Qwen3-TTS-12Hz-1.7B-Base", "seamless-m4t-v2-large", "Qwen3-0.6B", "Mystery-ST", "whisper/models--Systran--faster-whisper-large-v3",
               "translate/models--facebook--nllb-200-distilled-600M", "translate/models--facebook--nllb-200-3.3B"].map(f);
// The page's own listing names a GGUF by its path and no kind: without the editor's rows nothing is known of it.
const LISTING = FILES.filter((x) => !x.path.endsWith(".gguf")).concat([{ path: "Hermes/a/Q4/hermes.gguf" }]);
out.noRows = ModelFacts.of(null, LISTING).of("Hermes/a/Q4/hermes.gguf");
out.noRowsFolder = ModelFacts.of(null, LISTING).of("Qwen3-0.6B");

const plain = (b) => ({ jobs: [...b.jobs], lo: b.lo === Infinity ? null : b.lo, hi: b.hi, unnamed: b.unnamed, models: b.models });
const branch = (paths) => paths.reduce((b, p) => facts.take(b, p), ModelFacts.blank());
out.branch = {
  coder: plain(branch(["Coder/a/Q4/coder-00001-of-00002.gguf", "Coder/a/Q4/coder-00002-of-00002.gguf", "Coder/a/Q5/coder-q5.gguf"])),
  mixed: plain(branch(["Giga/a/Q8/giga.gguf", "Emb/a/Q8/emb.gguf", "Hermes/a/Q4/hermes.gguf", "Hermes/a/Q4/mmproj-hermes.gguf"])),
  speech: plain(branch(["Giga/a/Q8/giga.gguf", "whisper/models--Systran--faster-whisper-large-v3"])),
  odd: plain(branch(["Odd/a/Q4/odd.gguf"])),
  empty: plain(branch(["Hermes/a/Q4/mmproj-hermes.gguf", "loose.bin"])),
};
const state = (html) => (/data-t-state="([^"]*)"/.exec(html) || [])[1] || "";
const text = (html) => html.replace(/<[^>]*>/g, "").trim();
const w = (paths) => { const h = facts.windowHtml(branch(paths), "id"); return [state(h), text(h), h.includes(' title="')]; };
out.window = {
  one: w(["Hermes/a/Q4/hermes.gguf"]),
  range: w(["Coder/a/Q4/coder-00001-of-00002.gguf", "Coder/a/Q5/coder-q5.gguf"]),
  unknown: w(["Odd/a/Q4/odd.gguf"]),
  dash: w(["whisper/models--Systran--faster-whisper-large-v3"]),
  nothing: w(["Hermes/a/Q4/mmproj-hermes.gguf"]),
  hook: facts.windowHtml(branch(["Hermes/a/Q4/hermes.gguf"]), "Hermes/a").includes('data-t="models-row-window" data-t-id="Hermes/a"'),
};
const chips = (html) => [...html.matchAll(/data-job="([^"]*)">([^<]*)</g)].map((m) => [m[1], m[2].trim()]);
out.jobs = {
  order: chips(facts.jobsHtml(branch(["Qwen3-TTS-12Hz-1.7B-Base", "Giga/a/Q8/giga.gguf", "Emb/a/Q8/emb.gguf", "Hermes/a/Q4/hermes.gguf"]), "x")),
  none: chips(facts.jobsHtml(branch(["loose.bin"]), "x")),
  hook: facts.jobsHtml(branch(["Hermes/a/Q4/hermes.gguf"]), "Hermes").includes('data-t="models-row-jobs" data-t-id="Hermes"'),
};
const keep = (p, v) => facts.keeps(p, v);
out.keeps = {
  llm: ["Hermes/a/Q4/hermes.gguf", "Emb/a/Q8/emb.gguf", "Qwen3-0.6B", "Mystery-ST", "loose.bin"].map((p) => keep(p, { job: "llm" })),
  long: ["Hermes/a/Q4/hermes.gguf", "Coder/a/Q4/coder-00001-of-00002.gguf", "Coder/a/Q5/coder-q5.gguf", "Odd/a/Q4/odd.gguf", "loose.bin"].map((p) => keep(p, { window: 262144 })),
  both: [keep("Coder/a/Q5/coder-q5.gguf", { job: "llm", window: 1048576 }), keep("Emb/a/Q8/emb.gguf", { job: "embed", window: 131072 })],
  any: ["loose.bin", "Hermes/a/Q4/mmproj-hermes.gguf"].map((p) => keep(p, {})),
};
// The files of a place, each once (the folder rows that stand for a GGUF above are a fixture of the "rows win" check).
const listed = [...new Map(FILES.concat(ROWS.models.map((r) => ({ path: r.path }))).map((x) => [x.path, x])).values()];
const buttons = (html, attr) => [...html.matchAll(new RegExp(`data-${attr}="([^"]*)"[^>]*aria-pressed="(true|false)"><span aria-hidden="true">[^<]*</span><span>([^<]*)</span><span class="c">(\\d+)</span>`, "g"))]
  .map((m) => [m[1], m[2] === "true", m[3], Number(m[4])]);
out.nav = {
  jobs: buttons(facts.jobsNavHtml(listed, ""), "mdl-job"),
  jobsChosen: buttons(facts.jobsNavHtml(listed.filter((x) => x.path === "loose.bin"), "robot-policy"), "mdl-job"),
  windows: buttons(facts.windowsNavHtml(listed, 262144), "mdl-window"),
  hooks: facts.jobsNavHtml(listed, "").includes('data-t="models-job-filter" data-t-id="llm"')
    && facts.windowsNavHtml(listed, 0).includes('data-t="models-window-filter" data-t-id="131072"'),
};
console.log(JSON.stringify(out));
'''


def main():
    node = find_node()
    if node is None:
        print("js model-facts: SKIPPED — node не найден ни в PATH, ни у менеджеров версий: " + ", ".join(node_search_paths()))
        return 0
    probe = ROOT / "scripts" / ".probe_model_facts.tmp.mjs"
    probe.write_text(PROBE, encoding="utf-8")
    try:
        env = {**os.environ, "JS_ROOT": str(ROOT / "static" / "js"), "JS_STUBS": "form", "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8", "TZ": "UTC"}
        proc = subprocess.run(probe_args(node, ROOT / "scripts" / "_js_harness.mjs", probe), capture_output=True, text=True, cwd=ROOT,
                              env=env, timeout=90)
    finally:
        probe.unlink(missing_ok=True)
    if proc.returncode != 0:
        print("js model-facts: FAILED — харнесс не отработал")
        print(proc.stderr.strip()[:2000])
        return 1
    got = json.loads(proc.stdout.strip().splitlines()[-1])

    print("модели GGUF — по заголовку и правилу выбора:")
    g = got["gguf"]
    check(g[0] == {"jobs": ["llm"], "window": 131072}, "чат: LLM, окно из заголовка")
    check(g[1] == {"jobs": ["embed"], "window": 32768}, "модель векторов — своей работой (detectedFamily embedding), окно её заголовка")
    check(g[2] == {"jobs": ["asr"], "window": None}, "распознаватель по stt.* — речь → текст; окна в токенах заголовок не называет")
    check(g[3] == {"jobs": ["llm"], "window": 262144} and got["partIsFirst"],
          "вторая часть разбитого файла говорит то же, что первая: её заголовок не называет ничего (на живой странице — «LLM · не известно»)")
    check(g[4] == {"jobs": ["llm"], "window": None} and g[5] == {"jobs": ["llm"], "window": None},
          "negative: заголовок с не-числом и с нулём — окна нет (null), а не 0 и не выдуманное")
    check(got["notModels"] == [None, None, None, None, None],
          "negative: проектор, черновик, посторонний файл, путь, которого нет, и часть без своей первой части — не модели: фактов нет вовсе")
    check(got["noRows"] is None and got["noRowsFolder"] == {"jobs": ["llm"], "window": 40960},
          "negative: строки редактора не пришли — про GGUF не известно ничего; папки страница знает по своему списку")

    print("папки — по config.json и виду:")
    fo = got["folders"]
    check(fo[0] == {"jobs": ["tts"], "window": None}, "Qwen3-TTS — по архитектуре текст → речь; окна конфиг не назвал")
    check(fo[1] == {"jobs": ["speech-translate"], "window": None}, "SeamlessM4T — речь → перевод")
    check(fo[2] == {"jobs": ["llm"], "window": 40960}, "чат-папка с окном из config.json")
    check(fo[3] == {"jobs": ["llm"], "window": None}, "папка без архитектуры — по правилу выбора чат для vLLM, окна нет")
    check(fo[4] == {"jobs": ["asr"], "window": None}, "кэш whisper — речь → текст, окна в токенах у него нет")
    check(fo[5] == {"jobs": ["translate"], "window": 1024},
          "defect-history (2026-10-26): кэш переводчика целиком — перевод, окно из config.json снимка main (снимок с одним "
          "model.safetensors читался «LLM · не известно»)")
    check(fo[6] == {"jobs": ["translate"], "window": None},
          "negative: кэш переводчика без окна в списке — перевод, окно не известно (null), а не 0 и не выдумано")
    check(g[0]["window"] == 131072, "negative: GGUF, который знают строки редактора, по списку страницы не перечитывается")

    print("ветка дерева:")
    br = got["branch"]
    check(br["coder"] == {"jobs": ["llm"], "lo": 262144, "hi": 1048576, "unnamed": False, "models": 3},
          "окна разных файлов — диапазон; вторая часть — окном первой, «не названо» ветка не получает")
    check(sorted(br["mixed"].pop("jobs")) == ["asr", "embed", "llm"] and br["mixed"] == {"lo": 32768, "hi": 131072, "unnamed": False, "models": 3},
          "работы всех моделей ветки (порядок словаря — у ячейки, ниже); проектор не модель и в счёт не идёт")
    check(br["speech"] == {"jobs": ["asr"], "lo": None, "hi": 0, "unnamed": False, "models": 2},
          "negative: у речи окна в токенах нет — «не названо» не ставится")
    check(br["odd"]["unnamed"] is True and br["empty"]["models"] == 0, "LLM без окна — «не названо»; ветка без моделей — пустая")

    print("ячейка «Контекст до»:")
    w = got["window"]
    check(w["one"] == ["known", "131,072", True] and w["range"] == ["known", "262,144 – 1,048,576", True],
          "одно окно и диапазон — числом, с подсказкой, откуда оно")
    check(w["unknown"] == ["unknown", "not known", True], "модель с окном в токенах, которого никто не назвал, — «не известен» (не пусто и не 0)")
    check(w["dash"] == ["none", "—", True], "у работы без окна в токенах — прочерк с объяснением")
    check(w["nothing"] == ["none", "", False], "negative: строка без модели (проектор) — ничего")
    check(w["hook"], "ячейка несёт хук models-row-window с путём ветки")

    print("ячейка «Для чего»:")
    j = got["jobs"]
    check(j["order"] == [["llm", "💬 LLM"], ["embed", "🧬 text → vectors"], ["asr", "🎧 speech → text"], ["tts", "🔊 text → speech"]],
          "работы ветки — знаком и словом словаря, в его порядке")
    check(j["none"] == [] and j["hook"], "negative: без моделей — без работ; хук models-row-jobs с путём")

    print("фильтры боковой колонки:")
    k = got["keeps"]
    check(k["llm"] == [True, False, True, True, False], "работа: оставляет только модели этой работы; не-модель не проходит")
    check(k["long"] == [False, True, True, False, False], "окно «от 262 144»: короче, не названное и не-модель отпадают")
    check(k["both"] == [True, False] and k["any"] == [True, True], "оба условия сразу; без выбора проходит всё")
    nav = got["nav"]
    check(nav["jobs"] == [["llm", False, "LLM", 8], ["embed", False, "text → vectors", 1], ["asr", False, "speech → text", 2],
                          ["tts", False, "text → speech", 1], ["translate", False, "translation", 2],
                          ["speech-translate", False, "speech → translation", 1]],
          "работы со счётом моделей, в порядке словаря; работ без моделей в списке нет")
    check(nav["jobsChosen"] == [["robot-policy", True, "images → robot actions", 0]],
          "negative: выбранная работа, которой здесь нет, остаётся видна с нулём — её можно снять")
    check(nav["windows"] == [["131072", False, "from 131,072", 4], ["262144", True, "from 262,144", 3], ["1048576", False, "from 1,048,576", 1]],
          "окна «от …» со счётом, выбранное нажато")
    check(nav["hooks"], "кнопки несут хуки models-job-filter и models-window-filter")

    print()
    if _fail:
        print(f"js model-facts FAILED ({len(_fail)}):")
        for msg in _fail:
            print("  - " + msg)
        return 1
    print("js model-facts OK: работа и окно моделей на /models — значениями")
    return 0


if __name__ == "__main__":
    sys.exit(main())
