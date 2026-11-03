//! Live calls to the providers' APIs: a key tried, a list of models fetched, what the topology adds to its accounts.

use super::call::{Upstream, UpstreamFailure};
use super::catalog::ModelCatalog;
use super::data::CloudData;
use super::oauth::SignIn;
use super::subscription::{CatalogueEntry, SubscriptionAuth};
use crate::app::App;
use crate::common::cloud_sources::CloudSources;
use plumbing::http_client::HttpError;
use rules::{AppError, Coerce};
use serde_json::{Value, json};
use std::time::Duration;

/// The calls of this controller.
pub struct CloudApi<'app> {
    app: &'app App,
}

impl<'app> CloudApi<'app> {
    /// The calls of `app`.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    fn test_path(&self, account: &Value) -> Option<String> {
        let preset = self.app.presets.get(&Coerce::text(account.get("type")));
        match preset.and_then(|preset| preset.get("testPath")) {
            Some(Value::Null) => None,
            Some(path) => Some(Coerce::text(Some(path))),
            None => Some("/models".to_string()),
        }
    }

    fn base_of(account: &Value) -> String {
        Coerce::text(account.get("baseUrl")).trim_end_matches('/').to_string()
    }

    /// Whether a key opens its account's provider: an endpoint with nothing there says nothing against the key.
    pub fn test_account_key(&self, account: &Value, key: &str) -> Value {
        // A provider with no test path answers at its address: the same call Python makes with `None`, which raises and is said as an error.
        let Some(path) = self.test_path(account) else {
            return json!({"ok": false, "error": "this account's provider has no way to test a key"});
        };
        let url = format!("{}{path}", Self::base_of(account));
        let fields = CloudData::of(self.app).auth_fields(account, &json!({"apiKey": key}));
        let asked: Vec<(&str, String)> = fields.iter().map(|(name, value)| (name.as_str(), value.clone())).collect();
        match self.app.http.ask("GET", &url, &asked, &[], Duration::from_secs(8)) {
            Ok(answer) => json!({"ok": true, "status": answer.head.status}),
            Err(HttpError::Status(code @ (401 | 403), _)) => json!({"ok": false, "status": code, "error": "key rejected"}),
            Err(HttpError::Status(code @ (404 | 405), _)) => {
                json!({"ok": true, "status": code, "note": format!("validated (endpoint returned {code})")})
            }
            Err(HttpError::Status(code, _)) => json!({"ok": false, "status": code, "error": format!("HTTP {code}")}),
            Err(error) => json!({"ok": false, "error": error.to_string()}),
        }
    }

    /// An account's key tried, then kept.
    pub fn set_account_key(&self, account_id: Option<&Value>, key: Option<&Value>) -> Result<Value, AppError> {
        let account_id = Coerce::stripped(account_id);
        let cloud = CloudData::of(self.app);
        let account = cloud.account(&account_id).ok_or_else(|| AppError::with_status("unknown account", 404))?;
        let key = Coerce::stripped(key);
        if key.is_empty() {
            return Err(AppError::new("api key required"));
        }
        let result = self.test_account_key(&account, &key);
        if !Coerce::truthy(result.get("ok")) {
            return Ok(json!({"ok": false, "test": result}));
        }
        cloud.vault().put_api_key(&account_id, &key).map_err(|error| AppError::with_status(error.to_string(), 500))?;
        let letters: Vec<char> = key.chars().collect();
        let last4: String = letters.iter().skip(letters.len().saturating_sub(4)).collect();
        Ok(json!({"ok": true, "test": result, "last4": last4}))
    }

    pub(super) fn source(&self, account_id: &str) -> Result<Value, AppError> {
        let data = CloudData::of(self.app).load();
        CloudSources::new(&data, None).source(account_id).ok_or_else(|| AppError::with_status("unknown account", 404))
    }

    /// Models via `GET /models`, for any OpenAI-compatible account.
    pub fn fetch_account_models(&self, account_id: &str) -> Result<Vec<Value>, AppError> {
        let account = self.source(account_id)?;
        let empty = json!({});
        let preset = self.app.presets.get(&Coerce::text(account.get("type"))).unwrap_or(&empty);
        let path = self.test_path(&account).filter(|path| !path.is_empty());
        let path = path.ok_or_else(|| AppError::new("model listing not supported for this account type"))?;
        if account.get("authMode").and_then(Value::as_str) == Some("oauth") {
            SignIn::of(self.app).refresh_token(&account);
        }
        let cloud = CloudData::of(self.app);
        let mut fields = cloud.auth_fields(&account, &cloud.secret_entry(account_id));
        fields.push(("Accept".to_string(), "application/json".to_string()));
        let said = Coerce::text(preset.get("modelsUrl"));
        let url = if said.is_empty() { format!("{}{path}", Self::base_of(&account)) } else { said };
        let upstream = Upstream::of(self.app);
        let data = ModelCatalog::of(self.app).guarded(&format!("{account_id}:models"), || {
            upstream.json("GET", &url, &fields, &[], Duration::from_secs(10)).map_err(|error| match error {
                HttpError::Status(code, said) => {
                    let said: String = said.chars().take(200).collect();
                    UpstreamFailure::answered(AppError::with_status(format!("HTTP {code}: {said}"), 502))
                }
                other => UpstreamFailure {
                    network: other.is_silence(),
                    error: AppError::with_status(format!("failed to fetch models: {other}"), 502),
                },
            })
        })?;
        Ok(Self::models_of(&data))
    }

    /// The rows of a provider's list, in the shape any of them sends: `data`, `models`, or the list itself.
    fn models_of(data: &Value) -> Vec<Value> {
        let items = match data {
            Value::Object(_) => {
                let first = data.get("data").filter(|said| Coerce::truthy(Some(*said)));
                // absent-ok: a provider that lists no models under either key lists none.
                first.or_else(|| data.get("models")).and_then(Value::as_array).cloned().unwrap_or_default()
            }
            Value::Array(rows) => rows.clone(),
            _ => Vec::new(),
        };
        let mut models: Vec<Value> = items
            .iter()
            .filter(|row| row.is_object())
            .filter_map(|row| {
                let id =
                    ["id", "name", "model"].iter().filter_map(|key| row.get(*key)).find(|said| Coerce::truthy(Some(*said)))?;
                Some(CatalogueEntry::of(id, row.get("name"), row))
            })
            .collect();
        models.sort_by_key(|row| Coerce::text(row.get("id")).to_lowercase());
        models
    }

    /// A blocking fetch for the catalogue, breaker-guarded inside.
    pub fn refresh_account_models(&self, account_id: &str, account: Option<&Value>) -> Result<Vec<Value>, AppError> {
        let found;
        let account = match account {
            Some(account) => account,
            None => {
                found = self.source(account_id)?;
                &found
            }
        };
        if CloudSources::is_subscription(account) {
            SubscriptionAuth::of(self.app).models(account_id)
        } else {
            self.fetch_account_models(account_id)
        }
    }

    /// "↻ Check now": an account's list asked for and kept; how many chat, and how many do not.
    pub fn check_account_models(&self, account_id: &str) -> Result<Value, AppError> {
        let account = self.source(account_id)?;
        let models = self.refresh_account_models(account_id, Some(&account))?;
        ModelCatalog::of(self.app).store_models(account_id, &models);
        let chat = self.app.chat_models.of(&models).len();
        Ok(json!({"total": chat, "skipped": models.len() - chat}))
    }

    /// What the topology adds to its accounts and pools: when each list was checked, which rows name a model the provider no longer has, and a
    /// refresh of the lists that grew old.
    pub fn annotate_topology(&self, accounts: &mut [Value], pools: &mut [Value]) -> Value {
        let catalog = ModelCatalog::of(self.app);
        let data = CloudData::of(self.app).load();
        let sources = CloudSources::new(&data, None);
        for account in accounts.iter_mut() {
            let id = Coerce::text(account.get("id"));
            if id.is_empty() {
                continue;
            }
            let fetched = catalog
                .cached_models_entry(&id)
                .and_then(|entry| entry.get("fetchedAt").filter(|at| Coerce::truthy(Some(*at))).cloned());
            if let Some(at) = fetched.as_ref().and_then(Coerce::int) {
                Coerce::put(account, "modelsCheckedAt", json!(at));
            }
            if !Coerce::truthy(account.get("hasCredential")) || Coerce::truthy(account.get("testAliasOf")) {
                continue;
            }
            if catalog.models_stale(&id) && !catalog.endpoint_blocked(&format!("{id}:models")) {
                catalog.kick_refresh(&id);
            }
        }
        for pool in pools.iter_mut() {
            for step in pool.get_mut("steps").and_then(Value::as_array_mut).into_iter().flatten() {
                if step.get("kind").and_then(Value::as_str).is_some_and(|kind| kind != "account") {
                    continue;
                }
                let account = Coerce::text(step.get("accountId"));
                let owner = sources.canonical(&account).map_or(account.clone(), |owner| Coerce::text(owner.get("id")));
                let model = Coerce::text(step.get("model"));
                if !model.is_empty() && catalog.cached_model_ids(&owner).is_some_and(|ids| !ids.contains(&model)) {
                    Coerce::put(step, "unlisted", json!(true));
                }
            }
        }
        let (version, source) = catalog.codex_client_version();
        json!({"endpoints": catalog.endpoints_report(), "codexClientVersion": {"value": version, "source": source}})
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_list_comes_in_any_of_its_shapes() {
        let ids =
            |data: Value| -> Vec<String> { CloudApi::models_of(&data).iter().map(|row| Coerce::text(row.get("id"))).collect() };
        assert_eq!(ids(json!({"data": [{"id": "b"}, {"id": "A"}]})), ["A", "b"]);
        assert_eq!(ids(json!({"models": [{"name": "n"}, {"model": "m"}, 5, {}]})), ["m", "n"]);
        assert_eq!(ids(json!([{"id": "x"}])), ["x"]);
        assert!(ids(json!("x")).is_empty());
    }

    #[test]
    fn a_window_stated_by_the_provider_is_kept() {
        let row = CloudApi::models_of(&json!({"data": [{"id": "m", "context_length": 100}]})).remove(0);
        assert_eq!(row["contextLength"], 100);
        assert_eq!(row["name"], "m");
    }
}
