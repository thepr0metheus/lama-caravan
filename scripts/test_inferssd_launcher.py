#!/usr/bin/env python3
"""Value snapshot: the launcher of InferSSD's cells (cells/run_inferssd.sh).

The launcher builds wici-ai's engine once, from its source at one commit, then becomes the server (exec). A build takes
minutes and needs CUDA, so every tool around it is a stand-in here: `git`, `python3`, the venv's `python` and `inferssd`,
`cmake`, `cc` and `nvcc` are scripts that write down what they were asked and make the files the launcher looks for
afterwards. The launcher sees NO other tool of the machine (the PATH is a folder of links to the plain utilities), so a
tool installed here cannot answer for a stand-in.

Pinned, each claim with the answer that would pass it wrongly:
  * a start that cannot serve says so before anything is built: no model, not a GGUF, a missing file, a part other
    than the first, a part of the model missing beside the first;
  * liburing's headers missing: the words the owner acts on, and nothing fetched;
  * the source is fetched at the pinned tag and checked against the pinned commit; another commit stops the build;
  * the build runs once: the second start fetches, installs and compiles nothing;
  * a build that stopped halfway is made again from the start by the next one, not taken for an installed engine;
  * `--install-only` ends the run before the server starts, wherever it stands; `--context` reaches the server;
  * the server gets the machine's loopback (LLAMA_SERVER_HOST, where every cell listens), a scope named after the cell, the prompt cache on the model's
    disk only when the scout says where that is, and a VRAM reserve only when the cell is pinned to one card.

Run: python3 scripts/test_inferssd_launcher.py
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LAUNCHER = ROOT / "cells" / "run_inferssd.sh"
PIN = "d326616c257585fd8e9176de1fc36fcd823c09f7"
UTILITIES = ("rm", "mkdir", "touch", "cat", "basename", "dirname", "cp", "chmod", "env")

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


# The stand-ins write one line per call to $LOG. $GIT_SHA is the commit a clone lands on; $CMAKE_FAIL fails the build.
GIT = r'''#!/bin/bash
echo "git $*" >> "$LOG"
dir=""
if [ "$1" = "-C" ]; then dir="$2"; shift 2; fi
case "$1" in
  clone)     dest="${@: -1}"; mkdir -p "$dest/.git" "$dest/framework" "$dest/scripts"; echo "${GIT_SHA:-}" > "$dest/.git/SHA" ;;
  rev-parse) cat "$dir/.git/SHA" ;;
esac
'''

# python3 of the machine: `-c` is the version check ($PY_OLD makes it fail), `-m venv DIR` makes the venv.
PYTHON3 = r'''#!/bin/bash
echo "python3 $*" >> "$LOG"
if [ "$1" = "-c" ]; then [ -z "${PY_OLD:-}" ]; exit $?; fi
if [ "$1" = "-m" ] && [ "$2" = "venv" ]; then
  mkdir -p "$3/bin"
  cp "$STUB_VENV_PYTHON" "$3/bin/python"; cp "$STUB_INFERSSD" "$3/bin/inferssd"; cp "$STUB_CMAKE" "$3/bin/cmake"
  chmod +x "$3/bin/python" "$3/bin/inferssd" "$3/bin/cmake"
fi
'''

# The venv's python: pip, and the script that writes the engine's resources file.
VENV_PYTHON = r'''#!/bin/bash
echo "venv-python $*" >> "$LOG"
if [ "$1" = "scripts/engine-resources.py" ]; then
  out=""; prev=""
  for a in "$@"; do [ "$prev" = "--output" ] && out="$a"; prev="$a"; done
  echo '{}' > "$out"
fi
'''

CMAKE = r'''#!/bin/bash
echo "cmake $*" >> "$LOG"
if [ "$1" = "--build" ] && [ -n "${CMAKE_FAIL:-}" ]; then exit 5; fi
'''

# The venv's inferssd: `serve --help` is the install's own check; any other call is the server being started.
INFERSSD = r'''#!/bin/bash
if [ "${*: -1}" = "--help" ]; then echo "inferssd $*" >> "$LOG"; exit 0; fi
{
  echo "SERVER $*"
  echo "ENV HOST=${LLAMA_SERVER_HOST-<unset>} SCOPE=${LAUNCH_SCOPE-<unset>} CACHE=${PROMPT_CACHE_DIR-<unset>} RESERVE=${VRAM_RESERVE_MIB-<unset>}"
  echo "HOME ${INFERSSD_HOME-<unset>} RESOURCES ${INFERSSD_RESOURCES-<unset>}"
} >> "$LOG"
'''

# cc -E reads `#include <liburing.h>` from stdin: $NO_URING is the machine without the headers.
CC = r'''#!/bin/bash
echo "cc $*" >> "$LOG"
cat > /dev/null
[ -z "${NO_URING:-}" ]
'''
NOP = "#!/bin/bash\nexit 0\n"
NVCC = "#!/bin/bash\necho 'nvcc stand-in'\n"


class Sandbox:
    """A home folder with the stand-in tools first on the PATH, and a library of one split model."""

    def __init__(self):
        self.dir = Path(tempfile.mkdtemp(prefix="caravan-inferssd-")).resolve()
        self.home = self.dir / "home"
        self.bin = self.dir / "bin"
        self.bin.mkdir(parents=True)
        self.home.mkdir()
        self.log = self.dir / "calls.log"
        self.log.write_text("")
        for name in UTILITIES:
            os.symlink(shutil.which(name), self.bin / name)
        for name, body in (("git", GIT), ("python3", PYTHON3), ("cc", CC), ("c++", NOP), ("nvcc", NVCC)):
            self.tool(name, body)
        self.stubs = {}
        for name, body in (("STUB_VENV_PYTHON", VENV_PYTHON), ("STUB_CMAKE", CMAKE), ("STUB_INFERSSD", INFERSSD)):
            path = self.dir / name.lower()
            path.write_text(body)
            path.chmod(0o755)
            self.stubs[name] = str(path)
        self.library = self.dir / "fast" / "DeepSeek-V4.1-Flash-1017-GGUF" / "mrfakename" / "Q8_0"
        self.library.mkdir(parents=True)
        for part in range(1, 4):
            self.part(part).write_bytes(b"x")
        self.release = self.home / "inferssd" / "releases" / PIN

    def part(self, index):
        return self.library / f"DeepSeek-V4.1-Flash-1017-Q8_0-{index:05d}-of-00003.gguf"

    def tool(self, name, body):
        path = self.bin / name
        path.write_text(body)
        path.chmod(0o755)

    def run(self, *args, env=None):
        full = {"HOME": str(self.home), "PATH": str(self.bin), "LOG": str(self.log), "GIT_SHA": PIN, **self.stubs}
        full.update(env or {})
        return subprocess.run(["/bin/bash", str(LAUNCHER), *args], env=full, capture_output=True, text=True,
                              cwd=str(self.dir), timeout=60)

    def calls(self):
        return [line for line in self.log.read_text().splitlines() if line]

    def forget(self):
        self.log.write_text("")

    def close(self):
        shutil.rmtree(self.dir, ignore_errors=True)


def refusals_before_the_build():
    box = Sandbox()
    try:
        first = str(box.part(1))
        cases = (
            ((), "no model given"),
            (("--context", "4096"), "no model given"),
            ((str(box.dir / "model.safetensors"),), "is no GGUF file"),
            ((str(box.library / "absent-00001-of-00003.gguf"),), "is missing: download the model on the /hf page first"),
            ((str(box.part(2)),), "is not the first part of its model: pick the part DeepSeek-V4.1-Flash-1017-Q8_0-00001-of-00003.gguf"),
        )
        for args, words in cases:
            r = box.run("22032", *args)
            check(r.returncode == 1 and words in r.stderr and box.calls() == [], f"{list(args) or 'no model'}: refused ({words!r}), nothing fetched or built")
        box.part(3).unlink()
        r = box.run("22032", first)
        check(r.returncode == 1 and "-00003-of-00003.gguf is missing: the model is 3 files" in r.stderr and box.calls() == [],
              "a part of the model missing beside the first: refused before the build, the part named")
        box.part(3).write_bytes(b"x")
        r = box.run("22032", "--context", "lots", first)
        check(r.returncode == 1 and "--context must be a positive number of tokens, not 'lots'" in r.stderr, "a window that is no number: refused")
        r = box.run("port", first)
        check(r.returncode == 1 and "the port must be a number" in r.stderr, "a port that is no number: refused")
    finally:
        box.close()
    # What the build needs is asked of a machine that has built nothing yet: each in a sandbox of its own, as a start that went on would leave an engine behind.
    for env, words, what in (({"NO_URING": "1"}, "sudo apt install liburing-dev", "no liburing headers: the owner's command"),
                             ({"PY_OLD": "1"}, "Python 3.9 or newer", "an old Python: refused")):
        box = Sandbox()
        try:
            r = box.run("22032", str(box.part(1)), env=env)
            check(r.returncode == 1 and words in r.stderr and not any(c.startswith("git") for c in box.calls()), f"{what}, and nothing fetched")
        finally:
            box.close()


def the_build_once_and_the_server():
    box = Sandbox()
    try:
        first = str(box.part(1))
        r = box.run("22032", first)
        calls = box.calls()
        kinds = [line.split()[0] + (" " + line.split()[1] if line.split()[0] in ("cmake", "venv-python") else "") for line in calls]
        check(r.returncode == 0, f"the first start builds and serves: {r.stderr[-300:]}")
        check(f"git clone -q --depth 1 --branch v0.1.1 https://github.com/wici-ai/inferssd.git {box.release}/source" in calls,
              "the source at the pinned tag, one commit deep, into the release of the pinned commit")
        clone = next(i for i, c in enumerate(calls) if c.startswith("git clone"))
        check(calls[clone + 1] == f"git -C {box.release}/source rev-parse HEAD", f"the clone, then its commit checked: {calls[clone:clone + 2]}")
        check(any(c == "cmake --preset linux-cuda" for c in calls)
              and any(c.startswith("cmake --build build-linux-cuda --parallel 4 --target inferssd-server inferssd-cpuprobe inferssd-ssdprobe inferssd-memprobe") for c in calls),
              "the CUDA preset, and the server and its three probes built")
        check(any("pip install -q cmake>=3.24,<5 ninja" in c and c.endswith("source/framework[hf]") for c in calls), "the framework with cmake and ninja into the venv")
        check((box.release / ".caravan-installed").is_file() and (box.release / "engine-resources.json").is_file(), "the install is marked done, beside its resources file")
        server = [c for c in calls if c.startswith("SERVER")]
        check(server == [f"SERVER serve -m {first} --port 22032 --context 32768"], f"the server: the first part, the cell's port, the window by default: {server}")
        env = next(c for c in calls if c.startswith("ENV"))
        check(env == "ENV HOST=127.0.0.1 SCOPE=caravan-cell-22032 CACHE=<unset> RESERVE=<unset>",
              f"on the machine's loopback, a scope of the cell's name; negative: no cache folder nor reserve unless told: {env}")
        check(next(c for c in calls if c.startswith("HOME")) == f"HOME {box.home}/inferssd RESOURCES {box.release}/engine-resources.json",
              "the engine's home and its resources: the pinned release")
        check(kinds.index("cmake --preset") < kinds.index("cmake --build") < kinds.index("venv-python scripts/engine-resources.py") < kinds.index("SERVER"),
              f"the steps in their order: {kinds}")

        box.forget()
        fast = box.dir / "fast"
        r = box.run("22032", "--context", "65536", first, env={"LLAMA_MODELS_DIR": str(fast), "CUDA_VISIBLE_DEVICES": "1", "LLAMA_SERVER_HOST": "10.0.0.5"})
        calls = box.calls()
        check(r.returncode == 0 and not [c for c in calls if c.split()[0] in ("git", "python3", "cmake", "venv-python", "cc")],
              f"the second start fetches, checks and builds nothing: {calls[:3]}")
        check([c for c in calls if c.startswith("SERVER")] == [f"SERVER serve -m {first} --port 22032 --context 65536"], "the window given reaches the server")
        env = next(c for c in calls if c.startswith("ENV"))
        check(env == f"ENV HOST=127.0.0.1 SCOPE=caravan-cell-22032 CACHE={fast}/.cells/22032/prompt-cache RESERVE=256",
              f"negative (2026-11-08): a host the environment says does not win — a cell listens on its machine's loopback; "
              f"the prompt cache on the model's disk; a reserve on a pinned card: {env}")
        check((fast / ".cells" / "22032").is_dir(), "the cell's folder made beside its model")

        box.forget()
        r = box.run("--install-only", "22032", first)
        check(r.returncode == 0 and "ready (install-only)" in r.stdout and not [c for c in box.calls() if c.startswith("SERVER")],
              "--install-only before the port: no server")
        r = box.run("22032", "--install-only")
        check(r.returncode == 0 and not [c for c in box.calls() if c.startswith("SERVER")], "--install-only with no model: the build alone, no refusal, no server")
    finally:
        box.close()


def a_broken_build_is_made_again():
    box = Sandbox()
    try:
        first = str(box.part(1))
        r = box.run("22032", first, env={"CMAKE_FAIL": "1"})
        check(r.returncode != 0 and not (box.release / ".caravan-installed").exists() and not [c for c in box.calls() if c.startswith("SERVER")],
              "a build that fails: no mark, no server")
        (box.release / "half-made").write_text("x")
        box.forget()
        r = box.run("22032", first)
        check(r.returncode == 0 and any(c.startswith("git clone") for c in box.calls()) and not (box.release / "half-made").exists(),
              "the next start makes the release again from the start")
        box.forget()
        r = box.run("22032", first, env={"GIT_SHA": "another"})
        check(r.returncode == 0 and not any(c.startswith("git") for c in box.calls()), "negative: an installed release is not fetched again")
    finally:
        box.close()
    box = Sandbox()
    try:
        r = box.run("22032", str(box.part(1)), env={"GIT_SHA": "0" * 40})
        check(r.returncode == 1 and f"no longer names {PIN}" in r.stderr and not any(c.startswith("cmake") for c in box.calls())
              and not (box.release / ".caravan-installed").exists(), "a tag that moved to another commit: no build, no mark")
    finally:
        box.close()


def no_cuda():
    if Path("/usr/local/cuda/bin/nvcc").exists():
        print("  --  no CUDA: this machine has /usr/local/cuda, the refusal is not reachable here")
        return
    box = Sandbox()
    try:
        (box.bin / "nvcc").unlink()
        r = box.run("22032", str(box.part(1)))
        check(r.returncode == 1 and "the CUDA toolkit is missing" in r.stderr and not any(c.startswith("git") for c in box.calls()),
              "no nvcc: refused before the clone")
        r = box.run("22032", str(box.part(1)), env={"CUDACXX": "/opt/cuda/bin/nvcc"})
        check(r.returncode == 0, "negative: CUDACXX names the compiler, and the build goes on")
    finally:
        box.close()


if __name__ == "__main__":
    for test in (refusals_before_the_build, the_build_once_and_the_server, a_broken_build_is_made_again, no_cuda):
        print(test.__name__)
        test()
    print(f"\n{'FAILED: ' + str(len(_fail)) if _fail else 'all ok'}")
    sys.exit(1 if _fail else 0)
