#!/usr/bin/env python3
"""Value snapshot: the GR00T runner — a robot policy on the runner row, as llama.cpp has one.

GR00T N1.7 (the SpiderMonkey task, visumap spider-monkey-model-servers) ran first as NVIDIA's own
ZMQ server, by hand: no board, no VRAM account, no HTTP for a client in another language
(2026-10-13). As a runner its cell is started by the scout like any other: two library folders
(the checkpoint and the backbone it names) brought to the machine, a command built from the
cell's fields, cells/gr00t_server.py serving POST /v1/robot/predict.

Each claim has a positive and a negative pin.

Run: python3 scripts/test_gr00t_runner.py
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from caravan.admin import cell_assets  # noqa: E402
from caravan.admin import fleet_clients as fc  # noqa: E402
from caravan.admin.config_builder import CONFIG_FIELDS, model_paths  # noqa: E402
from caravan.admin.model_locator import Locations  # noqa: E402
from caravan.common.errors import AppError  # noqa: E402
from caravan.common.model_jobs import jobs_for_artifact, jobs_for_cell  # noqa: E402
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


CKPT = "GR00T-N1.7-3B/nvidia/BF16"
BACKBONE = "Cosmos-Reason2-2B/nvidia/BF16"
ROOTED = '"${LLAMA_MODELS_DIR:-$HOME/llama.cpp/models}"/'
GR00T = get("gr00t")


def section_the_registry():
    print("реестр:")
    ids = [r.id for r in REGISTRY]
    check(ids.index("gr00t") == ids.index("strata") + 1, "кнопка GR00T стоит в ряду Runner сразу за Strata")
    row = next(r for r in registry_json() if r["id"] == "gr00t")
    check((row["artifacts"], row["stArchs"], row["modelField"], row["sharedPicker"], row["llamaConfig"],
           row["commandPath"], row["tokenContext"], row["vramPlan"])
          == (["gr00t-st"], ["Gr00tN1d7"], "MODEL_FILE", "source", False, True, False, {"fixedMiB": 7680}),
          f"в браузер уходит: свой вид папки, её архитектура Gr00tN1d7, модель из общего выбора, путь командной "
          f"ячейки, окна в токенах нет, память — замеренная цифра (получено {row})")
    claims = {r["id"]: r["stArchs"] for r in registry_json() if r["stArchs"]}
    check(claims == {"gr00t": ["Gr00tN1d7"], "seamless": ["seamless_m4t", "seamless_m4t_v2"],
                     "personaplex": ["personaplex"], "lfm-audio": ["Lfm2AudioForConditionalGeneration"],
                     "step-audio2": ["step_audio_2"], "qwen3-omni": ["qwen3_omni_moe"]},
          f"папки safetensors своих архитектур называют GR00T, seamless и четыре голосовых раннера (1.3.553, "
          f"их утверждения держит test_launcher_runners.py); литерал «seamless_m4t» "
          f"жил в браузере дважды (получено {claims})")
    check(jobs_for_cell("gr00t") == ("robot-policy",) and jobs_for_artifact("st", arch="Gr00tN1d7") == ("robot-policy",)
          and jobs_for_artifact("st", arch="qwen3_vl") == ("llm",),
          "работа ячейки и папки — robot-policy; negative: папка Cosmos (qwen3_vl) — чат, не робот")
    check(all(f in CONFIG_FIELDS for f in ("GR00T_BACKBONE", "GR00T_EMBODIMENT", "GR00T_DENOISING_STEPS")),
          "поля GR00T — в настройках ячейки")


def section_the_command():
    print("команда:")
    cfg = {"MODEL_FILE": CKPT, "MODEL_NAME": "gr00t-n1.7-droid"}
    check(GR00T.command(cfg) == (f'bash $HOME/run_gr00t.sh "$PORT" {ROOTED}{CKPT} --backbone {ROOTED}{BACKBONE} '
                                 "--embodiment OXE_DROID_RELATIVE_EEF_RELATIVE_JOINT --name gr00t-n1.7-droid"),
          "по умолчанию: основа Cosmos из библиотеки, робот DROID, имя модели на входе машины")
    full = {"MODEL_FILE": "/srv/models/" + CKPT + "/", "GR00T_BACKBONE": "/srv/models/" + BACKBONE,
            "GR00T_EMBODIMENT": "XDOF", "GR00T_DENOISING_STEPS": "8"}
    check(GR00T.command(full) == (f'bash $HOME/run_gr00t.sh "$PORT" /srv/models/{CKPT} --backbone /srv/models/{BACKBONE} '
                                  "--embodiment XDOF --denoising-steps 8"),
          "свои поля: абсолютные пути без корня моделей и без хвостового «/», робот и шаги")
    for name, cfg, words in (
            ("без чекпойнта", {}, "MODEL_FILE is required"),
            ("робот не тег", {"MODEL_FILE": CKPT, "GR00T_EMBODIMENT": "droid arm"}, "must be an embodiment tag"),
            ("шагов 0", {"MODEL_FILE": CKPT, "GR00T_DENOISING_STEPS": "0"}, "from 1 to 64"),
            ("шагов 65", {"MODEL_FILE": CKPT, "GR00T_DENOISING_STEPS": "65"}, "from 1 to 64"),
            ("шаги не число", {"MODEL_FILE": CKPT, "GR00T_DENOISING_STEPS": "4x"}, "from 1 to 64")):
        got = refusal(lambda: GR00T.command(cfg))
        check(got is not None and got[0] == 400 and words in got[1],
              f"negative: {name} — 400, а не команда с подменённым значением ({got})")
    check(refusal(lambda: GR00T.preflight_start({})) == (400, "GR00T cell has no checkpoint — configure it first")
          and GR00T.preflight_start({"MODEL_FILE": CKPT}) is None,
          "старт без чекпойнта отказан до скаута; с ним — проходит")
    check(GR00T.artifact_label({"MODEL_FILE": CKPT}) == "GR00T-N1.7-3B" and GR00T.artifact_label({}) == "GR00T",
          "подпись ячейки — имя модели из папки; без неё — «GR00T»")


TMP = Path(tempfile.mkdtemp(prefix="caravan-gr00t-"))
MODELS = TMP / "models"
for rel in (CKPT, BACKBONE):
    (MODELS / rel).mkdir(parents=True, exist_ok=True)
    (MODELS / rel / "config.json").write_text("{}")


def section_the_files_a_scout_brings():
    print("файлы, которые приносит скаут:")
    check(GR00T.model_file_paths({"MODEL_FILE": CKPT}) == [CKPT, BACKBONE],
          "пустое поле основы — основа по умолчанию: скаут приносит папку, которую называет команда")
    check(GR00T.model_file_paths({"MODEL_FILE": CKPT, "GR00T_BACKBONE": "Other/nvidia/BF16"}) == [CKPT, "Other/nvidia/BF16"],
          "своя основа — её папка")
    cfg = {"RUNNER": "gr00t", "MODEL_FILE": CKPT, "LLAMA_MODELS_DIR": str(MODELS)}
    found = model_paths(cfg)
    hints = {key: at.hint() for key, at in found.items()}
    check(sorted(found) == ["GR00T_BACKBONE", "MODEL_FILE"]
          and all(h and h.get("dir") is True for h in hints.values()),
          "контроллер находит обе папки, и подсказка говорит скауту «это папка»; поле вне трёх файловых "
          f"подсказки не получало, и скаут просил бы папку как файл — 404 (получено {hints})")
    llama = model_paths({"MODEL_FILE": "m.gguf", "LLAMA_MODELS_DIR": str(MODELS)})
    check(sorted(llama) == ["MODEL_FILE"], f"negative: у llama.cpp лишних полей нет (получено {sorted(llama)})")


def payload(cfg, scout_version="2.31.0"):
    keep = fc.topology_store, fc.current_locations, fc.controller_models_dir
    fc.topology_store = lambda: {"hosts": {"box-a": {"id": "box-a", "scoutVersion": scout_version,
                                                     "gpus": [{"index": "0", "memoryTotalMiB": "32607"}]}}}
    fc.current_locations = lambda wait=False: Locations([])
    fc.controller_models_dir = lambda: MODELS
    body = {"hostId": "box-a", "port": 22011, "config": dict(cfg), "modelPath": cfg.get("MODEL_FILE", ""),
            "cacheModels": True}
    try:
        return fc.scout_start_payload(body)
    finally:
        fc.topology_store, fc.current_locations, fc.controller_models_dir = keep


def section_the_start():
    print("старт на скауте:")
    p = payload({"RUNNER": "gr00t", "MODEL_FILE": CKPT, "PORT": "22011"})
    check(p.get("cellKind") == "command" and p.get("modelFiles") == [CKPT, BACKBONE]
          and p.get("healthPath") == "/health",
          "скауту названы обе папки (modelFiles) и путь здоровья ячейки")
    hints = p.get("inPlace") or {}
    check(set(hints) == {CKPT, BACKBONE} and all(h.get("dir") is True for h in hints.values()),
          f"обе папки помечены как папки: скаут соберёт их через /api/models/folder (получено {hints})")
    check(p.get("vram") == {"device": 0, "reserveMiB": 7680, "who": "GR00T",
                            "why": "the policy took 7.0 GB on an RTX 5090", "lower": ""},
          "старт просит у карты 7.5 ГБ: замер политики на RTX 5090 с запасом")
    line = p.get("shellLine") or ""
    check("run_gr00t.sh" in line and "--backbone" in line and "LLAMA_MODELS_DIR=" not in line,
          "строка запуска — run_gr00t.sh, папку моделей ставит скаут по месту, куда легли модели")
    old = refusal(lambda: payload({"RUNNER": "gr00t", "MODEL_FILE": CKPT, "PORT": "22011"}, scout_version="2.30.0"))
    check(old is not None and old[0] == 400 and "2.31.0" in old[1],
          f"negative: скаут 2.30 не приносит файлы командной ячейки — отказ до старта ({old})")
    check(cell_assets.RUNNER_ASSETS.get("gr00t") == ("run_gr00t.sh", "cell_base.py", "gr00t_server.py")
          and all(name in cell_assets.CELL_ASSETS and (ROOT / "cells" / name).is_file()
                  for name in cell_assets.RUNNER_ASSETS["gr00t"]),
          "скаут получает лаунчер, базу и сервер ячейки; все три в белом списке и в cells/")


def section_one_card_rule():
    print("какая карта:")
    gpus = [{"index": 0}, {"index": 1}]
    cases = ["", "CUDA_VISIBLE_DEVICES=1", "CUDA_VISIBLE_DEVICES=1\nCUDA_VISIBLE_DEVICES=0", "CUDA_VISIBLE_DEVICES=",
             "CUDA_VISIBLE_DEVICES=7", 'CUDA_VISIBLE_DEVICES="1"']
    strata = get("strata")
    got = [(GR00T.pinned_card({"ENV": env}, gpus), strata.pinned_card({"ENV": env}, gpus)) for env in cases]
    check(got == [(0, 0), (1, 1), (0, 0), (None, None), (None, None), (1, 1)],
          f"одно правило карты у GR00T и Strata: последний CUDA_VISIBLE_DEVICES, иначе 0, чужой — нет карты ({got})")
    check(GR00T.vram_reservation({"ENV": "CUDA_VISIBLE_DEVICES=7"}, gpus) is None,
          "negative: карта, которой у машины нет, — без резерва, а не резерв на карте 0")


def main():
    section_the_registry()
    section_the_command()
    section_the_files_a_scout_brings()
    section_the_start()
    section_one_card_rule()
    print()
    if _fail:
        print(f"FAILED ({len(_fail)}):")
        for m in _fail:
            print("  - " + m)
        return 1
    print("gr00t runner OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
