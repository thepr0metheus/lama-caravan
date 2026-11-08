//! What a wired reader is, said in one place: what the operator named, what that says about a word, the caption it gives
//! back, and what makes two captions the same.
//!
//! `docs/vision-describe.md` refuses a part the row that serves cannot take when nothing is wired to read it. This is the
//! other half: the wiring is read from the config here, the reader is asked what it promises, and its words are wrapped as
//! data with who read the part and with which version of the words, so a model is not handed text it might take for an
//! instruction.
//!
//! Five facts live here so they cannot drift apart: what a wiring is (`Wired`), what it says about a word (`Reader`), the
//! one place a wiring is read from the config (`EntryModels::wired`, kept in this file with the vocabulary it fills), the
//! one shape of a caption, and the fields that tell two captions of the same part apart. A copy of any of them elsewhere is
//! the defect `scripts/check_media_reader.py` is for, and `contract/media_reader.json` is the table both the program and
//! the guard read.
//!
//! The answers are kept apart on purpose. Nothing wired, a name the caravan does not know, and a promise not said are three
//! different absences, and drawing them as one word is how a reader guessed from a model's name gets shipped as a rule: a
//! model called `qwen3-vl-8b-instruct` whose facts say `text` is a text model, whatever its name says. So the promise comes
//! from `ModelKind` and never from the name.

use crate::client_deny::ClientDeny;
use crate::cloud_pools::Pool;
use crate::entry_models::EntryModels;
use crate::entry_refusal::EntryRefusal;
use crate::media_parts::Carried;
use crate::media_reading::Reading;
use crate::model_kind::{MayRead, ModelKind, RowKind};
use crate::summaries::RequestSummary;
use serde_json::{Value, json};

/// What the operator named for the parts a pool's rows cannot take. These are the facts; the answer is `promise`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Wired {
    /// The operator named nothing: an absence of a decision, not a reader that reads nothing.
    Nothing,
    /// A name the caravan does not know, so there is no promise to answer from.
    Unknown(String),
    /// A name the caravan knows, with what its facts promise; `None` when its facts say nothing of their inputs. Said only
    /// by `Wired::of`, which `EntryModels::wired` fills from `ModelKind`.
    Named(MediaReader, Option<Vec<String>>),
}

impl Wired {
    /// The words a reader is asked with, said once: two captions of the same picture are the same caption only when the
    /// reader and this version are the same, so changing the words changes the cache.
    pub const PROMPT_VERSION: &'static str = "v1";

    /// The words a reader is asked with in this version, said beside it: the version names these words, so the two change
    /// together or the cache keeps captions of a question nobody asks any more. A screenshot is what a client mostly sends,
    /// so its text comes first and comes exactly; what cannot be read is said, not guessed.
    pub const PROMPT: &'static str = "Describe this image for a reader who cannot see it and has to act on what it shows. \
First copy every piece of text in it exactly as written: code, commands, error messages, labels and numbers, keeping line \
breaks and indentation where they carry meaning. Then say what the image shows: what kind of image it is, its layout, and the \
elements, diagrams, objects and colours that matter, with where they are. Where something is too small or blurred to read, \
say so instead of guessing. Answer with the description alone.";

    /// The wiring as the entry's reading fills it. An empty name is the absence of a decision, not a reader with an empty
    /// name; a name the caravan does not know is kept as an unknown name, because there is no promise to answer from it.
    /// This is the only place a wiring is built, so the promise has one home: `EntryModels::wired` gives it the inputs from
    /// `ModelKind`, and nothing here reads a capability out of a name.
    pub fn of(name: &str, known: bool, takes: Option<Vec<String>>, for_pool: Option<&str>) -> Self {
        if name.is_empty() {
            return Self::Nothing;
        }
        if !known {
            return Self::Unknown(name.to_string());
        }
        Self::Named(MediaReader::new(name, Self::PROMPT_VERSION, for_pool), takes)
    }

