//! A server of the caravan's own launcher over ONE model of the library: `bash $HOME/<launcher> "$PORT" …`. The launcher installs its engine at the first start, in a folder of its own and without `sudo`, and then serves the model. What a row says is what differs; the line is built here and nowhere else: the cell form's preview reads the same `launcher`, `launcherArgs` and `folderRule` out of the registry.

use super::{Config, LauncherSpec, LiveSpec, PageSpec, PinnedCard, Runner, RunnerRow, TalkSpec};
use rules::{AppError, Coerce, ConfigField, PyRepr, ShellWord};
use serde_json::{Value, json};

/// One runner of this family: nothing but its row.
pub struct LauncherCell {
    row: RunnerRow,
}

impl LauncherCell {
    const ROOT: &'static str = super::MODELS_ROOT;
    /// What the family shares.
    const FAMILY: RunnerRow = RunnerRow {
        model_field: Some("MODEL_FILE"),
        model_files: &["MODEL_FILE"],
        shared_picker: "source",
        needs_models_dir: true,
        min_scout: Some((2, 31, 0)),
        gpu_only: true,
        one_card: true,
        ..RunnerRow::BASE
    };

    fn spec(&self) -> Option<&LauncherSpec> {
        self.row.launcher.as_ref()
    }

    fn display_name(&self) -> &'static str {
        self.spec().map_or(self.row.id, |spec| spec.display_name)
    }

    /// The folder the launcher is given for a picked `MODEL_FILE`, or "" when none can be told from it. "picked": the path itself. "entry": the folder two steps above the picked file: a model of several GGUF files is picked by one of them and launched by all.
    fn folder_of_model(&self, model: &str) -> String {
        let model = Coerce::strip(model).trim_end_matches('/');
        if model.is_empty() || self.spec().is_none_or(|spec| spec.folder_rule == "picked") {
            return model.to_string();
        }
        let mut folder = model;
        for _ in 0..2 {
            folder = folder.rsplit_once('/').map_or("", |(head, _)| head);
        }
        folder.to_string()
    }

    fn model_folder(&self, config: &Config) -> Result<String, AppError> {
        let model = ConfigField::word(config, "MODEL_FILE");
        let name = self.display_name();
        if model.is_empty() {
            return Err(AppError::new(format!("MODEL_FILE is required for a {name} cell: the model's folder of the library")));
        }
        let folder = self.folder_of_model(&model);
        if folder.is_empty() {
            return Err(AppError::new(format!(
                "MODEL_FILE of a {name} cell must be a file of a library model laid out as <model>/<author>/<variant>/<file>, not {}",
                PyRepr::of(&model)
            )));
        }
        Ok(folder)
    }

    fn path(rel: &str) -> String {
        let rel = Coerce::strip(rel).trim_end_matches('/');
        if rel.starts_with('/') || rel.starts_with('$') {
            return ShellWord::quote(rel);
        }
        format!("{}{}", Self::ROOT, ShellWord::quote(rel))
    }
}

impl Runner for LauncherCell {
    fn row(&self) -> &RunnerRow {
        &self.row
    }

    fn artifact_label(&self, config: &Config, _quant_words: &[&str]) -> String {
        let model = ConfigField::word(config, "MODEL_FILE");
        model.split('/').find(|part| !part.is_empty()).map_or_else(|| self.display_name().to_string(), str::to_string)
    }

    /// The folder the launcher reads, as the scout is to bring it. A value no folder can be told from is left out: the start itself refuses it, with the field's name.
    fn model_file_values(&self, config: &Config) -> Vec<(String, String)> {
        let folder = self.folder_of_model(&ConfigField::word(config, "MODEL_FILE"));
        if folder.is_empty() { Vec::new() } else { vec![("MODEL_FILE".to_string(), folder)] }
    }

    /// The launcher's line: the port, then the arguments with the model's folder in {model}.
    fn command(&self, config: &Config) -> Result<String, AppError> {
        let folder = Self::path(&self.model_folder(config)?);
        let Some(spec) = self.spec() else {
            return Err(AppError::with_status("this runner names no launcher", 500));
        };
        let mut parts = vec![format!("bash $HOME/{} \"$PORT\"", spec.launcher)];
        parts.extend(spec.args.iter().map(|word| word.replace("{model}", &folder)));
        Ok(parts.join(" "))
    }

    fn preflight_start(&self, config: &Config, model: &str) -> Result<(), AppError> {
        if model.is_empty() && self.model_ref(config).is_empty() {
            return Err(AppError::new(format!("{} cell has no model — configure it first", self.display_name())));
        }
        Ok(())
    }

