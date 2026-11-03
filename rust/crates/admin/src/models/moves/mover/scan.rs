//! What a move finds to do: the files of an item, walked and stamped, and the headers that go with them.

use super::*;

impl<'app> Mover<'app> {
    /// Reads the folder once; `false` when the item closed.
    pub(super) fn scan(&self, item: usize, folder: &str) -> Result<bool, Stop> {
        let (source_root, _) = self.roots();
        let place = source_root.join(folder);
        let found = loop {
            let looked = self.stores_here().and_then(|()| Self::walk_all(&place));
            match looked {
                Ok(rows) => break rows,
                Err(error) if error.kind() == io::ErrorKind::NotFound => {
                    self.close(item, "skipped", "local-gone", "");
                    return Ok(false);
                }
                Err(error) => {
                    if !self.trouble(item, &error)? {
                        return Ok(false);
                    }
                }
            }
        };
        let (mut files, mut links, mut dirs) = (Vec::new(), Vec::new(), Vec::new());
        for (kind, rel, size, target) in found {
            let path = format!("{folder}/{rel}");
            let full = place.join(&rel);
            match kind {
                "file" => {
                    let stamp = Self::stamp(&full).map_err(Stop::Failed)?;
                    files.push(MoveFile::new(&path, size, stamp));
                }
                "link" => {
                    let parent = full.parent().unwrap_or(&place);
                    if target.starts_with('/') || !Self::inside(&place, &parent.join(&target)) {
                        self.close(item, "skipped", "link-out", &format!("{path} → {target}"));
                        return Ok(false);
                    }
                    links.push((path, target));
                }
                "dir" => dirs.push(path),
                _ => {
                    self.close(item, "skipped", "folder-odd", &path);
                    return Ok(false);
                }
            }
        }
        self.edit(|job| {
            if let Some(row) = job.items.get_mut(item) {
                let weight: i64 = files.iter().map(|file| file.size).sum();
                row.files = files;
                row.links = links;
                row.dirs = dirs;
                row.scanned = true;
                if weight != 0 {
                    row.size = weight;
                }
            }
        });
        Ok(true)
    }

    /// Everything inside a folder, once: (kind, path from it, size, a link's target).
    pub(super) fn walk_all(root: &Path) -> io::Result<Vec<(&'static str, String, i64, String)>> {
        std::fs::metadata(root)?;
        let mut out = Vec::new();
        Self::walk_under(root, "", &mut out)?;
        Ok(out)
    }

    pub(super) fn walk_under(folder: &Path, rel: &str, out: &mut Vec<(&'static str, String, i64, String)>) -> io::Result<()> {
        let (mut folders, mut names) = (Vec::new(), Vec::new());
        for entry in std::fs::read_dir(folder)? {
            let entry = entry?;
            let name = entry.file_name().to_string_lossy().into_owned();
            if entry.file_type()?.is_dir() {
                folders.push(name);
            } else {
                names.push(name);
            }
        }
        folders.sort();
        names.sort();
        let join = |name: &str| if rel.is_empty() { name.to_string() } else { format!("{rel}/{name}") };
        for name in folders.iter().chain(&names) {
            let full = folder.join(name);
            let meta = std::fs::symlink_metadata(&full)?;
            let row = if meta.file_type().is_symlink() {
                ("link", join(name), 0, std::fs::read_link(&full)?.to_string_lossy().into_owned())
            } else if meta.is_dir() {
                ("dir", join(name), 0, String::new())
            } else if meta.is_file() {
                ("file", join(name), meta.size() as i64, String::new())
            } else {
                ("other", join(name), 0, String::new())
            };
            out.push(row);
        }
        for name in folders {
            Self::walk_under(&folder.join(&name), &join(&name), out)?;
        }
        Ok(())
    }

    pub(super) fn normal(path: &Path) -> PathBuf {
        let mut out = PathBuf::new();
        for part in path.components() {
            match part {
                std::path::Component::ParentDir => {
                    out.pop();
                }
                std::path::Component::CurDir => {}
                other => out.push(other),
            }
        }
        out
    }

    pub(super) fn inside(root: &Path, path: &Path) -> bool {
        Self::normal(path).starts_with(Self::normal(root))
    }

    pub(super) fn stamp(path: &Path) -> io::Result<Vec<i64>> {
        let meta = std::fs::metadata(path)?;
        Ok(vec![meta.size() as i64, meta.mtime() * 1_000_000_000 + meta.mtime_nsec()])
    }

    /// The folder's shape at the other end.
    pub(super) fn plant(&self, item: usize) -> io::Result<()> {
        let (_, target_root) = self.roots();
        let (dirs, links) =
            self.locked().items.get(item).map_or((Vec::new(), Vec::new()), |row| (row.dirs.clone(), row.links.clone()));
        for rel in dirs {
            std::fs::create_dir_all(target_root.join(rel))?;
        }
        for (rel, target) in links {
            let path = target_root.join(rel);
            if path.exists() || path.is_symlink() {
                continue;
            }
            if let Some(parent) = path.parent() {
                std::fs::create_dir_all(parent)?;
            }
            std::os::unix::fs::symlink(target, path)?;
        }
        Ok(())
    }

    /// The file left a library: what was remembered of its header goes with it.
    pub(super) fn forget_headers(&self, item: usize) {
        let (from_library, id, rels) = {
            let job = self.locked();
            (
                job.source.get("kind").and_then(Value::as_str) == Some("library"),
                Coerce::text(job.source.get("id")),
                job.items.get(item).map_or(Vec::new(), |row| row.files.iter().map(|file| file.rel.clone()).collect()),
            )
        };
        if from_library {
            for rel in rels {
                // A memory that is not written is read again; the file itself is where it should be.
                drop(self.app.library_meta.forget(&id, &rel));
            }
        }
    }
}
