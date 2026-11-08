//! The board's voice window, on the controller's side.

use crate::app::App;
use crate::domain::runner::{Runner, TalkSpec};
use crate::fleet::cell_doorway::CellDoorway;
use crate::fleet::server_cells::ServerCells;
use crate::store::topology::Topology;
use net::Base64Std;
use plumbing::http_client::HttpError;
use regex::Regex;
use rules::{AppError, CellId, Coerce, PyRepr, PythonJson};
use serde_json::{Map, Value, json};
use std::time::Duration;

mod mode;
pub use mode::TalkMode;

mod ask;
use ask::{Consent, FormBody, TalkAsk, VoiceList};

/// What a cell answered.
pub struct CellAnswer {
    /// Its status.
    pub status: u16,
    /// Its type.
    pub kind: String,
    /// Its body.
    pub raw: Vec<u8>,
    /// `{first, total}` in milliseconds.
    pub ms: Value,
}

/// Asks a running cell as the voice window does, and says what it answered and how long it took.
pub struct CellTalk<'app> {
    app: &'app App,
    timeout: Duration,
}

impl<'app> CellTalk<'app> {
    const LIMIT: u64 = 16_000_000;
    /// What is shown of a cell's refusal.
    pub const REFUSAL_SHOWN: usize = 4_000;

    /// The window of `app`.
    pub fn of(app: &'app App) -> Self {
        Self { app, timeout: Duration::from_secs(300) }
    }

    /// The same, with a shorter patience.
    pub fn with_timeout(app: &'app App, seconds: u64) -> Self {
        Self { app, timeout: Duration::from_secs(seconds) }
    }

    /// The node of cell `id` in a machine's report.
    fn node(host: &Value, id: &str) -> Option<Value> {
        let matches = |node: &&Value| node.is_object() && ServerCells::node_cell(node).as_deref() == Some(id);
        match host.get("llamaNodes").and_then(Value::as_array) {
            Some(nodes) => nodes.iter().find(matches).cloned(),
            None => host.get("llamaNode").filter(|node| matches(node)).cloned(),
        }
    }

    /// The cell that runs at `port` on some machine, by its id: what a pool's row of before names when it names a port. `None` when
    /// no machine reports a running cell there.
    pub fn running_at(&self, port: i64) -> Option<String> {
        let hosts = self.app.admin.change(|doc| Topology::of(doc).hosts().clone());
        hosts.values().find_map(|host| {
            host.get("llamaNodes")
                .and_then(Value::as_array)
                .into_iter()
                .flatten()
                .find(|node| node.get("port").and_then(Value::as_i64) == Some(port) && Coerce::truthy(node.get("running")))
                .and_then(ServerCells::node_cell)
        })
    }

    /// `(the way to it, its slot's config)` of cell `id`, refused when it is not running: the way goes through its machine's scout, as
    /// the cell listens on the machine's loopback (`cell_doorway.rs`).
    pub fn cell(&self, id: &str) -> Result<(CellDoorway, Value), AppError> {
        let id = CellId::read(&json!(Coerce::strip(id))).ok_or_else(|| AppError::new("cell is required"))?;
        let slot = self.app.admin.change(|doc| Topology::of(doc).find_slot(&id).cloned()).filter(|slot| slot.is_object());
        let slot = slot.ok_or_else(|| {
            AppError::with_status(format!("the board has no config of cell {id}: it does not know what runs there"), 409)
        })?;
        let host_id = Coerce::stripped(slot.get("hostId"));
        let host = self.app.admin.change(|doc| Topology::of(doc).hosts().get(&host_id).filter(|host| host.is_object()).cloned());
        let host = host.ok_or_else(|| AppError::with_status(format!("no machine {} on the board", PyRepr::of(&host_id)), 404))?;
        let running = Self::node(&host, &id).filter(|node| Coerce::truthy(node.get("running")));
        if running.is_none() {
            return Err(AppError::with_status(format!("cell {id} is not running on {host_id}: start it first"), 409));
        }
        let way = CellDoorway::of(self.app, &host, &id)
            .ok_or_else(|| AppError::with_status(format!("machine {host_id} has not said its scout's address"), 409))?;
        Ok((way, slot.get("config").filter(|config| Coerce::truthy(Some(*config))).cloned().unwrap_or_else(|| json!({}))))
    }

