//! A folder of the scout's moved with its files. The owner, 2026-11-03: "when the path is moved, the files move with it; when the folder is removed, they go — let me either delete or move". A move copies
//! each of the scout's own files into the new folder under a name of its own and gives it its name when it is whole; only when every one is there does the setting turn to the new folder, and then the
//! old files go. A move that fails on the way takes its copies back and leaves the old folder as it was. It runs on a thread of its own, as a cache of a hundred GB takes many minutes to an HDD, and the
//! board reads how far it is in the cache's report, while the cache refuses what would change its files under it.

use crate::errors::AppError;
use crate::log::{Log, Thousands};
use crate::models::shelf::Shelf;
use os::Disk;
use serde_json::{Map, Value, json};
use std::collections::BTreeSet;
use std::fs;
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex, MutexGuard, PoisonError};

/// A move under way: which shelf, where to, how far.
#[derive(Debug, Clone)]
struct Moving {
    moved: &'static Shelf,
    to: PathBuf,
    done: u64,
    total: u64,
}

/// The moves of this scout's folders: one at a time, how far the one under way is, why the last one failed, and how many have ended, so that figures measured before one are measured again.
#[derive(Debug, Default)]
pub struct Relocation {
    now: Mutex<(Option<Moving>, Option<String>, u64)>,
}

impl Relocation {
    fn lock(&self) -> MutexGuard<'_, (Option<Moving>, Option<String>, u64)> {
        self.now.lock().unwrap_or_else(PoisonError::into_inner)
    }

    /// Refuses while a move is under way, in words that say what moves where.
    pub fn refuse_while_moving(&self) -> Result<(), AppError> {
        match &self.lock().0 {
            Some(moving) => Err(AppError::with_status(
                format!("{} is moving to {}: try again when it is done", moving.moved.named, moving.to.display()),
                409,
            )),
            None => Ok(()),
        }
    }

    /// Whether a move is under way.
    pub fn is_moving(&self) -> bool {
        self.lock().0.is_some()
    }

    /// How many moves have ended.
    pub fn ended(&self) -> u64 {
        self.lock().2
    }

    /// What the board reads: `moving: {what, to, doneBytes, totalBytes}` while a move is under way, `moveError` when the last one failed.
    pub fn facts(&self) -> Map<String, Value> {
        let now = self.lock();
        let mut out = Map::new();
        if let Some(moving) = &now.0 {
            let said = json!({"what": moving.moved.word, "to": moving.to.display().to_string(), "doneBytes": moving.done, "totalBytes": moving.total});
            out.insert("moving".to_string(), said);
        }
        if let Some(words) = &now.1 {
            out.insert("moveError".to_string(), json!(words));
        }
        out
    }

    /// Takes the one place for a move.
    fn begin(&self, moved: &'static Shelf, to: &Path, total: u64) -> Result<(), AppError> {
        self.refuse_while_moving()?;
        let mut now = self.lock();
        now.0 = Some(Moving { moved, to: to.to_path_buf(), done: 0, total });
        now.1 = None;
        Ok(())
    }

    fn advance(&self, bytes: u64) {
        if let Some(moving) = &mut self.lock().0 {
            moving.done = moving.done.saturating_add(bytes);
        }
    }

    fn end(&self, error: Option<String>) {
        let mut now = self.lock();
        now.0 = None;
        now.1 = error;
        now.2 += 1;
    }
}

/// One move of files: their names inside `from`, copied to the same names inside `to`.
pub struct FileMove {
    /// The folder they leave.
    pub from: PathBuf,
    /// The folder they go to.
    pub to: PathBuf,
    /// Their names inside both.
    pub names: Vec<String>,
}

impl FileMove {
    const PART: &'static str = ".caravan-move";
    const CHUNK: usize = 8 << 20;

    /// The bytes it copies: what each file takes, a link nothing.
    pub fn bytes(&self) -> u64 {
        let sizes = self.names.iter().filter_map(|name| fs::symlink_metadata(self.from.join(name)).ok());
        sizes.filter(std::fs::Metadata::is_file).map(|meta| meta.len()).sum()
    }

    /// Refuses a move that would write over a file the new folder already holds, or that its disk cannot take with `left` bytes to spare.
    fn refuse_what_cannot_go(&self, total: u64, left: u64) -> Result<(), AppError> {
        let taken: Vec<&String> =
            self.names.iter().filter(|name| fs::symlink_metadata(self.to.join(name)).is_ok()).take(3).collect();
        if !taken.is_empty() {
            let named: Vec<&str> = taken.iter().map(|name| name.as_str()).collect();
            let words = format!(
                "{} already holds {}: choose an empty folder, or delete the files instead of moving them",
                self.to.display(),
                named.join(", ")
            );
            return Err(AppError::with_status(words, 409));
        }
        let probe = self.to.ancestors().find(|folder| folder.exists()).unwrap_or(&self.to);
        if let Some((_, free)) = Disk::usage(probe).filter(|(_, free)| *free < total.saturating_add(left)) {
            let gib = |bytes: u64| format!("{:.1} GB", bytes as f64 / f64::from(1u32 << 30));
            let words = format!(
                "{} has {} free, and the move needs {} with {} to spare",
                self.to.display(),
                gib(free),
                gib(total),
                gib(left)
            );
            return Err(AppError::with_status(words, 409));
        }
        Ok(())
    }

