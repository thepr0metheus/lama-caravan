"""The idle probe: asks every backup exit whether it is alive while no traffic says so.

Traffic keeps a verdict fresh on its own (caravan/proxy/output_health.py). An
exit nobody has used for VERDICT_TTL_SECONDS gets one small request instead —
GET /health on a cell, a one-token completion on a cloud block — so that the
backup node knows where the next request should go BEFORE it arrives, and the
board can draw it. A cloud probe costs a request against the account; that is
the price of knowing, and it is paid only while the exit is idle.
"""
import http.client
import json
import threading
import time
from urllib.parse import urlsplit

from caravan.proxy.cloud_auth import (
    CLOUD_PROVIDER_AUTH, load_cloud_account, load_cloud_provider, load_provider_secret,
)
from caravan.proxy.config import current_config
from caravan.proxy.graph import PLAIN_REQUEST_CTX, chain_exit, resolve_graph
from caravan.proxy.output_health import output_health, output_id_of_ref
from caravan.proxy.translate import (
    _chat_to_anthropic_body, _chat_to_responses_body, _extract_chatgpt_account_id, rewrite_model_in_body,
)

PROBE_INTERVAL_SECONDS = 30
PROBE_TIMEOUT_SECONDS = 8
# The request a cloud probe sends: one token, the cheapest answer that proves
# the account still serves this model.
_PROBE_CHAT = {"messages": [{"role": "user", "content": "hi"}], "max_tokens": 1, "stream": False}


def onerror_exits(config):
    """Every backup node's two exits, resolved THROUGH the graph to output ids.

    An exit may point at another rule node — on production the main exit goes
    into a queue — and the question this answers is about the model at the end
    of that chain: which output to probe, which verdict to read, whether a dead
    main can be skipped. Each entry therefore carries both: the edge's own ref
    (the cable, unchanged) and the terminal output plus the nodes crossed.
    None means the chain cannot be named — unwired, or decided by a node whose
    branch is drawn at request time (see graph.CHAIN_DECIDABLE).
    """
    found = []
    for router in config.get("routers") or []:
        graph = router.get("graph") if isinstance(router.get("graph"), dict) else None
        if not graph:
            continue
        edges = [e for e in (graph.get("edges") or []) if isinstance(e, dict)]
        outputs = {str(o.get("id")): o for o in (router.get("outputs") or []) if isinstance(o, dict)}
        names = {oid: str(o.get("name") or oid) for oid, o in outputs.items()}
        policy = config.get("policy") if isinstance(config.get("policy"), dict) else {}
        for node in graph.get("nodes") or []:
            if not isinstance(node, dict) or node.get("type") != "onError":
                continue
            nid = str(node.get("id") or "")
            cfg = node.get("config") if isinstance(node.get("config"), dict) else {}
            outs = [e for e in edges if str(e.get("from")) == f"rule:{nid}"]
            by_id = {str(e.get("id")): e for e in outs}
            main = by_id.get(str(cfg.get("mainEdge"))) or next((e for e in outs if str(e.get("id")) != str(cfg.get("rescueEdge"))), None)
            rescue = by_id.get(str(cfg.get("rescueEdge")))
            row = {"node": nid, "router": str(router.get("id") or "")}
            for side, edge in (("main", main), ("backup", rescue)):
                ref = (edge or {}).get("to")
                target, chain = chain_exit(graph, ref, outputs, dict(PLAIN_REQUEST_CTX), policy)
                oid = output_id_of_ref(target)
                row[side] = oid
                row[f"{side}Ref"] = str(ref) if ref else None
                row[f"{side}Chain"] = chain
                row[f"{side}Name"] = names.get(oid) if oid else None
            found.append(row)
    return found


def outputs_by_id(config):
    table = {}
    for router in config.get("routers") or []:
        for out in router.get("outputs") or []:
            if isinstance(out, dict) and out.get("id"):
                table[str(out.get("id"))] = out
    return table


def _failure_text(status, body):
    """The provider's own words from an error body, or the body's head; the kind carries the status."""
    text = ""
    try:
        data = json.loads(body or b"")
        err = data.get("error") if isinstance(data, dict) else None
        if isinstance(err, dict):
            text = str(err.get("message") or err.get("code") or err.get("type") or "")
        elif isinstance(err, str):
            text = err
    except Exception:
        pass
    if not text:
        text = (body or b"")[:160].decode("utf-8", "replace").strip()
    return text[:200]


def _probe_cell(output, timeout):
    """A cell's own liveness path: llama.cpp and vLLM both answer GET /health."""
    host = str(output.get("upstreamHost") or "127.0.0.1")
    port = int(output.get("upstreamPort") or 0)
    if not port:
        return (False, None, "config", "no upstream port")
    try:
        conn = http.client.HTTPConnection(host, port, timeout=timeout)
        try:
            conn.request("GET", "/health", headers={"Host": f"{host}:{port}", "Connection": "close"})
            resp = conn.getresponse()
            body = resp.read(2000)
            status = resp.status
        finally:
            conn.close()
    except Exception as exc:
        return (False, None, "connect", f"connect failed: {exc}"[:200])
    if status == 200:
        return (True, 200, "", "")
    if status == 503:
        return (False, 503, "loading", _failure_text(503, body))
    return (False, status, f"http {status}", _failure_text(status, body))


