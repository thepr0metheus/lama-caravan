"""Cross-domain proxy actions: stop a route (kills the in-flight request via
stopRequests). Reconciling the routes with the scouts' live reports went with
the reports (2026-09-24)."""
import time

from caravan.admin.proxies_config import (
    load_agent_proxy_config,
    write_agent_proxy_payload,
)
from caravan.admin.proxy_stats import agent_proxy_sample
from caravan.common.errors import AppError


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
