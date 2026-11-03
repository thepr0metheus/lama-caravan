//! Who the cloud accounts are and which of them can be called that says it.

use crate::coerce::Coerce;
use serde_json::Value;
use std::collections::BTreeMap;

/// An account of the cloud file, without anything secret: it keeps none.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct CloudAccount {
    /// Its id.
    pub id: String,
    kind: String,
    account_type: String,
    base_url: String,
    auth_mode: String,
    alias_of: String,
    token_url: String,
    client_id: String,
}

impl CloudAccount {
    const SUBSCRIPTION: &'static str = "openai-subscription";
    const ANTHROPIC: &'static str = "anthropic";
    /// The types whose every model chats and does nothing else: `CloudSources.CHAT_ONLY`.
    const CHAT_ONLY: [&'static str; 6] = [Self::ANTHROPIC, "deepseek", "kimi-code", "glm-coding", "minimax-plan", "opencode-go"];
    const NEEDS_NO_KEY: &'static str = "noKey";

    fn read(id: String, raw: &Value) -> Self {
        Self {
            id,
            kind: Coerce::text(raw.get("type")),
            account_type: Coerce::text(raw.get("accountType")),
            base_url: Coerce::text(raw.get("baseUrl")),
            auth_mode: Coerce::stripped(raw.get("authMode")),
            alias_of: Coerce::text(raw.get("testAliasOf")),
            token_url: Coerce::text(raw.get("oauthConfig").and_then(|config| config.get("tokenUrl"))),
            client_id: Coerce::text(raw.get("oauthConfig").and_then(|config| config.get("clientId"))),
        }
    }

    /// Whether its type is Anthropic's: the proxy speaks the Messages API to it.
    pub fn is_anthropic(&self) -> bool {
        self.kind == Self::ANTHROPIC
    }

    /// Whether it signs in to a subscription: `CloudSources.is_subscription`.
    pub fn is_subscription(&self) -> bool {
        self.account_type == Self::SUBSCRIPTION || self.base_url.contains("chatgpt.com")
    }

    /// Whether every model of its type chats and does nothing else: `CloudSources.chats_only`.
    pub fn chats_only(&self) -> bool {
        Self::CHAT_ONLY.contains(&self.kind.as_str())
    }
}

/// The accounts of one reading of the cloud file, in its order.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct CloudAccounts {
    accounts: Vec<CloudAccount>,
    /// An id that is not a clean word: Python files it under the raw value and finds it by text, which this does not repeat.
    unsure: bool,
}

impl CloudAccounts {
    /// The file's list. An account of an id already there takes its place, as a second key of a Python `dict` does.
    pub fn read(raw: Option<&Value>) -> Self {
        let mut read = Self::default();
        for item in raw.and_then(Value::as_array).into_iter().flatten() {
            if !item.is_object() || !Coerce::truthy(item.get("id")) {
                continue;
            }
            let id = item.get("id").and_then(Value::as_str).filter(|id| Coerce::strip(id) == *id);
            let Some(id) = id else {
                read.unsure = true;
                continue;
            };
            let account = CloudAccount::read(id.to_string(), item);
            match read.accounts.iter_mut().find(|kept| kept.id == account.id) {
                Some(kept) => *kept = account,
                None => read.accounts.push(account),
            }
        }
        read
    }

    /// Whether the reading has something it cannot answer for.
    pub fn unsure(&self) -> bool {
        self.unsure
    }

    /// The accounts, in the file's order.
    pub fn iter(&self) -> impl Iterator<Item = &CloudAccount> {
        self.accounts.iter()
    }

    /// The account of `id`.
    pub fn get(&self, id: &str) -> Option<&CloudAccount> {
        self.accounts.iter().find(|account| account.id == id)
    }

    /// The account that owns the sign-in of `id`: itself, or its original for a test's alias. An alias of an alias, or of an account
    /// gone, has none.
    pub fn canonical(&self, id: &str) -> Option<&CloudAccount> {
        let account = self.get(id)?;
        if account.alias_of.is_empty() {
            return Some(account);
        }
        self.get(&account.alias_of).filter(|owner| owner.alias_of.is_empty())
    }

