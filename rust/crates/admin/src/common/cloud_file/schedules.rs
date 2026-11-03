//! When a model is open: its weekly windows, under a key that names it.

use super::*;

/// When a model is open: the windows of one schedule, read and refused.
pub struct WeekWindows;

impl WeekWindows {
    pub(super) const MAX: usize = 168;

    pub(super) fn days(raw: Option<&Value>, place: &str) -> Result<Vec<i64>, AppError> {
        let Some(raw) = raw.filter(|raw| !raw.is_null()) else {
            return Ok(Vec::new());
        };
        let Some(list) = raw.as_array() else {
            return Err(AppError::new(format!("{place}: days must be a list of 0..6 (Monday is 0)")));
        };
        let mut days = BTreeSet::new();
        for day in list {
            let Some(number) = day.as_i64().filter(|number| (0..=6).contains(number)) else {
                return Err(AppError::new(format!(
                    "{place}: days must be numbers 0..6 (Monday is 0), got {}",
                    PyRepr::of_value(day)
                )));
            };
            days.insert(number);
        }
        Ok(if days.len() == 7 { Vec::new() } else { days.into_iter().collect() })
    }

    pub(super) fn window(raw: &Value, place: &str) -> Result<Value, AppError> {
        if !raw.is_object() {
            return Err(AppError::new(format!("{place} must be an object: {{days, from, to}}")));
        }
        let mut times = Vec::new();
        for name in ["from", "to"] {
            let value = Word::of(raw.get(name));
            if value.is_empty() {
                return Err(AppError::new(format!("{place}: `{name}` is required, as HH:MM")));
            }
            times.push(Daytime::of_text(&value).map_err(|error| AppError::new(format!("{place}: {}", error.message)))?);
        }
        Ok(json!({"days": Self::days(raw.get("days"), place)?, "from": times.first(), "to": times.get(1)}))
    }

    /// The windows the operator sent, or a refusal that says what is wrong with which one.
    pub fn parse(raw: Option<&Value>) -> Result<Vec<Value>, AppError> {
        let Some(raw) = raw.filter(|raw| !raw.is_null()) else {
            return Ok(Vec::new());
        };
        let Some(list) = raw.as_array() else {
            return Err(AppError::new("windows must be a list"));
        };
        if list.len() > Self::MAX {
            return Err(AppError::new(format!("a schedule holds at most {} windows", Self::MAX)));
        }
        let mut out = Vec::new();
        for (index, item) in list.iter().enumerate() {
            let window = Self::window(item, &format!("window {}", index + 1))?;
            if !out.contains(&window) {
                out.push(window);
            }
        }
        Ok(out)
    }

    /// The windows as a reader takes them from the file: each one that reads.
    pub fn clean(raw: Option<&Value>) -> Vec<Value> {
        let mut out = Vec::new();
        for (index, item) in raw.and_then(Value::as_array).into_iter().flatten().enumerate() {
            if let Ok(window) = Self::window(item, &format!("window {}", index + 1))
                && !out.contains(&window)
            {
                out.push(window);
            }
        }
        out.truncate(Self::MAX);
        out
    }
}

/// The one name a model has wherever the caravan keeps something of it: the key Routing draws its right column with.
pub struct ModelKey;

impl ModelKey {
    pub(super) const ACCOUNT: &'static str = "acc:";
    /// What a local output's key starts with.
    pub const OUTPUT: &'static str = "out:";

    /// The key of an account's model; "" when it names none.
    pub fn account(account_id: &str, model: &str) -> String {
        let (account, model) = (Coerce::strip(account_id), Coerce::strip(model));
        if !account.is_empty() && !model.is_empty() && !account.contains('/') {
            format!("{}{account}/{model}", Self::ACCOUNT)
        } else {
            String::new()
        }
    }

    /// The key of a local output; "" when it names none.
    pub fn output(output_id: &str) -> String {
        let output = Coerce::strip(output_id);
        if PoolRow::is_output_id(output) { format!("{}{output}", Self::OUTPUT) } else { String::new() }
    }

    /// The key of the model a pool's row is cabled to.
    pub fn of_row(row: &Value) -> String {
        match row.get("kind").and_then(Value::as_str).unwrap_or("account") {
            "output" => Self::output(&Word::of(row.get("output"))),
            "account" => Self::account(&Word::of(row.get("accountId")), &Word::of(row.get("model"))),
            _ => String::new(),
        }
    }

