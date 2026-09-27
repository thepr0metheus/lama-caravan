"""A cloud model's own ports — and with them its place on the kanban.

The operator's rule (2026-09-27): a model with a port of its own is on the
kanban; a model without one is not, and no cable can reach it there. So "on
the kanban" is read from the routes instead of kept as a flag: a model is on
the kanban while at least one port of its own — a route of kind "service"
whose providerId is the model — leads to it. The flag it replaces, `exposed`
on the model block, was set by the kanban's checklist apart from the ports,
and the two had come to disagree: six models on the kanban, two ports among
them.

Closing a model's last port takes it off the kanban, and whatever the routers
point at it — cables, the default, rules — would stop reaching it without a
word. So the last port closes only with an answer: move them onto another
model of the same provider (which gets a port of its own if it had none), or
disconnect them. A stashed default (dormantDefault) is not a reason to ask:
it waits for its output by design.
"""
from caravan.admin.cloud import cloud_accounts_state, load_cloud_data, save_cloud_data
from caravan.admin.cloud_refs import CloudModelRewire
from caravan.admin.output_refs import RouterOutputRefs
from caravan.admin.proxies_config import (
    bridge_route,
    cloud_block_output,
    load_agent_proxy_config,
    mint_bridge_port,
    next_free_proxy_port,
    save_agent_proxy_config,
)
from caravan.common.errors import AppError


class CloudModelPorts:
    """The models' own ports in one snapshot of agent-proxies.json."""

    #: What a model on the kanban can hold that stops working when it leaves.
    #: Not dormantDefault: that one waits for an absent output by design.
    HOLDING_RULES = ("default", "audioOutput", "embeddingsOutput", "schedule", "bySource", "failover")

    def __init__(self, cfg):
        self.cfg = cfg if isinstance(cfg, dict) else {}

    @staticmethod
    def is_model_port(route):
        return (isinstance(route, dict) and str(route.get("kind") or "") == "service"
                and bool(str(route.get("providerId") or "").strip()))

    def _ports(self):
        return [r for r in (self.cfg.get("routes") or []) if self.is_model_port(r)]

    def of(self, block_id):
        """The model's own ports, lowest first."""
        return sorted(int(r.get("port") or 0) for r in self._ports() if str(r.get("providerId")) == str(block_id))

    def on_kanban(self):
        """The ids of the models that have a port of their own."""
        return {str(r.get("providerId")) for r in self._ports()}

    def held(self, block_id):
        """What would stop reaching the model if it left the kanban: the cables
        into it and the rules that name it, over every router."""
        out = f"cb:{block_id}"
        cables, rules = 0, []
        for router in self.cfg.get("routers") or []:
            refs = RouterOutputRefs(router)
            cables += len(refs.edges_touching(out))
            rules += [k for k in refs.rules_naming(out) if k in self.HOLDING_RULES and k not in rules]
        return {"cables": cables, "rules": rules}

    def cut(self, block_id):
        """Disconnect everything the routers point at the model; returns how many places."""
        return sum(RouterOutputRefs(r).drop(f"cb:{block_id}") for r in self.cfg.get("routers") or [])


