//! A live talk with a running cell over the cell's own WebSocket, through the controller.

use super::cell_talk::CellTalk;
use crate::app::App;
use crate::web::Exchange;
use net::{Base64Std, Sha1};
use os::Readiness;
use plumbing::log::Log;
use rules::{AppError, Coerce};
use serde_json::{Value, json};
use std::collections::BTreeMap;
use std::io::{Read, Write};
use std::net::{Shutdown, TcpStream, ToSocketAddrs};
use std::time::Duration;

/// The browser's upgrade request.
struct LiveAsk {
    fields: Vec<(&'static str, String)>,
}

impl LiveAsk {
    const VERSION: &'static str = "13";
    const PASSED: [&'static str; 4] =
        ["Sec-WebSocket-Key", "Sec-WebSocket-Version", "Sec-WebSocket-Extensions", "Sec-WebSocket-Protocol"];
    const GUID: &'static str = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11";

    /// True when the request asks to become a WebSocket.
    fn wanted(h: &Exchange<'_>) -> bool {
        let connection = h.field_or_empty("Connection");
        let upgrade = connection.split(',').any(|token| Coerce::strip(token).eq_ignore_ascii_case("upgrade"));
        Coerce::strip(&h.field_or_empty("Upgrade")).eq_ignore_ascii_case("websocket") && upgrade
    }

    fn get(&self, name: &str) -> &str {
        self.fields.iter().find(|(field, _)| *field == name).map_or("", |(_, value)| value.as_str())
    }

    /// The ask, refused when its handshake is not a WebSocket's.
    fn read(h: &Exchange<'_>) -> Result<Self, AppError> {
        let ask = Self {
            fields: Self::PASSED.iter().map(|name| (*name, Coerce::strip(&h.field_or_empty(name)).to_string())).collect(),
        };
        if ask.get("Sec-WebSocket-Version") != Self::VERSION {
            return Err(AppError::new(format!("Sec-WebSocket-Version must be {}", Self::VERSION)));
        }
        if Base64Std::decode(ask.get("Sec-WebSocket-Key")).is_none_or(|key| key.len() != 16) {
            return Err(AppError::new("Sec-WebSocket-Key must be 16 bytes in base64"));
        }
        Ok(ask)
    }

    /// The Sec-WebSocket-Accept a server must answer this ask with.
    fn accept(&self) -> String {
        Base64Std::encode(&Sha1::bytes_of(format!("{}{}", self.get("Sec-WebSocket-Key"), Self::GUID).as_bytes()))
    }

    fn lines(&self) -> Vec<String> {
        self.fields.iter().filter(|(_, value)| !value.is_empty()).map(|(name, value)| format!("{name}: {value}")).collect()
    }
}

/// The head of the cell's answer to the handshake.
struct CellHead {
    head: Vec<u8>,
    rest: Vec<u8>,
    status: u16,
    line: String,
    fields: BTreeMap<String, String>,
}

impl CellHead {
    fn new(head: Vec<u8>, rest: Vec<u8>) -> Self {
        let text: String = head.iter().map(|byte| char::from(*byte)).collect();
        let (first, more) = text.split_once("\r\n").unwrap_or((text.as_str(), ""));
        // absent-ok: a head with no status is read as no answer.
        let status = first.split(' ').nth(1).and_then(|word| word.parse().ok()).unwrap_or(0);
        let mut fields = BTreeMap::new();
        for line in more.split("\r\n") {
            if let Some((name, value)) = line.split_once(':') {
                fields.insert(Coerce::strip(name).to_lowercase(), Coerce::strip(value).to_string());
            }
        }
        Self { status, line: first.to_string(), fields, head, rest }
    }
}

/// Opens a running cell's WebSocket for the board and passes the talk on both ways.
pub struct CellLive<'app> {
    app: &'app App,
}

impl<'app> CellLive<'app> {
    const IDLE: f64 = 300.0;
    const TICK: Duration = Duration::from_secs(5);
    const CONNECT: Duration = Duration::from_secs(10);
    const HEAD_LIMIT: usize = 16384;
    const CHUNK: usize = 65536;

