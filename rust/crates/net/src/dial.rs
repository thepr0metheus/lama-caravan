//! A connection opened to a name: its addresses in turn, the first that answers.
//!
//! A name often has more than one: `localhost` is `::1` before `127.0.0.1` on Linux, and a provider's name has IPv6 addresses a home with
//! no IPv6 route cannot reach. Taking the first alone refuses a provider that answers on the second.

use std::io;
use std::net::{SocketAddr, TcpStream, ToSocketAddrs};
use std::time::Duration;

/// How long an address may take.
#[derive(Debug, Clone, Copy)]
pub struct Dial {
    /// How long one wait takes before the caller looks around.
    pub turn: Duration,
    /// How long the last address may take in all.
    pub limit: Duration,
}

impl Dial {
    /// How long an address gets while another stands behind it: one that says nothing must not spend the others' time.
    const ONE_OF_MANY: Duration = Duration::from_secs(10);

    /// A connection to `host`'s addresses. `look_around` runs each time a wait has taken its turn: it says whether to go on.
    pub fn open<E: From<io::Error>>(
        self,
        host: &str,
        port: u16,
        look_around: &mut dyn FnMut() -> Result<(), E>,
    ) -> Result<TcpStream, E> {
        let addresses: Vec<SocketAddr> = (host, port).to_socket_addrs()?.collect();
        self.first_that_answers(&addresses, look_around)
    }

    /// The first of `addresses` that answers; every one refused is the last one's error.
    fn first_that_answers<E: From<io::Error>>(
        self,
        addresses: &[SocketAddr],
        look_around: &mut dyn FnMut() -> Result<(), E>,
    ) -> Result<TcpStream, E> {
        let mut failed = io::Error::new(io::ErrorKind::NotFound, "the name has no address");
        for (at, address) in addresses.iter().enumerate() {
            let limit = if at + 1 == addresses.len() { self.limit } else { self.limit.min(Self::ONE_OF_MANY) };
            match self.one(address, limit, look_around)? {
                Ok(socket) => return Ok(socket),
                Err(error) => failed = error,
            }
        }
        Err(failed.into())
    }

    /// One address: the socket or its failure inside, and outside what `look_around` said to stop for. No clock here: a wait that comes back
    /// empty has taken its whole turn, so the turns count the time.
    fn one<E>(
        self,
        address: &SocketAddr,
        limit: Duration,
        look_around: &mut dyn FnMut() -> Result<(), E>,
    ) -> Result<io::Result<TcpStream>, E> {
        let mut spent = Duration::ZERO;
        loop {
            match TcpStream::connect_timeout(address, self.turn) {
                Ok(socket) => return Ok(Ok(socket)),
                Err(error) if error.kind() != io::ErrorKind::TimedOut => return Ok(Err(error)),
                Err(error) => {
                    spent += self.turn;
                    if spent >= limit {
                        return Ok(Err(error));
                    }
                    look_around()?;
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::net::TcpListener;

    const DIAL: Dial = Dial { turn: Duration::from_secs(1), limit: Duration::from_secs(2) };

    fn a_closed_address() -> SocketAddr {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        listener.local_addr().unwrap()
    }

    fn walk(addresses: &[SocketAddr]) -> io::Result<TcpStream> {
        DIAL.first_that_answers::<io::Error>(addresses, &mut || Ok(()))
    }

    #[test]
    fn the_first_address_that_answers_serves_whatever_stands_before_it() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let open = listener.local_addr().unwrap();
        assert_eq!(walk(&[open]).unwrap().peer_addr().unwrap(), open);
        assert_eq!(walk(&[a_closed_address(), open]).unwrap().peer_addr().unwrap(), open);
        assert_eq!(walk(&[a_closed_address(), a_closed_address(), open]).unwrap().peer_addr().unwrap(), open);
        assert_eq!(walk(&[open, a_closed_address()]).unwrap().peer_addr().unwrap(), open);
    }

    #[test]
    fn with_no_address_answering_the_last_one_s_error_is_said() {
        let error = walk(&[a_closed_address(), a_closed_address()]).unwrap_err();
        assert_eq!(error.kind(), io::ErrorKind::ConnectionRefused);
    }

    #[test]
    fn a_name_with_no_address_says_so() {
        let error = walk(&[]).unwrap_err();
        assert_eq!(error.kind(), io::ErrorKind::NotFound);
        assert_eq!(error.to_string(), "the name has no address");
    }

    #[test]
    fn a_name_is_looked_up() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        let socket = DIAL.open::<io::Error>("127.0.0.1", port, &mut || Ok(())).unwrap();
        assert_eq!(socket.peer_addr().unwrap().port(), port);
        assert!(DIAL.open::<io::Error>("no-such-name.invalid", port, &mut || Ok(())).is_err());
    }
}
