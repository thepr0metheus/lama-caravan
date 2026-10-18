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
import threading
import time
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
    check((q4["compatibleDrafts"], q8["compatibleDrafts"], by[MMPROJ].get("compatibleDrafts"), by[DRAFT].get("compatibleDrafts"))
          == ([DRAFT], [DRAFT], None, None),
          f"список черновиков — тот же, что у проекторов: форма предлагает ровно его (got {q4['compatibleDrafts']}, {q8['compatibleDrafts']}); "
          "negative: у самих компаньонов списка нет")
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


def section_companions_by_header():
    print("проектор — по заголовку, не только по имени; порядок черновиков:")
    files = {
        "MiniCPM-o-x/openbmb/Q4_K_M/MiniCPM-o-x-Q4_K_M.gguf": 5000,
        "MiniCPM-o-x/openbmb/default/MiniCPM-o-x-projector-F16.gguf": 15,
        "MiniCPM-o-x/openbmb/F16/MiniCPM-o-x-vision-F16.gguf": 1100,
        "MiniCPM-o-x/openbmb/F16/MiniCPM-o-x-audio-F16.gguf": 660,
        "Llava/a/Q4/llava-Q4.gguf": 4000,
        "Llava/a/Q4/llava-projector-f16.gguf": 600,
        "Gem/b/Q5_K_M/gem-Q5_K_M.gguf": 8000,
        "Gem/b/Q5_K_M/mtp-own.gguf": 10,
        "Gem/b/default/mtp-default.gguf": 10,
        "Gem/b/Q8_0/gem-Q8_0.gguf": 12000,
        "Gem/b/Q8_0/mtp-sibling.gguf": 10,
        "vocabs/ggml-vocab-x.gguf": 5,
    }
    reads = []
    headers = {
        "MiniCPM-o-x-Q4_K_M.gguf": {"general.architecture": "llama"},
        # Four tensors of the speech pipeline, named like a projector: no engine loads it with --mmproj.
        "MiniCPM-o-x-projector-F16.gguf": {"general.architecture": "projector"},
        # The real one, named like weights.
        "MiniCPM-o-x-vision-F16.gguf": {"general.architecture": "clip"},
        "MiniCPM-o-x-audio-F16.gguf": {"general.architecture": "whisper"},
        "llava-Q4.gguf": {"general.architecture": "llama"},
        "llava-projector-f16.gguf": {"general.architecture": "clip"},
    }
    libraries = [{"id": "lib-a", "name": "NAS", "state": "ok", "path": "/mnt/lib", "files": [
        {"path": "Moved/a/Q4/moved-Q4.gguf", "size": 70, "mtime": 5},
        {"path": "Moved/a/Q4/moved-projector.gguf", "size": 7, "mtime": 5},
        {"path": "Moved/a/Q4/seen-projector.gguf", "size": 8, "mtime": 5}]}]
    import caravan.admin.library_meta as lm
    saved_meta, saved_read, saved_fresh = lm.library_meta, models.read_gguf_metadata_cached, models._freshness_by_path
    lm.library_meta = lambda: Remembered({("lib-a", "Moved/a/Q4/seen-projector.gguf"): {"architecture": "projector"}})
    models.read_gguf_metadata_cached = lambda path: (reads.append(Path(path).name), dict(headers.get(Path(path).name, {})))[1]
    models._freshness_by_path = lambda: {}
    try:
        with tempfile.TemporaryDirectory() as tmp:
            for rel, size in files.items():
                f = Path(tmp) / rel
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_bytes(b"x" * size)
            rows = models.list_models({"LLAMA_MODELS_DIR": tmp}, locations=model_locator.Locations(libraries))
    finally:
        lm.library_meta, models.read_gguf_metadata_cached, models._freshness_by_path = saved_meta, saved_read, saved_fresh
    by = {r["path"]: r for r in rows}
    check("vocabs/ggml-vocab-x.gguf" not in by and "ggml-vocab-x.gguf" not in reads,
          "словарь не в списке, и его заголовок не читается: имя уже сказало, что это не модель")
    cpm = "MiniCPM-o-x/openbmb/"
    vision, projector = cpm + "F16/MiniCPM-o-x-vision-F16.gguf", cpm + "default/MiniCPM-o-x-projector-F16.gguf"
    check(by[vision]["kind"] == "mmproj",
          "файл с архитектурой clip — проектор, хотя в имени этого нет (vision-F16)")
    check(projector not in by,
          "negative: файл с «projector» в имени и архитектурой projector — не проектор и не модель: в списке его нет")
    model = by[cpm + "Q4_K_M/MiniCPM-o-x-Q4_K_M.gguf"]
    check((model["compatibleMmprojs"], model["suggestedMmproj"]) == ([vision], vision),
          f"модели предложен настоящий проектор из соседней папки F16, а не «projector» (got {model['compatibleMmprojs']})")
    check(by[cpm + "F16/MiniCPM-o-x-audio-F16.gguf"]["kind"] == "model",
          "as-is: аудио-кодировщик с архитектурой whisper остаётся «моделью» — whisper-раннеры берут такие файлы")
    check(by["Llava/a/Q4/llava-projector-f16.gguf"]["kind"] == "mmproj" and by["Llava/a/Q4/llava-Q4.gguf"]["suggestedMmproj"] == "Llava/a/Q4/llava-projector-f16.gguf",
          "проектор с «projector» в имени и архитектурой clip остаётся проектором — заголовок с именем согласен")
    check(by["Moved/a/Q4/moved-projector.gguf"]["kind"] == "mmproj" and "Moved/a/Q4/seen-projector.gguf" not in by,
          "файл из библиотеки: заголовка нет — решает имя (проектор); заголовок запомнен и не clip — файла в списке нет")
    gem = by["Gem/b/Q5_K_M/gem-Q5_K_M.gguf"]
    check(gem["compatibleDrafts"] == ["Gem/b/Q5_K_M/mtp-own.gguf", "Gem/b/default/mtp-default.gguf", "Gem/b/Q8_0/mtp-sibling.gguf"]
          and gem["suggestedDraft"] == "Gem/b/Q5_K_M/mtp-own.gguf",
          f"черновики: своя папка, потом default/, потом соседние кванты; предложен первый (got {gem['compatibleDrafts']})")
    check(by["Gem/b/Q8_0/gem-Q8_0.gguf"]["compatibleDrafts"] == ["Gem/b/Q8_0/mtp-sibling.gguf", "Gem/b/default/mtp-default.gguf", "Gem/b/Q5_K_M/mtp-own.gguf"],
          "у другого кванта порядок свой: его папка первой")


