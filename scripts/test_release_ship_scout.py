#!/usr/bin/env python3
"""What a delivery says of the scout it carries (deploy/nas/release_ship.py): the content the controller follows by.

The controller hands a release to the machines by itself, and only when the scout in it changed (rust/crates/admin/src/fleet/scout_follow.rs).
It reads that from `content` in scout-bundle.json: the program's bytes and its scripts' tree. Pinned here by values, with a fake world:

- one program and one tree are one content; another program or another tree is another (negative: the archive's own times are not in it);
- the facts the release brings carry the content beside the bundle's sum;
- what the running release says of its scout: its facts, or nothing for none, for an unreadable file and for one that is no object;
- the line the delivery ends with: the same scout, a changed one, and one said for the first time.

The public mirror carries no deploy/nas/: there the test says so and passes.

Run: python3 scripts/test_release_ship_scout.py
"""
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAS = ROOT / "deploy" / "nas"


class FakeRun:
    """git as the delivery asks it: the scripts' tree by name, the release's files as an empty archive."""

    def __init__(self, tree):
        self.tree = tree

    def __call__(self, command, **_):
        if "rev-parse" in command:
            return subprocess.CompletedProcess(command, 0, stdout=self.tree.encode() + b"\n")
        return subprocess.CompletedProcess(command, 0, stdout=b"")


class FakeMachines:
    """The two machines: what was sent where, a file's sum as it arrived, and the running release's facts."""

    def __init__(self, current=b""):
        self.current = current
        self.files = {}

    def on(self, host, command, stdin=None):
        if command.startswith("cat > "):
            self.files[command.removeprefix("cat > ")] = stdin
            return b""
        if command.startswith("sha256sum "):
            return hashlib.sha256(self.files[command.removeprefix("sha256sum ")]).hexdigest().encode() + b"  file\n"
        if command.startswith("cat ") and "current/scout-bundle.json" in command:
            return self.current
        return b""


class Check:
    def __init__(self):
        self.failed = []

    def that(self, ok, words):
        if not ok:
            self.failed.append(words)


def load():
    spec = importlib.util.spec_from_file_location("release_ship", NAS / "release_ship.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["release_ship"] = module
    spec.loader.exec_module(module)
    return module


def contents(module, check):
    ship = lambda tree: module.ReleaseShip(machines=FakeMachines(), run=FakeRun(tree))  # noqa: E731
    one = ship("t1").content(b"program")
    check.that(one == ship("t1").content(b"program"), "one program and one tree are not one content")
    check.that(len(one) == 64 and int(one, 16) >= 0, f"the content is no sum: {one}")
    check.that(one != ship("t1").content(b"program2"), "negative: another program is the same content")
    check.that(one != ship("t2").content(b"program"), "negative: another tree of scripts is the same content")
    at = lambda moment: module.ReleaseShip(machines=FakeMachines(), run=FakeRun("t1"), clock=lambda: moment)  # noqa: E731
    check.that(at(1.0).content(b"program") == at(9.0).content(b"program"), "negative: the moment of the build is in the content")


def facts_brought(module, check):
    machines = FakeMachines()
    ship = module.ReleaseShip(machines=machines, run=FakeRun("t1"))
    ship.prune = lambda: None
    bundle = b"the bundle"
    ship.bring("abcd1234", {}, b"", bundle, "c0ffee")
    facts = json.loads(machines.files[f"{ship.FOLDER}/releases/abcd1234.new/{ship.BUNDLE_FACTS}"])
    check.that(facts == {"commit": "abcd1234", "sha256": hashlib.sha256(bundle).hexdigest(), "bytes": len(bundle), "content": "c0ffee"}, f"the facts brought: {facts}")


def running(module, check):
    said = lambda current: module.ReleaseShip(machines=FakeMachines(current), run=FakeRun("t1")).running_scout()  # noqa: E731
    facts = {"commit": "aaaa1111", "sha256": "ff", "bytes": 3, "content": "c1"}
    check.that(said(json.dumps(facts).encode()) == facts, "the running release's facts are not read")
    for nothing in (b"", b"  \n", b"not json", b"[1, 2]"):
        check.that(said(nothing) == {}, f"negative: {nothing!r} reads as something")


def lines(module, check):
    line = module.ReleaseShip.scouts_line
    same = line({"commit": "aaaa1111", "content": "c1"}, "c1")
    check.that("aaaa1111" in same and "keep theirs" in same, f"the same scout: {same}")
    changed = line({"commit": "aaaa1111", "content": "c1"}, "c2")
    check.that("changed since aaaa1111" in changed and "next report" in changed, f"a changed scout: {changed}")
    first = line({"commit": "aaaa1111", "sha256": "ff"}, "c2")
    check.that("first time" in first and "next report" in first, f"negative: a release that said nothing is not the same scout: {first}")
    check.that("first time" in line({}, "c2"), "no running release")


def main():
    if not (NAS / "release_ship.py").is_file():
        print("release ship scout: skipped, this copy carries no deploy/nas/")
        return 0
    module = load()
    check = Check()
    for step in (contents, facts_brought, running, lines):
        step(module, check)
    if check.failed:
        print("\n".join(check.failed))
        raise SystemExit(f"release ship scout: {len(check.failed)} failed")
    print("release ship scout: ok — one content for one scout, brought beside the bundle's sum, and said at the delivery's end")
    return 0


if __name__ == "__main__":
    sys.exit(main())
