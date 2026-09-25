#!/usr/bin/env python3
"""Value snapshot: moving models into a library without losing one on the way.

What is pinned, each claim with its opposite:

* The plan: nothing moves unless every file is on the models disk, a plain
  file, unused and not already moving; a picked part brings its whole group;
  the target is a library that is here and has room for the move plus a
  margin — that edge pinned from both sides.
* The move, on real temporary directories: the library copy is byte for byte
  the local file, proven by sha256 read back from the library; the local copy
  goes only after the proof and the settle time, and emptied folders go with
  it.
* The library's mark: with no mark (a share that did not mount) or another
  library's, not one byte is written — the job waits, and continues once the
  right library is back.
* Interruptions: a part written past the last confirmed point is cut back to
  it, not trusted; a controller that dies mid-copy continues from its saved
  record; an outage is waited out however long, while failures with the
  library answering end the item after MAX_ERRORS, both copies kept.
* Refusing to delete: a copy that does not match twice, a different file of
  the same name in the library, a local file changed after the plan, a cell
  that started using the model, a group with one part refused — each keeps
  the local copy and names why.
* Stopping: between blocks, in the copy or in the proof; the unfinished copy
  in the library goes, the local one never.
* The runner: a file already moving is refused, a stop is on disk at once, a
  restart puts unfinished jobs back in line (not "running"), a job that
  breaks the mover fails alone, and old finished jobs leave memory and disk.

Run: python3 scripts/test_store_moves.py
"""
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from caravan.admin import store_moves as sm  # noqa: E402

# Small blocks, so a few kilobytes cross several confirmed points.
sm.CHUNK = 1000
sm.CHECKPOINT_BYTES = 3000

_fail = []
GB = 2 ** 30
#: The two ends of a move, as a plan builds them.
LOCAL_END = {"id": "local", "name": "", "root": "/m", "kind": "local"}
LIB_END = {"id": "lib-a", "name": "NAS", "root": "/mnt/lib", "kind": "library"}
#: What the libraries hold, for plans that move files back out of one.
LIB_ROWS = [{"id": "lib-a", "name": "NAS", "state": "ok", "path": "/mnt/lib", "more": 0, "files": [
    {"path": "A/a.gguf", "size": 10 * GB}, {"path": "K/k.gguf", "size": GB},
    {"path": "P/p-00001-of-00002.gguf", "size": GB}, {"path": "P/p-00002-of-00002.gguf", "size": 2 * GB},
    {"path": "L/l.gguf", "size": GB},
    {"path": "whisper/models--openai--w", "kind": "whisper", "size": 4 * GB}]}]


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def asked(fn, *a, **k):
    """What the caller gets — or the name of what broke instead. A page asking
    for its rows must be answered, not dropped: pinning the break here keeps it
    on its own line instead of taking the rest of the snapshot down with it."""
    try:
        return fn(*a, **k)
    except Exception as exc:  # noqa: BLE001 - the break IS the pinned value
        return f"{type(exc).__name__}: {exc}"


def refused(fn, *a, **k):
    try:
        fn(*a, **k)
    except sm.MoveRefused as exc:
        return exc.code
    return None


class NotPlanned:
    """A plan that was refused where the snapshot expected one. Every field a
    check reads answers with the refusal, so the pin goes red and names it —
    instead of the run dying on an exception and hiding which pin broke."""

    def __init__(self, exc):
        self.id = self.status = f"refused: {exc.code}"
        self.source = self.target = f"refused: {exc.code}"
        # One placeholder file: a check (or its message) that reads files[0]
        # gets an answer that says "refused", not an IndexError.
        self.items = [{"key": f"refused: {exc.code}", "state": "refused", "note": exc.code, "detail": "",
                       "files": [{"rel": f"refused: {exc.code}", "size": 0, "stamp": f"refused: {exc.code}",
                                  "state": "refused", "phase": "", "done": 0}]}]
        self.created_at = 0


def planned(fn, *a, **k):
    """A plan the snapshot expects to succeed."""
    try:
        return fn(*a, **k)
    except sm.MoveRefused as exc:
        return NotPlanned(exc)


def blob(n, seed):
    return bytes((i * 31 + seed * 7) % 251 for i in range(n))


class Died(BaseException):
    """The controller process dying mid-copy: nothing the mover may catch."""


class Rig:
    """A local disk and a library on real temporary directories, a clock that
    moves only when the mover sleeps, and every saved state kept."""

    def __init__(self, tmp, files, mark="lib-a"):
        self.local = Path(tmp) / "local"
        self.lib = Path(tmp) / "lib"
        self.local.mkdir()
        self.lib.mkdir()
        if mark:
            self.set_mark(mark)
        self.now = [1000.0]
        self.saves = []
        self.data = dict(files)
        for rel, data in files.items():
            p = self.local / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)

    def set_mark(self, mark_id):
        (self.lib / sm.MARKER_NAME).write_text(json.dumps({"id": mark_id, "name": "NAS"}))

    def put_library(self, rel, data):
        """A file that already lives in the library — the start of a move back."""
        p = self.lib / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        self.data[rel] = data
        return p

    def here(self):
        return {"id": "local", "name": "", "root": str(self.local), "kind": "local"}

    def there(self):
        return {"id": "lib-a", "name": "NAS", "root": str(self.lib), "kind": "library"}

    def job(self, *groups):
        items = []
        for rels in groups:
            files = [sm.MoveJob.new_file(rel, len(self.data[rel]), sm.LocalIo().stamp(str(self.local / rel)))
                     for rel in rels]
            items.append(sm.MoveJob.new_item(rels[0], files))
        return sm.MoveJob("mv-test", self.here(), self.there(), items, created_at=1)

    def job_back(self, *groups, stamped=True):
        """The same move the other way: out of the library, onto this disk.
        `stamped=False` is how a real plan leaves it — a library file is not
        stat'ed while planning."""
        items = []
        for rels in groups:
            files = [sm.MoveJob.new_file(rel, (self.lib / rel).stat().st_size,
                                         sm.LocalIo().stamp(str(self.lib / rel)) if stamped else [])
                     for rel in rels]
            items.append(sm.MoveJob.new_item(rels[0], files))
        return sm.MoveJob("mv-back", self.there(), self.here(), items, created_at=1)

    def mover(self, job, io=None, reader=None, references=None, library_ok=None, on_save=None,
              remember=None, forget=None):
        def save():
            self.saves.append(json.loads(json.dumps(job.to_json())))
            if on_save:
                on_save(job)

        def sleep(seconds):
            self.now[0] += seconds
        return sm.Mover(job, save, reader=reader or sm.LibraryReader(direct=False), io=io or sm.LocalIo(),
                        references=references, library_ok=library_ok, sleep=sleep, clock=lambda: self.now[0],
                        remember=remember, forget=forget)

    def library_files(self):
        return sorted(str(p.relative_to(self.lib)) for p in self.lib.rglob("*")
                      if p.is_file() and p.name != sm.MARKER_NAME)

    def local_files(self):
        return sorted(str(p.relative_to(self.local)) for p in self.local.rglob("*") if p.is_file())

    def phases(self):
        """(phase, done) of the first file at every save, in order."""
        return [(s["items"][0]["files"][0]["phase"], s["items"][0]["files"][0]["done"]) for s in self.saves]

    def copying(self):
        return [d for p, d in self.phases() if p == "copying"]

    def steps(self):
        """The copy's progress with repeats collapsed: a wait saves the job twice
        (waiting, running again) at the same byte."""
        seq = self.copying()
        return [d for i, d in enumerate(seq) if i == 0 or d != seq[i - 1]]


class ClockIo(sm.LocalIo):
    """LocalIo that notes the clock at every delete."""

    def __init__(self, rig):
        self.rig = rig
        self.unlinked = []

    def unlink(self, path):
        self.unlinked.append((str(path), self.rig.now[0]))
        super().unlink(path)


