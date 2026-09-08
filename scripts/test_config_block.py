#!/usr/bin/env python3
"""Snapshot of the KEY="value" block a cell carries in its own start script.

The block is the cell's description of itself: `build_config_block` writes it,
`parse_config_from_text` reads it back, and a config backup is nothing but that
round trip. So a field the block omits is a field a restore silently drops —
the cell comes back configured differently and nothing reports it. That is what
happened to seventeen settings, TEMPERATURE and SWA_FULL among them, because
the writer worked from a hand-curated list of groups while CONFIG_FIELDS kept
growing.

Pinned by value: every llama field survives the round trip; the readable
grouping and its leading order are unchanged; the runners' own fields stay out;
and the validation that block writing performs still refuses what it refused.

Run: python3 scripts/test_config_block.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from caravan.common.errors import AppError                    # noqa: E402
from caravan.admin.config_builder import (                    # noqa: E402
    CONFIG_BEGIN, CONFIG_END, CONFIG_FIELDS, LLAMA_CONFIG_FIELDS,
    build_config_block, parse_config_from_text,
)

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def block_keys(text):
    """The keys the block states, in the order it states them."""
    out = []
    for line in text.splitlines():
        line = line.strip()
        if line and "=" in line and not line.startswith("#"):
            out.append(line.split("=", 1)[0])
    return out


# A config that states every llama field. The values are deliberately
# distinguishable per field, because the property under test is that each one
# comes back as ITSELF and not as a neighbour's.
FULL = {}
for _i, _f in enumerate(LLAMA_CONFIG_FIELDS):
    FULL[_f] = f"v{_i}"
FULL.update({
    "MODEL_FILE": "vendor/m/Q4_K_M/m-7B-Q4_K_M.gguf",
    "PORT": "22042",
    "HOST": "0.0.0.0",
    "CTX_SIZE": "131072",
    "THREADS": "16",
    "THREADS_BATCH": "16",
    "BATCH_SIZE": "2048",
    "UBATCH_SIZE": "512",
    "PARALLEL": "4",
    "N_PREDICT": "-1",
    "KEEP": "0",
    "POLL": "50",
    "MAIN_GPU": "0",
    "FIT_CTX": "1",
    "FIT_TARGET": "90,90",
    "TIMEOUT": "600",
    "THREADS_HTTP": "8",
    "CACHE_REUSE": "256",
    "CACHE_RAM": "8192",
    "SLEEP_IDLE_SECONDS": "0",
    "IMAGE_MIN_TOKENS": "64",
    "IMAGE_MAX_TOKENS": "2048",
    "REASONING_BUDGET": "-1",
    "SPEC_DRAFT_N_GPU_LAYERS": "999",
    "SPEC_DRAFT_N_MAX": "16",
    "SPEC_DRAFT_N_MIN": "0",
    # The eight that used to vanish, given values worth recognising.
    "TEMPERATURE": "0.7",
    "SWA_FULL": "1",
    "CTX_CHECKPOINTS": "24",
    "N_CPU_MOE": "12",
    "CORS_ORIGINS": "https://board.local",
    "API_KEY_FILE": "/etc/caravan/keys",
    "TOOLS_RUNTIME": "docker:alpine",
    "MMPROJ_AUTO": "0",
})


def main():
    text = build_config_block(FULL)
    keys = block_keys(text)

    # ── Every field survives ─────────────────────────────────────────────────
    missing = [f for f in LLAMA_CONFIG_FIELDS if f not in keys]
    check(not missing, f"каждое llama-поле записано в блок (не записаны: {missing})")

    back = parse_config_from_text(f"#!/bin/sh\n{text}\nexec llama-server\n", "pin")
    wrong = [f for f in LLAMA_CONFIG_FIELDS if str(back.get(f, "")) != str(FULL[f])]
    check(not wrong, f"и читается обратно тем же значением (разошлись: {wrong})")

    # The settings that used to be dropped, named one by one: a regression here
    # is a backup that restores a different cell, and the count alone would not
    # say which one.
    for field, value in (("TEMPERATURE", "0.7"), ("SWA_FULL", "1"),
                         ("CTX_CHECKPOINTS", "24"), ("N_CPU_MOE", "12"),
                         ("CORS_ORIGINS", "https://board.local"),
                         ("API_KEY_FILE", "/etc/caravan/keys"),
                         ("TOOLS_RUNTIME", "docker:alpine"), ("MMPROJ_AUTO", "0")):
        check(back.get(field) == value, f"{field} переживает круг: {value!r}")

    # ── The runners' fields stay out ─────────────────────────────────────────
    runner_only = [f for f in CONFIG_FIELDS if f not in LLAMA_CONFIG_FIELDS]
    check(runner_only[:3] == ["RUNNER", "CELL_KIND", "COMMAND"],
          "граница llama/раннеры проходит по RUNNER")
    check(not [f for f in runner_only if f in keys],
          "поля раннеров (COMMAND, VLLM_MODEL, WHISPER_MODEL…) в llama-блок не попадают")
    check("WHISPER_MODEL" not in keys and "VLLM_MODEL" not in keys,
          "…названные поимённо")

    # ── The readable grouping is unchanged ───────────────────────────────────
    check(keys[:2] == ["HOST", "PORT"], "блок по-прежнему открывается HOST, PORT")
    check(keys[2:5] == ["LLAMA_MODELS_DIR", "MODEL_FILE", "MMPROJ_FILE"],
          "затем группа моделей")
    check(text.startswith(CONFIG_BEGIN) and text.rstrip("\n").endswith(CONFIG_END),
          "маркеры на месте — по ним блок и вырезается")
    check("\n\n" in text, "группы по-прежнему разделены пустой строкой")
    check(len(keys) == len(set(keys)), "ни одно поле не записано дважды")
    check(keys[-1] == LLAMA_CONFIG_FIELDS[-1] or keys[-1] not in keys[:-1],
          "хвост — дописанный остаток, а не повтор")

    # ── Quoting, as is ───────────────────────────────────────────────────────
    quoted = build_config_block({**FULL, "EXTRA_ARGS": '--x "a b" $HOME \\ '})
    line = [l for l in quoted.splitlines() if l.startswith("EXTRA_ARGS=")][0]
    check(line == 'EXTRA_ARGS="--x \\"a b\\" \\$HOME \\\\"',
          "кавычки, доллар и обратный слэш экранируются, хвостовой пробел срезан (as-is)")
    check(parse_config_from_text(f"#!/bin/sh\n{quoted}\n", "pin")["EXTRA_ARGS"]
          == '--x \\"a b\\" \\$HOME \\\\',
          "…а на чтении экранирование НЕ снимается — as-is, читатель это шелл")

    # ── Empty is a value ─────────────────────────────────────────────────────
    empty = build_config_block({**FULL, "SWA_FULL": "", "TEMPERATURE": ""})
    check('SWA_FULL=""' in empty and 'TEMPERATURE=""' in empty,
          "снятый флаг пишется пустым, а не пропускается — иначе форма унаследует умолчание")

    # ── Negative: what the writer refuses ────────────────────────────────────
    def refuses(cfg, why):
        try:
            build_config_block(cfg)
        except AppError as exc:
            check(True, f"{why}: {exc}")
            return
        check(False, f"{why}: не отказал")

    refuses({**FULL, "MODEL_FILE": ""}, "без MODEL_FILE")
    refuses({**FULL, "PORT": "http"}, "нечисловой PORT")
    refuses({**FULL, "CTX_SIZE": "много"}, "нечисловой CTX_SIZE")
    refuses({**FULL, "FIT_TARGET": "90;90"}, "FIT_TARGET не через запятую")

    # A field nobody validates is still written — the block is a record, not a
    # schema, and llama-server is the one that judges the value.
    odd = build_config_block({**FULL, "PRIO_UNKNOWN": "1", "SPEC_TYPE": "не-тип"})
    check("PRIO_UNKNOWN" not in block_keys(odd),
          "ключ вне CONFIG_FIELDS в блок не попадает")
    check('SPEC_TYPE="не-тип"' in odd, "невалидное значение известного поля пишется как есть")
    check(parse_config_from_text(f"#!/bin/sh\n{odd}\n", "pin").get("PRIO_UNKNOWN") is None,
          "и на чтении такой ключ игнорируется")

    try:
        parse_config_from_text("#!/bin/sh\necho no markers\n", "pin")
        check(False, "текст без маркеров: не отказал")
    except AppError as exc:
        check("markers" in str(exc), f"текст без маркеров: {exc}")

    if _fail:
        print(f"FAILED ({len(_fail)}):")
        for msg in _fail:
            print("  - " + msg)
        sys.exit(1)
    print("config-block snapshots hold")


if __name__ == "__main__":
    main()
