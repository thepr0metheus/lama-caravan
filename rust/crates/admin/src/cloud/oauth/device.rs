//! The sign-in by a one-time code, step by step.

use super::*;

/// One sign-in by a one-time code, its thread asking OpenAI until the code is entered, it expires, or a newer start replaces it.
pub(super) struct DeviceLogin {
    pub(super) app: Arc<App>,
    pub(super) account: Value,
    pub(super) spec: Value,
    pub(super) state: String,
    pub(super) stop: Arc<StopSign>,
    pub(super) device_auth_id: String,
    pub(super) user_code: String,
    pub(super) interval: i64,
    pub(super) expires_at: f64,
    pub(super) failures: i64,
}

impl DeviceLogin {
    /// Answers OpenAI gives while the code waits.
    pub(super) const PENDING: [u16; 2] = [403, 404];
    pub(super) const LIFETIME: f64 = 15.0 * 60.0;
    pub(super) const INTERVAL: i64 = 5;
    pub(super) const PATIENCE: i64 = 5;

    pub(super) fn new(app: Arc<App>, account: Value, spec: Value) -> Result<Self, AppError> {
        let state = Randomness::token_urlsafe(16).ok_or_else(|| AppError::with_status("no randomness to be had", 500))?;
        Ok(Self {
            app,
            account,
            spec,
            state,
            stop: Arc::new(StopSign::default()),
            device_auth_id: String::new(),
            user_code: String::new(),
            interval: Self::INTERVAL,
            expires_at: 0.0,
            failures: 0,
        })
    }

    pub(super) fn post(&self, url: &str, payload: &Value) -> Result<Value, HttpError> {
        let fields = SignOut::headers();
        let asked: Vec<(&str, String)> = fields.iter().map(|(name, value)| (*name, value.clone())).collect();
        let answer = self.app.http.ask("POST", url, &asked, PythonJson::spaced(payload).as_bytes(), Duration::from_secs(15))?;
        let raw = answer.text(1 << 20)?;
        if raw.is_empty() {
            return Ok(json!({}));
        }
        serde_json::from_slice(&raw).map_err(|error| HttpError::Io(std::io::Error::new(std::io::ErrorKind::InvalidData, error)))
    }

    pub(super) fn begin(&mut self) -> Result<Value, AppError> {
        let client_id = Coerce::text(self.account.get("oauthConfig").and_then(|config| config.get("clientId")));
        let answer = self.post(&Coerce::text(self.spec.get("userCodeUrl")), &json!({"client_id": client_id}));
        let answer = answer.map_err(|error| {
            AppError::with_status(format!("OpenAI gave no sign-in code ({})", LoginFailure::describe(&error)), 502)
        })?;
        self.device_auth_id = Coerce::text(answer.get("device_auth_id"));
        let user_code = Coerce::text(answer.get("user_code"));
        self.user_code = if user_code.is_empty() { Coerce::text(answer.get("usercode")) } else { user_code };
        if self.device_auth_id.is_empty() || self.user_code.is_empty() {
            return Err(AppError::with_status("OpenAI gave no sign-in code (its answer has none)", 502));
        }
        self.interval = Self::pause(answer.get("interval"));
        let now = self.app.now();
        let stated = Self::moment(answer.get("expires_at"));
        self.expires_at = if now < stated && stated < now + Self::LIFETIME { stated } else { now + Self::LIFETIME };
        Ok(json!({
            "state": self.state, "userCode": self.user_code, "verifyUrl": self.spec.get("verifyUrl"),
            "expiresAt": self.expires_at as i64, "interval": self.interval,
        }))
    }

    /// OpenAI sends the pause as a string ("5").
    pub(super) fn pause(raw: Option<&Value>) -> i64 {
        let seconds = raw.and_then(Coerce::float).map(|seconds| seconds as i64);
        seconds.filter(|seconds| *seconds > 0).map_or(Self::INTERVAL, |seconds| seconds.min(60))
    }

    /// `expires_at` as Unix seconds, an ISO time or a number; 0 when it is missing or unreadable.
    pub(super) fn moment(raw: Option<&Value>) -> f64 {
        match raw {
            // absent-ok: a number too large for a float reads as a moment long past: the token is renewed.
            Some(Value::Number(number)) => number.as_f64().unwrap_or(0.0),
            // absent-ok: a moment that does not read is long past: the token is renewed.
            Some(Value::String(text)) => IsoMoment::epoch(text).unwrap_or(0.0),
            _ => 0.0,
        }
    }

