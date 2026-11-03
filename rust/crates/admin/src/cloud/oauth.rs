//! Signing a cloud account in and out. A ChatGPT subscription signs in with a one-time code, OpenAI's device authorization
//! for the Codex app; a deleted account's sign-in ends at the provider, the request `codex logout` sends.

use super::call::Upstream;
use super::catalog::ModelCatalog;
use super::data::CloudData;
use crate::app::App;
use crate::common::misc::IsoMoment;
use net::Randomness;
use plumbing::http_client::HttpError;
use rules::{AppError, Coerce, PythonJson};
use serde_json::{Map, Value, json};
use std::collections::BTreeMap;
use std::sync::{Arc, Condvar, Mutex, PoisonError};
use std::time::Duration;

mod device;
use device::DeviceLogin;

/// What tells a login's thread to stop asking.
#[derive(Default)]
struct StopSign {
    stopped: Mutex<bool>,
    told: Condvar,
}

impl StopSign {
    fn set(&self) {
        *self.stopped.lock().unwrap_or_else(PoisonError::into_inner) = true;
        self.told.notify_all();
    }

    /// Whether it was set before `pause` ran out.
    fn wait(&self, pause: Duration) -> bool {
        let held = self.stopped.lock().unwrap_or_else(PoisonError::into_inner);
        let (held, _) = self.told.wait_timeout_while(held, pause, |stopped| !*stopped).unwrap_or_else(PoisonError::into_inner);
        *held
    }
}

/// A login the board may still ask about.
struct LoginSession {
    account_id: String,
    result: Value,
    completing: bool,
    stop: Arc<StopSign>,
}

/// The logins of this controller, and why a login the board still waits on is no longer pending.
#[derive(Default)]
pub struct LoginMemory {
    held: Mutex<LoginBook>,
}

#[derive(Default)]
struct LoginBook {
    sessions: BTreeMap<String, LoginSession>,
    ended: BTreeMap<String, (f64, Value)>,
}

impl LoginBook {
    const KEEP: f64 = 30.0 * 60.0;

    fn note_ended(&mut self, state: String, result: Value, now: f64) {
        self.ended.retain(|_, row| now - row.0 < Self::KEEP);
        self.ended.insert(state, (now, result));
    }

    fn ended_result(&self, state: &str, now: f64) -> Option<Value> {
        self.ended.get(state).filter(|row| now - row.0 < Self::KEEP).map(|row| row.1.clone())
    }
}

/// What a failed step of a sign-in may say about itself: never a token, and never what a provider wrote at length.
struct LoginFailure;

impl LoginFailure {
    fn error_word(said: &str) -> String {
        let parsed: Option<Value> = serde_json::from_str(said).ok();
        let error = parsed.as_ref().and_then(|parsed| parsed.get("error"));
        let word = match error {
            Some(Value::Object(fields)) => {
                let code = fields.get("code").filter(|code| Coerce::truthy(Some(*code)));
                code.or_else(|| fields.get("type"))
            }
            other => other,
        };
        let text = word.filter(|word| Coerce::truthy(Some(*word))).map(|word| Coerce::str_of(Some(word)));
        // absent-ok: a word that is no code is said as none, the sign-in window then asks again.
        text.filter(|text| Self::is_code(text)).unwrap_or_default()
    }

    fn is_code(word: &str) -> bool {
        let shape = !word.is_empty()
            && word.chars().count() <= 64
            && word.chars().all(|letter| letter.is_ascii_alphanumeric() || matches!(letter, '_' | '.' | '-'));
        shape && word.chars().any(|letter| letter.is_ascii_alphabetic())
    }

    fn reason(error: &std::io::Error) -> String {
        if matches!(error.kind(), std::io::ErrorKind::TimedOut | std::io::ErrorKind::WouldBlock) {
            return "timed out".to_string();
        }
        let text = error.to_string();
        let text = text.split(" (os error").next().unwrap_or(&text);
        text.chars().take(120).collect()
    }

