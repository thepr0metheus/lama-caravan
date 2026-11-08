//! Router and graph normalization. What goes into the proxy's document goes through here, on its way in and on its way out.

use super::queues::ModelQueues;
use crate::common::entry::{ClientFields, ClientNameWord};
use crate::common::misc::SharedQueuePolicy;
use crate::common::model_kinds::ModelFacts;
use rules::{AppError, Coerce, RouteId};
use serde_json::{Map, Value, json};
use std::collections::{BTreeMap, BTreeSet};

mod graph;

/// `str(value or "").strip()`, what this file reads most.
struct Word;

impl Word {
    fn of(value: Option<&Value>) -> String {
        Coerce::stripped(value)
    }

    fn cut(value: Option<&Value>, most: usize) -> String {
        Coerce::first_letters(&Coerce::stripped(value), most).to_string()
    }
}

/// The normalizers.
pub struct RouterDsl;

impl RouterDsl {
    /// The router every route falls to.
    pub const DEFAULT_ROUTER_ID: &'static str = "router:default";
    const DEFAULT_UPSTREAM_HOST: &'static str = "127.0.0.1";
    const DEFAULT_UPSTREAM_PORT: i64 = 8080;
    const NODE_TYPES: [&'static str; 9] =
        ["byModel", "schedule", "weighted", "roundRobin", "failover", "queue", "requestType", "requestSize", "onError"];
    const WEEKDAYS: [&'static str; 7] = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];

    fn bad_int(value: Option<&Value>) -> AppError {
        AppError::with_status(format!("invalid literal for int(): {}", Coerce::str_of(value)), 500)
    }

    /// `int(value or default)`.
    fn int_or(value: Option<&Value>, default: i64) -> Result<i64, AppError> {
        match value.filter(|value| Coerce::truthy(Some(*value))) {
            Some(said) => Coerce::int(said).ok_or_else(|| Self::bad_int(value)),
            None => Ok(default),
        }
    }

    /// The last word of a label: "primary" or "fallback"; "primary" by default.
    fn role_of_label(label: &str) -> String {
        let label = Coerce::strip(label);
        let last = label.rsplit_once(char::is_whitespace).map(|(_, last)| last.to_lowercase());
        last.filter(|word| matches!(word.as_str(), "primary" | "fallback")).unwrap_or_else(|| "primary".to_string())
    }

    /// A label without its role, for grouping.
    fn group_key(label: &str) -> String {
        let text = Coerce::strip(label);
        let base = match text.rsplit_once(char::is_whitespace) {
            Some((head, last)) if matches!(last.to_lowercase().as_str(), "primary" | "fallback") => head,
            _ => text,
        };
        Coerce::strip(base).to_lowercase()
    }

    /// The out-of-the-box single output.
    fn default_output() -> Value {
        json!({"id": "o1", "label": format!("llama :{}", Self::DEFAULT_UPSTREAM_PORT), "target": format!("skynet:llama-server:{}", Self::DEFAULT_UPSTREAM_PORT), "upstreamHost": Self::DEFAULT_UPSTREAM_HOST, "upstreamPort": Self::DEFAULT_UPSTREAM_PORT, "upstreamType": "llama", "providerId": ""})
    }

    /// One output.
    pub fn output(out: &Value) -> Result<Value, AppError> {
        let said_type = Coerce::text(out.get("upstreamType")).to_lowercase();
        let said_type = Coerce::strip(&said_type);
        let upstream = if matches!(said_type, "engine" | "machine" | "cloud") { said_type } else { "llama" };
        let id = Word::of(out.get("id"));
        let host = Word::of(out.get("upstreamHost"));
        let mut norm = Map::new();
        norm.insert("id".to_string(), json!(if id.is_empty() { "o1" } else { id.as_str() }));
        norm.insert("label".to_string(), json!(Word::cut(out.get("label"), 80)));
        norm.insert("target".to_string(), json!(Word::of(out.get("target"))));
        norm.insert("upstreamHost".to_string(), json!(if host.is_empty() { Self::DEFAULT_UPSTREAM_HOST } else { host.as_str() }));
        norm.insert("upstreamPort".to_string(), json!(Self::int_or(out.get("upstreamPort"), Self::DEFAULT_UPSTREAM_PORT)?));
        norm.insert("upstreamType".to_string(), json!(upstream));
        norm.insert("providerId".to_string(), json!(Word::of(out.get("providerId"))));
        if upstream == "cloud" {
            norm.insert("accountId".to_string(), json!(Word::of(out.get("accountId"))));
        }
        if upstream == "engine" {
            for (key, limit) in [("upstreamModel", 200), ("engine", 40), ("hostId", 120)] {
                norm.insert(key.to_string(), json!(Word::cut(out.get(key), limit)));
            }
        }
        if upstream == "machine" {
            for (key, limit) in [("upstreamModel", 200), ("hostId", 120)] {
                norm.insert(key.to_string(), json!(Word::cut(out.get(key), limit)));
            }
            let ports: Vec<i64> = out
                .get("copyPorts")
                .and_then(Value::as_array)
                .into_iter()
                .flatten()
                .take(32)
                .filter_map(Value::as_i64)
                .filter(|port| (1..65536).contains(port))
                .collect();
            norm.insert("copyPorts".to_string(), json!(ports));
        }
        if matches!(upstream, "llama" | "machine") {
            norm.extend(ModelFacts::clean_facts(out));
            if out.get("stopped") == Some(&json!(true)) {
                norm.insert("stopped".to_string(), json!(true));
            }
        }
        Ok(Value::Object(norm))
    }

    /// One router.
    pub fn router(router: &Value) -> Result<Value, AppError> {
        let raw_outputs = router.get("outputs").and_then(Value::as_array).map_or(&[][..], Vec::as_slice);
        let mut outputs = raw_outputs.iter().map(Self::output).collect::<Result<Vec<_>, _>>()?;
        if outputs.is_empty() {
            outputs.push(Self::default_output());
        }
        let out_ids: BTreeSet<String> = outputs.iter().map(|row| Coerce::text(row.get("id"))).collect();
        let router_id = Word::of(router.get("id"));
        let router_id = if router_id.is_empty() { Self::DEFAULT_ROUTER_ID.to_string() } else { router_id };
        let empty = json!({});
        let rules = router.get("rules").filter(|rules| rules.is_object()).unwrap_or(&empty);
        let mut default_out = Word::of(rules.get("default"));
        if !out_ids.contains(&default_out) {
            default_out = outputs.first().map_or_else(String::new, |row| Coerce::text(row.get("id")));
        }
        let rows = |key: &str| rules.get(key).and_then(Value::as_array).map_or(&[][..], Vec::as_slice);
        let schedule: Vec<Value> = rows("schedule").iter().filter_map(|rule| Self::schedule_rule(rule, &out_ids)).collect();
        let by_source: Vec<Value> = rows("bySource").iter().filter_map(|rule| Self::by_source_rule(rule, &out_ids)).collect();
        let mut failover: Vec<String> = Vec::new();
        for said in rows("failover") {
            let id = Coerce::str_of(Some(said));
            if out_ids.contains(&id) && !failover.contains(&id) {
                failover.push(id);
            }
        }
        let mut rule_out = Map::new();
        rule_out.insert("default".to_string(), json!(default_out));
        rule_out.insert("schedule".to_string(), json!(schedule));
        rule_out.insert("bySource".to_string(), json!(by_source));
        rule_out.insert("failover".to_string(), json!(failover));
        for key in ["audioOutput", "embeddingsOutput"] {
            let said = Coerce::text(rules.get(key));
            if out_ids.contains(&said) {
                rule_out.insert(key.to_string(), json!(said));
            }
        }
        if !Word::of(rules.get("dormantDefault")).is_empty() {
            rule_out.insert("dormantDefault".to_string(), json!(Coerce::text(rules.get("dormantDefault"))));
        }
        let graph = Self::graph(router.get("graph"), &out_ids);
        let name = Word::cut(router.get("name"), 80);
        Ok(
            json!({"id": router_id, "name": if name.is_empty() { "Default" } else { name.as_str() }, "outputs": outputs, "rules": rule_out, "graph": ModelQueues::new(graph, &outputs, &router_id).reconcile()?}),
        )
    }

    /// A time-window rule.
    fn schedule_rule(rule: &Value, out_ids: &BTreeSet<String>) -> Option<Value> {
        rule.as_object()?;
        let output = Word::of(rule.get("output"));
        out_ids.contains(&output).then(|| json!({"days": Self::days(rule.get("days")), "from": Self::hhmm(rule.get("from"), "00:00"), "to": Self::hhmm(rule.get("to"), "23:59"), "output": output}))
    }

    /// A source-pin rule.
    fn by_source_rule(rule: &Value, out_ids: &BTreeSet<String>) -> Option<Value> {
        rule.as_object()?;
        let output = Word::of(rule.get("output"));
        let (proxy, client) = (Word::of(rule.get("proxyId")), Word::of(rule.get("clientId")));
        (out_ids.contains(&output) && !(proxy.is_empty() && client.is_empty()))
            .then(|| json!({"proxyId": proxy, "clientId": client, "output": output}))
    }

    /// A word for an upstream's host.
    fn host_ok(host: &str) -> bool {
        !host.is_empty() && host.chars().all(|letter| letter.is_ascii_alphanumeric() || matches!(letter, '_' | '.' | ':' | '-'))
    }

    /// One client's record, or a refusal. A client is known by its id and has no number: it comes in through the entry with its key
    /// (the owner, 2026-11-07).
    pub fn route(route: &Value) -> Result<Value, AppError> {
        let label = Word::cut(route.get("label"), 80);
        let id = Word::of(route.get("id"));
        let host =
            if Coerce::truthy(route.get("upstreamHost")) { Word::of(route.get("upstreamHost")) } else { "127.0.0.1".to_string() };
        let upstream_port = Self::int_or(route.get("upstreamPort"), 8080)?;
        if !RouteId::acceptable(&id) {
            return Err(AppError::new(
                "a client's record needs its id: a client is made with ＋ in the Clients column, which gives it one",
            ));
        }
        if label.is_empty() {
            return Err(AppError::new("label is required"));
        }
        if !(1..=65535).contains(&upstream_port) {
            return Err(AppError::new("upstream port must be 1..65535"));
        }
        if !Self::host_ok(&host) {
            return Err(AppError::new("upstream host contains unsupported characters"));
        }
        let upstream_type = Word::of(route.get("upstreamType")).to_lowercase();
        let upstream_type = if upstream_type == "cloud" { "cloud" } else { "llama" };
        let kind = Word::of(route.get("kind")).to_lowercase();
        if kind == "service" {
            return Err(AppError::new("a pool's own port is gone: a client comes in through the entry with its own key"));
        }
        if kind != "consumer" {
            return Err(AppError::new(
                "a route of the old kind has no way in: the entry serves clients alone — make one with ＋ in the Clients column",
            ));
        }
        let kind = "consumer";
        let mode =
            if Coerce::truthy(route.get("mode")) { Word::of(route.get("mode")).to_lowercase() } else { "open".to_string() };
        let on = |key: &str, default: bool| route.get(key).map_or(default, |flag| Coerce::truthy(Some(flag)));
        let mut row = Map::new();
        row.insert("id".to_string(), json!(id));
        row.insert("label".to_string(), json!(label));
        row.insert("kind".to_string(), json!(kind));
        row.extend(ClientFields::of(route));
        row.insert("upstreamHost".to_string(), json!(host));
        row.insert("upstreamPort".to_string(), json!(upstream_port));
        row.insert("upstreamType".to_string(), json!(upstream_type));
        row.insert("providerId".to_string(), json!(Word::of(route.get("providerId"))));
        row.insert("enabled".to_string(), json!(on("enabled", true)));
        row.insert("mode".to_string(), json!(mode));
        row.insert("apiKey".to_string(), json!(Word::cut(route.get("apiKey"), 128)));
        row.insert("priority".to_string(), json!(Self::int_or(route.get("priority"), 0)?));
        row.insert("preemptible".to_string(), json!(on("preemptible", true)));
        row.insert("clientTimeoutSeconds".to_string(), json!(Self::int_or(route.get("clientTimeoutSeconds"), 0)?.max(0)));
        Self::route_tail(route, &mut row)?;
        Ok(Value::Object(row))
    }

    fn route_tail(route: &Value, row: &mut Map<String, Value>) -> Result<(), AppError> {
        let window = Word::of(route.get("contextLength"));
        let digits = window.trim_start_matches('-');
        if !digits.is_empty() && digits.chars().all(|letter| letter.is_ascii_digit()) {
            let number =
                route.get("contextLength").and_then(Coerce::int).ok_or_else(|| Self::bad_int(route.get("contextLength")))?;
            if number > 0 {
                row.insert("contextLength".to_string(), json!(number));
            }
        }
        if Coerce::truthy(route.get("contextAuto")) {
            row.insert("contextAuto".to_string(), json!(true));
        }
        if !Word::of(route.get("modelName")).is_empty() {
            row.insert("modelName".to_string(), json!(Word::cut(route.get("modelName"), 120)));
        }
        if Coerce::truthy(route.get("modelNameAuto")) {
            row.insert("modelNameAuto".to_string(), json!(true));
        }
        row.insert("cloudFallbackProviderId".to_string(), json!(Word::of(route.get("cloudFallbackProviderId"))));
        row.insert("cloudFallbackEligible".to_string(), json!(Coerce::truthy(route.get("cloudFallbackEligible"))));
        for key in ["cloudFallbackPct", "priorityPreemptPct", "queueAbortPct"] {
            if let Some(said) = route.get(key).filter(|said| !said.is_null()) {
                row.insert(key.to_string(), json!(Coerce::int(said).ok_or_else(|| Self::bad_int(Some(said)))?.clamp(0, 100)));
            }
        }
        // A client of the entry calls a pool or a model by its name: it feeds no router.
        row.insert("routerId".to_string(), json!(""));
        let role = Word::of(route.get("role")).to_lowercase();
        row.insert(
            "role".to_string(),
            json!(if role.is_empty() { Self::role_of_label(&Coerce::text(route.get("label"))) } else { role }),
        );
        row.insert("clientId".to_string(), json!(Word::of(route.get("clientId"))));
        Ok(())
    }

    /// Re-evaluates the cloud-fallback eligibility for every route, in place.
    pub fn recompute_cloud_fallback(routes: &mut [Value]) {
        let is_consumer = |route: &Value| route.get("kind").and_then(Value::as_str) == Some("consumer");
        let is_cloud = |route: &Value| Word::of(route.get("upstreamType")).to_lowercase() == "cloud";
        let mut group_cloud: BTreeMap<String, String> = BTreeMap::new();
        for route in routes.iter().filter(|route| route.is_object() && !is_consumer(route) && is_cloud(route)) {
            let provider = Word::of(route.get("providerId"));
            if !provider.is_empty() {
                group_cloud.entry(Self::group_key(&Coerce::text(route.get("label")))).or_insert(provider);
            }
        }
        for route in routes.iter_mut().filter(|route| route.is_object() && !is_consumer(route)) {
            let provider =
                group_cloud.get(&Self::group_key(&Coerce::text(route.get("label")))).cloned().filter(|_| !is_cloud(route));
            let keeps = !Word::of(route.get("cloudFallbackProviderId")).is_empty();
            if let Value::Object(fields) = route {
                fields.insert("cloudFallbackEligible".to_string(), json!(provider.is_some()));
                match provider {
                    Some(provider) if keeps => {
                        fields.insert("cloudFallbackProviderId".to_string(), json!(provider));
                    }
                    Some(_) => {}
                    None => {
                        fields.insert("cloudFallbackProviderId".to_string(), json!(""));
                    }
                }
            }
        }
    }

    /// The proxy's policy, every setting in its range.
    pub fn policy(policy: Option<&Value>) -> Value {
        let empty = json!({});
        let policy = policy.filter(|policy| policy.is_object()).unwrap_or(&empty);
        let bounded = |key: &str, default: i64, least: i64, most: i64| {
            policy.get(key).map_or(Some(default), Coerce::int).unwrap_or(default).clamp(least, most)
        };
        let mut out = Map::new();
        out.insert("maxSlots".to_string(), json!(bounded("maxSlots", 1, 1, 64)));
        out.insert("priorityPreemptPct".to_string(), json!(bounded("priorityPreemptPct", 50, 0, 100)));
        out.insert("queueAbortPct".to_string(), json!(bounded("queueAbortPct", 85, 1, 100)));
        out.insert("preemptGraceSec".to_string(), json!(bounded("preemptGraceSec", 20, 1, 300)));
        out.insert(
            "preemptEnabled".to_string(),
            json!(policy.get("preemptEnabled").is_none_or(|flag| Coerce::truthy(Some(flag)))),
        );
        out.extend(Coerce::fields(&SharedQueuePolicy::policy_values(Some(policy))));
        let (yields, limit) = (bounded("queueYieldSec", 0, 0, 3600), bounded("queueLimitSec", 0, 0, 3600));
        out.insert("queueYieldSec".to_string(), json!(if limit != 0 { yields.min(limit) } else { yields }));
        out.insert("queueLimitSec".to_string(), json!(limit));
        out.insert("clientTimeoutSec".to_string(), json!(bounded("clientTimeoutSec", 3600, 60, 86400)));
        out.insert(ClientNameWord::KEY.to_string(), json!(ClientNameWord::of(Some(policy))));
        Value::Object(out)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn an_output_keeps_what_its_type_has() {
        let cloud = RouterDsl::output(
            &json!({"id": "cb:p", "upstreamType": "cloud", "accountId": " a ", "upstreamHost": "", "upstreamPort": 0}),
        )
        .unwrap();
        assert_eq!(cloud.get("accountId"), Some(&json!("a")));
        assert_eq!(cloud.get("upstreamHost"), Some(&json!("127.0.0.1")));
        assert_eq!(cloud.get("upstreamPort"), Some(&json!(8080)));
        let machine = RouterDsl::output(
            &json!({"upstreamType": "MACHINE", "copyPorts": [1, "2", true, 70000, 3], "stopped": true, "jobs": ["llm"]}),
        )
        .unwrap();
        assert_eq!(machine.get("copyPorts"), Some(&json!([1, 3])));
        assert_eq!(machine.get("stopped"), Some(&json!(true)));
        assert_eq!(machine.get("jobs"), Some(&json!(["llm"])));
        assert_eq!(RouterDsl::output(&json!({"upstreamType": "odd"})).unwrap().get("upstreamType"), Some(&json!("llama")));
    }

    #[test]
    fn a_route_is_refused_by_what_is_wrong_with_it() {
        let words = |route: Value| RouterDsl::route(&route).unwrap_err().message;
        assert_eq!(words(json!({"label": "", "id": "c1", "kind": "consumer"})), "label is required");
        assert!(words(json!({"label": "a", "port": 23001, "kind": "consumer"})).starts_with("a client's record needs its id"));
        assert!(words(json!({"label": "a", "id": "a b", "kind": "consumer"})).starts_with("a client's record needs its id"));
        assert_eq!(
            words(json!({"label": "a", "id": "c1", "kind": "consumer", "upstreamHost": "a b"})),
            "upstream host contains unsupported characters"
        );
        assert!(words(json!({"label": "a", "id": "c1", "kind": "service"})).starts_with("a pool's own port is gone"));
        assert!(words(json!({"label": "a", "id": "c1"})).starts_with("a route of the old kind has no way in"));
        let row = RouterDsl::route(
            &json!({"label": "x fallback", "id": " c1 ", "port": "2000", "portClosed": true, "contextLength": "0", "kind": "consumer", "deny": ["pool:a", "nope"]}),
        )
        .unwrap();
        assert_eq!((row.get("id"), row.get("port"), row.get("portClosed")), (Some(&json!("c1")), None, None));
        assert_eq!(row.get("role"), Some(&json!("fallback")));
        assert_eq!(row.get("routerId"), Some(&json!("")));
        assert_eq!(row.get("deny"), Some(&json!(["pool:a"])));
        assert!(row.get("contextLength").is_none());
    }

    #[test]
    fn a_route_in_a_cloud_group_may_fall_back() {
        let mut routes = [
            json!({"label": "x primary", "upstreamType": "llama", "cloudFallbackProviderId": "old"}),
            json!({"label": "x fallback", "upstreamType": "cloud", "providerId": "p"}),
            json!({"label": "y", "cloudFallbackProviderId": "z"}),
        ];
        RouterDsl::recompute_cloud_fallback(&mut routes);
        assert_eq!(routes[0].get("cloudFallbackEligible"), Some(&json!(true)));
        assert_eq!(routes[0].get("cloudFallbackProviderId"), Some(&json!("p")));
        assert_eq!(routes[1].get("cloudFallbackEligible"), Some(&json!(false)));
        assert_eq!(routes[2].get("cloudFallbackProviderId"), Some(&json!("")));
    }

    #[test]
    fn a_policy_is_in_its_range() {
        let policy = RouterDsl::policy(Some(
            &json!({"maxSlots": 100, "queueLimitSec": 10, "queueYieldSec": 50, "preemptEnabled": 0, "clientName": "имя"}),
        ));
        assert_eq!(policy.get("maxSlots"), Some(&json!(64)));
        assert_eq!(policy.get("queueYieldSec"), Some(&json!(10)));
        assert_eq!(policy.get("preemptEnabled"), Some(&json!(false)));
        assert_eq!(policy.get("clientName"), Some(&json!("")));
    }

    #[test]
    fn a_time_of_a_rule_is_clamped() {
        assert_eq!(RouterDsl::hhmm(Some(&json!(" 25:70 ")), "00:00"), "23:59");
        assert_eq!(RouterDsl::hhmm(Some(&json!("9:05")), "00:00"), "09:05");
        assert_eq!(RouterDsl::hhmm(Some(&json!("x")), "01:00"), "01:00");
    }
}
