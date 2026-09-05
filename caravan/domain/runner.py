"""Раннер как класс, а не как строка, с которой все сравниваются.

A "runner" is the launch flavour of a cell. Until now it was an id in a dict and
a chain of `if rid == "..."` in five modules: the registry said what a runner is,
`runners.py` said how to launch it, `launch.py` said what to validate first, and
each of those chains had to be extended by hand when a runner arrived. They were
extended by hand, and they drifted:

  * `effective_health_path` grew a list of runners that answer `/health` while
    the registry already held the same fact in `health` — and the two disagree
    for llama-server to this day (registry `/health`, effective ``), which is
    deliberate and is now stated in one place instead of being inferred from two;
  * `uses_command_path` is "every runner except llama-server", written as a set
    of six names that a seventh runner would have to be remembered into;
  * the cell card read `MODEL_FILE` for every runner until a translate cell
    rendered as a gemma with a full set of chips describing a model that was not
    running.

So: one class per runner, and the questions are methods on it. A runner that
does not answer a question inherits the base's answer, and a runner that is
added cannot be forgotten from a list somewhere else, because there is no list —
`REGISTRY` is the only one, and everything else reads it.

The JSON the frontend receives is unchanged: `registry_json()` renders exactly
the dicts `RUNNERS` used to hold, in the same order, so a browser holding cached
JS sees no difference.
"""
import os
import re
import shlex

from caravan.common.errors import AppError