class FlakyIo(sm.LocalIo):
    """LocalIo that breaks where it is told to: a write crossing `break_at`
    first appends `garbage` (bytes past the last confirmed point) and then
    fails — with an OSError, or by killing the process (`died`); `bad_source`
    makes every read of the local disk fail."""

    def __init__(self, break_at=None, garbage=b"", died=False, bad_source=False):
        self.break_at = break_at
        self.garbage = garbage
        self.died = died
        self.bad_source = bad_source
        self.truncated = []

    def open_read(self, path):
        if self.bad_source and f"{os.sep}local{os.sep}" in str(path):
            raise OSError(5, "Input/output error")
        return super().open_read(path)

    def truncate(self, path, size):
        self.truncated.append(size)
        super().truncate(path, size)

    def open_append(self, path):
        return _Writer(super().open_append(path), self)


class _Writer:
    def __init__(self, fh, io):
        self.fh, self.io = fh, io

    def write(self, data):
        io = self.io
        if io.break_at is not None and self.fh.tell() + len(data) > io.break_at:
            io.break_at = None
            self.fh.write(io.garbage)
            self.fh.flush()
            if io.died:
                raise Died()
            raise OSError(5, "Input/output error")
        return self.fh.write(data)

    def flush(self):
        self.fh.flush()

    def fileno(self):
        return self.fh.fileno()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.fh.close()


class BadReader(sm.LibraryReader):
    """Reads the library back with one bit flipped in the first block, for the
    first `times` proofs."""

    def __init__(self, times):
        super().__init__(direct=False)
        self.times = times

    def chunks(self, path):
        spoil = self.times > 0
        if spoil:
            self.times -= 1
        for i, block in enumerate(super().chunks(path)):
            yield bytes([block[0] ^ 1]) + block[1:] if spoil and i == 0 else block


def answers(*seq, then=True, hook=None):
    """library_ok answering from a list, then `then` forever; hook(i) runs first."""
    calls = []

    def ask():
        i = len(calls)
        calls.append(i)
        if hook:
            hook(i)
        return seq[i] if i < len(seq) else then
    ask.calls = calls
    return ask


def section_plan():
    print("план переноса:")
    files = [
        {"path": "A/a.gguf", "sizeBytes": 10 * GB, "group": "A/a.gguf", "referenced": False},
        {"path": "B/b-00001-of-00002.gguf", "sizeBytes": 20 * GB, "group": "B/b-*-of-00002.gguf", "referenced": False},
        {"path": "B/b-00002-of-00002.gguf", "sizeBytes": 30 * GB, "group": "B/b-*-of-00002.gguf", "referenced": False},
        {"path": "C/c.gguf", "sizeBytes": GB, "group": "C/c.gguf", "referenced": True},
        {"path": "D/d-00001-of-00002.gguf", "sizeBytes": GB, "group": "D/d-*-of-00002.gguf", "referenced": False},
        {"path": "D/d-00002-of-00002.gguf", "sizeBytes": GB, "group": "D/d-*-of-00002.gguf", "referenced": True},
        {"path": "whisper/models--x", "kind": "whisper", "sizeBytes": GB, "group": "whisper/models--x", "referenced": False},
        {"path": "L/l.gguf", "sizeBytes": GB, "group": "L/l.gguf", "referenced": False},
    ]
    stores = [
        {"id": "local", "role": "local", "state": "ok", "path": "/m", "free": 900 * GB},
        {"id": "lib-a", "role": "library", "state": "ok", "path": "/mnt/lib", "name": "NAS", "free": 1000 * GB},
        {"id": "lib-b", "role": "library", "state": "not-mounted", "path": "/mnt/b",
         "detail": "the folder carries no library mark"},
        {"id": "lib-c", "role": "library", "state": "low-space", "path": "/mnt/c", "name": "Spare",
         "free": 10 * GB + sm.SPACE_MARGIN},
    ]

    class PlanIo(sm.LocalIo):
        def stamp(self, path):
            return [7, len(path)]

        def is_link(self, path):
            return path.endswith("/L/l.gguf")

    def planner(store_rows=None, listing=None, lib_files=None, refs=(), reading=()):
        # `refs` is what cells NAME, `reading` what a running cell holds open —
        # two different questions since a stopped cell's model may travel.
        held = dict(reading)
        return sm.MovePlanner(unused=lambda: listing or {"ok": True, "path": "/m", "files": files},
                              stores=lambda: store_rows or stores, io=PlanIo(), clock=lambda: 77,
                              library_files=lambda: lib_files if lib_files is not None else LIB_ROWS,
                              refs=lambda: refs,
                              holders=lambda rels: sorted({w for r in rels for w in held.get(r, ())}))

    job = planner().plan(["B/b-00002-of-00002.gguf"], "lib-a")
    item = job.items[0]
    check(len(job.items) == 1 and [f["rel"] for f in item["files"]] == ["B/b-00001-of-00002.gguf", "B/b-00002-of-00002.gguf"]
          and [f["size"] for f in item["files"]] == [20 * GB, 30 * GB],
          f"выбрана одна часть — едет вся группа, части по порядку (got {[f['rel'] for f in item['files']]})")
    check(job.id.startswith("mv-") and job.status == "queued"
          and job.source == {"id": "local", "name": "", "root": "/m", "kind": "local"}
          and job.target == {"id": "lib-a", "name": "NAS", "root": "/mnt/lib", "kind": "library"}
          and job.created_at == 77 and item["files"][0]["stamp"] == [7, len("/m/B/b-00001-of-00002.gguf")],
          f"задача знает оба конца — откуда и куда, с корнями и родом хранилища — и какой именно файл планировался "
          f"(got {job.source}, {job.target}, {item['files'][0]['stamp']})")
    both = planner().plan(["A/a.gguf", "B/b-00001-of-00002.gguf", "B/b-00002-of-00002.gguf"], "lib-a")
    check([i["key"] for i in both.items] == ["A/a.gguf", "B/b-*-of-00002.gguf"],
          f"обе части выбраны — группа всё равно одна, порядок — как выбирали (got {[i['key'] for i in both.items]})")
    for paths, to, code, why in (
            ([], "lib-a", "empty", "нечего переносить"),
            (["nope.gguf"], "lib-a", "unknown-file", "файла нет на диске моделей"),
            (["L/l.gguf"], "lib-a", "link", "ссылка, а не файл: её удаление ничего не освобождает"),
            (["A/a.gguf"], "local", "same-store", "файл уже на этом диске — переносить некуда"),
            (["A/a.gguf"], "lib-z", "no-target", "такой библиотеки нет"),
            (["A/a.gguf"], "lib-b", "target-not-mounted", "библиотека не смонтирована")):
        got = refused(planner().plan, paths, to)
        check(got == code, f"negative: {why} — отказ {code} (got {got})")

    # Названа ячейкой — не то же самое, что читается ячейкой.
    run = {"C/c.gguf": ("controller:22001",), "D/d-00002-of-00002.gguf": ("forge:22021",)}
    check(refused(planner(reading=run).plan, ["C/c.gguf"], "lib-a") == "in-use",
          "negative: файл читает ЗАПУЩЕННАЯ ячейка — отказ in-use: копию удалили бы у неё из-под рук")
    check(refused(planner(reading=run).plan, ["D/d-00001-of-00002.gguf"], "lib-a") == "in-use",
          "negative: запущенная ячейка читает ДРУГУЮ часть той же группы — группа едет целиком, значит отказ")
    stopped = planned(planner().plan, ["C/c.gguf"], "lib-a")
    check([f["rel"] for f in stopped.items[0]["files"]] == ["C/c.gguf"],
          "модель ОСТАНОВЛЕННОЙ ячейки переносится: её никто не читает, а старт вернёт файл обратно")
    try:
        planner(reading=run).plan(["C/c.gguf"], "lib-a")
        named = ""
    except sm.MoveRefused as exc:
        named = str(exc)
    check("controller:22001" in named,
          f"и отказ называет, ЧЬЯ ячейка держит файл — иначе искать её по всему флоту (got {named})")
    check(refused(planner().plan, ["A/a.gguf"], "lib-a", busy={"A/a.gguf"}) == "busy",
          "negative: файл уже едет другой задачей — отказ busy")
    check(refused(planner(listing={"ok": False, "error": "models dir not found", "files": []}).plan,
                  ["A/a.gguf"], "lib-a") == "no-source",
          "negative: диск моделей не читается — отказ, а не пустой план")
    try:
        planner().plan(["A/a.gguf"], "lib-b")
        msg = ""
    except sm.MoveRefused as exc:
        msg = str(exc)
    check("not-mounted" in msg and "no library mark" in msg, f"отказ говорит, что с библиотекой и почему (got {msg!r})")
    edge = [dict(s) for s in stores]
    check([i["key"] for i in planner(edge).plan(["A/a.gguf"], "lib-c").items] == ["A/a.gguf"],
          "места ровно на перенос и запас — едет; «мало места» у библиотеки перенос не запрещает")
    edge[3]["free"] -= 1
    check(refused(planner(edge).plan, ["A/a.gguf"], "lib-c") == "no-room",
          "negative: на байт меньше, чем перенос плюс запас, — отказ no-room")

    folder = planned(planner().plan, ["whisper/models--x"], "lib-a")
    fitem = folder.items[0]
    check((fitem["folder"], fitem["files"], fitem["size"], fitem["scanned"]) == ("whisper/models--x", [], GB, False)
          and folder.paths() == ["whisper/models--x"],
          f"папка планируется ОДНИМ пунктом: её путь и измеренный размер, список файлов пуст — внутренности обойдёт мовер в своём "
          f"потоке; путь папки занят, пока она едет (got {fitem['folder']}, {fitem['files']}, {fitem['size']})")
    check(refused(planner().plan, ["whisper/models--x"], "lib-a", busy={"whisper/models--x"}) == "busy",
          "negative: папка уже едет другой задачей — отказ busy")
    tight_dir = [dict(s) for s in stores]
    tight_dir[1]["free"] = GB + sm.SPACE_MARGIN - 1
    check(refused(planner(tight_dir).plan, ["whisper/models--x"], "lib-a") == "no-room",
          "negative: размер папки считается в проверке места, хотя файлы внутри ещё не перечислены")

    print("план в обратную сторону:")
    back = planned(planner().plan, ["K/k.gguf"], "local", source_id="lib-a")
    check(back.source == {"id": "lib-a", "name": "NAS", "root": "/mnt/lib", "kind": "library"}
          and back.target == {"id": "local", "name": "", "root": "/m", "kind": "local"}
          and [f["rel"] for f in back.items[0]["files"]] == ["K/k.gguf"] and back.items[0]["files"][0]["stamp"] == [],
          f"обратно на диск: концы поменялись местами, файл взят из списка библиотеки; штампа нет — его снимет мовер, "
          f"чтобы не ходить по сети из потока, отвечающего на запрос (got {back.source}, {back.items[0]['files'][0]['stamp']})")
    pair = planned(planner().plan, ["P/p-00002-of-00002.gguf"], "local", source_id="lib-a")
    check([f["rel"] for f in pair.items[0]["files"]] == ["P/p-00001-of-00002.gguf", "P/p-00002-of-00002.gguf"],
          f"и из библиотеки группа едет целиком (got {[f['rel'] for f in pair.items[0]['files']]})")
    for paths, to, src, code, why in (
            (["nope.gguf"], "local", "lib-a", "unknown-file", "в библиотеке такого файла нет"),
            (["K/k.gguf"], "lib-a", "lib-a", "same-store", "туда, где файл и так лежит, переносить нечего"),
            (["K/k.gguf"], "local", "lib-b", "source-not-mounted", "библиотека-источник не смонтирована"),
            (["K/k.gguf"], "local", "lib-z", "no-source", "такого хранилища-источника нет")):
        got = refused(planner().plan, paths, to, source_id=src)
        check(got == code, f"negative: {why} — отказ {code} (got {got})")
    check(refused(planner(reading={"K/k.gguf": ("controller:22001",)}).plan,
                  ["K/k.gguf"], "local", source_id="lib-a") == "in-use",
          "negative: файл в библиотеке, который читает запущенная ячейка, с места не трогаем — "
          "ссылка ячейки одна и та же в любом хранилище")
    link = planned(planner().plan, ["L/l.gguf"], "local", source_id="lib-a")
    check([f["rel"] for f in link.items[0]["files"]] == ["L/l.gguf"],
          "план ничего не спрашивает у библиотеки по сети: файл, который на этом диске сочли бы ссылкой, из неё планируется как обычный — "
          "смотреть на него будет мовер, в своём потоке")
    home = planned(planner().plan, ["whisper/models--openai--w"], "local", source_id="lib-a")
    check(home.items == [{"key": "whisper/models--openai--w", "state": "pending", "note": "", "detail": "", "errors": 0,
                          "files": [], "folder": "whisper/models--openai--w", "size": 4 * GB,
                          "links": [], "dirs": [], "scanned": False}]
          and home.paths() == ["whisper/models--openai--w"],
          f"папка возвращается тем же одним предметом, каким уехала: библиотека назвала её вид, и план не заглядывает внутрь — "
          f"внутрь пойдёт мовер (got {home.items})")
    tight = [dict(s) for s in stores]
    tight[0]["free"] = GB + sm.SPACE_MARGIN - 1
    check(refused(planner(tight).plan, ["K/k.gguf"], "local", source_id="lib-a") == "no-room",
          "negative: на этом диске нет места под возврат — отказ no-room, как и у библиотеки")
    check(refused(planner(tight).plan, ["whisper/models--openai--w"], "local", source_id="lib-a") == "no-room",
          "negative: вес папки в проверке места считается тоже — иначе кэш на 4 GB уехал бы на диск, где их нет")


