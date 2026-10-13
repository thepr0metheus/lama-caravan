"""agent-proxies.json I/O and mutation: routes, routers, policy. Every write
funnels through write_agent_proxy_payload (with the kanban-graph autobackup)."""
import hashlib
import json
import secrets
import threading

from caravan.admin.state import topology as topo
from caravan.admin.paths import AGENT_PROXY_CONFIG_FILE, CONTROLLER_HOST_ID, PROXY_PORTS
from caravan.admin.output_refs import RouterOutputRefs
from caravan.admin.router_dsl import (
    DEFAULT_ROUTER_ID,
    normalize_agent_proxy_policy,
    normalize_agent_proxy_route,
    normalize_router,
    normalize_router_output,
    recompute_cloud_fallback_eligibility,
)
from caravan.admin.systemd_ctl import ensure_agent_proxy_running
from caravan.common.errors import AppError
from caravan.common.fsio import atomic_write_text
from caravan.store.proxies import ProxyStore
from caravan.common.key_entry import KeyEntry
from caravan.common.model_kinds import ModelKind


# What a caravan with no proxy config has: nothing. It used to have four —
# named after agents that were retired long ago, on ports that now belong to
# other things (8083 was a bridge). They appeared whenever the file was missing
# OR unreadable, so a corrupt config came up looking like a working four-route
# configuration, and the first write replaced the file that could have been
# recovered. An empty list is the only honest answer to "we could not read it".
DEFAULT_AGENT_PROXY_ROUTES = []

#: The document itself. Everything about how it is read, upgraded, backed up and
#: written lives in the store; this module is what the caravan DOES with it.
_store = ProxyStore(AGENT_PROXY_CONFIG_FILE, default_router_id=DEFAULT_ROUTER_ID)


def _migrate_legacy_router_payload(payload):
    """Back-compat: upgrade the pre-rename 'switchboard' schema to 'router' in place."""
    return _store.upgrade(payload)


def read_agent_proxy_payload():
    return _store.payload({"routes": DEFAULT_AGENT_PROXY_ROUTES,
                           "policy": normalize_agent_proxy_policy({}),
                           "routers": [], "stopRequests": []})


def write_agent_proxy_payload(payload):
    # Keep ↑☁ cloud-fallback eligibility in sync with the current graph connections
    # on every write (this is the single choke point for all proxy-config changes).
    try:
        if isinstance(payload, dict):
            recompute_cloud_fallback_eligibility(payload.get("routes"))
            # Keep routers (default exists, orphans re-pointed, inputs derived)
            # consistent with the routes on every write — single source of truth.
            if "routers" in payload or payload.get("routes"):
                payload["routers"] = normalize_routers(
                    payload.get("routers"), payload.get("routes"))
    except Exception:
        pass
    _store.write(_store.protect_graph(payload, _store.stamp()))


class StaleCopy(AppError):
    """A save made from an older version of a list than the stored one: refused, nothing written."""

    def __init__(self, name):
        super().__init__(f"the {name} changed since this page read them: nothing was saved — "
                         "the page makes its change again on the current version", 409)
        self.name = name


class ProxyRevisions:
    """Which version of the proxy document a page was shown, list by list — and the refusal
    of a save made from an older one.

    A page saves whole lists built from its own copy of the topology: the kanban its routers
    with every cable, the port form every route. A tab left open since the morning wrote its
    copy over the afternoon's with its first click: on the NAS (2026-10-08, 09:04) such a tab
    put back the cable of a deleted port, and a port given that number later took it over.
    So the topology names the version of each list it hands out — a digest of the list as
    stored — a page sends it back with a save, and a save made from an older version is
    refused (StaleCopy, 409); the page makes its change again on the current topology. A save
    that names no version goes through as before: a script that knows nothing of versions.

    The check and the write run under one lock, so two saves of one version cannot both pass.
    Background writers do not take it: what they change, a page either never sends or sees
    on its next reading — the save after it is refused once and made again.
    """

    LISTS = ("routes", "routers")
    LOCK = threading.RLock()

    def __init__(self, read=None):
        self._read = read

    @staticmethod
    def digest(value):
        text = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

    @classmethod
    def of(cls, payload):
        """The version of each list in a reading of the document, as stored."""
        payload = payload if isinstance(payload, dict) else {}
        return {name: cls.digest(payload.get(name)) for name in cls.LISTS}

    def current(self):
        return self.of((self._read or read_agent_proxy_payload)())

    def check(self, name, seen):
        """Refuse a save of list `name` made from version `seen`, unless it is the stored one.
        No version given — a script's save — passes. Call it holding LOCK, with the write."""
        if seen and str(seen) != self.current()[name]:
            raise StaleCopy(name)


