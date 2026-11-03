//! What comes back to the client: a machine's answer as it came, a provider's in the words its client speaks, a kept connection given back.

use super::Exchange;
use crate::provider_request::{Flavor, ProviderRequest};
use crate::record::CapturedAnswer;
use crate::relay::{ResponsesRelay, StreamRelay, TranslatedRelay, Translation, WholeRead, WholeRelay};
use crate::stop::{Ending, UpstreamEnd};
use crate::upstream::Answer;
use net::{KeptConnections, Stream, Target};
use rules::{AnthropicToChat, ChunkFold, OpenAiDialect, ResponsesToChat, StreamTranslator, UpstreamFailure};
use serde_json::{Value, json};
use std::io::Read;
use std::sync::Arc;
use std::time::Duration;
use wire::AnswerBody;

impl Exchange<'_> {
    pub(super) fn relay_machine(&mut self, mut answer: Answer) -> Result<(), Ending> {
        if answer.head.status >= 400 {
            let code = UpstreamFailure::code(&self.upstream_error_text);
            return self.tell_refusal(answer.head.status, code.as_ref());
        }
        self.relay_plain(&mut answer)
    }

    /// What a provider's answer comes back as, by who it was translated for.
    pub(super) fn relay_cloud(&mut self, request: &ProviderRequest, answer: &mut Answer) -> Result<(), Ending> {
        let status = answer.head.status;
        match &request.flavor {
            Flavor::SubscriptionResponses { client_stream } if status == 200 => self.relay_responses(answer, *client_stream),
            Flavor::SubscriptionChat { completion_id, model } if status == 200 => {
                self.relay_subscription_chat(answer, completion_id, model)
            }
            Flavor::Anthropic { completion_id, model } if status == 200 => self.relay_anthropic(answer, completion_id, model),
            _ if status >= 400 => self.tell_refusal(status, None),
            _ => self.relay_plain(answer),
        }
    }

    fn relay_plain(&mut self, answer: &mut Answer) -> Result<(), Ending> {
        if !self.client.head_sent() {
            self.send_answer_head(answer)?;
        }
        let streams = answer.is_event_stream();
        let (facts, clock, watch, client) = (&mut self.facts, &mut self.clock, &mut self.watch, &mut self.client);
        if streams {
            return StreamRelay::new(self.proxy, self.record).run(&mut answer.body, facts, clock, watch, client);
        }
        WholeRelay::new(self.proxy, self.record).run(&mut answer.body, facts, clock, watch, client)
    }

    /// A client that speaks Responses gets the Codex stream as it came, or, when it asked for a buffered answer, the final `response` as JSON.
    fn relay_responses(&mut self, answer: &mut Answer, client_stream: bool) -> Result<(), Ending> {
        if client_stream && !self.client.head_sent() {
            self.client.open_stream()?;
        }
        let (facts, clock, watch, client) = (&mut self.facts, &mut self.clock, &mut self.watch, &mut self.client);
        let tally =
            ResponsesRelay::new(self.proxy, self.record).run(&mut answer.body, client_stream, facts, clock, watch, client)?;
        if client_stream {
            return Ok(());
        }
        let done = tally.done;
        let last = tally.response.unwrap_or_else(|| json!({"error": {"message": "stream ended without response.completed"}}));
        let body = rules::PythonJson::spaced(&last).into_bytes();
        self.facts.bytes = body.len() as u64;
        if !self.client.head_sent() {
            let (status, reason) = if done { (200, "OK") } else { (502, "Bad Gateway") };
            let reply = self
                .client
                .reply_with_reason(status, reason)
                .field("Content-Type", "application/json")
                .field("Content-Length", body.len().to_string())
                .field("Connection", "close");
            self.client.send_head(&reply)?;
        }
        self.client.write(&body)
    }

    /// The Codex backend always streams. A client that did not ask for a stream gets the one chat completion OpenAI's API answers with.
    fn relay_subscription_chat(&mut self, answer: &mut Answer, completion_id: &str, model: &str) -> Result<(), Ending> {
        let mut whole = (!self.asked.streaming).then(ChunkFold::default);
        if whole.is_none() && !self.client.head_sent() {
            self.client.open_stream()?;
        }
        let mut translator = ResponsesToChat::new(completion_id, model, self.proxy.clock.epoch() as i64);
        self.relay_translated(answer, &mut translator, &mut whole)?;
        let Some(fold) = whole else {
            return Ok(());
        };
        if !fold.finished() {
            // A stream that ended without its last word is no answer: the client is told it failed, not handed half an answer as whole.
            return Err(Ending::Upstream(UpstreamEnd {
                words: "the model's stream ended before the answer was complete".to_string(),
                kind: "proxy_error",
            }));
        }
        let body = rules::PythonJson::spaced(&fold.completion()).into_bytes();
        self.facts.bytes = body.len() as u64;
        if !self.client.head_sent() {
            let reply = self
                .client
                .reply(200)
                .field("Content-Type", "application/json")
                .field("Content-Length", body.len().to_string())
                .field("Connection", "close")
                .field("X-Request-Id", self.record.id.as_bytes());
            self.client.send_head(&reply)?;
        }
        self.client.write(&body)
    }

    fn relay_anthropic(&mut self, answer: &mut Answer, completion_id: &str, model: &str) -> Result<(), Ending> {
        let now = self.proxy.clock.epoch() as i64;
        if answer.is_event_stream() {
            if !self.client.head_sent() {
                self.client.open_stream()?;
            }
            let mut translator = AnthropicToChat::new(completion_id, model, now);
            let ended = self.relay_translated(answer, &mut translator, &mut None);
            // A stream that was cut never reached its last chunk, where the usage rides: what the provider had said by then, billed all the same.
            if translator.used().known() {
                self.facts.usage_said_so_far = Some(translator.used().openai());
            }
            return ended;
        }
        let raw = WholeRead::of(
            self.proxy,
            self.record,
            &mut answer.body,
            &mut self.facts,
            &mut self.clock,
            &mut self.watch,
            &mut self.client,
        )?;
        let body = AnthropicToChat::whole(&raw, completion_id, model, now);
        self.facts.bytes = body.len() as u64;
        self.facts.response = CapturedAnswer::summary(&body);
        if !self.client.head_sent() {
            let reply = self
                .client
                .reply(200)
                .field("Content-Type", "application/json")
                .field("Content-Length", body.len().to_string())
                .field("Connection", "close");
            self.client.send_head(&reply)?;
        }
        self.client.write(&body)
    }

    fn relay_translated(
        &mut self,
        answer: &mut Answer,
        translator: &mut dyn StreamTranslator,
        whole: &mut Option<ChunkFold>,
    ) -> Result<(), Ending> {
        let (facts, clock, watch, client) = (&mut self.facts, &mut self.clock, &mut self.watch, &mut self.client);
        TranslatedRelay::new(self.proxy, self.record).run(
            &mut answer.body,
            Translation { translator, whole },
            facts,
            clock,
            watch,
            client,
        )
    }

    /// An upstream's refusal, in the dialect's words: its body and headers stay here, and the journal keeps its reason. `code` is what a cell called
    /// its refusal; a provider's code stays at the provider.
    fn tell_refusal(&mut self, status: u16, code: Option<&Value>) -> Result<(), Ending> {
        let (reason, _) = UpstreamFailure::summary(status, &self.upstream_error_text);
        let told = self.dialect.answer_error(status, &reason, code);
        self.facts.bytes += told.body.len() as u64;
        if self.client.head_sent() {
            let payload: Value = serde_json::from_slice(&told.body).unwrap_or(Value::Null);
            return self.client.send_stream_error(&payload);
        }
        self.client.send_told(&told, &self.record.id)
    }

    /// The upstream's status with the fields a consumer may see of it.
    fn send_answer_head(&mut self, answer: &Answer) -> Result<(), Ending> {
        let mut reply = self.client.reply_with_reason(answer.head.status, &answer.head.reason);
        for field in answer.head.headers.iter().filter(|field| OpenAiDialect::header_ok(&field.name)) {
            reply = reply.field(&field.name, field.value.clone());
        }
        reply = reply.field("X-Request-Id", self.record.id.as_bytes());
        if answer.is_event_stream() {
            reply = reply.field("X-Accel-Buffering", "no");
        }
        self.client.send_head(&reply.field("Connection", "close"))
    }

    /// A provider's connection is kept only after a clean relay. An answer read to its end goes back at once; one with bytes still to come is
    /// drained on a thread of its own, within its time, and nobody waits for it.
    pub(super) fn keep_connection(&self, target: Target, answer: Answer) {
        if answer.head.closes || answer.body.until_close() {
            return;
        }
        let kept = Arc::clone(&self.proxy.kept);
        let clock = Arc::clone(&self.proxy.clock);
        if answer.body.is_done() {
            KeptDrain::give_back(&kept, target, answer.body, clock.epoch());
            return;
        }
        let drained = std::thread::Builder::new().name("provider-drain".into()).spawn(move || {
            let mut body = answer.body;
            if KeptDrain::finish(&mut body) {
                KeptDrain::give_back(&kept, target, body, clock.epoch());
            }
        });
        // No thread for it: the connection goes with the failed spawn, and the next request opens its own.
        drop(drained);
    }
}

/// A provider's connection on its way back to the kept ones.
struct KeptDrain;

impl KeptDrain {
    /// How long the stream's closing bytes are waited for.
    const TURN: Duration = Duration::from_secs(1);
    /// How much of them is read.
    const MOST: usize = 65_536;

    /// Reads what is left of an answer: whether its end came.
    fn finish(body: &mut AnswerBody<Stream>) -> bool {
        let mut piece = [0u8; 16_384];
        let mut left = Self::MOST;
        while left > 0 {
            match body.read(&mut piece) {
                Ok(0) => break,
                Ok(count) => left = left.saturating_sub(count),
                Err(_) => return false,
            }
        }
        body.is_done()
    }

    /// Keeps the connection, when nothing is left in its buffer: bytes nobody asked for would be read as the next answer's.
    fn give_back(kept: &KeptConnections, target: Target, body: AnswerBody<Stream>, now: f64) {
        let source = body.into_source();
        if source.buffer().is_empty() {
            let stream = source.into_inner();
            if stream.set_read_timeout(Some(Self::TURN)).is_ok() {
                kept.give_back(target, stream, now);
            }
        }
    }
}
