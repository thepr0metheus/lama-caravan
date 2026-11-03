//! The client's side of a request: everything written to it goes through here.

use crate::clock::Clock;
use crate::stop::Ending;
use rules::{Keepalive, Told};
use serde_json::Value;
use std::io::Write;
use std::net::TcpStream;
use std::sync::Arc;
use std::time::Duration;
use wire::{HttpDate, Peer, Reply};

/// The socket to the client, and what is known of it. A failed write is the only direct word a request gets that its client is
/// gone, so every write ends the same way: `Ending::ClientGone`, never an upstream's blame.
pub struct ClientSide {
    peer: Peer,
    clock: Arc<dyn Clock>,
    head_sent: bool,
    last_write: f64,
    inside_event: bool,
}

impl ClientSide {
    /// How long a client that does not read holds a write up.
    const WRITE_LIMIT: Duration = Duration::from_secs(600);
    /// The name in the `Server` field: who answered is worth seeing in a client's log.
    const SERVER: &'static str = "caravan-proxy";

    /// The client on `stream`.
    pub fn new(stream: TcpStream, clock: Arc<dyn Clock>) -> Self {
        // Each token goes out when it comes: a lost setting costs milliseconds, not the answer, and has nobody to tell.
        drop(stream.set_nodelay(true));
        drop(stream.set_write_timeout(Some(Self::WRITE_LIMIT)));
        let last_write = clock.epoch();
        Self { peer: Peer::new(stream), clock, head_sent: false, last_write, inside_event: false }
    }

    /// Whether the client has left: the socket read again with nothing to read.
    pub fn has_left(&self) -> bool {
        self.peer.has_left()
    }

    /// Whether the status has gone out: after it, the only way to tell the client anything is an event in the stream.
    pub fn head_sent(&self) -> bool {
        self.head_sent
    }

    /// Seconds since the client last got anything.
    pub fn idle_seconds(&self) -> f64 {
        self.clock.epoch() - self.last_write
    }

    /// A head with the fields every reply of this process carries.
    pub fn reply(&self, status: u16) -> Reply {
        Self::stamped(Reply::new(status), self.clock.epoch())
    }

    /// A relayed status under the upstream's own words.
    pub fn reply_with_reason(&self, status: u16, reason: &str) -> Reply {
        Self::stamped(Reply::with_reason(status, reason), self.clock.epoch())
    }

    fn stamped(reply: Reply, now: f64) -> Reply {
        reply.field("Server", Self::SERVER).field("Date", HttpDate::format(now as u64))
    }

    /// Sends a head.
    pub fn send_head(&mut self, reply: &Reply) -> Result<(), Ending> {
        self.head_sent = true;
        self.send(&reply.head())
    }

    /// Opens an event stream, before anything else is known: a client's read timeout does not wait for a queue.
    pub fn open_stream(&mut self) -> Result<(), Ending> {
        let reply = self
            .reply(200)
            .field("Content-Type", "text/event-stream; charset=utf-8")
            .field("Cache-Control", "no-cache")
            .field("X-Accel-Buffering", "no")
            .field("Connection", "close");
        self.send_head(&reply)
    }

    /// Writes body bytes, and remembers whether they left an event open.
    pub fn write(&mut self, bytes: &[u8]) -> Result<(), Ending> {
        self.send(bytes)?;
        self.inside_event = !(bytes == b"\n" || bytes == b"\r\n" || bytes.ends_with(b"\n\n"));
        Ok(())
    }

    fn send(&mut self, bytes: &[u8]) -> Result<(), Ending> {
        let mut socket = self.peer.stream();
        if socket.write_all(bytes).is_err() {
            return Err(Ending::ClientGone);
        }
        self.last_write = self.clock.epoch();
        Ok(())
    }

    /// One complete reply: status, type, length and `Connection: close`, with the failure's own fields beside them and the
    /// request's id, so that a client's log and the journal can be matched.
    pub fn send_told(&mut self, told: &Told, request_id: &str) -> Result<(), Ending> {
        let mut reply = self
            .reply(told.status)
            .field("Content-Type", "application/json")
            .field("Content-Length", told.body.len().to_string())
            .field("Connection", "close");
        for (name, value) in &told.headers {
            reply = reply.field(name, value.as_bytes());
        }
        reply = reply.field("X-Request-Id", request_id);
        self.send_head(&reply)?;
        self.write(&told.body)
    }

    /// One complete answer of this process's own: `200`, its JSON, and `Connection: close`.
    pub fn send_answer(&mut self, answer: &Value) -> Result<(), Ending> {
        let body = answer.to_string().into_bytes();
        let reply = self
            .reply(200)
            .field("Content-Type", "application/json")
            .field("Content-Length", body.len().to_string())
            .field("Connection", "close");
        self.send_head(&reply)?;
        self.write(&body)
    }

