//! An Anthropic answer on its way back as a chat completion.

use crate::coerce::Coerce;
use crate::python_json::PythonJson;
use crate::responses_stream::StreamTranslator;
use serde_json::{Map, Value, json};

/// What an Anthropic response says it used, gathered from where it says it. The counts are cumulative, so a figure is taken only by being
/// larger than the one before: a delta that repeats the input does not add it twice.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct AnthropicUsage {
    input: i64,
    cache_creation: i64,
    cache_read: i64,
    output: i64,
}

impl AnthropicUsage {
    /// A token count as a whole number; 0 for what is no count.
    fn count(value: Option<&Value>) -> i64 {
        // absent-ok: a figure that is no count adds nothing, and a count is what is compared here.
        value.filter(|value| !value.is_boolean()).and_then(Coerce::int).unwrap_or(0).max(0)
    }

    /// Folds one usage object in.
    pub fn take(&mut self, usage: Option<&Value>) {
        let said = |name: &str| Self::count(usage.and_then(|usage| usage.get(name)));
        self.input = self.input.max(said("input_tokens"));
        self.cache_creation = self.cache_creation.max(said("cache_creation_input_tokens"));
        self.cache_read = self.cache_read.max(said("cache_read_input_tokens"));
        self.output = self.output.max(said("output_tokens"));
    }

    fn prompt(&self) -> i64 {
        self.input + self.cache_creation + self.cache_read
    }

    /// Whether it has said anything.
    pub fn known(&self) -> bool {
        self.prompt() > 0 || self.output > 0
    }

    /// The usage as OpenAI's chat completion says it: all the input as `prompt_tokens`, the cached part and the part written named.
    pub fn openai(&self) -> Value {
        let mut out = Map::new();
        out.insert("prompt_tokens".to_string(), json!(self.prompt()));
        out.insert("completion_tokens".to_string(), json!(self.output));
        out.insert("total_tokens".to_string(), json!(self.prompt() + self.output));
        if self.cache_read > 0 {
            out.insert("prompt_tokens_details".to_string(), json!({"cached_tokens": self.cache_read}));
        }
        if self.cache_creation > 0 {
            out.insert("cache_creation_input_tokens".to_string(), json!(self.cache_creation));
        }
        Value::Object(out)
    }
}

/// What one Messages event says. Read here once, because two readers need the same words: this translation turns the event into a chunk,
/// and the journal's fold (`StreamFold`) counts what the event said without turning it into anything — a client that speaks the Messages
/// API gets the stream as it came, so the fold reads this shape as it is, not as a chat choice.
pub(crate) struct MessagesWords;

impl MessagesWords {
    /// The text an event says the answer grew by: a text block's delta. A tool argument being built (`input_json_delta`) is no text said,
    /// so it adds no letters to the journal's count.
    pub(crate) fn text_of(event: &Value) -> Option<&Value> {
        event
            .get("delta")
            .filter(|delta| delta.get("type").and_then(Value::as_str) == Some("text_delta"))
            .and_then(|delta| delta.get("text"))
    }

    /// The word an event says the answer ends with, as the provider said it. This translation's own Chat word for `tool_use` is a
    /// different fact, and it stays in `AnthropicToChat::message_delta`.
    pub(crate) fn stop_reason_of(event: &Value) -> Option<&Value> {
        event.get("delta").and_then(|delta| delta.get("stop_reason"))
    }

    /// Where an event says usage: on itself, or on the message it opens with.
    pub(crate) fn usage_of(event: &Value) -> Option<&Value> {
        event.get("usage").or_else(|| event.get("message").and_then(|message| message.get("usage")))
    }

    /// The model an event names: on itself, or on the message it opens with.
    pub(crate) fn model_of(event: &Value) -> Option<&Value> {
        event.get("model").or_else(|| event.get("message").and_then(|message| message.get("model")))
    }

    /// Whether the event is the provider's own word that the stream is complete. `[DONE]` is the end the caravan writes for its own
    /// client, never what a Messages stream says.
    pub(crate) fn says_the_end(event: &Value) -> bool {
        event.get("type").and_then(Value::as_str) == Some("message_stop")
    }
}

