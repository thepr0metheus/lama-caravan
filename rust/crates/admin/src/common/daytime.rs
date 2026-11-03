//! Time of day "HH:MM": one parsing rule for every schedule.

use rules::{AppError, Coerce};
use serde_json::Value;

/// The rule.
pub struct Daytime;

impl Daytime {
    /// Normalized "HH:MM". An empty value is `default`; garbage is refused, not silently defaulted: a schedule that quietly drifted to a different time would only be noticed by its consequences.
    pub fn hhmm(value: Option<&Value>, default: &str) -> Result<String, AppError> {
        let empty = value.is_none_or(|value| value.is_null() || value.as_str() == Some(""));
        let text = if empty { default.to_string() } else { Coerce::text(value) };
        Self::of_text(Coerce::strip(&text))
    }

    /// The same of a text.
    pub fn of_text(raw: &str) -> Result<String, AppError> {
        let digits = |text: &str| text.chars().all(|letter| letter.is_ascii_digit());
        let shape = raw
            .split_once(':')
            .filter(|(hour, minute)| (1..=2).contains(&hour.len()) && minute.len() == 2 && digits(hour) && digits(minute));
        let Some((hour, minute)) = shape else {
            return Err(AppError::new(format!("time must look like HH:MM, got: {raw}")));
        };
        let (hour, minute): (u32, u32) = (
            hour.parse().map_err(|_| AppError::new(format!("time out of range: {raw}")))?,
            minute.parse().map_err(|_| AppError::new(format!("time out of range: {raw}")))?,
        );
        if hour > 23 || minute > 59 {
            return Err(AppError::new(format!("time out of range: {raw}")));
        }
        Ok(format!("{hour:02}:{minute:02}"))
    }

    /// "HH:MM" as minutes since midnight.
    pub fn minutes_of_day(value: &str) -> Result<i64, AppError> {
        let clean = Self::of_text(Coerce::strip(value))?;
        let number = |text: &str| text.parse::<i64>().map_err(|_| AppError::new(format!("time out of range: {clean}")));
        let (hour, minute) =
            clean.split_once(':').ok_or_else(|| AppError::new(format!("time must look like HH:MM, got: {clean}")))?;
        Ok(number(hour)? * 60 + number(minute)?)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn a_time_is_normal_or_refused() {
        assert_eq!(Daytime::hhmm(Some(&json!("9:05")), "03:00").unwrap(), "09:05");
        assert_eq!(Daytime::hhmm(None, "03:00").unwrap(), "03:00");
        assert_eq!(Daytime::hhmm(Some(&json!("")), "03:00").unwrap(), "03:00");
        assert_eq!(Daytime::hhmm(Some(&json!("24:00")), "03:00").unwrap_err().message, "time out of range: 24:00");
        assert_eq!(Daytime::hhmm(Some(&json!("noon")), "03:00").unwrap_err().message, "time must look like HH:MM, got: noon");
        assert_eq!(Daytime::minutes_of_day("01:30").unwrap(), 90);
    }
}