    /// Whether a key reads as one: ("account", id, model) or ("output", id, "").
    pub fn parse(key: &str) -> Option<(&'static str, String, String)> {
        if let Some(rest) = key.strip_prefix(Self::ACCOUNT) {
            let (account, model) = rest.split_once('/').unwrap_or((rest, ""));
            return (Self::account(account, model) == key).then(|| ("account", account.to_string(), model.to_string()));
        }
        if let Some(output) = key.strip_prefix(Self::OUTPUT) {
            return (Self::output(output) == key).then(|| ("output", output.to_string(), String::new()));
        }
        None
    }
}

/// The schedules of the models of one reading of the file.
#[derive(Debug, Default)]
pub struct ModelSchedules {
    pub(super) kept: BTreeMap<String, Value>,
}

impl ModelSchedules {
    /// One reading of the file.
    pub fn new(data: &Value) -> Self {
        let mut kept = BTreeMap::new();
        for (key, entry) in data.get("schedules").and_then(Value::as_object).into_iter().flatten() {
            if ModelKey::parse(key).is_some() && entry.is_object() {
                kept.insert(key.clone(), json!({"enabled": entry.get("enabled") == Some(&json!(true)), "windows": WeekWindows::clean(entry.get("windows"))}));
            }
        }
        Self { kept }
    }

    /// The model's schedule as kept.
    pub fn of(&self, key: &str) -> Option<&Value> {
        self.kept.get(key)
    }

    /// Keeps one.
    pub fn put(&mut self, key: &str, enabled: bool, windows: Option<&Value>) -> Value {
        let entry = json!({"enabled": enabled, "windows": WeekWindows::clean(windows)});
        self.kept.insert(key.to_string(), entry.clone());
        entry
    }

    /// Forgets one; true when it was there.
    pub fn forget(&mut self, key: &str) -> bool {
        self.kept.remove(key).is_some()
    }

    /// Forgets an account's.
    pub fn forget_account(&mut self, account_id: &str) {
        let prefix = format!("{}{}/", ModelKey::ACCOUNT, Coerce::strip(account_id));
        self.kept.retain(|key, _| !key.starts_with(&prefix));
    }

    /// A cell moved to another port takes its schedule along.
    pub fn follow(&mut self, old_output: &str, new_output: &str) -> bool {
        let (old, new) = (ModelKey::output(old_output), ModelKey::output(new_output));
        if old.is_empty() || new.is_empty() {
            return false;
        }
        let Some(entry) = self.kept.remove(&old) else {
            return false;
        };
        self.kept.insert(new, entry);
        true
    }

    /// Two cells that swapped ports swap their schedules.
    pub fn swap(&mut self, output_a: &str, output_b: &str) -> bool {
        let (a, b) = (ModelKey::output(output_a), ModelKey::output(output_b));
        if a.is_empty() || b.is_empty() || !(self.kept.contains_key(&a) || self.kept.contains_key(&b)) {
            return false;
        }
        let (held_a, held_b) = (self.kept.remove(&a), self.kept.remove(&b));
        if let Some(entry) = held_a {
            self.kept.insert(b, entry);
        }
        if let Some(entry) = held_b {
            self.kept.insert(a, entry);
        }
        true
    }

    /// The model's schedule and what it says at `now`.
    pub fn state(&self, key: &str, now: f64, clock: &dyn rules::WallClock) -> Option<Value> {
        let entry = self.of(key)?;
        let (open, opens_at, until) = if entry.get("enabled") == Some(&json!(true)) {
            let week = rules::WeekWindows::clean(entry.get("windows"));
            let said = week.state(now, clock);
            (said.open, said.opens_at, week.open_until(now, clock))
        } else {
            (true, None, None)
        };
        // absent-ok: an entry is an object: it was kept only as one
        let mut out = Coerce::fields(entry);
        out.insert("open".to_string(), json!(open));
        out.insert("until".to_string(), json!(until));
        out.insert("opensAt".to_string(), json!(opens_at));
        Some(Value::Object(out))
    }

    /// The shape the file keeps under `schedules`.
    pub fn stored(&self) -> Value {
        json!(self.kept)
    }
}
