//! What the entry decides of a request: serve it or refuse it. Only values go in and out, so that each answer can be checked by value;
//! `connection` acts on it. The rule: nothing is guessed. What the files do not let it say is refused in words.

use files::Settings;
use rules::{Coerce, EntryRefusal, KeyEntry, Pick, Pool, RequestFields, RequestJson, RequestKind, Route};
use serde_json::{Map, Value};
use wire::{Percent, RequestHead};

/// The decision before the body is read.
#[derive(Debug, PartialEq, Eq)]
pub enum BeforeBody {
    /// The body is needed to decide: the key has found this route, and the path says what the body is for.
    ReadBody(Route, BodyFor),
    /// This process's own answer: a question of the model list.
    Answer(Value),
    /// This process's own refusal, under the client's name once the key has found one.
    Refuse(EntryRefusal, Option<Route>),
}

/// What a request's body is read for.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BodyFor {
    /// A request to a model.
    Model,
    /// Ollama's question of a model's particulars: Hermes asks it for a model's window.
    Show,
}

/// The decision with the body in hand.
#[derive(Debug, PartialEq, Eq)]
pub enum WithBody {
    /// This process's: the model, and whether the client asked for a stream.
    Serve {
        /// The pool the name means.
        pool: Box<Pool>,
        /// Whether the client asked for a stream.
        streaming: bool,
    },
    /// This process's own answer: a question of the model list.
    Answer(Value),
    /// This process's own refusal.
    Refuse(EntryRefusal),
}

/// The decisions.
pub struct Front;

impl Front {
    const MODELS: &'static str = "/v1/models";
    const ONE_MODEL: &'static str = "/v1/models/";
    const SHOW: &'static str = "/api/show";

    /// What the head alone decides. `now` is what a list says as its `created`.
    pub fn before_body(settings: &Settings, head: &RequestHead, now: i64) -> BeforeBody {
        if settings.unread {
            return BeforeBody::Refuse(EntryRefusal::settings_unreadable(), None);
        }
        let key = KeyEntry::presented_key(head.headers.get("Authorization").as_deref(), head.headers.get("x-api-key").as_deref());
        let route = match KeyEntry::route_for(&key, &settings.routes) {
            Ok(route) => route,
            Err(miss) => return BeforeBody::Refuse(EntryRefusal::of_key(miss, &key), None),
        };
        if !route.is_consumer() {
            return BeforeBody::Refuse(EntryRefusal::not_a_consumer(), Some(route.clone()));
        }
        let path = head.path();
        match head.method.as_str() {
            "GET" => Self::question(settings, route, path, now),
            "OPTIONS" => BeforeBody::Refuse(EntryRefusal::invalid_url("OPTIONS", path), Some(route.clone())),
            "POST" if path.trim_end_matches('/') == Self::SHOW => BeforeBody::ReadBody(route.clone(), BodyFor::Show),
            "POST" if !RequestKind::is_inference(&head.method, path) => {
                BeforeBody::Refuse(EntryRefusal::invalid_url("POST", path), Some(route.clone()))
            }
            "POST" => BeforeBody::ReadBody(route.clone(), BodyFor::Model),
            _ => BeforeBody::Refuse(EntryRefusal::other_method(&head.method), Some(route.clone())),
        }
    }

    /// A target as `urlsplit` reads it: an address before the path and a fragment after it come off. Slashes at its start are one: a client whose base address ends in a slash asks `//v1/models`, and means the list.
    pub fn plain_target(target: &str) -> String {
        let no_fragment = target.split('#').next().unwrap_or(target);
        if no_fragment.starts_with("//") {
            return format!("/{}", no_fragment.trim_start_matches('/'));
        }
        let after_scheme =
            no_fragment.find("://").filter(|at| no_fragment.get(..*at).is_some_and(|word| !word.contains('/'))).map(|at| at + 1);
        let from_host = match after_scheme {
            Some(at) => no_fragment.get(at..),
            None => Some(no_fragment),
        };
        let Some(rest) = from_host.and_then(|text| text.strip_prefix("//")) else {
            return from_host.unwrap_or(no_fragment).to_string();
        };
        match rest.find(['/', '?']) {
            Some(at) => {
                let tail = rest.get(at..).unwrap_or("/");
                if tail.starts_with('?') { format!("/{tail}") } else { tail.to_string() }
            }
            None => "/".to_string(),
        }
    }

