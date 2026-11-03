//! A job run to its end on real folders, by value: every rule that stands between a model and its loss, each with its opposite.

use crate::models::moves::job::{MoveFile, MoveItem, MoveJob};
use crate::models::moves::tests::{LIBRARY, Rig, blob};
use net::Sha256;
use serde_json::json;
use std::fs;
use std::sync::Mutex;

fn digest(bytes: &[u8]) -> String {
    let mut digest = Sha256::new();
    digest.update(bytes);
    digest.hex()
}

#[test]
fn a_copy_reaches_the_library_whole_and_the_source_goes_with_the_folders_it_empties() {
    let rig = Rig::new("mover-plain");
    let data = blob(10_500, 1);
    rig.put_local("Qwen/unsloth/Q4/q.gguf", &data);
    rig.put_local("Keep/other.gguf", &blob(10, 2));
    let done = rig.run(rig.job(&[&["Qwen/unsloth/Q4/q.gguf"]]));
    assert_eq!(fs::read(rig.lib.join("Qwen/unsloth/Q4/q.gguf")).unwrap(), data);
    assert_eq!(rig.library_files(), ["Qwen/unsloth/Q4/q.gguf"], "under its own name, and no part left beside it");
    assert_eq!(rig.local_files(), ["Keep/other.gguf"], "the source went, its neighbour did not");
    assert!(!rig.local.join("Qwen").exists(), "the folders it emptied went too");
    let file = &done.items[0].files[0];
    assert_eq!((done.status.as_str(), done.items[0].state.as_str(), file.phase.as_str()), ("done", "done", "removed"));
    assert_eq!(file.sha256, digest(&data), "the record keeps what was proven");
    assert_eq!(file.bypassed, cfg!(target_os = "linux"), "and says whether the proof read past this host's cache");
    assert!(!rig.statuses().contains(&"waiting".to_string()), "a library that carries its mark is not waited for");
}

#[test]
fn a_copy_goes_through_its_phases_and_writes_down_each_confirmed_point() {
    let rig = Rig::new("mover-phases");
    rig.put_local("M/m.gguf", &blob(10_500, 1));
    rig.run(rig.job(&[&["M/m.gguf"]]));
    assert_eq!(rig.phase_order(), ["", "copying", "checking", "proven", "removed"]);
    assert_eq!(rig.copying(), [0, 3000, 6000, 9000]);
}

#[test]
fn a_copy_takes_the_model_s_name_only_when_it_is_proven() {
    let rig = Rig::new("mover-name");
    rig.put_local("M/m.gguf", &blob(5000, 1));
    let (part, last) = (rig.lib.join("M/m.gguf.caravan-part"), rig.lib.join("M/m.gguf"));
    let checked = Mutex::new(Vec::new());
    rig.run_watching(rig.job(&[&["M/m.gguf"]]), |job| {
        let phase = job.items[0].files[0].phase.as_str();
        if matches!(phase, "copying" | "checking" | "proven") {
            checked.lock().unwrap().push((phase.to_string(), last.exists(), part.exists()));
        }
    });
    let seen = checked.into_inner().unwrap();
    assert!(seen.iter().any(|row| row.0 == "copying"), "{seen:?}");
    assert!(seen.contains(&("checking".to_string(), false, true)), "proven under the part's name: {seen:?}");
    assert!(seen.contains(&("proven".to_string(), true, false)), "and only then the model's: {seen:?}");
    assert!(seen.iter().all(|(phase, named, _)| phase == "proven" || !named), "{seen:?}");
}

#[test]
fn the_copy_carries_the_time_of_its_source() {
    let rig = Rig::new("mover-age");
    let source = rig.put_local("M/m.gguf", &blob(100, 1));
    let old = std::time::UNIX_EPOCH + std::time::Duration::new(1_700_000_000, 123_000_000);
    fs::File::options().write(true).open(&source).unwrap().set_modified(old).unwrap();
    let job = rig.job(&[&["M/m.gguf"]]);
    let planned = job.items[0].files[0].stamp[1];
    rig.run(job);
    assert_eq!(Rig::stamp(&rig.lib.join("M/m.gguf"))[1], planned, "a move is not a download: the tree shows the model's age");
}

#[test]
fn the_source_stays_until_the_settle_time_after_the_last_byte_is_over() {
    let rig = Rig::new("mover-settle");
    rig.clock.each_look_takes(2);
    let source = rig.put_local("M/m.gguf", &blob(3000, 1));
    let clock = rig.clock.clone();
    let at_removal = Mutex::new(None);
    let done = rig.run_watching(rig.job(&[&["M/m.gguf"]]), |job| {
        if job.items[0].state == "removing" {
            let now = os::clock::Clock::epoch(clock.as_ref());
            *at_removal.lock().unwrap() = Some((now, job.items[0].files[0].copied_at as f64, source.exists()));
        }
    });
    let (now, copied, there) = at_removal.into_inner().unwrap().unwrap();
    assert!(there, "the source is there when the removal is written down");
    assert!(now >= copied + 120.0, "removed {} s after the last byte", now - copied);
    assert!(now < copied + 160.0, "and not kept much longer: {} s", now - copied);
    assert_eq!(done.items[0].state, "done");
    assert!(!source.exists());
}

