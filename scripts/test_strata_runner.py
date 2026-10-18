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


def section_ram_by_the_table():
    print("память по таблице Strata:")
    swift = "Swift-1.5-Qwen3.8-Flash-Next-GSQ-RCO-GGUF/ukisai/IQ3_S/Swift-Qwen3.8-Flash-Next-GSQ-RCO-IQ3_S-00001-of-00002.gguf"
    got = STRATA.ram_reservation({"MODEL_FILE": swift}, {"MODEL_FILE": 44900816736})
    check(got == {"reserveMiB": 51507 + 1024, "who": "Strata", "why": "its experts stay in memory: 50.3 GiB (Strata's table for this pack)",
                  "lower": "nothing — stop another cell"},
          "defect-history (2026-10-18): Swift 1.5's IQ3_S has 41.8 GiB in its first part and the rest of its 50.3 GiB of experts in the second; "
          "the start promised 42.8 GiB, the engine wanted 50, and systemd-oomd killed the cell four times — the promise is the table's 50.3 GiB plus a GiB")
    orig = "Qwen3.8-Flash-Next-GSQ-RCO-GGUF/ISTA-DASLab/IQ3_S/Qwen3.8-Flash-Next-GSQ-RCO-IQ3_S-00001-of-00002.gguf"
    got = STRATA.ram_reservation({"MODEL_FILE": orig}, {"MODEL_FILE": 51 * 2 ** 30 + 100 * 2 ** 20})
    check(got["reserveMiB"] == 51 * 1024 + 100 + 1024 and got["why"] == "its weights stay in memory: 51.1 GiB",
          "negative: ISTA-DASLab's own IQ3_S holds all its experts in its first part (51.1 GiB, more than the table's 50.3): the first part's size, as before")
    names = {"Q2_0": 34.0, "IQ2_XS": 35.5, "IQ3_XXS": 42.9, "IQ3_S": 50.3, "IQ1_M": 23.4}
    check({q: STRATA.arena_mib(f"Some-Name-{q}-00001-of-00002.gguf") for q in names} == {q: int(round(g * 1024)) for q, g in names.items()}
          and STRATA.arena_mib("Some-Name-iq3_s-00001-of-00002.gguf") == 51507 and STRATA.arena_mib("Some-Name-IQ3_S.gguf") == 51507,
          "the five packs of Strata's table are found by the quantization in the file's name — in capitals or not, a pack in parts or in one file")
    check(STRATA.arena_mib("Some-Name-IQ4_XS-00001-of-00003.gguf") == 0 and STRATA.arena_mib("IQ3_S-notes.txt") == 0 and STRATA.arena_mib("") == 0
          and STRATA.arena_mib(None) == 0 and STRATA.arena_mib("Qwen3.8-IQ3_S-extra-00001-of-00002.gguf") == 0,
          "negative: a quantization the table does not know, one that is not at the end of the name, no name — no experts named, never a guess")
    check(STRATA.ram_reservation({"MODEL_FILE": swift}, {})["reserveMiB"] == 51507 + 1024
          and STRATA.ram_reservation({"MODEL_FILE": swift}, {"MODEL_FILE": 0})["reserveMiB"] == 51507 + 1024,
          "boundary: no size (or a size of nothing) — the table still promises; the first part's size and the table are two sources, either is enough")


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
    check(planned == ["strata", "gr00t", "personaplex", "lfm-audio", "step-audio2", "qwen3-omni", "minicpm-omni"],
          f"negative: план есть только у Strata (берёт свободное), у GR00T и пяти голосовых раннеров (замеренные "
          f"цифры); остальным цифру считает форма (получено {planned})")


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
          and STRATA.preflight_start({"MODEL_FILE": FIRST, "SPEC_DRAFT_MODEL_FILE": DRAFT}) is None,
          "старт без модели отказан до скаута; с моделью и слоем черновика — проходит")
    check(STRATA.artifact_label({"MODEL_FILE": FIRST}) == "Qwen3.8-Flash-Next-GSQ-RCO-IQ2_XS"
          and STRATA.artifact_label({}) == "Strata",
          "подпись ячейки — имя модели без номера части; без модели — «Strata»")


