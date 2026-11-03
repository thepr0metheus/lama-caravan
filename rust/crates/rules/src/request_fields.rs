//! What a client's POST asks for when it comes as a form, held to
//! one table of forms with the cells' own reader (`contract/multipart.json`, written from `scripts/_multipart_cases.py`).

use crate::request_json::RequestJson;
use serde_json::Value;
use std::collections::BTreeMap;

/// One part of a form: its name, whether it is a file, and where its data stands.
struct Part {
    name: Option<String>,
    is_file: bool,
    start: usize,
    end: usize,
}

/// A form's text fields, read without a parser that walks the file: the ears send a growing recording twice a second, and the boundary
/// is found by a search, a part's head is read to its blank line, and a part with a filename is stepped over, never copied.
pub struct RequestFields;

impl RequestFields {
    const FORM: &'static str = "multipart/form-data";
    /// The most of a form's text field that is kept: a "field" this long is a file without its filename.
    const FIELD_MAX: usize = 65_536;
    const CRLF: &'static [u8] = b"\r\n";

    /// Whether the type says a form.
    pub fn is_form(content_type: &str) -> bool {
        content_type.split(';').next().is_some_and(|plain| plain.trim().eq_ignore_ascii_case(Self::FORM))
    }

    /// The form's boundary from its type, quoted or bare; "" when it names none.
    fn boundary(content_type: &str) -> String {
        for param in content_type.split(';').skip(1) {
            let (name, value) = param.trim().split_once('=').unwrap_or((param.trim(), ""));
            if name.trim().eq_ignore_ascii_case("boundary") {
                return Self::unquoted(value.trim()).to_string();
            }
        }
        String::new()
    }

    fn unquoted(value: &str) -> &str {
        match value.strip_prefix('"').and_then(|rest| rest.strip_suffix('"')) {
            Some(inner) => inner,
            None => value,
        }
    }

    /// `body.find(needle, from)`.
    fn find(body: &[u8], needle: &[u8], from: usize) -> Option<usize> {
        let rest = body.get(from..)?;
        rest.windows(needle.len()).position(|piece| piece == needle).map(|at| at + from)
    }

    fn holds_at(body: &[u8], at: usize, what: &[u8]) -> bool {
        body.get(at..at + what.len()) == Some(what)
    }

    /// Where the line that stands at `at` ends: spaces and tabs may pad it (RFC 2046's transport padding), then a CRLF.
    fn line_end(body: &[u8], at: usize) -> Option<usize> {
        let mut at = at;
        while matches!(body.get(at), Some(b' ' | b'\t')) {
            at += 1;
        }
        Self::holds_at(body, at, Self::CRLF).then_some(at + 2)
    }

    /// Where the next delimiter's CRLF stands at or after `start`. The boundary's letters inside a part's data are not a delimiter unless
    /// `--` or a line's end follows them.
    fn delimiter(body: &[u8], mark: &[u8], start: usize) -> Option<usize> {
        let mut needle = Self::CRLF.to_vec();
        needle.extend_from_slice(mark);
        let mut from = start;
        loop {
            let at = Self::find(body, &needle, from)?;
            let after = at + needle.len();
            if Self::holds_at(body, after, b"--") || Self::line_end(body, after).is_some() {
                return Some(at);
            }
            from = at + 1;
        }
    }

    /// (name, has a filename) of a part, from its head's `Content-Disposition`.
    fn disposition(head: &[u8]) -> (Option<String>, bool) {
        for line in String::from_utf8_lossy(head).split("\r\n") {
            let (key, value) = line.split_once(':').unwrap_or((line, ""));
            if !key.trim().eq_ignore_ascii_case("content-disposition") {
                continue;
            }
            let (mut name, mut filename) = (None, false);
            for param in value.split(';').skip(1) {
                let (key, raw) = param.trim().split_once('=').unwrap_or((param.trim(), ""));
                let raw = Self::unquoted(raw.trim());
                match key.trim().to_lowercase().as_str() {
                    "name" => name = Some(raw.to_string()),
                    "filename" | "filename*" => filename = true,
                    _ => {}
                }
            }
            return (name, filename);
        }
        (None, false)
    }