#[test]
fn a_group_settles_from_the_last_byte_of_its_last_part() {
    let rig = Rig::new("mover-settle-group");
    rig.clock.each_look_takes(2);
    rig.put_local("M/m-00001-of-00002.gguf", &blob(100, 1));
    rig.put_local("M/m-00002-of-00002.gguf", &blob(100, 2));
    let clock = rig.clock.clone();
    let gap = Mutex::new(false);
    let at_removal = Mutex::new(None);
    rig.run_watching(rig.job(&[&["M/m-00001-of-00002.gguf", "M/m-00002-of-00002.gguf"]]), |job| {
        let item = &job.items[0];
        if item.files[0].phase == "proven" && !std::mem::replace(&mut *gap.lock().unwrap(), true) {
            clock.pass(80);
        }
        if item.state == "removing" {
            *at_removal.lock().unwrap() =
                Some((os::clock::Clock::epoch(clock.as_ref()), item.files[0].copied_at as f64, item.files[1].copied_at as f64));
        }
    });
    let (now, first, last) = at_removal.into_inner().unwrap().unwrap();
    assert!(last >= first + 80.0, "the second part came later: {first} and {last}");
    assert!(now >= last + 120.0, "removed {} s after the last part", now - last);
}

#[test]
fn a_file_coming_home_leaves_the_library_at_once_with_what_was_remembered_of_it() {
    let rig = Rig::new("mover-home");
    rig.clock.each_look_takes(0);
    let data = blob(9000, 5);
    rig.put_local("Keep/other.gguf", &blob(10, 2));
    rig.put_library("Qwen/unsloth/Q4/q.gguf", &data);
    rig.app.library_meta.remember(LIBRARY, "Qwen/unsloth/Q4/q.gguf", 9000, &serde_json::Map::new()).unwrap();
    let done = rig.run(rig.job_back(&["Qwen/unsloth/Q4/q.gguf"]));
    assert_eq!(done.status, "done", "the clock stands still: a settle would never have ended");
    assert_eq!(fs::read(rig.local.join("Qwen/unsloth/Q4/q.gguf")).unwrap(), data);
    assert!(rig.library_files().is_empty(), "{:?}", rig.library_files());
    assert!(!rig.lib.join("Qwen").exists() && rig.lib.is_dir(), "its folders went, the library did not");
    let file = &done.items[0].files[0];
    assert_eq!(file.stamp[0], 9000, "the mover took the stamp the plan could not");
    assert_eq!(file.sha256, digest(&data));
    assert_eq!(rig.app.library_meta.lookup(LIBRARY, "Qwen/unsloth/Q4/q.gguf", 9000), None);
}

#[test]
fn a_library_with_no_mark_or_another_s_gets_no_byte_and_the_job_waits_for_it() {
    for (mark, name) in [(None, "mover-mark-none"), (Some("lib-b"), "mover-mark-other")] {
        let rig = Rig::unmarked(name);
        if let Some(mark) = mark {
            rig.set_mark(mark);
        }
        let data = blob(5000, 3);
        rig.put_local("M/m.gguf", &data);
        let seen = Mutex::new(Vec::new());
        let done = rig.run_watching(rig.job(&[&["M/m.gguf"]]), |job| {
            if job.status == "waiting" {
                let names: Vec<_> = fs::read_dir(&rig.lib).unwrap().flatten().map(|entry| entry.file_name()).collect();
                seen.lock().unwrap().push((job.reason.clone(), names, rig.local.join("M/m.gguf").exists()));
                rig.set_mark(LIBRARY);
            }
        });
        let seen = seen.into_inner().unwrap();
        let (reason, names, source) = &seen[0];
        assert!(reason.contains("does not carry this library's mark"), "{reason}");
        assert_eq!(reason.contains("(it carries lib-b)"), mark.is_some(), "{reason}");
        assert_eq!(
            names.iter().filter(|name| *name != ".caravan-store.json").count(),
            0,
            "not a byte and not a folder: {names:?}"
        );
        assert!(source);
        assert_eq!((done.status.as_str(), done.items[0].errors), ("done", 0), "an outage is no failure of the file");
        assert_eq!(fs::read(rig.lib.join("M/m.gguf")).unwrap(), data, "and when the library is back the move goes on");
        assert!(rig.local_files().is_empty());
    }
}

#[test]
fn a_library_with_no_mark_gives_no_byte_and_its_file_comes_home_when_it_is_back() {
    let rig = Rig::unmarked("mover-mark-back");
    let data = blob(2500, 8);
    rig.put_library("M/m.gguf", &data);
    let on_this_disk = Mutex::new(None);
    let done = rig.run_watching(rig.job_back(&["M/m.gguf"]), |job| {
        if job.status == "waiting" {
            *on_this_disk.lock().unwrap() = Some(rig.local_files());
            rig.set_mark(LIBRARY);
        }
    });
    assert_eq!(on_this_disk.into_inner().unwrap(), Some(Vec::new()));
    assert_eq!(done.status, "done");
    assert_eq!(fs::read(rig.local.join("M/m.gguf")).unwrap(), data);
    assert!(rig.library_files().is_empty());
}

