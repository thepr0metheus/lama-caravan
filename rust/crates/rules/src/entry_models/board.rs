//! What the board reads of the same reading the entry answers from: who may be closed to what, and what a client that writes its models down
//! is told. It stands beside `EntryModels` so that the list a client sees and the list the board draws cannot disagree.

use super::{EntryModels, LiveEntry};
use crate::casefold::Casefold;
use crate::client_deny::ClientDeny;
use crate::cloud_pools::{Pool, PoolRow, RowWork};
use crate::coerce::Coerce;
use serde_json::{Map, Value, json};

impl EntryModels {
    /// The pool's word for a pool on a client's refusal list.
    pub fn pool_key(pool_id: &str) -> String {
        format!("pool:{pool_id}")
    }

    /// A name as two names are compared: trimmed, without case.
    pub fn key_of(name: &str) -> String {
        Casefold::of(Coerce::strip(name))
    }

    /// Whether a pool other than `but` (an id) is already called `name`.
    pub fn taken(&self, name: &str, but: Option<&str>) -> bool {
        let wanted = Self::key_of(name);
        self.pools.iter().any(|pool| Self::key_of(&pool.name) == wanted && Some(pool.id.as_str()) != but)
    }

    fn names_shadowed(&self) -> impl Iterator<Item = &LiveEntry> {
        let taken: Vec<String> = self.pools.iter().map(|pool| Self::key_of(&pool.name)).collect();
        self.live.iter().filter(move |entry| !taken.contains(&Self::key_of(&entry.name)))
    }

    /// The names of what a client closed to nothing calls now.
    pub fn names(&self, deny: &ClientDeny) -> Vec<String> {
        self.models(deny).into_iter().map(|pool| pool.name.clone()).collect()
    }

    /// What a client can be closed to, each by the key its refusal keeps, in the board's order.
    pub fn choices(&self) -> Value {
        let pools: Vec<Value> =
            self.pools.iter().map(|pool| json!({"key": Self::pool_key(&pool.id), "name": pool.name})).collect();
        let (mut models, mut sources) = (Vec::new(), Vec::new());
        for entry in self.names_shadowed() {
            let source = if !entry.account.is_empty() {
                format!("account:{}", entry.account)
            } else if !entry.host.is_empty() {
                format!("host:{}", entry.host)
            } else {
                String::new()
            };
            models
                .push(json!({"key": format!("model:{}", entry.place), "name": entry.name, "source": source, "runs": entry.runs}));
            if !source.is_empty() && !sources.contains(&source) {
                sources.push(source);
            }
        }
        json!({"pools": pools, "models": models, "sources": sources})
    }

    /// Each model the board knows with what it stands on, its pool of one row and whether it runs.
    pub fn catalog(&self) -> Vec<Value> {
        let row = |entry: &LiveEntry| {
            let mut out = Map::new();
            out.insert("id".to_string(), json!(entry.name));
            out.insert("pool".to_string(), json!(entry.pool.id));
            out.insert("runs".to_string(), json!(entry.runs));
            match &entry.target {
                RowWork::Account { account, model } => {
                    out.insert("accountId".to_string(), json!(account));
                    out.insert("model".to_string(), json!(model));
                }
                RowWork::Output(output) => {
                    out.insert("output".to_string(), json!(output));
                }
                RowWork::Open => {}
            }
            Value::Object(out)
        };
        self.live.iter().map(row).collect()
    }

    /// The model a pool's row calls; empty for a row that names none, or an output no router has.
    pub fn row_model(&self, row: &PoolRow) -> String {
        match &row.work {
            RowWork::Account { model, .. } => model.clone(),
            RowWork::Output(output) if !self.live.is_empty() => {
                self.outputs.get(output).map_or_else(String::new, |found| found.model.clone())
            }
            RowWork::Output(_) | RowWork::Open => String::new(),
        }
    }

    /// A pool's name with the models it tries in turn, as a client that lists models by name shows it.
    pub fn chain(&self, pool: &Pool) -> String {
        let names: Vec<String> =
            pool.rows.iter().filter(|row| row.enabled).map(|row| self.row_model(row)).filter(|name| !name.is_empty()).collect();
        if names.len() > 1 { format!("{} — {}", pool.name, names.join(" → ")) } else { pool.name.clone() }
    }

    /// Whether a model holds a chat; `None` for one whose work the board does not know.
    fn chats(&self, entry: &LiveEntry) -> Option<bool> {
        self.kind(&entry.pool).map(|kind| kind.chats())
    }

    /// What a built-in client that writes its models down is configured with: its pools, then the models the board knows, stopped ones too,
    /// but those that do not hold a chat: opencode offers every line of its list as a chat.
    pub fn offer(&self, deny: &ClientDeny) -> Vec<Value> {
        let pools = self.pools.iter().filter(|pool| !deny.closes_pool(&pool.id));
        let mut out: Vec<Value> = pools.map(|pool| json!({"id": pool.name, "name": self.chain(pool)})).collect();
        for entry in self.names_shadowed() {
            if !deny.closes(&entry.place, &entry.account, &entry.host) && self.chats(entry) != Some(false) {
                out.push(json!({"id": entry.name, "name": entry.name}));
            }
        }
        out
    }

