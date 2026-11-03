//! The rows the cell editor's picker is built from, over a folder of the test's own: what the list makes of a header, by the values each rule was once
//! caught on. A header is told to the memory of headers, so the list reads it as it would a file's, and no file here has to be a real GGUF.

use super::super::gguf_header::GgufHeader;
use super::*;
use crate::tests::{TestApp, TestFolder};
use std::sync::Arc;

const Q4: &str = "gemma4-12b-it-GGUF/unsloth/Q4_K_M/gemma4-12b-it-Q4_K_M.gguf";
const Q8: &str = "gemma4-12b-it-GGUF/unsloth/Q8_0/gemma4-12b-it-Q8_0.gguf";
const MMPROJ: &str = "gemma4-12b-it-GGUF/unsloth/Q4_K_M/mmproj-F16.gguf";
const DRAFT: &str = "gemma4-12b-it-GGUF/unsloth/default/mtp-gemma4-12b-it.gguf";
const EMBED: &str = "bge-small-embed/x/Q8_0/bge-small-embed-Q8_0.gguf";
const Q6: &str = "gemma4-12b-it-GGUF/unsloth/Q6_K/gemma4-12b-it-Q6_K.gguf";
const KEYS: &str = GgufHeader::KEYS;
const EXPERTS: &str = GgufHeader::EXPERT_BYTES;

struct Stand {
    _folder: TestFolder,
    app: Arc<App>,
}

impl Stand {
    fn new(name: &str) -> Self {
        let folder = TestFolder::new(&format!("listing-{name}"));
        let app = TestApp::over(&folder.path, &[]);
        Self { _folder: folder, app }
    }

    /// A file of this size, its header saying `said` (nothing, when it is `{}`). Sparse: the size is what the list reads.
    fn put(&self, rel: &str, size: u64, said: &Value) {
        let path = self.app.models_dir().join(rel);
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        std::fs::File::create(&path).unwrap().set_len(size).unwrap();
        let meta = std::fs::metadata(&path).unwrap();
        self.app.header_memory.remember(&path.to_string_lossy(), meta.mtime(), meta.size() as i64, &Coerce::fields(said));
    }

    fn rows(&self, libraries: &[Value]) -> Rows {
        let rows = ModelListing::of(&self.app).rows(&Config::new(), &Locations::new(libraries, "/h"));
        Rows {
            order: rows.iter().map(|row| Coerce::text(row.get("path"))).collect(),
            by: rows.iter().map(|row| (Coerce::text(row.get("path")), row.clone())).collect(),
        }
    }

    fn told_of_a_library(&self, rel: &str, size: i64, meta: &Value) {
        self.app.library_meta.remember("lib-a", rel, size, &Coerce::fields(meta)).unwrap();
    }
}

/// The rows, as they came and by their path.
struct Rows {
    order: Vec<String>,
    by: BTreeMap<String, Value>,
}

impl Rows {
    fn of_kind(&self, kind: &str) -> Vec<&str> {
        self.order.iter().filter(|path| self.by[path.as_str()]["kind"] == json!(kind)).map(String::as_str).collect()
    }
}

fn library(files: Value) -> Value {
    json!({"id": "lib-a", "name": "NAS", "state": "ok", "path": "/mnt/lib", "files": files})
}

fn gemma(context: i64) -> Value {
    json!({"general.architecture": "gemma3", "gemma3.context_length": context, "gemma3.block_count": 48})
}

/// The picker's folder of the old table.
fn picker_folder(name: &str) -> Stand {
    let stand = Stand::new(name);
    stand.put(Q4, 4000, &gemma(131_072));
    stand.put(MMPROJ, 300, &json!({}));
    stand.put(Q8, 8000, &gemma(131_072));
    stand.put(DRAFT, 100, &json!({"general.architecture": "gemma3", "gemma3.block_size": 4}));
    stand.put(EMBED, 50, &json!({"general.architecture": "bert", "bert.context_length": 512, "bert.pooling_type": 1}));
    stand.put("vocabs/ggml-vocab-llama.gguf", 10, &json!({}));
    stand
}

#[test]
fn models_come_first_then_what_goes_with_them_and_a_vocabulary_is_no_row() {
    let got = picker_folder("order").rows(&[]);
    assert_eq!(got.order, [EMBED, Q4, Q8, MMPROJ, DRAFT]);
    assert_eq!(got.by[EMBED]["kind"], json!("model"));
    assert_eq!((&got.by[MMPROJ]["kind"], &got.by[DRAFT]["kind"]), (&json!("mmproj"), &json!("draft")));
}

#[test]
fn a_model_is_offered_its_folders_companions_then_defaults_then_its_sisters() {
    let got = picker_folder("companions").rows(&[]);
    let q4 = &got.by[Q4];
    assert_eq!((&q4["compatibleMmprojs"], &q4["suggestedMmproj"]), (&json!([MMPROJ]), &json!(MMPROJ)));
    assert_eq!(
        (&q4["compatibleDrafts"], &q4["suggestedDraft"]),
        (&json!([DRAFT]), &json!(DRAFT)),
        "from the default folder beside it"
    );
    assert_eq!(q4["capability"], json!("vision_likely"), "a projector means it sees");
    let q8 = &got.by[Q8];
    assert_eq!(
        (&q8["compatibleMmprojs"], &q8["suggestedDraft"]),
        (&json!([MMPROJ]), &json!(DRAFT)),
        "another quant takes them from its sister and default"
    );
    assert!(
        got.by[MMPROJ].get("compatibleDrafts").is_none() && got.by[DRAFT].get("compatibleDrafts").is_none(),
        "a companion has no list"
    );
}

