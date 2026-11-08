//! What a client of the entry gets for a question of its own, asked with its key on the operator's behalf: the rest.

use super::client_ids::ClientIds;
use super::config::ProxiesConfig;
use crate::app::App;
use crate::cloud::data::CloudData;
use crate::fleet::cell_talk::CellTalk;
use crate::store::topology::Topology;
use net::Base64Std;
use rules::{AppError, ClientDeny, Coerce, KeyEntry, PythonJson, RowWork};
use serde_json::{Map, Value, json};
use std::time::Duration;
use wire::Percent;

/// What a test sends in its body.
enum ProbeBody {
    /// A JSON request.
    Json(fn(&str, &str) -> Value),
    /// A form with half a second of silence as its file.
    Form(fn(&str) -> Vec<(&'static str, String)>),
}

/// One question a client asks by POST, sent as the shortest standard request of its kind (OpenAI's API reference).
pub struct ClientProbe {
    path: &'static str,
    body: ProbeBody,
    paid: bool,
    voiced: bool,
}

impl ClientProbe {
    const PROMPT: &'static str = "Reply with one word: OK";
    const BOUNDARY: &'static str = "caravan-probe";

    /// The tests, in the order a client's card lists them: one table sends them and says them.
    const ALL: [Self; 6] = [
        Self { path: "/v1/chat/completions", body: ProbeBody::Json(Self::chat), paid: false, voiced: false },
        Self { path: "/v1/responses", body: ProbeBody::Json(Self::responses), paid: false, voiced: false },
        Self { path: "/v1/audio/transcriptions", body: ProbeBody::Form(Self::transcription), paid: false, voiced: false },
        Self { path: "/v1/audio/speech", body: ProbeBody::Json(Self::speech), paid: false, voiced: true },
        Self { path: "/v1/images/generations", body: ProbeBody::Json(Self::image), paid: true, voiced: false },
        Self { path: "/v1/embeddings", body: ProbeBody::Json(Self::embedding), paid: false, voiced: false },
    ];

    fn chat(model: &str, _voice: &str) -> Value {
        json!({"model": model, "messages": [{"role": "user", "content": Self::PROMPT}], "max_tokens": 16})
    }

    fn responses(model: &str, _voice: &str) -> Value {
        json!({"model": model, "input": [{"role": "user", "content": Self::PROMPT}], "store": false})
    }

    fn transcription(model: &str) -> Vec<(&'static str, String)> {
        vec![("model", model.to_string()), ("response_format", "json".to_string())]
    }

    fn speech(model: &str, voice: &str) -> Value {
        json!({"model": model, "input": "OK", "voice": voice, "response_format": "wav"})
    }

    fn image(model: &str, _voice: &str) -> Value {
        json!({"model": model, "prompt": "A small red square on a white background", "n": 1, "size": "256x256"})
    }

    fn embedding(model: &str, _voice: &str) -> Value {
        json!({"model": model, "input": "OK"})
    }

    /// Half a second of silence as a 16-bit mono WAV at 16 kHz.
    fn silence_wav() -> Vec<u8> {
        const RATE: u32 = 16_000;
        // Half a second of two-byte samples is as many bytes as the rate says.
        let length = RATE;
        let data = vec![0u8; RATE as usize];
        let mut out = Vec::with_capacity(44 + data.len());
        out.extend_from_slice(b"RIFF");
        out.extend_from_slice(&(36 + length).to_le_bytes());
        out.extend_from_slice(b"WAVEfmt ");
        out.extend_from_slice(&16u32.to_le_bytes());
        out.extend_from_slice(&1u16.to_le_bytes());
        out.extend_from_slice(&1u16.to_le_bytes());
        out.extend_from_slice(&RATE.to_le_bytes());
        out.extend_from_slice(&(RATE * 2).to_le_bytes());
        out.extend_from_slice(&2u16.to_le_bytes());
        out.extend_from_slice(&16u16.to_le_bytes());
        out.extend_from_slice(b"data");
        out.extend_from_slice(&length.to_le_bytes());
        out.extend_from_slice(&data);
        out
    }

    /// (body, content type, what is said to have been sent) of the probe for `model`, in `voice` for a test that names one.
    fn request(&self, model: &str, voice: &str) -> (Vec<u8>, String, String) {
        match self.body {
            ProbeBody::Json(payload) => {
                let payload = payload(model, voice);
                (
                    PythonJson::spaced(&payload).into_bytes(),
                    "application/json".to_string(),
                    PythonJson::indented_letters(&payload),
                )
            }
            ProbeBody::Form(fields) => {
                let fields = fields(model);
                let audio = Self::silence_wav();
                let mut body = Vec::new();
                for (name, value) in &fields {
                    let part =
                        format!("--{}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n", Self::BOUNDARY);
                    body.extend_from_slice(part.as_bytes());
                }
                let head = format!(
                    "--{}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"probe.wav\"\r\nContent-Type: audio/wav\r\n\r\n",
                    Self::BOUNDARY
                );
                body.extend_from_slice(head.as_bytes());
                body.extend_from_slice(&audio);
                body.extend_from_slice(b"\r\n");
                body.extend_from_slice(format!("--{}--\r\n", Self::BOUNDARY).as_bytes());
                let mut sent: Vec<String> = fields.iter().map(|(name, value)| format!("{name}={value}")).collect();
                sent.push(format!("file=probe.wav (audio/wav, {} bytes: 0.5 s of silence, 16 kHz)", audio.len()));
                (body, format!("multipart/form-data; boundary={}", Self::BOUNDARY), sent.join("\n"))
            }
        }
    }
}

/// The voice a client's speech test names.
pub struct ProbeVoice<'app> {
    app: &'app App,
}

impl<'app> ProbeVoice<'app> {
    const REFERENCE: &'static str = "alloy";
    const MODE: &'static str = "speech";

