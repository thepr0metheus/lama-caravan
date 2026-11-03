//! What /hf reads of the hub and of the disk, over a hub that stands in and a folder of the test's own, by the values each rule was once caught on.

use super::super::hub::tests::{RouteCall, Row, TestHub};
use super::*;
use crate::routes::hf::HfRoutes;
use crate::tests::{StandIn, TestApp, TestFolder};
use std::sync::Arc;
use std::time::SystemTime;

const TOKEN: &str = "hf_test_not_a_real_token";

fn sha(number: u32) -> String {
    format!("{number:x}").repeat(64)
}

fn git(number: u32) -> String {
    format!("{number:x}").repeat(40)
}

/// A controller over its own folder whose hub is a table.
fn stand(name: &str, rows: Vec<Row>) -> (TestFolder, StandIn, Arc<App>) {
    let folder = TestFolder::new(&format!("hf-{name}"));
    let hub = StandIn::table(rows);
    let app = TestApp::over(&folder.path, &[("CARAVAN_HUB_URL", hub.address())]);
    (folder, hub, app)
}

fn save_token(app: &App) {
    app.admin.saving(|doc| doc.insert("hfToken".to_string(), json!(TOKEN)));
}

/// A listing's rows by their path.
fn by_path(rows: Option<&Value>) -> BTreeMap<String, Value> {
    rows.and_then(Value::as_array).into_iter().flatten().map(|row| (Coerce::text(row.get("path")), row.clone())).collect()
}

fn names(rows: &BTreeMap<String, Value>) -> Vec<&str> {
    rows.keys().map(String::as_str).collect()
}

/// What the hub says of a file's bytes, as a listing's row carries it.
fn digest(row: &Value) -> (String, String, bool) {
    (Coerce::text(row.get("oid")), Coerce::text(row.get("gitOid")), row.get("hashHidden") == Some(&json!(true)))
}

fn robot_tree() -> Vec<Value> {
    vec![
        TestHub::folder("experiment_cfg"),
        TestHub::plain(".gitattributes", 1578, &git(1)),
        TestHub::plain("README.md", 13111, &git(2)),
        TestHub::plain("LICENSE", 4063, &git(3)),
        TestHub::lfs("model-architecture.png", 3_184_280, &sha(1)),
        TestHub::plain("config.json", 2071, &git(4)),
        TestHub::plain("SUCCESS", 0, &git(5)),
        TestHub::plain("experiment_cfg/conf.yaml", 31159, &git(6)),
        TestHub::lfs("experiment_cfg/initial_actions.npz", 1_564_431, &sha(2)),
        TestHub::lfs("model-00001-of-00002.safetensors", 4_990_519_232, &sha(3)),
        TestHub::plain("model.safetensors.index.json", 104_985, &git(7)),
        TestHub::lfs("scheduler.pt", 1263, &sha(4)),
        TestHub::lfs("training_args.bin", 8259, &sha(5)),
    ]
}

/// The listing of the robot's repository, its config saying the type of its weights.
fn robot_listing(name: &str) -> Value {
    let rows = vec![TestHub::tree("org/Robot-3B", robot_tree()), TestHub::config("org/Robot-3B", &json!({"dtype": "bfloat16"}))];
    let (_folder, _hub, app) = stand(name, rows);
    HubBrowser::of(&app).list_files("org/Robot-3B")
}

#[test]
fn the_plan_holds_the_weights_the_configs_and_a_folder_of_the_repository_by_their_path() {
    let got = robot_listing("plan");
    assert_eq!(got["ok"], json!(true));
    let plan = by_path(got["safetensors"].get("files"));
    assert_eq!(
        names(&plan),
        [
            "SUCCESS",
            "config.json",
            "experiment_cfg/conf.yaml",
            "experiment_cfg/initial_actions.npz",
            "model-00001-of-00002.safetensors",
            "model.safetensors.index.json"
        ]
    );
    assert_eq!(
        plan["experiment_cfg/conf.yaml"]["name"],
        json!("conf.yaml"),
        "a file of a folder has its name and its path apart"
    );
    assert_eq!(plan["SUCCESS"]["size"], json!(0), "an empty file is in the plan, as an empty file");
}

#[test]
fn what_is_not_downloaded_by_design_is_grey_and_a_folder_is_neither() {
    let got = robot_listing("grey");
    let (plan, other) = (by_path(got["safetensors"].get("files")), by_path(got.get("otherFiles")));
    assert_eq!(
        names(&other),
        [".gitattributes", "LICENSE", "README.md", "model-architecture.png", "scheduler.pt", "training_args.bin"]
    );
    assert!(plan.keys().all(|path| !other.contains_key(path)), "a file is in the plan or out of it, never both");
    assert!(
        !plan.contains_key("experiment_cfg") && !other.contains_key("experiment_cfg"),
        "a folder's entry is no file of either"
    );
}

#[test]
fn the_grey_list_goes_by_the_name_in_any_case_and_in_its_order() {
    let tree = vec![
        TestHub::plain("zeta.PDF", 1, &git(1)),
        TestHub::plain("Readme.MD", 2, &git(2)),
        TestHub::plain("docs/NOTICE.txt", 3, &git(3)),
        TestHub::plain("alpha.SVG", 4, &git(4)),
        TestHub::lfs("model.SAFETENSORS", 5, &sha(1)),
        TestHub::lfs("weights.h5", 6, &sha(2)),
        TestHub::lfs("weights.msgpack", 7, &sha(3)),
        TestHub::lfs("weights.onnx", 8, &sha(4)),
        TestHub::lfs("weights.ckpt", 9, &sha(5)),
        TestHub::lfs("weights.tflite", 10, &sha(6)),
        TestHub::lfs("weights.pth", 11, &sha(7)),
        TestHub::plain("generation_config.json", 12, &git(5)),
    ];
    let (_folder, _hub, app) = stand("grey-case", vec![TestHub::tree("o/m", tree)]);
    let got = HubBrowser::of(&app).list_files("o/m");
    let order: Vec<String> = got["otherFiles"].as_array().unwrap().iter().map(|row| Coerce::text(row.get("name"))).collect();
    assert_eq!(
        order,
        [
            "alpha.SVG",
            "NOTICE.txt",
            "Readme.MD",
            "weights.ckpt",
            "weights.h5",
            "weights.msgpack",
            "weights.onnx",
            "weights.pth",
            "weights.tflite",
            "zeta.PDF"
        ],
        "sorted by the name's lower case, a folder's file by its own name"
    );
    assert_eq!(names(&by_path(got["safetensors"].get("files"))), ["generation_config.json", "model.SAFETENSORS"]);
}

#[test]
fn the_plans_size_is_the_sum_of_the_plans_files() {
    let got = robot_listing("total");
    assert_eq!(got["safetensors"]["totalSize"], json!(4_990_519_232_i64 + 1_564_431 + 104_985 + 31159 + 2071));
}

