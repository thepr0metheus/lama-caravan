"""How far a starting cell has read its model files, which file it reads now,
and what is still to come.

A start from a library reads its files over the network, and minutes pass
between Start and the first answer. For all of them the card showed a looping
bar and "loading model into VRAM…" — no size, no speed, no end (asked for on
2026-09-19).

Only a start that READS its files can be measured. A mapped file is paged in as
the weights are first touched, and nothing counts that, so the command line of
the running process decides (`LlamaProcess.reads_files`); a mapped load gets no
answer and keeps the old line instead of a confident 0 %. A file in a library is
never mapped (config_builder.no_mmap_mode), so a library start is always
measured; a local one only when its loading mode reads.

What the process has read is the kernel's own count: rchar in /proc/PID/io.
That is every read, not only the model's — the rest (its launch script, /proc
and /sys at CUDA start) is kilobytes against gigabytes. Which file is being read
now comes from the process's open files: readlink on /proc/PID/fd/N names a file
without touching it. Nothing here opens or stat()s a model file, so a NAS that
stops answering cannot hold the board; sizes are the caller's to supply.
"""
import os
import re
import threading
import time

#: The order llama-server opens its files in (tools/server/server-context.cpp,
#: load_model): the weights, then the draft, then the projector, each read to
#: its end before the next is opened. The context for the weights is made in
#: between, which is why a load can pause with no file open and resume. Bytes
#: are credited to the files in this order.
ORDER = ("model", "draft", "mmproj")
#: The flags that name each file on a llama-server command line.
_FILE_FLAGS = {"-m": "model", "--model": "model",
               "-md": "draft", "--model-draft": "draft",
               "-mm": "mmproj", "--mmproj": "mmproj"}
#: --load-mode values that read the files. The others map them, and so does a
#: command line that says nothing: mapping is llama.cpp's default. Direct I/O
#: ("dio") reads too — unless the file system refuses O_DIRECT, when llama.cpp
#: quietly maps instead; a mapped load would then read as a stall, the confident
#: wrong answer this module exists to avoid, so dio is not counted as reading.
_READING_MODES = ("none", "mlock")
_PART = re.compile(r"-\d{5}-of-(\d{5})\.gguf$", re.I)


class LlamaProcess:
    """A llama-server process as the kernel shows it: its command line, the bytes
    it has read and the files it has open."""

    def __init__(self, pid, args, proc="/proc"):
        self.pid = int(pid)
        self.args = list(args)
        self._proc = str(proc)

    @classmethod
    def among(cls, pids, proc="/proc"):
        """The llama-server among a cell's processes — or None while the launch
        script has not handed over to it yet, and after it is gone."""
        for pid in sorted(pids or ()):
            try:
                with open(os.path.join(str(proc), str(pid), "cmdline"), "rb") as f:
                    raw = f.read()
            except OSError:
                continue
            args = [a.decode("utf-8", "replace") for a in raw.split(b"\0") if a]
            if args and os.path.basename(args[0]) == "llama-server":
                return cls(pid, args, proc)
        return None

    @property
    def reads_files(self):
        """Whether this process loads its files by reading them. The last of the
        loading flags wins, as llama.cpp itself warns when they are combined."""
        reads = False
        args = self.args
        for i, arg in enumerate(args):
            if arg == "--no-mmap":
                reads = True
            elif arg in ("--mmap", "-dio", "--direct-io"):
                reads = False
            elif arg in ("-lm", "--load-mode") and i + 1 < len(args):
                reads = args[i + 1] in _READING_MODES
            elif arg.startswith("--load-mode="):
                reads = arg.split("=", 1)[1] in _READING_MODES
        return reads

    def files(self):
        """{role: path} for the files its command line names."""
        found = {}
        args = self.args
        for i, arg in enumerate(args[:-1]):
            role = _FILE_FLAGS.get(arg)
            if role and role not in found:
                found[role] = args[i + 1]
        return found

    def bytes_read(self):
        """What the process has read so far (rchar), or None when the kernel
        does not say — the process is gone, or not ours to look at."""
        try:
            with open(os.path.join(self._proc, str(self.pid), "io"), encoding="ascii") as f:
                for line in f:
                    if line.startswith("rchar:"):
                        return int(line.split(":", 1)[1])
        except (OSError, ValueError):
            return None
        return None

    def open_paths(self):
        """The paths of the files it has open now."""
        folder = os.path.join(self._proc, str(self.pid), "fd")
        try:
            names = os.listdir(folder)
        except OSError:
            return set()
        paths = set()
        for name in names:
            try:
                paths.add(os.readlink(os.path.join(folder, name)))
            except OSError:
                continue
        return paths


