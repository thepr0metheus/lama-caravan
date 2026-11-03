//! Looking inside a store from a child process, with a deadline: a share that hangs hangs its reader, and a controller must not hang with it. The child is this same program under `--store-probe`: nothing but what it says on its standard output comes back.

use crate::common::artifacts::ModelArtifacts;
use os::Disk;
use rules::{Coerce, PythonJson};
use serde_json::{Map, Value, json};
use std::os::unix::fs::{MetadataExt, PermissionsExt};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::Duration;

/// The name of a store's mark.
pub const MARKER_NAME: &str = rules::LibraryMark::NAME;

/// The parent's side.
#[derive(Debug, Clone)]
pub struct StoreProbe {
    timeout: Duration,
    program: PathBuf,
}

impl StoreProbe {
    /// The argument the child is started with.
    pub const CHILD_FLAG: &'static str = "--store-probe";
    const PROBE_TIMEOUT: Duration = Duration::from_secs(8);
    const LIST_LIMIT: i64 = 200;
    const FILES_LIMIT: i64 = 5000;

    /// The probe, by this program.
    pub fn new() -> Self {
        // absent-ok: a program that cannot say where it is goes by its name; the spawn says if that fails.
        let program = std::env::current_exe().unwrap_or_else(|_| PathBuf::from("caravan-admin"));
        // The test binary is no probe: see `run`.
        let program = if cfg!(test) { PathBuf::new() } else { program };
        Self { timeout: Self::PROBE_TIMEOUT, program }
    }

    /// What the folder holds, the listing only when asked.
    pub fn look(&self, root: &str, listing: bool) -> Value {
        self.run("probe", root, json!({"list": listing, "limit": Self::LIST_LIMIT, "files_limit": Self::FILES_LIMIT}))
    }

    /// Marks the folder as a library, or finds it marked.
    pub fn claim(&self, root: &str, store_id: &str, name: &str, force: bool) -> Value {
        self.run("claim", root, json!({"id": store_id, "name": name, "force": force}))
    }

    /// The file a folder of a test says what a look at it comes to in.
    #[cfg(test)]
    pub const SAYS: &'static str = ".test-probe-says.json";

    /// A probe by a program of the test's: `program` empty answers in the test's own process, for the test binary is no probe.
    #[cfg(test)]
    pub fn by_program(program: PathBuf, timeout: Duration) -> Self {
        Self { timeout, program }
    }

    fn run(&self, command: &str, root: &str, args: Value) -> Value {
        #[cfg(test)]
        if self.program.as_os_str().is_empty() {
            // A folder of a test may say what the child would, for what no folder can be made to do: a share that hangs.
            if let Ok(said) = std::fs::read(Path::new(root).join(Self::SAYS)) {
                // absent-ok: what is no JSON says nothing, and reads as a probe that failed.
                return serde_json::from_slice(&said).unwrap_or(Value::Null);
            }
            let now = os::clock::Clock::epoch(&os::clock::SystemClock::new()) as i64;
            return StoreProbeChild::answer(command, root, &PythonJson::spaced(&args), now);
        }
        let spawned = Command::new(&self.program)
            .args([Self::CHILD_FLAG, command, root, &PythonJson::spaced(&args)])
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn();
        let mut child = match spawned {
            Ok(child) => child,
            Err(error) => return json!({"ok": false, "error": format!("the probe did not start: {error}")}),
        };
        let (out, err) = (child.stdout.take(), child.stderr.take());
        let (out, err) = (Self::collected(out), Self::collected(err));
        let mut spent = Duration::ZERO;
        const TURN: Duration = Duration::from_millis(20);
        loop {
            match child.try_wait() {
                Ok(Some(_)) => break,
                Ok(None) if spent >= self.timeout => {
                    // A child stuck on a dead share may never go: it is left to end on its own, on a thread.
                    drop(child.kill());
                    std::thread::spawn(move || drop(child.wait()));
                    return json!({"ok": false, "timeout": true, "error": format!("no answer in {} s", self.timeout.as_secs())});
                }
                Ok(None) => {
                    std::thread::sleep(TURN);
                    spent += TURN;
                }
                Err(error) => return json!({"ok": false, "error": error.to_string()}),
            }
        }
        // absent-ok: a reader that panicked read nothing, and a child that said nothing is what the next lines are for.
        let said = String::from_utf8_lossy(&out.join().unwrap_or_default()).into_owned();
        if let Ok(doc) = serde_json::from_str::<Value>(Coerce::strip(&said))
            && doc.is_object()
        {
            return doc;
        }
        // absent-ok: as above.
        let words = String::from_utf8_lossy(&err.join().unwrap_or_default()).into_owned();
        let last = Coerce::strip(&words).lines().last().unwrap_or("the probe printed nothing").to_string();
        json!({"ok": false, "error": Coerce::first_letters(&last, 300)})
    }

