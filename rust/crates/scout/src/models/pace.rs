//! How a copy goes: its pace, and its written pages let go of.

use crate::log::Log;
use os::PageCache;
use std::collections::VecDeque;
use std::fs::File;
use std::io;
use std::time::Duration;

/// How fast a copy goes: bytes a second over its last few seconds. Over a window of samples, not the last two reads: two 32 MiB steps read a moment apart say nothing steady. `None`, not
/// measured, never a 0, until the window spans two seconds; a count that went back starts the window again.
#[derive(Debug, Default)]
pub struct CopyPace {
    samples: VecDeque<(f64, i64)>,
}

impl CopyPace {
    const WINDOW: f64 = 10.0;
    const SPAN: f64 = 2.0;
    const STEP: f64 = 0.25;

    /// A count of bytes copied so far, at `now`: kept every quarter of a second, the window's oldest let go.
    pub fn add(&mut self, done: i64, now: f64) {
        if self.samples.back().is_some_and(|(_, last)| done < *last) {
            self.samples.clear();
        }
        if self.samples.back().is_some_and(|(at, _)| now - *at < Self::STEP) {
            return;
        }
        self.samples.push_back((now, done));
        while self.samples.len() > 2 && self.samples.get(1).is_some_and(|(at, _)| now - *at >= Self::WINDOW) {
            self.samples.pop_front();
        }
    }

    /// Bytes a second over the window, or `None` while it spans less than two seconds.
    pub fn rate(&self) -> Option<i64> {
        let ((first_at, first), (last_at, last)) = (self.samples.front()?, self.samples.back()?);
        (self.samples.len() >= 2 && last_at - first_at >= Self::SPAN)
            .then(|| ((last - first) as f64 / (last_at - first_at)) as i64)
    }
}

/// A download's pages out of the page cache as they are written. A model is tens of GB, written once and read by the cell that asked for it; left in the page cache it is the youngest memory
/// of the machine, and the start that follows pays: the memory pressure of the session stayed above systemd-oomd's 50 %, and oomd killed the scout, GNOME Shell and the cell. A system with no
/// `posix_fadvise` keeps its cache; a refusal is said once and the download goes on.
pub struct WrittenPages {
    label: String,
    dropped: u64,
    on: bool,
}

impl WrittenPages {
    const STEP: u64 = 256 << 20;

    /// The pages of the file labelled `label`.
    pub fn new(label: &str) -> Self {
        Self { label: label.to_string(), dropped: 0, on: PageCache::can_drop() }
    }

    /// `done` bytes are written.
    pub fn wrote(&mut self, file: &File, done: u64) {
        if done - self.dropped >= Self::STEP {
            self.drop_to(file, done);
        }
    }

    /// Syncs what was written since the last drop, then takes it out of the page cache: only clean pages leave.
    pub fn drop_to(&mut self, file: &File, done: u64) {
        if !self.on || done <= self.dropped {
            return;
        }
        let went: io::Result<()> = file.sync_data().and_then(|()| PageCache::drop_range(file, self.dropped, done - self.dropped));
        match went {
            Ok(()) => self.dropped = done,
            Err(error) => {
                self.on = false;
                Log::line(&format!("[llama-node] {}: its pages stay in the page cache ({error})", self.label));
            }
        }
    }
}

/// How long a copy rests between its tries.
pub struct RetryDelays;

impl RetryDelays {
    /// Between attempts: 4 attempts in all, for a controller restarting during a deploy.
    pub const ALL: [Duration; 3] =
        if cfg!(test) { [Duration::ZERO; 3] } else { [Duration::from_secs(5), Duration::from_secs(15), Duration::from_secs(30)] };
}
