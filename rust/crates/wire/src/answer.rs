//! An upstream's answer: its head, and its body under whichever framing the head says.
//!
//! The body is read through a state kept in the object, not on the stack: a socket read that waited
//! its time (the relay wakes every two seconds to ask whether the client is still there) leaves the
//! decoder exactly where it was, in the middle of a chunk's size line if it must.

use crate::headers::Headers;
use std::io::{self, BufRead, BufReader, Read};

/// An answer's status line and fields.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AnswerHead {
    /// The status code.
    pub status: u16,
    /// The words after the code.
    pub reason: String,
    /// The fields.
    pub headers: Headers,
    /// Whether the connection ends with this answer: HTTP/1.0, or `Connection: close`.
    pub closes: bool,
}

impl AnswerHead {
    /// The most a head may take.
    const LIMIT: usize = 262_144;
    /// The most fields a head may carry.
    const FIELDS: usize = 128;

    fn parse(raw: &[u8]) -> io::Result<Self> {
        let mut slots = [httparse::EMPTY_HEADER; Self::FIELDS];
        let mut parsed = httparse::Response::new(&mut slots);
        match parsed.parse(raw) {
            Ok(httparse::Status::Complete(_)) => {}
            Ok(httparse::Status::Partial) => return Err(Self::bad("the answer's head ended too early")),
            Err(error) => return Err(Self::bad(&format!("the answer's head does not read: {error}"))),
        }
        let Some(status) = parsed.code else {
            return Err(Self::bad("the answer has no status"));
        };
        let mut headers = Headers::new();
        for field in parsed.headers.iter() {
            headers.push(field.name, field.value);
        }
        // absent-ok: a status line may have no words after its code; they are relayed as they came.
        let reason = parsed.reason.unwrap_or_default().to_string();
        let says_close = headers.get("Connection").is_some_and(|value| value.to_lowercase().contains("close"));
        Ok(Self { status, reason, closes: parsed.version == Some(0) || says_close, headers })
    }

    fn bad(words: &str) -> io::Error {
        io::Error::new(io::ErrorKind::InvalidData, words.to_string())
    }
}

/// An answer's head on its way in. What has come of it stays here when a read waits its time: the reader is asked again
/// and goes on from where it was.
#[derive(Debug, Default)]
pub struct AnswerHeadReader {
    raw: Vec<u8>,
    line_start: usize,
}

impl AnswerHeadReader {
    /// A reader at the start of an answer.
    pub fn new() -> Self {
        Self::default()
    }

    /// The answer's head, stepping over any `100 Continue` before it. Fails as the source fails, a read that waited its
    /// time included.
    pub fn read(&mut self, source: &mut impl BufRead) -> io::Result<AnswerHead> {
        loop {
            self.read_lines(source)?;
            let head = AnswerHead::parse(&self.raw)?;
            self.raw.clear();
            self.line_start = 0;
            if head.status >= 200 || head.status == 101 {
                return Ok(head);
            }
        }
    }

    /// Lines up to the head's blank one.
    fn read_lines(&mut self, source: &mut impl BufRead) -> io::Result<()> {
        loop {
            if source.read_until(b'\n', &mut self.raw)? == 0 {
                let words = if self.raw.is_empty() {
                    "the upstream closed without an answer"
                } else {
                    "the answer's head ended too early"
                };
                return Err(io::Error::new(io::ErrorKind::UnexpectedEof, words));
            }
            if self.raw.len() > AnswerHead::LIMIT {
                return Err(AnswerHead::bad("the answer's head is too long"));
            }
            let line = self.raw.get(self.line_start..).unwrap_or_default();
            if line == b"\r\n" || line == b"\n" {
                return Ok(());
            }
            if line.ends_with(b"\n") {
                self.line_start = self.raw.len();
            }
        }
    }
}

