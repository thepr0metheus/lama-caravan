//! One connection, plain or over TLS, read and written the same way.

use rustls::{ClientConnection, StreamOwned};
use std::io::{self, Read, Write};
use std::net::TcpStream;
use std::time::Duration;

/// A connection to a model or a provider.
#[derive(Debug)]
pub enum Stream {
    /// A machine of the home, or a provider at an `http://` address.
    Plain(TcpStream),
    /// A provider.
    Tls(Box<StreamOwned<ClientConnection, TcpStream>>),
}

impl Stream {
    fn socket(&self) -> &TcpStream {
        match self {
            Self::Plain(socket) => socket,
            Self::Tls(stream) => stream.get_ref(),
        }
    }

    /// How long a read waits before it comes back with `WouldBlock`: the caller's turn to look around.
    pub fn set_read_timeout(&self, turn: Option<Duration>) -> io::Result<()> {
        self.socket().set_read_timeout(turn)
    }

    /// How long a write may take.
    pub fn set_write_timeout(&self, limit: Option<Duration>) -> io::Result<()> {
        self.socket().set_write_timeout(limit)
    }

    /// Closes both ways at once: a read waiting on it in another thread comes back.
    pub fn shut_down(&self) {
        // A socket already closed has nothing to shut.
        drop(self.socket().shutdown(std::net::Shutdown::Both));
    }

    /// Still open and quiet: a kept connection that turned readable was closed by its provider, with a FIN or a TLS `close_notify`.
    pub fn is_quiet(&self) -> bool {
        let socket = self.socket();
        if socket.set_nonblocking(true).is_err() {
            return false;
        }
        let mut one = [0u8; 1];
        let quiet = matches!(socket.peek(&mut one), Err(error) if error.kind() == io::ErrorKind::WouldBlock);
        socket.set_nonblocking(false).is_ok() && quiet
    }

    /// What a read over TLS comes to: an end with no `close_notify` is an end.
    fn ragged_end_is_the_end(read: io::Result<usize>) -> io::Result<usize> {
        match read {
            Err(error) if error.kind() == io::ErrorKind::UnexpectedEof => Ok(0),
            other => other,
        }
    }

    /// Whether an error of a kept connection means its provider closed it while it sat idle: the request never got an answer, so sending it
    /// again is safe. `UpstreamPool.STALE_ERRORS`.
    pub fn is_stale_error(error: &io::Error) -> bool {
        matches!(
            error.kind(),
            io::ErrorKind::BrokenPipe
                | io::ErrorKind::ConnectionReset
                | io::ErrorKind::ConnectionAborted
                | io::ErrorKind::UnexpectedEof
        )
    }
}

impl Read for Stream {
    fn read(&mut self, out: &mut [u8]) -> io::Result<usize> {
        match self {
            Self::Plain(socket) => socket.read(out),
            // A provider that closes without TLS's `close_notify` has ended what it had to say: Python's `suppress_ragged_eofs`. An answer
            // that promised more is told by its own framing.
            Self::Tls(stream) => Self::ragged_end_is_the_end(stream.read(out)),
        }
    }
}

impl Write for Stream {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        match self {
            Self::Plain(socket) => socket.write(bytes),
            Self::Tls(stream) => stream.write(bytes),
        }
    }

    fn flush(&mut self) -> io::Result<()> {
        match self {
            Self::Plain(socket) => socket.flush(),
            Self::Tls(stream) => stream.flush(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::net::TcpListener;

    const A_WHILE: Duration = Duration::from_secs(5);

    fn pair() -> (Stream, TcpStream) {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let near = TcpStream::connect(listener.local_addr().unwrap()).unwrap();
        let (far, _) = listener.accept().unwrap();
        far.set_read_timeout(Some(A_WHILE)).unwrap();
        near.set_read_timeout(Some(A_WHILE)).unwrap();
        (Stream::Plain(near), far)
    }

    #[test]
    fn what_is_written_reaches_the_other_side_and_what_it_answers_comes_back() {
        let (mut near, mut far) = pair();
        near.write_all(b"hello").unwrap();
        near.flush().unwrap();
        let mut got = [0u8; 5];
        far.read_exact(&mut got).unwrap();
        assert_eq!(&got, b"hello");
        far.write_all(b"back").unwrap();
        let mut got = [0u8; 4];
        near.read_exact(&mut got).unwrap();
        assert_eq!(&got, b"back");
    }

    #[test]
    fn a_turn_and_a_limit_are_set_on_the_socket() {
        let (near, _far) = pair();
        let (turn, limit) = (Some(Duration::from_millis(70)), Some(Duration::from_millis(90)));
        near.set_read_timeout(turn).unwrap();
        near.set_write_timeout(limit).unwrap();
        assert_eq!(near.socket().read_timeout().unwrap(), turn);
        assert_eq!(near.socket().write_timeout().unwrap(), limit);
    }

    #[test]
    fn shutting_down_ends_both_ways() {
        let (near, mut far) = pair();
        near.shut_down();
        let mut got = [0u8; 1];
        assert_eq!(far.read(&mut got).unwrap(), 0);
    }

    #[test]
    fn a_connection_is_quiet_until_its_other_side_speaks_or_closes() {
        let (near, mut far) = pair();
        assert!(near.is_quiet());
        far.write_all(b"x").unwrap();
        std::thread::sleep(Duration::from_millis(50));
        assert!(!near.is_quiet(), "bytes nobody asked for");
        let (near, far) = pair();
        drop(far);
        std::thread::sleep(Duration::from_millis(50));
        assert!(!near.is_quiet(), "a FIN");
    }

    #[test]
    fn being_quiet_leaves_the_socket_blocking() {
        let (mut near, _far) = pair();
        near.set_read_timeout(Some(Duration::from_millis(30))).unwrap();
        assert!(near.is_quiet());
        let began = std::time::Instant::now();
        let mut got = [0u8; 1];
        assert!(near.read(&mut got).is_err());
        assert!(began.elapsed() >= Duration::from_millis(20), "a read still waits its turn");
    }

    #[test]
    fn an_error_of_a_connection_its_provider_closed_is_told_from_any_other() {
        for kind in [
            io::ErrorKind::BrokenPipe,
            io::ErrorKind::ConnectionReset,
            io::ErrorKind::ConnectionAborted,
            io::ErrorKind::UnexpectedEof,
        ] {
            assert!(Stream::is_stale_error(&kind.into()), "{kind:?}");
        }
        for kind in
            [io::ErrorKind::TimedOut, io::ErrorKind::WouldBlock, io::ErrorKind::ConnectionRefused, io::ErrorKind::InvalidData]
        {
            assert!(!Stream::is_stale_error(&kind.into()), "{kind:?}");
        }
    }

    #[test]
    fn an_end_with_no_goodbye_is_an_end_and_any_other_error_stays_one() {
        assert_eq!(Stream::ragged_end_is_the_end(Ok(3)).unwrap(), 3);
        assert_eq!(Stream::ragged_end_is_the_end(Err(io::ErrorKind::UnexpectedEof.into())).unwrap(), 0);
        let other = Stream::ragged_end_is_the_end(Err(io::ErrorKind::ConnectionReset.into())).unwrap_err();
        assert_eq!(other.kind(), io::ErrorKind::ConnectionReset);
    }
}
