//! A request on its way to its model: the part of the leg loop in `proxy()` a machine's model
//! goes through. The machine's entry first, then a running copy on its own port, each once; a cell that says it is still
//! loading is asked again for as long as the policy allows.

use crate::client::ClientSide;
use crate::clock::RequestClock;
use crate::proxy::Proxy;
use crate::record::RequestRecord;
use crate::stop::{Ending, UpstreamEnd, Waited};
use crate::watch::Watch;
use net::{Dial, Stream};
use rules::{ChatLevers, MachineOutput, RequestFields};
use serde_json::json;
use std::io::{self, BufReader, Read, Write};
use std::net::TcpStream;
use std::time::Duration;
use wire::{AnswerBody, AnswerHead, AnswerHeadReader, Headers};

/// An upstream's answer, its head read.
pub struct Answer {
    /// The head.
    pub head: AnswerHead,
    /// The body that follows.
    pub body: AnswerBody<Stream>,
    /// The first bytes of an error's body: what the journal keeps of it, and the client's words come from.
    pub error_raw: Vec<u8>,
}

impl Answer {
    /// Whether it is an event stream.
    pub fn is_event_stream(&self) -> bool {
        self.head.headers.get("Content-Type").is_some_and(|value| value.to_lowercase().starts_with("text/event-stream"))
    }

    /// An error's first bytes as text.
    pub fn error_text(&self) -> String {
        String::from_utf8_lossy(&self.error_raw).into_owned()
    }
}

/// What went wrong on the way.
enum Miss {
    /// The socket failed: the next way is tried.
    Socket(io::Error),
    /// The request ended meanwhile.
    Ended(Ending),
}

impl From<io::Error> for Miss {
    fn from(error: io::Error) -> Self {
        Self::Socket(error)
    }
}

impl From<Ending> for Miss {
    fn from(ending: Ending) -> Self {
        Self::Ended(ending)
    }
}

/// One request's way to its model. Holds what goes out; the way is walked by `ask`.
pub struct UpstreamCall<'a> {
    proxy: &'a Proxy,
    record: &'a RequestRecord,
    output: &'a MachineOutput,
    head_fields: Vec<(String, Vec<u8>)>,
    target: String,
    body: Vec<u8>,
    spares_tried: Vec<u16>,
    loading_retries: u32,
}

impl<'a> UpstreamCall<'a> {
    /// How many bytes of an error are read for the journal.
    const ERROR_KEPT: u64 = 4096;
    /// How long one connect may take before the client is looked at again.
    const CONNECT_TURN: Duration = Duration::from_secs(2);
    /// How long a socket read waits before the client is looked at again.
    pub const READ_TURN: Duration = Duration::from_secs(2);
    /// Python's `timeout=600` on the connection: this long without a byte, the upstream counts as gone.
    const SOCKET_LIMIT: f64 = 600.0;
    /// Seconds between two questions to a cell that says it is loading.
    const LOADING_RETRY: u64 = 3;
    /// The client's fields that stay with the caravan: its key opens a route here, not a server there, and the length is the
    /// length of the body that goes. `Expect` has been answered by this side.
    const KEPT_OUT: [&'static str; 13] = [
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
        "host",
        "authorization",
        "x-api-key",
        "content-length",
        "expect",
    ];

    /// The call of `record`'s request with these fields and this body. The body names the model its machine knows, not the pool or the
    /// name with its place in brackets a client called, and says "no thinking" the way a cell's template takes it.
    pub fn new(
        proxy: &'a Proxy,
        record: &'a RequestRecord,
        output: &'a MachineOutput,
        headers: &Headers,
        target: &str,
        body: Vec<u8>,
    ) -> Self {
        let body = if output.name.is_empty() {
            body
        } else {
            RequestFields::model_named(body, &output.name, &headers.text_of("Content-Type"))
        };
        let body = ChatLevers::for_cell(&body, target).unwrap_or(body);
        Self {
            proxy,
            record,
            output,
            head_fields: Self::kept_fields(headers),
            target: target.to_string(),
            body,
            spares_tried: Vec::new(),
            loading_retries: 0,
        }
    }