#[test]
fn a_size_is_the_lfs_records_and_else_the_entrys_and_a_file_with_neither_weighs_nothing() {
    let mut told = TestHub::lfs("model.safetensors", 5, &sha(1));
    told["size"] = json!(7);
    let mut bare = TestHub::plain("config.json", 0, &git(1));
    bare.as_object_mut().unwrap().remove("size");
    let (_folder, _hub, app) = stand("sizes", vec![TestHub::tree("o/m", vec![told, bare])]);
    let got = HubBrowser::of(&app).list_files("o/m");
    let plan = by_path(got["safetensors"].get("files"));
    assert_eq!((&plan["model.safetensors"]["size"], &plan["config.json"]["size"]), (&json!(5), &json!(0)));
    assert_eq!(got["safetensors"]["totalSize"], json!(5));
}

#[test]
fn an_lfs_file_says_its_sha256_and_an_ordinary_file_its_git_id_in_and_out_of_the_plan() {
    let got = robot_listing("digests");
    let (plan, other) = (by_path(got["safetensors"].get("files")), by_path(got.get("otherFiles")));
    assert_eq!(digest(&plan["model-00001-of-00002.safetensors"]), (sha(3), String::new(), false));
    assert_eq!(digest(&plan["config.json"]), (String::new(), git(4), false));
    assert_eq!(digest(&plan["SUCCESS"]), (String::new(), git(5), false), "an empty ordinary file has a git id too");
    assert_eq!(
        digest(&plan["experiment_cfg/initial_actions.npz"]),
        (sha(2), String::new(), false),
        "a small LFS file is an LFS file"
    );
    assert_eq!(digest(&other["scheduler.pt"]), (sha(4), String::new(), false));
    assert_eq!(digest(&other["README.md"]), (String::new(), git(2), false));
}

#[test]
fn a_gated_repositorys_mask_reaches_the_answer_as_hidden_and_its_sizes_stay_true() {
    let mask = TestHub::mask();
    let tree = vec![
        TestHub::plain("config.json", 1505, &git(1)),
        TestHub::plain("tokenizer.json", 7_032_403, &git(2)),
        TestHub::lfs("model.safetensors", 4_877_470_304, &mask),
        TestHub::lfs("chart.png", 473_585, &mask),
    ];
    let (_folder, _hub, app) = stand("gated", vec![TestHub::tree("nvidia/Gated-2B", tree)]);
    let got = HubBrowser::of(&app).list_files("nvidia/Gated-2B");
    let plan = by_path(got["safetensors"].get("files"));
    assert_eq!(digest(&plan["model.safetensors"]), (String::new(), String::new(), true), "`oid` is empty, never 64 asterisks");
    assert_eq!(plan["model.safetensors"]["size"], json!(4_877_470_304_i64), "the size is what the check compares");
    assert_eq!(digest(&plan["config.json"]), (String::new(), git(1), false), "the mask hides only the LFS hashes");
    assert_eq!(digest(&by_path(got.get("otherFiles"))["chart.png"]), (String::new(), String::new(), true));
    assert!(!got.to_string().contains("***"), "no asterisk reaches the answer: {got}");
}

#[test]
fn a_gguf_file_keeps_its_hash_its_kind_and_its_quant() {
    let tree = vec![
        TestHub::lfs("Model-Q4_K_M.gguf", 4000, &sha(1)),
        TestHub::lfs("mmproj-Model-f16.gguf", 900, &TestHub::mask()),
        TestHub::lfs("Model-Q8_0.gguf", 8000, ""),
        TestHub::plain("README.md", 5, &git(1)),
    ];
    let (_folder, hub, app) = stand("gguf", vec![TestHub::tree("acme/Model-GGUF", tree)]);
    let got = HubBrowser::of(&app).list_files("acme/Model-GGUF");
    let files = by_path(got.get("files"));
    assert_eq!(digest(&files["Model-Q4_K_M.gguf"]), (sha(1), String::new(), false));
    assert_eq!((&files["Model-Q4_K_M.gguf"]["kind"], &files["Model-Q4_K_M.gguf"]["quant"]), (&json!("model"), &json!("Q4_K_M")));
    assert_eq!(
        digest(&files["mmproj-Model-f16.gguf"]),
        (String::new(), String::new(), true),
        "it used to read as a different file"
    );
    assert_eq!(
        (&files["mmproj-Model-f16.gguf"]["kind"], &files["mmproj-Model-f16.gguf"]["quant"]),
        (&json!("mmproj"), &json!(""))
    );
    assert_eq!(digest(&files["Model-Q8_0.gguf"]), (String::new(), String::new(), false), "no hash given is not called hidden");
    assert!(got.get("safetensors").is_none(), "a GGUF-only repository has no plan");
    assert_eq!(by_path(got.get("otherFiles")).len(), 1);
    assert!(hub.targets().iter().all(|target| !target.contains("config.json")), "and no config to read");
}

#[test]
fn the_kinds_of_a_gguf_go_by_its_name_in_any_case() {
    for (name, kind) in [
        ("MMPROJ-x.gguf", "mmproj"),
        ("a-mm-proj.gguf", "mmproj"),
        ("x-Projector-f16.gguf", "mmproj"),
        ("mtp-x.gguf", "mtp"),
        ("ggml-vocab-x.gguf", "vocab"),
        ("x-Q4_K_M.gguf", "model"),
    ] {
        assert_eq!(HubBrowser::classify_gguf(name), kind, "{name}");
    }
}

#[test]
fn every_part_of_a_split_model_reads_the_quant_of_the_model_and_keeps_its_own_hash() {
    let parts = [
        "Split-Q8_0-00001-of-00003.gguf",
        "Split-Q8_0-00002-of-00003.gguf",
        "Split-Q8_0-00003-of-00003.gguf",
        "Split-UD-Q4_K_XL-00001-of-00002.gguf",
        "Split-UD-Q4_K_XL-00002-of-00002.gguf",
        "Split-BF16-00001-of-00002.gguf",
        "Split-BF16-00002-of-00002.gguf",
        "Split-Q4_K_M.gguf",
    ];
    let tree: Vec<Value> =
        parts.iter().zip(1_u32..).map(|(name, at)| TestHub::lfs(name, i64::from(at) * 10_000, &sha(at))).collect();
    let (_folder, _hub, app) = stand("split", vec![TestHub::tree("acme/Split-GGUF", tree)]);
    let files = by_path(HubBrowser::of(&app).list_files("acme/Split-GGUF").get("files"));
    let mut quants: BTreeMap<String, Vec<&str>> = BTreeMap::new();
    for (name, row) in &files {
        quants.entry(Coerce::text(row.get("quant"))).or_default().push(name);
    }
    assert_eq!(
        quants.keys().map(String::as_str).collect::<Vec<_>>(),
        ["BF16", "Q4_K_M", "Q4_K_XL", "Q8_0"],
        "four quants, not one per part"
    );
    assert_eq!(quants["Q8_0"], parts[..3], "the parts of a model share one row and one folder");
    for (name, at) in parts.iter().zip(1_u32..) {
        assert_eq!(digest(&files[*name]).0, sha(at), "{name}: the verify compares every part against the hub");
    }
}

