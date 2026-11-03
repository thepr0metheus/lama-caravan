//! How a moment of the local clock is written: nothing of the system is asked here.

use super::LocalTime;

impl LocalTime {
    /// The date as a journal's file is named: `2026-11-01`.
    pub fn date(&self) -> String {
        format!("{:04}-{:02}-{:02}", self.year, self.month, self.day)
    }

    /// The moment as a file's name holds it: `20261101-150405`.
    pub fn compact(&self) -> String {
        format!("{:04}{:02}{:02}-{:02}{:02}{:02}", self.year, self.month, self.day, self.hour, self.minute, self.second)
    }

    /// The moment as `%Y-%m-%dT%H:%M:%S%z` writes it: `2026-11-01T15:04:05+0400`.
    pub fn iso_with_zone(&self) -> String {
        let (sign, minutes) = if self.offset_minutes < 0 { ('-', -self.offset_minutes) } else { ('+', self.offset_minutes) };
        format!("{}{sign}{:02}{:02}", self.iso(), minutes / 60, minutes % 60)
    }

    /// The moment as Python's `isoformat(timespec="seconds")` writes a naive one: `2026-11-01T15:04:05`.
    pub fn iso(&self) -> String {
        format!("{}T{:02}:{:02}:{:02}", self.date(), self.hour, self.minute, self.second)
    }
}
