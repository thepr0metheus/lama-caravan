//! The board's reader at work for a row that cannot read the request's pictures (`docs/vision-describe.md`, "The reading"):
//! each picture asked of the reader once — or taken from what it said of the same picture before (`captions.rs`) — and the
//! request sent on to the row with the captions where the pictures stood.
//!
//! The reader is asked the way any client's request is served: a request of its own, walked down the reader's pool by an
//! `Exchange` of its own, so its queue, its place on a machine, its account, its limits, its spend and its record are the ones
//! every request has, and the board sees it as the reader's (`readerFor`). Its answer comes back over a socket pair on this
//! machine's loopback and is read the way an upstream's answer is read. The request it reads for waits, and is watched while
//! it waits: a stop from the board, or a streaming client gone, ends the wait at once and shuts the loopback. The reader's
//! request sees that while it waits in its model's queue and leaves it; a description its model is already writing is
//! finished and dropped, because a request that is not a stream is not watched for its client while its answer comes.
//!
//! A reading is whole or it is not: a picture the reader did not read ends the request with the reader's own words, and
//! nothing is sent to the row — a row that cannot read pictures is never sent one, and never sent a caption of nothing.

use super::{Asked, Exchange};
use crate::client::ClientSide;
use crate::proxy::Proxy;
use crate::record::{ReadFacts, RequestRecord};
use crate::stop::{Ending, Waited};
use files::Settings;
use net::Sha256;
use rules::{Pick, Picture, Pool, Reading, RequestJson, RequestSummary, Source};
use std::io::{self, BufReader, Read};
use std::net::{Shutdown, TcpListener, TcpStream};
use std::sync::Arc;
use std::time::Duration;
use wire::{AnswerBody, AnswerHeadReader, Headers};

