//! The voice-clone cell, a cell of a typed command, and a cell whose model runs inside an engine next to it.

use super::launcher::LauncherRunners;
use super::{Config, Runner, RunnerDefaults, RunnerRow, TalkSpec};
use rules::{AppError, Coerce, ConfigField, PyRepr, ShellWord};
use serde_json::json;

/// XTTS-v2, CosyVoice2 or F5-TTS: a text read out in a voice taken from a few seconds of a sample. The engine is the cell's choice; its packages and its weights install themselves at the cell's first start, so the model picker has nothing to offer it.
///
/// No VRAM is reserved before the start, and the plan names no figure, though the engines' footprints are measured: the cell picks its device itself as it loads, by its engine's own need
/// (`cells/tts_server.py`, `VoiceEngine.need_gb`), and on a card short of it runs on the CPU and says why in its health (`deviceReason`). A reservation would have the scout refuse the start
/// the CPU can still serve, and a plan is one figure a runner where the three engines need three: the needs live in the cell, in one place.
pub struct VoiceCloneRunner;

impl VoiceCloneRunner {
    const ROW: RunnerRow = RunnerRow {
        id: "voice-clone",
        icon: "\u{1f99c}",
        label_key: "runnerVoiceClone",
        benefits_key: "runnerVoiceCloneBenefits",
        minus_key: "runnerVoiceCloneMinus",
        health: "/health",
        default_health_path: "/health",
        model_field: Some("TTS_ENGINE"),
        shared_picker: "ignored",
        one_card: true,
        auto_device: true,
        talk: TalkSpec { modes: &["speech"], voices_path: "/v1/audio/voices", clone: true, ..TalkSpec::NONE },
        ..RunnerRow::BASE
    };
    /// The engines `run_tts.sh` installs, the first the default.
    const ENGINES: [&'static str; 3] = ["xtts", "cosyvoice", "f5"];

    const DEFAULT_ENGINE: &'static str = "xtts";

    /// The engine, in the launcher's case: refused when it is none of `run_tts.sh`'s: the launcher would install nothing and the cell die.
    fn engine(&self, config: &Config) -> Result<String, AppError> {
        let engine = self.model_ref(config).to_lowercase();
        if !Self::ENGINES.contains(&engine.as_str()) {
            return Err(AppError::new(format!(
                "TTS_ENGINE must be one of {}, not {}",
                Self::ENGINES.join(", "),
                PyRepr::of(&engine)
            )));
        }
        Ok(engine)
    }
}

impl Runner for VoiceCloneRunner {
    fn row(&self) -> &RunnerRow {
        &Self::ROW
    }

    fn model_ref(&self, config: &Config) -> String {
        let said = ConfigField::word(config, "TTS_ENGINE");
        if said.is_empty() { Self::DEFAULT_ENGINE.to_string() } else { said }
    }

    fn artifact_label(&self, config: &Config, _quant_words: &[&str]) -> String {
        self.model_ref(config).to_lowercase()
    }

    fn command(&self, config: &Config) -> Result<String, AppError> {
        Ok(format!("bash $HOME/run_tts.sh \"$PORT\" {}", self.engine(config)?))
    }

    /// The block says the engine the cell runs, the default too: the form reads the block back.
    fn prepare(&self, merged: &mut Config, _defaults: &RunnerDefaults) -> Result<String, AppError> {
        let engine = self.engine(merged)?;
        merged.insert("TTS_ENGINE".to_string(), json!(engine));
        self.command(merged)
    }

    fn preflight_start(&self, config: &Config, _model: &str) -> Result<(), AppError> {
        self.engine(config).map(drop)
    }
}

/// An arbitrary command line: nothing about `MODEL_FILE` can rule it out.
pub struct CustomRunner;

impl CustomRunner {
    const ROW: RunnerRow = RunnerRow {
        id: "custom",
        icon: "\u{1f6e0}\u{fe0f}",
        label_key: "runnerCustom",
        benefits_key: "runnerCustomBenefits",
        minus_key: "runnerCustomMinus",
        free_form_command: true,
        auto_device: true,
        ..RunnerRow::BASE
    };

    /// `^\s*exec\s+`, taken off.
    fn without_exec(line: &str) -> &str {
        let line = line.trim_start();
        match line.strip_prefix("exec") {
            Some(rest) if rest.starts_with(char::is_whitespace) => rest.trim_start(),
            _ => line,
        }
    }

    /// `^(?:exec\s+)?(?:env\s+\S+=\S*\s+)*`, taken off.
    fn without_prefix(command: &str) -> &str {
        let mut rest = Self::without_exec(command);
        while let Some(after) = rest.strip_prefix("env").filter(|after| after.starts_with(char::is_whitespace)) {
            let after = after.trim_start();
            let Some((word, tail)) = after.split_once(char::is_whitespace) else {
                break;
            };
            if !word.contains('=') || word.starts_with('=') {
                break;
            }
            rest = tail.trim_start();
        }
        rest
    }
}

impl Runner for CustomRunner {
    fn row(&self) -> &RunnerRow {
        &Self::ROW
    }

