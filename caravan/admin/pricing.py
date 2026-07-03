"""LiteLLM model-pricing table with a 24h on-disk cache."""
import json
import time
import urllib.request

from caravan.admin.paths import MODEL_PRICING_CACHE_PATH, MODEL_PRICING_TTL, MODEL_PRICING_URL
from caravan.common.fsio import atomic_write_text


def fetch_model_pricing():
    """Fetch LiteLLM model pricing JSON, cache on disk for 24 h.

    Returns a dict keyed by model name:
      { model_name: { inputPer1M, outputPer1M, provider } }
    On error returns {} (silently, non-critical feature).
    """
    # Return from cache if fresh
    try:
        if MODEL_PRICING_CACHE_PATH.exists():
            cached = json.loads(MODEL_PRICING_CACHE_PATH.read_text(encoding="utf-8"))
            if isinstance(cached, dict) and time.time() - float(cached.get("fetchedAt", 0)) < MODEL_PRICING_TTL:
                return cached.get("pricing") or {}
    except Exception:
        pass

    # Fetch from GitHub raw
    try:
        req = urllib.request.Request(MODEL_PRICING_URL, headers={"User-Agent": "llamacpp-easy-admin/1.0"})
        with urllib.request.urlopen(req, timeout=15) as response:
            raw = json.loads(response.read().decode("utf-8"))
    except Exception:
        return {}

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

    try:
        atomic_write_text(MODEL_PRICING_CACHE_PATH,
                          json.dumps({"fetchedAt": int(time.time()), "pricing": pricing},
                                     ensure_ascii=False) + "\n", mkdir=True)
    except Exception:
        pass

    return pricing
