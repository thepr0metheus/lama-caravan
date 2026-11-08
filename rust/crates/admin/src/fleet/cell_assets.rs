//! The cell servers themselves, the launchers and HTTP servers a command cell runs. The caravan keeps one copy, and each
//! machine fetches it.

use crate::app::App;
use net::Sha256;
use rules::{AppError, Coerce};
use serde_json::{Map, Value, json};
use std::path::PathBuf;

/// The assets of this controller.
pub struct CellAssets<'app> {
    app: &'app App,
}

impl<'app> CellAssets<'app> {
    const ASSETS: [&'static str; 25] = [
        "cell_base.py",
        "moonshine_server.py",
        "run_moonshine.sh",
        "tts_server.py",
        "run_tts.sh",
        "whisper_server.py",
        "run_whisper.sh",
        "transcribe_server.py",
        "run_transcribe.sh",
        "seamless_server.py",
        "run_seamless.sh",
        "translate_server.py",
        "run_translate.sh",
        "engine_cell_server.py",
        "run_engine.sh",
        "strata_launch.py",
        "run_strata.sh",
        "gr00t_server.py",
        "run_gr00t.sh",
        "lfm_audio_server.py",
        "run_lfm_audio.sh",
        "run_personaplex.sh",
        "run_vllm_omni.sh",
        "run_minicpm_omni.sh",
        "run_inferssd.sh",
    ];
    const RUNNERS: [(&'static str, &'static [&'static str]); 18] = [
        ("moonshine", &["run_moonshine.sh", "cell_base.py", "moonshine_server.py"]),
        ("whisper", &["run_whisper.sh", "cell_base.py", "whisper_server.py"]),
        ("custom", &["run_tts.sh", "cell_base.py", "tts_server.py"]),
        ("voice-clone", &["run_tts.sh", "cell_base.py", "tts_server.py"]),
        ("transcribe", &["run_transcribe.sh", "cell_base.py", "transcribe_server.py"]),
        ("seamless", &["run_seamless.sh", "cell_base.py", "seamless_server.py"]),
        ("translate", &["run_translate.sh", "cell_base.py", "translate_server.py"]),
        ("strata", &["run_strata.sh", "strata_launch.py"]),
        ("gr00t", &["run_gr00t.sh", "cell_base.py", "gr00t_server.py"]),
        ("ollama", &["run_engine.sh", "cell_base.py", "engine_cell_server.py"]),
        ("lmstudio", &["run_engine.sh", "cell_base.py", "engine_cell_server.py"]),
        ("lfm-audio", &["run_lfm_audio.sh", "cell_base.py", "lfm_audio_server.py"]),
        ("personaplex", &["run_personaplex.sh"]),
        ("step-audio2", &["run_vllm_omni.sh"]),
        ("qwen3-omni", &["run_vllm_omni.sh"]),
        ("qwen3-tts", &["run_vllm_omni.sh"]),
        ("minicpm-omni", &["run_minicpm_omni.sh"]),
        ("inferssd", &["run_inferssd.sh"]),
    ];

    /// The assets of `app`.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    fn folder(&self) -> PathBuf {
        self.app.paths.project_root.join("cells")
    }

    fn hex(raw: &[u8]) -> String {
        Sha256::of(raw)
    }

    /// `{assets, runners}`: what a scout compares its own copies against.
    pub fn manifest(&self) -> Value {
        let mut assets = Map::new();
        for name in Self::ASSETS {
            if let Ok(raw) = std::fs::read(self.folder().join(name)) {
                assets.insert(
                    name.to_string(),
                    json!({"sha256": Self::hex(&raw), "size": raw.len(), "executable": name.ends_with(".sh")}),
                );
            }
        }
        let runners: Map<String, Value> =
            Self::RUNNERS.iter().map(|(runner, names)| ((*runner).to_string(), json!(names))).collect();
        json!({"assets": assets, "runners": runners})
    }

    /// One asset's bytes.
    pub fn bytes(&self, name: &str) -> Result<Vec<u8>, AppError> {
        if !Self::ASSETS.contains(&name) {
            return Err(AppError::with_status(format!("unknown cell asset: {name}"), 404));
        }
        std::fs::read(self.folder().join(name))
            .map_err(|_| AppError::with_status(format!("cell asset missing on controller: {name}"), 500))
    }

    fn assets_for(runner: &str) -> &'static [&'static str] {
        let word = Coerce::strip(runner).to_lowercase();
        Self::RUNNERS.iter().find(|(id, _)| *id == word).map_or(&[], |(_, names)| names)
    }

    /// The asset group whose launcher a command names; empty when it names none of the caravan's.
    fn group_for_command(command: &str) -> &'static str {
        let launcher =
            command.split(|letter: char| !(letter.is_ascii_alphanumeric() || letter == '_' || letter == '.')).find(|word| {
                word.strip_prefix("run_").and_then(|rest| rest.strip_suffix(".sh")).is_some_and(|middle| !middle.is_empty())
            });
        let Some(launcher) = launcher else {
            return "";
        };
        Self::RUNNERS.iter().find(|(_, names)| names.contains(&launcher)).map_or("", |(group, _)| group)
    }

    /// What a cell of this runner says in `/health` when it runs the version the caravan ships: the first 12 of the server's sha256.
    pub fn server_stamp(&self, runner: &str) -> String {
        let mut paths: Vec<PathBuf> =
            Self::assets_for(runner).iter().filter(|name| name.ends_with(".py")).map(|name| self.folder().join(name)).collect();
        if paths.is_empty() {
            return String::new();
        }
        paths.sort();
        let mut parts = Vec::new();
        for path in &paths {
            match std::fs::read(path) {
                Ok(raw) => parts.push(raw),
                Err(_) => return String::new(),
            }
        }
        let hex = Self::hex(&parts.join(&b'\n'));
        hex.chars().take(12).collect()
    }

    /// What a running cell says it loaded against what the caravan ships: current, stale or unknown.
    pub fn source_state(&self, runner: &str, reported: &str, command: &str) -> &'static str {
        let group = Self::group_for_command(command);
        let want = self.server_stamp(if group.is_empty() { runner } else { group });
        let got = Coerce::strip(reported);
        if want.is_empty() || got.is_empty() {
            return "unknown";
        }
        if got == want { "current" } else { "stale" }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_command_names_its_group_by_its_launcher() {
        assert_eq!(CellAssets::group_for_command("bash ~/run_whisper.sh --x"), "whisper");
        assert_eq!(CellAssets::group_for_command("run_tts.sh"), "custom");
        assert_eq!(CellAssets::group_for_command("python server.py"), "");
        assert_eq!(CellAssets::group_for_command("run_unknown.sh"), "");
    }

    #[test]
    fn a_runner_names_its_assets() {
        assert_eq!(CellAssets::assets_for(" STRATA "), ["run_strata.sh", "strata_launch.py"]);
        assert!(CellAssets::assets_for("llama-server").is_empty());
    }
}
