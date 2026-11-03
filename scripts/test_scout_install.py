#!/usr/bin/env python3
"""The script a new machine runs to get a scout: rust/crates/scout/install.sh, run by bash in a folder of its own.

The script is meant for `curl ... | bash` on a real machine: here its system commands are stand-ins (`uname`, `systemctl`, `loginctl`), its download
comes from a local server and the program in the bundle is a small script. Pinned: what lands where, what the service runs, that a bundle that is not the one
named or a program that does not run leaves nothing behind, that a machine that ran a scout before keeps its pairing, that a download cut short runs nothing, and
that what was installed can be taken off again.

Run: python3 scripts/test_scout_install.py
"""
import hashlib
import http.server
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _ports import free_port  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = (ROOT / "rust/crates/scout/install.sh").read_text(encoding="utf-8")
COMMIT = "abc1234"
SCOUT = "#!/bin/sh\nif [ \"$1\" = \"--version\" ]; then echo caravan-scout 9.9.9; exit 0; fi\nexit 0\n"
BROKEN = "#!/bin/sh\nexit 3\n"
FAILED = []


def check(what, got, want):
    if got != want:
        FAILED.append(what)
        print(f"FAIL {what}\n  got  {got!r}\n  want {want!r}")
    else:
        print(f"  ok  {what}")


class Bundle:
    """What the controller hands out: a program, and the real scripts beside it."""

    @staticmethod
    def of(program):
        out = io.BytesIO()
        with tarfile.open(fileobj=out, mode="w:gz") as bundle:
            info = tarfile.TarInfo("caravan-scout")
            data = program.encode()
            info.size, info.mode = len(data), 0o755
            bundle.addfile(info, io.BytesIO(data))
            for script in sorted((ROOT / "rust/crates/scout/scripts").iterdir()):
                bundle.add(script, arcname=f"scripts/{script.name}")
        return out.getvalue()


class Server:
    """The controller's one address the script fetches from, and the scout's answer it waits for."""

    def __init__(self, files):
        files = dict(files)

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                body = files.get(self.path)
                self.send_response(200 if body is not None else 404)
                self.send_header("Content-Length", str(len(body or b"")))
                self.end_headers()
                self.wfile.write(body or b"")

            def log_message(self, *_):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


class Machine:
    """A home of its own and the system commands of a Linux machine, each writing down how it was called."""

    STAND_INS = {
        # The scout's default port is a stand-in's too: the real curl, sent to the local server instead.
        "curl": "#!/usr/bin/env bash\nargs=(\"${@//127.0.0.1:8092/127.0.0.1:${SCOUT_ANSWERS_ON}}\")\nexec \"$REAL_CURL\" \"${args[@]}\"\n",
        "uname": "#!/bin/sh\nif [ \"$1\" = \"-s\" ]; then echo \"${FAKE_SYSTEM:-Linux}\"; else echo x86_64; fi\n",
        "systemctl": "#!/bin/sh\necho \"systemctl $*\" >> \"$CALLS\"\nexit 0\n",
        "loginctl": "#!/bin/sh\necho \"loginctl $*\" >> \"$CALLS\"\nif [ \"$1\" = \"show-user\" ]; then echo no; fi\nexit 0\n",
        # A Mac has `shasum`, a Linux machine has this.
        "sha256sum": "#!/usr/bin/env python3\nimport hashlib, sys\nprint(hashlib.sha256(open(sys.argv[1], 'rb').read()).hexdigest() + '  ' + sys.argv[1])\n",
    }

    def __init__(self, base):
        self.base = base
        self.answers_on = 0
        self.home = base / "home"
        self.home.mkdir(parents=True)
        self.bin = base / "bin"
        self.bin.mkdir()
        self.calls = base / "calls"
        self.calls.touch()
        for name, text in self.STAND_INS.items():
            path = self.bin / name
            path.write_text(text)
            path.chmod(path.stat().st_mode | stat.S_IXUSR)

    def environment(self, more=None):
        env = {"HOME": str(self.home), "USER": "owner", "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}", "CALLS": str(self.calls),
               "REAL_CURL": shutil.which("curl"), "SCOUT_ANSWERS_ON": str(self.answers_on)}
        env.update(more or {})
        return env

    def run(self, script, args=(), more=None):
        """The script through bash's input, as `curl ... | bash` feeds it."""
        return subprocess.run(["bash", "-s", "--", *args], input=script, capture_output=True, text=True, env=self.environment(more), cwd=self.base, timeout=120)

    def told(self):
        return self.calls.read_text().splitlines()

    @property
    def scout_home(self):
        return self.home / "caravan-scout"

    @property
    def unit(self):
        return self.home / ".config/systemd/user/caravan-scout.service"

    def trail(self):
        """Everything the script left in the home, as paths."""
        return sorted(str(path.relative_to(self.home)) for path in self.home.rglob("*"))


