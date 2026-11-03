//! A local copy against the hub: the route, the listing, the finder and the job, over a hub that stands in and a folder of the test's own. A hash here is
//! worked out by the crate that holds the sums, not by the code under test.

use super::super::hf::HubBrowser;
use super::super::hub::tests::{RouteCall, Row, TestHub};
use super::*;
use crate::routes::hf::HfRoutes;
use crate::tests::{StandIn, TestApp, TestFolder};
use net::Sha1;
use std::collections::{BTreeMap, BTreeSet};
use std::path::PathBuf;
use std::sync::Arc;
use std::time::{Duration, SystemTime};

const REPO: &str = "acme/Robot-3B";
const BIG: &str = "model-00001-of-00002.safetensors";
const WEIGHTS2: &str = "model-00002-of-00002.safetensors";
const SMALL: &str = "config.json";
const YAML: &str = "experiment_cfg/conf.yaml";
const NPZ: &str = "experiment_cfg/initial_actions.npz";
const EMPTY_GIT_ID: &str = "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391";
const HELLO_GIT_ID: &str = "3b18e512dba79e4c8300dd08aeb37f8e728b8dad";
const HELLO_SHA256: &str = "a948904f2f0f479b8f8197694b30184b0d2ed1c1cd2a1ec0fb85d299a192a447";

fn sha(data: &[u8]) -> String {
    let mut sum = Sha256::new();
    sum.update(data);
    sum.hex()
}

fn git_id(data: &[u8]) -> String {
    let mut whole = format!("blob {}\0", data.len()).into_bytes();
    whole.extend_from_slice(data);
    Sha1::of(&whole)
}

/// A robot policy's checkpoint: weights, configs, an empty marker and a folder of the repository the runtime reads.
fn content() -> BTreeMap<&'static str, Vec<u8>> {
    BTreeMap::from([
        (SMALL, b"{\"model_type\": \"robot\"}\n".to_vec()),
        ("SUCCESS", Vec::new()),
        (YAML, b"horizon: 40\n".repeat(20)),
        (NPZ, vec![b'N'; 700]),
        (BIG, vec![b'W'; 5000]),
        (WEIGHTS2, vec![b'V'; 3000]),
        ("model.safetensors.index.json", b"{}".to_vec()),
    ])
}

fn is_lfs(path: &str) -> bool {
    [NPZ, BIG, WEIGHTS2].contains(&path)
}

/// The hub's tree of the checkpoint: masked as for a token without the terms when `masked`; what the plan leaves out beside it.
fn hub_tree(masked: bool, extra: Vec<Value>) -> Vec<Value> {
    let mut items = vec![TestHub::folder("experiment_cfg")];
    for (path, data) in content() {
        let size = data.len() as i64;
        items.push(if !is_lfs(path) {
            TestHub::plain(path, size, &git_id(&data))
        } else if masked {
            TestHub::lfs(path, size, &TestHub::mask())
        } else {
            TestHub::lfs(path, size, &sha(&data))
        });
    }
    items.push(TestHub::plain("README.md", 8, &git_id(b"# robot\n")));
    items.push(TestHub::plain(".gitattributes", 17, &git_id(b"*.npz filter=lfs\n")));
    items.push(TestHub::lfs("figure.png", 150, &sha(&b"PNG".repeat(50))));
    items.push(TestHub::lfs("training_args.bin", 90, &sha(&[b'B'; 90])));
    items.extend(extra);
    items
}

struct Stand {
    folder: TestFolder,
    app: Arc<App>,
    _hub: StandIn,
}

impl Stand {
    fn new(name: &str, rows: Vec<Row>) -> Self {
        let folder = TestFolder::new(&format!("verify-{name}"));
        let hub = StandIn::table(rows);
        let app = TestApp::over(&folder.path, &[("CARAVAN_HUB_URL", hub.address())]);
        Self { folder, app, _hub: hub }
    }

    /// With a hub that lists this tree for `repo`, and whose config.json says bfloat16.
    fn of_tree(name: &str, repo: &str, tree: Vec<Value>) -> Self {
        Self::new(name, vec![TestHub::tree(repo, tree), TestHub::config(repo, &json!({"dtype": "bfloat16"}))])
    }

    fn base(&self, repo: &str, label: &str) -> PathBuf {
        self.app.models_dir().join(CheckpointLayout::repo_folder(repo)).join(label)
    }

    /// Puts `files` (`{path in the repository: bytes}`) where the page puts a checkpoint.
    fn lay<'data>(&self, repo: &str, label: &str, files: impl IntoIterator<Item = (&'data str, Vec<u8>)>) {
        for (rel, data) in files {
            let target = self.base(repo, label).join(rel);
            std::fs::create_dir_all(target.parent().unwrap()).unwrap();
            std::fs::write(target, data).unwrap();
        }
    }

    /// POST /api/hf/verify and, when it started one, the job as it ended.
    fn verify(&self, repo: &str) -> (Value, Option<Value>) {
        let (status, answer) = RouteCall::post(&self.app, &HfRoutes::ROUTES, "/api/hf/verify", json!({"repo": repo}));
        assert_eq!(status, 200, "every refusal here is a 200 with `ok: false`");
        let job = (answer["ok"] == json!(true)).then(|| self.ended(answer["jobId"].as_str().unwrap()));
        (answer, job)
    }

    /// The job of a repository the hub lists, asked to verify what lies there.
    fn job_of(&self, repo: &str) -> Value {
        let (answer, job) = self.verify(repo);
        job.unwrap_or_else(|| panic!("no job: {answer}"))
    }

    fn ended(&self, id: &str) -> Value {
        for _ in 0..5000 {
            let job = ModelVerify::of(&self.app).status(id, "")["job"].clone();
            if job["done"] == json!(true) {
                return job;
            }
            std::thread::sleep(Duration::from_millis(2));
        }
        panic!("the job did not end");
    }

    fn start(&self, repo: &str, copies: Vec<CheckpointCopy>) -> Value {
        let id = ModelVerify::of(&self.app).start(repo, &[], &json!({}), copies).unwrap();
        self.ended(&id)
    }
}

