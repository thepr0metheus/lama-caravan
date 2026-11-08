//! Strata for DeepSeek-V4.1-Flash (40 layers of 384 experts, 6 per token, a 111 GB n-gram table beside them): ISTA-DASLab's IST-DAS sets of 1.75, 2.00 and 2.25 bits, run by Strata's own
//! engine for this model, `strata-dsv41`, on every card of the machine (Papyrus caravan-big-models-ssd, step 1; the owner gave its go on 2026-11-03).
//!
//! A set is several files the library keeps apart, and Strata's pack is made from all of them: the set's own parts, the n-gram table every set shares (the Engram), the 5.8 MB first part of
//! Unsloth's set that carries the Engram's hash parameters, Unsloth's DSpark drafter, and the picture reader. The operator picks the set; the others are the files Strata pins by name
//! (setup.py `DSV41_*`), found in the library when the cell is saved and written into its settings, where they can be read and changed. A start that lacks one is refused with the file named
//! and where /hf has it, before a byte is copied.

use super::{Config, Runner, RunnerDefaults, RunnerRow, TalkSpec};
use crate::models::walk::Walker;
use regex::{Regex, RegexBuilder};
use rules::{AppError, AskedWindow, ConfigField, PyRepr, ShellWord};
use serde_json::{Value, json};
use std::collections::BTreeMap;
use std::path::Path;

/// A file a set reads beside its own parts: the field it is named in, the name Strata pins, the repository /hf takes it from, and whether a start goes without it.
struct Companion {
    field: &'static str,
    name: &'static str,
    repo: &'static str,
    optional: bool,
}

/// The runner.
pub struct StrataDeepSeekRunner {
    set: Regex,
}

