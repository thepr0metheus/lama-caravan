//! The cloud accounts on the controller's files. A key is never in the board's document: the file of
//! accounts says what an account is, the file of secrets what opens it.

use super::board_providers::BoardProviders;
use super::call::{Fields, Upstream};
use super::catalog::ModelCatalog;
use super::oauth::{SignIn, SignOut};
use super::pools::PoolDesk;
use crate::app::App;
use crate::common::account_credit::AccountCredit;
use crate::common::cloud_pools::CloudPools;
use crate::common::cloud_sources::CloudSources;
use crate::common::misc::CloudFileKeys;
use files::CredentialVault;
use regex::Regex;
use rules::{AppError, Coerce};
use serde_json::{Map, Value, json};
use std::collections::{BTreeMap, BTreeSet};

mod reading;

/// The files of this controller.
pub struct CloudData<'app> {
    app: &'app App,
}

impl<'app> CloudData<'app> {
    const LEGACY_KEYS: [&'static str; 3] = ["blocks", "deletedModels", "sets"];
    const MIGRATION_CONTEXT_AUTO: &'static str = "contextAuto-2026-09";

    /// The files of `app`.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    fn objects_with_id(raw: Option<&Value>) -> Vec<Value> {
        let rows = raw.and_then(Value::as_array).into_iter().flatten();
        rows.filter(|row| row.is_object() && Coerce::truthy(row.get("id"))).cloned().collect()
    }

    /// `parsed`, a file in any of its forms, as accounts, pools, the subscription models' levels, the models added to Routing and the providers
    /// on the main board; and, in a file of the old form, its model blocks.
    pub fn parse(parsed: Option<&Value>) -> Value {
        let mut data = json!({"accounts": [], "pools": [], "migrations": []});
        let says = |key: &str| parsed.and_then(|parsed| parsed.get(key)).is_some();
        if says("accounts") || says("blocks") || says("pools") {
            let at = |key: &str| parsed.and_then(|parsed| parsed.get(key));
            Coerce::put(&mut data, "pools", Value::Array(Self::objects_with_id(at("pools"))));
            for (key, said) in CloudFileKeys::read(parsed) {
                Coerce::put(&mut data, &key, said);
            }
            let done = at("migrations").and_then(Value::as_array).into_iter().flatten();
            Coerce::put(&mut data, "migrations", Value::Array(done.filter(|row| row.is_string()).cloned().collect()));
            Coerce::put(&mut data, "accounts", Value::Array(Self::objects_with_id(at("accounts"))));
            if at("blocks").and_then(Value::as_array).is_some_and(|blocks| !blocks.is_empty()) {
                Coerce::put(&mut data, "blocks", Value::Array(Self::objects_with_id(at("blocks"))));
            }
            if let Some(deleted) = at("deletedModels").filter(|said| said.is_object() && Coerce::truthy(Some(*said))) {
                Coerce::put(&mut data, "deletedModels", deleted.clone());
            }
            if let Some(sets) = at("sets").filter(|said| said.is_array() && Coerce::truthy(Some(*said))) {
                Coerce::put(&mut data, "sets", sets.clone());
            }
            return data;
        }
        let legacy =
            if parsed.is_some_and(Value::is_object) { parsed.and_then(|parsed| parsed.get("providers")) } else { parsed };
        if let Some(rows) = legacy.and_then(Value::as_array) {
            Self::read_the_oldest(&mut data, rows);
        }
        data
    }

    /// The first form of the file: a provider was an account and a block at once.
    fn read_the_oldest(data: &mut Value, rows: &[Value]) {
        let (mut accounts, mut blocks) = (Vec::new(), Vec::new());
        for row in rows.iter().filter(|row| row.is_object() && Coerce::truthy(row.get("id"))) {
            let id = Coerce::str_of(row.get("id"));
            let word = |key: &str, otherwise: &str| {
                let said = Coerce::text(row.get(key));
                if said.is_empty() { otherwise.to_string() } else { said }
            };
            let account = format!("{id}-acct");
            accounts.push(json!({"id": account, "type": word("type", "openai"), "name": word("name", &id), "baseUrl": word("baseUrl", ""), "authMode": "apiKey"}));
            blocks.push(json!({"id": id, "accountId": account, "name": word("name", &id), "model": word("model", ""), "modelMode": word("modelMode", "rewrite")}));
        }
        Coerce::put(data, "accounts", Value::Array(accounts));
        Coerce::put(data, "blocks", Value::Array(blocks));
    }