    /// The reader to ask about `word`, when the wiring's answer for it is `Reads` — the only answer that names someone to ask.
    /// Every other answer is an absence, and an absence has nobody to call.
    pub fn reads(&self, word: &str) -> Option<&MediaReader> {
        match (self, self.promise(word)) {
            (Self::Named(reader, _), Reader::Reads) => Some(reader),
            _ => None,
        }
    }

    /// What these facts say about `word`. The only place a wiring is asked what it promises. `Nothing` and `Unknown`
    /// answer as what they are, and a name that is the pool the wiring is for answers as itself before anything is read
    /// out of its promise: a pool that names itself as its reader would have the caption made by the row that cannot
    /// read it, whatever that pool's facts say.
    pub fn promise(&self, word: &str) -> Reader {
        match self {
            Self::Nothing => Reader::Nothing,
            Self::Unknown(name) => Reader::Unknown(name.clone()),
            Self::Named(reader, _) if reader.is_itself() => Reader::Itself(reader.model().to_string()),
            Self::Named(reader, takes) => match takes.as_deref() {
                // No promise is not a promise of nothing: it is the operator's absence of a named work.
                None => Reader::NotSaid(reader.model().to_string()),
                Some(takes) if takes.iter().any(|taken| taken == word) => Reader::Reads,
                Some(_) => Reader::CannotTake(reader.model().to_string(), word.to_string()),
            },
        }
    }
}

/// What a wiring answers for one word, said as what it is. Only `Reads` reads. The other four are absences of different
/// kinds, and each is kept as itself so that the words of the refusal can say which absence it was: "wire a reader" is
/// wrong advice for a wiring that is already wired, and wrong for a name the caravan cannot check.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Reader {
    /// It promised this word: the caption it gives is the part, read.
    Reads,
    /// It promised its own inputs and not this one — named with the word it did not promise.
    CannotTake(String, String),
    /// Its facts say nothing of their inputs: there is no promise to answer from.
    NotSaid(String),
    /// The wiring names something the caravan does not know: not a reader, whatever the name looks like.
    Unknown(String),
    /// The wiring names the pool it is wired for: a caption cannot come from the row that cannot read the part, so a pool
    /// cannot be its own reader. Said before the promise is read, because this is not a question of what the model takes.
    Itself(String),
    /// The wiring names nothing: an absence of the operator's decision, said as an absence.
    Nothing,
}

impl Reader {
    /// The answer as one word, said once: the board draws this word for its reader block, so a second place that names the
    /// states is a second copy of the rule. The words are the answers the table names, and `Reads` is the only one that is
    /// not an absence.
    pub fn word(&self) -> String {
        match self {
            Self::Reads => "reads".to_string(),
            Self::CannotTake(_, _) => "cannot take".to_string(),
            Self::NotSaid(_) => "not said".to_string(),
            Self::Unknown(_) => "unknown".to_string(),
            Self::Itself(_) => "itself".to_string(),
            Self::Nothing => "nothing".to_string(),
        }
    }

    /// Whether the board may write this answer as a pool's reader. `Reads` writes, and `Nothing` writes: saving nothing is
    /// clearing a wiring, which is not a decision that reads nothing. The other answers say an absence the board cannot
    /// save, so the save is refused with the same words a request gets.
    pub fn writes(&self) -> bool {
        matches!(self, Self::Reads | Self::Nothing)
    }
}

/// One reader, as the wiring names it: the model it calls, the version of the words it is asked with, and the pool the
/// wiring is for — which is what tells a name from a self-naming.
///
/// Two captions are the same caption when the part, the reader and the version of the words are the same. The part is named
/// by the digest of the bytes it came as, which the layer holding those bytes takes: this module never sees a picture, so it
/// never hashes one. The pool the wiring is for is not part of the key: the same reader reading the same part is the same
/// caption for whichever pool asked it.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MediaReader {
    model: String,
    prompt_version: String,
    /// The pool the wiring is for, or `None` for the board's own reader. `None` is said, not left as an empty name: an empty
    /// pool would read as a reader wired for a pool called nothing.
    for_pool: Option<String>,
}