PROXY_REVISIONS = ProxyRevisions()


def load_agent_proxy_config(payload=None):
    """The document, normalised. `payload` is a reading already made (read_agent_proxy_payload),
    so a caller that names the version of what it shows names the version of THIS reading."""
    payload = read_agent_proxy_payload() if payload is None else payload
    routes = payload.get("routes") if isinstance(payload.get("routes"), list) else DEFAULT_AGENT_PROXY_ROUTES
    cleaned = []
    seen = set()
    for route in routes:
        try:
            row = normalize_agent_proxy_route(route)
        except Exception:
            continue
        if row["port"] in seen:
            continue
        seen.add(row["port"])
        cleaned.append(row)
    routers = normalize_routers(payload.get("routers"), cleaned)
    return {
        "routes": cleaned,
        "policy": normalize_agent_proxy_policy(payload.get("policy")),
        "routers": routers,
        "stopRequests": (payload.get("stopRequests") if isinstance(payload.get("stopRequests"), list) else [])[-100:],
        # The one entry for keys (caravan/common/key_entry.py). Every writer
        # that starts from this dict writes it back, so it is named here.
        "entry": KeyEntry.clean(payload.get("entry")),
    }

def _router_local_outputs(server_obj):
    """Auto-outputs = one per local llama server. Stable id `srv:<port>` so rules
    keep referencing the same output across restarts."""
    outs = []
    seen = set()
    for s in (server_obj.get("llamaServers") or []):
        port = s.get("port")
        if not port or port in seen:
            continue
        seen.add(port)
        if s.get("isController"):
            host, node = "127.0.0.1", CONTROLLER_HOST_ID
        else:
            host = node = str(s.get("clientIp") or "").strip()
            if not host:
                # A cell on a machine whose address nobody knows — forgotten on
                # the board, or never reported — is no output. It used to get
                # 127.0.0.1, which sends its traffic to whatever the controller
                # runs on that port. The router treats a missing srv: output as
                # a server that is down: its edges stay and come back with the
                # machine's next report.
                continue
        model = str(s.get("model") or "").split("/")[-1]
        # A command cell has no MODEL_FILE, so it used to render as a bare
        # `:8018` in the router's server list — its own artifact label stands in.
        what = model or str(s.get("cellLabel") or "")
        outs.append({
            "id": f"srv:{port}",
            "label": (f"{what} " if what else "") + f":{port}",
            "target": f"{node}:llama-server:{port}",
            "upstreamHost": host,
            "upstreamPort": int(port),
            "upstreamType": "llama",
            "providerId": "",
            # What the cell's model does, for the entry's model list and a pool's window
            # (caravan/common/model_kinds.py, 1.3.502).
            **ModelKind.cell_facts(s),
        })
    return outs

def pool_output(pool):
    """The router output of one pool: `cb:<pool id>` — the id the model block
    it was made from had, so the cables, rules and ports that named the model
    name the pool — labelled with the pool's name. A pool has no account of
    its own: its steps do, and the proxy picks one per request."""
    return {
        "id": f"cb:{pool['id']}",
        "label": f"☁ {pool.get('name') or pool['id']}",
        "target": f"pool:{pool['id']}",
        "upstreamHost": "",
        "upstreamPort": 0,
        "upstreamType": "cloud",
        "providerId": pool["id"],
    }

