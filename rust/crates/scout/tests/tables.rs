//! What the scout says to these inputs, recorded when it was written in Python: an answer here that changes is a difference.

#![allow(clippy::unwrap_used, clippy::panic, reason = "a table that does not read is a failed test")]

use os::clock::{Clock, SystemClock};
use rules::Coerce;
use scout::cells::probe::{ServerAsk, ServerProbe};
use scout::cells::watchdog::ProcessEnd;
use scout::commands::{Commands, NoAnswer, Ran};
use scout::config::ScoutConfig;
use scout::entry::known::KnownCells;
use scout::entry::names::ModelName;
use scout::entry::request::EntryRequest;
use scout::entry::served::ServedNames;
use scout::http_client::HttpError;
use scout::machine::Machine;
use scout::models::files::SplitGguf;
use scout::models::pace::CopyPace;
use scout::process::LogPatterns;
use scout::runtimes::prism::PrismRuntime;
use scout::starts::assets::CellAssets;
use serde_json::{Map, Value, json};
use std::path::PathBuf;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

fn table(name: &str) -> Value {
    let path = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tables").join(format!("{name}.json"));
    serde_json::from_slice(&std::fs::read(path).unwrap()).unwrap()
}

/// `subprocess.run`, answered from a case's table.
struct TableTools {
    tools: Map<String, Value>,
}

impl Commands for TableTools {
    fn run(&self, argv: &[&str], _timeout: Duration) -> Result<Ran, NoAnswer> {
        match self.tools.get(&argv.join(" ")) {
            None => Err(NoAnswer::NotFound),
            Some(Value::String(_)) => Err(NoAnswer::TimedOut),
            Some(said) => Ok(Ran {
                code: said.get(0).and_then(Value::as_i64).map(|code| i32::try_from(code).unwrap()),
                stdout: said.get(1).and_then(Value::as_str).unwrap().to_string(),
                stderr: said.get(2).and_then(Value::as_str).unwrap().to_string(),
            }),
        }
    }
}