fn summary(counts: &[(&str, i64)]) -> Value {
    let mut out = json!({"files": 0, "pending": 0, "same": 0, "differs": 0, "wrong-size": 0, "missing": 0, "size-only": 0, "unreadable": 0});
    for (state, count) in counts {
        out[*state] = json!(count);
    }
    out
}

fn total() -> i64 {
    content().values().map(|data| data.len() as i64).sum()
}

#[test]
fn a_folder_with_every_file_is_the_same_file_by_file() {
    let stand = Stand::of_tree("whole", REPO, hub_tree(false, Vec::new()));
    stand.lay(REPO, "BF16", content());
    stand.lay(REPO, "BF16", [("README.md", b"# robot (edited)\n".to_vec()), ("notes.txt", b"mine".to_vec())]);
    let job = stand.job_of(REPO);
    assert_eq!((&job["done"], &job["error"], &job["files"]), (&json!(true), &Value::Null, &json!({})), "no GGUF rows: {job}");
    let copies = job["checkpoints"].as_array().unwrap();
    assert_eq!(copies.len(), 1);
    assert_eq!(copies[0]["folder"], json!("Robot-3B/acme/BF16"));
    let rows = &copies[0]["files"];
    let paths: BTreeSet<&str> = rows.as_object().unwrap().keys().map(String::as_str).collect();
    assert_eq!(
        paths,
        content().keys().copied().collect(),
        "a row for every file of the plan, by its path; no README, no note of the owner's"
    );
    assert_eq!(copies[0]["summary"], summary(&[("files", 7), ("same", 7)]));
    let weights = sha(&content()[BIG]);
    assert_eq!(
        rows[BIG],
        json!({"state": "same", "hash": "sha256", "expectedSize": 5000, "size": 5000, "sha256": weights, "expected": weights})
    );
    let config = &content()[SMALL];
    assert_eq!(
        rows[SMALL],
        json!({"state": "same", "hash": "git-sha1", "expectedSize": config.len(), "size": config.len(), "gitSha1": git_id(config), "expected": git_id(config)})
    );
    assert_eq!(
        rows["SUCCESS"],
        json!({"state": "same", "hash": "git-sha1", "expectedSize": 0, "size": 0, "gitSha1": EMPTY_GIT_ID, "expected": EMPTY_GIT_ID}),
        "an empty file is a file"
    );
    assert_eq!(
        (&rows[YAML]["state"], &rows[NPZ]["hash"]),
        (&json!("same"), &json!("sha256")),
        "a folder of the repository keeps its place"
    );
    assert_eq!((&job["totalFiles"], &job["totalBytes"], &job["bytesDone"]), (&json!(7), &json!(total()), &json!(total())));
}

#[test]
fn what_the_plan_leaves_out_is_not_missing() {
    let stand = Stand::of_tree("design", REPO, hub_tree(false, Vec::new()));
    stand.lay(REPO, "BF16", content());
    let job = stand.job_of(REPO);
    assert_eq!(
        job["checkpoints"][0]["summary"],
        summary(&[("files", 7), ("same", 7)]),
        "the README, a picture and a .bin are on the hub and not here: no finding"
    );
    for path in ["README.md", ".gitattributes", "figure.png", "training_args.bin"] {
        assert!(job["checkpoints"][0]["files"].get(path).is_none(), "{path}");
    }
}

#[test]
fn a_missing_file_is_named_and_nothing_is_read_for_it() {
    let stand = Stand::of_tree("missing", REPO, hub_tree(false, Vec::new()));
    let mut files = content();
    files.remove(WEIGHTS2);
    let yaml = files.remove(YAML).unwrap();
    stand.lay(REPO, "BF16", files);
    let job = stand.job_of(REPO);
    let copy = &job["checkpoints"][0];
    assert_eq!(copy["files"][WEIGHTS2], json!({"state": "missing", "hash": "sha256", "expectedSize": 3000}));
    assert_eq!(copy["files"][YAML]["state"], json!("missing"), "a file of a folder of the repository too");
    assert_eq!(copy["summary"], summary(&[("files", 7), ("same", 5), ("missing", 2)]));
    assert_eq!(
        (&copy["files"][BIG]["state"], &copy["files"][SMALL]["state"]),
        (&json!("same"), &json!("same")),
        "the files that are there are still checked"
    );
    assert_eq!((&job["totalFiles"], &job["totalBytes"]), (&json!(5), &json!(total() - 3000 - yaml.len() as i64)));
}

#[test]
fn a_file_of_the_wrong_size_is_named_and_not_read() {
    let stand = Stand::of_tree("wrong-size", REPO, hub_tree(false, Vec::new()));
    let mut files = content();
    let config_size = files[SMALL].len() as i64;
    files.insert(BIG, vec![b'W'; 4999]);
    files.get_mut(SMALL).unwrap().push(b' ');
    stand.lay(REPO, "BF16", files);
    let job = stand.job_of(REPO);
    let copy = &job["checkpoints"][0];
    assert_eq!(
        copy["files"][BIG],
        json!({"state": "wrong-size", "hash": "sha256", "expectedSize": 5000, "size": 4999}),
        "both sizes, and no digest"
    );
    assert_eq!((&copy["files"][SMALL]["state"], &copy["files"][SMALL]["size"]), (&json!("wrong-size"), &json!(config_size + 1)));
    assert_eq!(copy["summary"], summary(&[("files", 7), ("same", 5), ("wrong-size", 2)]));
    assert_eq!(
        (&job["totalBytes"], &job["bytesDone"]),
        (&json!(total() - 5000 - config_size), &json!(total() - 5000 - config_size)),
        "its bytes cost nothing"
    );
}

