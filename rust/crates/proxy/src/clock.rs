//! The clocks, as parameters, and where one request's time went.

use os::LocalTime;
use rules::WallClock;
use serde_json::{Value, json};
use std::sync::Arc;

/// The zone schedules are read in: the one this process keeps time in, `TZ` or the machine's own.
#[derive(Debug, Clone, Copy, Default)]
pub struct SystemZone;

impl WallClock for SystemZone {
    fn minute_of_week(&self, epoch: f64) -> i64 {
        // absent-ok: the C library places every moment of this century; none here would read as Monday's first minute.
        LocalTime::of(epoch as i64).map_or(0, |at| i64::from(at.weekday) * 1440 + i64::from(at.hour) * 60 + i64::from(at.minute))
    }

    fn epoch_of_week_minute(&self, epoch: f64, minute: i64) -> i64 {
        LocalTime::epoch_of_week_minute(epoch as i64, minute).unwrap_or(epoch as i64)
    }

    fn text(&self, epoch: i64) -> String {
        LocalTime::of(epoch).map_or_else(String::new, |at| {
            let (sign, offset) = if at.offset_minutes >= 0 { ('+', at.offset_minutes) } else { ('-', -at.offset_minutes) };
            format!("{} {:02}:{:02} UTC{sign}{:02}:{:02}", at.date(), at.hour, at.minute, offset / 60, offset % 60)
        })
    }
}

pub use os::clock::{Clock, SystemClock};

/// Where one request's time went, in milliseconds. A mark that never happened stays `None`: a request answered by the caravan
/// itself never connected, and 0 there would read as "instant". `connReused` is `None` where nothing is kept, as for a cell:
/// "not kept" would claim a choice.
pub struct RequestClock {
    clock: Arc<dyn Clock>,
    cpu_started: Option<f64>,
    received: f64,
    queue_entered: Option<f64>,
    admitted: Option<f64>,
    leg_started: Option<f64>,
    connect_ms: Option<f64>,
    reused: Option<bool>,
    sent: Option<f64>,
    headers: Option<f64>,
    first_bytes: Option<f64>,
}

impl RequestClock {
    /// The clock of a request whose body has just come in.
    pub fn new(clock: Arc<dyn Clock>) -> Self {
        Self {
            cpu_started: clock.thread_cpu(),
            received: clock.monotonic(),
            clock,
            queue_entered: None,
            admitted: None,
            leg_started: None,
            connect_ms: None,
            reused: None,
            sent: None,
            headers: None,
            first_bytes: None,
        }
    }

    /// The request began to wait for its queue.
    pub fn queue_entered(&mut self) {
        self.queue_entered = Some(self.clock.monotonic());
    }

    /// The wait is over.
    pub fn admitted(&mut self) {
        self.admitted = Some(self.clock.monotonic());
    }

    /// Prep ends where the first upstream attempt begins; later legs keep it.
    pub fn leg_started(&mut self) {
        if self.leg_started.is_none() {
            self.leg_started = Some(self.clock.monotonic());
        }
    }

    /// A connection opened since `began`, or a kept one (`None`); `reused` says which where connections are kept at all.
    pub fn connected(&mut self, began: Option<f64>, reused: Option<bool>) {
        // absent-ok: a kept connection took no time to open.
        self.connect_ms = Some(began.map_or(0.0, |began| (self.clock.monotonic() - began) * 1000.0));
        self.reused = reused;
    }

    /// Whether this request has reached an upstream at all.
    pub fn connected_once(&self) -> bool {
        self.connect_ms.is_some()
    }

    /// The time on the clock, for `connected`.
    pub fn now(&self) -> f64 {
        self.clock.monotonic()
    }

    /// The request went out. Forgets the marks of an attempt before it: they belong to the leg that answered.
    pub fn sent(&mut self) {
        self.sent = Some(self.clock.monotonic());
        self.headers = None;
        self.first_bytes = None;
    }

    /// The answer's head came.
    pub fn answered(&mut self) {
        self.headers = Some(self.clock.monotonic());
    }

    /// The answer's first body bytes came; the later ones change nothing.
    pub fn first_bytes(&mut self) {
        if self.first_bytes.is_none() {
            self.first_bytes = Some(self.clock.monotonic());
        }
    }

