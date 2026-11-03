//! The scout's HTTP surface: which path does what, and who may ask. The scout's page, `/api/pairing`, `/api/health` and `/openapi.json` are open. Everything else stands behind the fleet token when `config.json` has one: the controller sends it as `X-Caravan-Token`, the pairing form may put it in the body. No token configured means open, a trusted LAN. The gate stands BEFORE the routes, so an unknown path without a token is 401, not 404. A path matches whole, query string and all.

use crate::api::handlers::{Handlers, Query};
use crate::api::routes::{RouteKind, RouteRow};
use crate::api::spec::ApiSpec;
use crate::entry::body::{BodyError, EntryBody};
use crate::entry::machine_entry::{Forwarded, MachineEntry};
use crate::errors::AppError;
use crate::log::Log;
use crate::report::Report;
use crate::scout::Scout;
use net::{Closing, Sha256};
use rules::Coerce;
use serde_json::{Map, Value, json};
use std::io::{BufRead, BufReader, Read, Write};
use std::net::{SocketAddr, TcpListener, TcpStream};
use std::sync::Arc;
use wire::{HeadError, HttpDate, Percent, Reply, RequestHead};

/// The answering of a scout: its tables, cut from the one list.
pub struct Api {
    scout: Arc<Scout>,
    routes: Vec<RouteRow>,
    spec: Value,
    page: &'static str,
}

impl Api {
    /// The most a request to the machine's entry may carry: a recording of two hours as 16 kHz WAV. The scout holds it in memory while it goes on.
    const ENTRY_BODY_MAX: u64 = 256 << 20;

    /// The answering of this scout.
    pub fn new(scout: Arc<Scout>) -> Result<Self, AppError> {
        let routes = RouteRow::table()
            .map_err(|error| AppError::with_status(format!("the table of paths does not read: {error}"), 500))?;
        let spec = ApiSpec::document(&routes, Report::VERSION);
        Ok(Self { scout, routes, spec, page: include_str!("../page.html") })
    }

    fn kind_of(&self, path: &str, method: &str) -> Option<RouteKind> {
        self.routes.iter().find(|route| route.path() == path && route.method() == method).map(RouteRow::kind)
    }

    /// Accepts for good, one thread to a connection.
    pub fn serve(self: Arc<Self>, listener: &TcpListener) {
        loop {
            match listener.accept() {
                Ok((stream, peer)) => {
                    let api = Arc::clone(&self);
                    let started = std::thread::Builder::new()
                        .name("request".to_string())
                        .spawn(move || api.answer_connection(stream, peer));
                    if let Err(error) = started {
                        Log::line(&format!("a connection not answered: {error}"));
                    }
                }
                Err(error) => Log::line(&format!("accept: {error}")),
            }
        }
    }

    fn answer_connection(&self, stream: TcpStream, peer: SocketAddr) {
        let Ok(writer) = stream.try_clone() else {
            return;
        };
        let mut reader = BufReader::new(stream);
        let mut client = Client { writer, now: self.scout.clock.epoch() as u64 };
        match RequestHead::read(&mut reader) {
            Ok(head) => {
                Log::line(&format!("{} - \"{} {}\"", peer.ip(), head.method, head.target));
                match head.method.as_str() {
                    "GET" => self.get(&head, &mut client),
                    "POST" => self.post(&head, &mut reader, &mut client),
                    other => client.json(&json!({"error": format!("Unsupported method ({other})")}), 501),
                }
            }
            Err(HeadError::Malformed(words)) => client.json(&json!({"error": words}), 400),
            Err(HeadError::Closed | HeadError::Io(_)) => {}
        }
        Closing::of(&client.writer);
    }

    fn token_ok(&self, head: &RequestHead, body: Option<&Map<String, Value>>) -> bool {
        let expected = self.scout.config.token();
        if expected.is_empty() {
            return true;
        }
        let mut got = head.headers.text_of("X-Caravan-Token");
        if got.is_empty() {
            got = body.map_or_else(String::new, |body| Coerce::text(body.get("token")));
        }
        // Compared by their digests, so that a wrong token's time says nothing of the right one.
        Sha256::of(got.as_bytes()) == Sha256::of(expected.as_bytes())
    }