#[test]
fn a_repository_with_both_kinds_has_one_listing_and_no_file_in_both() {
    let tree = vec![
        TestHub::lfs("Both-7B-Q4_K_M.gguf", 4000, &sha(1)),
        TestHub::lfs("model-00001-of-00001.safetensors", 14000, &sha(2)),
        TestHub::plain("config.json", 600, &git(1)),
    ];
    let rows = vec![TestHub::tree("acme/Both-7B", tree), TestHub::config("acme/Both-7B", &json!({"torch_dtype": "float16"}))];
    let (_folder, _hub, app) = stand("both", rows);
    let got = HubBrowser::of(&app).list_files("acme/Both-7B");
    assert_eq!(names(&by_path(got.get("files"))), ["Both-7B-Q4_K_M.gguf"]);
    assert_eq!(names(&by_path(got["safetensors"].get("files"))), ["config.json", "model-00001-of-00001.safetensors"]);
    assert_eq!(got["safetensors"]["format"], json!("FP16"));
}

#[test]
fn without_safetensors_weights_everything_is_grey_and_there_is_no_plan() {
    let tree = vec![TestHub::lfs("model.onnx", 100, &sha(1)), TestHub::plain("config.json", 5, &git(1))];
    let (_folder, hub, app) = stand("onnx", vec![TestHub::tree("acme/Onnx-Only", tree)]);
    let got = HubBrowser::of(&app).list_files("acme/Onnx-Only");
    assert!(got.get("safetensors").is_none());
    assert_eq!(names(&by_path(got.get("otherFiles"))), ["config.json", "model.onnx"]);
    assert_eq!(hub.targets().len(), 1, "nothing to label, so no config is asked for");
}

#[test]
fn the_last_change_is_the_newest_commit_a_file_names() {
    let (mut old, mut new) = (TestHub::plain("a.gguf", 1, &git(1)), TestHub::plain("b.gguf", 1, &git(2)));
    old["lastCommit"]["date"] = json!("2026-09-01T00:00:00.000Z");
    new["lastCommit"]["date"] = json!("2026-10-01T00:00:00.000Z");
    let mut none = TestHub::plain("c.gguf", 1, &git(3));
    none.as_object_mut().unwrap().remove("lastCommit");
    let (_folder, _hub, app) = stand("modified", vec![TestHub::tree("o/m", vec![new, old, none])]);
    let got = HubBrowser::of(&app).list_files("o/m");
    assert_eq!(got["lastModified"], json!("2026-10-01T00:00:00.000Z"));
    assert_eq!(by_path(got.get("files"))["c.gguf"]["date"], json!(""), "a file with no commit says no date, and no made-up one");
}

#[test]
fn an_invalid_id_is_a_refusal_with_no_request() {
    let (_folder, hub, app) = stand("bad-id", Vec::new());
    for bad in ["bad id", "no-slash", "a/b/c", "/", "a/", "/b", "a b/c", ""] {
        assert_eq!(HubBrowser::of(&app).list_files(bad), json!({"ok": false, "error": "invalid repo id"}), "{bad:?}");
    }
    assert_eq!(hub.targets(), Vec::<String>::new());
}

#[test]
fn spaces_and_slashes_around_an_id_are_no_part_of_it() {
    let (_folder, _hub, app) = stand("id-edges", vec![TestHub::tree("o/m", vec![TestHub::plain("a.gguf", 1, &git(1))])]);
    assert_eq!(HubBrowser::of(&app).list_files("  /o/m/ ")["repo"], json!("o/m"));
}

#[test]
fn an_unreachable_hub_is_a_refusal_with_its_reason_and_no_empty_list() {
    let (_folder, _hub, app) = stand("refused", vec![TestHub::refused("/api/models/o/m/tree/main", "401 Unauthorized")]);
    assert_eq!(HubBrowser::of(&app).list_files("o/m"), json!({"ok": false, "error": "HTTP Error 401: Unauthorized"}));
    let body = TestHub::json("/api/models/o/said/tree/main", &json!({"error": "Repository not found"}));
    let odd = TestHub::json("/api/models/o/odd/tree/main", &json!({"tree": "?"}));
    let (_folder, _hub, app) = stand("refused-words", vec![body, odd]);
    assert_eq!(HubBrowser::of(&app).list_files("o/said"), json!({"ok": false, "error": "Repository not found"}));
    assert_eq!(HubBrowser::of(&app).list_files("o/odd"), json!({"ok": false, "error": "unexpected response"}));
}

#[test]
fn a_badge_comes_from_the_name_then_the_config_then_the_type_of_the_weights() {
    for (repo, config, want) in [
        ("nvidia/GR00T-N1.7-3B", Some(json!({"dtype": "bfloat16"})), "BF16"),
        ("org/model", Some(json!({"torch_dtype": "float16"})), "FP16"),
        ("org/model", Some(json!({"dtype": "float32"})), "FP32"),
        ("org/model", Some(json!({"torch_dtype": "float32", "dtype": "bfloat16"})), "FP32"),
        ("org/model", Some(json!({"torch_dtype": "", "dtype": "bfloat16"})), "BF16"),
        ("org/model", Some(json!({"torch_dtype": "BFloat16"})), "BF16"),
        ("org/model-AWQ", Some(json!({"dtype": "bfloat16"})), "AWQ"),
        ("org/model-awq-x", None, "AWQ"),
        ("org/model", Some(json!({"quantization_config": {"quant_method": "fp8"}, "dtype": "bfloat16"})), "FP8"),
        ("org/model-GPTQ", Some(json!({"quantization_config": {"quant_method": "fp8"}})), "GPTQ"),
        ("org/model", Some(json!({"quantization_config": {"quant_method": "modelopt"}})), "NVFP4"),
        ("org/model", Some(json!({"quantization_config": {"quant_method": "bitsandbytes"}})), "BNB"),
        ("org/model", Some(json!({"quantization_config": {"quant_method": "AutoRound"}})), "AUTOROUND"),
        ("org/model", Some(json!({"quantization_config": {"quant_method": "other-way"}})), "OTHER-WAY"),
        ("org/model", Some(json!({"quantization_config": {"quant_method": ""}, "dtype": "float16"})), "FP16"),
    ] {
        assert_eq!(HubBrowser::safetensors_format(repo, config.as_ref()), want, "{repo} {config:?}");
    }
}

#[test]
fn a_type_not_in_the_table_or_a_config_not_read_is_safetensors_and_never_a_guess() {
    for config in [
        Some(json!({"dtype": "int8"})),
        None,
        Some(json!({})),
        Some(json!({"ok": false, "error": "HTTP Error 401: Unauthorized"})),
        Some(json!([])),
    ] {
        assert_eq!(HubBrowser::safetensors_format("org/model", config.as_ref()), "SAFETENSORS", "{config:?}");
    }
}

