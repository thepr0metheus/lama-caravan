//! SHA-256, by the library TLS already rests on.

use ring::digest::{Context, SHA1_FOR_LEGACY_USE_ONLY, SHA256, digest};
use ring::pbkdf2;
use ring::rand::{SecureRandom, SystemRandom};
use std::num::NonZeroU32;

/// A digest under way.
pub struct Sha256 {
    context: Context,
}

impl Sha256 {
    /// A digest of nothing yet.
    pub fn new() -> Self {
        Self { context: Context::new(&SHA256) }
    }

    /// Adds these bytes.
    pub fn update(&mut self, bytes: &[u8]) {
        self.context.update(bytes);
    }

    /// The digest in hexadecimal, as `hexdigest()` writes it.
    pub fn hex(self) -> String {
        let mut out = String::with_capacity(64);
        for byte in self.context.finish().as_ref() {
            out.push_str(&format!("{byte:02x}"));
        }
        out
    }

    /// The digest of these bytes.
    pub fn of(bytes: &[u8]) -> String {
        let mut digest = Self::new();
        digest.update(bytes);
        digest.hex()
    }
}

impl Default for Sha256 {
    fn default() -> Self {
        Self::new()
    }
}

/// SHA-1, where a stamp is all it makes: what tells two lists apart, never what proves anything.
pub struct Sha1;

impl Sha1 {
    /// `hashlib.sha1(bytes).hexdigest()`.
    pub fn of(bytes: &[u8]) -> String {
        digest(&SHA1_FOR_LEGACY_USE_ONLY, bytes).as_ref().iter().map(|byte| format!("{byte:02x}")).collect()
    }

    /// `hashlib.sha1(bytes).digest()`.
    pub fn bytes_of(bytes: &[u8]) -> Vec<u8> {
        digest(&SHA1_FOR_LEGACY_USE_ONLY, bytes).as_ref().to_vec()
    }
}

/// SHA-1 of a stream: how git names a blob, which is what the hub publishes for a file outside LFS.
pub struct Sha1Stream {
    context: Context,
}

impl Sha1Stream {
    /// A digest of nothing yet.
    pub fn new() -> Self {
        Self { context: Context::new(&SHA1_FOR_LEGACY_USE_ONLY) }
    }

    /// Adds these bytes.
    pub fn update(&mut self, bytes: &[u8]) {
        self.context.update(bytes);
    }

    /// The digest in hexadecimal.
    pub fn hex(self) -> String {
        self.context.finish().as_ref().iter().map(|byte| format!("{byte:02x}")).collect()
    }
}

impl Default for Sha1Stream {
    fn default() -> Self {
        Self::new()
    }
}

/// PBKDF2 over HMAC-SHA-256: what a password is kept as.
pub struct Pbkdf2;

impl Pbkdf2 {
    /// `hashlib.pbkdf2_hmac("sha256", password, salt, iterations)`; rounds of nothing are one round.
    pub fn derive(password: &[u8], salt: &[u8], iterations: u32) -> [u8; 32] {
        let mut out = [0u8; 32];
        pbkdf2::derive(
            pbkdf2::PBKDF2_HMAC_SHA256,
            NonZeroU32::new(iterations).unwrap_or(NonZeroU32::MIN),
            salt,
            password,
            &mut out,
        );
        out
    }

    /// Whether `password` is the one kept as `digest`, in constant time.
    pub fn matches(password: &[u8], salt: &[u8], iterations: u32, digest: &[u8]) -> bool {
        pbkdf2::verify(pbkdf2::PBKDF2_HMAC_SHA256, NonZeroU32::new(iterations).unwrap_or(NonZeroU32::MIN), salt, password, digest)
            .is_ok()
    }
}

/// Random bytes from the system, and the words made of them.
pub struct Randomness;

impl Randomness {
    /// `count` bytes; `None` when the system gives none, which nothing here may guess its way around.
    pub fn bytes(count: usize) -> Option<Vec<u8>> {
        let mut out = vec![0u8; count];
        SystemRandom::new().fill(&mut out).ok()?;
        Some(out)
    }

    /// `secrets.token_urlsafe(count)`: `count` random bytes in base64url without padding.
    pub fn token_urlsafe(count: usize) -> Option<String> {
        Some(Self::base64_url(&Self::bytes(count)?))
    }

    /// Base64url without padding.
    pub fn base64_url(bytes: &[u8]) -> String {
        const LETTERS: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
        let mut out = String::with_capacity(bytes.len() * 4 / 3 + 2);
        let (mut held, mut bits) = (0u32, 0u32);
        let mut push = |value: u32| {
            if let Some(letter) = LETTERS.get(value as usize) {
                out.push(char::from(*letter));
            }
        };
        for byte in bytes {
            held = (held << 8) | u32::from(*byte);
            bits += 8;
            while bits >= 6 {
                bits -= 6;
                push((held >> bits) & 63);
            }
        }
        if bits > 0 {
            push((held << (6 - bits)) & 63);
        }
        out
    }

    /// Whether two words are one, in time that does not say how much of them agreed.
    pub fn same(left: &[u8], right: &[u8]) -> bool {
        if left.len() != right.len() {
            return false;
        }
        left.iter().zip(right).fold(0u8, |seen, (one, other)| seen | (one ^ other)) == 0
    }
}

/// Base64 with its standard alphabet and padding: what a recording travels in, and a WebSocket's handshake.
pub struct Base64Std;

