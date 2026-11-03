//! What opens a provider, read when it is sent, and an OAuth token renewed.
//!
//! Refresh tokens rotate: letting two processes renew one at once destroys the other's copy. Per-account file locks serialize a renewal, and a
//! short document lock merges writes for unrelated accounts, with the same locks in either language. Every write re-reads the document under
//! that lock: a writer that read it, changed one entry and wrote it all back without the lock put a spent refresh token back whenever a
//! renewal landed in between, and the subscription needed a new login.

use crate::atomic::AtomicFile;
use os::FileLock;
use rules::{CloudProvider, Coerce, PythonJson};
use serde_json::{Map, Value, json};
use std::fs;
use std::io;
use std::path::{Path, PathBuf};

/// A field to send: its name and its value.
pub type AuthField = (String, String);

/// What asks for a new token: it gets the address and the form, and what comes back is the provider's JSON.
pub type TokenRequest<'a> = &'a dyn Fn(&str, &[(&str, &str)]) -> io::Result<Value>;

/// The credential document.
#[derive(Debug, Clone)]
pub struct CredentialVault {
    path: PathBuf,
}

impl CredentialVault {
    /// A token this near its end is renewed before it goes.
    const RENEW_WITHIN: i64 = 60;

    /// The document at `path`.
    pub fn new(path: PathBuf) -> Self {
        Self { path }
    }

    fn lock_path(path: &Path, suffix: &str) -> PathBuf {
        let name = path.file_name().map_or_else(String::new, |name| name.to_string_lossy().into_owned());
        path.with_file_name(format!("{name}{suffix}.lock"))
    }

    fn document(&self) -> Option<Map<String, Value>> {
        match serde_json::from_slice::<Value>(&fs::read(&self.path).ok()?).ok()? {
            Value::Object(fields) => Some(fields),
            _ => None,
        }
    }

    /// The field `provider`'s request goes with; `None` for no usable credential. `renew` asks for a new token: it gets the address and the
    /// form, and what comes back is the provider's JSON. A credential that expired and cannot be renewed is no working sign-in.
    pub fn field_for(&self, provider: &CloudProvider, now: i64, renew: TokenRequest<'_>) -> Option<AuthField> {
        let entry = self.document()?.get(&provider.credential_account_id)?.clone();
        if provider.oauth {
            return self.oauth_field(provider, &entry, now, renew);
        }
        let key = match &entry {
            Value::String(key) => key.clone(),
            Value::Object(_) => Coerce::text(entry.get("apiKey")),
            _ => String::new(),
        };
        if key.is_empty() {
            return None;
        }
        let (field, prefix) = provider.key_field();
        Some((field.to_string(), format!("{prefix}{key}")))
    }

    fn oauth_field(&self, provider: &CloudProvider, entry: &Value, now: i64, renew: TokenRequest<'_>) -> Option<AuthField> {
        let oauth = entry.get("oauth").filter(|oauth| oauth.is_object())?;
        let mut token = Coerce::text(oauth.get("accessToken"));
        // absent-ok: `int(oauth.get("expiresAt") or 0)`: a token that names no end does not expire.
        let expires = Coerce::int_or_zero(oauth.get("expiresAt")).unwrap_or(0);
        if !token.is_empty() && expires != 0 && expires - now < Self::RENEW_WITHIN {
            let renewed = self.renewed(provider, now, renew).ok()?;
            if !renewed.is_empty() {
                token = renewed;
            }
        }
        (!token.is_empty()).then(|| ("Authorization".to_string(), format!("Bearer {token}")))
    }

