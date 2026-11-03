//! What is remembered of a cell's port between two readings of the board: no socket here, the asking is the caller's.

use crate::common::misc::TtlCache;

/// What a port was found to be a moment ago, for no reading to ask it again.
pub struct PortAnswers {
    kept: TtlCache<String, bool>,
}

impl Default for PortAnswers {
    fn default() -> Self {
        Self { kept: TtlCache::new(15.0) }
    }
}

impl PortAnswers {
    /// How long a port found closed is remembered, seconds.
    const CLOSED_REMEMBERED_SEC: f64 = 2.0;

    /// Whether the port at `key` opens, remembered a moment: `ttl` when it opens, less when it does not. `ask` is the asking itself.
    pub fn answer(&self, key: &str, ttl: f64, now: f64, ask: impl FnOnce() -> bool) -> bool {
        let key = key.to_string();
        if self.kept.get(&key, now, Some(ttl)) == Some(true) {
            return true;
        }
        // A cell's port stands closed while it loads and opens the moment it is ready: a "no" kept longer said "open the firewall" of a cell that answers.
        if self.kept.get(&key, now, Some(Self::CLOSED_REMEMBERED_SEC)) == Some(false) {
            return false;
        }
        let open = ask();
        self.kept.put(key, open, now);
        open
    }
}

/// How long a port has been found closed, and what may be said of it. A cell just stopped or just up is closed for a moment on its way, and its row said "open the host firewall" in red for that moment
/// (2026-11-02). A firewall does not stop being closed.
pub struct ClosedPorts {
    since: TtlCache<String, f64>,
}

impl Default for ClosedPorts {
    fn default() -> Self {
        Self { since: TtlCache::new(Self::READINGS_GAP_SEC) }
    }
}

impl ClosedPorts {
    /// How long a port stays closed before it is said to be, seconds.
    const SAID_AFTER_SEC: f64 = 10.0;
    /// A gap in the readings longer than this starts the count again: nobody saw it stay closed. An open port is remembered longer than this (15 s), so one that opened starts over too.
    const READINGS_GAP_SEC: f64 = 8.0;

    /// This reading of the port at `key`: open, closed long enough to say so, or `None`, not known yet.
    pub fn said(&self, key: &str, open: bool, now: f64) -> Option<bool> {
        if open {
            return Some(true);
        }
        // absent-ok: a port with no reading lately starts its count now.
        let since = self.since.get(&key.to_string(), now, None).unwrap_or(now);
        self.since.put(key.to_string(), since, now);
        (now - since >= Self::SAID_AFTER_SEC).then_some(false)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::cell::Cell;

    #[test]
    fn a_port_found_closed_is_looked_at_again_soon_and_one_found_open_later() {
        let answers = PortAnswers::default();
        let asked = Cell::new(0);
        let said = |open: bool, now: f64| {
            answers.answer("a:1", 15.0, now, || {
                asked.set(asked.get() + 1);
                open
            })
        };
        assert!(!said(false, 1000.0), "closed");
        assert!(!said(true, 1000.0), "the answer of a moment ago: no asking at every reading");
        assert_eq!(asked.get(), 1);
        assert!(said(true, 1003.0), "seconds later it is asked again: the cell that came up is not said to be behind a firewall");
        assert!(said(false, 1013.0), "an open port is remembered for all of its time");
        assert_eq!(asked.get(), 2);
        assert!(!said(false, 1019.0), "and asked again after it");
        assert_eq!(asked.get(), 3);
    }

    #[test]
    fn a_port_is_said_to_be_closed_only_when_it_stays_closed() {
        let ports = ClosedPorts::default();
        let closed = |now: f64| ports.said("a:1", false, now);
        assert_eq!(closed(1000.0), None, "closed a moment: a cell on its way up or down, and nobody knows yet");
        assert_eq!(closed(1005.0), None, "five seconds on, the same");
        assert_eq!(closed(1010.0), Some(false), "ten seconds of it: now the board may say so");
        assert_eq!(closed(1015.0), Some(false), "and goes on saying so");
        assert_eq!(closed(1075.0), None, "nobody looked for a minute: the count starts again");
        assert_eq!(ports.said("a:1", true, 1078.0), Some(true), "it opened");
        assert_eq!(
            closed(1094.0),
            None,
            "closed again after it was open, the time an open port is remembered later: not the old count"
        );
        assert_eq!(ports.said("b:2", false, 1094.0), None, "another port has a count of its own");
    }
}
