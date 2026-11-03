//! A stream cut into lines: what an event stream is relayed by.

use std::io::{self, Read};

/// What the next line is.
#[derive(Debug, PartialEq, Eq)]
pub enum Next {
    /// A line with its end, or as much of one as `Lines::LIMIT` allows.
    Line(Vec<u8>),
    /// The stream has ended and everything has been given.
    End,
}

/// Lines from a `Read`. What has come of a line stays here when a read waits its time: asked again,
/// the line goes on from where it was.
pub struct Lines<R> {
    source: R,
    held: Vec<u8>,
    from: usize,
    ended: bool,
}

impl<R: Read> Lines<R> {
    /// The longest piece given at once: Python's `readline(65536)` on the relay.
    pub const LIMIT: usize = 65_536;
    /// How much is asked of the source at a time.
    const READ: usize = 16_384;

    /// Lines of `source`.
    pub fn new(source: R) -> Self {
        Self { source, held: Vec::new(), from: 0, ended: false }
    }

    /// The source, for what only it can answer.
    pub fn source(&self) -> &R {
        &self.source
    }

    /// The next line. Fails only as the source fails, a read that waited its time included; bytes held
    /// are kept for the next call.
    pub fn next_line(&mut self) -> io::Result<Next> {
        loop {
            if let Some(line) = self.cut() {
                return Ok(Next::Line(line));
            }
            if self.ended {
                return Ok(Next::End);
            }
            self.fill()?;
        }
    }

    /// A line out of what is held, if a whole one is there, or a piece at the limit, or the last
    /// bytes when the stream has ended.
    fn cut(&mut self) -> Option<Vec<u8>> {
        let rest = self.held.get(self.from..).unwrap_or_default();
        if rest.is_empty() {
            return None;
        }
        let window = rest.get(..Self::LIMIT.min(rest.len())).unwrap_or_default();
        let at = window.iter().position(|byte| *byte == b'\n').map(|at| at + 1);
        let take = match at {
            Some(take) => take,
            None if rest.len() >= Self::LIMIT => Self::LIMIT,
            None if self.ended => rest.len(),
            None => return None,
        };
        let line = rest.get(..take).unwrap_or_default().to_vec();
        self.from += take;
        Some(line)
    }

    fn fill(&mut self) -> io::Result<()> {
        if self.from > 0 {
            self.held.drain(..self.from);
            self.from = 0;
        }
        let before = self.held.len();
        self.held.resize(before + Self::READ, 0);
        let read = self.source.read(self.held.get_mut(before..).unwrap_or_default());
        // absent-ok: a read that failed brought no bytes; the failure itself goes up on the next line.
        self.held.truncate(before + read.as_ref().copied().unwrap_or(0));
        if read? == 0 {
            self.ended = true;
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Cursor;

    /// Pieces one read at a time, with a wait before each.
    struct Stutter(Vec<Vec<u8>>, bool);

    impl Read for Stutter {
        fn read(&mut self, out: &mut [u8]) -> io::Result<usize> {
            self.1 = !self.1;
            if self.1 {
                return Err(io::Error::new(io::ErrorKind::WouldBlock, "waited"));
            }
            if self.0.is_empty() {
                return Ok(0);
            }
            let piece = self.0.remove(0);
            out[..piece.len()].copy_from_slice(&piece);
            Ok(piece.len())
        }
    }

    fn all(lines: &mut Lines<impl Read>) -> Vec<Vec<u8>> {
        let mut out = Vec::new();
        loop {
            match lines.next_line() {
                Ok(Next::Line(line)) => out.push(line),
                Ok(Next::End) => return out,
                Err(error) if error.kind() == io::ErrorKind::WouldBlock => {}
                Err(error) => panic!("{error}"),
            }
        }
    }

    #[test]
    fn cuts_at_each_line_end_and_keeps_the_end() {
        let mut lines = Lines::new(Cursor::new(b"a\n\nb\r\nlast".to_vec()));
        assert_eq!(all(&mut lines), vec![b"a\n".to_vec(), b"\n".to_vec(), b"b\r\n".to_vec(), b"last".to_vec()]);
    }

    #[test]
    fn a_line_split_by_waits_comes_whole() {
        let mut lines = Lines::new(Stutter(vec![b"da".to_vec(), b"ta: 1\n\nda".to_vec(), b"ta: 2\n".to_vec()], false));
        assert_eq!(all(&mut lines), vec![b"data: 1\n".to_vec(), b"\n".to_vec(), b"data: 2\n".to_vec()]);
    }

    #[test]
    fn what_has_been_given_does_not_stay_in_memory() {
        let mut sent = Vec::new();
        for _ in 0..50_000 {
            sent.extend_from_slice(b"data: 1234567890\n");
        }
        let mut lines = Lines::new(Cursor::new(sent));
        let mut most = 0;
        while let Next::Line(_) = lines.next_line().unwrap() {
            most = most.max(lines.held.len());
        }
        assert!(most < 3 * 16_384, "{most} bytes held at once");
    }

    #[test]
    fn a_line_past_the_limit_comes_in_pieces() {
        let mut sent = vec![b'x'; Lines::<Cursor<Vec<u8>>>::LIMIT + 3];
        sent.push(b'\n');
        let mut lines = Lines::new(Cursor::new(sent));
        let got = all(&mut lines);
        assert_eq!(got.len(), 2);
        assert_eq!(got[0].len(), Lines::<Cursor<Vec<u8>>>::LIMIT);
        assert_eq!(got[1], b"xxx\n");
    }
}