    /// The account whose limits `id` is held by: the first in order of the subscriptions signed in as the same person, or its own.
    /// `CloudSources.quota_owner`.
    fn quota_owner(&self, id: &str, credentials: &Credentials) -> Option<&CloudAccount> {
        let account = self.canonical(id)?;
        let Some(identity) = credentials.identity(&account.id) else {
            return Some(account);
        };
        let mut same: Vec<&CloudAccount> = self
            .accounts
            .iter()
            .filter(|candidate| {
                candidate.alias_of.is_empty()
                    && candidate.is_subscription()
                    && credentials.identity(&candidate.id) == Some(identity)
            })
            .collect();
        same.sort_by(|left, right| left.id.cmp(&right.id));
        Some(same.first().copied().unwrap_or(account))
    }

    /// One account as a row of a pool goes to it: `load_cloud_account`. `None`: no such account, or an alias of nothing.
    pub fn provider(&self, id: &str, credentials: &Credentials) -> Option<CloudProvider> {
        let owner = self.canonical(id)?;
        let quota = self.quota_owner(id, credentials)?;
        Some(CloudProvider {
            account_id: id.to_string(),
            credential_account_id: owner.id.clone(),
            usage_account_id: quota.id.clone(),
            kind: if owner.kind.is_empty() { "openai".to_string() } else { owner.kind.clone() },
            subscription: owner.is_subscription(),
            anthropic: owner.is_anthropic(),
            base_url: owner.base_url.clone(),
            oauth: owner.auth_mode == "oauth",
            token_url: owner.token_url.clone(),
            client_id: owner.client_id.clone(),
        })
    }

    /// Whether an account can be called: one that needs no key, or one whose credential is kept. `LiveModels.signed_in`.
    pub fn signed_in(&self, id: &str, credentials: &Credentials) -> bool {
        self.canonical(id).is_some_and(|owner| owner.auth_mode == CloudAccount::NEEDS_NO_KEY || credentials.has(&owner.id))
    }
}

/// A row's account as the proxy goes to it.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CloudProvider {
    /// The account the row names.
    pub account_id: String,
    /// The account whose credential opens it: its original, for a test's alias.
    pub credential_account_id: String,
    /// The account whose limits hold it.
    pub usage_account_id: String,
    /// Its type, "openai" when it says none.
    pub kind: String,
    /// Whether it signs in to a ChatGPT subscription.
    pub subscription: bool,
    /// Whether it speaks Anthropic's Messages API.
    pub anthropic: bool,
    /// Its address.
    pub base_url: String,
    /// Whether it signs in with OAuth.
    pub oauth: bool,
    /// Where an OAuth token is renewed.
    pub token_url: String,
    /// Whose renewal it is.
    pub client_id: String,
}

impl CloudProvider {
    /// The field a key goes in, and what goes before the key: `CLOUD_PROVIDER_AUTH`.
    pub fn key_field(&self) -> (&'static str, &'static str) {
        if self.kind == "anthropic" { ("x-api-key", "") } else { ("Authorization", "Bearer ") }
    }

    /// The fields an account's type always sends.
    pub fn extra_fields(&self) -> &'static [(&'static str, &'static str)] {
        if self.kind == "anthropic" { &[("anthropic-version", "2023-06-01")] } else { &[] }
    }
}

/// Who has a credential kept, and who a sign-in's token says they are, and nothing else of the credentials: what is sent to a provider is
/// read from the file when it is sent, and what this reading does not hold it cannot leak.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Credentials {
    /// Each account with one, and the identity its token claims, when it claims one.
    kept: BTreeMap<String, Option<String>>,
    /// A document that does not read: nothing can be said of it to a client.
    unsure: bool,
}

impl Credentials {
    /// The credential document; `None` for one that does not read. No document at all is the caller's to read as an empty one.
    pub fn read(raw: Option<&Value>) -> Self {
        let Some(fields) = raw.and_then(Value::as_object) else {
            return Self { kept: BTreeMap::new(), unsure: true };
        };
        let mut read = Self::default();
        for (account, entry) in fields {
            match Self::holds(entry) {
                Some(true) => {
                    read.kept.insert(account.clone(), Self::token_of(entry).and_then(Self::account_claim));
                }
                Some(false) => {}
                None => read.unsure = true,
            }
        }
        read
    }

