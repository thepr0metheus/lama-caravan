#!/usr/bin/env python3
"""Regression tests for agent proxy auto-provisioning.

The case that matters is the one that took the fleet down on 2026-07-20: an
assignment naming a proxy port that no longer exists. The gate calls that agent
un-provisioned and mints a fresh port — so the ONLY thing that can end the loop
is writing that port back into the assignment. The old code appended a route
"if the role is missing", which is never true here, so every pass minted another
port. At board-polling rate that is a port every second or two, forever.

A loop like that cannot be caught by reading the function: both halves look
correct on their own. It is only visible by running provisioning twice and
checking that the second pass is a no-op. Hence this file.

Run: python3 scripts/test_auto_provision.py
"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FAILURES = []


def check(name, condition, detail=""):
    if condition:
        print(f"  ok   {name}")
    else:
        print(f"  FAIL {name}  {detail}")
        FAILURES.append(name)


def load_module():
    import caravan.admin.fleet_clients as fc
    return fc


def make_harness(fc, assignments, routes):
    """Point the module's collaborators at in-memory state."""
    store = {"assignments": assignments}
    written = {}

    fc.topology_store = lambda: store
    fc.load_agent_proxy_config = lambda: {"routes": list(routes), "policy": {},
                                          "routers": [], "stopRequests": []}
    fc.normalize_agent_proxy_policy = lambda _p: {}
    fc.normalize_routers = lambda _r, _routes: []

    def _write(payload):
        written["payload"] = payload
        routes[:] = payload["routes"]
    fc.write_agent_proxy_payload = _write
    fc.save_admin_state = lambda: None
    restarts = []
    fc.restart_agent_proxy = lambda **kw: restarts.append(kw)
    return store, routes, written, restarts


CLIENT = {
    "id": "foreman",
    "agentUrl": "http://10.0.0.2:8092",
    "agents": [{"id": "cerberus", "name": "Cerberus"}],
}


def test_stale_assignment_heals():
    """An assignment pointing at a deleted port must be repointed, not re-minted."""
    fc = load_module()
    assignments = {"foreman": {"agentUrl": "", "assignments": [
        {"agentId": "cerberus", "routes": [{
            "role": "primary",
            "proxyId": "skynet:proxy:9999",          # this port is gone
            "endpoint": "http://10.0.0.1:9999/v1",
        }]},
    ]}}
    routes = []
    store, routes, _written, _restarts = make_harness(fc, assignments, routes)

    fc.auto_provision_agent_proxies(CLIENT)
    after_first = [r["port"] for r in routes]
    check("first pass mints exactly one port", len(after_first) == 1, after_first)

    minted = after_first[0]
    route = store["assignments"]["foreman"]["assignments"][0]["routes"][0]
    check("assignment now names the minted port",
          route["proxyId"] == f"skynet:proxy:{minted}", route)
    check("endpoint follows the proxyId",
          route["endpoint"].endswith(f":{minted}/v1"), route)

    # The whole point: run it again exactly as the heartbeat would.
    fc.auto_provision_agent_proxies(CLIENT)
    fc.auto_provision_agent_proxies(CLIENT)
    check("further passes mint nothing", [r["port"] for r in routes] == after_first,
          [r["port"] for r in routes])


def test_fresh_agent_provisions_once():
    fc = load_module()
    assignments = {}
    routes = []
    store, routes, _written, _restarts = make_harness(fc, assignments, routes)

    fc.auto_provision_agent_proxies(CLIENT)
    first = [r["port"] for r in routes]
    check("fresh agent gets one port", len(first) == 1, first)
    check("port comes from the configured base",
          first[0] == fc.AGENT_PROXY_BASE_PORT, first)

    fc.auto_provision_agent_proxies(CLIENT)
    check("provisioning is idempotent", [r["port"] for r in routes] == first,
          [r["port"] for r in routes])


def test_manual_agent_is_left_alone():
    """A hand-wired agent must survive provisioning, even with a dead proxyId.

    This is the whole contract behind "wire it by hand": the provisioner runs on
    every heartbeat, so anything it does not deliberately skip, it overwrites
    within seconds — and the operator gets no message saying why their choice
    disappeared.
    """
    fc = load_module()
    assignments = {"foreman": {"agentUrl": "", "assignments": [
        {"agentId": "cerberus", "manual": True, "routes": [{
            "role": "primary",
            "proxyId": "skynet:proxy:9999",      # deliberately not a live port
            "endpoint": "http://10.0.0.1:9999/v1",
        }]},
    ]}}
    routes = []
    store, routes, _w, _r = make_harness(fc, assignments, routes)

    for _ in range(3):
        fc.auto_provision_agent_proxies(CLIENT)

    check("manual agent mints no ports", routes == [], routes)
    route = store["assignments"]["foreman"]["assignments"][0]["routes"][0]
    check("manual agent keeps the operator's port",
          route["proxyId"] == "skynet:proxy:9999", route)
    check("the manual flag survives", 
          store["assignments"]["foreman"]["assignments"][0].get("manual") is True)


def test_no_service_restart():
    """Binding is the listener_watcher's job; a restart drops every other port."""
    fc = load_module()
    routes = []
    _store, routes, _written, restarts = make_harness(fc, {}, routes)
    fc.auto_provision_agent_proxies(CLIENT)
    check("provisioning does not restart the proxy service", restarts == [], restarts)


def main():
    print("auto-provisioning:")
    test_stale_assignment_heals()
    test_fresh_agent_provisions_once()
    test_manual_agent_is_left_alone()
    test_no_service_restart()
    if FAILURES:
        print(f"\n{len(FAILURES)} failed: {', '.join(FAILURES)}")
        return 1
    print("\nall passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