#[test]
fn a_row_says_its_family_its_window_its_freshness_and_its_size() {
    let stand = picker_folder("facts");
    let local = stand.app.models_dir().join(Q4);
    let report = json!({"checkedAt": 1, "keys": "path", "repos": {"unsloth/gemma4-12b-it-GGUF": {"files": {Q4: {"state": "size", "localPath": local.to_string_lossy(), "remoteSize": 5, "remoteDate": "2030-01-01"}}}}});
    stand.app.admin.saving(|doc| doc.insert("modelFreshness".to_string(), report));
    let got = stand.rows(&[]);
    let q4 = &got.by[Q4];
    assert_eq!(
        (&q4["detectedFamily"], &q4["familyDefaults"]["SPEC_TYPE"], &q4["hasMtpBuiltin"]),
        (&json!("gemma4"), &json!("draft-mtp"), &json!(false))
    );
    assert_eq!(
        (&q4["fresh"], &q4["ggufMeta"]["contextLength"], &q4["ggufMeta"]["architecture"], &q4["size"]),
        (&json!("size"), &json!(131_072), &json!("gemma3"), &json!(4000))
    );
    assert_eq!(got.by[Q8]["fresh"], json!(""), "not in the report is not checked, and not matches");
    assert_eq!(got.by[MMPROJ]["fresh"], json!(""));
}

#[test]
fn an_embedding_model_is_known_by_its_name_or_its_pooling_and_a_speech_model_by_its_variant() {
    let got = picker_folder("embed").rows(&[]);
    assert_eq!(
        (&got.by[EMBED]["capability"], &got.by[EMBED]["detectedFamily"]),
        (&json!("embedding_likely"), &json!("embedding"))
    );
    assert_eq!(
        (&got.by[EMBED]["familyDefaults"]["POOLING"], &got.by[EMBED]["familyDefaults"]["CTX_SIZE"]),
        (&json!("mean"), &json!("512")),
        "the pooling its header says, the window it was trained for"
    );
    let stand = Stand::new("speech");
    stand.put("Named-embed/x/Q8/named.gguf", 1, &json!({}));
    stand.put("Pooled/x/Q8/p.gguf", 1, &json!({"general.architecture": "qwen3", "qwen3.pooling_type": 3}));
    stand.put(
        "Giga-GGUF/x/Q8_0/giga-Q8_0.gguf",
        7,
        &json!({"general.architecture": "gigaam", "stt.variant": "gigaam-v3-e2e-rnnt", KEYS: 20}),
    );
    stand.put("Plain/x/Q8/embedded-Q8.gguf", 1, &json!({"general.architecture": "llama", "llama.context_length": 8192}));
    let got = stand.rows(&[]);
    assert_eq!(got.by["Named-embed/x/Q8/named.gguf"]["capability"], json!("embedding_likely"));
    assert_eq!(
        (&got.by["Pooled/x/Q8/p.gguf"]["capability"], &got.by["Pooled/x/Q8/p.gguf"]["familyDefaults"]["POOLING"]),
        (&json!("embedding_likely"), &json!("last"))
    );
    assert_eq!(
        (
            &got.by["Giga-GGUF/x/Q8_0/giga-Q8_0.gguf"]["capability"],
            &got.by["Giga-GGUF/x/Q8_0/giga-Q8_0.gguf"]["detectedFamily"],
            &got.by["Giga-GGUF/x/Q8_0/giga-Q8_0.gguf"]["familyDefaults"]
        ),
        (&json!("asr"), &json!("asr"), &json!({}))
    );
    assert_eq!(got.by["Plain/x/Q8/embedded-Q8.gguf"]["capability"], json!("text"), "a word that only begins like it is no hint");
}

#[test]
fn a_projector_goes_by_its_header_and_the_name_alone_where_no_header_says() {
    let stand = Stand::new("projector");
    let cpm = "MiniCPM-o-x/openbmb/";
    let (vision, projector) =
        (format!("{cpm}F16/MiniCPM-o-x-vision-F16.gguf"), format!("{cpm}default/MiniCPM-o-x-projector-F16.gguf"));
    let model = format!("{cpm}Q4_K_M/MiniCPM-o-x-Q4_K_M.gguf");
    stand.put(&model, 5000, &json!({"general.architecture": "llama"}));
    stand.put(&projector, 15, &json!({"general.architecture": "projector"}));
    stand.put(&vision, 1100, &json!({"general.architecture": "clip"}));
    stand.put(&format!("{cpm}F16/MiniCPM-o-x-audio-F16.gguf"), 660, &json!({"general.architecture": "whisper"}));
    stand.put("Llava/a/Q4/llava-Q4.gguf", 4000, &json!({"general.architecture": "llama"}));
    stand.put("Llava/a/Q4/llava-projector-f16.gguf", 600, &json!({"general.architecture": "clip"}));
    stand.told_of_a_library("Moved/a/Q4/seen-projector.gguf", 8, &json!({"architecture": "projector"}));
    let got = stand.rows(&[library(json!([
        {"path": "Moved/a/Q4/moved-Q4.gguf", "size": 70, "mtime": 5},
        {"path": "Moved/a/Q4/moved-projector.gguf", "size": 7, "mtime": 5},
        {"path": "Moved/a/Q4/seen-projector.gguf", "size": 8, "mtime": 5}
    ]))]);
    assert_eq!(got.by[&vision]["kind"], json!("mmproj"), "architecture clip is a projector though its name says nothing of it");
    assert!(!got.by.contains_key(&projector), "named a projector, architecture projector: no projector and no model");
    assert_eq!(
        (&got.by[&model]["compatibleMmprojs"], &got.by[&model]["suggestedMmproj"]),
        (&json!([vision]), &json!(vision)),
        "a cell that took the other died on it"
    );
    assert_eq!(
        got.by[&format!("{cpm}F16/MiniCPM-o-x-audio-F16.gguf")]["kind"],
        json!("model"),
        "a header not read through says nothing against it"
    );
    assert_eq!(
        (&got.by["Llava/a/Q4/llava-projector-f16.gguf"]["kind"], &got.by["Llava/a/Q4/llava-Q4.gguf"]["suggestedMmproj"]),
        (&json!("mmproj"), &json!("Llava/a/Q4/llava-projector-f16.gguf")),
        "a header that agrees with the name"
    );
    assert_eq!(
        got.by["Moved/a/Q4/moved-projector.gguf"]["kind"],
        json!("mmproj"),
        "a library's file with no header: the name is the whole answer"
    );
    assert!(!got.by.contains_key("Moved/a/Q4/seen-projector.gguf"), "a remembered header that is no clip: not in the list");
}

