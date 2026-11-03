//! The pool's choice by values: every reason a row is unfit, what a refusal rests and for how long, and when the usage page is asked. Each
//! stands alone, on a clock in the test's hand.

use super::*;
use crate::clock::Clock;
use rules::{CloudPools, Credentials, ModelCatalogue};
use std::sync::atomic::{AtomicUsize, Ordering};

const NOW: f64 = 1_000_000.0;
const CHAT: &str = "/v1/chat/completions";

#[derive(Default)]
struct HandClock(Mutex<f64>);

impl HandClock {
    fn set(&self, at: f64) {
        *self.0.lock().unwrap() = at;
    }
}

impl Clock for HandClock {
    fn epoch(&self) -> f64 {
        *self.0.lock().unwrap()
    }
    fn monotonic(&self) -> f64 {
        self.epoch()
    }
    fn thread_cpu(&self) -> Option<f64> {
        None
    }
}

struct UtcZone;

impl WallClock for UtcZone {
    fn minute_of_week(&self, epoch: f64) -> i64 {
        (epoch as i64 / 60 + 3 * 24 * 60).rem_euclid(7 * 24 * 60)
    }
    fn epoch_of_week_minute(&self, epoch: f64, minute: i64) -> i64 {
        epoch as i64 / 60 / (7 * 24 * 60) * (7 * 24 * 60) * 60 + (minute - 3 * 24 * 60) * 60
    }
    fn text(&self, epoch: i64) -> String {
        format!("at {epoch}")
    }
}

/// The usage page, with what it says now and how many times it was asked.
#[derive(Default)]
struct Page {
    says: Mutex<Option<Value>>,
    asked: AtomicUsize,
}

struct SharedPage(Arc<Page>);

impl UsagePages for SharedPage {
    fn page(&self, _settings: &Settings, _provider: &CloudProvider) -> Option<Value> {
        self.0.asked.fetch_add(1, Ordering::SeqCst);
        self.0.says.lock().unwrap().clone()
    }
}

fn account(id: &str, kind: &str) -> Value {
    json!({"id": id, "name": id, "type": kind, "accountType": kind, "baseUrl": "http://provider/v1", "authMode": "apiKey"})
}

fn on_machine(id: &str, model: &str) -> Value {
    json!({"id": id, "output": format!("mm:{model}")})
}

fn on_account(id: &str, account: &str, model: &str) -> Value {
    json!({"id": id, "accountId": account, "model": model})
}

/// A pool of `rows`, the settings around it and the state of a process that has just started.
struct Stand {
    clock: Arc<HandClock>,
    page: Arc<Page>,
    steps: PoolSteps,
    settings: Settings,
    pool: Pool,
    /// The machine's models with no place free.
    busy: Vec<&'static str>,
}

impl Stand {
    fn new(rows: Value) -> Self {
        Self::with_policy(rows, json!({}))
    }

    fn with_policy(rows: Value, policy: Value) -> Self {
        let output = |name: &str, stopped: bool| {
            json!({"id": format!("mm:{name}"), "upstreamType": "machine", "upstreamModel": name, "name": name, "hostId": "box",
                   "upstreamHost": "box", "upstreamPort": 1, "jobs": ["llm"], "stopped": stopped})
        };
        let proxies = json!({"routes": [], "policy": policy, "routers": [{"id": "router:default",
            "outputs": [output("free", false), output("full", false), output("still", true)]}]});
        let cloud = json!({
            "accounts": [account("key", "custom"), account("other", "custom"), account("out", "custom"), account("listed", "custom"),
                         account("api", "openai"), account("sub", "openai-subscription")],
            "pools": [{"id": "p", "name": "the pool", "steps": rows}],
            "schedules": {"acc:key/closed": {"enabled": true, "windows": []}},
            "levels": {"sub": {"levelled": {"stopAt": {"18000": 5}, "switchAt": {"18000": 30}}, "plain": {"stopAt": {}, "switchAt": {}}}},
        });
        let key = json!({"apiKey": "a"});
        let credentials = Credentials::read(Some(&json!({
            "key": key, "other": key, "listed": key, "api": key,
            "sub": {"oauth": {"accessToken": "a", "refreshToken": "b", "expiresAt": 9_000_000_000_i64}},
        })));
        let catalogue = ModelCatalogue::read(Some(&json!({"accounts": {"listed": {"models": [{"id": "another"}]}}})));
        let settings = Settings::read(files::Documents {
            proxies: Some(&proxies),
            cloud: Some(&cloud),
            credentials,
            catalogue,
            resets: None,
        });
        let clock = Arc::new(HandClock::default());
        clock.set(NOW);
        let page = Arc::new(Page::default());
        let steps =
            PoolSteps::new(Arc::clone(&clock) as Arc<dyn Clock>, Arc::new(UtcZone), Box::new(SharedPage(Arc::clone(&page))));
        let pool = CloudPools::read(&cloud).all()[0].clone();
        Self { clock, page, steps, settings, pool, busy: Vec::new() }
    }

