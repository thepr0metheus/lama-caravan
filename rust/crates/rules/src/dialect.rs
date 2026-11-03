//! How a request is told its failures: the entry's way for a consumer.

use crate::openai_error::OpenAiError;
use serde_json::Value;

/// A failure as the client gets it.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Told {
    /// The status.
    pub status: u16,
    /// The body.
    pub body: Vec<u8>,
    /// The fields beside it.
    pub headers: Vec<(&'static str, String)>,
}

impl From<OpenAiError> for Told {
    fn from(error: OpenAiError) -> Self {
        Self { status: error.status, body: error.body(), headers: error.headers() }
    }
}

/// A consumer is told everything in OpenAI's shape and the caravan's words, with nothing of what stands behind its model:
/// not an upstream's headers, not its words about the caravan's sign-in.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct OpenAiDialect {
    model: String,
}

impl OpenAiDialect {
    /// The upstream headers a consumer gets.
    const HEADERS: [&'static str; 3] = ["content-type", "content-length", "cache-control"];

    /// The dialect of a request to the model called `model`.
    pub fn new(model: &str) -> Self {
        Self { model: model.to_string() }
    }

    /// The model a client calls.
    pub fn model(&self) -> &str {
        &self.model
    }

    /// A refusal the pool made itself, as it stands.
    pub fn own_refusal(&self, error: OpenAiError) -> OpenAiError {
        error
    }

    /// A failure of the caravan's own, in words that name nothing behind the model.
    pub fn error(&self, status: u16, kind: &str) -> OpenAiError {
        if kind == "blocked" {
            return OpenAiError::paused();
        }
        if status == 429 {
            return OpenAiError::limit(&self.model, 30);
        }
        let told = if status < 500 { 502 } else { status };
        let code = if kind.is_empty() { "proxy_error" } else { kind };
        OpenAiError {
            code: Some(code.to_string()),
            ..OpenAiError::new(told, format!("The model `{}` failed. Try again later.", self.model))
        }
    }

    /// (status, body, fields) of a failure the caravan tells itself.
    pub fn failure(&self, status: u16, kind: &str) -> Told {
        self.error(status, kind).into()
    }

    /// The data of the error event once a stream is open.
    pub fn stream_failure(&self, kind: &str) -> Value {
        self.error(502, kind).payload()
    }

    /// Whether an upstream header reaches the client.
    pub fn header_ok(name: &str) -> bool {
        Self::HEADERS.iter().any(|allowed| allowed.eq_ignore_ascii_case(name))
    }

    /// An upstream's error as the consumer is told it. `code` is what the cell behind a local row called its refusal.
    pub fn answer_error(&self, status: u16, reason: &str, code: Option<&Value>) -> Told {
        OpenAiError::upstream(status, &self.model, reason, code).into()
    }
}
