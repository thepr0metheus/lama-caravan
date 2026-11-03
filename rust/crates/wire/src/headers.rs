//! A message's header fields, as they came: in their order, under their own spelling.

/// One header field. The value stays bytes, because a value is relayed as it came.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Field {
    /// The name, spelled as the sender spelled it.
    pub name: String,
    /// The value, without the spaces around it.
    pub value: Vec<u8>,
}

/// The fields of a message. A name given twice stays twice: `get` reads the first, as Python's
/// `email.message.Message.get` does, and `all` reads every one.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Headers {
    fields: Vec<Field>,
}

impl Headers {
    /// No fields yet.
    pub fn new() -> Self {
        Self::default()
    }

    /// Adds a field after the others.
    pub fn push(&mut self, name: impl Into<String>, value: impl Into<Vec<u8>>) {
        self.fields.push(Field { name: name.into(), value: value.into() });
    }

    /// The first value of `name` as text, or `None` when the message does not carry it. An empty
    /// value is `Some("")`: said empty and not said are two answers.
    pub fn get(&self, name: &str) -> Option<String> {
        self.fields.iter().find(|field| field.name.eq_ignore_ascii_case(name)).map(|field| Self::text(&field.value))
    }

    /// The first value of `name` as text, "" when the message does not carry it: for what is read as Python's
    /// `str(headers.get(name) or "")`, where said empty and not said mean the same. `get` is for where they do not.
    pub fn text_of(&self, name: &str) -> String {
        // absent-ok: this method is the place that says a field not sent reads as an empty one.
        self.get(name).unwrap_or_default()
    }

    /// Every value of `name` as text, in their order.
    pub fn all(&self, name: &str) -> Vec<String> {
        self.fields.iter().filter(|field| field.name.eq_ignore_ascii_case(name)).map(|field| Self::text(&field.value)).collect()
    }

    /// Whether the message carries `name`.
    pub fn has(&self, name: &str) -> bool {
        self.fields.iter().any(|field| field.name.eq_ignore_ascii_case(name))
    }

    /// The fields in their order.
    pub fn iter(&self) -> std::slice::Iter<'_, Field> {
        self.fields.iter()
    }

    /// A value's bytes as latin-1 text. HTTP says nothing of a value's encoding, and this is how
    /// Python's `http.client` reads it, so one key reads the same on both sides.
    fn text(value: &[u8]) -> String {
        value.iter().map(|byte| char::from(*byte)).collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn fields() -> Headers {
        let mut headers = Headers::new();
        headers.push("X-One", "1");
        headers.push("x-one", "2");
        headers.push("X-Empty", "");
        headers.push("X-Bytes", vec![0xE9]);
        headers
    }

    #[test]
    fn a_name_is_found_without_case_and_a_name_given_twice_stays_twice() {
        let headers = fields();
        assert_eq!(headers.get("X-ONE").as_deref(), Some("1"));
        assert_eq!(headers.all("x-One"), vec!["1", "2"]);
        assert!(headers.has("x-empty"));
        assert!(!headers.has("X-None"));
    }

    #[test]
    fn said_empty_and_not_said_are_two_answers_where_it_matters() {
        let headers = fields();
        assert_eq!(headers.get("X-Empty").as_deref(), Some(""));
        assert_eq!(headers.get("X-None"), None);
        assert_eq!(headers.text_of("X-Empty"), "");
        assert_eq!(headers.text_of("X-None"), "");
        assert_eq!(headers.text_of("X-One"), "1");
    }

    #[test]
    fn a_value_reads_as_latin_1() {
        assert_eq!(fields().text_of("X-Bytes"), "é");
    }
}
