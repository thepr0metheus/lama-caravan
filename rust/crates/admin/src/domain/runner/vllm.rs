//! vLLM. Its artifact comes from its own `VLLM_MODEL` field, an HF repo id, a path on the machine or a place among the controller's models, so whatever sits in `MODEL_FILE` cannot disqualify it.

use super::{Config, MODELS_ROOT, PinnedCard, Runner, RunnerDefaults, RunnerRow, TalkSpec};
use rules::{AppError, CellDoor, Coerce, ConfigField, Flag, PyRepr, ShellWord};
use serde_json::{Value, json};
use std::collections::BTreeMap;

/// The runner.
pub struct VllmRunner;

impl VllmRunner {
    const ROW: RunnerRow = RunnerRow {
        id: "vllm",
        icon: "⚡",
        label_key: "runnerVllm",
        benefits_key: "runnerVllmBenefits",
        minus_key: "runnerVllmMinus",
        health: "/v1/models",
        api: "openai",
        talk: TalkSpec { modes: &["text-chat"], ..TalkSpec::NONE },
        model_field: Some("VLLM_MODEL"),
        shared_picker: "aim",
        token_context: true,
        context_field: "MAX_MODEL_LEN",
        default_health_path: "/v1/models",
        format_requirements: &[("nvfp4", 10.0), ("fp8", 8.9)],
        ..RunnerRow::BASE
    };
    const VENV: &'static str = "$HOME/vllm-venv";
    /// The version a FIRST-TIME provision installs. Pinned on purpose: an unpinned `pip install vllm` gave every new host "whatever PyPI had that day". 0.30.0 since 2026-10-05: 0.24.0 carried 28 known vulnerabilities.
    /// The vLLM a cell gets when it names none.
    pub const DEFAULT_VERSION: &'static str = "0.30.0";

    /// The field's value when it has the shape, "" when empty; anything else is refused by the field's name, not replaced: a cell started with another flag than the form shows is the wrong cell.
    fn flag_value(config: &Config, field: &str, shape: fn(&str) -> bool, what: &str) -> Result<String, AppError> {
        let raw = ConfigField::word(config, field);
        if !raw.is_empty() && !shape(&raw) {
            return Err(AppError::new(format!("{field} must be {what}, not {}", PyRepr::of(&raw))));
        }
        Ok(raw)
    }

    /// `[1-9][0-9]{0,5}`.
    fn is_seqs(text: &str) -> bool {
        (1..=6).contains(&text.len()) && !text.starts_with('0') && text.chars().all(|letter| letter.is_ascii_digit())
    }

    /// `[A-Za-z0-9_]{1,40}`.
    fn is_dtype(text: &str) -> bool {
        (1..=40).contains(&text.len()) && text.chars().all(|letter| letter.is_ascii_alphanumeric() || letter == '_')
    }

    /// `[A-Za-z0-9_.-]{1,64}`.
    fn is_name(text: &str) -> bool {
        (1..=64).contains(&text.len())
            && text.chars().all(|letter| letter.is_ascii_alphanumeric() || matches!(letter, '_' | '.' | '-'))
    }

    /// `[0-9]{1,4}(\.[0-9]{1,2})?`.
    fn is_gib(text: &str) -> bool {
        let digits =
            |part: &str, most: usize| (1..=most).contains(&part.len()) && part.chars().all(|letter| letter.is_ascii_digit());
        match text.split_once('.') {
            Some((whole, part)) => digits(whole, 4) && digits(part, 2),
            None => digits(text, 4),
        }
    }

    /// The name it answers with: its operator's, else its alias, else its checkpoint's (the owner's check, 2026-11-01: a cell named by its operator answered under the alias the form
    /// took from another field, and a request by its name found no model).
    fn served_name(config: &Config, model: &str) -> String {
        for field in ["MODEL_NAME", "ALIAS"] {
            let said = ConfigField::word(config, field);
            if !said.is_empty() {
                return said;
            }
        }
        model.rsplit('/').next().unwrap_or(model).to_lowercase()
    }

    fn flags_of_recipe(config: &Config, parts: &mut Vec<String>) -> Result<(), AppError> {
        // The three flags a model's recipe asks for: only their SHAPE is checked: the sets are vLLM's and move with its versions.
        let seqs = Self::flag_value(config, "MAX_NUM_SEQS", Self::is_seqs, "a number of sequences, 1 or more")?;
        if !seqs.is_empty() {
            parts.extend(["--max-num-seqs".to_string(), seqs]);
        }
        let kv =
            Self::flag_value(config, "KV_CACHE_DTYPE", Self::is_dtype, "a data type such as fp8 (letters, digits, underscore)")?
                .to_lowercase();
        if !kv.is_empty() && kv != "auto" {
            parts.extend(["--kv-cache-dtype".to_string(), kv]);
        }
        let reasoning = Self::flag_value(
            config,
            "REASONING_PARSER",
            Self::is_name,
            "a parser's name such as qwen3 (letters, digits, . _ -)",
        )?;
        if !reasoning.is_empty() {
            parts.extend(["--reasoning-parser".to_string(), reasoning]);
        }
        // Weights that stay in RAM and come to the card for every pass: the owner's way to run a model larger than the card without the processor computing any of it.
        let offload = Self::flag_value(config, "CPU_OFFLOAD_GB", Self::is_gib, "a number of GiB such as 12 or 7.5")?;
        if offload.parse::<f64>().is_ok_and(|gib| gib > 0.0) {
            parts.extend(["--cpu-offload-gb".to_string(), offload]);
        }
        Ok(())
    }
}

