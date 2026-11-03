//! What the journal keeps of a request and an answer.

use crate::coerce::Coerce;
use crate::request_json::RequestJson;
use serde_json::{Map, Value, json};

/// The compact picture of a request: its size, its model, its roles, the end of its last text.
pub struct RequestSummary;

impl RequestSummary {
    /// The longest preview of a text.
    const PREVIEW: usize = 180;

    /// A text on one line, cut to its preview.
    fn compact(text: &str) -> String {
        let flat = text.replace(['\n', '\r'], " ");
        let flat = Coerce::strip(&flat);
        if flat.chars().count() > Self::PREVIEW {
            return format!("{}...", Coerce::first_letters(flat, Self::PREVIEW).trim_end());
        }
        flat.to_string()
    }

    /// The summary of `body` as `content_type` says it travels. Only the JSON part is read; a body that is not JSON
    /// gets its type and its length. A body that claims JSON and does not read says so under `parseError`.
    pub fn of(body: &[u8], content_type: &str) -> Value {
        let mut summary = Map::new();
        summary.insert("contentType".into(), json!(content_type));
        summary.insert("contentLength".into(), json!(body.len()));
        if body.is_empty() || !content_type.to_lowercase().contains("json") {
            return Value::Object(summary);
        }
        let Some(payload) = RequestJson::read(body) else {
            // The words are the library's.
            let words = serde_json::from_slice::<Value>(body).err().map(|error| error.to_string());
            summary.insert("parseError".into(), json!(words));
            return Value::Object(summary);
        };
        if !payload.is_object() {
            return Value::Object(summary);
        }
        Self::read_payload(&payload, &mut summary);
        summary.retain(|_, value| !Self::is_nothing(value));
        Value::Object(summary)
    }

    /// `value not in (None, "", [])`.
    fn is_nothing(value: &Value) -> bool {
        match value {
            Value::Null => true,
            Value::String(text) => text.is_empty(),
            Value::Array(items) => items.is_empty(),
            _ => false,
        }
    }

    /// The messages, or a Responses-API `input` read the same way: a list of items of the same shape, or a bare string
    /// standing for one user turn.
    fn messages(payload: &Value) -> Vec<Value> {
        let listed = payload.get("messages").and_then(Value::as_array).filter(|items| !items.is_empty());
        if let Some(items) = listed {
            return items.clone();
        }
        match payload.get("input") {
            Some(Value::Array(items)) => {
                items.iter().filter(|item| item.get("role").is_some() && item.is_object()).cloned().collect()
            }
            Some(Value::String(text)) => vec![json!({"role": "user", "content": text})],
            _ => Vec::new(),
        }
    }

    fn read_payload(payload: &Value, summary: &mut Map<String, Value>) {
        let messages = Self::messages(payload);
        let mut fold = ContentFold::default();
        for message in messages.iter().filter(|message| message.is_object()) {
            fold.add_message(message);
        }
        let first_of = |names: [&str; 3]| {
            names.iter().filter_map(|name| payload.get(*name)).find(|value| Coerce::truthy(Some(*value))).cloned()
        };
        let plain = |name: &str| payload.get(name).cloned().unwrap_or(Value::Null);
        summary.insert("model".into(), plain("model"));
        summary.insert("stream".into(), plain("stream"));
        summary.insert("maxTokens".into(), first_of(["max_tokens", "max_completion_tokens", "n_predict"]).unwrap_or(Value::Null));
        summary.insert("temperature".into(), plain("temperature"));
        summary.insert("topP".into(), plain("top_p"));
        summary.insert("messages".into(), json!(messages.len()));
        summary.insert("roles".into(), json!(fold.roles));
        summary.insert("promptTextChars".into(), json!(fold.text_chars));
        summary.insert("imageParts".into(), json!(fold.image_parts));
        // absent-ok: `len(x) if isinstance(x, list) else 0`: no list of tools is no tool.
        summary.insert("tools".into(), json!(payload.get("tools").and_then(Value::as_array).map_or(0, Vec::len)));
        summary.insert("lastTextPreview".into(), json!(Self::compact(&fold.last_text)));
    }
}

/// What a request's messages add up to.
#[derive(Default)]
struct ContentFold {
    roles: Vec<String>,
    text_chars: usize,
    image_parts: usize,
    last_text: String,
}

