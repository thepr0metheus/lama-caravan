//! The credit the operator says a key account has left, and from when it counts. A provider does not tell: the board holds the figure the operator types and the moment it was typed, and takes from it what went through the caravan since. An estimate, said as one wherever it is shown.

use rules::{AppError, Coerce};
use serde_json::{Value, json};

/// The figure is the account's `credit`, `{"amountUsd", "asOf"}`. An edit sends `creditUsd`: blank takes the credit away, the figure it already holds keeps its moment, any other figure starts counting now.
pub struct AccountCredit;

impl AccountCredit {
    /// A figure above this is a typing slip, not a credit.
    const LIMIT: f64 = 1_000_000_000.0;

    /// Dollars, to the cent, from what the operator typed; none for blank. A decimal comma is read as a point: the figure is typed by hand, in the operator's own language.
    pub fn amount(raw: Option<&Value>) -> Result<Option<f64>, AppError> {
        let Some(raw) = raw.filter(|raw| !raw.is_null()) else {
            return Ok(None);
        };
        if raw.as_str().is_some_and(|text| Coerce::strip(text).is_empty()) {
            return Ok(None);
        }
        let text = Coerce::text(Some(raw));
        let value: f64 =
            Coerce::strip(&text).replace(',', ".").parse().map_err(|_| AppError::new("credit must be a number of dollars"))?;
        if !value.is_finite() || !(0.0..=Self::LIMIT).contains(&value) {
            return Err(AppError::new(format!("credit must be a number of dollars from 0 to {}", Self::LIMIT as i64)));
        }
        Ok(Some(Coerce::rounded(value, 2)))
    }

    /// The credit as a file holds it, or none when what stands there is no credit: dropped, not guessed.
    pub fn kept(stored: Option<&Value>) -> Option<Value> {
        let stored = stored?.as_object()?;
        let amount = stored.get("amountUsd").and_then(Value::as_f64).filter(|amount| amount.is_finite() && *amount >= 0.0)?;
        let as_of = stored.get("asOf").and_then(Value::as_f64)?;
        Some(json!({"amountUsd": amount, "asOf": as_of.trunc() as i64}))
    }

    /// The `credit` to store, or none. `account` is the stored account with the edit laid over it: an edit that names `creditUsd` replaces the credit, one that does not leaves what is stored.
    pub fn resolve(account: &Value, now: i64) -> Result<Option<Value>, AppError> {
        let stored = Self::kept(account.get("credit"));
        if account.get("creditUsd").is_none() {
            return Ok(stored);
        }
        let Some(amount) = Self::amount(account.get("creditUsd"))? else {
            return Ok(None);
        };
        if let Some(stored) = stored.filter(|stored| stored.get("amountUsd").and_then(Value::as_f64) == Some(amount)) {
            return Ok(Some(stored));
        }
        Ok(Some(json!({"amountUsd": amount, "asOf": now})))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_figure_typed_by_hand_is_read() {
        assert_eq!(AccountCredit::amount(Some(&json!("12,345"))).unwrap(), Some(12.35));
        assert_eq!(AccountCredit::amount(Some(&json!("  "))).unwrap(), None);
        assert_eq!(AccountCredit::amount(None).unwrap(), None);
        assert!(AccountCredit::amount(Some(&json!("x"))).is_err());
        assert!(AccountCredit::amount(Some(&json!(-1))).is_err());
    }

    #[test]
    fn the_same_figure_keeps_its_moment() {
        let account = json!({"credit": {"amountUsd": 5.0, "asOf": 100}, "creditUsd": "5"});
        assert_eq!(AccountCredit::resolve(&account, 200).unwrap(), Some(json!({"amountUsd": 5.0, "asOf": 100})));
        let other = json!({"credit": {"amountUsd": 5.0, "asOf": 100}, "creditUsd": "6"});
        assert_eq!(AccountCredit::resolve(&other, 200).unwrap(), Some(json!({"amountUsd": 6.0, "asOf": 200})));
        let blank = json!({"credit": {"amountUsd": 5.0, "asOf": 100}, "creditUsd": ""});
        assert_eq!(AccountCredit::resolve(&blank, 200).unwrap(), None);
        assert_eq!(AccountCredit::resolve(&json!({"credit": {"amountUsd": true, "asOf": 1}}), 200).unwrap(), None);
    }
}