    fn collected(pipe: Option<impl std::io::Read + Send + 'static>) -> std::thread::JoinHandle<Vec<u8>> {
        std::thread::spawn(move || {
            let mut out = Vec::new();
            if let Some(mut pipe) = pipe {
                // What came before a read failed is what it said.
                drop(pipe.read_to_end(&mut out));
            }
            out
        })
    }
}

impl Default for StoreProbe {
    fn default() -> Self {
        Self::new()
    }
}

/// The child's side: looks once, says one line, ends.
pub struct StoreProbeChild {
    root: String,
    args: Value,
    now: i64,
}

/// One model folder found by the walk: its path, its kind, what it weighs and when it last changed.
struct FoundFolder {
    rel: String,
    kind: &'static str,
    size: i64,
    mtime: i64,
}

/// What the walk adds up.
#[derive(Default)]
struct Tally {
    folders: Map<String, Value>,
    files: i64,
    size: i64,
    ggufs: Vec<(String, i64, i64)>,
    arts: Vec<FoundFolder>,
}

impl Tally {
    fn count(&mut self, key: &str, size: i64) {
        let entry = self.folders.entry(key.to_string()).or_insert_with(|| json!({"name": key, "bytes": 0, "files": 0}));
        // absent-ok: the entry was made with both figures on the line above.
        entry["bytes"] = json!(Coerce::i64_or_zero(entry.get("bytes")) + size);
        // absent-ok: as above.
        entry["files"] = json!(Coerce::i64_or_zero(entry.get("files")) + 1);
    }
}

impl StoreProbeChild {
    /// What the child prints, from its arguments: the command, the root and the JSON of the rest.
    pub fn answer(command: &str, root: &str, args: &str, now: i64) -> Value {
        let args: Value = serde_json::from_str(args).unwrap_or_else(|_| json!({}));
        let child = Self { root: root.to_string(), args, now };
        child.look(command).unwrap_or_else(|error| json!({"ok": false, "error": error}))
    }

    fn mark_path(&self) -> PathBuf {
        Path::new(&self.root).join(MARKER_NAME)
    }

    fn read_mark(&self) -> Option<Value> {
        let doc: Value = serde_json::from_slice(&std::fs::read(self.mark_path()).ok()?).ok()?;
        (doc.is_object() && !Coerce::stripped(doc.get("id")).is_empty()).then_some(doc)
    }

    /// `os.path.ismount`.
    fn is_mount(root: &Path) -> bool {
        let Ok(meta) = std::fs::symlink_metadata(root) else {
            return false;
        };
        if meta.file_type().is_symlink() {
            return false;
        }
        std::fs::symlink_metadata(root.join("..")).is_ok_and(|parent| parent.dev() != meta.dev() || parent.ino() == meta.ino())
    }

    fn look(&self, command: &str) -> Result<Value, String> {
        let root = Path::new(&self.root);
        if !root.is_dir() {
            return Ok(json!({"ok": true, "exists": false}));
        }
        let found = self.read_mark();
        let mounted = Self::is_mount(root);
        if command == "claim" {
            return Ok(self.claim(found, mounted));
        }
        let (total, free) = Disk::usage(root).ok_or_else(|| format!("OSError: no figures for {}", self.root))?;
        let mut doc = json!({"ok": true, "exists": true, "mounted": mounted, "marker": found, "free": free, "total": total, "writable": Disk::writable(root)});
        if Coerce::truthy(self.args.get("list"))
            && let Value::Object(fields) = &mut doc
        {
            fields.extend(self.listing());
        }
        Ok(doc)
    }

