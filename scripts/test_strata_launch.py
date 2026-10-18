#!/usr/bin/env python3
"""Value snapshot: cells/strata_launch.py — what a Strata cell makes and runs at its start.

The launcher reads Strata's own setup.py and runs Strata's own tools, so here it meets a
stand-in Strata: a setup.py with the tables and rules the launcher reads (the real ones,
v0.1.42, trimmed to the rows these pins use), tools that write what the real ones write,
and an engine that is a file. The engine arguments are pinned against the config Strata's
own setup wrote on the GPU machine for IQ2_XS at 131072 tokens (2026-10-13): the launcher
reproduced them there byte for byte, and these pins hold that shape.

Each refusal is a negative pin: a start that cannot work says why in one line of the cell's
log, before the engine is asked.

Run: python3 scripts/test_strata_launch.py
"""
import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "cells"))

import strata_launch  # noqa: E402
from strata_launch import StrataLaunch  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


TMP = Path(tempfile.mkdtemp(prefix="caravan-strata-launch-"))
FIRST = "Qwen3.8-Flash-Next-GSQ-RCO-IQ2_XS-00001-of-00002.gguf"
SECOND = "Qwen3.8-Flash-Next-GSQ-RCO-IQ2_XS-00002-of-00002.gguf"

SETUP = '''
import os
EXE = "strata"
import math
MODELS = {"IQ2_XS": {"ram_gb": 48, "arena_gb": 35.5},
          "UD-Q4_K_XL": {"ram_gb": 48, "arena_gb": 77.0, "budget": True},
          "UD-IQ4_XS": {"ram_gb": 48, "arena_gb": 59.5, "budget": True}}
KV_CELL_BYTES = {"q4_0": 576, "k8v4": 816}
UNSLOTH_RAM_LEFT_GB = 24
FAMILIES = {"qwen": {"name": "qwen3.8-flash-next"},
            "coder": {"name": "qwen3.8-flash-next-coder", "profile": "expert-profile-coder.bin"},
            "unsloth": {"name": "qwen3.8-flash-next-unsloth", "pack_args": ["--compat-bf16"]}}
DRAFT_VOCABS = {"cjk": "draft_vocab.bin", "en": "draft_vocab_en.bin",
                "cyrillic": "draft_vocab_cyrillic.bin", "fr": "draft_vocab_fr.bin"}
NAMES = {"Qwen3.8-Flash-Next-GSQ-RCO-IQ2_XS-00001-of-00002.gguf": ("qwen", "IQ2_XS"),
         "Qwen3.8-Flash-Next-UD-Q4_K_XL-00001-of-00004.gguf": ("unsloth", "UD-Q4_K_XL"),
         "Qwen3.8-Flash-Next-UD-IQ4_XS-00001-of-00003.gguf": ("unsloth", "UD-IQ4_XS")}
def ram_gb():
    return float(os.environ.get("FAKE_RAM_GB", "60"))
def gguf_choice(name):
    return NAMES.get(name)
def low_ram_wanted(model, ram, choice="auto"):
    return not MODELS[model].get("budget") and ram < MODELS[model]["arena_gb"] + 10
def kv_streaming_wanted(model, ctx, kv, ram, choice="auto"):
    return ctx >= 65536 and ram >= MODELS[model]["ram_gb"] + ctx * 13 * 1056 / 1e9 + 1
def kv_streaming_ram_gb(ctx, kv):
    return ctx * (13 * KV_CELL_BYTES.get(kv, 1056)) / 1e9
def resident_budget_gib(model, ram, kv_ram_gb=0.0):
    gib = round(ram) - UNSLOTH_RAM_LEFT_GB - math.ceil(kv_ram_gb)
    return max(8, min(gib, int(MODELS[model]["arena_gb"] / 1.073741824)))
'''
IQ_PACK = '''
import json, sys
from pathlib import Path
out = Path(sys.argv[sys.argv.index("--out") + 1])
(out / "tokenizer").mkdir(parents=True, exist_ok=True)
(out / "tokenizer" / "vocab.json").write_text("{}")
(out / "native_experts.txt").write_text("e")
(out / "argv.json").write_text(json.dumps(sys.argv[1:]))
with open(Path(__file__).resolve().parent.parent / "runs.txt", "a") as runs:
    runs.write("pack\\n")
'''
MTP_RT = '''
import sys
from pathlib import Path
out = Path(sys.argv[sys.argv.index("--out") + 1])
out.mkdir(parents=True, exist_ok=True)
(out / "experts.bin").write_bytes(b"x")
'''
READER = '''
class T:
    def __init__(self, name):
        self.name = name
class GGUFFile:
    def __init__(self, path):
        text = open(path, "rb").read().decode()
        self.tensors = [T("per_layer_token_embd.weight")] if "PLE" in text else [T("blk.0.ffn")]
'''