    fn get(&self, head: &RequestHead, client: &mut Client) {
        let target = head.target.as_str();
        // The machine's entry by OpenAI's API: open like the cells it reaches.
        if target.starts_with("/v1/") {
            let (payload, status) = self.scout.entry.get(target);
            client.json(&payload, status);
            return;
        }
        match self.kind_of(target, "GET") {
            Some(RouteKind::Page) => client.page(self.page.as_bytes()),
            Some(RouteKind::Public) if target == "/openapi.json" => client.json(&self.spec, 200),
            Some(RouteKind::Public) => self.table_get(target, client),
            _ if !self.token_ok(head, None) => client.refuse(),
            kind => {
                let (path, query) = target.split_once('?').unwrap_or((target, ""));
                if let Some((_, handler)) = Handlers::QUERIES.iter().find(|(said, _)| *said == path) {
                    client.result(handler(&self.scout, &Self::first_values(query)).map(|payload| (payload, 200)));
                } else if kind == Some(RouteKind::Get) {
                    self.table_get(target, client);
                } else {
                    client.json(&json!({"error": "not found"}), 404);
                }
            }
        }
    }

    fn table_get(&self, target: &str, client: &mut Client) {
        match Handlers::GETS.iter().find(|(said, _)| *said == target) {
            Some((_, handler)) => client.result(handler(&self.scout).map(|payload| (payload, 200))),
            None => client.json(&json!({"error": "not found"}), 404),
        }
    }

    /// `{k: v[0] for k, v in parse_qs(query).items()}`: the first value of each name; a blank value is no value.
    fn first_values(query: &str) -> Query {
        let mut out = Query::new();
        for pair in query.split('&') {
            let Some((name, value)) = pair.split_once('=').filter(|(_, value)| !value.is_empty()) else {
                continue;
            };
            let said = |word: &str| Percent::decode(&word.replace('+', " "));
            out.entry(said(name)).or_insert_with(|| said(value));
        }
        out
    }

    fn read_body(head: &RequestHead, reader: &mut impl BufRead) -> Result<Map<String, Value>, AppError> {
        let length = head.headers.text_of("Content-Length");
        let length: u64 = if length.is_empty() {
            0
        } else {
            length
                .trim()
                .parse()
                .map_err(|_| AppError::with_status(format!("invalid literal for int() with base 10: {length:?}"), 500))?
        };
        let mut raw = Vec::new();
        reader.take(length).read_to_end(&mut raw).map_err(|error| AppError::with_status(error.to_string(), 500))?;
        if raw.is_empty() {
            return Ok(Map::new());
        }
        match serde_json::from_slice::<Value>(&raw).map_err(|error| AppError::with_status(error.to_string(), 500))? {
            Value::Object(fields) => Ok(fields),
            _ => Err(AppError::new("body must be a JSON object")),
        }
    }

    fn post(&self, head: &RequestHead, reader: &mut BufReader<TcpStream>, client: &mut Client) {
        let target = head.target.as_str();
        if target.starts_with("/v1/") {
            self.entry_request(head, reader, client);
            return;
        }
        if target == "/api/controller-url" {
            let answer = self.pair(head, reader);
            client.result(answer);
            return;
        }
        if !self.token_ok(head, None) {
            client.refuse();
            return;
        }
        let Some((_, handler)) = Handlers::POSTS.iter().find(|(said, _)| *said == target) else {
            client.json(&json!({"error": "not found"}), 404);
            return;
        };
        let mut body = || Self::read_body(head, reader);
        client.result(handler(&self.scout, &mut body));
    }

    /// The pairing form may carry the token in the body, so the body is read before the gate on this one path, and a token the scout does not hold yet may pass it.
    fn pair(&self, head: &RequestHead, reader: &mut BufReader<TcpStream>) -> Result<(Value, u16), AppError> {
        let body = Self::read_body(head, reader)?;
        let url = if Coerce::truthy(body.get("url")) { Coerce::text(body.get("url")) } else { String::new() };
        let token = if Coerce::truthy(body.get("token")) { Coerce::text(body.get("token")) } else { String::new() };
        if !self.token_ok(head, Some(&body)) && !self.scout.heartbeat.takes_new_token(&url, &token) {
            return Err(AppError::with_status("fleet token required (X-Caravan-Token)", 401));
        }
        Ok((self.scout.heartbeat.pair(&url, &token)?, 200))
    }

