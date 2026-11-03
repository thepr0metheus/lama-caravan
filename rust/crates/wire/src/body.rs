//! A request's body off the wire, word for word in its refusals,
//! because a refusal's words reach the client.

use crate::headers::Headers;
use std::io::{self, BufRead, Read};

/// Why a body could not be read.
#[derive(Debug)]
pub enum BodyError {
    /// The body cannot be read as the request says it is sent; the words say why.
    Malformed(String),
    /// The socket failed, or waited past its time.
    Io(io::Error),
}

impl BodyError {
    fn malformed(words: &str) -> Self {
        Self::Malformed(words.to_string())
    }
}

/// The body a client sends, taken off the connection whole: by its `Content-Length`, or chunk by chunk.
/// Read whole either way, it goes upstream with its own length, never with the client's framing.
pub struct RequestBody;

impl RequestBody {
    /// The longest line a chunk's size may take, its extensions with it.
    const LINE: usize = 4096;
    /// The most trailer lines after the last chunk: a client sends none or a few.
    const TRAILERS: usize = 64;

    /// The body, or `None` when the request carries none: no length, or 0, and no chunks.
    pub fn read(headers: &Headers, source: &mut impl BufRead) -> Result<Option<Vec<u8>>, BodyError> {
        let codings: Vec<String> = headers
            .all("Transfer-Encoding")
            .iter()
            .flat_map(|value| value.split(','))
            .map(|coding| coding.trim().to_lowercase())
            .filter(|coding| !coding.is_empty())
            .collect();
        if !codings.is_empty() {
            if codings != ["chunked"] {
                return Err(BodyError::Malformed(format!(
                    "Transfer-Encoding {} is not read: send the body by its length or in chunks",
                    codings.join(", ")
                )));
            }
            return Self::chunks(source).map(Some);
        }
        let mut lengths: Vec<String> = headers.all("Content-Length").iter().map(|value| value.trim().to_string()).collect();
        lengths.sort();
        lengths.dedup();
        if lengths.len() > 1 {
            return Err(BodyError::malformed("Content-Length is given twice, differently"));
        }
        let Some(raw) = lengths.first().filter(|raw| !raw.is_empty()) else {
            return Ok(None);
        };
        if !raw.bytes().all(|byte| byte.is_ascii_digit()) {
            return Err(BodyError::malformed("Content-Length is not a number"));
        }
        let Ok(length) = raw.parse::<u64>() else {
            return Err(BodyError::malformed("Content-Length is not a number"));
        };
        if length == 0 {
            return Ok(None);
        }
        let mut body = Vec::new();
        source.take(length).read_to_end(&mut body).map_err(BodyError::Io)?;
        if (body.len() as u64) < length {
            return Err(BodyError::Malformed(format!("the body ended after {} of its {length} bytes", body.len())));
        }
        Ok(Some(body))
    }

    /// The chunks' data joined: each a hex size line, its bytes, a line end; the last of size 0, then
    /// the trailers up to a blank line, read and let go.
    fn chunks(source: &mut impl BufRead) -> Result<Vec<u8>, BodyError> {
        let mut joined = Vec::new();
        loop {
            let line = Self::line(source).map_err(BodyError::Io)?;
            if !line.ends_with(b"\n") {
                return Err(BodyError::malformed(if line.len() > Self::LINE {
                    "a chunk's size line is too long"
                } else {
                    "the body ended inside its chunks"
                }));
            }
            let count = Self::size(&line)?;
            if count == 0 {
                Self::trailers(source)?;
                return Ok(joined);
            }
            let before = joined.len() as u64;
            source.take(count).read_to_end(&mut joined).map_err(BodyError::Io)?;
            if (joined.len() as u64) - before < count {
                return Err(BodyError::malformed("the body ended inside a chunk"));
            }
            let end = Self::line(source).map_err(BodyError::Io)?;
            if end != b"\r\n" && end != b"\n" {
                return Err(BodyError::malformed("a chunk does not end where its size says"));
            }
        }
    }

    /// A chunk's size from its line, `;` extensions stepped over.
    fn size(line: &[u8]) -> Result<u64, BodyError> {
        let digits = line.split(|byte| *byte == b';').next().unwrap_or_default().trim_ascii();
        // `from_str_radix` takes a sign too, and a size has none; an empty one it refuses by itself.
        let hex = digits.iter().all(u8::is_ascii_hexdigit).then(|| std::str::from_utf8(digits).ok()).flatten();
        hex.and_then(|text| u64::from_str_radix(text, 16).ok())
            .ok_or_else(|| BodyError::malformed("a chunk's size is not a hex number"))
    }

    /// The fields after the last chunk, up to the blank line that ends the body. A client that closes
    /// after the last chunk has ended it too.
    fn trailers(source: &mut impl BufRead) -> Result<(), BodyError> {
        for _ in 0..Self::TRAILERS {
            let line = Self::line(source).map_err(BodyError::Io)?;
            if line == b"\r\n" || line == b"\n" || line.is_empty() {
                return Ok(());
            }
        }
        Err(BodyError::Malformed(format!("more than {} trailer lines", Self::TRAILERS)))
    }