    fn kept_fields(headers: &Headers) -> Vec<(String, Vec<u8>)> {
        headers
            .iter()
            .filter(|field| !Self::KEPT_OUT.iter().any(|name| field.name.eq_ignore_ascii_case(name)))
            .filter(|field| !field.name.eq_ignore_ascii_case("x-forwarded-for"))
            .map(|field| (field.name.clone(), field.value.clone()))
            .collect()
    }

    /// The bytes of the request to `port`.
    fn request_bytes(&self, port: u16) -> Vec<u8> {
        let output = self.output;
        let mut out = Vec::with_capacity(1024 + self.body.len());
        out.extend_from_slice(format!("{} {} HTTP/1.1\r\n", self.record.method, self.target).as_bytes());
        out.extend_from_slice(format!("Host: {}:{port}\r\n", output.upstream_host).as_bytes());
        let mut says_encoding = false;
        for (name, value) in &self.head_fields {
            says_encoding |= name.eq_ignore_ascii_case("accept-encoding");
            out.extend_from_slice(name.as_bytes());
            out.extend_from_slice(b": ");
            out.extend_from_slice(value);
            out.extend_from_slice(b"\r\n");
        }
        if !says_encoding {
            out.extend_from_slice(b"Accept-Encoding: identity\r\n");
        }
        out.extend_from_slice(format!("Content-Length: {}\r\n", self.body.len()).as_bytes());
        out.extend_from_slice(b"Connection: close\r\n");
        let label: String = self.record.route.label.chars().filter(|letter| !letter.is_control()).collect();
        out.extend_from_slice(format!("X-Agent-Proxy: {label}\r\n").as_bytes());
        out.extend_from_slice(format!("X-Agent-Proxy-Request-Id: {}\r\n", self.record.id).as_bytes());
        out.extend_from_slice(format!("X-Forwarded-For: {}\r\n\r\n", self.record.client).as_bytes());
        out.extend_from_slice(&self.body);
        out
    }

    /// Walks the way until an answer comes. `client` and `watch` are looked at while it waits.
    pub fn ask(
        &mut self,
        clock: &mut RequestClock,
        watch: &mut Watch,
        client: &mut ClientSide,
        loading_wait: f64,
    ) -> Result<Answer, Ending> {
        let deadline = self.proxy.clock.epoch() + loading_wait;
        let mut port = self.output.upstream_port;
        loop {
            match self.attempt(port, clock, watch, client) {
                Ok(answer) if self.still_loading(&answer) && self.proxy.clock.epoch() < deadline => {
                    self.note_loading_retry(deadline);
                    watch.sleep(Self::LOADING_RETRY, client)?;
                    port = self.output.upstream_port;
                }
                Ok(answer) => return Ok(answer),
                Err(Miss::Ended(ending)) => return Err(ending),
                Err(Miss::Socket(error)) => match self.next_spare() {
                    Some(spare) => {
                        self.note_spare(spare, &error);
                        port = spare;
                    }
                    None => return Err(self.connect_failed(&error)),
                },
            }
        }
    }

    fn still_loading(&self, answer: &Answer) -> bool {
        const LOADING: &[u8] = b"Loading model";
        answer.head.status == 503 && answer.error_raw.windows(LOADING.len()).any(|piece| piece == LOADING)
    }

    fn note_loading_retry(&mut self, deadline: f64) {
        self.loading_retries += 1;
        let remaining = ((deadline - self.proxy.clock.epoch()) * 10.0).round() / 10.0;
        self.proxy.recorder.event(
            "loading_model_retry",
            &self.record.route.label,
            &self.record.id,
            None,
            json!({"attempt": self.loading_retries, "retryDelaySec": Self::LOADING_RETRY as f64, "remainingSec": remaining}),
        );
    }

    /// The port of a running copy not tried yet.
    fn next_spare(&mut self) -> Option<u16> {
        let spare = self.output.copy_ports.iter().copied().find(|port| !self.spares_tried.contains(port))?;
        self.spares_tried.push(spare);
        Some(spare)
    }

