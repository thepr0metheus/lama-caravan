//! One file of a download: what the hub calls it and where it lands.

use rules::Coerce;
use serde_json::{Value, json};

/// One file to fetch.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DownloadFile {
    /// Its path in the repository.
    pub path: String,
    /// The name it lands under.
    pub name: String,
    /// The folder it lands in, under the models folder.
    pub dest_dir: String,
    /// Its size, as the hub said it.
    pub size: i64,
}

impl DownloadFile {
    /// The file as a request's body says it.
    pub fn of(raw: &Value) -> Self {
        // absent-ok: `f.get("size", 0)`: a size not said is no promise; the answer's own length says it.
        Self {
            path: Coerce::text(raw.get("path")),
            name: Coerce::text(raw.get("name")),
            dest_dir: Coerce::text(raw.get("destDir")),
            size: Coerce::whole(raw.get("size")),
        }
    }

    /// Where this file lands, relative to the models folder, in one spelling: `./a//b/` and `a/b` are one folder, and a running job's partial is
    /// told by this text.
    pub fn dest_path(&self) -> String {
        let folder: Vec<&str> = self.dest_dir.split('/').filter(|part| !part.is_empty() && *part != ".").collect();
        if folder.is_empty() { self.name.clone() } else { format!("{}/{}", folder.join("/"), self.name) }
    }

    /// The file as `of` reads it back: a partial's manifest names the files of its job after it so.
    pub fn said(&self) -> Value {
        json!({"path": self.path, "name": self.name, "destDir": self.dest_dir, "size": self.size})
    }

    /// A name that is one name: it cannot leave the folder it lands in.
    pub fn is_plain_name(name: &str) -> bool {
        !name.is_empty() && name != "." && name != ".." && !name.contains('/')
    }

    /// A folder under the models folder: not from the root, and no step out of it.
    pub fn folder_stays_inside(dest_dir: &str) -> bool {
        !dest_dir.starts_with('/') && !dest_dir.split('/').any(|part| part == "..")
    }

    /// The file lands under the models folder, by a name that is one name.
    pub fn lands_inside(&self) -> bool {
        Self::is_plain_name(&self.name) && Self::folder_stays_inside(&self.dest_dir)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn a_file_lands_under_its_folder() {
        let file = DownloadFile::of(&json!({"path": "p", "name": "n", "destDir": "/a/b/", "size": 3}));
        assert_eq!(file.dest_path(), "a/b/n");
        assert_eq!(DownloadFile::of(&json!({"name": "n"})).dest_path(), "n");
        for spelled in ["./f/acme/Q4", "f/acme//Q4", "f/./acme/Q4", "/f/acme/Q4/", "f/acme/Q4"] {
            assert_eq!(DownloadFile::of(&json!({"name": "n", "destDir": spelled})).dest_path(), "f/acme/Q4/n", "{spelled}");
        }
        assert_eq!(DownloadFile::of(&json!({"name": "n", "destDir": "."})).dest_path(), "n");
    }

    #[test]
    fn a_name_is_one_name() {
        for good in ["x.gguf", "a..b", ".hidden"] {
            assert!(DownloadFile::is_plain_name(good), "{good}");
        }
        for bad in ["", ".", "..", "../x", "a/b", "/x"] {
            assert!(!DownloadFile::is_plain_name(bad), "{bad}");
        }
    }

    #[test]
    fn a_folder_stays_under_the_models_folder_and_a_file_lands_there_by_one_name() {
        for inside in ["", ".", "m", "f/acme/Q4", "./f//acme/", "a..b", "f/..x"] {
            assert!(DownloadFile::folder_stays_inside(inside), "{inside}");
        }
        for outside in ["/m", "..", "../m", "m/..", "f/../../x", "/"] {
            assert!(!DownloadFile::folder_stays_inside(outside), "{outside}");
        }
        let at = |name: &str, dest: &str| DownloadFile::of(&json!({"path": "p", "name": name, "destDir": dest})).lands_inside();
        assert!(at("x.gguf", "f/acme/Q4"));
        assert!(!at("../x.gguf", "f") && !at("x.gguf", "/etc") && !at("", "f") && !at("x.gguf", "f/.."));
    }

    #[test]
    fn a_file_said_is_read_back_as_itself() {
        let file =
            DownloadFile { path: "q/x.gguf".to_string(), name: "x.gguf".to_string(), dest_dir: "f/acme/Q4".to_string(), size: 7 };
        assert_eq!(DownloadFile::of(&file.said()), file);
    }
}
