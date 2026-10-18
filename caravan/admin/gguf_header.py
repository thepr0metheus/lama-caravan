"""What a GGUF file's header says: the few facts the controller wants out of its key-value block.

A header is a list of key-value pairs, and most of its bytes are three of them: the tokenizer's tokens and
merges (a hundred thousand strings and more, each a length and its bytes) and its scores and token types
(as many numbers). The controller wants ten facts (the architecture, the trained window, the layer count, the
head counts, the pooling, a speech model's variant and languages); everything else is passed over.

Passed over, not read: until 1.3.544 every item of every array was unpacked one by one, in Python, and a library
of 56 models took 51 s on the NAS to read — once per start of the container, and the board's first page waited
for it (the owner's red "did not finish loading", 2026-10-14). A number array is now jumped over by its length, a
string array by the lengths in front of its strings, in a loop that reads nothing else. What it says is the
same: scripts/test_gguf_header.py holds this reader to the old one, file by file.

The file is read from its start in blocks, never mapped: a mapped file that is cut short while it is read kills
the process that reads it (SIGBUS), and a download or a move may do exactly that to a file under the models folder.
"""
from struct import Struct, error as StructError


class GgufHeader:
    #: The value types of GGUF that are one fixed number of bytes: the format's letter for each.
    NUMBERS = {0: "B", 1: "b", 2: "H", 3: "h", 4: "I", 5: "i", 6: "f", 7: "?", 10: "Q", 11: "q", 12: "d"}
    STRING, ARRAY = 8, 9
    #: What is read of the key-value block: whole keys, and the ends of keys that every architecture writes
    #: under its own name (`llama.context_length`, `qwen3.context_length`).
    #: `stt.variant` is what makes a speech GGUF self-identifying. The architecture name alone cannot:
    #: transcribe.cpp has arches called granite, cohere and moss, and so does llama.cpp — a Granite CHAT model
    #: and a Granite SPEECH model both say "granite". Every speech GGUF the engine reads carries the stt.*
    #: namespace (stt.variant, stt.frontend.*); no chat model does. `general.languages` then says which
    #: languages it was trained for, which is the thing an operator actually needs when picking one.
    WANTED = frozenset({"general.architecture", "stt.variant", "general.languages"})
    SUFFIXES = (
        "block_count",
        # Speculative sidecars carry <arch>.block_size — the number of tokens a
        # block-diffusion drafter denoises per pass, and therefore the draft
        # depth worth asking for. Without it here the key is filtered out
        # before extract_runtime_meta ever sees it.
        "block_size",
        "context_length",
        "embedding_length",
        "attention.head_count",
        "attention.head_count_kv",
        "attention.key_length",
        "attention.value_length",
        "pooling_type",
    )
    #: How many items of an array are kept; the rest are passed over.
    KEPT = 32
    #: How much of the file is read at a time. A header is a few megabytes; the reads are as few as that asks.
    BLOCK = 4 << 20
    #: No header is this long (the longest of the 56 models of the NAS: see test_gguf_header.py). A length a
    #: corrupt file claims — a string of 2**62 bytes — is refused here instead of read to the end of the file.
    LIMIT = 256 << 20
    LENGTH = Struct("<Q")
    KIND = Struct("<I")

    def __init__(self, handle):
        self.handle = handle
        # Only ever extended, never replaced: skip_strings holds it by name while the file is read on.
        self.buf = bytearray()
        self.formats = {code: Struct("<" + letter) for code, letter in self.NUMBERS.items()}

    @classmethod
    def read(cls, path, limit_keys=256):
        """The wanted facts of the file's header: `{}` for a file that is no GGUF, is too old, or ends before the
        header does. A half-read header says nothing rather than half of it."""
        try:
            with path.open("rb") as handle:
                return cls(handle).facts(limit_keys)
        except Exception:
            return {}

    @classmethod
    def wanted(cls, key):
        return key in cls.WANTED or key.endswith(cls.SUFFIXES)

    # ── the block, read as far as it is asked ───────────────────────────────────────────────────────────

    def ensure(self, end):
        """The bytes up to `end` are in the buffer, or the file ends first (EOFError) or `end` is no header's (ValueError)."""
        if end > self.LIMIT:
            raise ValueError("a header this long is no header")
        while len(self.buf) < end:
            chunk = self.handle.read(max(end - len(self.buf), self.BLOCK))
            if not chunk:
                raise EOFError("the header ends before it should")
            self.buf += chunk

    def number(self, code, pos):
        form = self.formats[code]
        self.ensure(pos + form.size)
        return form.unpack_from(self.buf, pos)[0]

    def length_at(self, pos):
        self.ensure(pos + 8)
        return self.LENGTH.unpack_from(self.buf, pos)[0]

    def string_at(self, pos):
        """The string whose length stands at `pos`, and where it ends."""
        end = pos + 8 + self.length_at(pos)
        self.ensure(end)
        return self.buf[pos + 8:end].decode("utf-8", errors="replace"), end

    def value_at(self, code, pos):
        """The value of this type at `pos`, and where it ends. An array gives its first KEPT items; the rest are passed over."""
        if code == self.STRING:
            return self.string_at(pos)
        if code == self.ARRAY:
            item = self.KIND.unpack_from(self.take(pos, 4))[0]
            length = self.LENGTH.unpack_from(self.take(pos + 4, 8))[0]
            pos += 12
            values = []
            for _ in range(min(length, self.KEPT)):
                value, pos = self.value_at(item, pos)
                values.append(value)
            return values, self.skip_items(item, pos, length - len(values))
        if code in self.formats:
            return self.number(code, pos), pos + self.formats[code].size
        return None, pos

    def take(self, pos, size):
        self.ensure(pos + size)
        return self.buf[pos:pos + size]

    def skip_at(self, code, pos):
        """Where the value of this type at `pos` ends, read as little as the format lets."""
        if code == self.STRING:
            return pos + 8 + self.length_at(pos)
        if code == self.ARRAY:
            item = self.KIND.unpack_from(self.take(pos, 4))[0]
            length = self.LENGTH.unpack_from(self.take(pos + 4, 8))[0]
            return self.skip_items(item, pos + 12, length)
        if code in self.formats:
            return pos + self.formats[code].size
        return pos

    def skip_items(self, item, pos, count):
        """Where `count` items of this type, one after another from `pos`, end."""
        if count <= 0:
            return pos
        if item in self.formats:
            return pos + count * self.formats[item].size
        if item == self.STRING:
            return self.skip_strings(pos, count)
        if item == self.ARRAY:
            for _ in range(count):
                pos = self.skip_at(item, pos)
            return pos
        # A type this reader does not know takes no bytes, as the old reader read it: `count` of them are nothing.
        return pos

    def skip_strings(self, pos, count):
        """Where `count` strings, each a length and its bytes, end. The lengths are all that is looked at, in a loop of
        one line: a tokenizer is a hundred thousand strings and more. When the buffer ends in the middle of it the file
        is read on and the loop goes on where it stopped."""
        unpack = self.LENGTH.unpack_from
        buf = self.buf
        while count:
            try:
                while count:
                    pos += 8 + unpack(buf, pos)[0]
                    count -= 1
            except StructError:
                self.ensure(pos + 8)
        return pos

    # ── the facts ───────────────────────────────────────────────────────────────────────────────────────

    def facts(self, limit_keys):
        self.buf += self.handle.read(24)
        if self.buf[:4] != b"GGUF" or len(self.buf) < 24:
            return {}
        if self.KIND.unpack_from(self.buf, 4)[0] < 2:
            return {}
        pairs = self.LENGTH.unpack_from(self.buf, 16)[0]
        meta, pos = {}, 24
        for _ in range(min(pairs, limit_keys)):
            key, pos = self.string_at(pos)
            code = self.KIND.unpack_from(self.take(pos, 4))[0]
            pos += 4
            if self.wanted(key):
                meta[key], pos = self.value_at(code, pos)
            else:
                pos = self.skip_at(code, pos)
        # What was passed over has to be in the file: a header cut short says nothing, whatever it said so far.
        self.ensure(pos)
        return meta
