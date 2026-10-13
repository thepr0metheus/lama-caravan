#!/usr/bin/env python3
"""Value snapshot: the badge and the folder a safetensors checkpoint gets on /hf (caravan/admin/hf.py).

The format names the checkpoint's folder (<model>/<author>/<FORMAT>), so a wrong badge is a
wrong folder too. The repository's name says it, or config.json's quantization_config, or the
weights' type. transformers wrote that type as `torch_dtype` and writes `dtype` since 4.56:
nvidia/GR00T-N1.7-3B (2026-10-12) said `dtype: bfloat16` and got "SAFETENSORS".

Run: python3 scripts/test_hf_checkpoint_format.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from caravan.admin.hf import _safetensors_format  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


print("значок чекпойнта:")
check(_safetensors_format("nvidia/GR00T-N1.7-3B", {"dtype": "bfloat16"}) == "BF16",
      "defect-history: `dtype` нового transformers — BF16 (раньше SAFETENSORS)")
check(_safetensors_format("org/model", {"torch_dtype": "float16"}) == "FP16", "`torch_dtype` прежних конфигов — как был")
check(_safetensors_format("org/model", {"torch_dtype": "float32", "dtype": "bfloat16"}) == "FP32",
      "оба поля — побеждает `torch_dtype`, как читалось всегда")
check(_safetensors_format("org/model-AWQ", {"dtype": "bfloat16"}) == "AWQ", "имя репозитория сильнее типа весов")
check(_safetensors_format("org/model", {"quantization_config": {"quant_method": "fp8"}, "dtype": "bfloat16"}) == "FP8",
      "quantization_config сильнее типа весов")
check(_safetensors_format("org/model", {"dtype": "int8"}) == "SAFETENSORS", "negative: тип, которого нет в таблице, — SAFETENSORS")
check(_safetensors_format("org/model", None) == "SAFETENSORS", "negative: config.json не прочитан — SAFETENSORS, а не догадка")

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail:
        print("  - " + m)
    sys.exit(1)
print("hf checkpoint format snapshot holds")
