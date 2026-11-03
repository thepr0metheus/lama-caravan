//! The one name every client goes to the providers under, when the operator has set one.
//!
//! Unset, a provider hears each client as the client named itself. A name changes what names a client and nothing more: a session header names
//! no one and stays.

use serde_json::Value;

/// The name in the proxy's policy.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct ClientName {
    value: String,
}

impl ClientName {
    const LONGEST: usize = 120;
    /// The headers that name a client to a provider, in lower case.
    const NAMING: [&'static str; 4] = ["user-agent", "http-referer", "x-title", "x-openrouter-title"];

    /// The name in `policy`. A value that is no text, too long, or that holds what is not printable ASCII names no one: nothing but this one
    /// header may go out with it.
    pub fn read(policy: Option<&Value>) -> Self {
        let said = policy.and_then(|policy| policy.get("clientName")).and_then(Value::as_str).map(crate::coerce::Coerce::strip);
        let fit =
            said.filter(|name| name.chars().count() <= Self::LONGEST && name.chars().all(|letter| (' '..='~').contains(&letter)));
        Self { value: fit.map_or_else(String::new, str::to_string) }
    }

    /// `fields` as they go out: as they are with no name; with one, under it and under no other.
    pub fn say(&self, fields: &mut Vec<(String, Vec<u8>)>) {
        if !self.value.is_empty() {
            fields.retain(|(name, _)| !Self::NAMING.iter().any(|naming| name.eq_ignore_ascii_case(naming)));
            fields.push(("User-Agent".to_string(), self.value.clone().into_bytes()));
        }
    }

    /// `name` as it goes out when it is set, `None` when no name is set.
    pub fn word(&self) -> Option<&str> {
        (!self.value.is_empty()).then_some(self.value.as_str())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn said(fields: &[(&str, &str)], policy: Value) -> Vec<(String, String)> {
        let mut out: Vec<(String, Vec<u8>)> =
            fields.iter().map(|(name, value)| ((*name).to_string(), value.as_bytes().to_vec())).collect();
        ClientName::read(Some(&policy)).say(&mut out);
        out.into_iter().map(|(name, value)| (name, String::from_utf8(value).unwrap())).collect()
    }

    #[test]
    fn it_says_the_name_set_and_none_when_none_is() {
        assert_eq!(ClientName::read(Some(&json!({"clientName": " pi "}))).word(), Some("pi"));
        assert_eq!(ClientName::read(Some(&json!({}))).word(), None);
    }

    #[test]
    fn a_name_set_replaces_every_field_that_names_a_client_and_nothing_else() {
        let got = said(
            &[("USER-AGENT", "x"), ("X-Title", "t"), ("HTTP-Referer", "r"), ("x-openrouter-title", "o"), ("session-id", "s")],
            json!({"clientName": " pi (linux; x64) "}),
        );
        assert_eq!(got, [("session-id".to_string(), "s".to_string()), ("User-Agent".to_string(), "pi (linux; x64)".to_string())]);
    }

    #[test]
    fn no_name_or_one_that_cannot_be_one_leaves_the_fields_as_they_came() {
        let fields = [("user-agent", "own")];
        let same = vec![("user-agent".to_string(), "own".to_string())];
        for policy in [
            json!({}),
            json!({"clientName": ""}),
            json!({"clientName": "  "}),
            json!({"clientName": 5}),
            json!({"clientName": "имя"}),
            json!({"clientName": "a\nb"}),
            json!({"clientName": "x".repeat(121)}),
        ] {
            assert_eq!(said(&fields, policy.clone()), same, "{policy}");
        }
        assert_eq!(said(&fields, json!({"clientName": "x".repeat(120)})).len(), 1);
        assert_eq!(ClientName::read(None).word(), None);
    }
}
