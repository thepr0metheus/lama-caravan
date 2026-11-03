//! The cloud accounts, what they cost and how they fail.

use super::asked::Asked;
use crate::app::App;
use crate::cloud::api::CloudApi;
use crate::cloud::catalog::ModelCatalog;
use crate::cloud::data::CloudData;
use crate::cloud::oauth::{SignIn, SignOut};
use crate::cloud::pools::PoolDesk;
use crate::cloud::pricing::ModelPricing;
use crate::cloud::reports::KeyReports;
use crate::cloud::resets::SubscriptionResetDesk;
use crate::cloud::spend::CloudSpend;
use crate::cloud::subscription::SubscriptionAuth;
use crate::cloud::upstream_errors::UpstreamErrors;
use crate::cloud::usage_stats::UsageStats;
use crate::common::cloud_sources::CloudSources;
use crate::web::{Exchange, Routes};
use rules::{AppError, Coerce};
use serde_json::{Map, Value, json};

/// The routes.
pub struct CloudRoutes;

impl CloudRoutes {
    const COSTS_DAYS: i64 = 30;
    const SPEND_DAYS: i64 = 30;
    const USAGE_DAYS: i64 = 30;
    const ERROR_HOURS: i64 = 24;

    /// The table.
    pub const ROUTES: Routes = Routes {
        get: &[
            ("/api/cloud-accounts/oauth/status", Self::oauth_status),
            ("/api/cloud-accounts/models", Self::models),
            ("/api/cloud-accounts/subscription-models", Self::subscription_models),
            ("/api/cloud-accounts/subscription-usage", Self::subscription_usage),
            ("/api/cloud-accounts/subscription-resets", Self::subscription_resets),
            ("/api/cloud-accounts/api-costs", Self::api_costs),
            ("/api/cloud-accounts/openrouter-limits", Self::openrouter_limits),
            ("/api/cloud-accounts/deepseek-balance", Self::deepseek_balance),
            ("/api/cloud-accounts/proxy-spend", Self::proxy_spend),
            ("/api/cloud-accounts/catalogue", Self::catalogue),
            ("/api/cloud-upstream-errors", Self::upstream_errors),
            ("/api/usage-stats", Self::usage_stats),
            ("/api/local-pricing", Self::local_pricing),
            ("/api/api-pricing", Self::api_pricing),
            ("/api/model-pricing", Self::model_pricing),
        ],
        post: &[
            ("/api/local-pricing", Self::set_local_pricing),
            ("/api/api-pricing", Self::set_api_pricing),
            ("/api/cloud-accounts/check-models", Self::check_models),
            ("/api/cloud-accounts/subscription-reset", Self::subscription_reset),
            ("/api/cloud-accounts/test-alias", Self::test_alias),
            ("/api/cloud-accounts/save", Self::save),
            ("/api/cloud-accounts/delete", Self::delete),
            ("/api/cloud-accounts/key", Self::key),
            ("/api/cloud-accounts/key-delete", Self::key_delete),
            ("/api/cloud-accounts/oauth/device-start", Self::device_start),
            ("/api/cloud-api-health/retry", Self::health_retry),
        ],
        delete: &[],
    };

    fn oauth_status(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        let mut status = SignIn::of(app).status(&h.parsed.param_or("state", ""));
        if Coerce::text(status.get("state")) == "done" {
            Coerce::put(&mut status, "topology", Asked::board(app)?);
        }
        h.ok(&status);
        Ok(())
    }

    fn models(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        let models = CloudApi::of(app).fetch_account_models(&Asked::word(h, "id"))?;
        h.ok(&json!({"ok": true, "models": models}));
        Ok(())
    }

    fn subscription_models(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        let models = SubscriptionAuth::of(app).models(&Asked::word(h, "id"))?;
        h.ok(&json!({"ok": true, "models": models}));
        Ok(())
    }

    fn subscription_usage(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        h.ok(&SubscriptionAuth::of(app).usage(&Asked::word(h, "id"))?);
        Ok(())
    }

    fn subscription_resets(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        h.ok(&SubscriptionResetDesk::of(app).list(&h.parsed.param_or("id", ""))?);
        Ok(())
    }

