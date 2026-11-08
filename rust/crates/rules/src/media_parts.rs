//! What a request carries, and what the entry answers when the model cannot take it.
//!
//! One fact, one place: the words a part may name are `MediaParts::WORDS`, and whoever needs them reads them here.
//! Before this the fact had two copies. The journal counted a request's pictures in `summaries.rs`, and the entry
//! decided a chat by its path: a request with a picture went to a model that had promised `input_modalities:
//! ["text"]`, and its answer read as "the model looked at the picture", while the model was given nothing it could
//! read. The copy that looked affected nothing, and the copy that decided never looked at the content.
//!
//! The answers are kept apart on purpose. `Reader::Nothing` is an absence of the operator's decision, `Reader::NotSaid` an
//! absence of a promise, and `Reader::Unknown` a name with no facts to read: drawing them as one word is how a guess gets
//! shipped as a rule. `scripts/check_media_parts.py` holds the readers to reading this file, `check_media_reader.py` holds the
//! vocabulary of the wiring, and `contract/media_parts.json` is this file's table of cases.

use crate::coerce::Coerce;
use crate::media_reader::{Reader, Wired};
use crate::request_json::RequestJson;
use serde_json::Value;

/// One part of a message: where it stands and what it names. Its numbers count from 1, because the refusal says them to the client as the client sent them.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Part {
    /// The message's number.
    pub message: usize,
    /// The part's number within that message.
    pub index: usize,
    /// What it names, in the vocabulary's words; `None` for a part that says nothing of itself.
    pub word: Option<&'static str>,
}

impl Part {
    /// What the refusal calls this part: the word it named, or the words for a part that named nothing.
    pub fn says(&self) -> String {
        match self.word {
            Some(word) => word.to_string(),
            // A part that names nothing is not carried: it is counted as nothing and refused as nothing, never as a picture.
            None => "nothing it carries".to_string(),
        }
    }
}

/// What the entry answers to a request, by what it carries, what the row that serves promises, and what the wiring names.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Verdict {
    /// Nothing the row cannot take: the request goes as it came.
    Goes,
    /// The row says nothing of what it takes: there is no promise to refuse against, so this is not the entry's to decide.
    NotSaid,
    /// The row cannot take the part, so the wiring answers — and the answer says which answer it is. Only `Reader::Reads`
    /// reads: the part goes to that reader and comes back as text, signed by who read it. Every other answer is an absence,
    /// and it is kept as itself so that the refusal can say which absence it was. A row that reads the part itself is never
    /// given a caption.
    Reading(Part, Reader),
    /// A word this rule does not decide yet. Refusing `audio` would change what the speech pools accept today, so it stands
    /// here as said: not decided.
    NotDecided(Part),
}

/// The words a part's `type` may name. The vocabulary lives here: `ModelKind` reads it for what a pool promises, and the journal reads it for what a request carries.
pub struct MediaParts;

impl MediaParts {
    /// The vocabulary, in the order its words are said.
    pub const WORDS: [&'static str; 3] = ["text", "image", "audio"];
    /// The names that mean text exactly: `text` and `input_text`. A name that only holds the word `text` inside it is not a text part — `image_text` carries a picture, and the journal has counted it as one since its first case.
    const TEXT: [&'static str; 2] = ["text", "input_text"];

    /// Whether this part is the kind that carries text. Whoever counts what a request carries reads `modality`, and whoever
    /// needs the letters asks this; both ask here, so the words are named in one place.
    pub fn carries_text(part: &Value) -> bool {
        Self::modality(part) == Some("text")
    }

    /// What one part names it carries; `None` for a part that says nothing of itself.
    pub fn modality(part: &Value) -> Option<&'static str> {
        let said = Coerce::text(part.get("type"));
        if Self::TEXT.contains(&said.as_str()) {
            return Some("text");
        }
        for word in Self::WORDS.iter().filter(|word| **word != "text") {
            if said.contains(word) {
                return Some(word);
            }
        }
        // A part named by its field and not by a `type`: `{"image_url": "y"}` is the picture the client sent, and a part
        // with neither is not something the entry can name — it is counted as nothing, not drawn as a part.
        if Coerce::truthy(part.get("image_url")) {
            return Some("image");
        }
        if Coerce::truthy(part.get("input_audio")) {
            return Some("audio");
        }
        None
    }
}

/// What a message list carries: its parts, in the order they came. The order is part of the fact — three pictures in a row are three parts, and it is what says which reading belongs to which.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Carried {
    /// Every part, in the order it came.
    pub parts: Vec<Part>,
}

