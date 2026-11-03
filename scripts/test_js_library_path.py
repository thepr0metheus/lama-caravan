#!/usr/bin/env python3
"""Value snapshot: where a model of the library is shown in the caravan's own pages (static/js/library-path.js, 1.3.660).

The owner, 2026-10-26, in a cell's window: "I want to see, where possible, a link to the model in our storage, and to our page on
HF". The library lays a download out as <model>/<author>/<quant>/<file>, as /hf names the folders; the models page (/models) is
asked for the quant's folder, and /hf for the repository the first two folders name. The models page's 🤗 on its branches asks
the same rule (LibraryPath.hfQuery), so the two pages cannot name one repository two ways.

Pinned by value, each claim with its negative:
  * a GGUF laid out as /hf lays it: the models page on its quant's folder (every file of it — a GGUF of several parts too), /hf on
    `<author>/<model>`; a model that is a folder (vLLM's safetensors) the same;
  * a path not laid out so: the models page on the path itself, no /hf; a path of the machine's own disk or one that climbs out
    (".."): nothing; no path: nothing;
  * the repository's parts as Hugging Face spells them: an author "default", a cache folder `models--…`, a name with a space —
    no /hf; the words go through encodeURIComponent;
  * hfQuery: a model's branch (no author given) is asked by its name, an author's branch by `<author>/<model>`; an empty author is
    no repository.

Run: python3 scripts/test_js_library_path.py
"""
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _contract import Contract  # noqa: E402
from _node import find_node, node_search_paths, probe_args  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


PROBE = r'''
import "./_js_globals.mjs";
const { LibraryPath } = await import("../static/js/library-path.js");
const of = (ref) => new LibraryPath(ref).links();
console.log(JSON.stringify({
  gguf: of("Hermes-4-70B-GGUF/lmstudio-community/Q4_K_M/Hermes-4-70B-Q4_K_M.gguf"),
  parts: of("Qwen3.8-Flash-Next-GGUF/unsloth/IQ4_XS/Qwen3.8-Flash-Next-UD-IQ4_XS-00001-of-00003.gguf"),
  folder: of("Qwen3-Omni-30B-A3B-Instruct-AWQ-4bit/cyankiwi/AWQ"),
  spaced: of("  gemma-4-12B-it-GGUF/bartowski/Q5_K_M/gemma-4-12B-it-Q5_K_M.gguf  "),
  two: of("whisper/ggml-large-v3-turbo.bin"), one: of("root.gguf"),
  home: of("/home/someone/llama-model-cache/Hermes-4-70B-GGUF/lmstudio-community/Q4_K_M/x.gguf"), climbs: of("../outside/a/b/c.gguf"),
  none: [of(""), of(null), of(undefined)],
  byDefault: of("gemma/default/Q4/g.gguf"), cache: of("models--facebook--nllb/snap/abc/x.gguf"), oddName: of("my model/Org/Q4/m.gguf"),
  model: JSON.parse(process.env.MODEL_CASES).map((ref) => new LibraryPath(ref).model()),
  listed: ["Hermes-4-70B-GGUF/lmstudio-community/Q4_K_M/x.gguf", "root.gguf", "/home/someone/a/b/x.gguf", "../up.gguf", ""].map((ref) => new LibraryPath(ref).listed()),
  quant: ["Hermes-4-70B-GGUF/lmstudio-community/Q4_K_M/Hermes-4-70B-Q4_K_M.gguf", "Qwen3-Omni-30B-A3B-Instruct-AWQ-4bit/cyankiwi/AWQ", "whisper/ggml-large-v3-turbo.bin", "root.gguf", "/home/someone/a/b/c/x.gguf", ""]
    .map((ref) => new LibraryPath(ref).quant()),
  query: [LibraryPath.hfQuery("qwen"), LibraryPath.hfQuery("qwen", "Qwen"), LibraryPath.hfQuery("qwen", ""), LibraryPath.hfQuery("(root)"),
          LibraryPath.hfQuery("·", null), LibraryPath.hfQuery("models--x"), LibraryPath.hfQuery("gemma", "default"), LibraryPath.hfQuery("gemma", undefined)],
}));
'''


#: (a path, the model it lies in): one table, for the browser's rule and the program's.
MODEL_CASES = [(row["path"], row["model"]) for row in Contract.table("library_model")["cases"]]


