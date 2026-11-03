//! A pool's own answer when no row fits: 429 when every row is held by a limit, 503
//! otherwise, 400 when none of them does this kind of work. A refusal the provider never gave must not be read as the provider's.

use crate::cloud_pools::Pool;
use crate::dialect::{OpenAiDialect, Told};
use crate::model_schedules::WallClock;
use crate::openai_error::OpenAiError;
use crate::python_json::PythonJson;
use serde_json::{Value, json};

/// What the pool said.
#[derive(Debug, Clone, PartialEq)]
pub struct PoolRefusal {
    /// The status.
    pub status: u16,
    /// What the journal and the board call it.
    pub kind: &'static str,
    /// The words of the record: the pool and each row's reason.
    pub message: String,
    /// The answer as a provider's would stand in the journal: the rows' whole state, for whoever reads why.
    pub journal_body: String,
    retry_after: i64,
    closed: bool,
    opens_text: String,
    unsupported: bool,
    /// Whether it is the refusal of a response to go on from.
    context: bool,
    path: String,
}

impl PoolRefusal {
    const KIND: &'static str = "pool_unavailable";
    const CONTEXT_KIND: &'static str = "pool_context_required";
    const LIMITS: [&'static str; 4] = ["reserve", "quota", "payment", "disabled"];
    const BAD_REQUEST: u16 = 400;
    const NO_WAIT_KNOWN: i64 = 30;
    const CONTEXT_WORDS: &'static str = "A pool with more than one step needs the full conversation history in input; previous_response_id belongs to one account and cannot be switched safely.";

    /// The refusal of `pool` at `now`, from the state of its rows.
    pub fn of_rows(pool: &Pool, rows: &[Value], now: f64, path: &str, clock: &dyn WallClock) -> Self {
        let reason = |row: &Value| row.get("reason").and_then(Value::as_str).map(str::to_string);
        let ahead = |field: &str| -> Vec<&Value> {
            rows.iter().filter_map(|row| row.get(field)).filter(|at| at.as_f64().is_some_and(|at| at > now)).collect()
        };
        let (resets, opens) = (ahead("resetAt"), ahead("opensAt"));
        let every = |word: &str| !rows.is_empty() && rows.iter().all(|row| reason(row).as_deref() == Some(word));
        let unsupported = every("format_unsupported");
        let limits =
            !rows.is_empty() && rows.iter().all(|row| reason(row).is_some_and(|word| Self::LIMITS.contains(&word.as_str())));
        let status = if limits {
            429
        } else if unsupported {
            Self::BAD_REQUEST
        } else {
            503
        };
        let soonest = Self::soonest(resets.iter().chain(&opens).copied());
        let retry_after = soonest.and_then(Value::as_f64).map_or(Self::NO_WAIT_KNOWN, |at| ((at - now) as i64).max(1));
        let opens_at = Self::soonest(opens.iter().copied());
        let message = Self::words(&pool.name, rows);
        Self {
            status,
            kind: Self::KIND,
            journal_body: Self::journal_words(Self::KIND, &message, pool, rows, Self::soonest(resets.iter().copied()), opens_at),
            message,
            retry_after,
            closed: every("closed"),
            opens_text: opens_at.and_then(Value::as_f64).map_or(String::new(), |at| clock.text(at as i64)),
            unsupported,
            context: false,
            path: path.split_once('?').map_or(path, |(before, _)| before).to_string(),
        }
    }

    /// A request that goes on from a response of one account, to a pool with more than one row.
    pub fn of_context(pool: &Pool) -> Self {
        let message = Self::CONTEXT_WORDS.to_string();
        Self {
            status: Self::BAD_REQUEST,
            kind: Self::CONTEXT_KIND,
            journal_body: Self::journal_words(Self::CONTEXT_KIND, &message, pool, &[], None, None),
            message,
            retry_after: Self::NO_WAIT_KNOWN,
            closed: false,
            opens_text: String::new(),
            unsupported: false,
            context: true,
            path: String::new(),
        }
    }

    /// The earliest of moments that are said as they were read: the JSON keeps a whole number whole.
    fn soonest<'v>(moments: impl Iterator<Item = &'v Value>) -> Option<&'v Value> {
        moments.min_by(|one, other| one.as_f64().partial_cmp(&other.as_f64()).unwrap_or(std::cmp::Ordering::Equal))
    }

    fn journal_words(
        kind: &str,
        message: &str,
        pool: &Pool,
        rows: &[Value],
        resets: Option<&Value>,
        opens: Option<&Value>,
    ) -> String {
        let error =
            json!({"type": kind, "message": message, "pool_id": pool.id, "steps": rows, "resets_at": resets, "opens_at": opens});
        PythonJson::spaced(&json!({"error": error}))
    }

    fn words(pool_name: &str, rows: &[Value]) -> String {
        if rows.is_empty() {
            return format!("Pool {pool_name} has no step: add one on the board");
        }
        let said: Vec<String> = rows
            .iter()
            .map(|row| {
                let word = |field: &str| row.get(field).and_then(Value::as_str);
                // absent-ok: `s.get("reason", "unknown")`: every row says its id, this code writes them.
                format!("{} ({})", word("stepId").unwrap_or_default(), word("reason").unwrap_or("unknown"))
            })
            .collect();
        format!("Pool {pool_name} has no step that fits now: {}", said.join("; "))
    }

    /// What the client is told, in the dialect's words: a limit or an outage of the model as a whole.
    pub fn told(&self, dialect: &OpenAiDialect) -> Told {
        dialect.own_refusal(self.error_of(dialect.model())).into()
    }

    fn error_of(&self, model: &str) -> OpenAiError {
        if self.context {
            return OpenAiError::coded_as(self.status, &self.message, self.kind);
        }
        let wait = u64::try_from(self.retry_after).unwrap_or(1);
        match self.status {
            429 => OpenAiError::limit(model, wait),
            503 if self.closed => OpenAiError::closed(model, &self.opens_text, wait),
            503 => OpenAiError::unavailable(model, wait),
            400 if self.unsupported => OpenAiError::unsupported(model, &self.path),
            _ => OpenAiError::coded_as(self.status, &self.message, self.kind),
        }
    }
}
