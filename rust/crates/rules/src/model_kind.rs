//! What a model of the entry does, from its pool's rows.
//!
//! A pool answers from whichever of its rows serves, so it promises only what every row that may serve does. A row that may serve
//! and says nothing of itself makes the pool's kind unknown: absent from the list, never guessed.

use crate::cloud_accounts::{CloudAccount, CloudAccounts};
use crate::cloud_models::AccountModelJobs;
use crate::cloud_pools::{Pool, RowWork};
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
    /// A chat's inputs, in the order they are said.
    const INPUTS: [&'static str; 3] = ["text", "image", "audio"];
    /// A subscription's chat takes pictures; another provider's is promised text alone.
    const SUBSCRIPTION_INPUTS: [&'static str; 2] = ["text", "image"];
    /// The work a key's model may be said to do: `AccountModelJobs.OFFERED`.
    const OFFERED: [&'static str; 5] = ["llm", "embed", "asr", "speech-translate", "tts"];
    const CHAT: &'static str = "llm";

    fn new(jobs: &[&str], inputs: &[&str], languages: Option<Vec<String>>, max_audio_ms: Option<i64>) -> Self {
        Self {
            jobs: Self::WORK.iter().map(|work| work.job).filter(|job| jobs.contains(job)).collect(),
            inputs: Self::INPUTS.iter().copied().filter(|input| inputs.contains(input)).collect(),
            languages: languages.filter(|languages| !languages.is_empty()),
            max_audio_ms,
            mixed: false,
        }
    }

    /// The kind of these jobs and nothing else said: `ModelKind(jobs)`.
    pub fn of_jobs(jobs: &[&str]) -> Self {
        Self::new(jobs, &[], None, None)
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
        Self::fixed(account).or_else(|| said.map(|jobs| Self::new(jobs, &["text"], None, None)))
    }

    /// A local output's row: what its model said of itself.
    fn of_output(output: &RouterOutput) -> Option<Self> {
        if !output.says_its_work {
            return None;
        }
        let jobs: Vec<&str> = output.jobs.iter().map(String::as_str).collect();
        let said: Vec<&str> = output.inputs.iter().map(String::as_str).collect();
        let inputs: &[&str] = if said.is_empty() { &["text"] } else { &said };
        Some(Self::new(&jobs, inputs, Some(output.languages.clone()), output.max_audio_ms))
    }

    /// The pool's kind: what every row that may serve does, mixed when they share no job, `None` when there is no such row or one of
    /// them says nothing of itself. A row switched off, open, or whose account or cell is gone is no part of the promise.
    pub fn of_pool(pool: &Pool, accounts: &CloudAccounts, outputs: &RouterOutputs, jobs: &AccountModelJobs) -> Option<Self> {
        let mut kinds = Vec::new();
        for row in pool.rows.iter().filter(|row| row.enabled) {
            let kind = match &row.work {
                RowWork::Open => continue,
                RowWork::Account { account, model } => match accounts.get(account) {
                    None => continue,
                    Some(found) => Self::of_account(found, jobs.of(account, model)),
                },
                RowWork::Output(output) => match outputs.get(output) {
                    None => continue,
                    Some(found) => Self::of_output(found),
                },
            };
            kinds.push(kind?);
        }
        let (first, rest) = kinds.split_first()?;
        Some(Self::together(first, rest))
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