/// An Anthropic stream as Chat Completions chunks, a line at a time.
#[derive(Debug, Clone)]
pub struct AnthropicToChat {
    completion_id: String,
    model: String,
    created: i64,
    call_indexes: Vec<(i64, i64)>,
    calls: i64,
    finish_reason: &'static str,
    pending_event: Option<String>,
    used: AnthropicUsage,
    ended: bool,
}

impl AnthropicToChat {
    const THE_END: &'static [u8] = b"data: [DONE]\n\n";

    /// The translation of one answer: the chunks' id, model and time.
    pub fn new(completion_id: &str, model: &str, created: i64) -> Self {
        Self {
            completion_id: completion_id.to_string(),
            model: model.to_string(),
            created,
            call_indexes: Vec::new(),
            calls: 0,
            finish_reason: "stop",
            pending_event: None,
            used: AnthropicUsage::default(),
            ended: false,
        }
    }

    /// What the answer has said it used so far: a stream cut before its last chunk is billed all the same.
    pub fn used(&self) -> &AnthropicUsage {
        &self.used
    }

    fn chunk(&self, delta: &Value, finish_reason: Option<&str>) -> Map<String, Value> {
        let mut chunk = Map::new();
        chunk.insert("id".to_string(), json!(self.completion_id));
        chunk.insert("object".to_string(), json!("chat.completion.chunk"));
        chunk.insert("created".to_string(), json!(self.created));
        chunk.insert("model".to_string(), json!(self.model));
        chunk.insert("choices".to_string(), json!([{"index": 0, "delta": delta, "finish_reason": finish_reason}]));
        chunk
    }

    fn framed(chunk: &Map<String, Value>) -> Vec<u8> {
        let mut out = b"data: ".to_vec();
        out.extend_from_slice(PythonJson::compact(&Value::Object(chunk.clone())).as_bytes());
        out.extend_from_slice(b"\n\n");
        out
    }

    fn read_line(&mut self, raw: &[u8]) -> Option<Vec<u8>> {
        let text = String::from_utf8_lossy(raw);
        let line = text.trim_end_matches(['\r', '\n']);
        if let Some(event) = line.strip_prefix("event: ") {
            self.pending_event = Some(event.to_string());
            return None;
        }
        let data = line.strip_prefix("data: ")?;
        if data == "[DONE]" {
            self.ended = true;
            return None;
        }
        let event: Value = serde_json::from_str(data).ok()?;
        let said = event.get("type").and_then(Value::as_str).filter(|word| !word.is_empty()).map(str::to_string);
        let word = said.or_else(|| self.pending_event.clone());
        self.pending_event = None;
        match word?.as_str() {
            "message_start" => {
                self.used.take(MessagesWords::usage_of(&event));
                None
            }
            "content_block_start" => self.block_opened(&event),
            "content_block_delta" => self.block_delta(&event),
            "message_delta" => Some(self.message_delta(&event)),
            "message_stop" => {
                self.ended = true;
                None
            }
            _ => None,
        }
    }

    fn block_opened(&mut self, event: &Value) -> Option<Vec<u8>> {
        let block = event.get("content_block")?;
        if block.get("type").and_then(Value::as_str) != Some("tool_use") {
            return None;
        }
        // absent-ok: `ev.get("index", 0)`.
        let at = event.get("index").and_then(Value::as_i64).unwrap_or(0);
        let index = self.calls;
        self.calls += 1;
        self.call_indexes.retain(|(block_at, _)| *block_at != at);
        self.call_indexes.push((at, index));
        let id = block.get("id").cloned().unwrap_or_else(|| json!(""));
        let name = block.get("name").cloned().unwrap_or_else(|| json!(""));
        let delta =
            json!({"tool_calls": [{"index": index, "id": id, "type": "function", "function": {"name": name, "arguments": ""}}]});
        Some(Self::framed(&self.chunk(&delta, None)))
    }

