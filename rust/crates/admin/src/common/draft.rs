//! Which speculative type a draft file is for, read from its path, and which draft files a model may be drafted by, found by what their headers say. The first rule lives twice, here and in static/js/draft-file.js; both copies are run against one table of cases.

use serde_json::Value;
use std::collections::BTreeMap;

/// A draft file, named by its path, and the speculative type it is for.
pub struct DraftFile<'path> {
    path: &'path str,
}

impl<'path> DraftFile<'path> {
    /// Sidecar prefix to speculative type: upstream's own convention. Matched on the FIRST word of the name only, so a model that merely contains one of these words is not taken for a sidecar.
    const PREFIXES: [(&'static str, &'static str); 4] =
        [("dflash", "draft-dflash"), ("dspark", "draft-dspark"), ("eagle3", "draft-eagle3"), ("mtp", "draft-mtp")];
    /// The layout before upstream's `mtp-` names: a model's MTP head in a folder of its own.
    const MTP_FOLDER: &'static str = "mtp";
    /// A file that is no sidecar is a plain second model, drafted autoregressively. Not draft-mtp: that aborts outright on a model with no MTP head.
    const PLAIN: &'static str = "draft-simple";

    /// The file at `path`.
    pub fn new(path: &'path str) -> Self {
        Self { path }
    }

    /// The type the file is a sidecar for, or "" when it is none: said, not guessed.
    pub fn sidecar_type(&self) -> &'static str {
        let (folders, name) = self.path.rsplit_once('/').map_or(("", self.path), |(folders, name)| (folders, name));
        let lower = name.to_lowercase();
        let head = lower.split(['-', '_', '.']).next().unwrap_or_default();
        if let Some((_, kind)) = Self::PREFIXES.iter().find(|(prefix, _)| *prefix == head) {
            return kind;
        }
        if folders.split('/').any(|folder| folder.to_lowercase() == Self::MTP_FOLDER) {
            return "draft-mtp";
        }
        ""
    }

    /// The type a cell with no type of its own launches the file with.
    pub fn launch_type(&self) -> &'static str {
        match self.sidecar_type() {
            "" => Self::PLAIN,
            kind => kind,
        }
    }
}

/// The drafts of a library by the architecture of the model each is a draft of. A draft file's architecture is its model's with `-mtp` after it: an architecture with no `-mtp` partner in the library gets nothing, and a draft of another architecture is never offered to a model it was not made for.
#[derive(Debug, Default)]
pub struct DraftPairing {
    by_model_arch: BTreeMap<String, Vec<Value>>,
}

impl DraftPairing {
    const SUFFIX: &'static str = "-mtp";

    /// Takes a draft file by the architecture its header names; a file whose header names none, or none of the form `<model's>-mtp`, is paired with no model.
    pub fn add(&mut self, path: Value, architecture: &str) {
        if let Some(base) = architecture.strip_suffix(Self::SUFFIX).filter(|base| !base.is_empty()) {
            self.by_model_arch.entry(base.to_string()).or_default().push(path);
        }
    }

    /// The drafts made for models of this architecture, in the order they were added.
    pub fn of(&self, architecture: &str) -> Vec<Value> {
        // absent-ok: an architecture with no partner in the library gets nothing
        self.by_model_arch.get(architecture).cloned().unwrap_or_default()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn a_draft_is_told_by_its_first_word_or_its_folder() {
        assert_eq!(DraftFile::new("q/mtp-q2_0.gguf").launch_type(), "draft-mtp");
        assert_eq!(DraftFile::new("q/Eagle3_x.gguf").launch_type(), "draft-eagle3");
        assert_eq!(DraftFile::new("m/mtp/head.gguf").sidecar_type(), "draft-mtp");
        assert_eq!(DraftFile::new("q/model-mtp.gguf").sidecar_type(), "");
        assert_eq!(DraftFile::new("q/model.gguf").launch_type(), "draft-simple");
    }

    #[test]
    fn a_draft_goes_with_the_architecture_it_was_made_for() {
        let mut pairing = DraftPairing::default();
        pairing.add(json!("a"), "qwen4exp-mtp");
        pairing.add(json!("b"), "qwen35");
        pairing.add(json!("c"), "-mtp");
        assert_eq!(pairing.of("qwen4exp"), [json!("a")]);
        assert!(pairing.of("qwen35").is_empty());
    }
}