#[test]
fn a_folder_in_a_library_that_did_not_mount_is_waited_for_and_not_called_gone() {
    let rig = Rig::unmarked("mover-mark-folder");
    // The share is not there: under its mount point nothing, the folder neither.
    let job = Rig::blank(
        json!({"id": LIBRARY, "name": "NAS", "root": rig.lib.to_string_lossy(), "kind": "library"}),
        json!({"id": "local", "name": "", "root": rig.local.to_string_lossy(), "kind": "local"}),
        vec![MoveItem::new("whisper/models--x", Vec::new(), "whisper/models--x", 3)],
    );
    let done = rig.run_watching(job, |job| {
        if job.status == "waiting" {
            rig.put_library("whisper/models--x/blobs/one", b"abc");
            rig.set_mark(LIBRARY);
        }
    });
    assert_eq!((done.status.as_str(), done.items[0].state.as_str(), done.items[0].note.as_str()), ("done", "done", ""));
    assert_eq!(fs::read(rig.local.join("whisper/models--x/blobs/one")).unwrap(), b"abc");
    assert!(rig.library_files().is_empty());
}

#[test]
fn an_outage_is_waited_out_however_long_it_takes() {
    let rig = Rig::unmarked("mover-outage");
    rig.put_local("M/m.gguf", &blob(100, 1));
    let told = Mutex::new(false);
    let done = std::thread::scope(|scope| {
        rig.run_watching(rig.job(&[&["M/m.gguf"]]), |job| {
            if job.status == "waiting" && !std::mem::replace(&mut *told.lock().unwrap(), true) {
                // Many rounds of the wait pass before the mark comes back.
                let (lib, mark) = (rig.lib.clone(), rig.mark());
                scope.spawn(move || {
                    std::thread::sleep(std::time::Duration::from_millis(60));
                    assert!(lib.is_dir());
                    fs::write(mark, json!({"id": LIBRARY}).to_string()).unwrap();
                });
            }
        })
    });
    assert_eq!((done.status.as_str(), done.items[0].state.as_str(), done.items[0].errors), ("done", "done", 0));
    assert_eq!(
        rig.statuses().iter().filter(|status| *status == "waiting").count(),
        1,
        "one outage is one wait, for as long as it lasts"
    );
}

#[test]
fn a_mark_gone_before_the_removal_holds_the_source_until_it_is_back() {
    let rig = Rig::new("mover-mark-late");
    let source = rig.put_local("M/m.gguf", &blob(100, 1));
    let seen = Mutex::new(Vec::new());
    let done = rig.run_watching(rig.job(&[&["M/m.gguf"]]), |job| {
        let mut seen = seen.lock().unwrap();
        if job.items[0].files[0].phase == "proven" && seen.is_empty() {
            fs::remove_file(rig.mark()).unwrap();
            seen.push("gone");
        }
        if job.status == "waiting" {
            assert!(source.exists(), "a copy on a share that went is no reason to delete");
            seen.push("waited");
            rig.set_mark(LIBRARY);
        }
    });
    assert_eq!(seen.into_inner().unwrap(), ["gone", "waited"]);
    assert_eq!(done.items[0].state, "done");
    assert!(!source.exists());
}

#[test]
fn a_restart_goes_on_from_the_manifest_and_cuts_off_what_came_after_the_last_confirmed_point() {
    let rig = Rig::new("mover-restart");
    let data = blob(10_500, 4);
    let source = rig.put_local("M/m.gguf", &data);
    let part = rig.lib.join("M/m.gguf.caravan-part");
    let record = Mutex::new(None);
    // The clock stands: however late the stop comes, the first run does not get past its settle.
    rig.clock.each_look_takes(0);
    rig.run_stopping(rig.job(&[&["M/m.gguf"]]), |job| {
        if job.items[0].files[0].synced != 6000 {
            return false;
        }
        record.lock().unwrap().get_or_insert_with(|| (job.to_json(), fs::read(&part).unwrap()));
        true
    });
    drop(fs::remove_file(rig.lib.join("M/m.gguf")));
    rig.clock.each_look_takes(30);
    let (manifest, bytes) = record.into_inner().unwrap().unwrap();
    assert_eq!(manifest["items"][0]["files"][0]["synced"], 6000, "the point is in the manifest");
    assert_eq!(bytes, data[..6000], "and on the disk, before it is written down");
    // What a controller that dies leaves: the part as it stood, with bytes past the point that may have a hole before them.
    let mut torn = bytes;
    torn.extend_from_slice(&[0u8; 700]);
    fs::write(&part, &torn).unwrap();
    rig.saves.lock().unwrap().clear();
    let again = MoveJob::of_json(&manifest).unwrap();
    let done = rig.run(again);
    assert_eq!(rig.copying()[0], 6000, "from the point: not from zero, and not from the end of the part");
    assert_eq!(fs::read(rig.lib.join("M/m.gguf")).unwrap(), data);
    assert_eq!(done.items[0].files[0].attempts, 0, "the first proof holds: nothing of the torn tail stayed");
    assert!(!source.exists() && !part.exists());
}

