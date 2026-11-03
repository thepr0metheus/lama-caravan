//! Where a model file lives right now. A snapshot of the libraries' files, taken once and asked many times.

use rules::Coerce;
use serde_json::{Map, Value, json};
use std::collections::BTreeMap;
use std::path::Path;

/// A library, as an answer names it.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LibraryStore {
    /// Its id.
    pub id: String,
    /// Its name.
    pub name: String,
    /// Its folder as this host reads it.
    pub root: String,
}

/// Where a file is.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Place {
    /// On this host's disk.
    Local,
    /// In a library.
    Library,
    /// Nowhere known.
    Missing,
}

impl Place {
    fn word(self) -> &'static str {
        match self {
            Self::Local => "local",
            Self::Library => "library",
            Self::Missing => "missing",
        }
    }
}

/// One file's answer.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Located {
    /// Its path from the models folder.
    pub rel: String,
    /// Where it is.
    pub place: Place,
    /// Where this host reads it.
    pub path: String,
    /// The library, when it is in one.
    pub store: Option<LibraryStore>,
    /// Its size as the library knows it.
    pub size: i64,
}

impl Located {
    /// A file on this host's disk.
    pub fn local(rel: &str, path: String) -> Self {
        Self { rel: rel.to_string(), place: Place::Local, path, store: None, size: 0 }
    }

    /// Whether it is in a library.
    pub fn in_library(&self) -> bool {
        self.place == Place::Library
    }

    /// The answer as the board reads it.
    pub fn to_json(&self) -> Value {
        let mut doc = json!({"rel": self.rel, "where": self.place.word(), "path": self.path});
        if let (Some(store), Value::Object(fields)) = (&self.store, &mut doc) {
            fields.insert("store".to_string(), json!({"id": store.id, "name": store.name}));
        }
        doc
    }

    /// This file as offered to a scout; none when there is nothing to offer.
    pub fn hint(&self) -> Option<Value> {
        if self.path.is_empty() {
            return None;
        }
        if self.in_library() {
            let name = self.store.as_ref().map_or("", |store| store.name.as_str());
            let mut doc = json!({"path": self.path, "library": name});
            if let (true, Value::Object(fields)) = (self.size != 0, &mut doc) {
                fields.insert("size".to_string(), json!(self.size));
            }
            return Some(doc);
        }
        let path = Path::new(&self.path);
        if path.is_dir() {
            return Some(json!({"path": self.path, "dir": true}));
        }
        if self.place == Place::Local && path.is_file() {
            return Some(json!({"path": self.path, "size": std::fs::metadata(path).ok()?.len()}));
        }
        None
    }
}

/// `~` and `$HOME` of a cell's models directory, as a real path on this host.
pub struct HomePath;

impl HomePath {
    /// The path.
    pub fn of(value: &str, home: &str) -> String {
        let tail = value.strip_prefix("$HOME").or_else(|| value.strip_prefix("${HOME}")).or_else(|| value.strip_prefix('~'));
        match tail {
            Some(tail) if tail.is_empty() || tail.starts_with('/') => format!("{}{tail}", home.trim_end_matches('/')),
            _ => value.to_string(),
        }
    }
}

/// The parts of a split GGUF: `<stem>-00001-of-00003.gguf`.
pub struct SplitParts;

/// A part of a split file.
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
pub struct SplitPart {
    /// What groups it with its sisters: its folder, its stem and how many there are.
    pub group: (String, String, String),
    /// Its number.
    pub index: i64,
    /// How many there are.
    pub total: i64,
}