#[test]
fn other_bytes_of_the_same_size_differ_with_both_sides_said() {
    let stand = Stand::of_tree("differs", REPO, hub_tree(false, Vec::new()));
    let other_config = b"{\"model_type\": \"other\"}\n".to_vec();
    assert_eq!(other_config.len(), content()[SMALL].len());
    let mut files = content();
    files.insert(BIG, vec![b'X'; 5000]);
    files.insert(SMALL, other_config.clone());
    stand.lay(REPO, "BF16", files);
    let copy = stand.job_of(REPO)["checkpoints"][0].clone();
    assert_eq!(
        copy["files"][BIG],
        json!({"state": "differs", "hash": "sha256", "expectedSize": 5000, "size": 5000, "sha256": sha(&[b'X'; 5000]), "expected": sha(&content()[BIG])})
    );
    let config = &copy["files"][SMALL];
    assert_eq!(
        (&config["state"], &config["gitSha1"], &config["expected"]),
        (&json!("differs"), &json!(git_id(&other_config)), &json!(git_id(&content()[SMALL])))
    );
    assert_eq!(copy["summary"], summary(&[("files", 7), ("same", 5), ("differs", 2)]));
}

const GATED: &str = "nvidia/Gated-Policy-2B";

/// A gated repository: the tree masks the LFS hashes and config.json is refused, so today's listing labels the folder SAFETENSORS.
fn gated_stand(name: &str) -> Stand {
    let refused = TestHub::refused(&format!("/{GATED}/resolve/main/config.json"), "401 Unauthorized");
    Stand::new(name, vec![TestHub::tree(GATED, hub_tree(true, Vec::new())), refused])
}

#[test]
fn a_hidden_hash_is_checked_by_size_only_and_the_row_says_so() {
    let stand = gated_stand("gated");
    stand.lay(GATED, "BF16", content());
    let today = HubBrowser::of(&stand.app).list_files(GATED);
    assert_eq!(today["safetensors"]["format"], json!("SAFETENSORS"), "the setting: a label that is not the copy's folder");
    let job = stand.job_of(GATED);
    let copy = &job["checkpoints"][0];
    assert_eq!(
        copy["folder"],
        json!("Gated-Policy-2B/nvidia/BF16"),
        "the copy is found where it lies, not where today's label would put it"
    );
    assert_eq!(
        copy["files"][BIG],
        json!({"state": "size-only", "hash": "hidden", "expectedSize": 5000, "size": 5000}),
        "neither a pass nor a failure, and nothing computed"
    );
    let hidden: BTreeSet<&str> = copy["files"]
        .as_object()
        .unwrap()
        .iter()
        .filter(|(_, row)| row["state"] == json!("size-only"))
        .map(|(path, _)| path.as_str())
        .collect();
    assert_eq!(hidden, BTreeSet::from([NPZ, BIG, WEIGHTS2]), "every LFS file, and only those");
    assert_eq!(
        (&copy["files"][SMALL]["state"], &copy["files"][SMALL]["hash"]),
        (&json!("same"), &json!("git-sha1")),
        "the ordinary files are still verified by their git ids"
    );
    assert_eq!(copy["summary"], summary(&[("files", 7), ("same", 4), ("size-only", 3)]));
    let plain: i64 = content().iter().filter(|(path, _)| !is_lfs(path)).map(|(_, data)| data.len() as i64).sum();
    assert_eq!(
        (&job["totalFiles"], &job["totalBytes"], &job["bytesDone"]),
        (&json!(4), &json!(plain), &json!(plain)),
        "only the ordinary files are read"
    );
}

#[test]
fn a_hidden_hash_still_catches_a_wrong_size_and_cannot_catch_other_bytes() {
    let stand = gated_stand("gated-size");
    let mut files = content();
    files.insert(BIG, vec![b'W'; 4000]);
    files.insert(WEIGHTS2, vec![b'X'; 3000]);
    stand.lay(GATED, "BF16", files);
    let rows = stand.job_of(GATED)["checkpoints"][0]["files"].clone();
    assert_eq!(rows[BIG]["state"], json!("wrong-size"));
    assert_eq!(
        rows[WEIGHTS2]["state"],
        json!("size-only"),
        "the limit, said out loud: the row stays size-only, which is NOT verified"
    );
    assert!(rows[WEIGHTS2].get("sha256").is_none());
}

#[test]
fn a_copy_that_needs_no_reading_still_answers() {
    let stand = gated_stand("no-reading");
    stand.lay(GATED, "BF16", [(BIG, content()[BIG].clone())]);
    let job = stand.job_of(GATED);
    assert_eq!(job["checkpoints"][0]["summary"], summary(&[("files", 7), ("missing", 6), ("size-only", 1)]));
    assert_eq!((&job["totalFiles"], &job["done"], &job["error"]), (&json!(0), &json!(true), &Value::Null));
}

#[test]
fn every_folder_holding_a_file_of_the_plan_is_a_copy_and_a_gguf_or_hidden_folder_is_not() {
    let stand = Stand::of_tree("labels", REPO, hub_tree(false, Vec::new()));
    stand.lay(REPO, "BF16", content());
    stand.lay(REPO, "SAFETENSORS", [(SMALL, content()[SMALL].clone())]);
    stand.lay(REPO, "Q4_K_M", [("Robot-3B-Q4_K_M.gguf", vec![b'G'; 40])]);
    stand.lay(REPO, ".hidden", content());
    stand.lay(REPO, "#recycle", content());
    stand.lay(REPO, "@eaDir", content());
    let job = stand.job_of(REPO);
    let copies = job["checkpoints"].as_array().unwrap();
    let folders: Vec<&Value> = copies.iter().map(|copy| &copy["folder"]).collect();
    assert_eq!(folders, [&json!("Robot-3B/acme/BF16"), &json!("Robot-3B/acme/SAFETENSORS")], "in order");
    assert_eq!(copies[0]["summary"], summary(&[("files", 7), ("same", 7)]), "each copy answers on its own");
    assert_eq!(
        copies[1]["summary"],
        summary(&[("files", 7), ("same", 1), ("missing", 6)]),
        "the one with a single file names the other six"
    );
    assert_eq!(job["files"], json!({}), "the GGUF lying beside is no row: the repository lists none");
}

