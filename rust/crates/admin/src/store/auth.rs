//! The accounts: who may drive the fleet, and what proves it, with the file a JSON document at mode 0600 in place of SQLite: read from the old database at the first start, which stays as it was.
//!
//! What is deliberate here, and would be easy to "simplify" away:
//! * Passwords are never stored, and never compared as bytes by ==. Each user has their own salt, and the comparison is constant-time.
//! * An unknown user costs the same as a wrong password: a login form that answers faster for names that do not exist is a way to enumerate the ones that do.
//! * Sessions are stored as a hash of the token: reading the file does not hand anyone a live session.
//! * The last admin cannot be demoted or deleted: there is no other way back in.
//! * A file that does not read is no empty file: it would read as "no accounts yet", and anyone could make the first one.

use super::base::Unreadable;
use super::sqlite::{SqlRow, SqlValue, SqliteFile};
use files::AtomicFile;
use net::{Pbkdf2, Randomness, Sha256};
use rules::{AppError, Coerce, PythonJson};
use serde_json::{Map, Value, json};
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::{Mutex, MutexGuard, PoisonError};

mod document;

mod sessions;

/// Who a session is.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SessionInfo {
    /// The user's name.
    pub user: String,
    /// "admin" or "viewer".
    pub role: String,
}

/// The accounts document, its rate limiter.
pub struct AuthStore {
    path: PathBuf,
    doc: Mutex<Result<Map<String, Value>, String>>,
    login_fails: Mutex<HashMap<String, (i64, f64)>>,
}

impl AuthStore {
    /// How long a session lives without being renewed.
    pub const SESSION_TTL: i64 = 30 * 24 * 3600;
    /// PBKDF2 rounds for a NEW password. Stored per user, so raising this does not invalidate anybody.
    const ITERATIONS: u32 = 200_000;
    /// Wrong passwords from one address before it is made to wait.
    const MAX_FAILS: i64 = 5;
    const LOCKOUT_SECONDS: f64 = 60.0;
    const SESSION_ID_LENGTH: usize = 12;
    /// Seconds between two writes of a session's `lastSeen`: what the sessions list shows, its grain, not its life (that is `expiresAt`). Once a
    /// minute it rewrote the accounts' file for every open board, on the NAS's disks (2026-11-03; the owner: «write less»).
    const SEEN_EVERY: f64 = 600.0;
    /// The cookie's name.
    pub const SESSION_COOKIE: &'static str = "caravan_session";
    const UNAVAILABLE: &'static str = "the sign-in store did not answer, try again in a moment";

    /// The store whose old database is at `database`; its document stands beside it. `stamp` names the copy of a document that does not read.
    pub fn open(database: &Path, stamp: &str) -> Self {
        let path = database.with_file_name("auth.json");
        let doc = Self::read_document(&path, database, stamp);
        if let Err(error) = &doc {
            plumbing::Log::line(&format!("auth: the accounts did not read, every request is answered 503: {error}"));
        }
        Self { path, doc: Mutex::new(doc), login_fails: Mutex::new(HashMap::new()) }
    }