    /// Accounts and pools, cached on the file's own (mtime, size).
    pub fn load(&self) -> Value {
        match self.app.cloud_file.read(&self.app.stamp()) {
            Some(parsed) => Self::parse(Some(&parsed)),
            None => json!({"accounts": [], "pools": [], "migrations": []}),
        }
    }

    /// The migrations `data` has been through, with `more`, as a save keeps them.
    pub fn with_migrations(data: &mut Value, more: &[&str]) {
        let rows = data.get("migrations").and_then(Value::as_array).into_iter().flatten();
        let mut all: BTreeSet<String> = rows.filter_map(Value::as_str).map(str::to_string).collect();
        all.extend(more.iter().map(|word| (*word).to_string()));
        Coerce::put(data, "migrations", json!(all));
    }

    /// The file, in the order a person reads it: what an account is first.
    pub fn save(&self, data: &Value) -> Result<(), AppError> {
        let mut migrations = json!({"migrations": data.get("migrations").cloned().unwrap_or_else(|| json!([]))});
        Self::with_migrations(&mut migrations, &[]);
        let mut out = Map::new();
        out.insert("accounts".to_string(), data.get("accounts").cloned().unwrap_or_else(|| json!([])));
        out.insert("pools".to_string(), data.get("pools").cloned().unwrap_or_else(|| json!([])));
        out.insert("migrations".to_string(), migrations.get("migrations").cloned().unwrap_or_else(|| json!([])));
        out.extend(CloudFileKeys::read(Some(data)));
        for key in Self::LEGACY_KEYS {
            if let Some(said) = data.get(key).filter(|said| Coerce::truthy(Some(*said))) {
                out.insert(key.to_string(), said.clone());
            }
        }
        self.app.cloud_file.write(&Value::Object(out)).map_err(|error| AppError::with_status(error.to_string(), 500))
    }

    /// Stamps `contextAuto` on the blocks that were living off the silent fallback, once; how many.
    pub fn migrate_context_auto(&self) -> Result<i64, AppError> {
        let mut data = self.load();
        let done = data.get("migrations").and_then(Value::as_array).into_iter().flatten();
        if done.filter_map(Value::as_str).any(|word| word == Self::MIGRATION_CONTEXT_AUTO) {
            return Ok(0);
        }
        let catalog = ModelCatalog::of(self.app);
        let mut windows: BTreeMap<String, Map<String, Value>> = BTreeMap::new();
        let mut changed = 0;
        for block in data.get_mut("blocks").and_then(Value::as_array_mut).into_iter().flatten() {
            if !block.is_object() || block.get("contextAuto").is_some() || Coerce::truthy(block.get("contextLength")) {
                continue;
            }
            let account = Coerce::text(block.get("accountId"));
            let known = windows.entry(account.clone()).or_insert_with(|| {
                let entry = catalog.cached_models_entry(&account);
                let rows = entry.as_ref().and_then(|entry| entry.get("models")).and_then(Value::as_array).into_iter().flatten();
                rows.map(|row| (Coerce::text(row.get("id")), row.get("contextLength").cloned().unwrap_or(Value::Null))).collect()
            });
            if Coerce::truthy(known.get(&Coerce::text(block.get("model")))) {
                Coerce::put(block, "contextAuto", json!(true));
                changed += 1;
            }
        }
        Self::with_migrations(&mut data, &[Self::MIGRATION_CONTEXT_AUTO]);
        self.save(&data)?;
        Ok(changed)
    }

    /// The keys, cached the same way.
    pub fn secrets(&self) -> Value {
        let read = self.app.secrets_file.read(&self.app.stamp());
        read.filter(|raw| raw.is_object()).map_or_else(|| json!({}), |raw| (*raw).clone())
    }

    /// The one writer of the keys.
    pub fn vault(&self) -> CredentialVault {
        CredentialVault::new(self.app.paths.provider_secrets_file.clone())
    }