class Runner:
    """One launch flavour. The base answers for a runner that says nothing.

    Class attributes are the registry row; methods are the behaviour that used
    to be a branch keyed on the id.
    """

    #: What the config's RUNNER field holds.
    id = ""
    icon = ""
    label_key = ""
    benefits_key = ""

    #: The KIND of artifact this runner can launch — not the file extension.
    #: Extension alone could not separate them: an LLM and a speech recognizer
    #: are both ".gguf", so picking GigaAM left the llama.cpp tab enabled and
    #: picking Qwen left transcribe.cpp enabled, and both of those only fail
    #: once the engine is already starting. The kinds are
    #:
    #:     llm-gguf | asr-gguf | whisper-size | moonshine-lang | safetensors | "*"
    #:
    #: where a gguf is sorted into llm/asr by its own stt.* metadata. "*" means
    #: the runner's artifact does not live in MODEL_FILE at all (vLLM reads
    #: VLLM_MODEL, custom runs a command line), so nothing in that field can
    #: disqualify it.
    artifacts = ("*",)
    #: The older, extension-only version of the same idea, kept because a
    #: browser holding cached JS still reads it.
    formats = ("*",)
    #: Health path as the REGISTRY advertises it, for the editor's hints.
    health = ""
    api = "raw"
    #: CUDA compute capability this runner needs (NVFP4 checkpoints want >= 10.0).
    #: None means no GPU requirement at all.
    min_compute = None
    #: Per-quant hardware gates, for greying a tab the host GPU cannot run.
    format_requirements = None

    #: Where in the config this runner keeps its model. None = nowhere.
    model_field = None
    #: How the shared model picker treats this runner: source (the picker's rows
    #: are its artifacts), carrier (it names a model of its own), aim, ignored.
    shared_picker = "ignored"

    #: True when this cell's work is measured in tokens, so CTX_SIZE means
    #: something to it. Every cell config inherits CTX_SIZE from the controller
    #: defaults, including the ones that will never read it; rendering it anyway
    #: put "🪟 100k" on a translation cell — a precise number, in the unit of a
    #: different runner, for a limit that does not exist. Opt-in on purpose: a
    #: runner added later shows no window until someone decides it has one.
    token_context = False
    #: True when the cell launches through the generic command machinery.
    command_path = True
    #: True when the command IS the config — typed by a person rather than built
    #: from fields. Only such a cell has a previous command worth remembering for
    #: a one-click revert; for every other runner the command is regenerated from
    #: the fields, and "the last one" is a re-render, not a decision anyone made.
    free_form_command = False
    #: What `effective_health_path` answers when the config names no path. NOT
    #: the same as `health`: llama-server advertises /health to the editor and
    #: answers "" here, because its health is probed by the llama-specific path
    #: and always has been. Two fields because they are two facts.
    default_health_path = ""
    #: True when start.sh's config block must carry a concrete LLAMA_MODELS_DIR:
    #: the generated command references ${LLAMA_MODELS_DIR} and the launcher's
    #: own fallback points somewhere else.
    needs_models_dir = False

    # ── what a cell of this kind is ──────────────────────────────────────────
    def model_ref(self, config) -> str:
        """The thing a cell actually serves, as this runner names it.

        Every runner keeps its model somewhere different — MODEL_FILE for llama,
        VLLM_MODEL for vLLM, TRANSLATE_MODEL for NLLB — and the board used to
        read MODEL_FILE for all of them. A translate cell serving nllb-200
        therefore rendered as "google gemma-4-31B-it" with a full set of chips
        (quant, size, mmproj, a 100k window) describing a model that was not
        running: the model picker's leftover value, drawn as fact.
        """
        if not self.model_field:
            return ""
        return str((config or {}).get(self.model_field) or "").strip()

    def artifact_label(self, config) -> str:
        """What a cell RUNS, in one short phrase, for lists with no room for a
        card. Empty means "the caller already shows the model file"."""
        return ""

    # ── how a cell of this kind is launched ──────────────────────────────────
    def command(self, config, with_bootstrap=False) -> str:
        """The shell command this cell runs, without `exec`.

        The base answers with the stored COMMAND, which is right for the two
        runners that have no command of their own to build: custom, whose
        command IS the config, and llama-server, which never comes down this
        path at all.
        """
        return str((config or {}).get("COMMAND") or "").strip()

    def bootstrap_lines(self, config):
        """Lines start.sh runs before the exec — provisioning, env. Usually none."""
        return []

    def prepare(self, merged) -> str:
        """Validate and complete `merged` in place, and answer with its command.

        This is what the chain of `elif is_whisper:` in launch.py was: each
        runner needs something different in the config block before its command
        can be written, and getting it wrong produces a cell that starts and
        then cannot find its model.
        """
        if self.needs_models_dir and not merged.get("LLAMA_MODELS_DIR"):
            from caravan.admin.paths import DEFAULT_MODELS_DIR
            merged["LLAMA_MODELS_DIR"] = str(DEFAULT_MODELS_DIR)
        return self.command(merged)

    def preflight_start(self, config, model="") -> None:
        """Refuse a start that cannot possibly work, naming what is missing.

        Not validation for its own sake: without it an unconfigured cell dies
        inside its own launcher, and what reaches the operator is a systemd
        exit code. `model` is what the caller resolved for this cell (its slot's
        model, or MODEL_FILE) — the runners that keep their model elsewhere
        ignore it and read their own field.

        The base refuses nothing: whisper and moonshine have a default size and
        a default language, so an unconfigured cell of theirs still starts.
        """
        return None

    #: True when a start must be gated on free VRAM before it is attempted.
    #: vLLM pre-allocates util×total VRAM and otherwise dies in a minute-long
    #: crash loop; llama.cpp fails fast with a legible message instead.
    vram_gated = False

    def health_path(self, config) -> str:
        explicit = str((config or {}).get("HEALTH_PATH") or "").strip()
        return explicit or self.default_health_path

    # ── what the frontend gets ───────────────────────────────────────────────
    def as_dict(self) -> dict:
        row = {
            "id": self.id,
            "sharedPicker": self.shared_picker,
            "modelField": self.model_field,
            "icon": self.icon,
            "labelKey": self.label_key,
            "benefitsKey": self.benefits_key,
            "formats": list(self.formats),
            "artifacts": list(self.artifacts),
            "health": self.health,
            "api": self.api,
            "minCompute": self.min_compute,
            # Sent so the browser stops keeping its own copy of these two facts.
            # It kept them as lists of runner ids, and the lists went stale: the
            # cell-detail modal enumerated five runners and rendered the other
            # three — seamless and translate among them — as llama-server, with
            # a `llama-server --model …` command line for a cell running
            # run_translate.sh, and a "🪟 100k" window on a translator that has
            # no context window at all.
            "tokenContext": self.token_context,
            "commandPath": self.command_path,
        }
        if self.format_requirements:
            row["formatRequirements"] = dict(self.format_requirements)
        return row


