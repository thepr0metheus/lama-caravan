"""The stand's model library: GGUF files with real headers and no weights.

A file is its header and then a hole: it says it weighs 40 GB and takes a few KB of the disk. The caravan reads the header
for what it reads of a real model (layers, the trained window, the KV heads) and the size for what a model weighs, and no
file is ever read past its header here: the stand's scout reads the library in place, it copies nothing.
"""
import json
import struct
from pathlib import Path


class GgufWriter:
    MAGIC = b"GGUF"
    VERSION = 3
    UINT32, STRING = 4, 8

    @staticmethod
    def text(value) -> bytes:
        raw = str(value).encode()
        return struct.pack("<Q", len(raw)) + raw

    @classmethod
    def pair(cls, key, value) -> bytes:
        if isinstance(value, int):
            return cls.text(key) + struct.pack("<II", cls.UINT32, value)
        return cls.text(key) + struct.pack("<I", cls.STRING) + cls.text(value)

    @classmethod
    def header(cls, facts) -> bytes:
        out = cls.MAGIC + struct.pack("<IQQ", cls.VERSION, 0, len(facts))
        return out + b"".join(cls.pair(key, value) for key, value in facts.items())


class StandModels:
    GIB = 1024 ** 3
    #: More than this on the disk and a file is no hole: the library's 174 GiB would be real on a laptop with 20 free.
    HOLE_CEILING_BYTES = 1024 * 1024
    #: file name, architecture, layers, trained window, embedding, GiB
    LIBRARY = (
        ("stand-small-8B-Q4_K_M.gguf", "llama", 33, 32768, 3072, 5),
        ("stand-chat-27B-Q4_K_M.gguf", "llama", 49, 131072, 3840, 17),
        ("stand-coder-70B-Q3_K_M.gguf", "llama", 81, 262144, 5120, 36),
        ("stand-huge-120B-Q4_K_M.gguf", "llama", 97, 262144, 6144, 70),
    )

    def __init__(self, folder):
        self.folder = Path(folder)

    @classmethod
    def facts(cls, name, arch, layers, window, embedding):
        return {
            "general.architecture": arch,
            "general.name": Path(name).stem,
            f"{arch}.block_count": layers,
            f"{arch}.context_length": window,
            f"{arch}.embedding_length": embedding,
            f"{arch}.attention.head_count": 16,
            f"{arch}.attention.head_count_kv": 8,
        }

    #: A checkpoint for vLLM: a folder of a config and weights that are a hole. Folder name, GiB.
    CHECKPOINTS = (("stand-vllm-small-8B", 6), ("stand-vllm-big-70B", 40))

    def checkpoints(self):
        for name, gib in self.CHECKPOINTS:
            folder = self.folder / name
            weights = folder / "model.safetensors"
            if weights.exists():
                continue
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "config.json").write_text(json.dumps({"architectures": ["LlamaForCausalLM"], "model_type": "llama", "max_position_embeddings": 131072}), encoding="utf-8")
            with weights.open("wb") as fh:
                fh.truncate(gib * self.GIB)
            self.refuse_unless_hole(weights)

    def write(self):
        """Writes what is not there yet; a file that is there is kept (its mtime is what a header is remembered by)."""
        self.folder.mkdir(parents=True, exist_ok=True)
        self.checkpoints()
        for name, arch, layers, window, embedding, gib in self.LIBRARY:
            path = self.folder / name
            if path.exists():
                continue
            path.write_bytes(GgufWriter.header(self.facts(name, arch, layers, window, embedding)))
            with path.open("r+b") as fh:
                fh.truncate(gib * self.GIB)
            self.refuse_unless_hole(path)

    @classmethod
    def refuse_unless_hole(cls, path, on_disk=None):
        """A file system without holes writes the zeros out. The file goes at once and the stand does not start."""
        taken = on_disk if on_disk is not None else path.stat().st_blocks * 512
        if taken > cls.HOLE_CEILING_BYTES:
            path.unlink()
            raise SystemExit(f"{path.name} took {taken:,} bytes of the disk, it was to be a hole: this file system "
                             f"writes the zeros out, and the stand's library would fill the disk. Not started.")
