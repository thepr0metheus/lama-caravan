//! A JSON value as Python's `json.dumps` writes it, to the byte.
//!
//! Some of what the caravan says is JSON inside a string: the arguments of a tool call, what a tool answered. A client or a model reads
//! that text as text, so two languages that write it differently would be two answers. And a stream's chunks are written here as Python
//! writes them, so that a client gets the same bytes from either. What goes to a provider whole is one document and only its meaning
//! counts: it is written by `serde_json`, without the escapes.

use serde_json::Value;

/// The two spacings the caravan uses, and whether letters past ASCII are escaped.
#[derive(Debug, Clone, Copy)]
struct Spacing {
    between: &'static str,
    after_key: &'static str,
    ascii: bool,
}

/// `json.dumps(value)`, in the ways the caravan calls it.
pub struct PythonJson;

impl PythonJson {
    /// `json.dumps(value)`: `", "` and `": "`.
    pub fn spaced(value: &Value) -> String {
        Self::written(value, Spacing { between: ", ", after_key: ": ", ascii: true })
    }

    /// `json.dumps(value, ensure_ascii=False)`.
    pub fn spaced_letters(value: &Value) -> String {
        Self::written(value, Spacing { between: ", ", after_key: ": ", ascii: false })
    }

    /// `json.dumps(value, separators=(",", ":"))`.
    pub fn compact(value: &Value) -> String {
        Self::written(value, Spacing { between: ",", after_key: ":", ascii: true })
    }

    /// `json.dumps(value, ensure_ascii=False, separators=(",", ":"))`.
    pub fn compact_letters(value: &Value) -> String {
        Self::written(value, Spacing { between: ",", after_key: ":", ascii: false })
    }

    /// `json.dumps(value, indent=2)`: what a document on disk is written as.
    pub fn indented(value: &Value) -> String {
        let mut out = String::new();
        Self::write_indented(&mut out, value, (0, "  "), true);
        out
    }

    /// `json.dumps(value, ensure_ascii=False, indent=2)`: what the controller answers, and the documents a person reads.
    pub fn indented_letters(value: &Value) -> String {
        let mut out = String::new();
        Self::write_indented(&mut out, value, (0, "  "), false);
        out
    }

    /// `json.dumps(value, ensure_ascii=False, indent=1)`: the model catalogue's file.
    pub fn indented_once_letters(value: &Value) -> String {
        let mut out = String::new();
        Self::write_indented(&mut out, value, (0, " "), false);
        out
    }

    fn written(value: &Value, spacing: Spacing) -> String {
        let mut out = String::new();
        Self::write(&mut out, value, spacing);
        out
    }

    fn write_indented(out: &mut String, value: &Value, at: (usize, &str), ascii: bool) {
        let (depth, step) = at;
        let scalar = Spacing { between: ", ", after_key: ": ", ascii };
        match value {
            Value::Array(items) if !items.is_empty() => {
                out.push('[');
                for (at, item) in items.iter().enumerate() {
                    out.push_str(if at > 0 { ",\n" } else { "\n" });
                    out.push_str(&step.repeat(depth + 1));
                    Self::write_indented(out, item, (depth + 1, step), ascii);
                }
                out.push('\n');
                out.push_str(&step.repeat(depth));
                out.push(']');
            }
            Value::Object(fields) if !fields.is_empty() => {
                out.push('{');
                for (at, (key, item)) in fields.iter().enumerate() {
                    out.push_str(if at > 0 { ",\n" } else { "\n" });
                    out.push_str(&step.repeat(depth + 1));
                    Self::string(out, key, ascii);
                    out.push_str(": ");
                    Self::write_indented(out, item, (depth + 1, step), ascii);
                }
                out.push('\n');
                out.push_str(&step.repeat(depth));
                out.push('}');
            }
            other => Self::write(out, other, scalar),
        }
    }

