//! Why one row of a pool is fit or not now: `_candidate`, `_local_candidate` and `_reading` of `PoolSteps`.

use super::{PoolQuestion, PoolSteps};
use files::Settings;
use rules::{
    Carried, CloudProvider, Coerce, MachineOutput, PoolRow, Reader, RequestKind, ResponsesPassthrough, RowKind, RowWork,
    UsageReserve, UsageWindow, Verdict, Wired,
};
use serde_json::{Map, Value, json};

/// Why one row is fit or not now, as one row of the pool's state.
pub(super) struct RowState {
    pub(super) step_id: String,
    pub(super) eligible: bool,
    pub(super) reason: &'static str,
    pub(super) said: Map<String, Value>,
    /// What is said of a row once its reason is known. The order of a row's fields is Python's: a refusal's JSON goes to the journal as text.
    after_reason: Map<String, Value>,
    pub(super) target: Option<MachineOutput>,
    pub(super) provider: Option<CloudProvider>,
    /// The row cannot read the request's pictures, and the board's reader reads them for it (`Sight::ReadFirst`).
    pub(super) read_first: bool,
}

impl RowState {
    fn of(step: &PoolRow, mut said: Map<String, Value>) -> Self {
        said.insert("eligible".to_string(), json!(false));
        Self {
            step_id: step.id.clone(),
            eligible: false,
            reason: "",
            said,
            after_reason: Map::new(),
            target: None,
            provider: None,
            read_first: false,
        }
    }

    pub(super) fn as_json(&self) -> Value {
        let mut out = self.said.clone();
        out.insert("eligible".to_string(), json!(self.eligible));
        out.insert("reason".to_string(), json!(self.reason));
        out.extend(self.after_reason.clone());
        Value::Object(out)
    }

    fn fit(mut self, reason: &'static str) -> Self {
        self.eligible = true;
        self.reason = reason;
        self
    }

    fn unfit(mut self, reason: &'static str) -> Self {
        self.eligible = false;
        self.reason = reason;
        self
    }

    fn with(mut self, field: &str, value: Value) -> Self {
        self.said.insert(field.to_string(), value);
        self
    }

    fn then(mut self, field: &str, value: Value) -> Self {
        self.after_reason.insert(field.to_string(), value);
        self
    }

    /// The row marked to have the request's pictures read for it first — said in the pool's state too, so the board can tell
    /// a row that reads from a row that is read for.
    fn read_for(self) -> Self {
        let mut row = self.then("readFirst", json!(true));
        row.read_first = true;
        row
    }
}

/// What one row is to the pictures a request carries.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Sight {
    /// It reads them, or the request has none, or the row says nothing of its inputs: the request goes to it as it came.
    Sees,
    /// It said it cannot read them, and the board's reader reads them for it first.
    ReadFirst,
    /// It said it cannot read them, and nothing reads for it: no candidate for this request, for this reason.
    Blind(&'static str),
}

/// What kind of request a row is judged for.
#[derive(Debug, Clone, Copy)]
struct AskedWork {
    /// A client that speaks the Responses API.
    responses: bool,
    /// A chat's path: a subscription does nothing else.
    chat: bool,
}

/// What a request asks of every row: the kind of work its path names, and what its body carries. One argument,
/// because both are read for each row and passing them apart is how a row came to be judged by only one of them.
struct Asked<'a> {
    work: AskedWork,
    carried: &'a Carried,
}

