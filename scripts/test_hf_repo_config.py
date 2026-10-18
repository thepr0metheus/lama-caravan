#!/usr/bin/env python3
"""Value snapshot: every read of the hub carries the operator's token, config.json included (caravan/admin/hf.py).

A gated repository answers only to a token whose owner accepted its terms, and ANY file of it is refused without
one. The listing of a repository's tree carried the token (`_hf_request`); the read of its config.json did not
(`_fetch_repo_config`). The checkpoint's label ("BF16", "NVFP4", …) comes from that config, so a gated repository
the token could list answered 401 for the config and was labelled "SAFETENSORS": its files were laid out under
<model>/<author>/SAFETENSORS/ where a repository that is not gated lands under .../BF16/ (nvidia/Cosmos-Reason2-2B,
2026-10-13: the label read SAFETENSORS). The headers now come from one place, `_hf_headers`.

The hub is a stand-in: it refuses what carries no Authorization header, as a gated repository does. No network.

Run: python3 scripts/test_hf_repo_config.py
"""
import os
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("CARAVAN_DATA_DIR", tempfile.mkdtemp(prefix="caravan-repo-config-test-"))

import caravan.admin.hf as hf  # noqa: E402
import caravan.common.fetch as fetch  # noqa: E402
from caravan.admin.state import admin_state  # noqa: E402

_fail = []
TOKEN = "hf_test_not_a_real_token"
UA = {"User-Agent": "lama-caravan/1.0"}


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


class GatedHub:
    """config.json of a gated repository: the file for a bearer token, a refusal for everyone else."""

    def __init__(self, config):
        self.config = config
        self.asked = []

    def fetch_json(self, url, timeout=2, headers=None):
        self.asked.append({"url": url, "timeout": timeout, "headers": dict(headers or {})})
        if (headers or {}).get("Authorization", "").startswith("Bearer "):
            return self.config
        return {"ok": False, "error": "HTTP Error 401: Unauthorized"}


class Stand:
    """The hub's stand-in installed for one case, the operator's token set or not, and put back after it."""

    def __init__(self, config, token=""):
        self.hub = GatedHub(config)
        self.token = token

    def __enter__(self):
        self.saved = (fetch.fetch_json, admin_state.get("hfToken"), hf._hf_request)
        fetch.fetch_json = self.hub.fetch_json
        if self.token:
            admin_state["hfToken"] = self.token
        else:
            admin_state.pop("hfToken", None)
        return self.hub

    def __exit__(self, *exc):
        fetch.fetch_json, token, hf._hf_request = self.saved
        if token is None:
            admin_state.pop("hfToken", None)
        else:
            admin_state["hfToken"] = token


def tree():
    """The tree of a gated repository as the hub lists it for a token: weights and a config."""
    return [{"type": "file", "path": "config.json", "size": 1505, "oid": "a" * 40},
            {"type": "file", "path": "model.safetensors", "size": 4877470304, "oid": "e" * 40,
             "lfs": {"oid": "b" * 64, "size": 4877470304, "pointerSize": 135}}]


def label(token):
    """The checkpoint label hf_list_files gives the gated repository, for an operator with or without a token."""
    with Stand({"dtype": "bfloat16"}, token) as hub:
        hf._hf_request = lambda path, timeout=12, all_pages=False: tree()
        return hf.hf_list_files("nvidia/Gated-2B")["safetensors"]["format"], hub


def main():
    print("the headers of a read of the hub:")
    with Stand({}):
        check(hf._hf_headers() == UA, "no token: who asks, and nothing else")
    with Stand({}, TOKEN):
        check(hf._hf_headers() == {**UA, "Authorization": f"Bearer {TOKEN}"}, "a token: the bearer header beside it")

    print("config.json of a repository:")
    with Stand({"dtype": "bfloat16"}) as hub:
        got = hf._fetch_repo_config("nvidia/Gated-2B")
        check(hub.asked == [{"url": "https://huggingface.co/nvidia/Gated-2B/resolve/main/config.json", "timeout": 8,
                             "headers": UA}], f"no token: asked at its own address, 8 s, with no Authorization (got {hub.asked})")
        check(got == {"ok": False, "error": "HTTP Error 401: Unauthorized"},
              "no token: the refusal comes back as it was — a refusal, which reads as no config")
    with Stand({"dtype": "bfloat16"}, TOKEN) as hub:
        got = hf._fetch_repo_config("nvidia/Gated-2B")
        check(hub.asked[0]["headers"] == {**UA, "Authorization": f"Bearer {TOKEN}"},
              "a token: the same request carries it")
        check(got == {"dtype": "bfloat16"}, "a token the terms are accepted for: the config itself")

    print("the label of a gated checkpoint:")
    check(label("")[0] == "SAFETENSORS", "no token: nothing to read the type of the weights from — SAFETENSORS, as it was")
    check(label(TOKEN)[0] == "BF16",
          "a token with the terms: the config is read, the label is the type of the weights — BF16, like a repository that is not gated")
    with Stand({"dtype": "bfloat16"}, TOKEN) as hub:
        hub.fetch_json = lambda url, timeout=2, headers=None: {"ok": False, "error": "HTTP Error 403: Forbidden"}
        fetch.fetch_json = hub.fetch_json
        hf._hf_request = lambda path, timeout=12, all_pages=False: tree()
        check(hf.hf_list_files("nvidia/Gated-2B")["safetensors"]["format"] == "SAFETENSORS",
              "negative: a token whose owner has not accepted the terms is refused too — SAFETENSORS, never a guess")

    print("the tree request and the config request take their headers from one place:")
    seen = []

    class Reply:
        headers = {}                      # what an answer of urllib carries: no `Link`, no next page

        def __init__(self, body=b"[]"):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return self.body

    real_open = urllib.request.urlopen
    urllib.request.urlopen = lambda req, timeout=0: (seen.append(dict(req.header_items())), Reply())[1]
    try:
        with Stand({}, TOKEN):
            hf._hf_cache.clear()
            hf._hf_request("models/probe")
    finally:
        urllib.request.urlopen = real_open
    check(seen and seen[0].get("Authorization") == f"Bearer {TOKEN}" and seen[0].get("User-agent") == "lama-caravan/1.0",
          f"a request of the API carries the same bearer and agent (got {seen})")

    print("an answer read without a token is not handed to a request with one:")
    # A gated repository's tree answers a request with no token with masked hashes, and one with a token with the real ones;
    # the operator who saves a token must not read the first answer back for the next five minutes.
    urllib.request.urlopen = lambda req, timeout=0: Reply(b'["with"]' if req.get_header("Authorization") else b'["without"]')
    try:
        hf._hf_cache.clear()
        with Stand({}):
            first = hf._hf_request("models/gated/tree/main")
        with Stand({}, TOKEN):
            second = hf._hf_request("models/gated/tree/main")
            third = hf._hf_request("models/gated/tree/main")
    finally:
        urllib.request.urlopen = real_open
        hf._hf_cache.clear()
    check((first, second, third) == (["without"], ["with"], ["with"]),
          f"no token, then a token: the second read asks again and the third is the second's (got {(first, second, third)})")

    if _fail:
        print(f"FAILED ({len(_fail)}):")
        for msg in _fail:
            print("  - " + msg)
        sys.exit(1)
    print("hf repo-config snapshots hold")


if __name__ == "__main__":
    main()