    fn api_costs(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        h.ok(&KeyReports::of(app).account_costs(&Asked::word(h, "id"), Self::COSTS_DAYS)?);
        Ok(())
    }

    fn openrouter_limits(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        h.ok(&KeyReports::of(app).openrouter_limits(&Asked::word(h, "id"))?);
        Ok(())
    }

    fn deepseek_balance(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        h.ok(&KeyReports::of(app).deepseek_balance(&Asked::word(h, "id"))?);
        Ok(())
    }

    fn proxy_spend(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        h.ok(&json!({"ok": true, "spend": CloudSpend::of(app).summary(Self::SPEND_DAYS, app.now())}));
        Ok(())
    }

    fn catalogue(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        let account_id = Asked::word(h, "id");
        let data = CloudData::of(app).load();
        let sources = CloudSources::new(&data, None);
        let owner =
            sources.canonical(&account_id).ok_or_else(|| AppError::with_status(format!("unknown account: {account_id}"), 404))?;
        let entry = ModelCatalog::of(app).cached_models_entry(&Coerce::text(owner.get("id"))).unwrap_or_else(|| json!({}));
        let listed = entry.get("models").and_then(Value::as_array).into_iter().flatten();
        let mut rows: Vec<Value> = listed
            .filter(|model| model.is_object() && Coerce::truthy(model.get("id")))
            .map(|model| {
                let mut row = Coerce::fields(model);
                row.insert("chat".to_string(), json!(app.chat_models.is_chat(&Coerce::text(model.get("id")))));
                Value::Object(row)
            })
            .collect();
        rows.sort_by_key(|row| (!Coerce::truthy(row.get("chat")), Coerce::str_of(row.get("id")).to_lowercase()));
        h.ok(&json!({"ok": true, "models": rows, "fetchedAt": entry.get("fetchedAt")}));
        Ok(())
    }

    fn upstream_errors(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        h.ok(&UpstreamErrors::of(app).over(Self::ERROR_HOURS));
        Ok(())
    }

    fn usage_stats(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        let days =
            h.parsed.param("days").map_or(Self::USAGE_DAYS, |days| Coerce::strip(&days).parse().unwrap_or(Self::USAGE_DAYS));
        h.ok(&UsageStats::of(app).over(days, app.now()));
        Ok(())
    }

    fn section_or_empty(app: &App, name: &str) -> Value {
        app.admin.read(|doc| doc.get(name).filter(|said| Coerce::truthy(Some(*said))).cloned()).unwrap_or_else(|| json!({}))
    }

    fn local_pricing(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        h.ok(&json!({"ok": true, "rate": Self::section_or_empty(app, "localPricing")}));
        Ok(())
    }

    fn api_pricing(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        h.ok(&json!({"ok": true, "pricing": Self::section_or_empty(app, "apiPricing")}));
        Ok(())
    }

    /// The prices of a table with the operator's own over them: his price is the only one a model then has.
    fn model_pricing(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        let mut pricing = Coerce::fields(&ModelPricing::of(app).table());
        for (model, row) in Coerce::fields(&Self::section_or_empty(app, "apiPricing")) {
            // absent-ok: a model the table does not price starts from nothing.
            let mut base = pricing.get(&model).map(Coerce::fields).unwrap_or_default();
            base.insert("inputPer1M".to_string(), row.get("inputPer1M").cloned().unwrap_or_else(|| json!(0)));
            base.insert("outputPer1M".to_string(), row.get("outputPer1M").cloned().unwrap_or_else(|| json!(0)));
            base.shift_remove("cacheReadPer1M");
            base.shift_remove("cacheWritePer1M");
            base.entry("provider".to_string()).or_insert_with(|| json!("manual"));
            pricing.insert(model, Value::Object(base));
        }
        h.ok(&json!({"ok": true, "pricing": pricing}));
        Ok(())
    }