def script_for(controller, bundle):
    return TEMPLATE.replace("@@CONTROLLER@@", controller).replace("@@COMMIT@@", COMMIT).replace("@@SHA256@@", hashlib.sha256(bundle).hexdigest())


class Scene:
    """One machine and one controller, for one story."""

    def __init__(self, base, name, served=None, named=None, with_config=True):
        self.machine = Machine(base / name)
        self.bundle = Bundle.of(SCOUT)
        self.port = free_port()
        files = {"/scout/bundle.tar.gz": served if served is not None else self.bundle, "/api/pairing": json.dumps({"ip": "192.0.2.7", "controllerUrl": ""}).encode()}
        self.server = Server(files)
        self.script = script_for(f"http://127.0.0.1:{self.server.port}", named if named is not None else self.bundle)
        # The script waits for the scout on the port of its config: here the stand-in answers on the local server's.
        self.machine.answers_on = self.server.port
        if with_config:
            self.machine.scout_home.mkdir()
            (self.machine.scout_home / "config.json").write_text(json.dumps({"listenPort": self.server.port}, indent=2))

    def install(self, args=("--skip-llama", "--skip-whisper"), more=None):
        return self.machine.run(self.script, args, more)


def a_new_machine(base):
    scene = Scene(base, "new")
    done = scene.install()
    machine = scene.machine
    check("a new machine: it ends well", (done.returncode, done.stderr), (0, ""))
    release = machine.scout_home / "releases" / COMMIT
    check("the link names the release", os.readlink(machine.scout_home / "current"), f"releases/{COMMIT}")
    check("the program stands in the release and runs", subprocess.run([str(release / "caravan-scout"), "--version"], capture_output=True, text=True).stdout, "caravan-scout 9.9.9\n")
    check("its scripts stand beside it", (release / "scripts/update-llama.sh").is_file() and (release / "scripts/uninstall.sh").is_file(), True)
    unit = machine.unit.read_text()
    for line in (f"WorkingDirectory={machine.scout_home}", f"Environment=CARAVAN_SCOUT_ROOT={machine.scout_home}/current",
                 f"Environment=LAMA_CARAVAN_SERVER_CELLS_DIR={machine.scout_home}/var/server-cells",
                 f"ExecStart={machine.scout_home}/current/caravan-scout --config {machine.scout_home}/config.json --state {machine.scout_home}/state.json",
                 "Restart=always", "KillMode=process"):
        check(f"the service says {line.split('=')[0]}", line in unit.splitlines(), True)
    told = machine.told()
    check("the service is read, enabled and started, in that order", [call for call in told if call.startswith("systemctl")],
          ["systemctl --user daemon-reload", "systemctl --user enable caravan-scout.service", "systemctl --user restart caravan-scout.service"])
    check("it stays after logout", "loginctl enable-linger owner" in told, True)
    check("it says the address to enter on the board", "192.0.2.7" in done.stdout and str(scene.server.port) in done.stdout, True)
    check("the bundle's temporary folder is gone, nothing stray in the release's place", sorted(path.name for path in (machine.scout_home / "releases").iterdir()), [COMMIT])
    scene.server.stop()
    return machine


def nothing_here_yet(base):
    """What a machine that never had a scout really looks like: no folder and no config. The scout makes its config when it is paired, and listens on its default until then."""
    scene = Scene(base, "bare", with_config=False)
    done = scene.install()
    machine = scene.machine
    check("a bare machine: it ends well, and does not stop in silence", (done.returncode, done.stderr), (0, ""))
    check("a bare machine: the service was started", "systemctl --user restart caravan-scout.service" in machine.told(), True)
    check("a bare machine: it says the default port", "8092" in done.stdout and "192.0.2.7" in done.stdout, True)
    check("a bare machine: no config was made up", (machine.scout_home / "config.json").exists(), False)
    scene.server.stop()


