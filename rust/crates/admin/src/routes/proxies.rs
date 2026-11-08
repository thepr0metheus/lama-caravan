//! The proxy: its routes, its journal, its numbers, the clients of its entry.

use super::asked::Asked;
use crate::app::App;
use crate::cloud::consumers::ConsumerDesk;
use crate::fleet::model_card::ModelCard;
use crate::proxies::as_consumer::AsConsumer;
use crate::proxies::client_ids::ClientIds;
use crate::proxies::config::{ProxiesConfig, StaleCopy};
use crate::proxies::entry_settings::{ConsumerAddress, EntrySettings, PortDoor};
use crate::proxies::latency::ProxyLatencyDigest;
use crate::proxies::ops::ProxyStops;
use crate::proxies::queue_thresholds::QueueThresholds;
use crate::proxies::stats::{LogQuery, ProxyStats};
use crate::proxies::token_history::TokenHistory;
use crate::web::{Exchange, Routes};
use plumbing::Log;
use rules::{AppError, Coerce};
use serde_json::{Value, json};

/// The routes.
pub struct ProxyRoutes;

impl ProxyRoutes {
    /// The table.
    pub const ROUTES: Routes = Routes {
        get: &[
            ("/api/queue-thresholds", Self::thresholds),
            ("/api/agent-proxies/raw", Self::raw),
            ("/api/token-history", Self::token_history),
            ("/api/agent-proxy-latency", Self::latency),
            ("/api/agent-proxy-entry", Self::entry),
            ("/api/agent-proxy-model-card", Self::model_card),
            ("/api/agent-proxy-logs", Self::logs),
            ("/api/proxy-daily-stats", Self::daily_stats),
            ("/api/consumers/ask", Self::consumer_ask),
        ],
        post: &[
            ("/api/agent-proxies/config", Self::config),
            ("/api/agent-proxies/policy", Self::policy),
            ("/api/agent-proxies/route-policy", Self::route_policy),
            ("/api/agent-proxies/route-delete", Self::route_delete),
            ("/api/agent-proxies/routers", Self::routers),
            ("/api/agent-proxies/switchboards", Self::routers),
            ("/api/agent-proxies/stop", Self::stop),
            ("/api/queue-thresholds/recalc", Self::recalc),
            ("/api/agent-proxy-entry", Self::set_entry),
            ("/api/consumers/probe", Self::consumer_probe),
            ("/api/consumers/create", Self::consumer_create),
            ("/api/consumers/deny", Self::consumer_deny),
            ("/api/consumers/key", Self::consumer_key),
        ],
        delete: &[],
    };

    /// The client a query names by its record's id; a query that still names a port is refused.
    fn route_asked(h: &Exchange<'_>) -> Result<String, AppError> {
        ClientIds::asked(Some(&json!(Asked::word(h, "routeId"))), h.parsed.param("port").is_some())
    }

    /// The client a query may name, as a filter: `None` for every client.
    fn route_filter(h: &Exchange<'_>) -> Result<Option<String>, AppError> {
        if Asked::word(h, "routeId").is_empty() && h.parsed.param("port").is_none() {
            return Ok(None);
        }
        Self::route_asked(h).map(Some)
    }

    /// The client a body names by its record's id; a body that still names a port is refused.
    fn route_in(body: &Value) -> Result<String, AppError> {
        ClientIds::asked(body.get("routeId"), body.get("port").is_some())
    }

    fn thresholds(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        h.ok(&json!({"ok": true, "thresholds": QueueThresholds::of(app).latest()}));
        Ok(())
    }

    fn raw(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        let path = &app.paths.agent_proxy_config_file;
        let content = if path.exists() {
            std::fs::read(path).map_or_else(
                |error| format!("(unable to read {}: {error})", path.display()),
                |raw| String::from_utf8_lossy(&raw).into_owned(),
            )
        } else {
            String::new()
        };
        h.ok(&json!({"ok": true, "path": path.to_string_lossy(), "content": content}));
        Ok(())
    }

    fn token_history(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        let range = Coerce::strip(&h.parsed.param_or("range", "all")).to_string();
        let samples = TokenHistory::of(app).query(&Asked::word(h, "client"), &range, Self::route_filter(h)?.as_deref());
        h.ok(&json!({"samples": samples}));
        Ok(())
    }

    fn latency(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        let route_id = Self::route_asked(h)?;
        let range = Coerce::strip(&h.parsed.param_or("range", "all")).to_string();
        h.ok(&json!({"latency": ProxyLatencyDigest::of(app).summary(&route_id, &range)}));
        Ok(())
    }

    fn entry(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        h.ok(&EntrySettings::of(app).read()?);
        Ok(())
    }

    fn model_card(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        h.ok(&ModelCard::of(app).card(&Self::route_asked(h)?)?);
        Ok(())
    }

    fn logs(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        let asked = LogQuery {
            date: h.parsed.param_or("date", ""),
            limit: h.parsed.param_or("limit", "200"),
            event: h.parsed.param_or("event", ""),
            route_id: Self::route_filter(h)?,
            route: h.parsed.param_or("route", ""),
            client: h.parsed.param_or("client", ""),
            errors: h.parsed.flag("errors", false),
            slim: h.parsed.flag("slim", false),
            summary: h.parsed.flag("summary", false),
            since: h.parsed.param_or("since", ""),
        };
        h.ok(&ProxyStats::of(app).logs(&asked)?);
        Ok(())
    }

    fn daily_stats(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        h.ok(&ProxyStats::of(app).daily_stats(&h.parsed.param_or("date", "")));
        Ok(())
    }

