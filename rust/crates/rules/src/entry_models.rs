//! What the entry's clients call, as the entry names it.
//!
//! A client's key calls every pool and every model that runs, but what the board closed to it. `GET /v1/models` lists them, and a
//! request's `model` picks one. The same reading answers both, so that the list and the routing cannot disagree.
//!
//! A reading it cannot answer for names nothing: `Pick::Unsure`, and the client hears that the settings do not read.

use crate::casefold::Casefold;
use crate::client_deny::ClientDeny;
use crate::cloud_accounts::{CloudAccounts, CloudProvider, Credentials};
use crate::cloud_models::{AccountModelJobs, AddedModels, ModelCatalogue};
use crate::cloud_pools::{CloudPools, Pool, PoolRow, RowWork};
use crate::coerce::Coerce;
use crate::entry_refusal::EntryRefusal;
use crate::model_kind::{ModelKind, RowKind};
use crate::model_schedules::ModelSchedules;
use crate::router_outputs::{MachineOutput, RouterOutput, RouterOutputs};
use crate::usage_limits::ModelLevels;
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};

mod answer;
mod board;

/// A model a client calls without a pool.
#[derive(Debug, Clone, PartialEq, Eq)]
struct LiveEntry {
    /// The name a client calls it by.
    name: String,
    /// Whether it can serve now.
    runs: bool,
    /// Its pool of one row.
    pool: Pool,
    /// Where it stands: the key a refusal names it by.
    place: String,
    account: String,
    host: String,
    /// What it stands on, as the board names it: an output a row would refuse is still the output the board knows.
    target: RowWork,
}

/// One row of what the board knows, before its name is known: the name depends on who else has it.
struct KnownModel {
    name: String,
    /// What a name shared with another place is told apart by.
    place_word: String,
    runs: bool,
    place: String,
    account: String,
    host: String,
    work: RowWork,
}

/// The answer to a request's `model`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Pick {
    /// This process serves it: the pool the name means, whose rows are all ones it can walk.
    Pool(Box<Pool>),
    /// This process refuses it.
    Refused(EntryRefusal),
    /// The files do not read: nothing can be said of the name.
    Unsure,
}

/// One reading of everything that says what a client calls: the routers, the cloud file, the credentials and the catalogue.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct EntryModels {
    pools: Vec<Pool>,
    live: Vec<LiveEntry>,
    accounts: CloudAccounts,
    outputs: RouterOutputs,
    jobs: AccountModelJobs,
    catalogue: ModelCatalogue,
    credentials: Credentials,
    levels: ModelLevels,
    schedules: ModelSchedules,
    /// The reader the board names for the parts no pool's rows can take. `None` is the absence of the operator's decision,
    /// said as an absence — not a reader with an empty name. This is a fact of the board, not of a pool: the parts come from
    /// a request, and the request's pool only says which row was asked to read.
    reader: Option<String>,
    /// Something in the reading this cannot answer for: nothing is sure then, and the client hears that.
    unsure: bool,
}

impl EntryModels {
    const LIVE_PREFIX: &'static str = "live:";
    /// A name's place when its machine does not say which: `LiveModels._known`.
    const NO_HOST: &'static str = "machine";

    /// `routers` is the settings' list, `cloud` the cloud file, `None` for one that does not read.
    pub fn read(routers: Option<&Value>, cloud: Option<&Value>, credentials: &Credentials, catalogue: ModelCatalogue) -> Self {
        let empty = Value::Null;
        let file = cloud.unwrap_or(&empty);
        let accounts = CloudAccounts::read(file.get("accounts"));
        let pools = CloudPools::read(file);
        let known = Self::known(routers, file, &accounts, credentials);
        let mut names_sure = true;
        let live = Self::named(known, &mut names_sure);
        // An empty name is the absence of the operator's decision, not a reader named nothing.
        let named = Coerce::word(file.get(Self::READER_FIELD));
        let mut read = Self {
            unsure: cloud.is_none() || accounts.unsure() || pools.unsure() || credentials.unsure() || !names_sure,
            pools: pools.all().to_vec(),
            live,
            accounts,
            outputs: RouterOutputs::read(routers),
            jobs: AccountModelJobs::read(file.get("modelJobs")),
            catalogue,
            credentials: credentials.clone(),
            levels: ModelLevels::read(file.get("levels")),
            schedules: ModelSchedules::read(file.get("schedules")),
            reader: (!named.is_empty()).then_some(named),
        };
        read.unsure = read.unsure || read.pools.iter().any(|pool| Self::key(&pool.name).is_none());
        read
    }

