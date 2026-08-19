"""Runner registry: which inference engines the caravan can launch and which
model formats each accepts.

A "runner" is the launch flavour of a cell. The cell config carries it in the
RUNNER field; legacy configs predate that field and are mapped from CELL_KIND
("command" -> custom, anything else -> llama-server), so every saved config,
snapshot and backup keeps working unchanged.

Stage 1 ships llama-server + custom; the vLLM runner lands next (stage 2) and
faster-whisper after that.

`artifacts` is what the editor greys a runner tab on: the KIND of thing the
runner can launch, not the file extension. Extension alone could not separate
them — an LLM and a speech recognizer are both ".gguf", so picking GigaAM left
the llama.cpp tab enabled and picking Qwen left transcribe.cpp enabled, and both
of those only fail once the engine is already starting. The kinds are

    llm-gguf | asr-gguf | whisper-size | moonshine-lang | safetensors | "*"

where a gguf is sorted into llm/asr by its own stt.* metadata. "*" means the
runner's artifact does not live in MODEL_FILE at all (vLLM reads VLLM_MODEL,
custom runs a command line), so nothing in that field can disqualify it.

`formats` is the older, extension-only version of the same idea, kept because a
browser holding cached JS still reads it. `minCompute` gates a runner on CUDA
compute capability (e.g. NVFP4 checkpoints need >= 10.0) — None means no GPU
requirement at all.
"""
import re

from caravan.common.errors import AppError

