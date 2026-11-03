//! The runners of a server of the caravan's own over a model it does not build a command from fields for: Whisper, Moonshine, transcribe.cpp, SeamlessM4T, NLLB-200.

use super::{Config, Runner, RunnerDefaults, RunnerRow, TalkSpec};
use rules::{AppError, ConfigField, ShellWord};
use std::path::Path;

const ROOT: &str = super::MODELS_ROOT;
const TRANSCRIPTION: TalkSpec = TalkSpec { modes: &["transcription"], ..TalkSpec::NONE };

/// A path of a model under the shared root.
struct ModelPath;

impl ModelPath {
    /// Quoted for a shell, against the root when it is relative: the transcribe and seamless form.
    fn plain(model: &str) -> String {
        if model.starts_with('/') || model.starts_with('$') { format!("\"{model}\"") } else { format!("{ROOT}{model}") }
    }
}

/// faster-whisper speech-to-text. The model is a SIZE name: faster-whisper downloads it itself; language is a per-request field of the API, not a launch arg.
pub struct WhisperRunner;

impl WhisperRunner {
    const ROW: RunnerRow = RunnerRow {
        id: "whisper",
        icon: "\u{1f399}\u{fe0f}",
        label_key: "runnerWhisper",
        benefits_key: "runnerWhisperBenefits",
        minus_key: "runnerWhisperMinus",
        artifacts: &["whisper-size"],
        needs_key: "runnerNeedsWhisperSize",
        health: "/health",
        model_field: Some("WHISPER_MODEL"),
        shared_picker: "carrier",
        default_health_path: "/health",
        talk: TRANSCRIPTION,
        needs_models_dir: true,
        one_card: true,
        ..RunnerRow::BASE
    };
    const SIZES: [&'static str; 7] = ["tiny", "base", "small", "medium", "large-v3", "large-v3-turbo", "distil-large-v3"];
}

impl Runner for WhisperRunner {
    fn row(&self) -> &RunnerRow {
        &Self::ROW
    }

    fn artifact_label(&self, config: &Config, _quant_words: &[&str]) -> String {
        let size = ConfigField::word(config, "WHISPER_MODEL");
        if size.is_empty() { "whisper".to_string() } else { size }
    }

    /// The `run_whisper.sh` line. Models live under the SAME root as everything else.
    fn command(&self, config: &Config) -> Result<String, AppError> {
        let said = ConfigField::word(config, "WHISPER_MODEL");
        let size = if Self::SIZES.contains(&said.as_str()) { said.as_str() } else { "large-v3" };
        Ok(format!(
            "env HUGGINGFACE_HUB_CACHE=\"${{LLAMA_MODELS_DIR:-$HOME/llama-model-cache}}/whisper\" bash $HOME/run_whisper.sh \"$PORT\" {size}"
        ))
    }
}

/// Moonshine v2 speech-to-text, CPU-only by design. The "model" is a language code; the package downloads weights itself. No Russian: whisper stays the Russian recognizer.
pub struct MoonshineRunner;

impl MoonshineRunner {
    const ROW: RunnerRow = RunnerRow {
        id: "moonshine",
        icon: "🌙",
        label_key: "runnerMoonshine",
        benefits_key: "runnerMoonshineBenefits",
        minus_key: "runnerMoonshineMinus",
        artifacts: &["moonshine-lang"],
        needs_key: "runnerNeedsMoonshineLang",
        health: "/health",
        model_field: Some("MOONSHINE_MODEL"),
        shared_picker: "carrier",
        default_health_path: "/health",
        talk: TRANSCRIPTION,
        ..RunnerRow::BASE
    };
    const LANGS: [&'static str; 8] = ["en", "es", "zh", "ja", "ko", "vi", "uk", "ar"];
}

impl Runner for MoonshineRunner {
    fn row(&self) -> &RunnerRow {
        &Self::ROW
    }

    fn artifact_label(&self, config: &Config, _quant_words: &[&str]) -> String {
        let said = ConfigField::word(config, "MOONSHINE_MODEL").to_lowercase();
        format!("moonshine {}", if said.is_empty() { "en" } else { said.as_str() })
    }

