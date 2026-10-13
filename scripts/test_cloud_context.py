#!/usr/bin/env python3
"""Characterization snapshot: what the cloud path does with a context window.

Pins the VALUE at the three places a cloud model's context could survive or be
lost — the provider fetch that narrows each catalogue entry, the per-account
catalogue cache, and the pool the operator edits (a model block, before pools
of steps) — plus what the proxy publishes for a cloud upstream.

Written before the cloud path learned to carry the number, so the change shows
exactly which of them starts keeping it and which must not shift.

Run: python3 scripts/test_cloud_context.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="caravan-cloudctx-"))
os.environ["CARAVAN_DATA_DIR"] = str(TMP)
(TMP / "state").mkdir(parents=True, exist_ok=True)
(TMP / "config").mkdir(parents=True, exist_ok=True)
(TMP / "secrets").mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT))

from caravan.admin import cloud, model_catalog  # noqa: E402
from caravan.admin.pools import PoolDesk  # noqa: E402
from caravan.common.cloud_pools import CloudPools  # noqa: E402
from caravan.common.errors import AppError  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


# A catalogue entry in the shape each supported provider actually answers with.
# OpenRouter names the number context_length on every one of its models;
# Anthropic names it max_input_tokens; api.openai.com and Ollama's OpenAI layer
# report no such field at all. Values invented.
PROVIDER_ENTRIES = {
    "openrouter": {"id": "vendor/model-a", "name": "Model A", "context_length": 131072,
                   "pricing": {"prompt": "0.000001"}},
    "anthropic": {"id": "model-b", "display_name": "Model B", "max_input_tokens": 204800,
                  "max_tokens": 64000},
    "openai": {"id": "model-c", "object": "model", "created": 1, "owned_by": "openai",
               "shutdown_date": None},
    "ollama": {"id": "model-d", "object": "model", "created": 1, "owned_by": "library"},
}


ACCOUNT = {"id": "acc", "type": "openrouter", "baseUrl": "https://example.invalid"}


def one_pool(**extra):
    """A file of the new form with one pool of one step, `extra` on the pool."""
    cloud.save_cloud_data({"accounts": [dict(ACCOUNT)], "migrations": [],
                           "pools": [{"id": "p", "name": "P", "steps": [{"id": "acc", "accountId": "acc", "model": "m"}],
                                      **extra}]})


def test_pool_shape():
    print("CloudPools.pool — the window on a pool:")
    got = CloudPools.pool({"id": "p", "steps": []})
    check(sorted(got.keys()) == ["contextAuto", "id", "name", "steps"],
          f"a pool that states no window keeps four keys (got {sorted(got.keys())})")
    check(CloudPools.pool({"id": "p", "contextLength": 131072})["contextLength"] == 131072, "a stated contextLength is kept")
    # Every shape that is not a usable size must leave the key absent rather
    # than store a number a client would read as a real limit.
    for bad in (0, -1, "", None, "abc", False):
        check("contextLength" not in CloudPools.pool({"id": "p", "contextLength": bad}),
              f"contextLength={bad!r} leaves the key ABSENT")
    check(CloudPools.pool({"id": "p", "contextLength": "65536"})["contextLength"] == 65536,
          "a numeric string from a form field is accepted")
    one_pool()
    for bad in (-1, "abc"):
        try:
            PoolDesk().save_pool({"id": "p", "contextLength": bad})
            refused = False
        except AppError as exc:
            refused = exc.status == 400
        check(refused, f"negative: the board's save of contextLength={bad!r} is refused, not stored as nothing")


def test_catalog_cache():
    print("model_catalog.store_models:")
    model_catalog.store_models("acc", [dict(PROVIDER_ENTRIES["openrouter"]),
                                       dict(PROVIDER_ENTRIES["anthropic"])])
    entry = model_catalog.cached_models_entry("acc") or {}
    models = entry.get("models") or []
    check(len(models) == 2, f"both models cached (got {len(models)})")
    check(all("contextLength" not in m for m in models),
          "a raw provider entry carries no contextLength of its own, so none is cached")
    # What the fetch produces IS carried, and what it does not produce stays out.
    model_catalog.store_models("acc2", [{"id": "a", "name": "A", "contextLength": 131072},
                                        {"id": "b", "name": "B"}])
    rows = (model_catalog.cached_models_entry("acc2") or {}).get("models") or []
    by_id = {r["id"]: r for r in rows}
    check(by_id["a"].get("contextLength") == 131072, "a known window is cached")
    check("contextLength" not in by_id["b"], "an unknown window is ABSENT, not zero")


def test_narrowing():
    """Exercise the REAL fetch against a fake provider, not a re-implementation.

    A test that copies the narrowing it means to pin cannot fail when the
    narrowing changes, so the account's baseUrl is pointed at a local server
    that answers with each provider's real catalogue shape.
    """
    print("fetch_account_models against a fake provider:")
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import socket
    import threading
    from caravan.admin import cloud_api

    serve = {}

    class _P(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def do_GET(self):
            body = json.dumps(serve["payload"]).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    sock = socket.socket(); sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]; sock.close()
    srv = ThreadingHTTPServer(("127.0.0.1", port), _P)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    for kind, raw in PROVIDER_ENTRIES.items():
        serve["payload"] = {"data": [dict(raw)]}
        cloud.save_cloud_data({"accounts": [{"id": "acc", "type": "openai",
                                             "baseUrl": f"http://127.0.0.1:{port}"}], "blocks": []})
        model_catalog.record_ok("acc:models")
        got = cloud_api.fetch_account_models("acc")
        check(len(got) == 1, f"{kind}: one model returned (got {len(got)})")
        keys = sorted(got[0].keys()) if got else []
        reported = any(k in raw for k in ("context_length", "max_input_tokens", "context_window"))
        expect = ["contextLength", "id", "name"] if reported else ["id", "name"]
        check(keys == expect, f"{kind}: keys {keys}")
        check(("contextLength" in got[0]) == reported,
              f"{kind}: context {'reported and kept' if reported else 'not reported, none invented'}")
    # Anthropic answers with BOTH numbers; max_tokens is the output cap, not the
    # window. Taking it would under-report by 3.2x and fire a client's compressor
    # far too early — the mistake Hermes documents in its own resolver.
    serve["payload"] = {"data": [dict(PROVIDER_ENTRIES["anthropic"])]}
    model_catalog.record_ok("acc:models")
    got = cloud_api.fetch_account_models("acc")
    check(got[0].get("contextLength") == 204800,
          f"anthropic: the INPUT window is taken (got {got[0].get('contextLength')})")
    check(got[0].get("contextLength") != 64000, "anthropic: max_tokens is not mistaken for the window")
    srv.shutdown()


def test_save_preserves():
    print("PoolDesk.save_pool — an edit keeps what it does not send:")
    one_pool(contextLength=65536)
    again = PoolDesk().save_pool({"id": "p", "name": "Renamed"})
    check(again.get("contextLength") == 65536, f"a stated window survives an edit that does not send it (got {again.get('contextLength')})")
    # The editor always sends the field, so a blank one REMOVES it.
    cleared = PoolDesk().save_pool({"id": "p", "contextLength": ""})
    check("contextLength" not in cleared, "clearing the field in the editor removes it")



# ── what the proxy publishes as the window, and where it takes it from ───────
# Two sources can know it: the operator, on the pool, and the account's own
# catalogue, which caches whatever the provider last reported. The catalogue
# counts only when the operator ticked the switch. The file here is of the old
# form, a model block — the proxy reads it as a pool until it is rewritten.
def _provider_window(block_extra, cached):
    import importlib
    from caravan.proxy import cloud_auth
    cloud.save_cloud_data({
        "accounts": [{"id": "acc", "type": "openrouter", "baseUrl": "https://example.invalid"}],
        "blocks": [{"id": "b", "accountId": "acc", "model": "m", **block_extra}],
    })
    model_catalog.store_models("acc", [{"id": "m", "name": "M", **({"contextLength": cached} if cached else {})}])
    importlib.reload(cloud_auth)
    return (cloud_auth.load_cloud_provider("b") or {}).get("contextLength")


def test_provider_window_source():
    print("load_cloud_provider — which window reaches the proxy:")
    print("  switch OFF (the default) — only what the operator stated:")
    check(_provider_window({"contextLength": 131072}, 65536) == 131072,
          "stated 131072, catalogue says 65536 -> the operator's number")
    check(_provider_window({}, 65536) is None,
          "nothing stated -> ABSENT, even though the catalogue reports 65536: nobody chose it")
    check(_provider_window({}, None) is None, "neither knows -> absent, never guessed")
    check(_provider_window({"contextLength": 200000}, None) == 200000, "stated only -> that number")
    print("  switch ON — the provider's number, on purpose:")
    check(_provider_window({"contextAuto": True}, 65536) == 65536,
          "nothing stated, catalogue reports 65536 -> 65536")
    check(_provider_window({"contextAuto": True, "contextLength": 131072}, 65536) == 65536,
          "the provider's number wins while the switch is on, even over a stated one")
    check(_provider_window({"contextAuto": True, "contextLength": 131072}, None) == 131072,
          "provider reports nothing -> the stated number is the fallback, not silence")
    check(_provider_window({"contextAuto": True}, None) is None,
          "switch on and nobody knows -> still absent")


def test_pool_switch_shape():
    print("the pool's switch itself:")
    check(CloudPools.pool({"id": "p"})["contextAuto"] is False, "absent -> False, stored explicitly")
    for truthy in (True, "1", 1, "on"):
        check(CloudPools.pool({"id": "p", "contextAuto": truthy})["contextAuto"] is True, f"contextAuto={truthy!r} -> True")
    for falsy in (False, "", 0, None):
        check(CloudPools.pool({"id": "p", "contextAuto": falsy})["contextAuto"] is False, f"contextAuto={falsy!r} -> False")
    # An edit that omits the switch must not silently turn it off.
    one_pool(contextAuto=True)
    again = PoolDesk().save_pool({"id": "p", "name": "x"})
    check(again.get("contextAuto") is True, "the switch survives an edit that omits it")
    off = PoolDesk().save_pool({"id": "p", "contextAuto": False})
    check(off.get("contextAuto") is False, "and the editor, which always sends it, can turn it off")
    made = PoolDesk().create("", "acc", "new-model")
    check(made["contextAuto"] is True and made["name"] == "new-model",
          "a pool made on the board takes the providers' window, and its model's name")


def test_context_auto_migration():
    print("migrate_context_auto — the implicit choice, written down:")
    cloud.save_cloud_data({
        "accounts": [{"id": "acc", "type": "openrouter", "baseUrl": "https://example.invalid"}],
        "blocks": [
            {"id": "lived-off-fallback", "accountId": "acc", "model": "known"},
            {"id": "states-its-own", "accountId": "acc", "model": "known", "contextLength": 8192},
            {"id": "nobody-knows", "accountId": "acc", "model": "unknown"},
            {"id": "already-off", "accountId": "acc", "model": "known", "contextAuto": False},
            {"id": "already-on", "accountId": "acc", "model": "known", "contextAuto": True},
        ],
    })
    model_catalog.store_models("acc", [{"id": "known", "name": "K", "contextLength": 131072},
                                       {"id": "unknown", "name": "U"}])
    stamped = cloud.migrate_context_auto()
    by_id = {b["id"]: b for b in cloud.load_cloud_data()["blocks"]}
    check(stamped == 1, f"exactly one block was living off the fallback (got {stamped})")
    check(by_id["lived-off-fallback"].get("contextAuto") is True,
          "it keeps publishing the provider's real number — now as a visible choice")
    check("contextAuto" not in by_id["states-its-own"],
          "a block that states its own window is left alone")
    check("contextAuto" not in by_id["nobody-knows"],
          "a block whose provider reports nothing is left alone — there is nothing to choose")
    check(by_id["already-off"].get("contextAuto") is False,
          "an operator who already turned it OFF is not overridden")
    check(by_id["already-on"].get("contextAuto") is True, "and one who turned it on stays on")
    check(cloud.migrate_context_auto() == 0, "running it again changes nothing")

    # A block the operator creates AFTER the migration, leaving the window
    # empty on purpose. The docstring promised these keep the off default; the
    # controller restarts, the migration runs again, and it was stamped —
    # publishing a number nobody chose, which is what the switch was for.
    data = cloud.load_cloud_data()
    data["blocks"].append({"id": "made-later", "accountId": "acc", "model": "known"})
    cloud.save_cloud_data(data)
    stamped_again = cloud.migrate_context_auto()
    by_id = {b["id"]: b for b in cloud.load_cloud_data()["blocks"]}
    check(stamped_again == 0,
          f"a later restart stamps nothing — the migration already ran (got {stamped_again})")
    check("contextAuto" not in by_id["made-later"],
          f"a block created after it keeps the off default (got {by_id['made-later']!r})")
    check(by_id["lived-off-fallback"].get("contextAuto") is True,
          "and what it did stamp the first time is still stamped")

def test_board_state_carries_window():
    print("PoolDesk.state — what the board (and its editor) receives:")
    cloud.save_cloud_data({"accounts": [dict(ACCOUNT)], "migrations": [], "pools": [
        {"id": "stated", "name": "S", "contextLength": 65536, "contextAuto": True,
         "steps": [{"id": "acc", "accountId": "acc", "model": "m1"}]},
        {"id": "unstated", "name": "U", "steps": [{"id": "acc", "accountId": "acc", "model": "m2"}]}]})
    rows = {r["id"]: r for r in PoolDesk().state()}
    check(rows["stated"].get("contextLength") == 65536 and rows["stated"].get("contextAuto") is True,
          "defect-history: a stated window and the switch reach the board — they never did, so the editor opened "
          f"blank and its Save wiped both (got {rows['stated'].get('contextLength')}, {rows['stated'].get('contextAuto')})")
    check("contextLength" not in rows["unstated"] and rows["unstated"].get("contextAuto") is False,
          "negative: nothing stated -> the key is ABSENT (never 0), the switch is off")
    # The editor's round trip: it opens on the row and saves both fields back.
    row = rows["stated"]
    saved = PoolDesk().save_pool({"id": row["id"], "contextLength": row.get("contextLength") or "",
                                  "contextAuto": bool(row.get("contextAuto"))})
    check(saved.get("contextLength") == 65536 and saved.get("contextAuto") is True,
          f"an edit that changes nothing keeps the window and the switch (got {saved.get('contextLength')}, "
          f"{saved.get('contextAuto')})")


def test_subscription_catalogue():
    """The REAL subscription fetch against a fake codex/models answer.

    The ChatGPT subscription names each model's window as context_window, next
    to max_context_window, the most it can be raised to. Until 1.3.432 the fetch
    kept only slug and display_name, so a subscription block's "provider's
    window" switch had nothing to show. Only the network, the login and the
    client version are stood in; the narrowing is the real one.
    """
    print("fetch_subscription_models against a fake codex/models answer:")
    from unittest import mock
    from caravan.admin import cloud_api

    answer = {"models": [
        {"slug": "model-x", "display_name": "Model X", "visibility": "list", "supported_in_api": True,
         "context_window": 200000, "max_context_window": 800000, "auto_compact_token_limit": None},
        {"slug": "model-y", "display_name": "Model Y", "visibility": "list", "supported_in_api": True},
        {"slug": "model-hidden", "visibility": "hide", "supported_in_api": True, "context_window": 1000},
        {"slug": "model-no-api", "visibility": "list", "supported_in_api": False, "context_window": 1000},
    ]}
    asked = []

    class _Reply:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return json.dumps(answer).encode("utf-8")

    def _urlopen(req, timeout=None):
        asked.append(req.full_url)
        return _Reply()

    cloud.save_cloud_data({"accounts": [{"id": "sub", "type": "openai-subscription", "authMode": "oauth"}],
                           "blocks": []})
    model_catalog.record_ok("sub:models")
    with mock.patch.dict(os.environ, {"CARAVAN_CODEX_CLIENT_VERSION": "9.9.9"}), \
            mock.patch.object(cloud_api, "_subscription_auth_headers", return_value=("token", "account")), \
            mock.patch.object(cloud_api.urllib.request, "urlopen", _urlopen):
        got = cloud_api.fetch_subscription_models("sub")
    by_id = {m["id"]: m for m in got}
    check(asked == ["https://chatgpt.com/backend-api/codex/models?client_version=9.9.9"],
          f"one request to codex/models (got {asked})")
    check(sorted(by_id) == ["model-x", "model-y"],
          f"hidden and not-in-API models stay out, as before (got {sorted(by_id)})")
    check(by_id["model-x"].get("contextLength") == 200000,
          f"context_window is kept (got {by_id['model-x'].get('contextLength')})")
    check(by_id["model-x"].get("contextLength") != 800000,
          "negative: max_context_window, the most it can be raised to, is not taken for the window")
    check(sorted(by_id["model-x"]) == ["contextLength", "id", "name"] and by_id["model-x"]["name"] == "Model X",
          f"the entry is id, name and window (got {by_id['model-x']})")
    check("contextLength" not in by_id["model-y"],
          "negative: a model that names no window gets none (ABSENT, never 0)")


def test_pool_window():
    """A pool answers from whichever step serves: its window is the smallest
    any step names, and none when a step names none (CloudPools.window)."""
    print("a pool's window over its steps:")
    named = {("a", "m"): 272000, ("b", "m"): 200000}
    catalogue = lambda account, model: named.get((account, model))
    pool = {"contextAuto": True, "steps": [{"accountId": "a", "model": "m"}, {"accountId": "b", "model": "m"}]}
    check(CloudPools.window(pool, catalogue) == 200000, "the smaller window of the two steps")
    pool["steps"].reverse()
    check(CloudPools.window(pool, catalogue) == 200000, "the order of the steps does not change the window")
    pool["steps"].append({"accountId": "c", "model": "m"})
    check(CloudPools.window(pool, catalogue) is None, "negative: a step that names no window leaves the pool without one")
    check(CloudPools.window({"contextAuto": True, "steps": []}, catalogue) is None, "no step, no window")


for fn in (test_pool_shape, test_context_auto_migration, test_pool_switch_shape, test_provider_window_source, test_save_preserves, test_catalog_cache, test_narrowing, test_board_state_carries_window, test_subscription_catalogue, test_pool_window):
    fn()

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail:
        print("  - " + m)
    sys.exit(1)
print("all cloud-context snapshots hold")
