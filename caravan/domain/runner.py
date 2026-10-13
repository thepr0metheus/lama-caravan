"""A runner as a class, not as a string everything else compares against.

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
    #:     llm-gguf | asr-gguf | strata-gguf | whisper-size | moonshine-lang | safetensors | "*"
    #:
    #: where a gguf is sorted into llm/asr by its own stt.* metadata, and into a
    #: runner's own kind when its architecture is one that runner claims
    #: (gguf_archs). "*" means
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
    #: GGUF architectures only this runner's engine reads (general.architecture
    #: in the file's header): such a file is this runner's kind — artifacts[0] —
    #: and not an LLM that llama.cpp would load. Empty: it claims none.
    gguf_archs = ()
    #: The same for safetensors folders: config.json model_type values only this runner reads.
    #: Such a folder is this runner's kind — artifacts[0] — not a chat checkpoint for vLLM. The
    #: browser kept this as a literal for seamless alone (llama-edit.js, form.js), twice.
    st_archs = ()
    #: The config fields that name model files a command cell of this runner
    #: reads — what its scout fetches before the start (modelFiles), in this
    #: order. The scout fetched MODEL_FILE for every command cell, a leftover
    #: one too, and nothing else: Strata reads its weights and its draft layer.
    model_files = ()
    #: The oldest caravan-scout that can start this runner's cells, as
    #: (major, minor, patch); None: any.
    min_scout = None
    #: The field that holds the cell's context window, for the card's 🪟 when
    #: its machine does not report one. vLLM keeps its own (MAX_MODEL_LEN): read
    #: as CTX_SIZE, its card showed the window every config inherits.
    context_field = "CTX_SIZE"

    #: True when this cell's work is measured in tokens, so CTX_SIZE means
    #: something to it. Every cell config inherits CTX_SIZE from the controller
    #: defaults, including the ones that will never read it; rendering it anyway
    #: put "🪟 100k" on a translation cell — a precise number, in the unit of a
    #: different runner, for a limit that does not exist. Opt-in on purpose: a
    #: runner added later shows no window until someone decides it has one.
    token_context = False
    #: True when the cell launches through the generic command machinery.
    command_path = True
    #: Uses the GGUF parameters, placement and memory estimator of llama.cpp.
    llama_config = False
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
    #: Whether the cell editor draws a tab for this runner. The engine runners
    #: have none: an engine cell is made on the reserve step, choosing the
    #: engine and its model, and the editor's forms are the caravan's own.
    editor_tab = True
    #: A cell whose model runs inside an engine next to it (Ollama, LM Studio),
    #: reserved in that engine with its model — EngineCellMixin says it once.
    engine_cell = False

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

    def model_file_values(self, config) -> dict:
        """{field: path} of the model files this runner's cell reads (model_files), in that
        order, the empty fields left out. The one reading behind both the files a scout is sent
        (model_file_paths) and the controller's hints of where each one is (model_paths)."""
        cfg = config or {}
        return {f: str(cfg.get(f) or "").strip() for f in self.model_files if str(cfg.get(f) or "").strip()}

    def model_file_paths(self, config) -> list[str]:
        """The model files this runner's cell reads, as its config names them
        (model_files), in that order; the empty fields left out."""
        return list(self.model_file_values(config).values())

    # ── how a cell of this kind is launched ──────────────────────────────────
    def command(self, config) -> str:
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

    def vram_reservation(self, config, gpus):
        """What a start reserves on a card the moment it runs — {device,
        reserveMiB, who, why, lower} — so a start the card cannot hold is
        refused before it is attempted; None when it reserves nothing up
        front. vLLM pre-allocates util×total VRAM and otherwise dies in a
        minute-long crash loop; llama.cpp fails fast with a legible message
        instead, so the base reserves nothing. `gpus` are the machine's cards
        as its report or nvidia-smi names them (index, memoryTotalMiB)."""
        return None

    def vram_plan(self):
        """How a start takes VRAM when its cost is not its model's files, for
        the cell form's estimate bar; None when the form has its own figure for
        this runner (llama.cpp sums its files, KV and batch; vLLM reserves its
        utilization of the card). The form sent every runner with a model
        through llama.cpp's sum, and a Strata cell — which sizes itself to the
        card — read "37.2 GB, won't fit" on the 32 GB card it runs on (live
        check, 2026-10-13)."""
        return None

    def pinned_card(self, config, gpus):
        """The card a one-card start lands on: the last CUDA_VISIBLE_DEVICES in the cell's ENV,
        else card 0; None when the pin names no single card or the machine has no such card.
        The browser reads ENV the same way (memory.js FreeVramStart.device), and one table of
        cases holds the two copies together (scripts/test_js_memory.py)."""
        pinned = [v for k, v in self.env_pairs((config or {}).get("ENV")) if k == "CUDA_VISIBLE_DEVICES"]
        device = pinned[-1].strip().strip('"') if pinned else "0"
        if not device.isdigit():
            return None
        if not any(str(g.get("index")) == device for g in gpus or []):
            return None
        return int(device)

    def launch_env(self, config) -> dict:
        """The environment the engine itself must start with, NAME -> value:
        what this controller's start.sh exports before the exec, and what a
        scout sets on the process it starts without a shell. Usually none."""
        return {}

    @staticmethod
    def env_pairs(env_raw):
        """(KEY, VALUE) pairs of a cell's ENV field — newline- or
        comma-separated; a malformed name is skipped, and so is a `#` comment,
        since `#` cannot begin a name. One parser for the exports both
        launchers write and for whatever reads ENV."""
        pairs = []
        for raw in re.split(r"[\n,]", str(env_raw or "")):
            item = raw.strip()
            if "=" not in item:
                continue
            k, v = item.split("=", 1)
            k = k.strip()
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", k):
                pairs.append((k, v.strip()))
        return pairs

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
            "llamaConfig": self.llama_config,
            "editorTab": self.editor_tab,
            "engineCell": self.engine_cell,
            # Sent so the picker sorts a GGUF by the same rule the server does:
            # a file of an architecture only this runner reads is its kind.
            "ggufArchs": list(self.gguf_archs),
            "stArchs": list(self.st_archs),
            "contextField": self.context_field,
            # Sent so the estimate bar draws a start as the scout will judge it.
            "vramPlan": self.vram_plan(),
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
    llama_config = True

    def server_binary(self, llama_home):
        return f"{str(llama_home).rstrip('/')}/build/bin/llama-server"

    def preflight_start(self, config, model="") -> None:
        if re.search(r"(?:PQ2_0|PTQ1_0)", model or self.model_ref(config), re.I):
            raise AppError("This GGUF uses PrismML tensor types — select the PrismML runner", 400)

    def launch_env(self, config):
        # CPU mode (n-gpu-layers 0): hide GPUs entirely. A CUDA-enabled llama.cpp build
        # still initializes the CUDA backend and queries device memory even with -ngl 0
        # (in common_params_print_info), which ABORTS with "CUDA error: out of memory"
        # when the GPU is already full — e.g. an embeddings cell on CPU on a host whose
        # GPU runs another model. Empty CUDA_VISIBLE_DEVICES makes CUDA report no devices,
        # so it falls back to CPU cleanly. (--device none is NOT enough: it stops
        # offloading but the backend still inits and OOMs.) A scout's cell needs it
        # as much as this controller's: the scout used to start the same cell
        # without it.
        if str((config or {}).get("N_GPU_LAYERS", "")).strip() == "0":
            return {"CUDA_VISIBLE_DEVICES": ""}
        return {}


