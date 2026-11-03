//! The scout's `config.json`: what it was set up with, and the pairing that points it at a controller.

use crate::errors::AppError;
use files::AtomicFile;
use os::Host;
use rules::{BaseUrl, Coerce};
use serde_json::{Map, Value, json};
use std::path::{Path, PathBuf};
use std::sync::{Mutex, MutexGuard, PoisonError};

/// `config.json`, read once and merged over the defaults. Read like a document; its writers are `pair` and `unpair`, the only things that
/// change the file on disk.
#[derive(Debug)]
pub struct ScoutConfig {
    path: PathBuf,
    data: Mutex<Map<String, Value>>,
    /// What the file itself says, apart from the defaults: a `hostId` or a `displayName` written there is the operator's choice.
    file: Map<String, Value>,
}

impl ScoutConfig {
    const DEFAULT_PORT: i64 = 8092;
    const DEFAULT_BEAT: i64 = 60;
    const FASTEST_BEAT: i64 = 2;

    /// The config at `path`. A file that is no JSON object is a bad start, and says so.
    pub fn load(path: &Path) -> Result<Self, AppError> {
        // The fleet token is in it: a file older than the rule is narrowed before anything else.
        AtomicFile::narrow(path);
        let host = Host::short_name();
        let mut data = Self::defaults(&host);
        let file = Self::file_of(path)?;
        data.extend(file.clone());
        let port = Coerce::int_or_zero(data.get("listenPort")).filter(|port| *port != 0).unwrap_or(Self::DEFAULT_PORT);
        data.insert("listenPort".to_string(), json!(port));
        let beat =
            Coerce::int_or_zero(data.get("heartbeatIntervalSeconds")).filter(|beat| *beat != 0).unwrap_or(Self::DEFAULT_BEAT);
        data.insert("heartbeatIntervalSeconds".to_string(), json!(beat.max(Self::FASTEST_BEAT)));
        Ok(Self { path: path.to_path_buf(), data: Mutex::new(data), file })
    }

    fn defaults(host: &str) -> Map<String, Value> {
        let defaults = json!({
            "hostId": host, "displayName": host, "listenHost": "0.0.0.0", "listenPort": Self::DEFAULT_PORT, "controllerUrl": "",
            "heartbeatIntervalSeconds": Self::DEFAULT_BEAT, "llamaServerBin": "", "modelsBasePath": "", "llamaNodeDefaultPort": 8180,
        });
        match defaults {
            Value::Object(fields) => fields,
            _ => Map::new(),
        }
    }

    fn file_of(path: &Path) -> Result<Map<String, Value>, AppError> {
        if !path.exists() {
            return Ok(Map::new());
        }
        let text = std::fs::read(path).map_err(|error| AppError::new(format!("config cannot be read: {error}")))?;
        match serde_json::from_slice(&text) {
            Ok(Value::Object(fields)) => Ok(fields),
            Ok(_) => Err(AppError::new("config must be a JSON object")),
            Err(error) => Err(AppError::new(format!("config is no JSON: {error}"))),
        }
    }

    fn data(&self) -> MutexGuard<'_, Map<String, Value>> {
        self.data.lock().unwrap_or_else(PoisonError::into_inner)
    }

    /// A value of the running config.
    pub fn get(&self, key: &str) -> Option<Value> {
        self.data().get(key).cloned()
    }

    /// `str(config.get(key) or "")`.
    pub fn text(&self, key: &str) -> String {
        Coerce::text(self.get(key).as_ref())
    }

    /// Sets a value of the running config, and not of the file: the id this run goes by.
    pub fn set(&self, key: &str, value: Value) {
        self.data().insert(key.to_string(), value);
    }

    /// What `config.json` itself holds for `key`; `None` when only a default supplies it.
    pub fn from_file(&self, key: &str) -> Option<&Value> {
        self.file.get(key)
    }

    /// The fleet token, "" for none.
    pub fn token(&self) -> String {
        Coerce::stripped(self.get("controllerToken").as_ref())
    }

    /// A controller's address as it is stored: with a scheme, without the trailing slash. An error when it is no address at all.
    pub fn controller_address(raw_url: &str) -> Result<String, AppError> {
        let trimmed = Coerce::strip(raw_url);
        let url = if !trimmed.is_empty() && !trimmed.contains("://") { format!("http://{trimmed}") } else { trimmed.to_string() };
        let is_web = url.starts_with("http://") || url.starts_with("https://");
        // Checked before the trailing slash goes: "http://" stripped first was "http:", which gained a second "http://" and passed.
        if url.is_empty() || !is_web || BaseUrl::read(&url).is_none() {
            return Err(AppError::new("controller url must look like http://host:7990"));
        }
        Ok(url.trim_end_matches('/').to_string())
    }

    /// Points the scout at a controller: the address, and a token when one is given, into the raw file and the running config. The address as stored.
    pub fn pair(&self, raw_url: &str, raw_token: &str) -> Result<String, AppError> {
        let url = Self::controller_address(raw_url)?;
        let token = Coerce::strip(raw_token).to_string();
        let mut raw = self.raw();
        raw.insert("controllerUrl".to_string(), json!(url));
        if !token.is_empty() {
            raw.insert("controllerToken".to_string(), json!(token));
        }
        self.write(&raw)?;
        let mut data = self.data();
        data.insert("controllerUrl".to_string(), json!(url));
        if !token.is_empty() {
            data.insert("controllerToken".to_string(), json!(token));
        }
        Ok(url)
    }

    /// Forgets the controller: its address and its token leave the file and the running config; the rest stays.
    pub fn unpair(&self) -> Result<(), AppError> {
        let mut raw = self.raw();
        raw.remove("controllerUrl");
        raw.remove("controllerToken");
        self.write(&raw)?;
        let mut data = self.data();
        data.insert("controllerUrl".to_string(), json!(""));
        data.remove("controllerToken");
        Ok(())
    }

    /// The file as the user's file holds it, without the defaults that do not belong in it; nothing when it is missing or unreadable.
    fn raw(&self) -> Map<String, Value> {
        let read = std::fs::read(&self.path).ok().and_then(|text| serde_json::from_slice::<Value>(&text).ok());
        match read {
            Some(Value::Object(fields)) => fields,
            _ => Map::new(),
        }
    }

    fn write(&self, raw: &Map<String, Value>) -> Result<(), AppError> {
        let text = serde_json::to_string_pretty(raw).map_err(|error| AppError::with_status(error.to_string(), 500))?;
        AtomicFile::write_private(&self.path, format!("{text}\n").as_bytes())
            .map_err(|error| AppError::with_status(format!("config cannot be written: {error}"), 500))
    }
}
