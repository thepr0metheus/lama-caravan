//! A JSON value read as the caravan's settings have always been read.
//!
//! The settings files are written by hand as well as by the board, and the rules of what a value
//! means came from Python: `int(route.get("port"))` takes `22001`, `"22001"` and `22001.0`, and `x or ""` takes
//! `0` for nothing.

use serde_json::Value;

/// How Python's `bool`, `str` and `int` read a JSON value.
pub struct Coerce;

impl Coerce {
    /// `bool(value)`: nothing, `null`, `false`, zero, `""`, `[]` and `{}` are false.
    pub fn truthy(value: Option<&Value>) -> bool {
        match value {
            None | Some(Value::Null) => false,
            Some(Value::Bool(flag)) => *flag,
            Some(Value::Number(number)) => number.as_f64().is_some_and(|n| n != 0.0),
            Some(Value::String(text)) => !text.is_empty(),
            Some(Value::Array(items)) => !items.is_empty(),
            Some(Value::Object(fields)) => !fields.is_empty(),
        }
    }

    /// `str(value or "")`. A list or an object has no text a setting could mean: its JSON stands in for Python's
    /// `repr`, and no rule compares it to anything.
    pub fn text(value: Option<&Value>) -> String {
        let Some(value) = value.filter(|value| Self::truthy(Some(*value))) else {
            return String::new();
        };
        match value {
            Value::String(text) => text.clone(),
            Value::Bool(_) => "True".to_string(),
            other => other.to_string(),
        }
    }

    /// The fields of an object, to lay over another: what is no object has none.
    pub fn fields(value: &Value) -> serde_json::Map<String, Value> {
        match value {
            Value::Object(fields) => fields.clone(),
            _ => serde_json::Map::new(),
        }
    }

    /// `out.update(more)`: the fields of `more` at the end of `out`, in their order.
    pub fn extend(out: &mut Value, more: &Value) {
        if let (Value::Object(fields), Value::Object(said)) = (out, more) {
            for (key, value) in said {
                fields.insert(key.clone(), value.clone());
            }
        }
    }

    /// The rows a document says: what is not there, or is not a list, is no rows.
    pub fn list(value: Option<&Value>) -> Vec<Value> {
        // absent-ok: this reading says it in its name; a caller that must tell the two apart reads the value itself.
        value.and_then(Value::as_array).cloned().unwrap_or_default()
    }

    /// A figure of a document: one not said, or that is no number, adds nothing.
    pub fn float_or_zero(value: Option<&Value>) -> f64 {
        // absent-ok: this reading says it in its name; a caller that must tell the two apart reads the value itself.
        value.and_then(Self::float).unwrap_or(0.0)
    }

    /// `int(value or 0)` of a figure the board only adds up or shows: a word that is no number counts as none.
    pub fn whole(value: Option<&Value>) -> i64 {
        // absent-ok: this reading is for what is shown or added up; a reader that must refuse keeps `int_or_zero`.
        Self::int_or_zero(value).unwrap_or(0)
    }

    /// A whole number the program itself wrote: what is not there is none.
    pub fn i64_or_zero(value: Option<&Value>) -> i64 {
        // absent-ok: this reading says it in its name; a caller that must tell the two apart reads the value itself.
        value.and_then(Value::as_i64).unwrap_or(0)
    }

    /// `str(value)` of a value that is there: `0` is "0" and `False` is "False", unlike `text`; a key not there is "", as `config.get(key, "")` has it.
    pub fn str_of(value: Option<&Value>) -> String {
        match value {
            None => String::new(),
            Some(Value::Null) => "None".to_string(),
            Some(Value::Bool(flag)) => if *flag { "True" } else { "False" }.to_string(),
            Some(Value::String(text)) => text.clone(),
            Some(other) => other.to_string(),
        }
    }

    /// `str(value or "").strip()`.
    pub fn stripped(value: Option<&Value>) -> String {
        Self::strip(&Self::text(value)).to_string()
    }

    /// An id as `CloudPools._id` reads it: a string or a whole number, stripped, and "" for anything else.
    pub fn word(value: Option<&Value>) -> String {
        match value {
            Some(Value::String(_)) => Self::stripped(value),
            Some(Value::Number(number)) if number.is_i64() || number.is_u64() => Self::stripped(value),
            _ => String::new(),
        }
    }

    /// A size as `_positive_int` reads it: what `int()` takes, above zero. A flag, nothing and rubbish are no size.
    pub fn positive(value: Option<&Value>) -> Option<i64> {
        Self::int(value.filter(|value| !value.is_boolean())?).filter(|size| *size > 0)
    }

    /// `value[key] = said`, when `value` is an object; what is not one has nowhere to keep it.
    pub fn put(value: &mut Value, key: &str, said: Value) {
        if let Value::Object(fields) = value {
            fields.insert(key.to_string(), said);
        }
    }

    /// `value.pop(key, None)`, when `value` is an object.
    pub fn take(value: &mut Value, key: &str) -> Option<Value> {
        value.as_object_mut().and_then(|fields| fields.shift_remove(key))
    }

    /// `str.strip()`: Unicode's white space and the four separators Python counts with it.
    pub fn strip(text: &str) -> &str {
        text.trim_matches(|letter: char| letter.is_whitespace() || ('\x1c'..='\x1f').contains(&letter))
    }

