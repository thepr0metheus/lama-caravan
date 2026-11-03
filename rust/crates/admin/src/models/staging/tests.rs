//! The update of a model in place: the old build kept under a second name, a revert, a drop, and a whole update against a hub of the test's.

#![allow(
    clippy::unwrap_used,
    clippy::panic,
    clippy::indexing_slicing,
    reason = "a helper of a test may stop where it found something wrong"
)]

use super::*;
use std::os::unix::fs::{MetadataExt, PermissionsExt};

fn folder(name: &str) -> PathBuf {
    let root = std::env::temp_dir().join(format!("staging-{name}-{}", std::process::id()));
    drop(std::fs::remove_dir_all(&root));
    std::fs::create_dir_all(&root).unwrap();
    root
}

fn links_of(path: &Path) -> u64 {
    std::fs::metadata(path).unwrap().nlink()
}

#[test]
fn the_old_build_is_kept_as_a_second_name_and_a_second_keep_takes_its_place() {
    let root = folder("chain");
    let live = root.join("m.gguf");
    std::fs::write(&live, b"build one").unwrap();
    let prev = ModelStaging::link_prev(&live).unwrap();
    assert_eq!(prev, format!("{}.prev", live.display()));
    assert_eq!(links_of(&live), 2, "a link, and nobody reads seventeen gigabytes");
    std::fs::remove_file(&live).unwrap();
    std::fs::write(&live, b"build two").unwrap();
    ModelStaging::link_prev(&live).unwrap();
    assert_eq!(std::fs::read(&prev).unwrap(), b"build two", "the second keep replaces the first");
    assert_eq!(links_of(&live), 2);
    std::fs::remove_dir_all(&root).unwrap();
}

#[test]
fn no_file_means_nothing_to_keep() {
    let root = folder("none");
    assert_eq!(ModelStaging::link_prev(&root.join("gone.gguf")).unwrap(), "");
    std::fs::remove_dir_all(&root).unwrap();
}

#[test]
fn a_keep_that_cannot_clear_the_old_name_leaves_the_working_file_whole() {
    let root = folder("sealed");
    let live = root.join("m.gguf");
    std::fs::write(&live, b"the only build").unwrap();
    // An update that never landed: `.prev` is this very file under its other name, and the folder takes no deletion.
    let prev = root.join("m.gguf.prev");
    std::fs::hard_link(&live, &prev).unwrap();
    std::fs::set_permissions(&root, std::fs::Permissions::from_mode(0o555)).unwrap();
    // Root writes in a sealed folder, and the keep then goes through: only the file's being whole is promised there.
    let sealed = std::fs::File::create(root.join("probe")).is_err();
    let kept = ModelStaging::link_prev(&live);
    std::fs::set_permissions(&root, std::fs::Permissions::from_mode(0o755)).unwrap();
    assert_eq!(std::fs::read(&live).unwrap(), b"the only build", "a copy over its own other name empties the file");
    assert!(!sealed || kept.is_err(), "and it says so");
    std::fs::remove_dir_all(&root).unwrap();
}

#[test]
fn what_stands_in_the_way_of_the_old_name_stops_the_keep() {
    let root = folder("folder");
    let live = root.join("m.gguf");
    std::fs::write(&live, b"the only build").unwrap();
    std::fs::create_dir(root.join("m.gguf.prev")).unwrap();
    assert!(ModelStaging::link_prev(&live).is_err());
    assert_eq!(std::fs::read(&live).unwrap(), b"the only build");
    std::fs::remove_dir_all(&root).unwrap();
}

#[test]
fn a_dead_link_under_the_old_name_is_not_written_through() {
    let root = folder("dangling");
    let live = root.join("m.gguf");
    std::fs::write(&live, b"build").unwrap();
    let prev = root.join("m.gguf.prev");
    std::os::unix::fs::symlink(root.join("elsewhere"), &prev).unwrap();
    ModelStaging::link_prev(&live).unwrap();
    assert!(!root.join("elsewhere").exists(), "the link goes, and nothing lands where it pointed");
    assert_eq!(std::fs::read(&prev).unwrap(), b"build");
    std::fs::remove_dir_all(&root).unwrap();
}

#[test]
fn a_copy_keeps_the_file_s_time() {
    let root = folder("time");
    let (from, to) = (root.join("a"), root.join("b"));
    std::fs::write(&from, b"x").unwrap();
    let old = std::time::SystemTime::UNIX_EPOCH + std::time::Duration::from_secs(1_700_000_000);
    std::fs::File::options().write(true).open(&from).unwrap().set_modified(old).unwrap();
    ModelStaging::copy_with_its_time(&from, &to).unwrap();
    assert_eq!(std::fs::metadata(&to).unwrap().modified().unwrap(), old);
    std::fs::remove_dir_all(&root).unwrap();
}

/// A controller whose hub has the new build, with a model on the disk that its last report says is older.
struct Update {
    folder: crate::tests::TestFolder,
    app: std::sync::Arc<App>,
    hub: crate::tests::StandIn,
    live: PathBuf,
}