    /// The view.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    fn reference() -> Value {
        json!({"name": Self::REFERENCE, "cell": ""})
    }

    /// `{name, cell}`: the voice the test names, and the cell (its id) whose voice it is, "" for the reference voice.
    fn of_route(&self, route: &Value, model: &str) -> Result<Value, AppError> {
        let cloud = CloudData::of(self.app);
        let models = cloud.board_names(&cloud.load());
        let deny = ClientDeny::clean(route.get(ClientDeny::FIELD));
        // absent-ok: a model no pool answers to has no rows.
        let rows = models.pick(&deny, model).map(|pool| pool.rows.clone()).unwrap_or_default();
        for row in rows {
            if !row.enabled || matches!(row.work, RowWork::Open) {
                continue;
            }
            if let RowWork::Output(output) = &row.work
                && output.starts_with("srv:")
            {
                match self.of_cell(output)? {
                    Some(voice) => return Ok(voice),
                    None => continue,
                }
            }
            break;
        }
        Ok(Self::reference())
    }

    /// The voice of the cell a row of before names by its port (`srv:<port>`); `None` when no machine runs a cell there.
    fn of_cell(&self, output: &str) -> Result<Option<Value>, AppError> {
        let Some(port) = output.split_once(':').and_then(|(_, port)| port.parse::<i64>().ok()) else {
            return Ok(None);
        };
        let talk = CellTalk::with_timeout(self.app, 10);
        let Some(cell) = talk.running_at(port) else {
            return Ok(None);
        };
        let config = self.app.admin.change(|doc| {
            Topology::of(doc).find_slot(&cell).filter(|slot| slot.is_object()).and_then(|slot| slot.get("config")).cloned()
        });
        let Some(config) = config else {
            return Ok(Some(Self::reference()));
        };
        let runner = talk.runner_of(&config);
        let spec = &runner.row().talk;
        if !spec.modes.contains(&Self::MODE) {
            return Ok(Some(Self::reference()));
        }
        if let Some(own) = spec.voices_of(Self::MODE).first() {
            return Ok(Some(json!({"name": own, "cell": cell})));
        }
        if spec.voices_path.is_empty() {
            return Ok(Some(Self::reference()));
        }
        let listed = talk.voices(&cell)?;
        if Coerce::truthy(listed.get("error")) {
            let words =
                format!("the {} cell {cell} did not list its voices: {}", runner.row().id, Coerce::str_of(listed.get("error")));
            return Err(AppError::with_status(words, 502));
        }
        let voices = listed.get("voices").and_then(Value::as_array).into_iter().flatten().cloned();
        let stored =
            listed.get("stored").and_then(Value::as_array).into_iter().flatten().filter_map(|kept| kept.get("name").cloned());
        let Some(name) = voices.chain(stored).next() else {
            let words = format!(
                "the {} cell {cell}, the one that serves the pool, has no voice: keep one in its 🎙 window — a client is refused there whatever voice it names",
                runner.row().id
            );
            return Err(AppError::with_status(words, 409));
        };
        Ok(Some(json!({"name": name, "cell": cell})))
    }
}