    /// `(inputPer1M, outputPer1M)`: never below zero; what is no number is refused.
    fn rates(body: &Value) -> Result<(f64, f64), AppError> {
        let rate = |name: &str| -> Result<f64, AppError> {
            let Some(said) = body.get(name).filter(|said| Coerce::truthy(Some(*said))) else {
                return Ok(0.0);
            };
            Coerce::float(said).map(|rate| rate.max(0.0)).ok_or_else(|| AppError::new("inputPer1M/outputPer1M must be numbers"))
        };
        Ok((rate("inputPer1M")?, rate("outputPer1M")?))
    }

    fn set_local_pricing(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        let (input, output) = Self::rates(&body)?;
        let rate = app.admin.saving(|doc| {
            let section = crate::store::base::Store::section(doc, "localPricing", &[]);
            section.insert("inputPer1M".to_string(), json!(input));
            section.insert("outputPer1M".to_string(), json!(output));
            Value::Object(section.clone())
        });
        h.ok(&json!({"ok": true, "rate": rate}));
        Ok(())
    }

    fn set_api_pricing(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        let model = Coerce::stripped(body.get("model"));
        if model.is_empty() {
            return Err(AppError::new("model required"));
        }
        let (input, output) = Self::rates(&body)?;
        let pricing = app.admin.saving(|doc| {
            let section = crate::store::base::Store::section(doc, "apiPricing", &[]);
            if input != 0.0 || output != 0.0 {
                section.insert(model.clone(), json!({"inputPer1M": input, "outputPer1M": output}));
            } else {
                section.shift_remove(&model);
            }
            Value::Object(section.clone())
        });
        h.ok(&json!({"ok": true, "pricing": pricing}));
        Ok(())
    }

    fn check_models(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        let result = CloudApi::of(app).check_account_models(&Coerce::stripped(body.get("id")))?;
        Asked::send_with_board(app, h, Asked::ok_with(result))
    }

    fn subscription_reset(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        h.ok(&SubscriptionResetDesk::of(app).consume(
            &Coerce::text(body.get("id")),
            body.get("creditId"),
            body.get("idempotencyKey"),
            body.get("confirmed"),
        )?);
        Ok(())
    }

    fn test_alias(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        let alias = PoolDesk::of(app).clone_test(&Coerce::text(body.get("id")))?;
        Asked::send_with_board(app, h, json!({"ok": true, "account": alias}))
    }

    fn save(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        let supplied = body.get("account").filter(|account| Coerce::truthy(Some(*account))).cloned().unwrap_or_else(|| json!({}));
        let account = CloudData::of(app).upsert_account(&supplied, app.now_whole())?;
        Asked::send_with_board(app, h, json!({"ok": true, "account": account}))
    }

    /// An account and the steps that name it go, then its sign-in at the provider ends; the answer says how that went when it had one.
    fn delete(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        let account_id = Coerce::stripped(body.get("id"));
        let account = CloudData::of(app).account(&account_id);
        let removed = PoolDesk::of(app).remove_account(&account_id)?;
        let sign_in = SignIn::of(app);
        sign_in.end_pending_of_removed(&account_id);
        let mut out = Map::new();
        out.insert("ok".to_string(), json!(true));
        let topology = Asked::board(app)?;
        let leaving = SignOut::of(app, account.as_ref(), removed.as_ref());
        out.insert("topology".to_string(), topology);
        if let Some(leaving) = leaving {
            let said = leaving.send();
            if Coerce::truthy(Some(&said)) {
                out.insert("signOut".to_string(), said);
            }
        }
        h.ok(&Value::Object(out));
        Ok(())
    }

    fn key(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        let result = CloudApi::of(app).set_account_key(body.get("id"), body.get("apiKey"))?;
        Asked::send_with_board(app, h, result)
    }

    fn key_delete(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        let vault = CloudData::of(app).vault();
        vault.delete(&Coerce::stripped(body.get("id"))).map_err(|error| AppError::with_status(error.to_string(), 500))?;
        Asked::send_with_board(app, h, json!({"ok": true}))
    }

    fn device_start(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        h.ok(&Asked::ok_with(SignIn::of(app).start_device_login(&Coerce::text(body.get("id")))?));
        Ok(())
    }

    fn health_retry(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        ModelCatalog::of(app).record_ok(&Coerce::text(body.get("key")));
        Asked::send_with_board(app, h, json!({"ok": true}))
    }
}