impl StrataDeepSeekRunner {
    const ROW: RunnerRow = RunnerRow {
        id: "strata-ds",
        icon: "\u{1faa8}",
        label_key: "runnerStrataDs",
        benefits_key: "runnerStrataDsBenefits",
        minus_key: "runnerStrataDsMinus",
        // The kind of a DeepSeek-V4.1 GGUF, named after the model: InferSSD reads it too (2026-11-03).
        artifacts: &["deepseek41-gguf"],
        needs_key: "runnerNeedsStrataDsGguf",
        gpu_only: true,
        formats: &["gguf"],
        gguf_archs: &["deepseek41"],
        health: "/health",
        api: "openai",
        talk: TalkSpec { modes: &["text-chat"], ..TalkSpec::NONE },
        model_field: Some("MODEL_FILE"),
        model_files: &["MODEL_FILE", "STRATA_ENGRAM_FILE", "STRATA_META_FILE", "SPEC_DRAFT_MODEL_FILE", "MMPROJ_FILE"],
        // COMPANIONS' fields: a test holds the two together.
        own_companions: &["STRATA_ENGRAM_FILE", "STRATA_META_FILE", "SPEC_DRAFT_MODEL_FILE", "MMPROJ_FILE"],
        shared_picker: "source",
        token_context: true,
        context_field: "STRATA_CONTEXT",
        default_health_path: "/health",
        needs_models_dir: true,
        // A set's first part names six parts and the library has five: the sixth is the Engram, named apart. Only a scout that copies what the start asks for brings it (2.44.0).
        min_scout: Some((2, 44, 0)),
        work_folder: true,
        ..RunnerRow::BASE
    };
    /// What a set reads beside its own parts, as Strata 0.2.9 pins them. The picture reader is ISTA-DASLab's own; without it the cell reads text only.
    const COMPANIONS: [Companion; 4] = [
        Companion {
            field: "STRATA_ENGRAM_FILE",
            name: "DeepSeek-V4.1-Flash-Engram-IQ4_NL.gguf",
            repo: "ISTA-DASLab/DeepSeek-V4.1-Flash-1017-GSQ-RCO-GGUF",
            optional: false,
        },
        Companion {
            field: "STRATA_META_FILE",
            name: "DeepSeek-V4.1-Flash-1017-UD-Q8_K_XL-00001-of-00009.gguf",
            repo: "unsloth/DeepSeek-V4.1-Flash-1017-GGUF",
            optional: false,
        },
        Companion {
            field: "SPEC_DRAFT_MODEL_FILE",
            name: "dspark-DeepSeek-V4.1-Flash-1017-Q8_0.gguf",
            repo: "unsloth/DeepSeek-V4.1-Flash-1017-GGUF",
            optional: false,
        },
        Companion {
            field: "MMPROJ_FILE",
            name: "mmproj-DeepSeek-V4.1-Flash-1017-BF16.gguf",
            repo: "ISTA-DASLab/DeepSeek-V4.1-Flash-1017-GSQ-RCO-GGUF",
            optional: true,
        },
    ];
    /// The RAM Strata's table says each set needs (setup.py MULTI_FILE_FAMILIES, `ram_gb`): the engine keeps the experts used most in RAM and reads the rest from the disk, sizing its store itself.
    const RAM_GB: [(&'static str, i64); 3] = [("IQ1_M", 34), ("IQ2_XXS", 40), ("IQ2_XS", 44)];
    /// The parts of a set the library holds under the set's name in ISTA-DASLab's six-part layout of 2026-10-27: the sixth is the Engram.
    const SIX_PART_SETS_BRING: u32 = 5;

    /// The runner. Its pattern is this program's own text.
    pub fn new() -> Result<Self, regex::Error> {
        Ok(Self {
            set: RegexBuilder::new(r"^DeepSeek-V4\.1-Flash-1017-GSQ-RCO-(IQ1_M|IQ2_XXS|IQ2_XS)-00001-of-0000([46])\.gguf$")
                .case_insensitive(true)
                .build()?,
        })
    }

    fn file_name(path: &str) -> &str {
        path.rsplit('/').next().unwrap_or(path)
    }

    /// `(quant, parts the set is split in)` when `path` names the first part of an IST-DAS set; `None` for any other file.
    fn set_of(&self, path: &str) -> Option<(String, u32)> {
        let found = self.set.captures(Self::file_name(path))?;
        let quant = found.get(1)?.as_str().to_uppercase();
        let parts = found.get(2)?.as_str().parse().ok()?;
        Some((quant, parts))
    }

    fn path(rel: &str) -> String {
        if rel.starts_with('/') || rel.starts_with('$') {
            return ShellWord::quote(rel);
        }
        format!("{}{}", super::MODELS_ROOT, ShellWord::quote(rel))
    }

    /// The window asked for: the field's number, and for a field left empty the window the model was trained for (the owner's rule of 2026-10-26). Anything else is refused, not replaced.
    fn context(config: &Config, trained: Option<i64>) -> Result<Option<i64>, AppError> {
        let field = Self::ROW.context_field;
        let raw = ConfigField::word(config, field);
        let window = AskedWindow::of(&raw, trained);
        if window.is_none() && !AskedWindow::empty(&raw) {
            return Err(AppError::new(format!("{field} must be a number of tokens, not {}", PyRepr::of(&raw))));
        }
        Ok(window)
    }

    /// The file named `name` in the library under `root`, by its path there: the one nearest to `near` (most folders in common), the first in path order among equals; `None` when the library
    /// holds none. A file still downloading ends in `.part` and is not this name.
    fn find(root: &Path, name: &str, near: &str) -> Option<String> {
        let found: Vec<String> = Walker::ending_in(root, name)
            .iter()
            .filter(|path| path.file_name().is_some_and(|said| said == name) && path.is_file())
            .filter_map(|path| Walker::relative(path, root))
            .collect();
        let shared = |rel: &str| rel.split('/').zip(near.split('/')).take_while(|(one, other)| one == other).count();
        // max_by_key keeps the last of equals: walked in reverse, the first in path order wins.
        found.iter().rev().max_by_key(|rel| shared(rel)).cloned()
    }

    /// The `run_strata.sh` line, with the window the model was trained for, which an empty context field asks for.
    pub fn command_with(&self, config: &Config, trained: Option<i64>) -> Result<String, AppError> {
        let model = ConfigField::word(config, "MODEL_FILE");
        if model.is_empty() {
            return Err(AppError::new("MODEL_FILE is required for a Strata DeepSeek cell"));
        }
        let mut parts =
            vec![format!("bash $HOME/run_strata.sh \"$PORT\" {}", Self::path(&model)), "--family deepseek41".to_string()];
        let flags = [
            ("STRATA_ENGRAM_FILE", "--engram"),
            ("STRATA_META_FILE", "--meta"),
            ("SPEC_DRAFT_MODEL_FILE", "--dspark"),
            ("MMPROJ_FILE", "--mmproj"),
        ];
        for (field, flag) in flags {
            let file = ConfigField::word(config, field);
            if !file.is_empty() {
                parts.extend([flag.to_string(), Self::path(&file)]);
            }
        }
        if let Some(window) = Self::context(config, trained)? {
            parts.extend(["--context".to_string(), window.to_string()]);
        }
        let said = ConfigField::word(config, "MODEL_NAME");
        let name = if said.is_empty() { ConfigField::word(config, "ALIAS") } else { said };
        if !name.is_empty() {
            parts.extend(["--name".to_string(), ShellWord::quote(&name)]);
        }
        Ok(parts.join(" "))
    }
}

impl Runner for StrataDeepSeekRunner {
    fn row(&self) -> &RunnerRow {
        &Self::ROW
    }

    fn artifact_label(&self, config: &Config, _quant_words: &[&str]) -> String {
        let model = ConfigField::word(config, "MODEL_FILE");
        self.set_of(&model).map_or_else(|| "DeepSeek-V4.1-Flash".to_string(), |(quant, _)| format!("DeepSeek-V4.1-Flash {quant}"))
    }

    fn command(&self, config: &Config) -> Result<String, AppError> {
        self.command_with(config, None)
    }

    /// Fills in what the set reads beside its own parts, from the library, where the cell names none: a file the operator named stays his. The library is the cell's models
    /// folder where this controller has it, else the controller's own.
    fn complete(&self, config: &mut Config, defaults: &RunnerDefaults) {
        let said = ConfigField::word(config, "LLAMA_MODELS_DIR");
        let root = if !said.is_empty() && Path::new(&said).is_dir() { said } else { defaults.models_dir.clone() };
        let model = ConfigField::word(config, "MODEL_FILE");
        for companion in &Self::COMPANIONS {
            if ConfigField::word(config, companion.field).is_empty()
                && let Some(rel) = Self::find(Path::new(&root), companion.name, &model)
            {
                config.insert(companion.field.to_string(), json!(rel));
            }
        }
    }

    fn prepare(&self, merged: &mut Config, defaults: &RunnerDefaults) -> Result<String, AppError> {
        defaults.fill_models_dir(merged);
        self.complete(merged, defaults);
        self.command(merged)
    }

    fn preflight_start(&self, config: &Config, model: &str) -> Result<(), AppError> {
        let first = if model.is_empty() { self.model_ref(config) } else { model.to_string() };
        if self.set_of(&first).is_none() {
            return Err(AppError::new(format!(
                "{} is not the first part of an IST-DAS DeepSeek-V4.1-Flash set: pick one (…-IQ1_M-00001-of-00006.gguf, from ISTA-DASLab/DeepSeek-V4.1-Flash-1017-GSQ-RCO-GGUF on /hf)",
                if first.is_empty() { "The cell's model".to_string() } else { Self::file_name(&first).to_string() }
            )));
        }
        if let Some(missing) =
            Self::COMPANIONS.iter().find(|companion| !companion.optional && ConfigField::word(config, companion.field).is_empty())
        {
            return Err(AppError::new(format!(
                "the set needs {} beside it and the cell names none: download it on /hf from {}, then save the cell again — the file is found in the library",
                missing.name, missing.repo
            )));
        }
        Ok(())
    }

    /// The RAM Strata's table says the set needs; `None` for a file that is no set.
    fn ram_reservation(&self, config: &Config, _sizes: &BTreeMap<String, i64>) -> Option<Value> {
        let (quant, _) = self.set_of(&ConfigField::word(config, "MODEL_FILE"))?;
        let gib = Self::RAM_GB.iter().find(|(said, _)| *said == quant).map(|(_, gib)| *gib)?;
        Some(json!({
            "reserveMiB": gib * 1024,
            "who": "Strata",
            "why": format!("Strata's table for this set: {gib} GB of RAM — it keeps the experts used most there and reads the rest from the disk"),
            "lower": "nothing — stop another cell",
        }))
    }

    fn keeps_ram(&self) -> bool {
        true
    }

    /// Strata's engine sizes its expert cache to what the cards have free: every card of the machine.
    fn vram_plan(&self) -> Value {
        json!({"takesFree": true, "everyCard": true})
    }

    /// Five of a six-part set's parts (the sixth is the Engram, named apart); the metadata part alone (only its header is read).
    fn parts_brought(&self, field: &str, value: &str) -> Option<u32> {
        match field {
            "MODEL_FILE" => self.set_of(value).filter(|(_, parts)| *parts == 6).map(|_| Self::SIX_PART_SETS_BRING),
            "STRATA_META_FILE" => Some(1),
            _ => None,
        }
    }

    /// Every card: the engine takes them all.
    fn pinned_card(&self, _config: &Config, _gpus: &[Value]) -> Option<i64> {
        None
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const SET: &str =
        "DeepSeek-V4.1-Flash-1017-GSQ-RCO-GGUF/ISTA-DASLab/IQ1_M/DeepSeek-V4.1-Flash-1017-GSQ-RCO-IQ1_M-00001-of-00006.gguf";

    fn config(pairs: &[(&str, &str)]) -> Config {
        pairs.iter().map(|(key, value)| ((*key).to_string(), json!(value))).collect()
    }

    fn runner() -> StrataDeepSeekRunner {
        StrataDeepSeekRunner::new().unwrap()
    }

    fn library(name: &str, files: &[&str]) -> crate::tests::TestFolder {
        let folder = crate::tests::TestFolder::new(name);
        for file in files {
            let path = folder.path.join(file);
            std::fs::create_dir_all(path.parent().unwrap()).unwrap();
            std::fs::write(path, b"x").unwrap();
        }
        folder
    }

    #[test]
    fn a_set_is_known_by_the_name_of_its_first_part() {
        let runner = runner();
        assert_eq!(runner.set_of(SET), Some(("IQ1_M".to_string(), 6)));
        assert_eq!(
            runner.set_of("x/DeepSeek-V4.1-Flash-1017-GSQ-RCO-IQ2_XS-00001-of-00004.gguf"),
            Some(("IQ2_XS".to_string(), 4)),
            "the pinned four-part layout too"
        );
        for other in [
            "x/DeepSeek-V4.1-Flash-1017-GSQ-RCO-IQ1_M-00002-of-00006.gguf",
            "x/DeepSeek-V4.1-Flash-Engram-IQ4_NL.gguf",
            "x/DeepSeek-V4.1-Flash-1017-UD-Q8_K_XL-00001-of-00009.gguf",
            "x/Qwen3.8-Flash-Next-GSQ-RCO-IQ1_M-00001-of-00002.gguf",
            "",
        ] {
            assert_eq!(runner.set_of(other), None, "{other}: no set");
        }
    }

    #[test]
    fn the_line_names_every_file_of_the_set_and_the_window() {
        let settings = config(&[
            ("MODEL_FILE", SET),
            ("STRATA_ENGRAM_FILE", "e/IQ4_NL/DeepSeek-V4.1-Flash-Engram-IQ4_NL.gguf"),
            ("STRATA_META_FILE", "u/Q8_K_XL/m-00001-of-00009.gguf"),
            ("SPEC_DRAFT_MODEL_FILE", "u/Q8_0/dspark.gguf"),
            ("STRATA_CONTEXT", "32768"),
            ("MODEL_NAME", "deepseek flash"),
        ]);
        let root = super::super::MODELS_ROOT;
        assert_eq!(
            runner().command(&settings).unwrap(),
            format!(
                "bash $HOME/run_strata.sh \"$PORT\" {root}{SET} --family deepseek41 --engram {root}e/IQ4_NL/DeepSeek-V4.1-Flash-Engram-IQ4_NL.gguf --meta {root}u/Q8_K_XL/m-00001-of-00009.gguf --dspark {root}u/Q8_0/dspark.gguf --context 32768 --name 'deepseek flash'"
            )
        );
        let mut empty = settings.clone();
        empty.insert("STRATA_CONTEXT".to_string(), json!(""));
        assert!(
            runner().command_with(&empty, Some(1_048_576)).unwrap().contains("--context 1048576"),
            "an empty window is the trained one"
        );
        assert!(!runner().command(&empty).unwrap().contains("--context"), "and none, when the header was not read");
        empty.insert("STRATA_CONTEXT".to_string(), json!("lots"));
        assert!(runner().command(&empty).unwrap_err().message.contains("STRATA_CONTEXT must be a number"));
        assert!(runner().command(&config(&[])).unwrap_err().message.contains("MODEL_FILE is required"));
    }

    #[test]
    fn a_save_finds_what_the_set_reads_beside_it_and_keeps_what_the_operator_named() {
        let folder = library(
            "strata-ds-find",
            &[
                SET,
                "DeepSeek-V4.1-Flash-1017-GSQ-RCO-GGUF/ISTA-DASLab/IQ4_NL/DeepSeek-V4.1-Flash-Engram-IQ4_NL.gguf",
                "Other/copy/DeepSeek-V4.1-Flash-Engram-IQ4_NL.gguf",
                "DeepSeek-V4.1-Flash-1017-GGUF/unsloth/Q8_K_XL/DeepSeek-V4.1-Flash-1017-UD-Q8_K_XL-00001-of-00009.gguf",
                "DeepSeek-V4.1-Flash-1017-GGUF/unsloth/Q8_0/dspark-DeepSeek-V4.1-Flash-1017-Q8_0.gguf.part",
            ],
        );
        let defaults = RunnerDefaults { models_dir: folder.path.to_string_lossy().into_owned(), home: String::new() };
        let mut merged = config(&[("MODEL_FILE", SET), ("MMPROJ_FILE", "mine/mmproj.gguf")]);
        runner().prepare(&mut merged, &defaults).unwrap();
        assert_eq!(
            ConfigField::word(&merged, "STRATA_ENGRAM_FILE"),
            "DeepSeek-V4.1-Flash-1017-GSQ-RCO-GGUF/ISTA-DASLab/IQ4_NL/DeepSeek-V4.1-Flash-Engram-IQ4_NL.gguf",
            "the copy beside the set, not the other one"
        );
        assert_eq!(
            ConfigField::word(&merged, "STRATA_META_FILE"),
            "DeepSeek-V4.1-Flash-1017-GGUF/unsloth/Q8_K_XL/DeepSeek-V4.1-Flash-1017-UD-Q8_K_XL-00001-of-00009.gguf"
        );
        assert_eq!(ConfigField::word(&merged, "SPEC_DRAFT_MODEL_FILE"), "", "a file still downloading is not there");
        assert_eq!(ConfigField::word(&merged, "MMPROJ_FILE"), "mine/mmproj.gguf", "what the operator named stays");
        let refused = runner().preflight_start(&merged, "").unwrap_err();
        assert!(
            refused.message.contains("dspark-DeepSeek-V4.1-Flash-1017-Q8_0.gguf")
                && refused.message.contains("unsloth/DeepSeek-V4.1-Flash-1017-GGUF"),
            "{}",
            refused.message
        );
        merged.insert("SPEC_DRAFT_MODEL_FILE".to_string(), json!("u/dspark.gguf"));
        merged.remove("MMPROJ_FILE");
        assert!(runner().preflight_start(&merged, "").is_ok(), "without the picture reader it reads text only");
        let other = runner().preflight_start(&merged, "x/Qwen3.8-Flash-Next-GSQ-RCO-IQ1_M-00001-of-00002.gguf").unwrap_err();
        assert!(
            other.message.starts_with("Qwen3.8-Flash-Next-GSQ-RCO-IQ1_M-00001-of-00002.gguf is not the first part"),
            "{}",
            other.message
        );
    }

    #[test]
    fn the_files_a_save_finds_are_the_ones_the_board_leaves_as_the_cell_names_them() {
        let found: Vec<&str> = StrataDeepSeekRunner::COMPANIONS.iter().map(|companion| companion.field).collect();
        assert_eq!(found, StrataDeepSeekRunner::ROW.own_companions, "one list: what `complete` fills is what a form keeps");
        assert!(RunnerRow::BASE.own_companions.is_empty(), "a runner that says nothing names no companion itself");
    }

    #[test]
    fn a_start_brings_five_parts_of_a_six_part_set_and_the_metadata_part_alone() {
        let runner = runner();
        assert_eq!(runner.parts_brought("MODEL_FILE", SET), Some(5));
        assert_eq!(
            runner.parts_brought("MODEL_FILE", "x/DeepSeek-V4.1-Flash-1017-GSQ-RCO-IQ1_M-00001-of-00004.gguf"),
            None,
            "the four-part layout brings every part"
        );
        assert_eq!(runner.parts_brought("STRATA_META_FILE", "u/m-00001-of-00009.gguf"), Some(1));
        assert_eq!(runner.parts_brought("STRATA_ENGRAM_FILE", "e.gguf"), None);
    }

    #[test]
    fn the_ram_a_set_promises_is_strata_s_table() {
        let runner = runner();
        let said = runner.ram_reservation(&config(&[("MODEL_FILE", SET)]), &BTreeMap::new()).unwrap();
        assert_eq!(said["reserveMiB"], json!(34 * 1024));
        assert!(said["why"].as_str().unwrap().contains("34 GB"));
        let big = "x/DeepSeek-V4.1-Flash-1017-GSQ-RCO-IQ2_XS-00001-of-00006.gguf";
        assert_eq!(
            runner.ram_reservation(&config(&[("MODEL_FILE", big)]), &BTreeMap::new()).unwrap()["reserveMiB"],
            json!(44 * 1024)
        );
        assert_eq!(
            runner.ram_reservation(&config(&[("MODEL_FILE", "x/other.gguf")]), &BTreeMap::new()),
            None,
            "no set, no figure"
        );
        assert_eq!(
            runner.pinned_card(&config(&[("ENV", "CUDA_VISIBLE_DEVICES=1")]), &[json!({"index": 1})]),
            None,
            "it takes every card"
        );
    }
}