impl PoolSteps {
    const FRESH_SEC: f64 = 300.0;
    const FAILED_REFRESH_SEC: f64 = 30.0;
    /// The providers a Responses request may go to as it is: the subscription speaks it, and so does api.openai.com. The rest take chat requests only.
    const RESPONSES_TYPES: [&'static str; 1] = ["openai"];

    /// When a row's model opens, while its schedule closes it: `None` while it may serve. A closed model is not asked at all: no connection is
    /// tried, no account spent.
    fn closed_until(&self, settings: &Settings, key: &str, now: f64) -> Option<Option<i64>> {
        settings.models.schedules().closed(key, now, self.zone.as_ref())
    }

    fn output_row(&self, ask: &PoolQuestion<'_>, step: &PoolRow, output: &str, now: f64, asked: &Asked<'_>) -> RowState {
        let mut said = Map::new();
        said.insert("stepId".to_string(), json!(step.id));
        said.insert("kind".to_string(), json!("output"));
        said.insert("output".to_string(), json!(output));
        let row = RowState::of(step, said);
        if !step.enabled {
            return row.unfit("disabled");
        }
        if let Some(opens_at) = self.closed_until(ask.settings, &format!("out:{output}"), now) {
            return row.then("opensAt", json!(opens_at)).unfit("closed");
        }
        if ask.excluded.contains(&format!("row:{}", step.id)) {
            return row.unfit("tried");
        }
        let Some(machine) = ask.settings.models.output(output).and_then(|found| found.machine.clone()) else {
            return row.unfit("output_missing");
        };
        if machine.stopped {
            return row.unfit("stopped");
        }
        if self.health.is_dead(output, now) {
            return row.unfit("unavailable");
        }
        let mut row = match self.sight(ask, step, asked.carried) {
            Sight::Blind(reason) => return row.unfit(reason),
            Sight::ReadFirst => row.read_for(),
            Sight::Sees => row,
        };
        let free = (ask.free)(&machine);
        row.target = Some(machine);
        row.fit(if free { "ready" } else { "busy" })
    }

    /// A reset seen for the first time: an account's refusal for its quota and its last try at the page are over.
    fn note_reset(&self, owner: &str, reset_at: f64) {
        let mut memory = self.memory();
        // absent-ok: no reset seen yet is the start of time.
        if reset_at <= memory.resets_seen.get(owner).copied().unwrap_or(0.0) {
            return;
        }
        memory.resets_seen.insert(owner.to_string(), reset_at);
        if memory.blocked.get(owner).is_some_and(|blocked| blocked.reason == "quota" && blocked.at <= reset_at) {
            memory.blocked.remove(owner);
        }
        // absent-ok: never tried is older than any reset.
        if memory.tried.get(owner).copied().unwrap_or(0.0) < reset_at {
            memory.tried.remove(owner);
        }
    }

    fn account_row(
        &self,
        ask: &PoolQuestion<'_>,
        step: &PoolRow,
        account: &str,
        model: &str,
        asked: &Asked<'_>,
        now: f64,
    ) -> RowState {
        let mut said = Map::new();
        said.insert("stepId".to_string(), json!(step.id));
        said.insert("kind".to_string(), json!("account"));
        said.insert("accountId".to_string(), json!(account));
        said.insert("model".to_string(), json!(model));
        let row = RowState::of(step, said);
        if !step.enabled {
            return row.unfit("disabled");
        }
        if let Some(opens_at) = self.closed_until(ask.settings, &format!("acc:{account}/{model}"), now) {
            return row.then("opensAt", json!(opens_at)).unfit("closed");
        }
        if ask.excluded.contains(&format!("row:{}", step.id)) {
            return row.unfit("tried");
        }
        let models = &ask.settings.models;
        let Some(provider) = models.provider(account).filter(|provider| models.has_credential(&provider.credential_account_id))
        else {
            return row.unfit("credential_missing");
        };
        if (asked.work.responses && !provider.subscription && !Self::RESPONSES_TYPES.contains(&provider.kind.as_str()))
            || (provider.subscription && !asked.work.chat)
        {
            return row.unfit("format_unsupported");
        }
        let owner = provider.usage_account_id.clone();
        let row = row.with("usageAccountId", json!(owner));
        // absent-ok: an account never reset has a reset of 0.
        let reset_at = ask.settings.resets.get(&owner).copied().unwrap_or(0.0);
        self.note_reset(&owner, reset_at);
        if ask.excluded.contains(&owner) {
            return row.unfit("upstream_refused");
        }
        if let Some(blocked) = self.memory().blocked.get(&owner).filter(|blocked| blocked.until > now) {
            return row.then("resetAt", json!(blocked.until)).unfit(blocked.reason);
        }
        if models.catalogue().lists(&provider.credential_account_id, model) == Some(false) {
            return row.unfit("model_unavailable");
        }
        let row = match self.sight(ask, step, asked.carried) {
            Sight::Blind(reason) => return row.unfit(reason),
            Sight::ReadFirst => row.read_for(),
            Sight::Sees => row,
        };
        self.by_account(ask, row, provider, model, reset_at, now)
    }

    /// A row that may serve, by what its account is: a subscription by its windows, a key ready now.
    fn by_account(
        &self,
        ask: &PoolQuestion<'_>,
        row: RowState,
        provider: CloudProvider,
        model: &str,
        reset_at: f64,
        now: f64,
    ) -> RowState {
        let mut row = if provider.subscription {
            self.subscription_row(ask, row, &provider, model, reset_at, now)
        } else {
            row.fit("ready")
        };
        row.provider = Some(provider);
        row
    }

    fn subscription_row(
        &self,
        ask: &PoolQuestion<'_>,
        row: RowState,
        provider: &CloudProvider,
        model: &str,
        reset_at: f64,
        now: f64,
    ) -> RowState {
        let (windows, at, known) = self.reading(ask.settings, provider, reset_at, now);
        let said: Vec<Value> = windows.iter().map(UsageWindow::as_json).collect();
        let row = row.with("windows", json!(said)).with("readAt", json!(at));
        if !known {
            return row.unfit("usage_unknown");
        }
        let (stop, switch) = ask.settings.models.levels().of(&provider.account_id, model);
        if windows.iter().any(|window| window.reset_at.is_none() && (stop.names(window.seconds) || switch.names(window.seconds)))
        {
            return row.unfit("usage_unknown");
        }
        if let Some(hit) = stop.verdict(&windows, now) {
            return row.then("reserve", hit.as_json()).then("resetAt", json!(hit.reset_at)).unfit("reserve");
        }
        let exhausted: Vec<&UsageWindow> = windows.iter().filter(|window| window.used_pct >= 100).collect();
        if !exhausted.is_empty() {
            let soonest = exhausted.iter().map(|window| window.reset_at.map_or(now + 30.0, |at| at as f64)).reduce(f64::max);
            return row.then("resetAt", json!(soonest)).unfit("quota");
        }
        self.switch_row(row, &switch, &windows, now)
    }

    fn switch_row(&self, row: RowState, switch: &UsageReserve, windows: &[UsageWindow], now: f64) -> RowState {
        match switch.verdict(windows, now) {
            // Fit, but giving way: served only when no row above its own switch level is fit.
            Some(hit) => row.then("reserve", hit.as_json()).then("resetAt", json!(hit.reset_at)).fit("switch"),
            None => row.fit("ready"),
        }
    }

    /// (windows, when they were read, whether they can be read at all): the last reading while it is fresh, or the account's usage page: a
    /// row held at its switch level gets no traffic, so no answer brings a new reading, and a reset that came early would stay unseen until
    /// the old reset time.
    fn reading(
        &self,
        settings: &Settings,
        provider: &CloudProvider,
        reset_at: f64,
        now: f64,
    ) -> (Vec<UsageWindow>, Option<f64>, bool) {
        let owner = &provider.usage_account_id;
        let (windows, at) = self.usage.reading(owner);
        let expired = windows.iter().any(|window| window.reset_at.is_some_and(|at| at as f64 <= now));
        if at.is_some_and(|at| at >= reset_at && now - at < Self::FRESH_SEC) && !expired {
            return (windows, at, true);
        }
        if let Some(seen) =
            self.memory().unlimited.get(owner).copied().filter(|seen| *seen >= reset_at && now - seen < Self::FRESH_SEC)
        {
            return (Vec::new(), Some(seen), true);
        }
        let due = {
            let mut memory = self.memory();
            let due = memory.tried.get(owner).is_none_or(|tried| now - tried >= Self::FAILED_REFRESH_SEC);
            if due {
                memory.tried.insert(owner.clone(), now);
            }
            due
        };
        if due && let Some(page) = self.pages.page(settings, provider) {
            let fresh = UsageWindow::from_usage_page(&page);
            if !fresh.is_empty() {
                self.usage.keep(owner, fresh.clone(), now);
                return (fresh, Some(now), true);
            }
            if Self::says_no_limits(&page) {
                self.memory().unlimited.insert(owner.clone(), now);
                return (Vec::new(), Some(now), true);
            }
        }
        (windows, at, false)
    }

    fn says_no_limits(page: &Value) -> bool {
        let Some(rate) = page.get("rate_limit").filter(|rate| rate.is_object()) else {
            return false;
        };
        rate.get("allowed") == Some(&Value::Bool(true))
            && !Coerce::truthy(rate.get("limit_reached"))
            && ["primary_window", "secondary_window"].iter().all(|slot| rate.get(*slot).is_none_or(Value::is_null))
    }

    /// What this row is to the pictures the request carries. Only a picture is asked, because this rule decides images: audio
    /// keeps its own rule. A row that says nothing of its inputs is no refusal — the absence of a promise is not a promise
    /// that it cannot read.
    ///
    /// Whether the row can take the picture is asked with `Wired::Nothing`: the question is the row's own promise, not the
    /// wiring's. What reads for a row that cannot was decided by the entry, which asked the board's wiring through
    /// `EntryModels::wired` — the only place that fills a promise — and said it as `reads`. A row that reads the picture
    /// itself is never given a caption.
    fn sight(&self, ask: &PoolQuestion<'_>, step: &PoolRow, carried: &Carried) -> Sight {
        if carried.count("image") == 0 {
            return Sight::Sees;
        }
        match ask.settings.models.row_kind(step) {
            RowKind::Said(kind)
                if matches!(carried.verdict(kind.takes(), &Wired::Nothing), Verdict::Reading(_, Reader::Nothing)) =>
            {
                if ask.reads { Sight::ReadFirst } else { Sight::Blind("media_unsupported") }
            }
            _ => Sight::Sees,
        }
    }

    pub(super) fn rows(&self, ask: &PoolQuestion<'_>, now: f64) -> Vec<RowState> {
        let carried = Carried::of_body(ask.body);
        let asked = Asked {
            work: AskedWork {
                responses: (!ask.path.is_empty() || !ask.body.is_empty()) && ResponsesPassthrough::is_request(ask.path, ask.body),
                chat: ask.path.is_empty() || RequestKind::is_chat(ask.path),
            },
            carried: &carried,
        };
        ask.pool
            .rows
            .iter()
            .map(|step| match &step.work {
                RowWork::Open => {
                    let mut said = Map::new();
                    said.insert("stepId".to_string(), json!(step.id));
                    said.insert("kind".to_string(), json!("open"));
                    RowState::of(step, said).unfit("not_connected")
                }
                RowWork::Output(output) => self.output_row(ask, step, output, now, &asked),
                RowWork::Account { account, model } => self.account_row(ask, step, account, model, &asked, now),
            })
            .collect()
    }
}
