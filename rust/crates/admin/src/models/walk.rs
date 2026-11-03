//! A walk under a folder, as `Path.rglob` makes it: links to folders are not followed.

use std::path::{Path, PathBuf};

/// The walks.
pub struct Walker;

impl Walker {
    /// Every path under `root` whose name ends in `suffix`, in path order.
    pub fn ending_in(root: &Path, suffix: &str) -> Vec<PathBuf> {
        let mut out = Vec::new();
        Self::walk(root, suffix, &mut out);
        out.sort();
        out
    }

    fn walk(folder: &Path, suffix: &str, out: &mut Vec<PathBuf>) {
        for entry in std::fs::read_dir(folder).into_iter().flatten().flatten() {
            let path = entry.path();
            if entry.file_type().is_ok_and(|kind| kind.is_dir()) {
                Self::walk(&path, suffix, out);
            }
            if entry.file_name().to_string_lossy().ends_with(suffix) {
                out.push(path);
            }
        }
    }

    /// `rel` of a path under `root`, in the one spelling every store speaks.
    pub fn relative(path: &Path, root: &Path) -> Option<String> {
        path.strip_prefix(root).ok().map(|rel| rel.to_string_lossy().into_owned())
    }
}

/// `Path.resolve()`: the real place of what is there, and for what is not, the path with its `..` worked out.
pub struct Resolved;

impl Resolved {
    /// `rel` under `root`, resolved.
    pub fn under(root: &Path, rel: &str) -> PathBuf {
        let wanted = root.join(rel);
        std::fs::canonicalize(&wanted).unwrap_or_else(|_| {
            let mut out = PathBuf::new();
            for part in wanted.components() {
                match part {
                    std::path::Component::ParentDir => {
                        out.pop();
                    }
                    std::path::Component::CurDir => {}
                    other => out.push(other),
                }
            }
            out
        })
    }
}

/// `pathlib`'s reading of a relative path's text.
pub struct RelPath;

impl RelPath {
    /// `str(Path(rel).parent)`: "." for a name with no folder.
    pub fn parent(rel: &str) -> String {
        rel.rsplit_once('/').map_or_else(|| ".".to_string(), |(head, _)| head.to_string())
    }

    /// `str(Path(rel).parent / name)`.
    pub fn sibling(rel: &str, name: &str) -> String {
        let parent = Self::parent(rel);
        if parent == "." { name.to_string() } else { format!("{parent}/{name}") }
    }

    /// `Path(rel).name`.
    pub fn name(rel: &str) -> &str {
        rel.rsplit('/').next().unwrap_or(rel)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_walk_finds_by_the_name_as_written_in_path_order_and_a_link_is_not_gone_through() {
        let folder = crate::tests::TestFolder::new("walk-rules");
        let root = &folder.path;
        std::fs::create_dir_all(root.join("b/deep")).unwrap();
        std::fs::create_dir_all(root.join("a")).unwrap();
        std::fs::create_dir_all(root.join("dir.gguf")).unwrap();
        for file in
            ["b/deep/x.gguf", "a/y.gguf", "a/UPPER.GGUF", "a/z.gguf.part", "a/.gguf", "dir.gguf/inner.gguf", "a/notes.txt"]
        {
            std::fs::write(root.join(file), b"x").unwrap();
        }
        std::os::unix::fs::symlink("b", root.join("linked")).unwrap();
        std::os::unix::fs::symlink("a/y.gguf", root.join("file-link.gguf")).unwrap();
        std::os::unix::fs::symlink("nowhere", root.join("dead.gguf")).unwrap();
        let found: Vec<String> =
            Walker::ending_in(root, ".gguf").iter().map(|path| Walker::relative(path, root).unwrap()).collect();
        assert_eq!(
            found,
            ["a/.gguf", "a/y.gguf", "b/deep/x.gguf", "dead.gguf", "dir.gguf", "dir.gguf/inner.gguf", "file-link.gguf"],
            "a link to a folder is not walked; a link to a file and a dead one are found, and the reader looks at them; the upper case is another name"
        );
        assert_eq!(Walker::ending_in(&root.join("nothing-here"), ".gguf"), Vec::<std::path::PathBuf>::new());
    }

    #[test]
    fn a_path_left_out_of_a_walk_has_no_relative_name() {
        assert_eq!(Walker::relative(Path::new("/a/b/c"), Path::new("/a")), Some("b/c".to_string()));
        assert_eq!(Walker::relative(Path::new("/x/c"), Path::new("/a")), None);
    }

    #[test]
    fn a_path_is_resolved_with_its_steps_back_worked_out_where_it_is_not_there() {
        let folder = crate::tests::TestFolder::new("walk-resolved");
        std::fs::create_dir(folder.path.join("real")).unwrap();
        std::os::unix::fs::symlink("real", folder.path.join("link")).unwrap();
        assert_eq!(Resolved::under(&folder.path, "link"), folder.path.join("real"), "the real place of what is there");
        assert_eq!(Resolved::under(&folder.path, "a/../b/c"), folder.path.join("b/c"), "what is not there");
        assert_eq!(
            Resolved::under(&folder.path, "../x"),
            folder.path.parent().unwrap().join("x"),
            "and a step out stays a step out, for the caller to refuse"
        );
    }

    #[test]
    fn a_relative_path_reads_as_pathlib_has_it() {
        assert_eq!(RelPath::parent("a.gguf"), ".");
        assert_eq!(RelPath::parent("a/b/c.gguf"), "a/b");
        assert_eq!(RelPath::sibling("a", "default"), "default");
        assert_eq!(RelPath::sibling("a/b", "default"), "a/default");
        assert_eq!(RelPath::name("a/b.gguf"), "b.gguf");
    }
}
