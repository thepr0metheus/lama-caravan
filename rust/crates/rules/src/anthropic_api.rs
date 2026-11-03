//! A chat request said to Anthropic's Messages API.

use crate::coerce::Coerce;
use crate::python_json::PythonJson;
use crate::request_json::RequestJson;
use crate::responses_api::NotAChatRequest;
use serde_json::{Map, Value, json};

/// The model a translated request goes with when nothing names one.
const FALLBACK_MODEL: &str = "claude-opus-4-8";

/// A Chat Completions request as the Messages API takes it.
pub struct ChatToAnthropic;

impl ChatToAnthropic {
    const FALLBACK_TOKENS: i64 = 4096;

    /// The body to send. A body that is no JSON goes as it came.
    pub fn body(body: &[u8], override_model: Option<&str>) -> Result<Vec<u8>, NotAChatRequest> {
        let override_model = override_model.filter(|model| !model.is_empty());
        if body.is_empty() {
            let model = override_model.unwrap_or(FALLBACK_MODEL);
            let minimal = json!({"model": model, "max_tokens": Self::FALLBACK_TOKENS, "messages": []});
            return Ok(minimal.to_string().into_bytes());
        }
        let Some(payload) = RequestJson::read(body) else {
            return Ok(body.to_vec());
        };
        let fields = payload.as_object().ok_or(NotAChatRequest("the request is no JSON object"))?;
        let (system, messages) = Self::messages(fields.get("messages"))?;
        let mut out = Map::new();
        out.insert("model".to_string(), Self::model(fields, override_model));
        out.insert("messages".to_string(), Value::Array(messages));
        out.insert("max_tokens".to_string(), json!(Self::max_tokens(fields)?));
        out.insert("stream".to_string(), json!(fields.get("stream").is_some_and(|stream| Coerce::truthy(Some(stream)))));
        if let Some(system) = system {
            out.insert("system".to_string(), json!(system));
        }
        for name in ["temperature", "top_p"] {
            if let Some(value) = fields.get(name).filter(|value| !value.is_null()) {
                out.insert(name.to_string(), value.clone());
            }
        }
        if let Some(stop) = fields.get("stop").filter(|stop| Coerce::truthy(Some(*stop))) {
            let sequences = if stop.is_string() { json!([stop]) } else { stop.clone() };
            out.insert("stop_sequences".to_string(), sequences);
        }
        let tools: Vec<Value> =
            fields.get("tools").and_then(Value::as_array).into_iter().flatten().filter_map(Self::tool).collect();
        if !tools.is_empty() {
            out.insert("tools".to_string(), Value::Array(tools));
        }
        if let Some(choice) = fields.get("tool_choice").and_then(Self::tool_choice) {
            out.insert("tool_choice".to_string(), choice);
        }
        Ok(Value::Object(out).to_string().into_bytes())
    }

    /// The model it goes with: the row's, the client's, or the fallback; a client's that is no text stays what it is.
    fn model(fields: &Map<String, Value>, override_model: Option<&str>) -> Value {
        match override_model {
            Some(model) => json!(model),
            None => {
                fields.get("model").filter(|model| Coerce::truthy(Some(*model))).cloned().unwrap_or_else(|| json!(FALLBACK_MODEL))
            }
        }
    }

    /// `int(max_tokens or max_completion_tokens or 4096)`.
    fn max_tokens(fields: &Map<String, Value>) -> Result<i64, NotAChatRequest> {
        let said = ["max_tokens", "max_completion_tokens"]
            .iter()
            .find_map(|name| fields.get(*name).filter(|value| Coerce::truthy(Some(*value))));
        match said {
            Some(value) => Coerce::int(value).ok_or(NotAChatRequest("max_tokens is no number")),
            None => Ok(Self::FALLBACK_TOKENS),
        }
    }

