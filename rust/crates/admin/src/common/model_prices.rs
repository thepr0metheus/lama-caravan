//! What a model costs per million tokens, in the one place that says it. A model nobody priced is KNOWN not to be: `known` is false and the cost it adds is 0, and the caller says how many requests that covered. The cache has its own two prices.

use serde_json::Value;

/// The operator's prices laid over the LiteLLM table, both as `{model: {inputPer1M, outputPer1M[, cacheReadPer1M, cacheWritePer1M]}}`.
pub struct ModelPrices<'prices> {
    table: Option<&'prices Value>,
    overrides: Option<&'prices Value>,
}

impl<'prices> ModelPrices<'prices> {
    /// The prices.
    pub fn new(table: Option<&'prices Value>, overrides: Option<&'prices Value>) -> Self {
        Self { table, overrides }
    }

    fn figure(row: &Value, name: &str) -> f64 {
        // absent-ok: `float(row.get(name) or 0)`: a figure nobody said is no price of that kind.
        row.get(name).and_then(Value::as_f64).unwrap_or(0.0)
    }

    /// The row that prices the model: the operator's when it names a price, else the table's. A row that names neither number is no price.
    pub fn row(&self, model: &str) -> Option<&'prices Value> {
        [self.overrides, self.table]
            .into_iter()
            .flatten()
            .filter_map(|source| source.get(model))
            .find(|row| row.is_object() && (Self::figure(row, "inputPer1M") != 0.0 || Self::figure(row, "outputPer1M") != 0.0))
    }

    /// (inputPer1M, outputPer1M, known).
    pub fn of(&self, model: &str) -> (f64, f64, bool) {
        self.row(model).map_or((0.0, 0.0, false), |row| (Self::figure(row, "inputPer1M"), Self::figure(row, "outputPer1M"), true))
    }

    /// (cacheReadPer1M, cacheWritePer1M): the same row's own cache prices, and for one it does not name the row's INPUT price: the cache is not free, and a plain input token is the nearest price there is.
    pub fn cache_of(&self, model: &str) -> (f64, f64) {
        let Some(row) = self.row(model) else {
            return (0.0, 0.0);
        };
        let input = Self::figure(row, "inputPer1M");
        let rate = |name: &str| row.get(name).and_then(Value::as_f64).filter(|price| *price >= 0.0).unwrap_or(input);
        (rate("cacheReadPer1M"), rate("cacheWritePer1M"))
    }

    /// (dollars, known) of that many tokens of the model. `prompt` is ALL the input, the cached and the written parts included. A cache count larger than the prompt it belongs to is cut to it.
    pub fn cost(&self, model: &str, prompt: i64, completion: i64, cache_read: i64, cache_write: i64) -> (f64, bool) {
        let (price_in, price_out, known) = self.of(model);
        let (read_price, write_price) = self.cache_of(model);
        let prompt = prompt.max(0);
        let read = cache_read.max(0).min(prompt);
        let write = cache_write.max(0).min(prompt - read);
        let dollars = (prompt - read - write) as f64 * price_in
            + read as f64 * read_price
            + write as f64 * write_price
            + completion.max(0) as f64 * price_out;
        (dollars / 1e6, known)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn the_operators_price_wins_and_a_model_nobody_priced_is_said() {
        let table = json!({"m": {"inputPer1M": 2.0, "outputPer1M": 4.0, "cacheReadPer1M": 0.1}});
        let overrides = json!({"n": {"inputPer1M": 1.0, "outputPer1M": 1.0}, "m": {"inputPer1M": 0, "outputPer1M": 0}});
        let prices = ModelPrices::new(Some(&table), Some(&overrides));
        assert_eq!(prices.of("n"), (1.0, 1.0, true));
        assert_eq!(prices.of("m"), (2.0, 4.0, true));
        assert_eq!(prices.of("z"), (0.0, 0.0, false));
        assert_eq!(prices.cache_of("m"), (0.1, 2.0));
        let (dollars, known) = prices.cost("m", 1000, 500, 400, 700);
        assert!(known);
        assert!((dollars - (0.0 * 2.0 + 400.0 * 0.1 + 600.0 * 2.0 + 500.0 * 4.0) / 1e6).abs() < 1e-12);
    }
}