    fn claim(&self, found: Option<Value>, mounted: bool) -> Value {
        if let Some(found) = found {
            return json!({"ok": true, "exists": true, "adopted": true, "marker": found});
        }
        if !mounted && !Coerce::truthy(self.args.get("force")) {
            return json!({"ok": true, "exists": true, "refused": "not-a-mount"});
        }
        let doc = json!({"id": self.args.get("id"), "name": Coerce::text(self.args.get("name")), "role": "library", "createdAt": self.now, "tool": "lama-caravan"});
        let mark = self.mark_path();
        let temporary = mark.with_file_name(format!("{MARKER_NAME}.tmp"));
        let text = PythonJson::indented(&doc) + "\n";
        let written = std::fs::File::create(&temporary).and_then(|mut file| {
            use std::io::Write;
            file.write_all(text.as_bytes())?;
            file.sync_all()
        });
        if let Err(error) = written.and_then(|()| std::fs::rename(&temporary, &mark)) {
            return json!({"ok": true, "exists": true, "refused": "not-writable", "error": error.to_string()});
        }
        // A library's mark is what everyone reads: it stays readable by them.
        drop(std::fs::set_permissions(&mark, std::fs::Permissions::from_mode(0o644)));
        json!({"ok": true, "exists": true, "adopted": false, "marker": doc})
    }

    fn listing(&self) -> Map<String, Value> {
        let mut tally = Tally::default();
        Self::walk(Path::new(&self.root), "", &mut tally);
        for index in 0..tally.arts.len() {
            let Some(art) = tally.arts.get(index) else {
                continue;
            };
            let (key, size) = (art.rel.split('/').next().unwrap_or_default().to_string(), art.size);
            tally.files += 1;
            tally.size += size;
            tally.count(&key, size);
        }
        tally.arts.sort_by(|left, right| left.rel.cmp(&right.rel).then_with(|| left.kind.cmp(right.kind)));
        let mut ranked: Vec<Value> = tally.folders.values().cloned().collect();
        // absent-ok: each entry was made with its figures; the sort needs a number.
        ranked.sort_by_key(|row| (std::cmp::Reverse(Coerce::i64_or_zero(row.get("bytes"))), Coerce::text(row.get("name"))));
        let limit = self.limit("limit", 200);
        tally.ggufs.sort();
        let cap = self.limit("files_limit", 5000);
        let mut out = Map::new();
        out.insert("files".to_string(), json!(tally.files));
        out.insert("bytes".to_string(), json!(tally.size));
        out.insert("more".to_string(), json!(ranked.len().saturating_sub(limit)));
        ranked.truncate(limit);
        out.insert("folders".to_string(), json!(ranked));
        out.insert(
            "entries".to_string(),
            json!(tally.ggufs.iter().take(cap).map(|(rel, size, mtime)| json!([rel, size, mtime])).collect::<Vec<_>>()),
        );
        out.insert("entriesMore".to_string(), json!(tally.ggufs.len().saturating_sub(cap)));
        out.insert(
            "dirs".to_string(),
            json!(tally.arts.iter().take(cap).map(|art| json!([art.rel, art.kind, art.size, art.mtime])).collect::<Vec<_>>()),
        );
        out.insert("dirsMore".to_string(), json!(tally.arts.len().saturating_sub(cap)));
        out
    }

    fn limit(&self, key: &str, otherwise: usize) -> usize {
        let said = self.args.get(key).filter(|said| Coerce::truthy(Some(*said))).and_then(Coerce::int);
        said.and_then(|said| usize::try_from(said).ok()).unwrap_or(otherwise)
    }

