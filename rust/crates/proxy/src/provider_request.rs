//! What goes out to a provider on one leg: its address, its fields and its body, by who it goes to. What the request is once said is another
//! object's: `ProviderCall`.

use crate::exchange::Asked;
use crate::pool_steps::CloudRow;
use crate::proxy::Proxy;
use crate::stop::{Ending, UpstreamEnd};
use files::{AuthField, Settings};
use net::Target;
use rules::{
    BaseUrl, ChatToAnthropic, ChatToResponses, Credentials, EffortSwap, ProviderBodyWords, RequestFields, ResponsesPassthrough,
};
use serde_json::{Value, json};
use std::collections::hash_map::RandomState;
use std::hash::{BuildHasher, Hasher};

/// Who a request is translated for, and what its answer needs to come back.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Flavor {
    /// A provider that speaks OpenAI's API: the body goes as it came, naming the row's model, and its answer comes back as it is.
    Plain,
    /// A ChatGPT subscription, for a client that speaks the Responses API already.
    SubscriptionResponses {
        /// Whether the client wants a stream: the backend always streams, and one that does not gets the final response.
        client_stream: bool,
    },
    /// A ChatGPT subscription, for a chat's client: its stream becomes chat completion chunks.
    SubscriptionChat {
        /// The id of the chunks.
        completion_id: String,
        /// The model they name.
        model: String,
    },
    /// Anthropic's Messages API, for a chat's client.
    Anthropic {
        /// The id of the chunks.
        completion_id: String,
        /// The model they name.
        model: String,
    },
}

/// What goes out on one leg.
#[derive(Debug)]
pub struct ProviderRequest {
    /// Where to.
    pub target: Target,
    /// The path and the query.
    pub path: String,
    /// The fields, `Host` first.
    pub fields: Vec<(String, Vec<u8>)>,
    /// The body.
    pub body: Vec<u8>,
    /// Who it is for.
    pub flavor: Flavor,
    /// The effort sent in place of the one asked.
    pub swap: Option<EffortSwap>,
    host: String,
}

impl ProviderRequest {
    /// The client's fields that do not go to a provider: its key opens a route here, what the home's nginx says is the home's, and the rest
    /// are said below by the caravan. `Expect` has been answered by this side: the body comes in one piece.
    const KEPT_OUT: [&'static str; 23] = [
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
        "x-forwarded-for",
        "x-forwarded-proto",
        "x-real-ip",
        "host",
        "authorization",
        "x-api-key",
        "chatgpt-account-id",
        "originator",
        "openai-beta",
        "accept",
        "content-length",
        "content-type",
        "accept-encoding",
        "accept-language",
        "expect",
    ];

    /// The request of a leg to `row`. An account with no usable credential, or an address that does not read, is the leg's failure.
    pub fn build(proxy: &Proxy, settings: &Settings, row: &CloudRow, asked: &Asked, path: &str) -> Result<Self, Ending> {
        let auth = proxy
            .access
            .field_for(&row.provider)
            .ok_or_else(|| Self::failure("cloud account missing credential (API key or OAuth)"))?;
        let place = BaseUrl::read(&row.provider.base_url).ok_or_else(|| Self::failure("cloud account baseUrl invalid"))?;
        let mut draft = Draft::new(settings, row, &place, asked, path, auth);
        let (send_path, body, flavor) = if row.provider.subscription {
            draft.for_subscription()?
        } else if row.provider.anthropic && path.ends_with("/chat/completions") {
            draft.for_anthropic()?
        } else {
            draft.for_plain()
        };
        let (body, swap) = match proxy.efforts.fit(&place.host, &body) {
            Some((fitted, swap)) => (fitted, Some(swap)),
            None => (body, None),
        };
        draft.say("Content-Length", body.len().to_string().as_bytes());
        draft.say("Accept-Encoding", b"identity");
        Ok(Self {
            target: Target { tls: place.tls, host: place.host.clone(), port: place.port },
            path: send_path,
            fields: draft.fields,
            body,
            flavor,
            swap,
            host: place.host.clone(),
        })
    }

    fn failure(words: &str) -> Ending {
        Ending::Upstream(UpstreamEnd { words: words.to_string(), kind: "proxy_error" })
    }

    /// The provider's host: whose list of efforts this leg's body is fitted to.
    pub fn host(&self) -> &str {
        &self.host
    }