    /// A request to the machine's entry: its body read whole, by its length or its chunks, never past the limit, and handed on. A client gone mid-answer ends it.
    fn entry_request(&self, head: &RequestHead, reader: &mut BufReader<TcpStream>, client: &mut Client) {
        let transfer = head.headers.get("Transfer-Encoding");
        let length = head.headers.get("Content-Length");
        let refused = |words: String| MachineEntry::refusal(&words, "invalid_request_error", None, None);
        let body = match EntryBody::new(Self::ENTRY_BODY_MAX).read(transfer.as_deref(), length.as_deref(), reader) {
            Ok(body) => body,
            Err(BodyError::TooLong) => {
                client.json(&refused(format!("The request body is over {} bytes", Self::ENTRY_BODY_MAX)), 413);
                return;
            }
            Err(BodyError::Malformed(words)) => {
                client.json(&refused(format!("The request body cannot be read: {words}")), 400);
                return;
            }
            Err(BodyError::Io(_)) => return,
        };
        match self.scout.entry.forward(head, body) {
            Forwarded::Refused(payload, status) => client.json(&payload, status),
            Forwarded::Answer(answer, answer_body) => {
                let mut reply = Reply::new(answer.status);
                for (name, value) in MachineEntry::passed(&answer.headers, &MachineEntry::TO_CLIENT) {
                    reply = reply.field(&name, value);
                }
                if let Some(said) = answer.headers.get("Content-Length").filter(|_| !answer.headers.has("Transfer-Encoding")) {
                    reply = reply.field("Content-Length", said);
                }
                if client.send_head(reply) {
                    MachineEntry::relay(answer_body, &mut client.writer);
                }
            }
        }
    }
}

/// The client's side of one request. HTTP/1.1 with `Connection: close`: one request to a connection, as `http.server`'s HTTP/1.0 has it.
struct Client {
    writer: TcpStream,
    now: u64,
}

impl Client {
    fn send_head(&mut self, reply: Reply) -> bool {
        let head = reply
            .field("Server", format!("caravan-scout/{}", Report::VERSION))
            .field("Date", HttpDate::format(self.now))
            .field("Connection", "close")
            .head();
        self.writer.write_all(&head).is_ok()
    }

    fn json(&mut self, payload: &Value, status: u16) {
        // A value of no JSON cannot be: what is written here was made of JSON's own values.
        let text = serde_json::to_string_pretty(payload).unwrap_or_else(|_| "{}".to_string());
        let reply = Reply::new(status)
            .field("Content-Type", "application/json; charset=utf-8")
            .field("Content-Length", text.len().to_string());
        if self.send_head(reply) {
            // A client gone has been answered as far as it wanted.
            drop(self.writer.write_all(text.as_bytes()));
        }
    }

    fn page(&mut self, data: &[u8]) {
        let reply = Reply::new(200)
            .field("Content-Type", "text/html; charset=utf-8")
            .field("Content-Length", data.len().to_string())
            .field("Cache-Control", "no-cache");
        if self.send_head(reply) {
            // A client gone has been answered as far as it wanted.
            drop(self.writer.write_all(data));
        }
    }

    fn refuse(&mut self) {
        self.json(&json!({"error": "fleet token required (X-Caravan-Token)"}), 401);
    }

    fn result(&mut self, result: Result<(Value, u16), AppError>) {
        match result {
            Ok((payload, status)) => self.json(&payload, status),
            Err(error) => self.json(&json!({"error": error.message}), error.status),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::BTreeSet;

    #[test]
    fn every_row_has_its_handler_and_every_handler_its_row() {
        let rows = RouteRow::table().unwrap();
        assert_eq!(rows.len(), 53);
        let of = |kinds: &[RouteKind]| -> BTreeSet<String> {
            rows.iter().filter(|row| kinds.contains(&row.kind())).map(RouteRow::path).collect()
        };
        let gets: BTreeSet<String> =
            Handlers::GETS.iter().map(|(path, _)| (*path).to_string()).filter(|path| path != "/").collect();
        let pages = of(&[RouteKind::Page]);
        assert_eq!(pages.into_iter().collect::<Vec<_>>(), ["/", "/index.html"]);
        assert_eq!(gets, of(&[RouteKind::Public, RouteKind::Get]));
        let queries: BTreeSet<String> = Handlers::QUERIES.iter().map(|(path, _)| (*path).to_string()).collect();
        assert_eq!(queries, of(&[RouteKind::Query]));
        let posts: BTreeSet<String> = Handlers::POSTS.iter().map(|(path, _)| (*path).to_string()).collect();
        assert_eq!(posts, of(&[RouteKind::Post]));
        assert_eq!(of(&[RouteKind::Own]).into_iter().collect::<Vec<_>>(), ["/api/controller-url"]);
    }

    #[test]
    fn a_query_says_its_first_values_and_no_blank_ones() {
        let query = Api::first_values("port=22001&lines=&run=a%20b&port=2&x&name=c+d");
        assert_eq!(query.get("port").map(String::as_str), Some("22001"));
        assert_eq!(query.get("lines"), None);
        assert_eq!(query.get("run").map(String::as_str), Some("a b"));
        assert_eq!(query.get("x"), None);
        assert_eq!(query.get("name").map(String::as_str), Some("c d"));
    }
}
