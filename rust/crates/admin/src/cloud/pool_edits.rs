//! The edits of a pool from the board.

use super::data::CloudData;
use super::pools::PoolDesk;
use super::refs::CloudModelRefs;
use crate::common::cloud_file::{AccountModelJobs, AddedModels, ModelLevels, ModelSchedules, UsageLevels};
use crate::common::cloud_pools::CloudPools;
use crate::common::cloud_sources::CloudSources;
use crate::proxies::config::ProxiesConfig;
use rules::{AppError, ClientDeny, Coerce, EntryModels};
use serde_json::{Map, Value, json};
use std::collections::BTreeSet;

mod accounts;

impl PoolDesk<'_> {
    /// How high a level goes.
    pub const MAX_PCT: i64 = 90;

    fn push_row(pool: &mut Value, row: Value) {
        if let Some(rows) = pool.get_mut("steps").and_then(Value::as_array_mut) {
            rows.push(row);
        }
    }

    fn keep_rows(pool: &mut Value, keep: impl Fn(&Value) -> bool) {
        if let Some(rows) = pool.get_mut("steps").and_then(Value::as_array_mut) {
            rows.retain(keep);
        }
    }

    fn save_pool_in(&self, data: &mut Value, pool: &Value) -> Result<Value, AppError> {
        let kept = Self::put(data, pool)?;
        self.cloud().save(data)?;
        Ok(kept)
    }

    /// A new pool.
    pub fn create(
        &self,
        name: Option<&Value>,
        account: Option<&Value>,
        model: Option<&Value>,
        target: Option<&Value>,
        name_after: Option<&Value>,
    ) -> Result<Value, AppError> {
        let mut data = self.cloud().load();
        let said = target.filter(|target| !target.is_null() && *target != &json!("") && *target != &json!({}));
        let first = match said {
            Some(target) => Self::target_of(&data, Some(target))?,
            None if Coerce::truthy(account) || Coerce::truthy(model) => {
                Self::target_of(&data, Some(&json!({"accountId": account, "model": model})))?
            }
            None => json!({}),
        };
        let typed = Self::name_of(name, "");
        let name = if typed.is_empty() {
            let after = Self::name_of(name_after, "");
            let wanted = if !after.is_empty() {
                after
            } else if Coerce::truthy(first.get("model")) {
                Coerce::text(first.get("model"))
            } else {
                Self::NEW_NAME.to_string()
            };
            self.free_name(&data, &wanted)
        } else {
            self.unique(&data, &typed, None)?
        };
        let mut pool = json!({"id": Self::slug(&name, &Self::ids_of(&data)), "name": name, "steps": [], "contextAuto": true});
        if Coerce::truthy(first.get("accountId")) {
            let step = Self::new_step(&mut data, &pool, &Coerce::text(first.get("accountId")), first.get("model"))?;
            Self::push_row(&mut pool, step);
        } else if Coerce::truthy(first.get("output")) {
            let row = json!({"id": CloudPools::row_id(&BTreeSet::new()), "enabled": true, "output": first.get("output")});
            Self::push_row(&mut pool, row);
        }
        self.save_pool_in(&mut data, &pool)
    }

    /// A pool with what this one has, its rows in their order and every setting of its own, right under it (the owner, 2026-10-29).
    pub fn copy(&self, pool_id: &str) -> Result<Value, AppError> {
        let mut data = self.cloud().load();
        let source = Self::pool_of(&data, pool_id)?;
        let source_id = Coerce::text(source.get("id"));
        let own_name = Coerce::text(source.get("name"));
        let base = if own_name.is_empty() { source_id.clone() } else { own_name };
        let wanted: String = format!("{base} copy").chars().take(Self::NAME_MAX).collect();
        let name = self.free_name(&data, &wanted);
        let mut copy = source.clone();
        Coerce::put(&mut copy, "id", json!(Self::slug(&name, &Self::ids_of(&data))));
        Coerce::put(&mut copy, "name", json!(name));
        let kept = Self::put(&mut data, &copy)?;
        if let Some(pools) = data.get_mut("pools").and_then(Value::as_array_mut)
            && let Some(at) = pools.iter().position(|row| Coerce::text(row.get("id")) == source_id)
            && let Some(last) = pools.pop()
        {
            pools.insert(at + 1, last);
        }
        self.cloud().save(&data)?;
        Ok(kept)
    }

    /// One more row at the end of the pool: cabled when `target` says to what.
    pub fn add_row(&self, pool_id: &str, target: Option<&Value>, name_after: Option<&Value>) -> Result<Value, AppError> {
        let mut data = self.cloud().load();
        let mut pool = Self::pool_of(&data, pool_id)?;
        let cabled_before = Self::cabled(&pool);
        let mut row = json!({"id": CloudPools::row_id(&Self::row_ids(&pool)), "enabled": true});
        Coerce::extend(&mut row, &Self::target_of(&data, target)?);
        Self::keep_model(&mut data, &row);
        let has_cable = Coerce::truthy(row.get("accountId")) || Coerce::truthy(row.get("output"));
        Self::push_row(&mut pool, row);
        if has_cable {
            self.named_after(&data, &mut pool, name_after, cabled_before);
        }
        self.save_pool_in(&mut data, &pool)
    }

    /// The row's output cabled to `target`, or its cable taken away.
    pub fn connect_row(
        &self,
        pool_id: &str,
        row_id: &str,
        target: Option<&Value>,
        name_after: Option<&Value>,
    ) -> Result<Value, AppError> {
        let mut data = self.cloud().load();
        let mut pool = Self::pool_of(&data, pool_id)?;
        if !Self::row_ids(&pool).contains(row_id) {
            return Err(AppError::with_status(format!("pool {pool_id} has no row {row_id}"), 404));
        }
        let cabled_before = Self::cabled(&pool);
        let cabled = Self::target_of(&data, target)?;
        Self::keep_model(&mut data, &cabled);
        let rows = pool.get_mut("steps").and_then(Value::as_array_mut).into_iter().flatten();
        for row in rows.filter(|row| Coerce::text(row.get("id")) == row_id) {
            for key in ["accountId", "model", "output", "kind"] {
                Coerce::take(row, key);
            }
            for (key, said) in Coerce::fields(&cabled) {
                Coerce::put(row, &key, said);
            }
        }
        if Coerce::truthy(Some(&cabled)) {
            self.named_after(&data, &mut pool, name_after, cabled_before);
        }
        self.save_pool_in(&mut data, &pool)
    }

    /// The pools in the order Routing's column shows them, from the board's drag.
    pub fn order(&self, ids: Option<&Value>) -> Result<Vec<String>, AppError> {
        let mut data = self.cloud().load();
        let pools: Vec<Value> =
            data.get("pools").and_then(Value::as_array).into_iter().flatten().filter(|row| row.is_object()).cloned().collect();
        let mut by_id: Map<String, Value> = Map::new();
        for pool in pools {
            by_id.insert(Coerce::str_of(pool.get("id")), pool);
        }
        let wanted: Option<Vec<String>> =
            ids.and_then(Value::as_array).map(|ids| ids.iter().map(|id| Coerce::str_of(Some(id))).collect());
        let changed =
            AppError::with_status("the pools changed since the board was drawn — draw it again and move the card again", 409);
        let Some(wanted) = wanted else {
            return Err(changed);
        };
        let distinct: BTreeSet<&String> = wanted.iter().collect();
        let known: BTreeSet<&String> = by_id.keys().collect();
        if distinct.len() != wanted.len() || distinct != known {
            return Err(changed);
        }
        let ordered: Vec<Value> = wanted.iter().filter_map(|id| by_id.get(id).cloned()).collect();
        Coerce::put(&mut data, "pools", Value::Array(ordered));
        self.cloud().save(&data)?;
        Ok(wanted)
    }

    /// "Arrange by cables" (the owner, 2026-10-12): each account's models in the order the pools reach them.
    pub fn arrange(&self) -> Result<Vec<String>, AppError> {
        let mut data = self.cloud().load();
        let rows = data.get("pools").and_then(Value::as_array).into_iter().flatten().filter(|row| row.is_object());
        let order: Vec<String> = rows.map(|pool| Coerce::str_of(pool.get("id"))).collect();
        let reading = CloudPools::new(&data, None);
        let mut named: Map<String, Value> = Map::new();
        for id in &order {
            for row in reading.get(id).and_then(|pool| pool.get("steps")).and_then(Value::as_array).into_iter().flatten() {
                if row.get("kind").and_then(Value::as_str) == Some("account") {
                    let account = Coerce::text(row.get("accountId"));
                    if let Some(models) = named.entry(account).or_insert_with(|| json!([])).as_array_mut() {
                        models.push(row.get("model").cloned().unwrap_or(Value::Null));
                    }
                }
            }
        }
        let mut added = AddedModels::new(&data);
        for (account, models) in &named {
            let models: Vec<String> = models.as_array().into_iter().flatten().map(|model| Coerce::text(Some(model))).collect();
            added.put_first(account, &models);
        }
        Coerce::put(&mut data, "addedModels", added.stored());
        self.cloud().save(&data)?;
        Ok(order)
    }

    fn edited_rows(data: &mut Value, stored: &Value, raw: &[Value]) -> Result<Vec<Value>, AppError> {
        let known: Vec<&Value> = stored.get("steps").and_then(Value::as_array).into_iter().flatten().collect();
        let (mut seen, mut steps) = (BTreeSet::new(), Vec::new());
        let refused = || AppError::new("pool.steps: each step once, and only the pool's own");
        for item in raw {
            let id = item.get("id").filter(|_| item.is_object()).ok_or_else(refused)?;
            let row = known.iter().find(|row| row.get("id") == Some(id)).ok_or_else(refused)?;
            if !seen.insert(Coerce::str_of(Some(id))) {
                return Err(refused());
            }
            let said_on = item.get("enabled").or_else(|| row.get("enabled"));
            let automatic = item.get("automatic").is_none_or(|flag| Coerce::truthy(Some(flag)));
            let enabled = Coerce::truthy(said_on) && automatic;
            let mut out = (*row).clone();
            Coerce::put(&mut out, "enabled", json!(enabled));
            if row.get("kind").and_then(Value::as_str) == Some("account") {
                let account_id = item.get("accountId").or_else(|| row.get("accountId"));
                let account = Self::account_of(data, &Coerce::text(account_id))?;
                Coerce::put(&mut out, "accountId", account.get("id").cloned().unwrap_or(Value::Null));
                let model = Self::model_of(item.get("model").or_else(|| row.get("model")))?;
                Coerce::put(&mut out, "model", json!(model));
                Self::keep_model(data, &out);
            }
            steps.push(out);
        }
        Ok(steps)
    }

    /// An edit of a pool as the board sends it whole.
    pub fn save_pool(&self, supplied: &Value) -> Result<Value, AppError> {
        if !supplied.is_object() {
            return Err(AppError::new("pool must be an object"));
        }
        let mut data = self.cloud().load();
        let stored = Self::pool_of(&data, &Coerce::str_of(Some(supplied.get("id").unwrap_or(&Value::Null))))?;
        let raw = supplied.get("steps").or_else(|| stored.get("steps"));
        let raw = raw.and_then(Value::as_array).ok_or_else(|| AppError::new("pool.steps must be a list"))?;
        let steps = Self::edited_rows(&mut data, &stored, raw)?;
        let window = supplied.get("contextLength").or_else(|| stored.get("contextLength")).cloned().unwrap_or(Value::Null);
        if !window.is_null() && window != json!("") && CloudPools::positive(Some(&window)).is_none() {
            return Err(AppError::new("contextLength must be a positive number or empty"));
        }
        let stored_id = Coerce::text(stored.get("id"));
        let name = Self::name_of(supplied.get("name").or_else(|| stored.get("name")), &Coerce::text(stored.get("name")));
        let name = self.unique(&data, &name, Some(&stored_id))?;
        let mut pool = stored.clone();
        Coerce::put(&mut pool, "name", json!(name));
        Coerce::put(&mut pool, "steps", Value::Array(steps));
        Coerce::put(&mut pool, "contextLength", window);
        let auto = supplied.get("contextAuto").or_else(|| stored.get("contextAuto"));
        Coerce::put(&mut pool, "contextAuto", json!(Coerce::truthy(auto)));
        self.save_pool_in(&mut data, &pool)
    }

    /// What the board names as the reader of a part no pool's rows can take. The rule is asked before the write, so the
    /// board's error and the entry's refusal are one answer, said by the same words: this file does not decide what a reader
    /// is, and it does not write what the answer refuses.
    ///
    /// The key is the rule's name (`EntryModels::READER_FIELD`), so the door that writes it and the reading that reads it
    /// say one word. Nothing named is written as nothing, not as an empty name: the absence is kept as the absence it is.
    pub fn set_reader(&self, supplied: &Value) -> Result<Value, AppError> {
        if !supplied.is_object() {
            return Err(AppError::new("body must be an object"));
        }
        let mut data = self.cloud().load();
        let named = Coerce::word(supplied.get(EntryModels::READER_FIELD));
        if let Some(refusal) = self.cloud().board_names(&data).can_write(&named) {
            return Err(AppError::with_status(refusal.error.message, refusal.error.status));
        }
        let said = if named.is_empty() { Value::Null } else { json!(named) };
        Coerce::put(&mut data, EntryModels::READER_FIELD, said.clone());
        self.cloud().save(&data)?;
        Ok(said)
    }

    /// One more step at the end of the pool.
    pub fn add_step(&self, pool_id: &str, account_id: &str, model: Option<&Value>) -> Result<Value, AppError> {
        let mut data = self.cloud().load();
        let mut pool = Self::pool_of(&data, pool_id)?;
        let step = Self::new_step(&mut data, &pool, account_id, model)?;
        Self::push_row(&mut pool, step);
        self.save_pool_in(&mut data, &pool)
    }

    /// The step leaves the pool; the pool stays, even with none.
    pub fn remove_step(&self, pool_id: &str, step_id: &str) -> Result<Value, AppError> {
        let mut data = self.cloud().load();
        let mut pool = Self::pool_of(&data, pool_id)?;
        if !Self::row_ids(&pool).contains(step_id) {
            return Err(AppError::with_status(format!("pool {pool_id} has no step {step_id}"), 404));
        }
        Self::keep_rows(&mut pool, |row| Coerce::text(row.get("id")) != step_id);
        self.save_pool_in(&mut data, &pool)
    }

    /// A pool deleted. What leads to it moves onto another, is cut, or stops the delete: the operator is asked first.
    pub fn delete(&self, pool_id: &str, resolution: Option<&Value>) -> Result<Value, AppError> {
        let mut data = self.cloud().load();
        let pool = Self::pool_of(&data, pool_id)?;
        let id = Coerce::text(pool.get("id"));
        let config = self.proxies();
        let mut payload = config.load()?;
        let held = CloudModelRefs::new(&payload).held(&id);
        let (empty, rules) = (json!({}), held.get("rules").cloned().unwrap_or_else(|| json!([])));
        let answer = resolution.filter(|said| said.is_object()).unwrap_or(&empty);
        let mut onto = Coerce::stripped(answer.get("moveTo"));
        let (mut moved, mut cut) = (0, 0);
        let cables = Coerce::i64_or_zero(held.get("cables"));
        if cables > 0 || Coerce::truthy(Some(&rules)) {
            if !onto.is_empty() {
                if onto == id {
                    return Err(AppError::new("move the cables onto another pool"));
                }
                let output = ProxiesConfig::pool_output(&Self::pool_of(&data, &onto)?);
                moved = CloudModelRefs::move_onto(&mut payload, &id, &onto, Some(&output));
            } else if Coerce::truthy(answer.get("cut")) {
                cut = CloudModelRefs::cut(&mut payload, &id);
            } else {
                return Err(AppError::with_status(
                    format!(
                        "pool {id}: {cables} cable(s) and rules {} lead to it in Routing — move them onto another pool, or disconnect them",
                        rules::PyRepr::of_value(&rules)
                    ),
                    409,
                ));
            }
        } else {
            onto = String::new();
        }
        let mut routes = payload.get("routes").cloned().unwrap_or_else(|| json!([]));
        let unclosed = Self::unclose(&mut routes, &id);
        config.save(routes, payload.get("routers").cloned(), None)?;
        if let Some(pools) = data.get_mut("pools").and_then(Value::as_array_mut) {
            pools.retain(|row| row.is_object() && Coerce::text(row.get("id")) != id);
        }
        self.cloud().save(&data)?;
        Ok(
            json!({"deleted": id, "moved": moved, "cut": cut, "onto": if onto.is_empty() { Value::Null } else { json!(onto) }, "unclosed": unclosed}),
        )
    }

    /// The clients closed to the deleted pool lose that refusal; how many.
    fn unclose(routes: &mut Value, pool_id: &str) -> i64 {
        let key = EntryModels::pool_key(pool_id);
        let mut unclosed = 0;
        for route in routes.as_array_mut().into_iter().flatten() {
            if Coerce::text(route.get("kind")) != "consumer" {
                continue;
            }
            let Some(deny) = route.get_mut(ClientDeny::FIELD).and_then(Value::as_array_mut) else {
                continue;
            };
            let before = deny.len();
            deny.retain(|said| said.as_str() != Some(key.as_str()));
            if deny.len() != before {
                unclosed += 1;
            }
        }
        unclosed
    }

    /// The file's reading, for the helpers that take one.
    pub fn data(&self) -> Value {
        CloudData::of(self.app).load()
    }
}