    /// The talks of `app`.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    /// `((ip, port), path, config)` of a running cell whose runner talks live.
    fn target(&self, host_id: &str, port: Option<&Value>) -> Result<(String, &'static str, Value), AppError> {
        let talk = CellTalk::of(self.app);
        let (address, config) = talk.cell(host_id, CellTalk::port_of(port)?)?;
        let row = talk.runner_of(&config).row();
        if row.live.path.is_empty() {
            let who = if row.id.is_empty() { "command" } else { row.id };
            return Err(AppError::new(format!("a {who} cell does not talk live")));
        }
        Ok((address, row.live.path, config))
    }

    /// What a talk would reach, and whether the cell answers its health.
    pub fn check(&self, host_id: &str, port: Option<&Value>) -> Result<Value, AppError> {
        let (address, _, config) = self.target(host_id, port)?;
        let talk = CellTalk::of(self.app);
        let runner = talk.runner_of(&config);
        let health = {
            let said = runner.health_path(&serde_json::Map::new());
            if said.is_empty() { "/health".to_string() } else { said }
        };
        let out = match talk.ask(&address, &health, None) {
            Ok(answer) => {
                let error = if answer.status < 400 { String::new() } else { CellTalk::refusal(answer.status, &answer.raw) };
                json!({"status": answer.status, "error": error, "ms": answer.ms})
            }
            Err(error) => json!({"status": 0, "error": error.message, "ms": null}),
        };
        Ok(json!({"ok": true, "runner": runner.row().id, "protocol": runner.row().live.protocol, "health": out}))
    }

    fn read_head(&self, socket: &mut TcpStream) -> Result<CellHead, AppError> {
        let mut data = Vec::new();
        let mut chunk = [0u8; 4096];
        let at_end = |data: &[u8]| data.windows(4).position(|window| window == b"\r\n\r\n");
        while at_end(&data).is_none() {
            let count = socket
                .read(&mut chunk)
                .map_err(|error| AppError::with_status(format!("the cell broke off the handshake: {error}"), 502))?;
            if count == 0 {
                break;
            }
            data.extend_from_slice(chunk.get(..count).unwrap_or_default());
            if data.len() > Self::HEAD_LIMIT {
                return Err(AppError::with_status(
                    format!("the cell's answer to the handshake is longer than {} bytes", Self::HEAD_LIMIT),
                    502,
                ));
            }
        }
        let Some(at) = at_end(&data) else {
            return Err(AppError::with_status("the cell closed the connection before it answered the handshake", 502));
        };
        let rest = data.split_off(at + 4);
        Ok(CellHead::new(data, rest))
    }

    fn open(&self, address: &str, path: &str, ask: &LiveAsk) -> Result<(TcpStream, CellHead), AppError> {
        let silent = |error: String| AppError::with_status(format!("the cell on {address} did not answer: {error}"), 502);
        let place = address
            .to_socket_addrs()
            .map_err(|error| silent(error.to_string()))?
            .next()
            .ok_or_else(|| silent("no such address".to_string()))?;
        let mut socket = TcpStream::connect_timeout(&place, Self::CONNECT).map_err(|error| silent(error.to_string()))?;
        drop(socket.set_read_timeout(Some(Self::CONNECT)));
        let mut request = vec![
            format!("GET {path} HTTP/1.1"),
            format!("Host: {address}"),
            "Upgrade: websocket".to_string(),
            "Connection: Upgrade".to_string(),
        ];
        request.extend(ask.lines());
        let text = format!("{}\r\n\r\n", request.join("\r\n"));
        socket
            .write_all(text.as_bytes())
            .map_err(|error| AppError::with_status(format!("the cell on {address} broke off the handshake: {error}"), 502))?;
        let answer = self.read_head(&mut socket)?;
        if answer.status != 101 {
            let line = if answer.line.is_empty() { "no answer" } else { &answer.line };
            return Err(AppError::with_status(format!("the cell did not open a WebSocket on {path}: {line}"), 502));
        }
        if answer.fields.get("sec-websocket-accept").map(String::as_str) != Some(ask.accept().as_str()) {
            return Err(AppError::with_status("the cell's Sec-WebSocket-Accept is not the one of the key it was given", 502));
        }
        drop(socket.set_read_timeout(None));
        Ok((socket, answer))
    }