    /// A custom cell has only the command, so the boilerplate goes, the interpreter, the home prefix, the `$PORT`, and what identifies it stays: `bash ~/run_tts.sh $PORT cosyvoice` reads as `run_tts.sh cosyvoice`.
    fn artifact_label(&self, config: &Config, _quant_words: &[&str]) -> String {
        let command = ConfigField::word(config, "COMMAND");
        if command.is_empty() {
            return String::new();
        }
        let mut rest = Self::without_prefix(&command);
        for shell in ["bash", "sh", "python3", "python"] {
            if let Some(after) = rest.strip_prefix(shell).filter(|after| after.starts_with(char::is_whitespace)) {
                rest = after.trim_start();
                break;
            }
        }
        let line = rest.replace("$HOME/", "").replace("~/", "");
        let mut parts: Vec<&str> =
            line.split_whitespace().filter(|part| !matches!(*part, "\"$PORT\"" | "$PORT" | "'$PORT'")).collect();
        if let Some(first) = parts.first_mut() {
            *first = first.rsplit('/').next().unwrap_or(first);
        }
        Coerce::first_letters(&parts.join(" "), 40).to_string()
    }

    fn preflight_start(&self, config: &Config, _model: &str) -> Result<(), AppError> {
        if ConfigField::word(config, "COMMAND").is_empty() {
            return Err(AppError::new("command cell has no command — configure it first"));
        }
        Ok(())
    }

    /// Forgiving: a leading `exec ` goes: the launch adds its own. The config block and the exec line stay in sync.
    fn prepare(&self, merged: &mut Config, _defaults: &RunnerDefaults) -> Result<String, AppError> {
        let said = if Coerce::truthy(merged.get("COMMAND")) { Coerce::text(merged.get("COMMAND")) } else { String::new() };
        let command = Coerce::strip(Self::without_exec(&said)).to_string();
        if command.is_empty() {
            return Err(AppError::new("COMMAND is required for a command cell"));
        }
        merged.insert("COMMAND".to_string(), json!(command));
        Ok(command)
    }
}

/// A cell whose model runs inside an engine next to it (Ollama, LM Studio). The engine listens on 127.0.0.1 only; the cell's own port is the way in, which loads the model when the cell starts and unloads it when it stops. The config names the model as the engine does and the engine's loopback port, both written when the cell is reserved in that engine.
pub struct EngineCell {
    row: RunnerRow,
    default_port: i64,
}

impl EngineCell {
    const FAMILY: RunnerRow = RunnerRow {
        artifacts: &["engine-model"],
        health: "/health",
        default_health_path: "/health",
        model_field: Some("ENGINE_MODEL"),
        shared_picker: "ignored",
        editor_tab: false,
        engine_cell: true,
        talk: TalkSpec { modes: &["text-chat"], ..TalkSpec::NONE },
        ..RunnerRow::BASE
    };

    fn engine_port(&self, config: &Config) -> Result<i64, AppError> {
        let said = ConfigField::word(config, "ENGINE_PORT");
        let port = if said.is_empty() {
            self.default_port
        } else {
            said.parse().map_err(|_| {
                AppError::new(format!("ENGINE_PORT is not a port: {}", PyRepr::of(&Coerce::text(config.get("ENGINE_PORT")))))
            })?
        };
        if !(1..65536).contains(&port) {
            return Err(AppError::new(format!("ENGINE_PORT is not a port: {port}")));
        }
        Ok(port)
    }
}

impl Runner for EngineCell {
    fn row(&self) -> &RunnerRow {
        &self.row
    }

    /// The `run_engine.sh` line: a scout brings a cell's files into `$HOME` by the launcher its command names, and a bare `python3 …server.py` names none.
    fn command(&self, config: &Config) -> Result<String, AppError> {
        let model = self.model_ref(config);
        if model.is_empty() {
            return Err(AppError::new(format!("ENGINE_MODEL is required for a {} cell", self.row.id)));
        }
        Ok(format!(
            "bash $HOME/run_engine.sh \"$PORT\" {} {} {}",
            self.row.id,
            self.engine_port(config)?,
            ShellWord::quote(&model)
        ))
    }

    fn prepare(&self, merged: &mut Config, _defaults: &RunnerDefaults) -> Result<String, AppError> {
        self.command(merged)
    }

    fn preflight_start(&self, config: &Config, _model: &str) -> Result<(), AppError> {
        if self.model_ref(config).is_empty() {
            return Err(AppError::new(format!("{} cell has no model — reserve it with one", self.row.id)));
        }
        Ok(())
    }

    fn artifact_label(&self, config: &Config, _quant_words: &[&str]) -> String {
        self.model_ref(config)
    }
}

/// These, in the registry's order.
pub struct OtherRunners;

impl OtherRunners {
    /// Each one.
    pub fn all() -> Vec<Box<dyn Runner>> {
        vec![
            Box::new(VoiceCloneRunner),
            LauncherRunners::after_voice_clone(),
            Box::new(CustomRunner),
            Box::new(EngineCell {
                row: RunnerRow { id: "ollama", icon: "\u{1f7e0}", label_key: "runnerOllama", ..EngineCell::FAMILY },
                default_port: 11434,
            }),
            Box::new(EngineCell {
                row: RunnerRow { id: "lmstudio", icon: "\u{1f7e3}", label_key: "runnerLmStudio", ..EngineCell::FAMILY },
                default_port: 1234,
            }),
        ]
    }
}
