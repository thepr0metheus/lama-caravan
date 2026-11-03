//! One request the proxy serves, from its coming to its record. What `proxy()` does for a client of the
//! entry: down its pool's rows until one answers; each part of it is another object's, and this one says their order.

use crate::admission::Admission;
use crate::client::ClientSide;
use crate::clock::RequestClock;
use crate::pool_steps::{PoolQuestion, RowChoice};
use crate::proxy::Proxy;
use crate::record::{Facts, LegNow, RequestRecord};
use crate::stop::Ending;
use crate::upstream::Answer;
use crate::watch::Watch;
use files::Settings;
use rules::{MachineOutput, OpenAiDialect, Pool, PoolRefusal, UpstreamFailure};
use serde_json::{Value, json};
use std::collections::BTreeSet;
use std::sync::Arc;
use wire::Headers;

mod answers;
mod cloud;
mod machine;

/// What the request came with.
pub struct Asked {
    /// Its fields.
    pub headers: Headers,
    /// Its target: the path and the query.
    pub target: String,
    /// Its body.
    pub body: Vec<u8>,
    /// Whether the client asked for a stream.
    pub streaming: bool,
}

/// What this request has walked so far.
#[derive(Debug, Default)]
struct Walk {
    /// What it tried: `row:<id>`, and the accounts that refused it. Shared quota owners are excluded together, so a duplicate cannot evade a limit.
    excluded: BTreeSet<String>,
    /// Legs a pool may take for one request: each failed row is excluded, so a pool of N rows takes at most N. The bound only stops a loop that
    /// a fault elsewhere would make endless.
    legs: u32,
    /// A refusal of the effort a model does not take is asked again once a request.
    effort_asked_again: bool,
}

/// What comes after a leg.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Next {
    /// The pool's next row is asked.
    Again,
    /// The client has its answer.
    Done,
}

/// What a pool is asked, by the parts of a request that do not change on its way.
struct PoolAsk<'p> {
    proxy: &'p Proxy,
    settings: &'p Settings,
    pool: &'p Pool,
    body: &'p [u8],
    path: &'p str,
}

impl PoolAsk<'_> {
    fn can_go_on(&self, excluded: &BTreeSet<String>, ready: bool) -> bool {
        let free = |output: &MachineOutput| Admission::has_room(self.proxy, output, &self.settings.policy);
        self.proxy.pools.can_go_on(
            &PoolQuestion { settings: self.settings, pool: self.pool, body: self.body, path: self.path, excluded, free: &free },
            ready,
        )
    }

    fn can_go_on_past(&self, excluded: &BTreeSet<String>, row: &str, ready: bool) -> bool {
        let mut past = excluded.clone();
        past.insert(row.to_string());
        self.can_go_on(&past, ready)
    }
}

/// The walk of one request.
pub struct Exchange<'a> {
    proxy: &'a Proxy,
    settings: Arc<Settings>,
    record: &'a RequestRecord,
    pool: Pool,
    asked: Asked,
    client: ClientSide,
    clock: RequestClock,
    watch: Watch<'a>,
    dialect: OpenAiDialect,
    facts: Facts,
    upstream_error_text: String,
    leg: LegNow,
}

impl<'a> Exchange<'a> {
    /// From here a row's answer is its failure: a request-specific 4xx stays the client's.
    const SERVER_ERROR: u16 = 500;
    /// The bound of `Walk::legs`.
    const MOST_LEGS: u32 = 16;
    /// How much of an upstream's words a `pool_retry` keeps.
    const RETRY_WORDS: usize = 300;

    /// The walk of `record`'s request down `pool`.
    pub fn new(
        proxy: &'a Proxy,
        settings: Arc<Settings>,
        record: &'a RequestRecord,
        pool: Pool,
        asked: Asked,
        client: ClientSide,
    ) -> Self {
        Self {
            clock: RequestClock::new(Arc::clone(&proxy.clock)),
            watch: Watch::new(proxy, record, asked.streaming),
            dialect: OpenAiDialect::new(&pool.name),
            proxy,
            settings,
            record,
            pool,
            asked,
            client,
            facts: Facts::default(),
            upstream_error_text: String::new(),
            leg: LegNow::None,
        }
    }