def section_an_iq_pack_needs_its_draft_layer():
    print("пакет IQ без слоя черновика — отказ до копирования:")
    # The engine's own answer to a native (IQ) pack with no `--spec`: found on 2026-10-17 after the scout had copied the Coder's
    # IQ1_M (54 GiB) and the engine had loaded it. The refusal comes before the scout is sent anything.
    G = "Qwen3.8-Flash-Next-GSQ-RCO"
    pack = {
        "IQ1_M (the Coder's)": f"{G}-Coder-GGUF/ISTA-DASLab/IQ1_M/{G}-IQ1_M-00001-of-00002.gguf",
        "IQ2_XS": FIRST,
        "IQ3_XXS": f"{G}-GGUF/ISTA-DASLab/IQ3_XXS/{G}-IQ3_XXS-00001-of-00002.gguf",
        "IQ3_S": f"{G}-GGUF/ISTA-DASLab/IQ3_S/{G}-IQ3_S-00001-of-00002.gguf",
        "Swift's IQ3_XXS": "Swift-1.5-Qwen3.8-Flash-Next-GSQ-RCO-GGUF/ukisai/IQ3_XXS/Swift-Qwen3.8-Flash-Next-GSQ-RCO-IQ3_XXS-00001-of-00002.gguf",
        "Unsloth's UD-IQ4_XS": "Qwen3.8-Flash-Next-GGUF/unsloth/UD-IQ4_XS/Qwen3.8-Flash-Next-UD-IQ4_XS-00001-of-00003.gguf",
        "lower case": f"{G}-GGUF/x/IQ3_S/{G.lower()}-iq3_s-00001-of-00002.gguf",
        "one file, no parts": "Some-GGUF/x/IQ2_XS/Some-IQ2_XS.gguf",
    }
    for what, path in pack.items():
        name = path.rsplit("/", 1)[-1]
        want = (400, f"{name} is an IQ pack: Strata does not start it without a draft layer, and this cell names none. "
                     f"Open the cell's settings and pick the model again: the form fills in the draft layer "
                     f"(mtp-q2_0.gguf) from the library. If the library holds none, it has to be added first")
        check(refusal(lambda: STRATA.preflight_start({"MODEL_FILE": path})) == want
              and refusal(lambda: STRATA.preflight_start({"MODEL_FILE": path, "SPEC_DRAFT_MODEL_FILE": "  "})) == want,
              f"{what}: no draft layer (or a blank one) — refused, naming the file and the way out")
        check(STRATA.preflight_start({"MODEL_FILE": path, "SPEC_DRAFT_MODEL_FILE": DRAFT}) is None,
              f"{what}: with a draft layer it starts")
    check(refusal(lambda: STRATA.preflight_start({}, pack["IQ3_S"]))[0] == 400
          and STRATA.preflight_start({"MODEL_FILE": pack["IQ3_S"]}, FIRST.replace("IQ2_XS", "Q2_0")) is None,
          "the model the caller resolved (the slot's) is the one judged, not the MODEL_FILE left in the config: an IQ3_S in the "
          "config and a Q2_0 resolved starts, an IQ3_S resolved and nothing in the config does not")
    for what, path in {
            "Q2_0": f"{G}-GGUF/ISTA-DASLab/Q2_0/{G}-Q2_0-00001-of-00002.gguf",
            "UD-Q4_K_XL": "Qwen3.8-Flash-Next-GGUF/unsloth/UD-Q4_K_XL/Qwen3.8-Flash-Next-UD-Q4_K_XL-00001-of-00004.gguf",
            "a folder named IQ2_XS, a file that is not": f"{G}-GGUF/ISTA-DASLab/IQ2_XS/{G}-Q2_0-00001-of-00002.gguf",
            "IQ in the middle of the name": "Some-GGUF/x/q/Some-IQ2_XS-extra.gguf",
            "IQ with no quant after it": "Some-GGUF/x/q/Some-IQ-00001-of-00002.gguf",
            "not a .gguf at all": "Some-GGUF/x/q/Some-IQ2_XS.gguf.bak"}.items():
        check(STRATA.preflight_start({"MODEL_FILE": path}) is None,
              f"negative: {what} — not refused: nothing says the engine asks a draft layer of it, and a refusal from a guess is worse")
    # The refusal stands on the way a start takes (cell_ops.scout_start_body), the one the board's Start and "start with the
    # machine" both take — a method nobody calls would pin nothing.
    from caravan.admin import cell_ops
    slot = {"config": {"RUNNER": "strata", "MODEL_FILE": pack["IQ1_M (the Coder's)"], "PORT": "22009"}}
    got = refusal(lambda: cell_ops.scout_start_body("box-a", 22009, slot))
    check(got is not None and got[0] == 400 and "is an IQ pack" in got[1],
          "scout_start_body — the one function the board's Start and the switch that makes a cell start with the machine both call — "
          "refuses before any scout is asked")
    body = cell_ops.scout_start_body("box-a", 22009, {"config": {**slot["config"], "SPEC_DRAFT_MODEL_FILE": DRAFT}})
    check(body["modelPath"] == slot["config"]["MODEL_FILE"], "negative: the same cell with its draft layer — the start body is made")
    check(cell_ops.scout_start_body("box-a", 22009, slot, check=False)["modelPath"] == slot["config"]["MODEL_FILE"],
          "as-is: a stop (check=False) is never refused by the start's rule")


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