class PrismRunner(LlamaServerRunner):
    """PrismML's fork, with its own binary and matching ggml libraries."""
    id = "prism"
    icon = "🌱"
    label_key = "runnerPrism"
    benefits_key = "runnerPrismBenefits"
    model_field = "MODEL_FILE"

    def server_binary(self, llama_home):
        # Preview only: the scout records the immutable installed release path.
        from pathlib import Path
        return str(Path.home() / ".local/share/caravan/prismml/current/llama-server")

    def preflight_start(self, config, model="") -> None:
        if not (model or self.model_ref(config)):
            raise AppError("PrismML cell has no model — configure it first", 400)

    def launch_env(self, config):
        from pathlib import Path
        folder = str(Path(self.server_binary("")).parent)
        return {**super().launch_env(config), "LD_LIBRARY_PATH": folder, "DYLD_LIBRARY_PATH": folder}


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
    context_field = "MAX_MODEL_LEN"
    default_health_path = "/v1/models"
    format_requirements = {"nvfp4": 10.0, "fp8": 8.9}

    venv = "$HOME/vllm-venv"
    #: The version a FIRST-TIME provision installs. Pinned on purpose: an
    #: unpinned `pip install vllm` gave every new host "whatever PyPI had that
    #: day" — the pip flavour of the mixed-toolkit franken-build. Update and
    #: rollback from the UI move it deliberately; VLLM_VERSION overrides at
    #: cell start. 0.30.0 since 2026-10-05: 0.24.0 carried 28 known
    #: vulnerabilities (osv.dev), fixed in 0.28–0.30.
    default_version = "0.30.0"

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

    def vram_reservation(self, config, gpus):
        """vLLM takes GPU_MEMORY_UTILIZATION (0.9 by default) × the card at
        start. The card is the one CUDA_VISIBLE_DEVICES in the cell's ENV pins
        (a single index), else the first. None when vLLM places itself — tensor
        parallel over several cards, several pinned — or the card is unknown."""
        cfg = config or {}
        if str(cfg.get("TENSOR_PARALLEL") or "").strip() not in ("", "0", "1"):
            return None
        pinned = [v for k, v in self.env_pairs(cfg.get("ENV")) if k == "CUDA_VISIBLE_DEVICES"]
        device = pinned[-1].strip().strip('"') if pinned else "0"
        if not device.isdigit():
            return None
        try:
            util = float(str(cfg.get("GPU_MEMORY_UTILIZATION") or "").strip() or 0.9)
        except ValueError:
            util = 0.9
        card = next((g for g in gpus or [] if str(g.get("index")) == device), None)
        try:
            total = float((card or {}).get("memoryTotalMiB") or 0)
        except (TypeError, ValueError):
            total = 0.0
        if not total:
            return None
        return {"device": int(device), "reserveMiB": int(util * total), "who": "vLLM",
                "why": f"utilization {util:.2f} × {total / 1024:.1f} GiB", "lower": "GPU_MEMORY_UTILIZATION"}

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

    def command(self, config) -> str:
        """The `vllm serve …` line (no bootstrap, no exec). The provisioning in
        front of it is `bootstrap`, one list of lines for start.sh and for the
        one line a scout runs (launch.render_command_cell_shell_line)."""
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
        return " ".join(parts)

    def prepare(self, merged) -> str:
        if not merged.get("VLLM_MODEL"):
            raise AppError("VLLM_MODEL is required for a vLLM cell")
        return self.command(merged)

    def preflight_start(self, config, model="") -> None:
        if not str((config or {}).get("VLLM_MODEL") or "").strip():
            raise AppError("vLLM cell has no model — configure it first", 400)