class LlamaServerRunner(Runner):
    """llama.cpp's own server: the default, and the only one not on the
    command path — it has a launch renderer of its own."""
    id = "llama-server"
    icon = "\U0001f999"
    label_key = "runnerLlama"
    benefits_key = "runnerLlamaBenefits"
    formats = ("gguf",)
    artifacts = ("llm-gguf",)
    health = "/health"
    api = "openai"
    model_field = "MODEL_FILE"
    shared_picker = "source"
    token_context = True
    command_path = False


class VllmRunner(Runner):
    """vLLM. Its artifact comes from its own VLLM_MODEL field (an HF repo id or
    a local path), so whatever sits in MODEL_FILE cannot disqualify it."""
    id = "vllm"
    icon = "⚡"
    label_key = "runnerVllm"
    benefits_key = "runnerVllmBenefits"
    artifacts = ("*",)
    formats = ("*",)
    health = "/v1/models"
    api = "openai"
    model_field = "VLLM_MODEL"
    shared_picker = "aim"
    token_context = True
    vram_gated = True
    default_health_path = "/v1/models"
    format_requirements = {"nvfp4": 10.0, "fp8": 8.9}

    venv = "$HOME/vllm-venv"
    #: The version a FIRST-TIME provision installs. Pinned on purpose: an
    #: unpinned `pip install vllm` gave every new host "whatever PyPI had that
    #: day" — the pip flavour of the mixed-toolkit franken-build. Update and
    #: rollback from the UI move it deliberately; VLLM_VERSION overrides at
    #: cell start.
    default_version = "0.24.0"

    @property
    def bootstrap(self):
        """One line per step so the cell log tells WHERE a cold provision is:
        the first vLLM start on a host downloads several GB of wheels and can
        take minutes."""
        venv = self.venv
        return [
            f'if [ ! -x {venv}/bin/vllm ]; then',
            f'  echo "[caravan] provisioning vLLM venv at {venv} (first start on this host, several minutes)…"',
            f'  python3 -m venv {venv}',
            f'  {venv}/bin/pip install --quiet --upgrade pip',
            f'  {venv}/bin/pip install --quiet "vllm==${{VLLM_VERSION:-{self.default_version}}}"',
            'fi',
            # torch-inductor compiles kernels through ninja; venvs provisioned
            # before this line existed lack it, so the check is separate from
            # the vllm one.
            f'[ -x {venv}/bin/ninja ] || {venv}/bin/pip install --quiet ninja',
            # the unit calls venv binaries directly (no activate) — subprocesses
            # like ninja are found via PATH, so put the venv first.
            f'export PATH="{venv}/bin:$PATH"'.replace("$HOME", "${HOME}"),
            # torch-inductor spawns one cicc per core by default; on the 27B
            # NVFP4 checkpoint that peaked at ~4 GB PER WORKER and OOMed the
            # host. Four workers keep the compile phase inside a few GB; the
            # compile cache in ~/.cache/vllm makes later starts skip it.
            'export MAX_JOBS=4',
            # fragmentation on tight-VRAM launches (the NVFP4 27B on a 32G card
            # died asking for 1.5G with 0.9G free) — expandable segments reclaim
            # the gaps.
            'export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True',
        ]

    def bootstrap_lines(self, config):
        return list(self.bootstrap)

    def artifact_label(self, config):
        from caravan.admin.models import _ST_FORMAT_HINTS   # local: models imports config_builder
        parts = [p for p in str((config or {}).get("VLLM_MODEL") or "").strip().split("/") if p]
        if not parts:
            return "vLLM"
        # Safetensors artifacts live at <Model>/<author>/<FORMAT>, so the last
        # segment names the quantization, not the model — "BF16" on its own
        # tells you nothing about which model the cell serves.
        if len(parts) >= 3 and parts[-1].upper() in _ST_FORMAT_HINTS:
            return f"{parts[-3]} {parts[-1].upper()}"
        return parts[-1]

    def command(self, config, with_bootstrap=False) -> str:
        """The `vllm serve …` line (no bootstrap, no exec) — or, with
        `with_bootstrap`, the single-line provisioning chain in front of it for
        the scout's `bash -lc`."""
        cfg = config or {}
        model = str(cfg.get("VLLM_MODEL") or "").strip()
        parts = [f"{self.venv}/bin/vllm", "serve", shlex.quote(model),
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
        cmd = " ".join(parts)
        if not with_bootstrap:
            return cmd
        venv = self.venv
        one_liner = (f'[ -x {venv}/bin/vllm ] || (python3 -m venv {venv}'
                     f' && {venv}/bin/pip install --quiet --upgrade pip'
                     f' && {venv}/bin/pip install --quiet vllm)')
        ninja = f'[ -x {venv}/bin/ninja ] || {venv}/bin/pip install --quiet ninja'
        path = f'export PATH="{venv}/bin:$PATH"'
        jobs = "export MAX_JOBS=4"
        alloc = "export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True"
        return f"{one_liner}; {ninja}; {path}; {jobs}; {alloc}; exec {cmd}"

    def prepare(self, merged) -> str:
        if not merged.get("VLLM_MODEL"):
            raise AppError("VLLM_MODEL is required for a vLLM cell")
        return self.command(merged)

    def preflight_start(self, config, model="") -> None:
        if not str((config or {}).get("VLLM_MODEL") or "").strip():
            raise AppError("vLLM cell has no model — configure it first", 400)


class WhisperRunner(Runner):
    """faster-whisper speech-to-text (the whisper_server.py that run_whisper.sh
    launches on every GPU host). The model is a SIZE name (tiny…large-v3) —
    faster-whisper downloads it itself, MODEL_FILE is unused; language is a
    per-request field of the API, not a launch arg."""
    id = "whisper"
    icon = "\U0001f399️"
    label_key = "runnerWhisper"
    benefits_key = "runnerWhisperBenefits"
    artifacts = ("whisper-size",)
    formats = ("*",)
    health = "/health"
    model_field = "WHISPER_MODEL"
    shared_picker = "carrier"
    default_health_path = "/health"
    #: The command references ${LLAMA_MODELS_DIR} for the shared model root.
    needs_models_dir = True

    sizes = ("tiny", "base", "small", "medium", "large-v3", "large-v3-turbo",
             "distil-large-v3")

    def artifact_label(self, config):
        return str((config or {}).get("WHISPER_MODEL") or "").strip() or "whisper"

    def command(self, config, with_bootstrap=False) -> str:
        """The run_whisper.sh line (no exec). The script and its ~/wsr venv are
        provisioned by the agent installer on every GPU host; it self-carries
        its env (venv python + cuDNN LD paths), so there is no bootstrap chain
        — a missing script fails with a clear exec error.

        Models live under the SAME root as everything else: HUGGINGFACE_HUB_CACHE
        points faster-whisper at <models root>/whisper. On the controller
        start.sh the config block defines LLAMA_MODELS_DIR; on clients the env
        var is unset and the fallback is the scout's model cache."""
        size = str((config or {}).get("WHISPER_MODEL") or "").strip() or "large-v3"
        if size not in self.sizes:
            size = "large-v3"
        cache = '"${LLAMA_MODELS_DIR:-$HOME/llama-model-cache}/whisper"'
        return f'env HUGGINGFACE_HUB_CACHE={cache} bash $HOME/run_whisper.sh "$PORT" {size}'


class MoonshineRunner(Runner):
    """Moonshine v2 speech-to-text (CPU-only by design): the launcher the
    installer drops in $HOME runs moonshine_server.py with a LANGUAGE argument.
    EN's medium-streaming model beats Whisper large-v3 WER at 250M params on a
    laptop core, so the GPUs stay free for LLMs. The "model" is a language code;
    the package downloads weights itself."""
    id = "moonshine"
    icon = "🌙"
    label_key = "runnerMoonshine"
    benefits_key = "runnerMoonshineBenefits"
    artifacts = ("moonshine-lang",)
    formats = ("*",)
    health = "/health"
    model_field = "MOONSHINE_MODEL"
    shared_picker = "carrier"
    default_health_path = "/health"

    #: Moonshine v2 language models. en is MIT; the rest ship under the free
    #: Moonshine Community License (registration + attribution, < $1M/yr
    #: revenue). No Russian — whisper stays the RU recognizer.
    langs = ("en", "es", "zh", "ja", "ko", "vi", "uk", "ar")

    def artifact_label(self, config):
        return f"moonshine {str((config or {}).get('MOONSHINE_MODEL') or 'en').strip().lower()}"

    def command(self, config, with_bootstrap=False) -> str:
        """The run_moonshine.sh line. The script and its ~/moonshine-venv are
        provisioned by scripts/install-moonshine.sh; the model downloads itself
        on first start, keyed by the LANGUAGE argument. Like whisper the
        launcher self-installs, so no bootstrap chain here either.

        The command is SYNTHESIZED from the runner's own field — requiring
        COMMAND here rejected a perfectly valid moonshine cell."""
        lang = str((config or {}).get("MOONSHINE_MODEL") or "").strip().lower() or "en"
        if lang not in self.langs:
            lang = "en"
        return f'bash $HOME/run_moonshine.sh "$PORT" {lang}'


class TranscribeRunner(Runner):
    """transcribe.cpp speech-to-text on the ggml runtime — the llama.cpp of ASR.

    Alone among the speech runners it takes a GGUF PATH rather than a size or
    language code, because one build runs sixteen model families (GigaAM,
    Parakeet, Canary, Whisper, Qwen3-ASR…) picked by the file. So it reuses
    MODEL_FILE and the whole model pipeline behind it: the HF browser downloads
    an ASR gguf into the same models dir, and the picker lists it beside the
    llama ones. Adding a language later is a download, not another runner. It is
    why RUSSIAN finally has a good cell: GigaAM-v3 sits near 8% WER where
    whisper large-v3 sits at 21-25%."""
    id = "transcribe"
    icon = "\U0001f4dd"
    label_key = "runnerTranscribe"
    benefits_key = "runnerTranscribeBenefits"
    artifacts = ("asr-gguf",)
    formats = ("gguf",)
    health = "/health"
    model_field = "MODEL_FILE"
    shared_picker = "source"
    default_health_path = "/health"
    #: Its model is a GGUF PATH, so like whisper it needs the shared model root
    #: spelled out rather than left to the launcher's fallback.
    needs_models_dir = True

    def artifact_label(self, config):
        name = os.path.basename(str((config or {}).get("MODEL_FILE") or "").strip())
        return name.removesuffix(".gguf") or "transcribe"

    def command(self, config, with_bootstrap=False) -> str:
        """The run_transcribe.sh line. The path is resolved against
        LLAMA_MODELS_DIR when it is relative, which is how the picker stores it.
        The venv and libtranscribe come from scripts/install-transcribe.sh."""
        model = str((config or {}).get("MODEL_FILE") or "").strip()
        if not model:
            raise AppError("MODEL_FILE is required for a transcribe cell", 400)
        if not model.startswith("/") and not model.startswith("$"):
            model = '"${LLAMA_MODELS_DIR:-$HOME/llama.cpp/models}"/' + model
        else:
            model = f'"{model}"'
        return f'bash $HOME/run_transcribe.sh "$PORT" {model}'

    def prepare(self, merged) -> str:
        if not merged.get("LLAMA_MODELS_DIR"):
            from caravan.admin.paths import DEFAULT_MODELS_DIR
            merged["LLAMA_MODELS_DIR"] = str(DEFAULT_MODELS_DIR)
        if not merged.get("MODEL_FILE"):
            raise AppError("MODEL_FILE is required for a transcribe cell", 400)
        return self.command(merged)

    def preflight_start(self, config, model="") -> None:
        # Alone among the command-path runners it has NO default to fall back
        # on — its model is a GGUF path, so an unconfigured cell has to be
        # caught here rather than crashing inside the builder.
        if not model:
            raise AppError("transcribe cell has no model — configure it first", 400)


class SeamlessRunner(Runner):
    """SeamlessM4T v2: speech in one language -> TEXT in another, one model.

    The fleet could already do EN speech -> RU text with whisper plus an LLM,
    but that is two cells and the translator only ever sees the transcriber's
    guess — a misheard name is translated faithfully into the wrong name. Here
    the translation is conditioned on the audio.

    It takes a safetensors DIRECTORY, not a gguf: hence its own artifact kind,
    so picking any other ST folder does not silently switch the runner to this
    one. Weights are CC-BY-NC-4.0 — non-commercial, unlike whisper (MIT)."""
    id = "seamless"
    icon = "\U0001f310"
    label_key = "runnerSeamless"
    benefits_key = "runnerSeamlessBenefits"
    artifacts = ("seamless-st",)
    formats = ("*",)
    health = "/health"
    model_field = "MODEL_FILE"
    shared_picker = "source"
    default_health_path = "/health"
    #: Its model is a DIRECTORY under the shared model root, so the block must
    #: carry a concrete LLAMA_MODELS_DIR the same way transcribe does.
    needs_models_dir = True

    def command(self, config, with_bootstrap=False) -> str:
        """The run_seamless.sh line. Takes a DIRECTORY (the downloaded HF
        folder), not a file: the model is a sharded safetensors checkpoint plus
        its processor config, and transformers wants the folder. Resolved
        against LLAMA_MODELS_DIR when relative, which is how the picker stores
        it — same convention as transcribe."""
        cfg = config or {}
        model = str(cfg.get("MODEL_FILE") or "").strip()
        if not model:
            raise AppError("MODEL_FILE is required for a seamless cell", 400)
        tgt = str(cfg.get("SEAMLESS_TGT_LANG") or "rus").strip().lower() or "rus"
        if not model.startswith("/") and not model.startswith("$"):
            model = '"${LLAMA_MODELS_DIR:-$HOME/llama.cpp/models}"/' + model
        else:
            model = f'"{model}"'
        return f'bash $HOME/run_seamless.sh "$PORT" {model} {tgt}'

    def prepare(self, merged) -> str:
        if not merged.get("LLAMA_MODELS_DIR"):
            from caravan.admin.paths import DEFAULT_MODELS_DIR
            merged["LLAMA_MODELS_DIR"] = str(DEFAULT_MODELS_DIR)
        if not merged.get("MODEL_FILE"):
            raise AppError("MODEL_FILE is required for a seamless cell", 400)
        return self.command(merged)

    def preflight_start(self, config, model="") -> None:
        # Same shape as transcribe: its model is a downloaded directory, so
        # there is no default to fall back on.
        if not model:
            raise AppError("seamless cell has no model — configure it first", 400)


class TranslateRunner(Runner):
    """NLLB-200 text translation. The other half of the cascade: seamless goes
    speech -> translated text in one hop and refuses to say what it heard, which
    is right when you only want the translation and wrong when you need the
    source words too. whisper + this gives you both, each half inspectable.

    A dedicated MT model rather than an LLM because they fail differently: an
    LLM reads the text it translates as possible instructions, and at 600M
    against 12B this one is cheap enough for text nobody waits on. Its model is
    an HF REPO ID, like vLLM's — it downloads itself, so nothing has to come
    through the model browser. Weights are CC-BY-NC-4.0 — non-commercial."""
    id = "translate"
    icon = "\U0001f504"
    label_key = "runnerTranslate"
    benefits_key = "runnerTranslateBenefits"
    #: Its own kind, like whisper's sizes: the picker rows ARE this runner's
    #: checkpoints, so picking one lands here and nothing else claims them.
    artifacts = ("nllb-repo",)
    formats = ("*",)
    health = "/health"
    model_field = "TRANSLATE_MODEL"
    shared_picker = "carrier"
    default_health_path = "/health"

    def command(self, config, with_bootstrap=False) -> str:
        """The run_translate.sh line.

        The model is an HF repo id by default — the weights download themselves
        on first start, so this runner needs nothing from the model browser and
        no MODEL_FILE. A local directory works too, and is passed through
        unchanged."""
        cfg = config or {}
        model = str(cfg.get("TRANSLATE_MODEL") or "").strip() or "facebook/nllb-200-distilled-600M"
        src = str(cfg.get("TRANSLATE_SRC_LANG") or "eng_Latn").strip() or "eng_Latn"
        tgt = str(cfg.get("TRANSLATE_TGT_LANG") or "rus_Cyrl").strip() or "rus_Cyrl"
        # Under the SAME root as every other model, exactly as whisper does.
        # Left to itself the library downloads into ~/.cache/huggingface, where
        # 4.7 GB is invisible to the models page, uncounted by the disk figures,
        # out of reach of the model GC — and, because the picker lists the models
        # tree, gives the editor nothing to show for a runner that plainly has a
        # model.
        cache = '"${LLAMA_MODELS_DIR:-$HOME/llama-model-cache}/translate"'
        return (f'env HUGGINGFACE_HUB_CACHE={cache} bash $HOME/run_translate.sh "$PORT" '
                f'{shlex.quote(model)} {shlex.quote(src)} {shlex.quote(tgt)}')

    def prepare(self, merged) -> str:
        # No MODEL_FILE and nothing to resolve: its model is a repo id the
        # launcher hands straight to transformers, which fetches it itself.
        return self.command(merged)


class CustomRunner(Runner):
    """An arbitrary command line — nothing about MODEL_FILE can rule it out."""
    id = "custom"
    icon = "\U0001f6e0️"
    label_key = "runnerCustom"
    benefits_key = "runnerCustomBenefits"
    artifacts = ("*",)
    formats = ("*",)
    health = ""
    model_field = None
    shared_picker = "ignored"
    free_form_command = True

    def artifact_label(self, config):
        """A custom cell has only the command, so drop the boilerplate — the
        interpreter, the home prefix, the `$PORT` the launcher substitutes — and
        keep what actually identifies it: `bash ~/run_tts.sh $PORT cosyvoice`
        reads as `run_tts.sh cosyvoice`. Without this the kanban's server list
        rendered such a cell as a bare `:8018`."""
        cmd = str((config or {}).get("COMMAND") or "").strip()
        if not cmd:
            return ""
        cmd = re.sub(r"^(?:exec\s+)?(?:env\s+\S+=\S*\s+)*", "", cmd)
        cmd = re.sub(r"^(?:bash|sh|python3?)\s+", "", cmd)
        cmd = cmd.replace("$HOME/", "").replace("~/", "")
        parts = [p for p in cmd.split() if p not in ('"$PORT"', "$PORT", "'$PORT'")]
        if parts:                   # the script's own path adds nothing here
            parts[0] = parts[0].rsplit("/", 1)[-1]
        return " ".join(parts)[:40]

    def preflight_start(self, config, model="") -> None:
        if not str((config or {}).get("COMMAND") or "").strip():
            raise AppError("command cell has no command — configure it first", 400)

    def prepare(self, merged) -> str:
        # Be forgiving: strip a leading `exec ` — we add our own.
        command = re.sub(r"^\s*exec\s+", "", merged.get("COMMAND") or "").strip()
        if not command:
            raise AppError("COMMAND is required for a command cell")
        merged["COMMAND"] = command   # keep the config block and the exec line in sync
        return command


class UnknownRunner(Runner):
    """A RUNNER value nothing in the registry answers to.

    It exists so that a config saved by a NEWER caravan — or corrupted — is read
    as "a cell whose runner I do not know" rather than crashing a page that was
    only trying to draw a card. Its answers are the old code's fallbacks: the
    model comes from MODEL_FILE, there is no command to build, and it is not on
    the command path. It is deliberately absent from `REGISTRY`, so nothing
    offers it in the editor.
    """
    id = ""
    model_field = "MODEL_FILE"
    command_path = False


#: Order is the order the editor draws the tabs in.
REGISTRY = (
    LlamaServerRunner(),
    VllmRunner(),
    WhisperRunner(),
    MoonshineRunner(),
    TranscribeRunner(),
    SeamlessRunner(),
    TranslateRunner(),
    CustomRunner(),
)

_BY_ID = {r.id: r for r in REGISTRY}
_UNKNOWN = UnknownRunner()


def runner_id(config) -> str:
    """Effective runner of a cell config. Explicit RUNNER wins; legacy
    CELL_KIND="command" maps to custom; the default is llama-server.

    Legacy configs predate the RUNNER field, so every saved config, snapshot and
    backup keeps working unchanged.
    """
    rid = str((config or {}).get("RUNNER") or "").strip().lower()
    if rid:
        return rid
    if str((config or {}).get("CELL_KIND") or "").strip().lower() == "command":
        return "custom"
    return "llama-server"


def get(rid):
    """The runner with this id, or the unknown-runner stand-in."""
    return _BY_ID.get(str(rid or "").strip().lower(), _UNKNOWN)


def for_config(config):
    """The runner a config runs on. Never None."""
    return get(runner_id(config))


def registry_json():
    """The registry as the frontend has always received it."""
    return [r.as_dict() for r in REGISTRY]