def payload(cfg, scout_version="2.31.0", ask_cache=None, libraries=(), models=None):
    keep = fc.topology_store, fc.current_locations, fc.controller_models_dir
    fc.topology_store = lambda: {"hosts": {"box-a": {"id": "box-a", "scoutVersion": scout_version,
                                                     "gpus": [{"index": "0", "memoryTotalMiB": "32607"}]}}}
    fc.current_locations = lambda wait=False: Locations(list(libraries))
    fc.controller_models_dir = lambda: models or MODELS
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
    # What it keeps in the machine's memory (scout 2.32, MemoryLedger): the first part of its weights, whole, and a GiB more.
    GIB = 2 ** 30
    library = [{"id": "lib", "name": "NAS", "state": "ok", "path": "/mnt/lib",
                "files": [{"path": FIRST, "size": 40 * GIB, "mtime": 1}, {"path": DRAFT, "size": 5 * GIB, "mtime": 1}]}]
    far = payload(cfg, libraries=library, models=TMP / "no-models-here")
    check(far.get("ram") == {"reserveMiB": 40 * 1024 + 1024, "who": "Strata",
                             "why": "its weights stay in memory: 40.0 GiB", "lower": "nothing — stop another cell"},
          "defect-history (2026-10-14): Strata keeps its weights in RAM, and the start says how much — the size the library "
          "lists for the first part, plus a GiB: a second start beside the first, still loading, is refused by the scout, "
          "not left to load the model twice")
    here = MODELS / FIRST
    here.write_bytes(b"GGUF")
    with open(here, "r+b") as handle:
        handle.truncate(40 * GIB)           # a sparse file: the size is the disk's, no space is used
    try:
        near = payload(cfg)
    finally:
        here.write_bytes(b"GGUF")
    check(near.get("ram") == {"reserveMiB": 40 * 1024 + 1024, "who": "Strata", "why": "its weights stay in memory: 40.0 GiB",
                              "lower": "nothing — stop another cell"},
          "a file on this disk is asked of the disk: its own size, since a library's listing is not there to say it")
    # An Unsloth ~4-bit pack keeps a BUDGET of its experts in RAM: its first part is a 10 MB header, and Strata's table says 48 GB.
    UD = "Qwen3.8-Flash-Next-GGUF/unsloth/UD-IQ4_XS/Qwen3.8-Flash-Next-UD-IQ4_XS-00001-of-00003.gguf"
    pack = payload({**cfg, "MODEL_FILE": UD, "SPEC_DRAFT_MODEL_FILE": ""},
                   libraries=[{"id": "lib", "name": "NAS", "state": "ok", "path": "/mnt/lib",
                               "files": [{"path": UD, "size": 10 * 2 ** 20, "mtime": 1}]}], models=TMP / "no-models-here")
    check(pack.get("ram") == {"reserveMiB": 48 * 1024, "who": "Strata",
                              "why": "a budget of its experts stays in memory and the rest is read from the disk: Strata asks 48 GiB of RAM for this pack",
                              "lower": "nothing — stop another cell"},
          "a ~4-bit Unsloth pack promises 48 GiB, whatever its first part weighs (10 MB of header): the budget of its experts "
          "stays in memory, and a header's size would have promised nothing")
    check(STRATA.ram_reservation({"MODEL_FILE": UD.replace("UD-IQ4_XS", "UD-Q4_K_XL").replace("of-00003", "of-00004")}, {})
          == pack["ram"] and STRATA.ram_reservation({"MODEL_FILE": UD}, {"MODEL_FILE": 10 * 2 ** 20})["reserveMiB"] == 48 * 1024,
          "the other budget pack (UD-Q4_K_XL, four parts) the same; the promise does not wait for a size")
    check(STRATA.ram_reservation({"MODEL_FILE": "org/Some-UD-name.gguf"}, {}) is None
          and STRATA.ram_reservation({"MODEL_FILE": "Qwen3.8-Flash-Next-GSQ-RCO-IQ3_XXS-00001-of-00002.gguf"}, {"MODEL_FILE": 47 * 2 ** 30})["reserveMiB"] == 47 * 1024 + 1024,
          "negative: an ISTA-DASLab pack (IQ2_XS, IQ3_XXS) keeps ALL its experts in memory — its first part's size plus a GiB when that is more than "
          "Strata's table says its experts are; a name with UD in it that is not a pack's part is not a budget pack")
    check(STRATA.ram_reservation({"MODEL_FILE": FIRST}, {}) == {"reserveMiB": 36352 + 1024, "who": "Strata",
          "why": "its experts stay in memory: 35.5 GiB (Strata's table for this pack)", "lower": "nothing — stop another cell"},
          "a pack nobody can size (not in a library, not on the disk) is promised by Strata's own table — 35.5 GiB of experts for IQ2_XS, plus a GiB: "
          "the engine's own figure, not a guess")
    check("ram" not in payload({**cfg, "MODEL_FILE": "org/Unknown-Quant/Some-Pack-00001-of-00002.gguf"}, models=TMP / "no-models-here"),
          "negative: a pack the table does not know and nobody can size — no promise, and no refusal made up from a guess")
    check("ram" not in payload({"MODEL_FILE": "org/m.gguf", "PORT": "22001"})
          and "ram" not in payload({"RUNNER": "whisper", "MODEL_FILE": "left.gguf", "PORT": "22005"}),
          "negative: llama.cpp maps its file and pages it, whisper is small — a start that keeps nothing in memory promises none")
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


