//! A row of a provider: the request said in its words, its limits and its refusals.

use super::{Exchange, Next, Walk};
use crate::pool_steps::CloudRow;
use crate::provider_call::{AnswerWindows, Miss, ProviderCall};
use crate::provider_request::ProviderRequest;
use crate::record::LegNow;
use crate::stop::{Ending, UpstreamEnd};
use serde_json::{Value, json};
use std::sync::Arc;

impl Exchange<'_> {
    /// A row of a provider.
    pub(super) fn cloud_leg(&mut self, row: CloudRow, walk: &mut Walk) -> Result<Next, Ending> {
        self.update(self.record.cloud_patch(&row));
        self.leg = LegNow::Cloud(row.clone());
        let settings = Arc::clone(&self.settings);
        let request = ProviderRequest::build(self.proxy, &settings, &row, &self.asked, &self.record.path)?;
        if let Some(swap) = &request.swap {
            self.update(json!({"effort": swap.as_json()}));
        }
        self.note_started(request.meta(), Some(request.fields_for_journal()));
        let output = self.record.pool_output();
        let call = ProviderCall::new(self.proxy, self.record, &request);
        let row_key = format!("row:{}", row.row_id);
        let mut answer = match call.ask(&mut self.clock, &mut self.watch, &mut self.client) {
            Ok(answer) => answer,
            Err(Miss::Ended(ending)) => return Err(ending),
            Err(Miss::Socket(error)) => return self.provider_failed(&error, &request, &row, row_key, walk),
        };
        let now = self.proxy.clock.epoch();
        if row.provider.subscription {
            self.proxy.pools.usage.keep(&row.provider.usage_account_id, AnswerWindows::of(&answer.head.headers), now);
        }
        self.note_answer(&answer, request.meta());
        let status = answer.head.status;
        self.proxy.pools.health.note_status(&output, status, &self.upstream_error_text, now);
        if !walk.effort_asked_again && self.facts.bytes == 0 {
            // A provider refusing the effort its model does not take, and listing those it does: the same leg is asked again, once, with the nearest.
            if let Some(lesson) = self.proxy.efforts.learn(request.host(), &request.body, status, &self.upstream_error_text) {
                walk.effort_asked_again = true;
                let fields = json!({"host": request.host(), "model": lesson.model, "asked": lesson.asked, "sent": lesson.sent, "takes": lesson.takes});
                self.note("effort_retry", None, fields);
                return Ok(Next::Again);
            }
        }
        // A row's provider refusing it for a limit sends the request on to the pool's next row, only before output. Other errors are the row's.
        let waited = answer.head.headers.get("Retry-After");
        if self.facts.bytes == 0 && self.facts.chunks == 0 && self.proxy.pools.failed(&row.provider, status, waited.as_deref()) {
            walk.excluded.insert(row.provider.usage_account_id.clone());
            let fields = json!({"poolId": self.record.pool_id(), "stepId": row.row_id, "accountId": row.provider.account_id, "status": status});
            self.note("pool_retry", None, fields);
            return Ok(Next::Again);
        }
        if status >= Self::SERVER_ERROR && self.goes_on(walk, &row_key) {
            let fields = json!({"poolId": self.record.pool_id(), "stepId": row.row_id, "output": Value::Null, "status": status, "reason": "status", "upstreamErrorBody": self.retry_words()});
            self.note("pool_retry", None, fields);
            walk.excluded.insert(row_key);
            walk.legs += 1;
            return Ok(Next::Again);
        }
        self.facts.effort.clone_from(&request.swap);
        self.relay_cloud(&request, &mut answer)?;
        self.keep_connection(request.target.clone(), answer);
        Ok(Next::Done)
    }

    fn provider_failed(
        &mut self,
        error: &std::io::Error,
        request: &ProviderRequest,
        row: &CloudRow,
        row_key: String,
        walk: &mut Walk,
    ) -> Result<Next, Ending> {
        let words = rules::Coerce::first_letters(&error.to_string(), 200).to_string();
        let said = format!("upstream connect failed: {words}");
        self.update(json!({"phase": "reading", "status": 502, "response": {"contentType": "", "headers": {"server": "", "xRequestId": ""}}}));
        self.note(
            "upstream_response",
            None,
            json!({"status": 502, "contentType": "", "upstreamErrorBody": said, "cloudMeta": request.meta()}),
        );
        self.proxy.pools.health.note_error(&self.record.pool_output(), None, "connect", &words, self.proxy.clock.epoch());
        if !self.goes_on(walk, &row_key) {
            return Err(Ending::Upstream(UpstreamEnd::of(error)));
        }
        let fields = json!({"poolId": self.record.pool_id(), "stepId": row.row_id, "output": Value::Null, "status": 0, "reason": "connect", "upstreamErrorBody": rules::Coerce::first_letters(&said, Self::RETRY_WORDS)});
        self.note("pool_retry", None, fields);
        walk.excluded.insert(row_key);
        walk.legs += 1;
        Ok(Next::Again)
    }
}
