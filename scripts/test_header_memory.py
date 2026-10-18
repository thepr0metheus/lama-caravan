#!/usr/bin/env python3
"""Value snapshot: what the headers of GGUF files said, kept across starts (caravan/admin/header_memory.py).

The first /api/state after every start of the container waited 51 s while the controller read the headers of
the 56 models of the NAS (2026-10-14, the owner's red "did not finish loading"). `HeaderMemory` keeps what a
header said, keyed by the file's path, the second it was written and its size, in memory and in
`state/gguf-headers.json`; `read_gguf_metadata_cached` asks it before it reads a header, and a walk of the models
folder (`list_models`) writes it out once at its end.

Pinned: what is recalled and what is not (another second or size is another file); that a header which said nothing
is kept in the process but never on disk; that a file the code did not write, or wrote wrong, is read as no file;
the cap; a disk that cannot be written to does not stop the walk and says so once; a restart (a second memory over
the same file) finds every fact and parses nothing; a rewritten file is parsed again; and the walk writes the file.

Run: python3 scripts/test_header_memory.py
"""
import contextlib
import io
import json
import os
import struct
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from caravan.admin import model_locator, models  # noqa: E402
from caravan.admin.header_memory import HeaderMemory  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


META = {"general.architecture": "llama", "llama.context_length": 4096, "general.languages": ["en", "ru"],
        "x.flag": True, "x.ratio": 1.5, "x.nothing": None}


def gguf_with(pairs):
    """A GGUF header of version 3 with these (key, string value) pairs — only what the walk needs to read."""
    body = b""
    for key, value in pairs:
        raw_key, raw = key.encode(), value.encode()
        body += struct.pack("<Q", len(raw_key)) + raw_key + struct.pack("<I", 8) + struct.pack("<Q", len(raw)) + raw
    return b"GGUF" + struct.pack("<IQQ", 3, 0, len(pairs)) + body


def stat_of(path):
    st = Path(path).stat()
    return int(st.st_mtime), st.st_size


class Memories:
    """Memories that read a header from a table and count how often they did."""

    def __init__(self, tmp):
        self.tmp = Path(tmp)
        self.parsed = []

    def patch(self, memory, said):
        self.real = models.header_memory, models.read_gguf_metadata
        models.header_memory = lambda: memory

        def read(path, limit_keys=256):
            self.parsed.append(Path(path).name)
            return dict(said.get(Path(path).name, {}))
        models.read_gguf_metadata = read

    def restore(self):
        models.header_memory, models.read_gguf_metadata = self.real