def section_the_note_is_true_in_every_language():
    print("строка «слоя черновика нет» — правда на всех 20 языках:")
    import re
    langs = sorted(f.stem for f in (ROOT / "static/js/i18n").glob("*.js") if re.fullmatch(r"[a-z]{2}", f.stem))
    bad = []
    for lang in langs:
        text = (ROOT / "static/js/i18n" / f"{lang}.js").read_text(encoding="utf-8")
        found = re.search(r'^  strataDraftOff: "([^"\n]*)",$', text, re.M)
        # The two pack names and the file pattern are no one's words: each language's note must still carry them, or it
        # kept the old sentence (Strata "runs without it") that is false for an IQ pack.
        if not found or not all(token in found.group(1) for token in ("mtp-*.gguf", "Q2_0", "IQ")):
            bad.append(lang)
    check(len(langs) == 20 and not bad,
          f"defect-history (2026-10-17): the note said, in all 20 languages, that Strata runs without the draft layer — false for an IQ "
          f"pack, which the engine refuses to start without it; now each says both, naming Q2_0 and IQ (languages: {len(langs)}, not so: {bad})")


def section_cell_assets():
    print("файлы ячейки для скаута:")
    files = cell_assets.RUNNER_ASSETS.get("strata") or ()
    check(files == ("run_strata.sh", "strata_launch.py")
          and all(f in cell_assets.CELL_ASSETS and (ROOT / "cells" / f).is_file() for f in files),
          "скаут берёт у контроллера run_strata.sh и strata_launch.py — оба в белом списке и в cells/")


def main():
    section_the_registry()
    section_ram_by_the_table()
    section_the_command()
    section_an_iq_pack_needs_its_draft_layer()
    section_the_files_a_scout_brings()
    section_the_start()
    section_reported_processes()
    section_the_draft_note_is_seen()
    section_the_note_is_true_in_every_language()
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