    /// The account's token after a renewal, under the account's lock: another process may have renewed it while this one waited, and then
    /// nothing is asked. The refresh token a provider rotates is kept before anyone else can read the old one.
    fn renewed(&self, provider: &CloudProvider, now: i64, renew: TokenRequest<'_>) -> io::Result<String> {
        let account = &provider.credential_account_id;
        let _held = FileLock::exclusive(&Self::lock_path(&self.path, &format!(".{account}")))?;
        let mut oauth = self.oauth_of(account);
        // absent-ok: a token that names no end does not expire.
        let expires = Coerce::int_or_zero(oauth.get("expiresAt")).unwrap_or(0);
        let refresh = Coerce::text(oauth.get("refreshToken"));
        if expires == 0 || expires - now >= Self::RENEW_WITHIN || refresh.is_empty() || provider.token_url.is_empty() {
            return Ok(Coerce::text(oauth.get("accessToken")));
        }
        let form =
            [("grant_type", "refresh_token"), ("refresh_token", refresh.as_str()), ("client_id", provider.client_id.as_str())];
        let tokens = renew(&provider.token_url, &form)?;
        let access = Coerce::text(tokens.get("access_token"));
        if access.is_empty() {
            return Err(io::Error::new(io::ErrorKind::InvalidData, "the renewal returned no access token"));
        }
        oauth.insert("accessToken".to_string(), json!(access));
        let new_refresh = Coerce::text(tokens.get("refresh_token"));
        oauth.insert("refreshToken".to_string(), json!(if new_refresh.is_empty() { refresh } else { new_refresh }));
        oauth.insert("obtainedAt".to_string(), json!(now));
        if let Some(lasts) = tokens.get("expires_in").filter(|lasts| Coerce::truthy(Some(*lasts))).and_then(Coerce::int) {
            oauth.insert("expiresAt".to_string(), json!(now + lasts));
        }
        self.put_oauth(account, oauth)?;
        Ok(access)
    }

    fn oauth_of(&self, account: &str) -> Map<String, Value> {
        let entry = self.document().and_then(|mut document| document.remove(account));
        // absent-ok: an account with no sign-in has nothing to renew, and an empty map says so to the caller.
        entry.and_then(|entry| entry.get("oauth").and_then(Value::as_object).cloned()).unwrap_or_default()
    }

    /// One account's tokens written, every other entry as the file holds them at this moment.
    fn put_oauth(&self, account: &str, oauth: Map<String, Value>) -> io::Result<()> {
        self.put_field(account, "oauth", Value::Object(oauth))
    }

    fn put_field(&self, account: &str, field: &str, value: Value) -> io::Result<()> {
        let _held = FileLock::exclusive(&Self::lock_path(&self.path, ".write"))?;
        // absent-ok: a document gone since the read has this one entry to hold now.
        let mut document = self.document().unwrap_or_default();
        let entry = document.entry(account.to_string()).or_insert_with(|| Value::Object(Map::new()));
        if !entry.is_object() {
            *entry = Value::Object(Map::new());
        }
        if let Some(fields) = entry.as_object_mut() {
            fields.insert(field.to_string(), value);
        }
        self.write_document(document)
    }

    fn write_document(&self, document: Map<String, Value>) -> io::Result<()> {
        let text = PythonJson::indented_letters(&Value::Object(document));
        if let Some(parent) = self.path.parent() {
            fs::create_dir_all(parent)?;
        }
        AtomicFile::write_private(&self.path, format!("{text}\n").as_bytes())
    }

    /// The tokens a sign-in just took, under the account's lock: a renewal in another process waits for them.
    pub fn take_oauth(&self, account: &str, oauth: Map<String, Value>) -> io::Result<()> {
        let _held = FileLock::exclusive(&Self::lock_path(&self.path, &format!(".{account}")))?;
        self.put_oauth(account, oauth)
    }

    /// One account's API key set.
    pub fn put_api_key(&self, account: &str, key: &str) -> io::Result<()> {
        self.put_field(account, "apiKey", json!(key))
    }

    /// A whole document written (a settings restore) under the document lock.
    pub fn replace(&self, document: Map<String, Value>) -> io::Result<()> {
        let _held = FileLock::exclusive(&Self::lock_path(&self.path, ".write"))?;
        self.write_document(document)
    }

