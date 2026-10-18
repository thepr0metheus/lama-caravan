"""Which pair of flash attention and V cache type llama.cpp starts with.

llama.cpp keeps the V half of its KV cache in a quantized type (q8_0, q4_0 …) only with flash
attention on. With it off the context cannot be made and the server exits at once:

    E llama_init_from_model: quantized V cache requires flash_attn to be enabled
    E srv  llama_server: exiting due to model loading error

The cell form of a new cell offered exactly that pair: V cache q8_0 and flash attention off
(2026-10-14, the first start of a Qwen3-Omni cell: four crashes in ten minutes). The card said
"Model loading failed" and showed the last line of the log, which is not the cause.

So the pair is refused where it can be refused with the cause named: at Apply (static/js/kv-cache.js,
the same rule, held to this one by scripts/fixtures/kv-cache-cases.json) and before a start
(Runner.preflight_start), for a cell saved earlier. Flash attention left UNSTATED is not refused: then
llama.cpp decides for itself (`auto`), and it is no choice the operator made.
"""
from caravan.common.errors import AppError
from caravan.common.flags import truthy


class KvCache:
    """The one rule: a quantized V cache needs flash attention."""

    #: The cache types that hold plain numbers, so need no flash attention. "" is
    #: the field left empty: llama.cpp's own default, f16.
    PLAIN = ("", "f32", "f16", "bf16")
    #: The cell's V cache. (The draft model's own cache types are saved but not passed.)
    V_FIELD = "CACHE_TYPE_V"
    FLASH_FIELD = "ENABLE_FLASH_ATTN"

    @classmethod
    def refused_type(cls, config):
        """The quantized V cache type this config pairs with flash attention OFF, or "" when the
        pair is fine. Off means stated and not a yes: an empty field is not a choice."""
        cfg = config or {}
        flash = str(cfg.get(cls.FLASH_FIELD) or "").strip()
        if not flash or truthy(flash):
            return ""
        kind = str(cfg.get(cls.V_FIELD) or "").strip().lower()
        return "" if kind in cls.PLAIN else kind

    @classmethod
    def check(cls, config):
        """Raise AppError, naming the cause and the two ways out, for a pair llama.cpp does not start with."""
        kind = cls.refused_type(config)
        if kind:
            raise AppError(
                f"The V cache type {kind} needs flash attention, which is off: llama.cpp stops with "
                "'quantized V cache requires flash_attn to be enabled'. Turn ENABLE_FLASH_ATTN on, "
                "or set CACHE_TYPE_V to f16.", 400)