def section_move():
    print("перенос на настоящих папках:")
    with tempfile.TemporaryDirectory() as tmp:
        data = blob(10_500, 1)
        rig = Rig(tmp, {"Qwen/unsloth/Q4/q.gguf": data, "Keep/other.gguf": blob(10, 2)})
        io = ClockIo(rig)
        job = rig.job(["Qwen/unsloth/Q4/q.gguf"])
        rig.mover(job, io=io, references=lambda rels: False, library_ok=answers()).run()
        f = job.items[0]["files"][0]
        check((rig.lib / "Qwen/unsloth/Q4/q.gguf").read_bytes() == data and rig.library_files() == ["Qwen/unsloth/Q4/q.gguf"],
              f"копия в библиотеке — байт в байт локальный файл, под настоящим именем, временных копий нет (got {rig.library_files()})")
        check(rig.local_files() == ["Keep/other.gguf"] and not (rig.local / "Qwen").exists() and (rig.local / "Keep").is_dir(),
              f"локальная копия удалена, опустевшие папки ушли с ней; соседи на месте (got {rig.local_files()})")
        check(job.status == "done" and job.items[0]["state"] == "done" and f["phase"] == "removed"
              and f["sha256"] == hashlib.sha256(data).hexdigest() and f["bypassed"] is False,
              f"задача закончена; в записи sha256 оригинала и честная пометка, что кэш хоста не обходили "
              f"(got {job.status}, {f['sha256'][:12]}, {f['bypassed']})")
        order = [p for i, (p, _d) in enumerate(rig.phases()) if i == 0 or p != rig.phases()[i - 1][0]]
        check(order == ["", "copying", "checking", "proven", "removed"],
              f"порядок: копия → сверка → сверено → удалено (got {order})")
        check(rig.copying() == [0, 3000, 6000, 9000],
              f"прогресс копии записан на каждой подтверждённой точке (got {rig.copying()})")
        check(os.stat(rig.lib / "Qwen/unsloth/Q4/q.gguf").st_mtime_ns == f["stamp"][1],
              "копия в библиотеке несёт время оригинала: дерево показывает возраст модели, а перенос — не скачивание")

    with tempfile.TemporaryDirectory() as tmp:
        data = blob(3000, 21)
        rig = Rig(tmp, {"M/m.gguf": data})
        job = rig.job(["M/m.gguf"])
        told = []

        def remember(store_id, rel, size, local_path):
            told.append((store_id, rel, size, local_path, os.path.exists(local_path)))
            raise RuntimeError("header store down")
        mover = rig.mover(job, references=lambda r: False, library_ok=answers())
        mover._remember = remember
        mover.run()
        check(told == [("lib-a", "M/m.gguf", 3000, str(rig.local / "M/m.gguf"), True)] and job.status == "done"
              and rig.local_files() == [],
              f"сверенный файл отдаёт заголовок на память, ПОКА локальная копия ещё есть; сломавшаяся память перенос не останавливает (got {told})")
        removed = [at for path, at in io.unlinked if path.endswith("q.gguf")]
        check(removed == [f["copiedAt"] + sm.SETTLE_S] and sm.SETTLE_S >= 60,
              f"локальную копию удаляют ровно через SETTLE_S после последнего записанного байта — не раньше; и это не ноль: "
              f"NAS с async-экспортом отвечает раньше, чем данные легли на диски (got {removed}, copied at {f['copiedAt']}, SETTLE_S {sm.SETTLE_S})")


