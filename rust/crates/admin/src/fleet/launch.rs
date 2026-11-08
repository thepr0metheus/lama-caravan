//! The start script of a cell, and the same cell as one line a scout runs.

use crate::app::App;
use crate::config::args::LlamaArgs;
use crate::config::builder::{CellCommand, FoundFiles};
use crate::config::text::ConfigText;
use crate::domain::runner::{Config, RunnerDefaults};
use crate::models::locator::Locations;
use crate::models::store_probe::MARKER_NAME;
use rules::{AppError, Coerce, EnvField, ShellWord};
use serde_json::json;

/// The start script of this controller's cells.
pub struct LaunchScript<'app> {
    app: &'app App,
}

impl<'app> LaunchScript<'app> {
    const COMMAND_BEGIN: &'static str = "# BEGIN LLAMA COMMAND";
    const COMMAND_END: &'static str = "# END LLAMA COMMAND";
    const BLOCK_KEYS: [&'static str; 36] = [
        "RUNNER",
        "CELL_KIND",
        "PORT",
        "HEALTH_PATH",
        "WORKDIR",
        "COMMAND",
        "VLLM_MODEL",
        "MAX_MODEL_LEN",
        "GPU_MEMORY_UTILIZATION",
        "QUANTIZATION",
        "DTYPE",
        "TENSOR_PARALLEL",
        "TRUST_REMOTE_CODE",
        "MAX_NUM_SEQS",
        "KV_CACHE_DTYPE",
        "CPU_OFFLOAD_GB",
        "REASONING_PARSER",
        "WHISPER_MODEL",
        "MOONSHINE_MODEL",
        "SEAMLESS_TGT_LANG",
        "TRANSLATE_MODEL",
        "TRANSLATE_SRC_LANG",
        "TRANSLATE_TGT_LANG",
        "STRATA_CONTEXT",
        "STRATA_KV",
        "STRATA_DRAFT_VOCAB",
        "STRATA_VRAM_RESERVE_MIB",
        "GR00T_BACKBONE",
        "GR00T_EMBODIMENT",
        "GR00T_DENOISING_STEPS",
        "TTS_ENGINE",
        "PAGE_URL",
        "MODEL_FILE",
        "SPEC_DRAFT_MODEL_FILE",
        "LLAMA_MODELS_DIR",
        "ALIAS",
    ];