#[test]
fn a_link_is_the_file_it_leads_to_and_a_dead_link_or_a_folder_is_not_there() {
    let stand = Stand::of_tree("links", REPO, hub_tree(false, Vec::new()));
    let mut files = content();
    files.remove(SMALL);
    files.remove("model.safetensors.index.json");
    files.remove("SUCCESS");
    stand.lay(REPO, "BF16", files);
    let (models, base) = (stand.app.models_dir(), stand.base(REPO, "BF16"));
    std::fs::create_dir(base.join("SUCCESS")).unwrap();
    std::fs::create_dir(models.join("shared")).unwrap();
    std::fs::write(models.join("shared").join(SMALL), &content()[SMALL]).unwrap();
    std::os::unix::fs::symlink("../../../shared/config.json", base.join(SMALL)).unwrap();
    std::os::unix::fs::symlink("../../../shared/nowhere.json", base.join("model.safetensors.index.json")).unwrap();
    let rows = stand.job_of(REPO)["checkpoints"][0]["files"].clone();
    assert_eq!(rows[SMALL]["state"], json!("same"), "a link to a file with the right bytes is that file");
    assert_eq!(rows["model.safetensors.index.json"]["state"], json!("missing"), "a link to nothing is a file that is not there");
    assert_eq!(rows["SUCCESS"]["state"], json!("missing"), "a folder where the file should be is not the file");
}

#[test]
fn a_path_of_dots_is_looked_up_inside_the_copy_and_never_finds_what_lies_outside() {
    let escape = TestHub::plain("../../up.json", 2, &git_id(b"{}"));
    let stand = Stand::of_tree("escape", REPO, hub_tree(false, vec![escape]));
    stand.lay(REPO, "BF16", content());
    std::fs::write(stand.app.models_dir().join("Robot-3B/up.json"), b"{}").unwrap();
    let rows = stand.job_of(REPO)["checkpoints"][0]["files"].clone();
    assert_eq!(rows["../../up.json"]["state"], json!("missing"));
    stand.lay(REPO, "BF16", [("up.json", b"{}".to_vec())]);
    let job = stand.job_of(REPO);
    assert_eq!(job["checkpoints"][0]["files"]["../../up.json"]["state"], json!("same"), "the file it names inside is the one");
}

#[test]
fn a_file_that_cannot_even_be_looked_at_is_unreadable_and_no_size_is_made_up() {
    let stand = Stand::of_tree("no-look", REPO, hub_tree(false, Vec::new()));
    let mut files = content();
    files.remove(SMALL);
    stand.lay(REPO, "BF16", files);
    // A link to itself: the look fails as it fails for a share that refuses, and for root too.
    std::os::unix::fs::symlink(SMALL, stand.base(REPO, "BF16").join(SMALL)).unwrap();
    let copy = stand.job_of(REPO)["checkpoints"][0].clone();
    let row = &copy["files"][SMALL];
    assert_eq!(row["state"], json!("unreadable"), "{row}");
    assert!(Coerce::truthy(row.get("error")), "with the reason: {row}");
    assert!(row.get("size").is_none(), "{row}");
    assert_eq!(
        copy["summary"],
        summary(&[("files", 7), ("same", 6), ("unreadable", 1)]),
        "not called missing, and the six others are checked"
    );
}

#[test]
fn a_file_that_vanishes_between_the_look_and_the_read_is_unreadable() {
    let stand = Stand::of_tree("vanish", REPO, hub_tree(false, Vec::new()));
    stand.lay(REPO, "BF16", content());
    let listing = HubBrowser::of(&stand.app).list_files(REPO);
    let copies = CheckpointCopy::find(&stand.app.models_dir(), REPO, listing.get("safetensors")).unwrap();
    std::fs::remove_file(stand.base(REPO, "BF16").join(WEIGHTS2)).unwrap();
    let job = stand.start(REPO, copies);
    let row = &job["checkpoints"][0]["files"][WEIGHTS2];
    assert_eq!((&row["state"], &row["size"]), (&json!("unreadable"), &json!(3000)), "not differs, not missing: {row}");
    assert!(Coerce::truthy(row.get("error")), "with the reason: {row}");
    assert_eq!((&job["done"], &job["error"]), (&json!(true), &Value::Null), "one row does not stop the job");
    assert_eq!(job["checkpoints"][0]["summary"], summary(&[("files", 7), ("same", 6), ("unreadable", 1)]));
}

/// A job as `start` would keep it before its thread has read a byte, with `works` still to read.
fn held_job(stand: &Stand, id: &str) -> Vec<Work> {
    let mut files = content();
    files.remove(WEIGHTS2);
    stand.lay(REPO, "BF16", files);
    let listing = HubBrowser::of(&stand.app).list_files(REPO);
    let copies = CheckpointCopy::find(&stand.app.models_dir(), REPO, listing.get("safetensors")).unwrap();
    let (works, _, results) = ModelVerify::work_of(&[], &json!({}), copies);
    let doc = json!({"id": id, "repo": REPO, "done": false, "error": null, "files": {}, "checkpoints": [], "totalFiles": works.len(), "bytesDone": 0, "startedAt": 1.0, "finishedAt": null});
    let verify = ModelVerify::of(&stand.app);
    verify.jobs().push((id.to_string(), VerifyJob { doc: Coerce::fields(&doc), results }));
    works
}

