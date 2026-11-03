//! The models of engines next to the cells that the operator made router outputs, and the outputs they become.

use super::controller_machine::ControllerMachine;
use crate::app::App;
use crate::store::admin::AdminStore;
use net::Sha1;
use rules::{AppError, Coerce};
use serde_json::{Map, Value, json};
use std::net::IpAddr;

/// The engine models the operator made router outputs: `eng:<hash>` each.
pub struct EngineOutputs<'app> {
    app: &'app App,
    controller: ControllerMachine,
}

impl<'app> EngineOutputs<'app> {
    const SECTION: &'static str = "engineOutputs";

    /// The outputs of `app`.
    pub fn of(app: &'app App) -> Self {
        Self { app, controller: ControllerMachine::of(app) }
    }

    /// The id of one.
    pub fn output_id(host_id: &str, kind: &str, model: &str) -> String {
        let hex = Sha1::of(format!("{host_id}\n{kind}\n{model}").as_bytes());
        format!("eng:{}", hex.get(..12).unwrap_or(&hex))
    }

    /// `{output id: row}`.
    pub fn exposed(&self) -> Map<String, Value> {
        self.app.admin.change(|doc| {
            let store = AdminStore::topology(doc);
            // absent-ok: a section that is not a table holds nothing yet.
            store.entry(Self::SECTION.to_string()).or_insert_with(|| json!({})).as_object().cloned().unwrap_or_default()
        })
    }