    /// A name as two names are compared: trimmed, without case. `None`: a letter this cannot compare.
    fn key(name: &str) -> Option<String> {
        Some(Casefold::of(Coerce::strip(name)))
    }

    /// Every model the board knows, in order: the machines' models as their outputs come, then each account's added ones, the accounts
    /// in the file's order; each with where it stands and whether it can serve now.
    fn known(routers: Option<&Value>, file: &Value, accounts: &CloudAccounts, credentials: &Credentials) -> Vec<KnownModel> {
        let mut rows = Vec::new();
        let mut seen = BTreeSet::new();
        for out in RouterOutputs::raw(routers).filter(|out| Coerce::text(out.get("upstreamType")) == "machine") {
            let (name, id) = (Coerce::stripped(out.get("upstreamModel")), Coerce::text(out.get("id")));
            if name.is_empty() || id.is_empty() || !seen.insert(id.clone()) {
                continue;
            }
            let host = Coerce::text(out.get("hostId"));
            rows.push(KnownModel {
                name,
                place_word: if host.is_empty() { Self::NO_HOST.to_string() } else { host.clone() },
                runs: Coerce::truthy(out.get("copyPorts")),
                place: id.clone(),
                account: String::new(),
                host,
                work: RowWork::Output(id),
            });
        }
        let added = AddedModels::read(file.get("addedModels"));
        for account in accounts.iter() {
            let runs = accounts.signed_in(&account.id, credentials);
            for model in added.of(&account.id) {
                rows.push(KnownModel {
                    name: model.clone(),
                    place_word: account.id.clone(),
                    runs,
                    place: format!("acc:{}/{model}", account.id),
                    account: account.id.clone(),
                    host: String::new(),
                    work: RowWork::Account { account: account.id.clone(), model: model.clone() },
                });
            }
        }
        rows
    }

    /// Each model with the name a client calls it by: a name in two places makes two models, each with its place in brackets. Whether
    /// a name is shared is read over every model the board knows, running or not, so that a name does not change when the other place
    /// stops: a client keeps its chats by that name.
    fn named(rows: Vec<KnownModel>, sure: &mut bool) -> Vec<LiveEntry> {
        let mut count: BTreeMap<String, usize> = BTreeMap::new();
        for row in &rows {
            match Self::key(&row.name) {
                Some(key) => *count.entry(key).or_insert(0) += 1,
                None => *sure = false,
            }
        }
        rows.into_iter()
            .map(|row| {
                let shared = Self::key(&row.name).and_then(|key| count.get(&key).copied()).is_some_and(|many| many > 1);
                let name = if shared { format!("{} ({})", row.name, row.place_word) } else { row.name };
                let id = format!("{}{}", Self::LIVE_PREFIX, row.place);
                // `CloudPools.OUTPUT` holds for a live row too: an output's id it refuses makes an open row, which serves nothing.
                let target = row.work.clone();
                let work = Self::as_a_row(row.work);
                LiveEntry {
                    target,
                    pool: Pool::of_one_row(id, name.clone(), work),
                    name,
                    runs: row.runs,
                    place: row.place,
                    account: row.account,
                    host: row.host,
                }
            })
            .collect()
    }

