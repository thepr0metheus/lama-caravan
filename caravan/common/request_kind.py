"""What KIND of request this is, by method and path — one answer for the fleet.

A client that has just met a port asks it a handful of questions before it
sends a single token: llama.cpp's `/props`, Ollama's `/api/tags` and
`/api/show`, text-generation-webui's `/v1/internal/model/info`, sometimes the
bare `/`. Whichever server actually stands behind the port has most of them
NOT, and answers 404. That is a normal conversation between a client and a
server neither of which is broken.

Read as failures, those answers do real damage. They once marked a healthy cell
dead and sent the probe to a cloud block (fixed by giving the health module this
rule), and they still filled the route's incident panel with red "proxy failed"
lines while every completion through the same port succeeded — 31 of 46
incidents on one production day, all of them discovery. Absence of an endpoint
rendered as failure of a route is the mirror of docs/why.md's usual defect, and
it costs the same thing: a panel nobody believes.

So the rule lives in one place and both readers take it from here: the proxy,
deciding whether a status is a verdict about the model behind an exit, and the
controller, deciding whether an answer is worth an incident.
"""

#: Paths whose answer says something about the MODEL behind an exit.
INFERENCE_PATH_SUFFIXES = (
    "/chat/completions", "/completions", "/embeddings", "/responses", "/messages",
    "/rerank", "/audio/transcriptions", "/audio/translations", "/audio/speech",
    "/infill", "/tokenize", "/detokenize", "/generate", "/predict",
)

#: Statuses that mean "this server has no such path", and nothing else. A 401 or
#: a 403 on the same probe is worth showing — the operator's key is wrong; a 5xx
#: means the exit itself is broken. Only "no such path" is silence, not failure.
ABSENT_PATH_STATUSES = frozenset({404, 405, 415, 501})


def is_inference_request(method, path):
    """True for a request whose failure is the model's failure, not the path's."""
    if str(method or "").upper() != "POST":
        return False
    clean = str(path or "").split("?", 1)[0].rstrip("/")
    return any(clean.endswith(suffix) for suffix in INFERENCE_PATH_SUFFIXES)


def is_discovery_probe(method, path, status):
    """True for "the client asked for a path this server does not have".

    Both halves are required: a POST to /v1/chat/completions answering 404 is
    the model saying it does not exist, which is a real failure of a real
    request, and a GET /props answering 500 is the exit itself falling over.

    A record that does not say WHICH path was asked is not a probe either. Not
    knowing what the client asked for is not the same as knowing it asked for
    nothing, and the silent half of that pair would hide real failures — the
    exact trade this rule exists to avoid making in the other direction.
    """
    if not str(path or "").strip():
        return False
    try:
        code = int(status)
    except (TypeError, ValueError):
        return False
    return code in ABSENT_PATH_STATUSES and not is_inference_request(method, path)