#[test]
fn a_part_shorter_than_its_record_goes_on_from_what_is_there_and_none_from_zero() {
    for (name, there, first) in [("mover-short", Some(4000), 4000), ("mover-no-part", None, 0)] {
        let rig = Rig::new(name);
        let data = blob(10_500, 4);
        rig.put_local("M/m.gguf", &data);
        if let Some(there) = there {
            rig.put_library("M/m.gguf.caravan-part", &data[..there]);
        }
        let mut job = rig.job(&[&["M/m.gguf"]]);
        job.items[0].files[0].synced = 6000;
        let done = rig.run(job);
        assert_eq!(rig.copying()[0], first, "{name}");
        assert_eq!(fs::read(rig.lib.join("M/m.gguf")).unwrap(), data, "{name}");
        assert_eq!(done.items[0].files[0].attempts, 0, "{name}");
    }
}

/// Spoils the part the proof is about to read, `times` times.
fn spoiled(rig: &Rig, times: usize, data: &[u8]) -> MoveJob {
    rig.put_local("M/m.gguf", data);
    let part = rig.lib.join("M/m.gguf.caravan-part");
    let left = Mutex::new(times);
    rig.run_watching(rig.job(&[&["M/m.gguf"]]), |job| {
        let mut left = left.lock().unwrap();
        if job.items[0].files[0].phase == "checking" && *left > 0 && part.exists() {
            *left -= 1;
            let mut raw = fs::read(&part).unwrap();
            raw[0] ^= 1;
            fs::write(&part, raw).unwrap();
        }
    })
}

#[test]
fn a_proof_that_fails_once_copies_again_from_zero() {
    let rig = Rig::new("mover-proof-once");
    let data = blob(10_500, 7);
    let done = spoiled(&rig, 1, &data);
    assert_eq!((done.items[0].state.as_str(), done.items[0].files[0].attempts), ("done", 1));
    assert_eq!(rig.copying().iter().filter(|done| **done == 0).count(), 2, "{:?}", rig.copying());
    assert_eq!(fs::read(rig.lib.join("M/m.gguf")).unwrap(), data);
    assert!(rig.local_files().is_empty());
}

#[test]
fn a_proof_that_fails_twice_leaves_the_source_and_no_copy() {
    let rig = Rig::new("mover-proof-twice");
    let data = blob(5000, 8);
    let done = spoiled(&rig, 2, &data);
    assert_eq!((done.items[0].state.as_str(), done.items[0].note.as_str()), ("skipped", "mismatch"));
    assert!(rig.library_files().is_empty(), "{:?}", rig.library_files());
    assert_eq!(fs::read(rig.local.join("M/m.gguf")).unwrap(), data);
    assert_eq!(done.status, "done", "a skipped item ends the item, not the job");
}

#[test]
fn another_file_under_the_target_s_name_is_not_written_over_and_the_source_stays() {
    let rig = Rig::new("mover-taken");
    let (data, other) = (blob(5000, 9), blob(5000, 10));
    rig.put_local("M/m.gguf", &data);
    rig.put_library("M/m.gguf", &other);
    let done = rig.run(rig.job(&[&["M/m.gguf"]]));
    assert_eq!((done.items[0].state.as_str(), done.items[0].note.as_str()), ("skipped", "name-taken"));
    assert_eq!(fs::read(rig.lib.join("M/m.gguf")).unwrap(), other);
    assert_eq!(fs::read(rig.local.join("M/m.gguf")).unwrap(), data);
    assert!(rig.copying().is_empty(), "the copy never began");
}

#[test]
fn the_same_file_there_already_lets_the_source_go_with_no_copy_and_no_wait() {
    let rig = Rig::new("mover-same");
    rig.clock.each_look_takes(0);
    let data = blob(5000, 11);
    rig.put_local("M/m.gguf", &data);
    rig.put_library("M/m.gguf", &data);
    let done = rig.run(rig.job(&[&["M/m.gguf"]]));
    assert_eq!((done.status.as_str(), done.items[0].state.as_str()), ("done", "done"), "the clock stands still: no settle");
    assert!(rig.copying().is_empty());
    assert!(rig.local_files().is_empty());
    assert!(rig.local.is_dir() && !rig.local.join("M").exists(), "the emptied folder went, the models folder stayed");
}

#[test]
fn a_source_changed_after_the_plan_is_not_moved() {
    let rig = Rig::new("mover-changed");
    let source = rig.put_local("M/m.gguf", &blob(5000, 12));
    let job = rig.job(&[&["M/m.gguf"]]);
    Rig::touch(&source);
    let done = rig.run(job);
    assert_eq!((done.items[0].state.as_str(), done.items[0].note.as_str()), ("skipped", "local-changed"));
    assert!(rig.library_files().is_empty());
    assert_eq!(rig.local_files(), ["M/m.gguf"]);
}

#[test]
fn one_part_changed_keeps_every_part_of_the_group_here() {
    let rig = Rig::new("mover-changed-group");
    let (one, two) = (blob(4000, 14), blob(4000, 15));
    rig.put_local("M/m-00001-of-00002.gguf", &one);
    let second = rig.put_local("M/m-00002-of-00002.gguf", &two);
    let job = rig.job(&[&["M/m-00001-of-00002.gguf", "M/m-00002-of-00002.gguf"]]);
    Rig::touch(&second);
    let done = rig.run(job);
    assert_eq!(done.items[0].note, "local-changed");
    assert_eq!(rig.local_files(), ["M/m-00001-of-00002.gguf", "M/m-00002-of-00002.gguf"]);
    assert_eq!(rig.library_files(), ["M/m-00001-of-00002.gguf"], "the proven part stays whole in the library");
    assert_eq!(fs::read(rig.local.join("M/m-00001-of-00002.gguf")).unwrap(), one);
}