impl SplitParts {
    /// (stem, index, total as written) of a file's name; `<stem>-\d{5}-of-\d{5}\.gguf`, any case.
    fn name_parts(name: &str) -> Option<(&str, &str, &str)> {
        let lower = name.to_ascii_lowercase();
        if !lower.ends_with(".gguf") || name.len() < 5 + 16 {
            return None;
        }
        let bare = name.get(..name.len() - 5)?;
        let total = bare.get(bare.len().checked_sub(5)?..)?;
        let middle = bare.get(bare.len().checked_sub(9)?..bare.len() - 5)?;
        let index = bare.get(bare.len().checked_sub(14)?..bare.len() - 9)?;
        let dash = bare.get(bare.len().checked_sub(15)?..bare.len() - 14)?;
        let stem = bare.get(..bare.len() - 15)?;
        let digits = |word: &str| word.chars().all(|letter| letter.is_ascii_digit());
        (dash == "-" && middle.eq_ignore_ascii_case("-of-") && digits(index) && digits(total) && !stem.is_empty())
            .then_some((stem, index, total))
    }

    /// The name a part of a split GGUF has before its `-00001-of-00003.gguf`; none for a whole file.
    pub fn stem_of(name: &str) -> Option<&str> {
        Self::name_parts(name).map(|(stem, _, _)| stem)
    }

    /// What part of a split GGUF a path is; none for a whole file.
    pub fn of(rel: &str) -> Option<SplitPart> {
        let (folder, name) = rel.rsplit_once('/').unwrap_or(("", rel));
        let (stem, index, total) = Self::name_parts(name)?;
        Some(SplitPart {
            group: (folder.to_string(), stem.to_string(), total.to_string()),
            index: index.parse().ok()?,
            total: total.parse().ok()?,
        })
    }

    /// Whether `other` is part of the file `rel` names: its sisters for a part, itself for a whole file.
    fn same_file(rel: &str, other: &str) -> bool {
        let Some(mine) = Self::of(rel) else {
            return other == rel;
        };
        let (folder, name) = other.rsplit_once('/').unwrap_or(("", other));
        Self::name_parts(name).is_some_and(|(stem, _, total)| {
            folder.eq_ignore_ascii_case(&mine.group.0) && stem.eq_ignore_ascii_case(&mine.group.1) && total == mine.group.2
        })
    }
}

/// A file of a library, as a look at the library saw it.
pub type LibraryFile = Map<String, Value>;

/// A snapshot of the libraries' files.
#[derive(Default)]
pub struct Locations {
    index: BTreeMap<String, (LibraryStore, LibraryFile)>,
    copies: Vec<(String, LibraryStore, LibraryFile)>,
    roots: Vec<(String, Option<LibraryStore>)>,
    home: String,
}