    /// What a start needs free on its card: the measured footprint, on the card the ENV pins, else the first.
    fn vram_reservation(&self, config: &Config, gpus: &[Value]) -> Option<Value> {
        let device = PinnedCard::of(config, gpus)?;
        let spec = self.spec()?;
        Some(json!({"device": device, "reserveMiB": spec.vram_mib, "who": spec.vram_who, "why": spec.vram_why, "lower": ""}))
    }

    /// A fixed figure: the engine and the model take what they took when measured.
    fn vram_plan(&self) -> Value {
        self.spec().map_or(Value::Null, |spec| json!({"fixedMiB": spec.vram_mib}))
    }
}

/// The family, in the registry's order.
pub struct LauncherRunners;

impl LauncherRunners {
    const OMNI: &'static str = "run_vllm_omni.sh";

    const PERSONAPLEX: RunnerRow = RunnerRow {
        id: "personaplex",
        icon: "\u{1f5e3}\u{fe0f}",
        label_key: "runnerPersonaplex",
        benefits_key: "runnerPersonaplexBenefits",
        minus_key: "runnerPersonaplexMinus",
        needs_key: "runnerNeedsPersonaplexSt",
        artifacts: &["personaplex-st"],
        st_archs: &["personaplex"],
        // It has no /health: its page is what answers, once the model is loaded.
        health: "/",
        default_health_path: "/",
        page: PageSpec { field: "PAGE_URL" },
        launcher: Some(LauncherSpec {
            launcher: "run_personaplex.sh",
            args: &["{model}"],
            folder_rule: "picked",
            vram_mib: 20480,
            vram_who: "PersonaPlex",
            vram_why: "the model and its codec took 19.5 GB on an RTX 5090",
            display_name: "PersonaPlex",
        }),
        ..LauncherCell::FAMILY
    };
    const LFM_AUDIO: RunnerRow = RunnerRow {
        id: "lfm-audio",
        icon: "\u{1f50a}",
        label_key: "runnerLfmAudio",
        benefits_key: "runnerLfmAudioBenefits",
        minus_key: "runnerLfmAudioMinus",
        needs_key: "runnerNeedsLfmAudioSt",
        artifacts: &["lfm-audio-st"],
        st_archs: &["Lfm2AudioForConditionalGeneration"],
        health: "/health",
        default_health_path: "/health",
        // Its chat answers the LAST user message only: one message a request, no memory of the talk.
        talk: TalkSpec {
            modes: &["spoken-chat", "speech"],
            voices: &[("speech", &["us_female", "us_male", "uk_female", "uk_male"])],
            turns: 1,
            ..TalkSpec::NONE
        },
        launcher: Some(LauncherSpec {
            launcher: "run_lfm_audio.sh",
            args: &["{model}"],
            folder_rule: "picked",
            vram_mib: 7168,
            vram_who: "LFM2.5-Audio",
            vram_why: "the model took 6.8 GB on an RTX 5090",
            display_name: "LFM2.5-Audio",
        }),
        ..LauncherCell::FAMILY
    };
    const STEP_AUDIO2: RunnerRow = RunnerRow {
        id: "step-audio2",
        icon: "\u{1f463}",
        label_key: "runnerStepAudio2",
        benefits_key: "runnerStepAudio2Benefits",
        minus_key: "runnerStepAudio2Minus",
        needs_key: "runnerNeedsStepAudio2St",
        artifacts: &["step-audio2-st"],
        st_archs: &["step_audio_2"],
        api: "openai",
        health: "/health",
        default_health_path: "/health",
        talk: TalkSpec { modes: &["spoken-chat"], answer_cue: "<tts_start>", text_noise: r"<audio_\d+>", ..TalkSpec::NONE },
        launcher: Some(LauncherSpec {
            launcher: Self::OMNI,
            args: &["step-audio2", "{model}"],
            folder_rule: "picked",
            vram_mib: 25600,
            vram_who: "Step-Audio 2",
            vram_why: "its two stages took 25 GB on an RTX 5090",
            display_name: "Step-Audio 2",
        }),
        ..LauncherCell::FAMILY
    };
    const QWEN3_OMNI: RunnerRow = RunnerRow {
        id: "qwen3-omni",
        icon: "\u{1f3ad}",
        label_key: "runnerQwen3Omni",
        benefits_key: "runnerQwen3OmniBenefits",
        minus_key: "runnerQwen3OmniMinus",
        needs_key: "runnerNeedsQwen3OmniSt",
        artifacts: &["qwen3-omni-st"],
        st_archs: &["qwen3_omni_moe"],
        api: "openai",
        health: "/health",
        default_health_path: "/health",
        // Its model card's system prompt for an answer in a voice, and its three speakers. A bare digit it speaks badly: the prompt asks for numbers in words.
        talk: TalkSpec {
            modes: &["spoken-chat"],
            voices: &[("spoken-chat", &["ethan", "chelsie", "aiden"])],
            voice_field: "speaker",
            system: "You are Qwen, a virtual human developed by the Qwen Team, Alibaba Group, capable of perceiving auditory and visual inputs, as well as generating text and speech. Answer in full sentences and write numbers in words.",
            ..TalkSpec::NONE
        },
        launcher: Some(LauncherSpec {
            launcher: Self::OMNI,
            args: &["qwen3-omni", "{model}"],
            folder_rule: "picked",
            vram_mib: 31744,
            vram_who: "Qwen3-Omni",
            vram_why: "its three stages took 30.7 GB — the whole 32 GB card — on an RTX 5090",
            display_name: "Qwen3-Omni",
        }),
        ..LauncherCell::FAMILY
    };
    const QWEN3_TTS: RunnerRow = RunnerRow {
        id: "qwen3-tts",
        icon: "\u{1f4e2}",
        label_key: "runnerQwen3Tts",
        benefits_key: "runnerQwen3TtsBenefits",
        minus_key: "runnerQwen3TtsMinus",
        needs_key: "runnerNeedsQwen3TtsSt",
        artifacts: &["qwen3-tts-st"],
        st_archs: &["qwen3_tts"],
        api: "openai",
        health: "/health",
        default_health_path: "/health",
        talk: TalkSpec { modes: &["speech"], voices_path: "/v1/audio/voices", clone: true, ..TalkSpec::NONE },
        launcher: Some(LauncherSpec {
            launcher: Self::OMNI,
            args: &["qwen3-tts", "{model}"],
            folder_rule: "picked",
            vram_mib: 9216,
            vram_who: "Qwen3-TTS",
            vram_why: "its two stages took 8.3 GB at most on an RTX 5090, and the decoder wants 2.5 GB free at its start",
            display_name: "Qwen3-TTS",
        }),
        ..LauncherCell::FAMILY
    };
    const MINICPM_OMNI: RunnerRow = RunnerRow {
        id: "minicpm-omni",
        icon: "\u{1f3a4}",
        label_key: "runnerMinicpmOmni",
        benefits_key: "runnerMinicpmOmniBenefits",
        minus_key: "runnerMinicpmOmniMinus",
        // Its model is a GGUF like any LLM's, so no file claims it: a GGUF LLM may be picked, and llama.cpp's tab stays open beside this one.
        artifacts: &["llm-gguf"],
        formats: &["gguf"],
        needs_key: "runnerNeedsMinicpmOmniGguf",
        health: "/health",
        default_health_path: "/health",
        live: LiveSpec { path: "/backend", protocol: "minicpm-omni" },
        launcher: Some(LauncherSpec {
            launcher: "run_minicpm_omni.sh",
            args: &["{model}"],
            folder_rule: "entry",
            vram_mib: 12800,
            vram_who: "MiniCPM-o",
            vram_why: "the model took 12.4 GB on an RTX 5090",
            display_name: "llama.cpp-omni",
        }),
        ..LauncherCell::FAMILY
    };