#[test]
fn drafts_are_offered_own_folder_then_default_then_sisters_and_the_first_suggested() {
    let stand = Stand::new("draft-order");
    for (rel, size) in [
        ("Gem/b/Q5_K_M/gem-Q5_K_M.gguf", 8000),
        ("Gem/b/Q5_K_M/mtp-own.gguf", 10),
        ("Gem/b/default/mtp-default.gguf", 10),
        ("Gem/b/Q8_0/gem-Q8_0.gguf", 12000),
        ("Gem/b/Q8_0/mtp-sibling.gguf", 10),
    ] {
        stand.put(rel, size, &json!({}));
    }
    let got = stand.rows(&[]);
    let q5 = &got.by["Gem/b/Q5_K_M/gem-Q5_K_M.gguf"];
    assert_eq!(
        q5["compatibleDrafts"],
        json!(["Gem/b/Q5_K_M/mtp-own.gguf", "Gem/b/default/mtp-default.gguf", "Gem/b/Q8_0/mtp-sibling.gguf"])
    );
    assert_eq!(q5["suggestedDraft"], json!("Gem/b/Q5_K_M/mtp-own.gguf"));
    assert_eq!(
        got.by["Gem/b/Q8_0/gem-Q8_0.gguf"]["compatibleDrafts"],
        json!(["Gem/b/Q8_0/mtp-sibling.gguf", "Gem/b/default/mtp-default.gguf", "Gem/b/Q5_K_M/mtp-own.gguf"]),
        "another quant: its own folder first"
    );
}

/// The folder and the library of the drafts made for an architecture.
fn drafts_by_architecture(name: &str) -> (Stand, Vec<Value>) {
    let stand = Stand::new(name);
    let exp = json!({"general.architecture": "qwen4exp"});
    let exp_mtp = json!({"general.architecture": "qwen4exp-mtp"});
    stand.put(ORIG, 10, &exp);
    stand.put(ORIG_MTP, 10, &exp_mtp);
    stand.put(CODER, 10, &exp);
    stand.put(SWIFT, 10, &exp);
    stand.put(SWIFT_MTP, 10, &exp_mtp);
    stand.put(GEM, 10, &json!({"general.architecture": "gemma3"}));
    stand.put(PI, 10, &json!({"general.architecture": "qwen35"}));
    stand.put(PI_MTP, 10, &json!({"general.architecture": "qwen35"}));
    for rel in more() {
        stand.put(&rel, 10, &exp_mtp);
    }
    stand.told_of_a_library(LIB, 70, &json!({"architecture": "qwen4exp"}));
    stand.told_of_a_library(LIB_MTP, 8, &json!({"architecture": "qwen4exp-mtp"}));
    stand.told_of_a_library(ODD, 8, &json!({"architecture": "-mtp"}));
    let libraries = vec![library(json!([
        {"path": LIB, "size": 70, "mtime": 5}, {"path": LIB_MTP, "size": 8, "mtime": 5}, {"path": LIB_BARE, "size": 9, "mtime": 5},
        {"path": ODD, "size": 8, "mtime": 5}, {"path": NOHDR, "size": 70, "mtime": 5}
    ]))];
    (stand, libraries)
}

const ORIG: &str = "Orig-GGUF/ista/IQ2_XS/orig-IQ2_XS-00001-of-00002.gguf";
const ORIG_MTP: &str = "Orig-GGUF/ista/IQ2_XS/mtp-q2_0.gguf";
const CODER: &str = "Coder-GGUF/ista/IQ1_M/coder-IQ1_M-00001-of-00002.gguf";
const SWIFT: &str = "Swift-GGUF/uki/IQ3_XXS/swift-IQ3_XXS-00001-of-00002.gguf";
const SWIFT_MTP: &str = "Swift-GGUF/uki/IQ3_XXS/mtp-swift-own.gguf";
const GEM: &str = "Gem/b/Q5_K_M/gem-Q5_K_M.gguf";
const PI: &str = "Pi/c/Q4/pi-Q4_0.gguf";
const PI_MTP: &str = "Pi/c/default/mtp-pi.gguf";
const LIB: &str = "Lib-GGUF/x/IQ3_S/lib-IQ3_S-00001-of-00002.gguf";
const LIB_MTP: &str = "Lib-GGUF/x/IQ3_S/mtp-lib.gguf";
const LIB_BARE: &str = "Bare-GGUF/y/default/mtp-unknown.gguf";
const ODD: &str = "Odd-GGUF/o/default/mtp-odd.gguf";
const NOHDR: &str = "Nohdr-GGUF/n/Q4/nohdr-Q4.gguf";

