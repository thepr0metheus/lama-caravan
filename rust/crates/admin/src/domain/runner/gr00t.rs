//! NVIDIA GR00T N1.7: a robot policy's cell.

use super::{Config, PinnedCard, Runner, RunnerRow};
use rules::{AppError, Coerce, ConfigField, PyRepr, ShellWord};
use serde_json::{Value, json};

/// A folder of the library.
struct ModelFolder;

impl ModelFolder {
    const ROOT: &'static str = super::MODELS_ROOT;

    /// Quoted for a shell, against the root when it is relative.
    fn path(rel: &str) -> String {
        let rel = Coerce::strip(rel).trim_end_matches('/');
        if rel.starts_with('/') || rel.starts_with('$') {
            return ShellWord::quote(rel);
        }
        format!("{}{}", Self::ROOT, ShellWord::quote(rel))
    }
}

/// NVIDIA GR00T N1.7: a robot policy. Camera frames, the robot's state and an instruction in, a chunk of actions out. Its model is two FOLDERS of the library: the checkpoint and the backbone that checkpoint names, a gated repository the cell never asks the hub for.
pub struct Gr00tRunner;

impl Gr00tRunner {
    const ROW: RunnerRow = RunnerRow {
        id: "gr00t",
        icon: "\u{1f9be}",
        label_key: "runnerGr00t",
        benefits_key: "runnerGr00tBenefits",
        minus_key: "runnerGr00tMinus",
        artifacts: &["gr00t-st"],
        needs_key: "runnerNeedsGr00tSt",
        gpu_only: true,
        one_card: true,
        st_archs: &["Gr00tN1d7"],
        health: "/health",
        model_field: Some("MODEL_FILE"),
        model_files: &["MODEL_FILE", "GR00T_BACKBONE"],
        shared_picker: "source",
        default_health_path: "/health",
        needs_models_dir: true,
        min_scout: Some((2, 31, 0)),
        ..RunnerRow::BASE
    };
    const DEFAULT_BACKBONE: &'static str = "Cosmos-Reason2-2B/nvidia/BF16";
    const DEFAULT_EMBODIMENT: &'static str = "OXE_DROID_RELATIVE_EEF_RELATIVE_JOINT";
    /// VRAM a start takes: 7030 MiB measured for the policy on an RTX 5090 (2026-10-13), rounded up.
    const MIN_FREE_MIB: i64 = 7680;

    fn embodiment(config: &Config) -> Result<String, AppError> {
        let raw = ConfigField::word(config, "GR00T_EMBODIMENT");
        if raw.is_empty() {
            return Ok(Self::DEFAULT_EMBODIMENT.to_string());
        }
        if !raw.chars().all(|letter| letter.is_ascii_alphanumeric() || letter == '_') {
            return Err(AppError::new(format!(
                "GR00T_EMBODIMENT must be an embodiment tag such as {}, not {}",
                Self::DEFAULT_EMBODIMENT,
                PyRepr::of(&raw)
            )));
        }
        Ok(raw)
    }

    fn denoising_steps(config: &Config) -> Result<i64, AppError> {
        let raw = ConfigField::word(config, "GR00T_DENOISING_STEPS");
        if raw.is_empty() {
            return Ok(0);
        }
        let steps =
            raw.parse::<i64>().ok().filter(|steps| raw.chars().all(|letter| letter.is_ascii_digit()) && (1..=64).contains(steps));
        steps.ok_or_else(|| {
            AppError::new(format!("GR00T_DENOISING_STEPS must be a number from 1 to 64, not {}", PyRepr::of(&raw)))
        })
    }
}

impl Runner for Gr00tRunner {
    fn row(&self) -> &RunnerRow {
        &Self::ROW
    }

    fn artifact_label(&self, config: &Config, _quant_words: &[&str]) -> String {
        let model = ConfigField::word(config, "MODEL_FILE");
        model.split('/').find(|part| !part.is_empty()).unwrap_or("GR00T").to_string()
    }

    fn command(&self, config: &Config) -> Result<String, AppError> {
        let model = ConfigField::word(config, "MODEL_FILE");
        if model.is_empty() {
            return Err(AppError::new("MODEL_FILE is required for a GR00T cell: the checkpoint's folder"));
        }
        let said = ConfigField::word(config, "GR00T_BACKBONE");
        let backbone = if said.is_empty() { Self::DEFAULT_BACKBONE.to_string() } else { said };
        let mut parts = vec![
            format!("bash $HOME/run_gr00t.sh \"$PORT\" {}", ModelFolder::path(&model)),
            "--backbone".to_string(),
            ModelFolder::path(&backbone),
            "--embodiment".to_string(),
            Self::embodiment(config)?,
        ];
        let steps = Self::denoising_steps(config)?;
        if steps != 0 {
            parts.extend(["--denoising-steps".to_string(), steps.to_string()]);
        }
        let said = ConfigField::word(config, "MODEL_NAME");
        let name = if said.is_empty() { ConfigField::word(config, "ALIAS") } else { said };
        if !name.is_empty() {
            parts.extend(["--name".to_string(), ShellWord::quote(&name)]);
        }
        Ok(parts.join(" "))
    }

    /// The checkpoint and the backbone, the latter by default when its field is empty: the scout brings the folder the command names, not the field's emptiness.
    fn model_file_values(&self, config: &Config) -> Vec<(String, String)> {
        let mut filled = config.clone();
        if ConfigField::word(config, "GR00T_BACKBONE").is_empty() {
            filled.insert("GR00T_BACKBONE".to_string(), json!(Self::DEFAULT_BACKBONE));
        }
        Self::ROW
            .model_files
            .iter()
            .map(|field| ((*field).to_string(), ConfigField::word(&filled, field)))
            .filter(|(_, path)| !path.is_empty())
            .collect()
    }

    fn preflight_start(&self, config: &Config, model: &str) -> Result<(), AppError> {
        if model.is_empty() && self.model_ref(config).is_empty() {
            return Err(AppError::new("GR00T cell has no checkpoint — configure it first"));
        }
        Ok(())
    }

    fn vram_reservation(&self, config: &Config, gpus: &[Value]) -> Option<Value> {
        let device = PinnedCard::of(config, gpus)?;
        Some(
            json!({"device": device, "reserveMiB": Self::MIN_FREE_MIB, "who": "GR00T", "why": "the policy took 7.0 GB on an RTX 5090", "lower": ""}),
        )
    }

    fn vram_plan(&self) -> Value {
        json!({"fixedMiB": Self::MIN_FREE_MIB})
    }
}
