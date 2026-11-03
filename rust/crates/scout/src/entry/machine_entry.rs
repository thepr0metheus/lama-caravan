//! `GET /v1/models`, `GET /v1/models/<name>` and a request by `model` to a cell of this machine. Refusals speak OpenAI's shape: no `model`, 400; a name no cell has, 404 `model_not_found`; a model with no running copy, 503 `model_not_running`, its copies' states in the message; a cell that does not answer, 502 `cell_unreachable`. The request goes to the cell as it came, but for what belongs to one hop and the client's `Authorization` (the cells hold no keys, and a key is not theirs to see), and for `model`, given in the cell's own words when the cell answers to other names. The answer comes back as it came: past its headers nothing can be refused any more, and a cell that breaks off ends the answer where it got to.

use crate::cells::Cells;
use crate::entry::machine_models::MachineModels;
use crate::entry::request::EntryRequest;
use crate::entry::served::{CopyTurns, ServedNames};
use crate::http_client::HttpClient;
use net::{Dial, Stream};
use serde_json::{Value, json};
use std::collections::BTreeSet;
use std::io::{self, BufReader, Read, Write};
use std::sync::Arc;
use std::time::Duration;
use wire::{AnswerBody, AnswerHead, AnswerHeadReader, Headers, Percent, RequestHead};

/// A refusal to say to the client, or an answer on its way.
pub enum Forwarded {
    /// Said in OpenAI's shape.
    Refused(Value, u16),
    /// The cell's answer: its head, then its body.
    Answer(AnswerHead, AnswerBody<Stream>),
}

/// The entry.
pub struct MachineEntry {
    models: Arc<MachineModels>,
    cells: Arc<Cells>,
    turns: CopyTurns,
    names: ServedNames,
}