def run_again(base):
    """Safe to run again: the same release, the service restarted, its config untouched."""
    scene = Scene(base, "again")
    scene.install()
    config = scene.machine.scout_home / "config.json"
    before = config.read_text()
    done = scene.install()
    check("run again: it ends well", done.returncode, 0)
    check("run again: the config is the same", config.read_text(), before)
    check("run again: one release", sorted(path.name for path in (scene.machine.scout_home / "releases").iterdir()), [COMMIT])
    scene.server.stop()


def not_what_was_named(base):
    scene = Scene(base, "wrong", served=Bundle.of(SCOUT) + b"")
    wrong = Scene(base, "wrong-sum", named=b"another bundle")
    done = wrong.install()
    check("another bundle than was named: refused", done.returncode, 1)
    check("another bundle: it says so", "not what the controller named" in done.stderr, True)
    check("another bundle: no release, no service", (wrong.machine.scout_home / "releases").exists() or wrong.machine.unit.exists(), False)
    check("another bundle: the system was not told", wrong.machine.told(), [])
    scene.server.stop()
    wrong.server.stop()


def a_program_that_does_not_run(base):
    broken = Bundle.of(BROKEN)
    scene = Scene(base, "broken", served=broken, named=broken)
    done = scene.install()
    check("a program that does not run here: refused", done.returncode, 1)
    check("a program that does not run: it says so", "does not run on this machine" in done.stderr, True)
    check("a program that does not run: no release, no service", (scene.machine.scout_home / "releases").exists() or scene.machine.unit.exists(), False)
    scene.server.stop()


def another_system(base):
    scene = Scene(base, "mac")
    done = scene.install(more={"FAKE_SYSTEM": "Darwin"})
    check("another system: refused", done.returncode, 1)
    check("another system: it names what it found", "Darwin-x86_64" in done.stderr, True)
    check("another system: nothing fetched, nothing placed", (scene.machine.scout_home / "releases").exists(), False)
    scene.server.stop()


def a_machine_that_ran_a_scout(base):
    """Its pairing, its cells' records and its cache's settings stay: it does not have to be paired anew."""
    scene = Scene(base, "old")
    (scene.machine.scout_home / "config.json").unlink()
    old = scene.machine.home / "projects/caravan-scout"
    old.mkdir(parents=True)
    (old / "config.json").write_text(json.dumps({"listenPort": scene.server.port, "controllerUrl": "http://controller"}, indent=2))
    (old / "state.json").write_text('{"cells": 3}')
    done = scene.install()
    check("a machine that ran a scout: it ends well", done.returncode, 0)
    check("its config came along", json.loads((scene.machine.scout_home / "config.json").read_text())["controllerUrl"], "http://controller")
    check("its state came along", (scene.machine.scout_home / "state.json").read_text(), '{"cells": 3}')
    (old / "config.json").write_text('{"listenPort": 1}')
    scene.install()
    check("negative: a second run does not take the old one over the new one", json.loads((scene.machine.scout_home / "config.json").read_text()).get("listenPort"), scene.server.port)
    scene.server.stop()


