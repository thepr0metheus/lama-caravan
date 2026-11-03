//! A Responses API stream on its way back: relayed as it is and tallied for the journal, or translated into chat completion chunks.
//!
//! What a provider sends that is not the shape it should be reads as nothing here: a stream does not stop for a field nobody reads.

use crate::coerce::Coerce;
use crate::python_json::PythonJson;
use serde_json::{Map, Value, json};

/// What a relayed Responses stream said, kept for the journal.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct ResponsesTally {
    /// Events seen.
    pub events: u64,
    /// Letters of text in them.
    pub delta_text_chars: u64,
    delta_seen: bool,
    /// The usage the last one said, in Chat Completions' words.
    pub usage: Option<Value>,
    /// How the answer ended.
    pub finish_reasons: Vec<String>,
    /// Whether `response.completed` came.
    pub done: bool,
    /// The final `response` object, when a client wants it whole.
    pub response: Option<Value>,
    done_items: Vec<Value>,
}

impl ResponsesTally {
    /// What it has come to, in the words of the journal's `stream`. A count nobody added to is not there.
    pub fn as_summary(&self) -> Value {
        let mut out = Map::new();
        if self.events > 0 {
            out.insert("events".to_string(), json!(self.events));
        }
        if self.delta_seen {
            out.insert("deltaTextChars".to_string(), json!(self.delta_text_chars));
        }
        if let Some(usage) = &self.usage {
            out.insert("usage".to_string(), usage.clone());
        }
        if !self.finish_reasons.is_empty() {
            out.insert("finishReasons".to_string(), json!(self.finish_reasons));
        }
        if self.done {
            out.insert("done".to_string(), json!(true));
        }
        if let Some(response) = &self.response {
            out.insert("response".to_string(), response.clone());
        }
        Value::Object(out)
    }

    /// Takes one line of the stream.
    pub fn line(&mut self, raw: &[u8]) {
        let text = String::from_utf8_lossy(raw);
        let Some(data) = Coerce::strip(&text).strip_prefix("data: ") else {
            return;
        };
        let Ok(event) = serde_json::from_str::<Value>(data) else {
            return;
        };
        self.events += 1;
        match event.get("type").and_then(Value::as_str) {
            Some("response.output_text.delta") => {
                self.delta_seen = true;
                // absent-ok: a delta that says no text adds no letters.
                self.delta_text_chars +=
                    // absent-ok: a delta that says no text adds no letters.
                    event.get("delta").and_then(Value::as_str).map_or(0, |delta| delta.chars().count() as u64);
            }
            Some("response.output_item.done") => {
                if let Some(item) = event.get("item").filter(|item| item.is_object()) {
                    self.done_items.push(item.clone());
                }
            }
            Some("response.completed") => self.completed(&event),
            _ => {}
        }
    }

    /// The subscription's final response carries no `output`: the items only ever arrive as `output_item.done`, and a client that wants
    /// it whole would get a completed response with nothing in it.
    fn completed(&mut self, event: &Value) {
        let mut response = event.get("response").filter(|response| response.is_object()).cloned().unwrap_or_else(|| json!({}));
        let has_output = Coerce::truthy(response.get("output"));
        if let (false, false, Some(fields)) = (has_output, self.done_items.is_empty(), response.as_object_mut()) {
            fields.insert("output".to_string(), Value::Array(self.done_items.clone()));
        }
        if let Some(usage) = response.get("usage").filter(|usage| Coerce::truthy(Some(*usage))) {
            self.usage = Some(ResponsesWords::usage(usage));
        }
        let called = response.get("output").and_then(Value::as_array).is_some_and(|output| ResponsesWords::has_a_call(output));
        self.finish_reasons = vec![if called { "tool_calls" } else { "stop" }.to_string()];
        self.done = true;
        self.response = Some(response);
    }
}

/// The two things both directions read off a Responses answer.
struct ResponsesWords;

impl ResponsesWords {
    /// A Responses usage in Chat Completions' words.
    fn usage(usage: &Value) -> Value {
        let count = |name: &str| usage.get(name).cloned().unwrap_or_else(|| json!(0));
        // absent-ok: `usage.get("input_tokens", 0)`: a count not said is none.
        let total = count("input_tokens").as_i64().unwrap_or(0) + count("output_tokens").as_i64().unwrap_or(0);
        json!({"prompt_tokens": count("input_tokens"), "completion_tokens": count("output_tokens"), "total_tokens": total})
    }

    fn has_a_call(output: &[Value]) -> bool {
        output.iter().any(|item| item.get("type").and_then(Value::as_str) == Some("function_call"))
    }
}

/// A Responses stream as Chat Completions chunks, a line at a time.
#[derive(Debug, Clone)]
pub struct ResponsesToChat {
    completion_id: String,
    model: String,
    created: i64,
    call_indexes: Vec<(i64, i64)>,
    ended: bool,
}