impl MachineEntry {
    /// Not passed on, either way: one hop's own (and what its Connection header names), the length, said again for the body that goes, and the client's key.
    const HOP: [&'static str; 11] = [
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
        "host",
        "content-length",
        "authorization",
    ];
    /// Not passed on to the cell: the body is here whole, and nothing waits for a 100.
    const TO_CELL: [&'static str; 1] = ["expect"];
    /// Not passed back: the scout's own server writes them.
    pub const TO_CLIENT: [&'static str; 2] = ["date", "server"];
    /// How long a cell may stay silent mid-answer: a long generation or a recording's transcription.
    const TIMEOUT: Duration = Duration::from_secs(600);

    /// The entry of these models.
    pub fn new(models: Arc<MachineModels>, cells: Arc<Cells>, http: Arc<HttpClient>) -> Self {
        Self { models, cells, turns: CopyTurns::default(), names: ServedNames::new(http) }
    }

    /// A refusal in OpenAI's shape.
    pub fn refusal(message: &str, kind: &str, code: Option<&str>, param: Option<&str>) -> Value {
        json!({"error": {"message": message, "type": kind, "param": param, "code": code}})
    }

    /// The fields that go on: all but one hop's own, and `also`.
    pub fn passed(headers: &Headers, also: &[&str]) -> Vec<(String, Vec<u8>)> {
        let named: BTreeSet<String> = headers
            .all("Connection")
            .iter()
            .flat_map(|value| value.split(','))
            .map(|token| token.trim().to_lowercase())
            .collect();
        headers
            .iter()
            .filter(|field| {
                let low = field.name.to_lowercase();
                !Self::HOP.contains(&low.as_str()) && !named.contains(&low) && !also.contains(&low.as_str())
            })
            .map(|field| (field.name.clone(), field.value.clone()))
            .collect()
    }

    /// The list.
    pub fn listing(&self) -> Value {
        json!({"object": "list", "data": self.models.listing()})
    }

    /// A GET under `/v1`: the list, or one model by its name.
    pub fn get(&self, target: &str) -> (Value, u16) {
        let path = target.split('?').next().unwrap_or(target).trim_end_matches('/');
        if path == "/v1/models" {
            return (self.listing(), 200);
        }
        if let Some(name) = path.strip_prefix("/v1/models/") {
            let name = Percent::decode(name);
            if let Some(found) =
                self.models.listing().into_iter().find(|model| model.get("id").and_then(Value::as_str) == Some(name.as_str()))
            {
                return (found, 200);
            }
            return (
                Self::refusal(
                    &format!("The model `{name}` does not exist on this machine"),
                    "invalid_request_error",
                    Some("model_not_found"),
                    Some("model"),
                ),
                404,
            );
        }
        (Self::refusal(&format!("No such path on this machine's entry: {path}"), "invalid_request_error", None, None), 404)
    }

    /// Hands the request to a running copy of its model, or refuses.
    pub fn forward(&self, head: &RequestHead, body: Vec<u8>) -> Forwarded {
        let request = EntryRequest::new(body, &head.headers.text_of("Content-Type"));
        let name = request.model();
        if name.is_empty() {
            return Forwarded::Refused(
                Self::refusal("You must provide a model parameter", "invalid_request_error", None, Some("model")),
                400,
            );
        }
        let (port, since) = match self.running_copy(&name) {
            Ok(chosen) => chosen,
            Err((payload, status)) => return Forwarded::Refused(payload, status),
        };
        let served = self.names.of(port, since.as_ref());
        let send = match served.as_ref().filter(|served| !served.contains(&name)).and_then(|served| served.first()) {
            Some(own) => request.naming(own),
            None => request.body().to_vec(),
        };
        match Self::asked(port, head, &send) {
            Ok((answer_head, answer_body)) => Forwarded::Answer(answer_head, answer_body),
            Err(error) => Forwarded::Refused(
                Self::refusal(
                    &format!("The cell of `{name}` on :{port} did not answer: {error}"),
                    "server_error",
                    Some("cell_unreachable"),
                    Some("model"),
                ),
                502,
            ),
        }
    }

    /// The running copy that takes a request for `name`: its port, and when it started. A name no cell has, or a model with no running copy, is refused.
    fn running_copy(&self, name: &str) -> Result<(i64, Option<Value>), (Value, u16)> {
        let copies = self.models.copies(name);
        if copies.is_empty() {
            return Err((
                Self::refusal(
                    &format!("The model `{name}` does not exist on this machine"),
                    "invalid_request_error",
                    Some("model_not_found"),
                    Some("model"),
                ),
                404,
            ));
        }
        let running: Vec<&crate::entry::machine_models::Copy> = copies.iter().filter(|copy| copy.state == "running").collect();
        let ports: Vec<i64> = running.iter().map(|copy| copy.port).collect();
        let busy = |port: i64| {
            let said = self.cells.probe.metrics(port).get("requestsProcessing").and_then(Value::as_i64);
            // absent-ok: a count a server does not say is taken as none.
            said.filter(|busy| *busy > 0).unwrap_or_default()
        };
        let Some(port) = self.turns.pick(&ports, busy) else {
            let states: Vec<String> = copies.iter().map(|copy| format!(":{} {}", copy.port, copy.state)).collect();
            return Err((
                Self::refusal(
                    &format!("The model `{name}` is not running on this machine ({})", states.join(", ")),
                    "server_error",
                    Some("model_not_running"),
                    Some("model"),
                ),
                503,
            ));
        };
        Ok((port, running.iter().find(|copy| copy.port == port).and_then(|copy| copy.since.clone())))
    }

    /// The request, to the cell.
    fn asked(port: i64, head: &RequestHead, body: &[u8]) -> io::Result<(AnswerHead, AnswerBody<Stream>)> {
        let port_number = u16::try_from(port).map_err(io::Error::other)?;
        let socket =
            Dial { turn: Self::TIMEOUT, limit: Self::TIMEOUT }.open::<io::Error>("127.0.0.1", port_number, &mut || Ok(()))?;
        socket.set_read_timeout(Some(Self::TIMEOUT))?;
        socket.set_write_timeout(Some(Self::TIMEOUT))?;
        let mut stream = Stream::Plain(socket);
        let fields = Self::passed(&head.headers, &Self::TO_CELL);
        let mut out = format!("{} {} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n", head.method, head.target).into_bytes();
        if !fields.iter().any(|(name, _)| name.eq_ignore_ascii_case("accept-encoding")) {
            out.extend_from_slice(b"Accept-Encoding: identity\r\n");
        }
        for (name, value) in &fields {
            out.extend_from_slice(name.as_bytes());
            out.extend_from_slice(b": ");
            out.extend_from_slice(value);
            out.extend_from_slice(b"\r\n");
        }
        out.extend_from_slice(format!("Content-Length: {}\r\n\r\n", body.len()).as_bytes());
        stream.write_all(&out)?;
        stream.write_all(body)?;
        stream.flush()?;
        let mut source = BufReader::new(stream);
        let answer_head = AnswerHeadReader::new().read(&mut source)?;
        let answer_body = AnswerBody::new(source, &answer_head, &head.method);
        Ok((answer_head, answer_body))
    }

    /// Reads the cell's answer to the client as it comes: a cell that breaks off, or a client that leaves, ends it where it got to.
    pub fn relay(mut body: impl Read, client: &mut impl Write) {
        let mut chunk = vec![0u8; 65536];
        while let Ok(count) = body.read(&mut chunk) {
            let Some(part) = chunk.get(..count).filter(|_| count != 0) else {
                break;
            };
            if client.write_all(part).and_then(|()| client.flush()).is_err() {
                break;
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn one_hops_fields_and_the_clients_key_stay_here() {
        let mut headers = Headers::new();
        for (name, value) in [
            ("Connection", "X-Mine, close"),
            ("X-Mine", "1"),
            ("Authorization", "Bearer k"),
            ("Host", "h"),
            ("Content-Length", "3"),
            ("Expect", "100-continue"),
            ("Content-Type", "application/json"),
            ("Date", "d"),
        ] {
            headers.push(name, value);
        }
        let names = |also: &[&str]| MachineEntry::passed(&headers, also).into_iter().map(|(name, _)| name).collect::<Vec<_>>();
        assert_eq!(names(&MachineEntry::TO_CELL), ["Content-Type", "Date"]);
        assert_eq!(names(&MachineEntry::TO_CLIENT), ["Expect", "Content-Type"]);
    }

    #[test]
    fn a_refusal_has_openais_shape() {
        assert_eq!(
            MachineEntry::refusal("m", "t", Some("c"), None),
            json!({"error": {"message": "m", "type": "t", "param": null, "code": "c"}})
        );
    }
}