    /// A model folder, a whisper cache or a checkpoint, is ONE thing here: the walk goes through it to weigh it, but nothing inside is named on its own.
    fn walk(folder: &Path, rel: &str, tally: &mut Tally) {
        let (mut folders, mut plain) = (Vec::new(), Vec::new());
        for entry in std::fs::read_dir(folder).into_iter().flatten().flatten() {
            let name = entry.file_name().to_string_lossy().into_owned();
            if ModelArtifacts::hidden(&name) {
                continue;
            }
            // A link to a folder is a folder, whatever its name, and the walk does not go through it: it would weigh another folder's files twice.
            if entry.path().is_dir() {
                if !entry.file_type().is_ok_and(|kind| kind.is_symlink()) {
                    folders.push(name);
                }
            } else {
                plain.push(name);
            }
        }
        let inside = |tally: &Tally| {
            tally
                .arts
                .iter()
                .position(|art| rel == art.rel || rel.strip_prefix(art.rel.as_str()).is_some_and(|tail| tail.starts_with('/')))
        };
        let mut art = inside(tally);
        if art.is_none() {
            let kind = ModelArtifacts::kind(rel, &plain);
            if !kind.is_empty() {
                tally.arts.push(FoundFolder { rel: rel.to_string(), kind, size: 0, mtime: 0 });
                art = Some(tally.arts.len() - 1);
            }
        }
        for name in plain {
            Self::one_file(folder, rel, &name, art, tally);
        }
        for name in folders {
            let inner = if rel.is_empty() { name.clone() } else { format!("{rel}/{name}") };
            Self::walk(&folder.join(&name), &inner, tally);
        }
    }

    fn one_file(folder: &Path, rel: &str, name: &str, art: Option<usize>, tally: &mut Tally) {
        let Ok(meta) = std::fs::symlink_metadata(folder.join(name)) else {
            return;
        };
        if let Some(art) = art.and_then(|at| tally.arts.get_mut(at)) {
            // Links weigh nothing: a move plants them, it does not copy them, and a cache keeps every blob under one of each.
            if meta.file_type().is_file() {
                art.size += meta.size() as i64;
                art.mtime = art.mtime.max(meta.mtime());
            }
            return;
        }
        if !name.ends_with(".gguf") && !name.ends_with(".safetensors") {
            return;
        }
        let size = meta.size() as i64;
        tally.files += 1;
        tally.size += size;
        let key = if rel.is_empty() { name } else { rel.split('/').next().unwrap_or(rel) };
        tally.count(key, size);
        if name.ends_with(".gguf") {
            tally.ggufs.push((if rel.is_empty() { name.to_string() } else { format!("{rel}/{name}") }, size, meta.mtime()));
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::tests::TestFolder;

    fn folder(name: &str) -> PathBuf {
        let root = std::env::temp_dir().join(format!("store-probe-{name}-{}", std::process::id()));
        std::fs::create_dir_all(&root).unwrap();
        root
    }

    fn answer(command: &str, root: &Path, args: Value) -> Value {
        StoreProbeChild::answer(command, root.to_str().unwrap(), &args.to_string(), 100)
    }

    /// A program that says `body` as a shell says it, whatever it is asked. It is run once before it is given: a process another test forks while the file is being
    /// written holds it open until it execs, and until then the kernel will not run it ("Text file busy", seen once in CI). Only a test writes the program it runs.
    fn script(root: &Path, body: &str) -> PathBuf {
        use std::os::unix::fs::PermissionsExt;
        let path = root.join("probe.sh");
        std::fs::write(&path, format!("#!/bin/sh\n[ \"$1\" = --ready ] && exit 0\n{body}\n")).unwrap();
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o755)).unwrap();
        while Command::new(&path)
            .arg("--ready")
            .status()
            .is_err_and(|error| error.kind() == std::io::ErrorKind::ExecutableFileBusy)
        {
            std::thread::sleep(Duration::from_millis(5));
        }
        path
    }

    #[test]
    fn a_probe_that_hangs_is_not_waited_for() {
        let root = folder("hangs");
        let probe = StoreProbe::by_program(script(&root, "sleep 30"), Duration::from_millis(100));
        let said = probe.look(root.to_str().unwrap(), false);
        assert_eq!(said.get("timeout"), Some(&json!(true)), "{said}");
        assert_eq!(said.get("ok"), Some(&json!(false)));
        std::fs::remove_dir_all(&root).unwrap();
    }

