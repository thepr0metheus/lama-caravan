//! The program against `contract/*.json`: a rule by one table of cases. Where the browser has the rule too, its test reads the same table.
// A test may stop where it found something wrong; clippy sees only `#[test]` bodies as tests, not their helpers.
#![allow(clippy::unwrap_used, clippy::panic, clippy::indexing_slicing)]

use rules::{
    AnthropicToChat, AnthropicUsage, Carried, ChatLevers, ChatToAnthropic, ChatToResponses, ChunkFold, ClientAddress, ClientDeny,
    Credentials, EffortFit, EntryModels, EntryRefusal, Keepalive, KeyEntry, KeyMiss, MayRead, MediaAnswer, MediaParts,
    MediaReader, ModelCatalogue, ModelKind, ModelLevels, ModelSchedules, OpenAiDialect, OpenAiError, Part, Pick, Picture, Policy,
    Pool, QueueLeave, Reader, Reading, RequestFields, RequestJson, RequestKind, RequestSummary, ResponseSummary,
    ResponsesPassthrough, ResponsesTally, ResponsesToChat, Route, RowKind, Source, StreamFold, StreamTranslator, Told,
    UpstreamFailure, UpstreamType, UsageReserve, UsageWindow, UsageWords, Verdict, WallClock, WeekWindows, Wired,
};
use serde_json::{Value, json};
use std::fs;
use std::path::PathBuf;

/// The tables' folder: beside `rust/`, or where `CARAVAN_CONTRACT_DIR` says for a copy of `rust/` that stands elsewhere, as a mutants'
/// run makes one.
fn folder() -> PathBuf {
    std::env::var_os("CARAVAN_CONTRACT_DIR")
        .map_or_else(|| PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../contract"), PathBuf::from)
}

fn table(name: &str) -> Value {
    let path = folder().join(format!("{name}.json"));
    serde_json::from_str(&fs::read_to_string(&path).unwrap_or_else(|error| panic!("{path:?}: {error}"))).unwrap()
}

/// The rows of a sub-table: one with nothing in it holds nothing to anything.
fn rows<'a>(data: &'a Value, name: &str) -> &'a Vec<Value> {
    let rows = data[name].as_array().unwrap_or_else(|| panic!("{name}: not a list"));
    assert!(!rows.is_empty(), "{name}: no cases");
    rows
}

fn text(value: &Value) -> Option<&str> {
    value.as_str()
}

#[test]
fn key_entry() {
    let data = table("key_entry");
    for row in rows(&data, "presented_key") {
        assert_eq!(KeyEntry::presented_key(text(&row["authorization"]), text(&row["x_api_key"])), row["key"], "{row}");
    }
    for row in rows(&data, "same") {
        assert_eq!(KeyEntry::same(row["left"].as_str().unwrap(), row["right"].as_str().unwrap()), row["same"], "{row}");
    }
    let routes: Vec<Route> = rows(&data["route_for"], "routes").iter().map(|raw| Route::normalize(raw).unwrap()).collect();
    for row in rows(&data["route_for"], "cases") {
        let answer = match KeyEntry::route_for(row["key"].as_str().unwrap(), &routes) {
            Ok(route) => route.label.clone(),
            Err(KeyMiss::NoKey) => "no-key".to_string(),
            Err(KeyMiss::UnknownKey) => "unknown-key".to_string(),
            Err(KeyMiss::AmbiguousKey) => "ambiguous-key".to_string(),
        };
        let want = row.get("label").or(row.get("miss")).unwrap();
        assert_eq!(answer, *want, "{row}");
    }
}

#[test]
fn model_kind() {
    for row in rows(&table("model_kind"), "serves") {
        let jobs: Vec<&str> = row["jobs"].as_array().unwrap().iter().map(|job| job.as_str().unwrap()).collect();
        assert_eq!(json!(ModelKind::of_jobs(&jobs).serves(row["path"].as_str().unwrap())), row["serves"], "{row}");
    }
}

#[test]
fn model_kind_pool_reads_one_row_at_a_time() {
    for row in rows(&table("model_kind"), "pool") {
        let kinds = row["rows"].as_array().unwrap().iter().map(|row| {
            if row.get("serves") == Some(&Value::Bool(false)) {
                RowKind::ServesNothing
            } else {
                row.get("kind").and_then(kind_from).map_or(RowKind::Silent, RowKind::Said)
            }
        });
        let answer = ModelKind::may_read(kinds, row["word"].as_str().unwrap());
        assert_eq!(may_read_json(&answer), row["answer"], "{row}");
    }
}

/// Standard base64, for a table's bytes: a test's own few lines, not a package.
fn base64_bytes(text: &str) -> Vec<u8> {
    const LETTERS: &[u8] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let mut out = Vec::new();
    let (mut held, mut bits) = (0u32, 0);
    for byte in text.bytes().filter(|byte| *byte != b'=') {
        held = (held << 6) | LETTERS.iter().position(|letter| *letter == byte).unwrap() as u32;
        bits += 6;
        if bits >= 8 {
            bits -= 8;
            out.push(((held >> bits) & 0xFF) as u8);
        }
    }
    out
}

#[test]
fn multipart() {
    for row in rows(&table("multipart"), "cases") {
        let body = base64_bytes(row["body"].as_str().unwrap());
        let got = RequestFields::form(row["ctype"].as_str().unwrap(), &body);
        assert_eq!(json!(got), row["fields"], "{}", row["id"]);
        let renamed = RequestFields::with_field(row["ctype"].as_str().unwrap(), body, "model", "a-row-s-model");
        assert_eq!(renamed, base64_bytes(row["renamed"].as_str().unwrap()), "{}", row["id"]);
    }
}

#[test]
fn model_named() {
    for row in rows(&table("model_named"), "cases") {
        let body = row["body"].as_str().unwrap().as_bytes().to_vec();
        let kind = row.get("type").and_then(Value::as_str).unwrap_or("application/json");
        let got = RequestFields::model_named(body.clone(), row["model"].as_str().unwrap(), kind);
        match row.get("becomes") {
            Some(want) => assert_eq!(&serde_json::from_slice::<Value>(&got).unwrap(), want, "{row}"),
            None => assert_eq!(got, body, "{row}"),
        }
    }
}

