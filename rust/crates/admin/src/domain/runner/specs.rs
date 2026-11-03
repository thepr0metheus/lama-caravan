//! What a runner's row says beyond words: how the board talks to its cell, and what a launcher cell says differently from another.

use regex::RegexBuilder;
use rules::{AppError, Coerce};
use serde_json::{Map, Value, json};

/// How the board's voice window talks to a running cell of a runner. `TalkSpec::NONE` says nothing: the card offers no window.
#[derive(Debug, Clone, Copy)]
pub struct TalkSpec {
    /// Which of the window's ways of talking its server answers.
    pub modes: &'static [&'static str],
    /// The system prompt its model wants before a spoken answer.
    pub system: &'static str,
    /// The voices in each mode, the first the server's default.
    pub voices: &'static [(&'static str, &'static [&'static str])],
    /// The request's field for a voice.
    pub voice_field: &'static str,
    /// How many messages of the talk one request carries.
    pub turns: i64,
    /// The start of the answer that makes the model answer in a voice.
    pub answer_cue: &'static str,
    /// The model's own tokens its words carry, as a pattern the reader takes out.
    pub text_noise: &'static str,
    /// Where the server lists its voices, when they are the cell's to say.
    pub voices_path: &'static str,
    /// Whether the server takes a voice from a sample.
    pub clone: bool,
}

impl TalkSpec {
    /// Nothing to say.
    pub const NONE: Self = Self {
        modes: &[],
        system: "",
        voices: &[],
        voice_field: "voice",
        turns: 8,
        answer_cue: "",
        text_noise: "",
        voices_path: "",
        clone: false,
    };
    /// A voice's name as a cell that keeps voices takes it.
    pub const VOICE_NAME: &'static str = "[A-Za-z0-9_.-]{1,64}";

    /// The voices of a mode.
    pub fn voices_of(&self, mode: &str) -> &'static [&'static str] {
        self.voices.iter().find(|(said, _)| *said == mode).map_or(&[], |(_, names)| *names)
    }

    /// Whether `name` is of a voice's shape.
    pub fn is_voice_name(name: &str) -> bool {
        (1..=64).contains(&name.len())
            && name.chars().all(|letter| letter.is_ascii_alphanumeric() || matches!(letter, '_' | '.' | '-'))
    }

    /// True when `name` may go as the voice of a request in `mode`: one of the runner's voices, or, where the cell says its voices itself, any name of a voice's shape: the cell knows its own and refuses another.
    pub fn names_voice(&self, mode: &str, name: &str) -> bool {
        self.voices_of(mode).contains(&name) || (!self.voices_path.is_empty() && Self::is_voice_name(name))
    }

    pub(super) fn as_json(&self) -> Value {
        let voices: Map<String, Value> = self.voices.iter().map(|(mode, names)| ((*mode).to_string(), json!(names))).collect();
        let mut row = json!({"modes": self.modes, "system": self.system, "voices": voices, "turns": self.turns});
        if let Value::Object(fields) = &mut row {
            if !self.voices_path.is_empty() {
                fields.insert("asksVoices".to_string(), json!(true));
                fields.insert("voiceName".to_string(), json!(Self::VOICE_NAME));
            }
            if self.clone {
                fields.insert("clone".to_string(), json!(true));
            }
        }
        row
    }
}

/// How the board talks live with a running cell of a runner, over the cell's own WebSocket. An empty path says nothing.
#[derive(Debug, Clone, Copy)]
pub struct LiveSpec {
    /// The cell's WebSocket path: the controller's alone.
    pub path: &'static str,
    /// Which talk it speaks there.
    pub protocol: &'static str,
}

/// A page the cell's server serves itself, reached over https through the reverse proxy in front of the cell: the config field that holds that address. An empty field says nothing.
#[derive(Debug, Clone, Copy)]
pub struct PageSpec {
    /// The config field.
    pub field: &'static str,
}

impl PageSpec {
    /// Matched whole, ignoring case and in ASCII alone: here and in the browser alike.
    pub const PATTERN: &'static str =
        r"https://(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)*[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?::[0-9]{1,5})?(?:/[!-~]*)?";

    /// The address as a config keeps it, trimmed ("" for none), or a refusal that names the field and the form.
    pub fn checked(&self, raw: Option<&Value>) -> Result<String, AppError> {
        let text = if Coerce::truthy(raw) { Coerce::stripped(raw) } else { String::new() };
        if text.is_empty() {
            return Ok(text);
        }
        let whole = format!("^(?:{})$", Self::PATTERN);
        let pattern = RegexBuilder::new(&whole)
            .case_insensitive(true)
            .unicode(false)
            .build()
            .map_err(|error| AppError::with_status(error.to_string(), 500))?;
        if pattern.is_match(&text) {
            return Ok(text);
        }
        Err(AppError::new(format!(
            "{} must be the https address of the cell's page, https://name[:port][/path] — not {}",
            self.field,
            rules::PyRepr::of(&text)
        )))
    }
}

/// What a launcher cell says differently from another: the script of `cells/`, what it is given after the port, how the model's folder comes out of `MODEL_FILE`, and what a start takes on its card.
#[derive(Debug, Clone, Copy)]
pub struct LauncherSpec {
    /// The script.
    pub launcher: &'static str,
    /// What it is given after the port; "{model}" is the model's folder.
    pub args: &'static [&'static str],
    /// "picked" or "entry".
    pub folder_rule: &'static str,
    /// What a start takes on its card, MiB.
    pub vram_mib: i64,
    /// Who takes it, in a refusal.
    pub vram_who: &'static str,
    /// Why, in a refusal.
    pub vram_why: &'static str,
    /// The runner's name in a refusal.
    pub display_name: &'static str,
}