impl Locations {
    const USABLE: [&'static str; 3] = ["ok", "low-space", "read-only"];

    /// The snapshot of these libraries, each `{id, name, path, state, files}`.
    pub fn new(libraries: &[Value], home: &str) -> Self {
        let mut this = Self { home: home.to_string(), ..Self::default() };
        for library in libraries {
            if !Coerce::truthy(library.get("path")) {
                continue;
            }
            let id = Coerce::text(library.get("id"));
            let name = if Coerce::truthy(library.get("name")) { Coerce::text(library.get("name")) } else { id.clone() };
            let store = LibraryStore { id, name, root: Coerce::text(library.get("path")) };
            let usable = library.get("state").and_then(Value::as_str).is_some_and(|state| Self::USABLE.contains(&state));
            this.roots.push((format!("{}/", store.root.trim_end_matches('/')), usable.then(|| store.clone())));
            if !usable {
                continue;
            }
            for file in library.get("files").and_then(Value::as_array).into_iter().flatten() {
                let (rel, row) = (Coerce::text(file.get("path")), Coerce::fields(file));
                this.index.entry(rel.clone()).or_insert_with(|| (store.clone(), row.clone()));
                this.copies.push((rel, store.clone(), row));
            }
        }
        this
    }

    fn size_of(file: &LibraryFile) -> i64 {
        // absent-ok: `f.get("size") or 0`: a file whose size the look did not get adds nothing to a sum.
        Coerce::whole(file.get("size"))
    }

    /// Where a file is: the local disk first, then a library.
    pub fn locate(&self, rel: &str, local_root: &str) -> Option<Located> {
        let rel = Coerce::strip(rel).trim_start_matches('/');
        if rel.is_empty() {
            return None;
        }
        let local = format!("{}/{rel}", HomePath::of(local_root, &self.home).trim_end_matches('/'));
        if Path::new(&local).is_file() {
            return Some(Located::local(rel, local));
        }
        if let Some((store, file)) = self.index.get(rel) {
            return Some(Located {
                rel: rel.to_string(),
                place: Place::Library,
                path: format!("{}/{rel}", store.root.trim_end_matches('/')),
                store: Some(store.clone()),
                size: Self::size_of(file),
            });
        }
        Some(Located { rel: rel.to_string(), place: Place::Missing, path: local, store: None, size: 0 })
    }

    /// (rel, store, file) for every file a usable library holds, by path.
    pub fn library_entries(&self) -> impl Iterator<Item = (&String, &LibraryStore, &LibraryFile)> {
        self.index.iter().map(|(rel, (store, file))| (rel, store, file))
    }

    /// (rel, store, file) for every copy in every usable library.
    pub fn library_copies(&self) -> Vec<&(String, LibraryStore, LibraryFile)> {
        let mut copies: Vec<&(String, LibraryStore, LibraryFile)> = self.copies.iter().collect();
        copies.sort_by(|left, right| (&left.0, &left.1.name).cmp(&(&right.0, &right.1.name)));
        copies
    }

    /// What the library holds for this file, all its parts together.
    pub fn library_size(&self, rel: &str) -> i64 {
        self.index.iter().filter(|(other, _)| SplitParts::same_file(rel, other)).map(|(_, (_, file))| Self::size_of(file)).sum()
    }

    /// What a library holds at `path`, a path as this host reads it, by the library's last look: `None` when no library's folder holds the path, `Some((None, 0))` when the library is not usable.
    pub fn library_file(&self, path: &str) -> Option<(Option<&LibraryStore>, i64)> {
        for (root, store) in &self.roots {
            let Some(rel) = path.strip_prefix(root.as_str()) else {
                continue;
            };
            let Some(store) = store else {
                return Some((None, 0));
            };
            let size = self
                .copies
                .iter()
                .filter(|(other, held, _)| held.id == store.id && SplitParts::same_file(rel, other))
                .map(|(_, _, file)| Self::size_of(file))
                .sum();
            return Some((Some(store), size));
        }
        None
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn locations() -> Locations {
        Locations::new(
            &[
                json!({"id": "n", "name": "NAS", "path": "/lib", "state": "ok", "files": [{"path": "a/b-00001-of-00002.gguf", "size": 5}, {"path": "a/b-00002-of-00002.gguf", "size": 7}, {"path": "c.gguf", "size": 3}]}),
                json!({"id": "off", "path": "/off", "state": "unmounted", "files": [{"path": "x.gguf", "size": 9}]}),
            ],
            "/home/me",
        )
    }

    #[test]
    fn a_file_is_found_where_it_is() {
        let found = locations();
        let at = found.locate("c.gguf", "/nowhere").unwrap();
        assert!(at.in_library());
        assert_eq!(at.path, "/lib/c.gguf");
        assert_eq!(
            at.to_json(),
            json!({"rel": "c.gguf", "where": "library", "path": "/lib/c.gguf", "store": {"id": "n", "name": "NAS"}})
        );
        assert_eq!(at.hint(), Some(json!({"path": "/lib/c.gguf", "library": "NAS", "size": 3})));
        let gone = found.locate("x.gguf", "$HOME/m").unwrap();
        assert_eq!((gone.place, gone.path.as_str()), (Place::Missing, "/home/me/m/x.gguf"));
        assert_eq!(gone.hint(), None);
        assert!(found.locate(" ", "/m").is_none());
    }

    #[test]
    fn the_parts_of_a_file_count_as_one() {
        let found = locations();
        assert_eq!(found.library_size("a/b-00001-of-00002.gguf"), 12);
        assert_eq!(found.library_size("c.gguf"), 3);
        assert_eq!(
            found.library_file("/lib/a/b-00002-of-00002.gguf").map(|(store, size)| (store.map(|store| store.id.clone()), size)),
            Some((Some("n".to_string()), 12))
        );
        assert_eq!(found.library_file("/off/x.gguf"), Some((None, 0)));
        assert_eq!(found.library_file("/other/x.gguf"), None);
    }

    #[test]
    fn the_tail_of_a_part_is_read_exactly_and_the_quant_is_what_lies_before_it() {
        for (name, stem) in [
            ("X-Q8_0-00001-of-00006.gguf", Some("X-Q8_0")),
            ("a-00001-of-00002.gguf", Some("a")),
            ("m-Q5_K_S-00001-of-00002.GGUF", Some("m-Q5_K_S")),
            ("m-00001-OF-00002.gguf", Some("m")),
            ("Ünï-00001-of-00002.gguf", Some("Ünï")),
            ("-00001-of-00002.gguf", None),
            ("x-1-of-2.gguf", None),
            ("x-0001-of-00002.gguf", None),
            ("x-00001-of-0002.gguf", None),
            ("x-00001-to-00002.gguf", None),
            ("x_00001-of-00002.gguf", None),
            ("x-0000a-of-00002.gguf", None),
            ("x-00001-of-00002.bin", None),
            ("x-Q8_0.gguf", None),
            ("", None),
            ("яяяяяяяяяяяяя.gguf", None),
        ] {
            assert_eq!(SplitParts::stem_of(name), stem, "{name:?}");
        }
    }

    #[test]
    fn a_part_groups_with_its_sisters_by_its_folder_its_stem_and_how_many_there_are() {
        let found = Locations::new(
            &[json!({"id": "n", "path": "/lib", "state": "ok", "files": [
                {"path": "m/x-00001-of-00002.gguf", "size": 1},
                {"path": "m/x-00002-of-00002.gguf", "size": 2},
                {"path": "m/x-00001-of-00003.gguf", "size": 4},
                {"path": "other/x-00002-of-00002.gguf", "size": 8},
                {"path": "m/y-00002-of-00002.gguf", "size": 16},
                {"path": "M/X-00002-OF-00002.GGUF", "size": 32}
            ]})],
            "/h",
        );
        assert_eq!(
            found.library_size("m/x-00001-of-00002.gguf"),
            1 + 2 + 32,
            "the case does not part them; another count, folder or stem does"
        );
        assert_eq!(found.library_size("m/none.gguf"), 0);
    }

    #[test]
    fn only_a_library_that_is_there_holds_anything_and_this_disk_goes_first() {
        let folder = crate::tests::TestFolder::new("locator-usable");
        std::fs::write(folder.path.join("c.gguf"), b"x").unwrap();
        for (state, usable) in [
            ("ok", true),
            ("low-space", true),
            ("read-only", true),
            ("not-mounted", false),
            ("foreign", false),
            ("unknown", false),
            ("missing", false),
        ] {
            let found = Locations::new(
                &[json!({"id": "n", "path": "/lib", "state": state, "files": [{"path": "c.gguf", "size": 3}]})],
                "/h",
            );
            assert_eq!(found.library_copies().is_empty(), !usable, "{state}");
            assert_eq!(found.locate("c.gguf", "/nowhere").unwrap().in_library(), usable, "{state}");
            assert_eq!(
                found.locate("c.gguf", &folder.path.to_string_lossy()).unwrap().place,
                Place::Local,
                "{state}: a file here is read here"
            );
        }
    }

    #[test]
    fn a_part_says_which_it_is() {
        let part = SplitParts::of("a/B-00002-OF-00003.GGUF").unwrap();
        assert_eq!((part.index, part.total, part.group.1.as_str()), (2, 3, "B"));
        assert_eq!(SplitParts::of("a/b.gguf"), None);
        assert_eq!(SplitParts::of("a/-00002-of-00003.gguf"), None);
    }

    #[test]
    fn a_home_is_this_hosts() {
        assert_eq!(HomePath::of("$HOME/m", "/h"), "/h/m");
        assert_eq!(HomePath::of("${HOME}/m", "/h/"), "/h/m");
        assert_eq!(HomePath::of("~", "/h"), "/h");
        assert_eq!(HomePath::of("/m", "/h"), "/m");
    }
}
