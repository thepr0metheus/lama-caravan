//! Combined usage and spend over the last days, for the statistics panel.

use super::data::CloudData;
use super::pricing::ModelPricing;
use super::spend::{CloudLeg, JournalDays};
use crate::app::App;
use crate::common::cloud_sources::CloudSources;
use crate::common::misc::Ordered;
use crate::common::model_prices::ModelPrices;
use rules::Coerce;
use serde_json::{Map, Value, json};

#[derive(Default, Clone)]
struct Tally {
    cost: f64,
    requests: i64,
    prompt: i64,
    completion: i64,
    has_price: bool,
}

impl Tally {
    fn add(&mut self, cost: f64, prompt: i64, completion: i64) {
        self.cost += cost;
        self.requests += 1;
        self.prompt += prompt;
        self.completion += completion;
    }
}

#[derive(Default)]
struct AccountTally {
    all: Tally,
    by_model: Ordered<Tally>,
}

#[derive(Default)]
struct DayTally {
    cloud_cost: f64,
    cloud_tokens: i64,
    local_tokens: i64,
    local_would_cost: f64,
}

#[derive(Default)]
struct Totals {
    accounts: Ordered<AccountTally>,
    cloud_models: Ordered<Tally>,
    local_models: Ordered<Tally>,
    daily: Ordered<DayTally>,
}

/// The panel's reading.
pub struct UsageStats<'app> {
    app: &'app App,
}