    /// InferSSD (wici-ai, Apache-2.0): llama.cpp's server forked to read a MoE model's experts from an SSD with io_uring and keep the most used ones in RAM and on the card (Papyrus
    /// caravan-big-models-ssd, step 10; the owner gave its go on 2026-11-03). One card, as its documentation describes. Its model sits on the machine's fast disk: the folder for Strata's
    /// files, where the scout copies every part of a split GGUF before the start.
    const INFERSSD: RunnerRow = RunnerRow {
        id: "inferssd",
        icon: "\u{1f4bd}",
        label_key: "runnerInferssd",
        benefits_key: "runnerInferssdBenefits",
        minus_key: "runnerInferssdMinus",
        needs_key: "runnerNeedsInferssdGguf",
        artifacts: &["deepseek41-gguf"],
        formats: &["gguf"],
        gguf_archs: &["deepseek41"],
        api: "openai",
        health: "/health",
        default_health_path: "/health",
        talk: TalkSpec { modes: &["text-chat"], ..TalkSpec::NONE },
        // The scout that copies what a start asks for onto the fast disk (the folder for Strata's files).
        min_scout: Some((2, 44, 0)),
        work_folder: true,
        launcher: Some(LauncherSpec {
            launcher: "run_inferssd.sh",
            // The window Strata's DeepSeek cell was measured at: the two compared on the same questions (step 11).
            args: &["--context", "32768", "{model}"],
            folder_rule: "picked",
            vram_mib: 31744,
            vram_who: "InferSSD",
            vram_why: "it takes the card it is given whole: its expert cache fills what the card admits (vram.budget = auto)",
            display_name: "InferSSD",
        }),
        ..LauncherCell::FAMILY
    };

