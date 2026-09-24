#!/usr/bin/env python3
"""Ячейка скаута запускается так же, как ячейка контроллера.

Перед переносом ячеек машины контроллера на её скаут (шаг 6.8) каждую
сравнили: что написано в start.sh и что запустил бы скаут. Команды совпали
у всех, кроме двух различий — оба теперь закрыты:

* окружение движка. CPU-ячейка (N_GPU_LAYERS 0) в start.sh прячет карту
  (CUDA_VISIBLE_DEVICES=""), иначе сборка llama.cpp с CUDA будит карту и
  падает от нехватки памяти, когда её занял сосед. Скаут запускал ту же
  ячейку с картой на виду. Правило теперь у раннера (`Runner.launch_env`):
  start.sh экспортирует его, запрос скауту несёт его как `env`;
* YaRN. Контекст выше родного окна модели сам включает рецепт YaRN — но
  только там, где контроллер читает заголовок модели, а в аргументах для
  скаута вместо пути стоит плейсхолдер, и рецепт молча пропадал: ячейка
  :22007 (180000 при родных 131072) на скауте потеряла бы окно. Теперь
  заголовок читается там, где файл есть у контроллера (`header_path`).

Пинится значениями: правило окружения, запрос скауту, рецепт YaRN из копии
контроллера (своей и библиотечной) и итог — одна и та же строка запуска.
Хранилище, места моделей и чтение заголовка подменены.

Запуск: python3 scripts/test_scout_launch_parity.py
"""
import shlex
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import caravan.admin.models as models_mod  # noqa: E402
from caravan.admin import fleet_clients as fc  # noqa: E402
from caravan.admin.config_builder import CONFIG_BEGIN, build_local_llama_command  # noqa: E402
from caravan.admin.launch import command_cell_env_exports, export_lines, render_launch_script  # noqa: E402
from caravan.admin.model_locator import Locations  # noqa: E402
from caravan.domain.runner import LlamaServerRunner, for_config  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


TMP = Path(tempfile.mkdtemp(prefix="caravan-parity-"))
MODELS = TMP / "models"
LIBRARY = TMP / "library"
for rel, root in (("org/m.gguf", MODELS), ("org/mmproj.gguf", MODELS), ("org/draft.gguf", MODELS),
                  ("org/n.gguf", LIBRARY)):
    (root / rel).parent.mkdir(parents=True, exist_ok=True)
    (root / rel).write_bytes(b"GGUF")
YARN = ["--rope-scaling", "yarn", "--rope-scale", "1.38", "--yarn-orig-ctx", "131072",
        "--override-kv", "gemma4.context_length=int:180000"]


class Header:
    """The model's header, as this controller reads it: a native window of
    131072 and the gemma4 architecture, for any file; every read written down."""

    def __init__(self):
        self.read = []

    def __enter__(self):
        self.keep = models_mod.read_gguf_metadata_cached, models_mod.extract_runtime_meta
        models_mod.read_gguf_metadata_cached = lambda path: self.read.append(str(path)) or {"path": str(path)}
        models_mod.extract_runtime_meta = lambda meta: {"contextLength": 131072, "architecture": "gemma4"}
        return self

    def __exit__(self, *exc):
        models_mod.read_gguf_metadata_cached, models_mod.extract_runtime_meta = self.keep
        return False


def llama(**over):
    return {"MODEL_FILE": "org/m.gguf", "LLAMA_MODELS_DIR": str(MODELS), "PORT": "22007",
            "CTX_SIZE": "180000", "N_GPU_LAYERS": "999", **over}


def locations(library=False):
    libs = [{"id": "lib", "name": "shelf", "path": str(LIBRARY), "state": "ok",
             "files": [{"path": "org/n.gguf", "size": 4}]}] if library else []
    return Locations(libs)


def payload(cfg, library=False, model=None):
    keep = fc.topology_store, fc.current_locations
    fc.topology_store = lambda: {"hosts": {"box-a": {"id": "box-a"}}}
    fc.current_locations = lambda wait=False: locations(library)
    try:
        return fc.scout_start_payload({"hostId": "box-a", "port": int(cfg.get("PORT") or 22007),
                                       "config": dict(cfg),
                                       "modelPath": cfg.get("MODEL_FILE", "") if model is None else model})
    finally:
        fc.topology_store, fc.current_locations = keep


def section_the_engines_environment():
    print("окружение движка — одно правило:")
    runner = LlamaServerRunner()
    check(runner.launch_env({"N_GPU_LAYERS": "0"}) == {"CUDA_VISIBLE_DEVICES": ""},
          "CPU-ячейка (N_GPU_LAYERS 0) не видит карт: CUDA_VISIBLE_DEVICES пустой")
    check(runner.launch_env({"N_GPU_LAYERS": 0}) == {"CUDA_VISIBLE_DEVICES": ""}
          and runner.launch_env({"N_GPU_LAYERS": " 0 "}) == {"CUDA_VISIBLE_DEVICES": ""},
          "boundary: 0 числом и «0» в пробелах — тоже CPU")
    for why, cfg in (("999", {"N_GPU_LAYERS": "999"}), ("auto", {"N_GPU_LAYERS": "auto"}),
                     ("пусто", {"N_GPU_LAYERS": ""}), ("поля нет", {}), ("None", {"N_GPU_LAYERS": None}),
                     ("«00»", {"N_GPU_LAYERS": "00"}), ("конфига нет", None)):
        check(runner.launch_env(cfg) == {}, f"negative: слои на карте ({why}) — окружения сверх обычного нет")
    for rid in ("whisper", "vllm", "custom", "transcribe"):
        check(for_config({"RUNNER": rid}).launch_env({"RUNNER": rid, "N_GPU_LAYERS": "0"}) == {},
              f"negative: {rid} карту так не прячет — правило только у llama-server")
    script = render_launch_script(llama(N_GPU_LAYERS="0"))
    lines = script.splitlines()
    check(lines.count('export CUDA_VISIBLE_DEVICES=""') == 1
          and lines.index('export CUDA_VISIBLE_DEVICES=""') < lines.index(CONFIG_BEGIN),
          "start.sh CPU-ячейки экспортирует его один раз, в шапке — до блока конфига")
    check("CUDA_VISIBLE_DEVICES" not in render_launch_script(llama()),
          "negative: start.sh ячейки на карте его не трогает")