def sync_router_outputs(routers, server_obj, pools=None, engine_outputs=None, machine_outputs=None):
    """Outputs are AUTO-derived from the available providers: one per local llama
    server + one per model of an engine next to the cells the operator made an
    output (`engine_outputs`, EngineOutputs.outputs) + one per model of a machine's
    entry (`machine_outputs`, MachineOutputs.outputs, 1.3.506) + one per pool.
    Replace each router's outputs with the desired set; keep rules.default valid.
    Returns True if changed."""
    local = _router_local_outputs(server_obj)
    cloud = [pool_output(p) for p in (pools or [])]
    desired = [normalize_router_output(o)
               for o in (local + list(engine_outputs or []) + list(machine_outputs or []) + cloud)]
    changed = False
    for router in routers:
        if not isinstance(router, dict):
            continue
        existing = router.get("outputs") or []
        if existing != desired:
            router["outputs"] = [dict(o) for o in desired]
            changed = True
        ids = {o["id"] for o in desired}
        rules = router.setdefault("rules", {})
        # A previously stashed default whose output came back wins the slot again
        # (an explicit user default-pick clears the stash on the frontend).
        dormant = str(rules.get("dormantDefault") or "")
        if dormant and dormant in ids:
            rules["default"] = dormant
            rules.pop("dormantDefault", None)
            changed = True
        # Default prefers a local server (cloud is overflow, not the primary).
        if rules.get("default") not in ids:
            old_default = str(rules.get("default") or "")
            # Stash a stable-keyed default (srv:/cb:/eng:/mm:) so it survives the
            # rewrite and auto-restores when its output reappears.
            if old_default.startswith(("srv:", "cb:", "eng:", "mm:")) and not rules.get("dormantDefault"):
                rules["dormantDefault"] = old_default
            local_ids = [o["id"] for o in desired if o["upstreamType"] != "cloud"]
            rules["default"] = (local_ids or [o["id"] for o in desired] or [""])[0]
            changed = True
    return changed

class PortInputs:
    """The client ports a graph may start from: one input per proxy route.

    The graph names a client port by its number (`in:skynet:proxy:<port>`), so
    whatever it holds for a port — the cable out of it, its wait budget —
    outlives the port unless something takes it away. Nothing did on a save:
    a page holding an old copy of the graph saved it on the NAS (2026-10-08,
    09:04) and wrote back the cable of a port deleted a quarter of an hour
    earlier. The next port given that number took the cable over, and its new
    client went to a model nobody chose; only the kanban showed it. So every
    read and every write forgets what a graph holds for a port no route has.

    A port that exists keeps its cables, also while no router has it: the board
    promises that unassigning a port deletes nothing (dlgUnassignRouter).
    """

    #: What the graph calls a client port: the proxy's id of the route.
    PREFIX = "skynet:proxy:"

    def __init__(self, routes):
        self.routes = [r for r in (routes or []) if isinstance(r, dict)]
        self.known = {self.of(r) for r in self.routes}

    @classmethod
    def of(cls, route):
        return f"{cls.PREFIX}{route.get('port')}"

    def of_router(self, router_id):
        """The inputs of one router: the routes that carry its id. An unassigned
        route ("") feeds none — no router's id is empty."""
        return [self.of(r) for r in self.routes if r.get("routerId") == router_id]

    def holds(self, ref):
        ref = str(ref or "")
        return not ref.startswith("in:") or ref[3:] in self.known

    def forget_absent(self, router):
        """`router` without the cables and wait budgets of ports no route has —
        a copy. Anything malformed passes as it is: normalize_router drops it.
        Before the graph is normalised, so a model's queue is reconciled
        against the cables that stay."""
        graph = router.get("graph") if isinstance(router, dict) else None
        if not isinstance(graph, dict):
            return router
        kept = dict(graph)
        if isinstance(graph.get("edges"), list):
            kept["edges"] = [e for e in graph["edges"]
                             if not isinstance(e, dict) or (self.holds(e.get("from")) and self.holds(e.get("to")))]
        if isinstance(graph.get("inputs"), dict):
            kept["inputs"] = {pid: cfg for pid, cfg in graph["inputs"].items() if str(pid) in self.known}
        return {**router, "graph": kept}


def normalize_routers(raw, routes):
    """Normalize the router list and keep it consistent with the proxy routes.

    Guarantees: the default router always exists; every route's routerId
    points at a real router (orphans fall back to default); each router's
    `inputs` is derived fresh from the routes that carry its id (single source of
    truth — never trusted from disk); a graph holds nothing for a port no route
    has (PortInputs). Without the routes (None) nothing is forgotten: not knowing
    the ports is not knowing there are none."""
    ports = PortInputs(routes) if isinstance(routes, list) else None
    routers = [normalize_router(ports.forget_absent(s) if ports else s)
               for s in (raw if isinstance(raw, list) else [])]
    by_id = {}
    for router in routers:
        by_id.setdefault(router["id"], router)
    if DEFAULT_ROUTER_ID not in by_id:
        default_router = normalize_router({"id": DEFAULT_ROUTER_ID, "name": "Default"})
        by_id[DEFAULT_ROUTER_ID] = default_router
    # Re-point routes whose router no longer exists at the default — EXCEPT the
    # intentional "unassigned" state ("" empty), which is left free (runtime → 503).
    # A client of the entry is never on a router, whatever a raw route says: its
    # cable leads to a set of models.
    for route in (routes or []):
        if route.get("kind") == "consumer":
            route["routerId"] = ""
        router_id = route.get("routerId")
        if router_id == "":
            continue
        if router_id not in by_id:
            route["routerId"] = DEFAULT_ROUTER_ID
    # Inputs from the routes, after the re-pointing above (unassigned "" feeds no router).
    derived = ports or PortInputs([])
    ordered = [by_id[DEFAULT_ROUTER_ID]] + [router for sid, router in by_id.items() if sid != DEFAULT_ROUTER_ID]
    for router in ordered:
        router["inputs"] = derived.of_router(router["id"])
    return ordered