    /// `int(value)`, or `None` where Python raises. A number past `i64` raises too: no setting means it.
    pub fn int(value: &Value) -> Option<i64> {
        match value {
            Value::Bool(flag) => Some(i64::from(*flag)),
            Value::Number(number) => number.as_i64().or_else(|| number.as_f64().map(f64::trunc).and_then(Self::of_float)),
            Value::String(text) => Self::int_of_text(text),
            Value::Null | Value::Array(_) | Value::Object(_) => None,
        }
    }

    /// `float(value)`, or `None` where Python raises.
    pub fn float(value: &Value) -> Option<f64> {
        match value {
            Value::Bool(flag) => Some(f64::from(u8::from(*flag))),
            Value::Number(number) => number.as_f64(),
            Value::String(text) => Self::strip(text).parse().ok(),
            Value::Null | Value::Array(_) | Value::Object(_) => None,
        }
    }

    /// `int(value or 0)`, or `None` where Python raises.
    pub fn int_or_zero(value: Option<&Value>) -> Option<i64> {
        match value.filter(|value| Self::truthy(Some(*value))) {
            None => Some(0),
            Some(value) => Self::int(value),
        }
    }

    fn of_float(number: f64) -> Option<i64> {
        const LIMIT: f64 = 9.2e18;
        (number.abs() < LIMIT).then_some(number as i64)
    }

    /// `int("…")`: spaces around, one sign, digits with single `_` between them.
    fn int_of_text(text: &str) -> Option<i64> {
        let trimmed = Self::strip(text);
        let (negative, digits) = match trimmed.strip_prefix('-') {
            Some(rest) => (true, rest),
            None => (false, trimmed.strip_prefix('+').unwrap_or(trimmed)),
        };
        if digits.is_empty() || digits.starts_with('_') || digits.ends_with('_') || digits.contains("__") {
            return None;
        }
        let plain: String = digits.chars().filter(|letter| *letter != '_').collect();
        if !plain.chars().all(|letter| letter.is_ascii_digit()) {
            return None;
        }
        let magnitude = plain.parse::<i64>().ok()?;
        Some(if negative { -magnitude } else { magnitude })
    }

    /// `round(value, digits)`: by the exact value of the float, as Python rounds it.
    pub fn rounded(value: f64, digits: usize) -> f64 {
        // absent-ok: Rust's own digits of a float always read back; only NaN and the infinities print otherwise, and they read back too.
        format!("{value:.digits$}").parse().unwrap_or(value)
    }

    /// The first `count` letters of `text`: `text[:count]`.
    pub fn first_letters(text: &str, count: usize) -> &str {
        match text.char_indices().nth(count) {
            Some((at, _)) => text.get(..at).unwrap_or(text),
            None => text,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn an_id_is_a_word_or_a_whole_number() {
        for (raw, want) in [
            (json!(" a "), "a"),
            (json!(77), "77"),
            (json!(18_446_744_073_709_551_615u64), "18446744073709551615"),
            (json!(0), ""),
            (json!(1.5), ""),
            (json!(true), ""),
            (json!(null), ""),
            (json!(["a"]), ""),
        ] {
            assert_eq!(Coerce::word(Some(&raw)), want, "{raw}");
        }
        assert_eq!(Coerce::word(None), "");
    }

    #[test]
    fn a_size_is_what_int_takes_above_zero() {
        for (raw, want) in [
            (json!(5), Some(5)),
            (json!("5"), Some(5)),
            (json!(5.9), Some(5)),
            (json!(0), None),
            (json!(-1), None),
            (json!(true), None),
            (json!("x"), None),
            (json!(null), None),
        ] {
            assert_eq!(Coerce::positive(Some(&raw)), want, "{raw}");
        }
        assert_eq!(Coerce::positive(None), None);
    }

    #[test]
    fn reads_a_value_as_python_does() {
        for (raw, want) in [
            (json!(22001), Some(22001)),
            (json!("22001"), Some(22001)),
            (json!(" 7 "), Some(7)),
            (json!("+5"), Some(5)),
            (json!("-5"), Some(-5)),
            (json!("1_000"), Some(1000)),
            (json!(22001.9), Some(22001)),
            (json!(true), Some(1)),
            (json!(9.1e18), Some(9_100_000_000_000_000_000)),
            (json!(9.2e18), None),
            (json!("12.5"), None),
            (json!("_1"), None),
            (json!("1__0"), None),
            (json!(""), None),
            (json!(null), None),
            (json!([]), None),
            (json!({}), None),
        ] {
            assert_eq!(Coerce::int(&raw), want, "{raw}");
        }
        assert_eq!(Coerce::int_or_zero(None), Some(0));
        assert_eq!(Coerce::int_or_zero(Some(&json!(""))), Some(0));
        assert_eq!(Coerce::int_or_zero(Some(&json!("x"))), None);
    }

    #[test]
    fn takes_nothing_for_what_python_takes_for_nothing() {
        for raw in [json!(null), json!(false), json!(0), json!(0.0), json!(""), json!([]), json!({})] {
            assert!(!Coerce::truthy(Some(&raw)), "{raw}");
            assert_eq!(Coerce::text(Some(&raw)), "");
        }
        assert_eq!(Coerce::text(Some(&json!(3))), "3");
        assert_eq!(Coerce::text(Some(&json!(true))), "True");
        assert_eq!(Coerce::stripped(Some(&json!("  a "))), "a");
    }

    #[test]
    fn cuts_by_letters() {
        assert_eq!(Coerce::first_letters("яблоко", 3), "ябл");
        assert_eq!(Coerce::first_letters("ab", 3), "ab");
    }
}
