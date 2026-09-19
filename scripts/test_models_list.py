#!/usr/bin/env python3
"""Value snapshot: the model list the cell editor's picker is built from.

list_models() walks the controller's models directory and turns every GGUF
into a row: its kind (model, projector, speculative draft — vocab files are
skipped), its companions (a projector or a draft in the same quant folder, in
the sibling default/ folder, or in another quant folder of the same
repository — in that order), what it can do (vision, embeddings), its family
defaults and the facts its header states. It had no snapshot; this one pins the
rows by value.

Headers are not parsed here: read_gguf_metadata_cached is replaced by a table,
so the snapshot pins what the list MAKES of a header, not the parser.

Run: python3 scripts/test_models_list.py
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from caravan.admin import model_locator, models  # noqa: E402

_fail = []

HEADERS = {
    "gemma4-12b-it-Q4_K_M.gguf": {"general.architecture": "gemma3", "gemma3.context_length": 131072, "gemma3.block_count": 48},
    "gemma4-12b-it-Q8_0.gguf": {"general.architecture": "gemma3", "gemma3.context_length": 131072, "gemma3.block_count": 48},
    "mtp-gemma4-12b-it.gguf": {"general.architecture": "gemma3", "gemma3.block_size": 4},
    "bge-small-embed-Q8_0.gguf": {"general.architecture": "bert", "bert.context_length": 512, "bert.pooling_type": 1},
}
FILES = {
    "gemma4-12b-it-GGUF/unsloth/Q4_K_M/gemma4-12b-it-Q4_K_M.gguf": 4000,
    "gemma4-12b-it-GGUF/unsloth/Q4_K_M/mmproj-F16.gguf": 300,
    "gemma4-12b-it-GGUF/unsloth/Q8_0/gemma4-12b-it-Q8_0.gguf": 8000,
    "gemma4-12b-it-GGUF/unsloth/default/mtp-gemma4-12b-it.gguf": 100,
    "bge-small-embed/x/Q8_0/bge-small-embed-Q8_0.gguf": 50,
    "vocabs/ggml-vocab-llama.gguf": 10,
}
Q4 = "gemma4-12b-it-GGUF/unsloth/Q4_K_M/gemma4-12b-it-Q4_K_M.gguf"
Q8 = "gemma4-12b-it-GGUF/unsloth/Q8_0/gemma4-12b-it-Q8_0.gguf"
MMPROJ = "gemma4-12b-it-GGUF/unsloth/Q4_K_M/mmproj-F16.gguf"
DRAFT = "gemma4-12b-it-GGUF/unsloth/default/mtp-gemma4-12b-it.gguf"
EMBED = "bge-small-embed/x/Q8_0/bge-small-embed-Q8_0.gguf"


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def fake_meta(path):
    return dict(HEADERS.get(Path(path).name, {}))


def listing(tmp, libraries=()):
    for rel, size in FILES.items():
        p = Path(tmp) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x" * size)
    models.read_gguf_metadata_cached = fake_meta
    models._freshness_by_path = lambda: {Q4: "size"}
    return models.list_models({"LLAMA_MODELS_DIR": tmp}, locations=model_locator.Locations(libraries))


class Remembered:
    """library_meta's lookup, answered from a table."""

    def __init__(self, table):
        self.table = table

    def lookup(self, store_id, rel, size):
        hit = self.table.get((store_id, rel))
        return dict(hit) if hit and hit.get("_size", size) == size else None


