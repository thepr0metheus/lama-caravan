//! What a provider says of a key: what it spent, what is left on it.

use super::api::CloudApi;
use super::call::Upstream;
use super::catalog::ModelCatalog;
use super::data::CloudData;
use super::oauth::SignIn;
use crate::app::App;
use plumbing::http_client::HttpError;
use rules::{AppError, Coerce};
use serde_json::{Value, json};
use std::time::Duration;

/// The reports of this controller.
pub struct KeyReports<'app> {
    app: &'app App,
}

impl<'app> KeyReports<'app> {
    /// The reports of `app`.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    fn fields_of(&self, account: &Value, account_id: &str) -> super::call::Fields {
        let cloud = CloudData::of(self.app);
        let mut fields = cloud.auth_fields(account, &cloud.secret_entry(account_id));
        fields.push(("Accept".to_string(), "application/json".to_string()));
        fields
    }

    fn disabled_words(&self, endpoint: &str) -> Value {
        let state = ModelCatalog::of(self.app).endpoint_state(endpoint);
        json!({"ok": false, "disabled": true, "error": format!("disabled after {}", ModelCatalog::refusal_words(&state))})
    }

    /// Official OpenAI-compatible spend, `GET <baseUrl>/organization/costs` (needs an API key with the api.usage.read scope).
    pub fn account_costs(&self, account_id: &str, days: i64) -> Result<Value, AppError> {
        let account = CloudApi::of(self.app).source(account_id)?;
        let base = Coerce::text(account.get("baseUrl")).trim_end_matches('/').to_string();
        if base.is_empty() {
            return Ok(json!({"ok": false, "error": "account has no baseUrl"}));
        }
        if account.get("authMode").and_then(Value::as_str) == Some("oauth") {
            SignIn::of(self.app).refresh_token(&account);
        }
        let fields = self.fields_of(&account, account_id);
        let start = self.app.now_whole() - days * 86400;
        let url = format!("{base}/organization/costs?start_time={start}&bucket_width=1d&limit={}", days + 1);
        let catalog = ModelCatalog::of(self.app);
        let endpoint = format!("{account_id}:costs");
        if catalog.endpoint_blocked(&endpoint) {
            return Ok(self.disabled_words(&endpoint));
        }
        let data = match Upstream::of(self.app).json("GET", &url, &fields, &[], Duration::from_secs(12)) {
            Ok(data) => data,
            Err(HttpError::Status(code @ (401 | 403), said)) => {
                let words = if said.contains("api.usage.read") {
                    "needs an API key with the api.usage.read scope (Admin key or a key granted Usage read)".to_string()
                } else {
                    format!("not permitted ({code})")
                };
                return Ok(json!({"ok": false, "error": words}));
            }
            Err(HttpError::Status(code, _)) => {
                catalog.record_fail(&endpoint, &format!("HTTP {code}"), false);
                return Ok(json!({"ok": false, "error": format!("HTTP {code}")}));
            }
            Err(other) => {
                catalog.record_fail(&endpoint, &other.to_string(), other.is_silence());
                return Ok(json!({"ok": false, "error": other.to_string()}));
            }
        };
        catalog.record_ok(&endpoint);
        let (mut total, mut currency, mut series) = (0.0, "usd".to_string(), Vec::new());
        for bucket in data.get("data").and_then(Value::as_array).into_iter().flatten() {
            let mut cost = 0.0;
            for result in bucket.get("results").and_then(Value::as_array).into_iter().flatten() {
                let amount = result.get("amount");
                // absent-ok: `float(amt.get("value") or 0)`: an amount that names no value adds nothing.
                cost += amount.and_then(|amount| amount.get("value")).and_then(Coerce::float).unwrap_or(0.0);
                let named = Coerce::text(amount.and_then(|amount| amount.get("currency")));
                if !named.is_empty() {
                    currency = named;
                }
            }
            total += cost;
            series.push(json!({"t": bucket.get("start_time"), "cost": Coerce::rounded(cost, 4)}));
        }
        Ok(json!({"ok": true, "total": Coerce::rounded(total, 4), "currency": currency, "windowDays": days, "days": series}))
    }

    /// What a key's provider says of the key at `path`; `Err` holds the refusal the board shows instead.
    fn key_report(
        &self,
        account_id: &str,
        path: &str,
        endpoint: &str,
        default_base: &str,
    ) -> Result<Result<Value, Value>, AppError> {
        let account = CloudApi::of(self.app).source(account_id)?;
        let said = Coerce::text(account.get("baseUrl"));
        let base = if said.is_empty() { default_base.to_string() } else { said };
        let url = format!("{}{path}", base.trim_end_matches('/'));
        let fields = self.fields_of(&account, account_id);
        let catalog = ModelCatalog::of(self.app);
        let endpoint = format!("{account_id}:{endpoint}");
        if catalog.endpoint_blocked(&endpoint) {
            return Ok(Err(self.disabled_words(&endpoint)));
        }
        match Upstream::of(self.app).json("GET", &url, &fields, &[], Duration::from_secs(10)) {
            Ok(data) => {
                catalog.record_ok(&endpoint);
                Ok(Ok(data))
            }
            Err(HttpError::Status(401 | 403, _)) => {
                Ok(Err(json!({"ok": false, "authError": true, "error": "key invalid or revoked"})))
            }
            Err(HttpError::Status(code, _)) => {
                catalog.record_fail(&endpoint, &format!("HTTP {code}"), false);
                Ok(Err(json!({"ok": false, "error": format!("HTTP {code}")})))
            }
            Err(other) => {
                catalog.record_fail(&endpoint, &other.to_string(), other.is_silence());
                Ok(Err(json!({"ok": false, "error": other.to_string()})))
            }
        }
    }

    /// What is left on the balance a DeepSeek key's tokens are paid from, `GET /user/balance`.
    pub fn deepseek_balance(&self, account_id: &str) -> Result<Value, AppError> {
        let base = self.app.presets.get("deepseek").map_or_else(String::new, |preset| Coerce::text(preset.get("baseUrl")));
        let data = match self.key_report(account_id, "/user/balance", "balance", &base)? {
            Ok(data) => data,
            Err(refused) => return Ok(refused),
        };
        let rows: Vec<Value> = data
            .get("balance_infos")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            .filter(|row| {
                row.is_object()
                    && !matches!(row.get("total_balance"), None | Some(Value::Null))
                    && row.get("total_balance") != Some(&json!(""))
            })
            .map(|row| {
                json!({
                    "currency": Coerce::text(row.get("currency")),
                    "total": Coerce::str_of(row.get("total_balance")),
                    "granted": Coerce::text(row.get("granted_balance")),
                    "toppedUp": Coerce::text(row.get("topped_up_balance")),
                })
            })
            .collect();
        Ok(json!({"ok": true, "available": data.get("is_available").filter(|said| said.is_boolean()), "balances": rows}))
    }

    /// The limits of an OpenRouter key, `GET /api/v1/auth/key`.
    pub fn openrouter_limits(&self, account_id: &str) -> Result<Value, AppError> {
        let data = match self.key_report(account_id, "/auth/key", "limits", "https://openrouter.ai/api/v1")? {
            Ok(data) => data,
            Err(refused) => return Ok(refused),
        };
        let empty = json!({});
        let key = data.get("data").filter(|said| Coerce::truthy(Some(*said))).unwrap_or(&empty);
        let rate = key.get("rate_limit").filter(|said| Coerce::truthy(Some(*said)));
        Ok(json!({
            "ok": true,
            "isFreeTier": Coerce::truthy(key.get("is_free_tier")),
            "label": key.get("label"),
            "usage": key.get("usage"),
            "limit": key.get("limit"),
            "rateLimit": rate.map(|rate| json!({"requests": rate.get("requests"), "interval": rate.get("interval")})),
        }))
    }
}