    /// The cell of InferSSD: it stands beside Strata's DeepSeek cell, the other server of the same model.
    pub fn inferssd() -> Box<dyn Runner> {
        Box::new(LauncherCell { row: Self::INFERSSD })
    }

    /// All but the last, which stands after the voice-clone cell in the editor: see `after_voice_clone`.
    pub fn all() -> Vec<Box<dyn Runner>> {
        [Self::PERSONAPLEX, Self::LFM_AUDIO, Self::STEP_AUDIO2, Self::QWEN3_OMNI, Self::QWEN3_TTS]
            .into_iter()
            .map(|row| Box::new(LauncherCell { row }) as Box<dyn Runner>)
            .collect()
    }

    /// The cell of MiniCPM-o.
    pub fn after_voice_clone() -> Box<dyn Runner> {
        Box::new(LauncherCell { row: Self::MINICPM_OMNI })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::domain::runner::{RunnerDefaults, RunnerRegistry};

    const Q8: &str = "DeepSeek-V4.1-Flash-1017-GGUF/mrfakename/Q8_0/DeepSeek-V4.1-Flash-1017-Q8_0-00001-of-00010.gguf";

    fn config(pairs: &[(&str, &str)]) -> Config {
        pairs.iter().map(|(key, value)| ((*key).to_string(), json!(value))).collect()
    }

    fn registry() -> RunnerRegistry {
        RunnerRegistry::new(&RunnerDefaults { models_dir: "/m".to_string(), home: "/home/u".to_string() }).unwrap()
    }

    #[test]
    fn inferssd_reads_a_deepseek_gguf_beside_strata_from_the_fast_disk() {
        let registry = registry();
        let ids: Vec<&str> = registry.all().map(|runner| runner.row().id).collect();
        let at = |id: &str| ids.iter().position(|said| *said == id);
        assert_eq!(
            at("inferssd"),
            at("strata-ds").map(|place| place + 1),
            "it stands beside the other server of the same model: {ids:?}"
        );
        let (inferssd, strata) = (registry.get("inferssd").row(), registry.get("strata-ds").row());
        assert_eq!((inferssd.artifacts, inferssd.gguf_archs), (&["deepseek41-gguf"][..], &["deepseek41"][..]));
        assert_eq!(
            strata.artifacts.first(),
            inferssd.artifacts.first(),
            "one kind for both, named after the model: a DeepSeek-V4.1 GGUF opens both tabs"
        );
        assert!(
            !registry.get("llama-server").row().artifacts.contains(&"deepseek41-gguf"),
            "negative: llama.cpp's tab stays grey for it"
        );
        assert!(inferssd.work_folder && inferssd.one_card && inferssd.gpu_only, "the fast disk, one card, no CPU");
        assert!(
            !registry.get("personaplex").row().work_folder,
            "negative: the other launcher cells read their model where the cache keeps it"
        );
        let runner = registry.get("inferssd");
        assert_eq!(
            runner.model_file_values(&config(&[("MODEL_FILE", Q8)])),
            vec![("MODEL_FILE".to_string(), Q8.to_string())],
            "the part picked, which names the others"
        );
    }

    #[test]
    fn inferssd_reserves_the_card_it_is_given_whole() {
        let runner = LauncherRunners::inferssd();
        let gpus = [json!({"index": 0}), json!({"index": 1})];
        let pinned = runner.vram_reservation(&config(&[("MODEL_FILE", Q8), ("ENV", "CUDA_VISIBLE_DEVICES=1")]), &gpus).unwrap();
        assert_eq!(
            (pinned["device"].clone(), pinned["reserveMiB"].clone(), pinned["who"].clone()),
            (json!(1), json!(31744), json!("InferSSD"))
        );
        assert_eq!(
            runner.vram_reservation(&config(&[("MODEL_FILE", Q8)]), &gpus).unwrap()["device"],
            json!(0),
            "unpinned: the first card"
        );
        assert_eq!(
            runner.vram_reservation(&config(&[("ENV", "CUDA_VISIBLE_DEVICES=2")]), &gpus),
            None,
            "negative: a card the machine lacks"
        );
        assert_eq!(runner.vram_plan(), json!({"fixedMiB": 31744}));
    }
}