impl Runner for VllmRunner {
    fn row(&self) -> &RunnerRow {
        &Self::ROW
    }

    /// One line per step, so that the cell log tells WHERE a cold provision is: the first vLLM start on a host downloads several GB of wheels.
    fn bootstrap_lines(&self) -> Vec<String> {
        let venv = Self::VENV;
        let version = Self::DEFAULT_VERSION;
        vec![
            format!("if [ ! -x {venv}/bin/vllm ]; then"),
            format!("  echo \"[caravan] provisioning vLLM venv at {venv} (first start on this host, several minutes)…\""),
            format!("  python3 -m venv {venv}"),
            format!("  {venv}/bin/pip install --quiet --upgrade pip"),
            format!("  {venv}/bin/pip install --quiet \"vllm==${{VLLM_VERSION:-{version}}}\""),
            "fi".to_string(),
            // torch-inductor compiles kernels through ninja; venvs provisioned before this line existed lack it.
            format!("[ -x {venv}/bin/ninja ] || {venv}/bin/pip install --quiet ninja"),
            // flashinfer-cubin stayed behind flashinfer when vLLM moved on (0.30.0, 2026-10-05), and FlashInfer refuses to start with the two apart: the pair that differs is removed.
            format!("fi_py=$(ls -d {venv}/lib/python3*/site-packages/flashinfer_python-*.dist-info 2>/dev/null | head -n 1 | sed 's/.*flashinfer_python-//; s/[.]dist-info$//' || true)"),
            format!("fi_cu=$(ls -d {venv}/lib/python3*/site-packages/flashinfer_cubin-*.dist-info 2>/dev/null | head -n 1 | sed 's/.*flashinfer_cubin-//; s/[.]dist-info$//' || true)"),
            "if [ -n \"$fi_py\" ] && [ -n \"$fi_cu\" ] && [ \"$fi_py\" != \"$fi_cu\" ]; then".to_string(),
            "  echo \"[caravan] flashinfer-cubin $fi_cu does not match flashinfer $fi_py: removing it, FlashInfer fetches its own kernels\"".to_string(),
            format!("  {venv}/bin/pip uninstall --quiet -y flashinfer-cubin"),
            "fi".to_string(),
            // The unit calls venv binaries directly: subprocesses like ninja are found via PATH.
            format!("export PATH=\"{venv}/bin:$PATH\"").replace("$HOME", "${HOME}"),
            // torch-inductor spawns one cicc per core by default: about 4 GB PER WORKER on the 27B checkpoint, and the host ran out of memory.
            "export MAX_JOBS=4".to_string(),
            // Fragmentation on tight-VRAM launches: expandable segments reclaim the gaps.
            "export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True".to_string(),
        ]
    }

    /// vLLM takes `GPU_MEMORY_UTILIZATION` (0.9 by default) × the card at start. `None` when vLLM places itself, or the card is unknown.
    fn vram_reservation(&self, config: &Config, gpus: &[Value]) -> Option<Value> {
        if !matches!(ConfigField::word(config, "TENSOR_PARALLEL").as_str(), "" | "0" | "1") {
            return None;
        }
        let device = PinnedCard::device(config)?;
        let util_word = ConfigField::word(config, "GPU_MEMORY_UTILIZATION");
        // absent-ok: 0.9 is vLLM's own default, for a field empty or of no number.
        let util = if util_word.is_empty() { 0.9 } else { util_word.parse().unwrap_or(0.9) };
        let card = gpus.iter().find(|gpu| Coerce::str_of(gpu.get("index")) == device.to_string());
        let total = card
            .and_then(|card| card.get("memoryTotalMiB"))
            .filter(|said| Coerce::truthy(Some(*said)))
            .and_then(Coerce::float)
            .filter(|total| *total != 0.0)?;
        Some(json!({
            "device": device,
            "reserveMiB": (util * total).trunc() as i64,
            "who": "vLLM",
            "why": format!("utilization {util:.2} × {:.1} GiB", total / 1024.0),
            "lower": "GPU_MEMORY_UTILIZATION",
        }))
    }

