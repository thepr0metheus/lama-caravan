#!/usr/bin/env python3
"""Value snapshot: the servers that answer in a voice are RUNNERS — PersonaPlex, LFM2.5-Audio, Step-Audio 2,
Qwen3-Omni and llama.cpp-omni stand on the runner row of the new-cell form as llama.cpp and vLLM do.

The owner, 2026-10-15: "if there is no fitting server, add the needed server to the list of servers in the
caravan's UI first, and start it from the UI — as the llama.cpp panel has; not some fake button on a panel, but a
server one can pick and start". In 1.3.551 they were custom-command cells with presets (a command typed into a
box); now each is a class of caravan/domain/runner.py with its launcher (cells/run_<name>.sh), its model's kind,
its footprint and its words, and the board treats it like any other runner.

Pinned by value, each claim with a positive and a negative: the row and its place in the registry; the line a start
runs (the table CASES, which the browser's twin of the preview is run against in test_js_llama_edit.py); the folder
a model of several files is launched by; what the scout is told to bring; the VRAM a start reserves; the claims on
checkpoint folders and what each folder does; the asset group a scout fetches; the words every tab needs.

Run: python3 scripts/test_launcher_runners.py
"""
import json
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from caravan.admin import cell_assets  # noqa: E402
from caravan.admin import models as models_mod  # noqa: E402
from caravan.common.errors import AppError  # noqa: E402
from caravan.common.model_jobs import _ARCH_JOBS, jobs_for_artifact, jobs_for_cell  # noqa: E402
from caravan.domain.runner import REGISTRY, get, registry_json  # noqa: E402

ROOTED = '"${LLAMA_MODELS_DIR:-$HOME/llama.cpp/models}"/'
VOICE = ("personaplex", "lfm-audio", "step-audio2", "qwen3-omni", "minicpm-omni")
PP = "personaplex-7b-v1/nvidia/SAFETENSORS"
LFM = "LFM2.5-Audio-1.5B/LiquidAI/SAFETENSORS"
STEP = "Step-Audio-2-mini/stepfun-ai/SAFETENSORS"
QWEN = "Qwen3-Omni-30B-A3B-Instruct-AWQ-4bit/cyankiwi/AWQ"
MINI = "MiniCPM-o-4_5-gguf/openbmb"
MINI_FILE = MINI + "/Q4_K_M/MiniCPM-o-4_5-Q4_K_M.gguf"

#: (name, runner, config, the line a start runs) — the browser's preview is held to the same table.
CASES = [
    ("PersonaPlex: a library folder", "personaplex", {"MODEL_FILE": PP},
     f'bash $HOME/run_personaplex.sh "$PORT" {ROOTED}{PP}'),
    ("LFM2.5-Audio: a library folder", "lfm-audio", {"MODEL_FILE": LFM},
     f'bash $HOME/run_lfm_audio.sh "$PORT" {ROOTED}{LFM}'),
    ("Step-Audio 2: the recipe comes before the folder", "step-audio2", {"MODEL_FILE": STEP},
     f'bash $HOME/run_vllm_omni.sh "$PORT" step-audio2 {ROOTED}{STEP}'),
    ("Qwen3-Omni: the same launcher, its own recipe", "qwen3-omni", {"MODEL_FILE": QWEN},
     f'bash $HOME/run_vllm_omni.sh "$PORT" qwen3-omni {ROOTED}{QWEN}'),
    ("llama.cpp-omni: the model is picked by one file and launched by its folder", "minicpm-omni", {"MODEL_FILE": MINI_FILE},
     f'bash $HOME/run_minicpm_omni.sh "$PORT" {ROOTED}{MINI}'),
    ("llama.cpp-omni: any other file of the model gives the same folder", "minicpm-omni",
     {"MODEL_FILE": MINI + "/default/hifigan2.gguf"}, f'bash $HOME/run_minicpm_omni.sh "$PORT" {ROOTED}{MINI}'),
    ("an absolute folder: no root, no trailing slash", "personaplex", {"MODEL_FILE": "/srv/models/p/"},
     'bash $HOME/run_personaplex.sh "$PORT" /srv/models/p'),
    ("an absolute folder with a space is quoted, not split", "lfm-audio", {"MODEL_FILE": "/srv/my models/l"},
     "bash $HOME/run_lfm_audio.sh \"$PORT\" '/srv/my models/l'"),
    ("a relative folder with a quote in it is quoted", "step-audio2", {"MODEL_FILE": "a'b/c/d"},
     f"bash $HOME/run_vllm_omni.sh \"$PORT\" step-audio2 {ROOTED}'a'\"'\"'b/c/d'"),
    ("llama.cpp-omni: an absolute file", "minicpm-omni", {"MODEL_FILE": "/srv/m/" + MINI_FILE},
     f'bash $HOME/run_minicpm_omni.sh "$PORT" /srv/m/{MINI}'),
]

