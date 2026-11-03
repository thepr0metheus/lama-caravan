//! One file of a download: what the hub calls it and where it lands.

use rules::Coerce;
use serde_json::Value;

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

    /// A name that is one name: it cannot leave the folder it lands in.
    pub fn is_plain_name(name: &str) -> bool {
        !name.is_empty() && name != "." && name != ".." && !name.contains('/')
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
}
