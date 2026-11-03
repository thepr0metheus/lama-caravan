//! Strata: Qwen3.8-Flash-Next (177B, 24 576 experts, 10 per token) on one 32 GB card: its experts compressed to about 2 bits, the ones a token needs streamed to the card. `llama.cpp` does not know the model's architecture, so a file of it is this runner's kind. The model is two things from the library: the GGUF's first part and the MTP draft layer. What Strata makes from them, the launcher writes into the cell's scratch folder at every start.

use super::{Config, PinnedCard, Runner, RunnerDefaults, RunnerRow, TalkSpec};
use regex::{Regex, RegexBuilder};
use rules::{AppError, AskedWindow, ConfigField, PyRepr, ShellWord};
use serde_json::{Value, json};
use std::collections::BTreeMap;
use std::path::Path;

/// The runner.
pub struct StrataRunner {
    native_pack: Regex,
    pack_quant: Regex,
    budget_pack: Regex,
    split_or_gguf: Regex,
}

impl StrataRunner {
    const ROW: RunnerRow = RunnerRow {
        id: "strata",
        icon: "\u{1faa8}",
        label_key: "runnerStrata",
        benefits_key: "runnerStrataBenefits",
        minus_key: "runnerStrataMinus",
        artifacts: &["strata-gguf"],
        needs_key: "runnerNeedsStrataGguf",
        gpu_only: true,
        one_card: true,
        formats: &["gguf"],
        gguf_archs: &["qwen4exp"],
        health: "/health",
        api: "openai",
        talk: TalkSpec { modes: &["text-chat"], ..TalkSpec::NONE },
        model_field: Some("MODEL_FILE"),
        model_files: &["MODEL_FILE", "SPEC_DRAFT_MODEL_FILE"],
        shared_picker: "source",
        token_context: true,
        context_field: "STRATA_CONTEXT",
        default_health_path: "/health",
        needs_models_dir: true,
        min_scout: Some((2, 31, 0)),
        work_folder: true,
        ..RunnerRow::BASE
    };
    /// Strata's own answers (setup.py, v0.2.9).
    const KV_TYPES: [&'static str; 3] = ["int8", "q4_0", "k8v4"];
    const DRAFT_VOCABS: [&'static str; 4] = ["cyrillic", "cjk", "en", "fr"];
    /// The free VRAM below which Strata does not start: its smallest card is 6 GB. Asked before the start, since the start downloads the model first: 68 GB, then a refusal.
    const MIN_FREE_MIB: i64 = 6144;
    const RESERVE_FIELD: &'static str = "STRATA_VRAM_RESERVE_MIB";
    const ROOT: &'static str = super::MODELS_ROOT;
    /// What Strata's process and its tables take in memory over its weights, MiB.
    const RAM_OVERHEAD_MIB: i64 = 1024;
    /// Strata's own table of its packs: the GiB of experts that stay in RAM, by the quantization the pack's file name carries. A pack's first part says the same only where the file split puts every expert in it: a start that promised the first part's 42.8 GiB of Swift's IQ3_S loaded an engine that wanted 50, and it was killed for memory pressure four times (2026-10-18).
    const ARENA_GIB: [(&'static str, f64); 5] =
        [("Q2_0", 34.0), ("IQ2_XS", 35.5), ("IQ3_XXS", 42.9), ("IQ3_S", 50.3), ("IQ1_M", 23.4)];
    /// A budget pack keeps only a budget of its experts in RAM: Strata's table says such a pack needs 48 GB.
    const BUDGET_RAM_MIB: i64 = 48 * 1024;

    /// The runner. The patterns are this program's own text.
    pub fn new() -> Result<Self, regex::Error> {
        let pattern = |text: &str| RegexBuilder::new(text).case_insensitive(true).build();
        Ok(Self {
            // An IQ pack: its engine does not start one without the draft layer, and a Coder's IQ1_M met that after 54 GiB were copied (2026-10-17).
            native_pack: pattern(r"-IQ\d[A-Za-z0-9_]*(?:-\d{5}-of-\d{5})?\.gguf$")?,
            pack_quant: pattern(r"-(Q2_0|IQ\d_[A-Z]+)(?:-\d{5}-of-\d{5})?\.gguf$")?,
            budget_pack: pattern(r"-UD-[A-Za-z0-9_]+-\d{5}-of-\d{5}\.gguf$")?,
            split_or_gguf: pattern(r"-\d{5}-of-\d{5}\.gguf$|\.gguf$")?,
        })
    }

    /// The window asked for: the field's number, and for a field left empty the window the model was trained for. Anything that is not a number is refused, not replaced: a cell started with another window than the one its config shows is the wrong cell.
    pub fn context(&self, config: &Config, trained: Option<i64>) -> Result<Option<i64>, AppError> {
        let field = Self::ROW.context_field;
        let raw = ConfigField::word(config, field);
        let window = AskedWindow::of(&raw, trained);
        if window.is_none() && !AskedWindow::empty(&raw) {
            return Err(AppError::new(format!("{field} must be a number of tokens, not {}", PyRepr::of(&raw))));
        }
        Ok(window)
    }

    /// A field with a closed set of values: empty is the first, anything outside the set refused.
    fn choice(config: &Config, field: &str, allowed: &[&str]) -> Result<String, AppError> {
        let raw = ConfigField::word(config, field).to_lowercase();
        if let (true, Some(first)) = (raw.is_empty(), allowed.first()) {
            return Ok((*first).to_string());
        }
        if !allowed.contains(&raw.as_str()) {
            return Err(AppError::new(format!("{field} must be one of {}, not {}", allowed.join(", "), PyRepr::of(&raw))));
        }
        Ok(raw)
    }

    /// MiB of VRAM left to other cells; 0 when the field is empty.
    fn reserve(config: &Config) -> Result<i64, AppError> {
        let raw = ConfigField::word(config, Self::RESERVE_FIELD);
        if raw.is_empty() {
            return Ok(0);
        }
        raw.parse()
            .ok()
            .filter(|_| raw.chars().all(|letter| letter.is_ascii_digit()))
            .ok_or_else(|| AppError::new(format!("{} must be a number of MiB, not {}", Self::RESERVE_FIELD, PyRepr::of(&raw))))
    }

    fn path(rel: &str) -> String {
        if rel.starts_with('/') || rel.starts_with('$') {
            return ShellWord::quote(rel);
        }
        format!("{}{}", Self::ROOT, ShellWord::quote(rel))
    }

    fn base_name(config: &Config) -> String {
        let model = ConfigField::word(config, "MODEL_FILE");
        Path::new(&model).file_name().map_or_else(String::new, |name| name.to_string_lossy().into_owned())
    }

    /// The MiB of experts Strata's table says this pack keeps in RAM; 0 for a name the table does not know.
    fn arena_mib(&self, name: &str) -> i64 {
        let found = self.pack_quant.captures(name).and_then(|found| found.get(1)).map(|word| word.as_str().to_uppercase());
        let gib = found.and_then(|quant| Self::ARENA_GIB.iter().find(|(said, _)| *said == quant).map(|(_, gib)| *gib));
        // absent-ok: 0 says the table does not know it, as the caller reads it.
        gib.map_or(0, |gib| (gib * 1024.0).round_ties_even() as i64)
    }

    /// The `run_strata.sh` line, with the window the model was trained for, which an empty context field asks for.
    pub fn command_with(&self, config: &Config, trained: Option<i64>) -> Result<String, AppError> {
        let model = ConfigField::word(config, "MODEL_FILE");
        if model.is_empty() {
            return Err(AppError::new("MODEL_FILE is required for a Strata cell"));
        }
        let mut parts = vec![format!("bash $HOME/run_strata.sh \"$PORT\" {}", Self::path(&model))];
        let draft = ConfigField::word(config, "SPEC_DRAFT_MODEL_FILE");
        if !draft.is_empty() {
            parts.extend(["--mtp".to_string(), Self::path(&draft)]);
        }
        if let Some(window) = self.context(config, trained)? {
            parts.extend(["--context".to_string(), window.to_string()]);
        }
        parts.extend([
            "--kv".to_string(),
            Self::choice(config, "STRATA_KV", &Self::KV_TYPES)?,
            "--draft-vocab".to_string(),
            Self::choice(config, "STRATA_DRAFT_VOCAB", &Self::DRAFT_VOCABS)?,
        ]);
        let reserve = Self::reserve(config)?;
        if reserve != 0 {
            parts.extend(["--vram-reserve-mib".to_string(), reserve.to_string()]);
        }
        let said = ConfigField::word(config, "MODEL_NAME");
        let name = if said.is_empty() { ConfigField::word(config, "ALIAS") } else { said };
        if !name.is_empty() {
            parts.extend(["--name".to_string(), ShellWord::quote(&name)]);
        }
        Ok(parts.join(" "))
    }
}

impl Runner for StrataRunner {
    fn row(&self) -> &RunnerRow {
        &Self::ROW
    }

    fn artifact_label(&self, config: &Config, _quant_words: &[&str]) -> String {
        let name = Self::base_name(config);
        let label = self.split_or_gguf.replace(&name, "").into_owned();
        if label.is_empty() { "Strata".to_string() } else { label }
    }

    fn command(&self, config: &Config) -> Result<String, AppError> {
        self.command_with(config, None)
    }

    fn prepare(&self, merged: &mut Config, defaults: &RunnerDefaults) -> Result<String, AppError> {
        if !rules::Coerce::truthy(merged.get("LLAMA_MODELS_DIR")) {
            merged.insert("LLAMA_MODELS_DIR".to_string(), json!(defaults.models_dir));
        }
        self.command_with(merged, None)
    }

    fn preflight_start(&self, config: &Config, model: &str) -> Result<(), AppError> {
        let pack = if model.is_empty() { self.model_ref(config) } else { model.to_string() };
        if pack.is_empty() {
            return Err(AppError::new("Strata cell has no model — configure it first"));
        }
        if self.native_pack.is_match(&pack) && ConfigField::word(config, "SPEC_DRAFT_MODEL_FILE").is_empty() {
            let name = Path::new(&pack).file_name().map_or_else(String::new, |name| name.to_string_lossy().into_owned());
            return Err(AppError::new(format!(
                "{name} is an IQ pack: Strata does not start it without a draft layer, and this cell names none. Open the cell's settings and pick the model again: the form fills in the draft layer (mtp-q2_0.gguf) from the library. If the library holds none, it has to be added first"
            )));
        }
        Ok(())
    }

    /// What a start needs free on its card: its smallest card, plus the VRAM the cell is told to leave to others.
    fn vram_reservation(&self, config: &Config, gpus: &[Value]) -> Option<Value> {
        let device = PinnedCard::of(config, gpus)?;
        // The start itself refuses a reserve of no number, with the field's name.
        let extra = Self::reserve(config).ok()?;
        let more = if extra == 0 { String::new() } else { format!(", plus {extra} MiB left to others") };
        Some(json!({
            "device": device,
            "reserveMiB": Self::MIN_FREE_MIB + extra,
            "who": "Strata",
            "why": format!("its smallest card is 6 GB{more}"),
            "lower": Self::RESERVE_FIELD,
        }))
    }

    fn keeps_ram(&self) -> bool {
        true
    }

    /// The weights of the pack stay in RAM, whole: the larger of the first part's size and what Strata's own table says the pack's experts are, plus the overhead. `None` when neither is known. A budget pack keeps only a budget of its experts in RAM.
    fn ram_reservation(&self, config: &Config, sizes: &BTreeMap<String, i64>) -> Option<Value> {
        let name = Self::base_name(config);
        if self.budget_pack.is_match(&name) {
            return Some(json!({
                "reserveMiB": Self::BUDGET_RAM_MIB,
                "who": "Strata",
                "why": format!("a budget of its experts stays in memory and the rest is read from the disk: Strata asks {} GiB of RAM for this pack", Self::BUDGET_RAM_MIB / 1024),
                "lower": "nothing — stop another cell",
            }));
        }
        // absent-ok: a first part of no said size leaves the table's figure to speak.
        let size = sizes.get("MODEL_FILE").copied().unwrap_or(0);
        let first = if size > 0 { (size + (1 << 20) - 1) / (1 << 20) } else { 0 };
        let arena = self.arena_mib(&name);
        if first == 0 && arena == 0 {
            return None;
        }
        let why = if first >= arena {
            format!("its weights stay in memory: {:.1} GiB", size as f64 / (1u64 << 30) as f64)
        } else {
            format!("its experts stay in memory: {:.1} GiB (Strata's table for this pack)", arena as f64 / 1024.0)
        };
        Some(
            json!({"reserveMiB": first.max(arena) + Self::RAM_OVERHEAD_MIB, "who": "Strata", "why": why, "lower": "nothing — stop another cell"}),
        )
    }

    /// Strata sizes its expert cache to the card's free VRAM: a start takes what is free on its card, less the reserve.
    fn vram_plan(&self) -> Value {
        json!({"takesFree": true, "floorMiB": Self::MIN_FREE_MIB, "reserveField": Self::RESERVE_FIELD})
    }
}
