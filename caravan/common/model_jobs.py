"""What a model DOES — as opposed to what launches it.

Two different questions had one answer on screen. The picker drew the ENGINE
("🦙 llama.cpp", "🌙 moonshine", "🔄 nllb") and left the job to a tooltip, so
reading a row required already knowing that moonshine recognizes speech and
that NLLB translates. Worse, the commonest row said nothing at all: an LLM was
whatever carried no speech badge — the job of most of the list expressed by
silence.

The two questions do not have the same answer even for one file. A `.gguf` is
an LLM or a speech recognizer depending on its own `stt.*` metadata, and both
are launched by different engines. So the job is its own axis, and this is the
one place that computes it.

The vocabulary is deliberately about INPUT → OUTPUT, because that is what the
operator is choosing between:

    llm              text → text
    embed            text → vectors
    asr              speech → text
    tts              text → speech
    translate        text → text in another language
    speech-translate speech → text in another language

`embed` is separate from `llm` for the same kind of reason, and it was got
wrong first: every non-speech gguf was called an LLM, so a live
Qwen3-Embedding cell wore "💬 LLM" on the board. An embedding server answers
/v1/embeddings and returns vectors — llama.cpp's own help says a chat model
cannot also serve embeddings on the same instance — so an operator scanning for
something to chat with would have picked it.

`speech-translate` is separate from `asr` on purpose. SeamlessM4T takes speech
and returns the TARGET language only — no transcript of the source is produced
along the way (its own module docstring says so). A consumer that picked it up
as a recognizer would receive a translation labelled as a transcription.

The twin of this file is static/js/model-jobs.js; both are run against one
table of cases in scripts/test_model_jobs.py, because diverging twins is
exactly the defect this rule was split into its own file to prevent.
"""

#: The whole vocabulary. Order is the order chips are drawn in.
JOBS = ("llm", "embed", "asr", "tts", "translate", "speech-translate")

#: Words a cell may report in `kinds` that mean one of ours. Cell servers grew
#: their own spellings before there was a vocabulary — whisper says
#: "stt.whisper", transcribe says "asr" — so a dotted kind is read by its first
#: segment and the aliases below carry the rest.
_KIND_ALIASES = {
    "stt": "asr",
    "asr": "asr",
    "tts": "tts",
    "translate": "translate",
    "speech-translate": "speech-translate",
    "llm": "llm",
    "embed": "embed",
}

#: What each runner can be, when the cell itself has not said. A runner absent
#: from this map contributes nothing: "custom" runs whatever command a person
#: typed, and guessing its job from the runner id would be inventing a fact.
_RUNNER_JOBS = {
    "llama-server": ("llm",),
    "vllm": ("llm",),
    "whisper": ("asr",),
    "moonshine": ("asr", "tts"),
    "transcribe": ("asr",),
    "seamless": ("speech-translate",),
    "translate": ("translate",),
}


def _ordered(found):
    """The vocabulary's order, not the caller's — so two cells reporting the
    same pair of jobs draw the same pair of chips in the same places."""
    return tuple(job for job in JOBS if job in found)


def jobs_for_artifact(kind, stt_variant="", arch="", family=""):
    """What a model in the picker does, from the row the picker already has.

    `kind` is the picker's own artifact class (model | st | whisper | moonshine
    | translate). A gguf ("model") is split by `stt_variant`: present means the
    file's metadata declares speech weights, and llama-server cannot load it at
    all. Safetensors ("st") are vLLM chat checkpoints except the seamless
    family, told apart by architecture the same way the picker already tells it
    apart to avoid promising a ⚡ that cannot start.

    An unknown kind answers with nothing. A row whose job we cannot name must
    say nothing rather than guess "llm", which is how the silence started.
    """
    kind = str(kind or "").strip()
    if kind == "model":
        if str(stt_variant or "").strip():
            return ("asr",)
        # `family` is what the controller already worked out from the file's own
        # pooling_type (chat models carry none) or its name. Reading it here
        # rather than re-deriving keeps the one answer in the one place.
        return ("embed",) if str(family or "") == "embedding" else ("llm",)
    if kind == "st":
        return ("speech-translate",) if str(arch or "").startswith("seamless_m4t") else ("llm",)
    if kind == "whisper":
        return ("asr",)
    if kind == "moonshine":
        return ("asr", "tts")
    if kind == "translate":
        return ("translate",)
    return ()


def jobs_from_kinds(kinds):
    """The canonical jobs behind whatever a cell reported in `kinds`.

    Read by first segment so "stt.whisper" counts as speech recognition without
    the reader having to know the engine, and unknown words are dropped rather
    than shown: a kind nobody here understands is not a job we can name.
    """
    found = set()
    for raw in kinds or ():
        head = str(raw or "").strip().lower().split(".")[0]
        job = _KIND_ALIASES.get(head)
        if job:
            found.add(job)
    return _ordered(found)


def jobs_for_cell(runner_id, kinds=()):
    """What a RUNNING cell does.

    The cell's own `kinds` wins when it says anything: it is the live report,
    and the runner table is only what a runner is usually for. That order
    matters most for the custom runner, where the table knows nothing and the
    live report is the only thing that can name a TTS cell as one — voice
    cloning runs as a typed command, not as a runner of its own.
    """
    live = jobs_from_kinds(kinds)
    if live:
        return live
    return _ordered(set(_RUNNER_JOBS.get(str(runner_id or "").strip().lower(), ())))