#: (name, runner, config, the words of the refusal)
REFUSALS = [
    ("no model", "personaplex", {}, "MODEL_FILE is required for a PersonaPlex cell"),
    ("no model, whitespace only", "step-audio2", {"MODEL_FILE": "   "}, "MODEL_FILE is required for a Step-Audio 2 cell"),
    ("llama.cpp-omni: a file with no model folder above it", "minicpm-omni", {"MODEL_FILE": "model.gguf"},
     "must be a file of a library model laid out as <model>/<author>/<variant>/<file>"),
    ("llama.cpp-omni: a file one folder deep", "minicpm-omni", {"MODEL_FILE": "m/model.gguf"},
     "must be a file of a library model laid out as <model>/<author>/<variant>/<file>"),
    ("llama.cpp-omni: an absolute file with nothing above it", "minicpm-omni", {"MODEL_FILE": "/model.gguf"},
     "must be a file of a library model laid out as <model>/<author>/<variant>/<file>"),
]

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


def section_the_row():
    print("the registry:")
    ids = [r.id for r in REGISTRY]
    check(ids[ids.index("translate") + 1:ids.index("custom")] == list(VOICE),
          f"the five tabs stand together after the speech runners and before custom: {ids}")
    rows = {r["id"]: r for r in registry_json()}
    want = {
        "personaplex": (["personaplex-st"], ["personaplex"], "run_personaplex.sh", ["{model}"], "picked", 20480, "/", "raw"),
        "lfm-audio": (["lfm-audio-st"], ["Lfm2AudioForConditionalGeneration"], "run_lfm_audio.sh", ["{model}"], "picked", 7168, "/health", "raw"),
        "step-audio2": (["step-audio2-st"], ["step_audio_2"], "run_vllm_omni.sh", ["step-audio2", "{model}"], "picked", 25600, "/health", "openai"),
        "qwen3-omni": (["qwen3-omni-st"], ["qwen3_omni_moe"], "run_vllm_omni.sh", ["qwen3-omni", "{model}"], "picked", 31744, "/health", "openai"),
        "minicpm-omni": (["llm-gguf"], [], "run_minicpm_omni.sh", ["{model}"], "entry", 12800, "/health", "raw"),
    }
    for rid, (artifacts, archs, launcher, args, rule, mib, health, api) in want.items():
        row = rows[rid]
        got = (row["artifacts"], row["stArchs"], row["launcher"], row["launcherArgs"], row["folderRule"],
               row["vramPlan"]["fixedMiB"], row["health"], row["api"])
        check(got == (artifacts, archs, launcher, args, rule, mib, health, api), f"{rid}: the row says {got}")
        common = (row["sharedPicker"], row["modelField"], row["commandPath"], row["llamaConfig"], row["tokenContext"],
                  row["editorTab"], row["engineCell"], row["gpuOnly"], row["formats"])
        check(common == ("source", "MODEL_FILE", True, False, False, True, False, True, ["gguf"] if rid == "minicpm-omni" else ["*"]),
              f"{rid}: it reads the shared picker, is a command cell with no llama flags and no token window, and has a tab and no CPU mode ({common})")
        check(all(row[k] for k in ("labelKey", "benefitsKey", "minusKey", "icon")), f"{rid}: it has a label, its benefits, its costs and an icon")
    icons = [rows[r]["icon"] for r in VOICE]
    check(len(set(icons)) == 5 and all(i not in [x["icon"] for x in rows.values() if x["id"] not in VOICE] for i in icons),
          f"negative: no two tabs wear one icon, and none wears another runner's ({icons})")
    check(all("launcher" not in rows[r] for r in rows if r not in VOICE),
          "negative: no other runner says a launcher — the preview of those is their own")
    old = {rid: row for rid, row in rows.items() if rid not in VOICE}
    needs = {rid: row.get("needsKey") for rid, row in old.items() if row["artifacts"] != ["*"] and not row["engineCell"]}
    check(all(needs.values()), f"every older runner with a kind of its own says why its tab is grey: {needs}")
    check(all("minusKey" in rows[r] for r in ("llama-server", "prism", "vllm", "strata", "gr00t", "whisper", "moonshine",
                                               "transcribe", "seamless", "translate", "custom")),
          "the costs moved into the registry for every tab that had them in the browser's table")
    check({r["id"] for r in registry_json() if r.get("gpuOnly")} == {"strata", "gr00t", *VOICE},
          "the runners with no CPU mode: Strata and GR00T, as the browser's lists said by id, and the five voice runners")


