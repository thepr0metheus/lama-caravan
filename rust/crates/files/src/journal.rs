//! The proxy's journal: `logs/proxy-events/<date>.jsonl`.
//!
//! Two processes may share the file, and it is safe to: it is only ever added to, opened with `O_APPEND`, and each row goes out in one write, so two
//! processes do not mix their lines. The file is opened for each row: a day's file replaced from outside (a key masked out of its rows, 2026-11) goes on
//! being written, and no row goes to a file nobody can read any more.

use os::LocalTime;
use std::fs::{self, OpenOptions};
use std::io::{self, Write};
use std::path::PathBuf;
use std::sync::{Mutex, PoisonError};

/// Rows added to the file of the day they happen on, by the local clock: the zone `TZ` names.
pub struct Journal {
    folder: PathBuf,
    keep_days: Option<i64>,
    /// The day old files were last taken away on: once a day is enough, and a row must not pay for a listing.
    trimmed_on: Mutex<String>,
}

impl Journal {
    /// The journal in `folder`, made when the first row comes. `keep_days`: how many days back a file stays; `None` keeps them all, for when another process trims:
    /// two trimmers would be two owners of one rule.
    pub fn new(folder: PathBuf, keep_days: Option<i64>) -> Self {
        Self { folder, keep_days, trimmed_on: Mutex::new(String::new()) }
    }

    /// Adds one row at the moment `epoch`. A row is one line: a line end in it would be two rows, which `serde_json` never
    /// writes. A failure is the caller's to count: it must not fail the request it is about.
    pub fn append(&self, epoch: i64, row: &[u8]) -> io::Result<()> {
        let date =
            LocalTime::of(epoch).map(|moment| moment.date()).ok_or_else(|| io::Error::other("the moment has no local date"))?;
        let mut line = Vec::with_capacity(row.len() + 1);
        line.extend_from_slice(row);
        line.push(b'\n');
        fs::create_dir_all(&self.folder)?;
        OpenOptions::new().append(true).create(true).open(self.folder.join(format!("{date}.jsonl")))?.write_all(&line)?;
        self.trim_once_a_day(epoch, date);
        Ok(())
    }

    fn trim_once_a_day(&self, epoch: i64, today: String) {
        let Some(days) = self.keep_days else {
            return;
        };
        {
            let mut trimmed_on = self.trimmed_on.lock().unwrap_or_else(PoisonError::into_inner);
            if *trimmed_on == today {
                return;
            }
            *trimmed_on = today;
        }
        let Some(cutoff) = LocalTime::of(epoch - days * 86_400).map(|moment| moment.date()) else {
            return;
        };
        self.take_older_than(&cutoff);
    }

    /// A day's file older than `cutoff` goes, as `trim_proxy_event_logs` takes it; a file whose name is no day stays. One that cannot be taken is taken at the next trim.
    fn take_older_than(&self, cutoff: &str) {
        let Ok(entries) = fs::read_dir(&self.folder) else {
            return;
        };
        for entry in entries.flatten() {
            let name = entry.file_name();
            let day = name.to_str().and_then(|name| name.strip_suffix(".jsonl")).filter(|day| Self::is_day(day));
            if day.is_some_and(|day| day < cutoff) {
                drop(fs::remove_file(entry.path()));
            }
        }
    }