    /// Whether an entry holds a key or a token; `None` where Python raises.
    fn holds(entry: &Value) -> Option<bool> {
        match entry {
            Value::String(text) => Some(!Coerce::strip(text).is_empty()),
            Value::Object(fields) => {
                if Coerce::truthy(fields.get("apiKey")) {
                    return Some(true);
                }
                match fields.get("oauth").filter(|oauth| Coerce::truthy(Some(*oauth))) {
                    None => Some(false),
                    Some(Value::Object(oauth)) => Some(Coerce::truthy(oauth.get("accessToken"))),
                    Some(_) => None,
                }
            }
            _ => Some(false),
        }
    }

    fn token_of(entry: &Value) -> Option<&str> {
        entry.get("oauth")?.get("accessToken")?.as_str()
    }

    /// The ChatGPT account a token's claims name: compared for quota, and sent with a request to its own backend. Never an authorization:
    /// the token's signature is its provider's to check. `_extract_chatgpt_account_id`.
    pub fn account_claim(token: &str) -> Option<String> {
        let payload = token.split('.').nth(1)?;
        let claims: Value = serde_json::from_slice(&Self::base64_url(payload)).ok()?;
        let claim = claims.get("https://api.openai.com/auth")?.get("chatgpt_account_id")?.as_str()?;
        (!claim.is_empty()).then(|| claim.to_string())
    }

    /// `urlsafe_b64decode`, the padding optional and what is no letter of its alphabet left out.
    fn base64_url(text: &str) -> Vec<u8> {
        let mut out = Vec::with_capacity(text.len() * 3 / 4);
        let (mut held, mut bits) = (0u32, 0u32);
        for letter in text.bytes() {
            let value = match letter {
                b'A'..=b'Z' => letter - b'A',
                b'a'..=b'z' => letter - b'a' + 26,
                b'0'..=b'9' => letter - b'0' + 52,
                b'-' => 62,
                b'_' => 63,
                _ => continue,
            };
            held = (held << 6) | u32::from(value);
            bits += 6;
            if bits >= 8 {
                bits -= 8;
                out.push((held >> bits) as u8);
            }
        }
        out
    }

    /// Whether the reading has something it cannot answer for.
    pub fn unsure(&self) -> bool {
        self.unsure
    }

    /// Whether `account` has a credential.
    pub fn has(&self, account: &str) -> bool {
        self.kept.contains_key(account)
    }