def section_the_line():
    print("the line a start runs:")
    for name, rid, cfg, want in CASES:
        got = get(rid).command(cfg)
        check(got == want, f"{name}: {got}")
    for name, rid, cfg, words in REFUSALS:
        got = refusal(lambda: get(rid).command(cfg))
        check(got is not None and got[0] == 400 and words in got[1], f"negative: {name} — 400 naming the field, not a line with an empty folder ({got})")
    check(refusal(lambda: get("personaplex").preflight_start({})) == (400, "PersonaPlex cell has no model — configure it first")
          and get("personaplex").preflight_start({"MODEL_FILE": PP}) is None
          and get("qwen3-omni").preflight_start({}, model=QWEN) is None,
          "a start without a model is refused before the scout; with the picked model (or the slot's) it goes")
    merged = {"MODEL_FILE": PP}
    line = get("personaplex").prepare(merged)
    check(merged.get("LLAMA_MODELS_DIR") and line == get("personaplex").command(merged),
          "prepare writes the models root into the config block, and answers the same line")
    merged = {"MODEL_FILE": PP, "LLAMA_MODELS_DIR": "/data/models"}
    get("personaplex").prepare(merged)
    check(merged["LLAMA_MODELS_DIR"] == "/data/models", "negative: a root the config names is left as it is")
    check(get("step-audio2").artifact_label({"MODEL_FILE": STEP}) == "Step-Audio-2-mini"
          and get("minicpm-omni").artifact_label({"MODEL_FILE": MINI_FILE}) == "MiniCPM-o-4_5-gguf"
          and get("lfm-audio").artifact_label({}) == "LFM2.5-Audio" and get("minicpm-omni").artifact_label({}) == "llama.cpp-omni",
          "a cell is labelled by its model's folder; with none, by the runner's name")
    check(all(get(r).health_path({}) == ("/" if r == "personaplex" else "/health") for r in VOICE)
          and get("lfm-audio").health_path({"HEALTH_PATH": "/ready"}) == "/ready",
          "health: PersonaPlex answers its page, the others /health; the config's own path wins")


def section_the_files_a_scout_brings():
    print("what the scout is told to bring:")
    check(get("personaplex").model_file_paths({"MODEL_FILE": PP}) == [PP]
          and get("qwen3-omni").model_file_paths({"MODEL_FILE": QWEN + "/"}) == [QWEN],
          "a checkpoint: its folder, without a trailing slash")
    check(get("minicpm-omni").model_file_paths({"MODEL_FILE": MINI_FILE}) == [MINI],
          "llama.cpp-omni: the model's folder, not the one file — the launcher needs all ten")
    check(get("minicpm-omni").model_file_paths({"MODEL_FILE": "model.gguf"}) == [] and get("minicpm-omni").model_file_paths({}) == [],
          "negative: a file no folder can be told from, and no file: nothing to bring, and no refusal here (the start refuses it)")
    from caravan.admin.config_builder import model_paths
    with tempfile.TemporaryDirectory(prefix="caravan-voice-") as tmp:
        (Path(tmp) / MINI / "Q4_K_M").mkdir(parents=True)
        (Path(tmp) / MINI / "Q4_K_M" / "MiniCPM-o-4_5-Q4_K_M.gguf").write_bytes(b"x")
        found = model_paths({"RUNNER": "minicpm-omni", "MODEL_FILE": MINI_FILE, "LLAMA_MODELS_DIR": tmp})
        hint = found["MODEL_FILE"].hint()
        check(found["MODEL_FILE"].rel == MINI and hint is not None and hint.get("dir") is True,
              f"the controller names the FOLDER to the scout, with the hint «this is a folder»: {hint}")


