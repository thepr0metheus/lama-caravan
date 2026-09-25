"""A model of an engine next to the cells (Ollama, LM Studio) loaded or
unloaded from the board: the controller asks the machine's scout, which does
it on its own thread (scout 2.14+). docs/foreign-engines.md, step 3."""
from caravan.admin.state import save_admin_state, topology_store
from caravan.common.errors import AppError
from caravan.domain.engine import EngineReport


class EngineActions:
    """Load or unload a model of an engine on a machine with a scout.

    The scout answers at once, the model marked as being acted on, and does
    the act on its own thread; its answer carries the machine's engines as
    they are now, and they go into the host record straight away — the board
    shows "loading…" on the next read, not after the next report. What the
    act came to arrives with the reports after it.
    """

    ACTIONS = EngineReport.ACTIONS
    #: The scout answers before the engine does; seconds are plenty.
    TIMEOUT = 15

    def __init__(self, scout_for, hosts, store=None, save=None):
        self._scout_for = scout_for
        self._hosts = hosts
        self._store = store or topology_store
        self._save = save or save_admin_state

    def act(self, host_id, op, kind, model, context_length=None):
        host_id, kind, model = (str(x or "").strip() for x in (host_id, kind, model))
        if op not in self.ACTIONS:
            raise AppError(f"unknown engine action {op!r}", 400)
        if not host_id or not kind or not model:
            raise AppError("hostId, kind and model are required", 400)
        host = next((h for h in self._hosts() if str(h.get("id") or "") == host_id), None)
        if host is None:
            raise AppError(f"no scout has reported for host {host_id}", 404)
        engine = next((e for e in host.get("engines") or [] if isinstance(e, dict) and e.get("kind") == kind), None)
        if engine is None:
            raise AppError(f"{host_id} reports no {kind}", 404)
        body = {"kind": kind, "port": engine.get("port"), "model": model}
        if context_length not in (None, ""):
            body["contextLength"] = context_length
        answer = self._scout_for(host_id).post(f"/api/engines/{op}", body, timeout=self.TIMEOUT)
        engines = EngineReport.engines((answer or {}).get("engines"))
        if engines is not None:
            record = self._store().get("hosts", {}).get(host_id)
            if isinstance(record, dict):
                record["engines"] = engines
                self._save()
        return {"ok": True, "hostId": host_id, "kind": kind, "model": model, "op": op}