    /// The delimiter's letters: `--` and the boundary, in Latin-1, with a mark for a letter past it.
    fn mark(boundary: &str) -> Vec<u8> {
        let mut mark = b"--".to_vec();
        // absent-ok: a letter Latin-1 has not is a question mark in the cells' reader too.
        mark.extend(boundary.chars().map(|letter| u8::try_from(u32::from(letter)).unwrap_or(b'?')));
        mark
    }

    /// The form's parts in order and where its closing delimiter stands; `None` for a form that does not read as one: no boundary, no
    /// part, a part with no head or no end.
    fn parts(content_type: &str, body: &[u8]) -> Option<(Vec<Part>, usize)> {
        let boundary = Self::boundary(content_type);
        if boundary.is_empty() {
            return None;
        }
        let mark = Self::mark(&boundary);
        let mut at = Self::find(body, &mark, 0)?;
        let mut parts = Vec::new();
        loop {
            at += mark.len();
            if Self::holds_at(body, at, b"--") {
                let closing = at - mark.len();
                return (!parts.is_empty()).then_some((parts, closing));
            }
            let head_at = Self::line_end(body, at)?;
            if Self::holds_at(body, head_at, Self::CRLF) {
                return None;
            }
            let head_end = Self::find(body, b"\r\n\r\n", head_at)?;
            let (name, is_file) = Self::disposition(body.get(head_at..head_end)?);
            let next = Self::delimiter(body, &mark, head_end + 4)?;
            parts.push(Part { name, is_file, start: head_end + 4, end: next });
            at = next + 2;
        }
    }

    /// A form's text fields by name, the first of a name sent twice; `None` for a form that does not read as one.
    pub fn form(content_type: &str, body: &[u8]) -> Option<BTreeMap<String, String>> {
        let mut fields = BTreeMap::new();
        for part in Self::parts(content_type, body)?.0 {
            let Some(name) = part.name.filter(|name| !name.is_empty()) else {
                continue;
            };
            if !part.is_file && part.end - part.start <= Self::FIELD_MAX {
                let data = body.get(part.start..part.end)?;
                fields.entry(name).or_insert_with(|| String::from_utf8_lossy(data).into_owned());
            }
        }
        Some(fields)
    }

    /// The part `form` reads as the text field `name`.
    fn is_value(part: &Part, name: &str) -> bool {
        part.name.as_deref() == Some(name) && !part.is_file && part.end - part.start <= Self::FIELD_MAX
    }

    /// The form with its text field `name` saying `value`: in place, or in a part of its own before the closing delimiter. A file's bytes
    /// are not touched, and the rest of the form stays byte for byte. A form that cannot be read is not this process's to write.
    pub fn with_field(content_type: &str, body: Vec<u8>, name: &str, value: &str) -> Vec<u8> {
        let Some((parts, closing)) = Self::parts(content_type, &body) else {
            return body;
        };
        let data = value.as_bytes();
        let (start, end, inserted) = match parts.iter().find(|part| Self::is_value(part, name)) {
            Some(part) => (part.start, part.end, data.to_vec()),
            None => {
                let mut added = Self::mark(&Self::boundary(content_type));
                added.extend_from_slice(b"\r\nContent-Disposition: form-data; name=\"");
                added.extend_from_slice(name.as_bytes());
                added.extend_from_slice(b"\"\r\n\r\n");
                added.extend_from_slice(data);
                added.extend_from_slice(Self::CRLF);
                (closing, closing, added)
            }
        };
        let mut out = body;
        out.splice(start..end, inserted);
        out
    }