def strata_home(name="home", setup=SETUP, engine=True, build=None):
    home = TMP / name
    files = {"setup.py": setup, "tools/iq_pack.py": IQ_PACK, "tools/mtp_rt.py": MTP_RT,
             "tools/gguf_reader.py": READER, "serve/server.py": "", "data/expert-profile.bin": "p",
             "data/expert-profile-coder.bin": "c", "data/draft_vocab_cyrillic.bin": "cyr",
             "data/draft_vocab_en.bin": "en",
             "engine/BUILD.json": json.dumps(build or {"cuda_dirs": ["/cuda/bin"]})}
    if engine:
        files["engine/strata"] = "engine"
    for rel, text in files.items():
        (home / rel).parent.mkdir(parents=True, exist_ok=True)
        (home / rel).write_text(text)
    return home


def model(folder="model", first_text="GGUF", second_text="GGUF PLE", mtp=True):
    root = TMP / folder
    root.mkdir(parents=True, exist_ok=True)
    (root / FIRST).write_text(first_text)
    if second_text is not None:
        (root / SECOND).write_text(second_text)
    if mtp:
        (root / "mtp-q2_0.gguf").write_text("GGUF mtp")
    return root


class RamOf:
    """The machine's RAM as the stand-in setup.py reads it (os.environ, as the real one reads
    /proc/meminfo) — for one call."""

    def __init__(self, gb):
        self.gb = gb

    def __call__(self, fn):
        keep = os.environ.get("FAKE_RAM_GB")
        os.environ["FAKE_RAM_GB"] = str(self.gb)
        try:
            return fn()
        finally:
            if keep is None:
                os.environ.pop("FAKE_RAM_GB", None)
            else:
                os.environ["FAKE_RAM_GB"] = keep


def launch(home, root, *extra, env=None, first=FIRST):
    args = StrataLaunch.parser().parse_args(
        ["--strata-home", str(home), "22009", str(root / first), *extra])
    return StrataLaunch(args, env={"PATH": os.environ.get("PATH", ""), **(env or {})})


def refused(fn):
    try:
        fn()
    except StrataLaunch.Refusal as exc:
        return str(exc)
    return None


HOME = strata_home()
ROOT_M = model()
WORK = TMP / "scratch"


