//! The cloud providers on the main board, each a block of its accounts.

use super::data::CloudData;
use crate::app::App;
use crate::common::cloud_sources::CloudSources;
use rules::{AppError, Coerce};
use serde_json::{Value, json};
use std::collections::BTreeMap;

/// The providers of one reading of the file, and the rule that puts an account under one.
pub struct BoardProviders {
    kinds: Vec<String>,
}

impl BoardProviders {
    /// The reading of `data`.
    pub fn new(data: &Value) -> Self {
        let mut this = Self { kinds: Vec::new() };
        for kind in data.get("boardProviders").and_then(Value::as_array).into_iter().flatten() {
            this.add(&Coerce::stripped(Some(kind)));
        }
        this
    }

    /// The provider an account stands under.
    pub fn kind(account: &Value) -> String {
        if CloudSources::is_subscription(account) {
            return CloudSources::SUBSCRIPTION.to_string();
        }
        let said = Coerce::stripped(account.get("type"));
        if said.is_empty() { "custom".to_string() } else { said }
    }

    /// One put last; whether that changed anything.
    pub fn add(&mut self, kind: &str) -> bool {
        let kind = Coerce::strip(kind);
        if kind.is_empty() || self.kinds.iter().any(|held| held == kind) {
            return false;
        }
        self.kinds.push(kind.to_string());
        true
    }

    /// One taken off; whether that changed anything.
    pub fn remove(&mut self, kind: &str) -> bool {
        let kind = Coerce::strip(kind);
        let before = self.kinds.len();
        self.kinds.retain(|held| held != kind);
        before != self.kinds.len()
    }

    /// The shape the file keeps.
    pub fn stored(&self) -> Value {
        json!(self.kinds)
    }

    /// What the board draws: every provider with its accounts, one the list forgot last.
    pub fn shown<'accounts>(&self, accounts: impl Iterator<Item = &'accounts Value>) -> Value {
        let mut order = self.kinds.clone();
        let mut groups: BTreeMap<String, Vec<Value>> = order.iter().map(|kind| (kind.clone(), Vec::new())).collect();
        for account in accounts {
            let kind = Self::kind(account);
            if !groups.contains_key(&kind) {
                order.push(kind.clone());
            }
            groups.entry(kind).or_default().push(account.get("id").cloned().unwrap_or(Value::Null));
        }
        let rows: Vec<Value> = order.iter().map(|kind| json!({"kind": kind, "accounts": groups.get(kind)})).collect();
        Value::Array(rows)
    }
}

/// The providers on the controller's file.
pub struct ProviderDesk<'app> {
    app: &'app App,
}

impl<'app> ProviderDesk<'app> {
    const MIGRATION: &'static str = "board-providers-2026-10";

    /// The desk of `app`.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    /// Every provider on the board with its accounts, as the board draws them.
    pub fn state_of(data: &Value) -> Value {
        let sources = CloudSources::new(data, None);
        BoardProviders::new(data).shown(sources.accounts().values())
    }

    /// The same, of the file as it stands.
    pub fn state(&self) -> Value {
        Self::state_of(&CloudData::of(self.app).load())
    }

    /// A provider put on the board, last.
    pub fn add(&self, kind: &str) -> Result<Value, AppError> {
        let kind = Coerce::strip(kind);
        if self.app.presets.get(kind).is_none() {
            return Err(AppError::new(format!("unknown provider: {kind}")));
        }
        let cloud = CloudData::of(self.app);
        let mut data = cloud.load();
        let mut providers = BoardProviders::new(&data);
        if providers.add(kind) {
            Coerce::put(&mut data, "boardProviders", providers.stored());
            cloud.save(&data)?;
        }
        Ok(Self::state_of(&data))
    }

    /// A provider taken off the board while no account stands under it.
    pub fn remove(&self, kind: &str) -> Result<Value, AppError> {
        let kind = Coerce::strip(kind);
        let cloud = CloudData::of(self.app);
        let mut data = cloud.load();
        let held =
            CloudSources::new(&data, None).accounts().values().filter(|account| BoardProviders::kind(account) == kind).count();
        if held > 0 {
            return Err(AppError::with_status(format!("{kind}: {held} account(s) stand under it — delete them first"), 409));
        }
        let mut providers = BoardProviders::new(&data);
        if providers.remove(kind) {
            Coerce::put(&mut data, "boardProviders", providers.stored());
            cloud.save(&data)?;
        }
        Ok(Self::state_of(&data))
    }

    /// The providers of the accounts put on the board, once; what was added, or `None` when it was done before.
    pub fn migrate(&self) -> Result<Option<Value>, AppError> {
        let cloud = CloudData::of(self.app);
        let mut data = cloud.load();
        let done = data.get("migrations").and_then(Value::as_array).into_iter().flatten();
        if done.filter_map(Value::as_str).any(|word| word == Self::MIGRATION) {
            return Ok(None);
        }
        let mut providers = BoardProviders::new(&data);
        let mut added = Vec::new();
        for account in CloudSources::new(&data, None).accounts().values() {
            let kind = BoardProviders::kind(account);
            if providers.add(&kind) {
                added.push(kind);
            }
        }
        Coerce::put(&mut data, "boardProviders", providers.stored());
        CloudData::with_migrations(&mut data, &[Self::MIGRATION]);
        cloud.save(&data)?;
        Ok(Some(json!({"providers": added})))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn an_account_stands_under_its_type_a_subscription_under_its_own() {
        assert_eq!(BoardProviders::kind(&json!({"type": "deepseek"})), "deepseek");
        assert_eq!(BoardProviders::kind(&json!({})), "custom");
        assert_eq!(BoardProviders::kind(&json!({"type": "x", "baseUrl": "https://chatgpt.com/a"})), "openai-subscription");
    }

    #[test]
    fn the_board_draws_the_list_then_what_it_forgot() {
        let providers = BoardProviders::new(&json!({"boardProviders": ["kimi-code", "kimi-code", "  ", "openai"]}));
        let accounts = [json!({"id": "a", "type": "deepseek"}), json!({"id": "b", "type": "openai"})];
        assert_eq!(
            providers.shown(accounts.iter()),
            json!([{"kind": "kimi-code", "accounts": []}, {"kind": "openai", "accounts": ["b"]}, {"kind": "deepseek", "accounts": ["a"]}])
        );
    }
}