class LoadFile:
    """One file a start reads: its role, where this host reads it, how big it is
    and, when it is read from a library, which one."""

    def __init__(self, role, path, size, library=None):
        self.role = role
        self.path = str(path)
        self.size = int(size)
        self.library = library

    @classmethod
    def of(cls, process, size_of):
        """The files `process` will read, in the order it reads them — or [] when
        a size is not known: a share of an unknown whole is not a number."""
        named = process.files()
        files = []
        for role in ORDER:
            if role not in named:
                continue
            found = size_of(named[role])
            if not found or not found[0]:
                return []
            files.append(cls(role, named[role], found[0], found[1]))
        return files

    def is_among(self, paths):
        """Whether this file is one of `paths`. A multi-part GGUF is named by its
        first part, and llama.cpp opens all of them at once."""
        if self.path in paths:
            return True
        m = _PART.search(self.path)
        if not m:
            return False
        stem = self.path[: m.start()]
        rest = re.compile(r"-\d{5}-of-" + m.group(1) + r"\.gguf$", re.I)
        return any(p.startswith(stem) and rest.fullmatch(p[len(stem):]) for p in paths)


class _Start:
    """One start being watched: its process, its files, and what the readings
    so far add up to."""

    def __init__(self, pid, files, now, rules):
        self.pid = pid
        self.files = files
        self.rules = rules
        self.last = None
        self.was_reading = False
        self.moved = now
        self.speed = None
        self.looked = now

    def reading(self, got, opened, now):
        """The answer for one more reading: `got` bytes read in all, `opened` the
        paths open now."""
        rules = self.rules
        self.looked = now
        at = next((i for i, f in enumerate(self.files) if f.is_among(opened)), None)
        if self.last is not None and got > self.last[1]:
            self.moved = now
            # Only a stretch read with a file open all along is a speed: the
            # context is made between two files, and a reading across that
            # pause would pull the speed down for no slower a link.
            if at is not None and self.was_reading and now > self.last[0]:
                rate = (got - self.last[1]) / (now - self.last[0])
                self.speed = rate if self.speed is None else self.speed + rules.PACE * (rate - self.speed)
        if at is not None and not self.was_reading:
            self.moved = now  # a file was just opened: the stall clock starts here
        self.last = (now, got)
        self.was_reading = at is not None

        total = sum(f.size for f in self.files)
        rows, before = [], 0
        for i, f in enumerate(self.files):
            credit = max(0, min(f.size, got - before))
            before += f.size
            if at is not None:
                state = "done" if i < at else "reading" if i == at else "waiting"
                credit = f.size if i < at else credit if i == at else 0
            else:
                # Nothing open. Being seen open is not enough to be done:
                # llama.cpp may open the weights once for their header alone,
                # close them, and open them again to load.
                state = "done" if credit >= f.size * rules.NEARLY else "waiting"
            row = {"role": f.role, "name": os.path.basename(f.path), "size": f.size,
                   "read": credit, "state": state}
            if f.library:
                row["library"] = f.library
            rows.append(row)

        answer = {"read": min(got, total), "total": total, "files": rows}
        if at is None:
            answer["stage"] = "setup" if any(r["state"] == "done" for r in rows) else "starting"
            return answer
        idle = now - self.moved
        if idle >= rules.STALL:
            answer.update(stage="stalled", idle=int(idle))
            return answer
        answer["stage"] = "reading"
        if self.speed:
            answer["speed"] = int(self.speed)
            answer["left"] = int(max(0, total - got) / self.speed)
        return answer


class LoadWatch:
    """What each starting cell has read, remembered between the board's looks:
    a speed needs two readings, and a stall is a reading that did not move.

    One object per controller process; the board builds cards from several
    threads, hence the lock. A cell that stops loading is forgotten the next
    time anyone looks, or after FORGET seconds unseen."""

    #: How far one new speed reading moves the shown one: enough to follow a
    #: real change within a few looks, not so far that one slow stretch makes
    #: the time left jump. The same weight as the moves on /models.
    PACE = 0.3
    #: Seconds without a byte, a file open, before the load is called stalled.
    #: CUDA starts with the weights' file open and nothing read yet, for up to
    #: a few seconds on this fleet; a dead share never answers at all.
    STALL = 30.0
    #: With no file open, a file this much accounted for is done. The rest is
    #: what a load may skip (tensors it has no use for), not what is to come.
    NEARLY = 0.9
    FORGET = 600.0

    def __init__(self, proc="/proc", clock=time.monotonic):
        self._proc = proc
        self._clock = clock
        self._starts = {}
        self._lock = threading.Lock()

    def look(self, port, pids, size_of):
        """The load of the cell on `port` now — or None when it cannot be
        measured: no llama-server yet, a mapped load, a size not known, a
        kernel that does not answer. `size_of(path)` → (bytes, library name or
        None), or None when not known."""
        now = self._clock()
        process = LlamaProcess.among(pids, self._proc)
        with self._lock:
            for key in [k for k, s in self._starts.items() if now - s.looked > self.FORGET]:
                del self._starts[key]
            if process is None or not process.reads_files:
                self._starts.pop(port, None)
                return None
            start = self._starts.get(port)
            if start is None or start.pid != process.pid:
                files = LoadFile.of(process, size_of)
                if not files:
                    self._starts.pop(port, None)
                    return None
                start = self._starts[port] = _Start(process.pid, files, now, self)
            got = process.bytes_read()
            if got is None:
                return None
            return start.reading(got, process.open_paths(), now)

    def forget(self, port):
        """Drop what is known about the cell on `port` — it is not loading."""
        with self._lock:
            self._starts.pop(port, None)


#: The controller's one watch. The board asks it about every starting cell.
LOAD_WATCH = LoadWatch()
