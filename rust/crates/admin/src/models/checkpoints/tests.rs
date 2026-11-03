//! What the controller reads off its models folder. Above all `GET /api/models` and `GET /api/models/download`, which a scout fetches a model by: both read the
//! folder the configuration names. They once read `LLAMA_HOME/models`, the same place only while the configuration says so: in a container the list was empty and every
//! download a 404 for a file the picker had just offered.

use super::*;
use crate::tests::{TestApp, TestFolder};
use crate::web::Exchange;
use std::fs;
use std::io::{BufReader, Read};
use std::net::{Shutdown, TcpListener, TcpStream};
use wire::{Headers, Percent, RequestHead};

const MIB: usize = 1_048_576;

/// What a download answered: its status, its head as it was sent, and its bytes.
struct Answer {
    status: u16,
    head: String,
    body: Vec<u8>,
}

/// `GET /api/models/download` with this query.
fn asked(app: &App, query: &str) -> Answer {
    asked_with(app, query, Headers::new())
}

/// The same with these fields.
fn asked_with(app: &App, query: &str, headers: Headers) -> Answer {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let mut client = TcpStream::connect(listener.local_addr().unwrap()).unwrap();
    let (server, _) = listener.accept().unwrap();
    let reader = std::thread::spawn(move || {
        let mut raw = Vec::new();
        client.read_to_end(&mut raw).unwrap();
        raw
    });
    let mut source = BufReader::new(server.try_clone().unwrap());
    let head = RequestHead { method: "GET".to_string(), target: format!("/api/models/download{query}"), headers };
    let mut exchange = Exchange::new(head, &mut source, &server, "127.0.0.1".to_string(), 0, "test");
    ModelCheckpoints::of(app).serve_file(&mut exchange).unwrap();
    drop(exchange);
    server.shutdown(Shutdown::Both).unwrap();
    let raw = reader.join().unwrap();
    let cut = raw.windows(4).position(|four| four == b"\r\n\r\n").unwrap();
    let head = String::from_utf8_lossy(raw.get(..cut).unwrap()).into_owned();
    Answer { status: head.split_whitespace().nth(1).unwrap().parse().unwrap(), head, body: raw.get(cut + 4..).unwrap().to_vec() }
}

/// A download of `rel`, as a scout asks for it.
fn served(app: &App, rel: &str) -> Answer {
    asked(app, &format!("?path={}", Percent::encode_path(rel)))
}

fn put(root: &Path, rel: &str, size: usize, fill: u8) -> PathBuf {
    let path = root.join(rel);
    fs::create_dir_all(path.parent().unwrap()).unwrap();
    fs::write(&path, vec![fill; size]).unwrap();
    path
}

/// A controller whose folder holds a model, its projector, a vocabulary, three small files and a name with spaces; and a file that lies only where the old code read.
fn shelf(name: &str) -> (TestFolder, std::sync::Arc<App>) {
    let folder = TestFolder::new(name);
    let home = folder.path.join("home");
    let app = TestApp::over(&folder.path, &[("LLAMA_HOME", home.to_str().unwrap())]);
    let models = app.models_dir();
    put(&models, "Qwen/unsloth/Q4_K_M/qwen-Q4_K_M.gguf", 3 * MIB, b'q');
    put(&models, "Qwen/unsloth/Q4_K_M/mmproj-F16.gguf", 2 * MIB, b'x');
    put(&models, "projectors/vision-projector.gguf", 2 * MIB, b'x');
    put(&models, "vocabs/ggml-vocab-llama.gguf", 2 * MIB, b'x');
    put(&models, "stubs/tiny.gguf", 1023, b'x');
    put(&models, "stubs/edge.gguf", 1024, b'x');
    put(&models, "stubs/small.gguf", 500_000, b'x');
    put(&models, "stubs/mid.gguf", 2_883_584, b'x');
    put(&models, "My Model/Q8_0/my model-Q8_0.gguf", 4 * MIB, b'm');
    put(&models, "notes/readme.txt", 5000, b'x');
    put(&home, "models/stale/only-here.gguf", 3 * MIB, b's');
    (folder, app)
}

fn paths_of(listing: &Value) -> Vec<String> {
    listing["models"].as_array().unwrap().iter().map(|row| row["path"].as_str().unwrap().to_string()).collect()
}

