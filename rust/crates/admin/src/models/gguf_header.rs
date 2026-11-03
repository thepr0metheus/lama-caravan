//! What a GGUF file's header says. Only the wanted facts are kept, and as little of the file is read as the format lets.

use serde_json::{Map, Value, json};
use std::fs::File;
use std::io::{Read, Seek, SeekFrom};
use std::path::Path;

/// Why a header could not be read: a file that ends early, or a header past any header's length. Either way the file says nothing.
#[derive(Debug)]
struct NoHeader;

/// One reading of a file.
pub struct GgufHeader {
    file: File,
    buf: Vec<u8>,
}

impl GgufHeader {
    const STRING: u32 = 8;
    const ARRAY: u32 = 9;
    const WANTED: [&'static str; 3] = ["general.architecture", "stt.variant", "general.languages"];
    const SUFFIXES: [&'static str; 17] = [
        "block_count",
        "block_size",
        "context_length",
        "embedding_length",
        "attention.head_count",
        "attention.head_count_kv",
        "attention.key_length",
        "attention.value_length",
        "attention.sliding_window",
        "attention.sliding_window_pattern",
        "attention.key_length_swa",
        "attention.value_length_swa",
        "attention.shared_kv_layers",
        "full_attention_interval",
        "attention.recurrent_layers",
        "pooling_type",
        "expert_count",
    ];
    const KEPT: u64 = 32;
    const PER_LAYER: [&'static str; 4] =
        ["attention.head_count", "attention.head_count_kv", "attention.sliding_window_pattern", "attention.recurrent_layers"];
    const LAYERS: u64 = 1024;
    /// The bytes of the expert tensors, summed by this reader.
    pub const EXPERT_BYTES: &'static str = "caravan.expert_bytes";
    /// How many keys the header has, once it was read to its end.
    pub const KEYS: &'static str = "caravan.keys";
    const TENSORS: u64 = 1 << 16;
    const ALIGNMENT: u64 = 32;
    const BLOCK: usize = 4 << 20;
    const LIMIT: u64 = 256 << 20;
    const LIMIT_KEYS: u64 = 256;

    /// The wanted facts of the file's header; none for a file that says none.
    pub fn read(path: &Path) -> Map<String, Value> {
        let Ok(file) = File::open(path) else {
            return Map::new();
        };
        // absent-ok: a file that is no GGUF, or ends early, says nothing: `{}` is what its readers take for that.
        Self { file, buf: Vec::new() }.facts().unwrap_or_default()
    }

    fn wanted(key: &str) -> bool {
        Self::WANTED.contains(&key) || Self::SUFFIXES.iter().any(|suffix| key.ends_with(suffix))
    }

    fn ensure(&mut self, end: u64) -> Result<(), NoHeader> {
        if end > Self::LIMIT {
            return Err(NoHeader);
        }
        let end = end as usize;
        while self.buf.len() < end {
            let mut chunk = vec![0u8; (end - self.buf.len()).max(Self::BLOCK)];
            let read = self.file.read(&mut chunk).map_err(|_| NoHeader)?;
            if read == 0 {
                return Err(NoHeader);
            }
            self.buf.extend_from_slice(chunk.get(..read).ok_or(NoHeader)?);
        }
        Ok(())
    }

    fn take(&mut self, pos: u64, size: u64) -> Result<&[u8], NoHeader> {
        self.ensure(pos + size)?;
        self.buf.get(pos as usize..(pos + size) as usize).ok_or(NoHeader)
    }

    fn u32_at(&mut self, pos: u64) -> Result<u32, NoHeader> {
        let bytes: [u8; 4] = self.take(pos, 4)?.try_into().map_err(|_| NoHeader)?;
        Ok(u32::from_le_bytes(bytes))
    }

    fn u64_at(&mut self, pos: u64) -> Result<u64, NoHeader> {
        let bytes: [u8; 8] = self.take(pos, 8)?.try_into().map_err(|_| NoHeader)?;
        Ok(u64::from_le_bytes(bytes))
    }

    fn string_at(&mut self, pos: u64) -> Result<(String, u64), NoHeader> {
        let length = self.u64_at(pos)?;
        let end = (pos + 8).checked_add(length).ok_or(NoHeader)?;
        let text = String::from_utf8_lossy(self.take(pos + 8, length)?).into_owned();
        Ok((text, end))
    }

    /// The size of a number of this type; none for a type that is no number.
    fn number_size(code: u32) -> Option<u64> {
        match code {
            0 | 1 | 7 => Some(1),
            2 | 3 => Some(2),
            4..=6 => Some(4),
            10..=12 => Some(8),
            _ => None,
        }
    }

    fn number(&mut self, code: u32, pos: u64) -> Result<Value, NoHeader> {
        let size = Self::number_size(code).ok_or(NoHeader)?;
        let bytes = self.take(pos, size)?;
        // absent-ok: past the end reads as zero: the length check refuses it next.
        let at = |index: usize| bytes.get(index).copied().unwrap_or_default();
        let wide = |count: usize| (0..count).rev().fold(0u64, |held, index| (held << 8) | u64::from(at(index)));
        Ok(match code {
            0 => json!(at(0)),
            1 => json!(at(0) as i8),
            2 => json!(wide(2) as u16),
            3 => json!(wide(2) as u16 as i16),
            4 => json!(wide(4) as u32),
            5 => json!(wide(4) as u32 as i32),
            6 => json!(f64::from(f32::from_bits(wide(4) as u32))),
            7 => json!(at(0) != 0),
            10 => json!(wide(8)),
            11 => json!(wide(8) as i64),
            _ => json!(f64::from_bits(wide(8))),
        })
    }

    fn value_at(&mut self, code: u32, pos: u64, kept: u64) -> Result<(Value, u64), NoHeader> {
        if code == Self::STRING {
            let (text, end) = self.string_at(pos)?;
            return Ok((json!(text), end));
        }
        if code == Self::ARRAY {
            let item = self.u32_at(pos)?;
            let length = self.u64_at(pos + 4)?;
            let mut at = pos + 12;
            let mut values = Vec::new();
            for _ in 0..length.min(kept) {
                let (value, end) = self.value_at(item, at, Self::KEPT)?;
                values.push(value);
                at = end;
            }
            let end = self.skip_items(item, at, length - values.len() as u64)?;
            return Ok((Value::Array(values), end));
        }
        match Self::number_size(code) {
            Some(size) => Ok((self.number(code, pos)?, pos + size)),
            None => Ok((Value::Null, pos)),
        }
    }

    fn skip_at(&mut self, code: u32, pos: u64) -> Result<u64, NoHeader> {
        if code == Self::STRING {
            return Ok(pos + 8 + self.u64_at(pos)?);
        }
        if code == Self::ARRAY {
            let item = self.u32_at(pos)?;
            let length = self.u64_at(pos + 4)?;
            return self.skip_items(item, pos + 12, length);
        }
        // absent-ok: a kind of no fixed size was handled above.
        Ok(pos + Self::number_size(code).unwrap_or_default())
    }

    fn skip_items(&mut self, item: u32, pos: u64, count: u64) -> Result<u64, NoHeader> {
        if count == 0 {
            return Ok(pos);
        }
        if let Some(size) = Self::number_size(item) {
            return pos.checked_add(count.checked_mul(size).ok_or(NoHeader)?).ok_or(NoHeader);
        }
        if item == Self::STRING || item == Self::ARRAY {
            let mut at = pos;
            for _ in 0..count {
                at = self.skip_at(item, at)?;
            }
            return Ok(at);
        }
        Ok(pos)
    }

    fn facts(&mut self) -> Result<Map<String, Value>, NoHeader> {
        self.ensure(24).map_err(|_| NoHeader)?;
        if self.buf.get(..4) != Some(b"GGUF".as_slice()) || self.u32_at(4)? < 2 {
            return Ok(Map::new());
        }
        let pairs = self.u64_at(16)?;
        let mut meta = Map::new();
        let mut pos = 24;
        for _ in 0..pairs.min(Self::LIMIT_KEYS) {
            let (key, after_key) = self.string_at(pos)?;
            let code = self.u32_at(after_key)?;
            pos = after_key + 4;
            if Self::wanted(&key) {
                let kept = if Self::PER_LAYER.iter().any(|suffix| key.ends_with(suffix)) { Self::LAYERS } else { Self::KEPT };
                let (value, end) = self.value_at(code, pos, kept)?;
                meta.insert(key, value);
                pos = end;
            } else {
                pos = self.skip_at(code, pos)?;
            }
        }
        self.ensure(pos)?;
        if pairs <= Self::LIMIT_KEYS {
            meta.insert(Self::KEYS.to_string(), json!(pairs));
            let tensors = self.u64_at(8)?;
            let experts = self.expert_bytes(pos, tensors)?;
            if experts != 0 {
                meta.insert(Self::EXPERT_BYTES.to_string(), json!(experts));
            }
        }
        Ok(meta)
    }

    /// `blk\.\d+\.ffn_(up|down|gate_up|gate)_(ch|)exps`, anywhere in the name.
    fn is_expert(name: &str) -> bool {
        name.match_indices("blk.").any(|(at, _)| {
            // absent-ok: the word was just found at this place.
            let rest = name.get(at + 4..).unwrap_or_default();
            let digits = rest.chars().take_while(char::is_ascii_digit).count();
            if digits == 0 {
                return false;
            }
            let Some(after) = rest.get(digits..).and_then(|tail| tail.strip_prefix(".ffn_")) else {
                return false;
            };
            ["up_", "down_", "gate_up_", "gate_"]
                .iter()
                .filter_map(|word| after.strip_prefix(word))
                .any(|tail| tail.starts_with("exps") || tail.starts_with("chexps"))
        })
    }

    /// The bytes of the expert tensors in the list of `count` tensors from `pos`; 0 when there are none or the list does not add up.
    fn expert_bytes(&mut self, pos: u64, count: u64) -> Result<u64, NoHeader> {
        if count > Self::TENSORS {
            return Ok(0);
        }
        let mut spans = Vec::with_capacity(count as usize);
        let mut at = pos;
        for _ in 0..count {
            let (name, end) = self.string_at(at)?;
            let dims = u64::from(self.u32_at(end)?);
            at = end + 4 + 8 * dims + 4;
            spans.push((self.u64_at(at)?, Self::is_expert(&name)));
            at += 8;
        }
        if !spans.iter().any(|(_, expert)| *expert) {
            return Ok(0);
        }
        let size = self.file.seek(SeekFrom::End(0)).map_err(|_| NoHeader)?;
        let data = size.saturating_sub(at.div_ceil(Self::ALIGNMENT) * Self::ALIGNMENT);
        spans.sort_unstable();
        let ends: Vec<u64> = spans.iter().skip(1).map(|(offset, _)| *offset).chain([data]).collect();
        if spans.iter().zip(&ends).any(|((offset, _), end)| end < offset) {
            return Ok(0);
        }
        Ok(spans.iter().zip(&ends).filter(|((_, expert), _)| *expert).map(|((offset, _), end)| end - offset).sum())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    struct Writer(Vec<u8>);

    impl Writer {
        fn u32(&mut self, value: u32) {
            self.0.extend_from_slice(&value.to_le_bytes());
        }

        fn u64(&mut self, value: u64) {
            self.0.extend_from_slice(&value.to_le_bytes());
        }

        fn text(&mut self, value: &str) {
            self.u64(value.len() as u64);
            self.0.extend_from_slice(value.as_bytes());
        }
    }

    #[test]
    fn the_wanted_keys_and_the_experts_are_read() {
        let mut out = Writer(b"GGUF".to_vec());
        out.u32(3);
        out.u64(2);
        out.u64(5);
        out.text("general.architecture");
        out.u32(8);
        out.text("qwen3");
        out.text("qwen3.context_length");
        out.u32(4);
        out.u32(4096);
        out.text("other.thing");
        out.u32(9);
        out.u32(8);
        out.u64(2);
        out.text("a");
        out.text("b");
        out.text("qwen3.attention.head_count");
        out.u32(9);
        out.u32(5);
        out.u64(2);
        out.u32(7);
        out.u32(9);
        out.text("qwen3.rope.scale");
        out.u32(6);
        out.0.extend_from_slice(&1.5f32.to_le_bytes());
        for (name, offset) in [("blk.0.ffn_up_exps", 0u64), ("blk.0.other", 100)] {
            out.text(name);
            out.u32(1);
            out.u64(10);
            out.u32(0);
            out.u64(offset);
        }
        let length = out.0.len() as u64;
        let total = length.div_ceil(32) * 32 + 300;
        out.0.resize(total as usize, 0);
        let path = std::env::temp_dir().join(format!("gguf-{}.gguf", std::process::id()));
        std::fs::write(&path, &out.0).unwrap();
        let meta = GgufHeader::read(&path);
        std::fs::remove_file(&path).unwrap();
        assert_eq!(meta.get("general.architecture"), Some(&json!("qwen3")));
        assert_eq!(meta.get("qwen3.context_length"), Some(&json!(4096)));
        assert_eq!(meta.get("qwen3.attention.head_count"), Some(&json!([7, 9])));
        assert!(meta.get("other.thing").is_none());
        assert_eq!(meta.get(GgufHeader::KEYS), Some(&json!(5)));
        assert_eq!(meta.get(GgufHeader::EXPERT_BYTES), Some(&json!(100)));
    }

    #[test]
    fn a_file_that_is_no_gguf_says_nothing() {
        let path = std::env::temp_dir().join(format!("gguf-none-{}.gguf", std::process::id()));
        std::fs::write(&path, b"not a model at all, and long enough").unwrap();
        assert!(GgufHeader::read(&path).is_empty());
        std::fs::write(&path, b"GGUF").unwrap();
        assert!(GgufHeader::read(&path).is_empty());
        std::fs::remove_file(&path).unwrap();
        assert!(GgufHeader::read(&path).is_empty());
    }

    #[test]
    fn an_expert_is_told_by_its_name() {
        assert!(GgufHeader::is_expert("blk.12.ffn_gate_up_chexps.weight"));
        assert!(GgufHeader::is_expert("x.blk.3.ffn_down_exps"));
        assert!(!GgufHeader::is_expert("blk.x.ffn_up_exps"));
        assert!(!GgufHeader::is_expert("blk.1.ffn_up"));
    }
}
