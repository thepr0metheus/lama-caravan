//! What is said of one request: its identity, its running record and its finished one, in the shape the board and the
//! journal's readers know from `proxy()`.

use crate::pool_steps::{CloudRow, MachineRow};
use crate::recorder::Recorder;
use rules::{EffortSwap, ResponseSummary, Route, StreamFold, UsageWords};
use serde_json::{Map, Value, json};

/// Who asked what, fixed when the request came.
#[derive(Debug, Clone)]
pub struct RequestRecord {
    /// The request's id.
    pub id: String,
    /// The HTTP method.
    pub method: String,
    /// The path, without the query.
    pub path: String,
    /// The sender.
    pub client: String,
    /// When it came, epoch seconds.
    pub started: f64,
    /// The client's route.
    pub route: Route,
    /// The pool it came through.
    pub pool_id: String,
    /// The pool's name: what a client calls it.
    pub pool_name: String,
    /// The compact picture of the request.
    pub summary: Value,
    /// When its client gives up on it, epoch seconds.
    pub client_deadline: f64,
    /// The request this one reads a picture for, when it is the board's reader at work (`exchange/reading.rs`): the board
    /// lights the reader's cable for it, not its client's. `None` for a client's own request.
    pub reader_for: Option<String>,
}

/// The row a request is on, as its record says it. A request that has none, because no row fits, is the pool's own.
#[derive(Debug, Clone, Default)]
pub enum LegNow {
    /// No row yet.
    #[default]
    None,
    /// A machine's model.
    Machine(MachineRow),
    /// A provider.
    Cloud(CloudRow),
}

/// What the request has come to by its end.
#[derive(Debug, Clone)]
pub struct Facts {
    /// The status: 502 until an upstream says one.
    pub status: u16,
    /// Bytes sent to the client, heads aside.
    pub bytes: u64,
    /// Pieces sent to the client.
    pub chunks: u64,
    /// Milliseconds to the first byte for the client; `None` when none came.
    pub first_byte_ms: Option<i64>,
    /// The queue's part: `queuedMs`.
    pub queued_ms: i64,
    /// The summary of a whole answer.
    pub response: Value,
    /// What an event stream said.
    pub stream: StreamFold,
    /// The words of its failure.
    pub error: String,
    /// The kind of its failure.
    pub error_kind: String,
    /// What an Anthropic stream said it used, for a stream cut before its last chunk, where the usage rides.
    pub usage_said_so_far: Option<Value>,
    /// What the board's reader read for this request: its name, the pictures, and how many of them it had read before.
    /// `None` for a request nothing was read for.
    pub reading: Option<ReadFacts>,
    /// The effort the answering leg sent in place of the one asked.
    pub effort: Option<EffortSwap>,
}

impl Default for Facts {
    fn default() -> Self {
        Self {
            status: 502,
            bytes: 0,
            chunks: 0,
            first_byte_ms: None,
            queued_ms: 0,
            response: json!({}),
            stream: StreamFold::default(),
            error: String::new(),
            error_kind: String::new(),
            usage_said_so_far: None,
            effort: None,
            reading: None,
        }
    }
}

/// What the board's reader read for one request, as its record says it.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ReadFacts {
    /// The reader, as the board names it.
    pub reader: String,
    /// The pictures read.
    pub pictures: usize,
    /// Of them, the ones whose caption was kept from a reading before (`captions.rs`).
    pub kept: usize,
}

impl ReadFacts {
    /// The record's fields: `readerName` is what the board lights the reader's cable by (`static/js/pool-flow.js`).
    pub fn fields(&self) -> Value {
        json!({"readerName": self.reader, "readerPictures": self.pictures, "readerKept": self.kept})
    }
}

impl RequestRecord {
    /// The model the request names, as a sign of life repeats it.
    pub fn model_said(&self) -> &str {
        // absent-ok: it serves only a request that named one (`Front::with_body`).
        self.summary.get("model").and_then(Value::as_str).unwrap_or_default()
    }

    /// The pool the request came through.
    pub fn pool_id(&self) -> &str {
        &self.pool_id
    }

    /// The name of the route's own upstream, before a model is reached: a pool's route says its file's address.
    fn route_group(&self) -> String {
        format!("{}:{}", self.route.upstream_host, self.route.upstream_port)
    }

    /// The running record, when the request has just come: on its way to the pool's cable, as the board knows it.
    pub fn active_json(&self) -> Value {
        let pool = self.pool_id();
        let mut active = json!({
            "id": self.id,
            "method": self.method,
            "path": self.path,
            "client": self.client,
            "startedAt": self.started as i64,
            "clientDeadline": (self.client_deadline * 1000.0).round() / 1000.0,
            "route": self.route.label,
            "routeId": self.route.id,
            "upstream": self.route_group(),
            "upstreamType": "cloud",
            "providerId": pool,
            "routedOutputId": format!("cb:{pool}"),
            "routedOutputName": self.pool_name,
            "request": self.summary,
            "bytes": 0,
            "chunks": 0,
            "phase": "queued",
            "queue": {"queuedMs": 0, "position": Value::Null},
            "priority": self.route.priority,
            "proxy": Recorder::WHO,
        });
        // Said only for the reader's own request: a client's record keeps the shape every reader of the journal knows.
        if let (Some(reads_for), Value::Object(fields)) = (&self.reader_for, &mut active) {
            fields.insert("readerFor".to_string(), json!(reads_for));
        }
        active
    }