#[test]
fn a_half_read_copy_does_not_read_as_a_whole_one() {
    let stand = Stand::of_tree("pending", REPO, hub_tree(false, Vec::new()));
    let works = held_job(&stand, "job-1");
    let (_, mid) = RouteCall::get(&stand.app, &HfRoutes::ROUTES, "/api/hf/verify?job=job-1");
    let copy = &mid["job"]["checkpoints"][0];
    assert_eq!(mid["job"]["done"], json!(false));
    assert_eq!(
        copy["summary"],
        summary(&[("files", 7), ("pending", 6), ("missing", 1)]),
        "the missing file is in, six are still to come"
    );
    assert_eq!(copy["files"].as_object().unwrap().keys().collect::<Vec<_>>(), [WEIGHTS2], "only the rows that are settled");
    ModelVerify::of(&stand.app).run("job-1", works);
    let job = ModelVerify::of(&stand.app).status("job-1", "")["job"].clone();
    assert_eq!(
        (&job["done"], &job["checkpoints"][0]["summary"]),
        (&json!(true), &summary(&[("files", 7), ("same", 6), ("missing", 1)])),
        "ended, nothing pending"
    );
}

#[test]
fn a_second_start_on_a_repository_being_verified_is_the_same_job() {
    let stand = Stand::of_tree("same-job", REPO, hub_tree(false, Vec::new()));
    let _works = held_job(&stand, "job-1");
    let answer = RouteCall::post(&stand.app, &HfRoutes::ROUTES, "/api/hf/verify", json!({"repo": REPO})).1;
    assert_eq!(answer, json!({"ok": true, "jobId": "job-1"}), "no second pass over the same files");
    let other = ModelVerify::of(&stand.app)
        .start("another/repo", &[json!({"name": "x.gguf"})], &json!({"x.gguf": {"path": "/nowhere/x.gguf"}}), Vec::new())
        .unwrap();
    assert_ne!(other, "job-1", "another repository's is its own");
    stand.ended(&other);
    let verify = ModelVerify::of(&stand.app);
    verify.with_job("job-1", |job| {
        job.doc.insert("done".to_string(), json!(true));
    });
    let (answer, job) = stand.verify(REPO);
    assert_ne!(answer["jobId"], json!("job-1"), "a job that ended is not the one a new start joins");
    assert_eq!(job.unwrap()["done"], json!(true));
}

/// A repository with both kinds of file.
fn both_tree() -> Vec<Value> {
    vec![
        TestHub::lfs("Both-7B-Q4_K_M.gguf", 400, &sha(&[b'G'; 400])),
        TestHub::lfs("mmproj-Both-7B-f16.gguf", 60, &TestHub::mask()),
        TestHub::plain(SMALL, 9, &git_id(b"{\"a\": 1}\n")),
        TestHub::lfs("model.safetensors", 900, &sha(&[b'S'; 900])),
    ]
}

const BOTH: &str = "acme/Both-7B";

#[test]
fn a_repository_with_both_kinds_answers_each_in_its_own_section() {
    let stand = Stand::of_tree("both", BOTH, both_tree());
    stand.lay(BOTH, "Q4_K_M", [("Both-7B-Q4_K_M.gguf", vec![b'G'; 400]), ("mmproj-Both-7B-f16.gguf", vec![b'M'; 60])]);
    stand.lay(BOTH, "BF16", [(SMALL, b"{\"a\": 1}\n".to_vec()), ("model.safetensors", vec![b'S'; 900])]);
    let job = stand.job_of(BOTH);
    assert_eq!(job["files"].as_object().unwrap().keys().collect::<Vec<_>>(), ["Both-7B-Q4_K_M.gguf", "mmproj-Both-7B-f16.gguf"]);
    assert_eq!(
        job["files"]["Both-7B-Q4_K_M.gguf"],
        json!({"state": "same", "sha256": sha(&[b'G'; 400]), "expected": sha(&[b'G'; 400]), "hash": "sha256"})
    );
    let mask_row = json!({"state": "unknown", "sha256": sha(&[b'M'; 60]), "expected": "", "hash": "hidden"});
    assert_eq!(
        job["files"]["mmproj-Both-7B-f16.gguf"], mask_row,
        "a GGUF whose hash is hidden is unknown: it used to be a different file, from the mask"
    );
    assert_eq!(job["checkpoints"].as_array().unwrap().len(), 1);
    assert_eq!(job["checkpoints"][0]["folder"], json!("Both-7B/acme/BF16"));
    assert_eq!(job["checkpoints"][0]["summary"], summary(&[("files", 2), ("same", 2)]));
    assert_eq!((&job["totalFiles"], &job["totalBytes"]), (&json!(4), &json!(400 + 60 + 9 + 900)), "one job, one progress");
}

#[test]
fn a_gguf_copy_of_a_repository_that_also_has_a_checkpoint_is_not_files_missing() {
    let stand = Stand::of_tree("gguf-only", BOTH, both_tree());
    stand.lay(BOTH, "Q4_K_M", [("Both-7B-Q4_K_M.gguf", vec![b'G'; 400])]);
    let job = stand.job_of(BOTH);
    assert_eq!(job["checkpoints"], json!([]), "the checkpoint was never downloaded: no copy, no rows");
    assert_eq!(job["files"]["Both-7B-Q4_K_M.gguf"]["state"], json!("same"));
    assert!(
        job["files"].get("mmproj-Both-7B-f16.gguf").is_none(),
        "a file not on the disk is not verified: there is nothing to hash"
    );
}

