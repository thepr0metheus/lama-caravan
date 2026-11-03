//! Asking an engine over HTTP: GET to look, POST or DELETE to change it.

use crate::http_client::HttpClient;
use rules::{Coerce, PythonJson};
use serde_json::Value;
use std::time::Duration;

/// What a look answers: the status (`None` when nothing answered: refused, timed out) and the JSON payload (`None` when the answer is not JSON). An HTTP error is an answer: its code is the status (401 is how an engine says it wants a token).
pub type Seen = (Option<u16>, Option<Value>);

/// One engine's port.
pub struct EnginePort<'a> {
    /// How to ask.
    pub http: &'a HttpClient,
    /// Which port.
    pub port: i64,
    /// At which address.
    pub host: &'a str,
}

impl EnginePort<'_> {
    const ASK_TIMEOUT: Duration = Duration::from_millis(1500);
    /// No engine's model list is near this; a stuck stream is cut here.
    const ASK_MOST: u64 = 4 << 20;
    /// An engine busy with another request may answer late, so the timeout is minutes, not seconds; the call runs on a thread of its own.
    const CALL_TIMEOUT: Duration = Duration::from_secs(300);
    const CALL_MOST: u64 = 1 << 20;
    const WORD_LETTERS: usize = 300;

    fn url(&self, path: &str) -> String {
        format!("http://{}:{}{path}", self.host, self.port)
    }

    /// GET.
    pub fn ask(&self, path: &str) -> Seen {
        let Ok(answer) = self.http.answer("GET", &self.url(path), &[], &[], Self::ASK_TIMEOUT) else {
            return (None, None);
        };
        let status = answer.head.status;
        if status >= 400 {
            return (Some(status), None);
        }
        let Ok(raw) = answer.text(Self::ASK_MOST) else {
            return (None, None);
        };
        (Some(status), serde_json::from_str(&String::from_utf8_lossy(&raw)).ok())
    }

    /// The only place the scout changes an engine, and only when the operator asked: (status, the engine's own words). The status is `None` when nothing answered; an answer that did what was asked says no words.
    pub fn call(&self, method: &str, path: &str, body: &Value) -> (Option<u16>, String) {
        let fields = [("Content-Type", "application/json".to_string())];
        let sent = PythonJson::spaced(body).into_bytes();
        let answer = match self.http.answer(method, &self.url(path), &fields, &sent, Self::CALL_TIMEOUT) {
            Ok(answer) => answer,
            Err(error) => return (None, Coerce::first_letters(&format!("no answer: {error}"), Self::WORD_LETTERS).to_string()),
        };
        let status = answer.head.status;
        // absent-ok: an error's body that did not come says nothing; its status speaks.
        let raw = answer.text(Self::CALL_MOST).unwrap_or_default();
        let text = String::from_utf8_lossy(&raw);
        if (200..300).contains(&status) {
            return (Some(status), String::new());
        }
        (Some(status), Self::words(serde_json::from_str::<Value>(&text).ok().as_ref(), &text))
    }

    /// What the engine said went wrong, as it said it: its `error` (a text or `{message}`), else the raw answer.
    fn words(payload: Option<&Value>, text: &str) -> String {
        let error = payload.and_then(|payload| payload.get("error")).filter(|error| Coerce::truthy(Some(*error)));
        let said = match error {
            Some(Value::Object(fields)) if Coerce::truthy(fields.get("message")) => Coerce::text(fields.get("message")),
            Some(error @ Value::Object(_)) => PythonJson::spaced(error),
            Some(error) => Coerce::text(Some(error)),
            None => text.to_string(),
        };
        Coerce::first_letters(Coerce::strip(&said), Self::WORD_LETTERS).to_string()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn an_engines_words_are_its_error_or_its_answer() {
        assert_eq!(EnginePort::words(Some(&json!({"error": "no such model"})), "x"), "no such model");
        assert_eq!(EnginePort::words(Some(&json!({"error": {"message": "busy"}})), "x"), "busy");
        assert_eq!(EnginePort::words(Some(&json!({"error": {"code": 5}})), "x"), "{\"code\": 5}");
        assert_eq!(EnginePort::words(None, " raw "), "raw");
    }
}
