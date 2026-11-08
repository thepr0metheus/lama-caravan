//! Where the cells' logs lie and how long they stay. They lay in the model cache's folder until 2026-11-03: Clear left them, Change left them behind, and nothing ever took one away (405 files from two months, the owner: "let them stay 30 days").
//!
//! A log bears its cell's name: `llama-server.c3f9a2b1.log`, and a run kept aside its moment after it, `command-cell.c3f9a2b1.20261002-125817.log`. Until 2026-11-07 it bore the cell's port; a name of
//! then is read as its cell's name of now (`c<port>`), and the log is renamed to it when it comes into the logs' folder or when the scout of now first starts (`migration.rs`).

use crate::log::Log;
use crate::process::log::FileTimes;
use crate::state::ScoutState;
use os::clock::Clock;
use rules::CellId;
use serde_json::Value;
use std::collections::BTreeSet;
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::Arc;

/// A cell's log by its file name: which cell, and whether it is the cell's current log or a run kept aside.
#[derive(Debug, PartialEq, Eq)]
struct LogName {
    /// What it runs, `llama-server` or `command-cell`.
    kind: &'static str,
    /// The cell's name.
    cell: String,
    /// The moment a kept run bears; `None` for the log the cell writes.
    stamp: Option<String>,
}

impl LogName {
    /// The name as it is to be: by its cell's name.
    fn file_name(&self) -> String {
        match &self.stamp {
            Some(stamp) => format!("{}.{}.{stamp}.log", self.kind, self.cell),
            None => format!("{}.{}.log", self.kind, self.cell),
        }
    }
}

/// The logs of this machine's cells.
pub struct CellLogs {
    folder: PathBuf,
    clock: Arc<dyn Clock>,
}

impl CellLogs {
    /// The folder beside the state they lie in.
    const FOLDER: &'static str = "cell-logs";
    /// How long a log stays, seconds.
    const KEPT_SEC: i64 = 30 * 86_400;
    /// The names of a cell's log, by what it runs.
    const NAMES: [&'static str; 2] = ["llama-server", "command-cell"];

    /// The logs in `folder`, which is made when the first is written.
    pub fn new(folder: PathBuf, clock: Arc<dyn Clock>) -> Self {
        Self { folder, clock }
    }

    /// The logs of the scout whose state this is: in a folder beside it.
    pub fn of_state(state: &ScoutState, clock: Arc<dyn Clock>) -> Self {
        Self::new(state.folder().join(Self::FOLDER), clock)
    }

    /// Where they lie.
    pub fn folder(&self) -> &Path {
        &self.folder
    }

    /// Where a cell of `kind` named `cell` writes: nothing is made for it.
    pub fn named(&self, kind: &str, cell: &str) -> PathBuf {
        self.folder.join(format!("{kind}.{cell}.log"))
    }

    /// Where a cell of `kind` named `cell` writes, its folder made. A folder that cannot be made is said by the write that follows.
    pub fn path(&self, kind: &str, cell: &str) -> PathBuf {
        // absent-ok: the write that follows says what is wrong with the place.
        drop(fs::create_dir_all(&self.folder));
        self.named(kind, cell)
    }

    /// The log the cell `cell` wrote last, here first, then in the folder logs lay in before: a llama server's before a command cell's, a name of now before the port it bore before 2026-11-07.
    /// `None` for a cell that wrote none.
    pub fn find(&self, cell: &str, before: &Path) -> Option<PathBuf> {
        [self.folder.as_path(), before].into_iter().find_map(|folder| {
            let mut found: Vec<(usize, bool, PathBuf)> = fs::read_dir(folder)
                .into_iter()
                .flatten()
                .flatten()
                .filter_map(|entry| {
                    let name = entry.file_name().to_string_lossy().into_owned();
                    let log = Self::read(&name).filter(|log| log.cell == cell && log.stamp.is_none())?;
                    let kind = Self::NAMES.iter().position(|kind| *kind == log.kind)?;
                    Some((kind, name != log.file_name(), entry.path())).filter(|(_, _, path)| path.is_file())
                })
                .collect();
            found.sort();
            found.into_iter().next().map(|(_, _, path)| path)
        })
    }

    /// A log's file name read: `llama-server.c22013.log`, `command-cell.22013.20261002-125817.log` (a cell of before, by its port). `None` for a file that is no cell's log.
    fn read(name: &str) -> Option<LogName> {
        let rest = name.strip_suffix(".log")?;
        let (kind, rest) = Self::NAMES.iter().find_map(|kind| Some((*kind, rest.strip_prefix(kind)?.strip_prefix('.')?)))?;
        let (said, stamp) = match rest.split_once('.') {
            Some((said, stamp)) => (said, Some(stamp.to_string())),
            None => (rest, None),
        };
        let cell = CellId::read(&Value::String(said.to_string()))?;
        Some(LogName { kind, cell, stamp })
    }

    /// The name a log of before is to bear now: `None` for one that bears its cell's name already, or is no cell's log.
    pub fn renamed(name: &str) -> Option<String> {
        Self::read(name).map(|log| log.file_name()).filter(|now| now != name)
    }

    /// Every log here that bears its cell's port, renamed to bear its name: what was renamed, from where to where. A name taken already is left as it is, and so is the log under the old one.
    pub fn rename_by_port(&self) -> Vec<(PathBuf, PathBuf)> {
        let mut done = Vec::new();
        for entry in fs::read_dir(&self.folder).into_iter().flatten().flatten() {
            let Some(now) = Self::renamed(&entry.file_name().to_string_lossy()) else {
                continue;
            };
            let (old, new) = (entry.path(), self.folder.join(now));
            if !new.exists() && fs::rename(&old, &new).is_ok() {
                done.push((old, new));
            }
        }
        done.sort();
        done
    }

    /// One pass: what lies in the folder of before comes here, under its cell's name, and what is older than the time they stay goes, from both. A log a running cell writes stays where it is,
    /// whatever its age.
    pub fn pass(&self, before: &Path, live: &BTreeSet<String>) {
        let (mut moved, mut gone) = (0, 0);
        let now = self.clock.epoch() as i64;
        for folder in [self.folder.as_path(), before] {
            for entry in fs::read_dir(folder).into_iter().flatten().flatten() {
                let name = entry.file_name().to_string_lossy().into_owned();
                let Some(log) = Self::read(&name) else {
                    continue;
                };
                if live.contains(&log.cell) && log.stamp.is_none() {
                    continue;
                }
                let old = entry.metadata().is_ok_and(|meta| now - FileTimes::modified(&meta) > Self::KEPT_SEC);
                if old {
                    gone += u32::from(fs::remove_file(entry.path()).is_ok());
                } else if folder != self.folder {
                    moved += u32::from(self.brought(&entry.path(), &log.file_name()));
                }
            }
        }
        if moved != 0 || gone != 0 {
            Log::line(&format!(
                "[llama-node] cells' logs: {moved} brought to {}, {gone} older than 30 days removed",
                self.folder.display()
            ));
        }
    }

    /// The log at `path` here, as `name`. On another disk it is copied, and the original goes only when the copy is whole.
    fn brought(&self, path: &Path, name: &str) -> bool {
        let here = self.path_of_name(name);
        fs::rename(path, &here).is_ok() || (fs::copy(path, &here).is_ok() && fs::remove_file(path).is_ok())
    }

    fn path_of_name(&self, name: &str) -> PathBuf {
        // absent-ok: the move that follows says what is wrong with the place.
        drop(fs::create_dir_all(&self.folder));
        self.folder.join(name)
    }
}

#[cfg(test)]
mod tests {
    #![allow(clippy::unwrap_used, reason = "a helper of a test may stop where it found something wrong")]

