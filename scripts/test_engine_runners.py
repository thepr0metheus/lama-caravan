#!/usr/bin/env python3
"""Снимок раннеров ollama и lmstudio — ячейка, чья модель живёт в движке рядом.

Раннер отвечает на вопросы реестра о ячейке движка; пинится ЗНАЧЕНИЯМИ:

  * строка запуска — сервер ячейки-движка с портом ячейки, движком, портом
    движка и моделью; имя модели экранировано (оно пришло от движка);
  * порт движка — из конфига, иначе свой у каждого движка; не порт — отказ;
  * без модели не собирается и не запускается — отказ словами;
  * вкладки в редакторе нет (editorTab: false), подпись — имя движка;
  * скауту уезжают cell_base.py и сервер, и отпечаток исходника у
    контроллера совпадает с тем, что сообщит ячейка (иначе на ней вечно
    горел бы «устарел»).

Запуск: python3 scripts/test_engine_runners.py
"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from caravan.admin.cell_assets import assets_for_runner, server_stamp  # noqa: E402
from caravan.common.errors import AppError  # noqa: E402
from caravan.domain import runner as r  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def refusal(fn):
    try:
        fn()
    except AppError as exc:
        return str(exc)
    return None


oll, lms = r.get("ollama"), r.get("lmstudio")

print("реестр:")
ids = [x.id for x in r.REGISTRY]
check(ids[-2:] == ["ollama", "lmstudio"], "оба раннера в реестре, после раннеров каравана")
check(type(oll).__name__ == "OllamaRunner" and type(lms).__name__ == "LmStudioRunner", "у каждого свой класс")
check(r.for_config({"RUNNER": "Ollama"}) is oll and r.runner_id({"RUNNER": " LMSTUDIO "}) == "lmstudio",
      "RUNNER читается без оглядки на регистр и пробелы")
d = oll.as_dict()
check(d["editorTab"] is False and lms.as_dict()["editorTab"] is False and r.get("whisper").as_dict()["editorTab"] is True,
      "вкладки в редакторе нет — ячейку движка делают на шаге резерва; у раннеров каравана есть")
check(d["engineCell"] is True and lms.as_dict()["engineCell"] is True
      and [x.id for x in r.REGISTRY if x.as_dict()["engineCell"]] == ["ollama", "lmstudio"],
      "engineCell — у двух раннеров движков и ни у кого больше: доска берёт список движков отсюда, а не держит свой")
check((d["labelKey"], lms.as_dict()["labelKey"], d["benefitsKey"]) == ("runnerOllama", "runnerLmStudio", ""),
      "подпись — имя движка; пояснения нет: его показывает только вкладка, которой нет")
check(d["modelField"] == "ENGINE_MODEL" and d["artifacts"] == ["engine-model"] and d["health"] == "/health"
      and d["commandPath"] is True,
      "модель — в ENGINE_MODEL; свой вид артефакта (файлы пикера его не зовут); здоровье на /health; путь команды")

print("строка запуска:")
check(oll.command({"ENGINE_MODEL": "qwen2.5:0.5b", "ENGINE_PORT": "11434"})
      == 'bash $HOME/run_engine.sh "$PORT" ollama 11434 qwen2.5:0.5b',
      "Ollama: сервер ячейки-движка, порт ячейки, движок, порт движка, модель")
check(lms.command({"ENGINE_MODEL": "google/gemma-4-e4b"})
      == 'bash $HOME/run_engine.sh "$PORT" lmstudio 1234 google/gemma-4-e4b',
      "LM Studio без ENGINE_PORT — его собственный порт 1234")
check(oll.command({"ENGINE_MODEL": "qwen2.5:0.5b"}).endswith(" ollama 11434 qwen2.5:0.5b"),
      "Ollama без ENGINE_PORT — 11434")
check(oll.command({"ENGINE_MODEL": "my model;rm -rf ~", "ENGINE_PORT": 11500})
      == """bash $HOME/run_engine.sh "$PORT" ollama 11500 'my model;rm -rf ~'""",
      "имя модели пришло от движка — экранировано для оболочки; порт из конфига числом")
check(oll.prepare({"ENGINE_MODEL": "m"}) == oll.command({"ENGINE_MODEL": "m"}), "prepare — та же строка, дополнять нечего")
check(oll.artifact_label({"ENGINE_MODEL": "qwen2.5:0.5b"}) == "qwen2.5:0.5b" and oll.model_ref({"ENGINE_MODEL": " x "}) == "x",
      "в коротком списке ячейка называется своей моделью")

print("отказы:")
check(refusal(lambda: oll.command({})) == "ENGINE_MODEL is required for a ollama cell",
      "negative: без модели строку не собрать — отказ словами")
check(refusal(lambda: lms.preflight_start({"ENGINE_MODEL": ""})) == "lmstudio cell has no model — reserve it with one",
      "negative: без модели старт отказан до попытки, с подсказкой, где её дают")
check(lms.preflight_start({"ENGINE_MODEL": "m"}) is None, "с моделью старт не отказан")
check(refusal(lambda: oll.command({"ENGINE_MODEL": "m", "ENGINE_PORT": "eleven"})) == "ENGINE_PORT is not a port: 'eleven'",
      "negative: порт движка не число — отказ")
check(refusal(lambda: oll.command({"ENGINE_MODEL": "m", "ENGINE_PORT": 70000})) == "ENGINE_PORT is not a port: 70000",
      "boundary: порт за 65535 — отказ")
check(refusal(lambda: oll.command({"ENGINE_MODEL": "m", "ENGINE_PORT": "0"})) == "ENGINE_PORT is not a port: 0",
      "boundary: порт 0 — отказ, а не молчаливая подстановка порта по умолчанию (догадка вместо отказа)")
check(refusal(lambda: oll.command({"ENGINE_MODEL": "m", "ENGINE_PORT": ""})) is None,
      "пустой ENGINE_PORT — не указан: порт движка по умолчанию")

print("что уезжает скауту:")
check(assets_for_runner("ollama") == ("run_engine.sh", "cell_base.py", "engine_cell_server.py") == assets_for_runner("LMStudio"),
      "обоим раннерам — лаунчер, база и сервер ячейки-движка")
launcher = (ROOT / "cells" / "run_engine.sh").read_text()
check(launcher.startswith("#!/bin/bash\n") and 'exec python3 "$HOME/engine_cell_server.py" "$@"' in launcher,
      "лаунчер только запускает сервер: стандартная библиотека, без venv, аргументы как есть")
import re as _re
check(_re.search(r"\brun_([a-z0-9_]+)\.sh\b", oll.command({"ENGINE_MODEL": "m"})).group(1) == "engine",
      "строка называет лаунчер run_engine.sh — по нему скаут находит, какие файлы привезти в $HOME (регулярка скаута "
      "LAUNCHER_RE); без него сервер на машину не доехал бы")
from caravan.admin.cell_assets import cell_assets_manifest  # noqa: E402
_man = cell_assets_manifest()
_owner = next((rid for rid, names in _man["runners"].items() if "run_engine.sh" in (names or [])), "")
check(_owner in ("ollama", "lmstudio") and _man["runners"][_owner] == list(assets_for_runner("lmstudio"))
      and _man["assets"]["run_engine.sh"]["executable"] is True,
      "манифест: скаут берёт первый раннер с этим лаунчером — у обоих движков файлы те же; лаунчер ложится исполняемым")
spec = importlib.util.spec_from_file_location("cell_base_probe", ROOT / "cells" / "cell_base.py")
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
reported = base._source_stamp(str(ROOT / "cells" / "engine_cell_server.py"))
check(len(server_stamp("ollama")) == 12 and server_stamp("ollama") == reported == server_stamp("lmstudio"),
      "отпечаток исходника у контроллера = тот, что сообщит ячейка: иначе «устарел» горел бы на ней всегда")

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m_ in _fail:
        print("  - " + m_)
    sys.exit(1)
print("engine runners OK: строка запуска, отказы, вкладки нет, файлы и отпечаток — значениями")