    /// The runner of a config.
    pub fn runner_of(&self, config: &Value) -> &'app dyn Runner {
        self.app.runners.for_config(&Coerce::fields(config))
    }

    fn who(runner: &dyn Runner) -> &'static str {
        let id = runner.row().id;
        if id.is_empty() { "command" } else { id }
    }

    /// The cell's answer to a request of `path`: a POST of `data` when there is one, else a GET. It goes through the cell's machine's
    /// scout, whose refusal (no such cell, a cell that does not take the connection) comes back as the answer's status and words.
    pub fn ask(&self, way: &CellDoorway, path: &str, data: Option<(&[u8], &str)>) -> Result<CellAnswer, AppError> {
        let mut fields = vec![("Accept", "*/*".to_string())];
        if let Some((_, ctype)) = data.filter(|(_, ctype)| !ctype.is_empty()) {
            fields.push(("Content-Type", ctype.to_string()));
        }
        fields.extend(way.fields().iter().cloned());
        let (method, body): (&str, &[u8]) = match data {
            Some((body, _)) => ("POST", body),
            None => ("GET", &[]),
        };
        let url = way.url(path);
        let started = self.app.clock.monotonic();
        let failed = |error: String| AppError::with_status(format!("the {} did not answer: {error}", way.named()), 502);
        let answer = self
            .app
            .http
            .answer(method, &url, &fields, body, self.timeout)
            .map_err(|error: HttpError| failed(error.to_string()))?;
        let began = self.app.clock.monotonic();
        let status = answer.head.status;
        let kind = answer.head.headers.text_of("Content-Type");
        let raw = answer.text(Self::LIMIT).map_err(|error| failed(error.to_string()))?;
        let done = self.app.clock.monotonic();
        let ms = |moment: f64| ((moment - started) * 1000.0).round() as i64;
        Ok(CellAnswer { status, kind, raw, ms: json!({"first": ms(began), "total": ms(done)}) })
    }

    /// What is shown of a cell's refusal.
    pub fn refusal(status: u16, raw: &[u8]) -> String {
        let shown: String = String::from_utf8_lossy(raw).chars().take(Self::REFUSAL_SHOWN).collect();
        if shown.is_empty() { format!("HTTP {status}") } else { shown }
    }

    /// What the cell answered the window's `body`.
    pub fn talk(&self, body: &Value) -> Result<Value, AppError> {
        let wanted = Coerce::text(body.get("mode"));
        let mode = TalkMode::ALL.iter().find(|mode| mode.id == wanted);
        let mode = mode.ok_or_else(|| {
            let ids: Vec<&str> = TalkMode::ALL.iter().map(|mode| mode.id).collect();
            AppError::new(format!("mode must be one of {}", ids.join(", ")))
        })?;
        let (way, config) = self.cell(&Coerce::text(body.get("cellId")))?;
        let runner = self.runner_of(&config);
        let spec = &runner.row().talk;
        if !spec.modes.contains(&mode.id) {
            return Err(AppError::new(format!("a {} cell does not answer {}", Self::who(runner), mode.id)));
        }
        let ask = TalkAsk::read(body, mode)?;
        if !ask.sample.is_empty() && !spec.clone {
            return Err(AppError::new(format!("a {} cell does not speak in the voice of a sample", Self::who(runner))));
        }
        let (data, ctype) = mode.request(&ask, spec)?;
        let answer = self.ask(&way, mode.path, Some((&data, &ctype)))?;
        let mut out = json!({"mode": mode.id, "status": answer.status, "bytes": answer.raw.len(), "text": "", "audio": "", "audioType": "", "error": "", "ms": answer.ms});
        if answer.status >= 400 {
            Coerce::put(&mut out, "error", json!(Self::refusal(answer.status, &answer.raw)));
            return Ok(out);
        }
        for (key, said) in mode.answer(&answer.kind, &answer.raw, spec) {
            Coerce::put(&mut out, &key, said);
        }
        Ok(out)
    }

    /// `(the way to it, runner)` of a running cell whose server says its voices.
    fn keeper(&self, id: &str) -> Result<(CellDoorway, &'app dyn Runner), AppError> {
        let (way, config) = self.cell(id)?;
        let runner = self.runner_of(&config);
        if runner.row().talk.voices_path.is_empty() {
            return Err(AppError::new(format!("a {} cell does not say its voices", Self::who(runner))));
        }
        Ok((way, runner))
    }

    /// The voices the cell has, for the window's list.
    pub fn voices(&self, id: &str) -> Result<Value, AppError> {
        let (way, runner) = self.keeper(id)?;
        let answer = self.ask(&way, runner.row().talk.voices_path, None)?;
        let mut out = json!({"status": answer.status, "voices": [], "stored": [], "error": "", "ms": answer.ms});
        if answer.status >= 400 {
            Coerce::put(&mut out, "error", json!(Self::refusal(answer.status, &answer.raw)));
            return Ok(out);
        }
        for (key, said) in VoiceList::read(&answer.raw) {
            Coerce::put(&mut out, &key, said);
        }
        Ok(out)
    }

    /// A voice kept on the cell under a name, from a sample and the words it says.
    pub fn store_voice(&self, body: &Value) -> Result<Value, AppError> {
        let (way, runner) = self.keeper(&Coerce::text(body.get("cellId")))?;
        let spec = &runner.row().talk;
        if !spec.clone {
            return Err(AppError::new(format!("a {} cell keeps no voice from a sample", Self::who(runner))));
        }
        let name = Coerce::stripped(body.get("name"));
        if !TalkSpec::is_voice_name(&name) {
            return Err(AppError::new("name must be 1..64 letters, digits, '.', '_' or '-'"));
        }
        let sample = TalkAsk::recording(body.get("sample"), "sample")?;
        if sample.is_empty() {
            return Err(AppError::new("sample is empty: record the voice first"));
        }
        let words = TalkAsk::words(body.get("sampleText"), "sampleText")?;
        Consent::require(body)?;
        let mut form = FormBody::default();
        form.file("audio_sample", "sample.wav", "audio/wav", &sample)?;
        form.field("consent", Consent::ID)?;
        form.field("name", &name)?;
        if !words.is_empty() {
            form.field("ref_text", &words)?;
        }
        let (data, ctype) = form.done();
        let answer = self.ask(&way, spec.voices_path, Some((&data, &ctype)))?;
        let mut out = json!({"status": answer.status, "name": name, "error": "", "ms": answer.ms});
        if answer.status >= 400 {
            Coerce::put(&mut out, "error", json!(Self::refusal(answer.status, &answer.raw)));
            return Ok(out);
        }
        let kept = serde_json::from_slice::<Value>(&answer.raw).ok().is_some_and(|doc| doc.get("success") == Some(&json!(true)));
        if !kept {
            Coerce::put(
                &mut out,
                "error",
                json!(format!("the cell did not say it kept the voice: {}", Self::refusal(answer.status, &answer.raw))),
            );
        }
        Ok(out)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_form_keeps_its_boundary_to_itself() {
        let mut form = FormBody::default();
        assert_eq!(form.field("a", "--caravan-talk").unwrap_err().status, 400);
        form.field("a", "b").unwrap();
        let (body, ctype) = form.done();
        assert_eq!(ctype, "multipart/form-data; boundary=caravan-talk");
        assert_eq!(
            String::from_utf8(body).unwrap(),
            "--caravan-talk\r\nContent-Disposition: form-data; name=\"a\"\r\n\r\nb\r\n--caravan-talk--\r\n"
        );
    }

    #[test]
    fn a_voice_list_leaves_out_what_is_kept_and_placeholders() {
        let read = VoiceList::read(
            br#"{"voices": ["alloy", "Mine", "default", 5], "uploaded_voices": [{"name": "mine", "ref_text": "hi"}]}"#,
        );
        assert_eq!(read["voices"], json!(["alloy"]));
        assert_eq!(read["stored"], json!([{"name": "mine", "words": "hi"}]));
        assert!(VoiceList::read(b"nope").contains_key("error"));
        assert!(VoiceList::read(b"{}").contains_key("error"));
    }

    #[test]
    fn an_ask_is_refused_when_its_mode_cannot_send_it() {
        let speech = &TalkMode::ALL[3];
        assert!(TalkAsk::read(&json!({}), speech).unwrap_err().message.contains("takes a text"));
        let heard = &TalkMode::ALL[1];
        assert!(TalkAsk::read(&json!({}), heard).unwrap_err().message.contains("takes a recording"));
        assert!(TalkAsk::read(&json!({"audio": "!!"}), heard).unwrap_err().message.contains("not base64"));
        assert!(TalkAsk::read(&json!({"text": "x", "sampleText": "y"}), speech).is_err());
        assert!(TalkAsk::read(&json!({"text": "x", "sample": "YWJj"}), speech).unwrap_err().message.contains("consent"));
        assert!(TalkAsk::read(&json!({"text": "x", "sample": "YWJj", "consent": true}), speech).is_ok());
    }

    #[test]
    fn a_chat_answer_says_its_words_and_its_counts() {
        let mode = &TalkMode::ALL[2];
        let raw = br#"{"choices": [{"message": {"content": [{"type": "text", "text": "hi"}], "audio": {"data": "QQ==", "format": "mp3"}}}], "usage": {"prompt_tokens": 3}, "timings": {"predicted_n": 4, "predicted_per_second": 5.123}}"#;
        let answer = mode.answer("application/json", raw, &TalkSpec::NONE);
        assert_eq!(answer["text"], "hi");
        assert_eq!(answer["audioType"], "audio/mp3");
        assert_eq!(answer["tokens"], json!({"read": 3, "written": 4}));
        assert_eq!(answer["speed"], json!({"written": 5.12}));
        assert!(mode.answer("text/plain", b"nope", &TalkSpec::NONE)["error"].as_str().unwrap().contains("text/plain"));
    }
}
