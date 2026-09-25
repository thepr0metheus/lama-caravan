"""Model engines on a machine that are not its cells — Ollama, LM Studio — as
its scout finds them (scout 2.12+) and as the controller keeps and reads them.

The scout decides what an engine is and which processes are its own; here the
report is only kept honestly and joined with the cards' memory. Plan and
steps: docs/foreign-engines.md.
"""


class EngineReport:
    """The `engines` of a scout's report as the host record keeps them: each
    field typed and bounded, anything the scout did not say kept as None.

    None for the whole list is an older scout — it cannot look — and the
    board then says nothing; [] is a scout that looked and found none. A
    model's memory, window or loaded state the engine did not say stays None,
    never a zero: a zero would read as "holds nothing", "serves no window".
    """

    MAX_ENGINES = 8
    MAX_MODELS = 200
    MAX_PIDS = 256
    #: What an engine's answer can be. Anything else is no engine the scout
    #: named, and is not kept.
    STATES = ("ok", "auth", "unreachable", "stopped")
    #: Where it takes connections from; "" when the scout's OS did not say.
    LISTEN = ("loopback", "network")
    #: Who ufw lets reach its port, as a cell's port says it (scout 2.13+).
    FIREWALL = ("open", "all", "restricted", "blocked", "unknown")
    #: What the board may do to an engine's model (scout 2.14+; delete 2.17+).
    ACTIONS = ("load", "unload", "delete")
    #: A model downloaded into the engine (scout 2.17+): an act on the engine,
    #: not on one of its models.
    DOWNLOADS = ("pull",)
    #: What the board may do to the engine's server itself (scout 2.16+).
    SERVER_ACTIONS = ("start", "stop")
    #: Who runs its server (scout 2.16+): this scout's user, or another one.
    RUN_BY = ("user", "other")
    #: Where the need of a load that would not fit comes from (scout 2.15+):
    #: the engine's own estimate, the file and the window's cache, the file
    #: alone — at least that much.
    BASES = ("engine", "weights+cache", "weights")

    @staticmethod
    def text(value, limit=120):
        return str(value or "").strip()[:limit]

    @staticmethod
    def number(value):
        """A count or a size as the scout said it; None when it did not."""
        if isinstance(value, bool) or value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def flag(value):
        """True, False, or None when the engine did not say."""
        return value if isinstance(value, bool) else None

    @classmethod
    def engines(cls, raw):
        if not isinstance(raw, list):
            return None
        return [e for e in (cls.engine(x) for x in raw[:cls.MAX_ENGINES]) if e]

    @classmethod
    def engine(cls, raw):
        if not isinstance(raw, dict):
            return None
        kind, state = cls.text(raw.get("kind"), 40), cls.text(raw.get("state"), 20)
        port = cls.number(raw.get("port"))
        if not kind or state not in cls.STATES or not port or not 0 < port < 65536:
            return None
        models = raw.get("models")
        pids = raw.get("pids") if isinstance(raw.get("pids"), list) else []
        listen = cls.text(raw.get("listen"), 20)
        row = {
            "kind": kind,
            "label": cls.text(raw.get("label"), 60) or kind,
            "port": port,
            "listen": listen if listen in cls.LISTEN else "",
            "state": state,
            "version": cls.text(raw.get("version"), 40),
            # LM Studio's native API ("v1") or its older one ("v0"): which of
            # them can load and unload a model (docs/foreign-engines.md, step 3).
            "api": cls.text(raw.get("api"), 10),
            # None: the engine listed none (it wants a token, it is silent).
            "models": ([m for m in (cls.model(x) for x in models[:cls.MAX_MODELS]) if m]
                       if isinstance(models, list) else None),
            "pids": sorted({p for p in (cls.number(x) for x in pids[:cls.MAX_PIDS]) if p and p > 0}),
            "ramBytes": cls.number(raw.get("ramBytes")),
            "firewall": cls.firewall(raw.get("firewall")),
            # What the board may do to it — nothing for a scout before 2.14,
            # an engine that did not answer, or LM Studio 0.3.
            "controls": [a for a in cls.ACTIONS + cls.DOWNLOADS + cls.SERVER_ACTIONS
                         if isinstance(raw.get("controls"), list) and a in raw["controls"]],
            # Whether a load can say how long the model stays unused (scout
            # 2.15+): Ollama always, LM Studio where its command line is.
            "holds": raw.get("holds") is True,
            # Who runs its server — "" when the scout's machine did not say —
            # whether it starts with the machine, and its start or stop under
            # way or refused (scout 2.16+).
            "runBy": cls.text(raw.get("runBy"), 10) if raw.get("runBy") in cls.RUN_BY else "",
            "autostart": raw.get("autostart") is True,
            "serverAction": cls.act_mark(raw.get("serverAction"), "since", ops=cls.SERVER_ACTIONS),
            "serverError": cls.act_mark(raw.get("serverError"), "at", with_error=True, ops=cls.SERVER_ACTIONS),
            # A download under way into it, and the last one that failed
            # (scout 2.17+); None when there is none.
            "downloading": cls.download(raw.get("downloading")),
            "downloadError": cls.download(raw.get("downloadError"), failed=True),
        }
        # Only when the list of installed models did not answer: the models
        # shown are the loaded ones, and "that is all it has" would be a guess.
        if raw.get("installedKnown") is False:
            row["installedKnown"] = False
        return row

    @classmethod
    def firewall(cls, raw):
        """{state, allowedFrom} as the scout's ufw reading says it, or None —
        an engine on 127.0.0.1 only, or a scout before 2.13."""
        if not isinstance(raw, dict) or raw.get("state") not in cls.FIREWALL:
            return None
        allowed = raw.get("allowedFrom") if isinstance(raw.get("allowedFrom"), list) else []
        return {"state": raw["state"], "allowedFrom": [cls.text(a, 60) for a in allowed[:8] if cls.text(a, 60)]}

    @classmethod
    def model(cls, raw):
        if not isinstance(raw, dict) or not cls.text(raw.get("name"), 200):
            return None
        return {
            "name": cls.text(raw.get("name"), 200),
            "type": cls.text(raw.get("type"), 20),
            "format": cls.text(raw.get("format"), 20),
            "family": cls.text(raw.get("family"), 40),
            "params": cls.text(raw.get("params"), 20),
            "quant": cls.text(raw.get("quant"), 20),
            "fileBytes": cls.number(raw.get("fileBytes")),
            # An Ollama cloud model: it runs on Ollama's servers, not here.
            "remote": raw.get("remote") is True,
            "loaded": cls.flag(raw.get("loaded")),
            "memBytes": cls.number(raw.get("memBytes")),
            "vramBytes": cls.number(raw.get("vramBytes")),
            "contextLength": cls.number(raw.get("contextLength")),
            "maxContextLength": cls.number(raw.get("maxContextLength")),
            "expiresAt": cls.text(raw.get("expiresAt"), 40),
            # LM Studio's "no idle limit" (scout 2.15+): true, false, or None
            # when its command line did not say. Ollama says it by a far
            # expiresAt instead.
            "staysLoaded": cls.flag(raw.get("staysLoaded")),
            "instances": cls.number(raw.get("instances")),
            # An act under way on it, and the last one the engine refused, in
            # its own words (scout 2.14+); None when there is none.
            "action": cls.act_mark(raw.get("action"), "since"),
            "actionError": cls.act_mark(raw.get("actionError"), "at", with_error=True),
        }

    @classmethod
    def download(cls, raw, failed=False):
        """{model, since, doneBytes, totalBytes} of a download under way — the
        sizes None until the engine says them — or {model, error, at} of the
        last one that failed; None when there is none."""
        if not isinstance(raw, dict) or not cls.text(raw.get("model"), 300):
            return None
        if failed:
            return {"model": cls.text(raw.get("model"), 300), "error": cls.text(raw.get("error"), 300),
                    "at": cls.number(raw.get("at"))}
        return {"model": cls.text(raw.get("model"), 300), "since": cls.number(raw.get("since")),
                "doneBytes": cls.number(raw.get("doneBytes")), "totalBytes": cls.number(raw.get("totalBytes"))}

    @classmethod
    def short(cls, raw):
        """{needBytes, freeBytes, basis} of a load the scout did not start
        because it would not fit into the cards' free memory (2.15+); None
        when the answer is not that."""
        if not isinstance(raw, dict):
            return None
        need, free = cls.number(raw.get("needBytes")), cls.number(raw.get("freeBytes"))
        if not need or free is None or need <= free:
            return None
        basis = cls.text(raw.get("basis"), 20)
        return {"needBytes": need, "freeBytes": free, "basis": basis if basis in cls.BASES else ""}

    @classmethod
    def act_mark(cls, raw, when, with_error=False, ops=None):
        """{op, <when>[, error]} of a load or unload — or of `ops` — or None."""
        if not isinstance(raw, dict) or raw.get("op") not in (ops or cls.ACTIONS):
            return None
        mark = {"op": raw["op"], when: cls.number(raw.get(when))}
        if with_error:
            mark["error"] = cls.text(raw.get("error"), 300)
        return mark


