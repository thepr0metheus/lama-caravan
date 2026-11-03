//! What the proxy's logs say each cloud account spent.

use super::data::CloudData;
use super::pricing::ModelPricing;
use crate::app::App;
use crate::common::account_credit::AccountCredit;
use crate::common::cloud_pools::CloudPools;
use crate::common::misc::Ordered;
use crate::common::model_prices::ModelPrices;
use os::LocalTime;
use rules::Coerce;
use serde_json::{Value, json};
use std::path::PathBuf;

/// Which account and which model a finished cloud request went to, read off its record in the proxy's event log.
pub struct CloudLeg {
    reading: CloudPools,
}

impl CloudLeg {
    /// A refusal of a pool names no account: nothing went out.
    const POOL_KINDS: [&'static str; 2] = ["pool_unavailable", "pool_context_required"];
    /// The kinds the caravan's own refusals have been recorded under; the last three are the names before pools of steps, still in the day of logs the board reads.
    pub const OWN_KINDS: [&'static str; 5] = [
        "pool_unavailable",
        "pool_context_required",
        "usage_reserve",
        "subscription_pool_unavailable",
        "subscription_pool_context_required",
    ];

    /// The reading of `data`.
    pub fn new(data: &Value) -> Self {
        Self { reading: CloudPools::new(data, None) }
    }

    /// `(account id, model)`: empty for what the record does not say.
    pub fn of(&self, item: &Value) -> (String, String) {
        let mut account = Coerce::text(item.get("cloudAccountId"));
        let mut model = Coerce::text(item.get("cloudModel"));
        if account.is_empty() && Self::POOL_KINDS.contains(&Coerce::text(item.get("errorKind")).as_str()) {
            return (String::new(), String::new());
        }
        if model.is_empty() {
            let pool = self.reading.get(&Coerce::text(item.get("providerId")));
            let rows: Vec<&Value> = pool
                .and_then(|pool| pool.get("steps"))
                .and_then(Value::as_array)
                .into_iter()
                .flatten()
                .filter(|row| row.get("kind").and_then(Value::as_str).is_none_or(|kind| kind == "account"))
                .collect();
            let named = rows.iter().find(|row| Coerce::text(row.get("accountId")) == account);
            let step = named.or_else(|| if account.is_empty() { rows.first() } else { None });
            if let Some(step) = step {
                if account.is_empty() {
                    account = Coerce::text(step.get("accountId"));
                }
                model = Coerce::text(step.get("model"));
            }
        }
        if model.is_empty() {
            model = Coerce::text(item.get("model"));
        }
        (account, model)
    }
}

/// The days of the proxy's journal.
pub struct JournalDays;

impl JournalDays {
    /// The name of the day `back` days before `now`, as its file is named; `None` when the system cannot place it.
    pub fn name(now: f64, back: i64) -> Option<String> {
        LocalTime::of(now as i64 - back * 86400).map(|day| day.date())
    }

    /// The file of a day.
    pub fn file(app: &App, day: &str) -> PathBuf {
        app.paths.agent_proxy_log_dir.join(format!("{day}.jsonl"))
    }

    /// A day's text, for its lines to be read one by one; `None` for a day with no file, or one that does not read.
    pub fn text(app: &App, now: f64, back: i64) -> Option<(String, String)> {
        let day = Self::name(now, back)?;
        let raw = std::fs::read(Self::file(app, &day)).ok()?;
        Some((day, String::from_utf8(raw).ok()?))
    }

