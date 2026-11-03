//! Talking to caravan-scout on a client machine. A failure is said in words a person reads on the board, naming the machine.

use crate::app::App;
use crate::store::topology::Topology;
use plumbing::http_client::HttpError;
use rules::{AppError, Coerce, PythonJson};
use serde_json::{Value, json};
use std::time::Duration;

/// The fleet token's field: a scout that holds a token asks for it.
pub struct ScoutAuth;

impl ScoutAuth {
    /// The field for controller→scout calls; none while accounts are off.
    pub fn fields(app: &App) -> Vec<(&'static str, String)> {
        if !app.auth.enabled().unwrap_or(false) {
            return Vec::new();
        }
        match app.auth.fleet_token() {
            Ok(token) if !token.is_empty() => vec![("X-Caravan-Token", token)],
            _ => Vec::new(),
        }
    }
}

/// The scout of one machine.
pub struct ScoutCall<'app> {
    app: &'app App,
    host_id: String,
    agent_url: String,
}

impl<'app> ScoutCall<'app> {
    /// The scout of a machine that reported, at the address it reported.
    pub fn of_host(app: &'app App, host_id: &str) -> Result<Self, AppError> {
        let host_id = Coerce::strip(host_id).to_string();
        if host_id.is_empty() {
            return Err(AppError::new("hostId is required"));
        }
        let host = app.admin.change(|doc| Topology::of(doc).hosts().get(&host_id).cloned());
        let host = host
            .filter(|host| Coerce::truthy(Some(host)))
            .ok_or_else(|| AppError::with_status(format!("no scout has reported for host {host_id}"), 404))?;
        let agent_url = Coerce::text(host.get("agentUrl")).trim_end_matches('/').to_string();
        if agent_url.is_empty() {
            return Err(AppError::new(format!("host {host_id} reported no scout address")));
        }
        Ok(Self { app, host_id, agent_url })
    }

    /// The scout's own words from an error's body; else the body; else the status.
    fn reason(failure: &HttpError) -> String {
        if let HttpError::Status(_, said) = failure {
            let parsed: Option<Value> = serde_json::from_str(said).ok();
            let words = parsed.as_ref().and_then(|parsed| parsed.get("error")).filter(|words| Coerce::truthy(Some(*words)));
            return match words {
                Some(words) => Coerce::str_of(Some(words)),
                None if !said.is_empty() => said.clone(),
                None => failure.to_string(),
            };
        }
        failure.to_string()
    }

    fn words_of(&self, failure: &HttpError) -> String {
        match failure {
            HttpError::Status(..) => format!("{}: {}", self.host_id, Self::reason(failure)).trim().to_string(),
            HttpError::Io(error) if error.kind() == std::io::ErrorKind::InvalidData => {
                format!("{} answered with an unusable reply: {error}", self.host_id)
            }
            other => format!("{} unreachable: {other}", self.host_id),
        }
    }

    fn parse(raw: &[u8]) -> Result<Value, HttpError> {
        if raw.is_empty() {
            return Ok(json!({"ok": true}));
        }
        serde_json::from_slice(raw).map_err(|error| HttpError::Io(std::io::Error::new(std::io::ErrorKind::InvalidData, error)))
    }

    /// Calls the scout; a failure is a legible refusal.
    pub fn post(&self, path: &str, payload: &Value, timeout: u64) -> Result<Value, AppError> {
        let mut fields = vec![("Content-Type", "application/json".to_string())];
        fields.extend(ScoutAuth::fields(self.app));
        let url = format!("{}{path}", self.agent_url);
        let body = PythonJson::spaced(payload);
        let answer = self.app.http.ask("POST", &url, &fields, body.as_bytes(), Duration::from_secs(timeout));
        let said = answer.and_then(|answer| answer.text(64 << 20).map_err(HttpError::Io)).and_then(|raw| Self::parse(&raw));
        said.map_err(|failure| AppError::with_status(self.words_of(&failure), 502))
    }

    /// Asks the scout for something; a failure is an answer that says so.
    pub fn read(&self, path: &str, timeout: u64) -> Value {
        let fields = ScoutAuth::fields(self.app);
        let url = format!("{}{path}", self.agent_url);
        let answer = self.app.http.ask("GET", &url, &fields, &[], Duration::from_secs(timeout));
        let said = answer.and_then(|answer| answer.text(64 << 20).map_err(HttpError::Io)).and_then(|raw| Self::parse(&raw));
        said.unwrap_or_else(|failure| json!({"ok": false, "error": self.words_of(&failure)}))
    }

    /// The machine it stands on.
    pub fn host_id(&self) -> &str {
        &self.host_id
    }

    /// The address it reported.
    pub fn agent_url(&self) -> &str {
        &self.agent_url
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_refusal_says_the_scout_s_own_words() {
        let reason = |said: &str| ScoutCall::reason(&HttpError::Status(500, said.to_string()));
        assert_eq!(reason(r#"{"error": "no disk"}"#), "no disk");
        assert_eq!(reason("plain words"), "plain words");
        assert_eq!(reason(r#"{"other": 1}"#), r#"{"other": 1}"#);
        assert_eq!(reason(""), "HTTP Error 500: Internal Server Error");
    }
}