    /// This registration removed, never another login of its identity; what it held, or `None` when it held nothing.
    pub fn delete(&self, account: &str) -> io::Result<Option<Value>> {
        let _renewal = FileLock::exclusive(&Self::lock_path(&self.path, &format!(".{account}")))?;
        let _held = FileLock::exclusive(&Self::lock_path(&self.path, ".write"))?;
        let Some(mut document) = self.document() else {
            return Ok(None);
        };
        let removed = document.remove(account);
        if removed.is_some() {
            self.write_document(document)?;
        }
        Ok(removed)
    }

    /// The account's sign-in, renewed first when it is about to end (or always, when `force`). `token_url` empty, or a sign-in with no refresh
    /// token, cannot be renewed: what is kept is the answer.
    pub fn oauth(
        &self,
        account: &str,
        config: (&str, &str),
        force: bool,
        now: i64,
        renew: TokenRequest<'_>,
    ) -> io::Result<Map<String, Value>> {
        let (token_url, client_id) = config;
        let _held = FileLock::exclusive(&Self::lock_path(&self.path, &format!(".{account}")))?;
        let mut oauth = self.oauth_of(account);
        // absent-ok: a token that names no end does not expire.
        let expires = Coerce::int_or_zero(oauth.get("expiresAt")).unwrap_or(0);
        let refresh = Coerce::text(oauth.get("refreshToken"));
        if !force && (expires == 0 || expires - now >= Self::RENEW_WITHIN) {
            return Ok(oauth);
        }
        if refresh.is_empty() || token_url.is_empty() {
            return Ok(oauth);
        }
        let form = [("grant_type", "refresh_token"), ("refresh_token", refresh.as_str()), ("client_id", client_id)];
        let tokens = renew(token_url, &form)?;
        let access = Coerce::text(tokens.get("access_token"));
        if access.is_empty() {
            return Err(io::Error::new(io::ErrorKind::InvalidData, "OAuth renewal returned no access token"));
        }
        oauth.insert("accessToken".to_string(), json!(access));
        let new_refresh = Coerce::text(tokens.get("refresh_token"));
        oauth.insert("refreshToken".to_string(), json!(if new_refresh.is_empty() { refresh } else { new_refresh }));
        oauth.insert("obtainedAt".to_string(), json!(now));
        if let Some(lasts) = tokens.get("expires_in").filter(|lasts| Coerce::truthy(Some(*lasts))).and_then(Coerce::int) {
            oauth.insert("expiresAt".to_string(), json!(now + lasts));
        }
        self.put_oauth(account, oauth.clone())?;
        Ok(oauth)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use rules::{CloudAccounts, Credentials};
    use std::cell::Cell;
    use std::os::unix::fs::PermissionsExt;

    struct Place {
        folder: PathBuf,
        vault: CredentialVault,
    }

    impl Place {
        fn new(name: &str, document: &Value) -> Self {
            let folder = std::env::temp_dir().join(format!("caravan-vault-{name}-{}", std::process::id()));
            fs::create_dir_all(&folder).unwrap();
            let path = folder.join("provider-secrets.json");
            fs::write(&path, document.to_string()).unwrap();
            Self { folder, vault: CredentialVault::new(path) }
        }

        fn written(&self) -> Value {
            serde_json::from_slice(&fs::read(self.folder.join("provider-secrets.json")).unwrap()).unwrap()
        }
    }

    impl Drop for Place {
        fn drop(&mut self) {
            fs::remove_dir_all(&self.folder).unwrap();
        }
    }

    fn provider(account: Value) -> CloudProvider {
        let id = account["id"].as_str().unwrap().to_string();
        CloudAccounts::read(Some(&json!([account]))).provider(&id, &Credentials::default()).unwrap()
    }

    fn no_renewal(_: &str, _: &[(&str, &str)]) -> io::Result<Value> {
        panic!("nothing should be renewed here");
    }

    const NOW: i64 = 1_000_000;

    #[test]
    fn a_key_goes_in_the_field_its_type_names() {
        let place =
            Place::new("keys", &json!({"open": {"apiKey": "k1"}, "text": "k2", "anth": {"apiKey": "k3"}, "none": {}, "odd": 5}));
        let field = |account: Value| place.vault.field_for(&provider(account), NOW, &no_renewal);
        assert_eq!(field(json!({"id": "open", "type": "openai"})), Some(("Authorization".to_string(), "Bearer k1".to_string())));
        assert_eq!(field(json!({"id": "text"})), Some(("Authorization".to_string(), "Bearer k2".to_string())));
        assert_eq!(field(json!({"id": "anth", "type": "anthropic"})), Some(("x-api-key".to_string(), "k3".to_string())));
        assert_eq!(field(json!({"id": "none"})), None);
        assert_eq!(field(json!({"id": "odd"})), None);
        assert_eq!(field(json!({"id": "nobody"})), None);
    }

    fn signed_in() -> Value {
        json!({"id": "sub", "authMode": "oauth", "accountType": "openai-subscription", "oauthConfig": {"tokenUrl": "https://auth/token", "clientId": "app"}})
    }

    /// A sign-in whose token ends at `expires`, and the provider that answers a renewal.
    fn with_end(name: &str, expires: i64) -> Place {
        Place::new(name, &json!({"acc": {"oauth": {"accessToken": "old", "refreshToken": "refresh", "expiresAt": expires}}}))
    }

    fn renewing(asked: &Cell<u32>) -> impl Fn(&str, &[(&str, &str)]) -> io::Result<Value> + '_ {
        move |_, _| {
            asked.set(asked.get() + 1);
            Ok(json!({"access_token": "new"}))
        }
    }

