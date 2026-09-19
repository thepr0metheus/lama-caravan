#!/usr/bin/env python3
"""Value snapshot: how far a starting cell has read its model files.

A library start reads its files over the network for minutes, and the card had
nothing to say but a looping bar (2026-09-19). load_progress.py measures it
from the kernel alone — the process's command line, its byte count (rchar) and
its open files — against a fake /proc tree and a clock the test turns by hand.

Pinned from both sides:
* only a load that READS is measured: --no-mmap and --load-mode none|mlock
  read; nothing said, --mmap, mmap, mmap+mlock and direct I/O do not; the last
  flag wins;
* the llama-server is found among the cell's processes by its name, and the
  files by the flags that name them;
* no answer when there is nothing to measure: no llama-server yet, a mapped
  load, a size nobody knows, a kernel that does not say;
* bytes are credited in llama-server's order — weights, draft, projector — and
  an open file says which one is being read now;
* the speed needs two readings, follows a change by 0.3 of it, and is not
  pulled down by the pause in which the context is made;
* between files and after the last one the stage is setup; before any file,
  starting — a header read that closed again is not a file done;
* thirty seconds without a byte, a file open, is a stall; a file just opened
  starts that clock afresh;
* a new process starts from nothing, a multi-part GGUF is one file, a cell not
  looked at for ten minutes is forgotten;
* nothing here opens or stat()s a model file — the fake paths do not exist, and
  every open/stat outside /proc is recorded.

Run: python3 scripts/test_load_progress.py
"""
import builtins
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import caravan.admin.load_progress as lp  # noqa: E402

_fail = []
GB = 2 ** 30
MB = 2 ** 20


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


class FakeProc:
    """A /proc of our own: cmdline, io and fd symlinks per pid."""

    def __init__(self, root):
        self.root = Path(root)

    def process(self, pid, args, rchar=0, opened=()):
        folder = self.root / str(pid)
        (folder / "fd").mkdir(parents=True, exist_ok=True)
        (folder / "cmdline").write_bytes(b"\0".join(a.encode() for a in args) + b"\0")
        self.io(pid, rchar)
        self.open(pid, opened)

    def io(self, pid, rchar):
        (self.root / str(pid) / "io").write_text(
            f"rchar: {rchar}\nwchar: 0\nsyscr: 9\nsyscw: 0\nread_bytes: 0\nwrite_bytes: 0\n"
            "cancelled_write_bytes: 0\n")

    def open(self, pid, paths):
        fd = self.root / str(pid) / "fd"
        for entry in fd.iterdir():
            entry.unlink()
        for i, path in enumerate(paths, start=3):
            os.symlink(path, fd / str(i))

    def drop(self, pid):
        shutil.rmtree(self.root / str(pid), ignore_errors=True)


MODEL = "/nas/lib/m/unsloth/Q4_K_M/m-Q4_K_M.gguf"
MMPROJ = "/nas/lib/m/unsloth/default/mmproj-BF16.gguf"
DRAFT = "/disk/models/m/unsloth/default/mtp-m.gguf"
SIZES = {MODEL: (10 * GB, "lama-caravan-models"), MMPROJ: (1 * GB, "lama-caravan-models"),
         DRAFT: (512 * MB, None)}


def llama(*extra, model=MODEL, mmproj=MMPROJ, draft=None, load=("--no-mmap",)):
    args = ["/home/u/llama.cpp/build/bin/llama-server", "--host", "0.0.0.0", "--port", "22009",
            "--model", model]
    if mmproj:
        args += ["--mmproj", mmproj]
    if draft:
        args += ["--spec-type", "draft-mtp", "--model-draft", draft]
    return args + list(load) + list(extra)


def reads(*flags):
    return lp.LlamaProcess(1, ["/x/llama-server", "--model", "/m.gguf", *flags]).reads_files


def main():
    touched = []
    real_open, real_stat = builtins.open, os.stat

    def spy_open(file, *a, **k):
        if isinstance(file, str) and file.startswith(("/nas", "/disk")):
            touched.append(("open", file))
        return real_open(file, *a, **k)

    def spy_stat(path, *a, **k):
        if isinstance(path, str) and path.startswith(("/nas", "/disk")):
            touched.append(("stat", path))
        return real_stat(path, *a, **k)

    builtins.open, os.stat = spy_open, spy_stat
    try:
        with tempfile.TemporaryDirectory() as tmp:
            run(FakeProc(tmp), tmp)
    finally:
        builtins.open, os.stat = real_open, real_stat
    check(touched == [], f"ни один файл модели не открыт и не stat()-нут — только /proc (got {touched})")

    if _fail:
        print(f"FAILED ({len(_fail)}):")
        for msg in _fail:
            print("  - " + msg)
        sys.exit(1)
    print("load-progress snapshots hold")