def section_the_start():
    print("the start the scout gets (fleet_clients.scout_start_payload):")
    from caravan.admin import fleet_clients as fc
    from caravan.admin.model_locator import Locations
    with tempfile.TemporaryDirectory(prefix="caravan-voice-start-") as tmp:
        models = Path(tmp)
        for folder in (PP, LFM, STEP, QWEN, MINI + "/Q4_K_M"):
            (models / folder).mkdir(parents=True)
        (models / MINI_FILE).write_bytes(b"x")

        def payload(cfg, scout_version="2.31.0"):
            keep = fc.topology_store, fc.current_locations, fc.controller_models_dir
            fc.topology_store = lambda: {"hosts": {"box-a": {"id": "box-a", "scoutVersion": scout_version,
                                                             "gpus": [{"index": "0", "memoryTotalMiB": "32607"}]}}}
            fc.current_locations = lambda wait=False: Locations([])
            fc.controller_models_dir = lambda: models
            body = {"hostId": "box-a", "port": 22031, "config": dict(cfg), "modelPath": cfg.get("MODEL_FILE", ""), "cacheModels": True}
            try:
                return fc.scout_start_payload(body)
            finally:
                fc.topology_store, fc.current_locations, fc.controller_models_dir = keep

        for rid, model, folder, mib, health in (("personaplex", PP, PP, 20480, "/"), ("lfm-audio", LFM, LFM, 7168, "/health"),
                                                ("step-audio2", STEP, STEP, 25600, "/health"), ("qwen3-omni", QWEN, QWEN, 31744, "/health"),
                                                ("minicpm-omni", MINI_FILE, MINI, 12800, "/health")):
            p = payload({"RUNNER": rid, "MODEL_FILE": model, "PORT": "22031"})
            hints = p.get("inPlace") or {}
            check(p.get("cellKind") == "command" and p.get("modelFiles") == [folder] and p.get("healthPath") == health,
                  f"{rid}: a command cell; the scout is told to bring {folder}, and where to look for health ({p.get('modelFiles')}, {p.get('healthPath')})")
            check(folder in hints and hints[folder].get("dir") is True,
                  f"{rid}: the folder is marked as a folder — a scout that cannot read it in place fetches it whole (got {hints})")
            check(p.get("vram") == {"device": 0, "reserveMiB": mib, "who": get(rid).vram_who, "why": get(rid).vram_why, "lower": ""},
                  f"{rid}: the start asks the card for {mib} MiB: {p.get('vram')}")
            line = p.get("shellLine") or ""
            check(line.startswith('set -euo pipefail; export PORT=22031; export CUDA_DEVICE_ORDER="PCI_BUS_ID"; exec bash $HOME/' + get(rid).launcher + ' "$PORT" ')
                  and "LLAMA_MODELS_DIR=" not in line and "${LLAMA_MODELS_DIR:-" in line,
                  f"{rid}: the start line numbers the cards as the board does, then is the launcher and the port, and leaves the models root to the scout (where the files landed): {line[:130]}")
        old = refusal(lambda: payload({"RUNNER": "qwen3-omni", "MODEL_FILE": QWEN, "PORT": "22031"}, scout_version="2.30.0"))
        check(old is not None and old[0] == 400 and "2.31.0" in old[1],
              f"negative: scout 2.30 does not bring a command cell's model files: refused before the start ({old})")
        shallow = refusal(lambda: payload({"RUNNER": "minicpm-omni", "MODEL_FILE": "model.gguf", "PORT": "22031"}))
        check(shallow is not None and shallow[0] == 400 and "<model>/<author>/<variant>/<file>" in shallow[1],
              f"negative: llama.cpp-omni with a file that has no model folder: refused with the field's name ({shallow})")
        nomodel = refusal(lambda: payload({"RUNNER": "personaplex", "PORT": "22031"}))
        check(nomodel is not None and nomodel[0] == 400, f"negative: no model: refused before the scout ({nomodel})")


