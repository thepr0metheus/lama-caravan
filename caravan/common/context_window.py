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
a client that believes either sends more than the server will accept. Nothing
outside this module may read the trained number by name —
``scripts/check_context_window.py`` enforces that. It is not hidden, though: a
cell card shows it beside the model's name, labelled as what the weights were
trained with (``trained_window``), because the two numbers differ on this very
fleet and an operator sizing a cell wants both. It reaches the board under its
own name and never enters ``effective_window``, which takes served and
declared inputs only.

Servers disagree about where the served number lives (vLLM and SGLang put
``max_model_len`` on the card, llama.cpp nests ``meta.n_ctx``, Ollama and
text-generation-inference report nothing), and provider catalogues disagree
again (OpenRouter says ``context_length``, Anthropic ``max_input_tokens``,
api.openai.com says nothing). Hence two vocabularies, not one: a live server is
asked what it serves, a catalogue is asked what it declares.
"""
from urllib.parse import quote

# A live server's own model card.
SERVED_KEYS = ("max_model_len",)
SERVED_NESTED = (("meta", "n_ctx"),)

# A live llama.cpp server's /props: the window per slot, the same served
# number, under `default_generation_settings` (older builds: the top level).
# A client that knows llama.cpp reads its window here, not in /v1/models.
PROPS_SERVED_KEYS = ("n_ctx",)
PROPS_SERVED_NESTED = (("default_generation_settings", "n_ctx"),)

# The llama.cpp paths that state the served window. A cell's port rewrites
# them to its own figure (caravan/proxy/handler.py, _publish_props_window).
PROPS_PATHS = frozenset({"/props", "/v1/props"})

# A provider catalogue entry. `max_model_len` appears in both because a
# self-hosted OpenAI-compatible server can be registered as a cloud account.
DECLARED_KEYS = ("context_length", "max_input_tokens", "context_window", "max_model_len")

# Named here so that it is never read anywhere else: scripts/check_context_window.py
# refuses any module outside this one that mentions it. (The other trap, a cell's
# configured CTX_SIZE, cannot be forbidden the same way — launching a cell is what
# that field is FOR — so it is guarded by the docstring above and by the tests.)
FORBIDDEN_KEYS = ("n_ctx_train",)
# Where a live llama.cpp server states the trained window on its model card.
TRAINED_NESTED = (("meta", "n_ctx_train"),)


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


def props_served_window(props):
    """The context one request may use, as a llama.cpp server's /props states it."""
    if not isinstance(props, dict):
        return None
    for outer, inner in PROPS_SERVED_NESTED:
        section = props.get(outer)
        if isinstance(section, dict):
            found = _positive_int(section.get(inner))
            if found is not None:
                return found
    for key in PROPS_SERVED_KEYS:
        found = _positive_int(props.get(key))
        if found is not None:
            return found
    return None


def trained_window(entry):
    """The context the WEIGHTS were trained with, as a live server's model card states it.

    A fact about the model, not about the server: shown beside the model's
    name and labelled as such, never advertised as a window (see the module
    docstring). llama.cpp is the one server that reports it; the GGUF header's
    ``context_length`` is the same number for a file that is not running.
    """
    if not isinstance(entry, dict):
        return None
    for outer, inner in TRAINED_NESTED:
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


def effective_window(limit, model, prefer_model=False):
    """The window a PORT advertises, from the operator's limit and the model's own size.

    Two numbers meet at a port: the limit the operator set for this one client
    (an assignment field, copied onto the proxy route) and the window the
    output a plain request reaches serves — a cell's served window, or a cloud
    block's. The smaller wins, because larger is the direction that makes a
    client send more than the server accepts. When only one is known that one
    is published; when neither is, nothing is — a guessed window is worse than
    none (docs/why.md).

    `prefer_model` is the operator's opt-in to publish the model's own size
    even above their limit: with it the model's number wins whenever it is
    known, and the limit still applies while the model's is not. It replaces
    the old "auto" mode, which dropped the limit outright.

    One rule for two readers on purpose: the proxy answers /v1/models with it
    and the board shows the same figure from the same inputs, so a client and
    an operator can never see two different windows for one port.
    """
    limit = _positive_int(limit)
    model = _positive_int(model)
    if prefer_model and model is not None:
        return model
    if limit is None:
        return model
    if model is None:
        return limit
    return min(limit, model)


def route_window_inputs(route):
    """The operator's two settings on a proxy route: (limit, prefer_model).

    Zero and rubbish are absences, not limits: a client would read a zero as a
    real window of nothing.
    """
    route = route if isinstance(route, dict) else {}
    return _positive_int(route.get("contextLength")), bool(route.get("contextAuto"))


def block_window(declared, reported, prefer_reported=False):
    """The window a cloud BLOCK stands for.

    The operator's declared figure is the rule: it is deliberate, and it is the
    only source for a provider that publishes none. The figure the provider
    reports is used ONLY when the operator ticked the block's switch — it used
    to be a silent fallback, and a number nobody chose is the same trap as a
    guessed one. Neither known → None.
    """
    declared = _positive_int(declared)
    reported = _positive_int(reported)
    if prefer_reported and reported is not None:
        return reported
    return declared


def window_paths(upstream_type, model_ids=()):
    """Where a PORT states its window: [(question, path)], by what its plain request reaches.

    Every port answers the model list, /v1/models ("list"). A cloud port also
    answers OpenAI's retrieve-model, /v1/models/<id> ("retrieve"), from the
    same entry. A cell's port also rewrites llama.cpp's /props and /v1/props
    ("props") — a cell that is not llama.cpp answers those 404, and the port
    passes that on. An engine serves no /props and a cloud port answers it 404
    itself (CLOUD_ABSENT_PATHS), so neither gets them. A port that reaches
    nothing ("") gets the list alone: that is the answer that says why.

    The proxy answers by these rules (caravan/proxy/handler.py); the Model card
    turns them into links, so an operator can ask the port a client's own
    questions instead of trusting the board's figure for what it says.
    """
    paths = [("list", "/v1/models")]
    if upstream_type == "cloud":
        # The id as a client puts it in the path: `openai/gpt-4o` stays one
        # path, because the port takes the whole rest of the path as the id,
        # decoded; what a path cannot carry, a space among it, is escaped.
        paths += [("retrieve", f"/v1/models/{quote(str(model_id), safe='/:@')}")
                  for model_id in model_ids if model_id]
    elif upstream_type == "llama":
        paths += [("props", path) for path in sorted(PROPS_PATHS)]
    return paths