    /// The model list, one model of it, and any other question: a path the entry has not.
    fn question(settings: &Settings, route: &Route, path: &str, now: i64) -> BeforeBody {
        let models = &settings.models;
        if route.is_paused() {
            return BeforeBody::Refuse(EntryRefusal::paused(), Some(route.clone()));
        }
        let listed = path.trim_end_matches('/') == Self::MODELS;
        let one = path.strip_prefix(Self::ONE_MODEL).filter(|rest| !rest.is_empty());
        if !listed && one.is_none() {
            return BeforeBody::Refuse(EntryRefusal::invalid_url("GET", path), Some(route.clone()));
        }
        if !models.sure() {
            return BeforeBody::Refuse(EntryRefusal::settings_unreadable(), Some(route.clone()));
        }
        let Some(one) = one.filter(|_| !listed) else {
            return BeforeBody::Answer(models.list(route, now));
        };
        let wanted = Percent::decode(one);
        match models.pick(&route.deny, &wanted) {
            Some(pool) => BeforeBody::Answer(models.model_object(route, pool, now)),
            None => BeforeBody::Refuse(models.refusal_of(&route.deny, &wanted), Some(route.clone())),
        }
    }

    /// What the body decides.
    pub fn with_body(settings: &Settings, route: &Route, head: &RequestHead, body: &[u8], body_for: BodyFor) -> WithBody {
        match body_for {
            BodyFor::Model => Self::request_model(settings, route, head, body),
            BodyFor::Show => Self::shown_model(settings, route, body),
        }
    }

    /// Ollama's `/api/show`: the model the body names, `model`, or `name` as older Ollama clients send it, picked among the client's as
    /// a request picks it. What is not a JSON object here names no model.
    fn shown_model(settings: &Settings, route: &Route, body: &[u8]) -> WithBody {
        let models = &settings.models;
        if !models.sure() {
            return WithBody::Refuse(EntryRefusal::settings_unreadable());
        }
        let asked = match RequestJson::read(body) {
            Some(Value::Object(asked)) => asked,
            _ => Map::new(),
        };
        let said = asked.get("model").filter(|model| Coerce::truthy(Some(*model))).or_else(|| asked.get("name"));
        let wanted = Coerce::text(said);
        if Coerce::strip(&wanted).is_empty() {
            return WithBody::Refuse(EntryRefusal::no_model());
        }
        match models.pick(&route.deny, &wanted) {
            Some(pool) => WithBody::Answer(models.show(route, pool)),
            None => WithBody::Refuse(models.refusal_of(&route.deny, &wanted)),
        }
    }

