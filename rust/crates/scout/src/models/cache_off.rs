//! A machine that keeps no copies of models (the owner, 2026-11-02: "turn caching off on the device, on its disk"): nothing of a model lands on its disk. The model comes through the controller as it is
//! read (`LibraryView`), and a machine that mounts the library may be told to read it from that folder instead; a start that cannot read its model the way chosen is refused in words, rather than brought here after all.

use crate::errors::AppError;
use crate::models::ModelFetcher;
use crate::state::ScoutState;
use rules::{Coerce, LibraryMark};
use serde_json::{Map, Value, json};
use std::collections::BTreeSet;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::sync::mpsc::channel;
use std::time::Duration;

/// The library on this machine, found by itself (the owner, 2026-11-02: "why ask for a folder?"): the controller leaves its mark at the top of a library, and a machine that
/// mounts it has the mark in one of its mounts. Exactly one is an answer. None, or two, are a question for the operator: guessing between two would read the wrong models.
pub struct LibraryFinder;

impl LibraryFinder {
    /// The kinds of file system a library can stand on. `autofs` is a share mounted on the first look, which this look is.
    const KINDS: [&'static str; 13] =
        ["nfs", "nfs4", "cifs", "smb3", "smbfs", "autofs", "ext4", "xfs", "btrfs", "zfs", "fuseblk", "exfat", "ntfs3"];
    /// How long a mount is looked at. A share that is gone can hang a look for minutes: its thread is left to it.
    const LOOK: Duration = Duration::from_secs(5);

    /// The folders in `table`, as `/proc/mounts` says them, that can hold a library. A space comes as `\\040`.
    fn mounted(table: &str) -> Vec<PathBuf> {
        let folders: BTreeSet<PathBuf> = table
            .lines()
            .filter_map(|line| {
                let mut words = line.split_whitespace();
                let folder = words.nth(1)?;
                let kind = words.next()?;
                Self::KINDS.contains(&kind).then(|| PathBuf::from(folder.replace("\\040", " ")))
            })
            .collect();
        folders.into_iter().collect()
    }

    /// Those of `folders` with the mark at their top, as far as `wait` allows.
    fn marked(folders: Vec<PathBuf>, wait: Duration) -> Vec<PathBuf> {
        let (told, heard) = channel();
        let count = folders.len();
        for folder in folders {
            let told = told.clone();
            let looked = std::thread::Builder::new().name("library-look".to_string()).spawn(move || {
                let has = folder.join(LibraryMark::NAME).is_file();
                // A send after the wait is over has nobody to tell.
                drop(told.send(has.then_some(folder)));
            });
            // No thread for a look is a folder not looked at: the next pass looks again.
            drop(looked);
        }
        drop(told);
        let mut found = Vec::new();
        for _ in 0..count {
            // The first silence ends the look: what has not answered by now is a mount that does not answer.
            let Ok(answer) = heard.recv_timeout(wait) else {
                break;
            };
            found.extend(answer);
        }
        found.sort();
        found
    }

    /// The one library in `table`; `None` for no library, and for two.
    pub fn one_in(table: &str, wait: Duration) -> Option<PathBuf> {
        let mut found = Self::marked(Self::mounted(table), wait);
        if found.len() == 1 { found.pop() } else { None }
    }

    /// The one library this machine mounts, by what it says of its mounts.
    pub fn here() -> Option<PathBuf> {
        Self::one_in(&std::fs::read_to_string("/proc/mounts").ok()?, Self::LOOK)
    }
}

/// The setting. It lives in `state.json`, as the cache's folder does: the board changes it over HTTP.
pub struct CacheOff {
    state: Arc<ScoutState>,
}

impl CacheOff {
    const OFF: &'static str = "cacheOff";
    const LIBRARY: &'static str = "libraryHere";
    const FROM_FOLDER: &'static str = "cacheOffFromFolder";

    /// The setting in this state.
    pub fn new(state: Arc<ScoutState>) -> Self {
        Self { state }
    }

    /// Where the view of the library stands on this machine: beside the scout's state.
    pub fn view_folder(&self) -> PathBuf {
        self.state.folder().join("library-view")
    }

