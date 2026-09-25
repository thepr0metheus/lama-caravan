"""Token-rate history (token-history.json), fed by the proxy's own records.

_token_history is rebound here — every function that rebinds it must stay in
this module (import-freeze rule). (The controller-side token counters, which
scraped the controller's own llama-servers every second, went with its cells
in step 6.9: a cell's rates now come from its machine's scout.)
"""
import json
import threading
import time

from caravan.admin.paths import TOKEN_HISTORY_FILE, TOKEN_HISTORY_MAX, TOKEN_HISTORY_RETENTION_SEC
from caravan.common.fsio import atomic_write_text


_token_history = None

_token_history_lock = threading.Lock()

def load_token_history():
    global _token_history
    if _token_history is None:
        _token_history = []
        if TOKEN_HISTORY_FILE.exists():
            try:
                data = json.loads(TOKEN_HISTORY_FILE.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    _token_history = data
            except Exception:
                _token_history = []
    return _token_history

def save_token_history():
    hist = _token_history or []
    cutoff = time.time() - TOKEN_HISTORY_RETENTION_SEC
    hist = [h for h in hist if h.get("t", 0) >= cutoff][-TOKEN_HISTORY_MAX:]
    globals()["_token_history"] = hist
    try:
        atomic_write_text(TOKEN_HISTORY_FILE, json.dumps(hist, ensure_ascii=False) + "\n")
    except Exception:
        pass

def _usage_sample(item):
    """Generation speed derived from a completed request's TOTALS, or None.

    llama.cpp hands over its own `timings` block, and the whole history used
    to be written from that alone. A cloud upstream never sends that block at
    all — so a port that carried traffic all day had an empty chart, and it
    looked like "there were no requests". There were plenty; there was no
    MEASUREMENT.

    Exactly one thing can be derived: how many tokens arrived, and over how
    much time after the first byte. That's a real generation speed, not a
    guess. A prompt speed cannot be derived from this: the time to first byte
    on a cloud call is network and the provider's queue, and passing it off
    as prompt processing would be a lie.
    """
    if not isinstance(item, dict) or item.get("timings"):
        return None
    resp = item.get("response") if isinstance(item.get("response"), dict) else {}
    strm = item.get("stream") if isinstance(item.get("stream"), dict) else {}
    usage = resp.get("usage") if isinstance(resp.get("usage"), dict) else {}
    if not usage:
        usage = strm.get("usage") if isinstance(strm.get("usage"), dict) else {}
    if not usage:
        return None
    try:
        eval_tokens = int(usage.get("completion_tokens") or usage.get("completionTokens") or 0)
        prompt_tokens = int(usage.get("prompt_tokens") or usage.get("promptTokens") or 0)
        total_ms = float(item.get("durationMs") or item.get("elapsedMs") or 0)
        first_byte_ms = float(item.get("firstByteMs") or 0)
    except (TypeError, ValueError):
        return None
    gen_ms = total_ms - first_byte_ms
    if eval_tokens <= 0 or gen_ms <= 0:
        return None
    return {
        "evalTokens": eval_tokens,
        "promptTokens": prompt_tokens,
        "genMs": int(round(gen_ms)),
        "evalTps": round(eval_tokens / (gen_ms / 1000.0), 1),
    }


def record_token_history(sample):
    """Append one entry per COMPLETED proxy request, from llama.cpp's exact
    per-request `timings` carried on the proxy record, attributed to the
    consumer by proxy port. This is the authoritative per-request source —
    exact sizes/durations/throughput, deduped by the proxy request id (no
    time-correlation guesswork)."""
    agents = (sample.get("agentProxies") or {}).get("agents") or {}
    items = []
    for row in (agents.values() if isinstance(agents, dict) else []):
        for item in (row.get("recent") or []):
            if not isinstance(item, dict):
                continue
            if isinstance(item.get("timings"), dict) and item.get("timings"):
                items.append(item)
            elif _usage_sample(item):
                items.append(item)
    if not items:
        return
    with _token_history_lock:
        hist = load_token_history()
        # Dedup by proxy request id. Window comfortably exceeds the proxy's
        # retained recent items (≤20 per agent) so nothing is double-counted.
        recent_sigs = {h.get("sig") for h in hist[-2000:]}
        changed = False
        for item in items:
            tm = item.get("timings") or {}
            derived = None if tm else _usage_sample(item)
            eval_tokens = int(tm.get("predicted_n") or 0) if tm else derived["evalTokens"]
            if eval_tokens <= 0:
                continue
            ts = item.get("finishedAt")
            rid = str(item.get("id") or "")
            sig = rid or f"{ts}:{eval_tokens}:{tm.get('predicted_per_second') if tm else derived['evalTps']}"
            if sig in recent_sigs:
                continue
            try:
                port = int(item.get("port")) if item.get("port") is not None else None
            except (TypeError, ValueError):
                port = None
            # finish_reason ("stop"/"length"/…) — already summarized by the proxy
            # in the response or final stream chunk. "length" means the answer was
            # cut at max_tokens, a useful per-consumer signal.
            resp = item.get("response") if isinstance(item.get("response"), dict) else {}
            strm = item.get("stream") if isinstance(item.get("stream"), dict) else {}
            finishes = resp.get("finishReasons") or strm.get("finishReasons") or []
            finish = str(finishes[0]) if isinstance(finishes, list) and finishes else ""
            hist.append({
                "t": int(ts) if ts else int(time.time()),
                "sig": sig,
                "client": item.get("client") or "",
                "port": port,
                "route": item.get("route") or "",
                # Prompt speed is NOT set for a derived entry. The time to
                # first byte on a cloud call is network and the provider's
                # queue, not prompt processing; calling it "prompt speed"
                # would claim a measurement we never took.
                "promptTps": round(float(tm.get("prompt_per_second") or 0), 1) if tm else 0,
                "evalTps": round(float(tm.get("predicted_per_second") or 0), 1) if tm else derived["evalTps"],
                "promptTokens": int(tm.get("prompt_n") or 0) if tm else derived["promptTokens"],
                "evalTokens": eval_tokens,
                "promptMs": int(round(float(tm.get("prompt_ms") or 0))) if tm else 0,
                "genMs": int(round(float(tm.get("predicted_ms") or 0))) if tm else derived["genMs"],
                "cacheTokens": int(tm.get("cache_n") or 0) if tm else 0,
                "finish": finish,
                # What it was measured with: the server's own timings, or
                # derived from the request's totals. Not the same thing to
                # whoever reads the chart.
                "source": "timings" if tm else "usage",
            })
            recent_sigs.add(sig)
            changed = True
        if changed:
            save_token_history()

def token_history_query(client="", range_key="all", port=None):
    with _token_history_lock:
        hist = list(load_token_history())
    # Prefer the proxy port (consumer identity) when given; fall back to client
    # IP for legacy entries recorded before per-port attribution existed.
    if port:
        try:
            port_i = int(port)
            hist = [h for h in hist if h.get("port") == port_i]
        except (TypeError, ValueError):
            pass
    elif client:
        hist = [h for h in hist if h.get("client") == client]
    windows = {"1h": 3600, "12h": 12 * 3600, "24h": 24 * 3600}
    if range_key in windows:
        cutoff = time.time() - windows[range_key]
        hist = [h for h in hist if h.get("t", 0) >= cutoff]
    return [{
        "t": h.get("t"), "promptTps": h.get("promptTps", 0), "evalTps": h.get("evalTps", 0),
        "promptTokens": h.get("promptTokens", 0), "evalTokens": h.get("evalTokens", 0),
        "promptMs": h.get("promptMs", 0), "genMs": h.get("genMs", 0),
        "cacheTokens": h.get("cacheTokens", 0), "finish": h.get("finish", ""),
        "port": h.get("port"), "route": h.get("route", ""), "client": h.get("client", ""),
    } for h in hist]