RUNNERS = [
    {
        "id": "llama-server",
        "sharedPicker": "source",
        "modelField": "MODEL_FILE",
        "icon": "\U0001f999",
        "labelKey": "runnerLlama",
        "benefitsKey": "runnerLlamaBenefits",
        "formats": ["gguf"],
        "artifacts": ["llm-gguf"],
        "health": "/health",
        "api": "openai",
        "minCompute": None,
    },
    {
        "id": "vllm",
        "sharedPicker": "aim",
        "modelField": "VLLM_MODEL",
        "icon": "\u26a1",
        "labelKey": "runnerVllm",
        "benefitsKey": "runnerVllmBenefits",
        # Any artifact: vLLM reads VLLM_MODEL, so whatever sits in MODEL_FILE
        # cannot disqualify it.
        "artifacts": ["*"],
        # In stage 2 the artifact comes from the runner's own VLLM_MODEL field
        # (HF repo id or a local path) — the unified safetensors picker arrives
        # with the multi-format /hf stage, so the tab never blocks on MODEL_FILE.
        "formats": ["*"],
        "health": "/v1/models",
        "api": "openai",
        "minCompute": None,
        # Per-quant hardware gates (CUDA compute capability): the frontend uses
        # these to grey the tab / warn when the host GPU cannot run the format.
        "formatRequirements": {"nvfp4": 10.0, "fp8": 8.9},
    },
    {
        # faster-whisper speech-to-text (the whisper_server.py that
        # run_whisper.sh launches on every GPU host). The model is a SIZE name
        # (tiny\u2026large-v3) \u2014 faster-whisper downloads it itself, MODEL_FILE is
        # unused; language is a per-request field of the API, not a launch arg.
        "id": "whisper",
        "sharedPicker": "carrier",
        "modelField": "WHISPER_MODEL",
        "icon": "\U0001f399\ufe0f",
        "labelKey": "runnerWhisper",
        "benefitsKey": "runnerWhisperBenefits",
        "artifacts": ["whisper-size"],
        "formats": ["*"],
        "health": "/health",
        "api": "raw",
        "minCompute": None,
    },
    {
        # Moonshine v2 speech-to-text (CPU-only by design): the launcher the
        # installer drops in $HOME runs moonshine_server.py with a LANGUAGE
        # argument. EN's medium-streaming model beats Whisper large-v3 WER at
        # 250M params on a laptop core, so the GPUs stay free for LLMs. The
        # "model" is a language code; the package downloads weights itself.
        "id": "moonshine",
        "sharedPicker": "carrier",
        "modelField": "MOONSHINE_MODEL",
        "icon": "🌙",
        "labelKey": "runnerMoonshine",
        "benefitsKey": "runnerMoonshineBenefits",
        "artifacts": ["moonshine-lang"],
        "formats": ["*"],
        "health": "/health",
        "api": "raw",
        "minCompute": None,
    },
    {
        # transcribe.cpp speech-to-text on the ggml runtime \u2014 the llama.cpp of
        # ASR. Alone among the speech runners it takes a GGUF PATH rather than a
        # size or language code, because one build runs sixteen model families
        # (GigaAM, Parakeet, Canary, Whisper, Qwen3-ASR\u2026) picked by the file. So
        # it reuses MODEL_FILE and the whole model pipeline behind it: the HF
        # browser downloads an ASR gguf into the same models dir, and the picker
        # lists it beside the llama ones. Adding a language later is a download,
        # not another runner. It is why RUSSIAN finally has a good cell: GigaAM-v3
        # sits near 8% WER where whisper large-v3 sits at 21-25%.
        "id": "transcribe",
        "sharedPicker": "source",
        "modelField": "MODEL_FILE",
        "icon": "\U0001f4dd",
        "labelKey": "runnerTranscribe",
        "benefitsKey": "runnerTranscribeBenefits",
        "artifacts": ["asr-gguf"],
        "formats": ["gguf"],
        "health": "/health",
        "api": "raw",
        "minCompute": None,
    },
    {
        # SeamlessM4T v2: speech in one language -> TEXT in another, one model.
        # The fleet could already do EN speech -> RU text with whisper plus an
        # LLM, but that is two cells and the translator only ever sees the
        # transcriber's guess — a misheard name is translated faithfully into
        # the wrong name. Here the translation is conditioned on the audio.
        # It takes a safetensors DIRECTORY, not a gguf: hence its own artifact
        # kind, so picking any other ST folder does not silently switch the
        # runner to this one.
        # Weights are CC-BY-NC-4.0 — non-commercial, unlike whisper (MIT).
        "id": "seamless",
        "sharedPicker": "source",
        "modelField": "MODEL_FILE",
        "icon": "\U0001f310",
        "labelKey": "runnerSeamless",
        "benefitsKey": "runnerSeamlessBenefits",
        "artifacts": ["seamless-st"],
        "formats": ["*"],
        "health": "/health",
        "api": "raw",
        "minCompute": None,
    },
    {
        # NLLB-200 text translation. The other half of the cascade: seamless
        # goes speech -> translated text in one hop and refuses to say what it
        # heard, which is right when you only want the translation and wrong
        # when you need the source words too. whisper + this gives you both,
        # each half inspectable.
        # A dedicated MT model rather than an LLM because they fail differently:
        # an LLM reads the text it translates as possible instructions, and at
        # 600M against 12B this one is cheap enough for text nobody waits on.
        # Its model is an HF REPO ID, like vLLM's — it downloads itself, so
        # nothing has to come through the model browser.
        # Weights are CC-BY-NC-4.0 — non-commercial.
        "id": "translate",
        "sharedPicker": "carrier",
        "modelField": "TRANSLATE_MODEL",
        "icon": "\U0001f504",
        "labelKey": "runnerTranslate",
        "benefitsKey": "runnerTranslateBenefits",
        # Its own kind, like whisper's sizes: the picker rows ARE this runner's
        # checkpoints, so picking one lands here and nothing else claims them.
        "artifacts": ["nllb-repo"],
        "formats": ["*"],
        "health": "/health",
        "api": "raw",
        "minCompute": None,
    },
    {
        "id": "custom",
        "sharedPicker": "ignored",
        "modelField": None,
        "icon": "\U0001f6e0\ufe0f",
        "labelKey": "runnerCustom",
        "benefitsKey": "runnerCustomBenefits",
        # An arbitrary command line — nothing about MODEL_FILE can rule it out.
        "artifacts": ["*"],
        "formats": ["*"],
        "health": "",
        "api": "raw",
        "minCompute": None,
    },
]

