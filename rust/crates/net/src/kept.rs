//! Connections to providers kept open between requests.
//!
//! To a provider a new connection is a TCP and a TLS handshake every time: about 52 ms from the controller's machine to OpenAI and 91–122 ms
//! from the NAS, measured 2026-10-07. A cell is not kept: its connection costs a fraction of a millisecond, and the proxy cancels a cell's
//! generation by tearing its socket down.

use crate::stream::Stream;
use std::collections::BTreeMap;
use std::sync::{Mutex, PoisonError};

/// Where a connection goes.
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
pub struct Target {
    /// Over TLS or not.
    pub tls: bool,
    /// The host.
    pub host: String,
    /// The port.
    pub port: u16,
}

/// The idle connections, newest last, each with when it went idle.
#[derive(Debug, Default)]
pub struct KeptConnections {
    idle: Mutex<BTreeMap<Target, Vec<(Stream, f64)>>>,
}

impl KeptConnections {
    /// A connection idle longer than this is dropped instead of handed out.
    const IDLE_SEC: f64 = 60.0;
    /// The most kept for one place.
    const PER_HOST: usize = 8;

    /// A live connection to `target`, when one is kept. One that went past its time or that its provider has closed is dropped on the way.
    pub fn take(&self, target: &Target, now: f64) -> Option<Stream> {
        let mut idle = self.idle.lock().unwrap_or_else(PoisonError::into_inner);
        Self::sweep(&mut idle, now);
        let kept = idle.get_mut(target)?;
        let mut found = None;
        while let Some((stream, _)) = kept.pop() {
            if stream.is_quiet() {
                found = Some(stream);
                break;
            }
        }
        if kept.is_empty() {
            idle.remove(target);
        }
        found
    }

    /// Keeps `stream` for the next request to the same place.
    pub fn give_back(&self, target: Target, stream: Stream, now: f64) {
        let mut idle = self.idle.lock().unwrap_or_else(PoisonError::into_inner);
        Self::sweep(&mut idle, now);
        let kept = idle.entry(target).or_default();
        kept.push((stream, now));
        if kept.len() > Self::PER_HOST {
            kept.remove(0);
        }
    }

    fn sweep(idle: &mut BTreeMap<Target, Vec<(Stream, f64)>>, now: f64) {
        for kept in idle.values_mut() {
            kept.retain(|(_, since)| now - since <= Self::IDLE_SEC);
        }
        idle.retain(|_, kept| !kept.is_empty());
    }

    /// How many sit idle.
    pub fn idle_count(&self) -> usize {
        self.idle.lock().unwrap_or_else(PoisonError::into_inner).values().map(Vec::len).sum()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::net::{TcpListener, TcpStream};

    fn pair() -> (TcpStream, Stream) {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let near = TcpStream::connect(listener.local_addr().unwrap()).unwrap();
        let (far, _) = listener.accept().unwrap();
        (far, Stream::Plain(near))
    }

    fn target(host: &str) -> Target {
        Target { tls: true, host: host.to_string(), port: 443 }
    }

    #[test]
    fn a_kept_connection_goes_to_its_own_place_and_only_there() {
        let kept = KeptConnections::default();
        let (_far, stream) = pair();
        kept.give_back(target("a"), stream, 100.0);
        assert!(kept.take(&target("b"), 100.0).is_none());
        assert!(kept.take(&Target { tls: false, ..target("a") }, 100.0).is_none());
        assert!(kept.take(&target("a"), 100.0).is_some());
        assert_eq!(kept.idle_count(), 0);
    }

    #[test]
    fn one_past_its_time_is_dropped_and_one_at_it_is_not() {
        let kept = KeptConnections::default();
        let (_far, stream) = pair();
        kept.give_back(target("a"), stream, 100.0);
        assert!(kept.take(&target("a"), 160.0).is_some(), "sixty seconds exactly");
        let (_far, stream) = pair();
        kept.give_back(target("a"), stream, 100.0);
        assert!(kept.take(&target("a"), 160.5).is_none());
        assert_eq!(kept.idle_count(), 0);
    }

    #[test]
    fn one_its_provider_closed_or_wrote_on_is_dropped() {
        let kept = KeptConnections::default();
        let (far, stream) = pair();
        kept.give_back(target("a"), stream, 100.0);
        drop(far);
        std::thread::sleep(std::time::Duration::from_millis(20));
        assert!(kept.take(&target("a"), 100.0).is_none());
        let (mut far, stream) = pair();
        kept.give_back(target("a"), stream, 100.0);
        std::io::Write::write_all(&mut far, b"x").unwrap();
        std::thread::sleep(std::time::Duration::from_millis(20));
        assert!(kept.take(&target("a"), 100.0).is_none());
    }

    #[test]
    fn the_newest_goes_first_and_a_place_keeps_eight_at_most() {
        let kept = KeptConnections::default();
        let mut far_ends = Vec::new();
        // A connection is known by both its ends: the system may give one local port to two connections with different far ends, and did (2026-11-03, CI).
        let ends = |socket: &std::net::TcpStream| (socket.local_addr().unwrap(), socket.peer_addr().unwrap());
        let mut oldest = None;
        for at in 0..9 {
            let (far, stream) = pair();
            let Stream::Plain(ref socket) = stream else { panic!("plain") };
            if at == 0 {
                oldest = Some(ends(socket));
            }
            far_ends.push(far);
            kept.give_back(target("a"), stream, 100.0);
        }
        assert_eq!(kept.idle_count(), 8);
        let mut taken = Vec::new();
        while let Some(Stream::Plain(socket)) = kept.take(&target("a"), 100.0) {
            taken.push(ends(&socket));
        }
        assert_eq!(taken.len(), 8);
        assert!(!taken.contains(&oldest.unwrap()), "the oldest went first");
        assert!(taken.windows(2).all(|pair| pair[0] != pair[1]));
    }
}
