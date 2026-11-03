//! The cells a scout was keeping when it was first heard: they go on the board as they are.

use super::*;

/// A scout's kept start requests, and the controller's records of the cells it lacks (1.3.504).
pub struct KeptCells<'app> {
    pub(super) app: &'app App,
}

impl<'app> KeptCells<'app> {
    /// The adoption of `app`.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    pub(super) fn port(key: &str) -> i64 {
        key.parse::<i64>()
            .ok()
            .filter(|port| (1..=65535).contains(port) && key.chars().all(|digit| digit.is_ascii_digit()))
            // absent-ok: no cell yet: the first port of the range is next.
            .unwrap_or(0)
    }

    /// A record made of each kept request the controller lacks; the ports.
    pub fn adopt(&self, host_id: &str, requests: Option<&Value>) -> Result<Vec<i64>, AppError> {
        let host_id = Coerce::strip(host_id);
        let Some(requests) = requests.and_then(Value::as_object) else {
            return Ok(Vec::new());
        };
        if host_id.is_empty() || HostIds::is_controller(host_id) {
            return Ok(Vec::new());
        }
        let cells = ServerCells::of(self.app);
        let mut keys: Vec<&String> = requests.keys().collect();
        keys.sort_by_key(|key| Self::port(key));
        let mut made = Vec::new();
        for key in keys {
            let port = Self::port(key);
            let Some(request) =
                requests.get(key).filter(|request| port != 0 && request.get("config").is_some_and(Value::is_object))
            else {
                continue;
            };
            if self.app.admin.change(|doc| Topology::of(doc).has_slot(host_id, port)) {
                continue;
            }
            if cells.used_ports(None).contains(&port) {
                Log::line(&format!(
                    "[cells] {host_id}:{port}: its scout keeps a cell there, but the number is taken here — no record made"
                ));
                continue;
            }
            let model = request.get("modelPath").filter(|model| Coerce::truthy(Some(*model)));
            let mut slot = cells.upsert_slot(host_id, port, request.get("config"), model, None)?;
            Coerce::put(&mut slot, "cacheModels", json!(Coerce::truthy(request.get("cacheModels"))));
            Coerce::put(&mut slot, "adoptedFrom", json!("scout"));
            self.app.admin.change(|doc| {
                Topology::of(doc).put_slot(host_id, port, slot);
            });
            made.push(port);
        }
        if !made.is_empty() {
            self.app.save_admin();
            Log::line(&format!(
                "[cells] {host_id}: a record made of each cell its scout keeps and this controller lacked: {made:?}"
            ));
        }
        Ok(made)
    }
}
