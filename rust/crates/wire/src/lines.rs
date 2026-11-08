//! A stream cut into lines: what an event stream is relayed by.

use std::io::{self, Read};

/// What the next line is.
#[derive(Debug, PartialEq, Eq)]
pub enum Next {
    /// A whole line, with its end — or the last bytes of a stream that ended without one.
    Line(Vec<u8>),
    /// What of a line longer than `Lines::LIMIT` has come. This is not a line, so a reader that takes a line as one event must not take
    /// this as one; a journal that says nothing about it says the stream was read whole when it was not.
    PastCap(Vec<u8>),
    /// The stream has ended and everything has been given.
    End,
}

/// Lines from a `Read`. What has come of a line stays here when a read waits its time: asked again,
/// the line goes on from where it was.
pub struct Lines<R> {
    source: R,
    held: Vec<u8>,
    from: usize,
    /// What of the line in hand has been looked at for its end: a long line is not searched again on every read.
    looked: usize,
    /// Whether the line in hand has gone past the cap. Once it has, it cannot come as one line any more, so everything of it until its
    /// end is a piece.
    past_cap: bool,
    ended: bool,
}

impl<R: Read> Lines<R> {
    /// The longest line given as one.
    ///
    /// A line is one event, and the event that ends a stream is the biggest one: `response.completed` carries the whole answer, its usage
    /// and how it ended. On a long answer that is past 64 KB, and given in pieces it parsed as nothing — the client got a stream with no
    /// last chunk, and the journal had no word for what it missed (the owner's Hermes client, 2026-11-03). A line past this is still passed
    /// on, but it is named as pieces, so nothing reads it as an event.
    pub const LIMIT: usize = 1024 * 1024;
    /// How much is asked of the source at a time.
    const READ: usize = 16_384;

    /// Lines of `source`.
    pub fn new(source: R) -> Self {
        Self { source, held: Vec::new(), from: 0, looked: 0, past_cap: false, ended: false }
    }

    /// The source, for what only it can answer.
    pub fn source(&self) -> &R {
        &self.source
    }

    /// The next line. Fails only as the source fails, a read that waited its time included; bytes held
    /// are kept for the next call.
    pub fn next_line(&mut self) -> io::Result<Next> {
        loop {
            if let Some(next) = self.cut() {
                return Ok(next);
            }
            if self.ended {
                return Ok(Next::End);
            }
            self.fill()?;
        }
    }