#[test]
fn nothing_of_the_plan_on_disk_is_a_refusal_and_no_job() {
    for (name, lay) in [("none", &[][..]), ("notes", &["notes.txt", "README.md"][..])] {
        let stand = Stand::of_tree(&format!("nothing-{name}"), REPO, hub_tree(false, Vec::new()));
        stand.lay(REPO, "BF16", lay.iter().map(|file| (*file, b"x".to_vec())));
        let (answer, job) = stand.verify(REPO);
        assert_eq!(answer, json!({"ok": false, "error": "nothing of this repo is on disk"}), "{name}");
        assert!(job.is_none());
    }
    let stand = Stand::of_tree("nothing-empty", REPO, hub_tree(false, Vec::new()));
    std::fs::create_dir_all(stand.base(REPO, "BF16")).unwrap();
    assert_eq!(
        stand.verify(REPO).0,
        json!({"ok": false, "error": "nothing of this repo is on disk"}),
        "a folder of the model with nothing in it"
    );
}

#[test]
fn a_hub_that_refuses_and_an_invalid_id_are_the_refusals_they_were() {
    let stand = Stand::new("refusals", vec![TestHub::refused(&format!("/api/models/{REPO}/tree/main"), "404 Not Found")]);
    stand.lay(REPO, "BF16", content());
    assert_eq!(
        stand.verify(REPO).0,
        json!({"ok": false, "error": "HTTP Error 404: Not Found"}),
        "no claim about what is on the disk"
    );
    assert_eq!(stand.verify("no-slash").0, json!({"ok": false, "error": "invalid repo id"}));
    assert_eq!(stand.verify("").0, json!({"ok": false, "error": "invalid repo id"}));
}

#[test]
fn a_folder_that_cannot_be_read_is_a_refusal_and_not_nothing_on_disk() {
    let stand = Stand::of_tree("unreadable-folder", REPO, hub_tree(false, Vec::new()));
    let model = stand.app.models_dir().join("Robot-3B");
    std::fs::create_dir_all(&model).unwrap();
    // A link to itself refuses a read as a share that went bad does, and for root too.
    std::os::unix::fs::symlink("acme", model.join("acme")).unwrap();
    let (answer, job) = stand.verify(REPO);
    assert_eq!(answer["ok"], json!(false));
    let said = Coerce::text(answer.get("error"));
    assert!(said.contains("cannot read Robot-3B/acme") && !said.contains("on disk"), "{said}");
    assert!(job.is_none());
    let plan = json!({"files": [{"path": "a", "name": "a", "size": 1}]});
    let refused = CheckpointCopy::find(&stand.app.models_dir(), REPO, Some(&plan)).unwrap_err();
    assert_eq!(refused.status, 500);
}

#[test]
fn a_repository_with_no_plan_or_no_folder_has_no_copy_to_find_and_no_exception() {
    let stand = Stand::new("no-plan", Vec::new());
    let models = stand.app.models_dir();
    let plan = json!({"files": [{"path": "a", "name": "a", "size": 1}]});
    assert!(CheckpointCopy::find(&models, REPO, None).unwrap().is_empty());
    assert!(CheckpointCopy::find(&models, REPO, Some(&json!({"files": []}))).unwrap().is_empty());
    assert!(CheckpointCopy::find(&models, REPO, Some(&plan)).unwrap().is_empty(), "no such model folder");
    assert!(CheckpointCopy::find(&models.join("no-such-dir"), REPO, Some(&plan)).unwrap().is_empty());
    std::fs::write(models.join("Robot-3B"), b"not a folder").unwrap();
    assert!(CheckpointCopy::find(&models, REPO, Some(&plan)).unwrap().is_empty(), "a file where the model's folder should be");
}

fn sized_file(local: Option<Value>, hash: HubHash) -> CheckpointFile {
    CheckpointFile { repo_path: "w.safetensors".to_string(), expected_size: 10, hub_hash: hash, local }
}

#[test]
fn the_digest_decides_same_or_differs_and_nothing_else_does() {
    let hash = HubHash::Sha256("a".repeat(64));
    let file = sized_file(Some(json!({"path": "/x", "size": 10, "mtime": 1})), hash.clone());
    assert_eq!(file.judged(&"a".repeat(64))["state"], json!("same"));
    assert_eq!(file.judged(&"b".repeat(64))["state"], json!("differs"));
    assert!(
        file.settled().is_none(),
        "a file of the right size with a hash to hold it against is the one case that needs reading"
    );
    let git = sized_file(Some(json!({"size": 10})), HubHash::GitSha1("c".repeat(40)));
    assert!(git.settled().is_none());
    assert_eq!(git.judged(&"c".repeat(40))["gitSha1"], json!("c".repeat(40)), "and says which digest it is");
}

#[test]
fn no_hash_from_the_hub_is_size_only_whatever_the_reason_and_the_row_names_it() {
    let row = |hash| sized_file(Some(json!({"size": 10})), hash).settled().unwrap();
    assert_eq!((&row(HubHash::Hidden)["state"], &row(HubHash::Hidden)["hash"]), (&json!("size-only"), &json!("hidden")));
    assert_eq!((&row(HubHash::None)["state"], &row(HubHash::None)["hash"]), (&json!("size-only"), &json!("none")));
}

#[test]
fn a_file_is_judged_in_order_before_any_question_of_hashes() {
    let sha = HubHash::Sha256("a".repeat(64));
    assert_eq!(sized_file(None, sha.clone()).settled().unwrap()["state"], json!("missing"));
    assert_eq!(
        sized_file(None, HubHash::Hidden).settled().unwrap()["state"],
        json!("missing"),
        "a hidden hash does not make a file there"
    );
    assert_eq!(
        sized_file(Some(json!({"path": "/x", "error": "denied"})), HubHash::Hidden).settled().unwrap()["state"],
        json!("unreadable")
    );
    assert_eq!(
        sized_file(Some(json!({"size": 9})), HubHash::Hidden).settled().unwrap()["state"],
        json!("wrong-size"),
        "a wrong size is caught without the hash"
    );
    assert_eq!(sized_file(Some(json!({"size": 11})), sha).settled().unwrap()["state"], json!("wrong-size"));
}

#[test]
fn a_copy_with_nothing_in_its_plan_summarises_as_nothing_and_not_as_a_pass() {
    let result = CheckpointResult { folder: "a/b/c".to_string(), planned: 0, rows: Map::new() };
    assert_eq!(result.snapshot()["summary"], summary(&[]));
}