#[test]
fn upstream_type() {
    for row in rows(&table("upstream_type"), "of") {
        assert_eq!(UpstreamType::of(&row["output"]).word(), row["word"], "{row}");
    }
}

#[test]
fn request_kind() {
    for row in rows(&table("request_kind"), "cases") {
        let (method, path) = (row["method"].as_str().unwrap(), row["path"].as_str().unwrap());
        assert_eq!(RequestKind::is_inference(method, path), row["inference"], "{row}");
        assert_eq!(RequestKind::is_chat(path), row["chat"], "{row}");
    }
}

#[test]
fn client_address() {
    for row in rows(&table("client_address"), "cases") {
        let sender = ClientAddress::of(row["peer"].as_str().unwrap(), text(&row["forwarded"]), text(&row["real_ip"]));
        assert_eq!(sender, row["sender"], "{row}");
    }
}

fn route_in_table_words(route: &Route) -> Value {
    json!({
        "id": route.id, "label": route.label, "kind": route.kind, "deny": route.deny.keys().collect::<Vec<_>>(),
        "upstreamHost": route.upstream_host, "upstreamPort": route.upstream_port, "enabled": route.enabled, "mode": route.mode,
        "apiKey": route.api_key, "priority": route.priority,
        "clientTimeoutSeconds": route.client_timeout_seconds, "contextLength": route.context_limit, "contextAuto": route.context_auto,
    })
}

#[test]
fn route() {
    for row in rows(&table("route"), "normalize") {
        let got = Route::normalize(&row["raw"]).as_ref().map_or(Value::Null, route_in_table_words);
        assert_eq!(got, row["route"], "{row}");
    }
}

#[test]
fn policy() {
    let data = table("policy");
    for row in rows(&data, "read") {
        let policy = Policy::read(Some(&row["raw"]));
        let got = json!({
            "maxSlots": policy.max_slots, "loadingModelWaitSec": policy.loading_model_wait_sec, "queueYieldSec": policy.queue.yield_sec,
            "queueLimitSec": policy.queue.limit_sec, "clientTimeoutSec": policy.queue.client_timeout_sec,
        });
        assert_eq!(got, row["policy"], "{row}");
    }
    for row in rows(&data, "client_timeout") {
        let policy = Policy::read(Some(&row["raw"]));
        assert_eq!(policy.queue.client_timeout(row["own"].as_i64().unwrap()), row["seconds"], "{row}");
    }
    for row in rows(&data, "leave") {
        let leave = QueueLeave::at_admission(&Policy::read(Some(&row["raw"])), row["way_on"].as_bool().unwrap());
        assert_eq!(
            json!({"after": leave.after, "to": leave.to.word(), "limit": leave.limit}),
            json!({"after": row["after"], "to": row["to"], "limit": row["limit"]}),
            "{row}"
        );
        let (at, to) = leave.said(1000.0);
        assert_eq!(json!({"leaveAt": at, "leaveTo": to}), row["said_since_1000"], "{row}");
        for pair in row["due"].as_array().unwrap() {
            assert_eq!(leave.due(pair[0].as_f64().unwrap()), pair[1], "{row}");
        }
        let away = leave.without_way();
        assert_eq!(json!({"after": away.after, "to": away.to.word(), "limit": away.limit}), row["without_way"], "{row}");
    }
}

fn error_of(row: &Value) -> OpenAiError {
    let args = row["args"].as_array().unwrap();
    match row["make"].as_str().unwrap() {
        "broken_body" => OpenAiError::broken_body(args[0].as_str().unwrap()),
        "paused" => OpenAiError::paused(),
        "no_key" => OpenAiError::no_key(),
        "wrong_key" => OpenAiError::wrong_key(args[0].as_str().unwrap()),
        "shared_key" => OpenAiError::shared_key(),
        "unknown_model" => OpenAiError::unknown_model(args[0].as_str().unwrap()),
        "no_model" => OpenAiError::no_model(),
        "invalid_url" => OpenAiError::invalid_url(args[0].as_str().unwrap(), args[1].as_str().unwrap()),
        "unreadable" => OpenAiError::unreadable(),
        "no_pool" => OpenAiError::no_pool(),
        "not_allowed" => OpenAiError::not_allowed(args[0].as_str().unwrap()),
        "not_running" => OpenAiError::not_running(args[0].as_str().unwrap()),
        "limit" => OpenAiError::limit(args[0].as_str().unwrap(), args[1].as_u64().unwrap()),
        "upstream" => OpenAiError::upstream(
            u16::try_from(args[0].as_u64().unwrap()).unwrap(),
            args[1].as_str().unwrap(),
            args[2].as_str().unwrap(),
            Some(&args[3]),
        ),
        other => panic!("the table names a maker this test does not know: {other}"),
    }
}

fn pairs(headers: &[(&str, String)]) -> Value {
    json!(headers.iter().map(|(name, value)| [name.to_string(), value.clone()]).collect::<Vec<_>>())
}

#[test]
fn openai_error() {
    let data = table("openai_error");
    for row in rows(&data, "errors") {
        let error = error_of(row);
        assert_eq!(error.status, row["status"], "{row}");
        assert_eq!(error.payload(), row["payload"], "{row}");
        assert_eq!(pairs(&error.headers()), row["headers"], "{row}");
        assert_eq!(serde_json::from_slice::<Value>(&error.body()).unwrap(), row["payload"], "{row}");
    }
    for pair in rows(&data, "duration") {
        assert_eq!(OpenAiError::duration(pair[0].as_u64().unwrap()), pair[1], "{pair}");
    }
    for pair in rows(&data, "clean_code") {
        assert_eq!(json!(OpenAiError::clean_code(Some(&pair[0]))), pair[1], "{pair}");
    }
}

fn told_in_table_words(told: &Told) -> Value {
    json!({"told": told.status, "payload": serde_json::from_slice::<Value>(&told.body).unwrap(), "headers": pairs(&told.headers)})
}