impl ContentFold {
    fn add_message(&mut self, message: &Value) {
        let role = Coerce::text(message.get("role"));
        if !role.is_empty() && !self.roles.contains(&role) {
            self.roles.push(role);
        }
        match message.get("content") {
            Some(Value::String(text)) => self.add_text(text),
            Some(Value::Array(parts)) => parts.iter().filter(|part| part.is_object()).for_each(|part| self.add_part(part)),
            _ => {}
        }
    }

    fn add_text(&mut self, text: &str) {
        self.text_chars += text.chars().count();
        self.last_text = text.to_string();
    }

    fn add_part(&mut self, part: &Value) {
        let kind = Coerce::text(part.get("type"));
        if kind == "text" || kind == "input_text" {
            self.add_text(&Coerce::text(part.get("text")));
        } else if kind.contains("image") || Coerce::truthy(part.get("image_url")) {
            self.image_parts += 1;
        }
    }
}

/// The compact picture of a whole JSON answer.
pub struct ResponseSummary;

/// What the journal keeps of a body on its way to a provider: `cloudMeta`.
pub struct ProviderBodyWords;

impl ProviderBodyWords {
    /// The body's model and its counts. A body that is no JSON object, or a count that is no length (`len(1)` raises), is kept as nothing.
    pub fn of(body: &[u8]) -> Option<Value> {
        let payload = RequestJson::read(body)?;
        let fields = payload.as_object()?;
        let said = |name: &str| fields.get(name).filter(|value| Coerce::truthy(Some(*value)));
        let model = said("model").cloned().unwrap_or_else(|| json!(""));
        let tools = Self::length(said("tools"))?;
        let inputs = Self::length(said("input").or_else(|| said("messages")))?;
        Some(json!({"model": model, "toolCount": tools, "inputCount": inputs}))
    }

    /// `len(value or [])`.
    fn length(value: Option<&Value>) -> Option<usize> {
        match value {
            None => Some(0),
            Some(Value::Array(items)) => Some(items.len()),
            Some(Value::Object(fields)) => Some(fields.len()),
            Some(Value::String(text)) => Some(text.chars().count()),
            Some(_) => None,
        }
    }
}

impl ResponseSummary {
    /// The summary of `payload`; `{}` for anything but an object.
    pub fn of(payload: &Value) -> Value {
        if !payload.is_object() {
            return json!({});
        }
        let empty = Vec::new();
        let choices = payload.get("choices").and_then(Value::as_array).unwrap_or(&empty);
        let reasons: Vec<&Value> = choices
            .iter()
            .filter_map(|choice| choice.get("finish_reason"))
            .filter(|reason| Coerce::truthy(Some(*reason)))
            .collect();
        let object_or_empty =
            |name: &str| payload.get(name).filter(|value| value.is_object()).cloned().unwrap_or_else(|| json!({}));
        json!({
            "id": payload.get("id"),
            "model": payload.get("model"),
            "object": payload.get("object"),
            "usage": object_or_empty("usage"),
            "timings": object_or_empty("timings"),
            "choices": choices.len(),
            "finishReasons": reasons,
        })
    }
}

/// What an event stream has said so far: the `stream` of a request's record. Fed line by line while the stream is relayed.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct StreamFold {
    /// `data:` lines seen.
    pub events: u64,
    /// Letters of generated text.
    pub delta_text_chars: u64,
    /// The latest chunk's finish reasons.
    pub finish_reasons: Vec<Value>,
    /// The latest usage a chunk carried.
    pub usage: Option<Value>,
    /// The latest timings a chunk carried: llama.cpp puts exact ones in its final chunk.
    pub timings: Option<Value>,
    /// The model the stream names.
    pub model: Option<Value>,
    /// Whether `[DONE]` came.
    pub done: bool,
}

impl StreamFold {
    /// One line of the stream; a line that is not an event changes nothing.
    pub fn add_line(&mut self, line: &[u8]) {
        let Some(rest) = line.strip_prefix(b"data:") else {
            return;
        };
        self.events += 1;
        let data = rest.trim_ascii();
        if data.is_empty() {
            return;
        }
        if data == b"[DONE]" {
            self.done = true;
            return;
        }
        if let Ok(payload) = serde_json::from_slice::<Value>(data)
            && payload.is_object()
        {
            self.add_payload(&payload);
        }
    }

    /// One chunk a translation made: its own chunk's model and timings are no provider's word.
    pub fn add_translated(&mut self, chunk: &[u8]) {
        if chunk.starts_with(b"data:") {
            self.add_line(chunk);
            self.model = None;
            self.timings = None;
        }
    }

