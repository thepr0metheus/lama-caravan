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

    A load that would not fit into the cards' free memory is not started by
    the scout (2.15+): the answer is `short` — how much it needs, how much is
    free — and the board asks the operator; the same load with `force`
    starts anyway.
    """

    ACTIONS = EngineReport.ACTIONS
    SERVER_ACTIONS = EngineReport.SERVER_ACTIONS
    #: The scout answers before the engine does; seconds are plenty.
    TIMEOUT = 15

    def __init__(self, scout_for, hosts, store=None, save=None):
        self._scout_for = scout_for
        self._hosts = hosts
        self._store = store or topology_store
        self._save = save or save_admin_state

    def engine(self, host_id, kind):
        """The machine's reported engine of this kind — or the refusal that
        says why there is none to act on."""
        host = next((h for h in self._hosts() if str(h.get("id") or "") == host_id), None)
        if host is None:
            raise AppError(f"no scout has reported for host {host_id}", 404)
        engine = next((e for e in host.get("engines") or [] if isinstance(e, dict) and e.get("kind") == kind), None)
        if engine is None:
            raise AppError(f"{host_id} reports no {kind}", 404)
        return engine

    def act(self, host_id, op, kind, model, context_length=None, force=False, hold=None):
        host_id, kind, model = (str(x or "").strip() for x in (host_id, kind, model))
        if op not in self.ACTIONS:
            raise AppError(f"unknown engine action {op!r}", 400)
        if not host_id or not kind or not model:
            raise AppError("hostId, kind and model are required", 400)
        engine = self.engine(host_id, kind)
        body = {"kind": kind, "port": engine.get("port"), "model": model}
        if context_length not in (None, ""):
            body["contextLength"] = context_length
        if force is True:
            body["force"] = True
        if hold not in (None, ""):
            body["hold"] = hold
        answer = self._scout_for(host_id).post(f"/api/engines/{op}", body, timeout=self.TIMEOUT)
        self.keep(host_id, answer)
        done = {"hostId": host_id, "kind": kind, "model": model, "op": op}
        short = EngineReport.short((answer or {}).get("short")) if (answer or {}).get("ok") is False else None
        if short:
            return {"ok": False, **done, "short": short}
        return {"ok": True, **done}

    def serve(self, host_id, op, kind):
        """Start the engine's server, or stop it (scout 2.16+): the scout
        answers at once, the engine marked, and waits for the server on its
        own thread."""
        host_id, kind = (str(x or "").strip() for x in (host_id, kind))
        if op not in self.SERVER_ACTIONS:
            raise AppError(f"unknown engine action {op!r}", 400)
        if not host_id or not kind:
            raise AppError("hostId and kind are required", 400)
        engine = self.engine(host_id, kind)
        answer = self._scout_for(host_id).post(f"/api/engines/{op}", {"kind": kind, "port": engine.get("port")},
                                               timeout=self.TIMEOUT)
        self.keep(host_id, answer)
        return {"ok": True, "hostId": host_id, "kind": kind, "op": op}

    def keep(self, host_id, answer):
        """The engines the scout answered with, into the machine's host
        record at once — the board shows the act under way on its next read.
        An answer that names none leaves the record as it was."""
        engines = EngineReport.engines((answer or {}).get("engines"))
        if engines is None:
            return
        record = self._store().get("hosts", {}).get(host_id)
        if isinstance(record, dict):
            record["engines"] = engines
            self._save()
