//! Errors as an OpenAI client reads them, word for word, because the words
//! reach the client.

use crate::python_json::PythonJson;
use serde_json::{Value, json};

/// One error: its status, message, code and how long to wait.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct OpenAiError {
    /// The HTTP status.
    pub status: u16,
    /// The words.
    pub message: String,
    /// A word a client can branch on.
    pub code: Option<String>,
    /// The request's field it is about.
    pub param: Option<String>,
    /// Seconds to wait.
    pub retry_after: Option<u64>,
}

impl OpenAiError {
    /// The longest wait an OpenAI client still takes from `Retry-After`.
    const RETRY_WINDOW: u64 = 60;
    /// The longest code a client can branch on.
    const CODE_MAX: usize = 64;

    /// An error with its status and words alone.
    pub fn new(status: u16, message: impl Into<String>) -> Self {
        Self { status, message: message.into(), code: None, param: None, retry_after: None }
    }

    fn coded(status: u16, message: impl Into<String>, code: &str) -> Self {
        Self { code: Some(code.to_string()), ..Self::new(status, message) }
    }

    /// The `type` OpenAI's own API gives a status.
    pub fn kind(&self) -> &'static str {
        match self.status {
            429 => "rate_limit_error",
            500.. => "server_error",
            _ => "invalid_request_error",
        }
    }

    /// The error as its JSON.
    pub fn payload(&self) -> Value {
        json!({"error": {"message": self.message, "type": self.kind(), "param": self.param, "code": self.code}})
    }

    /// The body it is sent as.
    pub fn body(&self) -> Vec<u8> {
        PythonJson::spaced(&self.payload()).into_bytes()
    }

    /// `Retry-After` when a wait is known, and `x-should-retry: false` when it is longer than a client would wait.
    pub fn headers(&self) -> Vec<(&'static str, String)> {
        let Some(wait) = self.retry_after.filter(|wait| *wait > 0) else {
            return Vec::new();
        };
        let mut out = vec![("Retry-After", wait.to_string())];
        if wait > Self::RETRY_WINDOW {
            out.push(("x-should-retry", "false".to_string()));
        }
        out
    }

    /// `OpenAIError.no_key`.
    pub fn no_key() -> Self {
        Self::new(
            401,
            "You didn't provide an API key. Send your key from the caravan in an Authorization header: Authorization: Bearer <key>.",
        )
    }

    /// `OpenAIError.wrong_key`.
    pub fn wrong_key(key: &str) -> Self {
        Self::coded(
            401,
            format!("Incorrect API key provided: {}. Ask the caravan's operator for your key.", Self::masked(key)),
            "invalid_api_key",
        )
    }

    /// `OpenAIError.shared_key`: a key two consumers carry, which a hand-edited file may hold. Not a 409, which a client retries.
    pub fn shared_key() -> Self {
        Self::coded(
            401,
            "This API key is given to more than one consumer, so it opens none. Ask the caravan's operator for a key of your own.",
            "invalid_api_key",
        )
    }

    /// `OpenAIError.unknown_model`.
    pub fn unknown_model(model: &str) -> Self {
        Self {
            param: Some("model".to_string()),
            ..Self::coded(404, format!("The model `{model}` does not exist or you do not have access to it."), "model_not_found")
        }
    }

    /// `OpenAIError.no_model`: OpenAI's own words for a request that names no model.
    pub fn no_model() -> Self {
        Self { param: Some("model".to_string()), ..Self::new(400, "you must provide a model parameter") }
    }

    /// `OpenAIError.invalid_url`.
    pub fn invalid_url(method: &str, path: &str) -> Self {
        Self::new(404, format!("Invalid URL ({method} {path})"))
    }

    /// `OpenAIError.unreadable`: a body that is neither a JSON object nor a form.
    pub fn unreadable() -> Self {
        Self::new(
            400,
            "The caravan reads a request as JSON (application/json), or as a form (multipart/form-data) where OpenAI's API takes a file: send it as one of them.",
        )
    }

    /// `OpenAIError.no_pool`: a key that calls no model at all.
    pub fn no_pool() -> Self {
        Self {
            param: Some("model".to_string()),
            ..Self::coded(
                404,
                "This API key has no model to call now. Ask the caravan's operator to start a model, or to open one to this client.",
                "model_not_found",
            )
        }
    }

    /// `OpenAIError.not_allowed`: said so, not that no such model exists: the operator closed it, and the client's owner should know whom to ask.
    pub fn not_allowed(model: &str) -> Self {
        Self {
            param: Some("model".to_string()),
            ..Self::coded(
                403,
                format!("This API key may not call the model `{model}`: it is closed to this client on the caravan's board."),
                "model_not_allowed",
            )
        }
    }

    /// `OpenAIError.not_running`: a model the caravan knows that does not serve now.
    pub fn not_running(model: &str) -> Self {
        Self {
            param: Some("model".to_string()),
            ..Self::coded(
                503,
                format!("The model `{model}` is not running now. Start it in the caravan, then try again."),
                "model_unavailable",
            )
        }
    }

    /// A key as OpenAI names one back: its last four letters only.
    fn masked(key: &str) -> String {
        let letters: Vec<char> = key.chars().collect();
        match letters.len().checked_sub(4).filter(|cut| *cut > 0) {
            Some(cut) => format!("…{}", letters.get(cut..).unwrap_or_default().iter().collect::<String>()),
            None => "…".to_string(),
        }
    }

    /// A body that cannot be taken off the connection as the request says it is sent.
    pub fn broken_body(reason: &str) -> Self {
        Self::new(400, format!("The request body cannot be read: {reason}."))
    }

    /// The consumer is held back on the board.
    pub fn paused() -> Self {
        Self { retry_after: Some(30), ..Self::new(503, "This consumer is paused on the caravan's board.") }
    }

    /// The model is held by a limit until `retry_after` seconds from now.
    pub fn limit(model: &str, retry_after: u64) -> Self {
        Self {
            retry_after: Some(retry_after),
            ..Self::coded(
                429,
                format!("The model `{model}` has reached its usage limit. Try again in {}.", Self::duration(retry_after)),
                "rate_limit_exceeded",
            )
        }
    }

    /// `code` when it is a word a client can branch on, else `None`: `[A-Za-z][A-Za-z0-9_.-]{0,63}`.
    pub fn clean_code(code: Option<&Value>) -> Option<String> {
        let text = code?.as_str()?;
        let mut letters = text.chars();
        let starts = letters.next().is_some_and(|first| first.is_ascii_alphabetic());
        let rest_fits = letters.all(|letter| letter.is_ascii_alphanumeric() || matches!(letter, '_' | '.' | '-'));
        (starts && rest_fits && text.chars().count() <= Self::CODE_MAX).then(|| text.to_string())
    }

    /// An upstream's own refusal of a request, as the consumer is told it: a 4xx is about the request and its words are
    /// the client's, the caravan's sign-in refused and an upstream's own failures are not.
    pub fn upstream(status: u16, model: &str, reason: &str, code: Option<&Value>) -> Self {
        match status {
            401 | 403 => Self::coded(
                502,
                format!("The provider behind `{model}` refused the caravan. The operator must sign in again."),
                "upstream_auth",
            ),
            429 => Self {
                retry_after: Some(30),
                ..Self::coded(429, format!("The model `{model}` is busy. Try again later."), "rate_limit_exceeded")
            },
            400..=499 => {
                let words = if reason.is_empty() {
                    format!("The model `{model}` refused the request (HTTP {status}).")
                } else {
                    reason.to_string()
                };
                Self { code: Self::clean_code(code), ..Self::new(status, words) }
            }
            _ => Self::coded(502, format!("The model `{model}` failed (HTTP {status})."), "upstream_error"),
        }
    }

    /// An error with the code the caller names.
    pub fn coded_as(status: u16, message: &str, code: &str) -> Self {
        Self::coded(status, message.to_string(), code)
    }

    /// `OpenAIError.unavailable`.
    pub fn unavailable(model: &str, retry_after: u64) -> Self {
        Self {
            retry_after: Some(retry_after),
            ..Self::coded(503, format!("The model `{model}` cannot serve now. Try again later."), "model_unavailable")
        }
    }

    /// `OpenAIError.unsupported`: no row of the pool does this kind of work. The caller's to fix, never a wait.
    pub fn unsupported(model: &str, path: &str) -> Self {
        let path = if path.is_empty() { "this path" } else { path };
        Self {
            param: Some("model".to_string()),
            ..Self::new(400, format!("The model `{model}` does not serve POST {path}. Pick a model of your list that does."))
        }
    }

    /// `OpenAIError.closed`: every row of the model is closed by its schedule. `opens` is that time in the caravan's zone with its offset,
    /// "" when no window opens.
    pub fn closed(model: &str, opens: &str, retry_after: u64) -> Self {
        if opens.is_empty() {
            return Self::coded(
                503,
                format!("The model `{model}` is closed by its schedule, and no window of it opens."),
                "model_unavailable",
            );
        }
        Self {
            retry_after: Some(retry_after),
            ..Self::coded(
                503,
                format!(
                    "The model `{model}` is closed by its schedule until {opens}. Try again in {}.",
                    Self::duration(retry_after)
                ),
                "model_unavailable",
            )
        }
    }

    /// `seconds` in words a person reads at a glance: 45 s, 12 min, 3 h 20 min.
    pub fn duration(seconds: u64) -> String {
        let seconds = seconds.max(1);
        if seconds < 60 {
            return format!("{seconds} s");
        }
        let minutes = seconds.div_ceil(60);
        if minutes < 60 {
            return format!("{minutes} min");
        }
        match (minutes / 60, minutes % 60) {
            (hours, 0) => format!("{hours} h"),
            (hours, rest) => format!("{hours} h {rest} min"),
        }
    }
}