#[test]
fn the_list_is_of_the_configured_folder_and_of_its_models_alone() {
    let (_folder, app) = shelf("list");
    let listing = ModelCheckpoints::of(&app).gguf_models();
    assert_eq!((&listing["ok"], listing["modelsDir"].as_str()), (&json!(true), app.models_dir().to_str()));
    let paths = paths_of(&listing);
    let mut sorted = paths.clone();
    sorted.sort();
    assert_eq!(paths, sorted, "in order of their paths");
    assert_eq!(
        paths,
        [
            "My Model/Q8_0/my model-Q8_0.gguf",
            "Qwen/unsloth/Q4_K_M/qwen-Q4_K_M.gguf",
            "stubs/edge.gguf",
            "stubs/mid.gguf",
            "stubs/small.gguf",
        ],
        "no projector or vocabulary, no file under 1 KiB, nothing but .gguf, and nothing from under LLAMA_HOME/models"
    );
    let row = |path: &str| listing["models"].as_array().unwrap().iter().find(|row| row["path"] == path).unwrap().clone();
    assert_eq!(
        row("Qwen/unsloth/Q4_K_M/qwen-Q4_K_M.gguf"),
        json!({"path": "Qwen/unsloth/Q4_K_M/qwen-Q4_K_M.gguf", "name": "qwen-Q4_K_M.gguf", "sizeMiB": 3, "dir": "Qwen/unsloth/Q4_K_M"}),
        "the path from the folder, the name, the size, the folder it sits in"
    );
    assert_eq!(
        row("stubs/small.gguf")["sizeMiB"],
        json!(0),
        "half a MiB is listed with a size of 0, not dropped: only a file under 1 KiB is"
    );
    assert_eq!(row("stubs/mid.gguf")["sizeMiB"], json!(3), "sizes are rounded, not cut");
    assert_eq!(row("stubs/edge.gguf")["sizeMiB"], json!(0), "a file of 1 KiB exactly is a model");
}

#[test]
fn a_download_is_the_exact_bytes_and_says_what_they_are() {
    let (_folder, app) = shelf("bytes");
    let got = served(&app, "Qwen/unsloth/Q4_K_M/qwen-Q4_K_M.gguf");
    assert_eq!(got.status, 200);
    assert_eq!(got.body, vec![b'q'; 3 * MIB]);
    for field in [
        "Content-Type: application/octet-stream",
        "Content-Length: 3145728",
        "Content-Disposition: attachment; filename=\"qwen-Q4_K_M.gguf\"",
    ] {
        assert!(got.head.contains(field), "{field} in {}", got.head);
    }
    assert_eq!(
        served(&app, "My Model/Q8_0/my model-Q8_0.gguf").body,
        vec![b'm'; 4 * MIB],
        "a name with spaces reads back to the same file"
    );
}

#[test]
fn every_row_the_list_offers_can_be_downloaded() {
    let (_folder, app) = shelf("offers");
    let listing = ModelCheckpoints::of(&app).gguf_models();
    let models = app.models_dir();
    assert!(!paths_of(&listing).is_empty());
    for path in paths_of(&listing) {
        let got = served(&app, &path);
        assert_eq!((got.status, got.body.len() as u64), (200, fs::metadata(models.join(&path)).unwrap().len()), "{path}");
    }
}

#[test]
fn a_file_of_a_library_is_given_too_and_nothing_else_is_reached_that_way() {
    let (folder, app) = shelf("library");
    let library = folder.path.join("nas");
    put(&library, "Far/a/Q4/far.gguf", 3 * MIB, b'f');
    let registry = crate::models::stores::StoreRegistry::of(&app);
    assert!(registry.add(library.to_str().unwrap(), "NAS", true).is_ok());
    registry.statuses(false);
    let got = served(&app, "Far/a/Q4/far.gguf");
    assert_eq!((got.status, got.body.len()), (200, 3 * MIB), "a machine needs no mount of its own: {}", got.head);
    assert!(got.body.iter().all(|byte| *byte == b'f'));
    assert_eq!(served(&app, "Far/a/Q4/not-there.gguf").status, 404, "what a look did not find");
    assert_eq!(served(&app, "Far/a/../a/Q4/far.gguf").status, 404, "the path is a key, not a way to walk");
    let ours = served(&app, "stubs/tiny.gguf");
    assert_eq!((ours.status, ours.body.len()), (200, 1023), "the models folder as ever");
}

