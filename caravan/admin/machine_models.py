"""The models of a machine as its scout's entry lists them, and the router outputs they become (1.3.506).

Step 2 of the owner's plan of 2026-10-12 (visumap caravan-scout-openai): the machine is a provider,
and a pool's row names "machine + model". The scout serves the machine's models at one address by
OpenAI's API (scout 2.27) and both its reports carry the list (`entryModels`, scout 2.28) with each
model's places (scout 2.29). A model is called by its name, and its output's id holds no port: a
cell's port moved or a copy added does not touch the pool rows that name the model.
"""
import hashlib
from urllib.parse import urlsplit

from caravan.common.model_kinds import ModelKind


class MachineModels:
    """A machine's models as its report says them, cleaned for its record: each model's name, its
    state, its places and its copies.

    None when the report does not say — a scout older than 2.28 cannot — and [] when it says the
    machine has none: the two are drawn apart (absence is not "no models")."""

    STATES = ("running", "starting", "failed", "stopped")
    #: The most models and copies a record keeps: a machine has a handful.
    MODELS, COPIES = 200, 32

    @staticmethod
    def count(raw):
        """A count the scout said, or None: an int, not a flag, not negative."""
        return raw if isinstance(raw, int) and not isinstance(raw, bool) and raw >= 0 else None

    @classmethod
    def state(cls, raw):
        """The state the scout said, or "unknown" for a word this table does not know."""
        return raw if raw in cls.STATES else "unknown"

    @classmethod
    def clean(cls, raw):
        if not isinstance(raw, list):
            return None
        models = []
        for item in raw[:cls.MODELS]:
            if not isinstance(item, dict):
                continue
            name = str(item.get("id") or "").strip()[:200]
            said = item.get("caravan") if isinstance(item.get("caravan"), dict) else {}
            if not name:
                continue
            copies = []
            for copy in (said.get("copies") or [])[:cls.COPIES]:
                port = cls.count(copy.get("port")) if isinstance(copy, dict) else None
                if not port:
                    continue
                copies.append({"port": port, "state": cls.state(copy.get("state")),
                               "slots": cls.count(copy.get("slots")), "busy": cls.count(copy.get("busy"))})
            models.append({"id": name, "state": cls.state(said.get("state")), "slots": cls.count(said.get("slots")),
                           "busy": cls.count(said.get("busy")), "copies": copies})
        return models


class MachineOutputs:
    """Each model of a machine's entry as a router output, `mm:<hash>`: a pool's row names it, and the
    proxy sends the request to the machine's entry — its scout's address, `agentUrl` — with the
    model's name in it (`upstreamModel`), as it does to an engine next to the cells.

    The id is made of the machine and the model's name: a name carries ':' and '/', which an id read
    by prefix must not, and an id with no port in it stays when a cell moves to another port.

    What the model does and the window it serves are its copies' (ModelKind.cell_facts, the facts a
    cell's own output carries): the kinds of the first copy that says them, and the smallest window
    of those that say one — a request may land on any copy. A copy the controller has no record of
    says nothing, and a model none of whose copies says anything carries no facts: its pool's kind
    and window are then not known, never guessed.

    A machine whose scout says no address, or no list, has no such outputs: its cells' own outputs
    (`srv:<port>`) still serve, as before step 2."""

    PREFIX = "mm:"

    @classmethod
    def output_id(cls, host_id, model):
        digest = hashlib.sha1(f"{host_id}\n{model}".encode("utf-8")).hexdigest()[:12]
        return f"{cls.PREFIX}{digest}"

    @staticmethod
    def entry_address(host):
        """(address, port) of the machine's entry — its scout's, as its report gives it — or None."""
        try:
            url = urlsplit(str((host or {}).get("agentUrl") or "").strip())
            return (url.hostname, url.port) if url.hostname and url.port else None
        except ValueError:
            return None

    @staticmethod
    def cell_facts(server_obj):
        """(machine id, port) → what each cell the controller knows says of its model."""
        found = {}
        for row in (server_obj or {}).get("llamaServers") or []:
            if isinstance(row, dict) and row.get("clientId") and row.get("port"):
                found[(str(row["clientId"]), int(row["port"]))] = ModelKind.cell_facts(row)
        return found

    @classmethod
    def facts(cls, host_id, model, cells):
        """The model's facts from its copies: the first copy's kinds, the smallest window said."""
        said = [cells.get((host_id, copy["port"])) or {} for copy in model.get("copies") or []]
        first = next((f for f in said if f.get("jobs")), {})
        out = {key: value for key, value in first.items() if key != "contextLength"}
        windows = [f["contextLength"] for f in said if f.get("contextLength")]
        if windows:
            out["contextLength"] = min(windows)
        return out

    def outputs(self, hosts, server_obj):
        """One output per model of each machine whose scout lists them, in the order it lists them."""
        cells = self.cell_facts(server_obj)
        outs = []
        for host in hosts or []:
            host_id = str((host or {}).get("id") or "") if isinstance(host, dict) else ""
            address = self.entry_address(host) if host_id else None
            models = host.get("entryModels") if address else None
            for model in models if isinstance(models, list) else []:
                name = str(model.get("id") or "")
                if not name:
                    continue
                outs.append({
                    "id": self.output_id(host_id, name),
                    "label": name,
                    "target": f"{host_id}:machine:{name}",
                    "upstreamHost": address[0],
                    "upstreamPort": address[1],
                    "upstreamType": "machine",
                    "providerId": "",
                    # The model's name at the machine's entry: the proxy puts it into every request.
                    "upstreamModel": name,
                    "hostId": host_id,
                    **self.facts(host_id, model, cells),
                })
        return outs
