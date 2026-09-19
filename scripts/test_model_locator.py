#!/usr/bin/env python3
"""Value snapshot: where a model file lives, and what its header said.

Two small pieces the picker, the cell card and the start path lean on:

* Locations answers "where is this file right now": on this disk (looked at
  directly), in a library (from the registry's last look — never a look at
  the NAS from this process), or missing. A library counts only while it is
  really there; one that is not mounted holds nothing, whatever its last list
  said. This disk wins over a library, a "~" in the models directory is
  expanded, and a multi-part GGUF's library size counts all its parts.
* The board reads the last measurement and never waits for the NAS; a start
  waits for a fresh one.
* A controller cell's card names which of its launch files only a library
  holds, looked for where the start joins them, and its ≈VRAM badge counts
  moved weights by the library's measure.
* LibraryMeta keeps a GGUF header's facts for files that live in a library,
  read from the local copy before a move deleted it; a different size under
  the same name is another file and gets nothing.

Run: python3 scripts/test_model_locator.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from caravan.admin import library_meta, model_locator  # noqa: E402

_fail = []

LIBS = [
    {"id": "lib-a", "name": "NAS", "state": "ok", "path": "/mnt/lib", "files": [
        {"path": "M/a/Q4/m.gguf", "size": 40}, {"path": "M/a/Q4/both.gguf", "size": 7},
        {"path": "Big/x/Q8/big-00001-of-00002.gguf", "size": 30}, {"path": "Big/x/Q8/big-00002-of-00002.gguf", "size": 12}]},
    {"id": "lib-b", "name": "Old", "state": "not-mounted", "path": "/mnt/old", "files": [{"path": "Gone/g.gguf", "size": 5}]},
    {"id": "lib-c", "name": "RO", "state": "read-only", "path": "/mnt/ro", "files": [{"path": "R/r.gguf", "size": 3}]},
]


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def section_locations():
    print("где лежит файл:")
    local = {"/models/M/a/Q4/both.gguf", "/models/Here/h.gguf", os.path.expanduser("~/models/T/t.gguf")}
    locs = model_locator.Locations(LIBS, exists=lambda p: p in local)
    here = locs.locate("Here/h.gguf", "/models")
    check((here.where, here.path, here.store) == ("local", "/models/Here/h.gguf", None), "файл на этом диске — отсюда")
    lib = locs.locate("/M/a/Q4/m.gguf", "/models")
    check((lib.where, lib.path, lib.store["id"], lib.size, lib.to_json()["store"]) ==
          ("library", "/mnt/lib/M/a/Q4/m.gguf", "lib-a", 40, {"id": "lib-a", "name": "NAS"}),
          f"только в библиотеке — путь от её корня на этом хосте, с размером; ведущий / у пути не мешает (got {lib.to_json()})")
    both = locs.locate("M/a/Q4/both.gguf", "/models")
    check(both.where == "local", "есть и здесь, и в библиотеке — берётся этот диск: он быстрее, и сеть ему не нужна")
    gone = locs.locate("Gone/g.gguf", "/models")
    check((gone.where, gone.path) == ("missing", "/models/Gone/g.gguf"),
          "negative: библиотека не смонтирована — её файлов нет, что бы ни говорил её прошлый список; путь — где файл ждали")
    ro = locs.locate("R/r.gguf", "/models")
    check(ro.where == "library" and ro.path == "/mnt/ro/R/r.gguf", "библиотека только для чтения — читать из неё можно")
    tilde = locs.locate("T/t.gguf", "~/models")
    check(tilde.where == "local", "«~» в каталоге моделей раскрывается: спрашиваем о файле, который ячейка откроет")
    check(locs.locate("", "/models") is None, "negative: пустой путь — не файл")
    check((locs.library_size("Big/x/Q8/big-00001-of-00002.gguf"), locs.library_size("M/a/Q4/m.gguf"), locs.library_size("Nope/n.gguf"))
          == (42, 40, 0), "размер в библиотеке: многочастный GGUF — все части, одиночный — свой, чужой — ноль")
    check([r for r, _s, _f in locs.library_entries()] ==
          ["Big/x/Q8/big-00001-of-00002.gguf", "Big/x/Q8/big-00002-of-00002.gguf", "M/a/Q4/both.gguf", "M/a/Q4/m.gguf", "R/r.gguf"],
          "файлы всех доступных библиотек, по пути; несмонтированной — нет")


def section_current():
    print("живой снимок:")
    import caravan.admin.model_stores as ms
    saved = ms.registry
    asked = []

    class Registry:
        def library_files(self, wait=True):
            asked.append(wait)
            return LIBS

    class Broken:
        def library_files(self, wait=True):
            raise RuntimeError("registry down")
    try:
        ms.registry = lambda: Registry()
        board = model_locator.current_locations()
        start = model_locator.current_locations(wait=True)
        ms.registry = lambda: Broken()
        broken = model_locator.current_locations()
    finally:
        ms.registry = saved
    check(asked == [False, True], f"доска и пикер не ждут NAS — читают последний замер; старт ждёт свежий (got {asked})")
    check(board.locate("M/a/Q4/m.gguf", "/nonexistent").where == "library" and len(start.library_entries()) == 5,
          "снимок строится из файлов реестра")
    check(broken.library_entries() == [], "negative: реестр не ответил — библиотек нет, остаётся старый ответ «только этот диск», а не ошибка посреди старта")


def section_card():
    print("карточка ячейки:")
    from caravan.admin import topology
    locs = model_locator.Locations(LIBS, exists=lambda p: p == "/models/M/a/Q4/both.gguf")
    split = topology._launch_in_library({"MODEL_FILE": "M/a/Q4/m.gguf", "MMPROJ_FILE": "M/a/Q4/both.gguf",
                                         "SPEC_DRAFT_MODEL_FILE": "R/r.gguf", "LLAMA_MODELS_DIR": "/models"}, "", {}, locs)
    check(split == {"stores": [{"id": "lib-a", "name": "NAS"}, {"id": "lib-c", "name": "RO"}], "roles": ["model", "draft"]},
          f"веса и черновик только в библиотеках, проектор здесь — названы оба файла и обе библиотеки (got {split})")
    one = topology._launch_in_library({"MODEL_FILE": "M/a/Q4/m.gguf", "MMPROJ_FILE": "Big/x/Q8/big-00001-of-00002.gguf"}, "",
                                      {"LLAMA_MODELS_DIR": "/models"}, locs)
    check(one == {"stores": [{"id": "lib-a", "name": "NAS"}], "roles": ["model", "mmproj"]},
          f"два файла в одной библиотеке — она названа один раз (got {one})")
    fallback = topology._launch_in_library({}, "M/a/Q4/m.gguf", {"LLAMA_MODELS_DIR": "/models"}, locs)
    check(fallback == {"stores": [{"id": "lib-a", "name": "NAS"}], "roles": ["model"]},
          f"MODEL_FILE пуст — модель ячейки берётся из её записи (got {fallback})")
    own = topology._launch_in_library({"MODEL_FILE": "M/a/Q4/both.gguf", "LLAMA_MODELS_DIR": "/models"}, "",
                                      {"LLAMA_MODELS_DIR": "/elsewhere"}, locs)
    other = topology._launch_in_library({"MODEL_FILE": "M/a/Q4/both.gguf"}, "", {"LLAMA_MODELS_DIR": "/elsewhere"}, locs)
    check(own is None and other == {"stores": [{"id": "lib-a", "name": "NAS"}], "roles": ["model"]},
          f"файл ищется там, куда его подставит старт: в каталоге ячейки, без него — в каталоге контроллера (got {own}, {other})")
    check(topology._launch_in_library({"MODEL_FILE": "Nope/n.gguf"}, "", {"LLAMA_MODELS_DIR": "/models"}, locs) is None,
          "negative: файла нет нигде — это не «в библиотеке»: отсутствие скажет сам старт")
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "L").mkdir()
        (Path(tmp) / "L" / "loc-size.gguf").write_bytes(b"x" * 9)
        sizes = [topology._parked_model_size(p, {"LLAMA_MODELS_DIR": tmp}, locs)
                 for p in ("L/loc-size.gguf", "Big/x/Q8/big-00001-of-00002.gguf", "Nope/n.gguf")]
    check(sizes == [9, 42, 0], f"≈VRAM стоящей ячейки: веса здесь — с диска, перенесённые — мера библиотеки (все части), нигде — ноль (got {sizes})")


def section_load_sizes():
    print("размеры для загрузки ячейки:")
    from caravan.admin import topology
    locs = model_locator.Locations(LIBS)
    check((locs.library_file("/mnt/lib/M/a/Q4/m.gguf")[0]["id"], locs.library_file("/mnt/lib/M/a/Q4/m.gguf")[1]) == ("lib-a", 40),
          "путь в доступной библиотеке — её запись и размер из её последнего осмотра")
    check(locs.library_file("/mnt/lib/Big/x/Q8/big-00001-of-00002.gguf")[1] == 42, "многочастный GGUF — все его части")
    check(locs.library_file("/mnt/ro/R/r.gguf")[1] == 3, "библиотека только для чтения — тоже библиотека")
    check(locs.library_file("/mnt/old/Gone/g.gguf") == (None, 0),
          "negative: библиотека не смонтирована — о файле ничего не известно, но путь всё равно её (смотреть туда нельзя)")
    check(locs.library_file("/mnt/lib/Nope/n.gguf")[1] == 0, "negative: в доступной библиотеке, но не в её списке — ноль, а не догадка")
    check([locs.library_file(p) for p in ("/models/Here/h.gguf", "/mnt/library/M/a/Q4/m.gguf", "")] == [None, None, None],
          "negative: путь вне библиотек — None; папка, чьё имя лишь начинается как корень библиотеки, — не она")
    twin = model_locator.Locations([
        {"id": "a", "name": "First", "state": "ok", "path": "/mnt/a", "files": [{"path": "M/m.gguf", "size": 10}]},
        {"id": "b", "name": "Second", "state": "ok", "path": "/mnt/b", "files": [{"path": "M/m.gguf", "size": 11}]}])
    check(twin.library_file("/mnt/b/M/m.gguf")[1] == 11, "один путь в двух библиотеках — размер той, из которой читают, а не первой")

    touched = []
    saved = (os.path.isfile, os.path.getsize)
    os.path.isfile = lambda p: touched.append(p) or saved[0](p)
    os.path.getsize = lambda p: touched.append(p) or saved[1](p)
    try:
        lib = topology._load_file_size("/mnt/lib/M/a/Q4/m.gguf", locs)
        dead = topology._load_file_size("/mnt/old/Gone/g.gguf", locs)
        unlisted = topology._load_file_size("/mnt/lib/Nope/n.gguf", locs)
        nas_touched = list(touched)
        with tempfile.TemporaryDirectory() as tmp:
            one = Path(tmp) / "load-one.gguf"
            one.write_bytes(b"x" * 7)
            for n in (1, 2):
                (Path(tmp) / f"load-split-0000{n}-of-00002.gguf").write_bytes(b"x" * (5 * n))
            here = topology._load_file_size(str(one), locs)
            split = topology._load_file_size(str(Path(tmp) / "load-split-00001-of-00002.gguf"), locs)
            missing = topology._load_file_size(str(Path(tmp) / "load-none.gguf"), locs)
    finally:
        os.path.isfile, os.path.getsize = saved
    check((lib, nas_touched) == ((40, "NAS"), []), f"файл библиотеки: размер и её имя, без единого stat() (got {lib}, {nas_touched})")
    check((dead, unlisted) == (None, None), "negative: библиотека недоступна или файла нет в её списке — не известно, и туда не смотрят")
    check((here, split, missing) == ((7, None), (15, None), None),
          f"файл этого диска — stat(), все части многочастного; нет файла — не известно (got {here}, {split}, {missing})")

    calls = []

    class Watch:
        def look(self, port, pids, size_of):
            calls.append(("look", port, sorted(pids), size_of("/mnt/lib/M/a/Q4/m.gguf")))
            if port == 99:
                raise OSError("proc gone")
            return {"stage": "reading"}

        def forget(self, port):
            calls.append(("forget", port))
    saved = (topology.LOAD_WATCH, topology.cell_unit_pids)
    topology.LOAD_WATCH, topology.cell_unit_pids = Watch(), lambda port: {port + 1}
    try:
        got = [topology._cell_load(22001, phase, locs) for phase in ("starting", "warming", "running", "stopped", "error", "broken")]
        failed = topology._cell_load(99, "warming", locs)
    finally:
        topology.LOAD_WATCH, topology.cell_unit_pids = saved
    check(got == [{"stage": "reading"}, {"stage": "reading"}, None, None, None, None] and failed is None,
          f"о загрузке спрашивают только стартующую и греющуюся ячейку; сбой замера — None, доска цела (got {got}, {failed})")
    check(calls == [("look", 22001, [22002], (40, "NAS"))] * 2 + [("forget", 22001)] * 4 + [("look", 99, [100], (40, "NAS"))],
          f"замер получает процессы ячейки и размеры из снимка библиотек; остальные ячейки забываются (got {calls})")


def section_meta():
    print("запомненные заголовки:")
    with tempfile.TemporaryDirectory() as tmp:
        read = []
        store = library_meta.LibraryMeta(Path(tmp) / "meta.json", read=lambda p: read.append(p) or {"contextLength": 131072})
        check(store.remember_file("lib-a", "M/m.gguf", 40, "/models/M/m.gguf") is True and read == ["/models/M/m.gguf"],
              "заголовок читается с ЛОКАЛЬНОЙ копии")
        check(store.lookup("lib-a", "M/m.gguf", 40) == {"contextLength": 131072}, "и находится по библиотеке и пути")
        check(store.lookup("lib-a", "M/m.gguf", 41) is None, "negative: другой размер под тем же именем — другой файл, фактов нет")
        check(store.lookup("lib-b", "M/m.gguf", 40) is None, "negative: другая библиотека — другая запись")
        again = library_meta.LibraryMeta(Path(tmp) / "meta.json")
        check(again.lookup("lib-a", "M/m.gguf", 40) == {"contextLength": 131072}, "переживает рестарт: лежит в файле")
        check(store.remember_file("lib-a", "M/notes.txt", 3, "/models/M/notes.txt") is False and len(read) == 1,
              "negative: у не-GGUF заголовка нет — и не читается")
        broken = library_meta.LibraryMeta(Path(tmp) / "b.json", read=lambda p: (_ for _ in ()).throw(ValueError("bad header")))
        check(broken.remember_file("lib-a", "M/x.gguf", 5, "/models/M/x.gguf") is False and not (Path(tmp) / "b.json").exists(),
              "negative: заголовок не разобрался — ничего не записано, перенос этим не ломается")
        doc = json.loads((Path(tmp) / "meta.json").read_text())
        check(list(doc) == ["lib-a/M/m.gguf"], f"ключ — библиотека и путь (got {list(doc)})")
        check((store.forget("lib-a", "M/m.gguf"), store.lookup("lib-a", "M/m.gguf", 40), store.forget("lib-a", "M/m.gguf")) == (True, None, False),
              "файл уехал из библиотеки — запись о нём уходит: заголовок снова читается с диска; забывать нечего — False, а не ошибка")
        back = library_meta.LibraryMeta(Path(tmp) / "meta.json")
        check(back.lookup("lib-a", "M/m.gguf", 40) is None, "забытое не возвращается после перезапуска: файл переписан")
        store.remember_file("lib-a", "M/m.gguf", 40, "/models/M/m.gguf")
        mute = library_meta.LibraryMeta(Path(tmp) / "mute.json", read=lambda p: None)
        check(mute.remember_file("lib-a", "M/junk.gguf", 5, "/models/M/junk.gguf") is False and not (Path(tmp) / "mute.json").exists(),
              "negative: заголовок ничего не сказал — ничего не записано: нули не выдаются за факты")
    import caravan.admin.models as md
    saved = md.read_gguf_metadata_cached
    try:
        md.read_gguf_metadata_cached = lambda p: {}
        nothing = library_meta._runtime_meta("/models/M/junk.gguf")
        md.read_gguf_metadata_cached = lambda p: {"general.architecture": "llama", "llama.context_length": 4096}
        facts = library_meta._runtime_meta("/models/M/real.gguf") or {}
    finally:
        md.read_gguf_metadata_cached = saved
    check(nothing is None and (facts.get("architecture"), facts.get("contextLength")) == ("llama", 4096),
          f"файл только называется .gguf (заголовок пуст) — фактов нет; настоящий заголовок — его факты (got {nothing}, {facts})")


def main():
    section_locations()
    section_current()
    section_card()
    section_load_sizes()
    section_meta()
    print()
    if _fail:
        print(f"model locator FAILED ({len(_fail)}):")
        for m in _fail:
            print("  - " + m.splitlines()[0])
        return 1
    print("model locator OK: где лежит файл, живой снимок и запомненные заголовки")
    return 0


if __name__ == "__main__":
    sys.exit(main())
