//! A pass that repeats for as long as the program lives.

use crate::log::Log;
use std::panic::{AssertUnwindSafe, catch_unwind};
use std::time::Duration;

/// The loops of a program's watches. One bad pass must not end the watch: a defect in a pass is said, and the next pass comes.
pub struct Ticking;

impl Ticking {
    /// Runs `pass` every `rest`, for good.
    pub fn forever(name: &str, rest: Duration, mut pass: impl FnMut()) -> ! {
        loop {
            Self::once(name, &mut pass);
            std::thread::sleep(rest);
        }
    }

    /// One pass: a defect in it is said, and the next pass still comes.
    pub fn once(name: &str, pass: impl FnOnce()) {
        if catch_unwind(AssertUnwindSafe(pass)).is_err() {
            Log::line(&format!("[{name}] a pass failed"));
        }
    }

    /// The same on a thread of its own. A system that gives no thread is said: that watch does not run.
    pub fn in_background(name: &'static str, rest: Duration, pass: impl FnMut() + Send + 'static) {
        let started = std::thread::Builder::new().name(name.to_string()).spawn(move || -> () {
            Self::forever(name, rest, pass);
        });
        if let Err(error) = started {
            Log::line(&format!("[{name}] not started: {error}"));
        }
    }
}
