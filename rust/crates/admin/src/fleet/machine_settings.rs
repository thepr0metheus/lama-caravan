//! What an operator set on a machine, beyond its cells: how much its cache keeps and where, whether it keeps any, what starts with the machine. A scout keeps these in its own state, and loses them when it is taken
//! off; the controller keeps a copy of what the scout last reported, and gives it back when that machine's scout is paired anew (the owner, 2026-11-02: settings "must be kept on the caravan, not on the machines with
//! a scout"; a reinstall had lost a cache's limit and two engines' start at boot).

use super::cell_ops::CellAutostart;
use super::engine_actions::EngineActions;
use super::model_cache::ModelCache;
use crate::app::App;
use crate::store::topology::Topology;
use rules::Coerce;
use serde_json::{Value, json};

/// One thing to give back to a scout.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SettingBack {
    /// Where its cache lies.
    Folder(String),
    /// Where its folder for Strata's files lies.
    Work(String),
    /// How much the models in that folder may take, bytes: the operator's, not the folder's own 300 GB.
    WorkBudget(i64),
    /// How many models its cache keeps.
    Keep(i64),
    /// How much its cache may take, bytes.
    Budget(i64),
    /// Its cache is off: a folder it reads from, or none for through the controller.
    Off(String),
    /// An engine that starts with the machine: whether it runs now.
    Engine(String, bool),
    /// A cell that starts with the machine.
    Cell(i64),
}

/// The settings of the machines.
pub struct MachineSettings<'app> {
    app: &'app App,
}

impl<'app> MachineSettings<'app> {
    const SECTION: &'static str = "machineSettings";

    /// The settings of `app`.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    /// What of a machine's record is the operator's. `None` for a scout that says nothing of its cache: an older one, and its silence is no setting to keep.
    pub fn read(record: &Value) -> Option<Value> {
        let cache = record.get("modelCache").filter(|cache| cache.is_object())?;
        let said = |key: &str| cache.get(key).cloned().unwrap_or(Value::Null);
        let rows = record.get("engines").and_then(Value::as_array).into_iter().flatten();
        let engines: Vec<Value> =
            rows.filter(|row| row.get("autostart") == Some(&json!(true))).filter_map(|row| row.get("kind").cloned()).collect();
        let chosen = said("dirChosen") == json!(true);
        let work = cache.get("work").filter(|work| work.is_object());
        let work_dir = work.filter(|work| work.get("chosen") == Some(&json!(true))).and_then(|work| work.get("dir")).cloned();
        let work_budget =
            work.filter(|work| work.get("budgetChosen") == Some(&json!(true))).and_then(|work| work.get("budgetBytes")).cloned();
        Some(json!({
            "dir": if chosen { said("dir") } else { Value::Null }, "workDir": work_dir, "workBudgetBytes": work_budget, "keep": said("keep"), "budgetBytes": said("budgetBytes"), "off": said("off"), "through": said("through"), "library": said("library"),
            "engines": engines,
            "autostart": record.get("autostart").filter(|ports| ports.is_array()).cloned().unwrap_or_else(|| json!([])),
        }))
    }

    /// What is kept for this machine.
    pub fn kept(&self, host_id: &str) -> Option<Value> {
        self.app.admin.change(|doc| Topology::of(doc).named(Self::SECTION).get(host_id).cloned())
    }

    /// Keeps what `record` says: a report's part, on the document it is saved with.
    pub fn remember(topology: &mut Topology<'_>, host_id: &str, record: &Value) {
        if let Some(settings) = Self::read(record) {
            topology.named(Self::SECTION).insert(host_id.to_string(), settings);
        }
    }