fn more() -> Vec<String> {
    (1..=4).map(|number| format!("Z{number}-GGUF/z/q/mtp-z{number}.gguf")).collect()
}

#[test]
fn a_pack_with_no_draft_is_offered_those_made_for_its_architecture_at_most_five() {
    let (stand, libraries) = drafts_by_architecture("drafts-coder");
    let got = stand.rows(&libraries);
    let more = more();
    let coder = &got.by[CODER];
    assert_eq!(
        coder["compatibleDrafts"],
        json!([LIB_MTP, ORIG_MTP, SWIFT_MTP, more[0], more[1]]),
        "wherever they lie, in the list's order, five of the seven"
    );
    assert_eq!(coder["suggestedDraft"], json!(LIB_MTP));
}

#[test]
fn a_packs_own_folder_comes_first_and_none_is_offered_twice() {
    let (stand, libraries) = drafts_by_architecture("drafts-own");
    let got = stand.rows(&libraries);
    let more = more();
    assert_eq!(got.by[SWIFT]["compatibleDrafts"], json!([SWIFT_MTP, LIB_MTP, ORIG_MTP, more[0], more[1]]));
    assert_eq!(got.by[SWIFT]["suggestedDraft"], json!(SWIFT_MTP));
    assert_eq!(
        got.by[ORIG]["compatibleDrafts"],
        json!([ORIG_MTP, LIB_MTP, SWIFT_MTP, more[0], more[1]]),
        "the original's own stays its suggestion"
    );
    assert_eq!(
        got.by[LIB]["compatibleDrafts"],
        json!([LIB_MTP, ORIG_MTP, SWIFT_MTP, more[0], more[1]]),
        "a pack only a library holds, by its remembered header"
    );
}

#[test]
fn a_draft_pairs_with_no_model_of_another_architecture_or_of_none_at_all() {
    let (stand, libraries) = drafts_by_architecture("drafts-negative");
    let got = stand.rows(&libraries);
    assert_eq!(got.by[NOHDR]["compatibleDrafts"], json!([]), "a header never read takes no draft that names no architecture");
    assert_eq!(
        got.by[GEM]["compatibleDrafts"],
        json!([]),
        "a llama.cpp model of another architecture is offered none of Strata's"
    );
    assert_eq!(got.by[GEM]["suggestedDraft"], json!(""));
    let coder = got.by[CODER]["compatibleDrafts"].as_array().unwrap();
    assert!(
        !coder.contains(&json!(ODD)) && !coder.contains(&json!(LIB_BARE)) && !coder.contains(&json!(PI_MTP)),
        "`-mtp` alone, a header never read, llama.cpp's own kind: {coder:?}"
    );
    assert_eq!(got.by[PI]["compatibleDrafts"], json!([PI_MTP]), "that one stays its folder's");
    assert!(got.by[ORIG_MTP].get("compatibleDrafts").is_none());
    assert_eq!(
        got.by[ORIG_MTP]["ggufMeta"]["architecture"],
        json!("qwen4exp-mtp"),
        "the draft's own header is in its row: its depth comes from it"
    );
}

fn library_rows(name: &str, models_dir_there: bool) -> Rows {
    let stand = picker_folder(name);
    stand.told_of_a_library(Q6, 6000, &json!({"architecture": "gemma3", "contextLength": 131_072}));
    if !models_dir_there {
        std::fs::remove_dir_all(stand.app.models_dir()).unwrap();
    }
    let libraries = [
        library(json!([
            {"path": Q6, "size": 6000, "mtime": 1_700_000_000},
            {"path": "gemma4-12b-it-GGUF/unsloth/Q6_K/mmproj-BF16.gguf", "size": 600, "mtime": 1_700_000_000},
            {"path": Q4, "size": 4000, "mtime": 1},
            {"path": "vocabs/ggml-vocab-qwen.gguf", "size": 5, "mtime": 1},
            {"path": "Moved/a/Q4/moved-Q4.gguf", "size": 70, "mtime": 5}
        ])),
        json!({"id": "lib-b", "name": "Old", "state": "not-mounted", "path": "/mnt/old", "files": [{"path": "Gone/g/Q4/g.gguf", "size": 9, "mtime": 1}]}),
    ];
    stand.rows(&libraries)
}

