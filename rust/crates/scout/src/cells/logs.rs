//! Where the cells' logs lie and how long they stay. They lay in the model cache's folder until 2026-11-03: Clear left them, Change left them behind, and nothing ever took one away (405 files from two months, the owner: "let them stay 30 days").

use crate::log::Log;
use crate::process::log::FileTimes;
use os::clock::Clock;
use std::collections::BTreeSet;
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::Arc;

/// The logs of this machine's cells.
pub struct CellLogs {
    folder: PathBuf,
    clock: Arc<dyn Clock>,
}

impl CellLogs {
    /// How long a log stays, seconds.
    const KEPT_SEC: i64 = 30 * 86_400;
    /// The names of a cell's log, by what it runs.
    const NAMES: [&'static str; 2] = ["llama-server", "command-cell"];

    /// The logs in `folder`, which is made when the first is written.
    pub fn new(folder: PathBuf, clock: Arc<dyn Clock>) -> Self {
        Self { folder, clock }
    }

    /// Where they lie.
    pub fn folder(&self) -> &Path {
        &self.folder
    }

    /// Where a cell of `name` on `port` writes. A folder that cannot be made is said by the write that follows.
    pub fn path(&self, name: &str, port: i64) -> PathBuf {
        // absent-ok: the write that follows says what is wrong with the place.
        drop(fs::create_dir_all(&self.folder));
        self.folder.join(format!("{name}.{port}.log"))
    }

    /// The log a cell on `port` wrote last, here or in the folder logs lay in before; `None` for a cell that wrote none.
    pub fn find(&self, port: i64, before: &Path) -> Option<PathBuf> {
        [self.folder.as_path(), before].into_iter().find_map(|folder| {
            Self::NAMES.iter().map(|name| folder.join(format!("{name}.{port}.log"))).find(|path| path.is_file())
        })
    }

    /// The port of a log's file name: `llama-server.22013.log`, `command-cell.22013.20261002-125817.log`. `None` for a file that is no cell's log.
    fn port_of(name: &str) -> Option<i64> {
        let rest = name.strip_suffix(".log")?;
        let rest = Self::NAMES.iter().find_map(|kind| rest.strip_prefix(kind)?.strip_prefix('.'))?;
        rest.split('.').next()?.parse().ok()
    }

    /// Whether this is the log a cell of `port` is writing now: a kept run has its moment in its name.
    fn is_current(name: &str, port: i64) -> bool {
        Self::NAMES.iter().any(|kind| name == format!("{kind}.{port}.log"))
    }

    /// One pass: what lies in the folder of before comes here, and what is older than the time they stay goes, from both. A log a running cell writes stays where it is, whatever its age.
    pub fn pass(&self, before: &Path, live: &BTreeSet<i64>) {
        let (mut moved, mut gone) = (0, 0);
        let now = self.clock.epoch() as i64;
        for folder in [self.folder.as_path(), before] {
            for entry in fs::read_dir(folder).into_iter().flatten().flatten() {
                let name = entry.file_name().to_string_lossy().into_owned();
                let Some(port) = Self::port_of(&name) else {
                    continue;
                };
                if live.contains(&port) && Self::is_current(&name, port) {
                    continue;
                }
                let old = entry.metadata().is_ok_and(|meta| now - FileTimes::modified(&meta) > Self::KEPT_SEC);
                if old {
                    gone += u32::from(fs::remove_file(entry.path()).is_ok());
                } else if folder != self.folder {
                    moved += u32::from(self.brought(&entry.path(), &name));
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

    /// The log at `path` here. On another disk it is copied, and the original goes only when the copy is whole.
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

    #[test]
    fn a_log_stays_thirty_days_and_a_running_cell_keeps_the_one_it_writes() {
        let folder = TestFolder::new("logs-age");
        let logs = logs(&folder);
        let (young, old, running, its_old_run) = (
            put(logs.folder(), "llama-server.1.log", 29),
            put(logs.folder(), "command-cell.2.20261001-101010.log", 31),
            put(logs.folder(), "llama-server.3.log", 90),
            put(logs.folder(), "llama-server.3.20260801-101010.log", 90),
        );
        logs.pass(&folder.path.join("nothing"), &BTreeSet::from([3]));
        assert!(young.exists(), "29 days");
        assert!(!old.exists(), "31 days");
        assert!(running.exists(), "a running cell writes it, however quiet it has been");
        assert!(!its_old_run.exists(), "its old runs are no different from anybody's");
    }

    #[test]
    fn what_lay_in_the_cache_comes_here_and_nothing_else_of_it_moves() {
        let folder = TestFolder::new("logs-move");
        let logs = logs(&folder);
        let cache = folder.path.join("cache");
        let (log, kept_run, old, running) = (
            put(&cache, "llama-server.1.log", 1),
            put(&cache, "command-cell.1.20261002-125817.log", 2),
            put(&cache, "command-cell.2.log", 40),
            put(&cache, "llama-server.3.log", 1),
        );
        let others = [
            put(&cache, "model.gguf", 90),
            put(&cache, "notes.log", 90),
            put(&cache, "llama-server.log", 90),
            put(&cache, "llama-server.x.log", 90),
            put(&cache, ".caravan-downloads.json", 90),
        ];
        logs.pass(&cache, &BTreeSet::from([3]));
        assert!(!log.exists() && logs.folder().join("llama-server.1.log").is_file());
        assert!(!kept_run.exists() && logs.folder().join("command-cell.1.20261002-125817.log").is_file(), "its old runs too");
        assert!(!old.exists() && !logs.folder().join("command-cell.2.log").exists(), "too old to bring");
        assert!(
            running.exists() && !logs.folder().join("llama-server.3.log").exists(),
            "a running cell goes on writing where it writes"
        );
        assert!(others.iter().all(|path| path.exists()), "what is no cell's log stays");
    }

    #[test]
    fn a_cell_s_log_is_found_here_first_then_where_it_lay() {
        let folder = TestFolder::new("logs-find");
        let logs = logs(&folder);
        let cache = folder.path.join("cache");
        assert_eq!(logs.find(1, &cache), None);
        let there = put(&cache, "llama-server.1.log", 1);
        assert_eq!(logs.find(1, &cache), Some(there));
        let here = put(logs.folder(), "command-cell.1.log", 1);
        assert_eq!(logs.find(1, &cache), Some(here));
        assert_eq!(logs.path("llama-server", 7), logs.folder().join("llama-server.7.log"));
        assert!(logs.folder().is_dir());
    }

    #[test]
    fn a_name_is_read_for_its_port() {
        assert_eq!(CellLogs::port_of("llama-server.22013.log"), Some(22013));
        assert_eq!(CellLogs::port_of("command-cell.22013.20261002-125817.log"), Some(22013));
        for name in
            ["llama-server.log", "llama-server.x.log", "other.22013.log", "llama-server.22013.txt", "llama-server-22013.log"]
        {
            assert_eq!(CellLogs::port_of(name), None, "{name}");
        }
    }
}
