"""A cell reserved to run inside an engine next to it — what it is made of.

The operator reserves a cell and says where it runs (2026-09-25): the caravan
itself, Ollama, or LM Studio on that machine. For an engine the reserve step
also takes the model, so the cell is configured the moment it exists: its
runner, the model as the engine names it, and the engine's loopback port —
all read off the machine's own report, never guessed. A plan that cannot be
made is refused before a port is taken, so a refusal leaves no empty cell
behind it.
"""
from caravan.common.errors import AppError
from caravan.domain import runner as runners


class EngineCellPlan:
    """The config of a cell in one engine of one machine — or the refusal
    that says why there is none."""

    #: Why an engine the scout found cannot take a cell, by what it answered
    #: (EngineReport.STATES). Each says what the operator can do about it.
    NOT_READY = {
        "stopped": "{name} is not running on this machine — start its server first",
        "unreachable": "{name} is not answering on this machine",
        "auth": "{name} on this machine asks for a token, and a cell has none to give it",
    }

    def __init__(self, host, engine, model):
        self.host = host if isinstance(host, dict) else None
        self.kind = str(engine or "").strip().lower()
        self.model = str(model or "").strip()

    @staticmethod
    def kinds():
        """The engines a cell can run in: the runners of engine cells. Their
        ids are the scout's words for the engines."""
        return tuple(r.id for r in runners.REGISTRY if r.engine_cell)

    @classmethod
    def from_body(cls, host, body):
        """The plan a reserve request asks for, or None when it names no
        engine — an ordinary reserve, a cell the caravan runs itself."""
        engine = str((body or {}).get("engine") or "").strip()
        if not engine:
            return None
        return cls(host, engine, (body or {}).get("model"))

    def engine(self):
        """The machine's reported engine of this kind, running and listing
        the model. The engine is asked about before the model: a board that
        found nothing to choose from sends none, and hears why."""
        kinds = self.kinds()
        if self.kind not in kinds:
            raise AppError(f"a cell runs in {', '.join(kinds)}, not in {self.kind!r}", 400)
        if self.host is None:
            raise AppError("no scout has reported for this machine", 404)
        reported = self.host.get("engines")
        if reported is None:
            raise AppError("this machine's scout does not look for engines — it is older than 2.12", 409)
        found = next((e for e in reported if isinstance(e, dict) and e.get("kind") == self.kind), None)
        if found is None:
            raise AppError(f"this machine reports no {self.kind}", 404)
        name = found.get("label") or self.kind
        state = found.get("state")
        if state != "ok":
            words = self.NOT_READY.get(state, "{name} on this machine answers {state!r}")
            raise AppError(words.format(name=name, state=state), 409)
        models = found.get("models")
        if models is None:
            raise AppError(f"{name} did not list its models, so the cell's model cannot be checked", 409)
        if not models:
            raise AppError(f"{name} on this machine has no models — download one into it first", 409)
        if not self.model:
            raise AppError("a cell in an engine is reserved with its model", 400)
        if not any(isinstance(m, dict) and m.get("name") == self.model for m in models):
            raise AppError(f"{name} has no model {self.model} on this machine", 404)
        return found

    def config(self):
        """What the cell's config holds: its runner, CELL_KIND for the readers
        that take the command path from it alone, the model, the port."""
        found = self.engine()
        port = runners.get(self.kind).engine_port({"ENGINE_PORT": found.get("port")})
        return {"RUNNER": self.kind, "CELL_KIND": "command", "ENGINE_MODEL": self.model, "ENGINE_PORT": str(port)}


class EngineCellFit:
    """Whether the model of a cell in an engine fits into its machine's cards,
    asked before the cell starts it (2026-09-26: the question the board's load
    asked moved to the start of the cell that loads the model now).

    "At least": the model's file alone against the free memory of all the
    machine's cards together — an engine spreads a model across cards, and
    the file is the least it takes. Nothing is asked when either side is not
    known (no size, a card that does not say, no card at all), when the model
    is loaded already (the cell takes it as it is), or when it runs on the
    engine's cloud.
    """

    def __init__(self, host, config):
        self.host = host if isinstance(host, dict) else None
        cfg = config if isinstance(config, dict) else {}
        self.kind = str(cfg.get("RUNNER") or "").strip().lower()
        self.model = str(cfg.get("ENGINE_MODEL") or "").strip()

    def model_row(self):
        """The model as the machine's engine reports it; None for a cell that
        is not in an engine, or a model the report does not name."""
        if self.host is None or not self.model or self.kind not in EngineCellPlan.kinds():
            return None
        engine = next((e for e in self.host.get("engines") or []
                       if isinstance(e, dict) and e.get("kind") == self.kind), None)
        return next((m for m in (engine or {}).get("models") or []
                     if isinstance(m, dict) and m.get("name") == self.model), None)

    def free_bytes(self):
        """Bytes free on all the machine's cards together — None when there is
        no card, or one does not say (nvidia-smi answers [N/A])."""
        cards = self.host.get("gpus") if self.host else None
        if not isinstance(cards, list) or not cards:
            return None
        free = 0.0
        for card in cards:
            try:
                free += float((card or {}).get("memoryFreeMiB"))
            except (TypeError, ValueError):
                return None
        return int(free * 1024 * 1024)

    def short(self):
        """{model, needBytes, freeBytes, basis} when the model would not fit;
        None when it would, or when it cannot be told."""
        row = self.model_row()
        if not row or row.get("loaded") is True or row.get("remote") is True:
            return None
        need = row.get("fileBytes")
        if isinstance(need, bool) or not isinstance(need, int) or need <= 0:
            return None
        free = self.free_bytes()
        if free is None or need <= free:
            return None
        return {"model": self.model, "needBytes": need, "freeBytes": free, "basis": "weights"}

