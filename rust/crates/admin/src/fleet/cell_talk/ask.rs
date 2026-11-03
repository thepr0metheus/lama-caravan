//! What the window sends: its form, its turns, its consent, the voices a cell lists.

use super::*;

/// A multipart/form-data body.
#[derive(Default)]
pub(super) struct FormBody {
    pub(super) parts: Vec<u8>,
}

impl FormBody {
    pub(super) const BOUNDARY: &'static str = "caravan-talk";

    pub(super) fn part(&mut self, head: &str, data: &[u8]) -> Result<(), AppError> {
        let boundary = format!("--{}", Self::BOUNDARY);
        if data.windows(boundary.len()).any(|window| window == boundary.as_bytes()) {
            return Err(AppError::new(format!("a value of the form holds its boundary {boundary}")));
        }
        self.parts.extend_from_slice(format!("{boundary}\r\n{head}\r\n\r\n").as_bytes());
        self.parts.extend_from_slice(data);
        self.parts.extend_from_slice(b"\r\n");
        Ok(())
    }

    pub(super) fn field(&mut self, name: &str, value: &str) -> Result<(), AppError> {
        self.part(&format!("Content-Disposition: form-data; name=\"{name}\""), value.as_bytes())
    }

    pub(super) fn file(&mut self, name: &str, filename: &str, ctype: &str, data: &[u8]) -> Result<(), AppError> {
        self.part(
            &format!("Content-Disposition: form-data; name=\"{name}\"; filename=\"{filename}\"\r\nContent-Type: {ctype}"),
            data,
        )
    }

    pub(super) fn done(mut self) -> (Vec<u8>, String) {
        self.parts.extend_from_slice(format!("--{}--\r\n", Self::BOUNDARY).as_bytes());
        (self.parts, format!("multipart/form-data; boundary={}", Self::BOUNDARY))
    }
}

/// One message of the talk as the window keeps it.
#[derive(Debug)]
pub(super) struct TalkTurn {
    pub(super) role: String,
    pub(super) text: String,
    pub(super) audio: Vec<u8>,
}

/// What the window asks, read from its body and refused when it is not what a mode can send.
#[derive(Debug)]
pub(super) struct TalkAsk {
    pub(super) audio: Vec<u8>,
    pub(super) text: String,
    pub(super) history: Vec<TalkTurn>,
    pub(super) system: Option<String>,
    pub(super) voice: String,
    pub(super) sample: Vec<u8>,
    pub(super) sample_text: String,
}

impl TalkAsk {
    pub(super) const MAX_AUDIO: usize = 10_000_000;
    pub(super) const MAX_TOTAL: usize = 24_000_000;
    pub(super) const MAX_TEXT: usize = 20_000;
    pub(super) const MAX_HISTORY: usize = 64;

    pub(super) fn recording(raw: Option<&Value>, what: &str) -> Result<Vec<u8>, AppError> {
        let Some(raw) = raw.filter(|raw| !raw.is_null() && **raw != json!("")) else {
            return Ok(Vec::new());
        };
        let audio =
            Base64Std::decode(&Coerce::str_of(Some(raw))).ok_or_else(|| AppError::new(format!("{what} is not base64")))?;
        if audio.len() > Self::MAX_AUDIO {
            return Err(AppError::with_status(format!("{what} is longer than {} bytes", Self::MAX_AUDIO), 413));
        }
        Ok(audio)
    }

    pub(super) fn words(raw: Option<&Value>, what: &str) -> Result<String, AppError> {
        let text = Coerce::stripped(raw);
        if text.chars().count() > Self::MAX_TEXT {
            return Err(AppError::with_status(format!("{what} is longer than {} characters", Self::MAX_TEXT), 413));
        }
        Ok(text)
    }

