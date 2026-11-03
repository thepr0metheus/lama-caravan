//! What a pool says of an account's models: their levels, their jobs, their column in Routing.

use super::*;

impl PoolDesk<'_> {
    /// One level of one window of a subscription's model.
    pub fn set_level(
        &self,
        account_id: &str,
        model: Option<&Value>,
        window_seconds: Option<&Value>,
        pct: Option<&Value>,
        level: &str,
    ) -> Result<Value, AppError> {
        let key = match level {
            "switch" => "switchAt",
            "stop" => "stopAt",
            _ => return Err(AppError::new("level must be switch or stop")),
        };
        let number = |raw: Option<&Value>| raw.and_then(Coerce::int);
        let (Some(seconds), Some(pct)) = (number(window_seconds), number(pct)) else {
            return Err(AppError::new("windowSeconds and pct must be numbers"));
        };
        if seconds <= 0 {
            return Err(AppError::new("windowSeconds must be positive"));
        }
        if !(0..=Self::MAX_PCT).contains(&pct) {
            return Err(AppError::new(format!("pct must be 0..{}", Self::MAX_PCT)));
        }
        let mut data = self.cloud().load();
        let account = Self::account_of(&data, account_id)?;
        let model = Self::model_of(model)?;
        if !CloudSources::is_subscription(&account) {
            return Err(AppError::new("a level is kept only on a ChatGPT subscription's model"));
        }
        let id = Coerce::text(account.get("id"));
        let mut levels = ModelLevels::new(&data);
        let (mut stop, mut switch) = levels.of(&id, &model);
        let pair = if key == "stopAt" { &mut stop } else { &mut switch };
        if pct != 0 {
            Coerce::put(pair, &seconds.to_string(), json!(pct));
        } else {
            Coerce::take(pair, &seconds.to_string());
        }
        let (stop, switch) = levels.put(&id, &model, &stop, &switch);
        Coerce::put(&mut data, "levels", levels.stored());
        self.cloud().save(&data)?;
        Ok(json!({"switchAt": switch, "stopAt": stop}))
    }

    /// What a key's model does, in the operator's word.
    pub fn set_jobs(&self, account_id: &str, model: Option<&Value>, jobs: Option<&Value>) -> Result<Value, AppError> {
        let jobs = jobs.and_then(Value::as_array).ok_or_else(|| AppError::new("jobs must be a list"))?;
        let unknown = AccountModelJobs::unknown(jobs);
        if !unknown.is_empty() {
            let named: Vec<String> = unknown.iter().map(|job| Coerce::str_of(Some(job))).collect();
            return Err(AppError::new(format!(
                "not a job a key's model may be said to do: {} (one of {})",
                named.join(", "),
                AccountModelJobs::OFFERED.join(", ")
            )));
        }
        let mut data = self.cloud().load();
        let account = Self::account_of(&data, account_id)?;
        let model = Self::model_of(model)?;
        if CloudSources::fixed_jobs(&account).is_some() {
            return Err(AppError::new("a ChatGPT subscription's or an Anthropic key's model does the work its type fixes"));
        }
        let mut said = AccountModelJobs::new(&data);
        let kept = said.put(&Coerce::text(account.get("id")), &model, jobs);
        Coerce::put(&mut data, "modelJobs", said.stored());
        self.cloud().save(&data)?;
        // absent-ok: a model with no jobs left says an empty list.
        Ok(json!(kept.unwrap_or_default()))
    }

    /// The account and model a pool's account row names: the page before 1.3.486 set a level by its pool and step.
    pub fn row_target(&self, pool_id: &str, step_id: &str) -> Result<(String, String), AppError> {
        let data = self.cloud().load();
        let pool = Self::pool_of(&data, pool_id)?;
        let row =
            pool.get("steps").and_then(Value::as_array).into_iter().flatten().find(|row| Coerce::text(row.get("id")) == step_id);
        let row = row.ok_or_else(|| AppError::with_status(format!("pool {pool_id} has no step {step_id}"), 404))?;
        if row.get("kind").and_then(Value::as_str) != Some("account") {
            return Err(AppError::new("a level is kept only on a subscription's model"));
        }
        Ok((Coerce::text(row.get("accountId")), Coerce::text(row.get("model"))))
    }

    /// One account and every step that names it deleted, in every pool; what opened it.
    pub fn remove_account(&self, account_id: &str) -> Result<Option<Value>, AppError> {
        let account_id = Coerce::strip(account_id).to_string();
        let mut data = self.cloud().load();
        let accounts = Coerce::list(data.get("accounts"));
        if accounts.iter().any(|account| account.get("testAliasOf").and_then(Value::as_str) == Some(account_id.as_str())) {
            return Err(AppError::with_status("delete this account's legacy test aliases first", 409));
        }
        for mut pool in CloudPools::new(&data, None).all() {
            let names_it = |row: &Value| row.get("accountId").and_then(Value::as_str) == Some(account_id.as_str());
            if pool.get("steps").and_then(Value::as_array).into_iter().flatten().any(names_it) {
                Self::keep_rows(&mut pool, |row| !names_it(row));
                Self::put(&mut data, &pool)?;
            }
        }
        let mut levels = ModelLevels::new(&data);
        levels.forget_account(&account_id);
        Coerce::put(&mut data, "levels", levels.stored());
        let mut added = AddedModels::new(&data);
        added.forget_account(&account_id);
        Coerce::put(&mut data, "addedModels", added.stored());
        let mut schedules = ModelSchedules::new(&data);
        schedules.forget_account(&account_id);
        Coerce::put(&mut data, "schedules", schedules.stored());
        let mut said = AccountModelJobs::new(&data);
        said.forget_account(&account_id);
        Coerce::put(&mut data, "modelJobs", said.stored());
        if let Some(rows) = data.get_mut("accounts").and_then(Value::as_array_mut) {
            rows.retain(|row| row.get("id").and_then(Value::as_str) != Some(account_id.as_str()));
        }
        self.cloud().save(&data)?;
        self.cloud().vault().delete(&account_id).map_err(|error| AppError::with_status(error.to_string(), 500))
    }

    /// A labelled routing-test alias of a subscription.
    pub fn clone_test(&self, source_id: &str) -> Result<Value, AppError> {
        let mut data = self.cloud().load();
        let sources = CloudSources::new(&data, None);
        let owner = sources.canonical(source_id).filter(|owner| CloudSources::is_subscription(owner)).cloned();
        let Some(owner) = owner else {
            return Err(AppError::new("test aliases require an existing ChatGPT subscription"));
        };
        let owner_id = Coerce::text(owner.get("id"));
        let accounts = Coerce::list(data.get("accounts"));
        if let Some(existing) =
            accounts.iter().find(|row| row.get("testAliasOf").and_then(Value::as_str) == Some(owner_id.as_str()))
        {
            return Ok(existing.clone());
        }
        let stem: String = owner_id.chars().take(40).collect::<String>() + "-test";
        let (mut id, mut number) = (stem.clone(), 2);
        while sources.accounts().contains_key(&id) {
            id = format!("{stem}-{number}");
            number += 1;
        }
        let shown = owner.get("name").map_or_else(|| owner_id.clone(), |name| Coerce::str_of(Some(name)));
        let mut alias = owner;
        Coerce::put(&mut alias, "id", json!(id));
        Coerce::put(&mut alias, "name", json!(format!("{shown} · TEST")));
        Coerce::put(&mut alias, "testAliasOf", json!(owner_id));
        if let Some(rows) = data.get_mut("accounts").and_then(Value::as_array_mut) {
            rows.push(alias.clone());
        }
        self.cloud().save(&data)?;
        Ok(alias)
    }

    /// One of an account's models put on Routing's column, last.
    pub fn add_model(&self, account_id: &str, model: Option<&Value>) -> Result<Vec<String>, AppError> {
        let mut data = self.cloud().load();
        let id = Coerce::text(Self::account_of(&data, account_id)?.get("id"));
        let mut added = AddedModels::new(&data);
        if added.add(&id, &Self::model_of(model)?) {
            Coerce::put(&mut data, "addedModels", added.stored());
            self.cloud().save(&data)?;
        }
        Ok(added.of(&id))
    }

    /// A model taken off Routing's column, while no row is cabled to it.
    pub fn remove_model(&self, account_id: &str, model: Option<&Value>) -> Result<Vec<String>, AppError> {
        let mut data = self.cloud().load();
        let id = Coerce::text(Self::account_of(&data, account_id)?.get("id"));
        let model = Self::model_of(model)?;
        let mut holders = Vec::new();
        for pool in CloudPools::new(&data, None).all() {
            let holds = pool.get("steps").and_then(Value::as_array).into_iter().flatten().any(|row| {
                row.get("kind").and_then(Value::as_str) == Some("account")
                    && Coerce::text(row.get("accountId")) == id
                    && Coerce::text(row.get("model")) == model
            });
            if holds {
                holders.push(Coerce::text(pool.get("name")));
            }
        }
        if !holders.is_empty() {
            return Err(AppError::with_status(
                format!("{model}: a row of {} is cabled to it — take that cable away first", holders.join(", ")),
                409,
            ));
        }
        let mut added = AddedModels::new(&data);
        if added.remove(&id, &model) {
            Coerce::put(&mut data, "addedModels", added.stored());
            self.cloud().save(&data)?;
        }
        Ok(added.of(&id))
    }

    /// The levels a new step starts from.
    pub fn new_step_levels() -> Value {
        let row: Map<String, Value> =
            UsageLevels::NEW_STEP.iter().map(|(seconds, pct)| ((*seconds).to_string(), json!(pct))).collect();
        Value::Object(row)
    }
}
