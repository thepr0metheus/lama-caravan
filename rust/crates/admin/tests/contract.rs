//! The controller's half of the tables the browser's tests are held to: `contract/*.json`. The other half is the browser's own (`scripts/test_js_*.py` and the tests that name
//! a table), so the page and the program cannot part with neither going red.
// A test may stop where it found something wrong; clippy sees only `#[test]` bodies as tests, not their helpers.
#![allow(clippy::unwrap_used, clippy::panic, clippy::indexing_slicing)]

use admin::common::draft::DraftFile;
use admin::common::freshness::ModelFreshness;
use admin::common::misc::SharedQueuePolicy;
use admin::common::model_jobs::ModelJobs;
use admin::common::window::Windows;
use admin::config::args::LlamaArgs;
use admin::domain::runner::{Config, PageSpec, RunnerDefaults, RunnerRegistry, StrataRunner};
use admin::fleet::cell_talk::TalkMode;
use admin::fleet::remote_cells::TokenRates;
use admin::models::gguf_header::GgufHeader;
use admin::models::headers::ModelHeader;
use admin::models::hf::HubMemory;
use admin::models::listing::ModelListing;
use admin::models::notes::ModelNotes;
use admin::models::verify::CheckpointLayout;
use admin::proxies::config::ProxiesConfig;
use admin::routes::AllRoutes;
use rules::{AskedWindow, Coerce, KvCache, MachineOutput, Policy, WeekWindows};
use serde_core::Serialize;
use serde_json::{Value, json};
use std::fs;
use std::path::PathBuf;

/// The tables' folder: beside `rust/`, or where `CARAVAN_CONTRACT_DIR` says for a copy of `rust/` that stands elsewhere.
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

fn text(value: &Value) -> &str {
    value.as_str().unwrap_or_else(|| panic!("no text: {value}"))
}

fn config(value: &Value) -> Config {
    value.as_object().unwrap_or_else(|| panic!("no config: {value}")).clone()
}

fn registry() -> RunnerRegistry {
    RunnerRegistry::new(&RunnerDefaults {
        models_dir: "/home/caravan/llama.cpp/models".to_string(),
        home: "/home/caravan".to_string(),
    })
    .unwrap()
}

/// Whether a run writes the program's words over the table: a change on purpose, and the file's diff in the merge request says what changed.
fn writing() -> bool {
    std::env::var_os("CARAVAN_CONTRACT_WRITE").is_some()
}

fn write_table(name: &str, data: &Value) {
    let mut out = Vec::new();
    let mut writer = serde_json::Serializer::with_formatter(&mut out, serde_json::ser::PrettyFormatter::with_indent(b" "));
    data.serialize(&mut writer).unwrap();
    out.push(b'\n');
    fs::write(folder().join(format!("{name}.json")), out).unwrap();
}

#[test]
fn what_the_page_is_told_of_the_runners_and_the_talks() {
    let mut data = table("controller");
    if writing() {
        data["runners"] = registry().registry_json();
        data["talkModes"] = TalkMode::all_json();
        write_table("controller", &data);
    }
    assert_eq!(registry().registry_json(), data["runners"]);
    assert_eq!(TalkMode::all_json(), data["talkModes"]);
    assert_eq!(json!(PageSpec::PATTERN), data["pagePattern"]);
}

#[test]
fn the_phases_of_a_cell_that_stands() {
    let mut phases = ProxiesConfig::STANDING_PHASES.to_vec();
    phases.sort_unstable();
    assert_eq!(json!(phases), table("controller")["standingPhases"]);
}