/// The label of a repository of one weights file, over these rows of the hub.
fn label_over(name: &str, repo: &str, mut rows: Vec<Row>) -> (String, StandIn) {
    rows.push(TestHub::tree(
        repo,
        vec![TestHub::lfs("model.safetensors", 9, &sha(1)), TestHub::plain("config.json", 5, &git(1))],
    ));
    let (_folder, hub, app) = stand(name, rows);
    let got = HubBrowser::of(&app).list_files(repo);
    (Coerce::text(got["safetensors"].get("format")), hub)
}

#[test]
fn a_config_behind_a_relative_redirect_gives_the_right_label() {
    let cached = "/api/resolve-cache/models/nvidia/GR00T/abc/config.json?x=1";
    let rows = vec![
        TestHub::moved("/nvidia/GR00T/resolve/main/config.json", cached),
        TestHub::json("/api/resolve-cache/models/nvidia/GR00T/", &json!({"dtype": "bfloat16"})),
    ];
    let (label, hub) = label_over("config-redirect", "nvidia/GR00T", rows);
    assert_eq!(label, "BF16", "the owner's defect of 2026-11-02: SAFETENSORS, and a folder of that name");
    assert!(hub.targets().iter().any(|target| target == cached), "{:?}", hub.targets());
}

#[test]
fn a_config_refused_or_no_json_leaves_the_label_safetensors() {
    let refused = vec![TestHub::refused("/o/m/resolve/main/config.json", "401 Unauthorized")];
    assert_eq!(label_over("config-refused", "o/m", refused).0, "SAFETENSORS");
    let broken = vec![("/o/m/resolve/main/config.json".to_string(), "200 OK".to_string(), String::new(), b"<html>".to_vec())];
    assert_eq!(label_over("config-broken", "o/m", broken).0, "SAFETENSORS");
    let nowhere = vec![(
        "/o/m/resolve/main/config.json".to_string(),
        "302 Found".to_string(),
        String::new(),
        b"{\"dtype\": \"bfloat16\"}".to_vec(),
    )];
    assert_eq!(
        label_over("config-nowhere", "o/m", nowhere).0,
        "SAFETENSORS",
        "a redirect with nowhere to go has no config in its body"
    );
}

/// A hub whose gated repository lists to anyone and gives its config.json to a bearer of a token alone.
fn gated_hub() -> StandIn {
    StandIn::serving(|head| {
        let target = head.split_whitespace().nth(1).unwrap_or_default();
        if target.contains("/tree/") {
            let tree = json!([TestHub::plain("config.json", 1505, &git(1)), TestHub::lfs("model.safetensors", 9, &sha(1))]);
            return StandIn::answer("200 OK", "", tree.to_string().as_bytes());
        }
        if head.contains("Authorization: Bearer ") {
            return StandIn::answer("200 OK", "", b"{\"dtype\": \"bfloat16\"}");
        }
        StandIn::answer("401 Unauthorized", "", b"{\"error\": \"gated\"}")
    })
}

#[test]
fn a_gated_config_is_read_with_the_token_and_refused_without_it() {
    let folder = TestFolder::new("hf-gated-config");
    let hub = gated_hub();
    let app = TestApp::over(&folder.path, &[("CARAVAN_HUB_URL", hub.address())]);
    let label = |app: &App| Coerce::text(HubBrowser::of(app).list_files("nvidia/Gated-2B")["safetensors"].get("format"));
    assert_eq!(label(&app), "SAFETENSORS", "no token: nothing to read the type of the weights from");
    save_token(&app);
    assert_eq!(label(&app), "BF16", "a token with the terms: like a repository that is not gated");
}

#[test]
fn every_read_of_the_hub_says_who_asks_and_carries_the_token_when_there_is_one() {
    let tree = |repo: &str| TestHub::tree(repo, vec![TestHub::lfs("model.safetensors", 9, &sha(1))]);
    let (_folder, hub, app) =
        stand("fields", vec![tree("a/b"), tree("c/d"), TestHub::config("a/b", &json!({})), TestHub::config("c/d", &json!({}))]);
    HubBrowser::of(&app).list_files("a/b");
    assert!(
        hub.asked().iter().all(|head| head.contains("User-Agent: lama-caravan/1.0\r\n") && !head.contains("Authorization")),
        "{:?}",
        hub.asked()
    );
    save_token(&app);
    HubBrowser::of(&app).list_files("c/d");
    let asked = hub.asked();
    assert_eq!(asked.len(), 4, "the tree and the config, twice");
    let bearer = format!("Authorization: Bearer {TOKEN}\r\n");
    assert!(
        asked[2..].iter().all(|head| head.contains("User-Agent: lama-caravan/1.0\r\n") && head.contains(&bearer)),
        "{asked:?}"
    );
}

/// A hub whose tree answers by whether it sees a token, and counts.
fn two_faced_hub() -> StandIn {
    StandIn::serving(|head| {
        let said: &[u8] = if head.contains("Authorization") { b"[\"with\"]" } else { b"[\"without\"]" };
        StandIn::answer("200 OK", "", said)
    })
}

#[test]
fn an_answer_read_without_a_token_is_not_handed_to_a_request_with_one() {
    let folder = TestFolder::new("hf-two-faces");
    let hub = two_faced_hub();
    let app = TestApp::over(&folder.path, &[("CARAVAN_HUB_URL", hub.address())]);
    let browser = HubBrowser::of(&app);
    assert_eq!(browser.request("models/gated/tree/main", false), json!(["without"]));
    save_token(&app);
    assert_eq!(browser.request("models/gated/tree/main", false), json!(["with"]), "the second read asks again");
    assert_eq!(browser.request("models/gated/tree/main", false), json!(["with"]), "and the third is the second's");
    assert_eq!(hub.targets().len(), 2);
}

#[test]
fn a_whole_list_is_kept_but_a_read_of_one_page_is_not_served_it() {
    let next = "/api/models/o/m/tree/main?limit=100&cursor=2";
    let hub = StandIn::serving(move |head| {
        let target = head.split_whitespace().nth(1).unwrap_or_default();
        if target.contains("cursor") {
            return StandIn::answer("200 OK", "", b"[\"c\"]");
        }
        // The address of the next page is the one this stand-in was told at its first request: it is the same host.
        let host = head.lines().find_map(|line| line.strip_prefix("Host: ")).unwrap_or_default();
        StandIn::answer("200 OK", &format!("Link: <http://{host}{next}>; rel=\"next\"\r\n"), b"[\"a\", \"b\"]")
    });
    let folder = TestFolder::new("hf-page-memory");
    let app = TestApp::over(&folder.path, &[("CARAVAN_HUB_URL", hub.address())]);
    let browser = HubBrowser::of(&app);
    assert_eq!(browser.request("models/o/m/tree/main", true), json!(["a", "b", "c"]), "read to its end");
    assert_eq!(browser.request("models/o/m/tree/main", true), json!(["a", "b", "c"]));
    assert_eq!(hub.targets().len(), 2, "the second read asks nobody");
    assert_eq!(browser.request("models/o/m/tree/main", false), json!(["a", "b"]), "the read of one page is one page");
}

