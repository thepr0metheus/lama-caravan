"""The models of engines next to the cells (Ollama, LM Studio) that the
operator made router outputs, and the outputs they become.

The engines are found by the machines' scouts (caravan/domain/engine.py keeps
what they say); which of their models route traffic is the operator's choice,
kept here. docs/foreign-engines.md, step 2.
"""
import hashlib
import ipaddress

from caravan.admin.controller_machine import ControllerMachine
from caravan.admin.paths import TOPOLOGY_SERVER_IP
from caravan.admin.state import save_admin_state, topology_store
from caravan.common.errors import AppError


class EngineOutputs:
    """The engine models the operator made router outputs — `eng:<hash>` each.

    An output is keyed by (machine, engine kind, model name): a model name
    carries ':' and '/', which an id read by prefix must not, and an id that
    does not hold the port stays the same when the engine moves to another
    one — the edges wired to it stay wired.

    An exposed model whose machine is on the board is always an output, even
    when it cannot work right now: its engine stopped, the model was removed,
    or the engine listens on 127.0.0.1 of another machine. Such an output
    fails its probe and the board says why; one that silently vanished from
    the router would be absence drawn as normality, and each coming and going
    would rewrite the router's default. The port and the address are read
    from the machine's last report; an engine the report no longer lists
    keeps the port it had when its model was exposed.
    """

    PREFIX = "eng:"
    SECTION = "engineOutputs"

    def __init__(self, store=None, save=None, controller=None, controller_ip=None):
        # Looked up when made, not when defined: a test stands in for the store.
        self._store = store or topology_store
        self._save = save or save_admin_state
        self._controller = controller or ControllerMachine()
        # Where the proxy's connections come from, for a machine's ufw rules.
        self._controller_ip = TOPOLOGY_SERVER_IP if controller_ip is None else controller_ip

    @classmethod
    def output_id(cls, host_id, kind, model):
        digest = hashlib.sha1(f"{host_id}\n{kind}\n{model}".encode("utf-8")).hexdigest()[:12]
        return f"{cls.PREFIX}{digest}"

    def exposed(self):
        """{output id: {hostId, kind, model, port}} — the operator's choice."""
        rows = self._store().setdefault(self.SECTION, {})
        return rows if isinstance(rows, dict) else {}

    @staticmethod
    def engine_of(host, kind):
        """The machine's reported engine of this kind, or None."""
        for engine in (host or {}).get("engines") or []:
            if isinstance(engine, dict) and engine.get("kind") == kind:
                return engine
        return None

    @classmethod
    def model_of(cls, host, kind, model):
        engine = cls.engine_of(host, kind)
        for row in (engine or {}).get("models") or []:
            if isinstance(row, dict) and row.get("name") == model:
                return engine, row
        return engine, None

    def set(self, hosts, host_id, kind, model, on):
        """Make a model an output (`on`) or stop. Only a model the machine's
        report lists can become one, and not a model Ollama runs on its own
        cloud: its traffic would leave the fleet under a local engine's name.
        Returns the output's id and whether it is exposed now."""
        host_id, kind, model = (str(x or "").strip() for x in (host_id, kind, model))
        if not host_id or not kind or not model:
            raise AppError("hostId, kind and model are required", 400)
        output_id = self.output_id(host_id, kind, model)
        rows = self.exposed()
        if on:
            host = next((h for h in hosts or [] if str(h.get("id") or "") == host_id), None)
            engine, row = self.model_of(host, kind, model)
            if row is None:
                raise AppError(f"{model} is not a model of {kind} on {host_id}", 404)
            if row.get("remote"):
                raise AppError(f"{model} runs on the engine's cloud, not on {host_id}", 400)
            rows[output_id] = {"hostId": host_id, "kind": kind, "model": model, "port": int(engine["port"])}
        else:
            rows.pop(output_id, None)
        self._save()
        return {"id": output_id, "exposed": bool(on)}

    def upstream_host(self, host, engine):
        """Where the controller's proxy reaches the engine: the machine's own
        loopback when the engine listens there and the machine is the
        controller's, else the machine's address — which an engine on
        127.0.0.1 of another machine refuses; its output fails its probe, and
        the engine's card says how to open it."""
        if (engine or {}).get("listen") == "loopback" and self._controller.is_host(host):
            return "127.0.0.1"
        return str((host or {}).get("ip") or "")

    def blocked_by(self, host, engine):
        """Why the controller's proxy cannot reach the engine, or "" when it
        can — or when nothing says it cannot:
        - "loopback": it listens on 127.0.0.1 of a machine that is not the
          controller's;
        - "firewall": its machine's ufw lets no one in on its port, or only
          sources the controller is not among (scout 2.13+).
        On the controller's own machine neither applies. A firewall the scout
        could not read ("unknown", or no reading at all) blocks nothing: it is
        not known to."""
        if self._controller.is_host(host):
            return ""
        engine = engine or {}
        if engine.get("listen") == "loopback":
            return "loopback"
        wall = engine.get("firewall") if isinstance(engine.get("firewall"), dict) else {}
        if wall.get("state") == "blocked":
            return "firewall"
        if wall.get("state") == "restricted" and not self.lets_in(wall.get("allowedFrom")):
            return "firewall"
        return ""

    def lets_in(self, sources):
        """True when the controller's address is among ufw's allowed sources
        — an address or a network; a source that is neither is not read."""
        try:
            me = ipaddress.ip_address(str(self._controller_ip or "").strip())
        except ValueError:
            return True   # the controller's own address is unknown: not a verdict
        if me.is_loopback:
            return True   # its address was never set (the default): not a verdict either
        for source in sources or []:
            try:
                if me in ipaddress.ip_network(str(source).split()[0], strict=False):
                    return True
            except (ValueError, IndexError):
                continue
        return False

    def reachable(self, host, engine):
        """False when the controller's proxy cannot reach the engine."""
        return not self.blocked_by(host, engine)

    def outputs(self, hosts):
        """One router output per exposed model whose machine is on the board,
        in the order the models were exposed."""
        by_id = {str(h.get("id") or ""): h for h in hosts or [] if isinstance(h, dict)}
        outs = []
        for output_id, row in self.exposed().items():
            host = by_id.get(str(row.get("hostId") or "")) if isinstance(row, dict) else None
            if host is None:
                continue
            engine = self.engine_of(host, row.get("kind"))
            port = int((engine or {}).get("port") or row.get("port") or 0)
            address = self.upstream_host(host, engine)
            if not port or not address:
                continue
            label = str((engine or {}).get("label") or row.get("kind") or "")
            outs.append({
                "id": output_id,
                "label": f"{row.get('model')} · {label}",
                "target": f"{row.get('hostId')}:engine:{row.get('kind')}",
                "upstreamHost": address,
                "upstreamPort": port,
                "upstreamType": "engine",
                "providerId": "",
                # The model's own name in the engine: the proxy puts it into
                # every request, since one engine serves many models.
                "upstreamModel": str(row.get("model") or ""),
                "engine": str(row.get("kind") or ""),
                "hostId": str(row.get("hostId") or ""),
            })
        return outs

    def annotate(self, host):
        """The machine's engines as the board draws them: each model with its
        output id and whether it is one; each engine with whether the proxy
        can reach it, and why not."""
        engines = host.get("engines") if isinstance(host, dict) else None
        if not isinstance(engines, list):
            return engines
        rows = self.exposed()
        out = []
        for engine in engines:
            engine = dict(engine)
            engine["blockedBy"] = self.blocked_by(host, engine)
            engine["reachable"] = not engine["blockedBy"]
            models = []
            for model in engine.get("models") or []:
                model = dict(model)
                model["outputId"] = self.output_id(host.get("id"), engine.get("kind"), model.get("name"))
                model["exposed"] = model["outputId"] in rows
                models.append(model)
            if isinstance(engine.get("models"), list):
                engine["models"] = models
            out.append(engine)
        return out