#[test]
fn where_a_port_states_its_window() {
    let data = table("controller");
    let mut kinds = std::collections::BTreeSet::new();
    for (reaches, said) in data["windowPaths"].as_object().unwrap() {
        let reaches = if reaches == "other" { "" } else { reaches.as_str() };
        let paths: Vec<Value> =
            Windows::paths(reaches, &["m".to_string()]).into_iter().map(|(kind, path)| json!([kind, path])).collect();
        assert_eq!(json!(paths), *said, "{reaches}");
        kinds.extend(Windows::paths(reaches, &["m".to_string()]).into_iter().map(|(kind, _)| kind));
    }
    assert_eq!(json!(kinds), data["windowKinds"]);
}

#[test]
fn the_queue_s_settings_as_the_board_edits_them() {
    let data = table("controller");
    let queue = |raw: &Value| {
        let policy = Policy::read(Some(raw)).queue;
        json!({"queueYieldSec": policy.yield_sec, "queueLimitSec": policy.limit_sec, "clientTimeoutSec": policy.client_timeout_sec})
    };
    for row in rows(&data, "modelQueueFields") {
        let (key, fallback, least, most) = (text(&row[0]), &row[1], &row[2], &row[3]);
        assert_eq!(queue(&json!({}))[key], *fallback, "{key}: said nothing");
        assert_eq!(queue(&json!({key: least.as_i64().unwrap() - 1}))[key], *least, "{key}: below its least");
        assert_eq!(queue(&json!({key: most.as_i64().unwrap() + 1}))[key], *most, "{key}: above its most");
    }
    for row in rows(&data, "modelQueueCaps") {
        assert_eq!(
            queue(&json!({"queueYieldSec": row["queueYieldSec"], "queueLimitSec": row["queueLimitSec"]})),
            row["said"],
            "{row}"
        );
    }
    for row in rows(&data, "sharedQueueFields") {
        let (policy_key, key, fallback, most) = (text(&row[0]), text(&row[1]), &row[2], &row[3]);
        assert_eq!(SharedQueuePolicy::values(None)[key], *fallback, "{key}");
        assert_eq!(SharedQueuePolicy::values(Some(&json!({policy_key: 1_000_000})))[key], *most, "{key}");
    }
}

#[test]
fn the_name_of_a_model_s_queue() {
    let data = table("controller");
    for row in rows(&data, "routeGroups") {
        let mut output = row["upstream"].clone();
        output.as_object_mut().unwrap().insert("id".to_string(), json!("out"));
        assert_eq!(json!(MachineOutput::read(&output).unwrap().group()), row["group"], "{row}");
    }
}

#[test]
fn the_line_a_cell_starts_with() {
    let mut data = table("runner_lines");
    let registry = registry();
    let line_of = |row: &Value| {
        let settings = config(&row["config"]);
        let line = match row.get("trained") {
            Some(trained) => StrataRunner::new().unwrap().command_with(&settings, trained.as_i64()),
            None => registry.get(text(&row["runner"])).command(&settings),
        };
        json!(line.unwrap_or_else(|error| panic!("{row}: {}", error.message)))
    };
    if writing() {
        for row in data["lines"].as_array_mut().unwrap() {
            row["line"] = line_of(row);
        }
        write_table("runner_lines", &data);
    }
    for row in rows(&data, "lines") {
        assert_eq!(line_of(row), row["line"], "{row}");
    }
    for row in rows(&data, "refusals") {
        let refused = registry.get(text(&row["runner"])).command(&config(&row["config"])).unwrap_err();
        assert!(refused.message.contains(text(&row["refusal"])), "{row}: {}", refused.message);
    }
}

#[test]
fn the_card_a_start_lands_on_and_what_it_holds() {
    let data = table("runner_cards");
    let (registry, gpus) = (registry(), rows(&data, "gpus").clone());
    let strata = registry.get("strata");
    for row in rows(&data, "vram") {
        assert_eq!(json!(strata.vram_reservation(&config(&row["config"]), &gpus)), row["said"], "{row}");
    }
    for row in rows(&data, "pinned") {
        assert_eq!(json!(strata.pinned_card(&config(&row["config"]), &gpus)), row["said"], "{row}");
    }
}