impl MediaReader {
    /// The reader a wiring names. An empty model names no reader, and `EntryModels::wired` says so as `Wired::Nothing`: a
    /// wiring to nothing is not a reader.
    pub fn new(model: &str, prompt_version: &str, for_pool: Option<&str>) -> Self {
        Self {
            model: model.to_string(),
            prompt_version: prompt_version.to_string(),
            for_pool: for_pool.map(|pool| pool.to_string()),
        }
    }

    /// The model the caption names as its reader.
    pub fn model(&self) -> &str {
        &self.model
    }

    /// Whether the wiring names the pool it is wired for. `None` is the board's own reader, which is not wired for a pool, so
    /// it cannot be itself: there is no row that could be the one asked to read.
    pub fn is_itself(&self) -> bool {
        self.for_pool.as_ref() == Some(&self.model)
    }

    /// The version of the words, as the caption and the key name it.
    pub fn version(&self) -> &str {
        &self.prompt_version
    }

    /// The caption as the model's answer carries it: the reader's words wrapped as data, signed with who read the part and
    /// with which version of the words.
    ///
    /// The text is escaped, and so are the two attributes: a reader that writes `<` is a reader whose words stay words, not
    /// an envelope that ends early.
    pub fn caption(&self, text: &str) -> String {
        format!(
            "<caravan-caption by=\"{}\" prompt_version=\"{}\">{}</caravan-caption>",
            Self::escaped(&self.model),
            Self::escaped(&self.prompt_version),
            Self::escaped(text)
        )
    }

    /// What tells one caption from another: the part as the layer that holds it names it, the reader, and the version of the
    /// words.
    ///
    /// Written as a JSON array rather than joined by a separator: a model or a version holding the separator would make two
    /// different captions share one key, which is the one thing a cache must never do.
    pub fn key(&self, part: &str) -> String {
        json!([part, &self.model, &self.prompt_version]).to_string()
    }

    /// A value written into the caption's words: the five characters that would end the envelope, each as its entity.
    fn escaped(text: &str) -> String {
        let mut out = String::with_capacity(text.len());
        for letter in text.chars() {
            match letter {
                '&' => out.push_str("&amp;"),
                '<' => out.push_str("&lt;"),
                '>' => out.push_str("&gt;"),
                '"' => out.push_str("&quot;"),
                '\'' => out.push_str("&apos;"),
                other => out.push(other),
            }
        }
        out
    }
}

impl EntryModels {
    /// Which word of `MediaParts::WORDS` a reader is wired for: said once here, so a request and a save ask the same rule
    /// about the same word. `audio` is not this rule's, and `text` needs no reader.
    pub const READER_WORD: &'static str = "image";

    /// The key the board keeps the reader under, said once here: the file's table (`CloudFileKeys::KEPT`) reads this name, so
    /// the door that writes the key and the reading that reads it cannot name it differently.
    pub const READER_FIELD: &'static str = "reader";

    /// The board's reader, as its facts say it, for the pool `for_pool` the request is for. `None` is the reading with no
    /// pool in front of it — the save door names a name, not a pool — and that is what keeps `itself` out of the board's row.
    pub fn wired(&self, deny: &ClientDeny, for_pool: Option<&str>) -> Wired {
        let Some(name) = self.reader() else {
            return Wired::Nothing;
        };
        self.wired_for(deny, name, for_pool)
    }

    /// The same reading for any name the board is about to write. This is the only place a promise is filled, and it fills it
    /// from `ModelKind`: a name the caravan does not know is said as `Unknown`, and a name with no promise is not a reader.
    ///
    /// The name is looked for among what the board knows, not among what a client can call this second: the rule asks what a
    /// name's facts promise, and a name the board knows but cannot call still has facts to read against. So this asks
    /// `known_name`, and `Reader::Unknown` is left for a name no place in the reading has.
    pub fn wired_for(&self, deny: &ClientDeny, name: &str, for_pool: Option<&str>) -> Wired {
        let found = self.known_name(deny, name);
        // The promise is what the model's facts name, read through `ModelKind::takes` — never what its name looks like.
        let promise = match found.and_then(|reader| self.kind(reader)) {
            Some(kind) => kind.takes().map(|takes| takes.iter().map(|word| word.to_string()).collect()),
            None => None,
        };
        Wired::of(name, found.is_some(), promise, for_pool)
    }