def section_the_config():
    print("конфиг Strata:")
    L = launch(HOME, ROOT_M, "--mtp", str(ROOT_M / "mtp-q2_0.gguf"), "--name", "qwen3.8-flash-next",
               env={"CARAVAN_CELL_SCRATCH": str(WORK)})
    path = L.config()
    cfg = json.loads(path.read_text())
    check(path == WORK / "strata.json" and L.work == WORK,
          "всё, что делает запуск, лежит в рабочей папке ячейки от скаута (CARAVAN_CELL_SCRATCH)")
    check(cfg["args"] == ["--pack", str(WORK / "pack"), "--native", str(ROOT_M / FIRST),
                          "--ple-gguf", str(ROOT_M / SECOND), "--expert-profile", str(HOME / "data/expert-profile.bin"),
                          "--expert-cache", "auto", "--prefill", "auto", "--spec", "4", "--spec-min-p", "0.5",
                          "--mtp", str(WORK / "mtp/rt"), "--max-context", "131072", "--kv", "int8",
                          "--kv-resident", "32768"],
          "аргументы движка — как их пишет установщик Strata (сверено побайтно на машине с картой): пак, первая часть, "
          "часть с таблицей n-грамм, профиль, черновик MTP, окно 131072, KV int8, KV в ОЗУ")
    check((cfg["exe"], cfg["cwd"], cfg["tokenizer"], cfg["model_name"], cfg["port"], cfg["gpu"], cfg["lib_dirs"],
           cfg["draft_vocab"], cfg["log"])
          == (str(HOME / "engine/strata"), str(HOME), str(WORK / "pack/tokenizer"), "qwen3.8-flash-next", 22009, 0,
              ["/cuda/bin"], "cyrillic", str(WORK / "engine.log")),
          "движок, его библиотеки CUDA из BUILD.json, токенизатор пака, имя, порт, карта 0, лог в рабочей папке")
    check((WORK / "mtp/rt/draft_vocab.bin").read_text() == "cyr",
          "слою черновика положен словарь кириллицы из data/ Strata")
    check(json.loads((WORK / "pack/argv.json").read_text())
          == ["--gguf", str(ROOT_M / FIRST), "--out", str(WORK / "pack")],
          "пак собран из первой части инструментом Strata (iq_pack.py)")
    check(L.server_argv(path) == [sys.executable, str(HOME / "serve/server.py"), "--engine", "strata", "--config",
                                  str(path), "--host", "0.0.0.0", "--port", "22009"],
          "сервер Strata слушает 0.0.0.0 — доска и вход машины достают его по сети")

    L = launch(HOME, ROOT_M, "--work", str(TMP / "plain"), "--context", "16384")
    cfg = json.loads(L.config().read_text())
    check("--mtp" not in cfg["args"] and "--spec" not in cfg["args"] and cfg["model_name"] == "qwen3.8-flash-next",
          "negative: без слоя черновика — без --spec и --mtp; имя по умолчанию — семейства из setup.py")
    check("--kv-resident" not in cfg["args"] and cfg["args"][cfg["args"].index("--kv") + 1] == "int8",
          "negative: окно 16384 (меньше 64K) — KV не уходит в ОЗУ")
    cfg = json.loads(launch(HOME, ROOT_M, "--work", str(TMP / "w8"), "--context", "8192").config().read_text())
    check("--kv" not in cfg["args"], "boundary: окно 8192 — тип KV не передаётся, как у установщика")
    cfg = json.loads(launch(HOME, ROOT_M, "--work", str(TMP / "big"), "--context", "393216",
                            "--vram-reserve-mib", "4096").config().read_text())
    check(cfg["args"][cfg["args"].index("--rope-scaling"):cfg["args"].index("--rope-scaling") + 4]
          == ["--rope-scaling", "yarn", "--rope-scale", "1.5"] and cfg["args"][-2:] == ["--vram-reserve-mib", "4096"],
          "окно дальше 262144 — YaRN с множителем окно/262144; запас VRAM — последним аргументом")
    cfg = json.loads(RamOf(48)(lambda: launch(HOME, ROOT_M, "--work", str(TMP / "ram")).config()).read_text())
    check("--kv-resident" not in cfg["args"],
          "negative: ОЗУ не хватает на KV рядом с экспертами — KV остаётся в видеопамяти, как решает setup.py")
    cfg = json.loads(launch(HOME, ROOT_M, "--work", str(TMP / "g1"), env={"CUDA_VISIBLE_DEVICES": "1"})
                     .config().read_text())
    check(cfg["gpu"] == 1, "карта, закреплённая в окружении ячейки, — карта Strata")


def unsloth_pack(folder, quant="UD-Q4_K_XL", parts=4):
    root = TMP / folder
    root.mkdir(parents=True, exist_ok=True)
    for i in range(1, parts + 1):
        (root / f"Qwen3.8-Flash-Next-{quant}-0000{i}-of-0000{parts}.gguf").write_text("GGUF")
    return root, f"Qwen3.8-Flash-Next-{quant}-00001-of-0000{parts}.gguf"