    /// A request to a model: the model it names, read the way its type says it travels. Anything but a form is read as JSON, the type named
    /// or not.
    fn request_model(settings: &Settings, route: &Route, head: &RequestHead, body: &[u8]) -> WithBody {
        let content_type = head.headers.text_of("Content-Type");
        let (model, streaming) = if RequestFields::is_form(&content_type) {
            let Some(fields) = RequestFields::form(&content_type, body) else {
                return WithBody::Refuse(EntryRefusal::unreadable());
            };
            // absent-ok: a form with no `model` field names no model, and `native` refuses it as that.
            (fields.get("model").cloned().unwrap_or_default(), false)
        } else {
            let Some(Value::Object(payload)) = RequestJson::read(body) else {
                return WithBody::Refuse(EntryRefusal::unreadable());
            };
            (Coerce::text(payload.get("model")), Coerce::truthy(payload.get("stream")))
        };
        match settings.models.for_request(&route.deny, &model, head.path()) {
            Pick::Pool(pool) => WithBody::Serve { pool, streaming },
            Pick::Refused(refusal) => WithBody::Refuse(refusal),
            Pick::Unsure => WithBody::Refuse(EntryRefusal::settings_unreadable()),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use files::Documents;
    use serde_json::json;
    use std::io::{BufReader, Cursor};

    fn settings() -> Settings {
        let proxies = json!({
            "routes": [
                {"label": "client", "port": 23001, "kind": "consumer", "apiKey": "client-key", "deny": ["model:mm:closed"]},
                {"label": "held", "port": 23002, "kind": "consumer", "apiKey": "held-key", "mode": "paused"},
                {"label": "crowned", "port": 23003, "kind": "consumer", "apiKey": "crowned-key", "priority": 1},
                {"label": "agent", "port": 23004, "apiKey": "agent-key"},
                {"label": "twin-1", "port": 23005, "kind": "consumer", "apiKey": "twin-key"},
                {"label": "twin-2", "port": 23006, "kind": "consumer", "apiKey": "twin-key"},
            ],
            "routers": [{"outputs": [
                {"id": "mm:a", "upstreamType": "machine", "upstreamModel": "gemma", "upstreamHost": "10.0.0.1", "upstreamPort": 8092, "copyPorts": [22001]},
                {"id": "mm:closed", "upstreamType": "machine", "upstreamModel": "shut", "upstreamHost": "10.0.0.1", "upstreamPort": 8092, "copyPorts": [22002]},
            ]}],
        });
        let cloud = json!({"pools": [{"id": "p", "name": "pool-one", "steps": []}]});
        Settings::read(Documents { proxies: Some(&proxies), cloud: Some(&cloud), ..Documents::default() })
    }

    const NOW: i64 = 1_700_000_000;

    fn head(text: &str) -> RequestHead {
        RequestHead::read(&mut BufReader::new(Cursor::new(text.as_bytes().to_vec()))).unwrap()
    }

    fn chat(key: &str, extra: &str) -> RequestHead {
        head(&format!(
            "POST /v1/chat/completions HTTP/1.1\r\nAuthorization: Bearer {key}\r\nContent-Type: application/json\r\nContent-Length: 20\r\n{extra}\r\n"
        ))
    }

    fn refused(decision: BeforeBody) -> (&'static str, Option<String>) {
        match decision {
            BeforeBody::Refuse(refusal, route) => (refusal.reason, route.map(|route| route.label)),
            other => panic!("not refused: {other:?}"),
        }
    }

    fn reads_body(decision: BeforeBody) -> BodyFor {
        match decision {
            BeforeBody::ReadBody(_, body_for) => body_for,
            other => panic!("not to read a body: {other:?}"),
        }
    }

    #[test]
    fn a_plain_chat_of_a_client_needs_its_body() {
        match Front::before_body(&settings(), &chat("client-key", ""), NOW) {
            BeforeBody::ReadBody(route, body_for) => assert_eq!((route.label.as_str(), body_for), ("client", BodyFor::Model)),
            other => panic!("not to read a body: {other:?}"),
        }
    }

    #[test]
    fn a_key_that_names_nobody_is_refused() {
        let settings = settings();
        let of = |decision| refused(decision);
        assert_eq!(
            of(Front::before_body(&settings, &head("POST /v1/chat/completions HTTP/1.1\r\n\r\n"), NOW)),
            ("entry:no-key", None)
        );
        assert_eq!(of(Front::before_body(&settings, &chat("nobody", ""), NOW)), ("entry:unknown-key", None));
        assert_eq!(of(Front::before_body(&settings, &chat("twin-key", ""), NOW)), ("entry:ambiguous-key", None));
    }

    #[test]
    fn a_proxies_file_that_does_not_read_blames_no_key() {
        let settings = Settings::read(Documents::default());
        assert_eq!(refused(Front::before_body(&settings, &chat("client-key", ""), NOW)), ("entry:settings-unreadable", None));
    }

    #[test]
    fn a_route_of_the_old_kind_is_refused() {
        let settings = settings();
        assert_eq!(
            refused(Front::before_body(&settings, &chat("agent-key", ""), NOW)),
            ("entry:not-a-consumer", Some("agent".to_string()))
        );
    }

    #[test]
    fn a_paused_client_is_refused_a_question_and_its_request_is_read_first() {
        let settings = settings();
        let asked = head("GET /v1/models HTTP/1.1\r\nAuthorization: Bearer held-key\r\n\r\n");
        assert_eq!(refused(Front::before_body(&settings, &asked, NOW)), ("entry:paused", Some("held".to_string())));
        assert_eq!(reads_body(Front::before_body(&settings, &chat("held-key", ""), NOW)), BodyFor::Model);
    }

    #[test]
    fn a_method_the_entry_has_not_is_refused() {
        let settings = settings();
        let of = |method: &str| {
            refused(Front::before_body(
                &settings,
                &head(&format!("{method} /v1/chat/completions HTTP/1.1\r\nAuthorization: Bearer client-key\r\n\r\n")),
                NOW,
            ))
            .0
        };
        assert_eq!(of("PUT"), "entry:other-method");
        assert_eq!(of("post"), "entry:other-method");
    }

    #[test]
    fn a_path_the_entry_has_not_is_refused_by_its_method() {
        let settings = settings();
        let of = |method: &str, path: &str| {
            let asked = head(&format!("{method} {path} HTTP/1.1\r\nAuthorization: Bearer client-key\r\n\r\n"));
            match Front::before_body(&settings, &asked, NOW) {
                BeforeBody::Refuse(refusal, Some(route)) => (refusal.reason, refusal.error.message, route.label),
                other => panic!("not refused: {other:?}"),
            }
        };
        let invalid = |words: &str| ("entry:invalid-url", words.to_string(), "client".to_string());
        assert_eq!(of("GET", "/v1/chat/completions"), invalid("Invalid URL (GET /v1/chat/completions)"));
        assert_eq!(of("GET", "/v1/modelsx"), invalid("Invalid URL (GET /v1/modelsx)"));
        assert_eq!(of("POST", "/v1/other?x=1"), invalid("Invalid URL (POST /v1/other)"));
        assert_eq!(of("OPTIONS", "/v1/chat/completions"), invalid("Invalid URL (OPTIONS /v1/chat/completions)"));
    }

    #[test]
    fn any_body_is_read_here_whatever_way_it_comes() {
        let settings = settings();
        let of = |text: &str| reads_body(Front::before_body(&settings, &head(text), NOW));
        let client = "Authorization: Bearer client-key\r\n";
        assert_eq!(of(&format!("POST /api/show HTTP/1.1\r\n{client}\r\n")), BodyFor::Show);
        assert_eq!(of(&format!("POST /api/show/ HTTP/1.1\r\n{client}Content-Length: 1\r\n\r\n")), BodyFor::Show);
        for fields in ["Transfer-Encoding: chunked\r\n", "", "Content-Length: 0\r\n", "Content-Length: x\r\n"] {
            assert_eq!(of(&format!("POST /v1/chat/completions HTTP/1.1\r\n{client}{fields}\r\n")), BodyFor::Model, "{fields}");
        }
    }

    fn with_body(body: &str) -> WithBody {
        let settings = settings();
        let route = settings.routes[0].clone();
        Front::with_body(&settings, &route, &chat("client-key", ""), body.as_bytes(), BodyFor::Model)
    }

    fn reason(decision: WithBody) -> &'static str {
        match decision {
            WithBody::Refuse(refusal) => refusal.reason,
            other => panic!("not refused: {other:?}"),
        }
    }

    #[test]
    fn a_form_names_its_model_in_a_field_and_never_streams() {
        let settings = settings();
        let route = settings.routes[0].clone();
        let head = head("POST /v1/chat/completions HTTP/1.1\r\nContent-Type: multipart/form-data; boundary=x\r\n\r\n");
        let of = |body: &[u8]| Front::with_body(&settings, &route, &head, body, BodyFor::Model);
        let named = b"--x\r\nContent-Disposition: form-data; name=\"model\"\r\n\r\ngemma\r\n--x--\r\n";
        assert!(matches!(of(named), WithBody::Serve { streaming: false, .. }));
        let unnamed = b"--x\r\nContent-Disposition: form-data; name=\"a\"\r\n\r\ngemma\r\n--x--\r\n";
        assert_eq!(reason(of(unnamed)), "entry:no-model");
        assert_eq!(reason(of(b"not a form")), "entry:unreadable");
    }

    #[test]
    fn the_work_a_model_does_not_do_is_refused() {
        let mut settings = settings();
        let proxies = json!({"routers": [{"outputs": [
            {"id": "mm:ear", "upstreamType": "machine", "upstreamModel": "ear", "upstreamHost": "h", "upstreamPort": 1, "copyPorts": [2], "jobs": ["asr"]},
        ]}]});
        let cloud = json!({});
        settings.models =
            Settings::read(Documents { proxies: Some(&proxies), cloud: Some(&cloud), ..Documents::default() }).models;
        let route = settings.routes[0].clone();
        let asked = |path: &str| head(&format!("POST {path} HTTP/1.1\r\nContent-Type: application/json\r\n\r\n"));
        let body = br#"{"model":"ear"}"#;
        let of = |path: &str| Front::with_body(&settings, &route, &asked(path), body, BodyFor::Model);
        assert_eq!(reason(of("/v1/chat/completions")), "entry:unsupported");
        assert!(matches!(of("/v1/audio/transcriptions"), WithBody::Serve { .. }));
    }

    #[test]
    fn the_body_names_the_model_and_says_whether_it_streams() {
        match with_body(r#"{"model":"gemma","stream":true}"#) {
            WithBody::Serve { pool, streaming } => assert_eq!((pool.id.as_str(), streaming), ("live:mm:a", true)),
            other => panic!("not served: {other:?}"),
        }
        for body in [r#"{"model":"gemma"}"#, r#"{"model":"gemma","stream":false}"#, r#"{"model":"gemma","stream":null}"#] {
            assert!(matches!(with_body(body), WithBody::Serve { streaming: false, .. }), "{body}");
        }
    }

    #[test]
    fn half_of_a_letter_in_a_message_is_no_reason_to_refuse_a_request() {
        assert!(matches!(with_body(r#"{"model":"gemma","messages":[{"content":"\ud83d"}]}"#), WithBody::Serve { .. }));
    }

    #[test]
    fn a_body_that_says_no_model_or_another_is_refused_as_what_it_is() {
        assert_eq!(reason(with_body("not json")), "entry:unreadable");
        assert_eq!(reason(with_body("[1]")), "entry:unreadable");
        assert_eq!(reason(with_body("")), "entry:unreadable");
        assert_eq!(reason(with_body("{}")), "entry:no-model");
        assert_eq!(reason(with_body(r#"{"model":"  "}"#)), "entry:no-model");
        assert_eq!(reason(with_body(r#"{"model":0}"#)), "entry:no-model");
        assert_eq!(reason(with_body(r#"{"model":5}"#)), "entry:model-unknown");
        assert_eq!(reason(with_body(r#"{"model":"shut"}"#)), "entry:model-closed");
        assert_eq!(reason(with_body(r#"{"model":"nobody"}"#)), "entry:model-unknown");
        assert!(
            matches!(with_body(r#"{"model":"pool-one"}"#), WithBody::Serve { .. }),
            "a pool is this process's now, whatever its rows"
        );
    }

    fn question(target: &str) -> BeforeBody {
        Front::before_body(&settings(), &head(&format!("GET {target} HTTP/1.1\r\nAuthorization: Bearer client-key\r\n\r\n")), NOW)
    }

    fn answer(decision: BeforeBody) -> Value {
        match decision {
            BeforeBody::Answer(answer) => answer,
            other => panic!("not answered: {other:?}"),
        }
    }

    #[test]
    fn the_list_is_answered_here_by_its_every_spelling() {
        for target in ["/v1/models", "/v1/models/", "/v1/models//", "/v1/models?x=1"] {
            let list = answer(question(target));
            let ids: Vec<&str> = list["data"].as_array().unwrap().iter().map(|model| model["id"].as_str().unwrap()).collect();
            assert_eq!(ids, ["pool-one", "gemma"], "{target}");
            assert_eq!(list["data"][0]["created"], json!(NOW), "{target}");
            assert_eq!(list["object"], json!("list"));
        }
    }

    #[test]
    fn one_model_is_answered_here_and_what_the_client_does_not_call_is_refused() {
        assert_eq!(answer(question("/v1/models/gemma"))["id"], json!("gemma"));
        assert_eq!(answer(question("/v1/models/g%65mma"))["id"], json!("gemma"));
        assert_eq!(answer(question("/v1/models/pool-one"))["id"], json!("pool-one"));
        let client = Some("client".to_string());
        assert_eq!(refused(question("/v1/models/shut")), ("entry:model-closed", client.clone()));
        for target in ["/v1/models/nobody", "/v1/models/gemma/", "/v1/models/GEMMA", "/v1/models/%FF"] {
            assert_eq!(refused(question(target)), ("entry:model-unknown", client.clone()), "{target}");
        }
    }

    #[test]
    fn a_key_with_nothing_to_call_is_told_so() {
        let mut settings = settings();
        let proxies = json!({});
        let cloud = json!({});
        settings.models =
            Settings::read(Documents { proxies: Some(&proxies), cloud: Some(&cloud), ..Documents::default() }).models;
        let asked = head("GET /v1/models/any HTTP/1.1\r\nAuthorization: Bearer client-key\r\n\r\n");
        assert_eq!(refused(Front::before_body(&settings, &asked, NOW)).0, "entry:no-pool");
    }

    #[test]
    fn a_reading_it_cannot_answer_for_lists_nothing_here() {
        let mut settings = settings();
        let (proxies, cloud) = (json!({}), json!({"pools": [{"id": "p", "members": []}]}));
        settings.models =
            Settings::read(Documents { proxies: Some(&proxies), cloud: Some(&cloud), ..Documents::default() }).models;
        let asked = head("GET /v1/models HTTP/1.1\r\nAuthorization: Bearer client-key\r\n\r\n");
        let client = Some("client".to_string());
        assert_eq!(refused(Front::before_body(&settings, &asked, NOW)), ("entry:settings-unreadable", client));
        let route = settings.routes[0].clone();
        let show = Front::with_body(&settings, &route, &asked, br#"{"model":"gemma"}"#, BodyFor::Show);
        assert_eq!(show, WithBody::Refuse(EntryRefusal::settings_unreadable()));
        let wrong_path = head("GET /v1/other HTTP/1.1\r\nAuthorization: Bearer client-key\r\n\r\n");
        assert_eq!(refused(Front::before_body(&settings, &wrong_path, NOW)).0, "entry:invalid-url", "no reading decides a path");
    }

    #[test]
    fn a_target_reads_as_urlsplit_reads_it() {
        for (said, plain) in [
            ("http://x/v1/chat/completions?a=1", "/v1/chat/completions?a=1"),
            ("//v1/models", "/v1/models"),
            ("///v1/models?a=1", "/v1/models?a=1"),
            ("//x/v1/models", "/x/v1/models"),
            ("/v1/models#part", "/v1/models"),
            ("/v1/models", "/v1/models"),
            ("http://x", "/"),
            ("//x?a=1", "/x?a=1"),
        ] {
            assert_eq!(Front::plain_target(said), plain, "{said}");
        }
    }

    #[test]
    fn a_route_with_a_priority_is_served_as_any_other() {
        let settings = settings();
        let asked = head("GET /v1/models HTTP/1.1\r\nAuthorization: Bearer crowned-key\r\n\r\n");
        assert!(matches!(Front::before_body(&settings, &asked, NOW), BeforeBody::Answer(_)));
        assert_eq!(reads_body(Front::before_body(&settings, &chat("crowned-key", ""), NOW)), BodyFor::Model);
    }

    #[test]
    fn ollama_s_question_is_read_and_answered_here() {
        let settings = settings();
        let route = settings.routes[0].clone();
        let asked = head("POST /api/show HTTP/1.1\r\nContent-Length: 1\r\n\r\n");
        let of = |body: &str| Front::with_body(&settings, &route, &asked, body.as_bytes(), BodyFor::Show);
        let gemma = settings.models.pick(&route.deny, "gemma").unwrap().clone();
        let shown = settings.models.show(&route, &gemma);
        assert_eq!(of(r#"{"model":"gemma"}"#), WithBody::Answer(shown.clone()));
        assert_eq!(of(r#"{"name":"gemma"}"#), WithBody::Answer(shown.clone()));
        assert_eq!(of(r#"{"model":"","name":"gemma"}"#), WithBody::Answer(shown));
        assert_eq!(reason(of(r#"{"model":"nobody"}"#)), "entry:model-unknown");
        assert_eq!(reason(of(r#"{"model":"shut"}"#)), "entry:model-closed");
        assert_eq!(reason(of(r#"{"model":"  "}"#)), "entry:no-model");
        assert_eq!(reason(of(r#"{"model":5}"#)), "entry:model-unknown");
        assert_eq!(reason(of(r#"{}"#)), "entry:no-model");
        assert_eq!(reason(of("not json")), "entry:no-model");
        assert_eq!(reason(of("[1]")), "entry:no-model");
        assert_eq!(reason(of("")), "entry:no-model");
    }
}