def section_the_card():
    print("the card:")
    gpus = [{"index": 0, "memoryTotalMiB": 32607}, {"index": 1, "memoryTotalMiB": 24576}]
    for rid, mib in (("personaplex", 20480), ("lfm-audio", 7168), ("step-audio2", 25600), ("qwen3-omni", 31744), ("minicpm-omni", 12800)):
        r = get(rid)
        res = r.vram_reservation({"MODEL_FILE": "x"}, gpus)
        check(res is not None and res["device"] == 0 and res["reserveMiB"] == mib and res["who"] and res["why"],
              f"{rid}: a start reserves {mib} MiB on the first card ({res})")
        check(r.vram_plan() == {"fixedMiB": mib}, f"{rid}: the form's estimate is the same fixed figure")
    check(get("lfm-audio").vram_reservation({"ENV": "CUDA_VISIBLE_DEVICES=1"}, gpus)["device"] == 1,
          "the card the ENV pins is the card it reserves on")
    check(get("lfm-audio").vram_reservation({"ENV": "CUDA_VISIBLE_DEVICES=5"}, gpus) is None
          and get("lfm-audio").vram_reservation({}, []) is None
          and get("lfm-audio").vram_reservation({"ENV": "CUDA_VISIBLE_DEVICES="}, gpus) is None,
          "negative: a pin that names no card of the machine, a machine that reports no card, an empty pin: nothing is reserved, none is guessed")
    check(max(get(r).vram_mib for r in VOICE) < 32607 and get("qwen3-omni").vram_mib > 30 * 1024,
          "Qwen3-Omni's figure is the whole 32 GB card, and no figure is more than a card")
    check(all(get(r).min_scout == (2, 31, 0) for r in VOICE), "the scout must be 2.31: folders and a command cell's model files")


def section_the_claims():
    print("the folders a runner claims, and what a folder does:")
    claims = {r.id: r.st_archs for r in REGISTRY if r.st_archs}
    check(claims == {"gr00t": ("Gr00tN1d7",), "seamless": ("seamless_m4t", "seamless_m4t_v2"), "personaplex": ("personaplex",),
                     "lfm-audio": ("Lfm2AudioForConditionalGeneration",), "step-audio2": ("step_audio_2",), "qwen3-omni": ("qwen3_omni_moe",)},
          f"the architectures with an owner: {claims}")
    seen = [a for r in REGISTRY for a in r.st_archs]
    check(len(seen) == len(set(seen)), "negative: no architecture has two owners")
    check(all(a not in ("qwen3", "qwen3_vl", "qwen3_moe", "qwen3_omni") for a in seen),
          "negative: the ordinary Qwen3 families (chat, vision, MoE) are nobody's but vLLM's")
    # The jobs of a folder are the jobs of the runner that owns its architecture: two tables, one rule.
    for r in REGISTRY:
        for arch in r.st_archs:
            check(jobs_for_artifact("st", arch=arch) == jobs_for_cell(r.id),
                  f"{r.id}: a folder of {arch} does what a cell of {r.id} does ({jobs_for_artifact('st', arch=arch)})")
    check(set(_ARCH_JOBS) == {a for r in REGISTRY if r.id in VOICE for a in r.st_archs},
          "the architecture table of model_jobs.py names the voice runners' claims and no other")
    check(jobs_for_cell("personaplex") == ("voice-chat",) and jobs_for_cell("minicpm-omni") == ("voice-chat",)
          and jobs_for_cell("qwen3-omni") == ("llm", "voice-chat") and jobs_for_cell("step-audio2") == ("llm", "voice-chat")
          and jobs_for_cell("lfm-audio") == ("tts",),
          "what the cells do: two talk and nothing else, two talk and also chat, one speaks")
    check(jobs_for_cell("lfm-audio", ["tts", "tts.lfm-audio"]) == ("tts",) and jobs_for_cell("custom", ["voice-chat"]) == ("voice-chat",),
          "the live word wins, and a cell may say voice-chat")
    check(jobs_for_artifact("st", arch="qwen3") == ("llm",) and jobs_for_artifact("st", arch="") == ("llm",),
          "negative: an ordinary chat checkpoint is still an LLM")


