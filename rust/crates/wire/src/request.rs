//! A request's head off the wire.

use crate::headers::Headers;
use std::io::{self, BufRead};

/// Why a head could not be read.
#[derive(Debug)]
pub enum HeadError {
    /// The peer closed the connection before a whole head; before its first byte, nothing was asked.
    Closed,
    /// The socket failed, or waited past its time.
    Io(io::Error),
    /// The bytes are not an HTTP request; the words say why.
    Malformed(String),
}

/// The request line and the fields of one request.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RequestHead {
    /// `GET`, `POST`…
    pub method: String,
    /// The target as sent: the path and the query.
    pub target: String,
    /// The fields.
    pub headers: Headers,
}

impl RequestHead {
    /// The most a head may take. Python's `http.server` allows 65536 per line and 100 fields.
    pub const LIMIT: usize = 262_144;
    /// The most fields a head may carry.
    pub const FIELDS: usize = 128;

    /// Reads one head and leaves the body unread in `source`.
    pub fn read(source: &mut impl BufRead) -> Result<Self, HeadError> {
        let raw = Self::raw_head(source)?;
        let mut slots = [httparse::EMPTY_HEADER; Self::FIELDS];
        let mut parsed = httparse::Request::new(&mut slots);
        match parsed.parse(&raw) {
            Ok(httparse::Status::Complete(_)) => {}
            Ok(httparse::Status::Partial) => return Err(HeadError::Malformed("the head ended too early".into())),
            Err(error) => return Err(HeadError::Malformed(error.to_string())),
        }
        let (Some(method), Some(target)) = (parsed.method, parsed.path) else {
            return Err(HeadError::Malformed("no request line".into()));
        };
        let mut headers = Headers::new();
        for field in parsed.headers.iter() {
            headers.push(field.name, field.value);
        }
        Ok(Self { method: method.to_string(), target: target.to_string(), headers })
    }

    /// The head's bytes up to its blank line, the line included. A line at a time, so that not a
    /// byte of the body is taken.
    fn raw_head(source: &mut impl BufRead) -> Result<Vec<u8>, HeadError> {
        let mut raw = Vec::with_capacity(1024);
        loop {
            let before = raw.len();
            let read = source.read_until(b'\n', &mut raw).map_err(HeadError::Io)?;
            if read == 0 {
                return Err(if raw.is_empty() {
                    HeadError::Closed
                } else {
                    HeadError::Malformed("the head ended too early".into())
                });
            }
            if raw.len() > Self::LIMIT {
                return Err(HeadError::Malformed("the head is too long".into()));
            }
            let line = raw.get(before..).unwrap_or_default();
            if line == b"\r\n" || line == b"\n" {
                if before == 0 {
                    // A blank line before the request line is allowed by RFC 9112 2.2, and skipped.
                    raw.clear();
                    continue;
                }
                return Ok(raw);
            }
        }
    }

    /// The target's path, without its query.
    pub fn path(&self) -> &str {
        self.target.split_once('?').map_or(self.target.as_str(), |(path, _)| path)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::{BufReader, Cursor, Read};

    fn head_of(text: &[u8]) -> Result<RequestHead, HeadError> {
        RequestHead::read(&mut BufReader::new(Cursor::new(text.to_vec())))
    }

    #[test]
    fn reads_the_line_and_the_fields_as_they_came() {
        let head = head_of(b"POST /v1/chat/completions?x=1 HTTP/1.1\r\nHost: a\r\nX-Two: 1\r\nx-two: 2\r\n\r\nbody").unwrap();
        assert_eq!(head.method, "POST");
        assert_eq!(head.target, "/v1/chat/completions?x=1");
        assert_eq!(head.path(), "/v1/chat/completions");
        assert_eq!(head.headers.get("HOST").as_deref(), Some("a"));
        assert_eq!(head.headers.get("x-two").as_deref(), Some("1"));
        assert_eq!(head.headers.all("X-TWO"), vec!["1", "2"]);
    }

    #[test]
    fn leaves_the_body_unread() {
        let mut source = BufReader::new(Cursor::new(b"GET / HTTP/1.1\r\n\r\nbody".to_vec()));
        RequestHead::read(&mut source).unwrap();
        let mut rest = String::new();
        source.read_to_string(&mut rest).unwrap();
        assert_eq!(rest, "body");
    }

    #[test]
    fn a_closed_connection_and_a_cut_head_are_two_answers() {
        assert!(matches!(head_of(b""), Err(HeadError::Closed)));
        assert!(matches!(head_of(b"GET / HTTP/1.1\r\nHost"), Err(HeadError::Malformed(_))));
        assert!(matches!(head_of(b"not http\r\n\r\n"), Err(HeadError::Malformed(_))));
    }

    #[test]
    fn a_blank_line_before_the_request_is_skipped() {
        assert_eq!(head_of(b"\r\nGET /x HTTP/1.1\r\n\r\n").unwrap().target, "/x");
    }

    /// A head of exactly `size` bytes, one long field in it.
    fn head_of_size(size: usize) -> Vec<u8> {
        let start = b"GET / HTTP/1.1\r\nX-Long: ".to_vec();
        let padding = size - start.len() - 4;
        let mut text = start;
        text.extend(std::iter::repeat_n(b'x', padding));
        text.extend_from_slice(b"\r\n\r\n");
        text
    }

    #[test]
    fn a_head_at_its_limit_reads_and_a_byte_past_it_is_refused() {
        assert_eq!(head_of_size(262_144).len(), 262_144);
        assert!(head_of(&head_of_size(262_144)).is_ok());
        match head_of(&head_of_size(262_145)) {
            Err(HeadError::Malformed(words)) => assert_eq!(words, "the head is too long"),
            other => panic!("{other:?}"),
        }
    }

    #[test]
    fn a_head_with_too_many_fields_is_refused() {
        let mut text = b"GET / HTTP/1.1\r\n".to_vec();
        for at in 0..200 {
            text.extend_from_slice(format!("X-{at}: value\r\n").as_bytes());
        }
        text.extend_from_slice(b"\r\n");
        assert!(matches!(head_of(&text), Err(HeadError::Malformed(_))));
    }

    #[test]
    fn a_blank_line_after_a_field_ends_the_head_with_either_line_end() {
        assert_eq!(head_of(b"GET /a HTTP/1.1\nHost: x\n\nbody").unwrap().target, "/a");
        assert_eq!(head_of(b"\nGET /b HTTP/1.1\r\n\r\n").unwrap().target, "/b");
    }
}
