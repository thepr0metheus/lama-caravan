#!/usr/bin/env python3
"""Value snapshot: what /api/hf/local-check says we have of one repository.

This disk: every GGUF under <model>/<author>/, by name, with size and time; a
name in two quant folders is the newer one. Libraries: a move carries a
model's files to a library (a NAS share), and /hf marked them as not
downloaded (found live, 2026-09-17). Now libraryFiles names each file a usable
library holds under the same folder, with the library, size and time; one
entry per library holding it. Only that repository's folder counts — not a
folder whose name merely starts the same, not another author's — and only
GGUF files. A library that is not there holds nothing (model_locator.py
decides that), and a locator that cannot be asked leaves the answer about this
disk intact with no library files, instead of failing the request.

Run: python3 scripts/test_hf_local_check.py
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import caravan.admin.hf as hf  # noqa: E402
import caravan.admin.model_locator as locator  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def library(store_id, name, state, files):
    return {"id": store_id, "name": name, "state": state, "path": f"/mnt/{store_id}",
            "files": [{"path": p, "size": s, "mtime": m} for p, s, m in files]}


LIBRARIES = [
    library("lib-a", "lama-caravan-models", "ok", [
        ("gemma-4-31B-it-GGUF/unsloth/Q5_K_M/gemma-4-31B-it-Q5_K_M.gguf", 20_200, 1_780_000_000),
        ("gemma-4-31B-it-GGUF/unsloth/default/mmproj-BF16.gguf", 1_100, 1_780_000_001),
        ("gemma-4-31B-it-GGUF/unsloth/Q8_0/gemma-4-31B-it-Q8_0.gguf", 34_000, 1_780_000_002),
        ("gemma-4-31B-it-GGUF/unsloth/Q8_0/README.md", 5, 1_780_000_003),
        ("gemma-4-31B-it-GGUF/bartowski/Q4_K_M/gemma-4-31B-it-Q4_K_M.gguf", 17_000, 1_780_000_004),
        ("gemma-4-31B-it-GGUF-extra/unsloth/Q4_K_M/x.gguf", 1, 1_780_000_005),
        ("gemma-4-31B-it-GGUF/unsloth-extra/Q4_K_M/y.gguf", 1, 1_780_000_008),
        ("solo-model/Q4_K_M/solo-Q4_K_M.gguf", 9, 1_780_000_006),
    ]),
    library("lib-b", "second-shelf", "read-only", [
        ("gemma-4-31B-it-GGUF/unsloth/Q8_0/gemma-4-31B-it-Q8_0.gguf", 34_000, 1_770_000_000),
    ]),
    library("lib-c", "unplugged", "unavailable", [
        ("gemma-4-31B-it-GGUF/unsloth/Q4_K_S/gemma-4-31B-it-Q4_K_S.gguf", 16_000, 1_780_000_007),
    ]),
]


def run(repo, models_dir, libraries=LIBRARIES, broken=False):
    real = (hf.models_dir_from_config, hf.parse_config, locator.current_locations)
    hf.models_dir_from_config = lambda _cfg: Path(models_dir)
    hf.parse_config = lambda: {}

    def fake_locations(wait=False):
        if broken:
            raise RuntimeError("registry down")
        return locator.Locations(libraries)
    locator.current_locations = fake_locations
    try:
        return hf.hf_local_check(repo)
    finally:
        hf.models_dir_from_config, hf.parse_config, locator.current_locations = real


def main():
    with tempfile.TemporaryDirectory() as tmp:
        disk = Path(tmp)
        for rel, size, mtime in (("gemma-4-31B-it-GGUF/unsloth/default/mtp-gemma-4-31B-it.gguf", 267, 1_780_100_000),
                                 ("gemma-4-31B-it-GGUF/unsloth/Q4_0/twin.gguf", 10, 1_780_000_000),
                                 ("gemma-4-31B-it-GGUF/unsloth/Q8_0/twin.gguf", 20, 1_780_200_000),
                                 ("gemma-4-31B-it-GGUF/unsloth/Q8_0/notes.txt", 3, 1_780_000_000)):
            p = disk / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"x" * size)
            os.utime(p, (mtime, mtime))

        print("этот диск:")
        got = run("unsloth/gemma-4-31B-it-GGUF", disk)
        check(got.get("ok") is True and got.get("localNames") == ["mtp-gemma-4-31B-it.gguf", "twin.gguf"],
              f"GGUF-файлы папки <модель>/<автор>/, по имени (got {got.get('localNames')})")
        twin = (got.get("localFiles") or {}).get("twin.gguf") or {}
        check((twin.get("size"), twin.get("mtime")) == (20, 1_780_200_000), f"одно имя в двух квантах — более новый файл (got {twin})")

        print("библиотеки:")
        lib = got.get("libraryFiles") or {}
        check(sorted(lib) == ["gemma-4-31B-it-Q5_K_M.gguf", "gemma-4-31B-it-Q8_0.gguf", "mmproj-BF16.gguf"],
              f"файлы этого репозитория в библиотеках, только GGUF (got {sorted(lib)})")
        check(lib.get("gemma-4-31B-it-Q5_K_M.gguf") == [{"store": {"id": "lib-a", "name": "lama-caravan-models"}, "size": 20_200, "mtime": 1_780_000_000}],
              "запись: библиотека, размер и время — чтобы сверить с HF")
        check([c["store"]["name"] for c in lib.get("gemma-4-31B-it-Q8_0.gguf", [])] == ["lama-caravan-models", "second-shelf"],
              "файл в двух библиотеках — по записи на каждую (read-only тоже читается)")
        check("gemma-4-31B-it-Q4_K_S.gguf" not in lib, "недоступная библиотека не держит ничего")
        check("gemma-4-31B-it-Q4_K_M.gguf" not in lib and "x.gguf" not in lib and "y.gguf" not in lib,
              "чужой автор и папки, чьё имя (модели или автора) только начинается так же, не считаются")

        solo = run("solo-model", disk)
        check(list((solo.get("libraryFiles") or {})) == ["solo-Q4_K_M.gguf"], f"репозиторий без автора — папка <модель>/ (got {solo.get('libraryFiles')})")

        try:
            broken = run("unsloth/gemma-4-31B-it-GGUF", disk, broken=True)
        except Exception as exc:  # a request that fails is exactly what this check is about
            broken = {"raised": repr(exc)}
        check(broken.get("ok") is True and broken.get("localNames") == ["mtp-gemma-4-31B-it.gguf", "twin.gguf"] and broken.get("libraryFiles") == {},
              "локатор не отвечает — ответ о диске цел, библиотек нет, запрос не падает")
        empty = run("nobody/none-GGUF", disk)
        check(empty == {"ok": True, "localNames": [], "localFiles": {}, "libraryFiles": {}}, f"ничего нигде — пусто везде (got {empty})")

    if _fail:
        print(f"FAILED ({len(_fail)}):")
        for msg in _fail:
            print("  - " + msg)
        sys.exit(1)
    print("hf-local-check snapshots hold")


if __name__ == "__main__":
    main()