def section_budget_packs():
    print("~4-битные модели Unsloth — с бюджетом ОЗУ по правилу самой Strata:")
    root, first = unsloth_pack("unsloth-q4")
    cfg = json.loads(RamOf(60)(lambda: launch(HOME, root, "--work", str(TMP / "b1"), "--vram-reserve-mib", "4096",
                                              first=first).config()).read_text())
    args = cfg["args"]
    check(args[-6:] == ["--kv-resident", "32768", "--resident-budget-gib", "34", "--vram-reserve-mib", "4096"],
          f"UD-Q4_K_XL на 60 ГБ ОЗУ: после --kv-resident — --resident-budget-gib 34 (60 − 24 на систему − 2 на KV в ОЗУ), "
          f"до запаса видеопамяти, как пишет установщик (получено {args[-6:]})")
    check("--ple-gguf" not in args and args[args.index("--native") + 1] == str(root / first),
          "часть с таблицей n-грамм не названа движку, когда частей больше двух: он находит её сам с первой (так пишет установщик)")
    check(json.loads((TMP / "b1/pack/argv.json").read_text())
          == ["--gguf", str(root / first), "--out", str(TMP / "b1/pack"), "--compat-bf16"],
          "пак для Unsloth собран с --compat-bf16 (pack_args семейства из setup.py)")
    check(cfg["model_name"] == "qwen3.8-flash-next-unsloth", "имя по умолчанию — семейства Unsloth")
    one = json.loads(RamOf(60)(lambda: launch(HOME, root, "--work", str(TMP / "b2"), "--context", "16384", first=first).config()).read_text())
    check(one["args"][-2:] == ["--resident-budget-gib", "36"] and "--kv-resident" not in one["args"],
          "окно 16384: KV в ОЗУ не уходит и из бюджета не вычитается — 60 − 24 = 36")
    big = json.loads(RamOf(100)(lambda: launch(HOME, root, "--work", str(TMP / "b3"), first=first).config()).read_text())
    check("--resident-budget-gib" in big["args"] and big["args"][big["args"].index("--resident-budget-gib") + 1] == "71",
          "boundary: ОЗУ много — бюджет не больше самих экспертов (77 ГБ / 1.0737 = 71)")
    tiny = json.loads(RamOf(28)(lambda: launch(HOME, root, "--work", str(TMP / "b4"), "--context", "16384", first=first).config()).read_text())
    check(tiny["args"][-2:] == ["--resident-budget-gib", "8"], "boundary: ОЗУ мало — бюджет не меньше 8 (правило Strata)")
    three, first3 = unsloth_pack("unsloth-iq4", "UD-IQ4_XS", 3)
    cfg3 = json.loads(RamOf(60)(lambda: launch(HOME, three, "--work", str(TMP / "b5"), first=first3).config()).read_text())
    check("--ple-gguf" not in cfg3["args"] and cfg3["args"][cfg3["args"].index("--resident-budget-gib") + 1] == "34",
          "UD-IQ4_XS в три части — так же: бюджет 34, таблицу n-грамм движок находит сам")
    plain = json.loads(launch(HOME, ROOT_M, "--work", str(TMP / "b6")).config().read_text())
    check("--resident-budget-gib" not in plain["args"],
          "negative: IQ2_XS бюджета не знает — все эксперты в ОЗУ, флага нет")
    old = strata_home("no-budget", setup=SETUP.replace("def resident_budget_gib", "def resident_budget_was"))
    check(refused(lambda: launch(old, ROOT_M, "--work", str(TMP / "b7")).config())
          == "this Strata has no setup.resident_budget_gib — the caravan's launcher knows v0.1.42",
          "negative: в setup.py нет правила бюджета — отказ с его именем, а не догадка о числе")
    old = strata_home("no-kv-ram", setup=SETUP.replace("def kv_streaming_ram_gb", "def kv_streaming_ram_was"))
    check(refused(lambda: launch(old, ROOT_M, "--work", str(TMP / "b8")).config())
          == "this Strata has no setup.kv_streaming_ram_gb — the caravan's launcher knows v0.1.42",
          "negative: нет правила, сколько ОЗУ берёт KV, — отказ с его именем: бюджет без него был бы неверен")


