//! The controller's way into one of this machine's cells (`rules::CellDoor`): the request handed to the cell on the loopback as it
//! came, its head with the fleet token taken out, then every byte both ways until each side has said all it had. A plain answer, a
//! stream and a WebSocket go through alike, and the scout reads none of them.
//!
//! Since step 7 of the owner's plan (Papyrus `caravan-scout-port-lease`, 2026-11-08) a cell listens on the loopback alone: this is
//! how the controller reaches a cell's health, its `/props`, a question of the Talk tab and a live talk, all of which it asked over
//! the network before.

use crate::cells::Cells;
use rules::CellDoor;
use serde_json::{Value, json};
use std::io::{self, BufReader, Write};
use std::net::{Shutdown, SocketAddr, TcpStream};
use std::time::Duration;
use wire::RequestHead;

/// The door of this machine's cells.
pub struct Door<'cells> {
    cells: &'cells Cells,
}

impl<'cells> Door<'cells> {
    /// How long a cell gets to take the connection.
    const CONNECT: Duration = Duration::from_secs(5);
    /// The fields that stay here: the token opens the scout and not the cell, and the cell is told its own address instead.
    const KEPT_HERE: [&'static str; 2] = ["x-caravan-token", "host"];

    /// The door of `cells`.
    pub fn of(cells: &'cells Cells) -> Self {
        Self { cells }
    }

    /// Hands the request of `head`, its rest still in `reader`, to the cell it names, and passes the bytes on both ways until each
    /// side has said all it had. `Err` is the scout's own refusal, said before a byte reached a cell: a path that names no cell, no
    /// such cell, a cell that holds no port, a cell that does not take the connection.
    pub fn pass(&self, head: &RequestHead, reader: BufReader<TcpStream>, client: &TcpStream) -> Result<(), (Value, u16)> {
        let (id, path) = CellDoor::read(&head.target)
            .ok_or_else(|| Self::refusal(format!("{} names no cell: {}<cell><path>", head.target, CellDoor::PREFIX), 404))?;
        let cell = self.cells.table.find(&id).ok_or_else(|| Self::refusal(format!("no cell {id} on this machine"), 404))?;
        let port = cell
            .port()
            .and_then(|port| u16::try_from(port).ok())
            .ok_or_else(|| Self::refusal(format!("cell {id} holds no port: it does not run"), 409))?;
        let address: SocketAddr = format!("{}:{port}", CellDoor::LISTEN)
            .parse()
            .map_err(|error| Self::refusal(format!("the loopback is no address here: {error}"), 500))?;
        let unreached =
            |error: io::Error| Self::refusal(format!("cell {id} does not take connections on its port: {error}"), 502);
        let mut upstream = TcpStream::connect_timeout(&address, Self::CONNECT).map_err(unreached)?;
        // What came after the head with it is the request's too: a body's first bytes.
        let early = reader.buffer().to_vec();
        upstream.write_all(&Self::head_for_cell(head, &path, port)).map_err(unreached)?;
        upstream.write_all(&early).map_err(unreached)?;
        Self::both_ways(reader.into_inner(), client, upstream);
        Ok(())
    }

    fn refusal(words: String, status: u16) -> (Value, u16) {
        (json!({"error": words}), status)
    }

    /// The head as the cell gets it: its own path, its own address, the token gone. A request of one answer closes after it, as
    /// every connection of the scout does; a WebSocket's upgrade keeps the client's words.
    fn head_for_cell(head: &RequestHead, path: &str, port: u16) -> Vec<u8> {
        let upgrade = head.headers.has("Upgrade");
        let mut out = format!("{} {path} HTTP/1.1\r\nHost: {}:{port}\r\n", head.method, CellDoor::LISTEN).into_bytes();
        for field in head.headers.iter() {
            let name = field.name.to_ascii_lowercase();
            if Self::KEPT_HERE.contains(&name.as_str()) || (!upgrade && name == "connection") {
                continue;
            }
            out.extend_from_slice(field.name.as_bytes());
            out.extend_from_slice(b": ");
            out.extend_from_slice(&field.value);
            out.extend_from_slice(b"\r\n");
        }
        if !upgrade {
            out.extend_from_slice(b"Connection: close\r\n");
        }
        out.extend_from_slice(b"\r\n");
        out
    }

    /// The bytes on, both ways, each way in a thread of its own. The client's end is told to the cell as the client said it, so a
    /// half that is done does not cut the other; the cell's end ends the client's connection whole: its answer, or its WebSocket, is over.
    fn both_ways(from_client: TcpStream, client: &TcpStream, cell: TcpStream) {
        let (Ok(mut to_client), Ok(mut from_cell)) = (client.try_clone(), cell.try_clone()) else {
            // A socket that cannot be shared cannot be passed on: both are closed, and each side sees its connection end.
            drop(client.shutdown(Shutdown::Both));
            drop(cell.shutdown(Shutdown::Both));
            return;
        };
        let back = std::thread::Builder::new().name("cell-door".to_string()).spawn(move || {
            // A side gone mid-copy ends the copy: what is left to do is the end, said below.
            drop(io::copy(&mut from_cell, &mut to_client));
            drop(to_client.shutdown(Shutdown::Both));
        });
        let mut from_client = from_client;
        let mut to_cell = cell;
        let told = io::copy(&mut from_client, &mut to_cell);
        drop(to_cell.shutdown(if told.is_ok() { Shutdown::Write } else { Shutdown::Both }));
        match back {
            // The answer's half ends with the cell's: waited for, so the connection is counted while it lasts (api/answering.rs).
            Ok(back) => drop(back.join()),
            Err(_) => drop(to_cell.shutdown(Shutdown::Both)),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::{BufRead, Read};
    use std::net::TcpListener;

    fn head_of(raw: &str) -> RequestHead {
        RequestHead::read(&mut BufReader::new(raw.as_bytes())).unwrap()
    }

    #[test]
    fn the_cell_gets_its_own_path_and_address_and_no_token() {
        let head = head_of(
            "POST /api/cell/c22035/v1/chat/completions HTTP/1.1\r\nHost: 10.0.0.5:8092\r\nX-Caravan-Token: secret\r\nConnection: keep-alive\r\nContent-Length: 2\r\nContent-Type: application/json\r\n\r\n",
        );
        let sent = String::from_utf8(Door::head_for_cell(&head, "/v1/chat/completions", 22001)).unwrap();
        assert!(sent.starts_with("POST /v1/chat/completions HTTP/1.1\r\nHost: 127.0.0.1:22001\r\n"), "{sent}");
        assert!(!sent.to_lowercase().contains("x-caravan-token"), "negative: the fleet token stays with the scout: {sent}");
        assert!(!sent.contains("10.0.0.5"), "negative: the scout's own address is not the cell's: {sent}");
        assert!(sent.contains("Content-Length: 2\r\n") && sent.contains("Content-Type: application/json\r\n"), "{sent}");
        assert!(sent.ends_with("Connection: close\r\n\r\n") && !sent.contains("keep-alive"), "one answer, then the end: {sent}");
    }

    #[test]
    fn a_websocket_keeps_its_upgrade() {
        let head = head_of(
            "GET /api/cell/c22024/backend HTTP/1.1\r\nHost: x\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: k\r\n\r\n",
        );
        let sent = String::from_utf8(Door::head_for_cell(&head, "/backend", 22024)).unwrap();
        assert!(sent.contains("Upgrade: websocket\r\n") && sent.contains("Connection: Upgrade\r\n"), "{sent}");
        assert!(!sent.contains("Connection: close"), "negative: an upgrade is not closed after one answer: {sent}");
    }

    /// A cell that reads a request whole and answers with what it read, then closes, as `http.server` does.
    fn echo_cell() -> (u16, std::thread::JoinHandle<String>) {
        let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
        let port = listener.local_addr().unwrap().port();
        let cell = std::thread::spawn(move || {
            let (socket, _) = listener.accept().unwrap();
            let mut reader = BufReader::new(socket.try_clone().unwrap());
            let mut head = String::new();
            loop {
                let mut line = String::new();
                reader.read_line(&mut line).unwrap();
                head.push_str(&line);
                if line == "\r\n" {
                    break;
                }
            }
            let mut body = [0u8; 5];
            reader.read_exact(&mut body).unwrap();
            let mut socket = socket;
            write!(socket, "HTTP/1.1 200 OK\r\nContent-Length: 5\r\nConnection: close\r\n\r\n").unwrap();
            socket.write_all(&body).unwrap();
            head
        });
        (port, cell)
    }

    #[test]
    fn bytes_pass_both_ways_and_the_cell_s_end_ends_the_client_s() {
        let (port, cell) = echo_cell();
        // The scout's side of a client's connection: the head read off it, the body's first bytes still in the reader.
        let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
        let mut client = TcpStream::connect(listener.local_addr().unwrap()).unwrap();
        client.write_all(b"POST /api/cell/c1/x HTTP/1.1\r\nContent-Length: 5\r\n\r\nhel").unwrap();
        let (served, _) = listener.accept().unwrap();
        let mut reader = BufReader::new(served.try_clone().unwrap());
        let head = RequestHead::read(&mut reader).unwrap();
        let passing = std::thread::spawn(move || {
            let mut upstream = TcpStream::connect(("127.0.0.1", port)).unwrap();
            let early = reader.buffer().to_vec();
            upstream.write_all(&Door::head_for_cell(&head, "/x", port)).unwrap();
            upstream.write_all(&early).unwrap();
            Door::both_ways(reader.into_inner(), &served, upstream);
        });
        client.write_all(b"lo").unwrap();
        let mut answer = String::new();
        client.read_to_string(&mut answer).unwrap();
        assert!(
            answer.starts_with("HTTP/1.1 200 OK") && answer.ends_with("hello"),
            "the body came whole, its first bytes too: {answer}"
        );
        passing.join().unwrap();
        assert!(cell.join().unwrap().starts_with("POST /x HTTP/1.1\r\n"));
    }
}
