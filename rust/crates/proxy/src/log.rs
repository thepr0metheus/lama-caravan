//! The process's own log: what `docker logs` and `logs/rust-proxy.log` show.

/// One line on standard error. The one place that prints.
pub struct Log;

impl Log {
    /// Writes `words` as a line.
    #[allow(clippy::print_stderr, reason = "this is the one place the proxy prints")]
    pub fn line(words: &str) {
        eprintln!("{words}");
    }
}