    /// Whether this machine keeps no copies.
    pub fn is_off(&self) -> bool {
        self.state.get(Self::OFF) == Some(Value::Bool(true))
    }

    /// Whether a model is read from the folder where the library is mounted, and not through the controller. Only the operator's word makes it so: the default is the long way (the owner, 2026-11-02).
    pub fn from_folder(&self) -> bool {
        self.state.get(Self::FROM_FOLDER) == Some(Value::Bool(true))
    }

    /// Reads from the folder, or through the controller.
    pub fn choose(&self, from_folder: bool) {
        self.state.change(|doc| doc.insert(Self::FROM_FOLDER.to_string(), json!(from_folder)));
    }

    /// Where the library lies on this machine, when it was said.
    pub fn library(&self) -> Option<PathBuf> {
        self.state.get(Self::LIBRARY)?.as_str().filter(|path| path.starts_with('/')).map(PathBuf::from)
    }

    /// Keeps the switch, and the library when it is named.
    pub fn set(&self, off: bool, library: Option<&Path>) {
        self.state.change(|doc| {
            doc.insert(Self::OFF.to_string(), json!(off));
            if let Some(library) = library {
                doc.insert(Self::LIBRARY.to_string(), json!(library.display().to_string()));
            }
        });
    }

    /// What the scout says of it: the board offers the switch only to a scout that says this.
    pub fn facts(&self) -> Map<String, Value> {
        let mut out = Map::new();
        out.insert("off".to_string(), json!(self.is_off()));
        out.insert("through".to_string(), json!(self.is_off() && !self.from_folder()));
        if let Some(library) = self.library() {
            out.insert("library".to_string(), json!(library.display().to_string()));
        }
        out
    }

