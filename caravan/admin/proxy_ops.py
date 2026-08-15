"""Cross-domain proxy actions: reconcile the proxy daemon\'s view with the
admin config and stop a route (kills the in-flight request via stopRequests)."""
import json
import os
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


def reconcile_agent_proxies(dry_run=False):
    """Clean up proxy/assignment drift from re-provisioning:
      • rewrite each ONLINE agent's stored assignment to match what it LIVE-uses
        (primary = the proxy the agent reports);
      • delete proxy routes no assignment references anymore (the stale duplicate set).
    Offline agents (no live report) are left untouched. Returns a summary.

    With dry_run the plan is computed and NOTHING is written — same code path,
    so the preview cannot describe a different operation than the one that runs.
    That matters here more than usual: this function deletes routes, and the
    first time it ran after service bridges were introduced it deleted three
    live ones. A destructive action whose only account of itself arrives
    afterwards is one an operator has no way to refuse.
    """
    try:
        refresh_topology_clients_from_agents()
    except Exception:
        pass
    store = topology_store()
    server_ip = TOPOLOGY_SERVER_IP
    cfg = load_agent_proxy_config()
    routes = cfg["routes"]
    assignments_store = store.setdefault("assignments", {})
    reassigned = 0
    changes = []      # what the operator is being asked to approve
    proposed = {}     # host -> assignments as they WOULD be, for the dry run
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
            # Fallback pairs are retired: assignments are rewritten primary-only,
            # which in turn leaves the fallback routes unreferenced below — the
            # standard deletion path then removes them and restarts the proxies.
            rts = [{"role": "primary", "proxyId": f"skynet:proxy:{port}", "endpoint": f"http://{server_ip}:{port}/v1"}]
            new_list.append({"agentId": aid, "routes": rts})
        tombstoned = set(store.get("deletedAgents", {}).get(host_id, []))
        for aid, a in existing.items():  # keep offline agents' assignments as-is — but not tombstoned ones
            if aid not in live_ids and aid not in tombstoned:
                new_list.append(a)
        if json.dumps(host_entry.get("assignments")) != json.dumps(new_list):
            for before, after in zip(host_entry.get("assignments") or [], new_list):
                if json.dumps(before) != json.dumps(after):
                    changes.append({
                        "kind": "reassign", "hostId": host_id,
                        "agentId": after.get("agentId"),
                        "from": ((before.get("routes") or [{}])[0] or {}).get("proxyId", ""),
                        "to": ((after.get("routes") or [{}])[0] or {}).get("proxyId", ""),
                        "why": "the agent reports a different proxy than the store holds",
                    })
            if not dry_run:
                host_entry["assignments"] = new_list
            proposed[host_id] = new_list
            reassigned += 1
    # Ports still referenced by any assignment → keep; the rest are stale dups → delete.
    referenced = set()
    for host_id, host_entry in assignments_store.items():
        rows = proposed.get(host_id, host_entry.get("assignments", []))
        for a in rows:
            for r in a.get("routes", []):
                pid = str(r.get("proxyId") or "")
                if pid.startswith("skynet:proxy:"):
                    try:
                        referenced.add(int(pid.split(":")[-1]))
                    except ValueError:
                        pass
    # Only agent-pair routes (clientId set) are deletion candidates. Service
    # bridges (promie-ui, the voice-app bridge, …) are standalone by design — no assignment
    # ever references them, and the old rule deleted exactly those three live
    # routes when reconcile first ran after the bridges were introduced.
    def _deletable(r):
        return bool(str(r.get("clientId") or "")) and int(r["port"]) not in referenced
    kept = [r for r in routes if not _deletable(r)]
    deleted = sorted(int(r["port"]) for r in routes if _deletable(r))
    for r in routes:
        if _deletable(r):
            changes.append({
                "kind": "delete", "port": int(r["port"]),
                "label": str(r.get("label") or ""), "clientId": str(r.get("clientId") or ""),
                "why": "no assignment references this port any more",
            })
    if dry_run:
        return {"dryRun": True, "reassigned": reassigned, "deletedPorts": deleted,
                "keptPorts": sorted(int(r["port"]) for r in kept), "changes": changes}
    save_admin_state()
    if deleted:
        save_agent_proxy_config(kept)   # rewrites file + restarts agent-proxies + re-normalizes routers
    return {"reassigned": reassigned, "changes": changes, "deletedPorts": deleted, "keptPorts": sorted(int(r["port"]) for r in kept)}

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