    fn write(out: &mut String, value: &Value, spacing: Spacing) {
        match value {
            Value::Null => out.push_str("null"),
            Value::Bool(flag) => out.push_str(if *flag { "true" } else { "false" }),
            Value::Number(number) => match number.as_f64().filter(|_| number.is_f64()) {
                Some(float) => out.push_str(&Self::float(float)),
                None => out.push_str(&number.to_string()),
            },
            Value::String(text) => Self::string(out, text, spacing.ascii),
            Value::Array(items) => {
                out.push('[');
                for (at, item) in items.iter().enumerate() {
                    if at > 0 {
                        out.push_str(spacing.between);
                    }
                    Self::write(out, item, spacing);
                }
                out.push(']');
            }
            Value::Object(fields) => {
                out.push('{');
                for (at, (key, item)) in fields.iter().enumerate() {
                    if at > 0 {
                        out.push_str(spacing.between);
                    }
                    Self::string(out, key, spacing.ascii);
                    out.push_str(spacing.after_key);
                    Self::write(out, item, spacing);
                }
                out.push('}');
            }
        }
    }

    /// A string, with ASCII escapes when `ascii`: `ensure_ascii`, a letter past the basic plane as its two surrogates.
    fn string(out: &mut String, text: &str, ascii: bool) {
        out.push('"');
        for letter in text.chars() {
            match letter {
                '"' => out.push_str("\\\""),
                '\\' => out.push_str("\\\\"),
                '\n' => out.push_str("\\n"),
                '\r' => out.push_str("\\r"),
                '\t' => out.push_str("\\t"),
                '\u{8}' => out.push_str("\\b"),
                '\u{c}' => out.push_str("\\f"),
                ' '..='~' => out.push(letter),
                other if !ascii && u32::from(other) >= 0x20 => out.push(other),
                other => {
                    let mut units = [0u16; 2];
                    for unit in other.encode_utf16(&mut units).iter() {
                        out.push_str(&format!("\\u{unit:04x}"));
                    }
                }
            }
        }
        out.push('"');
    }

    /// `repr(float)`: the shortest digits that read back, in exponent form below 1e-4 and from 1e16.
    fn float(value: f64) -> String {
        let scientific = format!("{value:e}");
        let Some((digits, exponent)) = scientific.split_once('e') else {
            return scientific;
        };
        // absent-ok: Rust's exponent form always has a whole exponent; zero leaves the number in its plain form.
        let exponent: i32 = exponent.parse().unwrap_or(0);
        if (-4..16).contains(&exponent) {
            let plain = format!("{value}");
            return if plain.contains('.') { plain } else { format!("{plain}.0") };
        }
        let sign = if exponent < 0 { '-' } else { '+' };
        format!("{digits}e{sign}{:02}", exponent.abs())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn a_document_is_indented_as_python_indents_it() {
        let value = json!({"a": [1, {"b": []}, {}], "c": {"d": "ю\n"}, "e": 1.0});
        let want = "{\n  \"a\": [\n    1,\n    {\n      \"b\": []\n    },\n    {}\n  ],\n  \"c\": {\n    \"d\": \"ю\\n\"\n  },\n  \"e\": 1.0\n}";
        assert_eq!(PythonJson::indented_letters(&value), want);
        assert_eq!(PythonJson::indented(&json!({"d": "ю"})), "{\n  \"d\": \"\\u044e\"\n}");
    }

    #[test]
    fn the_two_writers_a_file_of_the_controller_is_written_by() {
        let value = json!({"a": [1, "ю"], "b": {"c": null}});
        assert_eq!(PythonJson::compact_letters(&value), "{\"a\":[1,\"ю\"],\"b\":{\"c\":null}}");
        assert_eq!(
            PythonJson::indented_once_letters(&value),
            "{\n \"a\": [\n  1,\n  \"ю\"\n ],\n \"b\": {\n  \"c\": null\n }\n}"
        );
    }

    #[test]
    fn a_float_is_written_as_python_repr_writes_it() {
        for (value, want) in [
            (0.0, "0.0"),
            (1.0, "1.0"),
            (0.7, "0.7"),
            (-2.5, "-2.5"),
            (100000.0, "100000.0"),
            (0.0001, "0.0001"),
            (0.00001, "1e-05"),
            (1.5e-7, "1.5e-07"),
            (1e15, "1000000000000000.0"),
            (1e16, "1e+16"),
            (1.5e22, "1.5e+22"),
            (1e100, "1e+100"),
        ] {
            assert_eq!(PythonJson::float(value), want, "{value}");
        }
    }

    #[test]
    fn a_whole_number_stays_whole_and_a_float_stays_a_float() {
        assert_eq!(PythonJson::compact(&json!([1, 1.0, -3, 18_446_744_073_709_551_615u64])), "[1,1.0,-3,18446744073709551615]");
    }
}
