//! Which folders are models in their own right. A model is not always one file: a whisper cache is a directory of blobs with a tree of links over it; a checkpoint is a directory of shards. The manager, the mover and the library walk all have to agree on where such a folder starts, otherwise the page offers to move half of one. Nothing here opens a file.

use std::collections::BTreeSet;
use std::os::unix::fs::MetadataExt;
use std::path::Path;

/// The rule.
pub struct ModelArtifacts;

impl ModelArtifacts {
    /// Names no walk here looks into: dotfiles, Synology's #recycle and @eaDir, and macOS's "._name" shadows on a share.
    pub fn hidden(name: &str) -> bool {
        matches!(name.chars().next(), Some('.' | '#' | '@'))
    }

    /// The kind of model a directory is by itself: "whisper", "translate", "safetensors", or "" for an ordinary folder. A HF cache under whisper/ or translate/ is one model, its runner's.
    pub fn kind(rel: &str, names: &[String]) -> &'static str {
        let parts: Vec<&str> = rel.split('/').filter(|part| !part.is_empty() && *part != ".").collect();
        // The store's own root is a store, not a model: a stray .safetensors lying at the top would otherwise make the whole library one giant item.
        let Some(first) = parts.first() else {
            return "";
        };
        if parts.len() == 2 && parts.get(1).is_some_and(|second| second.starts_with("models--")) {
            match *first {
                "whisper" => return "whisper",
                "translate" => return "translate",
                _ => {}
            }
        }
        if names.iter().any(|name| name.ends_with(".safetensors")) { "safetensors" } else { "" }
    }

    fn listed(folder: &Path) -> (Vec<String>, Vec<String>) {
        let (mut folders, mut files) = (Vec::new(), Vec::new());
        for entry in std::fs::read_dir(folder).into_iter().flatten().flatten() {
            let name = entry.file_name().to_string_lossy().into_owned();
            if entry.file_type().is_ok_and(|kind| kind.is_dir()) {
                folders.push(name);
            } else {
                files.push(name);
            }
        }
        (folders, files)
    }

    /// Every model folder under `root`, outermost first, as (relpath, kind). Outermost only: a whisper cache holds snapshot directories full of .safetensors links, and naming them too would put a part of a model beside the model.
    pub fn dirs(root: &Path) -> Vec<(String, &'static str)> {
        let mut found = Vec::new();
        Self::walk_dirs(root, "", &mut found);
        found
    }

    fn walk_dirs(folder: &Path, rel: &str, found: &mut Vec<(String, &'static str)>) {
        let (mut folders, files) = Self::listed(folder);
        let shown: Vec<String> = files.into_iter().filter(|name| !Self::hidden(name)).collect();
        let kind = Self::kind(rel, &shown);
        if !kind.is_empty() {
            found.push((rel.to_string(), kind));
            return;
        }
        folders.retain(|name| !Self::hidden(name));
        folders.sort();
        for name in folders {
            let inner = if rel.is_empty() { name.clone() } else { format!("{rel}/{name}") };
            Self::walk_dirs(&folder.join(&name), &inner, found);
        }
    }

    /// What a folder weighs and when it last changed, as a copy of it would weigh, so links count for nothing: a whisper cache keeps every blob twice, once as a link under snapshots/.
    pub fn folder_weight(root: &Path) -> (i64, i64) {
        let (mut size, mut mtime) = (0, 0);
        Self::weigh(root, &mut size, &mut mtime);
        (size, mtime)
    }

    fn weigh(folder: &Path, size: &mut i64, mtime: &mut i64) {
        let (folders, files) = Self::listed(folder);
        for name in files.iter().filter(|name| !Self::hidden(name)) {
            let Ok(meta) = std::fs::symlink_metadata(folder.join(name)) else {
                continue;
            };
            if meta.file_type().is_file() {
                *size += meta.size() as i64;
                *mtime = (*mtime).max(meta.mtime());
            }
        }
        for name in folders.iter().filter(|name| !Self::hidden(name)) {
            Self::weigh(&folder.join(name), size, mtime);
        }
    }

    /// The set of a walk's folders, for a caller that asks "is this inside one".
    pub fn inside(rel: &str, dirs: &BTreeSet<String>) -> bool {
        dirs.iter().any(|dir| rel == dir || rel.strip_prefix(dir.as_str()).is_some_and(|rest| rest.starts_with('/')))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_cache_is_one_model_and_a_root_is_none() {
        let names = |list: &[&str]| list.iter().map(|name| (*name).to_string()).collect::<Vec<_>>();
        assert_eq!(ModelArtifacts::kind("", &names(&["a.safetensors"])), "");
        assert_eq!(ModelArtifacts::kind("whisper/models--a--b", &names(&[])), "whisper");
        assert_eq!(ModelArtifacts::kind("translate/models--a--b", &names(&[])), "translate");
        assert_eq!(ModelArtifacts::kind("m/a/b", &names(&["x.safetensors"])), "safetensors");
        assert_eq!(ModelArtifacts::kind("m/a/b", &names(&["x.gguf"])), "");
    }

    #[test]
    fn only_the_outermost_folder_is_named_and_links_weigh_nothing() {
        let root = std::env::temp_dir().join(format!("artifacts-{}", std::process::id()));
        let snap = root.join("whisper/models--a--b/snapshots/s");
        std::fs::create_dir_all(&snap).unwrap();
        std::fs::write(root.join("whisper/models--a--b/blob"), b"12345").unwrap();
        std::os::unix::fs::symlink(root.join("whisper/models--a--b/blob"), snap.join("model.safetensors")).unwrap();
        std::fs::create_dir_all(root.join(".hidden/m")).unwrap();
        std::fs::write(root.join(".hidden/m/x.safetensors"), b"1").unwrap();
        assert_eq!(ModelArtifacts::dirs(&root), [("whisper/models--a--b".to_string(), "whisper")]);
        assert_eq!(ModelArtifacts::folder_weight(&root.join("whisper")).0, 5);
        std::fs::remove_dir_all(&root).unwrap();
    }
}
