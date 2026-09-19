#!/usr/bin/env python3
"""Value snapshot: which folders are models in their own right.

A model is not always a file. A whisper cache is a directory of blobs under a
tree of links; a checkpoint is a directory of shards. Three places have to
agree where such a folder starts — the manager on /models, the mover, and the
walk that lists a library — or the page offers to move half a model.

What is pinned, each claim together with its opposite:

* The rule, artifact_kind: a directory under whisper/ named models--… is a
  whisper cache; a directory holding a .safetensors is a checkpoint; the
  store's own root is neither, whatever lies in it; an ordinary folder is "".
* The walk, artifact_dirs: outermost only — the snapshot directory inside a
  cache is full of .safetensors links and matches the rule on its own, but it
  is a PART of that cache, and naming it too would let one move carry half of
  one away. Hidden and system folders are not walked at all.
* The weight, folder_weight: a copy's worth of bytes — real files counted
  once, links counted for nothing (a cache keeps every blob under a link as
  well, and following those would report it at double its size), hidden files
  left out, and the newest mtime inside as the folder's own.
* The two walks answer the same: the models disk (model_gc) and a library
  (the probe child, which imports nothing and carries this rule as text) name
  the same folders for the same tree.

Run: python3 scripts/test_model_artifacts.py
"""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from caravan.admin import model_gc, model_stores as ms  # noqa: E402
from caravan.common.model_artifacts import artifact_dirs, artifact_kind, folder_weight, relative  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def build(root):
    """One tree, laid out the way both walks will meet it: a whisper cache with
    blobs and a snapshot of links, a checkpoint of shards, a plain GGUF, and
    the noise a NAS collects."""
    cache = root / "whisper" / "models--Systran--faster-whisper-large-v3"
    (cache / "blobs").mkdir(parents=True)
    (cache / "snapshots" / "abc").mkdir(parents=True)
    (cache / "refs").mkdir(parents=True)
    (cache / "blobs" / "sha1").write_bytes(b"x" * 4000)
    (cache / "blobs" / "sha2").write_bytes(b"y" * 1500)
    (cache / "snapshots" / "abc" / "model.safetensors").symlink_to("../../blobs/sha1")
    (cache / "snapshots" / "abc" / "config.json").symlink_to("../../blobs/sha2")
    (root / "sd" / "ckpt").mkdir(parents=True)
    (root / "sd" / "ckpt" / "model.safetensors").write_bytes(b"z" * 900)
    (root / "sd" / "ckpt" / ".DS_Store").write_bytes(b"?" * 60)
    (root / "TheBloke").mkdir()
    (root / "TheBloke" / "m.gguf").write_bytes(b"g" * 700)
    for noise in ("#recycle", "@eaDir", ".Trash"):
        (root / noise / "deep").mkdir(parents=True)
        (root / noise / "deep" / "model.safetensors").write_bytes(b"!" * 10)
    return cache


def section_rule():
    print("правило — что такое папка-модель:")
    for rel, names, kind, why in (
            ("whisper/models--openai--whisper-large-v3", [], "whisper", "кэш HF под whisper/ — по имени, даже пустой"),
            ("sd/ckpt", ["model.safetensors", "config.json"], "safetensors", "папка с шардом — чекпойнт"),
            ("a/b/c/deep", ["x.safetensors"], "safetensors", "чекпойнт на любой глубине"),
            ("whisper/other", ["m.safetensors"], "safetensors", "под whisper/, но не models--… — судим по содержимому"),
            ("whisper", ["x.gguf"], "", "negative: сама whisper/ — просто папка, а не одна большая модель"),
            ("whisper/models--x/snapshots", [], "", "negative: каталог ВНУТРИ кэша сам по себе не кэш — имя проверяется на своём месте"),
            ("TheBloke", ["m.gguf", "notes.txt"], "", "negative: папка с GGUF — не папка-модель: GGUF называют по одному"),
            ("", ["stray.safetensors"], "", "negative: корень хранилища — хранилище, а не гигантская модель"),
            (".", ["stray.safetensors"], "", "negative: тот же корень, записанный точкой"),
            ("/", ["stray.safetensors"], "", "negative: и он же со слэшем")):
        got = artifact_kind(rel, names)
        check(got == kind, f"{why}: {rel or '(корень)'} → {kind or 'не модель'} (got {got or 'не модель'})")
    check(relative("/m/whisper/x", "/m") == "whisper/x" and relative("/m", "/m") == "" and relative("/m/", "/m") == "",
          "путь внутри хранилища — со слэшами и без точки: корень это пустая строка, а не «.»")


