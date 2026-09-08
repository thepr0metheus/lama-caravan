"""ProxyHandler: the per-port HTTP request handler — route resolution, queue
admission, upstream forwarding (llama or cloud with protocol translation),
response relay and event logging."""
import hmac
import http.client
import json
import select
import socket
import threading
import time
import uuid as _uuid
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlsplit

from caravan.common.request_kind import is_inference_request
from caravan.common.context_window import served_window, effective_window, route_window_inputs
from caravan.proxy.cloud_auth import (
    CLOUD_PROVIDER_AUTH,
    load_cloud_account,
    load_cloud_provider,
    provider_secret_present,
    load_provider_secret,
)
from caravan.proxy.config import current_config, live_route_for_port
from caravan.proxy.graph import PLAIN_REQUEST_CTX, apply_router, apply_router_spill
from caravan.proxy.events import write_proxy_event
from caravan.proxy.output_health import output_health
from caravan.proxy.paths import BODY_CAPTURE_LIMIT, DEFAULT_POLICY, HOP_HEADERS, STREAM_DONE_MARKER
from caravan.proxy.queue_admission import (
    ProxyClientDisconnected,
    ProxyCloudError,
    ProxyCloudFallback,
    ProxyQueueSpill,
    ProxyRequestBlocked,
    ProxyRequestStopped,
    active_control_stop_reason,
    keepalive_sse_bytes,
    register_active_control,
    stop_requested,
    unregister_active_control,
    wait_for_proxy_slot,
)
from caravan.proxy.runtime import admitted_requests, queue_condition
from caravan.proxy.state import add_active, finish_active, update_active
from caravan.proxy.summarize import (
    parse_json_bytes,
    request_summary,
    response_summary,
    stream_summary_from_line,
)
from caravan.proxy.translate import (
    _anthropic_to_completions_json,
    _chat_to_anthropic_body,
    _chat_to_responses_body,
    _responses_passthrough_body,
    is_responses_request,
    iter_responses_passthrough,
    _extract_chatgpt_account_id,
    _iter_anthropic_as_completions_sse,
    _iter_responses_as_completions_sse,
    classify_proxy_error,
    rewrite_model_in_body,
)


# Only an inference request earns a health verdict from an HTTP status and a
# replay on the backup exit: a client's discovery probe — GET /api/v1/models,
# /v1/internal/model/info, "/" — draws a 404 from llama.cpp for a path it never
# had, which is no word about the model, yet it once marked a healthy cell dead
# and sent the probe to a cloud block that answered 405 (2026-09-06). A connect
# failure stays a verdict for any request: a refused socket is the exit's own
# fact. The rule itself lives in caravan/common/request_kind.py — the
# controller's incident panel judges the same answers by the same words.


def _rescue_chain_text(trail, skipped):
    """The exits a request passed before the one answering now, as one line.

    Replayed exits come from the rescue trail with their status and words;
    exits skipped on a fresh dead verdict come first, since they were never
    asked. Empty when the request went straight to its answer.
    """
    parts = [f"{dead}: skipped, known dead" for dead in (skipped or [])]
    for hop in (trail or []):
        parts.append(f"{hop.get('from')}: {hop.get('status')}"
                     + (f" {hop.get('reason')}" if hop.get("reason") else ""))
    return "; ".join(parts)


def _upstream_failure_summary(status, body):
    """(human reason, short kind) for an upstream that answered with an error.

    Providers put the reason in the body and each nests it differently — OpenAI
    uses {"error":{"message","code"}} for some failures, a bare {"error":"…"}
    for others, {"detail":"…"} at the edge, and a {"code":"…_circuit_open"} when
    their own breaker trips. Anything unparsed still beats an empty string, so
    the raw text is the fallback rather than a discard.
    """
    text = str(body or "").strip()
    kind = ""
    reason = ""
    if text.startswith("{") or text.startswith("["):
        try:
            data = json.loads(text)
        except Exception:
            data = None
        if isinstance(data, dict):
            err = data.get("error")
            if isinstance(err, dict):
                reason = str(err.get("message") or "").strip()
                kind = str(err.get("code") or err.get("type") or "").strip()
            elif isinstance(err, str):
                reason = err.strip()
            reason = reason or str(data.get("detail") or data.get("message") or "").strip()
            kind = kind or str(data.get("code") or "").strip()
    if not reason:
        reason = " ".join(text.split())[:300]
    if not kind:
        kind = f"http_{int(status)}"
    return reason, kind[:60]


def _publish_context_window(body, route):
    """Publish each entry's context window under the two widely-read names.

    The clients that read a context window disagree on the name as much as the
    servers do — Continue reads `max_model_len`, LibreChat reads
    `context_length`, and llama.cpp's own `meta.n_ctx` is read by none of the
    nine surveyed — so the figure is published under both, beside the nested
    one rather than instead of it: the nested value is a fact about the running
    server and is never rewritten.

    The figure is `effective_window(limit, served)`: the operator's limit for
    this port against what the server itself reported for the entry, the
    smaller of the two unless the operator chose the model's own. An entry with
    neither keeps no size, because a guessed context is worse than an absent one
    (docs/why.md). Without a limit an upstream's own top-level value is left
    alone — this republishes what the server said, it does not correct it; with
    a limit the operator's decision is the answer and both names carry it.

    Returns the re-serialised body, or the original bytes untouched when it is
    not a model list this can safely read.
    """
    try:
        payload = json.loads(body)
    except Exception:
        return body
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        return body
    limit, prefer_model = route_window_inputs(route)
    touched = False
    for entry in payload["data"]:
        if not isinstance(entry, dict):
            continue
        window = effective_window(limit, served_window(entry), prefer_model)
        if window is None:
            continue
        for name in ("context_length", "max_model_len"):
            if limit is None and name in entry:
                continue
            if entry.get(name) != window:
                entry[name] = window
                touched = True
    if not touched:
        return body
    return json.dumps(payload).encode("utf-8")


# Paths a client tries before it knows what kind of server answers this port:
# llama.cpp's /props and /version, Ollama's /api/tags and /api/show. A cloud
# bridge has none of them — and the subscription branch sends EVERY path to
# /backend-api/codex/responses, so a GET arrived there as "Method Not Allowed"
# and POST /api/show reached the paid API as a request with no input at all.
# 152 such answers in one production day painted the route's error panel red
# while every real completion succeeded. The port answers for itself now: 404
# is the true statement — this server has no such endpoint — and it costs no
# upstream call. Only for a CLOUD upstream: on a llama route each of these
# belongs to the upstream and stays forwarded.
CLOUD_ABSENT_PATHS = frozenset({
    "/props", "/v1/props", "/version", "/api/version",
    "/api/tags", "/api/show", "/api/ps", "/api/v1/models",
})


def _route_model_name(route):
    """The name THIS port advertises its model under, or "".

    A client asks `/v1/models` and looks up ITS OWN id there. Not finding it,
    it falls back to its built-in default (256k for one of them), and a
    window honestly published under the upstream's name never reaches it at
    all. The name is set by the operator on the route and arrives here as the
    same copy as the window.

    The open lock (`modelNameAuto`) lifts the operator's name without erasing
    it: the port advertises the model under whatever name it calls itself —
    the upstream's on a llama output, the block's model on a cloud one. The
    operator asked specifically to lift it, not to forget it: closing the
    lock again needs no retyping the name.
    """
    if (route or {}).get("modelNameAuto"):
        return ""
    return str((route or {}).get("modelName") or "").strip()


#: The fields where llama.cpp names the model in the Ollama-compatible
#: `models` list. Both are the same name, and both must be renamed.
_OLLAMA_NAME_FIELDS = ("name", "model")


