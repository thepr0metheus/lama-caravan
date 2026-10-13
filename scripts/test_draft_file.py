#!/usr/bin/env python3
"""Value snapshot: which speculative type a draft file is for.

The rule lives twice — caravan/common/draft_file.py and static/js/draft-file.js
— because the cell editor names a draft's type in the browser and the command
builder names it on the server. Both copies are run here against ONE table of
cases, and so are the rule's readers on the server: the model scanner, which
tells a draft from a model by it, and the builder, which launches a cell whose
type is left empty with it.

What's pinned. A sidecar by the FIRST word of its name, without case, after a
hyphen, an underscore or a dot; a file in a model's `mtp/` folder is an MTP head
(the defect: the scanner offered it as the model's draft and the type rule named
it draft-simple, which llama.cpp runs as a model of its own on token batches
without the hidden state an MTP head drafts from); a prefix in the name outranks
the folder; a word further along the name, a folder that is not exactly `mtp`
and a model that merely says MTP are no sidecars; no path is no sidecar — "" said
out loud, and draft-simple only as the type to launch with. The scanner files
exactly the sidecars as drafts. The builder reads the type off the file the
CONFIG names, not the path it emits: a scout's cell is emitted with the
`{{SPEC_PATH}}` placeholder, and until 2026-10-11 every such cell with an empty
type ran its draft as draft-simple. In the browser, the type a cell's draft gets
when a model is picked or speculation is switched on (`DraftFile.cellType`): the
file's own, never the family's over a sidecar.

Run: python3 scripts/test_draft_file.py
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _node import find_node  # noqa: E402
from caravan.admin.config_builder import LLAMA_PATH_PLACEHOLDER_SPEC, build_llama_args, build_remote_llama_args  # noqa: E402
from caravan.admin.models import _gguf_kind  # noqa: E402
from caravan.common.draft_file import DraftFile  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


# (path, sidecar type, launch type, what the pin is for)
CASES = [
    ("m/dflash-qwen.gguf", "draft-dflash", "draft-dflash", "positive: dflash- в начале имени — DFlash"),
    ("DSPARK_x.gguf", "draft-dspark", "draft-dspark", "positive: регистр не важен, после слова подчёркивание"),
    ("eagle3.head.gguf", "draft-eagle3", "draft-eagle3", "positive: после слова точка"),
    ("g/unsloth/default/mtp-gemma-4-31B-it-Q8_0.gguf", "draft-mtp", "draft-mtp",
     "positive: mtp- в начале имени — голова MTP, как называет upstream"),
    ("gemma-4-31b-it/mtp/gemma-4-31B-it-MTP-Q8_0.gguf", "draft-mtp", "draft-mtp",
     "positive (дефект): файл в папке mtp/ модели — голова MTP; сканер предлагал его черновиком, а тип был draft-simple"),
    ("Gemma/MTP/head.gguf", "draft-mtp", "draft-mtp", "positive: папка MTP без учёта регистра"),
    ("/models/gemma/mtp/head.gguf", "draft-mtp", "draft-mtp", "positive: абсолютный путь — та же папка"),
    ("gemma-4-31b-it/mtp/dflash-x.gguf", "draft-dflash", "draft-dflash",
     "boundary: слово в имени важнее папки"),
    ("my-dflash-lookalike.gguf", "", "draft-simple", "negative: слово дальше по имени — не sidecar"),
    ("mtpx-head.gguf", "", "draft-simple", "negative: mtpx — не mtp"),
    ("a/mtp-heads/x.gguf", "", "draft-simple", "negative: папка не ровно mtp"),
    ("Qwen3.6-27B-MTP-GGUF/unsloth/Q4_K_M/Qwen3.6-27B-MTP-Q4_K_M.gguf", "", "draft-simple",
     "negative: модель, которая лишь говорит MTP в имени, — модель (MTP у неё внутри)"),
    ("plain.gguf", "", "draft-simple", "negative: обычный файл — вторая модель, draft-simple"),
    ("", "", "draft-simple", "absence: нет пути — sidecar нет (пусто сказано), запуск draft-simple"),
]

# (draft, family type, cell type, what the pin is for) — the browser's DraftFile.cellType
CELL_TYPES = [
    ("gemma-4-31b-it/mtp/head.gguf", "draft-mtp", "draft-mtp", "черновик из папки mtp/ — draft-mtp"),
    ("m/dflash-x.gguf", "draft-mtp", "draft-dflash",
     "negative: тип семейства не пишется поверх DFlash: такая голова стартует как MTP и ничего не предлагает"),
    ("m/plain.gguf", "draft-mtp", "draft-simple", "negative: обычный черновик — draft-simple, не тип семейства"),
    ("", "draft-eagle3", "draft-eagle3", "без файла — тип семейства (MTP внутри модели)"),
    ("", "", "draft-mtp", "без файла и без типа семейства — draft-mtp"),
    ("", None, "draft-mtp", "absence: семейство не сказало ничего — тоже draft-mtp"),
]


def section_python():
    print("правило на сервере:")
    for path, sidecar, launch, why in CASES:
        got = (DraftFile(path).sidecar_type, DraftFile(path).launch_type)
        check(got == (sidecar, launch), f"py: {why} ({path!r} → {got})")
    check(DraftFile(None).sidecar_type == "" and DraftFile(None).launch_type == "draft-simple",
          "absence: None — как пустой путь")


def section_scanner():
    print("сканер моделей — читает то же правило:")
    for path, sidecar, _launch, why in CASES:
        if not path:
            continue
        want = "draft" if sidecar else "model"
        got = _gguf_kind(path)
        check(got == want, f"сканер: {path!r} → {got} (ждали {want}) — {why}")
    check(_gguf_kind("g/q4/mmproj-F16.gguf") == "mmproj" and _gguf_kind("vocabs/ggml-vocab-llama.gguf") is None,
          "negative: проектор остаётся проектором, словарь — не модель")


def section_builder():
    print("сборщик команды — тип из файла, который назван в конфиге:")

    def spec(args):
        if "--spec-type" not in args:
            return None
        i = args.index("--spec-type")
        return args[i + 1], (args[i + 3] if args[i + 2:i + 3] == ["--model-draft"] else None)

    base = {"MODEL_FILE": "m/model.gguf", "SPEC_TYPE": ""}
    for path, _sidecar, launch, why in CASES:
        if not path:
            continue
        got = spec(build_remote_llama_args({**base, "SPEC_DRAFT_MODEL_FILE": path}))
        check(got == (launch, LLAMA_PATH_PLACEHOLDER_SPEC),
              f"ячейка скаута с пустым типом: {path!r} → {got} — {why}")
    # The emitted path says dflash, the config says the mtp/ folder: the type
    # follows the config. Read off the emitted path, it would say dflash here and
    # draft-simple for every placeholder.
    got = spec(build_llama_args({**base, "SPEC_DRAFT_MODEL_FILE": "g/mtp/head.gguf"},
                                model_path="/abs/m.gguf", spec_path="/abs/lib/dflash-other.gguf"))
    check(got == ("draft-mtp", "/abs/lib/dflash-other.gguf"),
          f"тип — по файлу из конфига, а не по пути в команде (got {got})")
    got = spec(build_remote_llama_args({**base, "SPEC_TYPE": "draft-eagle3", "SPEC_DRAFT_MODEL_FILE": "g/mtp/head.gguf"}))
    check(got == ("draft-eagle3", LLAMA_PATH_PLACEHOLDER_SPEC),
          f"negative: тип, заданный оператором, не угадывается заново (got {got})")
    got = spec(build_remote_llama_args({**base, "SPEC_TYPE": "MTP", "SPEC_DRAFT_MODEL_FILE": "m/plain.gguf"}))
    check(got == ("draft-mtp", LLAMA_PATH_PLACEHOLDER_SPEC), f"старое имя mtp — это draft-mtp (got {got})")
    check(spec(build_remote_llama_args({**base, "SPEC_DRAFT_MODEL_FILE": "g/mtp/head.gguf", "ENABLE_EMBEDDINGS": "1"})) is None,
          "negative: у ячейки эмбеддингов спекуляции нет и с файлом черновика")
    check(spec(build_remote_llama_args(base)) is None, "absence: нет файла и нет типа — нет --spec-type")


def section_js():
    print("двойник в браузере — та же таблица:")
    node = find_node()
    if not node:
        check(False, "node не найден — двойник не проверен")
        return
    probe = (
        'import { pathToFileURL } from "node:url";\n'
        'const { DraftFile } = await import(pathToFileURL(process.env.JS_FILE).href);\n'
        f"const paths = {json.dumps([c[0] for c in CASES])};\n"
        f"const cells = {json.dumps([[d, f] for d, f, _w, _m in CELL_TYPES])};\n"
        "const out = {\n"
        "  types: paths.map((p) => [new DraftFile(p).sidecarType, new DraftFile(p).launchType]),\n"
        "  cells: cells.map(([d, f]) => DraftFile.cellType(d, f === null ? undefined : f)),\n"
        "  absent: [new DraftFile(undefined).sidecarType, new DraftFile(null).launchType],\n"
        "};\n"
        "console.log(JSON.stringify(out));\n"
    )
    env = {**os.environ, "JS_FILE": str(ROOT / "static" / "js" / "draft-file.js")}
    run = subprocess.run([node, "--input-type=module", "-e", probe], capture_output=True, text=True,
                         env=env, timeout=60)
    if run.returncode != 0:
        check(False, f"node вышел с кодом {run.returncode}: {run.stderr.strip()[-300:]}")
        return
    js = json.loads(run.stdout.strip().splitlines()[-1])
    for (path, sidecar, launch, why), got in zip(CASES, js["types"]):
        check(got == [sidecar, launch], f"js: {why} ({path!r} → {got})")
    for (draft, family, want, why), got in zip(CELL_TYPES, js["cells"]):
        check(got == want, f"js cellType: {why} ({draft!r}, {family!r} → {got})")
    check(js["absent"] == ["", "draft-simple"], f"js absence: undefined и null — как пустой путь (got {js['absent']})")
    check(len(js["types"]) == len(CASES) and len(js["cells"]) == len(CELL_TYPES),
          "двойник ответил на каждый случай таблицы")


def main():
    section_python()
    section_scanner()
    section_builder()
    section_js()
    if _fail:
        print(f"\ndraft file FAILED: {len(_fail)}")
        return 1
    print(f"\ndraft file OK: {len(CASES)} путей одной таблицей в обоих двойниках, сканер и сборщик по тому же правилу, "
          f"{len(CELL_TYPES)} случаев типа ячейки в браузере")
    return 0


if __name__ == "__main__":
    sys.exit(main())