    fn signed_in_provider() -> CloudProvider {
        provider(
            json!({"id": "acc", "type": "openai-subscription", "accountType": "openai-subscription", "authMode": "oauth", "oauthConfig": {"tokenUrl": "https://t/x", "clientId": "c"}}),
        )
    }

    #[test]
    fn a_token_is_renewed_inside_the_window_and_not_at_its_edge() {
        let within = CredentialVault::RENEW_WITHIN;
        for (name, left, renewed) in [("edge", within, false), ("inside", within - 1, true), ("far", within * 1000, false)] {
            let temp = with_end(name, NOW + left);
            let asked = Cell::new(0);
            let said = temp.vault.field_for(&signed_in_provider(), NOW, &renewing(&asked));
            let token = if renewed { "Bearer new" } else { "Bearer old" };
            assert_eq!(said.map(|field| field.1), Some(token.to_string()), "{name}");
            assert_eq!(asked.get(), u32::from(renewed), "{name}");
        }
    }

    #[test]
    fn a_token_that_names_no_end_or_an_empty_one_is_not_renewed() {
        let temp = with_end("no-end", 0);
        let asked = Cell::new(0);
        let said = temp.vault.field_for(&signed_in_provider(), NOW, &renewing(&asked));
        assert_eq!(said.map(|field| field.1), Some("Bearer old".to_string()));
        assert_eq!(asked.get(), 0, "a token that names no end does not expire");
        let temp =
            Place::new("empty", &json!({"acc": {"oauth": {"accessToken": "", "refreshToken": "r", "expiresAt": NOW + 1}}}));
        let said = temp.vault.field_for(&signed_in_provider(), NOW, &renewing(&asked));
        assert_eq!(said, None, "no token is no sign-in");
        assert_eq!(asked.get(), 0);
    }

    #[test]
    fn a_process_that_renewed_it_first_spares_this_one_the_question() {
        let within = CredentialVault::RENEW_WITHIN;
        for (name, expires) in [("renewed-meanwhile", NOW + within), ("no-end-meanwhile", 0)] {
            let temp = with_end(name, expires);
            let asked = Cell::new(0);
            let said = temp.vault.renewed(&signed_in_provider(), NOW, &renewing(&asked)).unwrap();
            assert_eq!((said.as_str(), asked.get()), ("old", 0), "{name}");
        }
        let temp = with_end("still-due", NOW + within - 1);
        let asked = Cell::new(0);
        let said = temp.vault.renewed(&signed_in_provider(), NOW, &renewing(&asked)).unwrap();
        assert_eq!((said.as_str(), asked.get()), ("new", 1));
    }

