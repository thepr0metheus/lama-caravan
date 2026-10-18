"""What a model of the entry does — its kind of work, what it takes and gives — from its pool's rows.

OpenAI's GET /v1/models says nothing of it: an OpenAI client knows a model's kind by its name. A
client of the caravan cannot: the owner names the pools ("for agents", "gemma-4-12b"), and sinapse
would put a recogniser into its chat lists or a chat model into its ears and learn of it from a 4xx
in the middle of a conversation (sinapse, 2026-10-12). So each model of the list says what it does
(the owner, 2026-10-12: «Вид модели», step 3 of the visumap scheme caravan-model-sets) — in the
words gateways already use, OpenRouter's `architecture` (`modality`, `input_modalities`,
`output_modalities`), and under `caravan` in the fleet's own: its jobs (caravan/common/model_jobs.py),
the languages an ear hears or a translating ear writes, the longest recording it takes.

A pool answers from whichever of its rows serves, so it promises only what every row that may
serve does: the jobs and the inputs all of them have, the languages all of them name, the shortest
recording. A row that may serve and says nothing of itself makes the pool's kind unknown — absent
from the list, never guessed. Rows that do different work make it `mixed`: Routing says so, the
list says nothing. A row that cannot serve — switched off, open, its account or cell gone — is no
part of the promise.

The board reads a pool's kind by `state` (Routing's chip), the entry by `models_entry` (the
list) and `serves` (a request the pool cannot do is refused before it is sent).
"""
from caravan.common.cloud_sources import CloudSources
from caravan.common.model_jobs import JOBS, cell_jobs, cell_runner_id


