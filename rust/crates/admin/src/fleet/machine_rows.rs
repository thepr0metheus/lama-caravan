//! The pools' rows of a machine's cells, named by the machine's model rather than by a cell. A cell has a port only while it
//! runs (Papyrus `caravan-scout-port-lease`); what it serves stays, and a pool's row should follow. A row of before that named a
//! cell's port (`srv:<port>`) names the cell `c<port>` (`rules::CellId`), and goes to that cell's model.

use super::machine_models::MachineOutputs;
use super::server_cells::ServerCells;
use crate::app::App;
use crate::cloud::data::CloudData;
use crate::common::cloud_file::{ModelKey, ModelSchedules};
use os::LocalTime;
use plumbing::log::Log;
use rules::{AppError, CellId, Coerce, PyRepr};
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};

/// The cells of each model a machine lists, by name: their ids.
pub type Listed = BTreeMap<String, Vec<String>>;

/// The rows of the pools, and the schedules, that name a machine's cells, re-cabled to its models.
pub struct MachineRows<'app> {
    app: &'app App,
}

impl<'app> MachineRows<'app> {
    const BACKUP: &'static str = "bak-machine-rows";
    const BACKUPS_KEPT: usize = 10;

    /// The rows of `app`.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    /// The models a host record lists; `None` for one that lists none, or has no entry to call them through.
    pub fn listed(host: &Value) -> Option<Listed> {
        if !host.is_object() || MachineOutputs::entry_address(host).is_none() {
            return None;
        }
        let models = host.get("entryModels")?.as_array()?;
        let mut out = Listed::new();
        for model in models.iter().filter(|model| model.is_object()) {
            let name = Coerce::text(model.get("id"));
            if name.is_empty() {
                continue;
            }
            let copies = model.get("copies").and_then(Value::as_array).into_iter().flatten();
            out.insert(name, copies.filter_map(ServerCells::node_cell).collect());
        }
        Some(out)
    }

    /// Each cell with the machines' models that hold it.
    fn owners(hosts: &[Value]) -> BTreeMap<String, BTreeSet<(String, String)>> {
        let mut found: BTreeMap<String, BTreeSet<(String, String)>> = BTreeMap::new();
        for host in hosts {
            let host_id = Coerce::text(host.get("id"));
            if host_id.is_empty() {
                continue;
            }
            // absent-ok: a report that lists no models changes no row.
            for (name, cells) in Self::listed(host).unwrap_or_default() {
                for cell in cells {
                    found.entry(cell).or_default().insert((host_id.clone(), name.clone()));
                }
            }
        }
        found
    }

    /// The output of the model whose only copy is cell `id`: what goes with the cell when it is deleted.
    pub fn sole_model(host: Option<&Value>, id: &str) -> Option<String> {
        let host = host?;
        let host_id = Coerce::text(host.get("id"));
        if host_id.is_empty() {
            return None;
        }
        let listed = Self::listed(host)?;
        listed
            .iter()
            .find(|(_, cells)| matches!(cells.as_slice(), [only] if only == id))
            .map(|(name, _)| MachineOutputs::output_id(&host_id, name))
    }

    /// `{old name: new name}`: a model gone from the list whose cells all serve one other now.
    fn renames(before: Option<&Listed>, after: Option<&Listed>) -> BTreeMap<String, String> {
        let (Some(before), Some(after)) = (before, after) else {
            return BTreeMap::new();
        };
        let at: BTreeMap<&String, &String> =
            after.iter().flat_map(|(name, cells)| cells.iter().map(move |cell| (cell, name))).collect();
        let mut out = BTreeMap::new();
        for (name, cells) in before {
            if after.contains_key(name) || cells.is_empty() {
                continue;
            }
            let became: BTreeSet<Option<&&String>> = cells.iter().map(|cell| at.get(cell)).collect();
            if let [Some(new)] = became.into_iter().collect::<Vec<_>>().as_slice() {
                out.insert(name.clone(), (**new).clone());
            }
        }
        out
    }

    /// The rows of `pool` whose output `mapping` names, cabled to its new name. Two rows that come to name one output are one, on when either was.
    fn recable(pool: &mut Value, mapping: &BTreeMap<String, String>) -> Vec<(String, String)> {
        let Some(steps) = pool.get("steps").and_then(Value::as_array).cloned() else {
            return Vec::new();
        };
        let targets: BTreeSet<&String> = steps.iter().filter_map(|step| mapping.get(&Coerce::text(step.get("output")))).collect();
        if targets.is_empty() {
            return Vec::new();
        }
        let mut kept: Vec<Value> = Vec::new();
        let mut first: BTreeMap<String, usize> = BTreeMap::new();
        let mut moved: Vec<(String, String)> = Vec::new();
        for mut step in steps.iter().cloned() {
            if !step.is_object() {
                kept.push(step);
                continue;
            }
            let old = Coerce::text(step.get("output"));
            if let Some(new) = mapping.get(&old) {
                Coerce::put(&mut step, "output", json!(new));
                moved.push((old, new.clone()));
            }
            let out = Coerce::text(step.get("output"));
            let on = |row: &Value| row.get("enabled").is_none_or(|flag| Coerce::truthy(Some(flag)));
            if targets.contains(&out)
                && let Some(row) = first.get(&out).and_then(|at| kept.get_mut(*at))
            {
                let enabled = on(row) || on(&step);
                Coerce::put(row, "enabled", json!(enabled));
                continue;
            }
            if targets.contains(&out) {
                first.insert(out, kept.len());
            }
            kept.push(step);
        }
        Coerce::put(pool, "steps", Value::Array(kept));
        moved
    }

