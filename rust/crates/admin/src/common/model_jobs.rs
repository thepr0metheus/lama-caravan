//! What a model DOES, as opposed to what launches it. The commonest row said nothing at all: an LLM was whatever carried no speech badge. The jobs are one vocabulary, in one order.

use rules::Coerce;
use serde_json::Value;

/// The vocabulary and the rules that read it.
pub struct ModelJobs;

impl ModelJobs {
    /// Every job there is, in the order they are drawn.
    pub const JOBS: [&'static str; 8] =
        ["llm", "embed", "asr", "tts", "translate", "speech-translate", "voice-chat", "robot-policy"];

    const KIND_ALIASES: [(&'static str, &'static str); 12] = [
        ("stt", "asr"),
        ("asr", "asr"),
        ("tts", "tts"),
        ("translate", "translate"),
        ("speech-translate", "speech-translate"),
        ("llm", "llm"),
        ("embed", "embed"),
        ("vlm", "llm"),
        ("embedding", "embed"),
        ("voice-chat", "voice-chat"),
        ("robot-policy", "robot-policy"),
        ("vla", "robot-policy"),
    ];

    const RUNNER_JOBS: [(&'static str, &'static [&'static str]); 17] = [
        ("llama-server", &["llm"]),
        ("prism", &["llm"]),
        ("vllm", &["llm"]),
        ("strata", &["llm"]),
        ("whisper", &["asr"]),
        ("moonshine", &["asr", "tts"]),
        ("transcribe", &["asr"]),
        ("seamless", &["speech-translate"]),
        ("translate", &["translate"]),
        ("gr00t", &["robot-policy"]),
        ("personaplex", &["voice-chat"]),
        ("lfm-audio", &["tts"]),
        ("step-audio2", &["llm", "voice-chat"]),
        ("qwen3-omni", &["llm", "voice-chat"]),
        ("qwen3-tts", &["tts"]),
        ("voice-clone", &["tts"]),
        ("minicpm-omni", &["voice-chat"]),
    ];

    const ARCH_JOBS: [(&'static str, &'static [&'static str]); 5] = [
        ("personaplex", &["voice-chat"]),
        ("Lfm2AudioForConditionalGeneration", &["tts"]),
        ("step_audio_2", &["llm", "voice-chat"]),
        ("qwen3_omni_moe", &["llm", "voice-chat"]),
        ("qwen3_tts", &["tts"]),
    ];

    const OFF: [&'static str; 5] = ["", "0", "no", "false", "off"];

    /// The vocabulary's order, not the caller's: two cells reporting the same pair of jobs draw the same pair of chips in the same places.
    fn ordered(found: &[&str]) -> Vec<&'static str> {
        Self::JOBS.iter().copied().filter(|job| found.contains(job)).collect()
    }

    /// What a model in the picker does, from the row the picker already has.
    pub fn for_artifact(kind: &str, stt_variant: &str, arch: &str, family: &str) -> &'static [&'static str] {
        match Coerce::strip(kind) {
            "model" if !Coerce::strip(stt_variant).is_empty() => &["asr"],
            "model" if family == "embedding" => &["embed"],
            "model" => &["llm"],
            "st" => {
                if arch.starts_with("seamless_m4t") {
                    return &["speech-translate"];
                }
                if let Some((_, jobs)) = Self::ARCH_JOBS.iter().find(|(name, _)| *name == arch) {
                    return jobs;
                }
                if arch.to_lowercase().starts_with("gr00t") { &["robot-policy"] } else { &["llm"] }
            }
            "whisper" => &["asr"],
            "moonshine" => &["asr", "tts"],
            "translate" => &["translate"],
            _ => &[],
        }
    }

    /// The canonical jobs behind whatever a cell reported in `kinds`.
    pub fn from_kinds(kinds: &[Value]) -> Vec<&'static str> {
        let mut found = Vec::new();
        for raw in kinds {
            let word = if Coerce::truthy(Some(raw)) { Coerce::stripped(Some(raw)).to_lowercase() } else { String::new() };
            let head = word.split('.').next().unwrap_or_default();
            if let Some((_, job)) = Self::KIND_ALIASES.iter().find(|(alias, _)| *alias == head) {
                found.push(*job);
            }
        }
        Self::ordered(&found)
    }

    /// What a RUNNING cell does: what it said of itself, else what its runner does.
    pub fn for_cell(runner_id: &str, kinds: &[Value]) -> Vec<&'static str> {
        let live = Self::from_kinds(kinds);
        if !live.is_empty() {
            return live;
        }
        let id = Coerce::strip(runner_id).to_lowercase();
        Self::RUNNER_JOBS.iter().find(|(runner, _)| *runner == id).map_or_else(Vec::new, |(_, jobs)| Self::ordered(jobs))
    }

    /// The runner that launches a cell.
    pub fn cell_runner_id(config: Option<&Value>) -> String {
        let field = |name: &str| config.and_then(|config| config.get(name)).filter(|said| Coerce::truthy(Some(*said)));
        let runner = Coerce::stripped(field("RUNNER")).to_lowercase();
        if !runner.is_empty() {
            return runner;
        }
        if Coerce::text(field("CELL_KIND")).to_lowercase() == "command" {
            "custom".to_string()
        } else {
            "llama-server".to_string()
        }
    }

    /// What a cell DOES, from its record: its embeddings switch first, then what it says of itself, then its runner.
    pub fn cell_jobs(runner_id: &str, cell_meta: Option<&Value>, config: Option<&Value>) -> Vec<&'static str> {
        let config = config.filter(|config| config.is_object());
        let embeddings = config.and_then(|config| config.get("ENABLE_EMBEDDINGS")).filter(|said| Coerce::truthy(Some(*said)));
        if !Self::OFF.contains(&Coerce::stripped(embeddings).to_lowercase().as_str()) {
            return vec!["embed"];
        }
        let kinds = cell_meta.and_then(|meta| meta.get("kinds")).and_then(Value::as_array).map_or(&[][..], Vec::as_slice);
        let empty = config.and_then(Value::as_object).is_none_or(serde_json::Map::is_empty);
        Self::for_cell(if empty { "" } else { runner_id }, kinds)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn what_a_cell_says_of_itself_comes_first() {
        assert_eq!(ModelJobs::for_cell("llama-server", &[json!("stt.whisper")]), ["asr"]);
        assert_eq!(ModelJobs::for_cell("moonshine", &[]), ["asr", "tts"]);
        assert!(ModelJobs::for_cell("custom", &[]).is_empty());
        assert_eq!(ModelJobs::cell_jobs("llama-server", None, Some(&json!({"ENABLE_EMBEDDINGS": "1"}))), ["embed"]);
        assert_eq!(ModelJobs::cell_jobs("llama-server", None, Some(&json!({}))), Vec::<&str>::new());
        assert_eq!(ModelJobs::cell_jobs("llama-server", None, Some(&json!({"RUNNER": "x"}))), ["llm"]);
    }

    #[test]
    fn a_row_of_the_picker_says_its_job() {
        assert_eq!(ModelJobs::for_artifact("model", "v", "", ""), ["asr"]);
        assert_eq!(ModelJobs::for_artifact("model", "", "", "embedding"), ["embed"]);
        assert_eq!(ModelJobs::for_artifact("st", "", "seamless_m4t_v2", ""), ["speech-translate"]);
        assert_eq!(ModelJobs::for_artifact("st", "", "Gr00tN1d7", ""), ["robot-policy"]);
        assert_eq!(ModelJobs::for_artifact("st", "", "other", ""), ["llm"]);
        assert!(ModelJobs::for_artifact("nope", "", "", "").is_empty());
    }

    #[test]
    fn the_runner_of_a_cell_is_named() {
        assert_eq!(ModelJobs::cell_runner_id(Some(&json!({"RUNNER": " VLLM "}))), "vllm");
        assert_eq!(ModelJobs::cell_runner_id(Some(&json!({"CELL_KIND": "Command"}))), "custom");
        assert_eq!(ModelJobs::cell_runner_id(None), "llama-server");
    }
}
