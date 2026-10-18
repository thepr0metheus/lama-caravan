"""LiteLLM model-pricing table with a 24h on-disk cache."""
import json
import time
import urllib.request

from caravan.admin.paths import MODEL_PRICING_CACHE_PATH, MODEL_PRICING_TTL, MODEL_PRICING_URL
from caravan.common.fsio import atomic_write_text


#: The shape of the cache file. 2: rows may carry `cacheReadPer1M` and `cacheWritePer1M` (1.3.585). A file of another shape is refetched, not
#: read: a table of the older shape would price every cached token as a plain one until its day was up.
PRICING_SHAPE = 2


def per_million(value):
    """A LiteLLM price per token as dollars per million tokens, or None where the table names no usable one."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    return round(number * 1_000_000, 6) if number >= 0 else None


def fetch_model_pricing():
    """Fetch LiteLLM model pricing JSON, cache on disk for 24 h.

    Returns a dict keyed by model name:
      { model_name: { inputPer1M, outputPer1M, provider[, cacheReadPer1M, cacheWritePer1M] } }
    The cache prices are the table's `cache_read_input_token_cost` and `cache_creation_input_token_cost`; a row that does not name them has none.
    On error returns the cached table even when it is old or of an older shape — an old price is better than none, and no price reads as a
    spend of nothing — and {} when there is none (silently, non-critical feature).
    """
    # Return from cache if fresh
    stale = {}
    try:
        if MODEL_PRICING_CACHE_PATH.exists():
            cached = json.loads(MODEL_PRICING_CACHE_PATH.read_text(encoding="utf-8"))
            if isinstance(cached, dict) and isinstance(cached.get("pricing"), dict):
                if cached.get("shape") == PRICING_SHAPE and time.time() - float(cached.get("fetchedAt", 0)) < MODEL_PRICING_TTL:
                    return cached.get("pricing") or {}
                stale = cached["pricing"]
    except Exception:
        pass

    # Fetch from GitHub raw
    try:
        req = urllib.request.Request(MODEL_PRICING_URL, headers={"User-Agent": "llamacpp-easy-admin/1.0"})
        with urllib.request.urlopen(req, timeout=15) as response:
            raw = json.loads(response.read().decode("utf-8"))
    except Exception:
        return stale

    pricing = {}
    for model_name, data in raw.items():
        if not isinstance(data, dict):
            continue
        inp = data.get("input_cost_per_token")
        out = data.get("output_cost_per_token")
        if inp is None and out is None:
            continue
        pricing[model_name] = {
            "inputPer1M": round(float(inp or 0) * 1_000_000, 6),
            "outputPer1M": round(float(out or 0) * 1_000_000, 6),
            "provider": str(data.get("litellm_provider") or ""),
        }
        for name, field in (("cacheReadPer1M", "cache_read_input_token_cost"), ("cacheWritePer1M", "cache_creation_input_token_cost")):
            price = per_million(data.get(field))
            if price is not None:
                pricing[model_name][name] = price

    try:
        atomic_write_text(MODEL_PRICING_CACHE_PATH,
                          json.dumps({"fetchedAt": int(time.time()), "shape": PRICING_SHAPE, "pricing": pricing},
                                     ensure_ascii=False) + "\n", mkdir=True)
    except Exception:
        pass

    return pricing
