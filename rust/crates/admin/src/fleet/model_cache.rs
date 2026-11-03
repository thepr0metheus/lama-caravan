//! The model cache of a machine as its scout reports it, and what the board asks of it.

use super::machine_models::MachineModels;
use super::scout::ScoutCall;
use crate::app::App;
use crate::store::topology::Topology;
use rules::{AppError, Coerce};
use serde_json::{Value, json};

#[cfg(test)]
mod tests;

/// A scout's word on its model cache, cleaned for the machine's record.
pub struct ModelCacheFacts;

impl ModelCacheFacts {
    const FOLDERS: usize = 8;

    /// The block as the record keeps it; `None` for a scout that keeps no cache.
    pub fn clean(raw: Option<&Value>) -> Option<Value> {
        let raw = raw.filter(|raw| raw.is_object())?;
        let keep = MachineModels::count(raw.get("keep")).filter(|keep| *keep != 0)?;
        let mut out = json!({
            "keep": keep,
            "managedBytes": MachineModels::count(raw.get("managedBytes")),
            "foreign": Self::foreign(raw.get("foreign")),
            "disk": Self::disk(raw.get("disk")),
        });
        if raw.get("budgetBytes").is_some() {
            Coerce::put(
                &mut out,
                "budgetBytes",
                json!(MachineModels::count(raw.get("budgetBytes")).filter(|budget| *budget != 0)),
            );
        }
        for key in ["dir", "dirOwn"] {
            if let Some(folder) = raw.get(key).and_then(Value::as_str).map(Coerce::strip).filter(|folder| folder.starts_with('/'))
            {
                Coerce::put(&mut out, key, json!(folder.chars().take(500).collect::<String>()));
            }
        }
        // Said only by a scout that can turn its cache off: the board offers the switch to no other.
        if let Some(off) = raw.get("off").and_then(Value::as_bool) {
            Coerce::put(&mut out, "off", json!(off));
        }
        for said in ["through", "canThrough", "dirChosen"] {
            if let Some(word) = raw.get(said).and_then(Value::as_bool) {
                Coerce::put(&mut out, said, json!(word));
            }
        }
        if let Some(library) = raw.get("library").and_then(Value::as_str).map(Coerce::strip).filter(|said| said.starts_with('/'))
        {
            let library: String = library.chars().take(500).collect();
            Coerce::put(&mut out, "library", json!(library));
        }
        if let Some(work) = Self::work(raw.get("work")) {
            Coerce::put(&mut out, "work", work);
        }
        if let Some(moving) = Self::moving(raw.get("moving")) {
            Coerce::put(&mut out, "moving", moving);
        }
        if let Some(words) = raw.get("moveError").and_then(Value::as_str).map(Coerce::strip).filter(|words| !words.is_empty()) {
            Coerce::put(&mut out, "moveError", json!(words.chars().take(500).collect::<String>()));
        }
        Some(out)
    }

    /// A folder's files on their way (2026-11-03): which folder, where to, how far. Unsaid or unreadable, no move is said.
    fn moving(raw: Option<&Value>) -> Option<Value> {
        let raw = raw.filter(|raw| raw.is_object())?;
        let what = raw.get("what").and_then(Value::as_str).filter(|what| ["cache", "work"].contains(what))?;
        let to = raw.get("to").and_then(Value::as_str).map(Coerce::strip).filter(|to| to.starts_with('/'))?;
        let (done, total) = (MachineModels::count(raw.get("doneBytes"))?, MachineModels::count(raw.get("totalBytes"))?);
        Some(json!({"what": what, "to": to.chars().take(500).collect::<String>(), "doneBytes": done, "totalBytes": total}))
    }

    /// The folder for Strata's files, said only by a scout that keeps it apart (2026-11-03): the folder and whether the operator chose it; what lies in it — the copies of the models and what
    /// the cells made from them — and its limit over the copies; its disk, and whether that disk spins. What a scout does not say is left out, not made up.
    fn work(raw: Option<&Value>) -> Option<Value> {
        let raw = raw.filter(|raw| raw.is_object())?;
        let folder = raw.get("dir").and_then(Value::as_str).map(Coerce::strip).filter(|folder| folder.starts_with('/'))?;
        let folder: String = folder.chars().take(500).collect();
        let chosen = raw.get("chosen").and_then(Value::as_bool)?;
        let mut out = json!({"dir": folder, "chosen": chosen, "bytes": MachineModels::count(raw.get("bytes"))});
        for key in ["modelsBytes", "madeBytes", "budgetBytes"] {
            if let Some(bytes) = MachineModels::count(raw.get(key)) {
                Coerce::put(&mut out, key, json!(bytes));
            }
        }
        for key in ["budgetChosen", "rotational"] {
            if let Some(word) = raw.get(key).and_then(Value::as_bool) {
                Coerce::put(&mut out, key, json!(word));
            }
        }
        if raw.get("disk").is_some() {
            Coerce::put(&mut out, "disk", Self::disk(raw.get("disk")));
        }
        if let Some(rows) = raw.get("models").and_then(Value::as_array) {
            let models: Vec<Value> = rows
                .iter()
                .filter_map(|row| {
                    let name: String = Coerce::stripped(row.get("name")).chars().take(300).collect();
                    let bytes = MachineModels::count(row.get("bytes"))?;
                    (!name.is_empty()).then(|| json!({"name": name, "bytes": bytes}))
                })
                .take(Self::FOLDERS)
                .collect();
            Coerce::put(&mut out, "models", json!(models));
        }
        Some(out)
    }