    fn as_a_row(work: RowWork) -> RowWork {
        let raw = match &work {
            RowWork::Output(output) => json!({"id": "r1", "output": output}),
            RowWork::Account { .. } | RowWork::Open => return work,
        };
        PoolRow::read(&raw).map_or(RowWork::Open, |row| row.work)
    }

    /// The models of the live list no pool's name takes, in order: those that serve now, or every one the board knows.
    fn live_models(&self, runs_only: bool) -> impl Iterator<Item = &LiveEntry> {
        let taken: BTreeSet<Option<String>> = self.pools.iter().map(|pool| Self::key(&pool.name)).collect();
        self.live.iter().filter(move |entry| (entry.runs || !runs_only) && !taken.contains(&Self::key(&entry.name)))
    }

    /// The accounts, each with what opens it, as a row goes to them.
    pub fn provider(&self, account: &str) -> Option<CloudProvider> {
        self.accounts.provider(account, &self.credentials)
    }

    /// Whether the account has a credential kept.
    pub fn has_credential(&self, account: &str) -> bool {
        self.credentials.has(account)
    }

    /// The levels of the subscriptions' models.
    pub fn levels(&self) -> &ModelLevels {
        &self.levels
    }

    /// When each model is open.
    pub fn schedules(&self) -> &ModelSchedules {
        &self.schedules
    }

    /// The providers' lists of their models.
    pub fn catalogue(&self) -> &ModelCatalogue {
        &self.catalogue
    }

    /// The machine's model on a router's output of this id.
    pub fn output(&self, id: &str) -> Option<&RouterOutput> {
        self.outputs.get(id)
    }

    /// Every output this process can call, each with what it takes.
    pub fn callable_outputs(&self) -> impl Iterator<Item = &MachineOutput> {
        self.outputs.callable()
    }

    /// The pools the cloud file holds: those a board can edit.
    pub fn file_pools(&self) -> &[Pool] {
        &self.pools
    }

    /// Whether this reading can answer at all.
    pub fn sure(&self) -> bool {
        !self.unsure
    }

    /// What a client's key calls now, what `/v1/models` lists: every pool, then every model that runs, but what it is closed to.
    pub fn models(&self, deny: &ClientDeny) -> Vec<&Pool> {
        self.open_to(deny, true)
    }

    /// The two questions are different, so the set is held open to the flag: what a key can call now (`runs_only`), and what
    /// the board has facts about (a name the board knows but cannot call this second still has facts to read against).
    fn open_to(&self, deny: &ClientDeny, runs_only: bool) -> Vec<&Pool> {
        let pools = self.pools.iter().filter(|pool| !deny.closes_pool(&pool.id));
        let known = self
            .live_models(runs_only)
            .filter(|entry| !deny.closes(&entry.place, &entry.account, &entry.host))
            .map(|entry| &entry.pool);
        pools.chain(known).collect()
    }

    /// The pool a request's `model` names among the client's, spelled as the list spells it; `None` for a name its key does not call now.
    pub fn pick(&self, deny: &ClientDeny, wanted: &str) -> Option<&Pool> {
        if wanted.is_empty() {
            return None;
        }
        self.models(deny).into_iter().find(|pool| pool.name == wanted)
    }

    /// The name the board named as its reader, as the file holds it. `None` is the absence of the operator's decision, said
    /// as an absence — not a reader named nothing.
    pub fn reader(&self) -> Option<&str> {
        self.reader.as_deref()
    }

    /// The model `wanted` names among everything the board knows, running or not. This is what a reader is checked against:
    /// the rule asks what a name's facts promise, not whether a call is possible this second, so a model the board knows and
    /// cannot call is still a name with a promise, and `Reader::Unknown` stays the answer for a name no place in the reading
    /// has. A reading that holds only the pools answers `unknown` for every model name, which is a fact about the reading.
    pub fn known_name(&self, deny: &ClientDeny, wanted: &str) -> Option<&Pool> {
        if wanted.is_empty() {
            return None;
        }
        self.open_to(deny, false).into_iter().find(|pool| pool.name == wanted)
    }

