//! How many requests a model takes at once.

use crate::clock::Clock;
use crate::log::Log;
use crate::proxy::Proxy;
use net::Dial;
use rules::{MachineOutput, UpstreamType};
use serde_json::{Map, Value, json};
use std::collections::BTreeMap;
use std::io::{self, BufReader, Read, Write};
use std::sync::{Arc, Mutex, PoisonError};
use std::time::Duration;
use wire::{AnswerBody, AnswerHeadReader, Percent};

/// A number the server said, and when it was asked.
#[derive(Debug, Clone, Copy)]
struct Said {
    places: Option<u32>,
    at: f64,
}

/// The server's word on a model's places, kept a few seconds: a request's admission must not cost an HTTP call each. A question
/// that fails keeps the last number known: its latency flaps under load, and "unknown" every other second would read as a
/// model that lost its places.
pub struct MachinePlaces {
    clock: Arc<dyn Clock>,
    said: Mutex<BTreeMap<String, Said>>,
}

impl MachinePlaces {
    /// Seconds a number stands.
    const TTL: f64 = 5.0;
    /// How long a server is given to answer on a request's way.
    const TIMEOUT: Duration = Duration::from_millis(800);
    /// How long it is given by the watch, with nobody waiting: `/slots` of a server at work can take longer.
    const WATCH_TIMEOUT: Duration = Duration::from_secs(3);
    /// The most of its answer that is read.
    const ANSWER_MAX: u64 = 1024 * 1024;

    /// The word kept on these clocks.
    pub fn new(clock: Arc<dyn Clock>) -> Self {
        Self { clock, said: Mutex::new(BTreeMap::new()) }
    }

    /// The places of `output`'s model, or `None` when nothing has been said of them: the policy's number stands in then.
    pub fn of(&self, output: &MachineOutput) -> Option<u32> {
        self.asked_within(output, Self::TIMEOUT)
    }

    fn asked_within(&self, output: &MachineOutput, patience: Duration) -> Option<u32> {
        let group = output.group();
        let now = self.clock.epoch();
        {
            let said = self.said.lock().unwrap_or_else(PoisonError::into_inner);
            if let Some(kept) = said.get(&group).filter(|kept| now - kept.at < Self::TTL) {
                return kept.places;
            }
        }
        let asked = Self::ask(output, patience);
        let mut said = self.said.lock().unwrap_or_else(PoisonError::into_inner);
        if asked.is_none()
            && let Some(known) = said.get(&group).and_then(|kept| kept.places)
        {
            return Some(known);
        }
        said.insert(group, Said { places: asked, at: now });
        asked
    }

    /// The numbers said so far, by the queue's name: what the board reads as `slotTotals`, and finds a model's by its output's `slotGroup`.
    pub fn totals(&self) -> Value {
        let said = self.said.lock().unwrap_or_else(PoisonError::into_inner);
        let known = said.iter().filter_map(|(group, kept)| kept.places.map(|places| (group.clone(), json!(places))));
        Value::Object(known.collect::<Map<String, Value>>())
    }

    /// `/slots` is llama.cpp's, and an engine next to the cells has none: it is not asked what it cannot answer.
    fn ask(output: &MachineOutput, patience: Duration) -> Option<u32> {
        match output.kind {
            UpstreamType::Machine => {
                let path = format!("/v1/models/{}", Percent::encode(&output.name));
                Self::places_in(&serde_json::from_slice(&Self::answer(output, &path, patience)?).ok()?)
            }
            UpstreamType::Llama => Self::slots_in(&serde_json::from_slice(&Self::answer(output, "/slots", patience)?).ok()?),
            UpstreamType::Engine | UpstreamType::Cloud => None,
        }
    }

    /// `caravan.slots` of a model's answer; zero places is no number to wait for: the request goes, and the entry answers that
    /// the model is not running, at once.
    fn places_in(said: &Value) -> Option<u32> {
        let slots = said.get("caravan")?.get("slots")?.as_u64()?;
        u32::try_from(slots).ok().filter(|slots| *slots > 0)
    }

    /// A cell's `/slots`: one row for each place.
    fn slots_in(said: &Value) -> Option<u32> {
        u32::try_from(said.as_array()?.len()).ok()
    }