fn config() -> Arc<ScoutConfig> {
    let path = std::env::temp_dir().join(format!("scout-tables-{}-{:?}.json", std::process::id(), std::thread::current().id()));
    std::fs::write(&path, r#"{"listenHost": "127.0.0.1"}"#).unwrap();
    let config = ScoutConfig::load(&path).unwrap();
    std::fs::remove_file(&path).unwrap();
    Arc::new(config)
}

fn ask_machine(machine: &Machine, ask: &str) -> Value {
    if let Some(port) = ask.strip_prefix("firewall:") {
        return match port.parse::<i64>() {
            Ok(port) => machine.firewall(&json!(port)),
            Err(_) => machine.firewall(&json!(port)),
        };
    }
    match ask {
        "gpus" => json!(machine.gpus()),
        "gpu_error" => json!(machine.gpu_error()),
        "compute_apps" => json!(machine.compute_apps()),
        "listeners" => machine.listeners(),
        "listening_ports" => json!(machine.listening_ports()),
        "processes" => machine
            .processes()
            .map_or(Value::Null, |rows| Value::Object(rows.into_iter().map(|(pid, row)| (pid.to_string(), row)).collect())),
        "top_processes" => {
            let mut said = machine.top_processes();
            said.as_object_mut().unwrap().remove("time");
            said
        }
        other => panic!("no such question: {other}"),
    }
}

#[test]
fn what_the_machines_tools_say_reads_as_it_did() {
    for case in table("machine").as_array().unwrap() {
        let name = Coerce::text(case.get("name"));
        let tools = TableTools { tools: case.get("tools").and_then(Value::as_object).unwrap().clone() };
        let clock: Arc<dyn Clock> = Arc::new(SystemClock::new());
        let machine = Machine::on_system(config(), Arc::new(tools), clock, true);
        for (ask, said) in case.get("said").and_then(Value::as_object).unwrap() {
            assert_eq!(&ask_machine(&machine, ask), said, "{name}: {ask}");
        }
    }
}

fn rows(table: &Value, name: &str) -> Vec<Value> {
    table.get(name).and_then(Value::as_array).unwrap().clone()
}

#[test]
fn a_models_name_reads_as_it_did() {
    for row in rows(&table("rules"), "names") {
        let asked = row.get("in").unwrap();
        let said = ModelName::of(asked.get(0), &Coerce::text(asked.get(1)), asked.get(2).and_then(Value::as_i64).unwrap());
        assert_eq!(Some(&json!(said)), row.get("out"), "{asked}");
    }
}

#[test]
fn what_a_controller_keeps_reads_as_it_did() {
    for row in rows(&table("rules"), "known") {
        let said = KnownCells::clean(row.get("in"));
        let out = said.map_or(Value::Null, |cells| {
            Value::Object(
                cells
                    .iter()
                    .map(|(port, cell)| (port.to_string(), json!({"config": cell.config, "modelPath": cell.model_path})))
                    .collect(),
            )
        });
        assert_eq!(Some(&out), row.get("out"), "{}", row.get("in").unwrap());
    }
}

#[test]
fn a_request_names_its_model_as_it_did() {
    for row in rows(&table("rules"), "requests") {
        let asked = row.get("in").unwrap();
        let (body, kind, name) = (Coerce::text(asked.get(0)), Coerce::text(asked.get(1)), Coerce::text(asked.get(2)));
        let request = EntryRequest::new(body.clone().into_bytes(), &kind);
        assert_eq!(Some(&json!(request.model())), row.get("model"), "{asked}");
        let renamed = String::from_utf8(request.naming(&name)).unwrap();
        let expected = Coerce::text(row.get("naming"));
        // Python's `json.dumps` writes "ю" as an escape: one meaning, and the cell reads the same.
        match (serde_json::from_str::<Value>(&renamed), serde_json::from_str::<Value>(&expected)) {
            (Ok(left), Ok(right)) => assert_eq!(left, right, "{asked}"),
            _ => assert_eq!(renamed, expected, "{asked}"),
        }
    }
}

#[test]
fn the_names_a_server_answers_to_read_as_they_did() {
    for row in rows(&table("rules"), "served") {
        assert_eq!(
            Some(&json!(ServedNames::parse(Coerce::text(row.get("in")).as_bytes()))),
            row.get("out"),
            "{}",
            row.get("in").unwrap()
        );
    }
}

#[test]
fn the_parts_of_a_split_file_are_what_they_were() {
    let splits = SplitGguf::new().unwrap();
    for row in rows(&table("rules"), "splits") {
        assert_eq!(Some(&json!(splits.parts(&Coerce::text(row.get("in"))))), row.get("out"), "{}", row.get("in").unwrap());
    }
}

#[test]
fn an_end_is_said_in_the_same_words() {
    for row in rows(&table("rules"), "ends") {
        let status = row.get("in").and_then(Value::as_object).unwrap();
        assert_eq!(Some(&json!(ProcessEnd::how(status))), row.get("how"), "{status:?}");
        assert_eq!(Some(&json!(ProcessEnd::reason(status))), row.get("reason"), "{status:?}");
    }
}

#[test]
fn the_archive_of_a_system_is_the_one_it_was() {
    for row in rows(&table("rules"), "assets") {
        let asked = row.get("in").unwrap();
        let word = |at: usize| Coerce::text(asked.get(at));
        let said = match PrismRuntime::asset(&word(0), &word(1), &word(2), &word(3)) {
            Ok(name) => json!({"ok": name}),
            Err(error) => json!({"error": error.message}),
        };
        assert_eq!(Some(&said), row.get("out"), "{asked}");
    }
}

#[test]
fn a_launcher_is_found_where_it_was() {
    for row in rows(&table("rules"), "stems") {
        assert_eq!(
            Some(&json!(CellAssets::launcher_stem(&Coerce::text(row.get("in"))))),
            row.get("out"),
            "{}",
            row.get("in").unwrap()
        );
    }
}

#[test]
fn a_copys_pace_is_what_it_was() {
    for row in rows(&table("rules"), "paces") {
        let mut pace = CopyPace::default();
        let mut said = Vec::new();
        for sample in row.get("in").and_then(Value::as_array).unwrap() {
            pace.add(sample.get(1).and_then(Value::as_i64).unwrap(), sample.get(0).and_then(Value::as_f64).unwrap());
            said.push(pace.rate());
        }
        assert_eq!(Some(&json!(said)), row.get("out"), "{}", row.get("in").unwrap());
    }
}

#[test]
fn a_key_leaves_a_log_as_it_did() {
    let patterns = LogPatterns::new().unwrap();
    for row in rows(&table("rules"), "scrub") {
        assert_eq!(Some(&json!(patterns.scrub(&Coerce::text(row.get("in"))))), row.get("out"), "{}", row.get("in").unwrap());
    }
}

/// A clock set by the test.
#[derive(Default)]
struct SetClock {
    seconds: AtomicU64,
}

impl Clock for SetClock {
    fn epoch(&self) -> f64 {
        self.seconds.load(Ordering::SeqCst) as f64
    }

    fn monotonic(&self) -> f64 {
        self.epoch()
    }

    fn thread_cpu(&self) -> Option<f64> {
        None
    }
}

/// A cell's server, answering from a table.
struct TableServer {
    step: Mutex<Value>,
    props: Value,
}

impl ServerAsk for TableServer {
    fn metrics(&self, _port: i64) -> Result<(String, String), HttpError> {
        let step = self.step.lock().unwrap();
        if Coerce::truthy(step.get("gone")) {
            return Err(HttpError::Io(std::io::Error::other("no answer")));
        }
        if let Some(status) = step.get("status").and_then(Value::as_u64) {
            return Err(HttpError::Status(u16::try_from(status).unwrap(), String::new()));
        }
        Ok((Coerce::text(step.get("text")), Coerce::text(step.get("start"))))
    }

    fn props(&self, _port: i64) -> Option<Value> {
        Some(self.props.clone()).filter(|props| !props.is_null())
    }
}

#[test]
fn what_a_servers_metrics_come_to_is_what_it_was() {
    for serie in table("probe").as_array().unwrap() {
        let name = Coerce::text(serie.get("name"));
        let server = Arc::new(TableServer { step: Mutex::new(Value::Null), props: serie.get("props").cloned().unwrap() });
        let clock = Arc::new(SetClock::default());
        let probe = ServerProbe::new(Arc::clone(&server) as Arc<dyn ServerAsk>, Arc::clone(&clock) as Arc<dyn Clock>);
        let steps = serie.get("steps").and_then(Value::as_array).unwrap();
        let said = serie.get("said").and_then(Value::as_array).unwrap();
        for (at, (step, expected)) in steps.iter().zip(said).enumerate() {
            clock.seconds.store(step.get("at").and_then(Value::as_u64).unwrap(), Ordering::SeqCst);
            *server.step.lock().unwrap() = step.clone();
            let out = Value::Object(probe.metrics(22001));
            assert_eq!(&out, expected, "{name}, step {at}");
        }
        assert_eq!(Some(&json!(probe.slots_total(22001))), serie.get("slots"), "{name}: slots");
        assert_eq!(Some(&json!(probe.ctx_max(22001))), serie.get("ctx"), "{name}: window");
    }
}