def remap_router_output_refs(old_id, new_id):
    """Follow a renamed output id everywhere a router can point at it: the
    outputs list itself (so normalize doesn't reset a default that referenced
    the old id before the next auto-sync) and every place in RouterOutputRefs.
    Persists when changed (the proxy re-reads its config by itself)."""
    payload = load_agent_proxy_config()
    routers = payload.get("routers") or []
    changed = False
    new_port = 0
    if str(new_id).startswith("srv:"):
        try:
            new_port = int(str(new_id).split(":", 1)[1])
        except ValueError:
            pass
    for router in routers:
        for out in router.get("outputs") or []:
            if out.get("id") == old_id:
                out["id"] = new_id
                if new_port:
                    out["upstreamPort"] = new_port
                changed = True
        if RouterOutputRefs(router).rewrite(lambda v: new_id if v == old_id else v):
            changed = True
    if changed:
        save_agent_proxy_config(payload.get("routes") or [], routers)
    return changed

def swap_router_output_refs(id_a, id_b):
    """Swap two output ids everywhere a router points at either — the mirror of
    remap for a port SWAP between two cells, so each cable follows its own cell.
    Done in a single pass (an `a`→`b` remap then a `b`→`a` remap would clobber:
    the second flips the just-written `b`s back). Persists once."""
    payload = load_agent_proxy_config()
    routers = payload.get("routers") or []
    port_a = int(str(id_a).split(":", 1)[1]) if str(id_a).startswith("srv:") else 0
    port_b = int(str(id_b).split(":", 1)[1]) if str(id_b).startswith("srv:") else 0
    changed = False

    def swap(v):
        return id_b if v == id_a else (id_a if v == id_b else v)

    for router in routers:
        for out in router.get("outputs") or []:
            if out.get("id") == id_a:
                out["id"] = id_b
                if port_b:
                    out["upstreamPort"] = port_b
                changed = True
            elif out.get("id") == id_b:
                out["id"] = id_a
                if port_a:
                    out["upstreamPort"] = port_a
                changed = True
        if RouterOutputRefs(router).rewrite(swap):
            changed = True
    if changed:
        save_agent_proxy_config(payload.get("routes") or [], routers)
    return changed

class PolicyOwnedFields:
    """The fields of a route only their own doors set: whether its port is
    closed and its own queue thresholds (set_agent_proxy_route_policy), and a
    consumer's key and its set (caravan/admin/consumers.py) — or its pool, on a
    route of the form before 1.3.497 not yet rewritten. The board's
    full-list save rebuilds every route from what its page holds, and the page
    never carried the first ones: any ✎ save reopened every closed port and
    reset every threshold, without a word (found 2026-10-07, before the first
    agent's port was closed). A consumer's key never reaches the page at all —
    it is shown once, when it is made. A posted route that leaves such a field
    out keeps the stored value; one that names it — false, null or "" — says
    what it wants, as the doors do."""

    FIELDS = ("portClosed", "cloudFallbackPct", "priorityPreemptPct", "queueAbortPct", "apiKey", "set", "pool")

    def __init__(self, stored_routes):
        self.by_port = {}
        for route in stored_routes or []:
            try:
                self.by_port[int(route.get("port") or 0)] = route
            except (AttributeError, TypeError, ValueError):
                continue

    def kept(self, route):
        """The posted route with the stored values of the fields it left out."""
        if not isinstance(route, dict):
            return route
        try:
            stored = self.by_port.get(int(route.get("port") or 0))
        except (TypeError, ValueError):
            return route
        missing = {k: stored[k] for k in self.FIELDS if stored and k in stored and k not in route}
        return {**route, **missing} if missing else route

