//! The standard fields of a chat request that steer how a model answers, said to the row that serves.

use crate::coerce::Coerce;
use crate::request_kind::RequestKind;
use serde_json::{Map, Value, json};

/// OpenAI's `reasoning_effort`, `verbosity` and an image's `detail`, as each backend takes them. A llama.cpp cell thinks or not by its chat
/// template: gemma-4 thinks by default, and through the entry a short answer came back empty, every token spent on thinking. A subscription
/// speaks the Responses API, which says all three its own way.
pub struct ChatLevers;

impl ChatLevers {
    /// The efforts that ask a model not to think.
    const NO_THINKING: [&'static str; 2] = ["none", "minimal"];
    /// The verbosity a subscription is told when a client says none.
    const QUIET: &'static str = "low";
    const VERBOSITIES: [&'static str; 3] = ["low", "medium", "high"];
    const DETAILS: [&'static str; 3] = ["low", "high", "auto"];
    /// OpenAI's reasoning efforts, from no thinking to the most.
    const EFFORTS: [&'static str; 7] = ["none", "minimal", "low", "medium", "high", "xhigh", "max"];

    /// The effort a client asked for as it wrote it, or `None` when it asked for none.
    fn effort(payload: &Value) -> Option<&str> {
        let said = Coerce::strip(payload.get("reasoning_effort")?.as_str()?);
        (!said.is_empty()).then_some(said)
    }

    /// The efforts of the scale among `words`, in the scale's order.
    pub fn efforts_among(words: &[&str]) -> Vec<&'static str> {
        Self::EFFORTS.iter().copied().filter(|effort| words.contains(effort)).collect()
    }

    /// The effort of `offered` nearest to `asked` on the scale; of two as near, the lower: the cheaper and the faster. `None` when `asked`
    /// is not on the scale, or nothing offered is: a word nobody can place is not swapped for a guess.
    pub fn nearest_effort(asked: &str, offered: &[&str]) -> Option<&'static str> {
        let at = Self::EFFORTS.iter().position(|effort| *effort == asked)?;
        let placed = Self::EFFORTS.iter().enumerate().filter(|(_, effort)| offered.contains(effort));
        placed.min_by_key(|(index, _)| (index.abs_diff(at), *index)).map(|(_, effort)| *effort)
    }

    /// An image's detail as the client set it on `image_url`, or "auto".
    pub fn detail(image: Option<&Value>) -> &'static str {
        let said = image.and_then(|image| image.get("detail")).and_then(Value::as_str);
        Self::DETAILS.iter().copied().find(|detail| Some(*detail) == said).unwrap_or("auto")
    }

    /// What a Responses-API body gets from a chat request's levers: `text`, and `reasoning` only when the client asked for an effort.
    pub fn for_responses(fields: &Map<String, Value>) -> Map<String, Value> {
        let said = fields.get("verbosity").and_then(Value::as_str);
        let verbosity = Self::VERBOSITIES.iter().copied().find(|word| Some(*word) == said).unwrap_or(Self::QUIET);
        let mut out = Map::new();
        out.insert("text".to_string(), json!({"verbosity": verbosity}));
        let effort =
            fields.get("reasoning_effort").and_then(Value::as_str).map(Coerce::strip).filter(|effort| !effort.is_empty());
        if let Some(effort) = effort {
            out.insert("reasoning".to_string(), json!({"effort": effort}));
        }
        out
    }

    /// The chat request with "no thinking" said the template's way, or `None` when nothing changes: a body that is not a
    /// chat request's JSON, an effort that allows thinking, a client that set `enable_thinking` itself.
    pub fn for_cell(body: &[u8], path: &str) -> Option<Vec<u8>> {
        if body.is_empty() || !RequestKind::is_chat_completion(path) {
            return None;
        }
        let mut payload = crate::request_json::RequestJson::read(body)?;
        if !payload.is_object() || !Self::NO_THINKING.contains(&Self::effort(&payload)?) {
            return None;
        }
        let kwargs = payload.get("chat_template_kwargs").and_then(Value::as_object);
        if kwargs.is_some_and(|said| said.contains_key("enable_thinking")) {
            return None;
        }
        // absent-ok: no kwargs yet is what `{**{}, "enable_thinking": False}` starts from; the odd value goes, as there.
        let mut merged: Map<String, Value> = kwargs.cloned().unwrap_or_default();
        merged.insert("enable_thinking".to_string(), Value::Bool(false));
        payload.as_object_mut()?.insert("chat_template_kwargs".to_string(), Value::Object(merged));
        Some(payload.to_string().into_bytes())
    }
}