    /// What the board may write as its reader. `None` is the answer that writes: the name that reads the word, and the
    /// absence — writing nothing is clearing a wiring, not a decision that reads nothing. The other answers are refused by
    /// their own words, the same words a request gets, because they are the same answers. `ClientDeny::clean(None)` is
    /// the operator's reading: nothing is closed to the operator, so "the caravan does not know this name" is the fact the
    /// save has to check, and not a fact about one client.
    pub fn can_write(&self, reader: &str) -> Option<EntryRefusal> {
        // Asked with no pool: the board's reader is one fact for the whole board, so a name cannot be the board itself.
        let answer = self.wired_for(&ClientDeny::clean(None), reader, None).promise(Self::READER_WORD);
        if answer.writes() {
            return None;
        }
        // `here` is what the board says in place of a part: it is not looking at a request, so it names what it asked for.
        let here = format!("The board asked to save `{reader}` as its reader.");
        EntryRefusal::wiring("the board", &answer, &here, Self::READER_WORD)
    }

    /// What the entry answers to what a request carries (`payload`, its body), once its model is known.
    ///
    /// The pool is asked row by row, not as one promise: the row that serves this request decides. When the board's reader
    /// reads the picture, the request goes, with what the reader reads of it: whichever row serves — and only that row — has
    /// the pictures read for it when it cannot read them itself, and a row that reads them gets them as they came
    /// (`pool_steps`, `exchange/reading.rs`). Otherwise a row that reads the picture is enough, because selection sends an image
    /// request to a row that reads it; a row that said it cannot read it is no candidate for that request. The entry refuses
    /// only when every row that may serve said it cannot and nothing reads for them, and then the wiring answers as what it is.
    /// A row that says nothing of its inputs is the operator's to name on the board, not the entry's to refuse.
    pub fn media(&self, deny: &ClientDeny, pool: &Pool, payload: &Value) -> MediaAnswer {
        let carried = Carried::of(&RequestSummary::messages(payload));
        if carried.count(Self::READER_WORD) == 0 {
            return MediaAnswer::Goes;
        }
        let wired = self.wired(deny, Some(&pool.name));
        if let Some(reader) = wired.reads(Self::READER_WORD) {
            return MediaAnswer::Readable(Reading::of(payload, reader.clone(), &pool.name));
        }
        let rows: Vec<RowKind> = pool.rows.iter().filter(|row| row.enabled).map(|row| self.row_kind(row)).collect();
        let serving = rows.iter().find_map(|row| match row {
            RowKind::Said(kind) => kind.takes(),
            _ => None,
        });
        match ModelKind::may_read(rows.iter().cloned(), "image") {
            MayRead::Takes | MayRead::Unsaid | MayRead::NoRow => MediaAnswer::Goes,
            // Every row that may serve said it cannot read the part, so the wiring answers here — and the words come from the
            // answer the rule gave, never from a state named by hand.
            MayRead::Cannot => {
                EntryRefusal::media(&pool.name, &carried.verdict(serving, &wired)).map_or(MediaAnswer::Goes, MediaAnswer::Refused)
            }
        }
    }
}

/// What the entry does with what a request carries, once its pool is known: three answers, kept apart, because "it goes" and
/// "it goes, and a reader reads its pictures for a row that cannot" are different promises to the row that serves.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum MediaAnswer {
    /// It goes as it came.
    Goes,
    /// It is refused, in the words of the answer the rule gave.
    Refused(EntryRefusal),
    /// It goes, and the board's reader reads its pictures for whichever row serves it and cannot read them: who reads, and the
    /// pictures. A row that reads them gets them as they came.
    Readable(Reading),
}