    /// What to give back of `kept` to a scout whose record is `now`, in the order it is to go: the folder before anything lands in it, the cache's rules, then what starts. What the scout already has is not asked of it.
    pub fn steps(kept: &Value, now: &Value) -> Vec<SettingBack> {
        let Some(said) = Self::read(now) else {
            return Vec::new();
        };
        let differs = |key: &str| kept.get(key).is_some_and(|value| !value.is_null()) && kept.get(key) != said.get(key);
        let mut steps = Vec::new();
        // Where the cache lies now, chosen or not: a new scout already there has nothing to move.
        let dir_now = now.get("modelCache").and_then(|cache| cache.get("dir"));
        if differs("dir") && kept.get("dir") != dir_now {
            steps.push(SettingBack::Folder(Coerce::text(kept.get("dir"))));
        }
        // Where the cells' files go, before a start that needs it.
        let work_now = now.get("modelCache").and_then(|cache| cache.get("work")).and_then(|work| work.get("dir"));
        if differs("workDir") && kept.get("workDir") != work_now {
            steps.push(SettingBack::Work(Coerce::text(kept.get("workDir"))));
        }
        let work_budget_now = now.get("modelCache").and_then(|cache| cache.get("work")).and_then(|work| work.get("budgetBytes"));
        if differs("workBudgetBytes") && kept.get("workBudgetBytes") != work_budget_now {
            steps.extend(kept.get("workBudgetBytes").and_then(Value::as_i64).map(SettingBack::WorkBudget));
        }
        if differs("keep") {
            steps.extend(kept.get("keep").and_then(Value::as_i64).map(SettingBack::Keep));
        }
        if differs("budgetBytes") {
            steps.extend(kept.get("budgetBytes").and_then(Value::as_i64).map(SettingBack::Budget));
        }
        if kept.get("off") == Some(&json!(true))
            && (said.get("off") != Some(&json!(true)) || kept.get("through") != said.get("through"))
        {
            let through = kept.get("through") == Some(&json!(true));
            steps.push(SettingBack::Off(if through { String::new() } else { Coerce::text(kept.get("library")) }));
        }
        // absent-ok: a list that is not there has nothing in it, on either side.
        let listed = |doc: &Value, key: &str| doc.get(key).and_then(Value::as_array).cloned().unwrap_or_default();
        let rows = listed(now, "engines");
        for kind in listed(kept, "engines").iter().filter(|kind| !listed(&said, "engines").contains(kind)) {
            let kind = Coerce::text(Some(kind));
            let row = rows.iter().find(|row| Coerce::text(row.get("kind")) == kind);
            steps.push(SettingBack::Engine(kind, row.is_some_and(|row| row.get("state") == Some(&json!("ok")))));
        }
        for port in listed(kept, "autostart").iter().filter(|port| !listed(&said, "autostart").contains(port)) {
            steps.extend(port.as_i64().map(SettingBack::Cell));
        }
        steps
    }

    /// One step, on the scout. Its refusal is said in the scout's words.
    fn apply(&self, host_id: &str, step: &SettingBack) -> Result<(), String> {
        let host = json!(host_id);
        let cache = ModelCache::of(self.app);
        let words = |error: rules::AppError| error.message;
        match step {
            // A scout paired anew holds nothing yet: nothing to carry.
            SettingBack::Folder(path) => {
                cache.move_to(host_id, Some(&json!(path)), Some(&json!("delete"))).map(drop).map_err(words)
            }
            SettingBack::Work(path) => cache.work(host_id, Some(&json!(path)), Some(&json!("delete"))).map(drop).map_err(words),
            SettingBack::WorkBudget(bytes) => cache.work_budget(host_id, Some(&json!(bytes))).map(drop).map_err(words),
            SettingBack::Keep(keep) => cache.keep(host_id, Some(&json!(keep))).map(drop).map_err(words),
            SettingBack::Budget(bytes) => cache.budget(host_id, Some(&json!(bytes))).map(drop).map_err(words),
            SettingBack::Off(library) => cache.off(host_id, Some(&json!(true)), Some(&json!(library))).map(drop).map_err(words),
            SettingBack::Engine(kind, true) => EngineActions::of(self.app).keep_at_boot(host_id, kind).map(drop).map_err(words),
            SettingBack::Engine(kind, false) => {
                EngineActions::of(self.app).serve(Some(&host), "start", Some(&json!(kind))).map(drop).map_err(words)
            }
            SettingBack::Cell(port) => {
                let said = CellAutostart::of(self.app).set(host_id, *port, true);
                if said.get("ok") == Some(&json!(true)) { Ok(()) } else { Err(Coerce::text(said.get("error"))) }
            }
        }
    }

    /// The name of a step, as the board says what came back.
    fn name_of(step: &SettingBack) -> String {
        match step {
            SettingBack::Folder(_) => "cacheFolder".to_string(),
            SettingBack::Work(_) => "workFolder".to_string(),
            SettingBack::WorkBudget(_) => "workLimit".to_string(),
            SettingBack::Keep(_) => "cacheKeep".to_string(),
            SettingBack::Budget(_) => "cacheLimit".to_string(),
            SettingBack::Off(_) => "cacheOff".to_string(),
            SettingBack::Engine(kind, _) => format!("engine:{kind}"),
            SettingBack::Cell(port) => format!("cell:{port}"),
        }
    }

