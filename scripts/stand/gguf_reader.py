"""What a stand-in reads of a GGUF: the fake engine answers by a model's header, as llama.cpp does. A reader of its own: the program's is the program's, and the
stand's engine is held to the same headers by what the board then shows.
"""
import struct
from pathlib import Path


class GgufHeader:
    """A header's keys and values, as far as `limit` lets a list go: the engine asks for numbers and words, and no fake needs a whole vocabulary."""

    SCALARS = {0: "<B", 1: "<b", 2: "<H", 3: "<h", 4: "<I", 5: "<i", 6: "<f", 7: "<?", 10: "<Q", 11: "<q", 12: "<d"}
    TEXT = 8
    LIST = 9

    def __init__(self, handle):
        self.handle = handle

    @classmethod
    def read(cls, path: Path, limit=256):
        """The keys of the file; {} for what is no GGUF."""
        with open(path, "rb") as handle:
            reader = cls(handle)
            if handle.read(4) != b"GGUF":
                return {}
            reader.number("<I")
            reader.number("<Q")
            count = reader.number("<Q")
            out = {}
            for _ in range(count):
                key = reader.text()
                kind = reader.number("<I")
                out[key] = reader.value(kind, limit)
            return out

    def number(self, form):
        return struct.unpack(form, self.handle.read(struct.calcsize(form)))[0]

    def text(self):
        return self.handle.read(self.number("<Q")).decode("utf-8", "replace")

    def value(self, kind, limit):
        if kind == self.TEXT:
            return self.text()
        if kind == self.LIST:
            item, size = self.number("<I"), self.number("<Q")
            values = [self.value(item, limit) for _ in range(size)]
            return values if size <= limit else None
        return self.number(self.SCALARS[kind])