def section_back():
    print("обратно на этот диск:")
    with tempfile.TemporaryDirectory() as tmp:
        data = blob(9000, 5)
        rig = Rig(tmp, {"Keep/other.gguf": blob(10, 2)})
        rig.put_library("Qwen/unsloth/Q4/q.gguf", data)
        io = ClockIo(rig)
        job = rig.job_back(["Qwen/unsloth/Q4/q.gguf"], stamped=False)
        told, dropped = [], []
        rig.mover(job, io=io, references=lambda rels: False, library_ok=answers(),
                  remember=lambda *a: told.append(a), forget=lambda *a: dropped.append(a)).run()
        f = job.items[0]["files"][0]
        landed = rig.local / "Qwen/unsloth/Q4/q.gguf"
        check((landed.read_bytes() if landed.exists() else b"") == data and rig.library_files() == []
              and job.status == "done",
              f"файл вернулся на этот диск байт в байт, в библиотеке его больше нет (got {rig.local_files()}, "
              f"{rig.library_files()}, {job.status})")
        check(bool(f["stamp"]) and f["sha256"] == hashlib.sha256(data).hexdigest(),
              f"штамп снял сам мовер, у себя в потоке; sha256 сверен, как и в ту сторону (got {f['stamp']}, {f['sha256'][:12]})")
        removed = [at for path, at in io.unlinked if path.endswith("q.gguf")]
        check(removed == [f["copiedAt"]],
              f"копию в библиотеке удаляют сразу после сверки: ждать нечего — читали её с того же диска, куда писали "
              f"(got {removed}, copied at {f['copiedAt']})")
        check(dropped == [("lib-a", "Qwen/unsloth/Q4/q.gguf")] and told == [],
              f"память заголовков забывает уехавший из библиотеки файл — и ничего не запоминает про свой диск (got {dropped}, {told})")

    with tempfile.TemporaryDirectory() as tmp:
        data = blob(2500, 8)
        rig = Rig(tmp, {}, mark=None)
        rig.put_library("M/m.gguf", data)
        job = rig.job_back(["M/m.gguf"], stamped=False)
        seen = []

        def hook(i, rig=rig, seen=seen):
            seen.append(rig.local_files())
            if i == 0:
                rig.set_mark("lib-a")
        rig.mover(job, references=lambda r: False, library_ok=answers(False, hook=hook)).run()
        statuses = [s["status"] for s in rig.saves]
        check(seen[0] == [] and rig.local_files() == ["M/m.gguf"] and rig.library_files() == []
              and "waiting" in statuses and job.status == "done",
              f"библиотека-источник без своей метки — ни байта оттуда не читаем: задача ждёт, и файл едет домой, только когда метка "
              f"на месте (got {seen}, {job.status})")


def section_folder():
    print("папка целиком:")
    with tempfile.TemporaryDirectory() as tmp:
        rig = Rig(tmp, {"Keep/other.gguf": blob(10, 2)})
        cache = rig.local / "whisper" / "models--Systran--x"
        (cache / "blobs").mkdir(parents=True)
        (cache / "snapshots" / "abc").mkdir(parents=True)
        (cache / "refs").mkdir(parents=True)
        (cache / "blobs" / "sha1").write_bytes(blob(4000, 11))
        (cache / "blobs" / "sha2").write_bytes(blob(1500, 12))
        (cache / "snapshots" / "abc" / "model.bin").symlink_to("../../blobs/sha1")
        (cache / "snapshots" / "abc" / "config.json").symlink_to("../../blobs/sha2")
        job = sm.MoveJob("mv-dir", rig.here(), rig.there(),
                         [sm.MoveJob.new_item("whisper/models--Systran--x", [], folder="whisper/models--Systran--x", size=5500)],
                         created_at=1)
        rig.mover(job, references=lambda r: False, library_ok=answers()).run()
        lib = rig.lib / "whisper/models--Systran--x"
        links = {str(p.relative_to(lib)): os.readlink(p) for p in lib.rglob("*") if p.is_symlink()}
        check(job.status == "done" and (lib / "blobs/sha1").read_bytes() == blob(4000, 11)
              and (lib / "blobs/sha2").read_bytes() == blob(1500, 12),
              f"папка уехала целиком: каждый файл внутри сверен и лежит на своём месте (got {job.status}, {job.items[0]['note']})")
        check(links == {"snapshots/abc/model.bin": "../../blobs/sha1", "snapshots/abc/config.json": "../../blobs/sha2"},
              f"ссылки внутри остались ССЫЛКАМИ с теми же целями: копия по ним удвоила бы байты кэша (got {links})")
        check((lib / "refs").is_dir() and not (rig.local / "whisper").exists() and rig.local_files() == ["Keep/other.gguf"],
              f"пустая папка внутри тоже переехала; на этом диске от кэша не осталось ничего, соседи целы (got {rig.local_files()})")
        rows = job.summary(now=9999)["files"]
        check([r["path"] for r in rows] == ["whisper/models--Systran--x"] and rows[0]["size"] == 5500
              and rows[0]["phase"] == "removed",
              f"страница видит ОДНУ строку — саму папку, а не тысячу файлов внутри (got {[r['path'] for r in rows]})")

    with tempfile.TemporaryDirectory() as tmp:
        rig = Rig(tmp, {"out/secret.gguf": blob(50, 13)})
        cache = rig.local / "whisper" / "models--x"
        cache.mkdir(parents=True)
        (cache / "link").symlink_to("../../out/secret.gguf")
        job = sm.MoveJob("mv-out", rig.here(), rig.there(),
                         [sm.MoveJob.new_item("whisper/models--x", [], folder="whisper/models--x", size=0)], created_at=1)
        rig.mover(job, references=lambda r: False, library_ok=answers()).run()
        check(job.items[0]["note"] == "link-out" and rig.library_files() == [] and (rig.local / "out/secret.gguf").exists()
              and (rig.local / "whisper/models--x").is_dir(),
              f"ссылка наружу папки — перенос отказывается: там она указала бы в никуда, а пойти по ней значит увезти чужой файл "
              f"(got {job.items[0]['note']}, {rig.library_files()})")

    with tempfile.TemporaryDirectory() as tmp:
        rig = Rig(tmp, {})
        cache = rig.local / "whisper" / "models--y"
        cache.mkdir(parents=True)
        (cache / "a.bin").write_bytes(blob(3000, 14))
        job = sm.MoveJob("mv-grow", rig.here(), rig.there(),
                         [sm.MoveJob.new_item("whisper/models--y", [], folder="whisper/models--y", size=3000)], created_at=1)
        added = []

        def grow(j, cache=cache, added=added):
            if not added and j.items[0]["files"] and j.items[0]["files"][0]["phase"] == "proven":
                (cache / "b.bin").write_bytes(blob(100, 15))
                added.append(True)
        rig.mover(job, references=lambda r: False, library_ok=answers(), on_save=grow).run()
        check(job.items[0]["note"] == "folder-changed" and (cache / "a.bin").exists() and (cache / "b.bin").exists()
              and (rig.lib / "whisper/models--y/a.bin").exists(),
              f"внутри папки появился новый файл — папку не удаляем: он уехал бы вместе с ней, так и не переехав "
              f"(got {job.items[0]['note']})")


    # A folder with nothing to copy: only a link and an empty directory. There
    # is no "last byte", so the settle wait has nothing to wait for and the
    # page's countdown has nothing to count.
    with tempfile.TemporaryDirectory() as tmp:
        rig = Rig(tmp, {})
        cache = rig.local / "whisper" / "models--empty"
        (cache / "inner").mkdir(parents=True)
        (cache / "here").symlink_to("inner")
        job = sm.MoveJob("mv-void", rig.here(), rig.there(),
                         [sm.MoveJob.new_item("whisper/models--empty", [], folder="whisper/models--empty", size=0)], created_at=1)
        started = rig.now[0]
        broke = asked(rig.mover(job, references=lambda r: False, library_ok=answers()).run)
        lib = rig.lib / "whisper/models--empty"
        row = asked(lambda: job.summary(now=9999)["files"][0])
        check(broke is None and job.status == "done" and lib.is_dir() and (lib / "inner").is_dir()
              and os.readlink(lib / "here") == "inner"
              and not (rig.local / "whisper").exists() and rig.now[0] == started,
              f"папка без единого файла — одни ссылки и пустые каталоги — переезжает целиком и не ждёт библиотеку: "
              f"ждать нечего, ни байта не записано (got {broke or job.status}, {job.items[0]['note']}, "
              f"ждали {rig.now[0] - started} с)")
        check(isinstance(row, dict) and row["removeIn"] == 0 and row["size"] == 0,
              f"и её строка не показывает обратного отсчёта до удаления — страница спрашивает сводку у задачи, "
              f"в которой ещё ни одного файла (got {row})")