    /// What the journal keeps of the body: `cloudMeta`.
    pub fn meta(&self) -> Option<Value> {
        ProviderBodyWords::of(&self.body)
    }

    /// What the journal keeps of the fields: `cloudHeaders`. A key is no word of a journal: `JournalHeaders`. `Accept-Encoding` never was in
    /// the journal.
    pub fn fields_for_journal(&self) -> Value {
        let mut out = serde_json::Map::new();
        for (name, value) in self.fields.iter().filter(|(name, _)| !name.eq_ignore_ascii_case("accept-encoding")) {
            let text = String::from_utf8_lossy(value);
            let said = if name.eq_ignore_ascii_case("authorization") || name.eq_ignore_ascii_case("x-api-key") {
                let shown: String = text.chars().rev().take(4).collect::<Vec<_>>().into_iter().rev().collect();
                format!("...{shown}")
            } else {
                text.into_owned()
            };
            out.insert(name.clone(), json!(said));
        }
        Value::Object(out)
    }

    /// The request as it goes on the wire.
    pub fn bytes(&self, method: &str) -> Vec<u8> {
        let mut out = Vec::with_capacity(1024 + self.body.len());
        out.extend_from_slice(format!("{method} {} HTTP/1.1\r\n", self.path).as_bytes());
        for (name, value) in &self.fields {
            out.extend_from_slice(name.as_bytes());
            out.extend_from_slice(b": ");
            out.extend_from_slice(value);
            out.extend_from_slice(b"\r\n");
        }
        out.extend_from_slice(b"\r\n");
        out.extend_from_slice(&self.body);
        out
    }
}

/// A leg's request in the making: what each kind of provider says on top of what they all share.
struct Draft<'a> {
    fields: Vec<(String, Vec<u8>)>,
    auth: AuthField,
    row: &'a CloudRow,
    place: &'a BaseUrl,
    asked: &'a Asked,
    path: &'a str,
    model: Option<&'a str>,
}

impl<'a> Draft<'a> {
    const CODEX_PATH: &'static str = "/backend-api/codex/responses";
    const FALLBACK_TYPE: &'static str = "application/json";
    const FALLBACK_SUBSCRIPTION_MODEL: &'static str = "gpt-5.4-mini";
    const FALLBACK_ANTHROPIC_MODEL: &'static str = "claude-opus-4-8";

    fn new(settings: &Settings, row: &'a CloudRow, place: &'a BaseUrl, asked: &'a Asked, path: &'a str, auth: AuthField) -> Self {
        let mut fields = vec![("Host".to_string(), place.netloc.clone().into_bytes())];
        let kept = asked
            .headers
            .iter()
            .filter(|field| !ProviderRequest::KEPT_OUT.iter().any(|name| field.name.eq_ignore_ascii_case(name)));
        fields.extend(kept.map(|field| (field.name.clone(), field.value.clone())));
        settings.client_name.say(&mut fields);
        let model = Some(row.model.as_str()).filter(|model| !model.is_empty());
        Self { fields, auth, row, place, asked, path, model }
    }

    fn say(&mut self, name: &str, value: &[u8]) {
        self.fields.retain(|(said, _)| !said.eq_ignore_ascii_case(name));
        self.fields.push((name.to_string(), value.to_vec()));
    }

    /// What the account adds to every request, and its credential.
    fn say_credential(&mut self) {
        let row = self.row;
        for (name, value) in row.provider.extra_fields() {
            self.say(name, value.as_bytes());
        }
        let (name, value) = self.auth.clone();
        self.say(&name, value.as_bytes());
    }

    fn query(&self) -> String {
        self.asked.target.split_once('?').map_or(String::new(), |(_, query)| format!("?{query}"))
    }

    /// A chunk's id: nobody reads it for more than telling two answers apart.
    fn completion_id() -> String {
        let state = RandomState::new();
        let (mut one, mut two) = (state.build_hasher(), state.build_hasher());
        one.write_u8(1);
        two.write_u8(2);
        format!("chatcmpl-{:016x}{:08x}", one.finish(), two.finish() as u32)
    }

    fn model_said(body: &[u8]) -> Option<String> {
        let said = rules::RequestJson::read(body)?;
        said.get("model").and_then(Value::as_str).filter(|model| !model.is_empty()).map(str::to_string)
    }