    fn locked(&self) -> MutexGuard<'_, Result<Map<String, Value>, String>> {
        self.doc.lock().unwrap_or_else(PoisonError::into_inner)
    }

    fn with<R>(&self, work: impl FnOnce(&mut Map<String, Value>) -> Result<R, AppError>) -> Result<R, AppError> {
        let mut held = self.locked();
        let doc = held.as_mut().map_err(|_| AppError::with_status(Self::UNAVAILABLE, 503))?;
        work(doc)
    }

    /// A change, saved. A file that does not take it fails the request: an account that exists only in memory is gone at the next start.
    fn changing<R>(&self, work: impl FnOnce(&mut Map<String, Value>) -> Result<R, AppError>) -> Result<R, AppError> {
        self.with(|doc| {
            let out = work(doc)?;
            Self::write(&self.path, doc).map_err(|error| AppError::with_status(error.to_string(), 500))?;
            Ok(out)
        })
    }

    fn rows<'doc>(doc: &'doc Map<String, Value>, name: &str) -> impl Iterator<Item = &'doc Value> {
        doc.get(name).and_then(Value::as_array).into_iter().flatten()
    }

    fn rows_mut<'doc>(doc: &'doc mut Map<String, Value>, name: &str) -> Option<&'doc mut Vec<Value>> {
        doc.get_mut(name).and_then(Value::as_array_mut)
    }

    /// The accounts whole, for a settings export.
    pub fn document(&self) -> Result<Value, AppError> {
        self.with(|doc| Ok(Value::Object(doc.clone())))
    }

    /// The accounts of a settings import. Whoever was signed in by the sessions it replaces is out, and a store that did not read before reads now.
    pub fn replace_document(&self, document: Map<String, Value>) -> Result<(), AppError> {
        Self::write(&self.path, &document).map_err(|error| AppError::with_status(error.to_string(), 500))?;
        *self.locked() = Ok(document);
        self.login_fails.lock().unwrap_or_else(PoisonError::into_inner).clear();
        Ok(())
    }

    /// The accounts of an older settings export: the database file it carries.
    pub fn replace_from_database(&self, raw: Vec<u8>) -> Result<(), AppError> {
        let file = SqliteFile::of_bytes(raw).map_err(AppError::new)?;
        self.replace_document(Self::from_file(&file).map_err(AppError::new)?)
    }

    /// Whether any account exists: what "sign-in is on" means.
    pub fn enabled(&self) -> Result<bool, AppError> {
        self.with(|doc| Ok(Self::rows(doc, "users").next().is_some()))
    }

    fn salted(password: &str) -> Result<(String, String), AppError> {
        let salt = Randomness::bytes(16).ok_or_else(|| AppError::with_status("the system gives no random bytes", 500))?;
        let digest = Pbkdf2::derive(password.as_bytes(), &salt, Self::ITERATIONS);
        Ok((Self::hex(&salt), Self::hex(&digest)))
    }

    fn word_role(role: &str) -> Result<String, AppError> {
        let role = Coerce::strip(role).to_lowercase();
        if role == "admin" || role == "viewer" { Ok(role) } else { Err(AppError::new("role must be admin or viewer")) }
    }

    /// Makes an account.
    pub fn create_user(&self, username: &str, password: &str, role: &str, now: i64) -> Result<Value, AppError> {
        let username = Coerce::strip(username).to_string();
        let role = Self::word_role(if role.is_empty() { "admin" } else { role })?;
        if username.is_empty() || username.chars().count() > 64 {
            return Err(AppError::new("username is required (max 64 chars)"));
        }
        if password.chars().count() < 8 {
            return Err(AppError::new("password must be at least 8 characters"));
        }
        let (salt, digest) = Self::salted(password)?;
        self.changing(|doc| {
            if Self::rows(doc, "users").any(|row| row.get("username").and_then(Value::as_str) == Some(&username)) {
                return Err(AppError::with_status(format!("user {username} already exists"), 409));
            }
            let id = Self::rows(doc, "users").filter_map(|row| row.get("id").and_then(Value::as_i64)).max().map_or(1, |most| most + 1);
            let row = json!({"id": id, "username": username, "salt": salt, "hash": digest, "iters": Self::ITERATIONS, "createdAt": now, "role": role});
            if let Some(users) = Self::rows_mut(doc, "users") {
                users.push(row);
            }
            Ok(())
        })?;
        Ok(json!({"username": username, "role": role}))
    }

    /// Changes a role. The last admin cannot be demoted.
    pub fn set_role(&self, username: &str, role: &str) -> Result<(), AppError> {
        let role = Self::word_role(role)?;
        self.changing(|doc| {
            let other_admins = Self::rows(doc, "users")
                .filter(|row| {
                    row.get("role").and_then(Value::as_str) == Some("admin")
                        && row.get("username").and_then(Value::as_str) != Some(username)
                })
                .count();
            if role == "viewer" && other_admins == 0 {
                return Err(AppError::new("cannot demote the last admin"));
            }
            let found = Self::rows_mut(doc, "users")
                .into_iter()
                .flatten()
                .find(|row| row.get("username").and_then(Value::as_str) == Some(username));
            let Some(found) = found else {
                return Err(AppError::with_status(format!("no such user: {username}"), 404));
            };
            found["role"] = json!(role);
            Ok(())
        })
    }

    /// Changes a password.
    pub fn set_password(&self, username: &str, password: &str) -> Result<(), AppError> {
        if password.chars().count() < 8 {
            return Err(AppError::new("password must be at least 8 characters"));
        }
        let (salt, digest) = Self::salted(password)?;
        self.changing(|doc| {
            let found = Self::rows_mut(doc, "users")
                .into_iter()
                .flatten()
                .find(|row| row.get("username").and_then(Value::as_str) == Some(username));
            let Some(found) = found else {
                return Err(AppError::with_status(format!("no such user: {username}"), 404));
            };
            found["salt"] = json!(salt);
            found["hash"] = json!(digest);
            found["iters"] = json!(Self::ITERATIONS);
            Ok(())
        })
    }

    /// Deletes an account and its sessions. The last one stays: the UI offers no "disable auth".
    pub fn delete_user(&self, username: &str) -> Result<(), AppError> {
        self.changing(|doc| {
            let Some(id) = Self::rows(doc, "users")
                .find(|row| row.get("username").and_then(Value::as_str) == Some(username))
                .and_then(|row| row.get("id").and_then(Value::as_i64))
            else {
                return Err(AppError::with_status(format!("no such user: {username}"), 404));
            };
            if Self::rows(doc, "users").count() <= 1 {
                return Err(AppError::new("cannot delete the last user — disable auth is not supported from the UI"));
            }
            if let Some(sessions) = Self::rows_mut(doc, "sessions") {
                sessions.retain(|row| row.get("userId").and_then(Value::as_i64) != Some(id));
            }
            if let Some(users) = Self::rows_mut(doc, "users") {
                users.retain(|row| row.get("id").and_then(Value::as_i64) != Some(id));
            }
            Ok(())
        })
    }

    /// The accounts, as the Security panel lists them.
    pub fn list_users(&self) -> Result<Vec<Value>, AppError> {
        self.with(|doc| {
            Ok(Self::rows(doc, "users")
                .map(|row| json!({"username": row.get("username"), "createdAt": row.get("createdAt"), "role": row.get("role")}))
                .collect())
        })
    }

    /// The cookie's field.
    pub fn cookie_header(token: &str, clear: bool) -> String {
        let name = Self::SESSION_COOKIE;
        if clear {
            return format!("{name}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax");
        }
        format!("{name}={token}; Path=/; Max-Age={}; HttpOnly; SameSite=Lax", Self::SESSION_TTL)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn folder(name: &str) -> PathBuf {
        let folder = std::env::temp_dir().join(format!("auth-{name}-{}", std::process::id()));
        std::fs::create_dir_all(&folder).unwrap();
        folder
    }

    #[test]
    fn an_account_signs_in_and_a_wrong_password_is_counted() {
        let root = folder("signin");
        let store = AuthStore::open(&root.join("auth.db"), "s");
        assert!(!store.enabled().unwrap());
        store.create_user("me", "password1", "", 1).unwrap();
        assert!(store.enabled().unwrap());
        assert_eq!(store.create_user("me", "password1", "", 1).unwrap_err().status, 409);
        assert_eq!(store.create_user("x", "short", "", 1).unwrap_err().message, "password must be at least 8 characters");
        let (id, name) = store.verify_login(" me ", "password1", "ip", 10.0).unwrap();
        assert_eq!(name, "me");
        for _ in 0..5 {
            assert_eq!(store.verify_login("me", "wrong", "ip", 10.0).unwrap_err().status, 401);
        }
        assert_eq!(store.verify_login("me", "password1", "ip", 11.0).unwrap_err().status, 429);
        assert!(store.verify_login("me", "password1", "ip", 71.0).is_ok());
        let token = store.create_session(id, "ip", "ua", 100).unwrap();
        assert_eq!(
            store.validate_session(&token, 100.0).unwrap(),
            Some(SessionInfo { user: "me".to_string(), role: "admin".to_string() })
        );
        assert_eq!(store.validate_session("other", 100.0).unwrap(), None);
        assert_eq!(store.validate_session(&token, 100.0 + 31.0 * 86400.0).unwrap(), None);
        let listed = store.list_sessions(100).unwrap();
        assert_eq!(listed.first().and_then(|row| row.get("id")).and_then(Value::as_str).map(str::len), Some(12));
        store.delete_session(&token).unwrap();
        assert_eq!(store.validate_session(&token, 100.0).unwrap(), None);
        std::fs::remove_dir_all(&root).unwrap();
    }

    #[test]
    fn a_session_s_last_sight_is_written_once_in_its_grain() {
        let root = folder("seen");
        let store = AuthStore::open(&root.join("auth.db"), "s");
        store.create_user("me", "password1", "", 1).unwrap();
        let (id, _) = store.verify_login("me", "password1", "ip", 1.0).unwrap();
        let token = store.create_session(id, "ip", "ua", 100).unwrap();
        let file = || std::fs::read(root.join("auth.json")).unwrap();
        let seen = || store.list_sessions(100).unwrap().first().and_then(|row| row.get("lastSeen")).cloned();
        let before = file();
        assert!(store.validate_session(&token, 100.0 + AuthStore::SEEN_EVERY).unwrap().is_some());
        assert_eq!((seen(), file() == before), (Some(json!(100)), true), "negative: a sight within its grain is not written");
        assert!(store.validate_session(&token, 101.0 + AuthStore::SEEN_EVERY).unwrap().is_some());
        assert_eq!((seen(), file() == before), (Some(json!(701)), false), "a sight after it is");
        std::fs::remove_dir_all(&root).unwrap();
    }

    #[test]
    fn the_last_admin_stays() {
        let root = folder("last");
        let store = AuthStore::open(&root.join("auth.db"), "s");
        store.create_user("me", "password1", "admin", 1).unwrap();
        assert_eq!(store.set_role("me", "viewer").unwrap_err().message, "cannot demote the last admin");
        assert_eq!(store.delete_user("me").unwrap_err().status, 400);
        store.create_user("two", "password2", "viewer", 1).unwrap();
        assert!(store.set_role("two", "admin").is_ok());
        assert!(store.delete_user("two").is_ok());
        assert_eq!(store.delete_user("nobody").unwrap_err().status, 404);
        std::fs::remove_dir_all(&root).unwrap();
    }

    #[test]
    fn a_document_that_does_not_read_is_no_empty_one() {
        let root = folder("broken");
        std::fs::write(root.join("auth.json"), "{").unwrap();
        let store = AuthStore::open(&root.join("auth.db"), "s");
        assert_eq!(store.enabled().unwrap_err().status, 503);
        assert!(root.join("auth.json.unreadable-s").exists());
        std::fs::remove_dir_all(&root).unwrap();
    }

    #[test]
    fn the_fleet_token_is_made_once_and_matched_whole() {
        let root = folder("fleet");
        let store = AuthStore::open(&root.join("auth.db"), "s");
        assert!(!store.fleet_token_verify("").unwrap());
        let token = store.fleet_token_ensure().unwrap();
        assert!(token.starts_with("caravan-"));
        assert_eq!(store.fleet_token_ensure().unwrap(), token);
        assert!(store.fleet_token_verify(&token).unwrap());
        assert!(!store.fleet_token_verify("caravan-").unwrap());
        assert_ne!(store.fleet_token_regenerate().unwrap(), token);
        std::fs::remove_dir_all(&root).unwrap();
    }
}