    fn answer(output: &MachineOutput, path: &str, patience: Duration) -> Option<Vec<u8>> {
        let dial = Dial { turn: patience, limit: patience };
        let mut socket = dial.open::<io::Error>(&output.upstream_host, output.upstream_port, &mut || Ok(())).ok()?;
        socket.set_read_timeout(Some(patience)).ok()?;
        socket.set_write_timeout(Some(patience)).ok()?;
        let question = format!(
            "GET {path} HTTP/1.1\r\nHost: {}:{}\r\nAccept-Encoding: identity\r\nConnection: close\r\n\r\n",
            output.upstream_host, output.upstream_port
        );
        socket.write_all(question.as_bytes()).ok()?;
        let mut source = BufReader::new(socket);
        let head = AnswerHeadReader::new().read(&mut source).ok()?;
        if head.status != 200 {
            return None;
        }
        let mut body = Vec::new();
        AnswerBody::new(source, &head, "GET").take(Self::ANSWER_MAX).read_to_end(&mut body).ok()?;
        Some(body)
    }
}

/// Every model's places asked while nobody calls it, so that the board can say them before the first request: an idle model's strip said "0 of ?" (the owner, 2026-10-26).
/// One thread, one question at a time: a machine that is off costs its timeout here and no request anything. A model the board knows stands still has nothing to say.
pub struct PlacesWatch;

impl PlacesWatch {
    const BEAT: Duration = Duration::from_secs(10);