impl Exchange<'_> {
    /// The path the reader is asked on: a chat, which every model that reads pictures answers.
    const READER_PATH: &'static str = "/v1/chat/completions";

    /// The body a row is sent: the request as it came, or — for a row that cannot read its pictures — the request with the
    /// reader's captions where the pictures stood, read once for the request whichever row it goes on to.
    pub(super) fn body_for(&mut self, read_first: bool) -> Result<Vec<u8>, Ending> {
        if !read_first {
            return Ok(self.asked.body.clone());
        }
        if let Some(body) = &self.captioned {
            return Ok(body.clone());
        }
        let body = self.read_pictures()?;
        self.captioned = Some(body.clone());
        Ok(body)
    }

    /// Every picture read, and the request written again with the captions. Whatever ends it ends the request.
    fn read_pictures(&mut self) -> Result<Vec<u8>, Ending> {
        // A row marked to be read for in a request the entry said nothing reads for is two decisions that disagree: a bug here.
        let Some(reading) = self.reading.take() else {
            return Err(Ending::Inside("a row to be read for, in a request with no reading".to_string()));
        };
        if let Some(refusal) = reading.elsewhere() {
            return Err(Ending::Refused(refusal));
        }
        // Said before the reader is asked, so that a reading that fails is recorded as the reader's: the board lights the
        // reader's cable by this while it works and after, and the record keeps it either way.
        self.facts.reading =
            Some(ReadFacts { reader: reading.reader.model().to_string(), pictures: reading.pictures.len(), kept: 0 });
        self.say_reading();
        let mut captions = Vec::with_capacity(reading.pictures.len());
        for picture in &reading.pictures {
            let Source::Inside(url) = &picture.source else {
                // `elsewhere()` said every picture is inside: a picture that is not is the same bug as above.
                return Err(Ending::Inside("a picture to read that is not inside the request".to_string()));
            };
            let key = reading.reader.key(&Sha256::of(url.as_bytes()));
            let now = self.proxy.clock.epoch();
            if let Some(words) = self.proxy.captions.get(&key, now) {
                if let Some(read) = self.facts.reading.as_mut() {
                    read.kept += 1;
                }
                captions.push(words);
                continue;
            }
            let words = self.ask_reader(&reading, picture)?;
            self.proxy.captions.keep(key, words.clone(), self.proxy.clock.epoch());
            captions.push(words);
        }
        self.say_reading();
        let payload = RequestJson::read(&self.asked.body)
            .ok_or_else(|| Ending::Inside("the request read before does not read now".to_string()))?;
        let rewritten = reading
            .rewritten(&payload, &captions)
            .ok_or_else(|| Ending::Inside("a caption with no picture to stand in for".to_string()))?;
        serde_json::to_vec(&rewritten).map_err(|error| Ending::Inside(format!("the request with its captions: {error}")))
    }

    /// What the reader read so far, on the board's running record.
    fn say_reading(&self) {
        if let Some(read) = &self.facts.reading {
            self.update(read.fields());
        }
    }

    /// One picture asked of the reader, through the reader's pool: its words, or the refusal that says why there are none.
    fn ask_reader(&mut self, reading: &Reading, picture: &Picture) -> Result<String, Ending> {
        let question = reading.question(picture).ok_or_else(|| Ending::Inside("a question about no picture".to_string()))?;
        let body = serde_json::to_vec(&question).map_err(|error| Ending::Inside(format!("the reader's question: {error}")))?;
        let pool = match self.settings.models.for_request(&self.record.route.deny, reading.reader.model(), Self::READER_PATH) {
            Pick::Pool(pool) => *pool,
            Pick::Refused(refusal) => {
                let why = format!("the caravan cannot ask it now: {}", refusal.error.message);
                return Err(Ending::Refused(reading.failed(picture, &why)));
            }
            Pick::Unsure => return Err(Ending::Refused(reading.failed(picture, "the caravan cannot read its settings now"))),
        };
        let record = RequestRecord {
            id: self.proxy.new_request_id(),
            method: "POST".to_string(),
            path: Self::READER_PATH.to_string(),
            client: self.record.client.clone(),
            started: self.proxy.clock.epoch(),
            route: self.record.route.clone(),
            pool_id: pool.id.clone(),
            pool_name: pool.name.clone(),
            summary: RequestSummary::of(&body, "application/json"),
            client_deadline: self.record.client_deadline,
            reader_for: Some(self.record.id.clone()),
        };
        let call = ReaderCall { proxy: self.proxy, settings: Arc::clone(&self.settings), record, pool, body };
        let (status, answer) = call.ask(&mut || self.watch.turn(&mut self.client))?;
        Reading::words(status, &answer).map_err(|why| Ending::Refused(reading.failed(picture, &why)))
    }
}

/// The reader's request: served by an `Exchange` of its own, on a thread of its own, its answer read back over the loopback.
struct ReaderCall<'p> {
    proxy: &'p Proxy,
    settings: Arc<Settings>,
    record: RequestRecord,
    pool: Pool,
    body: Vec<u8>,
}