class StrataRunner(Runner):
    """Strata: Qwen3.8-Flash-Next (177B, 24 576 experts, 10 per token) on one
    32 GB card — its experts compressed by GSQ-RCO to about 2 bits (IQ2_XS: 68
    GB in two GGUF parts), the ones a token needs streamed to the card.

    llama.cpp does not know the model's architecture (qwen4exp; b10357), so a
    file of it is this runner's kind, and picking it lands here. The model is
    two things from the caravan's library: the GGUF's first part (MODEL_FILE —
    the scout brings the second beside it) and the MTP draft layer
    (SPEC_DRAFT_MODEL_FILE, mtp-q2_0.gguf, Strata's own pack of the original
    checkpoint's MTP tensors: about 2x the output speed). What Strata makes from
    them — its pack, the draft layer's runtime, its config — the launcher
    writes into the cell's scratch folder at every start
    (cells/strata_launch.py). The engine is installed on the machine once
    (~/Strata, Strata's own setup.sh), as transcribe.cpp's is."""
    id = "strata"
    icon = "\U0001faa8"
    label_key = "runnerStrata"
    benefits_key = "runnerStrataBenefits"
    artifacts = ("strata-gguf",)
    formats = ("gguf",)
    gguf_archs = ("qwen4exp",)
    health = "/health"
    api = "openai"
    model_field = "MODEL_FILE"
    model_files = ("MODEL_FILE", "SPEC_DRAFT_MODEL_FILE")
    shared_picker = "source"
    token_context = True
    context_field = "STRATA_CONTEXT"
    default_health_path = "/health"
    #: Its model is a GGUF PATH under the shared model root, as transcribe's.
    needs_models_dir = True
    #: The scout that brings both parts and the draft layer (modelFiles, split
    #: GGUFs) and gives the cell a scratch folder for the pack.
    min_scout = (2, 31, 0)

    #: Strata's own answers (setup.py, v0.1.42): the context it recommends for
    #: a 32 GB card, its KV cache types and its draft-vocabulary subsets
    #: (cyrillic: English, code and the Cyrillic script).
    default_context = 131072
    kv_types = ("int8", "q4_0", "k8v4")
    draft_vocabs = ("cyrillic", "cjk", "en", "fr")
    #: The free VRAM below which Strata does not start: its smallest card is
    #: 6 GB (v0.1.38, "a 6 GB card starts"). Asked before the start, since the
    #: start downloads the model first — 68 GB, then a refusal.
    min_free_mib = 6144
    #: The field naming the MiB of VRAM a cell leaves to other cells.
    reserve_field = "STRATA_VRAM_RESERVE_MIB"
    ROOT = '"${LLAMA_MODELS_DIR:-$HOME/llama.cpp/models}"/'

    def artifact_label(self, config):
        name = os.path.basename(str((config or {}).get("MODEL_FILE") or "").strip())
        return re.sub(r"-\d{5}-of-\d{5}\.gguf$|\.gguf$", "", name, flags=re.I) or "Strata"

    def context(self, config) -> int:
        """The window asked for; empty is Strata's own default. Anything else
        is refused, not replaced: a cell started with another window than the
        one its config shows is the wrong cell."""
        raw = str((config or {}).get(self.context_field) or "").strip()
        if not raw:
            return self.default_context
        if not raw.isdigit() or int(raw) <= 0:
            raise AppError(f"{self.context_field} must be a number of tokens, not {raw!r}", 400)
        return int(raw)

    def choice(self, config, field, allowed) -> str:
        """A field with a closed set of values: empty is the first, anything
        outside the set refused."""
        raw = str((config or {}).get(field) or "").strip().lower()
        if not raw:
            return allowed[0]
        if raw not in allowed:
            raise AppError(f"{field} must be one of {', '.join(allowed)}, not {raw!r}", 400)
        return raw

    def reserve(self, config) -> int:
        """MiB of VRAM left to other cells; 0 when the field is empty."""
        raw = str((config or {}).get(self.reserve_field) or "").strip()
        if not raw:
            return 0
        if not raw.isdigit():
            raise AppError(f"{self.reserve_field} must be a number of MiB, not {raw!r}", 400)
        return int(raw)

    def _path(self, rel) -> str:
        rel = str(rel or "").strip()
        if rel.startswith("/") or rel.startswith("$"):
            return shlex.quote(rel)
        return self.ROOT + shlex.quote(rel)

    def command(self, config) -> str:
        """The run_strata.sh line: the model's first part and its draft layer
        under the models root, then Strata's own settings. The launcher checks
        each value again — this line is also typed by hand."""
        cfg = config or {}
        model = str(cfg.get("MODEL_FILE") or "").strip()
        if not model:
            raise AppError("MODEL_FILE is required for a Strata cell", 400)
        parts = [f'bash $HOME/run_strata.sh "$PORT" {self._path(model)}']
        draft = str(cfg.get("SPEC_DRAFT_MODEL_FILE") or "").strip()
        if draft:
            parts += ["--mtp", self._path(draft)]
        parts += ["--context", str(self.context(cfg)),
                  "--kv", self.choice(cfg, "STRATA_KV", self.kv_types),
                  "--draft-vocab", self.choice(cfg, "STRATA_DRAFT_VOCAB", self.draft_vocabs)]
        reserve = self.reserve(cfg)
        if reserve:
            parts += ["--vram-reserve-mib", str(reserve)]
        name = str(cfg.get("MODEL_NAME") or cfg.get("ALIAS") or "").strip()
        if name:
            parts += ["--name", shlex.quote(name)]
        return " ".join(parts)

    def prepare(self, merged) -> str:
        if not merged.get("LLAMA_MODELS_DIR"):
            from caravan.admin.paths import DEFAULT_MODELS_DIR
            merged["LLAMA_MODELS_DIR"] = str(DEFAULT_MODELS_DIR)
        return self.command(merged)

    def preflight_start(self, config, model="") -> None:
        if not (model or self.model_ref(config)):
            raise AppError("Strata cell has no model — configure it first", 400)

    def vram_reservation(self, config, gpus):
        """What a start needs free on its card: min_free_mib, plus the VRAM the
        cell is told to leave to others. The card is the one CUDA_VISIBLE_DEVICES
        in the cell's ENV pins, else the first; None when it is unknown."""
        cfg = config or {}
        device = self.pinned_card(cfg, gpus)
        if device is None:
            return None
        try:
            extra = self.reserve(cfg)
        except AppError:
            return None     # the start itself refuses it, with the field's name
        return {"device": device, "reserveMiB": self.min_free_mib + extra, "who": "Strata",
                "why": "its smallest card is 6 GB" + (f", plus {extra} MiB left to others" if extra else ""),
                "lower": self.reserve_field}

    def vram_plan(self):
        """Strata sizes its expert cache to the card's free VRAM: a start takes
        what is free on its card, less the reserve, and needs min_free_mib plus
        the reserve free — the reservation above, which the scout checks."""
        return {"takesFree": True, "floorMiB": self.min_free_mib, "reserveField": self.reserve_field}

