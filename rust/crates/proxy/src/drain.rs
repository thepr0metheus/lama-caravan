//! The way out for a version that has been replaced: it stops taking connections, finishes what it started and ends.
//!
//! A new version of the program comes as a new file. The controller starts it beside the running one, and the running one sees the file
//! change: it lets its port go, so that the new one takes it, and answers the requests it has to their last byte. No client's stream
//! is cut by a new version: every client's request passes through this process, and a stop would cut them all.
//!
//! A controller that ends takes the same way out with it. The controller starts this process in a session of its own, and nothing else tells it the
//! controller is gone: outside a container it would stay, holding the entry's port against the proxy of the next controller.

use std::fs;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::time::{Duration, SystemTime};

/// What tells a program's file changed.
type Stamp = (SystemTime, u64);

/// This process's way out.
#[derive(Debug)]
pub struct Drain {
    program: Option<PathBuf>,
    started: Option<Stamp>,
    keeper: Option<u32>,
    draining: AtomicBool,
    open: AtomicUsize,
}

impl Drain {
    /// How often the program's file is looked at. The controller looks more often, so that the new version already waits for the port
    /// when this one lets it go.
    pub const TURN: Duration = Duration::from_secs(2);
    /// The longest it stays for a request: past any client's patience, it is holding nobody's answer.
    pub const LONGEST_SECONDS: f64 = 7200.0;

    /// The way out of a process started from `program`; with `None` there is nothing to watch.
    pub fn of_program(program: Option<PathBuf>) -> Self {
        let started = program.as_deref().and_then(Self::stamp);
        Self { program, started, keeper: None, draining: AtomicBool::new(false), open: AtomicUsize::new(0) }
    }

    /// The same way out, for a process `keeper` started: it also leaves when that process is gone.
    pub fn kept_by(self, keeper: Option<u32>) -> Self {
        Self { keeper, ..self }
    }

    /// Why this process is to leave; `None` while it is to stay.
    pub fn why_leave(&self) -> Option<&'static str> {
        if self.program_changed() {
            Some("a new version came")
        } else if self.keeper_gone() {
            Some("the controller that keeps it is gone")
        } else {
            None
        }
    }

    /// Whether this process has another parent than the one that said it keeps it. A process that loses its parent gets a new one; the id is compared with
    /// the word, not with what was read at the start, so a keeper that was gone before the first look is seen too.
    fn keeper_gone(&self) -> bool {
        self.keeper.is_some_and(|keeper| std::os::unix::process::parent_id() != keeper)
    }

    fn stamp(path: &Path) -> Option<Stamp> {
        let meta = fs::metadata(path).ok()?;
        Some((meta.modified().ok()?, meta.len()))
    }

    /// Whether the program's file is another one now. A file that cannot be read says nothing: replacing it is one rename, so a missing
    /// one is somebody's mistake, and the running version stays.
    pub fn program_changed(&self) -> bool {
        match (self.program.as_deref().and_then(Self::stamp), self.started) {
            (Some(now), Some(started)) => now != started,
            _ => false,
        }
    }

    /// From now on it takes no new connection.
    pub fn begin(&self) {
        self.draining.store(true, Ordering::Release);
    }

    /// Whether it is on its way out.
    pub fn is_on(&self) -> bool {
        self.draining.load(Ordering::Acquire)
    }

    /// How many connections are being served.
    pub fn open(&self) -> usize {
        self.open.load(Ordering::Acquire)
    }

    /// A connection begins. Counted before its thread starts, so that the last one cannot slip past the count; it ends when this is
    /// dropped, on any way out of its thread.
    pub fn connection(self: &Arc<Self>) -> OpenConnection {
        self.open.fetch_add(1, Ordering::AcqRel);
        OpenConnection { drain: Arc::clone(self) }
    }
}

/// One connection being served.
#[derive(Debug)]
pub struct OpenConnection {
    drain: Arc<Drain>,
}

impl Drop for OpenConnection {
    fn drop(&mut self) {
        self.drain.open.fetch_sub(1, Ordering::AcqRel);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_new_file_is_a_change_and_a_missing_one_is_not() {
        let folder = std::env::temp_dir().join(format!("caravan-drain-{}", std::process::id()));
        fs::create_dir_all(&folder).unwrap();
        let program = folder.join("caravan-proxy");
        fs::write(&program, b"one").unwrap();
        let drain = Drain::of_program(Some(program.clone()));
        assert!(!drain.program_changed());
        fs::remove_file(&program).unwrap();
        assert!(!drain.program_changed());
        let replacement = folder.join("caravan-proxy.new");
        fs::write(&replacement, b"the new one").unwrap();
        fs::rename(&replacement, &program).unwrap();
        assert!(drain.program_changed());
        fs::remove_dir_all(&folder).unwrap();
    }

    #[test]
    fn no_program_to_watch_never_changes() {
        assert!(!Drain::of_program(None).program_changed());
        assert!(!Drain::of_program(Some(PathBuf::from("/no/such/file"))).program_changed());
    }

    #[test]
    fn it_leaves_for_a_new_file_or_for_a_keeper_that_is_gone_and_says_which() {
        let parent = std::os::unix::process::parent_id();
        assert_eq!(Drain::of_program(None).why_leave(), None, "nobody said they keep it: nobody to lose");
        assert_eq!(Drain::of_program(None).kept_by(Some(parent)).why_leave(), None);
        let gone = Drain::of_program(None).kept_by(Some(parent + 1));
        assert_eq!(gone.why_leave(), Some("the controller that keeps it is gone"));
        let folder = std::env::temp_dir().join(format!("caravan-drain-why-{}", std::process::id()));
        fs::create_dir_all(&folder).unwrap();
        let program = folder.join("caravan-proxy");
        fs::write(&program, b"one").unwrap();
        let replaced = Drain::of_program(Some(program.clone())).kept_by(Some(parent));
        assert_eq!(replaced.why_leave(), None);
        fs::write(&program, b"the new one").unwrap();
        assert_eq!(replaced.why_leave(), Some("a new version came"));
        fs::remove_dir_all(&folder).unwrap();
    }

    #[test]
    fn it_starts_open_and_begin_closes_it() {
        let drain = Drain::of_program(None);
        assert!(!drain.is_on());
        drain.begin();
        assert!(drain.is_on());
    }

    #[test]
    fn connections_are_counted_to_their_end_a_panic_included() {
        let drain = Arc::new(Drain::of_program(None));
        let one = drain.connection();
        let two = drain.connection();
        assert_eq!(drain.open(), 2);
        drop(one);
        assert_eq!(drain.open(), 1);
        let ended = std::thread::spawn(move || {
            let _two = two;
            panic!("a bug inside one request");
        })
        .join();
        assert!(ended.is_err());
        assert_eq!(drain.open(), 0);
    }
}