#[cfg(test)]
mod from_the_old_file {
    use super::*;

    /// A file sqlite3 made: an old account from before roles, more rows than one page holds, and a value past a page.
    fn store() -> (PathBuf, AuthStore) {
        let root = std::env::temp_dir().join(format!("auth-old-{}", std::process::id()));
        std::fs::create_dir_all(&root).unwrap();
        std::fs::write(root.join("auth.db"), include_bytes!("../../tests/tables/auth.db")).unwrap();
        let store = AuthStore::open(&root.join("auth.db"), "s");
        (root, store)
    }

    #[test]
    fn its_accounts_and_sessions_are_all_here() {
        let (root, store) = store();
        let users = store.list_users().unwrap();
        assert_eq!(users.len(), 42);
        assert_eq!(users.first().and_then(|row| row.get("role")), Some(&json!("admin")));
        assert_eq!(users.get(1).and_then(|row| row.get("role")), Some(&json!("viewer")));
        assert_eq!(users.get(41).and_then(|row| row.get("username")), Some(&json!("user-39")));
        assert_eq!(store.verify_login("old-admin", "password-of-old", "", 1.0).unwrap().0, 1);
        assert_eq!(store.verify_login("user-39", "password-39", "", 1.0).unwrap().0, 42);
        assert_eq!(store.verify_login("old-admin", "other", "", 1.0).unwrap_err().status, 401);
        assert_eq!(store.fleet_token().unwrap(), "caravan-test-token");
        let sessions = store.list_sessions(100).unwrap();
        assert_eq!(sessions.len(), 31);
        assert!(sessions.iter().any(|row| row.get("ua").and_then(Value::as_str) == Some(&"x".repeat(60))));
        assert!(root.join("auth.json").exists());
        std::fs::remove_dir_all(&root).unwrap();
    }
}
