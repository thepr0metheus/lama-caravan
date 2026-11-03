//! What the entry says itself when it refuses a request, and what the journal calls it.

use crate::key_entry::KeyMiss;
use crate::openai_error::OpenAiError;

/// One refusal of the entry.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EntryRefusal {
    /// What the client is told.
    pub error: OpenAiError,
    /// What the journal calls it.
    pub reason: &'static str,
}

impl EntryRefusal {
    fn of(error: OpenAiError, reason: &'static str) -> Self {
        Self { error, reason }
    }

    /// A key that names no route.
    pub fn of_key(miss: KeyMiss, key: &str) -> Self {
        match miss {
            KeyMiss::NoKey => Self::of(OpenAiError::no_key(), "entry:no-key"),
            KeyMiss::UnknownKey => Self::of(OpenAiError::wrong_key(key), "entry:unknown-key"),
            KeyMiss::AmbiguousKey => Self::of(OpenAiError::shared_key(), "entry:ambiguous-key"),
        }
    }

    /// A route of the old kind, with a port of its own: the entry serves the clients of Routing.
    pub fn not_a_consumer() -> Self {
        Self::of(
            OpenAiError::new(
                403,
                "This key belongs to a port of the old kind: the caravan's entry serves the clients of Routing.",
            ),
            "entry:not-a-consumer",
        )
    }

    /// A method the entry has not.
    pub fn other_method(method: &str) -> Self {
        Self::of(OpenAiError::new(501, format!("Unsupported method ('{method}').")), "entry:other-method")
    }

    /// The settings do not read: nothing can be said of the key or the model, and it is no fault of the client's.
    pub fn settings_unreadable() -> Self {
        Self::of(
            OpenAiError {
                retry_after: Some(30),
                ..OpenAiError::new(503, "The caravan cannot read its settings now. Try again later.")
            },
            "entry:settings-unreadable",
        )
    }

    /// A client held back on the board.
    pub fn paused() -> Self {
        Self::of(OpenAiError::paused(), "entry:paused")
    }

    /// A path the entry has not.
    pub fn invalid_url(method: &str, path: &str) -> Self {
        Self::of(OpenAiError::invalid_url(method, path), "entry:invalid-url")
    }

    /// A body that is neither a JSON object nor a form.
    pub fn unreadable() -> Self {
        Self::of(OpenAiError::unreadable(), "entry:unreadable")
    }

    /// A body that cannot be taken off the connection as the request says it is sent.
    pub fn broken_body(words: &str) -> Self {
        Self::of(OpenAiError::broken_body(words), "entry:broken-body")
    }

    /// A request that names no model.
    pub fn no_model() -> Self {
        Self::of(OpenAiError::no_model(), "entry:no-model")
    }

    /// A request for work the model does not do.
    pub fn unsupported(model: &str, path: &str) -> Self {
        Self::of(OpenAiError::unsupported(model, path), "entry:unsupported")
    }

    /// A model the board closed to this client.
    pub fn model_closed(model: &str) -> Self {
        Self::of(OpenAiError::not_allowed(model), "entry:model-closed")
    }

    /// A model the caravan knows that does not run.
    pub fn model_stopped(model: &str) -> Self {
        Self::of(OpenAiError::not_running(model), "entry:model-stopped")
    }

    /// A key that calls no model at all now.
    pub fn no_pool() -> Self {
        Self::of(OpenAiError::no_pool(), "entry:no-pool")
    }

    /// A name the caravan has not.
    pub fn model_unknown(model: &str) -> Self {
        Self::of(OpenAiError::unknown_model(model), "entry:model-unknown")
    }
}