    /// SYNTHESIZED from the runner's own field: requiring COMMAND here rejected a perfectly valid moonshine cell.
    fn command(&self, config: &Config) -> Result<String, AppError> {
        let said = ConfigField::word(config, "MOONSHINE_MODEL").to_lowercase();
        let lang = if Self::LANGS.contains(&said.as_str()) { said.as_str() } else { "en" };
        Ok(format!("bash $HOME/run_moonshine.sh \"$PORT\" {lang}"))
    }
}

/// transcribe.cpp speech-to-text on the ggml runtime: the `llama.cpp` of ASR. Alone among the speech runners it takes a GGUF PATH, because one build runs sixteen model families picked by the file. It is why RUSSIAN finally has a good cell.
pub struct TranscribeRunner;

impl TranscribeRunner {
    const ROW: RunnerRow = RunnerRow {
        id: "transcribe",
        icon: "\u{1f4dd}",
        label_key: "runnerTranscribe",
        benefits_key: "runnerTranscribeBenefits",
        minus_key: "runnerTranscribeMinus",
        artifacts: &["asr-gguf"],
        needs_key: "runnerNeedsAsrGguf",
        formats: &["gguf"],
        health: "/health",
        model_field: Some("MODEL_FILE"),
        model_files: &["MODEL_FILE"],
        shared_picker: "source",
        default_health_path: "/health",
        talk: TRANSCRIPTION,
        needs_models_dir: true,
        ..RunnerRow::BASE
    };
}

impl Runner for TranscribeRunner {
    fn row(&self) -> &RunnerRow {
        &Self::ROW
    }

    fn artifact_label(&self, config: &Config, _quant_words: &[&str]) -> String {
        let model = ConfigField::word(config, "MODEL_FILE");
        let name = Path::new(&model).file_name().map_or_else(String::new, |name| name.to_string_lossy().into_owned());
        let label = name.strip_suffix(".gguf").unwrap_or(&name);
        if label.is_empty() { "transcribe".to_string() } else { label.to_string() }
    }

    fn command(&self, config: &Config) -> Result<String, AppError> {
        let model = ConfigField::word(config, "MODEL_FILE");
        if model.is_empty() {
            return Err(AppError::new("MODEL_FILE is required for a transcribe cell"));
        }
        Ok(format!("bash $HOME/run_transcribe.sh \"$PORT\" {}", ModelPath::plain(&model)))
    }

    /// It has NO default to fall back on: an unconfigured cell has to be caught here rather than crashing inside the builder.
    fn preflight_start(&self, _config: &Config, model: &str) -> Result<(), AppError> {
        if model.is_empty() {
            return Err(AppError::new("transcribe cell has no model — configure it first"));
        }
        Ok(())
    }
}

/// SeamlessM4T v2: speech in one language to TEXT in another, one model. It takes a safetensors DIRECTORY, hence its own artifact kind. Weights are CC-BY-NC-4.0: non-commercial.
pub struct SeamlessRunner;

impl SeamlessRunner {
    const ROW: RunnerRow = RunnerRow {
        id: "seamless",
        icon: "\u{1f310}",
        label_key: "runnerSeamless",
        benefits_key: "runnerSeamlessBenefits",
        minus_key: "runnerSeamlessMinus",
        artifacts: &["seamless-st"],
        needs_key: "runnerNeedsSeamlessSt",
        st_archs: &["seamless_m4t", "seamless_m4t_v2"],
        health: "/health",
        model_field: Some("MODEL_FILE"),
        model_files: &["MODEL_FILE"],
        shared_picker: "source",
        default_health_path: "/health",
        talk: TalkSpec { modes: &["speech-translation"], ..TalkSpec::NONE },
        needs_models_dir: true,
        one_card: true,
        ..RunnerRow::BASE
    };
}

impl Runner for SeamlessRunner {
    fn row(&self) -> &RunnerRow {
        &Self::ROW
    }

