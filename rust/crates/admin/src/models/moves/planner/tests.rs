//! A plan through the real listing, the real registry and a look at real folders, by the word it refuses with.

use super::*;
use crate::models::moves::tests::{LIBRARY, Rig, blob};
use os::Disk;
use std::fs;

/// A rig whose library is on the controller's list, with a split model, a plain one, a link and a folder model on the disk, and a file and a folder in the library.
fn rig(name: &str) -> Rig {
    let rig = Rig::new(name);
    rig.put_local("A/a.gguf", &blob(10, 1));
    rig.put_local("B/b-00001-of-00002.gguf", &blob(20, 2));
    rig.put_local("B/b-00002-of-00002.gguf", &blob(30, 3));
    rig.put_local("L/target.bin", &blob(5, 5));
    std::os::unix::fs::symlink("target.bin", rig.local.join("L/l.gguf")).unwrap();
    rig.put_local("whisper/models--x/blobs/one", &blob(40, 6));
    rig.put_library("K/k.gguf", &blob(7, 7));
    rig.put_library("P/p-00001-of-00002.gguf", &blob(8, 8));
    rig.put_library("P/p-00002-of-00002.gguf", &blob(9, 9));
    rig.put_library("whisper/models--openai--w/blobs/one", &blob(11, 10));
    assert!(
        StoreRegistry::of(&rig.app).add(&rig.lib.to_string_lossy(), "", false).is_ok(),
        "the library takes its id from its mark"
    );
    rig
}

fn plan(rig: &Rig, paths: &[&str], to: &str, from: Option<&str>, busy: &[&str]) -> Result<MoveJob, MoveRefused> {
    let paths: Vec<Value> = paths.iter().map(|path| json!(path)).collect();
    let busy: BTreeSet<String> = busy.iter().map(|path| (*path).to_string()).collect();
    MovePlanner::of(&rig.app).plan(&paths, to, &busy, from)
}

fn refusal(rig: &Rig, paths: &[&str], to: &str, from: Option<&str>, busy: &[&str]) -> String {
    plan(rig, paths, to, from, busy).err().map_or_else(|| "planned".to_string(), |refused| refused.code)
}

fn planned(rig: &Rig, paths: &[&str], to: &str, from: Option<&str>) -> MoveJob {
    plan(rig, paths, to, from, &[]).map_err(|refused| refused.code).unwrap()
}

#[test]
fn a_plan_refuses_by_the_word_the_page_acts_on() {
    let rig = rig("plan-words");
    for (paths, to, from, busy, want) in [
        (&[][..], LIBRARY, None, &[][..], "empty"),
        (&["  ", ""][..], LIBRARY, None, &[][..], "empty"),
        (&["nope.gguf"][..], LIBRARY, None, &[][..], "unknown-file"),
        (&["L/l.gguf"][..], LIBRARY, None, &[][..], "link"),
        (&["A/a.gguf"][..], "local", None, &[][..], "same-store"),
        (&["A/a.gguf"][..], "lib-z", None, &[][..], "no-target"),
        (&["A/a.gguf"][..], LIBRARY, None, &["A/a.gguf"][..], "busy"),
        (&["B/b-00001-of-00002.gguf"][..], LIBRARY, None, &["B/b-00002-of-00002.gguf"][..], "busy"),
        (&["whisper/models--x"][..], LIBRARY, None, &["whisper/models--x"][..], "busy"),
        (&["nope.gguf"][..], "local", Some(LIBRARY), &[][..], "unknown-file"),
        (&["K/k.gguf"][..], LIBRARY, Some(LIBRARY), &[][..], "same-store"),
        (&["K/k.gguf"][..], "local", Some("lib-z"), &[][..], "no-source"),
    ] {
        assert_eq!(refusal(&rig, paths, to, from, busy), want, "{paths:?} to {to} from {from:?}, busy {busy:?}");
    }
}

#[test]
fn a_plan_that_goes_knows_both_ends_and_which_file_was_planned() {
    let rig = rig("plan-ends");
    let job = planned(&rig, &[" /A/a.gguf "], LIBRARY, None);
    assert!(job.id.starts_with("mv-") && job.id.len() == 11, "{}", job.id);
    assert_eq!(job.status, "queued");
    assert_eq!(job.source, json!({"id": "local", "name": "", "root": rig.local.to_string_lossy(), "kind": "local"}));
    assert_eq!(job.target, json!({"id": LIBRARY, "name": "NAS", "root": rig.lib.to_string_lossy(), "kind": "library"}));
    let file = &job.items[0].files[0];
    assert_eq!((file.rel.as_str(), file.size), ("A/a.gguf", 10));
    assert_eq!(file.stamp, Rig::stamp(&rig.local.join("A/a.gguf")), "the mover holds the file to what the plan saw");
}