def section_drafts_by_architecture():
    print("черновик — и по архитектуре в заголовке, не только по папке:")
    # Strata's draft layer is made once, from the original checkpoint, and serves every pack of the family — the Coder's, the
    # fine-tunes', Unsloth's — though no repository of theirs ships it. Its header says whose it is: "<model's>-mtp".
    ORIG = "Orig-GGUF/ista/IQ2_XS/orig-IQ2_XS-00001-of-00002.gguf"
    ORIG_MTP = "Orig-GGUF/ista/IQ2_XS/mtp-q2_0.gguf"
    CODER = "Coder-GGUF/ista/IQ1_M/coder-IQ1_M-00001-of-00002.gguf"
    SWIFT = "Swift-GGUF/uki/IQ3_XXS/swift-IQ3_XXS-00001-of-00002.gguf"
    SWIFT_MTP = "Swift-GGUF/uki/IQ3_XXS/mtp-swift-own.gguf"
    GEM = "Gem/b/Q5_K_M/gem-Q5_K_M.gguf"
    PI = "Pi/c/Q4/pi-Q4_0.gguf"
    PI_MTP = "Pi/c/default/mtp-pi.gguf"
    LIB = "Lib-GGUF/x/IQ3_S/lib-IQ3_S-00001-of-00002.gguf"
    LIB_MTP = "Lib-GGUF/x/IQ3_S/mtp-lib.gguf"
    LIB_BARE = "Bare-GGUF/y/default/mtp-unknown.gguf"
    headers = {
        "orig-IQ2_XS-00001-of-00002.gguf": {"general.architecture": "qwen4exp"},
        "mtp-q2_0.gguf": {"general.architecture": "qwen4exp-mtp"},
        "coder-IQ1_M-00001-of-00002.gguf": {"general.architecture": "qwen4exp"},
        "swift-IQ3_XXS-00001-of-00002.gguf": {"general.architecture": "qwen4exp"},
        "mtp-swift-own.gguf": {"general.architecture": "qwen4exp-mtp"},
        "gem-Q5_K_M.gguf": {"general.architecture": "gemma3"},
        "pi-Q4_0.gguf": {"general.architecture": "qwen35"},
        # llama.cpp's own MTP file: the model's architecture, with no "-mtp" after it.
        "mtp-pi.gguf": {"general.architecture": "qwen35"},
    }
    # Four more drafts of the architecture, after the others by path: seven are paired, five are offered.
    MORE = [f"Z{n}-GGUF/z/q/mtp-z{n}.gguf" for n in (1, 2, 3, 4)]
    headers.update({f"mtp-z{n}.gguf": {"general.architecture": "qwen4exp-mtp"} for n in (1, 2, 3, 4)})
    # A library draft whose header names the suffix and nothing before it, and a library model whose header was never read: the
    # empty architecture of one must not take the "empty" model of the other.
    ODD = "Odd-GGUF/o/default/mtp-odd.gguf"
    NOHDR = "Nohdr-GGUF/n/Q4/nohdr-Q4.gguf"
    files = [ORIG, ORIG_MTP, CODER, SWIFT, SWIFT_MTP, GEM, PI, PI_MTP, *MORE]
    libraries = [{"id": "lib-a", "name": "NAS", "state": "ok", "path": "/mnt/lib", "files": [
        {"path": LIB, "size": 70, "mtime": 5}, {"path": LIB_MTP, "size": 8, "mtime": 5}, {"path": LIB_BARE, "size": 9, "mtime": 5},
        {"path": ODD, "size": 8, "mtime": 5}, {"path": NOHDR, "size": 70, "mtime": 5}]}]
    import caravan.admin.library_meta as lm
    saved_meta, saved_read, saved_fresh = lm.library_meta, models.read_gguf_metadata_cached, models._freshness_by_path
    lm.library_meta = lambda: Remembered({("lib-a", LIB): {"architecture": "qwen4exp"},
                                          ("lib-a", LIB_MTP): {"architecture": "qwen4exp-mtp"},
                                          ("lib-a", ODD): {"architecture": "-mtp"}})
    models.read_gguf_metadata_cached = lambda path: dict(headers.get(Path(path).name, {}))
    models._freshness_by_path = lambda: {}
    try:
        with tempfile.TemporaryDirectory() as tmp:
            for rel in files:
                f = Path(tmp) / rel
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_bytes(b"x" * 10)
            rows = models.list_models({"LLAMA_MODELS_DIR": tmp}, locations=model_locator.Locations(libraries))
    finally:
        lm.library_meta, models.read_gguf_metadata_cached, models._freshness_by_path = saved_meta, saved_read, saved_fresh
    by = {r["path"]: r for r in rows}
    check((by[CODER]["compatibleDrafts"], by[CODER]["suggestedDraft"]) == ([LIB_MTP, ORIG_MTP, SWIFT_MTP, MORE[0], MORE[1]], LIB_MTP),
          f"defect-history (2026-10-17): the Coder's pack has no draft in its folder or its repository's — the drafts made for its "
          f"architecture are offered, wherever they lie, in the library's order, the first suggested, and no more than five of "
          f"the seven there are (got {by[CODER]['compatibleDrafts']})")
    check((by[SWIFT]["compatibleDrafts"], by[SWIFT]["suggestedDraft"]) == ([SWIFT_MTP, LIB_MTP, ORIG_MTP, MORE[0], MORE[1]], SWIFT_MTP),
          f"a pack's own folder still comes first, the paired ones after it, none twice (got {by[SWIFT]['compatibleDrafts']})")
    check(by[ORIG]["compatibleDrafts"] == [ORIG_MTP, LIB_MTP, SWIFT_MTP, MORE[0], MORE[1]] and by[ORIG]["suggestedDraft"] == ORIG_MTP,
          f"the original's own draft stays its suggestion; the others of the architecture follow (got {by[ORIG]['compatibleDrafts']})")
    check(by[LIB]["compatibleDrafts"] == [LIB_MTP, ORIG_MTP, SWIFT_MTP, MORE[0], MORE[1]],
          "a pack only a library holds is paired by its remembered header, as a file on this disk is by the one it reads")
    check(by[NOHDR]["compatibleDrafts"] == [] and ODD not in by[CODER]["compatibleDrafts"],
          "negative: a draft whose header names `-mtp` and no architecture before it is paired with no model — least of all with "
          "one whose own header was never read (both architectures empty)")
    check(by[GEM]["compatibleDrafts"] == [] and by[GEM]["suggestedDraft"] == "",
          f"negative: a llama.cpp model of another architecture is offered none of Strata's drafts (got {by[GEM]['compatibleDrafts']})")
    check(by[PI]["compatibleDrafts"] == [PI_MTP] and PI_MTP not in by[CODER]["compatibleDrafts"],
          "negative: a draft of llama.cpp's kind (the model's own architecture, no `-mtp`) stays its folder's: found by folder "
          "for the model beside it, paired with no model of another architecture")
    check(LIB_BARE not in by[CODER]["compatibleDrafts"] and LIB_BARE not in by[GEM]["compatibleDrafts"],
          "negative: a draft in the library whose header was never read is paired with nobody — said, not guessed")
    check("compatibleDrafts" not in by[ORIG_MTP] and by[ORIG_MTP]["ggufMeta"]["architecture"] == "qwen4exp-mtp",
          "the draft's own row carries no list, and its architecture is what the pairing read")
    from caravan.common.draft_pairing import DraftPairing
    pairing = DraftPairing()
    for rel, arch in (("a.gguf", "qwen4exp-mtp"), ("b.gguf", "qwen4exp-mtp"), ("c.gguf", "qwen35"), ("d.gguf", None), ("e.gguf", "-mtp"),
                      ("f.gguf", "x-mtp-y"), ("g.gguf", "qwen4exp-mpt")):
        pairing.add(rel, arch)
    offered = pairing.of("qwen4exp")
    offered.append("tampered")
    check(offered == ["a.gguf", "b.gguf", "tampered"] and pairing.of("qwen4exp") == ["a.gguf", "b.gguf"],
          "DraftPairing: the drafts of an architecture in the order they came; the list handed out is a copy — a caller's edit is not kept")
    check((pairing.of("qwen35"), pairing.of(""), pairing.of(None), pairing.of("x"), pairing.of("x-mtp-y"), pairing.of("never-seen"))
          == ([], [], [], [], [], []),
          "negative: an architecture with no `-mtp` file after it, no architecture, a suffix in the middle of the name — nothing; "
          "and the suffix one letter off (`-mpt`) is not the suffix: it is not taken for qwen4exp's draft")


