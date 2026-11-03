//! A pool's own ports are gone (the owner, 2026-10-12).

use crate::app::App;
use crate::proxies::config::ProxiesConfig;
use rules::Coerce;
use serde_json::{Value, json};

/// Takes the pools' own ports out of the proxy's settings, at the controller's start.
pub struct PoolPortsRetired;

impl PoolPortsRetired {
    fn is_pool_port(route: &Value) -> bool {
        route.is_object() && Coerce::stripped(route.get("kind")).to_lowercase() == "service"
    }

    /// Every pool's own port leaves the file; those that left, or `None` when none was there.
    pub fn migrate(app: &App) -> Result<Option<Value>, rules::AppError> {
        let config = ProxiesConfig::of(app);
        let mut payload = config.read_payload();
        let Some(routes) = payload.get("routes").and_then(Value::as_array).cloned() else {
            return Ok(None);
        };
        let (gone, kept): (Vec<Value>, Vec<Value>) = routes.into_iter().partition(Self::is_pool_port);
        if gone.is_empty() {
            return Ok(None);
        }
        Coerce::put(&mut payload, "routes", Value::Array(kept));
        config.write_payload(payload)?;
        let rows: Vec<Value> = gone
            .iter()
            // absent-ok: `int(route.get("port") or 0)`, with 0 for what is no number: the row only reports what left.
            .map(|route| json!({"port": Coerce::whole(route.get("port")), "label": Coerce::text(route.get("label")), "pool": Coerce::text(route.get("providerId"))}))
            .collect();
        Ok(Some(Value::Array(rows)))
    }
}