def section_one_way_to_export():
    print("экспорт — одно написание для обеих строк запуска:")
    got = export_lines([("A", 'say "hi"'), ("B", "C:\\dir"), ("C", "$HOME/x"), ("D", ""), ("E", 7)])
    check(got == ['export A="say \\"hi\\""', 'export B="C:\\\\dir"', 'export C="$HOME/x"', 'export D=""',
                  'export E="7"'],
          f"в двойных кавычках: кавычка и обратная косая экранированы, $ раскрывается, пустое — \"\" (got {got})")
    check(command_cell_env_exports("A=1, B = two\n# C=3") == ['export A="1"', 'export B="two"'],
          "ENV командной ячейки идёт через него же (разбор — Runner.env_pairs)")
    check(export_lines([]) == [], "negative: нечего экспортировать — ни строки")


def section_the_scouts_start():
    print("запрос старта ячейки скаута:")
    check(payload(llama(N_GPU_LAYERS="0"))["env"] == {"CUDA_VISIBLE_DEVICES": ""},
          "CPU-ячейка: в запросе то же окружение, что экспортирует start.sh")
    check(payload(llama())["env"] == {}, "negative: ячейка на карте — окружение пустое, но названо")
    check("env" not in payload({"RUNNER": "whisper", "PORT": "22024"}),
          "negative: у командной ячейки окружение в её строке запуска, отдельного env нет")


def section_yarn_for_a_scouts_cell():
    print("YaRN у ячейки скаута:")
    with Header() as header:
        got = payload(llama())
    args = got["args"]
    check(args[-len(YARN):] == YARN,
          f"контекст выше родного окна — весь рецепт YaRN, как у ячейки контроллера (got {args[-8:]})")
    check(header.read == [str(MODELS / "org/m.gguf")],
          "заголовок прочитан из копии контроллера — того файла, что скаут прочтёт на месте или скачает")
    check(args[args.index("--model") + 1] == "{{MODEL_PATH}}" and str(MODELS) not in " ".join(args),
          "negative: путь контроллера в аргументы не попал — модель скаут подставит сам")
    with Header():
        check("--rope-scaling" not in payload(llama(CTX_SIZE="100000"))["args"],
              "negative: контекст в родном окне — YaRN нет")
        missing = payload(llama(MODEL_FILE="org/absent.gguf"))
    check("--rope-scaling" not in missing["args"] and missing["modelPath"] == "org/absent.gguf",
          "negative: файла у контроллера нет — рецепта нет, как было (остаётся EXTRA_ARGS)")
    with Header():
        explicit = payload(llama(ROPE_SCALING="linear"))["args"]
    check(explicit.count("--rope-scaling") == 1 and explicit[explicit.index("--rope-scaling") + 1] == "linear"
          and "--yarn-orig-ctx" in explicit,
          "явный ROPE_SCALING сильнее: метод оператора, остальное рецепт дополняет")
    with Header() as header:
        lib = payload(llama(MODEL_FILE="org/n.gguf"), library=True)
    check(header.read == [str(LIBRARY / "org/n.gguf")] and lib["args"][-len(YARN):] == YARN
          and "--no-mmap" in lib["args"],
          "модель из библиотеки: заголовок из библиотеки, рецепт тот же, и чтение без отображения")


def section_one_start_line():
    print("одна и та же строка запуска:")
    cfg = llama(N_GPU_LAYERS="0", MMPROJ_FILE="org/mmproj.gguf", SPEC_DRAFT_MODEL_FILE="org/draft.gguf",
                SPEC_TYPE="draft-mtp")
    with Header():
        here = build_local_llama_command(cfg, locations=locations())[1:]
        script = render_launch_script(cfg, locations=locations())
        got = payload(cfg)
    hints = got["inPlace"]
    subst = {"{{MODEL_PATH}}": hints["org/m.gguf"]["path"], "{{MMPROJ_PATH}}": hints["org/mmproj.gguf"]["path"],
             "{{SPEC_PATH}}": hints["org/draft.gguf"]["path"]}
    there = [subst.get(a, a) for a in got["args"]]
    check(there == here, "аргументы скаута с подставленными путями — те же, что у llama-server в start.sh")
    exports = dict(line[len("export "):].split("=", 1) for line in script.splitlines()
                   if line.startswith("export ") and not line.startswith(("export LD_LIBRARY_PATH", "export PATH=")))
    check({k: shlex.split(v)[0] if shlex.split(v) else "" for k, v in exports.items()} == got["env"]
          == {"CUDA_VISIBLE_DEVICES": ""},
          "окружение движка то же, что экспортирует start.sh")


def main():
    section_the_engines_environment()
    section_one_way_to_export()
    section_the_scouts_start()
    section_yarn_for_a_scouts_cell()
    section_one_start_line()
    if _fail:
        print(f"\nFAILED ({len(_fail)}):")
        for m in _fail:
            print("  - " + m)
        return 1
    print("\nscout launch parity OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
