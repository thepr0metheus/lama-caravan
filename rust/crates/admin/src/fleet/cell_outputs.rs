//! A machine's cell, followed where the caravan names it: since 2026-11-07 (Papyrus `caravan-scout-port-lease`) a pool's row names a
//! machine's model (`mm:`), never a cell's port, so what follows a cell is its leaving — the cable of the model whose only copy it was.

use super::machine_rows::MachineRows;
use crate::app::App;
use crate::cloud::data::CloudData;
use crate::common::cloud_file::{ModelKey, ModelSchedules};
use crate::store::topology::Topology;
use plumbing::log::Log;
use rules::{AppError, Coerce};
use serde_json::{Value, json};

/// The cables a cell takes with it when it leaves.
pub struct CellOutputs<'app> {
    app: &'app App,
}

/// What a row's output is called from now on: another output, the same one, or none, which takes the cable away.
type Rename<'name> = &'name dyn Fn(&str) -> Option<String>;

impl<'app> CellOutputs<'app> {
    /// The names of `app`.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    /// Every pool's row cabled to a cell, named anew; the names of the pools that changed.
    fn rows(data: &mut Value, rename: Rename<'_>) -> Vec<String> {
        let mut changed = Vec::new();
        for pool in data.get_mut("pools").and_then(Value::as_array_mut).into_iter().flatten() {
            let shown = {
                let name = Coerce::text(pool.get("name"));
                if name.is_empty() { Coerce::text(pool.get("id")) } else { name }
            };
            let mut touched = false;
            for step in pool.get_mut("steps").and_then(Value::as_array_mut).into_iter().flatten() {
                if !step.is_object() || !Coerce::truthy(step.get("output")) {
                    continue;
                }
                let old = Coerce::str_of(step.get("output"));
                let named = rename(&old);
                if named.as_deref() == Some(old.as_str()) {
                    continue;
                }
                match named {
                    Some(new) => Coerce::put(step, "output", json!(new)),
                    None => {
                        for key in ["accountId", "model", "output", "kind"] {
                            Coerce::take(step, key);
                        }
                    }
                }
                touched = true;
            }
            if touched {
                changed.push(shown);
            }
        }
        changed
    }

    /// One reading and one writing of the cloud file.
    fn cloud(
        &self,
        rename: Rename<'_>,
        schedules_change: &dyn Fn(&mut ModelSchedules) -> bool,
    ) -> Result<(Vec<String>, bool), AppError> {
        let cloud = CloudData::of(self.app);
        let mut data = cloud.load();
        let pools = Self::rows(&mut data, rename);
        let mut schedules = ModelSchedules::new(&data);
        let changed = schedules_change(&mut schedules);
        if !pools.is_empty() || changed {
            Coerce::put(&mut data, "schedules", schedules.stored());
            cloud.save(&data)?;
        }
        Ok((pools, changed))
    }

    /// Each file followed on its own: a failure of one is said, and the other still follows.
    fn follow(
        &self,
        what: &str,
        routers: &dyn Fn() -> Result<bool, AppError>,
        rename: Rename<'_>,
        schedules: &dyn Fn(&mut ModelSchedules) -> bool,
    ) -> Value {
        let mut failures = Vec::new();
        let routers_moved = routers().unwrap_or_else(|error| {
            failures.push(format!("routers: {}", error.message));
            false
        });
        let (pools, schedule) = self.cloud(rename, schedules).unwrap_or_else(|error| {
            failures.push(format!("pools and schedules: {}", error.message));
            (Vec::new(), false)
        });
        for failure in &failures {
            Log::line(&format!("[cell-outputs] {what}: did not follow — {failure}"));
        }
        json!({"routers": routers_moved, "pools": pools, "schedule": schedule, "notFollowed": failures})
    }

    /// Cell `id` of machine `host_id` was deleted: with its model's only copy the model's cable goes from the pools and schedules.
    pub fn dropped(&self, id: &str, host_id: Option<&str>) -> Value {
        let mut gone = Vec::new();
        if let Some(host_id) = host_id.filter(|host_id| !host_id.is_empty()) {
            let host = self.app.admin.change(|doc| Topology::of(doc).hosts().get(host_id).cloned());
            if let Some(model) = MachineRows::sole_model(host.as_ref(), id) {
                gone.push(model);
            }
        }
        if gone.is_empty() {
            return json!({"routers": false, "pools": [], "schedule": false, "notFollowed": []});
        }
        let rename = |output: &str| if gone.iter().any(|name| name == output) { None } else { Some(output.to_string()) };
        let schedules = |kept: &mut ModelSchedules| {
            let mut changed = false;
            for name in &gone {
                changed = kept.forget(&ModelKey::output(name)) || changed;
            }
            changed
        };
        self.follow(&format!("{} deleted", gone.join(", ")), &|| Ok(false), &rename, &schedules)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_row_follows_its_cell_or_loses_its_cable() {
        let mut data = json!({"pools": [
            {"id": "p", "steps": [{"id": "a", "output": "mm:a", "enabled": true}, {"id": "b", "output": "mm:b"}, {"id": "c", "accountId": "x"}]},
            {"id": "q", "name": "Q", "steps": [{"id": "d", "output": "mm:c"}]},
        ]});
        let rename = |output: &str| match output {
            "mm:a" => Some("mm:z".to_string()),
            "mm:b" => None,
            other => Some(other.to_string()),
        };
        let changed = CellOutputs::rows(&mut data, &rename);
        assert_eq!(changed, ["p"]);
        assert_eq!(data["pools"][0]["steps"][0]["output"], "mm:z");
        assert_eq!(data["pools"][0]["steps"][1], json!({"id": "b"}));
        assert_eq!(data["pools"][1]["steps"][0]["output"], "mm:c");
    }
}
