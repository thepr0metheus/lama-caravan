//! The body of a request to the machine's entry, read whole before it goes on: by its length, or chunk by chunk when the client sends it so. Never past `limit`: the scout holds it in memory.

use std::io::{self, BufRead, Read};

/// What a body may come to.
#[derive(Debug)]
pub enum BodyError {
    /// Over the limit: refused, not read further.
    TooLong,
    /// It cannot be read as it says it is sent.
    Malformed(&'static str),
    /// The connection failed.
    Io(io::Error),
}

impl From<io::Error> for BodyError {
    fn from(error: io::Error) -> Self {
        Self::Io(error)
    }
}

/// The reader.
pub struct EntryBody {
    limit: u64,
}

impl EntryBody {
    const LINE: u64 = 1024;

    /// A body of at most `limit` bytes.
    pub fn new(limit: u64) -> Self {
        Self { limit }
    }

    /// The whole of it, by what its head says.
    pub fn read(
        &self,
        transfer_encoding: Option<&str>,
        content_length: Option<&str>,
        source: &mut impl BufRead,
    ) -> Result<Vec<u8>, BodyError> {
        if transfer_encoding.is_some_and(|said| said.to_lowercase().contains("chunked")) {
            return self.chunks(source);
        }
        let said = content_length.map(str::trim).filter(|said| !said.is_empty());
        let length: i64 = match said {
            Some(said) => said.parse().map_err(|_| BodyError::Malformed("Content-Length is not a number"))?,
            None => 0,
        };
        let length = u64::try_from(length).map_err(|_| BodyError::Malformed("Content-Length is negative"))?;
        if length > self.limit {
            return Err(BodyError::TooLong);
        }
        let mut body = Vec::new();
        source.take(length).read_to_end(&mut body)?;
        Ok(body)
    }

    fn line(source: &mut impl BufRead) -> Result<Vec<u8>, BodyError> {
        let mut line = Vec::new();
        source.take(Self::LINE).read_until(b'\n', &mut line)?;
        Ok(line)
    }

    fn chunks(&self, source: &mut impl BufRead) -> Result<Vec<u8>, BodyError> {
        let mut body = Vec::new();
        loop {
            let line = Self::line(source)?;
            let word = line.split(|byte| *byte == b';').next().unwrap_or_default();
            // absent-ok: a size that is no text is no number, and is refused on the next line.
            let word = std::str::from_utf8(word).map(str::trim).unwrap_or_default();
            let count = u64::from_str_radix(word, 16).map_err(|_| BodyError::Malformed("a chunk's size is not a number"))?;
            if count == 0 {
                // The trailers, up to the blank line.
                while !Self::line(source)?.iter().all(u8::is_ascii_whitespace) {}
                return Ok(body);
            }
            if body.len() as u64 + count > self.limit {
                return Err(BodyError::TooLong);
            }
            let before = body.len();
            (&mut *source).take(count).read_to_end(&mut body)?;
            if ((body.len() - before) as u64) < count {
                return Err(BodyError::Malformed("the body ended inside a chunk"));
            }
            // The line end after the chunk.
            Self::line(source)?;
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn read(transfer: Option<&str>, length: Option<&str>, raw: &[u8]) -> Result<Vec<u8>, BodyError> {
        EntryBody::new(16).read(transfer, length, &mut io::Cursor::new(raw))
    }

    #[test]
    fn a_body_by_its_length() {
        assert_eq!(read(None, Some("3"), b"abcd").unwrap(), b"abc");
        assert_eq!(read(None, None, b"abc").unwrap(), b"");
        assert!(matches!(read(None, Some("x"), b""), Err(BodyError::Malformed(_))));
        assert!(matches!(read(None, Some("-1"), b""), Err(BodyError::Malformed(_))));
        assert!(matches!(read(None, Some("17"), b""), Err(BodyError::TooLong)));
    }

    #[test]
    fn a_body_chunk_by_chunk() {
        assert_eq!(read(Some("chunked"), None, b"3;ext=1\r\nabc\r\n2\r\nde\r\n0\r\nTrailer: x\r\n\r\n").unwrap(), b"abcde");
        assert!(matches!(read(Some("Chunked"), None, b"zz\r\n"), Err(BodyError::Malformed(_))));
        assert!(matches!(read(Some("chunked"), None, b"5\r\nab"), Err(BodyError::Malformed(_))));
        assert!(matches!(read(Some("chunked"), None, b"11\r\n"), Err(BodyError::TooLong)));
    }
}