/// A provider's stream, a line at a time, as Chat Completions chunks.
pub trait StreamTranslator {
    /// The first chunk: the role.
    fn opening(&self) -> Vec<u8>;
    /// What one line of the stream comes to: a chunk, or nothing.
    fn line(&mut self, raw: &[u8]) -> Option<Vec<u8>>;
    /// The last bytes, whatever came before them.
    fn closing(&self) -> &'static [u8];
    /// Whether the stream has said all it will: nothing after this is read.
    fn ended(&self) -> bool;
}

impl ResponsesToChat {
    const THE_END: &'static [u8] = b"data: [DONE]\n\n";

    /// The translation of one answer: the chunks' id, model and time.
    pub fn new(completion_id: &str, model: &str, created: i64) -> Self {
        Self {
            completion_id: completion_id.to_string(),
            model: model.to_string(),
            created,
            call_indexes: Vec::new(),
            ended: false,
        }
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
        let data = text.trim_end_matches(['\r', '\n']).strip_prefix("data: ")?;
        if data == "[DONE]" {
            self.ended = true;
            return None;
        }
        let event: Value = serde_json::from_str(data).ok()?;
        match event.get("type").and_then(Value::as_str)? {
            "response.output_text.delta" => {
                let delta = event.get("delta").cloned().unwrap_or_else(|| json!(""));
                Some(Self::framed(&self.chunk(&json!({"content": delta}), None)))
            }
            "response.output_item.added" => self.call_opened(&event),
            "response.function_call_arguments.delta" => {
                // absent-ok: `ev.get("output_index", 0)`.
                let at = event.get("output_index").and_then(Value::as_i64).unwrap_or(0);
                let index = self.call_indexes.iter().find(|(output, _)| *output == at).map_or(at, |(_, chat)| *chat);
                let arguments = event.get("delta").cloned().unwrap_or_else(|| json!(""));
                let delta = json!({"tool_calls": [{"index": index, "function": {"arguments": arguments}}]});
                Some(Self::framed(&self.chunk(&delta, None)))
            }
            "response.completed" => Some(self.completed(&event)),
            _ => None,
        }
    }

    fn call_opened(&mut self, event: &Value) -> Option<Vec<u8>> {
        let item = event.get("item")?;
        if item.get("type").and_then(Value::as_str) != Some("function_call") {
            return None;
        }
        // absent-ok: `ev.get("output_index", 0)`.
        let at = event.get("output_index").and_then(Value::as_i64).unwrap_or(0);
        let index = self.call_indexes.len() as i64;
        self.call_indexes.retain(|(output, _)| *output != at);
        self.call_indexes.push((at, index));
        let id = item
            .get("call_id")
            .filter(|id| Coerce::truthy(Some(*id)))
            .or_else(|| item.get("id"))
            .cloned()
            .unwrap_or_else(|| json!(""));
        let name = item.get("name").cloned().unwrap_or_else(|| json!(""));
        let delta =
            json!({"tool_calls": [{"index": index, "id": id, "type": "function", "function": {"name": name, "arguments": ""}}]});
        Some(Self::framed(&self.chunk(&delta, None)))
    }

    fn completed(&mut self, event: &Value) -> Vec<u8> {
        self.ended = true;
        let response = event.get("response");
        let output = response.and_then(|response| response.get("output")).and_then(Value::as_array);
        let finish = if output.is_some_and(|output| ResponsesWords::has_a_call(output)) { "tool_calls" } else { "stop" };
        let mut last = self.chunk(&json!({}), Some(finish));
        if let Some(usage) = response.and_then(|response| response.get("usage")).filter(|usage| Coerce::truthy(Some(*usage))) {
            last.insert("usage".to_string(), ResponsesWords::usage(usage));
        }
        Self::framed(&last)
    }
}

impl StreamTranslator for ResponsesToChat {
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
    fn the_stream_of_a_tool_call_keeps_its_own_index() {
        let mut stream = ResponsesToChat::new("c", "m", 1);
        let line = |event: Value| format!("data: {event}\n").into_bytes();
        let opened = stream.line(&line(json!({"type": "response.output_item.added", "output_index": 3, "item": {"type": "function_call", "call_id": "k", "name": "f"}}))).unwrap();
        assert!(String::from_utf8_lossy(&opened).contains(r#""index":0,"id":"k""#));
        let more = stream
            .line(&line(json!({"type": "response.function_call_arguments.delta", "output_index": 3, "delta": "{"})))
            .unwrap();
        assert!(String::from_utf8_lossy(&more).contains(r#"{"index":0,"function":{"arguments":"{"}}"#));
        assert!(
            stream
                .line(&line(json!({"type": "response.output_item.added", "output_index": 4, "item": {"type": "message"}})))
                .is_none()
        );
        assert!(!stream.ended());
        let last = stream.line(&line(json!({"type": "response.completed", "response": {"output": [{"type": "function_call"}], "usage": {"input_tokens": 2, "output_tokens": 3}}}))).unwrap();
        assert!(String::from_utf8_lossy(&last).contains(r#""finish_reason":"tool_calls""#));
        assert!(String::from_utf8_lossy(&last).contains(r#""usage":{"prompt_tokens":2,"completion_tokens":3,"total_tokens":5}"#));
        assert!(stream.ended());
    }
}