    fn describe(failure: &HttpError) -> String {
        match failure {
            HttpError::Status(code, said) => {
                let word = Self::error_word(said);
                if word.is_empty() { format!("HTTP {code}") } else { format!("HTTP {code} {word}") }
            }
            HttpError::Io(error) if error.kind() == std::io::ErrorKind::InvalidData => "a malformed answer".to_string(),
            HttpError::Io(error) => format!("no answer: {}", Self::reason(error)),
            HttpError::BadAddress(_) => "a malformed answer".to_string(),
        }
    }
}

/// The sign-ins of this controller.
pub struct SignIn<'app> {
    app: &'app App,
}

impl<'app> SignIn<'app> {
    /// The sign-ins of `app`.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    fn jwt_email(id_token: &str) -> String {
        let payload = id_token.split('.').nth(1).and_then(net::Base64Url::decode);
        let said: Option<Value> = payload.and_then(|raw| serde_json::from_slice(&raw).ok());
        let at = |key: &str| said.as_ref().and_then(|said| said.get(key)).filter(|word| Coerce::truthy(Some(*word)));
        at("email").or_else(|| at("preferred_username")).map_or_else(String::new, |word| Coerce::str_of(Some(word)))
    }

    fn store_tokens(&self, account_id: &str, tokens: &Value) -> Result<Map<String, Value>, AppError> {
        let now = self.app.now() as i64;
        let token_type = Coerce::text(tokens.get("token_type"));
        let lasts = tokens.get("expires_in").filter(|said| Coerce::truthy(Some(*said))).and_then(Coerce::int);
        let oauth = json!({
            "accessToken": Coerce::text(tokens.get("access_token")),
            "refreshToken": Coerce::text(tokens.get("refresh_token")),
            "tokenType": if token_type.is_empty() { "Bearer".to_string() } else { token_type },
            "scope": Coerce::text(tokens.get("scope")),
            // absent-ok: a sign-in that does not say how long it lasts has no end to show.
            "expiresAt": lasts.map_or(0, |lasts| now + lasts),
            "obtainedAt": now,
            "email": Self::jwt_email(&Coerce::text(tokens.get("id_token"))),
        });
        let fields = Coerce::fields(&oauth);
        let vault = CloudData::of(self.app).vault();
        vault.take_oauth(account_id, fields.clone()).map_err(|error| AppError::with_status(error.to_string(), 500))?;
        Ok(fields)
    }

    /// The account a login is for: it must exist, sign in by OAuth and name where.
    fn login_account(&self, account_id: &str) -> Result<Value, AppError> {
        let account = CloudData::of(self.app).account(account_id);
        if account.as_ref().is_some_and(|account| Coerce::truthy(account.get("testAliasOf"))) {
            return Err(AppError::new("a test alias uses its original account login"));
        }
        let account = account.ok_or_else(|| AppError::with_status("unknown account", 404))?;
        if account.get("authMode").and_then(Value::as_str) != Some("oauth") {
            return Err(AppError::new("account authMode is not oauth"));
        }
        let config = account.get("oauthConfig");
        let names = |key: &str| Coerce::truthy(config.and_then(|config| config.get(key)));
        if !names("tokenUrl") || !names("clientId") {
            return Err(AppError::new("account oauthConfig incomplete (tokenUrl/clientId)"));
        }
        Ok(account)
    }

    /// The one ending of every way to sign in: the tokens kept, and the account's list of models asked for.
    fn finish_login(&self, account_id: &str, tokens: &Value) -> Result<Value, AppError> {
        if !Coerce::truthy(tokens.get("access_token")) {
            return Err(AppError::with_status("the provider returned no login token", 502));
        }
        let oauth = self.store_tokens(account_id, tokens)?;
        ModelCatalog::of(self.app).kick_refresh(account_id);
        Ok(json!({"state": "done", "email": oauth.get("email")}))
    }

    fn end_pending(&self, account_id: &str, why: &Value) {
        let now = self.app.now();
        let mut stops = Vec::new();
        {
            let mut book = self.app.logins.held.lock().unwrap_or_else(PoisonError::into_inner);
            let keys: Vec<String> = book
                .sessions
                .iter()
                .filter(|(_, session)| session.account_id == account_id && !session.completing)
                .map(|(key, _)| key.clone())
                .collect();
            for key in keys {
                if let Some(session) = book.sessions.remove(&key) {
                    let pending = session.result.get("state").and_then(Value::as_str).is_none_or(|state| state == "pending");
                    let said = if pending { why.clone() } else { session.result.clone() };
                    book.note_ended(key, said, now);
                    stops.push(session.stop);
                }
            }
        }
        for stop in stops {
            stop.set();
        }
    }

    /// A deleted account's sign-in in progress ends with it: a sign-in by code would otherwise keep asking OpenAI for up to 15 minutes.
    pub fn end_pending_of_removed(&self, account_id: &str) {
        self.end_pending(
            account_id,
            &json!({"state": "error", "reason": "removed", "error": "the account was removed during the sign-in"}),
        );
    }

    /// Renews through the same per-account lock the proxy uses; `None` for an account with no sign-in kept. A failure is the caller's to ignore.
    pub fn refresh_token(&self, account: &Value) -> Value {
        let id = {
            let owner = Coerce::text(account.get("credentialAccountId"));
            if owner.is_empty() { Coerce::text(account.get("id")) } else { owner }
        };
        let config = account.get("oauthConfig");
        let (url, client) = (
            Coerce::text(config.and_then(|config| config.get("tokenUrl"))),
            Coerce::text(config.and_then(|config| config.get("clientId"))),
        );
        let upstream = Upstream::of(self.app);
        let renewed = CloudData::of(self.app)
            .vault()
            .oauth(&id, (&url, &client), false, self.app.now() as i64, &|url, form| upstream.renew(url, form));
        match renewed {
            Ok(oauth) if !oauth.is_empty() => json!({"ok": true, "oauth": oauth}),
            Ok(_) => Value::Null,
            Err(error) => json!({"ok": false, "error": error.to_string()}),
        }
    }

    /// Where a login stands.
    pub fn status(&self, state: &str) -> Value {
        let book = self.app.logins.held.lock().unwrap_or_else(PoisonError::into_inner);
        if let Some(session) = book.sessions.get(state) {
            return session.result.clone();
        }
        book.ended_result(state, self.app.now()).unwrap_or_else(|| json!({"state": "unknown"}))
    }

    /// A sign-in by a one-time code started for an account whose provider has one: what the operator enters, and where.
    pub fn start_device_login(&self, account_id: &str) -> Result<Value, AppError> {
        let account = self.login_account(account_id)?;
        let spec = self.app.presets.device_login_spec(&account);
        let Some(spec) = spec.filter(|spec| Coerce::truthy(Some(spec))) else {
            return Err(AppError::new("this account's provider has no sign-in by code"));
        };
        let app = self.app.shared().ok_or_else(|| AppError::with_status("the controller is stopping", 503))?;
        let mut login = DeviceLogin::new(app, account, spec)?;
        let shown = login.begin()?;
        let id = Coerce::text(login.account.get("id"));
        self.end_pending(
            &id,
            &json!({"state": "error", "reason": "replaced", "error": "a newer sign-in replaced this code — use the code shown last"}),
        );
        {
            let mut book = self.app.logins.held.lock().unwrap_or_else(PoisonError::into_inner);
            book.sessions.insert(
                login.state.clone(),
                LoginSession { account_id: id, result: json!({"state": "pending"}), completing: false, stop: login.stop.clone() },
            );
        }
        let started = std::thread::Builder::new().name("device-login".to_string()).spawn(move || login.run());
        started.map_err(|error| AppError::with_status(error.to_string(), 500))?;
        Ok(shown)
    }
}