def _probe_cloud(output, timeout):
    """One-token completion through the same headers and translations real traffic uses."""
    provider_id = str(output.get("providerId") or "")
    provider = load_cloud_provider(provider_id) if provider_id else load_cloud_account(output.get("accountId"))
    if not provider:
        return (False, None, "config", "cloud provider not configured")
    model = str(provider.get("model") or "")
    if not model:
        # An account passthrough pins no model: there is nothing one request could prove.
        return (None, None, "", "")
    auth_pair = load_provider_secret(provider)
    if not auth_pair:
        return (False, None, "config", "cloud account missing credential")
    base = urlsplit(provider.get("baseUrl") or "")
    if not base.hostname:
        return (False, None, "config", "cloud account baseUrl invalid")
    is_subscription = (str(provider.get("accountType") or "") == "openai-subscription"
                       or "chatgpt.com" in str(provider.get("baseUrl") or ""))
    use_tls = base.scheme != "http"
    port = base.port or (443 if use_tls else 80)
    chat = json.dumps({"model": model, **_PROBE_CHAT}).encode("utf-8")
    headers = {"Host": base.netloc, "Connection": "close", "X-Agent-Proxy": "output-probe",
               "Content-Type": "application/json"}
    if is_subscription:
        body, _model = _chat_to_responses_body(chat, model)
        token = auth_pair[1][7:]
        headers["Authorization"] = auth_pair[1]
        headers["chatgpt-account-id"] = _extract_chatgpt_account_id(token) or ""
        headers["originator"] = "pi"
        headers["OpenAI-Beta"] = "responses=experimental"
        headers["Accept"] = "text/event-stream"
        path = "/backend-api/codex/responses"
    elif str(provider.get("type")) == "anthropic":
        auth = CLOUD_PROVIDER_AUTH.get("anthropic", CLOUD_PROVIDER_AUTH["custom"])
        headers.update(auth.get("extraHeaders") or {})
        headers[auth_pair[0]] = auth_pair[1]
        headers["Accept"] = "application/json"
        body = _chat_to_anthropic_body(chat, model)
        path = base.path.rstrip("/") + "/messages"
    else:
        auth = CLOUD_PROVIDER_AUTH.get(str(provider.get("type")), CLOUD_PROVIDER_AUTH["custom"])
        headers.update(auth.get("extraHeaders") or {})
        headers[auth_pair[0]] = auth_pair[1]
        headers["Accept"] = "application/json"
        body = rewrite_model_in_body(chat, model)
        path = base.path.rstrip("/") + "/chat/completions"
    headers["Content-Length"] = str(len(body))
    try:
        conn = (http.client.HTTPSConnection if use_tls else http.client.HTTPConnection)(base.hostname, port, timeout=timeout)
        try:
            conn.request("POST", path, body=body, headers=headers)
            resp = conn.getresponse()
            status = resp.status
            snippet = resp.read(4000)
        finally:
            conn.close()
    except Exception as exc:
        return (False, None, "connect", f"connect failed: {exc}"[:200])
    if status < 400:
        return (True, status, "", "")
    return (False, status, f"http {status}", _failure_text(status, snippet))


def probe_output(output, timeout=PROBE_TIMEOUT_SECONDS):
    """(ok, status, kind, message) for one output; ok=None when nothing can be proved."""
    if not isinstance(output, dict):
        return (False, None, "config", "unknown output")
    if str(output.get("upstreamType") or "llama") == "cloud":
        return _probe_cloud(output, timeout)
    return _probe_cell(output, timeout)


def probe_pass(config=None, now=None, timeout=PROBE_TIMEOUT_SECONDS):
    """Probe every backup exit whose verdict is stale; returns the ids probed."""
    config = config if config is not None else current_config()
    policy = config.get("policy") if isinstance(config.get("policy"), dict) else {}
    try:
        ttl = int(policy.get("outputProbeSeconds", output_health.ttl_seconds))
    except (TypeError, ValueError):
        ttl = output_health.ttl_seconds
    if ttl <= 0:
        return []
    output_health.ttl_seconds = ttl
    wanted = []
    for exit_ in onerror_exits(config):
        for key in ("main", "backup"):
            if exit_[key] and exit_[key] not in wanted:
                wanted.append(exit_[key])
    table = outputs_by_id(config)
    probed = []
    for output_id in output_health.stale_ids(wanted, now):
        ok, status, kind, message = probe_output(table.get(output_id), timeout)
        if ok is None:
            continue
        if ok:
            output_health.note_ok(output_id, source="probe", now=now)
        else:
            output_health.note_error(output_id, status=status, kind=kind, message=message, source="probe", now=now)
        probed.append(output_id)
    return probed


def onerror_next_map(config, now=None):
    """Per backup node: which exit the next request takes, and why — for the board."""
    result = {}
    for exit_ in onerror_exits(config):
        nxt, reason = output_health.next_exit(exit_["main"], exit_["backup"], now)
        row = {k: v for k, v in exit_.items() if k != "node"}
        row.update({"next": nxt, "reason": reason})
        result[exit_["node"]] = row
    return result


def probe_loop():
    """Daemon: a pass every PROBE_INTERVAL_SECONDS; the state file is rewritten when a verdict changed."""
    from caravan.proxy.state import write_state
    while True:
        time.sleep(PROBE_INTERVAL_SECONDS)
        try:
            if probe_pass():
                write_state()
        except Exception:
            pass


def start_probe_thread():
    thread = threading.Thread(target=probe_loop, name="output-probe", daemon=True)
    thread.start()
    return thread