    /// `int(item.get(key) or 0)`: an amount the record does not state is none.
    pub fn whole(row: Option<&Value>, key: &str) -> i64 {
        // absent-ok: a record that names no amount spent none.
        Coerce::int_or_zero(row.and_then(|row| row.get(key))).unwrap_or(0)
    }
}

/// What one account spent.
#[derive(Default)]
struct SpendRecord {
    total: f64,
    requests: i64,
    prompt_tokens: i64,
    completion_tokens: i64,
    unpriced: i64,
    by_model: Ordered<(f64, i64)>,
    since_total: f64,
    since_requests: i64,
    since_unpriced: i64,
}

impl SpendRecord {
    fn add(&mut self, model: &str, tokens: (i64, i64), cost: f64, known: bool) {
        self.total += cost;
        self.requests += 1;
        self.prompt_tokens += tokens.0;
        self.completion_tokens += tokens.1;
        self.unpriced += i64::from(!known);
        let row = self.by_model.entry(model);
        row.0 += cost;
        row.1 += 1;
    }

    fn add_since_credit(&mut self, cost: f64, known: bool) {
        self.since_total += cost;
        self.since_requests += 1;
        self.since_unpriced += i64::from(!known);
    }

    fn public(&self, days: i64, credit: Option<&Value>, now: f64, retention_days: i64) -> Value {
        let mut models: Vec<(&String, &(f64, i64))> = self.by_model.iter().collect();
        models.sort_by(|left, right| right.1.0.total_cmp(&left.1.0));
        let rows: Vec<Value> = models
            .iter()
            .map(|(model, (cost, requests))| json!({"model": model, "cost": Coerce::rounded(*cost, 4), "requests": requests}))
            .collect();
        let mut entry = json!({
            "total": Coerce::rounded(self.total, 4), "requests": self.requests, "promptTokens": self.prompt_tokens,
            "completionTokens": self.completion_tokens, "unpriced": self.unpriced, "windowDays": days, "byModel": rows,
        });
        if let Some(credit) = credit {
            // absent-ok: a credit is kept only with its moment: `AccountCredit.kept` holds that.
            let as_of = Coerce::float_or_zero(credit.get("asOf"));
            Coerce::put(
                &mut entry,
                "sinceCredit",
                json!({
                    "asOf": credit.get("asOf"), "total": Coerce::rounded(self.since_total, 4),
                    "requests": self.since_requests, "unpriced": self.since_unpriced,
                    "partial": retention_days > 0 && now - as_of > (retention_days * 86400) as f64,
                }),
            );
        }
        entry
    }
}

/// The spend meter on the board.
pub struct CloudSpend<'app> {
    app: &'app App,
}

impl<'app> CloudSpend<'app> {
    const LONGEST_REACH: i64 = 3650;

