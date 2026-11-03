//! `str.casefold()`: two names are compared with it, and a client keeps its chats by a name.

use crate::casefold_table::{LONGER, RUNS};

/// The folding of a text, read off Python's own table: `char::to_lowercase` says something else for German's sharp s, Greek's final sigma and
/// some 300 other letters.
pub struct Casefold;

impl Casefold {
    /// `text.casefold()`.
    pub fn of(text: &str) -> String {
        let mut out = String::with_capacity(text.len());
        for letter in text.chars() {
            Self::write(&mut out, letter);
        }
        out
    }

    fn write(out: &mut String, letter: char) {
        let code = u32::from(letter);
        if let Ok(found) = LONGER.binary_search_by_key(&code, |(from, _)| *from)
            && let Some((_, fold)) = LONGER.get(found)
        {
            out.push_str(fold);
            return;
        }
        out.push(Self::single(letter, code));
    }

    fn single(letter: char, code: u32) -> char {
        let at = RUNS.partition_point(|(first, _, _, _)| *first <= code);
        let run = at.checked_sub(1).and_then(|at| RUNS.get(at));
        let Some((first, last, every, far)) = run else {
            return letter;
        };
        if code > *last || !(code - first).is_multiple_of(*every) {
            return letter;
        }
        code.checked_add_signed(*far).and_then(char::from_u32).unwrap_or(letter)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_name_folds_as_python_folds_it() {
        for (text, fold) in [
            ("Qwen3-Omni", "qwen3-omni"),
            ("Модель", "модель"),
            ("Straße", "strasse"),
            ("ΣΊΣΥΦΟΣ", "σίσυφοσ"),
            ("ς", "σ"),
            ("ﬁne", "fine"),
            ("Ꭰ", "Ꭰ"),
            ("ꭰ", "Ꭰ"),
            ("İ", "i\u{307}"),
            ("Āā", "āā"),
            ("日本語", "日本語"),
            ("", ""),
        ] {
            assert_eq!(Casefold::of(text), fold, "{text}");
        }
    }
}