def _rename_models(body, name):
    """Rename the models in a `/v1/models` response to the advertised name.

    Renames a SINGLE entry: a port advertises one model, and if the upstream
    returned a list, we have no right to pick on the client's behalf which
    one is "the" model — the response is then left as-is.

    There are TWO lists in the response: OpenAI's `data` and the
    Ollama-compatible `models`, and they name the same model twice. Only the
    first used to be renamed, so a closed lock held the name for only half
    of its readers: a client polling the port the Ollama way (LAN scanners do
    this) saw the model's filename instead. Found live on 2026-09-07 at
    :23001 — the card showed `hemi-proxy` with the lock closed, while
    `models[0].name` reported `qwen3.8-27b-q4`.

    The old name isn't lost: llama.cpp puts it in `aliases`, and a request
    against it keeps working. The lock changes HOW the port calls itself, not
    what it answers to.
    """
    if not name:
        return body
    try:
        payload = json.loads(body.decode("utf-8"))
    except Exception:
        return body
    if not isinstance(payload, dict):
        return body
    changed = False
    data = payload.get("data")
    if isinstance(data, list) and len(data) == 1 and isinstance(data[0], dict):
        if data[0].get("id") != name:
            data[0]["id"] = name
            changed = True
    models = payload.get("models")
    if isinstance(models, list) and len(models) == 1 and isinstance(models[0], dict):
        for field in _OLLAMA_NAME_FIELDS:
            if field in models[0] and models[0][field] != name:
                models[0][field] = name
                changed = True
    if not changed:
        return body
    return json.dumps(payload).encode("utf-8")


def _cloud_model_entry(route):
    """The one model a cloud-routed port serves, in OpenAI's model shape.

    Shared by /v1/models and /v1/models/<id> so the two can never disagree
    about what this port answers with.
    """
    provider = load_cloud_provider(route.get("providerId") or "")
    entry = {
        "id": (provider.get("model") if provider else None) or route.get("label") or "default",
        "object": "model",
        "created": int(time.time()),
        "owned_by": (provider.get("type") if provider else None) or "cloud",
    }
    # The window the block stands for — stated by the operator on the model
    # block, or the provider's reported figure when they chose that (both
    # resolved by load_cloud_provider) — against THIS port's own limit, by the
    # same rule the llama path applies. Omitted when neither knows: several
    # providers publish no window at all, and a guessed one is worse than none
    # (docs/why.md). Applied here rather than at the caller so that /v1/models
    # and retrieve-model can never disagree: they once answered 32768 to a list
    # and 200000 to a lookup of the same model.
    limit, prefer_model = route_window_inputs(route)
    window = effective_window(limit, (provider or {}).get("contextLength"), prefer_model)
    if window is not None:
        entry["context_length"] = entry["max_model_len"] = window
    # The operator's name wins over the block's: a client looks for ITS id.
    name = _route_model_name(route)
    if name:
        entry["id"] = name
    return entry


class ProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        return

    @property
    def route(self):
        return self.server.route

    @property
    def agent_name(self):
        return self.route["label"]

    def _api_key_ok(self, route):
        """Data-plane auth: when the route carries an apiKey, the request must
        present it (Authorization: Bearer …, or x-api-key). Empty key = open
        (the default — LAN routes keep working until the operator opts in)."""
        want = str(route.get("apiKey") or "")
        if not want:
            return True
        auth = self.headers.get("Authorization") or ""
        got = auth[7:].strip() if auth.startswith("Bearer ") else (self.headers.get("x-api-key") or "").strip()
        return bool(got) and hmac.compare_digest(got, want)

    def _reject_unauthorized(self, route, request_id):
        payload = json.dumps({"error": {"message": f"proxy {route.get('label') or ''} requires an API key "
                                                   "(Authorization: Bearer <key>)", "type": "unauthorized"}}).encode("utf-8")
        try:
            self._send_bytes(401, payload)
        except Exception:
            pass
        write_proxy_event("blocked", route_label=route.get("label") or "", request_id=request_id,
                          item={"id": request_id, "route": route.get("label") or "",
                                "port": route.get("port"), "reason": "unauthorized:bad-api-key",
                                "client": self.client_address[0] if self.client_address else ""})

    def proxy(self):
        request_id = f"{time.time_ns()}-{threading.get_ident()}"
        started = time.time()
        length = int(self.headers.get("Content-Length", "0") or "0")
        body = self.rfile.read(length) if length else None
        client = self.client_address[0] if self.client_address else ""
        parsed = urlsplit(self.path)
        path = parsed.path + (f"?{parsed.query}" if parsed.query else "")
        req_summary = request_summary(body, self.headers)
        route = live_route_for_port(self.route.get("port")) or self.route
        if not self._api_key_ok(route):
            self._reject_unauthorized(route, request_id)
            return
        # Resolve the actual upstream through this proxy's router (routing layer).
        # ctx.model lets a byModel graph node branch on the requested model.
        route = apply_router(route, current_config(), ctx={"model": req_summary.get("model"), "maxTokens": req_summary.get("maxTokens"), "audio": ("/audio/" in parsed.path), "embeddings": parsed.path.rstrip("/").endswith("/embeddings")})
        route["label"] = route.get("label") or self.agent_name
        # Unassigned / unroutable proxy → 503 immediately (no queue, no upstream).
        if route.get("unrouted") and str(route.get("upstreamType") or "llama") != "cloud":
            reason = route["unrouted"]
            payload503 = json.dumps({"error": {"message": f"proxy {route['label']} is not routed to a router output ({reason})", "type": "unrouted"}}).encode("utf-8")
            try:
                self._send_bytes(503, payload503)
            except Exception:
                pass
            write_proxy_event("blocked", route_label=route["label"], request_id=request_id,
                              item={"id": request_id, "route": route["label"], "port": route.get("port"), "reason": f"unrouted:{reason}"})
            return
        active = {
            "id": request_id,
            "method": self.command,
            "path": parsed.path,
            "client": client,
            "startedAt": int(started),
            "route": route["label"],
            "port": route.get("port"),
            "upstream": f"{route['upstreamHost']}:{route['upstreamPort']}",
            # upstreamType/providerId let the admin colour the right output cable
            # (cloud upstreams collide on host:port, so providerId disambiguates).
            "upstreamType": str(route.get("upstreamType") or "llama"),
            "providerId": str(route.get("providerId") or ""),
            "routedOutputId": str(route.get("routedOutputId") or ""),
            "routedOutputName": str(route.get("routedOutputName") or ""),
            "request": req_summary,
            "bytes": 0,
            "chunks": 0,
            "phase": "queued",
            "queue": {"queuedMs": 0, "position": None},
            "priority": int(route.get("priority") or 0),
        }
        add_active(str(route["port"]), active)
        write_proxy_event("received", route_label=route["label"], request_id=request_id, item=active)
        queue = {"queuedMs": 0, "preempted": ""}
        route_is_cloud = str(route.get("upstreamType") or "llama") == "cloud"
        cloud_fallback_provider_id = None

        # ── SSE keep-alive setup ───────────────────────────────────────────────
        # For streaming requests going to a local llama slot, send HTTP 200 +
        # SSE headers immediately so we can write ": keepalive" comments while
        # the request waits in queue, preventing the client's read-timeout from
        # firing (~150s for OpenClaw/Claude Code) before a slot is available.
        headers_sent = False
        keepalive_writer = None
        body_obj = parse_json_bytes(body)
        is_request_streaming = bool(body_obj.get("stream")) if isinstance(body_obj, dict) else False
        if is_request_streaming and not route_is_cloud:
            try:
                self.send_response(200, "OK")
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("X-Accel-Buffering", "no")
                self.send_header("Connection", "close")
                self.end_headers()
                headers_sent = True
                _wfile = self.wfile
                _ka_model = str(body_obj.get("model") or "") if isinstance(body_obj, dict) else ""
                def keepalive_writer():
                    # Real (empty-delta) data event, not a bare comment — see keepalive_sse_bytes.
                    _wfile.write(keepalive_sse_bytes(_ka_model))
                    _wfile.flush()
            except Exception:
                headers_sent = False
                keepalive_writer = None

        def _probe_client_gone():
            # Probe the client socket without writing: after the request body is
            # read, the socket goes readable again only on EOF/RST (agents never
            # pipeline) — so readable + empty MSG_PEEK means the client left.
            # Works in every phase, even before any response headers exist.
            try:
                readable, _, _ = select.select([self.connection], [], [], 0)
                if not readable:
                    return False
                return self.connection.recv(1, socket.MSG_PEEK) == b""
            except Exception:
                return True

        try:
            if route_is_cloud:
                cloud_mode = str(route.get("mode") or "open").lower()
                if cloud_mode in ("paused", "drain"):
                    raise ProxyRequestBlocked(503, f"proxy route {route['label']} is {cloud_mode}", "blocked")
            # Queue + spill loop. A graph queue node may divert (spill) to another
            # output/queue when its spillPct fires; we re-resolve and re-queue there,
            # chaining across the fleet until admitted, cloud, or the chain is exhausted.
            spill_guard = 0
            while not route_is_cloud:
                spec = (route.get("queuePlan") or {}).get("spec")
                try:
                    queue = wait_for_proxy_slot(route, request_id, keepalive_writer=keepalive_writer, spec=spec,
                                                client_gone=_probe_client_gone)
                    break
                except ProxyQueueSpill as exc:
                    spill_guard += 1
                    newr = (apply_router_spill(route, current_config(), exc.spill_ref,
                                               ctx={"model": req_summary.get("model"), "maxTokens": req_summary.get("maxTokens"), "audio": ("/audio/" in parsed.path), "embeddings": parsed.path.rstrip("/").endswith("/embeddings")})
                            if exc.spill_ref else None)
                    if spill_guard > 8 or not newr or newr.get("unrouted"):
                        raise ProxyRequestBlocked(503, "queue spill target unroutable", "queue_timeout")
                    route = newr
                    route["label"] = route.get("label") or self.agent_name
                    # Propagate the absolute deadline so the next queue node uses
                    # remaining budget, not a fresh clientTimeoutSeconds.
                    if exc.deadline_epoch:
                        route["deadlineEpoch"] = exc.deadline_epoch
                    route_is_cloud = str(route.get("upstreamType") or "llama") == "cloud"
                    update_active(str(route["port"]), request_id, {
                        "upstream": f"{route['upstreamHost']}:{route['upstreamPort']}",
                        "upstreamType": str(route.get("upstreamType") or "llama"),
                        "providerId": str(route.get("providerId") or ""),
                        "spilledTo": route["label"],
                    })
                    write_proxy_event("queue_spill", route_label=route["label"], request_id=request_id,
                                      item=active, queuedMs=exc.queued_ms, spillRef=exc.spill_ref)
                    # Loop: a spill target may carry its own queue node (chained queues).
        except ProxyCloudFallback as exc:
            cloud_fallback_provider_id = exc.provider_id
            queue = {"queuedMs": exc.queued_ms, "preempted": "", "cloudFallback": True}
            write_proxy_event("cloud_fallback", route_label=route["label"], request_id=request_id,
                              item=active, queuedMs=exc.queued_ms, providerId=exc.provider_id)
        except ProxyClientDisconnected:
            # Client closed the connection while waiting in queue — nothing to
            # send; the queue loop already logged the slim probe event, this
            # writes the full terminal record.
            result = {
                "id": request_id, "method": self.command, "path": parsed.path,
                "client": client, "route": route["label"], "port": route.get("port"),
                "upstream": f"{route['upstreamHost']}:{route['upstreamPort']}",
                "upstreamHost": route.get("upstreamHost"), "upstreamPort": route.get("upstreamPort"),
                "upstreamType": str(route.get("upstreamType") or "llama"),
                "status": 0, "startedAt": int(started), "finishedAt": int(time.time()),
                "durationMs": round((time.time() - started) * 1000),
                "bytes": 0, "chunks": 0, "firstByteMs": None, "request": req_summary,
                "queue": {"queuedMs": round((time.time() - started) * 1000)},
                "response": {}, "stream": {},
                "error": "client disconnected while queued", "errorKind": "client_disconnected",
            }
            finish_active(str(route["port"]), request_id, result)
            write_proxy_event("client_disconnected_queued", route_label=route["label"],
                              request_id=request_id, item=result)
            return
        except ProxyRequestBlocked as exc:
            status = exc.status
            payload = json.dumps({"error": str(exc), "kind": exc.kind}).encode("utf-8")
            try:
                if headers_sent:
                    self._send_sse_error({"error": str(exc), "kind": exc.kind})
                else:
                    self._send_bytes(status, payload)
            except Exception:
                pass
            result = {
                "id": request_id,
                "method": self.command,
                "path": parsed.path,
                "client": client,
                "route": route["label"],
                "port": route.get("port"),
                "upstream": f"{route['upstreamHost']}:{route['upstreamPort']}",
                "upstreamHost": route.get("upstreamHost"),
                "upstreamPort": route.get("upstreamPort"),
                "upstreamType": str(route.get("upstreamType") or "llama"),
                "status": status,
                "startedAt": int(started),
                "finishedAt": int(time.time()),
                "durationMs": round((time.time() - started) * 1000),
                "bytes": 0,
                "chunks": 0,
                "firstByteMs": None,
                "request": req_summary,
                "queue": {"queuedMs": round((time.time() - started) * 1000)},
                "response": {},
                "stream": {},
                "error": str(exc),
                "errorKind": exc.kind,
            }
            finish_active(str(route["port"]), request_id, result)
            write_proxy_event("blocked", route_label=route["label"], request_id=request_id, item=result, status=status)
            return
        update_active(str(route["port"]), request_id, {"phase": "received", "queue": queue})
        with queue_condition:
            admitted_requests.discard(str(request_id))
            queue_condition.notify_all()
        status = 502
        bytes_out = 0
        error = ""
        error_kind = ""
        chunks = 0
        first_byte_ms = None
        response = {}
        stream = {"events": 0, "deltaTextChars": 0, "finishReasons": [], "usage": {}, "done": False}
        last_state_write = 0
        conn = None
        # ── Idle SSE heartbeat during forwarding ────────────────────────────────
        # The queue keepalive only covers the QUEUE wait. Once admitted, a slow upstream
        # (big-context prompt-processing / near-idle generation) can go many seconds with
        # no bytes to the client → its read-timeout fires → "Broken pipe". Extend the same
        # trick: a background thread writes ": keepalive" SSE comments whenever the client
        # has been idle for _hb_interval, until real tokens flow / the request ends. All
        # client writes share _wfile_lock so a heartbeat never splits a chunk.
        _wfile_lock = threading.Lock()
        _last_client_write = [time.time()]
        _sse_open = [bool(headers_sent)]
        _client_gone = [False]
        _hb_stop = threading.Event()
        _hb_interval = float((current_config().get("policy") or {}).get("queueKeepaliveSec") or 20)
        _hb_interval = max(5.0, min(_hb_interval, 30.0))

        def _on_client(fn):
            # Run one write to the CLIENT. A failure here is the only direct
            # observation this thread ever gets that the client is gone: the
            # heartbeat probe exists just for streaming requests, so for a plain
            # POST there is no other signal. Without this, the EPIPE from
            # writing to a vanished client fell through to the upstream-leg
            # branch and was recorded as the UPSTREAM dropping the connection —
            # the same false blame the kind was introduced to remove, pointing
            # the other way. Mark it as the heartbeat would, which also tears the
            # upstream socket down so the cell stops generating into the void.
            #
            # Both kinds of write go through here. The body goes through
            # _client_write; the response HEADERS go through end_headers(),
            # which is where the buffered header block first touches the socket
            # — and an agent that is killed usually dies while the cell is still
            # generating, so the headers are the write that fails. The first
            # version of this marking covered only the body and missed exactly
            # that, the common production case.
            try:
                return fn()
            except (BrokenPipeError, ConnectionResetError, OSError):
                _abort_for_client_gone()
                raise

        def _client_write(data):
            def _do():
                with _wfile_lock:
                    self.wfile.write(data)
                    self.wfile.flush()
                    _last_client_write[0] = time.time()
            _on_client(_do)

        # Our own reference to the upstream TCP socket: once the response headers
        # arrive, http.client detaches conn.sock (Connection: close), so tearing
        # the exchange down later must go through the socket itself.
        _up_sock = [None]

        def _abort_for_client_gone():
            # The client hung up. Don't just stop the heartbeat — kill the
            # upstream socket too, so llama.cpp cancels the slot instead of
            # generating into the void (the relay thread is blocked on
            # upstream.read* and would otherwise notice only on the next
            # real chunk write, after the whole answer was computed).
            _client_gone[0] = True
            _hb_stop.set()
            sck = _up_sock[0]
            try:
                if sck is not None:
                    # shutdown() before close(): close() alone does not unblock
                    # a recv() already parked on the socket in the relay thread.
                    try:
                        sck.shutdown(socket.SHUT_RDWR)
                    except Exception:
                        pass
                    sck.close()
                if conn is not None:
                    conn.close()
            except Exception:
                pass
            try:
                write_proxy_event("client_gone_probe", route_label=route["label"],
                                  request_id=request_id,
                                  elapsedSec=round(time.time() - started, 1),
                                  hadSock=sck is not None)
            except Exception:
                pass

        def _heartbeat_loop():
            while not _hb_stop.wait(2.0):
                if _probe_client_gone():
                    _abort_for_client_gone()
                    return
                if not _sse_open[0] or time.time() - _last_client_write[0] < _hb_interval:
                    continue
                try:
                    with _wfile_lock:
                        self.wfile.write(keepalive_sse_bytes(str((req_summary or {}).get("model") or "")))
                        self.wfile.flush()
                        _last_client_write[0] = time.time()
                except Exception:
                    _abort_for_client_gone()
                    return

        _hb_thread = None
        if is_request_streaming:
            _hb_thread = threading.Thread(target=_heartbeat_loop, daemon=True)
            _hb_thread.start()
        try:
            # ── Upstream leg loop ────────────────────────────────────────────
            # Normally one pass. An onError node in the graph gives the route a
            # rescue exit: when THIS leg fails (connect error or HTTP >= 400)
            # before a single response byte reached the client, the loop
            # re-resolves the route down the rescue edge and replays the same
            # request there. The SSE keepalive preamble does not count as
            # output — the backup's stream continues into the same open pipe.
            _rescue_refs = list(route.get("rescueRefs") or [])
            _rescue_hops = 0
            _rescue_trail = []
            # A discovery probe is answered by the exit it reached, as it came:
            # no replay elsewhere, no verdict from its status (see
            # caravan/common/request_kind.py).
            _inference_request = is_inference_request(self.command, parsed.path)
            if not _inference_request:
                _rescue_refs = []
            while True:
                _conn_exc = None
                upstream = None
                is_cloud = route_is_cloud or cloud_fallback_provider_id is not None
                is_subscription = False
                is_anthropic = False
                responses_passthrough = False
                responses_client_stream = True
                send_body = body
                completion_id = None
                subscription_model = None
                anthropic_model = None
                if is_cloud:
                    effective_provider_id = cloud_fallback_provider_id or route.get("providerId")
                    # A block id resolves to a specific model; otherwise route to the cloud
                    # account directly (passthrough — forward the client's requested model).
                    provider = (load_cloud_provider(effective_provider_id) if effective_provider_id
                                else load_cloud_account(route.get("cloudAccountId")))
                    if not provider:
                        raise ProxyCloudError("cloud provider not configured")
                    auth_pair = load_provider_secret(provider)
                    if not auth_pair:
                        raise ProxyCloudError("cloud account missing credential (API key or OAuth)")
                    base = urlsplit(provider.get("baseUrl") or "")
                    if not base.hostname:
                        raise ProxyCloudError("cloud account baseUrl invalid")
                    is_subscription = (
                        str(provider.get("accountType") or "") == "openai-subscription"
                        or "chatgpt.com" in str(provider.get("baseUrl") or "")
                    )
                    use_tls = base.scheme != "http"
                    cloud_port = base.port or (443 if use_tls else 80)
                    if use_tls:
                        conn = http.client.HTTPSConnection(base.hostname, cloud_port, timeout=600)
                    else:
                        conn = http.client.HTTPConnection(base.hostname, cloud_port, timeout=600)
                    register_active_control(request_id, route["label"], conn)
                    headers = {
                        key2: value for key2, value in self.headers.items()
                        if key2.lower() not in HOP_HEADERS and key2.lower() not in (
                            "host", "authorization", "x-api-key", "chatgpt-account-id",
                            "originator", "openai-beta", "accept",
                            # Exclude these — we set them explicitly to correct values below
                            "content-length", "content-type", "accept-encoding", "accept-language",
                        )
                    }
                    headers["Host"] = base.netloc
                    headers["Connection"] = "close"
                    headers["X-Agent-Proxy"] = route["label"]
                    headers["X-Agent-Proxy-Request-Id"] = request_id
                    if is_subscription:
                        model_override = provider.get("model") if str(provider.get("modelMode") or "rewrite") == "rewrite" else None
                        if is_responses_request(parsed.path, body):
                            # The client speaks Responses already (Codex CLI): the
                            # body goes through as written, and the stream comes
                            # back untranslated.
                            responses_passthrough = True
                            send_body, subscription_model, responses_client_stream = _responses_passthrough_body(body, model_override)
                        else:
                            # Translate a chat/completions request to the Responses API format
                            send_body, subscription_model = _chat_to_responses_body(body, model_override)
                        completion_id = "chatcmpl-" + str(_uuid.uuid4()).replace("-", "")[:24]
                        token = auth_pair[1][7:]  # strip "Bearer "
                        account_id = _extract_chatgpt_account_id(token) or ""
                        headers["Authorization"] = auth_pair[1]
                        headers["chatgpt-account-id"] = account_id
                        headers["originator"] = "pi"
                        headers["OpenAI-Beta"] = "responses=experimental"
                        headers["Accept"] = "text/event-stream"
                        headers["Content-Type"] = "application/json"
                        headers["Content-Length"] = str(len(send_body))
                        send_path = "/backend-api/codex/responses"
                    elif str(provider.get("type")) == "anthropic" and parsed.path.endswith("/chat/completions"):
                        is_anthropic = True
                        auth = CLOUD_PROVIDER_AUTH.get("anthropic", CLOUD_PROVIDER_AUTH["custom"])
                        headers.update(auth.get("extraHeaders") or {})
                        headers[auth_pair[0]] = auth_pair[1]
                        base_path = base.path.rstrip("/")
                        send_path = base_path + "/messages" + (f"?{parsed.query}" if parsed.query else "")
                        completion_id = "chatcmpl-" + str(_uuid.uuid4()).replace("-", "")[:24]
                        model_override = provider.get("model") if str(provider.get("modelMode") or "rewrite") == "rewrite" else None
                        anthropic_model = model_override or (json.loads(body).get("model") if body else None) or "claude-opus-4-8"
                        send_body = _chat_to_anthropic_body(body, model_override)
                        headers["Content-Type"] = "application/json"
                        headers["Content-Length"] = str(len(send_body))
                        headers["Accept"] = "application/json"
                    else:
                        auth = CLOUD_PROVIDER_AUTH.get(str(provider.get("type")), CLOUD_PROVIDER_AUTH["custom"])
                        headers.update(auth.get("extraHeaders") or {})
                        headers[auth_pair[0]] = auth_pair[1]
                        base_path = base.path.rstrip("/")
                        incoming = parsed.path
                        if base_path.endswith("/v1") and incoming.startswith("/v1"):
                            incoming = incoming[3:]
                        send_path = base_path + incoming + (f"?{parsed.query}" if parsed.query else "")
                        if str(provider.get("modelMode") or "rewrite") == "rewrite":
                            send_body = rewrite_model_in_body(body, provider.get("model"))
                        # The header filter above strips content-type/length and accept
                        # "to set them explicitly below" — the subscription/anthropic
                        # branches do, but this generic one never did: the cloud API got
                        # a JSON body with no Content-Type and answered "you must
                        # provide a model parameter". Restore them for ANY body,
                        # rewritten or passed through.
                        headers["Content-Type"] = self.headers.get("Content-Type") or "application/json"
                        if self.headers.get("Accept"):
                            headers["Accept"] = self.headers.get("Accept")
                        if send_body is not None:
                            headers["Content-Length"] = str(len(send_body))
                else:
                    conn = http.client.HTTPConnection(route["upstreamHost"], route["upstreamPort"], timeout=600)
                    register_active_control(request_id, route["label"], conn)
                    headers = {
                        key2: value for key2, value in self.headers.items()
                        if key2.lower() not in HOP_HEADERS and key2.lower() != "host"
                    }
                    headers["Host"] = f"{route['upstreamHost']}:{route['upstreamPort']}"
                    headers["Connection"] = "close"
                    headers["X-Agent-Proxy"] = route["label"]
                    headers["X-Agent-Proxy-Request-Id"] = request_id
                    headers["X-Forwarded-For"] = client
                    send_path = path
                update_active(str(route["port"]), request_id, {"phase": "upstream"})
                # Build cloud request metadata for logging
                cloud_meta = {}
                if is_cloud and send_body:
                    try:
                        req_payload = json.loads(send_body)
                        cloud_meta = {
                            "model": req_payload.get("model") or "",
                            "toolCount": len(req_payload.get("tools") or []),
                            "inputCount": len(req_payload.get("input") or req_payload.get("messages") or []),
                        }
                    except Exception:
                        pass
                # Log outgoing headers for cloud routes to aid debugging
                cloud_headers_debug = {k: (v if k.lower() != "authorization" else f"Bearer ...{str(v)[-8:]}") for k, v in headers.items()} if is_cloud else None
                write_proxy_event("upstream_started", route_label=route["label"], request_id=request_id, item=active, queue=queue, cloudMeta=cloud_meta or None, cloudHeaders=cloud_headers_debug)
                # ── Retry on llama "Loading model" 503 (brief window during startup) ─
                # Time-based: keep retrying every 3s for up to loadingModelWaitSec (default 60s).
                # The governing queue node wins; the global policy is the
                # fallback — the same precedence stickySlotSec already uses, so
                # one queue can wait out a slow-loading 70B while the rest of
                # the fleet keeps the short window.
                _lm_qspec = (route.get("queuePlan") or {}).get("spec") or {}
                _lm_node = _lm_qspec.get("loadingModelWaitSec")
                _lm_wait = float(_lm_node if _lm_node is not None
                                 else ((current_config().get("policy") or DEFAULT_POLICY)
                                       .get("loadingModelWaitSec") or 60))
                _lm_retry_delay = 3.0
                _lm_deadline = time.time() + _lm_wait
                _lm_attempt = 0
                upstream_error_body = ""
                upstream_error_raw = b""
                while True:
                    if _client_gone[0]:
                        raise ConnectionResetError("client disconnected during upstream wait")
                    try:
                        conn.request(self.command, send_path, body=send_body, headers=headers)
                        # Grab the raw socket now — getresponse() detaches conn.sock on
                        # Connection: close responses, and the abort path needs it.
                        _up_sock[0] = conn.sock
                        upstream = conn.getresponse()
                    except (ConnectionError, OSError, http.client.HTTPException) as exc:
                        # A dead upstream is as rescueable as an erroring one — but only
                        # while a rescue exit exists; otherwise keep the old behaviour.
                        # (_client_gone aborts tear this socket down on purpose — those
                        # must keep raising, not turn into a rescue.)
                        if not (_rescue_refs and _rescue_hops < 3 and bytes_out == 0
                                and not _client_gone[0]):
                            raise
                        _conn_exc = exc
                        status = 502
                        upstream_headers = {}
                        content_type = ""
                        is_event_stream = False
                        upstream_error_body = f"upstream connect failed: {exc}"
                        upstream_error_raw = b""
                        break
                    status = upstream.status
                    upstream_headers = dict(upstream.getheaders())
                    content_type = upstream_headers.get("Content-Type", "")
                    is_event_stream = content_type.lower().startswith("text/event-stream")
                    if status >= 400:
                        try:
                            upstream_error_raw = upstream.read(4096)
                            upstream_error_body = upstream_error_raw.decode("utf-8", errors="replace")
                        except Exception:
                            upstream_error_raw = b""
                    if (not is_cloud and status == 503
                            and b"Loading model" in upstream_error_raw
                            and time.time() < _lm_deadline):
                        _lm_attempt += 1
                        write_proxy_event("loading_model_retry", route_label=route["label"],
                                          request_id=request_id, attempt=_lm_attempt,
                                          retryDelaySec=_lm_retry_delay,
                                          remainingSec=round(_lm_deadline - time.time(), 1))
                        try:
                            conn.close()
                        except Exception:
                            pass
                        time.sleep(_lm_retry_delay)
                        conn = http.client.HTTPConnection(route["upstreamHost"], route["upstreamPort"], timeout=600)
                        register_active_control(request_id, route["label"], conn)
                        upstream_error_raw = b""
                        upstream_error_body = ""
                        continue
                    break
                update_active(str(route["port"]), request_id, {
                    "phase": "streaming" if is_event_stream else "reading",
                    "status": status,
                    "response": {"contentType": content_type, "headers": {
                        "server": upstream_headers.get("Server", ""),
                        "xRequestId": upstream_headers.get("X-Request-Id", ""),
                    }},
                })
                write_proxy_event("upstream_response", route_label=route["label"], request_id=request_id, status=status, contentType=content_type,
                                  upstreamErrorBody=upstream_error_body if upstream_error_body else None,
                                  cloudMeta=cloud_meta or None)
                # What this answer says about the OUTPUT itself — a verdict the
                # backup node reads before the next request and the board
                # draws (output_health.py). A request-specific 4xx counts as
                # alive: the output answered.
                if _conn_exc is not None:
                    output_health.note_error(route.get("routedOutputId"), kind="connect",
                                             message=str(_conn_exc)[:200])
                elif _inference_request:
                    output_health.note_status(route.get("routedOutputId"), status,
                                              message=(upstream_error_body or "")[:200])
                # ── onError rescue: replay the request down the backup exit ──
                if (status >= 400 and _rescue_refs and _rescue_hops < 3
                        and bytes_out == 0 and chunks == 0 and not _client_gone[0]):
                    _resc_ref = _rescue_refs.pop(0)
                    _newr = apply_router_spill(route, current_config(), _resc_ref,
                                               ctx={"model": req_summary.get("model"),
                                                    "maxTokens": req_summary.get("maxTokens"),
                                                    "audio": ("/audio/" in parsed.path),
                                                    "embeddings": parsed.path.rstrip("/").endswith("/embeddings")})
                    if _newr and not _newr.get("unrouted"):
                        _rescue_hops += 1
                        try:
                            conn.close()
                        except Exception:
                            pass
                        write_proxy_event("rescue_retry", route_label=route["label"],
                                          request_id=request_id, item=active, status=status,
                                          rescueRef=_resc_ref, hop=_rescue_hops,
                                          upstreamErrorBody=(upstream_error_body[:300] or None))
                        _rescue_trail.append({
                            "from": str(route.get("routedOutputId")
                                        or f"{route.get('upstreamHost')}:{route.get('upstreamPort')}"),
                            "status": int(status),
                            # The words of the exit that failed, short: the
                            # client's error names the chain (see below).
                            "reason": _upstream_failure_summary(status, upstream_error_body)[0][:120],
                        })
                        # The skip that started this chain belongs to the
                        # whole request, not to the leg that made it.
                        _newr["deadSkipped"] = list(route.get("deadSkipped") or []) + list(_newr.get("deadSkipped") or [])
                        route = _newr
                        route["label"] = route.get("label") or self.agent_name
                        route_is_cloud = str(route.get("upstreamType") or "llama") == "cloud"
                        cloud_fallback_provider_id = None
                        # A rescued route may cross its own onError node(s) — its
                        # fresh exits take precedence over any remaining ones.
                        _rescue_refs = list(route.get("rescueRefs") or []) + _rescue_refs
                        update_active(str(route["port"]), request_id, {
                            "upstream": f"{route['upstreamHost']}:{route['upstreamPort']}",
                            "upstreamType": str(route.get("upstreamType") or "llama"),
                            "providerId": str(route.get("providerId") or ""),
                            "rescuedTo": str(route.get("routedOutputId") or ""),
                        })
                        status = 502
                        upstream_error_body = ""
                        upstream_error_raw = b""
                        continue
                if _conn_exc is not None:
                    raise _conn_exc
                break
            if is_subscription and status == 200 and responses_passthrough:
                # A Responses client gets the codex stream as it came — event
                # by event — or, when it asked for a buffered answer, the final
                # `response` object of `response.completed` as JSON.
                if responses_client_stream:
                    if not headers_sent:
                        self.send_response(200, "OK")
                        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                        self.send_header("Cache-Control", "no-cache")
                        self.send_header("Connection", "close")
                        _on_client(self.end_headers)
                        _sse_open[0] = True
                    for chunk in iter_responses_passthrough(upstream, stream):
                        if first_byte_ms is None:
                            first_byte_ms = round((time.time() - started) * 1000)
                        bytes_out += len(chunk)
                        chunks += 1
                        _client_write(chunk)
                        if stop_requested(request_id):
                            raise ProxyRequestStopped("request stopped by traffic policy")
                        now = time.time()
                        if now - last_state_write >= 1:
                            last_state_write = now
                            update_active(str(route["port"]), request_id, {
                                "bytes": bytes_out, "chunks": chunks,
                                "firstByteMs": first_byte_ms, "stream": stream,
                                "elapsedMs": round((now - started) * 1000),
                            })
                else:
                    for chunk in iter_responses_passthrough(upstream, stream, keep_response=True):
                        if first_byte_ms is None:
                            first_byte_ms = round((time.time() - started) * 1000)
                        chunks += 1
                    final = json.dumps(stream.pop("response", None) or {"error": {"message": "stream ended without response.completed"}}).encode("utf-8")
                    bytes_out = len(final)
                    if not headers_sent:
                        self.send_response(200 if stream.get("done") else 502, "OK" if stream.get("done") else "Bad Gateway")
                        self.send_header("Content-Type", "application/json")
                        self.send_header("Content-Length", str(len(final)))
                        self.send_header("Connection", "close")
                        _on_client(self.end_headers)
                    self.wfile.write(final)
                    self.wfile.flush()
            elif is_subscription and status == 200:
                # Send chat/completions-compatible SSE headers (skip if already sent via keep-alive)
                if not headers_sent:
                    self.send_response(200, "OK")
                    self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                    self.send_header("Cache-Control", "no-cache")
                    self.send_header("Connection", "close")
                    _on_client(self.end_headers)
                    _sse_open[0] = True
                for chunk in _iter_responses_as_completions_sse(upstream, completion_id, subscription_model or "gpt-5.4-mini"):
                    if first_byte_ms is None:
                        first_byte_ms = round((time.time() - started) * 1000)
                    bytes_out += len(chunk)
                    chunks += 1
                    if chunk.startswith(b"data:"):
                        stream["events"] += 1
                        translated_summary = stream_summary_from_line(chunk)
                        stream["deltaTextChars"] += int(translated_summary.get("deltaTextChars") or 0)
                        # The translated final chunk carries usage (input/output tokens from
                        # the Responses API) — capture it so the spend-meter can price it.
                        if translated_summary.get("usage"):
                            stream["usage"] = translated_summary["usage"]
                        if translated_summary.get("finishReasons"):
                            stream["finishReasons"] = translated_summary["finishReasons"]
                        if translated_summary.get("done"):
                            stream["done"] = True
                    _client_write(chunk)
                    if stop_requested(request_id):
                        raise ProxyRequestStopped("request stopped by traffic policy")
                    now = time.time()
                    if now - last_state_write >= 1:
                        last_state_write = now
                        update_active(str(route["port"]), request_id, {
                            "bytes": bytes_out, "chunks": chunks,
                            "firstByteMs": first_byte_ms, "stream": stream,
                            "elapsedMs": round((now - started) * 1000),
                        })
            elif is_anthropic and status == 200:
                # Translate Anthropic Messages API response to OpenAI chat.completion format
                _amodel = anthropic_model or "claude-opus-4-8"
                if is_event_stream:
                    if not headers_sent:
                        self.send_response(200, "OK")
                        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                        self.send_header("Cache-Control", "no-cache")
                        self.send_header("Connection", "close")
                        _on_client(self.end_headers)
                        _sse_open[0] = True
                    for chunk in _iter_anthropic_as_completions_sse(upstream, completion_id, _amodel):
                        if first_byte_ms is None:
                            first_byte_ms = round((time.time() - started) * 1000)
                        bytes_out += len(chunk)
                        chunks += 1
                        if chunk.startswith(b"data:"):
                            stream["events"] += 1
                            translated_summary = stream_summary_from_line(chunk)
                            stream["deltaTextChars"] += int(translated_summary.get("deltaTextChars") or 0)
                            if translated_summary.get("usage"):
                                stream["usage"] = translated_summary["usage"]
                            if translated_summary.get("finishReasons"):
                                stream["finishReasons"] = translated_summary["finishReasons"]
                            if translated_summary.get("done"):
                                stream["done"] = True
                        _client_write(chunk)
                        if stop_requested(request_id):
                            raise ProxyRequestStopped("request stopped by traffic policy")
                        now = time.time()
                        if now - last_state_write >= 1:
                            last_state_write = now
                            update_active(str(route["port"]), request_id, {
                                "bytes": bytes_out, "chunks": chunks,
                                "firstByteMs": first_byte_ms, "stream": stream,
                                "elapsedMs": round((now - started) * 1000),
                            })
                else:
                    raw = b""
                    while True:
                        buf = upstream.read(65536)
                        if not buf:
                            break
                        if first_byte_ms is None:
                            first_byte_ms = round((time.time() - started) * 1000)
                        raw += buf
                    translated = _anthropic_to_completions_json(raw, completion_id, _amodel)
                    bytes_out = len(translated)
                    if not headers_sent:
                        self.send_response(200, "OK")
                        self.send_header("Content-Type", "application/json")
                        self.send_header("Content-Length", str(len(translated)))
                        self.send_header("Connection", "close")
                        _on_client(self.end_headers)
                    self.wfile.write(translated)
                    self.wfile.flush()
            else:
                if not headers_sent:
                    self.send_response(upstream.status, upstream.reason)
                    for key, value in upstream_headers.items():
                        if key.lower() not in HOP_HEADERS:
                            self.send_header(key, value)
                    self.send_header("Connection", "close")
                    # The body is the answering exit's own; the exits before
                    # it — skipped or replayed on — travel in a header, so a
                    # relayed error never hides the chain that led to it.
                    _chain = _rescue_chain_text(_rescue_trail, route.get("deadSkipped"))
                    if _chain:
                        self.send_header("X-Agent-Proxy-Chain", _chain[:900])
                    if upstream_error_raw:
                        # Already read the error body for logging — send it with correct length
                        self.send_header("Content-Length", str(len(upstream_error_raw)))
                    _on_client(self.end_headers)
                if upstream_error_raw:
                    if headers_sent:
                        # SSE stream already open — encode error as event
                        err_data = json.dumps({"error": f"upstream {status}", "status": status,
                                               "body": upstream_error_body[:256]})
                        self.wfile.write(f"event: error\ndata: {err_data}\n\ndata: [DONE]\n\n".encode())
                        self.wfile.flush()
                    else:
                        self.wfile.write(upstream_error_raw)
                        bytes_out += len(upstream_error_raw)
            if not is_subscription and not is_anthropic and is_event_stream:
                while True:
                    chunk = upstream.readline(65536)
                    if not chunk:
                        break
                    if first_byte_ms is None:
                        first_byte_ms = round((time.time() - started) * 1000)
                    bytes_out += len(chunk)
                    chunks += 1
                    if chunk.startswith(b"data:"):
                        stream["events"] += 1
                        event_summary = stream_summary_from_line(chunk)
                        stream["deltaTextChars"] += int(event_summary.get("deltaTextChars") or 0)
                        if event_summary.get("usage"):
                            stream["usage"] = event_summary["usage"]
                        if event_summary.get("timings"):
                            stream["timings"] = event_summary["timings"]
                        if event_summary.get("model"):
                            stream["model"] = event_summary["model"]
                        if event_summary.get("finishReasons"):
                            stream["finishReasons"] = event_summary["finishReasons"]
                        if event_summary.get("done"):
                            stream["done"] = True
                    _client_write(chunk)
                    if stop_requested(request_id):
                        raise ProxyRequestStopped("request stopped by traffic policy")
                    now = time.time()
                    if now - last_state_write >= 1:
                        last_state_write = now
                        update_active(str(route["port"]), request_id, {
                            "bytes": bytes_out,
                            "chunks": chunks,
                            "firstByteMs": first_byte_ms,
                            "stream": stream,
                            "elapsedMs": round((now - started) * 1000),
                        })
                    if STREAM_DONE_MARKER in chunk:
                        # Stopping here is our choice, so the frame we leave the
                        # client with has to be complete. readline() returns the
                        # marker without the blank line that ENDS the event, and
                        # that line is still in the socket when we break. Without
                        # it a parser that follows the SSE format never dispatches
                        # [DONE] — it waits for a terminator that never comes,
                        # until the connection closes. Both translating iterators
                        # already yield "data: [DONE]\n\n", and _send_sse_error
                        # writes it too: this passthrough was the one streaming
                        # path of three that ended a frame unterminated.
                        trailing = len(chunk) - len(chunk.rstrip(b"\n"))
                        missing = b"\n" * max(0, 2 - trailing)
                        if missing:
                            _client_write(missing)
                            bytes_out += len(missing)
                        break
            elif not is_subscription and not is_anthropic:
                if is_event_stream:
                    pass  # already handled above
                else:
                    capture = bytearray()
                    while True:
                        chunk = upstream.read(65536)
                        if not chunk:
                            break
                        if first_byte_ms is None:
                            first_byte_ms = round((time.time() - started) * 1000)
                        bytes_out += len(chunk)
                        chunks += 1
                        if len(capture) < BODY_CAPTURE_LIMIT:
                            capture.extend(chunk[:BODY_CAPTURE_LIMIT - len(capture)])
                        _client_write(chunk)
                        if stop_requested(request_id):
                            raise ProxyRequestStopped("request stopped by traffic policy")
                        now = time.time()
                        if now - last_state_write >= 1:
                            last_state_write = now
                            update_active(str(route["port"]), request_id, {
                                "bytes": bytes_out,
                                "chunks": chunks,
                                "firstByteMs": first_byte_ms,
                                "elapsedMs": round((now - started) * 1000),
                            })
                    response = response_summary(parse_json_bytes(bytes(capture)))
            if _client_gone[0]:
                # The heartbeat thread aborted the upstream, but the read loop
                # drained to EOF without an exception — still a dead client.
                raise ConnectionResetError("client disconnected during upstream wait")
            self.close_connection = True
            conn.close()
        except Exception as exc:
            _hb_stop.set()   # stop heartbeat before writing the error frame
            stop_reason = active_control_stop_reason(request_id)
            if stop_reason and not isinstance(exc, ProxyRequestStopped):
                exc = ProxyRequestStopped(stop_reason)
            if _client_gone[0]:
                # Whatever the read raised after we tore the upstream down, the
                # root cause is the vanished client.
                error = "client disconnected (upstream generation aborted)"
                error_kind = "client_disconnected"
            else:
                error = str(exc)
                # A failed replay must not hide what it was replaying for. The
                # client saw "[Errno 111] Connection refused" and never learned
                # that main had answered 429 first, nor which exit refused
                # (an agent's own log, 2026-09-06). Name the chain: the exit
                # that failed now, then every exit before it — replayed on, or
                # skipped on a fresh dead verdict.
                _chain = _rescue_chain_text(locals().get("_rescue_trail"), route.get("deadSkipped"))
                if _chain and not headers_sent:
                    _here = str(route.get("routedOutputId") or f"{route.get('upstreamHost')}:{route.get('upstreamPort')}")
                    error = f"{_here}: {error} — after {_chain}"
                # client_present=True is earned here, not assumed. Every write to
                # the client goes through _client_write, which flags a failed
                # write as the client leaving before re-raising; the heartbeat
                # flags a silent departure the same way. So an exception that
                # reaches this else did NOT come from the client side — it came
                # from the upstream leg, and a reset there is the upstream's.
                # (An earlier version of this comment claimed the client was
                # "still on the socket" because the flag was unset. For a
                # non-streaming request nothing was watching the socket at all.)
                error_kind = ("stopped" if isinstance(exc, ProxyRequestStopped)
                              else classify_proxy_error(exc, client_present=True))
            try:
                if _client_gone[0]:
                    pass   # nobody to write the error frame to
                elif headers_sent:
                    # The kind travels with the error, as it already does for a
                    # blocked request: it was computed two lines up and reached
                    # only the journal, so a client could see that something
                    # failed but never what.
                    self._send_sse_error({"error": error, "kind": error_kind})
                else:
                    self._send_bytes(status, json.dumps(
                        {"error": error, "kind": error_kind}).encode("utf-8"))
            except Exception:
                pass
        finally:
            _hb_stop.set()   # stop the idle SSE heartbeat thread
            if _hb_thread is not None:
                _hb_thread.join(timeout=1.0)   # ensure it never writes to a closing socket
            unregister_active_control(request_id)
            try:
                if conn:
                    conn.close()
            except Exception:
                pass
            result = {
                "id": request_id,
                "method": self.command,
                "path": parsed.path,
                "client": client,
                "route": route["label"],
                "port": route.get("port"),
                "upstream": f"{route['upstreamHost']}:{route['upstreamPort']}",
                "upstreamHost": route.get("upstreamHost"),
                "upstreamPort": route.get("upstreamPort"),
                "upstreamType": str(route.get("upstreamType") or "llama"),
                "status": status,
                "startedAt": int(started),
                "finishedAt": int(time.time()),
                "durationMs": round((time.time() - started) * 1000),
                "bytes": bytes_out,
                "chunks": chunks,
                "firstByteMs": first_byte_ms,
                "request": req_summary,
                "queue": queue,
                "priority": int(route.get("priority") or 0),
                "response": response,
                "stream": stream if stream["events"] else {},
                "error": error,
                "errorKind": error_kind,
            }
            # Spend attribution for the local proxy spend-meter (admin aggregates by
            # account/model × pricing). usage may live in response or the SSE stream.
            _u = {}
            if isinstance(response, dict) and isinstance(response.get("usage"), dict):
                _u = response["usage"]
            elif isinstance(stream, dict) and isinstance(stream.get("usage"), dict):
                _u = stream["usage"]
            result["usage"] = {
                "prompt": int(_u.get("prompt_tokens") or _u.get("input_tokens") or 0),
                "completion": int(_u.get("completion_tokens") or _u.get("output_tokens") or 0),
            }
            # Exact per-request timings (llama upstreams) — top-level for the admin
            # to build per-consumer token history keyed by this route's port.
            _tm = {}
            if isinstance(response, dict) and isinstance(response.get("timings"), dict):
                _tm = response["timings"]
            elif isinstance(stream, dict) and isinstance(stream.get("timings"), dict):
                _tm = stream["timings"]
            if _tm:
                result["timings"] = _tm
            # The summary must confess the rescue. Without this the finished
            # record reads as if the request went to its final upstream directly —
            # the failed first leg was only visible by scrolling back to the
            # rescue_retry events, an easy step to miss when diagnosing "why did
            # this agent suddenly answer through the cloud".
            if _rescue_trail:
                result["rescued"] = {"hops": len(_rescue_trail), "trail": _rescue_trail}
            # Likewise a main exit skipped on a fresh dead verdict: the record
            # says the request went down the backup at once, and why.
            if route.get("deadSkipped"):
                result["skippedDead"] = list(route.get("deadSkipped"))
            result["providerId"] = str(route.get("providerId") or "")
            result["cloudAccountId"] = str(route.get("cloudAccountId") or "")
            result["model"] = str((req_summary or {}).get("model") or "")
            # Sticky reservation: a graph queue node sets its own period (per-block);
            # None ⇒ finish_active falls back to the global policy default.
            _qspec = (route.get("queuePlan") or {}).get("spec") or {}
            if "stickySlotSec" in _qspec:
                result["stickySlotSec"] = _qspec.get("stickySlotSec")
            # An upstream that answered 4xx/5xx usually SAYS why, and that body
            # was reaching only the upstream_response event — the terminal
            # record, which every panel and stats reader consumes, carried a
            # bare status and two empty strings. On the board that renders as
            # "HTTP 503 ×25" with no reason, and the difference between
            # "circuit open", "too many concurrent requests" and a reset
            # connection is the difference between waiting and calling the
            # provider. error/errorKind are only set for client disconnects and
            # exceptions above, so filling them here takes nothing away.
            if status >= 400 and not error and not error_kind:
                error, error_kind = _upstream_failure_summary(status, upstream_error_body)
            # The exits this answer came AFTER. On the exception path the chain
            # is already inside the error text; a RELAYED error carried it only
            # in a response header, so the journal — and every panel reading it
            # — showed the last word and not the story. A local cell refusing
            # with 502 and the cloud then answering 429 was recorded as "usage
            # limit reached", which names the wrong culprit (2026-09-06).
            _chain = _rescue_chain_text(_rescue_trail, route.get("deadSkipped"))
            if _chain:
                result["chain"] = _chain[:900]
            finish_active(str(route["port"]), request_id, result)
            write_proxy_event("finished", route_label=route["label"], request_id=request_id, item=result, status=status, error=error, errorKind=error_kind)

    def _send_bytes(self, status, body, ctype="application/json"):
        """One complete reply: status, type, length, and Connection: close.

        The last header is why this exists rather than being written out at each
        site. This handler speaks HTTP/1.1, so a client that says keep-alive —
        which every modern SDK does by default — gets a persistent connection
        unless we say otherwise. The success path closes explicitly, but an
        exception jumps over that, and one hand-written copy of this block had
        no Connection header of its own: the thread then parked in readline()
        with no socket timeout, holding a listener thread for as long as the
        client kept the socket. Four copies of five lines, and the bug was one
        line missing from one of them.
        """
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def _send_sse_error(self, payload):
        """Report a failure inside an SSE stream that is already open.

        Once headers are sent the status is spent, so the only way left to tell
        the client anything is an error event followed by [DONE] — without the
        terminator a client waits out its own read timeout instead of failing.
        """
        data = json.dumps(payload)
        self.wfile.write(f"event: error\ndata: {data}\n\ndata: [DONE]\n\n".encode())
        self.wfile.flush()

    def _send_models(self, route):
        """Answer GET /v1/models with what the model behind this port serves.

        The port is an entry point, not a model. Which output actually serves a
        request is the router's decision, and it can land on a different cell —
        or on a cloud block — than the route's own upstream fields name. Built
        from the label instead, this endpoint told a client an id that no
        completion ever came back with, and a port whose cell was stopped, or
        that was bound to no router at all, still advertised a model as if it
        were there. That is absence rendered as normality (docs/why.md): an
        endpoint that cannot serve now says so instead.

        Cloud outputs keep a synthesised answer on purpose. The account's own
        /v1/models lists the provider's entire catalogue, while this port routes
        to exactly the one model its block pins; relaying the catalogue would
        advertise hundreds of models the port will not serve.
        """
        mode = str(route.get("mode") or "open").lower()
        if mode in ("paused", "drain"):
            self._send_bytes(503, json.dumps(
                {"error": f"proxy route {route['label']} is {mode}", "kind": "blocked"}).encode("utf-8"))
            return
        # Same resolution a request goes through (proxy()), with a neutral ctx:
        # a GET carries no model, no token count and is neither audio nor
        # embeddings, so the graph answers with the output a plain chat request
        # would reach.
        route = apply_router(route, current_config(), ctx=dict(PLAIN_REQUEST_CTX))
        upstream_type = str(route.get("upstreamType") or "llama")
        if route.get("unrouted") and upstream_type != "cloud":
            reason = route["unrouted"]
            self._send_bytes(503, json.dumps({"error": {
                "message": f"proxy {route.get('label') or ''} is not routed to a router output ({reason})",
                "type": "unrouted"}}).encode("utf-8"))
            return
        if upstream_type == "cloud":
            entry = _cloud_model_entry(route)
            self._send_bytes(200, json.dumps({"object": "list", "data": [entry]}).encode("utf-8"))
            return
        host, port = route.get("upstreamHost"), route.get("upstreamPort")
        try:
            conn = http.client.HTTPConnection(host, port, timeout=10)
            try:
                conn.request("GET", "/v1/models", headers={"Host": f"{host}:{port}"})
                resp = conn.getresponse()
                body = resp.read()
                ctype = resp.getheader("Content-Type") or "application/json"
                status = resp.status
            finally:
                conn.close()
        except Exception as exc:
            self._send_bytes(502, json.dumps({"error": {
                "message": f"upstream {host}:{port} did not answer /v1/models: {exc}",
                "type": "upstream_unavailable"}}).encode("utf-8"))
            return
        if status == 200:
            body = _publish_context_window(body, route)
            body = _rename_models(body, _route_model_name(route))
        self._send_bytes(status, body, ctype)

    def _routed_upstream_type(self):
        """"cloud" or "llama" for THIS port, as the router decides it.

        The stored route can name 127.0.0.1 and still send every request to a
        cloud block through the graph — that is the shape running in
        production. Reading the stored field alone was the blind spot that let
        /health fall through to the cloud leg on exactly those ports.
        """
        route = live_route_for_port(self.server.route.get("port")) or self.server.route
        route = apply_router(route, current_config(),
                             ctx={"model": "", "maxTokens": None, "audio": False, "embeddings": False})
        return str(route.get("upstreamType") or "llama"), route

    def _send_cloud_absent(self, path):
        self._send_bytes(404, json.dumps({"error": {
            "message": f"{path} is not served by a cloud bridge port",
            "type": "not_found"}}).encode("utf-8"))

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/v1/models":
            route = live_route_for_port(self.server.route.get("port")) or self.server.route
            if not self._api_key_ok(route):
                self._reject_unauthorized(route, f"{time.time_ns()}-{threading.get_ident()}")
                return
            self._send_models(route)
            return
        if path in CLOUD_ABSENT_PATHS:
            upstream_type, _route = self._routed_upstream_type()
            if upstream_type == "cloud":
                self._send_cloud_absent(path)
                return
        if path.startswith("/v1/models/") and len(path) > len("/v1/models/"):
            upstream_type, route = self._routed_upstream_type()
            if upstream_type == "cloud":
                if not self._api_key_ok(route):
                    self._reject_unauthorized(route, f"{time.time_ns()}-{threading.get_ident()}")
                    return
                # OpenAI's retrieve-model. Answered from the same source as
                # /v1/models, so the two cannot disagree; an id this port does
                # not serve is a 404, which is the honest answer and the one
                # the spec gives.
                entry = _cloud_model_entry(route)
                if entry["id"] == path[len("/v1/models/"):]:
                    self._send_bytes(200, json.dumps(entry).encode("utf-8"))
                else:
                    self._send_cloud_absent(path)
                return
        if path == "/health":
            upstream_type, route = self._routed_upstream_type()
            if upstream_type == "cloud":
                # Bridge health is the port itself: cloud APIs have no /health,
                # so forwarding answered 405 and painted the activity strip red
                # every time an external consumer probed its endpoint. But "the
                # port answers" must not mean "requests will work": a dangling
                # providerId (model block deleted) or a missing credential fails
                # every real call with "cloud provider not configured" — report
                # that as degraded/503 instead of lying with ok.
                provider = load_cloud_provider(route.get("providerId") or "")
                reason = ("" if provider and provider_secret_present(provider)
                          else ("no credentials for account" if provider else "cloud provider not configured"))
                payload = {"status": "ok"} if not reason else {"status": "degraded", "reason": reason}
                body = json.dumps(payload).encode("utf-8")
                self._send_bytes(200 if not reason else 503, body)
                return
        self.proxy()

    def do_POST(self):
        # /api/show is Ollama's model-info call and it is a POST. Left to
        # proxy() it was translated into a Responses request with no input and
        # sent to the paid API, which rejected it 26 times in one day.
        if urlsplit(self.path).path in CLOUD_ABSENT_PATHS:
            upstream_type, _route = self._routed_upstream_type()
            if upstream_type == "cloud":
                self._send_cloud_absent(urlsplit(self.path).path)
                return
        self.proxy()

    def do_OPTIONS(self):
        self.proxy()
