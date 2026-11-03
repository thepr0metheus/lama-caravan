//! A ChatGPT subscription's own calls: its models and its limits.

use super::call::{Upstream, UpstreamFailure};
use super::catalog::ModelCatalog;
use super::data::CloudData;
use crate::app::App;
use crate::common::cloud_sources::CloudSources;
use crate::common::window::Windows;
use plumbing::http_client::HttpError;
use rules::{AppError, Coerce};
use serde_json::{Value, json};
use std::time::Duration;
use wire::{HttpDate, Percent};

/// A catalogue's row: one provider model as the catalogue keeps it.
pub struct CatalogueEntry;

impl CatalogueEntry {
    /// The row of `raw`, its window only when the provider states one.
    pub fn of(id: &Value, name: Option<&Value>, raw: &Value) -> Value {
        let shown = name.filter(|name| Coerce::truthy(Some(*name))).unwrap_or(id);
        let mut entry = json!({"id": id, "name": shown});
        if let Some(window) = Windows::declared(raw) {
            Coerce::put(&mut entry, "contextLength", json!(window));
        }
        entry
    }
}

/// What opens a subscription's own calls.
pub struct SubscriptionAuth<'app> {
    app: &'app App,
}

impl<'app> SubscriptionAuth<'app> {
    /// The calls of `app`.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    /// The id a token claims: ChatGPT wants it in a field of its own; empty for a token that claims none.
    pub fn claimed_account(token: &str) -> String {
        let payload = token.split('.').nth(1).and_then(net::Base64Url::decode);
        let said: Option<Value> = payload.and_then(|raw| serde_json::from_slice(&raw).ok());
        let claim = said.as_ref().and_then(|said| said.get("https://api.openai.com/auth"));
        Coerce::text(claim.and_then(|claim| claim.get("chatgpt_account_id")))
    }

    /// `(token, account id)` of a subscription account, renewed if needed.
    pub fn fields_of(&self, account: &Value) -> Result<(String, String), AppError> {
        let cloud = CloudData::of(self.app);
        let data = cloud.load();
        let sources = CloudSources::new(&data, None);
        let owner = sources.canonical(&Coerce::text(account.get("id")));
        let owner = owner.ok_or_else(|| AppError::new("this source has no individual subscription login"))?;
        let config = owner.get("oauthConfig");
        let at = |key: &str| Coerce::text(config.and_then(|config| config.get(key)));
        let (url, client) = (at("tokenUrl"), at("clientId"));
        let upstream = Upstream::of(self.app);
        let oauth =
            cloud.vault().oauth(&Coerce::text(owner.get("id")), (&url, &client), false, self.app.now() as i64, &|url, form| {
                upstream.renew(url, form)
            });
        let oauth = oauth.map_err(|error| AppError::with_status(format!("OAuth renewal failed: {error}"), 502))?;
        let token = Coerce::text(oauth.get("accessToken"));
        if token.is_empty() {
            return Err(AppError::new("no OAuth token — log in first"));
        }
        let claimed = Self::claimed_account(&token);
        Ok((token, claimed))
    }

    fn own_fields(&self, account: &Value) -> Result<super::call::Fields, AppError> {
        let (token, claimed) = self.fields_of(account)?;
        Ok(vec![
            ("Authorization".to_string(), format!("Bearer {token}")),
            ("chatgpt-account-id".to_string(), claimed),
            ("originator".to_string(), "pi".to_string()),
        ])
    }

    /// The models a subscription offers: chatgpt.com/backend-api/codex/models.
    pub fn models(&self, account_id: &str) -> Result<Vec<Value>, AppError> {
        let account = self.source(account_id)?;
        let upstream = Upstream::of(self.app);
        let fields = upstream.named(self.own_fields(&account)?);
        let (version, _) = ModelCatalog::of(self.app).codex_client_version();
        let url = format!("https://chatgpt.com/backend-api/codex/models?client_version={}", Percent::encode_path(&version));
        let data = ModelCatalog::of(self.app).guarded(&format!("{account_id}:models"), || {
            upstream.json("GET", &url, &fields, &[], Duration::from_secs(15)).map_err(|error| match error {
                HttpError::Status(code, said) => {
                    let said: String = said.chars().take(200).collect();
                    UpstreamFailure::answered(AppError::with_status(format!("chatgpt.com returned {code}: {said}"), 502))
                }
                other => UpstreamFailure {
                    network: other.is_silence(),
                    error: AppError::with_status(format!("failed to fetch models: {other}"), 502),
                },
            })
        })?;
        let rows = data.get("models").and_then(Value::as_array).into_iter().flatten();
        let offered = rows.filter(|row| {
            row.get("visibility").and_then(Value::as_str) != Some("hide") && Coerce::truthy(row.get("supported_in_api"))
        });
        Ok(offered.map(|row| CatalogueEntry::of(row.get("slug").unwrap_or(&Value::Null), row.get("display_name"), row)).collect())
    }