    fn resolve_on(&self, path: &str, body: &[u8], excluded: &[&str]) -> (RowChoice, Option<Value>) {
        let excluded: BTreeSet<String> = excluded.iter().map(|word| (*word).to_string()).collect();
        let free = |output: &MachineOutput| !self.busy.contains(&output.name.as_str());
        self.steps.resolve(&PoolQuestion {
            settings: &self.settings,
            pool: &self.pool,
            body,
            path,
            excluded: &excluded,
            free: &free,
        })
    }

    /// The row that serves a chat, or what the pool refused it with.
    fn served(&self, excluded: &[&str]) -> String {
        match self.resolve_on(CHAT, b"{}", excluded).0 {
            RowChoice::Machine(row) => row.row_id,
            RowChoice::Cloud(row) => row.row_id,
            RowChoice::Refused(refusal) => format!("refused {}", refusal.status),
        }
    }

    /// What the last choice said of its rows.
    fn rows_said(&self) -> Value {
        self.steps.snapshot()["pools"]["p"]["steps"].clone()
    }

    /// Why the first row is as it is, a chat being asked with `excluded` tried.
    fn first_reason(&self, excluded: &[&str]) -> String {
        self.served(excluded);
        self.rows_said()[0]["reason"].as_str().unwrap().to_string()
    }

    fn can_go_on(&self, ready: bool) -> bool {
        let excluded = BTreeSet::new();
        let free = |output: &MachineOutput| !self.busy.contains(&output.name.as_str());
        self.steps.can_go_on(
            &PoolQuestion {
                settings: &self.settings,
                pool: &self.pool,
                body: b"{}",
                path: CHAT,
                excluded: &excluded,
                free: &free,
            },
            ready,
        )
    }

    fn reads(&self, used_pct: i64, reset_at: Option<i64>) {
        self.steps.usage.keep("sub", vec![rules::UsageWindow { seconds: 18_000, used_pct, reset_at }], self.clock.epoch());
    }

    fn provider(&self, id: &str) -> CloudProvider {
        self.settings.models.provider(id).unwrap()
    }
}

#[test]
fn each_row_that_cannot_serve_says_why() {
    let cases: [(Value, &[&str], &str, &str); 12] = [
        (json!({"id": "r", "accountId": "key", "model": "m", "enabled": false}), &[], "disabled", "refused 429"),
        (on_account("r", "key", "closed"), &[], "closed", "refused 503"),
        (on_account("r", "key", "m"), &["row:r"], "tried", "refused 503"),
        (on_account("r", "out", "m"), &[], "credential_missing", "refused 503"),
        (on_account("r", "nobody", "m"), &[], "credential_missing", "refused 503"),
        (on_account("r", "key", "m"), &["key"], "upstream_refused", "refused 503"),
        (on_account("r", "listed", "m"), &[], "model_unavailable", "refused 503"),
        (json!({"id": "r"}), &[], "not_connected", "refused 503"),
        (on_machine("r", "nothing-here"), &[], "output_missing", "refused 503"),
        (on_machine("r", "still"), &[], "stopped", "refused 503"),
        (json!({"id": "r", "output": "mm:free", "enabled": false}), &[], "disabled", "refused 429"),
        (on_machine("r", "free"), &["row:r"], "tried", "refused 503"),
    ];
    for (row, excluded, reason, refused) in cases {
        let stand = Stand::new(json!([row]));
        assert_eq!(stand.first_reason(excluded), reason, "{row}");
        assert_eq!(stand.rows_said()[0]["eligible"], json!(false), "{row}");
        assert_eq!(stand.served(excluded), refused, "{row}");
    }
}