#[test]
fn a_file_lands_inside_its_checkpoint() {
    assert_eq!(CheckpointLayout::repo_folder("a/b"), "b/a");
    assert_eq!(CheckpointLayout::repo_folder("b"), "b/unknown");
    assert_eq!(CheckpointLayout::file_path("x/../y/z.bin", "z.bin"), "x/y/z.bin");
    assert_eq!(CheckpointLayout::file_path("z.bin", "z.bin"), "z.bin");
    assert_eq!(CheckpointLayout::file_path("../../up.json", "up.json"), "up.json");
    assert_eq!(CheckpointLayout::file_path("./a//b/c", "c"), "a/b/c");
}

/// A GGUF file on the disk and its row of a listing.
fn local_row(path: &std::path::Path) -> Value {
    json!({"size": std::fs::metadata(path).unwrap().len(), "path": path.to_string_lossy()})
}

#[test]
fn a_gguf_is_same_differs_or_unknown_by_the_hubs_sha256_and_never_matched_by_silence() {
    let stand = Stand::new("gguf-table", Vec::new());
    let dir = stand.folder.path.join("files");
    std::fs::create_dir(&dir).unwrap();
    let (good, bad, blank) = (dir.join("good.gguf"), dir.join("bad.gguf"), dir.join("no-oid.gguf"));
    let weights = b"weights".repeat(1000);
    std::fs::write(&good, &weights).unwrap();
    std::fs::write(&bad, b"other".repeat(1000)).unwrap();
    std::fs::write(&blank, b"small").unwrap();
    let files = [
        json!({"name": "good.gguf", "size": weights.len(), "oid": sha(&weights)}),
        json!({"name": "bad.gguf", "size": 5000, "oid": "0".repeat(64)}),
        json!({"name": "no-oid.gguf", "size": 5, "oid": ""}),
        json!({"name": "not-here.gguf", "size": 10, "oid": "a".repeat(64)}),
    ];
    let local = json!({"good.gguf": local_row(&good), "bad.gguf": local_row(&bad), "no-oid.gguf": local_row(&blank)});
    let id = ModelVerify::of(&stand.app).start("author/repo", &files, &local, Vec::new()).unwrap();
    let job = stand.ended(&id);
    assert_eq!((&job["done"], &job["error"]), (&json!(true), &Value::Null));
    assert_eq!(job["files"]["good.gguf"]["state"], json!("same"));
    assert_eq!(job["files"]["bad.gguf"]["state"], json!("differs"));
    assert_eq!(
        job["files"]["no-oid.gguf"]["state"],
        json!("unknown"),
        "no oid on the hub: we do not know, and it is NOT matched"
    );
    assert!(job["files"].get("not-here.gguf").is_none(), "a file not on the disk is not verified");
    let sizes = weights.len() + 5000 + 5;
    assert_eq!((&job["totalFiles"], &job["totalBytes"], &job["bytesDone"]), (&json!(3), &json!(sizes), &json!(sizes)));
    assert_eq!(job["files"]["bad.gguf"]["expected"], json!("0".repeat(64)), "both sides in the answer");
    assert_eq!(job["files"]["bad.gguf"]["sha256"], json!(sha(&b"other".repeat(1000))));
}

#[test]
fn a_git_id_never_passes_a_gguf_for_a_gguf_is_held_against_its_sha256_alone() {
    let stand = Stand::new("gguf-git", Vec::new());
    let path = stand.folder.path.join("tiny.gguf");
    std::fs::write(&path, b"tiny").unwrap();
    let files = [json!({"name": "tiny.gguf", "size": 4, "oid": "", "gitOid": git_id(b"tiny")})];
    let id =
        ModelVerify::of(&stand.app).start("author/tiny", &files, &json!({"tiny.gguf": local_row(&path)}), Vec::new()).unwrap();
    let row = stand.ended(&id)["files"]["tiny.gguf"].clone();
    assert_eq!((&row["state"], &row["hash"], &row["expected"]), (&json!("unknown"), &json!("git-sha1"), &json!("")));
}

#[test]
fn a_gguf_that_vanishes_between_the_list_and_the_read_is_unreadable_and_says_why() {
    let stand = Stand::new("gguf-gone", Vec::new());
    let path = stand.folder.path.join("gone.gguf");
    let files = [json!({"name": "gone.gguf", "size": 1, "oid": "b".repeat(64)})];
    let local = json!({"gone.gguf": {"size": 1, "mtime": 1, "path": path.to_string_lossy()}});
    let id = ModelVerify::of(&stand.app).start("author/repo2", &files, &local, Vec::new()).unwrap();
    let job = stand.ended(&id);
    let row = &job["files"]["gone.gguf"];
    assert_eq!(row["state"], json!("unreadable"), "not differs: {row}");
    assert!(Coerce::truthy(row.get("error")));
    assert_eq!((&job["done"], &job["error"]), (&json!(true), &Value::Null), "one row does not end the job");
}

#[test]
fn a_gguf_whose_look_failed_is_not_read_for_it_has_no_path() {
    let stand = Stand::new("gguf-no-path", Vec::new());
    let files = [json!({"name": "dead.gguf", "size": 1, "oid": "b".repeat(64)})];
    let refused = ModelVerify::of(&stand.app).start("author/dead", &files, &json!({"dead.gguf": {}}), Vec::new()).unwrap_err();
    assert_eq!(refused.status, 400);
}

