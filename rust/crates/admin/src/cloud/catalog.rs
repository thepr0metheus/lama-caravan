//! Each provider's list of models, and the health of each upstream endpoint. A breaker stands before an
//! endpoint that keeps refusing: three refusals in a row disable it for 6 hours, doubling to 48; a network with no answer never does, since it says
//! nothing of the endpoint.

use super::api::CloudApi;
use super::call::UpstreamFailure;
use crate::app::App;
use files::AtomicFile;
use plumbing::log::Log;
use regex::{Regex, RegexBuilder};
use rules::{AppError, Coerce, PythonJson};
use serde_json::{Map, Value, json};
use std::collections::BTreeSet;
use std::sync::{Mutex, PoisonError};
use std::time::Duration;

/// What the catalogue's file stands under, and the refreshes going on.
#[derive(Default)]
pub struct CatalogMemory {
    file: Mutex<()>,
    refreshing: Mutex<BTreeSet<String>>,
}

/// Which models of a provider's list make sense as a pool's step: a speaker or a picture is no chat.
pub struct ChatModels {
    non_chat: Regex,
}

impl ChatModels {
    /// The rule.
    pub fn new() -> Result<Self, regex::Error> {
        let non_chat = RegexBuilder::new(
            r"(?:^|[-/_.:])(tts|whisper|embed|embedding|embeddings|moderation|dall-e|dalle|sora|image|audio|transcribe|realtime|search|babbage|davinci|computer-use)(?:$|[-/_.:0-9])",
        )
        .case_insensitive(true)
        .build()?;
        Ok(Self { non_chat })
    }

    /// Whether a model of this id chats.
    pub fn is_chat(&self, model_id: &str) -> bool {
        !self.non_chat.is_match(model_id)
    }

    /// The models of a list that do.
    pub fn of<'list>(&self, models: &'list [Value]) -> Vec<&'list Value> {
        let named = models.iter().filter(|model| model.is_object() && Coerce::truthy(model.get("id")));
        named.filter(|model| self.is_chat(&Coerce::text(model.get("id")))).collect()
    }
}

/// The catalogue of this controller.
pub struct ModelCatalog<'app> {
    app: &'app App,
}

impl<'app> ModelCatalog<'app> {
    const MODELS_TTL_SEC: f64 = 600.0;
    const NPM_TTL_SEC: f64 = 86400.0;
    const BREAK_AFTER: i64 = 3;
    const BREAK_BASE_SEC: f64 = 6.0 * 3600.0;
    const BREAK_MAX_SEC: f64 = 48.0 * 3600.0;
    const CODEX_CLIENT_VERSION_FLOOR: &'static str = "0.160.0";
    const NPM_LATEST_URL: &'static str = "https://registry.npmjs.org/@openai/codex/latest";
    const NPM_ENDPOINT: &'static str = "global:codex-npm";
    const VERSION_VARIABLE: &'static str = "CARAVAN_CODEX_CLIENT_VERSION";