#[test]
fn a_source_changed_after_its_proof_stays() {
    let rig = Rig::new("mover-changed-late");
    let source = rig.put_local("M/m.gguf", &blob(1000, 12));
    let done = rig.run_watching(rig.job(&[&["M/m.gguf"]]), |job| {
        let file = &job.items[0].files[0];
        if file.phase == "proven" && Rig::stamp(&source) == file.stamp {
            Rig::touch(&source);
        }
    });
    assert_eq!((done.items[0].state.as_str(), done.items[0].note.as_str()), ("skipped", "local-changed"));
    assert!(source.exists(), "what changed since it was proven is not what the library holds");
    assert!(rig.lib.join("M/m.gguf").exists());
}

#[test]
fn a_copy_gone_or_cut_short_before_the_removal_keeps_the_source() {
    for (name, gone) in [("mover-copy-gone", true), ("mover-copy-short", false)] {
        let rig = Rig::new(name);
        let data = blob(1000, 13);
        let source = rig.put_local("M/m.gguf", &data);
        let copy = rig.lib.join("M/m.gguf");
        let done = rig.run_watching(rig.job(&[&["M/m.gguf"]]), |job| {
            if job.items[0].files[0].phase == "proven" && copy.exists() && fs::metadata(&copy).unwrap().len() == 1000 {
                if gone {
                    fs::remove_file(&copy).unwrap();
                } else {
                    fs::File::options().write(true).open(&copy).unwrap().set_len(999).unwrap();
                }
            }
        });
        assert_eq!((done.items[0].state.as_str(), done.items[0].note.as_str()), ("skipped", "copy-missing"), "{name}");
        assert_eq!(fs::read(&source).unwrap(), data, "{name}");
    }
}

#[test]
fn a_cell_that_began_to_read_during_the_move_keeps_both_copies() {
    let rig = Rig::new("mover-in-use");
    let data = blob(5000, 13);
    let source = rig.put_local("M/m.gguf", &data);
    let done = rig.run_watching(rig.job(&[&["M/m.gguf"]]), |job| {
        if job.items[0].files[0].phase == "proven" {
            rig.a_cell_names("M/m.gguf");
        }
    });
    assert_eq!((done.items[0].state.as_str(), done.items[0].note.as_str()), ("skipped", "in-use"));
    assert_eq!(fs::read(&source).unwrap(), data);
    assert_eq!(fs::read(rig.lib.join("M/m.gguf")).unwrap(), data);
}

#[test]
fn a_cell_that_reads_another_part_of_the_group_keeps_them_all() {
    let rig = Rig::new("mover-in-use-group");
    rig.put_local("M/m-00001-of-00002.gguf", &blob(100, 1));
    rig.put_local("M/m-00002-of-00002.gguf", &blob(100, 2));
    rig.a_cell_names("M/m-00002-of-00002.gguf");
    let done = rig.run(rig.job(&[&["M/m-00001-of-00002.gguf", "M/m-00002-of-00002.gguf"]]));
    assert_eq!(done.items[0].note, "in-use");
    assert_eq!(rig.local_files().len(), 2);
}

#[test]
fn a_stopped_cell_s_model_travels() {
    let rig = Rig::new("mover-stopped");
    rig.clock.each_look_takes(0);
    let now = rig.app.now_whole();
    rig.put_library("M/m.gguf", &blob(100, 1));
    rig.app.admin.saving(|doc| {
        doc.insert(
            "topology".to_string(),
            json!({"serverSlots": {"box:22001": {"hostId": "box", "port": 22001, "config": {"MODEL_FILE": "M/m.gguf"}}},
                   "hosts": {"box": {"lastSeen": now, "llamaNodes": []}}}),
        );
    });
    let done = rig.run(rig.job_back(&["M/m.gguf"]));
    assert_eq!(done.items[0].state, "done", "it names the file and does not hold it: a start brings it back");
    assert!(rig.library_files().is_empty());
}

