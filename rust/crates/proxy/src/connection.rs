//! One client's connection: its request read, the decision taken, the request served or refused.

use crate::client::ClientSide;
use crate::exchange::{Asked, Exchange};
use crate::front::{BeforeBody, BodyFor, Front, WithBody};
use crate::proxy::Proxy;
use crate::record::RequestRecord;
use files::Settings;
use rules::{ClientAddress, EntryRefusal, KeyEntry, OpenAiError, Pool, RequestSummary, Route, Told};
use serde_json::{Value, json};
use std::io::{BufReader, Write};
use std::net::{SocketAddr, TcpStream};
use std::sync::Arc;
use std::time::Duration;
use wire::{BodyError, HeadError, RequestBody, RequestHead};

/// A client's connection. One request: every answer closes it.
pub struct Connection<'a> {
    proxy: &'a Proxy,
    stream: TcpStream,
    peer: String,
}

impl<'a> Connection<'a> {
    /// How long a client is given to send each piece of its request. The answer's time is not limited by this.
    const REQUEST_TURN: Duration = Duration::from_secs(120);

    /// The connection on `stream`, from `peer`.
    pub fn new(proxy: &'a Proxy, stream: TcpStream, peer: SocketAddr) -> Self {
        Self { proxy, stream, peer: peer.ip().to_string() }
    }

    /// Serves the connection to its end.
    pub fn serve(self) {
        let Ok(reading) = self.stream.try_clone() else {
            return;
        };
        if reading.set_read_timeout(Some(Self::REQUEST_TURN)).is_err() {
            return;
        }
        let mut source = BufReader::with_capacity(64 * 1024, reading);
        let mut head = match RequestHead::read(&mut source) {
            Ok(head) => head,
            Err(HeadError::Closed | HeadError::Io(_)) => return,
            Err(HeadError::Malformed(words)) => return self.refuse_head(&words),
        };
        let settings = self.proxy.settings.current();
        head.target = Front::plain_target(&head.target);
        match Front::before_body(&settings, &head, self.proxy.clock.epoch() as i64) {
            BeforeBody::ReadBody(route, body_for) => self.read_body_and_go_on(&settings, &head, &route, body_for, source),
            BeforeBody::Answer(answer) => self.answer(&answer),
            BeforeBody::Refuse(refusal, route) => self.refuse(&head, route.as_ref(), &refusal),
        }
    }

    /// Bytes that are not a request at all have no route and no key.
    fn refuse_head(self, words: &str) {
        let told: Told = OpenAiError::new(400, format!("The request cannot be read: {words}.")).into();
        let id = self.proxy.new_request_id();
        // A client that sent this much of nothing and left changes nothing here.
        drop(ClientSide::new(self.stream, Arc::clone(&self.proxy.clock)).send_told(&told, &id));
    }

    /// An answer of this process's own. A client that left before it changes nothing here.
    fn answer(self, answer: &Value) {
        drop(ClientSide::new(self.stream, Arc::clone(&self.proxy.clock)).send_answer(answer));
    }

    fn read_body_and_go_on(
        self,
        settings: &Arc<Settings>,
        head: &RequestHead,
        route: &Route,
        body_for: BodyFor,
        mut source: BufReader<TcpStream>,
    ) {
        if head.headers.get("Expect").is_some_and(|value| value.eq_ignore_ascii_case("100-continue")) {
            let mut socket = &self.stream;
            if socket.write_all(b"HTTP/1.1 100 Continue\r\n\r\n").is_err() {
                return;
            }
        }
        let body = match RequestBody::read(&head.headers, &mut source) {
            // absent-ok: `RequestBody.read(...) or b""`: no body is an empty one, and what it says is read from it.
            Ok(body) => body.unwrap_or_default(),
            Err(BodyError::Malformed(words)) => return self.refuse(head, Some(route), &EntryRefusal::broken_body(&words)),
            Err(BodyError::Io(_)) => return,
        };
        match Front::with_body(settings, route, head, &body, body_for) {
            WithBody::Answer(answer) => self.answer(&answer),
            WithBody::Refuse(refusal) => self.refuse(head, Some(route), &refusal),
            WithBody::Serve { pool, streaming } => self.serve_here(settings, head, route, *pool, body, streaming),
        }
    }

    /// A refusal of the entry: the client is told, and the journal has it under the client's name once it is known. `_refuse`.
    fn refuse(self, head: &RequestHead, route: Option<&Route>, refusal: &EntryRefusal) {
        let id = self.proxy.new_request_id();
        let told: Told = refusal.error.clone().into();
        let label = route.map_or("entry", |route| route.label.as_str());
        let port = route.map_or(json!("entry"), |route| json!(route.port));
        let client = self.client_name(head);
        let item = json!({
            "id": id, "route": label, "port": port, "method": head.method, "path": head.path(),
            "status": told.status, "reason": refusal.reason, "client": client,
        });
        // A client gone before its refusal changes nothing here.
        drop(ClientSide::new(self.stream, Arc::clone(&self.proxy.clock)).send_told(&told, &id));
        self.proxy.recorder.event("blocked", label, &id, Some(&item), json!({}));
    }

    fn serve_here(self, settings: &Arc<Settings>, head: &RequestHead, route: &Route, pool: Pool, body: Vec<u8>, streaming: bool) {
        let started = self.proxy.clock.epoch();
        let content_type = head.headers.text_of("Content-Type");
        let record = RequestRecord {
            id: self.proxy.new_request_id(),
            method: head.method.clone(),
            path: head.path().to_string(),
            client: self.client_name(head),
            started,
            route: route.clone(),
            pool_id: pool.id.clone(),
            pool_name: pool.name.clone(),
            summary: RequestSummary::of(&body, &content_type),
            client_deadline: started + settings.policy.queue.client_timeout(route.client_timeout_seconds) as f64,
        };
        let asked = Asked { headers: head.headers.clone(), target: head.target.clone(), body, streaming };
        let client = ClientSide::new(self.stream, Arc::clone(&self.proxy.clock));
        Exchange::new(self.proxy, Arc::clone(settings), &record, pool, asked, client).run();
    }

    /// The sender as the journal names it: Routing's test of a client, from this machine itself and not through the DSM's proxy,
    /// is named as the test, so that a client cannot hide its own errors by sending the header.
    fn client_name(&self, head: &RequestHead) -> String {
        let forwarded = head.headers.get(ClientAddress::FORWARDED);
        let direct = matches!(self.peer.as_str(), "127.0.0.1" | "::1") && forwarded.as_deref().is_none_or(str::is_empty);
        if direct && head.headers.get(KeyEntry::PROBE_HEADER).is_some_and(|value| !value.is_empty()) {
            return KeyEntry::PROBE_CLIENT.to_string();
        }
        ClientAddress::of(&self.peer, forwarded.as_deref(), head.headers.get(ClientAddress::REAL_IP).as_deref())
    }
}