    /// `YYYY-MM-DD`: read as text they sort as the days do.
    fn is_day(word: &str) -> bool {
        word.len() == 10
            && word
                .bytes()
                .enumerate()
                .all(|(at, letter)| if at == 4 || at == 7 { letter == b'-' } else { letter.is_ascii_digit() })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rows_go_to_the_file_of_their_day_each_on_its_line() {
        let folder = std::env::temp_dir().join(format!("caravan-journal-{}", std::process::id()));
        let journal = Journal::new(folder.clone(), None);
        let (first_day, next_day) = (1_793_491_199, 1_793_491_199 + 2 * 86_400);
        journal.append(first_day, b"{\"a\":1}").unwrap();
        journal.append(first_day, b"{\"a\":2}").unwrap();
        journal.append(next_day, b"{\"a\":3}").unwrap();
        let name = |epoch| folder.join(format!("{}.jsonl", LocalTime::of(epoch).unwrap().date()));
        assert_eq!(fs::read_to_string(name(first_day)).unwrap(), "{\"a\":1}\n{\"a\":2}\n");
        assert_eq!(fs::read_to_string(name(next_day)).unwrap(), "{\"a\":3}\n");
        fs::remove_dir_all(&folder).unwrap();
    }

    #[test]
    fn a_file_another_process_adds_to_keeps_every_line() {
        let folder = std::env::temp_dir().join(format!("caravan-journal-two-{}", std::process::id()));
        let journal = Journal::new(folder.clone(), None);
        let epoch = 1_793_491_199;
        journal.append(epoch, b"mine").unwrap();
        let path = folder.join(format!("{}.jsonl", LocalTime::of(epoch).unwrap().date()));
        let mut other = OpenOptions::new().append(true).open(&path).unwrap();
        other.write_all(b"theirs\n").unwrap();
        journal.append(epoch, b"mine again").unwrap();
        assert_eq!(fs::read_to_string(&path).unwrap(), "mine\ntheirs\nmine again\n");
        fs::remove_dir_all(&folder).unwrap();
    }

    #[test]
    fn a_file_replaced_from_outside_goes_on_being_written() {
        let folder = std::env::temp_dir().join(format!("caravan-journal-replaced-{}", std::process::id()));
        let journal = Journal::new(folder.clone(), None);
        let epoch = 1_793_491_199;
        journal.append(epoch, b"before").unwrap();
        let path = folder.join(format!("{}.jsonl", LocalTime::of(epoch).unwrap().date()));
        let beside = folder.join("clean");
        fs::write(&beside, b"masked\n").unwrap();
        fs::rename(&beside, &path).unwrap();
        journal.append(epoch, b"after").unwrap();
        assert_eq!(fs::read_to_string(&path).unwrap(), "masked\nafter\n");
        fs::remove_dir_all(&folder).unwrap();
    }

    #[test]
    fn old_days_go_once_a_day_and_nothing_else_does() {
        let folder = std::env::temp_dir().join(format!("caravan-journal-old-{}", std::process::id()));
        fs::create_dir_all(&folder).unwrap();
        // A moment with a next second on the same day, in whatever zone this runs.
        let date = |epoch: i64| LocalTime::of(epoch).unwrap().date();
        let epoch = (1_793_491_199..).find(|epoch| date(*epoch) == date(*epoch + 1)).unwrap();
        let day = |back: i64| LocalTime::of(epoch - back * 86_400).unwrap().date();
        let place = |name: String| folder.join(name);
        for name in [
            format!("{}.jsonl", day(31)),
            format!("{}.jsonl", day(30)),
            format!("{}.jsonl", day(1)),
            "notes.jsonl".to_string(),
            "2026-1-5.jsonl".to_string(),
            "0000000000.jsonl".to_string(),
            format!("{}.txt", day(40)),
        ] {
            fs::write(place(name), b"x\n").unwrap();
        }
        let journal = Journal::new(folder.clone(), Some(30));
        journal.append(epoch, b"row").unwrap();
        assert!(!place(format!("{}.jsonl", day(31))).exists(), "older than the days it keeps");
        for name in [
            format!("{}.jsonl", day(30)),
            format!("{}.jsonl", day(1)),
            format!("{}.jsonl", day(0)),
            "notes.jsonl".to_string(),
            "2026-1-5.jsonl".to_string(),
            "0000000000.jsonl".to_string(),
            format!("{}.txt", day(40)),
        ] {
            assert!(place(name.clone()).exists(), "{name} stays");
        }
        fs::write(place(format!("{}.jsonl", day(50))), b"x\n").unwrap();
        journal.append(epoch + 1, b"row").unwrap();
        assert!(place(format!("{}.jsonl", day(50))).exists(), "the same day: no second listing");
        journal.append(epoch + 86_400, b"row").unwrap();
        assert!(!place(format!("{}.jsonl", day(50))).exists(), "the next day trims again");
        fs::remove_dir_all(&folder).unwrap();
    }

    #[test]
    fn with_no_days_to_keep_every_file_stays() {
        let folder = std::env::temp_dir().join(format!("caravan-journal-all-{}", std::process::id()));
        fs::create_dir_all(&folder).unwrap();
        let old = folder.join("2001-01-01.jsonl");
        fs::write(&old, b"x\n").unwrap();
        Journal::new(folder.clone(), None).append(1_793_491_199, b"row").unwrap();
        assert!(old.exists());
        fs::remove_dir_all(&folder).unwrap();
    }
}
