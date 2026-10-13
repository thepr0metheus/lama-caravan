"""Errors as an OpenAI client reads them: the entry's language for a consumer.

An OpenAI client — the official libraries and every tool built on them — reads
a failure by its status and by `{"error": {"message", "type", "param",
"code"}}`. It retries 408, 409, 429 and every 5xx by itself, and it obeys two
headers: `Retry-After` (seconds; past 60 it backs off on its own clock
instead) and `x-should-retry`, which overrides the status. So a limit that
lasts hours says `x-should-retry: false`: the client's retries could not
outwait it, they would only be refused again.

The words are the caravan's. A provider's message can name its account — its
organisation, its plan — and a consumer must not learn what stands behind a
model (the owner, 2026-10-11), so a refusal about the caravan's own sign-in at
a provider never reaches a consumer as a 401: that status would tell the
client its own key is wrong.
"""
import json
import re


class OpenAIError:
    """One error: its status, message, code and how long to wait."""

    #: The `type` OpenAI's own API gives a status; a 5xx is a "server_error".
    TYPES = {400: "invalid_request_error", 401: "invalid_request_error", 403: "invalid_request_error",
             404: "invalid_request_error", 409: "invalid_request_error", 413: "invalid_request_error",
             422: "invalid_request_error", 429: "rate_limit_error"}
    #: The longest wait an OpenAI client still takes from Retry-After.
    RETRY_WINDOW = 60
    #: A code a client can branch on, in the shape OpenAI's own have: words joined by "_". A number
    #: (llama.cpp answers `"code": 400`), a sentence or anything longer is no such code, and what it
    #: holds may be something that must not reach a client.
    CODE = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,63}")

    def __init__(self, status, message, code=None, param=None, retry_after=None):
        self.status = int(status)
        self.message = str(message)
        self.code = code
        self.param = param
        self.retry_after = int(retry_after) if retry_after else None

    @property
    def type(self):
        return self.TYPES.get(self.status, "server_error" if self.status >= 500 else "invalid_request_error")

    def payload(self):
        return {"error": {"message": self.message, "type": self.type, "param": self.param, "code": self.code}}

    def body(self):
        return json.dumps(self.payload()).encode("utf-8")

    def headers(self):
        """Retry-After when a wait is known, and `x-should-retry: false` when it is
        longer than an OpenAI client would wait."""
        if not self.retry_after:
            return []
        out = [("Retry-After", str(self.retry_after))]
        if self.retry_after > self.RETRY_WINDOW:
            out.append(("x-should-retry", "false"))
        return out

    # ── the entry's own refusals ─────────────────────────────────────────────

    @classmethod
    def no_key(cls):
        return cls(401, "You didn't provide an API key. Send your key from the caravan in an "
                        "Authorization header: Authorization: Bearer <key>.")

    @classmethod
    def wrong_key(cls, key):
        return cls(401, f"Incorrect API key provided: {cls.masked(key)}. Ask the caravan's operator for your key.",
                   code="invalid_api_key")

    @classmethod
    def shared_key(cls):
        """A key two consumers carry: the board refuses it, a hand-edited file may hold it.
        Not a 409 — a client retries that — and the key works for neither."""
        return cls(401, "This API key is given to more than one consumer, so it opens none. "
                        "Ask the caravan's operator for a key of your own.", code="invalid_api_key")

    @classmethod
    def unknown_model(cls, model):
        return cls(404, f"The model `{model}` does not exist or you do not have access to it.",
                   param="model", code="model_not_found")

    @classmethod
    def no_model(cls):
        """A request that names no model: OpenAI's own words for it. A key calls a set of models
        now, and which of them is the request's to say."""
        return cls(400, "you must provide a model parameter", param="model")

    @classmethod
    def invalid_url(cls, method, path):
        return cls(404, f"Invalid URL ({method} {path})")

    @classmethod
    def unreadable(cls):
        """A body that is neither a JSON object nor a form (caravan/common/request_fields.py)."""
        return cls(400, "The caravan reads a request as JSON (application/json), or as a form "
                        "(multipart/form-data) where OpenAI's API takes a file: send it as one of them.")

    @classmethod
    def broken_body(cls, reason):
        """A body that cannot be taken off the connection as the request says it is sent — its length
        or its chunks (caravan/proxy/request_body.py)."""
        return cls(400, f"The request body cannot be read: {reason}.")

    @classmethod
    def no_pool(cls):
        """A key no cable on the kanban leads to a set of models yet, or whose set holds none: it
        calls no model at all."""
        return cls(404, "This API key has no model yet. Ask the caravan's operator to connect it to a set of models.",
                   param="model", code="model_not_found")

    @classmethod
    def paused(cls):
        return cls(503, "This consumer is paused on the caravan's board.", retry_after=30)

    # ── a pool's own answers and a provider's, in the caravan's words ────────

    @classmethod
    def limit(cls, model, retry_after):
        """Every step of the pool is held by a limit until `retry_after` seconds from now."""
        return cls(429, f"The model `{model}` has reached its usage limit. Try again in {cls.duration(retry_after)}.",
                   code="rate_limit_exceeded", retry_after=retry_after)

    @classmethod
    def unavailable(cls, model, retry_after=None):
        return cls(503, f"The model `{model}` cannot serve now. Try again later.",
                   code="model_unavailable", retry_after=retry_after)

    @classmethod
    def unsupported(cls, model, path):
        """No row of the pool does this kind of work — a recording sent to a model of subscriptions
        (caravan/proxy/pool_steps.py PoolRefusal.unsupported): the caller's to fix, never a wait."""
        return cls(400, f"The model `{model}` does not serve POST {path or 'this path'}. "
                        "Pick a model of your list that does.", param="model")

    @classmethod
    def closed(cls, model, opens, retry_after=None):
        """Every row of the model is closed by its schedule (caravan/common/model_schedules.py):
        503 with the time it opens, as the owner chose on 2026-10-12, and Retry-After until then.
        `opens` is that time in the caravan's zone with its offset, "" when no window opens."""
        if not opens:
            return cls(503, f"The model `{model}` is closed by its schedule, and no window of it opens.",
                       code="model_unavailable")
        return cls(503, f"The model `{model}` is closed by its schedule until {opens}. "
                        f"Try again in {cls.duration(retry_after)}.",
                   code="model_unavailable", retry_after=retry_after)

    @classmethod
    def clean_code(cls, code):
        """`code` when it is a word a client can branch on, else None."""
        return code if isinstance(code, str) and cls.CODE.fullmatch(code) else None

    @classmethod
    def upstream(cls, status, model, reason="", code=None):
        """An upstream's own refusal of a request, as the consumer is told it.

        A 4xx other than about the caravan's sign-in is about the request —
        too long a context, a bad parameter — and its words are the client's
        to read. The caravan's sign-in refused (401, 403) and the provider's
        own failures (5xx) are not the client's fault: 502, in the caravan's
        words.

        `code` is what the cell behind a local row called its refusal
        (`unsupported_robot_schema`): with the words it is the client's too, and the
        client branches on it as on OpenAI's own. The caller gives none for a
        provider's row — a provider's code stays the provider's — and only a clean
        one is told (clean_code). A status that has words of the caravan's own
        keeps their code."""
        status = int(status)
        if status in (401, 403):
            return cls(502, f"The provider behind `{model}` refused the caravan. The operator must sign in again.",
                       code="upstream_auth")
        if status == 429:
            return cls(429, f"The model `{model}` is busy. Try again later.", code="rate_limit_exceeded",
                       retry_after=30)
        if 400 <= status < 500:
            return cls(status, reason or f"The model `{model}` refused the request (HTTP {status}).",
                       code=cls.clean_code(code))
        return cls(502, f"The model `{model}` failed (HTTP {status}).", code="upstream_error")

    # ── words ────────────────────────────────────────────────────────────────

    @staticmethod
    def masked(key):
        """A key as OpenAI names one back: its last four characters only."""
        key = str(key or "")
        return ("…" + key[-4:]) if len(key) > 4 else "…"

    @staticmethod
    def duration(seconds):
        """`seconds` in words a person reads at a glance: 45 s, 12 min, 3 h 20 min."""
        seconds = max(1, int(seconds or 0))
        if seconds < 60:
            return f"{seconds} s"
        minutes = (seconds + 59) // 60
        if minutes < 60:
            return f"{minutes} min"
        hours, rest = divmod(minutes, 60)
        return f"{hours} h {rest} min" if rest else f"{hours} h"