    /// The script of `app`.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    fn defaults(&self) -> RunnerDefaults {
        RunnerDefaults {
            models_dir: self.app.paths.default_models_dir.to_string_lossy().into_owned(),
            home: self.app.env.home().to_string_lossy().into_owned(),
        }
    }

    fn word(config: &Config, key: &str) -> String {
        Coerce::text(config.get(key))
    }

    fn port_word(merged: &Config) -> Result<String, AppError> {
        let port = Self::word(merged, "PORT");
        if port.is_empty() || !port.chars().all(|digit| digit.is_ascii_digit()) {
            return Err(AppError::new("PORT must be a number"));
        }
        Ok(port)
    }

    /// A configured path as it must appear inside double quotes in a start line.
    pub fn shell_path_value(raw: &str) -> String {
        let value = Coerce::strip(raw);
        let value = if value == "~" {
            "$HOME".to_string()
        } else if let Some(rest) = value.strip_prefix("~/") {
            format!("$HOME/{rest}")
        } else {
            value.to_string()
        };
        value.replace('\\', "\\\\").replace('"', "\\\"")
    }

    /// `export KEY="VALUE"` for each pair: the one way a start line exports anything.
    pub fn export_lines(pairs: &[(String, String)]) -> Vec<String> {
        pairs
            .iter()
            .map(|(key, value)| format!("export {key}=\"{}\"", value.replace('\\', "\\\\").replace('"', "\\\"")))
            .collect()
    }

    /// `KEY="VALUE"` for each pair.
    pub fn env_words(pairs: &[(String, String)]) -> Vec<String> {
        Self::export_lines(pairs).into_iter().map(|line| line.trim_start_matches("export ").to_string()).collect()
    }

    fn env_exports(merged: &Config) -> Vec<String> {
        Self::export_lines(&EnvField::pairs(merged.get("ENV")))
    }

    /// Script lines as the statements of one `;`-joined line.
    fn one_line_statements(lines: &[String]) -> Vec<String> {
        let mut statements: Vec<String> = Vec::new();
        for raw in lines {
            let line = Coerce::strip(raw);
            if line.is_empty() {
                continue;
            }
            let opens = statements.last().is_some_and(|last| {
                let word = last.rsplit([' ', '\t', ';']).next().unwrap_or(last);
                matches!(word, "then" | "do" | "else")
            });
            match statements.last_mut().filter(|_| opens) {
                Some(last) => {
                    last.push(' ');
                    last.push_str(line);
                }
                None => statements.push(line.to_string()),
            }
        }
        statements
    }

    /// A start script for a generic command cell.
    pub fn command_cell_script(&self, config: &Config) -> Result<String, AppError> {
        let mut merged = ConfigText::merged(config);
        let port = Self::port_word(&merged)?;
        let runner = self.app.runners.for_config(&merged);
        let command = runner.prepare(&mut merged, &self.defaults())?;
        let mut block = vec![ConfigText::BEGIN.to_string()];
        for key in Self::BLOCK_KEYS {
            let raw = Self::word(&merged, key);
            if matches!(key, "LLAMA_MODELS_DIR" | "WORKDIR") && !Coerce::strip(&raw).is_empty() {
                block.push(format!("{key}=\"{}\"", Self::shell_path_value(&raw)));
            } else {
                block.push(format!("{key}={}", ConfigText::quote_shell_value(&raw)));
            }
        }
        block.push(ConfigText::END.to_string());
        let mut lines = vec![
            "#!/usr/bin/env bash".to_string(),
            "set -euo pipefail".to_string(),
            String::new(),
            block.join("\n"),
            String::new(),
        ];
        lines.push(format!("export PORT={}", ShellWord::quote(&port)));
        lines.extend(Self::export_lines(&runner.launch_env(&merged)));
        lines.extend(Self::env_exports(&merged));
        let workdir = Self::shell_path_value(&Self::word(&merged, "WORKDIR"));
        if !workdir.is_empty() {
            lines.push(format!("cd \"{workdir}\""));
        }
        let boot = runner.bootstrap_lines();
        if !boot.is_empty() {
            lines.push(String::new());
            lines.extend(boot);
        }
        lines.push(String::new());
        lines.push(format!("{} — generated command cell; edit via the admin UI, not by hand", Self::COMMAND_BEGIN));
        lines.push(format!("exec {command}"));
        lines.push(Self::COMMAND_END.to_string());
        lines.push(String::new());
        Ok(lines.join("\n"))
    }

    /// The same command cell as one `bash -lc` line: how a scout runs it, as a child process. Its port is the one the scout leases at
    /// the start: the line exports the placeholder, and the scout fills it (`LlamaArgs::LEASED_PORT`).
    pub fn command_cell_shell_line(&self, config: &Config) -> Result<String, AppError> {
        let merged = ConfigText::merged(config);
        let runner = self.app.runners.for_config(&merged);
        let command = runner.command(&merged)?;
        if command.is_empty() {
            return Err(AppError::new("command is required for a command cell"));
        }
        let mut parts = vec!["set -euo pipefail".to_string(), format!("export PORT={}", LlamaArgs::LEASED_PORT)];
        let models_dir = Self::shell_path_value(&Self::word(&merged, "LLAMA_MODELS_DIR"));
        if !models_dir.is_empty() {
            parts.push(format!("export LLAMA_MODELS_DIR=\"{models_dir}\""));
        }
        parts.extend(Self::export_lines(&runner.launch_env(&merged)));
        parts.extend(Self::env_exports(&merged));
        let workdir = Self::shell_path_value(&Self::word(&merged, "WORKDIR"));
        if !workdir.is_empty() {
            parts.push(format!("cd \"{workdir}\""));
        }
        parts.extend(Self::one_line_statements(&runner.bootstrap_lines()));
        parts.push(format!("exec {command}"));
        Ok(parts.join("; "))
    }

    /// What the script checks before it starts: a library unmounted is said as that, not as a model gone.
    fn start_guards(found: &FoundFiles) -> Vec<String> {
        let (mut marks, mut files, mut seen) = (Vec::new(), Vec::new(), Vec::<String>::new());
        for (key, what) in [("MODEL_FILE", "Model"), ("MMPROJ_FILE", "MMProj"), ("SPEC_DRAFT_MODEL_FILE", "Spec draft")] {
            let Some(at) = found.get(key) else {
                continue;
            };
            if let Some(store) = at.store.as_ref().filter(|_| at.in_library())
                && !seen.contains(&store.root)
            {
                seen.push(store.root.clone());
                let mark = format!("{}/{MARKER_NAME}", store.root.trim_end_matches('/'));
                let name = if store.name.is_empty() { &store.id } else { &store.name };
                marks.push(format!(
                    "[ -f {} ] || {{ echo \"The library {name} is not mounted at {} — the model stays there\" >&2; exit 1; }}",
                    ShellWord::quote(&mark),
                    store.root
                ));
            }
            files.push(format!(
                "[ -f {} ] || {{ echo \"{what} not found: {}\" >&2; exit 1; }}",
                ShellWord::quote(&at.path),
                at.path
            ));
        }
        marks.extend(files);
        marks
    }

    /// A complete, self-contained start script.
    pub fn render(&self, config: &Config, locations: Option<&Locations>) -> Result<String, AppError> {
        let mut merged = ConfigText::merged(config);
        let runner = self.app.runners.for_config(&merged);
        if runner.row().command_path {
            return self.command_cell_script(&merged);
        }
        if Self::word(&merged, "LLAMA_MODELS_DIR").is_empty() {
            merged.insert("LLAMA_MODELS_DIR".to_string(), json!(self.app.paths.default_models_dir.to_string_lossy()));
        }
        let block = ConfigText::build_block(&merged, &self.app.runners)?;
        let cells = CellCommand::of(self.app);
        let command = cells.local_command(&merged, locations)?;
        let binary_ok = command.first().is_some_and(|binary| binary.contains("llama-server"));
        if command.len() < 2 || !binary_ok {
            return Err(AppError::with_status("generated launch command looks invalid", 500));
        }
        let guards = Self::start_guards(&cells.model_paths(&merged, locations));
        // absent-ok: a llama-config runner has a binary: it built `command` above.
        let binary = Self::shell_path_value(&runner.server_binary("$LLAMA_HOME").unwrap_or_default());
        let args: Vec<String> = command.iter().skip(1).map(|word| ShellWord::quote(word)).collect();
        let mut lines = vec![
            "#!/usr/bin/env bash".to_string(),
            "set -euo pipefail".to_string(),
            String::new(),
            "LLAMA_HOME=\"$HOME/llama.cpp\"".to_string(),
            "export LD_LIBRARY_PATH=\"$LLAMA_HOME/build/bin:$LLAMA_HOME/build/lib:${LD_LIBRARY_PATH:-}\"".to_string(),
            "export PATH=\"$LLAMA_HOME/build/bin:$PATH\"".to_string(),
        ];
        lines.extend(Self::export_lines(&runner.launch_env(&merged)));
        lines.push(String::new());
        lines.push(block.trim_end_matches('\n').to_string());
        lines.push(String::new());
        lines.push(format!(
            "{} — generated from the config above by the admin UI; edit via the UI, not by hand",
            Self::COMMAND_BEGIN
        ));
        lines.extend(guards);
        lines.push(format!("exec \"{binary}\" {} \"$@\"", args.join(" ")));
        lines.push(Self::COMMAND_END.to_string());
        lines.push(String::new());
        Ok(lines.join("\n"))
    }

    /// A name a backup's file can carry.
    pub fn sanitize_snapshot_name(name: &str) -> String {
        let mut out = String::new();
        let mut in_run = false;
        for letter in Coerce::strip(name).chars() {
            if letter.is_alphanumeric() || matches!(letter, '_' | '.' | '-') {
                out.push(letter);
                in_run = false;
            } else if !in_run {
                out.push('-');
                in_run = true;
            }
        }
        out.trim_matches(['-', '.']).chars().take(60).collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_path_goes_into_double_quotes_with_home_said_as_home() {
        assert_eq!(LaunchScript::shell_path_value(" ~/a b "), "$HOME/a b");
        assert_eq!(LaunchScript::shell_path_value("~"), "$HOME");
        assert_eq!(LaunchScript::shell_path_value(r#"/a"b\c"#), r#"/a\"b\\c"#);
        assert_eq!(LaunchScript::shell_path_value(""), "");
    }

    #[test]
    fn statements_join_after_a_word_that_opens_a_block() {
        let lines: Vec<String> = ["if x; then", "  y", "", "fi", "z"].iter().map(ToString::to_string).collect();
        assert_eq!(LaunchScript::one_line_statements(&lines), ["if x; then y", "fi", "z"]);
    }

    #[test]
    fn a_snapshot_name_is_plain() {
        assert_eq!(LaunchScript::sanitize_snapshot_name(" a b/c "), "a-b-c");
        assert_eq!(LaunchScript::sanitize_snapshot_name("..x.."), "x");
        assert_eq!(LaunchScript::sanitize_snapshot_name(&"y".repeat(99)).len(), 60);
    }

    #[test]
    fn env_is_exported_with_its_quotes_escaped() {
        let pairs = vec![("A".to_string(), "b\"c".to_string())];
        assert_eq!(LaunchScript::export_lines(&pairs), ["export A=\"b\\\"c\""]);
        assert_eq!(LaunchScript::env_words(&pairs), ["A=\"b\\\"c\""]);
    }
}
