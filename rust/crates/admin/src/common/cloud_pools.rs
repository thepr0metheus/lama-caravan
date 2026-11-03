//! A pool as the controller reads and writes cloud-providers.json. The pools of the file in either form: a list of steps, or the old model blocks.

use super::cloud_sources::CloudSources;
use super::window::Windows;
use rules::{Coerce, PoolRow};
use serde_json::{Map, Value, json};
use std::collections::BTreeSet;

/// The window a local output serves.
pub type LocalWindow<'asked> = &'asked dyn Fn(&str) -> Option<i64>;

/// The pools of one reading of the file, in either form.
pub struct CloudPools {
    sources: CloudSources,
    /// Every step the old form's blocks became.
    pub legacy_steps: Vec<Value>,
    pools: Map<String, Value>,
}

impl CloudPools {
    /// The reading of `data`, with the keys in `secrets`.
    pub fn new(data: &Value, secrets: Option<&Value>) -> Self {
        let mut this = Self { sources: CloudSources::new(data, secrets), legacy_steps: Vec::new(), pools: Map::new() };
        let read: Vec<Value> = if Self::legacy(data) {
            // absent-ok: a file of the old form with no blocks has no pools
            let blocks = Coerce::list(data.get("blocks"));
            blocks
                .iter()
                .filter(|block| block.is_object() && !Self::id(block.get("id")).is_empty())
                .filter_map(|block| this.of_block(block))
                .collect()
        } else {
            data.get("pools").and_then(Value::as_array).into_iter().flatten().filter_map(Self::pool).collect()
        };
        for pool in read {
            this.pools.insert(Coerce::text(pool.get("id")), pool);
        }
        this
    }

    /// The sources of this reading.
    pub fn sources(&self) -> &CloudSources {
        &self.sources
    }

    /// The pool of an id.
    pub fn get(&self, pool_id: &str) -> Option<&Value> {
        self.pools.get(pool_id)
    }

    /// All of them, in order.
    pub fn all(&self) -> Vec<Value> {
        self.pools.values().cloned().collect()
    }

    /// Whether the file is in the old form: blocks, or pools with members.
    pub fn legacy(data: &Value) -> bool {
        Coerce::truthy(data.get("blocks"))
            || data
                .get("pools")
                .and_then(Value::as_array)
                .into_iter()
                .flatten()
                .any(|pool| pool.is_object() && pool.get("members").is_some())
    }

    /// One row as it is kept, or none without an id.
    pub fn step(raw: &Value) -> Option<Value> {
        raw.as_object()?;
        let word = |key: &str| if Coerce::truthy(raw.get(key)) { Coerce::stripped(raw.get(key)) } else { String::new() };
        let (id, account, model, output) = (word("id"), word("accountId"), word("model"), word("output"));
        if id.is_empty() {
            return None;
        }
        let on = |key: &str| raw.get(key).is_none_or(|flag| Coerce::truthy(Some(flag)));
        let enabled = on("enabled") && on("automatic");
        if !account.is_empty() && !model.is_empty() {
            return Some(json!({"id": id, "kind": "account", "accountId": account, "model": model, "enabled": enabled}));
        }
        if PoolRow::is_output_id(&output) {
            return Some(json!({"id": id, "kind": "output", "output": output, "enabled": enabled}));
        }
        Some(json!({"id": id, "kind": "open", "enabled": enabled}))
    }

    /// One pool as it is kept, or none.
    pub fn pool(raw: &Value) -> Option<Value> {
        raw.as_object()?;
        let id = Self::id(raw.get("id"));
        if id.is_empty() {
            return None;
        }
        let (mut steps, mut seen) = (Vec::new(), BTreeSet::new());
        for item in raw.get("steps").and_then(Value::as_array).into_iter().flatten() {
            if let Some(step) = Self::step(item)
                && seen.insert(Coerce::text(step.get("id")))
            {
                steps.push(step);
            }
        }
        let said =
            if Coerce::truthy(raw.get("name")) { Coerce::stripped(raw.get("name")) } else { Coerce::strip(&id).to_string() };
        let mut out = json!({"id": id, "name": if said.is_empty() { id.clone() } else { said }, "steps": steps, "contextAuto": Coerce::truthy(raw.get("contextAuto"))});
        if let (Some(window), Value::Object(fields)) = (Self::positive(raw.get("contextLength")), &mut out) {
            fields.insert("contextLength".to_string(), json!(window));
        }
        Some(out)
    }

