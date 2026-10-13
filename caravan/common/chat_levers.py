"""The standard fields of a chat request that steer how a model answers, said to the row that serves.

OpenAI's Chat Completions API has three of them: `reasoning_effort` (how long a model thinks before
it answers), `verbosity` (how long its answer is) and an image's `detail`. A client of the entry
keeps to that API (the owner, 2026-10-12: "we follow the OpenAI API standard"); the backends behind
a pool do not:

- a subscription's Codex backend speaks the Responses API: `reasoning.effort`, `text.verbosity`,
  an `input_image` part with its own `detail`. Until 1.3.501 the translator dropped the effort,
  fixed the verbosity at "low" and every image's detail at "auto" — sinapse, calling the
  subscription by itself, steered all three, and through the caravan would have lost them;
- a llama.cpp cell thinks or not by its chat template (`chat_template_kwargs.enable_thinking`).
  gemma-4 thinks by default: through the entry a short answer came back empty, every token spent
  on thinking (2026-10-12, max_tokens 16 — content "", reasoning_content 37 characters).

One class owns which values the fields take and what each backend is told, so the translator and
the cell's leg cannot read them two ways.
"""
import json


class ChatLevers:
    """OpenAI's reasoning_effort, verbosity and image detail, as each backend takes them."""

    #: The verbosity the subscription's translator has always sent when a client says none.
    QUIET = "low"
    VERBOSITIES = ("low", "medium", "high")
    DETAILS = ("low", "high", "auto")
    #: The efforts that ask a model not to think: a llama.cpp cell is told by its chat template.
    NO_THINKING = ("none", "minimal")

    @staticmethod
    def effort(payload):
        """The reasoning effort a client asked for, as it wrote it — the provider judges the word —
        or None when it asked for none."""
        value = payload.get("reasoning_effort") if isinstance(payload, dict) else None
        return value.strip() if isinstance(value, str) and value.strip() else None

    @classmethod
    def verbosity(cls, payload):
        """The verbosity a client asked for, or the caravan's quiet default for a word it does not
        know or none at all."""
        value = payload.get("verbosity") if isinstance(payload, dict) else None
        return value if value in cls.VERBOSITIES else cls.QUIET

    @classmethod
    def detail(cls, image_url):
        """An image's detail as the client set it on `image_url`, or "auto"."""
        value = image_url.get("detail") if isinstance(image_url, dict) else None
        return value if value in cls.DETAILS else "auto"

    @classmethod
    def for_responses(cls, payload):
        """What a Responses-API body gets from a chat request's levers: `text`, and `reasoning`
        only when the client asked for an effort."""
        said = {"text": {"verbosity": cls.verbosity(payload)}}
        effort = cls.effort(payload)
        if effort:
            said["reasoning"] = {"effort": effort}
        return said

    @classmethod
    def for_cell(cls, body, path):
        """A chat request bound for a llama.cpp cell, with "no thinking" said the template's way
        when the client asked for no effort. The same bytes object whenever nothing changes — a
        body that is not a chat request's JSON, an effort that allows thinking, a client that set
        `enable_thinking` itself (its word wins) — so the caller can tell."""
        if not body or not str(path or "").split("?", 1)[0].rstrip("/").endswith("/chat/completions"):
            return body
        try:
            payload = json.loads(body)
        except (ValueError, UnicodeDecodeError):
            return body
        if not isinstance(payload, dict) or cls.effort(payload) not in cls.NO_THINKING:
            return body
        kwargs = payload.get("chat_template_kwargs")
        if isinstance(kwargs, dict) and "enable_thinking" in kwargs:
            return body
        payload["chat_template_kwargs"] = {**(kwargs if isinstance(kwargs, dict) else {}), "enable_thinking": False}
        return json.dumps(payload).encode("utf-8")