    /// The clients of the entry that call `pool_id` now, by name.
    pub fn callers(&self, routes: &[Value], pool_id: &str) -> Vec<String> {
        let consumers = routes.iter().filter(|route| route.get("kind").and_then(Value::as_str) == Some("consumer"));
        consumers
            .filter(|route| {
                let deny = ClientDeny::clean(route.get(ClientDeny::FIELD));
                self.models(&deny).iter().any(|pool| pool.id == pool_id)
            })
            .map(|route| Coerce::text(route.get("label")))
            .collect()
    }

    /// The pools named as the model of their one row: a client closed to one still calls the other.
    pub fn twins(&self) -> Vec<Value> {
        let names: Vec<String> = self.live.iter().map(|entry| Self::key_of(&entry.name)).collect();
        let mut out = Vec::new();
        for pool in &self.pools {
            let [row] = pool.rows.as_slice() else { continue };
            if !row.enabled {
                continue;
            }
            let model = Self::key_of(&self.row_model(row));
            if model.is_empty() || model != Self::key_of(&pool.name) || !names.contains(&model) {
                continue;
            }
            let place = match &row.work {
                RowWork::Account { account, .. } => account.clone(),
                RowWork::Output(output) => self.outputs.get(output).map_or_else(String::new, |found| found.host.clone()),
                RowWork::Open => String::new(),
            };
            out.push(json!({"id": pool.id, "name": pool.name, "where": place}));
        }
        out
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::cloud_accounts::Credentials;
    use crate::cloud_models::ModelCatalogue;

    fn reading() -> EntryModels {
        let cloud = json!({
            "accounts": [{"id": "open", "type": "openai", "baseUrl": "https://x/v1"}],
            "addedModels": {"open": ["gpt", "shared", "Twin"]},
            "pools": [
                {"id": "fast", "name": "Fast", "contextAuto": true, "steps": [
                    {"id": "r1", "enabled": true, "accountId": "open", "model": "gpt"},
                    {"id": "r2", "enabled": true, "output": "mm:qwen"}]},
                {"id": "twin", "name": "twin", "contextAuto": true, "steps": [{"id": "r1", "enabled": true, "accountId": "open", "model": "Twin"}]},
            ],
        });
        let routers = json!([{"outputs": [
            {"id": "mm:qwen", "upstreamType": "machine", "upstreamModel": "qwen", "hostId": "h1", "upstreamPort": 1, "upstreamHost": "a", "copyPorts": [1], "jobs": ["llm"]},
            {"id": "mm:shared", "upstreamType": "machine", "upstreamModel": "shared", "hostId": "h2", "upstreamPort": 1, "upstreamHost": "a", "jobs": ["speech-to-text"]},
        ]}]);
        let secrets = json!({"open": {"apiKey": "k"}});
        EntryModels::read(Some(&routers), Some(&cloud), &Credentials::read(Some(&secrets)), ModelCatalogue::default())
    }

    #[test]
    fn a_name_is_taken_without_case_and_not_by_its_own_pool() {
        let read = reading();
        assert!(read.taken(" FAST ", None));
        assert!(!read.taken("Fast", Some("fast")));
        assert!(!read.taken("slow", None));
    }

    #[test]
    fn the_board_is_told_what_a_client_can_be_closed_to() {
        let choices = reading().choices();
        assert_eq!(choices["pools"][0], json!({"key": "pool:fast", "name": "Fast"}));
        assert_eq!(choices["sources"], json!(["host:h1", "host:h2", "account:open"]));
        let names: Vec<&str> =
            choices["models"].as_array().unwrap().iter().map(|model| model["name"].as_str().unwrap()).collect();
        assert_eq!(names, ["qwen", "shared (h2)", "gpt", "shared (open)"]);
    }

    #[test]
    fn a_chain_names_the_models_a_pool_tries_in_turn() {
        let read = reading();
        assert_eq!(read.chain(&read.file_pools()[0]), "Fast — gpt → qwen");
        assert_eq!(read.chain(&read.file_pools()[1]), "twin");
    }

    #[test]
    fn a_model_that_does_not_chat_is_not_offered() {
        let offer = reading().offer(&ClientDeny::clean(Some(&json!(["pool:twin"]))));
        let ids: Vec<&str> = offer.iter().map(|row| row["id"].as_str().unwrap()).collect();
        assert_eq!(ids, ["Fast", "qwen", "gpt", "shared (open)"]);
    }

    #[test]
    fn a_pool_named_as_its_one_row_is_a_twin() {
        assert_eq!(reading().twins(), [json!({"id": "twin", "name": "twin", "where": "open"})]);
    }

    #[test]
    fn callers_are_the_clients_not_closed_to_the_pool() {
        let routes = [
            json!({"kind": "consumer", "label": "a"}),
            json!({"kind": "consumer", "label": "b", "deny": ["pool:fast"]}),
            json!({"kind": "service", "label": "c"}),
        ];
        assert_eq!(reading().callers(&routes, "fast"), ["a"]);
    }
}
