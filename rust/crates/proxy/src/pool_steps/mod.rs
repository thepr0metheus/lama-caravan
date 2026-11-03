//! Which row of a pool serves a request, chosen at admission.
//!
//! The first row that is fit now serves, always: the pool goes back up the chain as soon as an earlier row is fit again. A row is not fit while
//! it is switched off, while its model is closed by its schedule, while its account has no sign-in or its provider no longer lists the model,
//! while one of its limit windows is down to the stop level, and for a while after its provider refused it for its limit, its money or its
//! sign-in. Below its switch level a row is fit but gives way. A local model with every place taken gives way to a later ready row at once,
//! or after the patience every model shares.

use crate::clock::Clock;
use crate::output_health::OutputHealth;
use crate::subscription_usage::SubscriptionUsage;
use files::Settings;
use rows::RowState;
use rules::{CloudProvider, Coerce, MachineOutput, Pool, PoolRefusal, QueueLeave, RowWork, WallClock};
use serde_json::{Map, Value, json};
use std::collections::{BTreeMap, BTreeSet, VecDeque};
use std::sync::{Arc, Mutex, PoisonError};

mod rows;
#[cfg(test)]
mod tests;

/// A row of a pool that goes to a machine's model.
#[derive(Debug, Clone)]
pub struct MachineRow {
    /// The row.
    pub row_id: String,
    /// The model.
    pub output: MachineOutput,
    /// When the request leaves the model's queue if it has to wait, and where to.
    pub leave: QueueLeave,
}

/// A row of a pool that goes to a provider.
#[derive(Debug, Clone)]
pub struct CloudRow {
    /// The row.
    pub row_id: String,
    /// The account.
    pub provider: CloudProvider,
    /// The model the row asks for.
    pub model: String,
}

/// What a pool says of one request.
#[derive(Debug, Clone)]
pub enum RowChoice {
    /// That row of a machine.
    Machine(MachineRow),
    /// That row of a provider.
    Cloud(CloudRow),
    /// No row fits: the pool's own answer.
    Refused(PoolRefusal),
}

/// What is asked of a pool.
pub struct PoolQuestion<'a> {
    /// The reading the request was admitted under.
    pub settings: &'a Settings,
    /// The pool.
    pub pool: &'a Pool,
    /// The request's body.
    pub body: &'a [u8],
    /// The request's path.
    pub path: &'a str,
    /// What this request has already tried: `row:<id>`, and the accounts that refused it.
    pub excluded: &'a BTreeSet<String>,
    /// Whether a machine's model has a place free now.
    pub free: &'a dyn Fn(&MachineOutput) -> bool,
}

/// An account that rests after its provider refused it.
#[derive(Debug, Clone)]
struct Blocked {
    reason: &'static str,
    at: f64,
    until: f64,
}

/// What the proxy remembers between requests.
#[derive(Debug, Default)]
struct Memory {
    selected: BTreeMap<String, String>,
    states: Map<String, Value>,
    tried: BTreeMap<String, f64>,
    /// When an account's page last said it has no limit windows at all.
    unlimited: BTreeMap<String, f64>,
    blocked: BTreeMap<String, Blocked>,
    resets_seen: BTreeMap<String, f64>,
    events: VecDeque<Value>,
}

/// The usage page of an account, asked without spending a share of any window.
pub trait UsagePages: Send + Sync {
    /// The page's JSON, or `None`.
    fn page(&self, settings: &Settings, provider: &CloudProvider) -> Option<Value>;
}

/// The pools' state: fresh limit readings, refusals and a bounded journal of switches. The controller edits the chain and draws the decisions.
pub struct PoolSteps {
    clock: Arc<dyn Clock>,
    zone: Arc<dyn WallClock + Send + Sync>,
    pages: Box<dyn UsagePages>,
    /// What each account's answers said of its windows.
    pub usage: SubscriptionUsage,
    /// What each output's answers said of it.
    pub health: OutputHealth,
    memory: Mutex<Memory>,
}

impl PoolSteps {
    const EVENTS_KEPT: usize = 50;

    /// The pools' state on these clocks.
    pub fn new(clock: Arc<dyn Clock>, zone: Arc<dyn WallClock + Send + Sync>, pages: Box<dyn UsagePages>) -> Self {
        Self {
            clock,
            zone,
            pages,
            usage: SubscriptionUsage::default(),
            health: OutputHealth::default(),
            memory: Mutex::new(Memory::default()),
        }
    }

