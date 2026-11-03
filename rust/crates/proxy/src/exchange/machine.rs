//! A row of a machine: its model's queue, then its model.

use super::{Exchange, Next, PoolAsk, Walk};
use crate::admission::Admission;
use crate::pool_steps::MachineRow;
use crate::record::LegNow;
use crate::stop::{Ending, UpstreamEnd};
use crate::upstream::UpstreamCall;
use serde_json::json;
use std::sync::Arc;

impl Exchange<'_> {
    /// A row of a machine: the model's queue, as a local route waits in it, then its model. A stream gets its keepalive first.
    pub(super) fn machine_leg(&mut self, row: MachineRow, walk: &mut Walk) -> Result<Next, Ending> {
        self.update(self.record.machine_patch(&row));
        self.leg = LegNow::Machine(row.clone());
        if self.asked.streaming && !self.client.head_sent() {
            self.client.open_stream()?;
        }
        let row_key = format!("row:{}", row.row_id);
        let settings = Arc::clone(&self.settings);
        let ask =
            PoolAsk { proxy: self.proxy, settings: &settings, pool: &self.pool, body: &self.asked.body, path: &self.record.path };
        let admission = Admission::new(self.proxy, self.record, &row.output, &settings.policy, row.leave);
        let way_on = || ask.can_go_on_past(&walk.excluded, &row_key, true);
        let place = match admission.wait(&mut self.client, &way_on) {
            Ok((place, queued_ms)) => {
                self.facts.queued_ms += queued_ms;
                place
            }
            Err(ending @ (Ending::Yielded(_) | Ending::Blocked { .. })) => {
                return self.left_the_queue(ending, &row, row_key, walk);
            }
            Err(other) => return Err(other),
        };
        self.note_started(None, None);
        let mut call = UpstreamCall::new(
            self.proxy,
            self.record,
            &row.output,
            &self.asked.headers,
            &self.asked.target,
            self.asked.body.clone(),
        );
        let loading_wait = settings.policy.loading_model_wait_sec as f64;
        let answer = match call.ask(&mut self.clock, &mut self.watch, &mut self.client, loading_wait) {
            Ok(answer) => answer,
            Err(Ending::Upstream(end)) => return self.machine_failed(end, &row, row_key, walk),
            Err(other) => return Err(other),
        };
        self.note_answer(&answer, None);
        let status = answer.head.status;
        self.proxy.pools.health.note_status(&row.output.id, status, &self.upstream_error_text, self.proxy.clock.epoch());
        if status >= Self::SERVER_ERROR && self.goes_on(walk, &row_key) {
            let fields = json!({"poolId": self.record.pool_id(), "stepId": row.row_id, "output": row.output.id, "status": status, "reason": "status", "upstreamErrorBody": self.retry_words()});
            self.note("pool_retry", None, fields);
            walk.excluded.insert(row_key);
            walk.legs += 1;
            return Ok(Next::Again);
        }
        let answered = self.relay_machine(answer);
        drop(place);
        answered.map(|()| Next::Done)
    }

    /// The model's queue let it go, its patience over or its limit: the pool's next row is asked, or, with none left, the request is refused as
    /// a queue's is.
    fn left_the_queue(&mut self, ending: Ending, row: &MachineRow, row_key: String, walk: &mut Walk) -> Result<Next, Ending> {
        walk.excluded.insert(row_key);
        if !self.pool_ask().can_go_on(&walk.excluded, false) {
            self.facts.status = 503;
            return Err(match ending {
                Ending::Blocked { .. } => ending,
                _ => Ending::Blocked {
                    status: 503,
                    words: "the cell's queue gave up on the request".to_string(),
                    kind: "queue_timeout",
                },
            });
        }
        let (reason, error) = match &ending {
            Ending::Yielded(waited) => ("yield", waited.to_string()),
            Ending::Blocked { words, .. } => ("queue", words.clone()),
            _ => ("queue", String::new()),
        };
        let fields = json!({"poolId": self.record.pool_id(), "stepId": row.row_id, "output": row.output.id, "reason": reason, "error": error});
        self.note("pool_retry", None, fields);
        Ok(Next::Again)
    }

    fn machine_failed(&mut self, end: UpstreamEnd, row: &MachineRow, row_key: String, walk: &mut Walk) -> Result<Next, Ending> {
        self.proxy.pools.health.note_error(&row.output.id, None, "connect", &end.words, self.proxy.clock.epoch());
        if !self.goes_on(walk, &row_key) {
            return Err(Ending::Upstream(end));
        }
        let words = format!("upstream connect failed: {}", end.words);
        let fields = json!({"poolId": self.record.pool_id(), "stepId": row.row_id, "output": row.output.id, "status": 0, "reason": "connect", "upstreamErrorBody": rules::Coerce::first_letters(&words, Self::RETRY_WORDS)});
        self.note("pool_retry", None, fields);
        walk.excluded.insert(row_key);
        walk.legs += 1;
        Ok(Next::Again)
    }

    /// Whether a row that failed before its first byte sends the request on: with no row left the client is told the failure it met, not that
    /// no row fits.
    pub(super) fn goes_on(&self, walk: &Walk, row_key: &str) -> bool {
        self.facts.bytes == 0
            && self.facts.chunks == 0
            && walk.legs < Self::MOST_LEGS
            && self.pool_ask().can_go_on_past(&walk.excluded, row_key, false)
    }

    pub(super) fn retry_words(&self) -> Option<String> {
        (!self.upstream_error_text.is_empty())
            .then(|| rules::Coerce::first_letters(&self.upstream_error_text, Self::RETRY_WORDS).to_string())
    }
}