const KEY: &str = "Q/a/Q4/m.gguf";
const NEW_BUILD: &[u8] = b"the new build, longer than the old";

impl Update {
    fn new(name: &str, keep_prev: bool) -> Self {
        let body = NEW_BUILD.to_vec();
        let hub = crate::tests::StandIn::serving(move |_| crate::tests::StandIn::answer("200 OK", "", &body));
        let folder = crate::tests::TestFolder::new(&format!("staging-{name}"));
        let app = crate::tests::TestApp::over(&folder.path, &[("CARAVAN_HUB_URL", hub.address())]);
        let live = app.models_dir().join(KEY);
        std::fs::create_dir_all(live.parent().unwrap()).unwrap();
        std::fs::write(&live, b"the old build").unwrap();
        let update = Self { folder, app, hub, live };
        update.report(KEY, &json!({"localPath": update.live.to_string_lossy(), "remotePath": "m.gguf", "remoteSize": NEW_BUILD.len(), "remoteDate": "2030-01-01"}));
        update.app.admin.saving(|doc| doc.insert("modelWatch".to_string(), json!({"keepPrev": keep_prev})));
        update
    }

    fn report(&self, key: &str, row: &Value) {
        self.app.admin.saving(|doc| {
            doc.insert(
                "modelFreshness".to_string(),
                json!({"keys": "path", "checkedAt": 1, "repos": {"acme/model": {"files": {key: row}}}}),
            );
        });
    }

    fn run(&self) -> Value {
        let staging = ModelStaging::of(&self.app);
        let answer = staging.start_update(KEY).unwrap();
        let id = answer["jobId"].as_str().unwrap().to_string();
        for _ in 0..3000 {
            if Downloads::of(&self.app).job(&id).unwrap()["done"] == json!(true) {
                return answer;
            }
            std::thread::sleep(std::time::Duration::from_millis(5));
        }
        panic!("the update did not end");
    }

    fn refusal(&self, key: &str) -> u16 {
        ModelStaging::of(&self.app).start_update(key).map(|_| 0).unwrap_or_else(|refused| refused.status)
    }
}

#[test]
fn a_revert_puts_the_kept_build_back_and_uses_it_up() {
    let root = folder("revert");
    let live = root.join("m.gguf");
    std::fs::write(&live, b"the kept build").unwrap();
    ModelStaging::link_prev(&live).unwrap();
    std::fs::remove_file(&live).unwrap();
    std::fs::write(&live, b"the new build").unwrap();
    let text = live.to_string_lossy().into_owned();
    assert_eq!(ModelStaging::restore_prev(&text).unwrap(), json!({"ok": true, "restored": text}));
    assert_eq!(std::fs::read(&live).unwrap(), b"the kept build");
    assert!(!root.join("m.gguf.prev").exists(), "there is no second revert out of nothing");
    assert_eq!(ModelStaging::restore_prev(&text).unwrap_err().status, 404);
    assert_eq!(std::fs::read(&live).unwrap(), b"the kept build", "and the refusal touches nothing");
    std::fs::remove_dir_all(&root).unwrap();
}

#[test]
fn dropping_the_kept_build_says_what_it_freed_and_leaves_the_working_file() {
    let root = folder("drop");
    let live = root.join("m.gguf");
    std::fs::write(&live, b"12345").unwrap();
    ModelStaging::link_prev(&live).unwrap();
    let text = live.to_string_lossy().into_owned();
    assert_eq!(ModelStaging::drop_prev(&text).unwrap(), json!({"ok": true, "freed": 5}));
    assert!(!root.join("m.gguf.prev").exists());
    assert_eq!(std::fs::read(&live).unwrap(), b"12345");
    assert_eq!(ModelStaging::drop_prev(&text).unwrap(), json!({"ok": true, "freed": 0}), "a second time: nothing, and no error");
    std::fs::remove_dir_all(&root).unwrap();
}

#[test]
fn the_room_asked_for_holds_the_new_build_and_a_margin_and_a_refusal_says_both_figures() {
    let root = folder("room");
    let live = root.join("m.gguf");
    std::fs::write(&live, b"x").unwrap();
    let room = ModelStaging::check_room(&live, 1).unwrap();
    assert_eq!(room["need"], json!(1 + ModelStaging::DISK_MARGIN_BYTES), "both builds lie on the disk while it runs");
    let refused = ModelStaging::check_room(&live, 1 << 60).unwrap_err();
    assert_eq!(refused.status, 409);
    assert!(refused.message.contains("need") && refused.message.contains("free"), "{}", refused.message);
    assert_eq!(
        ModelStaging::check_room(&root.join("no-folder/m.gguf"), 0).unwrap_err().status,
        409,
        "a disk that does not say is no room promised"
    );
    std::fs::remove_dir_all(&root).unwrap();
}

