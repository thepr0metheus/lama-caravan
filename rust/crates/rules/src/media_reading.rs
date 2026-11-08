//! What the board's reader does with the pictures of a request, for the row of a pool that cannot read them
//! (`docs/vision-describe.md`, "The reading"): which parts are pictures and where their bytes are, the question the reader is
//! asked about each, the words taken back from its answer, and the request the row is sent with those words in their place.
//!
//! Values only, so every answer is checked by value against `contract/media_reading.json`. Calling the reader, and keeping
//! what it said, are the proxy's (`rust/crates/proxy/src/exchange/reading.rs`): the reader is asked through the same pools as
//! any request, so its queue, its limits and its account are the ones every request has.
//!
//! Only a picture sent inside the request is read — a `data:` URL. A picture behind a link is refused, and said as a link, not
//! as a picture that could not be read: the caravan does not fetch what a client points at for a reader (an address on the
//! caravan's own network would be read by the caravan on a client's word), and what a link shows can change while its address
//! stays the same, so no caption could be said to be of it. A row that reads pictures itself takes a link as it came: the
//! refusal is asked only when a row that cannot is about to serve.

use crate::coerce::Coerce;
use crate::entry_models::EntryModels;
use crate::entry_refusal::EntryRefusal;
use crate::media_parts::{MediaParts, Part};
use crate::media_reader::{MediaReader, Wired};
use crate::request_json::RequestJson;
use serde_json::{Value, json};

/// The list a request's turns stand in, as `RequestSummary::messages` picks it. A picture put back as words is written in the
/// list's own word for a part of text, so the row reads it as the client's own kind of part.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Turns {
    /// A chat's `messages`.
    Chat,
    /// A Responses-API `input`.
    Responses,
}

impl Turns {
    /// The field the list stands under.
    fn field(self) -> &'static str {
        match self {
            Self::Chat => "messages",
            Self::Responses => "input",
        }
    }

    /// The type a part of text has in this list.
    fn text_type(self) -> &'static str {
        match self {
            Self::Chat => "text",
            Self::Responses => "input_text",
        }
    }
}

/// Where a picture's bytes are.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Source {
    /// Inside the request: the `data:` URL it came as, which is the picture itself.
    Inside(String),
    /// Somewhere else: a link, or a file a provider keeps. Not read, and said as what it is.
    Elsewhere,
}

/// One picture of a request: the part as the client numbers it, where it stands in the body, and where its bytes are.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Picture {
    /// The part as the client numbers it, from 1: a refusal names it so.
    pub part: Part,
    /// The turn's place in its list and the part's place in the turn's content, from 0: where its caption goes.
    at: (usize, usize),
    /// Where its bytes are.
    pub source: Source,
}

/// What the board's reader reads of one request: who reads, for which pool, and the pictures in the order they came.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Reading {
    /// Who reads.
    pub reader: MediaReader,
    /// The pool the request is for: the words of a refusal name it.
    pub pool: String,
    turns: Turns,
    /// The pictures, in the order they came.
    pub pictures: Vec<Picture>,
}

impl Reading {
    /// How much of a reader's error is said back to the client: enough to act on, not a provider's page.
    const WHY_LETTERS: usize = 300;

    /// The pictures `payload` carries, each with the number the client gave it — the same numbers `Carried::of` gives, read
    /// from the same list: a chat's `messages`, or the turns of a Responses-API `input` (its items that have a role).
    pub fn of(payload: &Value, reader: MediaReader, pool: &str) -> Self {
        let listed = payload.get("messages").and_then(Value::as_array).filter(|items| !items.is_empty());
        let (turns, items) = match listed {
            Some(items) => (Turns::Chat, items.as_slice()),
            None => (Turns::Responses, payload.get("input").and_then(Value::as_array).map_or(&[][..], Vec::as_slice)),
        };
        let mut pictures = Vec::new();
        let mut counted = 0;
        for (at, item) in items.iter().enumerate() {
            // A chat numbers every message, a Responses input only its turns: the numbers a refusal says are the client's.
            let number = match turns {
                Turns::Chat => at + 1,
                Turns::Responses if item.is_object() && item.get("role").is_some() => {
                    counted += 1;
                    counted
                }
                Turns::Responses => continue,
            };
            let Some(parts) = item.get("content").and_then(Value::as_array) else {
                continue;
            };
            for (index, part) in parts.iter().enumerate().filter(|(_, part)| part.is_object()) {
                let word = MediaParts::modality(part);
                if word != Some(EntryModels::READER_WORD) {
                    continue;
                }
                let part_said = Part { message: number, index: index + 1, word };
                pictures.push(Picture { part: part_said, at: (at, index), source: Self::source(part) });
            }
        }
        Self { reader, pool: pool.to_string(), turns, pictures }
    }

    /// Where a picture part's bytes are: a chat's `image_url` (an object with `url`, or the address alone), a Responses-API
    /// `input_image`'s `image_url`, or base64 data and its type said in a `source` — which is a `data:` URL written in parts.
    fn source(part: &Value) -> Source {
        let url = match part.get("image_url") {
            Some(Value::Object(said)) => Coerce::text(said.get("url")),
            Some(Value::String(url)) => url.clone(),
            _ => String::new(),
        };
        if Self::is_inside(&url) {
            return Source::Inside(url);
        }
        let said = part.get("source").filter(|source| Coerce::text(source.get("type")) == "base64");
        if let Some(source) = said {
            let (kind, data) = (Coerce::text(source.get("media_type")), Coerce::text(source.get("data")));
            if !kind.is_empty() && !data.is_empty() {
                return Source::Inside(format!("data:{kind};base64,{data}"));
            }
        }
        Source::Elsewhere
    }