    /// What opens an account: a test alias uses its original's.
    pub fn secret_entry(&self, account_id: &str) -> Value {
        let data = self.load();
        let sources = CloudSources::new(&data, None);
        let owner = sources.canonical(account_id).map_or_else(|| account_id.to_string(), |owner| Coerce::text(owner.get("id")));
        let secrets = self.secrets();
        match secrets.get(&owner) {
            Some(Value::String(key)) => json!({"apiKey": key}),
            Some(entry) if entry.is_object() => entry.clone(),
            _ => json!({}),
        }
    }

    fn word_or(raw: Option<&Value>, otherwise: Option<&Value>) -> String {
        let said = Coerce::stripped(raw);
        if said.is_empty() { Coerce::stripped(otherwise) } else { said }
    }

    /// An account as the file keeps it.
    pub fn normalize_account(&self, account: &Value, now: i64) -> Result<Value, AppError> {
        if !account.is_object() {
            return Err(AppError::new("account must be an object"));
        }
        let id = Coerce::stripped(account.get("id"));
        let good = Regex::new(r"^[A-Za-z0-9_-]{1,48}$").map_err(|error| AppError::with_status(error.to_string(), 500))?;
        if !good.is_match(&id) {
            return Err(AppError::new("account.id must be 1-48 chars [A-Za-z0-9_-]"));
        }
        let kind = {
            let said = Coerce::stripped(account.get("type"));
            if said.is_empty() { "openai".to_string() } else { said }
        };
        let empty = json!({});
        let preset = self.app.presets.get(&kind).unwrap_or(&empty);
        let name = {
            let said = Self::word_or(account.get("name"), preset.get("name"));
            if said.is_empty() { id.clone() } else { said }
        };
        let base_url = Self::word_or(account.get("baseUrl"), preset.get("baseUrl")).trim_end_matches('/').to_string();
        if !base_url.starts_with("http") {
            return Err(AppError::new("account.baseUrl must be http(s)"));
        }
        let account_type = Self::word_or(account.get("accountType"), preset.get("accountType"));
        let mut auth_modes: Vec<String> = match preset.get("authModes").and_then(Value::as_array) {
            Some(modes) => modes.iter().filter_map(Value::as_str).map(str::to_string).collect(),
            None => vec!["apiKey".to_string()],
        };
        let by_code = self.app.presets.device_login_preset(&account_type);
        if by_code.is_some() && !auth_modes.iter().any(|mode| mode == "oauth") {
            auth_modes.push("oauth".to_string());
        }
        let said_mode = Coerce::stripped(account.get("authMode"));
        // absent-ok: `auth_modes` always holds one: `apiKey` when the table names none.
        let auth_mode = if auth_modes.contains(&said_mode) { said_mode } else { auth_modes.first().cloned().unwrap_or_default() };
        let mut out = json!({"id": id, "type": kind, "name": name, "baseUrl": base_url, "authMode": auth_mode});
        if !account_type.is_empty() {
            Coerce::put(&mut out, "accountType", json!(account_type));
        }
        if auth_modes.iter().any(|mode| mode == "oauth") {
            let of_table = preset.get("oauth").or_else(|| by_code.and_then(|preset| preset.get("oauth")));
            let supplied = account.get("oauthConfig").filter(|said| said.is_object());
            let field = |key: &str| {
                let at = |source: Option<&Value>| source.and_then(|source| source.get(key)).cloned();
                Self::word_or(at(supplied).as_ref(), at(of_table).as_ref())
            };
            Coerce::put(&mut out, "oauthConfig", json!({"tokenUrl": field("tokenUrl"), "clientId": field("clientId")}));
        }
        if Coerce::truthy(account.get("testAliasOf")) {
            Coerce::put(&mut out, "testAliasOf", json!(Coerce::str_of(account.get("testAliasOf"))));
        }
        if auth_mode == "oauth" {
            if account.get("creditUsd").is_some() && AccountCredit::amount(account.get("creditUsd"))?.is_some() {
                return Err(AppError::new("a subscription has limits, not a dollar credit"));
            }
        } else if let Some(credit) = AccountCredit::resolve(account, now)? {
            Coerce::put(&mut out, "credit", credit);
        }
        Ok(out)
    }