def save_agent_proxy_config(routes, routers=None, revision=None):
    """Save the whole list of routes. `revision` is the version of the routes the caller's
    list was built from (ProxyRevisions): an older one is refused before anything is written."""
    with ProxyRevisions.LOCK:
        PROXY_REVISIONS.check("routes", revision)
        payload = _write_routes(routes, routers)
    # The running proxy picks the file up by itself; the save only makes sure
    # there is one running (see ensure_agent_proxy_running).
    result = ensure_agent_proxy_running(timeout=30)
    if not result["ok"]:
        raise AppError(result["stderr"] or "failed to start agent proxy service", 500)
    return payload


def _write_routes(routes, routers):
    current = load_agent_proxy_config()
    keep = PolicyOwnedFields(current.get("routes") or [])
    cleaned = []
    seen = set()
    for route in routes:
        row = normalize_agent_proxy_route(keep.kept(route))
        if row["port"] in seen:
            raise AppError(f"duplicate proxy port {row['port']}", 400)
        seen.add(row["port"])
        cleaned.append(row)
    before = set()
    for r in current.get("routes") or []:
        try:
            before.add(int(r.get("port") or 0))
        except (AttributeError, TypeError, ValueError):
            pass
    # The firewall is not the caravan's: the operator opened the proxy block
    # once (PROXY_PORTS). Every path that adds or renumbers a port passes here,
    # so a new port outside the block is refused here, before anything is
    # written — it would listen and stay unreachable, and nothing would say why.
    # A port already in the file keeps working as it is: the old ones outside
    # the block (8022) have firewall rules of their own.
    outside = sorted(row["port"] for row in cleaned
                     if row["port"] not in before and not PROXY_PORTS.holds(row["port"]))
    if outside:
        raise AppError(
            f"port {', '.join(str(port) for port in outside)} is outside the proxy range "
            f"{PROXY_PORTS}, the one the firewall lets in — pick a port inside it", 400)
    KeyAudit(cleaned).enforce()
    # Routers: caller-provided list (Stage 4 UI) or keep the existing one;
    # either way re-normalize against the cleaned routes so inputs stay in sync.
    router_source = routers if routers is not None else current.get("routers")
    payload = {
        "routes": cleaned,
        "policy": current.get("policy") or normalize_agent_proxy_policy({}),
        "routers": normalize_routers(router_source, cleaned),
        "stopRequests": current.get("stopRequests") or [],
        "entry": current.get("entry") or {},
    }
    write_agent_proxy_payload(payload)
    return payload

class KeyAudit:
    """The keys of the routes, as the entry needs them (caravan/common/key_entry.py).

    The entry finds an agent by its key, so a key two routes carry would find
    neither; and a closed port without a key leaves its agent no way in at
    all. Both are refused where the routes are saved, before anything is
    written — the proxy refuses the first one again at request time, for a
    file edited by hand.
    """

    def __init__(self, routes):
        self.routes = [route for route in routes or [] if isinstance(route, dict)]

    def problems(self):
        found = []
        for key, ports in KeyEntry.shared_keys(self.routes).items():
            found.append(f"ports {', '.join(str(port) for port in ports)} share one key (…{key[-4:]}) — "
                         f"the entry could not tell their agents apart; give each its own")
        for route in self.routes:
            if route.get("portClosed") and not str(route.get("apiKey") or "").strip():
                found.append(f"port {route.get('port')} is closed and has no key — its agent would have "
                             f"no way in; give it a key first")
        return found

    def enforce(self):
        found = self.problems()
        if found:
            raise AppError("; ".join(found), 400)


# ── The proxy's port numbers ─────────────────────────────────────────────────
# Which numbers are taken, and the next free one for a consumer or an agent.

def _all_taken_ports(routes=None):
    """Every number the fleet must not hand out, from ALL of its own registers.

    There were two allocators with two different ideas of "taken": the bridge
    one asked used_server_cell_ports() (cells, exclusions, the controller's own
    web port, existing routes), while the agent one looked only at
    agent-proxies.json. So an agent port could be minted onto a number a cell
    already held or an operator had excluded, and the collision surfaced later
    as a bind failure in a log nobody was reading. One register, both callers.
    """
    used = set()
    try:
        from caravan.admin.server_cells import used_server_cell_ports
        used |= used_server_cell_ports()
    except Exception:
        pass
    for r in (routes or []):
        if isinstance(r, dict):
            try:
                used.add(int(r.get("port") or 0))
            except (TypeError, ValueError):
                continue
    # The entry's port is the fleet's too: no route may be minted onto it.
    try:
        used.add(int((load_agent_proxy_config().get("entry") or {}).get("port") or 0))
    except Exception:  # noqa: BLE001 — an unreadable config names no entry
        pass
    used.discard(0)
    return used


