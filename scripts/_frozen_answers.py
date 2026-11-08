"""What the caravan's programs promised to answer, kept in a file: the comparisons read it instead of running a second program.

Each comparison used to run the Python twin beside the Rust program and hold the two to each other. Python left the repository
(2026-11-02) and what it last said stayed here, in tests/frozen: an answer that changes is a difference, as it was.

An answer changed on purpose: run the comparison with --write. The file's diff in the merge request says what changed.
"""
import json
import math
import re
import socket
import subprocess
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class FrozenAnswers:
    """One comparison's file, a line per answer. An answer is found by its key and by how many times that key was asked before it, so a
    request added to a scenario moves nothing else."""

    FOLDER = ROOT / "tests" / "frozen"
    #: The answer of a key the file does not hold: a new request, or a file that was not written again.
    NOTHING = object()

    def __init__(self, name, writing=False):
        self.path = self.FOLDER / f"{name}.jsonl"
        self.writing = writing
        self.asked = Counter()
        self.seen = set()
        self.rows = {}
        if not writing:
            for line in self.path.read_text(encoding="utf-8").splitlines():
                row = json.loads(line)
                self.rows[row["key"]] = row["said"]

    def said(self, key, now):
        """What is kept for this asking of `key`. Writing, `now` is what gets kept, and it is what comes back."""
        self.asked[key] += 1
        full = key if self.asked[key] == 1 else f"{key} #{self.asked[key]}"
        self.seen.add(full)
        if self.writing:
            self.rows[full] = now
        return self.rows.get(full, self.NOTHING)

    def unasked(self):
        """Keys the file holds and a whole run never asked: a request taken out, with its answer left behind."""
        return [key for key in self.rows if key not in self.seen]

    def write(self):
        """Half of a letter a request carried stays an escape: a file of plain UTF-8 reads anywhere."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lines = (json.dumps({"key": key, "said": said}, ensure_ascii=False) for key, said in self.rows.items())
        text = "".join(re.sub("[\ud800-\udfff]", lambda half: f"\\u{ord(half.group()):04x}", line) + "\n" for line in lines)
        self.path.write_text(text, encoding="utf-8")


class OwnWords:
    """What belongs to one run and is no word of an answer: its ports, its folders, this machine's name, today, the moment, this tree's version and commit.

    A day belongs here only when the program COMPUTED it (the journal's date, a schedule's last firing). A day the program
    QUOTED — a date written in its own words, a description — is a word of the answer: it stays as written, else the promise
    is a different promise the day after the snapshot was written, and the comparison goes red on code that changed nothing
    (pipeline #581, 2026-11-04: four descriptions written on 2026-11-03). Guarded by scripts/check_frozen_day_words.py.
    """

    #: A field that holds the program's own words, written in its source. A day inside it is a word of the answer, not of the run.
    OWN_WORDS = {"description"}
    #: A number here is a moment, 2025 to 2030: nothing else the fake world says is this large and this close.
    MOMENTS = range(1_750_000_000, 1_900_000_000)
    MOMENT_WORDS = re.compile(r"(?<![0-9.])1(?:7[5-9]|8[0-9])[0-9]{7}(?:\.[0-9]+)?(?![0-9])")
    #: A file named by when it was saved.
    STAMP = re.compile(r"(?<![0-9])20[0-9]{6}-[0-9]{6}(?![0-9])")
    #: A client's id the controller drew at random (rust/crates/admin/src/proxies/client_ids.rs): said by the order the run first met
    #: it, the same on every run — a scenario makes its clients in one order.
    CLIENT_ID = re.compile(r"(?<![0-9A-Za-z_-])client-[0-9a-f]{8}(?![0-9A-Za-z_-])")
    #: A new cell's name, drawn at random the same way (rules::CellId::fresh): `c` and eight hex digits, said by the order the run first met
    #: it. A cell of before is `c<port>`, and its port is a word of the run already.
    CELL_ID = re.compile(r"(?<![0-9A-Za-z_-])c[0-9a-f]{8}(?![0-9A-Za-z_-])")

    def __init__(self, folders, ports):
        """`folders` and `ports` map each to the word it is said by."""
        now = time.time()
        machine = socket.gethostname()
        self.folders = {str(folder): word for folder, word in folders.items()}
        self.ports = dict(ports)
        self.days = {time.strftime("%Y-%m-%d", time.gmtime(now)): "<today>", time.strftime("%Y-%m-%d", time.gmtime(now - 86400)): "<yesterday>"}
        self.machines = sorted({machine, machine.split(".")[0], machine.lower(), machine.split(".")[0].lower()}, key=len, reverse=True)
        self.version = re.search(r'pub const VERSION: &str = "([^"]+)"', (ROOT / "rust/crates/admin/src/lib.rs").read_text()).group(1)
        self.commit = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        self.address = self.machine_address()
        self.clients = {}
        self.cells = {}

    @staticmethod
    def machine_address():
        """The address this machine says it is at: the interface the kernel picks towards the world, no packet sent. "" when it has none."""
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            try:
                probe.connect(("8.8.8.8", 80))
            except OSError:
                return ""
            return probe.getsockname()[0]

    def name_port(self, port, word):
        """A port the scenario opened on its way."""
        self.ports[port] = word

    def client_word(self, found):
        """The word of a client's random id: the first met is `<client 1>`."""
        return self.clients.setdefault(found.group(), f"<client {len(self.clients) + 1}>")

    def cell_word(self, found):
        """The word of a new cell's random name: the first met is `<cell 1>`."""
        return self.cells.setdefault(found.group(), f"<cell {len(self.cells) + 1}>")

    def words(self, text, quoted: bool = False):
        out = text
        for folder, word in self.folders.items():
            out = out.replace(folder, word)
        for port, word in self.ports.items():
            out = re.sub(rf"(?<![0-9]){port}(?![0-9])", word, out)
        if not quoted:
            for day, word in self.days.items():
                out = out.replace(day, word)
        out = self.STAMP.sub("<stamp>", self.MOMENT_WORDS.sub("<moment>", out))
        out = self.CLIENT_ID.sub(self.client_word, out)
        out = self.CELL_ID.sub(self.cell_word, out)
        out = re.sub(r"/run/user/[0-9]+/", "/run/user/<uid>/", out)
        out = re.sub(rf"(?<![0-9.]){re.escape(self.version)}(?![0-9.])", "<version>", out)
        if self.commit:
            out = re.sub(rf"(?<![0-9a-f]){self.commit[:7]}[0-9a-f]*(?![0-9a-f])", "<commit>", out)
        for machine in self.machines:
            out = re.sub(rf"(?<![\w-]){re.escape(machine)}(?![\w-])", "<this machine>", out)
        if self.address:
            out = re.sub(rf"(?<![0-9.]){re.escape(self.address)}(?![0-9.])", "<this machine's address>", out)
        return out

    def clean(self, value, key: str = ""):
        """`key` is the field the value sits under: it says whether the text is the program's own words, where a day is a word of the answer."""
        quoted = key in self.OWN_WORDS
        if isinstance(value, dict):
            return {self.words(name): self.clean(item, name) for name, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.clean(item, key) for item in value]
        if isinstance(value, str):
            return self.words(value, quoted)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return value
        if value != value:
            return "<not a number>"
        if value == 0 and math.copysign(1, value) < 0:
            return "<negative zero>"  # equal to 0 for Python, and an answer says it as "-0.0"
        if value in self.ports:
            return self.ports[value]
        return "<moment>" if abs(value) < 2_000_000_000 and int(value) in self.MOMENTS else value