    pub(super) fn result_state(&self) -> String {
        let book = self.app.logins.held.lock().unwrap_or_else(PoisonError::into_inner);
        let session = book.sessions.get(&self.state);
        session.map_or_else(|| "ended".to_string(), |session| Coerce::text(session.result.get("state")))
    }

    pub(super) fn end(&self, result: Value) -> String {
        let state = Coerce::text(result.get("state"));
        {
            let mut book = self.app.logins.held.lock().unwrap_or_else(PoisonError::into_inner);
            if let Some(session) = book.sessions.get_mut(&self.state) {
                session.result = result;
                session.completing = false;
            }
        }
        self.stop.set();
        state
    }

    pub(super) fn mark_completing(&self) {
        let mut book = self.app.logins.held.lock().unwrap_or_else(PoisonError::into_inner);
        if let Some(session) = book.sessions.get_mut(&self.state) {
            session.completing = true;
        }
    }

    pub(super) fn exchange(&self, code: &str, verifier: &str) -> Result<Value, String> {
        let config = self.account.get("oauthConfig");
        let at = |key: &str| Coerce::text(config.and_then(|config| config.get(key)));
        let redirect = Coerce::text(self.spec.get("redirectUri"));
        let client = at("clientId");
        let form = [
            ("grant_type", "authorization_code"),
            ("code", code),
            ("redirect_uri", redirect.as_str()),
            ("client_id", client.as_str()),
            ("code_verifier", verifier),
        ];
        let tokens = Upstream::of(&self.app).post_form(&at("tokenUrl"), &form, Duration::from_secs(15));
        let tokens = tokens.map_err(|error| LoginFailure::describe(&error))?;
        let id = Coerce::text(self.account.get("id"));
        SignIn::of(&self.app).finish_login(&id, &tokens).map_err(|error| error.message)
    }

    /// OpenAI asked once whether the code was entered, and the login taken when it was.
    pub(super) fn step(&mut self) -> String {
        let current = self.result_state();
        if current != "pending" {
            return current;
        }
        if self.app.now() >= self.expires_at {
            return self
                .end(json!({"state": "error", "reason": "expired", "error": "the code expired; start the sign-in again"}));
        }
        let asked = json!({"device_auth_id": self.device_auth_id, "user_code": self.user_code});
        let answer = match self.post(&Coerce::text(self.spec.get("pollUrl")), &asked) {
            Ok(answer) => answer,
            Err(HttpError::Status(code, _)) if Self::PENDING.contains(&code) => {
                self.failures = 0;
                return "pending".to_string();
            }
            Err(failure @ HttpError::Status(..)) => {
                let error = format!("OpenAI refused the sign-in ({})", LoginFailure::describe(&failure));
                return self.end(json!({"state": "error", "error": error}));
            }
            Err(failure) => {
                self.failures += 1;
                if self.failures < Self::PATIENCE {
                    return "pending".to_string();
                }
                let error = format!("OpenAI did not answer ({})", LoginFailure::describe(&failure));
                return self.end(json!({"state": "error", "error": error}));
            }
        };
        self.failures = 0;
        let (code, verifier) = (Coerce::text(answer.get("authorization_code")), Coerce::text(answer.get("code_verifier")));
        if code.is_empty() || verifier.is_empty() {
            return self.end(json!({"state": "error", "error": "OpenAI accepted the code but sent no login"}));
        }
        if CloudData::of(&self.app).account(&Coerce::text(self.account.get("id"))).is_none() {
            return self.end(json!({"state": "error", "error": "the subscription was removed during login"}));
        }
        self.mark_completing();
        let result = self.exchange(&code, &verifier).unwrap_or_else(
            |why| json!({"state": "error", "error": format!("the login was not taken ({why}); start the sign-in again")}),
        );
        self.end(result)
    }

    pub(super) fn run(mut self) {
        while !self.stop.wait(Duration::from_secs(self.interval.unsigned_abs())) {
            if self.step() != "pending" {
                return;
            }
        }
    }
}
