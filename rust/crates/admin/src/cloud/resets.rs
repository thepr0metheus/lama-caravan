//! Banked OpenAI resets. A reset is spent once: the attempt is written down before it is asked for, and a
//! retry names the same request id.

use super::call::Upstream;
use super::data::CloudData;
use super::subscription::SubscriptionAuth;
use crate::app::App;
use crate::common::cloud_sources::CloudSources;
use crate::common::misc::{IsoMoment, SubscriptionResetJournal};
use plumbing::http_client::HttpError;
use rules::{AppError, Coerce, PythonJson};
use serde_json::{Value, json};
use std::time::Duration;

/// The desk of the resets.
pub struct SubscriptionResetDesk<'app> {
    app: &'app App,
}

impl<'app> SubscriptionResetDesk<'app> {
    const URL: &'static str = "https://chatgpt.com/backend-api/wham/rate-limit-reset-credits";
    const OUTCOMES: [&'static str; 4] = ["reset", "already_redeemed", "nothing_to_reset", "no_credit"];

    /// The desk of `app`.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    fn journal(&self) -> SubscriptionResetJournal {
        SubscriptionResetJournal::new(self.app.paths.subscription_resets_file.clone())
    }

    /// The account, and the one whose limits it spends.
    fn account_of(&self, account_id: &str) -> Result<(Value, String), AppError> {
        let cloud = CloudData::of(self.app);
        let (data, secrets) = (cloud.load(), cloud.secrets());
        let sources = CloudSources::new(&data, Some(&secrets));
        let account = sources.canonical(account_id).filter(|account| CloudSources::is_subscription(account));
        let account = account.ok_or_else(|| AppError::new("an individual ChatGPT subscription is required"))?;
        let owner = sources.quota_owner(account_id).map_or_else(String::new, |owner| Coerce::text(owner.get("id")));
        Ok((account.clone(), owner))
    }

    fn ask(&self, account: &Value, method: &str, payload: Option<&Value>) -> Result<Value, AppError> {
        let (token, account_id) = SubscriptionAuth::of(self.app).fields_of(account)?;
        let upstream = Upstream::of(self.app);
        let mut fields = upstream.named(vec![
            ("Authorization".to_string(), format!("Bearer {token}")),
            ("chatgpt-account-id".to_string(), account_id),
            ("originator".to_string(), "pi".to_string()),
            ("Accept".to_string(), "application/json".to_string()),
        ]);
        // absent-ok: a GET has no body.
        let body = payload.map(PythonJson::spaced).unwrap_or_default();
        if payload.is_some() {
            fields.push(("Content-Type".to_string(), "application/json".to_string()));
        }
        let url = if method == "POST" { format!("{}/consume", Self::URL) } else { Self::URL.to_string() };
        upstream.json(method, &url, &fields, body.as_bytes(), Duration::from_secs(15)).map_err(|error| match error {
            HttpError::Status(code, _) => AppError::with_status(format!("ChatGPT reset endpoint: HTTP {code}"), 502),
            other => AppError::with_status(format!("ChatGPT reset endpoint unavailable: {other}"), 502),
        })
    }

    /// What resets the account has banked, and which of its attempts are still open.
    pub fn list(&self, account_id: &str) -> Result<Value, AppError> {
        let (account, owner) = self.account_of(account_id)?;
        let unavailable = || AppError::with_status("ChatGPT reset details are unavailable", 502);
        let payload = self.ask(&account, "GET", None)?;
        let rows = payload.get("credits").and_then(Value::as_array).ok_or_else(unavailable)?;
        let count =
            payload.get("available_count").filter(|count| count.is_i64() || count.is_boolean()).ok_or_else(unavailable)?;
        let mut credits = Vec::new();
        for row in rows {
            if !row.is_object() || !Coerce::truthy(row.get("id")) {
                return Err(AppError::with_status("ChatGPT returned an invalid reset credit", 502));
            }
            let mut expired = false;
            if Coerce::truthy(row.get("expires_at")) {
                let when = row.get("expires_at").and_then(Value::as_str).and_then(IsoMoment::epoch);
                let when = when.ok_or_else(|| AppError::with_status("ChatGPT returned an invalid reset expiry", 502))?;
                expired = when <= self.app.now();
            }
            let word = |key: &str| row.get(key).cloned().unwrap_or(Value::Null);
            let usable = row.get("status").and_then(Value::as_str) == Some("available")
                && row.get("reset_type").and_then(Value::as_str) == Some("codex_rate_limits")
                && !expired;
            credits.push(json!({
                "id": word("id"), "resetType": word("reset_type"), "status": word("status"), "expiresAt": word("expires_at"),
                "title": word("title"), "description": word("description"), "usable": usable,
            }));
        }
        let journal = self.journal().read().map_err(|error| AppError::with_status(error, 500))?;
        let attempts = journal.get("attempts").and_then(Value::as_object).into_iter().flatten();
        let pending: Vec<Value> = attempts
            .filter(|(_, row)| Coerce::text(row.get("accountId")) == owner && !Coerce::truthy(row.get("outcome")))
            .map(|(key, row)| json!({"idempotencyKey": key, "creditId": row.get("creditId")}))
            .collect();
        Ok(json!({
            "ok": true, "accountId": account.get("id"), "usageAccountId": owner, "availableCount": count,
            "credits": credits, "pending": pending, "readAt": self.app.now(),
        }))
    }