#[test]
fn what_a_model_s_header_tells_the_page() {
    let data = table("gguf_meta");
    let folder = std::env::temp_dir().join(format!("caravan-contract-gguf-{}", std::process::id()));
    fs::create_dir_all(&folder).unwrap();
    for (name, row) in data.as_object().unwrap() {
        let hex = text(&row["hex"]).as_bytes();
        let bytes: Vec<u8> =
            hex.chunks(2).map(|pair| u8::from_str_radix(std::str::from_utf8(pair).unwrap(), 16).unwrap()).collect();
        let path = folder.join(text(&row["file"]));
        fs::write(&path, bytes).unwrap();
        assert_eq!(ModelHeader::runtime_meta(&GgufHeader::read(&path)), row["meta"], "{name}");
    }
    fs::remove_dir_all(&folder).unwrap();
}

#[test]
fn which_kind_of_draft_a_file_is() {
    let data = table("draft_file");
    for row in rows(&data, "cases") {
        let path = text(&row["path"]);
        let file = DraftFile::new(path);
        assert_eq!(
            (json!(file.sidecar_type()), json!(file.launch_type())),
            (row["sidecar"].clone(), row["launch"].clone()),
            "{row}"
        );
        if !path.is_empty() {
            let want = if text(&row["sidecar"]).is_empty() { "model" } else { "draft" };
            assert_eq!(ModelListing::gguf_kind(path, ""), Some(want), "{row}");
        }
    }
    assert_eq!(ModelListing::gguf_kind("g/q4/mmproj-F16.gguf", ""), Some("mmproj"));
    assert_eq!(ModelListing::gguf_kind("vocabs/ggml-vocab-llama.gguf", ""), None);
}

#[test]
fn the_open_minutes_of_a_week() {
    let data = table("week_windows");
    for row in rows(&data, "cases") {
        let runs: Vec<Value> =
            WeekWindows::clean(Some(&row["windows"])).runs().into_iter().map(|(from, to)| json!([from, to])).collect();
        assert_eq!(json!(runs), row["runs"], "{}", row["why"]);
    }
}

#[test]
fn our_file_against_the_one_on_hugging_face() {
    let data = table("model_freshness");
    for row in rows(&data, "cases") {
        let local = Some(&row["local"]).filter(|local| !local.is_null());
        assert_eq!(json!(ModelFreshness::compare_file(local, Some(&row["remote"])).0), row["state"], "{}", row["why"]);
    }
}

#[test]
fn a_cell_starts_with_its_metrics_unless_it_says_off() {
    let data = table("metrics_default");
    for row in rows(&data, "cases") {
        let settings = if row["said"].is_null() { Config::new() } else { config(&json!({"ENABLE_METRICS": row["said"]})) };
        assert_eq!(json!(LlamaArgs::metrics_on(&settings)), row["on"], "{row}");
    }
}

#[test]
fn where_a_checkpoint_lies() {
    let data = table("checkpoint_layout");
    for row in rows(&data, "cases") {
        let folder = CheckpointLayout::repo_folder(text(&row["repo"]));
        let file = CheckpointLayout::file_path(text(&row["path"]), text(&row["name"]));
        assert_eq!(json!(format!("{folder}/{}/{file}", text(&row["label"]))), row["lies"], "{}", row["why"]);
    }
}

#[test]
fn the_address_of_a_cell_s_page() {
    let data = table("cell_page");
    let spec = PageSpec { field: "PAGE_URL" };
    for row in rows(&data, "cases") {
        let said = spec.checked(Some(&row["said"]));
        match row["kept"].as_str() {
            Some(kept) => assert_eq!(said.unwrap_or_else(|error| panic!("{row}: {}", error.message)), kept, "{row}"),
            None => assert_eq!(said.unwrap_err().status, 400, "{row}"),
        }
    }
    let refused = spec.checked(Some(&json!(" http://personaplex.example.org "))).unwrap_err();
    assert_eq!(
        refused.message,
        "PAGE_URL must be the https address of the cell's page, https://name[:port][/path] — not 'http://personaplex.example.org'"
    );
    assert_eq!(spec.checked(None).unwrap(), "", "no address is no refusal: the cell simply has no link");
}

