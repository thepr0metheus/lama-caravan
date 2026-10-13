"""What a router output's upstream is, and what that changes on the way to it (1.3.506)."""


class UpstreamType:
    """The kinds of upstream a router output names, as one table:

    - `llama` — a cell: one model on its own port; its places are its /slots.
    - `engine` — a model of an engine next to the cells (Ollama, LM Studio):
      many models on the engine's port, the request names its model; its
      places are not known (the policy's).
    - `machine` — a model of a machine's entry (its scout, scout 2.27+): many
      models on the scout's port, the request names its model; its places are
      the scout's word for it (scout 2.29+), and it has a queue of its own.
    - `cloud` — a pool or an account: no places counted.

    The controller writes the type on each output (proxies_config); the proxy
    and the board read it. A type outside this table is read as `llama`, as
    the file has always been.
    """

    LLAMA, ENGINE, MACHINE, CLOUD = "llama", "engine", "machine", "cloud"
    ALL = (LLAMA, ENGINE, MACHINE, CLOUD)
    #: The kinds whose port serves many models: a request names its model (`upstreamModel`).
    NAMED = (ENGINE, MACHINE)

    @classmethod
    def of(cls, out):
        """The output's type, `llama` when it says none or one this table does not know."""
        said = str((out or {}).get("upstreamType") or cls.LLAMA).strip().lower()
        return said if said in cls.ALL else cls.LLAMA

    @classmethod
    def named(cls, out):
        """Whether a request to the output names the model it wants."""
        return cls.of(out) in cls.NAMED
