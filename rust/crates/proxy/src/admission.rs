//! A request waiting for a place on its model: the loop of `wait_for_proxy_slot`, for a
//! request with no graph queue over it.

use crate::client::ClientSide;
use crate::proxy::Proxy;
use crate::queue::Slot;
use crate::record::RequestRecord;
use crate::stop::Ending;
use rules::{LeaveTo, MachineOutput, Policy, QueueLeave};
use serde_json::{Value, json};
use std::time::Duration;

/// The wait of one request.
pub struct Admission<'a> {
    proxy: &'a Proxy,
    record: &'a RequestRecord,
    output: &'a MachineOutput,
    leave: QueueLeave,
    places: u32,
    client_timeout: i64,
}

impl<'a> Admission<'a> {
    /// How long the queue sleeps before it looks again, if nothing wakes it.
    const TURN: Duration = Duration::from_millis(250);

    /// The wait of `record`'s request for `output` under `policy`, until `leave` says it goes. The places are the scout's word, or the
    /// policy's number when it says none.
    pub fn new(
        proxy: &'a Proxy,
        record: &'a RequestRecord,
        output: &'a MachineOutput,
        policy: &Policy,
        leave: QueueLeave,
    ) -> Self {
        Self {
            proxy,
            record,
            output,
            leave,
            places: Self::places_of(proxy, output, policy),
            client_timeout: policy.queue.client_timeout(record.route.client_timeout_seconds).max(10),
        }
    }

    /// How many requests the model takes at once.
    fn places_of(proxy: &Proxy, output: &MachineOutput, policy: &Policy) -> u32 {
        let said = proxy.places.of(output).map(i64::from);
        // absent-ok: a figure past `u32` is no place count: one is what a model has at least.
        u32::try_from(said.unwrap_or(policy.max_slots)).unwrap_or(1).max(1)
    }

    /// Whether a place of the model is free now: `output_has_capacity`.
    pub fn has_room(proxy: &Proxy, output: &MachineOutput, policy: &Policy) -> bool {
        proxy.queue.taken(&output.group()) < Self::places_of(proxy, output, policy)
    }

    /// The request's line in the journal and on the board.
    fn entry(&self, started: f64) -> Value {
        json!({
            "id": self.record.id,
            "route": self.record.route.label,
            "port": self.record.route.port,
            "group": self.output.group(),
            "priority": self.record.route.priority,
            "queuedAt": started as i64,
            "preemptTried": false,
            "cloudTried": false,
            "queueNodeId": Value::Null,
            "thresholds": {"priorityAt": Value::Null, "cloudAt": Value::Null, "clientTimeoutSeconds": self.client_timeout},
        })
    }

    /// Waits until a place is taken: the place, and how long it took in milliseconds; or how the request ended meanwhile. `way_on` says
    /// whether the pool still has a row ready now, when the patience is over.
    pub fn wait(&self, client: &mut ClientSide, way_on: &dyn Fn() -> bool) -> Result<(Slot<'a>, i64), Ending> {
        let queue = &self.proxy.queue;
        let group = self.output.group();
        let (started, entry) = {
            let started = self.proxy.clock.epoch();
            (started, self.entry(started))
        };
        let seat = queue.enter(&self.record.id, &group);
        self.proxy.board.add_pending(entry.clone());
        self.note("queued", Some(&entry), json!({}));
        let ended = self.take_turns(&seat, client, started, &entry, way_on);
        self.proxy.board.remove_pending(&self.record.id);
        ended
    }

    fn take_turns(
        &self,
        seat: &crate::queue::Seat<'a>,
        client: &mut ClientSide,
        started: f64,
        entry: &Value,
        way_on: &dyn Fn() -> bool,
    ) -> Result<(Slot<'a>, i64), Ending> {
        let mut last_keepalive = started;
        let mut leave = self.leave;
        loop {
            let now = self.proxy.clock.epoch();
            let elapsed = now - started;
            let elapsed_ms = (elapsed * 1000.0).round() as i64;
            if client.has_left() {
                self.note("client_disconnected_queued", None, json!({"elapsedSec": Self::tenths(elapsed)}));
                return Err(Ending::ClientGone);
            }
            if client.head_sent() && now - last_keepalive >= Policy::KEEPALIVE_SEC {
                last_keepalive = now;
                self.keep_alive(client, elapsed)?;
            }
            self.tell_board(&leave, seat.position(), started, elapsed_ms);
            if let Some(slot) = seat.try_take(self.places) {
                self.proxy.board.update_active(
                    self.record.route.port,
                    &self.record.id,
                    json!({"slotAt": Self::thousandths(now)}),
                );
                self.note("admitted", Some(entry), json!({"queuedMs": elapsed_ms}));
                return Ok((slot, elapsed_ms));
            }
            if leave.due(elapsed) {
                if leave.to == LeaveTo::Next && way_on() {
                    self.note("queue_yield", Some(entry), json!({"queuedMs": elapsed_ms}));
                    return Err(Ending::Yielded(elapsed_ms));
                }
                if leave.to == LeaveTo::Next {
                    // Its pool has nowhere to go any more: the limit holds, from the start of the wait.
                    leave = leave.without_way();
                    continue;
                }
                self.note("queue_limit", Some(entry), json!({"queuedMs": elapsed_ms}));
                return Err(Self::limit_reached(&leave));
            }
            seat.wait(Self::TURN);
        }
    }

    fn keep_alive(&self, client: &mut ClientSide, elapsed: f64) -> Result<(), Ending> {
        if let Err(ending) = client.keepalive(self.record.model_said()) {
            self.note("client_disconnected_queued", None, json!({"elapsedSec": Self::tenths(elapsed)}));
            return Err(ending);
        }
        self.note("queue_keepalive", None, json!({"elapsedSec": Self::tenths(elapsed)}));
        Ok(())
    }

    fn tell_board(&self, leave: &QueueLeave, position: usize, started: f64, elapsed_ms: i64) {
        let (leave_at, leave_to) = leave.said(started);
        let queue = json!({
            "queuedMs": elapsed_ms,
            "position": position,
            "priority": self.record.route.priority,
            "since": Self::thousandths(started),
            "leaveAt": leave_at.map(Self::thousandths),
            "leaveTo": leave_to,
        });
        self.proxy.board.update_active(self.record.route.port, &self.record.id, json!({"phase": "queued", "queue": queue}));
    }

    fn limit_reached(leave: &QueueLeave) -> Ending {
        // absent-ok: `due` said it has a time, or this is not reached.
        let limit = leave.after.unwrap_or_default() as i64;
        Ending::Blocked { status: 503, words: format!("the model's queue waited its limit of {limit} s"), kind: "queue_timeout" }
    }

    fn note(&self, event: &str, item: Option<&Value>, fields: Value) {
        self.proxy.recorder.event(event, &self.record.route.label, &self.record.id, item, fields);
    }

    fn tenths(value: f64) -> f64 {
        (value * 10.0).round() / 10.0
    }

    fn thousandths(value: f64) -> f64 {
        (value * 1000.0).round() / 1000.0
    }
}
