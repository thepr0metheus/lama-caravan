//! What the entry says itself when it refuses a request, and what the journal calls it.

use crate::key_entry::KeyMiss;
use crate::media_parts::{Part, Verdict};
use crate::media_reader::Reader;
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

    /// What the entry says to a part the row that serves cannot take, in the words of the wiring the operator named for it.
    ///
    /// The answers get different words because they are different absences, and one sentence for all of them is the defect:
    /// "wire a reader" is wrong advice where a reader is already wired, and wrong for a name the caravan cannot check. The
    /// numbers are the client's own: the message and the part, as it sent them, so that the refusal points at what it refused.
    /// The part comes from the answer, so the words and the numbers cannot name a different part than the rule looked at.
    /// `None` is the answer that refuses nothing: a wiring that reads the word takes the part, and the answers that are not
    /// about the wiring are not this rule's to refuse.
    pub fn media(model: &str, answer: &Verdict) -> Option<Self> {
        // The words are read from the answer the rule gave, never from a state named here.
        let Verdict::Reading(part, reader) = answer else {
            return None;
        };
        let word = part.says();
        let here = format!("Message {} part {}: {word}.", part.message, part.index);
        Self::wiring(model, reader, &here, &word)
    }

    /// The words of one answer. `here` is what the answer was asked about: the message and the part as a client sent them,
    /// or the name the board wrote when there is no request. `word` is the word the rule was asked about, and the answer
    /// that names a word it did not promise says that word itself. The same answer gets the same sentence and the same
    /// code whichever path asked it: a second set of words for one answer is how the board and the journal start saying
    /// different things.
    pub fn wiring(model: &str, answer: &Reader, here: &str, word: &str) -> Option<Self> {
        let wired = format!("The reader wired for `{model}` names");
        let (code, reason, words) = match answer {
            Reader::Reads => return None,
            Reader::Nothing => (
                "media_unsupported",
                "entry:media-unsupported",
                format!(
                    "The model `{model}` does not take {word}, and no reader is wired for it. {here} Send the request to a model that takes {word}, or wire a reader on Routing."
                ),
            ),
            Reader::Unknown(reader) => (
                "media_reader_unknown",
                "entry:media-reader-unknown",
                format!(
                    "{wired} `{reader}`, which the caravan does not know. {here} A wiring that cannot be checked is not a path that reads."
                ),
            ),
            Reader::NotSaid(reader) => (
                "media_reader_unverified",
                "entry:media-reader-unverified",
                format!(
                    "{wired} `{reader}` and says nothing of what it takes. {here} Its promise is not said, so nothing was read."
                ),
            ),
            Reader::CannotTake(reader, taken) => (
                "media_reader_cannot",
                "entry:media-reader-cannot",
                format!(
                    "{wired} `{reader}`, which does not take {taken}. {here} The wiring names a model that cannot read what the request carries."
                ),
            ),
            Reader::Itself(reader) => (
                "media_reader_self",
                "entry:media-reader-self",
                format!(
                    "{wired} `{reader}`, the pool the wiring is for. {here} A pool cannot be its own reader: the caption would come from the row that cannot read it."
                ),
            ),
        };
        Some(Self::of(OpenAiError { param: Some("model".to_string()), ..OpenAiError::coded_as(400, &words, code) }, reason))
    }

    /// A picture the board's reader would read for a row that cannot, whose bytes are not inside the request: a link, or a
    /// file a provider keeps. The caravan reads only a picture sent inside the request, and does not fetch one for a reader —
    /// an address on its own network would be read by the caravan on a client's word. The numbers are the client's own.
    pub fn picture_elsewhere(model: &str, reader: &str, part: &Part) -> Self {
        let (message, index) = (part.message, part.index);
        let words = format!(
            "The model `{model}` does not take image, and the reader wired for it, `{reader}`, reads only a picture sent inside the request (a `data:` URL). Message {message} part {index} is not: the caravan does not fetch a picture for a reader. Send the picture itself, or send the request to a model that takes image."
        );
        Self::of(
            OpenAiError { param: Some("messages".to_string()), ..OpenAiError::coded_as(400, &words, "media_reader_link") },
            "entry:media-reader-link",
        )
    }

    /// The board's reader did not read a picture: who was asked, which part, and why. Nothing went on to the pool, and the
    /// words say so — a request that was not served is not told it was, and the row that cannot read pictures is never sent
    /// one in place of a caption.
    pub fn reader_failed(model: &str, reader: &str, part: &Part, why: &str) -> Self {
        let (message, index) = (part.message, part.index);
        // The reason is a clause of this sentence: a reader's words that end in a full stop do not end it twice.
        let why = why.trim_end().trim_end_matches('.');
        let words = format!(
            "The reader wired for `{model}` names `{reader}`, and it did not read message {message} part {index}: {why}. Nothing was sent to `{model}`."
        );
        Self::of(OpenAiError::coded_as(502, &words, "media_reader_failed"), "entry:media-reader-failed")
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