def port_is_listening(port):
    """Something already bound locally? The registers describe what the caravan
    INTENDS; this asks the kernel what is actually true. A number that is free
    on paper and bound in fact fails at start-up, three steps after the choice."""
    try:
        from caravan.admin.systemd_ctl import listening_pid
        pid, comm = listening_pid(int(port))
        return bool(pid or comm)
    except Exception:
        return False


def _next_agent_port(used_ports):
    """The next odd port from AGENT_PROXY_BASE_PORT whose +1 neighbour is free too.

    The +1 hole is the fossil of the retired fallback pair: primaries stay on
    odd ports, and "New port" for a fallback takes the neighbour
    (fleet_clients.fallback_port_for). `used_ports` carries the routes;
    everything else the fleet has claimed comes from the shared register, and
    the kernel is asked last. This allocator used to consult the routes file
    and nothing else, while the bridge allocator next door consulted all of
    them; the collision it could produce surfaced only as a failed bind in a
    log. Its other caller, the provisioner that minted a port for every agent a
    scout reported, is gone (2026-09-24): agent ports are made by hand.
    """
    from caravan.admin.paths import AGENT_PROXY_BASE_PORT
    claimed = set(used_ports)
    try:
        claimed |= _all_taken_ports()
    except Exception:
        pass
    candidate = AGENT_PROXY_BASE_PORT
    while (candidate in claimed or (candidate + 1) in claimed
           or port_is_listening(candidate)):
        candidate += 2
        # Inside the block the firewall lets in, neighbour included: a pair
        # past its ceiling would bind and stay unreachable (PROXY_PORTS).
        if candidate + 1 > PROXY_PORTS.upper:
            raise AppError(f"no free agent proxy port left in the proxy range {PROXY_PORTS}", 500)
    return candidate


def next_free_proxy_port(routes):
    """Smallest free port in the PROXY range — a consumer's number.

    These used to count from SERVER_CELL_BASE_PORT: with one flat range that was
    simply "the next free number", but 1.3.188 split the ranges — cells at
    22001+, proxies at 23001+ — and the old base was left behind, so a port
    minted here landed among the model cells. It did not collide (the shared
    register keeps it out of the picker), it was just filed in the wrong drawer,
    which is the sort of thing nobody notices until they are looking for it.
    Every listener the proxy owns belongs in the proxy range.
    """
    from caravan.admin.paths import AGENT_PROXY_BASE_PORT
    used = _all_taken_ports(routes)
    port = AGENT_PROXY_BASE_PORT
    while port in used or port_is_listening(port):
        port += 1
        if port > PROXY_PORTS.upper:
            raise AppError(f"no free proxy port left in the proxy range {PROXY_PORTS}", 500)
    return port

def mint_agent_port(client_id, agent_id, label="", port=None):
    """Create an AGENT entry port deliberately, with a name the operator chose.

    Agent routes could only come into existence by being provisioned, which is
    why every one of them is called "<Name> primary" and why the answer to
    "who decided this?" was always "the provisioner". An operator who wants a
    second port for an agent, or a port named after what it is for, had no way
    to say so except by editing JSON on the controller.

    Born without a key, matching the form's default: requiring one is a
    deliberate act, made in the route form. The port binds 0.0.0.0, so on a flat
    LAN that means anything on the network can reach it.
    """
    client_id = str(client_id or "").strip()
    agent_id = str(agent_id or "").strip()
    if not client_id or not agent_id:
        raise AppError("clientId and agentId are required", 400)
    payload = load_agent_proxy_config()
    routes = payload.get("routes") or []
    if port in (None, "", 0):
        # From the AGENT base, not the cell base: handing one out at 22026 would
        # put a proxy inside the range the cell picker draws from. (Consumers count
        # from the same base, one by one; agent ports take a pair.)
        port = _next_agent_port({int(r.get("port") or 0) for r in routes if isinstance(r, dict)})
    else:
        try:
            port = int(port)
        except (TypeError, ValueError):
            raise AppError("port must be a number", 400)
        if port < 1024 or port > 65535:
            raise AppError(f"port {port} is out of range", 400)
        taken = _all_taken_ports(routes)
        if port in taken:
            raise AppError(f"port {port} is already taken — pick another", 409)
    route = {
        "label": (str(label or "").strip() or f"{agent_id} port")[:80],
        "port": port,
        # Legacy placeholder — the router graph owns the real upstream choice.
        "upstreamHost": "127.0.0.1",
        "upstreamPort": 8080,
        "upstreamType": "llama",
        "enabled": True,
        "mode": "open",
        "priority": 0,
        "preemptible": True,
        "clientTimeoutSeconds": 1800,
        "routerId": DEFAULT_ROUTER_ID,
        "clientId": client_id,
        "role": "primary",
    }
    routes.append(route)
    saved = save_agent_proxy_config(routes, payload.get("routers"))
    return next((r for r in saved["routes"] if int(r.get("port") or 0) == port), route)