/// How far a chunked body has been read.
#[derive(Debug, Clone, PartialEq, Eq)]
enum Chunk {
    /// Reading a size line; what has come of it so far.
    Size(Vec<u8>),
    /// Inside a chunk's data: how much is left.
    Data(u64),
    /// Reading the line end after a chunk's data.
    DataEnd(Vec<u8>),
    /// Reading the trailers after the last chunk; what has come of the current line.
    Trailer(Vec<u8>),
}

/// How the body ends.
#[derive(Debug, Clone, PartialEq, Eq)]
enum Framing {
    /// By its stated length: how much is left.
    Length(u64),
    /// In chunks.
    Chunked(Chunk),
    /// When the connection closes.
    UntilClose,
    /// It has ended.
    Done,
}

/// An answer's body as plain bytes, whatever its framing. Holds the buffered socket.
pub struct AnswerBody<R> {
    source: BufReader<R>,
    framing: Framing,
}

impl<R: Read> AnswerBody<R> {
    /// The longest line of a chunked body's framing.
    const LINE_LIMIT: usize = 65_536;

    /// The body that follows `head` on `source`, the answer to a request of `method`. The rules are
    /// `http.client`'s: chunked wins over a length, a length that does not read is none, and an answer to
    /// HEAD, a 1xx, a 204 and a 304 have no body.
    pub fn new(source: BufReader<R>, head: &AnswerHead, method: &str) -> Self {
        Self { source, framing: Self::framing(head, method) }
    }

    fn framing(head: &AnswerHead, method: &str) -> Framing {
        if method.eq_ignore_ascii_case("HEAD") || head.status < 200 || head.status == 204 || head.status == 304 {
            return Framing::Done;
        }
        let chunked = head.headers.get("Transfer-Encoding").is_some_and(|value| value.trim().eq_ignore_ascii_case("chunked"));
        if chunked {
            return Framing::Chunked(Chunk::Size(Vec::new()));
        }
        match head.headers.get("Content-Length").and_then(|value| value.trim().parse::<u64>().ok()) {
            Some(0) => Framing::Done,
            Some(length) => Framing::Length(length),
            None => Framing::UntilClose,
        }
    }

    /// Whether all of it has been read.
    pub fn is_done(&self) -> bool {
        matches!(self.framing, Framing::Done)
    }

    /// Whether only the connection's end can end it.
    pub fn until_close(&self) -> bool {
        matches!(self.framing, Framing::UntilClose)
    }

    /// The buffered connection it was read from.
    pub fn into_source(self) -> BufReader<R> {
        self.source
    }

    /// One step through a chunked body: the bytes of data read into `out`, or 0 with the state moved on.
    fn chunk_step(&mut self, chunk: Chunk, out: &mut [u8]) -> io::Result<usize> {
        match chunk {
            Chunk::Size(held) => self.chunk_size_step(held),
            Chunk::Data(left) => self.chunk_data_step(left, out),
            Chunk::DataEnd(held) => self.chunk_end_step(held),
            Chunk::Trailer(held) => self.chunk_trailer_step(held),
        }
    }

    fn chunk_size_step(&mut self, mut held: Vec<u8>) -> io::Result<usize> {
        let keep = |held: Vec<u8>| Framing::Chunked(Chunk::Size(held));
        self.framing = keep(Vec::new());
        match self.line_step(&mut held) {
            Ok(true) => {}
            Ok(false) => {
                self.framing = keep(held);
                return Ok(0);
            }
            Err(error) => {
                self.framing = keep(held);
                return Err(error);
            }
        }
        let digits = held.split(|byte| *byte == b';').next().unwrap_or_default().trim_ascii();
        let Some(size) = std::str::from_utf8(digits).ok().and_then(|text| u64::from_str_radix(text, 16).ok()) else {
            return Err(AnswerHead::bad("a chunk's size is not a hex number"));
        };
        self.framing = Framing::Chunked(if size == 0 { Chunk::Trailer(Vec::new()) } else { Chunk::Data(size) });
        Ok(0)
    }