    #[test]
    fn a_probe_that_says_no_json_is_said_by_its_last_line() {
        let root = folder("garbage");
        let probe =
            StoreProbe::by_program(script(&root, "echo first >&2; echo last line >&2; echo not json"), Duration::from_secs(5));
        let said = probe.look(root.to_str().unwrap(), false);
        assert_eq!(said, json!({"ok": false, "error": "last line"}));
        let silent = StoreProbe::by_program(script(&root, "exit 3"), Duration::from_secs(5));
        assert_eq!(silent.look(root.to_str().unwrap(), false), json!({"ok": false, "error": "the probe printed nothing"}));
        let gone = StoreProbe::by_program(root.join("nothing-here"), Duration::from_secs(5));
        assert!(
            gone.look(root.to_str().unwrap(), false)
                .get("error")
                .unwrap()
                .as_str()
                .unwrap()
                .starts_with("the probe did not start")
        );
        std::fs::remove_dir_all(&root).unwrap();
    }

    #[test]
    fn a_probe_in_a_test_answers_in_its_process() {
        let root = folder("in-process");
        let said = StoreProbe::new().look(root.to_str().unwrap(), false);
        assert_eq!(said.get("ok"), Some(&json!(true)), "{said}");
        std::fs::remove_dir_all(&root).unwrap();
    }

    /// A library's folder as the old table has it, its mark in place.
    fn marked_library(path: &Path) {
        std::fs::create_dir_all(path.join("Qwen/unsloth/Q4")).unwrap();
        std::fs::write(path.join("Qwen/unsloth/Q4/q.gguf"), vec![b'x'; 3000]).unwrap();
        std::fs::write(path.join("Qwen/unsloth/Q4/._q.gguf"), vec![b'y'; 10]).unwrap();
        std::fs::create_dir(path.join("Small")).unwrap();
        std::fs::write(path.join("Small/s.gguf"), vec![b'x'; 100]).unwrap();
        for system in ["#recycle", "@eaDir", ".hidden"] {
            std::fs::create_dir(path.join(system)).unwrap();
            std::fs::write(path.join(system).join("old.gguf"), vec![b'x'; 5000]).unwrap();
        }
        std::fs::write(path.join("root.gguf"), vec![b'x'; 50]).unwrap();
        std::fs::write(path.join("notes.txt"), b"not a model").unwrap();
        std::fs::write(path.join(MARKER_NAME), json!({"id": "lib-new", "name": "NAS"}).to_string()).unwrap();
    }

    fn paths_of(list: Option<&Value>) -> Vec<String> {
        list.unwrap().as_array().unwrap().iter().map(|row| row[0].as_str().unwrap().to_string()).collect()
    }

    #[test]
    fn a_look_says_the_mark_the_room_and_whether_it_can_be_written() {
        let root = TestFolder::new("probe-look");
        marked_library(&root.path);
        let look = answer("probe", &root.path, json!({"list": true}));
        assert_eq!(
            (&look["ok"], &look["exists"], &look["marker"]["id"], &look["writable"]),
            (&json!(true), &json!(true), &json!("lib-new"), &json!(true))
        );
        assert!(look["total"].as_i64().unwrap() > 0, "{look}");
    }

    #[test]
    fn inside_a_library_only_models_count_and_shadows_and_system_folders_do_not() {
        let root = TestFolder::new("probe-counts");
        marked_library(&root.path);
        let look = answer("probe", &root.path, json!({"list": true}));
        assert_eq!(
            (&look["files"], &look["bytes"]),
            (&json!(3), &json!(3150)),
            "no ._ shadow, no #recycle, no @eaDir, nothing hidden, no notes"
        );
        let entries = look["entries"].as_array().unwrap();
        let named: Vec<(&Value, &Value)> = entries.iter().map(|row| (&row[0], &row[1])).collect();
        assert_eq!(
            named,
            [
                (&json!("Qwen/unsloth/Q4/q.gguf"), &json!(3000)),
                (&json!("Small/s.gguf"), &json!(100)),
                (&json!("root.gguf"), &json!(50))
            ]
        );
        assert!(entries.iter().all(|row| row[2].as_i64().unwrap() > 1_600_000_000), "with its time: {entries:?}");
        assert_eq!(look["entriesMore"], json!(0));
    }

