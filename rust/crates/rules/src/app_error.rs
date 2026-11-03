//! A failure the HTTP surface answers with its own status and words: `AppError`, the one kind of refusal both the scout and the controller say.

use std::fmt;

/// One failure a request is told.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AppError {
    /// The words of `{"error": ...}`.
    pub message: String,
    /// The status it goes with.
    pub status: u16,
}

impl AppError {
    /// A request's own fault: 400.
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into(), status: 400 }
    }

    /// A failure with a status of its own.
    pub fn with_status(message: impl Into<String>, status: u16) -> Self {
        Self { message: message.into(), status }
    }
}

impl fmt::Display for AppError {
    fn fmt(&self, out: &mut fmt::Formatter<'_>) -> fmt::Result {
        out.write_str(&self.message)
    }
}

/// A text as Python's `repr` writes it, for the words that quote what they were told.
pub struct PyRepr;

impl PyRepr {
    /// `repr` of a JSON value as Python holds it: `True`, `None`, `'word'`, `[1, 2]`.
    pub fn of_value(value: &serde_json::Value) -> String {
        use serde_json::Value;
        match value {
            Value::Null => "None".to_string(),
            Value::Bool(flag) => if *flag { "True" } else { "False" }.to_string(),
            Value::Number(number) => number.to_string(),
            Value::String(text) => Self::of(text),
            Value::Array(items) => format!("[{}]", items.iter().map(Self::of_value).collect::<Vec<_>>().join(", ")),
            Value::Object(fields) => format!(
                "{{{}}}",
                fields
                    .iter()
                    .map(|(key, item)| format!("{}: {}", Self::of(key), Self::of_value(item)))
                    .collect::<Vec<_>>()
                    .join(", ")
            ),
        }
    }

    /// `'text'`, in double quotes when it holds a single quote and no double one.
    pub fn of(text: &str) -> String {
        let quote = if text.contains('\'') && !text.contains('"') { '"' } else { '\'' };
        let mut out = String::with_capacity(text.len() + 2);
        out.push(quote);
        for letter in text.chars() {
            match letter {
                '\\' => out.push_str("\\\\"),
                '\n' => out.push_str("\\n"),
                '\r' => out.push_str("\\r"),
                '\t' => out.push_str("\\t"),
                _ if letter == quote => {
                    out.push('\\');
                    out.push(letter);
                }
                _ if letter.is_control() => out.push_str(&format!("\\x{:02x}", u32::from(letter))),
                _ => out.push(letter),
            }
        }
        out.push(quote);
        out
    }
}

/// A word for the shell, as `shlex.quote` writes it.
pub struct ShellWord;

impl ShellWord {
    /// Quoted, unless every letter of it is safe.
    pub fn quote(word: &str) -> String {
        let safe = |letter: char| {
            letter.is_ascii_alphanumeric() || matches!(letter, '_' | '@' | '%' | '+' | '=' | ':' | ',' | '.' | '/' | '-')
        };
        if !word.is_empty() && word.chars().all(safe) {
            return word.to_string();
        }
        format!("'{}'", word.replace('\'', "'\"'\"'"))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_word_is_quoted_only_when_it_has_to_be() {
        assert_eq!(ShellWord::quote("--ctx-size=4096"), "--ctx-size=4096");
        assert_eq!(ShellWord::quote(""), "''");
        assert_eq!(ShellWord::quote("a b"), "'a b'");
        assert_eq!(ShellWord::quote("it's"), "'it'\"'\"'s'");
    }

    #[test]
    fn repr_takes_the_quote_python_takes() {
        assert_eq!(PyRepr::of("plain"), "'plain'");
        assert_eq!(PyRepr::of("it's"), "\"it's\"");
        assert_eq!(PyRepr::of("both ' and \""), "'both \\' and \"'");
        assert_eq!(PyRepr::of("a\nb"), "'a\\nb'");
    }
}