def delete_proxy_route(port, force=False):
    """Delete ANY proxy port from the board, with its router wiring.

    Deletion had no single home: bridges came off the Cloud card, agent routes
    only vanished when reconcile happened to notice nothing referenced them, and
    an app port made by hand could be edited forever but never removed. So the
    one operation an operator asks for by name — "how do I delete this?" — had
    no answer that did not involve editing JSON on the controller.

    A port still named by an assignment is refused unless forced: the listener
    would go and the agent on the other machine would keep calling the number,
    which is a silent outage somewhere the operator is not looking.
    """
    try:
        port = int(port)
    except (TypeError, ValueError):
        raise AppError("port must be a number", 400)
    payload = load_agent_proxy_config()
    routes = payload.get("routes") or []
    target = next((r for r in routes if isinstance(r, dict) and int(r.get("port") or 0) == port), None)
    if not target:
        raise AppError(f"no proxy route on port {port}", 404)

    if not force:
        from caravan.admin.state import topology_store
        bound = []
        for host_id, row in topo.assignments().items():
            for entry in (row.get("assignments") or []):
                for r in (entry.get("routes") or []):
                    if str(r.get("proxyId") or "").endswith(f":{port}"):
                        bound.append(f"{host_id}/{entry.get('agentId')}")
        if bound:
            raise AppError(
                f"port {port} is still assigned to {', '.join(bound)} — "
                f"point the agent elsewhere first", 409)

    # The router wiring goes with the port: the save forgets whatever a graph
    # holds for a port no route has (PortInputs). Left behind, it was an orphan
    # edge, invisible on the board, waiting for the next port given this number.
    save_agent_proxy_config([r for r in routes if r is not target], payload.get("routers") or [])
    return {"deleted": port, "label": str(target.get("label") or "")}


def set_agent_proxy_policy(policy):
    payload = load_agent_proxy_config()
    payload["policy"] = normalize_agent_proxy_policy({**payload["policy"], **policy})
    write_agent_proxy_payload(payload)
    return payload

class RouteKeys:
    """A consumer's key, given where none was: the board's "Give a key".

    The key is what finds the consumer at the entry (caravan/common/key_entry.py),
    and from that moment the entry is its only way in: the port closes in the
    same write. No window in which the old port still answers without a key —
    the operator's word (2026-10-07): a consumer that has not moved yet gets no
    answer until it calls the entry with its key. So the entry must be on, or
    the consumer would have no way in at all. A route that has a key keeps it:
    replacing one is its own act (the consumer must be told), not a click on a
    free one.
    """

    PREFIX = "lcv1_"

    def __init__(self, token=None):
        self._token = token or (lambda: secrets.token_hex(24))

    def new(self):
        """A fresh key: the prefix, then 48 hex characters from the system's randomness."""
        return self.PREFIX + self._token()

    def issue(self, port):
        try:
            target = int(port)
        except (TypeError, ValueError):
            raise AppError("port must be a number", 400)
        payload = load_agent_proxy_config()
        route = next((r for r in payload["routes"] if int(r.get("port") or 0) == target), None)
        if not route:
            raise AppError("proxy route not found", 404)
        if str(route.get("kind") or "") == "consumer":
            raise AppError("a consumer of the entry has its key — replace it on its card", 409)
        if str(route.get("apiKey") or "").strip():
            raise AppError(f"port {target} already has a key", 409)
        if not int((payload.get("entry") or {}).get("port") or 0):
            raise AppError("the entry is off — open it before giving a key: the consumer's only way in "
                           "is the entry", 409)
        route["apiKey"] = self.new()
        route["portClosed"] = True
        KeyAudit(payload["routes"]).enforce()
        write_agent_proxy_payload(payload)
        return {"port": target, "key": route["apiKey"]}