def a_download_cut_short(base):
    scene = Scene(base, "cut")
    half = scene.script[: len(scene.script) // 2]
    before = scene.machine.trail()
    done = scene.machine.run(half, ("--skip-llama", "--skip-whisper"))
    check("a download cut short: bash says it is not whole", done.returncode != 0, True)
    check("a download cut short: nothing ran", (scene.machine.trail(), scene.machine.told()), (before, []))
    scene.server.stop()


def unknown_word(base):
    scene = Scene(base, "word")
    done = scene.machine.run(scene.script, ("--no-such",))
    check("an unknown word: refused before anything", (done.returncode, "unknown arg" in done.stderr, scene.machine.told()), (1, True, []))
    scene.server.stop()


def the_card_is_seen(base):
    """The script's own word on the machine's card, under the shell options install.sh runs with. A real lspci prints on after the first match: `grep -q` closed the
    pipe, lspci died of it, pipefail read that as no match, and a machine with two cards got no llama.cpp and no path to it in its config (2026-11-02)."""
    folder = base / "card"
    folder.mkdir()
    script = ROOT / "rust/crates/scout/scripts/install-llama.sh"

    def said(stand_ins):
        tools = folder / f"tools-{len(list(folder.iterdir()))}"
        tools.mkdir()
        for name, body in stand_ins.items():
            path = tools / name
            path.write_text("#!/bin/sh\n" + body + "\n")
            path.chmod(0o755)
        for name in ("grep", "sed", "cat", "mkdir"):
            found = shutil.which(name)
            (tools / name).symlink_to(found)
        line = f"set -euo pipefail; source {script}; if is_nvidia; then echo card; else echo none; fi"
        bash = shutil.which("bash")
        return subprocess.run([bash, "-c", line], env={"PATH": str(tools), "HOME": str(folder)}, capture_output=True, text=True, timeout=60).stdout.strip()

    long_output = 'echo "01:00.0 VGA compatible controller: NVIDIA Corporation"; i=0; while [ $i -lt 50000 ]; do echo "00:00.0 Host bridge: a line that keeps the pipe busy"; i=$((i+1)); done'
    check("lspci that prints on after the card: the card is seen", said({"lspci": long_output}), "card")
    check("nvidia-smi answers: the card is seen, with no lspci at all", said({"nvidia-smi": "exit 0"}), "card")
    check("negative: nvidia-smi fails and lspci names no card", said({"nvidia-smi": "exit 9", "lspci": 'echo "00:00.0 Host bridge: Other"'}), "none")
    check("negative: neither tool on the machine", said({}), "none")
    # A machine with a build already: nothing is fetched, and its config says where the build is.
    home = base / "built"
    llama = home / "llama.cpp/build/bin/llama-server"
    llama.parent.mkdir(parents=True)
    llama.write_text("#!/bin/sh\n")
    (home / "caravan-scout").mkdir()
    line = f'set -euo pipefail; source {script}; is_nvidia() {{ return 0; }}; install_llama "$HOME/caravan-scout" "$HOME/llama.cpp" "" 0'
    linux = home / "tools"
    linux.mkdir()
    (linux / "uname").write_text("#!/bin/sh\necho Linux\n")
    (linux / "uname").chmod(0o755)
    done = subprocess.run([shutil.which("bash"), "-c", line], env={"PATH": f"{linux}{os.pathsep}{os.environ['PATH']}", "HOME": str(home)}, capture_output=True, text=True, timeout=60)
    check("a build that is there is kept", done.returncode, 0)
    told = json.loads((home / "caravan-scout/config.json").read_text())
    check("its config says where the build and the cache are", (told.get("llamaServerBin"), told.get("modelsBasePath")), (str(llama), str(home / "llama-model-cache")))


def taken_off(machine):
    """uninstall.sh of the release: the service and the program go, what is expensive to make stays."""
    (machine.home / "llama.cpp").mkdir()
    (machine.scout_home / "state.json").write_text("{}")
    script = machine.scout_home / "current/scripts/uninstall.sh"
    # What a running scout writes beside its config: an engine's log (2026-11-02: this folder stayed behind on a real machine).
    (machine.scout_home / "engine-logs").mkdir(exist_ok=True)
    (machine.scout_home / "engine-logs" / "ollama.log").write_text("a line", encoding="utf-8")
    done = subprocess.run(["bash", str(script)], capture_output=True, text=True, env=machine.environment(), cwd=machine.base, timeout=120)
    check("taken off: it ends well", (done.returncode, done.stderr.strip()), (0, ""))
    check("taken off: the service is gone", machine.unit.exists(), False)
    check("taken off: the scout's folder is gone", machine.scout_home.exists(), False)
    check("taken off: llama.cpp stays and is named", ((machine.home / "llama.cpp").is_dir(), "rm -rf ~/llama.cpp" in done.stdout), (True, True))


def main():
    if not shutil.which("bash") or not shutil.which("curl"):
        print("scout install: SKIPPED, this machine has no bash or curl")
        return 0
    with tempfile.TemporaryDirectory(prefix="scout-install-") as raw:
        base = Path(raw).resolve()
        machine = a_new_machine(base)
        nothing_here_yet(base)
        run_again(base)
        not_what_was_named(base)
        a_program_that_does_not_run(base)
        another_system(base)
        a_machine_that_ran_a_scout(base)
        a_download_cut_short(base)
        unknown_word(base)
        the_card_is_seen(base)
        taken_off(machine)
    if FAILED:
        print(f"scout install: FAILED, {len(FAILED)}")
        return 1
    print("scout install: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