    /// One line, no longer than `LINE` + 1 bytes: Python's `readline(limit)`.
    fn line(source: &mut impl BufRead) -> io::Result<Vec<u8>> {
        let mut line = Vec::new();
        source.take((Self::LINE + 1) as u64).read_until(b'\n', &mut line)?;
        Ok(line)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Cursor;

    fn read(fields: &[(&str, &str)], sent: &[u8]) -> Result<Option<Vec<u8>>, BodyError> {
        let mut headers = Headers::new();
        for (name, value) in fields {
            headers.push(*name, value.as_bytes());
        }
        RequestBody::read(&headers, &mut Cursor::new(sent.to_vec()))
    }

    fn words(result: Result<Option<Vec<u8>>, BodyError>) -> String {
        match result {
            Err(BodyError::Malformed(words)) => words,
            other => panic!("expected a refusal, got {other:?}"),
        }
    }

    #[test]
    fn by_its_length() {
        assert_eq!(read(&[("Content-Length", "2")], b"abc").unwrap().unwrap(), b"ab");
        assert_eq!(read(&[], b"abc").unwrap(), None);
        assert_eq!(read(&[("Content-Length", "0")], b"abc").unwrap(), None);
        assert_eq!(read(&[("Content-Length", "")], b"abc").unwrap(), None);
    }

    #[test]
    fn a_length_it_cannot_trust_is_refused() {
        assert_eq!(words(read(&[("Content-Length", "x")], b"")), "Content-Length is not a number");
        assert_eq!(words(read(&[("Content-Length", "-1")], b"")), "Content-Length is not a number");
        assert_eq!(
            words(read(&[("Content-Length", "1"), ("Content-Length", "2")], b"ab")),
            "Content-Length is given twice, differently"
        );
        assert_eq!(words(read(&[("Content-Length", "5")], b"ab")), "the body ended after 2 of its 5 bytes");
    }

    #[test]
    fn the_same_length_twice_is_one_length() {
        assert_eq!(read(&[("Content-Length", "2"), ("Content-Length", "2")], b"abc").unwrap().unwrap(), b"ab");
    }

    #[test]
    fn by_its_chunks() {
        let chunked = [("Transfer-Encoding", "chunked")];
        assert_eq!(read(&chunked, b"3\r\nabc\r\n2;ext=1\r\nde\r\n0\r\nTrailer: x\r\n\r\n").unwrap().unwrap(), b"abcde");
        assert_eq!(read(&[("Transfer-Encoding", "Chunked")], b"1\nz\n0\n\n").unwrap().unwrap(), b"z");
        // No chunks at all is an empty body, not none: the request said it would send them.
        assert_eq!(read(&chunked, b"0\r\n\r\n").unwrap().unwrap(), b"");
        // A client that closes after the last chunk has ended it too.
        assert_eq!(read(&chunked, b"0\r\n").unwrap().unwrap(), b"");
    }

    #[test]
    fn the_body_ends_where_it_says_and_what_follows_stays_unread() {
        for sent in [&b"1\r\nz\r\n0\r\n\r\nNEXT"[..], &b"1\nz\n0\n\nNEXT"[..], &b"1\r\nz\r\n0\r\nT: v\r\n\r\nNEXT"[..]] {
            let mut headers = Headers::new();
            headers.push("Transfer-Encoding", "chunked");
            let mut source = Cursor::new(sent.to_vec());
            assert_eq!(RequestBody::read(&headers, &mut source).unwrap().unwrap(), b"z");
            let mut rest = String::new();
            source.read_to_string(&mut rest).unwrap();
            assert_eq!(rest, "NEXT");
        }
    }

    #[test]
    fn chunks_it_cannot_read_are_refused() {
        let chunked = [("Transfer-Encoding", "chunked")];
        assert_eq!(
            words(read(&[("Transfer-Encoding", "gzip, chunked")], b"")),
            "Transfer-Encoding gzip, chunked is not read: send the body by its length or in chunks"
        );
        assert_eq!(words(read(&chunked, b"zz\r\n")), "a chunk's size is not a hex number");
        assert_eq!(words(read(&chunked, b"\r\n")), "a chunk's size is not a hex number");
        assert_eq!(words(read(&chunked, b"")), "the body ended inside its chunks");
        assert_eq!(words(read(&chunked, b"+1\r\nz\r\n")), "a chunk's size is not a hex number");
        assert_eq!(words(read(&chunked, b"3\r\nab")), "the body ended inside a chunk");
        assert_eq!(words(read(&chunked, b"2\r\nab\r\n3\r\nc")), "the body ended inside a chunk");
        let at_the_limit = vec![b'1'; 4096];
        assert_eq!(words(read(&chunked, &at_the_limit)), "the body ended inside its chunks");
        assert_eq!(words(read(&chunked, b"3\r\nabcX\r\n")), "a chunk does not end where its size says");
        let long = vec![b'1'; 5000];
        assert_eq!(words(read(&chunked, &long)), "a chunk's size line is too long");
        let mut many = b"0\r\n".to_vec();
        for _ in 0..65 {
            many.extend_from_slice(b"T: x\r\n");
        }
        assert_eq!(words(read(&chunked, &many)), "more than 64 trailer lines");
    }
}