def section_memory(tmp):
    print("-- what is recalled")
    path = tmp / "headers.json"
    memory = HeaderMemory(path)
    check(memory.recall("/m/a.gguf", 100, 5) is None, "a file never seen: nothing")
    memory.remember("/m/a.gguf", 100, 5, META)
    check(memory.recall("/m/a.gguf", 100, 5) is META, "the header remembered, as it was (the same dict)")
    check(memory.recall("/m/a.gguf", 101, 5) is None and memory.recall("/m/a.gguf", 100, 6) is None,
          "negative: another second or another size is another file — nothing")
    check(memory.recall("/m/b.gguf", 100, 5) is None, "negative: another path — nothing")
    memory.remember("/m/e.gguf", 100, 5, {})
    check(memory.recall("/m/e.gguf", 100, 5) == {}, "a header that said nothing is recalled as nothing (read once per walk, not twice)")
    memory.remember("/m/a.gguf", 200, 7, {"general.architecture": "qwen"})
    check(memory.recall("/m/a.gguf", 100, 5) is None and memory.recall("/m/a.gguf", 200, 7) == {"general.architecture": "qwen"},
          "a file rewritten: the new header replaces the old one, which is gone")

    print("-- what is written")
    fresh = HeaderMemory(tmp / "fresh.json")
    check(fresh.flush() is False and not (tmp / "fresh.json").exists(), "nothing remembered: nothing is written, no file is made")
    fresh.remember("/m/a.gguf", 100, 5, META)
    fresh.remember("/m/e.gguf", 100, 5, {})
    check(fresh.flush() is True and (tmp / "fresh.json").exists(), "something remembered: the file is written")
    before = (tmp / "fresh.json").stat().st_mtime_ns
    check(fresh.flush() is False and (tmp / "fresh.json").stat().st_mtime_ns == before, "negative: written already — not written again")
    doc = json.loads((tmp / "fresh.json").read_text(encoding="utf-8"))
    check(doc["format"] == 1 and list(doc["files"]) == ["/m/a.gguf"] and doc["files"]["/m/a.gguf"]["mtime"] == 100
          and doc["files"]["/m/a.gguf"]["size"] == 5,
          "the file holds the header that said something, with its second and size, and not the one that said nothing")
    only_nothing = HeaderMemory(tmp / "only-nothing.json")
    only_nothing.remember("/m/e.gguf", 1, 1, {})
    check(only_nothing.flush() is False and not (tmp / "only-nothing.json").exists(),
          "negative: only a header that said nothing — no file at all")

    print("-- a start that follows")
    restarted = HeaderMemory(tmp / "fresh.json")
    hit = restarted.recall("/m/a.gguf", 100, 5)
    check(hit == META and type(hit["x.flag"]) is bool and type(hit["x.ratio"]) is float and hit["general.languages"] == ["en", "ru"]
          and hit["x.nothing"] is None, "a second memory over the file recalls every fact, each as its own type")
    check(restarted.recall("/m/e.gguf", 100, 5) is None, "…but not the header that said nothing: it is read again")
    check(restarted.recall("/m/a.gguf", 100, 6) is None, "negative: the file grew since — read again")
    restarted.remember("/m/a.gguf", 100, 5, {})
    check(restarted.flush() is True and "/m/a.gguf" not in json.loads((tmp / "fresh.json").read_text())["files"],
          "a file that has stopped saying anything leaves the disk at the next write")

    print("-- a file the code did not write")
    cases = {
        "garbage": "{not json",
        "empty": "",
        "a list": "[1, 2]",
        "another format": json.dumps({"format": 2, "files": {"/m/a.gguf": {"mtime": 100, "size": 5, "meta": META}}}),
        "no format": json.dumps({"files": {"/m/a.gguf": {"mtime": 100, "size": 5, "meta": META}}}),
        "files is a list": json.dumps({"format": 1, "files": []}),
    }
    for name, content in cases.items():
        (tmp / "bad.json").write_text(content, encoding="utf-8")
        check(HeaderMemory(tmp / "bad.json").recall("/m/a.gguf", 100, 5) is None, "negative: " + name + " — read as no file")
    (tmp / "bad.json").write_text(json.dumps({"format": 1, "files": {
        "/m/ok.gguf": {"mtime": 1, "size": 2, "meta": META},
        "/m/str-mtime.gguf": {"mtime": "1", "size": 2, "meta": META},
        "/m/no-size.gguf": {"mtime": 1, "meta": META},
        "/m/meta-list.gguf": {"mtime": 1, "size": 2, "meta": [1]},
        "/m/meta-empty.gguf": {"mtime": 1, "size": 2, "meta": {}},
        "/m/not-a-dict.gguf": 7}}), encoding="utf-8")
    mixed = HeaderMemory(tmp / "bad.json")
    check(mixed.recall("/m/ok.gguf", 1, 2) == META
          and all(mixed.recall("/m/%s.gguf" % n, 1, 2) is None for n in ("str-mtime", "no-size", "meta-list", "meta-empty", "not-a-dict")),
          "one good entry among five wrong ones: the good one is kept, the wrong ones are not")

    print("-- the cap")
    capped = HeaderMemory(tmp / "capped.json")
    capped.CAP = 3
    for index in range(5):
        capped.remember("/m/f%d.gguf" % index, index, index, {"n": index})
    capped.remember("/m/f0.gguf", 0, 0, {"n": 0})
    capped.flush()
    kept = list(json.loads((tmp / "capped.json").read_text())["files"])
    check(kept == ["/m/f3.gguf", "/m/f4.gguf", "/m/f0.gguf"],
          "past the cap the ones remembered longest ago go, a file seen again counts as new (got %s)" % kept)
    check(capped.recall("/m/f1.gguf", 1, 1) == {"n": 1}, "the process still knows what the disk dropped")

    print("-- a disk that cannot be written to")
    (tmp / "blocker").write_text("a file where a folder should be", encoding="utf-8")
    blocked = HeaderMemory(tmp / "blocker" / "inside" / "x.json")
    blocked.remember("/m/a.gguf", 1, 1, META)
    said = io.StringIO()
    with contextlib.redirect_stdout(said):
        first = blocked.flush()
        second = blocked.flush()
    check(first is False and second is False and said.getvalue().count("not kept on disk") == 1,
          "the write fails, the walk goes on, and it is said once (got %r)" % said.getvalue()[:120])
    check(blocked.recall("/m/a.gguf", 1, 1) == META, "…and the process remembers it all the same")
    odd = HeaderMemory(tmp / "odd.json")
    odd.remember("/m/o.gguf", 1, 1, {"x": object()})
    with contextlib.redirect_stdout(io.StringIO()):
        check(odd.flush() is False, "a header with a value no JSON holds does not break the walk either")

    print("-- many threads")
    busy = HeaderMemory(tmp / "busy.json")
    errors = []

    def work(worker):
        try:
            for index in range(150):
                busy.remember("/m/w%d-%d.gguf" % (worker, index), index, index, {"w": worker, "i": index})
                busy.recall("/m/w%d-%d.gguf" % (worker, index), index, index)
                if index % 25 == 0:
                    busy.flush()
        except Exception as exc:  # pragma: no cover - the check below says it
            errors.append(repr(exc))
    threads = [threading.Thread(target=work, args=(n,)) for n in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    busy.flush()
    written = json.loads((tmp / "busy.json").read_text())["files"]
    check(not errors and len(written) == 8 * 150 and all(not p.name.endswith(".tmp") for p in tmp.iterdir()),
          "8 threads remembering and writing together: no error, all %d files written, no temp file left (%s)" % (
              len(written), errors[:1]))


def section_cached(tmp):
    print("-- the cached reader")
    folder = tmp / "cached"
    folder.mkdir()
    a, b = folder / "a.gguf", folder / "b.gguf"
    a.write_bytes(b"x" * 10)
    b.write_bytes(b"y" * 10)
    said = {"a.gguf": {"general.architecture": "llama", "llama.context_length": 8192}, "b.gguf": {}}
    memory = HeaderMemory(tmp / "cached.json")
    counter = Memories(tmp)
    counter.patch(memory, said)
    try:
        first = models.read_gguf_metadata_cached(a)
        again = models.read_gguf_metadata_cached(a)
        check(first == said["a.gguf"] and again is first and counter.parsed == ["a.gguf"], "a header is read once, then recalled")
        models.read_gguf_metadata_cached(b)
        models.read_gguf_metadata_cached(b)
        check(counter.parsed == ["a.gguf", "b.gguf"], "a header that says nothing is read once in the process too")
        memory.flush()
        restart = HeaderMemory(tmp / "cached.json")
        counter.restore()
        counter.parsed.clear()
        counter.patch(restart, said)
        check(models.read_gguf_metadata_cached(a) == said["a.gguf"] and counter.parsed == [],
              "after a restart (a second memory over the same file) the header is recalled from disk, nothing is parsed")
        models.read_gguf_metadata_cached(b)
        check(counter.parsed == ["b.gguf"], "…except the one that said nothing: it is read again")
        a.write_bytes(b"x" * 11)
        models.read_gguf_metadata_cached(a)
        check(counter.parsed == ["b.gguf", "a.gguf"], "a file that grew is parsed again")
        st = a.stat()
        os.utime(a, (st.st_atime, st.st_mtime + 5))
        models.read_gguf_metadata_cached(a)
        check(counter.parsed == ["b.gguf", "a.gguf", "a.gguf"], "a file written again, the same size, is parsed again")
        missing = folder / "gone.gguf"
        models.read_gguf_metadata_cached(missing)
        models.read_gguf_metadata_cached(missing)
        check(counter.parsed[-2:] == ["gone.gguf", "gone.gguf"] and restart.recall(str(missing), 0, 0) is None,
              "negative: a file that is not there is asked of the reader each time and remembered by nobody")
    finally:
        counter.restore()


def section_walk(tmp):
    print("-- the walk writes the file")
    root = tmp / "walk"
    quant = root / "Demo-GGUF" / "x" / "Q4_K_M"
    quant.mkdir(parents=True)
    model = quant / "demo-Q4_K_M.gguf"
    model.write_bytes(gguf_with([("general.architecture", "llama"), ("llama.context_length", "1")]) + b"tensors" * 10)
    quant2 = root / "Other-GGUF" / "x" / "Q8_0"
    quant2.mkdir(parents=True)
    (quant2 / "junk-Q8_0.gguf").write_bytes(b"not a gguf at all")
    memory = HeaderMemory(tmp / "walk.json")
    real = models.header_memory, models._freshness_by_path
    models.header_memory = lambda: memory
    models._freshness_by_path = lambda: {}
    try:
        rows = models.list_models({"LLAMA_MODELS_DIR": str(root)}, locations=model_locator.Locations(()))
    finally:
        models.header_memory, models._freshness_by_path = real
    check(len(rows) == 2 and (tmp / "walk.json").exists(), "a walk of the folder: two rows, and the file is there")
    written = json.loads((tmp / "walk.json").read_text())["files"]
    check(list(written) == [str(model)] and written[str(model)]["meta"] == {"general.architecture": "llama", "llama.context_length": "1"}
          and (written[str(model)]["mtime"], written[str(model)]["size"]) == stat_of(model),
          "…holding the model that said something, and not the file that is no GGUF")
    again = HeaderMemory(tmp / "walk.json")
    check(again.recall(str(model), *stat_of(model)) == written[str(model)]["meta"], "a restart's memory recalls it")


def main():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        section_memory(tmp)
        section_cached(tmp)
        section_walk(tmp)

    print()
    if _fail:
        print(f"header memory FAILED ({len(_fail)}):")
        for m in _fail:
            print("  - " + m.splitlines()[0])
        return 1
    print("header memory OK: recalled by path, second and size; said nothing is never kept on disk; a restart parses nothing")
    return 0


if __name__ == "__main__":
    sys.exit(main())