#[test]
fn dialect() {
    let data = table("dialect");
    let dialect = OpenAiDialect::new(data["model"].as_str().unwrap());
    for row in rows(&data, "failure") {
        let told = dialect.failure(u16::try_from(row["status"].as_u64().unwrap()).unwrap(), row["kind"].as_str().unwrap());
        assert_eq!(
            told_in_table_words(&told),
            json!({"told": row["told"], "payload": row["payload"], "headers": row["headers"]}),
            "{row}"
        );
    }
    for row in rows(&data, "stream_failure") {
        assert_eq!(dialect.stream_failure(row["kind"].as_str().unwrap()), row["payload"], "{row}");
    }
    for row in rows(&data, "answer_error") {
        let told = dialect.answer_error(
            u16::try_from(row["status"].as_u64().unwrap()).unwrap(),
            row["reason"].as_str().unwrap(),
            Some(&row["code"]),
        );
        assert_eq!(
            told_in_table_words(&told),
            json!({"told": row["told"], "payload": row["payload"], "headers": row["headers"]}),
            "{row}"
        );
    }
    for pair in rows(&data, "header_ok") {
        assert_eq!(OpenAiDialect::header_ok(pair[0].as_str().unwrap()), pair[1], "{pair}");
    }
}

#[test]
fn upstream_failure() {
    let data = table("upstream_failure");
    for row in rows(&data, "summary") {
        let (reason, kind) =
            UpstreamFailure::summary(u16::try_from(row["status"].as_u64().unwrap()).unwrap(), row["body"].as_str().unwrap());
        assert_eq!((json!(reason), json!(kind)), (row["reason"].clone(), row["kind"].clone()), "{row}");
    }
    for pair in rows(&data, "is_dead_status") {
        assert_eq!(UpstreamFailure::is_dead_status(u16::try_from(pair[0].as_u64().unwrap()).unwrap()), pair[1], "{pair}");
    }
    for row in rows(&data, "code") {
        assert_eq!(json!(UpstreamFailure::code(row["body"].as_str().unwrap())), row["code"], "{row}");
    }
}

fn read_back(out: Option<Vec<u8>>) -> Value {
    out.map_or(Value::Null, |bytes| serde_json::from_slice(&bytes).unwrap())
}

#[test]
fn levers() {
    let data = table("levers");
    for row in rows(&data, "for_cell") {
        let out = ChatLevers::for_cell(row["body"].as_str().unwrap().as_bytes(), row["path"].as_str().unwrap());
        assert_eq!(read_back(out), row["result"], "{row}");
    }
    for row in rows(&data, "keepalive") {
        let sent = Keepalive::bytes(row["model"].as_str().unwrap(), row["payload"]["created"].as_i64().unwrap());
        let text = String::from_utf8(sent).unwrap();
        let json_text = text.strip_prefix("data: ").unwrap().strip_suffix("\n\n").unwrap();
        assert_eq!(serde_json::from_str::<Value>(json_text).unwrap(), row["payload"], "{row}");
    }
}

#[test]
fn summaries() {
    let data = table("summaries");
    for row in rows(&data, "request") {
        let sent = row["body"].as_str().unwrap();
        let body = if row.get("preview").is_some() { sent.replace("PREVIEW", &"x".repeat(200)) } else { sent.to_string() };
        let mut got = RequestSummary::of(body.as_bytes(), row["content_type"].as_str().unwrap());
        if got.get("parseError").is_some() {
            got["parseError"] = json!(true);
        }
        let mut want = row["summary"].clone();
        if row.get("length_is_bytes").is_some() {
            want["contentLength"] = json!(body.len());
        }
        assert_eq!(got, want, "{row}");
    }
    for row in rows(&data, "response") {
        assert_eq!(ResponseSummary::of(&row["payload"]), row["summary"], "{row}");
    }
    for row in rows(&data, "usage") {
        assert_eq!(UsageWords::of(Some(&row["said"])), row["usage"], "{row}");
    }
    for row in rows(&data, "stream") {
        let mut fold = StreamFold::default();
        for line in row["lines"].as_array().unwrap() {
            fold.add_line(line.as_str().unwrap().as_bytes());
        }
        for _ in 0..row.get("past_cap").and_then(Value::as_u64).unwrap_or(0) {
            fold.line_past_cap();
        }
        assert_eq!(fold.live_json(), row["live"], "{row}");
        assert_eq!(fold.as_json(), row["finished"], "{row}");
    }
}

const CHAT: &str = "/v1/chat/completions";

fn routers_of(outputs: &Value) -> Value {
    json!([{"id": "router:default", "outputs": outputs}])
}

