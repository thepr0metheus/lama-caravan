//! An answer on its way to the client: an event stream line by line, or a whole answer piece by piece.

use crate::client::ClientSide;
use crate::clock::RequestClock;
use crate::proxy::Proxy;
use crate::record::{CapturedAnswer, Facts, RequestRecord};
use crate::stop::{Ending, UpstreamEnd, Waited};
use crate::watch::Watch;
use net::Stream;
use rules::{ChunkFold, ResponsesTally, StreamTranslator};
use serde_json::{Map, Value, json};
use std::io::Read;
use wire::{AnswerBody, Lines, Next};

/// What every relay does around each piece: counts it, notes the first byte, tells the board once a second.
struct Progress<'a> {
    proxy: &'a Proxy,
    record: &'a RequestRecord,
    last_board_write: f64,
}

impl<'a> Progress<'a> {
    fn new(proxy: &'a Proxy, record: &'a RequestRecord) -> Self {
        Self { proxy, record, last_board_write: 0.0 }
    }

    fn piece_came(&self, facts: &mut Facts, clock: &mut RequestClock, size: usize) {
        clock.first_bytes();
        if facts.first_byte_ms.is_none() {
            facts.first_byte_ms = Some(((self.proxy.clock.epoch() - self.record.started) * 1000.0).round() as i64);
        }
        facts.bytes += size as u64;
        facts.chunks += 1;
    }

    fn tell_board(&mut self, facts: &Facts) {
        let now = self.proxy.clock.epoch();
        if now - self.last_board_write < 1.0 {
            return;
        }
        self.last_board_write = now;
        let mut patch = Map::new();
        patch.insert("bytes".into(), json!(facts.bytes));
        patch.insert("chunks".into(), json!(facts.chunks));
        patch.insert("firstByteMs".into(), json!(facts.first_byte_ms));
        patch.insert("elapsedMs".into(), json!(((now - self.record.started) * 1000.0).round() as i64));
        if facts.stream.events > 0 {
            patch.insert("stream".into(), facts.stream.live_json());
        }
        self.proxy.board.update_active(self.record.route.port, &self.record.id, Value::Object(patch));
    }
}

/// An event stream, passed on as it comes, each event read for the record.
pub struct StreamRelay<'a> {
    progress: Progress<'a>,
}

impl<'a> StreamRelay<'a> {
    /// The line that ends a stream.
    const DONE: &'static [u8] = b"data: [DONE]";

    /// The relay of `record`'s answer.
    pub fn new(proxy: &'a Proxy, record: &'a RequestRecord) -> Self {
        Self { progress: Progress::new(proxy, record) }
    }

    /// Passes the stream on, until it ends or `[DONE]` comes. Stopping at `[DONE]` is this side's choice, so the frame the client
    /// is left with must be complete: the blank line that ends the event is still in the socket when the loop leaves, and a parser
    /// that follows the format would wait for it until the connection closes.
    pub fn run(
        &mut self,
        body: &mut AnswerBody<Stream>,
        facts: &mut Facts,
        clock: &mut RequestClock,
        watch: &mut Watch,
        client: &mut ClientSide,
    ) -> Result<(), Ending> {
        let mut lines = Lines::new(body);
        loop {
            let line = match lines.next_line() {
                Ok(Next::Line(line)) => line,
                Ok(Next::End) => return Ok(()),
                Err(error) if Waited::is(&error) => {
                    watch.waited_for_upstream(client)?;
                    continue;
                }
                Err(error) => return Err(Ending::Upstream(UpstreamEnd::of(&error))),
            };
            watch.byte_came();
            self.progress.piece_came(facts, clock, line.len());
            facts.stream.add_line(&line);
            client.write(&line)?;
            watch.check_stop()?;
            self.progress.tell_board(facts);
            if line.windows(Self::DONE.len()).any(|piece| piece == Self::DONE) {
                let trailing = line.iter().rev().take_while(|byte| **byte == b'\n').count();
                let missing = 2usize.saturating_sub(trailing);
                if missing > 0 {
                    client.write(b"\n\n".get(..missing).unwrap_or_default())?;
                    facts.bytes += missing as u64;
                }
                return Ok(());
            }
        }
    }
}

/// A whole answer, passed on as it comes, its first megabyte kept for the record's summary.
pub struct WholeRelay<'a> {
    progress: Progress<'a>,
}

impl<'a> WholeRelay<'a> {
    /// The most of an answer kept for its summary.
    const CAPTURE_LIMIT: usize = 1024 * 1024;
    /// The most read at a time.
    const PIECE: usize = 64 * 1024;

    /// The relay of `record`'s answer.
    pub fn new(proxy: &'a Proxy, record: &'a RequestRecord) -> Self {
        Self { progress: Progress::new(proxy, record) }
    }

    /// Passes the answer on, until it ends.
    pub fn run(
        &mut self,
        body: &mut AnswerBody<Stream>,
        facts: &mut Facts,
        clock: &mut RequestClock,
        watch: &mut Watch,
        client: &mut ClientSide,
    ) -> Result<(), Ending> {
        let mut captured = Vec::new();
        let mut piece = vec![0u8; Self::PIECE];
        loop {
            let count = match body.read(&mut piece) {
                Ok(0) => break,
                Ok(count) => count,
                Err(error) if Waited::is(&error) => {
                    watch.waited_for_upstream(client)?;
                    continue;
                }
                Err(error) => return Err(Ending::Upstream(UpstreamEnd::of(&error))),
            };
            let bytes = piece.get(..count).unwrap_or_default();
            watch.byte_came();
            self.progress.piece_came(facts, clock, count);
            let room = Self::CAPTURE_LIMIT.saturating_sub(captured.len()).min(count);
            captured.extend_from_slice(bytes.get(..room).unwrap_or_default());
            client.write(bytes)?;
            watch.check_stop()?;
            self.progress.tell_board(facts);
        }
        facts.response = CapturedAnswer::summary(&captured);
        Ok(())
    }
}