WHISPER_SIZES = ("tiny", "base", "small", "medium", "large-v3", "large-v3-turbo", "distil-large-v3")

# Moonshine v2 language models. en is MIT; the rest ship under the free
# Moonshine Community License (registration + attribution, < $1M/yr revenue).
# No Russian — whisper stays the RU recognizer.
MOONSHINE_LANGS = ("en", "es", "zh", "ja", "ko", "vi", "uk", "ar")


def runner_id(config) -> str:
    """Effective runner of a cell config. Explicit RUNNER wins; legacy
    CELL_KIND="command" maps to custom; the default is llama-server."""
    rid = str((config or {}).get("RUNNER") or "").strip().lower()
    if rid:
        return rid
    if str((config or {}).get("CELL_KIND") or "").strip().lower() == "command":
        return "custom"
    return "llama-server"


def uses_token_context(config) -> bool:
    """True when this cell's work is measured in tokens, so CTX_SIZE means
    something to it.

    Every cell config inherits CTX_SIZE from the controller defaults, including
    the ones that will never read it. Rendering it anyway put "🪟 100k" on a
    translation cell — a precise number, in the unit of a different runner,
    for a limit that does not exist. An allow-list is the safe direction here:
    a runner added later shows no window until someone decides it has one.
    """
    return runner_id(config or {}) in ("llama-server", "vllm")


def cell_model_ref(config) -> str:
    """The thing a cell actually serves, as its own runner names it.

    Every runner keeps its model somewhere different — MODEL_FILE for llama,
    VLLM_MODEL for vLLM, TRANSLATE_MODEL for NLLB — and the board used to read
    MODEL_FILE for all of them. A translate cell serving nllb-200 therefore
    rendered as "google gemma-4-31B-it" with a full set of chips (quant, size,
    mmproj, a 100k window) describing a model that was not running: the model
    picker's leftover value, drawn as fact.

    Reading `modelField` off the registry means a new runner cannot inherit
    that lie by omission — check_runner_model_fields.py fails the build if it
    does not say where its model lives.
    """
    cfg = config or {}
    for row in RUNNERS:
        if row["id"] == runner_id(cfg):
            field = row.get("modelField")
            return str(cfg.get(field) or "").strip() if field else ""
    return str(cfg.get("MODEL_FILE") or "").strip()


def cell_artifact_label(config) -> str:
    """What a cell RUNS, in one short phrase, for lists with no room for a card.

    A llama cell's artifact is its MODEL_FILE and callers already show that;
    these are the cells that carry a command instead, which is why the kanban's
    server list rendered them as a bare `:8018`. whisper and vLLM name their
    model in their own field. A custom cell has only the command, so drop the
    boilerplate — the interpreter, the home prefix, the `$PORT` the launcher
    substitutes — and keep what actually identifies it: `bash ~/run_tts.sh
    $PORT cosyvoice` reads as `run_tts.sh cosyvoice`."""
    cfg = config or {}
    rid = runner_id(cfg)
    if rid == "whisper":
        return str(cfg.get("WHISPER_MODEL") or "").strip() or "whisper"
    if rid == "moonshine":
        return f"moonshine {str(cfg.get('MOONSHINE_MODEL') or 'en').strip().lower()}"
    if rid == "transcribe":
        import os as _os
        _m = _os.path.basename(str(cfg.get("MODEL_FILE") or "").strip())
        return _m.removesuffix(".gguf") or "transcribe"
    if rid == "vllm":
        from caravan.admin.models import _ST_FORMAT_HINTS   # local: models imports config_builder
        parts = [p for p in str(cfg.get("VLLM_MODEL") or "").strip().split("/") if p]
        if not parts:
            return "vLLM"
        # Safetensors artifacts live at <Model>/<author>/<FORMAT>, so the last
        # segment names the quantization, not the model — "BF16" on its own
        # tells you nothing about which model the cell serves.
        if len(parts) >= 3 and parts[-1].upper() in _ST_FORMAT_HINTS:
            return f"{parts[-3]} {parts[-1].upper()}"
        return parts[-1]
    if rid != "custom":
        return ""
    cmd = str(cfg.get("COMMAND") or "").strip()
    if not cmd:
        return ""
    cmd = re.sub(r"^(?:exec\s+)?(?:env\s+\S+=\S*\s+)*", "", cmd)
    cmd = re.sub(r"^(?:bash|sh|python3?)\s+", "", cmd)
    cmd = cmd.replace("$HOME/", "").replace("~/", "")
    parts = [p for p in cmd.split() if p not in ('"$PORT"', "$PORT", "'$PORT'")]
    if parts:                       # the script's own path adds nothing here
        parts[0] = parts[0].rsplit("/", 1)[-1]
    return " ".join(parts)[:40]


