//! Why a request's work ends before its answer does.

use rules::EntryRefusal;
use std::io;

/// What ends a request early. Each carries what the record and the client are told.
#[derive(Debug)]
pub enum Ending {
    /// The client hung up.
    ClientGone,
    /// The board asked this request to stop; the words are its reason.
    Stopped(String),
    /// The caravan refused it on the way: a status, its words and its kind.
    Blocked {
        /// The status.
        status: u16,
        /// The words the journal keeps.
        words: String,
        /// The kind the board branches on.
        kind: &'static str,
    },
    /// The caravan refused it on the way in words of its own, which the client is told as they are: the board's reader did
    /// not read a picture, or a picture is not inside the request. The words say what to do, so they are not the dialect's.
    Refused(EntryRefusal),
    /// The upstream failed.
    Upstream(UpstreamEnd),
    /// Its patience with a full model is over, and its pool has a row ready: the milliseconds it waited.
    Yielded(i64),
    /// A bug here: the words the panic said.
    Inside(String),
}

impl Ending {
    /// What `work` comes to, a panic inside it included: a bug ends the one request it is in, and that request still gets its
    /// record, its answer to the client and every place it held given back.
    pub fn guarded(work: impl FnOnce() -> Result<(), Self>) -> Result<(), Self> {
        match std::panic::catch_unwind(std::panic::AssertUnwindSafe(work)) {
            Ok(ended) => ended,
            Err(panic) => {
                let words = panic
                    .downcast_ref::<&str>()
                    .map(|words| (*words).to_string())
                    .or_else(|| panic.downcast_ref::<String>().cloned());
                Err(Self::Inside(words.unwrap_or_else(|| "the proxy failed inside".to_string())))
            }
        }
    }
}

/// How an upstream failed, in the journal's words.
#[derive(Debug)]
pub struct UpstreamEnd {
    /// The words.
    pub words: String,
    /// The kind the board branches on: `classify_proxy_error` with the client still there.
    pub kind: &'static str,
}

impl UpstreamEnd {
    /// The failure an error of the socket means. Only reached with the client still there, so a reset here is the upstream's;
    pub fn of(error: &io::Error) -> Self {
        let words = error.to_string();
        Self { kind: Self::kind_of(error, &words), words }
    }

    fn kind_of(error: &io::Error, words: &str) -> &'static str {
        use io::ErrorKind::{BrokenPipe, ConnectionAborted, ConnectionReset, TimedOut, UnexpectedEof, WouldBlock};
        match error.kind() {
            BrokenPipe | ConnectionReset | ConnectionAborted | UnexpectedEof => "upstream_disconnected",
            TimedOut | WouldBlock => "upstream_timeout",
            _ if words.contains("timed out") => "upstream_timeout",
            _ => "proxy_error",
        }
    }
}

/// Whether a socket's read only waited its time: the relay's turn to look around, nothing wrong.
pub struct Waited;

impl Waited {
    /// True for a read that came back for want of bytes.
    pub fn is(error: &io::Error) -> bool {
        matches!(error.kind(), io::ErrorKind::WouldBlock | io::ErrorKind::TimedOut)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_bug_inside_a_request_is_an_ending_and_not_the_end_of_the_process() {
        assert!(matches!(Ending::guarded(|| Ok(())), Ok(())));
        assert!(matches!(Ending::guarded(|| Err(Ending::ClientGone)), Err(Ending::ClientGone)));
        let quiet = std::panic::take_hook();
        std::panic::set_hook(Box::new(|_| {}));
        let said = Ending::guarded(|| panic!("a bug"));
        let formatted = Ending::guarded(|| panic!("a bug {}", 2));
        std::panic::set_hook(quiet);
        assert!(matches!(said, Err(Ending::Inside(words)) if words == "a bug"));
        assert!(matches!(formatted, Err(Ending::Inside(words)) if words == "a bug 2"));
    }

    #[test]
    fn a_failure_is_named_as_the_python_names_it() {
        let kind = |kind: io::ErrorKind| UpstreamEnd::of(&io::Error::new(kind, "words")).kind;
        assert_eq!(kind(io::ErrorKind::ConnectionReset), "upstream_disconnected");
        assert_eq!(kind(io::ErrorKind::BrokenPipe), "upstream_disconnected");
        assert_eq!(kind(io::ErrorKind::UnexpectedEof), "upstream_disconnected");
        assert_eq!(kind(io::ErrorKind::TimedOut), "upstream_timeout");
        assert_eq!(kind(io::ErrorKind::ConnectionRefused), "proxy_error");
        assert_eq!(UpstreamEnd::of(&io::Error::other("the read timed out")).kind, "upstream_timeout");
    }
}