impl Base64Std {
    const LETTERS: &'static [u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

    /// `base64.b64encode(raw)`.
    pub fn encode(raw: &[u8]) -> String {
        let mut out = String::with_capacity(raw.len().div_ceil(3) * 4);
        let letter = |value: u32| Self::LETTERS.get(value as usize).map_or('=', |byte| char::from(*byte));
        for chunk in raw.chunks(3) {
            // absent-ok: the last chunk may be short: encoding pads it.
            let first = chunk.first().copied().map_or(0, u32::from);
            // absent-ok: the last chunk may be short: encoding pads it.
            let second = chunk.get(1).copied().map_or(0, u32::from);
            // absent-ok: the last chunk may be short: encoding pads it.
            let third = chunk.get(2).copied().map_or(0, u32::from);
            let held = (first << 16) | (second << 8) | third;
            out.push(letter((held >> 18) & 63));
            out.push(letter((held >> 12) & 63));
            out.push(if chunk.len() > 1 { letter((held >> 6) & 63) } else { '=' });
            out.push(if chunk.len() > 2 { letter(held & 63) } else { '=' });
        }
        out
    }

    /// `base64.b64decode(text, validate=True)`; `None` for a letter outside the alphabet, or a length no encoder writes.
    pub fn decode(text: &str) -> Option<Vec<u8>> {
        if !text.len().is_multiple_of(4) {
            return None;
        }
        let body = text.trim_end_matches('=');
        if text.len() - body.len() > 2 {
            return None;
        }
        let mut out = Vec::with_capacity(body.len() * 3 / 4);
        let (mut held, mut bits) = (0u32, 0u32);
        for byte in body.bytes() {
            let value = Self::LETTERS.iter().position(|letter| *letter == byte)?;
            held = (held << 6) | value as u32;
            bits += 6;
            if bits >= 8 {
                bits -= 8;
                out.push(((held >> bits) & 0xff) as u8);
            }
        }
        Some(out)
    }
}

/// Reading base64url: a token's middle part, and a sign-in's claims.
pub struct Base64Url;

impl Base64Url {
    /// What `text` says, padded or not; `None` for a letter outside the alphabet.
    pub fn decode(text: &str) -> Option<Vec<u8>> {
        let mut out = Vec::with_capacity(text.len() * 3 / 4);
        let (mut held, mut bits) = (0u32, 0u32);
        for byte in text.bytes().filter(|byte| *byte != b'=') {
            let value = match byte {
                b'A'..=b'Z' => byte - b'A',
                b'a'..=b'z' => byte - b'a' + 26,
                b'0'..=b'9' => byte - b'0' + 52,
                b'-' | b'+' => 62,
                b'_' | b'/' => 63,
                _ => return None,
            };
            held = (held << 6) | u32::from(value);
            bits += 6;
            if bits >= 8 {
                bits -= 8;
                out.push(((held >> bits) & 0xff) as u8);
            }
        }
        Some(out)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_password_derives_as_the_standard_says() {
        let digest = Pbkdf2::derive(b"password", b"salt", 1);
        let word: String = digest.iter().map(|byte| format!("{byte:02x}")).collect();
        assert_eq!(word, "120fb6cffcf8b32c43e7225256c4f837a86548c92ccc35480805987cb70be17b");
        assert!(Pbkdf2::matches(b"password", b"salt", 1, &digest));
        assert!(!Pbkdf2::matches(b"other", b"salt", 1, &digest));
    }

    #[test]
    fn base64url_has_no_padding_and_its_two_letters() {
        assert_eq!(Randomness::base64_url(b"\xfb\xff\xfe"), "-__-");
        assert_eq!(Randomness::base64_url(b"f"), "Zg");
        assert_eq!(Randomness::base64_url(b"fo"), "Zm8");
        assert_eq!(Randomness::token_urlsafe(32).unwrap().len(), 43);
        assert!(Randomness::same(b"a", b"a") && !Randomness::same(b"a", b"b") && !Randomness::same(b"a", b"ab"));
    }

    #[test]
    fn the_digest_of_abc_is_what_the_standard_says() {
        assert_eq!(Sha256::of(b"abc"), "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
        assert_eq!(Sha256::of(b""), "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
    }

    #[test]
    fn a_digest_in_parts_is_the_digest_of_the_whole() {
        let mut digest = Sha256::new();
        digest.update(b"a");
        digest.update(b"bc");
        assert_eq!(digest.hex(), Sha256::of(b"abc"));
    }

    #[test]
    fn base64url_reads_back_what_it_writes() {
        for raw in [&b""[..], b"a", b"ab", b"abc", b"\xff\xfe\xfd\x00"] {
            assert_eq!(Base64Url::decode(&Randomness::base64_url(raw)).unwrap(), raw);
        }
        assert_eq!(Base64Url::decode("YWI=").unwrap(), b"ab");
        assert!(Base64Url::decode("a b").is_none());
    }

    #[test]
    fn base64_is_written_and_read_as_python_does() {
        assert_eq!(Base64Std::encode(b"abc"), "YWJj");
        assert_eq!(Base64Std::encode(b"ab"), "YWI=");
        assert_eq!(Base64Std::encode(b"a"), "YQ==");
        assert_eq!(Base64Std::decode("YWI=").unwrap(), b"ab");
        assert_eq!(Base64Std::decode("").unwrap(), b"");
        assert!(Base64Std::decode("YW").is_none());
        assert!(Base64Std::decode("Y!Jj").is_none());
    }
}