    /// An id: a string or a whole number, trimmed; anything else is none.
    pub fn id(value: Option<&Value>) -> String {
        match value {
            Some(Value::String(text)) => Coerce::strip(text).to_string(),
            Some(Value::Number(number)) if number.is_i64() || number.is_u64() => {
                let text = number.to_string();
                if text == "0" { String::new() } else { text }
            }
            _ => String::new(),
        }
    }

    /// A size, or none.
    pub fn positive(value: Option<&Value>) -> Option<i64> {
        value.filter(|value| !value.is_boolean()).and_then(Coerce::int).filter(|number| *number > 0)
    }

    /// The id a new step of `account_id` gets in a pool whose step ids are `taken`.
    pub fn step_id(account_id: &str, taken: &BTreeSet<String>) -> String {
        let base = Coerce::first_letters(account_id, 44);
        let (mut id, mut number) = (base.to_string(), 2);
        while taken.contains(&id) {
            id = format!("{base}-{number}");
            number += 1;
        }
        id
    }

    /// The id of a row added in Routing.
    pub fn row_id(taken: &BTreeSet<String>) -> String {
        let mut number = 1;
        while taken.contains(&format!("r{number}")) {
            number += 1;
        }
        format!("r{number}")
    }

    /// A model block of the old form as the pool it becomes.
    fn of_block(&mut self, block: &Value) -> Option<Value> {
        let account_id =
            if Coerce::truthy(block.get("accountId")) { Coerce::text(block.get("accountId")) } else { String::new() };
        let model = if Coerce::truthy(block.get("model")) { Coerce::stripped(block.get("model")) } else { String::new() };
        let name = if Coerce::truthy(block.get("name")) {
            block.get("name").cloned().unwrap_or(Value::Null)
        } else if model.is_empty() {
            block.get("id").cloned().unwrap_or(Value::Null)
        } else {
            json!(model)
        };
        let steps: Vec<Value> = match self.sources.old_pools().get(&account_id).filter(|old| old.get("members").is_some()) {
            Some(old) => {
                let members = old.get("members").and_then(Value::as_array).into_iter().flatten();
                let on = |member: &Value, key: &str| member.get(key).cloned().unwrap_or_else(|| json!(true));
                members
                    .filter(|member| member.is_object() && Coerce::truthy(member.get("accountId")))
                    .map(|member| {
                        self.legacy_step(
                            &Coerce::text(member.get("accountId")),
                            &model,
                            on(member, "enabled"),
                            on(member, "automatic"),
                        )
                    })
                    .collect()
            }
            None => vec![self.legacy_step(&account_id, &model, json!(true), json!(true))],
        };
        self.legacy_steps.extend(steps.iter().cloned());
        let context_auto = block.get("contextAuto").cloned().unwrap_or_else(|| json!(false));
        Self::pool(
            &json!({"id": Self::id(block.get("id")), "name": name, "contextLength": block.get("contextLength"), "contextAuto": context_auto, "steps": steps}),
        )
    }

    /// A member, or a block's own account, of the old form as a step.
    fn legacy_step(&self, account_id: &str, model: &str, enabled: Value, automatic: Value) -> Value {
        let source = self.sources.source(account_id).unwrap_or_else(|| json!({}));
        let switch_at =
            source.get("usageReserve").filter(|reserve| Coerce::truthy(Some(*reserve))).cloned().unwrap_or_else(|| json!({}));
        json!({"id": account_id, "accountId": account_id, "model": model, "switchAt": switch_at, "enabled": enabled, "automatic": automatic})
    }