#[test]
fn a_folder_goes_whole_with_its_links_as_links_and_its_empty_folders() {
    let rig = Rig::new("mover-folder");
    rig.put_local("Keep/other.gguf", &blob(10, 2));
    let cache = rig.local.join("whisper/models--Systran--x");
    Rig::put(&cache, "blobs/sha1", &blob(4000, 11));
    Rig::put(&cache, "blobs/sha2", &blob(1500, 12));
    fs::create_dir_all(cache.join("snapshots/abc")).unwrap();
    fs::create_dir_all(cache.join("refs")).unwrap();
    std::os::unix::fs::symlink("../../blobs/sha1", cache.join("snapshots/abc/model.bin")).unwrap();
    std::os::unix::fs::symlink("../../blobs/sha2", cache.join("snapshots/abc/config.json")).unwrap();
    let done = rig.run(rig.folder_job("whisper/models--Systran--x", 5500));
    let lib = rig.lib.join("whisper/models--Systran--x");
    assert_eq!((done.status.as_str(), done.items[0].state.as_str(), done.items[0].note.as_str()), ("done", "done", ""));
    assert_eq!(fs::read(lib.join("blobs/sha1")).unwrap(), blob(4000, 11));
    assert_eq!(fs::read(lib.join("blobs/sha2")).unwrap(), blob(1500, 12));
    assert_eq!(fs::read_link(lib.join("snapshots/abc/model.bin")).unwrap().to_string_lossy(), "../../blobs/sha1");
    assert_eq!(fs::read_link(lib.join("snapshots/abc/config.json")).unwrap().to_string_lossy(), "../../blobs/sha2");
    assert_eq!(
        rig.library_files(),
        ["whisper/models--Systran--x/blobs/sha1", "whisper/models--Systran--x/blobs/sha2"],
        "a copy through the links would double the bytes"
    );
    assert!(lib.join("refs").is_dir(), "the folder with nothing in it came too");
    assert!(!rig.local.join("whisper").exists());
    assert_eq!(rig.local_files(), ["Keep/other.gguf"]);
    let rows = done.summary(9999.0);
    let rows = rows["files"].as_array().unwrap();
    assert_eq!(rows.len(), 1, "the page sees the folder and not the files in it");
    assert_eq!(
        (&rows[0]["path"], &rows[0]["size"], &rows[0]["phase"]),
        (&json!("whisper/models--Systran--x"), &json!(5500), &json!("removed"))
    );
}

#[test]
fn a_link_out_of_the_folder_refuses_the_folder() {
    for (name, target) in
        [("mover-out-rel", None), ("mover-out-abs", Some("/etc/hosts")), ("mover-out-abs-inside", Some("a.bin"))]
    {
        let rig = Rig::new(name);
        let target = match target {
            None => "../../out/secret.gguf".to_string(),
            Some("a.bin") => rig.local.join("whisper/models--x/a.bin").to_string_lossy().into_owned(),
            Some(path) => path.to_string(),
        };
        let secret = rig.put_local("out/secret.gguf", &blob(50, 13));
        let cache = rig.local.join("whisper/models--x");
        Rig::put(&cache, "a.bin", &blob(10, 1));
        std::os::unix::fs::symlink(&target, cache.join("link")).unwrap();
        let done = rig.run(rig.folder_job("whisper/models--x", 10));
        assert_eq!((done.items[0].state.as_str(), done.items[0].note.as_str()), ("skipped", "link-out"), "{name}");
        assert_eq!(done.items[0].detail, format!("whisper/models--x/link → {target}"));
        assert!(rig.library_files().is_empty(), "{name}: nothing was carried");
        assert!(secret.exists() && cache.join("a.bin").exists() && cache.join("link").is_symlink(), "{name}: nothing was taken");
    }
}

#[test]
fn a_file_that_came_or_went_in_the_folder_after_it_was_read_keeps_the_folder_here() {
    for (name, comes) in [("mover-grow", true), ("mover-shrink", false)] {
        let rig = Rig::new(name);
        let cache = rig.local.join("whisper/models--y");
        Rig::put(&cache, "a.bin", &blob(3000, 14));
        Rig::put(&cache, "b.bin", &blob(100, 15));
        let done = rig.run_watching(rig.folder_job("whisper/models--y", 3100), |job| {
            if job.items[0].files.iter().all(|file| file.phase == "proven")
                && job.items[0].files.len() == 2
                && job.items[0].state == "pending"
            {
                if comes {
                    fs::write(cache.join("c.bin"), blob(100, 16)).unwrap();
                } else {
                    drop(fs::remove_file(cache.join("b.bin")));
                }
            }
        });
        assert_eq!((done.items[0].state.as_str(), done.items[0].note.as_str()), ("skipped", "folder-changed"), "{name}");
        assert!(cache.join("a.bin").exists(), "{name}: it would have gone with the folder, unmoved");
        assert_eq!(comes, cache.join("c.bin").exists(), "{name}");
        assert!(rig.lib.join("whisper/models--y/a.bin").exists(), "{name}");
    }
}

#[test]
fn a_pipe_in_the_folder_refuses_the_folder() {
    let rig = Rig::new("mover-odd");
    let cache = rig.local.join("whisper/models--z");
    Rig::put(&cache, "a.bin", &blob(10, 1));
    assert!(std::process::Command::new("mkfifo").arg(cache.join("pipe")).status().unwrap().success());
    let done = rig.run(rig.folder_job("whisper/models--z", 10));
    assert_eq!((done.items[0].state.as_str(), done.items[0].note.as_str()), ("skipped", "folder-odd"));
    assert_eq!(done.items[0].detail, "whisper/models--z/pipe");
    assert!(rig.library_files().is_empty(), "a copy cannot carry it, and removing the folder would take it away");
    assert!(cache.join("pipe").exists() && cache.join("a.bin").exists());
}

#[test]
fn a_folder_with_nothing_to_copy_moves_with_no_wait_and_no_countdown() {
    let rig = Rig::new("mover-void");
    rig.clock.each_look_takes(0);
    let cache = rig.local.join("whisper/models--empty");
    fs::create_dir_all(cache.join("inner")).unwrap();
    std::os::unix::fs::symlink("inner", cache.join("here")).unwrap();
    let done = rig.run(rig.folder_job("whisper/models--empty", 0));
    let lib = rig.lib.join("whisper/models--empty");
    assert_eq!((done.status.as_str(), done.items[0].state.as_str()), ("done", "done"));
    assert!(lib.join("inner").is_dir());
    assert_eq!(fs::read_link(lib.join("here")).unwrap().to_string_lossy(), "inner");
    assert!(!rig.local.join("whisper").exists());
    let row = done.summary(9999.0)["files"][0].clone();
    assert_eq!((&row["removeIn"], &row["size"]), (&json!(0), &json!(0)));
}