    fn engine_of<'host>(host: &'host Value, kind: &str) -> Option<&'host Value> {
        let engines = host.get("engines").and_then(Value::as_array).into_iter().flatten();
        engines.into_iter().find(|engine| engine.get("kind").and_then(Value::as_str) == Some(kind))
    }

    /// A model made an output (`on`), or no longer.
    pub fn set(
        &self,
        hosts: &[Value],
        host_id: Option<&Value>,
        kind: Option<&Value>,
        model: Option<&Value>,
        on: bool,
    ) -> Result<Value, AppError> {
        let (host_id, kind, model) = (Coerce::stripped(host_id), Coerce::stripped(kind), Coerce::stripped(model));
        if host_id.is_empty() || kind.is_empty() || model.is_empty() {
            return Err(AppError::new("hostId, kind and model are required"));
        }
        let id = Self::output_id(&host_id, &kind, &model);
        let row = if on {
            let host = hosts.iter().find(|host| Coerce::text(host.get("id")) == host_id);
            let engine = host.and_then(|host| Self::engine_of(host, &kind));
            let models = engine.and_then(|engine| engine.get("models")).and_then(Value::as_array).into_iter().flatten();
            let found = models.into_iter().find(|row| row.get("name").and_then(Value::as_str) == Some(model.as_str()));
            let found =
                found.ok_or_else(|| AppError::with_status(format!("{model} is not a model of {kind} on {host_id}"), 404))?;
            if Coerce::truthy(found.get("remote")) {
                return Err(AppError::new(format!("{model} runs on the engine's cloud, not on {host_id}")));
            }
            let port = engine.and_then(|engine| engine.get("port")).and_then(Coerce::int);
            Some(json!({"hostId": host_id, "kind": kind, "model": model, "port": port}))
        } else {
            None
        };
        self.app.admin.saving(|doc| {
            let store = AdminStore::topology(doc);
            if let Some(rows) = store.entry(Self::SECTION.to_string()).or_insert_with(|| json!({})).as_object_mut() {
                match row {
                    Some(row) => {
                        rows.insert(id.clone(), row);
                    }
                    None => {
                        rows.shift_remove(&id);
                    }
                }
            }
        });
        Ok(json!({"id": id, "exposed": on}))
    }

    /// Where the controller's proxy reaches the engine.
    fn upstream_host(&self, host: &Value, engine: Option<&Value>) -> String {
        if engine.and_then(|engine| engine.get("listen")).and_then(Value::as_str) == Some("loopback")
            && self.controller.is_host(host)
        {
            return "127.0.0.1".to_string();
        }
        Coerce::text(host.get("ip"))
    }

    /// Why the controller's proxy cannot reach the engine; empty when it can, or when nothing says it cannot.
    pub fn blocked_by(&self, host: &Value, engine: &Value) -> &'static str {
        if self.controller.is_host(host) {
            return "";
        }
        if engine.get("listen").and_then(Value::as_str) == Some("loopback") {
            return "loopback";
        }
        let wall = engine.get("firewall").filter(|wall| wall.is_object());
        let state = wall.and_then(|wall| wall.get("state")).and_then(Value::as_str);
        if state == Some("blocked")
            || (state == Some("restricted") && !self.lets_in(wall.and_then(|wall| wall.get("allowedFrom"))))
        {
            return "firewall";
        }
        ""
    }

    /// True when the controller's address is among ufw's allowed sources, an address or a network; an address it does not know lets it in.
    fn lets_in(&self, sources: Option<&Value>) -> bool {
        let Ok(me) = Coerce::strip(&self.app.paths.topology_server_ip).parse::<IpAddr>() else {
            return true;
        };
        if me.is_loopback() {
            return true;
        }
        sources.and_then(Value::as_array).into_iter().flatten().any(|source| {
            let word = Coerce::str_of(Some(source));
            word.split_whitespace().next().is_some_and(|network| Self::network_holds(network, me))
        })
    }

    fn network_holds(network: &str, address: IpAddr) -> bool {
        let (base, bits) = network.split_once('/').map_or((network, None), |(base, bits)| (base, Some(bits)));
        let Ok(base) = base.parse::<IpAddr>() else {
            return false;
        };
        match (base, address) {
            (IpAddr::V4(base), IpAddr::V4(me)) => {
                let bits = bits.map_or(Some(32), |bits| bits.parse::<u32>().ok()).filter(|bits| *bits <= 32);
                bits.is_some_and(|bits| {
                    // absent-ok: a mask of no bits covers everything: the address alone is compared.
                    let mask = u32::MAX.checked_shl(32 - bits).unwrap_or(0);
                    u32::from(base) & mask == u32::from(me) & mask
                })
            }
            (IpAddr::V6(base), IpAddr::V6(me)) => {
                let bits = bits.map_or(Some(128), |bits| bits.parse::<u32>().ok()).filter(|bits| *bits <= 128);
                bits.is_some_and(|bits| {
                    // absent-ok: a mask of no bits covers everything: the address alone is compared.
                    let mask = u128::MAX.checked_shl(128 - bits).unwrap_or(0);
                    u128::from(base) & mask == u128::from(me) & mask
                })
            }
            _ => false,
        }
    }

    /// One router output per exposed model whose machine is on the board, in the order the models were exposed.
    pub fn outputs(&self, hosts: &[Value]) -> Vec<Value> {
        let mut outs = Vec::new();
        for (id, row) in self.exposed() {
            let host = hosts.iter().find(|host| Coerce::text(host.get("id")) == Coerce::text(row.get("hostId")));
            let Some(host) = host.filter(|_| row.is_object()) else {
                continue;
            };
            let kind = Coerce::text(row.get("kind"));
            let engine = Self::engine_of(host, &kind);
            let said = engine
                .and_then(|engine| engine.get("port"))
                .filter(|port| Coerce::truthy(Some(*port)))
                .or_else(|| row.get("port"));
            // absent-ok: `int(... or 0)`: an engine with no port is skipped below.
            let port = Coerce::whole(said);
            let address = self.upstream_host(host, engine);
            if port == 0 || address.is_empty() {
                continue;
            }
            let label = {
                let named = Coerce::text(engine.and_then(|engine| engine.get("label")));
                if named.is_empty() { kind.clone() } else { named }
            };
            let model = Coerce::str_of(row.get("model"));
            let host_id = Coerce::text(row.get("hostId"));
            outs.push(json!({
                "id": id, "label": format!("{model} · {label}"), "target": format!("{host_id}:engine:{kind}"),
                "upstreamHost": address, "upstreamPort": port, "upstreamType": "engine", "providerId": "",
                "upstreamModel": Coerce::text(row.get("model")), "engine": kind, "hostId": host_id,
            }));
        }
        outs
    }

    /// The machine's engines as the board draws them: whether the proxy reaches each, and which models are outputs.
    pub fn annotate(&self, host: &Value) -> Value {
        let Some(engines) = host.get("engines").and_then(Value::as_array) else {
            return host.get("engines").cloned().unwrap_or(Value::Null);
        };
        let rows = self.exposed();
        let host_id = Coerce::str_of(host.get("id"));
        let mut out = Vec::new();
        for engine in engines {
            let mut shown = engine.clone();
            let blocked = self.blocked_by(host, engine);
            Coerce::put(&mut shown, "blockedBy", json!(blocked));
            Coerce::put(&mut shown, "reachable", json!(blocked.is_empty()));
            if let Some(models) = engine.get("models").and_then(Value::as_array) {
                let kind = Coerce::str_of(engine.get("kind"));
                let marked: Vec<Value> = models
                    .iter()
                    .map(|model| {
                        let mut row = model.clone();
                        let id = Self::output_id(&host_id, &kind, &Coerce::str_of(model.get("name")));
                        Coerce::put(&mut row, "outputId", json!(id));
                        Coerce::put(&mut row, "exposed", json!(rows.contains_key(&id)));
                        row
                    })
                    .collect();
                Coerce::put(&mut shown, "models", Value::Array(marked));
            }
            out.push(shown);
        }
        Value::Array(out)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn an_address_is_in_its_network() {
        let me: IpAddr = "10.0.30.20".parse().unwrap();
        assert!(EngineOutputs::network_holds("10.0.30.0/24", me));
        assert!(EngineOutputs::network_holds("10.0.30.20", me));
        assert!(EngineOutputs::network_holds("0.0.0.0/0", me));
        assert!(!EngineOutputs::network_holds("10.0.31.0/24", me));
        assert!(!EngineOutputs::network_holds("nonsense", me));
    }
}