impl ReaderCall<'_> {
    /// How long one read of the answer waits before the request it reads for is looked at again.
    const LOOK_TURN: Duration = Duration::from_secs(1);
    /// The most of an answer that is read: a description is words, not a file.
    const ANSWER_MAX: usize = 4 * 1024 * 1024;

    /// The reader's status and body. `look` is the waiting request's look-out, asked between reads: what it says ends the
    /// reading, and the socket is shut, so that the reader's own request — while it still waits in its model's queue — sees
    /// its client gone and leaves.
    fn ask(self, look: &mut dyn FnMut() -> Result<(), Ending>) -> Result<(u16, Vec<u8>), Ending> {
        let (near, far) = Self::pair().map_err(|error| Ending::Inside(format!("the reader's socket pair: {error}")))?;
        let Self { proxy, settings, record, pool, body } = self;
        let mut headers = Headers::new();
        headers.push("Content-Type", "application/json");
        let asked = Asked { headers, target: Exchange::READER_PATH.to_string(), body, streaming: false };
        std::thread::scope(|scope| {
            let record = &record;
            let clock = Arc::clone(&proxy.clock);
            let served =
                scope.spawn(move || Exchange::new(proxy, settings, record, pool, asked, ClientSide::new(far, clock)).run());
            let answer = Self::answer_of(&near, look);
            if answer.is_err() {
                // A close changes nothing for a socket already shut; what matters is that the reader's request sees it.
                drop(near.shutdown(Shutdown::Both));
            }
            // `Exchange::run` keeps its own panics, so the thread ends with its request's record either way.
            drop(served.join());
            answer
        })
    }

    /// Two ends of one connection on this machine's loopback: the near one is read here, the far one is the reader's client.
    fn pair() -> io::Result<(TcpStream, TcpStream)> {
        let listener = TcpListener::bind(("127.0.0.1", 0))?;
        let near = TcpStream::connect(listener.local_addr()?)?;
        let (far, _) = listener.accept()?;
        near.set_read_timeout(Some(Self::LOOK_TURN))?;
        Ok((near, far))
    }

    /// The answer as it comes over `near`, the waiting request looked at between reads.
    fn answer_of(near: &TcpStream, look: &mut dyn FnMut() -> Result<(), Ending>) -> Result<(u16, Vec<u8>), Ending> {
        let unread = |error: io::Error| Ending::Inside(format!("the reader's answer does not read: {error}"));
        let mut source = BufReader::new(near.try_clone().map_err(unread)?);
        let mut heads = AnswerHeadReader::new();
        let head = loop {
            match heads.read(&mut source) {
                Ok(head) => break head,
                Err(error) if Waited::is(&error) => look()?,
                Err(error) => return Err(unread(error)),
            }
        };
        let mut body = AnswerBody::new(source, &head, "POST");
        let mut out = Vec::new();
        let mut piece = [0u8; 16 * 1024];
        loop {
            match body.read(&mut piece) {
                Ok(0) => return Ok((head.status, out)),
                Ok(count) => {
                    out.extend_from_slice(piece.get(..count).unwrap_or_default());
                    if out.len() > Self::ANSWER_MAX {
                        return Err(Ending::Inside("the reader's answer is longer than any description".to_string()));
                    }
                }
                Err(error) if Waited::is(&error) => look()?,
                Err(error) => return Err(unread(error)),
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;

    #[test]
    fn an_answer_is_read_whole_whatever_its_framing() {
        for (raw, status, said) in [
            ("HTTP/1.1 200 OK\r\nContent-Length: 5\r\n\r\nhello", 200, "hello"),
            ("HTTP/1.1 502 Bad Gateway\r\nTransfer-Encoding: chunked\r\n\r\n3\r\nbad\r\n0\r\n\r\n", 502, "bad"),
            ("HTTP/1.1 200 OK\r\nConnection: close\r\n\r\nuntil the end", 200, "until the end"),
        ] {
            let (near, mut far) = ReaderCall::pair().unwrap();
            far.write_all(raw.as_bytes()).unwrap();
            drop(far);
            let answer = ReaderCall::answer_of(&near, &mut || Ok(())).unwrap();
            assert_eq!((answer.0, String::from_utf8(answer.1).unwrap()), (status, said.to_string()), "{raw}");
        }
    }

    #[test]
    fn a_wait_looks_at_the_request_and_its_end_ends_the_reading() {
        let (near, far) = ReaderCall::pair().unwrap();
        let mut looked = 0;
        let ended = ReaderCall::answer_of(&near, &mut || {
            looked += 1;
            Err(Ending::ClientGone)
        });
        assert!(matches!(ended, Err(Ending::ClientGone)), "{ended:?}");
        assert_eq!(looked, 1, "the first wait looked once, and what it saw ended the reading");
        drop(far);
    }
}