    /// Whether `wanted` names a pool or a model the board knows, running or not, that this client is closed to.
    pub fn closed(&self, deny: &ClientDeny, wanted: &str) -> bool {
        if let Some(pool) = self.pools.iter().find(|pool| pool.name == wanted) {
            return deny.closes_pool(&pool.id);
        }
        self.live_models(false)
            .find(|entry| entry.name == wanted)
            .is_some_and(|entry| deny.closes(&entry.place, &entry.account, &entry.host))
    }

    /// Whether `wanted` names a model the board knows that does not serve now.
    pub fn stopped(&self, wanted: &str) -> bool {
        self.live_models(false).any(|entry| !entry.runs && entry.name == wanted)
    }

    /// What a pool's rows do together.
    pub fn kind(&self, pool: &Pool) -> Option<ModelKind> {
        ModelKind::of_pool(pool, &self.accounts, &self.outputs, &self.jobs)
    }

    /// What one row says of itself: `ServesNothing` for a row that names no work, or whose account or cell is gone.
    pub fn row_kind(&self, row: &PoolRow) -> RowKind {
        ModelKind::of_row(row, &self.accounts, &self.outputs, &self.jobs)
    }

    /// The window a pool stands for.
    pub fn window(&self, pool: &Pool) -> Option<i64> {
        pool.window(|row| match &row.work {
            RowWork::Account { account, model } => {
                let owner = self.accounts.canonical(account).map_or(account.as_str(), |owner| owner.id.as_str());
                self.catalogue.window(owner, model)
            }
            RowWork::Output(output) => self.outputs.get(output).and_then(|found| found.window),
            RowWork::Open => None,
        })
    }

    /// What a request's `model` means: the pool that serves it, what the entry refuses it with, or that the files do not read.
    pub fn for_request(&self, deny: &ClientDeny, wanted: &str, path: &str) -> Pick {
        if self.unsure {
            return Pick::Unsure;
        }
        if Coerce::strip(wanted).is_empty() {
            return Pick::Refused(EntryRefusal::no_model());
        }
        let Some(pool) = self.pick(deny, wanted) else {
            return Pick::Refused(self.refusal_of(deny, wanted));
        };
        if self.kind(pool).is_some_and(|kind| !kind.serves(path)) {
            return Pick::Refused(EntryRefusal::unsupported(&pool.name, path));
        }
        Pick::Pool(Box::new(pool.clone()))
    }