/// A hub of two pages: fifty extras, then the weights.
fn two_page_hub(second: fn(&str) -> Vec<u8>) -> StandIn {
    StandIn::serving(move |head| {
        let target = head.split_whitespace().nth(1).unwrap_or_default();
        if target.contains("cursor") {
            return second(target);
        }
        if target.contains("config.json") {
            return StandIn::answer("200 OK", "", b"{\"dtype\": \"bfloat16\"}");
        }
        let extras: Vec<Value> = (0..50).map(|at| TestHub::plain(&format!("assets/s{at:02}.wav"), 10, &git(1))).collect();
        let host = head.lines().find_map(|line| line.strip_prefix("Host: ")).unwrap_or_default();
        let link = format!("Link: <http://{host}/api/models/org/Repo/tree/main?limit=100&cursor=2>; rel=\"next\"\r\n");
        StandIn::answer("200 OK", &link, Value::Array(extras).to_string().as_bytes())
    })
}

#[test]
fn the_weights_that_sit_after_fifty_extras_are_in_the_plan() {
    let hub = two_page_hub(|_| {
        let weights = json!([
            TestHub::plain("config.json", 100, &git(1)),
            TestHub::lfs("model-00001-of-00002.safetensors", 5000, &sha(1)),
            TestHub::lfs("model-00002-of-00002.safetensors", 3000, &sha(2)),
        ]);
        StandIn::answer("200 OK", "", weights.to_string().as_bytes())
    });
    let folder = TestFolder::new("hf-after-extras");
    let app = TestApp::over(&folder.path, &[("CARAVAN_HUB_URL", hub.address())]);
    save_token(&app);
    let got = HubBrowser::of(&app).list_files("org/Repo");
    let plan = by_path(got["safetensors"].get("files"));
    assert!(plan.contains_key("model-00001-of-00002.safetensors") && plan.contains_key("model-00002-of-00002.safetensors"));
    assert_eq!(got["safetensors"]["totalSize"], json!(50 * 10 + 100 + 5000 + 3000));
    let bearer = format!("Authorization: Bearer {TOKEN}\r\n");
    assert!(hub.asked().iter().all(|head| head.contains(&bearer)), "every page goes with the same fields as the first");
}

#[test]
fn a_second_page_that_fails_is_a_refusal_and_not_the_first_pages_files() {
    let hub = two_page_hub(|_| StandIn::answer("500 Internal Server Error", "", b"no"));
    let folder = TestFolder::new("hf-second-page");
    let app = TestApp::over(&folder.path, &[("CARAVAN_HUB_URL", hub.address())]);
    assert_eq!(
        HubBrowser::of(&app).list_files("org/Repo"),
        json!({"ok": false, "error": "HTTP Error 500: Internal Server Error"})
    );
}

#[test]
fn a_renamed_repository_is_listed_at_its_new_name_under_the_name_it_was_asked_by() {
    let rows = vec![
        TestHub::moved("/api/models/old-org/m/tree/main", "/api/models/new-org/m/tree/main?recursive=true&expand=true&limit=100"),
        TestHub::tree(
            "new-org/m",
            vec![TestHub::lfs("model.safetensors", 9, &sha(1)), TestHub::plain("config.json", 5, &git(1))],
        ),
        TestHub::moved("/old-org/m/resolve/main/config.json", "/new-org/m/resolve/main/config.json"),
        TestHub::config("new-org/m", &json!({"dtype": "bfloat16"})),
    ];
    let (_folder, _hub, app) = stand("renamed", rows);
    let got = HubBrowser::of(&app).list_files("old-org/m");
    assert_eq!(got["ok"], json!(true), "{got}");
    assert_eq!(got["repo"], json!("old-org/m"));
    assert_eq!(got["safetensors"]["format"], json!("BF16"));
    assert_eq!(names(&by_path(got["safetensors"].get("files"))), ["config.json", "model.safetensors"]);
}

#[test]
fn a_renamed_repository_is_found_by_a_search_with_its_counts_under_its_new_name() {
    let record = json!({"id": "new-org/m", "downloads": 283, "likes": 1829, "createdAt": "2024-04-03T13:27:04.000Z", "pipeline_tag": "text-generation", "tags": ["gguf"]});
    let rows =
        vec![TestHub::moved("/api/models/old-org/m", "/api/models/new-org/m"), TestHub::json("/api/models/new-org/m", &record)];
    let (_folder, _hub, app) = stand("renamed-search", rows);
    assert_eq!(
        HubBrowser::of(&app).search("old-org/m", 20),
        json!({"ok": true, "repos": [{"id": "new-org/m", "downloads": 283, "likes": 1829, "createdAt": "2024-04-03T13:27:04.000Z", "pipelineTag": "text-generation", "tags": ["gguf"]}]})
    );
}

#[test]
fn a_redirect_that_goes_on_for_ever_is_an_error_and_no_list() {
    let (_folder, _hub, app) =
        stand("endless", vec![TestHub::moved("/api/models/o/m/tree/main", "/api/models/o/m/tree/main?again=1")]);
    let got = HubBrowser::of(&app).list_files("o/m");
    assert_eq!(got["ok"], json!(false), "{got}");
}

fn model_page() -> Value {
    let mut tags = vec![json!("gguf"), json!("vision"), json!(7)];
    tags.extend((0..50).map(|at| json!(format!("t{at}"))));
    json!({"id": "bartowski/gemma-4-12B-it-GGUF", "downloads": 33831, "likes": 47, "createdAt": "2026-06-03T18:37:35.000Z",
           "pipeline_tag": "image-text-to-text", "tags": tags, "siblings": [{"rfilename": "a.gguf"}]})
}

#[test]
fn an_exact_id_opens_that_repositorys_page_with_its_real_counts() {
    let (_folder, hub, app) = stand("search-id", vec![TestHub::json("/api/models/bartowski/gemma-4-12B-it-GGUF", &model_page())]);
    let got = HubBrowser::of(&app).search("  /bartowski/gemma-4-12B-it-GGUF/ ", 20);
    assert_eq!(
        hub.targets(),
        ["/api/models/bartowski/gemma-4-12B-it-GGUF"],
        "the model's page and no search; spaces and slashes cut"
    );
    let repos = got["repos"].as_array().unwrap();
    assert_eq!(repos.len(), 1);
    let record = &repos[0];
    assert_eq!(
        (&record["id"], &record["downloads"], &record["likes"]),
        (&json!("bartowski/gemma-4-12B-it-GGUF"), &json!(33831), &json!(47))
    );
    assert_eq!(
        (&record["createdAt"], &record["pipelineTag"]),
        (&json!("2026-06-03T18:37:35.000Z"), &json!("image-text-to-text"))
    );
    let tags = record["tags"].as_array().unwrap();
    assert_eq!(tags.len(), 40, "no more than forty");
    assert!(tags.iter().all(Value::is_string), "and only words");
    assert!(record.get("siblings").is_none(), "the page's other fields do not come along");
}