def section_walk():
    print("обход — папка целиком, и только снаружи:")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = build(root)
        found = artifact_dirs(str(root))
        check(found == [("sd/ckpt", "safetensors"),
                        ("whisper/models--Systran--faster-whisper-large-v3", "whisper")],
              f"кэш и чекпойнт названы целиком, по одному разу каждый (got {found})")
        inside = [rel for rel, _kind in found if "snapshots" in rel]
        check(inside == [],
              f"negative: снимок внутри кэша полон .safetensors-ссылок и сам подходит под правило — но он ЧАСТЬ кэша: "
              f"назвать его отдельно значит разрешить переносу увезти половину модели (got {inside})")
        noise = [rel for rel, _kind in found if rel[:1] in ("#", "@", ".")]
        check(noise == [], f"negative: #recycle, @eaDir и скрытые папки не обходятся вовсе (got {noise})")

        size, mtime = folder_weight(str(cache))
        check(size == 5500, f"вес папки — сколько весит её копия: два блоба по разу, ссылки на них не в счёт (got {size})")
        check(mtime > 0, f"и время последнего изменения внутри (got {mtime})")
        ckpt, _m = folder_weight(str(root / "sd" / "ckpt"))
        check(ckpt == 900, f"скрытые файлы (.DS_Store) в вес не входят — их не копируют (got {ckpt})")
        empty, no_time = folder_weight(str(cache / "refs"))
        check((empty, no_time) == (0, 0), f"negative: пустая папка весит ноль и времени не имеет (got {empty}, {no_time})")
        gone, _g = folder_weight(str(root / "nope"))
        check(gone == 0, "negative: папки нет — ноль, а не падение: список и удаление бегут по одному и тому же списку")


def section_both_walks():
    print("оба обхода отвечают одинаково:")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        build(root)
        (root / ms.MARKER_NAME).write_text(json.dumps({"id": "lib-a", "name": "NAS"}))
        disk = [(rel, kind, folder_weight(str(root / rel))[0]) for rel, kind in model_gc._artifact_dirs(root)]
        look = ms.StoreProbe(timeout=60).look(root, listing=True)
        lib = [(d[0], d[1], d[2]) for d in look.get("dirs", [])]
        check(disk == lib == [("sd/ckpt", "safetensors", 900),
                              ("whisper/models--Systran--faster-whisper-large-v3", "whisper", 5500)],
              f"свой диск и библиотека называют одни и те же папки с одним весом — иначе уехавший кэш потерял бы себя "
              f"по дороге (диск {disk}, библиотека {lib})")
        named = [e[0] for e in look.get("entries", [])]
        check(named == ["TheBloke/m.gguf"],
              f"по отдельности названы только GGUF вне папок-моделей: внутри кэша файлов не перечисляем (got {named})")
        check(look.get("files") == 3 and look.get("bytes") == 7100,
              f"в счёт хранилища папка входит одним предметом своего веса (got {look.get('files')}, {look.get('bytes')})")


def main():
    section_rule()
    section_walk()
    section_both_walks()
    print()
    if _fail:
        print(f"model artifacts FAILED ({len(_fail)}):")
        for msg in _fail:
            print("  - " + msg)
        return 1
    print("model artifacts OK: правило, обход целиком, вес копии, один ответ у обоих обходов")
    return 0


if __name__ == "__main__":
    sys.exit(main())
