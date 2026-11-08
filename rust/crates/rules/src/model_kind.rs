//! What a model of the entry does, from its pool's rows.
//!
//! A pool answers from whichever of its rows serves, so it promises only what every row that may serve does. A row that may serve
//! and says nothing of itself makes the pool's kind unknown: absent from the list, never guessed.
//!
//! A request is different from the list: it is served by one row, not by all of them together. `may_read` asks the rows one by one,
//! and a picture goes to a row that promises pictures; a row that said it does not read them is no candidate for that request.
//! `pool_steps` keeps such a row out of the choice, so the promise the list advertises and the row that serves cannot disagree.

use crate::cloud_accounts::{CloudAccount, CloudAccounts};
use crate::cloud_models::AccountModelJobs;
use crate::cloud_pools::{Pool, PoolRow, RowWork};
use crate::media_parts::MediaParts;
use crate::router_outputs::{RouterOutput, RouterOutputs};
use serde_json::{Map, Value, json};

/// One job: what it takes and gives in OpenRouter's words for modalities, and the paths of OpenAI's API it answers.
struct Work {
    job: &'static str,
    takes: &'static [&'static str],
    gives: &'static [&'static str],
    paths: &'static [&'static str],
}

/// The kind of one row, or of a pool's rows together.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct ModelKind {
    jobs: Vec<&'static str>,
    inputs: Vec<&'static str>,
    languages: Option<Vec<String>>,
    max_audio_ms: Option<i64>,
    mixed: bool,
}

/// What one row of a pool contributes to a request's promise.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum RowKind {
    /// The row serves nothing: it is open, or the account or cell it names is gone.
    ServesNothing,
    /// It serves, and says nothing of its inputs: there is no promise to read a request against.
    Silent,
    /// It serves, and says what it does.
    Said(ModelKind),
}

/// What a pool's rows say about one word a request carries.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MayRead {
    /// Some row promises the word: this request may go, and the row that serves it is one that reads it.
    Takes,
    /// No row promises it, and some row says nothing of its inputs: the absence of a promise is not a refusal.
    Unsaid,
    /// Every row that may serve said it cannot read the word.
    Cannot,
    /// No row may serve at all: the pool's own refusal says why, not this rule.
    NoRow,
}