    /// (the system's words, the messages). Consecutive tool results go in one user message.
    fn messages(raw: Option<&Value>) -> Result<(Option<String>, Vec<Value>), NotAChatRequest> {
        let empty = Vec::new();
        let list = raw.and_then(Value::as_array).unwrap_or(&empty);
        let mut system = None;
        let mut out = Vec::new();
        let mut at = 0;
        while let Some(message) = list.get(at) {
            let fields = message.as_object().ok_or(NotAChatRequest("a message is no object"))?;
            let content = fields.get("content").filter(|content| Coerce::truthy(Some(*content)));
            at += 1;
            // absent-ok: a message of no role is one nobody knows: passed over.
            match fields.get("role").and_then(Value::as_str).unwrap_or_default() {
                "system" => system = Some(Self::system_text(content)),
                "tool" => {
                    at -= 1;
                    out.push(Self::tool_results(list, &mut at)?);
                }
                "assistant" => out.push(Self::assistant(fields, content)?),
                "user" => out.push(Self::user(content)),
                _ => {}
            }
        }
        Ok((system, out))
    }

    fn system_text(content: Option<&Value>) -> String {
        match content {
            None => String::new(),
            Some(Value::String(text)) => text.clone(),
            Some(other) => {
                let parts = other.as_array().map_or(&[][..], Vec::as_slice);
                let texts: Vec<&str> = parts
                    .iter()
                    .filter(|part| part.get("type").and_then(Value::as_str) == Some("text"))
                    // absent-ok: `p.get("text", "")`: a part of no text says nothing.
                    .map(|part| part.get("text").and_then(Value::as_str).unwrap_or_default())
                    .collect();
                texts.join("\n")
            }
        }
    }

    fn tool_results(list: &[Value], at: &mut usize) -> Result<Value, NotAChatRequest> {
        let mut results = Vec::new();
        while let Some(message) = list.get(*at).filter(|message| message.get("role").and_then(Value::as_str) == Some("tool")) {
            let fields = message.as_object().ok_or(NotAChatRequest("a message is no object"))?;
            let content = fields.get("content").filter(|content| Coerce::truthy(Some(*content)));
            let text = content.map_or_else(String::new, |content| match content {
                Value::String(text) => text.clone(),
                other => PythonJson::spaced(other),
            });
            let id = fields.get("tool_call_id").cloned().unwrap_or_else(|| json!(""));
            results.push(json!({"type": "tool_result", "tool_use_id": id, "content": text}));
            *at += 1;
        }
        Ok(json!({"role": "user", "content": results}))
    }

    /// The text of an odd content: its JSON.
    fn text_of(content: &Value) -> String {
        match content {
            Value::String(text) => text.clone(),
            other => other.to_string(),
        }
    }

    fn assistant(fields: &Map<String, Value>, content: Option<&Value>) -> Result<Value, NotAChatRequest> {
        let calls = fields.get("tool_calls").and_then(Value::as_array).filter(|calls| !calls.is_empty());
        if let Some(calls) = calls {
            let mut blocks = Vec::new();
            if let Some(content) = content {
                blocks.push(json!({"type": "text", "text": Self::text_of(content)}));
            }
            for call in calls {
                blocks.push(Self::tool_use(call)?);
            }
            return Ok(json!({"role": "assistant", "content": blocks}));
        }
        let content = match content {
            None => json!(""),
            Some(Value::Array(parts)) => {
                let blocks: Vec<Value> = parts
                    .iter()
                    .filter(|part| part.get("type").and_then(Value::as_str) == Some("text"))
                    .map(|part| json!({"type": "text", "text": part.get("text").cloned().unwrap_or_else(|| json!(""))}))
                    .collect();
                if blocks.is_empty() { json!(Value::Array(parts.clone()).to_string()) } else { Value::Array(blocks) }
            }
            Some(other) => json!(Self::text_of(other)),
        };
        Ok(json!({"role": "assistant", "content": content}))
    }

