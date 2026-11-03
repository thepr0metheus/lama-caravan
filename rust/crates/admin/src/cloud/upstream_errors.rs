//! The data plane's cloud failures per account, from the proxy's event log.

use super::data::CloudData;
use super::spend::{CloudLeg, JournalDays};
use crate::app::App;
use crate::common::misc::Ordered;
use rules::Coerce;
use serde_json::{Map, Value, json};
use std::collections::BTreeMap;

#[derive(Default)]
struct ErrorRow {
    model: String,
    code: String,
    count: i64,
    first_at: i64,
    last_at: i64,
    error: String,
    kind: String,
}

/// The panel's reading.
pub struct UpstreamErrors<'app> {
    app: &'app App,
}

impl<'app> UpstreamErrors<'app> {
    const SHOWN: usize = 8;
    const DAYS: i64 = 2;

    /// The reading of `app`.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    fn finished_rows(&self, now: f64) -> Vec<Value> {
        let mut rows = Vec::new();
        for back in 0..Self::DAYS {
            let Some((_, text)) = JournalDays::text(self.app, now, back) else {
                continue;
            };
            for line in text.lines().filter(|line| line.contains("\"finished\"") && line.contains("\"cloud\"")) {
                let Ok(row) = serde_json::from_str::<Value>(line) else {
                    continue;
                };
                if Coerce::str_of(row.get("item").and_then(|item| item.get("upstreamType"))) == "cloud" {
                    rows.push(row);
                }
            }
        }
        rows
    }

    fn add_failure(rows: &mut Ordered<Ordered<ErrorRow>>, account: &str, event: &Value, named: (&str, &str, &str), at: i64) {
        let (model, code, kind) = named;
        let row = rows.entry(account).entry(&format!("{model}\0{code}"));
        row.model = model.to_string();
        row.code = code.to_string();
        row.count += 1;
        if row.first_at == 0 || at < row.first_at {
            row.first_at = at;
        }
        if at >= row.last_at {
            row.last_at = at;
            let item = event.get("item");
            let said = item.and_then(|item| item.get("error")).filter(|said| Coerce::truthy(Some(*said)));
            if let Some(said) = said.or_else(|| event.get("error").filter(|said| Coerce::truthy(Some(*said)))) {
                row.error = Coerce::str_of(Some(said)).chars().take(200).collect();
            }
            if !kind.is_empty() {
                row.kind = kind.chars().take(60).collect();
            }
        }
    }

    /// Failures of the last `hours`, per account, with what went well since each.
    pub fn over(&self, hours: i64) -> Value {
        let now = self.app.now();
        let cutoff = now - (hours * 3600) as f64;
        let data = CloudData::of(self.app).load();
        let legs = CloudLeg::new(&data);
        let accounts = Coerce::list(data.get("accounts"));
        let known = |id: &str| accounts.iter().any(|row| row.get("id").and_then(Value::as_str) == Some(id));
        let mut by_account: Ordered<Ordered<ErrorRow>> = Ordered::default();
        let events = self.finished_rows(now);
        for event in &events {
            let item = event.get("item");
            let status = JournalDays::whole(item, "status");
            let kind = {
                let said = Coerce::text(item.and_then(|item| item.get("errorKind")));
                if said.is_empty() { Coerce::text(event.get("errorKind")) } else { said }
            };
            if status < 400 && kind.is_empty() {
                continue;
            }
            let at = JournalDays::whole(item, "finishedAt");
            if (at as f64) < cutoff {
                continue;
            }
            let (account, model) = legs.of(item.unwrap_or(&Value::Null));
            if !known(&account) {
                continue;
            }
            let model = if model.is_empty() { "?".to_string() } else { model };
            let code = if CloudLeg::OWN_KINDS.contains(&kind.as_str()) || status < 400 {
                kind.clone()
            } else {
                format!("HTTP {status}")
            };
            Self::add_failure(&mut by_account, &account, event, (&model, &code, &kind), at);
        }
        let after = Self::success_after(&by_account, &events, cutoff);
        let mut shown = Map::new();
        for (account, rows) in by_account.iter() {
            let (count, last) = after.get(account).copied().unwrap_or((0, 0));
            let mut ordered: Vec<&ErrorRow> = rows.iter().map(|(_, row)| row).collect();
            ordered.sort_by_key(|row| std::cmp::Reverse(row.count));
            let cards: Vec<Value> = ordered
                .iter()
                .take(Self::SHOWN)
                .map(|row| {
                    json!({
                        "model": row.model, "code": row.code, "count": row.count, "firstAt": row.first_at, "lastAt": row.last_at,
                        "error": row.error, "kind": row.kind, "okSince": count, "lastOkAt": last,
                    })
                })
                .collect();
            shown.insert(account.clone(), Value::Array(cards));
        }
        json!({"ok": true, "windowHours": hours, "byAccount": shown})
    }

    /// Per account: how many requests answered since its last failure, and when the last one did.
    fn success_after(by_account: &Ordered<Ordered<ErrorRow>>, events: &[Value], cutoff: f64) -> BTreeMap<String, (i64, i64)> {
        let newest: BTreeMap<&String, i64> = by_account
            .iter()
            // absent-ok: an account with no rows has no last failure.
            .map(|(account, rows)| (account, rows.iter().map(|(_, row)| row.last_at).max().unwrap_or(0)))
            .collect();
        let mut out: BTreeMap<String, (i64, i64)> = BTreeMap::new();
        for event in events {
            let item = event.get("item");
            let status = JournalDays::whole(item, "status");
            if status >= 400 || status == 0 {
                continue;
            }
            let account = Coerce::text(item.and_then(|item| item.get("cloudAccountId")));
            let at = JournalDays::whole(item, "finishedAt");
            let Some(failed) = newest.get(&account) else {
                continue;
            };
            if (at as f64) < cutoff.max(*failed as f64) {
                continue;
            }
            let row = out.entry(account).or_insert((0, 0));
            row.0 += 1;
            row.1 = row.1.max(at);
        }
        out
    }
}
