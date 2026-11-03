//! A local model's queue.

use crate::policy::Policy;

/// The settings as the proxy reads them: whole seconds within their bounds; an unsaid or a broken value is its default.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ModelQueuePolicy {
    /// Seconds a request waits for a busy model while its pool could go on.
    pub yield_sec: i64,
    /// Seconds a request waits with nowhere to go; 0 is no limit.
    pub limit_sec: i64,
    /// Seconds a client waits for its whole answer when its route says none.
    pub client_timeout_sec: i64,
}

impl ModelQueuePolicy {
    /// Seconds a request waits with nowhere to go, or `None`: no limit.
    pub fn limit(&self) -> Option<i64> {
        (self.limit_sec > 0).then_some(self.limit_sec)
    }

    /// Seconds the client of a route waits for its whole answer: its own, else everyone's.
    pub fn client_timeout(&self, own: i64) -> i64 {
        if own > 0 { own } else { self.client_timeout_sec }
    }
}

/// Where a request goes when it leaves a model's queue.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LeaveTo {
    /// On to its pool's next ready row.
    Next,
    /// Out, its client answered 503.
    Refuse,
}

impl LeaveTo {
    /// The word the board reads on the request.
    pub fn word(self) -> &'static str {
        match self {
            Self::Next => "next",
            Self::Refuse => "refuse",
        }
    }
}

/// When a request waiting in a model's queue leaves it, and where to. Decided at admission and kept on the request: the
/// proxy acts on it, the board draws it.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct QueueLeave {
    /// Seconds from the start of the wait; `None` for a request that does not leave by itself.
    pub after: Option<f64>,
    /// Where it goes.
    pub to: LeaveTo,
    /// The limit it falls back on when its pool has no way on any more.
    pub limit: Option<f64>,
}

impl QueueLeave {
    /// The leave of a request admitted to a model's queue. `way_on`: whether its pool has another row ready now.
    pub fn at_admission(policy: &Policy, way_on: bool) -> Self {
        let rule = policy.queue;
        let limit = rule.limit().map(|seconds| seconds as f64);
        if way_on {
            return Self { after: Some(rule.yield_sec as f64), to: LeaveTo::Next, limit };
        }
        Self { after: limit, to: LeaveTo::Refuse, limit }
    }

    /// Whether the request has waited its time.
    pub fn due(&self, waited: f64) -> bool {
        self.after.is_some_and(|after| waited >= after)
    }

    /// The leave once its pool has nowhere to go: the limit holds, counted from the start of the wait.
    pub fn without_way(&self) -> Self {
        Self { after: self.limit, to: LeaveTo::Refuse, limit: self.limit }
    }

    /// When it leaves in epoch seconds, and where to; both `None` while it does not leave by itself.
    pub fn said(&self, since: f64) -> (Option<f64>, Option<&'static str>) {
        match self.after {
            None => (None, None),
            Some(after) => (Some(since + after), Some(self.to.word())),
        }
    }
}
