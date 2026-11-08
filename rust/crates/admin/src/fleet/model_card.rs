//! What a port answers a client on `GET /v1/models`, asked on the operator's behalf.

use crate::app::App;
use crate::common::window::Windows;
use crate::proxies::client_ids::ClientIds;
use crate::proxies::config::ProxiesConfig;
use crate::topology::windows::PortQuestion;
use rules::{AppError, Coerce};
use serde_json::{Map, Value, json};
use std::time::Duration;

/// The card of one port.
pub struct ModelCard<'app> {
    app: &'app App,
}

impl<'app> ModelCard<'app> {
    const CONTEXT_KEYS: [&'static str; 10] = [
        "context_length",
        "max_model_len",
        "context_window",
        "max_context_length",
        "max_position_embeddings",
        "max_input_tokens",
        "max_sequence_length",
        "max_seq_len",
        "n_ctx",
        "ctx_size",
    ];
    const READ_MOST: u64 = 200_000;
    const RAW_SHOWN: usize = 100_000;
    const ALIASES_SHOWN: usize = 8;

    /// The view.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    /// `isinstance(x, int)`: a whole number; `True` is one in Python, and no card says it.
    fn whole(value: Option<&Value>) -> Option<&Value> {
        value.filter(|value| value.is_i64() || value.is_u64())
    }

    /// A flat digest of one `data[]` entry.
    fn entry_summary(entry: &Value) -> Value {
        let mut windows = Map::new();
        for key in Self::CONTEXT_KEYS {
            if let Some(said) = Self::whole(entry.get(key)) {
                windows.insert(key.to_string(), said.clone());
            }
        }
        let first = windows.values().next().cloned();
        let served = entry.get("meta").filter(|meta| meta.is_object()).and_then(|meta| Self::whole(meta.get("n_ctx"))).cloned();
        let aliases: Vec<&Value> =
            entry.get("aliases").and_then(Value::as_array).into_iter().flatten().filter(|alias| alias.is_string()).collect();
        let aliases: Vec<&Value> = aliases.into_iter().take(Self::ALIASES_SHOWN).collect();
        json!({
            "id": Coerce::text(entry.get("id")),
            "ownedBy": Coerce::text(entry.get("owned_by")),
            "created": entry.get("created"),
            "windows": windows,
            "window": first,
            "servedWindow": served,
            "trainedWindow": Windows::trained(entry),
            "aliases": aliases,
        })
    }

    /// Every path on which this port states its window, as links.
    fn window_links(route: &Value, config: &Value, base: &str, entries: &[Value]) -> Vec<Value> {
        let reaches = PortQuestion::reaches(&PortQuestion::answer(route, config));
        let ids: Vec<String> = entries.iter().map(|entry| Coerce::text(entry.get("id"))).filter(|id| !id.is_empty()).collect();
        Windows::paths(&reaches, &ids)
            .into_iter()
            .map(|(kind, path)| json!({"kind": kind, "url": format!("{base}{path}")}))
            .collect()
    }

    /// Asks the entry, with this client's key, what it offers this client, and says the parsed answer. A client has no port of its own: the entry is the
    /// one place that answers (the owner, 2026-11-02), and it listens beside the controller. The links name the address a client calls.
    pub fn card(&self, route_id: &str) -> Result<Value, AppError> {
        let config = ProxiesConfig::of(self.app).load()?;
        let routes = config.get("routes").and_then(Value::as_array).into_iter().flatten();
        let route = routes
            .into_iter()
            .find(|route| ClientIds::of(route) == route_id)
            .cloned()
            .ok_or_else(|| AppError::with_status(format!("no client has the id {route_id}"), 404))?;
        // absent-ok: a port not named is an entry that is off, said below.
        let entry_port = Coerce::whole(config.get("entry").and_then(|entry| entry.get("port")));
        let public = Coerce::stripped(config.get("entry").and_then(|entry| entry.get("publicUrl")));
        let own = format!("http://{}:{entry_port}", self.app.paths.topology_server_ip);
        let base = if public.is_empty() { own } else { public.trim_end_matches('/').trim_end_matches("/v1").to_string() };
        let url = format!("{base}/v1/models");
        let key = Coerce::text(route.get("apiKey"));
        let started = self.app.now();
        let (status, raw, mut error) = if entry_port == 0 {
            (0, String::new(), "the entry is off".to_string())
        } else {
            self.asked(&format!("http://127.0.0.1:{entry_port}/v1/models"), &key)
        };
        let took_ms = ((self.app.now() - started) * 1000.0) as i64;
        let payload: Option<Value> = if raw.is_empty() {
            None
        } else {
            match serde_json::from_str(&raw) {
                Ok(parsed) => Some(parsed),
                Err(_) => {
                    if error.is_empty() {
                        error = "the answer is not JSON".to_string();
                    }
                    None
                }
            }
        };
        let rows = payload.as_ref().and_then(|payload| payload.get("data")).and_then(Value::as_array);
        let entries: Vec<Value> = rows.into_iter().flatten().filter(|entry| entry.is_object()).map(Self::entry_summary).collect();
        let links = Self::window_links(&route, &config, &base, &entries);
        let shown: String = raw.chars().take(Self::RAW_SHOWN).collect();
        Ok(json!({
            "ok": status == 200 && error.is_empty(),
            "url": url,
            "label": Coerce::text(route.get("label")),
            "routeId": route_id,
            "keyed": !key.is_empty(),
            "status": status,
            "tookMs": took_ms,
            "error": error,
            "entries": entries,
            "windowLinks": links,
            "raw": shown,
        }))
    }

    /// `(status, the body as words, what went wrong)` of the port's own answer.
    fn asked(&self, url: &str, key: &str) -> (u16, String, String) {
        let mut fields = vec![("Accept", "application/json".to_string())];
        if !key.is_empty() {
            fields.push(("Authorization", format!("Bearer {key}")));
        }
        let answer = match self.app.http.answer("GET", url, &fields, b"", Duration::from_secs(10)) {
            Ok(answer) => answer,
            Err(failure) => return (0, String::new(), failure.to_string()),
        };
        let status = answer.head.status;
        let error = if status >= 400 { format!("HTTP {status}") } else { String::new() };
        match answer.text(Self::READ_MOST) {
            Ok(body) => (status, String::from_utf8_lossy(&body).into_owned(), error),
            Err(failure) if status < 400 => (status, String::new(), failure.to_string()),
            Err(_) => (status, String::new(), error),
        }
    }
}
