//! llama-server's and vLLM's own counters.

use crate::app::App;
use serde_json::{Map, Value, json};
use std::time::Duration;

/// The counters of the servers on this host.
pub struct ServerMetrics<'app> {
    app: &'app App,
}

impl<'app> ServerMetrics<'app> {
    const WANTED: [&'static str; 9] = [
        "llamacpp:requests_processing",
        "llamacpp:requests_deferred",
        "llamacpp:prompt_tokens_seconds",
        "llamacpp:predicted_tokens_seconds",
        "llamacpp:kv_cache_usage_ratio",
        "llamacpp:prompt_tokens_total",
        "llamacpp:prompt_seconds_total",
        "llamacpp:tokens_predicted_total",
        "llamacpp:tokens_predicted_seconds_total",
    ];

    /// The counters of `app`.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    /// The counters a `/metrics` text says.
    pub fn parse(text: &str) -> Map<String, Value> {
        let mut metrics = Map::new();
        for line in text.lines() {
            if line.starts_with('#') || !line.contains(' ') {
                continue;
            }
            let mut words = line.split_whitespace();
            let (Some(key), Some(value)) = (words.next(), words.next()) else {
                continue;
            };
            if !Self::WANTED.contains(&key) {
                continue;
            }
            let said = value.parse::<f64>().map_or_else(|_| json!(value), |number| json!(number));
            metrics.insert(key.to_string(), said);
        }
        metrics
    }

    fn fetch(&self, port: &str) -> Result<String, String> {
        let url = format!("http://127.0.0.1:{port}/metrics");
        let answer =
            self.app.http.ask("GET", &url, &[], &[], Duration::from_secs(3)).map_err(|error| format!("ERROR: {error}"))?;
        let raw = answer.text(16 << 20).map_err(|error| format!("ERROR: {error}"))?;
        Ok(String::from_utf8_lossy(&raw).into_owned())
    }

    /// The sample of a llama-server on this host.
    pub fn runtime(&self, port: &str) -> Value {
        let text = match self.fetch(port) {
            Ok(text) => text,
            Err(words) => return json!({"ok": false, "error": words}),
        };
        let metrics = Self::parse(&text);
        if !metrics.contains_key("llamacpp:prompt_tokens_seconds") && !metrics.contains_key("llamacpp:predicted_tokens_seconds") {
            return json!({"ok": false, "error": "metrics unavailable"});
        }
        let at = |key: &str| metrics.get(key).cloned().unwrap_or_else(|| json!(0));
        json!({
            "ok": true,
            "promptTokensPerSecond": at("llamacpp:prompt_tokens_seconds"),
            "predictedTokensPerSecond": at("llamacpp:predicted_tokens_seconds"),
            "requestsProcessing": at("llamacpp:requests_processing"),
            "requestsDeferred": at("llamacpp:requests_deferred"),
            "kvCacheUsageRatio": at("llamacpp:kv_cache_usage_ratio"),
            "promptTokensTotal": at("llamacpp:prompt_tokens_total"),
            "promptSecondsTotal": at("llamacpp:prompt_seconds_total"),
            "predictedTokensTotal": at("llamacpp:tokens_predicted_total"),
            "predictedSecondsTotal": at("llamacpp:tokens_predicted_seconds_total"),
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn only_the_wanted_counters_are_read() {
        let metrics =
            ServerMetrics::parse("# comment\nllamacpp:requests_processing 2\nother 5\nllamacpp:requests_deferred x y\nbad");
        assert_eq!(Value::Object(metrics), json!({"llamacpp:requests_processing": 2.0, "llamacpp:requests_deferred": "x"}));
    }
}