    /// The bytes passed on both ways until a side ends or both are silent long enough.
    fn relay(&self, client: &TcpStream, cell: &TcpStream, first: &[u8]) -> Value {
        let started = self.app.clock.monotonic();
        let mut last = started;
        let mut count = (0usize, first.len());
        let mut ended = String::new();
        let (mut client_write, mut cell_write) = (client, cell);
        if !first.is_empty()
            && let Err(error) = client_write.write_all(first)
        {
            ended = format!("{error}");
        }
        let mut chunk = vec![0u8; Self::CHUNK];
        while ended.is_empty() {
            let ready = match Readiness::of_two(client, cell, Self::TICK) {
                Ok(ready) => ready,
                Err(error) => {
                    ended = format!("{error}");
                    break;
                }
            };
            if !ready.0 && !ready.1 {
                if self.app.clock.monotonic() - last >= Self::IDLE {
                    ended = "idle".to_string();
                }
                continue;
            }
            if ready.0
                && let Some(end) = Self::pass_on(client, cell_write, "client", &mut chunk, &mut count.0)
            {
                ended = end;
            } else if ready.1
                && let Some(end) = Self::pass_on(cell, client_write, "cell", &mut chunk, &mut count.1)
            {
                ended = end;
            }
            last = self.app.clock.monotonic();
        }
        // Either side may have gone already: there is nothing to say about a socket that will not shut.
        drop(cell_write.flush());
        drop(cell.shutdown(Shutdown::Both));
        drop(client.shutdown(Shutdown::Both));
        json!({"up": count.0, "down": count.1, "seconds": Coerce::rounded(self.app.clock.monotonic() - started, 1), "ended": ended})
    }

    /// One read from `source` handed on to `sink`; the word that ends the talk, when it ended.
    fn pass_on(mut source: &TcpStream, mut sink: &TcpStream, name: &str, chunk: &mut [u8], moved: &mut usize) -> Option<String> {
        match source.read(chunk) {
            Ok(0) => Some(name.to_string()),
            Ok(count) => {
                if let Err(error) = sink.write_all(chunk.get(..count).unwrap_or_default()) {
                    return Some(format!("{error}"));
                }
                *moved += count;
                None
            }
            Err(error) => Some(format!("{error}")),
        }
    }

    /// `GET /api/cell-live` answered: what it would reach when no WebSocket is asked for, else the talk itself.
    pub fn serve(&self, h: &mut Exchange<'_>, host_id: &str, port: Option<&Value>) -> Result<(), AppError> {
        if !LiveAsk::wanted(h) {
            h.ok(&self.check(host_id, port)?);
            return Ok(());
        }
        let ask = LiveAsk::read(h)?;
        let (address, path, config) = self.target(host_id, port)?;
        let id = CellTalk::of(self.app).runner_of(&config).row().id;
        let (cell, answer) = self.open(&address, path, &ask)?;
        h.close = true;
        h.write(&answer.head);
        let port_word = Coerce::str_of(port);
        Log::line(&format!("cell-live {host_id}:{port_word} {id} {path} opened"));
        let (_, client) = h.socket();
        let moved = self.relay(client, &cell, &answer.rest);
        Log::line(&format!(
            "cell-live {host_id}:{port_word} ended ({}): {} B up, {} B down, {} s",
            Coerce::text(moved.get("ended")),
            Coerce::str_of(moved.get("up")),
            Coerce::str_of(moved.get("down")),
            Coerce::str_of(moved.get("seconds")),
        ));
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_head_is_read_as_latin_one_lines() {
        let head =
            CellHead::new(b"HTTP/1.1 101 Switching\r\nSec-WebSocket-Accept: abc\r\nX: y\r\n\r\n".to_vec(), b"rest".to_vec());
        assert_eq!(head.status, 101);
        assert_eq!(head.fields["sec-websocket-accept"], "abc");
        assert_eq!(head.rest, b"rest");
    }
}