    #[test]
    fn what_the_board_writes_reaches_the_file_and_touches_no_other_account() {
        let place = Place::new("board-writes", &json!({"old": {"apiKey": "k"}, "other": {"apiKey": "o"}}));
        place.vault.put_api_key("new", "sk").unwrap();
        assert_eq!(place.written()["new"]["apiKey"], json!("sk"));
        place.vault.take_oauth("sub", Map::from_iter([("accessToken".to_string(), json!("t"))])).unwrap();
        assert_eq!(place.written()["sub"]["oauth"]["accessToken"], json!("t"));
        assert_eq!(place.vault.delete("old").unwrap(), Some(json!({"apiKey": "k"})));
        assert!(place.written().get("old").is_none());
        assert_eq!(place.vault.delete("old").unwrap(), None, "what is not there held nothing");
        assert_eq!(place.written()["other"]["apiKey"], json!("o"));
        place.vault.replace(Map::from_iter([("only".to_string(), json!({"apiKey": "x"}))])).unwrap();
        assert_eq!(place.written(), json!({"only": {"apiKey": "x"}}));
    }

    #[test]
    fn the_board_s_sign_in_is_renewed_when_it_is_due_or_asked_for() {
        let within = CredentialVault::RENEW_WITHIN;
        let config = ("https://t/x", "client");
        for (name, expires, force, renewed) in [
            ("edge", NOW + within, false, false),
            ("due", NOW + within - 1, false, true),
            ("past", NOW - 5, false, true),
            ("no-end", 0, false, false),
            ("forced", NOW + within * 1000, true, true),
            ("forced-no-end", 0, true, true),
        ] {
            let temp = with_end(&format!("board-{name}"), expires);
            let asked = Cell::new(0);
            let said = temp.vault.oauth("acc", config, force, NOW, &renewing(&asked)).unwrap();
            assert_eq!(asked.get(), u32::from(renewed), "{name}");
            assert_eq!(said["accessToken"], json!(if renewed { "new" } else { "old" }), "{name}");
            assert_eq!(temp.written()["acc"]["oauth"]["accessToken"], json!(if renewed { "new" } else { "old" }), "{name}");
        }
        let asked = Cell::new(0);
        let no_refresh = Place::new("board-no-refresh", &json!({"acc": {"oauth": {"accessToken": "old", "expiresAt": NOW + 1}}}));
        assert_eq!(no_refresh.vault.oauth("acc", config, false, NOW, &renewing(&asked)).unwrap()["accessToken"], json!("old"));
        let no_address = with_end("board-no-address", NOW + 1);
        assert_eq!(
            no_address.vault.oauth("acc", ("", "client"), true, NOW, &renewing(&asked)).unwrap()["accessToken"],
            json!("old")
        );
        assert_eq!(asked.get(), 0, "nothing to renew by, or nowhere to ask");
    }

    #[test]
    fn a_token_far_from_its_end_goes_as_it_is() {
        for oauth in [
            json!({"accessToken": "t", "expiresAt": NOW + 60}),
            json!({"accessToken": "t"}),
            json!({"accessToken": "t", "expiresAt": 0}),
        ] {
            let place = Place::new("far-oauth", &json!({"sub": {"oauth": oauth}}));
            assert_eq!(
                place.vault.field_for(&provider(signed_in()), NOW, &no_renewal),
                Some(("Authorization".to_string(), "Bearer t".to_string()))
            );
        }
        let place = Place::new("none", &json!({"sub": {"oauth": {}}, "key": {"apiKey": "k"}}));
        assert_eq!(place.vault.field_for(&provider(signed_in()), NOW, &no_renewal), None);
    }

