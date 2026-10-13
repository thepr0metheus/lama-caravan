#!/usr/bin/env python3
"""Value snapshot: the Strata runner (1.3.512) — a button on the runner row, as llama.cpp has.

Strata runs Qwen3.8-Flash-Next (GSQ-RCO GGUF, two parts, 68 GB) on one card. It was a hand-typed
custom cell: the board drew a raw command line with a CPU chip, the scout fetched no model for
it, and its files lived outside the library (2026-10-13). Now it is a runner: the picker sorts
its file to it by the file's architecture, the command is built from its own fields, the scout
is told which files it reads (the first part and the draft layer), and it keeps them by the
cell's cache switch like every other cell: a scout starts an engine only from its own disk, so
the cache is what keeps the model from being written there at every start (2026-10-13).

Each claim has a positive and a negative pin.

Run: python3 scripts/test_strata_runner.py
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from caravan.admin import cell_assets  # noqa: E402
from caravan.admin import fleet_clients as fc  # noqa: E402
from caravan.admin.model_locator import Locations  # noqa: E402
from caravan.common.errors import AppError  # noqa: E402
from caravan.domain.runner import REGISTRY, get, registry_json  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def refusal(fn):
    try:
        fn()
    except AppError as exc:
        return exc.status, str(exc)
    return None


FIRST = "Qwen3.8-Flash-Next-GSQ-RCO-GGUF/ISTA-DASLab/IQ2_XS/Qwen3.8-Flash-Next-GSQ-RCO-IQ2_XS-00001-of-00002.gguf"
DRAFT = "Qwen3.8-Flash-Next-GSQ-RCO-GGUF/ISTA-DASLab/IQ2_XS/mtp-q2_0.gguf"
ROOTED = '"${LLAMA_MODELS_DIR:-$HOME/llama.cpp/models}"/'
STRATA = get("strata")


def section_the_registry():
    print("реестр:")
    ids = [r.id for r in REGISTRY]
    check(ids.index("strata") == ids.index("vllm") + 1,
          "кнопка Strata стоит в ряду Runner сразу за vLLM — среди движков чата, до речи")
    row = next(r for r in registry_json() if r["id"] == "strata")
    check((row["artifacts"], row["ggufArchs"], row["contextField"], row["sharedPicker"], row["tokenContext"],
           row["commandPath"], row["llamaConfig"])
          == (["strata-gguf"], ["qwen4exp"], "STRATA_CONTEXT", "source", True, True, False),
          "в браузер уходит: свой вид файла, архитектура qwen4exp, своё поле окна, модель из общего выбора, "
          "окно в токенах, путь командной ячейки, флаги llama.cpp ему не нужны")
    llama = next(r for r in registry_json() if r["id"] == "llama-server")
    check(llama["ggufArchs"] == [] and "strata-gguf" not in llama["artifacts"],
          "negative: llama.cpp архитектуру Strata не берёт — b10357 не знает qwen4exp")
    vllm = next(r for r in registry_json() if r["id"] == "vllm")
    check(vllm["contextField"] == "MAX_MODEL_LEN" and llama["contextField"] == "CTX_SIZE",
          "окно у vLLM — MAX_MODEL_LEN, у llama.cpp — CTX_SIZE")
    check(row["vramPlan"] == {"takesFree": True, "floorMiB": 6144, "reserveField": "STRATA_VRAM_RESERVE_MIB"},
          "defect-history: в браузер уходит план VRAM — Strata берёт свободную память своей карты, и ей нужно 6 ГБ "
          "плюс резерв; форма считала её суммой llama.cpp и писала «37.2 GB, won't fit» на карте, где она работает "
          "(живая проверка 2026-10-13)")
    planned = [r["id"] for r in registry_json() if r["vramPlan"] is not None]
    check(planned == ["strata", "gr00t"],
          f"negative: план есть только у Strata (берёт свободное) и GR00T (замеренная цифра); остальным "
          f"цифру считает форма (получено {planned})")


def section_the_command():
    print("команда:")
    full = {"MODEL_FILE": FIRST, "SPEC_DRAFT_MODEL_FILE": DRAFT, "STRATA_CONTEXT": "65536", "STRATA_KV": "K8V4",
            "STRATA_DRAFT_VOCAB": "en", "STRATA_VRAM_RESERVE_MIB": "2048", "MODEL_NAME": "qwen3.8-flash-next"}
    check(STRATA.command(full)
          == (f'bash $HOME/run_strata.sh "$PORT" {ROOTED}{FIRST} --mtp {ROOTED}{DRAFT} --context 65536 --kv k8v4 '
              f'--draft-vocab en --vram-reserve-mib 2048 --name qwen3.8-flash-next'),
          "все поля — в строке run_strata.sh: первая часть и слой черновика под корнем моделей, окно, KV, "
          "словарь черновика, запас VRAM, имя")
    check(STRATA.command({"MODEL_FILE": FIRST})
          == f'bash $HOME/run_strata.sh "$PORT" {ROOTED}{FIRST} --context 131072 --kv int8 --draft-vocab cyrillic',
          "пустые поля — решения самой Strata: окно 131072, KV int8, кириллица; без черновика, запаса и имени")
    check("--name alias-x" in STRATA.command({"MODEL_FILE": FIRST, "ALIAS": "alias-x"})
          and "--name own" in STRATA.command({"MODEL_FILE": FIRST, "ALIAS": "alias-x", "MODEL_NAME": "own"}),
          "имя — MODEL_NAME, иначе ALIAS: то же, по которому модель зовут на входе машины")
    check("'/m/a b.gguf'" in STRATA.command({"MODEL_FILE": "/m/a b.gguf"}),
          "абсолютный путь берётся как есть, в кавычках оболочки")
    for field, value, text in (
            ("STRATA_KV", "fp8", "STRATA_KV must be one of int8, q4_0, k8v4, not 'fp8'"),
            ("STRATA_DRAFT_VOCAB", "de", "STRATA_DRAFT_VOCAB must be one of cyrillic, cjk, en, fr, not 'de'"),
            ("STRATA_CONTEXT", "128k", "STRATA_CONTEXT must be a number of tokens, not '128k'"),
            ("STRATA_VRAM_RESERVE_MIB", "2G", "STRATA_VRAM_RESERVE_MIB must be a number of MiB, not '2G'")):
        check(refusal(lambda: STRATA.command({"MODEL_FILE": FIRST, field: value})) == (400, text),
              f"negative: {field}={value!r} — отказ с именем поля, а не подмена значением по умолчанию")
    check(refusal(lambda: STRATA.command({})) == (400, "MODEL_FILE is required for a Strata cell"),
          "negative: без модели — отказ")
    check(refusal(lambda: STRATA.preflight_start({}, "")) == (400, "Strata cell has no model — configure it first")
          and STRATA.preflight_start({"MODEL_FILE": FIRST}) is None,
          "старт без модели отказан до скаута; с моделью — проходит")
    check(STRATA.artifact_label({"MODEL_FILE": FIRST}) == "Qwen3.8-Flash-Next-GSQ-RCO-IQ2_XS"
          and STRATA.artifact_label({}) == "Strata",
          "подпись ячейки — имя модели без номера части; без модели — «Strata»")


def section_the_files_a_scout_brings():
    print("файлы, которые приносит скаут:")
    check(STRATA.model_file_paths({"MODEL_FILE": FIRST, "SPEC_DRAFT_MODEL_FILE": DRAFT, "MMPROJ_FILE": "x.gguf"})
          == [FIRST, DRAFT],
          "Strata читает первую часть и слой черновика — mmproj, оставшийся от llama, не её файл")
    check(STRATA.model_file_paths({"MODEL_FILE": FIRST}) == [FIRST], "без черновика — одна модель")
    check(get("whisper").model_file_paths({"MODEL_FILE": "left.gguf"}) == []
          and get("transcribe").model_file_paths({"MODEL_FILE": "asr.gguf"}) == ["asr.gguf"],
          "negative: whisper не читает оставшийся MODEL_FILE; transcribe читает свой")


TMP = Path(tempfile.mkdtemp(prefix="caravan-strata-"))
MODELS = TMP / "models"
for rel in (FIRST, FIRST.replace("00001-of", "00002-of"), DRAFT):
    (MODELS / rel).parent.mkdir(parents=True, exist_ok=True)
    (MODELS / rel).write_bytes(b"GGUF")


def payload(cfg, scout_version="2.31.0", ask_cache=None):
    keep = fc.topology_store, fc.current_locations, fc.controller_models_dir
    fc.topology_store = lambda: {"hosts": {"box-a": {"id": "box-a", "scoutVersion": scout_version,
                                                     "gpus": [{"index": "0", "memoryTotalMiB": "32607"}]}}}
    fc.current_locations = lambda wait=False: Locations([])
    fc.controller_models_dir = lambda: MODELS
    body = {"hostId": "box-a", "port": 22009, "config": dict(cfg), "modelPath": cfg.get("MODEL_FILE", "")}
    if ask_cache is not None:
        body["cacheModels"] = ask_cache
    try:
        return fc.scout_start_payload(body)
    finally:
        fc.topology_store, fc.current_locations, fc.controller_models_dir = keep


def section_the_start():
    print("старт на скауте:")
    cfg = {"RUNNER": "strata", "MODEL_FILE": FIRST, "SPEC_DRAFT_MODEL_FILE": DRAFT, "PORT": "22009"}
    p = payload(cfg, ask_cache=True)
    check(p.get("modelFiles") == [FIRST, DRAFT] and p.get("cellKind") == "command",
          "скауту названы файлы ячейки (modelFiles): первая часть и слой черновика — вторую часть он берёт сам")
    check(p.get("cacheModels") is True and payload(cfg).get("cacheModels") is False,
          "кэш — как просит запрос (галочка формы): модель пишется на диск один раз; запрос молчит — кэша нет")
    check(p.get("vram") == {"device": 0, "reserveMiB": 6144, "who": "Strata", "why": "its smallest card is 6 GB",
                            "lower": "STRATA_VRAM_RESERVE_MIB"},
          "старт просит у карты 6 ГБ свободных: иначе отказ до загрузки 68 ГБ, а не после")
    check(set(p.get("inPlace") or {}) <= {FIRST, DRAFT},
          "подсказки «на месте» — только про файлы ячейки")
    line = p.get("shellLine") or ""
    check("LLAMA_MODELS_DIR=" not in line and line.count('"${LLAMA_MODELS_DIR:-$HOME/llama.cpp/models}"/') == 2,
          "строка запуска не задаёт папку моделей: обе части пути — под ${LLAMA_MODELS_DIR}, а его ставит скаут "
          "по месту, куда легла модель (его кэш); папка моделей NAS скауту не передаётся")
    whisper = payload({"RUNNER": "whisper", "MODEL_FILE": "left.gguf", "PORT": "22005"})
    check(whisper.get("modelFiles") == [],
          "negative: whisper — пустой список: оставшийся MODEL_FILE скаут больше не качает")
    llama = payload({"MODEL_FILE": "org/m.gguf", "PORT": "22001"}, ask_cache=True)
    check("modelFiles" not in llama and llama.get("cacheModels") is True,
          "llama-ячейка своих файлов не перечисляет (скаут читает их из конфига); кэш — как у всех, по запросу")
    old = refusal(lambda: payload(cfg, scout_version="2.30.0"))
    check(old == (400, "this scout (2.30.0) cannot start a strata cell — it needs caravan-scout 2.31.0: "
                       "update the scout"),
          "negative: скаут 2.30 не приносит вторую часть и черновик — отказ до старта с номером нужной версии")
    check(payload(cfg, scout_version="2.31.4").get("cellKind") == "command",
          "скаут новее 2.31 — старт идёт")
    check(payload(cfg, scout_version="").get("cellKind") == "command",
          "as-is: версия скаута неизвестна — старт идёт: скауты называют её с 2.0, и отказ без знания был бы догадкой")
    check(refusal(lambda: payload({**cfg, "STRATA_KV": "fp8"})) == (400, "STRATA_KV must be one of int8, q4_0, "
                                                                        "k8v4, not 'fp8'"),
          "negative: неверное поле отказывает при старте — ячейка не уходит на скаут с подменённым значением")


def section_reported_processes():
    print("процессы ячейки из отчёта скаута:")
    node = {"running": True, "port": 22009, "pid": 4343, "pids": [4345, True, "7", 1, 4346]}
    host = fc.host_from_report({"hostId": "box-a", "host": {"name": "box-a"}, "llamaNodes": [node]})
    check(host["llamaNodes"][0]["pids"] == [4345, 4346],
          "pids — только числа процессов: True, строки и pid 1 отброшены")
    many = fc.host_from_report({"hostId": "box-a", "host": {"name": "box-a"}, "llamaNodes": [{**node, "pids": list(range(2, 200))}]})
    old = fc.host_from_report({"hostId": "box-a", "host": {"name": "box-a"}, "llamaNodes": [{"running": True, "pid": 4343}]})
    check(len(many["llamaNodes"][0]["pids"]) == 64 and old["llamaNodes"][0]["pids"] == [],
          "boundary: не больше 64; negative: скаут старше 2.31 их не шлёт — пустой список")


def section_the_draft_note_is_seen():
    print("строка про слой черновика видна в окне ячейки:")
    import re
    html = (ROOT / "static/index.html").read_text(encoding="utf-8")
    css = (ROOT / "static/css/monitor.css").read_text(encoding="utf-8")
    tag = re.search(r'<(\w+)\b([^>]*\bid="tr-strataDraft"[^>]*)>', html)
    hides_p = re.search(r"\.topo-edit-form \.field p:not\(\.field-note\)\s*\{\s*display:\s*none;", css)
    shown = tag is not None and (tag.group(1) != "p" or "field-note" in tag.group(2))
    check(bool(hides_p) and shown,
          "defect-history: строка «Draft layer (MTP)» — не скрытый абзац: окно настройки прячет описания в поле "
          "(`p:not(.field-note)` в monitor.css), и в 1.3.512 строка была абзацем, заполнена, но не видна")


def section_cell_assets():
    print("файлы ячейки для скаута:")
    files = cell_assets.RUNNER_ASSETS.get("strata") or ()
    check(files == ("run_strata.sh", "strata_launch.py")
          and all(f in cell_assets.CELL_ASSETS and (ROOT / "cells" / f).is_file() for f in files),
          "скаут берёт у контроллера run_strata.sh и strata_launch.py — оба в белом списке и в cells/")


def main():
    section_the_registry()
    section_the_command()
    section_the_files_a_scout_brings()
    section_the_start()
    section_reported_processes()
    section_the_draft_note_is_seen()
    section_cell_assets()
    if _fail:
        print(f"\nFAILED ({len(_fail)}):")
        for msg in _fail:
            print("  -", msg)
        return 1
    print("\nstrata runner OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