    use super::*;
    use crate::tests::{HandClock, TestFolder};

    /// A file of this age, by its name.
    fn put(folder: &Path, name: &str, age_days: i64) -> PathBuf {
        fs::create_dir_all(folder).unwrap();
        let path = folder.join(name);
        fs::write(&path, b"a line").unwrap();
        let moment = std::time::SystemTime::now() - std::time::Duration::from_secs((age_days * 86_400) as u64);
        fs::File::options().write(true).open(&path).unwrap().set_modified(moment).unwrap();
        path
    }

    fn logs(folder: &TestFolder) -> CellLogs {
        let now = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_secs();
        CellLogs::new(folder.path.join("cell-logs"), HandClock::at(now))
    }

    fn cells(names: &[&str]) -> BTreeSet<String> {
        names.iter().map(|name| (*name).to_string()).collect()
    }

    #[test]
    fn a_log_stays_thirty_days_and_a_running_cell_keeps_the_one_it_writes() {
        let folder = TestFolder::new("logs-age");
        let logs = logs(&folder);
        let (young, old, running, its_old_run) = (
            put(logs.folder(), "llama-server.c1.log", 29),
            put(logs.folder(), "command-cell.c2.20261001-101010.log", 31),
            put(logs.folder(), "llama-server.c3.log", 90),
            put(logs.folder(), "llama-server.c3.20260801-101010.log", 90),
        );
        logs.pass(&folder.path.join("nothing"), &cells(&["c3"]));
        assert!(young.exists(), "29 days");
        assert!(!old.exists(), "31 days");
        assert!(running.exists(), "a running cell writes it, however quiet it has been");
        assert!(!its_old_run.exists(), "its old runs are no different from anybody's");
    }