def section_library():
    print("файлы из библиотеки:")
    lib_files = [
        {"path": "gemma4-12b-it-GGUF/unsloth/Q6_K/gemma4-12b-it-Q6_K.gguf", "size": 6000, "mtime": 1_700_000_000},
        {"path": "gemma4-12b-it-GGUF/unsloth/Q6_K/mmproj-BF16.gguf", "size": 600, "mtime": 1_700_000_000},
        {"path": Q4, "size": 4000, "mtime": 1},
        {"path": "vocabs/ggml-vocab-qwen.gguf", "size": 5, "mtime": 1},
        {"path": "Moved/a/Q4/moved-Q4.gguf", "size": 70, "mtime": 5},
    ]
    libraries = [{"id": "lib-a", "name": "NAS", "state": "ok", "path": "/mnt/lib", "files": lib_files},
                 {"id": "lib-b", "name": "Old", "state": "not-mounted", "path": "/mnt/old",
                  "files": [{"path": "Gone/g/Q4/g.gguf", "size": 9, "mtime": 1}]}]
    import caravan.admin.library_meta as lm
    saved = lm.library_meta
    lm.library_meta = lambda: Remembered({("lib-a", "gemma4-12b-it-GGUF/unsloth/Q6_K/gemma4-12b-it-Q6_K.gguf"):
                                          {"architecture": "gemma3", "contextLength": 131072}})
    try:
        with tempfile.TemporaryDirectory() as tmp:
            rows = listing(tmp, libraries)
    finally:
        lm.library_meta = saved
    by = {r["path"]: r for r in rows}
    order = [r["path"] for r in rows if r["kind"] == "model"]
    check(order == ["Moved/a/Q4/moved-Q4.gguf", EMBED, Q4, "gemma4-12b-it-GGUF/unsloth/Q6_K/gemma4-12b-it-Q6_K.gguf", Q8],
          f"файл из библиотеки стоит на своём месте, рядом с соседями с этого диска, а не в хвосте (got {order})")
    q6 = by.get("gemma4-12b-it-GGUF/unsloth/Q6_K/gemma4-12b-it-Q6_K.gguf") or {}
    check((q6.get("kind"), q6.get("libraryOnly"), q6.get("store"), q6.get("size"), q6.get("mtime"))
          == ("model", True, {"id": "lib-a", "name": "NAS"}, 6000, 1_700_000_000),
          f"модель только из библиотеки — в списке, с её библиотекой, размером и временем (got {q6})")
    check((q6.get("ggufMeta"), q6.get("suggestedMmproj"), q6.get("suggestedDraft"), q6.get("detectedFamily"))
          == ({"architecture": "gemma3", "contextLength": 131072}, "gemma4-12b-it-GGUF/unsloth/Q6_K/mmproj-BF16.gguf", DRAFT, "gemma4"),
          f"её заголовок — запомненный, а не прочитанный по сети; компаньоны — и из библиотеки, и с этого диска (got {q6.get('ggufMeta')}, "
          f"{q6.get('suggestedMmproj')}, {q6.get('suggestedDraft')})")
    moved = by.get("Moved/a/Q4/moved-Q4.gguf") or {}
    check(moved.get("ggufMeta") == {} and moved.get("libraryOnly") is True,
          "файл, попавший в библиотеку мимо переноса, — без фактов заголовка, а не с выдуманными")
    q4 = by[Q4]
    check("libraryOnly" not in q4 and "store" not in q4 and q4["size"] == 4000,
          "negative: файл есть и здесь, и в библиотеке — строка этого диска, без пометки")
    check("vocabs/ggml-vocab-qwen.gguf" not in by and "Gone/g/Q4/g.gguf" not in by,
          "negative: словарь из библиотеки не модель; файлы несмонтированной библиотеки в списке не появляются")
    check(by["gemma4-12b-it-GGUF/unsloth/Q6_K/mmproj-BF16.gguf"].get("libraryOnly") is True,
          "компаньон из библиотеки тоже помечен")
    with tempfile.TemporaryDirectory() as tmp:
        only = models.list_models({"LLAMA_MODELS_DIR": str(Path(tmp) / "missing")},
                                  locations=model_locator.Locations(libraries[:1]))
    only_models = [r["path"] for r in only if r["kind"] == "model"]
    check(only_models == ["Moved/a/Q4/moved-Q4.gguf", Q4, "gemma4-12b-it-GGUF/unsloth/Q6_K/gemma4-12b-it-Q6_K.gguf"],
          f"каталога моделей здесь нет, а библиотека есть — её модели всё равно в списке (got {only_models})")


def section_rows():
    print("строки пикера:")
    with tempfile.TemporaryDirectory() as tmp:
        rows = listing(tmp)
    order = [(r["path"], r["kind"]) for r in rows]
    check(order == [(EMBED, "model"), (Q4, "model"), (Q8, "model"), (MMPROJ, "mmproj"), (DRAFT, "draft")],
          f"сначала модели, потом компаньоны; словари не в списке (got {order})")
    by = {r["path"]: r for r in rows}
    q4 = by[Q4]
    check((q4["compatibleMmprojs"], q4["suggestedMmproj"], q4["suggestedDraft"], q4["capability"])
          == ([MMPROJ], MMPROJ, DRAFT, "vision_likely"),
          f"проектор из своей папки, черновик из соседней default/ — модель умеет картинки (got {q4['compatibleMmprojs']}, {q4['suggestedDraft']}, {q4['capability']})")
    q8 = by[Q8]
    check((q8["compatibleMmprojs"], q8["suggestedDraft"]) == ([MMPROJ], DRAFT),
          f"у другого кванта своей папки компаньонов нет — берутся из default/ и из соседнего кванта (got {q8['compatibleMmprojs']}, {q8['suggestedDraft']})")
    check((q4["detectedFamily"], q4["familyDefaults"].get("SPEC_TYPE"), q4["hasMtpBuiltin"]) == ("gemma4", "draft-mtp", False),
          f"семейство по верхней папке, его флаги по умолчанию (got {q4['detectedFamily']}, {q4['familyDefaults']})")
    check((q4["fresh"], q4["ggufMeta"]["contextLength"], q4["ggufMeta"]["architecture"], q4["size"])
          == ("size", 131072, "gemma3", 4000),
          f"свежесть из отчёта, окно и архитектура из заголовка, размер с диска (got {q4['fresh']}, {q4['ggufMeta']}, {q4['size']})")
    embed = by[EMBED]
    check((embed["capability"], embed["detectedFamily"]) == ("embedding_likely", "embedding"),
          f"эмбеддинги узнаются по имени и по pooling_type (got {embed['capability']}, {embed['detectedFamily']})")
    check("ggufMeta" not in by[MMPROJ] and by[DRAFT]["ggufMeta"]["specBlockSize"] == 4 and by[MMPROJ]["fresh"] == "",
          "у проектора заголовок не читается, у черновика — да: глубина черновика из его файла")


def section_absent():
    print("нет каталога:")
    check(models.list_models({"LLAMA_MODELS_DIR": "/nonexistent/caravan-models"}, locations=model_locator.Locations(())) == [],
          "negative: каталога моделей нет и библиотек нет — пустой список, а не ошибка")


def main():
    section_rows()
    section_library()
    section_absent()
    print()
    if _fail:
        print(f"models list FAILED ({len(_fail)}):")
        for m in _fail:
            print("  - " + m.splitlines()[0])
        return 1
    print("models list OK: строки пикера, компаньоны, семейства и заголовки")
    return 0


if __name__ == "__main__":
    sys.exit(main())