impl<'app> UsageStats<'app> {
    /// The reading of `app`.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    fn sorted_by<'list>(
        rows: impl Iterator<Item = (&'list String, &'list Tally)>,
        key: impl Fn(&Tally) -> f64,
    ) -> Vec<(&'list String, &'list Tally)> {
        let mut rows: Vec<(&String, &Tally)> = rows.collect();
        rows.sort_by(|left, right| key(right.1).total_cmp(&key(left.1)));
        rows
    }

    fn cloud_row(totals: &mut Totals, day: &str, tokens: (i64, i64), named: (&str, &str), priced: (f64, bool)) {
        let (prompt, completion) = tokens;
        let (account, model) = named;
        let (cost, has_price) = priced;
        let row = totals.accounts.entry(account);
        row.all.add(cost, prompt, completion);
        let by_model = row.by_model.entry(model);
        by_model.add(cost, prompt, completion);
        by_model.has_price = has_price;
        totals.cloud_models.entry(model).add(cost, prompt, completion);
        let date = totals.daily.entry(day);
        date.cloud_cost += cost;
        date.cloud_tokens += prompt + completion;
    }

    fn read_day(&self, totals: &mut Totals, day: &str, text: &str, legs: &CloudLeg, prices: &ModelPrices<'_>, rate: (f64, f64)) {
        totals.daily.entry(day);
        for line in text.lines().filter(|line| line.contains("\"finished\"")) {
            let Ok(row) = serde_json::from_str::<Value>(line) else {
                continue;
            };
            let item = row.get("item").cloned().unwrap_or_else(|| json!({}));
            let kind = {
                let said = Coerce::text(item.get("upstreamType"));
                if said.is_empty() { "llama".to_string() } else { said }
            };
            let usage = item.get("usage");
            let (prompt, completion) = (JournalDays::whole(usage, "prompt"), JournalDays::whole(usage, "completion"));
            if kind == "cloud" {
                let (account, model) = legs.of(&item);
                if account.is_empty() {
                    continue;
                }
                let model = if model.is_empty() { "?".to_string() } else { model };
                let (_, _, has_price) = prices.of(&model);
                let (cost, _) = prices.cost(
                    &model,
                    prompt,
                    completion,
                    JournalDays::whole(usage, "cacheRead"),
                    JournalDays::whole(usage, "cacheWrite"),
                );
                Self::cloud_row(totals, day, (prompt, completion), (&account, &model), (cost, has_price));
            } else {
                let said = Coerce::str_of(item.get("model"));
                let model = if Coerce::truthy(item.get("model")) { said } else { "(unspecified)".to_string() };
                let would = prompt as f64 / 1e6 * rate.0 + completion as f64 / 1e6 * rate.1;
                totals.local_models.entry(&model).add(would, prompt, completion);
                let date = totals.daily.entry(day);
                date.local_tokens += prompt + completion;
                date.local_would_cost += would;
            }
        }
    }

    fn account_rows(totals: &Totals, data: &Value, prices: &ModelPrices<'_>) -> Value {
        let accounts = Coerce::list(data.get("accounts"));
        let find = |id: &str| accounts.iter().find(|row| Coerce::str_of(row.get("id")) == id);
        let mut out = Map::new();
        for (id, row) in totals.accounts.iter() {
            let models = Self::sorted_by(row.by_model.iter(), |tally| tally.cost);
            let shown: Vec<Value> = models
                .iter()
                .map(|(model, tally)| {
                    let (price_in, price_out, _) = prices.of(model);
                    json!({
                        "model": model, "cost": Coerce::rounded(tally.cost, 4), "requests": tally.requests,
                        "promptTokens": tally.prompt, "completionTokens": tally.completion, "hasPrice": tally.has_price,
                        "priceIn": price_in, "priceOut": price_out,
                    })
                })
                .collect();
            let account = find(id);
            let name = account.and_then(|account| {
                let named = account.get("name").filter(|said| Coerce::truthy(Some(*said)));
                named.or_else(|| account.get("id")).cloned()
            });
            let subscription = account.is_some_and(CloudSources::is_subscription);
            out.insert(
                id.clone(),
                json!({
                    "id": id, "name": name.unwrap_or_else(|| json!(id)), "subscription": subscription,
                    "total": Coerce::rounded(row.all.cost, 4), "requests": row.all.requests,
                    "promptTokens": row.all.prompt, "completionTokens": row.all.completion, "byModel": shown,
                }),
            );
        }
        Value::Object(out)
    }

    /// The cloud's models and the local ones, each with its figures, the largest first.
    fn model_rows(totals: &Totals) -> (Vec<Value>, Vec<Value>) {
        let cloud_models = Self::sorted_by(totals.cloud_models.iter(), |tally| tally.cost);
        let cloud_rows: Vec<Value> = cloud_models
            .iter()
            .map(|(model, tally)| {
                json!({"model": model, "cost": Coerce::rounded(tally.cost, 4), "requests": tally.requests, "promptTokens": tally.prompt, "completionTokens": tally.completion})
            })
            .collect();
        let local_models = Self::sorted_by(totals.local_models.iter(), |tally| (tally.prompt + tally.completion) as f64);
        let local_rows: Vec<Value> = local_models
            .iter()
            .map(|(model, tally)| {
                json!({"model": model, "requests": tally.requests, "promptTokens": tally.prompt, "completionTokens": tally.completion, "wouldCost": Coerce::rounded(tally.cost, 4)})
            })
            .collect();
        (cloud_rows, local_rows)
    }

    fn daily_rows(totals: &Totals) -> Vec<Value> {
        let mut days_seen: Vec<(&String, &DayTally)> = totals.daily.iter().collect();
        days_seen.sort_by_key(|(day, _)| *day);
        days_seen
            .iter()
            .map(|(day, row)| {
                json!({
                    "date": day, "cloudCost": Coerce::rounded(row.cloud_cost, 4), "cloudTokens": row.cloud_tokens,
                    "localTokens": row.local_tokens, "localWouldCost": Coerce::rounded(row.local_would_cost, 4),
                })
            })
            .collect()
    }

    /// The panel's numbers over the last `days`.
    pub fn over(&self, days: i64, now: f64) -> Value {
        let days = days.clamp(1, 365);
        let table = ModelPricing::of(self.app).table();
        let (overrides, rate) = self.app.admin.read(|doc| (doc.get("apiPricing").cloned(), doc.get("localPricing").cloned()));
        let data = CloudData::of(self.app).load();
        let legs = CloudLeg::new(&data);
        // absent-ok: `float(rate.get(key) or 0)`: a rate the operator did not set prices nothing.
        let rate_of = |key: &str| rate.as_ref().and_then(|rate| rate.get(key)).and_then(Coerce::float).unwrap_or(0.0);
        let (rate_in, rate_out) = (rate_of("inputPer1M"), rate_of("outputPer1M"));
        let prices = ModelPrices::new(Some(&table), overrides.as_ref());
        let mut totals = Totals::default();
        for back in 0..days {
            if let Some((day, text)) = JournalDays::text(self.app, now, back) {
                self.read_day(&mut totals, &day, &text, &legs, &prices, (rate_in, rate_out));
            }
        }
        let by_account = Self::account_rows(&totals, &data, &prices);
        // A fold and not `sum`: the sum of nothing is -0.0 in Rust, and an answer would say it so.
        let sum = |pick: &dyn Fn(&AccountTally) -> f64| {
            totals.accounts.iter().map(|(_, row)| pick(row)).fold(0.0, |total, cost| total + cost)
        };
        let count = |pick: &dyn Fn(&AccountTally) -> i64| totals.accounts.iter().map(|(_, row)| pick(row)).sum::<i64>();
        let (cloud_rows, local_rows) = Self::model_rows(&totals);
        let local = |pick: &dyn Fn(&Tally) -> i64| totals.local_models.iter().map(|(_, tally)| pick(tally)).sum::<i64>();
        let local_would =
            totals.local_models.iter().map(|(_, tally)| Coerce::rounded(tally.cost, 4)).fold(0.0, |total, cost| total + cost);
        let daily = Self::daily_rows(&totals);
        json!({
            "ok": true, "windowDays": days,
            "rate": {"inputPer1M": rate_in, "outputPer1M": rate_out},
            "cloud": {
                "total": Coerce::rounded(sum(&|row| row.all.cost), 4), "requests": count(&|row| row.all.requests),
                "promptTokens": count(&|row| row.all.prompt), "completionTokens": count(&|row| row.all.completion),
                "byAccount": by_account, "byModel": cloud_rows,
            },
            "local": {
                "wouldCost": Coerce::rounded(local_would, 4), "requests": local(&|tally| tally.requests),
                "promptTokens": local(&|tally| tally.prompt), "completionTokens": local(&|tally| tally.completion),
                "byModel": local_rows,
            },
            "daily": daily,
        })
    }
}
