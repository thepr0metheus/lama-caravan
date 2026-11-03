//! What an upstream's error says of itself.

use crate::coerce::Coerce;
use serde_json::Value;

/// Providers put the reason in the body and each nests it differently: `{"error":{"message","code"}}`, a bare
/// `{"error":"…"}`, `{"detail":"…"}`. Anything unparsed still beats an empty string, so the raw text is the fallback.
pub struct UpstreamFailure;

impl UpstreamFailure {
    /// Statuses that mean the upstream cannot serve anyone right now: `DEAD_STATUSES`. A
    /// request-specific 4xx is not among them: the upstream answered.
    const DEAD: [u16; 10] = [401, 402, 403, 404, 408, 429, 500, 502, 503, 504];

    /// Whether this status says the upstream itself is unusable, and not this one request.
    pub fn is_dead_status(status: u16) -> bool {
        Self::DEAD.contains(&status)
    }

    /// (human reason, short kind) for an upstream that answered with an error.
    pub fn summary(status: u16, body: &str) -> (String, String) {
        let text = Coerce::strip(body);
        let (mut reason, mut kind) = (String::new(), String::new());
        if (text.starts_with('{') || text.starts_with('['))
            && let Ok(Value::Object(data)) = serde_json::from_str::<Value>(text)
        {
            match data.get("error") {
                Some(Value::Object(error)) => {
                    reason = Coerce::stripped(error.get("message"));
                    kind = Coerce::stripped(error.get("code"));
                    if kind.is_empty() {
                        kind = Coerce::stripped(error.get("type"));
                    }
                }
                Some(Value::String(error)) => reason = Coerce::strip(error).to_string(),
                _ => {}
            }
            if reason.is_empty() {
                reason = Coerce::stripped(data.get("detail"));
            }
            if reason.is_empty() {
                reason = Coerce::stripped(data.get("message"));
            }
            if kind.is_empty() {
                kind = Coerce::stripped(data.get("code"));
            }
        }
        if reason.is_empty() {
            let collapsed = text.split_whitespace().collect::<Vec<_>>().join(" ");
            reason = Coerce::first_letters(&collapsed, 300).to_string();
        }
        if kind.is_empty() {
            kind = format!("http_{status}");
        }
        let kind = Coerce::first_letters(&kind, 60).to_string();
        (reason, kind)
    }

    /// The `error.code` a JSON refusal names, as it stands; `None` when it names none. What to tell of it is decided by
    /// `OpenAiError::clean_code`.
    pub fn code(body: &str) -> Option<Value> {
        let data: Value = serde_json::from_str(Coerce::strip(body)).ok()?;
        data.get("error")?.as_object()?.get("code").cloned()
    }
}