def section_the_engine_knows_the_card():
    print("движок собран под карту ячейки:")
    def start(build, arch, name, env=None):
        home = strata_home(name, build=build)
        L = launch(home, ROOT_M, "--work", str(TMP / name), env=env)
        L.card_arch = lambda gpu: arch
        return refused(L.config)
    sm120 = {"cuda_dirs": ["/cuda/bin"], "archs": [120]}
    both = {"cuda_dirs": ["/cuda/bin"], "archs": [86, 120]}
    msg = start(sm120, 86, "arch1")
    check(msg == "Strata's engine has code for sm_120 and GPU 0 is sm_86: pin the cell to a card the engine has code for, "
                 "or build it for this card too (Strata's setup.sh --gpus <the cards>)",
          f"engine для RTX 5090 (120) и ячейка на RTX 3090 (86): отказ до запуска, с картой, архитектурами и тем, что сделать (получено {msg})")
    check(start(sm120, 120, "arch2") is None, "negative: карта той же архитектуры, что движок, — запуск идёт")
    check(start(both, 86, "arch3") is None and start(both, 120, "arch4") is None,
          "negative: движок собран под обе архитектуры — запуск идёт на любой из карт")
    check(start({**sm120, "ptx": True}, 130, "arch5") is None and start({**sm120, "ptx": True}, 86, "arch6") is not None,
          "boundary: с PTX движок идёт и на карте новее самой новой из собранных, а на старше — нет")
    check(start({"cuda_dirs": ["/cuda/bin"]}, 86, "arch7") is None, "negative: сборка не назвала архитектуры (BUILD.json без archs) — не отказываем")
    check(start(sm120, None, "arch8") is None, "negative: nvidia-smi карту не назвал — не отказываем: догадка хуже отказа")
    msg = start(both, 75, "arch9", env={"CUDA_VISIBLE_DEVICES": "2"})
    check(msg is not None and "GPU 2 is sm_75" in msg and "sm_86, sm_120" in msg, f"номер карты — закреплённая в окружении ячейки (получено {msg})")
    print("как читается compute_cap:")
    keep = strata_launch.subprocess.run
    def smi(out, rc=0):
        return lambda *a, **k: strata_launch.subprocess.CompletedProcess(a[0], rc, stdout=out, stderr="")
    L = launch(HOME, ROOT_M)
    try:
        strata_launch.subprocess.run = smi("0, 8.6\n1, 12.0\n")
        got = [L.card_arch(0), L.card_arch(1), L.card_arch(2)]
        strata_launch.subprocess.run = smi("0, [N/A]\ngarbage\n")
        junk = L.card_arch(0)
        strata_launch.subprocess.run = smi("0, 8\n")
        no_dot = L.card_arch(0)
        def missing(*a, **k):
            raise FileNotFoundError("nvidia-smi")
        strata_launch.subprocess.run = missing
        gone = L.card_arch(0)
    finally:
        strata_launch.subprocess.run = keep
    check(got == [86, 120, None] and junk is None and no_dot is None and gone is None,
          f"8.6 → 86, 12.0 → 120; карты нет, ответ не число, число без точки («8»), nvidia-smi нет — None (получено {got}, {junk}, {no_dot}, {gone})")


def section_refusals():
    print("отказы:")
    check(refused(lambda: launch(HOME, ROOT_M, "--work", str(TMP / "r1"), env={"CUDA_VISIBLE_DEVICES": "0,1"})
                  .config()) == "Strata runs on one card; CUDA_VISIBLE_DEVICES is '0,1'",
          "negative: две карты — отказ: слой карт Strata здесь не настраивается")
    check(refused(lambda: launch(HOME, ROOT_M, "--work", str(TMP / "r2"), env={"CUDA_VISIBLE_DEVICES": ""})
                  .config()) == "Strata runs on one card; CUDA_VISIBLE_DEVICES is ''",
          "negative: ячейка закреплена на ЦП — отказ: Strata без видеокарты не работает")
    lonely = model("lonely", second_text=None)
    check(refused(lambda: launch(HOME, lonely, "--work", str(TMP / "r3")).config())
          == f"the model's file is not here: {lonely / SECOND}",
          "negative: второй части рядом нет — отказ с её путём")
    odd = TMP / "odd"
    odd.mkdir(exist_ok=True)
    (odd / "my-model.gguf").write_text("GGUF")
    check(refused(lambda: launch(HOME, odd, "--work", str(TMP / "r4"), first="my-model.gguf").config())
          == "Strata does not know the file my-model.gguf: it runs the published Qwen3.8-Flash-Next GGUFs, by their names",
          "negative: файл с чужим именем — отказ: Strata знает модели по опубликованным именам")
    check(refused(lambda: RamOf(40)(lambda: launch(HOME, ROOT_M, "--work", str(TMP / "r6")).config()))
          == "IQ2_XS needs Strata's low-RAM mode on this machine (40 GB of RAM), which the caravan's Strata cell "
             "does not set up yet",
          "negative: ОЗУ меньше, чем экспертам нужно, — отказ: режим «мало ОЗУ» здесь не собирается")
    no_ple = model("nople", second_text="GGUF")
    check(refused(lambda: launch(HOME, no_ple, "--work", str(TMP / "r7")).config())
          == "the model has no per_layer_token_embd tensor — is it a Qwen3.8-Flash-Next GGUF?",
          "negative: ни в одной части нет таблицы n-грамм — это не модель Strata")
    bare = strata_home("bare", engine=False)
    check(refused(lambda: launch(bare, ROOT_M, "--work", str(TMP / "r8")).config())
          == f"Strata's engine is not built: {bare / 'engine/strata'} — run Strata's setup.sh",
          "negative: движок не собран — отказ с путём и тем, что сделать")
    check(refused(lambda: launch(TMP / "nowhere", ROOT_M, "--work", str(TMP / "r9")).config())
          == f"no Strata installed at {TMP / 'nowhere'} (setup.py and engine/BUILD.json) — install it with "
             "Strata's setup.sh",
          "negative: Strata не установлена — отказ с подсказкой")
    old = strata_home("old", setup=SETUP.replace("def kv_streaming_wanted", "def kv_streaming_was"))
    check(refused(lambda: launch(old, ROOT_M, "--work", str(TMP / "r10")).config())
          == "this Strata has no setup.kv_streaming_wanted — the caravan's launcher knows v0.1.42",
          "negative: в setup.py нет нужного правила — отказ с его именем, а не догадка")
    check(refused(lambda: launch(HOME, ROOT_M, "--work", str(TMP / "r11"), "--mtp", str(TMP / "none.gguf")).config())
          == f"the draft layer's file is not here: {TMP / 'none.gguf'}",
          "negative: файла черновика нет — отказ")
    code = strata_launch.main(["--strata-home", str(TMP / "nowhere"), "22009", str(ROOT_M / FIRST)])
    check(code == 1, "отказ — код выхода 1 и одна строка в логе ячейки")
    check(strata_launch.main(["--strata-home", str(HOME), "22009", str(ROOT_M / FIRST), "--context", "0"]) == 2,
          "negative: окно 0 — код 2, до чтения Strata")


