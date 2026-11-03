//! The scout's API described as OpenAPI 3.1, from the table it answers by: a path the scout answers is in the description, and one it does not answer is not. Level 1 of the home rule: paths and methods, what each does, the query and body fields the scout's own code reads, the content types, who may call. The types of fields and the shapes of answers are not described yet, and the document says so in words: an empty schema would read as "no body", and that is untrue.

use crate::api::routes::{RouteKind, RouteRow};
use serde_json::{Map, Value, json};
use std::collections::BTreeSet;

/// The document.
pub struct ApiSpec;

impl ApiSpec {
    const NOT_DESCRIBED: &'static str = "Not described yet.";
    const TOKEN_HEADER: &'static str = "X-Caravan-Token";
    const JSON: &'static str = "application/json";
    const HTML: &'static str = "text/html";
    const FORM: &'static str = "multipart/form-data";
    const STREAM: &'static str = "text/event-stream";
    const SCHEME: &'static str = "fleetToken";
    const ABOUT: &'static str = "The API of caravan-scout, the sidecar of a machine in a LAMA CARAVAN fleet: the controller drives the machine's cells, engines and llama.cpp build through it. Written from the table the scout answers by, so a path is here exactly when the scout answers it. Types of fields and the shapes of answers are not described yet.";
    const SECURITY: &'static str = "The fleet token the controller hands a scout when the operator adds it on the board (`controllerToken` in config.json), sent as X-Caravan-Token. A scout that holds none is open, as a trusted LAN is; the page, /api/pairing, /api/health, this document and the machine's entry (/v1) are open either way.";

    /// The description of these rows.
    pub fn document(routes: &[RouteRow], version: &str) -> Value {
        let mut sorted: Vec<&RouteRow> = routes.iter().collect();
        sorted.sort_by_key(|route| (route.path(), route.method()));
        let mut paths = Map::new();
        for route in sorted {
            let row = paths.entry(route.path()).or_insert_with(|| json!({}));
            if let Value::Object(row) = row {
                row.insert(route.method().to_lowercase(), Self::operation(route));
            }
        }
        let tags: BTreeSet<String> = routes.iter().map(|route| route.word("tag")).collect();
        let tags: Vec<Value> = tags.iter().map(|tag| json!({"name": tag})).collect();
        json!({
            "openapi": "3.1.0",
            "info": {"title": "caravan-scout", "version": version, "description": Self::ABOUT},
            "tags": tags,
            "paths": paths,
            "components": {
                "securitySchemes": {Self::SCHEME: {"type": "apiKey", "in": "header", "name": Self::TOKEN_HEADER, "description": Self::SECURITY}},
                "schemas": {
                    "Error": {
                        "type": "object",
                        "required": ["error"],
                        "properties": {"error": {"type": "string"}},
                        "description": "A refusal or a failure: the status is the scout's own (400 a bad request, 404, 409…), or 500 for what it did not expect.",
                    },
                    "OpenAIError": {
                        "type": "object",
                        "required": ["error"],
                        "properties": {"error": {
                            "type": "object",
                            "required": ["message", "type"],
                            "properties": {"message": {"type": "string"}, "type": {"type": "string"}, "param": {"type": ["string", "null"]}, "code": {"type": ["string", "null"]}},
                        }},
                        "description": "A refusal of the machine's entry, in OpenAI's shape: 400 no `model` or a body that cannot be read, 404 `model_not_found`, 413, 502 `cell_unreachable`, 503 `model_not_running`.",
                    },
                },
            },
        })
    }

