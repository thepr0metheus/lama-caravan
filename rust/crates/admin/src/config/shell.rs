//! A command line as a shell reads it: `shlex.split` in POSIX mode, and `difflib.SequenceMatcher`'s opcodes over its tokens, for who owns which token.

/// `shlex.split`.
pub struct ShellSplit;

impl ShellSplit {
    /// The words of `text`; an open quote or a lone last backslash is an error, as `ValueError` was.
    pub fn split(text: &str) -> Result<Vec<String>, String> {
        let mut words = Vec::new();
        let mut word = String::new();
        let mut in_word = false;
        let mut letters = text.chars();
        while let Some(letter) = letters.next() {
            match letter {
                ' ' | '\t' | '\r' | '\n' => {
                    if in_word {
                        words.push(std::mem::take(&mut word));
                        in_word = false;
                    }
                }
                '\'' => {
                    in_word = true;
                    loop {
                        match letters.next() {
                            Some('\'') => break,
                            Some(inner) => word.push(inner),
                            None => return Err("No closing quotation".to_string()),
                        }
                    }
                }
                '"' => {
                    in_word = true;
                    Self::double_quoted(&mut letters, &mut word)?;
                }
                '\\' => {
                    in_word = true;
                    word.push(letters.next().ok_or("No escaped character")?);
                }
                other => {
                    in_word = true;
                    word.push(other);
                }
            }
        }
        if in_word {
            words.push(word);
        }
        Ok(words)
    }

    /// Inside double quotes a backslash escapes only `"` and itself.
    fn double_quoted(letters: &mut std::str::Chars<'_>, word: &mut String) -> Result<(), String> {
        loop {
            match letters.next() {
                Some('"') => return Ok(()),
                Some('\\') => match letters.next() {
                    Some(escaped @ ('"' | '\\')) => word.push(escaped),
                    Some(other) => {
                        word.push('\\');
                        word.push(other);
                    }
                    None => return Err("No escaped character".to_string()),
                },
                Some(other) => word.push(other),
                None => return Err("No closing quotation".to_string()),
            }
        }
    }

    /// `shlex.split` with what cannot be split read as plain words.
    pub fn words(text: &str) -> Vec<String> {
        Self::split(text).unwrap_or_else(|_| text.split_whitespace().map(str::to_string).collect())
    }
}

/// `difflib.SequenceMatcher(a, b, autojunk=False)`: the parts of `a` that a `get_opcodes` calls "delete" or "replace".
pub struct TokenDiff;

impl TokenDiff {
    /// The longest matching block in the ranges, the first of those of one length: (start in a, start in b, its length).
    fn longest(a: &[String], b: &[String], range_a: (usize, usize), range_b: (usize, usize)) -> (usize, usize, usize) {
        let (mut best_a, mut best_b, mut best) = (range_a.0, range_b.0, 0);
        let mut lengths = vec![0usize; b.len() + 1];
        for (at, token) in a.iter().enumerate().take(range_a.1).skip(range_a.0) {
            let mut next = vec![0usize; b.len() + 1];
            for (place, other) in b.iter().enumerate().take(range_b.1).skip(range_b.0) {
                if token == other {
                    // absent-ok: a place not counted yet has no letters.
                    let length = lengths.get(place).copied().unwrap_or_default() + 1;
                    if let Some(slot) = next.get_mut(place + 1) {
                        *slot = length;
                    }
                    if length > best {
                        (best_a, best_b, best) = (at + 1 - length, place + 1 - length, length);
                    }
                }
            }
            lengths = next;
        }
        (best_a, best_b, best)
    }

    fn blocks(a: &[String], b: &[String]) -> Vec<(usize, usize, usize)> {
        let mut queue = vec![((0, a.len()), (0, b.len()))];
        let mut found = Vec::new();
        while let Some((range_a, range_b)) = queue.pop() {
            let (at_a, at_b, length) = Self::longest(a, b, range_a, range_b);
            if length == 0 {
                continue;
            }
            found.push((at_a, at_b, length));
            if range_a.0 < at_a && range_b.0 < at_b {
                queue.push(((range_a.0, at_a), (range_b.0, at_b)));
            }
            if at_a + length < range_a.1 && at_b + length < range_b.1 {
                queue.push(((at_a + length, range_a.1), (at_b + length, range_b.1)));
            }
        }
        found.sort_unstable();
        found
    }

    /// The indexes of `a` that are gone or replaced in `b`.
    pub fn lost(a: &[String], b: &[String]) -> Vec<usize> {
        let mut out = Vec::new();
        let mut from = 0;
        for (at_a, _, length) in Self::blocks(a, b) {
            out.extend(from..at_a);
            from = at_a + length;
        }
        out.extend(from..a.len());
        out
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn words(text: &str) -> Vec<String> {
        text.split_whitespace().map(str::to_string).collect()
    }

    #[test]
    fn a_line_splits_as_a_shell_reads_it() {
        assert_eq!(ShellSplit::split("a 'b c' \"d \\\" \\x\" e\\ f").unwrap(), ["a", "b c", "d \" \\x", "e f"]);
        assert_eq!(ShellSplit::split("''").unwrap(), [""]);
        assert_eq!(ShellSplit::split("a'b'c").unwrap(), ["abc"]);
        assert!(ShellSplit::split("'open").is_err());
        assert!(ShellSplit::split("end\\").is_err());
        assert_eq!(ShellSplit::words("'open a"), ["'open", "a"]);
    }

    #[test]
    fn what_is_lost_is_what_is_not_matched() {
        assert_eq!(TokenDiff::lost(&words("a b c d"), &words("a c d")), [1]);
        assert_eq!(TokenDiff::lost(&words("a b c"), &words("a x c")), [1]);
        assert_eq!(TokenDiff::lost(&words("a b"), &words("a b")), Vec::<usize>::new());
        assert_eq!(TokenDiff::lost(&words("--x 1 --y 1"), &words("--x 1")), [2, 3]);
    }
}
