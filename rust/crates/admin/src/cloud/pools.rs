//! The pools on the controller's files. A pool is what a client calls; a row is what it tries.

use super::data::CloudData;
use super::refs::CloudModelRefs;
use crate::app::App;
use crate::common::cloud_file::{AddedModels, ModelLevels};
use crate::common::cloud_pools::CloudPools;
use crate::common::cloud_sources::CloudSources;
use crate::proxies::config::ProxiesConfig;
use regex::Regex;
use rules::{AppError, Coerce};
use serde_json::{Value, json};
use std::collections::BTreeSet;

/// The desk of the pools.
pub struct PoolDesk<'app> {
    pub(super) app: &'app App,
}

impl<'app> PoolDesk<'app> {
    const MIGRATION: &'static str = "pools-of-steps-2026-10";
    const ROWS_MIGRATION: &'static str = "pools-of-rows-2026-10";
    const ADDED_MIGRATION: &'static str = "added-models-2026-10";
    pub(super) const NAME_MAX: usize = 80;
    pub(super) const NEW_NAME: &'static str = "Pool";
    /// The fields a step used to keep its levels in.
    const LEVEL_KEYS: [&'static str; 2] = ["stopAt", "switchAt"];

    /// The desk of `app`.
    pub fn of(app: &'app App) -> Self {
        Self { app }
    }

    pub(super) fn cloud(&self) -> CloudData<'app> {
        CloudData::of(self.app)
    }

