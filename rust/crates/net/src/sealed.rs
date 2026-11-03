//! Locking a settings file's credentials with a passphrase: scrypt makes the key (as `hashlib.scrypt`), AES-256-GCM locks (as `AESGCM`, the tag after the text). The library TLS rests on has no scrypt, and it is forty lines over its PBKDF2.

use ring::aead::{AES_256_GCM, Aad, LessSafeKey, Nonce, UnboundKey};
use ring::pbkdf2;
use std::num::NonZeroU32;

/// One 64-byte block of scrypt's mixing.
type Chunk = [u32; 16];

/// scrypt (RFC 7914).
pub struct Scrypt;

impl Scrypt {
    /// The Salsa20/8 core over one block.
    fn salsa(block: &mut Chunk) {
        let mut x = *block;
        macro_rules! quarter {
            ($a:literal, $b:literal, $c:literal, $d:literal) => {
                x[$b] ^= x[$a].wrapping_add(x[$d]).rotate_left(7);
                x[$c] ^= x[$b].wrapping_add(x[$a]).rotate_left(9);
                x[$d] ^= x[$c].wrapping_add(x[$b]).rotate_left(13);
                x[$a] ^= x[$d].wrapping_add(x[$c]).rotate_left(18);
            };
        }
        for _ in 0..4 {
            quarter!(0, 4, 8, 12);
            quarter!(5, 9, 13, 1);
            quarter!(10, 14, 2, 6);
            quarter!(15, 3, 7, 11);
            quarter!(0, 1, 2, 3);
            quarter!(5, 6, 7, 4);
            quarter!(10, 11, 8, 9);
            quarter!(15, 12, 13, 14);
        }
        for (own, mixed) in block.iter_mut().zip(x) {
            *own = own.wrapping_add(mixed);
        }
    }

    fn xor(own: &mut Chunk, said: &Chunk) {
        for (left, right) in own.iter_mut().zip(said) {
            *left ^= *right;
        }
    }

    /// BlockMix: the even blocks' results first, then the odd ones'.
    fn block_mix(input: &[Chunk], out: &mut [Chunk]) {
        let half = input.len() / 2;
        let mut x = input.last().copied().unwrap_or([0; 16]);
        for (at, chunk) in input.iter().enumerate() {
            Self::xor(&mut x, chunk);
            Self::salsa(&mut x);
            let place = if at.is_multiple_of(2) { at / 2 } else { half + at / 2 };
            if let Some(slot) = out.get_mut(place) {
                *slot = x;
            }
        }
    }

    fn rom_mix(blocks: &mut Vec<Chunk>, cost: usize) {
        let width = blocks.len();
        let mut memory: Vec<Chunk> = Vec::with_capacity(cost * width);
        let mut other = blocks.clone();
        for _ in 0..cost {
            memory.extend_from_slice(blocks);
            Self::block_mix(blocks, &mut other);
            std::mem::swap(blocks, &mut other);
        }
        for _ in 0..cost {
            let last = blocks.last().copied().unwrap_or([0; 16]);
            let row = (u64::from(last[0]) | (u64::from(last[1]) << 32)) as usize & (cost - 1);
            for (own, kept) in blocks.iter_mut().zip(memory.iter().skip(row * width)) {
                Self::xor(own, kept);
            }
            Self::block_mix(blocks, &mut other);
            std::mem::swap(blocks, &mut other);
        }
    }

    fn one_round(salt: &[u8], password: &[u8], out: &mut [u8]) {
        pbkdf2::derive(pbkdf2::PBKDF2_HMAC_SHA256, NonZeroU32::MIN, salt, password, out);
    }

    /// `hashlib.scrypt(password, salt=salt, n=cost, r=size, p=parallel, dklen=length)`. `cost` is a power of two.
    pub fn derive(password: &[u8], salt: &[u8], cost: usize, size: usize, parallel: usize, length: usize) -> Vec<u8> {
        let block_bytes = 128 * size;
        let mut mixed = vec![0u8; parallel * block_bytes];
        Self::one_round(salt, password, &mut mixed);
        for part in mixed.chunks_exact_mut(block_bytes) {
            let mut blocks: Vec<Chunk> = part.as_chunks::<64>().0.iter().map(Self::chunk_of).collect();
            Self::rom_mix(&mut blocks, cost);
            for (bytes, word) in part.as_chunks_mut::<4>().0.iter_mut().zip(blocks.iter().flatten()) {
                *bytes = word.to_le_bytes();
            }
        }
        let mut out = vec![0u8; length];
        Self::one_round(&mixed, password, &mut out);
        out
    }

