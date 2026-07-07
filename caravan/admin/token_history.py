"""Token-rate history (token-history.json) and controller-side TPS counters.

_token_history and the controller counters are rebound here — every function
that rebinds them must stay in this module (import-freeze rule).
"""
import json
import threading
import time

from caravan.admin.config_builder import parse_config
from caravan.admin.llama_metrics import runtime_metrics_sample
from caravan.admin.paths import TOKEN_HISTORY_FILE, TOKEN_HISTORY_MAX, TOKEN_HISTORY_RETENTION_SEC
from caravan.admin.state import topology_store
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
            if isinstance(item, dict) and isinstance(item.get("timings"), dict) and item.get("timings"):
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
            eval_tokens = int(tm.get("predicted_n") or 0)
            if eval_tokens <= 0:
                continue
            ts = item.get("finishedAt")
            rid = str(item.get("id") or "")
            sig = rid or f"{ts}:{eval_tokens}:{tm.get('predicted_per_second')}"
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
                "promptTps": round(float(tm.get("prompt_per_second") or 0), 1),
                "evalTps": round(float(tm.get("predicted_per_second") or 0), 1),
                "promptTokens": int(tm.get("prompt_n") or 0),
                "evalTokens": eval_tokens,
                "promptMs": int(round(float(tm.get("prompt_ms") or 0))),
                "genMs": int(round(float(tm.get("predicted_ms") or 0))),
                "cacheTokens": int(tm.get("cache_n") or 0),
                "finish": finish,
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

def controller_llama_ports():
    """Live llama-server ports on the controller: reserved cells plus
    the legacy single-server PORT. The model now runs in a cell (e.g. :8001),
    not on the legacy PORT, so node-level token sampling must look at the cells
    too — otherwise the controller TOKEN SPEED chart scrapes a dead :8080 and
    stays empty during real generation."""
    ports = []
    try:
        store = topology_store()
        for key, slot in (store.get("serverSlots") or {}).items():
            # Controller slots are always keyed/tagged "skynet" (see
            # is_controller_slot in topology_server); client cells carry their
            # own hostId and must NOT be summed into the controller's throughput.
            host_id = str(slot.get("hostId") or str(key).split(":")[0] or "")
            if host_id == "skynet":
                try:
                    ports.append(int(slot.get("port") or str(key).rsplit(":", 1)[-1]))
                except (TypeError, ValueError):
                    continue
    except Exception:
        pass
    try:
        ports.append(int(parse_config().get("PORT") or 8080))
    except Exception:
        pass
    seen, out = set(), []
    for port in ports:
        if port not in seen:
            seen.add(port)
            out.append(port)
    return out

# Token-speed counters per controller port (sampler thread only — no lock).
# Tuple: (promptTokensTotal, predictedTokensTotal, promptSecondsTotal, predictedSecondsTotal)
_controller_token_counters: dict = {}

# Generation-only token-speed series: one row PER COMPLETED REQUEST. llama.cpp
# updates its token counters atomically at request completion (the counter jumps
# once at the end, even for multi-second streams — verified), so a counter
# advance since the last scrape == a request just finished. Idle ticks add
# nothing, so the chart shows real per-request points connected across gaps,
# never the held-gauge plateau.
_controller_gen_tps: list = []           # [{t, promptTps, genTps, promptTokens, genTokens, promptMs, genMs}]

_controller_gen_tps_lock = threading.Lock()

CONTROLLER_GEN_TPS_MAX = 600             # keep the last N completed-request points