def section_absent():
    print("нет каталога:")
    check(models.list_models({"LLAMA_MODELS_DIR": "/nonexistent/caravan-models"}, locations=model_locator.Locations(())) == [],
          "negative: каталога моделей нет и библиотек нет — пустой список, а не ошибка")


def section_model_list():
    """ModelList — the list the board follows (2026-09-26): its stamp rides
    the topology on every beat, its rows go only when the stamp moved."""
    print("список, за которым идёт доска:")
    row = {"path": Q4, "kind": "model", "size": 4000, "mtime": 1700000000, "libraryOnly": False}
    other = {"path": EMBED, "kind": "model", "size": 50, "mtime": 1700000001}
    base = models.ModelList.stamp_of([row, other])
    check(models.ModelList.stamp_of([other, row]) == base and len(base) == 16,
          "тот же набор файлов в другом порядке — тот же отпечаток (16 знаков)")
    moved = {name: models.ModelList.stamp_of([{**row, name: value}, other]) for name, value in
             (("path", Q8), ("kind", "mmproj"), ("size", 4001), ("mtime", 1700000009), ("libraryOnly", True))}
    check(all(v != base for v in moved.values()) and len(set(moved.values())) == len(moved),
          "файл переименован, сменил вид, вырос, переписан, ушёл в библиотеку — каждый раз другой отпечаток "
          f"(got {sorted(k for k, v in moved.items() if v == base)} совпали)")
    check(models.ModelList.stamp_of([row]) != base and models.ModelList.stamp_of([row, other, {**other, "path": "x.gguf"}]) != base,
          "файл пропал или появился — другой отпечаток")
    check(models.ModelList.stamp_of([row, other, "junk", None]) == base,
          "negative: не-строки списка отпечаток не трогают")
    check(models.ModelList.stamp_of(None) == models.ModelList.stamp_of([]) != base,
          "boundary: списка нет — отпечаток пустого списка, а не ошибка")

    now = [1000.0]
    calls = []

    def lister():
        calls.append(now[0])
        return [dict(row)] if len(calls) == 1 else [dict(row), dict(other)]

    listed = models.ModelList(lister=lister, clock=lambda: now[0])
    first = listed.rows()
    stamp1 = listed.stamp()
    now[0] += models.ModelList.TTL - 0.5
    held = listed.rows()
    check(held is first and stamp1 == models.ModelList.stamp_of(first) and calls == [1000.0],
          "пока список свежий (5 с), обход каталога не повторяется: опрос каждой открытой доски спрашивает отпечаток")
    now[0] += 1.0
    check(listed.rows() == [row, other] and listed.stamp() == base and len(calls) == 2,
          "через 5 с — обходится заново, и новая модель двигает отпечаток")
    now[0] += models.ModelList.TTL
    rows, stamp = listed.current()
    check(len(calls) == 3 and stamp == models.ModelList.stamp_of(rows),
          "current() — строки и отпечаток одного и того же обхода (порознь кэш мог обновиться между ними)")
    saved = models.list_models
    try:
        models.list_models = lambda *a, **k: [dict(other)]
        check(models.ModelList().rows() == [other],
              "по умолчанию строки — list_models(), тот же список, что у редактора ячейки в /api/state")
    finally:
        models.list_models = saved


