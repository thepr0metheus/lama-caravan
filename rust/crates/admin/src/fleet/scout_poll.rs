//! The scouts' state, pulled off the board's request path.

use crate::app::App;
use std::sync::{Arc, Condvar, Mutex, PoisonError};
use std::time::Duration;

/// Starts background pulls, never more than one at a time and never more often than its pause.
#[derive(Default)]
pub struct ScoutPoller {
    state: Mutex<PollerState>,
}

#[derive(Default)]
struct PollerState {
    running: bool,
    last_start: Option<f64>,
}

impl ScoutPoller {
    const MIN_INTERVAL: f64 = 5.0;

    /// A pull started, unless one is running or one started a moment ago; whether it was. `pick` finds this poller on the app its thread holds.
    pub fn kick(&self, app: &Arc<App>, pick: fn(&App) -> &ScoutPoller, pull: fn(&App)) -> bool {
        let now = app.clock.monotonic();
        {
            let mut state = self.state.lock().unwrap_or_else(PoisonError::into_inner);
            if state.running || state.last_start.is_some_and(|last| now - last < Self::MIN_INTERVAL) {
                return false;
            }
            state.running = true;
            state.last_start = Some(now);
        }
        let held = Arc::clone(app);
        let started = std::thread::Builder::new().name("scout-poll".to_string()).spawn(move || {
            pull(&held);
            pick(&held).state.lock().unwrap_or_else(PoisonError::into_inner).running = false;
        });
        if started.is_err() {
            self.state.lock().unwrap_or_else(PoisonError::into_inner).running = false;
            return false;
        }
        true
    }
}

/// Runs work in the background when kicked, once more after the run in flight when kicked meanwhile.
#[derive(Default)]
pub struct Rerun {
    state: Mutex<RerunState>,
    settled: Condvar,
}

#[derive(Default)]
struct RerunState {
    running: bool,
    again: bool,
}

impl Rerun {
    /// The work run, or once more after the run in flight; whether a thread started.
    pub fn kick(&self, app: &Arc<App>, pick: fn(&App) -> &Rerun, work: fn(&App)) -> bool {
        {
            let mut state = self.state.lock().unwrap_or_else(PoisonError::into_inner);
            if state.running {
                state.again = true;
                return false;
            }
            state.running = true;
        }
        let held = Arc::clone(app);
        let started = std::thread::Builder::new().name("rerun".to_string()).spawn(move || {
            loop {
                work(&held);
                let rerun = pick(&held);
                let mut state = rerun.state.lock().unwrap_or_else(PoisonError::into_inner);
                if !state.again {
                    state.running = false;
                    rerun.settled.notify_all();
                    return;
                }
                state.again = false;
            }
        });
        if started.is_err() {
            self.state.lock().unwrap_or_else(PoisonError::into_inner).running = false;
            self.settled.notify_all();
            return false;
        }
        true
    }

    /// Waits until no run is in flight, the one after it included; whether that happened in `timeout`.
    pub fn idle(&self, timeout: Duration) -> bool {
        let state = self.state.lock().unwrap_or_else(PoisonError::into_inner);
        let (state, _) =
            self.settled.wait_timeout_while(state, timeout, |state| state.running).unwrap_or_else(PoisonError::into_inner);
        !state.running
    }
}
