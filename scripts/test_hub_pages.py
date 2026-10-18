#!/usr/bin/env python3
"""Value snapshot: a list the hub sends in pages is read to its end (caravan/admin/hub_pages.py, hf.py).

The incident (2026-10-15): the tree of openbmb/MiniCPM-o-4_5-awq has 75 files and the hub sends it 50
entries to a page when file details are asked for. The first page was the folder `assets/`; the weights
came after it. The /hf page read the first page and called it the repository: "34 files · 1.4 GB", and a
button that would have downloaded the extras without the model.

Pinned here, claim by claim, each with the answer that would pass it wrongly:
  * the next page is named by the `Link` header, and only an address of the hub's own API is followed
    (the request carries the operator's token);
  * the pages are joined in the hub's order, and the read ends at the page that names no next one;
  * a list that cannot be read to its end is an ERROR, never the pages read so far;
  * the tree is read to its end, a search is not (the hub would send every repository it has).

No network is touched: the hub is a fake that answers by address.

Run: python3 scripts/test_hub_pages.py
"""
import os
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("CARAVAN_DATA_DIR", tempfile.mkdtemp(prefix="caravan-hub-pages-test-"))

import caravan.admin.hf as hf  # noqa: E402
from caravan.admin.hub_pages import HubPages, HubPagesError  # noqa: E402
from caravan.admin.state import admin_state  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def refused(fn, *args):
    try:
        fn(*args)
    except HubPagesError as exc:
        return str(exc)
    return None


API = "https://huggingface.co/api/models/org/Repo/tree/main"
TREE = f"{API}?recursive=true&expand=true"


def link(url):
    return f'<{url}>; rel="next"'


class Hub:
    """A hub that answers a page by its address: {url: (data, link header)}; asks are remembered."""

    def __init__(self, pages):
        self.pages = pages
        self.asked = []

    def __call__(self, url):
        self.asked.append(url)
        if url not in self.pages:
            raise OSError(f"HTTP Error 404: {url}")
        return self.pages[url]


def entry(path, size=1):
    return {"type": "file", "path": path, "size": size, "oid": "a" * 40,
            "lastCommit": {"id": "c", "title": "t", "date": "2026-10-01T00:00:00.000Z"}}


