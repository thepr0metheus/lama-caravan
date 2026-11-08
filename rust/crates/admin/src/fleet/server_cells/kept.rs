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

    /// A record made of each kept request the controller lacks; the cells' ids. A request is kept under its cell's id, or — by a
    /// scout of before the cells had names — under its port, which names the cell `c<port>` (`rules::CellId`).
    pub fn adopt(&self, host_id: &str, requests: Option<&Value>) -> Result<Vec<String>, AppError> {
        let host_id = Coerce::strip(host_id);
        let Some(requests) = requests.and_then(Value::as_object) else {
            return Ok(Vec::new());
        };
        if host_id.is_empty() || HostIds::is_controller(host_id) {
            return Ok(Vec::new());
        }
        let cells = ServerCells::of(self.app);
        let mut kept: Vec<(String, &Value)> = requests
            .iter()
            .filter_map(|(key, request)| CellId::read(&json!(key)).map(|id| (id, request)))
            .filter(|(_, request)| request.get("config").is_some_and(Value::is_object))
            .collect();
        kept.sort_by(|a, b| a.0.cmp(&b.0));
        let mut made = Vec::new();
        for (id, request) in kept {
            if self.app.admin.change(|doc| Topology::of(doc).has_slot(&id)) {
                continue;
            }
            let model = request.get("modelPath").filter(|model| Coerce::truthy(Some(*model)));
            let mut slot = cells.upsert_slot(host_id, &id, request.get("config"), model, None)?;
            Coerce::put(&mut slot, "cacheModels", json!(Coerce::truthy(request.get("cacheModels"))));
            Coerce::put(&mut slot, "adoptedFrom", json!("scout"));
            self.app.admin.change(|doc| {
                Topology::of(doc).put_slot(&id, slot);
            });
            made.push(id);
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
