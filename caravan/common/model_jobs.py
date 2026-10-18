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
    voice-chat       speech (or text) → speech: a model you talk to and it talks back
    robot-policy     camera frames + robot state + instruction → robot actions

`embed` is separate from `llm` for the same kind of reason, and it was got
wrong first: every non-speech gguf was called an LLM, so a live
Qwen3-Embedding cell wore "💬 LLM" on the board. An embedding server answers
/v1/embeddings and returns vectors — llama.cpp's own help says a chat model
cannot also serve embeddings on the same instance — so an operator scanning for
something to chat with would have picked it.

`voice-chat` is a model that answers in a VOICE (PersonaPlex, Step-Audio 2, Qwen3-Omni, MiniCPM-o, 2026-10-15): a
spoken question in, a spoken answer out. It is not `tts` — a text-to-speech cell reads out the text it is given and
answers nothing — and not `llm`: a chat client that picked it from a list of chat models would get the words and
never the voice, or (PersonaPlex, MiniCPM-o) a WebSocket it cannot speak. Where it also answers an ordinary chat
(Step-Audio 2, Qwen3-Omni over vLLM's OpenAI API) it has both jobs, and the entry serves it as a chat model.

`robot-policy` is a vision-language-action model (GR00T N1.7, 2026-10-13): it
answers POST /v1/robot/predict with numbers for a robot to execute, which no
chat client can read. Calling it an LLM because a language model sits inside it
would put it in chat lists, so it is its own job.

`speech-translate` is separate from `asr` on purpose. SeamlessM4T takes speech
and returns the TARGET language only — no transcript of the source is produced
along the way (its own module docstring says so). A consumer that picked it up
as a recognizer would receive a translation labelled as a transcription.

The twin of this file is static/js/model-jobs.js; both are run against one
table of cases in scripts/test_model_jobs.py, because diverging twins is
exactly the defect this rule was split into its own file to prevent.
"""

#: The whole vocabulary. Order is the order chips are drawn in.
JOBS = ("llm", "embed", "asr", "tts", "translate", "speech-translate", "voice-chat", "robot-policy")

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
    # How the engines next to the cells say it of their models: LM Studio's
    # model list types each one "llm", "vlm" (a vision-language model — text
    # out, so a chat model) or "embedding".
    "vlm": "llm",
    "embedding": "embed",
    "voice-chat": "voice-chat",
    "robot-policy": "robot-policy",
    # A vision-language-action model, as the field calls it.
    "vla": "robot-policy",
}

#: What each runner can be, when the cell itself has not said. A runner absent
#: from this map contributes nothing: "custom" runs whatever command a person
#: typed, and guessing its job from the runner id would be inventing a fact.
_RUNNER_JOBS = {
    "llama-server": ("llm",),
    # PrismML's fork of llama.cpp: a chat model like its parent. The browser's
    # twin said so and this one did not — a prism cell's row in a pool did
    # nothing on the server's word while its card said "llm".
    "prism": ("llm",),
    "vllm": ("llm",),
    "strata": ("llm",),
    "whisper": ("asr",),
    "moonshine": ("asr", "tts"),
    "transcribe": ("asr",),
    "seamless": ("speech-translate",),
    "translate": ("translate",),
    "gr00t": ("robot-policy",),
    # The voice servers (1.3.553). LFM2.5-Audio is a speaker first (its cell says "tts" itself, and the table agrees);
    # Step-Audio 2 and Qwen3-Omni answer a chat too, over vLLM's OpenAI API; PersonaPlex and MiniCPM-o are voice and
    # nothing else (a page and a WebSocket).
    "personaplex": ("voice-chat",),
    "lfm-audio": ("tts",),
    "step-audio2": ("llm", "voice-chat"),
    "qwen3-omni": ("llm", "voice-chat"),
    "minicpm-omni": ("voice-chat",),
}

#: What a safetensors folder of an architecture only one runner reads does: the claims of runner.py (`st_archs`), with
#: that runner's jobs. The seamless and GR00T families are told by the start of their name (below), as they always were;
#: scripts/test_launcher_runners.py holds this table to the registry.
_ARCH_JOBS = {
    "personaplex": ("voice-chat",),
    "Lfm2AudioForConditionalGeneration": ("tts",),
    "step_audio_2": ("llm", "voice-chat"),
    "qwen3_omni_moe": ("llm", "voice-chat"),
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
    all. Safetensors ("st") are vLLM chat checkpoints except the seamless and
    GR00T families and the voice models (_ARCH_JOBS), told apart by architecture
    (config.json model_type, else its first architecture) the same way the picker
    already tells them apart to avoid promising a ⚡ that cannot start.

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
        arch = str(arch or "")
        if arch.startswith("seamless_m4t"):
            return ("speech-translate",)
        if arch in _ARCH_JOBS:
            return _ARCH_JOBS[arch]
        return ("robot-policy",) if arch.lower().startswith("gr00t") else ("llm",)
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


#: The values of a cell's ENABLE_EMBEDDINGS that leave it off.
_OFF = ("", "0", "no", "false", "off")


def cell_runner_id(cfg):
    """The runner that launches a cell: its RUNNER, a command cell's "custom", or llama-server.
    The twin of static/js/model-jobs.js cellRunnerId."""
    c = cfg if isinstance(cfg, dict) else {}
    runner = str(c.get("RUNNER") or "").strip().lower()
    if runner:
        return runner
    return "custom" if str(c.get("CELL_KIND") or "").lower() == "command" else "llama-server"


def cell_jobs(runner_id, cell_meta, cfg):
    """What a cell DOES, from its record: its settings and what it says of itself. The twin of
    static/js/model-jobs.js cellJobs — the board draws the chips by that one, the controller tells
    the proxy by this one what each cell's pool row does (1.3.502), and scripts/test_model_jobs.py
    runs both against one table of cases.

    An embedding server is an embedding server whatever its runner; a cell this controller holds
    no settings for is what it says it is, or nothing — the runner on record would be a guess."""
    c = cfg if isinstance(cfg, dict) else {}
    if str(c.get("ENABLE_EMBEDDINGS") or "").strip().lower() not in _OFF:
        return ("embed",)
    kinds = (cell_meta or {}).get("kinds") if isinstance(cell_meta, dict) else None
    if not c:
        return jobs_for_cell("", kinds or ())
    return jobs_for_cell(runner_id, kinds or ())