    /// Walks the request to its end. Every way out goes through `finish`: a request that came has a record.
    pub fn run(mut self) {
        self.note_received();
        if self.record.route.is_paused() {
            return self.held_back();
        }
        let ended = Ending::guarded(|| self.serve());
        self.finish(ended);
    }

    /// A paused client's request names a model it may call, and goes no further: its record says so, as a request a queue refused.
    fn held_back(&mut self) {
        const STATUS: u16 = 503;
        const KIND: &str = "blocked";
        let route = &self.record.route;
        let words = format!("proxy route {} is {}", route.label, route.mode);
        let told = self.dialect.failure(STATUS, KIND);
        // A client gone before its refusal changes nothing here.
        drop(self.client.send_told(&told, &self.record.id));
        let result = self.record.blocked_json(STATUS, &words, KIND, self.proxy.clock.epoch());
        self.proxy.board.finish_active(route.port, &self.record.id, result.clone());
        self.note("blocked", Some(&result), json!({"status": STATUS}));
    }

    fn pool_ask(&self) -> PoolAsk<'_> {
        PoolAsk { proxy: self.proxy, settings: &self.settings, pool: &self.pool, body: &self.asked.body, path: &self.record.path }
    }

    fn note_received(&self) {
        let active = self.record.active_json();
        self.proxy.board.add_active(&self.record.route.label, self.record.route.port, active.clone());
        self.note("received", Some(&active), json!({}));
    }

    fn serve(&mut self) -> Result<(), Ending> {
        // A pool's route is admitted at once, and the wait is the leg's: `prepMs` holds the model's queue.
        self.clock.queue_entered();
        self.clock.admitted();
        self.update(json!({"phase": "received", "queue": {"queuedMs": 0, "preempted": ""}}));
        let mut walk = Walk::default();
        loop {
            // Each leg starts from the pool's route: what a failed leg said of itself is no part of the next.
            self.leg = LegNow::None;
            self.facts.status = 502;
            self.upstream_error_text.clear();
            self.facts.effort = None;
            let next = match self.choose(&walk) {
                RowChoice::Refused(refusal) => self.pool_refused(&refusal)?,
                RowChoice::Machine(row) => self.machine_leg(row, &mut walk)?,
                RowChoice::Cloud(row) => self.cloud_leg(row, &mut walk)?,
            };
            if next == Next::Done {
                return Ok(());
            }
        }
    }

    fn choose(&self, walk: &Walk) -> RowChoice {
        self.proxy.choose_row(&self.settings, &self.pool, &self.asked.body, &self.record.path, &walk.excluded)
    }

    /// The pool answers this leg itself, no row fits now: nothing is sent, and the journal and the board say so, instead of blaming the provider
    /// for a 429 it never gave.
    fn pool_refused(&mut self, refusal: &PoolRefusal) -> Result<Next, Ending> {
        let meta = rules::ProviderBodyWords::of(&self.asked.body);
        self.note_started(meta.clone(), Some(json!({})));
        self.facts.status = refusal.status;
        self.update(json!({
            "phase": "reading",
            "status": refusal.status,
            "response": {"contentType": "application/json", "headers": {"server": "", "xRequestId": ""}},
        }));
        let fields = json!({"status": refusal.status, "contentType": "application/json", "upstreamErrorBody": refusal.journal_body, "cloudMeta": meta});
        self.note("upstream_response", None, fields);
        self.proxy.pools.health.note_status(
            &self.record.pool_output(),
            refusal.status,
            &refusal.journal_body,
            self.proxy.clock.epoch(),
        );
        self.facts.error.clone_from(&refusal.message);
        self.facts.error_kind = refusal.kind.to_string();
        let told = refusal.told(&self.dialect);
        self.facts.bytes += told.body.len() as u64;
        if self.client.head_sent() {
            let payload: Value = serde_json::from_slice(&told.body).unwrap_or(Value::Null);
            self.client.send_stream_error(&payload)?;
        } else {
            self.client.send_told(&told, &self.record.id)?;
        }
        Ok(Next::Done)
    }

    fn note_started(&self, meta: Option<Value>, headers: Option<Value>) {
        self.update(json!({"phase": "upstream"}));
        let active = self.proxy.board.active_item(self.record.route.port, &self.record.id);
        let queue = json!({"queuedMs": self.facts.queued_ms, "preempted": ""});
        self.note("upstream_started", active.as_ref(), json!({"queue": queue, "cloudMeta": meta, "cloudHeaders": headers}));
    }

    fn note_answer(&mut self, answer: &Answer, meta: Option<Value>) {
        let content_type = answer.head.headers.text_of("Content-Type");
        self.facts.status = answer.head.status;
        self.upstream_error_text = answer.error_text();
        self.update(json!({
            "phase": if answer.is_event_stream() { "streaming" } else { "reading" },
            "status": answer.head.status,
            "response": {"contentType": content_type, "headers": {
                "server": answer.head.headers.text_of("Server"),
                "xRequestId": answer.head.headers.text_of("X-Request-Id"),
            }},
        }));
        let error_body = (!self.upstream_error_text.is_empty()).then(|| self.upstream_error_text.clone());
        self.note(
            "upstream_response",
            None,
            json!({"status": answer.head.status, "contentType": content_type, "upstreamErrorBody": error_body, "cloudMeta": meta}),
        );
    }

    /// What is said at the end: the failure told to the client when there is one to tell it to, then the record.
    fn finish(&mut self, ended: Result<(), Ending>) {
        if let Err(ending) = ended {
            self.take_ending(ending);
        }
        if self.facts.status >= 400 && self.facts.error.is_empty() && self.facts.error_kind.is_empty() {
            let (reason, kind) = UpstreamFailure::summary(self.facts.status, &self.upstream_error_text);
            self.facts.error = reason;
            self.facts.error_kind = kind;
        }
        let result = self.record.finished_json(&self.facts, &self.leg, self.proxy.clock.epoch(), self.clock.as_json());
        self.proxy.board.finish_active(self.record.route.port, &self.record.id, result.clone());
        let fields = json!({"status": self.facts.status, "error": self.facts.error, "errorKind": self.facts.error_kind});
        self.note("finished", Some(&result), fields);
    }

    fn take_ending(&mut self, ending: Ending) {
        let (words, kind) = match ending {
            Ending::ClientGone => {
                self.note_client_gone();
                self.facts.error = "client disconnected (upstream generation aborted)".to_string();
                self.facts.error_kind = "client_disconnected".to_string();
                return;
            }
            Ending::Stopped(words) => (words, "stopped"),
            Ending::Blocked { status, words, kind } => {
                self.facts.status = status;
                (words, kind)
            }
            Ending::Upstream(end) => (end.words, end.kind),
            Ending::Inside(words) => (words, "proxy_error"),
            // A wait's end goes on to the pool's next row (`left_the_queue`) before it comes here.
            Ending::Yielded(waited) => (waited.to_string(), "queue_timeout"),
        };
        self.tell_failure(kind);
        self.facts.error = words;
        self.facts.error_kind = kind.to_string();
    }

    /// The failure, in the dialect's words. A client gone before its refusal changes nothing here.
    fn tell_failure(&mut self, kind: &str) {
        let told = if self.client.head_sent() {
            self.client.send_stream_error(&self.dialect.stream_failure(kind))
        } else {
            let told = self.dialect.failure(self.facts.status, kind);
            self.client.send_told(&told, &self.record.id)
        };
        drop(told);
    }

    fn note_client_gone(&self) {
        let elapsed = ((self.proxy.clock.epoch() - self.record.started) * 10.0).round() / 10.0;
        self.note("client_gone_probe", None, json!({"elapsedSec": elapsed, "hadSock": self.clock.connected_once()}));
    }

    fn update(&self, patch: Value) {
        self.proxy.board.update_active(self.record.route.port, &self.record.id, patch);
    }

    fn note(&self, event: &str, item: Option<&Value>, fields: Value) {
        self.proxy.recorder.event(event, &self.record.route.label, &self.record.id, item, fields);
    }
}