/// A deleted account's sign-in ended at the provider.
pub struct SignOut<'app> {
    app: &'app App,
    url: String,
    oauth: Value,
    client_id: String,
}

impl<'app> SignOut<'app> {
    const TIMEOUT: Duration = Duration::from_secs(10);

    fn headers() -> [(&'static str, String); 3] {
        [
            ("Content-Type", "application/json".to_string()),
            ("Accept", "application/json".to_string()),
            ("User-Agent", format!("lama-caravan/{}", crate::VERSION)),
        ]
    }

    /// The sign-out a deleted account owes; `None` when it owes none: an alias or an old pool holds no sign-in, and a plan may name no way out.
    pub fn of(app: &'app App, account: Option<&Value>, removed: Option<&Value>) -> Option<Self> {
        let account = account?;
        if Coerce::truthy(account.get("testAliasOf")) || Coerce::truthy(account.get("isPool")) {
            return None;
        }
        let oauth = removed?.get("oauth").filter(|oauth| oauth.is_object())?;
        if !Coerce::truthy(oauth.get("refreshToken")) && !Coerce::truthy(oauth.get("accessToken")) {
            return None;
        }
        let plan = app.presets.device_login_preset(&Coerce::text(account.get("accountType")))?.get("oauth")?;
        let url = Coerce::text(plan.get("revokeUrl"));
        if url.is_empty() {
            return None;
        }
        let said = Coerce::text(account.get("oauthConfig").and_then(|config| config.get("clientId")));
        let client_id = if said.is_empty() { Coerce::text(plan.get("clientId")) } else { said };
        Some(Self { app, url, oauth: oauth.clone(), client_id })
    }

    fn body(&self) -> Value {
        let refresh = Coerce::text(self.oauth.get("refreshToken"));
        if refresh.is_empty() {
            return json!({"token": Coerce::text(self.oauth.get("accessToken")), "token_type_hint": "access_token"});
        }
        json!({"token": refresh, "token_type_hint": "refresh_token", "client_id": self.client_id})
    }

    /// `{ok, error}`.
    pub fn send(&self) -> Value {
        let fields = Self::headers();
        let asked: Vec<(&str, String)> = fields.iter().map(|(name, value)| (*name, value.clone())).collect();
        match self.app.http.ask("POST", &self.url, &asked, PythonJson::spaced(&self.body()).as_bytes(), Self::TIMEOUT) {
            Ok(_) => json!({"ok": true, "error": ""}),
            Err(error) => json!({"ok": false, "error": LoginFailure::describe(&error)}),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_failure_says_only_a_short_code_of_what_it_was_told() {
        let word = |said: &str| LoginFailure::describe(&HttpError::Status(400, said.to_string()));
        assert_eq!(word(r#"{"error": "invalid_grant"}"#), "HTTP 400 invalid_grant");
        assert_eq!(word(r#"{"error": {"code": "bad_code"}}"#), "HTTP 400 bad_code");
        assert_eq!(word(r#"{"error": {"type": "t1"}}"#), "HTTP 400 t1");
        assert_eq!(word(r#"{"error": "a token sk-123 in a sentence"}"#), "HTTP 400");
        assert_eq!(word("not json"), "HTTP 400");
        assert_eq!(word(r#"{"error": "12345"}"#), "HTTP 400");
    }

    #[test]
    fn the_pause_is_a_string_and_has_bounds() {
        assert_eq!(DeviceLogin::pause(Some(&json!("7"))), 7);
        assert_eq!(DeviceLogin::pause(Some(&json!(100))), 60);
        assert_eq!(DeviceLogin::pause(Some(&json!(0))), DeviceLogin::INTERVAL);
        assert_eq!(DeviceLogin::pause(None), DeviceLogin::INTERVAL);
    }

    #[test]
    fn a_moment_is_a_number_or_an_iso_time() {
        assert!((DeviceLogin::moment(Some(&json!(1000))) - 1000.0).abs() < f64::EPSILON);
        assert!((DeviceLogin::moment(Some(&json!("1970-01-01T00:16:40Z"))) - 1000.0).abs() < f64::EPSILON);
        assert!(DeviceLogin::moment(Some(&json!("soon"))).abs() < f64::EPSILON);
    }

    #[test]
    fn a_token_names_its_email() {
        let payload = "eyJlbWFpbCI6ImFAYi5jIn0";
        assert_eq!(SignIn::jwt_email(&format!("h.{payload}.s")), "a@b.c");
        assert_eq!(SignIn::jwt_email("not-a-token"), "");
    }
}
