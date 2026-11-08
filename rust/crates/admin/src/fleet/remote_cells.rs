//! A remote cell as this controller reads it — through its machine's scout (`cell_doorway.rs`): a cell listens on its machine's loopback
//! alone since 2026-11-08 — and the histories its card draws.

use crate::app::App;
use crate::common::misc::TtlCache;
use crate::fleet::cell_doorway::CellDoorway;
use rules::Coerce;
use serde_json::{Map, Value, json};
use std::collections::BTreeMap;
use std::sync::{Mutex, PoisonError};
use std::time::Duration;

/// What was asked a moment ago, and the histories.
pub struct RemoteMemory {
    health: TtlCache<String, String>,
    modalities: TtlCache<String, Option<Value>>,
    about: TtlCache<String, Value>,
    histories: Mutex<Histories>,
}

impl Default for RemoteMemory {
    fn default() -> Self {
        Self {
            health: TtlCache::new(3.0),
            modalities: TtlCache::new(300.0),
            about: TtlCache::new(30.0),
            histories: Mutex::new(Histories::default()),
        }
    }
}

#[derive(Default)]
struct Histories {
    gpu: BTreeMap<String, Vec<Value>>,
    cpu: BTreeMap<String, Vec<Value>>,
    tps: BTreeMap<String, Vec<Value>>,
}

/// What is carried from a cell's own word on its health.
pub struct CellHealthWords;

impl CellHealthWords {
    const CARRIED: [&'static str; 21] = [
        "status",
        "engine",
        "model",
        "source",
        "backend",
        "kinds",
        "langs",
        "codeset",
        "srcLang",
        "targetLang",
        "srcLangRequired",
        "acceptsShortCodes",
        "acceptsIso639_1",
        "maxAudioMs",
        "maxNewTokens",
        "device",
        "dtype",
        "deviceReason",
        "downloadedBytes",
        "totalBytes",
        "error",
    ];

    /// The subset of a cell's reply that travels to the board.
    pub fn carry(payload: &Value) -> Map<String, Value> {
        Self::CARRIED.iter().filter_map(|key| payload.get(*key).map(|said| ((*key).to_string(), said.clone()))).collect()
    }
}

/// The token rates a cell has now, as the history of the machine's token speed records them: a server that serves nobody keeps saying its last rate.
pub struct TokenRates;

impl TokenRates {
    /// How many requests a cell says it answers; `None` for what is no whole count.
    pub fn count(value: Option<&Value>) -> Option<i64> {
        let number = value.filter(|said| !said.is_boolean())?.as_f64()?;
        (number.is_finite() && number >= 0.0 && number.fract() == 0.0).then_some(number as i64)
    }

    /// The rates, none while nobody is served.
    pub fn now<'said>(
        prompt: Option<&'said Value>,
        generated: Option<&'said Value>,
        requests: Option<&Value>,
    ) -> (Option<&'said Value>, Option<&'said Value>, bool) {
        if Self::count(requests) == Some(0) { (None, None, true) } else { (prompt, generated, false) }
    }
}

/// A remote cell as this controller reads it.
pub struct RemoteCells<'app> {
    app: &'app App,
}

impl<'app> RemoteCells<'app> {
    const HISTORY_RETENTION: i64 = 600;
    const HISTORY_MAX: usize = 300;
    const HISTORY_EMIT: usize = 150;