    fn since_sent(&self, at: Option<f64>) -> Option<f64> {
        Some(Self::tenths((at? - self.sent?) * 1000.0))
    }

    fn tenths(value: f64) -> f64 {
        (value * 10.0).round() / 10.0
    }

    fn prep_ms(&self) -> Option<f64> {
        let leg = self.leg_started?;
        let spent = match (self.queue_entered, self.admitted) {
            (Some(entered), Some(admitted)) => (entered - self.received) + (leg - admitted),
            _ => leg - self.received,
        };
        Some(Self::tenths(spent.max(0.0) * 1000.0))
    }

    fn cpu_ms(&self) -> Option<f64> {
        Some(Self::tenths((self.clock.thread_cpu()? - self.cpu_started?) * 1000.0))
    }

    /// The marks as the record's `latency`.
    pub fn as_json(&self) -> Value {
        json!({
            "prepMs": self.prep_ms(),
            "connectMs": self.connect_ms.map(Self::tenths),
            "connReused": self.reused,
            "headersMs": self.since_sent(self.headers),
            "firstChunkMs": self.since_sent(self.first_bytes),
            "cpuMs": self.cpu_ms(),
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Mutex;

    /// Clocks a test moves by hand.
    struct HandClock {
        now: Mutex<f64>,
        cpu: Mutex<Option<f64>>,
    }

    impl HandClock {
        fn at(now: f64) -> Arc<Self> {
            Arc::new(Self { now: Mutex::new(now), cpu: Mutex::new(Some(1.0)) })
        }

        fn step(&self, by: f64) {
            *self.now.lock().unwrap() += by;
        }
    }

    impl Clock for HandClock {
        fn epoch(&self) -> f64 {
            *self.now.lock().unwrap()
        }
        fn monotonic(&self) -> f64 {
            *self.now.lock().unwrap()
        }
        fn thread_cpu(&self) -> Option<f64> {
            *self.cpu.lock().unwrap()
        }
    }

    #[test]
    fn a_request_answered_by_nobody_has_no_marks() {
        let hand = HandClock::at(100.0);
        let clock = RequestClock::new(hand.clone());
        let said = clock.as_json();
        for mark in ["prepMs", "connectMs", "connReused", "headersMs", "firstChunkMs"] {
            assert_eq!(said[mark], Value::Null, "{mark}");
        }
        assert_eq!(said["cpuMs"], json!(0.0));
    }

    #[test]
    fn the_wait_in_the_queue_is_not_the_caravan_s_own_work() {
        let hand = HandClock::at(100.0);
        let mut clock = RequestClock::new(hand.clone());
        hand.step(0.002);
        clock.queue_entered();
        hand.step(30.0);
        clock.admitted();
        hand.step(0.003);
        clock.leg_started();
        let began = clock.now();
        hand.step(0.004);
        clock.connected(Some(began), None);
        clock.sent();
        hand.step(0.1);
        clock.answered();
        hand.step(0.2);
        clock.first_bytes();
        hand.step(0.5);
        clock.first_bytes();
        let said = clock.as_json();
        assert_eq!(said["prepMs"], json!(5.0));
        assert_eq!(said["connectMs"], json!(4.0));
        assert_eq!(said["headersMs"], json!(100.0));
        assert_eq!(said["firstChunkMs"], json!(300.0));
    }

    #[test]
    fn a_later_attempt_keeps_the_prep_and_gives_up_the_marks_of_the_first() {
        let hand = HandClock::at(100.0);
        let mut clock = RequestClock::new(hand.clone());
        hand.step(0.001);
        clock.leg_started();
        clock.sent();
        clock.answered();
        hand.step(5.0);
        clock.leg_started();
        clock.sent();
        let said = clock.as_json();
        assert_eq!(said["prepMs"], json!(1.0));
        assert_eq!(said["headersMs"], Value::Null);
    }

    #[test]
    fn a_processor_clock_that_says_nothing_is_said_as_nothing() {
        let hand = HandClock::at(100.0);
        *hand.cpu.lock().unwrap() = None;
        assert_eq!(RequestClock::new(hand).as_json()["cpuMs"], Value::Null);
    }
}