#[test]
fn what_a_model_does() {
    let data = table("model_jobs");
    assert_eq!(json!(ModelJobs::JOBS), data["jobs"]);
    for row in rows(&data, "artifacts") {
        let jobs =
            ModelJobs::for_artifact(text(&row["kind"]), text(&row["sttVariant"]), text(&row["arch"]), text(&row["family"]));
        assert_eq!(json!(jobs), row["jobs"], "{}", row["why"]);
    }
    for row in rows(&data, "cells") {
        assert_eq!(
            json!(ModelJobs::for_cell(text(&row["runner"]), row["kinds"].as_array().unwrap())),
            row["jobs"],
            "{}",
            row["why"]
        );
    }
    for row in rows(&data, "records") {
        let runner = ModelJobs::cell_runner_id(Some(&row["config"]));
        assert_eq!(json!(runner), row["runner"], "{}", row["why"]);
        assert_eq!(json!(ModelJobs::cell_jobs(&runner, Some(&row["meta"]), Some(&row["config"]))), row["jobs"], "{}", row["why"]);
    }
}

#[test]
fn the_model_a_path_lies_in() {
    let data = table("library_model");
    for row in rows(&data, "cases") {
        assert_eq!(json!(ModelNotes::model_of(text(&row["path"]), "/models")), row["model"], "{row}");
    }
}

#[test]
fn the_window_a_cell_asks_for() {
    let data = table("asked_window");
    for row in rows(&data, "cases") {
        // A field may hold a number, or nothing: the program reads it as its words.
        let field = row["field"].as_str().map_or_else(|| Coerce::str_of(Some(&row["field"])).replace("None", ""), str::to_string);
        assert_eq!(json!(AskedWindow::of(&field, Coerce::int(&row["trained"]))), row["asked"], "{}", row["say"]);
    }
}

#[test]
fn a_quantized_v_cache_needs_flash_attention() {
    let data = table("kv_cache");
    for row in rows(&data, "cases") {
        assert_eq!(json!(KvCache::refused_type(&config(&row["config"]))), row["refused"], "{}", row["say"]);
    }
}

#[test]
fn a_file_name_says_its_quant() {
    let memory = HubMemory::new().unwrap();
    let data = table("hf_quant");
    for row in rows(&data, "cases") {
        assert_eq!(json!(memory.quant_of(row["name"].as_str().unwrap())), row["quant"], "{}", row["name"]);
    }
}

#[test]
fn a_request_count_is_a_whole_number_from_zero() {
    let data = table("cell_counts");
    for row in rows(&data, "cases") {
        assert_eq!(json!(TokenRates::count(row.get("said"))), row["count"], "{}", row["js"]);
    }
}

#[test]
fn every_route_is_in_the_document_and_nothing_else_is() {
    let document: Value = serde_json::from_str(include_str!("../src/routes/openapi.json")).unwrap();
    let mut described = std::collections::BTreeSet::new();
    for (path, operations) in document["paths"].as_object().unwrap() {
        for method in operations.as_object().unwrap().keys() {
            described.insert((method.clone(), path.clone()));
        }
    }
    let table: std::collections::BTreeSet<(String, String)> =
        AllRoutes::table().unwrap().exact().into_iter().map(|(method, path)| (method.to_string(), path.to_string())).collect();
    let undescribed: Vec<_> = table.difference(&described).collect();
    assert!(undescribed.is_empty(), "routes the document does not describe: {undescribed:?}");
    let unanswered: Vec<_> = described.difference(&table).filter(|(_, path)| !path.contains('{')).collect();
    assert!(unanswered.is_empty(), "in the document, and no route answers them: {unanswered:?}");
}
