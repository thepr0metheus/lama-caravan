//! A request on its way to a provider: the cloud part of the leg loop in `proxy()`. What goes out depends on who
//! it goes to; everything else the provider's leg shares with a machine's.

use crate::client::ClientSide;
use crate::clock::RequestClock;
use crate::provider_request::ProviderRequest;
use crate::proxy::Proxy;
use crate::record::RequestRecord;
use crate::stop::{Ending, Waited};
use crate::upstream::Answer;
use crate::watch::Watch;
use net::{Dial, Stream};
use serde_json::json;
use std::io::{self, BufReader, Read, Write};
use std::time::Duration;
use wire::{AnswerBody, AnswerHead, AnswerHeadReader, Headers};

/// What failed on the way to a provider.
pub enum Miss {
    /// The socket failed: the pool's next row may serve.
    Socket(io::Error),
    /// The request ended meanwhile.
    Ended(Ending),
}

impl From<Ending> for Miss {
    fn from(ending: Ending) -> Self {
        Self::Ended(ending)
    }
}

impl From<io::Error> for Miss {
    fn from(error: io::Error) -> Self {
        Self::Socket(error)
    }
}

/// One leg's call: a connection, kept or new, the request, the answer's head and an error's first bytes.
pub struct ProviderCall<'a> {
    proxy: &'a Proxy,
    record: &'a RequestRecord,
    request: &'a ProviderRequest,
}

impl<'a> ProviderCall<'a> {
    const ERROR_KEPT: usize = 4096;
    /// How long one wait may take before the client is looked at again.
    const TURN: Duration = Duration::from_secs(2);
    /// Python's `timeout=600` on the connection.
    const SOCKET_LIMIT: f64 = 600.0;

    /// The call of `request`.
    pub fn new(proxy: &'a Proxy, record: &'a RequestRecord, request: &'a ProviderRequest) -> Self {
        Self { proxy, record, request }
    }

    /// The answer. A kept connection the provider closed while it sat idle has answered nothing, so the request goes again on a fresh one,
    /// once: the fresh one is not kept.
    pub fn ask(&self, clock: &mut RequestClock, watch: &mut Watch, client: &mut ClientSide) -> Result<Answer, Miss> {
        clock.leg_started();
        let now = self.proxy.clock.epoch();
        if let Some(kept) = self.proxy.kept.take(&self.request.target, now) {
            clock.connected(None, Some(true));
            match self.on(kept, clock, watch, client) {
                Err(Miss::Socket(error)) if Stream::is_stale_error(&error) => {
                    let said = rules::Coerce::first_letters(&error.to_string(), 200).to_string();
                    self.proxy.recorder.event(
                        "upstream_reconnect",
                        &self.record.route.label,
                        &self.record.id,
                        None,
                        json!({"error": said}),
                    );
                }
                other => return other,
            }
        }
        let began = clock.now();
        let fresh = self.connect(watch, client)?;
        clock.connected(Some(began), Some(false));
        self.on(fresh, clock, watch, client)
    }

    fn connect(&self, watch: &mut Watch, client: &mut ClientSide) -> Result<Stream, Miss> {
        let target = &self.request.target;
        let dial = Dial { turn: Self::TURN, limit: Duration::from_secs_f64(Self::SOCKET_LIMIT) };
        let socket = dial.open::<Miss>(&target.host, target.port, &mut || watch.turn(client).map_err(Miss::Ended))?;
        socket.set_nodelay(true)?;
        socket.set_read_timeout(Some(Self::TURN))?;
        socket.set_write_timeout(Some(Duration::from_secs_f64(Self::SOCKET_LIMIT)))?;
        if !target.tls {
            return Ok(Stream::Plain(socket));
        }
        let roots = self.proxy.access.roots()?;
        roots.wrap::<Miss>(socket, &target.host, &mut || watch.turn(client).map_err(Miss::Ended))
    }

    fn on(
        &self,
        mut stream: Stream,
        clock: &mut RequestClock,
        watch: &mut Watch,
        client: &mut ClientSide,
    ) -> Result<Answer, Miss> {
        stream.set_read_timeout(Some(Self::TURN))?;
        stream.write_all(&self.request.bytes(&self.record.method))?;
        stream.flush()?;
        clock.sent();
        let mut source = BufReader::with_capacity(32 * 1024, stream);
        let head = self.read_head(&mut source, watch, client)?;
        clock.answered();
        let mut body = AnswerBody::new(source, &head, &self.record.method);
        let error_raw = if head.status >= 400 { self.read_error(&mut body, clock, watch, client)? } else { Vec::new() };
        Ok(Answer { head, body, error_raw })
    }

    fn read_head(&self, source: &mut BufReader<Stream>, watch: &mut Watch, client: &mut ClientSide) -> Result<AnswerHead, Miss> {
        let mut reader = AnswerHeadReader::new();
        loop {
            match reader.read(source) {
                Ok(head) => return Ok(head),
                Err(error) if Waited::is(&error) => watch.waited_for_upstream(client)?,
                Err(error) => return Err(error.into()),
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
        let mut kept = vec![0u8; Self::ERROR_KEPT];
        let mut held = 0;
        while held < Self::ERROR_KEPT {
            match body.read(kept.get_mut(held..).unwrap_or_default()) {
                Ok(0) => break,
                Ok(count) => {
                    clock.first_bytes();
                    held += count;
                }
                Err(error) if Waited::is(&error) => watch.waited_for_upstream(client)?,
                // What came of an error's body is what the journal keeps; a body that breaks off changes nothing about the status.
                Err(_) => break,
            }
        }
        kept.truncate(held);
        Ok(kept)
    }
}

/// What a request's fields say of the provider's windows: a subscription's every answer states them.
pub struct AnswerWindows;

impl AnswerWindows {
    /// The windows `headers` state.
    pub fn of(headers: &Headers) -> Vec<rules::UsageWindow> {
        rules::UsageWindow::from_headers(|name| headers.get(name))
    }
}