    fn source(&self, account_id: &str) -> Result<Value, AppError> {
        let data = CloudData::of(self.app).load();
        CloudSources::new(&data, None).source(account_id).ok_or_else(|| AppError::with_status("unknown account", 404))
    }

    /// The Codex usage limits and credits of a subscription.
    pub fn usage(&self, account_id: &str) -> Result<Value, AppError> {
        let account = self.source(account_id)?;
        let upstream = Upstream::of(self.app);
        let mut own = self.own_fields(&account)?;
        own.push(("Accept".to_string(), "application/json".to_string()));
        let fields = upstream.named(own);
        let data = ModelCatalog::of(self.app).guarded(&format!("{account_id}:usage"), || {
            upstream.json("GET", "https://chatgpt.com/backend-api/wham/usage", &fields, &[], Duration::from_secs(10)).map_err(
                |error| match error {
                    HttpError::Status(code @ (401 | 403), _) => UpstreamFailure::answered(AppError::with_status(
                        format!("ChatGPT refused the sign-in (HTTP {code}) — sign in again in the account's ⚙"),
                        502,
                    )),
                    HttpError::Status(code, _) => {
                        UpstreamFailure::answered(AppError::with_status(format!("usage endpoint: HTTP {code}"), 502))
                    }
                    other => UpstreamFailure {
                        network: other.is_silence(),
                        error: AppError::with_status(format!("usage endpoint: {other}"), 502),
                    },
                },
            )
        })?;
        Ok(UsageShape::normalize(&data))
    }
}

/// chatgpt.com's usage answer in the one shape the page reads.
pub struct UsageShape;

impl UsageShape {
    fn window_label(window: &Value) -> String {
        // absent-ok: `int((window or {}).get("limit_window_seconds") or 0)`: a window that names no length is just a limit.
        let seconds = Coerce::whole(window.get("limit_window_seconds"));
        if seconds >= 604_800 {
            "Weekly limit".to_string()
        } else if seconds >= 86400 {
            format!("{}d limit", seconds / 86400)
        } else if seconds >= 3600 {
            format!("{}h limit", seconds / 3600)
        } else {
            "Limit".to_string()
        }
    }

    fn limit(window: &Value) -> Value {
        let label = Self::window_label(window);
        // absent-ok: `int(window.get("used_percent") or 0)`: what is not said to be used reads as free, as the provider's own page shows it.
        let used = Coerce::whole(window.get("used_percent"));
        let reset = window.get("reset_at").filter(|said| Coerce::truthy(Some(*said)));
        let resets_at = reset.map_or_else(String::new, |said| match Coerce::int(said) {
            Some(epoch) => HttpDate::iso_z(epoch),
            None => Coerce::str_of(Some(said)),
        });
        let name = {
            let said = Coerce::stripped(window.get("limit_name"));
            if said.is_empty() { Coerce::stripped(window.get("name")) } else { said }
        };
        let seconds = window
            .get("limit_window_seconds")
            .filter(|said| Coerce::truthy(Some(*said)))
            .and_then(Coerce::int)
            .filter(|seconds| *seconds != 0);
        json!({
            "label": if name.is_empty() { label.clone() } else { format!("{name} · {label}") },
            "name": name,
            "remainingPct": (100 - used).max(0),
            "resetsAt": resets_at,
            "windowSeconds": seconds,
        })
    }