    /// The cell a row of before names by its port (`srv:<port>`); none for any other output.
    fn is_cell_output(output: &str) -> Option<String> {
        let digits = output.strip_prefix("srv:")?;
        (!digits.is_empty() && digits.len() <= 5 && digits.chars().all(|digit| digit.is_ascii_digit()))
            .then(|| CellId::read(&json!(digits)))
            .flatten()
    }

    /// `{srv:<port>: its model's output}` and the words for each.
    fn cells_named(
        data: &Value,
        owners: &BTreeMap<String, BTreeSet<(String, String)>>,
    ) -> (BTreeMap<String, String>, BTreeMap<String, String>) {
        let mut named: BTreeSet<String> = BTreeSet::new();
        for pool in data.get("pools").and_then(Value::as_array).into_iter().flatten().filter(|pool| pool.is_object()) {
            for step in pool.get("steps").and_then(Value::as_array).into_iter().flatten().filter(|step| step.is_object()) {
                named.insert(Coerce::text(step.get("output")));
            }
        }
        let stored = ModelSchedules::new(data).stored();
        for key in stored.as_object().into_iter().flatten().map(|(key, _)| key) {
            if let Some(output) = key.strip_prefix(ModelKey::OUTPUT) {
                named.insert(output.to_string());
            }
        }
        let (mut mapping, mut labels) = (BTreeMap::new(), BTreeMap::new());
        for output in named {
            let Some(found) = Self::is_cell_output(&output).and_then(|cell| owners.get(&cell)) else {
                continue;
            };
            if found.len() > 1 {
                Log::line(&format!(
                    "[machine-rows] {output}: {} machines list this cell — its rows stay as they are",
                    found.len()
                ));
                continue;
            }
            if let Some((host_id, name)) = found.iter().next() {
                let id = MachineOutputs::output_id(host_id, name);
                labels.insert(id.clone(), format!("{name} on {host_id}"));
                mapping.insert(output, id);
            }
        }
        (mapping, labels)
    }

    /// Each row and each schedule `mapping` names, under its new name; what changed.
    fn apply(data: &mut Value, mapping: &BTreeMap<String, String>) -> Vec<(String, String, String)> {
        let mut changes = Vec::new();
        for pool in data.get_mut("pools").and_then(Value::as_array_mut).into_iter().flatten() {
            let shown = {
                let name = Coerce::text(pool.get("name"));
                if name.is_empty() { Coerce::text(pool.get("id")) } else { name }
            };
            for (old, new) in Self::recable(pool, mapping) {
                changes.push((shown.clone(), old, new));
            }
        }
        let mut schedules = ModelSchedules::new(data);
        let mut moved = false;
        for (old, new) in mapping {
            if schedules.of(&ModelKey::output(old)).is_none() {
                continue;
            }
            if schedules.of(&ModelKey::output(new)).is_some() {
                Log::line(&format!("[machine-rows] the schedule of {old} stays: {new} has one"));
                continue;
            }
            moved = schedules.follow(old, new) || moved;
        }
        if moved {
            Coerce::put(data, "schedules", schedules.stored());
            changes.push((String::new(), "schedules".to_string(), String::new()));
        }
        changes
    }

    /// One reading and at most one writing of the file: what `follow` names, then every cell a machine lists a model of.
    pub fn run(
        &self,
        hosts: &[Value],
        follow: &BTreeMap<String, String>,
        why: &str,
    ) -> Result<Vec<(String, String, String)>, AppError> {
        let cloud = CloudData::of(self.app);
        let mut data = cloud.load();
        let mut changes = Self::apply(&mut data, follow);
        let (mapping, labels) = Self::cells_named(&data, &Self::owners(hosts));
        changes.extend(Self::apply(&mut data, &mapping));
        if changes.is_empty() {
            return Ok(changes);
        }
        self.backup();
        cloud.save(&data)?;
        for (pool, old, new) in &changes {
            let said = if pool.is_empty() {
                "schedules moved with their cells' models".to_string()
            } else {
                let label = labels.get(new).map_or_else(String::new, |label| format!(" ({label})"));
                format!("pool {}: {old} → {new}{label}", PyRepr::of(pool))
            };
            Log::line(&format!("[machine-rows] {why}: {said}"));
        }
        Ok(changes)
    }