    fn memory(&self) -> std::sync::MutexGuard<'_, Memory> {
        self.memory.lock().unwrap_or_else(PoisonError::into_inner)
    }

    /// Whether a row of the pool could still serve this request: asked before leaving a failed row for the next one. With none left, the client is
    /// told the failure it met, not that no row fits. `ready` asks for a row ready now. Nothing is recorded: the next `resolve` decides.
    pub fn can_go_on(&self, ask: &PoolQuestion<'_>, ready: bool) -> bool {
        let now = self.clock.epoch();
        self.rows(ask, now).iter().any(|row| row.eligible && (!ready || row.reason == "ready"))
    }

    /// The row that serves, and the journal's `pool_switch` when the pool's choice has moved.
    pub fn resolve(&self, ask: &PoolQuestion<'_>) -> (RowChoice, Option<Value>) {
        let now = self.clock.epoch();
        let live_rows = ask.pool.rows.iter().filter(|row| row.enabled && row.work != RowWork::Open).count();
        let goes_on_from_a_response =
            rules::RequestJson::read(ask.body).is_some_and(|payload| Coerce::truthy(payload.get("previous_response_id")));
        if goes_on_from_a_response && live_rows > 1 {
            return (RowChoice::Refused(PoolRefusal::of_context(ask.pool)), None);
        }
        let policy = &ask.settings.policy;
        let rows = self.rows(ask, now);
        let waits = |row: &RowState| policy.queue.yield_sec > 0 && row.eligible && row.reason == "busy";
        let first_ready = rows.iter().find(|row| row.eligible && (row.reason == "ready" || waits(row)));
        let chosen = first_ready.or_else(|| rows.iter().find(|row| row.eligible));
        let event = self.remember(ask.pool, &rows, chosen.map(|row| row.step_id.as_str()), now);
        let Some(chosen) = chosen else {
            let said: Vec<Value> = rows.iter().map(RowState::as_json).collect();
            return (RowChoice::Refused(PoolRefusal::of_rows(ask.pool, &said, now, ask.path, self.zone.as_ref())), event);
        };
        let choice = match (&chosen.target, &chosen.provider) {
            (Some(output), _) => {
                let way_on = rows.iter().any(|row| row.step_id != chosen.step_id && row.eligible && row.reason == "ready");
                RowChoice::Machine(MachineRow {
                    row_id: chosen.step_id.clone(),
                    output: output.clone(),
                    leave: QueueLeave::at_admission(policy, way_on),
                })
            }
            (None, Some(provider)) => {
                let model = chosen.said.get("model").and_then(Value::as_str).map_or_else(String::new, str::to_string);
                RowChoice::Cloud(CloudRow { row_id: chosen.step_id.clone(), provider: provider.clone(), model })
            }
            (None, None) => RowChoice::Refused(PoolRefusal::of_context(ask.pool)),
        };
        (choice, event)
    }

    /// The state the board reads, and the journal's row when the choice moved.
    fn remember(&self, pool: &Pool, rows: &[RowState], chosen: Option<&str>, now: f64) -> Option<Value> {
        let mut memory = self.memory();
        let said: Vec<Value> = rows.iter().map(RowState::as_json).collect();
        memory.states.insert(pool.id.clone(), json!({"selectedStepId": chosen, "steps": said, "decidedAt": now}));
        let previous = memory.selected.get(&pool.id).cloned();
        if previous.as_deref() == chosen {
            return None;
        }
        let reasons: Vec<Value> = rows
            .iter()
            .filter(|row| row.reason != "ready")
            .map(|row| json!({"stepId": row.step_id, "reason": row.reason}))
            .collect();
        let event = json!({"poolId": pool.id, "from": previous, "to": chosen, "at": now, "reasons": reasons});
        memory.events.push_back(event.clone());
        while memory.events.len() > Self::EVENTS_KEPT {
            memory.events.pop_front();
        }
        match chosen {
            Some(row) => {
                memory.selected.insert(pool.id.clone(), row.to_string());
            }
            None => {
                memory.selected.remove(&pool.id);
            }
        }
        Some(event)
    }

    /// The row's provider refused it for a limit before any output: its account rests, and the request goes on to the pool's next row. True for
    /// such a refusal; false for any other answer, which stays the row's. `retry_after` is the provider's own word.
    pub fn failed(&self, provider: &CloudProvider, status: u16, retry_after: Option<&str>) -> bool {
        let (reason, rest) = match status {
            401 => ("auth_rejected", 300),
            402 => ("payment", 300),
            429 => ("quota", 30),
            _ => return false,
        };
        // absent-ok: a word that is no number is the same as none: the rest of this kind of refusal.
        let said =
            retry_after.filter(|text| !text.is_empty()).map_or(Some(rest), |text| Coerce::int(&Value::String(text.to_string())));
        let delay = said.map_or(rest, |seconds| seconds.clamp(1, 3600));
        let now = self.clock.epoch();
        self.memory().blocked.insert(provider.usage_account_id.clone(), Blocked { reason, at: now, until: now + delay as f64 });
        true
    }

    /// What the state file carries to the board.
    pub fn snapshot(&self) -> Value {
        let memory = self.memory();
        json!({"pools": memory.states, "events": memory.events})
    }
}
