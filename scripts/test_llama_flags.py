#!/usr/bin/env python3
"""Snapshot of the llama-server flags the config panel gained in 1.3.327.

Nineteen flags the binary always accepted were reachable only by typing them
into EXTRA_ARGS. Surfacing one means four things have to agree: the field
exists, the builder emits the flag, an operator who already typed it into
EXTRA_ARGS gets it hoisted into the new field instead, and the flag stays
ABSENT when the field is empty. The last one is the half that rots quietly —
a flag emitted with a default nobody chose looks exactly like a flag the
operator set.

Pinned by value: each flag with its value; each of the three default-ON
booleans in all three states (unstated / off / on); the two presence flags; the
draft-side flag and the embeddings gate that suppresses it; the YaRN field
against the automatic YaRN recipe, which must not state the same flag twice.

Run: python3 scripts/test_llama_flags.py
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import caravan.admin.models as models_mod                    # noqa: E402
from caravan.admin.config_builder import (                   # noqa: E402
    CONFIG_FIELDS, FIELD_HELP, build_llama_args, flag_to_field_map,
    parse_extra_args,
)

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


BASE = {"MODEL_FILE": "m.gguf", "PORT": "22042"}


def args(**over):
    return build_llama_args({**BASE, **over}, model_path="/models/m.gguf")


def value_of(argv, flag):
    """The token after `flag`, or None when the flag is absent."""
    return argv[argv.index(flag) + 1] if flag in argv else None


# field -> (flag, a value worth recognising)
VALUE_FLAGS = [
    ("CHECKPOINT_MIN_STEP", "--checkpoint-min-step", "4096"),
    ("SLOT_PROMPT_SIMILARITY", "--slot-prompt-similarity", "0.55"),
    ("SLOT_SAVE_PATH", "--slot-save-path", "/var/lib/caravan/slots"),
    ("SSE_PING_INTERVAL", "--sse-ping-interval", "15"),
    ("PRIO", "--prio", "2"),
    ("YARN_ORIG_CTX", "--yarn-orig-ctx", "32768"),
    ("YARN_EXT_FACTOR", "--yarn-ext-factor", "0.0"),
    ("YARN_ATTN_FACTOR", "--yarn-attn-factor", "1.5"),
    ("YARN_BETA_FAST", "--yarn-beta-fast", "32"),
    ("YARN_BETA_SLOW", "--yarn-beta-slow", "1"),
    ("SPEC_DRAFT_P_SPLIT", "--spec-draft-p-split", "0.25"),
    ("CORS_METHODS", "--cors-methods", "GET,POST"),
    ("CORS_HEADERS", "--cors-headers", "Authorization,Content-Type"),
]


def main():
    empty = args()

    # ── Value flags ──────────────────────────────────────────────────────────
    for field, flag, val in VALUE_FLAGS:
        got = args(**{field: val})
        check(value_of(got, flag) == val, f"{field}={val} → {flag} {val}")
        check(flag not in empty, f"…и без {field} флага {flag} нет")

    # ── The three the binary has ON by default ───────────────────────────────
    for field, on, off in (("OP_OFFLOAD", "--op-offload", "--no-op-offload"),
                           ("REPACK", "--repack", "--no-repack"),
                           ("WARMUP", "--warmup", "--no-warmup")):
        check(on not in empty and off not in empty,
              f"{field} не задан → ни {on}, ни {off}: умолчание бинаря остаётся умолчанием")
        check(off in args(**{field: "0"}) and on not in args(**{field: "0"}),
              f"{field}=0 → {off}")
        check(on in args(**{field: "1"}) and off not in args(**{field: "1"}),
              f"{field}=1 → {on}")

    # ── Presence flags ───────────────────────────────────────────────────────
    for field, flag in (("CPU_MOE", "--cpu-moe"), ("CHECK_TENSORS", "--check-tensors")):
        check(flag in args(**{field: "1"}), f"{field}=1 → {flag}")
        check(flag not in args(**{field: "0"}) and flag not in empty,
              f"{field}=0 или пусто → без {flag}")

    # A draft-side flag on an embeddings cell is spec leaking into a server that
    # has no draft: the same gate that drops --spec-type drops this one.
    check("--spec-draft-cpu-moe" in args(CPU_MOE_DRAFT="1"), "CPU_MOE_DRAFT=1 → --spec-draft-cpu-moe")
    check("--spec-draft-cpu-moe" not in args(CPU_MOE_DRAFT="1", ENABLE_EMBEDDINGS="1"),
          "…но на embeddings-ячейке — нет, как и остальные spec-флаги")
    check("--cpu-moe" in args(CPU_MOE="1", ENABLE_EMBEDDINGS="1"),
          "а --cpu-moe с embeddings живёт: это размещение весов, не спекуляция")

    # ── EXTRA_ARGS hoisting: the flag an operator already typed ──────────────
    typed = ("--checkpoint-min-step 512 -sps 0.3 --slot-save-path /s "
             "--sse-ping-interval 5 --prio 1 --cpu-moe --no-op-offload -nr "
             "--no-warmup --check-tensors --yarn-orig-ctx 8192 --yarn-ext-factor 0 "
             "--yarn-attn-factor 1 --yarn-beta-fast 32 --yarn-beta-slow 1 "
             "--draft-p-split 0.4 -cmoed --cors-methods GET --cors-headers X")
    hoisted = parse_extra_args(typed)
    got = hoisted["recognized"]
    want = {
        "CHECKPOINT_MIN_STEP": "512", "SLOT_PROMPT_SIMILARITY": "0.3",
        "SLOT_SAVE_PATH": "/s", "SSE_PING_INTERVAL": "5", "PRIO": "1",
        "CPU_MOE": "1", "OP_OFFLOAD": "0", "REPACK": "0", "WARMUP": "0",
        "CHECK_TENSORS": "1", "YARN_ORIG_CTX": "8192", "YARN_EXT_FACTOR": "0",
        "YARN_ATTN_FACTOR": "1", "YARN_BETA_FAST": "32", "YARN_BETA_SLOW": "1",
        "SPEC_DRAFT_P_SPLIT": "0.4", "CPU_MOE_DRAFT": "1",
        "CORS_METHODS": "GET", "CORS_HEADERS": "X",
    }
    for key, val in want.items():
        check(got.get(key) == val, f"из EXTRA_ARGS поднято {key}={val!r} (было {got.get(key)!r})")
    check(hoisted["remaining"] == "", f"…и в EXTRA_ARGS не осталось ничего: {hoisted['remaining']!r}")

    # ── Every new field is traceable and documented ──────────────────────────
    owners = flag_to_field_map()
    for field, flag, _ in VALUE_FLAGS:
        check(owners.get(flag) == field, f"наведение на {flag} находит поле {field}")
    for field in want:
        check(field in CONFIG_FIELDS, f"{field} в CONFIG_FIELDS")
        check(len(FIELD_HELP.get(field, "")) > 40, f"{field} объяснён в FIELD_HELP")

    # ── The automatic YaRN recipe must not say the same thing twice ──────────
    real_read, real_extract = models_mod.read_gguf_metadata_cached, models_mod.extract_runtime_meta
    try:
        models_mod.read_gguf_metadata_cached = lambda path: {"stub": True}
        models_mod.extract_runtime_meta = lambda meta: {"contextLength": 32768, "architecture": "llama"}
        with tempfile.TemporaryDirectory() as tmp:
            gguf = Path(tmp) / "m.gguf"
            gguf.write_bytes(b"GGUF")

            def auto(**over):
                return build_llama_args({**BASE, "CTX_SIZE": "65536", **over}, model_path=str(gguf))

            plain = auto()
            check(plain.count("--yarn-orig-ctx") == 1 and value_of(plain, "--yarn-orig-ctx") == "32768",
                  "CTX_SIZE выше родного окна → рецепт сам ставит --yarn-orig-ctx 32768")
            stated = auto(YARN_ORIG_CTX="16384")
            check(stated.count("--yarn-orig-ctx") == 1 and value_of(stated, "--yarn-orig-ctx") == "16384",
                  "но заданное поле побеждает и флаг остаётся ОДИН — иначе бинарь берёт последний")
            check(stated.count("--override-kv") == 1,
                  "--override-kv по-прежнему ставится ровно один раз")
            extra = auto(EXTRA_ARGS="--yarn-orig-ctx 4096")
            check(extra.count("--yarn-orig-ctx") == 1 and value_of(extra, "--yarn-orig-ctx") == "4096",
                  "и написанное руками в EXTRA_ARGS тоже не удваивается (as-is)")
            check(auto(YARN_EXT_FACTOR="0.0").count("--yarn-ext-factor") == 1,
                  "--yarn-ext-factor рецепт не ставит — поле единственный источник")
    finally:
        models_mod.read_gguf_metadata_cached, models_mod.extract_runtime_meta = real_read, real_extract

    if _fail:
        print(f"FAILED ({len(_fail)}):")
        for msg in _fail:
            print("  - " + msg)
        sys.exit(1)
    print("llama-flag snapshots hold")


if __name__ == "__main__":
    main()
