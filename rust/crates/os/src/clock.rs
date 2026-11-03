//! The clocks a program reads: a parameter everywhere else, so that a test drives them, and read here alone.

use crate::ThreadCpu;
use std::time::{Instant, SystemTime, UNIX_EPOCH};

/// The clocks a request reads. A test drives them.
pub trait Clock: Send + Sync {
    /// Wall-clock seconds since the epoch.
    fn epoch(&self) -> f64;
    /// Seconds on a clock that only goes forward.
    fn monotonic(&self) -> f64;
    /// Processor seconds of the calling thread; `None` when the system does not say.
    fn thread_cpu(&self) -> Option<f64>;
}

/// The machine's clocks.
pub struct SystemClock {
    started: Instant,
}

impl SystemClock {
    /// The clocks, as of now.
    pub fn new() -> Self {
        Self { started: Instant::now() }
    }
}

impl Default for SystemClock {
    fn default() -> Self {
        Self::new()
    }
}

impl Clock for SystemClock {
    fn epoch(&self) -> f64 {
        // absent-ok: a clock set before 1970 has no answer to give, and the epoch is what every comparison then starts from.
        SystemTime::now().duration_since(UNIX_EPOCH).map_or(0.0, |since| since.as_secs_f64())
    }

    fn monotonic(&self) -> f64 {
        self.started.elapsed().as_secs_f64()
    }

    fn thread_cpu(&self) -> Option<f64> {
        ThreadCpu::seconds()
    }
}