#[test]
fn an_id_that_cannot_be_read_is_the_id_alone_with_no_counts_of_zero() {
    let rows = vec![
        TestHub::refused("/api/models/nobody/typo-GGUF", "404 Not Found"),
        TestHub::json("/api/models/nobody/no-id", &json!({"downloads": 5})),
    ];
    let (_folder, _hub, app) = stand("search-typo", rows);
    assert_eq!(HubBrowser::of(&app).search("nobody/typo-GGUF", 20), json!({"ok": true, "repos": [{"id": "nobody/typo-GGUF"}]}));
    assert_eq!(HubBrowser::of(&app).search("nobody/no-id", 20), json!({"ok": true, "repos": [{"id": "nobody/no-id"}]}));
}

#[test]
fn words_are_escaped_held_to_five_and_a_hundred_and_ask_for_gguf_by_downloads() {
    let rows = vec![TestHub::json("/api/models?search=", &json!([model_page(), {"downloads": 1}, {"id": "acme/bare-GGUF"}]))];
    let (_folder, hub, app) = stand("search-words", rows);
    let got = HubBrowser::of(&app).search("gemma 4", 1);
    assert_eq!(hub.targets(), ["/api/models?search=gemma%204&filter=gguf&limit=5&sort=downloads&direction=-1"]);
    let repos = got["repos"].as_array().unwrap();
    assert_eq!(repos.len(), 2, "a record with no id is dropped: {got}");
    assert_eq!(
        repos[1],
        json!({"id": "acme/bare-GGUF", "downloads": 0, "likes": 0, "createdAt": "", "pipelineTag": "", "tags": []})
    );
    HubBrowser::of(&app).search("gemma", 500);
    assert!(hub.targets().last().unwrap().contains("limit=100&"), "{:?}", hub.targets());
    HubBrowser::of(&app).search("gemma three", 20);
    assert!(hub.targets().last().unwrap().contains("limit=20&"), "{:?}", hub.targets());
}

#[test]
fn a_failed_search_is_a_refusal_with_its_reason_and_an_empty_query_asks_nobody() {
    let (_folder, hub, app) = stand("search-fails", vec![TestHub::refused("/api/models?search=", "429 Too Many Requests")]);
    let said = HubBrowser::of(&app).search("gemma", 20);
    assert_eq!(said, json!({"ok": false, "error": "HTTP Error 429: Too Many Requests"}));
    assert_eq!(HubBrowser::of(&app).search("   ", 20), json!({"ok": false, "error": "missing query"}));
    assert_eq!(hub.targets().len(), 1);
}

#[test]
fn a_search_is_read_one_page_and_a_tree_to_its_end() {
    let (_folder, hub, app) =
        stand("search-page", vec![TestHub::json("/api/models?search=", &json!([])), TestHub::tree("o/m", Vec::new())]);
    HubBrowser::of(&app).search("gemma", 20);
    HubBrowser::of(&app).list_files("o/m");
    let targets = hub.targets();
    assert_eq!(targets[0].matches("limit=").count(), 1, "a search names its own size and reads what comes");
    assert_eq!(targets[1], "/api/models/o/m/tree/main?recursive=true&expand=true&limit=100");
}

/// A file of the models folder, as the test says it stands.
fn put(app: &App, rel: &str, size: usize, mtime: u64) {
    let path = app.models_dir().join(rel);
    std::fs::create_dir_all(path.parent().unwrap()).unwrap();
    std::fs::write(&path, vec![b'x'; size]).unwrap();
    let when = SystemTime::UNIX_EPOCH + Duration::from_secs(mtime);
    std::fs::File::options().write(true).open(&path).unwrap().set_modified(when).unwrap();
}

fn local_stand(name: &str) -> (TestFolder, Arc<App>) {
    let folder = TestFolder::new(&format!("hf-local-{name}"));
    let app = TestApp::over(&folder.path, &[]);
    (folder, app)
}

#[test]
fn the_ggufs_of_a_repositorys_folder_are_read_by_name() {
    let (_folder, app) = local_stand("names");
    put(&app, "gemma-4-31B-it-GGUF/unsloth/default/mtp-gemma-4-31B-it.gguf", 267, 1_780_100_000);
    put(&app, "gemma-4-31B-it-GGUF/unsloth/Q4_0/twin.gguf", 10, 1_780_000_000);
    put(&app, "gemma-4-31B-it-GGUF/unsloth/Q8_0/notes.txt", 3, 1_780_000_000);
    let got = HubBrowser::of(&app).local_check("unsloth/gemma-4-31B-it-GGUF");
    assert_eq!(got["ok"], json!(true));
    assert_eq!(got["localNames"], json!(["mtp-gemma-4-31B-it.gguf", "twin.gguf"]));
    let row = &got["localFiles"]["mtp-gemma-4-31B-it.gguf"];
    let path = app.models_dir().join("gemma-4-31B-it-GGUF/unsloth/default/mtp-gemma-4-31B-it.gguf");
    assert_eq!(row, &json!({"size": 267, "mtime": 1_780_100_000, "path": path.to_string_lossy()}));
}

#[test]
fn a_name_in_two_quants_is_the_newer_file_whichever_was_walked_first() {
    let (_folder, app) = local_stand("twins");
    put(&app, "M/a/Q4_0/twin.gguf", 10, 1_780_000_000);
    put(&app, "M/a/Q8_0/twin.gguf", 20, 1_780_200_000);
    put(&app, "M/a/Q4_0/other.gguf", 30, 1_780_200_000);
    put(&app, "M/a/Q8_0/other.gguf", 40, 1_780_000_000);
    let got = HubBrowser::of(&app).local_check("a/M");
    let row = |name: &str| (got["localFiles"][name]["size"].clone(), got["localFiles"][name]["mtime"].clone());
    assert_eq!(row("twin.gguf"), (json!(20), json!(1_780_200_000)));
    assert_eq!(row("other.gguf"), (json!(30), json!(1_780_200_000)));
}

#[test]
fn a_file_that_cannot_be_looked_at_is_named_with_an_empty_record_and_no_size() {
    let (_folder, app) = local_stand("dead-link");
    let quant = app.models_dir().join("M/a/Q4");
    std::fs::create_dir_all(&quant).unwrap();
    std::os::unix::fs::symlink("nowhere.gguf", quant.join("dead.gguf")).unwrap();
    std::os::unix::fs::symlink("gone.gguf", quant.join("beside.gguf")).unwrap();
    put(&app, "M/a/Q8/beside.gguf", 5, 1_780_000_000);
    let got = HubBrowser::of(&app).local_check("a/M");
    assert_eq!(got["localNames"], json!(["beside.gguf", "dead.gguf"]));
    assert_eq!(got["localFiles"]["dead.gguf"], json!({}), "that is NOT the same as on the hub: the rule reads it as unknown");
    assert_eq!(got["localFiles"]["beside.gguf"]["size"], json!(5), "a copy that can be read wins over one that cannot");
}

