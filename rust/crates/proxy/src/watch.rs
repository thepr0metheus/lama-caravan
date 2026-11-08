//! What a request looks at while it waits for its upstream: whether its client is still there, whether a waiting stream needs a
//! sign of life, whether the board asked it to stop.
//!
//! It is one turn of the relay's own loop: a socket read comes back every two seconds, and the same thread looks around. No second writer, no lock.

use crate::client::ClientSide;
use crate::proxy::Proxy;
use crate::record::RequestRecord;
use crate::stop::{Ending, UpstreamEnd};
use rules::Policy;
use std::io;
use std::time::Duration;

/// One request's look-out.
pub struct Watch<'a> {
    proxy: &'a Proxy,
    record: &'a RequestRecord,
    streaming: bool,
    last_upstream_byte: f64,
    last_stop_check: f64,
}

impl<'a> Watch<'a> {
    /// How long an upstream may stay silent: Python's `timeout=600` on the connection.
    const SILENCE_LIMIT: f64 = 600.0;
    /// How often a request asks whether the board has stopped it, at most.
    const STOP_TURN: f64 = 0.25;
    /// How long a wait goes before it looks around.
    const SLEEP_TURN: Duration = Duration::from_secs(1);

    /// The look-out of `record`'s request. `streaming` is whether its client asked for a stream: only such a client has an open
    /// socket to watch and a read timeout to feed.
    pub fn new(proxy: &'a Proxy, record: &'a RequestRecord, streaming: bool) -> Self {
        let now = proxy.clock.epoch();
        Self { proxy, record, streaming, last_upstream_byte: now, last_stop_check: now }
    }

    /// A byte came from the upstream.
    pub fn byte_came(&mut self) {
        self.last_upstream_byte = self.proxy.clock.epoch();
    }

    /// One look around.
    pub fn turn(&mut self, client: &mut ClientSide) -> Result<(), Ending> {
        self.check_stop()?;
        if !self.streaming {
            return Ok(());
        }
        if client.has_left() {
            return Err(Ending::ClientGone);
        }
        if client.head_sent() && client.idle_seconds() >= Policy::KEEPALIVE_SEC {
            return client.keepalive(self.record.model_said());
        }
        Ok(())
    }

    /// A read from the upstream came back empty: a look around, and the upstream's silence counted.
    pub fn waited_for_upstream(&mut self, client: &mut ClientSide) -> Result<(), Ending> {
        self.turn(client)?;
        if self.proxy.clock.epoch() - self.last_upstream_byte >= Self::SILENCE_LIMIT {
            let error = io::Error::new(io::ErrorKind::TimedOut, "timed out");
            return Err(Ending::Upstream(UpstreamEnd::of(&error)));
        }
        Ok(())
    }

    /// Between two chunks: whether the board asked it to stop, no more often than `STOP_TURN`.
    pub fn check_stop(&mut self) -> Result<(), Ending> {
        let now = self.proxy.clock.epoch();
        if now - self.last_stop_check < Self::STOP_TURN {
            return Ok(());
        }
        self.last_stop_check = now;
        match self.proxy.settings.current().stops.get(&self.record.id) {
            None => Ok(()),
            Some(reason) if reason.is_empty() => Err(Ending::Stopped("request stopped by traffic policy".to_string())),
            Some(reason) => Err(Ending::Stopped(reason.clone())),
        }
    }

    /// Waits `long`, looking around at least once a second.
    pub fn sleep(&mut self, long: Duration, client: &mut ClientSide) -> Result<(), Ending> {
        let mut left = long;
        while !left.is_zero() {
            let step = left.min(Self::SLEEP_TURN);
            std::thread::sleep(step);
            left = left.saturating_sub(step);
            self.turn(client)?;
        }
        self.last_upstream_byte = self.proxy.clock.epoch();
        Ok(())
    }
}