/// `(route, key, the entry's port)` of a client.
struct EntryClient {
    route: Value,
    key: String,
    entry_port: i64,
}

/// A client's question, asked as the client.
pub struct AsConsumer<'app> {
    app: &'app App,
}

impl<'app> AsConsumer<'app> {
    const MODELS: &'static str = "/v1/models";
    const LIMIT: u64 = 1_000_000;
    const TEXT_SHOWN: usize = 20_000;
    const AUDIO_SHOWN: usize = 2_000_000;
    const TIMEOUT: Duration = Duration::from_secs(10);
    const PROBE_TIMEOUT: Duration = Duration::from_secs(120);

    /// The view.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    /// The tests a client's card offers, from the one table that sends them.
    pub fn probes() -> Vec<Value> {
        ClientProbe::ALL.iter().map(|probe| json!({"path": probe.path, "paid": probe.paid})).collect()
    }

    /// The type an answer is handed on with.
    pub fn shown_as(content_type: &str) -> &'static str {
        if content_type.to_lowercase().contains("json") { "application/json; charset=utf-8" } else { "text/plain; charset=utf-8" }
    }

    /// The path as the entry is asked it; "" for one a client does not ask by GET.
    pub fn path_of(path: &str) -> String {
        if path.trim_end_matches('/') == Self::MODELS {
            return Self::MODELS.to_string();
        }
        match path.strip_prefix(Self::MODELS).and_then(|tail| tail.strip_prefix('/')).filter(|tail| !tail.is_empty()) {
            Some(tail) => format!("{}/{}", Self::MODELS, Percent::encode(tail)),
            None => String::new(),
        }
    }

    fn client(&self, route_id: &str) -> Result<EntryClient, AppError> {
        let config = ProxiesConfig::of(self.app).load()?;
        let routes = config.get("routes").and_then(Value::as_array).into_iter().flatten();
        let route = routes
            .filter(|route| route.is_object() && Coerce::text(route.get("kind")) == "consumer")
            .find(|route| ClientIds::of(route) == route_id)
            .cloned()
            .ok_or_else(|| AppError::with_status(format!("no client has the id {route_id}"), 404))?;
        let key = Coerce::text(route.get("apiKey"));
        if key.is_empty() {
            let said = Coerce::text(route.get("label"));
            let name = if said.is_empty() { route_id.to_string() } else { said };
            return Err(AppError::with_status(format!("client {name} has no key: the entry would refuse it"), 409));
        }
        // absent-ok: `int(... or 0)`: an entry with no port is off, refused just below.
        let entry_port = Coerce::int_or_zero(config.get("entry").and_then(|entry| entry.get("port"))).unwrap_or(0);
        if entry_port == 0 {
            return Err(AppError::with_status("the entry is off: no client gets anything", 409));
        }
        Ok(EntryClient { route, key, entry_port })
    }

    /// `(status, content type, body)` the entry answered: its refusal is an answer too.
    fn send(
        &self,
        method: &str,
        url: &str,
        fields: &[(&str, String)],
        body: &[u8],
        entry_port: i64,
        timeout: Duration,
    ) -> Result<(u16, String, Vec<u8>), AppError> {
        let answer = self.app.http.answer(method, url, fields, body, timeout);
        let refused =
            |error: String| AppError::with_status(format!("the entry on port {entry_port} did not answer: {error}"), 502);
        let answer = answer.map_err(|error| refused(error.to_string()))?;
        let status = answer.head.status;
        let kind = answer.head.headers.text_of("Content-Type");
        let raw = answer.text(Self::LIMIT).map_err(|error| refused(error.to_string()))?;
        Ok((status, kind, raw))
    }

    /// `(status, content type, body)` the entry answers the client `route_id` for `path`.
    pub fn ask(&self, route_id: &str, path: &str) -> Result<(u16, String, Vec<u8>), AppError> {
        let asked = Self::path_of(path);
        if asked.is_empty() {
            return Err(AppError::new(format!("a client asks by GET only {0} and {0}/<model>", Self::MODELS)));
        }
        let client = self.client(route_id)?;
        let fields = [
            ("Authorization", format!("Bearer {}", client.key)),
            ("Accept", "application/json".to_string()),
            (KeyEntry::PROBE_HEADER, "routing".to_string()),
        ];
        let url = format!("http://127.0.0.1:{}{asked}", client.entry_port);
        self.send("GET", &url, &fields, b"", client.entry_port, Self::TIMEOUT)
    }

    /// What the entry answers the client `route_id` for a POST of `path`, sent as the shortest standard request of its kind naming `model`: the name the client calls its pool by.
    pub fn probe(&self, route_id: &str, path: Option<&Value>, model: Option<&Value>) -> Result<Value, AppError> {
        let wanted = Coerce::text(path);
        let Some(probe) = ClientProbe::ALL.iter().find(|probe| probe.path == wanted) else {
            let listed: Vec<&str> = ClientProbe::ALL.iter().map(|probe| probe.path).collect();
            return Err(AppError::new(format!("a client asks by POST only {}", listed.join(", "))));
        };
        let client = self.client(route_id)?;
        let model = Coerce::text(model);
        let voice = if probe.voiced { Some(ProbeVoice::of(self.app).of_route(&client.route, &model)?) } else { None };
        let name = voice.as_ref().map_or_else(String::new, |voice| Coerce::text(voice.get("name")));
        let (body, kind, sent) = probe.request(&model, &name);
        let fields = [
            ("Authorization", format!("Bearer {}", client.key)),
            ("Content-Type", kind),
            ("Accept", "*/*".to_string()),
            (KeyEntry::PROBE_HEADER, "routing".to_string()),
        ];
        let url = format!("http://127.0.0.1:{}{}", client.entry_port, probe.path);
        let started = self.app.clock.monotonic();
        let (status, content_type, raw) = self.send("POST", &url, &fields, &body, client.entry_port, Self::PROBE_TIMEOUT)?;
        let ms = ((self.app.clock.monotonic() - started) * 1000.0).round() as i64;
        let mut request = Map::new();
        request.insert("method".to_string(), json!("POST"));
        request.insert("path".to_string(), json!(probe.path));
        request.insert("model".to_string(), json!(model));
        request.insert("sent".to_string(), json!(sent));
        if let Some(voice) = voice {
            request.insert("voice".to_string(), voice);
        }
        let mut out = json!({"request": request, "status": status, "contentType": content_type, "ms": ms, "bytes": raw.len()});
        if content_type.to_lowercase().starts_with("audio/") {
            let shown: Vec<u8> = raw.iter().copied().take(Self::AUDIO_SHOWN).collect();
            Coerce::put(&mut out, "audio", json!(Base64Std::encode(&shown)));
        } else {
            let text = String::from_utf8_lossy(&raw);
            let shown: String = text.chars().take(Self::TEXT_SHOWN).collect();
            Coerce::put(&mut out, "text", json!(shown));
            Coerce::put(&mut out, "cut", json!(text.chars().count() > Self::TEXT_SHOWN));
        }
        Ok(out)
    }
}