    /// The model read from the library on this machine: `raw` is its path inside the library, and the controller's `hint` says what it weighs. A file of another size is another
    /// file, and is not read.
    pub fn read_from_library(&self, raw: &str, hint: Option<&Value>) -> Result<PathBuf, AppError> {
        let refused = |words: String| AppError::with_status(words, 409);
        let Some(library) = self.library() else {
            return Err(refused(format!(
                "the model cache is off on this machine, and it was not told where the library lies here: {raw} cannot be read"
            )));
        };
        let inside = Path::new(raw);
        if inside.is_absolute() || inside.components().any(|part| matches!(part, std::path::Component::ParentDir)) {
            return Err(refused(format!("the model cache is off on this machine, and {raw} is no path inside its library")));
        }
        let said = hint.filter(|hint| hint.is_object());
        let asked = json!({
            "path": library.join(inside).display().to_string(),
            "size": said.and_then(|hint| hint.get("size")),
            "dir": said.map(|hint| Coerce::truthy(hint.get("dir"))),
        });
        ModelFetcher::in_place(raw, Some(&asked)).ok_or_else(|| {
            refused(format!(
                "the model cache is off on this machine, and its library {} has no {raw} of that size: copy it there, or turn the cache on",
                library.display()
            ))
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    fn setting(name: &str) -> (CacheOff, PathBuf) {
        let folder = std::env::temp_dir().join(format!("caravan-cache-off-{name}-{}", std::process::id()));
        drop(fs::remove_dir_all(&folder));
        fs::create_dir_all(folder.join("library/model/author")).unwrap();
        fs::write(folder.join("library/model/author/m.gguf"), b"GGUF model").unwrap();
        let state = Arc::new(ScoutState::load(&folder.join("state.json"), 0));
        (CacheOff::new(state), folder)
    }

    #[test]
    fn a_mount_table_is_read_for_the_folders_a_library_can_be() {
        let table = "proc /proc proc rw 0 0\n\
                     tmpfs /run tmpfs rw 0 0\n\
                     /dev/sda2 / ext4 rw 0 0\n\
                     /dev/loop1 /snap/core squashfs ro 0 0\n\
                     systemd-1 /mnt/lib autofs rw 0 0\n\
                     nas:/volume1/lib /mnt/lib nfs4 rw 0 0\n\
                     nas:/share /mnt/my\\040share cifs rw 0 0\n\
                     half-a-line\n";
        let folders = LibraryFinder::mounted(table);
        assert_eq!(
            folders,
            [PathBuf::from("/"), PathBuf::from("/mnt/lib"), PathBuf::from("/mnt/my share")],
            "one share under two kinds is one folder"
        );
    }

    #[test]
    fn one_mark_is_the_library_and_none_or_two_are_a_question() {
        let (_, folder) = setting("finder");
        let (first, second, plain) = (folder.join("first"), folder.join("second"), folder.join("plain"));
        for inner in [&first, &second, &plain] {
            fs::create_dir_all(inner).unwrap();
        }
        let table =
            format!("a {} nfs4 rw 0 0\nb {} nfs4 rw 0 0\nc {} nfs4 rw 0 0\n", first.display(), second.display(), plain.display());
        let wait = Duration::from_secs(5);
        assert_eq!(LibraryFinder::one_in(&table, wait), None, "no mark");
        fs::write(first.join(LibraryMark::NAME), "{}").unwrap();
        assert_eq!(LibraryFinder::one_in(&table, wait), Some(first.clone()));
        fs::write(second.join(LibraryMark::NAME), "{}").unwrap();
        assert_eq!(LibraryFinder::one_in(&table, wait), None, "two: which one is the operator's to say");
        fs::remove_file(second.join(LibraryMark::NAME)).unwrap();
        fs::create_dir(plain.join(LibraryMark::NAME)).unwrap();
        assert_eq!(LibraryFinder::one_in(&table, wait), Some(first.clone()), "a folder of that name is no mark");
        assert_eq!(LibraryFinder::one_in("", wait), None, "no mounts");
        fs::remove_dir_all(folder).unwrap();
    }

    #[test]
    fn it_is_on_until_turned_off_and_says_so() {
        let (off, folder) = setting("says");
        assert!(!off.is_off());
        assert_eq!(
            off.facts(),
            Map::from_iter([("off".to_string(), json!(false)), ("through".to_string(), json!(false))]),
            "on, and no library named"
        );
        off.set(true, None);
        assert_eq!(off.facts()["through"], json!(true), "off: through the controller, for nobody named a folder");
        off.choose(true);
        assert_eq!(off.facts()["through"], json!(false), "the operator's word: from the folder");
        off.choose(false);
        off.set(true, Some(&folder.join("library")));
        assert!(off.is_off());
        assert_eq!(off.facts()["library"], json!(folder.join("library").display().to_string()));
        off.set(false, None);
        assert!(!off.is_off());
        assert!(off.library().is_some(), "turned on again, the library is still known");
        fs::remove_dir_all(folder).unwrap();
    }

    #[test]
    fn a_model_is_read_where_the_library_lies_and_nowhere_else() {
        let (off, folder) = setting("reads");
        let library = folder.join("library");
        assert_eq!(off.read_from_library("model/author/m.gguf", None).unwrap_err().status, 409, "no library named");
        off.set(true, Some(&library));
        let right = json!({"path": "/data/models/model/author/m.gguf", "size": 10});
        assert_eq!(off.read_from_library("model/author/m.gguf", Some(&right)).unwrap(), library.join("model/author/m.gguf"));
        assert_eq!(
            off.read_from_library("model/author/m.gguf", None).unwrap(),
            library.join("model/author/m.gguf"),
            "no size said: nothing to differ from"
        );
        let other = json!({"path": "/data/models/model/author/m.gguf", "size": 11});
        assert!(
            off.read_from_library("model/author/m.gguf", Some(&other)).unwrap_err().message.contains("of that size"),
            "another file of that name is not read"
        );
        assert_eq!(off.read_from_library("model/none.gguf", None).unwrap_err().status, 409);
        for outside in ["../state.json", "/etc/passwd", "model/../../state.json"] {
            assert!(off.read_from_library(outside, None).unwrap_err().message.contains("no path inside"), "{outside}");
        }
        let dir = json!({"path": "/data/models/model/author", "dir": true});
        assert_eq!(
            off.read_from_library("model/author", Some(&dir)).unwrap(),
            library.join("model/author"),
            "a model that is a folder"
        );
        fs::remove_dir_all(folder).unwrap();
    }
}