def section_mark():
    print("метка библиотеки:")
    for mark, why in ((None, "метки нет — шара не смонтирована, под точкой монтирования локальная папка"),
                      ("lib-b", "метка ЧУЖОЙ библиотеки")):
        with tempfile.TemporaryDirectory() as tmp:
            data = blob(5000, 3)
            rig = Rig(tmp, {"M/m.gguf": data}, mark=mark)
            seen = []

            def hook(i, rig=rig, seen=seen):
                seen.append(sorted(str(p.relative_to(rig.lib)) for p in rig.lib.rglob("*")))
                if i == 1:
                    rig.set_mark("lib-a")
            job = rig.job(["M/m.gguf"])
            rig.mover(job, library_ok=answers(False, False, hook=hook), references=lambda r: False).run()
            before = [] if mark is None else [sm.MARKER_NAME]
            check(seen[:2] == [before, before],
                  f"{why}: пока метки нет, в библиотеку не записано НИ ОДНОГО байта и ни одной папки (got {seen[:2]})")
            reasons = [s["reason"] for s in rig.saves if s["status"] == "waiting"]
            check(bool(reasons) and "does not carry this library's mark" in reasons[0]
                  and (mark is None or f"(it carries {mark})" in reasons[0]),
                  f"задача ЖДЁТ и говорит почему (got {reasons[:1]})")
            check(job.status == "done" and (rig.lib / "M/m.gguf").read_bytes() == data and rig.local_files() == [],
                  "библиотека вернулась со своей меткой — перенос продолжился и закончился")


def section_interruptions():
    print("обрывы:")
    with tempfile.TemporaryDirectory() as tmp:
        data = blob(10_500, 4)
        rig = Rig(tmp, {"M/m.gguf": data})
        io = FlakyIo(break_at=6500, garbage=b"\0" * 700)
        job = rig.job(["M/m.gguf"])
        ok = answers(False, False, False, False, False, False)
        rig.mover(job, io=io, library_ok=ok, references=lambda r: False).run()
        f = job.items[0]["files"][0]
        check(io.truncated == [6000] and rig.steps() == [0, 3000, 6000, 9000],
              f"запись оборвалась после подтверждённой точки 6000 — хвост за ней отрезан, копия продолжена С НЕЁ, не с нуля "
              f"и не с конца куска (got truncated {io.truncated}, progress {rig.steps()})")
        check(job.status == "done" and (rig.lib / "M/m.gguf").read_bytes() == data and f["attempts"] == 0,
              f"итог байт в байт, и первая же сверка сошлась: мусора за точкой в файле нет (attempts {f['attempts']})")
        check(len(ok.calls) == 7 and job.items[0]["errors"] == 0,
              f"библиотека молчала шесть проверок подряд — ждали сколько нужно, это НЕ ошибки файла (calls {len(ok.calls)}, errors {job.items[0]['errors']})")

    with tempfile.TemporaryDirectory() as tmp:
        data = blob(10_500, 5)
        rig = Rig(tmp, {"M/m.gguf": data})
        job = rig.job(["M/m.gguf"])
        try:
            rig.mover(job, io=FlakyIo(break_at=6500, garbage=b"\0" * 700, died=True), library_ok=answers()).run()
            died = False
        except Died:
            died = True
        record = rig.saves[-1]
        check(died and record["items"][0]["files"][0]["synced"] == 6000 and (rig.local / "M/m.gguf").exists(),
              "контроллер умер посреди копии — на диске запись с подтверждённой точкой, локальный файл на месте")
        rig.saves.clear()
        again = sm.MoveJob.from_json(record)
        rig.mover(again, library_ok=answers(), references=lambda r: False).run()
        check(again.status == "done" and rig.copying()[:1] == [6000] and (rig.lib / "M/m.gguf").read_bytes() == data
              and again.items[0]["files"][0]["attempts"] == 0 and rig.local_files() == [],
              f"после рестарта — продолжение с 6000 по записи, итог байт в байт, локальный удалён (got {rig.copying()[:1]})")

    with tempfile.TemporaryDirectory() as tmp:
        data = blob(5000, 6)
        rig = Rig(tmp, {"M/m.gguf": data})
        job = rig.job(["M/m.gguf"])
        rig.mover(job, io=FlakyIo(bad_source=True), library_ok=answers()).run()
        item = job.items[0]
        check(item["state"] == "skipped" and item["note"] == "errors" and "Input/output error" in item["detail"]
              and item["errors"] == sm.MAX_ERRORS and rig.now[0] == 1000 + (sm.MAX_ERRORS - 1) * sm.WAIT_S,
              f"библиотека отвечает, а файл не читается — не обрыв: после {sm.MAX_ERRORS} ошибок с паузами файл пропущен с причиной "
              f"(got {item['state']}, {item['note']}, {item['errors']}, clock {rig.now[0]})")
        check((rig.local / "M/m.gguf").read_bytes() == data and rig.library_files() == [],
              "negative: пропущенный файл цел на месте, в библиотеке ни копии, ни временного куска")


