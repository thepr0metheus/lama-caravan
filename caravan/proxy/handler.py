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

from caravan.proxy.cloud_auth import (
    CLOUD_PROVIDER_AUTH,
    load_cloud_account,
    load_cloud_provider,
    load_provider_secret,
)
from caravan.proxy.config import current_config, live_route_for_port
from caravan.proxy.graph import apply_router, apply_router_spill
from caravan.proxy.events import write_proxy_event
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
    _extract_chatgpt_account_id,
    _iter_anthropic_as_completions_sse,
    _iter_responses_as_completions_sse,
    classify_proxy_error,
    rewrite_model_in_body,
)


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
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(payload)
        except Exception:
            pass
        write_proxy_event("blocked", route_label=route.get("label") or "", request_id=request_id,
                          item={"id": request_id, "route": route.get("label") or "",
                                "port": route.get("port"), "reason": "unauthorized:bad-api-key"})

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
                self.send_response(503)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload503)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(payload503)
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
                    # SSE stream already open — encode error as event then [DONE]
                    err_event = (f"event: error\ndata: {json.dumps({'error': str(exc), 'kind': exc.kind})}"
                                 f"\n\ndata: [DONE]\n\n").encode()
                    self.wfile.write(err_event)
                    self.wfile.flush()
                else:
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.wfile.write(payload)
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

        def _client_write(data):
            with _wfile_lock:
                self.wfile.write(data)
                self.wfile.flush()
                _last_client_write[0] = time.time()

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
            is_cloud = route_is_cloud or cloud_fallback_provider_id is not None
            is_subscription = False
            is_anthropic = False
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
                    # Translate request to Responses API format
                    model_override = provider.get("model") if str(provider.get("modelMode") or "rewrite") == "rewrite" else None
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
            _lm_wait = float((current_config().get("policy") or DEFAULT_POLICY).get("loadingModelWaitSec") or 60)
            _lm_retry_delay = 3.0
            _lm_deadline = time.time() + _lm_wait
            _lm_attempt = 0
            upstream_error_body = ""
            upstream_error_raw = b""
            while True:
                if _client_gone[0]:
                    raise ConnectionResetError("client disconnected during upstream wait")
                conn.request(self.command, send_path, body=send_body, headers=headers)
                # Grab the raw socket now — getresponse() detaches conn.sock on
                # Connection: close responses, and the abort path needs it.
                _up_sock[0] = conn.sock
                upstream = conn.getresponse()
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
            if is_subscription and status == 200:
                # Send chat/completions-compatible SSE headers (skip if already sent via keep-alive)
                if not headers_sent:
                    self.send_response(200, "OK")
                    self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                    self.send_header("Cache-Control", "no-cache")
                    self.send_header("Connection", "close")
                    self.end_headers()
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
                        self.end_headers()
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
                        self.end_headers()
                    self.wfile.write(translated)
                    self.wfile.flush()
            else:
                if not headers_sent:
                    self.send_response(upstream.status, upstream.reason)
                    for key, value in upstream_headers.items():
                        if key.lower() not in HOP_HEADERS:
                            self.send_header(key, value)
                    self.send_header("Connection", "close")
                    if upstream_error_raw:
                        # Already read the error body for logging — send it with correct length
                        self.send_header("Content-Length", str(len(upstream_error_raw)))
                    self.end_headers()
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
                        self.wfile.write(chunk)
                        self.wfile.flush()
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
                error_kind = "stopped" if isinstance(exc, ProxyRequestStopped) else classify_proxy_error(exc)
            try:
                if _client_gone[0]:
                    pass   # nobody to write the error frame to
                elif headers_sent:
                    # SSE stream already open — encode error as event
                    err_data = json.dumps({"error": error})
                    self.wfile.write(f"event: error\ndata: {err_data}\n\ndata: [DONE]\n\n".encode())
                    self.wfile.flush()
                else:
                    payload = json.dumps({"error": error}).encode("utf-8")
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
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
            result["providerId"] = str(route.get("providerId") or "")
            result["cloudAccountId"] = str(route.get("cloudAccountId") or "")
            result["model"] = str((req_summary or {}).get("model") or "")
            # Sticky reservation: a graph queue node sets its own period (per-block);
            # None ⇒ finish_active falls back to the global policy default.
            _qspec = (route.get("queuePlan") or {}).get("spec") or {}
            if "stickySlotSec" in _qspec:
                result["stickySlotSec"] = _qspec.get("stickySlotSec")
            finish_active(str(route["port"]), request_id, result)
            write_proxy_event("finished", route_label=route["label"], request_id=request_id, item=result, status=status, error=error, errorKind=error_kind)

    def _send_models_fast(self, route):
        mode = str(route.get("mode") or "open").lower()
        if mode in ("paused", "drain"):
            payload = json.dumps({"error": f"proxy route {route['label']} is {mode}", "kind": "blocked"}).encode("utf-8")
            self.send_response(503)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(payload)
            return
        upstream_type = str(route.get("upstreamType") or "llama")
        if upstream_type == "cloud":
            provider = load_cloud_provider(route.get("providerId") or "")
            model_id = (provider.get("model") if provider else None) or route.get("label") or "default"
            owned_by = (provider.get("type") if provider else None) or "cloud"
        else:
            model_id = route.get("label") or "default"
            owned_by = "llama.cpp"
        body = json.dumps({
            "object": "list",
            "data": [{"id": model_id, "object": "model", "created": int(time.time()), "owned_by": owned_by}],
        }).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if urlsplit(self.path).path == "/v1/models":
            route = live_route_for_port(self.server.route.get("port")) or self.server.route
            if not self._api_key_ok(route):
                self._reject_unauthorized(route, f"{time.time_ns()}-{threading.get_ident()}")
                return
            self._send_models_fast(route)
            return
        self.proxy()

    def do_POST(self):
        self.proxy()

    def do_OPTIONS(self):
        self.proxy()
