//! What the window can ask a cell: each mode as one row, how it is sent and how its answer is read.

use super::*;

#[derive(Clone, Copy, PartialEq, Eq)]
pub(super) enum ModeKind {
    Chat,
    TextChat,
    Speech,
    Transcription,
}

/// One way of talking to a cell.
pub struct TalkMode {
    /// Its id.
    pub id: &'static str,
    pub(super) label_key: &'static str,
    pub(super) takes: &'static str,
    pub(super) gives: &'static [&'static str],
    pub(super) path: &'static str,
    pub(super) needs_hearing: bool,
    pub(super) conversation: bool,
    pub(super) takes_sample: bool,
    /// A chat's: what it asks the answer to hold.
    pub(super) modalities: &'static [&'static str],
    pub(super) kind: ModeKind,
}

impl TalkMode {
    /// Every mode, in the board's order.
    pub const ALL: [Self; 6] = [
        Self {
            id: "spoken-chat",
            label_key: "talkModeSpokenChat",
            takes: "voice",
            gives: &["voice", "text"],
            path: "/v1/chat/completions",
            needs_hearing: false,
            conversation: true,
            takes_sample: false,
            modalities: &["text", "audio"],
            kind: ModeKind::Chat,
        },
        Self {
            id: "heard-chat",
            label_key: "talkModeHeardChat",
            takes: "voice",
            gives: &["text"],
            path: "/v1/chat/completions",
            needs_hearing: true,
            conversation: true,
            takes_sample: false,
            modalities: &[],
            kind: ModeKind::Chat,
        },
        Self {
            id: "text-chat",
            label_key: "talkModeTextChat",
            takes: "text",
            gives: &["text"],
            path: "/v1/chat/completions",
            needs_hearing: false,
            conversation: true,
            takes_sample: false,
            modalities: &[],
            kind: ModeKind::TextChat,
        },
        Self {
            id: "speech",
            label_key: "talkModeSpeech",
            takes: "text",
            gives: &["voice"],
            path: "/v1/audio/speech",
            needs_hearing: false,
            conversation: false,
            takes_sample: true,
            modalities: &[],
            kind: ModeKind::Speech,
        },
        Self {
            id: "transcription",
            label_key: "talkModeTranscription",
            takes: "voice",
            gives: &["text"],
            path: "/v1/audio/transcriptions",
            needs_hearing: false,
            conversation: false,
            takes_sample: false,
            modalities: &[],
            kind: ModeKind::Transcription,
        },
        Self {
            id: "speech-translation",
            label_key: "talkModeSpeechTranslation",
            takes: "voice",
            gives: &["text"],
            path: "/v1/audio/transcriptions",
            needs_hearing: false,
            conversation: false,
            takes_sample: false,
            modalities: &[],
            kind: ModeKind::Transcription,
        },
    ];

    /// The modes as the board gets them.
    pub fn all_json() -> Value {
        let rows: Vec<Value> = Self::ALL
            .iter()
            .map(|mode| {
                json!({
                    "id": mode.id, "labelKey": mode.label_key, "takes": mode.takes, "gives": mode.gives,
                    "needsHearing": mode.needs_hearing, "conversation": mode.conversation, "takesSample": mode.takes_sample,
                })
            })
            .collect();
        Value::Array(rows)
    }

    pub(super) fn voice_field(&self, ask: &TalkAsk, spec: &TalkSpec, field: &str) -> Option<(String, Value)> {
        (!ask.voice.is_empty() && spec.names_voice(self.id, &ask.voice)).then(|| (field.to_string(), json!(ask.voice)))
    }

    pub(super) fn user(&self, audio: &[u8], text: &str) -> Value {
        if self.kind == ModeKind::TextChat {
            return json!({"role": "user", "content": text});
        }
        let mut parts = Vec::new();
        if !audio.is_empty() {
            parts.push(json!({"type": "input_audio", "input_audio": {"data": Base64Std::encode(audio), "format": "wav"}}));
        }
        if !text.is_empty() {
            parts.push(json!({"type": "text", "text": text}));
        }
        json!({"role": "user", "content": parts})
    }