#[test]
fn another_authors_folder_and_a_folder_that_only_begins_the_same_are_not_this_repository() {
    let (_folder, app) = local_stand("prefix");
    put(&app, "Model-GGUF/author/Q4/mine.gguf", 1, 1_780_000_000);
    put(&app, "Model-GGUF/author-extra/Q4/y.gguf", 1, 1_780_000_000);
    put(&app, "Model-GGUF/other/Q4/z.gguf", 1, 1_780_000_000);
    put(&app, "Model-GGUF-extra/author/Q4/x.gguf", 1, 1_780_000_000);
    assert_eq!(HubBrowser::of(&app).local_check("author/Model-GGUF")["localNames"], json!(["mine.gguf"]));
}

#[test]
fn a_repository_with_no_author_is_the_models_folder() {
    let (_folder, app) = local_stand("solo");
    put(&app, "solo-model/Q4/solo-Q4_K_M.gguf", 1, 1_780_000_000);
    assert_eq!(HubBrowser::of(&app).local_check("solo-model")["localNames"], json!(["solo-Q4_K_M.gguf"]));
}

#[test]
fn nothing_anywhere_is_empty_everywhere_and_no_repository_is_a_refusal() {
    let (_folder, app) = local_stand("nothing");
    assert_eq!(
        HubBrowser::of(&app).local_check("nobody/none-GGUF"),
        json!({"ok": true, "localNames": [], "localFiles": {}, "libraryFiles": {}, "checkpointFolders": []})
    );
    assert_eq!(HubBrowser::of(&app).local_check(" / "), json!({"ok": false, "error": "missing repo"}));
}

#[test]
fn a_checkpoint_folder_is_a_folder_under_the_author_that_holds_weights_at_any_depth() {
    let (_folder, app) = local_stand("checkpoints");
    for rel in [
        "Robot-3B/acme/BF16/model-00001-of-00002.safetensors",
        "Robot-3B/acme/BF16/model-00002-of-00002.safetensors",
        "Robot-3B/acme/FP8/shards/deep/model.safetensors",
        "Robot-3B/acme/.hidden/model.safetensors",
        "Robot-3B/acme/#recycle/model.safetensors",
        "Robot-3B/acme/loose.safetensors",
        "Robot-3B/acme/PART/model.safetensors.part",
        "Robot-3B/acme/Q4_K_M/Robot-3B-Q4_K_M.gguf",
        "Robot-3B/other/NVFP4/model.safetensors",
    ] {
        put(&app, rel, 4, 1_780_000_000);
    }
    let browser = HubBrowser::of(&app);
    let robot = browser.local_check("acme/Robot-3B");
    assert_eq!(
        robot["checkpointFolders"],
        json!(["BF16", "FP8"]),
        "one row for a folder; no loose file, no .part, nothing hidden"
    );
    assert_eq!(
        robot["localNames"],
        json!(["Robot-3B-Q4_K_M.gguf"]),
        "a GGUF beside it reads as before, and its folder is no checkpoint"
    );
    assert_eq!(browser.local_check("other/Robot-3B")["checkpointFolders"], json!(["NVFP4"]));
    assert_eq!(browser.local_check("acme/Robot-3B-GGUF")["checkpointFolders"], json!([]));
}

#[test]
fn libraries_say_this_repositorys_ggufs_with_one_entry_per_library_that_holds_it() {
    let library = |id: &str, name: &str, state: &str, files: &[(&str, i64, i64)]| {
        let files: Vec<Value> =
            files.iter().map(|(path, size, mtime)| json!({"path": path, "size": size, "mtime": mtime})).collect();
        json!({"id": id, "name": name, "state": state, "path": format!("/mnt/{id}"), "files": files})
    };
    let libraries = [
        library(
            "lib-a",
            "lama-caravan-models",
            "ok",
            &[
                ("gemma-4-31B-it-GGUF/unsloth/Q5_K_M/gemma-4-31B-it-Q5_K_M.gguf", 20_200, 1_780_000_000),
                ("gemma-4-31B-it-GGUF/unsloth/default/mmproj-BF16.gguf", 1_100, 1_780_000_001),
                ("gemma-4-31B-it-GGUF/unsloth/Q8_0/gemma-4-31B-it-Q8_0.gguf", 34_000, 1_780_000_002),
                ("gemma-4-31B-it-GGUF/unsloth/Q8_0/README.md", 5, 1_780_000_003),
                ("gemma-4-31B-it-GGUF/bartowski/Q4_K_M/gemma-4-31B-it-Q4_K_M.gguf", 17_000, 1_780_000_004),
                ("gemma-4-31B-it-GGUF-extra/unsloth/Q4_K_M/x.gguf", 1, 1_780_000_005),
                ("gemma-4-31B-it-GGUF/unsloth-extra/Q4_K_M/y.gguf", 1, 1_780_000_008),
                ("solo-model/Q4_K_M/solo-Q4_K_M.gguf", 9, 1_780_000_006),
            ],
        ),
        library(
            "lib-b",
            "second-shelf",
            "read-only",
            &[("gemma-4-31B-it-GGUF/unsloth/Q8_0/gemma-4-31B-it-Q8_0.gguf", 34_000, 1_770_000_000)],
        ),
        library(
            "lib-c",
            "unplugged",
            "unavailable",
            &[("gemma-4-31B-it-GGUF/unsloth/Q4_K_S/gemma-4-31B-it-Q4_K_S.gguf", 16_000, 1_780_000_007)],
        ),
    ];
    let locations = Locations::new(&libraries, "/h");
    let found = HubBrowser::library_files(&locations, "gemma-4-31B-it-GGUF/unsloth/");
    let keys: Vec<&String> = found.as_object().unwrap().keys().collect();
    assert_eq!(
        keys,
        ["gemma-4-31B-it-Q5_K_M.gguf", "gemma-4-31B-it-Q8_0.gguf", "mmproj-BF16.gguf"],
        "GGUF only; no other author, no folder that only begins the same; nothing of a library that is not there"
    );
    assert_eq!(
        found["gemma-4-31B-it-Q5_K_M.gguf"],
        json!([{"store": {"id": "lib-a", "name": "lama-caravan-models"}, "size": 20_200, "mtime": 1_780_000_000}])
    );
    let shelves: Vec<&Value> =
        found["gemma-4-31B-it-Q8_0.gguf"].as_array().unwrap().iter().map(|copy| &copy["store"]["name"]).collect();
    assert_eq!(shelves, [&json!("lama-caravan-models"), &json!("second-shelf")], "a read-only library reads too");
    let solo = HubBrowser::library_files(&locations, "solo-model/");
    assert_eq!(
        solo.as_object().unwrap().keys().collect::<Vec<_>>(),
        ["solo-Q4_K_M.gguf"],
        "a repository with no author is the model's folder"
    );
}