    pub(super) fn proxies(&self) -> ProxiesConfig<'app> {
        ProxiesConfig::of(self.app)
    }

    fn has_migration(data: &Value, word: &str) -> bool {
        data.get("migrations").and_then(Value::as_array).into_iter().flatten().filter_map(Value::as_str).any(|said| said == word)
    }

    /// A file of the old form rewritten as pools of steps, once. What the old blocks with no client lose is said.
    pub fn migrate(&self) -> Result<Option<Value>, AppError> {
        let mut data = self.cloud().load();
        if !CloudPools::legacy(&data) {
            return Ok(None);
        }
        let mut refs = CloudModelRefs::new(&self.proxies().load()?);
        let blocks: Vec<Value> = Coerce::list(data.get("blocks"));
        let id_of = |block: &Value| Coerce::str_of(block.get("id"));
        let keep: BTreeSet<String> =
            blocks.iter().filter(|block| Coerce::truthy(block.get("exposed")) || refs.in_use(&id_of(block))).map(id_of).collect();
        let reading = CloudPools::new(&data, Some(&self.cloud().secrets()));
        let pools: Vec<Value> = blocks
            .iter()
            .filter(|block| keep.contains(&id_of(block)))
            .filter_map(|block| reading.get(&id_of(block)).cloned())
            .collect();
        let dropped: Vec<String> = blocks.iter().map(id_of).filter(|id| !keep.contains(id)).collect();
        let kept_steps: Vec<Value> = reading
            .legacy_steps
            .iter()
            .filter(|step| {
                pools
                    .iter()
                    .flat_map(|pool| pool.get("steps").and_then(Value::as_array).into_iter().flatten())
                    .any(|row| step.get("accountId") == row.get("accountId") && step.get("model") == row.get("model"))
            })
            .cloned()
            .collect();
        let levels = ModelLevels::new(&json!({"levels": data.get("levels"), "pools": [{"steps": kept_steps}]}));
        Coerce::put(&mut data, "levels", levels.stored());
        Coerce::put(&mut data, "pools", json!(pools));
        for account in data.get_mut("accounts").and_then(Value::as_array_mut).into_iter().flatten() {
            Coerce::take(account, "usageReserve");
        }
        Coerce::take(&mut data, "blocks");
        Coerce::take(&mut data, "deletedModels");
        CloudData::with_migrations(&mut data, &[Self::MIGRATION, Self::ROWS_MIGRATION]);
        self.cloud().save(&data)?;
        let ids: Vec<Value> = pools.iter().map(|pool| pool.get("id").cloned().unwrap_or(Value::Null)).collect();
        Ok(Some(json!({"pools": ids, "dropped": dropped})))
    }

    /// The levels each step kept moved onto its model, once (1.3.486).
    pub fn migrate_rows(&self) -> Result<Option<Value>, AppError> {
        let mut data = self.cloud().load();
        if Self::has_migration(&data, Self::ROWS_MIGRATION) || CloudPools::legacy(&data) {
            return Ok(None);
        }
        let levels = ModelLevels::new(&data);
        let mut moved = 0;
        for pool in data.get_mut("pools").and_then(Value::as_array_mut).into_iter().flatten() {
            for step in pool.get_mut("steps").and_then(Value::as_array_mut).into_iter().flatten() {
                if step.is_object() && Self::LEVEL_KEYS.iter().any(|key| step.get(key).is_some()) {
                    moved += 1;
                    for key in Self::LEVEL_KEYS {
                        Coerce::take(step, key);
                    }
                }
            }
        }
        let stored = levels.stored();
        let models: usize = stored
            .as_object()
            .into_iter()
            .flatten()
            .filter_map(|(_, models)| models.as_object())
            .map(|models| models.len())
            .sum();
        Coerce::put(&mut data, "levels", stored);
        CloudData::with_migrations(&mut data, &[Self::ROWS_MIGRATION]);
        self.cloud().save(&data)?;
        Ok(Some(json!({"models": models, "steps": moved})))
    }

    /// The models the pools' rows name added to Routing's column, once (1.3.491).
    pub fn migrate_added(&self) -> Result<Option<Value>, AppError> {
        let mut data = self.cloud().load();
        if Self::has_migration(&data, Self::ADDED_MIGRATION) || CloudPools::legacy(&data) {
            return Ok(None);
        }
        let mut added = AddedModels::new(&data);
        let mut count = 0;
        for pool in CloudPools::new(&data, None).all() {
            for row in pool.get("steps").and_then(Value::as_array).into_iter().flatten() {
                if row.get("kind").and_then(Value::as_str) == Some("account")
                    && added.add(&Coerce::text(row.get("accountId")), &Coerce::text(row.get("model")))
                {
                    count += 1;
                }
            }
        }
        Coerce::put(&mut data, "addedModels", added.stored());
        CloudData::with_migrations(&mut data, &[Self::ADDED_MIGRATION]);
        self.cloud().save(&data)?;
        Ok(Some(json!({"models": count})))
    }

    pub(super) fn pool_of(data: &Value, pool_id: &str) -> Result<Value, AppError> {
        CloudPools::new(data, None)
            .get(pool_id)
            .cloned()
            .ok_or_else(|| AppError::with_status(format!("unknown pool: {pool_id}"), 404))
    }

    /// `pool` in place of its stored self (or last, for a new one), kept by the shared rule.
    pub(super) fn put(data: &mut Value, pool: &Value) -> Result<Value, AppError> {
        let kept = CloudPools::pool(pool).ok_or_else(|| AppError::new("a pool needs an id"))?;
        let mut pools: Vec<Value> =
            data.get("pools").and_then(Value::as_array).into_iter().flatten().filter(|row| row.is_object()).cloned().collect();
        match pools.iter_mut().find(|row| row.get("id") == kept.get("id")) {
            Some(stored) => stored.clone_from(&kept),
            None => pools.push(kept.clone()),
        }
        Coerce::put(data, "pools", Value::Array(pools));
        Ok(kept)
    }

    pub(super) fn account_of(data: &Value, account_id: &str) -> Result<Value, AppError> {
        CloudSources::new(data, None)
            .accounts()
            .get(account_id)
            .cloned()
            .ok_or_else(|| AppError::with_status(format!("unknown account: {account_id}"), 404))
    }

    pub(super) fn model_of(model: Option<&Value>) -> Result<String, AppError> {
        let model = Coerce::stripped(model);
        if model.is_empty() {
            return Err(AppError::new("a step needs a model"));
        }
        Ok(model)
    }

    pub(super) fn name_of(name: Option<&Value>, fallback: &str) -> String {
        let name: String = Coerce::stripped(name).chars().take(Self::NAME_MAX).collect();
        let name = Coerce::strip(&name).to_string();
        if name.is_empty() { fallback.to_string() } else { name }
    }

    /// `name`, when no other pool carries it: consumers call a pool by its name.
    pub(super) fn unique(&self, data: &Value, name: &str, but: Option<&str>) -> Result<String, AppError> {
        if self.cloud().pool_names(data).taken(name, but) {
            return Err(AppError::with_status(
                format!("a pool named {name} exists — consumers call a pool by its name, so give this one another"),
                409,
            ));
        }
        Ok(name.to_string())
    }

    /// A name of the board's own choosing made free with " 2", " 3"…
    pub(super) fn free_name(&self, data: &Value, name: &str) -> String {
        let names = self.cloud().pool_names(data);
        let (mut candidate, mut number) = (name.to_string(), 2);
        while names.taken(&candidate, None) {
            candidate = format!("{name} {number}").chars().take(Self::NAME_MAX).collect();
            number += 1;
        }
        candidate
    }

    pub(super) fn slug(text: &str, taken: &BTreeSet<String>) -> String {
        let replaced: String = text
            .chars()
            .map(|letter| if letter.is_ascii_alphanumeric() || letter == '_' || letter == '-' { letter } else { '-' })
            .take(40)
            .collect();
        let base = replaced.trim_matches('-');
        let base = if base.is_empty() { "pool" } else { base };
        let (mut id, mut number) = (base.to_string(), 2);
        while taken.contains(&id) {
            id = format!("{base}-{number}");
            number += 1;
        }
        id
    }

    pub(super) fn ids_of(data: &Value) -> BTreeSet<String> {
        CloudPools::new(data, None).all().iter().map(|pool| Coerce::text(pool.get("id"))).collect()
    }

    /// Whether `name` is one the board gave, "Pool" or "Pool 2", not the operator.
    pub fn default_named(name: &str) -> bool {
        let Some(rest) = name.strip_prefix(Self::NEW_NAME) else {
            return false;
        };
        let good = Regex::new(r"^( [0-9]+)?$");
        good.is_ok_and(|good| good.is_match(rest))
    }

    pub(super) fn cabled(pool: &Value) -> bool {
        let rows = pool.get("steps").and_then(Value::as_array).into_iter().flatten();
        rows.into_iter().any(|row| matches!(row.get("kind").and_then(Value::as_str), Some("account" | "output")))
    }

    /// A pool the operator never named takes the name of the model its first cable reaches (the owner, 2026-10-12).
    pub(super) fn named_after(&self, data: &Value, pool: &mut Value, name_after: Option<&Value>, cabled_before: bool) {
        let name = Self::name_of(name_after, "");
        if !name.is_empty() && !cabled_before && Self::default_named(&Coerce::text(pool.get("name"))) {
            Coerce::put(pool, "name", json!(self.free_name(data, &name)));
        }
    }

    /// A model a row is cabled to is one Routing's column shows.
    pub(super) fn keep_model(data: &mut Value, target: &Value) {
        if Coerce::truthy(target.get("accountId")) && Coerce::truthy(target.get("model")) {
            let mut added = AddedModels::new(data);
            if added.add(&Coerce::text(target.get("accountId")), &Coerce::text(target.get("model"))) {
                Coerce::put(data, "addedModels", added.stored());
            }
        }
    }

    /// What a row's output is cabled to, as the row keeps it.
    pub(super) fn target_of(data: &Value, target: Option<&Value>) -> Result<Value, AppError> {
        let Some(target) =
            target.filter(|target| !matches!(target, Value::Null) && *target != &json!("") && *target != &json!({}))
        else {
            return Ok(json!({}));
        };
        if !target.is_object() {
            return Err(AppError::new("target must be an object: {accountId, model} or {output}"));
        }
        if Coerce::truthy(target.get("output")) {
            let output = Coerce::stripped(target.get("output"));
            if !rules::PoolRow::is_output_id(&output) {
                return Err(AppError::new(format!("not a local model: {output}")));
            }
            return Ok(json!({"output": output}));
        }
        let account = Self::account_of(data, &Coerce::text(target.get("accountId")))?;
        Ok(json!({"accountId": account.get("id"), "model": Self::model_of(target.get("model"))?}))
    }

    /// A step of `account_id` with `model`, under an id the pool does not use yet.
    pub(super) fn new_step(data: &mut Value, pool: &Value, account_id: &str, model: Option<&Value>) -> Result<Value, AppError> {
        let account = Self::account_of(data, account_id)?;
        let account_id = Coerce::text(account.get("id"));
        let id = CloudPools::step_id(&account_id, &Self::row_ids(pool));
        let step = json!({"id": id, "accountId": account_id, "model": Self::model_of(model)?, "enabled": true});
        Self::keep_model(data, &step);
        Ok(step)
    }

    pub(super) fn row_ids(pool: &Value) -> BTreeSet<String> {
        pool.get("steps").and_then(Value::as_array).into_iter().flatten().map(|row| Coerce::text(row.get("id"))).collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_default_name_is_the_board_s() {
        assert!(PoolDesk::default_named("Pool"));
        assert!(PoolDesk::default_named("Pool 2"));
        assert!(!PoolDesk::default_named("Pool two"));
        assert!(!PoolDesk::default_named("Pools"));
        assert!(!PoolDesk::default_named(""));
    }

    #[test]
    fn a_slug_is_free_and_plain() {
        let taken: BTreeSet<String> = ["gpt-5".to_string(), "gpt-5-2".to_string()].into();
        assert_eq!(PoolDesk::slug("gpt 5", &taken), "gpt-5-3");
        assert_eq!(PoolDesk::slug("---", &BTreeSet::new()), "pool");
        assert_eq!(PoolDesk::slug("модель", &BTreeSet::new()), "pool");
    }
}
