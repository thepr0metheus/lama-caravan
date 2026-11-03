//! A chat request said to the ChatGPT subscription's Responses API.

use crate::chat_levers::ChatLevers;
use crate::coerce::Coerce;
use crate::python_json::PythonJson;
use crate::request_json::RequestJson;
use serde_json::{Map, Value, json};

/// A request's shape that cannot be translated: the request ends as a failure.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NotAChatRequest(pub &'static str);

/// The model a translated request goes with when nothing names one.
const FALLBACK_MODEL: &str = "gpt-5.4-mini";

/// A Chat Completions request as the Responses API takes it.
pub struct ChatToResponses;

impl ChatToResponses {
    const SYSTEM: &'static str = "You are a helpful assistant.";

    /// (the body to send, the model it names). A body that is no JSON goes as it came, naming none: the provider says what it thinks.
    pub fn body(body: &[u8], override_model: Option<&str>) -> Result<(Vec<u8>, Option<String>), NotAChatRequest> {
        let override_model = override_model.filter(|model| !model.is_empty());
        if body.is_empty() {
            let model = override_model.unwrap_or(FALLBACK_MODEL);
            let minimal = json!({"model": model, "store": false, "stream": true, "instructions": Self::SYSTEM, "input": []});
            return Ok((minimal.to_string().into_bytes(), Some(model.to_string())));
        }
        let Some(payload) = RequestJson::read(body) else {
            return Ok((body.to_vec(), None));
        };
        let Some(fields) = payload.as_object() else {
            return Err(NotAChatRequest("the request is no JSON object"));
        };
        let (instructions, input) = Self::messages(fields.get("messages"))?;
        let said_model = fields.get("model").filter(|model| Coerce::truthy(Some(*model)));
        let model = override_model
            .map_or_else(|| said_model.map_or(FALLBACK_MODEL.to_string(), |model| Coerce::text(Some(model))), str::to_string);
        let mut out = Map::new();
        out.insert("model".to_string(), json!(model));
        out.insert("store".to_string(), json!(false));
        out.insert("stream".to_string(), json!(true));
        out.insert("instructions".to_string(), instructions);
        out.insert("input".to_string(), Value::Array(input));
        out.extend(ChatLevers::for_responses(fields));
        out.insert("include".to_string(), json!([]));
        out.insert("tool_choice".to_string(), fields.get("tool_choice").cloned().unwrap_or_else(|| json!("auto")));
        out.insert("parallel_tool_calls".to_string(), fields.get("parallel_tool_calls").cloned().unwrap_or_else(|| json!(true)));
        if let Some(tools) = fields.get("tools").and_then(Value::as_array).filter(|tools| !tools.is_empty()) {
            out.insert("tools".to_string(), Value::Array(tools.iter().filter_map(Self::tool).collect()));
        }
        Ok((Value::Object(out).to_string().into_bytes(), Some(model)))
    }

    /// The instructions and the input the messages come to.
    fn messages(raw: Option<&Value>) -> Result<(Value, Vec<Value>), NotAChatRequest> {
        let mut instructions = json!(Self::SYSTEM);
        let mut input = Vec::new();
        for message in raw.and_then(Value::as_array).into_iter().flatten() {
            let fields = message.as_object().ok_or(NotAChatRequest("a message is no object"))?;
            let content = fields.get("content").filter(|content| Coerce::truthy(Some(*content)));
            // absent-ok: a message of no role is one nobody knows: passed over.
            match fields.get("role").and_then(Value::as_str).unwrap_or_default() {
                "system" => match content {
                    None => instructions = json!(""),
                    Some(Value::String(text)) => instructions = json!(text),
                    Some(Value::Array(parts)) => instructions = json!(Self::joined_text(parts)?),
                    Some(_) => {}
                },
                "user" => Self::user(&mut input, content)?,
                "assistant" => Self::assistant(&mut input, fields, content)?,
                "tool" => {
                    let result = content.map_or_else(String::new, |content| match content {
                        Value::String(text) => text.clone(),
                        other => PythonJson::spaced(other),
                    });
                    let call = fields.get("tool_call_id").cloned().unwrap_or_else(|| json!(""));
                    input.push(json!({"type": "function_call_output", "call_id": call, "output": result}));
                }
                _ => {}
            }
        }
        Ok((instructions, input))
    }

    fn joined_text(parts: &[Value]) -> Result<String, NotAChatRequest> {
        let mut texts = Vec::new();
        for part in parts {
            let fields = part.as_object().ok_or(NotAChatRequest("a part of a message is no object"))?;
            if fields.get("type").and_then(Value::as_str) == Some("text") {
                // absent-ok: `p.get("text", "")`.
                texts.push(fields.get("text").and_then(Value::as_str).unwrap_or_default());
            }
        }
        Ok(texts.join("\n"))
    }

    fn user(input: &mut Vec<Value>, content: Option<&Value>) -> Result<(), NotAChatRequest> {
        match content {
            None => input.push(json!({"role": "user", "content": [{"type": "input_text", "text": ""}]})),
            Some(Value::String(text)) => input.push(json!({"role": "user", "content": [{"type": "input_text", "text": text}]})),
            Some(Value::Array(raw)) => {
                let mut parts = Vec::new();
                for part in raw {
                    let fields = part.as_object().ok_or(NotAChatRequest("a part of a message is no object"))?;
                    match fields.get("type").and_then(Value::as_str) {
                        Some("text") => {
                            let text = fields.get("text").cloned().unwrap_or_else(|| json!(""));
                            parts.push(json!({"type": "input_text", "text": text}));
                        }
                        Some("image_url") => parts.push(Self::image(fields.get("image_url"))),
                        _ => {}
                    }
                }
                if !parts.is_empty() {
                    input.push(json!({"role": "user", "content": parts}));
                }
            }
            Some(_) => {}
        }
        Ok(())
    }