    /// A failure inside a stream that is open: an error event, then `[DONE]`. Without the terminator a client waits out its
    /// own read timeout instead of failing. A failure between an event's line and its blank line ends that event first: a parser
    /// would read the two as one event otherwise, the model's text and the error's.
    pub fn send_stream_error(&mut self, payload: &Value) -> Result<(), Ending> {
        let lead = if self.inside_event { "\n" } else { "" };
        self.write(format!("{lead}event: error\ndata: {payload}\n\ndata: [DONE]\n\n").as_bytes())
    }

    /// An event that keeps a waiting stream alive.
    pub fn keepalive(&mut self, model: &str) -> Result<(), Ending> {
        let bytes = Keepalive::bytes(model, self.clock.epoch() as i64);
        self.write(&bytes)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::clock::SystemClock;
    use serde_json::json;
    use std::io::Read;
    use std::net::{Shutdown, TcpListener};

    fn pair() -> (TcpStream, ClientSide) {
        let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
        let near = TcpStream::connect(listener.local_addr().unwrap()).unwrap();
        let (far, _) = listener.accept().unwrap();
        (near, ClientSide::new(far, Arc::new(SystemClock::new())))
    }

    fn read_to_end(mut near: TcpStream, client: ClientSide) -> String {
        drop(client);
        let mut got = String::new();
        near.read_to_string(&mut got).unwrap();
        got
    }

    #[test]
    fn an_error_between_an_event_s_line_and_its_blank_line_ends_that_event_first() {
        let (near, mut client) = pair();
        client.write(b"data: 1\n").unwrap();
        client.send_stream_error(&json!({"e": 1})).unwrap();
        assert_eq!(read_to_end(near, client), "data: 1\n\nevent: error\ndata: {\"e\":1}\n\ndata: [DONE]\n\n");
    }

    #[test]
    fn an_error_after_a_finished_event_adds_no_blank_line() {
        for sent in [&b"data: 1\n\n"[..], &b"\n"[..], &b"\r\n"[..]] {
            let (near, mut client) = pair();
            client.write(sent).unwrap();
            client.send_stream_error(&json!({"e": 1})).unwrap();
            let got = read_to_end(near, client);
            let after = &got[sent.len()..];
            assert!(after.starts_with("event: error"), "{got:?}");
        }
    }

    #[test]
    fn an_error_at_the_very_start_stands_alone() {
        let (near, mut client) = pair();
        client.send_stream_error(&json!({})).unwrap();
        assert!(read_to_end(near, client).starts_with("event: error"));
    }

    #[test]
    fn an_error_right_after_the_head_stands_alone() {
        let (near, mut client) = pair();
        client.open_stream().unwrap();
        client.send_stream_error(&json!({})).unwrap();
        assert!(read_to_end(near, client).contains("\r\n\r\nevent: error"));
    }

    #[test]
    fn a_stream_s_head_and_a_failure_s_head_say_what_a_client_needs() {
        let (near, mut client) = pair();
        client.open_stream().unwrap();
        assert!(client.head_sent());
        let got = read_to_end(near, client);
        for line in [
            "HTTP/1.1 200 OK\r\n",
            "Content-Type: text/event-stream; charset=utf-8\r\n",
            "X-Accel-Buffering: no\r\n",
            "Connection: close\r\n",
        ] {
            assert!(got.contains(line), "{line:?} in {got:?}");
        }
        let (near, mut client) = pair();
        let told = Told { status: 503, body: b"{}".to_vec(), headers: vec![("Retry-After", "30".to_string())] };
        client.send_told(&told, "the-id").unwrap();
        let got = read_to_end(near, client);
        for line in [
            "HTTP/1.1 503 Service Unavailable\r\n",
            "Content-Length: 2\r\n",
            "Retry-After: 30\r\n",
            "X-Request-Id: the-id\r\n",
            "Connection: close\r\n",
        ] {
            assert!(got.contains(line), "{line:?} in {got:?}");
        }
        assert!(got.ends_with("\r\n\r\n{}"));
    }

    #[test]
    fn a_client_that_left_is_seen_and_a_write_to_it_says_so() {
        let (near, mut client) = pair();
        assert!(!client.has_left());
        near.shutdown(Shutdown::Both).unwrap();
        drop(near);
        std::thread::sleep(Duration::from_millis(50));
        assert!(client.has_left());
        let mut last = Ok(());
        for _ in 0..100 {
            last = client.write(&[b'x'; 4096]);
            if last.is_err() {
                break;
            }
            std::thread::sleep(Duration::from_millis(10));
        }
        assert!(matches!(last, Err(Ending::ClientGone)), "{last:?}");
    }
}
