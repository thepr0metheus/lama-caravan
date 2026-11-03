//! A machine's cell, named by its port, followed wherever the caravan names it.

use super::machine_rows::MachineRows;
use crate::app::App;
use crate::cloud::data::CloudData;
use crate::common::cloud_file::{ModelKey, ModelSchedules};
use crate::proxies::config::ProxiesConfig;
use crate::store::topology::Topology;
use plumbing::log::Log;
use rules::{AppError, Coerce};
use serde_json::{Value, json};

/// The names of a cell, `srv:<port>`, following it when its port changes and leaving with it.
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

    fn output(port: i64) -> String {
        format!("srv:{port}")
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

    /// The cell moved from `old_port` to `new_port`.
    pub fn moved(&self, old_port: i64, new_port: i64) -> Value {
        let (old, new) = (Self::output(old_port), Self::output(new_port));
        let rename = |output: &str| {
            if output == new {
                None
            } else if output == old {
                Some(new.clone())
            } else {
                Some(output.to_string())
            }
        };
        let schedules = |kept: &mut ModelSchedules| {
            let stale = kept.forget(&ModelKey::output(&new));
            kept.follow(&old, &new) || stale
        };
        let config = ProxiesConfig::of(self.app);
        self.follow(&format!("{old} → {new}"), &|| config.remap_output_refs(&old, &new), &rename, &schedules)
    }

    /// Two cells swapped their ports.
    pub fn swapped(&self, port_a: i64, port_b: i64) -> Value {
        let (a, b) = (Self::output(port_a), Self::output(port_b));
        let rename = |output: &str| {
            Some(if output == a {
                b.clone()
            } else if output == b {
                a.clone()
            } else {
                output.to_string()
            })
        };
        let schedules = |kept: &mut ModelSchedules| kept.swap(&a, &b);
        let config = ProxiesConfig::of(self.app);
        self.follow(&format!("{a} ↔ {b}"), &|| config.swap_output_refs(&a, &b), &rename, &schedules)
    }

    /// The cell at `port` of machine `host_id` was deleted: its cables go, and with its model's only copy the model's too.
    pub fn dropped(&self, port: i64, host_id: Option<&str>) -> Value {
        let mut gone = vec![Self::output(port)];
        if let Some(host_id) = host_id.filter(|host_id| !host_id.is_empty()) {
            let host = self.app.admin.change(|doc| Topology::of(doc).hosts().get(host_id).cloned());
            if let Some(model) = MachineRows::sole_model(host.as_ref(), port) {
                gone.push(model);
            }
        }
        gone.sort();
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
            {"id": "p", "steps": [{"id": "a", "output": "srv:1", "enabled": true}, {"id": "b", "output": "srv:2"}, {"id": "c", "accountId": "x"}]},
            {"id": "q", "name": "Q", "steps": [{"id": "d", "output": "srv:3"}]},
        ]});
        let rename = |output: &str| match output {
            "srv:1" => Some("srv:9".to_string()),
            "srv:2" => None,
            other => Some(other.to_string()),
        };
        let changed = CellOutputs::rows(&mut data, &rename);
        assert_eq!(changed, ["p"]);
        assert_eq!(data["pools"][0]["steps"][0]["output"], "srv:9");
        assert_eq!(data["pools"][0]["steps"][1], json!({"id": "b"}));
        assert_eq!(data["pools"][1]["steps"][0]["output"], "srv:3");
    }
}