    fn account_in<'data>(data: &'data Value, id: &str) -> Option<&'data Value> {
        let rows = data.get("accounts").and_then(Value::as_array).into_iter().flatten();
        rows.into_iter().find(|account| account.get("id").and_then(Value::as_str) == Some(id))
    }

    /// The account of an id, as the file holds it.
    pub fn account(&self, id: &str) -> Option<Value> {
        Self::account_in(&self.load(), id).cloned()
    }

    /// An account written, a new one's provider put on the board.
    pub fn upsert_account(&self, account: &Value, now: i64) -> Result<Value, AppError> {
        let mut data = self.load();
        let id = if account.is_object() { Coerce::stripped(account.get("id")) } else { String::new() };
        let previous = Self::account_in(&data, &id).filter(|_| !id.is_empty());
        let merged = match previous {
            Some(previous) => {
                let mut merged = Coerce::fields(previous);
                merged.extend(Coerce::fields(account));
                Value::Object(merged)
            }
            None => account.clone(),
        };
        let norm = self.normalize_account(&merged, now)?;
        let id = Coerce::text(norm.get("id"));
        if Coerce::truthy(norm.get("testAliasOf")) {
            let sources = CloudSources::new(&data, None);
            let owner = sources.canonical(&Coerce::text(norm.get("testAliasOf")));
            if !owner.is_some_and(CloudSources::is_subscription) || owner.is_some_and(|owner| Coerce::text(owner.get("id")) == id)
            {
                return Err(AppError::new("invalid test alias owner"));
            }
        }
        if let Some(rows) = data.get_mut("accounts").and_then(Value::as_array_mut) {
            rows.retain(|row| row.get("id").and_then(Value::as_str) != Some(id.as_str()));
            rows.push(norm.clone());
        }
        let mut providers = BoardProviders::new(&data);
        if providers.add(&BoardProviders::kind(&norm)) {
            Coerce::put(&mut data, "boardProviders", providers.stored());
        }
        self.save(&data)?;
        Ok(norm)
    }

    /// An account and the steps that name it deleted, then its sign-in ended at the provider.
    pub fn delete_account(&self, account_id: &str) -> Result<Option<Value>, AppError> {
        let id = Coerce::strip(account_id).to_string();
        let account = self.account(&id);
        let removed = PoolDesk::of(self.app).remove_account(&id)?;
        SignIn::of(self.app).end_pending_of_removed(&id);
        let leaving = SignOut::of(self.app, account.as_ref(), removed.as_ref());
        Ok(leaving.map(|leaving| leaving.send()))
    }

    /// The fields an account's request goes with.
    pub fn auth_fields(&self, account: &Value, secret: &Value) -> Fields {
        let empty = json!({});
        let preset = self.app.presets.get(&Coerce::text(account.get("type"))).unwrap_or(&empty);
        let extra = preset.get("extraHeaders").and_then(Value::as_object).into_iter().flatten();
        let mut fields: Fields = extra.map(|(name, value)| (name.clone(), Coerce::text(Some(value)))).collect();
        if account.get("authMode").and_then(Value::as_str) == Some("oauth") {
            let token = Coerce::text(secret.get("oauth").and_then(|oauth| oauth.get("accessToken")));
            if !token.is_empty() {
                fields.push(("Authorization".to_string(), format!("Bearer {token}")));
            }
        } else {
            let key = Coerce::text(secret.get("apiKey"));
            if !key.is_empty() {
                let name = preset.get("authHeader").and_then(Value::as_str).unwrap_or("Authorization");
                let prefix = preset.get("authPrefix").and_then(Value::as_str).unwrap_or("Bearer ");
                fields.push((name.to_string(), format!("{prefix}{key}")));
            }
        }
        Upstream::of(self.app).named(fields)
    }

    /// What the board may know of an account's credential: its kind and the last four letters of a key.
    pub fn credential_summary(&self, account_id: &str) -> Value {
        let id = Coerce::strip(account_id);
        let no_key = self.account(id).is_some_and(|account| Coerce::stripped(account.get("authMode")) == "noKey");
        if no_key {
            return json!({"hasCredential": true, "kind": "noKey", "last4": "", "oauthEmail": ""});
        }
        let entry = self.secret_entry(id);
        let oauth = entry.get("oauth").filter(|oauth| Coerce::truthy(Some(*oauth)));
        if let Some(oauth) = oauth.filter(|oauth| Coerce::truthy(oauth.get("accessToken"))) {
            return json!({"hasCredential": true, "kind": "oauth", "last4": "", "oauthEmail": Coerce::text(oauth.get("email"))});
        }
        let key = Coerce::text(entry.get("apiKey"));
        if key.is_empty() {
            return json!({"hasCredential": false, "kind": "", "last4": "", "oauthEmail": ""});
        }
        let letters: Vec<char> = key.chars().collect();
        let last4: String = letters.iter().skip(letters.len().saturating_sub(4)).collect();
        json!({"hasCredential": true, "kind": "apiKey", "last4": last4, "oauthEmail": ""})
    }

    /// Every account as the board shows it.
    pub fn accounts_state(&self) -> Value {
        let own = self.secrets();
        let data = self.load();
        let mut used: BTreeMap<String, Vec<Value>> = BTreeMap::new();
        let reading = CloudPools::new(&data, None);
        for pool in reading.all() {
            for step in pool.get("steps").and_then(Value::as_array).into_iter().flatten() {
                if step.get("kind").and_then(Value::as_str) == Some("account") {
                    used.entry(Coerce::text(step.get("accountId")))
                        .or_default()
                        .push(json!({"poolId": pool.get("id"), "poolName": pool.get("name"), "stepId": step.get("id")}));
                }
            }
        }
        let mut result = Vec::new();
        for (id, account) in reading.sources().accounts() {
            let summary = self.credential_summary(id);
            let credit = AccountCredit::kept(account.get("credit"));
            let credit_at = |key: &str| credit.as_ref().and_then(|credit| credit.get(key)).cloned().unwrap_or(Value::Null);
            let mode = Coerce::text(account.get("authMode"));
            let mut row = json!({
                "id": account.get("id"), "type": account.get("type"), "name": account.get("name"),
                "baseUrl": account.get("baseUrl"), "authMode": if mode.is_empty() { "apiKey".to_string() } else { mode },
                "accountType": Coerce::text(account.get("accountType")),
                "subscription": CloudSources::is_subscription(account),
                "plan": CloudSources::is_plan(account),
                "oauthConfig": account.get("oauthConfig").filter(|said| Coerce::truthy(Some(*said))).cloned().unwrap_or_else(|| json!({})),
                "hasCredential": summary.get("hasCredential"),
                "credentialKind": summary.get("kind"),
                "keyLast4": summary.get("last4"),
                "oauthEmail": summary.get("oauthEmail"),
                "deviceLogin": self.app.presets.device_login_spec(account).is_some_and(|spec| Coerce::truthy(Some(&spec))),
                "signOutOnDelete": SignOut::of(self.app, Some(account), own.get(id)).is_some(),
                // absent-ok: an account nothing was charged to has spent nothing.
                "usedIn": used.remove(id).unwrap_or_default(),
                "creditUsd": credit_at("amountUsd"),
                "creditAsOf": credit_at("asOf"),
            });
            if Coerce::truthy(account.get("testAliasOf")) {
                Coerce::put(&mut row, "testAliasOf", account.get("testAliasOf").cloned().unwrap_or(Value::Null));
            }
            result.push(row);
        }
        Value::Array(result)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_oldest_form_becomes_an_account_and_a_block() {
        let data = CloudData::parse(Some(&json!([{"id": "p", "type": "x", "model": "m"}, {"id": ""}, 5])));
        assert_eq!(data["accounts"][0]["id"], "p-acct");
        assert_eq!(data["blocks"][0]["accountId"], "p-acct");
        assert_eq!(data["blocks"][0]["modelMode"], "rewrite");
        assert_eq!(data["accounts"].as_array().unwrap().len(), 1);
    }

    #[test]
    fn what_a_file_keeps_is_read_with_its_shape() {
        let data = CloudData::parse(Some(&json!({
            "accounts": [{"id": "a"}, {"name": "no id"}], "pools": [{"id": "p"}, 5],
            "migrations": ["m", 5], "levels": {"a": {}}, "addedModels": {}, "sets": [],
        })));
        assert_eq!(data["accounts"], json!([{"id": "a"}]));
        assert_eq!(data["pools"], json!([{"id": "p"}]));
        assert_eq!(data["migrations"], json!(["m"]));
        assert_eq!(data["levels"], json!({"a": {}}));
        assert!(data.get("addedModels").is_none());
        assert!(data.get("sets").is_none());
    }
}