    /// A whole line out of what is held, a piece of a line that has gone past the cap, or the last bytes when the stream has ended.
    fn cut(&mut self) -> Option<Next> {
        if self.from >= self.held.len() {
            return None;
        }
        let in_hand = self.held.len() - self.from;
        // A line already past the cap cannot come as one any more, so its end is looked for wherever it is.
        let window = if self.past_cap { in_hand } else { Self::LIMIT.min(in_hand) };
        let mut end = None;
        let mut at = self.looked;
        while at < window {
            if matches!(self.held.get(self.from + at), Some(b'\n')) {
                end = Some(at + 1);
                break;
            }
            at += 1;
        }
        let take = match end {
            Some(take) => take,
            None if at >= Self::LIMIT => {
                self.past_cap = true;
                Self::LIMIT
            }
            None if self.ended => in_hand,
            None => {
                // Nothing held ends the line: the next read's bytes are what is searched next, not these again.
                self.looked = at;
                return None;
            }
        };
        // A piece is a piece of the long line, not the line itself, and only the last piece of it carries its end.
        let piece = self.past_cap;
        let bytes = self.held.get(self.from..self.from + take).unwrap_or_default().to_vec();
        self.from += take;
        // What was searched and not given away stays searched: the search goes on from where it stopped.
        self.looked = at.saturating_sub(take);
        if end.is_some() || self.ended {
            self.past_cap = false;
        }
        Some(if piece { Next::PastCap(bytes) } else { Next::Line(bytes) })
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
    use crate::stutter::{Patience, Stutter};
    use std::io::Cursor;

    /// Every line to the end, asked again after each of the source's waits, and for no longer than `Patience` allows.
    fn all(lines: &mut Lines<impl Read>) -> Vec<Next> {
        let mut patience = Patience::default();
        let mut out = Vec::new();
        loop {
            match patience.answer("the next line", || lines.next_line()) {
                Ok(Next::End) => return out,
                Ok(next) => out.push(next),
                Err(error) => panic!("{error}"),
            }
        }
    }

    fn line(bytes: &[u8]) -> Next {
        Next::Line(bytes.to_vec())
    }

    #[test]
    fn cuts_at_each_line_end_and_keeps_the_end() {
        let mut lines = Lines::new(Cursor::new(b"a\n\nb\r\nlast".to_vec()));
        assert_eq!(all(&mut lines), vec![line(b"a\n"), line(b"\n"), line(b"b\r\n"), line(b"last")]);
    }

    #[test]
    fn a_line_split_by_waits_comes_whole() {
        let mut lines = Lines::new(Stutter::of(io::ErrorKind::WouldBlock, &[b"da", b"ta: 1\n\nda", b"ta: 2\n"]));
        assert_eq!(all(&mut lines), vec![line(b"data: 1\n"), line(b"\n"), line(b"data: 2\n")]);
    }

    #[test]
    fn what_has_been_given_does_not_stay_in_memory() {
        let mut sent = Vec::new();
        for _ in 0..50_000 {
            sent.extend_from_slice(b"data: 1234567890\n");
        }
        let mut lines = Lines::new(Cursor::new(sent));
        let mut most = 0;
        while let Ok(Next::Line(_)) = lines.next_line() {
            most = most.max(lines.held.len());
        }
        assert!(most < 3 * 16_384, "{most} bytes held at once");
    }

    #[test]
    fn a_long_line_comes_as_one_line() {
        // The event that ends a stream is the biggest one, and it is the one that says how the answer ended: read in pieces, it is no event at all.
        let event = format!("data: {{\"type\": \"response.completed\", \"answer\": \"{}\"}}\n", "x".repeat(70_000));
        let mut lines = Lines::new(Cursor::new(event.as_bytes().to_vec()));
        assert_eq!(all(&mut lines), vec![line(event.as_bytes())]);
    }

    #[test]
    fn a_line_past_the_cap_is_pieces_and_not_an_event() {
        let mut sent = vec![b'x'; Lines::<Cursor<Vec<u8>>>::LIMIT + 3];
        sent.push(b'\n');
        let mut lines = Lines::new(Cursor::new(sent));
        let got = all(&mut lines);
        assert_eq!(got.len(), 2);
        assert_eq!(got[0], Next::PastCap(vec![b'x'; Lines::<Cursor<Vec<u8>>>::LIMIT]));
        assert_eq!(got[1], Next::PastCap(b"xxx\n".to_vec()));
    }

    #[test]
    fn a_long_line_is_searched_once_and_not_again_on_every_read() {
        // Searched again from its start on every read, a line that comes in n reads costs n times its length: a megabyte in reads
        // of 16 KB was some 34 MB of looking on the relay. What has been looked at for the line's end is remembered instead.
        let event = format!("data: {}\n", "x".repeat(60_000));
        let mut lines = Lines::new(Stutter::new(io::ErrorKind::WouldBlock, event.as_bytes().chunks(5_000).map(<[u8]>::to_vec)));
        let mut patience = Patience::default();
        let mut unlooked = Vec::new();
        let got = patience.answer("the long line", || {
            let next = lines.next_line();
            if next.is_err() {
                unlooked.push(lines.held.len() - lines.from - lines.looked);
            }
            next
        });
        assert_eq!(got.unwrap(), line(event.as_bytes()));
        assert!(unlooked.len() > 10, "the line came in {} reads", unlooked.len());
        assert!(unlooked.iter().all(|bytes| *bytes == 0), "bytes held but not looked at, read by read: {unlooked:?}");
    }

    #[test]
    fn what_was_searched_is_not_searched_again() {
        // A line end planted in bytes already looked at is not found: the search goes on from where it stopped, not from the start.
        let mut lines = Lines::new(Stutter::of(io::ErrorKind::WouldBlock, &[b"abc", b"def\n"]));
        assert_eq!(lines.next_line().unwrap_err().kind(), io::ErrorKind::WouldBlock, "the source waits before its first piece");
        assert_eq!(
            lines.next_line().unwrap_err().kind(),
            io::ErrorKind::WouldBlock,
            "abc is in and searched; the source waits again"
        );
        lines.held[lines.from + 1] = b'\n';
        assert_eq!(lines.next_line().unwrap(), line(b"a\ncdef\n"));
    }

    #[test]
    fn the_search_starts_again_at_each_line_and_counts_from_where_the_line_starts() {
        // A line given away takes what was searched of it with it, and a read moves what is kept to the front: the next line is
        // searched from its own first byte, wherever that now stands.
        let pieces: &[&[u8]] = &[b"aaa", b"a\nbb", b"b\nc", b"cc", b"c\n"];
        let mut lines = Lines::new(Stutter::of(io::ErrorKind::WouldBlock, pieces));
        assert_eq!(all(&mut lines), vec![line(b"aaaa\n"), line(b"bbb\n"), line(b"cccc\n")]);
    }

    #[test]
    fn a_long_line_split_by_reads_comes_whole() {
        // A line is one event: part of one, while the rest is still on the way, is not an event.
        let event = "data: {\"answer\": \"".to_string() + &"x".repeat(60_000) + "}\n";
        // Pieces of one read each, and pieces longer than a read, whose rest comes with the next one.
        for size in [Lines::<Cursor<Vec<u8>>>::READ, 20_000] {
            let parts = event.as_bytes().chunks(size).map(<[u8]>::to_vec);
            let mut lines = Lines::new(Stutter::new(io::ErrorKind::WouldBlock, parts));
            assert_eq!(all(&mut lines), vec![line(event.as_bytes())], "pieces of {size} bytes");
        }
    }
}
