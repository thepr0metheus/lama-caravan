//! The accounts database as the controller before this one left it, read once. A SQLite file is a set of b-trees of fixed-size pages; reading a table takes this much and no library. Nothing here writes: from the first start the accounts live in a JSON document, and the old file stays as it was for the way back.

use std::path::Path;

/// One value of a row.
#[derive(Debug, Clone, PartialEq)]
pub enum SqlValue {
    /// NULL.
    Null,
    /// An integer.
    Integer(i64),
    /// A float.
    Real(f64),
    /// Text.
    Text(String),
    /// A blob.
    Blob(Vec<u8>),
}

impl SqlValue {
    /// The integer it holds.
    pub fn int(&self) -> Option<i64> {
        match self {
            Self::Integer(number) => Some(*number),
            _ => None,
        }
    }

    /// The text it holds.
    pub fn text(&self) -> Option<&str> {
        match self {
            Self::Text(text) => Some(text),
            _ => None,
        }
    }

    /// The bytes it holds.
    pub fn blob(&self) -> Option<&[u8]> {
        match self {
            Self::Blob(bytes) => Some(bytes),
            Self::Text(text) => Some(text.as_bytes()),
            _ => None,
        }
    }
}

/// A row: its rowid and its fields as they are stored. A column added after a row was written is not in it.
#[derive(Debug, Clone, PartialEq)]
pub struct SqlRow {
    /// The rowid: what an `INTEGER PRIMARY KEY` column holds, stored as NULL in the record.
    pub rowid: i64,
    /// The fields.
    pub fields: Vec<SqlValue>,
}

/// A SQLite file, in memory.
pub struct SqliteFile {
    bytes: Vec<u8>,
    page_size: usize,
    usable: usize,
}

impl SqliteFile {
    const MAGIC: &'static [u8; 16] = b"SQLite format 3\0";
    const LEAF: u8 = 0x0d;
    const INTERIOR: u8 = 0x05;

    /// The file at `path`.
    pub fn open(path: &Path) -> Result<Self, String> {
        let bytes = std::fs::read(path).map_err(|error| error.to_string())?;
        Self::of_bytes(bytes)
    }

    /// The file these bytes are.
    pub fn of_bytes(bytes: Vec<u8>) -> Result<Self, String> {
        if bytes.get(..16) != Some(Self::MAGIC.as_slice()) {
            return Err("not a SQLite file".to_string());
        }
        let size = usize::from(Self::u16_at(&bytes, 16)?);
        let page_size = if size == 1 { 65536 } else { size };
        let reserved = usize::from(*bytes.get(20).ok_or("the header ends early")?);
        if page_size < 512 || reserved >= page_size {
            return Err("the header says no page size".to_string());
        }
        Ok(Self { bytes, page_size, usable: page_size - reserved })
    }

    fn u16_at(bytes: &[u8], at: usize) -> Result<u16, String> {
        let pair = bytes.get(at..at + 2).ok_or("a page ends early")?;
        Ok(pair.iter().fold(0, |held, byte| (held << 8) | u16::from(*byte)))
    }

    fn u32_at(bytes: &[u8], at: usize) -> Result<u32, String> {
        let four = bytes.get(at..at + 4).ok_or("a page ends early")?;
        Ok(four.iter().fold(0, |held, byte| (held << 8) | u32::from(*byte)))
    }

    /// A varint and how long it is.
    fn varint(bytes: &[u8], at: usize) -> Result<(u64, usize), String> {
        let mut value = 0u64;
        for used in 0..9 {
            let byte = *bytes.get(at + used).ok_or("a varint ends early")?;
            if used == 8 {
                return Ok(((value << 8) | u64::from(byte), 9));
            }
            value = (value << 7) | u64::from(byte & 0x7f);
            if byte & 0x80 == 0 {
                return Ok((value, used + 1));
            }
        }
        Err("a varint never ends".to_string())
    }

    fn page(&self, number: u32) -> Result<&[u8], String> {
        let start = (number as usize).checked_sub(1).ok_or("page zero does not exist")? * self.page_size;
        self.bytes.get(start..start + self.page_size).ok_or_else(|| format!("no page {number}"))
    }

    /// The rows of the table named `name`; none when there is no such table.
    pub fn table(&self, name: &str) -> Result<Vec<SqlRow>, String> {
        let schema = self.rows_of(1)?;
        let found = schema.iter().find(|row| {
            row.fields.first().and_then(SqlValue::text) == Some("table")
                && row.fields.get(1).and_then(SqlValue::text) == Some(name)
        });
        let Some(root) = found.and_then(|row| row.fields.get(3)).and_then(SqlValue::int) else {
            return Ok(Vec::new());
        };
        self.rows_of(u32::try_from(root).map_err(|error| error.to_string())?)
    }