    #[test]
    fn a_limit_cuts_a_list_and_what_it_left_out_is_named_by_a_number() {
        let root = TestFolder::new("probe-limits");
        marked_library(&root.path);
        let look = answer("probe", &root.path, json!({"list": true, "limit": 2}));
        let names: Vec<&Value> = look["folders"].as_array().unwrap().iter().map(|row| &row["name"]).collect();
        assert_eq!(names, [&json!("Qwen"), &json!("Small")], "the largest first");
        assert_eq!(look["more"], json!(1));
        let capped = answer("probe", &root.path, json!({"list": true, "files_limit": 2}));
        assert_eq!(paths_of(capped.get("entries")), ["Qwen/unsloth/Q4/q.gguf", "Small/s.gguf"]);
        assert_eq!(capped["entriesMore"], json!(1));
    }

    #[test]
    fn with_no_request_to_list_a_look_is_the_state_alone_and_no_walk() {
        let root = TestFolder::new("probe-plain");
        marked_library(&root.path);
        let plain = answer("probe", &root.path, json!({}));
        assert_eq!(plain["ok"], json!(true));
        assert!(plain.get("folders").is_none() && plain.get("files").is_none() && plain.get("entries").is_none(), "{plain}");
        assert_eq!(
            answer("probe", &root.path.join("nope"), json!({})),
            json!({"ok": true, "exists": false}),
            "no folder is a no, and no error"
        );
    }

    /// A library with a model that is a whole folder: a whisper cache and a checkpoint.
    fn with_model_folders(path: &Path) {
        marked_library(path);
        let cache = path.join("whisper/models--Systran--faster-whisper-large-v3");
        std::fs::create_dir_all(cache.join("blobs")).unwrap();
        std::fs::create_dir_all(cache.join("snapshots/abc")).unwrap();
        std::fs::write(cache.join("blobs/deadbeef"), vec![b'x'; 1000]).unwrap();
        std::os::unix::fs::symlink("../../blobs/deadbeef", cache.join("snapshots/abc/model.safetensors")).unwrap();
        std::fs::create_dir_all(path.join("sd/ckpt")).unwrap();
        std::fs::write(path.join("sd/ckpt/model.safetensors"), vec![b'y'; 400]).unwrap();
    }

    #[test]
    fn a_model_that_is_a_folder_is_named_whole_and_a_link_in_it_is_not_counted_twice() {
        let root = TestFolder::new("probe-model-folders");
        with_model_folders(&root.path);
        let look = answer("probe", &root.path, json!({"list": true}));
        let dirs: Vec<(&Value, &Value, &Value)> =
            look["dirs"].as_array().unwrap().iter().map(|row| (&row[0], &row[1], &row[2])).collect();
        assert_eq!(
            dirs,
            [
                (&json!("sd/ckpt"), &json!("safetensors"), &json!(400)),
                (&json!("whisper/models--Systran--faster-whisper-large-v3"), &json!("whisper"), &json!(1000))
            ],
            "the link in the cache weighs nothing: its blob is counted already; a moved cache would vanish from the page without this"
        );
        assert_eq!((&look["files"], &look["bytes"]), (&json!(5), &json!(4550)), "each counts as one thing");
    }

    #[test]
    fn nothing_inside_a_model_folder_is_named_on_its_own() {
        let root = TestFolder::new("probe-inside");
        with_model_folders(&root.path);
        let look = answer("probe", &root.path, json!({"list": true}));
        assert!(paths_of(look.get("entries")).iter().all(|path| !path.starts_with("whisper/") && !path.starts_with("sd/")));
        assert!(
            !paths_of(look.get("dirs")).iter().any(|path| path.ends_with("snapshots/abc")),
            "a snapshot is a part of the cache: one move would carry off half"
        );
    }

    #[test]
    fn a_weights_file_at_the_top_does_not_make_the_whole_library_one_model() {
        let root = TestFolder::new("probe-stray");
        std::fs::write(root.path.join("stray.safetensors"), b"xx").unwrap();
        let look = answer("probe", &root.path, json!({"list": true}));
        assert_eq!(look["dirs"], json!([]));
        assert_eq!((&look["files"], &look["bytes"]), (&json!(1), &json!(2)));
    }

