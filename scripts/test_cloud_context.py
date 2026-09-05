#!/usr/bin/env python3
"""Characterization snapshot: what the cloud path does with a context window.

Pins the VALUE at the three places a cloud model's context could survive or be
lost — the provider fetch that narrows each catalogue entry, the per-account
catalogue cache, and the model block the operator edits — plus what the proxy
publishes for a cloud upstream.

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


def test_block_shape():
    print("normalize_cloud_block:")
    cloud.save_cloud_data({"accounts": [{"id": "acc", "type": "openrouter",
                                         "baseUrl": "https://example.invalid"}], "blocks": []})
    got = cloud.normalize_cloud_block({"id": "blk", "accountId": "acc", "name": "B",
                                       "model": "vendor/model-a", "exposed": True}, {"acc"})
    check(sorted(got.keys()) == ["accountId", "contextAuto", "exposed", "id", "model", "modelMode", "name"],
          f"a block that states no window keeps seven keys (got {sorted(got.keys())})")
    got2 = cloud.normalize_cloud_block({"id": "blk", "accountId": "acc", "model": "m",
                                        "contextLength": 131072}, {"acc"})
    check(got2.get("contextLength") == 131072, "a stated contextLength is kept")
    # Every shape that is not a usable size must leave the key absent rather
    # than store a number a client would read as a real limit.
    for bad in (0, -1, "", None, "abc", False):
        out = cloud.normalize_cloud_block({"id": "b", "accountId": "acc", "model": "m",
                                           "contextLength": bad}, {"acc"})
        check("contextLength" not in out, f"contextLength={bad!r} leaves the key ABSENT")
    out = cloud.normalize_cloud_block({"id": "b", "accountId": "acc", "model": "m",
                                       "contextLength": "65536"}, {"acc"})
    check(out.get("contextLength") == 65536, "a numeric string from a form field is accepted")


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


def test_upsert_preserves():
    print("upsert_cloud_block:")
    cloud.save_cloud_data({"accounts": [{"id": "acc", "type": "openrouter",
                                         "baseUrl": "https://example.invalid"}], "blocks": []})
    cloud.upsert_cloud_block({"id": "b", "accountId": "acc", "model": "m",
                              "contextLength": 65536, "exposed": True})
    # A re-fetch upserts without either field; neither may be lost.
    again = cloud.upsert_cloud_block({"id": "b", "accountId": "acc", "model": "m"})
    check(again.get("contextLength") == 65536, f"a stated window survives a re-fetch (got {again.get('contextLength')})")
    check(again.get("exposed") is True, "and so does the exposed choice")
    # The editor always sends the field, so a blank one REMOVES it.
    cleared = cloud.upsert_cloud_block({"id": "b", "accountId": "acc", "model": "m",
                                        "contextLength": "", "exposed": True})
    check("contextLength" not in cleared, "clearing the field in the editor removes it")



# ── what the proxy publishes as the window, and where it takes it from ───────
# Two sources can know it: the operator, on the block, and the account's own
# catalogue, which caches whatever the provider last reported. Today the
# catalogue is a silent FALLBACK — a block that states nothing still gets the
# reported number without anybody choosing that.
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


def test_block_switch_shape():
    print("normalize_cloud_block — the switch itself:")
    cloud.save_cloud_data({"accounts": [{"id": "acc", "type": "openrouter",
                                         "baseUrl": "https://example.invalid"}], "blocks": []})
    out = cloud.normalize_cloud_block({"id": "b", "accountId": "acc", "model": "m"}, {"acc"})
    check(out.get("contextAuto") is False, "absent in the payload -> False, stored explicitly")
    for truthy in (True, "1", 1, "on"):
        got = cloud.normalize_cloud_block({"id": "b", "accountId": "acc", "model": "m",
                                           "contextAuto": truthy}, {"acc"})
        check(got.get("contextAuto") is True, f"contextAuto={truthy!r} -> True")
    for falsy in (False, "", 0, None):
        got = cloud.normalize_cloud_block({"id": "b", "accountId": "acc", "model": "m",
                                           "contextAuto": falsy}, {"acc"})
        check(got.get("contextAuto") is False, f"contextAuto={falsy!r} -> False")
    # A re-fetch that omits the switch must not silently turn it off.
    cloud.save_cloud_data({"accounts": [{"id": "acc", "type": "openrouter",
                                         "baseUrl": "https://example.invalid"}], "blocks": []})
    cloud.upsert_cloud_block({"id": "b", "accountId": "acc", "model": "m", "contextAuto": True})
    again = cloud.upsert_cloud_block({"id": "b", "accountId": "acc", "model": "m"})
    check(again.get("contextAuto") is True, "the switch survives a re-fetch that omits it")
    off = cloud.upsert_cloud_block({"id": "b", "accountId": "acc", "model": "m", "contextAuto": False})
    check(off.get("contextAuto") is False, "and the editor, which always sends it, can turn it off")


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

for fn in (test_block_shape, test_context_auto_migration, test_block_switch_shape, test_provider_window_source, test_upsert_preserves, test_catalog_cache, test_narrowing):
    fn()

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail:
        print("  - " + m)
    sys.exit(1)
print("all cloud-context snapshots hold")