    /// The files of the cache folder that the scout did not download.
    fn foreign(raw: Option<&Value>) -> Value {
        let Some(raw) = raw.filter(|raw| raw.is_object()) else {
            return Value::Null;
        };
        let (Some(files), Some(size)) = (MachineModels::count(raw.get("files")), MachineModels::count(raw.get("bytes"))) else {
            return Value::Null;
        };
        let mut folders = Vec::new();
        for row in raw.get("folders").and_then(Value::as_array).into_iter().flatten() {
            let name: String = Coerce::stripped(row.get("folder")).chars().take(200).collect();
            let name = Coerce::strip(&name);
            if let (false, Some(count), Some(bytes)) =
                (name.is_empty(), MachineModels::count(row.get("files")), MachineModels::count(row.get("bytes")))
            {
                folders.push(json!({"folder": name, "files": count, "bytes": bytes}));
            }
            if folders.len() == Self::FOLDERS {
                break;
            }
        }
        json!({"files": files, "bytes": size, "folders": folders})
    }

    /// The cache folder's disk.
    fn disk(raw: Option<&Value>) -> Value {
        let Some(raw) = raw.filter(|raw| raw.is_object()) else {
            return Value::Null;
        };
        match (
            MachineModels::count(raw.get("totalBytes")).filter(|total| *total != 0),
            MachineModels::count(raw.get("freeBytes")),
        ) {
            (Some(total), Some(free)) => json!({"totalBytes": total, "freeBytes": free}),
            _ => Value::Null,
        }
    }
}

/// What the board asks of a machine's model cache.
pub struct ModelCache<'app> {
    app: &'app App,
}