#[test]
fn a_librarys_file_stands_among_its_neighbours_and_says_where_it_is() {
    let got = library_rows("library-rows", true);
    assert_eq!(got.of_kind("model"), ["Moved/a/Q4/moved-Q4.gguf", EMBED, Q4, Q6, Q8], "in its place, and not at the tail");
    let q6 = &got.by[Q6];
    assert_eq!(
        (&q6["kind"], &q6["libraryOnly"], &q6["store"], &q6["size"], &q6["mtime"]),
        (&json!("model"), &json!(true), &json!({"id": "lib-a", "name": "NAS"}), &json!(6000), &json!(1_700_000_000))
    );
    assert_eq!(
        q6["ggufMeta"],
        json!({"architecture": "gemma3", "contextLength": 131_072}),
        "remembered, not read over the network"
    );
    assert_eq!(
        (&q6["suggestedMmproj"], &q6["suggestedDraft"], &q6["detectedFamily"]),
        (&json!("gemma4-12b-it-GGUF/unsloth/Q6_K/mmproj-BF16.gguf"), &json!(DRAFT), &json!("gemma4")),
        "companions from the library and from this disk"
    );
    assert_eq!(
        got.by["gemma4-12b-it-GGUF/unsloth/Q6_K/mmproj-BF16.gguf"]["libraryOnly"],
        json!(true),
        "a companion from a library is marked too"
    );
    assert_eq!(
        (&got.by["Moved/a/Q4/moved-Q4.gguf"]["ggufMeta"], &got.by["Moved/a/Q4/moved-Q4.gguf"]["libraryOnly"]),
        (&json!({}), &json!(true)),
        "no facts for a file that came some other way, and none made up"
    );
}

#[test]
fn a_file_in_both_places_is_this_disks_row_and_a_library_not_there_holds_nothing() {
    let got = library_rows("library-both", true);
    let q4 = &got.by[Q4];
    assert!(q4.get("libraryOnly").is_none() && q4.get("store").is_none(), "{q4}");
    assert_eq!(q4["size"], json!(4000));
    assert!(!got.by.contains_key("vocabs/ggml-vocab-qwen.gguf"), "a library's vocabulary is no model");
    assert!(!got.by.contains_key("Gone/g/Q4/g.gguf"), "a library that is not mounted: its last list is a guess");
}

#[test]
fn with_no_models_folder_a_librarys_models_are_still_listed_and_with_neither_there_is_no_list() {
    let got = library_rows("library-no-folder", false);
    assert_eq!(got.of_kind("model"), ["Moved/a/Q4/moved-Q4.gguf", Q4, Q6]);
    let stand = Stand::new("no-folder");
    std::fs::remove_dir_all(stand.app.models_dir()).unwrap();
    assert!(stand.rows(&[]).order.is_empty(), "no folder and no library: an empty list, and no error");
}

const GIB: u64 = 1 << 30;

fn split_stand(name: &str) -> (Stand, Vec<Value>) {
    let stand = Stand::new(name);
    for (rel, size) in [
        ("Big-GGUF/x/Q4_K_M/Big-Q4_K_M-00001-of-00003.gguf", 1 << 20),
        ("Big-GGUF/x/Q4_K_M/Big-Q4_K_M-00002-of-00003.gguf", 40 * GIB),
        ("Big-GGUF/x/Q4_K_M/Big-Q4_K_M-00003-of-00003.gguf", 40 * GIB),
        ("Half-GGUF/x/Q8_0/Half-Q8_0-00001-of-00002.gguf", 500),
        ("Other-GGUF/x/Q4_K_M/Big-Q4_K_M-00001-of-00003.gguf", 70),
        ("Whole-GGUF/x/Q4_K_M/Whole-Q4_K_M.gguf", 900),
        ("One-GGUF/x/Q8_0/One-Q8_0-00001-of-00001.gguf", 11),
        ("Mixed-GGUF/x/Q4/Mixed-Q4-00001-of-00003.gguf", 100),
        ("Mixed-GGUF/x/Q4/Mixed-Q4-00002-of-00003.gguf", 200),
    ] {
        stand.put(rel, size, &json!({}));
    }
    let libraries = vec![library(json!([{"path": "Mixed-GGUF/x/Q4/Mixed-Q4-00003-of-00003.gguf", "size": 2000, "mtime": 1}]))];
    (stand, libraries)
}

/// `(size, parts, partsFound)` of a row.
fn facts(got: &Rows, rel: &str) -> (Value, Option<Value>, Option<Value>) {
    let row = &got.by[rel];
    (row["size"].clone(), row.get("parts").cloned(), row.get("partsFound").cloned())
}

#[test]
fn a_split_models_first_part_is_the_row_of_the_whole_model() {
    let (stand, libraries) = split_stand("split-whole");
    let got = stand.rows(&libraries);
    let first = "Big-GGUF/x/Q4_K_M/Big-Q4_K_M-00001-of-00003.gguf";
    let whole = (1 << 20) + 80 * GIB;
    assert_eq!(
        facts(&got, first),
        (json!(whole), Some(json!(3)), Some(json!(3))),
        "a part of one header read as a model of 0.01 GB; two parts of one size are two"
    );
    assert_eq!(got.by[first]["sizeGb"], json!(80.0));
    for part in ["00002", "00003"] {
        let rel = format!("Big-GGUF/x/Q4_K_M/Big-Q4_K_M-{part}-of-00003.gguf");
        assert_eq!(facts(&got, &rel), (json!(40 * GIB), None, None), "the later parts: their own size and no word of parts");
        assert_eq!(got.by[&rel]["sizeGb"], json!(40.0));
    }
}

#[test]
fn a_part_that_has_not_come_is_named_and_a_model_short_of_one_is_not_drawn_whole() {
    let (stand, libraries) = split_stand("split-half");
    let got = stand.rows(&libraries);
    assert_eq!(facts(&got, "Half-GGUF/x/Q8_0/Half-Q8_0-00001-of-00002.gguf"), (json!(500), Some(json!(2)), Some(json!(1))));
}