    fn rows_of(&self, root: u32) -> Result<Vec<SqlRow>, String> {
        let mut rows = Vec::new();
        self.walk(root, &mut rows, 0)?;
        Ok(rows)
    }

    fn walk(&self, number: u32, rows: &mut Vec<SqlRow>, depth: u32) -> Result<(), String> {
        const DEEPEST: u32 = 32;
        if depth > DEEPEST {
            return Err("the tree goes deeper than a tree can".to_string());
        }
        let page = self.page(number)?;
        let head = if number == 1 { 100 } else { 0 };
        let kind = *page.get(head).ok_or("a page ends early")?;
        let cells = usize::from(Self::u16_at(page, head + 3)?);
        let pointers = head + if kind == Self::LEAF { 8 } else { 12 };
        for cell in 0..cells {
            let at = usize::from(Self::u16_at(page, pointers + 2 * cell)?);
            match kind {
                Self::LEAF => rows.push(self.leaf_cell(page, at)?),
                Self::INTERIOR => self.walk(Self::u32_at(page, at)?, rows, depth + 1)?,
                other => return Err(format!("a page of kind {other} in a table")),
            }
        }
        if kind == Self::INTERIOR {
            self.walk(Self::u32_at(page, head + 8)?, rows, depth + 1)?;
        }
        Ok(())
    }

    fn leaf_cell(&self, page: &[u8], at: usize) -> Result<SqlRow, String> {
        let (length, used) = Self::varint(page, at)?;
        let (rowid, used_id) = Self::varint(page, at + used)?;
        let start = at + used + used_id;
        let length = length as usize;
        let local = self.local_size(length);
        let mut payload = page.get(start..start + local).ok_or("a cell ends early")?.to_vec();
        if local < length {
            let mut next = Self::u32_at(page, start + local)?;
            while next != 0 && payload.len() < length {
                let over = self.page(next)?;
                next = Self::u32_at(over, 0)?;
                let take = (length - payload.len()).min(self.usable - 4);
                payload.extend_from_slice(over.get(4..4 + take).ok_or("an overflow page ends early")?);
            }
        }
        Ok(SqlRow { rowid: rowid as i64, fields: Self::record(&payload)? })
    }

    /// How much of a payload stays on its leaf page.
    fn local_size(&self, length: usize) -> usize {
        let most = self.usable - 35;
        if length <= most {
            return length;
        }
        let least = (self.usable - 12) * 32 / 255 - 23;
        let wanted = least + (length - least) % (self.usable - 4);
        if wanted <= most { wanted } else { least }
    }

    fn record(payload: &[u8]) -> Result<Vec<SqlValue>, String> {
        let (head_size, mut at) = Self::varint(payload, 0)?;
        let head_size = head_size as usize;
        let mut kinds = Vec::new();
        while at < head_size {
            let (kind, used) = Self::varint(payload, at)?;
            kinds.push(kind);
            at += used;
        }
        let mut body = head_size;
        let mut fields = Vec::with_capacity(kinds.len());
        for kind in kinds {
            let (value, used) = Self::value(payload, body, kind)?;
            fields.push(value);
            body += used;
        }
        Ok(fields)
    }

    fn value(payload: &[u8], at: usize, kind: u64) -> Result<(SqlValue, usize), String> {
        let whole = |size: usize| -> Result<(SqlValue, usize), String> {
            let bytes = payload.get(at..at + size).ok_or("a record ends early")?;
            let negative = bytes.first().is_some_and(|first| first & 0x80 != 0);
            let start: i64 = if negative { -1 } else { 0 };
            Ok((SqlValue::Integer(bytes.iter().fold(start, |held, byte| (held << 8) | i64::from(*byte))), size))
        };
        match kind {
            0 => Ok((SqlValue::Null, 0)),
            1 => whole(1),
            2 => whole(2),
            3 => whole(3),
            4 => whole(4),
            5 => whole(6),
            6 => whole(8),
            7 => {
                let bytes = payload.get(at..at + 8).ok_or("a record ends early")?;
                let bits = bytes.iter().fold(0u64, |held, byte| (held << 8) | u64::from(*byte));
                Ok((SqlValue::Real(f64::from_bits(bits)), 8))
            }
            8 => Ok((SqlValue::Integer(0), 0)),
            9 => Ok((SqlValue::Integer(1), 0)),
            even if even >= 12 && even % 2 == 0 => {
                let size = ((even - 12) / 2) as usize;
                Ok((SqlValue::Blob(payload.get(at..at + size).ok_or("a record ends early")?.to_vec()), size))
            }
            odd if odd >= 13 => {
                let size = ((odd - 13) / 2) as usize;
                let bytes = payload.get(at..at + size).ok_or("a record ends early")?;
                Ok((SqlValue::Text(String::from_utf8_lossy(bytes).into_owned()), size))
            }
            other => Err(format!("a field of kind {other}")),
        }
    }
}
