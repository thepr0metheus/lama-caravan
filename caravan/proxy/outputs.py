"""A route sent to one output: the one rule every reader applies.

The router graph's exits, an entry consumer's pool and a pool's local row all
end the same way — the request goes to an output's address — so the overlay
lives here, once (caravan/proxy/graph.py, dialect.py and the handler's pool legs
read it).
"""
from caravan.common.upstream_types import UpstreamType


def router_output(output_id, config=None):
    """A local model's output as the controller last wrote it — the address of its cell or
    engine, and what its model does (caravan/common/model_kinds.py) — or None when no router
    names it any more."""
    if config is None:
        from caravan.proxy.config import current_config
        config = current_config()
    for router in (config or {}).get("routers") or []:
        for out in router.get("outputs") or []:
            if isinstance(out, dict) and out.get("id") == output_id:
                return dict(out)
    return None


def overlay_output(route, out, queue_spec=None):
    """Overlay a resolved output onto a route copy. When queue_spec is set (the path
    crossed a queue node), stash it under `queuePlan` for the handler's wait/spill loop."""
    resolved = dict(route)
    resolved["upstreamHost"] = str(out.get("upstreamHost") or route.get("upstreamHost"))
    resolved["upstreamPort"] = int(out.get("upstreamPort") or route.get("upstreamPort"))
    out_type = str(out.get("upstreamType") or "llama")
    resolved["upstreamType"] = out_type
    resolved["routedOutputId"] = str(out.get("id") or "")
    resolved["routedOutputName"] = str(out.get("name") or "")
    if out_type == "cloud":
        # providerId = a model-block; empty = passthrough → resolve the account directly.
        resolved["providerId"] = str(out.get("providerId") or "")
        resolved["cloudAccountId"] = str(out.get("accountId") or "")
    # An engine's model, or a model of a machine's entry (1.3.506): the handler
    # names it in the request. Dropped first, so a route re-resolved onto a
    # cell (a spill, a rescue) carries no name left over from the engine it
    # was resolved onto before.
    resolved.pop("upstreamModel", None)
    if UpstreamType.named(out):
        resolved["upstreamModel"] = str(out.get("upstreamModel") or "")
    resolved.pop("queuePlan", None)
    resolved.pop("rescueRefs", None)
    resolved.pop("deadSkipped", None)
    if queue_spec:
        resolved["queuePlan"] = {"spec": queue_spec}
    return resolved


def pool_leg(route, out):
    """A pool's route sent to the cell (or engine) of its local row: the
    output's address, and none of the pool's cloud ends — no provider, and no
    old-style cloud fallback, which a pool's next row replaces."""
    leg = overlay_output(route, out)
    leg["providerId"] = ""
    leg["cloudAccountId"] = ""
    leg["cloudFallbackProviderId"] = ""
    return leg
