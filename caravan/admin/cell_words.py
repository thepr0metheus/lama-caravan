"""How a cell's own words are read: why it would not start, where its start
is, and what killed it."""


class CellWords:
    """One vocabulary for the words a cell writes, whoever carries them to the
    board — its scout's crash note (the reason and the last lines) and the
    lines it wrote while its port did not listen yet. It read the journal of
    the controller's own cells too, until those moved to the controller
    machine's scout (steps 6.8–6.9); that is why it outlived systemd_ctl.

    Each table is matched in order and the first hit wins — the order is the
    rule, and every entry says why it stands where it does.
    """

    #: Why a cell would not start.
    FAILURE = (
        ("exec", ("status=203", "203/exec", "failed to locate executable", "permission denied")),
        # oom BEFORE model: a card that cannot fit the weights always ends with
        # "error loading model" / "failed to load model" too, because that is how
        # llama.cpp reports the consequence — so matching model first told the user
        # the file was missing while it sat there, 22 GB and perfectly readable:
        #   cudaMalloc failed: out of memory
        #   alloc_tensor_range: failed to allocate CUDA0 buffer of size 22593124608
        #   llama_model_load: error loading model: unable to allocate CUDA0 buffer
        # The reverse mix-up cannot happen: a genuinely missing file fails at open,
        # before a single allocation is attempted, so its log has no oom wording.
        ("oom", ("out of memory", "cudamalloc", "failed to allocate", "unable to allocate",
                 "erroroutofdevicememory", "not enough memory", "insufficient memory")),
        # The last four are a launch script's own words for a file that is not
        # there — without them a missing model, or a library that is not
        # mounted, read as an unexplained crash.
        ("model", ("gguf_init_from_file", "error loading model", "failed to load model",
                   "no such file or directory", "model not found", "mmproj not found",
                   "spec draft not found", "library not mounted")),
        ("port", ("address already in use", "couldn't bind", "failed to bind")),
    )

    #: Where a starting cell is. Ordered from the latest stage to the earliest:
    #: the LAST line that names one wins, so the note follows the start.
    PROGRESS = (
        ("starting API",        ("starting vllm api server", "uvicorn running", "application startup complete")),
        ("capturing CUDA graphs", ("capturing cuda graph", "cudagraph", "graph capturing finished")),
        ("compiling kernels",   ("torch.compile", "dynamo bytecode", "compiling", "inductor")),
        ("loading weights",     ("loading safetensors", "model loading took", "loading weights", "load_tensors", "loading model")),
        ("downloading model",   ("downloading", "fetching ", "%|")),
        ("provisioning venv",   ("provisioning vllm venv",)),
        ("warming up",          ("warming up", "kv cache", "encoder cache")),
    )

    #: How a cell CRASHED: the driver's and llama.cpp's own words, by which
    #: "the card hung" is told apart from "the model didn't fit".
    CRASH = (
        ("gpu-hang", ("the launch timed out", "unspecified launch failure", "gpu is probably locked",
                      "xid")),
        ("gpu-oom", ("out of memory", "cudamalloc", "erroroutofdevicememory")),
        ("assert", ("ggml_assert", "ggml_abort", "assertion")),
        # A scout names the signal a process died of ("died of SIGKILL", 2.6+).
        ("killed", ("killed", "out of memory: killed process", "oom-killer", "sigkill")),
    )

    @classmethod
    def failure_kind(cls, text):
        """exec, oom, model, port — or "crash" when no word says which."""
        low = str(text or "").lower()
        for name, needles in cls.FAILURE:
            if any(n in low for n in needles):
                return name
        return "crash"

    @classmethod
    def progress_note(cls, text):
        """The latest stage its lines name; "" when none does."""
        for line in reversed(str(text or "").splitlines()):
            low = line.lower()
            for label, needles in cls.PROGRESS:
                if any(n in low for n in needles):
                    return label
        return ""

    @classmethod
    def crash_kind(cls, text):
        """gpu-hang, gpu-oom, assert, killed — or "crash"."""
        low = str(text or "").lower()
        for name, needles in cls.CRASH:
            if any(n in low for n in needles):
                return name
        return "crash"