#[test]
fn a_row_that_can_serve_goes_with_what_it_needs() {
    let stand = Stand::new(json!([on_account("r", "key", "m")]));
    let RowChoice::Cloud(row) = stand.resolve_on(CHAT, b"{}", &[]).0 else { panic!("a provider's row") };
    assert_eq!((row.row_id.as_str(), row.model.as_str(), row.provider.account_id.as_str()), ("r", "m", "key"));
    assert_eq!(stand.rows_said()[0]["reason"], json!("ready"));
    assert_eq!(stand.rows_said()[0]["usageAccountId"], json!("key"));
    let stand = Stand::new(json!([on_machine("r", "free")]));
    let RowChoice::Machine(row) = stand.resolve_on(CHAT, b"{}", &[]).0 else { panic!("a machine's row") };
    assert_eq!((row.row_id.as_str(), row.output.name.as_str()), ("r", "free"));
}

#[test]
fn a_closed_row_says_when_it_opens_and_is_asked_nothing() {
    let stand = Stand::new(json!([on_account("r", "key", "closed")]));
    assert_eq!(stand.first_reason(&[]), "closed");
    assert!(stand.rows_said()[0].as_object().unwrap().contains_key("opensAt"));
    assert_eq!(stand.page.asked.load(Ordering::SeqCst), 0);
}