    fn operation(route: &RouteRow) -> Value {
        let mut op = Map::new();
        op.insert("operationId".to_string(), json!(Self::operation_id(route)));
        op.insert("summary".to_string(), json!(route.word("summary")));
        op.insert("tags".to_string(), json!([route.word("tag")]));
        let description = route.word("description");
        if !description.is_empty() {
            op.insert("description".to_string(), json!(description));
        }
        op.insert("security".to_string(), if route.needs_no_token() { json!([]) } else { json!([{Self::SCHEME: []}]) });
        let mut params: Vec<Value> = route.params().iter().map(|(name, said)| json!({"name": name, "in": "path", "required": true, "schema": {"type": "string"}, "description": said})).collect();
        params.extend(
            route.list("query").iter().map(
                |name| json!({"name": name, "in": "query", "required": false, "schema": {"description": Self::NOT_DESCRIBED}}),
            ),
        );
        if !params.is_empty() {
            op.insert("parameters".to_string(), Value::Array(params));
        }
        if route.kind() == RouteKind::Own {
            // Answered by the server itself: it reads the body ahead of the token gate, and the fleet token may ride in the body instead of the header.
            op.insert("x-caravan-token-in-body".to_string(), json!(true));
        }
        if route.reads_a_body() {
            op.insert("requestBody".to_string(), Self::request_body(route));
            if route.body_more() {
                op.insert("x-caravan-fields-complete".to_string(), json!(false));
            }
        }
        op.insert("responses".to_string(), Self::responses(route));
        Value::Object(op)
    }

    fn request_body(route: &RouteRow) -> Value {
        let properties: Map<String, Value> =
            route.list("body").into_iter().map(|name| (name, json!({"description": Self::NOT_DESCRIBED}))).collect();
        let schema = json!({"type": "object", "properties": properties});
        let mut content = Map::new();
        content.insert(Self::JSON.to_string(), json!({"schema": schema}));
        if route.is_entry() {
            // A recording comes as a form, its `model` a field of it, as OpenAI's API takes it.
            content.insert(Self::FORM.to_string(), json!({"schema": schema}));
        }
        json!({"required": false, "content": content})
    }

    fn responses(route: &RouteRow) -> Value {
        if route.is_entry() {
            return Self::entry_responses(route);
        }
        let ok = if route.kind() == RouteKind::Page {
            json!({"description": "The page.", "content": {Self::HTML: {"schema": {"type": "string"}}}})
        } else {
            json!({"description": format!("The answer. {}", Self::NOT_DESCRIBED), "content": {Self::JSON: {"schema": {"description": Self::NOT_DESCRIBED}}}})
        };
        let error = json!({"schema": {"$ref": "#/components/schemas/Error"}});
        let mut out = Map::new();
        out.insert("200".to_string(), ok);
        if !route.needs_no_token() {
            out.insert(
                "401".to_string(),
                json!({"description": "The scout holds a fleet token and none, or another, came in X-Caravan-Token: `{error: \"fleet token required (X-Caravan-Token)\"}`.", "content": {Self::JSON: error}}),
            );
        }
        out.insert(
            "default".to_string(),
            json!({"description": "A refusal or a failure: `{error}`.", "content": {Self::JSON: error}}),
        );
        Value::Object(out)
    }

    /// The machine's entry answers as OpenAI's API does: its list or model, a cell's answer as the cell gave it, refusals in OpenAI's error shape; never a 401.
    fn entry_responses(route: &RouteRow) -> Value {
        let refusal = json!({"description": "A refusal in OpenAI's shape: `{error: {message, type, param, code}}`.", "content": {Self::JSON: {"schema": {"$ref": "#/components/schemas/OpenAIError"}}}});
        let ok = if route.method() == "GET" {
            json!({"description": format!("The answer, in OpenAI's shape. {}", Self::NOT_DESCRIBED), "content": {Self::JSON: {"schema": {"description": Self::NOT_DESCRIBED}}}})
        } else {
            json!({"description": "The cell's answer, as the cell gave it: JSON, or a stream of server-sent events.", "content": {Self::JSON: {"schema": {"description": "The cell's own."}}, Self::STREAM: {"schema": {"type": "string"}}}})
        };
        json!({"200": ok, "default": refusal})
    }

    /// `getApiLlamaNodeStatus`, `postApiHeartbeat`, `getRoot`: unique because a path and a method are.
    fn operation_id(route: &RouteRow) -> String {
        let path = route.path();
        let words: Vec<&str> =
            path.split(|letter: char| !letter.is_ascii_alphanumeric()).filter(|word| !word.is_empty()).collect();
        let mut out = route.method().to_lowercase();
        if words.is_empty() {
            out.push_str("Root");
        }
        for word in words {
            let mut letters = word.chars();
            if let Some(first) = letters.next() {
                out.extend(first.to_uppercase());
                out.push_str(letters.as_str());
            }
        }
        out
    }
}