    /// A model this client does not call now, said as what it is: closed to it, known and not running, or a name the caravan has not; to a
    /// key that calls nothing at all now, that it has no model.
    pub fn refusal_of(&self, deny: &ClientDeny, wanted: &str) -> EntryRefusal {
        if self.closed(deny, wanted) {
            EntryRefusal::model_closed(wanted)
        } else if self.stopped(wanted) {
            EntryRefusal::model_stopped(wanted)
        } else if self.models(deny).is_empty() {
            EntryRefusal::no_pool()
        } else {
            EntryRefusal::model_unknown(wanted)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn output(over: Value) -> Value {
        let mut out = json!({"id": "mm:a", "upstreamType": "machine", "upstreamModel": "m", "upstreamHost": "h", "upstreamPort": 1, "copyPorts": [2]});
        out.as_object_mut().unwrap().extend(over.as_object().unwrap().clone());
        out
    }

    fn reading(outputs: Value, cloud: Value) -> EntryModels {
        EntryModels::read(Some(&json!([{"outputs": outputs}])), Some(&cloud), &Credentials::default(), ModelCatalogue::default())
    }

    fn picked(outputs: Value, cloud: Value, wanted: &str) -> Pick {
        reading(outputs, cloud).for_request(&ClientDeny::default(), wanted, "/v1/chat/completions")
    }

    fn pool_id(pick: Pick) -> String {
        match pick {
            Pick::Pool(pool) => pool.id,
            other => panic!("not served: {other:?}"),
        }
    }

    #[test]
    fn a_model_called_by_its_name_is_its_pool_of_one_row() {
        assert_eq!(pool_id(picked(json!([output(json!({}))]), json!({}), "m")), "live:mm:a");
    }

    #[test]
    fn an_output_of_another_kind_is_no_model_of_a_machine() {
        let of = |over: Value| picked(json!([output(over)]), json!({}), "m");
        let nothing_to_call = Pick::Refused(EntryRefusal::no_pool());
        assert_eq!(of(json!({"upstreamType": "llama"})), nothing_to_call);
        assert_eq!(of(json!({"id": ""})), nothing_to_call);
        assert_eq!(of(json!({"upstreamModel": ""})), nothing_to_call);
    }

    #[test]
    fn a_pool_with_a_cell_on_a_row_is_served_as_any_other() {
        let cell = output(json!({"id": "srv:1", "upstreamType": "llama", "upstreamModel": "cell"}));
        let pool = |rows: Value| json!({"pools": [{"id": "p", "name": "pool", "steps": rows}]});
        let on = |id: &str, output: &str| json!({"id": id, "output": output});
        assert_eq!(
            pool_id(picked(json!([cell.clone(), output(json!({}))]), pool(json!([on("r1", "mm:a"), on("r2", "srv:1")])), "pool")),
            "p"
        );
        assert_eq!(
            pool_id(picked(json!([output(json!({}))]), pool(json!([on("r1", "mm:a"), on("r2", "mm:gone")])), "pool")),
            "p"
        );
        assert_eq!(
            pool_id(picked(json!([]), pool(json!([{"id": "r1", "accountId": "key", "model": "m"}, {"id": "r2"}])), "pool")),
            "p"
        );
    }

    #[test]
    fn a_name_of_any_letters_is_compared_as_python_compares_it() {
        let outputs = json!([output(json!({}))]);
        let of = |cloud: Value| reading(outputs.clone(), cloud).sure();
        assert!(of(json!({"pools": [{"id": "p", "name": "Общий"}]})));
        assert!(of(json!({"pools": [{"id": "p", "name": "Straße"}]})));
        assert!(reading(json!([output(json!({"upstreamModel": "Straße"}))]), json!({})).sure());
        assert!(of(json!({"accounts": [{"id": "a"}], "addedModels": {"a": ["ΣΑΣ"]}})));
    }

    #[test]
    fn a_broken_file_of_any_kind_leaves_nothing_sure() {
        let routers = json!([{"outputs": [output(json!({}))]}]);
        let of = |cloud: Option<&Value>, credentials: &Credentials| {
            EntryModels::read(Some(&routers), cloud, credentials, ModelCatalogue::default()).for_request(
                &ClientDeny::default(),
                "m",
                "/v1/chat/completions",
            )
        };
        assert!(matches!(of(Some(&json!({})), &Credentials::default()), Pick::Pool(_)));
        assert_eq!(of(None, &Credentials::default()), Pick::Unsure);
        assert_eq!(of(Some(&json!({})), &Credentials::read(None)), Pick::Unsure);
        assert_eq!(of(Some(&json!({"accounts": [{"id": 5}]})), &Credentials::default()), Pick::Unsure);
        assert_eq!(of(Some(&json!({"pools": [{"id": "p", "members": []}]})), &Credentials::default()), Pick::Unsure);
    }

    #[test]
    fn a_name_that_is_the_pool_s_goes_to_the_pool_whatever_its_case() {
        let cloud = json!({"pools": [{"id": "p", "name": "M"}]});
        let outputs = json!([output(json!({}))]);
        assert_eq!(pool_id(picked(outputs.clone(), cloud.clone(), "M")), "p");
        assert_eq!(picked(outputs, cloud, "m"), Pick::Refused(EntryRefusal::model_unknown("m")));
    }
}