def controller_token_metrics():
    """Aggregate token throughput across the controller's live llama-servers and
    flag whether generation is happening *right now*.

    The model runs in a cell, not on the legacy PORT, so scrape every controller
    llama port and sum the per-server gauges. Crucially, llama.cpp's *_seconds
    gauges HOLD the last request's value while idle, so the gauge alone can't
    tell "generating" from "idle". We detect real activity by the cumulative
    token counters advancing since the last scrape; only then is the rate a live
    generation value. Same schema as runtime_metrics_sample() plus `generating`
    and the gen-only gauge sums (`genPromptTps` / `genGenTps`)."""
    agg = {"ok": False, "promptTokensPerSecond": 0.0, "predictedTokensPerSecond": 0.0,
           "requestsProcessing": 0, "requestsDeferred": 0, "kvCacheUsageRatio": 0.0,
           # Per-request fields, populated only on a completion tick (counter advance).
           "generating": False, "reqPromptTps": 0.0, "reqGenTps": 0.0,
           "reqPromptTokens": 0, "reqGenTokens": 0, "reqPromptMs": 0.0, "reqGenMs": 0.0}
    for port in controller_llama_ports():
        metrics = runtime_metrics_sample(port)
        if not metrics.get("ok"):
            continue
        agg["ok"] = True
        # Lifetime gauges — kept for the live "live tokens" consumers only.
        agg["promptTokensPerSecond"] += float(metrics.get("promptTokensPerSecond") or 0)
        agg["predictedTokensPerSecond"] += float(metrics.get("predictedTokensPerSecond") or 0)
        agg["requestsProcessing"] += int(metrics.get("requestsProcessing") or 0)
        agg["requestsDeferred"] += int(metrics.get("requestsDeferred") or 0)
        agg["kvCacheUsageRatio"] = max(agg["kvCacheUsageRatio"],
                                       float(metrics.get("kvCacheUsageRatio") or 0))
        # Cumulative counters advance only at request completion → a delta means
        # one request just finished. Derive its exact size + duration + the REAL
        # per-request throughput (Δtokens/Δseconds) from the deltas.
        prompt_tok = float(metrics.get("promptTokensTotal") or 0)
        pred_tok = float(metrics.get("predictedTokensTotal") or 0)
        prompt_sec = float(metrics.get("promptSecondsTotal") or 0)
        pred_sec = float(metrics.get("predictedSecondsTotal") or 0)
        with _controller_gen_tps_lock:
            prev = _controller_token_counters.get(port)
            _controller_token_counters[port] = (prompt_tok, pred_tok, prompt_sec, pred_sec)
        if prev is not None and pred_tok > prev[1]:
            d_prompt_tok = max(0.0, prompt_tok - prev[0])
            d_pred_tok = max(0.0, pred_tok - prev[1])
            d_prompt_sec = max(0.0, prompt_sec - prev[2])
            d_pred_sec = max(0.0, pred_sec - prev[3])
            agg["generating"] = True
            agg["reqPromptTokens"] += int(round(d_prompt_tok))
            agg["reqGenTokens"] += int(round(d_pred_tok))
            agg["reqPromptMs"] += d_prompt_sec * 1000.0
            agg["reqGenMs"] += d_pred_sec * 1000.0
            if d_pred_sec > 0:
                agg["reqGenTps"] += d_pred_tok / d_pred_sec
            if d_prompt_sec > 0:
                agg["reqPromptTps"] += d_prompt_tok / d_prompt_sec
    if not agg["ok"]:
        return {"ok": False, "error": "no controller llama-server metrics", "generating": False}
    agg["reqPromptTps"] = round(agg["reqPromptTps"], 1)
    agg["reqGenTps"] = round(agg["reqGenTps"], 1)
    agg["reqPromptMs"] = int(agg["reqPromptMs"])
    agg["reqGenMs"] = int(agg["reqGenMs"])
    return agg

def record_controller_gen_tps(tokens, now):
    """Append one point per COMPLETED request: the token counter advanced since
    the last scrape, which llama.cpp only does at request completion. Each point
    carries that request's real throughput, token counts and durations. Idle
    ticks are dropped, so the chart plots real per-request points connected
    across gaps — no fake plateau."""
    if not isinstance(tokens, dict) or not tokens.get("generating"):
        return
    with _controller_gen_tps_lock:
        _controller_gen_tps.append({
            "t": int(now),
            "promptTps": float(tokens.get("reqPromptTps") or 0),
            "genTps": float(tokens.get("reqGenTps") or 0),
            "promptTokens": int(tokens.get("reqPromptTokens") or 0),
            "genTokens": int(tokens.get("reqGenTokens") or 0),
            "promptMs": int(tokens.get("reqPromptMs") or 0),
            "genMs": int(tokens.get("reqGenMs") or 0),
        })
        if len(_controller_gen_tps) > CONTROLLER_GEN_TPS_MAX:
            del _controller_gen_tps[:len(_controller_gen_tps) - CONTROLLER_GEN_TPS_MAX]

def controller_gen_tps_samples():
    """Per-request token series shaped like monitor samples so the chart
    renderer consumes it unchanged. promptTokensPerSecond/predictedTokensPerSecond
    are the REAL per-request rates (Δtokens/Δsec); the extra fields drive the
    hover tooltip (size + duration of each request)."""
    with _controller_gen_tps_lock:
        rows = list(_controller_gen_tps)
    return [{"time": r["t"], "tokens": {
        "promptTokensPerSecond": r["promptTps"],
        "predictedTokensPerSecond": r["genTps"],
        "promptTokens": r["promptTokens"],
        "genTokens": r["genTokens"],
        "promptMs": r["promptMs"],
        "genMs": r["genMs"],
    }} for r in rows]