#[test]
fn the_same_name_in_another_folder_is_another_model_and_a_whole_file_says_no_parts() {
    let (stand, libraries) = split_stand("split-other");
    let got = stand.rows(&libraries);
    assert_eq!(
        facts(&got, "Other-GGUF/x/Q4_K_M/Big-Q4_K_M-00001-of-00003.gguf"),
        (json!(70), Some(json!(3)), Some(json!(1))),
        "the parts of two folders do not add"
    );
    assert_eq!(facts(&got, "Whole-GGUF/x/Q4_K_M/Whole-Q4_K_M.gguf"), (json!(900), None, None));
    assert_eq!(
        facts(&got, "One-GGUF/x/Q8_0/One-Q8_0-00001-of-00001.gguf"),
        (json!(11), Some(json!(1)), Some(json!(1))),
        "part one of one"
    );
}

#[test]
fn a_part_in_a_library_counts_and_the_model_is_whole() {
    let (stand, libraries) = split_stand("split-library");
    let got = stand.rows(&libraries);
    assert_eq!(facts(&got, "Mixed-GGUF/x/Q4/Mixed-Q4-00001-of-00003.gguf"), (json!(2300), Some(json!(3)), Some(json!(3))));
}

fn experts_stand(name: &str) -> (Stand, Vec<Value>) {
    let stand = Stand::new(name);
    let moe = |bytes: i64| json!({"general.architecture": "qwen3moe", "qwen3moe.expert_count": 128, EXPERTS: bytes});
    stand.put("Moe-GGUF/x/Q4/Moe-Q4-00001-of-00003.gguf", 10, &moe(100));
    stand.put("Moe-GGUF/x/Q4/Moe-Q4-00002-of-00003.gguf", 20, &json!({"split.no": 1, EXPERTS: 2000}));
    stand.put("Moe-GGUF/x/Q4/Moe-Q4-00003-of-00003.gguf", 30, &json!({"split.no": 2}));
    stand.put("Gap-GGUF/x/Q4/Gap-Q4-00001-of-00002.gguf", 10, &moe(100));
    stand.put("Blind-GGUF/x/Q4/Blind-Q4-00001-of-00002.gguf", 10, &moe(100));
    stand.put("Blind-GGUF/x/Q4/Blind-Q4-00002-of-00002.gguf", 20, &json!({}));
    stand.put("Lib-GGUF/x/Q4/Lib-Q4-00001-of-00002.gguf", 10, &moe(10));
    stand.put("Old-GGUF/x/Q4/Old-Q4-00001-of-00002.gguf", 10, &moe(10));
    stand.put("Solo-GGUF/x/Q4/Solo-Q4.gguf", 50, &moe(777));
    stand.told_of_a_library("Lib-GGUF/x/Q4/Lib-Q4-00002-of-00002.gguf", 20, &json!({"architecture": "", "expertBytes": 990}));
    stand.told_of_a_library("Old-GGUF/x/Q4/Old-Q4-00002-of-00002.gguf", 20, &json!({"architecture": ""}));
    let libraries = vec![library(json!([
        {"path": "Lib-GGUF/x/Q4/Lib-Q4-00002-of-00002.gguf", "size": 20, "mtime": 1},
        {"path": "Old-GGUF/x/Q4/Old-Q4-00002-of-00002.gguf", "size": 20, "mtime": 1}
    ]))];
    (stand, libraries)
}

#[test]
fn the_first_part_says_the_experts_of_all_the_parts_a_part_that_holds_none_counting_as_none() {
    let (stand, libraries) = experts_stand("experts-sum");
    let got = stand.rows(&libraries);
    assert_eq!(got.by["Moe-GGUF/x/Q4/Moe-Q4-00001-of-00003.gguf"]["ggufMeta"]["expertBytes"], json!(2100), "100 + 2000 + 0");
    assert_eq!(
        got.by["Lib-GGUF/x/Q4/Lib-Q4-00001-of-00002.gguf"]["ggufMeta"]["expertBytes"],
        json!(1000),
        "a part in a library by what is remembered: 10 here and 990 there"
    );
    assert_eq!(got.by["Solo-GGUF/x/Q4/Solo-Q4.gguf"]["ggufMeta"]["expertBytes"], json!(777), "a whole file says its own");
}

#[test]
fn experts_are_unknown_unless_every_part_is_here_and_said_what_it_holds() {
    let (stand, libraries) = experts_stand("experts-unknown");
    let got = stand.rows(&libraries);
    let experts = |rel: &str| got.by[rel]["ggufMeta"]["expertBytes"].clone();
    assert_eq!(experts("Gap-GGUF/x/Q4/Gap-Q4-00001-of-00002.gguf"), json!(0), "a part short: not the first part's weight");
    assert_eq!(experts("Blind-GGUF/x/Q4/Blind-Q4-00001-of-00002.gguf"), json!(0), "the second part's header said nothing");
    assert_eq!(
        experts("Old-GGUF/x/Q4/Old-Q4-00001-of-00002.gguf"),
        json!(0),
        "remembered before these bytes were: unknown, and not no experts"
    );
}