#[test]
fn a_part_brings_its_whole_group_in_order_and_two_of_its_parts_are_one_item() {
    let rig = rig("plan-group");
    let job = planned(&rig, &["B/b-00002-of-00002.gguf"], LIBRARY, None);
    let files: Vec<(&str, i64)> = job.items[0].files.iter().map(|file| (file.rel.as_str(), file.size)).collect();
    assert_eq!(job.items.len(), 1);
    assert_eq!(files, [("B/b-00001-of-00002.gguf", 20), ("B/b-00002-of-00002.gguf", 30)]);
    let both = planned(&rig, &["A/a.gguf", "B/b-00001-of-00002.gguf", "B/b-00002-of-00002.gguf"], LIBRARY, None);
    let keys: Vec<&str> = both.items.iter().map(|item| item.key.as_str()).collect();
    assert_eq!(keys, ["A/a.gguf", "B/b-*-of-00002.gguf"], "in the order they were asked for");
    let home = planned(&rig, &["P/p-00002-of-00002.gguf"], "local", Some(LIBRARY));
    let rels: Vec<&str> = home.items[0].files.iter().map(|file| file.rel.as_str()).collect();
    assert_eq!(rels, ["P/p-00001-of-00002.gguf", "P/p-00002-of-00002.gguf"], "out of a library too");
}

#[test]
fn a_folder_is_one_item_with_its_weight_and_its_path_is_what_it_holds() {
    let rig = rig("plan-folder");
    let job = planned(&rig, &["whisper/models--x"], LIBRARY, None);
    let item = &job.items[0];
    assert_eq!((item.folder.as_str(), item.files.len(), item.size, item.scanned), ("whisper/models--x", 0, 40, false));
    assert_eq!(job.paths(), ["whisper/models--x"]);
    let home = planned(&rig, &["whisper/models--openai--w"], "local", Some(LIBRARY));
    let item = &home.items[0];
    assert_eq!((item.folder.as_str(), item.files.len(), item.size, item.scanned), ("whisper/models--openai--w", 0, 11, false));
}

#[test]
fn a_plan_out_of_a_library_has_no_stamp_and_asks_it_nothing_about_links() {
    let rig = rig("plan-back");
    let job = planned(&rig, &["K/k.gguf"], "local", Some(LIBRARY));
    assert_eq!(job.source["root"], json!(rig.lib.to_string_lossy()));
    assert_eq!(job.target["root"], json!(rig.local.to_string_lossy()));
    assert_eq!(job.items[0].files[0].stamp, Vec::<i64>::new(), "the mover takes it, away from the thread answering the request");
}

#[test]
fn a_running_cell_holds_its_file_its_group_and_its_file_in_a_library_and_says_whose() {
    let rig = rig("plan-in-use");
    rig.a_cell_names("A/a.gguf");
    let refused = plan(&rig, &["A/a.gguf"], LIBRARY, None, &[]).err().unwrap();
    assert_eq!(refused.code, "in-use");
    assert!(refused.error.message.contains("box:22001"), "{}", refused.error.message);
    rig.a_cell_names("B/b-00002-of-00002.gguf");
    assert_eq!(refusal(&rig, &["B/b-00001-of-00002.gguf"], LIBRARY, None, &[]), "in-use", "the group goes whole");
    rig.a_cell_names("K/k.gguf");
    assert_eq!(refusal(&rig, &["K/k.gguf"], "local", Some(LIBRARY), &[]), "in-use");
    rig.a_cell_names("whisper/models--x");
    assert_eq!(refusal(&rig, &["whisper/models--x"], LIBRARY, None, &[]), "in-use");
    assert_eq!(refusal(&rig, &["A/a.gguf"], LIBRARY, None, &[]), "planned", "the one no cell names any more goes");
}