class ModelKind:
    """The kind of one row, or of a pool's rows together."""

    #: What each job takes and gives, in OpenRouter's words for modalities.
    WORK = {
        "llm": (("text",), ("text",)),
        "embed": (("text",), ("embeddings",)),
        "asr": (("audio",), ("text",)),
        "speech-translate": (("audio",), ("text",)),
        "tts": (("text",), ("audio",)),
        "translate": (("text",), ("text",)),
        # A robot policy reads camera frames and an instruction (and the robot's state, which
        # OpenRouter has no word for) and gives actions — no word there either, so the caravan's.
        "robot-policy": (("image", "text"), ("actions",)),
        # A voice model takes speech or words and answers in speech (and its words).
        "voice-chat": (("audio", "text"), ("audio", "text")),
    }
    #: The paths of OpenAI's API each job answers. NLLB's own /v1/translate is no path of the entry.
    #: A robot policy's path is the caravan's own: OpenAI has none (visumap spider-monkey-model-api).
    PATHS = {
        "llm": ("/chat/completions", "/responses", "/completions", "/messages"),
        "embed": ("/embeddings",),
        "asr": ("/audio/transcriptions", "/audio/translations"),
        "speech-translate": ("/audio/transcriptions", "/audio/translations"),
        "tts": ("/audio/speech",),
        "translate": (),
        "robot-policy": ("/robot/predict",),
        # None: a voice cell speaks a WebSocket or a page of its own, or (Step-Audio 2, Qwen3-Omni) a chat — and that one
        # is served by their `llm` job. A pool of voice cells alone is refused any request the entry has a path for.
        "voice-chat": (),
    }
    #: A chat's inputs, in the order they are said.
    INPUTS = ("text", "image", "audio")
    #: A subscription's chat takes pictures: its Codex backend reads `input_image` parts, which the
    #: translator sends for every image a client attaches (caravan/proxy/translate.py). Another
    #: provider's models are promised text alone — the caravan keeps no word of their inputs.
    SUBSCRIPTION_INPUTS = ("text", "image")

    def __init__(self, jobs=(), inputs=(), languages=None, max_audio_ms=None, mixed=False):
        self.jobs = tuple(job for job in JOBS if job in set(jobs or ()))
        self.inputs = tuple(i for i in self.INPUTS if i in set(inputs or ()))
        self.languages = list(languages) if languages else None
        self.max_audio_ms = int(max_audio_ms) if max_audio_ms else None
        self.mixed = bool(mixed)

    # ── one row ──────────────────────────────────────────────────────────

    @staticmethod
    def _positive(value):
        return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None

    @classmethod
    def cell_facts(cls, server):
        """What a cell's router output says of the model behind it (caravan/admin/proxies_config.py),
        from the board's reading of the cell: its jobs (the record rule, model_jobs.cell_jobs), a
        chat cell's inputs (llama.cpp's own /props: `modalities`), the languages and the longest
        recording it said on its health path, the window it serves. Each only when known."""
        server = server if isinstance(server, dict) else {}
        cfg = server.get("slotConfig") if isinstance(server.get("slotConfig"), dict) else {}
        meta = server.get("cellMeta") if isinstance(server.get("cellMeta"), dict) else {}
        facts = {}
        jobs = list(cell_jobs(cell_runner_id(cfg), meta, cfg))
        if jobs:
            facts["jobs"] = jobs
        if jobs == ["llm"]:
            said = server.get("modalities") if isinstance(server.get("modalities"), dict) else {}
            facts["inputs"] = ["text"] + [name for name, flag in (("image", said.get("vision")), ("audio", said.get("audio"))) if flag]
        langs = meta.get("langs")
        if isinstance(langs, list) and langs:
            facts["languages"] = [str(lang) for lang in langs if str(lang).strip()]
        if cls._positive(meta.get("maxAudioMs")):
            facts["maxAudioMs"] = meta["maxAudioMs"]
        if cls._positive(server.get("ctxServed")):
            facts["contextLength"] = server["ctxServed"]
        return facts

    @classmethod
    def clean_facts(cls, raw):
        """A router output's facts as the file may keep them: each of the right shape, or left out.
        The controller writes them (cell_facts); the file can be edited by hand."""
        raw = raw if isinstance(raw, dict) else {}
        facts = {}
        jobs = [job for job in JOBS if job in set(j for j in raw.get("jobs") or () if isinstance(j, str))]
        if jobs:
            facts["jobs"] = jobs
        inputs = [i for i in cls.INPUTS if i in set(i for i in raw.get("inputs") or () if isinstance(i, str))]
        if inputs:
            facts["inputs"] = inputs
        langs = [str(lang).strip()[:32] for lang in raw.get("languages") or () if isinstance(lang, str) and lang.strip()]
        if langs:
            facts["languages"] = langs[:400]
        for key in ("maxAudioMs", "contextLength"):
            if cls._positive(raw.get(key)):
                facts[key] = raw[key]
        return facts

    @classmethod
    def of_row(cls, row, account=None, output=None):
        """The kind of one row that may serve, or None when it says nothing of itself."""
        if row.get("kind", "account") == "account":
            if not account:
                return None
            inputs = cls.SUBSCRIPTION_INPUTS if CloudSources.is_subscription(account) else ("text",)
            return cls(("llm",), inputs)
        jobs = (output or {}).get("jobs")
        if not jobs:
            return None
        return cls(jobs, (output or {}).get("inputs") or ("text",), (output or {}).get("languages"),
                   cls._positive((output or {}).get("maxAudioMs")))

    # ── a pool ───────────────────────────────────────────────────────────

    @staticmethod
    def may_serve(row, account_of, output_of):
        """Whether a row is part of the pool's promise: switched on, cabled, its account or cell there."""
        if not row.get("enabled", True) or row.get("kind", "account") == "open":
            return False
        if row.get("kind", "account") == "account":
            return bool(account_of(row.get("accountId")))
        return bool(output_of(row.get("output")))

    @classmethod
    def of_pool(cls, pool, account_of, output_of):
        """The pool's kind: what every row that may serve does, `mixed` when they share no job,
        None when there is no such row or one of them says nothing of itself.
        `account_of(id)` and `output_of(id)` give an account and a router output, or None."""
        kinds = []
        for row in (pool or {}).get("steps") or []:
            if not isinstance(row, dict) or not cls.may_serve(row, account_of, output_of):
                continue
            account = account_of(row.get("accountId")) if row.get("kind", "account") == "account" else None
            output = output_of(row.get("output")) if row.get("kind", "account") == "output" else None
            kind = cls.of_row(row, account, output)
            if kind is None:
                return None
            kinds.append(kind)
        if not kinds:
            return None
        jobs = set(kinds[0].jobs)
        for kind in kinds[1:]:
            jobs &= set(kind.jobs)
        if not jobs:
            return cls(mixed=True)
        inputs = set(cls.INPUTS)
        for kind in kinds:
            if "llm" in kind.jobs:
                inputs &= set(kind.inputs)
        languages = None
        if all(kind.languages for kind in kinds):
            shared = set(kinds[0].languages)
            for kind in kinds[1:]:
                shared &= set(kind.languages)
            languages = [lang for lang in kinds[0].languages if lang in shared] or None
        audio = [kind.max_audio_ms for kind in kinds]
        return cls(jobs, inputs if "llm" in jobs else (), languages,
                   min(audio) if all(audio) else None)

    # ── what is said of it ───────────────────────────────────────────────

    def serves(self, path):
        """Whether the pool does the work a request's path asks for. A mixed pool is the rows' to
        decide: it answers yes, and the row that cannot refuses."""
        if self.mixed:
            return True
        clean = str(path or "").split("?", 1)[0].rstrip("/")
        return any(clean.endswith(end) for job in self.jobs for end in self.PATHS.get(job, ()))

    def architecture(self):
        """OpenRouter's `architecture` for one kind of work, or None — no kind, or more than one."""
        if self.mixed or len(self.jobs) != 1:
            return None
        job = self.jobs[0]
        inputs = self.inputs if job == "llm" else self.WORK[job][0]
        outputs = self.WORK[job][1]
        return {"modality": "+".join(inputs) + "->" + "+".join(outputs),
                "input_modalities": list(inputs), "output_modalities": list(outputs)}

    def models_entry(self):
        """What a model of GET /v1/models adds: `architecture` and `caravan` — {} for a mixed pool."""
        if self.mixed:
            return {}
        said = {"jobs": list(self.jobs)}
        if self.languages:
            said["languages"] = list(self.languages)
        if self.max_audio_ms:
            said["max_audio_ms"] = self.max_audio_ms
        architecture = self.architecture()
        return {**({"architecture": architecture} if architecture else {}), "caravan": said}

    def state(self):
        """What Routing draws of a pool's kind: its jobs and inputs, or that its rows differ."""
        if self.mixed:
            return {"mixed": True}
        out = {"jobs": list(self.jobs)}
        if "llm" in self.jobs:
            out["inputs"] = list(self.inputs)
        if self.languages:
            out["languages"] = list(self.languages)
        return out
