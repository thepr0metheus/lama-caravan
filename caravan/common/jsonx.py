"""JSON serialization helpers shared by HTTP responders."""
import json


_INF = float("inf")

def _json_safe(o):
    """Replace non-finite floats (inf/nan) with None so responses are valid JSON —
    the browser's JSON.parse rejects Infinity/NaN even though Python's accepts them."""
    if isinstance(o, float):
        return o if (o == o and o != _INF and o != -_INF) else None
    if isinstance(o, dict):
        return {k: _json_safe(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_json_safe(v) for v in o]
    return o

def json_bytes(payload):
    # Fast path emits valid JSON; only sanitize (walk the tree) when inf/nan slipped in.
    try:
        return json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
    except ValueError:
        return json.dumps(_json_safe(payload), ensure_ascii=False, indent=2).encode("utf-8")
