//! How a connection the caravan serves ends.

use std::io::{self, Read};
use std::net::{Shutdown, TcpStream};
use std::time::Duration;

/// The end of a connection whose request may not have been read whole: a refusal before the body, a handler that needs none. A socket closed with bytes it never read is
/// reset, and the reset takes with it the answer still on its way: a client that was told why sees a dropped connection.
pub struct Closing;

impl Closing {
    /// How long it waits for the next bytes of a request it did not read.
    const LINGER: Duration = Duration::from_secs(2);
    /// How much of such a request it reads and throws away.
    const MOST: u64 = 64 << 20;

    /// This side says it is done, and what still comes is read and thrown away until the client closes, falls silent, or passes the limit. Any of those ends it.
    pub fn of(stream: &TcpStream) {
        // A socket that cannot be told either has nobody on it or cannot wait: closing is all that is left.
        if stream.shutdown(Shutdown::Write).is_err() || stream.set_read_timeout(Some(Self::LINGER)).is_err() {
            return;
        }
        drop(io::copy(&mut stream.take(Self::MOST), &mut io::sink()));
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;
    use std::net::TcpListener;

    /// The server has read only the head when the rest of the request arrives; it answers and ends the connection.
    fn answered_over_an_unread_body(end: fn(&TcpStream)) -> io::Result<Vec<u8>> {
        let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
        let mut near = TcpStream::connect(listener.local_addr().unwrap()).unwrap();
        let server = std::thread::spawn(move || {
            let (mut far, _) = listener.accept().unwrap();
            let mut head = [0u8; 4];
            far.read_exact(&mut head).unwrap();
            // The body lies unread in the socket from here on.
            while far.peek(&mut [0u8; 8]).unwrap() < 8 {
                std::thread::yield_now();
            }
            far.write_all(b"the answer").unwrap();
            end(&far);
        });
        near.write_all(b"head").unwrap();
        near.write_all(b"the body").unwrap();
        server.join().unwrap();
        let mut answer = Vec::new();
        near.read_to_end(&mut answer)?;
        Ok(answer)
    }

    #[test]
    fn an_answer_over_an_unread_body_reaches_the_client() {
        assert_eq!(answered_over_an_unread_body(Closing::of).unwrap(), b"the answer");
    }

    #[test]
    fn a_socket_just_closed_over_an_unread_body_loses_the_answer() {
        // What `Closing` is there for: if the system stopped resetting such a socket, it would have no reason left.
        let lost = answered_over_an_unread_body(|_| {});
        assert_eq!(lost.unwrap_err().kind(), io::ErrorKind::ConnectionReset);
    }

    #[test]
    fn a_client_that_stays_silent_is_told_and_not_waited_for_past_the_linger() {
        let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
        let near = TcpStream::connect(listener.local_addr().unwrap()).unwrap();
        let (far, _) = listener.accept().unwrap();
        Closing::of(&far);
        let mut seen = [0u8; 1];
        assert_eq!((&near).read(&mut seen).unwrap(), 0);
    }
}
