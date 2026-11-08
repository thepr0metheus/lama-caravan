//! Cross-domain proxy actions.

use super::client_ids::ClientIds;
use super::config::ProxiesConfig;
use super::stats::ProxyStats;
use crate::app::App;
use rules::{AppError, Coerce};
use serde_json::{Value, json};

/// The stops the board asks of the proxy.
pub struct ProxyStops<'app> {
    app: &'app App,
}

impl<'app> ProxyStops<'app> {
    const KEPT: usize = 100;

    /// The stops of `app`.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    /// One request stopped, or every request of one client (`route_id`).
    pub fn stop(&self, route_id: Option<&str>, request_id: &str) -> Result<Value, AppError> {
        let config = ProxiesConfig::of(self.app);
        let mut payload = config.load()?;
        let routes = Coerce::list(payload.get("routes"));
        let route = match route_id {
            Some(route_id) => Some(
                routes
                    .iter()
                    .find(|row| ClientIds::of(row) == route_id)
                    .cloned()
                    .ok_or_else(|| AppError::with_status(format!("no client has the id {route_id}"), 404))?,
            ),
            None => None,
        };
        let label = |route: &Value| Coerce::text(route.get("label"));
        let mut targets: Vec<(String, String, String)> = Vec::new();
        if !request_id.is_empty() {
            let shown = route.as_ref().map_or_else(String::new, label);
            let id = route.as_ref().map_or_else(String::new, ClientIds::of);
            targets.push((request_id.to_string(), shown, id));
        } else if let Some(route) = &route {
            let id = ClientIds::of(route);
            let state = ProxyStats::of(self.app).sample();
            for row in state.get("agents").and_then(Value::as_object).into_iter().flatten().map(|(_, row)| row) {
                for item in row.get("active").and_then(Value::as_array).into_iter().flatten() {
                    if Coerce::text(item.get("routeId")) == id && Coerce::truthy(item.get("id")) {
                        let said = Coerce::text(item.get("route"));
                        targets.push((
                            Coerce::str_of(item.get("id")),
                            if said.is_empty() { label(route) } else { said },
                            id.clone(),
                        ));
                    }
                }
            }
        }
        let now = self.app.now_whole();
        let stop_rows: Vec<Value> = targets
            .iter()
            .map(|(id, route, route_id)| json!({"id": id, "scope": "request", "route": route, "routeId": route_id, "reason": "manual stop", "requestedAt": now}))
            .collect();
        let held = Coerce::list(payload.get("stopRequests"));
        let mut stops: Vec<Value> =
            held.into_iter().filter(|row| !targets.iter().any(|(id, _, _)| *id == Coerce::text(row.get("id")))).collect();
        stops.extend(stop_rows.iter().cloned());
        let kept = stops.split_off(stops.len().saturating_sub(Self::KEPT));
        Coerce::put(&mut payload, "stopRequests", Value::Array(kept));
        config.write_payload(payload)?;
        Ok(json!({"stopped": stop_rows}))
    }
}