    #[test]
    fn a_link_to_a_folder_makes_no_checkpoint_of_the_folder_it_stands_in() {
        let root = TestFolder::new("probe-linked-weights");
        std::fs::create_dir_all(root.path.join("m/a/real")).unwrap();
        std::os::unix::fs::symlink("real", root.path.join("m/a/x.safetensors")).unwrap();
        let look = answer("probe", &root.path, json!({"list": true}));
        assert_eq!((&look["dirs"], &look["files"]), (&json!([]), &json!(0)), "{look}");
    }

    #[test]
    fn a_link_to_a_file_is_listed_as_itself_and_its_target_is_not_weighed() {
        let root = TestFolder::new("probe-linked-file");
        std::fs::create_dir_all(root.path.join("m")).unwrap();
        std::fs::write(root.path.join("m/real.bin"), vec![b'x'; 100]).unwrap();
        std::os::unix::fs::symlink("real.bin", root.path.join("m/link.gguf")).unwrap();
        let look = answer("probe", &root.path, json!({"list": true}));
        assert_eq!(look["entries"][0][0], json!("m/link.gguf"));
        assert_eq!(
            look["entries"][0][1],
            json!("real.bin".len()),
            "the link's own size, as the walk has always read it: a look at the target could wait on a dead share"
        );
    }

    #[test]
    fn a_mark_that_does_not_read_or_names_nobody_is_no_mark() {
        let root = TestFolder::new("probe-marks");
        let mark = root.path.join(MARKER_NAME);
        for (text, why) in
            [("{not json", "garbage"), ("[1, 2]", "a list"), ("{\"name\": \"x\"}", "no id"), ("{\"id\": \"  \"}", "a blank id")]
        {
            std::fs::write(&mark, text).unwrap();
            assert_eq!(answer("probe", &root.path, json!({}))["marker"], Value::Null, "{why}");
        }
        std::fs::write(&mark, "{\"id\": \"lib-1\"}").unwrap();
        assert_eq!(answer("probe", &root.path, json!({}))["marker"]["id"], json!("lib-1"));
    }

    #[test]
    fn a_probe_that_hangs_is_killed_and_its_end_is_not_waited_for() {
        let root = TestFolder::new("probe-killed");
        let probe = StoreProbe::by_program(script(&root.path, "sleep 30"), Duration::from_millis(100));
        let began = std::time::Instant::now();
        let said = probe.look(root.path.to_str().unwrap(), false);
        assert!(began.elapsed() < Duration::from_secs(5), "{:?}", began.elapsed());
        assert_eq!(said, json!({"ok": false, "timeout": true, "error": "no answer in 0 s"}));
    }

    #[test]
    fn a_probes_answer_that_is_no_object_is_no_answer() {
        let root = TestFolder::new("probe-no-object");
        let probe = StoreProbe::by_program(script(&root.path, "echo '[1, 2]'; echo why >&2"), Duration::from_secs(5));
        assert_eq!(probe.look(root.path.to_str().unwrap(), false), json!({"ok": false, "error": "why"}));
    }

    #[test]
    fn a_child_is_told_the_command_the_root_and_the_limits_and_a_listing_only_when_asked() {
        let root = TestFolder::new("probe-asked");
        let heard = root.path.join("heard");
        let program = script(&root.path, &format!("echo \"$*\" > {}; echo '{{\"ok\": true}}'", heard.display()));
        let probe = StoreProbe::by_program(program, Duration::from_secs(5));
        let at = root.path.to_str().unwrap();
        assert_eq!(probe.look(at, true), json!({"ok": true}));
        let said = std::fs::read_to_string(&heard).unwrap();
        assert!(said.starts_with(&format!("--store-probe probe {at} ")), "{said}");
        let args: Value = serde_json::from_str(said.split_once(&format!("{at} ")).unwrap().1.trim()).unwrap();
        assert_eq!(args, json!({"list": true, "limit": 200, "files_limit": 5000}));
        probe.look(at, false);
        let said = std::fs::read_to_string(&heard).unwrap();
        assert!(said.contains("\"list\": false"), "the state alone: {said}");
        probe.claim(at, "lib-1", "NAS", true);
        let said = std::fs::read_to_string(&heard).unwrap();
        assert!(said.starts_with(&format!("--store-probe claim {at} ")), "{said}");
        let args: Value = serde_json::from_str(said.split_once(&format!("{at} ")).unwrap().1.trim()).unwrap();
        assert_eq!(args, json!({"id": "lib-1", "name": "NAS", "force": true}));
    }

