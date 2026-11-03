//! Cloud identities, shared by the board and the proxy. An account owns a sign-in; a test alias owns a label, never another refresh token or quota; a pool owns its chain of steps, never credentials. The pools of the old form, a list of subscription members, are still read as sources while a file of that form is around.

use rules::Coerce;
use serde_json::{Map, Value, json};

/// The accounts and old pools of one reading of the file.
pub struct CloudSources {
    accounts: Map<String, Value>,
    pools: Map<String, Value>,
    secrets: Value,
}

impl CloudSources {
    /// A subscription's type.
    pub const SUBSCRIPTION: &'static str = "openai-subscription";
    /// An Anthropic key's type: the proxy speaks the Messages API to it.
    pub const ANTHROPIC: &'static str = "anthropic";
    /// DeepSeek's.
    pub const DEEPSEEK: &'static str = "deepseek";
    /// The subscriptions that come with a key of their own: a flat monthly price at an OpenAI-compatible address.
    pub const PLANS: [&'static str; 5] = ["kimi-code", "glm-coding", "minimax-plan", "qwen-token", "opencode-go"];
    /// The types whose every model chats and does nothing else, whatever it is called. Not qwen-token: that plan's models hear and speak too.
    pub const CHAT_ONLY: [&'static str; 6] = ["anthropic", "deepseek", "kimi-code", "glm-coding", "minimax-plan", "opencode-go"];

    /// The reading of `data`, with the keys in `secrets`.
    pub fn new(data: &Value, secrets: Option<&Value>) -> Self {
        let keyed = |name: &str, keep: &dyn Fn(&Value) -> bool| -> Map<String, Value> {
            let rows = data.get(name).and_then(Value::as_array).into_iter().flatten();
            rows.filter(|row| row.is_object() && Coerce::truthy(row.get("id")) && keep(row))
                .map(|row| (Coerce::text(row.get("id")), row.clone()))
                .collect()
        };
        Self {
            accounts: keyed("accounts", &|_| true),
            // Only the old form's pools stand where an account does; a pool of steps is no source of its own.
            pools: keyed("pools", &|pool| pool.get("members").is_some()),
            secrets: secrets.cloned().unwrap_or_else(|| json!({})),
        }
    }

    /// The accounts, by id, in the file's order.
    pub fn accounts(&self) -> &Map<String, Value> {
        &self.accounts
    }

    /// The old form's pools.
    pub fn old_pools(&self) -> &Map<String, Value> {
        &self.pools
    }

    /// Whether it signs in as a subscription.
    pub fn is_subscription(account: &Value) -> bool {
        Coerce::truthy(Some(account))
            && (account.get("accountType").and_then(Value::as_str) == Some(Self::SUBSCRIPTION)
                || Coerce::text(account.get("baseUrl")).contains("chatgpt.com"))
    }

    /// The jobs an account's type fixes for every model of it; `None` when the operator says them.
    pub fn fixed_jobs(account: &Value) -> Option<Value> {
        (Self::is_subscription(account) || Self::chats_only(account)).then(|| json!(["llm"]))
    }

    fn type_of(account: &Value) -> String {
        if Coerce::truthy(account.get("type")) { Coerce::text(account.get("type")) } else { String::new() }
    }

    /// Whether it is an Anthropic key.
    pub fn is_anthropic(account: &Value) -> bool {
        Self::type_of(account) == Self::ANTHROPIC
    }

    /// Whether it is a subscription with a key of its own.
    pub fn is_plan(account: &Value) -> bool {
        Self::PLANS.contains(&Self::type_of(account).as_str())
    }

    /// Whether its every model chats and does nothing else.
    pub fn chats_only(account: &Value) -> bool {
        Self::CHAT_ONLY.contains(&Self::type_of(account).as_str())
    }

    /// The account behind an id: an alias is its owner's; an alias of an alias, or of nothing, is no account.
    pub fn canonical(&self, account_id: &str) -> Option<&Value> {
        let account = self.accounts.get(account_id)?;
        if !Coerce::truthy(account.get("testAliasOf")) {
            return Some(account);
        }
        let owner = self.accounts.get(&Coerce::text(account.get("testAliasOf")))?;
        (!Coerce::truthy(owner.get("testAliasOf"))).then_some(owner)
    }

    fn identity(&self, account_id: &str) -> String {
        let token = self
            .secrets
            .get(account_id)
            .filter(|entry| entry.is_object())
            .and_then(|entry| entry.get("oauth"))
            .and_then(|oauth| oauth.get("accessToken"))
            .and_then(Value::as_str);
        // absent-ok: an account with no token has no identity to share a quota by.
        token.and_then(rules::Credentials::account_claim).unwrap_or_default()
    }

    /// Whose quota an account spends: the first subscription with the same sign-in, for quota deduplication: not OAuth verification, it never authorizes a request.
    pub fn quota_owner(&self, account_id: &str) -> Option<&Value> {
        let account = self.canonical(account_id)?;
        let key = self.identity(&Coerce::text(account.get("id")));
        if key.is_empty() {
            return Some(account);
        }
        let mut ids: Vec<&String> = self.accounts.keys().collect();
        ids.sort();
        let found = ids.into_iter().filter_map(|id| self.accounts.get(id)).find(|candidate| {
            !Coerce::truthy(candidate.get("testAliasOf"))
                && Self::is_subscription(candidate)
                && self.identity(&Coerce::text(candidate.get("id"))) == key
        });
        Some(found.unwrap_or(account))
    }

    /// What an id stands for as a source: an account with whose credentials and quota it speaks, or an old pool.
    pub fn source(&self, source_id: &str) -> Option<Value> {
        if let Some(account) = self.accounts.get(source_id) {
            let owner = self.canonical(source_id)?;
            let quota = self.quota_owner(source_id)?;
            // absent-ok: an account is an object: it was kept only as one
            let mut out = Coerce::fields(owner);
            let reserve =
                quota.get("usageReserve").filter(|reserve| Coerce::truthy(Some(*reserve))).cloned().unwrap_or_else(|| json!({}));
            out.insert("usageReserve".to_string(), reserve);
            out.insert("id".to_string(), account.get("id").cloned().unwrap_or(Value::Null));
            let name = if Coerce::truthy(account.get("name")) { account.get("name") } else { account.get("id") };
            out.insert("name".to_string(), name.cloned().unwrap_or(Value::Null));
            if Coerce::truthy(account.get("testAliasOf")) {
                out.insert("testAliasOf".to_string(), owner.get("id").cloned().unwrap_or(Value::Null));
            }
            out.insert("credentialAccountId".to_string(), owner.get("id").cloned().unwrap_or(Value::Null));
            out.insert("usageAccountId".to_string(), quota.get("id").cloned().unwrap_or(Value::Null));
            return Some(Value::Object(out));
        }
        let pool = self.pools.get(source_id)?;
        Some(
            json!({"id": pool.get("id"), "name": pool.get("name"), "type": Self::SUBSCRIPTION, "accountType": Self::SUBSCRIPTION, "baseUrl": "https://chatgpt.com/backend-api", "authMode": "oauth", "pool": pool, "isPool": true}),
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn data() -> Value {
        json!({"accounts": [
            {"id": "a", "accountType": "openai-subscription", "usageReserve": {"18000": 5}},
            {"id": "b", "testAliasOf": "a", "name": "alias"},
            {"id": "c", "testAliasOf": "b"},
            {"id": "k", "type": "anthropic"},
            {"id": "g", "type": "glm-coding"},
        ], "pools": [{"id": "old", "name": "Old", "members": []}, {"id": "new", "steps": []}]})
    }

    #[test]
    fn an_alias_speaks_with_its_owners_credentials() {
        let sources = CloudSources::new(&data(), None);
        let alias = sources.source("b").unwrap();
        assert_eq!(alias.get("name"), Some(&json!("alias")));
        assert_eq!(alias.get("credentialAccountId"), Some(&json!("a")));
        assert_eq!(alias.get("usageAccountId"), Some(&json!("a")));
        assert_eq!(alias.get("testAliasOf"), Some(&json!("a")));
        assert!(sources.source("c").is_none());
        assert_eq!(sources.source("old").unwrap().get("isPool"), Some(&json!(true)));
        assert!(sources.source("new").is_none());
    }

    #[test]
    fn a_type_says_what_an_account_is() {
        assert!(CloudSources::is_subscription(&json!({"baseUrl": "https://chatgpt.com/x"})));
        assert!(CloudSources::is_anthropic(&json!({"type": "anthropic"})));
        assert!(CloudSources::is_plan(&json!({"type": "glm-coding"})));
        assert!(CloudSources::chats_only(&json!({"type": "deepseek"})));
        assert!(!CloudSources::chats_only(&json!({"type": "qwen-token"})));
    }
}