#[test]
fn a_download_refuses_what_it_should_not_give() {
    let (folder, app) = shelf("refuses");
    let models = app.models_dir();
    let statuses = |rel: &str| {
        let got = served(&app, rel);
        assert!(got.body.is_empty(), "{rel}: a refusal has no bytes");
        assert!(got.head.contains("Content-Length: 0"), "{rel}: and says so");
        got.status
    };
    let nothing = asked(&app, "");
    assert_eq!((nothing.status, nothing.body.len()), (400, 0), "no path");
    assert_eq!(statuses("   "), 400, "a blank path is no path");
    assert_eq!(statuses("Qwen/unsloth/Q4_K_M/not-there.gguf"), 404, "no such file");
    assert_eq!(statuses("Qwen/unsloth"), 404, "a folder is no file");
    assert_eq!(statuses("stale/only-here.gguf"), 404, "a file that lies only under LLAMA_HOME/models is not given");
    assert_eq!(
        statuses("../home/models/stale/only-here.gguf"),
        403,
        "a path that leaves the folder, though the file it names is there"
    );
    assert_eq!(statuses("Qwen/../../home/models/stale/only-here.gguf"), 403, "and through a folder inside it");
    assert_eq!(statuses("/etc/hosts"), 403, "an absolute path is outside it");
    std::os::unix::fs::symlink(folder.path.join("home/models/stale/only-here.gguf"), models.join("linked.gguf")).unwrap();
    assert_eq!(statuses("linked.gguf"), 403, "a link that leads out of it: a library is read by a scout from its own mount");
    std::os::unix::fs::symlink("nowhere.gguf", models.join("dead.gguf")).unwrap();
    assert_eq!(statuses("dead.gguf"), 404, "a link that leads nowhere");
    std::os::unix::fs::symlink("Qwen/unsloth/Q4_K_M/qwen-Q4_K_M.gguf", models.join("inside.gguf")).unwrap();
    assert_eq!(served(&app, "inside.gguf").body.len(), 3 * MIB, "negative: a link that stays inside is the file it names");
}

#[test]
fn the_folder_of_the_saved_configuration_is_read_over_the_default() {
    let folder = TestFolder::new("saved");
    let app = TestApp::over(&folder.path, &[]);
    let named = folder.path.join("named");
    put(&named, "Named/named.gguf", 2 * MIB, b'n');
    put(&app.paths.default_models_dir, "Default/default.gguf", 2 * MIB, b'd');
    fs::create_dir_all(app.paths.start_script.parent().unwrap()).unwrap();
    fs::write(
        &app.paths.start_script,
        format!("# BEGIN LLAMA CONFIG\nLLAMA_MODELS_DIR=\"{}\"\n# END LLAMA CONFIG\n", named.display()),
    )
    .unwrap();
    assert_eq!(paths_of(&ModelCheckpoints::of(&app).gguf_models()), ["Named/named.gguf"], "the list");
    assert_eq!(served(&app, "Named/named.gguf").body, vec![b'n'; 2 * MIB], "and the download");
    assert_eq!(served(&app, "Default/default.gguf").status, 404, "negative: the default is no part of it");
}

#[test]
fn a_folder_that_is_not_there_is_said_and_nothing_falls_back_on_the_other_one() {
    let folder = TestFolder::new("nowhere");
    let (home, nowhere) = (folder.path.join("home"), folder.path.join("nowhere"));
    put(&home, "models/stale/only-here.gguf", 3 * MIB, b's');
    let app =
        TestApp::over(&folder.path, &[("LLAMA_HOME", home.to_str().unwrap()), ("LLAMA_MODELS_DIR", nowhere.to_str().unwrap())]);
    assert_eq!(
        ModelCheckpoints::of(&app).gguf_models(),
        json!({"ok": false, "error": format!("models dir not found: {}", nowhere.display()), "models": []}),
        "the list says which folder was asked for"
    );
    assert_eq!(served(&app, "stale/only-here.gguf").status, 404, "and a download does not go to the other one");
}

#[test]
fn a_token_of_kv_cache_weighs_what_vllm_counts() {
    // The owner's Cosmos-Reason2-2B: vLLM asked 0.88 GiB for a length of 8192, which is 8192 × this.
    let cosmos = json!({"dtype": "x", "text_config": {"num_hidden_layers": 28, "num_attention_heads": 16, "num_key_value_heads": 8, "head_dim": 128, "hidden_size": 2048, "dtype": "bfloat16"}});
    assert_eq!(ModelCheckpoints::kv_per_token(&cosmos), Some(114_688));
    let omni = json!({"dtype": "bfloat16", "thinker_config": {"text_config": {"num_hidden_layers": 48, "num_attention_heads": 32, "num_key_value_heads": 4, "head_dim": 128}}});
    assert_eq!(ModelCheckpoints::kv_per_token(&omni), Some(98_304), "the dtype of the whole model stands for its text part");
    let plain = json!({"num_hidden_layers": 12, "num_attention_heads": 8, "hidden_size": 1024, "torch_dtype": "float32"});
    assert_eq!(
        ModelCheckpoints::kv_per_token(&plain),
        Some(2 * 12 * 8 * 128 * 4),
        "no head_dim and no kv heads: from the hidden size and the heads"
    );
    for unknown in [
        json!({}),
        json!({"num_hidden_layers": 12}),
        json!({"num_hidden_layers": 12, "num_attention_heads": 8}),
        json!({"num_hidden_layers": 12, "num_attention_heads": 8, "hidden_size": 4}),
    ] {
        assert_eq!(ModelCheckpoints::kv_per_token(&unknown), None, "{unknown}");
    }
}