impl ModelKind {
    /// The vocabulary, in its order: a kind's jobs are said in it.
    const WORK: [Work; 8] = [
        Work {
            job: "llm",
            takes: &["text"],
            gives: &["text"],
            paths: &["/chat/completions", "/responses", "/completions", "/messages"],
        },
        Work { job: "embed", takes: &["text"], gives: &["embeddings"], paths: &["/embeddings"] },
        Work { job: "asr", takes: &["audio"], gives: &["text"], paths: &["/audio/transcriptions", "/audio/translations"] },
        Work { job: "tts", takes: &["text"], gives: &["audio"], paths: &["/audio/speech"] },
        Work { job: "translate", takes: &["text"], gives: &["text"], paths: &[] },
        Work {
            job: "speech-translate",
            takes: &["audio"],
            gives: &["text"],
            paths: &["/audio/transcriptions", "/audio/translations"],
        },
        Work { job: "voice-chat", takes: &["audio", "text"], gives: &["audio", "text"], paths: &[] },
        Work { job: "robot-policy", takes: &["image", "text"], gives: &["actions"], paths: &["/robot/predict"] },
    ];
    /// A chat's inputs, in the order they are said: the vocabulary, read where it lives, not written again here.
    const INPUTS: [&'static str; 3] = MediaParts::WORDS;
    /// A subscription's chat takes pictures; another provider's is promised text alone. A plan's choice, not the vocabulary: it is written as words because it is not the whole of it.
    const SUBSCRIPTION_INPUTS: [&'static str; 2] = ["text", "image"];
    /// The work a key's model may be said to do: `AccountModelJobs.OFFERED`.
    const OFFERED: [&'static str; 5] = ["llm", "embed", "asr", "speech-translate", "tts"];
    const CHAT: &'static str = "llm";

    fn new(jobs: &[&str], inputs: &[&str], languages: Option<Vec<String>>, max_audio_ms: Option<i64>) -> Self {
        let jobs: Vec<&'static str> = Self::WORK.iter().map(|work| work.job).filter(|job| jobs.contains(job)).collect();
        Self {
            inputs: Self::promised(&jobs, inputs),
            languages: languages.filter(|languages| !languages.is_empty()),
            max_audio_ms,
            mixed: false,
            jobs,
        }
    }

    /// What a kind promises it can read: the words its row named, plus the words a chat takes by definition (`WORK`'s `llm`).
    /// The definition is said once here; writing `"text"` again in a reader is the same fact a second way, and the two copies are
    /// where a promise and a refusal start disagreeing.
    fn promised(jobs: &[&'static str], named: &[&str]) -> Vec<&'static str> {
        Self::INPUTS
            .iter()
            .copied()
            .filter(|word| named.contains(word) || jobs.contains(&Self::CHAT) && Self::chat_takes().any(|taken| taken == *word))
            .collect()
    }

    /// What a chat takes because it is a chat, from `WORK`; not a word written again.
    fn chat_takes() -> impl Iterator<Item = &'static str> {
        Self::WORK.iter().filter(|work| work.job == Self::CHAT).flat_map(|work| work.takes.iter().copied())
    }

    /// The kind of these jobs and nothing else said: `ModelKind(jobs)`.
    pub fn of_jobs(jobs: &[&str]) -> Self {
        Self::new(jobs, &[], None, None)
    }

    /// A chat's kind as the table `contract/media_parts.json` says it: its jobs and the inputs it promises. A chat that promises
    /// no inputs says nothing of itself, and `takes()` answers `None` for it — the table's promise is never a guess.
    pub fn of_words(jobs: &[&str], inputs: &[&str]) -> Self {
        Self::new(jobs, inputs, None, None)
    }

    /// `jobs` as they may be said of a key's model, in the vocabulary's order.
    pub fn offered_jobs(jobs: &[&str]) -> Vec<&'static str> {
        Self::WORK.iter().map(|work| work.job).filter(|job| jobs.contains(job) && Self::OFFERED.contains(job)).collect()
    }

    /// The kind an account's type fixes for every model of it, or `None`: the operator says it.
    fn fixed(account: &CloudAccount) -> Option<Self> {
        if account.is_subscription() {
            return Some(Self::new(&[Self::CHAT], &Self::SUBSCRIPTION_INPUTS, None, None));
        }
        account.chats_only().then(|| Self::new(&[Self::CHAT], &["text"], None, None))
    }

    /// An account's row: the work its type fixes, or what the operator said of its model; nothing else.
    fn of_account(account: &CloudAccount, said: Option<&[&'static str]>) -> Option<Self> {
        Self::fixed(account).or_else(|| said.map(|jobs| Self::new(jobs, &[], None, None)))
    }

    /// A local output's row: what its model said of itself. What it did not say is not filled in here: `promised` adds only what a chat
    /// takes because it is a chat.
    fn of_output(output: &RouterOutput) -> Option<Self> {
        if !output.says_its_work {
            return None;
        }
        let jobs: Vec<&str> = output.jobs.iter().map(String::as_str).collect();
        let said: Vec<&str> = output.inputs.iter().map(String::as_str).collect();
        Some(Self::new(&jobs, &said, Some(output.languages.clone()), output.max_audio_ms))
    }

    /// The pool's kind: what every row that may serve does, mixed when they share no job, `None` when there is no such row or one of
    /// them says nothing of itself. A row switched off, open, or whose account or cell is gone is no part of the promise.
    pub fn of_pool(pool: &Pool, accounts: &CloudAccounts, outputs: &RouterOutputs, jobs: &AccountModelJobs) -> Option<Self> {
        let mut kinds = Vec::new();
        for row in pool.rows.iter().filter(|row| row.enabled) {
            match Self::of_row(row, accounts, outputs, jobs) {
                RowKind::ServesNothing => continue,
                RowKind::Silent => return None,
                RowKind::Said(kind) => kinds.push(kind),
            }
        }
        let (first, rest) = kinds.split_first()?;
        Some(Self::together(first, rest))
    }

    /// One row's kind: what it serves and what it says of its inputs. A row whose account or cell is gone serves nothing,
    /// as an open row does; a row that serves and names no jobs says nothing of itself.
    pub fn of_row(row: &PoolRow, accounts: &CloudAccounts, outputs: &RouterOutputs, jobs: &AccountModelJobs) -> RowKind {
        let kind = match &row.work {
            RowWork::Open => return RowKind::ServesNothing,
            RowWork::Account { account, model } => match accounts.get(account) {
                None => return RowKind::ServesNothing,
                Some(found) => Self::of_account(found, jobs.of(account, model)),
            },
            RowWork::Output(output) => match outputs.get(output) {
                None => return RowKind::ServesNothing,
                Some(found) => Self::of_output(found),
            },
        };
        kind.map_or(RowKind::Silent, RowKind::Said)
    }

    /// What the rows say about `word`, one by one: a row that promises it is enough for this request, because the row that
    /// serves is chosen among those that read it. A row that says nothing is not a promise of nothing.
    pub fn may_read(rows: impl IntoIterator<Item = RowKind>, word: &str) -> MayRead {
        let mut serving = false;
        let mut silent = false;
        for row in rows {
            match row {
                RowKind::ServesNothing => {}
                RowKind::Silent => {
                    serving = true;
                    silent = true;
                }
                RowKind::Said(kind) => {
                    serving = true;
                    match kind.reads(word) {
                        Some(true) => return MayRead::Takes,
                        Some(false) => {}
                        None => silent = true,
                    }
                }
            }
        }
        if !serving {
            MayRead::NoRow
        } else if silent {
            MayRead::Unsaid
        } else {
            MayRead::Cannot
        }
    }

    /// What this kind says of `word`: `Some(true)` promises it, `Some(false)` says it cannot, and `None` says nothing —
    /// a mixed kind, or no chat at all.
    pub fn reads(&self, word: &str) -> Option<bool> {
        self.takes().map(|takes| takes.contains(&word))
    }

    fn together(first: &Self, rest: &[Self]) -> Self {
        let every = || std::iter::once(first).chain(rest);
        let jobs: Vec<&str> = first.jobs.iter().copied().filter(|job| rest.iter().all(|kind| kind.jobs.contains(job))).collect();
        if jobs.is_empty() {
            return Self { mixed: true, ..Self::default() };
        }
        let inputs: Vec<&str> = if jobs.contains(&Self::CHAT) {
            let chats = || every().filter(|kind| kind.jobs.contains(&Self::CHAT));
            Self::INPUTS.iter().copied().filter(|input| chats().all(|kind| kind.inputs.contains(input))).collect()
        } else {
            Vec::new()
        };
        let audio: Option<Vec<i64>> = every().map(|kind| kind.max_audio_ms).collect();
        Self::new(&jobs, &inputs, Self::shared_languages(first, rest), audio.and_then(|audio| audio.into_iter().min()))
    }

    /// The languages every kind names, in the first one's order; `None` when one names none.
    fn shared_languages(first: &Self, rest: &[Self]) -> Option<Vec<String>> {
        let mine = first.languages.as_ref()?;
        let others: Option<Vec<&Vec<String>>> = rest.iter().map(|kind| kind.languages.as_ref()).collect();
        let others = others?;
        Some(mine.iter().filter(|language| others.iter().all(|other| other.contains(language))).cloned().collect())
    }

    /// Whether it holds a chat.
    pub fn chats(&self) -> bool {
        self.jobs.contains(&Self::CHAT)
    }

    /// What the kind promises it can read, in the vocabulary's order; `None` when there is no promise to refuse against — a mixed pool,
    /// or a row that says nothing of itself. The absence is kept as an absence: a promise the rows did not name is not a promise.
    pub fn takes(&self) -> Option<&[&'static str]> {
        (!self.mixed && self.chats()).then_some(self.inputs.as_slice())
    }

    /// What Routing draws of a pool's kind.
    pub fn state(&self) -> Value {
        if self.mixed {
            return json!({"mixed": true});
        }
        let mut out = Map::new();
        out.insert("jobs".to_string(), json!(self.jobs));
        if self.jobs.contains(&Self::CHAT) {
            out.insert("inputs".to_string(), json!(self.inputs));
        }
        if let Some(languages) = self.languages.as_ref().filter(|languages| !languages.is_empty()) {
            out.insert("languages".to_string(), json!(languages));
        }
        Value::Object(out)
    }

    /// Whether the pool does the work a request's path asks for. A mixed pool is the rows' to decide.
    pub fn serves(&self, path: &str) -> bool {
        if self.mixed {
            return true;
        }
        let clean = path.split_once('?').map_or(path, |(before, _)| before).trim_end_matches('/');
        let works = Self::WORK.iter().filter(|work| self.jobs.contains(&work.job));
        works.flat_map(|work| work.paths).any(|end| clean.ends_with(end))
    }

    /// OpenRouter's `architecture` for one kind of work, or `None`: no kind, or more than one.
    fn architecture(&self) -> Option<Value> {
        let (job, others) = self.jobs.split_first()?;
        let work = Self::WORK.iter().find(|work| work.job == *job)?;
        if self.mixed || !others.is_empty() {
            return None;
        }
        let takes: &[&str] = if *job == Self::CHAT { &self.inputs } else { work.takes };
        Some(json!({
            "modality": format!("{}->{}", takes.join("+"), work.gives.join("+")),
            "input_modalities": takes,
            "output_modalities": work.gives,
        }))
    }

    /// What a model of `GET /v1/models` adds: `architecture` and `caravan`; nothing for a mixed pool.
    pub fn models_entry(&self) -> Map<String, Value> {
        let mut entry = Map::new();
        if self.mixed {
            return entry;
        }
        if let Some(architecture) = self.architecture() {
            entry.insert("architecture".to_string(), architecture);
        }
        let mut said = Map::new();
        said.insert("jobs".to_string(), json!(self.jobs));
        if let Some(languages) = self.languages.as_ref().filter(|languages| !languages.is_empty()) {
            said.insert("languages".to_string(), json!(languages));
        }
        if let Some(longest) = self.max_audio_ms {
            said.insert("max_audio_ms".to_string(), json!(longest));
        }
        entry.insert("caravan".to_string(), Value::Object(said));
        entry
    }
}