    /// The meter of `app`.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    fn retention_days(&self) -> i64 {
        // absent-ok: the proxy's own default, when the variable says nothing.
        self.app.env.get("AGENT_PROXY_LOG_RETENTION_DAYS").and_then(|said| said.trim().parse().ok()).unwrap_or(30)
    }

    /// The local spend meter: each account's cost over `days`, and since the credit the operator typed, read back as far as the oldest credit.
    pub fn summary(&self, days: i64, now: f64) -> Value {
        let table = ModelPricing::of(self.app).table();
        let overrides = self.app.admin.read(|doc| doc.get("apiPricing").cloned());
        let prices = ModelPrices::new(Some(&table), overrides.as_ref());
        let data = CloudData::of(self.app).load();
        let legs = CloudLeg::new(&data);
        let mut credits: Ordered<Value> = Ordered::default();
        for account in data.get("accounts").and_then(Value::as_array).into_iter().flatten() {
            if Coerce::truthy(account.get("id"))
                && let Some(credit) = AccountCredit::kept(account.get("credit"))
            {
                *credits.entry(&Coerce::str_of(account.get("id"))) = credit;
            }
        }
        let reach = credits
            .iter()
            .filter_map(|(_, credit)| credit.get("asOf").and_then(Coerce::float))
            .map(|as_of| ((now - as_of) / 86400.0).floor() as i64 + 1)
            .fold(days, i64::max)
            .min(Self::LONGEST_REACH);
        let mut records: Ordered<SpendRecord> = Ordered::default();
        for (account, _) in credits.iter() {
            records.entry(account);
        }
        for back in 0..reach {
            let Some((_, text)) = JournalDays::text(self.app, now, back) else {
                continue;
            };
            for line in text.lines().filter(|line| line.contains("\"finished\"") && line.contains("\"cloud\"")) {
                Self::count_line(line, &legs, &prices, (&mut records, &credits), back < days);
            }
        }
        let retention = self.retention_days();
        let mut out = serde_json::Map::new();
        for (account, record) in records.iter() {
            out.insert(account.clone(), record.public(days, credits.get(account), now, retention));
        }
        Value::Object(out)
    }

    /// One finished request of the journal, on its account's record.
    fn count_line(
        line: &str,
        legs: &CloudLeg,
        prices: &ModelPrices,
        books: (&mut Ordered<SpendRecord>, &Ordered<Value>),
        in_window: bool,
    ) {
        let (records, credits) = books;
        let Ok(row) = serde_json::from_str::<Value>(line) else {
            return;
        };
        let item = row.get("item");
        if Coerce::str_of(item.and_then(|item| item.get("upstreamType"))) != "cloud" {
            return;
        }
        let (account, model) = legs.of(item.unwrap_or(&Value::Null));
        if account.is_empty() {
            return;
        }
        let model = if model.is_empty() { "?".to_string() } else { model };
        let usage = item.and_then(|item| item.get("usage"));
        let (prompt, completion) = (JournalDays::whole(usage, "prompt"), JournalDays::whole(usage, "completion"));
        let (cost, known) = prices.cost(
            &model,
            prompt,
            completion,
            JournalDays::whole(usage, "cacheRead"),
            JournalDays::whole(usage, "cacheWrite"),
        );
        let record = records.entry(&account);
        let credit_from = credits.get(&account).and_then(|credit| credit.get("asOf")).and_then(Coerce::float);
        if credit_from.is_some_and(|from| JournalDays::whole(Some(&row), "time") as f64 >= from) {
            record.add_since_credit(cost, known);
        }
        if in_window {
            record.add(&model, (prompt, completion), cost, known);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn legs() -> CloudLeg {
        CloudLeg::new(&json!({"pools": [{"id": "p", "steps": [
            {"id": "o", "output": "mm:x"},
            {"id": "a", "accountId": "a", "model": "ma"},
            {"id": "b", "accountId": "b", "model": "mb"},
        ]}]}))
    }

    #[test]
    fn a_record_names_its_leg_or_its_pool_does() {
        let of = |item: Value| legs().of(&item);
        assert_eq!(of(json!({"cloudAccountId": "x", "cloudModel": "m"})), ("x".to_string(), "m".to_string()));
        assert_eq!(of(json!({"cloudAccountId": "b", "providerId": "p"})), ("b".to_string(), "mb".to_string()));
        assert_eq!(of(json!({"providerId": "p"})), ("a".to_string(), "ma".to_string()));
        assert_eq!(of(json!({"cloudAccountId": "z", "providerId": "p", "model": "said"})), ("z".to_string(), "said".to_string()));
        assert_eq!(of(json!({"errorKind": "pool_unavailable", "providerId": "p"})), (String::new(), String::new()));
    }

    #[test]
    fn a_record_says_what_it_spent() {
        let mut record = SpendRecord::default();
        record.add("cheap", (10, 1), 0.1, true);
        record.add("dear", (10, 1), 0.5, false);
        record.add("cheap", (10, 1), 0.1, true);
        let shown = record.public(30, None, 0.0, 30);
        assert_eq!(shown["byModel"][0]["model"], "dear");
        assert_eq!(shown["byModel"][1]["requests"], 2);
        assert_eq!(shown["unpriced"], 1);
        assert_eq!(shown["promptTokens"], 30);
        assert!(shown.get("sinceCredit").is_none());
        let credit = json!({"asOf": 0});
        let shown = record.public(30, Some(&credit), 100.0 * 86400.0, 30);
        assert_eq!(shown["sinceCredit"]["partial"], true);
    }
}