VLLM_VENV = "$HOME/vllm-venv"

# The version a FIRST-TIME provision installs. Pinned on purpose: an unpinned
# `pip install vllm` gave every new host "whatever PyPI had that day" — the
# pip flavour of the mixed-toolkit franken-build. Update/rollback from the UI
# moves it deliberately; the VLLM_VERSION env var overrides at cell start.
VLLM_DEFAULT_VERSION = "0.24.0"

# One line per step so the cell log tells WHERE a cold provision is (the first
# vLLM start on a host downloads several GB of wheels and can take minutes).
VLLM_BOOTSTRAP_LINES = [
    f'if [ ! -x {VLLM_VENV}/bin/vllm ]; then',
    f'  echo "[caravan] provisioning vLLM venv at {VLLM_VENV} (first start on this host, several minutes)…"',
    f'  python3 -m venv {VLLM_VENV}',
    f'  {VLLM_VENV}/bin/pip install --quiet --upgrade pip',
    f'  {VLLM_VENV}/bin/pip install --quiet "vllm==${{VLLM_VERSION:-{VLLM_DEFAULT_VERSION}}}"',
    'fi',
    # torch-inductor compiles kernels through ninja; venvs provisioned before
    # this line existed lack it, so the check is separate from the vllm one.
    f'[ -x {VLLM_VENV}/bin/ninja ] || {VLLM_VENV}/bin/pip install --quiet ninja',
    # the unit calls venv binaries directly (no activate) — subprocesses like
    # ninja are found via PATH, so put the venv first.
    f'export PATH="{VLLM_VENV}/bin:$PATH"'.replace("$HOME", "${HOME}"),
    # torch-inductor spawns one cicc per core by default; on the 27B NVFP4
    # checkpoint that peaked at ~4 GB PER WORKER and OOMed the host. Four
    # workers keep the compile phase inside a few GB; the compile cache in
    # ~/.cache/vllm makes later starts skip it entirely.
    'export MAX_JOBS=4',
    # fragmentation on tight-VRAM launches (the NVFP4 27B on a 32G card died
    # asking for 1.5G with 0.9G free) — expandable segments reclaim the gaps.
    'export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True',
]


def uses_command_path(config) -> bool:
    """True when the cell launches through the generic command machinery
    (custom cells always; vllm/whisper compile their fields into a command)."""
    return runner_id(config) in {"custom", "vllm", "whisper", "moonshine",
                                 "transcribe", "seamless", "translate"}


def build_whisper_command(config) -> str:
    """The run_whisper.sh line for a whisper cell (no exec). The script and its
    ~/wsr venv are provisioned by the agent installer on every GPU host.

    Models live under the SAME root as everything else: HUGGINGFACE_HUB_CACHE
    points faster-whisper at <models root>/whisper. On the controller start.sh
    the config block defines LLAMA_MODELS_DIR; on clients the env var is unset
    and the fallback is the scout's model cache."""
    size = str((config or {}).get("WHISPER_MODEL") or "").strip() or "large-v3"
    if size not in WHISPER_SIZES:
        size = "large-v3"
    cache = '"${LLAMA_MODELS_DIR:-$HOME/llama-model-cache}/whisper"'
    return f'env HUGGINGFACE_HUB_CACHE={cache} bash $HOME/run_whisper.sh "$PORT" {size}'