    fn block_delta(&self, event: &Value) -> Option<Vec<u8>> {
        let delta = event.get("delta")?;
        match delta.get("type").and_then(Value::as_str)? {
            "text_delta" => {
                // absent-ok: a text delta that names no text says an empty piece: the client is reading the block as it is told.
                let text = MessagesWords::text_of(event).cloned().unwrap_or_else(|| json!(""));
                Some(Self::framed(&self.chunk(&json!({"content": text}), None)))
            }
            "input_json_delta" => {
                // absent-ok: `ev.get("index", 0)`.
                let at = event.get("index").and_then(Value::as_i64).unwrap_or(0);
                // absent-ok: a delta of a block that never opened goes to the first call.
                let index = self.call_indexes.iter().find(|(block_at, _)| *block_at == at).map_or(0, |(_, index)| *index);
                let partial = delta.get("partial_json").cloned().unwrap_or_else(|| json!(""));
                Some(Self::framed(
                    &self.chunk(&json!({"tool_calls": [{"index": index, "function": {"arguments": partial}}]}), None),
                ))
            }
            _ => None,
        }
    }

    fn message_delta(&mut self, event: &Value) -> Vec<u8> {
        if MessagesWords::stop_reason_of(event).and_then(Value::as_str) == Some("tool_use") {
            self.finish_reason = "tool_calls";
        }
        self.used.take(MessagesWords::usage_of(event));
        let mut last = self.chunk(&json!({}), Some(self.finish_reason));
        if self.used.known() {
            last.insert("usage".to_string(), self.used.openai());
        }
        Self::framed(&last)
    }

    /// A whole Messages response as OpenAI's chat completion. One that is no JSON goes as it came.
    pub fn whole(data: &[u8], completion_id: &str, model: &str, created: i64) -> Vec<u8> {
        let Ok(response) = serde_json::from_slice::<Value>(data) else {
            return data.to_vec();
        };
        let mut texts = Vec::new();
        let mut calls = Vec::new();
        for block in response.get("content").and_then(Value::as_array).into_iter().flatten() {
            match block.get("type").and_then(Value::as_str) {
                // absent-ok: `block.get("text", "")`.
                Some("text") => texts.push(block.get("text").and_then(Value::as_str).unwrap_or_default()),
                Some("tool_use") => {
                    let input =
                        block.get("input").filter(|input| Coerce::truthy(Some(*input))).cloned().unwrap_or_else(|| json!({}));
                    let id = block.get("id").cloned().unwrap_or_else(|| json!(""));
                    let name = block.get("name").cloned().unwrap_or_else(|| json!(""));
                    calls.push(json!({"id": id, "type": "function", "function": {"name": name, "arguments": PythonJson::spaced(&input)}}));
                }
                _ => {}
            }
        }
        let finish = if calls.is_empty() { "stop" } else { "tool_calls" };
        let mut message = Map::new();
        message.insert("role".to_string(), json!("assistant"));
        message.insert("content".to_string(), json!(texts.join("\n")));
        if !calls.is_empty() {
            message.insert("tool_calls".to_string(), Value::Array(calls));
        }
        let mut used = AnthropicUsage::default();
        used.take(response.get("usage"));
        let result = json!({
            "id": completion_id, "object": "chat.completion", "created": created, "model": model,
            "choices": [{"index": 0, "message": message, "finish_reason": finish}],
            "usage": used.openai(),
        });
        PythonJson::spaced_letters(&result).into_bytes()
    }
}

impl StreamTranslator for AnthropicToChat {
    fn opening(&self) -> Vec<u8> {
        Self::framed(&self.chunk(&json!({"role": "assistant", "content": ""}), None))
    }

    fn line(&mut self, raw: &[u8]) -> Option<Vec<u8>> {
        self.read_line(raw)
    }

    fn closing(&self) -> &'static [u8] {
        Self::THE_END
    }

    fn ended(&self) -> bool {
        self.ended
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_figure_that_is_no_count_adds_nothing_and_a_smaller_one_takes_nothing_back() {
        let mut used = AnthropicUsage::default();
        assert!(!used.known());
        used.take(Some(&json!({"input_tokens": "7", "output_tokens": true, "cache_read_input_tokens": -3, "cache_creation_input_tokens": "x"})));
        assert_eq!(used.openai(), json!({"prompt_tokens": 7, "completion_tokens": 0, "total_tokens": 7}));
        used.take(Some(&json!({"input_tokens": 2, "output_tokens": 5.9})));
        assert_eq!(used.openai(), json!({"prompt_tokens": 7, "completion_tokens": 5, "total_tokens": 12}));
        assert!(used.known());
    }
}