    /// What was kept, given back to the scout of `host_id` now paired: what came back, and what did not with why. A step that fails stops none of the others.
    pub fn give_back(&self, host_id: &str, kept: Option<&Value>) -> (Vec<String>, Vec<String>) {
        let Some(kept) = kept else {
            return (Vec::new(), Vec::new());
        };
        let now = self.app.admin.change(|doc| Topology::of(doc).hosts().get(host_id).cloned());
        let Some(now) = now else {
            return (Vec::new(), Vec::new());
        };
        let (mut back, mut not_back) = (Vec::new(), Vec::new());
        for step in Self::steps(kept, &now) {
            match self.apply(host_id, &step) {
                Ok(()) => back.push(Self::name_of(&step)),
                Err(words) => not_back.push(format!("{}: {words}", Self::name_of(&step))),
            }
        }
        (back, not_back)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn record(cache: Value) -> Value {
        json!({"modelCache": cache, "engines": [], "autostart": []})
    }

    fn fresh() -> Value {
        record(
            json!({"dir": "/home/u/cache", "keep": 1, "budgetBytes": null, "off": false, "through": false, "work": {"dir": "/home/u/cache", "chosen": false}}),
        )
    }

    #[test]
    fn what_a_new_scout_lacks_is_given_back_in_its_order_and_what_it_has_is_not_asked() {
        let kept = MachineSettings::read(&json!({
            "modelCache": {"dir": "/mnt/hdd", "dirChosen": true, "keep": 3, "budgetBytes": 1024, "off": false, "through": false, "work": {"dir": "/mnt/hdd2/strata", "chosen": true, "budgetBytes": 2048, "budgetChosen": true}},
            "engines": [{"kind": "ollama", "autostart": true}, {"kind": "lmstudio", "autostart": false}],
            "autostart": [22013, 22007],
        }))
        .unwrap();
        let mut now = fresh();
        now["engines"] = json!([{"kind": "ollama", "state": "ok", "autostart": false}]);
        now["autostart"] = json!([22007]);
        assert_eq!(
            MachineSettings::steps(&kept, &now),
            [
                SettingBack::Folder("/mnt/hdd".to_string()),
                SettingBack::Work("/mnt/hdd2/strata".to_string()),
                SettingBack::WorkBudget(2048),
                SettingBack::Keep(3),
                SettingBack::Budget(1024),
                SettingBack::Engine("ollama".to_string(), true),
                SettingBack::Cell(22013),
            ]
        );
        assert_eq!(
            MachineSettings::steps(&kept, &json!({"autostart": [1]})),
            [],
            "a scout that says nothing of its cache is not told anything"
        );
        let same = json!({"modelCache": {"dir": "/mnt/hdd", "dirChosen": true, "keep": 3, "budgetBytes": 1024, "off": false, "through": false, "work": {"dir": "/mnt/hdd2/strata", "chosen": true, "budgetBytes": 2048, "budgetChosen": true}}, "engines": [{"kind": "ollama", "autostart": true}], "autostart": [22013, 22007]});
        assert_eq!(MachineSettings::steps(&kept, &same), [], "the same scout paired again: nothing to give back");
    }

    #[test]
    fn a_folder_nobody_chose_is_no_setting() {
        let kept = MachineSettings::read(&record(json!({"dir": "/home/old/cache", "dirChosen": false}))).unwrap();
        assert_eq!(MachineSettings::steps(&kept, &fresh()), [], "where a cache lay by itself is not asked of the next one");
        let chosen = MachineSettings::read(&record(json!({"dir": "/home/u/cache", "dirChosen": true}))).unwrap();
        assert_eq!(MachineSettings::steps(&chosen, &fresh()), [], "chosen, and it lies there already: nothing to move");
        let work = MachineSettings::read(&record(json!({"work": {"dir": "/home/old/cache", "chosen": false}}))).unwrap();
        assert_eq!(MachineSettings::steps(&work, &fresh()), [], "nor where the cells' files lay by themselves");
        let own = record(
            json!({"work": {"dir": "/ssd/strata", "chosen": true, "budgetBytes": 322_122_547_200_i64, "budgetChosen": false}}),
        );
        let own = MachineSettings::read(&own).unwrap();
        assert_eq!(own["workBudgetBytes"], Value::Null, "the folder's own 300 GB is nobody's word");
        assert_eq!(MachineSettings::steps(&own, &fresh()), [SettingBack::Work("/ssd/strata".to_string())]);
    }

    #[test]
    fn a_cache_off_comes_back_by_the_way_it_went() {
        let by_controller =
            MachineSettings::read(&record(json!({"off": true, "through": true, "library": "/mnt/found"}))).unwrap();
        assert_eq!(
            MachineSettings::steps(&by_controller, &fresh()),
            [SettingBack::Off(String::new())],
            "a folder the scout found is no word of the operator's"
        );
        let from_folder = MachineSettings::read(&record(json!({"off": true, "through": false, "library": "/mnt/lib"}))).unwrap();
        assert_eq!(MachineSettings::steps(&from_folder, &fresh()), [SettingBack::Off("/mnt/lib".to_string())]);
        let now = record(json!({"keep": 1, "off": true, "through": true}));
        assert_eq!(MachineSettings::steps(&from_folder, &now), [SettingBack::Off("/mnt/lib".to_string())], "off, the other way");
        assert_eq!(MachineSettings::steps(&by_controller, &now), [], "off, the same way");
        let on = MachineSettings::read(&fresh()).unwrap();
        assert_eq!(
            MachineSettings::steps(&on, &now),
            [],
            "a cache that was on says nothing of one that is off: the scout keeps it as it is"
        );
    }

    #[test]
    fn no_limit_kept_takes_none_away_and_an_older_scout_keeps_nothing() {
        let kept = MachineSettings::read(&fresh()).unwrap();
        let mut now = fresh();
        now["modelCache"]["budgetBytes"] = json!(9);
        assert_eq!(MachineSettings::steps(&kept, &now), []);
        assert_eq!(MachineSettings::read(&json!({"autostart": [1]})), None);
        assert_eq!(MachineSettings::read(&json!({"modelCache": null})), None);
    }
}
