//! A request to the machine's entry, read once: the model it names, `model` of a JSON body or the form field `model` of a multipart one (a recording), and the same request naming another model.

use rules::Coerce;
use serde_json::{Map, Value, json};

/// The request.
pub struct EntryRequest {
    body: Vec<u8>,
    payload: Option<Map<String, Value>>,
    span: Option<(usize, usize)>,
}

impl EntryRequest {
    /// The request of this body.
    pub fn new(body: Vec<u8>, content_type: &str) -> Self {
        let form = content_type.to_lowercase().starts_with("multipart/form-data");
        let span = if form { Self::field_span(&body, content_type) } else { None };
        let payload = if form { None } else { Self::json_object(&body) };
        Self { body, payload, span }
    }

    /// The body as a JSON object; any other body (no body, not JSON, a list): `None`.
    fn json_object(body: &[u8]) -> Option<Map<String, Value>> {
        serde_json::from_slice::<Value>(body).ok()?.as_object().cloned()
    }

    /// `boundary="?([^";]+)"?`, in any case.
    fn boundary(content_type: &str) -> Option<&str> {
        let at = content_type.to_lowercase().find("boundary=")?;
        let rest = content_type.get(at + "boundary=".len()..)?;
        let rest = rest.strip_prefix('"').unwrap_or(rest);
        let word = rest.split(['"', ';']).next()?;
        (!word.is_empty()).then_some(word)
    }

    fn find(haystack: &[u8], needle: &[u8], from: usize, to: usize) -> Option<usize> {
        let part = haystack.get(from..to)?;
        part.windows(needle.len()).position(|window| window == needle).map(|at| at + from)
    }

    /// The form field `model` by its own name: a file's `filename="model"` is not it. `(?<![\w-])name="model"(?=;|\s|$)`.
    fn names_the_field(head: &[u8]) -> bool {
        const NAME: &[u8] = b"name=\"model\"";
        let mut from = 0;
        while let Some(at) = Self::find(head, NAME, from, head.len()) {
            let before = at.checked_sub(1).and_then(|before| head.get(before));
            let after = head.get(at + NAME.len());
            let starts = before.is_none_or(|byte| !(byte.is_ascii_alphanumeric() || matches!(*byte, b'_' | b'-')));
            let ends = after.is_none_or(|byte| *byte == b';' || byte.is_ascii_whitespace());
            if starts && ends {
                return true;
            }
            from = at + 1;
        }
        false
    }

    /// Where the value of the form field `model` lies in the body; no such field: `None`.
    fn field_span(body: &[u8], content_type: &str) -> Option<(usize, usize)> {
        let boundary = Self::boundary(content_type)?;
        let delimiter: Vec<u8> = [b"--".as_slice(), boundary.as_bytes()].concat();
        let closing: Vec<u8> = [b"\r\n".as_slice(), &delimiter].concat();
        let mut at = Self::find(body, &delimiter, 0, body.len());
        while let Some(start) = at {
            let head = start + delimiter.len();
            let end = Self::find(body, &closing, head, body.len())?;
            if let Some(split) = Self::find(body, b"\r\n\r\n", head, end)
                && body.get(head..split).is_some_and(Self::names_the_field)
            {
                return Some((split + 4, end));
            }
            at = Some(end + 2);
        }
        None
    }

    /// The model it names, "" when none.
    pub fn model(&self) -> String {
        if let Some(payload) = &self.payload {
            return if Coerce::truthy(payload.get("model")) { Coerce::stripped(payload.get("model")) } else { String::new() };
        }
        let value = self.span.and_then(|(start, end)| self.body.get(start..end));
        value.map_or_else(String::new, |value| Coerce::strip(&String::from_utf8_lossy(value)).to_string())
    }

    /// The body as it came.
    pub fn body(&self) -> &[u8] {
        &self.body
    }

    /// The body with `model` set to `name`: the same bytes when it already says so, or names no model to change. A JSON body is written again (its other fields as they were), a form's field is replaced in place: a recording's bytes are not touched.
    pub fn naming(&self, name: &str) -> Vec<u8> {
        let said = self.model();
        if name.is_empty() || said.is_empty() || name == said {
            return self.body.clone();
        }
        if let Some(payload) = &self.payload {
            let mut fields = payload.clone();
            fields.insert("model".to_string(), json!(name));
            return rules::PythonJson::spaced(&Value::Object(fields)).into_bytes();
        }
        let Some((start, end)) = self.span else {
            return self.body.clone();
        };
        [self.body.get(..start).unwrap_or_default(), name.as_bytes(), self.body.get(end..).unwrap_or_default()].concat()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const FORM: &str = "multipart/form-data; boundary=\"XX\"";

    fn form(fields: &[(&str, &str)]) -> Vec<u8> {
        let mut out = Vec::new();
        for (head, value) in fields {
            out.extend(format!("--XX\r\nContent-Disposition: form-data; {head}\r\n\r\n{value}\r\n").into_bytes());
        }
        out.extend(b"--XX--\r\n");
        out
    }

    #[test]
    fn a_json_body_names_its_model() {
        let request = EntryRequest::new(br#"{"model": " m ", "a": 1}"#.to_vec(), "application/json");
        assert_eq!(request.model(), "m");
        assert_eq!(request.naming("other"), br#"{"model": "other", "a": 1}"#.to_vec());
        assert_eq!(EntryRequest::new(b"[1]".to_vec(), "").model(), "");
        assert_eq!(EntryRequest::new(br#"{"a": 1}"#.to_vec(), "").naming("x"), br#"{"a": 1}"#.to_vec());
    }

    #[test]
    fn a_forms_field_is_replaced_in_place() {
        let body = form(&[("name=\"file\"; filename=\"model\"", "RAW"), ("name=\"model\"", "whisper")]);
        let request = EntryRequest::new(body, FORM);
        assert_eq!(request.model(), "whisper");
        let renamed = request.naming("large");
        assert_eq!(EntryRequest::new(renamed.clone(), FORM).model(), "large");
        assert!(renamed.windows(3).any(|window| window == b"RAW"));
    }

    #[test]
    fn a_file_called_model_is_no_field() {
        let body = form(&[("name=\"file\"; filename=\"model\"", "RAW")]);
        assert_eq!(EntryRequest::new(body, FORM).model(), "");
        let other = form(&[("x-name=\"model\"", "RAW")]);
        assert_eq!(EntryRequest::new(other, FORM).model(), "");
        assert_eq!(EntryRequest::new(b"--XX".to_vec(), "multipart/form-data").model(), "");
    }
}