def build_transcribe_command(config) -> str:
    """The run_transcribe.sh line for a transcribe.cpp cell.

    Unlike whisper/moonshine, which key their model off a size or language
    string, this engine takes a GGUF path exactly like llama-server does — one
    build runs GigaAM, Parakeet, Canary, Whisper and a dozen more, chosen by the
    file. So the cell reuses MODEL_FILE and the caravan's whole model pipeline:
    the HF browser downloads an ASR GGUF into the same models dir, and the picker
    lists it beside the LLM ones.

    The path is resolved against LLAMA_MODELS_DIR when it is relative, which is
    how the picker stores it. The venv and libtranscribe come from
    scripts/install-transcribe.sh."""
    model = str((config or {}).get("MODEL_FILE") or "").strip()
    if not model:
        raise AppError("MODEL_FILE is required for a transcribe cell", 400)
    if not model.startswith("/") and not model.startswith("$"):
        model = '"${LLAMA_MODELS_DIR:-$HOME/llama.cpp/models}"/' + model
    else:
        model = f'"{model}"'
    return f'bash $HOME/run_transcribe.sh "$PORT" {model}'


def build_moonshine_command(config) -> str:
    """The run_moonshine.sh line for a moonshine cell. The script and its
    ~/moonshine-venv are provisioned by scripts/install-moonshine.sh; the model
    downloads itself on first start, keyed by the LANGUAGE argument."""
    lang = str((config or {}).get("MOONSHINE_MODEL") or "").strip().lower() or "en"
    if lang not in MOONSHINE_LANGS:
        lang = "en"
    return f'bash $HOME/run_moonshine.sh "$PORT" {lang}'


def build_seamless_command(config) -> str:
    """The run_seamless.sh line for a SeamlessM4T cell.

    Takes a DIRECTORY (the downloaded HF folder), not a file: the model is a
    sharded safetensors checkpoint plus its processor config, and transformers
    wants the folder. Resolved against LLAMA_MODELS_DIR when relative, which is
    how the picker stores it — same convention as transcribe."""
    model = str((config or {}).get("MODEL_FILE") or "").strip()
    if not model:
        raise AppError("MODEL_FILE is required for a seamless cell", 400)
    tgt = str((config or {}).get("SEAMLESS_TGT_LANG") or "rus").strip().lower() or "rus"
    if not model.startswith("/") and not model.startswith("$"):
        model = '"${LLAMA_MODELS_DIR:-$HOME/llama.cpp/models}"/' + model
    else:
        model = f'"{model}"'
    return f'bash $HOME/run_seamless.sh "$PORT" {model} {tgt}'


def build_translate_command(config) -> str:
    """The run_translate.sh line for an NLLB cell.

    The model is an HF repo id by default — the weights download themselves on
    first start, so this runner needs nothing from the model browser and no
    MODEL_FILE. A local directory works too, and is passed through unchanged."""
    import shlex
    cfg = config or {}
    model = str(cfg.get("TRANSLATE_MODEL") or "").strip() or "facebook/nllb-200-distilled-600M"
    src = str(cfg.get("TRANSLATE_SRC_LANG") or "eng_Latn").strip() or "eng_Latn"
    tgt = str(cfg.get("TRANSLATE_TGT_LANG") or "rus_Cyrl").strip() or "rus_Cyrl"
    # Under the SAME root as every other model, exactly as whisper does. Left to
    # itself the library downloads into ~/.cache/huggingface, where 4.7 GB is
    # invisible to the models page, uncounted by the disk figures, out of reach
    # of the model GC — and, because the picker lists the models tree, gives the
    # editor nothing to show for a runner that plainly has a model.
    cache = '"${LLAMA_MODELS_DIR:-$HOME/llama-model-cache}/translate"'
    return (f'env HUGGINGFACE_HUB_CACHE={cache} bash $HOME/run_translate.sh "$PORT" '
            f'{shlex.quote(model)} {shlex.quote(src)} {shlex.quote(tgt)}')


