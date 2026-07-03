"""Cross-domain proxy actions: reconcile the proxy daemon\'s view with the
admin config and stop a route (kills the in-flight request via stopRequests)."""
import json
import os
import re
import time

from caravan.admin.fleet_clients import refresh_topology_clients_from_agents
from caravan.admin.paths import TOPOLOGY_SERVER_IP
from caravan.admin.proxies_config import (
    load_agent_proxy_config,
    save_agent_proxy_config,
    write_agent_proxy_payload,
)
from caravan.admin.proxy_stats import agent_proxy_sample
from caravan.admin.state import save_admin_state, topology_store
from caravan.common.errors import AppError


def reconcile_agent_proxies():
    """Clean up proxy/assignment drift from re-provisioning:
      • rewrite each ONLINE agent's stored assignment to match what it LIVE-uses
        (primary = the proxy the agent reports) + the contiguous pair fallback (P+1);
      • delete proxy routes no assignment references anymore (the stale duplicate set).
    Offline agents (no live report) are left untouched. Returns a summary."""
    try:
        refresh_topology_clients_from_agents()
    except Exception:
        pass
    store = topology_store()
    server_ip = TOPOLOGY_SERVER_IP
    cfg = load_agent_proxy_config()
    routes = cfg["routes"]
    fb_ports = {int(r["port"]) for r in routes
                if str(r.get("role") or "") == "fallback" or re.search(r"fallback$", str(r.get("label") or ""), re.I)}
    assignments_store = store.setdefault("assignments", {})
    reassigned = 0
    for host_id, client in store.get("clients", {}).items():
        live = client.get("assignments")
        if not isinstance(live, list) or not live:
            continue
        host_entry = assignments_store.setdefault(host_id, {"agentUrl": client.get("agentUrl", ""), "assignments": []})
        existing = {a.get("agentId"): a for a in host_entry.get("assignments", [])}
        new_list = []
        live_ids = set()
        for la in live:
            aid = la.get("agentId")
            if not aid:
                continue
            live_ids.add(aid)
            prim = next((r for r in (la.get("routes") or []) if (r.get("role") or "primary") == "primary"), None)
            try:
                port = int(str((prim or {}).get("proxyId") or "").split(":")[-1])
            except (TypeError, ValueError):
                port = 0
            if not port:
                if aid in existing:
                    new_list.append(existing[aid])
                continue
            rts = [{"role": "primary", "proxyId": f"skynet:proxy:{port}", "endpoint": f"http://{server_ip}:{port}/v1"}]
            if (port + 1) in fb_ports:
                rts.append({"role": "fallback", "proxyId": f"skynet:proxy:{port + 1}", "endpoint": f"http://{server_ip}:{port + 1}/v1"})
            new_list.append({"agentId": aid, "routes": rts})
        tombstoned = set(store.get("deletedAgents", {}).get(host_id, []))
        for aid, a in existing.items():  # keep offline agents' assignments as-is — but not tombstoned ones
            if aid not in live_ids and aid not in tombstoned:
                new_list.append(a)
        if json.dumps(host_entry.get("assignments")) != json.dumps(new_list):
            host_entry["assignments"] = new_list
            reassigned += 1
    # Ports still referenced by any assignment → keep; the rest are stale dups → delete.
    referenced = set()
    for host_entry in assignments_store.values():
        for a in host_entry.get("assignments", []):
            for r in a.get("routes", []):
                pid = str(r.get("proxyId") or "")
                if pid.startswith("skynet:proxy:"):
                    try:
                        referenced.add(int(pid.split(":")[-1]))
                    except ValueError:
                        pass
    kept = [r for r in routes if int(r["port"]) in referenced]
    deleted = sorted(int(r["port"]) for r in routes if int(r["port"]) not in referenced)
    save_admin_state()
    if deleted:
        save_agent_proxy_config(kept)   # rewrites file + restarts agent-proxies + re-normalizes routers
    return {"reassigned": reassigned, "deletedPorts": deleted, "keptPorts": sorted(int(r["port"]) for r in kept)}

def stop_agent_proxy_route(port=None, request_id=None):
    payload = load_agent_proxy_config()
    route = None
    if port is not None:
        for row in payload["routes"]:
            if int(row.get("port") or 0) == int(port):
                route = row
                break
        if not route:
            raise AppError("proxy route not found", 404)
    targets = []
    if request_id:
        targets.append({"id": str(request_id), "route": route.get("label") if route else "", "port": int(route.get("port")) if route else None})
    elif route:
        state = agent_proxy_sample()
        for row in (state.get("agents") or {}).values():
            for item in row.get("active", []) or []:
                if int(item.get("port") or 0) == int(route.get("port")) and item.get("id"):
                    targets.append({"id": str(item.get("id")), "route": item.get("route") or route.get("label"), "port": int(route.get("port"))})
    stop_rows = [{
        "id": target["id"],
        "scope": "request",
        "route": target.get("route") or "",
        "port": target.get("port"),
        "reason": "manual stop",
        "requestedAt": int(time.time()),
    } for target in targets]
    stops = [row for row in payload.get("stopRequests", []) if str(row.get("id") or "") not in {item["id"] for item in stop_rows}]
    stops.extend(stop_rows)
    payload["stopRequests"] = stops[-100:]
    write_agent_proxy_payload(payload)
    return {"stopped": stop_rows}
