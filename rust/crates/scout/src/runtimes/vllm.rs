//! vLLM on this machine: the version in its venv, the versions it had, and the job that installs another. The venv is `~/vllm-venv`: the controller's start line provisions and runs vLLM there.
//! vLLM is a pip package, so PyPI itself is the archive: an update and a rollback are the same `pip install vllm==X` with another pin. What is kept is a short history of the versions this venv has had, newest first.

use crate::errors::{AppError, PyRepr};
use crate::log::Log;
use crate::process::FileTimes;
use crate::runtimes::job::BackgroundJob;
use os::clock::Clock;
use rules::Coerce;
use serde_json::{Value, json};
use std::collections::BTreeMap;
use std::fs;
use std::path::PathBuf;
use std::sync::Arc;

/// The venv and its updates.
pub struct VllmVenv {
    venv: PathBuf,
    history_file: PathBuf,
    clock: Arc<dyn Clock>,
    job: BackgroundJob,
}

impl VllmVenv {
    /// How many versions the history keeps.
    const KEEP: usize = 5;
    const PREFIX: &'static str = "vllm-";
    const SUFFIX: &'static str = ".dist-info";

    /// The venv at `venv`, its history in `history_file`.
    pub fn new(venv: PathBuf, history_file: PathBuf, clock: Arc<dyn Clock>) -> Self {
        let job = BackgroundJob::new("vllm-update", "a vLLM install is already running", Arc::clone(&clock));
        Self { venv, history_file, clock, job }
    }

    fn pip(&self) -> PathBuf {
        self.venv.join("bin/pip")
    }

    /// The installed version, from its dist-info folder (what pip itself reads, without starting pip); "" when there is none.
    pub fn version(&self) -> String {
        let mut found: Vec<(i64, String)> = Vec::new();
        let Ok(lib) = fs::read_dir(self.venv.join("lib")) else {
            return String::new();
        };
        for python in lib.flatten().filter(|entry| entry.file_name().to_string_lossy().starts_with("python")) {
            let Ok(packages) = fs::read_dir(python.path().join("site-packages")) else {
                continue;
            };
            for entry in packages.flatten() {
                let name = entry.file_name().to_string_lossy().into_owned();
                if let Some(version) = name.strip_prefix(Self::PREFIX).and_then(|rest| rest.strip_suffix(Self::SUFFIX)) {
                    // absent-ok: a folder that cannot be read for its time is the oldest.
                    found.push((entry.metadata().map_or(0, |meta| FileTimes::modified(&meta)), version.to_string()));
                }
            }
        }
        found.sort_by_key(|(at, _)| std::cmp::Reverse(*at));
        found.into_iter().next().map_or_else(String::new, |(_, version)| version)
    }

    fn history(&self) -> Vec<Value> {
        let said = fs::read(&self.history_file).ok().and_then(|raw| serde_json::from_slice::<Value>(&raw).ok());
        said.and_then(|rows| rows.as_array().cloned())
            .into_iter()
            .flatten()
            .filter(|row| row.is_object() && Coerce::truthy(row.get("version")))
            .collect()
    }

    /// Puts `version` first in the history, once, keeping `KEEP`. A read of the version must not fail on this: the history just does not grow, and the journal says why.
    fn remember(&self, version: &str) {
        if version.is_empty() {
            return;
        }
        let mut rows = vec![json!({"version": version, "seenAt": self.clock.epoch() as i64})];
        rows.extend(self.history().into_iter().filter(|row| row.get("version").and_then(Value::as_str) != Some(version)));
        rows.truncate(Self::KEEP);
        let written = self.history_file.parent().map_or(Ok(()), fs::create_dir_all).and_then(|()| {
            let text = serde_json::to_string_pretty(&rows).map_err(std::io::Error::other)?;
            fs::write(&self.history_file, format!("{text}\n"))
        });
        if let Err(error) = written {
            Log::line(&format!("[vllm] history not written ({}): {error}", self.history_file.display()));
        }
    }

    /// What the System panel shows for this machine: the version, the history to roll back to, and the job.
    pub fn info(&self) -> Value {
        let current = self.version();
        self.remember(&current);
        json!({
            "ok": true,
            "installed": !current.is_empty(),
            "version": current,
            "venv": self.venv.display().to_string(),
            "history": self.history(),
            "job": self.job.status_slim(),
        })
    }

    /// A version pip is asked for: PEP 440 characters only.
    fn is_version(text: &str) -> bool {
        text.chars().next().is_some_and(|first| first.is_ascii_digit())
            && text.chars().all(|letter| letter.is_ascii_alphanumeric() || matches!(letter, '.' | '+' | '!' | '-'))
    }

    /// `{version?}`: empty installs the latest release; a version pins it (a rollback is an older pin). Refused before anything runs: no venv yet (the first vLLM start provisions it), or a version that is not one.
    pub fn start_update(&self, body: &Value) -> Result<Value, AppError> {
        if !self.pip().is_file() {
            return Err(AppError::new(format!(
                "vLLM is not installed on this machine yet — start a vLLM cell once to create its venv ({})",
                self.venv.display()
            )));
        }
        let version = if Coerce::truthy(body.get("version")) { Coerce::stripped(body.get("version")) } else { String::new() };
        if !version.is_empty() && !Self::is_version(&version) {
            return Err(AppError::new(format!("not a vLLM version: {}", PyRepr::of(&version))));
        }
        // The rollback candidate.
        self.remember(&self.version());
        let mut argv = vec![self.pip().display().to_string(), "install".to_string()];
        if version.is_empty() {
            argv.extend(["--upgrade".to_string(), "vllm".to_string()]);
        } else {
            argv.push(format!("vllm=={version}"));
        }
        let tag = format!("vllm:{}", if version.is_empty() { "latest" } else { version.as_str() });
        let environment: BTreeMap<String, String> = std::env::vars().collect();
        self.job.start(argv, &tag, environment)
    }

    /// The job's status.
    pub fn job_status(&self) -> Value {
        self.job.status()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_version_is_what_pep_440_writes() {
        for good in ["0.24.0", "1.0rc1", "1!2.0+local", "2-1"] {
            assert!(VllmVenv::is_version(good), "{good}");
        }
        for bad in ["", "latest", "1.0; rm -rf /", "v1.0", "1 0"] {
            assert!(!VllmVenv::is_version(bad), "{bad}");
        }
    }
}
