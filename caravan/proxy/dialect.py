"""How a request is routed and told its failures: a port's way, or the entry's for a consumer.

A port has always routed by its Routing graph and answered in its own words:
the upstream's status, headers and body as they came, the caravan's own
failures as `{"error", "kind"}`. A consumer of the entry (the owner,
2026-10-11) is served by the one pool its cable leads to (2026-10-12) and is
answered as an OpenAI client expects (caravan/proxy/openai_errors.py), with
nothing of the provider behind the pool: not its headers, not its words about
the caravan's sign-in.

The handler asks its dialect at each such point instead of branching on the
kind of request: one object per way, chosen when the request is known.
"""
import json

from caravan.proxy.config import current_config
from caravan.proxy.graph import _overlay_output, apply_router
from caravan.proxy.openai_errors import OpenAIError
from caravan.proxy.pool_steps import PoolRefusal


class PortDialect:
    """A port's way: its router decides, and failures are told as they always were."""

    #: Whether a client that did not ask for a stream gets one whole answer
    #: where the provider streams anyway (the Codex backend always does). A port
    #: has always relayed the stream; its clients ask for one.
    answers_whole = False

    def resolve(self, route, ctx):
        return apply_router(route, current_config(), ctx=dict(ctx))

    def failure(self, status, message, kind):
        """(status, body, headers) of a failure the caravan tells itself."""
        return status, json.dumps({"error": message, "kind": kind}).encode("utf-8"), []

    def stream_failure(self, message, kind):
        """The data of the error event once a stream is open."""
        return {"error": message, "kind": kind}

    def header_ok(self, name):
        """Whether an upstream header reaches the client: every one does on a port."""
        return True

    def answer_error(self, status, reason, answer, code=None):
        """The caravan's own words for an upstream error, or None to relay it as it came."""
        return None

    def extra_headers(self, request_id):
        return []


class OpenAIDialect:
    """The entry's way for a consumer: its pool serves, and it is told
    everything in OpenAI's shape and the caravan's words."""

    #: The upstream headers a consumer gets; the rest name the provider behind
    #: the pool — its organisation, its limits, its cookies.
    HEADERS = frozenset({"content-type", "content-length", "cache-control"})
    #: OpenAI's `stream` defaults to false: such a client reads one JSON answer.
    answers_whole = True

    def __init__(self, pool):
        self.pool = pool
        self.model = str(pool.get("name") or pool.get("id") or "")

    def resolve(self, route, ctx):
        """The consumer's route onto its pool. The output id is the
        one Routing gives a pool (`cb:<id>`, caravan/admin/proxies_config.py
        pool_output), so the board colours the same cable for both ways in."""
        return _overlay_output(route, {"id": f"cb:{self.pool['id']}", "name": self.model,
                                       "upstreamType": "cloud", "providerId": self.pool["id"]})

    def error(self, status, kind):
        """A failure of the caravan's own, in words that name nothing behind the model."""
        if kind == "blocked":
            return OpenAIError.paused()
        if int(status) == 429:
            return OpenAIError.limit(self.model, 30)
        return OpenAIError(502 if int(status) < 500 else int(status),
                           f"The model `{self.model}` failed. Try again later.", code=kind or "proxy_error")

    def failure(self, status, message, kind):
        err = self.error(status, kind)
        return err.status, err.body(), err.headers()

    def stream_failure(self, message, kind):
        return self.error(502, kind).payload()

    def header_ok(self, name):
        return str(name).lower() in self.HEADERS

    def answer_error(self, status, reason, answer, code=None):
        """(status, body, headers) for an upstream error. A pool's own refusal
        (no step fits) is a limit or an outage of the model as a whole; an
        upstream's refusal is told as openai_errors.OpenAIError.upstream says,
        with the `code` its cell gave when the row is a local one."""
        if isinstance(answer, PoolRefusal):
            if answer.status == 429:
                err = OpenAIError.limit(self.model, answer.retry_after)
            elif answer.status == 503 and answer.closed:
                err = OpenAIError.closed(self.model, answer.opens_text, answer.retry_after)
            elif answer.status == 400 and answer.unsupported:
                err = OpenAIError.unsupported(self.model, answer.path)
            elif answer.status == 503:
                err = OpenAIError.unavailable(self.model, answer.retry_after)
            else:
                err = OpenAIError(answer.status, answer.message, code=answer.KIND)
        else:
            err = OpenAIError.upstream(status, self.model, reason, code)
        return err.status, err.body(), err.headers()

    def extra_headers(self, request_id):
        return [("X-Request-Id", str(request_id))]


PORT_DIALECT = PortDialect()