#[test]
fn an_update_keeps_the_old_build_before_the_new_one_lands() {
    let update = Update::new("keep", true);
    let old = std::fs::metadata(&update.live).unwrap().ino();
    let answer = update.run();
    let prev = update.live.with_file_name("m.gguf.prev");
    assert_eq!(answer["prev"], json!(prev.to_string_lossy()));
    assert_eq!((&answer["ok"], &answer["file"]), (&json!(true), &json!(KEY)));
    assert_eq!(std::fs::read(&update.live).unwrap(), NEW_BUILD);
    assert_eq!(std::fs::read(&prev).unwrap(), b"the old build");
    assert_eq!(std::fs::metadata(&prev).unwrap().ino(), old, "the same file under a second name");
    assert_ne!(std::fs::metadata(&update.live).unwrap().ino(), old, "a running cell keeps the file it has open");
    assert_eq!(update.hub.targets(), ["/acme/model/resolve/main/m.gguf"]);
    assert_eq!(ModelStaging::of(&update.app).prev_overview()[KEY]["prevSize"], json!(13));
}

#[test]
fn an_update_with_the_keep_off_leaves_no_second_name() {
    let update = Update::new("no-keep", false);
    let answer = update.run();
    assert_eq!(answer["prev"], json!(""));
    assert_eq!(std::fs::read(&update.live).unwrap(), NEW_BUILD);
    assert!(!update.live.with_file_name("m.gguf.prev").exists());
}

#[test]
fn an_update_that_cannot_keep_the_old_build_does_not_start() {
    let update = Update::new("no-room-for-it", true);
    let prev = update.live.with_file_name("m.gguf.prev");
    std::fs::create_dir(&prev).unwrap();
    let refused = ModelStaging::of(&update.app).start_update(KEY).unwrap_err();
    assert_eq!(refused.status, 500);
    assert!(refused.message.contains("the old build could not be kept, nothing started"), "{}", refused.message);
    assert_eq!(std::fs::read(&update.live).unwrap(), b"the old build");
    assert_eq!(update.hub.asked(), Vec::<String>::new());
    assert!(Downloads::of(&update.app).all().is_empty());
}

#[test]
fn an_update_is_asked_of_the_report_and_refused_for_what_the_report_does_not_say() {
    let update = Update::new("refusals", true);
    let live = update.live.to_string_lossy().into_owned();
    assert_eq!(update.refusal("no/such/file.gguf"), 404, "a path made up by a client is not in the report");
    update.report(KEY, &json!({"localPath": live, "remotePath": "m.gguf", "remoteSize": 13, "remoteDate": "2000-01-01"}));
    assert_eq!(update.refusal(KEY), 409, "the same size and no newer: nothing to fetch");
    update.report(KEY, &json!({"localPath": live, "remoteSize": NEW_BUILD.len(), "remoteDate": "2030-01-01"}));
    assert_eq!(update.refusal(KEY), 409, "no path on the hub");
    update
        .report(KEY, &json!({"localPath": live, "remotePath": "m.gguf", "remoteSize": 1_i64 << 60, "remoteDate": "2030-01-01"}));
    assert_eq!(update.refusal(KEY), 409, "no room for both builds");
    let outside = update.folder.path.join("elsewhere.gguf");
    std::fs::write(&outside, b"x").unwrap();
    update.report(
        KEY,
        &json!({"localPath": outside.to_string_lossy(), "remotePath": "m.gguf", "remoteSize": 5, "remoteDate": "2030-01-01"}),
    );
    assert_eq!(update.refusal(KEY), 409, "it lives outside the models folder");
    update.report(KEY, &json!({"localPath": update.folder.path.join("gone.gguf").to_string_lossy(), "remotePath": "m.gguf", "remoteSize": 5, "remoteDate": "2030-01-01"}));
    assert_eq!(update.refusal(KEY), 404, "the file is gone");
    assert_eq!(update.hub.asked(), Vec::<String>::new(), "a refusal asks the hub nothing");
    assert_eq!(std::fs::read(&update.live).unwrap(), b"the old build");
}

#[test]
fn two_copies_of_one_name_are_two_files_and_the_update_writes_the_one_it_was_asked_for() {
    let update = Update::new("two-quants", false);
    let other = update.app.models_dir().join("Q/a/Q8/m.gguf");
    std::fs::create_dir_all(other.parent().unwrap()).unwrap();
    std::fs::write(&other, b"the other quant").unwrap();
    let row = |path: &Path| json!({"localPath": path.to_string_lossy(), "remotePath": "m.gguf", "remoteSize": NEW_BUILD.len(), "remoteDate": "2030-01-01"});
    update.app.admin.saving(|doc| {
        doc.insert(
            "modelFreshness".to_string(),
            json!({"keys": "path", "checkedAt": 1, "repos": {"acme/model": {"files": {KEY: row(&update.live), "Q/a/Q8/m.gguf": row(&other)}}}}),
        );
    });
    update.run();
    assert_eq!(std::fs::read(&update.live).unwrap(), NEW_BUILD);
    assert_eq!(std::fs::read(&other).unwrap(), b"the other quant");
}