    pub(super) fn messages(&self, ask: &TalkAsk, spec: &TalkSpec) -> Vec<Value> {
        // absent-ok: a mode of no history has no earlier turns.
        let earlier = usize::try_from(spec.turns - 1).unwrap_or(0);
        let start = ask.history.len().saturating_sub(earlier);
        let said = ask.history.iter().skip(if earlier == 0 { ask.history.len() } else { start }).map(|turn| {
            if turn.role == "assistant" {
                json!({"role": "assistant", "content": turn.text})
            } else {
                self.user(&turn.audio, &turn.text)
            }
        });
        let system = ask.system.as_deref().unwrap_or(spec.system);
        let mut out = Vec::new();
        if !system.is_empty() {
            out.push(json!({"role": "system", "content": system}));
        }
        out.extend(said);
        out.push(self.user(&ask.audio, &ask.text));
        out
    }

    /// `(body, content type)` of the request for `ask`.
    pub(super) fn request(&self, ask: &TalkAsk, spec: &TalkSpec) -> Result<(Vec<u8>, String), AppError> {
        match self.kind {
            ModeKind::Chat | ModeKind::TextChat => {
                let mut messages = self.messages(ask, spec);
                let mut doc = Map::new();
                if !self.modalities.is_empty() && !spec.answer_cue.is_empty() {
                    messages.push(json!({"role": "assistant", "content": spec.answer_cue}));
                }
                doc.insert("messages".to_string(), Value::Array(messages));
                if !self.modalities.is_empty() {
                    doc.insert("modalities".to_string(), json!(self.modalities));
                    if !spec.answer_cue.is_empty() {
                        doc.insert("continue_final_message".to_string(), json!(true));
                        doc.insert("add_generation_prompt".to_string(), json!(false));
                    }
                }
                doc.extend(self.voice_field(ask, spec, spec.voice_field));
                Ok((PythonJson::spaced(&Value::Object(doc)).into_bytes(), "application/json".to_string()))
            }
            ModeKind::Speech => {
                let mut doc = Map::new();
                doc.insert("input".to_string(), json!(ask.text));
                doc.insert("response_format".to_string(), json!("wav"));
                if ask.sample.is_empty() {
                    doc.extend(self.voice_field(ask, spec, "voice"));
                } else {
                    doc.insert(
                        "ref_audio".to_string(),
                        json!(format!("data:audio/wav;base64,{}", Base64Std::encode(&ask.sample))),
                    );
                    if ask.sample_text.is_empty() {
                        doc.insert("x_vector_only_mode".to_string(), json!(true));
                    } else {
                        doc.insert("ref_text".to_string(), json!(ask.sample_text));
                    }
                }
                Ok((PythonJson::spaced(&Value::Object(doc)).into_bytes(), "application/json".to_string()))
            }
            ModeKind::Transcription => {
                let mut form = FormBody::default();
                form.field("response_format", "json")?;
                form.file("file", "talk.wav", "audio/wav", &ask.audio)?;
                Ok(form.done())
            }
        }
    }

    pub(super) fn words(content: Option<&Value>) -> String {
        match content {
            Some(Value::String(text)) => text.clone(),
            Some(Value::Array(parts)) => parts
                .iter()
                .filter(|part| part.get("type").and_then(Value::as_str) == Some("text"))
                .map(|part| Coerce::text(part.get("text")))
                .collect(),
            _ => String::new(),
        }
    }