    fn chunk_data_step(&mut self, left: u64, out: &mut [u8]) -> io::Result<usize> {
        self.framing = Framing::Chunked(Chunk::Data(left));
        let room = usize::try_from(left).unwrap_or(usize::MAX).min(out.len());
        let target = out.get_mut(..room).unwrap_or_default();
        let got = self.source.read(target)?;
        if got == 0 {
            return Err(io::Error::new(io::ErrorKind::UnexpectedEof, "the answer ended inside a chunk"));
        }
        let left = left - got as u64;
        self.framing = Framing::Chunked(if left == 0 { Chunk::DataEnd(Vec::new()) } else { Chunk::Data(left) });
        Ok(got)
    }

    fn chunk_end_step(&mut self, mut held: Vec<u8>) -> io::Result<usize> {
        match self.line_step(&mut held) {
            Ok(true) => {
                self.framing = Framing::Chunked(Chunk::Size(Vec::new()));
                Ok(0)
            }
            Ok(false) => {
                self.framing = Framing::Chunked(Chunk::DataEnd(held));
                Ok(0)
            }
            Err(error) => {
                self.framing = Framing::Chunked(Chunk::DataEnd(held));
                Err(error)
            }
        }
    }

    fn chunk_trailer_step(&mut self, mut held: Vec<u8>) -> io::Result<usize> {
        match self.line_step(&mut held) {
            Ok(true) if held == b"\r\n" || held == b"\n" => {
                self.framing = Framing::Done;
                Ok(0)
            }
            Ok(true) => {
                self.framing = Framing::Chunked(Chunk::Trailer(Vec::new()));
                Ok(0)
            }
            Ok(false) => {
                self.framing = Framing::Chunked(Chunk::Trailer(held));
                Ok(0)
            }
            // A server that closes after its last chunk has ended the body; http.client takes it too.
            Err(error) if error.kind() == io::ErrorKind::UnexpectedEof => {
                self.framing = Framing::Done;
                Ok(0)
            }
            Err(error) => {
                self.framing = Framing::Chunked(Chunk::Trailer(held));
                Err(error)
            }
        }
    }

    /// Moves buffered bytes of the current line into `held`. `true` once the line's end is in it.
    fn line_step(&mut self, held: &mut Vec<u8>) -> io::Result<bool> {
        let available = self.source.fill_buf()?;
        if available.is_empty() {
            return Err(io::Error::new(io::ErrorKind::UnexpectedEof, "the answer ended inside its chunks"));
        }
        let (take, done) = match available.iter().position(|byte| *byte == b'\n') {
            Some(at) => (at + 1, true),
            None => (available.len(), false),
        };
        held.extend_from_slice(available.get(..take).unwrap_or_default());
        self.source.consume(take);
        if held.len() > Self::LINE_LIMIT {
            return Err(AnswerHead::bad("a chunk's line is too long"));
        }
        Ok(done)
    }
}