    /// What the record changes to when the request goes to a machine's row: the output and the machine, as the finished record says them
    /// (`leg_fields`), so that the board ties a running request and one just ended to the same machine.
    pub fn machine_patch(&self, row: &MachineRow) -> Value {
        json!({
            "upstream": row.output.group(),
            "upstreamHost": row.output.upstream_host,
            "upstreamPort": row.output.upstream_port,
            "upstreamType": "machine",
            "providerId": "",
            "routedOutputId": row.output.id,
            "cloudPoolId": self.pool_id(),
            "poolStepId": row.row_id,
        })
    }

    /// What the record changes to when the request goes to a provider's row.
    pub fn cloud_patch(&self, row: &CloudRow) -> Value {
        json!({"cloudPoolId": self.pool_id(), "cloudAccountId": row.provider.account_id, "poolStepId": row.row_id})
    }

    /// The output the board colours for a request on a provider's row, or for a pool's own answer.
    pub fn pool_output(&self) -> String {
        format!("cb:{}", self.pool_id())
    }

    /// The record of a request refused before it went anywhere: a paused client's.
    pub fn blocked_json(&self, status: u16, words: &str, kind: &str, now: f64) -> Value {
        let waited = ((now - self.started) * 1000.0).round() as i64;
        json!({
            "id": self.id, "method": self.method, "path": self.path, "client": self.client, "route": self.route.label,
            "routeId": self.route.id, "upstream": self.route_group(), "upstreamHost": self.route.upstream_host,
            "upstreamPort": self.route.upstream_port, "upstreamType": "cloud", "status": status, "startedAt": self.started as i64,
            "finishedAt": now as i64, "durationMs": waited, "bytes": 0, "chunks": 0, "firstByteMs": null, "request": self.summary,
            "queue": {"queuedMs": waited}, "response": {}, "stream": {}, "error": words, "errorKind": kind, "proxy": Recorder::WHO,
        })
    }

    /// The finished record. `latency` is the clock's word.
    pub fn finished_json(&self, facts: &Facts, leg: &LegNow, now: f64, latency: Value) -> Value {
        let mut record: Map<String, Value> = Map::new();
        let mut put = |name: &str, value: Value| {
            record.insert(name.to_string(), value);
        };
        put("id", json!(self.id));
        put("method", json!(self.method));
        put("path", json!(self.path));
        put("client", json!(self.client));
        put("route", json!(self.route.label));
        put("routeId", json!(self.route.id));
        match leg {
            LegNow::Machine(row) => {
                put("upstream", json!(row.output.group()));
                put("upstreamHost", json!(row.output.upstream_host));
                put("upstreamPort", json!(row.output.upstream_port));
            }
            LegNow::None | LegNow::Cloud(_) => {
                put("upstream", json!(self.route_group()));
                put("upstreamHost", json!(self.route.upstream_host));
                put("upstreamPort", json!(self.route.upstream_port));
            }
        }
        put("upstreamType", json!(if matches!(leg, LegNow::Machine(_)) { "machine" } else { "cloud" }));
        put("status", json!(facts.status));
        put("startedAt", json!(self.started as i64));
        put("finishedAt", json!(now as i64));
        put("durationMs", json!(((now - self.started) * 1000.0).round() as i64));
        put("bytes", json!(facts.bytes));
        put("chunks", json!(facts.chunks));
        put("firstByteMs", json!(facts.first_byte_ms));
        put("request", self.summary.clone());
        put("queue", json!({"queuedMs": facts.queued_ms, "preempted": ""}));
        put("latency", latency);
        put("priority", json!(self.route.priority));
        put("response", facts.response.clone());
        put("stream", facts.stream.as_json());
        put("error", json!(facts.error));
        put("errorKind", json!(facts.error_kind));
        put("usage", UsageWords::of(self.usage_said(facts)));
        if let Some(timings) = self.timings_said(facts) {
            put("timings", timings);
        }
        if let Some(swap) = &facts.effort {
            put("effort", swap.as_json());
        }
        for (name, value) in self.reading_fields(facts) {
            put(&name, value);
        }
        for (name, value) in Self::leg_fields(self.pool_id(), leg) {
            put(&name, value);
        }
        put("model", self.summary.get("model").filter(|model| model.is_string()).cloned().unwrap_or_else(|| json!("")));
        put("proxy", json!(Recorder::WHO));
        Value::Object(record)
    }