#[test]
fn a_request_goes_where_its_format_is_spoken() {
    let responses = "/v1/responses";
    let chat_only = Stand::new(json!([on_account("r", "key", "m")]));
    chat_only.resolve_on(responses, b"{}", &[]);
    assert_eq!(chat_only.rows_said()[0]["reason"], json!("format_unsupported"));
    let by_body = Stand::new(json!([on_account("r", "key", "m")]));
    by_body.resolve_on(CHAT, br#"{"input": []}"#, &[]);
    assert_eq!(by_body.rows_said()[0]["reason"], json!("format_unsupported"));
    let openai = Stand::new(json!([on_account("r", "api", "m")]));
    openai.resolve_on(responses, b"{}", &[]);
    assert_eq!(openai.rows_said()[0]["reason"], json!("ready"));
    let subscription = Stand::new(json!([on_account("r", "sub", "m")]));
    subscription.resolve_on("/v1/embeddings", b"{}", &[]);
    assert_eq!(subscription.rows_said()[0]["reason"], json!("format_unsupported"));
    assert_eq!(subscription.page.asked.load(Ordering::SeqCst), 0, "a row that cannot serve spends no question");
    let on_a_machine = Stand::new(json!([on_machine("r", "free")]));
    on_a_machine.resolve_on(responses, b"{}", &[]);
    assert_eq!(on_a_machine.rows_said()[0]["reason"], json!("ready"), "a machine's row takes any path");
}

#[test]
fn the_pool_goes_back_up_as_soon_as_a_row_is_fit_again() {
    let stand = Stand::new(json!([on_account("first", "key", "m"), on_account("second", "other", "m")]));
    assert_eq!(stand.served(&[]), "first");
    assert_eq!(stand.served(&["row:first"]), "second");
    assert!(stand.steps.failed(&stand.provider("key"), 429, None));
    assert_eq!(stand.served(&[]), "second", "the account rests");
    stand.clock.set(NOW + 29.0);
    assert_eq!(stand.served(&[]), "second");
    stand.clock.set(NOW + 31.0);
    assert_eq!(stand.served(&[]), "first");
}

#[test]
fn a_refusal_rests_an_account_for_its_own_time() {
    let cases: [(u16, Option<&str>, &str, f64); 7] = [
        (401, None, "auth_rejected", 300.0),
        (402, None, "payment", 300.0),
        (429, None, "quota", 30.0),
        (429, Some("200"), "quota", 200.0),
        (429, Some("99999"), "quota", 3600.0),
        (429, Some("0"), "quota", 1.0),
        (429, Some("soon"), "quota", 30.0),
    ];
    for (status, said, reason, rest) in cases {
        let stand = Stand::new(json!([on_account("r", "key", "m")]));
        assert!(stand.steps.failed(&stand.provider("key"), status, said), "{status}");
        assert_eq!(stand.first_reason(&[]), reason, "{status} {said:?}");
        assert_eq!(stand.rows_said()[0]["resetAt"], json!(NOW + rest), "{status} {said:?}");
        stand.clock.set(NOW + rest - 0.5);
        assert_eq!(stand.first_reason(&[]), reason, "{status} {said:?}");
        stand.clock.set(NOW + rest);
        assert_eq!(stand.first_reason(&[]), "ready", "{status} {said:?}");
    }
    let stand = Stand::new(json!([on_account("r", "key", "m")]));
    for other in [200, 400, 403, 404, 500, 503] {
        assert!(!stand.steps.failed(&stand.provider("key"), other, Some("100")), "{other}");
    }
    assert_eq!(stand.first_reason(&[]), "ready", "any other answer is the row's, and nothing rests");
    assert!(stand.steps.failed(&stand.provider("key"), 429, Some("")));
    assert_eq!(stand.rows_said()[0]["reason"], json!("ready"), "the word is read at the next choice");
    assert_eq!(stand.first_reason(&[]), "quota");
    assert_eq!(stand.rows_said()[0]["resetAt"], json!(NOW + 30.0), "an empty word is no word");
}

#[test]
fn a_reset_by_hand_ends_a_rest_for_a_limit_and_no_other() {
    let mut stand = Stand::new(json!([on_account("r", "key", "m")]));
    assert!(stand.steps.failed(&stand.provider("key"), 429, Some("1000")));
    stand.settings.resets.insert("key".to_string(), NOW - 1.0);
    assert_eq!(stand.first_reason(&[]), "quota", "a reset before the refusal says nothing of it");
    stand.settings.resets.insert("key".to_string(), NOW);
    assert_eq!(stand.first_reason(&[]), "ready", "a reset at its moment does");
    let mut stand = Stand::new(json!([on_account("r", "key", "m")]));
    assert!(stand.steps.failed(&stand.provider("key"), 401, None));
    stand.settings.resets.insert("key".to_string(), NOW + 1.0);
    assert_eq!(stand.first_reason(&[]), "auth_rejected");
}

#[test]
fn a_subscription_row_goes_by_its_limits() {
    let later = NOW as i64 + 1000;
    let cases: [(&str, i64, &str, bool); 7] = [
        ("levelled", 50, "ready", true),
        ("levelled", 69, "ready", true),
        ("levelled", 71, "switch", true),
        ("levelled", 94, "switch", true),
        ("levelled", 96, "reserve", false),
        ("plain", 99, "ready", true),
        ("plain", 100, "quota", false),
    ];
    for (model, used, reason, fit) in cases {
        let stand = Stand::new(json!([on_account("r", "sub", model)]));
        stand.reads(used, Some(later));
        assert_eq!(stand.first_reason(&[]), reason, "{model} at {used}");
        assert_eq!(stand.rows_said()[0]["eligible"], json!(fit), "{model} at {used}");
        assert_eq!(stand.page.asked.load(Ordering::SeqCst), 0, "a fresh reading needs no page");
        assert_eq!(stand.rows_said()[0]["windows"][0]["usedPct"], json!(used));
    }
}

#[test]
fn a_limit_says_when_it_resets() {
    let later = NOW as i64 + 1000;
    let stand = Stand::new(json!([on_account("r", "sub", "levelled")]));
    stand.reads(96, Some(later));
    assert_eq!(stand.first_reason(&[]), "reserve");
    assert_eq!(stand.rows_said()[0]["resetAt"], json!(later));
    assert_eq!(stand.rows_said()[0]["reserve"]["reservePct"], json!(5));
    let stand = Stand::new(json!([on_account("r", "sub", "levelled")]));
    stand.reads(71, Some(later));
    assert_eq!(stand.first_reason(&[]), "switch");
    assert_eq!(stand.rows_said()[0]["resetAt"], json!(later));
    let stand = Stand::new(json!([on_account("r", "sub", "plain")]));
    stand.steps.usage.keep(
        "sub",
        vec![
            rules::UsageWindow { seconds: 18_000, used_pct: 100, reset_at: Some(later) },
            rules::UsageWindow { seconds: 604_800, used_pct: 100, reset_at: None },
            rules::UsageWindow { seconds: 900, used_pct: 10, reset_at: Some(later + 9000) },
        ],
        NOW,
    );
    assert_eq!(stand.first_reason(&[]), "quota");
    assert_eq!(stand.rows_said()[0]["resetAt"], json!(later as f64), "the latest of the exhausted windows");
}

#[test]
fn a_level_on_a_window_with_no_reset_is_a_limit_nobody_can_answer_for() {
    let stand = Stand::new(json!([on_account("r", "sub", "levelled")]));
    stand.reads(10, None);
    assert_eq!(stand.first_reason(&[]), "usage_unknown");
    let stand = Stand::new(json!([on_account("r", "sub", "plain")]));
    stand.reads(10, None);
    assert_eq!(stand.first_reason(&[]), "ready", "no level names it");
}

#[test]
fn a_row_held_at_its_switch_gives_way_to_a_ready_one_and_serves_when_there_is_none() {
    let stand = Stand::new(json!([on_account("held", "sub", "levelled"), on_account("next", "key", "m")]));
    stand.reads(71, Some(NOW as i64 + 1000));
    assert_eq!(stand.served(&[]), "next");
    assert_eq!(stand.served(&["row:next"]), "held");
    assert!(stand.can_go_on(true));
}

#[test]
fn the_usage_page_is_asked_when_no_reading_answers_and_not_more_often() {
    let page_says = |used: i64| json!({"rate_limit": {"primary_window": {"limit_window_seconds": 18_000, "used_percent": used, "reset_at": NOW as i64 + 10_000}}});
    let asked = |stand: &Stand| stand.page.asked.load(Ordering::SeqCst);
    let stand = Stand::new(json!([on_account("r", "sub", "levelled")]));
    assert_eq!(stand.first_reason(&[]), "usage_unknown", "a page that says nothing");
    assert_eq!(asked(&stand), 1);
    stand.clock.set(NOW + 29.0);
    assert_eq!(stand.first_reason(&[]), "usage_unknown");
    assert_eq!(asked(&stand), 1, "a failed page is left alone for a while");
    stand.clock.set(NOW + 30.0);
    *stand.page.says.lock().unwrap() = Some(page_says(10));
    assert_eq!(stand.first_reason(&[]), "ready");
    assert_eq!(asked(&stand), 2);
    assert_eq!(stand.rows_said()[0]["readAt"], json!(NOW + 30.0));
    stand.clock.set(NOW + 30.0 + 299.0);
    assert_eq!(stand.first_reason(&[]), "ready");
    assert_eq!(asked(&stand), 2, "a reading is fresh for five minutes");
    stand.clock.set(NOW + 30.0 + 300.0);
    assert_eq!(stand.first_reason(&[]), "ready");
    assert_eq!(asked(&stand), 3, "and no longer");
}

#[test]
fn a_reading_past_its_window_s_reset_or_older_than_a_reset_by_hand_is_no_reading() {
    let stand = Stand::new(json!([on_account("r", "sub", "plain")]));
    stand.reads(100, Some(NOW as i64 + 10));
    assert_eq!(stand.first_reason(&[]), "quota");
    stand.clock.set(NOW + 10.0);
    assert_eq!(stand.first_reason(&[]), "usage_unknown", "the window has reset, and what it says now is not known");
    assert_eq!(stand.page.asked.load(Ordering::SeqCst), 1);
    let mut stand = Stand::new(json!([on_account("r", "sub", "plain")]));
    stand.reads(100, Some(NOW as i64 + 1000));
    stand.settings.resets.insert("sub".to_string(), NOW + 1.0);
    assert_eq!(stand.first_reason(&[]), "usage_unknown");
    assert_eq!(stand.page.asked.load(Ordering::SeqCst), 1);
}

#[test]
fn a_page_that_says_there_are_no_limits_is_believed_for_a_while() {
    let no_limits = json!({"rate_limit": {"allowed": true, "limit_reached": false, "primary_window": null}});
    let stand = Stand::new(json!([on_account("r", "sub", "plain")]));
    *stand.page.says.lock().unwrap() = Some(no_limits);
    assert_eq!(stand.first_reason(&[]), "ready");
    assert_eq!(stand.rows_said()[0]["windows"], json!([]));
    assert_eq!(stand.rows_said()[0]["readAt"], json!(NOW));
    stand.clock.set(NOW + 299.0);
    assert_eq!(stand.first_reason(&[]), "ready");
    assert_eq!(stand.page.asked.load(Ordering::SeqCst), 1);
    assert_eq!(stand.rows_said()[0]["readAt"], json!(NOW));
    stand.clock.set(NOW + 300.0);
    assert_eq!(stand.first_reason(&[]), "ready");
    assert_eq!(stand.page.asked.load(Ordering::SeqCst), 2);
    for says in [
        json!({"rate_limit": {"allowed": false, "primary_window": null}}),
        json!({"rate_limit": {"allowed": true, "limit_reached": true}}),
        json!({"rate_limit": {"allowed": true, "primary_window": {"x": 1}}}),
        json!({"rate_limit": {"allowed": true, "secondary_window": {"x": 1}}}),
        json!({"rate_limit": "none"}),
        json!({}),
    ] {
        let stand = Stand::new(json!([on_account("r", "sub", "plain")]));
        *stand.page.says.lock().unwrap() = Some(says.clone());
        assert_eq!(stand.first_reason(&[]), "usage_unknown", "{says}");
    }
}

#[test]
fn a_busy_model_gives_way_to_a_ready_row_or_waits_its_patience() {
    let rows = json!([on_machine("first", "full"), on_machine("second", "free")]);
    let mut gives_way = Stand::with_policy(rows.clone(), json!({"queueYieldSec": 0}));
    gives_way.busy = vec!["full"];
    assert_eq!(gives_way.served(&[]), "second");
    assert_eq!(gives_way.rows_said()[0]["reason"], json!("busy"));
    assert_eq!(gives_way.rows_said()[0]["eligible"], json!(true));
    let mut waits = Stand::with_policy(rows, json!({"queueYieldSec": 60}));
    waits.busy = vec!["full"];
    let RowChoice::Machine(row) = waits.resolve_on(CHAT, b"{}", &[]).0 else { panic!("a machine's row") };
    assert_eq!(row.row_id, "first");
    assert_eq!(row.leave, QueueLeave::at_admission(&waits.settings.policy, true), "with a ready row to go on to");
    let mut alone = Stand::with_policy(json!([on_machine("first", "full")]), json!({"queueYieldSec": 0}));
    alone.busy = vec!["full"];
    let RowChoice::Machine(row) = alone.resolve_on(CHAT, b"{}", &[]).0 else { panic!("a machine's row") };
    assert_eq!(row.row_id, "first", "nobody to give way to");
    assert_eq!(row.leave, QueueLeave::at_admission(&alone.settings.policy, false));
}

#[test]
fn whether_a_request_can_go_on_is_asked_without_a_word_recorded() {
    let mut stand = Stand::new(json!([on_machine("r", "full")]));
    stand.busy = vec!["full"];
    assert!(stand.can_go_on(false), "a busy row can still serve");
    assert!(!stand.can_go_on(true), "but it is not ready");
    stand.busy = Vec::new();
    assert!(stand.can_go_on(true));
    assert_eq!(stand.steps.snapshot()["pools"], json!({}));
    assert_eq!(stand.steps.snapshot()["events"], json!([]));
    let nothing = Stand::new(json!([{"id": "r"}]));
    assert!(!nothing.can_go_on(false));
}

#[test]
fn a_response_to_go_on_from_stays_with_a_pool_of_one_row() {
    let goes_on = br#"{"previous_response_id": "resp_1"}"#;
    let two = Stand::new(json!([on_account("a", "key", "m"), on_account("b", "other", "m")]));
    let (RowChoice::Refused(refusal), event) = two.resolve_on(CHAT, goes_on, &[]) else { panic!("refused") };
    assert_eq!((refusal.status, refusal.kind), (400, "pool_context_required"));
    assert_eq!(event, None);
    assert!(matches!(two.resolve_on(CHAT, br#"{"previous_response_id": ""}"#, &[]).0, RowChoice::Cloud(_)));
    assert!(matches!(two.resolve_on(CHAT, b"not json", &[]).0, RowChoice::Cloud(_)));
    let one = Stand::new(
        json!([on_account("a", "key", "m"), {"id": "open"}, {"id": "off", "accountId": "other", "model": "m", "enabled": false}]),
    );
    assert!(
        matches!(one.resolve_on(CHAT, goes_on, &[]).0, RowChoice::Cloud(_)),
        "an open row and a row switched off do not count"
    );
}

#[test]
fn the_journal_keeps_a_switch_when_the_choice_moves_and_not_otherwise() {
    let stand = Stand::new(json!([on_account("a", "key", "m"), on_account("b", "other", "m")]));
    let (_, first) = stand.resolve_on(CHAT, b"{}", &[]);
    let first = first.unwrap();
    assert_eq!((&first["poolId"], &first["from"], &first["to"]), (&json!("p"), &json!(null), &json!("a")));
    assert_eq!(first["at"], json!(NOW));
    assert_eq!(first["reasons"], json!([]));
    assert_eq!(stand.resolve_on(CHAT, b"{}", &[]).1, None);
    let (_, moved) = stand.resolve_on(CHAT, b"{}", &["row:a"]);
    let moved = moved.unwrap();
    assert_eq!((&moved["from"], &moved["to"]), (&json!("a"), &json!("b")));
    assert_eq!(moved["reasons"], json!([{"stepId": "a", "reason": "tried"}]));
    let (_, nothing) = stand.resolve_on(CHAT, b"{}", &["row:a", "row:b"]);
    assert_eq!(nothing.unwrap()["to"], json!(null));
    let (_, back) = stand.resolve_on(CHAT, b"{}", &[]);
    assert_eq!(back.unwrap()["from"], json!(null), "a pool with no row chosen has none to move from");
    assert_eq!(stand.steps.snapshot()["pools"]["p"]["selectedStepId"], json!("a"));
    assert_eq!(stand.steps.snapshot()["pools"]["p"]["decidedAt"], json!(NOW));
}

#[test]
fn the_journal_of_switches_stays_short() {
    let stand = Stand::new(json!([on_account("a", "key", "m"), on_account("b", "other", "m")]));
    for turn in 0..120 {
        stand.resolve_on(CHAT, b"{}", if turn % 2 == 0 { &[] } else { &["row:a"] });
    }
    let said = stand.steps.snapshot()["events"].as_array().unwrap().clone();
    assert_eq!(said.len(), 50);
    assert_eq!(said[49]["to"], json!("b"), "the newest stay");
}

#[test]
fn a_refusal_names_the_pool_and_each_row() {
    let stand = Stand::new(json!([{"id": "open"}, on_account("r", "out", "m")]));
    let (RowChoice::Refused(refusal), _) = stand.resolve_on(CHAT, b"{}", &[]) else { panic!("refused") };
    assert_eq!(refusal.status, 503);
    assert_eq!(refusal.message, "Pool the pool has no step that fits now: open (not_connected); r (credential_missing)");
    assert!(refusal.journal_body.contains(r#""pool_id": "p""#), "{}", refusal.journal_body);
}
