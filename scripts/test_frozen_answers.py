#!/usr/bin/env python3
"""Value snapshot: the file the comparisons read what was promised from (scripts/_frozen_answers.py).

Every comparison of a program stands on it: a key that comes back with another key's answer, or a word of one run that stays in an answer,
is a comparison that says nothing or goes red at random. Pinned, each with its negative: an answer is found by its key and by how many times
that key was asked; a request the file does not hold is said as NOTHING, not as a pass; a key nobody asked is named; writing keeps what it is
given and a file written reads back; half a letter stays an escape; the words of a run go, and what only looks like them stays.

Run: python3 scripts/test_frozen_answers.py
"""
import json
import socket
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _frozen_answers import FrozenAnswers, OwnWords  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


class Folder:
    """The file's folder for one test: the kept files are never touched."""

    def __init__(self):
        self.box = tempfile.TemporaryDirectory(prefix="caravan-frozen-")
        self.kept = FrozenAnswers.FOLDER

    def __enter__(self):
        FrozenAnswers.FOLDER = Path(self.box.name) / "frozen"
        return FrozenAnswers.FOLDER

    def __exit__(self, *_):
        FrozenAnswers.FOLDER = self.kept
        self.box.cleanup()


def section_the_file():
    print("a file read and written:")
    with Folder() as folder:
        writing = FrozenAnswers("one", writing=True)
        check(writing.said("GET /a", {"n": 1}) == {"n": 1}, "writing: what is given is what comes back")
        writing.said("GET /a", {"n": 2})
        writing.said("GET /b", "b")
        writing.write()
        check((folder / "one.jsonl").is_file(), "the file stands under its name, the folder made if it was not there")
        reading = FrozenAnswers("one")
        check(reading.said("GET /a", {"n": 9}) == {"n": 1}, "reading: the kept answer comes back, not the one given")
        check(reading.said("GET /a", {"n": 9}) == {"n": 2}, "the same key asked again is its second answer")
        check(reading.said("GET /a", {"n": 9}) is FrozenAnswers.NOTHING, "negative: asked a third time, nothing is kept: NOTHING, not an answer")
        check(reading.said("GET /c", "c") is FrozenAnswers.NOTHING, "negative: a request the file does not hold is NOTHING")
        check(reading.unasked() == ["GET /b"], "a key the run never asked is named")
        reading.said("GET /b", "")
        check(reading.unasked() == [], "negative: every key asked, nothing is named")


def section_half_a_letter():
    print("half a letter:")
    with Folder() as folder:
        writing = FrozenAnswers("two", writing=True)
        writing.said("a body", "half \ud83d of a letter")
        writing.write()
        text = (folder / "two.jsonl").read_text(encoding="utf-8")
        check("\\ud83d" in text and "\ud83d" not in text, "it stays an escape: the file is plain UTF-8")
        check(FrozenAnswers("two").said("a body", "") == "half \ud83d of a letter", "and it reads back as it was")


def section_own_words():
    print("the words of one run:")
    own = OwnWords({"/tmp/box-1": "<data>"}, {23456: "<port>"})
    now = time.time()
    check(own.words("in /tmp/box-1/x") == "in <data>/x", "a folder has its word")
    check(own.words("at 23456.") == "at <port>.", "a port has its word")
    check(own.words("at 123456 and 234567") == "at 123456 and 234567", "negative: digits that only hold the port stay")
    own.name_port(34567, "<other>")
    check(own.words("34567") == "<other>", "a port opened on the way can be named")
    check(own.words(time.strftime("%Y-%m-%d", time.gmtime(now))) == "<today>", "today")
    check(own.words(time.strftime("%Y-%m-%d", time.gmtime(now - 86400))) == "<yesterday>", "yesterday")
    check(own.words("2020-01-02") == "2020-01-02", "negative: another day stays")
    check(own.words("since 1780000000.25") == "since <moment>", "a moment in a text, with its fraction")
    check(own.words("1700000000") == "1700000000", "negative: a number before 2025 is no moment of this run")
    check(own.words("x-20261102-153000.json") == "x-<stamp>.json", "a file named by when it was saved")
    check(own.words("/run/user/501/bus") == "/run/user/<uid>/bus", "a user's run folder")
    check(own.words(f"v{own.version}") == "v<version>", "this tree's version")
    check(own.words(f"{own.version}.1") == f"{own.version}.1", "negative: a longer version that only starts with it stays")
    if own.commit:
        check(own.words(own.commit[:9]) == "<commit>", "this tree's commit, by any length from seven")
        check(own.words(own.commit[:6]) == own.commit[:6], "negative: six letters of it are no commit")
    machine = socket.gethostname().split(".")[0]
    check(own.words(f"on {machine}.") == "on <this machine>.", "this machine's name")
    check(own.words(f"on {machine}-other") == f"on {machine}-other", "negative: a longer name that holds it stays")
    if own.address:
        check(own.words(f"{own.address}:80") == "<this machine's address>:80", "this machine's address")
        check(own.words(f"1{own.address}") == f"1{own.address}", "negative: an address that only holds it stays")


def section_values():
    print("the words of one run, in a value:")
    own = OwnWords({"/tmp/box-2": "<data>"}, {23457: "<port>"})
    said = own.clean({"/tmp/box-2": ["/tmp/box-2/x", 23457, 1780000000, 1780000000.5, 5, True, None, 0.5]})
    check(said == {"<data>": ["<data>/x", "<port>", "<moment>", "<moment>", 5, True, None, 0.5]}, "keys, texts, ports and moments go; numbers, booleans and nothing stay")
    check(own.clean((1, 2)) == [1, 2], "a tuple reads as the list it goes out as")
    check(own.clean(float("nan")) == "<not a number>", "a value that is not equal to itself has a word: two runs compare equal")
    check(own.clean(-0.0) == "<negative zero>", "a negative zero has a word: it equals 0 for Python, and an answer says it as -0.0")
    check(own.clean(0.0) == 0 and own.clean(0) == 0, "negative: a zero stays a zero")
    check(own.clean(True) is True and own.clean(1) == 1, "negative: a boolean is no number and a small number no port")
    check(own.clean(3_000_000_000) == 3_000_000_000, "negative: past the moments a number is left alone")
    check(json.dumps(own.clean({"a": float("inf")})) == '{"a": Infinity}', "negative: an infinity is said as it is, so that a difference shows")


def main():
    section_the_file()
    section_half_a_letter()
    section_own_words()
    section_values()
    print()
    if _fail:
        print(f"frozen answers FAILED ({len(_fail)}):")
        for one in _fail:
            print("  - " + one)
        return 1
    print("frozen answers OK: the file, half a letter, the words of a run, in text and in values")
    return 0


if __name__ == "__main__":
    sys.exit(main())