fn loads_alone_stand(name: &str) -> (Stand, Vec<Value>) {
    let stand = Stand::new(name);
    let (lfm, cpm) = ("LFM-Audio-GGUF/x/Q8_0/", "MiniCPM-o-x/openbmb/");
    let window = json!({"general.architecture": "lfm2", "lfm2.context_length": 128_000, KEYS: 30});
    stand.put("Hermes-GGUF/x/default/Hermes.imatrix.gguf", 30, &json!({KEYS: 4}));
    stand.put(&format!("{lfm}lfm-Q8_0.gguf"), 40, &window);
    stand.put(
        &format!("{lfm}vocoder-lfm-Q8_0.gguf"),
        10,
        &json!({"general.architecture": "this model cannot be used as LLM, use it via --model-vocoder in TTS examples", KEYS: 3}),
    );
    stand.put(
        &format!("{lfm}tokenizer-lfm-Q8_0.gguf"),
        5,
        &json!({"general.architecture": "lfm2", "lfm2.context_length": 128_000, KEYS: 29}),
    );
    stand.put(&format!("{cpm}F16/MiniCPM-o-x-audio-F16.gguf"), 20, &json!({"general.architecture": "whisper", KEYS: 13}));
    stand.put(&format!("{cpm}default/flow_matching.gguf"), 9, &json!({"general.architecture": "flow_matching", KEYS: 3}));
    stand.put(&format!("{cpm}default/prompt_cache.gguf"), 3, &json!({KEYS: 7}));
    stand.put(
        "Big-GGUF/x/Q4/Big-Q4-00001-of-00002.gguf",
        50,
        &json!({"general.architecture": "qwen3", "qwen3.context_length": 262_144, KEYS: 40}),
    );
    stand.put("Big-GGUF/x/Q4/Big-Q4-00002-of-00002.gguf", 60, &json!({KEYS: 3}));
    stand.put(
        "Giga-GGUF/x/Q8_0/giga-Q8_0.gguf",
        7,
        &json!({"general.architecture": "gigaam", "stt.variant": "gigaam-v3-e2e-rnnt", KEYS: 20}),
    );
    stand.put("Strata-GGUF/x/IQ2/strata-IQ2.gguf", 70, &json!({"general.architecture": "qwen4exp", KEYS: 30}));
    stand.put("Broken-GGUF/x/Q4/broken-Q4.gguf", 8, &json!({}));
    stand.put("Old-GGUF/x/Q4/old-Q4.gguf", 8, &json!({"general.architecture": "llama"}));
    stand.told_of_a_library(
        "Lib-GGUF/x/default/lib.imatrix.gguf",
        6,
        &json!({"architecture": "", "contextLength": 0, "headerKeys": 4}),
    );
    stand.told_of_a_library(
        "Lib-GGUF/x/Q4/lib-Q4.gguf",
        60,
        &json!({"architecture": "llama", "contextLength": 8192, "headerKeys": 25}),
    );
    let libraries = vec![library(json!([
        {"path": "Lib-GGUF/x/default/lib.imatrix.gguf", "size": 6, "mtime": 1},
        {"path": "Lib-GGUF/x/Q4/lib-Q4.gguf", "size": 60, "mtime": 1},
        {"path": "Lib-GGUF/x/Q4/lib-unread-Q4.gguf", "size": 61, "mtime": 1}
    ]))];
    (stand, libraries)
}

#[test]
fn a_file_whose_header_shows_it_is_no_model_of_its_own_is_not_offered() {
    let (stand, libraries) = loads_alone_stand("loads-refused");
    let got = stand.rows(&libraries);
    for rel in [
        "Hermes-GGUF/x/default/Hermes.imatrix.gguf",
        "LFM-Audio-GGUF/x/Q8_0/vocoder-lfm-Q8_0.gguf",
        "MiniCPM-o-x/openbmb/F16/MiniCPM-o-x-audio-F16.gguf",
        "MiniCPM-o-x/openbmb/default/flow_matching.gguf",
        "MiniCPM-o-x/openbmb/default/prompt_cache.gguf",
        "Lib-GGUF/x/default/lib.imatrix.gguf",
    ] {
        assert!(!got.by.contains_key(rel), "{rel}: read through, no window, no speech: the picker offered it as an LLM");
    }
}

#[test]
fn a_model_that_names_its_window_a_later_part_a_speech_model_and_a_claimed_architecture_stay() {
    let (stand, libraries) = loads_alone_stand("loads-stay");
    let got = stand.rows(&libraries);
    for rel in [
        "LFM-Audio-GGUF/x/Q8_0/lfm-Q8_0.gguf",
        "LFM-Audio-GGUF/x/Q8_0/tokenizer-lfm-Q8_0.gguf",
        "Big-GGUF/x/Q4/Big-Q4-00002-of-00002.gguf",
        "Giga-GGUF/x/Q8_0/giga-Q8_0.gguf",
        "Strata-GGUF/x/IQ2/strata-IQ2.gguf",
        "Lib-GGUF/x/Q4/lib-Q4.gguf",
    ] {
        assert_eq!(got.by[rel]["kind"], json!("model"), "{rel}");
    }
    assert_eq!(got.by["Big-GGUF/x/Q4/Big-Q4-00001-of-00002.gguf"]["parts"], json!(2), "the parts are counted");
}

#[test]
fn a_header_nobody_read_through_leaves_the_name_the_whole_answer() {
    let (stand, libraries) = loads_alone_stand("loads-unread");
    let got = stand.rows(&libraries);
    for rel in ["Broken-GGUF/x/Q4/broken-Q4.gguf", "Old-GGUF/x/Q4/old-Q4.gguf", "Lib-GGUF/x/Q4/lib-unread-Q4.gguf"] {
        assert_eq!(got.by[rel]["kind"], json!("model"), "{rel}: nothing is known of it");
    }
    assert_eq!(
        got.by["LFM-Audio-GGUF/x/Q8_0/lfm-Q8_0.gguf"]["ggufMeta"]["headerKeys"],
        json!(30),
        "a row says how many keys its header holds"
    );
    assert_eq!(
        got.by["Broken-GGUF/x/Q4/broken-Q4.gguf"]["ggufMeta"]["headerKeys"],
        Value::Null,
        "none, and not 0, for a header nobody read through"
    );
}