    fn note_spare(&self, spare: u16, error: &io::Error) {
        self.proxy.recorder.event(
            "machine_entry_spare",
            &self.record.route.label,
            &self.record.id,
            None,
            json!({"output": self.output.id, "port": spare, "error": Self::short(&error.to_string())}),
        );
    }

    /// No way left: what the journal says of it, and the failure the request ends with.
    fn connect_failed(&self, error: &io::Error) -> Ending {
        self.proxy.board.update_active(self.record.route.port, &self.record.id, json!({"phase": "reading", "status": 502}));
        self.proxy.recorder.event(
            "upstream_response",
            &self.record.route.label,
            &self.record.id,
            None,
            json!({"status": 502, "contentType": "", "upstreamErrorBody": format!("upstream connect failed: {error}"), "cloudMeta": null}),
        );
        Ending::Upstream(UpstreamEnd::of(error))
    }

    fn short(words: &str) -> String {
        rules::Coerce::first_letters(words, 200).to_string()
    }

    /// One try at one port, up to the answer's head and an error's first bytes.
    fn attempt(&self, port: u16, clock: &mut RequestClock, watch: &mut Watch, client: &mut ClientSide) -> Result<Answer, Miss> {
        clock.leg_started();
        let began = clock.now();
        let mut socket = self.connect(port, watch, client)?;
        clock.connected(Some(began), None);
        socket.set_read_timeout(Some(Self::READ_TURN)).map_err(Miss::Socket)?;
        socket.set_write_timeout(Some(Duration::from_secs_f64(Self::SOCKET_LIMIT))).map_err(Miss::Socket)?;
        socket.set_nodelay(true).map_err(Miss::Socket)?;
        socket.write_all(&self.request_bytes(port)).map_err(Miss::Socket)?;
        clock.sent();
        let mut source = BufReader::with_capacity(32 * 1024, Stream::Plain(socket));
        let head = self.read_head(&mut source, watch, client)?;
        clock.answered();
        let mut body = AnswerBody::new(source, &head, &self.record.method);
        let error_raw = if head.status >= 400 { self.read_error(&mut body, clock, watch, client)? } else { Vec::new() };
        Ok(Answer { head, body, error_raw })
    }

    fn connect(&self, port: u16, watch: &mut Watch, client: &mut ClientSide) -> Result<TcpStream, Miss> {
        let dial = Dial { turn: Self::CONNECT_TURN, limit: Duration::from_secs_f64(Self::SOCKET_LIMIT) };
        dial.open::<Miss>(&self.output.upstream_host, port, &mut || watch.turn(client).map_err(Miss::Ended))
    }

    fn read_head(&self, source: &mut BufReader<Stream>, watch: &mut Watch, client: &mut ClientSide) -> Result<AnswerHead, Miss> {
        let mut reader = AnswerHeadReader::new();
        loop {
            match reader.read(source) {
                Ok(head) => return Ok(head),
                Err(error) if Waited::is(&error) => {
                    watch.waited_for_upstream(client)?;
                }
                Err(error) => return Err(Miss::Socket(error)),
            }
        }
    }

    fn read_error(
        &self,
        body: &mut AnswerBody<Stream>,
        clock: &mut RequestClock,
        watch: &mut Watch,
        client: &mut ClientSide,
    ) -> Result<Vec<u8>, Miss> {
        let mut kept = Vec::new();
        let mut piece = [0u8; 4096];
        loop {
            let room = (Self::ERROR_KEPT as usize).saturating_sub(kept.len()).min(piece.len());
            if room == 0 {
                return Ok(kept);
            }
            match body.read(piece.get_mut(..room).unwrap_or_default()) {
                Ok(0) => return Ok(kept),
                Ok(count) => {
                    clock.first_bytes();
                    kept.extend_from_slice(piece.get(..count).unwrap_or_default());
                }
                Err(error) if Waited::is(&error) => watch.waited_for_upstream(client)?,
                // What came of an error's body is what the journal keeps; a body that breaks off changes nothing about the status.
                Err(_) => return Ok(kept),
            }
        }
    }
}