    /// The watch, on a thread of its own.
    pub fn start(proxy: &Arc<Proxy>) {
        let proxy = Arc::clone(proxy);
        let watch = std::thread::Builder::new().name("places-watch".into()).spawn(move || {
            while !proxy.drain.is_on() {
                let settings = proxy.settings.current();
                for output in settings.models.callable_outputs().filter(|output| !output.stopped) {
                    proxy.places.asked_within(output, MachinePlaces::WATCH_TIMEOUT);
                }
                std::thread::sleep(Self::BEAT);
            }
        });
        if let Err(error) = watch {
            Log::line(&format!("caravan-proxy: no thread for the places' watch: {error}"));
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use std::io::BufRead;

    #[test]
    fn reads_the_places_a_model_says() {
        assert_eq!(MachinePlaces::places_in(&json!({"caravan": {"slots": 4, "busy": 1}})), Some(4));
        assert_eq!(MachinePlaces::places_in(&json!({"caravan": {"slots": 0}})), None);
        assert_eq!(MachinePlaces::places_in(&json!({"caravan": {"slots": "4"}})), None);
        assert_eq!(MachinePlaces::places_in(&json!({"caravan": {"slots": -1}})), None);
        assert_eq!(MachinePlaces::places_in(&json!({"caravan": {}})), None);
        assert_eq!(MachinePlaces::places_in(&json!({})), None);
    }

    /// A clock the test moves.
    struct HandClock(Mutex<f64>);

    impl Clock for HandClock {
        fn epoch(&self) -> f64 {
            *self.0.lock().unwrap()
        }

        fn monotonic(&self) -> f64 {
            self.epoch()
        }

        fn thread_cpu(&self) -> Option<f64> {
            None
        }
    }

    /// A server of one answer, which writes down what it was asked; its answer can be changed, and it can stop answering.
    struct Asked {
        port: u16,
        questions: Arc<Mutex<Vec<String>>>,
        answer: Arc<Mutex<Option<String>>>,
    }

    impl Asked {
        fn server(first: &str) -> Self {
            let listener = std::net::TcpListener::bind(("127.0.0.1", 0)).unwrap();
            let port = listener.local_addr().unwrap().port();
            let questions = Arc::new(Mutex::new(Vec::new()));
            let answer = Arc::new(Mutex::new(Some(first.to_string())));
            let (asked, said) = (Arc::clone(&questions), Arc::clone(&answer));
            std::thread::spawn(move || {
                for stream in listener.incoming() {
                    let mut stream = stream.unwrap();
                    let mut head = String::new();
                    BufReader::new(&stream).read_line(&mut head).unwrap();
                    asked.lock().unwrap().push(head.trim().to_string());
                    let Some(text) = said.lock().unwrap().clone() else {
                        continue;
                    };
                    write!(stream, "{text}").unwrap();
                }
            });
            Self { port, questions, answer }
        }

        fn ok(body: &str) -> String {
            format!("HTTP/1.1 200 OK\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}", body.len())
        }

        fn output(&self, kind: &str) -> MachineOutput {
            MachineOutput::read(&json!({"id": "o", "upstreamType": kind, "upstreamModel": "a b", "upstreamHost": "127.0.0.1", "upstreamPort": self.port})).unwrap()
        }

        fn questions(&self) -> Vec<String> {
            self.questions.lock().unwrap().clone()
        }
    }

    fn at(moment: f64) -> (Arc<HandClock>, MachinePlaces) {
        let clock = Arc::new(HandClock(Mutex::new(moment)));
        let places = MachinePlaces::new(Arc::clone(&clock) as Arc<dyn Clock>);
        (clock, places)
    }

    #[test]
    fn each_kind_is_asked_its_own_way() {
        let cell = Asked::server(&Asked::ok(r#"[{"id": 0}, {"id": 1}, {"id": 2}]"#));
        assert_eq!(at(0.0).1.of(&cell.output("llama")), Some(3));
        assert_eq!(cell.questions(), ["GET /slots HTTP/1.1"]);
        let machine = Asked::server(&Asked::ok(r#"{"caravan": {"slots": 4}}"#));
        assert_eq!(at(0.0).1.of(&machine.output("machine")), Some(4));
        assert_eq!(machine.questions(), ["GET /v1/models/a%20b HTTP/1.1"]);
        let refused = Asked::server("HTTP/1.1 404 Not Found\r\nContent-Length: 2\r\nConnection: close\r\n\r\n[]");
        assert_eq!(at(0.0).1.of(&refused.output("llama")), None, "a refusal says no number, whatever its body");
    }

    #[test]
    fn a_number_stands_a_few_seconds_and_is_then_asked_again() {
        let cell = Asked::server(&Asked::ok("[{}]"));
        let (clock, places) = at(100.0);
        let output = cell.output("llama");
        assert_eq!(places.of(&output), Some(1));
        *clock.0.lock().unwrap() = 100.0 + MachinePlaces::TTL - 0.5;
        assert_eq!(places.of(&output), Some(1));
        assert_eq!(cell.questions().len(), 1, "no second question while it stands");
        *clock.0.lock().unwrap() = 100.0 + MachinePlaces::TTL;
        *cell.answer.lock().unwrap() = Some(Asked::ok("[{}, {}]"));
        assert_eq!(places.of(&output), Some(2));
        assert_eq!(cell.questions().len(), 2, "asked again at its end");
        assert_eq!(places.totals(), json!({output.group(): 2}));
    }

    #[test]
    fn a_question_that_fails_keeps_the_last_number_known() {
        let cell = Asked::server(&Asked::ok("[{}, {}]"));
        let (clock, places) = at(100.0);
        let output = cell.output("llama");
        assert_eq!(places.of(&output), Some(2));
        *clock.0.lock().unwrap() = 200.0;
        *cell.answer.lock().unwrap() = None;
        assert_eq!(places.asked_within(&output, Duration::from_millis(100)), Some(2));
        assert_eq!(places.totals(), json!({output.group(): 2}));
    }

    #[test]
    fn a_cell_says_its_places_by_its_rows() {
        assert_eq!(MachinePlaces::slots_in(&json!([{"id": 0}, {"id": 1}])), Some(2));
        assert_eq!(MachinePlaces::slots_in(&json!({"error": "no"})), None);
    }

    #[test]
    fn the_board_reads_only_the_numbers_said() {
        let places = MachinePlaces::new(Arc::new(crate::clock::SystemClock::new()));
        let mut said = places.said.lock().unwrap();
        said.insert("h:1".to_string(), Said { places: Some(2), at: 0.0 });
        said.insert("h:2/m".to_string(), Said { places: None, at: 0.0 });
        drop(said);
        assert_eq!(places.totals(), json!({"h:1": 2}));
    }

    #[test]
    fn an_engine_is_not_asked_what_it_cannot_answer() {
        // Nothing listens at this address: a question would take its timeout, and the answer is known without one.
        let output = MachineOutput::read(&json!({"id": "eng:1", "upstreamType": "engine", "upstreamModel": "m", "upstreamHost": "192.0.2.1", "upstreamPort": 11434})).unwrap();
        assert_eq!(MachinePlaces::ask(&output, Duration::from_secs(30)), None);
    }
}