    /// The request with the model the caravan chose in it. A form says it in its text field;
    /// a JSON object gets it in place or added, unless it says so already; any other body goes as it came, the same bytes.
    pub fn model_named(body: Vec<u8>, model: &str, content_type: &str) -> Vec<u8> {
        if body.is_empty() || model.is_empty() {
            return body;
        }
        if Self::is_form(content_type) {
            return Self::with_field(content_type, body, "model", model);
        }
        let Some(Value::Object(mut payload)) = RequestJson::read(&body) else {
            return body;
        };
        if payload.get("model").and_then(Value::as_str) == Some(model) {
            return body;
        }
        payload.insert("model".to_string(), Value::String(model.to_string()));
        Value::Object(payload).to_string().into_bytes()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const TYPE: &str = "multipart/form-data; boundary=x";

    fn field(name: &str, value: &[u8]) -> Vec<u8> {
        let mut part = format!("--x\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n").into_bytes();
        part.extend_from_slice(value);
        part.extend_from_slice(b"\r\n");
        part
    }

    fn file(size: usize) -> Vec<u8> {
        let mut part = b"--x\r\nContent-Disposition: form-data; name=\"file\"; filename=\"a\"\r\n\r\n".to_vec();
        part.resize(part.len() + size, b'a');
        part.extend_from_slice(b"\r\n");
        part
    }

    fn closed(parts: &[Vec<u8>]) -> Vec<u8> {
        let mut body = parts.concat();
        body.extend_from_slice(b"--x--\r\n");
        body
    }

    #[test]
    fn a_field_is_kept_up_to_its_limit_and_wherever_it_stands() {
        let limit = RequestFields::FIELD_MAX;
        let at_limit = closed(&[field("a", &vec![b'v'; limit])]);
        assert_eq!(RequestFields::form(TYPE, &at_limit).unwrap().get("a").map(String::len), Some(limit));
        let past_limit = closed(&[field("a", &vec![b'v'; limit + 1])]);
        assert_eq!(
            RequestFields::form(TYPE, &past_limit).unwrap().get("a"),
            None,
            "a field this long is a file without its filename"
        );
        let after_a_file = closed(&[file(limit * 2), field("a", b"v")]);
        assert_eq!(RequestFields::form(TYPE, &after_a_file).unwrap().get("a").map(String::as_str), Some("v"));
        assert_eq!(RequestFields::form(TYPE, &after_a_file).unwrap().get("file"), None);
    }

    #[test]
    fn a_part_s_data_starts_after_its_head_whatever_the_head_holds() {
        let body = b"--x\r\nContent-Disposition: form-data; name=\"a\"\r\n--x\r\n\r\nvalue\r\n--x--\r\n";
        assert_eq!(RequestFields::form(TYPE, body).unwrap().get("a").map(String::as_str), Some("value"));
    }

    #[test]
    fn a_part_s_data_is_looked_at_only_from_its_own_start() {
        let body = b"--x\r\nContent-Disposition: form-data; name=\"a\"\r\n\r\n--x--\r\n--x--\r\n";
        assert_eq!(RequestFields::form(TYPE, body).unwrap().get("a").map(String::as_str), Some("--x--"));
    }

    #[test]
    fn a_field_is_rewritten_where_the_reader_finds_it_and_added_where_it_does_not() {
        let limit = RequestFields::FIELD_MAX;
        let after_a_file = closed(&[file(limit * 2), field("model", b"old")]);
        let renamed = RequestFields::with_field(TYPE, after_a_file, "model", "new");
        assert_eq!(RequestFields::form(TYPE, &renamed).unwrap().get("model").map(String::as_str), Some("new"));
        let too_long = closed(&[field("model", &vec![b'v'; limit + 1])]);
        let renamed = RequestFields::with_field(TYPE, too_long.clone(), "model", "new");
        assert_eq!(
            renamed.len(),
            too_long.len() + "--x\r\nContent-Disposition: form-data; name=\"model\"\r\n\r\nnew\r\n".len(),
            "a part of its own"
        );
        let at_limit = closed(&[field("model", &vec![b'v'; limit])]);
        let renamed = RequestFields::with_field(TYPE, at_limit, "model", "new");
        assert_eq!(RequestFields::form(TYPE, &renamed).unwrap().get("model").map(String::as_str), Some("new"));
    }

    #[test]
    fn a_lone_quote_is_no_quoted_boundary() {
        assert_eq!(RequestFields::boundary("multipart/form-data; boundary=\""), "\"");
        assert_eq!(RequestFields::boundary("multipart/form-data; boundary=\"x\""), "x");
        assert_eq!(RequestFields::boundary("multipart/form-data; boundary=\"\""), "");
    }

    #[test]
    fn a_form_is_told_by_its_type() {
        for form in ["multipart/form-data", "MULTIPART/FORM-DATA; boundary=x", " multipart/form-data ;x"] {
            assert!(RequestFields::is_form(form), "{form}");
        }
        for other in ["application/json", "", "multipart/mixed", "text/multipart/form-data"] {
            assert!(!RequestFields::is_form(other), "{other}");
        }
    }
}
