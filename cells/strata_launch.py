"""Strata for a caravan cell: its pack and draft layer made from the model the
scout brought, its config written, its server started in this process's place.

run_strata.sh runs this with Strata's own Python, so Strata's facts are read
from Strata itself — its setup.py's tables (models, families, draft
vocabularies, the KV-streaming rule) and its tools (iq_pack.py, mtp_rt.py,
gguf_reader) — instead of copied here, where they would drift with every
Strata release. Settled against the Strata named once by `KNOWS` below; the one
before it, v0.1.42, still starts, so a Strata put back keeps working. The parts of its setup this does
not do it refuses by name: the low-RAM mode and several cards. Unsloth's ~4-bit
packs (UD-IQ4_XS, UD-Q4_K_XL) run with the RAM budget of their experts that
Strata's own rule recommends for the machine (`--resident-budget-gib`).

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

    #: The Strata this launcher was written against: the version its setup.py's tables and rules
    #: were read from, and the version the pins hold. Named once, here — the refusal that says
    #: which version the launcher knows reads this, so the words and the check cannot name two
    #: versions. A newer Strata is not refused for being newer: it is refused by the name of the
    #: rule it lacks.
    KNOWS = "v0.2.11"

    #: The trained window of Qwen3.8-Flash-Next: a start that names no window
    #: asks for it (the owner, 2026-10-26: an empty context field means the
    #: window the model was trained for — it was 131072, Strata's figure for a
    #: 32 GB card); past it Strata's setup adds yarn with the factor
    #: context / 262144, and so does this.
    TRAINED_CONTEXT = 262144
    #: The KV positions per layer kept in VRAM when the cache streams from RAM
    #: (setup.py step 7 writes the same number).
    KV_RESIDENT = "32768"
    PART = re.compile(r"^(?P<stem>.+)-00001-of-(?P<count>\d{5})(?P<ext>\.gguf)$", re.IGNORECASE)

    class Refusal(Exception):
        """A start that cannot work, said in one line for the cell's log."""

    def __init__(self, args: argparse.Namespace, env: dict | None = None):
        self.args = args
        if args.context is None:
            args.context = self.default_window()
        self.env = dict(os.environ if env is None else env)
        self.home = Path(args.strata_home).expanduser()
        scratch = args.work or self.env.get("CARAVAN_CELL_SCRATCH") or ""
        self.work = Path(scratch).expanduser() if scratch else Path.home() / ".cache" / "caravan-strata" / str(args.port)
        self.setup = None

    def default_window(self) -> int | None:
        """The window of a start that names none: the one the model was trained for."""
        return self.TRAINED_CONTEXT

    # ── Strata itself ───────────────────────────────────────────────────────
    def strata(self):
        """Strata's setup.py as a module: its tables and rules. Loaded by path,
        so no other `setup` on the path can stand in for it; its folder goes on
        the path for the packages it imports (strata_control, since v0.2)."""
        if self.setup is not None:
            return self.setup
        path = self.home / "setup.py"
        engine = self.home / "engine"
        if not path.is_file() or not (engine / "BUILD.json").is_file():
            raise self.Refusal(f"no Strata installed at {self.home} (setup.py and engine/BUILD.json) — "
                               f"install it with Strata's setup.sh")
        spec = importlib.util.spec_from_file_location("strata_setup", path)
        module = importlib.util.module_from_spec(spec)
        sys.path.insert(0, str(self.home))
        try:
            spec.loader.exec_module(module)
        except Exception as exc:  # noqa: BLE001 — any failure is "cannot read it"
            raise self.Refusal(f"cannot read Strata's setup.py at {path}: {exc}")
        need = ("MODELS", "FAMILIES", "DRAFT_VOCABS", "EXE", "gguf_choice", "kv_streaming_wanted",
                "kv_streaming_ram_gb", "low_ram_wanted", "ram_gb", "resident_budget_gib")
        missing = [name for name in need if not hasattr(module, name)]
        if missing:
            raise self.Refusal(f"this Strata has no setup.{missing[0]} — the caravan's launcher knows {self.KNOWS}")
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

    def drafter(self, rt: Path | None) -> str:
        """Which drafter this start runs, as Strata's server reads it in the config's `drafting`.
        It has to be written, not left out: from Strata v0.2.10 the server decides the drafter from
        this key, and its default is Auto — Auto is DFlash2 for the models it was made for. So a key
        left out would run a drafter the cell did not name (and take its VRAM): this says what the
        cell itself chose — the layer it names, or none."""
        return "mtp" if rt else "off"

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

    def card_arch(self, gpu: int) -> int | None:
        """The architecture of card `gpu` as Strata's engine counts them (RTX 3090: 86, RTX 5090: 120), from the compute
        capability nvidia-smi names; None when it does not say (no nvidia-smi, no such card)."""
        try:
            out = subprocess.run(["nvidia-smi", "--query-gpu=index,compute_cap", "--format=csv,noheader"],
                                 capture_output=True, text=True, timeout=10, env=self.env).stdout
        except (OSError, subprocess.SubprocessError):
            return None
        for line in out.splitlines():
            index, _, cap = (part.strip() for part in line.partition(","))
            if index == str(gpu) and re.fullmatch(r"\d+\.\d+", cap):
                return int(cap.replace(".", ""))
        return None

    def has_code_for(self, build: dict, gpu: int) -> None:
        """Refuses when the engine was compiled for other architectures than the card's: a CUDA kernel image of another
        architecture does not run, and the cell would die at its first kernel with "no kernel image" a minute into the
        start. The engine says what it was built for (BUILD.json `archs`, and `ptx` when it carries PTX for newer
        cards); a card nvidia-smi does not name is not refused (2026-10-17: an engine built for the RTX 5090 alone
        met a cell pinned to the RTX 3090 that came to stand beside it)."""
        # A ready-made engine's record can write them as one string ("86;120"): Strata's own reader knows; v0.1.42 has none.
        read = getattr(self.strata(), "arch_numbers", None)
        archs = sorted(read(build.get("archs")) if read else (int(a) for a in build.get("archs") or []))
        arch = self.card_arch(gpu) if archs else None
        if arch is None or arch in archs or (build.get("ptx") and arch > max(archs)):
            return
        raise self.Refusal(f"Strata's engine has code for {', '.join(f'sm_{a}' for a in archs)} and GPU {gpu} is sm_{arch}: "
                           f"pin the cell to a card the engine has code for, or build it for this card too "
                           f"(Strata's setup.sh --gpus <the cards>)")

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

    def budget_mode(self, size: str) -> bool:
        """Does this pack keep only a budget of its experts in RAM? Strata's rule for the machine: an Unsloth pack whose
        experts fit with room beside them keeps them all. v0.1.42 has no such rule: every such pack kept a budget."""
        strata = self.strata()
        if not strata.MODELS[size].get("budget"):
            return False
        rule = getattr(strata, "unsloth_budget", None)
        return rule(size, strata.ram_gb()) if rule else True

    def engine_env(self, family: str, size: str) -> dict:
        """The engine settings Strata's setup writes for this pack on CUDA (its `hip` answer is False). Most packs have
        none; v0.1.42 has no such rule and writes none."""
        rule = getattr(self.strata(), "unsloth_default_env", None)
        return rule(family, size, False, self.budget_mode(size)) if rule else {}

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
        if self.budget_mode(size):
            # Unsloth's ~4-bit packs hold more experts than the RAM does: the engine keeps a budget of them in RAM and reads
            # the rest from the file. The size is Strata's own recommendation for this machine (the RAM less 24 GiB for the
            # system and the file cache the rest is read through, less the RAM a streamed KV cache takes), as setup writes it.
            kv_ram = strata.kv_streaming_ram_gb(a.context, a.kv) if "--kv-resident" in args else 0.0
            args += ["--resident-budget-gib", f"{strata.resident_budget_gib(size, strata.ram_gb(), kv_ram):g}"]
        if a.vram_reserve_mib:
            args += ["--vram-reserve-mib", str(a.vram_reserve_mib)]
        return args

    def config(self) -> Path:
        """Everything above, written as Strata's server reads it."""
        exe, build = self.engine()
        shards = self.shards()
        family, size = self.choice(shards[0])
        gpu = self.gpu()
        self.has_code_for(build, gpu)
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
            "drafting": self.drafter(rt),
        }
        env = self.engine_env(family, size)
        if env:
            cfg["env"] = env
        path = self.work / "strata.json"
        path.write_text(json.dumps(cfg, indent=1), encoding="utf-8")
        print(f"[strata] {size} ({family}), context {self.args.context}, KV {self.args.kv}, "
              f"draft layer {'on' if rt else 'off'}: {path}", flush=True)
        return path

    def server_argv(self, config: Path) -> list[str]:
        # On the machine's loopback, as every cell listens: the scout reaches it there (rules::CellDoor::LISTEN).
        return [sys.executable, str(self.home / "serve" / "server.py"), "--engine", "strata",
                "--config", str(config), "--host", "127.0.0.1", "--port", str(self.args.port)]

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
        ap.add_argument("--family", choices=["qwen", DeepSeekLaunch.FAMILY], default="qwen",
                        help="qwen: Qwen3.8-Flash-Next on Strata's engine; deepseek41: an IST-DAS DeepSeek-V4.1-Flash set on strata-dsv41")
        ap.add_argument("--mtp", default="", help="the MTP draft layer's GGUF (mtp-q2_0.gguf)")
        ap.add_argument("--engram", default="", help="DeepSeek: the n-gram table every IST-DAS set reads")
        ap.add_argument("--meta", default="", help="DeepSeek: the first part of Unsloth's set, for the Engram's hash parameters")
        ap.add_argument("--dspark", default="", help="DeepSeek: the DSpark drafter")
        ap.add_argument("--mmproj", default="", help="DeepSeek: the picture reader; without it the cell reads text only")
        ap.add_argument("--context", type=int, default=None, help="the window; none: the model's trained one (Qwen), 8192 (DeepSeek)")
        ap.add_argument("--kv", choices=["int8", "q4_0", "k8v4"], default="int8")
        ap.add_argument("--draft-vocab", choices=["cyrillic", "cjk", "en", "fr"], default="cyrillic")
        ap.add_argument("--vram-reserve-mib", type=int, default=0)
        ap.add_argument("--name", default="")
        ap.add_argument("--work", default="", help="where the pack goes (default: CARAVAN_CELL_SCRATCH)")
        return ap


