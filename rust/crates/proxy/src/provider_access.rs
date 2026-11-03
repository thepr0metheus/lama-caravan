//! What it takes to reach a provider outside a request's own leg: the connection's trust, the field a request goes with, a renewed token and
//! an account's usage page.

use crate::clock::Clock;
use crate::log::Log;
use crate::pool_steps::UsagePages;
use files::{AuthField, CredentialVault, Settings};
use net::{Dial, Stream, TlsError, TrustedRoots};
use rules::{BaseUrl, CloudProvider, Credentials};
use serde_json::Value;
use std::io::{self, BufReader, Read, Write};
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;
use wire::{AnswerBody, AnswerHeadReader, Percent};

/// The credential document, the trusted certificates and the clock.
pub struct ProviderAccess {
    vault: CredentialVault,
    /// The certificates, or why there are none: said at start, and said again by each provider's leg that needs them.
    roots: Result<TrustedRoots, TlsError>,
    clock: Arc<dyn Clock>,
}

impl ProviderAccess {
    const USAGE_PATH: &'static str = "/backend-api/wham/usage";
    /// How long the usage page is waited for.
    const PAGE_TIMEOUT: Duration = Duration::from_secs(10);
    /// How long a token's renewal is waited for.
    const RENEW_TIMEOUT: Duration = Duration::from_secs(15);
    /// The most read of either answer.
    const ANSWER_MAX: u64 = 1 << 20;

    /// The access through the document at `secrets`, trusting `cert_file` or the system's certificates.
    pub fn new(secrets: PathBuf, cert_file: Option<PathBuf>, clock: Arc<dyn Clock>) -> Self {
        let roots = TrustedRoots::read(cert_file);
        match &roots {
            Ok(roots) => Log::line(&format!("caravan-proxy: {}", roots.said())),
            Err(error) => Log::line(&format!("caravan-proxy: no provider can be reached over TLS: {}", error.0)),
        }
        Self { vault: CredentialVault::new(secrets), roots, clock }
    }

    /// The certificates a provider's is checked against.
    pub fn roots(&self) -> io::Result<&TrustedRoots> {
        self.roots.as_ref().map_err(|error| io::Error::new(io::ErrorKind::NotFound, error.0.clone()))
    }

    /// The field a request to `provider` goes with, a token near its end renewed first; `None`: no usable credential.
    pub fn field_for(&self, provider: &CloudProvider) -> Option<AuthField> {
        self.vault.field_for(provider, self.clock.epoch() as i64, &|url, form| self.renew(url, form))
    }

    fn renew(&self, url: &str, form: &[(&str, &str)]) -> io::Result<Value> {
        let place =
            BaseUrl::read(url).ok_or_else(|| io::Error::new(io::ErrorKind::InvalidInput, "the token's address does not read"))?;
        let body: Vec<String> = form.iter().map(|(name, value)| format!("{name}={}", Percent::encode(value))).collect();
        let fields =
            [("Content-Type", "application/x-www-form-urlencoded".to_string()), ("Accept", "application/json".to_string())];
        let (status, answer) = self.ask(&place, "POST", &place.path, &fields, body.join("&").as_bytes(), Self::RENEW_TIMEOUT)?;
        if status >= 400 {
            return Err(io::Error::other(format!("the renewal was refused: {status}")));
        }
        serde_json::from_slice(&answer).map_err(io::Error::other)
    }

    /// One question and its whole answer, on a connection of its own.
    fn ask(
        &self,
        place: &BaseUrl,
        method: &str,
        path: &str,
        fields: &[(&str, String)],
        body: &[u8],
        timeout: Duration,
    ) -> io::Result<(u16, Vec<u8>)> {
        let socket = Dial { turn: timeout, limit: timeout }.open::<io::Error>(&place.host, place.port, &mut || Ok(()))?;
        socket.set_read_timeout(Some(timeout))?;
        socket.set_write_timeout(Some(timeout))?;
        let mut stream = if place.tls {
            self.roots()?.wrap::<io::Error>(socket, &place.host, &mut || {
                Err(io::Error::new(io::ErrorKind::TimedOut, "the handshake timed out"))
            })?
        } else {
            Stream::Plain(socket)
        };
        let mut head =
            format!("{method} {path} HTTP/1.1\r\nHost: {}\r\nConnection: close\r\nAccept-Encoding: identity\r\n", place.netloc);
        for (name, value) in fields {
            head.push_str(&format!("{name}: {value}\r\n"));
        }
        if !body.is_empty() {
            head.push_str(&format!("Content-Length: {}\r\n", body.len()));
        }
        head.push_str("\r\n");
        stream.write_all(head.as_bytes())?;
        stream.write_all(body)?;
        stream.flush()?;
        let mut source = BufReader::new(stream);
        let answer_head = AnswerHeadReader::new().read(&mut source)?;
        let mut out = Vec::new();
        AnswerBody::new(source, &answer_head, method).take(Self::ANSWER_MAX).read_to_end(&mut out)?;
        Ok((answer_head.status, out))
    }
}

impl UsagePages for ProviderAccess {
    fn page(&self, settings: &Settings, provider: &CloudProvider) -> Option<Value> {
        let (_, auth) = self.field_for(provider)?;
        let place = BaseUrl::read(&provider.base_url)?;
        // absent-ok: a token that names no account goes with an empty field.
        let account = auth.strip_prefix("Bearer ").and_then(Credentials::account_claim).unwrap_or_default();
        let mut fields = vec![
            ("Accept", "application/json".to_string()),
            ("Authorization", auth),
            ("originator", "pi".to_string()),
            ("chatgpt-account-id", account),
        ];
        if let Some(name) = settings.client_name.word() {
            fields.push(("User-Agent", name.to_string()));
        }
        let (status, answer) = self.ask(&place, "GET", Self::USAGE_PATH, &fields, &[], Self::PAGE_TIMEOUT).ok()?;
        if status >= 400 {
            return None;
        }
        serde_json::from_slice(&answer).ok()
    }
}

/// `Arc<ProviderAccess>` as the pools' way to a usage page: both the pools and the requests hold the one access.
pub struct SharedAccess(pub Arc<ProviderAccess>);

impl UsagePages for SharedAccess {
    fn page(&self, settings: &Settings, provider: &CloudProvider) -> Option<Value> {
        self.0.page(settings, provider)
    }
}