def section_the_architecture_of_a_folder():
    print("the architecture of a checkpoint folder:")
    cases = [
        ("model_type is the answer", {"model_type": "personaplex"}, "personaplex"),
        ("no model_type: the first architecture", {"architectures": ["Lfm2AudioForConditionalGeneration"]}, "Lfm2AudioForConditionalGeneration"),
        ("both: model_type wins", {"model_type": "step_audio_2", "architectures": ["StepAudio2ForCausalLM"]}, "step_audio_2"),
        ("an empty model_type falls through to the architecture", {"model_type": "", "architectures": ["XForCausalLM"]}, "XForCausalLM"),
        ("negative: neither", {"hidden_size": 8}, ""),
        ("negative: an empty list of architectures", {"architectures": []}, ""),
        ("negative: architectures that is not a list", {"architectures": "X"}, ""),
        ("negative: a config that is not an object", [1, 2], ""),
    ]
    with tempfile.TemporaryDirectory(prefix="caravan-arch-") as tmp:
        for index, (name, doc, want) in enumerate(cases):
            folder = Path(tmp) / f"c{index}"
            folder.mkdir()
            (folder / "config.json").write_text(json.dumps(doc))
            got = models_mod._st_arch(folder)
            check(got == want, f"{name}: {got!r}")
        broken = Path(tmp) / "broken"
        broken.mkdir()
        (broken / "config.json").write_text("{not json")
        check(models_mod._st_arch(broken) == "" and models_mod._st_arch(Path(tmp) / "none") == "",
              "negative: a config that is not JSON, and a folder with none: no architecture, no error")
        again = Path(tmp) / "again"
        again.mkdir()
        (again / "config.json").write_text(json.dumps({"model_type": "a"}))
        first = models_mod._st_arch(again)
        (again / "config.json").write_text(json.dumps({"model_type": "bb"}))
        check((first, models_mod._st_arch(again)) == ("a", "bb"), "a rewritten config is read again, not remembered")
        # The Qwen3-Omni AWQ checkpoint's config.json is 649 KB, nearly all of it the list of modules the quantiser
        # leaves alone; model_type stands near the top, but 64 KiB of a JSON is not a JSON, so it was read as "" and
        # the folder reached no runner that claims by architecture. Found on the board, not by the fixtures: they
        # were small.
        big = Path(tmp) / "big"
        big.mkdir()
        (big / "config.json").write_text(json.dumps({
            "architectures": ["Qwen3OmniMoeForConditionalGeneration"], "model_type": "qwen3_omni_moe",
            "quantization_config": {"modules_to_not_convert": [f"thinker.model.layers.{i}.mlp.gate" for i in range(15000)]}}))
        size = (big / "config.json").stat().st_size
        check(size > 4 * 65536, f"the fixture is far bigger than the 64 KiB that used to be read ({size} bytes)")
        check(models_mod._st_arch(big) == "qwen3_omni_moe", "a config far over 64 KiB is read whole: its model_type answers")
        cap = models_mod._ST_ARCH_MAX_BYTES
        try:
            models_mod._ST_ARCH_CACHE.clear()  # the answer above is remembered; the cap is asked afresh each time
            models_mod._ST_ARCH_MAX_BYTES = size
            at_cap = models_mod._st_arch(big)
            models_mod._ST_ARCH_CACHE.clear()
            models_mod._ST_ARCH_MAX_BYTES = size - 1
            over_cap = models_mod._st_arch(big)
        finally:
            models_mod._ST_ARCH_MAX_BYTES = cap
            models_mod._ST_ARCH_CACHE.clear()
        check(at_cap == "qwen3_omni_moe", "a config exactly at the cap is still read")
        check(over_cap == "", "negative: a config one byte over the cap is not read, and is not guessed from a prefix")
        check(cap >= 1024 * 1024, "the cap leaves room: the biggest config met is 649 KB")


def section_the_files_of_a_runner():
    print("the files a scout fetches for a runner:")
    for rid in VOICE:
        files = cell_assets.assets_for_runner(rid)
        runner = get(rid)
        check(files and runner.launcher in files, f"{rid}: its group holds its launcher {runner.launcher} ({files})")
        check(all(name in cell_assets.CELL_ASSETS and (Path(cell_assets.CELLS_DIR) / name).is_file() for name in files),
              f"{rid}: every file of the group is one the controller hands out, and is in cells/")
    check(cell_assets.assets_for_runner("lfm-audio") == ("run_lfm_audio.sh", "cell_base.py", "lfm_audio_server.py"),
          "LFM2.5-Audio's group carries its cell server and the base it imports; the others serve themselves")
    check(cell_assets.assets_for_runner("step-audio2") == cell_assets.assets_for_runner("qwen3-omni") == ("run_vllm_omni.sh",),
          "the two vLLM-Omni families share one launcher: the same file under either id")
    manifest = cell_assets.cell_assets_manifest()
    check(all(list(manifest["runners"][rid]) == list(cell_assets.RUNNER_ASSETS[rid]) for rid in VOICE),
          "the manifest a scout reads says the same: runner id → files")
    for name, rid, cfg, want in CASES:
        group = cell_assets.group_for_command(get(rid).command(cfg))
        check(group in VOICE and get(rid).launcher in cell_assets.RUNNER_ASSETS[group],
              f"{name}: a cell's own line names a group of its launcher ({group})")
    check(cell_assets.group_for_command("bash $HOME/run_tts.sh \"$PORT\" xtts") == "custom"
          and cell_assets.group_for_command("echo hello") == "",
          "negative: the TTS launcher is still the custom group's, and a command with no launcher of ours has none")
    old = [r.id for r in REGISTRY if r.id.startswith("vllm-omni")]
    check(old == [] and "vllm-omni" not in cell_assets.RUNNER_ASSETS,
          "negative: the 1.3.551 group «vllm-omni» is gone: no runner has that id, and a group nobody asks for is a lie")


