//! The entry's socket: a thread for each connection.

use crate::connection::Connection;
use crate::drain::Drain;
use crate::log::Log;
use crate::proxy::Proxy;
use net::Closing;
use std::io;
use std::net::{IpAddr, Ipv4Addr, SocketAddr, TcpListener, TcpStream};
use std::process::ExitCode;
use std::sync::Arc;
use std::time::Duration;

/// The bound socket.
pub struct Listener {
    proxy: Arc<Proxy>,
    socket: TcpListener,
}

impl Listener {
    /// Room for one connection's thread: the deepest it goes is `serde_json`, which stops at 128 levels on its own.
    const STACK: usize = 1024 * 1024;
    /// How long it rests after `accept` fails, usually for want of file descriptors, before it tries again.
    const REST: Duration = Duration::from_millis(100);
    /// How long a new version waits for the old one to let the port go, and how often it asks.
    const BIND_PATIENCE: f64 = 15.0;
    const BIND_TURN: Duration = Duration::from_millis(50);
    /// How often a version on its way out counts what is left.
    const DRAIN_TURN: Duration = Duration::from_millis(200);

    /// Binds the entry's address, or says why it cannot. A port in use is waited for: it is the old version's until it sees this one.
    pub fn bind(proxy: Arc<Proxy>) -> Result<Self, String> {
        let address = format!("{}:{}", proxy.config.host, proxy.config.port);
        let began = proxy.clock.monotonic();
        loop {
            match TcpListener::bind(&address) {
                Ok(socket) => {
                    Log::line(&format!("caravan-proxy: entry listening on {address}"));
                    return Ok(Self { proxy, socket });
                }
                Err(error)
                    if error.kind() == io::ErrorKind::AddrInUse && proxy.clock.monotonic() - began < Self::BIND_PATIENCE =>
                {
                    std::thread::sleep(Self::BIND_TURN);
                }
                Err(error) => return Err(format!("cannot bind {address}: {error}")),
            }
        }
    }

    /// Serves until this process is to leave and the last request here has its answer.
    pub fn serve(self) -> ExitCode {
        self.start_watching();
        let drain = Arc::clone(&self.proxy.drain);
        while !drain.is_on() {
            match self.socket.accept() {
                Ok((stream, peer)) => self.start_connection(stream, peer),
                Err(error) => {
                    Log::line(&format!("caravan-proxy: accept failed: {error}"));
                    std::thread::sleep(Self::REST);
                }
            }
        }
        self.wait_for_the_last();
        ExitCode::SUCCESS
    }

    fn start_connection(&self, stream: TcpStream, peer: SocketAddr) {
        let proxy = Arc::clone(&self.proxy);
        let open = proxy.drain.connection();
        let thread = std::thread::Builder::new().name("connection".into()).stack_size(Self::STACK).spawn(move || {
            let _open = open;
            let closing = stream.try_clone();
            Connection::new(&proxy, stream, peer).serve();
            // Whichever way it went: a refusal does not wait for the body it refuses.
            if let Ok(closing) = closing {
                Closing::of(&closing);
            }
        });
        if let Err(error) = thread {
            Log::line(&format!("caravan-proxy: no thread for a connection: {error}"));
        }
    }

    /// The look-out: when this process is to leave, the accept below it is woken by a connection of its own, which reads nothing and ends.
    fn start_watching(&self) {
        let drain = Arc::clone(&self.proxy.drain);
        let wake = self.socket.local_addr().ok().map(Self::reachable);
        let watcher = std::thread::Builder::new().name("drain-watch".into()).spawn(move || {
            let why = loop {
                if let Some(why) = drain.why_leave() {
                    break why;
                }
                std::thread::sleep(Drain::TURN);
            };
            Log::line(&format!("caravan-proxy: {why}: the port is let go, the running requests finish"));
            drain.begin();
            if let Some(address) = wake {
                // A connection that cannot be made means nothing is listening: `accept` then ends by itself, or the next client wakes it.
                drop(TcpStream::connect_timeout(&address, Duration::from_secs(1)));
            }
        });
        if let Err(error) = watcher {
            Log::line(&format!("caravan-proxy: no thread to watch for its way out: {error}"));
        }
    }

    /// The address this process reaches its own socket at.
    fn reachable(bound: SocketAddr) -> SocketAddr {
        if bound.ip().is_unspecified() { SocketAddr::new(IpAddr::V4(Ipv4Addr::LOCALHOST), bound.port()) } else { bound }
    }

    /// Lets the port go and waits for the requests still here.
    fn wait_for_the_last(self) {
        let Self { proxy, socket } = self;
        drop(socket);
        let began = proxy.clock.monotonic();
        while proxy.drain.open() > 0 && proxy.clock.monotonic() - began < Drain::LONGEST_SECONDS {
            std::thread::sleep(Self::DRAIN_TURN);
        }
        Log::line(&format!("caravan-proxy: this version ends, {} connections open", proxy.drain.open()));
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::net::{IpAddr, Ipv6Addr};

    #[test]
    fn it_reaches_itself_where_it_listens() {
        let any = SocketAddr::new(IpAddr::V4(Ipv4Addr::UNSPECIFIED), 7);
        assert_eq!(Listener::reachable(any), SocketAddr::new(IpAddr::V4(Ipv4Addr::LOCALHOST), 7));
        let any_six = SocketAddr::new(IpAddr::V6(Ipv6Addr::UNSPECIFIED), 7);
        assert_eq!(Listener::reachable(any_six), SocketAddr::new(IpAddr::V4(Ipv4Addr::LOCALHOST), 7));
        let bound = SocketAddr::new(IpAddr::V4(Ipv4Addr::LOCALHOST), 9);
        assert_eq!(Listener::reachable(bound), bound);
    }
}