#[test]
fn a_cells_model_gets_a_short_name() {
    assert_eq!(ModelCheckpoints::display_name("Q/a/b/x.GGUF"), "x.GGUF");
    assert_eq!(ModelCheckpoints::display_name("/m/Qwen/nvidia/NVFP4"), "Qwen");
    assert_eq!(ModelCheckpoints::display_name("~/m/Qwen/other"), "other");
    assert_eq!(ModelCheckpoints::display_name("nvidia/Qwen"), "Qwen");
    assert_eq!(ModelCheckpoints::display_name("Qwen/nvidia/NVFP4"), "Qwen");
    assert_eq!(ModelCheckpoints::display_name(""), "");
}

#[test]
fn a_window_is_found_where_a_family_keeps_it() {
    assert_eq!(ModelCheckpoints::window_of(&json!({"max_position_embeddings": 5})), 5);
    assert_eq!(ModelCheckpoints::window_of(&json!({"thinker_config": {"text_config": {"max_position_embeddings": 7}}})), 7);
    assert_eq!(ModelCheckpoints::window_of(&json!({"max_position_embeddings": true})), 0);
    assert_eq!(ModelCheckpoints::window_of(&json!({})), 0);
}

/// A part of a file, as a machine with no copy reads a model.
#[test]
fn a_part_of_a_file_is_given_as_it_is_asked() {
    let folder = TestFolder::new("download-part");
    let app = TestApp::over(&folder.path, &[]);
    let root = app.models_dir();
    let path = root.join("a/part.gguf");
    fs::create_dir_all(path.parent().unwrap()).unwrap();
    fs::write(&path, (0..=255u8).collect::<Vec<u8>>()).unwrap();
    fs::write(root.join("a/empty.gguf"), b"").unwrap();
    let ranged = |rel: &str, range: &str| {
        let mut headers = Headers::new();
        headers.push("Range", range);
        asked_with(&app, &format!("?path={}", Percent::encode_path(rel)), headers)
    };
    let some = ranged("a/part.gguf", "bytes=10-19");
    assert_eq!(some.status, 206);
    assert_eq!(some.body, (10..=19u8).collect::<Vec<u8>>());
    assert!(some.head.contains("Content-Range: bytes 10-19/256"), "{}", some.head);
    assert!(some.head.contains("Content-Length: 10"), "{}", some.head);
    let tail = ranged("a/part.gguf", "bytes=250-");
    assert_eq!((tail.status, tail.body), (206, (250..=255u8).collect::<Vec<u8>>()));
    let first = ranged("a/part.gguf", "bytes=0-0");
    assert_eq!((first.status, first.body), (206, vec![0u8]));
    let over = ranged("a/part.gguf", "bytes=250-999");
    assert!(over.head.contains("Content-Range: bytes 250-255/256"), "{}", over.head);
    let past = ranged("a/part.gguf", "bytes=256-");
    assert_eq!((past.status, past.body), (416, Vec::new()));
    assert!(past.head.contains("Content-Range: bytes */256"), "the size goes along: {}", past.head);
    let nothing = ranged("a/empty.gguf", "bytes=0-0");
    assert_eq!(nothing.status, 416);
    assert!(nothing.head.contains("Content-Range: bytes */0"), "a file of nothing says so: {}", nothing.head);
    let plain = ranged("a/part.gguf", "bytes=nonsense");
    assert_eq!((plain.status, plain.body.len()), (200, 256), "a span that does not read: the whole file");
    assert!(!plain.head.contains("Content-Range"), "{}", plain.head);
    let whole = served(&app, "a/part.gguf");
    assert_eq!((whole.status, whole.body.len()), (200, 256), "no span: what a copy has always been given");
    assert_eq!(ranged("a/none.gguf", "bytes=0-0").status, 404);
    assert_eq!(ranged("../part.gguf", "bytes=0-0").status, 403, "a span opens no door");
}