    /// Whether an address is the picture itself: a `data:` URL, its scheme in any case.
    fn is_inside(url: &str) -> bool {
        url.get(..5).is_some_and(|scheme| scheme.eq_ignore_ascii_case("data:"))
    }

    /// The refusal for the first picture whose bytes are not inside the request, or `None` when every picture's are. Asked when
    /// a row that cannot read the pictures is about to serve, before the reader is asked about any of them: a request is read
    /// whole or not at all.
    pub fn elsewhere(&self) -> Option<EntryRefusal> {
        let picture = self.pictures.iter().find(|picture| picture.source == Source::Elsewhere)?;
        Some(EntryRefusal::picture_elsewhere(&self.pool, self.reader.model(), &picture.part))
    }

    /// What the reader is asked about one picture: the words of this version and the picture as it came, as a chat any
    /// provider takes, with no stream, so that the answer is one body. `None` for a picture whose bytes are elsewhere: there
    /// is nothing to ask about.
    pub fn question(&self, picture: &Picture) -> Option<Value> {
        let Source::Inside(url) = &picture.source else {
            return None;
        };
        Some(json!({
            "model": self.reader.model(),
            "stream": false,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": Wired::PROMPT},
                {"type": "image_url", "image_url": {"url": url}},
            ]}],
        }))
    }

    /// The reader's words in its answer, or why there are none. A chat answer says them in its first choice's message — as text,
    /// or as parts of text, joined in their order. A refusal the model said, and an answer with no words, are no reading: an
    /// empty caption would send the row a picture described as nothing.
    pub fn words(status: u16, body: &[u8]) -> Result<String, String> {
        let answer = RequestJson::read(body);
        if !(200..300).contains(&status) {
            return Err(Self::why(status, answer.as_ref(), body));
        }
        let message = answer
            .as_ref()
            .and_then(|answer| answer.get("choices"))
            .and_then(Value::as_array)
            .and_then(|choices| choices.first())
            .and_then(|choice| choice.get("message"));
        let Some(message) = message else {
            return Err("its answer has no message".to_string());
        };
        let refused = Coerce::text(message.get("refusal"));
        if !Coerce::strip(&refused).is_empty() {
            return Err(format!("it refused: {}", Coerce::first_letters(Coerce::strip(&refused), Self::WHY_LETTERS)));
        }
        let said = match message.get("content") {
            Some(Value::String(text)) => text.clone(),
            Some(Value::Array(parts)) => parts
                .iter()
                .filter(|part| MediaParts::carries_text(part) || Coerce::text(part.get("type")) == "output_text")
                .map(|part| Coerce::text(part.get("text")))
                .collect::<Vec<_>>()
                .join("\n"),
            _ => String::new(),
        };
        let said = Coerce::strip(&said);
        if said.is_empty() {
            return Err("its answer has no words".to_string());
        }
        Ok(said.to_string())
    }

    /// Why an answer that is not a success is no reading: its status, and what it said of itself — an OpenAI-shaped error's
    /// message, or the first words of anything else.
    fn why(status: u16, answer: Option<&Value>, body: &[u8]) -> String {
        let error = answer.and_then(|answer| answer.get("error"));
        let message = match error {
            Some(Value::Object(said)) => Coerce::text(said.get("message")),
            Some(Value::String(said)) => said.clone(),
            _ => String::from_utf8_lossy(body).into_owned(),
        };
        let message = Coerce::strip(&message);
        if message.is_empty() {
            return format!("it answered {status}");
        }
        format!("it answered {status}: {}", Coerce::first_letters(message, Self::WHY_LETTERS))
    }

    /// The refusal for a picture the reader did not read, with why: nothing went on to the pool.
    pub fn failed(&self, picture: &Picture, why: &str) -> EntryRefusal {
        EntryRefusal::reader_failed(&self.pool, self.reader.model(), &picture.part, why)
    }

    /// The request the row gets: each picture replaced where it stood by the reader's caption, the rest as it came. `captions`
    /// are the reader's words in the order of `pictures`. A reading with a picture left without words is not a request to send,
    /// so a count that does not match, or a picture no longer where it was read, is said as `None` — never as a request with a
    /// picture missing.
    pub fn rewritten(&self, payload: &Value, captions: &[String]) -> Option<Value> {
        if captions.len() != self.pictures.len() {
            return None;
        }
        let mut out = payload.clone();
        let items = out.get_mut(self.turns.field())?.as_array_mut()?;
        for (picture, words) in self.pictures.iter().zip(captions) {
            let (turn, part) = picture.at;
            let slot = items.get_mut(turn)?.get_mut("content")?.as_array_mut()?.get_mut(part)?;
            *slot = json!({"type": self.turns.text_type(), "text": self.reader.caption(words)});
        }
        Some(out)
    }
}