#[test]
fn a_vocabularys_header_is_not_read_for_its_name_said_enough() {
    let stand = Stand::new("vocab-unread");
    let path = stand.app.models_dir().join("x/ggml-vocab-llama.gguf");
    std::fs::create_dir_all(path.parent().unwrap()).unwrap();
    std::fs::write(&path, b"x").unwrap();
    assert!(stand.rows(&[]).order.is_empty());
    let meta = std::fs::metadata(&path).unwrap();
    assert_eq!(
        stand.app.header_memory.recall(&path.to_string_lossy(), meta.mtime(), meta.size() as i64),
        None,
        "a file read is a file remembered"
    );
}

#[test]
fn a_folder_or_a_dead_link_named_like_a_model_is_no_row_and_a_link_to_a_file_is_the_file() {
    let stand = Stand::new("not-there");
    stand.put("Real/x/q/real.gguf", 9, &json!({}));
    let quant = stand.app.models_dir().join("Real/x/q");
    std::fs::create_dir(quant.join("dir.gguf")).unwrap();
    std::fs::write(quant.join("dir.gguf/inner.gguf"), b"x").unwrap();
    std::os::unix::fs::symlink("nowhere.gguf", quant.join("dead.gguf")).unwrap();
    std::os::unix::fs::symlink("real.gguf", quant.join("link.gguf")).unwrap();
    std::fs::write(quant.join("real.gguf.part"), b"x").unwrap();
    let got = stand.rows(&[]);
    assert_eq!(
        got.order,
        ["Real/x/q/dir.gguf/inner.gguf", "Real/x/q/link.gguf", "Real/x/q/real.gguf"],
        "no folder, no dead link, no half-fetched file: a cell would fail on each"
    );
    assert_eq!(got.by["Real/x/q/link.gguf"]["size"], json!(9), "a link weighs what it leads to: a move plants them");
}

#[test]
fn an_mtp_built_in_goes_by_the_top_folders_word_and_not_by_a_word_inside_another() {
    let stand = Stand::new("mtp-builtin");
    for rel in
        ["a-MTP-GGUF/x/q/a.gguf", "b_mtp/x/q/b.gguf", "c-MTP.v2/x/q/c.gguf", "d-MTPX-GGUF/x/q/d.gguf", "e/x-MTP-GGUF/q/e.gguf"]
    {
        stand.put(rel, 1, &json!({}));
    }
    let got = stand.rows(&[]);
    let built_in = |rel: &str| got.by[rel]["hasMtpBuiltin"].clone();
    assert_eq!(
        (built_in("a-MTP-GGUF/x/q/a.gguf"), built_in("b_mtp/x/q/b.gguf"), built_in("c-MTP.v2/x/q/c.gguf")),
        (json!(true), json!(true), json!(true))
    );
    assert_eq!((built_in("d-MTPX-GGUF/x/q/d.gguf"), built_in("e/x-MTP-GGUF/q/e.gguf")), (json!(false), json!(false)));
}

#[test]
fn a_family_is_read_from_the_top_folder() {
    assert_eq!(ModelListing::detect_family("Qwen3.6-27B/x/y.gguf"), "qwen3.6");
    assert_eq!(ModelListing::detect_family("gemma-4-E4B/x.gguf"), "gemma4");
    assert_eq!(ModelListing::detect_family("mistral/x.gguf"), "mistral");
    assert_eq!(ModelListing::detect_family("3dmodel/x.gguf"), "");
    assert_eq!(ModelListing::detect_family(""), "");
}

#[test]
fn a_file_says_its_role() {
    assert_eq!(ModelListing::gguf_kind("a/ggml-vocab.gguf", ""), None);
    assert_eq!(ModelListing::gguf_kind("vocabs/a.gguf", ""), None);
    assert_eq!(ModelListing::gguf_kind("a/mtp-q.gguf", ""), Some("draft"));
    assert_eq!(ModelListing::gguf_kind("a/mmproj-x.gguf", ""), Some("mmproj"));
    assert_eq!(ModelListing::gguf_kind("a/x.gguf", "clip"), Some("mmproj"));
    assert_eq!(ModelListing::gguf_kind("a/projector.gguf", ""), Some("mmproj"));
    assert_eq!(ModelListing::gguf_kind("a/projector.gguf", "other"), None);
    assert_eq!(ModelListing::gguf_kind("a/x.gguf", ""), Some("model"));
}

#[test]
fn an_embedding_model_says_its_pooling() {
    assert_eq!(ModelListing::embedding_family_defaults("x", 1, 10).get("POOLING"), Some(&json!("mean")));
    assert_eq!(ModelListing::embedding_family_defaults("bge m3", -1, 0).get("POOLING"), Some(&json!("cls")));
    assert_eq!(ModelListing::embedding_family_defaults("nomic", -1, 0).get("POOLING"), Some(&json!("mean")));
    assert_eq!(ModelListing::embedding_family_defaults("x", -1, 10).get("CTX_SIZE"), Some(&json!("10")));
}