#[test]
fn nothing_to_check_is_a_refusal_and_no_repository_a_400() {
    let stand = Stand::new("refused-start", Vec::new());
    let files = [json!({"name": "a.gguf", "size": 1, "oid": "b".repeat(64)})];
    let verify = ModelVerify::of(&stand.app);
    let nothing = verify.start("author/empty", &files, &json!({}), Vec::new()).unwrap_err();
    assert_eq!((nothing.status, nothing.message.as_str()), (400, "nothing of this repo is on disk"));
    let no_repo = verify.start("  ", &files, &json!({"a.gguf": {"path": "/x"}}), Vec::new()).unwrap_err();
    assert_eq!((no_repo.status, no_repo.message.as_str()), (400, "missing repo"));
    assert_eq!(verify.status("", "author/empty"), json!({"ok": true, "job": null}), "and no empty job that reads as checked");
}

#[test]
fn a_job_is_found_by_its_repository_and_an_unknown_one_is_none() {
    let stand = Stand::new("status", Vec::new());
    let path = stand.folder.path.join("x.gguf");
    std::fs::write(&path, b"x").unwrap();
    let files = [json!({"name": "x.gguf", "size": 1, "oid": ""})];
    let verify = ModelVerify::of(&stand.app);
    let id = verify.start("author/repo", &files, &json!({"x.gguf": local_row(&path)}), Vec::new()).unwrap();
    stand.ended(&id);
    assert_eq!(verify.status("", "author/repo")["job"]["id"], json!(id), "the page asks by the repository");
    assert_eq!(verify.status("no-such-job", ""), json!({"ok": true, "job": null}));
    assert_eq!(verify.status("", "author/other"), json!({"ok": true, "job": null}));
    let (status, said) = RouteCall::get(&stand.app, &HfRoutes::ROUTES, "/api/hf/verify?repo=author/repo");
    assert_eq!((status, &said["job"]["id"]), (200, &json!(id)));
}

/// A file's time, set by hand: a test does not wait for a clock to move.
fn stamped(path: &std::path::Path, nanos: u64) {
    let when = SystemTime::UNIX_EPOCH + Duration::from_secs(1_780_000_000) + Duration::from_nanos(nanos);
    std::fs::File::options().write(true).open(path).unwrap().set_modified(when).unwrap();
}

/// The digest, and what the job's bar heard of it.
fn digest_with_progress(verify: &ModelVerify<'_>, path: &std::path::Path, git: bool) -> (String, Vec<i64>) {
    let mut heard = Vec::new();
    let value = verify.file_digest(path.to_str().unwrap(), git, |count| heard.push(count)).unwrap();
    (value, heard)
}

#[test]
fn a_git_id_is_what_git_says_of_the_file_and_a_sha256_of_the_bytes() {
    let stand = Stand::new("digests", Vec::new());
    let (hello, empty) = (stand.folder.path.join("hello"), stand.folder.path.join("empty"));
    std::fs::write(&hello, b"hello world\n").unwrap();
    std::fs::write(&empty, b"").unwrap();
    let verify = ModelVerify::of(&stand.app);
    assert_eq!(digest_with_progress(&verify, &hello, true).0, HELLO_GIT_ID);
    assert_eq!(digest_with_progress(&verify, &empty, true).0, EMPTY_GIT_ID, "an empty file's is the well-known one");
    assert_eq!(digest_with_progress(&verify, &hello, false).0, HELLO_SHA256);
    assert_ne!(HELLO_GIT_ID, Sha1::of(b"hello world\n"), "the sha1 of the bytes alone is not the git id");
}

#[test]
fn one_file_has_two_digests_and_the_memory_keeps_them_apart() {
    let stand = Stand::new("two-kinds", Vec::new());
    let hello = stand.folder.path.join("hello");
    std::fs::write(&hello, b"hello world\n").unwrap();
    let verify = ModelVerify::of(&stand.app);
    assert_eq!(digest_with_progress(&verify, &hello, false).0, HELLO_SHA256);
    assert_eq!(
        digest_with_progress(&verify, &hello, true).0,
        HELLO_GIT_ID,
        "asking for the other kind later does not answer with the first"
    );
    assert_eq!(digest_with_progress(&verify, &hello, false).0, HELLO_SHA256);
}

#[test]
fn a_rewritten_file_is_read_again_though_its_size_or_its_second_stayed() {
    let stand = Stand::new("rewritten", Vec::new());
    let path = stand.folder.path.join("good.gguf");
    let verify = ModelVerify::of(&stand.app);
    std::fs::write(&path, b"weights").unwrap();
    stamped(&path, 1_000);
    assert_eq!(digest_with_progress(&verify, &path, false).0, sha(b"weights"));
    std::fs::write(&path, b"WEIGHTS").unwrap();
    stamped(&path, 2_000);
    assert_eq!(
        digest_with_progress(&verify, &path, false).0,
        sha(b"WEIGHTS"),
        "the same size in the same second: the time is kept to the nanosecond"
    );
    std::fs::write(&path, b"longer weights").unwrap();
    stamped(&path, 2_000);
    assert_eq!(digest_with_progress(&verify, &path, false).0, sha(b"longer weights"), "the same time, another size");
}

#[test]
fn a_digest_known_already_is_not_read_again_and_the_bar_hears_the_whole_size_at_once() {
    let stand = Stand::new("progress", Vec::new());
    let path = stand.folder.path.join("big.gguf");
    let data = vec![b'x'; ModelVerify::CHUNK + 5];
    std::fs::write(&path, &data).unwrap();
    let verify = ModelVerify::of(&stand.app);
    let (first, heard) = digest_with_progress(&verify, &path, false);
    assert_eq!(heard, [ModelVerify::CHUNK as i64, 5], "the first read, chunk by chunk");
    let (second, heard) = digest_with_progress(&verify, &path, false);
    assert_eq!((second, heard), (first, vec![data.len() as i64]));
}

#[test]
fn a_file_that_is_not_there_has_no_digest() {
    let stand = Stand::new("no-digest", Vec::new());
    let path = stand.folder.path.join("gone");
    assert!(ModelVerify::of(&stand.app).file_digest(path.to_str().unwrap(), false, |_| {}).is_err());
}