def main():
    print("the size of a page:")
    check(HubPages.sized(TREE) == f"{TREE}&limit=100",
          f"no limit named: the largest page the hub allows with `expand` (got {HubPages.sized(TREE)})")
    check(HubPages.sized(f"{TREE}&limit=20") == f"{TREE}&limit=20", "negative: a limit the caller named stays")
    check(HubPages.sized(f"{API}") == f"{API}?limit=100", "an address with no query gets one")

    print("the next page, as the hub names it:")
    first = f"{TREE}&limit=50&cursor=ZXlK%3D"
    check(HubPages.next_url(link(first)) == first, "the address of `rel=\"next\"`, with its cursor as sent")
    check(HubPages.next_url("") == "" and HubPages.next_url(None) == "", "no header: no next page")
    check(HubPages.next_url(f'<{TREE}&cursor=a>; rel="prev"') == "", "negative: only `next` is followed, not `prev`")
    check(HubPages.next_url(f'<{TREE}&cursor=a>; rel="prev", <{first}>; rel="next"') == first,
          "several links in one header: the `next` among them")
    check(HubPages.next_url(f'<{first}>; rel="nextish"') == "", "negative: a relation that only starts with `next` is not it")
    for bad, why in (("https://evil.example/api/models/x/tree/main?cursor=1", "another host"),
                     ("http://huggingface.co/api/models/x/tree/main?cursor=1", "plain http"),
                     ("https://huggingface.co/not-the-api/x?cursor=1", "a path outside the API"),
                     ("https://huggingface.co.evil.example/api/x?cursor=1", "a host that only begins like the hub")):
        said = refused(HubPages.next_url, link(bad))
        check(said and "outside its API" in said, f"negative: {why} is refused, not followed (it would carry the token) — {said}")

    print("reading a list to its end:")
    p1, p2, p3 = f"{TREE}&limit=100", f"{TREE}&limit=100&cursor=2", f"{TREE}&limit=100&cursor=3"
    hub = Hub({p1: ([entry("a"), entry("b")], link(p2)), p2: ([entry("c")], link(p3)), p3: ([entry("d"), entry("e")], "")})
    got = HubPages(hub).read(TREE)
    check([e["path"] for e in got] == ["a", "b", "c", "d", "e"], f"three pages are one list, in the hub's order (got {[e['path'] for e in got]})")
    check(hub.asked == [p1, p2, p3], f"each page is asked once, the first with the page size (asked {hub.asked})")

    one = Hub({p1: ([entry("a")], "")})
    check([e["path"] for e in HubPages(one).read(TREE)] == ["a"] and one.asked == [p1],
          "a list of one page is read with one request")
    check(HubPages(Hub({p1: ([], "")})).read(TREE) == [], "an empty list is an empty list")

    print("a list that cannot be read to its end is an error:")
    broken = Hub({p1: ([entry("a")], link(p2))})          # the second page is not there: 404
    try:
        HubPages(broken).read(TREE)
        check(False, "negative: the second page fails and the first is handed back as the list")
    except OSError as exc:
        check("404" in str(exc), f"negative: the failure of a later page reaches the caller, not the pages before it ({exc})")
    endless = Hub({})

    def endless_get(url):
        endless.asked.append(url)
        return [entry("x")], link(f"{TREE}&cursor={len(endless.asked)}")
    said = refused(HubPages(endless_get).read, TREE)
    check(said and "not read to the end" in said and len(endless.asked) == HubPages.MAX_PAGES,
          f"negative: more pages than the limit is an error after exactly {HubPages.MAX_PAGES} requests, not a short list — {said}")
    said = refused(HubPages(Hub({p1: ([entry("a")], link("https://evil.example/api/x"))})).read, TREE)
    check(said and "outside its API" in said, f"negative: a next page of another host ends the read with an error — {said}")
    odd = HubPages(Hub({p1: ({"error": "Repository not found"}, "")})).read(TREE)
    check(odd == {"error": "Repository not found"}, "an answer that is no list is handed back as it came (the caller reads its error)")
    said = refused(HubPages(Hub({p1: ([entry("a")], link(p2)), p2: ({"error": "x"}, "")})).read, TREE)
    check(said and "not a list" in said, f"negative: a later page that is no list is an error — {said}")

    print("hf._hf_request over a hub that sends pages:")
    seen = []
    # TREE with no limit is what a read of ONE page asks for: the hub's first page, 50 to a page, names a next one too.
    answers = {TREE: (b'[{"path":"a"},{"path":"b"}]', link(p2)), p1: (b'[{"path":"a"},{"path":"b"}]', link(p2)),
               p2: (b'[{"path":"c"}]', "")}

    class Reply:
        def __init__(self, body, header):
            self.body, self.headers = body, ({"Link": header} if header else {})

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return self.body

    def urlopen(req, timeout=0):
        seen.append((req.full_url, req.get_header("Authorization")))
        if req.full_url not in answers:
            raise OSError("HTTP Error 404: Not Found")
        return Reply(*answers[req.full_url])

    real_open, saved_token = urllib.request.urlopen, admin_state.get("hfToken")
    urllib.request.urlopen = urlopen
    admin_state["hfToken"] = "hf_test_token_value"
    try:
        hf._hf_cache.clear()
        path = "models/org/Repo/tree/main?recursive=true&expand=true"
        got = hf._hf_request(path, all_pages=True)
        check([e["path"] for e in got] == ["a", "b", "c"], f"the tree is read to its end (got {got})")
        check(all(auth == "Bearer hf_test_token_value" for _, auth in seen) and len(seen) == 2,
              "every page of the list is asked with the same headers as the first — the token included")
        again = hf._hf_request(path, all_pages=True)
        check(again == got and len(seen) == 2, "the whole list is cached: the second read asks nobody")
        single = hf._hf_request(path)
        check(isinstance(single, list) and [e["path"] for e in single] == ["a", "b"],
              f"negative: the read of ONE page is not served the cached whole list (got {single})")
        hf._hf_cache.clear()
        answers.pop(p2)
        failed = hf._hf_request(path, all_pages=True)
        check(isinstance(failed, dict) and "404" in failed.get("_error", ""),
              f"negative: the second page fails: the answer is the error, not the first page's two files (got {failed})")
    finally:
        urllib.request.urlopen = real_open
        admin_state["hfToken"] = saved_token
        hf._hf_cache.clear()

    print("who reads to the end and who does not:")
    asked = []
    real = hf._hf_request

    def fake(path, timeout=12, all_pages=False):
        asked.append((path.split("?")[0], all_pages))
        return []
    hf._hf_request = fake
    try:
        hf.hf_list_files("org/Repo")
        hf.hf_search("gemma")
    finally:
        hf._hf_request = real
    check(("models/org/Repo/tree/main", True) in asked, "the tree of a repository is read to its end")
    check(("models", False) in asked, "negative: a search is read one page: the hub would send every repository it has")

    print("the incident: weights listed after a folder of 50 extras:")
    assets = [entry(f"assets/s{n:02d}.wav", 10) for n in range(50)]
    weights = [entry("config.json", 100), entry("model-00001-of-00002.safetensors", 5_000), entry("model-00002-of-00002.safetensors", 3_000)]
    pages = Hub({p1: (assets, link(p2)), p2: (weights, "")})
    real_req, real_cfg = hf._hf_request, hf._fetch_repo_config
    hf._hf_request = lambda path, timeout=12, all_pages=False: HubPages(pages).read(TREE) if all_pages else pages(p1)[0]
    hf._fetch_repo_config = lambda repo_id: {"dtype": "bfloat16"}
    try:
        listed = hf.hf_list_files("org/Repo")
        first_page_only = [e["path"] for e in pages(p1)[0]]
    finally:
        hf._hf_request, hf._fetch_repo_config = real_req, real_cfg
    names = [f["name"] for f in listed["safetensors"]["files"]]
    check("model-00001-of-00002.safetensors" in names and "model-00002-of-00002.safetensors" in names,
          "the weights that sit after the 50 extras are in the checkpoint's plan")
    check(listed["safetensors"]["totalSize"] == 50 * 10 + 100 + 5_000 + 3_000,
          f"the plan's size counts the weights (got {listed['safetensors']['totalSize']})")
    check("model-00001-of-00002.safetensors" not in first_page_only, "negative: the first page alone does not hold the weights — the old read missed them")

    if _fail:
        print(f"FAILED ({len(_fail)}):")
        for msg in _fail:
            print("  - " + msg)
        sys.exit(1)
    print("hub pages snapshots hold")


if __name__ == "__main__":
    main()