    /// The catalogue of `app`.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    fn read_file(&self) -> Value {
        let raw = std::fs::read(&self.app.paths.model_catalog_file).ok();
        let said = raw.and_then(|raw| serde_json::from_slice::<Value>(&raw).ok());
        said.filter(Value::is_object).unwrap_or_else(|| json!({}))
    }

    fn write_file(&self, data: &Value) {
        let mut text = PythonJson::indented_once_letters(data);
        text.push('\n');
        if let Err(error) = AtomicFile::write(&self.app.paths.model_catalog_file, text.as_bytes()) {
            Log::line(&format!("model catalog: not written: {error}"));
        }
    }

    fn read_locked(&self) -> Value {
        let _held = self.app.catalog.file.lock().unwrap_or_else(PoisonError::into_inner);
        self.read_file()
    }

    fn mutate(&self, change: impl FnOnce(&mut Value)) {
        let _held = self.app.catalog.file.lock().unwrap_or_else(PoisonError::into_inner);
        let mut data = self.read_file();
        change(&mut data);
        self.write_file(&data);
    }

    /// What is known of an endpoint.
    pub fn endpoint_state(&self, key: &str) -> Value {
        let data = self.read_locked();
        data.get("endpoints")
            .and_then(|endpoints| endpoints.get(key))
            .filter(|row| row.is_object())
            .cloned()
            .unwrap_or_else(|| json!({}))
    }

    fn float_of(row: &Value, key: &str) -> f64 {
        // absent-ok: `float(st.get(key) or 0)`: a moment that was never written is long past.
        Coerce::float_or_zero(row.get(key))
    }

    fn int_of(row: &Value, key: &str) -> i64 {
        // absent-ok: `int(st.get(key) or 0)`: a count that was never written is none.
        Coerce::whole(row.get(key))
    }

    /// Whether the breaker stands open.
    pub fn endpoint_blocked(&self, key: &str) -> bool {
        self.app.now() < Self::float_of(&self.endpoint_state(key), "disabledUntil")
    }

    /// A call answered: what was held against the endpoint goes.
    pub fn record_ok(&self, key: &str) {
        self.mutate(|data| {
            if !data.get("endpoints").is_some_and(Value::is_object) {
                Coerce::put(data, "endpoints", json!({}));
            }
            if let Some(endpoints) = data.get_mut("endpoints") {
                Coerce::take(endpoints, key);
            }
        });
    }

    /// One more failure. `network`: no answer came, which is counted and shown but opens no breaker.
    pub fn record_fail(&self, key: &str, error: &str, network: bool) {
        let now = self.app.now();
        self.mutate(|data| {
            if data.get("endpoints").is_none() {
                Coerce::put(data, "endpoints", json!({}));
            }
            let Some(endpoints) = data.get_mut("endpoints").and_then(Value::as_object_mut) else {
                return;
            };
            let row = endpoints.entry(key.to_string()).or_insert_with(|| json!({}));
            let fails = Self::int_of(row, "failCount");
            if row.get("hardFails").is_none() {
                Coerce::put(row, "hardFails", json!(fails));
            }
            Coerce::put(row, "failCount", json!(fails + 1));
            let shown: String = error.chars().take(300).collect();
            Coerce::put(row, "lastError", json!(shown));
            Coerce::put(row, "lastErrorAt", json!(now as i64));
            Coerce::put(row, "network", json!(network));
            if network {
                return;
            }
            let hard = Self::int_of(row, "hardFails") + 1;
            Coerce::put(row, "hardFails", json!(hard));
            let over = hard - Self::BREAK_AFTER;
            if over >= 0 {
                let pause = (Self::BREAK_BASE_SEC * 2_f64.powi(i32::try_from(over).unwrap_or(i32::MAX))).min(Self::BREAK_MAX_SEC);
                Coerce::put(row, "disabledUntil", json!((now + pause) as i64));
            }
        });
    }

    /// Everything that failed at least once, for the cloud health panel.
    pub fn endpoints_report(&self) -> Value {
        let now = self.app.now();
        let data = self.read_locked();
        let mut out = Map::new();
        for (key, row) in data.get("endpoints").and_then(Value::as_object).into_iter().flatten() {
            if !row.is_object() {
                continue;
            }
            out.insert(
                key.clone(),
                json!({
                    "failCount": Self::int_of(row, "failCount"),
                    "lastError": Coerce::text(row.get("lastError")),
                    "lastErrorAt": Self::int_of(row, "lastErrorAt"),
                    "disabledUntil": Self::int_of(row, "disabledUntil"),
                    "disabled": now < Self::float_of(row, "disabledUntil"),
                    "network": Coerce::truthy(row.get("network")),
                }),
            );
        }
        Value::Object(out)
    }

    /// What the board says of an endpoint its breaker keeps closed.
    pub fn refusal_words(state: &Value) -> String {
        let last: String = Coerce::text(state.get("lastError")).chars().take(120).collect();
        format!("{} failures: {last}", Self::int_of(state, "failCount"))
    }

    /// An upstream call run through the breaker.
    pub fn guarded<T>(&self, key: &str, work: impl FnOnce() -> Result<T, UpstreamFailure>) -> Result<T, AppError> {
        if self.endpoint_blocked(key) {
            let words = Self::refusal_words(&self.endpoint_state(key));
            let (count, last) = words.split_once(" failures: ").unwrap_or((words.as_str(), ""));
            return Err(AppError::with_status(
                format!("endpoint disabled after {count} failures (retry from the provider card): {last}"),
                503,
            ));
        }
        match work() {
            Ok(result) => {
                self.record_ok(key);
                Ok(result)
            }
            Err(failure) => {
                self.record_fail(key, &failure.error.message, failure.network);
                Err(failure.error)
            }
        }
    }

    fn version_numbers(text: &str) -> Vec<u64> {
        let digits = text.split(|letter: char| !letter.is_ascii_digit()).filter(|run| !run.is_empty());
        let numbers: Vec<u64> = digits.take(4).filter_map(|run| run.parse().ok()).collect();
        if numbers.is_empty() { vec![0] } else { numbers }
    }

    fn npm_latest_cached(&self) -> String {
        let data = self.read_locked();
        let empty = json!({});
        let cached = data.get("codexNpm").unwrap_or(&empty);
        let kept = Coerce::text(cached.get("version"));
        let now = self.app.now();
        if now - Self::float_of(cached, "checkedAt") < Self::NPM_TTL_SEC || self.endpoint_blocked(Self::NPM_ENDPOINT) {
            return kept;
        }
        let asked = self.guarded(Self::NPM_ENDPOINT, || {
            let answer = self.app.http.json("GET", Self::NPM_LATEST_URL, &[], &[], Duration::from_secs(8));
            answer
                .map(|said| Coerce::text(said.get("version")))
                .map_err(|error| UpstreamFailure { network: error.is_silence(), error: AppError::new(error.to_string()) })
        });
        let Ok(version) = asked else {
            return kept;
        };
        self.mutate(|data| Coerce::put(data, "codexNpm", json!({"version": version, "checkedAt": now as i64})));
        version
    }

    /// The version the operator set, else the newest of npm's latest and the floor; and which of them it is.
    pub fn codex_client_version(&self) -> (String, &'static str) {
        if let Some(said) = self.app.env.get(Self::VERSION_VARIABLE).map(str::trim).filter(|said| !said.is_empty()) {
            return (said.to_string(), "env");
        }
        let npm = self.npm_latest_cached();
        if !npm.is_empty() && Self::version_numbers(&npm) > Self::version_numbers(Self::CODEX_CLIENT_VERSION_FLOOR) {
            return (npm, "npm");
        }
        (Self::CODEX_CLIENT_VERSION_FLOOR.to_string(), "floor")
    }

    /// An account's list, as the last check left it.
    pub fn cached_models_entry(&self, account_id: &str) -> Option<Value> {
        let data = self.read_locked();
        data.get("accounts").and_then(|accounts| accounts.get(account_id)).filter(|entry| entry.is_object()).cloned()
    }

    /// The ids of an account's models; `None` when no list that names one is kept.
    pub fn cached_model_ids(&self, account_id: &str) -> Option<BTreeSet<String>> {
        let entry = self.cached_models_entry(account_id).filter(|entry| Coerce::truthy(Some(entry)))?;
        let models = entry.get("models").and_then(Value::as_array).into_iter().flatten();
        let ids: BTreeSet<String> = models
            .filter(|model| model.is_object() && Coerce::truthy(model.get("id")))
            .map(|model| Coerce::str_of(model.get("id")))
            .collect();
        (!ids.is_empty()).then_some(ids)
    }

    fn cached_model(model: &Value) -> Value {
        let id = model.get("id").cloned().unwrap_or(Value::Null);
        let name = model.get("name").filter(|said| Coerce::truthy(Some(*said))).cloned().unwrap_or_else(|| id.clone());
        let mut row = json!({"id": id, "name": name});
        if let Some(window) = model.get("contextLength").filter(|said| !said.is_null()) {
            Coerce::put(&mut row, "contextLength", window.clone());
        }
        row
    }

    /// An account's list kept.
    pub fn store_models(&self, account_id: &str, models: &[Value]) {
        let rows: Vec<Value> =
            models.iter().filter(|model| model.is_object() && Coerce::truthy(model.get("id"))).map(Self::cached_model).collect();
        let now = self.app.now() as i64;
        self.mutate(|data| {
            if data.get("accounts").is_none() {
                Coerce::put(data, "accounts", json!({}));
            }
            if let Some(accounts) = data.get_mut("accounts") {
                Coerce::put(accounts, account_id, json!({"models": rows, "fetchedAt": now}));
            }
        });
    }

    /// Whether an account's list is old enough to ask again.
    pub fn models_stale(&self, account_id: &str) -> bool {
        match self.cached_models_entry(account_id).filter(|entry| Coerce::truthy(Some(entry))) {
            None => true,
            Some(entry) => self.app.now() - Self::float_of(&entry, "fetchedAt") > Self::MODELS_TTL_SEC,
        }
    }

    /// An account's list refreshed in a thread of its own, at most one per account. A failure is the breaker's to count.
    pub fn kick_refresh(&self, account_id: &str) {
        let Some(app) = self.app.shared() else {
            return;
        };
        {
            let mut going = app.catalog.refreshing.lock().unwrap_or_else(PoisonError::into_inner);
            if !going.insert(account_id.to_string()) {
                return;
            }
        }
        let account = account_id.to_string();
        let name = format!("model-catalog-{account}");
        let started = std::thread::Builder::new().name(name).spawn({
            let app = app.clone();
            let account = account.clone();
            move || {
                if let Ok(models) = CloudApi::of(&app).refresh_account_models(&account, None) {
                    ModelCatalog::of(&app).store_models(&account, &models);
                }
                app.catalog.refreshing.lock().unwrap_or_else(PoisonError::into_inner).remove(&account);
            }
        });
        if started.is_err() {
            app.catalog.refreshing.lock().unwrap_or_else(PoisonError::into_inner).remove(&account);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_speaker_or_a_picture_is_no_chat() {
        let chat = ChatModels::new().unwrap();
        for model in ["gpt-5.4", "claude-sonnet-4-6", "deepseek-flash", "imagine-3"] {
            assert!(chat.is_chat(model), "{model}");
        }
        for model in
            ["tts-1", "whisper-1", "text-embedding-3", "gpt-4o-realtime-preview", "openai/dall-e-3", "gpt-image-1", "IMAGE"]
        {
            assert!(!chat.is_chat(model), "{model}");
        }
    }

    #[test]
    fn versions_are_compared_as_numbers() {
        assert!(ModelCatalog::version_numbers("0.161.0") > ModelCatalog::version_numbers("0.160.0"));
        assert!(ModelCatalog::version_numbers("0.99.0") < ModelCatalog::version_numbers("0.160.0"));
        assert_eq!(ModelCatalog::version_numbers("beta"), vec![0]);
    }
}
