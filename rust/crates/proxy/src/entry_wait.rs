//! A machine's entry that is not there for a moment: its scout restarting, after a release put in place or a crash the service
//! brings back. A request waits for the entry to take connections again and goes on there.
//!
//! Until 2026-11-08 such a request went to a running copy of its model instead, straight to the copy's own port
//! (`machine_entry_spare`). Since the cells listen on their machine's loopback alone (Papyrus `caravan-scout-port-lease`, step 7),
//! a machine shows the network one port, its scout's, and waiting is the way left: one place, which covers a scout that crashed too.

use rules::{Coerce, UpstreamType};
use serde_json::{Value, json};
use std::io;
use std::time::Duration;

/// One request's wait for its machine's entry.
#[derive(Debug)]
pub struct EntryWait {
    /// Whether the way is a machine's entry: a server of another kind is not waited for.
    patient: bool,
    /// When the entry first did not take the request; `None` while it has taken every one.
    first_refusal: Option<f64>,
    /// How many times it did not.
    refusals: u32,
    /// The socket's words for the last time.
    said: String,
}

impl EntryWait {
    /// How long a request waits, at the most. The service starts a scout again 3 s after it ended (`RestartSec=3`), and the scout
    /// listens about 45 ms after it starts (its journal, 2026-11-08): a gap of 3.3 s, waited for here more than four times over.
    pub const PATIENCE: f64 = 15.0;
    /// Between two knocks: a refused connection costs the machine nothing, and the gap's end is met within a quarter of a second.
    pub const TURN: Duration = Duration::from_millis(250);

    /// The wait of a request that goes to a server of `kind`.
    pub fn for_way(kind: UpstreamType) -> Self {
        Self { patient: kind == UpstreamType::Machine, first_refusal: None, refusals: 0, said: String::new() }
    }

    /// Whether `error`, met before a byte of the answer came, says that nobody took the request: the connection refused, or dropped
    /// unread, as the connections waiting in the queue of a scout that ended are. Nothing read the request, so it may go again.
    pub fn nobody_took(error: &io::Error) -> bool {
        matches!(
            error.kind(),
            io::ErrorKind::ConnectionRefused
                | io::ErrorKind::ConnectionReset
                | io::ErrorKind::ConnectionAborted
                | io::ErrorKind::BrokenPipe
                | io::ErrorKind::UnexpectedEof
        )
    }

    /// The entry did not take the request at `now`, for `error`: whether to knock again — a machine's entry whose patience is not
    /// spent.
    pub fn again(&mut self, error: &io::Error, now: f64) -> bool {
        self.refusals += 1;
        self.said = Coerce::first_letters(&error.to_string(), 200).to_string();
        let since = *self.first_refusal.get_or_insert(now);
        self.patient && now - since < Self::PATIENCE
    }

    /// What the journal says of the wait for `output`'s entry at `now`, once the request's way is walked: how long, how many knocks,
    /// whether the entry took the request in the end. `None` when it took it at once: there was no wait to tell.
    pub fn told(&self, output: &str, now: f64, took_it: bool) -> Option<Value> {
        let since = self.first_refusal?;
        let waited = ((now - since) * 10.0).round() / 10.0;
        Some(json!({"output": output, "waitedSec": waited, "knocks": self.refusals, "cameBack": took_it, "error": self.said}))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn refused() -> io::Error {
        io::Error::new(io::ErrorKind::ConnectionRefused, "Connection refused")
    }

    #[test]
    fn a_machine_s_entry_is_waited_for_as_long_as_its_patience() {
        let mut wait = EntryWait::for_way(UpstreamType::Machine);
        assert!(wait.again(&refused(), 100.0), "the first refusal starts the wait");
        assert!(wait.again(&refused(), 100.0 + EntryWait::PATIENCE - 0.1), "boundary: just inside the patience");
        assert!(!wait.again(&refused(), 100.0 + EntryWait::PATIENCE), "boundary: the patience is spent");
        let told = wait.told("mm:a", 100.0 + EntryWait::PATIENCE, false).unwrap();
        assert_eq!(told["knocks"], 3);
        assert_eq!(told["waitedSec"], 15.0);
        assert_eq!(told["cameBack"], false);
        assert_eq!(told["error"], "Connection refused");
        assert_eq!(told["output"], "mm:a");
    }

    #[test]
    fn another_server_is_not_waited_for() {
        for kind in [UpstreamType::Engine, UpstreamType::Llama] {
            let mut wait = EntryWait::for_way(kind);
            assert!(!wait.again(&refused(), 100.0), "negative: an engine or a cell of before fails at once, as it always did");
            assert_eq!(wait.told("eng:a", 100.0, false).unwrap()["knocks"], 1, "and the journal still says it was refused");
        }
    }

    #[test]
    fn no_refusal_is_no_wait_to_tell() {
        let wait = EntryWait::for_way(UpstreamType::Machine);
        assert_eq!(wait.told("mm:a", 100.0, true), None);
    }

    #[test]
    fn only_a_request_nobody_took_may_go_again() {
        for kind in [
            io::ErrorKind::ConnectionRefused,
            io::ErrorKind::ConnectionReset,
            io::ErrorKind::ConnectionAborted,
            io::ErrorKind::BrokenPipe,
            io::ErrorKind::UnexpectedEof,
        ] {
            assert!(EntryWait::nobody_took(&io::Error::new(kind, "x")), "{kind:?}");
        }
        for kind in [
            io::ErrorKind::TimedOut,
            io::ErrorKind::HostUnreachable,
            io::ErrorKind::NetworkUnreachable,
            io::ErrorKind::InvalidData,
        ] {
            assert!(
                !EntryWait::nobody_took(&io::Error::new(kind, "x")),
                "negative: {kind:?} — a machine that is off or a network that is down is no scout restarting"
            );
        }
    }
}