    pub(super) fn chat_answer(ctype: &str, raw: &[u8], spec: &TalkSpec) -> Map<String, Value> {
        let doc: Value = match std::str::from_utf8(raw).ok().and_then(|text| serde_json::from_str(text).ok()) {
            Some(doc) => doc,
            None => {
                let shown = if ctype.is_empty() { "no type" } else { ctype };
                return Coerce::fields(&json!({"error": format!("the cell answered {shown} that is not JSON")}));
            }
        };
        let (mut text, mut audio, mut kind) = (String::new(), String::new(), String::new());
        for choice in doc.get("choices").and_then(Value::as_array).into_iter().flatten() {
            let Some(message) = choice.get("message").filter(|message| message.is_object()) else {
                continue;
            };
            if text.is_empty() {
                text = Self::words(message.get("content"));
            }
            let voice = message.get("audio").filter(|voice| voice.is_object());
            let data = voice.and_then(|voice| voice.get("data")).filter(|data| Coerce::truthy(Some(*data)));
            if let Some(data) = data.filter(|_| audio.is_empty()) {
                audio = Coerce::str_of(Some(data));
                let format = Coerce::text(voice.and_then(|voice| voice.get("format")));
                kind = format!("audio/{}", if format.is_empty() { "wav" } else { &format });
            }
        }
        if !spec.text_noise.is_empty()
            && let Ok(noise) = Regex::new(spec.text_noise)
        {
            text = Coerce::strip(&noise.replace_all(&text, "")).to_string();
        }
        Coerce::fields(&json!({"text": text, "audio": audio, "audioType": kind}))
    }

    /// A count or a speed the server said; nothing for what is no positive number.
    pub(super) fn counted(value: Option<&Value>) -> Option<f64> {
        value.filter(|said| !said.is_boolean()).and_then(Value::as_f64).filter(|said| *said > 0.0)
    }

    pub(super) fn counts(doc: &Value) -> Map<String, Value> {
        let usage = doc.get("usage").filter(|said| said.is_object());
        let timings = doc.get("timings").filter(|said| said.is_object());
        let at = |part: Option<&Value>, key: &str| Self::counted(part.and_then(|part| part.get(key)));
        let tokens = [
            ("read", at(usage, "prompt_tokens").or_else(|| at(timings, "prompt_n"))),
            ("written", at(usage, "completion_tokens").or_else(|| at(timings, "predicted_n"))),
        ];
        let speed = [("read", at(timings, "prompt_per_second")), ("written", at(timings, "predicted_per_second"))];
        let mut out = Map::new();
        let whole: Map<String, Value> =
            tokens.iter().filter_map(|(name, value)| value.map(|value| ((*name).to_string(), json!(value as i64)))).collect();
        if !whole.is_empty() {
            out.insert("tokens".to_string(), Value::Object(whole));
        }
        let rates: Map<String, Value> = speed
            .iter()
            .filter_map(|(name, value)| value.map(|value| ((*name).to_string(), json!(Coerce::rounded(value, 2)))))
            .collect();
        if !rates.is_empty() {
            out.insert("speed".to_string(), Value::Object(rates));
        }
        out
    }

    /// What the cell's answer of 2xx says.
    pub(super) fn answer(&self, ctype: &str, raw: &[u8], spec: &TalkSpec) -> Map<String, Value> {
        match self.kind {
            ModeKind::Chat => Self::chat_answer(ctype, raw, spec),
            ModeKind::TextChat => {
                let mut out = Self::chat_answer(ctype, raw, spec);
                if !out.contains_key("error")
                    && let Ok(doc) = serde_json::from_slice::<Value>(raw)
                {
                    out.extend(Self::counts(&doc));
                }
                out
            }
            ModeKind::Speech => {
                if !ctype.to_lowercase().starts_with("audio/") {
                    let said: String = String::from_utf8_lossy(raw).chars().take(CellTalk::REFUSAL_SHOWN).collect();
                    let shown = if ctype.is_empty() { "no type" } else { ctype };
                    let error = format!("the cell answered {shown} where a voice was asked: {said}");
                    return Coerce::fields(&json!({"error": error.trim_end_matches([':', ' '])}));
                }
                let kind = Coerce::strip(ctype.split(';').next().unwrap_or(ctype));
                Coerce::fields(&json!({"text": "", "audio": Base64Std::encode(raw), "audioType": kind}))
            }
            ModeKind::Transcription => {
                let text = String::from_utf8_lossy(raw).into_owned();
                let said = match serde_json::from_str::<Value>(&text) {
                    Ok(doc) => Coerce::text(doc.get("text")),
                    Err(_) => text,
                };
                Coerce::fields(&json!({"text": said, "audio": "", "audioType": ""}))
            }
        }
    }
}
