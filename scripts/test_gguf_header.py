#!/usr/bin/env python3
"""Value snapshot: the GGUF header reader, held to the one it replaced.

Until 1.3.544 `read_gguf_metadata` unpacked every item of every array of a header — the tokenizer's hundred
thousand tokens and merges among them — one by one, and the first /api/state after a start of the container
waited 51 s for the 56 models of the NAS. caravan/admin/gguf_header.py (`GgufHeader`) passes the arrays over by
their lengths. What it SAYS has to stay what the old reader said, so the old reader stands here, verbatim, as the
oracle (`old_read_gguf_metadata`: the function as it was in 1.3.543, with its type table), and every file of the
corpus is read by both: a plain model, a tokenizer before and after the facts, every value type alone and in
arrays, arrays of arrays, empty arrays, strings that are no UTF-8, more keys than the limit, the same key twice,
a value of a kind nobody knows, files too short to be a header, a version-1 file, and 300 files of random shape
(a fixed seed). Each file is read again with a block of 1, 3, 7, 64 and 4096 bytes, so every kind of value has its
edge at a refill of the buffer.

Where the new reader differs ON PURPOSE it is pinned as it is: a header cut short says `{}` (the old reader said
the facts it had got, the last of them half a string); a length that no header has (a string of 2**62 bytes) is
refused at a ceiling instead of read to the end of the file; and a header is passed over, not read — counted by the
calls of the reader of single items, which a tokenizer of 40000 tokens must not make.

Run: python3 scripts/test_gguf_header.py
"""
import random
import struct
import sys
import tempfile
import time
from io import BytesIO
from pathlib import Path
from struct import calcsize, unpack

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from caravan.admin.gguf_header import GgufHeader  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


# ── the oracle: the reader as it was until 1.3.543, verbatim ─────────────────────────────────────────────────

GGUF_VALUE_TYPES = {
    0: "B",
    1: "b",
    2: "H",
    3: "h",
    4: "I",
    5: "i",
    6: "f",
    7: "?",
    10: "Q",
    11: "q",
    12: "d",
}