    /// The answer as the page reads it.
    pub fn normalize(data: &Value) -> Value {
        let empty = json!({});
        let rate = data.get("rate_limit").filter(|said| Coerce::truthy(Some(*said))).unwrap_or(&empty);
        let mut limits = Vec::new();
        for window in [rate.get("primary_window"), rate.get("secondary_window")].into_iter().flatten() {
            if window.is_object() {
                limits.push(Self::limit(window));
            }
        }
        for extra in rate.get("additional_rate_limits").and_then(Value::as_array).into_iter().flatten() {
            if extra.is_object() {
                limits.push(Self::limit(extra));
            }
        }
        let credits = data.get("credits").filter(|said| said.is_object());
        let has_credits = Coerce::truthy(credits.and_then(|said| said.get("has_credits")));
        let balance = credits.and_then(|said| said.get("balance")).and_then(Coerce::float).filter(|_| has_credits);
        let reached = data.get("rate_limit_reached_type").filter(|said| said.is_object()).unwrap_or(&empty);
        let upsell = data.get("rate_limit_upsell").filter(|said| said.is_object()).unwrap_or(&empty);
        let ctas = upsell.get("ctas").and_then(Value::as_array).into_iter().flatten();
        let ctas: Vec<String> = ctas
            .filter(|row| row.is_object() && Coerce::truthy(row.get("label")))
            .map(|row| Coerce::str_of(row.get("label")))
            .collect();
        let offered = Coerce::truthy(upsell.get("title")) || Coerce::truthy(upsell.get("description"));
        json!({
            "ok": true,
            "limits": limits,
            "credits": balance.map(Self::round_half_even),
            "planType": Coerce::text(data.get("plan_type")),
            "limitReached": Coerce::truthy(rate.get("limit_reached")),
            "allowed": rate.get("allowed").map(|allowed| Coerce::truthy(Some(allowed))),
            "reachedType": Coerce::text(reached.get("type")),
            "reachedDetails": Coerce::text(reached.get("details")),
            "upsell": offered.then(|| json!({"title": Coerce::text(upsell.get("title")), "description": Coerce::text(upsell.get("description")), "ctas": ctas})),
            "creditsInfo": {
                "hasCredits": has_credits,
                "unlimited": Coerce::truthy(credits.and_then(|said| said.get("unlimited"))),
                "approxLocalMessages": credits.and_then(|said| said.get("approx_local_messages")),
            },
        })
    }

    /// `round(balance)`: a half goes to the even neighbour.
    fn round_half_even(value: f64) -> i64 {
        let floor = value.floor();
        let gap = value - floor;
        let up = gap > 0.5 || (gap == 0.5 && (floor as i64) % 2 != 0);
        (if up { floor + 1.0 } else { floor }) as i64
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_window_says_its_length_in_a_word() {
        let label = |seconds: i64| UsageShape::window_label(&json!({"limit_window_seconds": seconds}));
        assert_eq!(label(604_800), "Weekly limit");
        assert_eq!(label(172_800), "2d limit");
        assert_eq!(label(18000), "5h limit");
        assert_eq!(label(60), "Limit");
    }

    #[test]
    fn the_usage_answer_has_one_shape() {
        let shaped = UsageShape::normalize(&json!({
            "plan_type": "plus",
            "rate_limit": {"allowed": true, "primary_window": {"used_percent": 30, "limit_window_seconds": 18000, "reset_at": 86400}},
            "credits": {"has_credits": true, "balance": "12.5"},
        }));
        assert_eq!(shaped["limits"][0]["remainingPct"], 70);
        assert_eq!(shaped["limits"][0]["resetsAt"], "1970-01-02T00:00:00Z");
        assert_eq!(shaped["limits"][0]["windowSeconds"], 18000);
        assert_eq!(shaped["credits"], 12);
        assert_eq!(shaped["allowed"], true);
        assert_eq!(shaped["upsell"], Value::Null);
        let none = UsageShape::normalize(&json!({}));
        assert_eq!(none["allowed"], Value::Null);
        assert_eq!(none["credits"], Value::Null);
    }

    #[test]
    fn a_token_claims_its_account() {
        // {"https://api.openai.com/auth":{"chatgpt_account_id":"acc"}}
        let payload = "eyJodHRwczovL2FwaS5vcGVuYWkuY29tL2F1dGgiOnsiY2hhdGdwdF9hY2NvdW50X2lkIjoiYWNjIn19";
        assert_eq!(SubscriptionAuth::claimed_account(&format!("h.{payload}.s")), "acc");
        assert_eq!(SubscriptionAuth::claimed_account("x"), "");
    }
}