    fn command(&self, config: &Config) -> Result<String, AppError> {
        let model = ConfigField::word(config, "MODEL_FILE");
        if model.is_empty() {
            return Err(AppError::new("MODEL_FILE is required for a seamless cell"));
        }
        let said = ConfigField::word(config, "SEAMLESS_TGT_LANG").to_lowercase();
        let target = if said.is_empty() { "rus" } else { said.as_str() };
        Ok(format!("bash $HOME/run_seamless.sh \"$PORT\" {} {target}", ModelPath::plain(&model)))
    }

    fn preflight_start(&self, _config: &Config, model: &str) -> Result<(), AppError> {
        if model.is_empty() {
            return Err(AppError::new("seamless cell has no model — configure it first"));
        }
        Ok(())
    }
}

/// NLLB-200 text translation. A dedicated MT model rather than an LLM because they fail differently: an LLM reads the text it translates as possible instructions. Its model is an HF REPO ID, like vLLM's: it downloads itself.
pub struct TranslateRunner;

impl TranslateRunner {
    const ROW: RunnerRow = RunnerRow {
        id: "translate",
        icon: "\u{1f504}",
        label_key: "runnerTranslate",
        benefits_key: "runnerTranslateBenefits",
        minus_key: "runnerTranslateMinus",
        artifacts: &["nllb-repo"],
        needs_key: "runnerNeedsNllbRepo",
        health: "/health",
        model_field: Some("TRANSLATE_MODEL"),
        shared_picker: "carrier",
        default_health_path: "/health",
        ..RunnerRow::BASE
    };
    const DEFAULT_MODEL: &'static str = "facebook/nllb-200-distilled-600M";

    /// The checkpoint the cell runs: an HF repo id, or a local directory.
    pub fn repo(config: &Config) -> String {
        let said = ConfigField::word(config, "TRANSLATE_MODEL");
        if said.is_empty() { Self::DEFAULT_MODEL.to_string() } else { said }
    }

    /// Where the models tree keeps the cell's checkpoint, `translate/models--<author>--<name>`, or "" for a checkpoint named by a directory of its own.
    pub fn cache_folder(config: &Config) -> String {
        let repo = Self::repo(config);
        let (author, name) = repo.split_once('/').unwrap_or((&repo, ""));
        if author.is_empty() || name.is_empty() || name.contains('/') || repo.starts_with(['.', '/', '~']) {
            return String::new();
        }
        format!("translate/models--{author}--{name}")
    }
}

impl Runner for TranslateRunner {
    fn row(&self) -> &RunnerRow {
        &Self::ROW
    }

    fn command(&self, config: &Config) -> Result<String, AppError> {
        let model = Self::repo(config);
        let word = |field: &str, otherwise: &str| {
            let said = ConfigField::word(config, field);
            if said.is_empty() { otherwise.to_string() } else { said }
        };
        let (source, target) = (word("TRANSLATE_SRC_LANG", "eng_Latn"), word("TRANSLATE_TGT_LANG", "rus_Cyrl"));
        // Under the SAME root as every other model: left to itself the library downloads into ~/.cache/huggingface, where 4.7 GB is invisible to the models page.
        Ok(format!(
            "env HUGGINGFACE_HUB_CACHE=\"${{LLAMA_MODELS_DIR:-$HOME/llama-model-cache}}/translate\" bash $HOME/run_translate.sh \"$PORT\" {} {} {}",
            ShellWord::quote(&model),
            ShellWord::quote(&source),
            ShellWord::quote(&target)
        ))
    }

    /// No `MODEL_FILE` and nothing to resolve: its model is a repo id the launcher hands straight to transformers.
    fn prepare(&self, merged: &mut Config, _defaults: &RunnerDefaults) -> Result<String, AppError> {
        self.command(merged)
    }
}

/// These runners, in the registry's order.
pub struct SpeechRunners;

impl SpeechRunners {
    /// Each one.
    pub fn all() -> Vec<Box<dyn Runner>> {
        vec![
            Box::new(WhisperRunner),
            Box::new(MoonshineRunner),
            Box::new(TranscribeRunner),
            Box::new(SeamlessRunner),
            Box::new(TranslateRunner),
        ]
    }
}