def run(proc, root):
    print("читает ли процесс файлы:")
    check([reads(), reads("--mmap")] == [False, False], "ничего не сказано или --mmap — отображает (так по умолчанию у llama.cpp)")
    check(reads("--no-mmap") is True, "--no-mmap — читает")
    check([reads("--load-mode", m) for m in ("none", "mlock", "mmap", "mmap+mlock", "dio")] == [True, True, False, False, False],
          "--load-mode: none и mlock читают; mmap, mmap+mlock и dio — нет (dio может молча уйти в отображение)")
    check([reads("-lm", "none"), reads("--load-mode=mlock"), reads("--load-mode=mmap")] == [True, True, False],
          "короткий -lm и форма через = понимаются так же")
    check([reads("--no-mmap", "--mmap"), reads("--mmap", "--load-mode", "mlock"), reads("--no-mmap", "--direct-io"), reads("--load-mode")]
          == [False, True, False, False], "побеждает последний флаг; --load-mode без значения не считается")

    print("процесс и его файлы:")
    proc.process(41, ["/bin/bash", "/home/u/start.sh"])
    proc.process(42, llama(draft=DRAFT))
    found = lp.LlamaProcess.among({43, 42, 41}, root)
    check(found is not None and found.pid == 42, "llama-server найден среди процессов ячейки по имени, bash и пропавший pid пропущены")
    check(lp.LlamaProcess.among({41, 43}, root) is None, "нет llama-server (скрипт ещё не передал ему управление) — None")
    named = lp.LlamaProcess(42, llama(draft=DRAFT)).files()
    check(named == {"model": MODEL, "mmproj": MMPROJ, "draft": DRAFT}, f"файлы по флагам --model/--mmproj/--model-draft (got {named})")
    short = lp.LlamaProcess(1, ["/x/llama-server", "-m", "/a.gguf", "-mm", "/b.gguf", "-md", "/c.gguf", "--model", "/z.gguf"])
    check(short.files() == {"model": "/a.gguf", "mmproj": "/b.gguf", "draft": "/c.gguf"}, "короткие -m/-mm/-md; повторный флаг не перебивает первый")
    proc.drop(41)
    proc.drop(42)

    now = [1000.0]
    watch = lp.LoadWatch(proc=root, clock=lambda: now[0])
    size_of = SIZES.get

    print("чего не измерить:")
    proc.process(50, llama(load=()), rchar=5 * GB, opened=[MODEL])
    check(watch.look(22009, {50}, size_of) is None and 22009 not in watch._starts, "отображаемая загрузка — None: карточке старая строка, а не уверенные 0 %")
    proc.process(50, llama(), rchar=0, opened=[MODEL])
    check(watch.look(22009, {50}, lambda p: None if p == MMPROJ else SIZES.get(p)) is None, "размер mmproj неизвестен — None: доля неизвестного целого не число")
    check(watch.look(22009, {50}, lambda p: (0, None) if p == MMPROJ else SIZES.get(p)) is None, "нулевой размер — то же, что неизвестный")
    check(watch.look(22009, {51}, size_of) is None, "процесса нет — None")
    (proc.root / "50" / "io").unlink()
    check(watch.look(22009, {50}, size_of) is None, "ядро не отдаёт io — None")
    proc.io(50, 0)

    print("чтение весов:")
    proc.io(50, 2 * GB)
    first = watch.look(22009, {50}, size_of)
    check(first == {"read": 2 * GB, "total": 11 * GB, "stage": "reading", "files": [
        {"role": "model", "name": "m-Q4_K_M.gguf", "size": 10 * GB, "read": 2 * GB, "state": "reading", "library": "lama-caravan-models"},
        {"role": "mmproj", "name": "mmproj-BF16.gguf", "size": 1 * GB, "read": 0, "state": "waiting", "library": "lama-caravan-models"}]},
          f"первое чтение: веса читаются, mmproj ждёт, скорости и остатка ещё нет (got {first})")
    now[0] += 5
    proc.io(50, 2 * GB + 500 * MB)
    second = watch.look(22009, {50}, size_of)
    check((second["speed"], second["left"]) == (100 * MB, int((11 * GB - 2 * GB - 500 * MB) / (100 * MB))),
          f"второе чтение: скорость = прирост за время, остаток = недочитанное / скорость (got {second.get('speed')}, {second.get('left')})")
    now[0] += 5
    proc.io(50, 2 * GB + 1500 * MB)
    third = watch.look(22009, {50}, size_of)
    check(third["speed"] == int(100 * MB + 0.3 * (200 * MB - 100 * MB)), f"новая скорость сдвигает показанную на 0,3 разницы (got {third['speed']})")

    print("пауза, стоп, второй файл:")
    now[0] += 20
    third_stall = watch.look(22009, {50}, size_of)
    check(third_stall["stage"] == "reading", "20 с без байта при открытом файле — ещё чтение (CUDA стартует с открытыми весами)")
    now[0] += 10
    stalled = watch.look(22009, {50}, size_of)
    check((stalled["stage"], stalled.get("idle"), "speed" in stalled, "left" in stalled) == ("stalled", 30, False, False),
          f"30 с без байта при открытом файле — «стоит»: скорость и остаток не показаны (got {stalled})")
    proc.io(50, 10 * GB - 50 * MB)
    proc.open(50, [])
    now[0] += 5
    setup = watch.look(22009, {50}, size_of)
    check((setup["stage"], [f["state"] for f in setup["files"]], "speed" in setup) == ("setup", ["done", "waiting"], False),
          f"веса прочитаны (без 50 МБ), файлов нет — подготовка контекста; mmproj ждёт; скорости нет (got {setup['stage']}, {[f['state'] for f in setup['files']]})")
    now[0] += 40
    proc.open(50, [MMPROJ])
    reopened = watch.look(22009, {50}, size_of)
    check((reopened["stage"], [f["state"] for f in reopened["files"]], reopened["files"][0]["read"], reopened["files"][1]["read"])
          == ("reading", ["done", "reading"], 10 * GB, 0),
          f"mmproj открыт после 40 с паузы — чтение, не «стоит»: часы стоя начинаются заново; веса — целиком, mmproj пока 0 (got {reopened['stage']})")
    check(reopened["speed"] == third["speed"], "первое чтение после паузы скорость не трогает: промежуток через паузу — не скорость канала")
    now[0] += 5
    proc.io(50, 10 * GB + 300 * MB)
    mm = watch.look(22009, {50}, size_of)
    check((mm["files"][1]["read"], mm["speed"]) == (300 * MB, int(third["speed"] + 0.3 * (350 * MB / 5 - third["speed"]))),
          f"mmproj: прочитано сверх весов; скорость снова следует за чтением (got {mm['files'][1]['read']}, {mm.get('speed')})")
    proc.io(50, 11 * GB + 2 * MB)
    proc.open(50, [])
    now[0] += 5
    done = watch.look(22009, {50}, size_of)
    check((done["stage"], done["read"], [f["state"] for f in done["files"]]) == ("setup", 11 * GB, ["done", "done"]),
          "всё прочитано, файлов нет — подготовка; прочитанное не больше целого")

    proc.process(90, llama(), rchar=1 * GB, opened=[MODEL])
    watch.look(22012, {90}, size_of)
    now[0] += 5
    proc.io(90, 1 * GB + 500 * MB)
    before = watch.look(22012, {90}, size_of)["speed"]
    now[0] += 5
    proc.io(90, 10 * GB - 10 * MB)
    proc.open(90, [])
    watch.look(22012, {90}, size_of)
    now[0] += 40
    proc.io(90, 10 * GB + 200 * MB)
    proc.open(90, [MMPROJ])
    after = watch.look(22012, {90}, size_of)
    check((before, after["speed"], after["files"][1]["read"]) == (100 * MB, 100 * MB, 200 * MB),
          f"байты пришли между паузой и следующим взглядом — скорость та же: 210 МБ за 40 с не скорость канала (got {before}, {after['speed']})")
    watch.forget(22012)

    print("заголовок, перезапуск, части:")
    proc.drop(50)
    proc.process(60, llama(), rchar=40 * MB, opened=[MODEL])
    now[0] += 1
    header = watch.look(22009, {60}, size_of)
    check("speed" not in header and header["stage"] == "reading", "новый процесс — с нуля: скорости прежнего нет")
    proc.open(60, [])
    now[0] += 5
    closed = watch.look(22009, {60}, size_of)
    check((closed["stage"], closed["files"][0]["state"]) == ("starting", "waiting"),
          f"веса открыты ради заголовка и закрыты (40 МБ) — ещё старт, веса не «готовы» (got {closed['stage']}, {closed['files'][0]['state']})")
    part1 = "/nas/lib/big/Q8_0/big-Q8_0-00001-of-00003.gguf"
    part2 = "/nas/lib/big/Q8_0/big-Q8_0-00002-of-00003.gguf"
    other = "/nas/lib/big/Q8_0/big-Q8_0-extra-00002-of-00003.gguf"
    parts = {part1: (30 * GB, "lama-caravan-models")}
    proc.process(70, llama(model=part1, mmproj=None), rchar=GB, opened=[part2])
    check(watch.look(22010, {70}, parts.get)["files"][0]["state"] == "reading", "многочастный GGUF: открыта вторая часть — читаются веса")
    proc.open(70, [other])
    check(watch.look(22010, {70}, parts.get)["stage"] == "starting", "файл, чьё имя лишь начинается так же, — не часть весов")
    local = watch.look(22010, {70}, parts.get)
    check("library" in local["files"][0], "файл из библиотеки несёт её имя")
    proc.process(80, llama(model=DRAFT, mmproj=None), rchar=GB, opened=[DRAFT])
    check("library" not in watch.look(22011, {80}, size_of)["files"][0], "файл с этого диска — без библиотеки")

    print("память:")
    now[0] += 601
    watch.look(22011, {80}, size_of)
    check(sorted(watch._starts) == [22011], f"ячейка, на которую не смотрели 10 минут, забыта (got {sorted(watch._starts)})")
    watch.forget(22011)
    check(22011 not in watch._starts, "forget снимает ячейку, которая больше не грузится")


if __name__ == "__main__":
    main()
