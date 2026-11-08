//! What this scout is answering now: every connection from its accept to its close, and of those the requests passing through the
//! machine's entry. A release put in place ends this process only once none is left (own_release.rs), as the controller ends once its
//! proxy runs no request: the process is the one way between a client and a cell, and its end cuts every stream on that way halfway.

use std::sync::Arc;
use std::sync::atomic::{AtomicUsize, Ordering};

/// A count of what is under way: each one counted while its token lives.
#[derive(Debug, Default)]
pub struct UnderWay {
    count: AtomicUsize,
}

impl UnderWay {
    /// One more begins. Counted before its work starts, so that a look cannot slip between the two, and until its token is dropped, on
    /// any way out of its thread, a panic among them.
    pub fn begin(self: &Arc<Self>) -> Begun {
        self.count.fetch_add(1, Ordering::AcqRel);
        Begun { of: Arc::clone(self) }
    }

    /// How many are under way.
    pub fn now(&self) -> usize {
        self.count.load(Ordering::Acquire)
    }
}

/// One thing under way: it ends when this is dropped.
#[derive(Debug)]
pub struct Begun {
    of: Arc<UnderWay>,
}

impl Drop for Begun {
    fn drop(&mut self) {
        self.of.count.fetch_sub(1, Ordering::AcqRel);
    }
}

/// What the scout is answering.
#[derive(Debug, Default)]
pub struct Answering {
    /// Every connection, from its accept to its close: the controller's calls and the update's own answer among them.
    pub connections: Arc<UnderWay>,
    /// The requests through the machine's entry, from their head to their answer's last byte: what a client would lose.
    pub entry: Arc<UnderWay>,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn each_is_counted_to_its_end_a_panic_included() {
        let answering = Answering::default();
        let one = answering.connections.begin();
        let two = answering.connections.begin();
        let request = answering.entry.begin();
        assert_eq!((answering.connections.now(), answering.entry.now()), (2, 1));
        drop(one);
        drop(request);
        assert_eq!((answering.connections.now(), answering.entry.now()), (1, 0));
        let ended = std::thread::spawn(move || {
            let _two = two;
            panic!("a defect inside one request");
        })
        .join();
        assert!(ended.is_err());
        assert_eq!(answering.connections.now(), 0, "negative: a thread that died still ended its count");
    }
}