def section_model_walks():
    """One walk of the folder at a time (1.3.544). A dozen pages that opened together walked the folder a dozen
    times, each reading the headers the others were reading; the first /api/state of a start waited for all of it."""
    print("one walk at a time:")
    row = {"path": Q4, "kind": "model", "size": 4000, "mtime": 1700000000}
    other = {"path": EMBED, "kind": "model", "size": 50, "mtime": 1700000001}

    gate, entered, calls = threading.Event(), threading.Event(), []

    def lister():
        calls.append(1)
        entered.set()
        gate.wait(10)
        return [dict(row)]

    listed = models.ModelList(lister=lister)
    got = []
    threads = [threading.Thread(target=lambda: got.append(listed.rows())) for _ in range(8)]
    for thread in threads:
        thread.start()
    entered.wait(10)
    time.sleep(0.2)
    gate.set()
    for thread in threads:
        thread.join(10)
    check(len(calls) == 1 and len(got) == 8 and all(g is got[0] for g in got),
          "eight callers ask before the first list is there: one walk is made, all eight get its list (walks: %d)" % len(calls))

    now, box = [0.0], {"n": 0}
    inside, gate2 = threading.Event(), threading.Event()

    def lister_stale():
        box["n"] += 1
        if box["n"] == 1:
            return [dict(row)]
        inside.set()
        gate2.wait(10)
        return [dict(row), dict(other)]

    listed = models.ModelList(lister=lister_stale, clock=lambda: now[0])
    first = listed.rows()
    now[0] += models.ModelList.TTL + 1
    refresher = threading.Thread(target=listed.rows)
    refresher.start()
    inside.wait(10)
    began = time.monotonic()
    meanwhile = listed.rows()
    waited = time.monotonic() - began
    check(meanwhile is first and waited < 2 and box["n"] == 2,
          "a stale list is being made anew: the next caller is given the old one at once, and starts no second walk "
          "(waited %.2f s, walks %d)" % (waited, box["n"]))
    gate2.set()
    refresher.join(10)
    check(listed.rows() == [row, other] and box["n"] == 2,
          "the walk ends: its list is served, and it is fresh — no walk follows at once")

    attempts = []

    def flaky():
        attempts.append(1)
        if len(attempts) in (1, 3):
            raise OSError("the folder is not there")
        return [dict(row)]

    listed = models.ModelList(lister=flaky, clock=lambda: now[0])
    try:
        listed.rows()
        failed = False
    except OSError:
        failed = True
    check(failed and listed.rows() == [row] and len(attempts) == 2,
          "a first walk that fails holds nothing: the next call walks again and gets the list")
    now[0] += models.ModelList.TTL + 1
    try:
        listed.rows()
        refresh_failed = False
    except OSError:
        refresh_failed = True
    now[0] += models.ModelList.TTL + 1
    check(refresh_failed and listed.rows() == [row] and len(attempts) == 4,
          "a stale list whose new walk fails keeps its place: the next call walks again, the lock is not left held")

    now[0], slow_calls = 100.0, []

    def slow():
        slow_calls.append(1)
        now[0] += models.ModelList.TTL + 2
        return [dict(row)]

    listed = models.ModelList(lister=slow, clock=lambda: now[0])
    listed.rows()
    listed.rows()
    check(len(slow_calls) == 1, "a walk that took longer than the time a list is kept: the list is as old as the walk's end, not its start")


