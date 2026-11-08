#!/usr/bin/env python3
"""A whole caravan on one laptop, to check the board with no machine at hand.

The real controller, proxy and scout of this tree, built in rust/target/release, talk over loopback, through their real protocol:
the pairing, the pulses, a start with its command line. Only what the laptop lacks is stood in for: the cards (bin/nvidia-smi),
the engines (bin/llama-server, bin/vllm), the scout's address and RAM (its config says them), and the weights of the models (models.py).

Everything lives in one folder with its own HOME: nothing of a real fleet is read or touched, no real machine is asked
anything, and every listener is on 127.0.0.1. A laptop away from home is on somebody else's network.

The folder is the system's temporary one, not var/ of this tree: its models are holes that say they weigh 174 GiB, and whatever
copies a working tree (a mutant run, an rsync, a backup) would write those zeros out.

Run: (cd rust && cargo build --release -p admin -p proxy -p scout)
     python3 scripts/stand/stand.py   (in the foreground, until SIGTERM; .claude/launch.json can run it as a preview)
The board: http://127.0.0.1:8799, signed in with the account in <folder>/account.json (made here, for here).
"""
import http.cookiejar
import json
import os
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))

from cards import StandCards  # noqa: E402
from models import StandModels  # noqa: E402


class DiskGuard:
    """The stand does not eat the laptop's disk.

    Its models are holes that say they weigh 174 GiB. Should anything ever copy one byte by byte (a start that does not read
    the library in place, a download into the scout's cache), the zeros are real, and they would fill the disk in minutes
    with the owner's work on it. So the stand stops itself first: below FREE_FLOOR_GIB left on the disk, or above
    OWN_CEILING_GIB of its own. What it takes in normal work is a few MB of logs and state.
    """

    GIB = 1024 ** 3
    FREE_FLOOR_GIB = 8
    OWN_CEILING_GIB = 2

    def __init__(self, root, free_bytes=None, own_bytes=None):
        self.root = Path(root)
        self.free_bytes = free_bytes or (lambda: shutil.disk_usage(self.existing()).free)
        self.own_bytes = own_bytes or self.walk

    def existing(self):
        path = self.root
        while not path.exists():
            path = path.parent
        return path

    def walk(self):
        """What the stand's files really take: blocks on the disk, not the size they say."""
        total = 0
        for folder, _dirs, files in os.walk(self.root):
            for name in files:
                try:
                    total += os.lstat(os.path.join(folder, name)).st_blocks * 512
                except OSError:
                    pass    # a log rotated or a claim dropped between the listing and the look
        return total

    def why_stop(self):
        """The words to stop with, None while there is room."""
        free, own = self.free_bytes() / self.GIB, self.own_bytes() / self.GIB
        if free < self.FREE_FLOOR_GIB:
            return f"{free:.1f} GiB left on the disk, the floor is {self.FREE_FLOOR_GIB}"
        if own > self.OWN_CEILING_GIB:
            return f"the stand itself takes {own:.1f} GiB of the disk, its ceiling is {self.OWN_CEILING_GIB}: something copied a model"
        return None


class StandControllerApi:
    """The controller's API as the stand uses it: a session and JSON both ways."""

    def __init__(self, url):
        self.url = url
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def call(self, method, path, body=None, timeout=20):
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(self.url + path, data=data, method=method,
                                         headers={"Content-Type": "application/json"})
        with self.opener.open(request, timeout=timeout) as response:
            return json.loads(response.read() or b"{}")

    def wait_up(self, seconds=45):
        deadline = time.time() + seconds
        while time.time() < deadline:
            try:
                return self.call("GET", "/health", timeout=3)
            except (urllib.error.URLError, OSError):
                time.sleep(0.5)
        raise SystemExit(f"the controller did not answer at {self.url} in {seconds} s")


