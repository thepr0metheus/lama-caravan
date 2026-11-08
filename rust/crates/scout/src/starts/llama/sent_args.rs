//! The command the controller built for a llama cell, as it came: which of the cell's files it loads, and its words with this machine's paths put in.

use super::Fetched;
use crate::errors::AppError;
use rules::Coerce;
use serde_json::{Map, Value};

/// The `args` of a start's payload: everything after the binary, with a placeholder where a path of this machine goes (variant 2: the controller is the single command builder). Which of a cell's files
/// its command loads is the builder's to decide (rust/crates/admin/src/config/args/switches.rs), and this scout follows the words it was sent rather than reading the config a second time: a draft switched
/// off stays named in the config beside SPEC_TYPE "none", the builder leaves it out, and a scout that went by the config copied, counted and reported gigabytes of a draft nothing read (2026-11-07).
pub(super) struct SentArgs {
    /// `None` when the payload carried none: the launch refuses it, in its own words.
    words: Option<Vec<String>>,
}

impl SentArgs {
    /// Where the model's path goes.
    pub(super) const MODEL: &'static str = "{{MODEL_PATH}}";
    /// Where the projector's goes.
    pub(super) const PROJECTOR: &'static str = "{{MMPROJ_PATH}}";
    /// Where the draft's goes.
    pub(super) const DRAFT: &'static str = "{{SPEC_PATH}}";

    /// The args of `payload`, as the controller sent them.
    pub(super) fn of(payload: &Map<String, Value>) -> Self {
        let said = payload.get("args").and_then(Value::as_array);
        Self { words: said.map(|args| args.iter().map(|word| Coerce::text(Some(word))).collect()) }
    }

    /// `file` when the command loads what `placeholder` stands for, "" when it does not: a file the command never reads is not asked of the cache, fetched, counted in the start's weight or reported as
    /// the cell's. The projector is held to it as the draft is: the builder writes `--mmproj {{MMPROJ_PATH}}` whenever the config names a projector, and has since it first sent placeholders, so no
    /// projector a command loads is left behind, and a builder that one day leaves one out is followed here with no second rule to change.
    pub(super) fn wanted(&self, placeholder: &str, file: String) -> String {
        if self.loads(placeholder) { file } else { String::new() }
    }

    fn loads(&self, placeholder: &str) -> bool {
        self.words.iter().flatten().any(|word| word == placeholder)
    }

    /// The words as they came, placeholders and all: for a check of the command before this machine's paths are in (Prism's).
    pub(super) fn as_sent(&self) -> &[String] {
        // absent-ok: a start with no args is refused at its launch, in its own words.
        self.words.as_deref().unwrap_or_default()
    }

    /// The command with the paths of the files this machine has where the placeholders stand. The controller builds the arg list, and this scout only puts the paths in. It used to carry its own builder
    /// as a fallback, already 23 flags behind: a cell started through it looked configured on the board and ran without half of that config. Refusing is the honest answer.
    pub(super) fn resolved(&self, files: &Fetched) -> Result<Vec<String>, AppError> {
        let words = self.words.as_ref().filter(|words| !words.is_empty()).ok_or_else(|| {
            AppError::new(
                "controller sent no args for this llama cell — it is older than this agent (needs lama-caravan v1.3.115+)",
            )
        })?;
        Ok(words
            .iter()
            .map(|word| match word.as_str() {
                Self::MODEL => files.model.clone(),
                Self::PROJECTOR => files.mmproj.clone(),
                Self::DRAFT => files.spec.clone(),
                _ => word.clone(),
            })
            .collect())
    }
}