    #[test]
    fn a_token_near_its_end_is_renewed_and_the_rest_of_the_file_stays() {
        let document = json!({"sub": {"oauth": {"accessToken": "old", "refreshToken": "r1", "expiresAt": NOW + 59, "kept": 1}, "apiKey": "k"}, "other": {"apiKey": "o"}});
        let place = Place::new("renew", &document);
        let asked = Cell::new(0);
        let renew = |url: &str, form: &[(&str, &str)]| {
            asked.set(asked.get() + 1);
            assert_eq!(url, "https://auth/token");
            assert_eq!(form, [("grant_type", "refresh_token"), ("refresh_token", "r1"), ("client_id", "app")]);
            Ok(json!({"access_token": "new", "refresh_token": "r2", "expires_in": 3600}))
        };
        assert_eq!(
            place.vault.field_for(&provider(signed_in()), NOW, &renew),
            Some(("Authorization".to_string(), "Bearer new".to_string()))
        );
        assert_eq!(asked.get(), 1);
        let written = place.written();
        assert_eq!(written["sub"]["oauth"]["refreshToken"], "r2");
        assert_eq!(written["sub"]["oauth"]["expiresAt"], NOW + 3600);
        assert_eq!(written["sub"]["oauth"]["obtainedAt"], NOW);
        assert_eq!(written["sub"]["oauth"]["kept"], 1);
        assert_eq!(written["sub"]["apiKey"], "k");
        assert_eq!(written["other"]["apiKey"], "o");
        let mode = fs::metadata(place.folder.join("provider-secrets.json")).unwrap().permissions().mode();
        assert_eq!(mode & 0o777, 0o600);
    }

    #[test]
    fn a_refresh_token_the_provider_does_not_rotate_is_kept() {
        let place =
            Place::new("keep", &json!({"sub": {"oauth": {"accessToken": "old", "refreshToken": "r1", "expiresAt": NOW}}}));
        let renew = |_: &str, _: &[(&str, &str)]| Ok(json!({"access_token": "new"}));
        assert!(place.vault.field_for(&provider(signed_in()), NOW, &renew).is_some());
        let written = place.written();
        assert_eq!(written["sub"]["oauth"]["refreshToken"], "r1");
        assert_eq!(written["sub"]["oauth"]["expiresAt"], NOW);
    }

    #[test]
    fn a_renewal_that_fails_is_no_sign_in_and_spends_nothing() {
        let document = json!({"sub": {"oauth": {"accessToken": "old", "refreshToken": "r1", "expiresAt": NOW}}});
        let place = Place::new("fail", &document);
        let refused = |_: &str, _: &[(&str, &str)]| Err(io::Error::other("refused"));
        assert_eq!(place.vault.field_for(&provider(signed_in()), NOW, &refused), None);
        let empty = |_: &str, _: &[(&str, &str)]| Ok(json!({}));
        assert_eq!(place.vault.field_for(&provider(signed_in()), NOW, &empty), None);
        assert_eq!(place.written(), document);
    }

    #[test]
    fn with_nothing_to_renew_by_the_old_token_goes_on() {
        let place = Place::new("no-refresh", &json!({"sub": {"oauth": {"accessToken": "old", "expiresAt": NOW}}}));
        assert_eq!(
            place.vault.field_for(&provider(signed_in()), NOW, &no_renewal),
            Some(("Authorization".to_string(), "Bearer old".to_string()))
        );
        let place =
            Place::new("no-address", &json!({"sub": {"oauth": {"accessToken": "old", "refreshToken": "r", "expiresAt": NOW}}}));
        let bare = json!({"id": "sub", "authMode": "oauth", "accountType": "openai-subscription"});
        assert_eq!(
            place.vault.field_for(&provider(bare), NOW, &no_renewal),
            Some(("Authorization".to_string(), "Bearer old".to_string()))
        );
    }
}
