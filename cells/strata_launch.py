"""Strata for a caravan cell: its pack and draft layer made from the model the
scout brought, its config written, its server started in this process's place.

run_strata.sh runs this with Strata's own Python, so Strata's facts are read
from Strata itself — its setup.py's tables (models, families, draft
vocabularies, the KV-streaming rule) and its tools (iq_pack.py, mtp_rt.py,
gguf_reader) — instead of copied here, where they would drift with every
Strata release. Settled against Strata v0.1.42. The parts of its setup this
does not do it refuses by name: the low-RAM mode, Unsloth's RAM-budget files,
several cards.

What it makes goes to CARAVAN_CELL_SCRATCH, the scout's scratch folder of the
cell: kept with the cell's models when it caches them, gone with them when it
does not. A start whose model, draft layer, token subset and Strata are those
of the last start uses what that start made (made.json) instead of writing
2.3 GB to the disk again — the disks' wear is why the cells keep their models
(the owner, 2026-10-13). Made anew, the pack takes seconds from the GGUF and
the draft layer's runtime as long from its file.

    python strata_launch.py --strata-home ~/Strata --port 22009 \\
        <first GGUF part> [--mtp mtp-q2_0.gguf] [--context N] [--kv int8] ...
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


class StrataLaunch:
    """One start of a Strata cell, from its arguments to the exec of Strata's
    server. Each step raises Refusal with what is missing; nothing is guessed."""

    #: The trained window of Qwen3.8-Flash-Next: past it Strata's setup adds
    #: yarn with the factor context / 262144, and so does this.
    TRAINED_CONTEXT = 262144
    #: The KV positions per layer kept in VRAM when the cache streams from RAM
    #: (setup.py step 7 writes the same number).
    KV_RESIDENT = "32768"
    PART = re.compile(r"^(?P<stem>.+)-00001-of-(?P<count>\d{5})(?P<ext>\.gguf)$", re.IGNORECASE)

    class Refusal(Exception):
        """A start that cannot work, said in one line for the cell's log."""

    def __init__(self, args: argparse.Namespace, env: dict | None = None):
        self.args = args
        self.env = dict(os.environ if env is None else env)
        self.home = Path(args.strata_home).expanduser()
        scratch = args.work or self.env.get("CARAVAN_CELL_SCRATCH") or ""
        self.work = Path(scratch).expanduser() if scratch else Path.home() / ".cache" / "caravan-strata" / str(args.port)
        self.setup = None

    # ── Strata itself ───────────────────────────────────────────────────────
    def strata(self):
        """Strata's setup.py as a module: its tables and rules. Loaded by path,
        so no other `setup` on the path can stand in for it."""
        if self.setup is not None:
            return self.setup
        path = self.home / "setup.py"
        engine = self.home / "engine"
        if not path.is_file() or not (engine / "BUILD.json").is_file():
            raise self.Refusal(f"no Strata installed at {self.home} (setup.py and engine/BUILD.json) — "
                               f"install it with Strata's setup.sh")
        spec = importlib.util.spec_from_file_location("strata_setup", path)
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception as exc:  # noqa: BLE001 — any failure is "cannot read it"
            raise self.Refusal(f"cannot read Strata's setup.py at {path}: {exc}")
        need = ("MODELS", "FAMILIES", "DRAFT_VOCABS", "EXE", "gguf_choice", "kv_streaming_wanted",
                "low_ram_wanted", "ram_gb")
        missing = [name for name in need if not hasattr(module, name)]
        if missing:
            raise self.Refusal(f"this Strata has no setup.{missing[0]} — the caravan's launcher knows v0.1.42")
        self.setup = module
        return module

    def engine(self) -> tuple[Path, dict]:
        """The engine binary and its build record (where its CUDA libraries are).
        Asks for the install first: without it there is no record to read."""
        exe = self.home / "engine" / self.strata().EXE
        build = json.loads((self.home / "engine" / "BUILD.json").read_text(encoding="utf-8"))
        if not exe.is_file():
            raise self.Refusal(f"Strata's engine is not built: {exe} — run Strata's setup.sh")
        return exe, build

    # ── the model ───────────────────────────────────────────────────────────
    def shards(self) -> list[Path]:
        """The model's parts, the first first: the scout brings them beside
        the first one."""
        first = Path(self.args.model).expanduser()
        match = self.PART.match(first.name)
        parts = [first] if not match else [
            first.with_name(f"{match['stem']}-{i:05d}-of-{match['count']}{match['ext']}")
            for i in range(1, int(match["count"]) + 1)]
        missing = [p for p in parts if not p.is_file()]
        if missing:
            raise self.Refusal(f"the model's file is not here: {missing[0]}")
        return parts

    def choice(self, first: Path) -> tuple[str, str]:
        """(family, size) as Strata names them, from the first part's name —
        the published names are the only ones Strata knows how to run."""
        found = self.strata().gguf_choice(first.name)
        if not found:
            raise self.Refusal(f"Strata does not know the file {first.name}: it runs the published "
                               f"Qwen3.8-Flash-Next GGUFs, by their names")
        family, size = found
        model = self.strata().MODELS[size]
        if model.get("budget"):
            raise self.Refusal(f"{size} keeps a RAM budget of its experts (--resident-budget-gib), "
                               f"which the caravan's Strata cell does not set up yet")
        if self.strata().low_ram_wanted(size, self.strata().ram_gb()):
            raise self.Refusal(f"{size} needs Strata's low-RAM mode on this machine "
                               f"({self.strata().ram_gb():.0f} GB of RAM), which the caravan's Strata cell "
                               f"does not set up yet")
        return family, size

    def ple(self, shards: list[Path]) -> Path | None:
        """The part holding the n-gram table (per_layer_token_embd), named to
        the engine when the model has two parts; with more, the engine finds
        it from the first (setup.py step 7)."""
        if len(shards) > 2:
            return None
        sys.path.insert(0, str(self.home / "tools"))
        from gguf_reader import GGUFFile   # Strata's own reader: the header only
        for shard in shards:
            if any(t.name == "per_layer_token_embd.weight" for t in GGUFFile(shard).tensors):
                return shard
        raise self.Refusal("the model has no per_layer_token_embd tensor — is it a Qwen3.8-Flash-Next GGUF?")

    # ── what Strata makes from it ───────────────────────────────────────────
    def tool_env(self) -> dict:
        return {**self.env, "STRATA_GGUF_PY": str(self.home / "third_party" / "llama.cpp" / "gguf-py")}

    def run(self, argv: list[str]) -> None:
        print("[strata] " + " ".join(argv), flush=True)
        done = subprocess.run(argv, env=self.tool_env(), cwd=str(self.home))
        if done.returncode != 0:
            raise self.Refusal(f"{Path(argv[1]).name} failed (exit {done.returncode})")

    def pack(self, first: Path, family: str) -> Path:
        """Every tensor as the GGUF stores it, the experts read from the GGUF
        at start (iq_pack.py: seconds). Strata's Q2_0 repack for AVX-512 is a
        40 GB conversion and is not made here; the pack works without it."""
        out = self.work / "pack"
        shutil.rmtree(out, ignore_errors=True)
        args = list(self.strata().FAMILIES[family].get("pack_args", []))
        self.run([sys.executable, str(self.home / "tools" / "iq_pack.py"), "--gguf", str(first),
                  "--out", str(out), *args])
        if not (out / "native_experts.txt").is_file() or not (out / "tokenizer" / "vocab.json").is_file():
            raise self.Refusal(f"the pack in {out} is incomplete")
        return out

    def draft(self) -> Path | None:
        """The MTP draft layer's runtime, from its GGUF, with the token subset
        asked for: None when the cell names no draft layer — Strata then runs
        without speculative decoding, about half as fast."""
        source = self.draft_source()
        if source is None:
            return None
        rt = self.work / "mtp" / "rt"
        shutil.rmtree(rt.parent, ignore_errors=True)
        self.run([sys.executable, str(self.home / "tools" / "mtp_rt.py"), "--gguf", str(source), "--out", str(rt)])
        vocab = self.home / "data" / self.strata().DRAFT_VOCABS[self.args.draft_vocab]
        if not vocab.is_file():
            raise self.Refusal(f"Strata has no draft vocabulary {self.args.draft_vocab}: {vocab}")
        shutil.copyfile(vocab, rt / "draft_vocab.bin")
        return rt

    def draft_source(self) -> Path | None:
        """The draft layer's file the cell names, refused when it is not there;
        None when the cell names none."""
        if not self.args.mtp:
            return None
        source = Path(self.args.mtp).expanduser()
        if not source.is_file():
            raise self.Refusal(f"the draft layer's file is not here: {source}")
        return source

    #: What a start wrote last, beside what it made: what it made it from.
    MADE = "made.json"

    def made_from(self, first: Path, build: dict, family: str) -> dict:
        """What the pack and the draft layer are made of: the model's first
        part and the draft layer's file (path, size, time), the token subset,
        the pack's options and the Strata that makes them."""
        def file(path):
            st = path.stat()
            return [str(path), st.st_size, st.st_mtime_ns]
        return {"model": file(first),
                "mtp": file(self.draft_source()) if self.args.mtp else None,
                "draftVocab": self.args.draft_vocab,
                "packArgs": list(self.strata().FAMILIES[family].get("pack_args", [])),
                "strata": [build.get("version"), build.get("src")]}

    def reusable(self, made: dict) -> bool:
        """The last start made the same things from the same files, and they
        are all still there."""
        try:
            last = json.loads((self.work / self.MADE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        pack = self.work / "pack"
        whole = (pack / "native_experts.txt").is_file() and (pack / "tokenizer" / "vocab.json").is_file()
        if made.get("mtp"):
            whole = whole and (self.work / "mtp" / "rt" / "experts.bin").is_file()
        return last == made and whole

    def gpu(self) -> int:
        """The card, numbered as nvidia-smi numbers them: the one the cell's
        environment pins, else the first. Strata's server sets the engine's
        CUDA_VISIBLE_DEVICES from it."""
        pinned = self.env.get("CUDA_VISIBLE_DEVICES")
        if pinned is None:
            return 0
        if not pinned.strip().isdigit():
            raise self.Refusal(f"Strata runs on one card; CUDA_VISIBLE_DEVICES is {pinned!r}")
        return int(pinned.strip())

    def engine_args(self, first: Path, ple: Path | None, pack: Path, rt: Path | None,
                    family: str, size: str) -> list[str]:
        """The engine's arguments, as Strata's setup.py step 7 writes them."""
        a, strata = self.args, self.strata()
        profile = strata.FAMILIES[family].get("profile", "expert-profile.bin")
        args = ["--pack", str(pack), "--native", str(first)]
        if ple:
            args += ["--ple-gguf", str(ple)]
        args += ["--expert-profile", str(self.home / "data" / profile), "--expert-cache", "auto",
                 "--prefill", "auto"]
        if rt:
            args += ["--spec", "4", "--spec-min-p", "0.5", "--mtp", str(rt)]
        args += ["--max-context", str(a.context)]
        if a.context > self.TRAINED_CONTEXT:
            args += ["--rope-scaling", "yarn", "--rope-scale", f"{a.context / self.TRAINED_CONTEXT:g}"]
        if a.context > 8192:
            args += ["--kv", a.kv]
        if strata.kv_streaming_wanted(size, a.context, a.kv, strata.ram_gb()):
            args += ["--kv-resident", self.KV_RESIDENT]
        if a.vram_reserve_mib:
            args += ["--vram-reserve-mib", str(a.vram_reserve_mib)]
        return args

    def config(self) -> Path:
        """Everything above, written as Strata's server reads it."""
        exe, build = self.engine()
        shards = self.shards()
        family, size = self.choice(shards[0])
        gpu = self.gpu()
        self.work.mkdir(parents=True, exist_ok=True)
        ple = self.ple(shards)
        made = self.made_from(shards[0], build, family)
        if self.reusable(made):
            pack = self.work / "pack"
            rt = self.work / "mtp" / "rt" if self.args.mtp else None
            print(f"[strata] the pack and the draft layer of the last start are this model's: kept", flush=True)
        else:
            (self.work / self.MADE).unlink(missing_ok=True)
            pack = self.pack(shards[0], family)
            rt = self.draft()
            (self.work / self.MADE).write_text(json.dumps(made, indent=1), encoding="utf-8")
        cfg = {
            "exe": str(exe),
            "args": self.engine_args(shards[0], ple, pack, rt, family, size),
            "cwd": str(self.home),
            "tokenizer": str(pack / "tokenizer"),
            "model_name": self.args.name or self.strata().FAMILIES[family]["name"],
            "log": str(self.work / "engine.log"),
            "lib_dirs": build.get("lib_dirs") or build.get("cuda_dirs") or [],
            "port": self.args.port,
            "gpu": gpu,
            "draft_vocab": self.args.draft_vocab,
        }
        path = self.work / "strata.json"
        path.write_text(json.dumps(cfg, indent=1), encoding="utf-8")
        print(f"[strata] {size} ({family}), context {self.args.context}, KV {self.args.kv}, "
              f"draft layer {'on' if rt else 'off'}: {path}", flush=True)
        return path

    def server_argv(self, config: Path) -> list[str]:
        return [sys.executable, str(self.home / "serve" / "server.py"), "--engine", "strata",
                "--config", str(config), "--host", "0.0.0.0", "--port", str(self.args.port)]

    def start(self) -> None:
        """Make it all and become Strata's server: the scout tracks this
        process, so it must be the server, not a parent waiting on one."""
        argv = self.server_argv(self.config())
        os.chdir(self.home)
        os.execve(argv[0], argv, self.env)

    @staticmethod
    def parser() -> argparse.ArgumentParser:
        ap = argparse.ArgumentParser(description="Start Strata for a caravan cell")
        ap.add_argument("port", type=int)
        ap.add_argument("model", help="the model's first GGUF part")
        ap.add_argument("--strata-home", default=str(Path.home() / "Strata"))
        ap.add_argument("--mtp", default="", help="the MTP draft layer's GGUF (mtp-q2_0.gguf)")
        ap.add_argument("--context", type=int, default=131072)
        ap.add_argument("--kv", choices=["int8", "q4_0", "k8v4"], default="int8")
        ap.add_argument("--draft-vocab", choices=["cyrillic", "cjk", "en", "fr"], default="cyrillic")
        ap.add_argument("--vram-reserve-mib", type=int, default=0)
        ap.add_argument("--name", default="")
        ap.add_argument("--work", default="", help="where the pack goes (default: CARAVAN_CELL_SCRATCH)")
        return ap


def main(argv: list[str] | None = None) -> int:
    """Why a function: the entry point the launcher runs — it only parses and
    hands over to StrataLaunch."""
    args = StrataLaunch.parser().parse_args(argv)
    if args.context <= 0:
        print("strata: --context must be a positive number of tokens", file=sys.stderr)
        return 2
    try:
        StrataLaunch(args).start()
    except StrataLaunch.Refusal as exc:
        print(f"strata: {exc}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
