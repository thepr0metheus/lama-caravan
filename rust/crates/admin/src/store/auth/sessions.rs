//! Who is signed in: a login, its session, and the fleet's token.

use super::*;

impl AuthStore {
    pub(super) fn fails(&self) -> MutexGuard<'_, HashMap<String, (i64, f64)>> {
        self.login_fails.lock().unwrap_or_else(PoisonError::into_inner)
    }

    pub(super) fn fail_key(ip: &str) -> String {
        if ip.is_empty() { "?".to_string() } else { ip.to_string() }
    }

    /// The account of a name and a password, or a refusal: "too many attempts" is said before a password is looked at.
    pub fn verify_login(&self, username: &str, password: &str, ip: &str, now: f64) -> Result<(i64, String), AppError> {
        let key = Self::fail_key(ip);
        // absent-ok: an address that failed nothing is locked until the epoch.
        let locked_until = self.fails().get(&key).map_or(0.0, |held| held.1);
        if now < locked_until {
            return Err(AppError::with_status("too many attempts — try again in a minute", 429));
        }
        let wanted = Coerce::strip(username).to_string();
        let row = self.with(|doc| {
            Ok(Self::rows(doc, "users").find(|row| row.get("username").and_then(Value::as_str) == Some(&wanted)).cloned())
        })?;
        let ok = match &row {
            Some(row) => {
                // absent-ok: a salt or a hash not kept reads as empty: the password then does not match.
                let word = |key: &str| Self::unhex(row.get(key).and_then(Value::as_str).unwrap_or_default());
                // absent-ok: the rounds are in every row written; one that lacks them matches no password.
                let rounds = row.get("iters").and_then(Value::as_u64).and_then(|rounds| u32::try_from(rounds).ok()).unwrap_or(1);
                Pbkdf2::matches(password.as_bytes(), &word("salt"), rounds, &word("hash"))
            }
            None => {
                // Spend the time a real check would have, for a user who does not exist.
                let _spent = Pbkdf2::derive(password.as_bytes(), b"caravan-timing-pad", Self::ITERATIONS);
                false
            }
        };
        if !ok {
            let mut fails = self.fails();
            let held = fails.entry(key).or_insert((0, 0.0));
            held.0 += 1;
            if held.0 >= Self::MAX_FAILS {
                *held = (0, now + Self::LOCKOUT_SECONDS);
            }
            return Err(AppError::with_status("invalid username or password", 401));
        }
        self.fails().remove(&key);
        // absent-ok: no such session is an empty row, refused just below.
        let row = row.unwrap_or_default();
        // absent-ok: a row that matched has its id; an old file's rows all do.
        Ok((Coerce::i64_or_zero(row.get("id")), Coerce::text(row.get("username"))))
    }

    /// A new session's token: only its hash is kept.
    pub fn create_session(&self, user_id: i64, ip: &str, ua: &str, now: i64) -> Result<String, AppError> {
        let token =
            Randomness::token_urlsafe(32).ok_or_else(|| AppError::with_status("the system gives no random bytes", 500))?;
        let hash = Sha256::of(token.as_bytes());
        self.changing(|doc| {
            if let Some(sessions) = Self::rows_mut(doc, "sessions") {
                sessions.retain(|row| row.get("expiresAt").and_then(Value::as_i64).is_some_and(|until| until >= now));
                sessions.push(json!({"tokenHash": hash, "userId": user_id, "createdAt": now, "expiresAt": now + Self::SESSION_TTL, "lastSeen": now, "ip": Coerce::first_letters(ip, 64), "ua": Coerce::first_letters(ua, 160)}));
            }
            Ok(())
        })?;
        Ok(token)
    }

    /// Who a token is; none for a token that is no live session. Its last sight is written once a minute at most.
    pub fn validate_session(&self, token: &str, now: f64) -> Result<Option<SessionInfo>, AppError> {
        if token.is_empty() {
            return Ok(None);
        }
        let hash = Sha256::of(token.as_bytes());
        let mut seen_now = false;
        let found = self.with(|doc| {
            let session = Self::rows(doc, "sessions").find(|row| row.get("tokenHash").and_then(Value::as_str) == Some(&hash));
            let Some(session) = session else {
                return Ok(None);
            };
            // absent-ok: a session with no end has ended.
            if session.get("expiresAt").and_then(Value::as_f64).unwrap_or(0.0) < now {
                return Ok(None);
            }
            let user_id = session.get("userId").and_then(Value::as_i64);
            // absent-ok: a session nobody saw is seen now.
            seen_now = now - session.get("lastSeen").and_then(Value::as_f64).unwrap_or(0.0) > Self::SEEN_EVERY;
            let user = Self::rows(doc, "users").find(|row| row.get("id").and_then(Value::as_i64) == user_id);
            Ok(user.map(|user| SessionInfo {
                user: Coerce::text(user.get("username")),
                role: if Coerce::truthy(user.get("role")) { Coerce::text(user.get("role")) } else { "admin".to_string() },
            }))
        })?;
        if found.is_some() && seen_now {
            self.changing(|doc| {
                if let Some(session) = Self::rows_mut(doc, "sessions")
                    .into_iter()
                    .flatten()
                    .find(|row| row.get("tokenHash").and_then(Value::as_str) == Some(&hash))
                {
                    session["lastSeen"] = json!(now.trunc() as i64);
                }
                Ok(())
            })?;
        }
        Ok(found)
    }

    /// Ends the session of a token.
    pub fn delete_session(&self, token: &str) -> Result<(), AppError> {
        if token.is_empty() {
            return Ok(());
        }
        let hash = Sha256::of(token.as_bytes());
        self.changing(|doc| {
            if let Some(sessions) = Self::rows_mut(doc, "sessions") {
                sessions.retain(|row| row.get("tokenHash").and_then(Value::as_str) != Some(&hash));
            }
            Ok(())
        })
    }

    /// The live sessions, last seen first, under the id the panel lists a session by.
    pub fn list_sessions(&self, now: i64) -> Result<Vec<Value>, AppError> {
        self.with(|doc| {
            let mut live: Vec<&Value> = Self::rows(doc, "sessions").filter(|row| row.get("expiresAt").and_then(Value::as_i64).is_some_and(|until| until >= now)).collect();
            // absent-ok: a session nobody saw stands last.
            live.sort_by_key(|row| std::cmp::Reverse(Coerce::i64_or_zero(row.get("lastSeen"))));
            let name_of = |user_id: Option<i64>| Self::rows(doc, "users").find(|row| row.get("id").and_then(Value::as_i64) == user_id).map(|row| row.get("username").cloned());
            Ok(live
                .into_iter()
                .filter_map(|row| {
                    let name = name_of(row.get("userId").and_then(Value::as_i64))?;
                    let hash = Coerce::text(row.get("tokenHash"));
                    let ua = Coerce::text(row.get("ua"));
                    Some(json!({"id": Coerce::first_letters(&hash, Self::SESSION_ID_LENGTH), "username": name, "createdAt": row.get("createdAt"), "lastSeen": row.get("lastSeen"), "ip": Coerce::text(row.get("ip")), "ua": Coerce::first_letters(&ua, 60)}))
                })
                .collect())
        })
    }

    /// Kills every session except the caller's own; how many went.
    pub fn revoke_other_sessions(&self, current: &str) -> Result<usize, AppError> {
        let keep = if current.is_empty() { String::new() } else { Sha256::of(current.as_bytes()) };
        self.changing(|doc| {
            let Some(sessions) = Self::rows_mut(doc, "sessions") else {
                return Ok(0);
            };
            let before = sessions.len();
            sessions.retain(|row| row.get("tokenHash").and_then(Value::as_str) == Some(&keep));
            Ok(before - sessions.len())
        })
    }

    /// Ends the one session listed under this id.
    pub fn revoke_session(&self, short_id: &str) -> Result<(), AppError> {
        let short_id = Coerce::strip(short_id);
        if short_id.is_empty() {
            return Err(AppError::new("session id is required"));
        }
        self.changing(|doc| {
            let sessions = Self::rows_mut(doc, "sessions").ok_or_else(|| AppError::with_status("session not found", 404))?;
            let at = sessions
                .iter()
                .position(|row| Coerce::first_letters(&Coerce::text(row.get("tokenHash")), Self::SESSION_ID_LENGTH) == short_id);
            let Some(at) = at else {
                return Err(AppError::with_status("session not found", 404));
            };
            sessions.remove(at);
            Ok(())
        })
    }

    /// The fleet token; "" when none is set.
    pub fn fleet_token(&self) -> Result<String, AppError> {
        self.with(|doc| {
            Ok(doc
                .get("meta")
                .and_then(|meta| meta.get("fleet_token"))
                .and_then(Value::as_str)
                .map_or_else(String::new, str::to_string))
        })
    }

    pub(super) fn new_fleet_token() -> Result<String, AppError> {
        Randomness::token_urlsafe(24)
            .map(|word| format!("caravan-{word}"))
            .ok_or_else(|| AppError::with_status("the system gives no random bytes", 500))
    }

    pub(super) fn put_fleet_token(&self, token: &str) -> Result<(), AppError> {
        self.changing(|doc| {
            let meta = doc.entry("meta".to_string()).or_insert_with(|| json!({}));
            meta["fleet_token"] = json!(token);
            Ok(())
        })
    }

    /// The fleet token, made when there is none.
    pub fn fleet_token_ensure(&self) -> Result<String, AppError> {
        let token = self.fleet_token()?;
        if !token.is_empty() {
            return Ok(token);
        }
        let token = Self::new_fleet_token()?;
        self.put_fleet_token(&token)?;
        Ok(token)
    }

    /// A new fleet token in place of the old.
    pub fn fleet_token_regenerate(&self) -> Result<String, AppError> {
        let token = Self::new_fleet_token()?;
        self.put_fleet_token(&token)?;
        Ok(token)
    }

    /// Whether `candidate` is the fleet token. No token set matches nothing.
    pub fn fleet_token_verify(&self, candidate: &str) -> Result<bool, AppError> {
        let token = self.fleet_token()?;
        Ok(!token.is_empty() && Randomness::same(candidate.as_bytes(), token.as_bytes()))
    }
}