/// What a stream is translated with.
pub struct Translation<'t> {
    /// The provider's words to chunks.
    pub translator: &'t mut dyn StreamTranslator,
    /// The fold, when the client asked for no stream.
    pub whole: &'t mut Option<ChunkFold>,
}

/// What a translated stream's lines are read for: a provider's stream becomes the chunks a chat client reads.
pub struct TranslatedRelay<'a> {
    progress: Progress<'a>,
}

impl<'a> TranslatedRelay<'a> {
    /// The relay of `record`'s answer.
    pub fn new(proxy: &'a Proxy, record: &'a RequestRecord) -> Self {
        Self { progress: Progress::new(proxy, record) }
    }

    /// One chunk: counted and folded for the record, then to the client, or into the one answer a client that asked for no stream gets.
    fn emit(
        &mut self,
        chunk: &[u8],
        whole: &mut Option<ChunkFold>,
        facts: &mut Facts,
        clock: &mut RequestClock,
        watch: &mut Watch,
        client: &mut ClientSide,
    ) -> Result<(), Ending> {
        self.progress.piece_came(facts, clock, chunk.len());
        facts.stream.add_translated(chunk);
        match whole {
            Some(fold) => fold.add(chunk),
            None => client.write(chunk)?,
        }
        watch.check_stop()?;
        self.progress.tell_board(facts);
        Ok(())
    }

    /// Reads the stream through the translation.
    pub fn run(
        &mut self,
        body: &mut AnswerBody<Stream>,
        translation: Translation<'_>,
        facts: &mut Facts,
        clock: &mut RequestClock,
        watch: &mut Watch,
        client: &mut ClientSide,
    ) -> Result<(), Ending> {
        let Translation { translator, whole } = translation;
        self.emit(&translator.opening(), whole, facts, clock, watch, client)?;
        let mut lines = Lines::new(body);
        while !translator.ended() {
            let line = match lines.next_line() {
                Ok(Next::Line(line)) => line,
                Ok(Next::End) => break,
                Err(error) if Waited::is(&error) => {
                    watch.waited_for_upstream(client)?;
                    continue;
                }
                Err(error) => return Err(Ending::Upstream(UpstreamEnd::of(&error))),
            };
            watch.byte_came();
            if let Some(chunk) = translator.line(&line) {
                self.emit(&chunk, whole, facts, clock, watch, client)?;
            }
        }
        self.emit(translator.closing(), whole, facts, clock, watch, client)
    }
}

/// A Responses stream for a client that speaks Responses: event by event as it came, its tallies kept for the journal.
pub struct ResponsesRelay<'a> {
    progress: Progress<'a>,
}

impl<'a> ResponsesRelay<'a> {
    /// The relay of `record`'s answer.
    pub fn new(proxy: &'a Proxy, record: &'a RequestRecord) -> Self {
        Self { progress: Progress::new(proxy, record) }
    }

    /// Reads the stream, passing it on when `to_client`; what it said comes back. A client that asked for a buffered answer gets the final
    /// `response` of `response.completed`.
    pub fn run(
        &mut self,
        body: &mut AnswerBody<Stream>,
        to_client: bool,
        facts: &mut Facts,
        clock: &mut RequestClock,
        watch: &mut Watch,
        client: &mut ClientSide,
    ) -> Result<ResponsesTally, Ending> {
        let mut tally = ResponsesTally::default();
        let mut lines = Lines::new(body);
        loop {
            let line = match lines.next_line() {
                Ok(Next::Line(line)) => line,
                Ok(Next::End) => return Ok(tally),
                Err(error) if Waited::is(&error) => {
                    watch.waited_for_upstream(client)?;
                    continue;
                }
                Err(error) => return Err(Ending::Upstream(UpstreamEnd::of(&error))),
            };
            watch.byte_came();
            self.progress.piece_came(facts, clock, line.len());
            tally.line(&line);
            facts.stream.take_tally(&tally);
            if to_client {
                client.write(&line)?;
                watch.check_stop()?;
                self.progress.tell_board(facts);
            }
        }
    }
}

/// An answer read whole before it is translated.
pub struct WholeRead;

impl WholeRead {
    const PIECE: usize = 64 * 1024;

    /// All of `body`, the first byte noted.
    pub fn of(
        proxy: &Proxy,
        record: &RequestRecord,
        body: &mut AnswerBody<Stream>,
        facts: &mut Facts,
        clock: &mut RequestClock,
        watch: &mut Watch,
        client: &mut ClientSide,
    ) -> Result<Vec<u8>, Ending> {
        let mut raw = Vec::new();
        let mut piece = vec![0u8; Self::PIECE];
        loop {
            match body.read(&mut piece) {
                Ok(0) => return Ok(raw),
                Ok(count) => {
                    clock.first_bytes();
                    if facts.first_byte_ms.is_none() {
                        facts.first_byte_ms = Some(((proxy.clock.epoch() - record.started) * 1000.0).round() as i64);
                    }
                    watch.byte_came();
                    raw.extend_from_slice(piece.get(..count).unwrap_or_default());
                }
                Err(error) if Waited::is(&error) => watch.waited_for_upstream(client)?,
                Err(error) => return Err(Ending::Upstream(UpstreamEnd::of(&error))),
            }
        }
    }
}