impl<R: Read> Read for AnswerBody<R> {
    /// Bytes of the body; 0 only at its end. A read that waited its time fails with the socket's
    /// `WouldBlock` or `TimedOut` and may simply be asked again.
    fn read(&mut self, out: &mut [u8]) -> io::Result<usize> {
        if out.is_empty() {
            return Ok(0);
        }
        loop {
            match std::mem::replace(&mut self.framing, Framing::Done) {
                Framing::Done => return Ok(0),
                Framing::UntilClose => {
                    self.framing = Framing::UntilClose;
                    let got = self.source.read(out)?;
                    if got == 0 {
                        self.framing = Framing::Done;
                    }
                    return Ok(got);
                }
                Framing::Length(left) => {
                    self.framing = Framing::Length(left);
                    let room = usize::try_from(left).unwrap_or(usize::MAX).min(out.len());
                    let got = self.source.read(out.get_mut(..room).unwrap_or_default())?;
                    if got == 0 {
                        return Err(io::Error::new(io::ErrorKind::UnexpectedEof, "the answer ended before its length"));
                    }
                    let left = left - got as u64;
                    self.framing = if left == 0 { Framing::Done } else { Framing::Length(left) };
                    return Ok(got);
                }
                Framing::Chunked(chunk) => {
                    let got = self.chunk_step(chunk, out)?;
                    if got > 0 {
                        return Ok(got);
                    }
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Cursor;

    /// A source that hands out its pieces one read at a time, failing with `TimedOut` between them:
    /// a socket whose read waited its time.
    struct Stutter {
        pieces: Vec<Vec<u8>>,
        at: usize,
        waited: bool,
    }

    impl Stutter {
        fn of(pieces: &[&[u8]]) -> Self {
            Self { pieces: pieces.iter().map(|piece| piece.to_vec()).collect(), at: 0, waited: false }
        }
    }

    impl Read for Stutter {
        fn read(&mut self, out: &mut [u8]) -> io::Result<usize> {
            if !self.waited {
                self.waited = true;
                return Err(io::Error::new(io::ErrorKind::TimedOut, "waited"));
            }
            self.waited = false;
            let Some(piece) = self.pieces.get_mut(self.at) else {
                return Ok(0);
            };
            let count = piece.len().min(out.len());
            out[..count].copy_from_slice(&piece[..count]);
            piece.drain(..count);
            if piece.is_empty() {
                self.at += 1;
            }
            Ok(count)
        }
    }

    fn head(fields: &[(&str, &str)], status: u16) -> AnswerHead {
        let mut headers = Headers::new();
        for (name, value) in fields {
            headers.push(*name, value.as_bytes());
        }
        AnswerHead { status, reason: String::new(), headers, closes: false }
    }

    fn body_of(fields: &[(&str, &str)], status: u16, sent: &[u8]) -> io::Result<Vec<u8>> {
        let mut body = AnswerBody::new(BufReader::new(Cursor::new(sent.to_vec())), &head(fields, status), "POST");
        let mut out = Vec::new();
        body.read_to_end(&mut out)?;
        Ok(out)
    }

    #[test]
    fn reads_a_head_and_steps_over_continue() {
        let sent = b"HTTP/1.1 100 Continue\r\n\r\nHTTP/1.1 503 Service Unavailable\r\nContent-Type: text/plain\r\n\r\nrest";
        let mut source = BufReader::new(Cursor::new(sent.to_vec()));
        let head = AnswerHeadReader::new().read(&mut source).unwrap();
        assert_eq!((head.status, head.reason.as_str()), (503, "Service Unavailable"));
        assert_eq!(head.headers.get("content-type").as_deref(), Some("text/plain"));
        let mut rest = String::new();
        source.read_to_string(&mut rest).unwrap();
        assert_eq!(rest, "rest");
    }

    #[test]
    fn a_wait_inside_the_head_loses_nothing() {
        let pieces: &[&[u8]] = &[b"HTTP/1.1 2", b"00 OK\r\nX-A", b": 1\r\n", b"\r", b"\nbody"];
        let mut source = BufReader::with_capacity(4, Stutter::of(pieces));
        let mut reader = AnswerHeadReader::new();
        let mut waits = 0;
        let head = loop {
            match reader.read(&mut source) {
                Ok(head) => break head,
                Err(error) if error.kind() == io::ErrorKind::TimedOut => waits += 1,
                Err(error) => panic!("{error}"),
            }
        };
        assert_eq!((head.status, head.headers.get("x-a").as_deref()), (200, Some("1")));
        assert!(waits >= pieces.len() - 1, "{waits} waits seen");
        let mut rest = Vec::new();
        loop {
            match source.read_to_end(&mut rest) {
                Ok(_) => break,
                Err(error) if error.kind() == io::ErrorKind::TimedOut => {}
                Err(error) => panic!("{error}"),
            }
        }
        assert_eq!(rest, b"body");
    }

    #[test]
    fn a_head_at_its_limit_reads_and_a_byte_past_it_is_refused() {
        let of_size = |size: usize| {
            let mut text = b"HTTP/1.1 200 OK\r\nX-Long: ".to_vec();
            let padding = size - text.len() - 4;
            text.extend(std::iter::repeat_n(b'x', padding));
            text.extend_from_slice(b"\r\n\r\n");
            AnswerHeadReader::new().read(&mut BufReader::new(Cursor::new(text)))
        };
        assert_eq!(of_size(262_144).unwrap().status, 200);
        let refused = of_size(262_145).unwrap_err();
        assert_eq!((refused.kind(), refused.to_string().as_str()), (io::ErrorKind::InvalidData, "the answer's head is too long"));
    }

    #[test]
    fn a_closed_socket_and_a_cut_head_say_which() {
        let of =
            |sent: &[u8]| AnswerHeadReader::new().read(&mut BufReader::new(Cursor::new(sent.to_vec()))).unwrap_err().to_string();
        assert_eq!(of(b""), "the upstream closed without an answer");
        assert_eq!(of(b"HTTP/1.1 200"), "the answer's head ended too early");
    }

    #[test]
    fn a_closed_socket_is_not_an_answer() {
        let mut source = BufReader::new(Cursor::new(Vec::new()));
        assert_eq!(AnswerHeadReader::new().read(&mut source).unwrap_err().kind(), io::ErrorKind::UnexpectedEof);
    }

    #[test]
    fn each_framing_ends_where_it_says() {
        assert_eq!(body_of(&[("Content-Length", "2")], 200, b"abc").unwrap(), b"ab");
        assert_eq!(body_of(&[], 200, b"abc").unwrap(), b"abc");
        assert_eq!(body_of(&[("Content-Length", "x")], 200, b"abc").unwrap(), b"abc");
        assert_eq!(body_of(&[("Content-Length", "0")], 200, b"abc").unwrap(), b"");
        assert_eq!(
            body_of(&[("Transfer-Encoding", "chunked"), ("Content-Length", "1")], 200, b"2\r\nab\r\n0\r\n\r\nX").unwrap(),
            b"ab"
        );
        assert_eq!(body_of(&[], 204, b"abc").unwrap(), b"");
        assert_eq!(body_of(&[], 304, b"abc").unwrap(), b"");
    }

    #[test]
    fn an_answer_with_no_body_by_its_kind_reads_none() {
        let of = |status: u16, method: &str| {
            let mut out = Vec::new();
            AnswerBody::new(BufReader::new(Cursor::new(b"abc".to_vec())), &head(&[], status), method)
                .read_to_end(&mut out)
                .unwrap();
            out
        };
        assert_eq!(of(200, "HEAD"), b"");
        assert_eq!(of(200, "head"), b"");
        assert_eq!(of(101, "POST"), b"");
        assert_eq!(of(199, "POST"), b"");
        assert_eq!(of(200, "POST"), b"abc");
        assert_eq!(of(404, "POST"), b"abc");
    }

    #[test]
    fn a_read_into_nothing_moves_nothing() {
        let chunked = [("Transfer-Encoding", "chunked")];
        let mut body =
            AnswerBody::new(BufReader::new(Cursor::new(b"1\r\na\r\n0\r\n\r\n".to_vec())), &head(&chunked, 200), "POST");
        assert_eq!(body.read(&mut []).unwrap(), 0);
        let mut out = Vec::new();
        body.read_to_end(&mut out).unwrap();
        assert_eq!(out, b"a");
    }

    /// Bytes, then a read that fails: a socket with nothing more to say and no end to its silence.
    struct ThenSilence(Cursor<Vec<u8>>);

    impl Read for ThenSilence {
        fn read(&mut self, out: &mut [u8]) -> io::Result<usize> {
            match self.0.read(out)? {
                0 => Err(io::Error::new(io::ErrorKind::TimedOut, "silent")),
                count => Ok(count),
            }
        }
    }

    #[test]
    fn the_blank_line_after_the_trailers_ends_the_body_with_no_more_reads() {
        for sent in [&b"1\r\na\r\n0\r\n\r\n"[..], &b"1\na\n0\n\n"[..], &b"1\r\na\r\n0\r\nT: v\r\n\r\n"[..]] {
            let source = BufReader::new(ThenSilence(Cursor::new(sent.to_vec())));
            let mut body = AnswerBody::new(source, &head(&[("Transfer-Encoding", "chunked")], 200), "POST");
            let mut out = Vec::new();
            body.read_to_end(&mut out).unwrap();
            assert_eq!(out, b"a");
        }
    }

    #[test]
    fn a_framing_line_past_its_limit_is_refused() {
        let line_of = |size: usize| {
            let mut sent = vec![b'1'; 1];
            sent.extend(std::iter::repeat_n(b' ', size - 2));
            sent.extend_from_slice(b"\n");
            sent.extend_from_slice(b"a\r\n0\r\n\r\n");
            sent
        };
        assert_eq!(body_of(&[("Transfer-Encoding", "chunked")], 200, &line_of(65_536)).unwrap(), b"a");
        assert_eq!(
            body_of(&[("Transfer-Encoding", "chunked")], 200, &line_of(65_537)).unwrap_err().kind(),
            io::ErrorKind::InvalidData
        );
    }

    #[test]
    fn an_answer_until_its_close_may_come_in_pieces() {
        let mut body = AnswerBody::new(BufReader::new(Stutter::of(&[b"one ", b"two"])), &head(&[], 200), "POST");
        let mut out = Vec::new();
        let mut piece = [0u8; 64];
        loop {
            match body.read(&mut piece) {
                Ok(0) => break,
                Ok(count) => out.extend_from_slice(&piece[..count]),
                Err(error) if error.kind() == io::ErrorKind::TimedOut => {}
                Err(error) => panic!("{error}"),
            }
        }
        assert_eq!(out, b"one two");
    }

    #[test]
    fn an_answer_cut_short_says_so() {
        assert_eq!(body_of(&[("Content-Length", "5")], 200, b"ab").unwrap_err().kind(), io::ErrorKind::UnexpectedEof);
        assert_eq!(
            body_of(&[("Transfer-Encoding", "chunked")], 200, b"5\r\nab").unwrap_err().kind(),
            io::ErrorKind::UnexpectedEof
        );
        assert_eq!(body_of(&[("Transfer-Encoding", "chunked")], 200, b"zz\r\n").unwrap_err().kind(), io::ErrorKind::InvalidData);
    }

    #[test]
    fn a_last_chunk_without_its_blank_line_has_ended_the_body() {
        assert_eq!(body_of(&[("Transfer-Encoding", "chunked")], 200, b"1\r\na\r\n0\r\n").unwrap(), b"a");
    }

    #[test]
    fn a_wait_anywhere_in_the_chunks_loses_nothing() {
        let pieces: &[&[u8]] = &[b"1", b"0\r", b"\n0123456", b"789abcdef\r", b"\n1;x=", b"y\r\nZ\r\n0\r\nT: ", b"v\r\n\r\n"];
        let mut body =
            AnswerBody::new(BufReader::new(Stutter::of(pieces)), &head(&[("Transfer-Encoding", "chunked")], 200), "POST");
        let mut out = Vec::new();
        let mut piece = [0u8; 64];
        let mut waits = 0;
        loop {
            match body.read(&mut piece) {
                Ok(0) => break,
                Ok(count) => out.extend_from_slice(&piece[..count]),
                Err(error) if error.kind() == io::ErrorKind::TimedOut => waits += 1,
                Err(error) => panic!("{error}"),
            }
        }
        assert_eq!(out, b"0123456789abcdefZ");
        assert!(waits >= pieces.len(), "the source waited before every piece, {waits} waits seen");
    }
}