#[test]
fn entry_models() {
    let data = table("entry_models");
    let routers = routers_of(&data["outputs"]);
    let reading = |cloud: Option<&Value>| {
        let catalogue = ModelCatalogue::read(Some(&data["catalogue"]));
        EntryModels::read(Some(&routers), cloud, &Credentials::read(Some(&data["secrets"])), catalogue)
    };
    let models = reading(Some(&data["cloud"]));
    assert!(models.sure());
    for row in rows(&data, "cases") {
        let deny = ClientDeny::clean(row.get("deny"));
        let wanted = row["wanted"].as_str().unwrap();
        let picked = models.pick(&deny, wanted).map(|pool| pool.id.clone());
        assert_eq!(json!(picked), row["picked"], "the list's pick: {row}");
        match models.for_request(&deny, wanted, row.get("path").and_then(Value::as_str).unwrap_or(CHAT)) {
            Pick::Pool(pool) => assert_eq!(json!(pool.id), row["pool"], "{row}"),
            Pick::Refused(refusal) => assert_eq!(json!(refusal.reason), row["refused"], "{row}"),
            Pick::Unsure => panic!("the files read, and the code said it cannot tell: {row}"),
        }
    }
    for row in rows(&data, "refusals") {
        let deny = ClientDeny::clean(row.get("deny"));
        let wanted = row["wanted"].as_str().unwrap();
        assert_eq!(json!(models.closed(&deny, wanted)), row["closed"], "{row}");
        assert_eq!(json!(models.stopped(wanted)), row["stopped"], "{row}");
    }
    // A pool is asked row by row: the row that serves the request decides, not the pool's shared promise. A case may name the
    // board's reader (`board_reader`): the reading is then the table's cloud with that name kept as the file keeps it.
    for row in rows(&data, "media") {
        let deny = ClientDeny::clean(row.get("deny"));
        let pool = Pool::read_one(&json!({"id": "media", "name": "media", "steps": row["rows"]})).unwrap();
        let mut cloud = data["cloud"].clone();
        if let Some(reader) = row.get("board_reader") {
            cloud[EntryModels::READER_FIELD] = reader.clone();
        }
        let answer = reading(Some(&cloud)).media(&deny, &pool, &json!({"messages": row["messages"]}));
        assert_eq!(json!(matches!(answer, MediaAnswer::Refused(_))), row["refused"], "{row}");
        assert_eq!(json!(matches!(answer, MediaAnswer::Readable(_))), *row.get("read").unwrap_or(&json!(false)), "{row}");
    }
    for row in rows(&data, "lists") {
        let mut raw = row["route"].clone();
        raw.as_object_mut().unwrap().extend([("id".to_string(), json!("client-1")), ("kind".to_string(), json!("consumer"))]);
        let route = Route::normalize(&raw).unwrap();
        let got: Vec<Value> = models.models(&route.deny).into_iter().map(|pool| models.model_object(&route, pool, 0)).collect();
        assert_eq!(got.len(), row["want"].as_array().unwrap().len(), "{}", row["route"]);
        for (got, want) in got.iter().zip(row["want"].as_array().unwrap()) {
            assert_eq!(got, want, "{}", row["route"]);
            // The order of the fields counts too: a client sees the same text but for its spaces.
            let keys = |value: &Value| value.as_object().unwrap().keys().cloned().collect::<Vec<_>>();
            assert_eq!(keys(got), keys(want));
        }
        let listed = models.list(&route, 0);
        assert_eq!(listed["object"], json!("list"));
        assert_eq!(listed["data"], row["want"], "{}", row["route"]);
    }
    for row in rows(&data, "unsure") {
        let cloud = (!row["cloud"].is_null()).then_some(&row["cloud"]);
        let unsure = reading(cloud);
        assert!(!unsure.sure(), "{row}");
        assert_eq!(unsure.for_request(&ClientDeny::default(), "gemma", CHAT), Pick::Unsure, "{row}");
    }
    assert!(matches!(models.for_request(&ClientDeny::default(), "gemma", CHAT), Pick::Pool(_)));
}

fn words(items: &[Value]) -> Vec<&str> {
    items.iter().map(|item| item.as_str().unwrap()).collect()
}

fn part_json(part: &Part) -> Value {
    json!({"message": part.message, "index": part.index, "word": part.word})
}

/// A `Verdict` as the table writes it. The words of the states are the table's, so a state renamed here goes red there.
fn verdict_json(answer: &Verdict) -> Value {
    match answer {
        Verdict::Goes => json!("goes"),
        Verdict::NotSaid => json!("not said"),
        Verdict::Reading(part, reader) => json!({"reading": part_json(part), "reader": reader_json(reader)}),
        Verdict::NotDecided(part) => json!({"not decided": part_json(part)}),
    }
}

/// A wiring's answer as the table writes it: the state named as itself, with the name it names. The state's name is the
/// rule's own word (`Reader::word`), so the table, the guard and the board read one list of answers and not a copy of it.
fn reader_json(reader: &Reader) -> Value {
    let word = reader.word();
    match reader {
        // An answer with no name: the state is the whole answer.
        Reader::Reads | Reader::Nothing => json!(word),
        Reader::Unknown(name) | Reader::NotSaid(name) | Reader::Itself(name) => {
            Value::Object(serde_json::Map::from_iter([(word, json!(name))]))
        }
        Reader::CannotTake(name, taken) => {
            Value::Object(serde_json::Map::from_iter([(word, json!(name)), ("word".to_string(), json!(taken))]))
        }
    }
}

/// The wiring as the table writes it: `null` is nothing named; a name with `known: false` is a name the caravan does not
/// have; a name with no `takes` is a name whose facts say nothing of their inputs; `pool` is the pool the wiring is for,
/// which is what tells a name from a self-naming. The table writes the facts, not the answer, and the wiring is built the
/// way the entry builds it — through `Wired::of`.
fn wired_of(said: &Value, for_pool: Option<&str>) -> Wired {
    match said {
        Value::Null => Wired::Nothing,
        Value::Object(row) => Wired::of(
            row["name"].as_str().unwrap(),
            row.get("known") == Some(&json!(true)),
            row.get("takes").and_then(words_of),
            for_pool,
        ),
        _ => panic!("the wiring is a name or nothing: {said}"),
    }
}

/// What the table says a name promises; `null` is the absence of a promise, which is not a promise of nothing.
fn words_of(list: &Value) -> Option<Vec<String>> {
    Some(list.as_array()?.iter().map(|word| word.as_str().unwrap().to_string()).collect())
}

/// A `MayRead` as the table writes it.
fn may_read_json(answer: &MayRead) -> Value {
    match answer {
        MayRead::Takes => json!("takes"),
        MayRead::Unsaid => json!("unsaid"),
        MayRead::Cannot => json!("cannot"),
        MayRead::NoRow => json!("no row"),
    }
}

/// A kind as the table writes it: its jobs and the inputs it promises; `null` is a row that says nothing.
fn kind_from(said: &Value) -> Option<ModelKind> {
    let said = said.as_object()?;
    Some(ModelKind::of_words(&words(said["jobs"].as_array().unwrap()), &words(said["inputs"].as_array().unwrap())))
}

/// The promise a row names, as the table writes it: `null` is a row that says nothing of itself, and `takes()` answers `None` for it.
fn kind_of(row: &Value) -> Option<ModelKind> {
    kind_from(row.get("kind")?)
}