    pub(super) fn read(body: &Value, mode: &TalkMode) -> Result<Self, AppError> {
        let audio = Self::recording(body.get("audio"), "audio")?;
        let text = Self::words(body.get("text"), "text")?;
        if mode.takes == "voice" && audio.is_empty() {
            return Err(AppError::new(format!("{} takes a recording: audio is empty", mode.id)));
        }
        if mode.takes == "text" && text.is_empty() {
            return Err(AppError::new(format!("{} takes a text: text is empty", mode.id)));
        }
        let sample = Self::recording(body.get("sample"), "sample")?;
        let sample_text = Self::words(body.get("sampleText"), "sampleText")?;
        if !sample.is_empty() && !mode.takes_sample {
            return Err(AppError::new(format!("{} takes no sample of a voice", mode.id)));
        }
        if !sample_text.is_empty() && sample.is_empty() {
            return Err(AppError::new("sampleText is the words of a sample, and there is no sample"));
        }
        if !sample.is_empty() {
            Consent::require(body)?;
        }
        let raw_history = match body.get("history").filter(|said| !said.is_null()) {
            None => &[][..],
            Some(said) => said.as_array().map(Vec::as_slice).ok_or_else(|| AppError::new("history must be a list"))?,
        };
        let (mut history, mut total) = (Vec::new(), audio.len() + sample.len());
        for (at, raw) in raw_history.iter().skip(raw_history.len().saturating_sub(Self::MAX_HISTORY)).enumerate() {
            let role = raw.get("role").and_then(Value::as_str).filter(|role| matches!(*role, "user" | "assistant"));
            let role =
                role.ok_or_else(|| AppError::new(format!("history[{at}] must be {{role: user|assistant, text, audio}}")))?;
            let text = Self::words(raw.get("text"), &format!("history[{at}].text"))?;
            let said_audio =
                if role == "user" { Self::recording(raw.get("audio"), &format!("history[{at}].audio"))? } else { Vec::new() };
            total += said_audio.len();
            history.push(TalkTurn { role: role.to_string(), text, audio: said_audio });
        }
        if total > Self::MAX_TOTAL {
            return Err(AppError::with_status(
                format!("the recordings of one request are longer than {} bytes", Self::MAX_TOTAL),
                413,
            ));
        }
        let system = match body.get("system").filter(|said| !said.is_null()) {
            None => None,
            Some(said) => Some(Self::words(Some(said), "system")?),
        };
        Ok(Self { audio, text, history, system, voice: Coerce::stripped(body.get("voice")), sample, sample_text })
    }
}

/// A voice is spoken in or kept from a sample only on the operator's word that it is their own voice, or that its owner agreed.
pub(super) struct Consent;

impl Consent {
    pub(super) const ID: &'static str = "given-on-the-caravan-board";

    pub(super) fn require(body: &Value) -> Result<(), AppError> {
        if body.get("consent") == Some(&json!(true)) {
            return Ok(());
        }
        Err(AppError::new("consent must be true: the voice of the sample is the operator's own, or its owner agreed"))
    }
}

/// The voices a cell says it has, read from vLLM-Omni's `GET /v1/audio/voices`.
pub(super) struct VoiceList;

impl VoiceList {
    pub(super) const PLACEHOLDERS: [&'static str; 1] = ["default"];

    pub(super) fn read(raw: &[u8]) -> Map<String, Value> {
        let Some(doc) = std::str::from_utf8(raw).ok().and_then(|text| serde_json::from_str::<Value>(text).ok()) else {
            return Coerce::fields(&json!({"error": "the cell's list of voices is not JSON"}));
        };
        let Some(listed) = doc.get("voices").and_then(Value::as_array) else {
            return Coerce::fields(&json!({"error": "the cell's answer has no list of voices"}));
        };
        let uploaded = doc.get("uploaded_voices").and_then(Value::as_array).into_iter().flatten();
        let stored: Vec<Value> = uploaded
            .filter(|row| row.is_object() && !Coerce::stripped(row.get("name")).is_empty())
            .map(|row| json!({"name": Coerce::stripped(row.get("name")), "words": Coerce::text(row.get("ref_text"))}))
            .collect();
        let kept: Vec<String> = stored.iter().map(|row| Coerce::text(row.get("name")).to_lowercase()).collect();
        let voices: Vec<&Value> = listed
            .iter()
            .filter(|voice| {
                voice.as_str().is_some_and(|voice| {
                    !Coerce::strip(voice).is_empty()
                        && !kept.contains(&voice.to_lowercase())
                        && !Self::PLACEHOLDERS.contains(&voice)
                })
            })
            .collect();
        Coerce::fields(&json!({"voices": voices, "stored": stored}))
    }
}