#[test]
fn a_folder_that_is_a_link_is_not_called_gone_when_only_the_link_could_go() {
    let rig = Rig::new("mover-folder-link");
    let real = rig.put_local("real/models--z/a.bin", &blob(100, 21));
    fs::create_dir_all(rig.local.join("whisper")).unwrap();
    std::os::unix::fs::symlink("../real/models--z", rig.local.join("whisper/models--z")).unwrap();
    let done = rig.run(rig.folder_job("whisper/models--z", 100));
    assert_eq!((done.items[0].state.as_str(), done.items[0].note.as_str()), ("skipped", "unlink-failed"));
    assert!(rig.local.join("whisper/models--z").is_symlink() && real.exists());
}

#[test]
fn a_gone_source_closes_its_item_and_the_next_goes_on() {
    let rig = Rig::new("mover-gone");
    rig.put_local("A/a.gguf", &blob(10, 1));
    rig.put_local("B/b.gguf", &blob(10, 2));
    let job = rig.job(&[&["A/a.gguf"], &["B/b.gguf"]]);
    fs::remove_file(rig.local.join("A/a.gguf")).unwrap();
    let done = rig.run(job);
    assert_eq!((done.items[0].state.as_str(), done.items[0].note.as_str()), ("skipped", "local-gone"));
    assert_eq!(done.items[1].state, "done");
    assert_eq!(rig.library_files(), ["B/b.gguf"]);

    let rig = Rig::new("mover-gone-folder");
    let done = rig.run(rig.folder_job("whisper/models--none", 10));
    assert_eq!((done.items[0].state.as_str(), done.items[0].note.as_str()), ("skipped", "local-gone"));
}

/// There is no way to make one stat fail but a file that goes between the walk and the stat, so one comes and goes while the folder is read, until it has gone at
/// that moment. Whichever way an attempt falls, nobody pressed Stop: `cancelled` is wrong at every one of them.
#[test]
fn a_failure_while_a_folder_is_read_is_a_failure_with_its_reason_and_never_a_stop() {
    let rig = Rig::new("mover-scan-failure");
    let cache = rig.local.join("whisper/models--b");
    let comes_and_goes = Rig::put(&cache, "boom", b"");
    // Many names to look at between the look at it and its stat, and a link at the end of the walk's order that ends the item before a byte is copied.
    for at in 0..300 {
        fs::File::create(cache.join(format!("z{at:03}"))).unwrap();
    }
    std::os::unix::fs::symlink("/etc/hosts", cache.join("zzzz-out")).unwrap();
    let over = std::sync::atomic::AtomicBool::new(false);
    let ends = std::thread::scope(|scope| {
        scope.spawn(|| {
            while !over.load(std::sync::atomic::Ordering::SeqCst) {
                drop(fs::remove_file(&comes_and_goes));
                drop(fs::File::create(&comes_and_goes));
            }
        });
        let mut ends = Vec::new();
        while ends.len() < 1000 && ends.last().is_none_or(|done: &MoveJob| done.status != "failed") {
            ends.push(rig.run(rig.folder_job("whisper/models--b", 0)));
        }
        over.store(true, std::sync::atomic::Ordering::SeqCst);
        ends
    });
    for done in &ends {
        assert_ne!(done.status, "cancelled", "nobody pressed Stop");
        assert_ne!(done.items[0].state, "cancelled");
        if done.status == "failed" {
            assert!(done.reason.contains("No such file"), "{}", done.reason);
            assert!(done.finished_at > 0);
            assert_eq!(done.items[0].state, "pending", "it stands as it stood, with its source in place");
        }
    }
    assert!(cache.join("z000").exists(), "nothing was carried off");
    assert!(rig.library_files().is_empty());
}

#[test]
fn a_file_that_cannot_be_read_ends_its_item_after_five_failures_and_the_next_goes_on() {
    let rig = Rig::new("mover-unreadable");
    // A folder where a file was planned: it opens and it does not read, for any user.
    fs::create_dir_all(rig.local.join("D/d.gguf")).unwrap();
    rig.put_local("Z/z.gguf", &blob(10, 2));
    let done = rig.run(rig.job(&[&["D/d.gguf"], &["Z/z.gguf"]]));
    let item = &done.items[0];
    assert_eq!((item.state.as_str(), item.note.as_str(), item.errors), ("skipped", "errors", 5), "{}", item.detail);
    assert!(item.detail.starts_with("OSError: "), "{}", item.detail);
    assert_eq!(rig.statuses().iter().filter(|status| *status == "waiting").count(), 4, "a pause between the failures");
    assert!(rig.local.join("D/d.gguf").is_dir());
    assert_eq!(rig.library_files(), ["Z/z.gguf"], "no part of it stayed, and the next item went");
    assert_eq!(done.status, "done");
}