#[test]
fn media_parts() {
    let data = table("media_parts");
    for row in rows(&data, "modality") {
        assert_eq!(json!(MediaParts::modality(&row["part"])), row["word"], "{row}");
    }
    for row in rows(&data, "carried") {
        let carried = Carried::of(row["messages"].as_array().unwrap());
        assert_eq!(json!(carried.parts.iter().map(part_json).collect::<Vec<Value>>()), row["parts"], "{row}");
    }
    for row in rows(&data, "verdict") {
        let carried = Carried::of(row["messages"].as_array().unwrap());
        let kind = kind_of(row);
        let answer =
            carried.verdict(kind.as_ref().and_then(ModelKind::takes), &wired_of(row.get("reader").unwrap_or(&Value::Null), None));
        assert_eq!(verdict_json(&answer), row["answer"], "{row}");
    }
    for row in rows(&data, "says") {
        let carried = Carried::of(row["messages"].as_array().unwrap());
        assert_eq!(json!(carried.parts[0].says()), row["says"], "{row}");
    }
}

#[test]
fn media_reader() {
    let data = table("media_reader");
    for row in rows(&data, "wired") {
        let wired = wired_of(row.get("reader").unwrap_or(&Value::Null), row.get("for_pool").and_then(Value::as_str));
        assert_eq!(reader_json(&wired.promise(row["word"].as_str().unwrap())), row["answer"], "{row}");
    }
    for row in rows(&data, "names") {
        // The reading the door asks the rule from: the board's, with the routers that say which name is a machine's model
        // and the keys that say which account is signed in. A name being known is what this reading answers; the case does
        // not write it in.
        let board = &row["board"];
        let routers = routers_of(&board["outputs"]);
        let models = EntryModels::read(
            Some(&routers),
            Some(&board["cloud"]),
            &Credentials::read(Some(&board["secrets"])),
            ModelCatalogue::default(),
        );
        let refusal = models.can_write(row["wanted"].as_str().unwrap());
        assert_eq!(json!(refusal.is_some()), row["refused"], "{row}");
        if refusal.is_none() {
            continue;
        }
        let refusal = refusal.unwrap();
        assert_eq!(json!(refusal.error.code), row["code"], "{row}");
        assert_eq!(json!(refusal.error.message), row["answer"], "{row}");
    }
    for row in rows(&data, "caption") {
        // The pool a wiring is for changes what the name answers, not what a caption looks like: the table's caption and key
        // cases name no pool, and the key has no field for one.
        let reader = MediaReader::new(row["reader"].as_str().unwrap(), Wired::PROMPT_VERSION, None);
        assert_eq!(json!(reader.caption(row["text"].as_str().unwrap())), row["caption"], "{row}");
    }
    for row in rows(&data, "key") {
        let reader = MediaReader::new(row["reader"].as_str().unwrap(), Wired::PROMPT_VERSION, None);
        assert_eq!(json!(reader.key(row["part"].as_str().unwrap())), row["key"], "{row}");
    }
    for row in rows(&data, "words") {
        // The words come from the answer the rule gave: the part is read through the classifier, not written here.
        let carried = Carried::of(row["messages"].as_array().unwrap());
        let kind = kind_of(row);
        let answer = carried.verdict(
            kind.as_ref().and_then(ModelKind::takes),
            &wired_of(row.get("reader").unwrap_or(&Value::Null), row["model"].as_str()),
        );
        let refusal = EntryRefusal::media(row["model"].as_str().unwrap(), &answer);
        assert_eq!(json!(refusal.is_some()), row["refused"], "{row}");
        if refusal.is_none() {
            continue;
        }
        let refusal = refusal.unwrap();
        assert_eq!(json!(refusal.reason), row["reason"], "{row}");
        assert_eq!(json!(refusal.error.status), row["status"], "{row}");
        assert_eq!(json!(refusal.error.code), row["code"], "{row}");
        assert_eq!(json!(refusal.error.param), row["param"], "{row}");
        assert_eq!(json!(refusal.error.message), row["message"], "{row}");
    }
}

/// A picture as the table says it: the client's numbers, where its bytes are, and the `data:` URL when they are inside.
fn picture_json(picture: &Picture) -> Value {
    let mut said = json!({"message": picture.part.message, "index": picture.part.index});
    match &picture.source {
        Source::Inside(url) => {
            said["source"] = json!("inside");
            said["url"] = json!(url);
        }
        Source::Elsewhere => said["source"] = json!("elsewhere"),
    }
    said
}

#[test]
fn media_reading() {
    let data = table("media_reading");
    let reading_of = |payload: &Value| {
        Reading::of(payload, MediaReader::new("gpt-sub", Wired::PROMPT_VERSION, Some("coder-auto")), "coder-auto")
    };
    for row in rows(&data, "pictures") {
        let said: Vec<Value> = reading_of(&row["payload"]).pictures.iter().map(picture_json).collect();
        assert_eq!(json!(said), row["pictures"], "{row}");
    }
    for row in rows(&data, "elsewhere") {
        let refusal = reading_of(&row["payload"]).elsewhere();
        assert_eq!(json!(refusal.is_some()), row["refused"], "{row}");
        let Some(refusal) = refusal else {
            continue;
        };
        assert_eq!(json!(refusal.error.status), row["status"], "{row}");
        assert_eq!(json!(refusal.error.code), row["code"], "{row}");
        assert_eq!(json!(refusal.error.param), row["param"], "{row}");
        assert_eq!(json!(refusal.reason), row["reason"], "{row}");
        assert_eq!(json!(refusal.error.message), row["message"], "{row}");
    }
    for row in rows(&data, "question") {
        let reading = reading_of(&row["payload"]);
        let picture = &reading.pictures[row["picture"].as_u64().unwrap() as usize];
        let mut asked = json!(reading.question(picture));
        // The words are said once, beside their version: the table names them, and the program's are the ones asked.
        if let Some(words) = asked.pointer_mut("/messages/0/content/0/text") {
            assert_eq!(*words, json!(Wired::PROMPT), "{row}");
            *words = json!("<the words of this version>");
        }
        assert_eq!(asked, row["question"], "{row}");
    }
    for row in rows(&data, "words") {
        let said = match Reading::words(row["status"].as_u64().unwrap() as u16, row["body"].as_str().unwrap().as_bytes()) {
            Ok(words) => json!({"words": words}),
            Err(why) => json!({"no": why}),
        };
        assert_eq!(said, row["said"], "{row}");
    }
    for row in rows(&data, "rewritten") {
        let captions: Vec<String> =
            row["captions"].as_array().unwrap().iter().map(|words| words.as_str().unwrap().to_string()).collect();
        assert_eq!(json!(reading_of(&row["payload"]).rewritten(&row["payload"], &captions)), row["rewritten"], "{row}");
    }
    for row in rows(&data, "failed") {
        let reading = reading_of(&row["payload"]);
        let refusal =
            reading.failed(&reading.pictures[row["picture"].as_u64().unwrap() as usize], row["because"].as_str().unwrap());
        assert_eq!(json!(refusal.error.status), row["status"], "{row}");
        assert_eq!(json!(refusal.error.code), row["code"], "{row}");
        assert_eq!(json!(refusal.reason), row["reason"], "{row}");
        assert_eq!(json!(refusal.error.message), row["message"], "{row}");
    }
}

