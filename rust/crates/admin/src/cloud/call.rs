//! A call of the controller's own to a provider. Which fields it goes with is the account's and the operator's; what it answers is the caller's.

use crate::app::App;
use plumbing::http_client::HttpError;
use rules::ClientName;
use serde_json::Value;
use std::io;
use std::time::Duration;
use wire::Percent;

/// Fields in the order they go.
pub type Fields = Vec<(String, String)>;

/// What a failed call says of itself: whether any answer came decides what the breaker counts.
pub struct UpstreamFailure {
    /// What the caller is told.
    pub error: rules::AppError,
    /// No answer came at all: the network's fault, not the endpoint's.
    pub network: bool,
}

impl UpstreamFailure {
    /// A failure the provider answered with.
    pub fn answered(error: rules::AppError) -> Self {
        Self { error, network: false }
    }

    /// A failure with no answer.
    pub fn silent(error: rules::AppError) -> Self {
        Self { error, network: true }
    }
}

/// The controller's calls to the providers.
pub struct Upstream<'app> {
    app: &'app App,
}

impl<'app> Upstream<'app> {
    /// The calls of this controller.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    /// The name the operator set for every client, from the proxy's settings file: this call holds no policy of its own.
    pub fn client_name(&self) -> ClientName {
        let raw = std::fs::read(&self.app.paths.agent_proxy_config_file).ok();
        let said = raw.and_then(|raw| serde_json::from_slice::<Value>(&raw).ok());
        ClientName::read(said.as_ref().and_then(|said| said.get("policy")))
    }

    /// `fields` as they go out: the operator's name in place of any other.
    pub fn named(&self, fields: Fields) -> Fields {
        let mut said: Vec<(String, Vec<u8>)> = fields.into_iter().map(|(name, value)| (name, value.into_bytes())).collect();
        self.client_name().say(&mut said);
        said.into_iter().map(|(name, value)| (name, String::from_utf8_lossy(&value).into_owned())).collect()
    }

    /// The JSON a provider answers.
    pub fn json(&self, method: &str, url: &str, fields: &Fields, body: &[u8], timeout: Duration) -> Result<Value, HttpError> {
        let asked: Vec<(&str, String)> = fields.iter().map(|(name, value)| (name.as_str(), value.clone())).collect();
        self.app.http.json(method, url, &asked, body, timeout)
    }

    /// `urlencode(pairs)`.
    pub fn form(pairs: &[(&str, &str)]) -> String {
        let plus = |text: &str| Percent::encode(text).replace("%20", "+");
        pairs.iter().map(|(name, value)| format!("{}={}", plus(name), plus(value))).collect::<Vec<_>>().join("&")
    }

    /// The token endpoint's answer to a form: what a renewal and a sign-in both post.
    pub fn post_form(&self, url: &str, pairs: &[(&str, &str)], timeout: Duration) -> Result<Value, HttpError> {
        let fields = vec![("Content-Type".to_string(), "application/x-www-form-urlencoded".to_string())];
        self.json("POST", url, &fields, Self::form(pairs).as_bytes(), timeout)
    }

    /// What `CredentialVault` asks a new token with.
    pub fn renew(&self, url: &str, pairs: &[(&str, &str)]) -> io::Result<Value> {
        self.post_form(url, pairs, Duration::from_secs(15)).map_err(|error| io::Error::other(error.to_string()))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_form_is_written_as_urlencode_writes_it() {
        assert_eq!(Upstream::form(&[("a b", "c/d"), ("e", "f g&h")]), "a+b=c%2Fd&e=f+g%26h");
    }
}
