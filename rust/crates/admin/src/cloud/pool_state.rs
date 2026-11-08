//! Every pool as the board draws it.

use super::pools::PoolDesk;
use super::refs::CloudModelRefs;
use crate::common::cloud_file::{AccountModelJobs, AddedModels, ModelLevels};
use crate::common::cloud_pools::CloudPools;
use crate::common::cloud_sources::CloudSources;
use crate::common::misc::ProxyHeartbeat;
use rules::usage_limits::{UsageReserve, UsageWindow};
use rules::{AppError, ClientDeny, Coerce, EntryModels};
use serde_json::{Map, Value, json};

impl PoolDesk<'_> {
    /// The models on Routing's column, by account, in the order they were added.
    pub fn added_models(&self) -> Value {
        AddedModels::new(&self.cloud().load()).stored()
    }

    /// What a key's model does as Routing's strip draws it.
    pub fn model_jobs(&self) -> Value {
        let data = self.cloud().load();
        let mut fixed = Map::new();
        for (id, account) in CloudSources::new(&data, None).accounts() {
            if let Some(jobs) = CloudSources::fixed_jobs(account) {
                fixed.insert(id.clone(), jobs);
            }
        }
        json!({"offered": AccountModelJobs::OFFERED, "set": AccountModelJobs::new(&data).stored(), "fixed": fixed})
    }

    fn state_file(&self) -> Option<Value> {
        let path = &self.app.paths.agent_proxy_state_file;
        serde_json::from_slice(&std::fs::read(path).ok()?).ok()
    }

    /// The proxy's word on each pool, while the proxy is alive to say it: which step served last, why the others did not, the switches.
    pub fn runtime(&self) -> Value {
        let state = self.state_file().filter(Value::is_object);
        let Some(state) = state.filter(|state| ProxyHeartbeat::fresh(state.get("time"), self.app.now())) else {
            return json!({"available": false, "pools": {}, "events": []});
        };
        let rows = state.get("pools");
        let at = |key: &str, otherwise: Value| rows.and_then(|rows| rows.get(key)).cloned().unwrap_or(otherwise);
        json!({"available": true, "pools": at("pools", json!({})), "events": at("events", json!([]))})
    }

    /// The levels of the subscription models as Routing's right column draws them.
    pub fn model_levels(&self) -> Value {
        json!({
            "max": Self::MAX_PCT,
            "default": {"stopAt": Self::new_step_levels(), "switchAt": Self::new_step_levels()},
            "set": ModelLevels::new(&self.cloud().load()).stored(),
        })
    }

    fn windows_of(raw: Option<&Value>) -> Option<Vec<UsageWindow>> {
        let rows = raw?;
        let rows = rows.as_array().map_or(&[][..], Vec::as_slice);
        let read = |row: &Value| {
            let seconds = row.get("seconds").and_then(Coerce::int)?;
            let used_pct = row.get("usedPct").and_then(Coerce::int)?;
            let reset_at = match row.get("resetAt").filter(|said| Coerce::truthy(Some(*said))) {
                Some(said) => Some(Coerce::int(said)?),
                None => None,
            };
            Some(UsageWindow { seconds, used_pct, reset_at })
        };
        Some(rows.iter().filter_map(read).collect())
    }

    fn account_row(step: &Value, sources: &CloudSources, levels: &ModelLevels, readings: &Value, now: f64) -> Value {
        let account = Coerce::text(step.get("accountId"));
        let owner = sources.quota_owner(&account);
        let owner_id = owner.and_then(|owner| owner.get("id"));
        let reading = owner_id.and_then(|id| readings.get(Coerce::text(Some(id))));
        let windows = Self::windows_of(reading.filter(|reading| reading.is_object()).and_then(|reading| reading.get("windows")));
        let (stop, switch) = levels.of(&account, &Coerce::text(step.get("model")));
        let reached = |pair: &Value| match &windows {
            Some(windows) => UsageReserve::normalize(Some(pair)).verdict(windows, now).map_or(Value::Null, |hit| hit.as_json()),
            None => Value::Null,
        };
        let read_at =
            reading.and_then(|reading| reading.get("readAt")).filter(|said| Coerce::truthy(Some(*said))).and_then(Coerce::int);
        let mut out = step.clone();
        let (switch_reached, stop_reached) = (reached(&switch), reached(&stop));
        Coerce::put(&mut out, "switchAt", switch);
        Coerce::put(&mut out, "stopAt", stop);
        Coerce::put(&mut out, "usageAccountId", owner_id.cloned().unwrap_or(Value::Null));
        Coerce::put(&mut out, "switchReached", switch_reached);
        Coerce::put(&mut out, "stopReached", stop_reached);
        Coerce::put(&mut out, "readAt", read_at.map_or(Value::Null, |at| json!(at)));
        out
    }

    /// Every pool as the board draws it.
    pub fn state(&self) -> Result<Value, AppError> {
        let data = self.cloud().load();
        let secrets = self.cloud().secrets();
        let sources = CloudSources::new(&data, Some(&secrets));
        let state = self.state_file().unwrap_or_else(|| json!({}));
        let readings = state.get("subscriptionUsage").filter(|said| said.is_object()).cloned().unwrap_or_else(|| json!({}));
        let mut refs = CloudModelRefs::new(&self.proxies().load()?);
        let now = self.app.now();
        let levels = ModelLevels::new(&data);
        let mut out = Vec::new();
        for pool in CloudPools::new(&data, None).all() {
            let id = Coerce::text(pool.get("id"));
            let rows = pool.get("steps").and_then(Value::as_array).into_iter().flatten();
            let steps: Vec<Value> = rows
                .map(|step| {
                    if step.get("kind").and_then(Value::as_str) == Some("account") {
                        Self::account_row(step, &sources, &levels, &readings, now)
                    } else {
                        step.clone()
                    }
                })
                .collect();
            let mut row = pool.clone();
            Coerce::put(&mut row, "steps", Value::Array(steps));
            Coerce::put(&mut row, "inUse", json!(refs.in_use(&id)));
            Coerce::put(&mut row, "held", refs.held(&id));
            Coerce::put(&mut row, "switchMax", json!(Self::MAX_PCT));
            out.push(row);
        }
        Ok(Value::Array(out))
    }

    /// The board's reader as the reader block draws it (`top.reader`): the name the operator named, and the word the rule gave
    /// for that name. The page does not work a state out, so the answer is read here, from `Reader::word()`, with the
    /// operator's view (`ClientDeny::clean(None)`) — the board is not one client's view of what is closed.
    ///
    /// `named` is the reading the board's answer is built from (`topology::cloud_part`), so the block and the entry read the
    /// same reading, and the topology does not read the files a second time for one row. Asked with no pool: the reader is
    /// one fact for the whole board, so a name here cannot be the board itself, and the word `itself` cannot come from this
    /// row. It comes from a request, whose pool is named.
    pub fn reader(named: &EntryModels) -> Value {
        let operator = ClientDeny::clean(None);
        let answer = named.wired(&operator, None).promise(EntryModels::READER_WORD);
        json!({"name": named.reader(), "answer": answer.word()})
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use rules::{Credentials, ModelCatalogue};

    /// The board's reading of a cloud file with one signed-in subscription that offers `gpt-6-luna`, whose facts say it takes
    /// `image` (the case `contract/media_reader.json` names for the door), and `reader` as the file says it.
    fn reading(reader: Option<&str>) -> EntryModels {
        let mut cloud = json!({
            "accounts": [{"id": "chatgpt-subscription", "accountType": "openai-subscription"}],
            "pools": [{"id": "pool-1", "name": "coder-auto", "steps": []}],
            "addedModels": {"chatgpt-subscription": ["gpt-6-luna"]},
        });
        if let Some(reader) = reader {
            Coerce::put(&mut cloud, EntryModels::READER_FIELD, json!(reader));
        }
        let secrets = json!({"chatgpt-subscription": "key"});
        EntryModels::read(Some(&json!([])), Some(&cloud), &Credentials::read(Some(&secrets)), ModelCatalogue::default())
    }

    #[test]
    fn the_board_s_reader_is_the_name_the_file_holds_and_the_rule_s_word_for_it() {
        assert_eq!(PoolDesk::reader(&reading(Some("gpt-6-luna"))), json!({"name": "gpt-6-luna", "answer": "reads"}));
        // Negative: nothing named is said as nothing, with the name absent rather than empty — the block draws "not named"
        // from the absence, and an empty name would read as a reader named nothing.
        assert_eq!(PoolDesk::reader(&reading(None)), json!({"name": null, "answer": "nothing"}));
        // Negative: a name the board has no facts about is drawn as what the rule says of it, not as a reader.
        assert_eq!(PoolDesk::reader(&reading(Some("gpt-9-mira"))), json!({"name": "gpt-9-mira", "answer": "unknown"}));
    }
}