    fn is_canonical_uuid(key: &str) -> bool {
        let groups: Vec<&str> = key.split('-').collect();
        let sizes = [8, 4, 4, 4, 12];
        groups.len() == sizes.len()
            && groups.iter().zip(sizes).all(|(group, size)| {
                group.len() == size && group.chars().all(|letter| letter.is_ascii_digit() || ('a'..='f').contains(&letter))
            })
    }

    /// One reset spent.
    pub fn consume(
        &self,
        account_id: &str,
        credit_id: Option<&Value>,
        key: Option<&Value>,
        confirmed: Option<&Value>,
    ) -> Result<Value, AppError> {
        if confirmed != Some(&json!(true)) {
            return Err(AppError::new("explicit reset confirmation is required"));
        }
        let key = key.and_then(Value::as_str).filter(|key| Self::is_canonical_uuid(key));
        let key = key.ok_or_else(|| AppError::new("idempotencyKey must be a UUID"))?;
        let credit_id = credit_id.and_then(Value::as_str).filter(|credit| !credit.is_empty() && credit.chars().count() <= 256);
        let credit_id = credit_id.ok_or_else(|| AppError::new("creditId is required"))?;
        let (account, owner) = self.account_of(account_id)?;
        let journal = self.journal();
        let answer = journal
            .locked(|mut data| Ok(self.consume_held(&journal, &mut data, (&account, &owner), (account_id, credit_id, key))));
        answer.map_err(|error| AppError::with_status(error, 500))?
    }

    fn consume_held(
        &self,
        journal: &SubscriptionResetJournal,
        data: &mut Value,
        whose: (&Value, &str),
        asked: (&str, &str, &str),
    ) -> Result<Value, AppError> {
        let (account, owner) = whose;
        let (account_id, credit_id, key) = asked;
        let written = |error: String| AppError::with_status(error, 500);
        let attempts = data.get("attempts").cloned().unwrap_or_else(|| json!({}));
        if let Some(old) = attempts.get(key) {
            if Coerce::text(old.get("accountId")) != owner || Coerce::text(old.get("creditId")) != credit_id {
                return Err(AppError::with_status("this request id belongs to another reset", 409));
            }
            if Coerce::truthy(old.get("outcome")) {
                return Ok(json!({"ok": true, "outcome": old.get("outcome"), "idempotencyKey": key}));
            }
        } else {
            self.refuse_while_open(&attempts, owner, account_id, credit_id)?;
            let row = json!({"accountId": owner, "creditId": credit_id, "at": self.app.now()});
            if let Some(rows) = data.get_mut("attempts") {
                Coerce::put(rows, key, row);
            }
            journal.write(data).map_err(written)?;
        }
        let result = self.ask(account, "POST", Some(&json!({"credit_id": credit_id, "redeem_request_id": key})))?;
        let outcome = Coerce::text(result.get("code"));
        if !Self::OUTCOMES.contains(&outcome.as_str()) {
            return Err(AppError::with_status("unknown reset outcome; retry with the same request id", 502));
        }
        if let Some(row) = data.get_mut("attempts").and_then(|rows| rows.get_mut(key)) {
            Coerce::put(row, "outcome", json!(outcome));
        }
        if outcome == "reset" || outcome == "already_redeemed" {
            let now = self.app.now();
            if data.get("resets").is_none() {
                Coerce::put(data, "resets", json!({}));
            }
            if let Some(resets) = data.get_mut("resets") {
                Coerce::put(resets, owner, json!(now));
            }
        }
        journal.write(data).map_err(written)?;
        Ok(json!({"ok": true, "outcome": outcome, "idempotencyKey": key}))
    }

    /// A new attempt waits for the one still open, and takes only a credit that is there to take.
    fn refuse_while_open(&self, attempts: &Value, owner: &str, account_id: &str, credit_id: &str) -> Result<(), AppError> {
        let rows = attempts.as_object().into_iter().flatten();
        if rows.into_iter().any(|(_, row)| Coerce::text(row.get("accountId")) == owner && !Coerce::truthy(row.get("outcome"))) {
            return Err(AppError::with_status("resolve the pending reset using its original request id first", 409));
        }
        let listed = self.list(account_id)?;
        let credits = listed.get("credits").and_then(Value::as_array).into_iter().flatten();
        if !credits
            .into_iter()
            .any(|row| row.get("id").and_then(Value::as_str) == Some(credit_id) && Coerce::truthy(row.get("usable")))
        {
            return Err(AppError::with_status("the selected reset is no longer available", 409));
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_request_id_is_a_uuid_as_python_writes_it() {
        assert!(SubscriptionResetDesk::is_canonical_uuid("123e4567-e89b-12d3-a456-426614174000"));
        assert!(!SubscriptionResetDesk::is_canonical_uuid("123E4567-E89B-12D3-A456-426614174000"));
        assert!(!SubscriptionResetDesk::is_canonical_uuid("123e4567e89b12d3a456426614174000"));
        assert!(!SubscriptionResetDesk::is_canonical_uuid("x"));
    }
}