impl Carried {
    /// What `messages` carries, read by `MediaParts`. A message that is no object, and a content that is neither text nor a list of parts, carries nothing.
    pub fn of(messages: &[Value]) -> Self {
        let mut carried = Self::default();
        for (number, message) in messages.iter().enumerate().filter(|(_, message)| message.is_object()) {
            match message.get("content") {
                Some(Value::String(_)) => carried.parts.push(Part { message: number + 1, index: 1, word: Some("text") }),
                Some(Value::Array(items)) => {
                    // The numbers are the client's: a piece of the list that is no part does not take one, so the refusal
                    // points at the same place the client wrote.
                    for (index, item) in items.iter().enumerate().filter(|(_, item)| item.is_object()) {
                        carried.parts.push(Part { message: number + 1, index: index + 1, word: MediaParts::modality(item) });
                    }
                }
                // A content that is neither: the journal has always counted it as nothing, and here it is named as nothing rather than drawn as a part.
                _ => {}
            }
        }
        carried
    }

    /// What a request's body carries: the messages it holds, read once. A body that is no JSON object, or holds no `messages`, carries nothing.
    pub fn of_body(body: &[u8]) -> Self {
        let read = RequestJson::read(body);
        let messages = read.as_ref().and_then(|payload| payload.get("messages")).and_then(Value::as_array);
        Self::of(messages.map_or(&[][..], Vec::as_slice))
    }

    /// How many parts name `word`.
    pub fn count(&self, word: &str) -> usize {
        self.parts.iter().filter(|part| part.word == Some(word)).count()
    }

    /// The first part that carries `word`, in the order they came: the refusal names the client's own numbers.
    pub fn first(&self, word: &str) -> Option<&Part> {
        self.parts.iter().find(|part| part.word == Some(word))
    }

    /// The answer to what this carries, against what the row that serves promises and what the pool names as its reader.
    /// `takes` is that row's own word for its inputs, or `None` when its facts say nothing of themselves; `wired` is said as
    /// what it is, because an absence is not a reader.
    pub fn verdict(&self, takes: Option<&[&'static str]>, wired: &Wired) -> Verdict {
        for part in &self.parts {
            let answer = Self::answer(takes, part, wired);
            if answer != Verdict::Goes {
                return answer;
            }
        }
        Verdict::Goes
    }

    /// One part, in the cases' order — the same order `contract/media_parts.json` writes as its rows.
    fn answer(takes: Option<&[&'static str]>, part: &Part, wired: &Wired) -> Verdict {
        // A part that names nothing it carries is not carried: refusing it would refuse a request that says nothing.
        let Some(word) = part.word else {
            return Verdict::Goes;
        };
        // Text is what every model reads, and the path rule already says who does which job: this rule does not refuse it.
        if word == "text" || takes.is_some_and(|takes| takes.contains(&word)) {
            return Verdict::Goes;
        }
        // No promise to refuse against. A pool whose rows say nothing of themselves is the operator's to name on the board, not the entry's to guess.
        if takes.is_none() {
            return Verdict::NotSaid;
        }
        // Only `image` is this rule's to decide, and `audio` is named as not decided — its rule would change what the speech pools accept today.
        if word == "image" {
            return Verdict::Reading(part.clone(), wired.promise(word));
        }
        Verdict::NotDecided(part.clone())
    }
}