    /// The client speaks Responses already and its body goes as written, or a chat request is translated. The backend takes one path.
    fn for_subscription(&mut self) -> Result<(String, Vec<u8>, Flavor), Ending> {
        let body = &self.asked.body;
        let (body, flavor) = if ResponsesPassthrough::is_request(self.path, body) {
            let (body, _, client_stream) = ResponsesPassthrough::body(body, self.model);
            (body, Flavor::SubscriptionResponses { client_stream })
        } else {
            let (body, used) = ChatToResponses::body(body, self.model).map_err(|error| ProviderRequest::failure(error.0))?;
            let model = used.unwrap_or_else(|| Self::FALLBACK_SUBSCRIPTION_MODEL.to_string());
            (body, Flavor::SubscriptionChat { completion_id: Self::completion_id(), model })
        };
        let auth = self.auth.1.clone();
        self.say("Authorization", auth.as_bytes());
        // absent-ok: a token that names no account goes with an empty field: the backend says what it thinks.
        let claim = Credentials::account_claim(auth.strip_prefix("Bearer ").unwrap_or_default()).unwrap_or_default();
        self.say("chatgpt-account-id", claim.as_bytes());
        self.say("originator", b"pi");
        self.say("OpenAI-Beta", b"responses=experimental");
        self.say("Accept", b"text/event-stream");
        self.say("Content-Type", b"application/json");
        Ok((Self::CODEX_PATH.to_string(), body, flavor))
    }

    fn for_anthropic(&mut self) -> Result<(String, Vec<u8>, Flavor), Ending> {
        self.say_credential();
        let base = self.place.path.trim_end_matches('/');
        let named = self
            .model
            .map(str::to_string)
            .or_else(|| Self::model_said(&self.asked.body))
            .unwrap_or_else(|| Self::FALLBACK_ANTHROPIC_MODEL.to_string());
        let body = ChatToAnthropic::body(&self.asked.body, self.model).map_err(|error| ProviderRequest::failure(error.0))?;
        self.say("Content-Type", b"application/json");
        self.say("Accept", b"application/json");
        Ok((
            format!("{base}/messages{}", self.query()),
            body,
            Flavor::Anthropic { completion_id: Self::completion_id(), model: named },
        ))
    }

    fn for_plain(&mut self) -> (String, Vec<u8>, Flavor) {
        self.say_credential();
        let content_type = self.asked.headers.text_of("Content-Type");
        let body = match self.model {
            Some(model) => RequestFields::model_named(self.asked.body.clone(), model, &content_type),
            None => self.asked.body.clone(),
        };
        let kind = if content_type.is_empty() { Self::FALLBACK_TYPE } else { content_type.as_str() };
        self.say("Content-Type", kind.as_bytes());
        if let Some(accept) = self.asked.headers.get("Accept").filter(|accept| !accept.is_empty()) {
            self.say("Accept", accept.as_bytes());
        }
        (format!("{}{}", self.place.upstream_path(self.path), self.query()), body, Flavor::Plain)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_journal_keeps_no_key_of_any_field() {
        let request = ProviderRequest {
            target: Target { tls: true, host: "x".to_string(), port: 443 },
            path: "/p".to_string(),
            fields: vec![
                ("Authorization".to_string(), b"Bearer secret-token-WXYZ".to_vec()),
                ("x-api-key".to_string(), b"secret-key-ABCD".to_vec()),
                ("Host".to_string(), b"x".to_vec()),
            ],
            body: br#"{"model":"m","tools":[1,2],"messages":[1]}"#.to_vec(),
            flavor: Flavor::Plain,
            swap: None,
            host: "x".to_string(),
        };
        let said = request.fields_for_journal().to_string();
        assert!(!said.contains("secret"), "{said}");
        assert_eq!(request.fields_for_journal(), json!({"Authorization": "...WXYZ", "x-api-key": "...ABCD", "Host": "x"}));
        assert_eq!(request.meta(), Some(json!({"model": "m", "toolCount": 2, "inputCount": 1})));
        let host = request.fields.iter().find(|(said, _)| said.eq_ignore_ascii_case("host"));
        assert_eq!(host.map(|(_, value)| value.as_slice()), Some(b"x".as_slice()));
    }
}
