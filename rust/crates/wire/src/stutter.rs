//! What the readers of this crate are tested against: a source whose reads wait their time, and the patience a test asks a
//! reader again with. One of each, for every test of the crate.
//!
//! A socket whose read waited its time answers with `WouldBlock` or `TimedOut`; the readers here keep what has come and are asked
//! again. A test that asks again must also stop asking. On 2026-11-04 a source of the tests that waited for ever after its last
//! piece met a loop that asked again at once on every wait: two tests spun two cores of a Mac for three days, and nothing failed.

use std::collections::VecDeque;
use std::fmt;
use std::io::{self, Read};

/// Hands out its pieces with a wait before every read, as a socket whose reads time out between the pieces of an answer. A piece
/// longer than the read leaves its rest for the next read, and after the last piece the source has ended: it reads 0 from then on.
pub(crate) struct Stutter {
    pieces: VecDeque<Vec<u8>>,
    wait: io::ErrorKind,
    waited: bool,
}

impl Stutter {
    /// `pieces`, each read's wait said as `wait`: a socket's timeout reads as `WouldBlock` on Linux and macOS, as `TimedOut`
    /// elsewhere, and the readers take either.
    pub(crate) fn new(wait: io::ErrorKind, pieces: impl IntoIterator<Item = Vec<u8>>) -> Self {
        let pieces: VecDeque<Vec<u8>> = pieces.into_iter().collect();
        // A read of no bytes is how a source says it has ended, so an empty piece would end the stream in its middle.
        assert!(pieces.iter().all(|piece| !piece.is_empty()), "an empty piece reads as the end of the stream");
        Self { pieces, wait, waited: false }
    }

    /// Borrowed pieces, copied.
    pub(crate) fn of(wait: io::ErrorKind, pieces: &[&[u8]]) -> Self {
        Self::new(wait, pieces.iter().map(|piece| piece.to_vec()))
    }
}

impl Read for Stutter {
    fn read(&mut self, out: &mut [u8]) -> io::Result<usize> {
        self.waited = !self.waited;
        if self.waited {
            return Err(io::Error::new(self.wait, StutterWait));
        }
        let Some(piece) = self.pieces.front_mut() else {
            return Ok(0);
        };
        let count = piece.len().min(out.len());
        out[..count].copy_from_slice(&piece[..count]);
        piece.drain(..count);
        if piece.is_empty() {
            self.pieces.pop_front();
        }
        Ok(count)
    }
}

/// What a `Stutter`'s wait carries: `Patience` takes the source's own waits for waits and nothing else, so a failure of the reader
/// under test is never asked again as if it were one.
#[derive(Debug)]
struct StutterWait;

impl fmt::Display for StutterWait {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("waited")
    }
}

impl std::error::Error for StutterWait {}

/// How a test asks a reader again after a wait, and when it stops: a run of waits with no answer is a source or a reader that no
/// longer moves, and the test fails saying so instead of spinning for ever.
#[derive(Default)]
pub(crate) struct Patience {
    waits: usize,
}

impl Patience {
    /// The most waits in a row a test lets go by. A `Stutter` waits once before each read, so a reader that needs a hundred reads for
    /// one answer sees a hundred in a row; ten thousand is a loop, not a slow source. Counted, not timed: a test reads no clock.
    const IN_A_ROW: usize = 10_000;

    /// How many of the source's waits it has let go by.
    pub(crate) fn waits(&self) -> usize {
        self.waits
    }

    /// `step`'s answer, asked again after each of a `Stutter`'s waits; any other failure is the answer too. Fails the test, naming
    /// `asked`, after `IN_A_ROW` waits in a row.
    pub(crate) fn answer<T>(&mut self, asked: &str, mut step: impl FnMut() -> io::Result<T>) -> io::Result<T> {
        for _ in 0..Self::IN_A_ROW {
            match step() {
                Err(error) if Self::is_a_wait(&error) => self.waits += 1,
                answer => return answer,
            }
        }
        panic!("{asked}: {} waits in a row and no answer: the source or the reader no longer moves", Self::IN_A_ROW)
    }

    fn is_a_wait(error: &io::Error) -> bool {
        error.get_ref().is_some_and(|inner| inner.is::<StutterWait>())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// One read's outcome: the bytes it gave (none at the end), or the kind of its failure.
    type Outcome = Result<Vec<u8>, io::ErrorKind>;

    /// What `count` reads of `room` bytes each give.
    fn reads(source: &mut Stutter, room: usize, count: usize) -> Vec<Outcome> {
        (0..count)
            .map(|_| {
                let mut out = vec![0u8; room];
                source.read(&mut out).map(|got| out[..got].to_vec()).map_err(|error| error.kind())
            })
            .collect()
    }

    fn gave(bytes: &[u8]) -> Outcome {
        Ok(bytes.to_vec())
    }

    #[test]
    fn the_source_waits_before_each_read_and_ends_after_its_last_piece() {
        // The source of 2026-11-04 answered every read after its last piece with a wait, so the stream it stood for never ended.
        let mut source = Stutter::of(io::ErrorKind::WouldBlock, &[b"ab", b"c"]);
        let wait = || Err(io::ErrorKind::WouldBlock);
        let expected = vec![wait(), gave(b"ab"), wait(), gave(b"c"), wait(), gave(b""), wait(), gave(b"")];
        assert_eq!(reads(&mut source, 8, 8), expected);
    }

    #[test]
    fn a_piece_longer_than_the_read_leaves_its_rest_for_the_next_one() {
        // The same source took a whole piece out on a read that had room for part of it, and the rest was gone.
        let mut source = Stutter::of(io::ErrorKind::TimedOut, &[b"abcdef"]);
        let wait = || Err(io::ErrorKind::TimedOut);
        assert_eq!(reads(&mut source, 4, 6), vec![wait(), gave(b"abcd"), wait(), gave(b"ef"), wait(), gave(b"")]);
    }

    #[test]
    fn patience_asks_again_after_each_wait_and_counts_them() {
        let mut source = Stutter::of(io::ErrorKind::WouldBlock, &[b"ab"]);
        let mut patience = Patience::default();
        let mut out = [0u8; 8];
        assert_eq!(patience.answer("a read", || source.read(&mut out)).unwrap(), 2);
        assert_eq!(patience.answer("a read", || source.read(&mut out)).unwrap(), 0);
        assert_eq!(patience.waits(), 2);
    }

    #[test]
    #[should_panic(expected = "a read: 10000 waits in a row and no answer: the source or the reader no longer moves")]
    fn a_source_that_waits_for_ever_fails_the_test_and_says_what_was_asked() {
        let mut patience = Patience::default();
        let waits_for_ever = || -> io::Result<usize> { Err(io::Error::new(io::ErrorKind::WouldBlock, StutterWait)) };
        let _never = patience.answer("a read", waits_for_ever);
    }

    #[test]
    fn a_failure_that_is_not_the_source_s_wait_is_the_answer() {
        // A reader that passed a wait of its own up, or turned the source's wait into another failure, is not asked again.
        let mut patience = Patience::default();
        let own =
            patience.answer("a read", || -> io::Result<usize> { Err(io::Error::new(io::ErrorKind::WouldBlock, "its own")) });
        assert_eq!(own.unwrap_err().to_string(), "its own");
        assert_eq!(patience.waits(), 0);
    }
}
