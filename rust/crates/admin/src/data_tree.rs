//! The single-volume layout's folders, made before any writer needs them, or a stop that says why they cannot be.

use os::Account;
use std::path::{Path, PathBuf};

/// The data folder's subfolders, and whether this process can write them.
pub struct DataTree {
    root: PathBuf,
}

impl DataTree {
    const SUBDIRS: [&'static str; 6] = ["state", "config", "logs", "secrets", "models", "server-backups"];
    const PROBE: &'static str = ".write-probe";

    /// The tree at `root`.
    pub fn new(root: &Path) -> Self {
        Self { root: root.to_path_buf() }
    }

    fn write_probe(folder: &Path) -> std::io::Result<()> {
        let path = folder.join(format!("{}.{}", Self::PROBE, std::process::id()));
        std::fs::write(&path, b"")?;
        std::fs::remove_file(&path)
    }

    /// Why this process cannot keep its data here; empty once the tree is made.
    pub fn problem(&self) -> String {
        let made = Self::SUBDIRS
            .iter()
            .try_for_each(|sub| std::fs::create_dir_all(self.root.join(sub)))
            .and_then(|()| Self::write_probe(&self.root.join("state")));
        match made {
            Ok(()) => String::new(),
            Err(error) if error.kind() == std::io::ErrorKind::PermissionDenied => format!(
                "cannot write the data folder {root} ({error}) as uid {uid}. The folder mounted there must be writable by that user. On Synology a folder with an ACL (ls -ld shows '+') refuses a container even when the user owns it: run 'chmod 755' on the folder on the host",
                root = self.root.to_string_lossy(),
                uid = Account::uid(),
            ),
            Err(error) => format!("cannot make the data folder {} ({error})", self.root.to_string_lossy()),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_tree_is_made_where_it_can_be() {
        let root = std::env::temp_dir().join(format!("caravan-tree-{}", std::process::id()));
        assert_eq!(DataTree::new(&root).problem(), "");
        assert!(root.join("server-backups").is_dir());
        std::fs::remove_dir_all(&root).unwrap();
        assert!(!DataTree::new(Path::new("/proc/nowhere/at-all")).problem().is_empty());
    }
}
