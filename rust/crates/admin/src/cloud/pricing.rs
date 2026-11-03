//! The LiteLLM model-pricing table with a 24 h cache on disk.

use crate::app::App;
use files::AtomicFile;
use rules::{Coerce, PythonJson};
use serde_json::{Map, Value, json};
use std::time::Duration;

/// The table of this controller.
pub struct ModelPricing<'app> {
    app: &'app App,
}

impl<'app> ModelPricing<'app> {
    const URL: &'static str = "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json";
    const TTL: f64 = 24.0 * 3600.0;
    const SHAPE: i64 = 2;

    /// The table of `app`.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    /// A LiteLLM price per token as dollars per million tokens; `None` where the table names no usable one.
    fn per_million(value: Option<&Value>) -> Option<f64> {
        let number = match value? {
            Value::Number(number) => number.as_f64()?,
            Value::String(text) => text.trim().parse().ok()?,
            _ => return None,
        };
        (number >= 0.0).then(|| Coerce::rounded(number * 1_000_000.0, 6))
    }

    fn row_of(data: &Value) -> Option<Value> {
        let (input, output) = (
            data.get("input_cost_per_token").filter(|said| !said.is_null()),
            data.get("output_cost_per_token").filter(|said| !said.is_null()),
        );
        if input.is_none() && output.is_none() {
            return None;
        }
        // absent-ok: `float(inp or 0)`: a model the table prices one way costs nothing the other.
        let price = |raw: Option<&Value>| Coerce::rounded(raw.and_then(Coerce::float).unwrap_or(0.0) * 1_000_000.0, 6);
        let mut row = json!({"inputPer1M": price(input), "outputPer1M": price(output), "provider": Coerce::text(data.get("litellm_provider"))});
        for (name, field) in
            [("cacheReadPer1M", "cache_read_input_token_cost"), ("cacheWritePer1M", "cache_creation_input_token_cost")]
        {
            if let Some(cost) = Self::per_million(data.get(field)) {
                Coerce::put(&mut row, name, json!(cost));
            }
        }
        Some(row)
    }

    /// The table: from the cache while it is fresh, else asked for; what the cache last held when the network says nothing.
    pub fn table(&self) -> Value {
        let path = &self.app.paths.model_pricing_cache;
        let cached: Option<Value> = std::fs::read(path).ok().and_then(|raw| serde_json::from_slice(&raw).ok());
        let held = cached.as_ref().filter(|cached| cached.get("pricing").is_some_and(Value::is_object));
        if let Some(cached) = held {
            // absent-ok: `float(cached.get("fetchedAt", 0))`: a cache that names no moment is an old one.
            let age = self.app.now() - Coerce::float_or_zero(cached.get("fetchedAt"));
            if cached.get("shape") == Some(&json!(Self::SHAPE)) && age < Self::TTL {
                return cached.get("pricing").cloned().unwrap_or_else(|| json!({}));
            }
        }
        let stale = held.and_then(|cached| cached.get("pricing")).cloned().unwrap_or_else(|| json!({}));
        let fields = [("User-Agent", "llamacpp-easy-admin/1.0".to_string())];
        let Ok(raw) = self.app.http.json("GET", Self::URL, &fields, &[], Duration::from_secs(15)) else {
            return stale;
        };
        let mut pricing = Map::new();
        for (model, data) in raw.as_object().into_iter().flatten() {
            if let Some(row) = Self::row_of(data) {
                pricing.insert(model.clone(), row);
            }
        }
        let pricing = Value::Object(pricing);
        let kept = json!({"fetchedAt": self.app.now_whole(), "shape": Self::SHAPE, "pricing": pricing});
        let mut text = PythonJson::spaced_letters(&kept);
        text.push('\n');
        if let Some(parent) = path.parent() {
            drop(std::fs::create_dir_all(parent));
        }
        // A cache that was not written is asked for again: nothing depends on it.
        drop(AtomicFile::write(path, text.as_bytes()));
        pricing
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_row_is_priced_per_million() {
        let row = ModelPricing::row_of(&json!({"input_cost_per_token": 0.000003, "output_cost_per_token": 0.000015, "litellm_provider": "x", "cache_read_input_token_cost": "0.0000003"})).unwrap();
        assert_eq!(row, json!({"inputPer1M": 3.0, "outputPer1M": 15.0, "provider": "x", "cacheReadPer1M": 0.3}));
        assert!(ModelPricing::row_of(&json!({"litellm_provider": "x"})).is_none());
    }
}