#[test]
fn a_copy_shorter_than_its_plan_is_never_proven() {
    let rig = Rig::new("mover-short-copy");
    let path = rig.put_local("M/m.gguf", &blob(50, 1));
    let files = vec![MoveFile::new("M/m.gguf", 100, Rig::stamp(&path))];
    let mut job = rig.job(&[&["M/m.gguf"]]);
    job.items = vec![MoveItem::new("M/m.gguf", files, "", 0)];
    let done = rig.run(job);
    assert_eq!((done.items[0].state.as_str(), done.items[0].note.as_str()), ("skipped", "errors"));
    assert!(done.items[0].detail.contains("the library copy holds 50 of 100 bytes"), "{}", done.items[0].detail);
    assert!(rig.library_files().is_empty());
    assert!(path.exists());
}

#[test]
fn a_stop_during_the_copy_takes_the_part_away_and_leaves_the_source() {
    let rig = Rig::new("mover-stop-copy");
    let source = rig.local.join("M/m.gguf");
    Rig::endless(&source);
    let job = rig.job(&[&["M/m.gguf"]]);
    let planned = job.items[0].files[0].stamp.clone();
    let done = rig.run_stopping(job, |job| job.items[0].files[0].phase == "copying" && job.items[0].files[0].done >= 3000);
    assert_eq!((done.status.as_str(), done.items[0].state.as_str()), ("cancelled", "cancelled"));
    assert_eq!(rig.phase_order(), ["", "copying"], "it stopped in the copy");
    assert!(rig.library_files().is_empty(), "{:?}", rig.library_files());
    assert_eq!(Rig::stamp(&source), planned, "the source is as it was");
}

#[test]
fn a_stop_during_the_proof_takes_the_part_away_and_leaves_the_source() {
    let rig = Rig::new("mover-stop-proof");
    let (source, part) = (rig.local.join("M/m.gguf"), rig.lib.join("M/m.gguf.caravan-part"));
    Rig::endless(&source);
    Rig::endless(&part);
    let mut job = rig.job(&[&["M/m.gguf"]]);
    let planned = job.items[0].files[0].stamp.clone();
    // The whole part is there, by its record: the copy has nothing to add, and the proof begins at once.
    job.items[0].files[0].synced = planned[0];
    let done = rig.run_stopping(job, |job| job.items[0].files[0].phase == "checking");
    assert_eq!((done.status.as_str(), done.items[0].state.as_str()), ("cancelled", "cancelled"));
    assert_eq!(rig.phase_order(), ["", "copying", "checking"], "it stopped in the proof");
    assert!(rig.library_files().is_empty(), "the unfinished copy goes: {:?}", rig.library_files());
    assert_eq!(Rig::stamp(&source), planned, "the source is as it was");
}

#[test]
fn a_stop_during_the_settle_keeps_both_whole_copies() {
    let rig = Rig::new("mover-stop-settle");
    rig.clock.each_look_takes(0);
    let data = blob(1000, 16);
    rig.put_local("M/m.gguf", &data);
    let done = rig.run_stopping(rig.job(&[&["M/m.gguf"]]), |job| job.items[0].files[0].phase == "proven");
    assert_eq!((done.status.as_str(), done.items[0].state.as_str()), ("cancelled", "cancelled"));
    assert_eq!(fs::read(rig.local.join("M/m.gguf")).unwrap(), data);
    assert_eq!(fs::read(rig.lib.join("M/m.gguf")).unwrap(), data);
    assert_eq!(rig.library_files(), ["M/m.gguf"]);
}

#[test]
fn a_stop_ends_a_wait_for_the_library() {
    let rig = Rig::unmarked("mover-stop-wait");
    rig.put_local("M/m.gguf", &blob(100, 16));
    let done = rig.run_stopping(rig.job(&[&["M/m.gguf"]]), |job| job.status == "waiting");
    assert_eq!(done.status, "cancelled");
    assert!(rig.library_files().is_empty());
    assert_eq!(rig.local_files(), ["M/m.gguf"]);
}

#[test]
fn a_job_stopped_before_it_began_never_begins_and_a_stop_closes_what_was_still_ahead() {
    let rig = Rig::new("mover-stop-before");
    rig.put_local("M/m.gguf", &blob(100, 17));
    let mut job = rig.job(&[&["M/m.gguf"]]);
    job.cancel = true;
    let done = rig.run(job);
    assert_eq!((done.status.as_str(), done.items[0].state.as_str()), ("cancelled", "cancelled"));
    assert!(!rig.statuses().contains(&"running".to_string()), "{:?}", rig.statuses());
    assert!(rig.library_files().is_empty());
    assert_eq!(rig.local_files(), ["M/m.gguf"]);

    let rig = Rig::new("mover-stop-ahead");
    Rig::endless(&rig.local.join("A/a.gguf"));
    rig.put_local("B/b.gguf", &blob(100, 2));
    let done = rig.run_stopping(rig.job(&[&["A/a.gguf"], &["B/b.gguf"]]), |job| job.items[0].files[0].done >= 3000);
    assert_eq!((done.items[0].state.as_str(), done.items[1].state.as_str()), ("cancelled", "cancelled"));
    assert_eq!(rig.local_files(), ["A/a.gguf", "B/b.gguf"]);
}