    /// What the record says of the board's reader: what it read for this request, and — for the reader's own request — the
    /// request it read for. Nothing for a request the reader has no part in, so its record keeps the shape it had.
    fn reading_fields(&self, facts: &Facts) -> Map<String, Value> {
        let mut fields = match facts.reading.as_ref().map(ReadFacts::fields) {
            Some(Value::Object(fields)) => fields,
            _ => Map::new(),
        };
        if let Some(reads_for) = &self.reader_for {
            fields.insert("readerFor".to_string(), json!(reads_for));
        }
        fields
    }

    /// What the record says of the row that answered, or of a pool that answered itself. The output it names is the running record's
    /// (`active_json`, `machine_patch`): the finished one said none, and the board's cable to a machine stayed dark for a request just
    /// ended there (2026-11-03).
    fn leg_fields(pool_id: &str, leg: &LegNow) -> Map<String, Value> {
        let fields = match leg {
            LegNow::None => json!({"providerId": pool_id, "cloudAccountId": "", "routedOutputId": format!("cb:{pool_id}")}),
            LegNow::Machine(row) => json!({
                "providerId": "", "cloudAccountId": "", "cloudPoolId": pool_id, "poolStepId": row.row_id, "cloudModel": "",
                "credentialAccountId": null, "routedOutputId": row.output.id,
            }),
            LegNow::Cloud(row) => json!({
                "providerId": pool_id, "cloudAccountId": row.provider.account_id, "cloudPoolId": pool_id, "poolStepId": row.row_id,
                "cloudModel": row.model, "credentialAccountId": row.provider.credential_account_id, "routedOutputId": format!("cb:{pool_id}"),
            }),
        };
        match fields {
            Value::Object(fields) => fields,
            _ => Map::new(),
        }
    }

    /// The usage the whole answer or the stream said.
    fn usage_said<'f>(&self, facts: &'f Facts) -> Option<&'f Value> {
        facts
            .response
            .get("usage")
            .filter(|usage| usage.is_object())
            .or(facts.stream.usage.as_ref())
            .or(facts.usage_said_so_far.as_ref())
    }

    /// The exact timings, when a cell gave them.
    fn timings_said(&self, facts: &Facts) -> Option<Value> {
        let said = match facts.response.get("timings").filter(|timings| timings.is_object()) {
            Some(timings) => Some(timings),
            None => facts.stream.timings.as_ref(),
        };
        said.filter(|timings| timings.as_object().is_some_and(|fields| !fields.is_empty())).cloned()
    }
}

/// The summary of what a whole answer's first bytes hold, or `{}`.
pub struct CapturedAnswer;

impl CapturedAnswer {
    /// The summary of the captured bytes; bytes that do not read say nothing.
    pub fn summary(captured: &[u8]) -> Value {
        let parsed = serde_json::from_slice::<Value>(captured).unwrap_or_else(|_| json!({}));
        ResponseSummary::of(&parsed)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use rules::{LeaveTo, MachineOutput, QueueLeave, Route};

    fn record() -> RequestRecord {
        RequestRecord {
            id: "r1".to_string(),
            method: "POST".to_string(),
            path: "/v1/chat/completions".to_string(),
            client: "10.0.0.2".to_string(),
            started: 100.0,
            route: Route::normalize(&json!({"label": "Open WebUI", "id": "client-ow"})).unwrap(),
            pool_id: "live:mm:a".to_string(),
            pool_name: "deepseek".to_string(),
            summary: json!({"model": "deepseek"}),
            client_deadline: 200.0,
            reader_for: None,
        }
    }

    fn machine_row() -> MachineRow {
        let output = MachineOutput::read(&json!({"id": "mm:a", "upstreamType": "machine", "upstreamModel": "deepseek", "upstreamHost": "10.0.0.20", "upstreamPort": 8092})).unwrap();
        MachineRow {
            row_id: "r1".to_string(),
            output,
            leave: QueueLeave { after: None, to: LeaveTo::Refuse, limit: None },
            read_first: false,
        }
    }

    #[test]
    fn a_request_on_a_machine_names_its_output_and_the_machine_while_it_runs_and_when_it_ended() {
        let record = record();
        let row = machine_row();
        let running = record.machine_patch(&row);
        let finished = record.finished_json(&Facts { status: 200, ..Facts::default() }, &LegNow::Machine(row), 110.0, json!({}));
        for (what, said) in [("running", &running), ("finished", &finished)] {
            assert_eq!(
                (
                    said["routedOutputId"].clone(),
                    said["upstreamHost"].clone(),
                    said["upstreamPort"].clone(),
                    said["upstreamType"].clone()
                ),
                (json!("mm:a"), json!("10.0.0.20"), json!(8092), json!("machine")),
                "{what}"
            );
        }
    }

    #[test]
    fn a_pool_s_own_answer_names_the_pool_s_output_as_its_running_record_did() {
        let record = record();
        let finished = record.finished_json(&Facts::default(), &LegNow::None, 110.0, json!({}));
        assert_eq!(finished["routedOutputId"], json!("cb:live:mm:a"));
        assert_eq!(record.active_json()["routedOutputId"], finished["routedOutputId"]);
        assert_eq!(finished["upstreamType"], json!("cloud"), "negative: no machine is named for it");
    }
}
