//! Token-rate history, fed by the proxy's own records.

use crate::app::App;
use files::AtomicFile;
use plumbing::log::Log;
use rules::{Coerce, PythonJson};
use serde_json::{Value, json};
use std::collections::BTreeSet;
use std::sync::{Mutex, PoisonError};

/// The history in memory: read once, written whole.
#[derive(Default)]
pub struct TokenHistoryMemory {
    rows: Mutex<Option<Vec<Value>>>,
}

/// The history of this controller.
pub struct TokenHistory<'app> {
    app: &'app App,
}

impl<'app> TokenHistory<'app> {
    const RECENT: usize = 2000;
    const RANGES: [(&'static str, i64); 3] = [("1h", 3600), ("12h", 12 * 3600), ("24h", 24 * 3600)];

    /// The history of `app`.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    fn load(&self) -> Vec<Value> {
        let raw = std::fs::read(&self.app.paths.token_history_file).ok();
        let said = raw.and_then(|raw| serde_json::from_slice::<Value>(&raw).ok());
        // absent-ok: what is not a list is no samples.
        said.and_then(|said| said.as_array().cloned()).unwrap_or_default()
    }

    fn save(&self, rows: &mut Vec<Value>) {
        let cutoff = self.app.now() - self.app.paths.token_history_retention_sec as f64;
        // absent-ok: `h.get("t", 0)`: a row with no moment is older than any cutoff.
        rows.retain(|row| Coerce::float_or_zero(row.get("t")) >= cutoff);
        let most = usize::try_from(self.app.paths.token_history_max).unwrap_or(usize::MAX);
        let extra = rows.len().saturating_sub(most);
        rows.drain(..extra);
        let mut text = PythonJson::spaced_letters(&Value::Array(rows.clone()));
        text.push('\n');
        if let Err(error) = AtomicFile::write(&self.app.paths.token_history_file, text.as_bytes()) {
            Log::line(&format!("token history: not written: {error}"));
        }
    }

    fn usage_of(item: &Value) -> Option<&Value> {
        let of = |key: &str| {
            item.get(key).and_then(|part| part.get("usage")).filter(|usage| usage.is_object() && Coerce::truthy(Some(*usage)))
        };
        of("response").or_else(|| of("stream"))
    }

    /// Generation speed derived from a completed request's totals; `None` when it says none.
    fn usage_sample(item: &Value) -> Option<Value> {
        if !item.is_object() || Coerce::truthy(item.get("timings")) {
            return None;
        }
        let usage = Self::usage_of(item)?;
        let number = |from: &Value, keys: [&str; 2]| {
            let said = keys.iter().filter_map(|key| from.get(*key)).find(|said| Coerce::truthy(Some(*said)));
            said.map_or(Some(0.0), Coerce::float)
        };
        let eval_tokens = number(usage, ["completion_tokens", "completionTokens"])? as i64;
        let prompt_tokens = number(usage, ["prompt_tokens", "promptTokens"])? as i64;
        let total_ms = number(item, ["durationMs", "elapsedMs"])?;
        let first_byte_ms = number(item, ["firstByteMs", "firstByteMs"])?;
        let gen_ms = total_ms - first_byte_ms;
        if eval_tokens <= 0 || gen_ms <= 0.0 {
            return None;
        }
        Some(json!({
            "evalTokens": eval_tokens, "promptTokens": prompt_tokens, "genMs": gen_ms.round() as i64,
            "evalTps": Coerce::rounded(eval_tokens as f64 / (gen_ms / 1000.0), 1),
        }))
    }

    fn row_of(&self, item: &Value, recent: &BTreeSet<String>) -> Option<Value> {
        let timed = item.get("timings").filter(|timings| timings.is_object() && Coerce::truthy(Some(*timings)));
        let derived = if timed.is_some() { None } else { Self::usage_sample(item) };
        let at_timed = |key: &str| timed.and_then(|timed| timed.get(key));
        // absent-ok: `float(tm.get(key) or 0)`: what the timings do not state took nothing.
        let measure = |key: &str| at_timed(key).and_then(Coerce::float).unwrap_or(0.0);
        // absent-ok: a derived row holds every field this reads: `usage_sample` wrote them.
        let derived_at = |key: &str| derived.as_ref().and_then(|row| row.get(key)).and_then(Value::as_f64).unwrap_or(0.0);
        let eval_tokens = if timed.is_some() { measure("predicted_n") as i64 } else { derived_at("evalTokens") as i64 };
        if eval_tokens <= 0 {
            return None;
        }
        let finished = item.get("finishedAt").filter(|at| Coerce::truthy(Some(*at)));
        let id = Coerce::text(item.get("id"));
        let eval_tps = if timed.is_some() {
            Coerce::str_of(at_timed("predicted_per_second"))
        } else {
            Coerce::str_of(derived.as_ref().and_then(|row| row.get("evalTps")))
        };
        let sig = if id.is_empty() {
            format!(
                "{}:{eval_tokens}:{eval_tps}",
                item.get("finishedAt").map_or_else(|| "None".to_string(), |at| Coerce::str_of(Some(at)))
            )
        } else {
            id
        };
        if recent.contains(&sig) {
            return None;
        }
        let finishes =
            |key: &str| item.get(key).and_then(|part| part.get("finishReasons")).filter(|said| Coerce::truthy(Some(*said)));
        let finish = finishes("response").or_else(|| finishes("stream")).and_then(Value::as_array).and_then(|rows| rows.first());
        let moment = finished.and_then(Coerce::int).unwrap_or_else(|| self.app.now_whole());
        let client = item.get("client").filter(|said| Coerce::truthy(Some(*said))).cloned().unwrap_or_else(|| json!(""));
        let route = item.get("route").filter(|said| Coerce::truthy(Some(*said))).cloned().unwrap_or_else(|| json!(""));
        Some(json!({
            "t": moment,
            "sig": sig,
            "client": client,
            "port": item.get("port").and_then(Coerce::int),
            "route": route,
            "promptTps": if timed.is_some() { json!(Coerce::rounded(measure("prompt_per_second"), 1)) } else { json!(0) },
            "evalTps": if timed.is_some() { json!(Coerce::rounded(measure("predicted_per_second"), 1)) } else { json!(derived_at("evalTps")) },
            "promptTokens": if timed.is_some() { measure("prompt_n") as i64 } else { derived_at("promptTokens") as i64 },
            "evalTokens": eval_tokens,
            "promptMs": if timed.is_some() { measure("prompt_ms").round() as i64 } else { 0 },
            "genMs": if timed.is_some() { measure("predicted_ms").round() as i64 } else { derived_at("genMs") as i64 },
            "cacheTokens": if timed.is_some() { measure("cache_n") as i64 } else { 0 },
            "finish": finish.map_or_else(String::new, |word| Coerce::str_of(Some(word))),
            "source": if timed.is_some() { "timings" } else { "usage" },
        }))
    }

    /// One entry per completed proxy request of the sample, attributed to the consumer by proxy port.
    pub fn record(&self, sample: &Value) {
        let agents = sample.get("agentProxies").and_then(|proxies| proxies.get("agents")).and_then(Value::as_object);
        let mut items: Vec<&Value> = Vec::new();
        for row in agents.into_iter().flatten().map(|(_, row)| row) {
            for item in row.get("recent").and_then(Value::as_array).into_iter().flatten() {
                let timed = item.get("timings").is_some_and(|timings| timings.is_object() && Coerce::truthy(Some(timings)));
                if item.is_object() && (timed || Self::usage_sample(item).is_some()) {
                    items.push(item);
                }
            }
        }
        if items.is_empty() {
            return;
        }
        let mut held = self.app.token_history.rows.lock().unwrap_or_else(PoisonError::into_inner);
        let rows = held.get_or_insert_with(|| self.load());
        let tail = rows.len().saturating_sub(Self::RECENT);
        let mut recent: BTreeSet<String> = rows.iter().skip(tail).map(|row| Coerce::text(row.get("sig"))).collect();
        let mut changed = false;
        for item in items {
            if let Some(row) = self.row_of(item, &recent) {
                recent.insert(Coerce::text(row.get("sig")));
                rows.push(row);
                changed = true;
            }
        }
        if changed {
            self.save(rows);
        }
    }

    /// The rows of one port, or of one client, over a range.
    pub fn query(&self, client: &str, range: &str, port: &str) -> Value {
        let mut rows = {
            let mut held = self.app.token_history.rows.lock().unwrap_or_else(PoisonError::into_inner);
            held.get_or_insert_with(|| self.load()).clone()
        };
        if !port.is_empty() {
            if let Ok(port) = Coerce::strip(port).parse::<i64>() {
                rows.retain(|row| row.get("port") == Some(&json!(port)));
            }
        } else if !client.is_empty() {
            rows.retain(|row| row.get("client").and_then(Value::as_str) == Some(client));
        }
        if let Some((_, span)) = Self::RANGES.iter().find(|(name, _)| *name == range) {
            let cutoff = self.app.now() - *span as f64;
            // absent-ok: `h.get("t", 0)`: a row with no moment is older than any cutoff.
            rows.retain(|row| Coerce::float_or_zero(row.get("t")) >= cutoff);
        }
        let shown: Vec<Value> = rows
            .iter()
            .map(|row| {
                let or = |key: &str, otherwise: Value| row.get(key).cloned().unwrap_or(otherwise);
                json!({
                    "t": row.get("t"), "promptTps": or("promptTps", json!(0)), "evalTps": or("evalTps", json!(0)),
                    "promptTokens": or("promptTokens", json!(0)), "evalTokens": or("evalTokens", json!(0)),
                    "promptMs": or("promptMs", json!(0)), "genMs": or("genMs", json!(0)),
                    "cacheTokens": or("cacheTokens", json!(0)), "finish": or("finish", json!("")),
                    "port": row.get("port"), "route": or("route", json!("")), "client": or("client", json!("")),
                })
            })
            .collect();
        Value::Array(shown)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn speed_is_derived_from_a_request_s_totals() {
        let item = json!({"durationMs": 2000, "firstByteMs": 1000, "response": {"usage": {"completion_tokens": 50, "prompt_tokens": 7}}});
        assert_eq!(
            TokenHistory::usage_sample(&item).unwrap(),
            json!({"evalTokens": 50, "promptTokens": 7, "genMs": 1000, "evalTps": 50.0})
        );
        assert!(TokenHistory::usage_sample(&json!({"timings": {"x": 1}})).is_none());
        assert!(TokenHistory::usage_sample(&json!({"response": {"usage": {"completion_tokens": 0}}})).is_none());
    }
}
