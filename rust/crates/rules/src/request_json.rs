//! A client's JSON, read as `json.loads` reads it.
//!
//! Python's reader takes two things strict JSON does not, and clients send one of them: half of a surrogate pair, from a text cut in the
//! middle of an emoji (JavaScript's `JSON.stringify` writes it as `"\ud83d"`). Refusing such a request would be a new refusal nobody had
//! before. `serde_json` refuses it, so what it refuses is mended and read again. What the mended text says is what this process reads,
//! never what goes to a machine's model: a body that needs no new `model` goes on as the client wrote it.

use serde_json::Value;

/// The reader.
pub struct RequestJson;

impl RequestJson {
    /// What the mark of a letter that cannot be said becomes. `json.loads` keeps the half; no later writer here could write it.
    const REPLACEMENT: &'static str = "\\ufffd";
    /// What Python reads as the floats it has no JSON for. Nothing a request says is decided by them, so they read as nothing.
    const NOT_NUMBERS: [&'static str; 3] = ["-Infinity", "Infinity", "NaN"];
    const NOTHING: &'static str = "null";

    /// The body's JSON; `None` for a body neither reader takes.
    pub fn read(body: &[u8]) -> Option<Value> {
        if let Ok(value) = serde_json::from_slice(body) {
            return Some(value);
        }
        let text = std::str::from_utf8(body).ok()?;
        serde_json::from_str(&Self::mended(text)).ok()
    }

    /// `text` with what only Python takes said so that `serde_json` takes it too. A letter inside a string stays where it stands.
    fn mended(text: &str) -> String {
        let mut out = String::with_capacity(text.len());
        let mut rest = text;
        let mut in_string = false;
        while let Some(letter) = rest.chars().next() {
            let taken = if in_string {
                Self::string_piece(rest, letter, &mut out, &mut in_string)
            } else {
                Self::outside_piece(rest, letter, &mut out, &mut in_string)
            };
            rest = rest.get(taken..).unwrap_or_default();
        }
        out
    }

    /// One piece outside a string: how many bytes of `rest` it took.
    fn outside_piece(rest: &str, letter: char, out: &mut String, in_string: &mut bool) -> usize {
        if let Some(word) = Self::NOT_NUMBERS.iter().find(|word| rest.starts_with(**word)) {
            out.push_str(Self::NOTHING);
            return word.len();
        }
        *in_string = letter == '"';
        out.push(letter);
        letter.len_utf8()
    }

    /// One piece inside a string.
    fn string_piece(rest: &str, letter: char, out: &mut String, in_string: &mut bool) -> usize {
        if letter == '"' {
            *in_string = false;
        }
        if letter != '\\' {
            out.push(letter);
            return letter.len_utf8();
        }
        let Some(unit) = Self::unit_at(rest) else {
            // An escape of another kind: its second letter is no end of the string, whatever it is.
            // absent-ok: a text that ends in a backslash has no second letter, and `serde_json` refuses it next.
            let second = rest.chars().nth(1).map_or(0, char::len_utf8);
            out.push_str(rest.get(..1 + second).unwrap_or_default());
            return 1 + second;
        };
        let high = (0xD800..=0xDBFF).contains(&unit);
        // absent-ok: `unit_at` read six bytes of plain ASCII, so the rest of the text begins on a letter's edge.
        let pair = high && Self::unit_at(rest.get(6..).unwrap_or_default()).is_some_and(|low| (0xDC00..=0xDFFF).contains(&low));
        if pair {
            out.push_str(rest.get(..12).unwrap_or_default());
            return 12;
        }
        if (0xD800..=0xDFFF).contains(&unit) {
            out.push_str(Self::REPLACEMENT);
        } else {
            out.push_str(rest.get(..6).unwrap_or_default());
        }
        6
    }

    /// The UTF-16 unit of a `\uXXXX` at the start of `text`.
    fn unit_at(text: &str) -> Option<u32> {
        let digits = text.strip_prefix("\\u")?.get(..4)?;
        if !digits.bytes().all(|digit| digit.is_ascii_hexdigit()) {
            return None;
        }
        u32::from_str_radix(digits, 16).ok()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn read(text: &str) -> Option<Value> {
        RequestJson::read(text.as_bytes())
    }

    #[test]
    fn what_strict_json_takes_is_read_as_it_is() {
        assert_eq!(read(r#"{"a": [1, "b"]}"#), Some(json!({"a": [1, "b"]})));
        assert_eq!(read(r#""😀""#), Some(json!("😀")));
    }

    #[test]
    fn half_of_a_pair_reads_as_a_mark_and_the_rest_stays() {
        assert_eq!(read(r#"{"m": "a\ud83d"}"#), Some(json!({"m": "a\u{fffd}"})));
        assert_eq!(read(r#"{"m": "\ude00b"}"#), Some(json!({"m": "\u{fffd}b"})));
        assert_eq!(read(r#"{"m": "\ud83d😀"}"#), Some(json!({"m": "\u{fffd}😀"})));
        assert_eq!(read(r#"{"m": "\ud83dя\n\"\\"}"#), Some(json!({"m": "\u{fffd}я\n\"\\"})));
        assert_eq!(read(r#"{"m": "\\ud83d", "n": "\ud83d"}"#), Some(json!({"m": "\\ud83d", "n": "\u{fffd}"})));
    }

    #[test]
    fn what_only_python_reads_as_a_number_reads_as_nothing_outside_a_string() {
        assert_eq!(read(r#"{"a": NaN, "b": Infinity, "c": -Infinity}"#), Some(json!({"a": null, "b": null, "c": null})));
        assert_eq!(read(r#"{"a": NaN, "b": "NaN Infinity"}"#), Some(json!({"a": null, "b": "NaN Infinity"})));
    }

    #[test]
    fn what_neither_reader_takes_is_nothing() {
        for text in ["", "{", "not json", r#"{"a": "b"#, r#"{"a": nan}"#, "{\"a\": \"\u{1}\"}", r#"{"a": "\x"}"#, r#""\ud83"#] {
            assert_eq!(read(text), None, "{text}");
        }
        assert_eq!(RequestJson::read(b"{\"a\": \"\xff\"}"), None, "letters that are no UTF-8");
    }
}
