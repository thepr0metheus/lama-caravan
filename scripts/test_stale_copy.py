#!/usr/bin/env python3
"""Value snapshot: a save made from an older copy of the proxy lists is refused.

A page saves whole lists built from its own copy of the topology: Routing its routers with
every cable, the port form every route. On the NAS (2026-10-08, 09:04) a tab left open since the
morning saved its copy over the afternoon's and put back the cable of a deleted port. The
topology now names the version of each list (ProxyRevisions, caravan/admin/proxies_config.py); a
save sends it back, and one made from an older version is refused with 409 and the current
topology, nothing written. A save that names no version — a script's — goes through as before.

Each case runs against a throwaway config file; the fleet's is never touched.

Run: python3 scripts/test_stale_copy.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="caravan-stale-"))
CONFIG = TMP / "agent-proxies.json"
os.environ["AGENT_PROXY_CONFIG_FILE"] = str(CONFIG)
os.environ["LLAMA_ADMIN_STATE"] = str(TMP / "admin.json")
sys.path.insert(0, str(ROOT))

import caravan.admin.proxies_config as pc  # noqa: E402
from caravan.admin import routes  # noqa: E402

pc.ensure_agent_proxy_running = lambda timeout=30: {"ok": True, "stderr": ""}

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


CLOUD_OUT = {"id": "cb:m", "label": "m", "target": "cloud:acc", "upstreamType": "cloud",
             "providerId": "m", "accountId": "acc"}


def route_on(port):
    return {"label": f"p{port}", "port": port, "upstreamHost": "127.0.0.1", "upstreamPort": 8080,
            "enabled": True, "routerId": "router:default"}


def router(*edges):
    return [{"id": "router:default", "outputs": [CLOUD_OUT],
             "graph": {"nodes": [], "edges": [{"id": eid, "from": frm, "to": "out:cb:m"} for eid, frm in edges]}}]


def fresh():
    """The file as the controller writes it: two ports, the first one wired."""
    CONFIG.write_text(json.dumps({"routes": [route_on(23001), route_on(23002)],
                                  "routers": router(("e1", "in:skynet:proxy:23001"))}), encoding="utf-8")
    pc.set_routers(pc.load_agent_proxy_config()["routers"])     # stored in the written form
    return pc.PROXY_REVISIONS.current()


def edges():
    return [e["id"] for e in pc.read_agent_proxy_payload()["routers"][0]["graph"]["edges"]]


def goes(call):
    """Whether a save went through: a refusal is an answer here, not a crash of the snapshot."""
    try:
        call()
    except pc.StaleCopy:
        return False
    return True


def refused(call):
    before = CONFIG.read_bytes()
    try:
        call()
    except pc.StaleCopy as exc:
        return exc.status, CONFIG.read_bytes() == before
    return None, CONFIG.read_bytes() == before


print("versions name what is stored:")
seen = fresh()
check(set(seen) == {"routes", "routers"} and all(len(v) == 16 for v in seen.values())
      and seen == pc.ProxyRevisions.of(pc.read_agent_proxy_payload()) == pc.PROXY_REVISIONS.current(),
      "a version per list, the same on every reading of the same file")
payload = pc.read_agent_proxy_payload()
payload["computedThresholds"] = {"computedAt": "2026-10-08T00:00:00Z"}
pc.write_agent_proxy_payload(payload)
check(pc.PROXY_REVISIONS.current() == seen,
      "negative: a mirror no page sends (computedThresholds) leaves both versions as they were")
check(pc.ProxyRevisions.of({"routes": [{"a": 1, "b": 2}]})["routes"] == pc.ProxyRevisions.of({"routes": [{"b": 2, "a": 1}]})["routes"],
      "negative: the order of keys in the file is not a new version")

print("Routing's routers:")
seen = fresh()
went = goes(lambda: pc.set_routers(router(("e1", "in:skynet:proxy:23001"), ("e2", "in:skynet:proxy:23002")), seen["routers"]))
now = pc.PROXY_REVISIONS.current()
check(went and edges() == ["e1", "e2"] and now["routers"] != seen["routers"] and now["routes"] == seen["routes"],
      "a save from the current version goes through and moves the routers' version on, not the routes'")
check(refused(lambda: pc.set_routers(router(("e1", "in:skynet:proxy:23001")), seen["routers"])) == (409, True),
      "a save from the version before it is refused with 409, and the file is left byte for byte as it was")
check(edges() == ["e1", "e2"], "…the newer cable stays")
check(goes(lambda: pc.set_routers(router(("e3", "in:skynet:proxy:23002")))) and edges() == ["e3"],
      "negative: a save that names no version goes through — a script that knows nothing of versions")
check(goes(lambda: pc.set_routers(router(("e4", "in:skynet:proxy:23002")), "")) and edges() == ["e4"],
      "negative: an empty version is no version")

print("the port form's routes:")
seen = fresh()
went = goes(lambda: pc.save_agent_proxy_config([route_on(23001)], None, seen["routes"]))
now = pc.PROXY_REVISIONS.current()
ports = [r["port"] for r in pc.read_agent_proxy_payload()["routes"]]
check(went and ports == [23001] and now["routes"] != seen["routes"],
      "a list from the current version goes through: port 23002 deleted")
check(refused(lambda: pc.save_agent_proxy_config([route_on(23001), route_on(23002)], None, seen["routes"])) == (409, True),
      "an old tab's list, with 23002 still in it, is refused and brings nothing back")
check([r["port"] for r in pc.read_agent_proxy_payload()["routes"]] == [23001], "…the deleted port stays deleted")
check(goes(lambda: pc.save_agent_proxy_config([route_on(23001), route_on(23003)], None, now["routes"]))
      and [r["port"] for r in pc.read_agent_proxy_payload()["routes"]] == [23001, 23003],
      "negative: the same list made again on the current version goes through")


class Handler:
    def __init__(self):
        self.sent = []

    def send_json(self, body, status=200):
        self.sent.append((status, body))


def post(path, body):
    keep = routes.topology_state, routes.system_monitor_state
    routes.topology_state = lambda refresh_hosts=True: {"marker": "current", "proxyRevisions": pc.PROXY_REVISIONS.current()}
    routes.system_monitor_state = lambda: {}
    try:
        h = Handler()
        routes.POST_ROUTES[path](h, urlparse(path), body)
        return h.sent[0]
    finally:
        routes.topology_state, routes.system_monitor_state = keep


print("the answers the page reads:")
seen = fresh()
goes(lambda: pc.set_routers(router(("e2", "in:skynet:proxy:23002")), seen["routers"]))
status, body = post("/api/agent-proxies/routers", {"routers": router(("e1", "in:skynet:proxy:23001")), "revision": seen["routers"]})
check(status == 409 and body.get("stale") is True and body["topology"]["marker"] == "current"
      and body["topology"]["proxyRevisions"] == pc.PROXY_REVISIONS.current() and "changed since" in body["error"],
      "routing: 409 with `stale` and the current topology — the page makes its change again on that")
status, body = post("/api/agent-proxies/routers", {"routers": router(("e5", "in:skynet:proxy:23002")),
                                                    "revision": pc.PROXY_REVISIONS.current()["routers"]})
check(status == 200 and body.get("ok") is True and edges() == ["e5"], "negative: the current version answers 200 and saves")
seen = pc.PROXY_REVISIONS.current()
goes(lambda: pc.save_agent_proxy_config([route_on(23002)], None, seen["routes"]))
status, body = post("/api/agent-proxies/config", {"routes": [route_on(23001), route_on(23002)], "revision": seen["routes"]})
check(status == 409 and body.get("stale") is True and body["topology"]["marker"] == "current",
      "port form: 409 with `stale` and the current topology")
check([r["port"] for r in pc.read_agent_proxy_payload()["routes"]] == [23002], "…and port 23001 stays deleted")

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail:
        print("  - " + m)
    sys.exit(1)
print("stale copy snapshot holds: versions per list, refusals by value")