class Gr00tRunner(Runner):
    """NVIDIA GR00T N1.7: a robot policy. Camera frames, the robot's state and an instruction
    in, a chunk of actions out (the SpiderMonkey task, visumap spider-monkey-model-servers,
    2026-10-13).

    Its model is two FOLDERS of the caravan's library: the checkpoint (MODEL_FILE, a safetensors
    folder whose config.json says model_type Gr00tN1d7, hence its own artifact kind) and the
    backbone that checkpoint names (GR00T_BACKBONE, nvidia/Cosmos-Reason2-2B, a gated repository
    the cell never asks the hub for). The scout brings both, as it brings any cell's model. The
    runtime is NVIDIA's Isaac-GR00T, installed once on the machine (scripts/install-gr00t.sh);
    the cell is cells/gr00t_server.py, which answers POST /v1/robot/predict — the path of the
    robot-policy job at the caravan's entry (caravan/common/model_kinds.py)."""
    id = "gr00t"
    icon = "\U0001f9be"
    label_key = "runnerGr00t"
    benefits_key = "runnerGr00tBenefits"
    artifacts = ("gr00t-st",)
    formats = ("*",)
    st_archs = ("Gr00tN1d7",)
    health = "/health"
    model_field = "MODEL_FILE"
    model_files = ("MODEL_FILE", "GR00T_BACKBONE")
    shared_picker = "source"
    default_health_path = "/health"
    #: Its folders are paths under the shared model root, as seamless's.
    needs_models_dir = True
    #: The scout that brings folders (2.30) and a command cell's model files (2.31).
    min_scout = (2, 31, 0)

    #: The backbone the base checkpoint names, where the caravan's library keeps it.
    default_backbone = "Cosmos-Reason2-2B/nvidia/BF16"
    #: The robot the policy acts for: the base checkpoint's DROID tag, the one its own sample
    #: runs on. The runtime holds the list of tags; the cell refuses an unknown one at its start.
    default_embodiment = "OXE_DROID_RELATIVE_EEF_RELATIVE_JOINT"
    #: VRAM a start takes: 7030 MiB measured for the policy on an RTX 5090 (2026-10-13), rounded up.
    min_free_mib = 7680
    ROOT = '"${LLAMA_MODELS_DIR:-$HOME/llama.cpp/models}"/'

    def artifact_label(self, config):
        parts = [p for p in str((config or {}).get("MODEL_FILE") or "").strip().rstrip("/").split("/") if p]
        return parts[0] if parts else "GR00T"

    def _path(self, rel) -> str:
        rel = str(rel or "").strip().rstrip("/")
        if rel.startswith("/") or rel.startswith("$"):
            return shlex.quote(rel)
        return self.ROOT + shlex.quote(rel)

    def embodiment(self, config) -> str:
        """The robot's tag: empty is the default, anything else a tag in the runtime's spelling."""
        raw = str((config or {}).get("GR00T_EMBODIMENT") or "").strip()
        if not raw:
            return self.default_embodiment
        if not re.fullmatch(r"[A-Za-z0-9_]+", raw):
            raise AppError(f"GR00T_EMBODIMENT must be an embodiment tag such as {self.default_embodiment}, "
                           f"not {raw!r}", 400)
        return raw

    def denoising_steps(self, config) -> int:
        """The action head's denoising steps; 0 when empty — the checkpoint's own."""
        raw = str((config or {}).get("GR00T_DENOISING_STEPS") or "").strip()
        if not raw:
            return 0
        if not raw.isdigit() or not 1 <= int(raw) <= 64:
            raise AppError(f"GR00T_DENOISING_STEPS must be a number from 1 to 64, not {raw!r}", 400)
        return int(raw)

    def command(self, config) -> str:
        """The run_gr00t.sh line: both folders under the models root, then the robot and the
        cell's name. The cell checks each value again — this line is also typed by hand."""
        cfg = config or {}
        model = str(cfg.get("MODEL_FILE") or "").strip()
        if not model:
            raise AppError("MODEL_FILE is required for a GR00T cell: the checkpoint's folder", 400)
        backbone = str(cfg.get("GR00T_BACKBONE") or "").strip() or self.default_backbone
        parts = [f'bash $HOME/run_gr00t.sh "$PORT" {self._path(model)}',
                 "--backbone", self._path(backbone), "--embodiment", self.embodiment(cfg)]
        steps = self.denoising_steps(cfg)
        if steps:
            parts += ["--denoising-steps", str(steps)]
        name = str(cfg.get("MODEL_NAME") or cfg.get("ALIAS") or "").strip()
        if name:
            parts += ["--name", shlex.quote(name)]
        return " ".join(parts)

    def model_file_values(self, config) -> dict:
        """The checkpoint and the backbone, the latter by default when its field is empty: the
        scout brings the folder the command names, not the field's emptiness."""
        cfg = dict(config or {})
        if not str(cfg.get("GR00T_BACKBONE") or "").strip():
            cfg["GR00T_BACKBONE"] = self.default_backbone
        return super().model_file_values(cfg)

    def prepare(self, merged) -> str:
        if not merged.get("LLAMA_MODELS_DIR"):
            from caravan.admin.paths import DEFAULT_MODELS_DIR
            merged["LLAMA_MODELS_DIR"] = str(DEFAULT_MODELS_DIR)
        return self.command(merged)

    def preflight_start(self, config, model="") -> None:
        if not (model or self.model_ref(config)):
            raise AppError("GR00T cell has no checkpoint — configure it first", 400)

    def vram_reservation(self, config, gpus):
        """What a start needs free on its card: the policy's measured footprint."""
        device = self.pinned_card(config, gpus)
        if device is None:
            return None
        return {"device": device, "reserveMiB": self.min_free_mib, "who": "GR00T",
                "why": "the policy took 7.0 GB on an RTX 5090", "lower": ""}

    def vram_plan(self):
        """A fixed figure: the policy and its backbone take what they took when measured."""
        return {"fixedMiB": self.min_free_mib}


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

    def command(self, config) -> str:
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

    def command(self, config) -> str:
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
    model_files = ("MODEL_FILE",)
    shared_picker = "source"
    default_health_path = "/health"
    #: Its model is a GGUF PATH, so like whisper it needs the shared model root
    #: spelled out rather than left to the launcher's fallback.
    needs_models_dir = True

    def artifact_label(self, config):
        name = os.path.basename(str((config or {}).get("MODEL_FILE") or "").strip())
        return name.removesuffix(".gguf") or "transcribe"

    def command(self, config) -> str:
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
    st_archs = ("seamless_m4t", "seamless_m4t_v2")
    health = "/health"
    model_field = "MODEL_FILE"
    model_files = ("MODEL_FILE",)
    shared_picker = "source"
    default_health_path = "/health"
    #: Its model is a DIRECTORY under the shared model root, so the block must
    #: carry a concrete LLAMA_MODELS_DIR the same way transcribe does.
    needs_models_dir = True

    def command(self, config) -> str:
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

    def command(self, config) -> str:
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