    fn image(image: Option<&Value>) -> Value {
        let url = image.and_then(|image| image.get("url")).cloned().unwrap_or_else(|| json!(""));
        json!({"type": "input_image", "detail": ChatLevers::detail(image), "image_url": url})
    }

    /// The text of an assistant's content; a list's text is its JSON.
    fn text_of(content: &Value) -> String {
        match content {
            Value::String(text) => text.clone(),
            other => other.to_string(),
        }
    }

    fn assistant(input: &mut Vec<Value>, fields: &Map<String, Value>, content: Option<&Value>) -> Result<(), NotAChatRequest> {
        if let Some(content) = content {
            input.push(json!({"role": "assistant", "content": [{"type": "output_text", "text": Self::text_of(content)}]}));
        }
        for call in fields.get("tool_calls").and_then(Value::as_array).into_iter().flatten() {
            let call = call.as_object().ok_or(NotAChatRequest("a tool call is no object"))?;
            let function = call.get("function").and_then(Value::as_object);
            let said = |name: &str| function.and_then(|function| function.get(name)).cloned().unwrap_or_else(|| json!(""));
            // absent-ok: `tc.get("id", "")`.
            let id = call.get("id").and_then(Value::as_str).unwrap_or_default();
            let item_id = if id.starts_with("fc") { id.to_string() } else { format!("fc_{id}") };
            input.push(json!({"type": "function_call", "id": item_id, "call_id": id, "name": said("name"), "arguments": said("arguments")}));
        }
        Ok(())
    }

    /// A tool as the Responses API says it; one that is no function goes as it came; one that is no object is dropped.
    fn tool(raw: &Value) -> Option<Value> {
        let fields = raw.as_object()?;
        let function = fields
            .get("function")
            .and_then(Value::as_object)
            .filter(|_| fields.get("type").and_then(Value::as_str) == Some("function"));
        let Some(function) = function else {
            return Some(raw.clone());
        };
        let mut tool = Map::new();
        tool.insert("type".to_string(), json!("function"));
        tool.insert("name".to_string(), function.get("name").cloned().unwrap_or_else(|| json!("")));
        for name in ["description", "parameters"] {
            if let Some(value) = function.get(name).filter(|value| Coerce::truthy(Some(*value))) {
                tool.insert(name.to_string(), value.clone());
            }
        }
        if let Some(strict) = function.get("strict").filter(|strict| !strict.is_null()) {
            tool.insert("strict".to_string(), strict.clone());
        }
        Some(Value::Object(tool))
    }
}

/// A request that speaks the Responses API already.
pub struct ResponsesPassthrough;

impl ResponsesPassthrough {
    /// Whether a client speaks it: the path says so, or the body carries `input` and no `messages`. `is_responses_request`.
    pub fn is_request(path: &str, body: &[u8]) -> bool {
        if path.trim_end_matches('/').ends_with("/responses") {
            return true;
        }
        let Some(Value::Object(fields)) = RequestJson::read(body) else {
            return false;
        };
        fields.contains_key("input") && !fields.contains_key("messages")
    }

    /// (the body to send, the model it names, whether the client wants a stream). The body goes as the client wrote it but for the three
    /// fields the subscription's backend dictates, and a bare string of `input`, which it refuses.
    pub fn body(body: &[u8], override_model: Option<&str>) -> (Vec<u8>, String, bool) {
        let override_model = override_model.filter(|model| !model.is_empty());
        let mut fields = match RequestJson::read(body) {
            Some(Value::Object(fields)) => fields,
            _ => {
                let mut empty = Map::new();
                empty.insert("input".to_string(), json!([]));
                empty
            }
        };
        let said_model = fields.get("model").filter(|model| Coerce::truthy(Some(*model)));
        let model = override_model
            .map_or_else(|| said_model.map_or(FALLBACK_MODEL.to_string(), |model| Coerce::text(Some(model))), str::to_string);
        let client_stream = fields.get("stream").is_none_or(|stream| Coerce::truthy(Some(stream)));
        fields.insert("model".to_string(), json!(model));
        fields.insert("store".to_string(), json!(false));
        fields.insert("stream".to_string(), json!(true));
        if let Some(text) = fields.get("input").and_then(Value::as_str).map(str::to_string) {
            fields.insert("input".to_string(), json!([{"role": "user", "content": [{"type": "input_text", "text": text}]}]));
        }
        (Value::Object(fields).to_string().into_bytes(), model, client_stream)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_request_that_is_no_chat_request_fails_as_it_does_in_python() {
        assert!(ChatToResponses::body(b"[1]", None).is_err());
        assert!(ChatToResponses::body(br#"{"messages":["text"]}"#, None).is_err());
        assert!(ChatToResponses::body(br#"{"messages":[{"role":"user","content":["text"]}]}"#, None).is_err());
        assert!(ChatToResponses::body(br#"{"messages":[{"role":"assistant","tool_calls":["x"]}]}"#, None).is_err());
    }
}