#[test]
fn media_reader_board() {
    let data = table("media_reader_board");
    for row in rows(&data, "answers") {
        // The negative case names no facts: there is nothing to ask the rule about, and that is what makes it the word the
        // table cannot say. It is held by scripts/check_media_reader_board.py and pinned by scripts/test_js_reader_block.py.
        let Some(facts) = row.get("reader") else {
            continue;
        };
        let wired = wired_of(facts, row.get("for_pool").and_then(Value::as_str));
        let answer = wired.promise(row["asked"].as_str().unwrap());
        assert_eq!(json!(answer.word()), row["answer"], "{row}");
        assert_eq!(json!(answer.writes()), row["writes"], "{row}");
    }
}

#[test]
fn request_json() {
    let data = table("request_json");
    for row in rows(&data, "cases") {
        let read = RequestJson::read(row["text"].as_str().unwrap().as_bytes()).filter(Value::is_object);
        assert_eq!(json!(read.is_some()), row["reads"], "{row}");
        if let Some(fields) = read {
            assert_eq!(fields["model"], row["model"], "{row}");
        }
    }
}

#[test]
fn ollama_s_answer_says_the_window_the_list_says() {
    let data = table("entry_models");
    let routers = routers_of(&data["outputs"]);
    let catalogue = ModelCatalogue::read(Some(&data["catalogue"]));
    let models = EntryModels::read(Some(&routers), Some(&data["cloud"]), &Credentials::read(Some(&data["secrets"])), catalogue);
    let route = Route::normalize(&json!({"id": "client-1", "kind": "consumer"})).unwrap();
    let windowed = models.pick(&route.deny, "seer").unwrap();
    let shown = models.show(&route, windowed);
    assert_eq!(shown["parameters"], json!("num_ctx 8192"));
    assert_eq!(shown["model_info"], json!({"general.architecture": "caravan", "caravan.context_length": 8192}));
    assert_eq!(shown["details"]["families"], json!(["caravan"]));
    let silent = models.pick(&route.deny, "gemma").unwrap();
    let shown = models.show(&route, silent);
    assert_eq!(shown["parameters"], json!(""));
    assert_eq!(shown["model_info"], json!({"general.architecture": "caravan"}));
}

fn override_of(row: &Value) -> Option<&str> {
    row["override"].as_str()
}

fn body_of(row: &Value) -> &[u8] {
    row["body"].as_str().unwrap().as_bytes()
}

fn lines_of(row: &Value) -> Vec<&str> {
    row["lines"].as_array().unwrap().iter().map(|line| line.as_str().unwrap()).collect()
}

#[test]
fn translate_chat_to_responses() {
    let data = table("translate");
    for row in rows(&data, "chat_to_responses") {
        let (sent, model) = ChatToResponses::body(body_of(row), override_of(row)).unwrap();
        assert_eq!(json!(model), row["model"], "{row}");
        if row.get("unchanged").is_some() {
            assert_eq!(sent, body_of(row), "{row}");
        } else {
            assert_eq!(serde_json::from_slice::<Value>(&sent).unwrap(), row["sends"], "{row}");
        }
    }
    for row in rows(&data, "responses_passthrough") {
        let (sent, model, stream) = ResponsesPassthrough::body(body_of(row), override_of(row));
        assert_eq!(serde_json::from_slice::<Value>(&sent).unwrap(), row["sends"], "{row}");
        assert_eq!((json!(model), json!(stream)), (row["model"].clone(), row["stream"].clone()), "{row}");
    }
    for row in rows(&data, "is_responses") {
        let got = ResponsesPassthrough::is_request(row["path"].as_str().unwrap(), body_of(row));
        assert_eq!(json!(got), row["is"], "{row}");
    }
}

#[test]
fn translate_responses_stream() {
    let data = table("translate");
    for row in rows(&data, "responses_stream") {
        let mut stream = ResponsesToChat::new("cc", "the-model", 1000);
        let mut frames = vec![String::from_utf8(stream.opening()).unwrap()];
        for line in lines_of(row) {
            frames.extend(stream.line(line.as_bytes()).map(|frame| String::from_utf8(frame).unwrap()));
            if stream.ended() {
                break;
            }
        }
        frames.push(String::from_utf8(stream.closing().to_vec()).unwrap());
        assert_eq!(json!(frames), row["frames"], "{}", row["lines"]);
    }
    for row in rows(&data, "responses_tally") {
        let mut tally = ResponsesTally::default();
        for line in lines_of(row) {
            tally.line(line.as_bytes());
        }
        assert_eq!(tally.as_summary(), row["summary"], "{}", row["lines"]);
    }
}

#[test]
fn translate_chat_to_anthropic() {
    for row in rows(&table("translate"), "chat_to_anthropic") {
        let sent = ChatToAnthropic::body(body_of(row), override_of(row)).unwrap();
        if row.get("unchanged").is_some() {
            assert_eq!(sent, body_of(row), "{row}");
        } else {
            assert_eq!(serde_json::from_slice::<Value>(&sent).unwrap(), row["sends"], "{row}");
        }
    }
}