class GpuOwners:
    """Who holds the part of a card's memory that is not the fleet's.

    An engine the scout found owns its processes (it names them, children
    and all: Ollama's runners, LM Studio's helpers); any other process is
    named by its executable, as nvidia-smi says it; a process nvidia-smi
    could not name has the name "". The board shows "Ollama 6.1 GB" where it
    showed "outside 6.1 GB".
    """

    def __init__(self, engines):
        self.by_pid = {}
        for engine in engines or []:
            for pid in engine.get("pids") or []:
                self.by_pid.setdefault(pid, engine)

    def owner(self, pid, name):
        """(name shown, engine kind or "") of one process on a card."""
        engine = self.by_pid.get(pid)
        if engine:
            return str(engine.get("label") or engine.get("kind") or ""), str(engine.get("kind") or "")
        return str(name or ""), ""

    def split(self, apps):
        """[(pid, MiB, process name)] on one card, none of them the fleet's →
        [{name, engine, mib}] by owner, largest first; names break ties."""
        held = {}
        for pid, mib, name in apps:
            key = self.owner(pid, name)
            held[key] = held.get(key, 0) + (mib or 0)
        rows = [{"name": name, "engine": engine, "mib": round(mib)} for (name, engine), mib in held.items()]
        return sorted(rows, key=lambda r: (-r["mib"], r["name"], r["engine"]))