def section_refusals():
    print("когда локальную копию НЕ удаляют:")
    with tempfile.TemporaryDirectory() as tmp:
        data = blob(10_500, 7)
        rig = Rig(tmp, {"M/m.gguf": data})
        job = rig.job(["M/m.gguf"])
        rig.mover(job, reader=BadReader(1), library_ok=answers(), references=lambda r: False).run()
        f = job.items[0]["files"][0]
        check(job.items[0]["state"] == "done" and f["attempts"] == 1 and rig.copying().count(0) == 2
              and (rig.lib / "M/m.gguf").read_bytes() == data,
              f"сверка не сошлась раз — кусок выброшен и скопирован заново с нуля, вторая сверка сошлась (got attempts {f['attempts']}, {rig.copying()})")
    with tempfile.TemporaryDirectory() as tmp:
        data = blob(5000, 8)
        rig = Rig(tmp, {"M/m.gguf": data})
        job = rig.job(["M/m.gguf"])
        rig.mover(job, reader=BadReader(2), library_ok=answers(), references=lambda r: False).run()
        item = job.items[0]
        check(item["state"] == "skipped" and item["note"] == "mismatch" and rig.library_files() == []
              and (rig.local / "M/m.gguf").read_bytes() == data,
              f"negative: не сошлась дважды — локальный цел, в библиотеке ничего (got {item['state']}, {item['note']}, {rig.library_files()})")
    with tempfile.TemporaryDirectory() as tmp:
        data, other = blob(5000, 9), blob(5000, 10)
        rig = Rig(tmp, {"M/m.gguf": data})
        (rig.lib / "M").mkdir()
        (rig.lib / "M/m.gguf").write_bytes(other)
        job = rig.job(["M/m.gguf"])
        rig.mover(job, library_ok=answers(), references=lambda r: False).run()
        check(job.items[0]["note"] == "name-taken" and (rig.lib / "M/m.gguf").read_bytes() == other
              and (rig.local / "M/m.gguf").read_bytes() == data and "copying" not in [p for p, _ in rig.phases()],
              "negative: в библиотеке ДРУГОЙ файл с тем же именем — не перезаписан, локальный цел, копия не начиналась")
    with tempfile.TemporaryDirectory() as tmp:
        data = blob(5000, 11)
        rig = Rig(tmp, {"M/m.gguf": data})
        (rig.lib / "M").mkdir()
        (rig.lib / "M/m.gguf").write_bytes(data)
        job = rig.job(["M/m.gguf"])
        rig.mover(job, library_ok=answers(), references=lambda r: False).run()
        check(job.items[0]["state"] == "done" and rig.local_files() == [] and rig.now[0] == 1000
              and "copying" not in [p for p, _ in rig.phases()],
              f"в библиотеке уже ТОТ ЖЕ файл — сверен без копии и без выдержки, локальный удалён (clock {rig.now[0]})")
        check(rig.local.is_dir() and not (rig.local / "M").exists(),
              "negative: опустевшая папка модели ушла, а сам каталог моделей остался, хоть и пустой")
    with tempfile.TemporaryDirectory() as tmp:
        data = blob(5000, 12)
        rig = Rig(tmp, {"M/m.gguf": data})
        job = rig.job(["M/m.gguf"])
        st = os.stat(rig.local / "M/m.gguf")
        os.utime(rig.local / "M/m.gguf", ns=(st.st_atime_ns, st.st_mtime_ns + 10 ** 9))
        rig.mover(job, library_ok=answers(), references=lambda r: False).run()
        check(job.items[0]["note"] == "local-changed" and rig.library_files() == [] and rig.local_files() == ["M/m.gguf"],
              "negative: локальный файл изменился после плана — не тот файл, что выбирали: не трогаем")
    with tempfile.TemporaryDirectory() as tmp:
        data = blob(5000, 13)
        rig = Rig(tmp, {"M/m.gguf": data})
        job = rig.job(["M/m.gguf"])
        rig.mover(job, library_ok=answers(), references=lambda r: True).run()
        check(job.items[0]["note"] == "in-use" and (rig.lib / "M/m.gguf").read_bytes() == data
              and (rig.local / "M/m.gguf").read_bytes() == data,
              "negative: ячейка начала использовать модель во время переноса — обе копии целы, локальная не удалена")
    with tempfile.TemporaryDirectory() as tmp:
        one, two = blob(4000, 14), blob(4000, 15)
        rig = Rig(tmp, {"M/m-00001-of-00002.gguf": one, "M/m-00002-of-00002.gguf": two})
        job = rig.job(["M/m-00001-of-00002.gguf", "M/m-00002-of-00002.gguf"])
        st = os.stat(rig.local / "M/m-00002-of-00002.gguf")
        os.utime(rig.local / "M/m-00002-of-00002.gguf", ns=(st.st_atime_ns, st.st_mtime_ns + 10 ** 9))
        rig.mover(job, library_ok=answers(), references=lambda r: False).run()
        check(job.items[0]["note"] == "local-changed"
              and rig.local_files() == ["M/m-00001-of-00002.gguf", "M/m-00002-of-00002.gguf"]
              and rig.library_files() == ["M/m-00001-of-00002.gguf"],
              f"группа целиком или никак: вторая часть отказана — ОБЕ локальные на месте; сверенная первая остаётся в библиотеке целой "
              f"(got local {rig.local_files()}, library {rig.library_files()})")


def section_cancel():
    print("остановка:")
    for phase, why in (("copying", "посреди копии"), ("checking", "посреди сверки")):
        with tempfile.TemporaryDirectory() as tmp:
            data = blob(10_500, 16)
            rig = Rig(tmp, {"M/m.gguf": data})
            job = rig.job(["M/m.gguf"])

            def stop(j, phase=phase):
                f = j.items[0]["files"][0]
                if f["phase"] == phase and (phase != "copying" or f["done"] >= 3000):
                    j.cancel = True
            rig.mover(job, library_ok=answers(), references=lambda r: False, on_save=stop).run()
            check(job.status == "cancelled" and job.items[0]["state"] == "cancelled" and rig.library_files() == []
                  and (rig.local / "M/m.gguf").read_bytes() == data,
                  f"стоп {why}: недописанная копия в библиотеке удалена, локальный файл цел (got {job.status}, {rig.library_files()})")
    with tempfile.TemporaryDirectory() as tmp:
        rig = Rig(tmp, {"M/m.gguf": blob(100, 17)})
        job = rig.job(["M/m.gguf"])
        job.cancel = True
        rig.mover(job, library_ok=answers()).run()
        check(job.status == "cancelled" and "running" not in [s["status"] for s in rig.saves]
              and rig.library_files() == [] and rig.local_files() == ["M/m.gguf"],
              "negative: остановлен до начала — так и не начался, ничего не тронуто")


def section_summary():
    print("сводка для страницы:")
    job = sm.MoveJob("mv-s", LOCAL_END, LIB_END, [
        sm.MoveJob.new_item("a", [sm.MoveJob.new_file("a.gguf", 100, [100, 1])]),
        sm.MoveJob.new_item("b", [sm.MoveJob.new_file("b.gguf", 300, [300, 1])]),
        sm.MoveJob.new_item("c", [sm.MoveJob.new_file("c.gguf", 50, [50, 1])])])
    job.items[0]["state"], job.items[0]["files"][0]["phase"] = "done", "removed"
    job.items[1]["files"][0].update(phase="checking", done=150)
    job.items[2].update(state="skipped", note="in-use")
    s = job.summary()
    got = (s["totalBytes"], s["movedBytes"], s["workDone"], s["workTotal"], s["items"], s["itemsDone"])
    check(got == (450, 100, 200 + 450 + 100, 900, 3, 1),
          f"работа — два прохода на файл (копия и сверка); пропущенный считается пройденным, но НЕ перенесённым (got {got})")
    check([(r["path"], r["item"], r["phase"], r["note"]) for r in s["files"]]
          == [("a.gguf", "done", "removed", ""), ("b.gguf", "pending", "checking", ""), ("c.gguf", "skipped", "", "in-use")],
          "строка на файл: путь, судьба, фаза и причина")
    # A folder still in line: the page polls every second and one of the jobs it
    # asks about has not been walked yet, so it holds no files at all.
    queued = sm.MoveJob("mv-q", LOCAL_END, LIB_END,
                        [sm.MoveJob.new_item("whisper/models--x", [], folder="whisper/models--x", size=700)])
    q = asked(queued.summary)
    check(isinstance(q, dict) and [(r["path"], r["item"], r["phase"], r["done"], r["size"], r["removeIn"]) for r in q["files"]]
          == [("whisper/models--x", "pending", "", 0, 700, 0)] and (q["workDone"], q["workTotal"]) == (0, 1400),
          f"папка, которую ещё не обошли: одна строка со своим весом, ничего не пройдено и отсчитывать нечего — "
          f"страница спрашивает сводку у каждой задачи, в том числе у стоящей в очереди (got {q})")
    wait = sm.MoveJob("mv-w", LOCAL_END, LIB_END, [
        sm.MoveJob.new_item("d", [sm.MoveJob.new_file("d.gguf", 10, [10, 1])]),
        sm.MoveJob.new_item("e", [sm.MoveJob.new_file("e-00001-of-00002.gguf", 10, [10, 1]),
                                  sm.MoveJob.new_file("e-00002-of-00002.gguf", 10, [10, 1])]),
        sm.MoveJob.new_item("f", [sm.MoveJob.new_file("f.gguf", 10, [10, 1])])])
    wait.items[0]["files"][0].update(state="proven", phase="proven", done=10, copiedAt=1000)
    wait.items[1]["files"][0].update(state="proven", phase="proven", done=10, copiedAt=1000)
    wait.items[1]["files"][1].update(phase="checking", done=5, copiedAt=1010)
    # Proven, then kept here: the file changed before the wait was over.
    wait.items[2].update(state="skipped", note="local-changed")
    wait.items[2]["files"][0].update(state="proven", phase="proven", done=10, copiedAt=1000)
    left = {r["path"]: r["removeIn"] for r in wait.summary(now=1030.5)["files"]}
    later = wait.summary(now=1200)["files"][0]["removeIn"]
    check(left == {"d.gguf": 90, "e-00001-of-00002.gguf": 0, "e-00002-of-00002.gguf": 0, "f.gguf": 0} and later == 0,
          f"сверенный файл говорит, сколько секунд ждать до удаления копии здесь (120 с после последнего байта, вверх до целой); "
          f"часть группы, пока другая ещё сверяется, — ноль; сверенный, но оставленный здесь — ноль; срок вышел — ноль (got {left}, {later})")
    check([r["removeIn"] for r in s["files"]] == [0, 0, 0],
          "negative: перенесённому, сверяемому и пропущенному ждать нечего")
    doc = job.to_json()
    check(sm.MoveJob.from_json(doc).to_json() == doc, "запись на диск и обратно — та же задача")
    old = json.loads(json.dumps(doc))
    del old["items"][1]["files"][0]["synced"], old["items"][1]["errors"]
    back = sm.MoveJob.from_json(old)
    check(back.items[1]["files"][0]["synced"] == 0 and back.items[1]["errors"] == 0,
          "negative: запись без новых полей читается с нулями, а не падает")