def section_one_card():
    print("раннеры, которые идут на одной карте:")
    rows = {r["id"]: r for r in registry_json()}
    one = {rid for rid, row in rows.items() if row.get("oneCard")}
    check(one == {"strata", "gr00t", *VOICE},
          f"форма спрашивает карту у Strata, GR00T и пяти голосовых: у них пин карты — единственный способ выбрать (получено {sorted(one)})")
    check(all(rows[rid].get("gpuOnly") for rid in one), "каждый из них без CPU-режима: одна карта — это и есть их устройство")
    others = ("llama-server", "prism", "vllm", "whisper", "moonshine", "transcribe", "seamless", "translate", "custom", "ollama", "lmstudio")
    check(not any("oneCard" in rows[rid] for rid in others if rid in rows),
          "negative: llama.cpp (набор карт), vLLM (свой ENV и тензорный параллелизм), речевые раннеры и custom чипов одной карты не получают")
    check("oneCard" not in rows["vllm"] and all(r.one_card is False for r in REGISTRY if r.id in others),
          "и признак в строке реестра появляется только у тех, у кого он есть (прежние строки читаются как читались)")


def section_the_words():
    print("the words every tab needs:")
    en = (ROOT / "static" / "js" / "i18n" / "en.js").read_text(encoding="utf-8")
    keys = set(re.findall(r"^  (\w+):", en, re.M))
    missing = []
    for r in registry_json():
        if not r.get("editorTab", True):
            continue
        for field in ("labelKey", "benefitsKey", "minusKey", "needsKey"):
            if r.get(field) and r[field] not in keys:
                missing.append(f"{r['id']}.{field} = {r[field]}")
    check(not missing, f"every key a tab names is in the dictionary: {missing}")
    check("jobVoiceChat" in keys, "the job's label (jobVoiceChat) is in the dictionary")
    for rid in VOICE:
        row = next(r for r in registry_json() if r["id"] == rid)
        label = re.search(rf'^  {row["labelKey"]}: "([^"]*)",$', en, re.M).group(1)
        check(label == get(rid).display_name(), f"{rid}: the tab reads «{label}»")


def section_the_tabs_wrap():
    print("the row of tabs:")
    tabs = [r["id"] for r in registry_json() if r.get("editorTab", True)]
    css = (ROOT / "static" / "css" / "form.css").read_text(encoding="utf-8")
    page = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    row = re.search(r'<div class="cell-kind-toggle runner-tabs"[^>]*>', page)
    check(len(tabs) >= 16 and all(r in tabs for r in VOICE), f"the form draws {len(tabs)} tabs, the five voice servers among them")
    check(re.search(r"\.runner-tabs\s*\{\s*flex-wrap:\s*wrap;\s*\}", css) is not None,
          "the row wraps onto more lines (form.css): in one line sixteen tabs were 2158 px wide, and no dialog held them — the last, Custom command among them, ran out of it")
    check(row is not None and "nowrap" not in row.group(0), "negative: the markup of the row does not say nowrap, which would beat the stylesheet")
    check(re.search(r"\.runner-tabs\s+\.cell-kind-btn\s*\{[^}]*white-space:\s*nowrap", css) is not None,
          "a tab's own name stays on one line: the row breaks between tabs, never inside one")


def main():
    section_the_row()
    section_the_tabs_wrap()
    section_the_line()
    section_the_files_a_scout_brings()
    section_the_start()
    section_the_card()
    section_the_claims()
    section_the_architecture_of_a_folder()
    section_the_files_of_a_runner()
    section_the_words()
    section_one_card()
    print()
    if _fail:
        print(f"launcher runners: {len(_fail)} FAILED")
        return 1
    print("launcher runners OK: five voice servers on the runner row, each a class")
    return 0


if __name__ == "__main__":
    sys.exit(main())