    fn keeps_ram(&self) -> bool {
        true
    }

    /// The weights `CPU_OFFLOAD_GB` leaves in RAM, on each card it takes: they stay resident all the time the cell runs.
    fn ram_reservation(&self, config: &Config, _sizes: &BTreeMap<String, i64>) -> Option<Value> {
        let word = ConfigField::word(config, "CPU_OFFLOAD_GB");
        let gib: f64 = if word.is_empty() { 0.0 } else { word.parse().ok()? };
        if gib <= 0.0 {
            return None;
        }
        let parallel = ConfigField::word(config, "TENSOR_PARALLEL").parse::<i64>().ok().filter(|cards| *cards > 1);
        let cards = parallel.unwrap_or(1);
        Some(json!({
            "reserveMiB": (gib * 1024.0 * cards as f64).trunc() as i64,
            "who": "vLLM",
            "lower": "CPU_OFFLOAD_GB",
            "why": format!("{gib} GiB of weights on each of {cards} card(s) stay in memory and come to the card for every pass"),
        }))
    }

    /// Safetensors artifacts live at `<Model>/<author>/<FORMAT>`, so the last segment names the quantization, not the model.
    fn artifact_label(&self, config: &Config, quant_words: &[&str]) -> String {
        let model = ConfigField::word(config, "VLLM_MODEL");
        let parts: Vec<&str> = model.split('/').filter(|part| !part.is_empty()).collect();
        let Some(last) = parts.last() else {
            return "vLLM".to_string();
        };
        let upper = last.to_uppercase();
        match parts.len().checked_sub(3).and_then(|at| parts.get(at)) {
            Some(model) if quant_words.contains(&upper.as_str()) => format!("{model} {upper}"),
            _ => (*last).to_string(),
        }
    }

    fn named_by_place(&self, config: &Config) -> Option<String> {
        let said = ConfigField::word(config, "VLLM_MODEL");
        let said = said.trim_end_matches('/');
        (!said.is_empty() && !said.starts_with(['/', '~', '$', '"'])).then(|| said.to_string())
    }

    /// The `vllm serve …` line, no bootstrap, no exec.
    fn command(&self, config: &Config) -> Result<String, AppError> {
        let model = ConfigField::word(config, "VLLM_MODEL");
        // A place among the controller's models is said from where the scout brought them; the rest as it is written.
        let word = model
            .strip_prefix(MODELS_ROOT)
            .map_or_else(|| ShellWord::quote(&model), |place| format!("{MODELS_ROOT}{}", ShellWord::quote(place)));
        let mut parts: Vec<String> = vec![
            format!("{}/bin/vllm", Self::VENV),
            "serve".to_string(),
            word,
            "--host".to_string(),
            CellDoor::LISTEN.to_string(),
            "--port".to_string(),
            "\"$PORT\"".to_string(),
        ];
        let served = Self::served_name(config, &model);
        if !served.is_empty() {
            parts.extend(["--served-model-name".to_string(), ShellWord::quote(&served)]);
        }
        for (field, flag) in [("MAX_MODEL_LEN", "--max-model-len"), ("GPU_MEMORY_UTILIZATION", "--gpu-memory-utilization")] {
            let said = ConfigField::word(config, field);
            if !said.is_empty() {
                parts.extend([flag.to_string(), said]);
            }
        }
        for (field, flag) in [("QUANTIZATION", "--quantization"), ("DTYPE", "--dtype")] {
            let said = ConfigField::word(config, field).to_lowercase();
            if !said.is_empty() && said != "auto" {
                parts.extend([flag.to_string(), said]);
            }
        }
        let parallel = ConfigField::word(config, "TENSOR_PARALLEL");
        if !matches!(parallel.as_str(), "" | "0" | "1") {
            parts.extend(["--tensor-parallel-size".to_string(), parallel]);
        }
        Self::flags_of_recipe(config, &mut parts)?;
        // A model that ships its own Python code is refused by vLLM without this flag. Off unless the operator said so: it runs the model authors' code on the machine.
        if Flag::yes(config.get("TRUST_REMOTE_CODE")) {
            parts.push("--trust-remote-code".to_string());
        }
        Ok(parts.join(" "))
    }

    fn prepare(&self, merged: &mut Config, _defaults: &RunnerDefaults) -> Result<String, AppError> {
        if !Coerce::truthy(merged.get("VLLM_MODEL")) {
            return Err(AppError::new("VLLM_MODEL is required for a vLLM cell"));
        }
        self.command(merged)
    }

    fn preflight_start(&self, config: &Config, _model: &str) -> Result<(), AppError> {
        if ConfigField::word(config, "VLLM_MODEL").is_empty() {
            return Err(AppError::new("vLLM cell has no model — configure it first"));
        }
        Ok(())
    }
}
