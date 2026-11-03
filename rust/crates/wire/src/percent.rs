//! A value as a URL's path carries it.

/// Percent-encoding: Python's `urllib.parse.quote(value, safe="")` and `unquote`.
pub struct Percent;

impl Percent {
    /// `value` with everything but letters, digits and `_.-~` escaped.
    pub fn encode(value: &str) -> String {
        let mut out = String::with_capacity(value.len());
        for byte in value.bytes() {
            if byte.is_ascii_alphanumeric() || matches!(byte, b'_' | b'.' | b'-' | b'~') {
                out.push(char::from(byte));
            } else {
                out.push_str(&format!("%{byte:02X}"));
            }
        }
        out
    }

    /// `value` as Python's `quote(value)` writes it in a path: a slash stays.
    pub fn encode_path(value: &str) -> String {
        Self::encode(value).replace("%2F", "/")
    }

    /// `quote(value, safe=keeping)`: the letters of `keeping` stay as they are.
    pub fn encode_keeping(value: &str, keeping: &str) -> String {
        let mut out = String::with_capacity(value.len());
        for byte in value.bytes() {
            if byte.is_ascii_alphanumeric() || matches!(byte, b'_' | b'.' | b'-' | b'~') || keeping.as_bytes().contains(&byte) {
                out.push(char::from(byte));
            } else {
                out.push_str(&format!("%{byte:02X}"));
            }
        }
        out
    }

    /// `unquote(value)`: `%XX` as the byte it says, a `%` that says none as itself, a `+` as a plus, and bytes that are no UTF-8 as Python's
    /// mark: a name with one in it is nobody's.
    pub fn decode(value: &str) -> String {
        let bytes = value.as_bytes();
        let mut out = Vec::with_capacity(bytes.len());
        let mut at = 0;
        while let Some(byte) = bytes.get(at).copied() {
            let escaped = (byte == b'%').then(|| Self::hex_pair(bytes.get(at + 1..at + 3))).flatten();
            match escaped {
                Some(decoded) => {
                    out.push(decoded);
                    at += 3;
                }
                None => {
                    out.push(byte);
                    at += 1;
                }
            }
        }
        String::from_utf8_lossy(&out).into_owned()
    }

    fn hex_pair(pair: Option<&[u8]>) -> Option<u8> {
        let text = std::str::from_utf8(pair?).ok()?;
        // `from_str_radix` takes a sign, and `%+1` is no escape.
        if !text.bytes().all(|digit| digit.is_ascii_hexdigit()) {
            return None;
        }
        u8::from_str_radix(text, 16).ok()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn encodes_as_python_quote_does() {
        assert_eq!(Percent::encode("gemma-4_12B.it~x"), "gemma-4_12B.it~x");
        assert_eq!(Percent::encode("a b/c"), "a%20b%2Fc");
        assert_eq!(Percent::encode("я"), "%D1%8F");
    }

    #[test]
    fn decodes_as_python_unquote_does() {
        assert_eq!(Percent::decode("gemma%204"), "gemma 4");
        assert_eq!(Percent::decode("a%2Fb%2fc"), "a/b/c");
        assert_eq!(Percent::decode("a+b"), "a+b");
        assert_eq!(Percent::decode("%D1%8F"), "я");
        assert_eq!(Percent::decode("100%"), "100%");
        assert_eq!(Percent::decode("%4"), "%4");
        assert_eq!(Percent::decode("%zz"), "%zz");
        assert_eq!(Percent::decode("%+1"), "%+1");
        assert_eq!(Percent::decode(""), "");
        assert_eq!(Percent::decode("%FF"), "\u{fffd}");
        assert_eq!(Percent::decode("a%FFb%C0%AF"), "a\u{fffd}b\u{fffd}\u{fffd}");
        assert_eq!(Percent::decode("%E2%82"), "\u{fffd}");
    }
}