class EngineCellMixin:
    """A cell whose model runs inside an engine next to it (Ollama, LM Studio).

    The engine listens on 127.0.0.1 only; the cell's own port is the way in
    (cells/engine_cell_server.py), which loads the model when the cell starts
    and unloads it when it stops. What the two engines share lives here once —
    a mixin rather than a base class, because every *Runner class is a row of
    the registry. The config names the model as the engine does
    (ENGINE_MODEL) and the engine's loopback port (ENGINE_PORT), both written
    when the cell is reserved in that engine.
    """
    artifacts = ("engine-model",)
    formats = ("*",)
    health = "/health"
    default_health_path = "/health"
    model_field = "ENGINE_MODEL"
    shared_picker = "ignored"
    editor_tab = False
    engine_cell = True
    #: The engine's own port when the config does not say.
    default_engine_port = 0

    def engine_port(self, config) -> int:
        try:
            port = int(str((config or {}).get("ENGINE_PORT") or "").strip() or self.default_engine_port)
        except ValueError:
            raise AppError(f"ENGINE_PORT is not a port: {(config or {}).get('ENGINE_PORT')!r}", 400)
        if not 0 < port < 65536:
            raise AppError(f"ENGINE_PORT is not a port: {port}", 400)
        return port

    def command(self, config) -> str:
        """The run_engine.sh line: a scout brings a cell's files into $HOME by
        the launcher its command names, and a bare `python3 …server.py` names
        none — the server would never reach the machine."""
        model = self.model_ref(config)
        if not model:
            raise AppError(f"ENGINE_MODEL is required for a {self.id} cell", 400)
        return (f'bash $HOME/run_engine.sh "$PORT" {self.id} {self.engine_port(config)} '
                f'{shlex.quote(model)}')

    def prepare(self, merged) -> str:
        return self.command(merged)

    def preflight_start(self, config, model="") -> None:
        if not self.model_ref(config):
            raise AppError(f"{self.id} cell has no model — reserve it with one", 400)

    def artifact_label(self, config) -> str:
        return self.model_ref(config)


class OllamaRunner(EngineCellMixin, Runner):
    """A model inside Ollama, reached through the cell's port."""
    id = "ollama"
    icon = "\U0001f7e0"
    label_key = "runnerOllama"
    default_engine_port = 11434


class LmStudioRunner(EngineCellMixin, Runner):
    """A model inside LM Studio, reached through the cell's port."""
    id = "lmstudio"
    icon = "\U0001f7e3"
    label_key = "runnerLmStudio"
    default_engine_port = 1234


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
    PrismRunner(),
    VllmRunner(),
    StrataRunner(),
    Gr00tRunner(),
    WhisperRunner(),
    MoonshineRunner(),
    TranscribeRunner(),
    SeamlessRunner(),
    TranslateRunner(),
    CustomRunner(),
    OllamaRunner(),
    LmStudioRunner(),
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