#[test]
fn translate_anthropic_answers() {
    let data = table("translate");
    for row in rows(&data, "anthropic_stream") {
        let mut stream = AnthropicToChat::new("cc", "the-model", 1000);
        let mut frames = vec![String::from_utf8(stream.opening()).unwrap()];
        for line in lines_of(row) {
            frames.extend(stream.line(line.as_bytes()).map(|frame| String::from_utf8(frame).unwrap()));
            if stream.ended() {
                break;
            }
        }
        frames.push(String::from_utf8(stream.closing().to_vec()).unwrap());
        assert_eq!(json!(frames), row["frames"], "{}", row["lines"]);
        assert_eq!(stream.used().openai(), row["used"], "{}", row["lines"]);
        assert_eq!(json!(stream.used().known()), row["known"], "{}", row["lines"]);
    }
    for row in rows(&data, "anthropic_whole") {
        let got = AnthropicToChat::whole(body_of(row), "cc", "the-model", 1000);
        if row.get("unchanged").is_some() {
            assert_eq!(got, body_of(row), "{row}");
        } else {
            assert_eq!(serde_json::from_slice::<Value>(&got).unwrap(), row["answer"], "{row}");
        }
    }
    for row in rows(&data, "anthropic_usage") {
        let mut used = AnthropicUsage::default();
        for step in row["steps"].as_array().unwrap() {
            used.take(Some(step));
        }
        assert_eq!((used.openai(), json!(used.known())), (row["openai"].clone(), row["known"].clone()), "{row}");
    }
}

#[test]
fn chunk_fold() {
    for row in rows(&table("translate"), "chunk_fold") {
        let mut fold = ChunkFold::default();
        for piece in row["chunks"].as_array().unwrap() {
            fold.add(piece.as_str().unwrap().as_bytes());
        }
        assert_eq!(
            (json!(fold.finished()), fold.completion()),
            (row["finished"].clone(), row["completion"].clone()),
            "{}",
            row["chunks"]
        );
    }
}

#[test]
fn levers_said_to_a_model_that_does_not_take_them() {
    let chosen = ChatLevers::nearest_effort("none", &["low", "medium", "high"]);
    assert_eq!(chosen, Some("low"));
    assert_eq!(ChatLevers::nearest_effort("medium", &["low", "high"]), Some("low"), "of two as near, the lower");
    assert_eq!(ChatLevers::nearest_effort("odd", &["low"]), None);
    assert_eq!(ChatLevers::nearest_effort("low", &["odd"]), None);
}

/// The clock the schedule's table is written on: UTC, with Monday 1970-01-05 at epoch 345600.
struct UtcClock;

impl UtcClock {
    const MONDAY: i64 = 345_600;
    const WEEK: i64 = 7 * 1440 * 60;

    fn week_start(epoch: f64) -> i64 {
        Self::MONDAY + (epoch as i64 - Self::MONDAY).div_euclid(Self::WEEK) * Self::WEEK
    }
}

impl WallClock for UtcClock {
    fn minute_of_week(&self, epoch: f64) -> i64 {
        (epoch as i64 - Self::week_start(epoch)).div_euclid(60)
    }

    fn epoch_of_week_minute(&self, epoch: f64, minute: i64) -> i64 {
        Self::week_start(epoch) + minute * 60
    }

    fn text(&self, epoch: i64) -> String {
        format!("at {epoch}")
    }
}

fn windows_of(raw: &Value) -> Vec<UsageWindow> {
    raw.as_array()
        .unwrap()
        .iter()
        .map(|window| UsageWindow {
            seconds: window["seconds"].as_i64().unwrap(),
            used_pct: window["usedPct"].as_i64().unwrap(),
            reset_at: window["resetAt"].as_i64(),
        })
        .collect()
}

fn windows_json(windows: &[UsageWindow]) -> Value {
    json!(windows.iter().map(UsageWindow::as_json).collect::<Vec<_>>())
}

#[test]
fn usage_windows_and_levels() {
    let data = table("limits");
    for row in rows(&data, "usage_headers") {
        let lower: Vec<(String, String)> = row["headers"]
            .as_object()
            .unwrap()
            .iter()
            .map(|(name, value)| (name.to_lowercase(), value.as_str().unwrap().to_string()))
            .collect();
        let got = UsageWindow::from_headers(|name| lower.iter().find(|(said, _)| said == name).map(|(_, value)| value.clone()));
        assert_eq!(windows_json(&got), row["windows"], "{row}");
    }
    for row in rows(&data, "usage_page") {
        assert_eq!(windows_json(&UsageWindow::from_usage_page(&row["page"])), row["windows"], "{row}");
    }
    for row in rows(&data, "reserve") {
        let hit = UsageReserve::normalize(Some(&row["raw"])).verdict(&windows_of(&row["windows"]), row["now"].as_f64().unwrap());
        assert_eq!(hit.map_or(Value::Null, |hit| hit.as_json()), row["hit"], "{row}");
    }
    let levels = ModelLevels::read(Some(&data["levels_document"]));
    for row in rows(&data, "levels") {
        let (stop, switch) = levels.of(row["account"].as_str().unwrap(), row["model"].as_str().unwrap());
        assert_eq!(
            (stop, switch),
            (UsageReserve::normalize(Some(&row["stop"])), UsageReserve::normalize(Some(&row["switch"]))),
            "{row}"
        );
    }
}

#[test]
fn schedules() {
    let data = table("limits");
    for row in rows(&data, "schedule") {
        let said = WeekWindows::clean(Some(&row["windows"])).state(row["now"].as_f64().unwrap(), &UtcClock);
        assert_eq!((json!(said.open), json!(said.opens_at)), (row["open"].clone(), row["opensAt"].clone()), "{row}");
    }
    let schedules = ModelSchedules::read(Some(&data["schedules_document"]));
    for row in rows(&data, "closed") {
        let closed = schedules.closed(row["key"].as_str().unwrap(), row["now"].as_f64().unwrap(), &UtcClock);
        let got = closed.map_or(Value::Null, |opens_at| json!({"opensAt": opens_at}));
        assert_eq!(got, row["closed"], "{row}");
    }
}