    /// The move started on a thread of its own: the files copied, then `switch` turns the setting, then the old files go. `relocation` holds how far it is; a disk that cannot take it, or a file the
    /// new folder already holds, refuses it before anything is written. `left`: what the new folder's disk must still have free when the files are in.
    pub fn start(
        self,
        moved: &'static Shelf,
        relocation: &Arc<Relocation>,
        left: u64,
        switch: Box<dyn FnOnce() + Send>,
    ) -> Result<Value, AppError> {
        let total = self.bytes();
        self.refuse_what_cannot_go(total, left)?;
        relocation.begin(moved, &self.to, total)?;
        let answer =
            json!({"moving": true, "dir": self.to.display().to_string(), "totalBytes": total, "files": self.names.len()});
        let keeps = Arc::clone(relocation);
        let spawned = std::thread::Builder::new().name("folder-move".to_string()).spawn(move || {
            let copied = self.copy(&|bytes| keeps.advance(bytes));
            let error = copied.err();
            if error.is_none() {
                switch();
                self.remove_old();
            }
            Log::line(&format!(
                "[llama-node] {} {} to {}: {} file(s), {} bytes{}",
                moved.named,
                if error.is_none() { "moved" } else { "did not move" },
                self.to.display(),
                self.names.len(),
                Thousands::of(i64::try_from(total).unwrap_or(i64::MAX)),
                error.as_ref().map_or_else(String::new, |words| format!(": {words}"))
            ));
            keeps.end(error);
        });
        if let Err(error) = spawned {
            relocation.end(Some(format!("the move could not start: {error}")));
            return Err(AppError::with_status(format!("the move could not start: {error}"), 500));
        }
        Ok(answer)
    }

    /// Every file copied; on a failure the copies made go, and the words say which file and why.
    fn copy(&self, advance: &dyn Fn(u64)) -> Result<(), String> {
        let mut made = Vec::new();
        for name in &self.names {
            let target = self.to.join(name);
            if let Err(error) = Self::copy_one(&self.from.join(name), &target, advance) {
                made.push(target);
                for copy in &made {
                    drop(fs::remove_file(copy));
                    drop(fs::remove_file(Self::part_of(copy)));
                }
                Self::prune(&self.to, &self.names);
                return Err(format!("{name}: {}", crate::errors::OsWords::of(&error)));
            }
            made.push(target);
        }
        Ok(())
    }

    fn part_of(target: &Path) -> PathBuf {
        // absent-ok: every name a move copies ends in a file's name.
        let mut name = target.file_name().map(std::ffi::OsStr::to_os_string).unwrap_or_default();
        name.push(Self::PART);
        target.with_file_name(name)
    }

    /// One file copied under a name of its own and given its name when whole; a link made again as the link it is.
    fn copy_one(source: &Path, target: &Path, advance: &dyn Fn(u64)) -> std::io::Result<()> {
        if let Some(folder) = target.parent() {
            fs::create_dir_all(folder)?;
        }
        if fs::symlink_metadata(source)?.file_type().is_symlink() {
            return std::os::unix::fs::symlink(fs::read_link(source)?, target);
        }
        let part = Self::part_of(target);
        let mut input = fs::File::open(source)?;
        let mut output = fs::File::create(&part)?;
        let mut buffer = vec![0u8; Self::CHUNK];
        loop {
            let read = input.read(&mut buffer)?;
            let Some(chunk) = buffer.get(..read).filter(|chunk| !chunk.is_empty()) else {
                break;
            };
            output.write_all(chunk)?;
            advance(read as u64);
        }
        output.sync_all()?;
        fs::rename(&part, target)
    }

    /// The old files removed, and the folders they leave empty.
    fn remove_old(&self) {
        for name in &self.names {
            drop(fs::remove_file(self.from.join(name)));
        }
        Self::prune(&self.from, &self.names);
    }

    /// The folders of `names` inside `root` that are empty now, deepest first; `root` stays.
    fn prune(root: &Path, names: &[String]) {
        let folders: BTreeSet<PathBuf> = names
            .iter()
            .flat_map(|name| {
                Path::new(name)
                    .ancestors()
                    .skip(1)
                    .filter(|up| !up.as_os_str().is_empty())
                    .map(Path::to_path_buf)
                    .collect::<Vec<_>>()
            })
            .collect();
        let mut folders: Vec<PathBuf> = folders.into_iter().collect();
        folders.sort_by_key(|folder| std::cmp::Reverse(folder.components().count()));
        for folder in folders {
            // Only an empty folder goes: one that holds anything else stays.
            drop(fs::remove_dir(root.join(folder)));
        }
    }
}

#[cfg(test)]
mod tests {
    #![allow(clippy::unwrap_used, clippy::indexing_slicing, reason = "a test stops where it found something wrong")]

    use super::*;

    #[test]
    fn one_move_at_a_time_and_the_board_hears_how_far_and_why_the_last_failed() {
        let relocation = Relocation::default();
        assert!(relocation.refuse_while_moving().is_ok() && relocation.facts().is_empty());
        relocation.begin(&Shelf::WORK, Path::new("/mnt/hdd"), 100).unwrap();
        relocation.advance(40);
        assert_eq!(relocation.facts()["moving"], json!({"what": "work", "to": "/mnt/hdd", "doneBytes": 40, "totalBytes": 100}));
        let refused = relocation.begin(&Shelf::CACHE, Path::new("/x"), 1).unwrap_err();
        assert_eq!(refused.status, 409);
        assert!(refused.message.contains("the folder for Strata's files is moving to /mnt/hdd"), "{}", refused.message);
        relocation.end(Some("x: no space".to_string()));
        assert_eq!(Value::Object(relocation.facts()), json!({"moveError": "x: no space"}));
        assert_eq!(relocation.ended(), 1);
        relocation.begin(&Shelf::CACHE, Path::new("/y"), 1).unwrap();
        assert!(relocation.facts().get("moveError").is_none(), "a new move forgets the last one's failure");
    }
}