    /// The readings of `app`.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    fn rounded_of(raw: Option<&Value>, digits: usize) -> Value {
        let number = raw.and_then(Coerce::float).filter(|number| number.is_finite());
        number.map_or(Value::Null, |number| json!(Coerce::rounded(number, digits)))
    }

    fn keep(buffer: &mut Vec<Value>, now: i64, sample: Value) -> Vec<Value> {
        if buffer.last().and_then(|last| last.get(0)).and_then(Value::as_i64) == Some(now) {
            if let Some(last) = buffer.last_mut() {
                *last = sample;
            }
        } else {
            buffer.push(sample);
        }
        let cutoff = now - Self::HISTORY_RETENTION;
        buffer.retain(|row| row.get(0).and_then(Value::as_i64).is_none_or(|at| at >= cutoff));
        let extra = buffer.len().saturating_sub(Self::HISTORY_MAX);
        buffer.drain(..extra);
        buffer.iter().skip(buffer.len().saturating_sub(Self::HISTORY_EMIT)).cloned().collect()
    }

    /// Each card's history kept, and written on the card.
    pub fn record_gpu_history(&self, node_id: &str, gpus: &mut [Value]) {
        let now = self.app.now_whole();
        let mut held = self.app.remote.histories.lock().unwrap_or_else(PoisonError::into_inner);
        for gpu in gpus {
            let Some(index) = gpu.get("index").filter(|index| !index.is_null()) else {
                continue;
            };
            let key = format!("{node_id}:{}", Coerce::str_of(Some(index)));
            let sample = json!([
                now,
                Self::rounded_of(gpu.get("memoryUsedMiB"), 1),
                Self::rounded_of(gpu.get("utilizationGpuPct"), 1),
                Self::rounded_of(gpu.get("powerDrawW"), 1)
            ]);
            let shown = Self::keep(held.gpu.entry(key).or_default(), now, sample);
            Coerce::put(gpu, "history", Value::Array(shown));
        }
    }

    /// A machine's CPU and memory history.
    pub fn record_cpu_history(&self, node_id: &str, cpu: &Value) -> Vec<Value> {
        let now = self.app.now_whole();
        let used = cpu.get("ram").and_then(|ram| ram.get("usedGb"));
        let sample = json!([now, Self::rounded_of(cpu.get("loadPct"), 1), Self::rounded_of(used, 1)]);
        let mut held = self.app.remote.histories.lock().unwrap_or_else(PoisonError::into_inner);
        Self::keep(held.cpu.entry(node_id.to_string()).or_default(), now, sample)
    }

    /// A server's token-speed history.
    pub fn record_tps_history(
        &self,
        key: &str,
        prompt: Option<&Value>,
        generated: Option<&Value>,
        requests: Option<&Value>,
    ) -> Vec<Value> {
        let now = self.app.now_whole();
        let (prompt, generated, idle) = TokenRates::now(prompt, generated, requests);
        let shown = |raw: Option<&Value>| if idle { json!(0.0) } else { Self::rounded_of(raw, 2) };
        let sample = json!([now, shown(prompt), shown(generated)]);
        let mut held = self.app.remote.histories.lock().unwrap_or_else(PoisonError::into_inner);
        Self::keep(held.tps.entry(key.to_string()).or_default(), now, sample)
    }

    /// The cell's own answer to a GET of `path`, through its machine's scout. A refusal of the scout's (no such cell, one that does
    /// not take the connection) is an answer of a status too: the cell is not reached, as when it did not answer at all.
    fn get(&self, way: &CellDoorway, path: &str, timeout_ms: u64) -> Result<(u16, Vec<u8>), plumbing::http_client::HttpError> {
        let answer = self.app.http.answer("GET", &way.url(path), way.fields(), &[], Duration::from_millis(timeout_ms))?;
        let status = answer.head.status;
        let raw = answer.text(65536)?;
        Ok((status, raw))
    }

    /// llama-server's `/health` state, remembered a moment: ok, loading or down.
    pub fn llama_health(&self, way: &CellDoorway) -> String {
        let key = way.key();
        let now = self.app.now();
        if let Some(hit) = self.app.remote.health.get(&key, now, Some(3.0)) {
            return hit;
        }
        let state = match self.get(way, "/health", 1200) {
            Ok((200, _)) => "ok",
            Ok((503, _)) => "loading",
            Ok((status, _)) if status < 400 => "loading",
            _ => "down",
        };
        self.app.remote.health.put(key, state.to_string(), now);
        state.to_string()
    }

    fn trimmed_word(body: &Value, name: &str, most: usize) -> Option<String> {
        let word = body.get(name)?.as_str().map(Coerce::strip).filter(|word| !word.is_empty())?;
        Some(word.chars().take(most).collect())
    }

    /// What a cell says it is on its `/health`, for a cell this controller holds no settings for.
    pub fn cell_about(&self, way: &CellDoorway) -> Value {
        let key = way.key();
        let now = self.app.now();
        if let Some(hit) = self.app.remote.about.get(&key, now, Some(30.0)) {
            return hit;
        }
        let mut about = Map::new();
        if let Ok((status, raw)) = self.get(way, "/health", 1000)
            && status < 400
            && let Ok(body) = serde_json::from_slice::<Value>(&raw)
            && body.is_object()
        {
            for name in ["engine", "model"] {
                if let Some(word) = Self::trimmed_word(&body, name, 120) {
                    about.insert(name.to_string(), json!(word));
                }
            }
            let words = |field: &str, longest: usize, most: usize| -> Vec<String> {
                let rows = body.get(field).and_then(Value::as_array).into_iter().flatten();
                rows.filter_map(Value::as_str)
                    .map(Coerce::strip)
                    .filter(|word| !word.is_empty())
                    .map(|word| word.chars().take(longest).collect())
                    .take(most)
                    .collect()
            };
            let kinds = words("kinds", usize::MAX, 16);
            if !kinds.is_empty() {
                about.insert("kinds".to_string(), json!(kinds));
            }
            let langs = words("langs", 32, 400);
            if !langs.is_empty() {
                about.insert("langs".to_string(), json!(langs));
            }
            if let Some(longest) = body.get("maxAudioMs").and_then(Value::as_i64).filter(|longest| *longest > 0) {
                about.insert("maxAudioMs".to_string(), json!(longest));
            }
            if let Some(word) = Self::trimmed_word(&body, "targetLang", 32) {
                about.insert("targetLang".to_string(), json!(word));
            }
        }
        let about = Value::Object(about);
        self.app.remote.about.put(key, about.clone(), now);
        about
    }

    fn health_of_answer(code: u16, raw: &[u8], path: &str) -> Value {
        let data: Value = serde_json::from_slice(raw).unwrap_or_else(|_| json!({}));
        let state = Coerce::text(data.get("status")).to_lowercase();
        let mut out = json!({"status": "down", "downloadedBytes": 0, "totalBytes": 0});
        if matches!(code, 401 | 403) {
            Coerce::put(&mut out, "status", json!("broken"));
            Coerce::put(&mut out, "error", json!(format!("the cell refuses the caravan (HTTP {code} on {path})")));
            return out;
        }
        if matches!(state.as_str(), "downloading" | "resolving" | "loading" | "starting") {
            Coerce::put(
                &mut out,
                "status",
                json!(if matches!(state.as_str(), "downloading" | "resolving") { "downloading" } else { "loading" }),
            );
            // absent-ok: `int(data.get(key) or 0)`: what is not said to be read is none so far.
            let count = |key: &str| Coerce::whole(data.get(key));
            Coerce::put(&mut out, "downloadedBytes", json!(count("downloadedBytes")));
            Coerce::put(&mut out, "totalBytes", json!(count("totalBytes")));
        } else if state == "error" || code >= 500 {
            Coerce::put(&mut out, "status", json!("broken"));
            let said = Coerce::text(data.get("error"));
            let shown = if said.is_empty() { format!("HTTP {code} on {path}") } else { said };
            Coerce::put(&mut out, "error", json!(shown.chars().take(300).collect::<String>()));
        } else {
            Coerce::put(&mut out, "status", json!("ok"));
        }
        let meta = CellHealthWords::carry(&data);
        if !meta.is_empty() {
            Coerce::put(&mut out, "meta", Value::Object(meta));
        }
        out
    }

    /// Health and startup progress of a generic command cell. One with no health path is as well as its port: whether it listens, as
    /// its machine's scout sees it on the loopback (`listening`); `unknown` when the scout could not read its listeners.
    pub fn command_cell_health(&self, way: &CellDoorway, health_path: &str, listening: Option<bool>) -> Value {
        let path = Coerce::strip(health_path);
        if path.is_empty() {
            let state = match listening {
                Some(true) => "ok",
                Some(false) => "down",
                None => "unknown",
            };
            return json!({"status": state, "downloadedBytes": 0, "totalBytes": 0});
        }
        let path = if path.starts_with('/') { path.to_string() } else { format!("/{path}") };
        match self.get(way, &path, 1000) {
            Ok((code, raw)) => Self::health_of_answer(code, &raw, &path),
            Err(_) => json!({"status": "down", "downloadedBytes": 0, "totalBytes": 0}),
        }
    }

    /// The input modalities a running llama-server accepts, read from its `/props`; `None` while it says none.
    pub fn llama_modalities(&self, way: &CellDoorway) -> Option<Value> {
        let key = way.key();
        let now = self.app.now();
        if let Some(hit) = self.app.remote.modalities.get(&key, now, Some(60.0)) {
            return hit;
        }
        let said = self.get(way, "/props", 1500).ok().filter(|(status, _)| *status == 200);
        let parsed = said.and_then(|(_, raw)| serde_json::from_slice::<Value>(&raw).ok());
        let mods = parsed.and_then(|props| props.get("modalities").filter(|raw| raw.is_object()).map(Self::only_modalities));
        self.app.remote.modalities.put(key, mods.clone(), now);
        mods
    }

    fn only_modalities(raw: &Value) -> Value {
        let fields = raw.as_object().into_iter().flatten();
        let kept: Map<String, Value> = fields
            .filter(|(key, _)| matches!(key.as_str(), "vision" | "video" | "audio"))
            .map(|(key, said)| (key.clone(), json!(Coerce::truthy(Some(said)))))
            .collect();
        Value::Object(kept)
    }

    /// A `/props` modalities object as `{vision, video, audio}` flags; `None` when nothing usable is there.
    pub fn normalize_modalities(raw: Option<&Value>) -> Value {
        let Some(raw) = raw.filter(|raw| raw.is_object()) else {
            return Value::Null;
        };
        let kept = Self::only_modalities(raw);
        if Coerce::truthy(Some(&kept)) { kept } else { Value::Null }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::tests::{HandClock, TestApp, TestFolder};
    use std::io::{BufRead, BufReader, Write};
    use std::net::TcpListener;

    /// A scout that answers one request with `answer`, and says what it was asked.
    fn scout_once(answer: &'static str) -> (u16, std::thread::JoinHandle<String>) {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        let asked = std::thread::spawn(move || {
            let (socket, _) = listener.accept().unwrap();
            let mut line = String::new();
            BufReader::new(socket.try_clone().unwrap()).read_line(&mut line).unwrap();
            (&socket).write_all(answer.as_bytes()).unwrap();
            line
        });
        (port, asked)
    }

    #[test]
    fn a_cell_is_asked_through_its_machine_s_scout() {
        let folder = TestFolder::new("cell-through-scout");
        let app = TestApp::with_clock(&folder.path, &[], HandClock::at(1000));
        let (port, asked) = scout_once("HTTP/1.1 200 OK\r\nContent-Length: 15\r\nConnection: close\r\n\r\n{\"status\":\"ok\"}");
        let way = CellDoorway::of(&app, &json!({"agentUrl": format!("http://127.0.0.1:{port}")}), "c22035").unwrap();
        assert_eq!(RemoteCells::of(&app).llama_health(&way), "ok");
        assert_eq!(asked.join().unwrap(), "GET /api/cell/c22035/health HTTP/1.1\r\n", "the door's path, not the cell's port");
    }

    #[test]
    fn a_command_cell_with_no_health_path_is_as_well_as_its_port_listens() {
        let folder = TestFolder::new("command-listens");
        let app = TestApp::with_clock(&folder.path, &[], HandClock::at(1000));
        // A scout nobody runs: a cell with no health path is not asked, its scout's word on its port is read.
        let way = CellDoorway::of(&app, &json!({"agentUrl": "http://127.0.0.1:1"}), "c1").unwrap();
        let cells = RemoteCells::of(&app);
        assert_eq!(cells.command_cell_health(&way, "", Some(true))["status"], "ok");
        assert_eq!(cells.command_cell_health(&way, "", Some(false))["status"], "down");
        assert_eq!(cells.command_cell_health(&way, " ", None)["status"], "unknown", "negative: not known is not down");
    }

    #[test]
    fn a_rate_is_none_while_nobody_is_served() {
        let (prompt, generated) = (json!(5.0), json!(9.0));
        let (first, second, idle) = TokenRates::now(Some(&prompt), Some(&generated), Some(&json!(0)));
        assert!(first.is_none() && second.is_none() && idle);
        let (first, _, idle) = TokenRates::now(Some(&prompt), Some(&generated), Some(&json!(1)));
        assert!(first.is_some() && !idle);
        assert!(TokenRates::count(Some(&json!(true))).is_none());
        assert!(TokenRates::count(Some(&json!(1.5))).is_none());
    }

    #[test]
    fn a_cell_says_its_state_in_one_shape() {
        let down = RemoteCells::health_of_answer(401, b"", "/h");
        assert_eq!(down["status"], "broken");
        let loading = RemoteCells::health_of_answer(200, br#"{"status":"downloading","downloadedBytes":5,"totalBytes":9}"#, "/h");
        assert_eq!(loading["status"], "downloading");
        assert_eq!(loading["downloadedBytes"], 5);
        assert_eq!(loading["meta"]["status"], "downloading");
        let broken = RemoteCells::health_of_answer(500, b"nope", "/h");
        assert_eq!(broken["error"], "HTTP 500 on /h");
        assert_eq!(RemoteCells::health_of_answer(200, b"{}", "/h")["status"], "ok");
    }

    #[test]
    fn modalities_keep_only_what_the_board_knows() {
        assert_eq!(RemoteCells::normalize_modalities(Some(&json!({"vision": 1, "other": 1}))), json!({"vision": true}));
        assert_eq!(RemoteCells::normalize_modalities(Some(&json!({"other": 1}))), Value::Null);
        assert_eq!(RemoteCells::normalize_modalities(None), Value::Null);
    }

    #[test]
    fn a_history_holds_one_sample_a_second_and_forgets() {
        let mut buffer = Vec::new();
        RemoteCells::keep(&mut buffer, 100, json!([100, 1]));
        let shown = RemoteCells::keep(&mut buffer, 100, json!([100, 2]));
        assert_eq!(shown, [json!([100, 2])]);
        let shown = RemoteCells::keep(&mut buffer, 1000, json!([1000, 3]));
        assert_eq!(shown, [json!([1000, 3])]);
    }
}
