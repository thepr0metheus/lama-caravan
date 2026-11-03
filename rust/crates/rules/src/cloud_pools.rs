//! A pool as the readers of `cloud-providers.json` see it, an ordered list of rows, with the window it stands for.

use crate::coerce::Coerce;
use serde_json::Value;

/// What a row of a pool names.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum RowWork {
    /// An account at a provider with one model.
    Account {
        /// The account's id.
        account: String,
        /// The model.
        model: String,
    },
    /// A local model: a cell's, an engine's or a machine's output.
    Output(String),
    /// Nothing cabled to it yet: it serves nothing.
    Open,
}

/// One row.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PoolRow {
    /// Its id, unique in its pool.
    pub id: String,
    /// What it names.
    pub work: RowWork,
    /// Whether it is switched on.
    pub enabled: bool,
}

impl PoolRow {
    /// The prefixes a local output's id has.
    const OUTPUT_KINDS: [&'static str; 3] = ["srv:", "eng:", "mm:"];
    const OUTPUT_LETTERS_MAX: usize = 80;

    /// `CloudPools.OUTPUT`.
    pub fn is_output_id(id: &str) -> bool {
        Self::OUTPUT_KINDS.iter().filter_map(|kind| id.strip_prefix(kind)).any(|rest| {
            (1..=Self::OUTPUT_LETTERS_MAX).contains(&rest.len())
                && rest.bytes().all(|letter| letter.is_ascii_alphanumeric() || matches!(letter, b'.' | b'_' | b':' | b'-'))
        })
    }

    /// The row `raw` says, or `None` without an id. A row manual-only before the hand pick was dropped reads as switched off: what
    /// the order did with it before. Half of an account and model names nothing it could serve from, and reads as open.
    pub fn read(raw: &Value) -> Option<Self> {
        raw.as_object()?;
        let id = Coerce::stripped(raw.get("id"));
        if id.is_empty() {
            return None;
        }
        let on = |field: &str| raw.get(field).is_none_or(|flag| Coerce::truthy(Some(flag)));
        let (account, model) = (Coerce::stripped(raw.get("accountId")), Coerce::stripped(raw.get("model")));
        let output = Coerce::stripped(raw.get("output"));
        let work = if !account.is_empty() && !model.is_empty() {
            RowWork::Account { account, model }
        } else if Self::is_output_id(&output) {
            RowWork::Output(output)
        } else {
            RowWork::Open
        };
        Some(Self { id, work, enabled: on("enabled") && on("automatic") })
    }
}

/// A pool of the cloud file, or the pool of one row a model called without one stands for.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Pool {
    /// Its id.
    pub id: String,
    /// What a client calls it.
    pub name: String,
    /// Its rows, in the order they are tried.
    pub rows: Vec<PoolRow>,
    context_auto: bool,
    context_length: Option<i64>,
}

impl Pool {
    /// The pool of one row of a model called without a pool: its window is what the row says.
    pub fn of_one_row(id: String, name: String, work: RowWork) -> Self {
        let row = PoolRow { id: "r1".to_string(), work, enabled: true };
        Self { id, name, rows: vec![row], context_auto: true, context_length: None }
    }

    /// One pool as the file holds it, for a reader of one.
    pub fn read_one(raw: &Value) -> Option<Self> {
        Self::read(raw)
    }

    /// The pool `raw` says, or `None` without an id; steps that cannot be routed to drop out, and so does a second step under an id
    /// already taken. An id is a word, or a whole number written as one.
    fn read(raw: &Value) -> Option<Self> {
        raw.as_object()?;
        let id = Coerce::word(raw.get("id"));
        if id.is_empty() {
            return None;
        }
        let mut rows: Vec<PoolRow> = Vec::new();
        for row in raw.get("steps").and_then(Value::as_array).into_iter().flatten().filter_map(PoolRow::read) {
            if !rows.iter().any(|kept| kept.id == row.id) {
                rows.push(row);
            }
        }
        let said = Coerce::text(raw.get("name"));
        let name = Coerce::strip(&said);
        Some(Self {
            name: if name.is_empty() { id.clone() } else { name.to_string() },
            id,
            rows,
            context_auto: Coerce::truthy(raw.get("contextAuto")),
            context_length: Coerce::positive(raw.get("contextLength")),
        })
    }

