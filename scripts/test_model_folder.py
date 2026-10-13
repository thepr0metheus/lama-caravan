#!/usr/bin/env python3
"""Value snapshot: GET /api/models/folder — a model that is a folder, listed for a scout.

A scout takes a model only through the controller (the owner, 2026-10-12: no scout gets rights
to the share the models live on), and the download serves a file: a folder model — a
checkpoint, a whisper cache, a robot policy — could not reach a scout at all. The listing names
each file with its size, to be fetched through GET /api/models/download, and each link inside
the folder, to be made again.

Pinned by value on a real tree: a checkpoint keeps its subfolders; a Hugging Face cache keeps
its snapshots/ links; a download still landing is left out; a link to a file elsewhere in the
models directory is that file; a link out of the models directory refuses the folder; the
statuses (400 no path, 403 outside, 404 no folder or a file, 413 too many files); the fleet
token may call the route.

Run: python3 scripts/test_model_folder.py
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from caravan.admin.model_folder import ModelFolder  # noqa: E402
from caravan.admin.route_access import RouteAccess  # noqa: E402
from caravan.common.errors import AppError  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def put(root, rel, size):
    path = Path(root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    return path


def link(root, rel, target):
    path = Path(root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(target, path)


EMPTY = {"path": "", "files": [], "links": [], "size": -1}


def listed(models, rel):
    """The listing, or EMPTY when it refuses: a pin whose listing breaks fails as itself."""
    try:
        return ModelFolder(models, rel).listing()
    except AppError as exc:
        print(f"  --  {rel}: {exc}")
        return EMPTY


def refused(models, rel, cls=ModelFolder):
    try:
        cls(models, rel).listing()
    except AppError as exc:
        return exc.status, str(exc)
    return None, ""


with tempfile.TemporaryDirectory() as tmp:
    models = Path(tmp) / "models"
    # A checkpoint with a subfolder the runtime reads, a download still landing, and a link to a
    # file another model folder holds.
    put(models, "GR00T/nvidia/BF16/config.json", 10)
    put(models, "GR00T/nvidia/BF16/model-00001-of-00002.safetensors", 100)
    put(models, "GR00T/nvidia/BF16/experiment_cfg/conf.yaml", 5)
    put(models, "GR00T/nvidia/BF16/extra.safetensors.part", 7)
    put(models, "GR00T/nvidia/BF16/extra.safetensors.part.json", 3)
    put(models, "shared/tokenizer.json", 33)
    link(models, "GR00T/nvidia/BF16/tokenizer.json", "../../../shared/tokenizer.json")
    # A Hugging Face cache: snapshots point at blobs.
    put(models, "whisper/models--S--small/blobs/abc", 50)
    put(models, "whisper/models--S--small/refs/main", 4)
    link(models, "whisper/models--S--small/snapshots/h1/model.bin", "../../blobs/abc")
    link(models, "whisper/models--S--small/snapshots/h2", "h1")
    # Refusals: a link out of the models directory, a file, a missing folder.
    put(Path(tmp), "outside/secret.txt", 9)
    link(models, "leaky/model/link.bin", str(Path(tmp) / "outside" / "secret.txt"))
    put(models, "plain/model.gguf", 12)

    print("чекпойнт с подпапкой:")
    got = listed(models, "GR00T/nvidia/BF16/")
    check(got["path"] == "GR00T/nvidia/BF16", "путь назван без косой черты в конце")
    check([f["path"] for f in got["files"]] == ["config.json", "model-00001-of-00002.safetensors",
                                                "tokenizer.json", "experiment_cfg/conf.yaml"],
          f"файлы по порядку, подпапка experiment_cfg/ сохранена: {[f['path'] for f in got['files']]}")
    check([f["size"] for f in got["files"]] == [10, 100, 33, 5], "размеры файлов — настоящие")
    check(got["size"] == 148, f"размер папки — сумма файлов: {got['size']}")
    check(not any(f["path"].endswith((".part", ".part.json")) for f in got["files"]),
          "negative: загрузка в пути (.part, .part.json) — не часть модели")
    check(got["links"] == [], "ссылка на файл в другой папке моделей — это сам файл, не ссылка")

    print("кэш Hugging Face:")
    got = listed(models, "whisper/models--S--small")
    check([f["path"] for f in got["files"]] == ["blobs/abc", "refs/main"], f"файлы кэша: {got['files']}")
    check(got["links"] == [{"path": "snapshots/h2", "target": "h1"},
                           {"path": "snapshots/h1/model.bin", "target": "../../blobs/abc"}],
          f"ссылки внутри папки — ссылками, с целью как есть: {got['links']}")
    check(got["size"] == 54, "ссылка в размер не входит: байты лежат в blobs/")

    print("отказы:")
    status, said = refused(models, "leaky/model")
    check(status == 409 and "outside the models directory" in said, f"ссылка за пределы папки моделей — 409: {said}")
    check(refused(models, "")[0] == 400, "пустой путь — 400")
    check(refused(models, "../outside")[0] == 403, "путь за пределы папки моделей — 403")
    check(refused(models, "plain/model.gguf")[0] == 404, "файл, а не папка — 404")
    check(refused(models, "no/such/folder")[0] == 404, "нет такой папки — 404")

    class Small(ModelFolder):
        MAX_FILES = 3

    check(refused(models, "GR00T/nvidia/BF16", Small)[0] == 413, "больше MAX_FILES файлов — 413, не модель")
    check(refused(models, "whisper/models--S--small", Small)[0] is None, "negative: 2 файла при пределе 3 — список")

print("доступ:")
access = RouteAccess()
check(access.kind("GET", "/api/models/folder") == RouteAccess.MACHINE, "скаут зовёт адрес токеном флота")
check(access.kind("GET", "/api/models/download") == RouteAccess.MACHINE, "как и загрузку файла")

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail:
        print("  - " + m)
    sys.exit(1)
print("model folder snapshot holds")