def old_read_gguf_metadata(path, limit_keys=256):
    wanted_suffixes = (
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
    # `stt.variant` is what makes a speech GGUF self-identifying. The
    # architecture name alone cannot: transcribe.cpp has arches called granite,
    # cohere and moss, and so does llama.cpp — a Granite CHAT model and a
    # Granite SPEECH model both say "granite". Every speech GGUF the engine
    # reads carries the stt.* namespace (stt.variant, stt.frontend.*); no chat
    # model does. general.languages then says which languages it was trained
    # for, which is the thing an operator actually needs when picking one.
    wanted = {"general.architecture", "stt.variant", "general.languages"}
    meta = {}
    try:
        with path.open("rb") as handle:
            if handle.read(4) != b"GGUF":
                return meta
            version = unpack("<I", handle.read(4))[0]
            if version < 2:
                return meta
            _tensor_count = unpack("<Q", handle.read(8))[0]
            kv_count = unpack("<Q", handle.read(8))[0]

            def read_string():
                length = unpack("<Q", handle.read(8))[0]
                return handle.read(length).decode("utf-8", errors="replace")

            def read_value(value_type):
                if value_type == 8:
                    return read_string()
                if value_type == 9:
                    item_type = unpack("<I", handle.read(4))[0]
                    length = unpack("<Q", handle.read(8))[0]
                    values = [read_value(item_type) for _ in range(min(length, 32))]
                    for _ in range(max(0, length - 32)):
                        read_value(item_type)
                    return values
                fmt = GGUF_VALUE_TYPES.get(value_type)
                if not fmt:
                    return None
                return unpack("<" + fmt, handle.read(calcsize("<" + fmt)))[0]

            for _ in range(min(kv_count, limit_keys)):
                key = read_string()
                value_type = unpack("<I", handle.read(4))[0]
                value = read_value(value_type)
                if key in wanted or key.endswith(wanted_suffixes):
                    meta[key] = value
            return meta
    except Exception:
        return {}


# ── a GGUF header, built by the format's own rules (not by the reader's table) ───────────────────────────────

LETTERS = {0: "B", 1: "b", 2: "H", 3: "h", 4: "I", 5: "i", 6: "f", 7: "?", 10: "Q", 11: "q", 12: "d"}
SAMPLES = {0: 200, 1: -5, 2: 65535, 3: -300, 4: 4000000000, 5: -70000, 6: 1.5, 7: True, 10: 2 ** 63, 11: -2 ** 40,
           12: 2.5e300}


def text(value):
    """A GGUF string: its length, then its bytes."""
    raw = value if isinstance(value, bytes) else value.encode("utf-8")
    return struct.pack("<Q", len(raw)) + raw


def payload(kind, value):
    """The bytes of one value of this kind. An array is (item kind, [items]); a kind nobody knows has no bytes."""
    if kind == 8:
        return text(value)
    if kind == 9:
        item, items = value
        return struct.pack("<I", item) + struct.pack("<Q", len(items)) + b"".join(payload(item, v) for v in items)
    if kind in LETTERS:
        return struct.pack("<" + LETTERS[kind], value)
    return value if isinstance(value, bytes) else b""


def pair(key, kind, value):
    return text(key) + struct.pack("<I", kind) + payload(kind, value)


def gguf(pairs, version=3, count=None, tail=b"", magic=b"GGUF"):
    count = len(pairs) if count is None else count
    return magic + struct.pack("<I", version) + struct.pack("<Q", 0) + struct.pack("<Q", count) + b"".join(pairs) + tail


def tokenizer(count):
    return [
        pair("tokenizer.ggml.model", 8, "gpt2"),
        pair("tokenizer.ggml.tokens", 9, (8, ["tok%d" % i * (1 + i % 3) for i in range(count)])),
        pair("tokenizer.ggml.scores", 9, (6, [i / 7.0 for i in range(count)])),
        pair("tokenizer.ggml.token_type", 9, (5, [i % 4 for i in range(count)])),
        pair("tokenizer.ggml.merges", 9, (8, ["a%d b%d" % (i, i) for i in range(count // 2)])),
        pair("tokenizer.ggml.bos_token_id", 4, 1),
    ]


FACTS = [
    pair("general.architecture", 8, "llama"),
    pair("llama.context_length", 4, 4096),
    pair("llama.block_count", 4, 32),
    pair("llama.embedding_length", 4, 4096),
    pair("llama.attention.head_count", 4, 32),
    pair("llama.attention.head_count_kv", 4, 8),
    pair("llama.attention.key_length", 4, 128),
    pair("llama.attention.value_length", 4, 128),
    pair("llama.pooling_type", 4, 1),
    pair("general.languages", 9, (8, ["en", "ru"])),
    pair("stt.variant", 8, "small"),
    pair("draft.block_size", 4, 4),
]
FACTS_SAID = {
    "general.architecture": "llama", "llama.context_length": 4096, "llama.block_count": 32,
    "llama.embedding_length": 4096, "llama.attention.head_count": 32, "llama.attention.head_count_kv": 8,
    "llama.attention.key_length": 128, "llama.attention.value_length": 128, "llama.pooling_type": 1,
    "general.languages": ["en", "ru"], "stt.variant": "small", "draft.block_size": 4,
}


def random_value(rng, kind, depth):
    """A random value of this kind, in the shape `payload` takes it."""
    if kind == 8:
        return bytes(rng.randrange(256) for _ in range(rng.choice([0, 1, 3, 12, 40])))
    if kind == 9:
        item = rng.choice([8, 8, 9, 4, 6, 7, 10, 0, 13] if depth < 2 else [8, 4, 6, 13])
        count = rng.choice([0, 1, 2, 5, 31, 32, 33, 40])
        return item, [random_value(rng, item, depth + 1) for _ in range(count)]
    if kind == 7:
        return rng.choice([True, False])
    if kind in (6, 12):
        return rng.choice([0.0, 1.5, -2.25, 1e10, 3.125])
    if kind in LETTERS:
        bits = struct.calcsize("<" + LETTERS[kind]) * 8
        low, high = (0, 2 ** bits - 1) if LETTERS[kind].isupper() else (-2 ** (bits - 1), 2 ** (bits - 1) - 1)
        return rng.choice([low, high, 0, rng.randrange(low, high + 1)])
    return b""


def random_file(rng):
    keys = ["general.architecture", "x.context_length", "y.block_count", "z.attention.head_count", "general.name",
            "tokenizer.ggml.tokens", "w.pooling_type", "stt.variant", "general.languages", "other.key",
            "foo.attention.value_length", "bar.block_size", "tokenizer.ggml.merges", "q.embedding_length"]
    pairs = []
    for index in range(rng.randrange(1, 41)):
        key = rng.choice(keys) if rng.random() < 0.8 else "k%d" % index
        kind = rng.choice([8, 9, 9, 0, 1, 2, 3, 4, 5, 6, 7, 10, 11, 12, 13])
        pairs.append(pair(key, kind, random_value(rng, kind, 0)))
    return gguf(pairs, version=rng.choice([2, 3, 3, 3]), tail=bytes(rng.randrange(256) for _ in range(rng.choice([0, 30]))))


def corpus():
    """(name, bytes, limit of keys) — every file the old and the new reader both have to say the same of."""
    files = []

    def add(name, blob, limit=256):
        files.append((name, blob, limit))

    add("model", gguf([pair("general.name", 8, "Demo 7B")] + FACTS + tokenizer(3000)
                      + [pair("general.quantization_version", 4, 2)], tail=b"tensor info and data" * 20))
    add("tokenizer-first", gguf(tokenizer(3000) + FACTS))
    add("tokenizer-between", gguf(FACTS[:6] + tokenizer(500) + FACTS[6:] + tokenizer(70)))
    numbers = []
    for kind, value in SAMPLES.items():
        numbers += [
            pair("t%d.context_length" % kind, kind, value),
            pair("u%d.size" % kind, kind, value),
            pair("t%d.attention.head_count" % kind, 9, (kind, [value] * 5)),
            pair("u%d.list" % kind, 9, (kind, [value] * 40)),
            pair("t%d.block_count" % kind, 9, (kind, [value] * 100)),
            pair("u%d.empty" % kind, 9, (kind, [])),
            pair("t%d.pooling_type" % kind, 9, (kind, [])),
        ]
    add("every-number-type", gguf(numbers))
    for count in (0, 1, 31, 32, 33, 40, 200):
        add("languages-%d" % count, gguf([pair("general.architecture", 8, "whisper"),
                                          pair("general.languages", 9, (8, ["l%d" % i for i in range(count)]))]))
    ints = (9, [(4, list(range(i % 5))) for i in range(40)])
    strings = (9, [(8, ["s%d" % j for j in range(i % 4)]) for i in range(35)])
    add("arrays-of-arrays", gguf([pair("n1.context_length", 9, ints), pair("n2.list", 9, ints),
                                  pair("n3.block_count", 9, strings), pair("n4.list", 9, strings),
                                  pair("n5.pooling_type", 9, (9, [(9, [(4, [1, 2]), (4, [])]), (9, [])])),
                                  pair("n6.list", 9, (9, [(9, [(8, ["a", "bc"])])])),
                                  pair("general.architecture", 8, "x")]))
    add("not-utf8", gguf([pair("general.architecture", 8, b"ll\xff\xfeama"), pair("u.name", 8, b"\xc3\x28 broken"),
                          pair("general.languages", 9, (8, [b"\xe2\x82", "ok", b"\xf0\x9f\x98"])),
                          pair("w.context_length", 4, 7)]))
    many = []
    for index in range(300):
        many.append(pair({100: "w1.context_length", 255: "w2.context_length", 256: "w3.context_length"}.get(
            index, "k%d" % index), 4, index))
    for limit in (1, 5, 100, 101, 256, 1000):
        add("many-keys-limit-%d" % limit, gguf(many), limit)
    add("count-over-the-pairs", gguf(FACTS, count=500))
    add("same-key-twice", gguf([pair("general.architecture", 8, "llama"), pair("x.block_count", 4, 1),
                                pair("general.architecture", 8, "qwen"), pair("x.block_count", 4, 2)]))
    add("version-2", gguf(FACTS, version=2))
    add("version-1", gguf(FACTS, version=1))
    add("version-4", gguf(FACTS, version=4))
    add("no-pairs", gguf([]))
    add("not-gguf", b"NOPE" + bytes(100))
    add("magic-differs-in-the-last-byte", gguf(FACTS, magic=b"GGUX"))
    add("magic-only", b"GGUF")
    add("empty", b"")
    add("three-bytes", b"GGU")
    add("magic-and-version", b"GGUF" + struct.pack("<I", 3))
    add("sixteen-bytes", b"GGUF" + struct.pack("<I", 3) + bytes(8))
    add("kind-nobody-knows", gguf([pair("general.architecture", 8, "llama"), pair("odd.value", 13, b""),
                                   pair("odd.context_length", 13, b""), pair("llama.block_count", 4, 12)]))
    add("array-of-kind-nobody-knows", gguf([pair("big.list", 9, (13, [None] * 200000)),
                                            pair("big.block_count", 9, (13, [None] * 50)),
                                            pair("general.architecture", 8, "llama")]))
    rng = random.Random(20261014)
    for index in range(300):
        add("random-%03d" % index, random_file(rng))
    return files


# ── how two answers are compared: True is not 1 ──────────────────────────────────────────────────────────────

def strict(value):
    if isinstance(value, dict):
        return [(key, strict(item)) for key, item in value.items()]
    if isinstance(value, list):
        return [strict(item) for item in value]
    return (type(value).__name__, value)


def read_new(path, limit, block):
    keep = GgufHeader.BLOCK
    GgufHeader.BLOCK = block
    try:
        return GgufHeader.read(path, limit)
    finally:
        GgufHeader.BLOCK = keep


class Endless:
    """A file that has its header and then zeros without end, and counts what is read of it."""

    def __init__(self, head):
        self.head = BytesIO(head)
        self.taken = 0

    def read(self, size):
        data = self.head.read(size)
        data += bytes(size - len(data))
        self.taken += len(data)
        if self.taken > 64 << 20:
            raise RuntimeError("read without end")
        return data


class Counting(GgufHeader):
    """The reader that counts the calls of the readers of single values."""
    calls = 0

    def string_at(self, pos):
        Counting.calls += 1
        return super().string_at(pos)

    def value_at(self, code, pos):
        Counting.calls += 1
        return super().value_at(code, pos)


def main():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        path = tmp / "m.gguf"
        blocks = (1, 3, 7, 64, 4096, GgufHeader.BLOCK)

        print("-- what the file says: the same as the old reader, at every size of block")
        files = corpus()
        differ, said, told = [], 0, 0
        for name, blob, limit in files:
            path.write_bytes(blob)
            old = old_read_gguf_metadata(path, limit)
            said += bool(old)
            told += any(isinstance(v, list) for v in old.values())
            for block in blocks:
                new = read_new(path, limit, block)
                if strict(new) != strict(old):
                    differ.append("%s (block %d)" % (name, block))
        check(len(files) == 334, "the corpus holds %d files" % len(files))
        check(not differ, "%d files x %d blocks read as the old reader read them%s" % (
            len(files), len(blocks), "" if not differ else ": " + ", ".join(differ[:6])))
        check(said >= 250 and told >= 40, "…and the corpus is no empty one: %d files say something, %d of them an array" % (said, told))

        print("-- pins by value, not by the old reader")
        path.write_bytes(gguf([pair("general.name", 8, "Demo 7B")] + FACTS + tokenizer(3000), tail=b"x" * 50))
        check(strict(GgufHeader.read(path)) == strict(FACTS_SAID), "a model: its twelve facts and nothing of its tokenizer")
        path.write_bytes(gguf([pair("t%d.context_length" % k, k, v) for k, v in SAMPLES.items()]))
        said_numbers = GgufHeader.read(path)
        check(said_numbers == {"t%d.context_length" % k: v for k, v in SAMPLES.items()}
              and type(said_numbers["t7.context_length"]) is bool and type(said_numbers["t6.context_length"]) is float,
              "each number type comes as its own type: a '?' is a bool, an 'f' a float")
        path.write_bytes(gguf([pair("general.languages", 9, (8, ["l%d" % i for i in range(40)]))]))
        check(GgufHeader.read(path)["general.languages"] == ["l%d" % i for i in range(32)],
              "an array keeps its first 32 items")
        path.write_bytes(gguf([pair("k%d" % i, 4, i) for i in range(300)] + [pair("w.block_count", 4, 9)]))
        check(GgufHeader.read(path) == {} and GgufHeader.read(path, 400) == {"w.block_count": 9},
              "only the first 256 keys are looked at, or as many as the call says")
        path.write_bytes(gguf(FACTS, version=1))
        check(GgufHeader.read(path) == {}, "a file of version 1 says nothing")
        check(GgufHeader.read(tmp / "missing.gguf") == {}, "a file that is not there says nothing")

        print("-- a header is passed over, not read")
        said_calls = {}
        for count in (2000, 40000):
            path.write_bytes(gguf(FACTS + tokenizer(count)))
            Counting.calls = 0
            Counting.read(path)
            said_calls[count] = Counting.calls
        check(said_calls[2000] == said_calls[40000] and said_calls[40000] <= 60,
              "single values read: %d for a tokenizer of 2000 tokens, %d for 40000 — the tokenizer costs none" % (
                  said_calls[2000], said_calls[40000]))

        print("-- a header cut short says nothing")
        last = pair("general.description", 8, "a description that is cut in the middle by the cut")
        whole = gguf(FACTS + tokenizer(40) + [last])
        blob = whole + b"tensor info and data" * 4
        start_of_last = len(whole) - len(last)
        wrong, said_half, early = [], [], []
        for cut in range(len(blob)):
            path.write_bytes(blob[:cut])
            new = GgufHeader.read(path)
            if (new == {}) != (cut < len(whole)):
                wrong.append(cut)
            if cut < len(whole) and old_read_gguf_metadata(path):
                said_half.append(cut)
                early.append(cut < start_of_last)
        check(not wrong and GgufHeader.read(path) == FACTS_SAID,
              "cut at each of %d places: {} while the keys looked at are cut, the facts once they are whole%s" % (
                  len(blob), "" if not wrong else " — wrong at " + str(wrong[:8])))
        check(said_half and not any(early),
              "the old reader said half a header only when the cut fell inside the last value (%d places)" % len(said_half))

        print("-- a length no header has is refused at a ceiling")
        keep_limit, keep_block = GgufHeader.LIMIT, GgufHeader.BLOCK
        GgufHeader.LIMIT, GgufHeader.BLOCK = 1 << 20, 4096
        try:
            cases = {
                "a key of 2**62 bytes": b"GGUF" + struct.pack("<IQQ", 3, 0, 1) + struct.pack("<Q", 2 ** 62),
                "an array of 2**40 numbers": gguf([pair("x.list", 9, (4, []))])[:-8] + struct.pack("<Q", 2 ** 40),
                "a string of 2**62 bytes": gguf([pair("x.value", 8, "")])[:-8] + struct.pack("<Q", 2 ** 62),
                "2**60 strings that are empty": gguf([pair("x.list", 9, (8, []))])[:-8] + struct.pack("<Q", 2 ** 60),
                "2**60 arrays that are empty": gguf([pair("x.list", 9, (9, []))])[:-8] + struct.pack("<Q", 2 ** 60),
            }
            for what, head in cases.items():
                handle = Endless(head)
                began = time.monotonic()
                try:
                    GgufHeader(handle).facts(256)
                    outcome = "no refusal"
                except Exception as exc:
                    outcome = type(exc).__name__
                took = time.monotonic() - began
                check(outcome == "ValueError" and handle.taken <= GgufHeader.LIMIT + GgufHeader.BLOCK and took < 20,
                      "%s: %s after %d bytes read, %.1f s" % (what, outcome, handle.taken, took))
            handle = Endless(gguf([pair("x.list", 9, (13, []))])[:-8] + struct.pack("<Q", 2 ** 62))
            check(GgufHeader(handle).facts(256) == {} and handle.taken <= 2 * GgufHeader.BLOCK,
                  "2**62 items of a kind nobody knows are nothing, and are not counted one by one")
        finally:
            GgufHeader.LIMIT, GgufHeader.BLOCK = keep_limit, keep_block

        print("-- wired into models.py")
        from caravan.admin import models  # noqa: E402
        path.write_bytes(gguf([pair("general.name", 8, "x")] + FACTS + tokenizer(50)))
        check(strict(models.read_gguf_metadata(path)) == strict(FACTS_SAID)
              and models.read_gguf_metadata(path, 3) == {"general.architecture": "llama", "llama.context_length": 4096}
              and strict(models.read_gguf_metadata(path, limit_keys=13)) == strict(FACTS_SAID),
              "read_gguf_metadata is this reader, limit_keys and all")

    print()
    if _fail:
        print(f"gguf header FAILED ({len(_fail)}):")
        for m in _fail:
            print("  - " + m.splitlines()[0])
        return 1
    print("gguf header OK: the old reader's answers at every block, a cut header says nothing, lengths have a ceiling")
    return 0


if __name__ == "__main__":
    sys.exit(main())
