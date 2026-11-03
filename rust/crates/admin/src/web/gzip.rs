//! A body in gzip, for the answers that are worth it.

use miniz_oxide::deflate::compress_to_vec;

/// `gzip.compress(data, 6)`.
pub struct Gzip;

impl Gzip {
    /// The body as one gzip member.
    pub fn compress(data: &[u8]) -> Vec<u8> {
        const LEVEL: u8 = 6;
        // The header: magic, deflate, no flags, no time, no hints, an unknown system.
        let mut out = vec![0x1f, 0x8b, 8, 0, 0, 0, 0, 0, 0, 255];
        out.extend(compress_to_vec(data, LEVEL));
        out.extend_from_slice(&Self::crc32(data).to_le_bytes());
        out.extend_from_slice(&(data.len() as u32).to_le_bytes());
        out
    }

    fn crc32(data: &[u8]) -> u32 {
        let mut crc = !0u32;
        for byte in data {
            crc ^= u32::from(*byte);
            for _ in 0..8 {
                crc = if crc & 1 == 1 { (crc >> 1) ^ 0xedb8_8320 } else { crc >> 1 };
            }
        }
        !crc
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_member_reads_back() {
        let data = "the same words again and again ".repeat(100);
        let member = Gzip::compress(data.as_bytes());
        assert!(member.len() < data.len() / 10);
        let body = member.get(10..member.len() - 8).unwrap();
        assert_eq!(miniz_oxide::inflate::decompress_to_vec(body).unwrap(), data.as_bytes());
        assert_eq!(Gzip::crc32(b"123456789"), 0xcbf4_3926);
    }
}
