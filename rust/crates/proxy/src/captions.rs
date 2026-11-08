//! What the board's reader said of the pictures it read, kept in this process's memory (the owner, 2026-11-06: "кеш в
//! памяти"): the same picture sent again — a client sends its whole conversation with every turn — is not read again.
//!
//! A caption is kept under the key `MediaReader::key` says — the picture, the reader and the version of the words — so a
//! changed picture, another reader or other words are another caption. Only a reading that gave words is kept: a failure is
//! asked again next time, never remembered as a caption. Nothing is written to disk, and a restart forgets it all: a caption
//! is the reader's interpretation of a client's picture, and it is not the caravan's to keep beyond its use.

use std::collections::{HashMap, VecDeque};
use std::sync::{Mutex, PoisonError};

/// The captions, by key, with the order they were kept in.
#[derive(Debug, Default)]
struct Kept {
    said: HashMap<String, (String, f64)>,
    order: VecDeque<String>,
}

/// The captions this process keeps: bounded by count and by age.
#[derive(Debug, Default)]
pub struct Captions {
    kept: Mutex<Kept>,
}

impl Captions {
    /// How many captions are kept at most: the oldest goes first. A conversation of screenshots holds a few dozen.
    const MOST: usize = 256;
    /// How long one is kept, in seconds: a day, the length of a working session and its next morning.
    const AGE: f64 = 86_400.0;

    fn kept(&self) -> std::sync::MutexGuard<'_, Kept> {
        self.kept.lock().unwrap_or_else(PoisonError::into_inner)
    }

    /// The caption kept under `key`, when one is and it is not older than `AGE` at `now`.
    pub fn get(&self, key: &str, now: f64) -> Option<String> {
        let kept = self.kept();
        let (words, at) = kept.said.get(key)?;
        (now - at < Self::AGE).then(|| words.clone())
    }

    /// Keeps `words` under `key` at `now`, the oldest going when there are too many.
    pub fn keep(&self, key: String, words: String, now: f64) {
        let mut kept = self.kept();
        if kept.said.insert(key.clone(), (words, now)).is_none() {
            kept.order.push_back(key);
        }
        while kept.order.len() > Self::MOST {
            if let Some(oldest) = kept.order.pop_front() {
                kept.said.remove(&oldest);
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_caption_is_found_by_its_key_until_it_is_a_day_old() {
        let captions = Captions::default();
        captions.keep("a".to_string(), "A red bicycle.".to_string(), 1000.0);
        assert_eq!(captions.get("a", 1000.0 + 60.0).as_deref(), Some("A red bicycle."));
        // Negative: another key is another picture, reader or version of the words.
        assert_eq!(captions.get("b", 1000.0), None);
        // Negative: a day later the caption is not said any more.
        assert_eq!(captions.get("a", 1000.0 + Captions::AGE), None);
    }

    #[test]
    fn the_oldest_caption_goes_first_when_too_many_are_kept() {
        let captions = Captions::default();
        for number in 0..=Captions::MOST {
            captions.keep(format!("k{number}"), format!("w{number}"), 1000.0);
        }
        assert_eq!(captions.get("k0", 1000.0), None, "the first kept is the first gone");
        assert_eq!(captions.get("k1", 1000.0).as_deref(), Some("w1"));
        assert_eq!(
            captions.get(&format!("k{}", Captions::MOST), 1000.0).as_deref(),
            Some(format!("w{}", Captions::MOST).as_str())
        );
        // Kept again under the same key, a caption is not counted twice.
        captions.keep("k1".to_string(), "w1 again".to_string(), 1000.0);
        assert_eq!(captions.kept().order.len(), Captions::MOST);
    }
}