def section_split():
    print("модель из частей:")
    MIB, GIB = 2 ** 20, 2 ** 30
    files = {
        "Big-GGUF/x/Q4_K_M/Big-Q4_K_M-00001-of-00003.gguf": MIB,     # the first part holds the header only
        "Big-GGUF/x/Q4_K_M/Big-Q4_K_M-00002-of-00003.gguf": 40 * GIB,
        "Big-GGUF/x/Q4_K_M/Big-Q4_K_M-00003-of-00003.gguf": 40 * GIB,      # the same size as the second: two parts, not one
        "Half-GGUF/x/Q8_0/Half-Q8_0-00001-of-00002.gguf": 500,       # the second part has not come yet
        "Other-GGUF/x/Q4_K_M/Big-Q4_K_M-00001-of-00003.gguf": 70,    # the same name in another folder: a model of its own
        "Whole-GGUF/x/Q4_K_M/Whole-Q4_K_M.gguf": 900,
        "One-GGUF/x/Q8_0/One-Q8_0-00001-of-00001.gguf": 11,
        "Mixed-GGUF/x/Q4/Mixed-Q4-00001-of-00003.gguf": 100,
        "Mixed-GGUF/x/Q4/Mixed-Q4-00002-of-00003.gguf": 200,
    }
    libraries = [{"id": "lib-a", "name": "NAS", "state": "ok", "path": "/mnt/lib",
                  "files": [{"path": "Mixed-GGUF/x/Q4/Mixed-Q4-00003-of-00003.gguf", "size": 2000, "mtime": 1}]}]
    import caravan.admin.library_meta as lm
    saved = lm.library_meta
    lm.library_meta = lambda: Remembered({})
    try:
        with tempfile.TemporaryDirectory() as tmp:
            for rel, size in files.items():
                p = Path(tmp) / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                with open(p, "wb") as handle:      # sparse: the size is what the list reads, nothing is written
                    handle.truncate(size)
            models.read_gguf_metadata_cached = fake_meta
            models._freshness_by_path = lambda: {}
            rows = models.list_models({"LLAMA_MODELS_DIR": tmp}, locations=model_locator.Locations(libraries))
    finally:
        lm.library_meta = saved
    by = {r["path"]: r for r in rows}

    def facts(rel):
        r = by[rel]
        return (r["size"], r.get("parts"), r.get("partsFound"))
    whole_big = MIB + 80 * GIB
    big = "Big-GGUF/x/Q4_K_M/Big-Q4_K_M-0000%d-of-00003.gguf"
    check(facts(big % 1) == (whole_big, 3, 3),
          f"первая часть модели из трёх — строка всей модели: размер всех частей (80 ГБ, а не 1 МБ: в первой части один заголовок — так 93 ГБ читались «0.01 GB»; вторая и третья части одного размера — это две части, а не одна), "
          f"три части названо, три найдено (got {facts(big % 1)})")
    check(facts(big % 2) == (40 * GIB, None, None) and facts(big % 3) == (40 * GIB, None, None),
          f"negative: вторая и третья части — свои размеры и без числа частей (пикер их прячет, к ним не прибавляется) (got {facts(big % 2)}, {facts(big % 3)})")
    check(facts("Half-GGUF/x/Q8_0/Half-Q8_0-00001-of-00002.gguf") == (500, 2, 1),
          "недостающая часть названа: «две части» и «найдена одна» — модель, которой не хватает части, не рисуется целой")
    check(facts("Other-GGUF/x/Q4_K_M/Big-Q4_K_M-00001-of-00003.gguf") == (70, 3, 1),
          "negative: то же имя в другой папке — другая модель: части двух папок не складываются")
    check(facts("Whole-GGUF/x/Q4_K_M/Whole-Q4_K_M.gguf") == (900, None, None),
          "negative: целый файл — свой размер и ни слова о частях")
    check(facts("One-GGUF/x/Q8_0/One-Q8_0-00001-of-00001.gguf") == (11, 1, 1),
          "boundary: «часть 1 из 1» — одна часть из одной: размер свой, части названы и найдены")
    check(facts("Mixed-GGUF/x/Q4/Mixed-Q4-00001-of-00003.gguf") == (2300, 3, 3),
          f"часть в библиотеке считается: две здесь и одна на NAS — модель целая, 2300 (got {facts('Mixed-GGUF/x/Q4/Mixed-Q4-00001-of-00003.gguf')})")
    check((by[big % 1]["sizeGb"], by[big % 2]["sizeGb"], by[big % 3]["sizeGb"]) == (80.0, 40.0, 40.0),
          f"размер в ГБ: у первой части — всей модели (80.0), у остальных — свой (40.0 и 40.0) (got {by[big % 1]['sizeGb']})")


def main():
    section_rows()
    section_split()
    section_companions_by_header()
    section_drafts_by_architecture()
    section_library()
    section_absent()
    section_model_list()
    section_model_walks()
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