    fn chunk_of(bytes: &[u8; 64]) -> Chunk {
        let mut chunk = [0u32; 16];
        for (word, four) in chunk.iter_mut().zip(bytes.as_chunks::<4>().0) {
            *word = u32::from_le_bytes(*four);
        }
        chunk
    }
}

/// AES-256-GCM with no associated data.
pub struct SealedBytes;

impl SealedBytes {
    fn key(key: &[u8]) -> Option<LessSafeKey> {
        UnboundKey::new(&AES_256_GCM, key).ok().map(LessSafeKey::new)
    }

    fn nonce(nonce: &[u8]) -> Option<Nonce> {
        Nonce::try_assume_unique_for_key(nonce).ok()
    }

    /// `AESGCM(key).encrypt(nonce, plain, None)`; `None` for a key or a nonce of the wrong length.
    pub fn seal(key: &[u8], nonce: &[u8], plain: &[u8]) -> Option<Vec<u8>> {
        let mut out = plain.to_vec();
        Self::key(key)?.seal_in_place_append_tag(Self::nonce(nonce)?, Aad::empty(), &mut out).ok()?;
        Some(out)
    }

    /// `AESGCM(key).decrypt(nonce, sealed, None)`; `None` when it does not open: a wrong key, or a text that was changed.
    pub fn open(key: &[u8], nonce: &[u8], sealed: &[u8]) -> Option<Vec<u8>> {
        let mut out = sealed.to_vec();
        let length = Self::key(key)?.open_in_place(Self::nonce(nonce)?, Aad::empty(), &mut out).ok()?.len();
        out.truncate(length);
        Some(out)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn hex(bytes: &[u8]) -> String {
        bytes.iter().map(|byte| format!("{byte:02x}")).collect()
    }

    #[test]
    fn scrypt_says_what_the_rfc_says() {
        let key = Scrypt::derive(b"password", b"NaCl", 1024, 8, 16, 64);
        assert_eq!(
            hex(&key),
            "fdbabe1c9d3472007856e7190d01e9fe7c6ad7cbc8237830e77376634b3731622eaf30d92e22a3886ff109279d9830dac727afb94a83ee6d8360cbdfa2cc0640"
        );
        let empty = Scrypt::derive(b"", b"", 16, 1, 1, 64);
        assert_eq!(
            hex(&empty),
            "77d6576238657b203b19ca42c18a0497f16b4844e3074ae8dfdffa3fede21442fcd0069ded0948f8326a753a0fc81f17e8d3e0fb2e0d3628cf35e20c38d18906"
        );
    }

    #[test]
    fn what_was_locked_opens_only_with_its_key() {
        let (key, nonce) = ([7u8; 32], [9u8; 12]);
        let sealed = SealedBytes::seal(&key, &nonce, b"secret").unwrap();
        assert_eq!(sealed.len(), 6 + 16);
        assert_eq!(SealedBytes::open(&key, &nonce, &sealed).unwrap(), b"secret");
        assert!(SealedBytes::open(&[8u8; 32], &nonce, &sealed).is_none());
        let mut changed = sealed;
        *changed.last_mut().unwrap() ^= 1;
        assert!(SealedBytes::open(&key, &nonce, &changed).is_none());
        assert!(SealedBytes::seal(&key[..3], &nonce, b"x").is_none());
    }

    #[test]
    fn a_lock_from_the_python_side_opens() {
        // AESGCM(bytes(32)).encrypt(bytes(12), b"hello", None), written by `cryptography`.
        let sealed = "a6c22c51228b908f7f62ffcea6a92fabef39bf4d93";
        let bytes: Vec<u8> =
            (0..sealed.len() / 2).map(|at| u8::from_str_radix(&sealed[at * 2..at * 2 + 2], 16).unwrap()).collect();
        assert_eq!(SealedBytes::open(&[0u8; 32], &[0u8; 12], &bytes).unwrap(), b"hello");
        assert_eq!(SealedBytes::seal(&[0u8; 32], &[0u8; 12], b"hello").unwrap(), bytes);
    }
}