def main():
    node = find_node()
    if node is None:
        print("js library-path: SKIPPED — node не найден ни в PATH, ни у менеджеров версий: " + ", ".join(node_search_paths()))
        return 0
    probe = ROOT / "scripts" / ".probe_library_path.tmp.mjs"
    probe.write_text(PROBE, encoding="utf-8")
    try:
        env = {**os.environ, "JS_ROOT": str(ROOT / "static" / "js"), "JS_STUBS": "", "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8", "TZ": "UTC",
               "MODEL_CASES": json.dumps([case[0] for case in MODEL_CASES])}
        proc = subprocess.run(probe_args(node, ROOT / "scripts" / "_js_harness.mjs", probe), capture_output=True, text=True, cwd=ROOT,
                              env=env, timeout=90)
    finally:
        probe.unlink(missing_ok=True)
    if proc.returncode != 0:
        print("js library-path: FAILED — харнесс не отработал")
        print(proc.stderr.strip()[:2000])
        return 1
    got = json.loads(proc.stdout.strip().splitlines()[-1])

    print("папка модели — одна таблица на браузер и контроллер:")
    want = [case[1] for case in MODEL_CASES]
    check(got["model"] == want, f"LibraryPath.model читает путь по таблице (got {got['model']})")
    check(got["listed"] == ["Hermes-4-70B-GGUF", "root.gguf", "", "", ""], f"LibraryPath.listed: папка модели, файл в корне библиотеки, а чужой путь не называет ничего (got {got['listed']})")
    check(got["quant"] == ["Q4_K_M", "", "", "", "", ""], f"LibraryPath.quant: папка сборки только у пути вида модель/автор/сборка/файл (got {got['quant']})")

    print("модель библиотеки — на страницах каравана:")
    check(got["gguf"] == {"models": "/models?q=Hermes-4-70B-GGUF%2Flmstudio-community%2FQ4_K_M%2F",
                          "hf": "/hf?q=lmstudio-community%2FHermes-4-70B-GGUF"},
          "GGUF, разложенный, как раскладывает /hf: /models — на папку кванта, /hf — на репозиторий «автор/модель»")
    check(got["parts"]["models"] == "/models?q=Qwen3.8-Flash-Next-GGUF%2Funsloth%2FIQ4_XS%2F",
          "GGUF из нескольких частей: /models — на папку кванта, все части; negative: не на первую часть по имени файла")
    check(got["folder"] == {"models": "/models?q=Qwen3-Omni-30B-A3B-Instruct-AWQ-4bit%2Fcyankiwi%2FAWQ%2F",
                            "hf": "/hf?q=cyankiwi%2FQwen3-Omni-30B-A3B-Instruct-AWQ-4bit"},
          "модель-папка (safetensors vLLM) — так же: папка кванта и репозиторий")
    check(got["spaced"]["hf"] == "/hf?q=bartowski%2Fgemma-4-12B-it-GGUF", "пробелы вокруг пути — не часть имени")
    check(got["two"] == {"models": "/models?q=whisper%2Fggml-large-v3-turbo.bin", "hf": ""}
          and got["one"] == {"models": "/models?q=root.gguf", "hf": ""},
          "путь не по раскладке /hf — /models по самому пути; negative: репозиторий не угадывается")
    check(got["home"] == {"models": "", "hf": ""} and got["climbs"] == {"models": "", "hf": ""},
          "negative: путь диска машины и путь, выходящий из библиотеки («..»), — ссылок нет: папок страниц он не называет")
    check(got["none"] == [{"models": "", "hf": ""}] * 3, "negative: пути нет — ссылок нет, а не ссылка на пустой поиск")
    check(got["byDefault"]["hf"] == "" and got["cache"]["hf"] == "" and got["oddName"]["hf"] == ""
          and got["byDefault"]["models"] == "/models?q=gemma%2Fdefault%2FQ4%2F" and got["oddName"]["models"] == "/models?q=my%20model%2FOrg%2FQ4%2F",
          "автор default, кэш models--, имя с пробелом — не репозиторий Hugging Face: /hf нет; /models — есть, слова закодированы")
    check(got["query"] == ["qwen", "Qwen/qwen", "", "", "", "", "", "gemma"],
          "правило 🤗 страницы /models: ветка модели — по имени (и когда автор не передан), ветка автора — «автор/модель»; "
          "negative: пустой автор, (root), «·», кэш models--, автор default — ничего")
    print()
    if _fail:
        print(f"js library-path FAILED ({len(_fail)}):")
        for msg in _fail:
            print("  - " + msg)
        return 1
    print("js library-path OK: the models page and /hf are asked for a cell's model by its folders, and the 🤗 of the models page by the same rule")
    return 0


if __name__ == "__main__":
    sys.exit(main())