    fn consumer_ask(app: &App, h: &mut Exchange<'_>) -> Result<(), AppError> {
        let route_id = Self::route_asked(h)?;
        let (status, kind, body) = AsConsumer::of(app).ask(&route_id, &h.parsed.param_or("path", ""))?;
        h.send_passed_on(status, AsConsumer::shown_as(&kind), &body);
        Ok(())
    }

    /// A save refused because the page read an older copy: the page takes the board it should have read.
    fn saved_or_stale(app: &App, h: &mut Exchange<'_>, saved: Result<Value, AppError>) -> Result<Option<Value>, AppError> {
        match saved {
            Ok(config) => Ok(Some(config)),
            Err(error) if StaleCopy::is(&error) => {
                h.send_json(&json!({"error": error.message, "stale": true, "topology": Asked::board(app)?}), 409);
                Ok(None)
            }
            Err(error) => Err(error),
        }
    }

    fn config(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        let routes = body.get("routes").filter(|routes| Coerce::truthy(Some(*routes))).cloned().unwrap_or_else(|| json!([]));
        let saved = ProxiesConfig::of(app).save(routes, body.get("routers").cloned(), body.get("revision"));
        if let Some(config) = Self::saved_or_stale(app, h, saved)? {
            Asked::send_with_monitor(app, h, json!({"ok": true, "config": config}));
        }
        Ok(())
    }

    /// The thresholds follow the policy; the answer does not wait for them.
    fn recompute_in_background(app: &App) {
        let Some(shared) = app.shared() else {
            return;
        };
        let started = std::thread::Builder::new().name("queue-thresholds".to_string()).spawn(move || {
            QueueThresholds::of(&shared).compute();
        });
        if let Err(error) = started {
            Log::line(&format!("queue thresholds: not recomputed: {error}"));
        }
    }

    fn policy(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        let said = body.get("policy").filter(|policy| Coerce::truthy(Some(*policy))).unwrap_or(&body);
        let config = ProxiesConfig::of(app).set_policy(said)?;
        Self::recompute_in_background(app);
        Asked::send_with_monitor(app, h, json!({"ok": true, "config": config}));
        Ok(())
    }

    fn entry_url(app: &App) -> Result<Value, AppError> {
        let config = ProxiesConfig::of(app).load()?;
        let entry = ConsumerAddress::new(&config, &app.paths.topology_server_ip, PortDoor::open(app)).entry();
        Ok(entry.get("url").cloned().unwrap_or(Value::Null))
    }

    /// `{"ok": True, **done, "entryUrl": ..., "topology": ...}`.
    fn send_with_entry(app: &App, h: &mut Exchange<'_>, done: Value) -> Result<(), AppError> {
        let mut out = Asked::ok_with(done);
        Coerce::put(&mut out, "entryUrl", Self::entry_url(app)?);
        Asked::send_with_board(app, h, out)
    }

    fn route_policy(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        let config = ProxiesConfig::of(app).set_route_policy(&Self::route_in(&body)?, &body)?;
        Asked::send_with_monitor(app, h, json!({"ok": true, "config": config}));
        Ok(())
    }

    fn route_delete(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        let result = ProxiesConfig::of(app).delete_route(&Self::route_in(&body)?)?;
        Asked::send_with_fresh_board(app, h, json!({"ok": true, "result": result}))
    }

    fn routers(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        let said = body
            .get("routers")
            .filter(|routers| Coerce::truthy(Some(*routers)))
            .or_else(|| body.get("switchboards").filter(|routers| Coerce::truthy(Some(*routers))));
        let empty = json!([]);
        let saved = ProxiesConfig::of(app).set_routers(said.unwrap_or(&empty), body.get("revision"));
        if let Some(config) = Self::saved_or_stale(app, h, saved)? {
            Asked::send_with_board(app, h, json!({"ok": true, "config": config}))?;
        }
        Ok(())
    }

    fn stop(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        let route_id =
            if body.get("routeId").is_none() && body.get("port").is_none() { None } else { Some(Self::route_in(&body)?) };
        let result = ProxyStops::of(app).stop(route_id.as_deref(), &Coerce::text(body.get("requestId")))?;
        Asked::send_with_monitor(app, h, json!({"ok": true, "result": result}));
        Ok(())
    }

    fn recalc(app: &App, h: &mut Exchange<'_>, _body: Value) -> Result<(), AppError> {
        Self::recompute_in_background(app);
        h.ok(&json!({"ok": true, "thresholds": QueueThresholds::of(app).latest()}));
        Ok(())
    }

    fn set_entry(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        h.ok(&EntrySettings::of(app).write(&body)?);
        Ok(())
    }

    fn consumer_probe(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        h.ok(&Asked::ok_with(AsConsumer::of(app).probe(&Self::route_in(&body)?, body.get("path"), body.get("model"))?));
        Ok(())
    }

    fn consumer_create(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        let done = ConsumerDesk::of(app).create(body.get("name"), &Coerce::text(body.get("kind")))?;
        Self::send_with_entry(app, h, done)
    }

    fn consumer_deny(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        let done = ConsumerDesk::of(app).set_deny(&Self::route_in(&body)?, body.get("deny"))?;
        Asked::send_with_board(app, h, Asked::ok_with(done))
    }

    fn consumer_key(app: &App, h: &mut Exchange<'_>, body: Value) -> Result<(), AppError> {
        let done = ConsumerDesk::of(app).new_key(&Self::route_in(&body)?)?;
        Self::send_with_entry(app, h, done)
    }
}
