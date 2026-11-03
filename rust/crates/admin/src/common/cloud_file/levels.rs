//! A subscription's levels, the models added to Routing and what a key's model does.

use super::*;

/// A step's levels on a subscription's limit windows, in their stored shape `{"<seconds>": pct}`.
pub struct UsageLevels;

impl UsageLevels {
    pub(super) const MAX_PCT: i64 = 90;
    /// What a new step gets.
    pub const NEW_STEP: [(&'static str, i64); 2] = [("18000", 10), ("604800", 10)];

    /// The stored shape: what does not read is left out, a level above the cap is cut to it.
    pub fn normalize(raw: Option<&Value>) -> Map<String, Value> {
        let mut out = Map::new();
        for (key, value) in raw.and_then(Value::as_object).into_iter().flatten() {
            if value.is_boolean() {
                continue;
            }
            let (Some(seconds), Some(pct)) = (Coerce::int(&json!(key)), Coerce::int(value)) else {
                continue;
            };
            if seconds > 0 && pct > 0 {
                out.insert(seconds.to_string(), json!(pct.min(Self::MAX_PCT)));
            }
        }
        out
    }

    pub(super) fn figure(map: &Map<String, Value>, key: &str) -> i64 {
        // absent-ok: `.get(key, 0)`: a window not named has no level, and a higher one wins below.
        Coerce::i64_or_zero(map.get(key))
    }

    /// Every window of two maps, in the windows' order, with the higher level of each.
    pub(super) fn higher(left: &Map<String, Value>, right: &Map<String, Value>) -> Map<String, Value> {
        let mut keys: Vec<&String> = left.keys().chain(right.keys()).collect();
        // absent-ok: a key that read no number never got into a normalized map.
        keys.sort_by_key(|key| key.parse::<i64>().unwrap_or_default());
        keys.dedup();
        keys.into_iter().map(|key| (key.clone(), json!(Self::figure(left, key).max(Self::figure(right, key))))).collect()
    }
}

/// One model's stop and switch levels.
pub(super) type LevelPair = (Map<String, Value>, Map<String, Value>);

/// The stop and switch levels of each subscription model, one pair for every pool.
pub struct ModelLevels {
    pub(super) kept: BTreeMap<(String, String), LevelPair>,
}

impl ModelLevels {
    /// The levels of one reading of the file: `levels`, and for a model it does not name, the stricter of what the old steps said.
    pub fn new(data: &Value) -> Self {
        let mut kept = BTreeMap::new();
        for (account, models) in data.get("levels").and_then(Value::as_object).into_iter().flatten() {
            for (model, entry) in models.as_object().into_iter().flatten() {
                let (account, model) = (Coerce::strip(account), Coerce::strip(model));
                if entry.is_object() && !account.is_empty() && !model.is_empty() {
                    kept.insert((account.to_string(), model.to_string()), Self::clean(entry));
                }
            }
        }
        let mut legacy: BTreeMap<(String, String), LevelPair> = BTreeMap::new();
        let pools = data.get("pools").and_then(Value::as_array).into_iter().flatten();
        for step in pools.filter_map(|pool| pool.get("steps")?.as_array()).flatten() {
            if !step.is_object() || !(step.get("stopAt").is_some() || step.get("switchAt").is_some()) {
                continue;
            }
            let key = (Word::of(step.get("accountId")), Word::of(step.get("model")));
            if key.0.is_empty() || key.1.is_empty() || kept.contains_key(&key) {
                continue;
            }
            let clean = Self::clean(step);
            let merged = match legacy.get(&key) {
                Some(held) => Self::stricter(held, &clean),
                None => clean,
            };
            legacy.insert(key, merged);
        }
        kept.extend(legacy);
        Self { kept }
    }

    /// A pair as it is kept: the switch never below the stop.
    pub(super) fn clean(entry: &Value) -> LevelPair {
        let stop =
            UsageLevels::normalize(if entry.get("stopAt").is_some() { entry.get("stopAt") } else { entry.get("switchAt") });
        let switch = UsageLevels::normalize(entry.get("switchAt"));
        let raised = UsageLevels::higher(&switch, &stop);
        (stop, raised)
    }

    pub(super) fn stricter(
        left: &(Map<String, Value>, Map<String, Value>),
        right: &(Map<String, Value>, Map<String, Value>),
    ) -> (Map<String, Value>, Map<String, Value>) {
        let merged =
            json!({"stopAt": UsageLevels::higher(&left.0, &right.0), "switchAt": UsageLevels::higher(&left.1, &right.1)});
        Self::clean(&merged)
    }

    /// The (stop, switch) maps of one model; a model nobody set has what a new step gets.
    pub fn of(&self, account_id: &str, model: &str) -> (Value, Value) {
        match self.kept.get(&(Coerce::strip(account_id).to_string(), Coerce::strip(model).to_string())) {
            Some((stop, switch)) => (Value::Object(stop.clone()), Value::Object(switch.clone())),
            None => {
                let fresh: Map<String, Value> =
                    UsageLevels::NEW_STEP.iter().map(|(key, pct)| ((*key).to_string(), json!(pct))).collect();
                (Value::Object(fresh.clone()), Value::Object(fresh))
            }
        }
    }

    /// Whether somebody set it.
    pub fn is_set(&self, account_id: &str, model: &str) -> bool {
        self.kept.contains_key(&(Coerce::strip(account_id).to_string(), Coerce::strip(model).to_string()))
    }

    /// Keeps one model's pair, the switch raised to the stop where it is lower.
    pub fn put(&mut self, account_id: &str, model: &str, stop: &Value, switch: &Value) -> (Value, Value) {
        let clean = Self::clean(&json!({"stopAt": stop, "switchAt": switch}));
        self.kept.insert((Coerce::strip(account_id).to_string(), Coerce::strip(model).to_string()), clean);
        self.of(account_id, model)
    }

    /// Forgets an account.
    pub fn forget_account(&mut self, account_id: &str) {
        self.kept.retain(|key, _| key.0 != account_id);
    }

    /// The shape the file keeps under `levels`.
    pub fn stored(&self) -> Value {
        let mut out = Map::new();
        for ((account, model), (stop, switch)) in &self.kept {
            let row = out.entry(account.clone()).or_insert_with(|| json!({}));
            row[model] = json!({"stopAt": stop, "switchAt": switch});
        }
        Value::Object(out)
    }
}

/// The models the operator added to Routing's right column, by account.
#[derive(Debug, Default)]
pub struct AddedModels {
    pub(super) kept: BTreeMap<String, Vec<String>>,
}

impl AddedModels {
    /// One reading of the file.
    pub fn new(data: &Value) -> Self {
        let mut this = Self::default();
        for (account, models) in data.get("addedModels").and_then(Value::as_object).into_iter().flatten() {
            for model in models.as_array().into_iter().flatten() {
                this.add(account, &Word::of(Some(model)));
            }
        }
        this
    }

    /// The account's models in the order they were added.
    pub fn of(&self, account_id: &str) -> Vec<String> {
        // absent-ok: an account nobody added to has no models
        self.kept.get(Coerce::strip(account_id)).cloned().unwrap_or_default()
    }

    /// Adds one at the end; false when there is nothing to add.
    pub fn add(&mut self, account_id: &str, model: &str) -> bool {
        let (account, model) = (Coerce::strip(account_id), Coerce::strip(model));
        if account.is_empty()
            || model.is_empty()
            || self.kept.get(account).is_some_and(|models| models.iter().any(|said| said == model))
        {
            return false;
        }
        self.kept.entry(account.to_string()).or_default().push(model.to_string());
        true
    }

    /// True when it was there.
    pub fn remove(&mut self, account_id: &str, model: &str) -> bool {
        let (account, model) = (Coerce::strip(account_id), Coerce::strip(model));
        let Some(models) = self.kept.get_mut(account) else {
            return false;
        };
        let Some(at) = models.iter().position(|said| said == model) else {
            return false;
        };
        models.remove(at);
        if models.is_empty() {
            self.kept.remove(account);
        }
        true
    }

    /// The account's models with `models` in front, in that order, and the rest after them as they were.
    pub fn put_first(&mut self, account_id: &str, models: &[String]) {
        let account = Coerce::strip(account_id);
        let Some(kept) = self.kept.get_mut(account) else {
            return;
        };
        let mut first: Vec<String> = Vec::new();
        for model in models {
            let model = Coerce::strip(model).to_string();
            if kept.contains(&model) && !first.contains(&model) {
                first.push(model);
            }
        }
        let rest: Vec<String> = kept.iter().filter(|model| !first.contains(model)).cloned().collect();
        first.extend(rest);
        *kept = first;
    }

    /// Forgets an account.
    pub fn forget_account(&mut self, account_id: &str) {
        self.kept.remove(Coerce::strip(account_id));
    }

    /// The shape the file keeps under `addedModels`.
    pub fn stored(&self) -> Value {
        json!(self.kept)
    }
}

/// What the operator said a key's model does: its jobs, the same in every pool whose row names it.
#[derive(Debug, Default)]
pub struct AccountModelJobs {
    pub(super) kept: BTreeMap<(String, String), Vec<&'static str>>,
}

impl AccountModelJobs {
    /// What a key's model may be said to do, in the board's order.
    pub const OFFERED: [&'static str; 5] = ["llm", "embed", "asr", "speech-translate", "tts"];

    /// One reading of the file.
    pub fn new(data: &Value) -> Self {
        let mut this = Self::default();
        for (account, models) in data.get("modelJobs").and_then(Value::as_object).into_iter().flatten() {
            for (model, jobs) in models.as_object().into_iter().flatten() {
                this.put(account, model, jobs.as_array().map_or(&[][..], Vec::as_slice));
            }
        }
        this
    }

    /// The words among `jobs` that are no job a key's model may be said to do.
    pub fn unknown(jobs: &[Value]) -> Vec<Value> {
        jobs.iter().filter(|job| !job.as_str().is_some_and(|word| Self::OFFERED.contains(&word))).cloned().collect()
    }

    /// The jobs said of one model, in the vocabulary's order, or none when nobody said.
    pub fn of(&self, account_id: &str, model: &str) -> Option<Vec<&'static str>> {
        self.kept.get(&(Word::of(Some(&json!(account_id))), Word::of(Some(&json!(model))))).cloned()
    }

    /// Keeps what is said of one model: nothing said forgets it.
    pub fn put(&mut self, account_id: &str, model: &str, jobs: &[Value]) -> Option<Vec<&'static str>> {
        let key = (Coerce::strip(account_id).to_string(), Coerce::strip(model).to_string());
        if key.0.is_empty() || key.1.is_empty() {
            return None;
        }
        let wanted: Vec<&str> = jobs.iter().filter_map(Value::as_str).collect();
        let said: Vec<&'static str> =
            ModelJobs::JOBS.iter().copied().filter(|job| wanted.contains(job) && Self::OFFERED.contains(job)).collect();
        if said.is_empty() {
            self.kept.remove(&key);
        } else {
            self.kept.insert(key.clone(), said);
        }
        self.kept.get(&key).cloned()
    }

    /// Forgets an account.
    pub fn forget_account(&mut self, account_id: &str) {
        let account = Coerce::strip(account_id);
        self.kept.retain(|key, _| key.0 != account);
    }

    /// The shape the file keeps under `modelJobs`.
    pub fn stored(&self) -> Value {
        let mut out = Map::new();
        for ((account, model), jobs) in &self.kept {
            let row = out.entry(account.clone()).or_insert_with(|| json!({}));
            row[model] = json!(jobs);
        }
        Value::Object(out)
    }
}
