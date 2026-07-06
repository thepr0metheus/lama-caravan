"""llama-server telemetry primitives: fetch and parse /metrics, /health, /props."""
from caravan.admin.config_builder import parse_config
from caravan.common.fetch import fetch_text


def parse_llamacpp_metrics(metrics_text):
    metrics = {}
    wanted = {
        "llamacpp:requests_processing",
        "llamacpp:requests_deferred",
        "llamacpp:prompt_tokens_seconds",
        "llamacpp:predicted_tokens_seconds",
        "llamacpp:kv_cache_usage_ratio",
        # Cumulative counters — used to detect that a request COMPLETED (the
        # counters only advance at completion) and to derive that request's
        # exact size and duration from the deltas. NB the *_seconds gauges above
        # are LIFETIME averages (total/seconds), useless for one request; the
        # real per-request throughput is Δtokens / Δseconds from these counters.
        "llamacpp:prompt_tokens_total",
        "llamacpp:prompt_seconds_total",
        "llamacpp:tokens_predicted_total",
        "llamacpp:tokens_predicted_seconds_total",
    }
    for line in metrics_text.splitlines():
        if line.startswith("#") or " " not in line:
            continue
        key, value = line.split(None, 1)
        if key not in wanted:
            continue
        try:
            metrics[key] = float(value.split()[0])
        except Exception:
            metrics[key] = value.split()[0]
    return metrics

def runtime_metrics_sample(port=None):
    try:
        if not port:
            port = parse_config().get("PORT") or "8080"
        # fetch_text returns "ERROR: ..." on failure instead of raising. A busy
        # llama-server (mid-generation, saturated GPU) can be slow to answer
        # /metrics, so give it headroom and treat a failed/timed-out scrape as
        # not-ok — otherwise the hardcoded ok:True below turns the parsed-empty
        # default into a fake 0 that flattens the live t/s and its sparkline.
        text = fetch_text(f"http://127.0.0.1:{port}/metrics", timeout=3)
        if text.startswith("ERROR"):
            return {"ok": False, "error": text}
        metrics = parse_llamacpp_metrics(text)
        if ("llamacpp:prompt_tokens_seconds" not in metrics
                and "llamacpp:predicted_tokens_seconds" not in metrics):
            return {"ok": False, "error": "metrics unavailable"}
        return {
            "ok": True,
            "promptTokensPerSecond": metrics.get("llamacpp:prompt_tokens_seconds", 0),
            "predictedTokensPerSecond": metrics.get("llamacpp:predicted_tokens_seconds", 0),
            "requestsProcessing": metrics.get("llamacpp:requests_processing", 0),
            "requestsDeferred": metrics.get("llamacpp:requests_deferred", 0),
            "kvCacheUsageRatio": metrics.get("llamacpp:kv_cache_usage_ratio", 0),
            "promptTokensTotal": metrics.get("llamacpp:prompt_tokens_total", 0),
            "promptSecondsTotal": metrics.get("llamacpp:prompt_seconds_total", 0),
            "predictedTokensTotal": metrics.get("llamacpp:tokens_predicted_total", 0),
            "predictedSecondsTotal": metrics.get("llamacpp:tokens_predicted_seconds_total", 0),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def vllm_metrics_sample(port):
    """vLLM's Prometheus /metrics, the card-worthy subset: active/queued
    requests and (when the build exports them) the rolling throughputs.
    Lines carry {model_name=…} labels, hence startswith matching."""
    wanted = ("vllm:num_requests_running", "vllm:num_requests_waiting",
              "vllm:avg_generation_throughput_toks_per_s",
              "vllm:avg_prompt_throughput_toks_per_s")
    try:
        text = fetch_text(f"http://127.0.0.1:{port}/metrics", timeout=3)
        if text.startswith("ERROR"):
            return {"ok": False, "error": text}
        vals = {}
        for line in text.splitlines():
            if line.startswith("#"):
                continue
            for name in wanted:
                if line.startswith(name):
                    try:
                        vals[name] = float(line.rsplit(None, 1)[-1])
                    except (ValueError, IndexError):
                        pass
        if not vals:
            return {"ok": False, "error": "no vllm metrics"}
        return {"ok": True,
                "requestsRunning": int(vals.get("vllm:num_requests_running", 0)),
                "requestsWaiting": int(vals.get("vllm:num_requests_waiting", 0)),
                "genTps": vals.get("vllm:avg_generation_throughput_toks_per_s"),
                "promptTps": vals.get("vllm:avg_prompt_throughput_toks_per_s")}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def runtime_phase(service, runtime):
    active_state = service.get("ActiveState") or "unknown"
    sub_state = service.get("SubState") or ""
    pid = service.get("MainPID") or "0"
    health = runtime.get("health") if isinstance(runtime, dict) else {}
    props = runtime.get("props") if isinstance(runtime, dict) else {}
    models = runtime.get("models") if isinstance(runtime, dict) else {}
    health_ok = isinstance(health, dict) and health.get("status") == "ok"
    props_ok = isinstance(props, dict) and props.get("ok") is not False and "error" not in props
    models_ok = isinstance(models, dict) and (models.get("data") or models.get("models"))
    error = ""
    for item in (health, props, models):
        if isinstance(item, dict) and item.get("error"):
            error = str(item.get("error"))
            break
    if not service.get("ok"):
        return {"phase": "unknown", "label": "admin cannot read service", "kind": "bad", "detail": service.get("error") or "systemctl --user failed"}
    if active_state == "failed":
        return {"phase": "failed", "label": "failed", "kind": "bad", "detail": error or sub_state}
    if active_state != "active":
        return {"phase": "stopped", "label": active_state, "kind": "bad", "detail": sub_state}
    if health_ok or props_ok or models_ok:
        return {"phase": "running", "label": "running", "kind": "good", "detail": "HTTP ready"}
    if pid and pid != "0":
        if "503" in error or "Service Unavailable" in error:
            return {"phase": "loading", "label": "loading model", "kind": "warn", "detail": error}
        return {"phase": "starting", "label": "starting", "kind": "warn", "detail": error or "waiting for HTTP"}
    return {"phase": "starting", "label": "starting", "kind": "warn", "detail": error or "waiting for process"}