    /// The window it stands for: the operator's figure, or, when they ticked "use the providers' figure", the smallest window any
    /// enabled row names, and none when one of them names none. `named` says a row's window.
    pub fn window(&self, named: impl Fn(&PoolRow) -> Option<i64>) -> Option<i64> {
        let reported = if self.context_auto {
            let rows = self.rows.iter().filter(|row| row.enabled && row.work != RowWork::Open);
            let named: Option<Vec<i64>> = rows.map(named).collect();
            named.and_then(|named| named.into_iter().min())
        } else {
            None
        };
        ContextWindow::of_pool(self.context_length, reported, self.context_auto)
    }
}

/// The pools of one reading of the file, in its order.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct CloudPools {
    pools: Vec<Pool>,
    /// A file of the old form, or a shape that does not read.
    unsure: bool,
}

impl CloudPools {
    /// The reading of the cloud file. A pool of an id already there takes its place, as a second key of a Python `dict` does.
    pub fn read(cloud: &Value) -> Self {
        let pools = cloud.get("pools").and_then(Value::as_array).map_or(&[][..], Vec::as_slice);
        let mut read = Self {
            pools: Vec::new(),
            unsure: Coerce::truthy(cloud.get("blocks")) || pools.iter().any(|pool| pool.get("members").is_some()),
        };
        for raw in pools {
            read.unsure = read.unsure || Self::odd(raw);
            let Some(pool) = Pool::read(raw) else {
                continue;
            };
            match read.pools.iter_mut().find(|kept| kept.id == pool.id) {
                Some(kept) => *kept = pool,
                None => read.pools.push(pool),
            }
        }
        read
    }

    /// A list for a name, or steps that are no list.
    fn odd(raw: &Value) -> bool {
        let steps = raw.get("steps").filter(|steps| Coerce::truthy(Some(*steps)));
        matches!(raw.get("name"), Some(Value::Array(_) | Value::Object(_))) || steps.is_some_and(|steps| !steps.is_array())
    }

    /// Whether the reading has something it cannot answer for.
    pub fn unsure(&self) -> bool {
        self.unsure
    }

    /// The pools.
    pub fn all(&self) -> &[Pool] {
        &self.pools
    }
}

/// The rules of how large a request may be, the ones a client's limit and a pool's rows meet in.
pub struct ContextWindow;

impl ContextWindow {
    /// The window a port advertises: the smaller of the operator's limit and the model's size, or the one that is known, or none. A
    /// guessed window is worse than none. `prefer_model` publishes the model's own size whenever it is known, even above the limit.
    pub fn effective(limit: Option<i64>, model: Option<i64>, prefer_model: bool) -> Option<i64> {
        if prefer_model && model.is_some() {
            return model;
        }
        match (limit, model) {
            (Some(limit), Some(model)) => Some(limit.min(model)),
            (limit, model) => limit.or(model),
        }
    }

