//! The reasoning effort a provider's model takes, learned from its refusal.
//!
//! A client names its effort in OpenAI's words, and a provider takes only the words its model takes: Hermes asks "none", and the subscription's
//! gpt-6.1-sol refused it five times a day, listing what it takes. So the request is asked again, once, with the nearest effort of that list,
//! and the list is kept for the model. Kept in memory: a list kept on disk would outlive a provider that has begun to take the word.

use crate::chat_levers::ChatLevers;
use serde_json::{Value, json};
use std::collections::BTreeMap;
use std::sync::{Mutex, PoisonError};

/// An effort sent in place of the one asked.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EffortSwap {
    /// What the client asked.
    pub asked: String,
    /// What went.
    pub sent: String,
}

impl EffortSwap {
    /// The words of a record.
    pub fn as_json(&self) -> Value {
        json!({"asked": self.asked, "sent": self.sent})
    }
}

/// What a refusal taught: the words of the journal's `effort_retry`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EffortLesson {
    /// The model.
    pub model: String,
    /// The effort refused.
    pub asked: String,
    /// The effort to send.
    pub sent: String,
    /// All it takes.
    pub takes: Vec<&'static str>,
}

/// The efforts each model of a provider takes, by (provider host, model).
#[derive(Debug, Default)]
pub struct EffortFit {
    takes: Mutex<BTreeMap<(String, String), Vec<&'static str>>>,
}

impl EffortFit {
    /// The fields an effort's refusal names: the Responses API's and Chat Completions'.
    const PARAMS: [&'static str; 2] = ["reasoning.effort", "reasoning_effort"];
    const LISTED: &'static str = "Supported values are:";

    /// The efforts a refusal lists as those its model takes: a 400 whose error names the effort's field and lists the values.
    pub fn offered(status: u16, error_body: &str) -> Vec<&'static str> {
        if status != 400 {
            return Vec::new();
        }
        let Ok(document) = serde_json::from_str::<Value>(error_body) else {
            return Vec::new();
        };
        let error = document.get("error").filter(|error| error.is_object());
        let names_it =
            error.and_then(|error| error.get("param")).and_then(Value::as_str).is_some_and(|param| Self::PARAMS.contains(&param));
        let message = error.and_then(|error| error.get("message")).and_then(Value::as_str);
        let (true, Some(message)) = (names_it, message) else {
            return Vec::new();
        };
        let Some((_, listed)) = message.split_once(Self::LISTED) else {
            return Vec::new();
        };
        ChatLevers::efforts_among(&Self::quoted_words(listed))
    }

    /// The words in single quotes: letters, `_` and `-`, as `'([A-Za-z_-]+)'` finds them from left to right.
    fn quoted_words(text: &str) -> Vec<&str> {
        let mut words = Vec::new();
        let mut rest = text;
        while let Some((_, after)) = rest.split_once('\'') {
            let Some((word, tail)) = after.split_once('\'') else {
                break;
            };
            if !word.is_empty() && word.chars().all(|letter| letter.is_ascii_alphabetic() || matches!(letter, '_' | '-')) {
                words.push(word);
                rest = tail;
            } else {
                rest = after;
            }
        }
        words
    }

    /// (document, model, effort) of a JSON body bound for a provider, its effort as the Responses API says it or as Chat Completions does.
    fn said(body: &[u8]) -> Option<(Value, String, String)> {
        let document = crate::request_json::RequestJson::read(body)?;
        document.as_object()?;
        let reasoning = document.get("reasoning").filter(|reasoning| reasoning.is_object());
        let effort = match reasoning {
            Some(reasoning) => reasoning.get("effort"),
            None => document.get("reasoning_effort"),
        };
        let effort = effort?.as_str().filter(|effort| !effort.is_empty())?.to_string();
        let model = crate::coerce::Coerce::text(document.get("model"));
        Some((document, model, effort))
    }

    fn sent_with(mut document: Value, effort: &str) -> Vec<u8> {
        if let Some(fields) = document.get_mut("reasoning").and_then(Value::as_object_mut) {
            fields.insert("effort".to_string(), json!(effort));
        } else if let Some(fields) = document.as_object_mut() {
            fields.insert("reasoning_effort".to_string(), json!(effort));
        }
        document.to_string().into_bytes()
    }

    /// The body with the effort its model takes when a refusal has listed them and the asked one is not among them, with what was swapped;
    /// `None`: it goes as it is.
    pub fn fit(&self, host: &str, body: &[u8]) -> Option<(Vec<u8>, EffortSwap)> {
        let (document, model, asked) = Self::said(body)?;
        let takes = self.takes.lock().unwrap_or_else(PoisonError::into_inner).get(&(host.to_string(), model))?.clone();
        if takes.contains(&asked.as_str()) {
            return None;
        }
        let sent = ChatLevers::nearest_effort(&asked, &takes)?;
        Some((Self::sent_with(document, sent), EffortSwap { asked, sent: sent.to_string() }))
    }

    /// What the provider's refusal of `body` taught, when it listed the efforts its model takes and the body's effort has a nearest one among
    /// them: the list is kept, and `fit` sends that one from now on. `None`: a refusal of something else, an effort the scale does not know,
    /// or a list that takes the very effort refused.
    pub fn learn(&self, host: &str, body: &[u8], status: u16, error_body: &str) -> Option<EffortLesson> {
        let takes = Self::offered(status, error_body);
        if takes.is_empty() {
            return None;
        }
        let (_, model, asked) = Self::said(body)?;
        let sent = ChatLevers::nearest_effort(&asked, &takes)?;
        if takes.contains(&asked.as_str()) {
            return None;
        }
        self.takes.lock().unwrap_or_else(PoisonError::into_inner).insert((host.to_string(), model.clone()), takes.clone());
        Some(EffortLesson { model, asked, sent: sent.to_string(), takes })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn offered(message: &str) -> Vec<&'static str> {
        EffortFit::offered(400, &json!({"error": {"param": "reasoning.effort", "message": message}}).to_string())
    }

    #[test]
    fn only_a_word_in_quotes_is_an_effort_said() {
        assert_eq!(offered("Supported values are: 'low', 'medium', and 'high'."), ["low", "medium", "high"]);
        assert_eq!(
            offered("Supported values are: the model's own 'low' and 'high'."),
            ["low", "high"],
            "an apostrophe opens no word"
        );
    }
}