    /// A machine reported (`report` replaced `previous`): a model renamed takes its rows with it.
    pub fn heard(&self, previous: &Value, report: &Value, hosts: &[Value]) -> Result<Vec<(String, String, String)>, AppError> {
        let host_id = Coerce::text(report.get("id"));
        let renamed = if host_id.is_empty() {
            BTreeMap::new()
        } else {
            Self::renames(Self::listed(previous).as_ref(), Self::listed(report).as_ref())
        };
        let mut follow = BTreeMap::new();
        for (old, new) in &renamed {
            follow.insert(MachineOutputs::output_id(&host_id, old), MachineOutputs::output_id(&host_id, new));
            Log::line(&format!(
                "[machine-rows] {host_id}: model {} is now {} — its rows follow",
                PyRepr::of(old),
                PyRepr::of(new)
            ));
        }
        self.run(hosts, &follow, &format!("{host_id} reported"))
    }

    /// A copy of the file as it is before the rewrite, the newest few kept.
    fn backup(&self) {
        let path = &self.app.paths.cloud_providers_file;
        if !path.exists() {
            return;
        }
        let now = self.app.now();
        let stamp = LocalTime::of(now as i64).map_or_else(String::new, |at| at.compact());
        let micros = (now.fract() * 1e6) as u64;
        let name = path.file_name().map_or_else(String::new, |name| name.to_string_lossy().into_owned());
        let copied = std::fs::copy(path, path.with_file_name(format!("{name}.{}-{stamp}-{micros:06}", Self::BACKUP)));
        if let Err(error) = copied {
            Log::line(&format!("[machine-rows] no copy of {name} before the rewrite: {error}"));
            return;
        }
        let prefix = format!("{name}.{}-", Self::BACKUP);
        let Some(parent) = path.parent() else {
            return;
        };
        let Ok(names) = std::fs::read_dir(parent) else {
            return;
        };
        let mut copies: Vec<std::path::PathBuf> = names
            .flatten()
            .filter(|entry| entry.file_name().to_string_lossy().starts_with(&prefix))
            .map(|entry| entry.path())
            .collect();
        copies.sort();
        for old in copies.iter().take(copies.len().saturating_sub(Self::BACKUPS_KEPT)) {
            drop(std::fs::remove_file(old));
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn host() -> Value {
        json!({"id": "h", "agentUrl": "http://a:1", "entryModels": [
            {"id": "m", "copies": [{"id": "c5a", "port": 22005}, {"port": 22006}]},
            {"id": "n", "copies": [{"id": "c7b", "port": null}]},
        ]})
    }

    #[test]
    fn a_report_lists_its_models_and_their_cells() {
        let listed = MachineRows::listed(&host()).unwrap();
        assert_eq!(listed["m"], ["c5a", "c22006"], "a copy by its id, or by the port a scout of before names");
        assert_eq!(listed["n"], ["c7b"], "a stopped copy holds no port and is still its cell");
        assert!(MachineRows::listed(&json!({"id": "h"})).is_none());
    }

    #[test]
    fn the_sole_copy_of_a_model_takes_the_model_with_it() {
        let host = host();
        assert_eq!(MachineRows::sole_model(Some(&host), "c7b"), Some(MachineOutputs::output_id("h", "n")));
        assert_eq!(MachineRows::sole_model(Some(&host), "c5a"), None, "negative: one copy of two takes no model");
        assert_eq!(MachineRows::sole_model(None, "c5a"), None);
    }

    #[test]
    fn a_model_is_renamed_when_all_its_cells_serve_one_other() {
        let cells = |ids: &[&str]| ids.iter().map(|id| id.to_string()).collect::<Vec<String>>();
        let before: Listed = [
            ("old".to_string(), cells(&["c5", "c6"])),
            ("gone".to_string(), cells(&["c9"])),
            ("same".to_string(), cells(&["c1"])),
        ]
        .into();
        let after: Listed = [("new".to_string(), cells(&["c5", "c6"])), ("same".to_string(), cells(&["c1"]))].into();
        let renamed = MachineRows::renames(Some(&before), Some(&after));
        assert_eq!(renamed, [("old".to_string(), "new".to_string())].into());
        assert!(MachineRows::renames(None, Some(&after)).is_empty());
    }

    #[test]
    fn two_rows_that_come_to_name_one_output_are_one() {
        let mut pool = json!({"steps": [
            {"id": "a", "output": "srv:5", "enabled": false},
            {"id": "b", "output": "mm:x", "enabled": true},
            {"id": "c", "output": "srv:6"},
        ]});
        let mapping: BTreeMap<String, String> = [("srv:5".to_string(), "mm:x".to_string())].into();
        let moved = MachineRows::recable(&mut pool, &mapping);
        assert_eq!(moved, [("srv:5".to_string(), "mm:x".to_string())]);
        assert_eq!(pool["steps"], json!([{"id": "a", "output": "mm:x", "enabled": true}, {"id": "c", "output": "srv:6"}]));
    }
}