class Stand:
    PORT = 8799
    SCOUT_PORT = 18092
    HOST_ID = "stand-box"
    #: Stopped cells on the bench, ready to be dragged, by their models: a cell has no port until its scout leases one at its start
    #: (2026-11-08), and its name is the controller's. The second is the one to split between the cards.
    CELLS = (
        ("stand-small-8B-Q4_K_M.gguf", "16384"),
        ("stand-chat-27B-Q4_K_M.gguf", "32768"),
        ("stand-coder-70B-Q3_K_M.gguf", "32768"),
        ("stand-huge-120B-Q4_K_M.gguf", "32768"),
    )
    #: vLLM over checkpoints: the second has more weights than either card's share holds.
    VLLM_CELLS = (
        ("stand-vllm-small-8B", "32768"),
        ("stand-vllm-big-70B", "32768"),
    )

    #: The machine the stand stands in for has this much; on macOS a scout measures no used memory at all, and a stand that only ever draws that says nothing of a Linux
    #: machine. Its scout listens on loopback only: the address of the default route would lead nowhere, and on a borrowed network it is nobody's business anyway.
    RAM = {"usedGb": 8.4, "totalGb": 60.5}
    ADDRESS = "127.0.0.1"
    SCOUT_ROOT = ROOT / "rust" / "crates" / "scout"

    def __init__(self, root=None, programs=None):
        self.root = Path(root or os.environ.get("CARAVAN_STAND_DIR") or Path(tempfile.gettempdir()) / "caravan-stand")
        self.programs = Path(programs or os.environ.get("CARAVAN_STAND_PROGRAMS") or ROOT / "rust" / "target" / "release")
        self.data = self.root / "data"
        self.home = self.root / "home"
        self.account_file = self.root / "account.json"
        self.url = f"http://127.0.0.1:{self.PORT}"
        self.api = StandControllerApi(self.url)
        self.disk = DiskGuard(self.root)
        self.children = []

    def base_env(self):
        env = dict(os.environ)
        env.update({"HOME": str(self.home), "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1",
                    StandCards.ROOT_VAR: str(self.root)})
        return env

    def controller_env(self):
        return {**self.base_env(), "LLAMACPP_ADMIN_HOST": "127.0.0.1", "LLAMACPP_ADMIN_PORT": str(self.PORT), "CARAVAN_ROOT": str(self.release),
                "CARAVAN_DATA_DIR": str(self.data), "LLAMA_MODELS_DIR": str(self.data / "models"), "AGENT_PROXY_HOST": "127.0.0.1"}

    def scout_env(self):
        return {**self.base_env(), "PATH": f"{HERE / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}",
                "CARAVAN_SCOUT_ROOT": str(self.SCOUT_ROOT), "LAMA_CARAVAN_SERVER_CELLS_DIR": str(self.root / "scout" / "server-cells")}

    def scout_config(self):
        return {"hostId": self.HOST_ID, "displayName": self.HOST_ID, "listenHost": "127.0.0.1", "listenPort": self.SCOUT_PORT,
                "heartbeatIntervalSeconds": 5, "llamaServerBin": str(HERE / "bin" / "llama-server"),
                "modelsBasePath": str(self.root / "scout" / "cache"), "llamaNodeDefaultPort": 22001, "standAddress": self.ADDRESS, "standRam": self.RAM}

    @property
    def release(self):
        """The folder the controller stands in, laid out as a release: the board's files and the cell servers of this tree, the proxy it keeps as its child."""
        return self.root / "release"

    def lay_out_release(self):
        (self.release / "bin").mkdir(parents=True, exist_ok=True)
        for link, target in ((self.release / "static", ROOT / "static"), (self.release / "cells", ROOT / "cells"), (self.release / "VERSION", ROOT / "VERSION"),
                             (self.release / "bin" / "caravan-proxy", self.programs / "caravan-proxy")):
            if not link.is_symlink():
                link.symlink_to(target)

    def venv(self):
        """vLLM where the caravan looks for it, under the stand's HOME, so the real start line runs. A start asks a login shell, which
        rebuilds the PATH: these say which Python they want."""
        folder = self.home / "vllm-venv" / "bin"
        folder.mkdir(parents=True, exist_ok=True)
        shims = {"vllm": f'exec "{sys.executable}" "{HERE / "bin" / "vllm"}" "$@"', "ninja": "exit 0"}
        for name, line in shims.items():
            path = folder / name
            path.write_text(f"#!/bin/sh\n{line}\n", encoding="utf-8")
            path.chmod(0o755)

    def prepare(self):
        missing = [name for name in ("caravan-admin", "caravan-proxy", "caravan-scout") if not (self.programs / name).is_file()]
        if missing:
            raise SystemExit(f"no {', '.join(missing)} in {self.programs}: (cd rust && cargo build --release -p admin -p proxy -p scout), or set CARAVAN_STAND_PROGRAMS")
        no_room = self.disk.why_stop()
        if no_room:
            raise SystemExit(f"stand: not started: {no_room}")
        for folder in (self.data, self.home, self.root / "scout"):
            folder.mkdir(parents=True, exist_ok=True)
        StandModels(self.data / "models").write()
        self.venv()
        self.lay_out_release()
        # The stand's facts over what the scout wrote there: a pairing stays, and a folder from an older stand takes the facts it lacks.
        config = self.root / "scout" / "config.json"
        kept = json.loads(config.read_text(encoding="utf-8")) if config.exists() else {}
        config.write_text(json.dumps({**kept, **self.scout_config()}, indent=1), encoding="utf-8")

    def spawn(self, label, argv, env, cwd):
        log = (self.root / f"{label}.log").open("a", encoding="utf-8")
        self.children.append((label, subprocess.Popen(argv, env=env, cwd=cwd, stdout=log, stderr=subprocess.STDOUT)))

    def start_controller(self):
        self.spawn("controller", [str(self.programs / "caravan-admin")], self.controller_env(), self.release)

    def start_scout(self):
        scout = self.root / "scout"
        self.spawn("scout", [str(self.programs / "caravan-scout"), "--config", str(scout / "config.json"), "--state", str(scout / "state.json")], self.scout_env(), scout)

    def sign_in(self, health):
        if health.get("setupRequired"):
            account = {"username": "stand", "password": secrets.token_urlsafe(18)}
            self.account_file.write_text(json.dumps(account), encoding="utf-8")
            self.account_file.chmod(0o600)
            self.api.call("POST", "/api/auth/setup", account)
            return
        self.api.call("POST", "/api/auth/login", json.loads(self.account_file.read_text(encoding="utf-8")))

    def pair(self):
        deadline = time.time() + 30
        while True:
            try:
                return self.api.call("POST", "/api/topology/scout/connect", {"address": "127.0.0.1", "port": self.SCOUT_PORT})
            except urllib.error.HTTPError as exc:
                said = exc.read().decode(errors="replace")[:300]
            except (urllib.error.URLError, OSError) as exc:
                said = str(exc)
            if time.time() > deadline:
                raise SystemExit(f"the scout was not paired: {said}")
            time.sleep(1)

    #: What names a bench cell's model in its settings.
    MODEL_KEYS = ("MODEL_FILE", "VLLM_MODEL")

    def add_cells(self):
        """The bench, first time only, a cell by its model: a cell an earlier run changed keeps what it was changed to, and a run
        makes no second cell of a model the bench has."""
        topology = self.api.call("GET", "/api/topology")
        have = {(server.get("slotConfig") or {}).get(key) for node in topology.get("nodes") or [] if node.get("id") == self.HOST_ID
                for server in node.get("servers") or [] for key in self.MODEL_KEYS}
        cells = [{"RUNNER": "llama-server", "MODEL_FILE": model, "HOST": "0.0.0.0", "CTX_SIZE": window, "N_GPU_LAYERS": "999", "PARALLEL": "1"}
                 for model, window in self.CELLS]
        cells += [{"RUNNER": "vllm", "VLLM_MODEL": str(self.data / "models" / model), "MAX_MODEL_LEN": window} for model, window in self.VLLM_CELLS]
        for config in cells:
            if any(config.get(key) in have for key in self.MODEL_KEYS):
                continue
            # No cell's id: the controller makes the cell and names it.
            self.api.call("POST", "/api/topology/server-cell/save-config", {"hostId": self.HOST_ID, "config": config, "cacheModels": False})

    def up(self):
        self.prepare()
        self.start_controller()
        self.sign_in(self.api.wait_up())
        self.start_scout()
        paired = self.pair()
        self.add_cells()
        print(f"stand: {self.url}, machine {paired.get('hostId')}, {len(self.CELLS) + len(self.VLLM_CELLS)} cells on the bench", flush=True)

    def down(self, _signum=None, _frame=None):
        for _label, child in self.children:
            child.terminate()
        for _label, child in self.children:
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
        # A scout's cells outlive it on purpose (they are adopted at its next start); the stand's are the stand's to end.
        for pid in (int(row["pid"]) for row in StandCards(self.root).claims()):
            try:
                if pid:
                    os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        sys.exit(0)

    def watch(self):
        while True:
            for label, child in self.children:
                if child.poll() is not None:
                    print(f"stand: the {label} ended with code {child.returncode}; see {self.root / (label + '.log')}", flush=True)
                    self.down()
            no_room = self.disk.why_stop()
            if no_room:
                print(f"stand: stopped: {no_room}", flush=True)
                self.down()
            time.sleep(1)


def main():
    stand = Stand()
    signal.signal(signal.SIGTERM, stand.down)
    signal.signal(signal.SIGINT, stand.down)
    try:
        stand.up()
    except BaseException:
        for _label, child in stand.children:
            child.terminate()
        raise
    stand.watch()


if __name__ == "__main__":
    main()
