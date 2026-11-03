//! A file replaced whole: a reader sees the old one or the new one, never half.

use std::fs;
use std::io::{self, Write};
use std::os::unix::fs::{OpenOptionsExt, PermissionsExt};
use std::path::{Path, PathBuf};

/// A write through a temporary file beside the target, then a rename.
pub struct AtomicFile;

impl AtomicFile {
    /// Replaces `path` with `body`. A failed write leaves the old file and no temporary one.
    pub fn write(path: &Path, body: &[u8]) -> io::Result<()> {
        Self::written_with(path, body, 0o644)
    }

    /// Replaces `path` with `body`, readable by its owner alone from the first byte it holds under its own name.
    pub fn write_private(path: &Path, body: &[u8]) -> io::Result<()> {
        Self::written_with(path, body, 0o600)
    }

    /// An existing file that others may read or write made its owner's only: at start, so that a file written before the rule is not left open until
    /// its next save. A missing file is not made; one that cannot be changed stays as it is, and whoever reads it reads it as before.
    pub fn narrow(path: &Path) {
        let Ok(meta) = fs::metadata(path) else {
            return;
        };
        if meta.permissions().mode() & 0o077 != 0 {
            drop(fs::set_permissions(path, fs::Permissions::from_mode(0o600)));
        }
    }

    fn written_with(path: &Path, body: &[u8], mode: u32) -> io::Result<()> {
        if let Some(folder) = path.parent() {
            fs::create_dir_all(folder)?;
        }
        let temporary = Self::temporary(path);
        let written = Self::fresh(&temporary, body, mode).and_then(|()| fs::rename(&temporary, path));
        if written.is_err() {
            // The write's own failure is what the caller hears; a temporary file that was never made cannot be removed.
            drop(fs::remove_file(&temporary));
        }
        written
    }

    fn fresh(path: &Path, body: &[u8], mode: u32) -> io::Result<()> {
        let mut file = fs::OpenOptions::new().write(true).create(true).truncate(true).mode(mode).open(path)?;
        file.write_all(body)
    }

    fn temporary(path: &Path) -> PathBuf {
        let name = path.file_name().map_or_else(|| "file".into(), |name| name.to_string_lossy().into_owned());
        path.with_file_name(format!("{name}.{}.tmp", std::process::id()))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn replaces_the_file_and_leaves_nothing_beside_it() {
        let folder = std::env::temp_dir().join(format!("caravan-atomic-{}", std::process::id()));
        let path = folder.join("deep").join("state.json");
        AtomicFile::write(&path, b"one").unwrap();
        AtomicFile::write(&path, b"two").unwrap();
        assert_eq!(fs::read(&path).unwrap(), b"two");
        assert_eq!(fs::read_dir(path.parent().unwrap()).unwrap().count(), 1);
        fs::remove_dir_all(&folder).unwrap();
    }

    #[test]
    fn a_private_file_is_its_owner_s_alone() {
        use std::os::unix::fs::PermissionsExt;
        let folder = std::env::temp_dir().join(format!("caravan-atomic-private-{}", std::process::id()));
        let path = folder.join("secrets.json");
        AtomicFile::write_private(&path, b"one").unwrap();
        assert_eq!(fs::metadata(&path).unwrap().permissions().mode() & 0o777, 0o600);
        assert_eq!(fs::read(&path).unwrap(), b"one");
        fs::remove_dir_all(&folder).unwrap();
    }
}
