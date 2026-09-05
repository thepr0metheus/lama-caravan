"""What counts as a context window — and which nearby numbers must never be taken for one.

Three numbers can be found around one model, and only the first answers the
question a client is actually asking, "how much may I send in one request":

* the SERVED window — what this server instance accepts per request. Measured on
  this fleet's chat cell: 60160, because llama.cpp divided a ``--ctx-size 180000``
  across three slots.
* the TRAINED window (``n_ctx_train``) — a property of the weights: 131072 for
  that same cell. True about the model, false about the server.
* the CONFIGURED total (``CTX_SIZE``) — what the operator asked for: 180000.
  The sum across slots, which no single request may use.

The last two are larger than the truth, and larger is the dangerous direction:
a client that believes either sends more than the server will accept. They are
named here only so they can be excluded, and nothing outside this module is
allowed to read them — ``scripts/check_context_window.py`` enforces that.

Servers disagree about where the served number lives (vLLM and SGLang put
``max_model_len`` on the card, llama.cpp nests ``meta.n_ctx``, Ollama and
text-generation-inference report nothing), and provider catalogues disagree
again (OpenRouter says ``context_length``, Anthropic ``max_input_tokens``,
api.openai.com says nothing). Hence two vocabularies, not one: a live server is
asked what it serves, a catalogue is asked what it declares.
"""

# A live server's own model card.
SERVED_KEYS = ("max_model_len",)
SERVED_NESTED = (("meta", "n_ctx"),)

# A provider catalogue entry. `max_model_len` appears in both because a
# self-hosted OpenAI-compatible server can be registered as a cloud account.
DECLARED_KEYS = ("context_length", "max_input_tokens", "context_window", "max_model_len")

# Named here so that it is never read anywhere else: scripts/check_context_window.py
# refuses any module outside this one that mentions it. (The other trap, a cell's
# configured CTX_SIZE, cannot be forbidden the same way — launching a cell is what
# that field is FOR — so it is guarded by the docstring above and by the tests.)
FORBIDDEN_KEYS = ("n_ctx_train",)


def _positive_int(value):
    """A size, or None. `null` from a vLLM LoRA card is an absence, not a size."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def served_window(entry):
    """The context one request may use, as the SERVER itself reported it."""
    if not isinstance(entry, dict):
        return None
    for key in SERVED_KEYS:
        found = _positive_int(entry.get(key))
        if found is not None:
            return found
    for outer, inner in SERVED_NESTED:
        section = entry.get(outer)
        if isinstance(section, dict):
            found = _positive_int(section.get(inner))
            if found is not None:
                return found
    return None


def declared_window(entry):
    """The context a provider's CATALOGUE claims for one of its models."""
    if not isinstance(entry, dict):
        return None
    for key in DECLARED_KEYS:
        found = _positive_int(entry.get(key))
        if found is not None:
            return found
    return None
