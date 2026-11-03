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
        }
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
        json!({
            "id": self.id,
            "method": self.method,
            "path": self.path,
            "client": self.client,
            "startedAt": self.started as i64,
            "clientDeadline": (self.client_deadline * 1000.0).round() / 1000.0,
            "route": self.route.label,
            "port": self.route.port,
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
        })
    }

    /// What the record changes to when the request goes to a machine's row.
    pub fn machine_patch(&self, row: &MachineRow) -> Value {
        json!({
            "upstream": row.output.group(),
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
            "port": self.route.port, "upstream": self.route_group(), "upstreamHost": self.route.upstream_host,
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
        put("port", json!(self.route.port));
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
        for (name, value) in Self::leg_fields(self.pool_id(), leg) {
            put(&name, value);
        }
        put("model", self.summary.get("model").filter(|model| model.is_string()).cloned().unwrap_or_else(|| json!("")));
        put("proxy", json!(Recorder::WHO));
        Value::Object(record)
    }

    /// What the record says of the row that answered, or of a pool that answered itself.
    fn leg_fields(pool_id: &str, leg: &LegNow) -> Map<String, Value> {
        let fields = match leg {
            LegNow::None => json!({"providerId": pool_id, "cloudAccountId": ""}),
            LegNow::Machine(row) => json!({
                "providerId": "", "cloudAccountId": "", "cloudPoolId": pool_id, "poolStepId": row.row_id, "cloudModel": "",
                "credentialAccountId": null,
            }),
            LegNow::Cloud(row) => json!({
                "providerId": pool_id, "cloudAccountId": row.provider.account_id, "cloudPoolId": pool_id, "poolStepId": row.row_id,
                "cloudModel": row.model, "credentialAccountId": row.provider.credential_account_id,
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