class DeepSeekLaunch(StrataLaunch):
    """One start of an IST-DAS DeepSeek-V4.1-Flash set on Strata's own engine for it, strata-dsv41 (Papyrus
    caravan-big-models-ssd, step 1): the engine fetched from Strata's signed feed when it is not here yet, the pack
    made from the files the scout brought (the set's parts, the Engram, Unsloth's metadata part, the DSpark drafter,
    the picture reader), every card of the machine, Strata's server started in this process's place.

    Each step is the one Strata's setup.py takes in install_dsv41, done with Strata's own tables and functions (its
    pack recipe, its plan of where the experts go, its engine's settings), so a Strata release that changes them
    changes this too. What setup does that a cell does not: download (the caravan brings the files), check SHA-256
    (the library's files are /hf's, checked there), and the 16-word test question (the cell's own first answer is that)."""

    FAMILY = "deepseek41"
    #: What Strata's own setup.py must have for this: v0.2.9's DeepSeek steps.
    NEED = ("MULTI_FILE_FAMILIES", "DSV41_CONTEXT", "DSV41_PROFILES", "dsv41_exe", "get_dsv41_engine", "dsv41_layout_of",
            "dsv41_pack_cmd", "dsv41_pack_info", "dsv41_pack_has_tower", "dsv41_prefill_chunk_args", "dsv41_config_env",
            "gpus", "gpu_problem", "ram_gb")

    def __init__(self, args: argparse.Namespace, env: dict | None = None):
        super().__init__(args, env)
        self.ds = None

    def deepseek(self):
        """Strata's setup.py, refused when it has no DeepSeek steps (a Strata older than 0.2.9)."""
        if self.ds is None:
            strata = self.strata()
            missing = [name for name in self.NEED if not hasattr(strata, name)]
            if missing:
                raise self.Refusal(f"this Strata has no setup.{missing[0]}: DeepSeek needs Strata 0.2.9 or newer")
            self.ds = strata
        return self.ds

    def default_window(self) -> int | None:
        """None: the window Strata's DeepSeek engine was checked at is read from Strata itself, in window()."""
        return None

    def window(self) -> int:
        """The window asked for, else the one Strata's DeepSeek engine was checked at."""
        return self.args.context or self.deepseek().DSV41_CONTEXT

    def the_set(self, first: Path) -> tuple[str, dict]:
        """(the set's name in Strata's table, its row), from its first part's name in either layout."""
        for name, row in self.deepseek().MULTI_FILE_FAMILIES[self.FAMILY]["models"].items():
            firsts = [row["shards"][0], *(row.get("shards6") or [])[:1]]
            if row.get("recipe") == "ista" and first.name in firsts:
                return name, row
        raise self.Refusal(f"Strata does not know {first.name} as the first part of an IST-DAS DeepSeek-V4.1-Flash set")

    def parts(self, first: Path, row: dict) -> list[Path]:
        """The set's own parts, from the folder the scout brought them to: the six-part layout's five, or the four."""
        strata = self.deepseek()
        layout = strata.dsv41_layout_of(row, lambda name: (first.parent / name).is_file())
        parts = [first.parent / name for name in (row["shards6"] if layout == "six" else row["shards"])]
        missing = [part for part in parts if not part.is_file()]
        if missing:
            raise self.Refusal(f"the set's part is not here: {missing[0]}")
        return parts

    def companion(self, raw: str, what: str, needed: bool = True) -> Path | None:
        """A file the set reads beside its parts, as the cell names it; refused when it is needed and not here."""
        if not raw and not needed:
            return None
        path = Path(raw).expanduser()
        if not raw or not path.is_file():
            raise self.Refusal(f"{what} is not here: {raw or '(the cell names none)'}")
        return path

    def dsv41_engine(self) -> tuple[Path, list[str]]:
        """DeepSeek's engine and the folders of its libraries: fetched from Strata's signed feed the first time (Strata's
        get_dsv41_engine: signature and every file checked), as setup does; Strata's Qwen engine is not touched."""
        strata = self.deepseek()
        eng = self.home / "engine"
        exe = strata.dsv41_exe(eng)
        if exe is None:
            print("[strata] DeepSeek's engine (strata-dsv41) is not here: fetching it from Strata's signed feed", flush=True)
            strata.get_dsv41_engine(eng, False, None, None)
            exe = strata.dsv41_exe(eng)
        if exe is None:
            raise self.Refusal("Strata could not install DeepSeek's engine (strata-dsv41) for this machine's cards: "
                               "see docs/DEEPSEEK41.md in Strata, \"Getting the engine by hand\"")
        lib_dirs: list[str] = []
        if Path(exe).parent != eng:
            from strata_control import dsv41_engine
            lib_dirs = list(dsv41_engine.lib_dirs(exe))
        return Path(exe), lib_dirs

    def cards(self) -> list[dict]:
        """Every card Strata can run on, as its setup lists them: DeepSeek takes them all."""
        strata = self.deepseek()
        cards = [card for card in strata.gpus() if strata.gpu_problem(card) is None]
        if not cards:
            raise self.Refusal("Strata finds no card it can run DeepSeek on (nvidia-smi names none, or none it can use)")
        return cards

    def made_by(self, files: list[Path | None], exe: Path) -> dict:
        """What the pack is made of: the files (path, size, time), the engine, and the Strata that makes it."""
        def file(path):
            if path is None:
                return None
            st = path.stat()
            return [str(path), st.st_size, st.st_mtime_ns]
        build = json.loads((self.home / "engine" / "BUILD.json").read_text(encoding="utf-8"))
        return {"family": self.FAMILY, "files": [file(path) for path in files], "engine": file(exe),
                "strata": [build.get("version"), build.get("src")]}

    def pack_whole(self, pack: Path, mmproj: Path | None) -> bool:
        whole = (pack / "tokenizer" / "vocab.json").is_file() and (pack / "tensors.txt").is_file()
        return whole and (mmproj is None or self.deepseek().dsv41_pack_has_tower(pack))

    def ds_pack(self, parts, engram, meta, dspark, mmproj, row, exe, lib_dirs) -> Path:
        """The engine's map of the files, the hash tables, the tokenizer and the chat template, a few MB: Strata's recipe
        for an official set, its shipped profile of the experts used most, and its engine's own check that every file
        the pack names is there."""
        strata = self.deepseek()
        out = self.work / "pack"
        shutil.rmtree(out, ignore_errors=True)
        self.run(strata.dsv41_pack_cmd(parts[0].parent, [part.name for part in parts], engram, meta, dspark, out, mmproj))
        profile = Path(strata.DSV41_PROFILES) / row["profile"]
        if profile.is_file():
            shutil.copyfile(profile, out / "expert-profile.bin")
        good, why = strata.dsv41_pack_info(exe, out, lib_dirs)
        if not good:
            raise self.Refusal(f"the pack in {out} is not complete: {(why or '').strip()[-300:]}")
        return out

    def config(self) -> Path:
        """Everything above, written as Strata's server reads it."""
        strata = self.deepseek()
        first = Path(self.args.model).expanduser()
        name, row = self.the_set(first)
        parts = self.parts(first, row)
        engram = self.companion(self.args.engram, "the Engram (DeepSeek-V4.1-Flash-Engram-IQ4_NL.gguf)")
        meta = self.companion(self.args.meta, "the metadata part of Unsloth's set")
        dspark = self.companion(self.args.dspark, "the DSpark drafter")
        mmproj = self.companion(self.args.mmproj, "the picture reader", needed=False)
        cards = self.cards()
        exe, lib_dirs = self.dsv41_engine()
        self.work.mkdir(parents=True, exist_ok=True)
        made = self.made_by([*parts, engram, meta, dspark, mmproj], exe)
        pack = self.work / "pack"
        if self.reused(made) and self.pack_whole(pack, mmproj):
            print("[strata] the pack of the last start is this set's: kept", flush=True)
        else:
            (self.work / self.MADE).unlink(missing_ok=True)
            pack = self.ds_pack(parts, engram, meta, dspark, mmproj, row, exe, lib_dirs)
            (self.work / self.MADE).write_text(json.dumps(made, indent=1), encoding="utf-8")
        from strata_control import dsv41_context, dsv41_fit
        window = self.window()
        problem = dsv41_context.problem(window, dsv41_context.read_limit(pack))
        if problem:
            raise self.Refusal(problem)
        plan = dsv41_fit.plan([{**card, "vram_gb": float(card.get("vram_gb") or 0)} for card in cards], strata.ram_gb(),
                              None, window, model=name, named=True)
        family = strata.MULTI_FILE_FAMILIES[self.FAMILY]
        args = ["--pack", str(pack), "--max-context", str(window), "--eos", "1", "--vision", "on" if mmproj else "off",
                "--dspark", "auto", "--dspark-conf", "0.65", *strata.dsv41_prefill_chunk_args(cards, strata.ram_gb()),
                *plan["args"]]
        # No `drafting` key here: this start's drafter is the DSpark, not the drafter that key chooses.
        # strata_control/drafting.py leaves a model it was not made for with its own flags (DeepSeek is not
        # one of its families), so a choice written here would say something about a drafter this start
        # does not use.
        cfg = {"exe": str(exe), "args": args, "cwd": str(self.home), "tokenizer": str(pack / "tokenizer"),
               "model_name": self.args.name or family["name"], "arch": family["arch"], "log": str(self.work / "engine.log"),
               "lib_dirs": lib_dirs, "port": self.args.port, "engine_ready_s": 3600}
        env = strata.dsv41_config_env(cards)
        if env:
            cfg["env"] = env
        numbers = [card["index"] for card in cards]
        cfg["gpu"] = numbers if len(numbers) > 1 else numbers[0]
        if len(numbers) > 1:
            cfg["gpus_asked"] = True
        path = self.work / "strata.json"
        path.write_text(json.dumps(cfg, indent=1), encoding="utf-8")
        for line in plan.get("lines") or []:
            print(f"[strata] {line}", flush=True)
        print(f"[strata] {name} (DeepSeek-V4.1-Flash), context {window}, cards {numbers}, "
              f"pictures {'on' if mmproj else 'off'}: {path}", flush=True)
        return path

    def reused(self, made: dict) -> bool:
        """The last start made its pack from the same files with the same engine."""
        try:
            return json.loads((self.work / self.MADE).read_text(encoding="utf-8")) == made
        except (OSError, ValueError):
            return False


def main(argv: list[str] | None = None) -> int:
    """Why a function: the entry point the launcher runs — it only parses and
    hands over to the family's start."""
    args = StrataLaunch.parser().parse_args(argv)
    if args.context is not None and args.context <= 0:
        print("strata: --context must be a positive number of tokens", file=sys.stderr)
        return 2
    start = DeepSeekLaunch if args.family == DeepSeekLaunch.FAMILY else StrataLaunch
    try:
        start(args).start()
    except StrataLaunch.Refusal as exc:
        print(f"strata: {exc}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