class CloudPortDesk:
    """Opening and closing models' ports on the files: agent-proxies.json holds
    the ports and the routers, cloud-providers.json the models."""

    def open(self, block_id):
        """Put a model on the kanban: its first port, or a new one. Returns the port."""
        ports = CloudModelPorts(load_agent_proxy_config()).of(block_id)
        return ports[0] if ports else int(mint_bridge_port(block_id)["port"])

    def close(self, block_id, ports=None, resolution=None):
        """Close some (default: all) of a model's ports. Closing the last one takes
        the model off the kanban; when the routers hold it, `resolution` says what
        happens to that: {"moveTo": <model>} or {"cut": True}, and without one the
        answer is 409."""
        block_id = str(block_id or "").strip()
        payload = load_agent_proxy_config()
        desk = CloudModelPorts(payload)
        mine = desk.of(block_id)
        wanted = None if ports is None else {int(p) for p in ports}
        closing = [p for p in mine if wanted is None or p in wanted]
        if not closing:
            raise AppError(f"model {block_id} has no such port", 404)
        leaves = len(closing) == len(mine)
        held = desk.held(block_id) if leaves else {"cables": 0, "rules": []}
        answer = resolution if isinstance(resolution, dict) else {}
        onto = str(answer.get("moveTo") or "").strip()
        moved = cut = 0
        if held["cables"] or held["rules"]:
            if onto:
                moved = self._move(payload, block_id, onto)
            elif answer.get("cut"):
                cut = desk.cut(block_id)
            else:
                raise AppError(f"model {block_id}: {held['cables']} cable(s) and rules {held['rules']} lead to it "
                               "on the kanban — move them onto another model of its provider, or disconnect them", 409)
        else:
            onto = ""
        routes = [r for r in (payload.get("routes") or [])
                  if not (CloudModelPorts.is_model_port(r) and str(r.get("providerId")) == block_id
                          and int(r.get("port") or 0) in closing)]
        save_agent_proxy_config(routes, payload.get("routers"))
        return {"closed": closing, "leaves": leaves, "moved": moved, "cut": cut, "onto": onto or None}

    def close_port(self, port, resolution=None):
        """Close one port found by its number — the ✕ beside it."""
        try:
            port = int(port)
        except (TypeError, ValueError):
            raise AppError("port must be a number", 400)
        payload = load_agent_proxy_config()
        route = next((r for r in (payload.get("routes") or []) if isinstance(r, dict) and int(r.get("port") or 0) == port), None)
        if not route:
            raise AppError(f"no proxy route on port {port}", 404)
        if str(route.get("kind") or "") != "service":
            raise AppError("not a model's port — agent routes are managed on the board", 400)
        if not CloudModelPorts.is_model_port(route):
            # A service route that names no model holds nothing on the kanban.
            save_agent_proxy_config([r for r in payload["routes"] if r is not route], payload.get("routers"))
            return {"closed": [port], "leaves": False, "moved": 0, "cut": 0, "onto": None}
        return self.close(route.get("providerId"), [port], resolution)

    def move_cables(self, src, dst):
        """Everything that pointed at one model now points at another of its
        provider, which is on the kanban from now on (a port of its own opens
        if it had none). Returns how many references moved."""
        payload = load_agent_proxy_config()
        moved = self._move(payload, src, dst)
        save_agent_proxy_config(payload.get("routes") or [], payload.get("routers"))
        return moved

    def _move(self, payload, src, dst):
        blocks = {b.get("id"): b for b in load_cloud_data()["blocks"]}
        if src not in blocks or dst not in blocks or src == dst:
            raise AppError("move cables: name two different models", 400)
        if blocks[src].get("accountId") != blocks[dst].get("accountId"):
            raise AppError("move cables: both models must be of one provider", 400)
        routes = payload.setdefault("routes", [])
        if not CloudModelPorts(payload).of(dst):
            routes.append(bridge_route(blocks[dst], next_free_proxy_port(routes)))
        output = cloud_block_output(cloud_accounts_state(), blocks[dst])
        return CloudModelRewire(payload).move(src, dst, output=output)

    def adopt_flags(self):
        """The one-time change of 2026-09-27: every model the old flag put on the
        kanban gets a port of its own, so nothing on the board changes — no
        cable, default or rule loses its model — and the flag leaves the model
        block. A model that already had a port only loses the flag. A port that
        cannot be opened leaves its flag for the next start. Returns the ports
        opened."""
        data = load_cloud_data()
        flagged = [b for b in data["blocks"] if b.get("exposed")]
        if not flagged:
            return []
        opened = []
        have = CloudModelPorts(load_agent_proxy_config()).on_kanban()
        for block in flagged:
            if block["id"] not in have:
                try:
                    opened.append(self.open(block["id"]))
                except AppError as exc:
                    print(f"cloud: no port for {block['id']} ({exc}); its flag waits for the next start", flush=True)
                    continue
            block.pop("exposed", None)
        save_cloud_data(data)
        return opened