    /// The window a pool stands for: the declared figure is the rule, the reported one is used only when the operator ticked it.
    fn of_pool(declared: Option<i64>, reported: Option<i64>, prefer_reported: bool) -> Option<i64> {
        if prefer_reported && reported.is_some() { reported } else { declared }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn row(raw: Value) -> Option<PoolRow> {
        PoolRow::read(&raw)
    }

    #[test]
    fn one_pool_of_the_file_reads_as_all_of_them_do() {
        let pool =
            Pool::read_one(&json!({"id": "p1", "name": "Fast", "steps": [{"id": "r", "accountId": "x", "model": "m"}]})).unwrap();
        assert_eq!((pool.id.as_str(), pool.name.as_str(), pool.rows.len()), ("p1", "Fast", 1));
        assert!(Pool::read_one(&json!({"name": "no id"})).is_none());
    }

    #[test]
    fn a_row_says_what_it_names() {
        let account = row(json!({"id": "a", "accountId": " x ", "model": " m "})).unwrap();
        assert_eq!(account.work, RowWork::Account { account: "x".to_string(), model: "m".to_string() });
        assert_eq!(row(json!({"id": "a", "output": "mm:x.y_z:1-2"})).unwrap().work, RowWork::Output("mm:x.y_z:1-2".to_string()));
        for open in [
            json!({"id": "a"}),
            json!({"id": "a", "accountId": "x"}),
            json!({"id": "a", "model": "m"}),
            json!({"id": "a", "output": "mm:"}),
            json!({"id": "a", "output": "mm:a b"}),
            json!({"id": "a", "output": "other:x"}),
            json!({"id": "a", "output": format!("mm:{}", "x".repeat(81))}),
        ] {
            assert_eq!(row(open.clone()).unwrap().work, RowWork::Open, "{open}");
        }
        assert_eq!(
            row(json!({"id": "a", "output": format!("srv:{}", "x".repeat(80))})).unwrap().work.clone(),
            RowWork::Output(format!("srv:{}", "x".repeat(80)))
        );
        assert!(row(json!({"accountId": "x", "model": "m"})).is_none());
        assert!(row(json!("a")).is_none());
    }

    #[test]
    fn a_row_is_on_unless_something_says_otherwise() {
        assert!(row(json!({"id": "a"})).unwrap().enabled);
        assert!(!row(json!({"id": "a", "enabled": false})).unwrap().enabled);
        assert!(!row(json!({"id": "a", "enabled": null})).unwrap().enabled);
        assert!(!row(json!({"id": "a", "automatic": false})).unwrap().enabled);
        assert!(row(json!({"id": "a", "enabled": 1, "automatic": "yes"})).unwrap().enabled);
    }

    #[test]
    fn a_shape_it_cannot_answer_for_is_a_doubt() {
        let of = |pools: Value| CloudPools::read(&json!({"pools": pools})).unsure();
        assert!(!of(json!([{"id": "p", "steps": [], "name": "n"}, {"id": "q"}, "row"])));
        assert!(of(json!([{"id": "p", "members": []}])));
        assert!(of(json!([{"id": "p", "name": ["n"]}])));
        assert!(of(json!([{"id": "p", "name": {"a": 1}}])));
        assert!(of(json!([{"id": "p", "steps": "text"}])));
        assert!(of(json!([{"id": "p", "steps": {"a": 1}}])));
        assert!(!of(json!([{"id": "p", "steps": null}])));
        assert!(CloudPools::read(&json!({"blocks": [{"id": "b"}]})).unsure());
        assert!(!CloudPools::read(&json!({"blocks": []})).unsure());
    }

    #[test]
    fn a_second_pool_of_one_id_takes_the_first_one_s_place() {
        let pools = CloudPools::read(&json!({"pools": [{"id": "a", "name": "one"}, {"id": "b"}, {"id": "a", "name": "two"}]}));
        let names: Vec<(&str, &str)> = pools.all().iter().map(|pool| (pool.id.as_str(), pool.name.as_str())).collect();
        assert_eq!(names, [("a", "two"), ("b", "b")]);
    }

    #[test]
    fn the_smallest_row_is_the_pool_s_window_only_when_every_row_names_one() {
        let pool = |rows: Value, extra: Value| {
            let mut raw = json!({"id": "p", "steps": rows});
            raw.as_object_mut().unwrap().extend(extra.as_object().unwrap().clone());
            Pool::read(&raw).unwrap()
        };
        let named = |row: &PoolRow| match row.id.as_str() {
            "a" => Some(100),
            "b" => Some(50),
            _ => None,
        };
        let two = json!([{"id": "a", "accountId": "x", "model": "m"}, {"id": "b", "accountId": "x", "model": "n"}]);
        assert_eq!(pool(two.clone(), json!({"contextAuto": true})).window(named), Some(50));
        assert_eq!(pool(two.clone(), json!({"contextAuto": true, "contextLength": 7})).window(named), Some(50));
        assert_eq!(pool(two.clone(), json!({"contextLength": 7})).window(named), Some(7));
        assert_eq!(pool(two, json!({})).window(named), None);
        let silent = json!([{"id": "a", "accountId": "x", "model": "m"}, {"id": "c", "accountId": "x", "model": "n"}]);
        assert_eq!(pool(silent.clone(), json!({"contextAuto": true})).window(named), None);
        assert_eq!(pool(silent, json!({"contextAuto": true, "contextLength": 7})).window(named), Some(7));
        let quiet = json!([{"id": "a", "accountId": "x", "model": "m"}, {"id": "c", "accountId": "x", "model": "n", "enabled": false}, {"id": "d"}]);
        assert_eq!(pool(quiet, json!({"contextAuto": true})).window(named), Some(100));
        assert_eq!(pool(json!([]), json!({"contextAuto": true, "contextLength": 7})).window(named), Some(7));
    }

    #[test]
    fn a_client_s_limit_and_a_model_s_size_meet_at_the_smaller() {
        for (limit, model, prefer, want) in [
            (Some(10), Some(20), false, Some(10)),
            (Some(20), Some(10), false, Some(10)),
            (Some(10), Some(20), true, Some(20)),
            (Some(20), Some(10), true, Some(10)),
            (Some(10), None, true, Some(10)),
            (Some(10), None, false, Some(10)),
            (None, Some(10), false, Some(10)),
            (None, None, true, None),
            (None, None, false, None),
        ] {
            assert_eq!(ContextWindow::effective(limit, model, prefer), want, "{limit:?} {model:?} {prefer}");
        }
    }
}