#[test]
fn deleting_a_downloaded_file_stays_inside_the_repositorys_folder() {
    let (_folder, app) = local_stand("delete");
    put(&app, "M/a/Q4/x.gguf", 1, 1_780_000_000);
    put(&app, "M/a/Q8/x.gguf", 1, 1_780_000_000);
    put(&app, "M/b/Q4/x.gguf", 1, 1_780_000_000);
    let browser = HubBrowser::of(&app);
    assert_eq!(browser.local_delete("a/M", "../x.gguf"), json!({"ok": false, "error": "invalid filename"}));
    assert_eq!(browser.local_delete("a/M", ".x.gguf"), json!({"ok": false, "error": "invalid filename"}));
    assert_eq!(browser.local_delete("a/M", ""), json!({"ok": false, "error": "missing repo or filename"}));
    assert_eq!(browser.local_delete("a/None", "x.gguf"), json!({"ok": false, "error": "repo folder not found"}));
    assert_eq!(browser.local_delete("a/M", "y.gguf"), json!({"ok": false, "error": "file not found"}));
    assert_eq!(browser.local_delete("a/M", "x.gguf"), json!({"ok": true}));
    let models = app.models_dir();
    assert!(!models.join("M/a").exists(), "both quants of the name went, and the empty folders with them");
    assert!(models.join("M/b/Q4/x.gguf").is_file(), "another author's copy stays");
}

#[test]
fn saving_a_token_forgets_what_the_hub_said_for_a_new_token_sees_other_things() {
    let folder = TestFolder::new("hf-token-memory");
    let hub = two_faced_hub();
    let app = TestApp::over(&folder.path, &[("CARAVAN_HUB_URL", hub.address())]);
    let save = |token: &str| RouteCall::post(&app, &HfRoutes::ROUTES, "/api/hf/token", json!({"token": token}));
    save("first-token-value");
    HubBrowser::of(&app).request("models/gated/tree/main", false);
    save("second-token-value");
    HubBrowser::of(&app).request("models/gated/tree/main", false);
    let asked = hub.asked();
    assert_eq!(asked.len(), 2, "both tokens have the same mark in the memory's key: only the forgetting tells them apart");
    assert!(asked[1].contains("Authorization: Bearer second-token-value\r\n"), "{}", asked[1]);
}

#[test]
fn a_saved_token_is_never_said_back_whole() {
    let (_folder, _hub, app) = stand("token-masked", Vec::new());
    let said = |target: &str, body: Value| RouteCall::post(&app, &HfRoutes::ROUTES, target, body).1;
    assert_eq!(RouteCall::get(&app, &HfRoutes::ROUTES, "/api/hf/token").1, json!({"ok": true, "set": false, "masked": ""}));
    assert_eq!(
        said("/api/hf/token", json!({"token": "  hf_abcdefgh1234  "})),
        json!({"ok": true, "set": true, "masked": "●●●●1234"})
    );
    assert_eq!(app.hf_token(), "hf_abcdefgh1234", "kept as it is, without the spaces around it");
    assert_eq!(
        RouteCall::get(&app, &HfRoutes::ROUTES, "/api/hf/token").1,
        json!({"ok": true, "set": true, "masked": "●●●●1234"})
    );
    assert_eq!(
        said("/api/hf/token", json!({"token": "short"})),
        json!({"ok": true, "set": true, "masked": "set"}),
        "too short to show four letters of"
    );
}

#[test]
fn a_model_tree_says_the_quantizations_of_a_repository_and_of_its_base_and_never_itself() {
    let quantized = |id: &str, tags: Value| json!({"id": id, "downloads": 5, "likes": 2, "tags": tags});
    let filter = "/api/models?filter=base_model%3Aquantized%3A";
    let rows = vec![
        TestHub::json(&format!("{filter}org/q-GGUF"), &json!([])),
        TestHub::json(
            "/api/models/org/q-GGUF",
            &json!({"id": "org/q-GGUF", "tags": ["gguf", 7, "base_model:quantized:org/base"]}),
        ),
        TestHub::json(
            &format!("{filter}org/base"),
            &json!([
                quantized("org/q-GGUF", json!(["gguf"])),
                quantized("other/base-NVFP4", json!(["safetensors"])),
                {"id": "", "downloads": 9},
                {"id": "third/base-GGUF"}
            ]),
        ),
    ];
    let (_folder, hub, app) = stand("tree", rows);
    let got = HubBrowser::of(&app).model_tree("org/q-GGUF");
    assert_eq!(got["base"], json!("org/base"));
    assert_eq!(got["quantizations"], json!([]));
    assert_eq!(
        got["siblings"],
        json!([
            {"id": "other/base-NVFP4", "downloads": 5, "likes": 2, "format": "NVFP4"},
            {"id": "third/base-GGUF", "downloads": 0, "likes": 0, "format": "GGUF"}
        ]),
        "not this repository, and no record with no id"
    );
    assert_eq!(hub.targets()[0], "/api/models?filter=base_model%3Aquantized%3Aorg/q-GGUF&sort=downloads&direction=-1&limit=30");
}

#[test]
fn a_repository_that_is_its_own_base_or_cannot_be_read_asks_for_no_siblings() {
    let rows = vec![
        TestHub::json("/api/models?filter=", &json!([])),
        TestHub::json("/api/models/org/self", &json!({"tags": ["base_model:quantized:ORG/SELF"]})),
        TestHub::refused("/api/models/org/gone", "404 Not Found"),
    ];
    let (_folder, hub, app) = stand("tree-self", rows);
    let selfish = HubBrowser::of(&app).model_tree("org/self");
    assert_eq!((&selfish["base"], &selfish["siblings"]), (&json!("ORG/SELF"), &json!([])));
    assert_eq!(hub.targets().len(), 2);
    let gone = HubBrowser::of(&app).model_tree("org/gone");
    assert_eq!((&gone["ok"], &gone["base"], &gone["siblings"]), (&json!(true), &json!(""), &json!([])));
    assert_eq!(HubBrowser::of(&app).model_tree("no-slash"), json!({"ok": false, "error": "invalid repo id"}));
}

#[test]
fn a_tree_rows_badge_goes_by_its_library_and_tags_before_its_name() {
    for (item, want) in [
        (json!({"id": "CodeFault/x-NVFP4-GGUF", "tags": ["gguf"]}), "GGUF"),
        (json!({"id": "a/x-NVFP4", "library_name": "llama.cpp"}), "GGUF"),
        (json!({"id": "a/x-NVFP4", "tags": ["mlx"]}), "MLX"),
        (json!({"id": "a/x", "library_name": "onnx"}), "ONNX"),
        (json!({"id": "a/x", "tags": ["awq", "safetensors"]}), "AWQ"),
        (json!({"id": "a/x-gptq"}), "GPTQ"),
        (json!({"id": "a/x-GGUF"}), "GGUF"),
        (json!({"id": "a/x-gguf-v2"}), "GGUF"),
        (json!({"id": "a/x", "tags": ["safetensors"]}), "SAFETENSORS"),
        (json!({"id": "a/x"}), ""),
    ] {
        assert_eq!(HubBrowser::tree_item_format(&item), want, "{item}");
    }
}