#[test]
fn a_stopped_cell_holds_nothing() {
    let rig = rig("plan-stopped");
    rig.clock.each_look_takes(0);
    let now = rig.app.now_whole();
    rig.app.admin.saving(|doc| {
        doc.insert(
            "topology".to_string(),
            json!({"serverSlots": {"box:22001": {"hostId": "box", "port": 22001, "config": {"MODEL_FILE": "A/a.gguf"}}},
                   "hosts": {"box": {"lastSeen": now, "llamaNodes": []}}}),
        );
    });
    assert_eq!(
        refusal(&rig, &["A/a.gguf"], LIBRARY, None, &[]),
        "planned",
        "named by a cell, and read by none: its start brings it back"
    );
}

#[test]
fn a_library_that_lost_its_mark_neither_takes_nor_gives() {
    let rig = rig("plan-mark");
    assert_eq!(refusal(&rig, &["A/a.gguf"], LIBRARY, None, &[]), "planned");
    fs::remove_file(rig.mark()).unwrap();
    let refused = plan(&rig, &["A/a.gguf"], LIBRARY, None, &[]).err().unwrap();
    assert_eq!(refused.code, "target-not-mounted");
    assert!(refused.error.message.contains("not-mounted"), "the page says what is wrong with it: {}", refused.error.message);
    assert_eq!(refusal(&rig, &["K/k.gguf"], "local", Some(LIBRARY), &[]), "source-not-mounted");
}

#[test]
fn a_models_disk_that_does_not_read_is_a_refusal_and_not_an_empty_plan() {
    let rig = rig("plan-no-disk");
    fs::remove_dir_all(&rig.local).unwrap();
    assert_eq!(refusal(&rig, &["A/a.gguf"], LIBRARY, None, &[]), "source-missing");
}

#[test]
fn the_room_is_counted_for_the_move_and_a_margin_to_the_byte() {
    let end = |state: &str, free: Option<f64>| End {
        id: LIBRARY.to_string(),
        name: "NAS".to_string(),
        path: "/l".to_string(),
        kind: "library",
        state: state.to_string(),
        free,
        detail: "the folder carries no library mark".to_string(),
    };
    let edge = (1000 + MovePlanner::SPACE_MARGIN) as f64;
    assert_eq!(MovePlanner::SPACE_MARGIN, 2 << 30);
    assert!(MovePlanner::check_room(&end("ok", Some(edge)), 1000).is_ok(), "room exactly for the move and the margin");
    assert!(MovePlanner::check_room(&end("low-space", Some(edge)), 1000).is_ok(), "low on space is no refusal while it fits");
    let code = |end: &End, total: i64| MovePlanner::check_room(end, total).err().map(|refused| refused.code);
    assert_eq!(code(&end("ok", Some(edge - 1.0)), 1000).as_deref(), Some("no-room"), "a byte short");
    assert_eq!(code(&end("low-space", Some(edge - 1.0)), 1000).as_deref(), Some("no-room"));
    assert_eq!(code(&end("ok", None), 0).as_deref(), Some("no-room"), "a free figure nobody measured is no room");
    let refused = MovePlanner::check_room(&end("not-mounted", Some(edge * 2.0)), 1000).err().unwrap();
    assert_eq!(refused.code, "target-not-mounted");
    assert!(refused.error.message.contains("no library mark"), "{}", refused.error.message);
}

#[test]
fn a_plan_counts_the_real_weight_of_what_it_moves_either_way() {
    let rig = rig("plan-room");
    let (_, free) = Disk::usage(&rig.folder.path).unwrap();
    let huge = free + (1 << 40);
    let sparse = |path: std::path::PathBuf| {
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::File::create(&path).unwrap().set_len(huge).unwrap();
    };
    sparse(rig.local.join("H/h.gguf"));
    sparse(rig.local.join("whisper/models--huge/blobs/big"));
    sparse(rig.lib.join("H/back.gguf"));
    sparse(rig.lib.join("whisper/models--wide/blobs/big"));
    assert_eq!(refusal(&rig, &["H/h.gguf"], LIBRARY, None, &[]), "no-room");
    assert_eq!(
        refusal(&rig, &["whisper/models--huge"], LIBRARY, None, &[]),
        "no-room",
        "a folder's weight counts, its files not read yet"
    );
    assert_eq!(refusal(&rig, &["H/back.gguf"], "local", Some(LIBRARY), &[]), "no-room", "and this disk is asked as a library is");
    assert_eq!(refusal(&rig, &["whisper/models--wide"], "local", Some(LIBRARY), &[]), "no-room");
    assert_eq!(refusal(&rig, &["A/a.gguf"], LIBRARY, None, &[]), "planned");
}
