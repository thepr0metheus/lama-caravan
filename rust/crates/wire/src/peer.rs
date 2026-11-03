//! The other end of a connection.

use std::io;
use std::net::{IpAddr, TcpStream};

/// A connected socket, asked what only a socket can say.
#[derive(Debug)]
pub struct Peer {
    stream: TcpStream,
}

impl Peer {
    /// The other end of `stream`.
    pub fn new(stream: TcpStream) -> Self {
        Self { stream }
    }

    /// Whether the other end has left, asked without taking a byte of what it sent. After a request's
    /// body the socket reads again only on its closing, because no client of the caravan pipelines.
    /// A socket that cannot be asked counts as gone: nothing can be told to it either.
    pub fn has_left(&self) -> bool {
        if self.stream.set_nonblocking(true).is_err() {
            return true;
        }
        let mut probe = [0u8; 1];
        let answer = self.stream.peek(&mut probe);
        let restored = self.stream.set_nonblocking(false).is_ok();
        match answer {
            Ok(0) => true,
            Ok(_) => !restored,
            Err(error) if error.kind() == io::ErrorKind::WouldBlock => !restored,
            Err(_) => true,
        }
    }

    /// The other end's address, as text; `None` when the socket cannot say.
    pub fn address(&self) -> Option<IpAddr> {
        self.stream.peer_addr().ok().map(|address| address.ip())
    }

    /// The socket.
    pub fn stream(&self) -> &TcpStream {
        &self.stream
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;
    use std::net::{Shutdown, TcpListener};

    fn pair() -> (TcpStream, Peer) {
        let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
        let near = TcpStream::connect(listener.local_addr().unwrap()).unwrap();
        let (far, _) = listener.accept().unwrap();
        (near, Peer::new(far))
    }

    #[test]
    fn a_silent_client_is_still_there() {
        let (_near, peer) = pair();
        assert!(!peer.has_left());
        assert_eq!(peer.address().unwrap().to_string(), "127.0.0.1");
    }

    #[test]
    fn a_client_with_something_unread_is_still_there_and_keeps_it() {
        let (mut near, peer) = pair();
        near.write_all(b"x").unwrap();
        std::thread::sleep(std::time::Duration::from_millis(50));
        assert!(!peer.has_left());
        let mut kept = [0u8; 1];
        assert_eq!(peer.stream().peek(&mut kept).unwrap(), 1);
    }

    #[test]
    fn a_closed_client_has_left() {
        let (near, peer) = pair();
        near.shutdown(Shutdown::Both).unwrap();
        drop(near);
        std::thread::sleep(std::time::Duration::from_millis(50));
        assert!(peer.has_left());
    }
}