    #[test]
    fn what_lay_in_the_cache_comes_here_under_its_cell_s_name_and_nothing_else_of_it_moves() {
        let folder = TestFolder::new("logs-move");
        let logs = logs(&folder);
        let cache = folder.path.join("cache");
        let (log, kept_run, old, running, named) = (
            put(&cache, "llama-server.1.log", 1),
            put(&cache, "command-cell.1.20261002-125817.log", 2),
            put(&cache, "command-cell.2.log", 40),
            put(&cache, "llama-server.3.log", 1),
            put(&cache, "command-cell.c3f9a2b1.log", 1),
        );
        let others = [
            put(&cache, "model.gguf", 90),
            put(&cache, "notes.log", 90),
            put(&cache, "llama-server.log", 90),
            put(&cache, "llama-server.x.log", 90),
            put(&cache, ".caravan-downloads.json", 90),
        ];
        logs.pass(&cache, &cells(&["c3"]));
        assert!(
            !log.exists() && logs.folder().join("llama-server.c1.log").is_file(),
            "a log of before bears its cell's name here"
        );
        assert!(!kept_run.exists() && logs.folder().join("command-cell.c1.20261002-125817.log").is_file(), "its old runs too");
        assert!(!named.exists() && logs.folder().join("command-cell.c3f9a2b1.log").is_file(), "a log of now as it is");
        assert!(!old.exists() && !logs.folder().join("command-cell.c2.log").exists(), "too old to bring");
        assert!(
            running.exists() && !logs.folder().join("llama-server.c3.log").exists(),
            "a running cell goes on writing where it writes, by its port of before as the cell c3"
        );
        assert!(others.iter().all(|path| path.exists()), "what is no cell's log stays");
    }

    #[test]
    fn a_cell_s_log_is_found_here_first_then_where_it_lay() {
        let folder = TestFolder::new("logs-find");
        let logs = logs(&folder);
        let cache = folder.path.join("cache");
        assert_eq!(logs.find("c1", &cache), None);
        let there = put(&cache, "llama-server.1.log", 1);
        assert_eq!(logs.find("c1", &cache), Some(there), "a cell of before is found by the port its log bore");
        let here = put(logs.folder(), "command-cell.c1.log", 1);
        assert_eq!(logs.find("c1", &cache), Some(here.clone()), "here first");
        put(logs.folder(), "command-cell.c1.20261101-101010.log", 1);
        put(logs.folder(), "llama-server.c12.log", 1);
        assert_eq!(logs.find("c1", &cache), Some(here), "a run kept aside, or another cell's, is not the cell's log");
        assert_eq!(logs.path("llama-server", "c7"), logs.folder().join("llama-server.c7.log"));
        assert!(logs.folder().is_dir());
    }

    #[test]
    fn a_name_is_read_for_its_cell_and_one_of_before_for_the_cell_of_its_port() {
        let read = |name: &str| CellLogs::read(name).map(|log| (log.kind, log.cell, log.stamp));
        assert_eq!(read("llama-server.c22013.log"), Some(("llama-server", "c22013".to_string(), None)));
        assert_eq!(
            read("command-cell.22013.20261002-125817.log"),
            Some(("command-cell", "c22013".to_string(), Some("20261002-125817".to_string())))
        );
        for name in [
            "llama-server.log",
            "llama-server.x.log",
            "other.22013.log",
            "llama-server.22013.txt",
            "llama-server-22013.log",
            "llama-server.C1.log",
        ] {
            assert_eq!(read(name), None, "{name}");
        }
        assert_eq!(CellLogs::renamed("llama-server.22013.log").as_deref(), Some("llama-server.c22013.log"));
        assert_eq!(
            CellLogs::renamed("command-cell.22013.20261002-125817.log").as_deref(),
            Some("command-cell.c22013.20261002-125817.log")
        );
        assert_eq!(CellLogs::renamed("llama-server.c22013.log"), None, "a name of now stays as it is");
        assert_eq!(CellLogs::renamed("notes.log"), None);
    }

    #[test]
    fn the_logs_of_before_are_renamed_once_and_a_name_taken_is_left_alone() {
        let folder = TestFolder::new("logs-rename");
        let logs = logs(&folder);
        let (legacy, run, current, clash, clashing) = (
            put(logs.folder(), "llama-server.22001.log", 1),
            put(logs.folder(), "command-cell.22002.20261002-125817.log", 1),
            put(logs.folder(), "llama-server.c22003.log", 1),
            put(logs.folder(), "command-cell.c22004.log", 1),
            put(logs.folder(), "command-cell.22004.log", 1),
        );
        let renamed = logs.rename_by_port();
        let new = |name: &str| logs.folder().join(name);
        assert_eq!(
            renamed,
            [(run.clone(), new("command-cell.c22002.20261002-125817.log")), (legacy.clone(), new("llama-server.c22001.log")),]
        );
        assert!(!legacy.exists() && !run.exists() && current.exists());
        assert!(clash.exists() && clashing.exists(), "a name taken is not written over: both stay as they are");
        assert!(logs.rename_by_port().is_empty(), "once: nothing of before is left the second time");
    }
}
