//! Chat completion chunks folded into the one chat completion they stream.
//!
//! A client that did not ask for a stream reads one JSON answer, while a provider may stream regardless: the Codex backend always does.

use crate::coerce::Coerce;
use serde_json::{Map, Value, json};
use std::collections::BTreeMap;

/// One tool call as far as it has come.
#[derive(Debug, Clone)]
struct HeldCall {
    id: String,
    kind: String,
    name: String,
    arguments: String,
}

impl Default for HeldCall {
    fn default() -> Self {
        Self { id: String::new(), kind: "function".to_string(), name: String::new(), arguments: String::new() }
    }
}

/// One choice as far as it has come.
#[derive(Debug, Clone, Default)]
struct Slot {
    role: String,
    text: String,
    calls: BTreeMap<i64, HeldCall>,
    finish: Option<String>,
}

/// The stream so far.
#[derive(Debug, Clone, Default)]
pub struct ChunkFold {
    id: Option<Value>,
    created: Option<Value>,
    model: Option<Value>,
    choices: BTreeMap<i64, Slot>,
    usage: Option<Value>,
}

impl ChunkFold {
    /// Takes one piece of the stream: `data: {…}` lines; `[DONE]` and anything else pass.
    pub fn add(&mut self, chunk: &[u8]) {
        for line in String::from_utf8_lossy(chunk).lines() {
            let Some(data) = line.strip_prefix("data:") else {
                continue;
            };
            let data = Coerce::strip(data);
            if data.is_empty() || data == "[DONE]" {
                continue;
            }
            if let Ok(event @ Value::Object(_)) = serde_json::from_str::<Value>(data) {
                self.event(&event);
            }
        }
    }

    fn event(&mut self, event: &Value) {
        let keep = |held: &mut Option<Value>, name: &str| {
            if held.is_none() {
                *held = event.get(name).cloned();
            }
        };
        keep(&mut self.id, "id");
        keep(&mut self.created, "created");
        keep(&mut self.model, "model");
        if let Some(usage) = event.get("usage").filter(|usage| usage.is_object()) {
            self.usage = Some(usage.clone());
        }
        for choice in event.get("choices").and_then(Value::as_array).into_iter().flatten().filter(|choice| choice.is_object()) {
            // absent-ok: `int(choice.get("index") or 0)`: a choice that names no index is the first.
            let slot = self.choices.entry(Coerce::int_or_zero(choice.get("index")).unwrap_or(0)).or_default();
            Self::choice(slot, choice);
        }
    }

    fn choice(slot: &mut Slot, choice: &Value) {
        if let Some(delta) = choice.get("delta").filter(|delta| delta.is_object()) {
            if Coerce::truthy(delta.get("role")) {
                slot.role = Coerce::text(delta.get("role"));
            }
            if let Some(text) = delta.get("content").and_then(Value::as_str) {
                slot.text.push_str(text);
            }
            for call in delta.get("tool_calls").and_then(Value::as_array).into_iter().flatten().filter(|call| call.is_object()) {
                Self::call(&mut slot.calls, call);
            }
        }
        if Coerce::truthy(choice.get("finish_reason")) {
            slot.finish = Some(Coerce::text(choice.get("finish_reason")));
        }
    }

    fn call(calls: &mut BTreeMap<i64, HeldCall>, part: &Value) {
        // absent-ok: `int(part.get("index") or 0)`: a part that names no index is the first call's.
        let held = calls.entry(Coerce::int_or_zero(part.get("index")).unwrap_or(0)).or_default();
        if Coerce::truthy(part.get("id")) {
            held.id = Coerce::text(part.get("id"));
        }
        if Coerce::truthy(part.get("type")) {
            held.kind = Coerce::text(part.get("type"));
        }
        if let Some(function) = part.get("function").filter(|function| function.is_object()) {
            if Coerce::truthy(function.get("name")) {
                held.name.push_str(&Coerce::text(function.get("name")));
            }
            if let Some(arguments) = function.get("arguments").and_then(Value::as_str) {
                held.arguments.push_str(arguments);
            }
        }
    }

    /// Whether any choice got its finish reason: a stream cut before its last word is no whole answer, and must not be handed out as one.
    pub fn finished(&self) -> bool {
        self.choices.values().any(|slot| slot.finish.is_some())
    }

    /// The answer as OpenAI's chat completion object. A message with tool calls and no text has `content: null`, as OpenAI's has.
    pub fn completion(&self) -> Value {
        let choices: Vec<Value> = self.choices.iter().map(|(index, slot)| Self::completed(*index, slot)).collect();
        let mut out = Map::new();
        out.insert("id".to_string(), self.id.clone().unwrap_or_else(|| json!("")));
        out.insert("object".to_string(), json!("chat.completion"));
        out.insert("created".to_string(), self.created.clone().unwrap_or_else(|| json!(0)));
        out.insert("model".to_string(), self.model.clone().unwrap_or_else(|| json!("")));
        out.insert("choices".to_string(), Value::Array(choices));
        if let Some(usage) = &self.usage {
            out.insert("usage".to_string(), usage.clone());
        }
        Value::Object(out)
    }

    fn completed(index: i64, slot: &Slot) -> Value {
        let calls: Vec<Value> = slot
            .calls
            .values()
            .map(|call| json!({"id": call.id, "type": call.kind, "function": {"name": call.name, "arguments": call.arguments}}))
            .collect();
        let mut message = Map::new();
        message.insert("role".to_string(), json!(if slot.role.is_empty() { "assistant" } else { slot.role.as_str() }));
        message.insert(
            "content".to_string(),
            if slot.text.is_empty() && !calls.is_empty() { Value::Null } else { json!(slot.text) },
        );
        if !calls.is_empty() {
            message.insert("tool_calls".to_string(), Value::Array(calls));
        }
        json!({"index": index, "message": message, "logprobs": null, "finish_reason": slot.finish.as_deref().unwrap_or("stop")})
    }
}