    /// The context window a pool stands for, by the pool rule: with `contextAuto`, the smallest of its rows that may serve, when each of them knows.
    pub fn window(pool: &Value, catalogue: &dyn Fn(&str, &str) -> Option<i64>, local: Option<LocalWindow<'_>>) -> Option<i64> {
        let auto = Coerce::truthy(pool.get("contextAuto"));
        let mut reported = None;
        if auto {
            let rows = pool.get("steps").and_then(Value::as_array).into_iter().flatten();
            let serving = rows.filter(|row| {
                row.get("enabled").is_none_or(|flag| Coerce::truthy(Some(flag)))
                    && row.get("kind").and_then(Value::as_str) != Some("open")
            });
            let named: Vec<Option<i64>> = serving
                .map(|row| {
                    if row.get("kind").and_then(Value::as_str).unwrap_or("account") == "account" {
                        catalogue(&Coerce::text(row.get("accountId")), &Coerce::text(row.get("model")))
                            .filter(|window| *window > 0)
                    } else {
                        local.and_then(|local| local(&Coerce::text(row.get("output")))).filter(|window| *window > 0)
                    }
                })
                .collect();
            if !named.is_empty() && named.iter().all(Option::is_some) {
                reported = named.into_iter().flatten().min();
            }
        }
        Windows::pool(pool.get("contextLength"), reported, auto)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_row_says_what_it_can() {
        assert_eq!(
            CloudPools::step(&json!({"id": "a", "accountId": "x", "model": "m"})),
            Some(json!({"id": "a", "kind": "account", "accountId": "x", "model": "m", "enabled": true}))
        );
        assert_eq!(
            CloudPools::step(&json!({"id": "a", "output": "srv:h:1", "automatic": false})),
            Some(json!({"id": "a", "kind": "output", "output": "srv:h:1", "enabled": false}))
        );
        assert_eq!(
            CloudPools::step(&json!({"id": "a", "accountId": "x"})),
            Some(json!({"id": "a", "kind": "open", "enabled": true}))
        );
        assert_eq!(CloudPools::step(&json!({"accountId": "x", "model": "m"})), None);
    }

    #[test]
    fn a_pool_keeps_one_row_of_an_id_and_says_its_window_only_when_positive() {
        let pool = CloudPools::pool(&json!({"id": " p ", "steps": [{"id": "a"}, {"id": "a"}], "contextLength": "0"})).unwrap();
        assert_eq!(
            pool,
            json!({"id": "p", "name": "p", "steps": [{"id": "a", "kind": "open", "enabled": true}], "contextAuto": false})
        );
        assert!(CloudPools::pool(&json!({"id": true})).is_none());
    }

    #[test]
    fn the_old_form_becomes_pools() {
        let data = json!({"accounts": [{"id": "s", "accountType": "openai-subscription"}], "pools": [{"id": "old", "name": "Old", "members": [{"accountId": "s"}]}], "blocks": [{"id": "b", "accountId": "old", "model": "m"}, {"id": "c", "accountId": "s", "model": "n", "name": "N"}]});
        let pools = CloudPools::new(&data, None);
        assert_eq!(pools.get("b").unwrap().get("steps").unwrap().as_array().unwrap().len(), 1);
        assert_eq!(pools.get("c").unwrap().get("name"), Some(&json!("N")));
        assert_eq!(pools.legacy_steps.len(), 2);
    }

    #[test]
    fn a_window_of_rows_is_their_smallest_when_each_knows() {
        let catalogue = |account: &str, _model: &str| (account != "x").then_some(100);
        let local = |_output: &str| Some(50);
        let local: &dyn Fn(&str) -> Option<i64> = &local;
        let pool = json!({"contextAuto": true, "contextLength": 10, "steps": [{"kind": "account", "accountId": "a", "model": "m"}, {"kind": "output", "output": "o"}]});
        assert_eq!(CloudPools::window(&pool, &catalogue, Some(local)), Some(50));
        let unknown =
            json!({"contextAuto": true, "contextLength": 10, "steps": [{"kind": "account", "accountId": "x", "model": "m"}]});
        assert_eq!(CloudPools::window(&unknown, &catalogue, Some(local)), Some(10));
        assert_eq!(CloudPools::window(&json!({"contextLength": 10}), &catalogue, None), Some(10));
    }

    #[test]
    fn new_ids_step_around_the_taken_ones() {
        let taken: BTreeSet<String> = ["a".to_string(), "a-2".to_string(), "r1".to_string()].into();
        assert_eq!(CloudPools::step_id("a", &taken), "a-3");
        assert_eq!(CloudPools::row_id(&taken), "r2");
    }
}