class ParkedRunner(sm.MoveRunner):
    """No worker: jobs stay where the snapshot left them."""

    def _ensure_worker(self):
        pass


class InlineRunner(sm.MoveRunner):
    """The worker runs in the caller's thread, so every step is in order."""

    def _ensure_worker(self):
        self._work()


class Finisher:
    def __init__(self, job, save):
        self.job, self.save = job, save

    def run(self):
        self.job.status, self.job.finished_at = "done", 1
        self.save()


class Breaker:
    def __init__(self, job, save):
        self.job = job

    def run(self):
        raise RuntimeError("boom")


class Delivers(Finisher):
    """A move that really carried everything home — items and all. Finisher
    ends the JOB; a promise to start a cell is kept only when every ITEM
    arrived, so the two stubs are not the same one."""

    def run(self):
        for item in self.job.items:
            item["state"] = "done"
        super().run()


class Skips(Finisher):
    """A move that ended well and carried nothing: every item was left where it
    was, with a reason."""

    def run(self):
        for item in self.job.items:
            item["state"], item["note"] = "skipped", "in-use"
        super().run()


def fake_planner():
    files = [{"path": "A/a.gguf", "sizeBytes": 10, "group": "A/a.gguf", "referenced": False},
             {"path": "B/b.gguf", "sizeBytes": 20, "group": "B/b.gguf", "referenced": False}]
    stores = [{"id": "local", "role": "local", "state": "ok", "path": "/m", "free": 900 * GB},
              {"id": "lib-a", "role": "library", "state": "ok", "path": "/mnt/lib", "name": "NAS", "free": 1000 * GB}]

    class StampIo(sm.LocalIo):
        def stamp(self, path):
            return [1, 2]

        def is_link(self, path):
            return False
    ticks = iter(range(100, 100000))
    return sm.MovePlanner(unused=lambda: {"ok": True, "path": "/m", "files": files}, stores=lambda: stores,
                          io=StampIo(), clock=lambda: next(ticks))


def saved_job(folder, job_id, created, status):
    job = sm.MoveJob(job_id, LOCAL_END, LIB_END,
                     [sm.MoveJob.new_item("a", [sm.MoveJob.new_file("a.gguf", 10, [10, 1])])],
                     created_at=created, status=status)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{job_id}.json").write_text(json.dumps(job.to_json()))


def section_runner():
    print("очередь переносов:")
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp) / "moves"
        r = ParkedRunner(folder, planner=fake_planner())
        first = r.start(["A/a.gguf"], "lib-a")
        check(first["status"] == "queued" and (folder / f"{first['id']}.json").exists(),
              "задача принята — в очереди и уже на диске, до первого байта")
        check(refused(r.start, ["A/a.gguf"], "lib-a") == "busy", "negative: файл уже едет — второй перенос его не берёт")
        second = r.start(["B/b.gguf"], "lib-a")
        check([s["id"] for s in r.summaries()] == [second["id"], first["id"]], "список — новые сверху")
        check(refused(r.cancel, "mv-none") == "unknown-job", "negative: неизвестный перенос — отказ")
        r.cancel(first["id"])
        check(json.loads((folder / f"{first['id']}.json").read_text())["cancel"] is True,
              "остановка сразу записана на диск: рестарт её не забудет")
        gone = {s["id"]: s for s in r.summaries()}[first["id"]]
        check((gone["status"], gone["files"][0]["item"], gone["finishedAt"] > 0) == ("cancelled", "cancelled", True),
              f"задача ещё в очереди — «Остановить» заканчивает её сразу: строка не стоит «в очереди» после нажатия "
              f"(got {gone['status']}, {gone['files'][0]['item']})")
        r2 = InlineRunner(folder, make_mover=lambda job, save: sm.Mover(job, save, io=sm.LocalIo(), sleep=lambda s: None))
        r2._make_mover = lambda job, save: (sm.Mover(job, save, sleep=lambda s: None) if job.cancel else Finisher(job, save))
        waiting = r2.resume()
        rows = {s["id"]: s for s in r2.summaries()}
        check(waiting == 1 and rows[first["id"]]["status"] == "cancelled" and rows[first["id"]]["files"][0]["item"] == "cancelled"
              and rows[second["id"]]["status"] == "done",
              f"после рестарта: остановленный в очереди так и не начался и в очередь не вернулся, второй доехал (got {waiting}, "
              f"{rows[first['id']]['status']}, {rows[second['id']]['status']})")

    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp) / "moves"
        seen = []

        class CancelsItself:
            """A mover that is stopped while it runs, and records what the stop did."""

            def __init__(self, job, save):
                self.job, self.save = job, save

            def run(self):
                inline.cancel(self.job.id)
                seen.append((self.job.status, self.job.cancel))
                self.job.status, self.job.finished_at = "cancelled", 1
                self.save()
        inline = InlineRunner(folder, planner=fake_planner(), make_mover=lambda job, save: CancelsItself(job, save))
        inline.start(["A/a.gguf"], "lib-a")
        check(seen == [("queued", True)] and inline._current is None,
              f"задачу, которую работник уже взял, «Остановить» не закрывает поверх него — только флаг, дальше решает перенос; "
              f"после задачи работник её отпускает (got {seen}, {inline._current})")

    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp) / "moves"
        saved_job(folder, "mv-held", 1, "queued")
        saved_job(folder, "mv-next", 2, "queued")
        held = ParkedRunner(folder)
        held.resume()
        held._current = "mv-held"
        held.cancel("mv-held")
        held.cancel("mv-next")
        rows = {s["id"]: s["status"] for s in held.summaries()}
        check(rows == {"mv-held": "queued", "mv-next": "cancelled"},
              f"negative: задачу, которую уже взял работник, останавливает он сам, между блоками, — здесь только флаг; "
              f"следующая в очереди заканчивается сразу (got {rows})")

    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp) / "moves"
        saved_job(folder, "mv-old", 5, "done")
        saved_job(folder, "mv-run", 6, "running")
        (folder / "mv-bad.json").write_text("not json")
        parked = ParkedRunner(folder)
        n = parked.resume()
        rows = {s["id"]: s["status"] for s in parked.summaries()}
        check(n == 1 and rows == {"mv-old": "done", "mv-run": "queued"},
              f"рестарт: незаконченная задача снова В ОЧЕРЕДИ, а не «идёт» — её поток умер со старым процессом; "
              f"битая запись пропущена (got {n}, {rows})")

    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp) / "moves"
        saved_job(folder, "mv-1", 1, "queued")
        saved_job(folder, "mv-2", 2, "queued")
        runs = []

        def make(job, save):
            runs.append(job.id)
            return Breaker(job, save) if job.id == "mv-1" else Finisher(job, save)
        r = InlineRunner(folder, make_mover=make, clock=lambda: 99)
        r.resume()
        rows = {s["id"]: s for s in r.summaries()}
        check(runs == ["mv-1", "mv-2"] and rows["mv-1"]["status"] == "failed" and rows["mv-1"]["reason"] == "RuntimeError: boom"
              and rows["mv-1"]["finishedAt"] == 99 and rows["mv-2"]["status"] == "done",
              f"задача, сломавшая перенос, падает одна и с причиной; следующая всё равно едет (got {runs}, {rows['mv-1']['status']})")

    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp) / "moves"
        for i in range(sm.KEEP_FINISHED + 2):
            saved_job(folder, f"mv-{i:02d}", i + 1, "done")
        r = ParkedRunner(folder)
        r.resume()
        kept = sorted(s["id"] for s in r.summaries())
        on_disk = sorted(p.stem for p in folder.glob("*.json"))
        check(len(kept) == sm.KEEP_FINISHED and "mv-00" not in kept and "mv-01" not in kept and on_disk == kept,
              f"законченных помним {sm.KEEP_FINISHED}: самые старые ушли из памяти и с диска (got {len(kept)}, {on_disk[:2]})")


    # Обещание «а потом запусти ячейку» живёт в манифесте: ждать приходится
    # дольше, чем живёт вкладка, а иногда и дольше, чем процесс контроллера.
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp) / "moves"
        started = []
        r = InlineRunner(folder, planner=fake_planner(), make_mover=lambda job, save: Delivers(job, save),
                         then_start=started.append)
        job = r.start(["A/a.gguf"], "lib-a", then={"start": {"hostId": "controller", "port": 22001}})
        check(started == [{"hostId": "controller", "port": 22001}],
              f"перенос довёз модель — ячейка запускается сама: тот, кто нажал «вернуть и запустить», "
              f"давно закрыл вкладку (got {started})")
        on_disk = asked(lambda: json.loads((folder / f"{job['id']}.json").read_text())["then"])
        check(on_disk == {"start": {"hostId": "controller", "port": 22001}},
              f"и обещание записано на диск: рестарт контроллера посреди копии его не теряет (got {on_disk})")

    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp) / "moves"
        started = []
        r = InlineRunner(folder, planner=fake_planner(), make_mover=lambda job, save: Breaker(job, save),
                         then_start=started.append)
        r.start(["A/a.gguf"], "lib-a", then={"start": {"hostId": "controller", "port": 22001}})
        check(started == [],
              f"negative: перенос упал — ячейку НЕ запускаем: она прочитала бы файл, которого на этом диске "
              f"ещё нет (got {started})")

    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp) / "moves"
        started = []
        r = InlineRunner(folder, planner=fake_planner(), make_mover=lambda job, save: Delivers(job, save),
                         then_start=started.append)
        r.start(["A/a.gguf"], "lib-a")
        check(started == [], "negative: у обычного переноса обещания нет — никто ничего не запускает")

    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp) / "moves"
        started = []
        r = InlineRunner(folder, planner=fake_planner(), make_mover=lambda job, save: Skips(job, save),
                         then_start=started.append)
        r.start(["A/a.gguf"], "lib-a", then={"start": {"hostId": "controller", "port": 22001}})
        check(started == [],
              f"negative: перенос закончился, но файл не увёз (пропущен с причиной) — ячейку не запускаем: "
              f"«задача done» и «модель дома» — не одно и то же (got {started})")


