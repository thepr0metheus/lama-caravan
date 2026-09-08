"""What a port answers a client on `GET /v1/models` — asked on the operator's
behalf.

A client learns the model's name and window size from exactly this: it asks
the port, reads `id` and one of the window fields, and lives with whatever it
read from then on. When its numbers disagree with the board, the question is
always the same — "what does the port ACTUALLY report?" — and before this
module the only way to answer it was by hand over ssh, knowing the route key.

The key stays here: the controller asks, the browser gets the parsed answer.
Handing the key to the page for one check would mean handing it to everyone
who ever opens that page.
"""
import json
import time
import urllib.error
import urllib.request

from caravan.admin.paths import TOPOLOGY_SERVER_IP
from caravan.common.context_window import trained_window
from caravan.admin.proxies_config import load_agent_proxy_config
from caravan.common.errors import AppError

#: Names clients read the context window under, in decreasing order of how
#: common they are. The first one found is what a client will actually read.
CONTEXT_KEYS = ("context_length", "max_model_len", "context_window", "max_context_length",
                "max_position_embeddings", "max_input_tokens", "max_sequence_length",
                "max_seq_len", "n_ctx", "ctx_size")


def _entry_summary(entry):
    """A flat digest of one `data[]` entry: what a client actually reads."""
    if not isinstance(entry, dict):
        return {}
    windows = {key: entry[key] for key in CONTEXT_KEYS if isinstance(entry.get(key), int)}
    meta = entry.get("meta") if isinstance(entry.get("meta"), dict) else {}
    return {
        "id": str(entry.get("id") or ""),
        "ownedBy": str(entry.get("owned_by") or ""),
        "created": entry.get("created"),
        "windows": windows,
        # The window a client would actually read — the first of its known names.
        "window": next(iter(windows.values()), None),
        # The nested `meta.n_ctx` is a fact about the RUNNING server, and it's
        # needed here SEPARATELY from the advertised one: the proxy publishes
        # the smaller of the cap and the model's window up top, and whether
        # these two numbers agree is itself informative. So it's read as-is,
        # not through `served_window`, which exists precisely to prefer the
        # published one. The trained window only ever comes through the
        # dict: `n_ctx_train` must not be read anywhere else (guarded).
        "servedWindow": meta.get("n_ctx") if isinstance(meta.get("n_ctx"), int) else None,
        "trainedWindow": trained_window(entry),
        "aliases": [str(a) for a in (entry.get("aliases") or []) if isinstance(a, str)][:8],
    }


def proxy_model_card(port):
    """Ask a port its own `/v1/models` and return the parsed answer.

    Returns EVERYTHING that happened: the address, status, timing, parsed
    entries, and raw body. An error is an answer too: "the port didn't
    answer" is a fact about the route, and a silently empty field would say
    "no models" in its place.
    """
    try:
        port = int(str(port).strip())
    except (TypeError, ValueError):
        raise AppError("port must be a number", 400)
    if port <= 0:
        raise AppError("port must be a number", 400)
    route = next((r for r in (load_agent_proxy_config().get("routes") or [])
                  if int(r.get("port") or 0) == port), None)
    if route is None:
        raise AppError(f"no proxy route on port {port}", 404)
    url = f"http://{TOPOLOGY_SERVER_IP}:{port}/v1/models"
    headers = {"Accept": "application/json"}
    if str(route.get("apiKey") or ""):
        headers["Authorization"] = f"Bearer {route['apiKey']}"
    started = time.time()
    status, raw, error = 0, "", ""
    try:
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=10) as response:
            status = int(response.status)
            raw = response.read(200_000).decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        try:
            raw = exc.read(200_000).decode("utf-8", errors="replace")
        except Exception:
            raw = ""
        error = f"HTTP {status}"
    except Exception as exc:
        error = str(exc)
    took_ms = int((time.time() - started) * 1000)
    payload = None
    try:
        payload = json.loads(raw) if raw else None
    except Exception:
        error = error or "the answer is not JSON"
    entries = []
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        entries = [_entry_summary(e) for e in payload["data"] if isinstance(e, dict)]
    return {
        "ok": status == 200 and not error,
        "url": url,
        "label": str(route.get("label") or ""),
        "port": port,
        # Whether the port demands a key. The value itself is never handed
        # out — but the link in the UI must warn: a browser without the key
        # gets a 401 from it, and that's the route's lock, not a malfunction.
        "keyed": bool(str(route.get("apiKey") or "")),
        "status": status,
        "tookMs": took_ms,
        "error": error,
        "entries": entries,
        "raw": raw[:100_000],
    }