    /// Who `account`'s token says it is.
    fn identity(&self, account: &str) -> Option<&str> {
        self.kept.get(account)?.as_deref()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn a_provider_says_whether_it_signs_in() {
        let accounts =
            CloudAccounts::read(Some(&json!([{"id": "sub", "authMode": "oauth"}, {"id": "key", "authMode": "apiKey"}])));
        let credentials = Credentials::default();
        assert!(accounts.provider("sub", &credentials).unwrap().oauth);
        assert!(!accounts.provider("key", &credentials).unwrap().oauth);
    }

    #[test]
    fn a_second_account_of_one_id_takes_the_first_one_s_place() {
        let accounts =
            CloudAccounts::read(Some(&json!([{"id": "a", "type": "x"}, {"id": "b"}, {"id": "a", "type": "anthropic"}])));
        assert_eq!(accounts.iter().map(|account| account.id.as_str()).collect::<Vec<_>>(), ["a", "b"]);
        assert!(accounts.get("a").unwrap().chats_only());
    }

    #[test]
    fn an_id_python_files_under_something_else_is_a_doubt() {
        for odd in [json!({"id": 5}), json!({"id": " a"}), json!({"id": true})] {
            assert!(CloudAccounts::read(Some(&json!([odd.clone()]))).unsure(), "{odd}");
        }
        for skipped in [json!("a"), json!({"id": ""}), json!({"id": 0}), json!({})] {
            let accounts = CloudAccounts::read(Some(&json!([skipped.clone()])));
            assert!(!accounts.unsure() && accounts.iter().next().is_none(), "{skipped}");
        }
    }

    #[test]
    fn a_credential_document_python_raises_at_is_a_doubt() {
        assert!(Credentials::read(None).unsure());
        assert!(Credentials::read(Some(&json!([]))).unsure());
        assert!(Credentials::read(Some(&json!({"a": {"oauth": "text"}}))).unsure());
        assert!(!Credentials::read(Some(&json!({"a": {"oauth": {}}, "b": 5, "c": null}))).unsure());
    }

    #[test]
    fn it_keeps_no_more_than_who_has_one() {
        let credentials = Credentials::read(Some(&json!({
            "key": {"apiKey": "k"}, "token": {"oauth": {"accessToken": "t"}}, "text": "k", "blank": "  ",
            "empty": {"apiKey": ""}, "spent": {"oauth": {"accessToken": ""}}, "number": 5,
        })));
        assert_eq!(credentials.kept.keys().map(String::as_str).collect::<Vec<_>>(), ["key", "text", "token"]);
    }

    /// A token with these claims, unsigned: only the middle part is ever read.
    fn token(claims: &Value) -> String {
        let text = claims.to_string();
        let mut encoded = String::new();
        for chunk in text.as_bytes().chunks(3) {
            let at = |index: usize| u32::from(chunk.get(index).copied().unwrap_or(0));
            let all = (at(0) << 16) | (at(1) << 8) | at(2);
            let alphabet = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
            for position in 0..=chunk.len() {
                let index = (all >> (18 - position * 6)) & 63;
                encoded.push(char::from(alphabet[index as usize]));
            }
        }
        format!("head.{encoded}.signature")
    }

    #[test]
    fn a_token_names_its_account_when_it_can() {
        let good = token(&json!({"https://api.openai.com/auth": {"chatgpt_account_id": "chat-1"}}));
        assert_eq!(Credentials::account_claim(&good).as_deref(), Some("chat-1"));
        for odd in [
            token(&json!({"https://api.openai.com/auth": {"chatgpt_account_id": ""}})),
            token(&json!({"https://api.openai.com/auth": {}})),
            token(&json!({})),
            "no-dots".to_string(),
            "a.%%%.c".to_string(),
        ] {
            assert_eq!(Credentials::account_claim(&odd), None, "{odd}");
        }
    }

    #[test]
    fn two_subscriptions_of_one_person_share_a_quota_owner() {
        let sign_in = |claim: &str| json!({"oauth": {"accessToken": token(&json!({"https://api.openai.com/auth": {"chatgpt_account_id": claim}}))}});
        let credentials = Credentials::read(Some(
            &json!({"zed": sign_in("same"), "bob": sign_in("same"), "other": sign_in("else"), "key": {"apiKey": "k"}}),
        ));
        let subscription = |id: &str| json!({"id": id, "accountType": "openai-subscription"});
        let accounts = CloudAccounts::read(Some(
            &json!([subscription("zed"), subscription("bob"), subscription("other"), {"id": "key", "type": "anthropic"}, {"id": "copy", "testAliasOf": "zed"}]),
        ));
        let usage_of = |id: &str| accounts.provider(id, &credentials).unwrap().usage_account_id;
        assert_eq!(usage_of("zed"), "bob");
        assert_eq!(usage_of("bob"), "bob");
        assert_eq!(usage_of("other"), "other");
        assert_eq!(usage_of("key"), "key");
        assert_eq!(usage_of("copy"), "bob");
        let copy = accounts.provider("copy", &credentials).unwrap();
        assert_eq!((copy.account_id.as_str(), copy.credential_account_id.as_str()), ("copy", "zed"));
        assert!(copy.subscription);
        let key = accounts.provider("key", &credentials).unwrap();
        assert_eq!((key.kind.as_str(), key.anthropic, key.key_field()), ("anthropic", true, ("x-api-key", "")));
        assert!(accounts.provider("nobody", &credentials).is_none());
    }
}