def build_vllm_command(config) -> str:
    """The `vllm serve …` line for a cell config (no bootstrap, no exec)."""
    import shlex
    cfg = config or {}
    model = str(cfg.get("VLLM_MODEL") or "").strip()
    parts = [f"{VLLM_VENV}/bin/vllm", "serve", shlex.quote(model),
             "--host", "0.0.0.0", "--port", '"$PORT"']
    served = str(cfg.get("ALIAS") or "").strip() or model.split("/")[-1].lower()
    if served:
        parts += ["--served-model-name", shlex.quote(served)]
    if str(cfg.get("MAX_MODEL_LEN") or "").strip():
        parts += ["--max-model-len", str(cfg.get("MAX_MODEL_LEN")).strip()]
    if str(cfg.get("GPU_MEMORY_UTILIZATION") or "").strip():
        parts += ["--gpu-memory-utilization", str(cfg.get("GPU_MEMORY_UTILIZATION")).strip()]
    quant = str(cfg.get("QUANTIZATION") or "").strip().lower()
    if quant and quant != "auto":
        parts += ["--quantization", quant]
    dtype = str(cfg.get("DTYPE") or "").strip().lower()
    if dtype and dtype != "auto":
        parts += ["--dtype", dtype]
    tp = str(cfg.get("TENSOR_PARALLEL") or "").strip()
    if tp and tp not in ("0", "1"):
        parts += ["--tensor-parallel-size", tp]
    return " ".join(parts)


def effective_command(config, with_bootstrap=False) -> str:
    """Shell command a command-path cell actually runs. For custom cells the
    stored COMMAND; for vllm the built serve line — optionally prefixed with
    the venv bootstrap chain (single-line form for the scout's `bash -lc`)."""
    rid = runner_id(config)
    if rid == "transcribe":
        return build_transcribe_command(config)
    if rid == "seamless":
        return build_seamless_command(config)
    if rid == "translate":
        return build_translate_command(config)
    if rid == "vllm":
        cmd = build_vllm_command(config)
        if with_bootstrap:
            one_liner = (f'[ -x {VLLM_VENV}/bin/vllm ] || (python3 -m venv {VLLM_VENV}'
                         f' && {VLLM_VENV}/bin/pip install --quiet --upgrade pip'
                         f' && {VLLM_VENV}/bin/pip install --quiet vllm)')
            ninja = f'[ -x {VLLM_VENV}/bin/ninja ] || {VLLM_VENV}/bin/pip install --quiet ninja'
            path = f'export PATH="{VLLM_VENV}/bin:$PATH"'
            jobs = "export MAX_JOBS=4"
            alloc = "export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True"
            return f"{one_liner}; {ninja}; {path}; {jobs}; {alloc}; exec {cmd}"
        return cmd
    if rid == "whisper":
        # run_whisper.sh self-carries its env (venv python + cuDNN LD paths);
        # no bootstrap chain — a missing script fails with a clear exec error.
        return build_whisper_command(config)
    if rid == "moonshine":
        # Same shape as whisper: the launcher self-installs its venv on first
        # run, so no bootstrap chain here either.
        return build_moonshine_command(config)
    return str((config or {}).get("COMMAND") or "").strip()


def effective_health_path(config) -> str:
    explicit = str((config or {}).get("HEALTH_PATH") or "").strip()
    if explicit:
        return explicit
    rid = runner_id(config)
    if rid == "vllm":
        return "/v1/models"
    if rid in ("whisper", "moonshine", "transcribe", "seamless", "translate"):
        return "/health"
    return ""
