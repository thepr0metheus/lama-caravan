//! Ports the fleet must not put a cell on.

use super::server_cells::ServerCells;
use crate::app::App;
use crate::fleet::scout::ScoutAuth;
use crate::paths::CONTROLLER_HOST_ID;
use crate::proxies::config::ProxiesConfig;
use crate::proxies::service::ListeningPorts;
use crate::store::admin::AdminStore;
use crate::store::topology::Topology;
use rules::{AppError, Coerce};
use serde_json::{Map, Value, json};
use std::collections::BTreeSet;
use std::time::Duration;

/// The exclusions of this controller.
pub struct PortExclusions<'app> {
    app: &'app App,
}

impl<'app> PortExclusions<'app> {
    const SECTION: &'static str = "portExclusions";

    /// The exclusions of `app`.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    fn kept(&self) -> Map<String, Value> {
        self.app.admin.change(|doc| {
            let store = AdminStore::topology(doc);
            if !store.get(Self::SECTION).is_some_and(Value::is_object) {
                store.insert(Self::SECTION.to_string(), json!({}));
            }
            // absent-ok: a section that is not a table holds nothing yet.
            store.get(Self::SECTION).and_then(Value::as_object).cloned().unwrap_or_default()
        })
    }

    /// Just the numbers.
    pub fn excluded(&self) -> BTreeSet<i64> {
        self.kept().keys().filter_map(|key| key.parse().ok()).collect()
    }

    /// The rows as the board lists them, by port.
    pub fn list(&self) -> Vec<Value> {
        let mut rows: Vec<(i64, Value)> = self
            .kept()
            .iter()
            .filter_map(|(key, row)| {
                let port = key.parse::<i64>().ok()?;
                // absent-ok: `int(v.get("addedAt") or 0)`: a row that names no moment was added long ago.
                let added = Coerce::whole(row.get("addedAt"));
                Some((port, json!({"port": port, "note": Coerce::text(row.get("note")), "host": Coerce::text(row.get("host")), "addedAt": added, "auto": Coerce::truthy(row.get("auto"))})))
            })
            .collect();
        rows.sort_by_key(|row| row.0);
        rows.into_iter().map(|row| row.1).collect()
    }

    /// Exclusions added and removed in one call, so that the page can apply a whole scan's result at once.
    pub fn set(&self, body: &Value) -> Result<Value, AppError> {
        let now = self.app.now_whole();
        let (mut added, mut removed) = (Vec::new(), Vec::new());
        let excluded = self.excluded();
        let used = ServerCells::of(self.app).used_ports(None);
        let mut rows = self.kept();
        for item in body.get("add").and_then(Value::as_array).into_iter().flatten() {
            let wrapped = if item.is_i64() || item.is_string() { json!({"port": item}) } else { item.clone() };
            if !wrapped.is_object() {
                continue;
            }
            let Some(port) = Coerce::int_or_zero(wrapped.get("port")) else {
                continue;
            };
            if !(1..=65535).contains(&port) {
                return Err(AppError::new(format!("port {port} is out of range")));
            }
            if used.contains(&port) && !excluded.contains(&port) {
                return Err(AppError::with_status(
                    format!("port {port} already belongs to a cell or proxy — move that first"),
                    409,
                ));
            }
            let cut = |key: &str, most: usize| -> String { Coerce::text(wrapped.get(key)).chars().take(most).collect() };
            rows.insert(port.to_string(), json!({"note": cut("note", 200), "host": cut("host", 60), "addedAt": now, "auto": Coerce::truthy(wrapped.get("auto"))}));
            added.push(port);
        }
        for raw in body.get("remove").and_then(Value::as_array).into_iter().flatten() {
            if let Some(port) = Coerce::int(raw)
                && rows.shift_remove(&port.to_string()).is_some()
            {
                removed.push(port);
            }
        }
        self.app.admin.saving(|doc| {
            AdminStore::topology(doc).insert(Self::SECTION.to_string(), Value::Object(rows));
        });
        Ok(json!({"ok": true, "added": added, "removed": removed, "exclusions": self.list()}))
    }

    /// Every port the caravan itself listens on, beyond the model cells.
    fn owned_ports(&self) -> BTreeSet<i64> {
        let mut owned = BTreeSet::from([self.app.paths.port]);
        if let Ok(config) = ProxiesConfig::of(self.app).load() {
            let routes = config.get("routes").and_then(Value::as_array).into_iter().flatten();
            owned.extend(routes.filter_map(|route| Coerce::int_or_zero(route.get("port"))));
        }
        let hosts = self.app.admin.change(|doc| Topology::of(doc).hosts().clone());
        for host in hosts.values() {
            let url = Coerce::text(host.get("agentUrl"));
            let tail = url.rsplit("//").next().unwrap_or(&url);
            if let Some((_, rest)) = tail.split_once(':') {
                let digits: String = rest.chars().take_while(char::is_ascii_digit).collect();
                if let Ok(port) = digits.parse() {
                    owned.insert(port);
                }
            }
        }
        owned.remove(&0);
        owned
    }

    fn in_range(&self, port: i64) -> bool {
        self.app.paths.cell_ports.base <= port && port <= self.app.paths.cell_ports.upper
    }

    /// Ports inside the cell range that are listening but are not the caravan's.
    pub fn scan_foreign(&self) -> Value {
        let mut ours = ServerCells::of(self.app).used_ports(None);
        ours.extend(self.owned_ports());
        let mut hosts = Vec::new();
        let listening = ListeningPorts::read();
        if listening.known {
            let found: Vec<Value> = listening
                .ports()
                .into_iter()
                .filter(|port| self.in_range(*port) && !ours.contains(port))
                .map(|port| {
                    let (pid, name) = listening.owner(port);
                    json!({"port": port, "proc": if name.is_empty() { "?".to_string() } else { name }, "pid": pid})
                })
                .collect();
            hosts.push(json!({"hostId": CONTROLLER_HOST_ID, "ok": true, "ports": found}));
        } else {
            hosts.push(json!({"hostId": CONTROLLER_HOST_ID, "ok": false, "ports": [], "error": "this machine has no table of listening ports (/proc/net/tcp)"}));
        }
        hosts.extend(self.client_scans(&ours));
        json!({"ok": true, "hosts": hosts, "rangeFrom": self.app.paths.cell_ports.base, "rangeTo": self.app.paths.cell_ports.upper})
    }

    /// Every registered scout asked what is listening on it.
    fn client_scans(&self, ours: &BTreeSet<i64>) -> Vec<Value> {
        let hosts = self.app.admin.change(|doc| Topology::of(doc).hosts().clone());
        let mut out = Vec::new();
        for (host_id, host) in &hosts {
            let base = Coerce::text(host.get("agentUrl")).trim_end_matches('/').to_string();
            if host_id.is_empty() || base.is_empty() {
                continue;
            }
            let fields = ScoutAuth::fields(self.app);
            let answer = self.app.http.json("GET", &format!("{base}/api/host/listeners"), &fields, &[], Duration::from_secs(6));
            let data = match answer {
                Ok(data) => data,
                Err(error) => {
                    let words: String = error.to_string().chars().take(160).collect();
                    out.push(json!({"hostId": host_id, "ok": false, "error": words, "ports": []}));
                    continue;
                }
            };
            if !data.is_object() || data.get("ok") == Some(&json!(false)) {
                let said = Coerce::text(data.get("error"));
                let words = if said.is_empty() { "the scout could not list its listeners".to_string() } else { said };
                let words: String = words.chars().take(160).collect();
                out.push(json!({"hostId": host_id, "ok": false, "error": words, "ports": []}));
                continue;
            }
            let rows: Vec<&Value> = data
                .get("ports")
                .and_then(Value::as_array)
                .into_iter()
                .flatten()
                .filter(|row| {
                    // absent-ok: `int(r.get("port") or 0)`: a row with no port is outside any range.
                    let port = Coerce::whole(row.get("port"));
                    row.is_object() && self.in_range(port) && !ours.contains(&port)
                })
                .collect();
            out.push(json!({"hostId": host_id, "ok": true, "ports": rows}));
        }
        out
    }
}