def set_agent_proxy_route_policy(port, patch):
    payload = load_agent_proxy_config()
    target_port = int(port)
    found = False
    for route in payload["routes"]:
        if int(route.get("port") or 0) != target_port:
            continue
        found = True
        if "label" in patch:
            lbl = str(patch.get("label") or "").strip()[:80]
            if lbl and str(route.get("kind") or "") == "consumer":
                # A client of the entry is named by the one rule its creation follows (consumers.py
                # imports this module: the rule is fetched here, when a client is renamed).
                from caravan.admin.consumers import ConsumerDesk
                lbl = ConsumerDesk.clean_name(lbl, payload["routes"], own_port=target_port)
            if lbl:
                route["label"] = lbl
        if "mode" in patch:
            mode = str(patch.get("mode") or "open").strip().lower()
            if mode not in ("open", "paused", "drain"):
                raise AppError("mode must be open, paused, or drain", 400)
            route["mode"] = mode
        if "priority" in patch:
            route["priority"] = max(0, min(100, int(patch.get("priority") or 0)))
        if "preemptible" in patch:
            route["preemptible"] = bool(patch.get("preemptible"))
        if "portClosed" in patch:
            # Closing the port moves the agent to the entry for good: only its key finds it there.
            if patch.get("portClosed"):
                if not int((payload.get("entry") or {}).get("port") or 0):
                    raise AppError("the entry is off — open it before closing a port, or the agent "
                                   "has no way in", 409)
                route["portClosed"] = True
            else:
                route.pop("portClosed", None)
        if "upstreamType" in patch:
            utype = str(patch.get("upstreamType") or "llama").strip().lower()
            if utype not in ("llama", "cloud"):
                raise AppError("upstreamType must be llama or cloud", 400)
            route["upstreamType"] = utype
            if utype == "cloud":
                pid = str(patch.get("providerId") or "").strip()
                if not pid:
                    raise AppError("providerId required for cloud upstream", 400)
                route["providerId"] = pid
            else:
                route["providerId"] = ""
        elif "providerId" in patch:
            route["providerId"] = str(patch.get("providerId") or "").strip()
        if "cloudFallbackProviderId" in patch:
            # Toggle the ↑☁ ability on (provider id) or off (""); eligibility/repointing
            # is finalized by recompute_cloud_fallback_eligibility on write.
            route["cloudFallbackProviderId"] = str(patch.get("cloudFallbackProviderId") or "").strip()
        if "routerId" in patch:
            # Re-bind this proxy to another router, or "" to UNASSIGN it (free →
            # runtime 503). No restart — agent-proxies.py re-reads routerId live.
            # A client of the entry has no router: its cable leads to a set of models.
            if str(route.get("kind") or "") == "consumer":
                raise AppError("a client of the entry goes to its set of models, not to a router: "
                               "cable it to a set on the kanban", 400)
            router_id = str(patch.get("routerId") or "").strip()
            if router_id and router_id not in {s.get("id") for s in (payload.get("routers") or [])}:
                raise AppError("unknown router", 400)
            route["routerId"] = router_id
        # Per-route threshold overrides — null/absent means "inherit from global policy"
        for pct_key in ("cloudFallbackPct", "priorityPreemptPct", "queueAbortPct"):
            if pct_key in patch:
                v = patch[pct_key]
                if v is None:
                    route.pop(pct_key, None)   # remove override → revert to global
                else:
                    route[pct_key] = max(0, min(100, int(v)))
    if not found:
        raise AppError("proxy route not found", 404)
    KeyAudit(payload["routes"]).enforce()
    write_agent_proxy_payload(payload)
    return payload

def set_routers(routers, revision=None):
    """Replace the router list (the UI sends the full array). No service restart:
    agent-proxies.py re-reads routers from the file by mtime on the next request.
    normalize_routers (via write) keeps inputs/default/orphans consistent. `revision` is
    the version of the routers the array was built from: an older one is refused
    (ProxyRevisions) before anything is written."""
    with ProxyRevisions.LOCK:
        PROXY_REVISIONS.check("routers", revision)
        payload = load_agent_proxy_config()
        payload["routers"] = normalize_routers(routers, payload.get("routes"))
        write_agent_proxy_payload(payload)
    return payload