    #[test]
    fn a_share_not_mounted_is_not_marked() {
        let root = folder("claim");
        let refused = answer("claim", &root, json!({"id": "lib-1", "name": "N"}));
        assert_eq!(refused.get("refused"), Some(&json!("not-a-mount")));
        let made = answer("claim", &root, json!({"id": "lib-1", "name": "N", "force": true}));
        assert_eq!(made.get("adopted"), Some(&json!(false)));
        let again = answer("claim", &root, json!({"id": "lib-2"}));
        assert_eq!(again.get("adopted"), Some(&json!(true)));
        assert_eq!(again.get("marker").unwrap().get("id"), Some(&json!("lib-1")));
        assert_eq!(answer("claim", &root.join("nope"), json!({})), json!({"ok": true, "exists": false}));
        std::fs::remove_dir_all(&root).unwrap();
    }

    #[test]
    fn a_link_to_a_folder_is_no_model_and_is_not_walked() {
        let root = folder("linked");
        std::fs::create_dir_all(root.join("Repo-GGUF/auth/Q4_K_M")).unwrap();
        std::fs::write(root.join("Repo-GGUF/auth/Q4_K_M/x.gguf"), b"123").unwrap();
        std::os::unix::fs::symlink("Q4_K_M", root.join("Repo-GGUF/auth/linkdir.gguf")).unwrap();
        std::os::unix::fs::symlink("Q4_K_M", root.join("Repo-GGUF/auth/again")).unwrap();
        let doc = answer("probe", &root, json!({"list": true}));
        assert_eq!(doc.get("files"), Some(&json!(1)));
        assert_eq!(doc.get("bytes"), Some(&json!(3)));
        let entries = doc.get("entries").unwrap().as_array().unwrap();
        assert_eq!(entries.len(), 1, "{entries:?}");
        assert_eq!(entries.first().unwrap().get(0), Some(&json!("Repo-GGUF/auth/Q4_K_M/x.gguf")));
        std::fs::remove_dir_all(&root).unwrap();
    }

    #[test]
    fn a_listing_names_each_model_once() {
        let root = folder("list");
        std::fs::create_dir_all(root.join("m/a")).unwrap();
        std::fs::create_dir_all(root.join("whisper/models--a--b/snap")).unwrap();
        std::fs::create_dir_all(root.join("#recycle")).unwrap();
        std::fs::write(root.join("m/a/x.gguf"), b"123").unwrap();
        std::fs::write(root.join("m/a/._x.gguf"), b"1").unwrap();
        std::fs::write(root.join("m/a/note.txt"), b"1").unwrap();
        std::fs::write(root.join("#recycle/y.gguf"), b"1").unwrap();
        std::fs::write(root.join("whisper/models--a--b/blob"), b"12345").unwrap();
        std::os::unix::fs::symlink("../blob", root.join("whisper/models--a--b/snap/model.safetensors")).unwrap();
        let doc = answer("probe", &root, json!({"list": true}));
        assert_eq!(doc.get("files"), Some(&json!(2)));
        assert_eq!(doc.get("bytes"), Some(&json!(8)));
        assert_eq!(
            doc.get("folders"),
            Some(&json!([{"name": "whisper", "bytes": 5, "files": 1}, {"name": "m", "bytes": 3, "files": 1}]))
        );
        assert_eq!(doc.get("entries").unwrap().get(0).unwrap().get(0), Some(&json!("m/a/x.gguf")));
        assert_eq!(doc.get("dirs").unwrap().get(0).unwrap().get(1), Some(&json!("whisper")));
        assert_eq!(doc.get("dirsMore"), Some(&json!(0)));
        std::fs::remove_dir_all(&root).unwrap();
    }
}
