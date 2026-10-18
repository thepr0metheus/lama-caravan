#!/usr/bin/env python3
"""Value snapshot: the launchers of the voice cells (cells/run_personaplex.sh, cells/run_lfm_audio.sh,
cells/run_vllm_omni.sh, cells/run_minicpm_omni.sh).

A launcher is what a custom-command cell runs: it installs its engine once, then becomes the server (exec). The
engines are tens of gigabytes and need a GPU, so the tools around them are stand-ins here: `uv`, `git`, `python3` and
the venv's `python` are scripts that write down what they were asked and make the files the launcher looks for
afterwards. What is pinned is what the launcher decides: which tool it runs with which arguments, in which order,
what it leaves alone the second time, what it does when a step fails, and what the server process finally gets
(arguments, environment, folder). `sed` and `tar` are the machine's own: the one patch the PersonaPlex launcher makes to
the source is a `sed` line, and BSD and GNU `sed` disagree about `-i`. The launcher sees NO other tool of the machine
(the PATH is a folder of links to the plain utilities), so a `uv` or a `git` installed here cannot answer for the stand-in.

Pinned, each claim with the answer that would pass it wrongly:
  * a missing weight file stops the launcher BEFORE anything is installed, and says which file is missing;
  * the install runs once: the second start fetches nothing, installs nothing, checks out nothing;
  * an install that stopped halfway is FINISHED by the next start (a venv that has a python is not a venv that is done);
  * a failing step stops the launcher: no later step runs, no server starts;
  * the source is fetched at ONE commit, and a checkout that is already on it is not repeated;
  * the patch touches the one unconditional hub call in each of the two files and no other line of them;
  * `--install-only` ends the run before the server starts, wherever it stands among the arguments, and the server
    starts without it;
  * the server is started with the weights of the models library and with the hub OFF (HF_HUB_OFFLINE=1), with the
    compiler off (NO_TORCH_COMPILE), and WITHOUT the machine's LD_LIBRARY_PATH (older CUDA libraries shadow torch's own);
  * the LFM launcher refuses to install without `uv` rather than fall back to a pip that ignores the package's lock.

Run: python3 scripts/test_voice_launchers.py
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CELLS = ROOT / "cells"
PIN = "3428dfd95309a7f3c84fd93259ded0f810d1ff91"
DEPS = ("numpy<2.2", "safetensors<0.5", "huggingface-hub<0.25", "einops==0.7.0", "sentencepiece==0.2.0", "sphn==0.1.9", "aiohttp<3.11", "tqdm")
# gzip: GNU tar runs it to unpack a .tgz (bsdtar, the macOS one, does it itself, which hid the want of it until the GitLab runner).
# tr, sort, paste: the architectures of the machine's cards, run through nvidia-smi's compute capabilities (run_minicpm_omni.sh).
UTILITIES = ("sed", "tar", "gzip", "rm", "mkdir", "cp", "chmod", "dirname", "touch", "cat", "env", "ln", "find", "wc", "tr", "sort", "paste")

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


# The stand-ins. They write one line per call to $LOG; the tests read it back. $UV_FAIL / $GIT_FAIL name the one
# sub-command that fails (after it is written down), the way a dropped network does.
UV = r'''#!/bin/bash
echo "uv $*" >> "$LOG"
[ "$UV_FAIL" = "$1" ] && exit 3
py=""; prev=""
for a in "$@"; do [ "$prev" = "--python" ] && py="$a"; prev="$a"; done
case "$1" in
  venv)  dest="${@: -1}"; mkdir -p "$dest/bin"; cp "$STUB_PYTHON" "$dest/bin/python"; cp "$STUB_VLLM" "$dest/bin/vllm"
         chmod +x "$dest/bin/python" "$dest/bin/vllm" ;;
  pip)   case " $* " in *" --no-deps "*) touch "$(dirname "$py")/../.moshi-installed" ;; esac ;;
  sync)  mkdir -p .venv/bin; cp "$STUB_PYTHON" .venv/bin/python; chmod +x .venv/bin/python ;;
esac
'''

GIT = r'''#!/bin/bash
echo "git $*" >> "$LOG"
dir=""
if [ "$1" = "-C" ]; then dir="$2"; shift 2; fi
[ "$GIT_FAIL" = "$1" ] && exit 4
case "$1" in
  clone)     dest="${@: -1}"; mkdir -p "$dest/.git" "$dest/moshi/moshi"
             cp "$FIXTURES/server.py" "$dest/moshi/moshi/server.py"; cp "$FIXTURES/offline.py" "$dest/moshi/moshi/offline.py"
             echo "not-the-pin" > "$dest/.git/SHA" ;;
  rev-parse) cat "$dir/.git/SHA" ;;
  checkout)  echo "${@: -1}" > "$dir/.git/SHA" ;;
esac
'''

# The venv's python: `-c` is the launcher asking "is moshi importable?" (the answer is its exit status);
# anything else is the server being started.
PYTHON = r'''#!/bin/bash
here="$(cd "$(dirname "$0")" && pwd)"
if [ "$1" = "-c" ]; then [ -f "$here/../.moshi-installed" ]; exit $?; fi
if [ "$1" = "-" ]; then      # a script on stdin: the hub download of the one folder Step-Audio needs
  cat > "$LOG.script"; echo "FETCH ${*:2}" >> "$LOG"; mkdir -p "$2/token2wav"; : > "$2/token2wav/flow.pt"; exit 0
fi
{
  echo "SERVER $*"
  echo "CWD $PWD"
  echo "ENV HF_HUB_OFFLINE=${HF_HUB_OFFLINE-<unset>} NO_TORCH_COMPILE=${NO_TORCH_COMPILE-<unset>} PYTHONUNBUFFERED=${PYTHONUNBUFFERED-<unset>} LD_LIBRARY_PATH=${LD_LIBRARY_PATH-<unset>}"
} >> "$LOG"
'''

# The machine without uv: python3 -m venv DIR, then DIR/bin/pip.
PYTHON3 = r'''#!/bin/bash
echo "python3 $*" >> "$LOG"
if [ "$1" = "-m" ] && [ "$2" = "venv" ]; then
  dest="$3"; mkdir -p "$dest/bin"; cp "$STUB_PYTHON" "$dest/bin/python"
  printf '#!/bin/bash\necho "pip $*" >> "$LOG"\ncase " $* " in *" --no-deps "*) touch "$(dirname "$0")/../.moshi-installed" ;; esac\n' > "$dest/bin/pip"
  chmod +x "$dest/bin/python" "$dest/bin/pip"
fi
'''

# The venv's `vllm`: the engine being started.
VLLM = r'''#!/bin/bash
{
  echo "VLLM $*"
  echo "CWD $PWD"
  echo "ENV PATH0=${PATH%%:*} SPAWN=${VLLM_WORKER_MULTIPROC_METHOD-<unset>} MAX_JOBS=${MAX_JOBS-<unset>} ALLOC=${PYTORCH_CUDA_ALLOC_CONF-<unset>}"
} >> "$LOG"
'''

# The stand-ins of the MiniCPM-o build: cmake (the build step makes the server), nvidia-smi (the card's compute capability), the server.
CMAKE = r'''#!/bin/bash
echo "cmake $*" >> "$LOG"
if [ "$1" = "--build" ]; then
  [ "$CMAKE_FAIL" = "build" ] && exit 5
  mkdir -p "$2/bin"; cp "$STUB_OMNI_SERVER" "$2/bin/llama-omni-server"; chmod +x "$2/bin/llama-omni-server"
fi
'''
NVIDIA_SMI = r'''#!/bin/bash
echo "${STUB_CAP:-12.0}"
'''
OMNI_SERVER = r'''#!/bin/bash
{
  echo "OMNI $*"
  echo "CWD $PWD"
} >> "$LOG"
'''

# The lines of the PersonaPlex source the launcher patches, as the pinned commit has them, among lines it must not touch.
SERVER_PY = '''def main():
    args = parse()
    voices_tgz = hf_hub_download(hf_repo, "voices.tgz")

    # Download config.json to increment download counter
    # No worries about double-counting since config.json will be cached the second time
    hf_hub_download(args.hf_repo, "config.json")

    logger.info("loading mimi")
    args.mimi_weight = hf_hub_download(args.hf_repo, loaders.MIMI_NAME)
    hf_hub_download(args.hf_repo, "tokenizer.model")
'''
OFFLINE_PY = '''def run(hf_repo):
    # Download config.json to increment download counter
    # No worries about double-counting since config.json will be cached the second time
    hf_hub_download(hf_repo, "config.json")

    mimi_weight = hf_hub_download(hf_repo, loaders.MIMI_NAME)  # type: ignore
'''
SERVER_PATCHED = SERVER_PY.replace('    hf_hub_download(args.hf_repo, "config.json")\n', "    pass\n")
OFFLINE_PATCHED = OFFLINE_PY.replace('    hf_hub_download(hf_repo, "config.json")\n', "    pass\n")
ENV_PLAIN = "ENV HF_HUB_OFFLINE=<unset> NO_TORCH_COMPILE=<unset> PYTHONUNBUFFERED=<unset> LD_LIBRARY_PATH=<unset>"


class Sandbox:
    """A home folder with stand-in tools first on the PATH, and the model folder the launcher expects."""

    def __init__(self):
        # resolve(): on macOS the temp folder is a link, and the server's $PWD is the real path.
        self.dir = Path(tempfile.mkdtemp(prefix="caravan-voice-launchers-")).resolve()
        self.home = self.dir / "home"
        self.bin = self.home / ".local" / "bin"
        self.bin.mkdir(parents=True)
        self.log = self.dir / "calls.log"
        self.log.write_text("")
        self.fixtures = self.dir / "fixtures"
        self.fixtures.mkdir()
        (self.fixtures / "server.py").write_text(SERVER_PY)
        (self.fixtures / "offline.py").write_text(OFFLINE_PY)
        self.utilities = self.dir / "utilities"
        self.utilities.mkdir()
        for name in UTILITIES:
            os.symlink(shutil.which(name), self.utilities / name)
        for name, body in (("uv", UV), ("git", GIT), ("python3", PYTHON3)):
            self.tool(name, body)
        self.stub_python = self.dir / "stub_python"
        self.stub_python.write_text(PYTHON)
        self.stub_python.chmod(0o755)
        self.stub_vllm = self.dir / "stub_vllm"
        self.stub_vllm.write_text(VLLM)
        self.stub_vllm.chmod(0o755)
        self.stub_omni_server = self.dir / "stub_omni_server"
        self.stub_omni_server.write_text(OMNI_SERVER)
        self.stub_omni_server.chmod(0o755)
        (self.dir / "tmp").mkdir()

    def tool(self, name, body):
        path = self.bin / name
        path.write_text(body)
        path.chmod(0o755)

    def drop(self, name):
        (self.bin / name).unlink()

    def personaplex_model(self):
        """The folder the /hf page lays out for nvidia/personaplex-7b-v1: five files, two of them real archives."""
        model = self.dir / "models" / "personaplex-7b-v1" / "nvidia" / "SAFETENSORS"
        model.mkdir(parents=True)
        for name in ("model.safetensors", "tokenizer-e351c8d8-checkpoint125.safetensors", "tokenizer_spm_32k_3.model"):
            (model / name).write_bytes(b"x")
        pack = self.dir / "pack"
        (pack / "voices").mkdir(parents=True)
        (pack / "voices" / "NATF0.pt").write_bytes(b"v")
        (pack / "dist").mkdir()
        (pack / "dist" / "index.html").write_text("<html></html>")
        subprocess.run(["tar", "-czf", str(model / "voices.tgz"), "-C", str(pack), "voices"], check=True)
        subprocess.run(["tar", "-czf", str(model / "dist.tgz"), "-C", str(pack), "dist"], check=True)
        return model

    def run(self, launcher, *args, env=None, cwd=None):
        full = {"HOME": str(self.home), "PATH": str(self.utilities), "LOG": str(self.log),
                "STUB_PYTHON": str(self.stub_python), "STUB_VLLM": str(self.stub_vllm), "FIXTURES": str(self.fixtures), "UV_FAIL": "", "GIT_FAIL": "",
                "STUB_OMNI_SERVER": str(self.stub_omni_server), "CMAKE_FAIL": "", "TMPDIR": str(self.dir / "tmp")}
        full.update(env or {})
        return subprocess.run(["/bin/bash", str(launcher), *args], env=full, capture_output=True, text=True,
                              cwd=str(cwd or self.dir), timeout=60)

    def calls(self):
        return [line for line in self.log.read_text().splitlines() if line]

    def forget(self):
        self.log.write_text("")

    def close(self):
        shutil.rmtree(self.dir, ignore_errors=True)


def personaplex():
    launcher = CELLS / "run_personaplex.sh"
    box = Sandbox()
    try:
        model = box.personaplex_model()
        venv, src, assets = box.home / "personaplex-venv", box.home / "personaplex", box.home / "pplex-assets"

        # A weight file is missing: stops before anything is installed, and names the file.
        (model / "tokenizer_spm_32k_3.model").unlink()
        r = box.run(launcher, "8030", str(model), "--install-only")
        check(r.returncode == 1 and "tokenizer_spm_32k_3.model is missing" in r.stderr,
              "a missing tokenizer: exit 1, and the message names the file")
        check(box.calls() == [] and not venv.exists() and not src.exists(),
              "a missing tokenizer: nothing installed, no venv made, nothing fetched")
        (model / "tokenizer_spm_32k_3.model").write_bytes(b"x")
        (model / "dist.tgz").rename(model / "dist.tgz.away")
        r = box.run(launcher, "8030", str(model))
        check(r.returncode == 1 and "dist.tgz is missing" in r.stderr and box.calls() == [],
              "the page's archive missing: the same refusal (the page is part of what the cell serves)")
        (model / "dist.tgz.away").rename(model / "dist.tgz")
        r = box.run(launcher, env={"LLAMA_MODELS_DIR": str(box.dir / "no-library")})
        check(r.returncode == 1 and f"{box.dir}/no-library/personaplex-7b-v1/nvidia/SAFETENSORS/model.safetensors is missing" in r.stderr,
              "no arguments: the library is looked for under $LLAMA_MODELS_DIR, as <model>/<author>/<format>")
        # Not run: a machine that has the NAS mounted would find the model there and the test would depend on the machine.
        check("${LLAMA_MODELS_DIR:-/mnt/lama-caravan-models}/personaplex-7b-v1/nvidia/SAFETENSORS" in launcher.read_text(),
              "without $LLAMA_MODELS_DIR the library is /mnt/lama-caravan-models, the folder the NAS is mounted at")

        # First start, install only: the exact steps, in order.
        r = box.run(launcher, "8030", str(model), "--install-only")
        calls = box.calls()
        check(r.returncode == 0 and "ready (install-only)" in r.stdout, "--install-only: exit 0 and says it is ready")
        check(calls[0] == f"uv venv --python 3.12 {venv}", "the venv is made first, on Python 3.12: " + repr(calls[:1]))
        check(calls[1] == f"uv pip install --python {venv}/bin/python torch==2.13.0 --torch-backend=cu130",
              "torch comes BEFORE the package, from the cu130 index (the repository's own pin has no kernels for an RTX 5090)")
        check(calls[2] == f"uv pip install --python {venv}/bin/python --only-binary=:all: " + " ".join(DEPS),
              "the dependencies are binary wheels at the versions that were proven")
        check(calls[3] == f"git clone -q https://github.com/NVIDIA/personaplex {src}", "the source is cloned from NVIDIA's repository")
        check(calls[4] == f"git -C {src} rev-parse HEAD" and calls[5] == f"git -C {src} checkout -q --force {PIN}",
              "the source is put on ONE commit")
        check(calls[6] == f"uv pip install --python {venv}/bin/python --no-deps -e {src}/moshi",
              "the package is installed from NVIDIA's source with --no-deps (its pins are stale), after the checkout")
        check(len(calls) == 7, "nothing else runs in an install: " + repr(calls[7:]))
        check((venv / ".deps-installed").is_file(), "the venv is marked done when its installs are done")
        check(not any(c.startswith("SERVER") for c in calls), "--install-only does not start the server")
        check((assets / "voices" / "NATF0.pt").is_file() and (assets / "dist" / "index.html").is_file(),
              "the voices and the page are unpacked from the library's archives")

        # The patch: the one line of each file, and only it.
        check((src / "moshi/moshi/server.py").read_text() == SERVER_PATCHED,
              "server.py: the config.json call became `pass`; the voices, mimi and comment lines are as they were")
        check((src / "moshi/moshi/offline.py").read_text() == OFFLINE_PATCHED,
              "offline.py: the same, with its own spelling of the argument")
        check(not list((src / "moshi/moshi").glob("*.orig")), "the sed backup file is not left behind")

        # Second start: the install is not repeated.
        box.forget()
        r = box.run(launcher, "8030", str(model), "--install-only")
        check(r.returncode == 0 and box.calls() == [f"git -C {src} rev-parse HEAD"],
              "the second start only asks which commit the source is on: " + repr(box.calls()))
        check((src / "moshi/moshi/server.py").read_text() == SERVER_PATCHED, "the second start leaves the patched file as it was")

        # The source on another commit is put back on the pin, and patched again.
        (src / ".git" / "SHA").write_text("something-else\n")
        (src / "moshi/moshi/server.py").write_text(SERVER_PY)
        box.forget()
        box.run(launcher, "8030", str(model), "--install-only")
        check(box.calls() == [f"git -C {src} rev-parse HEAD", f"git -C {src} checkout -q --force {PIN}"],
              "a source off the pin: one checkout to the pin and nothing else: " + repr(box.calls()))
        check((src / "moshi/moshi/server.py").read_text() == SERVER_PATCHED, "a source off the pin is patched again")

        # Serving: arguments, environment, folder.
        box.forget()
        r = box.run(launcher, "22021", str(model), env={"LD_LIBRARY_PATH": "/usr/local/cuda/lib64"})
        calls = box.calls()
        check(r.returncode == 0 and "serving on port 22021" in r.stdout, "serving: exit 0 and says which port")
        want = (f"SERVER -m moshi.server --host 0.0.0.0 --port 22021 --static {assets}/dist --voice-prompt-dir {assets}/voices "
                f"--moshi-weight {model}/model.safetensors --mimi-weight {model}/tokenizer-e351c8d8-checkpoint125.safetensors "
                f"--tokenizer {model}/tokenizer_spm_32k_3.model")
        check(want in calls, "the server gets the port, the page, the voices and the three weight files of the library: " + repr(calls))
        check(f"CWD {src}" in calls, "the server runs in the source's folder")
        check("ENV HF_HUB_OFFLINE=1 NO_TORCH_COMPILE=1 PYTHONUNBUFFERED=1 LD_LIBRARY_PATH=<unset>" in calls,
              "hub off, compiler off, unbuffered, and the machine's LD_LIBRARY_PATH NOT passed on: " + repr(calls[-1:]))

        # Defaults, and the flag among the arguments.
        library = {"LLAMA_MODELS_DIR": str(box.dir / "models")}
        box.forget()
        box.run(launcher, env=library)
        check([c for c in box.calls() if c.startswith("SERVER")][:1] == [want.replace("--port 22021", "--port 8030")],
              "no arguments: port 8030, and the folder under $LLAMA_MODELS_DIR")
        for args in (("--install-only", "8030", str(model)), ("8030", "--install-only", str(model)), ("8030", str(model), "--install-only")):
            box.forget()
            r = box.run(launcher, *args)
            check(r.returncode == 0 and not any(c.startswith("SERVER") for c in box.calls()),
                  f"`--install-only` at place {args.index('--install-only') + 1} of 3: still only the flag, no server")
        box.forget()
        box.run(launcher, "--install-only", env=library)
        check(box.calls() == [f"git -C {src} rev-parse HEAD"], "`--install-only` alone: the flag, with the default folder: " + repr(box.calls()))
    finally:
        box.close()


def personaplex_failures():
    launcher = CELLS / "run_personaplex.sh"
    box = Sandbox()
    try:
        model = box.personaplex_model()
        venv, src = box.home / "personaplex-venv", box.home / "personaplex"

        # The install stops at the torch step (the network): the launcher stops, nothing after it runs.
        r = box.run(launcher, "8030", str(model), env={"UV_FAIL": "pip"})
        calls = box.calls()
        check(r.returncode != 0, "a failing pip step: the launcher exits non-zero")
        check(calls == [f"uv venv --python 3.12 {venv}", f"uv pip install --python {venv}/bin/python torch==2.13.0 --torch-backend=cu130"],
              "a failing pip step: no clone, no server after it: " + repr(calls))
        check((venv / "bin" / "python").is_file() and not (venv / ".deps-installed").exists(),
              "a failing pip step: the venv has a python in it and is NOT marked done")

        # The next start finishes the job: it does not take a venv with a python for a finished one.
        box.forget()
        r = box.run(launcher, "8030", str(model), "--install-only")
        calls = box.calls()
        check(r.returncode == 0 and calls[0] == f"uv pip install --python {venv}/bin/python torch==2.13.0 --torch-backend=cu130",
              "the next start installs torch again, without making the venv again: " + repr(calls[:1]))
        check(not any(c.startswith("uv venv") for c in calls) and (venv / ".deps-installed").is_file(),
              "the next start does not remake the venv, and marks it done at the end")

        # A failing clone stops the launcher before the patch and the package step.
        shutil.rmtree(src, ignore_errors=True)
        box.forget()
        r = box.run(launcher, "8030", str(model), "--install-only", env={"GIT_FAIL": "clone"})
        check(r.returncode != 0 and [c for c in box.calls() if c.startswith("uv")] == [],
              "a failing clone: non-zero, and no package installed from a source that is not there: " + repr(box.calls()))
        box.forget()
        r = box.run(launcher, "8030", str(model), "--install-only")
        check(r.returncode == 0 and box.calls()[0] == f"git clone -q https://github.com/NVIDIA/personaplex {src}",
              "the next start clones again")
    finally:
        box.close()


def personaplex_without_uv():
    launcher = CELLS / "run_personaplex.sh"
    box = Sandbox()
    try:
        model = box.personaplex_model()
        venv, src = box.home / "personaplex-venv", box.home / "personaplex"
        box.drop("uv")
        r = box.run(launcher, "8030", str(model), "--install-only")
        calls = box.calls()
        check(r.returncode == 0, "no uv: the install still completes, with the venv's pip: " + (r.stderr[-200:] or "ok"))
        check(calls[:2] == [f"python3 -m venv {venv}", "pip -q install -U pip"], "no uv: the venv is made by python3 -m venv: " + repr(calls[:2]))
        check(calls[2] == "pip install torch==2.13.0 --index-url https://download.pytorch.org/whl/cu130",
              "no uv: torch comes first, from the cu130 index: " + repr(calls[2:3]))
        check(calls[3] == "pip install --only-binary=:all: " + " ".join(DEPS),
              "no uv: then the same dependencies as binary wheels: " + repr(calls[3:4]))
        check(calls[-1] == f"pip install --no-deps -e {src}/moshi", "no uv: the package is installed with --no-deps, last: " + repr(calls[-1:]))
        check((venv / ".deps-installed").is_file(), "no uv: the venv is marked done")
    finally:
        box.close()


def lfm_audio():
    launcher_src = CELLS / "run_lfm_audio.sh"
    box = Sandbox()
    try:
        # Placed as the scout places it: the launcher and the server side by side in $HOME.
        launcher = box.home / "run_lfm_audio.sh"
        shutil.copy(launcher_src, launcher)
        root, src = box.home / "lfm25", box.home / "lfm25" / "liquid-audio"
        model = box.dir / "models" / "LFM2.5-Audio-1.5B" / "LiquidAI" / "SAFETENSORS"
        clone = f"git clone -q --depth 1 --branch v1.3.0 https://github.com/Liquid4All/liquid-audio.git {src}"

        # No uv and no venv: refuses, and says why. A pip install would ignore the package's lock.
        box.drop("uv")
        r = box.run(launcher, "8031", str(model), "--install-only")
        check(r.returncode == 1 and "uv is not installed" in r.stderr, "no uv: exit 1 and the message says uv is missing")
        check(box.calls() == [] and not root.exists(), "no uv: nothing is fetched or created")
        box.tool("uv", UV)

        # The sync stops (the network): the launcher stops; the next start finishes the job.
        r = box.run(launcher, "8031", str(model), "--install-only", env={"UV_FAIL": "sync"})
        check(r.returncode != 0 and box.calls() == [clone, "uv sync --frozen --no-dev"],
              "a failing sync: non-zero, nothing after it: " + repr(box.calls()))
        check(not (src / ".venv" / ".synced").exists(), "a failing sync: the venv is NOT marked done")
        (src / ".venv" / "bin").mkdir(parents=True, exist_ok=True)        # what an interrupted sync leaves: a python, half the packages
        shutil.copy(box.stub_python, src / ".venv" / "bin" / "python")
        box.forget()
        r = box.run(launcher, "8031", str(model), "--install-only")
        check(r.returncode == 0 and box.calls() == ["uv sync --frozen --no-dev"],
              "the next start runs the sync again (the source is already there): " + repr(box.calls()))
        check((src / ".venv" / ".synced").is_file(), "and marks the venv done")

        # Second start: nothing installed again; the server is started.
        (box.home / "lfm_audio_server.py").write_text("# stand-in\n")
        box.forget()
        r = box.run(launcher, "22031", str(model))
        calls = box.calls()
        check(r.returncode == 0 and "serving on port 22031" in r.stdout, "serving: exit 0 and says which port")
        check(calls[:1] == [f"SERVER {box.home}/lfm_audio_server.py 22031 {model}"] and f"CWD {box.dir}" in calls,
              "the server file next to the launcher gets the port and the folder: " + repr(calls[:1]))
        check(not any(c.startswith(("uv ", "git ")) for c in calls), "serving installs and fetches nothing")

        # Defaults, and the flag among the arguments.
        library = {"LLAMA_MODELS_DIR": str(box.dir / "models")}
        box.forget()
        box.run(launcher, env=library)
        check(box.calls()[:1] == [f"SERVER {box.home}/lfm_audio_server.py 8031 {model}"],
              "no arguments: port 8031 and the library's folder: " + repr(box.calls()[:1]))
        box.forget()
        box.run(launcher, env={**library, "LFM_MODEL_DIR": "/elsewhere/lfm"})
        check(box.calls()[:1] == [f"SERVER {box.home}/lfm_audio_server.py 8031 /elsewhere/lfm"],
              "$LFM_MODEL_DIR wins over the library's folder: " + repr(box.calls()[:1]))
        box.forget()
        box.run(launcher, "8031", "/given/dir", env={**library, "LFM_MODEL_DIR": "/elsewhere/lfm"})
        check(box.calls()[:1] == [f"SERVER {box.home}/lfm_audio_server.py 8031 /given/dir"], "a folder given as an argument wins over both")
        for args in (("--install-only", "8031", str(model)), ("8031", "--install-only", str(model)), ("8031", str(model), "--install-only")):
            box.forget()
            r = box.run(launcher, *args)
            check(r.returncode == 0 and box.calls() == [], f"`--install-only` at place {args.index('--install-only') + 1} of 3: only the flag, no server")

        # The server file: next to the launcher, else in $HOME, else a refusal that says so.
        elsewhere = box.dir / "elsewhere"
        elsewhere.mkdir()
        shutil.copy(launcher_src, elsewhere / "run_lfm_audio.sh")
        box.forget()
        box.run(elsewhere / "run_lfm_audio.sh", "8031", str(model))
        check(box.calls()[:1] == [f"SERVER {box.home}/lfm_audio_server.py 8031 {model}"],
              "a launcher with no server beside it takes the one in $HOME: " + repr(box.calls()[:1]))
        (elsewhere / "lfm_audio_server.py").write_text("# beside\n")
        box.forget()
        box.run(elsewhere / "run_lfm_audio.sh", "8031", str(model))
        check(box.calls()[:1] == [f"SERVER {elsewhere}/lfm_audio_server.py 8031 {model}"],
              "a server beside the launcher wins over the one in $HOME: " + repr(box.calls()[:1]))
        (box.home / "lfm_audio_server.py").unlink()
        (elsewhere / "lfm_audio_server.py").unlink()
        box.forget()
        r = box.run(elsewhere / "run_lfm_audio.sh", "8031", str(model))
        check(r.returncode == 1 and "lfm_audio_server.py is not next to this launcher" in r.stderr and box.calls() == [],
              "no server file anywhere: exit 1 and the message says so, nothing is started")
    finally:
        box.close()


def vllm_omni_model(box, name, files):
    """A checkpoint folder of the library: the named files, empty."""
    model = box.dir / "models" / name
    model.mkdir(parents=True)
    for f in files:
        (model / f).write_bytes(b"x")
    return model


def budgets(yaml_text):
    import re
    return [float(x) for x in re.findall(r"gpu_memory_utilization:\s*([0-9.]+)", yaml_text)]


def vllm_omni():
    launcher = CELLS / "run_vllm_omni.sh"
    box = Sandbox()
    try:
        omni = box.home / "omni"
        step = vllm_omni_model(box, "step", ["config.json", "model-00001-of-00004.safetensors", "tokenizer.json"])
        (step / "token2wav").mkdir()
        qwen = vllm_omni_model(box, "qwen", ["config.json", "model-00001-of-00006.safetensors"])
        plain = vllm_omni_model(box, "plain", ["config.json"])
        nowhere = box.dir / "models" / "nowhere"

        # Refusals: before anything is installed.
        r = box.run(launcher)
        check(r.returncode == 2 and "usage: run_vllm_omni.sh" in r.stderr and box.calls() == [], "no arguments: exit 2 and the usage line")
        r = box.run(launcher, "22031", "nonsense", str(qwen))
        check(r.returncode == 2 and "unknown recipe 'nonsense'" in r.stderr and box.calls() == [], "an unknown recipe: exit 2, and it is named")
        r = box.run(launcher, "22031", "qwen3-omni", str(nowhere))
        check(r.returncode == 1 and "config.json is missing" in r.stderr and box.calls() == [],
              "a folder with no config.json: exit 1, and the message sends to the /hf page")
        r = box.run(launcher, "22031", "qwen3-omni", str(plain))
        check(r.returncode == 1 and "no .safetensors weights" in r.stderr and box.calls() == [],
              "a folder with a config and no weights: the same refusal (a half-downloaded model)")

        # First start of the Qwen3-Omni recipe, install only.
        venv = box.home / "venvs" / "omni-qwen3-omni"
        r = box.run(launcher, "22031", "qwen3-omni", str(qwen), "--install-only")
        calls = box.calls()
        check(r.returncode == 0 and "ready (install-only)" in r.stdout, "--install-only: exit 0 and says it is ready")
        check(calls == [f"uv venv --python 3.12 --seed {venv}",
                        f"uv pip install --python {venv}/bin/python vllm==0.30.0 vllm-omni==0.30.0"],
              "the venv, then vLLM and vLLM-Omni at the SAME version (one release): " + repr(calls))
        check((venv / ".installed-qwen3-omni").is_file(), "the venv is marked done for its recipe when the install is done")
        text = (omni / "qwen3-omni.yaml").read_text()
        check(budgets(text) == [0.655, 0.225, 0.04] and sum(budgets(text)) < 0.95,
              "qwen3-omni: three stages, budgets add up to less than the card: " + repr(budgets(text)))
        check(text.count('devices: "0"') == 3, "qwen3-omni: every stage on device 0 (the default files want two cards)")
        check("moe_backend: marlin" in text and "async_chunk: true" in text and "initial_codec_chunk_frames: 1" in text,
              "qwen3-omni: Marlin for the thinker's experts, chunks streamed, the first frame after one codec frame")

        # Second start: nothing installed again, the deploy file is written again from the launcher.
        (omni / "qwen3-omni.yaml").write_text("# an old copy\n")
        box.forget()
        r = box.run(launcher, "22031", "qwen3-omni", str(qwen), "--install-only")
        check(r.returncode == 0 and box.calls() == [], "the second start installs nothing: " + repr(box.calls()))
        check((omni / "qwen3-omni.yaml").read_text() == text, "the deploy file is rewritten at every start: it cannot be older than the launcher")

        # Serving.
        box.forget()
        r = box.run(launcher, "22031", "qwen3-omni", str(qwen))
        calls = box.calls()
        want = (f"VLLM serve {qwen} --omni --served-model-name qwen3-omni --host 0.0.0.0 --port 22031 --stage-init-timeout 1800 --init-timeout 2400 "
                f"--trust-remote-code --deploy-config {omni}/qwen3-omni.yaml")
        check(r.returncode == 0 and calls[:1] == [want], "serving: the library's folder, the name clients ask for, the port, the deploy file: " + repr(calls[:1]))
        check(f"CWD {omni}" in calls, "the engine runs in the launcher's own folder")
        check(f"ENV PATH0={venv}/bin SPAWN=spawn MAX_JOBS=4 ALLOC=expandable_segments:True" in calls,
              "venv's bin FIRST on the PATH (FlashInfer needs its ninja), spawn, 4 compile jobs, expandable segments: " + repr(calls[-1:]))
        box.forget()
        box.run(launcher, "22031", "qwen3-omni", str(qwen), env={"MAX_JOBS": "12"})
        check(any("MAX_JOBS=12" in c for c in box.calls()), "$MAX_JOBS from the cell's environment is kept")

        # A failing install is finished by the next start.
        shutil.rmtree(venv)
        box.forget()
        r = box.run(launcher, "22031", "qwen3-omni", str(qwen), env={"UV_FAIL": "pip"})
        check(r.returncode != 0 and not (venv / ".installed-qwen3-omni").exists() and not any(c.startswith("VLLM") for c in box.calls()),
              "a failing install: non-zero, not marked done, no engine started")
        box.forget()
        r = box.run(launcher, "22031", "qwen3-omni", str(qwen), "--install-only")
        check(r.returncode == 0 and box.calls() == [f"uv pip install --python {venv}/bin/python vllm==0.30.0 vllm-omni==0.30.0"]
              and (venv / ".installed-qwen3-omni").is_file(),
              "the next start installs again WITHOUT making the venv again: " + repr(box.calls()))

        # No uv, no venv: refuses and says why.
        box.drop("uv")
        shutil.rmtree(venv)
        box.forget()
        r = box.run(launcher, "22031", "qwen3-omni", str(qwen), "--install-only")
        check(r.returncode == 1 and "uv is not installed" in r.stderr and box.calls() == [], "no uv: exit 1, and it says so")
        box.tool("uv", UV)

        # Step-Audio 2 mini: its own venv, its own packages, its own engine flags.
        step_venv = box.home / "venvs" / "omni-step-audio2"
        box.forget()
        r = box.run(launcher, "22032", "step-audio2", str(step), "--install-only")
        calls = box.calls()
        check(calls == [f"uv venv --python 3.12 --seed {step_venv}",
                        f"uv pip install --python {step_venv}/bin/python vllm==0.30.0 vllm-omni==0.30.0 step-audio2==1.0.0"],
              "step-audio2: its own venv, and the one package more (its token2wav code): " + repr(calls))
        text = (omni / "step-audio2.yaml").read_text()
        check(budgets(text) == [0.6, 0.25] and text.count('devices: "0"') == 2 and "StepAudio2Token2WavForConditionalGeneration" in text,
              "step-audio2: the thinker and the Token2Wav stage on device 0, budgets " + repr(budgets(text)))
        box.forget()
        r = box.run(launcher, "22032", "step-audio2", str(step), env={"OMNI_VENV": str(box.dir / "mine")})
        check(box.calls()[0] == f"uv venv --python 3.12 --seed {box.dir}/mine", "$OMNI_VENV picks the venv's place: " + repr(box.calls()[:1]))
        # Two recipes in ONE venv (through $OMNI_VENV): each installs what it needs, the first one's marker is not the second's.
        box.forget()
        box.run(launcher, "22031", "qwen3-omni", str(qwen), "--install-only", env={"OMNI_VENV": str(box.dir / "mine")})
        check(box.calls() == [f"uv pip install --python {box.dir}/mine/bin/python vllm==0.30.0 vllm-omni==0.30.0"],
              "a recipe that finds another recipe's venv installs its own packages (the venv is not made again): " + repr(box.calls()))
        check((box.dir / "mine" / ".installed-qwen3-omni").is_file() and (box.dir / "mine" / ".installed-step-audio2").is_file(),
              "each recipe has its own marker in a shared venv")
        box.forget()
        r = box.run(launcher, "22032", "step-audio2", str(step))
        calls = box.calls()
        check(calls[:1] == [f"VLLM serve {step} --omni --served-model-name stepfun-ai/Step-Audio-2-mini --host 0.0.0.0 --port 22032 "
                            f"--stage-init-timeout 1800 --init-timeout 2400 --trust-remote-code --enforce-eager --deploy-config {omni}/step-audio2.yaml"],
              "step-audio2 serving: eager mode on, the model folder is the library's: " + repr(calls[:1]))
        check(f"ENV PATH0={step_venv}/bin SPAWN=spawn MAX_JOBS=4 ALLOC=<unset>" in calls,
              "step-audio2: no allocator setting that was not proven for it")

        # The folder the /hf page leaves out: linked together and fetched at the commit the recipe was proven on.
        (step / "token2wav").rmdir()
        box.forget()
        r = box.run(launcher, "22032", "step-audio2", str(step))
        calls = box.calls()
        joined = omni / "step-audio2-model"
        check(f"FETCH {joined} e36fdd5d71e0ea22f09dd94bbab9bfc544ca1e36" in calls, "no token2wav/ in the library: it is fetched, at ONE commit: " + repr(calls))
        check(all((joined / f).is_symlink() and os.path.realpath(joined / f) == os.path.realpath(step / f) for f in ("config.json", "tokenizer.json")),
              "the library's files are LINKED, not copied (tens of GB)")
        check(calls[-3].startswith(f"VLLM serve {joined} "), "the engine is started on the joined folder: " + repr(calls[-3:-2]))
        script = Path(str(box.log) + ".script").read_text()
        check('snapshot_download("stepfun-ai/Step-Audio-2-mini", revision=sys.argv[2], allow_patterns=["token2wav/*"], local_dir=sys.argv[1])' in script,
              "the fetch asks the hub for that ONE folder of that repository, and nothing else")
        box.forget()
        box.run(launcher, "22032", "step-audio2", str(step))
        check(not any(c.startswith("FETCH") for c in box.calls()), "the second start does not fetch again")
    finally:
        box.close()


def minicpm_model(box, skip=(), prompt_cache_bytes=211613152):
    """openbmb/MiniCPM-o-4_5-gguf as the /hf page lays it out: three folders, ten files (the prompt cache is sparse)."""
    root = box.dir / "models" / "MiniCPM-o-4_5-gguf" / "openbmb"
    for folder, names in (("Q4_K_M", ["MiniCPM-o-4_5-Q4_K_M.gguf"]),
                          ("F16", ["MiniCPM-o-4_5-audio-F16.gguf", "MiniCPM-o-4_5-vision-F16.gguf", "MiniCPM-o-4_5-tts-F16.gguf"]),
                          ("default", ["MiniCPM-o-4_5-projector-F16.gguf", "encoder.gguf", "flow_matching.gguf", "flow_extra.gguf",
                                       "hifigan2.gguf", "prompt_cache.gguf"])):
        (root / folder).mkdir(parents=True, exist_ok=True)
        for name in names:
            if name in skip:
                continue
            with open(root / folder / name, "wb") as f:
                if name == "prompt_cache.gguf":
                    f.truncate(prompt_cache_bytes)
                else:
                    f.write(b"x")
    return root


def minicpm_omni():
    launcher = CELLS / "run_minicpm_omni.sh"
    pin = "88bd37eb671f67cf8d747140ed100231756e0bc3"
    box = Sandbox()
    try:
        box.tool("cmake", CMAKE)
        box.tool("nvcc", "#!/bin/bash\n")
        box.tool("nvidia-smi", NVIDIA_SMI)
        model = minicpm_model(box)
        src, layout = box.home / "llama.cpp-omni", box.home / "omni-gguf"
        configure = (f"cmake -S {src} -B {src}/build -DCMAKE_BUILD_TYPE=Release -DGGML_CUDA=ON -DGGML_NATIVE=OFF "
                     f"-DCMAKE_CUDA_COMPILER={box.bin}/nvcc -DCMAKE_CUDA_ARCHITECTURES=120 -DCMAKE_CUDA_FLAGS=-Xcicc -O1 "
                     f"-DCMAKE_CXX_FLAGS=-DF_NOCACHE=-1 -DLLAMA_OPENSSL=OFF -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_EXAMPLES=OFF "
                     f"-DCMAKE_EXE_LINKER_FLAGS=-Wl,--allow-shlib-undefined")

        # Refusals: before anything is built.
        r = box.run(launcher)
        check(r.returncode == 2 and "usage: run_minicpm_omni.sh" in r.stderr and box.calls() == [], "no arguments: exit 2 and the usage line")
        broken = Sandbox()
        try:
            broken_model = minicpm_model(broken, skip=("encoder.gguf",))
            r = broken.run(launcher, "22035", str(broken_model), "--install-only")
            check(r.returncode == 1 and "encoder.gguf is not under" in r.stderr and broken.calls() == [],
                  "a model folder with a file missing: exit 1, the file is named, nothing is built")
        finally:
            broken.close()
        old = Sandbox()
        try:
            old_model = minicpm_model(old, prompt_cache_bytes=67000000)
            r = old.run(launcher, "22035", str(old_model), "--install-only")
            check(r.returncode == 1 and "67000000 bytes, not 211613152" in r.stderr and "older repository" in r.stderr and old.calls() == [],
                  "a prompt cache of the older repository (another voice): exit 1, the size is named, nothing is built")
        finally:
            old.close()

        # No compiler: it is said before the source is fetched.
        box.drop("cmake")
        r = box.run(launcher, "22035", str(model), "--install-only")
        check(r.returncode == 1 and "cmake is not installed" in r.stderr and box.calls() == [], "no cmake: exit 1, and it says so")
        box.tool("cmake", CMAKE)
        box.drop("nvcc")
        r = box.run(launcher, "22035", str(model), "--install-only")
        check(r.returncode == 1 and "nvcc is not found" in r.stderr and box.calls() == [] and not src.exists(),
              "no nvcc: exit 1 BEFORE the source is fetched")
        box.tool("nvcc", "#!/bin/bash\n")

        # First start, install only.
        r = box.run(launcher, "22035", str(model), "--install-only")
        calls = box.calls()
        check(r.returncode == 0 and "ready (install-only)" in r.stdout, "--install-only: exit 0 and says it is ready")
        check(calls == [f"git clone -q https://github.com/tc-mb/llama.cpp-omni {src}", f"git -C {src} rev-parse HEAD",
                        f"git -C {src} checkout -q --force {pin}", configure,
                        f"cmake --build {src}/build --target llama-omni-server -j8"],
              "the source at ONE commit, then the configure with the flags that were proven, then the one target: " + repr(calls))
        check((src / "build" / f".built-{pin}").is_file() and (src / "build" / "bin" / "llama-omni-server").is_file(),
              "the build is marked done, for that commit, when it is done")
        check((src / "build" / ".arch").read_text() == "120\n", "and with the architectures it was built for (one card: sm_120)")
        want = {"MiniCPM-o-4_5-Q4_K_M.gguf": ("Q4_K_M", "."), "MiniCPM-o-4_5-audio-F16.gguf": ("F16", "audio"),
                "MiniCPM-o-4_5-vision-F16.gguf": ("F16", "vision"), "MiniCPM-o-4_5-tts-F16.gguf": ("F16", "tts"),
                "MiniCPM-o-4_5-projector-F16.gguf": ("default", "tts"), "encoder.gguf": ("default", "token2wav-gguf"),
                "flow_matching.gguf": ("default", "token2wav-gguf"), "flow_extra.gguf": ("default", "token2wav-gguf"),
                "hifigan2.gguf": ("default", "token2wav-gguf"), "prompt_cache.gguf": ("default", "token2wav-gguf")}
        ok = all((layout / dest / name).is_symlink() and os.path.realpath(layout / dest / name) == os.path.realpath(model / folder / name)
                 for name, (folder, dest) in want.items())
        check(ok and len(want) == 10, "the ten files of the library are LINKED into the folders the server expects (8 GB are not copied)")

        # Second start: nothing built again.
        box.forget()
        r = box.run(launcher, "22035", str(model), "--install-only")
        check(r.returncode == 0 and box.calls() == [f"git -C {src} rev-parse HEAD"] or box.calls() == [],
              "the second start builds nothing: " + repr(box.calls()))
        check(not any(c.startswith("cmake") for c in box.calls()), "the second start runs no cmake")

        # The card decides the architecture; the operator can overrule it.
        for env, arch, why in (({"STUB_CAP": "8.6"}, "86", "an RTX 3090 reports 8.6"), ({"CUDA_ARCH": "90"}, "90", "$CUDA_ARCH overrules the card")):
            shutil.rmtree(src / "build")
            box.forget()
            box.run(launcher, "22035", str(model), "--install-only", env=env)
            check(any(f"-DCMAKE_CUDA_ARCHITECTURES={arch} " in c for c in box.calls()), f"sm_{arch}: {why}")
        shutil.rmtree(src / "build")
        box.drop("nvidia-smi")
        box.forget()
        box.run(launcher, "22035", str(model), "--install-only")
        check(any("-DCMAKE_CUDA_ARCHITECTURES=120 " in c for c in box.calls()), "no nvidia-smi: sm_120, the card of the fleet")
        box.tool("nvidia-smi", NVIDIA_SMI)

        # Two cards, 2026-10-17 (an RTX 3090 beside the RTX 5090): the server is built for BOTH architectures, whichever order
        # nvidia-smi names them in and however many cards share one; a cell pinned to the card its build lacks died with "no
        # kernel image". A card of another architecture added since the build asks for a new one; the same cards ask for nothing.
        for caps, arch, why in (("8.6\n12.0", "86;120", "a 3090 and a 5090"), ("12.0\n8.6", "86;120", "the other order: the same list"),
                                ("12.0\n12.0", "120", "two cards of one architecture: one entry"), ("8.6\n8.9\n12.0", "86;89;120", "three kinds")):
            shutil.rmtree(src / "build")
            box.forget()
            box.run(launcher, "22035", str(model), "--install-only", env={"STUB_CAP": caps})
            check(any(f"-DCMAKE_CUDA_ARCHITECTURES={arch} " in c for c in box.calls()) and (src / "build" / ".arch").read_text() == arch + "\n",
                  f"sm_{arch}: {why} (the build is marked with it)")
        shutil.rmtree(src / "build")
        box.forget()
        r = box.run(launcher, "22035", str(model), "--install-only", env={"STUB_CAP": "8.6\n12.0"})
        check("building llama-omni-server for sm_86, sm_120 with" in r.stdout, "the build says which architectures it is for")
        box.forget()
        box.run(launcher, "22035", str(model), "--install-only", env={"STUB_CAP": "8.6\n12.0"})
        check(not any(c.startswith("cmake") for c in box.calls()), "negative: the same two cards again: nothing is built")
        box.forget()
        box.run(launcher, "22035", str(model), "--install-only", env={"STUB_CAP": "8.6\n8.9\n12.0"})
        check(any(f"-DCMAKE_CUDA_ARCHITECTURES=86;89;120 " in c for c in box.calls()),
              "a card of another architecture added since the build: it is built again, for all three")
        box.forget()
        box.run(launcher, "22035", str(model), "--install-only", env={"STUB_CAP": "12.0"})
        check(any(f"-DCMAKE_CUDA_ARCHITECTURES=120 " in c for c in box.calls()),
              "a build made for other cards than this machine has now is not reused (the list is what it was built for)")
        shutil.rmtree(src / "build")
        box.forget()
        box.run(launcher, "22035", str(model), "--install-only")   # the build of the single card again, for what follows

        # The compiler: $NVCC, then $CUDA_HOME, else the PATH's.
        shutil.rmtree(src / "build")
        (box.dir / "cuda" / "bin").mkdir(parents=True)
        (box.dir / "cuda" / "bin" / "nvcc").write_text("#!/bin/bash\n")
        (box.dir / "cuda" / "bin" / "nvcc").chmod(0o755)
        box.forget()
        box.run(launcher, "22035", str(model), "--install-only", env={"CUDA_HOME": str(box.dir / "cuda")})
        check(any(f"-DCMAKE_CUDA_COMPILER={box.dir}/cuda/bin/nvcc " in c for c in box.calls()), "$CUDA_HOME's nvcc comes before the PATH's")
        shutil.rmtree(src / "build")
        box.forget()
        box.run(launcher, "22035", str(model), "--install-only", env={"CUDA_HOME": str(box.dir / "cuda"), "NVCC": "/opt/mine/nvcc"})
        check(any("-DCMAKE_CUDA_COMPILER=/opt/mine/nvcc " in c for c in box.calls()), "$NVCC comes before everything")

        # A tree that was configured before is not reused: cmake would drop the options of this command line.
        (src / "build" / "stale-from-another-compiler").write_text("x")
        (src / "build" / f".built-{pin}").unlink()
        box.forget()
        box.run(launcher, "22035", str(model), "--install-only")
        check(not (src / "build" / "stale-from-another-compiler").exists() and box.calls().count(configure) == 1,
              "a build tree without its done-marker is removed and configured afresh: " + repr(box.calls()[:2]))

        # A commit that is not the pin is put back on it, and built again.
        (src / ".git" / "SHA").write_text("something-else\n")
        shutil.rmtree(src / "build")
        box.forget()
        box.run(launcher, "22035", str(model), "--install-only")
        check(box.calls()[:2] == [f"git -C {src} rev-parse HEAD", f"git -C {src} checkout -q --force {pin}"],
              "a source off the pin: checked out to the pin first: " + repr(box.calls()[:2]))

        # A failing build stops the launcher and is finished by the next start, without fetching the source again.
        shutil.rmtree(src / "build")
        box.forget()
        r = box.run(launcher, "22035", str(model), "--install-only", env={"CMAKE_FAIL": "build"})
        check(r.returncode != 0 and not (src / "build" / f".built-{pin}").exists() and not any(c.startswith("OMNI") for c in box.calls()),
              "a failing build: non-zero, not marked done, no server started")
        box.forget()
        r = box.run(launcher, "22035", str(model), "--install-only")
        check(r.returncode == 0 and not any(c.startswith("git clone") for c in box.calls())
              and any(c.startswith("cmake --build") for c in box.calls()) and (src / "build" / f".built-{pin}").is_file(),
              "the next start builds again WITHOUT fetching the source again: " + repr(box.calls()))

        # Serving, and yesterday's sessions.
        sessions = box.dir / "tmp" / "omni_ws"
        for name, age_days in (("yesterday", 3), ("today", 0)):
            (sessions / name / "round_000").mkdir(parents=True)
            when = __import__("time").time() - age_days * 86400
            os.utime(sessions / name, (when, when))
        box.forget()
        r = box.run(launcher, "22035", str(model), "--install-only")
        check((sessions / "yesterday").exists(), "an install does not touch the sessions")
        box.forget()
        r = box.run(launcher, "22035", str(model))
        calls = box.calls()
        check(r.returncode == 0 and "serving on port 22035" in r.stdout, "serving: exit 0 and says which port")
        check(f"OMNI -m {layout}/MiniCPM-o-4_5-Q4_K_M.gguf --host 0.0.0.0 --port 22035 -ngl 99 -c 8192 --temp 0.7 --repeat-penalty 1.05" in calls,
              "the server gets the main GGUF of the layout, the port, the whole model on the GPU: " + repr(calls[-2:]))
        check(f"CWD {src}" in calls, "the server runs in its source folder (the reference voice is found relative to it)")
        check(not (sessions / "yesterday").exists() and (sessions / "today").is_dir(),
              "the sessions older than a day are removed, today's stay")
        for args in (("--install-only", "22035", str(model)), ("22035", "--install-only", str(model)), ("22035", str(model), "--install-only")):
            box.forget()
            r = box.run(launcher, *args)
            check(r.returncode == 0 and not any(c.startswith("OMNI") for c in box.calls()),
                  f"`--install-only` at place {args.index('--install-only') + 1} of 3: only the flag, no server")
    finally:
        box.close()


def real_files():
    """The launchers as they are in the repository."""
    for name in ("run_personaplex.sh", "run_lfm_audio.sh", "run_vllm_omni.sh", "run_minicpm_omni.sh"):
        r = subprocess.run(["/bin/bash", "-n", str(CELLS / name)], capture_output=True, text=True)
        check(r.returncode == 0, f"{name}: bash -n finds no syntax error " + r.stderr[:120])


def main():
    personaplex()
    personaplex_failures()
    personaplex_without_uv()
    lfm_audio()
    vllm_omni()
    minicpm_omni()
    real_files()
    print()
    if _fail:
        print(f"FAILED: {len(_fail)}")
        for m in _fail:
            print("  -", m)
        return 1
    print("all ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