def section_kept_with_the_cache():
    print("с кэшем — пак прошлого запуска:")
    home = strata_home("kept")
    root = model("kept-model")
    work = TMP / "kept-work"
    runs = lambda: (home / "runs.txt").read_text().count("pack") if (home / "runs.txt").exists() else 0  # noqa: E731
    mtp = ["--mtp", str(root / "mtp-q2_0.gguf")]
    first = launch(home, root, *mtp, "--work", str(work)).config()
    again = json.loads(launch(home, root, *mtp, "--work", str(work)).config().read_text())
    check(runs() == 1 and again["args"][again["args"].index("--pack") + 1] == str(work / "pack")
          and (work / "made.json").is_file() and first == work / "strata.json",
          "второй запуск той же модели берёт пак и черновик прошлого: 2,3 ГБ не пишутся на диск снова "
          "(ячейка с кэшем держит рабочую папку, 2026-10-13)")
    launch(home, root, *mtp, "--work", str(work), "--draft-vocab", "en").config()
    check(runs() == 2 and (work / "mtp/rt/draft_vocab.bin").read_text() == "en",
          "negative: другой словарь черновика — пак и черновик собраны заново")
    os.utime(root / FIRST, ns=(1, 1))
    launch(home, root, *mtp, "--work", str(work), "--draft-vocab", "en").config()
    check(runs() == 3, "negative: файл модели другой (время изменилось) — собрано заново")
    (work / "pack/native_experts.txt").unlink()
    launch(home, root, *mtp, "--work", str(work), "--draft-vocab", "en").config()
    check(runs() == 4, "negative: пак неполон — собран заново, а не взят наполовину")
    launch(home, root, "--work", str(work), "--draft-vocab", "en").config()
    check(runs() == 5, "negative: черновик убрали — заново: прошлый запуск делал другое")


def section_becomes_the_server():
    print("запуск становится сервером:")
    seen = {}
    keep = os.execve
    os.execve = lambda path, argv, env: seen.update(path=path, argv=argv, env=env)
    cwd = os.getcwd()
    try:
        launch(HOME, ROOT_M, env={"CARAVAN_CELL_SCRATCH": str(TMP / "exec"), "MARK": "1"}).start()
    finally:
        os.execve = keep
        os.chdir(cwd)
    check(seen.get("path") == sys.executable and seen.get("argv", [])[1:3] == [str(HOME / "serve/server.py"),
                                                                                 "--engine"]
          and seen.get("env", {}).get("MARK") == "1",
          "процесс ячейки сам становится сервером Strata (exec), с окружением ячейки: скаут следит за ним, "
          "а не за родителем, который ждал бы сервер")


def main():
    section_the_config()
    section_budget_packs()
    section_the_engine_knows_the_card()
    section_refusals()
    section_kept_with_the_cache()
    section_becomes_the_server()
    if _fail:
        print(f"\nFAILED ({len(_fail)}):")
        for msg in _fail:
            print("  -", msg)
        return 1
    print("\nstrata launch OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