def section_references():
    print("кто использует файл прямо сейчас:")
    from caravan.admin import model_gc
    saved = model_gc._referenced_relpaths
    model_gc._referenced_relpaths = lambda with_owners=False: {"B/b-00001-of-00002.gguf", "C/c.gguf"}
    try:
        got = [model_gc.referenced_any(["B/b-00002-of-00002.gguf"]), model_gc.referenced_any(["C/c.gguf"]),
               model_gc.referenced_any(["A/a.gguf"]), model_gc.referenced_any([])]
    finally:
        model_gc._referenced_relpaths = saved
    check(got == [True, True, False, False],
          f"используется файл или ЛЮБАЯ часть его группы — да; чужой файл и пустой список — нет (got {got})")

    # Названа ячейкой и ЧИТАЕТСЯ ячейкой — разные вопросы. Удаление спрашивает
    # первый (удалить модель остановленной ячейки — сломать её молча), перенос
    # второй (остановленная ячейка файл не держит, а старт вернёт его).
    import time as _time
    import caravan.admin.state as admin_state_mod
    owners = {"C/c.gguf": ["box:22001"], "D/d-00001-of-00002.gguf": ["box:22002", "forge:22021"],
              "E/e.gguf": ["box:22003"]}
    keep_store = admin_state_mod.topology_store
    admin_state_mod.topology_store = lambda: {"hosts": {"box": {"lastSeen": int(_time.time()), "llamaNodes": [
        {"port": 22001, "running": True}, {"port": 22003, "running": False, "phase": "error"}]}}}
    model_gc._referenced_relpaths = lambda with_owners=False: (set(owners), owners) if with_owners else set(owners)
    try:
        held = [model_gc.holders(["C/c.gguf"]), model_gc.holders(["E/e.gguf"]),
                model_gc.holders(["D/d-00002-of-00002.gguf"]), model_gc.holders(["A/a.gguf"])]
        stale_controller = model_gc.running_owners(["controller:22001"])
    finally:
        model_gc._referenced_relpaths = saved
        admin_state_mod.topology_store = keep_store
    check(held[0] == ["box:22001"],
          f"запущенная ячейка держит свой файл — и названа поимённо (got {held[0]})")
    check(held[1] == [],
          f"negative: ячейка упала — файл она не читает, и модель может уехать (got {held[1]})")
    check(held[2] == ["forge:22021"],
          f"спрашиваем по ГРУППЕ частей; ячейка машины без отчёта — спросить нечем, считаем читающей: "
          f"отказать зря безвредно, а увезти файл из-под неё — нет; остановленная (её нет в отчёте) — свободна "
          f"(got {held[2]})")
    check(held[3] == [], "negative: файла никто не называл — держать его некому")
    check(stale_controller == {"controller:22001"},
          "negative: запись ячейки на id контроллера (до шага 6.9) не спрашивает systemd — отчёта у него нет, и "
          "она считается занятой, как любая ячейка, которую спросить нечем")

    # Ячейка на машине со скаутом — то, что сказал последний отчёт машины. Раньше
    # любая клиентская ячейка считалась работающей, и когда ячейки машины
    # контроллера переехали к её скауту, ни одну модель ячейки увезти было нельзя.
    import time as _time
    now = int(_time.time())
    admin_state_mod.topology_store = lambda: {"hosts": {
        "box": {"lastSeen": now, "llamaNodes": [{"port": 22031, "running": True},
                                                {"port": 22032, "running": False, "phase": "loading"},
                                                {"port": 22033, "running": False, "phase": "error"}]},
        "gone": {"lastSeen": now - 100000, "llamaNodes": []}}}
    try:
        busy = model_gc.running_owners(["box:22031", "box:22032", "box:22033", "box:22034", "gone:22035",
                                        "nobody:22036"])
    finally:
        admin_state_mod.topology_store = keep_store
    check("box:22031" in busy and "box:22032" in busy,
          f"ячейка скаута работает или грузит модель — держит файл (got {sorted(busy)})")
    check("box:22033" not in busy and "box:22034" not in busy,
          f"negative: упала или остановлена (в отчёте её нет) — файл свободен, модель может уехать (got {sorted(busy)})")
    check("gone:22035" in busy and "nobody:22036" in busy,
          f"отчёт машины устарел или его нет — спросить нечем, считаем занятой (got {sorted(busy)})")


def section_reader():
    print("чтение обратно:")
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "f.bin"
        data = blob(2500, 18)
        p.write_bytes(data)
        blocks = list(sm.LibraryReader(direct=False).chunks(str(p)))
        check(b"".join(blocks) == data and [len(b) for b in blocks] == [1000, 1000, 500],
              "обычное чтение — файл целиком, блоками")
    check(sm.LibraryReader().bypasses_cache is sys.platform.startswith("linux"),
          "мимо кэша читает Linux; на другой системе запись честно говорит, что кэш не обходили")
    if sys.platform.startswith("linux"):
        # Under the checkout, not /tmp: tmpfs refuses O_DIRECT.
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            p = Path(tmp) / "f.bin"
            data = blob(3 * 4096 + 17, 19)
            p.write_bytes(data)
            got = b"".join(sm.LibraryReader(direct=True).chunks(str(p)))
            check(got == data, "O_DIRECT через dd — те же байты, включая хвост не кратный блоку")
    else:
        print("  --  O_DIRECT не проверен: на этой системе его нет; проверяется на Linux")


def main():
    section_plan()
    section_move()
    section_back()
    section_folder()
    section_mark()
    section_interruptions()
    section_refusals()
    section_cancel()
    section_summary()
    section_runner()
    section_references()
    section_reader()
    print()
    if _fail:
        print(f"store moves FAILED ({len(_fail)}):")
        for m in _fail:
            print("  - " + m.splitlines()[0])
        return 1
    print("store moves OK: план, перенос, метка, обрывы, отказы от удаления, остановка, сводка, очередь")
    return 0


if __name__ == "__main__":
    sys.exit(main())