impl<'app> ModelCache<'app> {
    /// The cache of `app`.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    fn whole(raw: Option<&Value>, name: &str) -> Result<i64, AppError> {
        raw.and_then(Value::as_i64).ok_or_else(|| AppError::new(format!("{name} is required: a whole number")))
    }

    fn asked(&self, host_id: &str, path: &str, payload: &Value, timeout: u64) -> Result<Value, AppError> {
        let host_id = Coerce::strip(host_id);
        let result = ScoutCall::of_host(self.app, host_id)?.post(path, payload, timeout)?;
        Ok(
            json!({"ok": Coerce::truthy(result.get("ok")), "hostId": host_id, "result": result, "modelCache": self.refresh(host_id)}),
        )
    }

    /// How many of the last started models the machine's cache keeps.
    pub fn keep(&self, host_id: &str, keep: Option<&Value>) -> Result<Value, AppError> {
        let keep = Self::whole(keep, "keep")?;
        self.asked(host_id, "/api/llama-node/cache/keep", &json!({"keep": keep}), 60)
    }

    /// How much the models in the machine's cache may take in all, in bytes; none takes it off, and the last `keep` models rule again.
    pub fn budget(&self, host_id: &str, budget_bytes: Option<&Value>) -> Result<Value, AppError> {
        let budget = match budget_bytes.filter(|said| !said.is_null()) {
            Some(said) => json!(Self::whole(Some(said), "budgetBytes")?),
            None => Value::Null,
        };
        self.asked(host_id, "/api/llama-node/cache/budget", &json!({"budgetBytes": budget}), 60)
    }

    /// The machine's cache moved to the folder `path` names (the owner, 2026-10-26), or back to the folder it lies in by itself when `path` names none; `how`: its files go with it ("move"),
    /// or they are deleted ("delete") — the owner's choice of 2026-11-03.
    pub fn move_to(&self, host_id: &str, path: Option<&Value>, how: Option<&Value>) -> Result<Value, AppError> {
        let how = Self::carry(how)?;
        self.asked(host_id, "/api/llama-node/cache/dir", &json!({"path": Coerce::stripped(path), "how": how}), 300)
    }

    /// What a move does with the files of the folder it leaves: "move" or "delete". A board from before the choice says nothing, and the move it means deletes them, as every move did then.
    fn carry(how: Option<&Value>) -> Result<&'static str, AppError> {
        match how.filter(|said| !said.is_null()).map(Value::as_str) {
            None => Ok("delete"),
            Some(Some("move")) => Ok("move"),
            Some(Some("delete")) => Ok("delete"),
            Some(_) => Err(AppError::new("how must be \"move\" or \"delete\"")),
        }
    }

    /// The folder where the machine's cells keep what they make from their models (the owner, 2026-11-03: Strata's pack, on a disk of his choosing), or none, when `path` names none: what they made
    /// there is deleted, and a Strata cell does not start until one is chosen. `how` as for the cache.
    pub fn work(&self, host_id: &str, path: Option<&Value>, how: Option<&Value>) -> Result<Value, AppError> {
        let how = Self::carry(how)?;
        self.asked(host_id, "/api/llama-node/cache/work", &json!({"path": Coerce::stripped(path), "how": how}), 120)
    }

    /// How much the models in the machine's folder for Strata's files may take in all, in bytes; none gives the folder its own limit back (300 GB). The owner, 2026-11-03: "and so that I can
    /// change it".
    pub fn work_budget(&self, host_id: &str, budget_bytes: Option<&Value>) -> Result<Value, AppError> {
        let budget = match budget_bytes.filter(|said| !said.is_null()) {
            Some(said) => json!(Self::whole(Some(said), "budgetBytes")?),
            None => Value::Null,
        };
        self.asked(host_id, "/api/llama-node/cache/work/budget", &json!({"budgetBytes": budget}), 60)
    }

    /// Refuses a start of `runner` on the machine of `host`, when the runner writes what it makes from its model at every start and nobody chose where (the owner, 2026-11-03: "do not let Strata start,
    /// and give a hint"). A scout that does not say where is not taken to have a folder.
    pub fn refuse_without_work(host: &Value, runner: &str) -> Result<(), AppError> {
        let name = Coerce::text(host.get("name"));
        let machine = if name.is_empty() { "this machine".to_string() } else { name };
        let chosen = host
            .get("modelCache")
            .and_then(|cache| cache.get("work"))
            .and_then(|work| work.get("chosen"))
            .and_then(Value::as_bool);
        let words = match chosen {
            Some(true) => return Ok(()),
            Some(false) => format!(
                "a {runner} cell writes its files on the disk at every start, and no folder is chosen for them on {machine}: open the machine's page, Model disk → Strata files → Choose…"
            ),
            None => format!(
                "the scout of {machine} does not say where a {runner} cell would write its files: update the scout from the ⋯ menu of the machine's page, then choose a folder in Model disk"
            ),
        };
        Err(AppError::with_status(words, 409))
    }

    /// The machine's cache turned off or on (the owner, 2026-11-02): off, it keeps no copies and its models come through this controller, or, with a folder named, from there.
    pub fn off(&self, host_id: &str, off: Option<&Value>, library: Option<&Value>) -> Result<Value, AppError> {
        let Some(off) = off.and_then(Value::as_bool) else {
            return Err(AppError::new("off must be true or false"));
        };
        self.asked(host_id, "/api/llama-node/cache/off", &json!({"off": off, "library": Coerce::stripped(library)}), 300)
    }

    /// The copies in the machine's cache deleted, but for what a running cell holds, and its figures as they are then.
    pub fn clear(&self, host_id: &str) -> Result<Value, AppError> {
        self.asked(host_id, "/api/llama-node/purge-cache", &json!({}), 300)
    }

    /// Whether the machine reports its cache off, so that its models come over the network.
    pub fn reads_over_network(host: &Value) -> bool {
        host.get("modelCache").and_then(|cache| cache.get("off")).and_then(Value::as_bool) == Some(true)
    }

    /// The files of the machine's cache folder its scout did not download deleted, only when their size is still the size the operator was shown.
    pub fn delete_foreign(&self, host_id: &str, expect_bytes: Option<&Value>) -> Result<Value, AppError> {
        let expect = Self::whole(expect_bytes, "expectBytes")?;
        self.asked(host_id, "/api/llama-node/cache/delete-foreign", &json!({"expectBytes": expect}), 120)
    }

    /// The machine's cache figures as its scout says them now, stored in its record.
    pub fn refresh(&self, host_id: &str) -> Value {
        let Ok(scout) = ScoutCall::of_host(self.app, host_id) else {
            return Value::Null;
        };
        let said = scout.read("/api/llama-node/cache", 10);
        let facts = if Coerce::truthy(said.get("ok")) { ModelCacheFacts::clean(Some(&said)) } else { None };
        if let Some(facts) = &facts {
            self.app.admin.saving(|doc| {
                if let Some(host) = Topology::of(doc).hosts().get_mut(host_id) {
                    Coerce::put(host, "modelCache", facts.clone());
                }
            });
        }
        facts.unwrap_or(Value::Null)
    }
}