#[test]
fn effort_fit() {
    let data = table("limits");
    for row in rows(&data, "effort_offered") {
        assert_eq!(
            json!(EffortFit::offered(row["status"].as_u64().unwrap() as u16, row["body"].as_str().unwrap())),
            row["offered"],
            "{row}"
        );
    }
    for row in rows(&data, "effort_fit") {
        let fit = EffortFit::default();
        let raw = row["body"].to_string().into_bytes();
        let swap_json = |fitted: Option<(Vec<u8>, rules::EffortSwap)>| fitted.map_or(Value::Null, |(_, swap)| swap.as_json());
        assert_eq!(swap_json(fit.fit("host", &raw)), row["before"], "{row}");
        let lesson = fit.learn("host", &raw, row["status"].as_u64().unwrap() as u16, row["error"].as_str().unwrap());
        let lesson = lesson.map_or(
            Value::Null,
            |lesson| json!({"model": lesson.model, "asked": lesson.asked, "sent": lesson.sent, "takes": lesson.takes}),
        );
        assert_eq!(lesson, row["lesson"], "{row}");
        let fitted = fit.fit("host", &raw);
        let sends = fitted.as_ref().map_or_else(|| row["body"].clone(), |(sent, _)| serde_json::from_slice(sent).unwrap());
        assert_eq!(sends, row["sends"], "{row}");
        assert_eq!(swap_json(fitted), row["swap"], "{row}");
        assert_eq!(swap_json(fit.fit("other-host", &raw)), row["elsewhere"], "{row}");
    }
    for row in rows(&data, "nearest_effort") {
        let offered: Vec<&str> = row["offered"].as_array().unwrap().iter().map(|word| word.as_str().unwrap()).collect();
        assert_eq!(json!(ChatLevers::nearest_effort(row["asked"].as_str().unwrap(), &offered)), row["nearest"], "{row}");
    }
}

#[test]
fn what_goes_out_to_a_provider() {
    let data = table("limits");
    for row in rows(&data, "base_url") {
        let got = rules::BaseUrl::read(row["text"].as_str().unwrap());
        let said = got.map_or(
            Value::Null,
            |place| json!({"tls": place.tls, "host": place.host, "port": place.port, "netloc": place.netloc, "path": place.path}),
        );
        assert_eq!(said, row["read"], "{row}");
    }
    for row in rows(&data, "upstream_path") {
        let place = rules::BaseUrl::read(&format!("https://x{}", row["base"].as_str().unwrap())).unwrap();
        assert_eq!(json!(place.upstream_path(row["incoming"].as_str().unwrap())), row["path"], "{row}");
    }
    for row in rows(&data, "client_name") {
        let mut fields: Vec<(String, Vec<u8>)> = row["fields"]
            .as_object()
            .unwrap()
            .iter()
            .map(|(name, value)| (name.clone(), value.as_str().unwrap().as_bytes().to_vec()))
            .collect();
        let name = rules::ClientName::read(Some(&row["policy"]));
        name.say(&mut fields);
        let said: serde_json::Map<String, Value> =
            fields.into_iter().map(|(name, value)| (name, json!(String::from_utf8(value).unwrap()))).collect();
        assert_eq!(
            json!(name.word()),
            row["says"].get("User-Agent").filter(|_| name.word().is_some()).cloned().unwrap_or(Value::Null),
            "{row}"
        );
        assert_eq!(Value::Object(said), row["says"], "{row}");
    }
}

#[test]
fn pool_refusal() {
    let data = table("limits");
    let cloud = json!({"pools": [{"id": "p", "name": "the pool", "steps": []}]});
    let pools = rules::CloudPools::read(&cloud);
    let pool = &pools.all()[0];
    let dialect = OpenAiDialect::new(&pool.name);
    for row in rows(&data, "pool_refusal") {
        let refusal = if row.get("context").is_some() {
            rules::PoolRefusal::of_context(pool)
        } else {
            rules::PoolRefusal::of_rows(
                pool,
                row["steps"].as_array().unwrap(),
                row["now"].as_f64().unwrap(),
                row["path"].as_str().unwrap(),
                &UtcClock,
            )
        };
        assert_eq!(json!(refusal.status), row["status"], "{row}");
        assert_eq!(json!(refusal.kind), row["kind"], "{row}");
        assert_eq!(json!(refusal.message), row["message"], "{row}");
        assert_eq!(json!(refusal.journal_body), row["body"], "{row}");
        assert_eq!(
            told_in_table_words(&refusal.told(&dialect)),
            json!({"told": row["told"], "payload": row["payload"], "headers": row["headers"]}),
            "{row}"
        );
    }
}

#[test]
fn what_a_key_goes_in() {
    let data = table("limits");
    for row in rows(&data, "provider_auth") {
        let accounts = rules::CloudAccounts::read(Some(&json!([row["account"]])));
        let provider = accounts.provider("a", &Credentials::default()).unwrap();
        let (field, prefix) = provider.key_field();
        let extra: Vec<Value> = provider.extra_fields().iter().map(|(name, value)| json!([name, value])).collect();
        assert_eq!(
            (json!(field), json!(prefix), json!(extra), json!(provider.anthropic)),
            (row["field"].clone(), row["prefix"].clone(), row["extra"].clone(), row["anthropic"].clone()),
            "{row}"
        );
    }
    for row in rows(&data, "account_claim") {
        assert_eq!(json!(Credentials::account_claim(row["token"].as_str().unwrap())), row["claim"], "{row}");
    }
}

#[test]
fn what_a_provider_lists() {
    let data = table("limits");
    let catalogue = ModelCatalogue::read(Some(&data["catalogue_document"]));
    for row in rows(&data, "catalogue_lists") {
        assert_eq!(
            json!(catalogue.lists(row["account"].as_str().unwrap(), row["model"].as_str().unwrap())),
            row["lists"],
            "{row}"
        );
    }
    for row in rows(&data, "reserve_names") {
        assert_eq!(
            json!(UsageReserve::normalize(Some(&row["raw"])).names(row["seconds"].as_i64().unwrap())),
            row["names"],
            "{row}"
        );
    }
}

#[test]
fn json_as_python_writes_it() {
    let data = table("translate");
    for row in rows(&data, "python_json") {
        let value = &row["value"];
        assert_eq!(json!(rules::PythonJson::spaced(value)), row["spaced"], "{row}");
        assert_eq!(json!(rules::PythonJson::spaced_letters(value)), row["letters"], "{row}");
        assert_eq!(json!(rules::PythonJson::compact(value)), row["compact"], "{row}");
    }
}