    /// What a relayed Responses stream said.
    pub fn take_tally(&mut self, tally: &crate::responses_stream::ResponsesTally) {
        self.events = tally.events;
        self.delta_text_chars = tally.delta_text_chars;
        if tally.usage.is_some() {
            self.usage.clone_from(&tally.usage);
        }
        if !tally.finish_reasons.is_empty() {
            self.finish_reasons = tally.finish_reasons.iter().map(|reason| json!(reason)).collect();
        }
        self.done = self.done || tally.done;
    }

    fn add_payload(&mut self, payload: &Value) {
        let mut reasons = Vec::new();
        for choice in payload.get("choices").and_then(Value::as_array).into_iter().flatten().filter(|choice| choice.is_object()) {
            self.delta_text_chars += Self::text_letters(choice);
            if let Some(reason) = choice.get("finish_reason").filter(|reason| Coerce::truthy(Some(*reason))) {
                reasons.push(reason.clone());
            }
        }
        if !reasons.is_empty() {
            self.finish_reasons = reasons;
        }
        Self::keep_filled(&mut self.usage, payload.get("usage"));
        Self::keep_filled(&mut self.timings, payload.get("timings"));
        if let Some(model) = payload.get("model").filter(|model| Coerce::truthy(Some(*model))) {
            self.model = Some(model.clone());
        }
    }

    /// `len(str(delta.content or choice.text or ""))`.
    fn text_letters(choice: &Value) -> u64 {
        let delta = choice.get("delta").filter(|delta| delta.is_object());
        let said = delta.and_then(|delta| delta.get("content")).filter(|content| Coerce::truthy(Some(*content)));
        Coerce::text(said.or(choice.get("text"))).chars().count() as u64
    }

    fn keep_filled(kept: &mut Option<Value>, said: Option<&Value>) {
        if let Some(value) = said.filter(|value| value.as_object().is_some_and(|fields| !fields.is_empty())) {
            *kept = Some(value.clone());
        }
    }

    /// The fold as the record's `stream`; `{}` when no event came, as the finished record says it.
    pub fn as_json(&self) -> Value {
        if self.events == 0 {
            return json!({});
        }
        self.live_json()
    }

    /// The fold as a running request's `stream`.
    pub fn live_json(&self) -> Value {
        let mut out = json!({
            "events": self.events,
            "deltaTextChars": self.delta_text_chars,
            "finishReasons": self.finish_reasons,
            "usage": self.usage.clone().unwrap_or_else(|| json!({})),
            "done": self.done,
        });
        if let Some(fields) = out.as_object_mut() {
            if let Some(timings) = &self.timings {
                fields.insert("timings".into(), timings.clone());
            }
            if let Some(model) = &self.model {
                fields.insert("model".into(), model.clone());
            }
        }
        out
    }
}

/// A request's tokens as the journal keeps them: the block of `proxy()` that the spend meter
/// and the token history read.
pub struct UsageWords;

impl UsageWords {
    /// A count of tokens as the record keeps it: a number, always.
    fn tokens(said: Option<&Value>) -> i64 {
        // absent-ok: the record's field and the spend meter read a number; not said is no tokens said, as `x or 0` has it.
        Coerce::int_or_zero(said).unwrap_or(0)
    }

    /// The record's `usage` from what an answer said, OpenAI's words or Anthropic's: `prompt` and `completion`, and the cached
    /// part of the prompt and the part written to the cache only when there is one, so a row of no cache stays as it was.
    pub fn of(said: Option<&Value>) -> Value {
        let empty = json!({});
        let said = said.unwrap_or(&empty);
        let count = |first: &str, second: &str| -> i64 {
            let filled = said.get(first).filter(|value| Coerce::truthy(Some(*value))).or(said.get(second));
            Self::tokens(filled)
        };
        let mut out = Map::new();
        out.insert("prompt".into(), json!(count("prompt_tokens", "input_tokens")));
        out.insert("completion".into(), json!(count("completion_tokens", "output_tokens")));
        let details = said.get("prompt_tokens_details").filter(|details| details.is_object());
        let cached = details.and_then(|details| details.get("cached_tokens")).filter(|value| Coerce::truthy(Some(*value)));
        let cached = Self::tokens(cached.or(said.get("cache_read_input_tokens")));
        let written = Self::tokens(said.get("cache_creation_input_tokens"));
        if cached > 0 {
            out.insert("cacheRead".into(), json!(cached));
        }
        if written > 0 {
            out.insert("cacheWrite".into(), json!(written));
        }
        Value::Object(out)
    }
}
