"""The one entry for consumers with keys (caravan/common/key_entry.py), in OpenAI's language."""
import json
import threading
import time
from urllib.parse import unquote, urlsplit

from caravan.common.context_window import effective_window, route_window_inputs
from caravan.common.entry_models import EntryModels
from caravan.common.key_entry import KeyEntry
from caravan.common.request_fields import RequestFields
from caravan.common.request_kind import is_inference_request
from caravan.proxy.cloud_auth import load_cloud_provider, load_entry_models, load_pool_kind
from caravan.proxy.config import current_config, normalize_route
from caravan.proxy.dialect import PORT_DIALECT, OpenAIDialect
from caravan.proxy.events import write_proxy_event
from caravan.proxy.handler import ProxyHandler
from caravan.proxy.openai_errors import OpenAIError
from caravan.proxy.request_body import RequestBody


class EntryHandler(ProxyHandler):
    """A request on the entry: its key finds its consumer, and then it is that consumer's request.

    Two kinds of consumer carry a key. A consumer of the entry — a route of
    kind "consumer", the owner's way since 2026-10-11 — is served as a company's
    gateway serves its clients: its key calls the pools of the set a cable on
    the kanban leads it to (caravan/common/entry_models.py), `GET /v1/models`
    lists them by their names, a request's `model` picks one, and every answer
    is in OpenAI's shape (caravan/proxy/dialect.py). An agent of the old kind, moved here with its
    port's key (1.3.442), is still its port's: its request goes through its
    kanban graph, as if it had come to the port — the window, the model name,
    the queue and the journal are the route's.

    A request without a key, or with one no route carries, is refused before
    anything else happens; so is a key two routes carry — the board refuses
    that on save, but the file can be edited by hand. A consumer's POST of
    Ollama's /api/show is answered too, in Ollama's shape: Hermes asks it for
    a model's window (`_consumer_show`).
    """

    REFUSALS = {
        "no-key": lambda key: OpenAIError.no_key(),
        "unknown-key": lambda key: OpenAIError.wrong_key(key),
        "ambiguous-key": lambda key: OpenAIError.shared_key(),
    }

    _entry_route = None

    @property
    def route(self):
        return self._entry_route

    @staticmethod
    def is_consumer(route):
        return str((route or {}).get("kind") or "") == "consumer"

    def _find_route(self):
        """True when the key names a route (it is then `route`); False after a refusal is sent.
        The route is found anew for every request: a connection is not a key."""
        self._entry_route = None
        self.dialect = PORT_DIALECT
        routes = []
        for raw in current_config().get("routes", []):
            try:
                routes.append(normalize_route(raw))
            except Exception:  # noqa: BLE001 — a malformed route is no route, as on the ports
                continue
        key = KeyEntry.presented_key(self.headers)
        route, reason = KeyEntry.route_for(key, routes)
        if route is None:
            self._refuse(self.REFUSALS[reason](key), f"entry:{reason}")
            return False
        self._entry_route = route
        return True

    def _client(self):
        """The sender as the journal names it. The kanban's test of a client — a request from this
        machine itself, not through the DSM's proxy, with KeyEntry.PROBE_HEADER — is named as the
        test: a client cannot hide its own errors by sending the header, it comes through the DSM."""
        remote = self.client_address[0] if self.client_address else ""
        direct = remote in ("127.0.0.1", "::1") and not (self.headers or {}).get("X-Forwarded-For")
        if direct and (self.headers or {}).get(KeyEntry.PROBE_HEADER):
            return KeyEntry.PROBE_CLIENT
        return super()._client()

    def _refuse(self, err, reason, route=None):
        """Send `err` and write it in the journal — under the consumer's name once it is known."""
        request_id = f"{time.time_ns()}-{threading.get_ident()}"
        try:
            self._send_bytes(err.status, err.body(), headers=err.headers() + [("X-Request-Id", request_id)])
        except Exception:  # noqa: BLE001 — a client gone before its refusal changes nothing here
            pass
        label = (route or {}).get("label") or "entry"
        write_proxy_event("blocked", route_label=label, request_id=request_id,
                          item={"id": request_id, "route": label, "port": (route or {}).get("port") or "entry",
                                "method": getattr(self, "command", ""), "path": urlsplit(self.path).path, "status": err.status,
                                "reason": reason, "client": self._client()})

    def do_GET(self):
        if not self._find_route():
            return
        if self.is_consumer(self.route):
            self._consumer_get(self.route)
            return
        super().do_GET()

    def do_POST(self):
        if not self._find_route():
            return
        if self.is_consumer(self.route):
            self._consumer_post(self.route)
            return
        super().do_POST()

    def do_OPTIONS(self):
        if not self._find_route():
            return
        if self.is_consumer(self.route):
            self._refuse(OpenAIError.invalid_url("OPTIONS", urlsplit(self.path).path), "entry:invalid-url", self.route)
            return
        super().do_OPTIONS()

    # ── a consumer of the entry ──────────────────────────────────────────────

    def _consumer_get(self, route):
        """The model list — the pools of the consumer's set, in its order, or none — and one
        model of it; any other question is a path the entry has not."""
        path = urlsplit(self.path).path
        if str(route.get("mode") or "open").lower() in ("paused", "drain"):
            self._refuse(OpenAIError.paused(), "entry:paused", route)
            return
        models = load_entry_models()
        now = int(time.time())
        if path.rstrip("/") == "/v1/models":
            data = [self._model_object(route, pool, now) for pool in models.models(route)]
            self._send_bytes(200, json.dumps({"object": "list", "data": data}).encode("utf-8"))
            return
        if path.startswith("/v1/models/") and len(path) > len("/v1/models/"):
            # The id is compared decoded: a client escapes what a path cannot carry
            # (a space travels as %20). `unquote`, not `unquote_plus`: a `+` is a plus.
            wanted = unquote(path[len("/v1/models/"):])
            pool = models.pick(route, wanted)
            if pool is None:
                self._refuse(OpenAIError.unknown_model(wanted), "entry:model-unknown", route)
                return
            self._send_bytes(200, json.dumps(self._model_object(route, pool, now)).encode("utf-8"))
            return
        self._refuse(OpenAIError.invalid_url("GET", path), "entry:invalid-url", route)

    #: Ollama's question for a model's particulars. Hermes asks it to learn a model's window and
    #: was answered 404 (the owner, 2026-10-12: "answer it").
    OLLAMA_SHOW = "/api/show"

    def _consumer_post(self, route):
        """A request of the consumer's key, in OpenAI's language: its `model` picks the pool among
        the ones its set holds (the owner, 2026-10-12: a set, and the standard's way to choose). A
        request that names no model is 400 and one its set has not is 404 `model_not_found`, as
        OpenAI answers them; a consumer no cable reaches is told it has no model yet. The model is
        read from a JSON body, or from a form's field where OpenAI takes a file — a recording to
        transcribe (caravan/common/request_fields.py, 1.3.501) — and the body goes on as it came."""
        path = urlsplit(self.path).path
        if path.rstrip("/") == self.OLLAMA_SHOW:
            self._consumer_show(route)
            return
        if not is_inference_request("POST", path):
            self._refuse(OpenAIError.invalid_url("POST", path), "entry:invalid-url", route)
            return
        body = self._body(route)
        if body is None:
            return
        asked = RequestFields.fields(self.headers.get("Content-Type"), body)
        if asked is None:
            self._refuse(OpenAIError.unreadable(), "entry:unreadable", route)
            return
        pool = self._picked(route, asked.get("model"))
        if pool is None:
            return
        # The work the model does is known (caravan/common/model_kinds.py): a request for other
        # work is the caller's to fix, said before anything is sent — a chat to an ear, a
        # recording to a chat model. Unknown or mixed, the rows decide.
        kind = load_pool_kind(pool)
        if kind is not None and not kind.serves(path):
            self._refuse(OpenAIError.unsupported(EntryModels.name(pool), path), "entry:unsupported", route)
            return
        self.dialect = OpenAIDialect(pool)
        self.proxy(body=body)

    def _body(self, route):
        """The request's body, by its length or its chunks (caravan/proxy/request_body.py): b"" for
        none; None with the refusal sent when it cannot be read as the request says it is sent."""
        try:
            return RequestBody.read(self.headers, self.rfile) or b""
        except RequestBody.Malformed as exc:
            self._refuse(OpenAIError.broken_body(str(exc)), "entry:broken-body", route)
            return None

    def _picked(self, route, model):
        """The pool `model` names among the consumer's, or None with the refusal sent: no model
        at all for its key, a request naming none, or a name its set has not."""
        models = load_entry_models()
        if not models.models(route):
            self._refuse(OpenAIError.no_pool(), "entry:no-pool", route)
            return None
        if not str(model or "").strip():
            self._refuse(OpenAIError.no_model(), "entry:no-model", route)
            return None
        pool = models.pick(route, model)
        if pool is None:
            self._refuse(OpenAIError.unknown_model(str(model)), "entry:model-unknown", route)
        return pool

    def _consumer_show(self, route):
        """Ollama's /api/show for the consumer's pool, in Ollama's shape: the window under
        `model_info` "<architecture>.context_length" and as `num_ctx` in its `parameters` — the
        figure /v1/models states, by the same rule (_model_object). A pool that states no window
        answers without one: a guessed window is worse than none (docs/why.md). The model is the
        one the body names (`model`, or `name` as older Ollama clients send it), picked among the
        consumer's as a request picks it."""
        body = self._body(route)
        if body is None:
            return
        try:
            asked = json.loads(body.decode("utf-8")) if body else {}
        except (UnicodeDecodeError, ValueError):
            asked = {}
        asked = asked if isinstance(asked, dict) else {}
        pool = self._picked(route, asked.get("model") or asked.get("name"))
        if pool is None:
            return
        window = self._model_object(route, pool, time.time()).get("context_length")
        doc = {"modelfile": "", "parameters": f"num_ctx {window}" if window else "", "template": "",
               "details": {"parent_model": "", "format": "", "family": "caravan", "families": ["caravan"],
                           "parameter_size": "", "quantization_level": ""},
               "model_info": {"general.architecture": "caravan", **({"caravan.context_length": window} if window else {})}}
        self._send_bytes(200, json.dumps(doc).encode("utf-8"))

    @staticmethod
    def _model_object(route, pool, now):
        """One model of the list in OpenAI's shape. The window is the pool's
        against this consumer's own limit — the rule a port applies — and
        absent when neither is known: a guessed window is worse than none
        (docs/why.md). `created` is the time of the answer: a pool keeps no
        date of its own, and the servers of the fleet answer the same way.
        What the model does (1.3.502): OpenRouter's `architecture` and the
        caravan's `caravan` — its jobs, an ear's languages and longest
        recording — when its rows say it (caravan/common/model_kinds.py)."""
        provider = load_cloud_provider(pool["id"])
        entry = {"id": EntryModels.name(pool), "object": "model", "created": int(now), "owned_by": "caravan"}
        limit, prefer_model = route_window_inputs(route)
        window = effective_window(limit, (provider or {}).get("contextLength"), prefer_model)
        if window is not None:
            entry["context_length"] = entry["max_model_len"] = window
        kind = load_pool_kind(pool)
        if kind is not None:
            entry.update(kind.models_entry())
        return entry