    fn tool_use(call: &Value) -> Result<Value, NotAChatRequest> {
        let fields = call.as_object().ok_or(NotAChatRequest("a tool call is no object"))?;
        let function = fields.get("function").and_then(Value::as_object);
        let said = |name: &str| function.and_then(|function| function.get(name));
        let input = match said("arguments") {
            // absent-ok: arguments that are no JSON reach the provider as none.
            Some(Value::String(text)) => serde_json::from_str::<Value>(text).unwrap_or_else(|_| json!({})),
            Some(other) if Coerce::truthy(Some(other)) => other.clone(),
            _ => json!({}),
        };
        let id = fields.get("id").cloned().unwrap_or_else(|| json!(""));
        Ok(json!({"type": "tool_use", "id": id, "name": said("name").cloned().unwrap_or_else(|| json!("")), "input": input}))
    }

    fn user(content: Option<&Value>) -> Value {
        match content {
            None => json!({"role": "user", "content": ""}),
            Some(Value::String(text)) => json!({"role": "user", "content": text}),
            Some(Value::Array(parts)) => {
                let blocks: Vec<Value> = parts.iter().filter_map(Self::user_block).collect();
                json!({"role": "user", "content": blocks})
            }
            Some(other) => json!({"role": "user", "content": other.to_string()}),
        }
    }

    fn user_block(part: &Value) -> Option<Value> {
        match part.get("type").and_then(Value::as_str)? {
            "text" => Some(json!({"type": "text", "text": part.get("text").cloned().unwrap_or_else(|| json!(""))})),
            "image_url" => {
                // absent-ok: an image that names no address is sent as one with an empty address: the provider says what it thinks.
                let url = part.get("image_url").and_then(|image| image.get("url")).and_then(Value::as_str).unwrap_or_default();
                Some(json!({"type": "image", "source": Self::image_source(url)}))
            }
            _ => None,
        }
    }

    fn image_source(url: &str) -> Value {
        if !url.starts_with("data:") {
            return json!({"type": "url", "url": url});
        }
        let read = url.split_once(',').and_then(|(head, data)| {
            let (_, rest) = head.split_once(':')?;
            Some((rest.split(';').next()?.to_string(), data.to_string()))
        });
        let (media_type, data) = read.unwrap_or_else(|| ("image/jpeg".to_string(), String::new()));
        json!({"type": "base64", "media_type": media_type, "data": data})
    }

    fn tool(raw: &Value) -> Option<Value> {
        let function =
            raw.get("function")?.as_object().filter(|_| raw.get("type").and_then(Value::as_str) == Some("function"))?;
        let mut tool = Map::new();
        tool.insert("name".to_string(), function.get("name").cloned().unwrap_or_else(|| json!("")));
        if let Some(description) = function.get("description").filter(|value| Coerce::truthy(Some(*value))) {
            tool.insert("description".to_string(), description.clone());
        }
        let schema = function.get("parameters").filter(|value| Coerce::truthy(Some(*value))).cloned();
        tool.insert("input_schema".to_string(), schema.unwrap_or_else(|| json!({"type": "object", "properties": {}})));
        Some(Value::Object(tool))
    }

    fn tool_choice(choice: &Value) -> Option<Value> {
        match choice {
            Value::String(word) => match word.as_str() {
                "auto" => Some(json!({"type": "auto"})),
                "none" => Some(json!({"type": "none"})),
                "required" => Some(json!({"type": "any"})),
                _ => None,
            },
            Value::Object(fields) if fields.get("type").and_then(Value::as_str) == Some("function") => {
                let name = fields.get("function").and_then(|function| function.get("name")).cloned();
                Some(json!({"type": "tool", "name": name.unwrap_or_else(|| json!(""))}))
            }
            _ => None,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn an_address_that_is_no_data_stays_an_address() {
        assert_eq!(ChatToAnthropic::image_source("https://x/y.png"), json!({"type": "url", "url": "https://x/y.png"}));
        assert_eq!(
            ChatToAnthropic::image_source("data:image/png;base64,AAA"),
            json!({"type": "base64", "media_type": "image/png", "data": "AAA"})
        );
        assert_eq!(
            ChatToAnthropic::image_source("data:nothing"),
            json!({"type": "base64", "media_type": "image/jpeg", "data": ""})
        );
    }
}
